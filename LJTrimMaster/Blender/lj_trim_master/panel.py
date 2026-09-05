# SPDX-License-Identifier: GPL-3.0-or-later
"""One panel: ``3D Viewport > N sidebar > Trim Master``.

Assignment happens here and nowhere else - there is no UV-editor copy and no
second entry point.

**No draw path may write to an ID** (verified fact 15, and the cause of the
crash this rework fixes). Everything below either reads, or binds a
``layout.prop()`` / ``layout.operator()``, both of which defer the write to a
click. In particular the expand arrows are ``prop`` bindings on the registry
entries, and the two dropdowns are ``prop`` bindings whose get/set live in
``assignment``.

Layout, top to bottom::

    Trim Master                                      [refresh]
    Project  [folder] [ .../Desktop            ]
    [ Toggle Transform on Export ]  (o)

    Create Material From Trim Image
       [ scrollable list of image_dump assets ]
       [ Create Material ]

    Meshes                        [ Add Mesh From Selection ]
     v [mesh] building_mesh_1  [trash]  (Needs Rexport) [!]
          [ Add Active Material Slot ]
        v [mat] Wood_1 Material  [trash]
              Trim:        [ Trim_W  v ]
              Trim Image:  [ wood_1  v ]  [!]

    v Export Hooks   (collapsed by default)
"""

import bpy
from bpy.types import Panel

from . import assignment, export_hook, material, settings


def missing_trim_lines(slot):
    """The two lines the Missing-trim-link footer draws, longest first.

    Split over two rows because one row was long enough that Blender's
    mid-string elision ate the asset name and left the tail of the sheet name -
    at a 373 px sidebar, wider than the default. The name is the only thing this
    message exists to say, so it gets a row to itself, and it goes at the END of
    that row: elision keeps a string's head and its tail, and between
    ``wood_wall_a`` and ``wood_wall_b`` the tail is what tells them apart.

    A module-level function rather than inline text so a test can measure it.
    """
    where = " on %s" % slot.sheet_name if slot.sheet_name else ""
    return (
        "Missing trim link" + where,
        "Re-pick above - was: %s" % (slot.asset_base_name or slot.trim_id[:8]),
    )


class LJTM_PT_main(Panel):
    bl_label = "Trim Master"
    bl_idname = "LJTM_PT_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Trim Master"

    def draw(self, context):
        layout = self.layout
        config = settings.settings(context)
        if config is None:
            layout.label(text="Scene settings unavailable", icon='ERROR')
            return

        snapshot = settings.snapshot(context)
        self._draw_project(layout, config, snapshot)
        layout.separator()
        self._draw_materials(layout, config)
        layout.separator()
        self._draw_meshes(context, layout, config, snapshot)

    # -- Project ------------------------------------------------------------

    def _draw_project(self, layout, config, snapshot):
        header = layout.row(align=True)
        header.label(text="Project")
        header.prop(config, "project_root", text="")
        header.operator(assignment.LJTM_OT_refresh.bl_idname, text="", icon='FILE_REFRESH')

        toggle = layout.row(align=True)
        toggle.scale_y = 1.2
        toggle.prop(config, "enabled", toggle=True,
                    icon='CHECKMARK' if config.enabled else 'X')
        # The dot reports whether the hooks are actually attached, which is a
        # different question from whether the switch is on - an exporter add-on
        # enabled after this one leaves the switch green and the hook missing.
        status = export_hook.hook_status()
        live = status.get('FBX') == 'HOOKED' and status.get('glTF') == 'HOOKED'
        dot = toggle.row()
        dot.alert = not live
        dot.label(text="", icon='COLORSET_03_VEC' if live else 'COLORSET_01_VEC')

        if snapshot is None:
            row = layout.row()
            row.alert = True
            row.label(text=settings.CACHE.error or "Set the project root", icon='ERROR')
            return
        if settings.CACHE.error:
            row = layout.row()
            row.alert = True
            row.label(text=settings.CACHE.error, icon='ERROR')
        if not snapshot.has_cached_vocabulary:
            row = layout.row()
            row.label(
                text="No cached map list - open this project in LJ Trim Master once",
                icon='INFO',
            )

    # -- Create Material From Trim Image ------------------------------------

    def _draw_materials(self, layout, config):
        layout.label(text="Create Material From Trim Image")
        if not len(config.assets):
            box = layout.box()
            box.label(text="image_dump/ is empty, or not scanned yet", icon='INFO')
            box.label(text="Press Refresh above", icon='BLANK1')
            return

        layout.template_list(
            "LJTM_UL_assets", "", config, "assets", config, "active_asset", rows=4,
        )
        row = layout.row()
        row.enabled = 0 <= config.active_asset < len(config.assets)
        create = row.operator(material.LJTM_OT_create_material.bl_idname, icon='MATERIAL')
        if row.enabled:
            create.base_name = config.assets[config.active_asset].name

    # -- Meshes -------------------------------------------------------------

    def _draw_meshes(self, context, layout, config, snapshot):
        header = layout.row(align=True)
        header.label(text="Meshes")
        header.operator(assignment.LJTM_OT_add_meshes.bl_idname, icon='ADD')

        if not len(config.meshes):
            layout.label(text="Select meshes and press Add", icon='INFO')
            return

        column = layout.column(align=True)
        for index, entry in enumerate(config.meshes):
            self._draw_mesh_row(context, column, config, index, entry, snapshot)

    def _draw_mesh_row(self, context, layout, config, index, entry, snapshot):
        box = layout.box()
        header = box.row(align=True)
        header.prop(
            entry, "expanded", text="", emboss=False,
            icon='DISCLOSURE_TRI_DOWN' if entry.expanded else 'DISCLOSURE_TRI_RIGHT',
        )

        mesh = assignment.mesh_of(entry)
        # Not the same question as `mesh is None`: the X key only unlinks, so a
        # deleted object keeps a live pointer and a live mesh. See
        # `assignment.object_missing`.
        missing = assignment.object_missing(entry)
        name = header.row(align=True)
        name.alert = missing
        name.label(text=assignment.display_name(entry), icon='OUTLINER_OB_MESH')

        # Two objects sharing a mesh share one UV array, so an edit on one row
        # lands on all of them. Say so rather than letting it surprise.
        shared = assignment.sharing_objects(mesh)
        if len(shared) > 1:
            note = header.row()
            note.alignment = 'RIGHT'
            note.label(text="shared by %d" % len(shared))

        state = assignment.entry_status(entry, snapshot)
        if state != assignment.STATUS_UP_TO_DATE:
            badge = header.row(align=True)
            badge.alignment = 'RIGHT'
            badge.alert = state in {
                assignment.STATUS_MISSING_TRIM, assignment.STATUS_MISSING_MESH
            }
            badge.label(text=assignment.STATUS_LABELS[state],
                        icon=assignment.STATUS_ICONS[state])

        remove = header.operator(
            assignment.LJTM_OT_remove_mesh.bl_idname, text="", icon='TRASH'
        )
        remove.index = index

        if not entry.expanded:
            return

        if missing:
            note = box.column(align=True)
            note.alert = True
            if entry.obj is None or mesh is None:
                note.label(text="Object is gone.", icon='ERROR')
            else:
                note.label(text="Object is not in the scene.", icon='ERROR')
            note.label(
                text="Flagged, not auto-removed - an undo or a library reload "
                     "can produce this transiently",
                icon='BLANK1',
            )
            return

        add = box.operator(assignment.LJTM_OT_add_slot.bl_idname, icon='ADD')
        add.index = index

        for slot in entry.slots:
            self._draw_slot_row(box, index, entry, slot, snapshot)

    def _draw_slot_row(self, layout, mesh_index, entry, slot, snapshot):
        box = layout.box()
        header = box.row(align=True)
        header.prop(
            slot, "expanded", text="", emboss=False,
            icon='DISCLOSURE_TRI_DOWN' if slot.expanded else 'DISCLOSURE_TRI_RIGHT',
        )

        live_name = assignment.slot_material_name(entry.obj, slot.slot_index)
        header.label(
            text="%s   (slot %d)" % (live_name or slot.material_name or "no material",
                                     slot.slot_index),
            icon='MATERIAL',
        )
        remove = header.operator(
            assignment.LJTM_OT_remove_slot.bl_idname, text="", icon='TRASH'
        )
        remove.mesh_index = mesh_index
        remove.slot_index = slot.slot_index

        if not entry.expanded or not slot.expanded:
            return

        # `material_name` is repair information only: slots can be reordered, and
        # a mismatch means slot_index now points somewhere else.
        if slot.material_name and live_name and live_name != slot.material_name:
            row = box.row()
            row.alert = True
            row.label(text="Slot %d is now '%s', was '%s'"
                      % (slot.slot_index, live_name, slot.material_name), icon='ERROR')

        state, item = assignment.status_of(slot, snapshot)
        body = box.column(align=True)
        body.prop(slot, "sheet_enum", text="Trim")
        body.prop(slot, "trim_enum", text="Trim Image")

        if state == assignment.STATUS_MISSING_TRIM:
            cause, name = missing_trim_lines(slot)
            footer = box.column(align=True)
            footer.alert = True
            footer.label(text=cause, icon='ERROR')
            footer.label(text=name, icon='BLANK1')
            return

        footer = box.row(align=True)
        if state == assignment.STATUS_HIDDEN:
            footer.alert = True
            footer.label(
                text="Hidden in the tool - not on '%s', so it cannot export"
                     % (item.sheet.name if item else "?"),
                icon=assignment.STATUS_ICONS[state],
            )
        elif item is not None:
            footer.label(
                text="%s  %d x %d" % (item.sheet.name, item.sheet.resolution[0],
                                      item.sheet.resolution[1]),
                icon=assignment.STATUS_ICONS[state],
            )
        else:
            footer.label(text=assignment.STATUS_LABELS[state],
                         icon=assignment.STATUS_ICONS[state])


class LJTM_PT_hooks(Panel):
    bl_label = "Export Hooks"
    bl_idname = "LJTM_PT_hooks"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Trim Master"
    bl_parent_id = "LJTM_PT_main"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, _context):
        layout = self.layout
        layout.label(text="File > Export is transparent for:")
        column = layout.column(align=True)
        for label, state in export_hook.hook_status().items():
            row = column.row()
            if state == 'HOOKED':
                row.label(text=label, icon='CHECKMARK')
            elif state == 'C_OPERATOR':
                row.label(text=label + " - use Trim-Synced Export", icon='INFO')
            elif state == 'UNAVAILABLE':
                row.label(text=label + " - add-on disabled", icon='BLANK1')
            else:
                row.alert = True
                row.label(text=label + " - NOT hooked", icon='ERROR')
        layout.operator(export_hook.LJTM_OT_attach_hooks.bl_idname, icon='FILE_REFRESH')

        layout.separator()
        # The only path that serves OBJ / PLY / STL / USD / Alembic - those are C
        # operators and cannot be hooked from Python. Without it the add-on would
        # cover FBX and glTF only, which contradicts the renderer-agnostic scope.
        layout.menu(export_hook.LJTM_MT_export.bl_idname, icon='EXPORT')
        layout.operator(export_hook.LJTM_OT_dry_run.bl_idname, icon='CHECKMARK')

        leftovers = export_hook.leftover_modifiers()
        if leftovers:
            box = layout.box()
            box.alert = True
            box.label(text="%d leftover temp modifier(s)" % len(leftovers), icon='ERROR')
            box.operator(export_hook.LJTM_OT_purge_modifiers.bl_idname, icon='TRASH')


classes = (
    LJTM_PT_main,
    LJTM_PT_hooks,
)
