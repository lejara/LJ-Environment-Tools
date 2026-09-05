# Handoff — LJ Trim Master, Blender Addon Rework

Paste everything below the line into a fresh session.

---

I'm building **LJ Trim Master**, a texture tool for authoring trim sheets / atlases. Working directory is `LJTrimMaster/` inside my Unity project at `Assets/LJ Environment Tools`.

**This is a rework of working code, not a new build.** The Blender addon exists at `Blender/lj_trim_master/` (10 modules, ~3300 lines, 148 headless assertions passing). The tool side is complete. You are changing the assignment data model, rewriting the panel UI, deleting two features, and fixing three bugs.

## How we work

Lockstep. **Do not write code until I give an explicit go-ahead**, even for something trivial. Ask about gaps rather than guessing on anything architectural.

- **One class/object per file.**
- Tool: UI in `renderer/ui/`, models in `renderer/models/`, non-UI logic in `main/` and `renderer/services/`.
- Keep chat replies short. Depth belongs in these docs.

## Read these first

- `Draft.md` — the spec. Note the **Scope** section: the tool is **renderer-agnostic**. Unity and Blender are the first two integrations, not the target. This matters — it is why non-FBX export formats must keep working.
- `Bugs.MD` — the live bug list. The Blender Addon section is what this rework closes.
- `ClassDiagram.md` — architecture, folder layout, event bus, Phase 1/2 decision records.
- `Blender/README.md` — the current addon.
- `Blender Export Write Test/README.md` — the export-hook technique the addon is built on.
- `Brainstroming.md` — Unity ideas only. **Out of scope.**

---

# Part 1 — The two invariants

Everything else follows from these. Do not break them.

**1. Read-only against the project.** `projectData.json` is never written by the addon. The only thing it writes into the project is the sidecar link file, which the tool treats as advisory.

**2. The `.blend`'s UVs are never modified.** The user's unwrap in source-image space *is* the reference. The affine that maps it onto the sheet is derived fresh on every export, so there is no accumulated state, nothing to invert, and no "initial transform" to keep in sync. Modelling continues against the individual texture at full resolution; the packed sheet exists only in the written file.

---

# Part 2 — Verified facts. Do NOT re-derive.

These cost real time to establish. Trust them.

1. **`export_scene.fbx` and `export_scene.gltf` are Python operators in Blender 5.1.2**, so their `execute` can be reassigned. Confirmed by a live FBX export showing the wrapper in the call stack above `io_scene_fbx/__init__.py`. Because the patch is on the operator **class**, every call path is caught.
2. **`wm.obj_export`, `wm.ply_export`, `wm.stl_export`, `wm.usd_export`, `wm.alembic_export` are C operators.** Python cannot intercept their execution. They are served by `File > Export > UV-Transformed Export`, which applies, invokes with `EXEC_DEFAULT`, and restores.
3. **The C exporters' menu *entries* are Python** (`bl_ui.space_topbar`, `TOPBAR_MT_file_export.draw._draw_funcs[0]`, a swappable list), so a native-looking click for those CAN be routed through the transform. Not implemented. Cost is owning the dialog (usd 68 / obj 46 / stl 31 options) — generate them from `get_rna_type().properties`, do not hand-write.
4. **Blender's UVWarp is `uv' = S*R*(uv + offset - center) + center`** — offset pre-transform, rotate before scale. A single UVWarp cannot express `R*S*(uv-P)+P+O`. Two chained ones do; that is the evaluated path.
5. **Never drive exporters through the Blender MCP bridge.** It crashed Blender twice. Test headlessly in a separate process.
6. **Blender 5.1.2 has a bug in its own FBX *importer*** — it raises on any file containing a light (`lamp.cycles.cast_shadow` is gone). Affects re-import in round-trip tests only. Export is fine. Tests delete Light and Camera before exporting.
7. **`BlenderAddon/export.py` calls `bpy.ops.export_scene.fbx`** at line 118, so the existing LJ Unity FBX Exporter is covered by the hook with **zero integration**.
8. **`@napi-rs/canvas` stores premultiplied alpha.** A packed output's alpha is *data* (smoothness), so round-tripping through a canvas wipes RGB where alpha is low — verified, not assumed. Strategies return plain unpremultiplied buffers; PNGs are written with `pngjs`.
9. **`Transform.rotation` is CCW-positive but CSS and canvas `rotate()` are CW-positive.** The Viewport and `TrimBlitter` each negate on the way in. Change one and you must change the other.
10. **A UVWarp `scale` component may be negative, and it reflects.** Set to `-1.5` it stores unclamped and the evaluated UVs come back mirrored (`det < 0`). This is what lets the two-modifier decomposition express a mirrored trim. Probed directly — `Blender/tests/probe_uvwarp.py`.
11. **An operator's own properties are NOT on `operator.bl_rna`.** `EXPORT_SCENE_OT_fbx.bl_rna.properties` has 14 entries — base `Operator` fields only, no `filepath`. The real 43 come from `bpy.ops.export_scene.fbx.get_rna_type().properties`. (The replay snapshot that needed this is being deleted, but the fact stays — anything touching operator RNA will hit it.)
12. **On Windows, renaming over `projectData.json` fails with EPERM while a reader holds it open.** Reproduced against `ProjectFs.write`. The atomic write serializes per root and retries the rename with backoff, falling back to a direct write rather than losing the save — the autosave swallows rejections, so a throw would lose the edit silently.
13. **`MeshPolygon.loop_total` and `material_index` are both still `foreach_get`-able in 5.1.2.** The per-slot loop mask is built from them, with a `loop_start`-diff fallback for when `loop_total` eventually goes.
14. **`main/menu.ts` has no Edit > Undo/Redo on purpose.** Menu accelerators are consumed before the renderer sees the keystroke, so `role: 'undo'` would swallow Ctrl+Z and run the focused text field's undo instead of the sheet's transform undo.
15. **You may not write to any ID datablock from inside `draw()`.** This is the cause of the current crash (`_migrate` setting `schema_version` on a Mesh during panel draw). Scene is also an ID, so moving state to the Scene does not exempt it. All writes must come from operators, handlers, or `layout.prop()` bindings.

---

# Part 3 — What this rework changes

| Area | Change |
|---|---|
| Assignment storage | Mesh PropertyGroup → **scene-level mesh registry**, with a serialized mirror on the mesh so data survives append/link |
| Panel UI | 8 sub-panel classes across 2 editors → **one panel** matching the new layout |
| Sync All And Reexport | **Deleted.** The addon never drives an export |
| Export replay snapshot | **Deleted** with it |
| Thumbnails | **Deleted** (`thumbnails.py`, `show_thumbnails`). May return later |
| `image_dump/` scanning | **Recursive** — must handle subfolders |
| Create Material list | Shows the **normalized** asset name |
| Sidecar link file | **Always written.** No toggle, no button, no UI |
| Refresh | **New** icon button, top-right of the panel |
| ID-write-in-draw crash | Fixed |

## Module disposition

```
Blender/lj_trim_master/
  uv_transform.py   251   KEEP as-is. The affine. No bpy import
  project.py        376   REWORK - recursive image_dump scan
  settings.py        97   REWORK - drop show_thumbnails, host the registry
  assignment.py     513   MAJOR REWORK - registry model, fix the crash
  export_hook.py   1122   TRIM - delete sync_all + replay; keep the hooks
  sidecar.py        176   KEEP - make unconditional
  material.py       202   SMALL - normalized names, recursive lookup
  thumbnails.py     106   DELETE
  panel.py          344   REWRITE
  __init__.py       112   UPDATE registration
```

---

# Part 4 — The new data model

## The registry is the source of truth

A scene-level collection is what the user edits and what the panel reads. Assignments are no longer authored on the mesh.

```
Scene.lj_trim_master
  project_root : str
  enabled      : bool            # "Toggle Transform on Export"
  meshes       : Collection[MeshEntry]

MeshEntry
  mesh         : PointerProperty(type=bpy.types.Mesh)   # NOT a name
  expanded     : bool                                   # UI state
  slots        : Collection[SlotEntry]

SlotEntry
  slot_index      : int
  material_name   : str      # repair only - slots can be reordered
  expanded        : bool
  trim_id         : str      # THE identity. The only resolution key
  assetBaseName   : str      # label only. Never used for matching
  last_exported   : ...      # trim state at last export. Informational only
```

**Key by mesh datablock, not object.** UVs are mesh data — two objects sharing a mesh share one UV array and *cannot* have different assignments. Show object names in the UI, store the mesh.

**Store a `PointerProperty`, not a name.** Blender keeps pointers valid across renames and nulls them on delete, which gives you the "missing" row for free.

**Never store `sheet_id`.** The sheet is resolved by scanning `projectData.json` fresh on every read. This is why Move to Sheet in the tool needs zero addon code — there is no reference to repoint.

## The mesh mirror

A serialized copy of that mesh's slot entries lives in a custom property on the **mesh**, so assignments travel with append/link.

- **Written** on any assignment change and on `save_post`.
- **Read** on `load_post` to repopulate the registry.
- **Conflict rule:** registry wins while the file is open; mirror wins on load.

**Gap it does not cover:** Blender has no `append_post` handler. Appending an object into an already-open scene fires nothing, so it arrives carrying a mirror and sits unregistered. That is what the Refresh button is for.

## Statuses

| Status | Meaning |
|---|---|
| Up to date | `last_exported` matches live `projectData.json` |
| **Needs Rexport** | trim moved, sheet resized, or the trim now lives on another sheet |
| Missing trim link | `trim_id` is gone from the project |
| Missing mesh | the registry entry's pointer is `None` |

**`last_exported` is informational only.** If it is wrong or absent the export is still correct, because the transform is derived fresh every time. A bad record produces a wrong *list*, never wrong UVs. Every export path maintains it — exporting by hand through `File > Export` fires the hook and clears the entry.

Entries with a null mesh pointer are **flagged, never auto-pruned.** An undo, a temporarily unlinked collection, or a library reload can null a pointer transiently; silently deleting the assignment would lose real work. The trash icon is the only thing that removes.

---

# Part 5 — The new panel

One panel, `3D Viewport > N sidebar`. Sections top to bottom:

```
Trim Master                                          [refresh icon]

Project  [file icon] [ ./Desktop                    ]

[ Toggle Transform on Export ]   (o)      <- status dot: green = hooks live

────────────────────────────────────────────────────────────

Create Material From Trim Image
   [ wood_1                                        ]
   [ stone_1                                       ]   <- scrollable
   [ stone_2                                       ]

────────────────────────────────────────────────────────────

Meshes                              [ Add Mesh From Selection ]

 v  [mesh]  bulding_mesh_1   [trash]   ( Needs Rexport )  [!]
              [ Add Active Material Slot ]
     v  [mat]  Wood_1 Material   [trash]
                 Trim:        [ Trim_W    v ]
                 Trim Image:   [ wood_1    v ]   [!]
     >  [mat]  Stone_1 Material  [trash]
 >  [mesh]  bulding_mesh_2   [trash]
 >  [mesh]  bulding_mesh_3   [trash]

────────────────────────────────────────────────────────────

v Export Hooks
    File > Export is transparent for:
      [x] FBX
      [x] glTF
          OBJ      - add-on disabled
          PLY      - add-on disabled
          STL      - add-on disabled
          USD      - add-on disabled
          Alembic  - add-on disabled
    [ Re-attach Export Hooks ]
```

## Terminology

The UI uses the user's words, which map cleanly onto the code's model names:

- **Trim** = `TrimSheet` (the sheet). Dropdown lists sheets from `projectData.json`.
- **Trim Image** = `TrimImage` (the placed instance on that sheet). Dropdown filtered to the chosen sheet.

## Behaviour

- **Assignment happens here and nowhere else.** No UV-editor panel, no other entry point.
- The tree is **explicit and opt-in**: `Add Mesh From Selection` adds meshes, `Add Active Material Slot` adds slots. A slot with no entry simply is not listed.
- **Refresh** (top-right) does all of: re-read `projectData.json` bypassing the mtime cache; rescan `image_dump/` recursively; walk `bpy.data.meshes` for mirrors not in the registry and add them; re-evaluate every status.
- `Create Material From Trim Image` lists **assets from `image_dump/`** by normalized name — not trim instances. A material comes from an image, not a placement. Clicking one builds a Principled material (BaseColor, plus Normal if a sibling exists). **Nothing depends on this button**; the addon never inspects materials.
- Register every operator with `{'REGISTER', 'UNDO'}` so Ctrl+Z covers assignment edits.
- All expand/collapse state lives on the registry entries via `layout.prop()`. **No draw path writes to an ID** — see verified fact 15.

---

# Part 6 — What gets deleted

- **`LJTM_OT_sync_all`** — "Sync All And Reexport". The addon must never create an FBX or drive an export. It only *reports* that a mesh needs re-exporting; the user exports however they normally do.
- **The export replay snapshot** — the `export_command` property on the slot record and the machinery in `export_hook.py` that captured and replayed exporter settings. It existed only to serve `sync_all`.
- **`thumbnails.py`** and `settings.show_thumbnails`. Pickers show text only.
- **`settings.show_unassigned`** — meaningless once slots are opt-in.
- The **UV editor** copies of every panel class, and the `Sync Status` / `Tools` sub-panels, folded into the single panel above.

## What explicitly stays

- **The export hooks.** `EXPORT_SCENE_OT_fbx` and `EXPORT_SCENE_OT_gltf` wrapping is the entire point of the addon.
- **`File > Export > UV-Transformed Export`** (`LJTM_MT_export`). ***Confirm this one.*** It is the only path that serves OBJ / PLY / STL / USD / Alembic, which are C operators and cannot be hooked (verified fact 2). It creates nothing on its own — it routes the user's own export through the transform. Deleting it as "export code" would leave only FBX and glTF working, contradicting the renderer-agnostic scope in `Draft.md`.
- **`LJTM_OT_dry_run`** — applies, prints before/after UV ranges, restores, verifies the restore was bit-exact. Writes no file. Cheap and it is the only way to check the transform without exporting.
- **The sidecar link file**, now unconditional.

---

# Part 7 — Bugs to fix

From `Bugs.MD`, Blender Addon section:

1. **Create Material From Image must show the normalized name.** `old-wood_Normal.png` and `old_wood-AO.png` collapse to one asset, `old_wood`. Show that, not a filename — the normalized name may match no file on disk exactly, and the UI must not imply otherwise.
2. **Account for subfolders in `image_dump/`.** The addon's scan must recurse. **Note:** the tool's `AssetScanner` needs the same change or the two will disagree about what an asset is. Watch for name collisions across subfolders.
3. **Redesign the UI panel** — Part 5.
4. **The crash.** `assignment._migrate()` writes `schema_version` to a Mesh from inside `draw()`. Fix by making all read paths non-mutating: migrate in `load_post` or an operator, and have `draw` treat an unmigrated or future-versioned record as read-only and report it.

---

# Part 8 — Tool side

Already built, no changes required by this rework:

- `Project.moveImage()` — Move to Sheet, preserving `id` and pixel geometry.
- Atomic `projectData.json` write (see verified fact 12).
- Project-wide unique trim ids.
- Sidecar link files read on load and refresh; warns before deleting a linked trim or sheet.

**One coupled change:** `AssetScanner` must recurse into `image_dump/` subfolders alongside bug 2 above.

The `Editor Tool` section of `Bugs.MD` is separate work and out of scope here.

---

# Part 9 — Testing

`blender --background --python`, following `Blender/tests/`. Blender is **not on PATH**:

```
"C:/Program Files/Blender Foundation/Blender 5.1/blender.exe" --background --python Blender/tests/test_affine.py
```

4.5 and 5.1 are both installed; 5.1.2 is the target. Export through the real operator, re-import, assert on file contents, exit non-zero on failure. Separate process, so an open session is never disturbed.

`uv_transform.py` imports no `bpy`, so the affine is testable in plain Python. **It must agree with `main/export/trimBlitter.ts` exactly.**

Existing suites must keep passing, minus the assertions covering deleted features.

---

# Part 10 — Open items

- **Confirm `UV-Transformed Export` stays** — Part 6.
- **Existing `.blend` files lose their assignments.** Assignments move from the mesh PropertyGroup to the registry with no import path. Accepted as a breaking change.
- **Overlapping trims are user error.** Neither side detects them. Accepted.
- **Never tested against a real ZenUV-trimmed asset** — only the default cube. ZenUV is installed on the dev machine.
- **FBX and glTF are the last Python exporters.** When Blender ports FBX to C++ the transparent hook dies. Contingency is verified fact 3.
- **Build system for the addon** — `Bugs.MD` Editor Tool item 7. Currently installed via a directory junction into `extensions/user_default/`.
- Two unrelated add-ons are broken on this machine's Blender 5.1.2: `GrabDoc` declares a max version of 4.7.0, and something raises `AttributeError: 'module' object has no attribute 'ActionFCurves'`. Neither touches this work.

---

# Part 11 — Tool decisions you must not re-litigate

**Project layout:** `/root` holds `projectData.json`, `image_dump/`, `placeholder slots/`, `output/`. **`image_dump/` is the source of truth** — models are UV-unwrapped against those images.

**`projectData.json`** (`version: "1"`):

```json
{
  "version": "1",
  "defaults": { "defaultTrimResolution": { "width": 2048, "height": 2048 } },
  "sheets": [{
    "id": "uuid", "name": "Trim01",
    "resolution": { "width": 2048, "height": 2048 },
    "enabledPresetNames": ["Unity HDRP"],
    "items": [{
      "id": "uuid", "assetBaseName": "wood",
      "transform": { "position": {"x":0.5,"y":0.5}, "scale": {"x":0.25,"y":0.25}, "rotation": 0 },
      "crop": { "x": 0, "y": 0 }
    }]
  }]
}
```

- `position` / `scale` are **normalized 0-1** against the sheet. `position` is the **centre**. Negative `scale` **mirrors** that axis.
- `rotation` is **degrees, counter-clockwise-positive**.
- `crop` is a **symmetric inset**, 0-0.5: `crop.x` trims equally off left AND right, `crop.y` off top AND bottom.

**The trim affine** — derived from `main/export/trimBlitter.ts`:

```
canvas    sx = u,  sy = 1 - v                    # Blender V up, canvas Y down
crop      bu = (sx - cx)/kw,  bv = (sy - cy)/kh  # kw = 1-2cx, kh = 1-2cy
box px    px = (bu - 0.5)*Sx*W                   # Sx signed - the sign IS the mirror
          py = (bv - 0.5)*Sy*H
rotate    x' =  px*cos(t) + py*sin(t)            # canvas rotate(-t); t is CCW-positive
          y' = -px*sin(t) + py*cos(t)
sheet     U = Px + x'/W
          V = 1 - (Py + y'/H)
```

**Rotation runs in sheet pixels** — rotating in normalized space shears on a non-square sheet. **Source image dimensions cancel** — the addon never opens an image for geometry.

**Per-slot masking:** build a loop mask from `polygon.material_index` plus `loop_total`, apply the matrix to that slice only.

| Case | Path |
|---|---|
| single trim, no UV-affecting modifier | Direct |
| single trim + UV-affecting modifier | Evaluated (two chained UVWarps) |
| multi-trim, no UV modifier | Direct, masked per slot |
| **multi-trim + UV-affecting modifier** | **unsupported — report, never silently pick wrong** |

The evaluated path cannot mask per slot: UVWarp filters by vertex group, and a vertex on a slot boundary belongs to both groups.

**Silent-failure rule.** An unresolvable `trim_id`, or an object in Edit Mode, must be reported **loudly** and skipped. Exporting untransformed UVs with no warning is the one unacceptable outcome.

**Map naming — `maps.yaml`.** Tool-wide, next to the binary. Several suffix delimiters at once; every delimiter is normalized to a single `_` before splitting, and normalization applies to the base name too, so `old-wood_Normal.png` and `old_wood-AO.png` group into **one** asset called `old_wood`. **The addon cannot read this file** — it lives next to the tool binary, not in the project. The addon globs `image_dump/<baseName>*` instead.

**Presets — `preset-packs/*.yaml`.** Global, next to the binary. One preset = a named bundle of outputs; identity is `name:`, not the filename. **The addon cannot read these either** — `projectData.json` stores preset *names* only, not their output suffixes.

**Outliner order is z-order** — top of the list draws last. The underlying `items` array is the reverse (index 0 = bottom).

**Undo/redo in the tool:** transforms + crop only, per sheet. Add / remove / rename / reorder / move-to-sheet are **not** undoable.
