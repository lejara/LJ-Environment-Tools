import { createCanvas, type Canvas } from '@napi-rs/canvas'
import type { Asset } from '@models/Asset'
import type { ChannelSpec } from '@models/ChannelSpec'
import type { PresetOutput } from '@models/PresetOutput'
import type { TrimSheet } from '@models/TrimSheet'
import type { Channel } from '@shared/types'
import { TrimBlitter } from './trimBlitter'
import type { ImageLoader } from './imageLoader'
import type { RenderedSheet } from './renderedSheet'

const CHANNELS: Channel[] = ['R', 'G', 'B', 'A']

/**
 * Builds a channel-packed output: each output channel is filled from its own
 * source map, a constant, or its fallback.
 *
 * ## The two-canvas split
 *
 * A packed output's alpha channel carries DATA (smoothness on an HDRP mask
 * map), while compositing needs alpha to mean COVERAGE. Drawing a packed image
 * straight onto a sheet would conflate them — a trim's smoothness would decide
 * how transparently it composites.
 *
 * So the sheet is built as two canvases, both fully opaque:
 *   - `rgb`   holds output channels R, G, B
 *   - `alpha` holds output channel A as a greyscale image
 *
 * Each trim is drawn onto both with the same transform, using the trim's own
 * coverage as the blend alpha. Because both canvases stay opaque, nothing is
 * lost to premultiplication. They are merged at the end into a plain buffer.
 *
 * Uncovered sheet area gets each channel's `fallback`, which is what makes an
 * empty mask map read as unoccluded rather than fully-occluded black.
 *
 * `source: Normal` is refused at load time, so no normal rotation happens here.
 */
export class PackStrategy {
  private readonly blitter = new TrimBlitter()

  async run(
    sheet: TrimSheet,
    output: PresetOutput,
    assets: Map<string, Asset>,
    loader: ImageLoader
  ): Promise<RenderedSheet> {
    const { width, height } = sheet.resolution
    const warnings: string[] = []

    const rgb = createCanvas(width, height)
    const rgbCtx = rgb.getContext('2d')
    const alpha = createCanvas(width, height)
    const alphaCtx = alpha.getContext('2d')

    for (const ctx of [rgbCtx, alphaCtx]) {
      ctx.imageSmoothingEnabled = true
      ctx.imageSmoothingQuality = 'high'
    }

    // Background: every channel's no-data value.
    const background = CHANNELS.map((channel) => this.backgroundFor(output, channel))
    rgbCtx.fillStyle = `rgb(${background[0]}, ${background[1]}, ${background[2]})`
    rgbCtx.fillRect(0, 0, width, height)
    alphaCtx.fillStyle = `rgb(${background[3]}, ${background[3]}, ${background[3]})`
    alphaCtx.fillRect(0, 0, width, height)

    // Draw order is array order: index 0 is the bottom of the z-stack.
    // Hidden trims are skipped entirely - they behave as if they are not on
    // the sheet, which is also what the Blender addon assumes.
    for (const trim of sheet.visibleItems) {
      const asset = assets.get(trim.assetBaseName)
      if (!asset) {
        warnings.push(`"${trim.assetBaseName}" is no longer in image_dump — skipped.`)
        continue
      }

      const built = await this.buildTrim(asset, output, loader, warnings)
      if (!built) continue

      this.blitter.drawInto(rgbCtx, built.rgb, trim, sheet.resolution)
      this.blitter.drawInto(alphaCtx, built.alpha, trim, sheet.resolution)
    }

    return {
      width,
      height,
      pixels: this.merge(rgb, alpha, width, height),
      warnings
    }
  }

  /**
   * Composes one trim's packed pixels at its source resolution, as two images:
   * RGB, and A-as-greyscale. Both carry the trim's coverage in their own alpha
   * so the blit blends correctly at edges and on cut-out trims.
   */
  private async buildTrim(
    asset: Asset,
    output: PresetOutput,
    loader: ImageLoader,
    warnings: string[]
  ): Promise<{ rgb: Canvas; alpha: Canvas } | null> {
    // Decode every distinct source map once, not once per channel that uses it.
    const planes = new Map<string, Uint8ClampedArray>()
    const sizes: { width: number; height: number }[] = []
    const loaded = new Map<string, { image: Awaited<ReturnType<ImageLoader['load']>> }>()

    for (const channel of CHANNELS) {
      const spec = output.channels.get(channel)
      if (!spec?.source || spec.isConstant || loaded.has(spec.source)) continue

      const path = asset.pathFor(spec.source)
      if (!path) {
        warnings.push(
          `"${asset.baseName}" has no ${spec.source} map — channel ${channel} fell back to ${spec.fallback}.`
        )
        loaded.set(spec.source, { image: null })
        continue
      }

      const image = await loader.load(path)
      if (!image) {
        warnings.push(`Could not decode ${path} — channel ${channel} fell back to ${spec.fallback}.`)
      } else {
        sizes.push({ width: image.width, height: image.height })
      }
      loaded.set(spec.source, { image })
    }

    // Coverage comes from the primary map's alpha, so cut-out trims stay cut
    // out in a packed output instead of becoming opaque rectangles.
    const primaryPath = asset.primaryPath
    const primary = primaryPath ? await loader.load(primaryPath) : null
    if (primary) sizes.push({ width: primary.width, height: primary.height })

    // Sample everything at the largest involved map, so a 2K roughness isn't
    // thrown away because the metallic beside it is 512.
    const workWidth = Math.max(1, ...sizes.map((size) => size.width))
    const workHeight = Math.max(1, ...sizes.map((size) => size.height))

    for (const [mapName, entry] of loaded) {
      if (entry.image) planes.set(mapName, this.rasterize(entry.image, workWidth, workHeight))
    }
    const coverage = primary ? this.rasterize(primary, workWidth, workHeight) : null

    const count = workWidth * workHeight
    const rgbData = new Uint8ClampedArray(count * 4)
    const alphaData = new Uint8ClampedArray(count * 4)

    const specs = CHANNELS.map((channel) => output.channels.get(channel) ?? null)

    for (let p = 0; p < count; p += 1) {
      const i = p * 4
      const cover = coverage ? coverage[i + 3] : 255

      rgbData[i] = this.sample(specs[0], planes, i, 'R')
      rgbData[i + 1] = this.sample(specs[1], planes, i, 'G')
      rgbData[i + 2] = this.sample(specs[2], planes, i, 'B')
      rgbData[i + 3] = cover

      const a = this.sample(specs[3], planes, i, 'A')
      alphaData[i] = a
      alphaData[i + 1] = a
      alphaData[i + 2] = a
      alphaData[i + 3] = cover
    }

    return {
      rgb: this.toCanvas(rgbData, workWidth, workHeight),
      alpha: this.toCanvas(alphaData, workWidth, workHeight)
    }
  }

  /** Value for one output channel at one pixel. */
  private sample(
    spec: ChannelSpec | null,
    planes: Map<string, Uint8ClampedArray>,
    index: number,
    channel: Channel
  ): number {
    // An undeclared channel contributes nothing, except alpha which defaults
    // opaque — an output that ignores A shouldn't come out fully transparent.
    if (!spec) return channel === 'A' ? 255 : 0
    if (spec.isConstant) return Math.round((spec.constant ?? 0) * 255)

    const plane = spec.source ? planes.get(spec.source) : undefined
    // Fallback is used AS-IS and is never run back through `invert` — the
    // number written in the preset is the number that lands in the channel.
    if (!plane) return Math.round(spec.fallback * 255)

    let value: number
    switch (spec.fromChannel) {
      case 'R':
        value = plane[index]
        break
      case 'G':
        value = plane[index + 1]
        break
      case 'B':
        value = plane[index + 2]
        break
      case 'A':
        value = plane[index + 3]
        break
      default:
        // Rec.709 luminance. On a genuinely greyscale map (roughness, AO) every
        // channel is equal and the weights don't matter; on a colour one this
        // is the perceptually correct reduction.
        value = 0.2126 * plane[index] + 0.7152 * plane[index + 1] + 0.0722 * plane[index + 2]
    }

    return Math.round(spec.invert ? 255 - value : value)
  }

  /** Value for uncovered sheet area. */
  private backgroundFor(output: PresetOutput, channel: Channel): number {
    const spec = output.channels.get(channel)
    if (!spec) return channel === 'A' ? 255 : 0
    if (spec.isConstant) return Math.round((spec.constant ?? 0) * 255)
    return Math.round(spec.fallback * 255)
  }

  /** Draws a source map at the working resolution and reads its pixels back. */
  private rasterize(
    image: NonNullable<Awaited<ReturnType<ImageLoader['load']>>>,
    width: number,
    height: number
  ): Uint8ClampedArray {
    const canvas = createCanvas(width, height)
    const ctx = canvas.getContext('2d')
    ctx.imageSmoothingEnabled = true
    ctx.imageSmoothingQuality = 'high'
    ctx.drawImage(image, 0, 0, width, height)
    return ctx.getImageData(0, 0, width, height).data
  }

  private toCanvas(pixels: Uint8ClampedArray, width: number, height: number): Canvas {
    const canvas = createCanvas(width, height)
    const ctx = canvas.getContext('2d')
    const data = ctx.createImageData(width, height)
    data.data.set(pixels)
    ctx.putImageData(data, 0, 0)
    return canvas
  }

  /** RGB from one canvas, A from the other's red channel. */
  private merge(rgb: Canvas, alpha: Canvas, width: number, height: number): Uint8ClampedArray {
    const rgbData = rgb.getContext('2d').getImageData(0, 0, width, height).data
    const alphaData = alpha.getContext('2d').getImageData(0, 0, width, height).data

    const out = new Uint8ClampedArray(width * height * 4)
    for (let i = 0; i < out.length; i += 4) {
      out[i] = rgbData[i]
      out[i + 1] = rgbData[i + 1]
      out[i + 2] = rgbData[i + 2]
      out[i + 3] = alphaData[i]
    }
    return out
  }
}
