from __future__ import annotations

from typing import Any

import bpy

from ..blender_nodes import (
    combine_components,
    component_socket,
    connect_or_set_input,
    constant_socket,
    coordinate_socket,
    input_socket,
    map_range_component,
    math_socket,
    scale_socket,
    texture_output,
    vector_math_output,
)
from ..document import type_name
from ..types import CompileContext, CompiledSocket
from ..values import COMPONENT_TYPES, component_count, static_bool_input, static_int_input

_MX_NODE_SUPPORT_CACHE: dict[str, bool] = {}


def register(registry) -> None:
    registry.register_many({"noise2d", "noise3d", "fractal2d", "fractal3d"}, compile_noise)
    registry.register_many({"cellnoise2d", "cellnoise3d"}, compile_cellnoise)
    registry.register_many({"worleynoise2d", "worleynoise3d", "worley2d", "worley3d"}, compile_worley)
    registry.register_many({"unifiednoise2d", "unifiednoise3d"}, compile_unified_noise)


def compile_noise(context: CompileContext, node: Any, output_name: str, scope: Any | None) -> CompiledSocket | None:
    node_category = node.getCategory()
    is_2d = node_category.endswith("2d")
    is_fractal = node_category.startswith("fractal")
    mx_node_type = f"ShaderNodeMx{'Fractal' if is_fractal else 'Noise'}{'2D' if is_2d else '3D'}"
    mx_output = compile_mx_noise_like(context, node, scope, mx_node_type, is_2d, is_fractal)
    if mx_output is not None:
        return mx_output
    warn_mx_fallback(context, node_category)

    texture = context.material.node_tree.nodes.new(type="ShaderNodeTexNoise")
    texture.label = f"MaterialX {node.getName()}"
    texture.noise_dimensions = "2D" if is_2d else "3D"
    if hasattr(texture, "normalize"):
        texture.normalize = False

    coordinate = coordinate_socket(context, node, "texcoord" if is_2d else "position", is_2d, scope)
    context.material.node_tree.links.new(coordinate.socket, texture.inputs["Vector"])

    if is_fractal:
        connect_or_set_input(context, node, "octaves", texture.inputs["Detail"], 3.0, scope)
        connect_or_set_input(context, node, "diminish", texture.inputs["Roughness"], 0.5, scope)
        if "Lacunarity" in texture.inputs:
            connect_or_set_input(context, node, "lacunarity", texture.inputs["Lacunarity"], 2.0, scope)
    else:
        texture.inputs["Detail"].default_value = 16.0
        texture.inputs["Roughness"].default_value = 0.5

    output_type = type_name(node) or "float"
    source_type = output_type if output_type in COMPONENT_TYPES else "float"
    source = texture_output(texture, "Color" if output_type in COMPONENT_TYPES else "Factor", "Fac")
    if source is None:
        return None
    return scale_noise_output(context, node, CompiledSocket(source, source_type), output_type, scope)


def compile_cellnoise(context: CompileContext, node: Any, output_name: str, scope: Any | None) -> CompiledSocket | None:
    node_category = node.getCategory()
    is_2d = node_category.endswith("2d")
    mx_node_type = f"ShaderNodeMxCellNoise{'2D' if is_2d else '3D'}"
    texture = create_mx_node(context, mx_node_type)
    if texture is not None:
        texture.label = f"MaterialX {node.getName()}"
        coordinate = coordinate_socket(context, node, "texcoord" if is_2d else "position", is_2d, scope)
        context.material.node_tree.links.new(coordinate.socket, texture.inputs["Vector"])
        source = texture.outputs.get("Value")
        return CompiledSocket(source, "float") if source is not None else None
    warn_mx_fallback(context, node_category)

    texture = context.material.node_tree.nodes.new(type="ShaderNodeTexWhiteNoise")
    texture.label = f"MaterialX {node.getName()}"
    texture.noise_dimensions = "2D" if is_2d else "3D"

    coordinate = coordinate_socket(context, node, "texcoord" if is_2d else "position", is_2d, scope)
    context.material.node_tree.links.new(coordinate.socket, texture.inputs["Vector"])

    source = texture.outputs.get("Value")
    return CompiledSocket(source, "float") if source is not None else None


def compile_worley(context: CompileContext, node: Any, output_name: str, scope: Any | None) -> CompiledSocket | None:
    node_category = node.getCategory()
    is_2d = node_category.endswith("2d")
    mx_node_type = f"ShaderNodeMxWorleyNoise{'2D' if is_2d else '3D'}"
    texture = create_mx_node(context, mx_node_type)
    if texture is not None:
        texture.label = f"MaterialX {node.getName()}"
        coordinate = coordinate_socket(context, node, "texcoord" if is_2d else "position", is_2d, scope)
        context.material.node_tree.links.new(coordinate.socket, texture.inputs["Vector"])
        connect_or_set_input(context, node, "jitter", texture.inputs["Jitter"], 1.0, scope)
        connect_or_set_input(context, node, "style", texture.inputs["Style"], 0.0, scope)

        output_type = type_name(node) or "float"
        if output_type in {"vector2", "vector3"}:
            source = texture.outputs.get("Vector")
            return worley_vector_output(context, source, output_type) if source is not None else None
        source = texture.outputs.get("Value")
        return CompiledSocket(source, "float") if source is not None else None
    warn_mx_fallback(context, node_category)

    texture = create_voronoi_texture(context, node, is_2d)
    coordinate = coordinate_socket(context, node, "texcoord" if is_2d else "position", is_2d, scope)
    context.material.node_tree.links.new(coordinate.socket, texture.inputs["Vector"])
    connect_or_set_input(context, node, "jitter", texture.inputs["Randomness"], 1.0, scope)

    output_type = type_name(node) or "float"
    if output_type in COMPONENT_TYPES:
        source = texture.outputs.get("Color")
        return CompiledSocket(source, output_type) if source is not None else None
    if static_int_input(node, "style", 0) == 1:
        color = texture.outputs.get("Color")
        return CompiledSocket(component_socket(context, CompiledSocket(color, "color3"), 0), "float") if color is not None else None
    source = texture.outputs.get("Distance")
    return CompiledSocket(source, "float") if source is not None else None


def worley_vector_output(
    context: CompileContext,
    source: bpy.types.NodeSocket,
    output_type: str,
) -> CompiledSocket:
    if output_type == "vector3":
        return CompiledSocket(source, "vector3")

    vector = CompiledSocket(source, "vector3")
    combine = context.material.node_tree.nodes.new(type="ShaderNodeCombineXYZ")
    context.material.node_tree.links.new(component_socket(context, vector, 0), combine.inputs["X"])
    context.material.node_tree.links.new(component_socket(context, vector, 1), combine.inputs["Y"])
    context.material.node_tree.links.new(constant_socket(context, 0.0, "float").socket, combine.inputs["Z"])
    return CompiledSocket(combine.outputs["Vector"], "vector2")


def compile_unified_noise(context: CompileContext, node: Any, output_name: str, scope: Any | None) -> CompiledSocket | None:
    node_category = node.getCategory()
    is_2d = node_category.endswith("2d")
    mx_node_type = f"ShaderNodeMxUnifiedNoise{'2D' if is_2d else '3D'}"
    texture = create_mx_node(context, mx_node_type)
    if texture is not None:
        texture.label = f"MaterialX {node.getName()}"
        coordinate = coordinate_socket(context, node, "texcoord" if is_2d else "position", is_2d, scope)
        context.material.node_tree.links.new(coordinate.socket, texture.inputs["Vector"])
        connect_or_set_input(context, node, "freq", texture.inputs["Frequency"], (1.0, 1.0, 1.0), scope)
        connect_or_set_input(context, node, "offset", texture.inputs["Offset"], (0.0, 0.0, 0.0), scope)
        connect_or_set_input(context, node, "type", texture.inputs["Type"], 0.0, scope)
        connect_or_set_input(context, node, "jitter", texture.inputs["Jitter"], 1.0, scope)
        connect_or_set_input(context, node, "style", texture.inputs["Style"], 0.0, scope)
        connect_or_set_input(context, node, "octaves", texture.inputs["Octaves"], 3.0, scope)
        connect_or_set_input(context, node, "lacunarity", texture.inputs["Lacunarity"], 2.0, scope)
        connect_or_set_input(context, node, "diminish", texture.inputs["Diminish"], 0.5, scope)
        connect_or_set_input(context, node, "outmin", texture.inputs["Out Min"], 0.0, scope)
        connect_or_set_input(context, node, "outmax", texture.inputs["Out Max"], 1.0, scope)
        connect_or_set_input(
            context,
            node,
            "clampoutput",
            texture.inputs["Clamp Output"],
            1.0,
            scope,
        )
        source = texture.outputs.get("Value")
        return CompiledSocket(source, "float") if source is not None else None
    warn_mx_fallback(context, node_category)

    coordinate = coordinate_socket(context, node, "texcoord" if is_2d else "position", is_2d, scope)
    frequency = input_socket(context, node, "freq", (1.0, 1.0, 1.0), scope)
    offset = input_socket(context, node, "offset", (0.0, 0.0, 0.0), scope)
    scaled = vector_math_output(context, "MULTIPLY", coordinate.socket, frequency.socket)
    positioned = vector_math_output(context, "ADD", scaled, offset.socket)

    noise_type = static_int_input(node, "type", 0)
    if noise_type == 1:
        source = cellnoise_texture_output(context, node, is_2d, positioned)
    elif noise_type == 2:
        source = worley_texture_output(context, node, is_2d, positioned, scope)
    elif noise_type == 3:
        source = noise_texture_output(context, node, is_2d, positioned, scope, fractal=True, amplitude=1.0, pivot=0.0)
    else:
        source = noise_texture_output(context, node, is_2d, positioned, scope, fractal=False, amplitude=0.5, pivot=0.5)

    if source is None:
        return None
    return CompiledSocket(apply_output_range(context, node, source, scope), "float")


def compile_mx_noise_like(
    context: CompileContext,
    node: Any,
    scope: Any | None,
    mx_node_type: str,
    is_2d: bool,
    is_fractal: bool,
) -> CompiledSocket | None:
    texture = create_mx_node(context, mx_node_type)
    if texture is None:
        return None
    texture.label = f"MaterialX {node.getName()}"
    coordinate = coordinate_socket(context, node, "texcoord" if is_2d else "position", is_2d, scope)
    context.material.node_tree.links.new(coordinate.socket, texture.inputs["Vector"])
    if is_fractal:
        connect_or_set_input(context, node, "octaves", texture.inputs["Octaves"], 3.0, scope)
        connect_or_set_input(context, node, "lacunarity", texture.inputs["Lacunarity"], 2.0, scope)
        connect_or_set_input(context, node, "diminish", texture.inputs["Diminish"], 0.5, scope)

    output_type = type_name(node) or "float"
    source_type = output_type if output_type in COMPONENT_TYPES else "float"
    source = texture.outputs.get("Color" if output_type in COMPONENT_TYPES else "Value")
    if source is None:
        return None
    return apply_mx_noise_scaling(context, node, CompiledSocket(source, source_type), output_type, scope, is_fractal)


def apply_mx_noise_scaling(
    context: CompileContext,
    node: Any,
    source: CompiledSocket,
    output_type: str,
    scope: Any | None,
    is_fractal: bool,
) -> CompiledSocket:
    amplitude = input_socket(context, node, "amplitude", 1.0, scope)
    pivot = input_socket(context, node, "pivot", 0.0, scope)
    components: list[bpy.types.NodeSocket] = []
    for index in range(component_count(output_type)):
        scaled = math_socket(
            context,
            "MULTIPLY",
            component_socket(context, source, index),
            component_socket(context, amplitude, index),
        )
        if is_fractal:
            components.append(scaled)
        else:
            components.append(math_socket(context, "ADD", scaled, component_socket(context, pivot, index)))
    return combine_components(context, components, output_type)


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


def warn_mx_fallback(context: CompileContext, category_name: str) -> None:
    if category_name in context.fallback_warnings:
        return
    context.fallback_warnings.add(category_name)
    context.warnings.append(
        f"MaterialX noise node {category_name} is using Blender's approximate native fallback; "
        "use a Blender build with mx-prefixed noise nodes for parity."
    )


def scale_noise_output(
    context: CompileContext,
    node: Any,
    source: CompiledSocket,
    output_type: str,
    scope: Any | None,
) -> CompiledSocket:
    amplitude = input_socket(context, node, "amplitude", 1.0, scope)
    pivot = input_socket(context, node, "pivot", 0.0, scope)
    components: list[bpy.types.NodeSocket] = []
    for index in range(component_count(output_type)):
        source_component = component_socket(context, source, index)
        pivot_component = component_socket(context, pivot, index)
        amplitude_component = component_socket(context, amplitude, index)
        centered = math_socket(context, "SUBTRACT", source_component, pivot_component)
        scaled = math_socket(context, "MULTIPLY", centered, amplitude_component)
        components.append(math_socket(context, "ADD", scaled, pivot_component))
    from ..blender_nodes import combine_components

    return combine_components(context, components, output_type)


def noise_texture_output(
    context: CompileContext,
    node: Any,
    is_2d: bool,
    vector: bpy.types.NodeSocket,
    scope: Any | None,
    fractal: bool,
    amplitude: float,
    pivot: float,
) -> bpy.types.NodeSocket | None:
    texture = context.material.node_tree.nodes.new(type="ShaderNodeTexNoise")
    texture.label = f"MaterialX {node.getName()} Noise"
    texture.noise_dimensions = "2D" if is_2d else "3D"
    if hasattr(texture, "normalize"):
        texture.normalize = False
    context.material.node_tree.links.new(vector, texture.inputs["Vector"])
    if fractal:
        connect_or_set_input(context, node, "octaves", texture.inputs["Detail"], 3.0, scope)
        connect_or_set_input(context, node, "diminish", texture.inputs["Roughness"], 0.5, scope)
        if "Lacunarity" in texture.inputs:
            connect_or_set_input(context, node, "lacunarity", texture.inputs["Lacunarity"], 2.0, scope)
    else:
        texture.inputs["Detail"].default_value = 16.0
        texture.inputs["Roughness"].default_value = 0.5
    source = texture_output(texture, "Factor", "Fac")
    if source is None:
        return None
    return scale_socket(context, source, amplitude, pivot)


def cellnoise_texture_output(
    context: CompileContext,
    node: Any,
    is_2d: bool,
    vector: bpy.types.NodeSocket,
) -> bpy.types.NodeSocket | None:
    texture = context.material.node_tree.nodes.new(type="ShaderNodeTexWhiteNoise")
    texture.label = f"MaterialX {node.getName()} Cell"
    texture.noise_dimensions = "2D" if is_2d else "3D"
    context.material.node_tree.links.new(vector, texture.inputs["Vector"])
    return texture.outputs.get("Value")


def worley_texture_output(
    context: CompileContext,
    node: Any,
    is_2d: bool,
    vector: bpy.types.NodeSocket,
    scope: Any | None,
) -> bpy.types.NodeSocket | None:
    texture = create_voronoi_texture(context, node, is_2d)
    context.material.node_tree.links.new(vector, texture.inputs["Vector"])
    connect_or_set_input(context, node, "jitter", texture.inputs["Randomness"], 1.0, scope)
    if static_int_input(node, "style", 0) == 1:
        color = texture.outputs.get("Color")
        return component_socket(context, CompiledSocket(color, "color3"), 0) if color is not None else None
    return texture.outputs.get("Distance")


def create_voronoi_texture(context: CompileContext, node: Any, is_2d: bool) -> bpy.types.Node:
    texture = context.material.node_tree.nodes.new(type="ShaderNodeTexVoronoi")
    texture.label = f"MaterialX {node.getName()}"
    texture.voronoi_dimensions = "2D" if is_2d else "3D"
    texture.feature = "F1"
    texture.distance = "EUCLIDEAN"
    if hasattr(texture, "normalize"):
        texture.normalize = False
    return texture


def apply_output_range(
    context: CompileContext,
    node: Any,
    source: bpy.types.NodeSocket,
    scope: Any | None,
) -> bpy.types.NodeSocket:
    out_low = input_socket(context, node, "outmin", 0.0, scope)
    out_high = input_socket(context, node, "outmax", 1.0, scope)
    return map_range_component(
        context,
        source,
        constant_socket(context, 0.0, "float").socket,
        constant_socket(context, 1.0, "float").socket,
        component_socket(context, out_low, 0),
        component_socket(context, out_high, 0),
        static_bool_input(node, "clampoutput", True),
    )
