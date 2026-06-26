# Setting up symlinks / junctions

The three plugins live in this repo, but Painter and Designer only load from their own user plugin folders. Use a Windows **directory junction** so changes you make in the repo are picked up live by the host app — no copy step, no committing from inside the app's plugin folder.

Run the commands below from an **elevated** (or developer-mode) Command Prompt. Both `mklink /J` (junction) and `mklink /D` (symlink) work; junctions don't need admin once Developer Mode is on.

Replace `<REPO>` with the absolute path to this repo. On the author's machine that's:

```
C:\Users\leone\OneDrive\Desktop\Yei City\Yei City\Assets\LJ Environment Tools
```

## Plugin target paths

| Plugin | Host | Target folder |
| --- | --- | --- |
| LJPainterIterate | Substance 3D Painter (Python) | `%USERPROFILE%\Documents\Adobe\Adobe Substance 3D Painter\python\plugins\LJPainterIterate` |
| LJSubPainterExportTool | Substance 3D Painter (QML) | `%USERPROFILE%\Documents\Adobe\Adobe Substance 3D Painter\plugins\LJSubPainterExportTool` |
| LJSubDesignerTools | Substance 3D Designer (Python) | `%USERPROFILE%\Documents\Adobe\Adobe Substance 3D Designer\python\sduserplugins\LJSubDesignerTools` |

> If your Painter / Designer installation uses a different "shelf" or plugin root, check **Edit → Settings → Plugins** (Painter) or **Tools → Plugin Manager** (Designer) for the actual path it scans.

## Commands (cmd.exe)

```cmd
:: LJPainterIterate  →  Substance 3D Painter Python plugins
mklink /J ^
  "%USERPROFILE%\Documents\Adobe\Adobe Substance 3D Painter\python\plugins\LJPainterIterate" ^
  "<REPO>\LJPainterIterate"

:: LJSubPainterExportTool  →  Substance 3D Painter QML plugins
mklink /J ^
  "%USERPROFILE%\Documents\Adobe\Adobe Substance 3D Painter\plugins\LJSubPainterExportTool" ^
  "<REPO>\LJSubPainterExportTool"

:: LJSubDesignerTools  →  Substance 3D Designer user plugins
mklink /J ^
  "%USERPROFILE%\Documents\Adobe\Adobe Substance 3D Designer\python\sduserplugins\LJSubDesignerTools" ^
  "<REPO>\LJSubDesignerTools"
```

## Commands (PowerShell)

```powershell
$repo = "C:\Users\leone\OneDrive\Desktop\Yei City\Yei City\Assets\LJ Environment Tools"
$painterPy  = "$env:USERPROFILE\Documents\Adobe\Adobe Substance 3D Painter\python\plugins"
$painterQml = "$env:USERPROFILE\Documents\Adobe\Adobe Substance 3D Painter\plugins"
$designerPy = "$env:USERPROFILE\Documents\Adobe\Adobe Substance 3D Designer\python\sduserplugins"

New-Item -ItemType Junction -Path "$painterPy\LJPainterIterate"   -Target "$repo\LJPainterIterate"
New-Item -ItemType Junction -Path "$painterQml\LJSubPainterExportTool" -Target "$repo\LJSubPainterExportTool"
New-Item -ItemType Junction -Path "$designerPy\LJSubDesignerTools" -Target "$repo\LJSubDesignerTools"
```

## Verify

```cmd
dir "%USERPROFILE%\Documents\Adobe\Adobe Substance 3D Painter\python\plugins"
```

A junction shows up as `<JUNCTION>` next to the folder name and points back at the repo.

## Removing a junction

Use `rmdir` (not `del`) — this removes the link only, never the repo files:

```cmd
rmdir "%USERPROFILE%\Documents\Adobe\Adobe Substance 3D Painter\python\plugins\LJPainterIterate"
```

## After linking

1. Restart Painter / Designer.
2. **Painter** — open **Python** (or **Plugins**) menu, confirm `LJPainterIterate` is loaded; the **LJ Sub Painter Export Tool** dock should be available from the dock menu.
3. **Designer** — open **Tools → Plugin Manager**, confirm `LJSubDesignerTools` is enabled.
