import { useEffect } from 'react'
import { useAssetsStore } from '../../../state/assetsStore'
import { usePresetsStore } from '../../../state/presetsStore'

interface HowToUseModalProps {
  onClose(): void
}

/**
 * Quick reference, opened from the toolbar.
 *
 * Everything here is read from live state rather than written out as prose —
 * the map names come from the user's own `maps.yaml` and the presets from
 * whatever is actually in `preset-packs/`. A hardcoded list would start out
 * correct and quietly drift the first time either file is edited.
 */
export function HowToUseModal({ onClose }: HowToUseModalProps): JSX.Element {
  const mapConfig = useAssetsStore((state) => state.mapConfig)
  const presets = usePresetsStore((state) => state.presets)

  useEffect(() => {
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const delim = mapConfig.suffixDelims[0] ?? '_'

  return (
    <div className="modal__backdrop" onClick={onClose}>
      <div className="modal modal--wide" onClick={(event) => event.stopPropagation()}>
        <header className="modal__header">
          <h2>How To Use</h2>
          <button type="button" className="modal__close" onClick={onClose} title="Close">
            ✕
          </button>
        </header>

        <div className="modal__body howto">
          <section className="howto__section">
            <h3 className="panel__subtitle">Image Dump</h3>
            <p className="howto__lead">
              Name files <code>asset{delim}Map.png</code> — e.g. <code>wood{delim}Normal.png</code>.
            </p>
            <div className="howto__chips">
              {mapConfig.knownMaps.map((map, index) => (
                <span key={map} className={`chip ${index === 0 ? 'chip--primary' : ''}`}>
                  {map}
                  {index === 0 ? ' ★' : ''}
                </span>
              ))}
            </div>
            <p className="panel__hint">
              ★ is the primary map — the only one listed in Assets and the Outliner. The rest are
              found automatically at export.
            </p>
            {mapConfig.suffixDelims.length > 1 ? (
              <p className="panel__hint">
                Separators accepted: {mapConfig.suffixDelims.map((d) => `"${d}"`).join(' ')}
              </p>
            ) : null}
          </section>

          <section className="howto__section">
            <h3 className="panel__subtitle">
              Preset Packs
              <span className="panel__count">{presets.length}</span>
            </h3>
            {presets.length === 0 ? (
              <p className="panel__empty">
                Nothing in <code>preset-packs/</code>.
              </p>
            ) : (
              <ul className="howto__presets">
                {presets.map((preset) => (
                  <li key={preset.name}>
                    <span className="howto__preset-name">{preset.name}</span>
                    <span className="howto__preset-files">
                      {preset.outputs.map((output) => output.outputSuffix || '(no suffix)').join('  ')}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            <p className="panel__hint">One preset can write several textures. Tick them per sheet.</p>
          </section>

          <section className="howto__section">
            <h3 className="panel__subtitle">Workflow</h3>
            <ol className="howto__steps">
              <li>
                Drop textures into <code>image_dump/</code>, then hit <b>Refresh</b>.
              </li>
              <li>
                Add a sheet with <b>+</b> in the tab bar.
              </li>
              <li>
                Add assets with <b>+</b> on a tile in <b>Assets</b>.
              </li>
              <li>
                Pick a trim in the <b>Outliner</b>, move it in <b>Properties</b>.
              </li>
              <li>
                Tick presets in <b>Sheet Settings</b>.
              </li>
              <li>
                <b>Build</b> once, or leave <b>Auto Export</b> on.
              </li>
            </ol>
            <p className="panel__hint">
              Outliner order is draw order — top of the list sits on top. Undo covers moves and
              crops only.
            </p>
          </section>
        </div>

        <footer className="modal__footer">
          <button type="button" className="is-primary" onClick={onClose}>
            Got it
          </button>
        </footer>
      </div>
    </div>
  )
}
