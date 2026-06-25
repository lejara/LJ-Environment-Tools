import sd
from sd.api.sbs.sdsbscompgraph import SDSBSCompGraph
from sd.api.sdhistoryutils import SDHistoryUtils

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
