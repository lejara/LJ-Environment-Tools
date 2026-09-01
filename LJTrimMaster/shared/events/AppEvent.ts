import type { SerializedAsset, SerializedMapConfig, SerializedPreset } from '../types'

/**
 * The only events on the bus. Scope is intentionally narrow: two families,
 * REFRESH_* and EXPORT_*. Property edits, selection, tab switches and
 * project open/save go through state stores or direct service calls instead.
 *
 * Before adding a name here, check it is a genuine broadcast — several
 * listeners that don't know about each other. If there is one emitter and one
 * consumer, call it directly.
 */
export enum AppEvent {
  REFRESH_REQUESTED = 'REFRESH_REQUESTED',
  REFRESH_COMPLETED = 'REFRESH_COMPLETED',
  EXPORT_STARTED = 'EXPORT_STARTED',
  EXPORT_COMPLETED = 'EXPORT_COMPLETED',
  EXPORT_FAILED = 'EXPORT_FAILED'
}

export interface RefreshRequestedPayload {
  /** undefined when no project is open — only global config reloads. */
  projectRoot?: string
}

export interface RefreshCompletedPayload {
  mapConfig: SerializedMapConfig
  presets: SerializedPreset[]
  assets: SerializedAsset[]
  warnings: string[]
}

export interface ExportStartedPayload {
  sheetId: string
  presetNames: string[]
}

export interface ExportCompletedPayload {
  sheetId: string
  outputPaths: string[]
  /**
   * Non-fatal problems from this export — a missing source map that fell back,
   * a trim whose asset is no longer in image_dump. The export still produced
   * files; these say where it quietly degraded.
   */
  warnings: string[]
}

export interface ExportFailedPayload {
  sheetId: string
  presetName: string
  error: string
}

/** Maps each event to its payload so `emit`/`on` are type-checked at the call site. */
export interface AppEventPayloads {
  [AppEvent.REFRESH_REQUESTED]: RefreshRequestedPayload
  [AppEvent.REFRESH_COMPLETED]: RefreshCompletedPayload
  [AppEvent.EXPORT_STARTED]: ExportStartedPayload
  [AppEvent.EXPORT_COMPLETED]: ExportCompletedPayload
  [AppEvent.EXPORT_FAILED]: ExportFailedPayload
}

/** Events that main forwards to the renderer over IPC. */
export const BRIDGED_EVENTS: AppEvent[] = [
  AppEvent.REFRESH_COMPLETED,
  AppEvent.EXPORT_STARTED,
  AppEvent.EXPORT_COMPLETED,
  AppEvent.EXPORT_FAILED
]
