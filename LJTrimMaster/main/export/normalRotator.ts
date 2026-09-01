import type { NormalConvention } from '@shared/types'

/**
 * Rotates the encoded vectors in a normal map so lighting stays correct on a
 * rotated trim.
 *
 * The (R,G) pair is a direction in tangent space, so when the trim's pixels are
 * rotated the vectors have to turn with them. B is the Z component — it points
 * out of the surface and is unaffected by a rotation in the plane.
 *
 * ## Why the convention matters
 *
 * R always encodes +X to the right. G is where the two conventions disagree:
 * OpenGL encodes +Y **upward** on screen, DirectX encodes it **downward**.
 * Working in screen coordinates (y down) and rotating counter-clockwise by θ:
 *
 *     x' =  x·cosθ + y·sinθ
 *     y' = -x·sinθ + y·cosθ
 *
 * Substituting y = -G for OpenGL and y = +G for DirectX gives:
 *
 *     OpenGL    R' = R·cosθ - G·sinθ     G' =  R·sinθ + G·cosθ
 *     DirectX   R' = R·cosθ + G·sinθ     G' = -R·sinθ + G·cosθ
 *
 * which differ only in the sign of sinθ — so the whole convention collapses to
 * one sign flip below. Get it backwards and rotated trims light as though the
 * sun moved, which is subtle enough to survive a long way into a scene.
 *
 * ## Mirroring
 *
 * A negative scale axis mirrors the geometry, which negates that axis of the
 * encoded vector. Mirroring is applied BEFORE the rotation, matching the blit,
 * where the canvas scale is applied to the image before the canvas rotation.
 * A flip negates G in both conventions (G = ±y, and y itself negates), so this
 * part is convention-independent.
 */
export class NormalRotator {
  /**
   * @param pixels RGBA8 buffer, mutated in place. Unpremultiplied.
   * @param degrees trim rotation, counter-clockwise.
   * @param scaleSign sign of each scale axis: -1 mirrors, +1 leaves alone.
   * @param convention handedness of the source map.
   */
  rotateInPlace(
    pixels: Uint8ClampedArray,
    degrees: number,
    scaleSign: { x: number; y: number },
    convention: NormalConvention = 'OpenGL'
  ): void {
    const flipX = scaleSign.x < 0 ? -1 : 1
    const flipY = scaleSign.y < 0 ? -1 : 1
    const rotation = ((degrees % 360) + 360) % 360

    // Nothing to do — skip the whole buffer rather than burning a pass
    // re-encoding every pixel to the value it already had.
    if (rotation === 0 && flipX === 1 && flipY === 1) return

    const radians = (rotation * Math.PI) / 180
    const cos = Math.cos(radians)
    // The one place the convention lives: DirectX is OpenGL with sinθ negated.
    const sin = Math.sin(radians) * (convention === 'DirectX' ? -1 : 1)

    for (let i = 0; i < pixels.length; i += 4) {
      // Fully transparent pixels carry no vector worth turning, and their RGB
      // is usually zero, which would decode to a bogus (-1,-1).
      if (pixels[i + 3] === 0) continue

      // Decode 0..255 to -1..1, mirror, rotate, re-encode.
      const r = (pixels[i] / 255) * 2 - 1
      const g = (pixels[i + 1] / 255) * 2 - 1

      const mx = r * flipX
      const my = g * flipY

      const rx = mx * cos - my * sin
      const ry = mx * sin + my * cos

      pixels[i] = Math.round(((rx + 1) / 2) * 255)
      pixels[i + 1] = Math.round(((ry + 1) / 2) * 255)
      // B and A are left exactly as they were.
    }
  }
}
