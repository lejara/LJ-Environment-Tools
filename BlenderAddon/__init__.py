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
    if "materials_import" in locals():
        importlib.reload(materials_import)

import bpy
from . import preferences
from . import export
from . import panel
from . import materials_import


classes = (
    preferences.LJEXPORT_AP_preferences,
    preferences.LJEXPORT_PG_scene,
    export.LJEXPORT_OT_export_selected,
    panel.LJEXPORT_PT_panel,
    materials_import.LJMATIMP_PG_scene,
    materials_import.LJMATIMP_OT_import_subfolder,
    materials_import.LJMATIMP_PT_panel,
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
    bpy.types.Scene.lj_mat_import = bpy.props.PointerProperty(type=materials_import.LJMATIMP_PG_scene)
    if preferences._on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(preferences._on_load_post)
    if materials_import._on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(materials_import._on_load_post)

    # During install/enable Blender runs register() in a restricted context where
    # bpy.data.scenes is not yet accessible. Defer the seed to the next tick.
    def _deferred_seed():
        preferences.seed_existing_scenes()
        materials_import.seed_existing_scenes()
        return None
    bpy.app.timers.register(_deferred_seed, first_interval=0.0)


def unregister():
    if preferences._on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(preferences._on_load_post)
    if materials_import._on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(materials_import._on_load_post)
    if hasattr(bpy.types.Scene, "lj_export"):
        del bpy.types.Scene.lj_export
    if hasattr(bpy.types.Scene, "lj_mat_import"):
        del bpy.types.Scene.lj_mat_import
    for cls in reversed(classes):
        _safe_unregister_class(cls)


if __name__ == "__main__":
    register()
