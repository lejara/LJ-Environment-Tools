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
 *
 * ## Coverage is the primary map's alpha
 *
 * A cut-out texture carries its shape in the alpha of its BaseColor. The other
 * maps beside it are usually opaque rectangles — a Normal has no idea the
 * silhouette exists — so drawing them with their own alpha would put a full
 * rectangle of normal data behind a cut-out base colour, and the trim would
 * light as though the removed parts were still there.
 *
 * So coverage for EVERY output of a trim comes from that trim's primary map,
 * exactly as `PackStrategy` already does it. An asset with no primary map falls
 * back to the drawn map's own alpha, which is the best information available.
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
    // Hidden trims are skipped entirely - they behave as if they are not on
    // the sheet, which is also what the Blender addon assumes.
    for (const trim of sheet.visibleItems) {
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

      // The primary map is the silhouette. Skipped when this output IS the
      // primary map, since its own alpha is already the coverage.
      const primaryPath = asset.primaryPath
      const needsMask = Boolean(primaryPath) && mapName !== asset.primaryMap
      const coverage = needsMask ? await loader.load(primaryPath as string) : null
      if (needsMask && !coverage) {
        warnings.push(
          `Could not decode ${primaryPath} — "${trim.assetBaseName}" drew ${mapName} without its cut-out.`
        )
      }

      if (output.isNormalSource || coverage) {
        this.drawIsolated(ctx, image, coverage, trim, sheet, output)
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
   * Renders one trim alone, applies the per-pixel passes it needs, and only
   * then composites it onto the sheet.
   *
   * Both passes have to happen off the shared canvas. Rotating normal vectors
   * on the sheet itself would re-rotate every trim already sitting underneath,
   * and masking there would punch holes in them.
   *
   * Normal maps carry direction, not colour, so rotating the pixels is only
   * half the job — the vectors they encode have to turn by the same angle.
   */
  private drawIsolated(
    ctx: SKRSContext2D,
    image: Drawable,
    coverage: Drawable | null,
    trim: TrimImage,
    sheet: TrimSheet,
    output: PresetOutput
  ): void {
    const isolated = this.blitter.renderIsolated(image, trim, sheet.resolution)
    if (!isolated) return

    const { transform } = trim
    const isIdentity =
      transform.rotation % 360 === 0 && transform.scale.x >= 0 && transform.scale.y >= 0
    const rotateVectors = output.isNormalSource && !isIdentity

    if (rotateVectors || coverage) {
      const isolatedCtx = isolated.canvas.getContext('2d')
      const data = isolatedCtx.getImageData(0, 0, isolated.canvas.width, isolated.canvas.height)

      if (rotateVectors) {
        this.rotator.rotateInPlace(
          data.data,
          transform.rotation,
          { x: transform.scale.x, y: transform.scale.y },
          output.normalConvention
        )
      }

      if (coverage) {
        // renderIsolated sizes its canvas from the trim and the sheet alone, so
        // the primary map rendered the same way lands pixel-for-pixel on top of
        // this one whatever the two source files' dimensions are.
        const mask = this.blitter.renderIsolated(coverage, trim, sheet.resolution)
        if (mask) {
          const maskData = mask.canvas
            .getContext('2d')
            .getImageData(0, 0, mask.canvas.width, mask.canvas.height).data
          for (let i = 3; i < data.data.length; i += 4) {
            data.data[i] = (data.data[i] * maskData[i]) / 255
          }
        }
      }

      isolatedCtx.putImageData(data, 0, 0)
    }

    ctx.drawImage(isolated.canvas, isolated.x, isolated.y)
  }
}
