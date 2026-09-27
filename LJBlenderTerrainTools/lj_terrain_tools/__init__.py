bl_info = {'name': 'LJ Terrain Tools', 'author': 'LJ', 'version': (0, 1, 0),
           'blender': (5, 1, 0), 'location': 'View3D > Sidebar > LJ Terrain',
           'description': 'Native texture painting with four masks and an internal RGBA splat',
           'category': 'Paint'}

import importlib
import sys
import time
import bpy
import numpy as np

# Re-enabling after an update reloads this file but reuses cached submodules, so a fresh
# __init__ can call into stale code. math_core is bound below, so it has to refresh first;
# nodes imports back into this package, so it is only safe to refresh from register().
_cached = sys.modules.get(__name__ + '.math_core')
if _cached:
    importlib.reload(_cached)
from bpy.app.handlers import persistent
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatProperty,
                       FloatVectorProperty, IntProperty, PointerProperty, StringProperty)
from .math_core import pack

_pending = set()
_dirty = set()
_raw = {}
_signatures = {}
_observers = set()
_fill_timers = set()
_mask_prompts = set()
_enabled = False
_busy = False
_generation = 0
SETTINGS = '.LJ Terrain File Settings'


def file_settings():
    # A single ID datablock is shared by all scenes and saved in the blend.
    value = bpy.data.texts.get(SETTINGS)
    if value is None:
        value = bpy.data.texts.new(SETTINGS)
        value.use_fake_user = True
    return value


def normalized():
    value = bpy.data.texts.get(SETTINGS)
    return bool(value and value.get('normalize', False))


def set_normalized(self, value):
    file_settings()['normalize'] = bool(value)
    for obj in terrains():
        queue(obj)
        if obj.lj_terrain.preview:
            node = obj.lj_terrain.preview.node_tree.nodes.get('Normalize RGBA')
            if node:
                node.outputs[0].default_value = float(value)


def terrains():
    return [o for o in bpy.data.objects if o.type == 'MESH' and o.lj_terrain.ready]


def queue(obj):
    if obj and obj.lj_terrain.ready:
        obj.lj_terrain.status = 'Pending'
        _pending.add(obj.name)


def layer_signatures(obj):
    from .nodes import signature
    return tuple(signature(l.material) if l.material else None for l in obj.lj_terrain.layers)


def rebuild(obj):
    from .nodes import build
    _signatures[obj.name] = layer_signatures(obj)
    try:
        build(obj)
    except Exception as exc:
        obj.lj_terrain.preview_status = 'Preview error: ' + str(exc)


def changed(self, context):
    if _busy:
        return
    obj = self.id_data
    if isinstance(obj, bpy.types.Object) and obj.lj_terrain.ready:
        obj.lj_terrain.status = 'Settings changed: refresh source preview'
        queue(obj)
        rebuild(obj)


def source_changed(self, context):
    if _busy:
        return
    obj = self.id_data
    if not isinstance(obj, bpy.types.Object) or not obj.lj_terrain.ready:
        return
    t = obj.lj_terrain
    index = next((i for i, l in enumerate(t.layers) if l.as_pointer() == self.as_pointer()), -1)
    if 0 < index <= len(t.masks):
        channel = index - 1
        if self.material:
            ensure_mask(obj, channel)
        elif t.masks[channel].image and not bpy.app.background:
            prompt_unused(obj.name, channel)
    rebuild(obj)


@persistent
def source_edited(scene, depsgraph):
    # Edits inside a source material raise no property callback. Flag here and rebuild on
    # the timer: writing node graphs from a depsgraph handler is unsafe. The preview and its
    # layer groups are generated, never sources, so a rebuild cannot flag itself again.
    if not _enabled or _busy:
        return
    touched = {u.id.original for u in depsgraph.updates if isinstance(u.id, bpy.types.Material)}
    if not touched:
        return
    for obj in terrains():
        if not touched.intersection(l.material for l in obj.lj_terrain.layers if l.material):
            continue
        current = layer_signatures(obj)
        if _signatures.get(obj.name) != current:
            _signatures[obj.name] = current
            _dirty.add(obj.name)


class LJLayer(bpy.types.PropertyGroup):
    show: BoolProperty(name='Expand Layer')
    material: PointerProperty(type=bpy.types.Material, update=source_changed)
    mode: EnumProperty(name='Blend', items=[('ALPHA', 'Alpha Blend', ''), ('HEIGHT', 'Height Blend', ''), ('MULTIPLY', 'Multiply 2X (shader branch)', '')], default='ALPHA', update=changed)
    strength: FloatProperty(name='Layer Strength', default=1, min=0, max=2, update=changed)
    albedo_strength: FloatProperty(name='Albedo Strength', default=1, min=0, max=2, update=changed)
    normal_strength: FloatProperty(name='Normal Strength', default=1, min=0, max=2, update=changed)
    tint: FloatVectorProperty(name='Tint', size=3, subtype='COLOR', default=(1, 1, 1), min=0, max=1, update=changed)
    uv: StringProperty(name='Material UV', update=changed)
    scale: FloatVectorProperty(name='UV Scale', size=2, default=(1, 1), update=changed)
    offset: FloatVectorProperty(name='UV Offset', size=2, update=changed)
    height_source: EnumProperty(name='Height Source', items=[('CONSTANT', 'Constant', ''), ('ALPHA', 'Albedo Alpha', ''), ('IMAGE', 'Separate Image', '')], update=changed)
    height_image: PointerProperty(type=bpy.types.Image, update=changed)
    height_channel: EnumProperty(name='Height Channel', items=[(c, c, '') for c in 'RGBA'], update=changed)
    height: FloatProperty(name='Height', default=.5, min=0, max=1, update=changed)
    height_remap: FloatVectorProperty(name='Height Remap', size=2, default=(0, 1), update=changed)
    contrast: FloatProperty(name='Height Contrast', default=.5, min=.01, max=.99, update=changed)
    alpha_mask: BoolProperty(name='Multiply mask by albedo alpha', default=True, update=changed)
    smooth_remap: FloatVectorProperty(name='Smoothness Remap', size=2, default=(0, 1), update=changed)
    metal_remap: FloatVectorProperty(name='Metallic Remap', size=2, default=(0, 1), update=changed)
    smooth_strength: FloatProperty(name='Multiply Surface Strength', default=1, min=0, max=1, update=changed)
    flip_green: BoolProperty(name='Flip Normal Green', update=changed)
    curve: BoolProperty(name='Curve Mask Weight', update=changed)
    curve_width: FloatProperty(name='Weight Curve Width', default=.5, min=.001, max=.5, update=changed)


class LJMask(bpy.types.PropertyGroup):
    image: PointerProperty(type=bpy.types.Image)


class LJTerrain(bpy.types.PropertyGroup):
    ready: BoolProperty()
    origin_saved: BoolProperty()
    origin_slots: IntProperty()
    origin_active: IntProperty()
    origin_index: IntProperty()
    paint_uv: StringProperty(name='Paint UV', update=changed)
    image_name: StringProperty(name='Image Name', default='Terrain Splat')
    resolution: EnumProperty(name='Resolution', items=[(str(n), str(n), '') for n in (1024, 2048, 4096)], default='2048')
    adopt: PointerProperty(name='Adopt Existing RGBA', type=bpy.types.Image)
    combined: PointerProperty(name='Combined RGBA', type=bpy.types.Image)
    preview: PointerProperty(type=bpy.types.Material)
    layers: CollectionProperty(type=LJLayer)
    masks: CollectionProperty(type=LJMask)
    active_mask: EnumProperty(name='Paint Channel', items=[(str(i), c, '') for i, c in enumerate('RGBA')], update=changed)
    mask_scale: FloatVectorProperty(name='Mask UV Scale', size=2, default=(1, 1), update=changed)
    mask_offset: FloatVectorProperty(name='Mask UV Offset', size=2, update=changed)
    display: EnumProperty(name='Preview', items=[('MATERIAL', 'Material', ''), ('MASK', 'Selected Raw Mask', ''), ('ALBEDO', 'Unlit Albedo', ''), ('HEIGHT', 'Accumulated Height', ''), ('SMOOTH', 'Smoothness', ''), ('METAL', 'Metallic', ''), ('NORMAL', 'Tangent Normal (encoded)', '')], update=changed)
    status: StringProperty(default='Not configured')
    preview_status: StringProperty(default='Not configured')
    sync_ms: FloatProperty()


def pixels(image):
    a = np.empty(image.size[0] * image.size[1] * image.channels, dtype=np.float32)
    image.pixels.foreach_get(a)
    return a.reshape(-1, 4)


def write(image, a):
    image.pixels.foreach_set(np.ascontiguousarray(a, dtype=np.float32).ravel())
    image.update()


def new_image(name, width, height):
    image = bpy.data.images.new(name, width, height, alpha=True, float_buffer=True)
    image.colorspace_settings.name = 'Non-Color'
    image.alpha_mode = 'CHANNEL_PACKED'
    image.use_fake_user = True
    return image


def ensure_mask(obj, index):
    """Give a channel a paintable mask, seeded from the RGBA so adopted paint is never lost."""
    t = obj.lj_terrain
    entry = t.masks[index]
    if entry.image:
        return entry.image
    size = tuple(t.combined.size)
    entry.image = new_image(t.image_name + " Working " + "RGBA"[index], *size)
    a = np.ones((size[0] * size[1], 4), np.float32)
    a[:, :3] = pixels(t.combined)[:, index:index + 1]
    write(entry.image, a)
    _raw.pop(obj.name, None)
    return entry.image


def canvas(obj):
    t = obj.lj_terrain
    index = int(t.active_mask)
    image = t.masks[index].image if len(t.masks) > index else None
    if not image:
        raise ValueError("Channel %s has no mask; assign a material to layer %d first"
                         % ("RGBA"[index], index + 1))
    return image


def prompt_unused(name, channel):
    """A property update cannot open a dialog, so hand it to the timer queue."""
    def ask():
        _mask_prompts.discard(ask)
        obj = bpy.data.objects.get(name)
        if (_enabled and obj and obj.lj_terrain.ready and len(obj.lj_terrain.masks) > channel
                and obj.lj_terrain.masks[channel].image
                and not obj.lj_terrain.layers[channel + 1].material):
            bpy.ops.lj_terrain.mask_prompt("INVOKE_DEFAULT", target=name, channel=channel)
        return None
    _mask_prompts.add(ask)
    bpy.app.timers.register(ask, first_interval=.05)


def sync(obj, persist=False, incremental=False):
    t = obj.lj_terrain
    start = time.perf_counter()
    try:
        if not t.combined or len(t.masks) != 4:
            raise ValueError('Missing images; restore or recreate setup')
        size = tuple(t.combined.size)
        for entry in t.masks:
            if entry.image and tuple(entry.image.size) != size:
                raise ValueError('Working mask dimensions do not match combined image')
        raw = _raw.get(obj.name)
        if not incremental or raw is None or raw.shape[0] != size[0] * size[1]:
            raw = np.empty((size[0] * size[1], 4), dtype=np.float32)
            channels = range(4)
        else:
            # Painting only ever writes the selected channel; re-reading the other three
            # costs three full image reads per stroke and can never change the result.
            channels = (int(t.active_mask),)
        for i in channels:
            image = t.masks[i].image
            raw[:, i] = pixels(image)[:, 0] if image else 0
        _raw[obj.name] = raw
        write(t.combined, pack(raw, normalized()))
        if persist:
            for image in [t.combined] + [m.image for m in t.masks]:
                if image:
                    image.pack()
        t.sync_ms = (time.perf_counter() - start) * 1000
        t.status = 'Current'
        _pending.discard(obj.name)
    except Exception as exc:
        _raw.pop(obj.name, None)
        t.status = 'Sync failed: ' + str(exc)
        _pending.discard(obj.name)
        raise


def reload_masks(obj):
    t = obj.lj_terrain
    raw = pixels(t.combined)
    for i, m in enumerate(t.masks):
        if not m.image:
            # Nothing to reload into unless the RGBA is actually carrying that channel.
            if raw[:, i].any():
                ensure_mask(obj, i)
            continue
        a = np.ones_like(raw)
        a[:, :3] = raw[:, i:i+1]
        write(m.image, a)
    sync(obj)


def native_fill(context, obj, value):
    """Use Blender's image undo tiles, including when launched from the sidebar."""
    if bpy.app.background:
        raise ValueError('Native Fill/Clear requires an interactive Blender window')
    area = context.area
    window = context.window
    old_type = area.type
    old_ui_type = area.ui_type
    image = canvas(obj)
    old_image = area.spaces.active.image if old_type == 'IMAGE_EDITOR' else None
    if old_type != 'IMAGE_EDITOR':
        area.type = 'IMAGE_EDITOR'
    area.spaces.active.mode = 'PAINT'
    area.spaces.active.image = image
    def apply():
        _fill_timers.discard(apply)
        if not _enabled:
            return None
        paint = window.scene.tool_settings.image_paint
        reference = paint.brush_asset_reference
        previous = {k: getattr(reference, k) for k in ('asset_library_type', 'asset_library_identifier', 'relative_asset_identifier')} if reference else None
        ups = paint.unified_paint_settings
        saved_ups = (ups.use_unified_color, ups.use_unified_strength)
        brush = None
        saved_brush = None
        try:
            region = next(r for r in area.regions if r.type == 'WINDOW')
            with bpy.context.temp_override(window=window, area=area, region=region):
                bpy.ops.wm.tool_set_by_id(name='builtin.brush')
                bpy.ops.brush.asset_activate(asset_library_type='ESSENTIALS', relative_asset_identifier='brushes/essentials_brushes-mesh_texture.blend/Brush/Fill')
                brush = paint.brush
                saved_brush = (tuple(brush.color), brush.strength, brush.blend, brush.fill_threshold, brush.color_type)
                brush.color = (value, value, value)
                brush.strength = 1
                brush.blend = 'MIX'
                brush.fill_threshold = 1
                brush.color_type = 'COLOR'
                ups.use_unified_color = False
                ups.use_unified_strength = False
                x, y = region.width/2, region.height/2
                stroke = [dict(name='LJ native fill', mouse=(x,y), mouse_event=(x,y), pressure=1, size=50, time=0, is_start=True, x_tilt=0, y_tilt=0, location=(0,0,0))]
                stroke.append(dict(stroke[0], is_start=False, time=.1))
                bpy.ops.paint.image_paint('EXEC_DEFAULT', True, stroke=stroke)
                sync(obj)
        except Exception as exc:
            obj.lj_terrain.status = 'Fill failed: ' + str(exc)
        finally:
            if brush and saved_brush:
                brush.color, brush.strength, brush.blend, brush.fill_threshold, brush.color_type = saved_brush
            ups.use_unified_color, ups.use_unified_strength = saved_ups
            if previous:
                with bpy.context.temp_override(window=window, area=area):
                    bpy.ops.brush.asset_activate(**previous)
            if old_type == 'IMAGE_EDITOR':
                area.spaces.active.image = old_image
            else:
                area.type = old_type
                area.ui_type = old_ui_type
        return None
    if old_type == 'IMAGE_EDITOR':
        apply()
    else:
        # Let Blender initialize the temporary editor before invoking native paint.
        obj.lj_terrain.status = 'Pending native fill'
        _fill_timers.add(apply)
        bpy.app.timers.register(apply, first_interval=.15)


def remember(obj):
    """Record the mesh once, before this addon first touches it, so reset can put it back."""
    t = obj.lj_terrain
    if t.origin_saved:
        return
    t.origin_saved = True
    t.origin_slots = len(obj.data.materials)
    t.origin_active = obj.active_material_index
    faces = np.empty(len(obj.data.polygons), np.int32)
    obj.data.polygons.foreach_get('material_index', faces)
    t.origin_index = int(faces[0]) if len(faces) else 0
    if len(faces) and faces.min() != faces.max():
        # Only a genuinely multi-material mesh pays to store the whole assignment.
        t['origin_faces'] = faces.tolist()


def reset(obj, delete_images=False):
    """Undo the setup: restore slots and face assignment, drop generated shading.

    Painted masks are kept unless the caller asks for them; they are the user's work.
    """
    t = obj.lj_terrain
    mesh = obj.data
    preview = t.preview
    groups = [g for g in (bpy.data.node_groups.get(preview.get(f'layer_{i}') or '')
                          for i in range(len(t.layers))) if g] if preview else []
    painted = [i for i in [t.combined] + [m.image for m in t.masks] if i]
    names = [i.name for i in painted]
    faces = t.get('origin_faces')
    index = t.origin_index if t.origin_saved else 0
    active = t.origin_active if t.origin_saved else 0
    if t.origin_saved:
        keep = t.origin_slots
    else:
        # Set up before this was recorded: the appended preview is all we can identify.
        keep = len(mesh.materials) - (1 if preview and preview.name in mesh.materials else 0)
    for i in range(len(mesh.materials) - 1, max(keep, 0) - 1, -1):
        mesh.materials.pop(index=i)
    last = max(len(mesh.materials) - 1, 0)
    if faces is not None and len(faces) == len(mesh.polygons):
        mesh.polygons.foreach_set('material_index', np.array(faces, np.int32))
    else:
        for face in mesh.polygons:
            face.material_index = min(index, last)
    obj.active_material_index = min(active, last)
    _pending.discard(obj.name)
    _dirty.discard(obj.name)
    _raw.pop(obj.name, None)
    _signatures.pop(obj.name, None)
    # Drop the pointers first; the property group itself counts as a user of what it holds.
    obj.property_unset('lj_terrain')
    # The preview material holds the layer groups, so it has to go first for them to free up.
    if preview and not preview.users:
        bpy.data.materials.remove(preview)
    for group in groups:
        if not group.users:
            bpy.data.node_groups.remove(group)
    if delete_images:
        for image in painted:
            # Only when this addon's fake user is the last reference; never a shared image.
            if image.users <= bool(image.use_fake_user):
                bpy.data.images.remove(image)
    mesh.update()
    # Names, not datablocks: a removed image's StructRNA is dead the moment it is freed.
    return [n for n in names if n in bpy.data.images]


def setup(obj):
    global _busy
    from .nodes import validate, build, starter
    t = obj.lj_terrain
    if not obj.data.uv_layers:
        raise ValueError('Mesh needs a UV map before setup')
    if not t.paint_uv:
        t.paint_uv = obj.data.uv_layers.active.name
    if t.paint_uv not in obj.data.uv_layers:
        raise ValueError('Paint UV map does not exist')
    remember(obj)
    _busy = True
    try:
        while len(t.layers) < 5:
            t.layers.add()
        base = t.layers[0]
        if not t.ready:
            base.show = True
            if obj.active_material and obj.active_material != t.preview:
                # Re-adopt when the stored source is missing or no longer on the mesh, so a
                # failed setup cannot strand the base layer on a material the user replaced.
                slots = [m for m in obj.data.materials if m]
                if not base.material or base.material not in slots:
                    base.material = obj.active_material
            if not base.material:
                # Nothing usable on the mesh: generate the shape this addon accepts rather
                # than silently building a flat grey base the user then has to diagnose.
                base.material = starter(obj.name + ' Base')
                obj.data.materials.append(base.material)
                obj.active_material_index = len(obj.data.materials) - 1
        for layer in t.layers:
            if layer.material:
                validate(layer.material)
        if not t.ready:
            source = t.adopt
            if source and (source.type not in {'IMAGE', 'UV_TEST'} or source.source not in {'FILE', 'GENERATED'} or source.channels != 4 or min(source.size) < 1):
                raise ValueError('Adopt an ordinary loaded four-channel image')
            if source and source.colorspace_settings.name not in {'Non-Color', 'Raw'}:
                raise ValueError('Adoption requires a Non-Color image; choose the data color space explicitly')
            n = int(t.resolution)
            w, h = source.size if source else (n, n)
            t.combined = new_image(t.image_name, w, h)
            if source:
                # Copy numeric channels; never change source color space or alpha mode.
                write(t.combined, pixels(source))
            else:
                write(t.combined, np.zeros((w*h, 4), np.float32))
            for _ in 'RGBA':
                t.masks.add()
            # A channel earns an image when its layer has a material, or when adopted paint
            # would otherwise be stranded in the RGBA with no canvas to edit it from.
            carried = pixels(t.combined) if source else None
            for i in range(4):
                if t.layers[i + 1].material or (carried is not None and carried[:, i].any()):
                    ensure_mask(obj, i)
            t.ready = True
        build(obj)
        _signatures[obj.name] = layer_signatures(obj)
        if t.preview.name not in obj.data.materials:
            obj.data.materials.append(t.preview)
        idx = list(obj.data.materials).index(t.preview)
        for face in obj.data.polygons:
            face.material_index = idx
        obj.active_material_index = idx
        sync(obj, True)
    finally:
        _busy = False


def tick():
    if not _enabled:
        return None
    if not bpy.app.background and terrains():
        for window in bpy.context.window_manager.windows:
            if window.as_pointer() not in _observers:
                with bpy.context.temp_override(window=window):
                    bpy.ops.lj_terrain.observe('INVOKE_DEFAULT')
    # A native stroke may consume its release event. The observer queues on press;
    # defer reads until Blender has removed the paint modal operator.
    if any(op.bl_idname == 'PAINT_OT_image_paint'
           for window in bpy.context.window_manager.windows for op in window.modal_operators):
        return .2
    for name in tuple(_dirty):
        _dirty.discard(name)
        obj = bpy.data.objects.get(name)
        if obj and obj.lj_terrain.ready:
            rebuild(obj)
    for name in tuple(_pending):
        obj = bpy.data.objects.get(name)
        if obj:
            try:
                sync(obj, incremental=True)
            except Exception:
                pass
        else:
            _pending.discard(name)
    return .2


@persistent
def save_pre(*args):
    for obj in terrains():
        try:
            sync(obj, True)
        except Exception as exc:
            print('LJ Terrain save synchronization failed:', exc)


@persistent
def restored(*args):
    _pending.clear()
    _raw.clear()
    _signatures.clear()
    for obj in terrains():
        queue(obj)
        _signatures[obj.name] = layer_signatures(obj)
        node = obj.lj_terrain.preview.node_tree.nodes.get('Normalize RGBA') if obj.lj_terrain.preview else None
        if node:
            node.outputs[0].default_value = float(normalized())


@persistent
def loaded(*args):
    _observers.clear()
    restored()


class LJ_OT_observe(bpy.types.Operator):
    """Pass events through to Blender; observe completion only, never paint."""
    bl_idname = 'lj_terrain.observe'
    bl_label = 'Observe native paint edits'
    def invoke(self, context, event):
        key = context.window.as_pointer()
        if key in _observers:
            return {'CANCELLED'}
        self.key = key
        self.generation = _generation
        _observers.add(key)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}
    def modal(self, context, event):
        if not _enabled or self.generation != _generation:
            if self.generation == _generation:
                _observers.discard(self.key)
            return {'CANCELLED'}
        if event.value in {'PRESS', 'RELEASE'} and event.type in {'LEFTMOUSE', 'RIGHTMOUSE', 'Z', 'Y'}:
            for obj in terrains():
                queue(obj)
        return {'PASS_THROUGH'}


class LJ_OT_mask_prompt(bpy.types.Operator):
    """Offer to drop a channel mask once its layer has no material."""
    bl_idname = 'lj_terrain.mask_prompt'
    bl_label = 'Delete Unused Mask'
    bl_options = {'REGISTER', 'INTERNAL'}
    target: StringProperty()
    channel: IntProperty()
    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(
            self, event, title='Unused Channel Mask', icon='WARNING', confirm_text='Delete Mask',
            message='Layer %d has no material, so channel %s is unused. Delete its painted mask? '
                    'Keep it to reuse the paint if you assign a material later.'
                    % (self.channel + 1, 'RGBA'[self.channel]))
    def execute(self, context):
        obj = bpy.data.objects.get(self.target)
        if not obj or not obj.lj_terrain.ready or len(obj.lj_terrain.masks) <= self.channel:
            return {'CANCELLED'}
        t = obj.lj_terrain
        image = t.masks[self.channel].image
        if image and not t.layers[self.channel + 1].material:
            t.masks[self.channel].image = None
            if image.users <= bool(image.use_fake_user):
                bpy.data.images.remove(image)
            _raw.pop(obj.name, None)
            queue(obj)
            self.report({'INFO'}, 'Channel %s mask deleted; it now reads as black' % 'RGBA'[self.channel])
        return {'FINISHED'}


class LJ_OT_action(bpy.types.Operator):
    bl_idname = 'lj_terrain.action'
    bl_label = 'LJ Terrain Action'
    bl_options = {'REGISTER'}
    action: StringProperty()
    index: IntProperty()
    delete_images: BoolProperty(name='Also Delete Painted Masks', options={'SKIP_SAVE'},
                                description='Permanently delete the RGBA splat and the four working mask images')
    def execute(self, context):
        obj = context.object
        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, 'Select a mesh')
            return {'CANCELLED'}
        t = obj.lj_terrain
        try:
            if self.action == 'SETUP':
                setup(obj)
            elif self.action == 'REFRESH':
                sync(obj)
            elif self.action == 'SOURCE':
                from .nodes import build
                build(obj)
                _signatures[obj.name] = layer_signatures(obj)
            elif self.action == 'STARTER':
                from .nodes import starter
                while len(t.layers) <= self.index:
                    t.layers.add()
                layer = t.layers[self.index]
                layer.material = starter(obj.name + (' Base' if not self.index else ' ' + 'RGBA'[self.index-1] + ' Layer'))
                layer.show = True
                if not self.index and not t.ready:
                    # Keep the base source on the mesh so setup's re-adoption leaves it alone.
                    remember(obj)
                    obj.data.materials.append(layer.material)
                    obj.active_material_index = len(obj.data.materials) - 1
            elif self.action == 'RESET':
                kept = reset(obj, self.delete_images)
                self.report({'INFO'}, f'Terrain setup removed; {len(kept)} painted image(s) kept in the blend')
            elif self.action == 'RELOAD':
                reload_masks(obj)
            elif self.action in {'FILL', 'CLEAR'}:
                native_fill(context, obj, 1 if self.action == 'FILL' else 0)
            elif self.action == 'PAINT':
                context.tool_settings.image_paint.mode = 'IMAGE'
                context.tool_settings.image_paint.canvas = canvas(obj)
                obj.data.uv_layers.active = obj.data.uv_layers[t.paint_uv]
                if obj.mode != 'TEXTURE_PAINT':
                    bpy.ops.object.mode_set(mode='TEXTURE_PAINT')
                if context.window:
                    bpy.ops.lj_terrain.observe('INVOKE_DEFAULT')
                for area in context.screen.areas if context.screen else []:
                    if area.type == 'VIEW_3D':
                        area.spaces.active.shading.type = 'MATERIAL'
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
    def invoke(self, context, event):
        if self.action == 'RESET':
            return context.window_manager.invoke_props_dialog(self)
        if self.action == 'RELOAD':
            return context.window_manager.invoke_confirm(self, event)
        return self.execute(context)
    def draw(self, context):
        ui = self.layout
        ui.label(text='Restore the mesh and remove the terrain setup?', icon='ERROR')
        ui.prop(self, 'delete_images')
        ui.label(text='Masks are deleted for good; this is not undoable.' if self.delete_images
                      else 'Painted masks are kept in the blend file.',
                 icon='TRASH' if self.delete_images else 'CHECKMARK')


class LJ_PT_terrain(bpy.types.Panel):
    bl_label = 'LJ Terrain Tools'
    bl_idname = 'LJ_PT_terrain'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'LJ Terrain'
    def draw(self, context):
        ui = self.layout
        obj = context.object
        if not obj or obj.type != 'MESH':
            ui.label(text='Select a terrain mesh')
            return
        t = obj.lj_terrain
        ui.label(text='Mesh: ' + obj.name)
        ui.prop_search(t, 'paint_uv', obj.data, 'uv_layers')
        def button(parent, label, action):
            parent.operator('lj_terrain.action', text=label).action = action
        def starter_button(parent, index):
            op = parent.operator('lj_terrain.action', text='New Starter Material', icon='ADD')
            op.action = 'STARTER'
            op.index = index
        if not t.ready:
            if len(t.layers):
                ui.prop(t.layers[0], 'material', text='Base Source')
            else:
                ui.label(text='Base Source: ' + (obj.active_material.name if obj.active_material else 'none'))
            if not (len(t.layers) and t.layers[0].material):
                starter_button(ui, 0)
            ui.prop(t, 'image_name')
            ui.prop(t, 'resolution')
            ui.prop(t, 'adopt')
            button(ui, 'Create Terrain Setup', 'SETUP')
            if t.origin_saved:
                button(ui, 'Reset Mesh', 'RESET')
            return
        ui.prop(context.scene, 'lj_normalize')
        ui.prop(t, 'active_mask', expand=True)
        if len(t.masks) > int(t.active_mask) and not t.masks[int(t.active_mask)].image:
            ui.label(text='No mask: give layer %d a material' % (int(t.active_mask) + 1), icon='INFO')
        button(ui, 'Paint Selected Channel', 'PAINT')
        row = ui.row()
        button(row, 'Fill White', 'FILL')
        button(row, 'Clear Black', 'CLEAR')
        ui.prop(t, 'display')
        ui.prop(t, 'mask_scale')
        ui.prop(t, 'mask_offset')
        for i, layer in enumerate(t.layers):
            box = ui.box()
            header = box.row(align=True)
            header.prop(layer, 'show', text='', emboss=False, icon='TRIA_DOWN' if layer.show else 'TRIA_RIGHT')
            title = 'Base' if i == 0 else f'{i}. {"RGBA"[i-1]} overlay'
            header.label(text=title + (' - ' + layer.material.name if layer.material else ''))
            if not layer.show:
                continue
            box.prop(layer, 'material', text='Source')
            if not layer.material:
                starter_button(box, i)
                if i:
                    continue
            if i:
                box.prop(layer, 'mode')
                for p in ('strength', 'albedo_strength', 'normal_strength', 'alpha_mask', 'contrast', 'smooth_strength'):
                    box.prop(layer, p)
                box.prop(layer, 'curve')
                if layer.curve:
                    box.prop(layer, 'curve_width')
            else:
                box.prop(layer, 'normal_strength')
            for p in ('tint', 'scale', 'offset'):
                box.prop(layer, p)
            box.prop_search(layer, 'uv', obj.data, 'uv_layers')
            box.prop(layer, 'height_source')
            if layer.height_source == 'IMAGE':
                box.prop(layer, 'height_image')
                box.prop(layer, 'height_channel')
            elif layer.height_source == 'CONSTANT':
                box.prop(layer, 'height')
            for p in ('height_remap', 'smooth_remap', 'metal_remap', 'flip_green'):
                box.prop(layer, p)
        button(ui, 'Refresh from Source Materials', 'SOURCE')
        row = ui.row()
        row.enabled = False
        row.prop(t, 'combined')
        ui.label(text=t.status)
        ui.label(text=t.preview_status)
        ui.label(text=f'Last sync: {t.sync_ms:.0f} ms')
        button(ui, 'Refresh RGBA', 'REFRESH')
        button(ui, 'Reload Masks from RGBA (overwrite)', 'RELOAD')
        ui.separator()
        button(ui, 'Reset Mesh (remove terrain setup)', 'RESET')


CLASSES = (LJLayer, LJMask, LJTerrain, LJ_OT_observe, LJ_OT_mask_prompt, LJ_OT_action, LJ_PT_terrain)
HANDLERS = ((bpy.app.handlers.save_pre, save_pre), (bpy.app.handlers.load_post, loaded),
            (bpy.app.handlers.undo_post, restored), (bpy.app.handlers.redo_post, restored),
            (bpy.app.handlers.depsgraph_update_post, source_edited))


def register():
    global _enabled, _generation
    _cached = sys.modules.get(__name__ + '.nodes')
    if _cached:
        importlib.reload(_cached)
    _generation += 1
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Object.lj_terrain = PointerProperty(type=LJTerrain)
    bpy.types.Scene.lj_normalize = BoolProperty(name='Normalize RGBA Channels', get=lambda self: normalized(), set=set_normalized)
    for handlers, callback in HANDLERS:
        handlers.append(callback)
    _enabled = True
    bpy.app.timers.register(tick, persistent=True)


def unregister():
    global _enabled, _generation
    _enabled = False
    _generation += 1
    _pending.clear()
    _dirty.clear()
    _raw.clear()
    _signatures.clear()
    _observers.clear()
    for callback in tuple(_fill_timers) + tuple(_mask_prompts):
        if bpy.app.timers.is_registered(callback):
            bpy.app.timers.unregister(callback)
    _fill_timers.clear()
    _mask_prompts.clear()
    if bpy.app.timers.is_registered(tick):
        bpy.app.timers.unregister(tick)
    for handlers, callback in HANDLERS:
        if callback in handlers:
            handlers.remove(callback)
    del bpy.types.Scene.lj_normalize
    del bpy.types.Object.lj_terrain
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
