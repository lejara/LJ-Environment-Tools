# LJ Environment Tools — Blender Addon Notes

## Persistent settings: two-tier pattern

Settings that should "stick" across sessions live in **both** places:

1. **`AddonPreferences`** (global default, saved to Blender's user prefs on disk).
2. **`Scene` PropertyGroup** (per-blend-file, saved with the .blend).

Blender only allows **one `AddonPreferences` class per addon** (`LJEXPORT_AP_preferences`). Modules that need persistent settings extend it rather than declare a second one:

- Define `_SHARED_PROP_NAMES` and `_shared_annotations()` in the module.
- At module-import time, merge into the existing class:
  ```python
  _prefs.LJEXPORT_AP_preferences.__annotations__.update(_shared_annotations())
  _prefs.addon_prefs_draw_extras["<module_key>"] = draw_addon_prefs
  ```
- Declare a per-scene `PropertyGroup` (`*_PG_scene`) with the same annotations **plus** an `initialized: BoolProperty(default=False)`.
- Register it as a `PointerProperty` on `bpy.types.Scene` in `__init__.py::register()`.

The flow:

- **Load** (`load_post` handler → `seed_existing_scenes`): copies global → scene if `initialized` is False, then marks initialized. Run from `__init__.py::register()` via a deferred timer because Blender's install/enable register context restricts `bpy.data.scenes`.
- **Action** (operator `execute` → `sync_to_global`): copies scene → global and calls `bpy.ops.wm.save_userpref()`.

This means: typing a value but never running an operator means it stays per-file but doesn't update the global default for new blend files. Match this trade-off when adding new persistent settings — don't add `update=` callbacks on the StringProperty just because the existing one doesn't have them.

## Reload-on-reinstall

`__init__.py` re-imports submodules via `importlib.reload(...)` when `"bpy" in locals()`. Order matters: `preferences` must reload **before** `materials_import` so the AddonPreferences class is recreated fresh before `materials_import` re-merges its annotations into it.

Static analyzers flag `"X" is unbound` inside the reload block — that's a false positive; the `if "X" in locals()` guard handles the binding at runtime.
