from __future__ import annotations

from typing import Any

from ..blender_nodes import (
    clamp01_component,
    combine_components,
    component_socket,
    input_socket,
    mix_component,
    ramp_interval_factor,
    ramp_position_socket,
    step_component,
    texcoord_input_socket,
)
from ..document import category, type_name
from ..types import CompileContext, CompiledSocket
from ..values import component_count, default_component_value, static_int_input


def register(registry) -> None:
    registry.register_many({"ramplr", "ramptb", "ramp4", "splitlr", "splittb", "ramp_gradient", "ramp"}, compile_ramp)


def compile_ramp(context: CompileContext, node: Any, output_name: str, scope: Any | None) -> CompiledSocket | None:
    node_category = category(node)
    if node_category == "ramplr":
        return compile_linear_ramp(context, node, "valuel", "valuer", 0, scope)
    if node_category == "ramptb":
        return compile_linear_ramp(context, node, "valueb", "valuet", 1, scope)
    if node_category == "ramp4":
        return compile_ramp4(context, node, scope)
    if node_category == "splitlr":
        return compile_split(context, node, "valuel", "valuer", 0, scope)
    if node_category == "splittb":
        return compile_split(context, node, "valueb", "valuet", 1, scope)
    if node_category == "ramp_gradient":
        return compile_ramp_gradient(context, node, scope)
    return compile_multi_ramp(context, node, scope)


def compile_linear_ramp(
    context: CompileContext,
    node: Any,
    input1_name: str,
    input2_name: str,
    uv_index: int,
    scope: Any | None,
) -> CompiledSocket | None:
    output_type = type_name(node) or "float"
    value1 = input_socket(context, node, input1_name, default_component_value(output_type, 0.0), scope)
    value2 = input_socket(context, node, input2_name, default_component_value(output_type, 0.0), scope)
    texcoord = texcoord_input_socket(context, node, scope)
    factor = clamp01_component(context, component_socket(context, texcoord, uv_index))
    components = [
        mix_component(
            context,
            component_socket(context, value1, index),
            component_socket(context, value2, index),
            factor,
        )
        for index in range(component_count(output_type))
    ]
    return combine_components(context, components, output_type)


def compile_ramp4(context: CompileContext, node: Any, scope: Any | None) -> CompiledSocket | None:
    output_type = type_name(node) or "color3"
    valuetl = input_socket(context, node, "valuetl", default_component_value(output_type, 0.0), scope)
    valuetr = input_socket(context, node, "valuetr", default_component_value(output_type, 0.0), scope)
    valuebl = input_socket(context, node, "valuebl", default_component_value(output_type, 0.0), scope)
    valuebr = input_socket(context, node, "valuebr", default_component_value(output_type, 0.0), scope)
    texcoord = texcoord_input_socket(context, node, scope)
    s = clamp01_component(context, component_socket(context, texcoord, 0))
    t = clamp01_component(context, component_socket(context, texcoord, 1))
    components = []
    for index in range(component_count(output_type)):
        top = mix_component(context, component_socket(context, valuetl, index), component_socket(context, valuetr, index), s)
        bottom = mix_component(context, component_socket(context, valuebl, index), component_socket(context, valuebr, index), s)
        components.append(mix_component(context, top, bottom, t))
    return combine_components(context, components, output_type)


def compile_split(
    context: CompileContext,
    node: Any,
    input1_name: str,
    input2_name: str,
    uv_index: int,
    scope: Any | None,
) -> CompiledSocket | None:
    output_type = type_name(node) or "float"
    value1 = input_socket(context, node, input1_name, default_component_value(output_type, 0.0), scope)
    value2 = input_socket(context, node, input2_name, default_component_value(output_type, 0.0), scope)
    center = input_socket(context, node, "center", 0.5, scope)
    texcoord = texcoord_input_socket(context, node, scope)
    factor = step_component(context, component_socket(context, center, 0), component_socket(context, texcoord, uv_index))
    components = [
        mix_component(
            context,
            component_socket(context, value1, index),
            component_socket(context, value2, index),
            factor,
        )
        for index in range(component_count(output_type))
    ]
    return combine_components(context, components, output_type)


def compile_ramp_gradient(context: CompileContext, node: Any, scope: Any | None) -> CompiledSocket | None:
    x_value = input_socket(context, node, "x", 0.0, scope)
    interval1 = input_socket(context, node, "interval1", 0.0, scope)
    interval2 = input_socket(context, node, "interval2", 1.0, scope)
    color1 = input_socket(context, node, "color1", (0.0, 0.0, 0.0, 1.0), scope)
    color2 = input_socket(context, node, "color2", (1.0, 1.0, 1.0, 1.0), scope)
    prev_color = input_socket(context, node, "prev_color", (0.0, 0.0, 0.0, 1.0), scope)
    factor = ramp_interval_factor(
        context,
        x_value.socket,
        interval1.socket,
        interval2.socket,
        static_int_input(node, "interpolation", 1),
    )
    x_after_start = step_component(context, interval1.socket, x_value.socket)
    interval_num = input_socket(context, node, "interval_num", 1.0, scope)
    num_intervals = input_socket(context, node, "num_intervals", 2.0, scope)
    keep_prev = step_component(context, num_intervals.socket, interval_num.socket)
    components = []
    for index in range(3):
        interpolated = mix_component(
            context,
            component_socket(context, color1, index),
            component_socket(context, color2, index),
            factor,
        )
        within_interval = mix_component(context, component_socket(context, prev_color, index), interpolated, x_after_start)
        components.append(mix_component(context, within_interval, component_socket(context, prev_color, index), keep_prev))
    return combine_components(context, components, "color4")


def compile_multi_ramp(context: CompileContext, node: Any, scope: Any | None) -> CompiledSocket | None:
    texcoord = texcoord_input_socket(context, node, scope)
    ramp_x = ramp_position_socket(context, node, texcoord)
    interpolation = static_int_input(node, "interpolation", 1)
    num_intervals = max(1, min(10, static_int_input(node, "num_intervals", 2)))
    result = input_socket(context, node, "color1", (0.0, 0.0, 0.0, 1.0), scope)
    for index in range(1, num_intervals):
        interval1 = input_socket(context, node, f"interval{index}", 0.0 if index == 1 else 1.0, scope)
        interval2 = input_socket(context, node, f"interval{index + 1}", 1.0, scope)
        color1 = input_socket(context, node, f"color{index}", (0.0, 0.0, 0.0, 1.0) if index == 1 else (1.0, 1.0, 1.0, 1.0), scope)
        color2 = input_socket(context, node, f"color{index + 1}", (1.0, 1.0, 1.0, 1.0), scope)
        factor = ramp_interval_factor(context, ramp_x, interval1.socket, interval2.socket, interpolation)
        x_after_start = step_component(context, interval1.socket, ramp_x)
        components = []
        for component_index in range(3):
            interpolated = mix_component(
                context,
                component_socket(context, color1, component_index),
                component_socket(context, color2, component_index),
                factor,
            )
            components.append(
                mix_component(
                    context,
                    component_socket(context, result, component_index),
                    interpolated,
                    x_after_start,
                )
            )
        result = combine_components(context, components, "color4")
    return result
