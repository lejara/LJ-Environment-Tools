import { useMemo, useState } from 'react'
import { useAssets } from '../../../state/assetsStore'
import { useProjectStore, useActiveSheet } from '../../../state/projectStore'
import { useSelectionStore } from '../../../state/selectionStore'
import { assetUrl } from '../../../services/bridge'

/**
 * Everything found in image_dump/, as a thumbnail grid. The + on a tile adds
 * that asset to the active sheet.
 *
 * Only the primary map (BaseColor by default) is listed — siblings like
 * Roughness and Normal are resolved at export time, so showing them here would
 * just be five rows per texture with no way to act on them.
 */
export function AssetsPanel(): JSX.Element {
  const assets = useAssets()
  const sheet = useActiveSheet()
  const addImage = useProjectStore((state) => state.addImage)
  const select = useSelectionStore((state) => state.select)
  const [filter, setFilter] = useState('')

  const shown = useMemo(() => {
    const needle = filter.trim().toLowerCase()
    if (!needle) return assets
    return assets.filter((asset) => asset.baseName.toLowerCase().includes(needle))
  }, [assets, filter])

  const add = (baseName: string): void => {
    const image = addImage(baseName)
    if (image) select(image.id)
  }

  return (
    <section className="panel panel--grow">
      <h2 className="panel__title">
        Assets
        <span className="panel__count">{assets.length}</span>
      </h2>

      <input
        className="panel__filter"
        type="search"
        placeholder="Filter…"
        value={filter}
        onChange={(event) => setFilter(event.target.value)}
      />

      {assets.length === 0 ? (
        <p className="panel__empty">
          Nothing in <code>image_dump/</code> yet. Drop textures in, then hit Refresh.
        </p>
      ) : (
        <div className="assets">
          {shown.map((asset) => (
            <div key={asset.baseName} className="assets__tile" title={asset.mapNames.join(', ')}>
              <button
                type="button"
                className="assets__add"
                disabled={!sheet}
                title={sheet ? 'Add to trim sheet' : 'No sheet to add to'}
                onClick={() => add(asset.baseName)}
              >
                +
              </button>
              {asset.primaryPath ? (
                <img className="assets__thumb" src={assetUrl(asset.primaryPath)} alt="" />
              ) : (
                <div className="assets__thumb assets__thumb--missing">?</div>
              )}
              <span className="assets__name">{asset.baseName}</span>
              <span className="assets__maps">{asset.mapNames.length} map{asset.mapNames.length === 1 ? '' : 's'}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
