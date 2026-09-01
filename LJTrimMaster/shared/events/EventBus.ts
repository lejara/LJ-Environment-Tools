import { AppEvent, type AppEventPayloads } from './AppEvent'

export type Handler<E extends AppEvent> = (payload: AppEventPayloads[E]) => void
export type Unsubscribe = () => void

/**
 * Typed pub/sub. One instance per process — main and renderer each own their
 * own; main bridges the events in BRIDGED_EVENTS across IPC.
 *
 * A throwing handler is logged and skipped so one bad listener can't take down
 * the rest of an emit.
 */
export class EventBus {
  private handlers = new Map<AppEvent, Set<Handler<AppEvent>>>()

  on<E extends AppEvent>(event: E, handler: Handler<E>): Unsubscribe {
    let set = this.handlers.get(event)
    if (!set) {
      set = new Set()
      this.handlers.set(event, set)
    }
    set.add(handler as Handler<AppEvent>)
    return () => this.off(event, handler)
  }

  off<E extends AppEvent>(event: E, handler: Handler<E>): void {
    this.handlers.get(event)?.delete(handler as Handler<AppEvent>)
  }

  emit<E extends AppEvent>(event: E, payload: AppEventPayloads[E]): void {
    const set = this.handlers.get(event)
    if (!set) return
    // Copy first: a handler may unsubscribe itself mid-emit.
    for (const handler of [...set]) {
      try {
        ;(handler as Handler<E>)(payload)
      } catch (err) {
        console.error(`[EventBus] handler for ${event} threw:`, err)
      }
    }
  }

  clear(): void {
    this.handlers.clear()
  }
}
