import type { Snapshot } from './Snapshot'

/**
 * Per-sheet undo/redo of transform + crop edits. Owned by TrimSheet, so it
 * survives tab switches.
 *
 * `push` takes the state as it was BEFORE an edit. Undo therefore needs the
 * caller to hand back the current state so it can be banked for redo — see
 * `undo(current)` / `redo(current)`.
 */
export class HistoryStack {
  private undoStack: Snapshot[] = []
  private redoStack: Snapshot[] = []

  constructor(private readonly limit: number = 100) {}

  get canUndo(): boolean {
    return this.undoStack.length > 0
  }

  get canRedo(): boolean {
    return this.redoStack.length > 0
  }

  /**
   * Which image the next undo/redo targets, without consuming the step.
   * TrimSheet needs this to know whose current state to bank before restoring.
   */
  peekUndo(): Snapshot | null {
    return this.undoStack[this.undoStack.length - 1] ?? null
  }

  peekRedo(): Snapshot | null {
    return this.redoStack[this.redoStack.length - 1] ?? null
  }

  /** Drop the next undo step without restoring it — used when its image is gone. */
  dropUndo(): void {
    this.undoStack.pop()
  }

  dropRedo(): void {
    this.redoStack.pop()
  }

  /** Record the pre-edit state. Invalidates the redo branch. */
  push(snapshot: Snapshot): void {
    this.undoStack.push(snapshot)
    if (this.undoStack.length > this.limit) this.undoStack.shift()
    this.redoStack.length = 0
  }

  /** @param current state to bank for redo. @returns state to restore, or null. */
  undo(current: Snapshot): Snapshot | null {
    const previous = this.undoStack.pop()
    if (!previous) return null
    this.redoStack.push(current)
    return previous
  }

  /** @param current state to bank for undo. @returns state to restore, or null. */
  redo(current: Snapshot): Snapshot | null {
    const next = this.redoStack.pop()
    if (!next) return null
    this.undoStack.push(current)
    return next
  }

  clear(): void {
    this.undoStack.length = 0
    this.redoStack.length = 0
  }
}
