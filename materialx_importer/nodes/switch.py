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
)
from ..document import get_input, type_name
from ..types import CompileContext, CompiledSocket
from ..values import component_count

_SWITCH_MIN_INDEX = 1
_SWITCH_MAX_INDEX = 10


def register(registry) -> None:
    registry.register("switch", compile_switch)


def compile_switch(context: CompileContext, node: Any, output_name: str, scope: Any | None) -> CompiledSocket | None:
    output_type = type_name(node) or "float"
    which = input_socket(context, node, "which", 0.0, scope)
    which_floor = math_socket(context, "FLOOR", component_socket(context, which, 0), None)
    switch_index = math_socket(context, "ADD", which_floor, constant_socket(context, 1.0, "float").socket)
    clamped_index = math_socket(
        context,
        "MINIMUM",
        math_socket(context, "MAXIMUM", switch_index, constant_socket(context, _SWITCH_MIN_INDEX, "float").socket),
        constant_socket(context, _SWITCH_MAX_INDEX, "float").socket,
    )

    result_components: list[bpy.types.NodeSocket] = []
    for component_index in range(component_count(output_type)):
        selected = component_socket(context, _branch_input_socket(context, node, _SWITCH_MIN_INDEX, output_type, scope), component_index)
        for branch_index in range(_SWITCH_MIN_INDEX + 1, _SWITCH_MAX_INDEX + 1):
            candidate = _branch_input_socket(context, node, branch_index, output_type, scope)
            is_branch = _compare_equals(context, clamped_index, branch_index)
            selected = mix_component(context, selected, component_socket(context, candidate, component_index), is_branch)
        result_components.append(selected)

    return combine_components(context, result_components, output_type)


def _branch_input_socket(
    context: CompileContext,
    node: Any,
    branch_index: int,
    branch_type: str,
    scope: Any | None,
) -> CompiledSocket:
    input_name = f"in{branch_index}"
    if get_input(node, input_name) is None:
        return constant_socket(context, 0.0, branch_type)
    return input_socket(context, node, input_name, 0.0, scope)


def _compare_equals(context: CompileContext, value: bpy.types.NodeSocket, target_index: int) -> bpy.types.NodeSocket:
    compare = context.material.node_tree.nodes.new(type="ShaderNodeMath")
    compare.operation = "COMPARE"
    context.material.node_tree.links.new(value, compare.inputs[0])
    context.material.node_tree.links.new(constant_socket(context, target_index, "float").socket, compare.inputs[1])
    compare.inputs[2].default_value = 1e-6
    return compare.outputs[0]
