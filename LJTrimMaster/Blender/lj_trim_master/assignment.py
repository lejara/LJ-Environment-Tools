# SPDX-License-Identifier: GPL-3.0-or-later
"""The registry: which object's material slots point at which trims.

The registry is a **scene-level collection** and is what the user edits. It is
explicit and opt-in - ``Add Mesh From Selection`` adds rows, ``Add Active
Material Slot`` adds slots - so a slot with no entry simply is not listed and is
not transformed.

Rows are keyed by **object**, because that is what the user selects and what the
Outliner names. But UVs and ``material_index`` are **mesh** data: two objects
sharing a mesh datablock share one UV array and physically cannot carry
different assignments. So an assignment written to one row **propagates to every
row whose object shares that mesh**, and such rows are drawn with a `shared by N`
note. That makes the impossible state unreachable rather than merely detected.

The durable copy
----------------
A serialized mirror of a mesh's slots lives in a custom property on the **mesh**,
so assignments travel with append and link. Written on any assignment change and
on ``save_post``; read on ``load_post``. **Registry wins while the file is open;
mirror wins on load.** Blender has no ``append_post``, so an object appended into
an open scene arrives carrying a mirror and sits unregistered - that is what
Refresh is for.

Nothing here may write to an ID from ``draw()`` (verified fact 15). Every read
path in this module is non-mutating; every write is reached from an operator or
a handler.
"""

import json

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import Operator, PropertyGroup

from . import project

def scene_config(context):
    """The scene's registry block, or None. No import of ``settings`` - that
    module imports THIS one for its PropertyGroup type, and a cycle would make
    the package import-order dependent."""
    scene = getattr(context, "scene", None)
    return getattr(scene, "lj_trim_master", None) if scene else None


def project_root(context):
    """Absolute project root, or ``""``. Resolves Blender's ``//`` prefix."""
    block = scene_config(context)
    if block is None or not block.project_root:
        return ""
    return bpy.path.abspath(block.project_root).rstrip("\\/")


def project_snapshot(context, force=False):
    """Current ``projectData.json``, reloaded if it changed on disk."""
    if context is None:
        return project.CACHE.snapshot
    return project.CACHE.get(project_root(context), force=force)


def project_assets(context, force=False):
    """Last ``image_dump/`` scan. Only rescanned on Refresh - see AssetCache."""
    return project.ASSETS.get(project_snapshot(context, force=force), force=force)


def project_outputs(context, force=False):
    """Last ``output/`` scan: what the tool has exported, per sheet."""
    return project.OUTPUTS.get(project_snapshot(context, force=force), force=force)


#: Shape of the mesh mirror. Deliberately NOT the name the old mesh-level
#: PropertyGroup used, so a .blend saved by the previous version cannot be
#: misread as JSON.
MIRROR_KEY = "lj_trim_master_slots"
MIRROR_VERSION = 1

STATUS_UP_TO_DATE = 'UP_TO_DATE'
STATUS_NEEDS_REEXPORT = 'NEEDS_REEXPORT'
STATUS_MISSING_TRIM = 'MISSING_TRIM'
STATUS_MISSING_MESH = 'MISSING_MESH'
STATUS_HIDDEN = 'HIDDEN'
STATUS_UNASSIGNED = 'UNASSIGNED'

STATUS_LABELS = {
    STATUS_UP_TO_DATE: "Up to date",
    STATUS_NEEDS_REEXPORT: "Needs Rexport",
    STATUS_MISSING_TRIM: "Missing trim link",
    STATUS_MISSING_MESH: "Missing mesh",
    STATUS_HIDDEN: "Trim hidden",
    STATUS_UNASSIGNED: "No trim",
}

STATUS_ICONS = {
    STATUS_UP_TO_DATE: 'CHECKMARK',
    STATUS_NEEDS_REEXPORT: 'FILE_REFRESH',
    STATUS_MISSING_TRIM: 'ERROR',
    STATUS_MISSING_MESH: 'ERROR',
    STATUS_HIDDEN: 'HIDE_ON',
    STATUS_UNASSIGNED: 'DOT',
}

#: Worst-first, so a mesh row can report the worst of its slots.
STATUS_SEVERITY = (
    STATUS_MISSING_MESH,
    STATUS_MISSING_TRIM,
    # Hidden outranks Needs Rexport: re-exporting will not fix it, and the slot
    # cannot export correctly until the trim is shown again in the tool.
    STATUS_HIDDEN,
    STATUS_NEEDS_REEXPORT,
    STATUS_UNASSIGNED,
    STATUS_UP_TO_DATE,
)

NONE_ID = '__none__'

#: Blender does not keep a reference to strings returned from an items callback,
#: so they must be held alive here or the menus draw garbage.
_ENUM_KEEPALIVE = {}


# ---------------------------------------------------------------------------
# Enum pickers
#
# These live on the slot entry, so the items callback receives `self` and can
# filter the trim list by the sheet this row is showing. The enum's own stored
# value is never the truth - `trim_id` is - because a dynamic enum silently
# falls back to its first item when the identifier it held disappears, and a
# project reload does exactly that. get/set translate between the two.
# ---------------------------------------------------------------------------

def _sheet_entries(context):
    snapshot = project_snapshot(context)
    return snapshot.sheets if snapshot else []


def sheet_items(_self, context):
    items = [
        (sheet.id, sheet.name, "%d x %d, %d trim(s)"
         % (sheet.resolution[0], sheet.resolution[1], len(sheet.items)))
        for sheet in _sheet_entries(context)
    ]
    if not items:
        items = [(NONE_ID, "(no trims)", "Set a project root with at least one trim sheet")]
    _ENUM_KEEPALIVE["sheets"] = items
    return items


def _visible_sheet_id(slot, context):
    """Which sheet this row's Trim dropdown should show.

    A resolvable ``trim_id`` decides it - the sheet is always **derived**, never
    stored, which is why Move to Sheet in the tool needs no addon code. The
    picker's own value is consulted only while no trim is chosen yet, and only
    while it still resolves.

    That last clause is the whole point. This must fall back exactly the way
    ``_get_sheet`` does, because the two answer halves of one question: this one
    decides what ``trim_items`` filters by, ``_get_sheet`` decides which name the
    Trim dropdown renders. When they disagree the row shows a sheet name over an
    empty Trim Image list, which reads as "this sheet has no trims" and is a lie.
    They disagree for two states that are both ordinary: a freshly added slot
    holds ``""``, and a slot outliving a deleted sheet holds a dead id.
    """
    snapshot = project_snapshot(context)
    if snapshot is None:
        return slot.picker_sheet_id
    if slot.trim_id:
        item = snapshot.find_trim(slot.trim_id)
        if item is not None:
            return item.sheet.id
    if slot.picker_sheet_id and snapshot.find_sheet(slot.picker_sheet_id) is not None:
        return slot.picker_sheet_id
    return snapshot.sheets[0].id if snapshot.sheets else ""


def _get_sheet(self):
    context = bpy.context
    identifier = _visible_sheet_id(self, context)
    items = sheet_items(self, context)
    for index, item in enumerate(items):
        if item[0] == identifier:
            return index
    return 0


def _set_sheet(self, value):
    context = bpy.context
    items = sheet_items(self, context)
    if not (0 <= value < len(items)):
        return
    chosen = items[value][0]
    self.picker_sheet_id = "" if chosen == NONE_ID else chosen
    # Changing the Trim drops a Trim Image that lives on a different one, so the
    # second dropdown always offers a valid choice rather than a stale label.
    snapshot = project_snapshot(context)
    if snapshot is not None and self.trim_id:
        item = snapshot.find_trim(self.trim_id)
        if item is None or item.sheet.id != chosen:
            _apply_assignment(context, self, None)


def trim_items(self, context):
    snapshot = project_snapshot(context)
    sheet = snapshot.find_sheet(_visible_sheet_id(self, context)) if snapshot else None
    # Hidden trims are not offered: they are not on the sheet, so picking one
    # could only ever produce a slot that refuses to export.
    items = ([(item.id, item.label, "trim id %s" % item.id)
              for item in sheet.items if item.visible] if sheet else [])
    if not items:
        items = [(NONE_ID, "(no trim images)", "Add an image to this trim in LJ Trim Master")]
    _ENUM_KEEPALIVE["trims"] = items
    return items


def _get_trim(self):
    items = trim_items(self, bpy.context)
    for index, item in enumerate(items):
        if item[0] == self.trim_id:
            return index
    return 0


def _set_trim(self, value):
    context = bpy.context
    items = trim_items(self, context)
    if not (0 <= value < len(items)):
        return
    chosen = items[value][0]
    snapshot = project_snapshot(context)
    item = snapshot.find_trim(chosen) if (snapshot and chosen != NONE_ID) else None
    _apply_assignment(context, self, item)


# ---------------------------------------------------------------------------
# Stored data
# ---------------------------------------------------------------------------

class LJTM_SlotEntry(PropertyGroup):
    slot_index: IntProperty(name="Slot", default=0, min=0)
    #: Label only, and only a fallback: the panel reads the live name off the
    #: mesh, so a renamed or replaced material just shows its new name. This is
    #: what the row says when `slot_index` no longer resolves to a material at
    #: all. It is in the mirror and the sidecar, so it stays.
    material_name: StringProperty(name="Material")
    expanded: BoolProperty(name="Expanded", default=True)

    #: THE identity, and the only resolution key.
    trim_id: StringProperty(name="Trim Image")
    #: Label only. Never used for matching - it is the tool's normalized name
    #: and may match no file on disk exactly.
    asset_base_name: StringProperty(name="Asset")
    #: Label only, for the missing-link message.
    sheet_name: StringProperty(name="Trim")
    #: Trim state at last export. Informational only - see `status_of`.
    last_export: StringProperty(name="Last Export")

    #: UI state for the Trim dropdown while no trim image is chosen yet. Never
    #: consulted to resolve a trim.
    picker_sheet_id: StringProperty(options={'SKIP_SAVE'})

    sheet_enum: EnumProperty(
        name="Trim",
        description="Which trim sheet this material slot is packed into",
        items=sheet_items,
        get=_get_sheet,
        set=_set_sheet,
    )
    trim_enum: EnumProperty(
        name="Trim Image",
        description="Which image on that trim sheet this material slot uses",
        items=trim_items,
        get=_get_trim,
        set=_set_trim,
    )


class LJTM_MeshEntry(PropertyGroup):
    obj: PointerProperty(
        name="Object",
        type=bpy.types.Object,
        description="Blender stores a pointer, so renames follow and a delete nulls it",
    )
    slots: CollectionProperty(type=LJTM_SlotEntry)


# ---------------------------------------------------------------------------
# Registry access - all non-mutating, safe to call from draw()
# ---------------------------------------------------------------------------

def mesh_of(entry):
    obj = entry.obj
    return obj.data if (obj is not None and obj.type == 'MESH') else None


def find_entry(config, obj):
    for entry in config.meshes:
        if entry.obj == obj:
            return entry
    return None


def find_slot(entry, slot_index):
    for slot in entry.slots:
        if slot.slot_index == slot_index:
            return slot
    return None


def slot_material_name(obj, slot_index):
    """Read through the MESH, because that is what ``material_index`` indexes."""
    mesh = obj.data if (obj is not None and obj.type == 'MESH') else None
    if mesh is None or not (0 <= slot_index < len(mesh.materials)):
        return ""
    material = mesh.materials[slot_index]
    return material.name if material else ""


def slot_count(obj):
    """Number of face groups. A mesh with no materials still has slot 0."""
    mesh = obj.data if (obj is not None and obj.type == 'MESH') else None
    return max(len(mesh.materials), 1) if mesh else 0


def sharing_objects(mesh):
    """Every object in the file using *mesh*. Drives the `shared by N` note."""
    if mesh is None:
        return []
    return [obj for obj in bpy.data.objects if obj.type == 'MESH' and obj.data == mesh]


def display_name(entry):
    obj = entry.obj
    return obj.name if obj is not None else "(missing object)"


def object_missing(entry):
    """Is this row's object gone, as far as anything downstream is concerned?

    A null pointer is the obvious case. The one that actually happens is the
    other one: ``bpy.ops.object.delete()`` - the ``X`` key, the only delete the
    UI offers - merely **unlinks** the object from its collections. This
    registry's ``PointerProperty`` is a real user, so the datablock survives at
    ``users == 1`` and ``entry.obj`` never becomes None. Checking the pointer
    alone therefore reports an ordinary status for an object that is not in the
    scene and will never be exported again.

    ``users_scene`` is empty for exactly that state, and for an object the user
    unlinked by hand, which is the same thing here. Note that
    ``bpy.data.objects.remove(obj, do_unlink=True)`` - what the test suite used -
    does force the purge and does null the pointer, which is why this went
    unnoticed.

    Report only: the row and the pointer are kept, per the same rule the null
    case follows, because an undo or a library reload can produce this state
    transiently and dropping the assignment would be unrecoverable.
    """
    obj = entry.obj
    if obj is None or obj.type != 'MESH':
        return True
    return not obj.users_scene


def is_selected(entry):
    """Is this row's object selected in the viewport?

    Read-only, so it is safe from draw - and the sidebar already redraws on a
    selection change, so the answer never goes stale.

    Guarded twice. ``object_missing`` covers the unlinked-but-alive object that
    function documents; the ``RuntimeError`` covers the narrower case it does
    not, an object that is in a scene but not in this view layer - an excluded
    collection - for which ``select_get()`` raises rather than returning False.
    """
    if object_missing(entry):
        return False
    try:
        return bool(entry.obj.select_get())
    except RuntimeError:
        return False


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def signature(item):
    """Everything about a trim that changes its UVs, as one comparable string.

    Fixed precision on purpose: a JSON round trip perturbs floats in the last
    bits, and a phantom "Needs Rexport" on every project reload would make the
    list useless. 1e-7 normalized is 0.0002 px on a 2048 sheet.
    """
    sheet = item.sheet
    return "%s:%dx%d:%.7f,%.7f:%.7f,%.7f:%.5f:%.7f,%.7f" % (
        sheet.id, sheet.resolution[0], sheet.resolution[1],
        item.position[0], item.position[1],
        item.scale[0], item.scale[1], item.rotation,
        item.crop[0], item.crop[1],
    )


def status_of(slot, snapshot):
    """``(status, item_or_None)`` for one slot against live project data.

    A trim that moved, a sheet that was resized, and a trim moved to another
    sheet all land on ``NEEDS_REEXPORT`` - the signature carries the sheet id
    and resolution, so all three change it. A never-exported slot is folded in
    there too: it also needs an export to become correct.

    A **hidden** trim gets its own status rather than reusing MISSING_TRIM. The
    link is perfectly good; the trim is simply switched off in the tool, and
    telling the user to re-pick would make them destroy a correct assignment to
    fix something that only needs unhiding.
    """
    if not slot.trim_id:
        return (STATUS_UNASSIGNED, None)
    if snapshot is None:
        return (STATUS_NEEDS_REEXPORT, None)
    item = snapshot.find_trim(slot.trim_id)
    if item is None:
        return (STATUS_MISSING_TRIM, None)
    if not item.visible:
        return (STATUS_HIDDEN, item)
    if slot.last_export and slot.last_export == signature(item):
        return (STATUS_UP_TO_DATE, item)
    return (STATUS_NEEDS_REEXPORT, item)


def entry_status(entry, snapshot):
    """The worst status among a row's slots, or MISSING_MESH."""
    if mesh_of(entry) is None or object_missing(entry):
        return STATUS_MISSING_MESH
    worst = None
    for slot in entry.slots:
        state, _item = status_of(slot, snapshot)
        if worst is None or STATUS_SEVERITY.index(state) < STATUS_SEVERITY.index(worst):
            worst = state
    return worst or STATUS_UNASSIGNED


def mark_exported(slot, item):
    slot.last_export = signature(item)
    slot.asset_base_name = item.asset_base_name
    slot.sheet_name = item.sheet.name


def iter_assignments(config):
    """``(obj, mesh, slot)`` for every assigned slot, **deduped by mesh**.

    Two objects sharing a mesh carry the same assignment by construction, so
    exporting or reporting them twice would be double work and a duplicated
    warning.
    """
    seen = set()
    for entry in config.meshes:
        mesh = mesh_of(entry)
        if mesh is None or mesh.as_pointer() in seen:
            continue
        seen.add(mesh.as_pointer())
        for slot in entry.slots:
            if slot.trim_id:
                yield (entry.obj, mesh, slot)


# ---------------------------------------------------------------------------
# Mutation. Reached only from operators and handlers.
# ---------------------------------------------------------------------------

def _apply_assignment(context, slot, item):
    """Point one slot at *item* (or clear it), then propagate and mirror.

    Propagation is what makes the object-keyed registry safe: every row whose
    object shares this mesh gets the same value, so two rows can never disagree
    about a UV array they both own.
    """
    slot.trim_id = item.id if item else ""
    slot.asset_base_name = item.asset_base_name if item else ""
    slot.sheet_name = item.sheet.name if item else ""
    slot.last_export = ""
    if item is not None:
        slot.picker_sheet_id = item.sheet.id

    config = scene_config(context)
    if config is None:
        return

    owner = None
    for entry in config.meshes:
        if any(existing == slot for existing in entry.slots):
            owner = entry
            break
    if owner is None:
        return

    mesh = mesh_of(owner)
    if mesh is None:
        return
    _propagate(config, owner, mesh, slot)
    write_mirror(mesh, owner)
    _write_sidecar(context)


def _propagate(config, owner, mesh, slot):
    for entry in config.meshes:
        if entry == owner or mesh_of(entry) != mesh:
            continue
        twin = find_slot(entry, slot.slot_index)
        if twin is None:
            twin = entry.slots.add()
            twin.slot_index = slot.slot_index
            twin.material_name = slot.material_name
        _copy_slot(slot, twin)


def _copy_slot(source, target):
    target.material_name = source.material_name
    target.trim_id = source.trim_id
    target.asset_base_name = source.asset_base_name
    target.sheet_name = source.sheet_name
    target.last_export = source.last_export


def _write_sidecar(context):
    from . import sidecar
    sidecar.write_for_scene(context)


def add_object(config, obj):
    """Register *obj*, seeding its slots from the mesh mirror if it has one."""
    if obj is None or obj.type != 'MESH' or obj.data is None:
        return None
    if find_entry(config, obj) is not None:
        return None
    entry = config.meshes.add()
    entry.obj = obj
    _seed_from_mirror(entry, obj.data)
    return entry


def add_slot(entry, slot_index):
    if find_slot(entry, slot_index) is not None:
        return None
    slot = entry.slots.add()
    slot.slot_index = slot_index
    slot.material_name = slot_material_name(entry.obj, slot_index)
    return slot


# ---------------------------------------------------------------------------
# The mesh mirror
# ---------------------------------------------------------------------------

def write_mirror(mesh, entry):
    """Serialize *entry*'s slots onto the mesh so they survive append/link."""
    if mesh is None:
        return
    mesh[MIRROR_KEY] = json.dumps({
        "version": MIRROR_VERSION,
        "slots": [
            {
                "slotIndex": slot.slot_index,
                "materialName": slot.material_name,
                "trimId": slot.trim_id,
                "assetBaseName": slot.asset_base_name,
                "sheetName": slot.sheet_name,
                "lastExport": slot.last_export,
            }
            for slot in entry.slots
        ],
    })


def read_mirror(mesh):
    """The mesh's stored slots, or None.

    Anything unparseable is treated as absent rather than raising: a ``.blend``
    saved by the previous add-on version stores a PropertyGroup under a
    different key, but a hand-edited or truncated value must not break loading
    the file either.
    """
    if mesh is None:
        return None
    raw = mesh.get(MIRROR_KEY)
    if not isinstance(raw, str):
        return None
    try:
        payload = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    slots = payload.get("slots")
    return slots if isinstance(slots, list) else None


def _seed_from_mirror(entry, mesh):
    stored = read_mirror(mesh)
    if not stored:
        return
    for raw in stored:
        if not isinstance(raw, dict):
            continue
        try:
            index = int(raw.get("slotIndex", 0))
        except (TypeError, ValueError):
            continue
        slot = find_slot(entry, index) or entry.slots.add()
        slot.slot_index = index
        slot.material_name = str(raw.get("materialName") or "")
        slot.trim_id = str(raw.get("trimId") or "")
        slot.asset_base_name = str(raw.get("assetBaseName") or "")
        slot.sheet_name = str(raw.get("sheetName") or "")
        slot.last_export = str(raw.get("lastExport") or "")


def write_all_mirrors(context):
    """``save_post``: flush the registry onto the meshes it describes."""
    config = scene_config(context)
    if config is None:
        return
    for entry in config.meshes:
        mesh = mesh_of(entry)
        if mesh is not None:
            write_mirror(mesh, entry)


def load_from_mirrors(context):
    """``load_post`` / Refresh: adopt any mesh carrying a mirror.

    **Mirror wins on load, registry wins while open.** An object appended into
    an already-open scene fires no handler, so it arrives with a mirror and no
    registry row until this runs. Returns how many rows were added.
    """
    config = scene_config(context)
    if config is None:
        return 0
    known = {entry.obj for entry in config.meshes if entry.obj is not None}
    added = 0
    for obj in context.scene.objects:
        if obj.type != 'MESH' or obj.data is None or obj in known:
            continue
        if read_mirror(obj.data) is None:
            continue
        if add_object(config, obj) is not None:
            added += 1
    return added


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

class LJTM_OT_add_meshes(Operator):
    bl_idname = "ljtm.add_meshes"
    bl_label = "Add Mesh From Selection"
    bl_description = "Register every selected mesh object so its slots can be assigned"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return any(obj.type == 'MESH' for obj in context.selected_objects)

    def execute(self, context):
        config = scene_config(context)
        if config is None:
            return {'CANCELLED'}
        added = sum(
            1 for obj in context.selected_objects if add_object(config, obj) is not None
        )
        # `add_object` appends, so the last new row is the last row. Point the
        # list at it: the slots draw below the list now, and landing on whatever
        # was active before would hide the mesh the user just added.
        if added:
            config.active_mesh = len(config.meshes) - 1
        _write_sidecar(context)
        self.report({'INFO'}, "Added %d mesh(es)" % added)
        return {'FINISHED'}


class LJTM_OT_remove_mesh(Operator):
    bl_idname = "ljtm.remove_mesh"
    bl_label = "Remove Mesh"
    bl_description = "Stop tracking this mesh. Its UVs are then left untransformed on export"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(default=-1, options={'SKIP_SAVE'})

    def execute(self, context):
        config = scene_config(context)
        if config is None or not (0 <= self.index < len(config.meshes)):
            return {'CANCELLED'}
        mesh = mesh_of(config.meshes[self.index])
        config.meshes.remove(self.index)
        # The list is the only way to reach a mesh's slots now, so a stale active
        # index would leave the editor below it blank. Same clamp
        # `settings.rebuild_asset_list` applies to the material list.
        if config.active_mesh >= len(config.meshes):
            config.active_mesh = max(len(config.meshes) - 1, 0)
        # The mirror goes too, or Refresh would immediately re-adopt it.
        if mesh is not None and MIRROR_KEY in mesh:
            del mesh[MIRROR_KEY]
        _write_sidecar(context)
        return {'FINISHED'}


class LJTM_OT_add_slot(Operator):
    bl_idname = "ljtm.add_slot"
    bl_label = "Add Active Material Slot"
    bl_description = "Track the object's active material slot so it can be assigned a trim"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(default=-1, options={'SKIP_SAVE'})

    def execute(self, context):
        config = scene_config(context)
        if config is None or not (0 <= self.index < len(config.meshes)):
            return {'CANCELLED'}
        entry = config.meshes[self.index]
        obj = entry.obj
        if obj is None:
            self.report({'ERROR'}, "That row's object is gone")
            return {'CANCELLED'}

        slot_index = obj.active_material_index if slot_count(obj) > 1 else 0
        if slot_index >= slot_count(obj):
            slot_index = 0
        if add_slot(entry, slot_index) is None:
            self.report({'WARNING'}, "Slot %d is already listed" % slot_index)
            return {'CANCELLED'}

        mesh = mesh_of(entry)
        if mesh is not None:
            write_mirror(mesh, entry)
        _write_sidecar(context)
        self.report({'INFO'}, "Added slot %d (%s)"
                    % (slot_index, slot_material_name(obj, slot_index) or "no material"))
        return {'FINISHED'}


class LJTM_OT_remove_slot(Operator):
    bl_idname = "ljtm.remove_slot"
    bl_label = "Remove Slot"
    bl_description = "Stop tracking this material slot"
    bl_options = {'REGISTER', 'UNDO'}

    mesh_index: IntProperty(default=-1, options={'SKIP_SAVE'})
    slot_index: IntProperty(default=-1, options={'SKIP_SAVE'})

    def execute(self, context):
        config = scene_config(context)
        if config is None or not (0 <= self.mesh_index < len(config.meshes)):
            return {'CANCELLED'}
        entry = config.meshes[self.mesh_index]
        mesh = mesh_of(entry)

        for position, slot in enumerate(entry.slots):
            if slot.slot_index == self.slot_index:
                entry.slots.remove(position)
                break
        else:
            return {'CANCELLED'}

        # Objects sharing this mesh must lose it too, or they would disagree.
        if mesh is not None:
            for other in config.meshes:
                if other == entry or mesh_of(other) != mesh:
                    continue
                for position, slot in enumerate(other.slots):
                    if slot.slot_index == self.slot_index:
                        other.slots.remove(position)
                        break
            write_mirror(mesh, entry)
        _write_sidecar(context)
        return {'FINISHED'}


class LJTM_OT_refresh(Operator):
    bl_idname = "ljtm.refresh"
    bl_label = "Refresh"
    bl_description = (
        "Re-read projectData.json, rescan image_dump/ including subfolders, "
        "adopt any appended mesh carrying trim data, and re-evaluate every status"
    )
    bl_options = {'REGISTER'}

    def execute(self, context):
        # Deferred, like the sidecar import below: `settings` imports THIS
        # module for its PropertyGroup types, so a module-level import here
        # would close the cycle.
        from . import settings

        snapshot = project_snapshot(context, force=True)
        found = settings.rebuild_asset_list(context)
        adopted = load_from_mirrors(context)
        _write_sidecar(context)

        if snapshot is None:
            self.report({'WARNING'}, project.CACHE.error or "No project root set")
            return {'FINISHED'}
        message = "%d trim(s) across %d sheet(s), %d image(s)" % (
            snapshot.trim_count, len(snapshot.sheets), found
        )
        if adopted:
            message += ", adopted %d appended mesh(es)" % adopted
        if not snapshot.has_cached_vocabulary:
            message += " - no cached map vocabulary; open the project in LJ Trim Master once"
        self.report({'INFO'}, message)
        return {'FINISHED'}


classes = (
    LJTM_SlotEntry,
    LJTM_MeshEntry,
    LJTM_OT_add_meshes,
    LJTM_OT_remove_mesh,
    LJTM_OT_add_slot,
    LJTM_OT_remove_slot,
    LJTM_OT_refresh,
)
