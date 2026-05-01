from __future__ import annotations

from typing import Any

import bpy

from .blender_nodes import (
    combine_components,
    component_socket,
    constant_socket,
    math_socket,
    set_color_socket,
    set_scalar_socket,
    set_socket_default,
)
from .document import call_optional, category, get_declaration_input, get_input, input_type_or_default, input_value, input_value_or_default, is_connected
from .nodes.geometry import materialx_direction_to_blender_world_socket, materialx_direction_value_to_blender
from .types import CompileContext, CompiledSocket
from .values import default_type_for_value, parse_color, parse_float, parse_vector


def apply_surface_inputs(
    context: CompileContext,
    surface_node: Any,
    principled: bpy.types.Node,
) -> None:
    surface_category = category(surface_node)
    if surface_category == "standard_surface":
        apply_standard_surface_inputs(context, surface_node, principled)
    elif surface_category == "gltf_pbr":
        apply_gltf_pbr_surface_inputs(context, surface_node, principled)
    elif surface_category == "open_pbr_surface":
        apply_open_pbr_surface_inputs(context, surface_node, principled)
    else:
        context.warnings.append(f"Unsupported surface shader category: {surface_category}")
        return


def apply_standard_surface_inputs(context: CompileContext, surface_node: Any, principled: bpy.types.Node) -> None:
    connect_weighted_color_input(context, surface_node, principled, "base", "base_color", ("Base Color",), 1.0, (0.8, 0.8, 0.8, 1.0))
    connect_weighted_color_input(
        context,
        surface_node,
        principled,
        "specular",
        "specular_color",
        ("Specular Tint", "Specular Color"),
        1.0,
        (1.0, 1.0, 1.0, 1.0),
    )

    for input_name, socket_names in {
        "metalness": ("Metallic",),
        "diffuse_roughness": ("Diffuse Roughness",),
        "specular_roughness": ("Roughness",),
        "specular_IOR": ("IOR",),
        "specular_ior": ("IOR",),
        "specular_anisotropy": ("Anisotropic", "Specular Anisotropy"),
        "specular_rotation": ("Anisotropic Rotation", "Specular Rotation"),
        "transmission": ("Transmission Weight", "Transmission"),
        "subsurface": ("Subsurface Weight", "Subsurface"),
        "subsurface_scale": ("Subsurface Scale",),
        "subsurface_anisotropy": ("Subsurface Anisotropy",),
        "sheen": ("Sheen Weight", "Sheen"),
        "sheen_roughness": ("Sheen Roughness",),
        "coat": ("Coat Weight", "Coat"),
        "coat_roughness": ("Coat Roughness",),
        "coat_ior": ("Coat IOR",),
        "thin_film_thickness": ("Thin Film Thickness",),
        "thin_film_IOR": ("Thin Film IOR",),
        "thin_film_ior": ("Thin Film IOR",),
        "emission": ("Emission Strength",),
    }.items():
        connect_or_set_surface_input(context, surface_node, principled, input_name, socket_names, "scalar")

    for input_name, socket_names in {
        "subsurface_radius": ("Subsurface Radius",),
        "normal": ("Normal",),
        "coat_normal": ("Coat Normal",),
        "tangent": ("Tangent",),
    }.items():
        connect_or_set_surface_input(context, surface_node, principled, input_name, socket_names, "vector")

    for input_name, socket_names in {
        "emission_color": ("Emission Color",),
        "sheen_color": ("Sheen Tint", "Sheen Color"),
        "coat_color": ("Coat Tint", "Coat Color"),
    }.items():
        connect_or_set_surface_input(context, surface_node, principled, input_name, socket_names, "color")

    apply_static_transmission_tint(context, surface_node, principled, "transmission", "transmission_color")
    configure_transmission_material(context, surface_node, "transmission")
    apply_opacity_input(context, surface_node, principled, "opacity", "BLEND")


def apply_gltf_pbr_surface_inputs(context: CompileContext, surface_node: Any, principled: bpy.types.Node) -> None:
    for input_name, socket_names in {
        "metallic": ("Metallic",),
        "roughness": ("Roughness",),
        "transmission": ("Transmission Weight", "Transmission"),
        "ior": ("IOR",),
        "specular": ("Specular IOR Level",),
        "emissive_strength": ("Emission Strength",),
    }.items():
        connect_or_set_surface_input(context, surface_node, principled, input_name, socket_names, "scalar")

    for input_name, socket_names in {
        "base_color": ("Base Color",),
        "emissive": ("Emission Color",),
    }.items():
        connect_or_set_surface_input(context, surface_node, principled, input_name, socket_names, "color")

    apply_static_transmission_tint(context, surface_node, principled, "transmission", "attenuation_color")
    configure_transmission_material(context, surface_node, "transmission")
    apply_gltf_alpha_inputs(context, surface_node, principled)
    connect_or_set_surface_input(context, surface_node, principled, "normal", ("Normal",), "vector", connected_only=True)


def apply_open_pbr_surface_inputs(context: CompileContext, surface_node: Any, principled: bpy.types.Node) -> None:
    connect_weighted_color_input(
        context,
        surface_node,
        principled,
        "base_weight",
        "base_color",
        ("Base Color",),
        1.0,
        (0.8, 0.8, 0.8, 1.0),
    )
    connect_weighted_color_input(
        context,
        surface_node,
        principled,
        "specular_weight",
        "specular_color",
        ("Specular Tint", "Specular Color"),
        1.0,
        (1.0, 1.0, 1.0, 1.0),
    )
    connect_weighted_color_input(
        context,
        surface_node,
        principled,
        "coat_darkening",
        "coat_color",
        ("Coat Tint", "Coat Color"),
        1.0,
        (1.0, 1.0, 1.0, 1.0),
    )
    multiply_inputs_to_socket(
        context,
        surface_node,
        principled,
        "subsurface_color",
        "subsurface_radius_scale",
        ("Subsurface Radius",),
        (1.0, 0.2, 0.1),
        (1.0, 1.0, 1.0),
    )
    multiply_inputs_to_socket(
        context,
        surface_node,
        principled,
        "thin_film_weight",
        "thin_film_thickness",
        ("Thin Film Thickness",),
        1.0,
        0.0,
    )

    for input_name, socket_names in {
        "base_diffuse_roughness": ("Diffuse Roughness",),
        "base_metalness": ("Metallic",),
        "specular_roughness": ("Roughness",),
        "specular_ior": ("IOR",),
        "specular_roughness_anisotropy": ("Anisotropic", "Specular Anisotropy"),
        "transmission_weight": ("Transmission Weight", "Transmission"),
        "subsurface_weight": ("Subsurface Weight", "Subsurface"),
        "subsurface_radius": ("Subsurface Scale",),
        "subsurface_scatter_anisotropy": ("Subsurface Anisotropy",),
        "fuzz_weight": ("Sheen Weight", "Sheen"),
        "fuzz_roughness": ("Sheen Roughness",),
        "coat_weight": ("Coat Weight", "Coat"),
        "coat_roughness": ("Coat Roughness",),
        "coat_ior": ("Coat IOR",),
        "thin_film_ior": ("Thin Film IOR",),
        "emission_luminance": ("Emission Strength",),
    }.items():
        connect_or_set_surface_input(context, surface_node, principled, input_name, socket_names, "scalar")

    for input_name, socket_names in {
        "fuzz_color": ("Sheen Tint", "Sheen Color"),
        "emission_color": ("Emission Color",),
    }.items():
        connect_or_set_surface_input(context, surface_node, principled, input_name, socket_names, "color")

    for input_name, socket_names in {
        "geometry_normal": ("Normal",),
        "geometry_coat_normal": ("Coat Normal",),
        "geometry_tangent": ("Tangent",),
    }.items():
        connect_or_set_surface_input(context, surface_node, principled, input_name, socket_names, "vector")

    apply_static_transmission_tint(context, surface_node, principled, "transmission_weight", "transmission_color")
    configure_transmission_material(context, surface_node, "transmission_weight")
    apply_opacity_input(context, surface_node, principled, "geometry_opacity", "BLEND")
    warn_unsupported_inputs(
        context,
        surface_node,
        {
            "transmission_depth",
            "transmission_scatter",
            "transmission_scatter_anisotropy",
            "coat_roughness_anisotropy",
        },
    )


def connect_or_set_surface_input(
    context: CompileContext,
    surface_node: Any,
    principled: bpy.types.Node,
    input_name: str,
    socket_names: tuple[str, ...],
    value_kind: str,
    *,
    connected_only: bool = False,
) -> None:
    input_element = get_input(surface_node, input_name)
    if input_element is None and get_declaration_input(surface_node, input_name) is None:
        return

    socket = principled_input(principled, socket_names)
    if socket is None:
        context.warnings.append(f"Blender Principled BSDF has no socket for MaterialX input: {input_name}")
        return

    if is_connected(input_element):
        compiled = compile_surface_input(context, input_element, input_name, surface_scope(surface_node))
        if compiled is None:
            return
        if value_kind == "scalar":
            source_socket = component_socket(context, compiled, 0)
        elif is_surface_direction_input(input_name):
            source_socket = materialx_direction_to_blender_world_socket(context, compiled).socket
        else:
            source_socket = compiled.socket
        context.material.node_tree.links.new(source_socket, socket)
        return

    if connected_only:
        return

    value = input_value_or_default(surface_node, input_name)
    if value is None:
        return
    if value_kind == "scalar":
        set_scalar_socket(principled, socket.name, parse_float(value))
    elif value_kind == "color":
        set_color_socket(principled, socket.name, parse_color(value))
    else:
        vector = parse_vector(value)
        if is_surface_direction_input(input_name):
            vector = materialx_direction_value_to_blender(tuple(vector))
        set_socket_default(socket, vector)


def is_surface_direction_input(input_name: str) -> bool:
    return input_name in {
        "normal",
        "coat_normal",
        "tangent",
        "geometry_normal",
        "geometry_coat_normal",
        "geometry_tangent",
    }


def connect_weighted_color_input(
    context: CompileContext,
    surface_node: Any,
    principled: bpy.types.Node,
    weight_name: str,
    color_name: str,
    socket_names: tuple[str, ...],
    default_weight: float,
    default_color: tuple[float, float, float, float],
) -> None:
    if not has_input_or_default(surface_node, weight_name) and not has_input_or_default(surface_node, color_name):
        return

    socket = principled_input(principled, socket_names)
    if socket is None:
        context.warnings.append(f"Blender Principled BSDF has no socket for weighted MaterialX input: {color_name}")
        return

    if is_static_input(surface_node, weight_name) and is_static_input(surface_node, color_name):
        weight = static_scalar_input(surface_node, weight_name, default_weight)
        color = static_color_input(surface_node, color_name, default_color)
        set_color_socket(principled, socket.name, (color[0] * weight, color[1] * weight, color[2] * weight, color[3]))
        return

    weight_socket = surface_input_or_default(context, surface_node, weight_name, default_weight, "float")
    color_socket = surface_input_or_default(context, surface_node, color_name, default_color, "color3")
    weighted_components = [
        math_socket(context, "MULTIPLY", component_socket(context, color_socket, index), component_socket(context, weight_socket, 0))
        for index in range(3)
    ]
    weighted_color = combine_components(context, weighted_components, "color3")
    context.material.node_tree.links.new(weighted_color.socket, socket)


def multiply_inputs_to_socket(
    context: CompileContext,
    surface_node: Any,
    principled: bpy.types.Node,
    left_name: str,
    right_name: str,
    socket_names: tuple[str, ...],
    default_left: float | tuple[float, ...],
    default_right: float | tuple[float, ...],
) -> None:
    if not has_input_or_default(surface_node, left_name) and not has_input_or_default(surface_node, right_name):
        return

    socket = principled_input(principled, socket_names)
    if socket is None:
        context.warnings.append(f"Blender Principled BSDF has no socket for multiplied MaterialX inputs: {left_name}, {right_name}")
        return

    if is_static_input(surface_node, left_name) and is_static_input(surface_node, right_name):
        left = static_value(surface_node, left_name, default_left)
        right = static_value(surface_node, right_name, default_right)
        set_socket_default(socket, multiply_static_values(left, right))
        return

    left_socket = surface_input_or_default(context, surface_node, left_name, default_left, default_type_for_value(default_left))
    right_socket = surface_input_or_default(context, surface_node, right_name, default_right, default_type_for_value(default_right))
    component_total = max(component_count_for_default(default_left), component_count_for_default(default_right))
    if component_total <= 1:
        multiplied = math_socket(context, "MULTIPLY", component_socket(context, left_socket, 0), component_socket(context, right_socket, 0))
        context.material.node_tree.links.new(multiplied, socket)
        return

    components = [
        math_socket(context, "MULTIPLY", component_socket(context, left_socket, index), component_socket(context, right_socket, index))
        for index in range(component_total)
    ]
    multiplied_vector = combine_components(context, components, default_type_for_component_count(component_total))
    context.material.node_tree.links.new(multiplied_vector.socket, socket)


def apply_static_transmission_tint(
    context: CompileContext,
    surface_node: Any,
    principled: bpy.types.Node,
    weight_name: str,
    color_name: str,
) -> None:
    if not is_static_input(surface_node, weight_name) or not is_static_input(surface_node, color_name):
        return

    weight = static_scalar_input(surface_node, weight_name, 0.0)
    if weight <= 0.0:
        return

    socket = principled_input(principled, ("Base Color",))
    if socket is None or len(socket.links) > 0:
        return

    tint = static_color_input(surface_node, color_name, (1.0, 1.0, 1.0, 1.0))
    current = tuple(socket.default_value)
    mixed = tuple(
        current[index] * (1.0 - weight) + tint[index] * weight
        for index in range(3)
    )
    set_color_socket(principled, socket.name, (mixed[0], mixed[1], mixed[2], current[3]))


def configure_transmission_material(context: CompileContext, surface_node: Any, input_name: str) -> None:
    input_element = get_input(surface_node, input_name)
    if input_element is None and get_declaration_input(surface_node, input_name) is None:
        return

    is_transmissive = is_connected(input_element) or static_scalar_input(surface_node, input_name, 0.0) > 0.0
    if not is_transmissive:
        return

    configure_alpha_material(context.material, "BLEND")


def principled_input(principled: bpy.types.Node, socket_names: tuple[str, ...]) -> bpy.types.NodeSocket | None:
    for socket_name in socket_names:
        socket = principled.inputs.get(socket_name)
        if socket is not None:
            return socket
    return None


def surface_scope(surface_node: Any) -> Any | None:
    parent = call_optional(surface_node, "getParent")
    return parent if category(parent) == "nodegraph" else None


def compile_surface_input(context: CompileContext, input_element: Any, input_name: str, scope: Any | None) -> CompiledSocket | None:
    compiled = context.compiler.compile_input(input_element, scope) if context.compiler is not None else None
    if isinstance(compiled, CompiledSocket):
        return compiled
    context.warnings.append(f"Unsupported connected surface input: {input_name}")
    return None


def surface_input_or_default(
    context: CompileContext,
    surface_node: Any,
    input_name: str,
    default: float | tuple[float, ...],
    default_type: str,
) -> CompiledSocket:
    input_element = get_input(surface_node, input_name)
    if input_element is not None and context.compiler is not None:
        compiled = context.compiler.compile_input(input_element, surface_scope(surface_node))
        if isinstance(compiled, CompiledSocket):
            return compiled
        if is_connected(input_element):
            context.warnings.append(f"Unsupported connected surface input: {input_name}")
    value = input_value_or_default(surface_node, input_name)
    if value is not None:
        return constant_socket(context, value, input_type_or_default(surface_node, input_name) or default_type)
    return constant_socket(context, default, default_type)


def is_static_input(surface_node: Any, input_name: str) -> bool:
    input_element = get_input(surface_node, input_name)
    return input_element is None or not is_connected(input_element)


def has_input_or_default(surface_node: Any, input_name: str) -> bool:
    return get_input(surface_node, input_name) is not None or get_declaration_input(surface_node, input_name) is not None


def static_scalar_input(surface_node: Any, input_name: str, default: float) -> float:
    value = input_value_or_default(surface_node, input_name)
    return default if value is None else parse_float(value)


def static_color_input(
    surface_node: Any,
    input_name: str,
    default: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    value = input_value_or_default(surface_node, input_name)
    return default if value is None else parse_color(value)


def static_value(surface_node: Any, input_name: str, default: float | tuple[float, ...]) -> float | tuple[float, ...]:
    value = input_value_or_default(surface_node, input_name)
    if value is None:
        return default
    if isinstance(default, tuple):
        parsed = parse_vector(value)
        return tuple(parsed[index] if index < len(parsed) else parsed[-1] for index in range(len(default)))
    return parse_float(value)


def multiply_static_values(
    left: float | tuple[float, ...],
    right: float | tuple[float, ...],
) -> float | tuple[float, ...]:
    if not isinstance(left, tuple) and not isinstance(right, tuple):
        return left * right
    component_total = max(component_count_for_default(left), component_count_for_default(right))
    left_values = left if isinstance(left, tuple) else tuple(left for _ in range(component_total))
    right_values = right if isinstance(right, tuple) else tuple(right for _ in range(component_total))
    component_total = max(len(left_values), len(right_values))
    return tuple(
        left_values[min(index, len(left_values) - 1)] * right_values[min(index, len(right_values) - 1)]
        for index in range(component_total)
    )


def component_count_for_default(value: float | tuple[float, ...]) -> int:
    return len(value) if isinstance(value, tuple) else 1


def default_type_for_component_count(component_total: int) -> str:
    return "vector2" if component_total == 2 else "vector3"


def warn_unsupported_inputs(context: CompileContext, surface_node: Any, input_names: set[str]) -> None:
    for input_name in sorted(input_names):
        if get_input(surface_node, input_name) is not None:
            context.warnings.append(f"Unsupported {category(surface_node)} input: {input_name}")


def apply_gltf_alpha_inputs(context: CompileContext, surface_node: Any, principled: bpy.types.Node) -> None:
    alpha_mode_value = input_value(get_input(surface_node, "alpha_mode"))
    alpha_mode = int(round(parse_float(alpha_mode_value))) if alpha_mode_value is not None else 2
    if alpha_mode == 0:
        return

    blend_method = "CLIP" if alpha_mode == 1 else "BLEND"
    if alpha_mode == 1:
        alpha_cutoff_value = input_value(get_input(surface_node, "alpha_cutoff"))
        if alpha_cutoff_value is not None and hasattr(context.material, "alpha_threshold"):
            context.material.alpha_threshold = parse_float(alpha_cutoff_value)
        elif hasattr(context.material, "alpha_threshold"):
            context.material.alpha_threshold = 0.5

    apply_opacity_input(context, surface_node, principled, "alpha", blend_method)


def apply_opacity_input(
    context: CompileContext,
    surface_node: Any,
    principled: bpy.types.Node,
    input_name: str,
    blend_method: str,
) -> None:
    opacity = get_input(surface_node, input_name)
    if opacity is None and get_declaration_input(surface_node, input_name) is None:
        return

    if is_connected(opacity):
        socket = principled.inputs.get("Alpha")
        compiled = compile_surface_input(context, opacity, input_name, surface_scope(surface_node))
        if socket is not None and compiled is not None:
            source_socket = component_socket(context, compiled, 0)
            context.material.node_tree.links.new(source_socket, socket)
            configure_alpha_material(context.material, blend_method)
        else:
            context.warnings.append(f"Unsupported connected {input_name} input.")
        return

    value = input_value_or_default(surface_node, input_name)
    if value is None:
        return
    alpha = parse_color(value)[0]
    set_scalar_socket(principled, "Alpha", alpha)
    if alpha < 1.0:
        configure_alpha_material(context.material, blend_method)


def configure_alpha_material(material: bpy.types.Material, blend_method: str) -> None:
    set_alpha_render_method(material, blend_method)
    if hasattr(material, "use_screen_refraction"):
        material.use_screen_refraction = True


def set_alpha_render_method(material: bpy.types.Material, blend_method: str) -> None:
    if hasattr(material, "surface_render_method"):
        # Blender 4.2+ replaces blend_method with surface_render_method. It no longer has
        # an exact alpha-clip mode, so dithered rendering is the closest material setting.
        render_methods = ("DITHERED", "BLENDED") if blend_method == "CLIP" else ("BLENDED",)
        for render_method in render_methods:
            try:
                material.surface_render_method = render_method
                return
            except (AttributeError, TypeError, ValueError):
                pass

    try:
        material.blend_method = blend_method
    except (AttributeError, TypeError, ValueError):
        pass


def get_principled_node(material: bpy.types.Material) -> bpy.types.Node | None:
    nodes = material.node_tree.nodes
    for node in nodes:
        if node.type == "BSDF_PRINCIPLED":
            return node
    return None


def create_fallback_material(name: str) -> bpy.types.Material:
    material = bpy.data.materials.new(name=name)
    material.use_nodes = True
    principled = get_principled_node(material)
    if principled is not None:
        set_color_socket(principled, "Base Color", (1.0, 0.0, 1.0, 1.0))
        set_scalar_socket(principled, "Roughness", 0.5)
    return material
