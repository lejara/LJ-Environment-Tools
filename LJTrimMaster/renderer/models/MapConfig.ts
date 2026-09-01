import type { SerializedMapConfig } from '@shared/types'

/**
 * The maps.yaml content — tool-wide, not per-project, so every project shares
 * one map vocabulary. Lives next to the binary.
 *
 * Several suffix delimiters can be live at once, so a dump that mixes
 * conventions (`wood_Normal.png`, `wood-Roughness.png`, `wood.AO.png`) still
 * reads as one asset. Rather than ranking the delimiters against each other,
 * `normalize()` rewrites every one of them to a single canonical `_` and the
 * scanner then does an ordinary single-delimiter split.
 */
export class MapConfig {
  /** What every configured delimiter is rewritten to before splitting. */
  static readonly NORMALIZED_DELIM = '_'

  private readonly delimPattern: RegExp | null

  constructor(
    public readonly suffixDelims: string[],
    public readonly knownMaps: string[]
  ) {
    this.delimPattern = MapConfig.buildPattern(suffixDelims)
  }

  /** The map treated as the asset's primary — the only one the UI lists. */
  get primaryMap(): string {
    return this.knownMaps[0] ?? 'BaseColor'
  }

  /**
   * Rewrites every configured delimiter to the canonical one.
   *
   * Delimiters are matched longest-first, so a two-character delimiter isn't
   * chewed up by a one-character one that happens to be its prefix — with
   * `["_", "__"]`, `wood__BaseColor` must collapse to `wood_BaseColor`, not
   * `wood__BaseColor`.
   *
   * Note this normalizes the WHOLE stem, base name included: `old-wood_Normal`
   * and `old_wood-Roughness` both land on the base `old_wood` and group into
   * one asset. That merging is the point — it's what lets a dump mix
   * conventions — but it does mean a displayed base name can differ from the
   * literal filename.
   */
  normalize(text: string): string {
    if (!this.delimPattern) return text
    return text.replace(this.delimPattern, MapConfig.NORMALIZED_DELIM)
  }

  isKnown(mapName: string): boolean {
    return this.knownMaps.some((known) => known.toLowerCase() === mapName.toLowerCase())
  }

  /** Canonical casing for a map name, or null if it isn't in the vocabulary. */
  canonical(mapName: string): string | null {
    return this.knownMaps.find((known) => known.toLowerCase() === mapName.toLowerCase()) ?? null
  }

  serialize(): SerializedMapConfig {
    return { suffixDelims: [...this.suffixDelims], knownMaps: [...this.knownMaps] }
  }

  static deserialize(raw: SerializedMapConfig): MapConfig {
    return new MapConfig([...raw.suffixDelims], [...raw.knownMaps])
  }

  static fallback(): MapConfig {
    return new MapConfig(
      ['_'],
      ['BaseColor', 'Roughness', 'Metallic', 'AO', 'Normal', 'Height', 'Emissive']
    )
  }

  /**
   * One alternation over every delimiter, longest first so the greedy match
   * wins. Each is regex-escaped — `.` is a plausible delimiter and must not
   * become "any character".
   */
  private static buildPattern(delims: string[]): RegExp | null {
    const usable = delims.filter((delim) => delim.length > 0)
    if (usable.length === 0) return null

    const escaped = [...usable]
      .sort((a, b) => b.length - a.length)
      .map((delim) => delim.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))

    return new RegExp(escaped.join('|'), 'g')
  }
}
