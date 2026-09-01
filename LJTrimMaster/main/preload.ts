import { contextBridge, ipcRenderer } from 'electron'
import { IpcChannels } from '@shared/ipcChannels'
import type { AppEvent } from '@shared/events/AppEvent'

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
  }
}

contextBridge.exposeInMainWorld('ljtm', api)

export type LjtmApi = typeof api
