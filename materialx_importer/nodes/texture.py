from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import bpy

from ..blender_nodes import (
    component_socket,
    combine_components,
    connect_or_set_input,
    constant_socket,
    input_socket,
    clamp01_component,
    math_socket,
    mix_component,
    rotate2d_components,
)
from ..document import (
    attribute,
    category,
    connected_node,
    get_input,
    input_value,
    input_value_or_default,
    type_name,
)
from ..types import CompileContext, CompiledSocket
from ..values import component_count, parse_float, resolve_asset_path
from .geometry import blender_world_direction_to_materialx_socket

_MX_NODE_SUPPORT_CACHE: dict[str, bool] = {}
_ADDRESS_MODE_EXTENSIONS = {
    "periodic": "REPEAT",
    "clamp": "EXTEND",
    "constant": "CLIP",
    "mirror": "MIRROR",
}
_ADDRESS_MODES = set(_ADDRESS_MODE_EXTENSIONS)


@dataclass
class ImageTexture:
    node: bpy.types.Node
    constant_mask: bpy.types.NodeSocket | None = None


def register(registry) -> None:
    registry.register_many({"image", "tiledimage"}, compile_image)
    registry.register("hextiledimage", compile_hextiledimage)
    registry.register("hextilednormalmap", compile_hextilednormalmap)
    registry.register("gltf_image", compile_gltf_image)
    registry.register("gltf_colorimage", compile_gltf_colorimage)
    registry.register("gltf_anisotropy_image", compile_gltf_anisotropy_image)
    registry.register("gltf_normalmap", compile_gltf_normalmap)
    registry.register("place2d", compile_place2d)
    registry.register("normalmap", compile_normalmap)
    registry.register("heighttonormal", compile_heighttonormal)
    registry.register("circle", compile_circle)
    registry.register("checkerboard", compile_checkerboard)
    registry.register("bump", compile_bump)


def compile_image(context: CompileContext, image_node: Any, output_name: str, scope: Any | None) -> CompiledSocket | None:
    output_type = type_name(image_node) or "color3"
    image_texture = create_image_texture_node(context, image_node, scope, non_color_default=is_data_image_type(output_type))
    if image_texture is None:
        return None

    compiled = compiled_texture_output(context, image_texture.node, output_type, output_name)
    if compiled is None:
        return None
    return apply_constant_address_default(context, image_node, compiled, output_type, output_name, scope, image_texture.constant_mask)


def compile_gltf_image(context: CompileContext, image_node: Any, output_name: str, scope: Any | None) -> CompiledSocket | None:
    output_type = type_name(image_node) or "color3"
    image = compile_gltf_image_lookup(context, image_node, scope, output_type)
    if image is None:
        return None

    if get_input(image_node, "factor") is not None:
        factor = input_socket(context, image_node, "factor", default_factor_value(output_type), scope)
        image = multiply_compiled_components(context, image, factor, output_type)

    return select_gltf_image_output(context, image, output_type, output_name)


def compile_gltf_colorimage(
    context: CompileContext,
    image_node: Any,
    output_name: str,
    scope: Any | None,
) -> CompiledSocket | None:
    image = compile_gltf_image_lookup(context, image_node, scope, "color4")
    if image is None:
        return None

    color = input_socket(context, image_node, "color", (1.0, 1.0, 1.0, 1.0), scope)
    geomcolor = input_socket(context, image_node, "geomcolor", (1.0, 1.0, 1.0, 1.0), scope)
    image = multiply_compiled_components(context, image, color, "color4")
    image = multiply_compiled_components(context, image, geomcolor, "color4")

    if output_name in {"outa", "a", "alpha"}:
        return CompiledSocket(component_socket(context, image, 3), "float")
    return combine_components(context, [component_socket(context, image, index) for index in range(3)], "color3")


def compile_gltf_anisotropy_image(
    context: CompileContext,
    image_node: Any,
    output_name: str,
    scope: Any | None,
) -> CompiledSocket | None:
    image = compile_gltf_image_lookup(context, image_node, scope, "vector3")
    if image is None:
        return None

    x = math_socket(
        context,
        "SUBTRACT",
        math_socket(
            context,
            "MULTIPLY",
            component_socket(context, image, 0),
            constant_socket(context, 2.0, "float").socket,
        ),
        constant_socket(context, 1.0, "float").socket,
    )
    y = math_socket(
        context,
        "SUBTRACT",
        math_socket(
            context,
            "MULTIPLY",
            component_socket(context, image, 1),
            constant_socket(context, 2.0, "float").socket,
        ),
        constant_socket(context, 1.0, "float").socket,
    )
    strength = math_socket(
        context,
        "MULTIPLY",
        input_socket(context, image_node, "anisotropy_strength", 1.0, scope).socket,
        component_socket(context, image, 2),
    )
    rotation = math_socket(
        context,
        "ADD",
        input_socket(context, image_node, "anisotropy_rotation", 0.0, scope).socket,
        math_socket(context, "ARCTAN2", y, x),
    )

    if output_name == "anisotropy_rotation_out":
        return CompiledSocket(rotation, "float")
    return CompiledSocket(strength, "float")


def compile_gltf_image_lookup(
    context: CompileContext,
    image_node: Any,
    scope: Any | None,
    output_type: str,
) -> CompiledSocket | None:
    image_texture = create_image_texture_node(
        context,
        image_node,
        scope,
        non_color_default=is_data_image_type(output_type),
        texcoord_override=gltf_image_texcoord_socket(context, image_node, scope),
    )
    if image_texture is None:
        return None
    compiled = texture_output_as_compiled(context, image_texture.node, output_type)
    if compiled is None:
        return None
    return apply_constant_address_default(context, image_node, compiled, output_type, "out", scope, image_texture.constant_mask)


def texture_output_as_compiled(
    context: CompileContext,
    texture_node: bpy.types.Node,
    output_type: str,
) -> CompiledSocket | None:
    color_socket = texture_node.outputs.get("Color")
    if color_socket is None:
        return None
    if output_type in {"color4", "vector4"}:
        alpha = texture_node.outputs.get("Alpha")
        components = [component_socket(context, CompiledSocket(color_socket, "color3"), index) for index in range(3)]
        components.append(alpha if alpha is not None else constant_socket(context, 1.0, "float").socket)
        return combine_components(context, components, output_type)
    if output_type == "float":
        return CompiledSocket(component_socket(context, CompiledSocket(color_socket, "color3"), 0), "float")
    return CompiledSocket(color_socket, output_type)


def default_factor_value(output_type: str) -> float | tuple[float, ...]:
    if output_type in {"color4", "vector4"}:
        return (1.0, 1.0, 1.0, 1.0)
    if output_type in {"color3", "vector3"}:
        return (1.0, 1.0, 1.0)
    return 1.0


def multiply_compiled_components(
    context: CompileContext,
    left: CompiledSocket,
    right: CompiledSocket,
    output_type: str,
) -> CompiledSocket:
    return combine_components(
        context,
        [
            math_socket(
                context,
                "MULTIPLY",
                component_socket(context, left, index),
                component_socket(context, right, index),
            )
            for index in range(component_count(output_type))
        ],
        output_type,
    )


def select_gltf_image_output(
    context: CompileContext,
    image: CompiledSocket,
    output_type: str,
    output_name: str,
) -> CompiledSocket:
    if output_name in {"outa", "a", "alpha"}:
        return CompiledSocket(component_socket(context, image, 3), "float")
    if output_type == "float":
        return CompiledSocket(component_socket(context, image, 0), "float")
    return image


def compile_hextiledimage(context: CompileContext, image_node: Any, output_name: str, scope: Any | None) -> CompiledSocket | None:
    output_type = type_name(image_node) or "color3"
    texture_node = create_hextiled_image_node(context, image_node, scope, non_color_default=is_data_image_type(output_type))
    if texture_node is None:
        return compile_image(context, image_node, output_name, scope)
    return compiled_texture_output(context, texture_node, output_type, output_name)


def compile_hextilednormalmap(
    context: CompileContext,
    image_node: Any,
    output_name: str,
    scope: Any | None,
) -> CompiledSocket | None:
    texture_node = create_hextiled_image_node(context, image_node, scope, non_color_default=True)
    if texture_node is None:
        return compile_gltf_normalmap(context, image_node, output_name, scope)

    color_socket = texture_node.outputs.get("Color")
    if color_socket is None:
        return None
    normal_map = context.material.node_tree.nodes.new(type="ShaderNodeNormalMap")
    context.material.node_tree.links.new(color_socket, normal_map.inputs["Color"])
    connect_or_set_input(context, image_node, "strength", normal_map.inputs["Strength"], 1.0, scope)
    socket = normal_map.outputs.get("Normal")
    if socket is None:
        return None
    compiled = blender_world_direction_to_materialx_socket(context, socket)
    compiled.semantic = "normal"
    return compiled


def compiled_texture_output(
    context: CompileContext,
    texture_node: bpy.types.Node,
    output_type: str,
    output_name: str,
) -> CompiledSocket | None:
    if output_name in {"outa", "a", "alpha"}:
        socket = texture_node.outputs.get("Alpha")
        return CompiledSocket(socket, "float") if socket is not None else None
    socket = texture_node.outputs.get("Color")
    if socket is None:
        return None
    if output_type == "float":
        socket = component_socket(context, CompiledSocket(socket, "color3"), 0)
    return CompiledSocket(socket, output_type)


def is_data_image_type(output_type: str) -> bool:
    return output_type not in {"color3", "color4"}


def compile_gltf_normalmap(context: CompileContext, image_node: Any, output_name: str, scope: Any | None) -> CompiledSocket | None:
    image_texture = create_image_texture_node(context, image_node, scope, non_color_default=True)
    if image_texture is None:
        return None

    color = texture_output_as_compiled(context, image_texture.node, "color3")
    if color is None:
        return None
    color = apply_constant_address_default(context, image_node, color, "color3", "out", scope, image_texture.constant_mask)
    normal_map = context.material.node_tree.nodes.new(type="ShaderNodeNormalMap")
    context.material.node_tree.links.new(color.socket, normal_map.inputs["Color"])
    connect_or_set_input(context, image_node, "scale", normal_map.inputs["Strength"], 1.0, scope)
    socket = normal_map.outputs.get("Normal")
    if socket is None:
        return None
    compiled = blender_world_direction_to_materialx_socket(context, socket)
    compiled.semantic = "normal"
    return compiled


def create_image_texture_node(
    context: CompileContext,
    image_node: Any,
    scope: Any | None,
    *,
    non_color_default: bool = False,
    texcoord_override: CompiledSocket | None = None,
) -> ImageTexture | None:
    file_input = get_input(image_node, "file")
    file_value = input_value(file_input) if file_input is not None else None
    if not file_value:
        context.warnings.append(f"Image node {image_node.getName()} has no file input.")
        return None

    image_path = resolve_asset_path(context.base_dir, str(file_value))
    if not image_path.exists():
        context.warnings.append(f"Image file not found: {image_path}")
        return None

    try:
        image = bpy.data.images.load(str(image_path), check_existing=True)
    except RuntimeError as exc:
        context.warnings.append(f"Failed to load image: {exc}")
        return None

    texture_node = context.material.node_tree.nodes.new(type="ShaderNodeTexImage")
    texture_node.image = image
    texture_node.label = f"MaterialX {image_node.getName()}"
    configure_image_colorspace(texture_node, image_node, non_color_default)
    configure_image_sampling(texture_node, image_node, set_extension=False)

    texcoord = texcoord_override or image_texcoord_socket(context, image_node, scope)
    if category(image_node) == "tiledimage":
        texcoord = compile_tiledimage_texcoord(context, image_node, texcoord, scope)
    texcoord, constant_mask = address_image_texcoord(context, image_node, texcoord)
    vector_input = texture_node.inputs.get("Vector")
    if vector_input is not None:
        context.material.node_tree.links.new(texcoord.socket, vector_input)
    texture_node.extension = "EXTEND"

    return ImageTexture(texture_node, constant_mask)


def create_hextiled_image_node(
    context: CompileContext,
    image_node: Any,
    scope: Any | None,
    *,
    non_color_default: bool = False,
) -> bpy.types.Node | None:
    texture_node = create_mx_node(context, "ShaderNodeMxHextiledImage")
    if texture_node is None:
        if "hextiledimage" not in context.fallback_warnings:
            context.fallback_warnings.add("hextiledimage")
            context.warnings.append(
                "MaterialX hextile image nodes are using plain image fallback; "
                "use a Blender build with ShaderNodeMxHextiledImage for parity."
            )
        return None

    image = load_image(context, image_node)
    if image is None:
        return None

    texture_node.image = image
    texture_node.label = f"MaterialX {image_node.getName()}"
    configure_image_colorspace(texture_node, image_node, non_color_default)
    configure_image_sampling(texture_node, image_node)

    texcoord = image_texcoord_socket(context, image_node, scope)
    vector_input = texture_node.inputs.get("Vector")
    if vector_input is not None:
        context.material.node_tree.links.new(texcoord.socket, vector_input)

    connect_or_set_input(context, image_node, "tiling", texture_node.inputs["Tiling"], (1.0, 1.0), scope)
    connect_or_set_input(context, image_node, "rotation", texture_node.inputs["Rotation"], 1.0, scope)
    connect_or_set_input(
        context, image_node, "rotationrange", texture_node.inputs["Rotation Range"], (0.0, 360.0), scope
    )
    connect_or_set_input(context, image_node, "scale", texture_node.inputs["Scale"], 1.0, scope)
    connect_or_set_input(context, image_node, "scalerange", texture_node.inputs["Scale Range"], (0.5, 2.0), scope)
    connect_or_set_input(context, image_node, "offset", texture_node.inputs["Offset"], 1.0, scope)
    connect_or_set_input(context, image_node, "offsetrange", texture_node.inputs["Offset Range"], (0.0, 1.0), scope)
    connect_or_set_input(context, image_node, "falloff", texture_node.inputs["Falloff"], 0.5, scope)
    connect_or_set_input(context, image_node, "falloffcontrast", texture_node.inputs["Falloff Contrast"], 0.5, scope)
    connect_or_set_input(
        context,
        image_node,
        "lumacoeffs",
        texture_node.inputs["Luma Coeffs"],
        (0.2722287, 0.6740818, 0.0536895),
        scope,
    )

    return texture_node


def load_image(context: CompileContext, image_node: Any) -> bpy.types.Image | None:
    file_input = get_input(image_node, "file")
    file_value = input_value(file_input) if file_input is not None else None
    if not file_value:
        context.warnings.append(f"Image node {image_node.getName()} has no file input.")
        return None

    image_path = resolve_asset_path(context.base_dir, str(file_value))
    if not image_path.exists():
        context.warnings.append(f"Image file not found: {image_path}")
        return None

    try:
        return bpy.data.images.load(str(image_path), check_existing=True)
    except RuntimeError as exc:
        context.warnings.append(f"Failed to load image: {exc}")
        return None


def create_mx_node(context: CompileContext, node_type: str) -> bpy.types.Node | None:
    if not has_mx_node(context, node_type):
        return None
    return context.material.node_tree.nodes.new(type=node_type)


def has_mx_node(context: CompileContext, node_type: str) -> bool:
    cached = _MX_NODE_SUPPORT_CACHE.get(node_type)
    if cached is not None:
        return cached
    nodes = context.material.node_tree.nodes
    try:
        probe = nodes.new(type=node_type)
    except Exception:
        _MX_NODE_SUPPORT_CACHE[node_type] = False
        return False
    nodes.remove(probe)
    _MX_NODE_SUPPORT_CACHE[node_type] = True
    return True


def configure_image_colorspace(texture_node: bpy.types.Node, image_node: Any, non_color_default: bool) -> None:
    image = texture_node.image
    if image is None:
        return

    file_input = get_input(image_node, "file")
    color_space = (attribute(file_input, "colorspace") or "").lower()
    if non_color_default and not color_space:
        set_image_colorspace(image, ("Non-Color", "Non-Color Data"))


def configure_image_sampling(texture_node: bpy.types.Node, image_node: Any, *, set_extension: bool = True) -> None:
    filter_input = get_input(image_node, "filtertype")
    filter_value = (input_value(filter_input) or "").lower()
    if filter_value == "closest":
        texture_node.interpolation = "Closest"
    elif filter_value == "cubic":
        texture_node.interpolation = "Cubic"

    if not set_extension:
        return

    u_mode = (input_value(get_input(image_node, "uaddressmode")) or "periodic").lower()
    v_mode = (input_value(get_input(image_node, "vaddressmode")) or "periodic").lower()
    if u_mode != v_mode:
        return
    extension = _ADDRESS_MODE_EXTENSIONS.get(u_mode)
    if extension is not None:
        texture_node.extension = extension


def address_image_texcoord(
    context: CompileContext,
    image_node: Any,
    texcoord: CompiledSocket,
) -> tuple[CompiledSocket, bpy.types.NodeSocket | None]:
    modes = (
        image_address_mode(context, image_node, "uaddressmode"),
        image_address_mode(context, image_node, "vaddressmode"),
    )
    adjusted_components = []
    constant_masks = []

    for index, mode in enumerate(modes):
        coord = component_socket(context, texcoord, index)
        if mode == "periodic":
            adjusted = periodic_address_socket(context, coord)
        elif mode == "mirror":
            adjusted = mirror_address_socket(context, coord)
        else:
            adjusted = clamp01_component(context, coord)

        adjusted_components.append(adjusted)
        if mode == "constant":
            constant_masks.append(outside_unit_interval_socket(context, coord))

    mask = None
    for constant_mask in constant_masks:
        mask = constant_mask if mask is None else math_socket(context, "MAXIMUM", mask, constant_mask)

    return combine_components(context, adjusted_components, "vector2"), mask


def image_address_mode(context: CompileContext, image_node: Any, input_name: str) -> str:
    raw_value = input_value(get_input(image_node, input_name))
    if raw_value is None or raw_value == "":
        return "periodic"

    mode = str(raw_value).strip().lower()
    if mode in _ADDRESS_MODES:
        return mode

    context.warnings.append(
        f"Image node {image_node.getName()} has unsupported {input_name} '{raw_value}'; using periodic."
    )
    return "periodic"


def periodic_address_socket(context: CompileContext, coord: bpy.types.NodeSocket) -> bpy.types.NodeSocket:
    floored = math_socket(context, "FLOOR", coord, None)
    return math_socket(context, "SUBTRACT", coord, floored)


def mirror_address_socket(context: CompileContext, coord: bpy.types.NodeSocket) -> bpy.types.NodeSocket:
    half_coord = math_socket(context, "DIVIDE", coord, constant_socket(context, 2.0, "float").socket)
    wrapped = math_socket(
        context,
        "SUBTRACT",
        coord,
        math_socket(
            context,
            "MULTIPLY",
            constant_socket(context, 2.0, "float").socket,
            math_socket(context, "FLOOR", half_coord, None),
        ),
    )
    distance_from_center = math_socket(
        context,
        "ABSOLUTE",
        math_socket(context, "SUBTRACT", wrapped, constant_socket(context, 1.0, "float").socket),
        None,
    )
    return math_socket(context, "SUBTRACT", constant_socket(context, 1.0, "float").socket, distance_from_center)


def outside_unit_interval_socket(context: CompileContext, coord: bpy.types.NodeSocket) -> bpy.types.NodeSocket:
    below = math_socket(context, "LESS_THAN", coord, constant_socket(context, 0.0, "float").socket)
    above = math_socket(context, "LESS_THAN", constant_socket(context, 1.0, "float").socket, coord)
    return math_socket(context, "MAXIMUM", below, above)


def apply_constant_address_default(
    context: CompileContext,
    image_node: Any,
    sampled: CompiledSocket,
    output_type: str,
    output_name: str,
    scope: Any | None,
    constant_mask: bpy.types.NodeSocket | None,
) -> CompiledSocket:
    if constant_mask is None:
        return sampled

    default_value = image_default_compiled(context, image_node, output_type, output_name, scope)
    if component_count(sampled.type_name) == 1:
        return CompiledSocket(
            mix_component(context, sampled.socket, component_socket(context, default_value, 0), constant_mask),
            sampled.type_name,
        )

    components = [
        mix_component(
            context,
            component_socket(context, sampled, index),
            component_socket(context, default_value, index),
            constant_mask,
        )
        for index in range(component_count(sampled.type_name))
    ]
    return combine_components(context, components, sampled.type_name)


def image_default_compiled(
    context: CompileContext,
    image_node: Any,
    output_type: str,
    output_name: str,
    scope: Any | None,
) -> CompiledSocket:
    if output_name in {"outa", "a", "alpha"}:
        if output_type in {"color4", "vector4"}:
            default_value = input_socket(context, image_node, "default", default_value_for_image_type(output_type), scope)
            return CompiledSocket(component_socket(context, default_value, 3), "float")
        return constant_socket(context, 1.0, "float")

    default_value = input_socket(context, image_node, "default", default_value_for_image_type(output_type), scope)
    if output_type == "float":
        return CompiledSocket(component_socket(context, default_value, 0), "float")
    return default_value


def default_value_for_image_type(output_type: str) -> float | tuple[float, ...]:
    if output_type in {"color4", "vector4"}:
        return (0.0, 0.0, 0.0, 0.0)
    if output_type in {"color3", "vector3"}:
        return (0.0, 0.0, 0.0)
    if output_type == "vector2":
        return (0.0, 0.0)
    return 0.0


def set_image_colorspace(image: bpy.types.Image, names: tuple[str, ...]) -> None:
    for name in names:
        try:
            image.colorspace_settings.name = name
            return
        except Exception:
            continue


def image_texcoord_socket(context: CompileContext, image_node: Any, scope: Any | None) -> CompiledSocket:
    texcoord_input = get_input(image_node, "texcoord")
    if texcoord_input is not None and context.compiler is not None:
        compiled = context.compiler.compile_input(texcoord_input, scope)
        if compiled is not None:
            return compiled
    fallback = context.compiler.compile_geometry("texcoord") if context.compiler is not None else None
    if fallback is not None:
        return fallback
    return constant_socket(context, (0.0, 0.0), "vector2")


def compile_tiledimage_texcoord(
    context: CompileContext,
    image_node: Any,
    texcoord: CompiledSocket,
    scope: Any | None,
) -> CompiledSocket:
    uvtiling = input_socket(context, image_node, "uvtiling", (1.0, 1.0), scope)
    uvoffset = input_socket(context, image_node, "uvoffset", (0.0, 0.0), scope)
    realworld_image_size = input_socket(context, image_node, "realworldimagesize", (1.0, 1.0), scope)
    realworld_tile_size = input_socket(context, image_node, "realworldtilesize", (1.0, 1.0), scope)
    components = []
    for index in range(2):
        tiled = math_socket(
            context,
            "MULTIPLY",
            component_socket(context, texcoord, index),
            component_socket(context, uvtiling, index),
        )
        offset = math_socket(context, "SUBTRACT", tiled, component_socket(context, uvoffset, index))
        realworld_ratio = math_socket(
            context,
            "DIVIDE",
            component_socket(context, realworld_tile_size, index),
            component_socket(context, realworld_image_size, index),
        )
        components.append(math_socket(context, "MULTIPLY", offset, realworld_ratio))
    return combine_components(context, components, "vector2")


def compile_place2d(context: CompileContext, node: Any, output_name: str, scope: Any | None) -> CompiledSocket | None:
    texcoord = input_socket(context, node, "texcoord", (0.0, 0.0), scope)
    pivot = input_socket(context, node, "pivot", (0.0, 0.0), scope)
    scale = input_socket(context, node, "scale", (1.0, 1.0), scope)
    rotate = input_socket(context, node, "rotate", 0.0, scope)
    offset = input_socket(context, node, "offset", (0.0, 0.0), scope)
    return place2d_transform(context, texcoord, pivot, scale, rotate, offset, operation_order(context, node, scope, 0))


def gltf_image_texcoord_socket(context: CompileContext, image_node: Any, scope: Any | None) -> CompiledSocket:
    texcoord = image_texcoord_socket(context, image_node, scope)
    pivot = input_socket(context, image_node, "pivot", (0.0, 1.0), scope)
    scale = input_socket(context, image_node, "scale", (1.0, 1.0), scope)
    rotate = input_socket(context, image_node, "rotate", 0.0, scope)
    offset = input_socket(context, image_node, "offset", (0.0, 0.0), scope)

    inverse_scale_components = [
        math_socket(
            context,
            "DIVIDE",
            constant_socket(context, 1.0, "float").socket,
            component_socket(context, scale, index),
        )
        for index in range(2)
    ]
    inverse_scale = combine_components(context, inverse_scale_components, "vector2")
    negative_rotate = CompiledSocket(
        math_socket(context, "MULTIPLY", rotate.socket, constant_socket(context, -1.0, "float").socket),
        "float",
    )
    negative_offset = combine_components(
        context,
        [
            math_socket(
                context,
                "MULTIPLY",
                component_socket(context, offset, 0),
                constant_socket(context, -1.0, "float").socket,
            ),
            component_socket(context, offset, 1),
        ],
        "vector2",
    )
    return place2d_transform(
        context,
        texcoord,
        pivot,
        inverse_scale,
        negative_rotate,
        negative_offset,
        operation_order(context, image_node, scope, 0),
    )


def place2d_transform(
    context: CompileContext,
    texcoord: CompiledSocket,
    pivot: CompiledSocket,
    scale: CompiledSocket,
    rotate: CompiledSocket,
    offset: CompiledSocket,
    order_value: int,
) -> CompiledSocket:
    centered = [
        math_socket(
            context,
            "SUBTRACT",
            component_socket(context, texcoord, index),
            component_socket(context, pivot, index),
        )
        for index in range(2)
    ]

    if order_value:
        shifted = [
            math_socket(context, "SUBTRACT", centered[index], component_socket(context, offset, index))
            for index in range(2)
        ]
        rotated = rotate2d_components(context, shifted, rotate)
        transformed = [
            math_socket(context, "DIVIDE", rotated[index], component_socket(context, scale, index))
            for index in range(2)
        ]
    else:
        scaled = [
            math_socket(context, "DIVIDE", centered[index], component_socket(context, scale, index))
            for index in range(2)
        ]
        rotated = rotate2d_components(context, scaled, rotate)
        transformed = [
            math_socket(context, "SUBTRACT", rotated[index], component_socket(context, offset, index))
            for index in range(2)
        ]

    result = [
        math_socket(context, "ADD", transformed[index], component_socket(context, pivot, index))
        for index in range(2)
    ]
    return combine_components(context, result, "vector2")


def operation_order(context: CompileContext, node: Any, scope: Any | None, default: int) -> int:
    input_element = get_input(node, "operationorder")
    value = input_value(input_element)
    if value is None and input_element is not None:
        connected = connected_node(context.document, input_element, scope=scope)
        if connected is not None and category(connected) == "constant":
            value = input_value(get_input(connected, "value"))
    if value is None:
        value = input_value_or_default(node, "operationorder")
    if value is None:
        return default
    return int(parse_float(value))


def compile_normalmap(context: CompileContext, node: Any, output_name: str, scope: Any | None) -> CompiledSocket | None:
    source = input_socket(context, node, "in", (0.5, 0.5, 1.0), scope)
    if source.semantic == "normal":
        return source

    normal_map = context.material.node_tree.nodes.new(type="ShaderNodeNormalMap")
    context.material.node_tree.links.new(source.socket, normal_map.inputs["Color"])
    connect_or_set_input(context, node, "scale", normal_map.inputs["Strength"], 1.0, scope)
    socket = normal_map.outputs.get("Normal")
    if socket is None:
        return None
    compiled = blender_world_direction_to_materialx_socket(context, socket)
    compiled.semantic = "normal"
    return compiled


def compile_heighttonormal(context: CompileContext, node: Any, output_name: str, scope: Any | None) -> CompiledSocket | None:
    bump = context.material.node_tree.nodes.new(type="ShaderNodeBump")
    connect_or_set_input(context, node, "in", bump.inputs["Height"], 0.0, scope)
    connect_or_set_input(context, node, "scale", bump.inputs["Strength"], 1.0, scope)
    socket = bump.outputs.get("Normal")
    if socket is None:
        return None
    compiled = blender_world_direction_to_materialx_socket(context, socket)
    compiled.semantic = "normal"
    return compiled


def compile_circle(context: CompileContext, node: Any, output_name: str, scope: Any | None) -> CompiledSocket | None:
    texcoord = image_texcoord_socket(context, node, scope)
    center = input_socket(context, node, "center", (0.0, 0.0), scope)
    radius = input_socket(context, node, "radius", 0.5, scope)
    delta = [
        math_socket(
            context,
            "SUBTRACT",
            component_socket(context, texcoord, index),
            component_socket(context, center, index),
        )
        for index in range(2)
    ]
    dist_square = math_socket(
        context,
        "ADD",
        math_socket(context, "MULTIPLY", delta[0], delta[0]),
        math_socket(context, "MULTIPLY", delta[1], delta[1]),
    )
    radius_square = math_socket(context, "MULTIPLY", radius.socket, radius.socket)
    outside = math_socket(context, "LESS_THAN", radius_square, dist_square)
    inside = math_socket(context, "SUBTRACT", constant_socket(context, 1.0, "float").socket, outside)
    return CompiledSocket(inside, "float")


def compile_checkerboard(context: CompileContext, node: Any, output_name: str, scope: Any | None) -> CompiledSocket | None:
    texcoord = image_texcoord_socket(context, node, scope)
    uvtiling = input_socket(context, node, "uvtiling", (8.0, 8.0), scope)
    uvoffset = input_socket(context, node, "uvoffset", (0.0, 0.0), scope)
    color1 = input_socket(context, node, "color1", (1.0, 1.0, 1.0), scope)
    color2 = input_socket(context, node, "color2", (0.0, 0.0, 0.0), scope)

    tiled_components = []
    for index in range(2):
        tiled = math_socket(
            context,
            "MULTIPLY",
            component_socket(context, texcoord, index),
            component_socket(context, uvtiling, index),
        )
        shifted = math_socket(context, "SUBTRACT", tiled, component_socket(context, uvoffset, index))
        tiled_components.append(math_socket(context, "FLOOR", shifted, None))

    checker_index = math_socket(context, "ADD", tiled_components[0], tiled_components[1])
    mix_factor = math_socket(context, "MODULO", checker_index, constant_socket(context, 2.0, "float").socket)
    output_type = type_name(node) or "color3"
    components = []
    for index in range(3):
        one_minus_mix = math_socket(context, "SUBTRACT", constant_socket(context, 1.0, "float").socket, mix_factor)
        color2_part = math_socket(context, "MULTIPLY", component_socket(context, color2, index), one_minus_mix)
        color1_part = math_socket(context, "MULTIPLY", component_socket(context, color1, index), mix_factor)
        components.append(math_socket(context, "ADD", color2_part, color1_part))
    return combine_components(context, components, output_type)


def compile_bump(context: CompileContext, node: Any, output_name: str, scope: Any | None) -> CompiledSocket | None:
    bump = context.material.node_tree.nodes.new(type="ShaderNodeBump")
    connect_or_set_input(context, node, "height", bump.inputs["Height"], 0.0, scope)
    connect_or_set_input(context, node, "scale", bump.inputs["Strength"], 1.0, scope)
    normal_input = bump.inputs.get("Normal")
    if normal_input is not None:
        connect_or_set_input(context, node, "normal", normal_input, (0.0, 0.0, 1.0), scope)
    socket = bump.outputs.get("Normal")
    if socket is None:
        return None
    compiled = blender_world_direction_to_materialx_socket(context, socket)
    compiled.semantic = "normal"
    return compiled
