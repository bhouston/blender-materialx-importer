from __future__ import annotations

from typing import Any

from ..blender_nodes import component_socket, connect_or_set_input, input_socket
from ..document import type_name
from ..types import CompileContext, CompiledSocket
from ..values import static_int_input


def register(registry) -> None:
    registry.register_many({"separate2", "separate3", "separate4"}, compile_separate)
    registry.register_many({"combine2", "combine3", "combine4"}, compile_combine)
    registry.register("dot", compile_dot)
    registry.register("extract", compile_extract)


def compile_separate(context: CompileContext, node: Any, output_name: str, scope: Any | None) -> CompiledSocket | None:
    source = input_socket(context, node, "in", 0.0, scope)
    separate = context.material.node_tree.nodes.new(type="ShaderNodeSeparateXYZ")
    context.material.node_tree.links.new(source.socket, separate.inputs["Vector"])
    output_map = {
        "x": "X",
        "outx": "X",
        "r": "X",
        "outr": "X",
        "y": "Y",
        "outy": "Y",
        "g": "Y",
        "outg": "Y",
        "z": "Z",
        "outz": "Z",
        "b": "Z",
        "outb": "Z",
    }
    socket = separate.outputs.get(output_map.get(output_name, "X"))
    return CompiledSocket(socket, "float") if socket is not None else None


def compile_combine(context: CompileContext, node: Any, output_name: str, scope: Any | None) -> CompiledSocket | None:
    combine = context.material.node_tree.nodes.new(type="ShaderNodeCombineXYZ")
    for input_name, socket_name in (("in1", "X"), ("in2", "Y"), ("in3", "Z")):
        connect_or_set_input(context, node, input_name, combine.inputs[socket_name], 0.0, scope)
    socket = combine.outputs.get("Vector")
    if socket is None:
        return None
    compiled = CompiledSocket(socket, type_name(node) or "vector3")
    output_index = {"x": 0, "outx": 0, "r": 0, "outr": 0, "y": 1, "outy": 1, "g": 1, "outg": 1, "z": 2, "outz": 2, "b": 2, "outb": 2}.get(output_name)
    if output_index is not None:
        return CompiledSocket(component_socket(context, compiled, output_index), "float")
    return compiled


def compile_dot(context: CompileContext, node: Any, output_name: str, scope: Any | None) -> CompiledSocket | None:
    output_type = type_name(node) or "float"
    default: float | tuple[float, ...]
    if output_type in {"color4", "vector4"}:
        default = (0.0, 0.0, 0.0, 0.0)
    elif output_type in {"color3", "vector3"}:
        default = (0.0, 0.0, 0.0)
    elif output_type == "vector2":
        default = (0.0, 0.0)
    else:
        default = 0.0
    return input_socket(context, node, "in", default, scope)


def compile_extract(context: CompileContext, node: Any, output_name: str, scope: Any | None) -> CompiledSocket | None:
    source = input_socket(context, node, "in", 0.0, scope)
    index = max(0, static_int_input(node, "index", 0))
    return CompiledSocket(component_socket(context, source, index), "float")
