# SPDX-License-Identifier: GPL-3.0-or-later
"""End-to-end: registry -> export -> written file -> restore -> status.

    "C:/Program Files/Blender Foundation/Blender 5.1/blender.exe" --background --factory-startup --python tests/test_sync_roundtrip.py

Exports through the real ``export_scene.fbx`` operator - the same one the
``File > Export`` menu calls - re-imports the written file, and asserts on its
contents. Exits non-zero on failure. Runs in a separate headless process, so it
cannot disturb an open session.

Assignments are made through the **enum pickers**, not by poking the underlying
strings, because the pickers are where the subtle failure lives: a dynamic enum
silently falls back to its first item when the identifier it held disappears,
and a project reload does exactly that.

The Light and Camera are deleted before every export. That is a workaround for a
**Blender 5.1.2 bug in its own FBX importer**: ``blen_read_light`` sets
``lamp.cycles.cast_shadow``, which no longer exists, so importing any FBX
containing a light raises. It affects the re-import half of the round trip only,
not this add-on and not exporting.
"""

import json
import os
import sys
import tempfile

import bpy
import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

import lj_trim_master  # noqa: E402
from lj_trim_master import assignment, export_hook, project, settings, sidecar  # noqa: E402
from lj_trim_master.uv_transform import TrimAffine  # noqa: E402

FAILURES = []
CHECKS = [0]


def check(label, condition, detail=""):
    CHECKS[0] += 1
    print(("  ok   " if condition else "  FAIL ") + label + (("  " + detail) if detail else ""))
    if not condition:
        FAILURES.append(label)


# ---------------------------------------------------------------------------
# Fixture: a project on disk
# ---------------------------------------------------------------------------

SHEET_ID = "sheet-0001"
SHEET_2_ID = "sheet-0002"
TRIM_A = "trim-aaaa"
TRIM_B = "trim-bbbb"
RESOLUTION = (2048, 1024)          # deliberately non-square
RESOLUTION_2 = (1024, 1024)

# Trim A: plain. Trim B: mirrored on x, rotated, and cropped - the awkward one.
TRIM_A_STATE = dict(position=(0.25, 0.25), scale=(0.2, 0.3), rotation=0.0, crop=(0.0, 0.0))
TRIM_B_STATE = dict(position=(0.7, 0.6), scale=(-0.15, 0.25), rotation=35.0, crop=(0.08, 0.12))

#: What the tool caches into projectData.json. Several delimiters live at once.
MAPS_BLOCK = {
    "suffixDelims": ["_", "-", "."],
    "knownMaps": ["BaseColor", "Roughness", "Metallic", "AO", "Normal", "Height", "Emissive"],
}


def project_json(trim_a=None, trim_b=None, include_b=True, sheet_resolution=None,
                 maps=True, hide_b=False):
    trim_a = dict(TRIM_A_STATE, **(trim_a or {}))
    trim_b = dict(TRIM_B_STATE, **(trim_b or {}))
    resolution = sheet_resolution or RESOLUTION

    def item(trim_id, name, state):
        return {
            "id": trim_id,
            "assetBaseName": name,
            "transform": {
                "position": {"x": state["position"][0], "y": state["position"][1]},
                "scale": {"x": state["scale"][0], "y": state["scale"][1]},
                "rotation": state["rotation"],
            },
            "crop": {"x": state["crop"][0], "y": state["crop"][1]},
        }

    items = [item(TRIM_A, "old_wood", trim_a)]
    if include_b:
        entry = item(TRIM_B, "brick_a", trim_b)
        if hide_b:
            entry["visible"] = False
        items.append(entry)

    payload = {
        "version": "1",
        "defaults": {"defaultTrimResolution": {"width": 2048, "height": 2048}},
        "sheets": [
            {
                "id": SHEET_ID, "name": "Trim01",
                "resolution": {"width": resolution[0], "height": resolution[1]},
                "enabledPresetNames": ["Unity HDRP"], "items": items,
            },
            {
                "id": SHEET_2_ID, "name": "Trim02",
                "resolution": {"width": RESOLUTION_2[0], "height": RESOLUTION_2[1]},
                "enabledPresetNames": [], "items": [],
            },
        ],
    }
    if maps:
        payload["maps"] = MAPS_BLOCK
    return payload


def write_project(root, payload):
    with open(os.path.join(root, "projectData.json"), "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    settings.CACHE.invalidate()


def affine(trim_id, payload):
    """The expected matrix, rebuilt from the JSON rather than from the fixture."""
    for sheet in payload["sheets"]:
        for item in sheet["items"]:
            if item["id"] != trim_id:
                continue
            transform = item["transform"]
            return TrimAffine.from_trim(
                (transform["position"]["x"], transform["position"]["y"]),
                (transform["scale"]["x"], transform["scale"]["y"]),
                transform["rotation"],
                (item["crop"]["x"], item["crop"]["y"]),
                (sheet["resolution"]["width"], sheet["resolution"]["height"]),
            )
    return None


# ---------------------------------------------------------------------------
# Fixture: meshes
# ---------------------------------------------------------------------------

QUAD_UVS = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]


def clear_scene():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for mesh in list(bpy.data.meshes):
        bpy.data.meshes.remove(mesh)
    for mat in list(bpy.data.materials):
        bpy.data.materials.remove(mat)


def two_slot_object(name="Panels"):
    """Two disjoint quads, one per material slot, each unwrapped 0-1."""
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(
        [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
         (2, 0, 0), (3, 0, 0), (3, 1, 0), (2, 1, 0)],
        [], [(0, 1, 2, 3), (4, 5, 6, 7)],
    )
    mesh.update()
    mesh.materials.append(bpy.data.materials.new("wood_mat"))
    mesh.materials.append(bpy.data.materials.new("brick_mat"))
    mesh.polygons[0].material_index = 0
    mesh.polygons[1].material_index = 1

    layer = mesh.uv_layers.new(name="UVMap")
    layer.data.foreach_set(
        "uv", np.array([c for _ in range(2) for uv in QUAD_UVS for c in uv], dtype=np.float32)
    )
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def base_uvs(mesh):
    layer = export_hook.target_uv_layer(mesh)
    buffer = np.empty(len(layer.data) * 2, dtype=np.float32)
    layer.data.foreach_get("uv", buffer)
    return buffer


def export_fbx(path, **kwargs):
    for obj in list(bpy.data.objects):
        if obj.type in {'LIGHT', 'CAMERA'}:
            bpy.data.objects.remove(obj, do_unlink=True)
    options = dict(filepath=path, use_selection=False, use_mesh_modifiers=True)
    options.update(kwargs)
    return bpy.ops.export_scene.fbx(**options)


def imported_uvs(path):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=path)
    fresh = [obj for obj in bpy.data.objects if obj not in before]
    rows = []
    for obj in fresh:
        if obj.type != 'MESH':
            continue
        layer = obj.data.uv_layers.active
        if layer is None:
            continue
        buffer = np.empty(len(layer.data) * 2, dtype=np.float32)
        layer.data.foreach_get("uv", buffer)
        rows.append(buffer.reshape(-1, 2))
    for obj in fresh:
        bpy.data.objects.remove(obj, do_unlink=True)
    return np.vstack(rows) if rows else np.zeros((0, 2))


def contains(rows, point, tolerance=2e-4):
    if not len(rows):
        return False
    return bool(np.any(np.abs(rows - np.array(point)).max(axis=1) < tolerance))


def corners_present(rows, matrix):
    return all(contains(rows, matrix.apply(u, v)) for u, v in QUAD_UVS)


def pick(slot, sheet_id, trim_id):
    """Assign through the enum pickers - the path the panel actually uses."""
    slot.sheet_enum = sheet_id
    slot.trim_enum = trim_id


# ---------------------------------------------------------------------------

ROOT = tempfile.mkdtemp(prefix="ljtm-test-")
DUMP = os.path.join(ROOT, "image_dump")
os.makedirs(os.path.join(DUMP, "stone"), exist_ok=True)
BLEND = os.path.join(ROOT, "scene.blend")
FBX = os.path.join(ROOT, "out.fbx")

print("Blender %s" % bpy.app.version_string)
print("project %s" % ROOT)
print()

lj_trim_master.register()
payload = project_json()
write_project(ROOT, payload)
bpy.ops.wm.save_as_mainfile(filepath=BLEND)

clear_scene()
obj = two_slot_object()
bpy.context.scene.lj_trim_master.project_root = ROOT
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
config = bpy.context.scene.lj_trim_master


print("the cached map vocabulary")
snapshot = settings.snapshot(bpy.context, force=True)
check("projectData.json parsed", snapshot is not None and snapshot.trim_count == 2)
check("the vocabulary came from the project, not the defaults",
      snapshot.has_cached_vocabulary and "-" in snapshot.maps.suffix_delims)
check("it splits a known suffix off the base name",
      snapshot.maps.split("wood_BaseColor") == ("wood", "BaseColor"))
check("a mixed-delimiter name normalizes the same way the tool does",
      snapshot.maps.split("old-wood_Normal") == ("old_wood", "Normal"))
check("an unknown suffix is not a suffix at all",
      snapshot.maps.split("old_wood_v2") == ("old_wood_v2", "BaseColor"))
check("a bare name keeps its whole stem",
      snapshot.maps.split("brick") == ("brick", "BaseColor"))
check("a project with no cached vocabulary falls back to the defaults",
      project.MapVocabulary.parse(None).known_maps == project.DEFAULT_KNOWN_MAPS)


print()
print("image_dump/ scans recursively, matching the tool")
for name in ("wood_BaseColor.png", "wood_Normal.png", "old-wood_AO.png",
             "brick.png", "notes.txt"):
    open(os.path.join(DUMP, name), "wb").close()
for name in ("wall_BaseColor.png", "wall_Normal.png"):
    open(os.path.join(DUMP, "stone", name), "wb").close()
os.makedirs(os.path.join(DUMP, ".cache"), exist_ok=True)
open(os.path.join(DUMP, ".cache", "wood_BaseColor.png"), "wb").close()

assets = dict(project.scan_assets(ROOT, snapshot.maps))
check("siblings group into one asset",
      sorted(assets.get("wood", {})) == ["BaseColor", "Normal"], str(assets.get("wood")))
check("a subfolder carries the folder in the base name", "stone/wall" in assets, str(list(assets)))
check("a top-level file keeps its bare name", "brick" in assets)
check("a non-image is ignored", "notes" not in assets)
check("dot-folders are skipped",
      len([n for n in assets if n.startswith(".")]) == 0 and len(assets.get("wood", {})) == 2)
check("mixed delimiters land on the tool's normalized name",
      "old_wood" in assets and "AO" in assets["old_wood"], str(list(assets)))
check("subfolder assets do not collide with top-level ones",
      "wall" not in assets and "stone/wall" in assets)


print()
print("the registry: object rows, opt-in slots")
entry = assignment.add_object(config, obj)
check("the object is registered, not the mesh", entry is not None and entry.obj == obj)
check("adding the same object twice is a no-op", assignment.add_object(config, obj) is None)

slot_a = assignment.add_slot(entry, 0)
slot_b = assignment.add_slot(entry, 1)
check("two slots tracked", len(entry.slots) == 2)
check("a slot records its material name for repair", slot_a.material_name == "wood_mat")

pick(slot_a, SHEET_ID, TRIM_A)
pick(slot_b, SHEET_ID, TRIM_B)
check("the pickers wrote trim_id, not an enum index",
      {slot.trim_id for slot in entry.slots} == {TRIM_A, TRIM_B})
check("and the label came along for the missing-link message",
      slot_a.asset_base_name == "old_wood" and slot_a.sheet_name == "Trim01")
check("a never-exported slot needs re-export",
      assignment.status_of(slot_a, snapshot)[0] == assignment.STATUS_NEEDS_REEXPORT)
check("the mesh row reports the worst of its slots",
      assignment.entry_status(entry, snapshot) == assignment.STATUS_NEEDS_REEXPORT)


print()
print("per-slot loop mask")
mask_0 = export_hook.loop_slot_mask(obj.data, 0)
mask_1 = export_hook.loop_slot_mask(obj.data, 1)
check("slot 0 masks exactly its own 4 loops",
      mask_0 is not None and mask_0.tolist() == [True] * 4 + [False] * 4)
check("slot 1 masks exactly its own 4 loops",
      mask_1 is not None and mask_1.tolist() == [False] * 4 + [True] * 4)
check("the two masks are disjoint and complete", bool(np.all(mask_0 ^ mask_1)))
check("an unused slot index masks nothing", export_hook.loop_slot_mask(obj.data, 7) is None)


print()
print("export: the file carries sheet-space UVs, the scene does not")
pristine = base_uvs(obj.data).copy()
result = export_fbx(FBX)
check("export finished", 'FINISHED' in result, str(result))
check("scene UVs restored bit-exact", np.array_equal(base_uvs(obj.data), pristine))
check("no temporary modifiers survived", not export_hook.leftover_modifiers())

rows = imported_uvs(FBX)
matrix_a = affine(TRIM_A, payload)
matrix_b = affine(TRIM_B, payload)
check("slot 0's UVs landed on trim A's box", corners_present(rows, matrix_a))
check("slot 1's UVs landed on trim B's box (mirrored, rotated, cropped)",
      corners_present(rows, matrix_b))
check("the raw 0-1 unwrap is NOT in the file",
      not contains(rows, (0.0, 0.0)) and not contains(rows, (1.0, 1.0)))
check("every UV in the file is inside the sheet",
      bool(np.all(rows >= -1e-3) and np.all(rows <= 1.0 + 1e-3)))
check("both slots are now up to date",
      assignment.entry_status(entry, settings.snapshot(bpy.context, True))
      == assignment.STATUS_UP_TO_DATE)


print()
print("opt-in: an unregistered mesh is left alone")
extra = two_slot_object("Untracked")
plan = export_hook.collect(bpy.context, None, apply_modifiers=True)
check("only registered rows are planned",
      plan.count == 2 and all(t.obj == obj for t in plan.direct))
os.remove(FBX)
export_fbx(FBX)
rows = imported_uvs(FBX)
check("the untracked mesh keeps its raw 0-1 unwrap in the file",
      contains(rows, (0.0, 0.0)) and contains(rows, (1.0, 1.0)))
bpy.data.objects.remove(extra, do_unlink=True)


print()
print("the mesh mirror")
stored = assignment.read_mirror(obj.data)
check("the mesh carries a serialized mirror", stored is not None and len(stored) == 2)
check("it holds the trim ids",
      {row["trimId"] for row in stored} == {TRIM_A, TRIM_B})
config.meshes.clear()
check("clearing the registry leaves the mirror behind",
      assignment.read_mirror(obj.data) is not None and len(config.meshes) == 0)
adopted = assignment.load_from_mirrors(bpy.context)
check("load_from_mirrors re-adopts it - the append path", adopted == 1)
entry = config.meshes[0]
check("and the assignments came back",
      {slot.trim_id for slot in entry.slots} == {TRIM_A, TRIM_B})
check("including the export state, so it is not falsely stale",
      assignment.entry_status(entry, settings.snapshot(bpy.context, True))
      == assignment.STATUS_UP_TO_DATE)
slot_a = assignment.find_slot(entry, 0)
slot_b = assignment.find_slot(entry, 1)


print()
print("two objects sharing a mesh cannot disagree")
twin = bpy.data.objects.new("PanelsTwin", obj.data)
bpy.context.scene.collection.objects.link(twin)
twin_entry = assignment.add_object(config, twin)
check("the twin registers as its own row", twin_entry is not None and len(config.meshes) == 2)
check("it seeded from the shared mirror", len(twin_entry.slots) == 2)
check("the UI can say how many objects share the mesh",
      len(assignment.sharing_objects(obj.data)) == 2)

pick(assignment.find_slot(twin_entry, 0), SHEET_ID, TRIM_B)
check("editing one row propagates to the other - they share one UV array",
      assignment.find_slot(entry, 0).trim_id == TRIM_B)
check("the mirror agrees too",
      {row["trimId"] for row in assignment.read_mirror(obj.data) if row["slotIndex"] == 0}
      == {TRIM_B})

plan = export_hook.collect(bpy.context, None, apply_modifiers=True)
check("the export plan is deduped by mesh, not doubled per object", plan.count == 2)

pick(assignment.find_slot(twin_entry, 0), SHEET_ID, TRIM_A)
bpy.data.objects.remove(twin, do_unlink=True)
for index in range(len(config.meshes) - 1, -1, -1):
    if assignment.mesh_of(config.meshes[index]) is None:
        config.meshes.remove(index)
entry = config.meshes[0]
slot_a = assignment.find_slot(entry, 0)
slot_b = assignment.find_slot(entry, 1)


print()
print("the sidecar link file")
os.remove(FBX)
export_fbx(FBX)
path = sidecar.sidecar_path(ROOT, BLEND)
check("named <stem>-<hash>.json under blender_links/",
      path is not None and os.path.basename(os.path.dirname(path)) == "blender_links")
check("written unconditionally, with no button to forget", os.path.exists(path))
with open(path, "r", encoding="utf-8") as handle:
    links = json.load(handle)
check("one entry per assigned slot", len(links["links"]) == 2)
check("entries resolve to a sheet",
      all(link["sheetId"] == SHEET_ID and link["resolved"] for link in links["links"]))
check("two .blends sharing a stem get different sidecar names",
      sidecar.sidecar_name("C:/a/crate.blend") != sidecar.sidecar_name("C:/b/crate.blend"))


print()
print("the trim moves in the tool")
moved = project_json(trim_a={"position": (0.6, 0.35)})
write_project(ROOT, moved)
snapshot = settings.snapshot(bpy.context, force=True)
check("only the moved trim's slot needs re-export",
      assignment.status_of(slot_a, snapshot)[0] == assignment.STATUS_NEEDS_REEXPORT
      and assignment.status_of(slot_b, snapshot)[0] == assignment.STATUS_UP_TO_DATE)
check("the scene's UVs did not move - they never do",
      np.array_equal(base_uvs(obj.data), pristine))

os.remove(FBX)
export_fbx(FBX)
rows = imported_uvs(FBX)
check("a plain File > Export picks up the new position",
      corners_present(rows, affine(TRIM_A, moved)) and not corners_present(rows, matrix_a))
check("and clears the entry, exactly as any other export path would",
      assignment.status_of(slot_a, settings.snapshot(bpy.context, True))[0]
      == assignment.STATUS_UP_TO_DATE)


print()
print("a sheet resize also invalidates")
resized = project_json(trim_a={"position": (0.6, 0.35)}, sheet_resolution=(4096, 1024))
write_project(ROOT, resized)
snapshot = settings.snapshot(bpy.context, force=True)
check("resizing the sheet marks its trims stale",
      assignment.entry_status(entry, snapshot) == assignment.STATUS_NEEDS_REEXPORT)


print()
print("the user deletes a trim")
without_b = project_json(trim_a={"position": (0.6, 0.35)}, include_b=False)
write_project(ROOT, without_b)
snapshot = settings.snapshot(bpy.context, force=True)
check("the orphaned slot is flagged Missing trim link",
      assignment.status_of(slot_b, snapshot)[0] == assignment.STATUS_MISSING_TRIM)
check("the mesh row shows the worst status",
      assignment.entry_status(entry, snapshot) == assignment.STATUS_MISSING_TRIM)
check("the label survives for the repair message", slot_b.asset_base_name == "brick_a")
check("the picker does NOT silently fall back to another trim",
      slot_b.trim_id == TRIM_B)

problems = []
plan = export_hook.collect(bpy.context, problems.append, apply_modifiers=True)
check("the missing link is reported loudly",
      any("missing trim link" in p for p in problems), "; ".join(problems))
check("and that slot is skipped, not guessed",
      plan.count == 1 and plan.direct[0].slot_index == 0)

os.remove(FBX)
export_fbx(FBX)
rows = imported_uvs(FBX)
check("the resolvable slot still exports correctly",
      corners_present(rows, affine(TRIM_A, without_b)))
check("the orphaned slot's UVs are left untransformed - visibly wrong, never silent",
      contains(rows, (0.0, 0.0)) and contains(rows, (1.0, 1.0)))
with open(sidecar.sidecar_path(ROOT, BLEND), "r", encoding="utf-8") as handle:
    check("the sidecar marks the unresolved link",
          any(link["resolved"] is False and link["trimId"] == TRIM_B
              for link in json.load(handle)["links"]))


print()
print("Move to Sheet: the sheet is derived, never stored")
write_project(ROOT, payload)
settings.snapshot(bpy.context, force=True)
os.remove(FBX)
export_fbx(FBX)

on_sheet_two = json.loads(json.dumps(payload))
item_b = [i for i in on_sheet_two["sheets"][0]["items"] if i["id"] == TRIM_B][0]
on_sheet_two["sheets"][0]["items"].remove(item_b)
on_sheet_two["sheets"][1]["items"].append(item_b)
write_project(ROOT, on_sheet_two)
snapshot = settings.snapshot(bpy.context, force=True)
found = snapshot.find_trim(TRIM_B)
check("the trim resolves under its new sheet by scan",
      found is not None and found.sheet.id == SHEET_2_ID)
check("nothing to repair - Needs Rexport, not Missing link",
      assignment.status_of(slot_b, snapshot)[0] == assignment.STATUS_NEEDS_REEXPORT)

os.remove(FBX)
export_fbx(FBX)
rows = imported_uvs(FBX)
check("it re-exports against the NEW sheet's resolution",
      corners_present(rows, affine(TRIM_B, on_sheet_two)))


print()
print("a hidden trim is not on the sheet")
write_project(ROOT, payload)
settings.snapshot(bpy.context, force=True)
os.remove(FBX)
export_fbx(FBX)
check("baseline: both slots export",
      assignment.entry_status(entry, settings.snapshot(bpy.context, True))
      == assignment.STATUS_UP_TO_DATE)

hidden = project_json(hide_b=True)
write_project(ROOT, hidden)
snapshot = settings.snapshot(bpy.context, force=True)
found = snapshot.find_trim(TRIM_B)
check("the trim still resolves, so the link is not lost",
      found is not None and found.visible is False)
check("its slot reports Trim hidden, NOT Missing trim link",
      assignment.status_of(slot_b, snapshot)[0] == assignment.STATUS_HIDDEN)
check("the visible slot is unaffected",
      assignment.status_of(slot_a, snapshot)[0] == assignment.STATUS_UP_TO_DATE)
check("hidden outranks needs-rexport on the mesh row",
      assignment.entry_status(entry, snapshot) == assignment.STATUS_HIDDEN)

problems = []
plan = export_hook.collect(bpy.context, problems.append, apply_modifiers=True)
check("the hidden slot is skipped", plan.count == 1 and plan.direct[0].slot_index == 0)
check("and it says hidden, not missing",
      any("hidden" in p for p in problems)
      and not any("missing trim link" in p for p in problems), "; ".join(problems))

os.remove(FBX)
export_fbx(FBX)
rows = imported_uvs(FBX)
check("the visible slot still exports correctly",
      corners_present(rows, affine(TRIM_A, hidden)))
check("the hidden slot keeps its raw unwrap - visibly wrong, never silent",
      contains(rows, (0.0, 0.0)) and contains(rows, (1.0, 1.0)))

with open(sidecar.sidecar_path(ROOT, BLEND), "r", encoding="utf-8") as handle:
    links = json.load(handle)["links"]
check("the sidecar flags it hidden but still resolved",
      any(link["trimId"] == TRIM_B and link["hidden"] and link["resolved"] for link in links))

hidden_ids = [i.id for i in snapshot.find_sheet(SHEET_ID).items if not i.visible]
check("a hidden trim is not offered by the Trim Image picker",
      TRIM_B in hidden_ids
      and TRIM_B not in [entry[0] for entry in assignment.trim_items(slot_a, bpy.context)])

write_project(ROOT, payload)
settings.snapshot(bpy.context, force=True)
check("showing it again clears the status",
      assignment.status_of(slot_b, settings.snapshot(bpy.context, True))[0]
      != assignment.STATUS_HIDDEN)


print()
print("the master switch")
write_project(ROOT, payload)
settings.snapshot(bpy.context, force=True)
config.enabled = False
os.remove(FBX)
export_fbx(FBX)
rows = imported_uvs(FBX)
check("off is a true no-op - the raw unwrap reaches the file",
      contains(rows, (0.0, 0.0)) and contains(rows, (1.0, 1.0)))
config.enabled = True


print()
print("Edit Mode is skipped, loudly")
problems = []
bpy.context.view_layer.objects.active = obj
bpy.ops.object.mode_set(mode='EDIT')
plan = export_hook.collect(bpy.context, problems.append, apply_modifiers=True)
bpy.ops.object.mode_set(mode='OBJECT')
check("nothing is transformed in Edit Mode", plan.count == 0)
check("and it says why", any("Edit Mode" in p for p in problems), "; ".join(problems))


print()
print("multi-trim + a UV-affecting modifier is refused, not guessed")
warp = obj.modifiers.new(name="UserWarp", type='UV_WARP')
warp.offset = (0.5, 0.0)
problems = []
plan = export_hook.collect(bpy.context, problems.append, apply_modifiers=True)
check("the object is skipped entirely", plan.count == 0)
check("with the reason spelled out",
      any("unsupported" in p and "material slot" in p for p in problems), "; ".join(problems))
check("and it is allowed when the exporter is not applying modifiers",
      export_hook.collect(bpy.context, None, apply_modifiers=False).count == 2)


print()
print("single trim + a UV-affecting modifier takes the evaluated path")
for position, slot in enumerate(entry.slots):
    if slot.slot_index == 1:
        entry.slots.remove(position)
        break
problems = []
plan = export_hook.collect(bpy.context, problems.append, apply_modifiers=True)
check("resolved to Evaluated", len(plan.evaluated) == 1 and not plan.direct)
check("it warns that the untracked slot's faces move too",
      any("no trim and will move too" in p for p in problems), "; ".join(problems))

os.remove(FBX)
pristine_single = base_uvs(obj.data).copy()
export_fbx(FBX)
rows = imported_uvs(FBX)
matrix_a = affine(TRIM_A, payload)
check("the file carries ours(modifier(uv)) - the transform lands last",
      all(contains(rows, matrix_a.apply(u + 0.5, v)) for u, v in QUAD_UVS))
check("and provably not modifier(ours(uv))",
      not contains(rows, (matrix_a.apply(0.0, 0.0)[0] + 0.5, matrix_a.apply(0.0, 0.0)[1])))
check("base UVs untouched by the evaluated path",
      np.array_equal(base_uvs(obj.data), pristine_single))
check("no temp modifiers left behind", not export_hook.leftover_modifiers())
check("the user's own modifier is still there", obj.modifiers.get("UserWarp") is not None)
obj.modifiers.remove(warp)


print()
print("restore survives a failing export")
slot_b = assignment.add_slot(entry, 1)
pick(slot_b, SHEET_ID, TRIM_B)
pristine = base_uvs(obj.data).copy()
try:
    export_fbx(os.path.join(ROOT, "no", "such", "folder", "x.fbx"))
except (RuntimeError, OSError):
    pass
check("scene UVs restored after a raised export",
      np.array_equal(base_uvs(obj.data), pristine))
check("and no modifiers leaked", not export_hook.leftover_modifiers())


print()
print("a half-written projectData.json does not blank the panel")
before = settings.snapshot(bpy.context, force=True)
with open(os.path.join(ROOT, "projectData.json"), "w", encoding="utf-8") as handle:
    handle.write('{"version": "1", "sheets": [{"id": "sheet-000')  # truncated
settings.CACHE.invalidate()
after = settings.snapshot(bpy.context, force=True)
check("the previous snapshot is kept", after is before)
check("and the failure is reported", bool(settings.CACHE.error))
write_project(ROOT, payload)
check("it recovers on the next read",
      settings.snapshot(bpy.context, force=True).trim_count == 2)


print()
print("a missing object is flagged, never auto-pruned")
orphan_mesh = bpy.data.meshes.new("OrphanMesh")
orphan_mesh.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0)], [], [(0, 1, 2)])
orphan_mesh.update()
orphan = bpy.data.objects.new("Orphan", orphan_mesh)
bpy.context.scene.collection.objects.link(orphan)
orphan_entry = assignment.add_object(config, orphan)
rows_before = len(config.meshes)
bpy.data.objects.remove(orphan, do_unlink=True)
check("the row survives the object's deletion", len(config.meshes) == rows_before)
check("and reports Missing mesh",
      assignment.entry_status(config.meshes[-1], settings.snapshot(bpy.context, True))
      == assignment.STATUS_MISSING_MESH)
problems = []
export_hook.collect(bpy.context, problems.append, apply_modifiers=True)
check("the export reports it rather than crashing",
      any("missing" in p.lower() for p in problems), "; ".join(problems))
config.meshes.remove(len(config.meshes) - 1)


print()
print("dry run")
check("dry run passes and restores bit-exact", 'FINISHED' in bpy.ops.ljtm.dry_run())
check("nothing leaked", not export_hook.leftover_modifiers())


print()
print("Refresh")
check("refresh runs", 'FINISHED' in bpy.ops.ljtm.refresh())
check("it repopulated the Create Material list", len(config.assets) > 0)
check("with normalized names, not filenames",
      any(item.name == "old_wood" for item in config.assets),
      ", ".join(item.name for item in config.assets))
check("and it found the subfolder asset",
      any(item.name == "stone/wall" for item in config.assets))


lj_trim_master.unregister()

print()
print("%d/%d checks passed" % (CHECKS[0] - len(FAILURES), CHECKS[0]))
if FAILURES:
    print("failed:")
    for label in FAILURES:
        print("  - " + label)
sys.exit(1 if FAILURES else 0)
