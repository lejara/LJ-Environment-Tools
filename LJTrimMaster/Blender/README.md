# LJ Trim Master — Blender add-on

Assigns material slots to trims authored in the tool, and transforms UVs into
trim-sheet space **only inside the exported file**. The `.blend`'s UVs are never
modified, and `projectData.json` is never written.

Specialization of the proven `Blender Export Write Test` extension: same
`execute` wrap, same `finally` restore, same dedup and depsgraph flush — but the
transform comes from `projectData.json` per material slot instead of from
hand-typed offsets, and it is **masked by `material_index`** so several trims can
share one mesh and one UV layer.

## Build

```powershell
.uild.ps1                 # -> dist/lj_trim_master-<version>.zip
.uild.ps1 -Blender "C:\...\Blender 4.5lender.exe"
```

Packs through `blender --command extension build`, which validates
`blender_manifest.toml` on the way. Falls back to a plain zip when no Blender is
found, and says so - that path checks nothing.

## Install

Already installed on this machine as a directory junction, so edits are live:

```
%APPDATA%\Blender Foundation\Blender\5.1\extensions\user_default\lj_trim_master
  -> <repo>\LJTrimMaster\Blender\lj_trim_master
```

Reload after an edit by disabling/re-enabling it in Preferences, or restart
Blender. To install elsewhere, zip `lj_trim_master/` and use
`Preferences > Get Extensions > Install from Disk`.

**Disable `UV Export Transform` while using this.** Both wrap the same exporters.
The test add-on is a no-op with an empty object list, but two live UV transforms
on one export is not a state worth debugging.

## Use

`3D Viewport > N sidebar > Trim Master`. **One panel** - there is deliberately no
UV-editor copy and no second place to assign anything.

```
Trim Master
Project  [ .../MyProject          ] [refresh]
[ Toggle Transform on Export ]  (o)      <- dot: green = FBX+glTF hooked

On-Click Material
   [ scrollable list: trim sheets, then image_dump assets ]
   [ Create Material ]

Meshes                        [ Add Mesh From Selection ]
[search] [                                      ]
   [ building_mesh_1              [!] [trash] ]  <- scrolls; selected on top
   [ building_mesh_2                  [trash] ]
   [ floor_slab                       [trash] ]

   building_mesh_1                  Needs Rexport
      [ Add Active Material Slot ]
    v [mat] wood_mat  (slot 0)  [trash]
          Trim:        [ Trim01  v ]
          Trim Image:  [ old_wood v ]

v Debugging               (collapsed by default)
     [ Integrity Check ]
     [ Duplicate and Transform ]
     v Export Hooks
```

**Terminology.** The UI uses the user's words: **Trim** = the trim *sheet*,
**Trim Image** = the image placed on it. In code, `Sheet` and `TrimItem`.

**The tree is opt-in.** `Add Mesh From Selection` adds rows, `Add Active Material
Slot` adds slots. A slot with no row is not listed and is not transformed - that
is the design, not an oversight, and it is not a silent failure because nothing
ever claimed the slot would be transformed.

**The Meshes list scrolls, and the slots are edited below it.** A `UIList` is
the only widget in Blender that scrolls, and a UIList row cannot nest - so every
mesh is visible in the list at once, but the slots belong to whichever row is
active. That is the trade: a registry with fifty meshes in it no longer pushes
everything below it off the bottom of the sidebar, and the price is that two
meshes' slots cannot be read side by side.

**Selected meshes float to the top**, and rows whose object is *not* selected in
the viewport are dimmed - Blender's layout API has no per-row background colour,
so the emphasis has to run the other way round. **A search overrides the
floating**: while the search field has text the list keeps its registry order,
because rows that reshuffle as the viewport selection changes would move out
from under the pointer just as you went to click one. The funnel's own filter
and alphabetical sort still work, and compose with both.

**On-Click Material** builds a Principled material in one click, from either
kind of row. A **trim sheet** row uses what the tool exported into `output/` -
the finished, packed textures, so the material shows what the model will look
like in-engine. An **image_dump asset** row uses the source texture you unwrapped
against, at full resolution. Sheets are listed first, and a sheet nothing has
been exported for is listed too, marked `not exported`, so "why is my sheet
missing?" is never the question. **Nothing in the add-on depends on either** -
the trim transform never inspects a material.

**Refresh** (top right) does all of: re-read `projectData.json` past the mtime
cache, rescan `image_dump/` recursively, rescan `output/`, adopt any appended
mesh carrying trim data, rebuild the On-Click Material list, and re-evaluate
every status.

**Debugging** holds the things that inspect the transform rather than perform
one, collapsed and one level down because none of it is part of the normal loop.

**Integrity Check** runs a full export cycle without writing a file: it applies
every trim transform, prints each slot's UV range before and after to the System
Console, restores, and then verifies the restore was **bit-exact** - not merely
close. It also fails on a leftover temporary modifier. This is the thing to run
before trusting a large export, because a wrong restore corrupts the `.blend`
silently. It does not exercise the exporter itself.

**Duplicate and Transform** copies the active mesh and bakes its trim transform
into the copy's UVs, so you can look at what the exported model will actually be.
The original keeps its reference unwrap. The copy is **not tracked** - no
registry row, and the mesh mirror it inherited is stripped - because its UVs are
already in sheet space and a second transform would silently ruin it. Active
object only; a mesh that is not in the Meshes list, or has no trim assigned, is
refused with a warning and nothing is created.

Workflow:

1. **Set the project root.** Saved with the `.blend`.
2. Optionally **On-Click Material**. **Nothing depends on this.**
3. **Unwrap normally** against that one texture, 0-1.
4. **Add the mesh, add the slot, pick a Trim then a Trim Image.**
5. **Keep modelling.** Nothing changes - the viewport still shows the individual
   texture at full resolution.
6. **Export.** FBX and glTF are transparent. OBJ/PLY/STL/USD/Alembic go through
   `File > Export > Trim-Synced Export`, or the menu under Debugging > Export
   Hooks.

**Transform On Export** is the master switch. Off means exports are byte-for-byte
what Blender would normally write.

## What is stored, and where

**The registry** is a scene-level collection and is what the user edits. Rows are
keyed by **object**, because that is what the user selects and what the Outliner
names.

```
Scene.lj_trim_master
  project_root, enabled, meshes[], assets[]

MeshEntry     obj (PointerProperty), expanded, slots[]
SlotEntry     slot_index, material_name, expanded,
              trim_id, asset_base_name, sheet_name, last_export
```

But UVs and `material_index` are **mesh** data: two objects sharing a mesh share
one UV array and physically cannot carry different assignments. So an assignment
**propagates to every row whose object shares that mesh**, and such rows show a
`shared by N` note. The impossible state is unreachable rather than merely
detected.

`PointerProperty`, not a name: Blender keeps pointers valid across renames and
nulls them on delete, which gives the **Missing mesh** row for free. Those rows
are flagged, never auto-pruned - an undo or a library reload can null a pointer
transiently, and silently dropping the assignment would lose real work.

**The mesh mirror.** A serialized copy of a mesh's slots lives in a custom
property on the **mesh** (`lj_trim_master_slots`), so assignments travel with
append and link. Written on any assignment change and on `save_post`; read on
`load_post`. **Registry wins while the file is open; mirror wins on load.**
Blender has no `append_post`, so an object appended into an open scene arrives
carrying a mirror and sits unregistered until Refresh adopts it.

**Never store `sheet_id`.** The sheet is resolved by scanning `projectData.json`
fresh on every read, which is why Move to Sheet in the tool needs zero add-on
code - there is no reference to repoint.

**Nothing stored can go stale into a wrong export.** A bad record can only
produce a wrong *list*, never wrong UVs.

`asset_base_name` is the tool's **normalized** name and may match no file on disk
exactly. The UI never presents it as a filename.

## The trim affine

`uv_transform.py` imports no `bpy`, so the one thing that has to be provably
right is testable without Blender. It must agree with
`main/export/trimBlitter.ts` exactly: that file draws the pixels, this one moves
the UVs onto them, and a disagreement is a silent misalignment.

Two load-bearing properties, both asserted:

- **Rotation runs in sheet pixels.** `W`/`H` sit *inside* the rotation. Rotating
  in normalized space shears on a non-square sheet.
- **Source image dimensions cancel.** Crop is normalized and the kept region
  stretches to fill the box, so the add-on never opens an image to learn its
  geometry.

There is no "initial transform" to store. The unwrap in source-image space *is*
the reference; the affine maps it to wherever the trim currently sits, derived
fresh every export — so no accumulated state and nothing to invert.

## Direct vs Evaluated

| Case | Path |
|---|---|
| single trim, no UV-affecting modifier | Direct |
| single trim + UV-affecting modifier | Evaluated (two chained UVWarps) |
| multi-trim, no UV modifier | Direct, masked per slot |
| **multi-trim + UV-affecting modifier** | **unsupported — reported, never guessed** |

The evaluated path cannot mask per slot: UVWarp filters by vertex group, and a
vertex on a slot boundary belongs to both groups. A mesh with two trims and a
modifier that rewrites UVs is refused outright rather than exported half right.
When the evaluated path *is* used and the mesh has other slots with faces, the
add-on warns — those faces move too.

Subsurf, Multires and Solidify are deliberately not counted as UV-affecting:
they interpolate or copy UVs affinely, and an affine transform commutes with
that, so Direct stays correct through them.

### Why two UVWarps, and can they mirror?

**Yes — verified, not assumed.** This was HANDOFF Part 6's open question.

Blender's UVWarp is `uv' = S·R·(uv + offset − center) + center` (measured again
by `tests/probe_uvwarp.py`: `S·R(+r)` matched to 3e-8, the three other candidate
conventions were off by 0.75–2.0). One modifier's linear part is a diagonal times
a rotation, so it cannot express an arbitrary 2×2. Two chained ones can, with the
second's scale left at 1: that is exactly `R(p)·diag(a,b)·R(q)`, the SVD form,
which has a closed form for 2×2.

A mirrored trim has `det < 0`, which no decomposition into pure rotations and
non-negative singular values reaches. Negating the matrix's second column flips
the determinant positive; folding that back out via
`R(q)·diag(1,−1) == diag(1,−1)·R(−q)` puts the reflection into a **negative** `b`
and a negated `q`. Blender stores a negative UVWarp `scale` unclamped and it does
reflect the evaluated UVs — probed directly. **So the evaluated path needs no
Direct fallback for mirrored trims.**

## Sync status

| Status | Meaning |
|---|---|
| Up to date | `last_export` matches the live trim |
| Needs Rexport | trim moved, sheet resized, trim moved to another sheet, or never exported |
| Trim hidden | resolvable, but hidden in the tool, so it is not on the sheet |
| Missing trim link | `trim_id` is gone from the project |
| Missing mesh | the row's object pointer is `None` |

**Hidden gets its own status** rather than reusing Missing trim link. The link is
good; the trim is switched off in the tool. Reporting it as missing would push
the user to re-pick, destroying a correct assignment to fix something that only
needs unhiding. Hidden trims are also dropped from the Trim Image picker, and
refused at export with a message that says why.

A mesh row reports the **worst** status among its slots.

**The add-on never drives an export.** It only reports that a mesh needs
re-exporting; the user exports however they normally do, and the hook fires. An
earlier version had a `Sync All And Reexport` button that replayed recorded
exporter settings - it is deleted, along with the replay snapshot that served it.

`last_export` is **informational only**. If it is wrong or absent the export is
still correct, because the affine is derived fresh every time. A bad record can
only produce a wrong list, never wrong UVs. Every export path maintains it, so
exporting by hand through `File > Export` clears the entry exactly as anything
else would.

Missing-link repair is **manual**. Re-adding the same image in the tool mints a
new `trim_id`, so there is nothing safe to auto-heal to; the tool's own warning
before deleting a linked trim is what discourages getting there.

## The sidecar link file

```
<projectRoot>/blender_links/<blend-stem>-<hash8-of-full-path>.json
```

The only thing the add-on writes into the project. One entry per assigned slot,
per **object** — the tool's warning is about which objects are linked, so two
objects sharing a mesh are two links. Written on assignment change, on export and
on `save_post`, temp-then-rename so the tool can never read a partial file.

The tool treats it as **read-only and possibly stale**: the `.blend` may have
moved or been deleted since. It surfaces as information, never as truth.

## Silent failure is the one unacceptable outcome

An unresolvable `trim_id`, a mesh in Edit Mode, an unreadable `projectData.json`,
a slot with no faces, and multi-trim-plus-UV-modifier are all reported loudly and
skipped. Nothing is ever written with untransformed UVs and no warning.

## Tests

```bash
BLENDER="C:/Program Files/Blender Foundation/Blender 5.1/blender.exe"

python tests/test_affine.py                                              # 43 checks, no Blender
"$BLENDER" --background --factory-startup --python tests/probe_uvwarp.py        # 11 checks
"$BLENDER" --background --factory-startup --python tests/smoke.py               # register/draw canary
"$BLENDER" --background --factory-startup --python tests/test_sync_roundtrip.py # 109 checks
"$BLENDER" --background --factory-startup --python tests/test_ui_bugs.py        # 99 checks
"$BLENDER" --background --factory-startup --python tests/test_mesh_list.py      # 30 checks
```

**Last run: all passing.** Each exits non-zero on failure and runs in a separate
headless process, so an open session is never disturbed.

`test_affine.py` checks the matrix against an *independent* reimplementation of
`TrimBlitter`'s canvas composition rather than a rearrangement of the same
algebra, so a wrong closed form shows up as a disagreement.

`test_mesh_list.py` covers the Meshes list. Background Blender cannot render a
panel, so `filter_items` is called directly with a stub standing in for the
registered UIList - the real method, not a copy. The two behaviours it pins are
that `flt_neworder` maps the *original* index to its new position rather than
the reverse, and that a live search suppresses the selected-first sort.

`smoke.py` is the regression test for the crash this rework fixed. Background
Blender cannot render a panel, so instead it fingerprints the datablocks, calls
**every function the panel's draw reaches**, and fails if anything changed - a
read path that writes to an ID is caught exactly as the panel would catch it.

`test_sync_roundtrip.py` exports through the real `export_scene.fbx` operator,
re-imports, and asserts the file carries sheet-space UVs while the scene still
reads 0-1. It also covers: the cached map vocabulary and the recursive
`image_dump` scan agreeing with the tool; opt-in (an unregistered mesh keeps its
raw unwrap); the mesh mirror surviving a cleared registry and being re-adopted;
two objects sharing a mesh staying in lockstep and being deduped in the export
plan; a trim moving, a sheet resizing and Move to Sheet all landing on Needs
Rexport while only a deleted trim becomes Missing link; a deleted object
producing a flagged-not-pruned row; the evaluated path producing
`ours(modifier(uv))` and provably not `modifier(ours(uv))`; Edit Mode and
multi-trim-plus-modifier refused with reasons; the master switch as a true
no-op; and the scene restored bit-exact even when the export raises.

Both Blender tests delete the Light and Camera before exporting, working around
a **Blender 5.1.2 bug in its own FBX importer**.

## Notable design decisions

- **The package is nested** as `Blender/lj_trim_master/`. A Blender extension's
  directory name *is* its Python module name, and `Blender` is not usable as one.
- **Import direction is one-way:** `project` <- `assignment` <- `settings` <-
  everything else. `settings` must import `assignment` for its PropertyGroup
  types, so `assignment` reaches `settings` and `sidecar` only through deferred
  imports inside functions. The `ProjectCache`/`AssetCache` singletons live in
  `project.py` for the same reason.
- **The pickers are `EnumProperty` with custom `get`/`set`.** The enum's own
  stored value is never the truth - `trim_id` is - because a dynamic enum
  silently falls back to its first item when the identifier it held disappears,
  and a project reload does exactly that. `get`/`set` translate between a list
  position and the durable string.
- **The Create Material list is a `UIList`.** It is the only widget in Blender
  that actually scrolls; a column of per-asset buttons grows without limit and
  would push the Meshes tree off the bottom of a large dump. That is why the
  scan is mirrored into a `CollectionProperty` - `template_list` cannot iterate
  a plain Python list.
- **The `maps.yaml` vocabulary is cached into `projectData.json`.** `maps.yaml`
  lives next to the tool binary and is unreachable from Blender, and without it
  the two sides disagree about where a base name ends and a map suffix begins.
  The editor stamps it on every refresh; the add-on reads it and falls back to
  built-in defaults when absent.

## Known limitations

- The transform lands on the **active render** UV layer (falling back to the
  active one). There is no per-mesh UV map override.
- `image_dump/` grouping matches the tool exactly **only when the project has a
  cached `maps` block**. A project written before that existed, or never opened
  in the editor since, falls back to built-in defaults and the two can then
  disagree on a name like `old_wood_v2.png`. The panel says so when it happens.
- Shape keys, multires and other data referencing UVs are not considered.
- The evaluated path appends to the end of the modifier stack; a modifier using
  `use_pin_to_last` would still sit after it.
- Overlapping trims are user error. Neither side detects them.
- Not yet verified against a real ZenUV-trimmed production asset — only
  hand-built quads and the default cube.
- **The panel has never been rendered by a real Blender UI.** Everything is
  verified headlessly. See `HANDOFF_Test.md`.
- When FBX and glTF are eventually ported to C++, the transparent `execute` hook
  dies. The contingency is proven (the C exporters' menu *entries* are Python and
  swappable) and `Trim-Synced Export` is already a first-class documented path,
  not an untried fallback.
