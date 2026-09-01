import type { SerializedCrop } from '@shared/types'

/**
 * Symmetric inset into the source image, normalized 0-0.5 per axis.
 *
 * `x` is trimmed off the left AND the right edge; `y` off the top AND the
 * bottom. So x = 0.1 keeps the middle 80% horizontally, and the trim stays
 * centred as it is cropped in. Clamped below 0.5 so a crop can never collapse
 * the image to nothing.
 */
export class Crop {
  static readonly MAX = 0.499

  constructor(
    public x: number = 0,
    public y: number = 0
  ) {}

  clone(): Crop {
    return new Crop(this.x, this.y)
  }

  /** Fraction of the source that survives the crop, per axis. */
  get keptWidth(): number {
    return 1 - this.x * 2
  }

  get keptHeight(): number {
    return 1 - this.y * 2
  }

  static clamp(value: number): number {
    if (Number.isNaN(value)) return 0
    return Math.min(Math.max(value, 0), Crop.MAX)
  }

  serialize(): SerializedCrop {
    return { x: this.x, y: this.y }
  }

  static deserialize(raw: SerializedCrop): Crop {
    return new Crop(Crop.clamp(raw.x), Crop.clamp(raw.y))
  }
}
