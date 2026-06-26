import os
import re
import shutil

_VER_RE = re.compile(r"^(.*)_ver_(\d+)$")


def base_name(stem):
    m = _VER_RE.match(stem)
    return m.group(1) if m else stem


def next_version_name(source_stem, sibling_stems):
    base = base_name(source_stem)
    n = 1
    while f"{base}_ver_{n}" in sibling_stems:
        n += 1
    return f"{base}_ver_{n}"


def duplicate_project(source_path):
    source_dir = os.path.dirname(source_path)
    source_stem = os.path.splitext(os.path.basename(source_path))[0]

    siblings = set()
    if os.path.isdir(source_dir):
        for fname in os.listdir(source_dir):
            if fname.lower().endswith(".spp"):
                siblings.add(os.path.splitext(fname)[0])

    new_name = next_version_name(source_stem, siblings)
    new_path = os.path.join(source_dir, f"{new_name}.spp")
    shutil.copy2(source_path, new_path)
    return new_path, new_name


_INVALID_NAME_CHARS = set('\\/:*?"<>|')


def is_valid_name(name):
    if not name:
        return False
    if name.startswith('.') or name.endswith('.'):
        return False
    return not any(c in _INVALID_NAME_CHARS for c in name)


def _family_members(source_dir, old_base):
    members = []
    if not os.path.isdir(source_dir):
        return members
    for fname in os.listdir(source_dir):
        if not fname.lower().endswith('.spp'):
            continue
        stem = os.path.splitext(fname)[0]
        if base_name(stem) == old_base:
            members.append((os.path.join(source_dir, fname), stem))
    return members


def plan_family_rename(project_path, new_base, include_iterations=False):
    """Plan a rename of the project family. Returns (new_current_path, ops):
    new_current_path is where the caller should save_as the active project.
    The active project becomes literally `{new_base}.spp` — any _ver_N
    suffix it had is dropped. When include_iterations is False, ops is
    empty — only the active .spp gets renamed. When True, ops covers
    sibling _ver_N .spp files (renamed to `{new_base}_ver_N.spp`), the
    _iterations folder, and the PNG snapshots inside.
    Returns (None, []) if no rename is needed."""
    if not is_valid_name(new_base):
        raise ValueError("Invalid project name")

    source_dir = os.path.dirname(project_path)
    source_stem = os.path.splitext(os.path.basename(project_path))[0]
    old_base = base_name(source_stem)

    new_current_path = os.path.join(source_dir, f"{new_base}.spp")
    if os.path.normcase(new_current_path) == os.path.normcase(project_path):
        return None, []
    if os.path.exists(new_current_path):
        raise ValueError(
            f"File already exists: {os.path.basename(new_current_path)}"
        )

    ops = []
    if not include_iterations:
        return new_current_path, ops

    for old_path, stem in _family_members(source_dir, old_base):
        if os.path.normcase(old_path) == os.path.normcase(project_path):
            continue
        m = _VER_RE.match(stem)
        if m is None:
            raise ValueError(
                f"'{os.path.basename(old_path)}' would collide with"
                f" '{os.path.basename(new_current_path)}'. Remove or rename"
                " it first."
            )
        new_path = os.path.join(
            source_dir, f"{new_base}_ver_{m.group(2)}.spp"
        )
        if os.path.exists(new_path):
            raise ValueError(
                f"File already exists: {os.path.basename(new_path)}"
            )
        ops.append((old_path, new_path))

    old_iter = os.path.join(source_dir, f"{old_base}_iterations")
    new_iter = os.path.join(source_dir, f"{new_base}_iterations")
    if os.path.isdir(old_iter):
        for fname in os.listdir(old_iter):
            if not fname.lower().endswith('.png'):
                continue
            stem = os.path.splitext(fname)[0]
            tail = '_tile' if stem.endswith('_tile') else ''
            core = stem[: -len(tail)] if tail else stem
            if core == source_stem:
                new_core = new_base
            else:
                m = _VER_RE.match(core)
                if m is None or m.group(1) != old_base:
                    continue
                new_core = f"{new_base}_ver_{m.group(2)}"
            new_fname = f"{new_core}{tail}.png"
            old_fpath = os.path.join(old_iter, fname)
            new_fpath = os.path.join(old_iter, new_fname)
            if os.path.normcase(old_fpath) != os.path.normcase(new_fpath):
                ops.append((old_fpath, new_fpath))
        if os.path.normcase(old_iter) != os.path.normcase(new_iter):
            if os.path.exists(new_iter):
                raise ValueError(
                    f"Folder already exists: {new_base}_iterations"
                )
            ops.append((old_iter, new_iter))

    return new_current_path, ops


def apply_rename_ops(ops):
    for old_path, new_path in ops:
        os.rename(old_path, new_path)


def find_locked_paths(paths):
    """Return paths from the input that cannot be opened for exclusive
    read+write access — typically because another process has them open.
    Directories are skipped; check files inside them instead."""
    locked = []
    for p in paths:
        if not os.path.exists(p) or os.path.isdir(p):
            continue
        try:
            with open(p, 'rb+'):
                pass
        except OSError:
            locked.append(p)
    return locked
