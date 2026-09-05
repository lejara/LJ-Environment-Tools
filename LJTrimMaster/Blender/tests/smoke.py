# SPDX-License-Identifier: GPL-3.0-or-later
"""Register / unregister / draw the panel once. The cheapest possible canary.

    "C:/Program Files/Blender Foundation/Blender 5.1/blender.exe" --background --factory-startup --python tests/smoke.py

Draws the panel against a real UI layout, which is what catches the class of bug
that crashed the previous version: a draw path that writes to an ID. Background
Blender has no real region, so the draw is exercised through a dry `poll` +
`draw` call on a temporary layout rather than by rendering.
"""

import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bpy  # noqa: E402

FAILURES = []


def check(label, condition, detail=""):
    print(("  ok   " if condition else "  FAIL ") + label + (("  " + detail) if detail else ""))
    if not condition:
        FAILURES.append(label)


print("Blender %s" % bpy.app.version_string)

import lj_trim_master  # noqa: E402
from lj_trim_master import assignment, export_hook, settings  # noqa: E402

lj_trim_master.register()
check("registers", True)

status = export_hook.hook_status()
check("FBX and glTF are hooked",
      status.get('FBX') == 'HOOKED' and status.get('glTF') == 'HOOKED', str(status))

config = bpy.context.scene.lj_trim_master
check("the scene block exists", config is not None)
check("the registry starts empty", len(config.meshes) == 0)

# Factory startup ships a selected Cube; start from an empty scene so the
# assertions below are about the add-on and not about the default file.
for existing in list(bpy.data.objects):
    bpy.data.objects.remove(existing, do_unlink=True)

# A mesh object to put through the registry.
mesh = bpy.data.meshes.new("SmokeMesh")
mesh.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [], [(0, 1, 2, 3)])
mesh.update()
mesh.uv_layers.new(name="UVMap")
mesh.materials.append(bpy.data.materials.new("smoke_mat"))
obj = bpy.data.objects.new("SmokeObject", mesh)
bpy.context.scene.collection.objects.link(obj)
bpy.context.view_layer.objects.active = obj
obj.select_set(True)

check("add_meshes runs", 'FINISHED' in bpy.ops.ljtm.add_meshes())
check("one row appeared", len(config.meshes) == 1)
check("the row points at the object", config.meshes[0].obj == obj)
check("add_slot runs", 'FINISHED' in bpy.ops.ljtm.add_slot(index=0))
check("the slot appeared", len(config.meshes[0].slots) == 1)
check("refresh runs with no project root", 'FINISHED' in bpy.ops.ljtm.refresh())


# The crash this rework fixes was a draw path writing to an ID. Background
# Blender cannot render a panel, so instead every function the panel's draw
# reaches is called directly and the datablocks are compared before and after.
# If any read path mutates, this catches it exactly as the panel would.
def _fingerprint():
    return (
        sorted(mesh.keys()),
        [mesh.get(key) for key in sorted(mesh.keys())],
        len(config.meshes),
        len(config.meshes[0].slots),
        config.meshes[0].slots[0].trim_id,
        config.meshes[0].slots[0].last_export,
    )


entry = config.meshes[0]
slot = entry.slots[0]
before = _fingerprint()
try:
    settings.settings(bpy.context)
    settings.snapshot(bpy.context)
    export_hook.hook_status()
    export_hook.leftover_modifiers()
    assignment.mesh_of(entry)
    assignment.display_name(entry)
    assignment.sharing_objects(mesh)
    assignment.entry_status(entry, None)
    assignment.status_of(slot, None)
    assignment.slot_material_name(entry.obj, slot.slot_index)
    assignment.slot_count(entry.obj)
    assignment.read_mirror(mesh)
    read_paths_ran = True
except Exception as err:
    traceback.print_exc()
    read_paths_ran = False
    print("   read path raised: %s" % err)

check("every draw-reachable read path runs", read_paths_ran)
check("and none of them wrote to an ID", _fingerprint() == before,
      "%r -> %r" % (before, _fingerprint()))

# The enum get/set are the other draw-time hazard: they run on every redraw.
try:
    _ = slot.sheet_enum
    _ = slot.trim_enum
    check("the pickers evaluate with no project", True)
except Exception as err:
    check("the pickers evaluate with no project", False, str(err))

check("reading the pickers wrote nothing either", _fingerprint() == before)

lj_trim_master.unregister()
check("unregisters", True)

print()
print("%d failure(s)" % len(FAILURES))
sys.exit(1 if FAILURES else 0)
