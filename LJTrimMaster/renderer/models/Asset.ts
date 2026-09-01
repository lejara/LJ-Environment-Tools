import type { SerializedAsset } from '@shared/types'

/**
 * One logical texture from image_dump/ with its map siblings resolved.
 * `wood_BaseColor.png` + `wood_Normal.png` collapse into a single Asset
 * "wood" with two entries in `mapPaths`.
 *
 * Only the primary map surfaces in the Assets panel and Outliner; the siblings
 * are looked up by the exporter.
 */
export class Asset {
  constructor(
    public readonly baseName: string,
    public readonly mapPaths: Map<string, string>,
    public readonly primaryMap: string
  ) {}

  hasMap(name: string): boolean {
    return this.mapPaths.has(name)
  }

  pathFor(name: string): string | undefined {
    return this.mapPaths.get(name)
  }

  /** Path to the map shown as the asset's thumbnail. */
  get primaryPath(): string | undefined {
    return this.mapPaths.get(this.primaryMap)
  }

  get mapNames(): string[] {
    return [...this.mapPaths.keys()]
  }

  serialize(): SerializedAsset {
    return {
      baseName: this.baseName,
      mapPaths: Object.fromEntries(this.mapPaths),
      primaryMap: this.primaryMap
    }
  }

  static deserialize(raw: SerializedAsset): Asset {
    return new Asset(raw.baseName, new Map(Object.entries(raw.mapPaths)), raw.primaryMap)
  }
}
