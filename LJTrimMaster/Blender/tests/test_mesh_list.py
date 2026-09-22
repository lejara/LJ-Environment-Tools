# SPDX-License-Identifier: GPL-3.0-or-later
"""The scrollable, searchable Meshes list.

    "C:/Program Files/Blender Foundation/Blender 5.1/blender.exe" --background --factory-startup --python tests/test_mesh_list.py

Background Blender cannot render a panel, so the list's ordering and filtering
are exercised the only way that is testable headless: ``filter_items`` is called
directly. It is a plain method over the collection - the only RNA it reads off
``self`` is the four filter widgets - so a stub stands in for the registered
UIList instance, and what runs is the real code, not a copy of it.

Two behaviours are load-bearing and neither is obvious from the signature:

**``flt_neworder`` maps the ORIGINAL index to its new position**, not the other
way round. Inverting it silently produces a list that looks plausibly sorted and
puts the wrong rows on top whenever the permutation is not its own inverse.

**A search suppresses the selected-first sort.** Without that, clicking a row
selects its object, which re-sorts the list out from under the pointer.

Exits non-zero on failure. Separate process, so an open session is undisturbed.
"""

import os
import sys

import bpy

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

import lj_trim_master  # noqa: E402
from lj_trim_master import assignment, panel, settings  # noqa: E402

FAILURES = []
CHECKS = [0]


def _die(kind, value, trace):
    """Blender prints an uncaught traceback and still exits 0. Don't let it."""
    import traceback
    traceback.print_exception(kind, value, trace)
    sys.stdout.flush()
    os._exit(1)


sys.excepthook = _die


def check(label, condition, detail=""):
    CHECKS[0] += 1
    print(("  ok   " if condition else "  FAIL ") + label + (("  " + detail) if detail else ""))
    sys.stdout.flush()
    if not condition:
        FAILURES.append(label)


class FilterStub:
    """The filter widgets ``template_list`` owns, without the C UIList.

    ``bitflag_filter_item`` is an arbitrary bit in the real thing too - the
    contract is only that a row carrying it is the one shown.
    """

    bitflag_filter_item = 1 << 30

    def __init__(self, filter_name="", sort_alpha=False):
        self.filter_name = filter_name
        self.use_filter_sort_alpha = sort_alpha


def run_filter(config, **kwargs):
    """Call the real ``filter_items`` with a stubbed ``self``."""
    return panel.LJTM_UL_meshes.filter_items(
        FilterStub(**kwargs), bpy.context, config, "meshes"
    )


def shown(config, flags):
    """The names ``filter_items`` left visible, in registry order."""
    bit = FilterStub.bitflag_filter_item
    return [
        assignment.display_name(entry)
        for entry, flag in zip(config.meshes, flags)
        if flag & bit
    ]


def displayed(config, flags, order):
    """The names as the user reads them down the list: filtered, then reordered."""
    bit = FilterStub.bitflag_filter_item
    visible = [i for i, flag in enumerate(flags) if flag & bit]
    if not order:
        return [assignment.display_name(config.meshes[i]) for i in visible]
    # `order` maps original index -> new position, so sorting the visible rows
    # BY that value walks the list top to bottom. Written as the inverse of what
    # the panel builds, on purpose: if both directions agreed by accident the
    # test would prove nothing.
    return [
        assignment.display_name(config.meshes[i])
        for i in sorted(visible, key=lambda i: order[i])
    ]


def deselect_all():
    for obj in bpy.context.scene.objects:
        obj.select_set(False)


#: name -> the Object datablock. Held here rather than reached through
#: ``config.meshes[i].obj`` because an Object is an ID and stays valid, where a
#: PropertyGroup reference does not - see ``entry_for``.
OBJECTS = {}


def new_mesh_object(name):
    obj = bpy.data.objects.new(name, bpy.data.meshes.new(name + "_data"))
    bpy.context.scene.collection.objects.link(obj)
    OBJECTS[name] = obj
    return obj


def entry_for(name):
    """The registry row for *name*, looked up fresh every time.

    Never cache one of these. ``CollectionProperty.remove()`` reallocates, so a
    Python reference taken before a removal points into freed memory afterwards
    - which does not raise, it hangs.
    """
    for entry in config.meshes:
        if assignment.display_name(entry) == name:
            return entry
    raise KeyError(name)


lj_trim_master.register()
config = settings.settings(bpy.context)

# ---------------------------------------------------------------------------
# Fixture: four meshes, deliberately NOT in alphabetical order
# ---------------------------------------------------------------------------

NAMES = ["wall_brick", "floor_stone", "wall_wood", "roof_tile"]

for name in NAMES:
    assignment.add_object(config, new_mesh_object(name))

check("the fixture registered four meshes", len(config.meshes) == 4,
      str([assignment.display_name(e) for e in config.meshes]))

# ---------------------------------------------------------------------------
# is_selected
# ---------------------------------------------------------------------------

deselect_all()
check("nothing is selected to start",
      not any(assignment.is_selected(e) for e in config.meshes))

OBJECTS["wall_wood"].select_set(True)
check("selecting an object shows up on its row",
      assignment.is_selected(entry_for("wall_wood")))
check("and on no other row",
      sum(assignment.is_selected(e) for e in config.meshes) == 1)

# The state `object_missing` documents: the X key unlinks, it does not delete.
orphan = new_mesh_object("orphan")
orphan_entry = assignment.add_object(config, orphan)
bpy.context.scene.collection.objects.unlink(orphan)

check("an unlinked object is still pointed at, per object_missing",
      orphan_entry.obj is not None)
check("and asking whether it is selected does not raise",
      assignment.is_selected(orphan_entry) is False)

config.meshes.remove(len(config.meshes) - 1)
bpy.data.objects.remove(orphan, do_unlink=True)

# ---------------------------------------------------------------------------
# Selected-first ordering
# ---------------------------------------------------------------------------

flags, order = run_filter(config)
check("with no search, every row is visible",
      shown(config, flags) == NAMES, str(shown(config, flags)))
check("the selected mesh is floated to the top",
      displayed(config, flags, order)[0] == "wall_wood",
      str(displayed(config, flags, order)))
check("and the rest keep registry order underneath",
      displayed(config, flags, order)
      == ["wall_wood", "wall_brick", "floor_stone", "roof_tile"],
      str(displayed(config, flags, order)))

OBJECTS["roof_tile"].select_set(True)
flags, order = run_filter(config)
check("two selected meshes both float, in registry order",
      displayed(config, flags, order)[:2] == ["wall_wood", "roof_tile"],
      str(displayed(config, flags, order)))

# Everything selected is the same permutation as nothing selected.
for entry in config.meshes:
    entry.obj.select_set(True)
flags, order = run_filter(config)
check("with everything selected the list does not reorder", order == [], str(order))

deselect_all()
OBJECTS["wall_wood"].select_set(True)

# ---------------------------------------------------------------------------
# Search, and its priority over the selected-first sort
# ---------------------------------------------------------------------------

config.mesh_search = "wall"
flags, order = run_filter(config)
check("the search narrows the list to matches",
      shown(config, flags) == ["wall_brick", "wall_wood"], str(shown(config, flags)))
check("a search suppresses the selected-first sort", order == [], str(order))
check("so matches stay in registry order even with one selected",
      displayed(config, flags, order) == ["wall_brick", "wall_wood"],
      str(displayed(config, flags, order)))

config.mesh_search = "WALL"
flags, _order = run_filter(config)
check("the search is case-insensitive",
      shown(config, flags) == ["wall_brick", "wall_wood"], str(shown(config, flags)))

config.mesh_search = "   wall   "
flags, _order = run_filter(config)
check("surrounding whitespace is ignored",
      shown(config, flags) == ["wall_brick", "wall_wood"], str(shown(config, flags)))

config.mesh_search = "no_such_mesh"
flags, order = run_filter(config)
check("a search matching nothing hides everything", shown(config, flags) == [],
      str(shown(config, flags)))

config.mesh_search = "   "
flags, order = run_filter(config)
check("a blank search is not a search - selected-first is back",
      displayed(config, flags, order)[0] == "wall_wood",
      str(displayed(config, flags, order)))

# The funnel's own field must keep working next to the panel's.
config.mesh_search = ""
flags, order = run_filter(config, filter_name="roof")
check("the built-in filter field still filters",
      shown(config, flags) == ["roof_tile"], str(shown(config, flags)))
check("and it suppresses the selected-first sort too", order == [], str(order))

config.mesh_search = "wall"
flags, _order = run_filter(config, filter_name="wood")
check("both search fields apply together, not one or the other",
      shown(config, flags) == ["wall_wood"], str(shown(config, flags)))

config.mesh_search = ""

# ---------------------------------------------------------------------------
# Alphabetical sort, and selected-first layered on top of it
# ---------------------------------------------------------------------------

deselect_all()
flags, order = run_filter(config, sort_alpha=True)
check("the funnel's alphabetical sort is honoured",
      displayed(config, flags, order) == sorted(NAMES),
      str(displayed(config, flags, order)))

OBJECTS["wall_wood"].select_set(True)
flags, order = run_filter(config, sort_alpha=True)
check("a selected mesh still floats above an alphabetical sort",
      displayed(config, flags, order)[0] == "wall_wood",
      str(displayed(config, flags, order)))
check("and the unselected remainder stays alphabetical",
      displayed(config, flags, order)[1:]
      == sorted(n for n in NAMES if n != "wall_wood"),
      str(displayed(config, flags, order)))

# ---------------------------------------------------------------------------
# The active index the slot editor reads
# ---------------------------------------------------------------------------

deselect_all()
OBJECTS["floor_stone"].select_set(True)
bpy.ops.ljtm.add_meshes()
check("re-adding an already-registered mesh adds no row", len(config.meshes) == 4,
      str(len(config.meshes)))

fresh = new_mesh_object("added_last")
deselect_all()
fresh.select_set(True)
bpy.context.view_layer.objects.active = fresh
bpy.ops.ljtm.add_meshes()
check("adding a mesh points the editor at it",
      config.active_mesh == len(config.meshes) - 1
      and assignment.display_name(config.meshes[config.active_mesh]) == "added_last",
      "%d -> %s" % (config.active_mesh,
                    assignment.display_name(config.meshes[config.active_mesh])))

bpy.ops.ljtm.remove_mesh(index=len(config.meshes) - 1)
check("removing the active row leaves the index in range",
      0 <= config.active_mesh < len(config.meshes),
      "%d of %d" % (config.active_mesh, len(config.meshes)))

config.active_mesh = 0
bpy.ops.ljtm.remove_mesh(index=len(config.meshes) - 1)
check("removing a row below the active one leaves it alone",
      config.active_mesh == 0, str(config.active_mesh))

while len(config.meshes):
    bpy.ops.ljtm.remove_mesh(index=len(config.meshes) - 1)
check("emptying the registry clamps the index to zero, not to -1",
      config.active_mesh == 0, str(config.active_mesh))

# ---------------------------------------------------------------------------
# The rule the whole panel is built around
# ---------------------------------------------------------------------------

probe = new_mesh_object("write_probe")
assignment.add_object(config, probe)
probe.select_set(True)

before = (config.active_mesh, config.mesh_search, len(config.meshes),
          sorted(probe.data.keys()))
for kwargs in ({}, {"filter_name": "write"}, {"sort_alpha": True}):
    run_filter(config, **kwargs)
    run_filter(config, **kwargs)
after = (config.active_mesh, config.mesh_search, len(config.meshes),
         sorted(probe.data.keys()))
check("filter_items writes to no ID - it is a draw path", before == after,
      "%s -> %s" % (before, after))

lj_trim_master.unregister()

print()
print("%d/%d checks passed" % (CHECKS[0] - len(FAILURES), CHECKS[0]))
if FAILURES:
    print("failed:")
    for label in FAILURES:
        print("  - " + label)
sys.exit(1 if FAILURES else 0)
