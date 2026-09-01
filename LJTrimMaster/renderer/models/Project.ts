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
