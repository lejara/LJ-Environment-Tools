import { create } from 'zustand'
import { Project } from '@models/Project'
import { Resolution } from '@models/Resolution'
import { Snapshot } from '@models/Snapshot'
import type { TrimImage } from '@models/TrimImage'
import type { TrimSheet } from '@models/TrimSheet'
import type { OpenProjectResult } from '@shared/types'
import { projectService } from '../services/projectService'

/**
 * The open Project.
 *
 * The models are mutable classes, which zustand can't see into — so every
 * mutating action bumps `rev`. Components select `rev` to subscribe to "the
 * project changed at all"; they read the actual values straight off the model.
 * That keeps the models free of React and avoids deep-cloning a sheet on every
 * drag of a QuantityInput.
 */
interface ProjectState {
  project: Project | null
  rev: number

  openFrom(result: OpenProjectResult): void
  close(): void

  addSheet(name?: string): void
  removeSheet(id: string): void
  renameSheet(id: string, name: string): void
  setActiveSheet(id: string): void

  addImage(assetBaseName: string): TrimImage | null
  removeImage(id: string): void
  reorder(fromIndex: number, toIndex: number): void

  /**
   * Mutate an image's transform/crop with undo recorded.
   * `commit` false is for live drags — it applies the change without pushing a
   * new history entry, so a drag collapses into one undo step. Pass true on the
   * first change of a gesture, false for the rest.
   */
  editImage(id: string, mutate: (image: TrimImage) => void, commit?: boolean): void

  undo(): string | null
  redo(): string | null

  setSheetResolution(sheetId: string, resolution: Resolution): void
  setSheetPresets(sheetId: string, presetNames: string[]): void
  setDefaultResolution(resolution: Resolution): void

  markSheetClean(sheetId: string): void
  save(): Promise<void>
  touch(): void
}

export const useProjectStore = create<ProjectState>((set, get) => {
  /** Applies a mutation to the live model and signals subscribers. */
  const mutate = (fn: (project: Project) => void): void => {
    const { project } = get()
    if (!project) return
    fn(project)
    set((state) => ({ rev: state.rev + 1 }))
  }

  const withActiveSheet = (fn: (sheet: TrimSheet) => void): void =>
    mutate((project) => {
      const sheet = project.activeSheet
      if (sheet) fn(sheet)
    })

  return {
    project: null,
    rev: 0,

    openFrom: (result) =>
      set({ project: Project.fromSerialized(result.rootPath, result.data), rev: 0 }),

    close: () => set({ project: null, rev: 0 }),

    addSheet: (name) => mutate((project) => void project.addSheet(name)),
    removeSheet: (id) => mutate((project) => project.removeSheet(id)),
    renameSheet: (id, name) => mutate((project) => project.renameSheet(id, name)),
    setActiveSheet: (id) => mutate((project) => project.setActiveSheet(id)),

    addImage: (assetBaseName) => {
      const sheet = get().project?.activeSheet
      if (!sheet) return null
      const image = sheet.addImage(assetBaseName)
      set((state) => ({ rev: state.rev + 1 }))
      return image
    },

    removeImage: (id) => withActiveSheet((sheet) => sheet.removeImage(id)),
    reorder: (fromIndex, toIndex) => withActiveSheet((sheet) => sheet.reorder(fromIndex, toIndex)),

    editImage: (id, mutateImage, commit = true) =>
      withActiveSheet((sheet) => {
        const image = sheet.find(id)
        if (!image) return
        if (commit) sheet.recordEdit(image)
        mutateImage(image)
        sheet.markDirty()
      }),

    undo: () => {
      let changed: string | null = null
      withActiveSheet((sheet) => {
        changed = sheet.undo()
      })
      return changed
    },

    redo: () => {
      let changed: string | null = null
      withActiveSheet((sheet) => {
        changed = sheet.redo()
      })
      return changed
    },

    setSheetResolution: (sheetId, resolution) =>
      mutate((project) => project.findSheet(sheetId)?.setResolution(resolution)),

    setSheetPresets: (sheetId, presetNames) =>
      mutate((project) => project.findSheet(sheetId)?.setEnabledPresets(presetNames)),

    setDefaultResolution: (resolution) =>
      mutate((project) => project.setDefaultResolution(resolution)),

    markSheetClean: (sheetId) => mutate((project) => project.findSheet(sheetId)?.clearDirty()),

    save: async () => {
      const { project } = get()
      if (!project) return
      await projectService.save(project.rootPath, project.serialize())
    },

    touch: () => set((state) => ({ rev: state.rev + 1 }))
  }
})

/** Convenience selectors. Each subscribes to `rev`, so they re-run on any edit. */
export const useProject = (): Project | null =>
  useProjectStore((state) => {
    void state.rev
    return state.project
  })

export const useActiveSheet = (): TrimSheet | null =>
  useProjectStore((state) => {
    void state.rev
    return state.project?.activeSheet ?? null
  })

/** Subscribe to "something changed" without caring what. */
export const useRevision = (): number => useProjectStore((state) => state.rev)

/** Snapshot helper for callers that want to hand-roll a history entry. */
export const captureSnapshot = Snapshot.capture
