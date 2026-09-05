# SPDX-License-Identifier: GPL-3.0-or-later
"""Reads ``projectData.json`` and the project's ``image_dump/``.

**Read-only, always.** The add-on never writes ``projectData.json`` and never
writes UVs into the ``.blend``. The only thing it writes into the project is the
sidecar link file (see ``sidecar.py``), which the tool treats as advisory.

Nothing the add-on stores is allowed to disagree with this file, so the sheet, a
sheet's resolution and a trim's transform are re-read here on every panel draw
and every export rather than cached in the ``.blend``. The cache below exists
only to avoid re-parsing JSON on every UI redraw; it invalidates on mtime.

The tool autosaves 800 ms after every edit, so a read can land mid-write. The
tool writes temp-then-rename to make that atomic, but this reader still keeps the
previous snapshot on a parse error instead of blanking the panel - an older
version of the truth beats none.

Asset grouping
--------------
``image_dump/`` is grouped into assets **exactly** the way the tool's
``AssetScanner`` does it, because a disagreement means the two sides do not even
agree on what an asset is. That is only possible because the tool caches its
``maps.yaml`` vocabulary into ``projectData.json`` under ``maps`` - the file
itself lives next to the tool binary and is unreachable from here. When a
project has no cached vocabulary (written before the cache existed, or never
refreshed) the defaults below are used, and the two can then disagree on a name
like ``old_wood_v2.png``.
"""

import json
import os
import time

__all__ = [
    "TrimItem",
    "Sheet",
    "MapVocabulary",
    "ProjectSnapshot",
    "ProjectCache",
    "AssetCache",
    "DATA_FILE",
    "IMAGE_DUMP",
]

DATA_FILE = "projectData.json"
IMAGE_DUMP = "image_dump"

#: Mirrors ``AssetScanner.MAX_DEPTH``. Depth-limited so a symlink loop or a dump
#: pointed at something huge cannot hang the scan.
MAX_DEPTH = 8

#: Mirrors ``AssetScanner.IMAGE_EXTENSIONS``.
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".tga", ".bmp", ".tif", ".tiff")

#: Used only when ``projectData.json`` carries no cached vocabulary. Mirrors
#: ``MapConfig.fallback()`` on the tool side.
DEFAULT_SUFFIX_DELIMS = ("_",)
DEFAULT_KNOWN_MAPS = (
    "BaseColor", "Roughness", "Metallic", "AO", "Normal", "Height", "Emissive",
)

#: Preferred map names when picking one file out of an asset's siblings for the
#: Create Material button. First match wins.
BASE_COLOR_MAPS = ("basecolor", "albedo", "diffuse", "color", "basemap", "col")
NORMAL_MAPS = ("normal", "normalgl", "normaldx", "nrm", "norm")


#: The single ``projectData.json`` reader and the last ``image_dump/`` scan.
#: They live here rather than in ``settings`` so that ``assignment`` can reach
#: them without importing ``settings`` - ``settings`` already imports
#: ``assignment`` for its PropertyGroup type, and a cycle would make the whole
#: package import-order dependent.
CACHE = None
ASSETS = None


class MapVocabulary:
    """The tool's ``maps.yaml``, as cached into ``projectData.json``.

    ``normalize`` and ``split`` reproduce ``MapConfig``/``AssetScanner``
    character for character. In particular ``normalize`` **only** rewrites
    delimiters - it does not collapse repeats or strip edges, because the tool
    does not either, and ``old__wood`` must group the same way on both sides.
    """

    __slots__ = ("suffix_delims", "known_maps", "_sorted_delims", "_lookup")

    def __init__(self, suffix_delims=None, known_maps=None):
        self.suffix_delims = tuple(suffix_delims or DEFAULT_SUFFIX_DELIMS)
        self.known_maps = tuple(known_maps or DEFAULT_KNOWN_MAPS)
        # Longest first, so a two-character delimiter is not chewed up by a
        # one-character one that happens to be its prefix.
        self._sorted_delims = tuple(
            sorted((d for d in self.suffix_delims if d), key=len, reverse=True)
        )
        self._lookup = {name.lower(): name for name in self.known_maps}

    @property
    def primary_map(self):
        return self.known_maps[0] if self.known_maps else "BaseColor"

    def normalize(self, text):
        for delim in self._sorted_delims:
            if delim != "_":
                text = text.replace(delim, "_")
        return text

    def canonical(self, map_name):
        return self._lookup.get(map_name.lower())

    def split(self, stem):
        """``wood_BaseColor`` -> ``("wood", "BaseColor")``.

        Matches on the LAST delimiter so a base name may contain one itself
        (``old_wood_BaseColor`` -> ``old_wood``). An unrecognised suffix is not
        a suffix at all: the whole normalized stem becomes the base name and the
        map is the primary, so a plain ``brick.png`` still reads as an asset.
        """
        normalized = self.normalize(stem)
        index = normalized.rfind("_")
        if index <= 0:
            return (normalized, self.primary_map)
        canonical = self.canonical(normalized[index + 1:])
        if canonical is None:
            return (normalized, self.primary_map)
        return (normalized[:index], canonical)

    @classmethod
    def parse(cls, raw):
        if not isinstance(raw, dict):
            return cls()
        delims = raw.get("suffixDelims")
        known = raw.get("knownMaps")
        return cls(
            [str(d) for d in delims] if isinstance(delims, list) else None,
            [str(m) for m in known] if isinstance(known, list) else None,
        )


class TrimItem:
    """One trim instance placed on a sheet."""

    __slots__ = ("id", "asset_base_name", "position", "scale", "rotation", "crop",
                 "visible", "sheet")

    def __init__(self, id, asset_base_name, position, scale, rotation, crop, visible, sheet):
        self.id = id
        self.asset_base_name = asset_base_name
        self.position = position
        self.scale = scale
        self.rotation = rotation
        self.crop = crop
        #: Hidden in the tool. A hidden trim is **not on the sheet**: the tool's
        #: exporter skips it, so its region of the PNG is empty and there is
        #: nothing to map UVs onto. Still parsed rather than dropped, so the
        #: panel can say "hidden" instead of the misleading "missing trim link".
        self.visible = visible
        self.sheet = sheet

    @property
    def label(self):
        return self.asset_base_name or self.id[:8]


class Sheet:
    """One trim sheet. The UI calls this a **Trim**."""

    __slots__ = ("id", "name", "resolution", "enabled_preset_names", "items")

    def __init__(self, id, name, resolution, enabled_preset_names, items):
        self.id = id
        self.name = name
        self.resolution = resolution
        self.enabled_preset_names = enabled_preset_names
        self.items = items


class ProjectSnapshot:
    """One successful parse of ``projectData.json``."""

    __slots__ = ("root", "version", "default_resolution", "sheets", "maps",
                 "has_cached_vocabulary", "_trims", "stamp")

    def __init__(self, root, version, default_resolution, sheets, maps,
                 has_cached_vocabulary, stamp):
        self.root = root
        self.version = version
        self.default_resolution = default_resolution
        self.sheets = sheets
        self.maps = maps
        self.has_cached_vocabulary = has_cached_vocabulary
        self.stamp = stamp
        self._trims = {}
        for sheet in sheets:
            for item in sheet.items:
                # A project-wide duplicate id would make resolution ambiguous.
                # The tool re-mints duplicates on load; first-wins here just
                # keeps a hand-edited file from crashing the panel.
                self._trims.setdefault(item.id, item)

    def find_trim(self, trim_id):
        """The only trim resolution path. ``assetBaseName`` is never a key."""
        return self._trims.get(trim_id) if trim_id else None

    def find_sheet(self, sheet_id):
        for sheet in self.sheets:
            if sheet.id == sheet_id:
                return sheet
        return None

    @property
    def trim_count(self):
        return len(self._trims)

    @property
    def image_dump(self):
        return os.path.join(self.root, IMAGE_DUMP)

    @classmethod
    def parse(cls, root, raw, stamp):
        sheets = []
        for raw_sheet in raw.get("sheets") or []:
            sheet = Sheet(
                id=str(raw_sheet.get("id") or ""),
                name=str(raw_sheet.get("name") or "(unnamed)"),
                resolution=_resolution(raw_sheet.get("resolution"), (2048, 2048)),
                enabled_preset_names=list(raw_sheet.get("enabledPresetNames") or []),
                items=[],
            )
            for raw_item in raw_sheet.get("items") or []:
                transform = raw_item.get("transform") or {}
                sheet.items.append(
                    TrimItem(
                        id=str(raw_item.get("id") or ""),
                        asset_base_name=str(raw_item.get("assetBaseName") or ""),
                        position=_vec2(transform.get("position"), (0.5, 0.5)),
                        scale=_vec2(transform.get("scale"), (0.25, 0.25)),
                        rotation=_number(transform.get("rotation"), 0.0),
                        crop=_vec2(raw_item.get("crop") or {}, (0.0, 0.0)),
                        # Absent means visible - a project written before hiding
                        # existed must not read as everything-hidden.
                        visible=raw_item.get("visible") is not False,
                        sheet=sheet,
                    )
                )
            sheets.append(sheet)

        defaults = raw.get("defaults") or {}
        return cls(
            root=root,
            version=str(raw.get("version") or "?"),
            default_resolution=_resolution(
                defaults.get("defaultTrimResolution"), (2048, 2048)
            ),
            sheets=sheets,
            maps=MapVocabulary.parse(raw.get("maps")),
            has_cached_vocabulary=isinstance(raw.get("maps"), dict),
            stamp=stamp,
        )


class ProjectCache:
    """mtime-keyed loader. One instance lives in ``settings``."""

    #: A panel redraws far more often than the file changes, and the project may
    #: sit on a synced drive where ``stat`` is not free.
    STAT_INTERVAL = 0.4

    def __init__(self):
        self._root = None
        self._snapshot = None
        self._error = None
        self._checked_at = 0.0

    @property
    def error(self):
        """Last load failure, or None. Kept alongside a stale snapshot."""
        return self._error

    @property
    def snapshot(self):
        """Whatever was last parsed, without touching the disk."""
        return self._snapshot

    def invalidate(self):
        self._checked_at = 0.0
        if self._root is None:
            self._snapshot = None

    def get(self, root, force=False):
        """Current snapshot for *root*, reloading if the file changed."""
        root = (root or "").strip()
        if not root:
            self._root = None
            self._snapshot = None
            self._error = None
            return None

        if root != self._root:
            self._root = root
            self._snapshot = None
            self._error = None
            force = True

        now = time.monotonic()
        if not force and (now - self._checked_at) < self.STAT_INTERVAL:
            return self._snapshot
        self._checked_at = now

        path = os.path.join(root, DATA_FILE)
        try:
            info = os.stat(path)
        except OSError:
            self._snapshot = None
            self._error = "No %s in \"%s\"" % (DATA_FILE, root)
            return None

        stamp = (info.st_mtime_ns, info.st_size)
        if self._snapshot is not None and self._snapshot.stamp == stamp:
            self._error = None
            return self._snapshot

        try:
            with open(path, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
        except (OSError, ValueError) as err:
            # Most likely a read that raced the tool's autosave. Keep the
            # previous snapshot and retry on the next poll.
            self._error = "%s could not be read: %s" % (DATA_FILE, err)
            self._checked_at = 0.0
            return self._snapshot

        if not isinstance(raw, dict):
            self._error = "%s is not an object" % DATA_FILE
            return self._snapshot

        self._snapshot = ProjectSnapshot.parse(root, raw, stamp)
        self._error = None
        return self._snapshot


# ---------------------------------------------------------------------------
# image_dump scanning
# ---------------------------------------------------------------------------

def collect_files(folder, depth=0):
    """Every image at or below *folder*. Depth-limited, dot-folders skipped.

    Mirrors ``AssetScanner.collect``.
    """
    try:
        entries = sorted(os.listdir(folder))
    except OSError:
        # No image_dump yet, or a subfolder we cannot read. Neither is fatal.
        return []

    found = []
    for name in entries:
        full = os.path.join(folder, name)
        if os.path.isdir(full):
            if name.startswith(".") or depth >= MAX_DEPTH:
                continue
            found.extend(collect_files(full, depth + 1))
        elif os.path.splitext(name)[1].lower() in IMAGE_EXTENSIONS:
            found.append(full)
    return found


def scan_assets(root, vocabulary):
    """Group ``image_dump/`` into assets exactly as the tool's scanner does.

    Returns ``[(base_name, {map_name: absolute_path}), ...]`` sorted by name.

    A file in a subfolder carries the folder in its base name (``stone/wall``),
    so two ``wall_BaseColor.png`` in different folders stay separate assets and
    only siblings in the SAME folder group together. Top-level files keep their
    bare name. On a base+map collision the **first** file wins, matching the
    tool - the loser is simply not returned.
    """
    dump = os.path.join(root or "", IMAGE_DUMP)
    grouped = {}
    order = []

    for path in collect_files(dump):
        relative = os.path.relpath(path, dump).replace(os.sep, "/")
        stem_with_folder = os.path.splitext(relative)[0]

        cut = stem_with_folder.rfind("/")
        folder = "" if cut < 0 else stem_with_folder[:cut + 1]
        stem = stem_with_folder if cut < 0 else stem_with_folder[cut + 1:]

        stem_base, map_name = vocabulary.split(stem)
        base_name = folder + stem_base

        maps = grouped.get(base_name)
        if maps is None:
            maps = {}
            grouped[base_name] = maps
            order.append(base_name)
        maps.setdefault(map_name, path)

    order.sort()
    return [(name, grouped[name]) for name in order]


class AssetCache:
    """The last ``image_dump/`` scan.

    Not mtime-polled: a recursive walk is far too expensive to run on every
    panel redraw, and a directory's mtime does not change when a file inside a
    subfolder is replaced anyway. The **Refresh** button is the documented way
    to pick up a changed dump, which is also what the tool's own Refresh does.
    """

    def __init__(self):
        self._key = None
        self._assets = []

    def get(self, snapshot, force=False):
        if snapshot is None:
            self._key = None
            self._assets = []
            return []
        key = (snapshot.root, snapshot.maps.suffix_delims, snapshot.maps.known_maps)
        if force or key != self._key:
            self._assets = scan_assets(snapshot.root, snapshot.maps)
            self._key = key
        return self._assets

    def invalidate(self):
        self._key = None


def find_asset_image(assets, base_name, prefer=BASE_COLOR_MAPS):
    """One representative file for an asset, or None.

    *assets* is the list from :func:`scan_assets`. Prefers a base-colour-ish
    map, then anything, so the Create Material button still has something to
    work with for an asset that only ships a Roughness.
    """
    for name, maps in assets:
        if name != base_name:
            continue
        lowered = {key.lower(): value for key, value in maps.items()}
        for wanted in prefer:
            if wanted in lowered:
                return lowered[wanted]
        return next(iter(maps.values()), None)
    return None


# ---------------------------------------------------------------------------

def _number(value, default):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return default if result != result else result  # NaN guard


def _vec2(raw, default):
    if not isinstance(raw, dict):
        return default
    return (_number(raw.get("x"), default[0]), _number(raw.get("y"), default[1]))


def _resolution(raw, default):
    if not isinstance(raw, dict):
        return default
    return (
        max(int(_number(raw.get("width"), default[0])), 1),
        max(int(_number(raw.get("height"), default[1])), 1),
    )


CACHE = ProjectCache()
ASSETS = AssetCache()
