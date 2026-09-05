import { create } from 'zustand'
import { Project } from '@models/Project'
import { Resolution } from '@models/Resolution'
import { MapConfig } from '@models/MapConfig'
import { Vec2 } from '@models/Vec2'
import { Snapshot } from '@models/Snapshot'
import type { TrimImage } from '@models/TrimImage'
import type { TrimSheet } from '@models/TrimSheet'
import type { OpenProjectResult } from '@shared/types'
import { projectService } from '../services/projectService'
import type { PixelSize } from './assetsStore'

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

  /**
   * Adds a trim, sized to the source image where its dimensions are known.
   * Pass *sourceSize* to size it synchronously; otherwise the caller may
   * probe and call `resizeToSource` once the image decodes.
   */
  addImage(assetBaseName: string, sourceSize?: PixelSize): TrimImage | null
  /** Late correction for a trim added before its image had decoded. */
  resizeToSource(id: string, sourceSize: PixelSize): void
  removeImage(id: string): void
  reorder(fromIndex: number, toIndex: number): void
  /** Hidden trims are skipped by the exporter and by the Blender addon. */
  setImageVisible(id: string, visible: boolean): void

  /**
   * Moves a trim to another sheet, preserving its id and pixel geometry.
   * Not undoable, consistent with add/remove/reorder/rename.
   * @returns true if the move happened.
   */
  moveImage(imageId: string, toSheetId: string): boolean

  /**
   * Mutate an image's transform/crop with undo recorded.
   * `commit` false is for live drags — it applies the change without pushing a
   * new history entry, so a drag collapses into one undo step. Pass true on the
   * first change of a gesture, false for the rest.
   */
  editImage(id: string, mutate: (image: TrimImage) => void, commit?: boolean): void

  undo(): string | null
  redo(): string | null

  /**
   * Caches the maps.yaml vocabulary into projectData.json.
   *
   * maps.yaml lives next to the binary, so the Blender addon cannot see it —
   * and without it the two disagree about where a base name ends and a map
   * suffix begins. Stamped on every refresh; it then rides along on the normal
   * autosave. No-op when nothing changed, so it never dirties a save on its own.
   */
  setMapVocabulary(mapConfig: MapConfig): void

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

    addImage: (assetBaseName, sourceSize) => {
      const sheet = get().project?.activeSheet
      if (!sheet) return null
      const image = sheet.addImage(assetBaseName, sourceSize)
      set((state) => ({ rev: state.rev + 1 }))
      return image
    },

    resizeToSource: (id, sourceSize) =>
      withActiveSheet((sheet) => {
        const image = sheet.find(id)
        if (!image || sourceSize.width <= 0 || sourceSize.height <= 0) return
        image.transform.scale = new Vec2(
          sourceSize.width / sheet.resolution.width,
          sourceSize.height / sheet.resolution.height
        )
        sheet.markDirty()
      }),

    removeImage: (id) => withActiveSheet((sheet) => sheet.removeImage(id)),
    reorder: (fromIndex, toIndex) => withActiveSheet((sheet) => sheet.reorder(fromIndex, toIndex)),

    setImageVisible: (id, visible) => withActiveSheet((sheet) => sheet.setVisible(id, visible)),

    moveImage: (imageId, toSheetId) => {
      const { project } = get()
      const from = project?.activeSheetId
      if (!project || !from) return false
      const moved = project.moveImage(imageId, from, toSheetId)
      // Deliberately does NOT switch tabs — the user asked to move the trim
      // away, not to go with it.
      if (moved) set((state) => ({ rev: state.rev + 1 }))
      return moved
    },

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

    setMapVocabulary: (mapConfig) => {
      const { project } = get()
      if (!project) return
      const current = project.data.maps
      if (current && MapConfig.sameAs(current, mapConfig)) return
      project.data.maps = mapConfig
      set((state) => ({ rev: state.rev + 1 }))
      // Saved right away rather than left to ride the autosave. Refresh is not
      // an edit, so nothing else would ever flush it — a user who changes
      // maps.yaml and hits Refresh must not have to also nudge a trim before
      // the addon can see the new vocabulary.
      void get().save().catch(() => undefined)
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
