import sys
from pathlib import Path
import time
import json
import bpy
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import lj_terrain_tools as lj
from lj_terrain_tools.math_core import pack, height_blend

lj.register()
bpy.ops.mesh.primitive_plane_add(size=2)
obj = bpy.context.object
obj.name = 'Terrain Example'
base = bpy.data.materials.new('Source Base Soil')
base.use_nodes = True
base.node_tree.nodes.get('Principled BSDF').inputs['Base Color'].default_value = (.12, .06, .025, 1)
obj.data.materials.append(base)
t = obj.lj_terrain
t.resolution = '1024'
lj.setup(obj)
assert not lj.normalized()
assert len(t.masks) == 4
initial = (len(bpy.data.images), len(bpy.data.materials), len(bpy.data.node_groups))
lj.setup(obj)
assert initial == (len(bpy.data.images), len(bpy.data.materials), len(bpy.data.node_groups))
raw = np.array([[0, 0, 0, 0], [1, 1, 0, 0], [0, 0, 0, 1], [.2, 0, 0, 0], [1e-20, 2e-20, 0, 0], [.2, .3, 0, .5]], np.float32)
# Channel masks are created on demand now; this block exercises packing, so ask for all four.
for i in range(4):
    lj.ensure_mask(obj, i)
for i, m in enumerate(t.masks):
    a = lj.pixels(m.image)
    a[:6, :3] = raw[:, i:i+1]
    lj.write(m.image, a)
lj.sync(obj)
np.testing.assert_allclose(lj.pixels(t.combined)[:6], raw, atol=1e-7)
bpy.context.scene.lj_normalize = True
lj.tick()
np.testing.assert_allclose(lj.pixels(t.combined)[:6], pack(raw, True), atol=1e-7)
for i, m in enumerate(t.masks):
    np.testing.assert_array_equal(lj.pixels(m.image)[:6, 0], raw[:, i])
bpy.context.scene.lj_normalize = False
lj.tick()
np.testing.assert_allclose(lj.pixels(t.combined)[:6], raw, atol=1e-7)

overlay = bpy.data.materials.new('Source Overlay Grass')
overlay.use_nodes = True
overlay.node_tree.nodes.get('Principled BSDF').inputs['Base Color'].default_value = (.12, .32, .04, 1)
t.layers[1].material = overlay
from lj_terrain_tools.nodes import build
for mode in ('ALPHA', 'HEIGHT', 'MULTIPLY'):
    t.layers[1].mode = mode
    build(obj)
t.layers[1].mode = 'HEIGHT'
before = (len(bpy.data.images), len(bpy.data.materials), len(bpy.data.node_groups))
for _ in range(3):
    build(obj)
assert before == (len(bpy.data.images), len(bpy.data.materials), len(bpy.data.node_groups))
assert base.node_tree.nodes.get('Principled BSDF').inputs['Base Color'].default_value[0] < .13

# Adoption copies channels without mutating the donor, and explicit reload works.
donor=lj.new_image('Adoption donor',16,16)
donor_data=np.tile(np.array([.2,.3,.4,0],np.float32),(256,1))
lj.write(donor,donor_data)
bpy.ops.mesh.primitive_plane_add()
adopt_obj=bpy.context.object
adopt_obj.lj_terrain.adopt=donor
lj.setup(adopt_obj)
np.testing.assert_array_equal(lj.pixels(adopt_obj.lj_terrain.combined),donor_data)
assert adopt_obj.lj_terrain.combined!=donor
bpy.context.scene.lj_normalize=True
lj.tick()
np.testing.assert_allclose(lj.pixels(adopt_obj.lj_terrain.combined),pack(donor_data,True),atol=1e-7)
np.testing.assert_array_equal(lj.pixels(donor),donor_data)
bpy.context.scene.lj_normalize=False
lj.tick()
donor_data[:]=(.8,.1,0,.5)
lj.write(adopt_obj.lj_terrain.combined,donor_data)
lj.reload_masks(adopt_obj)
np.testing.assert_array_equal(lj.pixels(adopt_obj.lj_terrain.combined),donor_data)
bpy.data.objects.remove(adopt_obj,do_unlink=True)
bpy.context.view_layer.objects.active=obj
obj.select_set(True)

# Native fill/clear and undo are covered by test_native_ui.py.

results = {'blender': bpy.app.version_string, 'sync_seconds': {}}
for resolution in (1024, 2048, 4096):
    for image in [t.combined] + [m.image for m in t.masks]:
        image.scale(resolution, resolution)
    start = time.perf_counter()
    lj.sync(obj)
    results['sync_seconds'][resolution] = time.perf_counter()-start
    print('SYNC BENCHMARK', resolution, results['sync_seconds'][resolution], flush=True)
for image in [t.combined] + [m.image for m in t.masks]:
    image.scale(1024, 1024)

# Pack an intentional RGB value with zero alpha and test reopening.
a = lj.pixels(t.masks[0].image)
a[:, :3] = .25
lj.write(t.masks[0].image, a)
bpy.context.scene.lj_normalize = True
example = ROOT / 'examples' / 'LJ Terrain Example.blend'
example.parent.mkdir(exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(example))
bpy.ops.wm.open_mainfile(filepath=str(example))
obj = bpy.data.objects['Terrain Example']
t = obj.lj_terrain
assert lj.normalized()
assert abs(lj.pixels(t.masks[0].image)[100, 0] - .25) < 1e-7
lj.sync(obj)
assert lj.pixels(t.combined)[100, 3] == 0
assert lj.pixels(t.combined)[100, 0] > 0
bpy.ops.wm.read_factory_settings(use_empty=True)
assert not lj.normalized()
bpy.ops.wm.open_mainfile(filepath=str(example))
assert lj.normalized()
lj.unregister()
assert not bpy.app.timers.is_registered(lj.tick)
for handlers, callback in lj.HANDLERS:
    assert callback not in handlers
lj.register()
lj.unregister()
results['passed'] = ['raw packing', 'normalization / tiny values / alpha-only', 'toggle reversibility', 'raw preservation', 'all three node graphs', 'resource reuse', 'source preservation', '1K / 2K / 4K timing', 'packed float RGB with zero alpha persistence', 'file-local setting isolation', 'registration cleanup']
(ROOT / 'tests' / 'results.json').write_text(json.dumps(results, indent=2))
print('LJ TERRAIN TESTS PASSED', json.dumps(results), flush=True)
