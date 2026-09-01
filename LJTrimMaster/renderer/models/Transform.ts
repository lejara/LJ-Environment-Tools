import { Vec2 } from './Vec2'
import type { SerializedTransform } from '@shared/types'

/**
 * Placement of a trim on its sheet.
 *
 * `position` and `scale` are normalized 0-1 against the sheet's resolution, so
 * a sheet can be resized without disturbing the layout, and Phase 3's UV sync
 * gets UV-space numbers with no conversion. The UI shows them as pixels —
 * see `toPixels`/`fromPixels` on the Properties panel side.
 *
 * `position` is the trim's centre. A negative `scale` component mirrors that
 * axis (and flips the matching normal-map channel at export).
 */
export class Transform {
  constructor(
    public position: Vec2 = new Vec2(0.5, 0.5),
    public scale: Vec2 = new Vec2(0.25, 0.25),
    /** Degrees, counter-clockwise. */
    public rotation: number = 0
  ) {}

  clone(): Transform {
    return new Transform(this.position.clone(), this.scale.clone(), this.rotation)
  }

  serialize(): SerializedTransform {
    return {
      position: this.position.serialize(),
      scale: this.scale.serialize(),
      rotation: this.rotation
    }
  }

  static deserialize(raw: SerializedTransform): Transform {
    return new Transform(
      Vec2.deserialize(raw.position),
      Vec2.deserialize(raw.scale),
      raw.rotation
    )
  }
}
