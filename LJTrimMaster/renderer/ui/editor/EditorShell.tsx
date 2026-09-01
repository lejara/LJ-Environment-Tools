import { useEffect, useState } from 'react'
import { Toolbar } from './Toolbar'
import { TabBar } from './TabBar'
import { Viewport } from './Viewport'
import { Sidebar } from './sidebar/Sidebar'
import { SettingsModal } from './modals/SettingsModal'
import { useProjectStore, useRevision } from '../../state/projectStore'
import { useAssetsStore } from '../../state/assetsStore'
import { usePresetsStore } from '../../state/presetsStore'
import { useSelectionStore } from '../../state/selectionStore'
import { autoExportService } from '../../services/autoExportService'
import { appBus } from '../../services/appBus'
import { AppEvent } from '@shared/events/AppEvent'

interface EditorShellProps {
  startupError: string | null
}

/**
 * Editor layout: tabs across the top, viewport + sidebar in the middle,
 * toolbar pinned to the bottom (per spec).
 */
export function EditorShell({ startupError }: EditorShellProps): JSX.Element {
  const project = useProjectStore((state) => state.project)
  const markSheetClean = useProjectStore((state) => state.markSheetClean)
  const undo = useProjectStore((state) => state.undo)
  const redo = useProjectStore((state) => state.redo)
  const select = useSelectionStore((state) => state.select)
  const rev = useRevision()
  const assets = useAssetsStore((state) => state.assets)
  const presets = usePresetsStore((state) => state.presets)

  const [settingsOpen, setSettingsOpen] = useState(false)
  const [status, setStatus] = useState<string | null>(startupError)

  // Keep main's AutoExporter mirror in step with the live project. Runs on
  // every revision bump; main only acts on it when the toggle is on.
  useEffect(() => {
    if (!project) return
    void autoExportService
      .syncSheets({
        sheets: project.sheets.map((sheet) => sheet.serialize()),
        dirtyIds: project.dirtySheets.map((sheet) => sheet.id),
        assets: assets.map((asset) => asset.serialize()),
        presets: presets.map((preset) => preset.serialize()),
        projectRoot: project.rootPath
      })
      .catch(() => {
        /* mirror sync is best-effort; the next edit re-sends it */
      })
  }, [project, rev, assets, presets])

  // Main's AutoExporter clears its own mirror's dirty flag inline. This clears
  // the renderer's authoritative copy off the bridged completion event.
  useEffect(() => {
    const offDone = appBus.on(AppEvent.EXPORT_COMPLETED, ({ sheetId, outputPaths, warnings }) => {
      markSheetClean(sheetId)

      if (outputPaths.length === 0) {
        setStatus('Export finished — no presets enabled for this sheet.')
        return
      }

      // A fallen-back channel still writes a file, so the count alone would
      // read as total success. Say when something quietly degraded.
      const files = `Exported ${outputPaths.length} file${outputPaths.length === 1 ? '' : 's'}`
      setStatus(
        warnings.length === 0
          ? `${files}.`
          : `${files} with ${warnings.length} warning${warnings.length === 1 ? '' : 's'} — ${warnings[0]}`
      )
      for (const warning of warnings) console.warn('[export]', warning)
    })
    const offFail = appBus.on(AppEvent.EXPORT_FAILED, ({ presetName, error }) => {
      setStatus(`Export failed on "${presetName}": ${error}`)
    })
    const offRefresh = appBus.on(AppEvent.REFRESH_COMPLETED, ({ assets: scanned, warnings }) => {
      setStatus(
        warnings.length > 0
          ? `Refreshed with ${warnings.length} warning${warnings.length === 1 ? '' : 's'}.`
          : `Refreshed — ${scanned.length} asset${scanned.length === 1 ? '' : 's'} found.`
      )
    })
    return () => {
      offDone()
      offFail()
      offRefresh()
    }
  }, [markSheetClean])

  // Undo/redo are transform + crop only, per sheet. Ignored while typing.
  useEffect(() => {
    const onKey = (event: KeyboardEvent): void => {
      if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== 'z') return
      const target = event.target as HTMLElement | null
      if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA')) return

      event.preventDefault()
      const changedId = event.shiftKey ? redo() : undo()
      if (changedId) select(changedId)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [undo, redo, select])

  if (!project) return <div className="editor editor--empty">No project open.</div>

  return (
    <div className="editor">
      <TabBar />
      <div className="editor__body">
        <Viewport />
        <Sidebar />
      </div>
      <Toolbar onOpenSettings={() => setSettingsOpen(true)} status={status} onStatus={setStatus} />
      {settingsOpen ? <SettingsModal onClose={() => setSettingsOpen(false)} /> : null}
    </div>
  )
}
