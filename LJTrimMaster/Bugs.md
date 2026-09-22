# Editor Tool

All verified headlessly (16 assertions) plus a typecheck and build. **Not
clicked in the running app yet.**

1. ~~Z order issue. a trim image thats overlapping the tab bar prevent it from
   being clicked.~~ **DONE.** `.viewport__sheet` now has `overflow: hidden`, so a
   trim hanging off the sheet is clipped instead of painting over the tab bar.
   That also matches the exporter, which crops at the canvas edge. The tab bar
   additionally gets its own stacking context as a second line of defence.
2. ~~Needs hide/unhide.~~ **DONE.** `◉` toggle in the Outliner. Hidden means
   **not on the sheet**: the exporter skips it, and the Blender addon refuses to
   transform UVs onto it. The addon reports **"Trim hidden"** rather than
   "Missing trim link" — the link is fine, so telling the user to re-pick would
   make them destroy a correct assignment to fix something that only needs
   unhiding. Hidden trims are also dropped from the addon's Trim Image picker.
   Not undoable, consistent with add/remove/reorder.
3. ~~Needs to account for opacity when blending texture maps~~ **DONE.**
   Coverage for **every** output of a trim now comes from that trim's BaseColor
   alpha, so a cut-out silhouette masks Normal and MaskMap identically instead of
   each map contributing its own opaque rectangle. `PackStrategy` already did
   this; the bug was in `CopyStrategy`. An asset with no BaseColor falls back to
   the drawn map's own alpha.
4. ~~Account for opacity when showing outline~~ **DONE.** The selection outline
   traces the opaque pixels via stacked `drop-shadow` filters rather than
   drawing a rectangle around empty space. The missing-asset placeholder keeps
   its own dashed box.
5. ~~Default scale needs to be the image size.~~ **DONE.** A new trim lands at
   1:1 texel density, sized from the thumbnail the Assets panel has already
   decoded. Oversized images land **oversized**, not clamped. If the thumbnail
   has not decoded yet the trim is added at the old default and corrected once a
   probe resolves.
6. ~~Rename scale to size for the entire project.~~ **WON'T DO**, per your call.
   `transform.scale` is the on-disk key in `projectData.json` and the Blender
   addon reads it.
7. ~~Create a build system for the blender add-on~~ **DONE.**
   `Blender/build.ps1` → `Blender/dist/lj_trim_master-<version>.zip`, via
   `blender --command extension build`, which validates the manifest. It caught
   a real bug on first run: `tagline` was 67 characters against a 64 limit, so
   the extension would have been rejected at install time.

# Blender Addon

## Fixed after the first real-UI test session (Blender 5.1.2)

All five reproduced, fixed, and pinned by `tests/test_ui_bugs.py` - **62/62**
with the cleanup below,
plus the four existing suites green afterwards: `test_affine` 43/43,
`probe_uvwarp` 11/11, `smoke` 0 failures, `test_sync_roundtrip` 109/109. The
add-on zip still builds. **Not re-clicked in the running app yet.**

The new suite exists because every one of these passed the old suites while
being broken in the panel: each test now reproduces the state through the path
the **UI** takes, not the path a test finds convenient.

### 1. ~~Export Hooks reports every C exporter as "add-on disabled"~~ **DONE**

Detection now goes through `bpy.ops`, not `bpy.types`. A **C** operator is not
exposed as a class on `bpy.types` at all - only Python-defined ones are - so
`getattr(bpy.types, "WM_OT_obj_export")` was None for an exporter that ships in
every build, and the panel reported it absent rather than unhookable. The probe
is `bpy.ops.<module>.<op>.get_rna_type()`, which raises `KeyError` for a name
that does not exist; `hasattr` cannot be used, because attribute access on
`bpy.ops` manufactures a live handle for any name at all.

`hook_status` and `attach_hooks` were also classifying independently and could
drift; both now call one `_classify`. OBJ, PLY, STL, USD and Alembic report
`C_OPERATOR` - *"use Trim-Synced Export"* - and FBX and glTF stay `HOOKED`.
Tone left as INFO, per your call.

### 2. ~~A newly added slot's Trim Image list is empty~~ **DONE**

`_visible_sheet_id` now validates `picker_sheet_id` against the snapshot and
falls back the way `_get_sheet` already did. The two halves answered the same
question differently, so a fresh slot (`picker_sheet_id == ""`) and a slot
outliving a deleted sheet both rendered a sheet name over an empty trim list -
which reads as "this sheet has no trims" and is a lie.

The recovery worry is moot: there is nothing to recover from, because the
fallback now populates the list on the first draw. A resolvable `trim_id` still
outranks the picker, so the sheet stays **derived** and Move to Sheet still
needs no add-on code.

### 3. ~~Deleting a tracked object does not produce "Missing mesh"~~ **DONE**

`bpy.ops.object.delete()` - the X key, the only delete the UI offers - merely
unlinks. The registry's `PointerProperty` is a real user, so the datablock
survives at `users == 1` and `entry.obj` never becomes None. New
`assignment.object_missing` checks `users_scene` as well as the pointer, and
`entry_status` uses it.

**Report only**, per your call: the row and the pointer are kept, matching the
existing rule for a null pointer, because an undo or a library reload can
produce this transiently and dropping the assignment would be unrecoverable.
The expanded row now distinguishes *"Object is gone"* from *"Object is not in
the scene"*.

**One extra, found while fixing it.** `export_hook.collect` called
`obj.select_get()` on every registered row, and that **raises** for an object
outside the view layer - so a selection-only export was a crash waiting on
exactly this row. `collect` now skips out-of-scene objects with a warning,
before that call.

### 4. ~~"Missing trim link" truncates away the one thing it must show~~ **DONE**

Split over two rows - 30 and 45 characters against the 78 that was being elided:

```
[!] Missing trim link on Test_Trim
    Re-pick above - was: pink_stone_quarry_wall_b
```

The name gets a row to itself and sits at the **end** of it: Blender's elision
keeps a string's head and its tail, and between `wood_wall_a` and `wood_wall_b`
the tail is what tells them apart. The text moved out of `draw()` into
`panel.missing_trim_lines`, so a test can measure it - a draw path cannot be
sampled.

### 5. ~~Create Material stacks duplicate texture nodes~~ **DONE**

`build_material` claimed nothing and called `nodes.new` unconditionally. It now
claims its nodes by label, so the second press is a no-op, and **prunes the
duplicates** - a material already stacked up by earlier clicks is repaired
(measured: 11 nodes / 6 image nodes back to 5 / 2). The unlabelled Normal Map
nodes older builds left behind are recognised by sitting at this module's own
coordinates with nothing wired out of them.

Nodes the module does not own are never touched, verified with a foreign image
node and a foreign Normal Map node in the same tree.

### 6. Cleanup: a changed material is reflected, not warned about

The slot row used to draw *"Slot 0 is now 'brick_mat', was 'wood_mat'"* in red
whenever the stored name and the live one disagreed. Dropped. A row is keyed by
**slot index**, not by material, so a rename or a swap is not a problem to
report - and the header was already reading the live name off the mesh, which
means the warning contradicted the line above it.

`slot.material_name` stays, in the mirror and the sidecar, purely as the
fallback label for when `slot_index` no longer resolves to a material. The same
stale name was leaking into one export warning ("has no faces"); that now
prefers the live name too.

## Rework after that session

Pinned by `tests/test_ui_bugs.py` sections 7-9 - **99/99** for the whole file,
with the four existing suites still green. **Not clicked in the running app.**

### Debugging container

New collapsed sub-panel holding **Integrity Check** and **Duplicate and
Transform**, with **Export Hooks** nested inside it. None of it is part of the
normal loop - assign, then export - so it sits one level down. Burying the panel
copy of Trim-Synced Export costs nothing: `File > Export > Trim-Synced Export`
is where that menu is actually used from, and the add-on installs it there.

### Dry Run Check -> Integrity Check

Renamed, operator and all: `ljtm.dry_run` is now `ljtm.integrity_check`.

It also used to report *"N slot(s) transformed and fully reverted"* with the
master switch **off**, when `uv_transform_applied` had yielded None and nothing
had been applied at all - every "restored" check passing vacuously. It now
refuses, and says the switch is off.

### Duplicate and Transform

A copy of the active mesh with its trim transform baked into the UVs, to look at
what the export will be. The original keeps its reference unwrap.

The copy is **untracked**, and that is the whole design constraint rather than a
convenience: its UVs are already in sheet space, so a registry row would mean the
next export transformed it a second time, silently and wrongly. Both routes in
are closed - no row, and the inherited mesh mirror is stripped so Refresh and the
load handler cannot adopt it either. Tested by running both.

Refused with a warning, creating nothing, for a mesh that is not in the Meshes
list, has no trim assigned, has no UV map, or whose every slot fails to resolve.
Resolution happens against the original **before** the duplicate is made, so a
run that can do nothing leaves nothing behind.

### On-Click Material

Renamed from Create Material From Trim Image, and it now lists **every trim
sheet in the project** alongside the `image_dump/` assets - one list, because it
is one question. A sheet row builds from what the tool exported into `output/`;
an asset row builds from the source texture. Sheets come first.

The add-on had never read `output/` before, so this is new: `project.OUTPUT`,
`scan_sheet_outputs`, and an `OutputCache` with the same Refresh-not-poll policy
as the asset cache.

Matching files to sheets is the fiddly part, and needed two rules. The remainder
after the sheet name must **begin at a delimiter** - `Test_Trim_BaseColor.png`
otherwise prefixes a sheet called `Test_Trim_B` with `aseColor` left over, which
is exactly what the first run did. Then **longest prefix wins**, for
`Test_Trim_B_BaseColor.png`, which both sheets can legitimately claim. Sheet
names are also sanitized identically to `Exporter.fileNameFor`, or a sheet
called `Trim.` would match none of its own files.

A suffix outside the map vocabulary is kept under its own name rather than
dropped, so `_MaskMap` counts. A sheet with nothing exported is still listed,
marked `not exported`, and building from it is refused with a message that points
at Build.

## Verified working in this session

- The panel draws, and no draw path crashes on redraw or writes to an ID.
- `Add Mesh From Selection`, `Add Active Material Slot`, the trash icons, and
  the expand/collapse arrows on both row types.
- Changing the Trim clears the Trim Image rather than keeping a stale label.
- Move-to-sheet in `projectData.json`: the row goes `Needs Rexport` and the Trim
  dropdown shows the **new** sheet, derived by scan.
- Deleting a trim: `Missing trim link`, `trim_id` retained, no silent re-point.
- Alt+D linked duplicate: `shared by 2` on both rows, an edit on one row
  propagates to the other. Shift+D full copy stays independent.
- Refresh: re-reads past the mtime cache, rescans `image_dump/` recursively
  (5 assets, normalized names including `pink_stone_1/pink_stone_1`), adopts
  appended meshes, re-evaluates statuses.
- Export, headlessly - 19/20 of a written gap suite, the one failure being item
  1 above: native OBJ ships raw 0-1 UVs; `Trim-Synced Export > OBJ` ships
  sheet-space UVs and leaks no `__ljtm_` modifiers; master switch off leaves
  scene UVs untouched and records nothing as exported; the sidecar is silent on
  an unsaved `.blend` and written on save with one resolved link; an append into
  a second `.blend` arrives with a mirror and no row, and Refresh adopts it with
  the assignment intact; `load_post` adopts on open.

## Still open

- **Install path.** The build system exists (`Blender/build.ps1`, and the zip
  still builds), but the add-on is installed via a directory junction -
  `extensions/user_default/` per HANDOFF, while the live instance loads it from
  `extensions/vscode_development/`.
- **The five fixes above have not been clicked in the running app.** Verified
  headlessly only.
- **Never tested against a real ZenUV-trimmed asset** - only hand-built quads
  and default cubes.
- **Existing `.blend` files lose their assignments.** Accepted breaking change.

## Closed by the UI rework (verified headlessly, now also clicked)

1. ~~Create Material From Image must show normalized name~~ **DONE.**
2. ~~Account for sub folders in image_dump~~ **DONE.**
3. ~~Redesign UI panel~~ **DONE.**
4. ~~Error when creating material~~ **DONE.**
