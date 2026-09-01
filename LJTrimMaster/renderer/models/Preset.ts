import { PresetOutput } from './PresetOutput'
import type { SerializedPreset } from '@shared/types'

/**
 * One preset-packs/*.yaml file: a named bundle of texture outputs.
 *
 * A preset describes a whole target rather than a single file, so ticking
 * "Unity HDRP" on a sheet emits its BaseColor, Normal and MaskMap together
 * instead of making the user tick three separate entries and remember which
 * three go together.
 *
 * Identity is the `name:` field, NOT the filename — on a duplicate name the
 * first loaded wins and the loser is logged as a warning by PresetLoader.
 */
export class Preset {
  constructor(
    public readonly name: string,
    public readonly outputs: PresetOutput[]
  ) {}

  /** Every file this preset writes for a given sheet, in declaration order. */
  fileNames(sheetName: string): string[] {
    return this.outputs.map((output) => output.fileName(sheetName))
  }

  /** Union of the maps every output reads, for missing-source checks. */
  requiredMaps(): string[] {
    const maps = new Set<string>()
    for (const output of this.outputs) {
      for (const map of output.requiredMaps()) maps.add(map)
    }
    return [...maps]
  }

  /** Short "2 copy, 1 pack" style summary for the sheet settings list. */
  get summary(): string {
    const copies = this.outputs.filter((output) => output.mode === 'copy').length
    const packs = this.outputs.length - copies
    const parts: string[] = []
    if (copies > 0) parts.push(`${copies} copy`)
    if (packs > 0) parts.push(`${packs} pack`)
    return parts.join(', ')
  }

  serialize(): SerializedPreset {
    return {
      name: this.name,
      outputs: this.outputs.map((output) => output.serialize())
    }
  }

  static deserialize(raw: SerializedPreset): Preset {
    return new Preset(raw.name, (raw.outputs ?? []).map((output) => PresetOutput.deserialize(output)))
  }
}
