import os

import substance_painter.logging
import substance_painter.project
import substance_painter.ui

from PySide6 import QtCore, QtWidgets

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

    try:
        if substance_painter.project.is_open():
            if substance_painter.project.needs_saving():
                substance_painter.project.save()
            substance_painter.project.close()
        substance_painter.project.open(target_path)
    except Exception as exc:
        substance_painter.logging.error(
            f"LJ Iterate: failed to open '{identifier}': {exc}"
        )


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
            tile.capture_btn.setEnabled(view_visible and ident == cur_stem)
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
    _widgets["last_signature"] = None
    _widgets["tiles"] = {}

    timer = QtCore.QTimer(panel)
    timer.setInterval(_REFRESH_INTERVAL_MS)
    timer.timeout.connect(_on_timer_tick)
    timer.start()
    _widgets["timer"] = timer

    QtCore.QTimer.singleShot(0, _rebuild_tile_grid)

    return panel
