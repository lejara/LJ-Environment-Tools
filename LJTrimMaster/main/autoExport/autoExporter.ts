import { TrimSheet } from '@models/TrimSheet'
import { Asset } from '@models/Asset'
import { Preset } from '@models/Preset'
import type { Exporter } from '../export/exporter'
import type { SerializedAsset, SerializedPreset, SerializedSheet } from '@shared/types'

const TICK_MS = 2000

/**
 * Timer loop behind the toolbar's Auto Export toggle. Each tick, re-exports
 * every sheet whose isDirty flag is set, then clears it.
 *
 * The authoritative Project lives in the renderer, so main keeps a MIRROR of
 * the sheets, refreshed by the renderer over AUTOEXPORT_SYNC_SHEETS whenever
 * editor state changes. The mirror is what the timer reads.
 *
 * isDirty is cleared INLINE after Exporter.export() returns — not via the bus.
 * There is one emitter and one dirty-owner in this process; a bus round-trip
 * would only hide the flow. The renderer clears its own copy of the flag off
 * the bridged EXPORT_COMPLETED event.
 */
export class AutoExporter {
  private timer: NodeJS.Timeout | null = null
  private running = false

  private sheets: TrimSheet[] = []
  private assets = new Map<string, Asset>()
  private presets: Preset[] = []
  private outputDir: string | null = null

  constructor(private readonly exporter: Exporter) {}

  get isEnabled(): boolean {
    return this.timer !== null
  }

  /** Replaces the mirror. Called by the renderer on every editor state change. */
  sync(payload: {
    sheets: SerializedSheet[]
    dirtyIds: string[]
    assets: SerializedAsset[]
    presets: SerializedPreset[]
    outputDir: string
  }): void {
    const dirty = new Set(payload.dirtyIds)
    this.sheets = payload.sheets.map((raw) => {
      const sheet = TrimSheet.deserialize(raw)
      if (dirty.has(sheet.id)) sheet.markDirty()
      return sheet
    })
    this.assets = new Map(
      payload.assets.map((raw) => {
        const asset = Asset.deserialize(raw)
        return [asset.baseName, asset]
      })
    )
    this.presets = payload.presets.map((raw) => Preset.deserialize(raw))
    this.outputDir = payload.outputDir
  }

  start(): void {
    if (this.timer) return
    this.timer = setInterval(() => {
      void this.tick()
    }, TICK_MS)
  }

  stop(): void {
    if (!this.timer) return
    clearInterval(this.timer)
    this.timer = null
  }

  setEnabled(enabled: boolean): void {
    if (enabled) this.start()
    else this.stop()
  }

  private async tick(): Promise<void> {
    // A slow export must not stack ticks on top of itself.
    if (this.running || !this.outputDir) return

    const dirty = this.sheets.filter((sheet) => sheet.isDirty)
    if (dirty.length === 0) return

    this.running = true
    try {
      for (const sheet of dirty) {
        await this.exporter.export(sheet, this.assets, this.presets, this.outputDir)
        // Inline, immediately after the export returns — see the class note.
        sheet.clearDirty()
      }
    } finally {
      this.running = false
    }
  }
}
