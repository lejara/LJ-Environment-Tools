# Handoff — LJ Trim Master, Phase 3 (Blender Addon)

Paste everything below the line into a fresh session.

---

I'm building **LJ Trim Master**, a texture tool for authoring trim sheets / atlases. Working directory is `LJTrimMaster/` inside my Unity project at `Assets/LJ Environment Tools`.

**Phase 3 is designed and approved. You are implementing it.** The design below is settled — do not re-litigate it. Ask me about anything genuinely missing.

## How we work

Lockstep. **Do not write code until I give an explicit go-ahead**, even for something that looks trivial. Ask about gaps rather than guessing on anything architectural.

- **One class/object per file.**
- Tool: UI in `renderer/ui/`, models in `renderer/models/`, non-UI logic in `main/` and `renderer/services/`.
- Keep replies short. Depth belongs in these docs, not in chat.

## Read these first

- `Draft.md` — the spec. Source of truth for behaviour. Note the **Scope** section: the tool is renderer-agnostic; Unity and Blender are the first two integrations, not the target.
- `ClassDiagram.md` — architecture, folder layout, event bus, Phase 1/2 decision records.
- `Blender Export Write Test/README.md` — **the proven export-hook technique Phase 3 is built on. Read this before touching the addon.**
- `Brainstroming.md` — Unity ideas only. **Out of scope.**

## Phase status

- **Phase 1** — class diagram, code structure: COMPLETE, approved.
- **Phase 2** — UI editor + export pipeline: COMPLETE. Builds clean, typechecks clean, ~150 headless assertions pass. **Never launched** — see Caveats.
- **Phase 3** — Blender sync addon: **designed, not started.** This document.
- **Phase 4** — Unity addon: TBD.

---

# Part 1 — What already exists

## The tool

Electron + TypeScript + React via `electron-vite`. Main process owns filesystem I/O and the export pipeline; renderer owns UI and zustand stores. Runtime deps: `@napi-rs/canvas`, `pngjs`, `yaml`, `zustand`.

```
LJTrimMaster/
  maps.yaml            preset-packs/        # ship next to the binary
  main/                fs/ export/ autoExport/ + main.ts, ipc.ts, preload.ts, menu.ts
  renderer/            models/ state/ services/ ui/
  shared/              types.ts, ipcChannels.ts, events/
  Blender/                                  # EMPTY - Phase 3 goes here
  Blender Export Write Test/                # working export-hook extension
```

Working end to end: startup screen and recents, project scaffolding, `image_dump/` scanning, preset loading, the full editor UI, undo/redo, Auto Export, and a real export pipeline writing PNG/JPG/TGA.

## `projectData.json`

Lives at the project root. This is what the addon reads. Shape (`version: "1"`):

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

- `position` / `scale` are **normalized 0-1** against the sheet. `position` is the trim's **centre**. Negative `scale` on an axis **mirrors** it.
- `rotation` is **degrees, counter-clockwise-positive**.
- `crop` is a **symmetric inset**, normalized 0-0.5: `crop.x` trims equally off the left AND right edges, `crop.y` off top and bottom.
- `history` and `isDirty` are runtime-only, not serialized.

## The export test addon

`Blender Export Write Test/uv_export_transform` — a working Blender extension (v0.3.0) that transforms UVs **only inside the exported file**; scene UVs never change. Installed live via a directory junction into `extensions/user_default/`.

**20/20 headless checks pass.** Verified independently, not just claimed:

```
"C:/Program Files/Blender Foundation/Blender 5.1/blender.exe" --background --python tests/test_fbx_roundtrip.py
"C:/Program Files/Blender Foundation/Blender 5.1/blender.exe" --background --python tests/test_evaluated_path.py
```

Phase 3's addon is a **specialization** of this, not a rewrite:

| Export test addon | Phase 3 |
|---|---|
| `UVXF_Entry` — manual offset/scale/rotation/pivot | per-material-slot trim assignment |
| `_apply_to_layer` — generic `R*S*(uv-P)+P+O` | the trim affine from `projectData.json` |
| `collect_targets` — hand-built object list | walks material slots on assigned meshes |
| whole-UV-layer transform | **masked by `material_index`** |

Everything else transfers essentially verbatim: `uv_transform_applied`, the hooks, `_flush`, dedup on `(mesh, layer)`, `finally` restore, leftover-modifier purge, Edit Mode skip, `hook_status`.

---

# Part 2 — Verified facts. Do NOT re-derive.

These cost real time to establish. Trust them.

1. **`export_scene.fbx` and `export_scene.gltf` are Python operators in Blender 5.1.2**, so their `execute` can be reassigned. Confirmed by a live FBX export showing the wrapper in the call stack above `io_scene_fbx/__init__.py`. Because the patch is on the operator **class**, every call path is caught.
2. **`wm.obj_export`, `wm.ply_export`, `wm.stl_export`, `wm.usd_export`, `wm.alembic_export` are C operators.** Python cannot intercept their execution. They are served by `File > Export > UV-Transformed Export`, which applies, invokes with `EXEC_DEFAULT`, and restores.
3. **The C exporters' menu *entries* are Python** (`bl_ui.space_topbar`, `TOPBAR_MT_file_export.draw._draw_funcs[0]`, a swappable list), so a native-looking click for those CAN be routed through the transform. Not implemented. Cost is owning the dialog (usd 68 / obj 46 / stl 31 options).
4. **Blender's UVWarp is `uv' = S*R*(uv + offset - center) + center`** — offset pre-transform, rotate before scale. A single UVWarp cannot express `R*S*(uv-P)+P+O`. Two chained ones do; that is the evaluated path.
5. **Never drive exporters through the Blender MCP bridge.** It crashed Blender twice. Test headlessly in a separate process.
6. **Blender 5.1.2 has a bug in its own FBX *importer*** — it raises on any file containing a light (`lamp.cycles.cast_shadow` is gone). Affects re-import in round-trip tests only. Export is fine. Tests delete Light and Camera before exporting.
7. **`BlenderAddon/export.py` calls `bpy.ops.export_scene.fbx`** at line 118, so the existing LJ Unity FBX Exporter is covered by the hook with **zero integration**.
8. **`@napi-rs/canvas` stores premultiplied alpha.** A packed output's alpha is *data* (smoothness), so round-tripping through a canvas wipes RGB where alpha is low — verified, not assumed. Strategies return plain unpremultiplied buffers; PNGs are written with `pngjs`.
9. **`Transform.rotation` is CCW-positive but CSS and canvas `rotate()` are CW-positive.** The Viewport and `TrimBlitter` each negate on the way in. Change one and you must change the other.
10. **`main/menu.ts` has no Edit > Undo/Redo on purpose.** Menu accelerators are consumed before the renderer sees the keystroke, so `role: 'undo'` would swallow Ctrl+Z and run the focused text field's undo instead of the sheet's transform undo. macOS would need an Edit menu for clipboard roles — it must still leave that accelerator alone.

---

# Part 3 — Phase 3 design (settled)

**Standalone Blender extension** in `LJTrimMaster/Blender/`. `blender_manifest.toml`, `blender_version_min = "4.2.0"`, developed against 5.1.2. **Not** a module inside `BlenderAddon/` — that addon is Unity-specific by construction (`AXIS_FORWARD='-Z'`, `AXIS_UP='Y'`, `FBX_SCALE_ALL`), and this one is renderer-agnostic.

**Read-only against the project.** Never writes `projectData.json`, never writes UVs into the `.blend`. There is no registration hook file.

## Settled decisions

| Question | Decision |
|---|---|
| UV write target | **Never written.** Transformed at export time, restored in a `finally` |
| Assignment unit | **Material slot** — the slot is the face grouping (`polygon.material_index`), which is what receives one affine |
| Assignment storage | On the **mesh**, keyed by slot index |
| Trim lookup | `trim_id`, enforced unique project-wide |
| Sheet lookup | **Derived by scan**, never stored |
| Material dependency | **None.** The addon never inspects the material — no texture lookup, no filename inference |
| Sheet material in Blender | **Cut.** Each downstream integration handles its own materials |
| Missing trim link | Loud warning, manual re-pick. No auto-healing |
| Shared mesh datablock | Shared link. Separating requires Make Single User |
| Plain `File > Export` | Transparent for FBX and glTF. Other formats via the explicit operator |

## Proposed file layout

```
LJTrimMaster/Blender/
  blender_manifest.toml
  __init__.py
  project.py         # projectData.json reader + mtime cache
  uv_transform.py    # the trim affine - NO bpy import
  export_hook.py     # lifted from the export test addon
  assignment.py      # per-slot records on the mesh + schema version
  sidecar.py         # writes the object->trim link file the tool reads
  panel.py           # per-slot UI, status, hook status
  material.py        # convenience: material from one image_dump image
```

`uv_transform.py` imports no `bpy` so the math is testable in plain Python. **It must agree with `main/export/trimBlitter.ts` exactly.**

## The trim affine

Derived from `main/export/trimBlitter.ts`. A pure affine — one 2x3 matrix per trim:

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

Two load-bearing properties:

- **Rotation runs in sheet pixels.** `W`/`H` are the sheet's resolution. Rotating in normalized space shears on a non-square sheet, and the UVs stop matching the exported PNG.
- **Source image dimensions cancel.** Crop is normalized and the kept region stretches to fill the box, so the matrix is correct whatever the source file's pixel size. The addon never opens an image for geometry.

**There is no "initial transform" to store.** The user's unwrap in source-image space *is* the reference; the affine maps it to wherever the trim currently sits. Derived fresh on every export, so there is no accumulated state and nothing to invert.

## Identity model

Stored per assigned slot, on the **mesh**:

| Field | Role |
|---|---|
| `schema_version` | int, on the mesh. Bump when this record's shape changes |
| `slot_index` | which face group |
| `material_name` | repair only — the user can reorder slots |
| `trim_id` | **the** identity, and the only resolution key |
| `assetBaseName` | **label only.** Never used for matching |
| `last_exported` | trim state at last export. Informational only |

Why the mesh and not the object: `material_index` is mesh polygon data and slots default to linking `mesh.materials`, so both halves are mesh-level. Two objects sharing a mesh datablock share one UV array — they physically cannot have different transforms.

`assetBaseName` exists so a missing-link message reads *"was: old_wood on Trim01"* instead of a bare UUID. It is the tool's **normalized** name (`old-wood_Normal.png` and `old_wood-AO.png` both collapse to `old_wood`), so it may match no file on disk exactly. **Show the normalized name in the UI** — do not imply it is a filename.

Nothing stored can go stale and disagree with `projectData.json`: the sheet, its resolution and the transform are re-read on every panel draw and every export.

## Export integration

Wrap `EXPORT_SCENE_OT_fbx.execute` and `EXPORT_SCENE_OT_gltf.execute` on register, exactly as the export test addon does.

Per-slot masking: build a loop mask from `polygon.material_index` plus `loop_start`/`loop_total`, and apply the matrix to that slice only.

| Case | Path |
|---|---|
| single trim, no UV-affecting modifier | Direct |
| single trim + UV-affecting modifier | Evaluated (two chained UVWarps) |
| multi-trim, no UV modifier | Direct, masked per slot |
| **multi-trim + UV-affecting modifier** | **unsupported — report, never silently pick wrong** |

The evaluated path cannot mask per slot: UVWarp filters by vertex group, and a vertex on a slot boundary belongs to both groups.

**Silent-failure rules.** An unresolvable `trim_id`, or an object in Edit Mode, must be reported **loudly** and skipped. Never export with untransformed UVs and no warning — that is the one unacceptable outcome.

## Sync status

Compare each assigned mesh's `last_exported` against live `projectData.json`.

| Status | Meaning |
|---|---|
| Up to date | record matches live |
| Needs re-export | trim moved, sheet resized, or trim now on another sheet |
| Missing trim link | `trim_id` gone from the project |

**The record is informational only.** If it is wrong or absent the export is still correct, because the transform is derived fresh. A bad record can only produce a wrong *list*, never wrong UVs. Every export path maintains it — exporting by hand through `File > Export` still fires the hook and still clears the entry.

The button is named **Sync All And Reexport**. It exports every mesh in the Needs re-export list.

## The sidecar link file

The object-to-sheet mapping must be visible outside the `.blend`, or Phase 4 has no data channel and the tool cannot warn before a destructive edit.

**One JSON per `.blend`**, written by the addon into the project root:

```
<projectRoot>/blender_links/<blend-stem>-<short-hash-of-full-path>.json
```

The hash disambiguates two `.blend` files that share a stem in different folders. Contents: the absolute `.blend` path, the addon schema version, and one entry per assigned slot — object name, mesh name, slot index, material name, `trim_id`, `assetBaseName`, and the resolved `sheet_id` / `sheet_name`.

Written on assignment change, on export, and on `save_post`. **The tool treats it as read-only and possibly stale** — the `.blend` may have been moved or deleted, so surface it as information, never as truth.

Tool side: build a reverse index `trim_id -> [objects]` on project load and refresh, and **warn before deleting a trim or a sheet that objects are linked to it.** Warn, do not block.

## Panel

`3D Viewport > N sidebar`, plus the UV editor sidebar per Draft. Per-slot rows for the active object, unassigned slots shown blank rather than hidden:

```
Slot 0  wood_mat     [Trim01 v] [old_wood v]      * needs re-export
Slot 1  brick_mat    [Trim01 v] [brick_a  v]      * up to date
Slot 2  metal_mat    [- none -]
Slot 3  glass_mat    [Trim02 v] [was: glass]      * missing trim link
```

Sheet dropdown, then trim-instance dropdown filtered to that sheet. Multi-select applies a pick across every selected object's matching slots — Draft's rule: if the selection is mixed, whatever you pick applies to all.

Also on the panel: project root picker, the Needs re-export list across the whole `.blend` (not just the selection), Sync All And Reexport, and live hook status.

**Thumbnails** via `bpy.utils.previews` — generated from `image_dump/` on disk, adding no Image datablock to the `.blend`. `EnumProperty` items carry `icon_value`, so the dropdown itself can show them. Load lazily (a large dump would stall the panel), invalidate on mtime, and glob `image_dump/<baseName>*` preferring a BaseColor/Albedo/Diffuse match, since the addon cannot read `maps.yaml`.

Register operators with `{'REGISTER', 'UNDO'}` so Ctrl+Z covers assignment edits.

## Authoring flow

1. Set the project root in the panel.
2. Optionally **Create Material From Image** — builds a Principled material from an `image_dump/` texture (BaseColor, plus Normal if a sibling exists). **Nothing depends on it.** The material may already exist, come from elsewhere, or have no image texture at all.
3. Unwrap normally against that image. The UV editor shows that one texture, 0-1, as always.
4. Assign the material slot to a sheet and a trim instance.
5. Keep modelling. **Nothing changes** — the viewport still shows the individual texture, correctly mapped, at full resolution.
6. Export. The hook transforms UVs into sheet space in the written file only.

Seeing the packed result is deliberately not the default: the individual texture is more useful while modelling than a small corner of a packed sheet.

## Flows

**Trim moves in the tool, 3 objects affected**

1. Tool: drag lands, sheet marked dirty, `projectData.json` autosaved 800 ms later. Auto Export or Build rewrites the sheet PNGs.
2. Blender: **nothing happens.** Scene UVs are the raw unwrap and always were.
3. Addon, next panel draw: mtime changed, cache reloads, the three meshes differ from `last_exported` and are listed under Needs re-export.
4. Sync All And Reexport: hook fires per export, transform applied, file written, restored in `finally`, records updated, list clears.

**User deletes a trim**

1. `trim_id` no longer in `projectData.json`.
2. Addon flags the mesh **Missing trim link**.
3. At export that object is skipped with a loud report.
4. Repair is manual — re-pick sheet + trim. Re-adding the same image mints a new id, so it is still a missing link. Accepted as user error; the sidecar warning in the tool is what discourages it.

**User moves a trim with Move to Sheet**

1. Tool: item spliced `Trim01 -> Trim02`, `id` preserved, transform recomputed to preserve pixel geometry, both sheets dirty.
2. Addon resolves `trim_id` fine and finds it under `Trim02` by scan. Nothing to repair — the sheet is derived, not stored.
3. Live state differs from `last_exported` -> Needs re-export.
4. Sync All And Reexport recomputes UVs against `Trim02`'s resolution. Repositioning afterwards is just another diff.

---

# Part 4 — Changes required in the tool (Phase 2 code)

Four edits. All small.

**1. Move to Sheet.** `Project.moveImage(imageId, fromSheetId, toSheetId)` — it spans two sheets so it belongs on `Project`, not `TrimSheet`. Preserves `id`, appends to the target (arriving on top of the z-order, matching `addImage`), marks **both** sheets dirty. **Not undoable**, consistent with add/remove/reorder/rename. Selection clears; do not switch tabs. Dangling history needs no work — `TrimSheet.step()` already drops snapshots whose image no longer exists. UI is a select in the Properties panel; the tool has no context menus and this does not justify inventing them.

**Transform recomputation preserves pixel geometry:**

```
newScale = oldScale * oldRes / newRes        newPos = oldPos * oldRes / newRes
```

A same-resolution move is a byte-identical no-op, which is the sheet-split case. Texel density is preserved, and rotation stays correct — rotation happens in pixel space, so it is only invariant if the pixel box is. Multiplying by a positive ratio keeps the sign, so mirroring survives. `rotation` and `crop` carry over untouched; neither depends on sheet resolution.

**2. Atomic `projectData.json` write.** `ProjectFs.write` is a plain `writeFile` and the tool autosaves 800 ms after every edit, so the addon can read a half-written file mid-export. Write temp + rename.

**3. Enforce project-wide unique trim ids.** `crypto.randomUUID` is unique in practice, but a duplicated sheet block or hand-edited JSON could collide. Re-mint duplicates in `ProjectFs.migrate`.

**4. Read the sidecar link files and warn.** On project load and refresh, read `<root>/blender_links/*.json`, build `trim_id -> [objects]`, and warn before deleting a trim or a sheet that objects are linked to. **Warn, do not block.** Treat the files as read-only and possibly stale.

---

# Part 5 — Build order

1. **Verify Blender 5.1.** Existing `BlenderAddon/` runs clean; FBX operator surface unchanged. `blender.exe` is **not on PATH** — use `"C:/Program Files/Blender Foundation/Blender 5.1/blender.exe"`. Blender 4.5 is also installed.
2. **Launch the Electron app and export once.** Everything in Phase 3 consumes `projectData.json` and `output/*.png` from a pipeline that has never run. If `TrimBlitter` has a geometry bug the addon will faithfully reproduce it and you will debug the wrong half.
3. **Affine slice.** One object, one trim, no masking, no status model — verify the written FBX against the exported PNG by eye and by headless assertion.
4. Per-slot masking and the assignment panel.
5. Status model, sidecar file, Sync All And Reexport.
6. Tool-side changes (Part 4).
7. Thumbnails, preview toggle.

Testing pattern: `blender --background --python`, following `Blender Export Write Test/tests/`. Export through the real operator, re-import, assert on file contents, exit non-zero on failure. Separate process, so an open session is never disturbed.

---

# Part 6 — Open / to verify

- **Can two chained UVWarps express a reflection?** Negative scale is how mirroring is encoded in a trim transform, and the two-modifier decomposition was derived for `R*S` without one. If it cannot, the evaluated path needs a Direct fallback plus a warning for mirrored trims. **Verify before relying on the evaluated path.**
- **Never tested against a real ZenUV-trimmed asset** — only the default cube. ZenUV is installed on the dev machine.
- **The Electron app has never been launched.** No GUI rendered, no IPC round-trip observed, no PNG ever written.
- **FBX and glTF are the last Python exporters.** When Blender ports FBX to C++ the transparent `execute` hook dies. The contingency is proven — see Verified Fact 3 — and the migration is: move the hook from `execute` to the menu draw func, and **generate** the mirrored dialog props from `bl_rna.properties` rather than hand-writing 145 of them, so they track Blender releases instead of drifting. Keep the explicit `UV-Transformed Export` operator a first-class documented path, not an untried fallback.
- **Preview toggle** — leaving the UVWarp pair on shows the packed result in the viewport without touching base UVs, but only for single-trim objects.
- **Overlapping trims are user error.** Neither side detects them. Accepted.

## Caveats

- `@napi-rs/canvas` ships a `.node` binary needing `asarUnpack` when electron-builder is configured. There is no packaging config yet.
- Export payloads carry no `trigger: "manual" | "auto"` field. Declined; revisit only if a listener needs to tell Build from Auto Export.
- A stray `package-lock.json` is staged one level up at `Assets/LJ Environment Tools/`. Probably wants unstaging.
- Two unrelated add-ons are broken on this machine's Blender 5.1.2: `GrabDoc` declares a max version of 4.7.0, and something raises `AttributeError: 'module' object has no attribute 'ActionFCurves'`. Neither touches this work.

---

# Part 7 — Tool decisions you must not re-litigate

**Startup:** startup screen with New / Open Recent / Browse. Recents in a user-scoped config file, not in the project.

**Project layout:** `/root` holds `projectData.json`, `image_dump/`, `placeholder slots/`, `output/`. **`image_dump/` is the source of truth** — models are UV-unwrapped against those images.

**Viewport UX:** preview + selection outline only. **No canvas drag, no click-to-select.** Selection via the Outliner; transform editing in the Properties panel.

**Sidebar:** two columns. Outliner alone on the left at full height; Properties / Assets / Sheet Settings on the right. Each scrolls independently.

**Trim sheet resolution:** per sheet. New sheets seed from the project default in the Settings modal; changing that default does **not** resize existing sheets.

**Outliner:** list order **is** z-order — top of the list draws last (on top). Reorderable by drag. The underlying `items` array is the reverse (index 0 = bottom).

**Undo/redo:** **transforms + crop only.** Per-sheet history stack surviving tab switches. Add / remove / rename / reorder / move-to-sheet / tab-level actions are **not** undoable.

**Toolbar (bottom):** settings gear, Auto Export toggle (timer polls each sheet's `isDirty` and re-exports dirty sheets), Build (manual full re-export of the active sheet), global Refresh.

**Application menu:** File / View / Help. Help > How To Use (F1) opens a quick-reference modal built from live state.

**Event bus — narrow by design.** Only `REFRESH_*` and `EXPORT_*`. Everything else uses state stores or direct service calls. `AutoExporter` clears `isDirty` **inline** after `Exporter.export()` returns, not via the bus.

**Asset references:** `TrimImage` references its source by `assetBaseName` (a string), not by an `Asset` object. Sibling maps are re-resolved from the current `image_dump/` scan at export time.

**Map naming — `maps.yaml`.** Tool-wide, next to the binary. Several suffix delimiters at once (`suffixDelims: ["_", "-", "."]`); a single `suffixDelim` string still works. Every delimiter is normalized to a single `_` before splitting, so a dump can mix conventions. Normalization applies to the base name too, so `old-wood_Normal.png` and `old_wood-AO.png` group into **one** asset called `old_wood` — that merging is deliberate. Only the primary map appears in the Assets panel and Outliner. **The addon cannot read this file** — it is next to the tool binary, not in the project.

**Presets — `preset-packs/*.yaml`.** Global, next to the binary. **One preset = a named bundle of texture outputs.** Identity is the `name:` field, not the filename; on a duplicate name the first loaded wins. Top-level `format:` and `normalConvention:` are per-output defaults. A single-output preset may drop `outputs:`. Validation is lenient one level at a time: a bad entry in `outputs:` is skipped with a warning and the preset keeps its other outputs; only a preset with zero usable outputs is dropped. **The addon cannot read these either** — `projectData.json` stores preset *names* only, not their output suffixes.

**Export behaviour:**

- Missing sources **warn but never block** — the channel falls back and the reason lands in `EXPORT_COMPLETED.warnings`.
- `fallback` is used **as-is** and never re-inverted, even when the channel sets `invert: true`.
- Uncovered sheet area gets each channel's `fallback` for pack outputs, and stays transparent for copy outputs.
- Failure is **per-output**: one preset's mask map failing does not cost the sheet its base colour.
- Output filename is `<SheetName><outputSuffix>.<ext>`, filesystem-illegal characters replaced, spaces and hyphens preserved.

**Normal maps:** only valid with `mode: copy` — `source: Normal` inside a pack is refused at load time. When a trim is rotated the encoded (R,G) vector rotates to match, B untouched, and negative scale flips the corresponding axis. Handedness is `normalConvention: OpenGL | DirectX` (default OpenGL), which collapses to the sign of `sin(theta)`.
