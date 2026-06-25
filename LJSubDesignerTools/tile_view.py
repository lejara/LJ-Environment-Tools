import os
import re

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets


_VER_RE = re.compile(r"^(.*)_ver_(\d+)$")
_TILE_SUFFIX = "_tile"


def base_name(identifier):
    m = _VER_RE.match(identifier)
    return m.group(1) if m else identifier


def _package_file(graph):
    try:
        return graph.getPackage().getFilePath() or ""
    except Exception:
        return ""


def iterations_dir(graph):
    sbs_path = _package_file(graph)
    if not sbs_path:
        return None
    base = os.path.splitext(os.path.basename(sbs_path))[0]
    return os.path.join(os.path.dirname(sbs_path), f"{base}_iterations")


def iteration_png_path(graph):
    folder = iterations_dir(graph)
    if folder is None:
        return None
    return os.path.join(folder, f"{graph.getIdentifier()}.png")


def tile_png_path(graph):
    folder = iterations_dir(graph)
    if folder is None:
        return None
    return os.path.join(folder, f"{base_name(graph.getIdentifier())}{_TILE_SUFFIX}.png")


_3D_VIEW_PREFIX = "3dview."


def _3d_view_widgets(main_window):
    if main_window is None:
        return []
    return [
        w
        for w in main_window.findChildren(QtWidgets.QWidget)
        if w.isVisible()
        and w.objectName().lower().startswith(_3D_VIEW_PREFIX)
    ]


def _widget_global_rects(main_window):
    rects = []
    for w in _3d_view_widgets(main_window):
        gp = w.mapToGlobal(QtCore.QPoint(0, 0))
        rects.append(QtCore.QRect(gp, w.size()))
    return rects


def find_3d_view_rect(main_window):
    """Global QRect spanning all visible 3dview.* widgets (the dock area)."""
    rects = _widget_global_rects(main_window)
    if not rects:
        return None
    outer = rects[0]
    for r in rects[1:]:
        outer = outer.united(r)
    if outer.width() <= 0 or outer.height() <= 0:
        return None
    return outer


def find_3d_viewport_rect(main_window):
    """Same as find_3d_view_rect but with toolbars cropped off each edge."""
    rects = _widget_global_rects(main_window)
    if not rects:
        return None
    outer = rects[0]
    for r in rects[1:]:
        outer = outer.united(r)
    if outer.width() <= 0 or outer.height() <= 0:
        return None

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

    viewport = QtCore.QRect(
        outer.left() + left,
        outer.top() + top,
        outer.width() - left - right,
        outer.height() - top - bottom,
    )
    if viewport.width() <= 0 or viewport.height() <= 0:
        return outer
    return viewport


def is_3d_view_visible(main_window):
    rect = find_3d_view_rect(main_window)
    return rect is not None and rect.width() > 50 and rect.height() > 50


def _screen_for_point(point):
    app = QtWidgets.QApplication.instance()
    if hasattr(app, "screenAt"):
        screen = app.screenAt(point)
        if screen is not None:
            return screen
    return QtWidgets.QApplication.primaryScreen()


def capture_3d_view(main_window):
    rect = find_3d_viewport_rect(main_window)
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


def list_3d_view_candidates(main_window):
    """Diagnostic — return all visible 3dview.* widgets."""
    out = []
    for w in _3d_view_widgets(main_window):
        gp = w.mapToGlobal(QtCore.QPoint(0, 0))
        out.append(
            (
                type(w).__name__,
                w.objectName(),
                w.windowTitle(),
                True,
                f"{w.width()}x{w.height()} @ ({gp.x()},{gp.y()})",
            )
        )
    return out


def diagnose_capture(main_window):
    lines = []
    widgets = _3d_view_widgets(main_window)
    lines.append(f"found {len(widgets)} visible 3dview.* widgets:")
    for w in widgets:
        gp = w.mapToGlobal(QtCore.QPoint(0, 0))
        lines.append(
            f"  {type(w).__name__} '{w.objectName()}' "
            f"size={w.width()}x{w.height()} global=({gp.x()},{gp.y()})"
        )
    rect = find_3d_view_rect(main_window)
    if rect is None:
        lines.append("outer rect: None")
    else:
        lines.append(
            f"outer rect:    ({rect.x()},{rect.y()}) {rect.width()}x{rect.height()}"
        )
    viewport = find_3d_viewport_rect(main_window)
    if viewport is None:
        lines.append("viewport rect: None")
    else:
        lines.append(
            f"viewport rect: ({viewport.x()},{viewport.y()}) {viewport.width()}x{viewport.height()}"
        )
    pix = capture_3d_view(main_window)
    if pix is None:
        lines.append("capture result: None")
    else:
        lines.append(
            f"capture result: {pix.width()}x{pix.height()} isNull={pix.isNull()}"
        )
    return "\n".join(lines)


def save_iteration_snapshot(graph, pixmap):
    path = iteration_png_path(graph)
    if path is None or pixmap is None or pixmap.isNull():
        return False
    folder = os.path.dirname(path)
    try:
        os.makedirs(folder, exist_ok=True)
    except Exception:
        return False
    return bool(pixmap.save(path, "PNG"))


def _iteration_sort_key(identifier):
    m = _VER_RE.match(identifier)
    if m:
        return (m.group(1), int(m.group(2)))
    return (identifier, -1)


def _existing_graph_ids(graph):
    try:
        package = graph.getPackage()
        return {r.getIdentifier() for r in package.getChildrenResources(True)}
    except Exception:
        return None


def collect_iteration_images(graph, delete_orphans=True):
    folder = iterations_dir(graph)
    if folder is None or not os.path.isdir(folder):
        return []
    existing_ids = _existing_graph_ids(graph)

    results = []
    for fname in os.listdir(folder):
        if not fname.lower().endswith(".png"):
            continue
        stem = os.path.splitext(fname)[0]
        if stem.endswith(_TILE_SUFFIX):
            continue
        if existing_ids is not None and stem not in existing_ids:
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


def build_tile_sheet(images, tiles_per_row, target_width):
    if not images or tiles_per_row < 1 or target_width < 1:
        return None

    padding = 8
    label_height = 20
    cell_w = max(1, (target_width - padding * (tiles_per_row + 1)) // tiles_per_row)

    first = images[0][1]
    aspect = first.height() / max(1, first.width())
    cell_img_h = max(1, int(cell_w * aspect))
    cell_h = cell_img_h + label_height + padding

    rows = (len(images) + tiles_per_row - 1) // tiles_per_row
    total_w = target_width
    total_h = padding + rows * cell_h

    sheet = QtGui.QPixmap(total_w, total_h)
    sheet.fill(QtGui.QColor(40, 40, 40))
    painter = QtGui.QPainter(sheet)
    try:
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
        painter.setPen(QtGui.QColor(220, 220, 220))
        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)

        for i, (name, pix) in enumerate(images):
            row = i // tiles_per_row
            col = i % tiles_per_row
            x = padding + col * (cell_w + padding)
            y = padding + row * cell_h
            scaled = pix.scaled(
                cell_w,
                cell_img_h,
                QtCore.Qt.KeepAspectRatio,
                QtCore.Qt.SmoothTransformation,
            )
            img_x = x + (cell_w - scaled.width()) // 2
            img_y = y + (cell_img_h - scaled.height()) // 2
            painter.drawPixmap(img_x, img_y, scaled)
            label_rect = QtCore.QRect(x, y + cell_img_h + 2, cell_w, label_height)
            painter.drawText(label_rect, QtCore.Qt.AlignCenter, name)
    finally:
        painter.end()
    return sheet


def save_tile_sheet(graph, sheet):
    path = tile_png_path(graph)
    if path is None or sheet is None or sheet.isNull():
        return False
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except Exception:
        return False
    return bool(sheet.save(path, "PNG"))
