import { QuantityInput } from '../controls/QuantityInput'
import { useActiveSheet, useProjectStore } from '../../../state/projectStore'
import { usePresetsStore } from '../../../state/presetsStore'
import { Resolution } from '@models/Resolution'

/**
 * Per-sheet settings: output resolution and which presets this sheet exports.
 *
 * Resolution is per sheet, not global — the project default only seeds new
 * sheets. Changing it here affects this sheet alone.
 */
export function SheetSettingsPanel(): JSX.Element {
  const sheet = useActiveSheet()
  const setSheetResolution = useProjectStore((state) => state.setSheetResolution)
  const setSheetPresets = useProjectStore((state) => state.setSheetPresets)
  const presets = usePresetsStore((state) => state.presets)
  const warnings = usePresetsStore((state) => state.warnings)

  if (!sheet) {
    return (
      <section className="panel">
        <h2 className="panel__title">Sheet Settings</h2>
        <p className="panel__empty">No sheet.</p>
      </section>
    )
  }

  const toggle = (name: string): void => {
    const enabled = sheet.enabledPresetNames.includes(name)
    setSheetPresets(
      sheet.id,
      enabled
        ? sheet.enabledPresetNames.filter((entry) => entry !== name)
        : [...sheet.enabledPresetNames, name]
    )
  }

  return (
    <section className="panel">
      <h2 className="panel__title">Sheet Settings</h2>

      <div className="panel__group">
        <h3 className="panel__subtitle">Output Resolution</h3>
        <QuantityInput
          label="W"
          suffix="px"
          step={16}
          min={1}
          value={sheet.resolution.width}
          onChange={(width) =>
            setSheetResolution(sheet.id, new Resolution(Math.round(width), sheet.resolution.height))
          }
        />
        <QuantityInput
          label="H"
          suffix="px"
          step={16}
          min={1}
          value={sheet.resolution.height}
          onChange={(height) =>
            setSheetResolution(sheet.id, new Resolution(sheet.resolution.width, Math.round(height)))
          }
        />
        <p className="panel__hint">Trims are stored proportionally, so resizing keeps the layout.</p>
      </div>

      <div className="panel__group">
        <h3 className="panel__subtitle">
          Enabled Presets
          <span className="panel__count">{sheet.enabledPresetNames.length}</span>
        </h3>

        {presets.length === 0 ? (
          <p className="panel__empty">
            No presets in <code>preset-packs/</code>.
          </p>
        ) : (
          <ul className="presets">
            {presets.map((preset) => (
              <li key={preset.name}>
                <label className="presets__row">
                  <input
                    type="checkbox"
                    checked={sheet.enabledPresetNames.includes(preset.name)}
                    onChange={() => toggle(preset.name)}
                  />
                  <span className="presets__name">{preset.name}</span>
                  {/* A preset can write several textures, so summarise here and
                      put the actual filenames on the tooltip. */}
                  <span
                    className="presets__meta"
                    title={preset.fileNames(sheet.name).join('\n')}
                  >
                    {preset.outputs.length} file{preset.outputs.length === 1 ? '' : 's'} ·{' '}
                    {preset.summary}
                  </span>
                </label>
              </li>
            ))}
          </ul>
        )}

        {/* Presets that failed to load are invisible otherwise — surface them
            here rather than letting a typo silently drop an output. */}
        {warnings.length > 0 ? (
          <details className="panel__warnings">
            <summary>
              {warnings.length} warning{warnings.length === 1 ? '' : 's'}
            </summary>
            <ul>
              {warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          </details>
        ) : null}
      </div>
    </section>
  )
}
