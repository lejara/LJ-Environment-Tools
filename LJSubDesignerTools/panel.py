import os
import subprocess

import sd
from sd.api.sbs.sdsbscompgraph import SDSBSCompGraph
from sd.api.sdhistoryutils import SDHistoryUtils
from sd.api.sdproperty import SDPropertyCategory

try:
    from PySide6 import QtCore, QtWidgets
    import shiboken6 as shiboken
except ImportError:
    from PySide2 import QtCore, QtWidgets
    import shiboken2 as shiboken

from .graph_iterate import duplicate_graph
from . import tile_view

_DEFAULT_TILES_PER_ROW = 4
_REFRESH_INTERVAL_MS = 500

_SETTINGS_ORG = "LJ"
_SETTINGS_APP = "SubDesignerTools"
_TILES_PER_ROW_KEY = "tilesPerRow"
_EXPORT_FOLDER_KEY = "exportFolder"
_EXPORT_NAME_KEY = "exportName"
_ASSETS_FOLDER_KEY = "assetsFolder"
_MATERIALS_SUBDIR = "materials"
_TEXTURES_SUBDIR = "textures"

_SBSCOOKER_EXE = r"C:\Program Files\Adobe\Adobe Substance 3D Designer\sbscooker.exe"

_widgets = {}


def _settings():
    return QtCore.QSettings(_SETTINGS_ORG, _SETTINGS_APP)


def _load_tiles_per_row():
    raw = _settings().value(_TILES_PER_ROW_KEY, _DEFAULT_TILES_PER_ROW)
    try:
        return max(1, min(12, int(raw)))
    except (TypeError, ValueError):
        return _DEFAULT_TILES_PER_ROW


def _save_tiles_per_row(value):
    _settings().setValue(_TILES_PER_ROW_KEY, int(value))


def _load_export_folder():
    return _settings().value(_EXPORT_FOLDER_KEY, "") or ""


def _save_export_folder(value):
    _settings().setValue(_EXPORT_FOLDER_KEY, value or "")


def _load_export_name():
    return _settings().value(_EXPORT_NAME_KEY, "") or ""


def _save_export_name(value):
    _settings().setValue(_EXPORT_NAME_KEY, value or "")


def _load_assets_folder():
    return _settings().value(_ASSETS_FOLDER_KEY, "") or ""


def _save_assets_folder(value):
    _settings().setValue(_ASSETS_FOLDER_KEY, value or "")


def _materials_folder(assets_folder):
    return os.path.join(assets_folder, _MATERIALS_SUBDIR)


def _textures_folder(assets_folder):
    return os.path.join(assets_folder, _TEXTURES_SUBDIR)


def get_main_window(ui_mgr):
    if hasattr(ui_mgr, "getMainWindowPtr"):
        return shiboken.wrapInstance(
            int(ui_mgr.getMainWindowPtr()), QtWidgets.QMainWindow
        )
    return ui_mgr.getMainWindow()


def wrap_widget(ptr):
    if isinstance(ptr, int):
        return shiboken.wrapInstance(ptr, QtWidgets.QWidget)
    return ptr


def _ui_mgr():
    return sd.getContext().getSDApplication().getUIMgr()


def _main_window():
    return get_main_window(_ui_mgr())


def _current_comp_graph():
    graph = _ui_mgr().getCurrentGraph()
    return graph if isinstance(graph, SDSBSCompGraph) else None


def _open_graph_view(ui_mgr, graph):
    try:
        ui_mgr.openResourceInEditor(graph)
    except Exception as exc:
        print(f"[LJ] openResourceInEditor failed: {exc}")


def on_hello_world():
    QtWidgets.QMessageBox.information(
        None,
        "LJ Sub Designer Tools",
        "Hello, World!",
    )


def on_diagnose_3d_view():
    main_window = _main_window()
    candidates = tile_view.list_3d_view_candidates(main_window)
    if not candidates:
        cand_text = "No matching widgets found."
    else:
        rows = [
            f"{cls}\tvisible={vis}\tsize={size}\tobjectName='{name}'\twindowTitle='{title}'"
            for cls, name, title, vis, size in candidates
        ]
        cand_text = "\n".join(rows)

    capture_text = tile_view.diagnose_capture(main_window)

    text = (
        "== capture diagnostic ==\n"
        + capture_text
        + "\n\n== all candidates ==\n"
        + cand_text
    )
    print("[LJSubDesignerTools] 3D view diagnostic:")
    print(text)
    dlg = QtWidgets.QMessageBox(None)
    dlg.setWindowTitle("3D View Diagnostic")
    dlg.setText("3D view detection / capture report:")
    dlg.setDetailedText(text)
    dlg.exec()


class _PreviewScrollArea(QtWidgets.QScrollArea):
    def __init__(self):
        super().__init__()
        self._last_width = 0
        self._resize_timer = QtCore.QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(120)
        self._resize_timer.timeout.connect(_rebuild_tile_grid)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        w = self.viewport().width()
        if w != self._last_width:
            self._last_width = w
            self._resize_timer.start()


class _ClickableLabel(QtWidgets.QLabel):
    clicked = QtCore.Signal()

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class _IterationTile(QtWidgets.QFrame):
    def __init__(
        self, identifier, pixmap, cell_w, cell_img_h, on_capture, on_open
    ):
        super().__init__()
        self.setObjectName("ljTile")
        self.identifier = identifier
        self._on_open = on_open
        self.setFixedWidth(cell_w)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setToolTip(f"Open '{identifier}'")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        holder = _ClickableLabel()
        holder.setFixedSize(cell_w, cell_img_h)
        holder.setAlignment(QtCore.Qt.AlignCenter)
        holder.setStyleSheet("background-color: #1e1e1e;")
        holder.setCursor(QtCore.Qt.PointingHandCursor)
        scaled = pixmap.scaled(
            cell_w,
            cell_img_h,
            QtCore.Qt.KeepAspectRatio,
            QtCore.Qt.SmoothTransformation,
        )
        holder.setPixmap(scaled)
        holder.clicked.connect(lambda i=identifier: on_open(i))
        layout.addWidget(holder)

        btn = QtWidgets.QToolButton(holder)
        btn.setText("↻")
        btn.setToolTip(f"Re-capture '{identifier}'")
        btn.setFixedSize(22, 22)
        btn.setCursor(QtCore.Qt.PointingHandCursor)
        btn.setStyleSheet(
            "QToolButton { background: rgba(30,30,30,200); color: #ddd;"
            " border: 1px solid #555; border-radius: 3px; }"
            "QToolButton:disabled { color: #555; border-color: #333;"
            " background: rgba(30,30,30,120); }"
            "QToolButton:hover:enabled { background: rgba(70,70,70,220); }"
        )
        btn.move(cell_w - 22 - 4, cell_img_h - 22 - 4)
        btn.setEnabled(False)
        btn.clicked.connect(lambda _=False, i=identifier: on_capture(i))
        self.capture_btn = btn

        name = _ClickableLabel(identifier)
        name.setAlignment(QtCore.Qt.AlignCenter)
        name.setStyleSheet("color: #ddd;")
        name.setCursor(QtCore.Qt.PointingHandCursor)
        name.clicked.connect(lambda i=identifier: on_open(i))
        layout.addWidget(name)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self._on_open(self.identifier)
            return
        super().mousePressEvent(event)

    def highlight(self, duration_ms=1200):
        self.setStyleSheet(
            "#ljTile { border: 2px solid #ffaa33; border-radius: 3px; }"
        )
        QtCore.QTimer.singleShot(duration_ms, self._clear_highlight)

    def _clear_highlight(self):
        try:
            self.setStyleSheet("")
        except RuntimeError:
            pass


def _clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()


def _add_grid_message(grid, text, tiles_per_row):
    label = QtWidgets.QLabel(text)
    label.setAlignment(QtCore.Qt.AlignCenter)
    label.setStyleSheet("color: #888; padding: 20px;")
    grid.addWidget(label, 0, 0, 1, max(1, tiles_per_row))


def _rebuild_tile_grid():
    container = _widgets.get("preview_container")
    grid = _widgets.get("preview_grid")
    spin = _widgets.get("tiles_spin")
    scroll = _widgets.get("preview_scroll")
    if container is None or grid is None or spin is None or scroll is None:
        return

    saved_y = scroll.verticalScrollBar().value()

    _clear_layout(grid)
    _widgets["tiles"] = {}

    tiles_per_row = spin.value()
    graph = _current_comp_graph()

    if graph is None:
        _add_grid_message(grid, "(no compositing graph active)", tiles_per_row)
        return

    images = tile_view.collect_iteration_images(graph)
    if not images:
        _add_grid_message(
            grid, "(no iterations yet — click Iterate)", tiles_per_row
        )
        return

    viewport_w = scroll.viewport().width()
    margins = grid.contentsMargins()
    spacing = grid.spacing()
    available = viewport_w - margins.left() - margins.right() - max(
        0, (tiles_per_row - 1) * spacing
    )
    cell_w = max(80, available // tiles_per_row)
    first = images[0][1]
    aspect = first.height() / max(1, first.width())
    cell_img_h = max(60, int(cell_w * aspect))

    tiles = {}
    for i, (name, pix) in enumerate(images):
        row = i // tiles_per_row
        col = i % tiles_per_row
        tile = _IterationTile(
            name, pix, cell_w, cell_img_h, _on_tile_capture, _on_tile_open
        )
        grid.addWidget(tile, row, col)
        tiles[name] = tile
    _widgets["tiles"] = tiles

    _update_tile_button_states()
    QtCore.QTimer.singleShot(
        0, lambda: scroll.verticalScrollBar().setValue(saved_y)
    )


def _update_tile_button_states():
    main_window = _main_window()
    current = _current_comp_graph()
    current_id = current.getIdentifier() if current is not None else None
    view_visible = tile_view.is_3d_view_visible(main_window)

    for ident, tile in list(_widgets.get("tiles", {}).items()):
        try:
            tile.capture_btn.setEnabled(view_visible and ident == current_id)
        except RuntimeError:
            pass


def _graph_signature():
    graph = _current_comp_graph()
    if graph is None:
        return (None, frozenset())
    try:
        pkg = graph.getPackage()
        ids = frozenset(
            r.getIdentifier() for r in pkg.getChildrenResources(True)
        )
    except Exception:
        ids = frozenset()
    return (graph.getIdentifier(), ids)


def _maybe_refresh_on_change():
    sig = _graph_signature()
    if sig != _widgets.get("last_signature"):
        _widgets["last_signature"] = sig
        _rebuild_tile_grid()


def _on_timer_tick():
    _update_tile_button_states()
    _maybe_refresh_on_change()


def _require_package_saved(graph, title):
    if not graph.getPackage().getFilePath():
        QtWidgets.QMessageBox.critical(
            None,
            title,
            "Save the package to disk first so snapshots have a folder to live in.",
        )
        return False
    return True


def _show_status(text, timeout_ms=3000):
    try:
        main_window = _main_window()
        if main_window is not None:
            main_window.statusBar().showMessage(text, timeout_ms)
    except Exception:
        pass


def _show_toast(text, duration_ms=2200):
    try:
        main_window = _main_window()
    except Exception:
        main_window = None
    toast = QtWidgets.QLabel(text, main_window)
    toast.setWindowFlags(
        QtCore.Qt.Tool
        | QtCore.Qt.FramelessWindowHint
        | QtCore.Qt.WindowStaysOnTopHint
    )
    toast.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)
    toast.setAttribute(QtCore.Qt.WA_DeleteOnClose)
    toast.setStyleSheet(
        "background-color: rgba(40, 40, 40, 230); color: #f0f0f0;"
        " padding: 10px 14px; border: 1px solid #555; border-radius: 4px;"
    )
    toast.adjustSize()
    if main_window is not None:
        geo = main_window.frameGeometry()
        x = geo.right() - toast.width() - 24
        y = geo.bottom() - toast.height() - 32
        toast.move(x, y)
    toast.show()
    QtCore.QTimer.singleShot(duration_ms, toast.close)


def _highlight_tile(identifier):
    tile = _widgets.get("tiles", {}).get(identifier)
    if tile is not None:
        tile.highlight()


def _on_tile_open(identifier):
    ui_mgr = _ui_mgr()
    current = _current_comp_graph()
    if current is None:
        QtWidgets.QMessageBox.warning(
            None, "Open", "No package context available."
        )
        return

    if current.getIdentifier() == identifier:
        return

    target = None
    try:
        for resource in current.getPackage().getChildrenResources(True):
            if resource.getIdentifier() == identifier:
                target = resource
                break
    except Exception:
        target = None

    if target is None:
        QtWidgets.QMessageBox.warning(
            None, "Open", f"Graph '{identifier}' not found in this package."
        )
        return

    _open_graph_view(ui_mgr, target)


def _on_tile_capture(identifier):
    main_window = _main_window()
    graph = _current_comp_graph()

    if graph is None or graph.getIdentifier() != identifier:
        QtWidgets.QMessageBox.warning(
            None, "Capture", f"'{identifier}' is not the active graph."
        )
        return

    if not tile_view.is_3d_view_visible(main_window):
        QtWidgets.QMessageBox.critical(
            None,
            "Capture",
            "The 3D View is closed. Open it to capture a snapshot.",
        )
        return

    if not _require_package_saved(graph, "Capture"):
        return

    pixmap = tile_view.capture_3d_view(main_window)
    if pixmap is None or pixmap.isNull():
        QtWidgets.QMessageBox.critical(
            None, "Capture", "Failed to capture the 3D view."
        )
        return

    if not tile_view.save_iteration_snapshot(graph, pixmap):
        QtWidgets.QMessageBox.critical(
            None, "Capture", "Failed to save the snapshot to disk."
        )
        return

    _rebuild_tile_grid()


def _on_tiles_per_row_changed(value):
    _save_tiles_per_row(value)
    _rebuild_tile_grid()


def _on_export_name_changed(text):
    _save_export_name(text)


def _on_fill_name_from_graph():
    field = _widgets.get("export_name_field")
    if field is None:
        return
    graph = _current_comp_graph()
    if graph is None:
        QtWidgets.QMessageBox.warning(
            None, "Name", "No compositing graph is active."
        )
        return
    field.setText(graph.getIdentifier())


def _collect_output_identifiers(graph):
    ids = []
    for output_node in graph.getOutputNodes():
        try:
            ident = output_node.getIdentifier()
        except Exception:
            ident = None
        if ident:
            ids.append(ident)
    return ids


def _is_exported_filename(stem, graph_id, output_ids):
    if graph_id not in stem:
        return False
    return any(oid in stem for oid in output_ids)


def _rename_exported_files(folder, graph_id, new_name, output_ids):
    renamed = 0
    skipped = 0
    for entry in os.listdir(folder):
        path = os.path.join(folder, entry)
        if not os.path.isfile(path):
            continue
        stem, _ = os.path.splitext(entry)
        if not _is_exported_filename(stem, graph_id, output_ids):
            continue
        new_basename = entry.replace(graph_id, new_name)
        if new_basename == entry:
            continue
        new_path = os.path.join(folder, new_basename)
        try:
            if os.path.exists(new_path):
                os.remove(new_path)
            os.rename(path, new_path)
            renamed += 1
        except Exception as exc:
            skipped += 1
            print(f"[LJ Rename] failed for '{entry}': {exc}")
    return renamed, skipped


def _on_rename():
    graph = _current_comp_graph()
    if graph is None:
        QtWidgets.QMessageBox.warning(
            None, "Rename", "No compositing graph is active."
        )
        return

    name_field = _widgets.get("export_name_field")
    if name_field is None:
        return

    start_dir = _load_export_folder()
    folder = QtWidgets.QFileDialog.getExistingDirectory(
        None, "Choose exported-textures folder", start_dir
    )
    if not folder:
        return
    _save_export_folder(folder)

    name = name_field.text().strip()
    if not name:
        QtWidgets.QMessageBox.warning(
            None, "Rename", "Enter a Name to replace the graph name with."
        )
        return

    graph_id = graph.getIdentifier()
    if name == graph_id:
        _show_status("Name matches the graph name — nothing to rename.", 4000)
        return

    output_ids = _collect_output_identifiers(graph)
    if not output_ids:
        QtWidgets.QMessageBox.warning(
            None, "Rename", "Current graph has no output nodes."
        )
        return

    renamed, skipped = _rename_exported_files(folder, graph_id, name, output_ids)
    if renamed == 0 and skipped == 0:
        _show_status(
            f"No exported files for '{graph_id}' found in {folder}", 4000
        )
    else:
        _show_status(
            f"Renamed {renamed} file(s); {skipped} skipped", 4000
        )


def _on_assets_folder_changed(text):
    _save_assets_folder(text)


def _on_browse_assets_folder():
    field = _widgets.get("assets_folder_field")
    if field is None:
        return
    start_dir = _load_assets_folder() or os.path.expanduser("~")
    folder = QtWidgets.QFileDialog.getExistingDirectory(
        None, "Choose Substance Painter assets folder", start_dir
    )
    if not folder:
        return
    field.setText(folder)


def _resolve_assets_folder(dialog_title):
    field = _widgets.get("assets_folder_field")
    assets_folder = (field.text().strip() if field is not None else "") or _load_assets_folder()
    if not assets_folder:
        QtWidgets.QMessageBox.warning(
            None,
            dialog_title,
            "Set the Substance Painter assets folder first.",
        )
        return None
    if not os.path.isdir(assets_folder):
        QtWidgets.QMessageBox.critical(
            None,
            dialog_title,
            f"Assets folder does not exist:\n{assets_folder}",
        )
        return None
    return assets_folder


def _ensure_subfolder(parent, name, dialog_title):
    sub = os.path.join(parent, name)
    try:
        os.makedirs(sub, exist_ok=True)
    except OSError as exc:
        QtWidgets.QMessageBox.critical(
            None, dialog_title, f"Failed to create {name} folder:\n{exc}"
        )
        return None
    return sub


def _on_send_to_painter():
    graph = _current_comp_graph()
    if graph is None:
        QtWidgets.QMessageBox.warning(
            None, "Send To Substance Painter", "No compositing graph is active."
        )
        return

    package = graph.getPackage()
    sbs_path = package.getFilePath() if package is not None else None
    if not sbs_path or not os.path.isfile(sbs_path):
        QtWidgets.QMessageBox.critical(
            None,
            "Send To Substance Painter",
            "Save the package to disk before exporting.",
        )
        return

    assets_folder = _resolve_assets_folder("Send To Substance Painter")
    if assets_folder is None:
        return
    materials_folder = _ensure_subfolder(assets_folder, _MATERIALS_SUBDIR, "Send To Substance Painter")
    if materials_folder is None:
        return

    if not os.path.isfile(_SBSCOOKER_EXE):
        QtWidgets.QMessageBox.critical(
            None,
            "Send To Substance Painter",
            f"sbscooker.exe not found at:\n{_SBSCOOKER_EXE}",
        )
        return

    try:
        pkg_mgr = sd.getContext().getSDApplication().getPackageMgr()
        pkg_mgr.savePackage(package)
    except Exception as exc:
        QtWidgets.QMessageBox.critical(
            None,
            "Send To Substance Painter",
            f"Failed to save package before cooking:\n{exc}",
        )
        return

    output_name = os.path.splitext(os.path.basename(sbs_path))[0]
    output_path = os.path.join(materials_folder, output_name + ".sbsar")
    if os.path.isfile(output_path):
        try:
            os.remove(output_path)
        except OSError as exc:
            QtWidgets.QMessageBox.critical(
                None,
                "Send To Substance Painter",
                f"Failed to overwrite existing .sbsar:\n{exc}",
            )
            return

    cmd = [
        _SBSCOOKER_EXE,
        sbs_path,
        "--output-path", materials_folder,
        "--output-name", output_name,
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as exc:
        QtWidgets.QMessageBox.critical(
            None, "Send To Substance Painter", f"Failed to run sbscooker:\n{exc}"
        )
        return

    if result.returncode != 0 or not os.path.isfile(output_path):
        details = (result.stdout or "") + "\n" + (result.stderr or "")
        dlg = QtWidgets.QMessageBox(None)
        dlg.setIcon(QtWidgets.QMessageBox.Critical)
        dlg.setWindowTitle("Send To Substance Painter")
        dlg.setText(f"sbscooker exited with code {result.returncode}.")
        dlg.setDetailedText(details.strip())
        dlg.exec()
        return

    _show_status(f"Sent → {output_path}", 4000)
    _show_toast(f"Sent to Substance Painter\n{output_name}.sbsar")


def _selected_nodes_in_current_graph():
    ui_mgr = _ui_mgr()
    for attr in ("getMainGraphSelectedNodes", "getCurrentGraphSelection", "getMainGraphSelectionAsArray"):
        fn = getattr(ui_mgr, attr, None)
        if fn is None:
            continue
        try:
            arr = fn()
        except Exception:
            continue
        if arr is None:
            continue
        try:
            size = arr.getSize()
            return [arr.getItem(i) for i in range(size)]
        except Exception:
            try:
                return list(arr)
            except Exception:
                continue
    return []


def _sanitize_filename_part(text):
    keep = []
    for ch in text:
        if ch.isalnum() or ch in ("_", "-"):
            keep.append(ch)
        else:
            keep.append("_")
    return "".join(keep) or "node"


def _node_display_name(node):
    try:
        prop = node.getPropertyFromId("label", SDPropertyCategory.Annotation)
        if prop is not None:
            value = node.getPropertyValue(prop)
            if value is not None:
                text = value.get()
                if text:
                    return str(text)
    except Exception:
        pass
    try:
        definition = node.getDefinition()
        if definition is not None:
            label = definition.getLabel()
            if label:
                return str(label)
    except Exception:
        pass
    try:
        return node.getIdentifier()
    except Exception:
        return "node"


def _on_export_selected_textures():
    dialog_title = "Export Selected Textures"

    graph = _current_comp_graph()
    if graph is None:
        QtWidgets.QMessageBox.warning(
            None, dialog_title, "No compositing graph is active."
        )
        return

    selected = _selected_nodes_in_current_graph()
    if not selected:
        QtWidgets.QMessageBox.warning(
            None, dialog_title, "Select a node in the current graph first."
        )
        return

    assets_folder = _resolve_assets_folder(dialog_title)
    if assets_folder is None:
        return
    textures_folder = _ensure_subfolder(assets_folder, _TEXTURES_SUBDIR, dialog_title)
    if textures_folder is None:
        return

    try:
        graph.compute()
    except Exception as exc:
        QtWidgets.QMessageBox.critical(
            None, dialog_title, f"Failed to compute graph:\n{exc}"
        )
        return

    graph_id = graph.getIdentifier()
    saved_paths = []
    failures = []

    for node in selected:
        try:
            node_id = node.getIdentifier()
        except Exception:
            node_id = "node"
        node_key = _sanitize_filename_part(_node_display_name(node))

        try:
            outputs = node.getProperties(SDPropertyCategory.Output)
        except Exception as exc:
            failures.append(f"{node_id}: {exc}")
            continue

        try:
            out_count = outputs.getSize()
        except Exception:
            out_count = 0
        if out_count == 0:
            failures.append(f"{node_id}: no outputs")
            continue

        for idx in range(out_count):
            try:
                prop = outputs.getItem(idx)
                value = node.getPropertyValue(prop)
                if value is None:
                    failures.append(f"{node_id}[{idx}]: no value")
                    continue
                texture = value.get()
                if texture is None:
                    failures.append(f"{node_id}[{idx}]: no texture")
                    continue
                filename = f"{graph_id}_{node_key}_{idx}.png"
                path = os.path.join(textures_folder, filename)
                texture.save(path)
                if not os.path.isfile(path):
                    failures.append(f"{node_id}[{idx}]: save returned no file")
                    continue
                saved_paths.append(path)
            except Exception as exc:
                failures.append(f"{node_id}[{idx}]: {exc}")

    if not saved_paths:
        details = "\n".join(failures) if failures else "Selected nodes had no exportable outputs."
        dlg = QtWidgets.QMessageBox(None)
        dlg.setIcon(QtWidgets.QMessageBox.Critical)
        dlg.setWindowTitle(dialog_title)
        dlg.setText("No textures were exported.")
        dlg.setDetailedText(details)
        dlg.exec()
        return

    summary = f"{len(saved_paths)} texture(s) → {textures_folder}"
    if failures:
        summary += f"  ({len(failures)} skipped)"
    _show_status(summary, 4000)
    _show_toast(f"Exported {len(saved_paths)} texture(s)\nto {_TEXTURES_SUBDIR}/")


def _on_iterate():
    ui_mgr = _ui_mgr()
    main_window = _main_window()

    current_graph = ui_mgr.getCurrentGraph()
    if current_graph is None:
        QtWidgets.QMessageBox.warning(
            None, "Iterate", "No graph is currently open."
        )
        return

    if not isinstance(current_graph, SDSBSCompGraph):
        QtWidgets.QMessageBox.warning(
            None,
            "Iterate",
            "Iterate currently only supports Substance compositing graphs.",
        )
        return

    if not tile_view.is_3d_view_visible(main_window):
        QtWidgets.QMessageBox.critical(
            None,
            "Iterate",
            "The 3D View dock is closed. Open it so the source graph snapshot can be captured.",
        )
        return

    if not _require_package_saved(current_graph, "Iterate"):
        return

    source_pixmap = tile_view.capture_3d_view(main_window)

    with SDHistoryUtils.UndoGroup("LJ Iterate Graph"):
        try:
            new_graph, new_name = duplicate_graph(current_graph)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(
                None, "Iterate", f"Failed to duplicate graph:\n{exc}"
            )
            return

    if source_pixmap is not None and not source_pixmap.isNull():
        tile_view.save_iteration_snapshot(current_graph, source_pixmap)
        tile_view.save_iteration_snapshot(new_graph, source_pixmap)

    _rebuild_tile_grid()
    _highlight_tile(new_name)
    _show_status(f"Created '{new_name}'", 3000)


def build_panel(parent):
    panel = QtWidgets.QWidget(parent)
    layout = QtWidgets.QVBoxLayout(panel)
    layout.setContentsMargins(8, 8, 8, 8)
    layout.setSpacing(6)

    title = QtWidgets.QLabel("LJ Sub Designer Tools")
    title_font = title.font()
    title_font.setBold(True)
    title.setFont(title_font)
    layout.addWidget(title)

    iterate_btn = QtWidgets.QPushButton("Iterate")
    iterate_btn.setToolTip(
        "Duplicate the current graph (append _ver_N) and snapshot the 3D view."
    )
    iterate_btn.clicked.connect(_on_iterate)
    layout.addWidget(iterate_btn)

    controls = QtWidgets.QHBoxLayout()
    controls.setSpacing(6)
    controls.addWidget(QtWidgets.QLabel("Tiles/row:"))
    tiles_spin = QtWidgets.QSpinBox()
    tiles_spin.setRange(1, 12)
    tiles_spin.setValue(_load_tiles_per_row())
    tiles_spin.valueChanged.connect(_on_tiles_per_row_changed)
    controls.addWidget(tiles_spin)
    controls.addStretch(1)
    layout.addLayout(controls)

    preview_container = QtWidgets.QWidget()
    preview_container.setStyleSheet("background-color: #282828;")
    preview_grid = QtWidgets.QGridLayout(preview_container)
    preview_grid.setContentsMargins(6, 6, 6, 6)
    preview_grid.setSpacing(6)
    preview_grid.setAlignment(QtCore.Qt.AlignTop)

    preview_scroll = _PreviewScrollArea()
    preview_scroll.setWidget(preview_container)
    preview_scroll.setWidgetResizable(True)
    preview_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
    preview_scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
    preview_scroll.setMinimumHeight(140)
    preview_scroll.setStyleSheet(
        "QScrollArea { background-color: #282828; border: none; }"
    )
    layout.addWidget(preview_scroll, 1)

    export_separator = QtWidgets.QFrame()
    export_separator.setFrameShape(QtWidgets.QFrame.HLine)
    export_separator.setFrameShadow(QtWidgets.QFrame.Sunken)
    layout.addWidget(export_separator)

    export_title = QtWidgets.QLabel("Rename Exported Textures")
    et_font = export_title.font()
    et_font.setBold(True)
    export_title.setFont(et_font)
    layout.addWidget(export_title)

    layout.addWidget(QtWidgets.QLabel("Name"))
    name_row = QtWidgets.QHBoxLayout()
    name_row.setSpacing(4)
    export_name_field = QtWidgets.QLineEdit(_load_export_name())
    export_name_field.textChanged.connect(_on_export_name_changed)
    name_row.addWidget(export_name_field, 1)
    fill_name_btn = QtWidgets.QToolButton()
    fill_name_btn.setText("G")
    fill_name_btn.setToolTip("Fill Name with the current graph name")
    fill_name_btn.clicked.connect(_on_fill_name_from_graph)
    name_row.addWidget(fill_name_btn)
    layout.addLayout(name_row)

    rename_btn = QtWidgets.QPushButton("Rename")
    rename_btn.setToolTip(
        "Replace the current graph name with Name in every exported texture\n"
        "in the folder above. Only files matching this graph's output nodes are touched."
    )
    rename_btn.clicked.connect(_on_rename)
    layout.addWidget(rename_btn)

    sbsar_separator = QtWidgets.QFrame()
    sbsar_separator.setFrameShape(QtWidgets.QFrame.HLine)
    sbsar_separator.setFrameShadow(QtWidgets.QFrame.Sunken)
    layout.addWidget(sbsar_separator)

    sbsar_title = QtWidgets.QLabel("Send To Substance Painter")
    st_font = sbsar_title.font()
    st_font.setBold(True)
    sbsar_title.setFont(st_font)
    layout.addWidget(sbsar_title)

    layout.addWidget(QtWidgets.QLabel(
        "Assets folder  (materials → ./materials, textures → ./textures)"
    ))
    assets_row = QtWidgets.QHBoxLayout()
    assets_row.setSpacing(4)
    assets_folder_field = QtWidgets.QLineEdit(_load_assets_folder())
    assets_folder_field.setPlaceholderText(
        r"C:\Users\<you>\Documents\Adobe\Adobe Substance 3D Painter\assets"
    )
    assets_folder_field.textChanged.connect(_on_assets_folder_changed)
    assets_row.addWidget(assets_folder_field, 1)
    browse_assets_btn = QtWidgets.QToolButton()
    browse_assets_btn.setText("…")
    browse_assets_btn.setToolTip("Browse for Substance Painter assets folder")
    browse_assets_btn.clicked.connect(_on_browse_assets_folder)
    assets_row.addWidget(browse_assets_btn)
    layout.addLayout(assets_row)

    send_to_painter_btn = QtWidgets.QPushButton("Send Material")
    send_to_painter_btn.setToolTip(
        "Save + cook the active graph's package to <assets>/materials/<package>.sbsar.\n"
        "Overwrites if a file with that name already exists."
    )
    send_to_painter_btn.clicked.connect(_on_send_to_painter)
    layout.addWidget(send_to_painter_btn)

    export_textures_btn = QtWidgets.QPushButton("Send Node Texture")
    export_textures_btn.setToolTip(
        "Save each output of the currently selected node(s) to\n"
        "<assets>/textures/<graph>_<node>_<idx>.png.\n"
        "Re-exporting from the same node overwrites."
    )
    export_textures_btn.clicked.connect(_on_export_selected_textures)
    layout.addWidget(export_textures_btn)

    _widgets["assets_folder_field"] = assets_folder_field
    _widgets["send_to_painter_btn"] = send_to_painter_btn
    _widgets["export_textures_btn"] = export_textures_btn

    _widgets["iterate_btn"] = iterate_btn
    _widgets["tiles_spin"] = tiles_spin
    _widgets["preview_container"] = preview_container
    _widgets["preview_grid"] = preview_grid
    _widgets["preview_scroll"] = preview_scroll
    _widgets["export_name_field"] = export_name_field
    _widgets["rename_btn"] = rename_btn
    _widgets["last_signature"] = None
    _widgets["tiles"] = {}

    timer = QtCore.QTimer(panel)
    timer.setInterval(_REFRESH_INTERVAL_MS)
    timer.timeout.connect(_on_timer_tick)
    timer.start()
    _widgets["timer"] = timer

    QtCore.QTimer.singleShot(0, _rebuild_tile_grid)

    return panel
