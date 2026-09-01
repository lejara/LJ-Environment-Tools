import { mkdir, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import type { Asset } from '@models/Asset'
import type { Preset } from '@models/Preset'
import type { PresetOutput } from '@models/PresetOutput'
import type { TrimSheet } from '@models/TrimSheet'
import type { EventBus } from '@shared/events/EventBus'
import { AppEvent } from '@shared/events/AppEvent'
import { CopyStrategy } from './copyStrategy'
import { PackStrategy } from './packStrategy'
import { ImageLoader } from './imageLoader'
import { ImageEncoder } from './imageEncoder'

/**
 * Characters no mainstream filesystem will accept in a name, plus control
 * codes. Spaces and hyphens are legal and deliberately left alone.
 */
const ILLEGAL_FILENAME_CHARS = /[<>:"/\\|?*\x00-\x1f]/g

/** Windows rejects a name ending in a dot or a space. */
const TRAILING_JUNK = /[. ]+$/

/**
 * Exports one sheet: walks each enabled preset's outputs, renders each through
 * its strategy, and writes the result into the project's output/ folder.
 *
 * Emits EXPORT_* unconditionally, so both the manual Build path and the Auto
 * Export path flow through here and listeners never need to tell them apart.
 * (There is deliberately no `trigger` field on the payload — add one only if a
 * listener actually needs to distinguish the two.)
 *
 * Failure is per-output: one preset's mask map blowing up doesn't cost the
 * sheet its base colour. Missing source maps are not failures at all — they
 * fall back and are reported as warnings on EXPORT_COMPLETED.
 */
export class Exporter {
  private readonly copy = new CopyStrategy()
  private readonly pack = new PackStrategy()
  private readonly encoder = new ImageEncoder()

  constructor(private readonly bus: EventBus) {}

  /** @returns absolute paths of everything written. */
  async export(
    sheet: TrimSheet,
    assets: Map<string, Asset>,
    presets: Preset[],
    outputDir: string
  ): Promise<string[]> {
    const enabled = presets.filter((preset) => sheet.enabledPresetNames.includes(preset.name))

    this.bus.emit(AppEvent.EXPORT_STARTED, {
      sheetId: sheet.id,
      presetNames: enabled.map((preset) => preset.name)
    })

    if (enabled.length === 0) {
      // Nothing ticked in this sheet's settings. Not an error — completing with
      // no outputs keeps the dirty flag clearing and the UI out of a stuck state.
      this.bus.emit(AppEvent.EXPORT_COMPLETED, { sheetId: sheet.id, outputPaths: [], warnings: [] })
      return []
    }

    // One loader per run: the same map is read by many trims and many outputs,
    // but a re-export still picks up textures edited on disk since last time.
    const loader = new ImageLoader()
    const outputPaths: string[] = []
    const warnings: string[] = []

    try {
      await mkdir(outputDir, { recursive: true })
    } catch (err) {
      this.bus.emit(AppEvent.EXPORT_FAILED, {
        sheetId: sheet.id,
        presetName: enabled[0].name,
        error: `Could not create ${outputDir}: ${err instanceof Error ? err.message : String(err)}`
      })
      this.bus.emit(AppEvent.EXPORT_COMPLETED, { sheetId: sheet.id, outputPaths: [], warnings })
      return []
    }

    for (const preset of enabled) {
      // A preset describes a whole target ("Unity HDRP"), so it may write
      // several textures. Each is dispatched independently.
      for (const output of preset.outputs) {
        try {
          const path = await this.runOutput(sheet, output, assets, loader, outputDir, warnings)
          outputPaths.push(path)
        } catch (err) {
          const message = err instanceof Error ? err.message : String(err)
          this.bus.emit(AppEvent.EXPORT_FAILED, {
            sheetId: sheet.id,
            presetName: preset.name,
            // The payload identifies the preset; name the output in the message
            // so a three-texture preset says WHICH texture failed.
            error: `${output.outputSuffix || output.mode}: ${message}`
          })
          // One failed output shouldn't cost the sheet its other textures.
          continue
        }
      }
    }

    this.bus.emit(AppEvent.EXPORT_COMPLETED, {
      sheetId: sheet.id,
      outputPaths,
      warnings: [...new Set(warnings)]
    })
    return outputPaths
  }

  /** Renders, encodes and writes one output. @returns the path written. */
  private async runOutput(
    sheet: TrimSheet,
    output: PresetOutput,
    assets: Map<string, Asset>,
    loader: ImageLoader,
    outputDir: string,
    warnings: string[]
  ): Promise<string> {
    const strategy = output.mode === 'copy' ? this.copy : this.pack
    const rendered = await strategy.run(sheet, output, assets, loader)

    // Prefix each warning with the file it belongs to — a sheet exporting six
    // textures otherwise produces an unattributable pile of them.
    const fileName = this.fileNameFor(sheet, output)
    for (const warning of rendered.warnings) warnings.push(`${fileName}: ${warning}`)

    const bytes = await this.encoder.encode(
      rendered.pixels,
      rendered.width,
      rendered.height,
      output.format
    )

    const path = join(outputDir, fileName)
    await writeFile(path, bytes)
    return path
  }

  /**
   * `<SheetName><outputSuffix>.<ext>`, with anything a filesystem would reject
   * replaced — sheet names are free text typed in the tab bar.
   */
  private fileNameFor(sheet: TrimSheet, output: PresetOutput): string {
    const safeName =
      sheet.name.replace(ILLEGAL_FILENAME_CHARS, '_').replace(TRAILING_JUNK, '').trim() || 'Sheet'
    return output.fileName(safeName)
  }
}
