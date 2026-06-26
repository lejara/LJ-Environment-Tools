import importlib

import substance_painter.event
import substance_painter.logging
import substance_painter.ui

from PySide6 import QtGui, QtWidgets

from . import project_iterate, tile_view, panel


_WIDGET = None
_MENU = None
_DIAGNOSE_ACTION = None
_CALLBACK = None
_SUBSCRIBED_EVENTS = []


def _reload_submodules():
    importlib.reload(project_iterate)
    importlib.reload(tile_view)
    importlib.reload(panel)


def _on_project_event(_event):
    try:
        panel.notify_project_event()
    except Exception as exc:
        substance_painter.logging.error(
            f"LJ Iterate: refresh on project event failed: {exc}"
        )


def _connect_events():
    global _CALLBACK, _SUBSCRIBED_EVENTS
    _CALLBACK = _on_project_event
    _SUBSCRIBED_EVENTS = [
        substance_painter.event.ProjectOpened,
        substance_painter.event.ProjectCreated,
        substance_painter.event.ProjectAboutToClose,
        substance_painter.event.ProjectClosed,
        substance_painter.event.ProjectSaved,
    ]
    for ev in _SUBSCRIBED_EVENTS:
        substance_painter.event.DISPATCHER.connect(ev, _CALLBACK)


def _disconnect_events():
    global _CALLBACK, _SUBSCRIBED_EVENTS
    if _CALLBACK is None:
        return
    for ev in _SUBSCRIBED_EVENTS:
        try:
            substance_painter.event.DISPATCHER.disconnect(ev, _CALLBACK)
        except Exception:
            pass
    _CALLBACK = None
    _SUBSCRIBED_EVENTS = []


def start_plugin():
    global _WIDGET, _MENU, _DIAGNOSE_ACTION

    _reload_submodules()

    _WIDGET = panel.build_panel()
    _WIDGET.setWindowTitle("LJ Iterate")
    ui_modes = (
        substance_painter.ui.UIMode.Edition.value
        | substance_painter.ui.UIMode.Visualisation.value
        | substance_painter.ui.UIMode.Baking.value
    )
    substance_painter.ui.add_dock_widget(_WIDGET, ui_modes)

    _MENU = QtWidgets.QMenu("LJ Iterate")
    _DIAGNOSE_ACTION = QtGui.QAction("Diagnose 3D View", _MENU)
    _DIAGNOSE_ACTION.triggered.connect(panel.on_diagnose_3d_view)
    _MENU.addAction(_DIAGNOSE_ACTION)
    substance_painter.ui.add_menu(_MENU)

    _connect_events()


def close_plugin():
    global _WIDGET, _MENU, _DIAGNOSE_ACTION

    _disconnect_events()

    if _WIDGET is not None:
        try:
            substance_painter.ui.delete_ui_element(_WIDGET)
        except Exception:
            pass
        _WIDGET = None

    if _MENU is not None:
        try:
            substance_painter.ui.delete_ui_element(_MENU)
        except Exception:
            pass
        _MENU = None

    _DIAGNOSE_ACTION = None
