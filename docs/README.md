# LJ Environment Tools — Docs

High-level overviews of the DCC plugins that ship with this repo.

| Plugin | Host application | What it does |
| --- | --- | --- |
| [LJPainterIterate](LJPainterIterate.md) | Substance 3D Painter | One-click "Iterate" — duplicates the current `.spp` to `_ver_N`, snapshots the 3D viewport, and shows a tile grid of every iteration. |
| [LJSubDesignerTools](LJSubDesignerTools.md) | Substance 3D Designer | Same iterate-and-tile workflow at the comp-graph level — duplicates the current graph to `_ver_N` and tiles previews. |
| [LJSubPainterExportTool](LJSubPainterExportTool.md) | Substance 3D Painter | QML dock that exports all texture maps for the current project using a chosen `.spexp` preset, renaming outputs to `<filename>_<map>.png`. |

## Installing — symlinks / junctions

These plugins live in this repo but Painter and Designer only load from their own user plugin folders. Use a **directory junction** (or symlink) so edits in the repo are picked up live by the host app — no copy step.

See **[symlinks.md](symlinks.md)** for the exact commands.
