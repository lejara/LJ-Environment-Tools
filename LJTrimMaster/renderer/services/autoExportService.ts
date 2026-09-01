import { IpcChannels } from '@shared/ipcChannels'
import type { SerializedAsset, SerializedPreset, SerializedSheet } from '@shared/types'
import { invoke } from './bridge'

/**
 * Auto Export lives on a timer in main, but the authoritative Project lives
 * here. `syncSheets` pushes the mirror main's timer reads; `setEnabled` is the
 * toolbar toggle.
 */
export const autoExportService = {
  setEnabled: (enabled: boolean): Promise<void> =>
    invoke<void>(IpcChannels.AUTOEXPORT_SET_ENABLED, enabled),

  syncSheets: (payload: {
    sheets: SerializedSheet[]
    dirtyIds: string[]
    assets: SerializedAsset[]
    presets: SerializedPreset[]
    projectRoot: string
  }): Promise<void> => invoke<void>(IpcChannels.AUTOEXPORT_SYNC_SHEETS, payload)
}
