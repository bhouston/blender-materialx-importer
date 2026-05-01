from __future__ import annotations

from typing import Any

import bpy

from ..blender_nodes import (
    component_socket,
    combine_components,
    connect_or_set_input,
    constant_socket,
    input_socket,
    math_socket,
    rotate2d_components,
)
from ..document import attribute, category, get_input, input_value, type_name
from ..types import CompileContext, CompiledSocket
from ..values import parse_float, resolve_asset_path
from .geometry import blender_world_direction_to_materialx_socket


def register(registry) -> None:
    registry.register_many({"image", "tiledimage"}, compile_image)
    registry.register_many({"gltf_image", "gltf_colorimage"}, compile_gltf_image)
    registry.register("gltf_normalmap", compile_gltf_normalmap)
    registry.register("place2d", compile_place2d)
    registry.register("normalmap", compile_normalmap)
    registry.register("heighttonormal", compile_heighttonormal)
    registry.register("circle", compile_circle)
    registry.register("checkerboard", compile_checkerboard)
    registry.register("bump", compile_bump)


def compile_image(context: CompileContext, image_node: Any, output_name: str, scope: Any | None) -> CompiledSocket | None:
    output_type = type_name(image_node) or "color3"
    texture_node = create_image_texture_node(context, image_node, scope, non_color_default=is_data_image_type(output_type))
    if texture_node is None:
        return None

    return compiled_texture_output(context, texture_node, output_type, output_name)


def compile_gltf_image(context: CompileContext, image_node: Any, output_name: str, scope: Any | None) -> CompiledSocket | None:
    output_type = "color3" if category(image_node) == "gltf_colorimage" else type_name(image_node) or "color3"
    texture_node = create_image_texture_node(
        context,
        image_node,
        scope,
        non_color_default=is_data_image_type(output_type),
    )
    if texture_node is None:
        return None

    return compiled_texture_output(context, texture_node, output_type, output_name)


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
    texture_node = create_image_texture_node(context, image_node, scope, non_color_default=True)
    if texture_node is None:
        return None

    color_socket = texture_node.outputs.get("Color")
    if color_socket is None:
        return None
    normal_map = context.material.node_tree.nodes.new(type="ShaderNodeNormalMap")
    context.material.node_tree.links.new(color_socket, normal_map.inputs["Color"])
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
) -> bpy.types.Node | None:
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
    configure_image_sampling(texture_node, image_node)

    texcoord = image_texcoord_socket(context, image_node, scope)
    if category(image_node) == "tiledimage":
        texcoord = compile_tiledimage_texcoord(context, image_node, texcoord, scope)
    vector_input = texture_node.inputs.get("Vector")
    if vector_input is not None:
        context.material.node_tree.links.new(texcoord.socket, vector_input)

    return texture_node


def configure_image_colorspace(texture_node: bpy.types.Node, image_node: Any, non_color_default: bool) -> None:
    image = texture_node.image
    if image is None:
        return

    file_input = get_input(image_node, "file")
    color_space = (attribute(file_input, "colorspace") or "").lower()
    if non_color_default and not color_space:
        set_image_colorspace(image, ("Non-Color", "Non-Color Data"))


def configure_image_sampling(texture_node: bpy.types.Node, image_node: Any) -> None:
    filter_input = get_input(image_node, "filtertype")
    filter_value = (input_value(filter_input) or "").lower()
    if filter_value == "closest":
        texture_node.interpolation = "Closest"
    elif filter_value == "cubic":
        texture_node.interpolation = "Cubic"

    u_mode = (input_value(get_input(image_node, "uaddressmode")) or "periodic").lower()
    v_mode = (input_value(get_input(image_node, "vaddressmode")) or "periodic").lower()
    if u_mode != v_mode:
        return
    extension_by_mode = {
        "periodic": "REPEAT",
        "clamp": "EXTEND",
        "constant": "CLIP",
        "mirror": "MIRROR",
    }
    extension = extension_by_mode.get(u_mode)
    if extension is not None:
        texture_node.extension = extension


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

    order_input = get_input(node, "operationorder")
    order_value = parse_float(input_value(order_input) or 0.0)
    centered = [
        math_socket(
            context,
            "SUBTRACT",
            component_socket(context, texcoord, index),
            component_socket(context, pivot, index),
        )
        for index in range(2)
    ]

    if abs(order_value) > 0.5:
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
