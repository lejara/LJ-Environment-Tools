"""Surface-property graph. Sources are read-only; only generated nodes are edited."""
import bpy
from . import normalized


def validate(material):
    if not material.use_nodes:
        raise ValueError(material.name + ': enable nodes and use a Principled BSDF')
    outputs = [n for n in material.node_tree.nodes if n.type == 'OUTPUT_MATERIAL' and n.is_active_output]
    if not outputs or not outputs[0].inputs['Surface'].is_linked:
        raise ValueError(material.name + ': no active surface output')
    shader = outputs[0].inputs['Surface'].links[0].from_node
    if shader.type != 'BSDF_PRINCIPLED':
        raise ValueError(material.name + ': only a direct Principled BSDF is supported')
    for name in ('Alpha', 'Transmission Weight', 'Coat Weight', 'Subsurface Weight'):
        s = shader.inputs[name]
        expected = 1 if name == 'Alpha' else 0
        if s.is_linked or abs(s.default_value - expected) > 1e-6:
            raise ValueError(material.name + ': unsupported ' + name)
    if shader.inputs['Emission Strength'].is_linked or (shader.inputs['Emission Strength'].default_value != 0 and (shader.inputs['Emission Color'].is_linked or any(shader.inputs['Emission Color'].default_value[:3]))):
        raise ValueError(material.name + ': emission is outside the supported scope')
    for name in ('Base Color', 'Roughness', 'Metallic', 'Normal'):
        socket = shader.inputs[name]
        if not socket.is_linked:
            continue
        node = socket.links[0].from_node
        if name == 'Normal':
            if node.type != 'NORMAL_MAP' or node.space != 'TANGENT' or node.inputs['Strength'].is_linked:
                raise ValueError(material.name + ': normal must be a tangent-space Normal Map')
            if not node.inputs['Color'].is_linked:
                raise ValueError(material.name + ': normal map needs an image')
            node = node.inputs['Color'].links[0].from_node
        if node.type != 'TEX_IMAGE' or not node.image or node.projection != 'FLAT':
            raise ValueError(material.name + ': ' + name + ' must use a direct ordinary image texture')
        if node.inputs['Vector'].is_linked and node.inputs['Vector'].links[0].from_node.type not in {'UVMAP', 'TEX_COORD'}:
            raise ValueError(material.name + ': use layer UV controls; procedural/vector mapping is unsupported')
        if node.inputs['Vector'].is_linked:
            link = node.inputs['Vector'].links[0]
            if link.from_node.type == 'TEX_COORD' and link.from_socket.name != 'UV':
                raise ValueError(material.name + ': only UV coordinates are supported')
        if name != 'Base Color' and node.image.colorspace_settings.name not in {'Non-Color', 'Raw'}:
            raise ValueError(material.name + ': set ' + node.image.name + ' to Non-Color data')
    return shader


def signature(material):
    """What build() reads out of a source material.

    Painting changes image *contents*, which Blender reports as a material update even
    though nothing here moved. Comparing this instead of trusting that update keeps a
    stroke from triggering a node-graph rebuild and a shader recompile.
    """
    try:
        shader = validate(material)
    except Exception as exc:
        return ('invalid', str(exc))
    state = []
    for name in ('Base Color', 'Roughness', 'Metallic', 'Normal'):
        socket = shader.inputs[name]
        if not socket.is_linked:
            value = socket.default_value
            state.append((name, tuple(value) if hasattr(value, '__len__') else value))
            continue
        node = socket.links[0].from_node
        strength = None
        if name == 'Normal':
            strength = node.inputs['Strength'].default_value
            node = node.inputs['Color'].links[0].from_node
        vector = node.inputs['Vector'].links[0].from_node.name if node.inputs['Vector'].is_linked else None
        state.append((name, node.image.name, node.interpolation, node.extension, node.projection, vector, strength))
    return tuple(state)


PLACEHOLDERS = (('Base Color', 'LJ Placeholder Color', (.25, .25, .25, 1), 'sRGB'),
                ('Roughness', 'LJ Placeholder Roughness', (.9, .9, .9, 1), 'Non-Color'),
                ('Normal', 'LJ Placeholder Normal', (.5, .5, 1, 1), 'Non-Color'))


def placeholder(name, color, colorspace):
    # One shared swatch per channel for the whole file; users repoint each node at their own map.
    image = bpy.data.images.get(name)
    if image is None:
        image = bpy.data.images.new(name, 8, 8)
        image.generated_color = color
        image.use_fake_user = True
    image.colorspace_settings.name = colorspace
    return image


def starter(name):
    """A source material in exactly the shape validate() accepts, so swapping images is the only step."""
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    tree = material.node_tree
    shader = next(n for n in tree.nodes if n.type == 'BSDF_PRINCIPLED')
    shader.inputs['Metallic'].default_value = 0
    for i, (socket, image_name, color, colorspace) in enumerate(PLACEHOLDERS):
        tex = tree.nodes.new('ShaderNodeTexImage')
        tex.image = placeholder(image_name, color, colorspace)
        tex.label = socket
        tex.location = (-640, 340 - i*330)
        if socket != 'Normal':
            tree.links.new(tex.outputs['Color'], shader.inputs[socket])
            continue
        decode = tree.nodes.new('ShaderNodeNormalMap')
        decode.location = (-320, 340 - i*330)
        tree.links.new(tex.outputs['Color'], decode.inputs['Color'])
        tree.links.new(decode.outputs['Normal'], shader.inputs['Normal'])
    validate(material)
    return material


class Graph:
    def __init__(self, tree):
        self.t = tree
        self.count = 0
    def node(self, kind, name=None):
        n = self.t.nodes.new(kind)
        self.count += 1
        n.location = ((self.count % 12)*200, -(self.count//12)*220)
        if name:
            n.name = n.label = name
        return n
    def put(self, socket, value):
        if isinstance(value, bpy.types.NodeSocket):
            self.t.links.new(value, socket)
        else:
            socket.default_value = value
    def math(self, op, a, b=0):
        n = self.node('ShaderNodeMath')
        n.operation = op
        self.put(n.inputs[0], a)
        self.put(n.inputs[1], b)
        return n.outputs[0]
    def clamp(self, a):
        return self.math('MINIMUM', self.math('MAXIMUM', a, 0), 1)
    def mix(self, a, b, f):
        # Explicit arithmetic preserves Better Lit's extrapolation above one.
        return self.math('ADD', a, self.math('MULTIPLY', self.math('SUBTRACT', b, a), f))
    def vec(self, op, a, b=(0, 0, 0)):
        n = self.node('ShaderNodeVectorMath')
        n.operation = op
        self.put(n.inputs[0], a)
        self.put(n.inputs[1], b)
        return n.outputs[0]
    def scale(self, a, f):
        n = self.node('ShaderNodeVectorMath')
        n.operation = 'SCALE'
        self.put(n.inputs[0], a)
        self.put(n.inputs['Scale'], f)
        return n.outputs[0]
    def vmix(self, a, b, f):
        return self.vec('ADD', a, self.scale(self.vec('SUBTRACT', b, a), f))
    def split(self, a):
        n = self.node('ShaderNodeSeparateXYZ')
        self.put(n.inputs[0], a)
        return tuple(n.outputs)
    def combine(self, x, y, z):
        n = self.node('ShaderNodeCombineXYZ')
        for s, a in zip(n.inputs, (x, y, z)):
            self.put(s, a)
        return n.outputs[0]
    def remap(self, x, limits):
        return self.math('ADD', limits[0], self.math('MULTIPLY', x, limits[1]-limits[0]))
    def image(self, image, uv, source=None):
        n = self.node('ShaderNodeTexImage')
        n.image = image
        if source:
            n.interpolation = source.interpolation
            n.extension = source.extension
        self.put(n.inputs['Vector'], uv)
        return n
    def height(self, h1, h2, weight, contrast):
        inverse = self.math('SUBTRACT', 1, h2)
        minimum = self.math('MINIMUM', h1, inverse)
        delta = self.math('ABSOLUTE', self.math('SUBTRACT', h1, inverse))
        tween = self.clamp(self.math('DIVIDE', self.math('SUBTRACT', weight, minimum), self.math('MAXIMUM', delta, .001)))
        return self.clamp(self.math('DIVIDE', self.math('SUBTRACT', tween, 1-contrast), max(contrast, .001)))


def layer_group(obj, layer, index):
    t = obj.lj_terrain
    key = f'layer_{index}'
    name = t.preview.get(key)
    tree = bpy.data.node_groups.get(name) if name else None
    if tree is None:
        tree = bpy.data.node_groups.new(t.preview.name + f' Layer {index}', 'ShaderNodeTree')
        t.preview[key] = tree.name
    tree.nodes.clear()
    tree.interface.clear()
    for name, kind in [('Color', 'NodeSocketColor'), ('Smooth', 'NodeSocketFloat'), ('Metal', 'NodeSocketFloat'), ('Height', 'NodeSocketFloat'), ('Alpha', 'NodeSocketFloat'), ('Normal', 'NodeSocketVector')]:
        tree.interface.new_socket(name=name, in_out='OUTPUT', socket_type=kind)
    g = Graph(tree)
    output = g.node('NodeGroupOutput')
    uv = g.node('ShaderNodeUVMap')
    uv.uv_map = layer.uv or t.paint_uv
    coord = g.vec('ADD', g.vec('MULTIPLY', uv.outputs[0], (*layer.scale, 1)), (*layer.offset, 0))
    shader = validate(layer.material) if layer.material else None
    alpha = 1
    def input_value(name, fallback):
        nonlocal alpha
        if not shader:
            return fallback
        s = shader.inputs[name]
        if not s.is_linked:
            return tuple(s.default_value) if name == 'Base Color' else s.default_value
        link = s.links[0]
        tex = g.image(link.from_node.image, coord, link.from_node)
        if name == 'Base Color':
            alpha = tex.outputs['Alpha']
        return tex.outputs[link.from_socket.name]
    color = input_value('Base Color', (.25, .25, .25, 1))
    if not isinstance(color, bpy.types.NodeSocket):
        color = color[:3]
    color = g.vec('MULTIPLY', color, tuple(layer.tint))
    smooth = g.remap(g.math('SUBTRACT', 1, input_value('Roughness', .5)), layer.smooth_remap)
    metal = g.remap(input_value('Metallic', 0), layer.metal_remap)
    height = layer.height
    if layer.height_source == 'ALPHA':
        height = alpha
    elif layer.height_source == 'IMAGE':
        if not layer.height_image:
            raise ValueError('Select a height image')
        if layer.height_image.colorspace_settings.name not in {'Non-Color', 'Raw'}:
            raise ValueError('Height image must use Non-Color')
        tex = g.image(layer.height_image, coord)
        height = tex.outputs['Alpha'] if layer.height_channel == 'A' else g.split(tex.outputs['Color'])['RGB'.index(layer.height_channel)]
    height = g.remap(height, layer.height_remap)
    # Decode tangent normals in a common tangent basis, before final Normal Map conversion.
    normal = (0, 0, 1)
    if shader and shader.inputs['Normal'].is_linked:
        source = shader.inputs['Normal'].links[0].from_node
        tex_source = source.inputs['Color'].links[0].from_node
        tex = g.image(tex_source.image, coord, tex_source)
        normal = g.vec('SUBTRACT', g.scale(tex.outputs['Color'], 2), (1, 1, 1))
        x, y, z = g.split(normal)
        s = source.inputs['Strength'].default_value * layer.normal_strength
        normal = g.combine(g.math('MULTIPLY', x, s), g.math('MULTIPLY', y, -s if layer.flip_green else s), z)
    for name, value in [('Color', color), ('Smooth', smooth), ('Metal', metal), ('Height', height), ('Alpha', g.remap(alpha, layer.height_remap)), ('Normal', normal)]:
        g.put(output.inputs[name], value)
    return tree


def build(obj):
    t = obj.lj_terrain
    # Validate before touching an existing preview.
    for layer in t.layers:
        if layer.material:
            if layer.material == t.preview:
                raise ValueError('Generated preview cannot be its own source')
            validate(layer.material)
        if layer.uv and layer.uv not in obj.data.uv_layers:
            raise ValueError('Material UV map does not exist: ' + layer.uv)
        if layer.height_source == 'IMAGE' and (not layer.height_image or layer.height_image.colorspace_settings.name not in {'Non-Color', 'Raw'}):
            raise ValueError('Select a Non-Color height image')
    if not t.preview:
        t.preview = bpy.data.materials.new(obj.name + ' LJ Terrain Preview')
        t.preview.use_nodes = True
    tree = t.preview.node_tree
    tree.nodes.clear()
    g = Graph(tree)
    uv = g.node('ShaderNodeUVMap', 'Paint UV')
    uv.uv_map = t.paint_uv
    mask_uv = g.vec('ADD', g.vec('MULTIPLY', uv.outputs[0], (*t.mask_scale, 1)), (*t.mask_offset, 0))
    # Sample the actual packed image. Normalizing filtered raw masks would disagree
    # with Unity's filtering of already-normalized texels along painted boundaries.
    packed = g.image(t.combined, mask_uv)
    weights = list(g.split(packed.outputs['Color'])) + [packed.outputs['Alpha']]
    toggle = g.node('ShaderNodeValue', 'Normalize RGBA')
    toggle.outputs[0].default_value = float(normalized())
    base = g.node('ShaderNodeGroup', 'Base')
    base.node_tree = layer_group(obj, t.layers[0], 0)
    color, smooth, metal, height, normal = [base.outputs[n] for n in ('Color', 'Smooth', 'Metal', 'Height', 'Normal')]
    for i, layer in enumerate(t.layers[1:]):
        if not layer.material:
            continue
        node = g.node('ShaderNodeGroup', 'RGBA'[i] + ' Overlay')
        node.node_tree = layer_group(obj, layer, i+1)
        weight = weights[i]
        if layer.curve:
            x = g.clamp(g.math('DIVIDE', g.math('SUBTRACT', weight, .5-layer.curve_width), 2*layer.curve_width))
            smoothstep = g.math('MULTIPLY', g.math('MULTIPLY', x, x), g.math('SUBTRACT', 3, g.math('MULTIPLY', 2, x)))
            weight = g.mix(smoothstep, weight, 2*layer.curve_width)
        w = g.math('MULTIPLY', weight, layer.strength)
        if layer.mode == 'ALPHA' and layer.alpha_mask:
            w = g.math('MULTIPLY', w, node.outputs['Alpha'])
        f = g.height(height, node.outputs['Height'], w, layer.contrast) if layer.mode == 'HEIGHT' else w
        target = node.outputs['Color']
        if layer.mode == 'MULTIPLY':
            target = g.scale(g.vec('MULTIPLY', color, target), 2)
        color = g.vmix(color, target, g.math('MULTIPLY', f, layer.albedo_strength))
        if layer.mode != 'MULTIPLY':
            height = g.mix(height, node.outputs['Height'], f)
        surface_factor = g.math('MULTIPLY', w, layer.smooth_strength) if layer.mode == 'MULTIPLY' else f
        # Multiply without a mask texture leaves the shader's scalar constants unchanged.
        source = validate(layer.material)
        if layer.mode != 'MULTIPLY' or source.inputs['Roughness'].is_linked or source.inputs['Metallic'].is_linked:
            smooth = g.mix(smooth, node.outputs['Smooth'], surface_factor)
            metal = g.mix(metal, node.outputs['Metal'], surface_factor)
        if source.inputs['Normal'].is_linked:
            x, y, z = g.split(node.outputs['Normal'])
            dn = g.combine(g.math('MULTIPLY', x, w), g.math('MULTIPLY', y, w), z)
            if layer.mode == 'MULTIPLY':
                bx, by, bz = g.split(normal)
                dx, dy, dz = g.split(dn)
                normal = g.vec('NORMALIZE', g.combine(g.math('ADD', bx, dx), g.math('ADD', by, dy), g.math('MULTIPLY', bz, dz)))
            else:
                normal = g.vmix(normal, dn, f)
    out = g.node('ShaderNodeOutputMaterial', 'Terrain Output')
    shader = g.node('ShaderNodeBsdfPrincipled', 'Terrain Surface')
    g.put(shader.inputs['Base Color'], color)
    g.put(shader.inputs['Roughness'], g.math('SUBTRACT', 1, smooth))
    g.put(shader.inputs['Metallic'], metal)
    nm = g.node('ShaderNodeNormalMap')
    nm.uv_map = t.layers[0].uv or t.paint_uv
    g.put(nm.inputs['Color'], g.scale(g.vec('ADD', normal, (1, 1, 1)), .5))
    g.put(shader.inputs['Normal'], nm.outputs[0])
    if t.display == 'MATERIAL':
        g.put(out.inputs['Surface'], shader.outputs[0])
    else:
        if t.display == 'MASK':
            # Built on demand: a channel with no material has no mask image, and reading
            # every mask here would pin four images the preview never samples.
            entry = t.masks[int(t.active_mask)] if len(t.masks) > int(t.active_mask) else None
            image = entry.image if entry else None
            diagnostic = g.clamp(g.split(g.image(image, mask_uv).outputs['Color'])[0]) if image else (0, 0, 0, 1)
        else:
            diagnostic = {'ALBEDO': color, 'HEIGHT': height, 'SMOOTH': smooth, 'METAL': metal, 'NORMAL': g.scale(g.vec('ADD', normal, (1,1,1)), .5)}[t.display]
        emission = g.node('ShaderNodeEmission', 'Unlit Diagnostic')
        g.put(emission.inputs['Color'], diagnostic)
        g.put(out.inputs['Surface'], emission.outputs[0])
    t.preview_status = 'Preview current'
