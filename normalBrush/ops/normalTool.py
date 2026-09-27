# This file is part of the Kitfox Normal Brush distribution (https://github.com/blackears/blenderNormalBrush).
# Copyright (c) 2021 Mark McKay
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.


import bpy
import bpy.utils.previews
import os
import gpu
import mathutils
import math
import traceback
import numpy as np

from mathutils.bvhtree import BVHTree
from gpu_extras.batch import batch_for_shader
from bpy_extras import view3d_utils


def ray_cast(context, ray_origin, view_vector):
    depsgraph = context.evaluated_depsgraph_get()
    return context.scene.ray_cast(depsgraph, ray_origin, view_vector)


def redraw_all_viewports(context):
    screen = context.window.screen if context.window else context.screen
    if screen is None:
        return
    for area in screen.areas: # iterate through areas in current screen
        if area.type == 'VIEW_3D':
            area.tag_redraw()


#Find the main 3D viewport region under the mouse.  Operators launched from the
#sidebar run with the sidebar as their region, so event.mouse_region_x cannot be
#trusted.  Returns (region, region_3d, mouse_pos_in_region) or (None, None, None)
#if the mouse is not over a viewport (eg, it is over the sidebar or header).
def find_view3d_region(context, event, region = None):
    mx, my = event.mouse_x, event.mouse_y

    if region is not None:
        return region, region.data, (mx - region.x, my - region.y)

    window = context.window
    if window is None:
        return None, None, None

    for area in window.screen.areas:
        if area.type != 'VIEW_3D':
            continue
        if not (area.x <= mx < area.x + area.width and area.y <= my < area.y + area.height):
            continue

        window_region = None
        for r in area.regions:
            if not (r.x <= mx < r.x + r.width and r.y <= my < r.y + r.height):
                continue
            if r.type == 'WINDOW':
                window_region = r
            elif r.width > 1 and r.height > 1:
                #Over a panel that overlaps the viewport
                return None, None, None

        if window_region is not None:
            return window_region, window_region.data, (mx - window_region.x, my - window_region.y)

    return None, None, None


def view_ray(region, rv3d, mouse_pos):
    view_vector = view3d_utils.region_2d_to_vector_3d(region, rv3d, mouse_pos)
    ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, mouse_pos)
    return ray_origin, view_vector


class NormalToolSettings(bpy.types.PropertyGroup):
    brush_type : bpy.props.EnumProperty(
        items=(
            ('COMB', "Comb", "Normals point in the direction that the brush moves"),
            ('FIXED', "Fixed", "Normals are in a fixed direction"),
            ('ATTRACT', "Attract", "Normals point toward target object"),
            ('REPEL', "Repel", "Normals point away from target object"),
            ('SMOOTH', "Smooth", "Average the normal direction under the brush"),
            ('VERTEX', "Vertex", "Get normal values from mesh vertices")
        ),
        default='COMB'
    )

    radius : bpy.props.FloatProperty(
        name="Radius",
        description="Radius of brush",
        default = 1,
        min = 0,
        soft_max = 4
    )

    strength : bpy.props.FloatProperty(
        name="Strength",
        description="Amount to adjust mesh normal",
        default = 1,
        min = 0,
        max = 1
    )

    use_pressure : bpy.props.BoolProperty(
        name="Pen Pressure",
        description="If true, pen pressure is used to adjust strength",
        default = True
    )

    normal_length : bpy.props.FloatProperty(
        name = "Normal Length",
        description="Display length of normal",
        default = 1,
        min=0,
        soft_max = 1
    )

    selected_verts_only : bpy.props.BoolProperty(
        name = "Selected Vertices Only",
        description = "If true, affect only selected vertices",
        default = False
    )

    selected_faces_only : bpy.props.BoolProperty(
        name = "Selected Faces Only",
        description = "If true, affect only selected faces",
        default = False
    )

    normal : bpy.props.FloatVectorProperty(
        name = "Normal",
        description = "Direction of normal in Fixed mode",
        default = (1, 0, 0),
        subtype = "DIRECTION"
    )

    normal_exact : bpy.props.BoolProperty(
        name = "Exact normal",
        description = "Display normal as exact coordinates",
        default = True
    )

    front_faces_only : bpy.props.BoolProperty(
        name = "Front Faces Only",
        description = "Only affect normals on front facing faces",
        default = True
    )

    target : bpy.props.PointerProperty(
        name = "Target",
        description = "Object Attract and Repel mode reference",
        type = bpy.types.Object
    )

    symmetry_x : bpy.props.BoolProperty(
        name="X",
        description = "Symmetry across the object's local X axis",
        default = False
    )

    symmetry_y : bpy.props.BoolProperty(
        name = "Y",
        description = "Symmetry across the object's local Y axis",
        default = False
    )

    symmetry_z : bpy.props.BoolProperty(
        name = "Z",
        description = "Symmetry across the object's local Z axis",
        default = False
    )

    show_normals : bpy.props.BoolProperty(
        name = "Show Normals",
        description = "Display normal lines while the tool is running",
        default = True,
        update = lambda self, context: redraw_all_viewports(context)
    )

    occlude_normals : bpy.props.BoolProperty(
        name = "Occlude",
        description = "Hide normal lines that are blocked by faces in front of them",
        default = False,
        update = lambda self, context: redraw_all_viewports(context)
    )

    use_shape_keys : bpy.props.BoolProperty(
        name="Use Shape Keys",
        description = "Use vertex positions of the active shape key for brushing and display",
        default = False
    )


#---------------------------
#Vectorized brush math

def normalize_rows(v):
    lengths = np.linalg.norm(v, axis=1)
    lengths[lengths < 1e-12] = 1
    return v / lengths[:, None]


#Rotate each normal in a toward the matching direction in b by fraction t of the angle between them
def slerp_normals(a, b, t):
    a = normalize_rows(a)
    b = normalize_rows(b)
    dot = np.clip(np.einsum('ij,ij->i', a, b), -1, 1)
    theta = np.arccos(dot)

    perp = b - a * dot[:, None]
    perp_len = np.linalg.norm(perp, axis=1)

    #When a and b are parallel or opposite any perpendicular axis will do
    degenerate = perp_len < 1e-8
    if degenerate.any():
        ad = a[degenerate]
        helper = np.where(np.abs(ad[:, 0:1]) < .9, np.array((1., 0, 0)), np.array((0., 1, 0)))
        p = np.cross(ad, helper)
        perp[degenerate] = p
        perp_len[degenerate] = np.linalg.norm(p, axis=1)

    perp /= perp_len[:, None]
    angle = theta * np.clip(t, 0, 1)
    return a * np.cos(angle)[:, None] + perp * np.sin(angle)[:, None]


def mirror_signs(sym_x, sym_y, sym_z):
    signs = [np.array((1., 1., 1.))]
    for axis, enabled in enumerate((sym_x, sym_y, sym_z)):
        if enabled:
            flip = np.ones(3)
            flip[axis] = -1
            signs = signs + [s * flip for s in signs]
    return signs


def foreach_array(collection, prop, count, dtype, components = 1):
    arr = np.empty(count * components, dtype=dtype)
    if count > 0:
        collection.foreach_get(prop, arr)
    if components > 1:
        arr.shape = (-1, components)
    return arr


def mesh_vertex_coords(obj, use_shape_keys):
    mesh = obj.data
    source = mesh.vertices
    if use_shape_keys and obj.active_shape_key:
        source = obj.active_shape_key.data
    return foreach_array(source, "co", len(mesh.vertices), np.float32, 3)


def mesh_corner_normals(mesh):
    return foreach_array(mesh.corner_normals, "vector", len(mesh.loops), np.float32, 3)


def geometry_key(obj, use_shape_keys):
    mesh = obj.data
    return (
        mesh.as_pointer(),
        tuple(v for row in obj.matrix_world for v in row),
        use_shape_keys,
        obj.active_shape_key_index,
        len(mesh.vertices),
        len(mesh.loops)
    )


#Mesh data used while brushing.  Geometry is read once and can be reused across strokes.
#
#Setting tangent space custom normals with normals_split_custom_set() is slow, so while a
#stroke is in progress the normals are written directly to a 'free' float custom_normal
#attribute, which is nearly instant.  commit() converts them back to regular custom normals
#(which follow mesh deformation) when the stroke ends.
class MeshStrokeData:
    def __init__(self, obj, use_shape_keys):
        mesh = obj.data
        self.obj = obj
        self.mesh = mesh
        self.key = geometry_key(obj, use_shape_keys)
        self.normals = None
        self.was_free = False
        self.bvh = None

        num_verts = len(mesh.vertices)
        num_loops = len(mesh.loops)
        num_polys = len(mesh.polygons)

        self.corner_verts = foreach_array(mesh.loops, "vertex_index", num_loops, np.int32)
        loop_totals = foreach_array(mesh.polygons, "loop_total", num_polys, np.int32)
        self.corner_polys = np.repeat(np.arange(num_polys, dtype=np.int32), loop_totals)

        self.coords = mesh_vertex_coords(obj, use_shape_keys).astype(np.float64)
        self.vert_normals = foreach_array(mesh.vertex_normals, "vector", num_verts, np.float32, 3).astype(np.float64)
        self.poly_normals = foreach_array(mesh.polygon_normals, "vector", num_polys, np.float32, 3).astype(np.float64)
        self.vert_select = foreach_array(mesh.vertices, "select", num_verts, bool)
        self.poly_select = foreach_array(mesh.polygons, "select", num_polys, bool)

        mw = np.array(obj.matrix_world, dtype=np.float64)
        self.m3 = mw[:3, :3]
        self.trans = mw[:3, 3]
        self.m3_inv = np.linalg.pinv(self.m3)

        self.coords_world = self.coords @ self.m3.T + self.trans

    #Ray cast in world space against this object.  Returns (distance, location, normal) or None.
    #Used while painting because scene.ray_cast() rebuilds its acceleration structure every time the mesh is updated.
    def ray_cast(self, depsgraph, origin, direction):
        if self.bvh is None:
            self.bvh = BVHTree.FromObject(self.obj, depsgraph)
        mw = self.obj.matrix_world
        inv = mw.inverted_safe()
        location, normal, index, dist = self.bvh.ray_cast(inv @ origin, inv.to_3x3() @ direction)
        if location is None:
            return None
        location = mw @ location
        normal = (inv.to_3x3().transposed() @ normal).normalized()
        return ((location - origin).length, location, normal, index)

    #Start a stroke: switch the mesh to free normals initialized to the current normals
    def begin(self):
        mesh = self.mesh
        self.normals = mesh_corner_normals(mesh).astype(np.float64)

        attr = mesh.attributes.get("custom_normal")
        self.was_free = attr is not None and attr.data_type == 'FLOAT_VECTOR' and attr.domain == 'CORNER'
        if not self.was_free:
            if attr is not None:
                mesh.attributes.remove(attr)
            mesh.attributes.new("custom_normal", 'FLOAT_VECTOR', 'CORNER')
            self.write()

    def write(self):
        self.mesh.attributes["custom_normal"].data.foreach_set("vector", self.normals.astype(np.float32).ravel())
        self.mesh.update()

    #End a stroke: convert back to tangent space custom normals
    def commit(self):
        if self.normals is None:
            return
        mesh = self.mesh
        if not self.was_free:
            attr = mesh.attributes.get("custom_normal")
            if attr is not None:
                mesh.attributes.remove(attr)
            #A plain list is much faster to pass to the API than a numpy array
            mesh.normals_split_custom_set(self.normals.tolist())
        self.normals = None

    #Row vectors: world direction -> local normal is (M^T) n, so n @ M
    def world_to_local_normal(self, n):
        return n @ self.m3

    #Row vectors: local normal -> world normal is (M^-1)^T n, so n @ M^-1
    def local_to_world_normal(self, n):
        return n @ self.m3_inv


#Apply one dab of the brush to a mesh.
#  location - brush center in world space
#  eye - (is_perspective, view origin, view direction) in world space
#  comb_dir - world space direction of stroke motion (COMB only)
#Returns True if the mesh normals were changed
def apply_dab(data, settings, location, eye, pressure, comb_dir):
    radius = settings.radius
    atten = settings.strength
    if settings.use_pressure:
        atten *= pressure
    if radius <= 0 or atten <= 0 or len(data.corner_verts) == 0:
        return False

    brush_type = settings.brush_type

    base_dir = None
    target_pos = None
    if brush_type == "FIXED":
        base_dir = data.world_to_local_normal(np.array(settings.normal, dtype=np.float64))
    elif brush_type == "COMB":
        if comb_dir is None:
            return False
        base_dir = data.world_to_local_normal(np.array(comb_dir, dtype=np.float64))
    elif brush_type in ("ATTRACT", "REPEL"):
        if settings.target is None:
            return False
        target_pos = np.array(settings.target.matrix_world.translation, dtype=np.float64)

    if base_dir is not None:
        length = np.linalg.norm(base_dir)
        if length < 1e-12:
            return False
        base_dir = base_dir / length

    is_persp, view_origin, view_dir = eye
    view_origin = np.array(view_origin, dtype=np.float64)
    view_dir = np.array(view_dir, dtype=np.float64)

    if data.normals is None:
        data.begin()
    cur = data.normals
    accum = np.zeros_like(cur)
    count = np.zeros(len(cur), dtype=np.int32)

    loc_local = data.m3_inv @ (np.array(location, dtype=np.float64) - data.trans)

    for sign in mirror_signs(settings.symmetry_x, settings.symmetry_y, settings.symmetry_z):
        center = data.m3 @ (loc_local * sign) + data.trans
        falloff = 1 - np.linalg.norm(data.coords_world - center, axis=1) / radius
        verts_inside = falloff > 0
        if not verts_inside.any():
            continue

        idx = np.flatnonzero(verts_inside[data.corner_verts])
        cv = data.corner_verts[idx]
        weights = falloff[cv]

        smooth_dir = None
        if brush_type == "SMOOTH":
            smooth_dir = (cur[idx] * weights[:, None]).sum(axis=0)
            length = np.linalg.norm(smooth_dir)
            if length < 1e-12:
                continue
            smooth_dir /= length

        keep = np.ones(len(idx), dtype=bool)
        if settings.selected_faces_only:
            keep &= data.poly_select[data.corner_polys[idx]]
        if settings.selected_verts_only:
            keep &= data.vert_select[cv]
        if settings.front_faces_only:
            #Test the face on the side of the stroke this mirror copy is reflected from
            face_normals = data.local_to_world_normal(data.poly_normals[data.corner_polys[idx]] * sign)
            if is_persp:
                view_dirs = ((data.coords[cv] * sign) @ data.m3.T + data.trans) - view_origin
            else:
                view_dirs = view_dir[None, :]
            keep &= np.einsum('ij,ij->i', face_normals, np.broadcast_to(view_dirs, face_normals.shape)) <= 0

        idx = idx[keep]
        if len(idx) == 0:
            continue
        cv = data.corner_verts[idx]
        weights = falloff[cv]

        if brush_type in ("FIXED", "COMB"):
            target = np.broadcast_to(base_dir * sign, (len(idx), 3))
        elif brush_type in ("ATTRACT", "REPEL"):
            offset = target_pos - data.coords_world[cv]
            if brush_type == "REPEL":
                offset = -offset
            target = data.world_to_local_normal(offset)
        elif brush_type == "SMOOTH":
            target = np.broadcast_to(smooth_dir, (len(idx), 3))
        else: #VERTEX
            target = data.vert_normals[cv]

        valid = np.linalg.norm(target, axis=1) > 1e-12
        idx = idx[valid]
        if len(idx) == 0:
            continue

        accum[idx] += slerp_normals(cur[idx], target[valid], weights[valid] * atten)
        count[idx] += 1

    changed = count > 0
    if not changed.any():
        return False

    cur[changed] = normalize_rows(accum[changed])
    data.write()
    return True


#---------------------------
#Undo snapshots.  Only the attributes that define the custom normals are saved.

NORMAL_ATTRIBUTES = ("custom_normal", "sharp_edge", "sharp_face")

ATTRIBUTE_FOREACH = {
    'INT16_2D': ("value", 2, np.int16),
    'BOOLEAN': ("value", 1, bool),
    'FLOAT_VECTOR': ("vector", 3, np.float32),
}

def snapshot_normals(mesh):
    snap = {}
    for name in NORMAL_ATTRIBUTES:
        attr = mesh.attributes.get(name)
        if attr is None:
            snap[name] = None
            continue
        info = ATTRIBUTE_FOREACH.get(attr.data_type)
        if info is None:
            #Unknown format - leave this attribute alone
            continue
        prop, components, dtype = info
        arr = np.empty(len(attr.data) * components, dtype=dtype)
        attr.data.foreach_get(prop, arr)
        snap[name] = (attr.domain, attr.data_type, arr)
    return snap


def restore_normals(mesh, snap):
    for name, saved in snap.items():
        attr = mesh.attributes.get(name)
        if saved is None:
            if attr is not None:
                mesh.attributes.remove(attr)
            continue

        domain, data_type, arr = saved
        if attr is not None and (attr.domain != domain or attr.data_type != data_type):
            mesh.attributes.remove(attr)
            attr = None
        if attr is None:
            attr = mesh.attributes.new(name, data_type, domain)

        prop, components, dtype = ATTRIBUTE_FOREACH[data_type]
        if len(attr.data) * components == len(arr):
            attr.data.foreach_set(prop, arr)
    mesh.update()


#---------------------------
#Drawing

circleSegs = 64
coordsCircle = [(math.sin(((2 * math.pi * i) / circleSegs)), math.cos((math.pi * 2 * i) / circleSegs), 0) for i in range(circleSegs + 1)]

coordsNormal = [(0, 0, 0), (0, 0, 1)]

vecZ = mathutils.Vector((0, 0, 1))
vecX = mathutils.Vector((1, 0, 0))

shader = None
batchLine = None
batchCircle = None

#Create GPU resources on first draw rather than at import time
def ensure_gpu_resources():
    global shader, batchLine, batchCircle
    if shader is None:
        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        batchLine = batch_for_shader(shader, 'LINES', {"pos": coordsNormal})
        batchCircle = batch_for_shader(shader, 'LINE_STRIP', {"pos": coordsCircle})


#Find matrix that will rotate Z axis to point along normal
#coord - point in world space
#normal - normal in world space
def calc_vertex_transform_world(pos, norm):
    norm = mathutils.Vector(norm).normalized()
    axis = norm.cross(vecZ)
    if axis.length_squared < .0001:
        axis = mathutils.Vector(vecX)
    else:
        axis.normalize()
    angle = -math.acos(max(-1, min(1, norm.dot(vecZ))))

    quat = mathutils.Quaternion(axis, angle)
    mR = quat.to_matrix()
    mR.resize_4x4()

    mT = mathutils.Matrix.Translation(pos)

    m = mT @ mR
    return m


#Start point of each corner's normal line.  Only changes when the geometry does.
def normal_line_starts(obj, use_shape_keys):
    mesh = obj.data
    coords = mesh_vertex_coords(obj, use_shape_keys)
    corner_verts = foreach_array(mesh.loops, "vertex_index", len(mesh.loops), np.int32)
    return coords[corner_verts]


def build_normals_batch(starts, corner_normals, normal_length):
    if len(starts) == 0:
        return None

    lines = np.empty((len(starts) * 2, 3), dtype=np.float32)
    lines[0::2] = starts
    lines[1::2] = starts + corner_normals * normal_length

    return batch_for_shader(shader, 'LINES', {"pos": lines})


#Matrix that moves geometry slightly toward the viewer so lines starting on a surface
#are not hidden by that surface when depth testing
def depth_bias_matrix(rv3d, amount = .001):
    view_inv = rv3d.view_matrix.inverted()
    if rv3d.is_perspective:
        eye = view_inv.translation
        return mathutils.Matrix.Translation(eye) @ mathutils.Matrix.Scale(1 - amount, 4) @ mathutils.Matrix.Translation(-eye)
    toward_viewer = view_inv.to_3x3() @ mathutils.Vector((0, 0, 1))
    return mathutils.Matrix.Translation(toward_viewer * rv3d.view_distance * amount)


#The running Normal Tool, so the panel button can act as a start/stop toggle
_active_tool = None
_draw_handle = None

def active_tool():
    global _active_tool
    if _active_tool is not None:
        try:
            _active_tool.bl_idname
        except ReferenceError:
            _active_tool = None
    return _active_tool


def remove_draw_handler():
    global _draw_handle
    if _draw_handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_draw_handle, 'WINDOW')
        _draw_handle = None


#Loading a file ends modal operators without letting them clean up
@bpy.app.handlers.persistent
def on_load_pre(*args):
    global _active_tool
    remove_draw_handler()
    _active_tool = None


def draw_callback(self, context):
    try:
        self.draw(bpy.context)
    except ReferenceError:
        pass


#---------------------------

class ModalDrawOperator(bpy.types.Operator):
    """Start or stop the normal brush.  Stopping keeps your changes"""
    bl_idname = "kitfox.normal_tool"
    bl_label = "Normal Tool Kitfox"
    bl_options = {"REGISTER", "UNDO"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.dragging = False

        self.cursor_pos = None
        self.cursor_normal = None
        self.show_cursor = False

        self.history = []
        self.history_idx = -1
        self.history_limit = 32
        self.original = {}

        self.stroke_data = []
        self.stroke_region = None
        self.last_trail_pos = None
        self.comb_dir = None
        self.geometry_cache = {}

        self.mesh_versions = {}
        self.draw_cache = {}
        self.stop_requested = False
        self._stop_timer = None

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    #---------------------------
    #History

    def selected_meshes(self, context):
        return [obj for obj in context.selected_objects if obj.type == 'MESH']

    def mark_changed(self, obj):
        self.mesh_versions[obj.name] = self.mesh_versions.get(obj.name, 0) + 1

    #Make sure every selected mesh has an original state recorded so it can be restored
    def track_objects(self, context):
        for obj in self.selected_meshes(context):
            if obj not in self.original:
                snap = snapshot_normals(obj.data)
                self.original[obj] = snap
                for entry in self.history:
                    entry.setdefault(obj, snap)

    def history_snapshot(self):
        entry = {obj: snapshot_normals(obj.data) for obj in self.original}

        #Remove all history past current pointer
        del self.history[self.history_idx + 1:]
        self.history.append(entry)

        #Remove oldest element if history queue is maxed out
        if len(self.history) > self.history_limit:
            self.history.pop(0)

        self.history_idx = len(self.history) - 1

    def restore_entry(self, entry):
        for obj, snap in entry.items():
            try:
                restore_normals(obj.data, snap)
                self.mark_changed(obj)
            except ReferenceError:
                pass

    def history_undo(self):
        if self.history_idx > 0:
            self.history_idx -= 1
            self.restore_entry(self.history[self.history_idx])

    def history_redo(self):
        if self.history_idx < len(self.history) - 1:
            self.history_idx += 1
            self.restore_entry(self.history[self.history_idx])

    def history_clear(self):
        self.history = []
        self.history_idx = -1
        self.original = {}

    #---------------------------
    #Brush

    def eye_info(self, region, rv3d, mouse_pos):
        ray_origin, view_vector = view_ray(region, rv3d, mouse_pos)
        if rv3d.is_perspective:
            origin = rv3d.view_matrix.inverted().translation
        else:
            origin = ray_origin
        return (rv3d.is_perspective, origin, view_vector)

    def begin_stroke(self, context, region):
        self.track_objects(context)
        use_shape_keys = context.scene.normal_brush_props.use_shape_keys

        self.stroke_data = []
        for obj in self.selected_meshes(context):
            if len(obj.data.loops) == 0:
                continue
            data = self.geometry_cache.get(obj)
            if data is None or data.key != geometry_key(obj, use_shape_keys):
                data = MeshStrokeData(obj, use_shape_keys)
                self.geometry_cache[obj] = data
            data.begin()
            self.stroke_data.append(data)

        self.stroke_region = region
        self.last_trail_pos = None
        self.comb_dir = None
        self.dragging = True

    def commit_stroke(self):
        for data in self.stroke_data:
            try:
                data.commit()
                self.mark_changed(data.obj)
            except ReferenceError:
                pass
        self.stroke_data = []
        self.dragging = False
        self.stroke_region = None

    def end_stroke(self):
        self.commit_stroke()
        self.history_snapshot()

    #hit - result of ray_cast() under the mouse
    def dab_brush(self, context, event, region, rv3d, mouse_pos, hit):
        settings = context.scene.normal_brush_props
        result, location = hit[0], hit[1]

        if not result:
            self.last_trail_pos = None
            self.comb_dir = None
            return

        #Track brush motion for comb.  Very small moves are ignored so that slow strokes still have a direction.
        if self.last_trail_pos is None:
            self.last_trail_pos = location.copy()
        else:
            step = location - self.last_trail_pos
            if step.length > max(settings.radius * .05, 1e-5):
                self.comb_dir = step
                self.last_trail_pos = location.copy()

        pressure = event.pressure if event.pressure > 0 else 1
        eye = self.eye_info(region, rv3d, mouse_pos)

        for data in self.stroke_data:
            if apply_dab(data, settings, location, eye, pressure, self.comb_dir):
                self.mark_changed(data.obj)

    #Ray cast against only the meshes being painted
    def stroke_ray_cast(self, context, ray_origin, view_vector):
        depsgraph = context.evaluated_depsgraph_get()
        best = None
        best_obj = None
        for data in self.stroke_data:
            hit = data.ray_cast(depsgraph, ray_origin, view_vector)
            if hit is not None and (best is None or hit[0] < best[0]):
                best = hit
                best_obj = data.obj
        if best is None:
            return (False, None, None, None, None, None)
        return (True, best[1], best[2], best[3], best_obj, best_obj.matrix_world)

    #Returns the ray_cast() result under the mouse
    def update_cursor(self, context, region, rv3d, mouse_pos):
        if region is None:
            self.show_cursor = False
            return (False, None, None, None, None, None)

        ray_origin, view_vector = view_ray(region, rv3d, mouse_pos)
        if self.dragging:
            hit = self.stroke_ray_cast(context, ray_origin, view_vector)
        else:
            hit = ray_cast(context, ray_origin, view_vector)
        result, location, normal = hit[0], hit[1], hit[2]

        if result:
            self.show_cursor = True
            self.cursor_pos = location
            self.cursor_normal = normal
        else:
            self.show_cursor = False
        return hit

    #---------------------------
    #Drawing

    def draw(self, context):
        props = context.scene.normal_brush_props

        ensure_gpu_resources()
        shader.bind()

        #Draw cursor
        if self.show_cursor:
            m = calc_vertex_transform_world(self.cursor_pos, self.cursor_normal)
            m = m @ mathutils.Matrix.Scale(props.radius, 4)

            #Tangent to mesh
            gpu.matrix.push()
            gpu.matrix.multiply_matrix(m)
            shader.uniform_float("color", (1, 0, 1, 1))
            batchCircle.draw(shader)
            gpu.matrix.pop()

            #Brush normal direction
            if props.brush_type == "FIXED":
                gpu.matrix.push()
                m = calc_vertex_transform_world(self.cursor_pos, props.normal)
                gpu.matrix.multiply_matrix(m)
                shader.uniform_float("color", (0, 1, 1, 1))
                batchLine.draw(shader)
                gpu.matrix.pop()

        if not props.show_normals:
            self.draw_cache = {}
            return

        #Draw editable normals.  Batches are rebuilt only when the mesh or display settings change.
        shader.uniform_float("color", (1, 1, 0, 1))

        bias = None
        if props.occlude_normals:
            gpu.state.depth_test_set('LESS_EQUAL')
            bias = depth_bias_matrix(context.region_data)

        stroke_normals = {data.obj.name: data.normals for data in self.stroke_data}

        cache = {}
        for obj in context.selected_objects:
            if obj.type != 'MESH':
                continue
            mesh = obj.data
            geo_key = (
                mesh.as_pointer(),
                props.use_shape_keys,
                obj.active_shape_key_index,
                len(mesh.vertices),
                len(mesh.loops)
            )
            key = (geo_key, self.mesh_versions.get(obj.name, 0), props.normal_length)

            cached = self.draw_cache.get(obj.name)
            if cached is not None and cached[0] == key:
                starts, batch = cached[1], cached[2]
            else:
                if cached is not None and cached[0][0] == geo_key:
                    starts = cached[1]
                else:
                    starts = normal_line_starts(obj, props.use_shape_keys)
                normals = stroke_normals.get(obj.name)
                if normals is None:
                    normals = mesh_corner_normals(mesh)
                batch = build_normals_batch(starts, normals, props.normal_length)
            cache[obj.name] = (key, starts, batch)

            if batch is None:
                continue

            gpu.matrix.push()
            gpu.matrix.multiply_matrix(obj.matrix_world if bias is None else bias @ obj.matrix_world)
            batch.draw(shader)
            gpu.matrix.pop()

        if bias is not None:
            gpu.state.depth_test_set('NONE')

        self.draw_cache = cache

    #---------------------------

    def finish(self, context):
        global _active_tool
        if self.dragging:
            self.commit_stroke()
        remove_draw_handler()
        if self._stop_timer is not None:
            context.window_manager.event_timer_remove(self._stop_timer)
            self._stop_timer = None
        _active_tool = None
        context.window.cursor_modal_restore()
        self.draw_cache = {}
        self.geometry_cache = {}
        redraw_all_viewports(context)

    def modal(self, context, event):
        try:
            return self.handle_event(context, event)
        except Exception:
            traceback.print_exc()
            self.finish(context)
            self.history_clear()
            self.report({'ERROR'}, "Normal Tool stopped due to an error. See the system console for details.")
            return {'CANCELLED'}

    def handle_event(self, context, event):
        #Panel button was pressed again
        if self.stop_requested:
            self.finish(context)
            self.history_clear()
            return {'FINISHED'}

        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'TRACKPADPAN', 'TRACKPADZOOM', 'MOUSEROTATE', 'NDOF_MOTION'}:
            # allow navigation
            return {'PASS_THROUGH'}

        elif event.type == 'MOUSEMOVE':
            region, rv3d, mouse_pos = find_view3d_region(context, event, self.stroke_region)

            if region is None:
                context.window.cursor_modal_restore()
            else:
                context.window.cursor_modal_set("PAINT_BRUSH")

            hit = self.update_cursor(context, region, rv3d, mouse_pos)

            if self.dragging:
                self.dab_brush(context, event, region, rv3d, mouse_pos, hit)
                redraw_all_viewports(context)
                return {'RUNNING_MODAL'}

            redraw_all_viewports(context)
            return {'PASS_THROUGH'}

        elif event.type == 'LEFTMOUSE':
            if event.value == 'PRESS':
                region, rv3d, mouse_pos = find_view3d_region(context, event)
                if region is None:
                    return {'PASS_THROUGH'}

                hit = self.update_cursor(context, region, rv3d, mouse_pos)
                result, object = hit[0], hit[4]
                if not result or object is None or not object.select_get():
                    return {'PASS_THROUGH'}

                self.begin_stroke(context, region)
                self.dab_brush(context, event, region, rv3d, mouse_pos, hit)
                redraw_all_viewports(context)
                return {'RUNNING_MODAL'}

            elif event.value == 'RELEASE':
                if self.dragging:
                    self.end_stroke()
                    return {'RUNNING_MODAL'}
                return {'PASS_THROUGH'}

            return {'RUNNING_MODAL' if self.dragging else 'PASS_THROUGH'}

        elif event.type == 'Z' and (event.ctrl or event.oskey):
            if event.value == 'PRESS' and not self.dragging:
                if event.shift:
                    self.history_redo()
                else:
                    self.history_undo()
                redraw_all_viewports(context)
            return {'RUNNING_MODAL'}

        elif event.type in {'RET', 'NUMPAD_ENTER'}:
            if event.value == 'RELEASE':
                self.finish(context)
                self.history_clear()
                return {'FINISHED'}
            return {'RUNNING_MODAL'}

        elif event.type in {'PAGE_UP', 'RIGHT_BRACKET'}:
            if event.value == "PRESS":
                context.scene.normal_brush_props.radius += .1
                redraw_all_viewports(context)
            return {'RUNNING_MODAL'}

        elif event.type in {'PAGE_DOWN', 'LEFT_BRACKET'}:
            if event.value == "PRESS":
                props = context.scene.normal_brush_props
                props.radius = max(props.radius - .1, .1)
                redraw_all_viewports(context)
            return {'RUNNING_MODAL'}

        elif event.type in {'RIGHTMOUSE', 'ESC'}:
            if event.value == 'RELEASE':
                self.finish(context)
                self.restore_entry(self.original)
                self.history_clear()
                return {'CANCELLED'}
            return {'RUNNING_MODAL'}

        return {'PASS_THROUGH'}

    def invoke(self, context, event):
        global _active_tool, _draw_handle

        #Already running: this press of the button stops the tool.  A timer wakes its modal handler.
        tool = active_tool()
        if tool is not None:
            tool.stop_requested = True
            if tool._stop_timer is None:
                tool._stop_timer = context.window_manager.event_timer_add(.01, window = context.window)
            return {'CANCELLED'}

        if context.area is None or context.area.type != 'VIEW_3D':
            self.report({'WARNING'}, "View3D not found, cannot run operator")
            return {'CANCELLED'}

        self.history_clear()
        self.track_objects(context)
        self.history_snapshot()

        # draw in view space with 'POST_VIEW'
        remove_draw_handler()
        _draw_handle = bpy.types.SpaceView3D.draw_handler_add(draw_callback, (self, context), 'WINDOW', 'POST_VIEW')
        _active_tool = self

        context.window.cursor_modal_set("PAINT_BRUSH")
        redraw_all_viewports(context)

        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

#---------------------------

class NormalPickerOperator(bpy.types.Operator):
    """Pick normal"""
    bl_idname = "kitfox.nt_pick_normal"
    bl_label = "Pick Normal"
    bl_options = {"REGISTER", "UNDO"}

    def pick(self, context, event):
        region, rv3d, mouse_pos = find_view3d_region(context, event)
        if region is None:
            return False

        ray_origin, view_vector = view_ray(region, rv3d, mouse_pos)
        result, location, normal, index, object, matrix = ray_cast(context, ray_origin, view_vector)

        if result:
            context.scene.normal_brush_props.normal = normal
            redraw_all_viewports(context)
        return result

    def modal(self, context, event):
        if event.type == 'MOUSEMOVE':
            return {'PASS_THROUGH'}

        elif event.type == 'LEFTMOUSE':
            if event.value == 'PRESS':
                if self.pick(context, event):
                    context.window.cursor_modal_restore()
                    return {'FINISHED'}
            return {'RUNNING_MODAL'}

        elif event.type in {'RIGHTMOUSE', 'ESC'}:
            context.window.cursor_modal_restore()
            return {'CANCELLED'}

        return {'PASS_THROUGH'}

    def invoke(self, context, event):
        if context.area is None or context.area.type != 'VIEW_3D':
            self.report({'WARNING'}, "View3D not found, cannot run operator")
            return {'CANCELLED'}

        context.window_manager.modal_handler_add(self)
        context.window.cursor_modal_set("EYEDROPPER")
        return {'RUNNING_MODAL'}

#---------------------------


class NormalToolPropsPanel(bpy.types.Panel):

    """Properties Panel for the Normal Tool on tool shelf"""
    bl_label = "Normal Brush"
    bl_idname = "OBJECT_PT_normal_tool_props"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Kitfox - Normal"


    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj != None and (obj.mode == 'OBJECT')

    def draw(self, context):
        layout = self.layout

        scene = context.scene
        settings = scene.normal_brush_props

        pcoll = preview_collections["main"]

        running = active_tool() is not None

        col = layout.column()
        col.scale_y = 1.4
        col.operator("kitfox.normal_tool",
            text = "Stop Normal Tool" if running else "Start Normal Tool",
            icon_value = pcoll["normalTool"].icon_id,
            depress = running)

        col = layout.column()
        row = col.row(align = True)
        row.prop(settings, "show_normals", toggle = True, icon = 'HIDE_OFF' if settings.show_normals else 'HIDE_ON')
        sub = row.row(align = True)
        sub.active = settings.show_normals
        sub.prop(settings, "occlude_normals", toggle = True, icon = 'XRAY')
        sub = col.column()
        sub.active = settings.show_normals
        sub.prop(settings, "normal_length")

        col.prop(settings, "strength")
        col.prop(settings, "use_pressure")
        col.prop(settings, "radius")
        col.prop(settings, "front_faces_only")
        col.prop(settings, "selected_verts_only")
        col.prop(settings, "selected_faces_only")
        col.prop(settings, "use_shape_keys")

        col.label(text="Brush Type:")
        col.prop(settings, "brush_type", expand = True)

        brush_type = settings.brush_type

        col = layout.column()
        col.label(text="Symmetry:")
        row = layout.row()
        row.prop(settings, "symmetry_x", text = "X", toggle = True)
        row.prop(settings, "symmetry_y", text = "Y", toggle = True)
        row.prop(settings, "symmetry_z", text = "Z", toggle = True)

        if brush_type == "FIXED":
            col = layout.column()
            if not settings.normal_exact:
                col.label(text="Normal:")
                col.prop(settings, "normal", text="")
            else:
                col.prop(settings, "normal", expand = True)
            col.prop(settings, "normal_exact")
            col.operator("kitfox.nt_pick_normal", icon="EYEDROPPER")

        elif brush_type == "ATTRACT" or brush_type == "REPEL":
            col = layout.column()
            col.prop(settings, "target")

        box = layout.box()
        col = box.column(align = True)
        col.label(text="LMB: paint    [ ]: radius")
        col.label(text="Ctrl+Z / Ctrl+Shift+Z: undo / redo")
        col.label(text="Enter or Stop: apply")
        col.label(text="Esc / RMB: cancel")


#---------------------------

preview_collections = {}

def register():

    bpy.utils.register_class(NormalToolSettings)
    bpy.utils.register_class(NormalPickerOperator)
    bpy.utils.register_class(ModalDrawOperator)
    bpy.utils.register_class(NormalToolPropsPanel)

    bpy.types.Scene.normal_brush_props = bpy.props.PointerProperty(type=NormalToolSettings)
    bpy.app.handlers.load_pre.append(on_load_pre)

    #Load icons
    icons_dir = os.path.join(os.path.dirname(__file__), "../icons")

    pcoll = bpy.utils.previews.new()
    pcoll.load("normalTool", os.path.join(icons_dir, "normalTool.png"), 'IMAGE')
    preview_collections["main"] = pcoll


def unregister():
    if on_load_pre in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.remove(on_load_pre)
    remove_draw_handler()

    del bpy.types.Scene.normal_brush_props

    bpy.utils.unregister_class(NormalToolPropsPanel)
    bpy.utils.unregister_class(ModalDrawOperator)
    bpy.utils.unregister_class(NormalPickerOperator)
    bpy.utils.unregister_class(NormalToolSettings)

    #Unload icons
    for pcoll in preview_collections.values():
        bpy.utils.previews.remove(pcoll)
    preview_collections.clear()



if __name__ == "__main__":
    register()
