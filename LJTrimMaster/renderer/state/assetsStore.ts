import { create } from 'zustand'
import { Asset } from '@models/Asset'
import { MapConfig } from '@models/MapConfig'
import type { SerializedAsset, SerializedMapConfig } from '@shared/types'

/**
 * The current image_dump/ scan, plus the map vocabulary it was scanned with.
 * Replaced wholesale on every refresh — assets are read-only here, so there's
 * no state to preserve across a rescan.
 */
interface AssetsState {
  assets: Asset[]
  mapConfig: MapConfig
  setFromSerialized(assets: SerializedAsset[], mapConfig: SerializedMapConfig): void
  find(baseName: string): Asset | undefined
}

export const useAssetsStore = create<AssetsState>((set, get) => ({
  assets: [],
  mapConfig: MapConfig.fallback(),

  setFromSerialized: (assets, mapConfig) =>
    set({
      assets: assets.map((raw) => Asset.deserialize(raw)),
      mapConfig: MapConfig.deserialize(mapConfig)
    }),

  find: (baseName) => get().assets.find((asset) => asset.baseName === baseName)
}))

export const useAssets = (): Asset[] => useAssetsStore((state) => state.assets)
