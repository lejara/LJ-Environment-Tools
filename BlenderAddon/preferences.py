# pyright: reportInvalidTypeForm=none
import bpy
from bpy.app.handlers import persistent


_SHARED_PROP_NAMES = (
    "export_path",
    "export_static_mesh",
    "export_materials",
    "export_animations",
    "export_rig",
    "combine_into_single_fbx",
    "file_name",
)


def _shared_annotations():
    return {
        "export_path": bpy.props.StringProperty(
            name="Export Path",
            description="Folder where each selected object will be saved as <name>.fbx",
            subtype='DIR_PATH',
            default="//Exports/",
        ),
        "export_static_mesh": bpy.props.BoolProperty(
            name="Static Mesh",
            description="Include mesh geometry in the FBX",
            default=True,
        ),
        "export_materials": bpy.props.BoolProperty(
            name="Materials",
            description="Include material slots in the FBX. When off, material slots are temporarily stripped during export and restored afterwards",
            default=True,
        ),
        "export_animations": bpy.props.BoolProperty(
            name="Animations",
            description="Bake and include animation tracks in the FBX",
            default=False,
        ),
        "export_rig": bpy.props.BoolProperty(
            name="Rig",
            description="Include armature data in the FBX",
            default=False,
        ),
        "combine_into_single_fbx": bpy.props.BoolProperty(
            name="Combine Into Single FBX",
            description="When on, export all selected objects into one FBX file. When off, each object gets its own file",
            default=False,
        ),
        "file_name": bpy.props.StringProperty(
            name="File Name",
            description="Name of the FBX file (without extension). When empty, the selected object's name is used",
            default="",
        ),
    }


def get_global_prefs(context):
    return context.preferences.addons[__package__].preferences


def get_prefs(context):
    """Per-blend-file prefs. Seeding happens on file load / addon register, not here —
    Blender forbids writing to Scene data from draw()."""
    return context.scene.lj_export


def sync_to_global(context):
    """Push the current per-blend prefs back to the addon-level globals and persist them."""
    _copy(context.scene.lj_export, get_global_prefs(context))
    try:
        bpy.ops.wm.save_userpref()
    except Exception:
        pass


def _copy(src, dst):
    for name in _SHARED_PROP_NAMES:
        setattr(dst, name, getattr(src, name))


def _seed_scene(scene):
    local = scene.lj_export
    if local.initialized:
        return
    global_prefs = bpy.context.preferences.addons[__package__].preferences
    _copy(global_prefs, local)
    local.initialized = True


def seed_existing_scenes():
    # bpy.data is a _RestrictData proxy during addon enable on install —
    # accessing .scenes throws AttributeError. Bail; the load_post handler
    # (and our deferred timer in __init__) will seed when data is real.
    try:
        scenes = bpy.data.scenes
    except AttributeError:
        return
    for scene in scenes:
        _seed_scene(scene)


@persistent
def _on_load_post(_dummy):
    seed_existing_scenes()


def draw_shared(layout, target):
    layout.prop(target, "export_path")
    layout.prop(target, "file_name")

    col = layout.column(heading="Include")
    col.prop(target, "export_static_mesh")
    col.prop(target, "export_materials")
    col.prop(target, "export_animations")
    col.prop(target, "export_rig")

    col = layout.column(heading="Options")
    col.prop(target, "combine_into_single_fbx")


class LJEXPORT_AP_preferences(bpy.types.AddonPreferences):
    bl_idname = __package__
    __annotations__ = _shared_annotations()

    def draw(self, context):
        layout = self.layout
        layout.label(text="Defaults for new blend files. Per-file values live in View3D > N > LJ.")
        draw_shared(layout, self)


class LJEXPORT_PG_scene(bpy.types.PropertyGroup):
    __annotations__ = {
        **_shared_annotations(),
        "initialized": bpy.props.BoolProperty(default=False),
    }
