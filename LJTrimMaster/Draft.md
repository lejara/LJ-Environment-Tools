# LJ Trim Master

## Abstract

Texture tool for building trim sheets or atlases. Done by decoupling trims to it own image then by using the editor build a custom trim texture.
Then using blender and unity intergration to provide automated updates models and its materials
This is designed to customize trim sheets after the texture has been made. Moving the trim sheet setup later rather than eailier.

### Scope

**The tool is renderer-agnostic.** It authors trim sheets and the UV transforms that go with them; it does not care what consumes them. Unity and Blender are the first two integrations, not the target. The same trim data is meant to drive Unreal, Godot, an offline renderer, or anything else that reads a mesh and a texture.

Concretely, that means the Blender addon must transform UVs for **every** export format Blender supports, not just FBX. Someone exporting OBJ into Substance, USD into a lookdev pipeline, or glTF for the web must get the same corrected UVs as someone exporting FBX into Unity.

## Implmentation Plan

Will Work in Phases

Phase 1: Show class and relationship diagram, plan code strcuture.

Phase 2: Code UI editor, Viewport, Sidebar, Trim Builder

Phase 3: Code Blender Sync Addon

Phase 4: Code Unity Addon (TBD)

## Tech Stack

Editor is built as an Electron app with a TypeScript + React renderer. Main process owns filesystem work (project I/O, scanning `image_dump/`, loading `preset-packs/` and `maps.yaml`) and exporting. Renderer owns the UI and holds the in-memory editor state.

## High-Level implmementation / Workflow

User opens tools. A startup screen shows: **New Project**, **Open Recent**, **Browse**. Recent projects are stored in a user-scoped config file (not in the project itself). Selecting New creates a folder structure in the chosen user directory; Open loads an existing `projectData.json`.

Folder sturture:

- `/root`
  - `projectData.json` (project data, tirm data, settings, user prefs)
  - `/image_dump` (the image dump, will be used to create place trims)
  - `/placeholder slots` (TBA, just add this folder)
  - `/output` (all image output made by the tool)

All textures that will be part of a trim sheet must be in image_dump folder.
The tool will use those image to build a trim sheet and is placed and adjusted by the user using the editor.
Export of an image trim is always done automatically. Basic undo and redo will be added.
Then by tracking transform offsets the tool will update mesh UV in the exporting event process using the blender addon (explained below)

When UV unwrapping a model. The user must use the image in the image dump folder to unwrap. Then assign the object to a avaiable trim sheet made in the tool.
Then by tracking all materal slots that uses an image the tool has a trim for. A UV sync to its trasnfrom of all islands in its assgined material slot will be applied when the object is exported.

## Texture Packing

Trim sheets can export multiple output textures per sheet — a base color sheet, a normal sheet, a packed ORM sheet, etc. — all sharing the same trim layout. What gets exported is controlled by pack presets.

### Image Dump Naming Convention

Each source image in `image_dump/` uses a suffix to declare which map it is. Example set for one texture:

- `wood_BaseColor.png`
- `wood_Roughness.png`
- `wood_Metallic.png`
- `wood_Normal.png`
- `wood_AO.png`

The delimiters and the list of known map names are set once in `maps.yaml`, which lives next to the tool binary alongside `preset-packs/`. Tool-wide config, not per-project, so every project shares the same map vocabulary.

```yaml
suffixDelims: ["_", "-", "."]
knownMaps:
  - BaseColor
  - Roughness
  - Metallic
  - AO
  - Normal
  - Height
  - Emissive
```

**More than one delimiter can be live at once**, so a dump that mixes conventions still reads correctly — `wood_Normal.png`, `wood-Roughness.png` and `wood.AO.png` all resolve to the asset `wood`.

Rather than ranking the delimiters against each other, every configured delimiter is rewritten to a single `_` before the name is split, and the split then runs on that one delimiter. Delimiters are matched longest-first, so a two-character delimiter isn't chewed up by a one-character one that is its prefix.

Normalization applies to the base name too, which means `old-wood_Normal.png` and `old_wood-Roughness.png` group into **one** asset named `old_wood`. That merging is the point — it is what lets a messy dump read as one set of textures — but it does mean a displayed base name can differ from the literal filename. If two files end up in the same base+map slot, the first wins and the loser is reported as a warning rather than dropped silently.

A single string is still accepted, so older `maps.yaml` files need no edit:

```yaml
suffixDelim: "_"
```

Only the base map (BaseColor by default) appears in the Asset Section and Outliner. Siblings are resolved by suffix automatically at export time.

### Preset Packs Folder

Lives next to the tool binary in `preset-packs/`. Presets are global — shared across all projects. Tool ships with a few factory presets on first install.

### Preset File Format

YAML. **Each file is one preset, and a preset is a named bundle of texture outputs.** A preset describes a whole target rather than a single file — tick "Unity HDRP" on a trim sheet and it emits BaseColor, Normal and MaskMap together, all sharing that sheet's trim layout.

Each output has one of two modes: `copy` (passthrough of one map) and `pack` (channel-packed output).

Dropdown identity comes from the `name:` field inside the file, not the filename. If two presets share a `name:`, the first one loaded wins and the loser is logged as a warning.

A top-level `format:` is the default for any output that doesn't set its own.

**Multi-output form** — `unity-hdrp.yaml`, abridged:

```yaml
name: Unity HDRP
format: PNG_RGBA

outputs:
  - mode: copy
    outputSuffix: _BaseColor
    source: BaseColor

  - mode: copy
    outputSuffix: _Normal
    source: Normal

  - mode: pack
    outputSuffix: _MaskMap
    channels:
      R: { source: Metallic, fallback: 0.0 }
      G: { source: AO, fallback: 1.0 }
      B: { constant: 0.0 }
      A: { source: Roughness, invert: true, fallback: 0.5 }
```

**Single-output short form** — when a preset writes exactly one texture, the `outputs:` list can be dropped and the output written at the top level:

```yaml
name: BaseColor
mode: copy
outputSuffix: _BaseColor
source: BaseColor
format: PNG_RGBA
```

Per-channel keys, `pack` only:

| Key           | Meaning                                                                                                |
| ------------- | ------------------------------------------------------------------------------------------------------ |
| `source`      | known map name from `maps.yaml` (required unless `constant` is set)                                    |
| `fromChannel` | `R \| G \| B \| A \| L` — default `L` = luminance                                                      |
| `invert`      | `true \| false` — default `false`                                                                      |
| `fallback`    | `0.0`–`1.0`, used when the source map is missing. Taken **as-is**; it is not run back through `invert` |
| `constant`    | `0.0`–`1.0`, skip the source and fill the channel flat                                                 |

Two templates ship in `preset-packs/` for users to copy: `copy.template.yaml` (short form) and `pack.template.yaml` (multi-output form).

Validation is lenient by one level at a time. A bad entry in `outputs:` is skipped with a warning and the preset keeps its other outputs; only a preset left with **no** usable output is dropped entirely. Two outputs declaring the same `outputSuffix` would race to write one filename, so the later one is skipped and warned about.

### Export Behavior

For each trim sheet, the tool runs every preset selected in that sheet's settings. For each output of each preset, it walks the outliner and blits — using the stored per-image transforms — either the resolved source map (copy) or the per-channel composite (pack) into the output canvas. Output filename is `<TrimName><outputSuffix>.png`.

Missing sources warn but do not block the export — the affected channel falls back to its `fallback` value, and the warning is reported on `EXPORT_COMPLETED` and shown in the toolbar status.

Sheet area that no trim covers is filled with each channel's `fallback` for `pack` outputs, and left transparent for `copy` outputs. That is what keeps an empty region of a mask map reading as unoccluded rather than fully-occluded black, so UV bleed at a trim edge doesn't darken the seam.

Normal maps are only valid with `mode: copy`. Using `source: Normal` inside a pack preset is refused with an error, since channel mixing on a normal map is nonsense.

### Normal Map Rotation

The handedness of the source maps is declared per preset (or per output) with `normalConvention: OpenGL | DirectX`, defaulting to OpenGL — Unity's convention, and what Substance Painter's Unity preset exports. It decides the sign of the rotation applied to the (R,G) vector; set it wrong and rotated trims light as though the sun moved.

When a trim's transform rotation is non-zero and the source map is typed as `Normal`, the encoded RGB vectors are rotated to match — after sampling but before blitting into the output canvas. The (R,G) channels are rotated by the same angle as the transform; B is left alone. This keeps lighting correct on rotated trims. Copy strategy for a `Normal` source always runs through this path; scale sign flips also flip the corresponding (R or G) axis.

## Editor

### Toolbar

Sits at the bottom of the editor and contains three controls:

- **Settings gear** — opens the Settings modal (see below).
- **Auto Export** — toggle. When on, a timer polls each trim sheet's `isDirty` flag and re-runs the export for any dirty sheet, then clears the flag. Any property change (transform, crop, add/remove image, reorder, enabled-presets change) marks the current sheet dirty.
- **Build** — manual full re-export of the active trim sheet, regardless of dirty state.

Global refresh is a separate action (also on the toolbar): re-scans `preset-packs/`, re-reads `maps.yaml` and `projectData.json`, and refreshes any dependent UI state. Shared control — other sections can hook into it to trigger their own refresh logic, so we only maintain one refresh entry point.

### Tab Bar

This is where we can add, rename or remove trim sheets.

### Viewport

This will preview the trim sheet only and provide an outline when an image is selected.

### Sidebar

#### Properties Section

This will contain transform and image adjutments controls.

Transform: position, Scale, Rotation

Image Crop: x, y. FOr now we only crop both x and y axis uniformaly.

For QOL:

All value editors will be a Quantity Input. The value will present and will contain top and bottom button to increase or decrease a value. As well as a mouse pan tool such that when the user hold left click the horizonail direction will determind to increase or decrease the value.

#### Asset Section

Folder set in to the image dump folder. The Assets Section will list all images with a preview.

There will be a button on the top left of an image to allow the user to add it into the trimsheet.

When added. The image will render to the veiwport and be added in the outliner.

#### Outliner

This is where all added image will be listed. Basically a list view for whats inside the trimsheet. The user can click on one of the listing and the properties section will update to those image properties then the user can update the properties. There will be also a button to remove image from the trim.

**Order = z-order.** Top of the list is drawn last (on top). The list is reorderable by drag.

#### Undo / Redo

Scope is limited to per-sheet **transform and crop edits only** in v1. Add, remove, rename, reorder, and tab-level actions are not undoable. Each trim sheet owns its own history stack; switching tabs does not clear it.

### Settings Modal

Opened by the toolbar's settings gear. Holds project-wide defaults that seed new trim sheets and other future defaults. For v1:

- **Default Trim Resolution** — width × height, used when the user creates a new sheet via the tab bar's `+` button. Editing this here does not retroactively resize existing sheets — each sheet keeps its own resolution.

Kept as a modal (not a sidebar tab) so the editor viewport stays uncluttered. The panel is designed to grow — more defaults can be added as the tool matures.

#### Trim Sheet Settings

Per-sheet settings panel. Contains:

- **Output resolution** (width × height in pixels). Each trim sheet has its own resolution; not shared globally.
- **Enabled presets** — multi-select dropdown listing every preset loaded from `preset-packs/` by its `name:` field. Whatever is ticked is what the trim sheet exports on the next export event.

## Blender Intergration

Image Dump folder is source of truth.

There will be a ui panel to set what TrimMaster project the addon is using. When added the addon will declare it self as a sync hook to the tool by writing into a json folder. Then it will watch for changes in the projectData.json and apply it to the blender instance.

There be an updated list of all trims and what mesh and its material is assigned to.

It will also have batch update tools. For changing what material/material goes to what trim sheet.

Another QOL of life tools is simlair to LJ material import and thats to allow a single click button to import all image dump images and create a basic material of its base color and normal texture. if normals is missing thats okay just warn the user.

### Export Format Coverage

UV transforms are applied **at export time only** — the UVs stored in the `.blend` are never modified. Coverage differs by format because of how Blender implements each exporter:

- **FBX and glTF** are Python operators, so their `execute` is wrapped. A plain `File > Export` click is transparent and catches every call path, including other addons that invoke the exporter through `bpy.ops`.
- **OBJ, PLY, STL, USD and Alembic** are C operators and cannot be intercepted from Python. They are served by `File > Export > UV-Transformed Export`, which applies the transform, invokes the native exporter, and restores in a `finally`.

Every format is supported today. What differs is whether the *native* menu entry is transparent. Because the tool is renderer-agnostic, transparency everywhere is the goal, not an extra: a habitual click on `File > Export > Wavefront (.obj)` must not silently ship untransformed UVs. The C exporters' menu entries are themselves Python and can be re-routed, which is the route to that.

### Blender Workflow

1. user selects an object and unwraps normally.
2. in the uv viewport. There will be a side panel called Trimed master here. you can set the project root and multi select what object goes to what trim sheet.
3. When the user exports weather it be normally or by using LJ exporter. Trim master will make sure the UV transform offsets are applied.

optionally, if a user multi selects objects and some are assign to the same trim sheet. Allow them to change it in the UI panel. If the multi select has different assignment then what ever the user selects applies to all.
