import { IpcChannels } from '@shared/ipcChannels'
import type { RefreshResult } from '@shared/types'
import { invoke } from './bridge'

/**
 * The single refresh entry point: re-reads maps.yaml and preset-packs/, and
 * re-scans image_dump/. Main emits REFRESH_COMPLETED, which every interested
 * panel subscribes to — the toolbar button doesn't need to know who cares.
 */
export const refreshService = {
  refreshAll: (projectRoot?: string): Promise<RefreshResult> =>
    invoke<RefreshResult>(IpcChannels.REFRESH_ALL, projectRoot)
}
