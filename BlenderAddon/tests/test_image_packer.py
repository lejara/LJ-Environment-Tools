"""Run with Blender --background --factory-startup --python this_file.py.

All exports and blend files go to a temporary directory. No user preferences
are saved. PNG checks decode actual bytes independently of Blender's loader.
"""

import importlib
import os
from pathlib import Path
import struct
import sys
import tempfile
import zlib

import addon_utils
import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
addon_utils.enable('BlenderAddon', default_set=True)
addon = importlib.import_module('BlenderAddon')
packer = addon.image_packer
packer.sync_to_global = lambda context: None
packer.seed_existing_scenes()


def decode_png(path):
    data = Path(path).read_bytes()
    assert data[:8] == b'\x89PNG\r\n\x1a\n'
    offset, payload, header = 8, b'', None
    while offset < len(data):
        length = struct.unpack('!I', data[offset:offset + 4])[0]
        kind = data[offset + 4:offset + 8]
        body = data[offset + 8:offset + 8 + length]
        checksum = struct.unpack('!I', data[offset + 8 + length:offset + 12 + length])[0]
        assert checksum == zlib.crc32(kind + body) & 0xffffffff
        if kind == b'IHDR':
            header = struct.unpack('!IIBBBBB', body)
        if kind == b'IDAT':
            payload += body
        offset += 12 + length
    width, height, bits, color, compression, filtering, interlace = header
    assert (color, compression, filtering, interlace) == (6, 0, 0, 0)
    raw = zlib.decompress(payload)
    stride = width * 4 * (bits // 8)
    assert len(raw) == height * (stride + 1)
    rows = []
    for y in range(height):
        start = y * (stride + 1)
        assert raw[start] == 0
        rows.append(np.frombuffer(raw[start + 1:start + 1 + stride],
                                  dtype=np.uint8 if bits == 8 else '>u2'))
    return np.array(rows).reshape(height, width, 4)[::-1], bits


def expect_cancel(**kwargs):
    try:
        assert bpy.ops.ljpack.export(**kwargs) == {'CANCELLED'}
    except RuntimeError:
        # bpy raises when an operator reports ERROR.
        pass


with tempfile.TemporaryDirectory(prefix='lj_image_packer_test_') as folder:
    settings = bpy.context.scene.lj_image_packer
    assert settings.initialized
    assert not settings.packer_load_images
    settings.packer_output_path = folder
    assert bpy.ops.ljpack.add_preset() == {'FINISHED'}
    preset = settings.presets[0]
    preset.name = 'Packed Test'
    preset.width = preset.height = 2
    assert preset.bit_depth == '8'
    assert all(slot.constant == 0 for slot in packer.channels(preset))

    original = np.array([[[0.1, 0.2, 0.3, 0.4], [0.5, 0.6, 0.7, 0.8]],
                         [[0.9, 1.0, 0.0, 0.1], [0.25, 0.5, 0.75, 1.0]]], dtype=np.float32)
    source = bpy.data.images.new('Test Source', width=2, height=2, alpha=True, float_buffer=True)
    source.colorspace_settings.name = 'Non-Color'
    source.alpha_mode = 'CHANNEL_PACKED'
    source.pixels.foreach_set(original.ravel())
    source.update()
    for slot, mode in zip(packer.channels(preset), ('B', 'GRAY', 'A', 'R')):
        slot.image = source
        slot.source = mode
    preset.alpha.image = None  # Alpha zero must not erase the RGB payload.
    expected = np.stack((original[..., 2], original[..., :3] @ np.array([0.2126, 0.7152, 0.0722]),
                         original[..., 3], np.zeros((2, 2))), axis=-1).astype(np.float32)
    image_count = len(bpy.data.images)
    assert bpy.ops.ljpack.export(index=0) == {'FINISHED'}
    path = Path(folder) / 'Packed Test.png'
    actual, bits = decode_png(path)
    assert bits == 8
    np.testing.assert_array_equal(actual, np.rint(expected * 255).astype(np.uint8))
    assert len(bpy.data.images) == image_count
    np.testing.assert_array_equal(packer._image_pixels(source), original)
    assert source.size[:] == (2, 2)
    for mode, channel_index in zip('RGBA', range(4)):
        preset.red.source = mode
        np.testing.assert_array_equal(packer.pack_pixels(preset)[..., 0], original[..., channel_index])
    preset.red.source = 'B'

    # 16-bit precision and overwrite the existing 8-bit file.
    preset.bit_depth = '16'
    preset.alpha.constant = 0.12345
    expected[..., 3] = np.float32(0.12345)
    assert bpy.ops.ljpack.export(index=0) == {'FINISHED'}
    actual, bits = decode_png(path)
    assert bits == 16
    np.testing.assert_array_equal(actual, np.rint(expected * 65535).astype(np.uint16))
    assert int(actual[0, 0, 3]) % 257 != 0  # Not 8-bit data padded into 16 bits.

    # Pixel-center bilinear resizing, including non-square and 1x1 cases.
    small = np.array([[0, 1], [1, 0]], dtype=np.float32)
    np.testing.assert_allclose(packer.core.resize_channel(small, 3, 3),
                               [[0, .5, 1], [.5, .5, .5], [1, .5, 0]])
    np.testing.assert_allclose(packer.core.resize_channel(small, 1, 1), [[.5]])
    np.testing.assert_allclose(packer.core.resize_channel(np.array([[.7]], dtype=np.float32), 3, 2), .7)
    preset.width, preset.height = 3, 5
    assert packer.pack_pixels(preset).shape == (5, 3, 4)

    # Individual export must not export another preset; all-export must honor overrides.
    bpy.ops.ljpack.add_preset()
    second = settings.presets[1]
    second.name = 'Other'
    second.width, second.height = 1, 2
    second.output_path = str(Path(folder) / 'override')
    second.red.constant = 0.75
    other_path = Path(second.output_path) / 'Other.png'
    bpy.ops.ljpack.export(index=0)
    assert not other_path.exists()
    settings.packer_load_images = True
    assert bpy.ops.ljpack.export() == {'FINISHED'}
    assert other_path.exists()
    loaded = next(image for image in bpy.data.images if image.filepath == str(path))
    assert loaded.colorspace_settings.name == 'Non-Color'
    assert loaded.alpha_mode == 'CHANNEL_PACKED'
    assert loaded.use_fake_user
    assert loaded.size[:] == (3, 5)
    actual, bits = decode_png(path)
    np.testing.assert_allclose(packer._image_pixels(loaded), actual / 65535, atol=2e-7)
    image_count = len(bpy.data.images)
    second.red.constant = 0.2
    assert bpy.ops.ljpack.export(index=1) == {'FINISHED'}
    assert len(bpy.data.images) == image_count
    other = next(image for image in bpy.data.images if image.filepath == str(other_path))
    np.testing.assert_allclose(packer._image_pixels(other)[..., 0], .2, atol=1 / 255)

    # Collision and invalid-path checks happen before any batch output is overwritten.
    before = path.read_bytes()
    second.name, second.output_path = preset.name, ''
    expect_cancel()
    assert path.read_bytes() == before
    second.name = '../escape'
    expect_cancel(index=1)
    second.name = 'CON'
    expect_cancel(index=1)
    second.name = 'Other'
    settings.packer_output_path = ''
    expect_cancel(index=1)
    settings.packer_output_path = '//exports/'
    expect_cancel(index=1)  # Unsaved blend cannot resolve a relative output path.
    settings.packer_output_path = folder

    # Scene recipes, image references, UI selection and options survive save/reopen.
    source.pack()
    blend_path = str(Path(folder) / 'presets.blend')
    bpy.ops.wm.save_as_mainfile(filepath=blend_path)
    bpy.ops.wm.open_mainfile(filepath=blend_path)
    settings = bpy.context.scene.lj_image_packer
    assert len(settings.presets) == 2
    assert settings.presets[0].blue.source == 'A'
    assert settings.presets[0].red.image.name == 'Test Source'
    assert settings.presets[0].bit_depth == '16'
    assert settings.packer_load_images
    assert settings.active_index == 1
    settings.presets[1].output_path = '//relative/'
    assert bpy.ops.ljpack.export(index=1) == {'FINISHED'}
    assert (Path(folder) / 'relative' / 'Other.png').exists()
    assert bpy.ops.ljpack.remove_preset() == {'FINISHED'}
    assert len(settings.presets) == 1 and settings.active_index == 0

    # Removing and enabling the addon cleans up its classes, property and handler.
    addon.unregister()

    addon = importlib.reload(addon)
    addon.register()
    assert bpy.types.LJPACK_PT_panel.bl_category == 'LJ'
    assert 'packer_output_path' in addon.preferences.LJEXPORT_AP_preferences.__annotations__
    addon.unregister()
    assert not hasattr(bpy.types.Scene, 'lj_image_packer')
    assert packer._on_load_post not in bpy.app.handlers.load_post
    addon.register()
    assert hasattr(bpy.types.Scene, 'lj_image_packer')
    assert bpy.types.LJPACK_PT_panel.bl_category == 'LJ'
    assert bpy.types.LJMATIMP_PT_panel.bl_category == 'LJ'
    addon.unregister()

print('PASS: LJ Image Packer integration, PNG bytes, precision, persistence and registration')
