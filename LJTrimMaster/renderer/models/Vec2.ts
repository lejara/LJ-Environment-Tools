import type { SerializedVec2 } from '@shared/types'

/** Value object. Immutable by convention — mutate via Transform, not in place. */
export class Vec2 {
  constructor(
    public x: number,
    public y: number
  ) {}

  clone(): Vec2 {
    return new Vec2(this.x, this.y)
  }

  equals(other: Vec2): boolean {
    return this.x === other.x && this.y === other.y
  }

  serialize(): SerializedVec2 {
    return { x: this.x, y: this.y }
  }

  static deserialize(raw: SerializedVec2): Vec2 {
    return new Vec2(raw.x, raw.y)
  }
}
