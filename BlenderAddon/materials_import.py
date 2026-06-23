# pyright: reportInvalidTypeForm=none
import os
import bpy
from bpy.app.handlers import persistent

from . import preferences as _prefs


_SHARED_PROP_NAMES = (
    "root_path",
    "tex_albedo",
    "tex_normal",
    "tex_roughness",
    "tex_metallic",
    "ignore_alpha",
)


def _shared_annotations():
    return {
        "root_path": bpy.props.StringProperty(
            name="Materials Root",
            description="Root folder containing material subfolders",
            subtype='DIR_PATH',
            default="",
        ),
        "tex_albedo": bpy.props.BoolProperty(
            name="Albedo",
            description="Import the first texture in the subfolder whose name contains 'Albedo'",
            default=True,
        ),
        "tex_normal": bpy.props.BoolProperty(
            name="Normal",
            description="Import the first texture in the subfolder whose name contains 'Normal'",
            default=True,
        ),
        "tex_roughness": bpy.props.BoolProperty(
            name="Roughness",
            description="Import the first texture in the subfolder whose name contains 'Roughness'",
            default=True,
        ),
        "tex_metallic": bpy.props.BoolProperty(
            name="Metallic",
            description="Import the first texture in the subfolder whose name contains 'Metallic'",
            default=True,
        ),
        "ignore_alpha": bpy.props.BoolProperty(
            name="Ignore Alpha",
            description="When on, the Albedo texture's Alpha output is left unconnected so the Principled BSDF Alpha input stays at 1.0 (white). When off, the texture's Alpha output is wired to Alpha for true transparency",
            default=True,
        ),
    }


# Names that appear in the user's textures, in slot order. Each entry is:
# (toggle_attr, search_needle, principled_socket, colorspace, via_normal_map, layout_y)
_TEXTURE_SLOTS = (
    ("tex_albedo", "Albedo", "Base Color", 'sRGB', False, 300.0),
    ("tex_normal", "Normal", "Normal", 'Non-Color', True, 100.0),
    ("tex_roughness", "Roughness", "Roughness", 'Non-Color', False, -100.0),
    ("tex_metallic", "Metallic", "Metallic", 'Non-Color', False, -300.0),
)


def get_prefs(context):
    """Per-blend-file prefs. Seeding from the addon-level globals happens on
    file load / register, not here — Blender forbids writing to Scene data
    from draw()."""
    return context.scene.lj_mat_import


def _global_prefs(context):
    return context.preferences.addons[__package__].preferences


def _copy(src, dst):
    for name in _SHARED_PROP_NAMES:
        setattr(dst, name, getattr(src, name))


def _seed_scene(scene):
    local = scene.lj_mat_import
    if local.initialized:
        return
    global_prefs = bpy.context.preferences.addons[__package__].preferences
    _copy(global_prefs, local)
    local.initialized = True


def seed_existing_scenes():
    try:
        scenes = bpy.data.scenes
    except AttributeError:
        return
    for scene in scenes:
        _seed_scene(scene)


@persistent
def _on_load_post(_dummy):
    seed_existing_scenes()


def sync_to_global(context):
    """Push the current per-blend prefs back to the addon-level globals and persist them."""
    _copy(context.scene.lj_mat_import, _global_prefs(context))
    try:
        bpy.ops.wm.save_userpref()
    except Exception:
        pass


def draw_addon_prefs(layout, target):
    layout.separator()
    layout.label(text="LJ Materials Import")
    layout.prop(target, "root_path")
    col = layout.column(heading="Include")
    for attr, _, _, _, _, _ in _TEXTURE_SLOTS:
        col.prop(target, attr)
    col = layout.column(heading="Options")
    col.prop(target, "ignore_alpha")


# Wire our globals into the single AddonPreferences class for this addon and
# add a section to its UI. Blender only allows one AddonPreferences per addon,
# so modules extend the existing one rather than declare a second.
_prefs.LJEXPORT_AP_preferences.__annotations__.update(_shared_annotations())
_prefs.addon_prefs_draw_extras["materials_import"] = draw_addon_prefs


def _resolve_root(prefs):
    raw = prefs.root_path
    if not raw:
        return ""
    return bpy.path.abspath(raw)


def _list_subfolders(root_abspath):
    if not root_abspath or not os.path.isdir(root_abspath):
        return []
    entries = []
    for name in os.listdir(root_abspath):
        full = os.path.join(root_abspath, name)
        if os.path.isdir(full):
            entries.append(name)
    entries.sort(key=str.lower)
    return entries


_TEXTURE_EXTS = {".png", ".jpg", ".jpeg", ".tga", ".tif", ".tiff", ".exr", ".bmp", ".webp"}


def _find_texture(folder, needle):
    """First file in `folder` whose name contains `needle` (case-insensitive)
    and has a known texture extension. Returns absolute path or None."""
    needle_low = needle.lower()
    try:
        names = sorted(os.listdir(folder), key=str.lower)
    except OSError:
        return None
    for name in names:
        if needle_low not in name.lower():
            continue
        if os.path.splitext(name)[1].lower() not in _TEXTURE_EXTS:
            continue
        full = os.path.join(folder, name)
        if os.path.isfile(full):
            return full
    return None


def _build_material(name, texture_paths, ignore_alpha=True):
    """Create or rebuild a Principled-BSDF material from the given map paths.
    `texture_paths` keys are search needles ("Albedo", "Normal", "Roughness",
    "Metallic"); missing keys are skipped. When `ignore_alpha` is True, the
    Albedo texture's Alpha output is left unconnected (BSDF Alpha stays at
    1.0); when False, it's wired to BSDF Alpha. Reuses the datablock if it
    already exists so existing assignments are preserved."""
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (400.0, 0.0)

    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (100.0, 0.0)
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

    for _, needle, socket, colorspace, via_normal_map, y in _TEXTURE_SLOTS:
        path = texture_paths.get(needle)
        if not path:
            continue
        img = bpy.data.images.load(path, check_existing=True)
        img.colorspace_settings.name = colorspace
        tex = nodes.new("ShaderNodeTexImage")
        tex.image = img
        tex.location = (-600.0, y)
        if via_normal_map:
            nmap = nodes.new("ShaderNodeNormalMap")
            nmap.location = (-300.0, y)
            links.new(tex.outputs["Color"], nmap.inputs["Color"])
            links.new(nmap.outputs["Normal"], bsdf.inputs[socket])
        else:
            links.new(tex.outputs["Color"], bsdf.inputs[socket])
        if needle == "Albedo" and not ignore_alpha:
            links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])

    return mat


class LJMATIMP_PG_scene(bpy.types.PropertyGroup):
    __annotations__ = {
        **_shared_annotations(),
        "initialized": bpy.props.BoolProperty(default=False),
    }


class LJMATIMP_OT_import_subfolder(bpy.types.Operator):
    bl_idname = "ljmatimp.import_subfolder"
    bl_label = "Import Material Subfolder"
    bl_options = {'REGISTER', 'UNDO'}

    subfolder: bpy.props.StringProperty()

    def execute(self, context):
        prefs = get_prefs(context)
        root = _resolve_root(prefs)
        folder = os.path.join(root, self.subfolder)
        if not os.path.isdir(folder):
            self.report({'ERROR'}, f"Subfolder not found: {folder}")
            return {'CANCELLED'}

        requested = [needle for attr, needle, *_ in _TEXTURE_SLOTS if getattr(prefs, attr)]
        if not requested:
            self.report({'WARNING'}, "No texture types enabled.")
            return {'CANCELLED'}

        found = {n: p for n in requested if (p := _find_texture(folder, n))}
        if not found:
            self.report({'WARNING'}, f"No matching textures in '{self.subfolder}'")
            return {'CANCELLED'}

        mat = _build_material(self.subfolder, found, ignore_alpha=prefs.ignore_alpha)

        missing = [n for n in requested if n not in found]
        msg = f"Material '{mat.name}' built with {', '.join(found.keys())}"
        if missing:
            msg += f" (missing: {', '.join(missing)})"
        self.report({'INFO'}, msg)

        sync_to_global(context)
        return {'FINISHED'}


class LJMATIMP_PT_panel(bpy.types.Panel):
    bl_idname = "LJMATIMP_PT_panel"
    bl_label = "LJ Materials Import"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "LJ"

    def draw(self, context):
        layout = self.layout
        prefs = get_prefs(context)

        layout.prop(prefs, "root_path")

        col = layout.column(heading="Include")
        for attr, *_ in _TEXTURE_SLOTS:
            col.prop(prefs, attr)

        col = layout.column(heading="Options")
        col.prop(prefs, "ignore_alpha")

        root = _resolve_root(prefs)
        if not prefs.root_path:
            layout.label(text="Set a root folder above.", icon='INFO')
            return
        if not os.path.isdir(root):
            layout.label(text="Folder not found.", icon='ERROR')
            return

        subfolders = _list_subfolders(root)
        if not subfolders:
            layout.label(text="No subfolders found.", icon='INFO')
            return

        layout.separator()
        layout.label(text=f"Subfolders ({len(subfolders)}):")
        col = layout.column(align=True)
        for name in subfolders:
            op = col.operator(
                LJMATIMP_OT_import_subfolder.bl_idname,
                text=name,
                icon='FILE_FOLDER',
            )
            op.subfolder = name
