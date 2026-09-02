import { contextBridge, ipcRenderer } from 'electron'
import { IpcChannels } from '@shared/ipcChannels'
import type { AppEvent } from '@shared/events/AppEvent'
import type { MenuCommand } from '@shared/types'

/**
 * The only bridge between renderer and main. contextIsolation stays on and the
 * renderer never sees `ipcRenderer` itself — it gets this narrow surface, so a
 * compromised renderer can't reach arbitrary channels.
 */
const api = {
  invoke: (channel: string, ...args: unknown[]): Promise<unknown> =>
    ipcRenderer.invoke(channel, ...args),

  /** Bridged EventBus events arriving from main. Returns an unsubscribe. */
  onBusEvent: (handler: (event: AppEvent, payload: unknown) => void): (() => void) => {
    const listener = (_e: unknown, event: AppEvent, payload: unknown): void => handler(event, payload)
    ipcRenderer.on(IpcChannels.BUS_FORWARD, listener)
    return () => ipcRenderer.off(IpcChannels.BUS_FORWARD, listener)
  },

  /** Application-menu clicks. Returns an unsubscribe. */
  onMenuCommand: (handler: (command: MenuCommand) => void): (() => void) => {
    const listener = (_e: unknown, command: MenuCommand): void => handler(command)
    ipcRenderer.on(IpcChannels.MENU_COMMAND, listener)
    return () => ipcRenderer.off(IpcChannels.MENU_COMMAND, listener)
  }
}

contextBridge.exposeInMainWorld('ljtm', api)

export type LjtmApi = typeof api
