import type { SerializedResolution } from '@shared/types'

/** Pixel dimensions of a trim sheet's output canvas. */
export class Resolution {
  constructor(
    public width: number,
    public height: number
  ) {}

  clone(): Resolution {
    return new Resolution(this.width, this.height)
  }

  get aspect(): number {
    return this.height === 0 ? 1 : this.width / this.height
  }

  serialize(): SerializedResolution {
    return { width: this.width, height: this.height }
  }

  static deserialize(raw: SerializedResolution): Resolution {
    return new Resolution(raw.width, raw.height)
  }

  static default(): Resolution {
    return new Resolution(2048, 2048)
  }
}
