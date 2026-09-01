import { ChannelSpec } from './ChannelSpec'
import {
  FORMAT_EXTENSIONS,
  type Channel,
  type NormalConvention,
  type OutputFormat,
  type PresetMode,
  type SerializedPresetOutput
} from '@shared/types'

/**
 * One texture written by a preset.
 *
 * This is the unit the export strategies actually operate on — a preset is
 * just a named bundle of these, so "Unity HDRP" can emit BaseColor, Normal and
 * MaskMap in one tick of the sheet's settings.
 */
export class PresetOutput {
  constructor(
    public readonly mode: PresetMode,
    public readonly outputSuffix: string,
    public readonly format: OutputFormat,
    /** copy mode: the map name passed through. */
    public readonly source: string | null = null,
    /** Handedness of the source, consulted only when it is a Normal map. */
    public readonly normalConvention: NormalConvention = 'OpenGL',
    /** pack mode: per-output-channel assignment. */
    public readonly channels: Map<Channel, ChannelSpec> = new Map()
  ) {}

  /**
   * Whether this output passes a normal map through, and so needs its encoded
   * vectors rotated with the trim. Only ever true for copy mode — the loader
   * refuses `source: Normal` inside a pack.
   */
  get isNormalSource(): boolean {
    return this.mode === 'copy' && this.source?.toLowerCase() === 'normal'
  }

  get extension(): string {
    return FORMAT_EXTENSIONS[this.format]
  }

  /** <SheetName><outputSuffix>.<ext> */
  fileName(sheetName: string): string {
    return `${sheetName}${this.outputSuffix}.${this.extension}`
  }

  /** Every map name this output reads, for missing-source checks. */
  requiredMaps(): string[] {
    if (this.mode === 'copy') return this.source ? [this.source] : []
    const maps = new Set<string>()
    for (const spec of this.channels.values()) {
      if (spec.source) maps.add(spec.source)
    }
    return [...maps]
  }

  serialize(): SerializedPresetOutput {
    const raw: SerializedPresetOutput = {
      mode: this.mode,
      outputSuffix: this.outputSuffix,
      format: this.format
    }
    if (this.mode === 'copy') {
      if (this.source) raw.source = this.source
      if (this.isNormalSource) raw.normalConvention = this.normalConvention
    } else {
      raw.channels = Object.fromEntries(
        [...this.channels].map(([channel, spec]) => [channel, spec.serialize()])
      ) as SerializedPresetOutput['channels']
    }
    return raw
  }

  static deserialize(raw: SerializedPresetOutput): PresetOutput {
    const channels = new Map<Channel, ChannelSpec>()
    for (const [channel, spec] of Object.entries(raw.channels ?? {})) {
      if (spec) channels.set(channel as Channel, ChannelSpec.deserialize(spec))
    }
    return new PresetOutput(
      raw.mode,
      raw.outputSuffix,
      raw.format,
      raw.source ?? null,
      raw.normalConvention ?? 'OpenGL',
      channels
    )
  }
}
