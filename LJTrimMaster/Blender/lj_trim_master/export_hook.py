# SPDX-License-Identifier: GPL-3.0-or-later
"""Transforms UVs into sheet space **only inside the exported file**.

Lifted from the ``Blender Export Write Test`` extension and specialized: instead
of a hand-built object list with manual offset/scale/rotation, it walks material
slots on assigned meshes, derives each slot's affine fresh from
``projectData.json``, and applies it **masked by ``material_index``** so several
trims can share one mesh and one UV layer.

Everything else transfers as proven there: the ``execute`` wrap on the Python
exporters, the ``finally`` restore, dedup on ``(mesh, layer)``, the depsgraph
flush, the Edit Mode skip, the leftover-modifier purge, and ``hook_status``.

Which path applies
------------------

=========================================  =========================================
single trim, no UV-affecting modifier      Direct
single trim + UV-affecting modifier        Evaluated (two chained UVWarps)
multi-trim, no UV modifier                 Direct, masked per slot
**multi-trim + UV-affecting modifier**     **unsupported - reported, never guessed**
=========================================  =========================================

The evaluated path cannot mask per slot: UVWarp filters by vertex group, and a
vertex on a slot boundary belongs to both groups. So a mesh with two trims and a
modifier that rewrites UVs is refused outright rather than exported half right.

Silent failure is the one unacceptable outcome
----------------------------------------------
An unresolvable ``trim_id``, a **hidden** trim, a mesh in Edit Mode, an
unreadable ``projectData.json``, or the unsupported case above are all
**reported loudly** and skipped. Nothing is ever written with untransformed UVs
and no warning.

A hidden trim is refused rather than transformed because the tool's exporter
skips it too - its region of the sheet PNG is empty, so there is nothing there
to map onto.
"""

import os
from contextlib import contextmanager

import bpy
import numpy as np
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy.types import Menu, Operator

from . import assignment, settings, sidecar
from .uv_transform import TrimAffine, is_degenerate

MODIFIER_PREFIX = "__ljtm_"

#: Re-entrancy guard. ``ljtm.export`` applies the transform itself and then calls
#: a real exporter, which would otherwise trip the ``execute`` hook and apply
#: everything twice.
_depth = 0


# ---------------------------------------------------------------------------
# Modifier classification
# ---------------------------------------------------------------------------

def uv_affecting_modifiers(obj):
    """Modifiers that generate or rewrite UVs, so a Direct edit would not survive.

    Subsurf, Multires and Solidify are deliberately absent: they interpolate or
    copy UVs affinely, and an affine transform commutes with that, so Direct
    stays correct through them.
    """
    found = []
    for mod in obj.modifiers:
        if not (mod.show_viewport or mod.show_render):
            continue
        if mod.name.startswith(MODIFIER_PREFIX):
            continue
        if mod.type in {'UV_WARP', 'UV_PROJECT', 'NODES'}:
            found.append(mod)
        elif mod.type == 'MIRROR':
            if any(getattr(mod, attr, False) for attr in (
                    "use_mirror_u", "use_mirror_v",
                    "mirror_offset_u", "mirror_offset_v",
                    "offset_u", "offset_v")):
                found.append(mod)
        elif mod.type == 'ARRAY':
            if getattr(mod, "offset_u", 0.0) or getattr(mod, "offset_v", 0.0):
                found.append(mod)
    return found


def target_uv_layer(mesh):
    """The UV layer a trim transform lands on.

    The render layer, because that is the one a material samples and therefore
    the one the sheet has to line up with. Falls back to the active layer.
    """
    for layer in mesh.uv_layers:
        if layer.active_render:
            return layer
    return mesh.uv_layers.active


# ---------------------------------------------------------------------------
# Per-slot loop mask
# ---------------------------------------------------------------------------

def _loop_totals(mesh):
    count = len(mesh.polygons)
    totals = np.empty(count, dtype=np.int32)
    try:
        mesh.polygons.foreach_get("loop_total", totals)
        return totals
    except (AttributeError, RuntimeError, TypeError):
        # Derivable from loop_start, since a face's loops are contiguous and
        # faces are stored in order. Guards a future Blender dropping the field.
        starts = np.empty(count, dtype=np.int32)
        mesh.polygons.foreach_get("loop_start", starts)
        totals[:-1] = np.diff(starts)
        totals[-1] = len(mesh.loops) - starts[-1]
        return totals


def loop_slot_mask(mesh, slot_index):
    """Boolean mask over ``mesh.loops`` selecting one material slot's faces.

    ``material_index`` is per face and UVs are per loop, so the face index of
    every loop is rebuilt by repeating each face index ``loop_total`` times -
    valid because ``loop_start`` is cumulative.
    """
    face_count = len(mesh.polygons)
    if face_count == 0 or len(mesh.loops) == 0:
        return None
    material_index = np.empty(face_count, dtype=np.int32)
    mesh.polygons.foreach_get("material_index", material_index)
    if not np.any(material_index == slot_index):
        return None
    face_of_loop = np.repeat(np.arange(face_count, dtype=np.int32), _loop_totals(mesh))
    return material_index[face_of_loop] == slot_index


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------

class DirectTarget:
    """One slot's masked affine on one UV layer."""

    __slots__ = ("obj", "mesh", "layer", "slot_index", "matrix", "mask", "record", "item")

    def __init__(self, obj, mesh, layer, slot_index, matrix, mask, record, item):
        self.obj = obj
        self.mesh = mesh
        self.layer = layer
        self.slot_index = slot_index
        self.matrix = matrix
        self.mask = mask
        self.record = record
        self.item = item


class EvaluatedTarget:
    """One object's whole-layer affine, as a temporary UVWarp pair."""

    __slots__ = ("obj", "mesh", "layer", "matrix", "record", "item")

    def __init__(self, obj, mesh, layer, matrix, record, item):
        self.obj = obj
        self.mesh = mesh
        self.layer = layer
        self.matrix = matrix
        self.record = record
        self.item = item


class Plan:
    """What one export will do, plus everything worth telling the user."""

    __slots__ = ("direct", "evaluated", "problems", "object_names", "selection_only")

    def __init__(self):
        self.direct = []
        self.evaluated = []
        self.problems = []
        self.object_names = []
        self.selection_only = False

    @property
    def count(self):
        return len(self.direct) + len(self.evaluated)

    @property
    def marks(self):
        """``(mesh, record, item)`` for every slot this export makes correct."""
        return [(t.mesh, t.record, t.item) for t in self.direct + self.evaluated]

    @property
    def meshes(self):
        seen = {}
        for target in self.direct + self.evaluated:
            seen.setdefault(target.mesh.as_pointer(), target.mesh)
        return list(seen.values())


def collect(context, report=None, apply_modifiers=None, selection_only=False):
    """Resolve every assignment in the scene into a :class:`Plan`.

    *apply_modifiers* is what the calling exporter will do with the modifier
    stack: True, False, or None when it cannot be determined (assume True).
    *selection_only* restricts the plan to selected objects, matching an
    exporter that is only writing the selection - otherwise a hidden object's
    UVs would be transformed and its record marked exported for a file it is
    not in.
    """
    plan = Plan()
    plan.selection_only = selection_only

    def problem(message):
        plan.problems.append(message)
        if report:
            report(message)

    snapshot = settings.snapshot(context, force=True)
    config = settings.settings(context)
    if config is None:
        return plan

    # The registry is the source of truth for what gets transformed. A mesh the
    # user never added, or a slot they never added, is deliberately untouched -
    # opt-in is the whole point, and an unlisted slot is not a silent failure
    # because nothing ever claimed it would be transformed.
    #
    # Deduped by mesh: rows sharing a mesh carry the same assignment by
    # construction, so transforming twice would be double work and a doubled
    # warning.
    rows = []
    handled = set()
    for entry in config.meshes:
        obj = entry.obj
        mesh = assignment.mesh_of(entry)
        if obj is None or mesh is None:
            if obj is None:
                problem("A registered mesh is missing - its row has no object")
            continue
        # Deleted with X, or unlinked by hand. The pointer is still live because
        # this registry is a user of it, so the row has to be recognised here
        # rather than by the None check above - and it has to be recognised
        # BEFORE `select_get`, which raises for an object that is not in the
        # view layer. Nothing would export it in any case.
        if not obj.users_scene:
            problem("'%s' is registered but not in the scene - nothing will "
                    "export it" % obj.name)
            continue
        if selection_only and not obj.select_get():
            continue
        if mesh.as_pointer() in handled:
            continue
        handled.add(mesh.as_pointer())
        rows.append((obj, mesh, [slot for slot in entry.slots if slot.trim_id]))

    plan.object_names = [obj.name for obj, _mesh, _slots in rows]

    # (mesh, layer, slot) already queued.
    seen = set()

    for obj, mesh, records in rows:
        if not records:
            continue

        if snapshot is None:
            problem(
                "'%s' has %d assigned slot(s) but projectData.json could not be "
                "read - UVs left untransformed" % (obj.name, len(records))
            )
            continue

        if obj.mode == 'EDIT':
            # BMesh owns the UV data in Edit Mode and would overwrite the change
            # on mode exit, so the write would not reach the file reliably.
            problem("'%s' is in Edit Mode - skipped, UVs left untransformed" % obj.name)
            continue

        layer = target_uv_layer(mesh)
        if layer is None:
            problem("'%s' has no UV map - skipped" % obj.name)
            continue

        resolved = []
        for record in records:
            item = snapshot.find_trim(record.trim_id)
            if item is None:
                problem(
                    "'%s' slot %d: missing trim link (was: %s%s) - skipped, UVs "
                    "left untransformed"
                    % (
                        obj.name,
                        record.slot_index,
                        record.asset_base_name or record.trim_id[:8],
                        " on " + record.sheet_name if record.sheet_name else "",
                    )
                )
                continue
            if not item.visible:
                problem(
                    "'%s' slot %d: trim '%s' is hidden in LJ Trim Master, so it "
                    "is not on '%s' - skipped, UVs left untransformed. Show it "
                    "in the tool, or pick a different trim image"
                    % (obj.name, record.slot_index, item.label, item.sheet.name)
                )
                continue
            resolved.append((record, item))
        if not resolved:
            continue

        modifiers = uv_affecting_modifiers(obj) if apply_modifiers is not False else []

        if modifiers and len(resolved) > 1:
            problem(
                "'%s' has %d trims AND UV-affecting modifier(s) (%s) - "
                "unsupported, skipped. A UVWarp cannot be masked per material "
                "slot, so there is no correct result to pick"
                % (obj.name, len(resolved), ", ".join(m.name for m in modifiers))
            )
            continue

        for record, item in resolved:
            matrix = TrimAffine.from_trim(
                item.position, item.scale, item.rotation, item.crop,
                item.sheet.resolution,
            )
            if is_degenerate(item.scale, item.sheet.resolution):
                problem(
                    "'%s' slot %d: trim '%s' is scaled below half a pixel on "
                    "'%s' - it contributes no sheet pixels"
                    % (obj.name, record.slot_index, item.label, item.sheet.name)
                )

            if modifiers:
                if matrix.is_singular:
                    problem(
                        "'%s': trim '%s' collapses to a line, so it cannot be "
                        "expressed as UVWarp modifiers - skipped"
                        % (obj.name, item.label)
                    )
                    continue
                used = _slots_with_faces(mesh)
                if len(used) > 1:
                    problem(
                        "'%s' needs the evaluated path, which transforms the "
                        "whole UV layer - slots %s have faces but no trim and "
                        "will move too"
                        % (obj.name, sorted(used - {record.slot_index}))
                    )
                plan.evaluated.append(
                    EvaluatedTarget(obj, mesh, layer, matrix, record, item)
                )
                continue

            mask = loop_slot_mask(mesh, record.slot_index)
            if mask is None:
                problem(
                    "'%s' slot %d ('%s') has no faces - nothing to transform"
                    % (obj.name, record.slot_index, record.material_name or "no material")
                )
                continue

            key = (mesh.as_pointer(), layer.name, record.slot_index)
            if key in seen:
                continue
            seen.add(key)
            plan.direct.append(
                DirectTarget(obj, mesh, layer, record.slot_index, matrix, mask, record, item)
            )

    return plan


def _slots_with_faces(mesh):
    if not len(mesh.polygons):
        return set()
    material_index = np.empty(len(mesh.polygons), dtype=np.int32)
    mesh.polygons.foreach_get("material_index", material_index)
    return set(int(value) for value in np.unique(material_index))


# ---------------------------------------------------------------------------
# Applying
# ---------------------------------------------------------------------------

def _apply_direct(layer, targets):
    """Transform each target's masked slice. Returns the buffer for restore."""
    buffer = np.empty(len(layer.data) * 2, dtype=np.float32)
    layer.data.foreach_get("uv", buffer)
    original = buffer.copy()

    uv = buffer.reshape(-1, 2)
    for target in targets:
        mask = target.mask
        # Fancy indexing copies, so u and v are read before either is written.
        u = uv[mask, 0]
        v = uv[mask, 1]
        matrix = target.matrix
        uv[mask, 0] = matrix.m00 * u + matrix.m01 * v + matrix.m02
        uv[mask, 1] = matrix.m10 * u + matrix.m11 * v + matrix.m12

    layer.data.foreach_set("uv", buffer)
    return original


def _append_uvwarp_pair(target):
    """Two temporary UVWarp modifiers reproducing ``target.matrix`` exactly.

    See ``TrimAffine.uvwarp_pair`` for why it takes two, and for why a mirrored
    trim works. Returns the modifier *names* - a reference can be invalidated by
    anything that reshuffles the stack.
    """
    names = []
    for index, stage in enumerate(target.matrix.uvwarp_pair()):
        mod = target.obj.modifiers.new(
            name="%s%d" % (MODIFIER_PREFIX, index), type='UV_WARP'
        )
        mod.uv_layer = target.layer.name
        mod.center = stage.center
        mod.offset = stage.offset
        mod.rotation = stage.rotation
        mod.scale = stage.scale
        names.append(mod.name)
    return names


def _flush(meshes, objects=()):
    """Push edits into the depsgraph - exporters read the *evaluated* mesh."""
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
def uv_transform_applied(context, report=None, apply_modifiers=None, selection_only=False):
    """Apply every assignment, yield the :class:`Plan`, then undo it completely.

    Nested use yields None so the wrapper operator and the ``execute`` hook
    cannot double-apply.
    """
    global _depth

    if _depth > 0 or not settings.is_enabled(context):
        yield None
        return

    _depth += 1
    restores = []
    temp_modifiers = []
    meshes = set()
    objects = set()
    plan = None
    try:
        plan = collect(context, report, apply_modifiers, selection_only)

        by_layer = {}
        for target in plan.direct:
            by_layer.setdefault(
                (target.mesh.as_pointer(), target.layer.name), (target.layer, [])
            )[1].append(target)
        for layer, targets in by_layer.values():
            restores.append((layer, _apply_direct(layer, targets)))
            meshes.add(targets[0].mesh)

        for target in plan.evaluated:
            temp_modifiers.extend(
                (target.obj, name) for name in _append_uvwarp_pair(target)
            )
            objects.add(target.obj)

        _flush(meshes, objects)
        yield plan
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
    """Any temp modifier still on an object is a leak. Surfaced by the panel."""
    return [
        (obj.name, mod.name)
        for obj in bpy.data.objects
        if obj.type == 'MESH'
        for mod in obj.modifiers
        if mod.name.startswith(MODIFIER_PREFIX)
    ]


# ---------------------------------------------------------------------------
# Committing the informational record
# ---------------------------------------------------------------------------

def commit(context, plan):
    """Record that these slots are now correct in a written file.

    Informational only: if it is wrong or missing the *export* is still correct,
    because the affine is derived fresh every time. A bad record can only
    produce a wrong list, never wrong UVs.

    Every export path lands here, so exporting by hand through ``File > Export``
    clears the entry exactly as anything else would.
    """
    if plan is None or not plan.count:
        return
    for _mesh, slot, item in plan.marks:
        assignment.mark_exported(slot, item)
    assignment.write_all_mirrors(context)
    sidecar.write_for_scene(context)


# ---------------------------------------------------------------------------
# Exporter hooks
# ---------------------------------------------------------------------------

#: Only the Python operators can be wrapped. The C ones are probed anyway so the
#: panel can say *why* they cannot be, rather than looking broken.
HOOK_TARGETS = (
    ("export_scene.fbx", "EXPORT_SCENE_OT_fbx", "FBX"),
    ("export_scene.gltf", "EXPORT_SCENE_OT_gltf", "glTF"),
    ("wm.obj_export", "WM_OT_obj_export", "OBJ"),
    ("wm.ply_export", "WM_OT_ply_export", "PLY"),
    ("wm.stl_export", "WM_OT_stl_export", "STL"),
    ("wm.usd_export", "WM_OT_usd_export", "USD"),
    ("wm.alembic_export", "WM_OT_alembic_export", "Alembic"),
)

#: Each exporter spells "apply the modifier stack" differently. Exporters absent
#: from this table always evaluate the depsgraph (OBJ, USD, Alembic), so None
#: there means "assume applied".
APPLY_MODIFIER_PROPS = (
    "use_mesh_modifiers",   # FBX
    "export_apply",         # glTF
    "apply_modifiers",      # PLY / STL
)

#: And each spells "selection only" differently too.
SELECTION_PROPS = (
    "use_selection",
    "export_selected_objects",
    "selected_objects_only",
    "selected",
)

_hooked = {}  # class name -> original execute


def exporter_applies_modifiers(operator):
    for name in APPLY_MODIFIER_PROPS:
        if hasattr(operator, name):
            return bool(getattr(operator, name))
    return None


def exporter_uses_selection(operator):
    for name in SELECTION_PROPS:
        if hasattr(operator, name):
            return bool(getattr(operator, name))
    return False


def _make_wrapper(original, idname):
    def execute(self, context):
        def report(message):
            self.report({'WARNING'}, "LJ Trim Master: " + message)

        applies = exporter_applies_modifiers(self)
        selection_only = exporter_uses_selection(self)

        with uv_transform_applied(context, report, applies, selection_only) as plan:
            if plan is not None and plan.count:
                print("[LJ Trim Master] transformed %d slot(s) for %s"
                      % (plan.count, idname))
            result = original(self, context)

        if plan is not None and 'FINISHED' in result:
            commit(context, plan)
        return result

    execute._ljtm_original = original
    return execute


def _is_python_execute(func):
    return callable(func) and getattr(func, "__module__", None) is not None


def _operator_exists(idname):
    """Is *idname* a real operator in this build?

    This question must go through ``bpy.ops``. ``bpy.types`` carries operator
    classes **defined in Python** and nothing else, so
    ``getattr(bpy.types, "WM_OT_obj_export")`` is None for an exporter that is
    present, callable, and shipped in every build. Asking ``bpy.types`` first is
    how OBJ, PLY, STL, USD and Alembic all came to be reported as "add-on
    disabled" - the one status that tells the user there is nothing here to
    worry about, when in fact ``File > Export > Wavefront`` writes untransformed
    UVs and the panel is the only thing that can warn them.

    Verified on 5.1.2, per target: ``bpy.types`` False, ``bpy.ops`` present,
    ``get_rna_type()`` OK.

    ``get_rna_type`` is the probe rather than ``hasattr`` because attribute
    access on ``bpy.ops`` never fails - both the submodule and the operator
    handle are manufactured on demand, so ``bpy.ops.wm.nonsense`` is a live
    object. ``get_rna_type()`` raises ``KeyError`` for it and returns a type for
    a real one.
    """
    module, _, func = idname.partition(".")
    submodule = getattr(bpy.ops, module, None)
    operator = getattr(submodule, func, None) if submodule is not None else None
    if operator is None:
        return False
    try:
        return operator.get_rna_type() is not None
    except (AttributeError, KeyError, RuntimeError, TypeError):
        return False


def _classify(idname, clsname):
    """``(status, cls, execute)`` for one hook target. Changes nothing.

    ``cls`` and ``execute`` are None unless the status is ``UNHOOKED``, which is
    the only state ``attach_hooks`` can act on.
    """
    if not _operator_exists(idname):
        return ('UNAVAILABLE', None, None)
    cls = getattr(bpy.types, clsname, None)
    if cls is None:
        # Present and callable, but implemented in C: there is no Python class
        # to wrap. Exactly the case the old bpy.types probe mislabelled.
        return ('C_OPERATOR', None, None)
    current = getattr(cls, "execute", None)
    if getattr(current, "_ljtm_original", None) is not None:
        return ('HOOKED', cls, current)
    if not _is_python_execute(current):
        return ('C_OPERATOR', cls, current)
    return ('UNHOOKED', cls, current)


def attach_hooks():
    """Wrap every exporter we can. Returns ``{label: status}`` for the UI."""
    status = {}
    for idname, clsname, label in HOOK_TARGETS:
        state, cls, current = _classify(idname, clsname)
        if state != 'UNHOOKED':
            status[label] = state
            continue
        try:
            cls.execute = _make_wrapper(current, idname)
        except (AttributeError, TypeError):
            status[label] = 'C_OPERATOR'
            continue
        _hooked[clsname] = current
        status[label] = 'HOOKED'
    return status


def detach_hooks():
    for clsname, original in list(_hooked.items()):
        cls = getattr(bpy.types, clsname, None)
        if cls is not None and getattr(getattr(cls, "execute", None), "_ljtm_original", None):
            try:
                cls.execute = original
            except (AttributeError, TypeError):
                pass
        _hooked.pop(clsname, None)


def hook_status():
    status = {}
    for idname, clsname, label in HOOK_TARGETS:
        status[label] = _classify(idname, clsname)[0]
    return status


_retries_left = 20


def _attach_timer():
    """Exporter add-ons can be enabled after us; keep trying for a while."""
    global _retries_left
    status = attach_hooks()
    _retries_left -= 1
    if (status.get('FBX') == 'HOOKED' and status.get('glTF') == 'HOOKED') or _retries_left <= 0:
        return None
    return 2.0


# ---------------------------------------------------------------------------
# The explicit operator, for the formats Python cannot intercept
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

FORMAT_MAP = {entry[0]: entry[1:] for entry in FORMATS}


def _resolve_op(idname):
    module, _, func = idname.partition(".")
    return getattr(getattr(bpy.ops, module), func)


class LJTM_OT_export(Operator):
    bl_idname = "ljtm.export"
    bl_label = "Export (Trim-Synced)"
    bl_description = (
        "Apply the trim UV transform, run the chosen exporter, then restore. "
        "Needed for OBJ/PLY/STL/USD/Alembic, which are C operators and cannot "
        "be hooked from Python. FBX and glTF do not need this - File > Export "
        "is already transparent for them"
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
            "Passed through to the exporter where it has such a setting. Also "
            "decides whether the evaluated path can reach the file"
        ),
        default=True,
    )

    def invoke(self, context, _event):
        _idname, extension, _kwargs = FORMAT_MAP[self.fmt]
        self.filter_glob = "*" + extension
        blend = bpy.data.filepath
        stem = os.path.splitext(os.path.basename(blend))[0] if blend else "untitled"
        folder = os.path.dirname(blend) or os.path.expanduser("~")
        self.filepath = os.path.join(folder, stem + extension)
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "use_selection")
        layout.prop(self, "apply_modifiers")
        config = settings.settings(context)
        if config:
            layout.prop(config, "enabled", text="Apply Trim UV Transform")

    def execute(self, context):
        idname, extension, kwargs = FORMAT_MAP[self.fmt]
        try:
            operator = _resolve_op(idname)
            valid = set(operator.get_rna_type().properties.keys())
        except (AttributeError, RuntimeError):
            self.report({'ERROR'}, "'%s' is unavailable - enable its add-on" % idname)
            return {'CANCELLED'}

        filepath = self.filepath
        if not filepath.lower().endswith(extension):
            filepath += extension

        call_kwargs = {"filepath": filepath}
        call_kwargs.update({k: v for k, v in kwargs.items() if k in valid})
        if self.use_selection:
            for name in SELECTION_PROPS:
                if name in valid:
                    call_kwargs[name] = True
                    break

        applies = None
        for name in APPLY_MODIFIER_PROPS:
            if name in valid:
                call_kwargs[name] = self.apply_modifiers
                applies = self.apply_modifiers
                break

        warnings = []
        # EXEC_DEFAULT: the exporter writes inline, so the restore in the
        # context manager's finally runs strictly after the file is on disk.
        with uv_transform_applied(
            context, warnings.append, applies, self.use_selection
        ) as plan:
            result = operator('EXEC_DEFAULT', **call_kwargs)

        if plan is not None and 'FINISHED' in result:
            commit(context, plan)

        for message in warnings:
            self.report({'WARNING'}, message)
        if 'FINISHED' in result:
            self.report(
                {'INFO'},
                "Exported %s with %d transformed slot(s)"
                % (os.path.basename(filepath), plan.count if plan else 0),
            )
        return result


class LJTM_MT_export(Menu):
    bl_idname = "LJTM_MT_export"
    bl_label = "Trim-Synced Export"

    def draw(self, _context):
        layout = self.layout
        for identifier, _idname, extension, _kwargs in FORMATS:
            entry = layout.operator(
                LJTM_OT_export.bl_idname, text="%s (%s)" % (identifier, extension)
            )
            entry.fmt = identifier


def file_export_menu(self, _context):
    self.layout.menu(LJTM_MT_export.bl_idname, icon='UV')


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

class LJTM_OT_dry_run(Operator):
    bl_idname = "ljtm.dry_run"
    bl_label = "Dry Run Check"
    bl_description = (
        "Apply every trim transform, measure it, restore - and verify the "
        "restore was bit-exact. Writes no file"
    )

    def execute(self, context):
        warnings = []
        before = {}
        snapshots = {}

        plan = collect(context, warnings.append, apply_modifiers=True)
        if not plan.count:
            for message in warnings:
                self.report({'WARNING'}, message)
            self.report({'ERROR'}, "Nothing to transform")
            return {'CANCELLED'}

        for target in plan.direct + plan.evaluated:
            key = (target.mesh.as_pointer(), target.layer.name)
            if key not in snapshots:
                buffer = np.empty(len(target.layer.data) * 2, dtype=np.float32)
                target.layer.data.foreach_get("uv", buffer)
                snapshots[key] = buffer
                before[key] = _bounds(buffer)

        lines = []
        with uv_transform_applied(context, warnings.append, apply_modifiers=True) as applied:
            for target in (applied.direct if applied else []):
                key = (target.mesh.as_pointer(), target.layer.name)
                buffer = np.empty(len(target.layer.data) * 2, dtype=np.float32)
                target.layer.data.foreach_get("uv", buffer)
                lines.append(
                    "%-24s slot %-3d %-14s direct     %s -> %s"
                    % (target.obj.name, target.slot_index, target.item.label,
                       _fmt(before.get(key)), _fmt(_bounds(buffer)))
                )
            for target in (applied.evaluated if applied else []):
                lines.append(
                    "%-24s slot %-3d %-14s evaluated  %s -> %s"
                    % (target.obj.name, target.record.slot_index, target.item.label,
                       _fmt(before.get((target.mesh.as_pointer(), target.layer.name))),
                       _fmt(_evaluated_bounds(target.obj, target.layer.name)))
                )

        mismatched = []
        for target in plan.direct + plan.evaluated:
            key = (target.mesh.as_pointer(), target.layer.name)
            buffer = np.empty(len(target.layer.data) * 2, dtype=np.float32)
            target.layer.data.foreach_get("uv", buffer)
            if not np.array_equal(buffer, snapshots[key]) and target.mesh.name not in mismatched:
                mismatched.append(target.mesh.name)

        leftovers = leftover_modifiers()

        print("[LJ Trim Master] dry run")
        for line in lines:
            print("  " + line)
        for message in warnings:
            print("  warning: " + message)
            self.report({'WARNING'}, message)

        if mismatched:
            self.report({'ERROR'}, "Scene UVs NOT restored: " + ", ".join(mismatched))
            return {'CANCELLED'}
        if leftovers:
            self.report({'ERROR'}, "Temporary modifiers left behind: "
                        + ", ".join("%s/%s" % pair for pair in leftovers))
            return {'CANCELLED'}
        self.report(
            {'INFO'},
            "%d slot(s) transformed and fully reverted - ranges in the System Console"
            % plan.count,
        )
        return {'FINISHED'}


class LJTM_OT_attach_hooks(Operator):
    bl_idname = "ljtm.attach_hooks"
    bl_label = "Re-attach Export Hooks"
    bl_description = (
        "Re-wrap the FBX and glTF exporters. Needed if those add-ons were "
        "enabled or reloaded after this one"
    )

    def execute(self, _context):
        status = attach_hooks()
        hooked = [label for label, state in status.items() if state == 'HOOKED']
        self.report({'INFO'}, "Hooked: " + (", ".join(hooked) or "nothing"))
        return {'FINISHED'}


class LJTM_OT_purge_modifiers(Operator):
    bl_idname = "ljtm.purge_modifiers"
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


def _bounds(buffer):
    uv = buffer.reshape(-1, 2)
    if not len(uv):
        return None
    return (float(uv[:, 0].min()), float(uv[:, 0].max()),
            float(uv[:, 1].min()), float(uv[:, 1].max()))


def _evaluated_bounds(obj, layer_name):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        layer = mesh.uv_layers.get(layer_name) or mesh.uv_layers.active
        if layer is None or not len(layer.data):
            return None
        buffer = np.empty(len(layer.data) * 2, dtype=np.float32)
        layer.data.foreach_get("uv", buffer)
        return _bounds(buffer)
    finally:
        evaluated.to_mesh_clear()


def _fmt(bounds):
    if bounds is None:
        return "(empty)"
    return "U[%.4f,%.4f] V[%.4f,%.4f]" % bounds


classes = (
    LJTM_OT_export,
    LJTM_MT_export,
    LJTM_OT_dry_run,
    LJTM_OT_attach_hooks,
    LJTM_OT_purge_modifiers,
)
