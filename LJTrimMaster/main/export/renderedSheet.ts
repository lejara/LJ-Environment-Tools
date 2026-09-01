/**
 * What a strategy hands back: one finished sheet as raw, UNPREMULTIPLIED RGBA,
 * plus anything that quietly degraded on the way.
 *
 * Deliberately a plain buffer rather than a canvas. A packed output's alpha is
 * data (smoothness), and a canvas surface premultiplies — round-tripping such
 * an image through one wipes RGB wherever alpha is low. See ImageEncoder.
 */
export interface RenderedSheet {
  width: number
  height: number
  pixels: Uint8ClampedArray
  warnings: string[]
}
