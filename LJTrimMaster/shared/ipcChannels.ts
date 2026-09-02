/**
 * IPC channel names. Renderer services call these; main/ipc.ts handles them.
 * Grouped by the main-process module that owns the handler.
 */
export const IpcChannels = {
  // main/fs/projectFs.ts
  PROJECT_NEW: 'project:new',
  PROJECT_OPEN: 'project:open',
  PROJECT_BROWSE: 'project:browse',
  PROJECT_SAVE: 'project:save',

  // main/fs/recentProjects.ts
  RECENT_LIST: 'recent:list',
  RECENT_REMOVE: 'recent:remove',

  // main/fs/{assetScanner,presetLoader,mapConfigLoader}.ts
  REFRESH_ALL: 'refresh:all',

  // main/export/exporter.ts
  EXPORT_SHEET: 'export:sheet',

  // main/autoExport/autoExporter.ts
  AUTOEXPORT_SET_ENABLED: 'autoExport:setEnabled',
  AUTOEXPORT_SYNC_SHEETS: 'autoExport:syncSheets',

  /** main -> renderer: a bridged EventBus event. */
  BUS_FORWARD: 'bus:forward',

  /**
   * main -> renderer: the user picked an application-menu item.
   * Deliberately NOT on the EventBus — that is reserved for REFRESH_* and
   * EXPORT_*, and a menu click has exactly one listener.
   */
  MENU_COMMAND: 'menu:command'
} as const

export type IpcChannel = (typeof IpcChannels)[keyof typeof IpcChannels]
