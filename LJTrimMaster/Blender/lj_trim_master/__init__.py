# SPDX-License-Identifier: GPL-3.0-or-later
"""LJ Trim Master - Blender sync add-on.

Assigns material slots to trims authored in the LJ Trim Master tool, and
transforms the UVs into trim-sheet space **only inside the exported file**.

Two invariants hold everywhere in here:

**Read-only against the project.** ``projectData.json`` is never written; the
only thing written into the project is the sidecar link file, which the tool
treats as advisory. There is no registration handshake and no watcher process -
the panel re-reads the file when its mtime moves.

**The .blend's UVs are never modified.** The user's unwrap in source-image space
*is* the reference. The affine that maps it onto the sheet is derived fresh on
every export, so there is no accumulated state, nothing to invert, and no
"initial transform" to keep in sync. Modelling continues against the individual
texture at full resolution; the packed sheet exists only in the written file.

Module map
----------
``uv_transform``  the trim affine. Imports no bpy, so it is unit-testable.
``project``       projectData.json reader, mtime cache, recursive image_dump scan.
``assignment``    the scene registry, the mesh mirror, statuses, the pickers.
``settings``      the Scene block. Imports ``assignment``; never the reverse.
``export_hook``   the exporter wrap and per-slot masking.
``sidecar``       the object-to-trim link file the tool reads. Unconditional.
``material``      convenience material builder. Nothing depends on it.
``panel``         the single sidebar panel.

Import direction is one-way: ``project`` <- ``assignment`` <- ``settings`` <-
everything else. ``assignment`` reaches ``settings`` and ``sidecar`` only
through deferred imports inside functions.
"""

import bpy
from bpy.app.handlers import persistent
from bpy.props import PointerProperty

from . import (
    assignment,
    export_hook,
    material,
    panel,
    project,
    settings,
    sidecar,
)

#: PropertyGroups first - ``LJTM_Settings`` references them by type.
MODULES = (assignment, settings, sidecar, material, export_hook, panel)


@persistent
def _on_load(_dummy):
    """A different .blend means a different project and a different registry.

    **Mirror wins on load.** Any mesh carrying a serialized mirror but no
    registry row is adopted, which is how assignments survive append and link.
    """
    project.CACHE.invalidate()
    project.ASSETS.invalidate()
    context = bpy.context
    try:
        assignment.load_from_mirrors(context)
        settings.rebuild_asset_list(context)
    except Exception as err:  # never let a handler break opening a file
        print("[LJ Trim Master] load handler failed: %s" % err)


@persistent
def _on_save(_dummy):
    """Flush the registry to the meshes, and refresh the tool's link file.

    ``save_post`` is the catch-all: assignment changes write both already, but a
    freshly saved-as ``.blend`` gets a new sidecar name, and an unsaved one had
    nowhere to write at all until now.
    """
    context = bpy.context
    try:
        assignment.write_all_mirrors(context)
        sidecar.write_for_scene(context)
    except Exception as err:  # never let a handler break saving
        print("[LJ Trim Master] save handler failed: %s" % err)


def register():
    for module in MODULES:
        for cls in getattr(module, "classes", ()):
            bpy.utils.register_class(cls)

    settings.register()
    bpy.types.TOPBAR_MT_file_export.append(export_hook.file_export_menu)

    export_hook.attach_hooks()
    export_hook._retries_left = 20
    if not bpy.app.timers.is_registered(export_hook._attach_timer):
        bpy.app.timers.register(export_hook._attach_timer, first_interval=1.0)

    if _on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load)
    if _on_save not in bpy.app.handlers.save_post:
        bpy.app.handlers.save_post.append(_on_save)


def unregister():
    if _on_save in bpy.app.handlers.save_post:
        bpy.app.handlers.save_post.remove(_on_save)
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)

    export_hook.detach_hooks()
    if bpy.app.timers.is_registered(export_hook._attach_timer):
        bpy.app.timers.unregister(export_hook._attach_timer)

    bpy.types.TOPBAR_MT_file_export.remove(export_hook.file_export_menu)

    settings.unregister()
    for module in reversed(MODULES):
        for cls in reversed(getattr(module, "classes", ())):
            bpy.utils.unregister_class(cls)
