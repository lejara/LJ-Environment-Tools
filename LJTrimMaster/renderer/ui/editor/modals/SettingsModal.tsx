import { useEffect, useState } from 'react'
import { QuantityInput } from '../controls/QuantityInput'
import { useProjectStore } from '../../../state/projectStore'
import { Resolution } from '@models/Resolution'

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
 */
export function SettingsModal({ onClose }: SettingsModalProps): JSX.Element {
  const project = useProjectStore((state) => state.project)
  const setDefaultResolution = useProjectStore((state) => state.setDefaultResolution)
  const save = useProjectStore((state) => state.save)

  const current = project?.data.defaults.defaultTrimResolution ?? Resolution.default()
  const [width, setWidth] = useState(current.width)
  const [height, setHeight] = useState(current.height)

  useEffect(() => {
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const apply = (): void => {
    setDefaultResolution(new Resolution(Math.round(width), Math.round(height)))
    void save()
    onClose()
  }

  return (
    <div className="modal__backdrop" onClick={onClose}>
      <div className="modal" onClick={(event) => event.stopPropagation()}>
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
        </div>

        <footer className="modal__footer">
          <button type="button" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="is-primary" onClick={apply}>
            Save
          </button>
        </footer>
      </div>
    </div>
  )
}
