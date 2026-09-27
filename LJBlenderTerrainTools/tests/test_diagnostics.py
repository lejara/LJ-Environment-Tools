"""Render linear emission diagnostics; compare node graph against shader equations."""
import bpy
import sys
import json
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import lj_terrain_tools as lj
from lj_terrain_tools.math_core import height_blend, blend, pack
from lj_terrain_tools.nodes import build
lj.register()
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
bpy.ops.mesh.primitive_plane_add(size=2)
obj = bpy.context.object
obj.lj_terrain.resolution = '1024'
lj.setup(obj)
t = obj.lj_terrain
colors = [(.1,.2,.3), (.8,.4,.2), (.2,.8,.6), (.7,.1,.4), (.4,.6,.9)]
heights = [.3,.6,.2,.8,.5]
for i, layer in enumerate(t.layers):
    mat = bpy.data.materials.new('Diagnostic source ' + str(i))
    mat.use_nodes = True
    s = mat.node_tree.nodes.get('Principled BSDF')
    s.inputs['Base Color'].default_value = (*colors[i], 1)
    s.inputs['Roughness'].default_value = .2+i*.1
    s.inputs['Metallic'].default_value = i*.15
    layer.material = mat
    layer.height = heights[i]
    layer.alpha_mask = False
raw = np.array([.7,.2,.4,.3], np.float32)
for i, entry in enumerate(t.masks):
    a = lj.pixels(entry.image)
    a[:,:3] = raw[i]
    lj.write(entry.image, a)
bpy.ops.object.camera_add(location=(0,0,3))
camera = bpy.context.object
camera.data.type = 'ORTHO'
camera.data.ortho_scale = 1
scene = bpy.context.scene
scene.camera = camera
scene.render.engine = 'CYCLES'
scene.cycles.samples = 16
scene.cycles.use_denoising = False
scene.render.resolution_x = 8
scene.render.resolution_y = 8
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = 'OPEN_EXR'
scene.render.image_settings.color_depth = '32'
errors=[]
for norm in (False, True):
    scene.lj_normalize = norm
    lj.sync(obj)
    weights = pack(raw, norm)
    for mode in ('ALPHA','HEIGHT','MULTIPLY'):
        c = np.array(colors[0])
        h = heights[0]
        smooth = .8
        metal = 0
        for i, layer in enumerate(t.layers[1:]):
            layer.mode = mode
            w = float(weights[i])
            f = float(height_blend(h, heights[i+1], w, .5)) if mode=='HEIGHT' else w
            c = blend(c, np.array(colors[i+1]), f, mode)
            if mode!='MULTIPLY':
                h += (heights[i+1]-h)*f
                smooth += (.8-(i+1)*.1-smooth)*f
                metal += ((i+1)*.15-metal)*f
        for display, expected in [('ALBEDO', c), ('HEIGHT', h), ('SMOOTH', smooth), ('METAL', metal)]:
            t.display = display
            build(obj)
            path = ROOT/'tests'/'diagnostic.exr'
            scene.render.filepath = str(path)
            bpy.ops.render.render(write_still=True)
            result = bpy.data.images.load(str(path), check_existing=False)
            actual = lj.pixels(result)[32,:3]
            error = float(np.max(np.abs(actual-expected)))
            errors.append(dict(normalize=norm, mode=mode, channel=display, expected=np.broadcast_to(expected,(3,)).tolist(), actual=actual.tolist(), error=error))
            bpy.data.images.remove(result)
            assert error < 2e-5, errors[-1]
(ROOT/'tests'/'diagnostic-results.json').write_text(json.dumps(errors, indent=2))
unity=json.loads((ROOT/'tests'/'unity-results.json').read_text())
cross_errors=[]
for record in errors:
    mode=('ALPHA','HEIGHT','MULTIPLY').index(record['mode'])
    diagnostic=0 if record['channel'] in {'ALBEDO','HEIGHT'} else 1
    row=next(r for r in unity if r['mode']==mode and bool(r['normalize'])==record['normalize'] and r['diagnostic']==diagnostic)
    v=row['rgba']
    expected=v[:3] if record['channel']=='ALBEDO' else v[3] if record['channel']=='HEIGHT' else v[0] if record['channel']=='SMOOTH' else v[1]
    error=float(np.max(np.abs(np.array(record['actual'])-expected)))
    cross_errors.append(error)
    assert error<2e-5
(ROOT/'tests'/'cross-engine-results.json').write_text(json.dumps({'cases':len(errors),'max_error':max(cross_errors),'tolerance':2e-5},indent=2))

# Actual image extraction, remapped albedo alpha, separate height and normal input.
for layer in t.layers[2:]:
    layer.material=None
scene.lj_normalize=False
lj.sync(obj)
layer=t.layers[1]
layer.mode='ALPHA';layer.alpha_mask=True;layer.height_remap=(.2,.8)
shader=layer.material.node_tree.nodes.get('Principled BSDF')
tex=layer.material.node_tree.nodes.new('ShaderNodeTexImage')
tex.image=lj.new_image('Constant texture test',1,1)
lj.write(tex.image,np.array([[.8,.4,.2,.35]],np.float32))
layer.material.node_tree.links.new(tex.outputs['Color'],shader.inputs['Base Color'])
f=.7*(.2+.35*.6)
c=np.array(colors[0])+(np.array(colors[1])-colors[0])*f
for display,expected in [('ALBEDO',c)]:
    t.display=display;build(obj)
    bpy.ops.render.render(write_still=True)
    result=bpy.data.images.load(str(path),check_existing=False)
    actual=lj.pixels(result)[32,:3]
    np.testing.assert_allclose(actual,expected,atol=2e-5)
    bpy.data.images.remove(result)
for i in (0,1):
    mat=t.layers[i].material
    shader=mat.node_tree.nodes.get('Principled BSDF')
    tex=mat.node_tree.nodes.new('ShaderNodeTexImage')
    tex.image=lj.new_image('Normal test '+str(i),1,1)
    value=[.6,.7,(np.sqrt(.8)+1)/2,1] if i==0 else [.7,.4,(np.sqrt(.8)+1)/2,1]
    lj.write(tex.image,np.array([value],np.float32))
    nm=mat.node_tree.nodes.new('ShaderNodeNormalMap')
    mat.node_tree.links.new(tex.outputs['Color'],nm.inputs['Color'])
    mat.node_tree.links.new(nm.outputs['Normal'],shader.inputs['Normal'])
t.display='NORMAL';build(obj)
bpy.ops.render.render(write_still=True)
result=bpy.data.images.load(str(path),check_existing=False)
base_n=np.array([.2,.4,np.sqrt(.8)])
overlay_n=np.array([.4*f,-.2*f,np.sqrt(.8)])
expected=(base_n+(overlay_n-base_n)*f+1)/2
np.testing.assert_allclose(lj.pixels(result)[32,:3],expected,atol=2e-5)
bpy.data.images.remove(result)
print('DIAGNOSTICS PASSED; max error', max(e['error'] for e in errors))
