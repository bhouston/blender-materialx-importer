from __future__ import annotations

from typing import Any

from ..blender_nodes import clamp01_component, constant_socket, input_socket, math_socket
from ..document import category
from ..types import CompileContext, CompiledSocket


def register(registry) -> None:
    registry.register_many({"and", "or", "xor", "not"}, compile_logical)


def compile_logical(context: CompileContext, node: Any, output_name: str, scope: Any | None) -> CompiledSocket | None:
    node_category = category(node)
    if node_category == "not":
        source = input_socket(context, node, "in", 0.0, scope)
        result = math_socket(context, "SUBTRACT", constant_socket(context, 1.0, "float").socket, source.socket)
        return CompiledSocket(clamp01_component(context, result), "boolean")

    input1 = input_socket(context, node, "in1", 0.0, scope)
    input2 = input_socket(context, node, "in2", 0.0, scope)
    if node_category == "and":
        result = math_socket(context, "MULTIPLY", input1.socket, input2.socket)
    elif node_category == "or":
        result = math_socket(context, "ADD", input1.socket, input2.socket)
    else:
        result = math_socket(context, "ABSOLUTE", math_socket(context, "SUBTRACT", input1.socket, input2.socket), None)
    return CompiledSocket(clamp01_component(context, result), "boolean")
