import os
import bpy

from . import preferences


# ---------------------------------------------------------------------------
# Tunables — adjust to taste, no UI for these (yet).
# ---------------------------------------------------------------------------

# Move each object to world origin during export so its pivot lands at (0,0,0)
# in Unity. The original transform is restored after export.
MOVE_TO_ORIGIN = False

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


# Sentinel suffix used while swapping an original out of the way so its
# duplicate can take the original's name during export.
_NAME_SWAP_SUFFIX = ".__lj_tmp__"


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


def _duplicate_with_data(context, obj):
    copy = obj.copy()
    if obj.data is not None:
        copy.data = obj.data.copy()
    context.collection.objects.link(copy)
    return copy


def _build_export_copies(context, targets):
    """Duplicate `targets`, swap names so copies inherit the originals' names,
    zero each copy's location, and apply all transforms. Returns
    (export_objects, restore_callable). The restore deletes the copies and
    restores original names."""
    pairs = []
    name_map = []
    for obj in targets:
        original_name = obj.name
        copy = _duplicate_with_data(context, obj)
        obj.name = original_name + _NAME_SWAP_SUFFIX
        copy.name = original_name
        pairs.append((obj, copy))
        name_map.append((obj, original_name))

    copies = [c for _, c in pairs]

    bpy.ops.object.select_all(action='DESELECT')
    for copy in copies:
        copy.select_set(True)
        copy.location = (0.0, 0.0, 0.0)
    context.view_layer.objects.active = copies[0]
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    def restore():
        for c in copies:
            try:
                bpy.data.objects.remove(c, do_unlink=True)
            except (ReferenceError, RuntimeError):
                pass
        for orig, name in name_map:
            try:
                orig.name = name
            except (ReferenceError, RuntimeError):
                pass

    return copies, restore


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

            if prefs.apply_transforms_on_export:
                copies, restore = _build_export_copies(context, [obj])
                export_obj = copies[0]
                original_location = None
            else:
                export_obj = obj
                restore = None
                bpy.ops.object.select_all(action='DESELECT')
                export_obj.select_set(True)
                context.view_layer.objects.active = export_obj
                original_location = obj.location.copy() if MOVE_TO_ORIGIN else None
                if MOVE_TO_ORIGIN:
                    obj.location = (0.0, 0.0, 0.0)

            material_backup = None
            if not prefs.export_materials and export_obj.type == 'MESH' and export_obj.data is not None:
                material_backup = list(export_obj.data.materials)
                export_obj.data.materials.clear()

            try:
                _run_fbx_export(filepath, object_types, prefs.export_animations)
                exported += 1
            finally:
                if restore is not None:
                    # Copy (and its materials) get deleted; no per-object restore needed.
                    restore()
                else:
                    if material_backup is not None:
                        export_obj.data.materials.clear()
                        for m in material_backup:
                            export_obj.data.materials.append(m)
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

        if prefs.apply_transforms_on_export:
            export_objects, restore = _build_export_copies(context, targets)
        else:
            export_objects = targets
            restore = None

        bpy.ops.object.select_all(action='DESELECT')
        for obj in export_objects:
            obj.select_set(True)
        context.view_layer.objects.active = export_objects[0]

        material_backups = {}
        if not prefs.export_materials:
            for obj in export_objects:
                if obj.type == 'MESH' and obj.data is not None:
                    material_backups[obj] = list(obj.data.materials)
                    obj.data.materials.clear()

        try:
            _run_fbx_export(filepath, object_types, prefs.export_animations)
        finally:
            if restore is not None:
                restore()
            else:
                for obj, mats in material_backups.items():
                    obj.data.materials.clear()
                    for m in mats:
                        obj.data.materials.append(m)

        return f"Exported {len(targets)} object(s) to {filepath}"
