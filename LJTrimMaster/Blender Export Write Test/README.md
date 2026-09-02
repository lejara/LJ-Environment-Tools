# UV Export Transform

Blender extension (v0.3.0) that transforms the UVs of a specific list of objects
**only inside the exported file**. The UVs in the .blend are never modified.

Architecture **option 1** from the handover: in-Blender export wrap. FBX and glTF
are transparent on a plain `File > Export` click. The C-operator formats need one
extra menu click.

## Install

Already installed on this machine as a directory junction, so edits to
`uv_export_transform/` are live in Blender:

```
%APPDATA%\Blender Foundation\Blender\5.1\extensions\user_default\uv_export_transform
  -> <this repo>\uv_export_transform
```

To reload after an edit: disable/re-enable the add-on in Preferences, or restart
Blender. To install elsewhere, zip the `uv_export_transform/` folder and use
`Preferences > Get Extensions > Install from Disk`.

## Use

`3D Viewport > N sidebar > UV Export` tab.

1. Select mesh objects, press **+** to add them to the list.
2. Set per-object **Offset / Scale / Rotation / Pivot**, and which UV map to hit
   (Active, All, or a Named one).
3. **Dry Run Check** applies the transform, prints the before/after UV ranges to
   the System Console, restores, and verifies the restore was bit-exact. Writes
   no file.
4. Export:
   - **FBX / glTF** — just use `File > Export` as normal. Hooked.
   - **OBJ / PLY / STL / USD / Alembic** — `File > Export > UV-Transformed Export`
     (also reachable from the panel).

**Transform On Export** is the master switch. Off means exports are byte-for-byte
what Blender would normally write.

Transform order is scale → rotate → translate, all about the pivot.

## How the hooks work

`export_scene.fbx` and `export_scene.gltf` are Python operators in Blender 5.1.2
(verified), so their `execute` is reassigned on register. The wrapper applies the
transform, calls the original, and restores in a `finally`.

`wm.obj_export`, `wm.ply_export`, `wm.stl_export`, `wm.usd_export` and
`wm.alembic_export` are C operators — a native menu click on those runs entirely
inside C and cannot be intercepted from Python. `uvxf.export` handles them by
applying the transform and then invoking the exporter with `EXEC_DEFAULT`, so the
write finishes before the restore runs.

The `Export Hooks` sub-panel shows the live status of each. `UNAVAILABLE` just
means that format's add-on is currently disabled.

## Direct vs Evaluated (handover Q4)

Per-entry **Method**, because a modifier that generates or rewrites UVs runs
*after* the base UV map:

| Method | What it does | When it reaches the file |
| --- | --- | --- |
| **Direct** | Rewrites the base UV map buffer | Always |
| **Evaluated** | Appends two temporary UVWarp modifiers to the end of the stack | Only when the exporter applies modifiers |
| **Auto** (default) | Evaluated if the object has UV-affecting modifiers *and* the exporter is applying them, else Direct | Always |

Auto detects `UV_WARP`, `UV_PROJECT`, `NODES` (Geometry Nodes), `MIRROR` with UV
mirroring, and `ARRAY` with UV offsets. Subsurf, Multires and Solidify are
deliberately *not* on that list: they interpolate or copy UVs affinely, and an
affine transform commutes with that, so Direct stays correct through them.

### Why the evaluated path takes *two* UVWarp modifiers

Measured convention of Blender's UVWarp (see `probe` results in the commit
history):

```
uv' = S · R · (uv + offset − center) + center
```

The offset is applied **before** the transform, and rotation **before** scale.
Ours is `uv' = R · S · (uv − P) + P + O`. A single UVWarp cannot express that —
matching `R·S` against `S'·R'` forces `sx² = sy²` or a zero rotation, so any
non-uniform scale combined with a rotation is out of reach. Two chained UVWarps
do reach it exactly:

```
M1: center=P,   offset=0, rotation=0,     scale=S   ->  S·(uv − P) + P
M2: center=P+O, offset=O, rotation=theta, scale=1   ->  R·(uv1 − P) + P + O
```

This is asserted directly by the test suite: Direct and Evaluated produce
identical UVs in the written FBX for `scale=(1.5, 0.75)`, `rotation=30°`.

## Safety properties

- Restore runs in a `finally`, so a failed or cancelled export still leaves the
  scene clean (covered by a test).
- Re-entrancy guard: `uvxf.export` calling a hooked exporter cannot double-apply.
- Direct targets are de-duplicated on `(mesh datablock, UV layer)`, so objects
  sharing mesh data are transformed once. Evaluated targets are *not* deduped —
  modifiers are per-object, so each needs its own pair.
- Temp modifiers are tracked by name, not by reference, and removed in the
  `finally`. `Export Hooks` shows a **Purge Leftover Modifiers** button if any
  ever survive.
- Meshes and objects are `update_tag()`-ed and the view layer re-evaluated after
  the change, because exporters read the *evaluated* mesh.
- Objects in Edit Mode are skipped with a warning (BMesh would overwrite the
  change on mode exit).

## Tests

```bash
"C:/Program Files/Blender Foundation/Blender 5.1/blender.exe" --background --python tests/test_fbx_roundtrip.py
```

```bash
"C:/Program Files/Blender Foundation/Blender 5.1/blender.exe" --background --python tests/test_evaluated_path.py
```

Both export through the real `export_scene.fbx` operator — the same one the
`File > Export` menu calls — re-import the written file, and assert on its
contents. They exit non-zero on failure. They run in a **separate headless
Blender process**, so they cannot disturb an open session.

Last run: **20/20 checks passed.**

`test_fbx_roundtrip.py` (8): hooks attach; the FBX carries
`(0.5625, 0.9375, 0.25, 0.75)` while the scene still reads
`(0.125, 0.875, 0.0, 1.0)`; the master switch off is a true no-op; the scene is
restored even when the export raises.

`test_evaluated_path.py` (12): Direct and Evaluated agree under non-uniform scale
+ rotation; Auto resolves to Evaluated when a UV modifier is present; the file
carries `ours(modifier(uv))` and provably not `modifier(ours(uv))`; no temp
modifiers or base-UV changes survive; Auto falls back to Direct when the exporter
is not applying modifiers.

Both tests delete the Light and Camera before exporting. That is a workaround for
a **Blender 5.1.2 bug in its own FBX importer** — `blen_read_light` sets
`lamp.cycles.cast_shadow`, which no longer exists, so importing any FBX
containing a light raises `AttributeError`. It affects the re-import half of the
round trip only, not this extension, and not exporting.

## Known limitations

- Shape keys, multires and other data that references UVs are not considered.
- The object list lives on the Scene, so it saves and loads with the .blend, but
  it does not follow objects across linked/appended libraries.
- The evaluated path appends to the end of the modifier stack; a modifier using
  `use_pin_to_last` would still sit after it.
- Not yet verified against a real ZenUV-trimmed production asset — only the
  default cube.
