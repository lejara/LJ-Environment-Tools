import { IpcChannels } from '@shared/ipcChannels'
import type { OpenProjectResult, SerializedProjectData } from '@shared/types'
import { invoke } from './bridge'

/**
 * Renderer-side wrapper over main/fs/projectFs and recentProjects.
 * Returns null when the user cancels a dialog — callers treat that as a no-op,
 * not an error.
 */
export const projectService = {
  newProject: (): Promise<OpenProjectResult | null> =>
    invoke<OpenProjectResult | null>(IpcChannels.PROJECT_NEW),

  browse: (): Promise<OpenProjectResult | null> =>
    invoke<OpenProjectResult | null>(IpcChannels.PROJECT_BROWSE),

  open: (rootPath: string): Promise<OpenProjectResult> =>
    invoke<OpenProjectResult>(IpcChannels.PROJECT_OPEN, rootPath),

  save: (rootPath: string, data: SerializedProjectData): Promise<void> =>
    invoke<void>(IpcChannels.PROJECT_SAVE, rootPath, data),

  recents: (): Promise<string[]> => invoke<string[]>(IpcChannels.RECENT_LIST),

  forgetRecent: (path: string): Promise<void> => invoke<void>(IpcChannels.RECENT_REMOVE, path)
}
