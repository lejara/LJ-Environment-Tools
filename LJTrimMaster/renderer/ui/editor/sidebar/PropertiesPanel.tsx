import { useCallback } from "react";
import { QuantityInput } from "../controls/QuantityInput";
import { useActiveSheet, useProjectStore } from "../../../state/projectStore";
import { useSelectedImageId } from "../../../state/selectionStore";
import { Crop } from "@models/Crop";
import type { TrimImage } from "@models/TrimImage";

/**
 * Transform + crop for the selected trim. The only place these values change.
 *
 * The model stores position/scale normalized 0-1 against the sheet; this panel
 * presents them as pixels, because that is what a texture artist thinks in.
 * Conversion happens here and nowhere else.
 */
export function PropertiesPanel(): JSX.Element {
  const sheet = useActiveSheet();
  const selectedId = useSelectedImageId();
  const editImage = useProjectStore((state) => state.editImage);

  const image = selectedId ? (sheet?.find(selectedId) ?? null) : null;

  const edit = useCallback(
    (mutate: (target: TrimImage) => void, isGestureStart: boolean) => {
      if (!image) return;
      editImage(image.id, mutate, isGestureStart);
    },
    [image, editImage],
  );

  if (!sheet || !image) {
    return (
      <section className="panel">
        <h2 className="panel__title">Properties</h2>
        <p className="panel__empty">Select a trim in the Outliner.</p>
      </section>
    );
  }

  const { width: sheetW, height: sheetH } = sheet.resolution;
  const { transform, crop } = image;

  return (
    <section className="panel">
      <h2 className="panel__title">Properties</h2>

      <div className="panel__group">
        <h3 className="panel__subtitle">Position</h3>
        <QuantityInput
          label="X"
          suffix="px"
          value={transform.position.x * sheetW}
          onChange={(px, start) =>
            edit((t) => void (t.transform.position.x = px / sheetW), start)
          }
        />
        <QuantityInput
          label="Y"
          suffix="px"
          value={transform.position.y * sheetH}
          onChange={(px, start) =>
            edit((t) => void (t.transform.position.y = px / sheetH), start)
          }
        />
      </div>

      <div className="panel__group">
        <h3 className="panel__subtitle">Scale</h3>
        <QuantityInput
          label="W"
          suffix="px"
          value={transform.scale.x * sheetW}
          onChange={(px, start) =>
            edit((t) => void (t.transform.scale.x = px / sheetW), start)
          }
        />
        <QuantityInput
          label="H"
          suffix="px"
          value={transform.scale.y * sheetH}
          onChange={(px, start) =>
            edit((t) => void (t.transform.scale.y = px / sheetH), start)
          }
        />
      </div>

      <div className="panel__group">
        <h3 className="panel__subtitle">Rotation</h3>
        <QuantityInput
          label="Angle"
          suffix="°"
          value={transform.rotation}
          precision={1}
          onChange={(deg, start) =>
            edit((t) => void (t.transform.rotation = deg), start)
          }
        />
        {transform.rotation !== 0 ? (
          <p className="panel__hint">
            Normal maps on this trim get their vectors rotated to match.
          </p>
        ) : null}
      </div>

      <div className="panel__group">
        <h3 className="panel__subtitle">Crop</h3>
        <QuantityInput
          label="X"
          suffix="%"
          value={crop.x * 100}
          precision={1}
          step={0.5}
          min={0}
          max={Crop.MAX * 100}
          onChange={(pct, start) =>
            edit((t) => void (t.crop.x = Crop.clamp(pct / 100)), start)
          }
        />
        <QuantityInput
          label="Y"
          suffix="%"
          value={crop.y * 100}
          precision={1}
          step={0.5}
          min={0}
          max={Crop.MAX * 100}
          onChange={(pct, start) =>
            edit((t) => void (t.crop.y = Crop.clamp(pct / 100)), start)
          }
        />
      </div>
    </section>
  );
}
