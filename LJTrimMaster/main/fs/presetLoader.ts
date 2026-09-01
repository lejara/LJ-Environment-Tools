import { readdir, readFile } from 'node:fs/promises'
import { join } from 'node:path'
import { parse } from 'yaml'
import { Preset } from '@models/Preset'
import { PresetOutput } from '@models/PresetOutput'
import { ChannelSpec } from '@models/ChannelSpec'
import {
  NORMAL_CONVENTIONS,
  OUTPUT_FORMATS,
  type Channel,
  type NormalConvention,
  type OutputFormat,
  type SourceChannel
} from '@shared/types'

const CHANNELS: Channel[] = ['R', 'G', 'B', 'A']
const SOURCE_CHANNELS: SourceChannel[] = ['R', 'G', 'B', 'A', 'L']

/**
 * Reads preset-packs/*.yaml from next to the binary. Presets are global —
 * shared across every project.
 *
 * Identity is the `name:` field, not the filename. On a duplicate name the
 * FIRST loaded wins and the loser is warned about, so a user's own preset can't
 * be silently shadowed without a trace.
 *
 * A malformed file is skipped with a warning rather than aborting the whole
 * load — one bad YAML file shouldn't cost the user every other preset. The same
 * leniency applies one level down: a bad entry in `outputs:` is skipped and
 * warned about, and only a preset with NO usable output is dropped entirely.
 */
export class PresetLoader {
  static readonly FOLDER = 'preset-packs'

  async load(binDir: string): Promise<{ presets: Preset[]; warnings: string[] }> {
    const dir = join(binDir, PresetLoader.FOLDER)
    const warnings: string[] = []

    let files: string[]
    try {
      const dirents = await readdir(dir, { withFileTypes: true })
      files = dirents
        .filter((d) => d.isFile() && /\.ya?ml$/i.test(d.name))
        .map((d) => d.name)
        .sort()
    } catch {
      warnings.push(`${PresetLoader.FOLDER}/ not found at ${dir} — no presets loaded.`)
      return { presets: [], warnings }
    }

    const byName = new Map<string, { preset: Preset; fileName: string }>()

    for (const fileName of files) {
      let parsed: unknown
      try {
        parsed = parse(await readFile(join(dir, fileName), 'utf-8'))
      } catch (err) {
        warnings.push(`${fileName}: not valid YAML (${String(err)}) — skipped.`)
        continue
      }

      const result = this.build(parsed, fileName)
      if ('error' in result) {
        warnings.push(`${fileName}: ${result.error} — skipped.`)
        continue
      }
      warnings.push(...result.warnings)

      const existing = byName.get(result.preset.name)
      if (existing) {
        warnings.push(
          `${fileName}: preset name "${result.preset.name}" already defined by ${existing.fileName} — keeping the first, skipping this one.`
        )
        continue
      }
      byName.set(result.preset.name, { preset: result.preset, fileName })
    }

    const presets = [...byName.values()].map((entry) => entry.preset)
    presets.sort((a, b) => a.name.localeCompare(b.name))
    return { presets, warnings }
  }

  private build(
    raw: unknown,
    fileName: string
  ): { preset: Preset; warnings: string[] } | { error: string } {
    if (!raw || typeof raw !== 'object') return { error: 'file is empty or not a mapping' }
    const doc = raw as Record<string, unknown>
    const warnings: string[] = []

    const name = typeof doc.name === 'string' ? doc.name.trim() : ''
    if (!name) return { error: 'missing required field `name`' }

    // A top-level `format:` is the default for outputs that don't set their own,
    // so a preset whose outputs are all PNG_RGBA states it once.
    const defaultFormat = this.readFormat(doc.format, fileName, 'format', warnings) ?? 'PNG_RGBA'

    // Same inheritance as `format`: state it once for the preset, override per
    // output if a single texture came from a different pipeline.
    const defaultConvention =
      this.readConvention(doc.normalConvention, fileName, 'normalConvention', warnings) ?? 'OpenGL'

    // Two accepted shapes. `outputs:` is the general one; a bare top-level
    // `mode:` is shorthand for a preset with exactly one output, which keeps
    // simple single-texture presets short.
    let entries: unknown[]
    if (Array.isArray(doc.outputs)) {
      entries = doc.outputs
      if (entries.length === 0) return { error: '`outputs:` is empty' }
    } else if (doc.outputs !== undefined) {
      return { error: '`outputs:` must be a list' }
    } else if (doc.mode !== undefined) {
      entries = [doc]
    } else {
      return { error: 'needs an `outputs:` list (or a single top-level `mode:`)' }
    }

    const outputs: PresetOutput[] = []
    const seenSuffixes = new Set<string>()

    for (const [index, entry] of entries.entries()) {
      const label = entries.length === 1 && entry === doc ? 'output' : `outputs[${index}]`

      if (!entry || typeof entry !== 'object') {
        warnings.push(`${fileName}: ${label} is not a mapping — skipped.`)
        continue
      }

      const built = this.buildOutput(
        entry as Record<string, unknown>,
        defaultFormat,
        defaultConvention,
        fileName,
        label
      )
      if ('error' in built) {
        warnings.push(`${fileName}: ${label} ${built.error} — skipped.`)
        continue
      }
      warnings.push(...built.warnings)

      // Two outputs with the same suffix would race to write one filename, and
      // whichever ran second would silently win.
      if (seenSuffixes.has(built.output.outputSuffix)) {
        warnings.push(
          `${fileName}: ${label} repeats outputSuffix "${built.output.outputSuffix}" — skipped, it would overwrite the earlier output.`
        )
        continue
      }
      seenSuffixes.add(built.output.outputSuffix)
      outputs.push(built.output)
    }

    if (outputs.length === 0) return { error: 'no usable outputs' }
    return { preset: new Preset(name, outputs), warnings }
  }

  private buildOutput(
    doc: Record<string, unknown>,
    defaultFormat: OutputFormat,
    defaultConvention: NormalConvention,
    fileName: string,
    label: string
  ): { output: PresetOutput; warnings: string[] } | { error: string } {
    const warnings: string[] = []

    const mode = doc.mode
    if (mode !== 'copy' && mode !== 'pack') {
      return { error: 'needs `mode` of "copy" or "pack"' }
    }

    const outputSuffix = typeof doc.outputSuffix === 'string' ? doc.outputSuffix : ''
    if (!outputSuffix) {
      warnings.push(
        `${fileName}: ${label} has no \`outputSuffix\` — its file is named after the sheet with nothing appended.`
      )
    }

    const format = this.readFormat(doc.format, fileName, `${label}.format`, warnings) ?? defaultFormat

    if (mode === 'copy') {
      const source = typeof doc.source === 'string' ? doc.source : ''
      if (!source) return { error: 'is copy mode and needs a `source` map name' }

      const convention =
        this.readConvention(doc.normalConvention, fileName, `${label}.normalConvention`, warnings) ??
        defaultConvention

      // Harmless but almost always a mistake: the key does nothing on a
      // non-normal map, so say so rather than letting it look effective.
      if (doc.normalConvention !== undefined && source.toLowerCase() !== 'normal') {
        warnings.push(
          `${fileName}: ${label} sets \`normalConvention\` on a "${source}" source — ignored, it only applies to Normal maps.`
        )
      }

      return { output: new PresetOutput('copy', outputSuffix, format, source, convention), warnings }
    }

    const rawChannels = doc.channels
    if (!rawChannels || typeof rawChannels !== 'object') {
      return { error: 'is pack mode and needs a `channels` mapping' }
    }

    const channels = new Map<Channel, ChannelSpec>()
    for (const channel of CHANNELS) {
      const spec = (rawChannels as Record<string, unknown>)[channel]
      if (spec === undefined || spec === null) continue
      if (typeof spec !== 'object') {
        warnings.push(`${fileName}: ${label} channel ${channel} is not a mapping — ignored.`)
        continue
      }
      const built = this.buildChannel(spec as Record<string, unknown>, channel, fileName, label)
      if ('error' in built) return { error: built.error }
      warnings.push(...built.warnings)
      channels.set(channel, built.spec)
    }

    if (channels.size === 0) return { error: 'is pack mode but defined no usable channels' }
    return {
      output: new PresetOutput('pack', outputSuffix, format, null, defaultConvention, channels),
      warnings
    }
  }

  private buildChannel(
    spec: Record<string, unknown>,
    channel: Channel,
    fileName: string,
    label: string
  ): { spec: ChannelSpec; warnings: string[] } | { error: string } {
    const warnings: string[] = []
    const constant = typeof spec.constant === 'number' ? spec.constant : null
    const source = typeof spec.source === 'string' ? spec.source : null

    if (constant === null && !source) {
      return { error: `channel ${channel} needs either \`source\` or \`constant\`` }
    }

    // Channel mixing a normal map is nonsense — the encoded vector stops being
    // a unit vector the moment you pull one channel out of it.
    if (source && source.toLowerCase() === 'normal') {
      return {
        error: `channel ${channel} uses \`source: Normal\`, which is only valid with mode: copy`
      }
    }

    if (constant !== null && source) {
      warnings.push(
        `${fileName}: ${label} channel ${channel} sets both \`constant\` and \`source\` — constant wins.`
      )
    }

    let fromChannel: SourceChannel = 'L'
    if (typeof spec.fromChannel === 'string') {
      const upper = spec.fromChannel.toUpperCase() as SourceChannel
      if (SOURCE_CHANNELS.includes(upper)) {
        fromChannel = upper
      } else {
        warnings.push(
          `${fileName}: ${label} channel ${channel} has unknown fromChannel "${spec.fromChannel}" — using L.`
        )
      }
    }

    const clamp01 = (value: unknown, fallback: number): number =>
      typeof value === 'number' && !Number.isNaN(value) ? Math.min(Math.max(value, 0), 1) : fallback

    return {
      spec: new ChannelSpec(
        source,
        fromChannel,
        spec.invert === true,
        clamp01(spec.fallback, 0),
        constant === null ? null : clamp01(constant, 0)
      ),
      warnings
    }
  }

  /** Returns null when the key is absent, so callers can fall back. */
  private readConvention(
    value: unknown,
    fileName: string,
    label: string,
    warnings: string[]
  ): NormalConvention | null {
    if (value === undefined || value === null) return null
    if (typeof value === 'string') {
      const match = NORMAL_CONVENTIONS.find(
        (known) => known.toLowerCase() === value.toLowerCase()
      )
      if (match) return match
    }
    warnings.push(
      `${fileName}: unknown ${label} "${String(value)}" — expected OpenGL or DirectX, using OpenGL.`
    )
    return null
  }

  /** Returns null when the key is absent, so callers can fall back. */
  private readFormat(
    value: unknown,
    fileName: string,
    label: string,
    warnings: string[]
  ): OutputFormat | null {
    if (value === undefined || value === null) return null
    if (typeof value === 'string' && OUTPUT_FORMATS.includes(value as OutputFormat)) {
      return value as OutputFormat
    }
    warnings.push(`${fileName}: unknown ${label} "${String(value)}" — defaulting to PNG_RGBA.`)
    return null
  }
}
