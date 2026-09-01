# Handoff Prompt — LJ Trim Master

Paste everything below the line into a fresh session.

---

I'm building **LJ Trim Master**, a texture tool for authoring trim sheets / atlases, with Blender and Unity integrations planned. Working directory is the `LJTrimMaster/` folder inside my Unity project at `Assets/LJ Environment Tools`.

## Read these first

- `LJTrimMaster/Draft.md` — the plan / spec. Source of truth for behavior.
- `LJTrimMaster/ClassDiagram.md` — Phase 1 deliverable: class relationship diagram, UI component tree, folder layout, event bus spec.
- `LJTrimMaster/Brainstroming.md` — Unity integration ideas only. **Explicitly out of scope**, do not plan against it.

## How we work

We work in **lockstep**. Do not start the next phase without my explicit go-ahead. Ask me about gaps rather than guessing on anything that changes the architecture.

Code structure rules already agreed:
- **One class/object per file.**
- UI components live in their own folder (`renderer/ui/`), data models in `renderer/models/`, non-UI logic split between `main/` and `renderer/services/`.

## Phase status

- **Phase 1 — class + relationship diagram, code structure: COMPLETE and approved.** Don't redo this; read `ClassDiagram.md` and build against it.
- **Phase 2 — code the UI editor (Viewport, Sidebar, Trim Builder): NOT STARTED. Awaiting my go-ahead.**
- Phase 3 — Blender sync addon. Not designed yet.
- Phase 4 — Unity addon. TBD.

## Settled decisions (do not re-litigate)

**Stack:** Electron + TypeScript + React. Main process owns filesystem I/O (project scaffolding, scanning `image_dump/`, loading `preset-packs/` + `maps.yaml`, writing `/output`) and the export pipeline. Renderer owns UI and in-memory editor state via zustand-style stores in `renderer/state/`.

**Startup:** Startup screen with New / Open Recent / Browse. Recent projects tracked in a user-scoped config file, not in the project.

**Viewport UX:** Preview + selection outline only. **No canvas drag or click-to-select.** Selection happens via the Outliner; all transform editing happens in the Properties panel.

**Trim sheet resolution:** Per sheet (per tab), set in that sheet's settings panel. New sheets are seeded from a project-wide default.

**Settings modal:** Opened by the toolbar gear. Holds project-wide defaults — currently just `defaultTrimResolution`. Editing it does **not** retroactively resize existing sheets. Designed to grow.

**Outliner:** List order **is** z-order — top of list draws last (on top). Reorderable by drag.

**Undo/redo:** Scope is **transforms + crop only**, v1. Per-sheet history stack that survives tab switches. Add / remove / rename / reorder / tab-level actions are **not** undoable.

**Toolbar (bottom of editor):** settings gear, **Auto Export** toggle (timer polls each sheet's `isDirty` flag and re-exports dirty sheets), **Build** (manual full re-export of active sheet regardless of dirty state), and a global **Refresh** (re-scans `preset-packs/`, re-reads `maps.yaml` + `projectData.json`).

**Event bus — narrow by design.** Only two event families are on the bus: `REFRESH_*` and `EXPORT_*` (`REFRESH_REQUESTED`, `REFRESH_COMPLETED`, `EXPORT_STARTED`, `EXPORT_COMPLETED`, `EXPORT_FAILED`). Everything else — property edits, selection, tab switches, project open/save — uses state stores or direct service calls. Notably: `AutoExporter` clears `isDirty` **inline** after `Exporter.export()` returns, *not* via the bus. If you're tempted to add an event outside those two families, use a store subscription or direct call instead and tell me why you wanted the event.

**Asset references:** `TrimImage` references its source by `assetBaseName` (a string), not by an `Asset` object. Sibling maps (Roughness, Normal, …) are re-resolved from the current `image_dump/` scan at export time, so adding a Normal map later is picked up automatically.

**Normal maps:** When a trim's transform rotation is non-zero and the source map is typed `Normal`, the encoded RGB vectors get rotated to match — (R,G) rotated by the same angle, B untouched, and negative scale flips the corresponding axis. Normal maps are only valid with `mode: copy`; `source: Normal` inside a pack preset is an error.

**Texture packing:** Pack presets are global YAML files in `preset-packs/` next to the binary, shared across projects. Preset identity comes from the `name:` field, not the filename; on duplicate names the first loaded wins and the loser is logged as a warning. `maps.yaml` (also next to the binary) defines the suffix delimiter and known map names. Only the base map (BaseColor) appears in the Assets panel and Outliner. Missing sources warn but don't block export — the channel falls back to its `fallback` value.

## Known-open items

- Export event payload does **not** currently carry a `trigger: "manual" | "auto"` field. I declined it for now; revisit only if a listener actually needs to distinguish Build from Auto Export.
- Phase 3 (Blender) will subscribe to `EXPORT_COMPLETED` via a JSON hook file, but the addon itself isn't designed yet.

## What I want next

Ask me for a go-ahead before writing code. If I've already given it in my message, start Phase 2 by scaffolding the Electron + React project and the file structure exactly as laid out in `ClassDiagram.md`.
