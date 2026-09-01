import type { SerializedChannelSpec, SourceChannel } from '@shared/types'

/**
 * How one output channel of a packed image is filled.
 *
 * Either `constant` (fill flat, ignore sources) or `source` (sample a map).
 * When a `source` map is missing from the asset, the channel falls back to
 * `fallback` and the export warns rather than failing.
 */
export class ChannelSpec {
  constructor(
    public readonly source: string | null = null,
    public readonly fromChannel: SourceChannel = 'L',
    public readonly invert: boolean = false,
    public readonly fallback: number = 0,
    public readonly constant: number | null = null
  ) {}

  get isConstant(): boolean {
    return this.constant !== null
  }

  serialize(): SerializedChannelSpec {
    const raw: SerializedChannelSpec = {
      fromChannel: this.fromChannel,
      invert: this.invert,
      fallback: this.fallback
    }
    if (this.source !== null) raw.source = this.source
    if (this.constant !== null) raw.constant = this.constant
    return raw
  }

  static deserialize(raw: SerializedChannelSpec): ChannelSpec {
    return new ChannelSpec(
      raw.source ?? null,
      raw.fromChannel ?? 'L',
      raw.invert ?? false,
      raw.fallback ?? 0,
      raw.constant ?? null
    )
  }
}
