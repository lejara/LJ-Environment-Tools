import { readdir } from 'node:fs/promises'
import { extname, join, posix, relative, sep } from 'node:path'
import { Asset } from '@models/Asset'
import { MapConfig } from '@models/MapConfig'

/**
 * Walks image_dump/ — top level AND subfolders — and groups files into Assets
 * by base name + known suffix.
 *
 * `wood_BaseColor.png` and `wood_Normal.png` become one Asset "wood" with two
 * maps. A file whose suffix isn't in the map vocabulary is treated as an
 * untagged asset named after the whole filename, mapped as the primary — so a
 * plain `brick.png` still shows up and is usable.
 *
 * Files in a subfolder carry that folder in their base name (`stone/wall`), so
 * two `wall_BaseColor.png` in different folders stay separate assets and only
 * siblings in the SAME folder group together. Top-level files keep their bare
 * name, which is what keeps projects saved before subfolder support working.
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

  /** How deep below image_dump/ to walk before giving up. */
  private static readonly MAX_DEPTH = 8

  async scan(
    imageDumpPath: string,
    mapConfig: MapConfig
  ): Promise<{ assets: Asset[]; warnings: string[] }> {
    const files = await this.collect(imageDumpPath, 0)

    // baseName -> (mapName -> absolute path)
    const grouped = new Map<string, Map<string, string>>()
    const warnings: string[] = []

    for (const filePath of files) {
      const ext = extname(filePath).toLowerCase()
      if (!AssetScanner.IMAGE_EXTENSIONS.has(ext)) continue

      // Everything below image_dump/, extension stripped, in posix form so a
      // base name reads the same on every platform.
      const relPath = relative(imageDumpPath, filePath).split(sep).join(posix.sep)
      const relStem = relPath.slice(0, relPath.length - ext.length)

      const cut = relStem.lastIndexOf(posix.sep)
      const folder = cut < 0 ? '' : relStem.slice(0, cut + 1)
      const stem = cut < 0 ? relStem : relStem.slice(cut + 1)

      const { baseName: stemBase, mapName } = this.split(stem, mapConfig)
      const baseName = folder + stemBase

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
        const existingRel = relative(imageDumpPath, existing).split(sep).join(posix.sep)
        warnings.push(
          `image_dump: "${relPath}" and "${existingRel}" both resolve to ${baseName} / ${mapName} — using "${existingRel}".`
        )
        continue
      }
      maps.set(mapName, filePath)
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
   * Absolute paths of every file at or below `dir`, depth-limited so a stray
   * symlink loop or a dump pointed at something huge can't hang the scan.
   */
  private async collect(dir: string, depth: number): Promise<string[]> {
    let dirents
    try {
      dirents = await readdir(dir, { withFileTypes: true })
    } catch {
      // No image_dump yet (fresh project, or the folder was moved), or a
      // subfolder we can't read — neither is fatal.
      return []
    }

    const files: string[] = []
    for (const dirent of dirents) {
      const full = join(dir, dirent.name)
      if (dirent.isFile()) {
        files.push(full)
        continue
      }
      // Skip dot-folders — .git, .DS_Store spill, thumbnail caches.
      if (!dirent.isDirectory() || dirent.name.startsWith('.')) continue
      if (depth >= AssetScanner.MAX_DEPTH) continue
      files.push(...(await this.collect(full, depth + 1)))
    }
    return files
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
