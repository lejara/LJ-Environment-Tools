import { readdir } from 'node:fs/promises'
import { basename, extname, join } from 'node:path'
import { Asset } from '@models/Asset'
import { MapConfig } from '@models/MapConfig'

/**
 * Walks image_dump/ and groups files into Assets by base name + known suffix.
 *
 * `wood_BaseColor.png` and `wood_Normal.png` become one Asset "wood" with two
 * maps. A file whose suffix isn't in the map vocabulary is treated as an
 * untagged asset named after the whole filename, mapped as the primary — so a
 * plain `brick.png` still shows up and is usable.
 *
 * Several delimiters can be configured at once. Rather than ranking them, each
 * stem is normalized (every configured delimiter rewritten to a single `_`)
 * and then split on that one delimiter — so `wood-Normal.png` and
 * `wood_Roughness.png` land on the same asset.
 */
export class AssetScanner {
  private static readonly IMAGE_EXTENSIONS = new Set([
    '.png',
    '.jpg',
    '.jpeg',
    '.tga',
    '.bmp',
    '.tif',
    '.tiff'
  ])

  async scan(
    imageDumpPath: string,
    mapConfig: MapConfig
  ): Promise<{ assets: Asset[]; warnings: string[] }> {
    let entries: string[]
    try {
      const dirents = await readdir(imageDumpPath, { withFileTypes: true })
      entries = dirents.filter((d) => d.isFile()).map((d) => d.name)
    } catch {
      // No image_dump yet (fresh project, or the folder was moved) — not fatal.
      return { assets: [], warnings: [] }
    }

    // baseName -> (mapName -> absolute path)
    const grouped = new Map<string, Map<string, string>>()
    const warnings: string[] = []

    for (const fileName of entries) {
      const ext = extname(fileName).toLowerCase()
      if (!AssetScanner.IMAGE_EXTENSIONS.has(ext)) continue

      const stem = fileName.slice(0, fileName.length - ext.length)
      const { baseName, mapName } = this.split(stem, mapConfig)

      let maps = grouped.get(baseName)
      if (!maps) {
        maps = new Map()
        grouped.set(baseName, maps)
      }

      // Two files can land on the same slot — differing extensions, or two
      // delimiter conventions that normalize together. First wins, but say so:
      // silently dropping a texture the user can see in the folder is the kind
      // of thing that costs an hour to work out.
      const existing = maps.get(mapName)
      if (existing) {
        warnings.push(
          `image_dump: "${fileName}" and "${basename(existing)}" both resolve to ${baseName} / ${mapName} — using "${basename(existing)}".`
        )
        continue
      }
      maps.set(mapName, join(imageDumpPath, fileName))
    }

    const assets: Asset[] = []
    for (const [baseName, maps] of grouped) {
      // The asset's primary is the configured primary when present, else
      // whichever map we did find — so an asset with only a Normal still lists.
      const primary = maps.has(mapConfig.primaryMap) ? mapConfig.primaryMap : [...maps.keys()][0]
      assets.push(new Asset(baseName, maps, primary))
    }

    assets.sort((a, b) => a.baseName.localeCompare(b.baseName))
    return { assets, warnings }
  }

  /**
   * Splits `wood_BaseColor` into base `wood` + map `BaseColor`, after
   * normalizing every configured delimiter to `_`.
   *
   * Matches on the LAST delimiter so base names may contain one themselves
   * (`old_wood_BaseColor` -> `old_wood`). The base name returned is the
   * NORMALIZED text, which is what makes mixed-convention files for one
   * texture group together.
   */
  private split(stem: string, mapConfig: MapConfig): { baseName: string; mapName: string } {
    const normalized = mapConfig.normalize(stem)
    const delim = MapConfig.NORMALIZED_DELIM

    const index = normalized.lastIndexOf(delim)
    if (index <= 0) return { baseName: normalized, mapName: mapConfig.primaryMap }

    const suffix = normalized.slice(index + delim.length)
    const canonical = mapConfig.canonical(suffix)
    if (!canonical) return { baseName: normalized, mapName: mapConfig.primaryMap }

    return { baseName: normalized.slice(0, index), mapName: canonical }
  }
}
