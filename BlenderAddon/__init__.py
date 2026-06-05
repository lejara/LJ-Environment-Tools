bl_info = {
    "name": "LJ Unity FBX Exporter",
    "author": "LJ",
    "version": (1, 0, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > LJ",
    "description": "Exports each selected object to its own FBX file using Unity-friendly settings.",
    "category": "Import-Export",
}

if "bpy" in locals():
    import importlib
    if "preferences" in locals():
        importlib.reload(preferences)
    if "export" in locals():
        importlib.reload(export)
    if "panel" in locals():
        importlib.reload(panel)

import bpy
from . import preferences
from . import export
from . import panel


classes = (
    preferences.LJEXPORT_AP_preferences,
    preferences.LJEXPORT_PG_scene,
    export.LJEXPORT_OT_export_selected,
    panel.LJEXPORT_PT_panel,
)


def _safe_unregister_class(cls):
    try:
        bpy.utils.unregister_class(cls)
    except (RuntimeError, ValueError):
        pass


def register():
    for cls in classes:
        # Drop any stale registration left over from a previous load
        # (happens when reinstalling without a full Blender restart).
        if getattr(cls, "is_registered", False):
            _safe_unregister_class(cls)
        bpy.utils.register_class(cls)
    bpy.types.Scene.lj_export = bpy.props.PointerProperty(type=preferences.LJEXPORT_PG_scene)
    if preferences._on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(preferences._on_load_post)
    preferences.seed_existing_scenes()


def unregister():
    if preferences._on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(preferences._on_load_post)
    if hasattr(bpy.types.Scene, "lj_export"):
        del bpy.types.Scene.lj_export
    for cls in reversed(classes):
        _safe_unregister_class(cls)


if __name__ == "__main__":
    register()
