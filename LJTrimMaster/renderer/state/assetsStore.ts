import { create } from 'zustand'
import { Asset } from '@models/Asset'
import { MapConfig } from '@models/MapConfig'
import type { SerializedAsset, SerializedMapConfig } from '@shared/types'

/**
 * The current image_dump/ scan, plus the map vocabulary it was scanned with.
 * Replaced wholesale on every refresh — assets are read-only here, so there's
 * no state to preserve across a rescan.
 */
/** A source image's pixel dimensions, once something has decoded it. */
export interface PixelSize {
  width: number
  height: number
}

interface AssetsState {
  assets: Asset[]
  mapConfig: MapConfig
  /**
   * Natural pixel size of each asset's primary map, recorded as the Assets
   * panel thumbnails load. Free - the browser has already decoded them - and it
   * is what lets a newly added trim default to 1:1 texel density.
   */
  sizes: Map<string, PixelSize>

  setFromSerialized(assets: SerializedAsset[], mapConfig: SerializedMapConfig): void
  find(baseName: string): Asset | undefined
  recordSize(baseName: string, size: PixelSize): void
  sizeOf(baseName: string): PixelSize | undefined
}

export const useAssetsStore = create<AssetsState>((set, get) => ({
  assets: [],
  mapConfig: MapConfig.fallback(),
  sizes: new Map(),

  setFromSerialized: (assets, mapConfig) =>
    set({
      assets: assets.map((raw) => Asset.deserialize(raw)),
      mapConfig: MapConfig.deserialize(mapConfig),
      // Dropped on a rescan: a texture can be replaced on disk between
      // refreshes, and a stale size would mint wrongly sized trims.
      sizes: new Map()
    }),

  find: (baseName) => get().assets.find((asset) => asset.baseName === baseName),

  recordSize: (baseName, size) => {
    if (size.width <= 0 || size.height <= 0) return
    const existing = get().sizes.get(baseName)
    if (existing && existing.width === size.width && existing.height === size.height) return
    // Mutated in place rather than replaced: this fires once per thumbnail as
    // the panel loads, and a new Map each time would re-render the whole list.
    get().sizes.set(baseName, size)
  },

  sizeOf: (baseName) => get().sizes.get(baseName)
}))

export const useAssets = (): Asset[] => useAssetsStore((state) => state.assets)
