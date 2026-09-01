import { createCanvas } from '@napi-rs/canvas'
import { PNG } from 'pngjs'
import type { OutputFormat } from '@shared/types'

const JPEG_QUALITY = 92

/**
 * Encodes a finished sheet — raw, UNPREMULTIPLIED RGBA — into output bytes.
 *
 * ## Why this takes a buffer and not a canvas
 *
 * A canvas surface stores premultiplied alpha. That is correct for pictures,
 * but a packed output's alpha channel is data, not coverage: on an HDRP mask
 * map it is smoothness. Round-tripping such an image through a canvas destroys
 * it — a pixel of (metallic 200, AO 100, detail 50, smoothness 0) comes back as
 * (0, 0, 0, 0), silently wiping three channels wherever the surface happens to
 * be fully rough. Verified against @napi-rs/canvas, not assumed.
 *
 * So PNG encoding goes through pngjs, which writes the bytes it is given. The
 * canvas is only used for JPEG, which has no alpha to lose.
 */
export class ImageEncoder {
  async encode(
    pixels: Uint8ClampedArray,
    width: number,
    height: number,
    format: OutputFormat
  ): Promise<Buffer> {
    switch (format) {
      case 'PNG_RGBA':
        return this.encodePng(pixels, width, height)

      case 'PNG_RGB':
        return this.encodePng(this.flatten(pixels), width, height)

      case 'JPG':
        return this.encodeJpeg(this.flatten(pixels), width, height)

      case 'TGA':
        return this.encodeTga(pixels, width, height)
    }
  }

  private encodePng(pixels: Uint8ClampedArray, width: number, height: number): Buffer {
    const png = new PNG({ width, height })
    png.data.set(pixels)
    return PNG.sync.write(png)
  }

  /**
   * Composites onto opaque black for the formats that can't carry alpha.
   * Done here in the buffer rather than on a canvas so the source RGB is the
   * real unpremultiplied value.
   */
  private flatten(pixels: Uint8ClampedArray): Uint8ClampedArray {
    const out = new Uint8ClampedArray(pixels.length)
    for (let i = 0; i < pixels.length; i += 4) {
      const alpha = pixels[i + 3] / 255
      out[i] = pixels[i] * alpha
      out[i + 1] = pixels[i + 1] * alpha
      out[i + 2] = pixels[i + 2] * alpha
      out[i + 3] = 255
    }
    return out
  }

  private async encodeJpeg(
    pixels: Uint8ClampedArray,
    width: number,
    height: number
  ): Promise<Buffer> {
    // Safe on a canvas: `flatten` has made every pixel opaque, so there is no
    // premultiplication left to lose.
    const canvas = createCanvas(width, height)
    const ctx = canvas.getContext('2d')
    const data = ctx.createImageData(width, height)
    data.data.set(pixels)
    ctx.putImageData(data, 0, 0)
    return canvas.encode('jpeg', JPEG_QUALITY)
  }

  /**
   * Uncompressed 32-bit TGA. @napi-rs/canvas doesn't encode TGA and the format
   * is small enough to write directly: an 18-byte header then bottom-up BGRA.
   */
  private encodeTga(pixels: Uint8ClampedArray, width: number, height: number): Buffer {
    const header = Buffer.alloc(18)
    header.writeUInt8(2, 2) // uncompressed true-colour
    header.writeUInt16LE(width, 12)
    header.writeUInt16LE(height, 14)
    header.writeUInt8(32, 16) // bits per pixel
    header.writeUInt8(8, 17) // 8 bits of alpha, origin bottom-left

    const out = Buffer.alloc(width * height * 4)
    for (let y = 0; y < height; y += 1) {
      // TGA rows run bottom-up when the origin bit is clear.
      const source = (height - 1 - y) * width * 4
      const target = y * width * 4
      for (let x = 0; x < width; x += 1) {
        const s = source + x * 4
        const t = target + x * 4
        out[t] = pixels[s + 2] // B
        out[t + 1] = pixels[s + 1] // G
        out[t + 2] = pixels[s] // R
        out[t + 3] = pixels[s + 3] // A
      }
    }

    return Buffer.concat([header, out])
  }
}
