# SPDX-License-Identifier: GPL-3.0-or-later
"""Plain-Python tests for the trim affine. No Blender, no numpy.

    python tests/test_affine.py

The matrix is checked against an *independent* reimplementation of
``TrimBlitter``'s canvas composition - translate, rotate(-t), scale(flip),
drawImage of the crop box - rather than against a rearrangement of the same
algebra. If the closed form in ``TrimAffine.from_trim`` is wrong, the two
disagree.
"""

import importlib.util
import math
import os
import sys

# Loaded by path, not as ``lj_trim_master.uv_transform`` - importing the package
# would run ``__init__.py``, which needs bpy. That this works at all is the
# point: the affine has no Blender dependency.
_HERE = os.path.dirname(os.path.abspath(__file__))
_SPEC = importlib.util.spec_from_file_location(
    "uv_transform", os.path.join(os.path.dirname(_HERE), "lj_trim_master", "uv_transform.py")
)
uv_transform = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(uv_transform)
TrimAffine = uv_transform.TrimAffine
is_degenerate = uv_transform.is_degenerate

FAILURES = []
CHECKS = [0]


def check(label, condition, detail=""):
    CHECKS[0] += 1
    if condition:
        print("  ok   %s" % label)
    else:
        print("  FAIL %s %s" % (label, detail))
        FAILURES.append(label)


def close(a, b, tolerance=1e-9):
    return abs(a - b) <= tolerance


def uv_close(got, want, tolerance=1e-9):
    return close(got[0], want[0], tolerance) and close(got[1], want[1], tolerance)


# ---------------------------------------------------------------------------
# Reference: TrimBlitter's canvas composition, step by step.
# ---------------------------------------------------------------------------

def blitter_reference(u, v, position, scale, rotation_degrees, crop, resolution):
    """Where does source UV (u, v) land, per TrimBlitter's own transform chain?

    Written as the sequence of canvas operations, deliberately not factored, so
    it is an independent witness rather than the same formula twice.
    """
    width, height = float(resolution[0]), float(resolution[1])
    crop_x, crop_y = float(crop[0]), float(crop[1])

    # drawImage source rect, in source-image fractions.
    kept_w = 1.0 - 2.0 * crop_x
    kept_h = 1.0 - 2.0 * crop_y

    # Canvas sampling coordinate for this UV: canvas Y runs down, Blender V up.
    sample_x = u
    sample_y = 1.0 - v

    # Position within the drawn crop box, 0-1.
    box_u = (sample_x - crop_x) / kept_w
    box_v = (sample_y - crop_y) / kept_h

    # Destination rect is (-w/2, -h/2, w, h) in the local frame, with w/h the
    # trim's *absolute* size in sheet pixels.
    box_width = abs(float(scale[0])) * width
    box_height = abs(float(scale[1])) * height
    local_x = -box_width / 2.0 + box_u * box_width
    local_y = -box_height / 2.0 + box_v * box_height

    # ctx.scale(flipX, flipY)
    local_x *= -1.0 if float(scale[0]) < 0.0 else 1.0
    local_y *= -1.0 if float(scale[1]) < 0.0 else 1.0

    # ctx.rotate(-radians): canvas rotate(a) is (x cos a - y sin a, x sin a + y cos a)
    angle = -math.radians(rotation_degrees)
    rot_x = local_x * math.cos(angle) - local_y * math.sin(angle)
    rot_y = local_x * math.sin(angle) + local_y * math.cos(angle)

    # ctx.translate(centre)
    canvas_x = float(position[0]) * width + rot_x
    canvas_y = float(position[1]) * height + rot_y

    # Back to sheet UV: canvas Y down, V up.
    return (canvas_x / width, 1.0 - canvas_y / height)


CASES = [
    ("identity", (0.5, 0.5), (1.0, 1.0), 0.0, (0.0, 0.0), (2048, 2048)),
    ("quarter centred", (0.5, 0.5), (0.25, 0.25), 0.0, (0.0, 0.0), (2048, 2048)),
    ("offset corner", (0.125, 0.875), (0.25, 0.25), 0.0, (0.0, 0.0), (2048, 2048)),
    ("rot 90", (0.5, 0.5), (0.25, 0.25), 90.0, (0.0, 0.0), (2048, 2048)),
    ("rot 30 nonsquare", (0.4, 0.6), (0.3, 0.2), 30.0, (0.0, 0.0), (2048, 1024)),
    ("rot -47 nonsquare", (0.31, 0.72), (0.18, 0.44), -47.0, (0.0, 0.0), (1024, 4096)),
    ("mirror x", (0.5, 0.5), (-0.25, 0.25), 0.0, (0.0, 0.0), (2048, 2048)),
    ("mirror y", (0.5, 0.5), (0.25, -0.25), 0.0, (0.0, 0.0), (2048, 2048)),
    ("mirror both", (0.5, 0.5), (-0.25, -0.25), 0.0, (0.0, 0.0), (2048, 2048)),
    ("mirror x + rot 30", (0.33, 0.66), (-0.3, 0.2), 30.0, (0.0, 0.0), (2048, 1024)),
    ("crop", (0.5, 0.5), (0.25, 0.25), 0.0, (0.1, 0.2), (2048, 2048)),
    ("crop + rot 30", (0.45, 0.55), (0.3, 0.15), 30.0, (0.05, 0.35), (2048, 1024)),
    ("crop + mirror + rot", (0.45, 0.55), (-0.3, 0.15), 123.0, (0.42, 0.11), (1024, 2048)),
    ("crop max", (0.5, 0.5), (0.25, 0.25), 17.0, (0.499, 0.499), (2048, 2048)),
]

PROBE_UVS = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0),
             (0.5, 0.5), (0.137, 0.891), (-0.25, 1.4)]


print("agrees with TrimBlitter's composition")
for label, position, scale, rotation, crop, resolution in CASES:
    matrix = TrimAffine.from_trim(position, scale, rotation, crop, resolution)
    worst = 0.0
    for u, v in PROBE_UVS:
        got = matrix.apply(u, v)
        want = blitter_reference(u, v, position, scale, rotation, crop, resolution)
        worst = max(worst, abs(got[0] - want[0]), abs(got[1] - want[1]))
    check(label, worst < 1e-9, "worst delta %g" % worst)


print("known-value anchors")
matrix = TrimAffine.from_trim((0.5, 0.5), (0.25, 0.25), 0.0, (0.0, 0.0), (2048, 2048))
check("identity-ish maps (0,0) -> (0.375, 0.375)",
      uv_close(matrix.apply(0.0, 0.0), (0.375, 0.375)), repr(matrix.apply(0.0, 0.0)))
check("identity-ish maps (1,1) -> (0.625, 0.625)",
      uv_close(matrix.apply(1.0, 1.0), (0.625, 0.625)), repr(matrix.apply(1.0, 1.0)))

matrix = TrimAffine.from_trim((0.5, 0.5), (1.0, 1.0), 0.0, (0.0, 0.0), (2048, 2048))
check("full-sheet trim is the identity",
      matrix.approx_equal(TrimAffine.identity(), 1e-12), repr(matrix))

matrix = TrimAffine.from_trim((0.5, 0.5), (0.25, 0.25), 90.0, (0.0, 0.0), (2048, 2048))
check("+90 rotates U into V (CCW in UV space)",
      uv_close(matrix.apply(1.0, 0.0), (0.625, 0.625))
      and uv_close(matrix.apply(0.0, 1.0), (0.375, 0.375)),
      "%r %r" % (matrix.apply(1.0, 0.0), matrix.apply(0.0, 1.0)))

# Rotation must happen in sheet *pixels*: a 512x256 px box rotated 90 degrees
# becomes 256x512 px, which on a 2048x1024 sheet is 0.125 x 0.5 normalized.
matrix = TrimAffine.from_trim((0.5, 0.5), (0.25, 0.25), 90.0, (0.0, 0.0), (2048, 1024))
u_extent = abs(matrix.apply(0.0, 1.0)[0] - matrix.apply(0.0, 0.0)[0])
v_extent = abs(matrix.apply(1.0, 0.0)[1] - matrix.apply(0.0, 0.0)[1])
check("rotation runs in sheet pixels, not normalized space",
      close(u_extent, 0.125, 1e-9) and close(v_extent, 0.5, 1e-9),
      "u %g v %g" % (u_extent, v_extent))

# Crop is normalized, and the kept region stretches to fill the box, so the
# source file's pixel size cannot enter the matrix. Nothing to vary here - the
# assertion is that the matrix has no source-dimension parameter at all.
check("matrix takes no source-image dimensions",
      TrimAffine.from_trim.__func__.__code__.co_varnames[1:6]
      == ("position", "scale", "rotation_degrees", "crop", "resolution"),
      str(TrimAffine.from_trim.__func__.__code__.co_varnames[:6]))


print("mirroring")
check("negative scale.x is a reflection",
      TrimAffine.from_trim((0.5, 0.5), (-0.25, 0.25), 0.0, (0, 0), (2048, 2048)).is_mirrored)
check("negative scale.y is a reflection",
      TrimAffine.from_trim((0.5, 0.5), (0.25, -0.25), 0.0, (0, 0), (2048, 2048)).is_mirrored)
check("both negative is not a reflection",
      not TrimAffine.from_trim((0.5, 0.5), (-0.25, -0.25), 0.0, (0, 0), (2048, 2048)).is_mirrored)


print("UVWarp pair reconstructs the matrix")


def compose_uvwarp(stages, u, v):
    """Blender's measured UVWarp: uv' = S . R . (uv + offset - center) + center."""
    for stage in stages:
        cx, cy = stage.center
        ox, oy = stage.offset
        x = u + ox - cx
        y = v + oy - cy
        cos_r = math.cos(stage.rotation)
        sin_r = math.sin(stage.rotation)
        rx = x * cos_r - y * sin_r
        ry = x * sin_r + y * cos_r
        u = rx * stage.scale[0] + cx
        v = ry * stage.scale[1] + cy
    return (u, v)


for label, position, scale, rotation, crop, resolution in CASES:
    matrix = TrimAffine.from_trim(position, scale, rotation, crop, resolution)
    stages = matrix.uvwarp_pair()
    worst = 0.0
    for u, v in PROBE_UVS:
        got = compose_uvwarp(stages, u, v)
        want = matrix.apply(u, v)
        worst = max(worst, abs(got[0] - want[0]), abs(got[1] - want[1]))
    check(label, worst < 1e-9, "worst delta %g" % worst)

mirrored = TrimAffine.from_trim((0.5, 0.5), (-0.3, 0.2), 30.0, (0, 0), (2048, 1024))
first, second = mirrored.uvwarp_pair()
check("a reflection needs a negative UVWarp scale component",
      first.scale[0] < 0.0 or first.scale[1] < 0.0,
      repr(first.scale))
check("the second stage is rotation-only",
      close(second.scale[0], 1.0) and close(second.scale[1], 1.0),
      repr(second.scale))


print("degeneracy")
check("a sub-half-pixel trim is degenerate",
      is_degenerate((0.0001, 0.25), (2048, 2048)))
check("a normal trim is not",
      not is_degenerate((0.25, 0.25), (2048, 2048)))
check("zero scale is degenerate",
      is_degenerate((0.0, 0.0), (2048, 2048)))
check("zero scale does not raise",
      TrimAffine.from_trim((0.5, 0.5), (0.0, 0.0), 0.0, (0, 0), (2048, 2048)).is_singular)


print()
print("%d/%d checks passed" % (CHECKS[0] - len(FAILURES), CHECKS[0]))
if FAILURES:
    print("failed: " + ", ".join(FAILURES))
    sys.exit(1)
