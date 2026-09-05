import { ProjectData } from './ProjectData'
import { TrimSheet } from './TrimSheet'
import { Resolution } from './Resolution'
import type { SerializedProjectData } from '@shared/types'

/**
 * Root aggregate: the open project. Owns the sheet list, which sheet is active,
 * and the defaults.
 *
 * Pure state — no IPC. Persisting goes through projectService, which calls
 * `serialize()` and ships the result to main/fs/projectFs.
 */
export class Project {
  constructor(
    public readonly rootPath: string,
    public data: ProjectData,
    public sheets: TrimSheet[] = [],
    public activeSheetId: string | null = null
  ) {}

  get activeSheet(): TrimSheet | null {
    if (!this.activeSheetId) return null
    return this.sheets.find((sheet) => sheet.id === this.activeSheetId) ?? null
  }

  get name(): string {
    return this.rootPath.split(/[\\/]/).filter(Boolean).pop() ?? 'Untitled'
  }

  get dirtySheets(): TrimSheet[] {
    return this.sheets.filter((sheet) => sheet.isDirty)
  }

  findSheet(id: string): TrimSheet | undefined {
    return this.sheets.find((sheet) => sheet.id === id)
  }

  /** New sheets are seeded from the project default resolution, then own their copy. */
  addSheet(name?: string): TrimSheet {
    const sheet = TrimSheet.create(
      name ?? this.nextSheetName(),
      this.data.defaults.defaultTrimResolution
    )
    this.sheets.push(sheet)
    this.activeSheetId = sheet.id
    return sheet
  }

  removeSheet(id: string): void {
    const index = this.sheets.findIndex((sheet) => sheet.id === id)
    if (index === -1) return
    this.sheets.splice(index, 1)
    if (this.activeSheetId !== id) return
    // Fall back to the neighbour that took its place, else the new last sheet.
    const fallback = this.sheets[index] ?? this.sheets[this.sheets.length - 1]
    this.activeSheetId = fallback?.id ?? null
  }

  renameSheet(id: string, name: string): void {
    const sheet = this.findSheet(id)
    if (sheet) sheet.name = name
  }

  setActiveSheet(id: string): void {
    if (this.findSheet(id)) this.activeSheetId = id
  }

  /**
   * Moves a trim from one sheet to another, preserving its `id`.
   *
   * Lives on Project rather than TrimSheet because it spans two sheets. The
   * preserved `id` is the point: it is the Blender addon's only resolution key,
   * so a mesh linked to this trim keeps working and simply reports "needs
   * re-export" — the addon derives the sheet by scan and never stores it.
   *
   * The transform is recomputed to preserve **pixel** geometry:
   *
   *     newScale = oldScale * oldRes / newRes
   *     newPos   = oldPos   * oldRes / newRes
   *
   * Texel density is preserved, and rotation stays correct because rotation
   * happens in pixel space — it is only invariant if the pixel box is. The
   * ratio is positive, so mirroring survives. `rotation` and `crop` carry over
   * untouched; neither depends on sheet resolution. A same-resolution move is
   * therefore a byte-identical no-op, which is the sheet-split case.
   *
   * Appends to the target, so it arrives on top of the z-order, matching
   * `addImage`. Marks BOTH sheets dirty. **Not undoable**, consistent with
   * add/remove/reorder/rename. Dangling history needs no work: `TrimSheet.step`
   * already drops snapshots whose image is no longer on the sheet.
   */
  moveImage(imageId: string, fromSheetId: string, toSheetId: string): boolean {
    if (fromSheetId === toSheetId) return false
    const from = this.findSheet(fromSheetId)
    const to = this.findSheet(toSheetId)
    if (!from || !to) return false

    const index = from.items.findIndex((item) => item.id === imageId)
    if (index === -1) return false
    const [image] = from.items.splice(index, 1)

    const ratioX = from.resolution.width / to.resolution.width
    const ratioY = from.resolution.height / to.resolution.height
    image.transform.position.x *= ratioX
    image.transform.position.y *= ratioY
    image.transform.scale.x *= ratioX
    image.transform.scale.y *= ratioY

    to.items.push(image)
    from.markDirty()
    to.markDirty()
    return true
  }

  setDefaultResolution(resolution: Resolution): void {
    // Deliberately does NOT touch existing sheets — each keeps its own.
    this.data.defaults.defaultTrimResolution = resolution
  }

  serialize(): SerializedProjectData {
    return this.data.serialize(this.sheets)
  }

  private nextSheetName(): string {
    const taken = new Set(this.sheets.map((sheet) => sheet.name))
    for (let n = this.sheets.length + 1; ; n += 1) {
      const candidate = `Sheet ${n}`
      if (!taken.has(candidate)) return candidate
    }
  }

  static fromSerialized(rootPath: string, raw: SerializedProjectData): Project {
    const sheets = raw.sheets.map((sheet) => TrimSheet.deserialize(sheet))
    return new Project(rootPath, ProjectData.deserialize(raw), sheets, sheets[0]?.id ?? null)
  }
}
