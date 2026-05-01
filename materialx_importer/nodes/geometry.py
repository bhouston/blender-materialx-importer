from __future__ import annotations

from typing import Any

import bpy

from ..blender_nodes import combine_components, component_socket, constant_socket, input_socket, math_socket
from ..types import CompileContext, CompiledSocket


def register(registry) -> None:
    registry.register_many({"texcoord", "position", "normal", "tangent"}, compile_geometry)
    registry.register("frame", compile_frame)
    registry.register("time", compile_time)


def compile_geometry(context: CompileContext, node: Any, output_name: str, scope: Any | None) -> CompiledSocket | None:
    return compile_geometry_category(context, node.getCategory())


def compile_geometry_category(context: CompileContext, category: str) -> CompiledSocket | None:
    nodes = context.material.node_tree.nodes
    if category == "texcoord":
        node = nodes.new(type="ShaderNodeTexCoord")
        socket = node.outputs.get("UV")
        return CompiledSocket(socket, "vector2") if socket is not None else None
    if category in {"normal", "tangent"}:
        node = nodes.new(type="ShaderNodeNewGeometry")
        socket = node.outputs.get("Tangent" if category == "tangent" else "Normal")
        if socket is None:
            return None
        object_socket = blender_world_to_object_direction_socket(context, socket, "NORMAL" if category == "normal" else "VECTOR")
        return blender_direction_to_materialx_socket(context, object_socket)
    node = nodes.new(type="ShaderNodeTexCoord")
    socket = node.outputs.get("Object")
    return materialx_position_socket(context, socket) if socket is not None else None


def materialx_position_socket(context: CompileContext, blender_position: bpy.types.NodeSocket) -> CompiledSocket:
    # MaterialX position defaults to object/model space. Blender supplies that
    # in its Z-up basis, so convert once at the geometry semantic boundary.
    separate = context.material.node_tree.nodes.new(type="ShaderNodeSeparateXYZ")
    context.material.node_tree.links.new(blender_position, separate.inputs["Vector"])

    negate_y = math_socket(
        context,
        "MULTIPLY",
        separate.outputs["Y"],
        constant_socket(context, -1.0, "float").socket,
    )

    combine = context.material.node_tree.nodes.new(type="ShaderNodeCombineXYZ")
    context.material.node_tree.links.new(separate.outputs["X"], combine.inputs["X"])
    context.material.node_tree.links.new(separate.outputs["Z"], combine.inputs["Y"])
    context.material.node_tree.links.new(negate_y, combine.inputs["Z"])
    return CompiledSocket(combine.outputs["Vector"], "vector3")


def blender_direction_to_materialx_socket(context: CompileContext, blender_direction: bpy.types.NodeSocket) -> CompiledSocket:
    # Match the position basis conversion for vectors without applying translation.
    converted = convert_direction_basis_socket(context, blender_direction, blender_to_materialx=True)
    normalize = context.material.node_tree.nodes.new(type="ShaderNodeVectorMath")
    normalize.operation = "NORMALIZE"
    context.material.node_tree.links.new(converted.socket, normalize.inputs[0])
    return CompiledSocket(normalize.outputs["Vector"], "vector3", "unit_vector")


def blender_world_direction_to_materialx_socket(
    context: CompileContext,
    blender_direction: bpy.types.NodeSocket,
    vector_type: str = "NORMAL",
) -> CompiledSocket:
    object_socket = blender_world_to_object_direction_socket(context, blender_direction, vector_type)
    return blender_direction_to_materialx_socket(context, object_socket)


def materialx_direction_to_blender_socket(context: CompileContext, materialx_direction: CompiledSocket) -> CompiledSocket:
    return convert_direction_basis_socket(context, materialx_direction.socket, blender_to_materialx=False)


def materialx_direction_to_blender_world_socket(context: CompileContext, materialx_direction: CompiledSocket) -> CompiledSocket:
    blender_object = materialx_direction_to_blender_socket(context, materialx_direction)
    world_socket = blender_object_to_world_direction_socket(context, blender_object.socket, "NORMAL")
    return CompiledSocket(world_socket, "vector3", materialx_direction.semantic)


def materialx_direction_value_to_blender(value: tuple[float, ...]) -> tuple[float, ...]:
    if len(value) < 3:
        return value
    return (value[0], -value[2], value[1], *value[3:])


def blender_world_to_object_direction_socket(
    context: CompileContext,
    blender_direction: bpy.types.NodeSocket,
    vector_type: str,
) -> bpy.types.NodeSocket:
    transform = context.material.node_tree.nodes.new(type="ShaderNodeVectorTransform")
    transform.vector_type = vector_type
    transform.convert_from = "WORLD"
    transform.convert_to = "OBJECT"
    context.material.node_tree.links.new(blender_direction, transform.inputs["Vector"])
    return transform.outputs["Vector"]


def blender_object_to_world_direction_socket(
    context: CompileContext,
    blender_direction: bpy.types.NodeSocket,
    vector_type: str,
) -> bpy.types.NodeSocket:
    transform = context.material.node_tree.nodes.new(type="ShaderNodeVectorTransform")
    transform.vector_type = vector_type
    transform.convert_from = "OBJECT"
    transform.convert_to = "WORLD"
    context.material.node_tree.links.new(blender_direction, transform.inputs["Vector"])
    return transform.outputs["Vector"]


def convert_direction_basis_socket(
    context: CompileContext,
    direction: bpy.types.NodeSocket,
    *,
    blender_to_materialx: bool,
) -> CompiledSocket:
    source = CompiledSocket(direction, "vector3")
    x = component_socket(context, source, 0)
    y = component_socket(context, source, 1)
    z = component_socket(context, source, 2)
    if blender_to_materialx:
        negated_y = math_socket(context, "MULTIPLY", y, constant_socket(context, -1.0, "float").socket)
        return combine_components(context, [x, z, negated_y], "vector3")
    negated_z = math_socket(context, "MULTIPLY", z, constant_socket(context, -1.0, "float").socket)
    return combine_components(context, [x, negated_z, y], "vector3")


def compile_frame(context: CompileContext, node: Any, output_name: str, scope: Any | None) -> CompiledSocket | None:
    return constant_socket(context, float(bpy.context.scene.frame_current), "float")


def compile_time(context: CompileContext, node: Any, output_name: str, scope: Any | None) -> CompiledSocket | None:
    frame_offset = constant_socket(context, float(bpy.context.scene.frame_current - 1), "float")
    fps = input_socket(context, node, "fps", 24.0, scope)
    return CompiledSocket(math_socket(context, "DIVIDE", frame_offset.socket, fps.socket), "float")
