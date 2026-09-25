"""Numeric channel packing and data PNG output (no display/color transforms)."""

import os
import struct
import tempfile
import zlib

import numpy as np


def extract_channel(pixels, channel):
    if channel == 'GRAY':
        # Rec. 709 luminance weights, applied to the supplied image buffer values.
        return (pixels[..., 0] * 0.2126 + pixels[..., 1] * 0.7152
                + pixels[..., 2] * 0.0722)
    return pixels[..., 'RGBA'.index(channel)]


def resize_channel(values, width, height):
    """Bilinear resize using pixel centers and clamped edges; never edits input."""
    src_h, src_w = values.shape
    if (src_w, src_h) == (width, height):
        return values
    x = np.clip((np.arange(width) + 0.5) * src_w / width - 0.5, 0, src_w - 1)
    x0 = x.astype(np.intp)
    x1 = np.minimum(x0 + 1, src_w - 1)
    weight_x = (x - x0).astype(np.float32)
    result = np.empty((height, width), dtype=np.float32)
    # Bound temporary array sizes even for large output textures.
    for start in range(0, height, 64):
        end = min(start + 64, height)
        y = np.clip((np.arange(start, end) + 0.5) * src_h / height - 0.5, 0, src_h - 1)
        y0 = y.astype(np.intp)
        y1 = np.minimum(y0 + 1, src_h - 1)
        weight_y = (y - y0).astype(np.float32)[:, None]
        top = values[y0[:, None], x0] * (1 - weight_x) + values[y0[:, None], x1] * weight_x
        bottom = values[y1[:, None], x0] * (1 - weight_x) + values[y1[:, None], x1] * weight_x
        result[start:end] = top * (1 - weight_y) + bottom * weight_y
    return result


def _chunk(stream, kind, data):
    stream.write(struct.pack('!I', len(data)))
    stream.write(kind)
    stream.write(data)
    stream.write(struct.pack('!I', zlib.crc32(data, zlib.crc32(kind)) & 0xffffffff))


def write_png(path, pixels, bit_depth):
    """Write independent RGBA data channels, including RGB where alpha is zero.

    Blender buffers are bottom-up; PNG scanlines are top-down. Streaming rows
    avoids allocating another full 16-bit image. Atomic replacement preserves
    an existing export if encoding fails. No gamma/display metadata is added.
    """
    height, width, channels = pixels.shape
    if channels != 4 or bit_depth not in (8, 16):
        raise ValueError('Expected RGBA pixels and 8-bit or 16-bit output')
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=folder, prefix='.ljpack-', suffix='.tmp', delete=False) as stream:
            temp_path = stream.name
            stream.write(b'\x89PNG\r\n\x1a\n')
            _chunk(stream, b'IHDR', struct.pack('!IIBBBBB', width, height, bit_depth, 6, 0, 0, 0))
            compressor = zlib.compressobj(6)
            maximum = (1 << bit_depth) - 1
            dtype = np.uint8 if bit_depth == 8 else np.dtype('>u2')
            for row in pixels[::-1]:
                clean = np.nan_to_num(row, nan=0.0, posinf=1.0, neginf=0.0)
                encoded = np.rint(np.clip(clean, 0, 1) * maximum).astype(dtype).tobytes()
                data = compressor.compress(b'\x00' + encoded)
                if data:
                    _chunk(stream, b'IDAT', data)
            _chunk(stream, b'IDAT', compressor.flush())
            _chunk(stream, b'IEND', b'')
        os.replace(temp_path, path)
        temp_path = None
    finally:
        if temp_path is not None:
            os.unlink(temp_path)
