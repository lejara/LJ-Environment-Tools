import os
import bpy

from . import preferences


# ---------------------------------------------------------------------------
# Tunables — adjust to taste, no UI for these (yet).
# ---------------------------------------------------------------------------

# Move each object to world origin during export so its pivot lands at (0,0,0)
# in Unity. The original transform is restored after export.
MOVE_TO_ORIGIN = True

# File overwrite behavior. When False, existing files are skipped.
OVERWRITE_EXISTING = True

# Always include empties as group/null nodes when any other type is enabled.
INCLUDE_EMPTIES = True

# Unity-friendly axis conversion. Unity is Y-up, -Z forward.
AXIS_FORWARD = '-Z'
AXIS_UP = 'Y'

# Scale handling. 'FBX_SCALE_ALL' bakes scale into the FBX so Unity reads
# 1 Blender unit = 1 meter without needing manual import-side scaling.
APPLY_SCALE_OPTIONS = 'FBX_SCALE_ALL'
GLOBAL_SCALE = 1.0
APPLY_UNIT_SCALE = True

# Bake axis conversion into the mesh data. Required for clean Unity imports.
USE_SPACE_TRANSFORM = True
BAKE_SPACE_TRANSFORM = True

# Mesh options.
USE_MESH_MODIFIERS = True
MESH_SMOOTH_TYPE = 'FACE'
USE_SUBSURF = False
USE_MESH_EDGES = False
USE_TSPACE = False
USE_TRIANGLES = False

# Armature bone export. Per-export animation/rig inclusion is now in preferences.
ADD_LEAF_BONES = False
PRIMARY_BONE_AXIS = 'Y'
SECONDARY_BONE_AXIS = 'X'
USE_ARMATURE_DEFORM_ONLY = False

# Texture handling. Unity prefers external textures over embedded.
PATH_MODE = 'AUTO'
EMBED_TEXTURES = False


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------

def enabled_object_types(prefs):
    types = set()
    if prefs.export_static_mesh:
        types.add('MESH')
    if prefs.export_rig:
        types.add('ARMATURE')
    if types and INCLUDE_EMPTIES:
        types.add('EMPTY')
    return types


def _run_fbx_export(filepath, object_types, bake_anim):
    bpy.ops.export_scene.fbx(
        filepath=filepath,
        use_selection=True,
        use_visible=False,
        use_active_collection=False,
        global_scale=GLOBAL_SCALE,
        apply_unit_scale=APPLY_UNIT_SCALE,
        apply_scale_options=APPLY_SCALE_OPTIONS,
        use_space_transform=USE_SPACE_TRANSFORM,
        bake_space_transform=BAKE_SPACE_TRANSFORM,
        object_types=object_types,
        use_mesh_modifiers=USE_MESH_MODIFIERS,
        mesh_smooth_type=MESH_SMOOTH_TYPE,
        use_subsurf=USE_SUBSURF,
        use_mesh_edges=USE_MESH_EDGES,
        use_tspace=USE_TSPACE,
        use_triangles=USE_TRIANGLES,
        add_leaf_bones=ADD_LEAF_BONES,
        primary_bone_axis=PRIMARY_BONE_AXIS,
        secondary_bone_axis=SECONDARY_BONE_AXIS,
        use_armature_deform_only=USE_ARMATURE_DEFORM_ONLY,
        bake_anim=bake_anim,
        path_mode=PATH_MODE,
        embed_textures=EMBED_TEXTURES,
        batch_mode='OFF',
        axis_forward=AXIS_FORWARD,
        axis_up=AXIS_UP,
    )


# ---------------------------------------------------------------------------
# Operator.
# ---------------------------------------------------------------------------

class LJEXPORT_OT_export_selected(bpy.types.Operator):
    bl_idname = "ljexport.export_selected"
    bl_label = "Export To Unity"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        prefs = preferences.get_prefs(context)
        types = enabled_object_types(prefs)
        if not types:
            return False
        return any(obj.type in types for obj in context.selected_objects)

    def execute(self, context):
        prefs = preferences.get_prefs(context)
        raw_path = prefs.export_path

        if not raw_path:
            self.report({'ERROR'}, "Export path is empty.")
            return {'CANCELLED'}

        object_types = enabled_object_types(prefs)
        if not object_types:
            self.report({'ERROR'}, "Nothing to export — enable Static Mesh or Rig in preferences.")
            return {'CANCELLED'}

        export_dir = bpy.path.abspath(raw_path)
        try:
            os.makedirs(export_dir, exist_ok=True)
        except OSError as e:
            self.report({'ERROR'}, f"Could not create export folder: {e}")
            return {'CANCELLED'}

        targets = [obj for obj in context.selected_objects if obj.type in object_types]
        if not targets:
            self.report({'WARNING'}, "No exportable objects in selection.")
            return {'CANCELLED'}

        original_selection = list(context.selected_objects)
        original_active = context.view_layer.objects.active

        if prefs.combine_into_single_fbx:
            result_msg = self._export_combined(context, targets, object_types, prefs, export_dir)
        else:
            result_msg = self._export_per_object(context, targets, object_types, prefs, export_dir)

        bpy.ops.object.select_all(action='DESELECT')
        for obj in original_selection:
            obj.select_set(True)
        context.view_layer.objects.active = original_active

        preferences.sync_to_global(context)

        self.report({'INFO'}, result_msg)
        return {'FINISHED'}

    def _export_per_object(self, context, targets, object_types, prefs, export_dir):
        override = prefs.file_name.strip()
        single_override = override if override and len(targets) == 1 else ""
        exported = 0
        skipped = 0
        for obj in targets:
            name = single_override or obj.name
            filepath = os.path.join(export_dir, f"{name}.fbx")
            if not OVERWRITE_EXISTING and os.path.exists(filepath):
                skipped += 1
                continue

            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)
            context.view_layer.objects.active = obj

            original_location = obj.location.copy() if MOVE_TO_ORIGIN else None
            if MOVE_TO_ORIGIN:
                obj.location = (0.0, 0.0, 0.0)

            material_backup = None
            if not prefs.export_materials and obj.type == 'MESH' and obj.data is not None:
                material_backup = list(obj.data.materials)
                obj.data.materials.clear()

            try:
                _run_fbx_export(filepath, object_types, prefs.export_animations)
                exported += 1
            finally:
                if material_backup is not None:
                    obj.data.materials.clear()
                    for m in material_backup:
                        obj.data.materials.append(m)
                if original_location is not None:
                    obj.location = original_location

        msg = f"Exported {exported} object(s) to {export_dir}"
        if skipped:
            msg += f" ({skipped} skipped)"
        return msg

    def _export_combined(self, context, targets, object_types, prefs, export_dir):
        active = context.view_layer.objects.active
        fallback = active.name if active in targets else targets[0].name
        name = prefs.file_name.strip() or fallback
        filepath = os.path.join(export_dir, f"{name}.fbx")
        if not OVERWRITE_EXISTING and os.path.exists(filepath):
            return f"Skipped (already exists): {filepath}"

        bpy.ops.object.select_all(action='DESELECT')
        for obj in targets:
            obj.select_set(True)
        context.view_layer.objects.active = targets[0]

        material_backups = {}
        if not prefs.export_materials:
            for obj in targets:
                if obj.type == 'MESH' and obj.data is not None:
                    material_backups[obj] = list(obj.data.materials)
                    obj.data.materials.clear()

        try:
            _run_fbx_export(filepath, object_types, prefs.export_animations)
        finally:
            for obj, mats in material_backups.items():
                obj.data.materials.clear()
                for m in mats:
                    obj.data.materials.append(m)

        return f"Exported {len(targets)} object(s) to {filepath}"
