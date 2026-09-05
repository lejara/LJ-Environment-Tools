# SPDX-License-Identifier: GPL-3.0-or-later
"""Convenience: build a Principled material from one ``image_dump/`` texture.

**Nothing in this add-on depends on it.** The trim transform never inspects a
material - no texture lookup, no filename inference - so the material a slot
carries may already exist, come from another pipeline, or have no image texture
at all. This module only saves the user a few minutes at the start of a model.

That independence is the point of the "sheet material in Blender: cut" decision:
each downstream integration handles its own materials, and the viewport keeps
showing the individual texture at full resolution while modelling rather than a
small corner of a packed sheet.

The list shows the **normalized asset name**, which is what the tool calls the
asset - ``old-wood_Normal.png`` and ``old_wood-AO.png`` collapse to one asset
``old_wood``. That name may match no file on disk exactly, so the UI must never
present it as a filename.
"""

import os

import bpy
from bpy.props import BoolProperty, StringProperty
from bpy.types import Operator, UIList

from . import project, settings


def load_image(path, non_color=False):
    """Load or reuse an Image datablock for *path*."""
    absolute = os.path.abspath(path)
    for image in bpy.data.images:
        if image.filepath and os.path.abspath(bpy.path.abspath(image.filepath)) == absolute:
            return image
    image = bpy.data.images.load(absolute)
    if non_color:
        try:
            image.colorspace_settings.name = 'Non-Color'
        except TypeError:
            pass
    return image


def _pick(maps, preferred):
    lowered = {key.lower(): value for key, value in maps.items()}
    for name in preferred:
        if name in lowered:
            return lowered[name]
    return None


#: Node labels this module owns. A node carrying one of these is ours to reuse
#: and to delete; every other node in the tree belongs to the user or to another
#: pipeline and is never touched. The material may well pre-date this add-on.
BASE_COLOR_LABEL = "BaseColor"
NORMAL_LABEL = "Normal"
NORMAL_MAP_LABEL = "Normal Map"

#: Where `_claim` parks each node. Also the fingerprint used to recognise the
#: unlabelled Normal Map nodes older versions stacked here.
NORMAL_MAP_LOCATION = (-250, -250)


def _claim(tree, bl_idname, label, location):
    """The one node of ours carrying *label*, created if absent.

    Duplicates are removed. `build_material` used to call ``nodes.new``
    unconditionally, so every press of Create Material dropped a fresh image
    node at the same coordinates as the last, relinked the Principled, and left
    the previous one orphaned underneath - invisible, and growing the file.
    Claiming both prevents that and repairs a material already stacked up.
    """
    ours = [node for node in tree.nodes
            if node.bl_idname == bl_idname and node.label == label]
    for extra in ours[1:]:
        tree.nodes.remove(extra)
    node = ours[0] if ours else tree.nodes.new(bl_idname)
    node.label = label
    node.location = location
    return node


def _claim_normal_map(tree):
    """The Normal Map node, adopting the unlabelled ones older builds stacked.

    Those carry no label, so `_claim` cannot see them. They are recognised by
    sitting at this module's own coordinates with nothing wired out of them -
    a Normal Map node the user placed deliberately is connected to something.
    """
    for node in list(tree.nodes):
        if node.bl_idname != 'ShaderNodeNormalMap' or node.label:
            continue
        if tuple(round(value) for value in node.location) != NORMAL_MAP_LOCATION:
            continue
        if not any(socket.links for socket in node.outputs):
            tree.nodes.remove(node)
    return _claim(tree, 'ShaderNodeNormalMap', NORMAL_MAP_LABEL, NORMAL_MAP_LOCATION)


def _link(tree, output, socket):
    """Wire *output* into *socket*, replacing whatever was there.

    ``links.new`` onto an input that already holds a link can leave two on a
    single-input socket until the next depsgraph update. Clearing first keeps
    the tree honest on the second press as well as the first.
    """
    for link in list(socket.links):
        if link.from_socket == output:
            return link
        tree.links.remove(link)
    return tree.links.new(output, socket)


def build_material(base_name, maps):
    """A Principled material named *base_name*. Returns ``(material, warnings)``.

    BaseColor is wired if a base-colour-ish map exists; Normal is wired through
    a Normal Map node if one exists. A missing map warns and is skipped - per the
    tool's own rule, a missing source never blocks.

    A material of that name is rewired rather than duplicated, so clicking twice
    does not leave ``wood_1.001`` behind - **and** rewires the same nodes rather
    than stacking a fresh set on top of them. Pressing Create Material twice is
    a no-op on the second press.
    """
    warnings = []

    material = bpy.data.materials.get(base_name)
    if material is None:
        material = bpy.data.materials.new(base_name)
    material.use_nodes = True
    tree = material.node_tree

    principled = next((node for node in tree.nodes if node.type == 'BSDF_PRINCIPLED'), None)
    if principled is None:
        principled = tree.nodes.new('ShaderNodeBsdfPrincipled')
        principled.location = (0, 0)
        output = next((n for n in tree.nodes if n.type == 'OUTPUT_MATERIAL'), None)
        if output is None:
            output = tree.nodes.new('ShaderNodeOutputMaterial')
            output.location = (300, 0)
        tree.links.new(principled.outputs['BSDF'], output.inputs['Surface'])

    base_path = _pick(maps, project.BASE_COLOR_MAPS)
    if base_path is None:
        warnings.append("'%s' has no base colour map - left untextured" % base_name)
    else:
        texture = _claim(tree, 'ShaderNodeTexImage', BASE_COLOR_LABEL, (-400, 100))
        texture.image = load_image(base_path)
        _link(tree, texture.outputs['Color'], principled.inputs['Base Color'])

    normal_path = _pick(maps, project.NORMAL_MAPS)
    if normal_path is None:
        # Explicitly a warning, not an error - Draft asks for exactly this.
        warnings.append("'%s' has no normal map - that is fine" % base_name)
    else:
        texture = _claim(tree, 'ShaderNodeTexImage', NORMAL_LABEL, (-600, -250))
        texture.image = load_image(normal_path, non_color=True)
        normal_map = _claim_normal_map(tree)
        _link(tree, texture.outputs['Color'], normal_map.inputs['Color'])
        _link(tree, normal_map.outputs['Normal'], principled.inputs['Normal'])

    return material, warnings


class LJTM_UL_assets(UIList):
    """The scrollable image_dump list.

    A UIList rather than a column of buttons because it is the only widget in
    Blender that actually scrolls - a per-asset button grows without limit and
    would push the Meshes tree off the bottom of a large dump.
    """

    def draw_item(self, _context, layout, _data, item, _icon, _active, _prop):
        row = layout.row(align=True)
        row.label(text=item.name, icon='IMAGE_DATA')
        sub = row.row()
        sub.alignment = 'RIGHT'
        sub.label(text="%d map%s" % (item.map_count, "" if item.map_count == 1 else "s"))


class LJTM_OT_create_material(Operator):
    bl_idname = "ljtm.create_material"
    bl_label = "Create Material"
    bl_description = (
        "Build a Principled material from the selected image_dump asset - base "
        "colour, plus normal if a sibling exists. Purely a convenience: nothing "
        "about trim syncing depends on the material"
    )
    bl_options = {'REGISTER', 'UNDO'}

    #: Resolved by NAME, not by list position, so the two lists cannot drift.
    base_name: StringProperty(default="", options={'SKIP_SAVE'})
    assign_to_active: BoolProperty(
        name="Add To Active Object",
        description="Append the material as a new slot on the active mesh",
        default=True,
        options={'SKIP_SAVE'},
    )

    @classmethod
    def poll(cls, context):
        return bool(settings.project_root(context))

    def execute(self, context):
        maps = None
        for name, found in settings.assets(context):
            if name == self.base_name:
                maps = found
                break
        if maps is None:
            self.report({'ERROR'}, "Pick an image first, or press Refresh")
            return {'CANCELLED'}

        material, warnings = build_material(self.base_name, maps)
        for message in warnings:
            self.report({'WARNING'}, message)

        obj = context.active_object
        if self.assign_to_active and obj is not None and obj.type == 'MESH':
            if material.name not in [m.name for m in obj.data.materials if m]:
                obj.data.materials.append(material)
            self.report({'INFO'}, "'%s' added as slot %d"
                        % (material.name, len(obj.data.materials) - 1))
        else:
            self.report({'INFO'}, "Created material '%s'" % material.name)
        return {'FINISHED'}


classes = (
    LJTM_UL_assets,
    LJTM_OT_create_material,
)
