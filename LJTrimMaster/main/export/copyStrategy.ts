import { createCanvas, type Canvas, type SKRSContext2D } from '@napi-rs/canvas'
import type { Asset } from '@models/Asset'
import type { PresetOutput } from '@models/PresetOutput'
import type { TrimSheet } from '@models/TrimSheet'
import type { TrimImage } from '@models/TrimImage'
import { NormalRotator } from './normalRotator'
import { TrimBlitter, type Drawable } from './trimBlitter'
import type { ImageLoader } from './imageLoader'
import type { RenderedSheet } from './renderedSheet'

/**
 * Passes one map through: for every trim on the sheet, samples that trim's
 * copy of the map, applies crop and transform, and blits it onto the canvas.
 *
 * The sheet starts transparent — a copy output is a picture, and empty space in
 * a picture is nothing rather than black.
 *
 * When the source is a Normal map the blit routes through `renderIsolated` so
 * the encoded vectors can be rotated after the pixels are rotated but before
 * they reach the shared canvas.
 */
export class CopyStrategy {
  private readonly blitter = new TrimBlitter()
  private readonly rotator = new NormalRotator()

  async run(
    sheet: TrimSheet,
    output: PresetOutput,
    assets: Map<string, Asset>,
    loader: ImageLoader
  ): Promise<RenderedSheet> {
    const canvas = createCanvas(sheet.resolution.width, sheet.resolution.height)
    const ctx = canvas.getContext('2d')
    ctx.imageSmoothingEnabled = true
    ctx.imageSmoothingQuality = 'high'

    const { width, height } = sheet.resolution
    const warnings: string[] = []
    const mapName = output.source
    if (!mapName) {
      // The loader rejects a copy output with no source, so this is defensive.
      return { width, height, pixels: this.read(canvas), warnings: ['copy output has no source map.'] }
    }

    // Draw order is array order: index 0 is the bottom of the z-stack.
    for (const trim of sheet.items) {
      const asset = assets.get(trim.assetBaseName)
      if (!asset) {
        warnings.push(`"${trim.assetBaseName}" is no longer in image_dump — skipped.`)
        continue
      }

      const path = asset.pathFor(mapName)
      if (!path) {
        // Not an error: a sheet can legitimately mix assets that have a Normal
        // with ones that don't. The trim simply contributes nothing here.
        warnings.push(`"${trim.assetBaseName}" has no ${mapName} map — left empty in this output.`)
        continue
      }

      const image = await loader.load(path)
      if (!image) {
        warnings.push(`Could not decode ${path} — skipped.`)
        continue
      }

      if (output.isNormalSource) {
        this.drawRotatedNormal(ctx, image, trim, sheet, output)
      } else {
        this.blitter.drawInto(ctx, image, trim, sheet.resolution)
      }
    }

    return { width, height, pixels: this.read(canvas), warnings }
  }

  /**
   * Reads the composited sheet back as unpremultiplied RGBA. For a copy output
   * alpha genuinely is coverage, so the premultiply round-trip is lossless
   * except in fully transparent pixels, which carry no colour to lose.
   */
  private read(canvas: Canvas): Uint8ClampedArray {
    return canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data
  }

  /**
   * Normal maps carry direction, not colour, so rotating the pixels is only
   * half the job — the vectors they encode have to turn by the same angle.
   *
   * The trim is rendered alone into a bounding-box canvas, its vectors are
   * rewritten in place, and only then is it composited. Doing the pixel pass on
   * the sheet itself would re-rotate every trim already sitting underneath.
   */
  private drawRotatedNormal(
    ctx: SKRSContext2D,
    image: Drawable,
    trim: TrimImage,
    sheet: TrimSheet,
    output: PresetOutput
  ): void {
    const isolated = this.blitter.renderIsolated(image, trim, sheet.resolution)
    if (!isolated) return

    const { transform } = trim
    const isIdentity =
      transform.rotation % 360 === 0 && transform.scale.x >= 0 && transform.scale.y >= 0

    if (!isIdentity) {
      const isolatedCtx = isolated.canvas.getContext('2d')
      const data = isolatedCtx.getImageData(0, 0, isolated.canvas.width, isolated.canvas.height)
      this.rotator.rotateInPlace(
        data.data,
        transform.rotation,
        { x: transform.scale.x, y: transform.scale.y },
        output.normalConvention
      )
      isolatedCtx.putImageData(data, 0, 0)
    }

    ctx.drawImage(isolated.canvas, isolated.x, isolated.y)
  }
}
