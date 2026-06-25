import re

from sd.api.sbs.sdsbscompgraph import SDSBSCompGraph
from sd.api.sdproperty import SDPropertyCategory
from sd.api.sdgraphobjectcomment import SDGraphObjectComment
from sd.api.sdgraphobjectframe import SDGraphObjectFrame
from sd.api.sdgraphobjectpin import SDGraphObjectPin

_VER_RE = re.compile(r"^(.*)_ver_(\d+)$")


def next_version_name(current_id, existing_ids):
    m = _VER_RE.match(current_id)
    base = m.group(1) if m else current_id
    n = 1
    while f"{base}_ver_{n}" in existing_ids:
        n += 1
    return f"{base}_ver_{n}"


def _copy_property_values(src_node, dst_node, category):
    for src_prop in src_node.getProperties(category):
        if src_prop.isReadOnly() or src_prop.isFunctionOnly():
            continue
        value = src_node.getPropertyValue(src_prop)
        if value is None:
            continue
        dst_prop = dst_node.getPropertyFromId(src_prop.getId(), category)
        if dst_prop is None or dst_prop.isReadOnly() or dst_prop.isFunctionOnly():
            continue
        try:
            dst_node.setPropertyValue(dst_prop, value)
        except Exception:
            pass


def _duplicate_node(src_node, dst_graph):
    referenced = None
    try:
        referenced = src_node.getReferencedResource()
    except Exception:
        referenced = None

    if referenced is not None:
        new_node = dst_graph.newInstanceNode(referenced)
    else:
        definition = src_node.getDefinition()
        if definition is None:
            return None
        new_node = dst_graph.newNode(definition.getId())

    if new_node is None:
        return None

    try:
        new_node.setPosition(src_node.getPosition())
    except Exception:
        pass

    _copy_property_values(src_node, new_node, SDPropertyCategory.Input)
    _copy_property_values(src_node, new_node, SDPropertyCategory.Annotation)
    return new_node


def _duplicate_connections(src_graph, node_map):
    for src_node in src_graph.getNodes():
        dst_node = node_map.get(src_node.getIdentifier())
        if dst_node is None:
            continue
        for out_prop in src_node.getProperties(SDPropertyCategory.Output):
            for conn in src_node.getPropertyConnections(out_prop):
                in_node = conn.getInputPropertyNode()
                in_prop = conn.getInputProperty()
                if in_node is None or in_prop is None:
                    continue
                dst_in_node = node_map.get(in_node.getIdentifier())
                if dst_in_node is None:
                    continue
                try:
                    dst_node.newPropertyConnectionFromId(
                        out_prop.getId(), dst_in_node, in_prop.getId()
                    )
                except Exception:
                    pass


def _duplicate_graph_objects(src_graph, dst_graph, node_map):
    for obj in src_graph.getGraphObjects():
        new_obj = None
        try:
            if isinstance(obj, SDGraphObjectFrame):
                new_obj = SDGraphObjectFrame.sNew(dst_graph)
                new_obj.setTitle(obj.getTitle())
                new_obj.setColor(obj.getColor())
                new_obj.setSize(obj.getSize())
            elif isinstance(obj, SDGraphObjectComment):
                parent = None
                try:
                    parent = obj.getParent()
                except Exception:
                    parent = None
                if parent is not None:
                    mapped = node_map.get(parent.getIdentifier())
                    if mapped is not None:
                        new_obj = SDGraphObjectComment.sNewAsChild(mapped)
                if new_obj is None:
                    new_obj = SDGraphObjectComment.sNew(dst_graph)
            elif isinstance(obj, SDGraphObjectPin):
                new_obj = SDGraphObjectPin.sNew(dst_graph)
        except Exception:
            new_obj = None

        if new_obj is None:
            continue
        try:
            new_obj.setDescription(obj.getDescription())
        except Exception:
            pass
        try:
            new_obj.setPosition(obj.getPosition())
        except Exception:
            pass


def duplicate_graph(src_graph):
    package = src_graph.getPackage()
    existing_ids = {
        r.getIdentifier() for r in package.getChildrenResources(True)
    }
    new_name = next_version_name(src_graph.getIdentifier(), existing_ids)

    new_graph = SDSBSCompGraph.sNew(package)
    new_graph.setIdentifier(new_name)

    node_map = {}
    for src_node in src_graph.getNodes():
        new_node = _duplicate_node(src_node, new_graph)
        if new_node is not None:
            node_map[src_node.getIdentifier()] = new_node

    _duplicate_connections(src_graph, node_map)
    _duplicate_graph_objects(src_graph, new_graph, node_map)

    for src_out in src_graph.getOutputNodes():
        dst = node_map.get(src_out.getIdentifier())
        if dst is None:
            continue
        try:
            new_graph.setOutputNode(dst, True)
        except Exception:
            pass

    return new_graph, new_name
