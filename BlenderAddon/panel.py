import bpy

from . import export
from . import preferences


class LJEXPORT_PT_panel(bpy.types.Panel):
    bl_idname = "LJEXPORT_PT_panel"
    bl_label = "LJ Unity FBX Exporter"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "LJ"

    def draw(self, context):
        layout = self.layout
        layout.label(text="For all youssssr exporting needs! 🚗")

        layout.separator()

        prefs = preferences.get_prefs(context)
        preferences.draw_shared(layout, prefs)

        layout.separator()

        types = export.enabled_object_types(prefs)
        count = sum(1 for obj in context.selected_objects if obj.type in types)
        layout.label(text=f"Selected exportable: {count}")

        row = layout.row()
        row.scale_y = 1.4
        row.operator(export.LJEXPORT_OT_export_selected.bl_idname, icon='EXPORT')
