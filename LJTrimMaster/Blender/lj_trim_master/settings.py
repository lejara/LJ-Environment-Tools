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
    project.OUTPUTS.invalidate()
    # A property update callback is not draw, so writing here is allowed - and
    # it has to happen somewhere, or the Create Material list would sit empty
    # until the user thought to press Refresh.
    rebuild_asset_list(context)


#: A row is either an exported trim sheet or an image_dump asset. They are one
#: list rather than two because they are the same choice - "what do I want this
#: material to show?" - and because a single `template_list` is the only widget
#: in Blender that scrolls.
KIND_SHEET = 'SHEET'
KIND_ASSET = 'ASSET'


class LJTM_AssetEntry(PropertyGroup):
    """One row in the On-Click Material list.

    Mirrors the Python-side scans into a Blender collection purely because
    ``template_list`` cannot iterate a plain list.

    For an asset, ``name`` is the tool's NORMALIZED asset name, which may match
    no file on disk exactly. For a sheet it is the sheet's name as the tool
    shows it - which is not necessarily its filename either, since the tool
    sanitizes on the way to disk. Neither is ever presented as a path.
    """

    name: StringProperty(name="Name")
    map_count: IntProperty(name="Maps", default=0)
    kind: StringProperty(name="Kind", default=KIND_ASSET)
    #: Sheets resolve by id, never by name: two sheets may share a name, and the
    #: tool lets the user rename one at any time.
    sheet_id: StringProperty(name="Trim")


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
    #: Which mesh the slot editor under the list is editing. Maintained by the
    #: add/remove operators - never from draw.
    active_mesh: IntProperty(default=0)
    mesh_search: StringProperty(
        name="Search",
        description=(
            "Show only meshes whose name contains this. While it is set the "
            "list keeps its registry order - selected meshes are not floated to "
            "the top, so a row cannot move out from under the pointer as the "
            "viewport selection changes"
        ),
        # Filter as the user types. Without this the list would not narrow until
        # Enter, which reads as the search being broken.
        options={'TEXTEDIT_UPDATE'},
    )

    #: Mirror of the last image_dump scan. Rebuilt on Refresh and on a root
    #: change - never from draw.
    assets: CollectionProperty(type=LJTM_AssetEntry)
    active_asset: IntProperty(default=0)


#: One implementation, re-exported so call sites stay readable.
settings = assignment.scene_config
project_root = assignment.project_root
snapshot = assignment.project_snapshot
assets = assignment.project_assets
outputs = assignment.project_outputs

CACHE = project.CACHE
ASSETS = project.ASSETS
OUTPUTS = project.OUTPUTS


def is_enabled(context):
    config = settings(context)
    return bool(config and config.enabled)


def rebuild_asset_list(context, force=True):
    """Refill the On-Click Material list: every trim sheet, then every asset.

    Called from Refresh and from the project-root update callback. **Never from
    draw** - this writes to the Scene, which is an ID (verified fact 15), and it
    walks the disk twice.

    Sheets come first because they are the finished thing: a sheet material
    shows what the model will actually look like in-engine, where an asset
    material shows the source texture you unwrapped against. A sheet with
    nothing exported yet is still listed, with a map count of zero, so the
    answer to "why is my sheet not here?" is never "because you have not
    pressed Build" - it says so on the row.
    """
    config = settings(context)
    if config is None:
        return 0
    config.assets.clear()

    for sheet, maps in outputs(context, force=force):
        entry = config.assets.add()
        entry.name = sheet.name
        entry.map_count = len(maps)
        entry.kind = KIND_SHEET
        entry.sheet_id = sheet.id

    for base_name, maps in assets(context, force=force):
        entry = config.assets.add()
        entry.name = base_name
        entry.map_count = len(maps)
        entry.kind = KIND_ASSET

    if config.active_asset >= len(config.assets):
        config.active_asset = max(len(config.assets) - 1, 0)
    return len(config.assets)


classes = (LJTM_AssetEntry, LJTM_Settings)


def register():
    bpy.types.Scene.lj_trim_master = PointerProperty(type=LJTM_Settings)


def unregister():
    del bpy.types.Scene.lj_trim_master
