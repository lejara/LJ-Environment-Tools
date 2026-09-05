# SPDX-License-Identifier: GPL-3.0-or-later
"""The Scene block that holds the project root, the master switch and the registry.

The project root and the registry live on the **Scene**, not in add-on
preferences, so they save with the ``.blend``. A ``.blend`` belongs to a project
the same way its assignments do; putting the root in a machine-wide preference
would mean opening a second project's file silently pointed the assignments at
the wrong sheets.

The accessors below are thin re-exports of ``assignment``'s. The implementation
lives there because ``settings`` must import ``assignment`` for its
PropertyGroup type, so the dependency can only run one way - see the note on
``assignment.scene_config``. Other modules use ``settings.snapshot(context)``
and friends so the call sites read the way they always have.
"""

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import PropertyGroup

from . import assignment, project


def _on_root_change(_self, context):
    project.CACHE.invalidate()
    project.ASSETS.invalidate()
    # A property update callback is not draw, so writing here is allowed - and
    # it has to happen somewhere, or the Create Material list would sit empty
    # until the user thought to press Refresh.
    rebuild_asset_list(context)


class LJTM_AssetEntry(PropertyGroup):
    """One image_dump asset, as a row in the Create Material list.

    Mirrors the Python-side scan into a Blender collection purely because
    ``template_list`` - the only widget that actually scrolls - cannot iterate a
    plain list. ``name`` is the tool's NORMALIZED asset name, which may match no
    file on disk exactly.
    """

    name: StringProperty(name="Asset")
    map_count: IntProperty(name="Maps", default=0)


class LJTM_Settings(PropertyGroup):
    project_root: StringProperty(
        name="Project",
        description=(
            "Folder containing projectData.json, image_dump/ and output/. "
            "Saved with this .blend"
        ),
        subtype='DIR_PATH',
        update=_on_root_change,
    )
    enabled: BoolProperty(
        name="Toggle Transform on Export",
        description=(
            "Master switch. When off, exports are byte-for-byte what Blender "
            "would normally write and nothing is synced"
        ),
        default=True,
    )
    #: The registry. This, not the mesh, is what the user edits.
    meshes: CollectionProperty(type=assignment.LJTM_MeshEntry)

    #: Mirror of the last image_dump scan. Rebuilt on Refresh and on a root
    #: change - never from draw.
    assets: CollectionProperty(type=LJTM_AssetEntry)
    active_asset: IntProperty(default=0)


#: One implementation, re-exported so call sites stay readable.
settings = assignment.scene_config
project_root = assignment.project_root
snapshot = assignment.project_snapshot
assets = assignment.project_assets

CACHE = project.CACHE
ASSETS = project.ASSETS


def is_enabled(context):
    config = settings(context)
    return bool(config and config.enabled)


def rebuild_asset_list(context, force=True):
    """Refill the Create Material list from a fresh image_dump scan.

    Called from Refresh and from the project-root update callback. **Never from
    draw** - this writes to the Scene, which is an ID (verified fact 15).
    """
    config = settings(context)
    if config is None:
        return 0
    scanned = assets(context, force=force)
    config.assets.clear()
    for base_name, maps in scanned:
        entry = config.assets.add()
        entry.name = base_name
        entry.map_count = len(maps)
    if config.active_asset >= len(config.assets):
        config.active_asset = max(len(config.assets) - 1, 0)
    return len(config.assets)


classes = (LJTM_AssetEntry, LJTM_Settings)


def register():
    bpy.types.Scene.lj_trim_master = PointerProperty(type=LJTM_Settings)


def unregister():
    del bpy.types.Scene.lj_trim_master
