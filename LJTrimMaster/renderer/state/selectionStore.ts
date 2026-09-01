import { create } from 'zustand'

/**
 * Which TrimImage is selected. Selection happens in the Outliner only — the
 * Viewport draws an outline for it but is not clickable, by design.
 *
 * Kept separate from projectStore so selecting doesn't bump the project
 * revision and re-render the whole editor.
 */
interface SelectionState {
  selectedImageId: string | null
  select(id: string | null): void
  clear(): void
}

export const useSelectionStore = create<SelectionState>((set) => ({
  selectedImageId: null,
  select: (id) => set({ selectedImageId: id }),
  clear: () => set({ selectedImageId: null })
}))

export const useSelectedImageId = (): string | null =>
  useSelectionStore((state) => state.selectedImageId)
