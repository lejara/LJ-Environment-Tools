# LJSubDesignerTools

Substance 3D Designer Python plugin — graph-level iteration with previews.

## What it does

- Adds an **LJ Tools** dock widget and an **LJ Tools** menu in Designer.
- **Iterate** on the current comp graph: duplicates it as `<base>_ver_N` inside the same package, copying nodes, connections, frames, comments, pins, and output flags.
- Tile grid of all sibling `_ver_N` graphs in the package — click a tile to open that graph in the editor.
- Extra menu actions: **Hello World** (sanity check), **Show Panel**, **Diagnose 3D View**.

## Files

- [LJSubDesignerTools/__init__.py](../LJSubDesignerTools/__init__.py) — plugin entry points (`initializeSDPlugin` / `uninitializeSDPlugin`), menu wiring.
- [LJSubDesignerTools/panel.py](../LJSubDesignerTools/panel.py) — dock UI, tile grid, iterate handler.
- [LJSubDesignerTools/graph_iterate.py](../LJSubDesignerTools/graph_iterate.py) — comp-graph duplication (nodes, connections, graph objects).
- [LJSubDesignerTools/tile_view.py](../LJSubDesignerTools/tile_view.py) — viewport capture and snapshot I/O.

## Install location

Symlink the [LJSubDesignerTools](../LJSubDesignerTools) folder into Designer's user plugin directory — see [symlinks.md](symlinks.md).
