import bpy
import traceback
def run():
    import bpy
    from pathlib import Path
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import lj_terrain_tools as lj
    lj.register()
    bpy.ops.mesh.primitive_plane_add()
    obj = bpy.context.object
    obj.lj_terrain.resolution = '1024'
    lj.setup(obj)
    area = next(a for a in bpy.context.screen.areas if a.type == 'VIEW_3D')
    area.type = 'IMAGE_EDITOR'
    area.spaces.active.mode = 'PAINT'
    area.spaces.active.image = obj.lj_terrain.masks[0].image
    region = next(r for r in area.regions if r.type == 'WINDOW')
    with bpy.context.temp_override(area=area, region=region):
        print('ASSET', bpy.ops.brush.asset_activate(asset_library_type='ESSENTIALS', relative_asset_identifier='brushes/essentials_brushes-mesh_texture.blend/Brush/Paint Hard'), flush=True)
        print('BRUSH', bpy.context.tool_settings.image_paint.brush, flush=True)
        brush = bpy.context.tool_settings.image_paint.brush
        if brush:
            brush.color = (1,1,1)
            brush.strength = 1
            brush.size = 60
        print('STROKE PROPS', bpy.types.OperatorStrokeElement.bl_rna.properties.keys(), flush=True)
        bpy.ops.image.view_all()
        bpy.ops.ed.undo_push(message='Before native paint')
        print('BEFORE', lj.pixels(area.spaces.active.image).max(axis=0), flush=True)
        stroke = [dict(name='test', mouse=(area.width/2, area.height/2), mouse_event=(area.width/2, area.height/2), pressure=1, size=60, time=0, is_start=True, x_tilt=0, y_tilt=0, location=(0,0,0))]
        print('PAINT', bpy.ops.paint.image_paint(stroke=stroke), flush=True)
        print('AFTER', lj.pixels(area.spaces.active.image).max(axis=0), flush=True)
    
    
    bpy.ops.wm.quit_blender()
bpy.app.timers.register(run, first_interval=3)

