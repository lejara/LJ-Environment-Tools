# SPDX-License-Identifier: GPL-3.0-or-later
"""Headless proof for the evaluated-mesh path (handover Q4).

Run with:
    blender.exe --background --python tests/test_evaluated_path.py

The evaluated path appends two temporary UVWarp modifiers instead of rewriting
the base UV buffer, so the transform lands *after* modifiers that generate or
alter UVs. These cases prove:

  1. Direct and Evaluated produce identical UVs in the file when there is no
     UV-affecting modifier - including a non-uniform scale combined with a
     rotation, which a single UVWarp provably cannot express.
  2. With a UV-altering modifier present, Auto picks Evaluated and the file
     carries ours(modifier(uv)), not modifier(ours(uv)).
  3. Nothing is left behind: no temp modifiers, base UVs bit-identical.
  4. When the exporter is not applying modifiers, Auto falls back to Direct
     rather than silently doing nothing.
"""

import math
import os
import sys
import tempfile

import bpy

MODULE = "bl_ext.user_default.uv_export_transform"

# Non-uniform scale + rotation on purpose: this is exactly the combination a
# single UVWarp modifier cannot represent (it forces sx**2 == sy**2).
OFFSET = (0.1, -0.2)
SCALE = (1.5, 0.75)
ROT = math.radians(30.0)
PIVOT = (0.5, 0.5)

# The "artist's" modifier standing between the base UVs and the file.
MOD_OFFSET = (0.25, 0.125)
MOD_SCALE = (0.5, 2.0)
MOD_ROT = math.radians(-15.0)
MOD_CENTER = (0.5, 0.5)

failures = []


def check(label, condition, detail=""):
    print("[%s] %s%s" % ("PASS" if condition else "FAIL", label,
                         ("  " + detail) if detail else ""))
    if not condition:
        failures.append(label)


def ours(coords):
    """The add-on's convention: scale, rotate, translate - about the pivot."""
    px, py = PIVOT
    out = []
    for u, v in coords:
        x, y = (u - px) * SCALE[0], (v - py) * SCALE[1]
        c, s = math.cos(ROT), math.sin(ROT)
        x, y = x * c - y * s, x * s + y * c
        out.append((x + px + OFFSET[0], y + py + OFFSET[1]))
    return out


def uvwarp(coords):
    """Blender's UVWarp convention, measured: S . R . (uv + off - c) + c."""
    cx, cy = MOD_CENTER
    out = []
    for u, v in coords:
        x, y = u + MOD_OFFSET[0] - cx, v + MOD_OFFSET[1] - cy
        c, s = math.cos(MOD_ROT), math.sin(MOD_ROT)
        x, y = x * c - y * s, x * s + y * c
        out.append((x * MOD_SCALE[0] + cx, y * MOD_SCALE[1] + cy))
    return out


def sig(coords, places=3):
    return sorted({(round(u, places), round(v, places)) for u, v in coords})


def read_uvs(mesh, name="UVMap"):
    layer = mesh.uv_layers.get(name) or mesh.uv_layers.active
    return [tuple(loop.uv) for loop in layer.data]


def reset_scene():
    """Cube only - Blender 5.1.2's FBX importer crashes on lights."""
    bpy.ops.wm.read_homefile(use_empty=False)
    for obj in list(bpy.data.objects):
        if obj.type != 'MESH':
            bpy.data.objects.remove(obj, do_unlink=True)
    return bpy.data.objects["Cube"]


def configure(cube, method):
    st = bpy.context.scene.uv_export_transform
    st.enabled = True
    st.entries.clear()
    entry = st.entries.add()
    entry.obj = cube
    entry.uv_mode = 'ACTIVE'
    entry.method = method
    entry.offset = OFFSET
    entry.scale = SCALE
    entry.rotation = ROT
    entry.pivot = PIVOT
    return entry


def add_artist_uvwarp(cube):
    mod = cube.modifiers.new(name="ArtistWarp", type='UV_WARP')
    mod.uv_layer = "UVMap"
    mod.center = MOD_CENTER
    mod.offset = MOD_OFFSET
    mod.scale = MOD_SCALE
    mod.rotation = MOD_ROT
    return mod


def export_import(path, **kwargs):
    bpy.ops.export_scene.fbx(filepath=path, **kwargs)
    bpy.ops.wm.read_homefile(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=path)
    mesh = [o for o in bpy.data.objects if o.type == 'MESH'][0].data
    return read_uvs(mesh)


def main():
    bpy.ops.preferences.addon_enable(module=MODULE)
    import importlib
    mod = importlib.import_module(MODULE)
    tmp = tempfile.mkdtemp(prefix="uvxf_eval_")

    # -- case 1: Direct and Evaluated agree when no modifier is in the way ---
    cube = reset_scene()
    base = read_uvs(cube.data)
    want = sig(ours(base))

    configure(cube, 'DIRECT')
    direct = export_import(os.path.join(tmp, "direct.fbx"))

    cube = reset_scene()
    configure(cube, 'EVALUATED')
    evaluated = export_import(os.path.join(tmp, "evaluated.fbx"))

    check("Direct matches the analytic transform", sig(direct) == want)
    check("Evaluated matches the analytic transform", sig(evaluated) == want,
          "two chained UVWarps reproduce scale->rotate->translate")
    check("Direct and Evaluated agree", sig(direct) == sig(evaluated),
          "non-uniform scale %s + rotation %.0f deg"
          % (SCALE, math.degrees(ROT)))

    # -- case 2: a UV-altering modifier is present ---------------------------
    cube = reset_scene()
    base = read_uvs(cube.data)
    add_artist_uvwarp(cube)
    entry = configure(cube, 'AUTO')

    detected = mod.uv_affecting_modifiers(cube)
    check("UV-affecting modifier detected", [m.name for m in detected] == ["ArtistWarp"],
          str([m.name for m in detected]))

    targets = mod.collect_targets(bpy.context.scene, apply_modifiers=True)
    check("Auto resolves to Evaluated", [t.method for t in targets] == ['EVALUATED'],
          str([t.method for t in targets]))

    got = export_import(os.path.join(tmp, "auto_eval.fbx"), use_mesh_modifiers=True)
    correct = sig(ours(uvwarp(base)))      # transform the FINAL UVs
    wrong = sig(uvwarp(ours(base)))        # what Direct would have produced
    check("file carries ours(modifier(uv))", sig(got) == correct)
    check("file is NOT modifier(ours(uv))", sig(got) != wrong,
          "the two orders are genuinely different")

    # -- case 3: nothing left behind ----------------------------------------
    bpy.ops.wm.read_homefile(use_empty=False)
    for obj in list(bpy.data.objects):
        if obj.type != 'MESH':
            bpy.data.objects.remove(obj, do_unlink=True)
    cube = bpy.data.objects["Cube"]
    before = list(read_uvs(cube.data))
    names_before = [m.name for m in cube.modifiers]
    add_artist_uvwarp(cube)
    configure(cube, 'EVALUATED')
    bpy.ops.export_scene.fbx(filepath=os.path.join(tmp, "cleanup.fbx"))
    check("no temp modifiers left", mod.leftover_modifiers() == [],
          str(mod.leftover_modifiers()))
    check("modifier stack restored",
          [m.name for m in cube.modifiers] == names_before + ["ArtistWarp"],
          str([m.name for m in cube.modifiers]))
    check("base UVs untouched by the evaluated path",
          read_uvs(cube.data) == before)

    # -- case 4: exporter not applying modifiers -----------------------------
    targets = mod.collect_targets(bpy.context.scene, apply_modifiers=False)
    st = bpy.context.scene.uv_export_transform
    st.entries[0].method = 'AUTO'
    targets = mod.collect_targets(bpy.context.scene, apply_modifiers=False)
    check("Auto falls back to Direct when modifiers are not applied",
          [t.method for t in targets] == ['DIRECT'],
          str([(t.method, t.reason) for t in targets]))

    got = export_import(os.path.join(tmp, "no_modifiers.fbx"),
                        use_mesh_modifiers=False)
    check("that fallback still transforms the exported UVs",
          sig(got) == sig(ours(before)))

    print("\nartifacts in %s" % tmp)
    if failures:
        print("\n%d FAILED: %s" % (len(failures), ", ".join(failures)))
        sys.exit(1)
    print("\nALL CHECKS PASSED")


main()
