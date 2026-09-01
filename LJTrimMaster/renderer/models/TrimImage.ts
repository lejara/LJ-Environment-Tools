import { Transform } from './Transform'
import { Crop } from './Crop'
import type { SerializedTrimImage } from '@shared/types'

/**
 * One image placed on a sheet.
 *
 * References its source by `assetBaseName` rather than by an Asset object or a
 * path, so sibling maps (Roughness, Normal, ...) are re-resolved from the
 * current image_dump scan at export time — adding a Normal map later is picked
 * up with no edit here.
 */
export class TrimImage {
  constructor(
    public readonly id: string,
    public assetBaseName: string,
    public transform: Transform = new Transform(),
    public crop: Crop = new Crop()
  ) {}

  serialize(): SerializedTrimImage {
    return {
      id: this.id,
      assetBaseName: this.assetBaseName,
      transform: this.transform.serialize(),
      crop: this.crop.serialize()
    }
  }

  static deserialize(raw: SerializedTrimImage): TrimImage {
    return new TrimImage(
      raw.id,
      raw.assetBaseName,
      Transform.deserialize(raw.transform),
      Crop.deserialize(raw.crop)
    )
  }

  static create(assetBaseName: string): TrimImage {
    return new TrimImage(crypto.randomUUID(), assetBaseName)
  }
}
