from __future__ import annotations

from typing import Any

from ..blender_nodes import combine_components, component_socket, input_socket
from ..document import type_name
from ..types import CompileContext, CompiledMatrix, CompiledSocket
from ..values import static_int_input


def register(registry) -> None:
    registry.register_many({"separate2", "separate3", "separate4"}, compile_separate)
    registry.register_many({"combine2", "combine3", "combine4"}, compile_combine)
    registry.register("dot", compile_dot)
    registry.register("extract", compile_extract)


def compile_separate(context: CompileContext, node: Any, output_name: str, scope: Any | None) -> CompiledSocket | None:
    source = input_socket(context, node, "in", 0.0, scope)
    output_map = {
        "x": 0,
        "outx": 0,
        "r": 0,
        "outr": 0,
        "y": 1,
        "outy": 1,
        "g": 1,
        "outg": 1,
        "z": 2,
        "outz": 2,
        "b": 2,
        "outb": 2,
        "w": 3,
        "outw": 3,
        "a": 3,
        "outa": 3,
    }
    return CompiledSocket(component_socket(context, source, output_map.get(output_name, 0)), "float")


def compile_combine(context: CompileContext, node: Any, output_name: str, scope: Any | None) -> CompiledSocket | None:
    output_type = type_name(node) or "vector3"
    components = [input_socket(context, node, f"in{index + 1}", 0.0, scope).socket for index in range({"combine2": 2, "combine4": 4}.get(node.getCategory(), 3))]
    compiled = combine_components(context, components, output_type)
    output_index = {
        "x": 0,
        "outx": 0,
        "r": 0,
        "outr": 0,
        "y": 1,
        "outy": 1,
        "g": 1,
        "outg": 1,
        "z": 2,
        "outz": 2,
        "b": 2,
        "outb": 2,
        "w": 3,
        "outw": 3,
        "a": 3,
        "outa": 3,
    }.get(output_name)
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
    if isinstance(source, CompiledMatrix):
        row = source.rows[min(index, source.size - 1)]
        return combine_components(context, row, type_name(node) or f"vector{source.size}")
    return CompiledSocket(component_socket(context, source, index), "float")
