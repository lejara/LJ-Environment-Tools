import { EventBus } from '@shared/events/EventBus'
import { AppEvent, type AppEventPayloads } from '@shared/events/AppEvent'
import { bridge } from './bridge'

/**
 * The renderer's EventBus instance. Main has its own; the events listed in
 * BRIDGED_EVENTS arrive over IPC and are re-emitted here, so a renderer
 * subscriber can't tell whether an event originated locally or in main.
 */
export const appBus = new EventBus()

let attached = false

/** Called once at startup. Idempotent so React StrictMode double-mounts are safe. */
export function attachBusBridge(): void {
  if (attached) return
  attached = true
  bridge().onBusEvent((event, payload) => {
    appBus.emit(event as AppEvent, payload as AppEventPayloads[AppEvent])
  })
}
