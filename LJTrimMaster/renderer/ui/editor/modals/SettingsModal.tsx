import { useEffect, useState } from 'react'
import { QuantityInput } from '../controls/QuantityInput'
import { useProjectStore } from '../../../state/projectStore'
import { useAssetsStore } from '../../../state/assetsStore'
import { usePresetsStore } from '../../../state/presetsStore'
import { useBlenderLinksStore } from '../../../state/blenderLinksStore'
import { projectService } from '../../../services/projectService'
import { refreshService } from '../../../services/refreshService'
import { Resolution } from '@models/Resolution'
import { MapConfig } from '@models/MapConfig'

interface FolderFieldProps {
  label: string
  stockName: string
  value: string
  rootPath: string
  onChange(value: string): void
}

/** One folder row: editable path, Browse, and Reset back to the stock folder. */
function FolderField({ label, stockName, value, rootPath, onChange }: FolderFieldProps): JSX.Element {
  const browse = async (): Promise<void> => {
    const picked = await projectService.pickFolder(rootPath, `Choose the ${label} folder`, value || undefined)
    if (picked !== null) onChange(picked)
  }

  return (
    <div className="settings__folder">
      <span className="settings__folder-label">{label}</span>
      <input
        type="text"
        className="settings__folder-input"
        value={value}
        placeholder={`${stockName} (default)`}
        onChange={(event) => onChange(event.target.value)}
      />
      <button type="button" onClick={() => void browse()}>
        Browse…
      </button>
      <button type="button" disabled={!value} onClick={() => onChange('')} title="Use the default folder">
        Reset
      </button>
    </div>
  )
}

interface SettingsModalProps {
  onClose(): void
}

/**
 * Project-wide defaults, opened by the toolbar gear.
 *
 * These SEED new objects only — editing the default resolution does not
 * retroactively resize existing sheets, and the copy under the field says so,
 * because that is the one thing a user would reasonably expect to go the other way.
 *
 * Built to grow: add a field to ProjectDefaults and a group here.
 *
 * The Folders group is not a default — it takes effect immediately. Moving
 * image_dump triggers a refresh so the Assets panel follows it.
 */
export function SettingsModal({ onClose }: SettingsModalProps): JSX.Element {
  const project = useProjectStore((state) => state.project)
  const setDefaultResolution = useProjectStore((state) => state.setDefaultResolution)
  const save = useProjectStore((state) => state.save)
  const setFolders = useProjectStore((state) => state.setFolders)
  const setMapVocabulary = useProjectStore((state) => state.setMapVocabulary)
  const setAssets = useAssetsStore((state) => state.setFromSerialized)
  const setPresets = usePresetsStore((state) => state.setFromSerialized)
  const setBlenderLinks = useBlenderLinksStore((state) => state.setFromSerialized)

  const current = project?.data.defaults.defaultTrimResolution ?? Resolution.default()
  const [width, setWidth] = useState(current.width)
  const [height, setHeight] = useState(current.height)
  const currentFolders = project?.data.folders ?? {}
  const [imageDump, setImageDump] = useState(currentFolders.imageDump ?? '')
  const [output, setOutput] = useState(currentFolders.output ?? '')

  useEffect(() => {
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const apply = async (): Promise<void> => {
    const dumpMoved = imageDump.trim() !== (currentFolders.imageDump ?? '')
    setDefaultResolution(new Resolution(Math.round(width), Math.round(height)))
    setFolders({ imageDump, output })
    onClose()
    await save()

    const live = useProjectStore.getState().project
    if (!dumpMoved || !live) return
    const result = await refreshService.refreshAll(live.rootPath, live.data.folders)
    setAssets(result.assets, result.mapConfig)
    setPresets(result.presets, result.warnings)
    setBlenderLinks(result.blenderLinks)
    setMapVocabulary(MapConfig.deserialize(result.mapConfig))
  }

  return (
    <div className="modal__backdrop" onClick={onClose}>
      <div className="modal modal--wide" onClick={(event) => event.stopPropagation()}>
        <header className="modal__header">
          <h2>Settings</h2>
          <button type="button" className="modal__close" onClick={onClose} title="Close">
            ✕
          </button>
        </header>

        <div className="modal__body">
          <div className="panel__group">
            <h3 className="panel__subtitle">Default Trim Resolution</h3>
            <QuantityInput label="W" suffix="px" step={16} min={1} value={width} onChange={setWidth} />
            <QuantityInput label="H" suffix="px" step={16} min={1} value={height} onChange={setHeight} />
            <p className="panel__hint">
              Used for new trim sheets. Existing sheets keep their own resolution.
            </p>
          </div>

          {project ? (
            <div className="panel__group">
              <h3 className="panel__subtitle">Folders</h3>
              <FolderField
                label="Image Dump"
                stockName="image_dump"
                value={imageDump}
                rootPath={project.rootPath}
                onChange={setImageDump}
              />
              <FolderField
                label="Export Output"
                stockName="output"
                value={output}
                rootPath={project.rootPath}
                onChange={setOutput}
              />
              <p className="panel__hint">
                Absolute, or relative to the project folder. Each trim exports into its own
                subfolder named after the trim.
              </p>
            </div>
          ) : null}
        </div>

        <footer className="modal__footer">
          <button type="button" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="is-primary" onClick={() => void apply()}>
            Save
          </button>
        </footer>
      </div>
    </div>
  )
}
