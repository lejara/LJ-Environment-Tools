# SPDX-License-Identifier: GPL-3.0-or-later
"""Measures Blender's UVWarp modifier and answers HANDOFF Part 6's open question.

    "C:/Program Files/Blender Foundation/Blender 5.1/blender.exe" --background --python tests/probe_uvwarp.py

Three things are established here, and nothing in the add-on should assume them
without this having been run:

1. UVWarp's actual convention - is the linear part ``S.R`` or ``R.S``, and is
   ``rotation`` counter-clockwise in UV space?
2. **Can a UVWarp scale component be negative?** A mirrored trim has a negative
   ``scale`` in ``projectData.json``, and the two-modifier decomposition puts
   that reflection into a negative singular value. If Blender clamps or refuses
   it, the evaluated path cannot express mirrored trims and needs a Direct
   fallback plus a warning.
3. Whether ``MeshPolygon.loop_total`` is still readable via ``foreach_get`` in
   this Blender, since the per-slot loop mask is built from it.

Exits non-zero if any of it comes out other than the add-on assumes.
"""

import math
import os
import sys

import bpy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import importlib.util

_SPEC = importlib.util.spec_from_file_location(
    "uv_transform",
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "lj_trim_master",
        "uv_transform.py",
    ),
)
uv_transform = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(uv_transform)
TrimAffine = uv_transform.TrimAffine

FAILURES = []
CHECKS = [0]


def check(label, condition, detail=""):
    CHECKS[0] += 1
    print(("  ok   " if condition else "  FAIL ") + label + ("  " + detail if detail else ""))
    if not condition:
        FAILURES.append(label)


# ---------------------------------------------------------------------------
# Scene setup
# ---------------------------------------------------------------------------

# Three UVs that are affinely independent, so a 2x3 matrix is fully determined
# by where they land. Given as (u, v) per loop of a single quad.
PROBE = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]


def fresh_plane(name):
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for mesh in list(bpy.data.meshes):
        bpy.data.meshes.remove(mesh)

    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(
        [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [], [(0, 1, 2, 3)]
    )
    mesh.update()
    layer = mesh.uv_layers.new(name="UVMap")
    flat = np.array([c for uv in PROBE for c in uv], dtype=np.float32)
    layer.data.foreach_set("uv", flat)

    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def evaluated_uvs(obj):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        layer = mesh.uv_layers.active
        buf = np.empty(len(layer.data) * 2, dtype=np.float64)
        tmp = np.empty(len(layer.data) * 2, dtype=np.float32)
        layer.data.foreach_get("uv", tmp)
        buf[:] = tmp
        return buf.reshape(-1, 2).copy()
    finally:
        evaluated.to_mesh_clear()


def fit_affine(source, destination):
    """Least-squares 2x3 from the probe UVs to where they landed."""
    rows = np.column_stack([source[:, 0], source[:, 1], np.ones(len(source))])
    solution, *_ = np.linalg.lstsq(rows, destination, rcond=None)
    return solution.T  # 2x3


def add_uvwarp(obj, center, offset, rotation, scale, name="probe"):
    mod = obj.modifiers.new(name=name, type='UV_WARP')
    mod.uv_layer = "UVMap"
    mod.center = center
    mod.offset = offset
    mod.rotation = rotation
    mod.scale = scale
    return mod


print("Blender %s" % bpy.app.version_string)
print()

source = np.array(PROBE, dtype=np.float64)


# ---------------------------------------------------------------------------
# 1. Which convention?
# ---------------------------------------------------------------------------

print("UVWarp convention")

ROT = math.radians(30.0)
SCALE = (2.0, 0.5)

obj = fresh_plane("convention")
add_uvwarp(obj, (0.0, 0.0), (0.0, 0.0), ROT, SCALE)
bpy.context.view_layer.update()
measured = fit_affine(source, evaluated_uvs(obj))
linear = measured[:, :2]

cos_r, sin_r = math.cos(ROT), math.sin(ROT)
rot_ccw = np.array([[cos_r, -sin_r], [sin_r, cos_r]])
rot_cw = rot_ccw.T
diag = np.diag(SCALE)

candidates = {
    "S . R(+r)": diag @ rot_ccw,
    "S . R(-r)": diag @ rot_cw,
    "R(+r) . S": rot_ccw @ diag,
    "R(-r) . S": rot_cw @ diag,
}
best = min(candidates, key=lambda k: np.abs(candidates[k] - linear).max())
for label, candidate in candidates.items():
    print("    %-11s max delta %.6g%s"
          % (label, np.abs(candidate - linear).max(), "   <-- match" if label == best else ""))

check("linear part is S . R(+rotation), rotation CCW in UV space",
      best == "S . R(+r)" and np.abs(candidates["S . R(+r)"] - linear).max() < 1e-5,
      "best was %s" % best)

# Offset is applied before the transform, per the measured convention.
obj = fresh_plane("offset_order")
add_uvwarp(obj, (0.25, 0.75), (0.1, -0.2), ROT, SCALE)
bpy.context.view_layer.update()
got = evaluated_uvs(obj)


def model(u, v, center, offset, rotation, scale):
    cx, cy = center
    x = u + offset[0] - cx
    y = v + offset[1] - cy
    rx = x * math.cos(rotation) - y * math.sin(rotation)
    ry = x * math.sin(rotation) + y * math.cos(rotation)
    return (rx * scale[0] + cx, ry * scale[1] + cy)


want = np.array([model(u, v, (0.25, 0.75), (0.1, -0.2), ROT, SCALE) for u, v in PROBE])
check("uv' = S . R . (uv + offset - center) + center",
      np.abs(got - want).max() < 1e-5,
      "max delta %.6g" % np.abs(got - want).max())


# ---------------------------------------------------------------------------
# 2. Negative scale - HANDOFF Part 6's open question
# ---------------------------------------------------------------------------

print()
print("negative UVWarp scale (mirroring)")

obj = fresh_plane("negative")
mod = add_uvwarp(obj, (0.0, 0.0), (0.0, 0.0), 0.0, (-1.5, 1.0))
check("scale.x survives being set to -1.5, unclamped",
      abs(mod.scale[0] - (-1.5)) < 1e-6, "stored %r" % (tuple(mod.scale),))

bpy.context.view_layer.update()
measured = fit_affine(source, evaluated_uvs(obj))
check("a negative scale actually reflects the evaluated UVs",
      abs(measured[0][0] - (-1.5)) < 1e-5 and np.linalg.det(measured[:, :2]) < 0.0,
      "linear %r det %.4f" % (measured[:, :2].round(4).tolist(), np.linalg.det(measured[:, :2])))


# ---------------------------------------------------------------------------
# 3. The real decomposition, end to end
# ---------------------------------------------------------------------------

print()
print("TrimAffine.uvwarp_pair against real modifiers")

TRIM_CASES = [
    ("quarter centred", (0.5, 0.5), (0.25, 0.25), 0.0, (0.0, 0.0), (2048, 2048)),
    ("rot 30 nonsquare", (0.4, 0.6), (0.3, 0.2), 30.0, (0.0, 0.0), (2048, 1024)),
    ("mirror x", (0.5, 0.5), (-0.25, 0.25), 0.0, (0.0, 0.0), (2048, 2048)),
    ("mirror x + rot 30", (0.33, 0.66), (-0.3, 0.2), 30.0, (0.0, 0.0), (2048, 1024)),
    ("mirror y + rot -47 + crop", (0.31, 0.72), (0.18, -0.44), -47.0, (0.08, 0.3), (1024, 4096)),
]

for label, position, scale, rotation, crop, resolution in TRIM_CASES:
    matrix = TrimAffine.from_trim(position, scale, rotation, crop, resolution)
    obj = fresh_plane("pair")
    for index, stage in enumerate(matrix.uvwarp_pair()):
        add_uvwarp(obj, stage.center, stage.offset, stage.rotation, stage.scale,
                   name="probe%d" % index)
    bpy.context.view_layer.update()
    got = evaluated_uvs(obj)
    want = np.array([matrix.apply(u, v) for u, v in PROBE])
    delta = np.abs(got - want).max()
    check(label, delta < 1e-5, "max delta %.6g" % delta)


# ---------------------------------------------------------------------------
# 4. Per-slot loop mask ingredients
# ---------------------------------------------------------------------------

print()
print("per-slot loop mask")

obj = fresh_plane("mask")
mesh = obj.data
have_loop_total = True
try:
    buf = np.empty(len(mesh.polygons), dtype=np.int32)
    mesh.polygons.foreach_get("loop_total", buf)
except (AttributeError, RuntimeError, TypeError) as err:
    have_loop_total = False
    print("    loop_total unavailable: %s" % err)
check("MeshPolygon.loop_total is readable via foreach_get", have_loop_total)

try:
    buf = np.empty(len(mesh.polygons), dtype=np.int32)
    mesh.polygons.foreach_get("material_index", buf)
    have_material_index = True
except (AttributeError, RuntimeError, TypeError) as err:
    have_material_index = False
    print("    material_index unavailable: %s" % err)
check("MeshPolygon.material_index is readable via foreach_get", have_material_index)


print()
print("%d/%d checks passed" % (CHECKS[0] - len(FAILURES), CHECKS[0]))
if FAILURES:
    print("failed: " + ", ".join(FAILURES))
sys.exit(1 if FAILURES else 0)
