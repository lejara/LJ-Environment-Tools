import type { AppEvent } from '@shared/events/AppEvent'

/**
 * Typed accessor for the preload bridge. Everything the renderer sends to main
 * goes through here, so there is one place that knows `window.ljtm` exists.
 */
interface LjtmBridge {
  invoke(channel: string, ...args: unknown[]): Promise<unknown>
  onBusEvent(handler: (event: AppEvent, payload: unknown) => void): () => void
}

declare global {
  interface Window {
    ljtm: LjtmBridge
  }
}

export function bridge(): LjtmBridge {
  if (!window.ljtm) {
    throw new Error('Preload bridge is missing — the renderer was loaded without preload.js.')
  }
  return window.ljtm
}

export async function invoke<T>(channel: string, ...args: unknown[]): Promise<T> {
  return (await bridge().invoke(channel, ...args)) as T
}

/**
 * Absolute path -> a URL the renderer can put in an <img src>.
 * Backed by the ljtm:// protocol registered in main.
 */
export function assetUrl(absolutePath: string): string {
  return `ljtm://local/${encodeURIComponent(absolutePath.replace(/\\/g, '/'))}`
}
