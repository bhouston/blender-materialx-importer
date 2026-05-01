from __future__ import annotations

import math
from typing import Any

import bpy

from .document import get_input, input_type_or_default, input_value, input_value_or_default, type_name
from .types import CompileContext, CompiledSocket
from .values import (
    COMPONENT_TYPES,
    component_count,
    default_type_for_value,
    parse_bool_float,
    parse_color,
    parse_float,
    parse_vector,
    static_bool_input,
    static_int_input,
)


def set_color_socket(node: bpy.types.Node, socket_name: str, value: tuple[float, float, float, float]) -> None:
    socket = node.inputs.get(socket_name)
    if socket is not None:
        socket.default_value = value


def set_scalar_socket(node: bpy.types.Node, socket_name: str, value: float) -> None:
    socket = node.inputs.get(socket_name)
    if socket is not None:
        socket.default_value = value


def set_socket_default(socket: bpy.types.NodeSocket, value: Any) -> None:
    try:
        current = socket.default_value
    except Exception:
        return
    if isinstance(current, float):
        socket.default_value = parse_bool_float(value)
        return
    pieces = parse_color(value)
    try:
        for index in range(min(len(current), len(pieces))):
            current[index] = pieces[index]
    except TypeError:
        socket.default_value = parse_bool_float(value)


def component_binary_math(
    context: CompileContext,
    node: Any,
    operation: str,
    input1_name: str,
    input2_name: str,
    default1: float,
    default2: float,
    scope: Any | None,
) -> CompiledSocket | None:
    output_type = type_name(node) or "vector3"
    input1 = input_socket(context, node, input1_name, default1, scope)
    input2 = input_socket(context, node, input2_name, default2, scope)
    components = [
        math_socket(context, operation, component_socket(context, input1, index), component_socket(context, input2, index))
        for index in range(component_count(output_type))
    ]
    return combine_components(context, components, output_type)


def component_unary_math(
    context: CompileContext,
    node: Any,
    operation: str,
    input_name: str,
    default: float,
    scope: Any | None,
) -> CompiledSocket | None:
    output_type = type_name(node) or "vector3"
    source = input_socket(context, node, input_name, default, scope)
    components = [
        math_socket(context, operation, component_socket(context, source, index), None)
        for index in range(component_count(output_type))
    ]
    return combine_components(context, components, output_type)


def input_socket(
    context: CompileContext,
    node: Any,
    input_name: str,
    default: float | tuple[float, ...],
    scope: Any | None,
) -> CompiledSocket:
    input_element = get_input(node, input_name)
    if input_element is not None and context.compiler is not None:
        compiled = context.compiler.compile_input(input_element, scope)
        if compiled is not None:
            return compiled
    value = input_value_or_default(node, input_name)
    if value is not None:
        return constant_socket(context, value, input_type_or_default(node, input_name) or default_type_for_value(default))
    return constant_socket(context, default, type_name(input_element) if input_element is not None else default_type_for_value(default))


def connect_or_set_input(
    context: CompileContext,
    node: Any,
    input_name: str,
    socket: bpy.types.NodeSocket,
    default: float | tuple[float, ...],
    scope: Any | None,
) -> None:
    input_element = get_input(node, input_name)
    if input_element is not None and context.compiler is not None:
        compiled = context.compiler.compile_input(input_element, scope)
        if compiled is not None:
            context.material.node_tree.links.new(compiled.socket, socket)
            return
    set_socket_default(socket, input_value_or_default(node, input_name) or default)


def coordinate_socket(
    context: CompileContext,
    node: Any,
    input_name: str,
    is_2d: bool,
    scope: Any | None,
) -> CompiledSocket:
    input_element = get_input(node, input_name)
    if input_element is not None and context.compiler is not None:
        compiled = context.compiler.compile_input(input_element, scope)
        if compiled is not None:
            return compiled
    fallback = context.compiler.compile_geometry("texcoord" if is_2d else "position") if context.compiler is not None else None
    if fallback is not None:
        return fallback
    return constant_socket(context, (0.0, 0.0, 0.0), "vector3")


def map_range_component(
    context: CompileContext,
    source: bpy.types.NodeSocket,
    in_low: bpy.types.NodeSocket,
    in_high: bpy.types.NodeSocket,
    out_low: bpy.types.NodeSocket,
    out_high: bpy.types.NodeSocket,
    do_clamp: bool,
) -> bpy.types.NodeSocket:
    denominator = math_socket(context, "SUBTRACT", in_high, in_low)
    normalized = math_socket(context, "DIVIDE", math_socket(context, "SUBTRACT", source, in_low), denominator)
    output_span = math_socket(context, "SUBTRACT", out_high, out_low)
    mapped = math_socket(context, "ADD", out_low, math_socket(context, "MULTIPLY", normalized, output_span))
    if not do_clamp:
        return mapped
    clamp = context.material.node_tree.nodes.new(type="ShaderNodeClamp")
    context.material.node_tree.links.new(mapped, clamp.inputs[0])
    context.material.node_tree.links.new(out_low, clamp.inputs[1])
    context.material.node_tree.links.new(out_high, clamp.inputs[2])
    return clamp.outputs[0]


def apply_gamma(
    context: CompileContext,
    source: bpy.types.NodeSocket,
    gamma: bpy.types.NodeSocket,
) -> bpy.types.NodeSocket:
    reciprocal = math_socket(context, "DIVIDE", constant_socket(context, 1.0, "float").socket, gamma)
    return math_socket(context, "POWER", source, reciprocal)


def vector_math_output(
    context: CompileContext,
    operation: str,
    input1: bpy.types.NodeSocket,
    input2: bpy.types.NodeSocket,
) -> bpy.types.NodeSocket:
    node = context.material.node_tree.nodes.new(type="ShaderNodeVectorMath")
    node.operation = operation
    context.material.node_tree.links.new(input1, node.inputs[0])
    context.material.node_tree.links.new(input2, node.inputs[1])
    return node.outputs["Vector"]


def texture_output(node: bpy.types.Node, *names: str) -> bpy.types.NodeSocket | None:
    for name in names:
        socket = node.outputs.get(name)
        if socket is not None:
            return socket
    return None


def scale_socket(
    context: CompileContext,
    source: bpy.types.NodeSocket,
    amplitude: float,
    pivot: float,
) -> bpy.types.NodeSocket:
    centered = math_socket(context, "SUBTRACT", source, constant_socket(context, pivot, "float").socket)
    scaled = math_socket(context, "MULTIPLY", centered, constant_socket(context, amplitude, "float").socket)
    return math_socket(context, "ADD", scaled, constant_socket(context, pivot, "float").socket)


def constant_socket(context: CompileContext, value: Any, type_name_value: str | None) -> CompiledSocket:
    nodes = context.material.node_tree.nodes
    if type_name_value in COMPONENT_TYPES:
        pieces = parse_vector(value)
        combine = nodes.new(type="ShaderNodeCombineXYZ")
        combine.inputs["X"].default_value = pieces[0] if len(pieces) > 0 else 0.0
        combine.inputs["Y"].default_value = pieces[1] if len(pieces) > 1 else combine.inputs["X"].default_value
        combine.inputs["Z"].default_value = pieces[2] if len(pieces) > 2 else combine.inputs["Y"].default_value
        return CompiledSocket(combine.outputs["Vector"], type_name_value or "vector3")
    node = nodes.new(type="ShaderNodeValue")
    node.outputs[0].default_value = parse_bool_float(value) if type_name_value == "boolean" else parse_float(value)
    return CompiledSocket(node.outputs[0], type_name_value or "float")


def component_socket(context: CompileContext, value: CompiledSocket, index: int) -> bpy.types.NodeSocket:
    if value.type_name not in COMPONENT_TYPES:
        return value.socket
    if index > 2:
        return constant_socket(context, 1.0, "float").socket
    separate = context.material.node_tree.nodes.new(type="ShaderNodeSeparateXYZ")
    context.material.node_tree.links.new(value.socket, separate.inputs["Vector"])
    output_name = ("X", "Y", "Z")[min(index, 2)]
    return separate.outputs[output_name]


def combine_components(
    context: CompileContext,
    components: list[bpy.types.NodeSocket],
    output_type: str,
) -> CompiledSocket:
    if component_count(output_type) == 1:
        return CompiledSocket(components[0], "float")
    combine = context.material.node_tree.nodes.new(type="ShaderNodeCombineXYZ")
    for index, socket_name in enumerate(("X", "Y", "Z")):
        source = components[min(index, len(components) - 1)]
        context.material.node_tree.links.new(source, combine.inputs[socket_name])
    return CompiledSocket(combine.outputs["Vector"], output_type)


def math_socket(
    context: CompileContext,
    operation: str,
    input1: bpy.types.NodeSocket,
    input2: bpy.types.NodeSocket | None,
) -> bpy.types.NodeSocket:
    node = context.material.node_tree.nodes.new(type="ShaderNodeMath")
    node.operation = operation
    context.material.node_tree.links.new(input1, node.inputs[0])
    if input2 is not None:
        context.material.node_tree.links.new(input2, node.inputs[1])
    return node.outputs[0]


def texcoord_input_socket(context: CompileContext, node: Any, scope: Any | None) -> CompiledSocket:
    input_element = get_input(node, "texcoord")
    if input_element is not None and context.compiler is not None:
        compiled = context.compiler.compile_input(input_element, scope)
        if compiled is not None:
            return compiled
    fallback = context.compiler.compile_geometry("texcoord") if context.compiler is not None else None
    if fallback is not None:
        return fallback
    return constant_socket(context, (0.0, 0.0), "vector2")


def clamp_component(
    context: CompileContext,
    source: bpy.types.NodeSocket,
    low: bpy.types.NodeSocket,
    high: bpy.types.NodeSocket,
) -> bpy.types.NodeSocket:
    return math_socket(context, "MINIMUM", math_socket(context, "MAXIMUM", source, low), high)


def clamp01_component(context: CompileContext, source: bpy.types.NodeSocket) -> bpy.types.NodeSocket:
    return clamp_component(
        context,
        source,
        constant_socket(context, 0.0, "float").socket,
        constant_socket(context, 1.0, "float").socket,
    )


def mix_component(
    context: CompileContext,
    value1: bpy.types.NodeSocket,
    value2: bpy.types.NodeSocket,
    factor: bpy.types.NodeSocket,
) -> bpy.types.NodeSocket:
    one_minus_factor = math_socket(context, "SUBTRACT", constant_socket(context, 1.0, "float").socket, factor)
    part1 = math_socket(context, "MULTIPLY", value1, one_minus_factor)
    part2 = math_socket(context, "MULTIPLY", value2, factor)
    return math_socket(context, "ADD", part1, part2)


def step_component(
    context: CompileContext,
    edge: bpy.types.NodeSocket,
    value: bpy.types.NodeSocket,
) -> bpy.types.NodeSocket:
    compare = context.material.node_tree.nodes.new(type="ShaderNodeMath")
    compare.operation = "LESS_THAN"
    context.material.node_tree.links.new(value, compare.inputs[0])
    context.material.node_tree.links.new(edge, compare.inputs[1])
    return math_socket(context, "SUBTRACT", constant_socket(context, 1.0, "float").socket, compare.outputs[0])


def smoothstep_component(
    context: CompileContext,
    source: bpy.types.NodeSocket,
    low: bpy.types.NodeSocket,
    high: bpy.types.NodeSocket,
) -> bpy.types.NodeSocket:
    range_size = math_socket(context, "SUBTRACT", high, low)
    safe_range = math_socket(context, "MAXIMUM", math_socket(context, "ABSOLUTE", range_size, None), constant_socket(context, 1e-6, "float").socket)
    t_value = clamp01_component(context, math_socket(context, "DIVIDE", math_socket(context, "SUBTRACT", source, low), safe_range))
    t_squared = math_socket(context, "MULTIPLY", t_value, t_value)
    hermite = math_socket(
        context,
        "MULTIPLY",
        t_squared,
        math_socket(
            context,
            "SUBTRACT",
            constant_socket(context, 3.0, "float").socket,
            math_socket(context, "MULTIPLY", constant_socket(context, 2.0, "float").socket, t_value),
        ),
    )
    fallback = step_component(context, high, source)
    use_fallback = step_component(context, high, low)
    return mix_component(context, hermite, fallback, use_fallback)


def ramp_interval_factor(
    context: CompileContext,
    x_value: bpy.types.NodeSocket,
    interval1: bpy.types.NodeSocket,
    interval2: bpy.types.NodeSocket,
    interpolation: int,
) -> bpy.types.NodeSocket:
    if interpolation == 2:
        return step_component(context, interval2, x_value)
    if interpolation == 1:
        return smoothstep_component(context, x_value, interval1, interval2)
    clamped = clamp_component(context, x_value, interval1, interval2)
    return map_range_component(
        context,
        clamped,
        interval1,
        interval2,
        constant_socket(context, 0.0, "float").socket,
        constant_socket(context, 1.0, "float").socket,
        False,
    )


def ramp_position_socket(context: CompileContext, node: Any, texcoord: CompiledSocket) -> bpy.types.NodeSocket:
    ramp_type = static_int_input(node, "type", 0)
    s = clamp01_component(context, component_socket(context, texcoord, 0))
    t = clamp01_component(context, component_socket(context, texcoord, 1))
    if ramp_type == 1:
        centered_s = math_socket(context, "SUBTRACT", s, constant_socket(context, 0.5, "float").socket)
        centered_t = math_socket(context, "SUBTRACT", t, constant_socket(context, 0.5, "float").socket)
        distance = math_socket(
            context,
            "SQRT",
            math_socket(
                context,
                "ADD",
                math_socket(context, "MULTIPLY", centered_s, centered_s),
                math_socket(context, "MULTIPLY", centered_t, centered_t),
            ),
            None,
        )
        return clamp01_component(context, math_socket(context, "MULTIPLY", distance, constant_socket(context, 2.0, "float").socket))
    if ramp_type == 2:
        centered_s = math_socket(context, "SUBTRACT", s, constant_socket(context, 0.5, "float").socket)
        centered_t = math_socket(context, "SUBTRACT", t, constant_socket(context, 0.5, "float").socket)
        angle = math_socket(context, "ARCTAN2", centered_t, centered_s)
        return math_socket(
            context,
            "ADD",
            math_socket(context, "DIVIDE", angle, constant_socket(context, math.pi * 2.0, "float").socket),
            constant_socket(context, 0.5, "float").socket,
        )
    if ramp_type == 3:
        centered_s = math_socket(context, "ABSOLUTE", math_socket(context, "SUBTRACT", s, constant_socket(context, 0.5, "float").socket), None)
        centered_t = math_socket(context, "ABSOLUTE", math_socket(context, "SUBTRACT", t, constant_socket(context, 0.5, "float").socket), None)
        return clamp01_component(
            context,
            math_socket(
                context,
                "MULTIPLY",
                math_socket(context, "MAXIMUM", centered_s, centered_t),
                constant_socket(context, 2.0, "float").socket,
            ),
        )
    return s


def luminance_component(
    context: CompileContext,
    source: CompiledSocket,
    coeffs: CompiledSocket,
) -> bpy.types.NodeSocket:
    weighted = [
        math_socket(
            context,
            "MULTIPLY",
            component_socket(context, source, index),
            component_socket(context, coeffs, index),
        )
        for index in range(3)
    ]
    return math_socket(context, "ADD", math_socket(context, "ADD", weighted[0], weighted[1]), weighted[2])


def alpha_socket(context: CompileContext, source: CompiledSocket) -> bpy.types.NodeSocket:
    if source.type_name == "color4":
        return component_socket(context, source, 3)
    return constant_socket(context, 1.0, "float").socket


def polynomial_socket(
    context: CompileContext,
    linear: bpy.types.NodeSocket,
    squared: bpy.types.NodeSocket,
    cubed: bpy.types.NodeSocket,
    coefficients: tuple[float, float, float, float],
) -> bpy.types.NodeSocket:
    cubic_part = math_socket(context, "MULTIPLY", constant_socket(context, coefficients[0], "float").socket, cubed)
    squared_part = math_socket(context, "MULTIPLY", constant_socket(context, coefficients[1], "float").socket, squared)
    linear_part = math_socket(context, "MULTIPLY", constant_socket(context, coefficients[2], "float").socket, linear)
    return math_socket(
        context,
        "ADD",
        math_socket(context, "ADD", cubic_part, squared_part),
        math_socket(context, "ADD", linear_part, constant_socket(context, coefficients[3], "float").socket),
    )


def matrix_row_socket(
    context: CompileContext,
    coefficients: tuple[float, float, float],
    values: tuple[bpy.types.NodeSocket, bpy.types.NodeSocket, bpy.types.NodeSocket],
) -> bpy.types.NodeSocket:
    products = [
        math_socket(context, "MULTIPLY", constant_socket(context, coefficients[index], "float").socket, values[index])
        for index in range(3)
    ]
    return math_socket(context, "ADD", math_socket(context, "ADD", products[0], products[1]), products[2])


def rotate2d_components(
    context: CompileContext,
    components: list[bpy.types.NodeSocket],
    degrees: CompiledSocket,
) -> list[bpy.types.NodeSocket]:
    radians = math_socket(
        context,
        "MULTIPLY",
        degrees.socket,
        constant_socket(context, math.pi / 180.0, "float").socket,
    )
    sine = math_socket(context, "SINE", radians, None)
    cosine = math_socket(context, "COSINE", radians, None)
    x_cos = math_socket(context, "MULTIPLY", cosine, components[0])
    y_sin = math_socket(context, "MULTIPLY", sine, components[1])
    y_cos = math_socket(context, "MULTIPLY", cosine, components[1])
    x_sin = math_socket(context, "MULTIPLY", sine, components[0])
    return [
        math_socket(context, "ADD", x_cos, y_sin),
        math_socket(context, "SUBTRACT", y_cos, x_sin),
    ]
