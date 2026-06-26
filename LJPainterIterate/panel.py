import os
import subprocess

import substance_painter.logging
import substance_painter.project
import substance_painter.ui

from PySide6 import QtCore, QtGui, QtWidgets

try:
    import shiboken6
    def _widget_valid(w):
        return w is not None and shiboken6.isValid(w)
except ImportError:
    def _widget_valid(w):
        return w is not None

from . import project_iterate, tile_view

_DEFAULT_TILES_PER_ROW = 4
_REFRESH_INTERVAL_MS = 500
_HANDOFF_CLOSE_DELAY_MS = 1500

_SETTINGS_ORG = "LJ"
_SETTINGS_APP = "PainterIterate"
_TILES_PER_ROW_KEY = "tilesPerRow"

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


def _main_window():
    try:
        return substance_painter.ui.get_main_window()
    except Exception:
        return None


def _current_project_path():
    try:
        if not substance_painter.project.is_open():
            return None
        return substance_painter.project.file_path()
    except Exception:
        return None


def _show_status(text, timeout_ms=3000):
    try:
        main_window = _main_window()
        if main_window is not None:
            main_window.statusBar().showMessage(text, timeout_ms)
    except Exception:
        pass


class _ClickableLabel(QtWidgets.QLabel):
    clicked = QtCore.Signal()

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


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


class _IterationTile(QtWidgets.QFrame):
    def __init__(
        self, identifier, pixmap, cell_w, cell_img_h, on_capture, on_open,
        on_delete
    ):
        super().__init__()
        self.setObjectName("ljTile")
        self.identifier = identifier
        self._on_open = on_open
        self._on_delete = on_delete
        self._is_active = False
        self.setFixedWidth(cell_w)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setToolTip(f"Open '{identifier}'")
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

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
        self._bright_pixmap = scaled
        self._dim_pixmap = self._make_dim_pixmap(scaled)
        holder.setPixmap(scaled)
        holder.clicked.connect(self._handle_click)
        layout.addWidget(holder)
        self._holder = holder

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
        name.clicked.connect(self._handle_click)
        layout.addWidget(name)
        self._name_label = name

    @staticmethod
    def _make_dim_pixmap(pixmap):
        out = QtGui.QPixmap(pixmap)
        painter = QtGui.QPainter(out)
        painter.fillRect(out.rect(), QtGui.QColor(0, 0, 0, 160))
        painter.end()
        return out

    def set_active(self, active):
        active = bool(active)
        if active == self._is_active:
            return
        self._is_active = active
        cursor = (
            QtCore.Qt.ArrowCursor if active else QtCore.Qt.PointingHandCursor
        )
        self.setCursor(cursor)
        self._holder.setCursor(cursor)
        self._name_label.setCursor(cursor)
        if active:
            self.setToolTip(f"'{self.identifier}' is currently open")
            self._holder.setPixmap(self._dim_pixmap)
            self._name_label.setStyleSheet("color: #888;")
        else:
            self.setToolTip(f"Open '{self.identifier}'")
            self._holder.setPixmap(self._bright_pixmap)
            self._name_label.setStyleSheet("color: #ddd;")

    def _handle_click(self):
        if self._is_active:
            return
        self._on_open(self.identifier)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            if self._is_active:
                event.accept()
                return
            self._on_open(self.identifier)
            return
        super().mousePressEvent(event)

    def _show_context_menu(self, pos):
        menu = QtWidgets.QMenu(self)
        delete_action = menu.addAction("Delete from disk")
        chosen = menu.exec(self.mapToGlobal(pos))
        if chosen is delete_action:
            self._on_delete(self.identifier)

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


def _highlight_tile(identifier):
    tile = _widgets.get("tiles", {}).get(identifier)
    if tile is not None:
        tile.highlight()


def _on_tile_open(identifier):
    project_path = _current_project_path()
    if project_path is None:
        substance_painter.logging.warning(
            "LJ Iterate: no project context to find sibling iterations"
        )
        return

    source_dir = os.path.dirname(project_path)
    target_path = os.path.join(source_dir, f"{identifier}.spp")
    if not os.path.isfile(target_path):
        substance_painter.logging.warning(
            f"LJ Iterate: '{identifier}' not found at {target_path}"
        )
        return

    if os.path.normcase(os.path.normpath(target_path)) == os.path.normcase(
        os.path.normpath(project_path)
    ):
        return

    app_path = QtWidgets.QApplication.applicationFilePath()
    if not app_path or not os.path.isfile(app_path):
        substance_painter.logging.error(
            "LJ Iterate: could not resolve Painter executable path"
        )
        _show_status("Could not launch a new Painter instance.", 4000)
        return

    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )

    try:
        subprocess.Popen(
            [app_path, target_path],
            cwd=os.path.dirname(app_path) or None,
            close_fds=True,
            creationflags=creationflags,
        )
    except Exception as exc:
        substance_painter.logging.error(
            f"LJ Iterate: failed to launch '{identifier}': {exc}"
        )
        _show_status(f"Launch failed: {exc}", 5000)
        return

    _show_status(f"Launching '{identifier}' — closing this Painter…", 3000)
    QtCore.QTimer.singleShot(_HANDOFF_CLOSE_DELAY_MS, _close_current_project)


def _close_current_project():
    try:
        if (
            substance_painter.project.is_open()
            and substance_painter.project.needs_saving()
        ):
            substance_painter.project.save()
    except Exception as exc:
        substance_painter.logging.warning(
            f"LJ Iterate: save before handoff quit failed: {exc}"
        )

    main_window = _main_window()
    if main_window is not None:
        try:
            main_window.close()
        except Exception:
            pass

    app = QtWidgets.QApplication.instance()
    if app is not None:
        QtCore.QTimer.singleShot(0, app.quit)


def _on_tile_delete(identifier):
    project_path = _current_project_path()
    if project_path is None:
        substance_painter.logging.warning(
            "LJ Iterate: no project context to delete from"
        )
        return

    source_dir = os.path.dirname(project_path)
    target_spp = os.path.join(source_dir, f"{identifier}.spp")
    if not os.path.isfile(target_spp):
        substance_painter.logging.warning(
            f"LJ Iterate: '{identifier}' not found at {target_spp}"
        )
        _rebuild_tile_grid()
        return

    main_window = _main_window()
    reply = QtWidgets.QMessageBox.question(
        main_window,
        "Delete iteration",
        f"Delete '{identifier}' from disk?\n\nThis removes:\n"
        f"  {target_spp}\nand its iteration snapshot.\n\n"
        "This cannot be undone.",
        QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel,
        QtWidgets.QMessageBox.Cancel,
    )
    if reply != QtWidgets.QMessageBox.Yes:
        return

    is_current = os.path.normcase(os.path.normpath(target_spp)) == os.path.normcase(
        os.path.normpath(project_path)
    )
    if is_current:
        if substance_painter.project.is_busy():
            _show_status("Painter is busy.", 3000)
            return
        try:
            substance_painter.project.close()
        except Exception as exc:
            substance_painter.logging.error(
                f"LJ Iterate: close failed: {exc}"
            )
            _show_status("Close failed; project not deleted.", 4000)
            return

    png_path = tile_view.iteration_png_path(target_spp)

    try:
        os.remove(target_spp)
    except Exception as exc:
        substance_painter.logging.error(
            f"LJ Iterate: failed to delete '{identifier}': {exc}"
        )
        _show_status(f"Delete failed: {exc}", 5000)
        return

    if png_path and os.path.isfile(png_path):
        try:
            os.remove(png_path)
        except Exception as exc:
            substance_painter.logging.warning(
                f"LJ Iterate: failed to delete snapshot for '{identifier}': {exc}"
            )

    _rebuild_tile_grid()
    _show_status(f"Deleted '{identifier}'", 3000)


def _on_tile_capture(identifier):
    project_path = _current_project_path()
    main_window = _main_window()

    if project_path is None:
        substance_painter.logging.warning("LJ Iterate: no project open to capture")
        return

    cur_stem = os.path.splitext(os.path.basename(project_path))[0]
    if cur_stem != identifier:
        substance_painter.logging.warning(
            f"LJ Iterate: '{identifier}' is not the active project"
        )
        return

    if not tile_view.is_viewport_visible(main_window):
        substance_painter.logging.warning("LJ Iterate: 3D viewport not visible")
        return

    pixmap = tile_view.capture_viewport(main_window)
    if pixmap is None or pixmap.isNull():
        substance_painter.logging.error("LJ Iterate: failed to capture viewport")
        return

    if not tile_view.save_iteration_snapshot(project_path, pixmap):
        substance_painter.logging.error("LJ Iterate: failed to save snapshot")
        return

    _rebuild_tile_grid()
    _show_status(f"Re-captured '{identifier}'", 2500)


def _refresh_name_edit():
    edit = _widgets.get("name_edit")
    check = _widgets.get("include_iter_check")
    project_path = _current_project_path()

    if project_path is None:
        if _widget_valid(edit):
            edit.setEnabled(False)
            if not edit.hasFocus():
                edit.setText("")
        if _widget_valid(check):
            check.setChecked(False)
            check.setEnabled(False)
            check.setToolTip("Open a project to enable this option.")
        return

    stem = os.path.splitext(os.path.basename(project_path))[0]
    base = project_iterate.base_name(stem)
    is_base = stem == base

    if _widget_valid(edit):
        edit.setEnabled(True)
        if not edit.hasFocus():
            edit.setText(base)

    if _widget_valid(check):
        if is_base:
            check.setEnabled(True)
            check.setToolTip(
                "When checked, sibling _ver_N .spp files, the _iterations"
                " folder, and its PNG snapshots are renamed too. When"
                " unchecked, only the active project file is renamed."
            )
        else:
            check.setChecked(False)
            check.setEnabled(False)
            check.setToolTip(
                "Only available when the base project (no _ver_N suffix) is"
                " open."
            )


def _on_rename_clicked():
    project_path = _current_project_path()
    edit = _widgets.get("name_edit")
    if project_path is None:
        _show_status("No saved project open to rename.", 3000)
        return
    if not _widget_valid(edit):
        return

    new_base = edit.text().strip()
    if not project_iterate.is_valid_name(new_base):
        _show_status("Invalid project name.", 4000)
        return

    cur_stem = os.path.splitext(os.path.basename(project_path))[0]
    old_base = project_iterate.base_name(cur_stem)
    if new_base == old_base:
        return

    if substance_painter.project.is_busy():
        _show_status("Painter is busy.", 3000)
        return

    edit.clearFocus()

    include_iter_check = _widgets.get("include_iter_check")
    include_iterations = (
        include_iter_check.isChecked()
        if _widget_valid(include_iter_check)
        else False
    )

    try:
        new_current_path, ops = project_iterate.plan_family_rename(
            project_path, new_base, include_iterations=include_iterations
        )
    except Exception as exc:
        substance_painter.logging.error(f"LJ Iterate: rename plan failed: {exc}")
        _show_status(f"Rename failed: {exc}", 5000)
        return

    if new_current_path is None:
        return

    locked = project_iterate.find_locked_paths([old for old, _ in ops])
    if locked:
        main_window = _main_window()
        QtWidgets.QMessageBox.critical(
            main_window,
            "Rename failed — files in use",
            "These files are currently in use by another process and cannot"
            " be renamed:\n\n"
            + "\n".join(f"  {p}" for p in locked)
            + "\n\nClose whatever has them open and try again.",
        )
        _show_status("Rename aborted: files in use.", 4000)
        return

    try:
        substance_painter.project.save_as(new_current_path)
    except Exception as exc:
        substance_painter.logging.error(f"LJ Iterate: save_as failed: {exc}")
        _show_status(f"Save As failed: {exc}", 5000)
        return

    try:
        project_iterate.apply_rename_ops(ops)
    except Exception as exc:
        substance_painter.logging.error(f"LJ Iterate: rename ops failed: {exc}")
        _show_status(f"Rename partially failed: {exc}", 5000)

    try:
        if os.path.isfile(project_path):
            os.remove(project_path)
    except Exception as exc:
        substance_painter.logging.warning(
            f"LJ Iterate: failed to remove old .spp: {exc}"
        )

    if not include_iterations:
        old_png = tile_view.iteration_png_path(project_path)
        if old_png and os.path.isfile(old_png):
            try:
                os.remove(old_png)
            except Exception as exc:
                substance_painter.logging.warning(
                    f"LJ Iterate: failed to remove old PNG: {exc}"
                )

    _show_status(f"Renamed to '{new_base}'", 3000)


def _on_iterate():
    main_window = _main_window()
    project_path = _current_project_path()

    if project_path is None:
        substance_painter.logging.warning(
            "LJ Iterate: no saved project open to iterate"
        )
        _show_status("Save a project first, then iterate.", 4000)
        return

    if substance_painter.project.is_busy():
        substance_painter.logging.warning("LJ Iterate: Painter is busy")
        _show_status("Painter is busy.", 4000)
        return

    if not tile_view.is_viewport_visible(main_window):
        substance_painter.logging.warning("LJ Iterate: 3D viewport not visible")
        _show_status("Open the 3D viewport to iterate.", 4000)
        return

    source_pixmap = tile_view.capture_viewport(main_window)

    try:
        substance_painter.project.save()
    except Exception as exc:
        substance_painter.logging.error(f"LJ Iterate: save failed: {exc}")
        _show_status("Save failed.", 4000)
        return

    try:
        new_path, new_name = project_iterate.duplicate_project(project_path)
    except Exception as exc:
        substance_painter.logging.error(f"LJ Iterate: copy failed: {exc}")
        _show_status("Copy failed.", 4000)
        return

    if source_pixmap is not None and not source_pixmap.isNull():
        tile_view.save_iteration_snapshot(project_path, source_pixmap)
        tile_view.save_iteration_snapshot(new_path, source_pixmap)

    _rebuild_tile_grid()
    _highlight_tile(new_name)
    _show_status(f"Created '{new_name}'", 3000)


def _rebuild_tile_grid():
    container = _widgets.get("preview_container")
    grid = _widgets.get("preview_grid")
    spin = _widgets.get("tiles_spin")
    scroll = _widgets.get("preview_scroll")
    if not all(_widget_valid(w) for w in (container, spin, scroll)):
        _widgets.clear()
        return
    if grid is None:
        return

    saved_y = scroll.verticalScrollBar().value()
    _clear_layout(grid)
    _widgets["tiles"] = {}

    tiles_per_row = spin.value()
    project_path = _current_project_path()

    if project_path is None:
        _add_grid_message(grid, "(no saved project open)", tiles_per_row)
        return

    images = tile_view.collect_iteration_images(project_path)
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
            name, pix, cell_w, cell_img_h, _on_tile_capture, _on_tile_open,
            _on_tile_delete
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
    project_path = _current_project_path()
    cur_stem = (
        os.path.splitext(os.path.basename(project_path))[0]
        if project_path
        else None
    )
    view_visible = tile_view.is_viewport_visible(main_window)

    for ident, tile in list(_widgets.get("tiles", {}).items()):
        if not _widget_valid(tile):
            continue
        try:
            is_active = ident == cur_stem
            tile.set_active(is_active)
            tile.capture_btn.setEnabled(view_visible and is_active)
        except RuntimeError:
            pass


def _signature():
    project_path = _current_project_path()
    if project_path is None:
        return (None, frozenset())
    source_dir = os.path.dirname(project_path)
    source_stem = os.path.splitext(os.path.basename(project_path))[0]
    base = project_iterate.base_name(source_stem)
    if not os.path.isdir(source_dir):
        return (project_path, frozenset())
    siblings = frozenset(
        os.path.splitext(f)[0]
        for f in os.listdir(source_dir)
        if f.lower().endswith(".spp")
        and project_iterate.base_name(os.path.splitext(f)[0]) == base
    )
    return (project_path, siblings)


def _maybe_refresh_on_change():
    sig = _signature()
    if sig != _widgets.get("last_signature"):
        _widgets["last_signature"] = sig
        _refresh_name_edit()
        _rebuild_tile_grid()


def _on_timer_tick():
    if not _widget_valid(_widgets.get("preview_scroll")):
        timer = _widgets.get("timer")
        if _widget_valid(timer):
            try:
                timer.stop()
            except RuntimeError:
                pass
        _widgets.clear()
        return
    _update_tile_button_states()
    _maybe_refresh_on_change()


def _on_tiles_per_row_changed(value):
    _save_tiles_per_row(value)
    _rebuild_tile_grid()


def notify_project_event():
    _widgets["last_signature"] = None
    _refresh_name_edit()
    _rebuild_tile_grid()


def on_diagnose_3d_view():
    main_window = _main_window()
    candidates = tile_view.list_viewport_candidates(main_window)
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
    print("[LJPainterIterate] viewport diagnostic:")
    print(text)
    dlg = QtWidgets.QMessageBox(main_window)
    dlg.setWindowTitle("3D View Diagnostic")
    dlg.setText("3D view detection / capture report:")
    dlg.setDetailedText(text)
    dlg.exec()


def build_panel():
    _widgets.clear()

    panel = QtWidgets.QWidget()
    panel.setObjectName("LJPainterIteratePanel")
    panel.setWindowTitle("LJ Iterate")
    panel.setMinimumSize(280, 320)
    layout = QtWidgets.QVBoxLayout()
    layout.setContentsMargins(8, 8, 8, 8)
    layout.setSpacing(6)
    panel.setLayout(layout)

    title = QtWidgets.QLabel("LJ Painter Iterate")
    title_font = title.font()
    title_font.setBold(True)
    title.setFont(title_font)
    layout.addWidget(title)

    rename_row = QtWidgets.QHBoxLayout()
    rename_row.setSpacing(6)
    rename_row.addWidget(QtWidgets.QLabel("Project name:"))
    name_edit = QtWidgets.QLineEdit()
    name_edit.setPlaceholderText("(no project open)")
    name_edit.setToolTip(
        "Rename this project's base name. All sibling _ver_N .spp files,"
        " the _iterations folder, and its PNGs are renamed together."
    )
    name_edit.returnPressed.connect(_on_rename_clicked)
    rename_row.addWidget(name_edit, 1)
    rename_btn = QtWidgets.QPushButton("Rename")
    rename_btn.clicked.connect(_on_rename_clicked)
    rename_row.addWidget(rename_btn)
    layout.addLayout(rename_row)

    include_iter_check = QtWidgets.QCheckBox("Also rename iterations")
    include_iter_check.setToolTip(
        "When checked, sibling _ver_N .spp files, the _iterations folder,"
        " and its PNG snapshots are renamed too. When unchecked, only the"
        " active project file is renamed."
    )
    include_iter_check.setChecked(False)
    layout.addWidget(include_iter_check)

    iterate_btn = QtWidgets.QPushButton("Iterate")
    iterate_btn.setToolTip(
        "Save the project, copy it to <base>_ver_N.spp, snapshot the 3D viewport."
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

    _widgets["iterate_btn"] = iterate_btn
    _widgets["tiles_spin"] = tiles_spin
    _widgets["preview_container"] = preview_container
    _widgets["preview_grid"] = preview_grid
    _widgets["preview_scroll"] = preview_scroll
    _widgets["name_edit"] = name_edit
    _widgets["rename_btn"] = rename_btn
    _widgets["include_iter_check"] = include_iter_check
    _widgets["last_signature"] = None
    _widgets["tiles"] = {}

    timer = QtCore.QTimer(panel)
    timer.setInterval(_REFRESH_INTERVAL_MS)
    timer.timeout.connect(_on_timer_tick)
    timer.start()
    _widgets["timer"] = timer

    QtCore.QTimer.singleShot(0, _refresh_name_edit)
    QtCore.QTimer.singleShot(0, _rebuild_tile_grid)

    return panel
