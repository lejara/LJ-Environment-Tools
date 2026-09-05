# SPDX-License-Identifier: GPL-3.0-or-later
"""The five defects found in the first real-UI session, each pinned by a test.

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

import os
import sys
import tempfile

import bpy

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

import lj_trim_master  # noqa: E402
from lj_trim_master import assignment, export_hook, material, panel, settings  # noqa: E402

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
    mesh.uv_layers.new(name="UVMap")
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


lj_trim_master.unregister()

print()
print("%d/%d checks passed" % (CHECKS[0] - len(FAILURES), CHECKS[0]))
if FAILURES:
    print("failed:")
    for label in FAILURES:
        print("  - " + label)
sys.exit(1 if FAILURES else 0)
