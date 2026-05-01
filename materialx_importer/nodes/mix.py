from __future__ import annotations

from typing import Any

import bpy

from ..blender_nodes import (
    combine_components,
    component_socket,
    constant_socket,
    input_socket,
    math_socket,
    mix_component,
    step_component,
)
from ..document import category, type_name
from ..types import CompileContext, CompiledSocket
from ..values import component_count


def register(registry) -> None:
    registry.register("mix", compile_mix_like)
    registry.register("minus", compile_mix_like)
    registry.register("difference", compile_mix_like)
    registry.register("burn", compile_burn)
    registry.register("dodge", compile_dodge)
    registry.register("overlay", compile_overlay)
    registry.register_many({"ifgreater", "ifgreatereq", "ifequal"}, compile_conditional)


def compile_mix_like(context: CompileContext, node: Any, output_name: str, scope: Any | None) -> CompiledSocket | None:
    mode = category(node)
    output_type = type_name(node) or "float"
    components = component_count(output_type)
    mix_socket = input_socket(context, node, "mix", 0.0 if mode == "mix" else 1.0, scope)
    bg = input_socket(context, node, "bg", 0.0, scope)
    fg = input_socket(context, node, "fg", 0.0, scope)
    result_components: list[bpy.types.NodeSocket] = []
    for index in range(components):
        bg_component = component_socket(context, bg, index)
        fg_component = component_socket(context, fg, index)
        mix_component = component_socket(context, mix_socket, index)
        if mode == "minus":
            diff = math_socket(context, "SUBTRACT", bg_component, fg_component)
            mixed_diff = math_socket(context, "MULTIPLY", mix_component, diff)
            one_minus_mix = math_socket(context, "SUBTRACT", constant_socket(context, 1.0, "float").socket, mix_component)
            retained_bg = math_socket(context, "MULTIPLY", one_minus_mix, bg_component)
            result_components.append(math_socket(context, "ADD", mixed_diff, retained_bg))
        elif mode == "difference":
            diff = math_socket(context, "ABSOLUTE", math_socket(context, "SUBTRACT", bg_component, fg_component), None)
            mixed_diff = math_socket(context, "MULTIPLY", mix_component, diff)
            retained_bg = math_socket(
                context,
                "MULTIPLY",
                math_socket(context, "SUBTRACT", constant_socket(context, 1.0, "float").socket, mix_component),
                bg_component,
            )
            result_components.append(math_socket(context, "ADD", mixed_diff, retained_bg))
        else:
            one_minus_mix = math_socket(context, "SUBTRACT", constant_socket(context, 1.0, "float").socket, mix_component)
            bg_part = math_socket(context, "MULTIPLY", bg_component, one_minus_mix)
            fg_part = math_socket(context, "MULTIPLY", fg_component, mix_component)
            result_components.append(math_socket(context, "ADD", bg_part, fg_part))
    return combine_components(context, result_components, output_type)


def compile_burn(context: CompileContext, node: Any, output_name: str, scope: Any | None) -> CompiledSocket | None:
    output_type = type_name(node) or "float"
    fg = input_socket(context, node, "fg", 0.0, scope)
    bg = input_socket(context, node, "bg", 0.0, scope)
    mix_socket = input_socket(context, node, "mix", 1.0, scope)
    one = constant_socket(context, 1.0, "float").socket
    epsilon = constant_socket(context, 1e-6, "float").socket
    result_components: list[bpy.types.NodeSocket] = []
    for index in range(component_count(output_type)):
        fg_component = component_socket(context, fg, index)
        bg_component = component_socket(context, bg, index)
        mix_component = component_socket(context, mix_socket, index)
        fg_abs = math_socket(context, "ABSOLUTE", fg_component, None)
        fg_present = step_component(context, epsilon, fg_abs)
        safe_fg = math_socket(
            context,
            "ADD",
            math_socket(context, "MULTIPLY", fg_component, fg_present),
            math_socket(context, "SUBTRACT", one, fg_present),
        )
        burned = math_socket(
            context,
            "SUBTRACT",
            one,
            math_socket(context, "DIVIDE", math_socket(context, "SUBTRACT", one, bg_component), safe_fg),
        )
        burned_part = math_socket(context, "MULTIPLY", mix_component, burned)
        retained_part = math_socket(context, "MULTIPLY", math_socket(context, "SUBTRACT", one, mix_component), bg_component)
        result_components.append(
            math_socket(context, "MULTIPLY", math_socket(context, "ADD", burned_part, retained_part), fg_present)
        )
    return combine_components(context, result_components, output_type)


def compile_dodge(context: CompileContext, node: Any, output_name: str, scope: Any | None) -> CompiledSocket | None:
    output_type = type_name(node) or "float"
    fg = input_socket(context, node, "fg", 0.0, scope)
    bg = input_socket(context, node, "bg", 0.0, scope)
    mix_socket = input_socket(context, node, "mix", 1.0, scope)
    one = constant_socket(context, 1.0, "float").socket
    epsilon = constant_socket(context, 1e-6, "float").socket
    result_components: list[bpy.types.NodeSocket] = []
    for index in range(component_count(output_type)):
        fg_component = component_socket(context, fg, index)
        bg_component = component_socket(context, bg, index)
        mix_component_socket = component_socket(context, mix_socket, index)
        one_minus_fg = math_socket(context, "SUBTRACT", one, fg_component)
        denominator_present = step_component(context, epsilon, math_socket(context, "ABSOLUTE", one_minus_fg, None))
        safe_denominator = math_socket(
            context,
            "ADD",
            math_socket(context, "MULTIPLY", one_minus_fg, denominator_present),
            math_socket(context, "SUBTRACT", one, denominator_present),
        )
        dodged = math_socket(context, "DIVIDE", bg_component, safe_denominator)
        dodged_part = math_socket(context, "MULTIPLY", mix_component_socket, dodged)
        retained_part = math_socket(
            context,
            "MULTIPLY",
            math_socket(context, "SUBTRACT", one, mix_component_socket),
            bg_component,
        )
        result_components.append(
            math_socket(context, "MULTIPLY", math_socket(context, "ADD", dodged_part, retained_part), denominator_present)
        )
    return combine_components(context, result_components, output_type)


def compile_overlay(context: CompileContext, node: Any, output_name: str, scope: Any | None) -> CompiledSocket | None:
    output_type = type_name(node) or "float"
    fg = input_socket(context, node, "fg", 0.0, scope)
    bg = input_socket(context, node, "bg", 0.0, scope)
    mix_socket = input_socket(context, node, "mix", 1.0, scope)
    one = constant_socket(context, 1.0, "float").socket
    two = constant_socket(context, 2.0, "float").socket
    half = constant_socket(context, 0.5, "float").socket
    result_components: list[bpy.types.NodeSocket] = []
    for index in range(component_count(output_type)):
        fg_component = component_socket(context, fg, index)
        bg_component = component_socket(context, bg, index)
        mix_component_socket = component_socket(context, mix_socket, index)
        low_branch = math_socket(context, "MULTIPLY", two, math_socket(context, "MULTIPLY", fg_component, bg_component))
        high_branch = math_socket(
            context,
            "SUBTRACT",
            one,
            math_socket(
                context,
                "MULTIPLY",
                two,
                math_socket(
                    context,
                    "MULTIPLY",
                    math_socket(context, "SUBTRACT", one, fg_component),
                    math_socket(context, "SUBTRACT", one, bg_component),
                ),
            ),
        )
        use_high_branch = step_component(context, half, bg_component)
        overlayed = mix_component(context, low_branch, high_branch, use_high_branch)
        result_components.append(mix_component(context, bg_component, overlayed, mix_component_socket))
    return combine_components(context, result_components, output_type)


def compile_conditional(context: CompileContext, node: Any, output_name: str, scope: Any | None) -> CompiledSocket | None:
    node_category = category(node)
    value1 = input_socket(context, node, "value1", 1.0 if node_category != "ifequal" else 0.0, scope)
    value2 = input_socket(context, node, "value2", 0.0, scope)
    compare = context.material.node_tree.nodes.new(type="ShaderNodeMath")
    if node_category == "ifgreater":
        compare.operation = "GREATER_THAN"
        context.material.node_tree.links.new(value1.socket, compare.inputs[0])
        context.material.node_tree.links.new(value2.socket, compare.inputs[1])
        condition = compare.outputs[0]
    elif node_category == "ifgreatereq":
        compare.operation = "LESS_THAN"
        context.material.node_tree.links.new(value1.socket, compare.inputs[0])
        context.material.node_tree.links.new(value2.socket, compare.inputs[1])
        condition = math_socket(context, "SUBTRACT", constant_socket(context, 1.0, "float").socket, compare.outputs[0])
    else:
        compare.operation = "COMPARE"
        context.material.node_tree.links.new(value1.socket, compare.inputs[0])
        context.material.node_tree.links.new(value2.socket, compare.inputs[1])
        compare.inputs[2].default_value = 1e-6
        condition = compare.outputs[0]

    output_type = type_name(node) or "float"
    if output_type == "boolean":
        return CompiledSocket(condition, "boolean")

    in1 = input_socket(context, node, "in1", 0.0, scope)
    in2 = input_socket(context, node, "in2", 0.0, scope)
    condition_value = CompiledSocket(condition, "float")
    result_components: list[bpy.types.NodeSocket] = []
    for index in range(component_count(output_type)):
        condition_component = component_socket(context, condition_value, index)
        in1_component = component_socket(context, in1, index)
        in2_component = component_socket(context, in2, index)
        one_minus_condition = math_socket(context, "SUBTRACT", constant_socket(context, 1.0, "float").socket, condition_component)
        false_part = math_socket(context, "MULTIPLY", in2_component, one_minus_condition)
        true_part = math_socket(context, "MULTIPLY", in1_component, condition_component)
        result_components.append(math_socket(context, "ADD", false_part, true_part))
    return combine_components(context, result_components, output_type)
