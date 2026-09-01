import { createCanvas, type Canvas, type Image, type SKRSContext2D } from '@napi-rs/canvas'
import type { Resolution } from '@models/Resolution'
import type { TrimImage } from '@models/TrimImage'

/** Anything that can be a drawImage source: a decoded file or a built canvas. */
export type Drawable = Image | Canvas

/** A trim's placement resolved from normalized values into sheet pixels. */
export interface Placement {
  /** Centre, in sheet pixels. */
  centreX: number
  centreY: number
  /** Size, in sheet pixels. Always positive; mirroring lives in the flips. */
  width: number
  height: number
  flipX: number
  flipY: number
  /** Counter-clockwise, radians. */
  radians: number
}

/** Antialiased edges spill about a pixel; give the isolated canvas room. */
const BBOX_PAD = 2

/**
 * Draws one trim onto a sheet, applying its transform and crop.
 *
 * Shared by both strategies so the geometry is defined exactly once — a copy
 * output and a packed output must land on identical pixels, otherwise a
 * material's BaseColor and MaskMap wouldn't line up.
 *
 * ## Rotation sign
 *
 * `Transform.rotation` is counter-clockwise-positive, the convention artists
 * expect. Canvas `rotate()` is clockwise-positive because its y axis points
 * down, so every rotation here is negated on the way in. The Viewport negates
 * the same way, which is what keeps the preview honest.
 */
export class TrimBlitter {
  place(trim: TrimImage, resolution: Resolution): Placement {
    const { position, scale, rotation } = trim.transform
    return {
      centreX: position.x * resolution.width,
      centreY: position.y * resolution.height,
      width: Math.abs(scale.x) * resolution.width,
      height: Math.abs(scale.y) * resolution.height,
      flipX: scale.x < 0 ? -1 : 1,
      flipY: scale.y < 0 ? -1 : 1,
      radians: (rotation * Math.PI) / 180
    }
  }

  /** A trim scaled to nothing has no pixels to contribute. */
  isDegenerate(placement: Placement): boolean {
    return placement.width < 0.5 || placement.height < 0.5
  }

  drawInto(
    ctx: SKRSContext2D,
    source: Drawable,
    trim: TrimImage,
    resolution: Resolution
  ): boolean {
    const placement = this.place(trim, resolution)
    if (this.isDegenerate(placement)) return false

    ctx.save()
    ctx.translate(placement.centreX, placement.centreY)
    ctx.rotate(-placement.radians)
    ctx.scale(placement.flipX, placement.flipY)
    this.drawCropped(ctx, source, trim, placement.width, placement.height)
    ctx.restore()
    return true
  }

  /**
   * Renders the trim alone into its own canvas, sized to its bounding box on
   * the sheet, and reports where that canvas belongs.
   *
   * This is what makes the normal-map pass possible: the encoded vectors have
   * to be rewritten AFTER the rotation has been baked into the pixels but
   * BEFORE the trim is composited, and touching the shared sheet buffer would
   * corrupt every trim already drawn underneath.
   */
  renderIsolated(
    source: Drawable,
    trim: TrimImage,
    resolution: Resolution
  ): { canvas: Canvas; x: number; y: number } | null {
    const placement = this.place(trim, resolution)
    if (this.isDegenerate(placement)) return null

    // Axis-aligned extent of the rotated rectangle.
    const cos = Math.abs(Math.cos(placement.radians))
    const sin = Math.abs(Math.sin(placement.radians))
    const boxWidth = Math.ceil(placement.width * cos + placement.height * sin) + BBOX_PAD * 2
    const boxHeight = Math.ceil(placement.width * sin + placement.height * cos) + BBOX_PAD * 2

    const x = Math.floor(placement.centreX - boxWidth / 2)
    const y = Math.floor(placement.centreY - boxHeight / 2)

    const canvas = createCanvas(boxWidth, boxHeight)
    const ctx = canvas.getContext('2d')

    // Same transform as drawInto, but relative to the box's own origin.
    ctx.translate(placement.centreX - x, placement.centreY - y)
    ctx.rotate(-placement.radians)
    ctx.scale(placement.flipX, placement.flipY)
    this.drawCropped(ctx, source, trim, placement.width, placement.height)

    return { canvas, x, y }
  }

  /**
   * Crop is a symmetric inset, so the surviving middle of the source is
   * stretched to fill the trim's box — the same mapping the Viewport does with
   * its oversized <img>.
   */
  private drawCropped(
    ctx: SKRSContext2D,
    source: Drawable,
    trim: TrimImage,
    width: number,
    height: number
  ): void {
    const sourceWidth = source.width
    const sourceHeight = source.height

    const cropX = trim.crop.x * sourceWidth
    const cropY = trim.crop.y * sourceHeight
    const keptWidth = Math.max(trim.crop.keptWidth * sourceWidth, 1)
    const keptHeight = Math.max(trim.crop.keptHeight * sourceHeight, 1)

    ctx.drawImage(
      source as Image,
      cropX,
      cropY,
      keptWidth,
      keptHeight,
      -width / 2,
      -height / 2,
      width,
      height
    )
  }
}
