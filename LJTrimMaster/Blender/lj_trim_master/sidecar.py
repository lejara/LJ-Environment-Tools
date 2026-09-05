# SPDX-License-Identifier: GPL-3.0-or-later
"""The object-to-trim link file the tool reads.

The mapping has to be visible from outside the ``.blend``, or Phase 4 has no
data channel and the tool cannot warn before a destructive edit - deleting a
trim that three meshes are unwrapped against.

One JSON per ``.blend``, written into the project root::

    <projectRoot>/blender_links/<blend-stem>-<short-hash-of-full-path>.json

The hash disambiguates two ``.blend`` files that share a stem in different
folders, which is common (``props/crate.blend`` and ``kit/crate.blend``).

**This is the only thing the add-on writes into the project**, and the tool must
treat it as read-only and possibly stale: the ``.blend`` may have been moved,
renamed or deleted since. Surface it as information, never as truth.

Written on assignment change, on export, and on ``save_post``. Writes are
temp-then-rename so the tool can never read a half-written file.

**Unconditional.** There is no toggle and no button. The tool's warning before a
destructive edit is only as good as the freshest link file, and a switch that can
be left off makes it worthless exactly when it matters.
"""

import hashlib
import json
import os
import tempfile

import bpy

from . import assignment, settings

__all__ = ["SCHEMA_VERSION", "LINKS_DIR", "sidecar_path", "write_for_scene"]

#: Shape of the file below. The tool checks it before trusting the contents.
SCHEMA_VERSION = 1

LINKS_DIR = "blender_links"


def sidecar_name(blend_path):
    """``<stem>-<hash8>.json`` for a ``.blend`` path, or None if unsaved."""
    if not blend_path:
        return None
    absolute = os.path.abspath(blend_path)
    # Windows paths are case-insensitive, so the same file reached two ways must
    # hash the same. Separators are normalized for the same reason.
    canonical = absolute.replace("\\", "/")
    if os.name == "nt":
        canonical = canonical.lower()
    digest = hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:8]
    stem = os.path.splitext(os.path.basename(absolute))[0] or "untitled"
    return "%s-%s.json" % (_safe(stem), digest)


def sidecar_path(root, blend_path):
    name = sidecar_name(blend_path)
    if not root or name is None:
        return None
    return os.path.join(root, LINKS_DIR, name)


def gather_links(context, snapshot):
    """One entry per assigned slot, per **object**.

    Per object, not per mesh: the tool's warning is about which objects are
    linked to a trim, so two objects sharing a datablock are two links even
    though they carry one assignment.
    """
    config = settings.settings(context)
    if config is None:
        return []

    links = []
    for entry in config.meshes:
        obj = entry.obj
        mesh = assignment.mesh_of(entry)
        if obj is None or mesh is None:
            continue
        for slot in entry.slots:
            if not slot.trim_id:
                continue
            item = snapshot.find_trim(slot.trim_id) if snapshot else None
            links.append({
                "objectName": obj.name,
                "meshName": mesh.name,
                "slotIndex": slot.slot_index,
                "materialName": slot.material_name,
                "trimId": slot.trim_id,
                # Normalized, as the tool stores it - not necessarily a filename.
                "assetBaseName": item.asset_base_name if item else slot.asset_base_name,
                "sheetId": item.sheet.id if item else None,
                "sheetName": item.sheet.name if item else (slot.sheet_name or None),
                # False means this .blend has a trim_id the project no longer
                # has. The tool should show it, not act on it.
                "resolved": item is not None,
                # Resolvable but hidden, so currently unexportable. Distinct
                # from unresolved: the link is fine, the trim is just off.
                "hidden": bool(item is not None and not item.visible),
            })
    links.sort(key=lambda link: (link["objectName"], link["slotIndex"]))
    return links


def write_for_scene(context, report=None):
    """Rewrite this ``.blend``'s link file. Returns the path, or None.

    Silent when there is no project root or the file has never been saved -
    both are ordinary states, and ``save_post`` will catch up. Pass *report* to
    surface a real failure.
    """
    root = settings.project_root(context)
    blend_path = bpy.data.filepath
    if not root:
        return None
    if not blend_path:
        if report:
            report("Save the .blend before the tool can see its trim links")
        return None

    path = sidecar_path(root, blend_path)
    if path is None:
        return None

    snapshot = settings.snapshot(context)
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "recordSchemaVersion": assignment.MIRROR_VERSION,
        "blendPath": os.path.abspath(blend_path).replace("\\", "/"),
        "links": gather_links(context, snapshot),
    }

    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _atomic_write(path, json.dumps(payload, indent=2))
    except OSError as err:
        if report:
            report("Could not write %s: %s" % (os.path.basename(path), err))
        return None
    return path


def _atomic_write(path, text):
    """Temp file in the destination folder, then rename over the target.

    The tool may read this at any moment; a plain write would let it see a
    truncated file. Same-directory temp keeps the rename on one filesystem, so
    it is atomic.
    """
    folder = os.path.dirname(path)
    handle, temp = tempfile.mkstemp(dir=folder, prefix=".ljtm-", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.replace(temp, path)
    except BaseException:
        try:
            os.unlink(temp)
        except OSError:
            pass
        raise


def _safe(name):
    return "".join(char if char not in '<>:"/\\|?*' else "_" for char in name)


classes = ()
