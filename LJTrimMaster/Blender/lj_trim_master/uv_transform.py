# SPDX-License-Identifier: GPL-3.0-or-later
"""The trim affine: source-image UV space -> trim-sheet UV space.

**Imports no ``bpy``.** The math is the one thing in this add-on that has to be
provably right, so it is kept in plain Python and exercised by tests that need
no Blender at all.

It must agree with ``main/export/trimBlitter.ts`` **exactly**. That file draws
the pixels; this file moves the UVs onto them. If they disagree the textures are
subtly misaligned and nothing errors.

Derivation
----------
``TrimBlitter`` composes, in canvas space (origin top-left, Y down)::

    translate(centre) -> rotate(-t) -> scale(flipX, flipY) -> drawImage(crop box)

Read as a mapping from a normalized source-image coordinate to a normalized
sheet coordinate, with ``W``/``H`` the sheet resolution in pixels::

    canvas    sx = u,  sy = 1 - v                     # Blender V up, canvas Y down
    crop      bu = (sx - cx)/kw,  bv = (sy - cy)/kh   # kw = 1-2cx, kh = 1-2cy
    box px    px = (bu - 0.5)*Sx*W                    # Sx signed - the sign IS the mirror
              py = (bv - 0.5)*Sy*H
    rotate    x' =  px*cos(t) + py*sin(t)             # canvas rotate(-t); t CCW-positive
              y' = -px*sin(t) + py*cos(t)
    sheet     U = Px + x'/W
              V = 1 - (Py + y'/H)

Every step is affine in ``(u, v)``, so the whole thing collapses to one 2x3
matrix. Two properties of it are load-bearing:

**Rotation runs in sheet pixels.** ``W`` and ``H`` sit inside the rotation, not
outside it, which is why the linear part is ``diag(1/W,1/H) . R(t) . diag(...)``
and not a similarity transform. Rotating in normalized space would shear on a
non-square sheet and the UVs would stop matching the exported PNG.

**Source image dimensions cancel.** Crop is normalized and the kept region is
stretched to fill the box, so the matrix holds whatever the source file's pixel
size is. The add-on never opens an image to learn its geometry.
"""

import math

__all__ = ["TrimAffine", "UVWarpStage", "is_degenerate"]


class UVWarpStage:
    """Parameters for one Blender UVWarp modifier."""

    __slots__ = ("center", "offset", "rotation", "scale")

    def __init__(self, center, offset, rotation, scale):
        self.center = center
        self.offset = offset
        self.rotation = rotation
        self.scale = scale

    def __repr__(self):
        return (
            "UVWarpStage(center=%r, offset=%r, rotation=%r, scale=%r)"
            % (self.center, self.offset, self.rotation, self.scale)
        )


class TrimAffine:
    """A trim's placement as one 2x3 matrix over ``(u, v)``.

    ``U = m00*u + m01*v + m02``
    ``V = m10*u + m11*v + m12``
    """

    __slots__ = ("m00", "m01", "m02", "m10", "m11", "m12")

    def __init__(self, m00, m01, m02, m10, m11, m12):
        self.m00 = m00
        self.m01 = m01
        self.m02 = m02
        self.m10 = m10
        self.m11 = m11
        self.m12 = m12

    # -- construction -------------------------------------------------------

    @classmethod
    def identity(cls):
        return cls(1.0, 0.0, 0.0, 0.0, 1.0, 0.0)

    @classmethod
    def from_trim(cls, position, scale, rotation_degrees, crop, resolution):
        """Build the matrix for one trim.

        *position* and *scale* are normalized against the sheet, *position*
        being the trim's centre and a negative *scale* component mirroring that
        axis. *rotation_degrees* is counter-clockwise-positive. *crop* is the
        symmetric normalized inset ``(cx, cy)``. *resolution* is the sheet's
        ``(width, height)`` in pixels.
        """
        pos_x, pos_y = float(position[0]), float(position[1])
        scale_x, scale_y = float(scale[0]), float(scale[1])
        crop_x, crop_y = float(crop[0]), float(crop[1])
        width, height = float(resolution[0]), float(resolution[1])

        # Crop is clamped to 0.499 by the tool, so these stay well away from
        # zero; the guard is for a hand-edited projectData.json.
        kept_w = _nonzero(1.0 - 2.0 * crop_x)
        kept_h = _nonzero(1.0 - 2.0 * crop_y)
        width = _nonzero(width)
        height = _nonzero(height)

        radians = math.radians(rotation_degrees)
        cos_t = math.cos(radians)
        sin_t = math.sin(radians)

        # px = a*u + b,  py = c*v + d   (canvas pixels, relative to the centre)
        a = scale_x * width / kept_w
        b = -scale_x * width * (crop_x / kept_w + 0.5)
        c = -scale_y * height / kept_h
        d = scale_y * height * ((1.0 - crop_y) / kept_h - 0.5)

        return cls(
            a * cos_t / width,
            c * sin_t / width,
            pos_x + (b * cos_t + d * sin_t) / width,
            a * sin_t / height,
            -c * cos_t / height,
            1.0 - pos_y + (b * sin_t - d * cos_t) / height,
        )

    # -- use ----------------------------------------------------------------

    def apply(self, u, v):
        """Map one UV. Used by the tests; the export path goes through numpy."""
        return (
            self.m00 * u + self.m01 * v + self.m02,
            self.m10 * u + self.m11 * v + self.m12,
        )

    @property
    def determinant(self):
        return self.m00 * self.m11 - self.m01 * self.m10

    @property
    def is_mirrored(self):
        return self.determinant < 0.0

    @property
    def is_singular(self):
        """Collapsed to a line or a point - not invertible, so no UVWarp pair."""
        return abs(self.determinant) < 1e-12

    def coefficients(self):
        return (self.m00, self.m01, self.m02, self.m10, self.m11, self.m12)

    def approx_equal(self, other, tolerance=1e-6):
        return all(
            abs(x - y) <= tolerance
            for x, y in zip(self.coefficients(), other.coefficients())
        )

    def __repr__(self):
        return "TrimAffine(%.6f, %.6f, %.6f, %.6f, %.6f, %.6f)" % self.coefficients()

    # -- the evaluated path -------------------------------------------------

    def uvwarp_pair(self):
        """Decompose into the two UVWarp modifiers that reproduce this matrix.

        Blender's UVWarp is (measured, see the export-hook test add-on)::

            uv' = S . R . (uv + offset - center) + center

        so one modifier's linear part is ``S.R`` - a diagonal times a rotation.
        Ours is an arbitrary 2x2, so a single UVWarp cannot express it: matching
        a general matrix against ``S.R`` forces a zero rotation or a uniform
        scale.

        Two chained ones reach any 2x2 exactly, because ``S2.R2 . S1.R1`` with
        ``S2 = I`` is ``R(p) . diag(a,b) . R(q)`` - the SVD form, with the
        singular values in ``diag``. Closed form for 2x2, from::

            m00 + m11 = (a + b) cos(p + q)      m10 - m01 = (a + b) sin(p + q)
            m00 - m11 = (a - b) cos(p - q)      m10 + m01 = (a - b) sin(p - q)

        **Reflections are covered.** A mirrored trim has ``det < 0``, which no
        decomposition into pure rotations and non-negative singular values can
        produce. Negating the matrix's second column flips the determinant
        positive; folding that back out uses
        ``R(q).diag(1,-1) == diag(1,-1).R(-q)``, so the reflection lands as a
        negative ``b`` and a negated ``q``. Blender's UVWarp ``scale`` accepts a
        negative component (verified headlessly), so this is representable.

        Translation is then free: with both centres at the origin and the first
        modifier's offset zero, the first stage is purely linear and the second
        stage's offset only has to satisfy ``R(p) . offset = T``.
        """
        m00, m01, m10, m11 = self.m00, self.m01, self.m10, self.m11

        mirrored = self.determinant < 0.0
        if mirrored:
            m01, m11 = -m01, -m11

        sum_cos = m00 + m11
        sum_sin = m10 - m01
        dif_cos = m00 - m11
        dif_sin = m10 + m01

        total = math.hypot(sum_cos, sum_sin)
        spread = math.hypot(dif_cos, dif_sin)
        scale_a = (total + spread) / 2.0
        scale_b = (total - spread) / 2.0

        angle_sum = math.atan2(sum_sin, sum_cos)   # p + q
        angle_dif = math.atan2(dif_sin, dif_cos)   # p - q
        p = (angle_sum + angle_dif) / 2.0
        q = (angle_sum - angle_dif) / 2.0

        if mirrored:
            scale_b = -scale_b
            q = -q

        # R(-p) . T, so that R(p) . offset == T.
        cos_p = math.cos(p)
        sin_p = math.sin(p)
        offset_u = cos_p * self.m02 + sin_p * self.m12
        offset_v = -sin_p * self.m02 + cos_p * self.m12

        return (
            UVWarpStage((0.0, 0.0), (0.0, 0.0), q, (scale_a, scale_b)),
            UVWarpStage((0.0, 0.0), (offset_u, offset_v), p, (1.0, 1.0)),
        )


def _nonzero(value, epsilon=1e-9):
    """Keep a divisor away from zero without changing its sign."""
    if -epsilon < value < epsilon:
        return epsilon if value >= 0.0 else -epsilon
    return value


def is_degenerate(scale, resolution):
    """True when the trim covers less than half a pixel on the sheet.

    Mirrors ``TrimBlitter.isDegenerate``, which draws nothing in that case. The
    transform is still applied - the matrix is the truth and the sheet simply
    has no pixels there - but the caller warns.
    """
    return (
        abs(float(scale[0])) * float(resolution[0]) < 0.5
        or abs(float(scale[1])) * float(resolution[1]) < 0.5
    )
