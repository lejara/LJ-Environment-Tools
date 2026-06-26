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
