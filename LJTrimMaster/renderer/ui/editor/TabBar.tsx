import { useState } from 'react'
import { useProjectStore, useRevision } from '../../state/projectStore'
import { useSelectionStore } from '../../state/selectionStore'
import { describeLinks, useBlenderLinksStore } from '../../state/blenderLinksStore'
import type { TrimSheet } from '@models/TrimSheet'

/**
 * Trim sheet tabs: add, rename (double-click), remove.
 * None of these are undoable — that's deliberate, undo is transforms + crop only.
 */
export function TabBar(): JSX.Element {
  const project = useProjectStore((state) => state.project)
  const addSheet = useProjectStore((state) => state.addSheet)
  const removeSheet = useProjectStore((state) => state.removeSheet)
  const renameSheet = useProjectStore((state) => state.renameSheet)
  const setActiveSheet = useProjectStore((state) => state.setActiveSheet)
  const clearSelection = useSelectionStore((state) => state.clear)
  const linksForTrims = useBlenderLinksStore((state) => state.forTrims)
  useRevision()

  /**
   * Warn before removing a sheet whose trims Blender meshes are unwrapped
   * against. Warn, do not block — `blender_links/` is advisory and may be stale.
   */
  const confirmSheetRemoval = (sheet: TrimSheet): boolean => {
    const summary = describeLinks(linksForTrims(sheet.items.map((item) => item.id)))
    if (!summary) return true
    return window.confirm(`Remove the sheet "${sheet.name}" and its ${sheet.items.length} trim(s)?\n\n${summary}`)
  }

  const [editingId, setEditingId] = useState<string | null>(null)
  const [draft, setDraft] = useState('')

  if (!project) return <nav className="tabbar" />

  const beginRename = (id: string, current: string): void => {
    setEditingId(id)
    setDraft(current)
  }

  const commitRename = (): void => {
    if (editingId && draft.trim()) renameSheet(editingId, draft.trim())
    setEditingId(null)
  }

  const switchTo = (id: string): void => {
    if (id === project.activeSheetId) return
    setActiveSheet(id)
    // Selection is per-sheet; carrying an id across tabs would point at nothing.
    clearSelection()
  }

  return (
    <nav className="tabbar">
      {project.sheets.map((sheet) => {
        const isActive = sheet.id === project.activeSheetId
        return (
          <div
            key={sheet.id}
            className={`tab ${isActive ? 'tab--active' : ''}`}
            onClick={() => switchTo(sheet.id)}
            onDoubleClick={() => beginRename(sheet.id, sheet.name)}
          >
            {editingId === sheet.id ? (
              <input
                className="tab__rename"
                autoFocus
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                onBlur={commitRename}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') commitRename()
                  if (event.key === 'Escape') setEditingId(null)
                }}
                onClick={(event) => event.stopPropagation()}
              />
            ) : (
              <>
                <span className="tab__name">{sheet.name}</span>
                {sheet.isDirty ? <span className="tab__dirty" title="Unexported changes">•</span> : null}
                <button
                  type="button"
                  className="tab__close"
                  title="Remove sheet"
                  onClick={(event) => {
                    event.stopPropagation()
                    if (!confirmSheetRemoval(sheet)) return
                    removeSheet(sheet.id)
                    clearSelection()
                  }}
                >
                  ✕
                </button>
              </>
            )}
          </div>
        )
      })}

      <button type="button" className="tabbar__add" title="New trim sheet" onClick={() => addSheet()}>
        +
      </button>
    </nav>
  )
}
