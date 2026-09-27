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
import mathutils
import numpy as np

from .normalTool import foreach_array, mesh_corner_normals, normalize_rows


#---------------------------

#World space geometry of a mesh object needed to match up seams
class SeamMeshData:
    def __init__(self, obj):
        mesh = obj.data
        self.obj = obj
        self.mesh = mesh

        num_verts = len(mesh.vertices)
        num_edges = len(mesh.edges)
        num_loops = len(mesh.loops)
        num_polys = len(mesh.polygons)

        mw = np.array(obj.matrix_world, dtype=np.float64)
        self.m3 = mw[:3, :3]
        self.m3_inv = np.linalg.pinv(self.m3)

        coords = foreach_array(mesh.vertices, "co", num_verts, np.float32, 3).astype(np.float64)
        self.coords = coords
        self.coords_world = coords @ self.m3.T + mw[:3, 3]

        self.corner_verts = foreach_array(mesh.loops, "vertex_index", num_loops, np.int32)
        corner_edges = foreach_array(mesh.loops, "edge_index", num_loops, np.int32)
        loop_starts = foreach_array(mesh.polygons, "loop_start", num_polys, np.int32)
        loop_totals = foreach_array(mesh.polygons, "loop_total", num_polys, np.int32)
        self.corner_polys = np.repeat(np.arange(num_polys, dtype=np.int32), loop_totals)
        self.corner_normals = mesh_corner_normals(mesh).astype(np.float64)

        #Boundary vertices are those on an edge used by exactly one face
        edge_verts = foreach_array(mesh.edges, "vertices", num_edges, np.int32, 2)
        edge_face_count = np.bincount(corner_edges, minlength=num_edges)
        self.boundary_verts = np.unique(edge_verts[edge_face_count == 1].ravel())

        #Angle of each face corner, used to weight face normals
        starts = loop_starts[self.corner_polys]
        ends = starts + loop_totals[self.corner_polys]
        idx = np.arange(num_loops)
        next_corner = np.where(idx + 1 == ends, starts, idx + 1)
        prev_corner = np.where(idx == starts, ends - 1, idx - 1)
        p = self.coords_world[self.corner_verts]
        e1 = normalize_rows(self.coords_world[self.corner_verts[next_corner]] - p)
        e2 = normalize_rows(self.coords_world[self.corner_verts[prev_corner]] - p)
        self.corner_angles = np.arccos(np.clip(np.einsum('ij,ij->i', e1, e2), -1, 1))

        poly_normals = foreach_array(mesh.polygon_normals, "vector", num_polys, np.float32, 3).astype(np.float64)
        self.poly_normals_world = normalize_rows(poly_normals @ self.m3_inv)

    def world_to_local_normal(self, n):
        return n @ self.m3

    #World space normal of each corner as currently shaded
    def corner_normals_world(self):
        return normalize_rows(self.corner_normals @ self.m3_inv)

    #Replace normals of all corners that use the given vertices.  Other corners keep their current normals.
    def set_vertex_normals(self, vert_normals_world):
        normals = self.corner_normals.copy()
        for vidx, n in vert_normals_world.items():
            local = self.world_to_local_normal(np.array(n))
            normals[self.corner_verts == vidx] = local
        self.mesh.normals_split_custom_set(normalize_rows(normals).tolist())


def build_kdtree(points):
    kd = mathutils.kdtree.KDTree(len(points))
    for i, p in enumerate(points):
        kd.insert(p, i)
    kd.balance()
    return kd


def mesh_objects_poll(context):
    return context.mode == 'OBJECT' and any(o.type == 'MESH' for o in context.selected_objects)


#---------------------------

class CopySeamNormalsOperator(bpy.types.Operator):
    """Copy normals from active mesh to selected meshes along seam."""
    bl_idname = "kitfox.nt_copy_seam_normals"
    bl_label = "Copy Seam Normals"
    bl_options = {"REGISTER", "UNDO"}

    distance : bpy.props.FloatProperty(
        name = "Merge Distance",
        description = "Maximum distance between vertices to be considered part of the same seam",
        default = .0001,
        min = 0,
        soft_max = .01,
        precision = 5
    )

    @classmethod
    def poll(cls, context):
        return mesh_objects_poll(context)

    def execute(self, context):
        active_obj = context.active_object
        if active_obj is None or not active_obj.type == 'MESH':
            self.report({"WARNING"}, "Active object is not a mesh")
            return {'CANCELLED'}

        neighbor_objs = [p for p in context.selected_objects if p.type == 'MESH' and p != active_obj]
        if not neighbor_objs:
            self.report({"WARNING"}, "No objects to copy to selected")
            return {'CANCELLED'}

        source = SeamMeshData(active_obj)
        if len(source.boundary_verts) == 0:
            self.report({"WARNING"}, "Active mesh has no open boundary edges")
            return {'CANCELLED'}

        #Normal of each source boundary vertex is the average of its corner normals
        src_corner_normals = source.corner_normals_world()
        src_normals = {}
        for v in source.boundary_verts:
            n = src_corner_normals[source.corner_verts == v].sum(axis=0)
            length = np.linalg.norm(n)
            if length > 1e-12:
                src_normals[v] = n / length

        kd = build_kdtree([source.coords_world[v] for v in source.boundary_verts])

        total = 0
        for nobj in neighbor_objs:
            if len(nobj.data.loops) == 0:
                continue
            target = SeamMeshData(nobj)
            updates = {}
            for v in target.boundary_verts:
                co, i, dist = kd.find(target.coords_world[v])
                if i is not None and dist <= self.distance:
                    src_v = source.boundary_verts[i]
                    if src_v in src_normals:
                        updates[v] = src_normals[src_v]
            if updates:
                target.set_vertex_normals(updates)
                total += len(updates)

        self.report({"INFO"}, "Copied normals to %d seam vertices" % total)
        return {'FINISHED'}

#---------------------------

class SmoothSeamNormalsOperator(bpy.types.Operator):
    """Calculate smoothed normal on boundary vertices where they are coincident with vertices of adjacent meshes."""
    bl_idname = "kitfox.nt_smooth_seam_normals"
    bl_label = "Smooth Seam Normals"
    bl_options = {"REGISTER", "UNDO"}

    distance : bpy.props.FloatProperty(
        name = "Merge Distance",
        description = "Maximum distance between vertices to be considered part of the same seam",
        default = .0001,
        min = 0,
        soft_max = .01,
        precision = 5
    )

    @classmethod
    def poll(cls, context):
        return mesh_objects_poll(context)

    def execute(self, context):
        objs = [p for p in context.selected_objects if p.type == 'MESH' and len(p.data.loops) > 0]
        if not objs:
            self.report({"WARNING"}, "No mesh objects selected")
            return {'CANCELLED'}

        datas = [SeamMeshData(obj) for obj in objs]

        #Angle weighted face normal sum for every boundary vertex of every mesh
        points = []
        for di, data in enumerate(datas):
            weighted = data.poly_normals_world[data.corner_polys] * data.corner_angles[:, None]
            vert_sums = np.zeros((len(data.coords), 3))
            np.add.at(vert_sums, data.corner_verts, weighted)
            for v in data.boundary_verts:
                points.append((di, v, data.coords_world[v], vert_sums[v]))

        if not points:
            self.report({"WARNING"}, "Selected meshes have no open boundary edges")
            return {'CANCELLED'}

        kd = build_kdtree([p[2] for p in points])

        #Sum contributions of all coincident boundary vertices, including the vertex itself
        updates = [{} for d in datas]
        for di, v, co, own_sum in points:
            total = np.zeros(3)
            for _, j, _ in kd.find_range(co, self.distance):
                total += points[j][3]
            length = np.linalg.norm(total)
            if length > 1e-12:
                updates[di][v] = total / length

        for data, upd in zip(datas, updates):
            if upd:
                data.set_vertex_normals(upd)

        return {'FINISHED'}

#---------------------------

class SeamNormalPropsPanel(bpy.types.Panel):

    """Properties Panel for the Normal Tool on tool shelf"""
    bl_label = "Seam Normals"
    bl_idname = "OBJECT_PT_seam_normals_props"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Kitfox - Normal"


    def draw(self, context):
        layout = self.layout

        col = layout.column()
        col.operator("kitfox.nt_copy_seam_normals")
        col.operator("kitfox.nt_smooth_seam_normals")


#---------------------------

def register():

    bpy.utils.register_class(SmoothSeamNormalsOperator)
    bpy.utils.register_class(CopySeamNormalsOperator)
    bpy.utils.register_class(SeamNormalPropsPanel)



def unregister():
    bpy.utils.unregister_class(SmoothSeamNormalsOperator)
    bpy.utils.unregister_class(CopySeamNormalsOperator)
    bpy.utils.unregister_class(SeamNormalPropsPanel)




if __name__ == "__main__":
    register()
