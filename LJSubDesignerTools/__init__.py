import importlib

import sd

try:
    from PySide6 import QtWidgets
except ImportError:
    from PySide2 import QtWidgets

from . import graph_iterate, tile_view, panel

_PANEL_ID = "lj_sub_designer_tools_panel"

_menu = None
_actions = []
_panel = None


def _show_panel():
    if _panel is not None:
        _panel.show()
        _panel.raise_()


def _reload_submodules():
    importlib.reload(graph_iterate)
    importlib.reload(tile_view)
    importlib.reload(panel)


def initializeSDPlugin():
    global _menu, _actions, _panel

    _reload_submodules()

    app = sd.getContext().getSDApplication()
    ui_mgr = app.getUIMgr()
    main_window = panel.get_main_window(ui_mgr)

    panel_ptr = ui_mgr.newDockWidget(_PANEL_ID, "LJ Tools")
    _panel = panel.wrap_widget(panel_ptr)

    content = panel.build_panel(_panel)
    panel_layout = QtWidgets.QVBoxLayout(_panel)
    panel_layout.setContentsMargins(0, 0, 0, 0)
    panel_layout.addWidget(content)

    menu_bar = main_window.menuBar()
    _menu = menu_bar.addMenu("LJ Tools")

    hello_action = _menu.addAction("Hello World")
    hello_action.triggered.connect(panel.on_hello_world)
    _actions.append(hello_action)

    show_panel_action = _menu.addAction("Show Panel")
    show_panel_action.triggered.connect(_show_panel)
    _actions.append(show_panel_action)

    diagnose_action = _menu.addAction("Diagnose 3D View")
    diagnose_action.triggered.connect(panel.on_diagnose_3d_view)
    _actions.append(diagnose_action)


def uninitializeSDPlugin():
    global _menu, _actions, _panel

    for action in _actions:
        if action is not None and _menu is not None:
            _menu.removeAction(action)
    _actions = []

    if _menu is not None:
        menu_bar = _menu.parent()
        if isinstance(menu_bar, QtWidgets.QMenuBar):
            menu_bar.removeAction(_menu.menuAction())
        _menu = None

    if _panel is not None:
        try:
            app = sd.getContext().getSDApplication()
            ui_mgr = app.getUIMgr()
            ui_mgr.deleteDockWidget(_PANEL_ID)
        except Exception:
            pass
        _panel = None
