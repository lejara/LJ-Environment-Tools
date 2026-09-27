import bpy
import sys
import math
from pathlib import Path
import numpy as np
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import lj_terrain_tools as lj
from lj_terrain_tools.nodes import build
lj.register()
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
bpy.ops.mesh.primitive_grid_add(x_subdivisions=65,y_subdivisions=65,size=8)
obj=bpy.context.object
obj.name='LJ Terrain - Paint Me'
for v in obj.data.vertices:
    x,y=v.co.x,v.co.y
    v.co.z=.28*math.sin(x*1.1)*math.cos(y*.8)+.6*math.exp(-((x-1)**2+(y+.5)**2)/4)
for p in obj.data.polygons:
    p.use_smooth=True
t=obj.lj_terrain
lj.setup(obj)
colors=[(.19,.105,.05),(.07,.22,.025),(.36,.28,.14),(.19,.23,.25),(.5,.57,.6)]
names=['Earth Base','R Grass','G Sand','B Stone','A Pale Rock']
for i,layer in enumerate(t.layers):
    mat=bpy.data.materials.new(names[i]);mat.use_nodes=True
    node=mat.node_tree.nodes.get('Principled BSDF')
    node.inputs['Base Color'].default_value=(*colors[i],1)
    node.inputs['Roughness'].default_value=.8
    layer.material=mat
    layer.alpha_mask=False
    layer.height=.5
    layer.mode='ALPHA'
n=t.combined.size[0]
y,x=np.mgrid[0:n,0:n]/(n-1)
for entry,(cx,cy) in zip(t.masks,[(.23,.3),(.7,.22),(.27,.74),(.73,.72)]):
    v=np.clip(1-np.sqrt((x-cx)**2+(y-cy)**2)/.43,0,1)
    a=np.ones((n*n,4),np.float32);a[:,:3]=v.reshape(-1,1)
    lj.write(entry.image,a)
lj.sync(obj,True);build(obj)
bpy.ops.object.camera_add(location=(9,-11,10))
camera=bpy.context.object
camera.rotation_euler=(Vector((0,0,0))-camera.location).to_track_quat('-Z','Y').to_euler()
camera.data.type='ORTHO';camera.data.ortho_scale=11.5
scene=bpy.context.scene;scene.camera=camera
bpy.ops.object.light_add(type='AREA',location=(0,-2,8))
bpy.context.object.data.energy=1800
bpy.context.object.data.shape='DISK';bpy.context.object.data.size=8
scene.world.color=(.18,.18,.18)
scene.render.engine='CYCLES';scene.cycles.samples=32
scene.render.resolution_x=700;scene.render.resolution_y=600;scene.render.resolution_percentage=100
bpy.ops.object.select_all(action='DESELECT')
obj.select_set(True);bpy.context.view_layer.objects.active=obj
for area in bpy.context.screen.areas:
    if area.type=='VIEW_3D':
        area.spaces.active.shading.type='MATERIAL'
        area.spaces.active.region_3d.view_distance=12
        area.spaces.active.region_3d.view_location=(0,0,0)
scene.render.filepath=str(ROOT/'examples'/'preview.png')
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/'examples'/'LJ Terrain Example.blend'))
bpy.ops.render.render(write_still=True)
