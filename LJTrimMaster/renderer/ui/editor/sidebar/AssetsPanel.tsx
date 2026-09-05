import { useMemo, useState } from 'react'
import { useAssets, useAssetsStore } from '../../../state/assetsStore'
import { useProjectStore, useActiveSheet } from '../../../state/projectStore'
import { useSelectionStore } from '../../../state/selectionStore'
import { assetUrl } from '../../../services/bridge'

/**
 * Everything found in image_dump/ and its subfolders, as a thumbnail grid. The
 * + on a tile adds that asset to the active sheet.
 *
 * An asset from a subfolder has the folder in its base name (`stone/wall`).
 * The tile shows the leaf on the name line and the folder above it, since a
 * single ellipsized line would cut off the half that tells two tiles apart.
 *
 * Only the primary map (BaseColor by default) is listed — siblings like
 * Roughness and Normal are resolved at export time, so showing them here would
 * just be five rows per texture with no way to act on them.
 */
export function AssetsPanel(): JSX.Element {
  const assets = useAssets()
  const sheet = useActiveSheet()
  const addImage = useProjectStore((state) => state.addImage)
  const resizeToSource = useProjectStore((state) => state.resizeToSource)
  const recordSize = useAssetsStore((state) => state.recordSize)
  const sizeOf = useAssetsStore((state) => state.sizeOf)
  const select = useSelectionStore((state) => state.select)
  const [filter, setFilter] = useState('')

  const shown = useMemo(() => {
    const needle = filter.trim().toLowerCase()
    if (!needle) return assets
    // Matching the whole base name means typing a folder narrows to it.
    return assets.filter((asset) => asset.baseName.toLowerCase().includes(needle))
  }, [assets, filter])

  /**
   * A new trim defaults to the source image's own size, so it lands at 1:1
   * texel density instead of an arbitrary quarter-sheet.
   *
   * The size normally comes free from the thumbnail this panel has already
   * decoded. If it has not loaded yet the trim is added at the fallback size
   * and corrected once a probe resolves — a brief pop, but only on a click that
   * beat the thumbnail.
   */
  const add = (baseName: string): void => {
    const asset = assets.find((candidate) => candidate.baseName === baseName)
    const image = addImage(baseName, sizeOf(baseName))
    if (!image) return
    select(image.id)

    if (!sizeOf(baseName) && asset?.primaryPath) {
      const probe = new Image()
      probe.onload = () => {
        const size = { width: probe.naturalWidth, height: probe.naturalHeight }
        recordSize(baseName, size)
        resizeToSource(image.id, size)
      }
      probe.src = assetUrl(asset.primaryPath)
    }
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
          {shown.map((asset) => {
            const cut = asset.baseName.lastIndexOf('/')
            const folder = cut < 0 ? '' : asset.baseName.slice(0, cut)
            const leaf = cut < 0 ? asset.baseName : asset.baseName.slice(cut + 1)
            return (
            <div
              key={asset.baseName}
              className="assets__tile"
              title={`${asset.baseName}
${asset.mapNames.join(', ')}`}
            >
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
                <img
                  className="assets__thumb"
                  src={assetUrl(asset.primaryPath)}
                  alt=""
                  onLoad={(event) =>
                    recordSize(asset.baseName, {
                      width: event.currentTarget.naturalWidth,
                      height: event.currentTarget.naturalHeight
                    })
                  }
                />
              ) : (
                <div className="assets__thumb assets__thumb--missing">?</div>
              )}
              {folder && <span className="assets__folder">{folder}/</span>}
              <span className="assets__name">{leaf}</span>
              <span className="assets__maps">{asset.mapNames.length} map{asset.mapNames.length === 1 ? '' : 's'}</span>
            </div>
            )
          })}
        </div>
      )}
    </section>
  )
}
