# Handoff — Test the LJ Trim Master Blender add-on

Paste everything below the line into a fresh session.

---

**You are testing a Blender add-on that has just been reworked. Your job is to
find what is broken, not to rebuild it.**

The add-on is at `LJTrimMaster/Blender/lj_trim_master/` inside a Unity project at
`Assets/LJ Environment Tools`. It is installed as a directory junction, so edits
to the repo take effect on add-on reload.

**Check which repo it is actually in before you start** - there are two, and only
one will be live:

```
%APPDATA%\Blender Foundation\Blender\5.1\extensions\
    user_default\lj_trim_master        <- manual junction
    vscode_development\lj_trim_master  <- created by the VS Code
                                          "Blender Development" extension
```

Starting a VS Code dev session **deletes the manual junction** and re-links into
`vscode_development`, so after stopping one a plain Blender launch has no add-on
until the junction is recreated:

```powershell
New-Item -ItemType Junction `
  -Path "$env:APPDATA\Blender Foundation\Blender\5.1\extensions\user_default\lj_trim_master" `
  -Target "<repo>\LJTrimMaster\Blender\lj_trim_master"
```

To build a distributable zip instead: `LJTrimMaster\Blender\build.ps1`.

## How we work

- **Do not rewrite code until you have reproduced a failure and told me what it
  is.** Report first, fix second, and ask before anything architectural.
- Keep chat replies short. Depth belongs in the docs.
- One class/object per file.

## Read these first

- `README.md` — what the whole project is and how it fits together. Start here.
- `Blender/README.md` — the add-on itself.
- `Bugs.md` — the live bug list. Add what you find.
- `HANDOFF.md` — the rework brief this was built from, including 15 verified
  facts you must not re-derive.

---

# 1. What the thing does, in one paragraph

The tool authors trim sheets **after** the textures exist. You texture each
material as its own 0–1 image in `image_dump/`, unwrap models against those
individual images the normal way, then compose the sheet later in the tool. The
add-on's whole job is to transform a model's UVs into sheet space **inside the
exported file only** — the `.blend`'s UVs are never touched. Move a trim on the
sheet and nothing needs re-unwrapping; it needs re-exporting.

Two invariants. Everything else follows from them, and a bug that breaks either
is the most serious kind:

1. **Read-only against the project.** `projectData.json` is never written by the
   add-on. The only thing it writes into the project is
   `blender_links/<blend>-<hash>.json`, which the tool treats as advisory.
2. **The `.blend`'s UVs are never modified.** Transformed at export, restored in
   a `finally`.

# 2. What just changed

This was a UI rework plus a data-model change. If something is broken, it is
most likely in here.

| Area | Change |
|---|---|
| Assignment storage | Mesh PropertyGroup → **scene-level registry**, keyed by **object**, with a serialized mirror on the mesh so it survives append/link |
| Panel | 8 sub-panels across 2 editors → **one panel** in `3D Viewport > N > Trim Master` |
| Sync All And Reexport | **Deleted.** The add-on never drives an export |
| Export replay snapshot | **Deleted** with it |
| Thumbnails | **Deleted** |
| `image_dump/` scan | Now **recursive**, and uses the tool's real map vocabulary |
| `maps.yaml` | Now **cached into `projectData.json`** by the tool, under `maps` |
| Sidecar link file | **Always written.** No toggle, no button |
| Refresh | New icon button, top-right |
| Hidden trims | New: a trim hidden in the tool is refused at export and reports "Trim hidden" |
| ID-write-in-draw crash | Fixed |

**Existing `.blend` files lose their assignments.** There is no import path from
the old mesh PropertyGroup. That is accepted and expected — do not report it.

# 3. The panel

`3D Viewport > N sidebar > Trim Master`. There is deliberately **no UV-editor
copy** and no second place to assign anything.

```
Trim Master
Project  [ .../MyProject          ] [refresh]
[ Toggle Transform on Export ]  (o)      <- dot: green = FBX+glTF hooked

Create Material From Trim Image
   [ scrollable list of image_dump assets ]
   [ Create Material ]

Meshes                        [ Add Mesh From Selection ]
 v [mesh] building_mesh_1  [trash]  (Needs Rexport) [!]
      [ Add Active Material Slot ]
    v [mat] wood_mat  (slot 0)  [trash]
          Trim:        [ Trim01  v ]
          Trim Image:  [ old_wood v ]

v Export Hooks            (collapsed)
    ... FBX / glTF / OBJ / ... status
    [ Re-attach Export Hooks ]
    [ Trim-Synced Export  v ]
    [ Dry Run Check ]
```

**Terminology.** The UI uses the user's words: **Trim** = the trim *sheet*,
**Trim Image** = the image placed on it. In code those are `Sheet` and
`TrimItem`.

**The tree is opt-in.** `Add Mesh From Selection` adds rows, `Add Active
Material Slot` adds slots. A slot with no row is simply not listed and is *not*
transformed — that is intended, not a bug.

# 4. Setting up a test project

You need a project folder. The Electron tool can make one (`npm run dev` in
`LJTrimMaster/`), but for add-on testing a hand-written folder is faster:

```
<root>/
  projectData.json
  image_dump/
    wood_BaseColor.png     wood_Normal.png
    stone/wall_BaseColor.png
```

Minimal `projectData.json`:

```json
{
  "version": "1",
  "defaults": { "defaultTrimResolution": { "width": 2048, "height": 2048 } },
  "maps": {
    "suffixDelims": ["_", "-", "."],
    "knownMaps": ["BaseColor","Roughness","Metallic","AO","Normal","Height","Emissive","Opacity"]
  },
  "sheets": [{
    "id": "sheet-1", "name": "Trim01",
    "resolution": { "width": 2048, "height": 1024 },
    "enabledPresetNames": [],
    "items": [{
      "id": "trim-1", "assetBaseName": "wood",
      "transform": { "position": {"x":0.25,"y":0.25}, "scale": {"x":0.2,"y":0.3}, "rotation": 0 },
      "crop": { "x": 0, "y": 0 }
    }]
  }]
}
```

Semantics that are easy to get wrong when hand-editing:

- `position` is the trim's **centre**, normalized 0–1 against the sheet.
- `scale` is normalized 0–1; **a negative component mirrors that axis**.
- `rotation` is **degrees, counter-clockwise-positive**.
- `crop` is a **symmetric inset** 0–0.5: `crop.x` trims off left AND right.
- `id` on an item is the **trim id** — the add-on's only resolution key.
- `maps` is optional. Without it the add-on falls back to built-in defaults and
  can then disagree with the tool about names like `old_wood_v2.png`.

# 5. Run the existing suites first

They all pass right now. If one fails, that is your first finding. Blender is
**not on PATH**:

```bash
BLENDER="C:/Program Files/Blender Foundation/Blender 5.1/blender.exe"
cd LJTrimMaster/Blender

python tests/test_affine.py                                              # 43 checks, no Blender
"$BLENDER" --background --factory-startup --python tests/probe_uvwarp.py        # 11 checks
"$BLENDER" --background --factory-startup --python tests/smoke.py               # register/draw canary
"$BLENDER" --background --factory-startup --python tests/test_sync_roundtrip.py # 109 checks
```

**Never drive exporters through the Blender MCP bridge — it crashed Blender
twice.** Test headlessly in a separate process, or by hand in a real session.

# 6. What to actually test — the untested surface

**Everything below has been verified headlessly and none of it has ever been
clicked.** The panel has never been rendered by a real Blender UI. That is the
gap you are here to close, so weight your effort accordingly.

## Highest value: the panel itself

- Does it draw at all, at a narrow N-panel width? Do the trash icons and status
  badges crowd out the name?
- **Does anything crash on redraw?** The previous version crashed because a draw
  path wrote to a Mesh. Blender forbids writing to any ID from `draw()`
  (verified fact 15). `tests/smoke.py` asserts read paths mutate nothing, but
  only a real UI exercises the real draw.
- Expand/collapse arrows on mesh and slot rows.
- The two dropdowns. **This is the most fragile thing in the rework.** They are
  `EnumProperty` with custom `get`/`set` that translate between a list position
  and the durable `trim_id` string, because a dynamic enum silently falls back
  to its first item when the identifier it held disappears. Specifically try:
  - Pick a Trim, then a Trim Image. Does the second list filter to the first?
  - Change the Trim to a different sheet — the Trim Image should **clear**, not
    keep a stale label.
  - Assign, then edit `projectData.json` so that trim moves to another sheet.
    The row should say **Needs Rexport**, and the Trim dropdown should now show
    the *new* sheet — the sheet is derived by scan, never stored.
  - Assign, then delete that trim from `projectData.json`. The row must say
    **Missing trim link** and keep showing `was: <name>`. It must **not**
    silently re-point at a different trim.

## The object/mesh relationship

Rows are keyed by **object**, but UVs are **mesh** data. Two objects sharing a
mesh (Alt+D linked duplicate) share one UV array and cannot hold different
assignments, so an edit on one row **propagates to every row sharing that mesh**
and the row shows `shared by N`.

- Alt+D a registered object, add the duplicate, change one row's Trim Image.
  Both rows must change together.
- Shift+D (a full copy, separate mesh) must stay independent.
- Delete an object that has a row. The row must survive, say **Missing mesh**,
  and **not** be auto-pruned — an undo or a library reload can null a pointer
  transiently, and silently deleting the assignment would lose real work. Only
  the trash icon removes.

## Append / link

- Assign slots, save, then **append** that object into a different `.blend` that
  also has the add-on. It arrives carrying a mirror on the mesh but no registry
  row — Blender has no `append_post` handler. **Refresh** should adopt it.
- Open a saved file: `load_post` should adopt mirrors automatically.

## Export — the part that must never be wrong

- Assign, then `File > Export > FBX`. Re-import and confirm the UVs are in sheet
  space, and that the scene's own UVs are unchanged.
- Export **OBJ**. Native `File > Export > Wavefront` is a C operator and cannot
  be hooked — it will ship **untransformed** UVs. `File > Export > Trim-Synced
  Export > OBJ` is the path that works. Confirm both behave as described; the
  Export Hooks panel should say so.
- Turn **Toggle Transform on Export** off. The export must be byte-identical to
  what Blender would normally write.
- Put an object in **Edit Mode** and export. It must be skipped with a loud
  warning, never silently untransformed.
- Two trims on one mesh **plus** a UV-affecting modifier (UV Warp, UV Project,
  Geometry Nodes, Mirror with UV offsets, Array with UV offsets) must be
  **refused with a reason** — a UVWarp cannot be masked per material slot, so
  there is no correct answer to pick.
- One trim plus such a modifier uses the evaluated path (two temporary UVWarps)
  and should still be correct. Check no `__ljtm_` modifiers survive afterwards.

**The one unacceptable outcome is a file written with untransformed UVs and no
warning.** Anything that produces that is a top-severity bug regardless of how
obscure the path.

## The rest

- **Create Material From Trim Image**: the list must show the tool's
  *normalized* asset name, and must include subfolder assets as `stone/wall`.
  Names come from grouping, so they may match no file on disk exactly — that is
  correct, not a bug. Clicking twice must rewire the existing material rather
  than leaving `wood.001`.
- **Refresh** should: re-read `projectData.json` past the mtime cache, rescan
  `image_dump/` recursively, adopt appended meshes, and re-evaluate statuses.
- **Hidden trims.** Hide a trim in the tool (the toggle in the Outliner).
  Every slot pointing at it must report **"Trim hidden"** - *not* "Missing trim
  link" - must vanish from the Trim Image dropdown, and must be refused at export
  with a message saying to unhide it. Showing it again must clear the status
  with no re-picking.
- **The sidecar** at `<root>/blender_links/` should update on every assignment
  change, on export, and on save — with no button and no toggle. Check it also
  behaves on an unsaved `.blend` (it should quietly do nothing until saved).
- With the tool running, edit a trim and watch the panel pick it up. The tool
  autosaves 800 ms after each edit and writes atomically, so the add-on should
  never see a torn file.

# 7. Things that are deliberate — do not report these

- An unlisted material slot is not transformed. Opt-in is the design.
- The sheet is never stored, only derived. Move to Sheet in the tool therefore
  needs zero add-on work.
- `last_exported` is **informational**. If it is wrong the export is still
  correct, because the affine is derived fresh every time. A bad record can only
  produce a wrong *list*, never wrong UVs.
- The add-on never inspects a material. Create Material is pure convenience and
  nothing depends on it.
- Overlapping trims are user error. Neither side detects them.
- `asset_base_name` is a **label** and never a matching key.
- Old `.blend` files losing assignments — accepted breaking change.

# 8. Known-good facts you must not re-derive

These cost real time to establish. Full list in `HANDOFF.md` Part 2.

1. `export_scene.fbx` and `export_scene.gltf` are **Python** operators in 5.1.2,
   so their `execute` is reassignable. The patch is on the operator *class*, so
   every call path is caught — including other add-ons calling `bpy.ops`.
2. `wm.obj_export`, `wm.ply_export`, `wm.stl_export`, `wm.usd_export`,
   `wm.alembic_export` are **C** operators and cannot be intercepted from Python.
3. Blender's UVWarp is `uv' = S·R·(uv + offset − center) + center`.
4. A UVWarp `scale` component **may be negative and does reflect** — that is what
   lets the two-modifier decomposition express a mirrored trim.
5. Blender 5.1.2 has a bug in its own FBX **importer**: it raises on any file
   containing a light. Affects re-import in round-trip tests only. Delete Light
   and Camera before exporting in tests.
6. An operator's own properties are **not** on `operator.bl_rna` — that has 14
   base fields. The real ones come from `bpy.ops.<id>.get_rna_type().properties`.
7. **You may not write to any ID datablock from inside `draw()`.** Scene is an ID
   too, so moving state to the Scene does not exempt it.
8. `MeshPolygon.loop_total` and `material_index` are both still
   `foreach_get`-able in 5.1.2.

# 9. How to report

Add findings to `Bugs.md` under `# Blender Addon`, newest first. For each one:

- What you did, in the fewest steps that reproduce it.
- What happened, with the traceback if there is one.
- What you expected, and which rule above it violates.
- Severity: **top** if a file can be written with untransformed UVs and no
  warning, or if the `.blend`'s own UVs changed. Everything else is below that.

Two unrelated add-ons are broken on this machine's Blender 5.1.2 — `GrabDoc`
declares a max version of 4.7.0, and something raises
`AttributeError: 'module' object has no attribute 'ActionFCurves'`. Neither
touches this work; ignore both.
