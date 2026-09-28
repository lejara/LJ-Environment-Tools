"""LJ Unity FBX Exporter + LJ Trim Master: the written FBX carries sheet-space UVs.

    "C:/Program Files/Blender Foundation/Blender 5.1/blender.exe" --background --factory-startup --python BlenderAddon/tests/test_trim_master_uvs.py

Runs every combination of Combine Into Single FBX and Apply Transforms On
Export, re-imports each file, and checks the UVs landed on the trim. Also checks
the scene is left exactly as it was. Exits non-zero on failure.
"""

import json
import os
import sys
import tempfile

import bpy
import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_ADDON_PARENT = os.path.dirname(os.path.dirname(_HERE))
# LJTM_PARENT points the test at another Trim Master build, e.g. an older one
# without export_hook.external_export or bypass.
_TRIM_MASTER_PARENT = os.environ.get("LJTM_PARENT") or os.path.join(_ADDON_PARENT, "LJTrimMaster", "Blender")
sys.path.insert(0, _ADDON_PARENT)
sys.path.insert(0, _TRIM_MASTER_PARENT)

import BlenderAddon  # noqa: E402
from BlenderAddon import export, preferences  # noqa: E402
import lj_trim_master  # noqa: E402
from lj_trim_master import assignment, export_hook, settings  # noqa: E402
from lj_trim_master.uv_transform import TrimAffine  # noqa: E402

FAILURES = []
CHECKS = [0]


def check(label, condition, detail=""):
    CHECKS[0] += 1
    print(("  ok   " if condition else "  FAIL ") + label + (("  " + detail) if detail else ""))
    if not condition:
        FAILURES.append(label)


SHEET_ID = "sheet-0001"
TRIM_A = "trim-aaaa"
TRIM_B = "trim-bbbb"
RESOLUTION = (2048, 1024)
TRIM_A_STATE = dict(position=(0.25, 0.25), scale=(0.2, 0.3), rotation=0.0, crop=(0.0, 0.0))
TRIM_B_STATE = dict(position=(0.7, 0.6), scale=(-0.15, 0.25), rotation=35.0, crop=(0.08, 0.12))
QUAD_UVS = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]


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


PAYLOAD = {
    "version": "1",
    "defaults": {"defaultTrimResolution": {"width": 2048, "height": 2048}},
    "sheets": [{
        "id": SHEET_ID, "name": "Trim01",
        "resolution": {"width": RESOLUTION[0], "height": RESOLUTION[1]},
        "enabledPresetNames": [],
        "items": [item(TRIM_A, "old_wood", TRIM_A_STATE), item(TRIM_B, "brick_a", TRIM_B_STATE)],
    }],
}


def affine(state):
    return TrimAffine.from_trim(state["position"], state["scale"], state["rotation"],
                                state["crop"], RESOLUTION)


def two_slot_object(name, x):
    """Two disjoint quads, one per material slot, each unwrapped 0-1."""
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(
        [(x, 0, 0), (x + 1, 0, 0), (x + 1, 1, 0), (x, 1, 0),
         (x + 2, 0, 0), (x + 3, 0, 0), (x + 3, 1, 0), (x + 2, 1, 0)],
        [], [(0, 1, 2, 3), (4, 5, 6, 7)],
    )
    mesh.update()
    mesh.materials.append(bpy.data.materials.new(name + "_wood"))
    mesh.materials.append(bpy.data.materials.new(name + "_brick"))
    mesh.polygons[0].material_index = 0
    mesh.polygons[1].material_index = 1
    layer = mesh.uv_layers.new(name="UVMap")
    layer.data.foreach_set(
        "uv", np.array([c for _ in range(2) for uv in QUAD_UVS for c in uv], dtype=np.float32)
    )
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = (0.0, 2.0, 0.5)
    return obj


def uvs(mesh):
    layer = mesh.uv_layers.active
    buffer = np.empty(len(layer.data) * 2, dtype=np.float32)
    layer.data.foreach_get("uv", buffer)
    return buffer


def imported_uvs(path):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=path)
    fresh = [obj for obj in bpy.data.objects if obj not in before]
    rows = [uvs(obj.data).reshape(-1, 2) for obj in fresh
            if obj.type == 'MESH' and obj.data.uv_layers.active is not None]
    for obj in fresh:
        data = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if isinstance(data, bpy.types.Mesh) and not data.users:
            bpy.data.meshes.remove(data)
    return np.vstack(rows) if rows else np.zeros((0, 2))


def corners_present(rows, matrix, tolerance=2e-4):
    return all(
        len(rows) and np.any(np.abs(rows - np.array(matrix.apply(u, v))).max(axis=1) < tolerance)
        for u, v in QUAD_UVS
    )


# ---------------------------------------------------------------------------

ROOT = tempfile.mkdtemp(prefix="ljexport-ljtm-")
OUT = os.path.join(ROOT, "fbx")
with open(os.path.join(ROOT, "projectData.json"), "w", encoding="utf-8") as handle:
    json.dump(PAYLOAD, handle)

for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)

lj_trim_master.register()
bpy.utils.register_class(preferences.LJEXPORT_PG_scene)
bpy.utils.register_class(export.LJEXPORT_OT_export_selected)
bpy.types.Scene.lj_export = bpy.props.PointerProperty(type=preferences.LJEXPORT_PG_scene)
# Not installed as an add-on here, so there are no global prefs to sync to.
preferences.sync_to_global = lambda _context: None

scene = bpy.context.scene
scene.lj_trim_master.project_root = ROOT
settings.CACHE.invalidate()
config = scene.lj_trim_master

objects = [two_slot_object("PanelsA", 0.0), two_slot_object("PanelsB", 5.0)]
for obj in objects:
    entry = assignment.add_object(config, obj)
    slot_a = assignment.add_slot(entry, 0)
    slot_b = assignment.add_slot(entry, 1)
    slot_a.sheet_enum, slot_a.trim_enum = SHEET_ID, TRIM_A
    slot_b.sheet_enum, slot_b.trim_enum = SHEET_ID, TRIM_B

matrix_a = affine(TRIM_A_STATE)
matrix_b = affine(TRIM_B_STATE)
pristine = {obj.name: uvs(obj.data).copy() for obj in objects}
object_count = len(bpy.data.objects)
mesh_count = len([m for m in bpy.data.meshes if m.users])

prefs = scene.lj_export
prefs.export_path = OUT
prefs.export_static_mesh = True
prefs.export_rig = False
prefs.file_name = ""

for combine in (False, True):
    for apply_transforms in (False, True):
        label = "combine=%s apply_transforms=%s" % (combine, apply_transforms)
        print()
        print(label)
        prefs.combine_into_single_fbx = combine
        prefs.apply_transforms_on_export = apply_transforms
        for name in os.listdir(OUT) if os.path.isdir(OUT) else []:
            os.remove(os.path.join(OUT, name))

        bpy.ops.object.select_all(action='DESELECT')
        for obj in objects:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = objects[0]

        result = bpy.ops.ljexport.export_selected()
        check("export finished", 'FINISHED' in result, str(result))

        files = sorted(os.listdir(OUT))
        check("wrote the expected files", len(files) == (1 if combine else 2), str(files))
        for name in files:
            rows = imported_uvs(os.path.join(OUT, name))
            check("%s: slot 0 landed on trim A" % name, corners_present(rows, matrix_a))
            check("%s: slot 1 landed on trim B" % name, corners_present(rows, matrix_b))

        check("scene UVs restored bit-exact",
              all(np.array_equal(uvs(obj.data), pristine[obj.name]) for obj in objects))
        check("no temporary modifiers survived", not export_hook.leftover_modifiers())
        check("no copies left behind",
              len(bpy.data.objects) == object_count
              and len([m for m in bpy.data.meshes if m.users]) == mesh_count)
        check("original names intact", sorted(o.name for o in objects) == ["PanelsA", "PanelsB"])


def export_all(sel=None):
    sel = sel or objects
    for name in os.listdir(OUT) if os.path.isdir(OUT) else []:
        os.remove(os.path.join(OUT, name))
    bpy.ops.object.select_all(action='DESELECT')
    for obj in sel:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = sel[0]
    result = bpy.ops.ljexport.export_selected()
    check("export finished", 'FINISHED' in result, str(result))
    return [imported_uvs(os.path.join(OUT, name)) for name in sorted(os.listdir(OUT))]


QUAD_CORNERS = np.array(QUAD_UVS, dtype=np.float32)


def untransformed(rows):
    return all(np.any(np.abs(rows - corner).max(axis=1) < 2e-4) for corner in QUAD_CORNERS) \
        and not corners_present(rows, matrix_a) and not corners_present(rows, matrix_b)


# Trim Master support OFF: the file gets the scene's own UVs, in every mode -
# including Apply Transforms off, where the originals themselves are exported
# and Trim Master's own FBX hook would otherwise still catch them.
prefs.trim_master_support = False
for combine in (False, True):
    for apply_transforms in (False, True):
        print()
        print("support OFF combine=%s apply_transforms=%s" % (combine, apply_transforms))
        prefs.combine_into_single_fbx = combine
        prefs.apply_transforms_on_export = apply_transforms
        for rows in export_all():
            check("UVs left untransformed", untransformed(rows))
        check("scene UVs untouched",
              all(np.array_equal(uvs(obj.data), pristine[obj.name]) for obj in objects))
        check("hook guard released", export_hook._depth == 0, str(export_hook._depth))
prefs.trim_master_support = True

# Materials off must not collapse the slots, or the next export loses trim B.
print()
print("materials off")
prefs.combine_into_single_fbx = False
prefs.export_materials = False
for apply_transforms in (False, True):
    prefs.apply_transforms_on_export = apply_transforms
    for _ in range(2):
        for rows in export_all():
            check("apply=%s: trim A and B both landed" % apply_transforms,
                  corners_present(rows, matrix_a) and corners_present(rows, matrix_b))
    check("material indices intact",
          all([p.material_index for p in obj.data.polygons] == [0, 1] for obj in objects))
    check("material slots intact", all(len(obj.data.materials) == 2 for obj in objects))
prefs.export_materials = True

# Evaluated path: a single-trim mesh with a UV-rewriting modifier.
print()
print("uv modifier")
single = two_slot_object("PanelsC", 10.0)
single.data.polygons[1].material_index = 0
entry = assignment.add_object(config, single)
slot = assignment.add_slot(entry, 0)
slot.sheet_enum, slot.trim_enum = SHEET_ID, TRIM_A
single.modifiers.new("warp", 'UV_WARP')
single_pristine = uvs(single.data).copy()
for apply_transforms in (False, True):
    prefs.apply_transforms_on_export = apply_transforms
    rows, = export_all([single])
    check("apply=%s: evaluated path landed on trim A" % apply_transforms,
          corners_present(rows, matrix_a))
    check("temporary modifiers removed",
          not export_hook.leftover_modifiers() and len(single.modifiers) == 1)
    check("UVs restored", np.array_equal(uvs(single.data), single_pristine))

print()
print("orphans")
check("no orphaned mesh copies", not any(m.name.startswith("Panels") and not m.users
                                        for m in bpy.data.meshes),
      str([m.name for m in bpy.data.meshes if not m.users]))

print()
print("%d/%d checks passed" % (CHECKS[0] - len(FAILURES), CHECKS[0]))
if FAILURES:
    sys.exit(1)
