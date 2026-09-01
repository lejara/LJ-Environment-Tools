import { IpcChannels } from '@shared/ipcChannels'
import type { SerializedAsset, SerializedPreset, SerializedSheet } from '@shared/types'
import { invoke } from './bridge'

/**
 * Manual Build. Auto Export does NOT come through here — it runs on main's own
 * timer against the mirrored sheet list (see autoExportService).
 */
export const exportService = {
  exportSheet: (payload: {
    sheet: SerializedSheet
    assets: SerializedAsset[]
    presets: SerializedPreset[]
    projectRoot: string
  }): Promise<string[]> => invoke<string[]>(IpcChannels.EXPORT_SHEET, payload)
}
