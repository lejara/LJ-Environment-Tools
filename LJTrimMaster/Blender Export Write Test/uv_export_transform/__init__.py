# SPDX-License-Identifier: GPL-3.0-or-later
"""UV Export Transform.

Applies a per-object UV transform *only while an exporter is writing the file*,
then restores the scene UVs exactly. Nothing in the .blend is permanently
changed.

How it hooks in
---------------
FBX and glTF are Python operators, so their ``execute`` is wrapped on register:
a plain File > Export click already goes through the transform.

OBJ / PLY / STL / USD / Alembic are C operators; a menu click on those runs
entirely inside C and cannot be intercepted from Python. For those, use
File > Export > UV-Transformed Export, which applies the transform and then
calls the exporter with EXEC_DEFAULT so the restore runs after the write.

Two ways to apply the transform
-------------------------------
Direct
    Rewrite the base UV map's buffer. Cheap, exact, and independent of the
    exporter's "apply modifiers" setting - but a modifier that generates or
    alters UVs runs *after* it, so the file would carry the modifier's output,
    not ours.

Evaluated
    Append a temporary pair of UVWarp modifiers to the end of the stack, so the
    transform lands after everything else the modifier stack does to the UVs.
    Only reaches the file when the exporter applies modifiers.

See ``_append_uvwarp_pair`` for why it takes *two* modifiers.
"""

import math
import os
from contextlib import contextmanager

import bpy
import numpy as np
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import Menu, Operator, Panel, PropertyGroup, UIList

# ---------------------------------------------------------------------------
# UV transform core
# ---------------------------------------------------------------------------

# Re-entrancy guard. The wrapper operator applies the transform itself and then
# calls the real exporter, which would otherwise trip the execute() hook and
# apply everything a second time.
_depth = 0

MODIFIER_PREFIX = "__uvxf_"


def _uv_layers_for(mesh, entry):
    """Return the UV layers on *mesh* that *entry* targets."""
    if entry.uv_mode == 'ALL':
        return list(mesh.uv_layers)
    if entry.uv_mode == 'NAMED':
        layer = mesh.uv_layers.get(entry.uv_map)
        return [layer] if layer else []
    layer = mesh.uv_layers.active
    return [layer] if layer else []


def _apply_to_layer(layer, entry):
    """Transform *layer* in place. Returns the original buffer for restore.

    Convention: scale, then rotate, then translate - all about the pivot.
    """
    buf = np.empty(len(layer.data) * 2, dtype=np.float32)
    layer.data.foreach_get("uv", buf)
    original = buf.copy()

    uv = buf.reshape(-1, 2)
    px, py = entry.pivot

    uv[:, 0] -= px
    uv[:, 1] -= py

    uv[:, 0] *= entry.scale[0]
    uv[:, 1] *= entry.scale[1]

    if entry.rotation:
        cos_r = math.cos(entry.rotation)
        sin_r = math.sin(entry.rotation)
        x = uv[:, 0].copy()
        uv[:, 0] = x * cos_r - uv[:, 1] * sin_r
        uv[:, 1] = x * sin_r + uv[:, 1] * cos_r

    uv[:, 0] += px + entry.offset[0]
    uv[:, 1] += py + entry.offset[1]

    layer.data.foreach_set("uv", buf)
    return original


def _append_uvwarp_pair(obj, entry, layer_name):
    """Append two UVWarp modifiers that reproduce ``_apply_to_layer`` exactly.

    Measured convention of Blender's UVWarp modifier::

        uv' = S . R . (uv + offset - center) + center

    - the offset is applied *before* the transform, not after
    - rotation is applied *before* scale

    Ours is ``uv' = R . S . (uv - P) + P + O``. A single UVWarp cannot express
    that: matching ``R.S`` against ``S'.R'`` forces sx**2 == sy**2 or a zero
    rotation, so any non-uniform scale combined with a rotation is unreachable.

    Two chained UVWarps do reach it:

        M1: center=P,     offset=0, rotation=0,     scale=S
            -> S.(uv - P) + P
        M2: center=P+O,   offset=O, rotation=theta, scale=1
            -> R.(uv1 + O - (P+O)) + (P+O)  ==  R.(uv1 - P) + P + O

    Returns the modifier names, which is what the caller stores - a modifier
    reference can be invalidated by anything that reshuffles the stack.
    """
    px, py = entry.pivot
    ox, oy = entry.offset

    scale_mod = obj.modifiers.new(name=MODIFIER_PREFIX + "scale", type='UV_WARP')
    scale_mod.uv_layer = layer_name
    scale_mod.center = (px, py)
    scale_mod.offset = (0.0, 0.0)
    scale_mod.rotation = 0.0
    scale_mod.scale = (entry.scale[0], entry.scale[1])

    rot_mod = obj.modifiers.new(name=MODIFIER_PREFIX + "rot", type='UV_WARP')
    rot_mod.uv_layer = layer_name
    rot_mod.center = (px + ox, py + oy)
    rot_mod.offset = (ox, oy)
    rot_mod.rotation = entry.rotation
    rot_mod.scale = (1.0, 1.0)

    return [scale_mod.name, rot_mod.name]


# Modifiers that can generate or rewrite UVs, so a Direct transform of the base
# map would not survive to the file. Subsurf/Multires/Solidify are absent on
# purpose: they interpolate or copy UVs affinely, and an affine transform
# commutes with that, so Direct stays correct through them.
def uv_affecting_modifiers(obj):
    found = []
    for mod in obj.modifiers:
        if not (mod.show_viewport or mod.show_render):
            continue
        kind = mod.type
        if kind in {'UV_WARP', 'UV_PROJECT', 'NODES'}:
            if mod.name.startswith(MODIFIER_PREFIX):
                continue
            found.append(mod)
        elif kind == 'MIRROR':
            if any(getattr(mod, attr, False) for attr in (
                    "use_mirror_u", "use_mirror_v",
                    "mirror_offset_u", "mirror_offset_v",
                    "offset_u", "offset_v")):
                found.append(mod)
        elif kind == 'ARRAY':
            if getattr(mod, "offset_u", 0.0) or getattr(mod, "offset_v", 0.0):
                found.append(mod)
    return found


class Target:
    """One resolved unit of work."""

    __slots__ = ("entry", "obj", "mesh", "layer", "method", "reason")

    def __init__(self, entry, obj, mesh, layer, method, reason=""):
        self.entry = entry
        self.obj = obj
        self.mesh = mesh
        self.layer = layer
        self.method = method
        self.reason = reason


def _resolve_method(entry, obj, apply_modifiers):
    """Decide Direct vs Evaluated for one entry."""
    if entry.method == 'DIRECT':
        return 'DIRECT', ""
    if entry.method == 'EVALUATED':
        return 'EVALUATED', "forced"
    # AUTO
    if apply_modifiers is False:
        # The exporter is writing the base mesh, so the modifier stack never
        # runs and a UVWarp would be silently dropped.
        return 'DIRECT', "exporter is not applying modifiers"
    mods = uv_affecting_modifiers(obj)
    if mods:
        return 'EVALUATED', ", ".join(m.name for m in mods)
    return 'DIRECT', ""


def collect_targets(scene, report=None, apply_modifiers=None):
    """Resolve the entry list into Target objects.

    *apply_modifiers* is what the calling exporter will do with the modifier
    stack: True, False, or None when it cannot be determined (assume True).

    Direct targets are de-duplicated on (mesh datablock, UV layer) so shared
    mesh data is never transformed twice. Evaluated targets are not: modifiers
    are per-object, so two objects sharing a mesh each need their own.
    """
    settings = scene.uv_export_transform
    targets = []
    seen = set()
    for entry in settings.entries:
        if not entry.enabled or entry.obj is None or entry.obj.type != 'MESH':
            continue
        obj = entry.obj
        mesh = obj.data
        if obj.mode == 'EDIT':
            if report:
                report("'%s' is in Edit Mode - skipped" % obj.name)
            continue
        layers = _uv_layers_for(mesh, entry)
        if not layers:
            if report:
                report("'%s' has no matching UV map - skipped" % obj.name)
            continue

        method, reason = _resolve_method(entry, obj, apply_modifiers)
        if method == 'EVALUATED' and apply_modifiers is False:
            if report:
                report(
                    "'%s' needs the evaluated path but this exporter is not "
                    "applying modifiers - the transform will not reach the file"
                    % obj.name
                )

        for layer in layers:
            if method == 'DIRECT':
                key = (mesh.as_pointer(), layer.name)
                if key in seen:
                    if report:
                        report(
                            "'%s'.'%s' already queued via another object "
                            "- skipped" % (mesh.name, layer.name)
                        )
                    continue
                seen.add(key)
            targets.append(Target(entry, obj, mesh, layer, method, reason))
    return targets


def _flush(meshes, objects=()):
    """Push edits into the depsgraph.

    Exporters read the evaluated mesh, so neither a foreach_set on the base
    layer nor a freshly added modifier is visible until the datablocks are
    tagged and the view layer re-evaluated.
    """
    for mesh in meshes:
        mesh.update_tag()
    for obj in objects:
        obj.update_tag()
    if meshes or objects:
        try:
            bpy.context.view_layer.update()
        except AttributeError:
            pass


@contextmanager
def uv_transform_applied(scene, report=None, apply_modifiers=None):
    """Apply every enabled entry, yield, then undo it completely.

    Nested use is a no-op so the wrapper operator and the execute() hook cannot
    double-apply.
    """
    global _depth
    settings = getattr(scene, "uv_export_transform", None)

    if _depth > 0 or settings is None or not settings.enabled:
        yield 0
        return

    _depth += 1
    restores = []
    temp_modifiers = []
    meshes = set()
    objects = set()
    try:
        for target in collect_targets(scene, report, apply_modifiers):
            if target.method == 'DIRECT':
                restores.append(
                    (target.layer, _apply_to_layer(target.layer, target.entry))
                )
                meshes.add(target.mesh)
            else:
                temp_modifiers.extend(
                    (target.obj, name)
                    for name in _append_uvwarp_pair(
                        target.obj, target.entry, target.layer.name
                    )
                )
                objects.add(target.obj)
        _flush(meshes, objects)
        yield len(restores) + len(temp_modifiers) // 2
    finally:
        for obj, name in reversed(temp_modifiers):
            mod = obj.modifiers.get(name)
            if mod is not None:
                obj.modifiers.remove(mod)
        for layer, original in reversed(restores):
            layer.data.foreach_set("uv", original)
        _flush(meshes, objects)
        _depth -= 1


def leftover_modifiers():
    """Any temp modifier still on an object is a leak. Used by the dry run."""
    return [
        (obj.name, mod.name)
        for obj in bpy.data.objects
        if obj.type == 'MESH'
        for mod in obj.modifiers
        if mod.name.startswith(MODIFIER_PREFIX)
    ]


def evaluated_uv_bounds(obj, layer_name):
    """min/max U and V of *layer_name* on the fully evaluated mesh."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        layer = mesh.uv_layers.get(layer_name) or mesh.uv_layers.active
        if layer is None or not len(layer.data):
            return None
        buf = np.empty(len(layer.data) * 2, dtype=np.float32)
        layer.data.foreach_get("uv", buf)
        uv = buf.reshape(-1, 2)
        return (float(uv[:, 0].min()), float(uv[:, 0].max()),
                float(uv[:, 1].min()), float(uv[:, 1].max()))
    finally:
        evaluated.to_mesh_clear()


def base_uv_bounds(layer):
    buf = np.empty(len(layer.data) * 2, dtype=np.float32)
    layer.data.foreach_get("uv", buf)
    uv = buf.reshape(-1, 2)
    return (float(uv[:, 0].min()), float(uv[:, 0].max()),
            float(uv[:, 1].min()), float(uv[:, 1].max()))


# ---------------------------------------------------------------------------
# Exporter hooks
# ---------------------------------------------------------------------------

# Only the Python operators can actually be wrapped; the rest are probed so the
# panel can report why they cannot be.
HOOK_TARGETS = (
    ("export_scene.fbx", "EXPORT_SCENE_OT_fbx", "FBX"),
    ("export_scene.gltf", "EXPORT_SCENE_OT_gltf", "glTF"),
    ("wm.obj_export", "WM_OT_obj_export", "OBJ"),
    ("wm.ply_export", "WM_OT_ply_export", "PLY"),
    ("wm.stl_export", "WM_OT_stl_export", "STL"),
    ("wm.usd_export", "WM_OT_usd_export", "USD"),
    ("wm.alembic_export", "WM_OT_alembic_export", "Alembic"),
)

# Each exporter spells "apply the modifier stack" differently. Exporters absent
# from this table always evaluate the depsgraph (OBJ, USD, Alembic), so None
# there means "assume applied".
APPLY_MODIFIER_PROPS = (
    "use_mesh_modifiers",   # FBX
    "export_apply",         # glTF
    "apply_modifiers",      # PLY / STL
)

_hooked = {}  # class name -> original execute function


def exporter_applies_modifiers(op_instance):
    for name in APPLY_MODIFIER_PROPS:
        if hasattr(op_instance, name):
            return bool(getattr(op_instance, name))
    return None


def _make_wrapper(original):
    def execute(self, context):
        def report(msg):
            self.report({'WARNING'}, "UV Export Transform: " + msg)

        applies = exporter_applies_modifiers(self)
        with uv_transform_applied(context.scene, report, applies) as count:
            if count:
                print("[UV Export Transform] transformed %d UV layer(s)" % count)
            return original(self, context)

    execute._uvxf_original = original
    return execute


def _is_python_execute(func):
    return callable(func) and getattr(func, "__module__", None) is not None


def attach_hooks():
    """Wrap every exporter we can. Returns {label: status} for the UI."""
    status = {}
    for _idname, clsname, label in HOOK_TARGETS:
        cls = getattr(bpy.types, clsname, None)
        if cls is None:
            status[label] = 'UNAVAILABLE'
            continue
        current = getattr(cls, "execute", None)
        if getattr(current, "_uvxf_original", None) is not None:
            status[label] = 'HOOKED'
            continue
        if not _is_python_execute(current):
            status[label] = 'C_OPERATOR'
            continue
        try:
            cls.execute = _make_wrapper(current)
        except (AttributeError, TypeError):
            status[label] = 'C_OPERATOR'
            continue
        _hooked[clsname] = current
        status[label] = 'HOOKED'
    return status


def detach_hooks():
    for clsname, original in list(_hooked.items()):
        cls = getattr(bpy.types, clsname, None)
        if cls is not None:
            if getattr(getattr(cls, "execute", None), "_uvxf_original", None):
                try:
                    cls.execute = original
                except (AttributeError, TypeError):
                    pass
        _hooked.pop(clsname, None)


def hook_status():
    status = {}
    for _idname, clsname, label in HOOK_TARGETS:
        cls = getattr(bpy.types, clsname, None)
        if cls is None:
            status[label] = 'UNAVAILABLE'
            continue
        current = getattr(cls, "execute", None)
        if getattr(current, "_uvxf_original", None) is not None:
            status[label] = 'HOOKED'
        elif not _is_python_execute(current):
            status[label] = 'C_OPERATOR'
        else:
            status[label] = 'UNHOOKED'
    return status


_retries_left = 20


def _attach_timer():
    """Exporter add-ons can be enabled after us; keep trying for a while."""
    global _retries_left
    status = attach_hooks()
    _retries_left -= 1
    core_done = status.get('FBX') == 'HOOKED' and status.get('glTF') == 'HOOKED'
    if core_done or _retries_left <= 0:
        return None
    return 2.0


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------

def _poll_mesh(_self, obj):
    return obj.type == 'MESH'


class UVXF_Entry(PropertyGroup):
    enabled: BoolProperty(
        name="Enabled",
        description="Include this object in the export transform",
        default=True,
    )
    obj: PointerProperty(
        name="Object",
        type=bpy.types.Object,
        poll=_poll_mesh,
    )
    method: EnumProperty(
        name="Method",
        items=(
            ('AUTO', "Auto",
             "Use Evaluated when the object has modifiers that generate or "
             "alter UVs, otherwise Direct"),
            ('DIRECT', "Direct",
             "Rewrite the base UV map. Independent of the exporter's apply-"
             "modifiers setting, but modifiers that touch UVs run after it"),
            ('EVALUATED', "Evaluated",
             "Append temporary UVWarp modifiers so the transform lands after "
             "the whole modifier stack. Only reaches the file when the "
             "exporter applies modifiers"),
        ),
        default='AUTO',
    )
    uv_mode: EnumProperty(
        name="UV Map",
        items=(
            ('ACTIVE', "Active", "The object's active UV map"),
            ('ALL', "All", "Every UV map on the object"),
            ('NAMED', "Named", "One UV map, looked up by name"),
        ),
        default='ACTIVE',
    )
    uv_map: StringProperty(
        name="Name",
        description="UV map to transform when UV Map is set to Named",
    )
    offset: FloatVectorProperty(
        name="Offset",
        description="Translation in UV space, applied after scale and rotation",
        size=2,
        default=(0.0, 0.0),
    )
    scale: FloatVectorProperty(
        name="Scale",
        description="Scale around the pivot",
        size=2,
        default=(1.0, 1.0),
    )
    rotation: FloatProperty(
        name="Rotation",
        description="Rotation around the pivot, applied after scale",
        subtype='ANGLE',
        default=0.0,
    )
    pivot: FloatVectorProperty(
        name="Pivot",
        description="Centre for scale and rotation",
        size=2,
        default=(0.5, 0.5),
    )


class UVXF_Settings(PropertyGroup):
    enabled: BoolProperty(
        name="Transform On Export",
        description="Master switch. When off, exports are completely untouched",
        default=True,
    )
    entries: CollectionProperty(type=UVXF_Entry)
    active_index: IntProperty(default=0)


# ---------------------------------------------------------------------------
# List operators
# ---------------------------------------------------------------------------

class UVXF_OT_add_selected(Operator):
    bl_idname = "uvxf.add_selected"
    bl_label = "Add Selected"
    bl_description = "Add every selected mesh object to the list"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return any(o.type == 'MESH' for o in context.selected_objects)

    def execute(self, context):
        settings = context.scene.uv_export_transform
        existing = {e.obj for e in settings.entries if e.obj}
        added = 0
        for obj in context.selected_objects:
            if obj.type != 'MESH' or obj in existing:
                continue
            entry = settings.entries.add()
            entry.obj = obj
            added += 1
        if added:
            settings.active_index = len(settings.entries) - 1
        self.report({'INFO'}, "Added %d object(s)" % added)
        return {'FINISHED'}


class UVXF_OT_remove(Operator):
    bl_idname = "uvxf.remove"
    bl_label = "Remove"
    bl_description = "Remove the highlighted object from the list"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return len(context.scene.uv_export_transform.entries) > 0

    def execute(self, context):
        settings = context.scene.uv_export_transform
        index = settings.active_index
        if 0 <= index < len(settings.entries):
            settings.entries.remove(index)
            settings.active_index = min(index, len(settings.entries) - 1)
        return {'FINISHED'}


class UVXF_OT_clear(Operator):
    bl_idname = "uvxf.clear"
    bl_label = "Clear List"
    bl_description = "Remove every object from the list"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return len(context.scene.uv_export_transform.entries) > 0

    def execute(self, context):
        context.scene.uv_export_transform.entries.clear()
        context.scene.uv_export_transform.active_index = 0
        return {'FINISHED'}


class UVXF_OT_attach(Operator):
    bl_idname = "uvxf.attach_hooks"
    bl_label = "Re-attach Export Hooks"
    bl_description = (
        "Re-wrap the FBX and glTF exporters. Needed if those add-ons were "
        "enabled or reloaded after this one"
    )

    def execute(self, context):
        status = attach_hooks()
        hooked = [k for k, v in status.items() if v == 'HOOKED']
        self.report({'INFO'}, "Hooked: " + (", ".join(hooked) or "nothing"))
        return {'FINISHED'}


class UVXF_OT_purge_modifiers(Operator):
    bl_idname = "uvxf.purge_modifiers"
    bl_label = "Purge Leftover Modifiers"
    bl_description = (
        "Remove any temporary UVWarp modifiers this add-on left behind. Should "
        "never be needed - the restore runs in a finally block"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, _context):
        removed = 0
        for obj in bpy.data.objects:
            if obj.type != 'MESH':
                continue
            for mod in list(obj.modifiers):
                if mod.name.startswith(MODIFIER_PREFIX):
                    obj.modifiers.remove(mod)
                    removed += 1
        self.report({'INFO'}, "Removed %d leftover modifier(s)" % removed)
        return {'FINISHED'}


class UVXF_OT_dry_run(Operator):
    bl_idname = "uvxf.dry_run"
    bl_label = "Dry Run Check"
    bl_description = (
        "Apply the transform, measure it, then restore - and verify the "
        "restore was bit-exact. Writes no file"
    )

    def execute(self, context):
        scene = context.scene
        warnings = []
        targets = collect_targets(scene, warnings.append, apply_modifiers=True)
        if not targets:
            for msg in warnings:
                self.report({'WARNING'}, msg)
            self.report({'ERROR'}, "Nothing to transform")
            return {'CANCELLED'}

        # Snapshot every base buffer so the restore can be proven bit-exact,
        # including for Evaluated targets, whose base map must not move at all.
        snapshots = {}
        for target in targets:
            key = (target.mesh.as_pointer(), target.layer.name)
            if key in snapshots:
                continue
            buf = np.empty(len(target.layer.data) * 2, dtype=np.float32)
            target.layer.data.foreach_get("uv", buf)
            snapshots[key] = buf

        before = [
            (t, base_uv_bounds(t.layer) if t.method == 'DIRECT'
             else evaluated_uv_bounds(t.obj, t.layer.name))
            for t in targets
        ]

        lines = []
        with uv_transform_applied(scene, apply_modifiers=True):
            for target, src in before:
                if target.method == 'DIRECT':
                    now = base_uv_bounds(target.layer)
                else:
                    now = evaluated_uv_bounds(target.obj, target.layer.name)
                lines.append(
                    "%-22s %-9s U [%.4f, %.4f] -> [%.4f, %.4f]   "
                    "V [%.4f, %.4f] -> [%.4f, %.4f]%s"
                    % (
                        target.obj.name + "." + target.layer.name,
                        target.method.lower(),
                        src[0], src[1], now[0], now[1],
                        src[2], src[3], now[2], now[3],
                        ("  (" + target.reason + ")") if target.reason else "",
                    )
                )

        mismatched = []
        for target in targets:
            key = (target.mesh.as_pointer(), target.layer.name)
            buf = np.empty(len(target.layer.data) * 2, dtype=np.float32)
            target.layer.data.foreach_get("uv", buf)
            if not np.array_equal(buf, snapshots[key]):
                name = "%s.%s" % (target.obj.name, target.layer.name)
                if name not in mismatched:
                    mismatched.append(name)

        leftovers = leftover_modifiers()

        print("[UV Export Transform] dry run")
        for line in lines:
            print("  " + line)
        for msg in warnings:
            print("  warning: " + msg)

        for msg in warnings:
            self.report({'WARNING'}, msg)
        if mismatched:
            self.report({'ERROR'}, "Scene UVs NOT restored: " + ", ".join(mismatched))
            return {'CANCELLED'}
        if leftovers:
            self.report(
                {'ERROR'},
                "Temporary modifiers left behind: "
                + ", ".join("%s/%s" % pair for pair in leftovers),
            )
            return {'CANCELLED'}
        self.report(
            {'INFO'},
            "%d UV layer(s) transformed and fully reverted - see the "
            "System Console for ranges" % len(targets),
        )
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Export wrapper (needed for the C-operator formats)
# ---------------------------------------------------------------------------

FORMATS = (
    ('FBX', "export_scene.fbx", ".fbx", {}),
    ('GLB', "export_scene.gltf", ".glb", {"export_format": 'GLB'}),
    ('GLTF', "export_scene.gltf", ".gltf", {"export_format": 'GLTF_SEPARATE'}),
    ('OBJ', "wm.obj_export", ".obj", {}),
    ('PLY', "wm.ply_export", ".ply", {}),
    ('STL', "wm.stl_export", ".stl", {}),
    ('USD', "wm.usd_export", ".usd", {}),
    ('ABC', "wm.alembic_export", ".abc", {}),
)

FORMAT_MAP = {f[0]: f[1:] for f in FORMATS}

# Every exporter spells "selection only" differently.
SELECTION_ARGS = (
    "use_selection",
    "export_selected_objects",
    "selected_objects_only",
    "selected",
)


def _resolve_op(idname):
    module, _, func = idname.partition(".")
    return getattr(getattr(bpy.ops, module), func)


class UVXF_OT_export(Operator):
    bl_idname = "uvxf.export"
    bl_label = "Export (UV Transform)"
    bl_description = (
        "Apply the UV transform, run the chosen exporter, then restore. Use "
        "this for OBJ/PLY/STL/USD/Alembic, which cannot be hooked from Python"
    )
    bl_options = {'REGISTER'}

    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default="*.*", options={'HIDDEN'})
    fmt: EnumProperty(
        name="Format",
        items=(
            ('FBX', "FBX (.fbx)", ""),
            ('GLB', "glTF Binary (.glb)", ""),
            ('GLTF', "glTF Separate (.gltf)", ""),
            ('OBJ', "Wavefront (.obj)", ""),
            ('PLY', "Stanford (.ply)", ""),
            ('STL', "STL (.stl)", ""),
            ('USD', "USD (.usd)", ""),
            ('ABC', "Alembic (.abc)", ""),
        ),
        default='FBX',
    )
    use_selection: BoolProperty(name="Selected Objects Only", default=False)
    apply_modifiers: BoolProperty(
        name="Apply Modifiers",
        description=(
            "Pass through to the exporter where it has such a setting. Also "
            "tells the Auto method whether the evaluated path can work"
        ),
        default=True,
    )

    def invoke(self, context, event):
        _idname, ext, _kwargs = FORMAT_MAP[self.fmt]
        self.filter_glob = "*" + ext
        blend = bpy.data.filepath
        stem = os.path.splitext(os.path.basename(blend))[0] if blend else "untitled"
        directory = os.path.dirname(blend) or os.path.expanduser("~")
        self.filepath = os.path.join(directory, stem + ext)
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "use_selection")
        layout.prop(self, "apply_modifiers")
        layout.prop(context.scene.uv_export_transform, "enabled",
                    text="Apply UV Transform")

    def execute(self, context):
        idname, ext, kwargs = FORMAT_MAP[self.fmt]
        try:
            op = _resolve_op(idname)
            valid = set(op.get_rna_type().properties.keys())
        except (AttributeError, RuntimeError):
            self.report({'ERROR'}, "'%s' is unavailable - enable its add-on" % idname)
            return {'CANCELLED'}

        filepath = self.filepath
        if not filepath.lower().endswith(ext):
            filepath += ext

        call_kwargs = {"filepath": filepath}
        call_kwargs.update({k: v for k, v in kwargs.items() if k in valid})
        if self.use_selection:
            for name in SELECTION_ARGS:
                if name in valid:
                    call_kwargs[name] = True
                    break

        # Mirror the apply-modifiers choice into the exporter where it exists,
        # so the Auto method's assumption matches what actually happens.
        applies = None
        for name in APPLY_MODIFIER_PROPS:
            if name in valid:
                call_kwargs[name] = self.apply_modifiers
                applies = self.apply_modifiers
                break

        warnings = []
        # EXEC_DEFAULT: the exporter writes inline, so the restore in the
        # context manager's finally runs strictly after the file is on disk.
        with uv_transform_applied(context.scene, warnings.append, applies) as count:
            result = op('EXEC_DEFAULT', **call_kwargs)

        for msg in warnings:
            self.report({'WARNING'}, msg)
        if 'FINISHED' in result:
            self.report(
                {'INFO'},
                "Exported %s with %d transformed UV layer(s)"
                % (os.path.basename(filepath), count),
            )
        return result


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

class UVXF_UL_entries(UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active, _prop):
        row = layout.row(align=True)
        row.prop(item, "enabled", text="")
        if item.obj:
            icon = 'MODIFIER' if (
                item.method == 'EVALUATED'
                or (item.method == 'AUTO' and uv_affecting_modifiers(item.obj))
            ) else 'OUTLINER_OB_MESH'
            row.label(text=item.obj.name, icon=icon)
        else:
            row.label(text="(no object)", icon='ERROR')
        sub = row.row(align=True)
        sub.alignment = 'RIGHT'
        sub.label(text="%+.2f, %+.2f" % (item.offset[0], item.offset[1]))


class UVXF_MT_export(Menu):
    bl_idname = "UVXF_MT_export"
    bl_label = "UV-Transformed Export"

    def draw(self, _context):
        layout = self.layout
        for identifier, _idname, ext, _kwargs in FORMATS:
            op = layout.operator(
                UVXF_OT_export.bl_idname, text="%s (%s)" % (identifier, ext)
            )
            op.fmt = identifier


def _file_export_menu(self, _context):
    self.layout.menu(UVXF_MT_export.bl_idname, icon='UV')


class UVXF_PT_panel(Panel):
    bl_label = "UV Export Transform"
    bl_idname = "UVXF_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "UV Export"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.uv_export_transform

        header = layout.row()
        header.scale_y = 1.2
        header.prop(settings, "enabled", toggle=True,
                    icon='CHECKMARK' if settings.enabled else 'X')

        row = layout.row()
        row.template_list(
            "UVXF_UL_entries", "", settings, "entries",
            settings, "active_index", rows=4,
        )
        col = row.column(align=True)
        col.operator(UVXF_OT_add_selected.bl_idname, icon='ADD', text="")
        col.operator(UVXF_OT_remove.bl_idname, icon='REMOVE', text="")
        col.separator()
        col.operator(UVXF_OT_clear.bl_idname, icon='TRASH', text="")

        entries = settings.entries
        index = settings.active_index
        if 0 <= index < len(entries):
            entry = entries[index]
            box = layout.box()
            box.prop(entry, "obj", text="Object")

            box.row(align=True).prop(entry, "uv_mode", expand=True)
            if entry.uv_mode == 'NAMED':
                if entry.obj:
                    box.prop_search(
                        entry, "uv_map", entry.obj.data, "uv_layers", text="Name"
                    )
                else:
                    box.prop(entry, "uv_map")

            box.column(align=True).prop(entry, "offset")
            box.column(align=True).prop(entry, "scale")
            box.prop(entry, "rotation")
            box.column(align=True).prop(entry, "pivot")

            box.separator()
            box.prop(entry, "method")
            if entry.obj:
                mods = uv_affecting_modifiers(entry.obj)
                if entry.method == 'AUTO':
                    if mods:
                        sub = box.column(align=True)
                        sub.label(text="Auto: Evaluated", icon='MODIFIER')
                        sub.label(
                            text="UVs touched by: "
                                 + ", ".join(m.name for m in mods)[:40],
                            icon='BLANK1',
                        )
                    else:
                        box.label(text="Auto: Direct", icon='CHECKMARK')
                elif entry.method == 'DIRECT' and mods:
                    box.label(
                        text="Modifiers rewrite these UVs",
                        icon='ERROR',
                    )
                if entry.method != 'DIRECT' and (mods or entry.method == 'EVALUATED'):
                    box.label(
                        text="Needs the exporter to apply modifiers",
                        icon='INFO',
                    )
        else:
            layout.label(text="Select objects, then press +", icon='INFO')

        layout.separator()
        layout.operator(UVXF_OT_dry_run.bl_idname, icon='CHECKMARK')
        layout.menu(UVXF_MT_export.bl_idname, icon='EXPORT')


class UVXF_PT_hooks(Panel):
    bl_label = "Export Hooks"
    bl_idname = "UVXF_PT_hooks"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "UV Export"
    bl_parent_id = "UVXF_PT_panel"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, _context):
        layout = self.layout
        layout.label(text="File > Export is transparent for:")
        col = layout.column(align=True)
        for label, state in hook_status().items():
            row = col.row()
            if state == 'HOOKED':
                row.label(text=label, icon='CHECKMARK')
            elif state == 'C_OPERATOR':
                row.label(text=label + " - use the menu above", icon='INFO')
            elif state == 'UNAVAILABLE':
                row.label(text=label + " - add-on disabled", icon='BLANK1')
            else:
                row.label(text=label + " - not hooked", icon='ERROR')
        layout.operator(UVXF_OT_attach.bl_idname, icon='FILE_REFRESH')

        leftovers = leftover_modifiers()
        if leftovers:
            box = layout.box()
            box.label(
                text="%d leftover temp modifier(s)" % len(leftovers),
                icon='ERROR',
            )
            box.operator(UVXF_OT_purge_modifiers.bl_idname, icon='TRASH')


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

classes = (
    UVXF_Entry,
    UVXF_Settings,
    UVXF_OT_add_selected,
    UVXF_OT_remove,
    UVXF_OT_clear,
    UVXF_OT_attach,
    UVXF_OT_purge_modifiers,
    UVXF_OT_dry_run,
    UVXF_OT_export,
    UVXF_UL_entries,
    UVXF_MT_export,
    UVXF_PT_panel,
    UVXF_PT_hooks,
)


def register():
    global _retries_left
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.uv_export_transform = PointerProperty(type=UVXF_Settings)
    bpy.types.TOPBAR_MT_file_export.append(_file_export_menu)

    attach_hooks()
    _retries_left = 20
    if not bpy.app.timers.is_registered(_attach_timer):
        bpy.app.timers.register(_attach_timer, first_interval=1.0)


def unregister():
    detach_hooks()
    if bpy.app.timers.is_registered(_attach_timer):
        bpy.app.timers.unregister(_attach_timer)

    bpy.types.TOPBAR_MT_file_export.remove(_file_export_menu)
    del bpy.types.Scene.uv_export_transform
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
