import { useActiveSheet } from '../../state/projectStore'
import { useAssetsStore } from '../../state/assetsStore'
import { useSelectedImageId } from '../../state/selectionStore'
import { assetUrl } from '../../services/bridge'
import type { TrimImage } from '@models/TrimImage'

/**
 * Preview of the active sheet, plus an outline on the selected trim.
 *
 * Deliberately NOT interactive: no drag, no click-to-select. Selection happens
 * in the Outliner and every transform edit happens in the Properties panel, so
 * there is exactly one way to change a value.
 *
 * Items render in array order, so the last item paints on top — matching the
 * Outliner, which lists the same array reversed.
 *
 * Hidden trims are not drawn, because hiding means "not on the sheet" rather
 * than "not in the preview" — the exporter and the Blender addon skip them too.
 */
export function Viewport(): JSX.Element {
  const sheet = useActiveSheet()
  const findAsset = useAssetsStore((state) => state.find)
  const selectedId = useSelectedImageId()

  if (!sheet) {
    return (
      <main className="viewport viewport--empty">
        <p>No trim sheet. Use the + in the tab bar to make one.</p>
      </main>
    )
  }

  return (
    <main className="viewport">
      <div className="viewport__stage">
        <div
          className="viewport__sheet"
          style={{ aspectRatio: `${sheet.resolution.width} / ${sheet.resolution.height}` }}
        >
          {sheet.visibleItems.map((item) => (
            <TrimLayer
              key={item.id}
              item={item}
              src={findAsset(item.assetBaseName)?.primaryPath}
              selected={item.id === selectedId}
            />
          ))}
        </div>
      </div>
      <div className="viewport__caption">
        {sheet.name} — {sheet.resolution.width} × {sheet.resolution.height}
      </div>
    </main>
  )
}

interface TrimLayerProps {
  item: TrimImage
  src: string | undefined
  selected: boolean
}

/**
 * One placed trim. Transform values are normalized 0-1 against the sheet, so
 * they map straight onto CSS percentages and the preview stays correct at any
 * on-screen size.
 */
function TrimLayer({ item, src, selected }: TrimLayerProps): JSX.Element {
  const { position, scale, rotation } = item.transform
  const width = Math.abs(scale.x)
  const height = Math.abs(scale.y)

  // A negative scale axis mirrors rather than inverting the box.
  const flipX = scale.x < 0 ? -1 : 1
  const flipY = scale.y < 0 ? -1 : 1

  const keptWidth = Math.max(item.crop.keptWidth, 0.001)
  const keptHeight = Math.max(item.crop.keptHeight, 0.001)

  return (
    <div
      className={`trim ${selected ? 'trim--selected' : ''}`}
      style={{
        left: `${(position.x - width / 2) * 100}%`,
        top: `${(position.y - height / 2) * 100}%`,
        width: `${width * 100}%`,
        height: `${height * 100}%`,
        // Negated: Transform.rotation is counter-clockwise-positive, CSS
        // rotate() is clockwise-positive. TrimBlitter negates identically, so
        // the preview and the exported file agree.
        transform: `rotate(${-rotation}deg) scale(${flipX}, ${flipY})`
      }}
    >
      {src ? (
        // Crop is a symmetric inset: blow the image up by 1/kept and shift it
        // back by the inset, so the kept middle exactly fills the box.
        <img
          className="trim__image"
          src={assetUrl(src)}
          alt=""
          draggable={false}
          style={{
            width: `${(1 / keptWidth) * 100}%`,
            height: `${(1 / keptHeight) * 100}%`,
            left: `${-(item.crop.x / keptWidth) * 100}%`,
            top: `${-(item.crop.y / keptHeight) * 100}%`
          }}
        />
      ) : (
        <div className="trim__missing" title={`${item.assetBaseName} is not in image_dump/`}>
          {item.assetBaseName}
        </div>
      )}
    </div>
  )
}
