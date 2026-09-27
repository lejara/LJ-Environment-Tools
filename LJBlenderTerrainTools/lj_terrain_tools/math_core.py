"""Array reference equations; no Blender dependency beyond bundled numpy."""
import numpy as np


def pack(raw, normalize=False):
    # clip already returns a fresh array; astype(copy=False) avoids a second full copy.
    result = np.clip(raw, 0, 1).astype(np.float32, copy=False)
    if normalize:
        total = result.sum(axis=-1, keepdims=True)
        np.divide(result, total, out=result, where=total > 0)
    return result


def height_blend(base, layer, mask, contrast):
    inverse = 1 - layer
    tween = np.clip((mask - np.minimum(base, inverse)) /
                    np.maximum(np.abs(base - inverse), .001), 0, 1)
    return np.clip((tween - (1 - contrast)) / max(contrast, .001), 0, 1)


def blend(base, layer, weight, mode='ALPHA', strength=1):
    target = base * 2 * layer if mode == 'MULTIPLY' else layer
    return base + (target - base) * weight * strength
