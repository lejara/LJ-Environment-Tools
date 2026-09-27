"""Run in an isolated GUI process; timers allow editor/tool initialization."""
import bpy
import sys
import traceback
import json
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import lj_terrain_tools as lj
results=[]

def prepare():
    try:
        lj.register()
        bpy.ops.mesh.primitive_plane_add()
        obj=bpy.context.object
        obj.name='NativeTest'
        obj.lj_terrain.resolution='1024'
        lj.setup(obj)
        area=next(a for a in bpy.context.screen.areas if a.type=='VIEW_3D')
        area.type='IMAGE_EDITOR'
        area.spaces.active.mode='PAINT'
        area.spaces.active.image=obj.lj_terrain.masks[0].image
        bpy.app.timers.register(run, first_interval=2)
    except Exception:
        traceback.print_exc()
        bpy.ops.wm.quit_blender()

def run():
    try:
        obj=bpy.data.objects['NativeTest']
        t=obj.lj_terrain
        area=next(a for a in bpy.context.screen.areas if a.type=='IMAGE_EDITOR')
        region=next(r for r in area.regions if r.type=='WINDOW')
        with bpy.context.temp_override(area=area, region=region):
            bpy.ops.wm.tool_set_by_id(name='builtin.brush')
            bpy.ops.brush.asset_activate(asset_library_type='ESSENTIALS', relative_asset_identifier='brushes/essentials_brushes-mesh_texture.blend/Brush/Paint Hard')
            bpy.ops.image.view_all()
        bpy.app.timers.register(strokes, first_interval=2)
    except Exception:
        traceback.print_exc()
        bpy.ops.wm.quit_blender()

def strokes():
    try:
        obj=bpy.data.objects['NativeTest']
        t=obj.lj_terrain
        area=next(a for a in bpy.context.screen.areas if a.type=='IMAGE_EDITOR')
        region=next(r for r in area.regions if r.type=='WINDOW')
        with bpy.context.temp_override(area=area, region=region):
            brush=bpy.context.tool_settings.image_paint.brush
            brush.color=(1,1,1)
            brush.strength=1
            brush.size=50
            ups=bpy.context.tool_settings.image_paint.unified_paint_settings
            ups.use_unified_color=False
            ups.use_unified_strength=False
            ups.use_unified_size=False
            bpy.ops.ed.undo_push(message='Native baseline')
            for resolution in (1024,2048):
                for image in [t.combined]+[m.image for m in t.masks]:
                    image.scale(resolution,resolution)
                    a=lj.pixels(image)
                    a[:,:3]=0
                    lj.write(image,a)
                bpy.ops.ed.undo_push(message='Resolution baseline')
                for i in range(4):
                    image=t.masks[i].image
                    area.spaces.active.image=image
                    previous=[lj.pixels(m.image).copy() for m in t.masks]
                    x,y=region.width/2,region.height/2
                    stroke=[dict(name='native test', mouse=(x,y), mouse_event=(x,y), pressure=1, size=50, time=0, is_start=True, x_tilt=0,y_tilt=0,location=(0,0,0)),dict(name='native test', mouse=(x+30,y), mouse_event=(x+30,y), pressure=1,size=50,time=.1,is_start=False,x_tilt=0,y_tilt=0,location=(0,0,0))]
                    bpy.ops.paint.image_paint(stroke=stroke)
                    painted=lj.pixels(image).copy()
                    delta=float(np.max(np.abs(painted-previous[i])))
                    print('NATIVE',resolution,i,delta,flush=True)
                    assert delta>0
                    for j in range(4):
                        if j!=i:
                            np.testing.assert_array_equal(lj.pixels(t.masks[j].image),previous[j])
                    lj.queue(obj)
                    lj.tick()
                    np.testing.assert_array_equal(lj.pixels(t.combined)[:,i],painted[:,0])
                    bpy.ops.ed.undo()
                    obj=bpy.data.objects['NativeTest']; t=obj.lj_terrain
                    np.testing.assert_array_equal(lj.pixels(t.masks[i].image),previous[i])
                    lj.tick()
                    np.testing.assert_array_equal(lj.pixels(t.combined)[:,i],previous[i][:,0])
                    bpy.ops.ed.redo()
                    obj=bpy.data.objects['NativeTest']; t=obj.lj_terrain
                    np.testing.assert_array_equal(lj.pixels(t.masks[i].image),painted)
                    lj.tick()
                    np.testing.assert_array_equal(lj.pixels(t.combined)[:,i],painted[:,0])
                    # Blender's native Blur brush, no custom smoothing code.
                    area.spaces.active.image=t.masks[i].image
                    bpy.ops.brush.asset_activate(asset_library_type='ESSENTIALS', relative_asset_identifier='brushes/essentials_brushes-mesh_texture.blend/Brush/Blur')
                    bpy.ops.paint.image_paint(stroke=stroke)
                    smoothed=lj.pixels(t.masks[i].image)
                    smooth_delta=float(np.max(np.abs(smoothed-painted)))
                    assert smooth_delta>0
                    lj.queue(obj); lj.tick()
                    np.testing.assert_array_equal(lj.pixels(t.combined)[:,i],smoothed[:,0])
                    results.append(dict(resolution=resolution,channel='RGBA'[i],paint_delta=delta,smooth_delta=smooth_delta,undo=True,redo=True))
                    bpy.ops.brush.asset_activate(asset_library_type='ESSENTIALS', relative_asset_identifier='brushes/essentials_brushes-mesh_texture.blend/Brush/Paint Hard')
            # Global operator undo must also restore direct pixel fills.
            t.active_mask='3'
            lj.save_pre()
            before=lj.pixels(t.masks[3].image).copy()
            bpy.ops.ed.undo_push(message='Before fill')
            bpy.ops.lj_terrain.action(action='FILL')
            print('FILL',t.status,lj.pixels(t.masks[3].image).min(axis=0),lj.pixels(t.masks[3].image).max(axis=0),flush=True)
            assert np.min(lj.pixels(t.masks[3].image)[:,:3]) == 1
            bpy.ops.ed.undo()
            obj=bpy.data.objects['NativeTest'];t=obj.lj_terrain
            np.testing.assert_array_equal(lj.pixels(t.masks[3].image),before)
            bpy.ops.ed.redo()
            obj=bpy.data.objects['NativeTest'];t=obj.lj_terrain
            assert np.min(lj.pixels(t.masks[3].image)[:,:3]) == 1
            results.append({'fill_global_undo_redo':True})
            bpy.ops.lj_terrain.action(action='CLEAR')
            assert np.max(lj.pixels(t.masks[3].image)[:,:3]) == 0
            bpy.ops.ed.undo()
            obj=bpy.data.objects['NativeTest'];t=obj.lj_terrain
            assert np.min(lj.pixels(t.masks[3].image)[:,:3]) == 1
            lj.tick()
            results.append({'clear_undo':True})
            # Same action from the actual sidebar's editor type uses a short
            # temporary image-editor context, then restores the viewport.
            area.type='VIEW_3D'
        with bpy.context.temp_override(area=area):
            bpy.ops.lj_terrain.action(action='CLEAR')
        bpy.app.timers.register(check_sidebar,first_interval=1)
        return
    except Exception:
        traceback.print_exc()
        bpy.ops.wm.quit_blender()

def check_sidebar():
    try:
        obj=bpy.data.objects['NativeTest']
        assert np.max(lj.pixels(obj.lj_terrain.masks[3].image)[:,:3])==0
        assert any(a.type=='VIEW_3D' for a in bpy.context.screen.areas)
        assert not lj._fill_timers
        results.append({'sidebar_native_clear':True})
        (ROOT/'tests'/'native-results.json').write_text(json.dumps(results,indent=2))
        print('NATIVE TESTS PASSED',flush=True)
    except Exception:
        traceback.print_exc()
    finally:
        bpy.ops.wm.quit_blender()

bpy.app.timers.register(prepare,first_interval=2)
