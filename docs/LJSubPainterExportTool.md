# LJSubPainterExportTool

Substance 3D Painter **QML** plugin — one-click texture-map exporter.

> The folder name is `LJSubPainterExportTool`, and the dock labels itself "LJ Exportor".

## What it does

- Adds an **LJ Sub Painter Export Tool** dock widget in Painter.
- Lets you pick:
  - a **Presets Folder** that contains `.spexp` export presets (default points at the user's Blender Store export presets folder),
  - an **Export Template** (one of the discovered `.spexp` files),
  - a **Root Folder** for exports,
  - a **Filename** stored per project that is appended to every exported map.
- **Export** runs `alg.mapexport.exportDocumentMaps` against the chosen preset, writes PNGs into `<Root>/<Filename>/`, and renames each output to `<Filename>_<MapName>.png`.

## Files

- [LJSubPainterExportTool/main.qml](../LJSubPainterExportTool/main.qml) — `PainterPlugin` entry, registers the dock and wires project events.
- [LJSubPainterExportTool/panel.qml](../LJSubPainterExportTool/panel.qml) — the dock UI and the export logic.
- [LJSubPainterExportTool/settings.ini](../LJSubPainterExportTool/settings.ini) — default settings (presets folder, last export path, last preset).

## Install location

Symlink the [LJSubPainterExportTool](../LJSubPainterExportTool) folder into Painter's user **QML** plugin directory (not the Python one) — see [symlinks.md](symlinks.md).
