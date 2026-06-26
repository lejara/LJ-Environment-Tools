import os
import re

from PySide6 import QtCore, QtGui, QtWidgets

_VER_RE = re.compile(r"^(.*)_ver_(\d+)$")
_TILE_SUFFIX = "_tile"

_VIEWPORT_PREFIX = "viewer3d"


def base_name(stem):
    m = _VER_RE.match(stem)
    return m.group(1) if m else stem


def iterations_dir(project_path):
    if not project_path:
        return None
    source_dir = os.path.dirname(project_path)
    source_stem = os.path.splitext(os.path.basename(project_path))[0]
    base = base_name(source_stem)
    return os.path.join(source_dir, f"{base}_iterations")


def iteration_png_path(project_path):
    folder = iterations_dir(project_path)
    if folder is None:
        return None
    stem = os.path.splitext(os.path.basename(project_path))[0]
    return os.path.join(folder, f"{stem}.png")


def _existing_spp_stems(project_path):
    if not project_path:
        return set()
    source_dir = os.path.dirname(project_path)
    if not os.path.isdir(source_dir):
        return set()
    source_stem = os.path.splitext(os.path.basename(project_path))[0]
    base = base_name(source_stem)
    stems = set()
    for fname in os.listdir(source_dir):
        if not fname.lower().endswith(".spp"):
            continue
        stem = os.path.splitext(fname)[0]
        if base_name(stem) == base:
            stems.add(stem)
    return stems


def _iteration_sort_key(stem):
    m = _VER_RE.match(stem)
    if m:
        return (m.group(1), int(m.group(2)))
    return (stem, -1)


def collect_iteration_images(project_path, delete_orphans=True):
    folder = iterations_dir(project_path)
    if folder is None or not os.path.isdir(folder):
        return []

    existing_stems = _existing_spp_stems(project_path)

    results = []
    for fname in os.listdir(folder):
        if not fname.lower().endswith(".png"):
            continue
        stem = os.path.splitext(fname)[0]
        if stem.endswith(_TILE_SUFFIX):
            continue
        if stem not in existing_stems:
            if delete_orphans:
                try:
                    os.remove(os.path.join(folder, fname))
                except Exception:
                    pass
            continue
        pix = QtGui.QPixmap(os.path.join(folder, fname))
        if pix.isNull():
            continue
        results.append((stem, pix))
    results.sort(key=lambda x: _iteration_sort_key(x[0]))
    return results


def save_iteration_snapshot(project_path, pixmap):
    path = iteration_png_path(project_path)
    if path is None or pixmap is None or pixmap.isNull():
        return False
    folder = os.path.dirname(path)
    try:
        os.makedirs(folder, exist_ok=True)
    except Exception:
        return False
    return bool(pixmap.save(path, "PNG"))


def _viewport_widgets(main_window):
    if main_window is None:
        return []
    return [
        w
        for w in main_window.findChildren(QtWidgets.QWidget)
        if w.isVisible()
        and w.objectName().lower().startswith(_VIEWPORT_PREFIX)
    ]


def find_viewport_rect(main_window):
    widgets = _viewport_widgets(main_window)
    if not widgets:
        return None
    rect = None
    for w in widgets:
        gp = w.mapToGlobal(QtCore.QPoint(0, 0))
        r = QtCore.QRect(gp, w.size())
        rect = r if rect is None else rect.united(r)
    if rect is None or rect.width() <= 0 or rect.height() <= 0:
        return None
    return rect


def find_viewport_inner_rect(main_window):
    rects = []
    for w in _viewport_widgets(main_window):
        gp = w.mapToGlobal(QtCore.QPoint(0, 0))
        rects.append(QtCore.QRect(gp, w.size()))
    if not rects:
        return None
    outer = rects[0]
    for r in rects[1:]:
        outer = outer.united(r)
    if outer.width() <= 0 or outer.height() <= 0:
        return None

    # Painter exposes a single Viewer3D widget with overlay children inside it.
    # No separate toolbar widgets to crop against — return the rect as-is.
    if len(rects) == 1:
        return outer

    edge_tolerance = 4
    left = right = top = bottom = 0
    for r in rects:
        if abs(r.left() - outer.left()) <= edge_tolerance:
            left = max(left, r.right() - outer.left() + 1)
        if abs(r.right() - outer.right()) <= edge_tolerance:
            right = max(right, outer.right() - r.left() + 1)
        if abs(r.top() - outer.top()) <= edge_tolerance:
            top = max(top, r.bottom() - outer.top() + 1)
        if abs(r.bottom() - outer.bottom()) <= edge_tolerance:
            bottom = max(bottom, outer.bottom() - r.top() + 1)

    inner = QtCore.QRect(
        outer.left() + left,
        outer.top() + top,
        outer.width() - left - right,
        outer.height() - top - bottom,
    )
    if inner.width() <= 0 or inner.height() <= 0:
        return outer
    return inner


def is_viewport_visible(main_window):
    rect = find_viewport_rect(main_window)
    return rect is not None and rect.width() > 50 and rect.height() > 50


def _screen_for_point(point):
    app = QtWidgets.QApplication.instance()
    if hasattr(app, "screenAt"):
        screen = app.screenAt(point)
        if screen is not None:
            return screen
    return QtWidgets.QApplication.primaryScreen()


def capture_viewport(main_window):
    rect = find_viewport_inner_rect(main_window)
    if rect is None:
        return None
    screen = _screen_for_point(rect.topLeft())
    if screen is None:
        return None
    try:
        pix = screen.grabWindow(
            0, rect.x(), rect.y(), rect.width(), rect.height()
        )
        if pix is not None and not pix.isNull():
            return pix
    except Exception:
        pass
    return None


def list_viewport_candidates(main_window):
    out = []
    if main_window is None:
        return out
    for w in main_window.findChildren(QtWidgets.QWidget):
        title = (w.windowTitle() or "").lower()
        obj_name = (w.objectName() or "").lower()
        if any(k in title for k in ("3d", "view", "viewport", "mesh")) or any(
            k in obj_name for k in ("3d", "view", "viewport", "mesh")
        ):
            gp = w.mapToGlobal(QtCore.QPoint(0, 0))
            out.append(
                (
                    type(w).__name__,
                    w.objectName(),
                    w.windowTitle(),
                    w.isVisible(),
                    f"{w.width()}x{w.height()} @ ({gp.x()},{gp.y()})",
                )
            )
    return out


def diagnose_capture(main_window):
    lines = []
    widgets = _viewport_widgets(main_window)
    lines.append(f"viewport prefix: '{_VIEWPORT_PREFIX}'")
    lines.append(f"found {len(widgets)} visible matching widgets:")
    for w in widgets:
        gp = w.mapToGlobal(QtCore.QPoint(0, 0))
        lines.append(
            f"  {type(w).__name__} '{w.objectName()}' "
            f"size={w.width()}x{w.height()} global=({gp.x()},{gp.y()})"
        )
    outer = find_viewport_rect(main_window)
    if outer is None:
        lines.append("outer rect: None")
    else:
        lines.append(
            f"outer rect:    ({outer.x()},{outer.y()}) "
            f"{outer.width()}x{outer.height()}"
        )
    inner = find_viewport_inner_rect(main_window)
    if inner is None:
        lines.append("inner rect: None")
    else:
        lines.append(
            f"inner rect:    ({inner.x()},{inner.y()}) "
            f"{inner.width()}x{inner.height()}"
        )
    pix = capture_viewport(main_window)
    if pix is None:
        lines.append("capture result: None")
    else:
        lines.append(
            f"capture result: {pix.width()}x{pix.height()} isNull={pix.isNull()}"
        )
    return "\n".join(lines)
