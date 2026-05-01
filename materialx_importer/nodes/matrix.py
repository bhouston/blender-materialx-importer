from __future__ import annotations

from typing import Any

import bpy

from ..blender_nodes import combine_components, component_socket, constant_socket, input_socket, math_socket
from ..document import attribute, get_input, input_value, is_connected, type_name
from ..types import CompileContext, CompiledMatrix, CompiledSocket
from ..values import identity_matrix_values, matrix_size, parse_matrix
from .geometry import blender_direction_to_materialx_socket, materialx_direction_to_blender_socket


VECTOR_OUTPUTS = {
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


def register(registry) -> None:
    registry.register("creatematrix", compile_creatematrix)
    registry.register("transpose", compile_transpose)
    registry.register("determinant", compile_determinant)
    registry.register("invertmatrix", compile_invertmatrix)
    registry.register("transformmatrix", compile_transformmatrix)
    registry.register("transformpoint", compile_space_transform)
    registry.register("transformvector", compile_space_transform)
    registry.register("transformnormal", compile_space_transform)


def compile_creatematrix(context: CompileContext, node: Any, output_name: str, scope: Any | None) -> CompiledMatrix | None:
    output_type = type_name(node) or "matrix33"
    size = matrix_size(output_type) or 3
    node_def = attribute(node, "nodedef") or ""
    use_vector4_rows = node_def == "ND_creatematrix_vector4_matrix44"
    identity = identity_matrix_values(size)
    rows: list[list[bpy.types.NodeSocket]] = []

    for row_index in range(size):
        default_components = tuple(identity[row_index][: 4 if use_vector4_rows else 3])
        source = input_socket(context, node, f"in{row_index + 1}", default_components, scope)
        row = [component_socket(context, source, column) for column in range(min(size, 3))]
        if size == 4:
            if use_vector4_rows:
                row.append(component_socket(context, source, 3))
            else:
                row.append(constant_socket(context, 1.0 if row_index == 3 else 0.0, "float").socket)
        rows.append(row)

    return CompiledMatrix(size=size, rows=rows, type_name=output_type)


def compile_transpose(context: CompileContext, node: Any, output_name: str, scope: Any | None) -> CompiledMatrix | None:
    source = matrix_input(context, node, "in", _node_matrix_size(node), scope)
    return CompiledMatrix(
        size=source.size,
        rows=[[source.rows[column][row] for column in range(source.size)] for row in range(source.size)],
        type_name=source.type_name,
        values=_transpose_values(source.values),
    )


def compile_determinant(context: CompileContext, node: Any, output_name: str, scope: Any | None) -> CompiledSocket | None:
    source = matrix_input(context, node, "in", _node_matrix_size(node), scope)
    return CompiledSocket(_determinant_socket(context, source.rows), "float")


def compile_invertmatrix(context: CompileContext, node: Any, output_name: str, scope: Any | None) -> CompiledMatrix | None:
    source = matrix_input(context, node, "in", _node_matrix_size(node), scope)
    if source.values is not None:
        inverted = _invert_matrix_values(source.values)
        if inverted is None:
            context.warnings.append(f"Matrix input for {node.getName() or 'invertmatrix'} is singular; using identity fallback.")
            return constant_matrix(context, identity_matrix_values(source.size), source.size)
        return constant_matrix(context, inverted, source.size)

    if source.size == 3:
        return CompiledMatrix(size=3, rows=_invert_matrix33_rows(context, source.rows), type_name="matrix33")

    context.warnings.append("Dynamic matrix44 inversion is not supported by the Blender importer; using identity fallback.")
    return constant_matrix(context, identity_matrix_values(source.size), source.size)


def compile_transformmatrix(context: CompileContext, node: Any, output_name: str, scope: Any | None) -> CompiledSocket | None:
    node_def = attribute(node, "nodedef") or ""
    output_type = type_name(node) or "vector3"
    matrix_size_value = 4 if node_def in {"ND_transformmatrix_vector3M4", "ND_transformmatrix_vector4"} else 3
    source = input_socket(context, node, "in", _default_transform_input(node_def), scope)
    matrix = matrix_input(context, node, "mat", matrix_size_value, scope)

    vector = [component_socket(context, source, index) for index in range(min(matrix.size, 3))]
    if matrix.size == 4:
        homogeneous = component_socket(context, source, 3) if node_def == "ND_transformmatrix_vector4" else constant_socket(context, 1.0, "float").socket
        vector.append(homogeneous)
    elif node_def == "ND_transformmatrix_vector2M3":
        vector = [component_socket(context, source, 0), component_socket(context, source, 1), constant_socket(context, 1.0, "float").socket]

    output_count = 2 if node_def == "ND_transformmatrix_vector2M3" else min(4 if output_type == "vector4" else 3, matrix.size)
    components = _matrix_vector_product(context, matrix.rows, vector, output_count)
    compiled = combine_components(context, components, output_type)
    return _select_vector_output(context, compiled, output_name)


def compile_space_transform(context: CompileContext, node: Any, output_name: str, scope: Any | None) -> CompiledSocket | None:
    category = node.getCategory()
    default = (0.0, 0.0, 1.0) if category == "transformnormal" else (0.0, 0.0, 0.0)
    source = input_socket(context, node, "in", default, scope)
    from_space = _space_input(node, "fromspace")
    to_space = _space_input(node, "tospace")

    if category == "transformnormal":
        blender_source = materialx_direction_to_blender_socket(context, source)
        if from_space is None or to_space is None or from_space == "" or to_space == "" or from_space == to_space:
            socket = blender_source.socket
        else:
            transform = context.material.node_tree.nodes.new(type="ShaderNodeVectorTransform")
            transform.vector_type = "NORMAL"
            transform.convert_from = from_space
            transform.convert_to = to_space
            context.material.node_tree.links.new(blender_source.socket, transform.inputs["Vector"])
            socket = transform.outputs["Vector"]
        compiled = blender_direction_to_materialx_socket(context, socket)
        return _select_vector_output(context, compiled, output_name)

    if from_space is None or to_space is None or from_space == "" or to_space == "" or from_space == to_space:
        socket = source.socket
    else:
        transform = context.material.node_tree.nodes.new(type="ShaderNodeVectorTransform")
        transform.vector_type = {"transformpoint": "POINT", "transformvector": "VECTOR", "transformnormal": "NORMAL"}[category]
        transform.convert_from = from_space
        transform.convert_to = to_space
        context.material.node_tree.links.new(source.socket, transform.inputs["Vector"])
        socket = transform.outputs["Vector"]

    return _select_vector_output(context, CompiledSocket(socket, "vector3"), output_name)


def matrix_input(context: CompileContext, node: Any, input_name: str, default_size: int, scope: Any | None) -> CompiledMatrix:
    input_element = get_input(node, input_name)
    input_type = type_name(input_element)
    size = matrix_size(input_type) or default_size
    if input_element is not None and is_connected(input_element) and context.compiler is not None:
        compiled = context.compiler.compile_input(input_element, scope)
        if isinstance(compiled, CompiledMatrix):
            return compiled
        context.warnings.append(f"Connected matrix input {input_name} did not produce a matrix; using identity fallback.")
    value = input_value(input_element)
    if value is not None:
        return constant_matrix(context, parse_matrix(value, size), size)
    return constant_matrix(context, identity_matrix_values(size), size)


def constant_matrix(context: CompileContext, values: list[list[float]], size: int) -> CompiledMatrix:
    rows = [[constant_socket(context, values[row][column], "float").socket for column in range(size)] for row in range(size)]
    return CompiledMatrix(size=size, rows=rows, type_name=f"matrix{size}{size}", values=values)


def _node_matrix_size(node: Any) -> int:
    size = matrix_size(type_name(node))
    if size is not None:
        return size
    input_size = matrix_size(type_name(get_input(node, "in")))
    return input_size or 3


def _default_transform_input(node_def: str) -> float | tuple[float, ...]:
    if node_def == "ND_transformmatrix_vector2M3":
        return (0.0, 0.0)
    if node_def == "ND_transformmatrix_vector4":
        return (0.0, 0.0, 0.0, 0.0)
    return (0.0, 0.0, 0.0)


def _space_input(node: Any, input_name: str) -> str | None:
    value = input_value(get_input(node, input_name))
    if value is None or value == "":
        return ""
    normalized = value.strip().lower()
    if normalized in {"object", "model"}:
        return "OBJECT"
    if normalized == "world":
        return "WORLD"
    return None


def _select_vector_output(context: CompileContext, compiled: CompiledSocket, output_name: str) -> CompiledSocket:
    index = VECTOR_OUTPUTS.get(output_name)
    if index is None:
        return compiled
    return CompiledSocket(component_socket(context, compiled, index), "float")


def _matrix_vector_product(
    context: CompileContext,
    rows: list[list[bpy.types.NodeSocket]],
    vector: list[bpy.types.NodeSocket],
    output_count: int,
) -> list[bpy.types.NodeSocket]:
    return [
        _sum_sockets(context, [math_socket(context, "MULTIPLY", rows[row][column], vector[column]) for column in range(len(vector))])
        for row in range(output_count)
    ]


def _sum_sockets(context: CompileContext, sockets: list[bpy.types.NodeSocket]) -> bpy.types.NodeSocket:
    result = sockets[0]
    for socket in sockets[1:]:
        result = math_socket(context, "ADD", result, socket)
    return result


def _determinant_socket(context: CompileContext, rows: list[list[bpy.types.NodeSocket]]) -> bpy.types.NodeSocket:
    size = len(rows)
    if size == 1:
        return rows[0][0]
    if size == 2:
        return math_socket(
            context,
            "SUBTRACT",
            math_socket(context, "MULTIPLY", rows[0][0], rows[1][1]),
            math_socket(context, "MULTIPLY", rows[0][1], rows[1][0]),
        )

    terms = []
    for column in range(size):
        minor = [[rows[row][minor_column] for minor_column in range(size) if minor_column != column] for row in range(1, size)]
        term = math_socket(context, "MULTIPLY", rows[0][column], _determinant_socket(context, minor))
        if column % 2 == 1:
            term = math_socket(context, "SUBTRACT", constant_socket(context, 0.0, "float").socket, term)
        terms.append(term)
    return _sum_sockets(context, terms)


def _invert_matrix33_rows(context: CompileContext, rows: list[list[bpy.types.NodeSocket]]) -> list[list[bpy.types.NodeSocket]]:
    m = rows
    determinant = _determinant_socket(context, rows)

    def submul(a: bpy.types.NodeSocket, b: bpy.types.NodeSocket, c: bpy.types.NodeSocket, d: bpy.types.NodeSocket) -> bpy.types.NodeSocket:
        return math_socket(context, "SUBTRACT", math_socket(context, "MULTIPLY", a, b), math_socket(context, "MULTIPLY", c, d))

    numerators = [
        [submul(m[1][1], m[2][2], m[1][2], m[2][1]), submul(m[0][2], m[2][1], m[0][1], m[2][2]), submul(m[0][1], m[1][2], m[0][2], m[1][1])],
        [submul(m[1][2], m[2][0], m[1][0], m[2][2]), submul(m[0][0], m[2][2], m[0][2], m[2][0]), submul(m[0][2], m[1][0], m[0][0], m[1][2])],
        [submul(m[1][0], m[2][1], m[1][1], m[2][0]), submul(m[0][1], m[2][0], m[0][0], m[2][1]), submul(m[0][0], m[1][1], m[0][1], m[1][0])],
    ]
    return [[math_socket(context, "DIVIDE", numerator, determinant) for numerator in row] for row in numerators]


def _transpose_values(values: list[list[float]] | None) -> list[list[float]] | None:
    if values is None:
        return None
    return [[values[column][row] for column in range(len(values))] for row in range(len(values))]


def _invert_matrix_values(values: list[list[float]]) -> list[list[float]] | None:
    size = len(values)
    matrix = [[float(values[row][column]) for column in range(size)] for row in range(size)]
    inverse = identity_matrix_values(size)
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(matrix[row][column]))
        if abs(matrix[pivot][column]) < 1e-8:
            return None
        if pivot != column:
            matrix[column], matrix[pivot] = matrix[pivot], matrix[column]
            inverse[column], inverse[pivot] = inverse[pivot], inverse[column]
        scale = matrix[column][column]
        matrix[column] = [value / scale for value in matrix[column]]
        inverse[column] = [value / scale for value in inverse[column]]
        for row in range(size):
            if row == column:
                continue
            factor = matrix[row][column]
            matrix[row] = [matrix[row][index] - factor * matrix[column][index] for index in range(size)]
            inverse[row] = [inverse[row][index] - factor * inverse[column][index] for index in range(size)]
    return inverse
