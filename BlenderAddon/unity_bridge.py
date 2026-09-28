# pyright: reportInvalidTypeForm=none
"""Localhost server that lets Unity send FBX files into this running Blender.

Each running instance advertises itself with %TEMP%/LJBridge/<pid>.json
({pid, port, file, version}). Unity lists those files, connects to the chosen
port and sends {"cmd": "import_fbx", "path": "..."}. The socket runs on a
background thread; imports are queued and run on the main thread via a timer.
"""
import atexit
import json
import os
import queue
import socket
import tempfile
import threading

import bpy
from bpy.app.handlers import persistent

BRIDGE_DIR = os.path.join(tempfile.gettempdir(), "LJBridge")
_POLL_INTERVAL = 0.25

_server_socket = None
_server_thread = None
_stop_event = threading.Event()
_pending = queue.Queue()
_port = 0


def is_running():
    return _server_socket is not None


def port():
    return _port


def _info_path():
    return os.path.join(BRIDGE_DIR, f"{os.getpid()}.json")


def _write_info():
    if not is_running():
        return
    try:
        filepath = bpy.data.filepath
    except AttributeError:
        filepath = ""
    info = {
        "pid": os.getpid(),
        "port": _port,
        "file": os.path.basename(filepath) if filepath else "Untitled",
        "version": bpy.app.version_string,
    }
    os.makedirs(BRIDGE_DIR, exist_ok=True)
    with open(_info_path(), "w", encoding="utf-8") as f:
        json.dump(info, f)


def _remove_info():
    try:
        os.remove(_info_path())
    except OSError:
        pass


def _handle_client(conn):
    with conn:
        conn.settimeout(5.0)
        chunks = []
        try:
            while True:
                data = conn.recv(4096)
                if not data:
                    break
                chunks.append(data)
            msg = json.loads(b"".join(chunks).decode("utf-8"))
        except (OSError, ValueError) as e:
            _reply(conn, {"ok": False, "error": f"Bad request: {e}"})
            return

        if msg.get("cmd") != "import_fbx" or not msg.get("path"):
            _reply(conn, {"ok": False, "error": "Unknown command"})
            return
        if not os.path.isfile(msg["path"]):
            _reply(conn, {"ok": False, "error": f"File not found: {msg['path']}"})
            return

        _pending.put(msg["path"])
        _reply(conn, {"ok": True})


def _reply(conn, payload):
    try:
        conn.sendall(json.dumps(payload).encode("utf-8"))
    except OSError:
        pass


def _serve(sock):
    while not _stop_event.is_set():
        try:
            conn, _addr = sock.accept()
        except socket.timeout:
            continue
        except OSError:
            break
        _handle_client(conn)


def _import_fbx(path):
    window = bpy.context.window or (bpy.context.window_manager.windows[0]
                                    if bpy.context.window_manager.windows else None)
    if window is None:
        print(f"[LJ Bridge] No window available to import {path}")
        return
    area = next((a for a in window.screen.areas if a.type == 'VIEW_3D'), None)
    override = {"window": window, "screen": window.screen}
    if area is not None:
        override["area"] = area
    with bpy.context.temp_override(**override):
        if bpy.context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.select_all(action='DESELECT')
        bpy.ops.import_scene.fbx(filepath=path)
    print(f"[LJ Bridge] Imported {path}")


def _process_queue():
    if not is_running():
        return None
    while True:
        try:
            path = _pending.get_nowait()
        except queue.Empty:
            break
        try:
            _import_fbx(path)
        except Exception as e:
            print(f"[LJ Bridge] Import failed for {path}: {e}")
    return _POLL_INTERVAL


def start():
    global _server_socket, _server_thread, _port
    if is_running():
        return
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(4)
    sock.settimeout(0.5)
    _server_socket = sock
    _port = sock.getsockname()[1]
    _stop_event.clear()
    _server_thread = threading.Thread(target=_serve, args=(sock,), daemon=True)
    _server_thread.start()
    if not bpy.app.timers.is_registered(_process_queue):
        bpy.app.timers.register(_process_queue, first_interval=_POLL_INTERVAL, persistent=True)
    _write_info()
    print(f"[LJ Bridge] Server listening on 127.0.0.1:{_port}")


def stop():
    global _server_socket, _server_thread, _port
    if not is_running():
        return
    _stop_event.set()
    try:
        _server_socket.close()
    except OSError:
        pass
    if _server_thread is not None:
        _server_thread.join(timeout=1.0)
    _server_socket = None
    _server_thread = None
    _port = 0
    if bpy.app.timers.is_registered(_process_queue):
        bpy.app.timers.unregister(_process_queue)
    _remove_info()
    print("[LJ Bridge] Server stopped")


def apply_enabled(enabled):
    if enabled:
        start()
    else:
        stop()


@persistent
def _on_file_changed(_dummy):
    _write_info()


_HANDLER_LISTS = (bpy.app.handlers.load_post, bpy.app.handlers.save_post)


def register():
    for handlers in _HANDLER_LISTS:
        if _on_file_changed not in handlers:
            handlers.append(_on_file_changed)
    atexit.register(stop)


def unregister():
    stop()
    atexit.unregister(stop)
    for handlers in _HANDLER_LISTS:
        if _on_file_changed in handlers:
            handlers.remove(_on_file_changed)
