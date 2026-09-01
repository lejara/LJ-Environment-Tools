import { Transform } from './Transform'
import { Crop } from './Crop'
import type { TrimImage } from './TrimImage'

/**
 * One undo step. Transform + crop only — that is the whole undo scope in v1.
 * Add / remove / rename / reorder / tab actions are deliberately not undoable.
 */
export class Snapshot {
  constructor(
    public readonly trimImageId: string,
    public readonly transform: Transform,
    public readonly crop: Crop
  ) {}

  /** Deep-copies, so later edits to the live image don't mutate the history. */
  static capture(image: TrimImage): Snapshot {
    return new Snapshot(image.id, image.transform.clone(), image.crop.clone())
  }

  /** Writes this snapshot back onto the image it came from. */
  applyTo(image: TrimImage): void {
    image.transform = this.transform.clone()
    image.crop = this.crop.clone()
  }
}
