import { Resolution } from './Resolution'
import { Vec2 } from './Vec2'
import { TrimImage } from './TrimImage'
import { HistoryStack } from './HistoryStack'
import { Snapshot } from './Snapshot'
import type { SerializedSheet } from '@shared/types'

/**
 * One tab in the editor.
 *
 * `items` is in draw order: index 0 is drawn first (bottom), the last index is
 * drawn last (on top). The Outliner shows this list REVERSED, so the top row of
 * the Outliner is the top of the z-order — see `displayOrder`.
 *
 * `isDirty` is set by any edit and consumed by AutoExporter, which clears it
 * inline after Exporter.export() returns.
 */
export class TrimSheet {
  readonly history = new HistoryStack()
  isDirty = false

  constructor(
    public readonly id: string,
    public name: string,
    public resolution: Resolution,
    public enabledPresetNames: string[] = [],
    public items: TrimImage[] = []
  ) {}

  /** Items top-of-z-order first, which is the order the Outliner renders. */
  get displayOrder(): TrimImage[] {
    return [...this.items].reverse()
  }

  find(id: string): TrimImage | undefined {
    return this.items.find((item) => item.id === id)
  }

  /**
   * Adds on top of the z-order.
   *
   * *sourceSize* is the source image's pixel dimensions. When known, the trim
   * lands at 1:1 texel density - its default size is exactly the image's size
   * on this sheet - which is almost always what you want and saves typing two
   * numbers. An image larger than the sheet lands **oversized** rather than
   * clamped: silently shrinking it would hide that the sheet is too small.
   *
   * Unknown size falls back to the Transform default, which is what happens if
   * the thumbnail has not decoded yet; `projectStore.addImage` corrects it once
   * the probe resolves.
   */
  addImage(assetBaseName: string, sourceSize?: { width: number; height: number }): TrimImage {
    const image = TrimImage.create(assetBaseName)
    if (sourceSize && sourceSize.width > 0 && sourceSize.height > 0) {
      image.transform.scale = new Vec2(
        sourceSize.width / this.resolution.width,
        sourceSize.height / this.resolution.height
      )
    }
    this.items.push(image)
    this.markDirty()
    return image
  }

  removeImage(id: string): void {
    const index = this.items.findIndex((item) => item.id === id)
    if (index === -1) return
    this.items.splice(index, 1)
    this.markDirty()
  }

  /**
   * Show or hide a trim. Marks the sheet dirty, because hiding changes what the
   * exporter writes — it is not a preview-only convenience.
   *
   * Not undoable, consistent with add / remove / reorder / rename.
   */
  setVisible(id: string, visible: boolean): void {
    const image = this.find(id)
    if (!image || image.visible === visible) return
    image.visible = visible
    this.markDirty()
  }

  /** What the exporter draws. Hidden trims are not on the sheet. */
  get visibleItems(): TrimImage[] {
    return this.items.filter((item) => item.visible)
  }

  /** Both indices are in draw order, not Outliner display order. */
  reorder(fromIndex: number, toIndex: number): void {
    if (fromIndex === toIndex) return
    if (fromIndex < 0 || fromIndex >= this.items.length) return
    if (toIndex < 0 || toIndex >= this.items.length) return
    const [moved] = this.items.splice(fromIndex, 1)
    this.items.splice(toIndex, 0, moved)
    this.markDirty()
  }

  setResolution(resolution: Resolution): void {
    this.resolution = resolution
    this.markDirty()
  }

  setEnabledPresets(names: string[]): void {
    this.enabledPresetNames = [...names]
    this.markDirty()
  }

  markDirty(): void {
    this.isDirty = true
  }

  clearDirty(): void {
    this.isDirty = false
  }

  // --- Undo / redo (transform + crop only) ---------------------------------

  /** Call immediately BEFORE mutating an item's transform or crop. */
  recordEdit(image: TrimImage): void {
    this.history.push(Snapshot.capture(image))
  }

  /** @returns the id of the image that changed, or null if nothing to undo. */
  undo(): string | null {
    return this.step('undo')
  }

  /** @returns the id of the image that changed, or null if nothing to redo. */
  redo(): string | null {
    return this.step('redo')
  }

  /**
   * Shared undo/redo body. Peeks at the pending step to learn which image it
   * targets, banks that image's current state on the opposite stack, then
   * restores.
   *
   * If the target image has since been removed (remove is not undoable, so this
   * is reachable), the step is dropped rather than restored and we move to the
   * next one — otherwise the stack would wedge on a dangling entry forever.
   */
  private step(direction: 'undo' | 'redo'): string | null {
    const peek = direction === 'undo' ? () => this.history.peekUndo() : () => this.history.peekRedo()
    const drop = direction === 'undo' ? () => this.history.dropUndo() : () => this.history.dropRedo()
    const take =
      direction === 'undo'
        ? (current: Snapshot) => this.history.undo(current)
        : (current: Snapshot) => this.history.redo(current)

    for (;;) {
      const pending = peek()
      if (!pending) return null

      const image = this.find(pending.trimImageId)
      if (!image) {
        drop()
        continue
      }

      const restored = take(Snapshot.capture(image))
      if (!restored) return null
      restored.applyTo(image)
      this.markDirty()
      return image.id
    }
  }

  // --- Serialization -------------------------------------------------------

  serialize(): SerializedSheet {
    return {
      id: this.id,
      name: this.name,
      resolution: this.resolution.serialize(),
      enabledPresetNames: [...this.enabledPresetNames],
      items: this.items.map((item) => item.serialize())
    }
  }

  static deserialize(raw: SerializedSheet): TrimSheet {
    return new TrimSheet(
      raw.id,
      raw.name,
      Resolution.deserialize(raw.resolution),
      [...raw.enabledPresetNames],
      raw.items.map((item) => TrimImage.deserialize(item))
    )
  }

  static create(name: string, resolution: Resolution): TrimSheet {
    return new TrimSheet(crypto.randomUUID(), name, resolution.clone())
  }
}
