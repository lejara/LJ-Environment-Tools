import { useState } from "react";
import { useActiveSheet, useProjectStore } from "../../../state/projectStore";
import {
  useSelectionStore,
  useSelectedImageId,
} from "../../../state/selectionStore";
import { useAssetsStore } from "../../../state/assetsStore";
import { assetUrl } from "../../../services/bridge";

/**
 * Everything on the active sheet, as a list. Click to select, drag to reorder,
 * ✕ to remove.
 *
 * LIST ORDER IS Z-ORDER: the top row draws last, i.e. on top. The underlying
 * `items` array is in draw order (index 0 = bottom), so this renders it
 * reversed and maps indices back on drop.
 */
export function Outliner(): JSX.Element {
  const sheet = useActiveSheet();
  const removeImage = useProjectStore((state) => state.removeImage);
  const reorder = useProjectStore((state) => state.reorder);
  const select = useSelectionStore((state) => state.select);
  const clear = useSelectionStore((state) => state.clear);
  const selectedId = useSelectedImageId();
  const findAsset = useAssetsStore((state) => state.find);

  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [overIndex, setOverIndex] = useState<number | null>(null);

  if (!sheet) {
    return (
      <section className="panel">
        <h2 className="panel__title">Outliner</h2>
        <p className="panel__empty">No sheet.</p>
      </section>
    );
  }

  const rows = sheet.displayOrder;
  /** Display row -> index into the draw-order array. */
  const toDrawIndex = (row: number): number => sheet.items.length - 1 - row;

  const handleDrop = (targetRow: number): void => {
    if (dragIndex === null) return;
    reorder(toDrawIndex(dragIndex), toDrawIndex(targetRow));
    setDragIndex(null);
    setOverIndex(null);
  };

  return (
    <section className="panel panel--grow">
      <h2 className="panel__title">
        Outliner
        <span className="panel__count">{rows.length}</span>
      </h2>

      {rows.length === 0 ? (
        <p className="panel__empty">Add an image from the Assets panel.</p>
      ) : (
        <ul className="outliner">
          {rows.map((item, row) => {
            const asset = findAsset(item.assetBaseName);
            const missing = !asset;
            return (
              <li
                key={item.id}
                className={[
                  "outliner__row",
                  item.id === selectedId ? "is-selected" : "",
                  overIndex === row ? "is-drop-target" : "",
                  missing ? "is-missing" : "",
                ]
                  .filter(Boolean)
                  .join(" ")}
                draggable
                onDragStart={() => setDragIndex(row)}
                onDragOver={(event) => {
                  event.preventDefault();
                  setOverIndex(row);
                }}
                onDragLeave={() =>
                  setOverIndex((current) => (current === row ? null : current))
                }
                onDrop={() => handleDrop(row)}
                onDragEnd={() => {
                  setDragIndex(null);
                  setOverIndex(null);
                }}
                onClick={() => select(item.id)}
              >
                <span className="outliner__grip" title="Drag to reorder">
                  ⠿
                </span>
                {asset?.primaryPath ? (
                  <img
                    className="outliner__thumb"
                    src={assetUrl(asset.primaryPath)}
                    alt=""
                  />
                ) : (
                  <span className="outliner__thumb outliner__thumb--missing">
                    ?
                  </span>
                )}
                <span
                  className="outliner__name"
                  title={
                    missing ? "Not found in image_dump/" : item.assetBaseName
                  }
                >
                  {item.assetBaseName}
                </span>
                <button
                  type="button"
                  className="outliner__remove"
                  title="Remove from sheet"
                  onClick={(event) => {
                    event.stopPropagation();
                    removeImage(item.id);
                    if (item.id === selectedId) clear();
                  }}
                >
                  ✕
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
