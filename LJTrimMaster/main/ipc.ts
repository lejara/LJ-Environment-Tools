import { BrowserWindow, dialog, ipcMain } from 'electron'
import { IpcChannels } from '@shared/ipcChannels'
import { AppEvent, BRIDGED_EVENTS } from '@shared/events/AppEvent'
import type { EventBus } from '@shared/events/EventBus'
import type {
  RefreshResult,
  SerializedAsset,
  SerializedPreset,
  SerializedProjectData,
  SerializedSheet
} from '@shared/types'
import { ProjectFs } from './fs/projectFs'
import { AssetScanner } from './fs/assetScanner'
import { PresetLoader } from './fs/presetLoader'
import { MapConfigLoader } from './fs/mapConfigLoader'
import { RecentProjects } from './fs/recentProjects'
import { Exporter } from './export/exporter'
import { AutoExporter } from './autoExport/autoExporter'
import { Asset } from '@models/Asset'
import { Preset } from '@models/Preset'
import { TrimSheet } from '@models/TrimSheet'

/**
 * Wires every IPC channel to its owning main-process service, and bridges
 * main's EventBus to the renderer's.
 *
 * Handlers are thin: they unwrap args, call a service, and return. Anything
 * that throws propagates to the renderer's invoke() as a rejected promise,
 * which the calling service turns into a user-visible message.
 */
export function registerIpc(bus: EventBus, binDir: string): void {
  const projectFs = new ProjectFs()
  const assetScanner = new AssetScanner()
  const presetLoader = new PresetLoader()
  const mapConfigLoader = new MapConfigLoader()
  const recentProjects = new RecentProjects()
  const exporter = new Exporter(bus)
  const autoExporter = new AutoExporter(exporter)

  // --- Bus bridge: main -> renderer ---------------------------------------
  for (const event of BRIDGED_EVENTS) {
    bus.on(event, (payload) => {
      for (const win of BrowserWindow.getAllWindows()) {
        win.webContents.send(IpcChannels.BUS_FORWARD, event, payload)
      }
    })
  }

  // --- Project -------------------------------------------------------------
  ipcMain.handle(IpcChannels.PROJECT_NEW, async () => {
    const result = await dialog.showOpenDialog({
      title: 'Choose a folder for the new project',
      properties: ['openDirectory', 'createDirectory']
    })
    if (result.canceled || !result.filePaths[0]) return null

    const opened = await projectFs.create(result.filePaths[0])
    await recentProjects.add(opened.rootPath)
    return opened
  })

  ipcMain.handle(IpcChannels.PROJECT_BROWSE, async () => {
    const result = await dialog.showOpenDialog({
      title: 'Open a Trim Master project folder',
      properties: ['openDirectory']
    })
    if (result.canceled || !result.filePaths[0]) return null

    const opened = await projectFs.open(result.filePaths[0])
    await recentProjects.add(opened.rootPath)
    return opened
  })

  ipcMain.handle(IpcChannels.PROJECT_OPEN, async (_e, rootPath: string) => {
    const opened = await projectFs.open(rootPath)
    await recentProjects.add(opened.rootPath)
    return opened
  })

  ipcMain.handle(
    IpcChannels.PROJECT_SAVE,
    async (_e, rootPath: string, data: SerializedProjectData) => {
      await projectFs.write(rootPath, data)
    }
  )

  // --- Recents -------------------------------------------------------------
  ipcMain.handle(IpcChannels.RECENT_LIST, () => recentProjects.listExisting())
  ipcMain.handle(IpcChannels.RECENT_REMOVE, (_e, path: string) => recentProjects.remove(path))

  // --- Refresh -------------------------------------------------------------
  // One entry point, many subscribers: re-reads maps.yaml + preset-packs/ and
  // re-scans image_dump/, then broadcasts the result.
  ipcMain.handle(IpcChannels.REFRESH_ALL, async (_e, projectRoot?: string): Promise<RefreshResult> => {
    bus.emit(AppEvent.REFRESH_REQUESTED, { projectRoot })

    const { config, warnings: mapWarnings } = await mapConfigLoader.load(binDir)
    const { presets, warnings: presetWarnings } = await presetLoader.load(binDir)
    const { assets, warnings: assetWarnings } = projectRoot
      ? await assetScanner.scan(ProjectFs.imageDumpPath(projectRoot), config)
      : { assets: [], warnings: [] }

    const result: RefreshResult = {
      mapConfig: config.serialize(),
      presets: presets.map((preset) => preset.serialize()),
      assets: assets.map((asset) => asset.serialize()),
      warnings: [...mapWarnings, ...presetWarnings, ...assetWarnings]
    }

    bus.emit(AppEvent.REFRESH_COMPLETED, result)
    return result
  })

  // --- Export --------------------------------------------------------------
  ipcMain.handle(
    IpcChannels.EXPORT_SHEET,
    async (
      _e,
      payload: {
        sheet: SerializedSheet
        assets: SerializedAsset[]
        presets: SerializedPreset[]
        projectRoot: string
      }
    ) => {
      const sheet = TrimSheet.deserialize(payload.sheet)
      const assets = new Map(
        payload.assets.map((raw) => {
          const asset = Asset.deserialize(raw)
          return [asset.baseName, asset] as const
        })
      )
      const presets = payload.presets.map((raw) => Preset.deserialize(raw))
      return exporter.export(sheet, assets, presets, ProjectFs.outputPath(payload.projectRoot))
    }
  )

  // --- Auto export ---------------------------------------------------------
  ipcMain.handle(IpcChannels.AUTOEXPORT_SET_ENABLED, (_e, enabled: boolean) => {
    autoExporter.setEnabled(enabled)
  })

  ipcMain.handle(
    IpcChannels.AUTOEXPORT_SYNC_SHEETS,
    (
      _e,
      payload: {
        sheets: SerializedSheet[]
        dirtyIds: string[]
        assets: SerializedAsset[]
        presets: SerializedPreset[]
        projectRoot: string
      }
    ) => {
      autoExporter.sync({
        sheets: payload.sheets,
        dirtyIds: payload.dirtyIds,
        assets: payload.assets,
        presets: payload.presets,
        outputDir: ProjectFs.outputPath(payload.projectRoot)
      })
    }
  )
}
