import { readFile } from 'node:fs/promises'
import { loadImage, type Image } from '@napi-rs/canvas'

/**
 * Decodes source textures, caching for the life of one export run.
 *
 * The same asset usually appears on several trims, and every output of a preset
 * re-reads the same maps — a three-texture HDRP preset over a sheet of twenty
 * trims would otherwise decode the same PNGs dozens of times. Cache lifetime is
 * deliberately one run, so a re-export after editing a texture on disk picks up
 * the new pixels.
 *
 * A file that fails to decode resolves to null rather than throwing: a single
 * corrupt texture should cost that one trim, not the whole sheet.
 */
export class ImageLoader {
  private readonly cache = new Map<string, Promise<Image | null>>()

  load(absolutePath: string): Promise<Image | null> {
    const cached = this.cache.get(absolutePath)
    if (cached) return cached

    const pending = this.decode(absolutePath)
    this.cache.set(absolutePath, pending)
    return pending
  }

  private async decode(absolutePath: string): Promise<Image | null> {
    try {
      // Read then decode, rather than handing loadImage a path: it keeps the
      // failure modes (missing file vs. undecodable bytes) in one place.
      return await loadImage(await readFile(absolutePath))
    } catch {
      return null
    }
  }
}
