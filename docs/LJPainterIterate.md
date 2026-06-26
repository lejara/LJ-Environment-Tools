# LJPainterIterate

Substance 3D Painter Python plugin for fast iteration on a project.

## What it does

- Adds an **LJ Iterate** dock widget and an **LJ Iterate** menu in Painter.
- **Iterate** button: saves the current `.spp`, copies it to `<base>_ver_N.spp` (auto-incrementing N), and snapshots the 3D viewport as the new tile's preview.
- Shows every sibling `_ver_N` project as a clickable tile in the dock — click a tile to open that iteration, click ↻ on the active tile to re-capture its preview.
- **Diagnose 3D View** menu action helps debug viewport-capture issues.

## Files

- [LJPainterIterate/__init__.py](../LJPainterIterate/__init__.py) — plugin entry points (`start_plugin` / `close_plugin`), event wiring.
- [LJPainterIterate/panel.py](../LJPainterIterate/panel.py) — dock UI, tile grid, iterate / capture handlers.
- [LJPainterIterate/project_iterate.py](../LJPainterIterate/project_iterate.py) — `_ver_N` naming and `.spp` duplication.
- [LJPainterIterate/tile_view.py](../LJPainterIterate/tile_view.py) — viewport detection, capture, and snapshot I/O.

## Install location

Symlink the [LJPainterIterate](../LJPainterIterate) folder into Painter's user Python plugin directory — see [symlinks.md](symlinks.md).
