# SPDX-License-Identifier: GPL-3.0-or-later
"""One panel: ``3D Viewport > N sidebar > Trim Master``.

Assignment happens here and nowhere else - there is no UV-editor copy and no
second entry point.

**No draw path may write to an ID** (verified fact 15, and the cause of the
crash this rework fixes). Everything below either reads, or binds a
``layout.prop()`` / ``layout.operator()``, both of which defer the write to a
click. In particular the slot expand arrows are ``prop`` bindings on the
registry entries, the search field is a ``prop`` binding on the Scene block, and
the two dropdowns are ``prop`` bindings whose get/set live in ``assignment``.
``LJTM_UL_meshes.filter_items`` is likewise pure - it returns flags, it does not
store them.

Layout, top to bottom::

    Trim Master                                      [refresh]
    Project  [folder] [ .../Desktop            ]
    [ Toggle Transform on Export ]  (o)

    On-Click Material
       [ scrollable list: trim sheets, then image_dump assets ]
       [ Create Material ]

    Meshes                        [ Add Mesh From Selection ]
    [search] [                                    ]
       [ scrollable list, selected meshes on top  ]
       [   building_mesh_1              [!] [trash] ]
       [   building_mesh_2                  [trash] ]

       building_mesh_1                  Needs Rexport
          [ Add Active Material Slot ]
        v [mat] Wood_1 Material  [trash]
              Trim:        [ Trim_W  v ]
              Trim Image:  [ wood_1  v ]  [!]

    v Debugging      (collapsed by default)
         [ Integrity Check ]
         [ Duplicate and Transform ]
         v Export Hooks
"""

import bpy
from bpy.types import Panel, UIList

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


#: Enough rows to be worth scrolling, not so many that the slot editor below
#: starts off-screen on a laptop sidebar. Between the two the list grows itself.
MESH_ROWS = 5
MESH_MAX_ROWS = 12


class LJTM_UL_meshes(UIList):
    """The scrollable Meshes list.

    A UIList for the same reason ``LJTM_UL_assets`` is one: it is the only
    widget in Blender that actually scrolls. The previous column of nested
    boxes grew without limit, so a registry with fifty meshes in it pushed the
    slot editor - and everything below it - off the bottom of the sidebar.

    The cost is that a UIList row cannot nest, so the slots no longer hang under
    each mesh inline. They are drawn under the list, for whichever row is
    active. Every mesh is still visible in the list at once; what you can no
    longer see is two meshes' *slots* at the same time.
    """

    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_propname, index=0, flt_flag=0):
        # `CACHE.snapshot` rather than `settings.snapshot(context)`: the panel's
        # own draw() refreshed the cache moments ago in this same redraw, and
        # this runs once per visible row - no reason for each to re-stat the
        # project file.
        snapshot = settings.CACHE.snapshot
        missing = assignment.object_missing(item)

        row = layout.row(align=True)

        # Blender's layout API has no per-row background colour, so viewport
        # selection is shown the other way round: everything NOT selected is
        # dimmed. `active` is a read-only emphasis flag - it greys a widget
        # without disabling it - so this writes nothing. A missing-object row is
        # never dimmed, or the red that says so would be dimmed along with it.
        body = row.row(align=True)
        body.active = missing or assignment.is_selected(item)

        name = body.row(align=True)
        name.alert = missing
        name.label(text=assignment.display_name(item), icon='OUTLINER_OB_MESH')

        # Two objects sharing a mesh share one UV array, so an edit on one row
        # lands on all of them. Abbreviated here and spelled out in the editor
        # below - a list row has nowhere near the width the old box header had.
        shared = assignment.sharing_objects(assignment.mesh_of(item))
        if len(shared) > 1:
            note = body.row()
            note.alignment = 'RIGHT'
            note.label(text="x%d" % len(shared))

        # Icon only, for the same width reason. `STATUS_LABELS[state]` is
        # written out under the list for the active row.
        state = assignment.entry_status(item, snapshot)
        if state != assignment.STATUS_UP_TO_DATE:
            badge = body.row(align=True)
            badge.alignment = 'RIGHT'
            badge.alert = state in {
                assignment.STATUS_MISSING_TRIM, assignment.STATUS_MISSING_MESH
            }
            badge.label(text="", icon=assignment.STATUS_ICONS[state])

        # Outside `body`, so it keeps full contrast: a dimmed trash button would
        # read as a disabled one, and `active` does not disable anything.
        remove = row.operator(
            assignment.LJTM_OT_remove_mesh.bl_idname, text="", icon='TRASH',
            emboss=False,
        )
        # Blender passes the index into the collection, not the position in the
        # filtered view, so this stays correct while the list is searched or
        # reordered.
        remove.index = index

    def filter_items(self, context, data, propname):
        """Search, then float the viewport selection to the top.

        Returns ``(flags, order)`` and keeps nothing - a UIList filter runs from
        the draw path, so it may not write to an ID any more than draw may.
        """
        entries = getattr(data, propname)
        count = len(entries)

        # Two searches can be live at once: the field drawn above the list, and
        # the one behind the funnel that `template_list` provides for free.
        # Honour both rather than letting the funnel's look broken.
        queries = [
            text for text in (
                (getattr(data, "mesh_search", "") or "").strip().lower(),
                (self.filter_name or "").strip().lower(),
            ) if text
        ]

        if queries:
            flags = [
                self.bitflag_filter_item
                if all(q in assignment.display_name(entry).lower() for q in queries)
                else 0
                for entry in entries
            ]
        else:
            flags = [self.bitflag_filter_item] * count

        display = list(range(count))
        if self.use_filter_sort_alpha:
            display.sort(key=lambda i: assignment.display_name(entries[i]).lower())
        if not queries:
            # Selected first - but only with no search running. A search means
            # the user is aiming at one name they already typed, and rows that
            # reshuffle every time the viewport selection changes would move the
            # row out from under the pointer just as they went to click it.
            # `sort` is stable, so any alpha order above survives inside each
            # group.
            display.sort(key=lambda i: not assignment.is_selected(entries[i]))

        if display == list(range(count)):
            return flags, []

        # `flt_neworder` maps the ORIGINAL index to its new position, which is
        # the inverse of the display list just built.
        order = [0] * count
        for position, original in enumerate(display):
            order[original] = position
        return flags, order


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
        self._draw_meshes(layout, config, snapshot)

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

    # -- On-Click Material --------------------------------------------------

    def _draw_materials(self, layout, config):
        layout.label(text="On-Click Material")
        if not len(config.assets):
            box = layout.box()
            box.label(text="No trim sheets and no image_dump textures yet", icon='INFO')
            box.label(text="Press Refresh above", icon='BLANK1')
            return

        layout.template_list(
            "LJTM_UL_assets", "", config, "assets", config, "active_asset", rows=4,
        )
        row = layout.row()
        row.enabled = 0 <= config.active_asset < len(config.assets)
        create = row.operator(material.LJTM_OT_create_material.bl_idname, icon='MATERIAL')
        if row.enabled:
            picked = config.assets[config.active_asset]
            create.base_name = picked.name
            create.kind = picked.kind
            create.sheet_id = picked.sheet_id

    # -- Meshes -------------------------------------------------------------

    def _draw_meshes(self, layout, config, snapshot):
        header = layout.row(align=True)
        header.label(text="Meshes")
        header.operator(assignment.LJTM_OT_add_meshes.bl_idname, icon='ADD')

        if not len(config.meshes):
            layout.label(text="Select meshes and press Add", icon='INFO')
            return

        layout.prop(config, "mesh_search", text="", icon='VIEWZOOM')
        layout.template_list(
            "LJTM_UL_meshes", "", config, "meshes", config, "active_mesh",
            rows=MESH_ROWS, maxrows=MESH_MAX_ROWS,
        )

        # The index is maintained by the add/remove operators, but a .blend
        # saved before this list existed arrives with none, and a filtered list
        # can leave the active row hidden. Read-only check - the repair belongs
        # to the operators.
        if not (0 <= config.active_mesh < len(config.meshes)):
            layout.label(text="Pick a mesh in the list", icon='INFO')
            return

        self._draw_mesh_detail(
            layout, config.active_mesh, config.meshes[config.active_mesh], snapshot,
        )

    def _draw_mesh_detail(self, layout, index, entry, snapshot):
        """The active row's slots, drawn under the list rather than inside it.

        A UIList row cannot contain another list, which is the whole reason this
        is a separate method now instead of the tail of the row draw.
        """
        box = layout.box()
        header = box.row(align=True)

        mesh = assignment.mesh_of(entry)
        # Not the same question as `mesh is None`: the X key only unlinks, so a
        # deleted object keeps a live pointer and a live mesh. See
        # `assignment.object_missing`.
        missing = assignment.object_missing(entry)
        name = header.row(align=True)
        name.alert = missing
        name.label(text=assignment.display_name(entry), icon='OUTLINER_OB_MESH')

        # The full wording, where the row above had room for the icon only.
        state = assignment.entry_status(entry, snapshot)
        badge = header.row(align=True)
        badge.alignment = 'RIGHT'
        badge.alert = state in {
            assignment.STATUS_MISSING_TRIM, assignment.STATUS_MISSING_MESH
        }
        badge.label(text=assignment.STATUS_LABELS[state],
                    icon=assignment.STATUS_ICONS[state])

        # Two objects sharing a mesh share one UV array, so an edit on one row
        # lands on all of them. Say so rather than letting it surprise.
        shared = assignment.sharing_objects(mesh)
        if len(shared) > 1:
            note = box.row()
            note.label(
                text="Mesh shared by %d objects - an edit here lands on all of them"
                     % len(shared),
                icon='INFO',
            )

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

        if not len(entry.slots):
            box.label(text="No slots tracked yet - press Add above", icon='INFO')
            return

        for slot in entry.slots:
            self._draw_slot_row(box, index, entry, slot, snapshot)

    def _draw_slot_row(self, layout, mesh_index, entry, slot, snapshot):
        box = layout.box()
        header = box.row(align=True)
        header.prop(
            slot, "expanded", text="", emboss=False,
            icon='DISCLOSURE_TRI_DOWN' if slot.expanded else 'DISCLOSURE_TRI_RIGHT',
        )

        # Read live off the mesh, so renaming or replacing a material is simply
        # reflected here. `slot.material_name` is only a fallback for when the
        # index no longer resolves - the row is keyed by slot index, not by
        # material, so a different material in the slot is not a problem to
        # report.
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

        if not slot.expanded:
            return

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


class LJTM_PT_debugging(Panel):
    """Everything that inspects the transform rather than performing one.

    Collapsed by default and one level down, because none of it is part of the
    normal loop: assign in the Meshes list, then export. You come here when
    something looks wrong, or before trusting a big export.

    Export Hooks lives inside as a nested child. It is a status readout about
    the same machinery, and burying the panel copy of Trim-Synced Export costs
    nothing - ``File > Export > Trim-Synced Export`` is the path that menu
    actually gets used from, and this add-on installs it there directly.
    """

    bl_label = "Debugging"
    bl_idname = "LJTM_PT_debugging"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Trim Master"
    bl_parent_id = "LJTM_PT_main"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout

        column = layout.column(align=True)
        column.operator(export_hook.LJTM_OT_integrity_check.bl_idname, icon='CHECKMARK')
        column.operator(export_hook.LJTM_OT_duplicate_transform.bl_idname, icon='DUPLICATE')

        obj = context.active_object
        config = settings.settings(context)
        entry = assignment.find_entry(config, obj) if config and obj else None
        note = layout.row()
        if obj is None or obj.type != 'MESH':
            note.label(text="Duplicate acts on the active mesh - none selected",
                       icon='INFO')
        elif entry is None:
            note.label(text="'%s' is not in the Meshes list" % obj.name, icon='INFO')
        else:
            assigned = len([slot for slot in entry.slots if slot.trim_id])
            note.label(text="'%s': %d assigned slot(s)" % (obj.name, assigned),
                       icon='INFO')

        # A temp modifier that outlived its export is a leak, and it would keep
        # deforming UVs in the viewport until it is removed.
        leftovers = export_hook.leftover_modifiers()
        if leftovers:
            box = layout.box()
            box.alert = True
            box.label(text="%d leftover temp modifier(s)" % len(leftovers), icon='ERROR')
            box.operator(export_hook.LJTM_OT_purge_modifiers.bl_idname, icon='TRASH')


class LJTM_PT_hooks(Panel):
    bl_label = "Export Hooks"
    bl_idname = "LJTM_PT_hooks"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Trim Master"
    bl_parent_id = "LJTM_PT_debugging"
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
        # Also in File > Export, which is where it is actually used from.
        layout.menu(export_hook.LJTM_MT_export.bl_idname, icon='EXPORT')


#: Parents before children: Blender resolves ``bl_parent_id`` at registration.
classes = (
    LJTM_UL_meshes,
    LJTM_PT_main,
    LJTM_PT_debugging,
    LJTM_PT_hooks,
)
