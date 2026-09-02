# SPDX-License-Identifier: GPL-3.0-or-later
"""Headless round-trip proof for the UV Export Transform extension.

Run with:
    blender.exe --background --python tests/test_fbx_roundtrip.py

Exports the default cube through the *native* export_scene.fbx operator (the
one the File > Export menu calls), re-imports the written file, and asserts:

  1. the UVs inside the FBX carry the transform,
  2. the UVs still in the .blend scene are untouched,
  3. with the master switch off the FBX matches the scene exactly.

Exits non-zero on failure so it can be wired into CI.
"""

import os
import sys
import tempfile

import bpy

MODULE = "bl_ext.user_default.uv_export_transform"

OFFSET = (0.25, 0.0)
SCALE = (0.5, 0.5)
PIVOT = (0.5, 0.5)

failures = []
notes = []


def check(label, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print("[%s] %s%s" % (status, label, ("  " + detail) if detail else ""))
    if not condition:
        failures.append(label)


def uv_signature(mesh, layer_name="UVMap"):
    """Order-independent fingerprint of a UV layer: bounds + unique coords."""
    layer = mesh.uv_layers.get(layer_name) or mesh.uv_layers.active
    coords = [tuple(round(c, 4) for c in loop.uv) for loop in layer.data]
    us = [c[0] for c in coords]
    vs = [c[1] for c in coords]
    return {
        "bounds": (round(min(us), 4), round(max(us), 4),
                   round(min(vs), 4), round(max(vs), 4)),
        "unique": sorted(set(coords)),
        "count": len(coords),
    }


def expected(sig):
    """Apply the same transform analytically to a signature's unique coords."""
    px, py = PIVOT
    out = []
    for u, v in sig["unique"]:
        u = (u - px) * SCALE[0] + px + OFFSET[0]
        v = (v - py) * SCALE[1] + py + OFFSET[1]
        out.append((round(u, 4), round(v, 4)))
    return sorted(set(out))


def reset_scene():
    """Fresh startup file, cube only.

    The Light and Camera are removed because Blender 5.1.2's own FBX *importer*
    crashes on lights (lamp.cycles.cast_shadow no longer exists). That is a
    Blender bug, unrelated to this extension, but it would break the re-import
    half of the round trip.
    """
    bpy.ops.wm.read_homefile(use_empty=False)
    for obj in list(bpy.data.objects):
        if obj.type != 'MESH':
            bpy.data.objects.remove(obj, do_unlink=True)
    return bpy.data.objects["Cube"]


def export_and_reimport(path):
    bpy.ops.export_scene.fbx(filepath=path)
    size = os.path.getsize(path)
    bpy.ops.wm.read_homefile(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=path)
    meshes = [o for o in bpy.data.objects if o.type == 'MESH']
    return meshes[0].data, size


def main():
    bpy.ops.preferences.addon_enable(module=MODULE)
    check("extension enabled", MODULE in bpy.context.preferences.addons)

    import importlib
    mod = importlib.import_module(MODULE)
    status = mod.hook_status()
    print("     hook status: %s" % status)
    check("FBX operator hooked", status.get("FBX") == 'HOOKED')

    tmp = tempfile.mkdtemp(prefix="uvxf_")

    # ---- case 1: transform enabled -------------------------------------
    cube = reset_scene()
    source = uv_signature(cube.data)
    print("     scene UV bounds before export: %s" % (source["bounds"],))

    st = bpy.context.scene.uv_export_transform
    st.enabled = True
    st.entries.clear()
    entry = st.entries.add()
    entry.obj = cube
    entry.uv_mode = 'ACTIVE'
    entry.offset = OFFSET
    entry.scale = SCALE
    entry.pivot = PIVOT
    entry.rotation = 0.0

    path = os.path.join(tmp, "cube_transformed.fbx")
    scene_after = None

    imported, size = None, 0
    try:
        bpy.ops.export_scene.fbx(filepath=path)
        size = os.path.getsize(path)
        # the scene must be untouched the instant the write returns
        scene_after = uv_signature(cube.data)
    finally:
        pass

    check("FBX written", size > 0, "%d bytes" % size)
    check(
        "scene UVs unchanged by export",
        scene_after == source,
        "%s vs %s" % (scene_after["bounds"], source["bounds"]),
    )

    bpy.ops.wm.read_homefile(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=path)
    imported = uv_signature(
        [o for o in bpy.data.objects if o.type == 'MESH'][0].data
    )
    print("     FBX UV bounds: %s" % (imported["bounds"],))

    want = expected(source)
    check(
        "FBX carries the transformed UVs",
        imported["unique"] == want,
        "got %s want %s" % (imported["bounds"], (
            min(u for u, _ in want), max(u for u, _ in want),
            min(v for _, v in want), max(v for _, v in want),
        )),
    )
    check(
        "FBX UVs differ from scene UVs",
        imported["unique"] != source["unique"],
    )

    # ---- case 2: master switch off (control) ---------------------------
    cube = reset_scene()
    control_source = uv_signature(cube.data)
    st = bpy.context.scene.uv_export_transform
    st.enabled = False
    st.entries.clear()
    entry = st.entries.add()
    entry.obj = cube
    entry.offset = OFFSET
    entry.scale = SCALE
    entry.pivot = PIVOT

    path = os.path.join(tmp, "cube_control.fbx")
    bpy.ops.export_scene.fbx(filepath=path)
    bpy.ops.wm.read_homefile(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=path)
    control = uv_signature(
        [o for o in bpy.data.objects if o.type == 'MESH'][0].data
    )
    check(
        "master switch off exports untransformed UVs",
        control["unique"] == control_source["unique"],
        "%s vs %s" % (control["bounds"], control_source["bounds"]),
    )

    # ---- case 3: exporter failure still restores -----------------------
    cube = reset_scene()
    before = uv_signature(cube.data)
    st = bpy.context.scene.uv_export_transform
    st.enabled = True
    st.entries.clear()
    entry = st.entries.add()
    entry.obj = cube
    entry.offset = OFFSET
    entry.scale = SCALE
    entry.pivot = PIVOT

    raised = False
    try:
        bpy.ops.export_scene.fbx(
            filepath=os.path.join(tmp, "nonexistent_dir", "x", "y.fbx")
        )
    except Exception as exc:  # noqa: BLE001 - we want any failure mode
        raised = True
        notes.append("export failure raised: %s" % type(exc).__name__)
    after = uv_signature(cube.data)
    check(
        "scene UVs restored even when the export fails",
        after == before,
        "raised=%s" % raised,
    )

    print("")
    for note in notes:
        print("note: %s" % note)
    print("artifacts in %s" % tmp)
    if failures:
        print("\n%d FAILED: %s" % (len(failures), ", ".join(failures)))
        sys.exit(1)
    print("\nALL CHECKS PASSED")


main()
