# SPDX-License-Identifier: GPL-3.0-or-later
"""The defects found in the first real-UI session, each pinned by a test.

    "C:/Program Files/Blender Foundation/Blender 5.1/blender.exe" --background --factory-startup --python tests/test_ui_bugs.py

Every one of these passed the existing suites while being broken in the panel,
which is the point of the file: each test reproduces the state through the path
the **UI** takes, not the path a test finds convenient.

The clearest example is item 3. `test_sync_roundtrip` deleted its object with
`bpy.data.objects.remove(obj, do_unlink=True)`, which purges the datablock and
nulls the pointer, so the check passed. The X key calls
`bpy.ops.object.delete()`, which only unlinks - and this registry is a user of
the object, so the datablock survives and the pointer stays live. Same
intention, opposite outcome.

Exits non-zero on failure. Separate process, so an open session is undisturbed.
"""

import io
import os
import sys
import tempfile

import bpy

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

import lj_trim_master  # noqa: E402
from lj_trim_master import (  # noqa: E402
    assignment, export_hook, material, panel, project, settings,
)

FAILURES = []
CHECKS = [0]


def _die(kind, value, trace):
    """Blender prints an uncaught traceback and still exits 0. Don't let it."""
    import traceback
    traceback.print_exception(kind, value, trace)
    sys.stdout.flush()
    os._exit(1)


sys.excepthook = _die


def check(label, condition, detail=""):
    CHECKS[0] += 1
    print(("  ok   " if condition else "  FAIL ") + label + (("  " + detail) if detail else ""))
    if not condition:
        FAILURES.append(label)


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

SHEET_ID = "sheet-0001"
SHEET_2_ID = "sheet-0002"
TRIM_A = "trim-aaaa"
TRIM_B = "trim-bbbb"

#: Long on purpose. The whole of item 4 is that a long name is what gets eaten.
LONG_ASSET = "pink_stone_quarry_wall_b"


def project_json():
    def item(trim_id, name):
        return {
            "id": trim_id,
            "assetBaseName": name,
            "transform": {"position": {"x": 0.5, "y": 0.5},
                          "scale": {"x": 0.4, "y": 0.4}, "rotation": 0.0},
            "crop": {"x": 0.0, "y": 0.0},
        }

    return {
        "version": "1",
        "defaults": {"defaultTrimResolution": {"width": 1024, "height": 1024}},
        "sheets": [
            {"id": SHEET_ID, "name": "Test_Trim",
             "resolution": {"width": 1024, "height": 1024},
             "enabledPresetNames": [],
             "items": [item(TRIM_A, "old_wood"), item(TRIM_B, LONG_ASSET)]},
            {"id": SHEET_2_ID, "name": "Test_Trim_B",
             "resolution": {"width": 512, "height": 512},
             "enabledPresetNames": [], "items": []},
        ],
    }


def write_project(root, payload):
    import json
    with open(os.path.join(root, "projectData.json"), "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    settings.CACHE.invalidate()


def write_png(path, colour=(0.5, 0.5, 1.0, 1.0)):
    """A real 4x4 PNG. `bpy.data.images.load` will not open an empty file."""
    image = bpy.data.images.new(os.path.basename(path), 4, 4, alpha=True)
    image.pixels = list(colour) * 16
    image.filepath_raw = path
    image.file_format = 'PNG'
    image.save()
    bpy.data.images.remove(image)


def one_object(name="Cube"):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [], [(0, 1, 2, 3)])
    mesh.update()
    layer = mesh.uv_layers.new(name="UVMap")
    # A real 0-1 unwrap. `uv_layers.new` leaves every UV at the origin, and a
    # transform of a single point measures nothing.
    for loop_uv, uv in zip(layer.data, [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]):
        loop_uv.uv = uv
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


# ---------------------------------------------------------------------------

ROOT = tempfile.mkdtemp(prefix="ljtm-ui-")
DUMP = os.path.join(ROOT, "image_dump")
os.makedirs(DUMP, exist_ok=True)

print("Blender %s" % bpy.app.version_string)
print("project %s" % ROOT)
print()

lj_trim_master.register()
write_project(ROOT, project_json())
bpy.context.scene.lj_trim_master.project_root = ROOT
config = bpy.context.scene.lj_trim_master
settings.snapshot(bpy.context, force=True)


# ---------------------------------------------------------------------------
print("1. Export Hooks classifies the C exporters, rather than calling them absent")
# ---------------------------------------------------------------------------

check("a real C operator is found through bpy.ops",
      export_hook._operator_exists("wm.obj_export"))
check("and is genuinely invisible to bpy.types - the cause of the bug",
      getattr(bpy.types, "WM_OT_obj_export", None) is None)
check("a name that does not exist is still reported absent",
      not export_hook._operator_exists("wm.definitely_not_an_export"))
check("as is a whole module that does not exist",
      not export_hook._operator_exists("nonsense_module.nope"))

export_hook.attach_hooks()
status = export_hook.hook_status()
print("   " + ", ".join("%s=%s" % pair for pair in sorted(status.items())))

for label in ("OBJ", "PLY", "STL", "USD", "Alembic"):
    check("%s reports C_OPERATOR, not UNAVAILABLE" % label,
          status.get(label) == 'C_OPERATOR', str(status.get(label)))
check("FBX is hooked, so the panel's dot stays green",
      status.get('FBX') == 'HOOKED', str(status.get('FBX')))
check("glTF is hooked", status.get('glTF') == 'HOOKED', str(status.get('glTF')))
check("no target is left UNAVAILABLE on a stock build",
      'UNAVAILABLE' not in status.values(), str(status))


# ---------------------------------------------------------------------------
print()
print("2. A fresh slot's Trim Image list is populated, not empty")
# ---------------------------------------------------------------------------

obj = one_object("Panel")
obj.data.materials.append(bpy.data.materials.new("wood_mat"))
entry = assignment.add_object(config, obj)
slot = assignment.add_slot(entry, 0)

check("a fresh slot holds no picker sheet, which is the trigger",
      slot.picker_sheet_id == "")

sheet_id = assignment._visible_sheet_id(slot, bpy.context)
trims = assignment.trim_items(slot, bpy.context)
trim_ids = [entry_[0] for entry_ in trims]

check("the row filters by the sheet it is displaying", sheet_id == SHEET_ID, sheet_id)
check("so the Trim Image list offers the sheet's trims",
      trim_ids == [TRIM_A, TRIM_B], str(trim_ids))
check("and not the '(no trim images)' placeholder",
      assignment.NONE_ID not in trim_ids, str(trims))

# The second trigger: a picker left pointing at a sheet that no longer exists.
# This is the state the live session was already in when the bug was found.
slot.picker_sheet_id = "76430692-dead-dead-dead-000000000000"
check("a picker pointing at a deleted sheet falls back too",
      assignment._visible_sheet_id(slot, bpy.context) == SHEET_ID)
check("and its Trim Image list is populated, not empty",
      [e[0] for e in assignment.trim_items(slot, bpy.context)] == [TRIM_A, TRIM_B])
check("which is the same sheet the Trim dropdown renders - the two now agree",
      assignment.sheet_items(slot, bpy.context)[
          assignment._get_sheet(slot)][0] == SHEET_ID)

# Picking a real sheet still wins over the fallback.
slot.picker_sheet_id = SHEET_2_ID
check("an explicitly picked sheet is honoured",
      assignment._visible_sheet_id(slot, bpy.context) == SHEET_2_ID)
check("an empty sheet correctly offers nothing",
      [e[0] for e in assignment.trim_items(slot, bpy.context)] == [assignment.NONE_ID])

# A resolvable trim always outranks the picker - the sheet stays derived.
slot.picker_sheet_id = SHEET_ID
slot.trim_enum = TRIM_A
slot.picker_sheet_id = SHEET_2_ID   # deliberately stale; the trim must still win
check("assigning a trim re-derives the sheet from the trim",
      assignment._visible_sheet_id(slot, bpy.context) == SHEET_ID)
check("the assignment landed", slot.trim_id == TRIM_A, slot.trim_id)


# ---------------------------------------------------------------------------
print()
print("3. An object deleted with X reports Missing mesh")
# ---------------------------------------------------------------------------

doomed = one_object("Cube_SHIFTD")
doomed_entry = assignment.add_object(config, doomed)
rows_before = len(config.meshes)

bpy.ops.object.select_all(action='DESELECT')
doomed.select_set(True)
bpy.context.view_layer.objects.active = doomed
bpy.ops.object.delete()

check("the row survives, as designed", len(config.meshes) == rows_before)
check("the datablock survives - the registry is a user of it",
      doomed.name in bpy.data.objects)
check("so the pointer is still live, which is why the None check missed it",
      doomed_entry.obj is not None)
check("and mesh_of still returns a mesh", assignment.mesh_of(doomed_entry) is not None)
check("users_scene is the state that actually changed",
      not doomed_entry.obj.users_scene)
check("object_missing sees it", assignment.object_missing(doomed_entry))

snapshot = settings.snapshot(bpy.context, force=True)
check("the row reports Missing mesh, not Needs Rexport",
      assignment.entry_status(doomed_entry, snapshot) == assignment.STATUS_MISSING_MESH,
      assignment.entry_status(doomed_entry, snapshot))

problems = []
plan = export_hook.collect(bpy.context, problems.append, apply_modifiers=True)
check("the export says so rather than silently including it",
      any("not in the scene" in message for message in problems), "; ".join(problems))
check("and does not queue it", "Cube_SHIFTD" not in plan.object_names,
      str(plan.object_names))

# select_get() raises for an object outside the view layer, so a selection-only
# export used to be a crash waiting on this exact row.
crashed = None
try:
    export_hook.collect(bpy.context, None, apply_modifiers=True, selection_only=True)
except Exception as exc:  # noqa: BLE001 - the point is that nothing escapes
    crashed = "%s: %s" % (type(exc).__name__, exc)
check("a selection-only export does not raise on that row", crashed is None, crashed or "")

# An object still in the scene must NOT be caught by any of this.
check("a live object is not reported missing", not assignment.object_missing(entry))

config.meshes.remove(len(config.meshes) - 1)
bpy.data.objects.remove(doomed, do_unlink=True)


# ---------------------------------------------------------------------------
print()
print("4. The Missing trim link footer keeps the asset name")
# ---------------------------------------------------------------------------

slot.trim_enum = TRIM_B
assignment.mark_exported(slot, settings.snapshot(bpy.context, force=True).find_trim(TRIM_B))
check("the fixture slot is assigned to the long-named trim",
      slot.asset_base_name == LONG_ASSET, slot.asset_base_name)

# Delete that trim from the project, exactly as editing projectData.json does.
payload = project_json()
payload["sheets"][0]["items"] = [payload["sheets"][0]["items"][0]]
write_project(ROOT, payload)
snapshot = settings.snapshot(bpy.context, force=True)

state, _item = assignment.status_of(slot, snapshot)
check("the state is Missing trim link", state == assignment.STATUS_MISSING_TRIM, state)
check("the trim_id is retained, not silently re-pointed", slot.trim_id == TRIM_B)

cause, name = panel.missing_trim_lines(slot)
print("   row 1: %s" % cause)
print("   row 2: %s" % name)
check("the name is on its own row", LONG_ASSET in name)
check("and it is the tail of that row, where elision cannot reach first",
      name.endswith(LONG_ASSET))
check("the sheet name moved to the other row", "Test_Trim" in cause)
check("the instruction survived", "Re-pick" in name)

# The one-row version measured 50 characters and was elided at a 373 px sidebar.
# Both replacements have to be materially shorter than that, individually.
one_row = "Missing trim link - was '%s' on %s. Re-pick above" % (LONG_ASSET, "Test_Trim")
check("row 1 is shorter than the string that was elided",
      len(cause) < len(one_row) - 12, "%d vs %d" % (len(cause), len(one_row)))
check("row 2 is shorter than the string that was elided",
      len(name) < len(one_row) - 12, "%d vs %d" % (len(name), len(one_row)))

# A slot that never recorded a name must still say something useful.
slot.asset_base_name = ""
_cause, fallback = panel.missing_trim_lines(slot)
check("with no recorded name it falls back to the trim id",
      slot.trim_id[:8] in fallback, fallback)
slot.asset_base_name = LONG_ASSET

write_project(ROOT, project_json())
settings.snapshot(bpy.context, force=True)


# ---------------------------------------------------------------------------
print()
print("5. Create Material twice does not stack duplicate nodes")
# ---------------------------------------------------------------------------

write_png(os.path.join(DUMP, "old_wood_BaseColor.png"))
write_png(os.path.join(DUMP, "old_wood_Normal.png"))
maps = dict(settings.assets(bpy.context, force=True)).get("old_wood", {})
check("the fixture asset scanned with both maps",
      sorted(maps) == ["BaseColor", "Normal"], str(sorted(maps)))


def counts(tree):
    images = [n for n in tree.nodes if n.bl_idname == 'ShaderNodeTexImage']
    normal_maps = [n for n in tree.nodes if n.bl_idname == 'ShaderNodeNormalMap']
    return len(tree.nodes), len(images), len(normal_maps)


built, _warnings = material.build_material("old_wood", maps)
first = counts(built.node_tree)
built_again, _warnings = material.build_material("old_wood", maps)
second = counts(built_again.node_tree)

check("the material is reused, not duplicated", built_again is built and
      built.name == "old_wood", built_again.name)
check("the second press adds nothing", first == second, "%s -> %s" % (first, second))
check("there is exactly one image node per map", second[1] == 2, str(second))
check("and exactly one Normal Map node", second[2] == 1, str(second))

principled = next(n for n in built.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
check("Base Color is wired once", len(principled.inputs['Base Color'].links) == 1)
check("Normal is wired once", len(principled.inputs['Normal'].links) == 1)

for _ in range(3):
    material.build_material("old_wood", maps)
check("and stays flat over repeated presses", counts(built.node_tree) == second,
      str(counts(built.node_tree)))

# Repair: a material already stacked up by the old code, rebuilt by hand.
tree = built.node_tree
for _ in range(2):
    stale_base = tree.nodes.new('ShaderNodeTexImage')
    stale_base.label = "BaseColor"
    stale_normal = tree.nodes.new('ShaderNodeTexImage')
    stale_normal.label = "Normal"
    stale_map = tree.nodes.new('ShaderNodeNormalMap')       # unlabelled, as before
    stale_map.location = material.NORMAL_MAP_LOCATION
polluted = counts(tree)
material.build_material("old_wood", maps)
check("a material already polluted is repaired, not just left alone",
      counts(tree) == second, "%s -> %s, want %s" % (polluted, counts(tree), second))

# A node that is not ours is never touched.
foreign = tree.nodes.new('ShaderNodeTexImage')
foreign.label = "Somebody Else's Texture"
foreign_map = tree.nodes.new('ShaderNodeNormalMap')
foreign_map.location = (900, 900)
tree.links.new(foreign.outputs['Color'], foreign_map.inputs['Color'])
material.build_material("old_wood", maps)
check("a foreign image node survives", foreign.name in tree.nodes)
check("a foreign Normal Map node survives", foreign_map.name in tree.nodes)


# ---------------------------------------------------------------------------
print()
print("6. A slot's material name is reflected, not warned about")
# ---------------------------------------------------------------------------

named = one_object("Renamed")
first_material = bpy.data.materials.new("slab_mat")
named.data.materials.append(first_material)
named_entry = assignment.add_object(config, named)
named_slot = assignment.add_slot(named_entry, 0)
check("the slot records the name it was added with",
      named_slot.material_name == "slab_mat", named_slot.material_name)

first_material.name = "slab_mat_v2"
check("a rename is reflected immediately",
      assignment.slot_material_name(named, 0) == "slab_mat_v2",
      assignment.slot_material_name(named, 0))

named.data.materials[0] = bpy.data.materials.new("brick_mat")
check("so is a different material dropped into the slot",
      assignment.slot_material_name(named, 0) == "brick_mat",
      assignment.slot_material_name(named, 0))
check("the stored name is left alone - it is only a fallback",
      named_slot.material_name == "slab_mat", named_slot.material_name)

named.data.materials.clear()
check("with nothing in the slot the live read is empty",
      assignment.slot_material_name(named, 0) == "")
check("and the stored name is what the row falls back to",
      (assignment.slot_material_name(named, 0) or named_slot.material_name
       or "no material") == "slab_mat")

check("no draw path claims a changed material is a problem",
      "is now" not in io.open(os.path.join(os.path.dirname(_HERE),
                                           "lj_trim_master", "panel.py"),
                              encoding="utf-8").read())

config.meshes.remove(len(config.meshes) - 1)
bpy.data.objects.remove(named, do_unlink=True)


# ---------------------------------------------------------------------------
print()
print("7. Integrity Check (was Dry Run Check)")
# ---------------------------------------------------------------------------

check("the operator answers to its new name", hasattr(bpy.ops.ljtm, "integrity_check"))
check("the slot the check will run on is assigned", slot.trim_id == TRIM_B, slot.trim_id)

layer = obj.data.uv_layers[0]
uvs_before = [tuple(loop.uv) for loop in layer.data]

config.enabled = True
result = bpy.ops.ljtm.integrity_check()
check("it passes with the master switch on", 'FINISHED' in result, str(result))
check("and left the scene UVs bit-exact",
      [tuple(loop.uv) for loop in layer.data] == uvs_before)

config.enabled = False
result = bpy.ops.ljtm.integrity_check()
check("with the master switch off it refuses rather than claiming success",
      'CANCELLED' in result, str(result))
check("and still touched nothing",
      [tuple(loop.uv) for loop in layer.data] == uvs_before)
config.enabled = True


# ---------------------------------------------------------------------------
print()
print("8. Duplicate and Transform")
# ---------------------------------------------------------------------------

stray = one_object("Untracked")
bpy.ops.object.select_all(action='DESELECT')
stray.select_set(True)
bpy.context.view_layer.objects.active = stray
objects_before = len(bpy.data.objects)

result = bpy.ops.ljtm.duplicate_transform()
check("an unlisted mesh is refused", 'CANCELLED' in result, str(result))
check("and nothing was created", len(bpy.data.objects) == objects_before)

# A tracked object with no trim assigned is refused too, and just as quietly.
bare = one_object("Bare")
bare.data.materials.append(bpy.data.materials.new("bare_mat"))
bare_entry = assignment.add_object(config, bare)
assignment.add_slot(bare_entry, 0)
bpy.ops.object.select_all(action='DESELECT')
bare.select_set(True)
bpy.context.view_layer.objects.active = bare
objects_before = len(bpy.data.objects)
result = bpy.ops.ljtm.duplicate_transform()
check("a tracked mesh with no trim is refused", 'CANCELLED' in result, str(result))
check("and nothing was created", len(bpy.data.objects) == objects_before)

# The real path: the assigned object from section 2.
bpy.ops.object.select_all(action='DESELECT')
obj.select_set(True)
bpy.context.view_layer.objects.active = obj
assignment.write_mirror(obj.data, entry)
check("the original carries a mesh mirror to inherit",
      assignment.MIRROR_KEY in obj.data)

result = bpy.ops.ljtm.duplicate_transform()
check("it runs", 'FINISHED' in result, str(result))

copy = bpy.data.objects.get(obj.name + export_hook.BAKED_SUFFIX)
check("a copy exists, named for what it is", copy is not None)

if copy is not None:
    check("the original's UVs are untouched",
          [tuple(loop.uv) for loop in layer.data] == uvs_before)

    baked = [tuple(loop.uv) for loop in copy.data.uv_layers[0].data]
    # The fixture trim sits at position 0.5,0.5 with scale 0.4,0.4, so its rect
    # on the sheet is U[0.3,0.7] V[0.3,0.7] whichever way the affine flips V.
    inside = all(0.29 < u < 0.71 and 0.29 < v < 0.71 for u, v in baked)
    check("the copy's UVs were baked into the trim's rect", inside, str(baked))
    check("and they actually moved", baked != uvs_before)

    check("the copy has no registry row",
          assignment.find_entry(config, copy) is None)
    check("and no mesh mirror, so Refresh cannot adopt it either",
          assignment.MIRROR_KEY not in copy.data)
    check("it is stamped, so the state is visible in Object Properties",
          copy.get(export_hook.BAKED_KEY) is True)
    check("it is the active selection", bpy.context.view_layer.objects.active == copy)

    # The real hazard this guards: a second export must not transform it again.
    assignment.load_from_mirrors(bpy.context)
    check("the load handler does not adopt it",
          assignment.find_entry(config, copy) is None)
    plan = export_hook.collect(bpy.context, None, apply_modifiers=True)
    check("and no export path queues it", copy.name not in plan.object_names,
          str(plan.object_names))

    bpy.data.objects.remove(copy, do_unlink=True)

config.meshes.remove(len(config.meshes) - 1)
bpy.data.objects.remove(bare, do_unlink=True)
bpy.data.objects.remove(stray, do_unlink=True)


# ---------------------------------------------------------------------------
print()
print("9. On-Click Material lists exported trim sheets")
# ---------------------------------------------------------------------------

check("a sheet name is sanitized the way the tool sanitizes it",
      project.output_base_name("Trim #1") == "Trim #1"
      and project.output_base_name("a/b") == "a_b"
      and project.output_base_name("Trim.") == "Trim"
      and project.output_base_name("") == "Sheet",
      project.output_base_name("a/b"))

OUT = os.path.join(ROOT, "output")
os.makedirs(OUT, exist_ok=True)
for output_name in ("Test_Trim_BaseColor.png", "Test_Trim_Normal.png",
                    "Test_Trim_MaskMap.png", "Test_Trim_B_BaseColor.png"):
    write_png(os.path.join(OUT, output_name))
open(os.path.join(OUT, "notes.txt"), "wb").close()

settings.OUTPUTS.invalidate()
scanned = dict((sheet.id, maps) for sheet, maps in settings.outputs(bpy.context, force=True))
check("the first sheet's exports were found",
      sorted(scanned.get(SHEET_ID, {})) == ["BaseColor", "MaskMap", "Normal"],
      str(sorted(scanned.get(SHEET_ID, {}))))
check("an unknown suffix is kept under its own name, not dropped",
      "MaskMap" in scanned.get(SHEET_ID, {}))
check("the longest sheet prefix wins, so Test_Trim_B keeps its own file",
      sorted(scanned.get(SHEET_2_ID, {})) == ["BaseColor"],
      str(sorted(scanned.get(SHEET_2_ID, {}))))
check("a non-image in output/ is ignored",
      not any("notes" in path for maps in scanned.values() for path in maps.values()))

settings.rebuild_asset_list(bpy.context)
rows = [(row.kind, row.name, row.map_count) for row in config.assets]
print("   rows: %s" % rows)
check("sheets are listed first",
      rows[0][0] == settings.KIND_SHEET and rows[1][0] == settings.KIND_SHEET,
      str(rows[:2]))
check("with their exported map counts",
      rows[0] == (settings.KIND_SHEET, "Test_Trim", 3), str(rows[0]))
check("image_dump assets still follow",
      any(kind == settings.KIND_ASSET and name == "old_wood" for kind, name, _ in rows),
      str(rows))

sheet_row = next(row for row in config.assets
                 if row.kind == settings.KIND_SHEET and row.sheet_id == SHEET_ID)
result = bpy.ops.ljtm.create_material(
    base_name=sheet_row.name, kind=sheet_row.kind, sheet_id=sheet_row.sheet_id,
    assign_to_active=False,
)
check("a sheet material builds", 'FINISHED' in result, str(result))
sheet_material = bpy.data.materials.get("Test_Trim")
check("named after the sheet", sheet_material is not None)
if sheet_material is not None:
    images = [node.image for node in sheet_material.node_tree.nodes
              if node.bl_idname == 'ShaderNodeTexImage' and node.image]
    sources = sorted(os.path.basename(bpy.path.abspath(image.filepath))
                     for image in images)
    check("wired to the sheet's own exports, not to image_dump",
          sources == ["Test_Trim_BaseColor.png", "Test_Trim_Normal.png"], str(sources))

# A sheet nothing has been exported for is listed, and says why it cannot build.
payload = project_json()
payload["sheets"].append({"id": "sheet-0003", "name": "Never_Built",
                          "resolution": {"width": 256, "height": 256},
                          "enabledPresetNames": [], "items": []})
write_project(ROOT, payload)
settings.OUTPUTS.invalidate()
settings.rebuild_asset_list(bpy.context)
unbuilt = next((row for row in config.assets if row.name == "Never_Built"), None)
check("an unexported sheet is still listed", unbuilt is not None)
if unbuilt is not None:
    check("with a map count of zero, which the row renders as 'not exported'",
          unbuilt.map_count == 0)
    # An operator that reports {'ERROR'} raises when called from Python, which
    # is Blender's contract, not a defect - in the UI it is a red status line.
    refusal = ""
    try:
        bpy.ops.ljtm.create_material(
            base_name=unbuilt.name, kind=unbuilt.kind, sheet_id=unbuilt.sheet_id,
            assign_to_active=False,
        )
    except RuntimeError as exc:
        refusal = str(exc)
    check("and building from it is refused, pointing at Build",
          "output/" in refusal and "Build" in refusal, refusal)
    check("no empty material was left behind",
          bpy.data.materials.get("Never_Built") is None)


lj_trim_master.unregister()

print()
print("%d/%d checks passed" % (CHECKS[0] - len(FAILURES), CHECKS[0]))
if FAILURES:
    print("failed:")
    for label in FAILURES:
        print("  - " + label)
sys.exit(1 if FAILURES else 0)
