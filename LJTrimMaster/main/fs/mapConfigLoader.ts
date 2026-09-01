import { readFile } from 'node:fs/promises'
import { join } from 'node:path'
import { parse } from 'yaml'
import { MapConfig } from '@models/MapConfig'

/**
 * Reads maps.yaml from next to the binary. Tool-wide config — one map
 * vocabulary shared by every project.
 *
 * A missing or malformed file is not fatal: we fall back to the built-in
 * vocabulary and surface a warning, so a bad edit can't lock the user out of
 * their own project.
 */
export class MapConfigLoader {
  static readonly FILENAME = 'maps.yaml'

  async load(binDir: string): Promise<{ config: MapConfig; warnings: string[] }> {
    const path = join(binDir, MapConfigLoader.FILENAME)
    const warnings: string[] = []

    let raw: string
    try {
      raw = await readFile(path, 'utf-8')
    } catch {
      warnings.push(`${MapConfigLoader.FILENAME} not found at ${path} — using built-in map names.`)
      return { config: MapConfig.fallback(), warnings }
    }

    try {
      const parsed = parse(raw) as {
        suffixDelim?: unknown
        suffixDelims?: unknown
        knownMaps?: unknown
      }

      const maps = Array.isArray(parsed?.knownMaps)
        ? parsed.knownMaps.filter((entry): entry is string => typeof entry === 'string')
        : []

      if (maps.length === 0) {
        warnings.push(`${MapConfigLoader.FILENAME} lists no knownMaps — using built-in map names.`)
        return { config: MapConfig.fallback(), warnings }
      }

      const delims = this.readDelims(parsed, warnings)
      return { config: new MapConfig(delims, maps), warnings }
    } catch (err) {
      warnings.push(
        `${MapConfigLoader.FILENAME} is not valid YAML (${String(err)}) — using built-in map names.`
      )
      return { config: MapConfig.fallback(), warnings }
    }
  }

  /**
   * Collects the delimiter list, accepting every reasonable spelling:
   *
   *   suffixDelim: "_"              # single, original form
   *   suffixDelim: ["_", "-"]       # list under the old key
   *   suffixDelims: ["_", "-", "."] # list under the plural key
   *
   * Both keys are read and unioned, so a file that sets one and forgets to
   * remove the other still behaves the way it reads.
   */
  private readDelims(
    parsed: { suffixDelim?: unknown; suffixDelims?: unknown },
    warnings: string[]
  ): string[] {
    const collected: string[] = []

    for (const [key, value] of [
      ['suffixDelim', parsed.suffixDelim],
      ['suffixDelims', parsed.suffixDelims]
    ] as const) {
      if (value === undefined || value === null) continue

      if (typeof value === 'string') {
        collected.push(value)
      } else if (Array.isArray(value)) {
        for (const entry of value) {
          if (typeof entry === 'string') collected.push(entry)
          else warnings.push(`${MapConfigLoader.FILENAME}: ${key} entry ${JSON.stringify(entry)} is not a string — ignored.`)
        }
      } else {
        warnings.push(`${MapConfigLoader.FILENAME}: ${key} must be a string or a list of strings — ignored.`)
      }
    }

    // An empty delimiter would match everywhere and split nothing sensibly.
    const usable = collected.filter((delim) => {
      if (delim.length > 0) return true
      warnings.push(`${MapConfigLoader.FILENAME}: an empty delimiter was listed — ignored.`)
      return false
    })

    const deduped = [...new Set(usable)]
    if (deduped.length === 0) {
      warnings.push(`${MapConfigLoader.FILENAME}: no usable suffix delimiter — falling back to "_".`)
      return ['_']
    }
    return deduped
  }
}
