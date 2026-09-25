# pyright: reportInvalidTypeForm=none
"""LJ Image Packer: per-scene recipes in the existing LJ sidebar."""

import os
import re

import bpy
import numpy as np
from bpy.app.handlers import persistent

from . import preferences as _prefs
from . import image_packer_core as core


_SHARED_PROP_NAMES = ('packer_output_path', 'packer_load_images')
# Blender 5.1 requires explicit opt-in for blend-relative path properties.
_PATH_OPTIONS = {'PATH_SUPPORTS_BLEND_RELATIVE'} if bpy.app.version >= (5, 1, 0) else set()


def _shared_annotations():
    return {
        'packer_output_path': bpy.props.StringProperty(
            name='Global Output Folder', subtype='DIR_PATH', default='', options=_PATH_OPTIONS,
            description='Used by presets with no output folder override'),
        'packer_load_images': bpy.props.BoolProperty(
            name='Load into Blender', default=False,
            description='Load exported PNGs or refresh images using the same file; keep them saved in this blend file'),
    }


def draw_addon_prefs(layout, target):
    layout.separator()
    layout.label(text='LJ Image Packer')
    for name in _SHARED_PROP_NAMES:
        layout.prop(target, name)


_prefs.LJEXPORT_AP_preferences.__annotations__.update(_shared_annotations())
_prefs.addon_prefs_draw_extras['image_packer'] = draw_addon_prefs


def seed_existing_scenes():
    try:
        scenes = bpy.data.scenes
        prefs = bpy.context.preferences.addons[__package__].preferences
    except (AttributeError, KeyError):
        return
    for scene in scenes:
        settings = scene.lj_image_packer
        if not settings.initialized:
            for name in _SHARED_PROP_NAMES:
                setattr(settings, name, getattr(prefs, name))
            settings.initialized = True


@persistent
def _on_load_post(_dummy):
    seed_existing_scenes()


def sync_to_global(context):
    prefs = context.preferences.addons.get(__package__)
    if prefs is None:
        return
    for name in _SHARED_PROP_NAMES:
        setattr(prefs.preferences, name, getattr(context.scene.lj_image_packer, name))
    try:
        bpy.ops.wm.save_userpref()
    except RuntimeError:
        pass


class LJPACK_PG_channel(bpy.types.PropertyGroup):
    image: bpy.props.PointerProperty(name='Image', type=bpy.types.Image,
        description='Existing Blender image; leave empty to use the constant')
    source: bpy.props.EnumProperty(name='Source', default='R', items=(
        ('R', 'R', 'Red channel'), ('G', 'G', 'Green channel'),
        ('B', 'B', 'Blue channel'), ('A', 'A', 'Alpha channel'),
        ('GRAY', 'RGB to Grayscale', 'Weighted luminance: 0.2126 R + 0.7152 G + 0.0722 B')))
    constant: bpy.props.FloatProperty(name='Constant', min=0, max=1, default=0,
        description='Value used when no source image is assigned')


class LJPACK_PG_preset(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty(name='Name', default='Packed Image',
        description='Output image name and PNG filename')
    output_path: bpy.props.StringProperty(name='Output Folder', subtype='DIR_PATH', options=_PATH_OPTIONS,
        description='Optional override; leave blank to use the global output folder')
    width: bpy.props.IntProperty(name='Width', default=1024, min=1, max=16384)
    height: bpy.props.IntProperty(name='Height', default=1024, min=1, max=16384)
    bit_depth: bpy.props.EnumProperty(name='Bit Depth', default='8', items=(
        ('8', '8-bit', '256 values per channel'),
        ('16', '16-bit', '65536 values per channel')))
    red: bpy.props.PointerProperty(type=LJPACK_PG_channel)
    green: bpy.props.PointerProperty(type=LJPACK_PG_channel)
    blue: bpy.props.PointerProperty(type=LJPACK_PG_channel)
    alpha: bpy.props.PointerProperty(type=LJPACK_PG_channel)


class LJPACK_PG_scene(bpy.types.PropertyGroup):
    __annotations__ = {
        **_shared_annotations(),
        'initialized': bpy.props.BoolProperty(default=False),
        'presets': bpy.props.CollectionProperty(type=LJPACK_PG_preset),
        'active_index': bpy.props.IntProperty(default=0),
    }


def channels(preset):
    return (preset.red, preset.green, preset.blue, preset.alpha)


def output_file(settings, preset):
    name = preset.name
    if (not name.strip() or name != name.strip() or name.endswith('.')
            or re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
            or name in ('.', '..')
            or re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])', name.split('.')[0])):
        raise ValueError(f'Invalid output name: {name!r}')
    folder = preset.output_path.strip() or settings.packer_output_path.strip()
    if not folder:
        raise ValueError(f'{name}: choose a preset or global output folder')
    if folder.startswith('//') and not bpy.data.filepath:
        raise ValueError(f'{name}: save the blend file before using a // relative folder')
    folder = bpy.path.abspath(folder)
    if not os.path.isabs(folder):
        raise ValueError(f'{name}: use an absolute folder or a // blend-relative folder')
    filename = name if name.lower().endswith('.png') else name + '.png'
    return os.path.normpath(os.path.join(folder, filename))


def _image_pixels(image):
    if image.source not in {'FILE', 'GENERATED'} or image.type in {'RENDER_RESULT', 'COMPOSITING'}:
        raise ValueError(f'{image.name}: use a still image (UDIMs, movies and render results are not supported)')
    width, height = image.size
    if not width or not height or len(image.pixels) != width * height * 4:
        raise ValueError(f'{image.name}: image pixels are unavailable')
    pixels = np.empty(width * height * 4, dtype=np.float32)
    image.pixels.foreach_get(pixels)
    return pixels.reshape(height, width, 4)


def pack_pixels(preset):
    output = np.empty((preset.height, preset.width, 4), dtype=np.float32)
    # Read each distinct source once per preset, without holding all sources in memory.
    slots = channels(preset)
    handled = set()
    for index, slot in enumerate(slots):
        if slot.image is None:
            output[..., index] = slot.constant
            continue
        key = slot.image.as_pointer()
        if key in handled:
            continue
        source = _image_pixels(slot.image)
        for target, other in enumerate(slots):
            if other.image == slot.image:
                values = core.extract_channel(source, other.source)
                output[..., target] = core.resize_channel(values, preset.width, preset.height)
        handled.add(key)
    return output


def _path_key(path):
    return os.path.normcase(os.path.realpath(path))


def load_output(path, name):
    key = _path_key(path)
    matches = [image for image in bpy.data.images
               if image.source == 'FILE' and image.filepath
               and _path_key(bpy.path.abspath(image.filepath, library=image.library)) == key
               and image.library is None]
    if not matches:
        image = bpy.data.images.load(path, check_existing=False)
        image.name = name
        matches = [image]
    for image in matches:
        # Treat alpha as an independent data channel, even when it is zero.
        image.alpha_mode = 'CHANNEL_PACKED'
        image.colorspace_settings.name = 'Non-Color'
        if image.packed_file:
            image.unpack(method='REMOVE')
        image.reload()
        image.use_fake_user = True


class LJPACK_OT_add(bpy.types.Operator):
    bl_idname = 'ljpack.add_preset'
    bl_label = 'Add Preset'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        settings = context.scene.lj_image_packer
        names = {preset.name for preset in settings.presets}
        name = 'Packed Image'
        number = 1
        while name in names:
            name = f'Packed Image {number:03d}'
            number += 1
        preset = settings.presets.add()
        preset.name = name
        settings.active_index = len(settings.presets) - 1
        settings.initialized = True
        return {'FINISHED'}


class LJPACK_OT_remove(bpy.types.Operator):
    bl_idname = 'ljpack.remove_preset'
    bl_label = 'Remove Preset'
    bl_description = 'Remove the selected preset; exported files are kept'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        settings = context.scene.lj_image_packer
        return 0 <= settings.active_index < len(settings.presets)

    def execute(self, context):
        settings = context.scene.lj_image_packer
        settings.presets.remove(settings.active_index)
        settings.active_index = max(0, min(settings.active_index, len(settings.presets) - 1))
        return {'FINISHED'}


class LJPACK_OT_export(bpy.types.Operator):
    bl_idname = 'ljpack.export'
    bl_label = 'Export All Presets'
    bl_description = 'Pack channels and save PNGs, replacing existing files with the same names'
    index: bpy.props.IntProperty(default=-1, options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return bool(context.scene.lj_image_packer.presets)

    def execute(self, context):
        settings = context.scene.lj_image_packer
        if self.index < -1 or self.index >= len(settings.presets):
            self.report({'ERROR'}, 'Preset no longer exists')
            return {'CANCELLED'}
        presets = list(settings.presets) if self.index == -1 else [settings.presets[self.index]]
        jobs = []
        try:
            # Check the whole batch before overwriting any output.
            seen = set()
            for preset in presets:
                path = output_file(settings, preset)
                key = _path_key(path)
                if key in seen:
                    raise ValueError(f'Multiple presets export to the same file: {path}')
                seen.add(key)
                for slot in channels(preset):
                    if slot.image is not None:
                        image = slot.image
                        if image.source not in {'FILE', 'GENERATED'} or not all(image.size):
                            raise ValueError(f'{preset.name}: {image.name} is not an available still image')
                jobs.append((preset, path))
        except ValueError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

        exported, errors = [], []
        wm = context.window_manager
        wm.progress_begin(0, len(jobs))
        try:
            for count, (preset, path) in enumerate(jobs, 1):
                try:
                    core.write_png(path, pack_pixels(preset), int(preset.bit_depth))
                    exported.append((path, preset.name))
                except (ValueError, OSError, RuntimeError, MemoryError) as exc:
                    errors.append(f'{preset.name}: {exc}')
                wm.progress_update(count)
            # Reload only after packing the whole batch, in case outputs are sources.
            if settings.packer_load_images:
                for path, name in exported:
                    try:
                        load_output(path, name)
                    except (ValueError, OSError, RuntimeError) as exc:
                        errors.append(f'{name}: PNG saved, but could not load into Blender: {exc}')
        finally:
            wm.progress_end()
        if exported:
            settings.initialized = True
            sync_to_global(context)
        if errors:
            for error in errors:
                self.report({'WARNING'} if exported else {'ERROR'}, error)
        if exported:
            self.report({'WARNING'} if errors else {'INFO'},
                        f'Exported {len(exported)}/{len(jobs)} PNGs' + ('; see reports for errors' if errors else ''))
        return {'FINISHED'} if exported else {'CANCELLED'}


class LJPACK_UL_presets(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.prop(item, 'name', text='', emboss=False, icon='IMAGE_DATA')
        op = row.operator('ljpack.export', text='', icon='EXPORT')
        op.index = index


class LJPACK_PT_panel(bpy.types.Panel):
    bl_idname = 'LJPACK_PT_panel'
    bl_label = 'LJ Image Packer'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'LJ'
    bl_order = 20

    def draw(self, context):
        layout = self.layout
        settings = context.scene.lj_image_packer
        layout.prop(settings, 'packer_output_path')
        layout.prop(settings, 'packer_load_images')
        row = layout.row()
        row.template_list('LJPACK_UL_presets', '', settings, 'presets', settings, 'active_index', rows=3)
        col = row.column(align=True)
        col.operator('ljpack.add_preset', text='', icon='ADD')
        col.operator('ljpack.remove_preset', text='', icon='REMOVE')
        if 0 <= settings.active_index < len(settings.presets):
            preset = settings.presets[settings.active_index]
            box = layout.box()
            box.prop(preset, 'name')
            box.prop(preset, 'output_path')
            if not preset.output_path:
                box.label(text='Using global output folder', icon='FILE_FOLDER')
            row = box.row(align=True)
            row.prop(preset, 'width')
            row.prop(preset, 'height')
            box.prop(preset, 'bit_depth', expand=True)
            for label, slot in zip('RGBA', channels(preset)):
                channel_box = box.box()
                row = channel_box.row(align=True)
                row.label(text=label)
                row.prop(slot, 'image', text='')
                if slot.image is None:
                    channel_box.prop(slot, 'constant', slider=True)
                else:
                    channel_box.prop(slot, 'source', text='Use')
        else:
            layout.label(text='Add a preset to assign channels.', icon='INFO')
        row = layout.row()
        row.scale_y = 1.5
        row.operator('ljpack.export', text='Export All Presets', icon='EXPORT').index = -1


classes = (LJPACK_PG_channel, LJPACK_PG_preset, LJPACK_PG_scene,
           LJPACK_OT_add, LJPACK_OT_remove, LJPACK_OT_export,
           LJPACK_UL_presets, LJPACK_PT_panel)
