import { create } from 'zustand'
import { Preset } from '@models/Preset'
import type { SerializedPreset } from '@shared/types'

/**
 * Presets loaded from preset-packs/. Global to the tool, not the project — the
 * per-sheet "enabled presets" list stores names that are resolved against this.
 *
 * `warnings` holds anything PresetLoader or MapConfigLoader flagged on the last
 * refresh (duplicate names, bad YAML). Surfaced in the sheet settings panel so
 * a preset that silently didn't load is still visible to the user.
 */
interface PresetsState {
  presets: Preset[]
  warnings: string[]
  setFromSerialized(presets: SerializedPreset[], warnings: string[]): void
  byName(name: string): Preset | undefined
}

export const usePresetsStore = create<PresetsState>((set, get) => ({
  presets: [],
  warnings: [],

  setFromSerialized: (presets, warnings) =>
    set({ presets: presets.map((raw) => Preset.deserialize(raw)), warnings }),

  byName: (name) => get().presets.find((preset) => preset.name === name)
}))

export const usePresets = (): Preset[] => usePresetsStore((state) => state.presets)
