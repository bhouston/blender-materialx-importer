from __future__ import annotations

from typing import Any

from ..blender_nodes import (
    alpha_socket,
    apply_gamma,
    clamp01_component,
    clamp_component,
    combine_components,
    component_binary_math,
    component_socket,
    constant_socket,
    input_socket,
    luminance_component,
    math_socket,
    matrix_row_socket,
    mix_component,
    polynomial_socket,
    step_component,
)
from ..document import type_name
from ..types import CompileContext, CompiledSocket
from ..values import component_count


def register(registry) -> None:
    registry.register("saturate", compile_saturate)
    registry.register("luminance", compile_luminance)
    registry.register("contrast", compile_contrast)
    registry.register("rgbtohsv", compile_rgbtohsv)
    registry.register("hsvtorgb", compile_hsvtorgb)
    registry.register("unpremult", compile_unpremult)
    registry.register("colorcorrect", compile_colorcorrect)
    registry.register("blackbody", compile_blackbody)


def compile_saturate(context: CompileContext, node: Any, output_name: str, scope: Any | None) -> CompiledSocket | None:
    output_type = type_name(node) or "color3"
    source = input_socket(context, node, "in", (0.0, 0.0, 0.0), scope)
    amount = input_socket(context, node, "amount", 1.0, scope)
    coeffs = input_socket(context, node, "lumacoeffs", (0.2722287, 0.6740818, 0.0536895), scope)
    luminance = luminance_component(context, source, coeffs)
    components = [
        mix_component(context, luminance, component_socket(context, source, index), amount.socket)
        for index in range(component_count(output_type))
    ]
    return combine_components(context, components, output_type)


def compile_luminance(context: CompileContext, node: Any, output_name: str, scope: Any | None) -> CompiledSocket | None:
    output_type = type_name(node) or "color3"
    source = input_socket(context, node, "in", (0.0, 0.0, 0.0), scope)
    coeffs = input_socket(context, node, "lumacoeffs", (0.2722287, 0.6740818, 0.0536895), scope)
    luminance = luminance_component(context, source, coeffs)
    return combine_components(context, [luminance for _ in range(component_count(output_type))], output_type)


def compile_contrast(context: CompileContext, node: Any, output_name: str, scope: Any | None) -> CompiledSocket | None:
    output_type = type_name(node) or "float"
    source = input_socket(context, node, "in", 0.0, scope)
    amount = input_socket(context, node, "amount", 1.0, scope)
    pivot = input_socket(context, node, "pivot", 0.5, scope)
    components = []
    for index in range(component_count(output_type)):
        centered = math_socket(
            context,
            "SUBTRACT",
            component_socket(context, source, index),
            component_socket(context, pivot, index),
        )
        scaled = math_socket(context, "MULTIPLY", centered, component_socket(context, amount, index))
        components.append(math_socket(context, "ADD", scaled, component_socket(context, pivot, index)))
    return combine_components(context, components, output_type)


def compile_rgbtohsv(context: CompileContext, node: Any, output_name: str, scope: Any | None) -> CompiledSocket | None:
    source = input_socket(context, node, "in", (0.0, 0.0, 0.0), scope)
    red = component_socket(context, source, 0)
    green = component_socket(context, source, 1)
    blue = component_socket(context, source, 2)
    min_comp = math_socket(context, "MINIMUM", red, math_socket(context, "MINIMUM", green, blue))
    max_comp = math_socket(context, "MAXIMUM", red, math_socket(context, "MAXIMUM", green, blue))
    delta = math_socket(context, "SUBTRACT", max_comp, min_comp)
    safe_delta = math_socket(context, "MAXIMUM", delta, constant_socket(context, 1e-6, "float").socket)
    saturation = math_socket(
        context,
        "MULTIPLY",
        math_socket(context, "DIVIDE", delta, math_socket(context, "MAXIMUM", max_comp, constant_socket(context, 1e-6, "float").socket)),
        step_component(context, constant_socket(context, 1e-6, "float").socket, max_comp),
    )

    hue_r = math_socket(context, "DIVIDE", math_socket(context, "SUBTRACT", green, blue), safe_delta)
    hue_g = math_socket(
        context,
        "ADD",
        constant_socket(context, 2.0, "float").socket,
        math_socket(context, "DIVIDE", math_socket(context, "SUBTRACT", blue, red), safe_delta),
    )
    hue_b = math_socket(
        context,
        "ADD",
        constant_socket(context, 4.0, "float").socket,
        math_socket(context, "DIVIDE", math_socket(context, "SUBTRACT", red, green), safe_delta),
    )
    g_is_max = step_component(context, red, green)
    b_is_max = step_component(context, math_socket(context, "MAXIMUM", red, green), blue)
    hue_rg = mix_component(context, hue_r, hue_g, g_is_max)
    hue_raw = mix_component(context, hue_rg, hue_b, b_is_max)
    hue = math_socket(context, "DIVIDE", hue_raw, constant_socket(context, 6.0, "float").socket)
    hue_negative = context.material.node_tree.nodes.new(type="ShaderNodeMath")
    hue_negative.operation = "LESS_THAN"
    context.material.node_tree.links.new(hue, hue_negative.inputs[0])
    hue_negative.inputs[1].default_value = 0.0
    hue = math_socket(context, "ADD", hue, hue_negative.outputs[0])
    hue = math_socket(context, "MULTIPLY", hue, step_component(context, constant_socket(context, 1e-6, "float").socket, delta))
    return combine_components(context, [hue, saturation, max_comp], type_name(node) or "color3")


def compile_hsvtorgb(context: CompileContext, node: Any, output_name: str, scope: Any | None) -> CompiledSocket | None:
    source = input_socket(context, node, "in", (0.0, 0.0, 0.0), scope)
    hue = component_socket(context, source, 0)
    saturation = component_socket(context, source, 1)
    value = component_socket(context, source, 2)
    components = [
        hsv_channel_socket(context, hue, saturation, value, 1.0),
        hsv_channel_socket(context, hue, saturation, value, 2.0 / 3.0),
        hsv_channel_socket(context, hue, saturation, value, 1.0 / 3.0),
    ]
    return combine_components(context, components, type_name(node) or "color3")


def hsv_channel_socket(
    context: CompileContext,
    hue: Any,
    saturation: Any,
    value: Any,
    offset: float,
) -> Any:
    hue_offset = math_socket(context, "ADD", hue, constant_socket(context, offset, "float").socket)
    wrapped = math_socket(context, "FRACT", hue_offset, None)
    scaled = math_socket(context, "MULTIPLY", wrapped, constant_socket(context, 6.0, "float").socket)
    centered = math_socket(context, "SUBTRACT", scaled, constant_socket(context, 3.0, "float").socket)
    triangle = math_socket(context, "SUBTRACT", math_socket(context, "ABSOLUTE", centered, None), constant_socket(context, 1.0, "float").socket)
    chroma = clamp01_component(context, triangle)
    mixed = mix_component(context, constant_socket(context, 1.0, "float").socket, chroma, saturation)
    return math_socket(context, "MULTIPLY", value, mixed)


def compile_unpremult(context: CompileContext, node: Any, output_name: str, scope: Any | None) -> CompiledSocket | None:
    source = input_socket(context, node, "in", (0.0, 0.0, 0.0, 1.0), scope)
    alpha = alpha_socket(context, source)
    nonzero_alpha = step_component(context, constant_socket(context, 1e-6, "float").socket, alpha)
    safe_alpha = math_socket(context, "MAXIMUM", alpha, constant_socket(context, 1e-6, "float").socket)
    components = []
    for index in range(3):
        channel = component_socket(context, source, index)
        divided = math_socket(context, "DIVIDE", channel, safe_alpha)
        components.append(mix_component(context, channel, divided, nonzero_alpha))
    return combine_components(context, components, type_name(node) or "color4")


def compile_colorcorrect(context: CompileContext, node: Any, output_name: str, scope: Any | None) -> CompiledSocket | None:
    source = input_socket(context, node, "in", (1.0, 1.0, 1.0), scope)
    hue = input_socket(context, node, "hue", 0.0, scope)
    saturation = input_socket(context, node, "saturation", 1.0, scope)
    gamma = input_socket(context, node, "gamma", 1.0, scope)
    lift = input_socket(context, node, "lift", 0.0, scope)
    gain = input_socket(context, node, "gain", 1.0, scope)
    contrast = input_socket(context, node, "contrast", 1.0, scope)
    contrast_pivot = input_socket(context, node, "contrastpivot", 0.5, scope)
    exposure = input_socket(context, node, "exposure", 0.0, scope)

    hue_node = context.material.node_tree.nodes.new(type="ShaderNodeHueSaturation")
    context.material.node_tree.links.new(source.socket, hue_node.inputs["Color"])
    context.material.node_tree.links.new(
        math_socket(context, "ADD", hue.socket, constant_socket(context, 0.5, "float").socket),
        hue_node.inputs["Hue"],
    )
    context.material.node_tree.links.new(saturation.socket, hue_node.inputs["Saturation"])
    hue_node.inputs["Value"].default_value = 1.0
    hue_node.inputs["Fac"].default_value = 1.0
    adjusted = CompiledSocket(hue_node.outputs["Color"], "color3")

    exposure_scale = math_socket(context, "POWER", constant_socket(context, 2.0, "float").socket, exposure.socket)
    components = []
    for index in range(component_count(type_name(node) or "color3")):
        channel = component_socket(context, adjusted, index)
        gamma_channel = apply_gamma(context, channel, gamma.socket)
        lifted = math_socket(
            context,
            "ADD",
            math_socket(
                context,
                "MULTIPLY",
                gamma_channel,
                math_socket(context, "SUBTRACT", constant_socket(context, 1.0, "float").socket, lift.socket),
            ),
            lift.socket,
        )
        gained = math_socket(context, "MULTIPLY", lifted, gain.socket)
        contrasted = math_socket(
            context,
            "ADD",
            math_socket(
                context,
                "MULTIPLY",
                math_socket(context, "SUBTRACT", gained, contrast_pivot.socket),
                contrast.socket,
            ),
            contrast_pivot.socket,
        )
        components.append(math_socket(context, "MULTIPLY", contrasted, exposure_scale))
    return combine_components(context, components, type_name(node) or "color3")


def compile_blackbody(context: CompileContext, node: Any, output_name: str, scope: Any | None) -> CompiledSocket | None:
    temperature = input_socket(context, node, "temperature", 5000.0, scope).socket
    temperature = clamp_component(
        context,
        temperature,
        constant_socket(context, 800.0, "float").socket,
        constant_socket(context, 25000.0, "float").socket,
    )
    t = math_socket(context, "DIVIDE", constant_socket(context, 1000.0, "float").socket, temperature)
    t2 = math_socket(context, "MULTIPLY", t, t)
    t3 = math_socket(context, "MULTIPLY", t2, t)
    low_x = polynomial_socket(context, t, t2, t3, (-0.2661239, -0.2343580, 0.8776956, 0.179910))
    high_x = polynomial_socket(context, t, t2, t3, (-3.0258469, 2.1070379, 0.2226347, 0.240390))
    xc = mix_component(context, low_x, high_x, step_component(context, constant_socket(context, 4000.0, "float").socket, temperature))
    xc2 = math_socket(context, "MULTIPLY", xc, xc)
    xc3 = math_socket(context, "MULTIPLY", xc2, xc)
    yc_low = polynomial_socket(context, xc, xc2, xc3, (-1.1063814, -1.34811020, 2.18555832, -0.20219683))
    yc_mid = polynomial_socket(context, xc, xc2, xc3, (-0.9549476, -1.37418593, 2.09137015, -0.16748867))
    yc_high = polynomial_socket(context, xc, xc2, xc3, (3.0817580, -5.87338670, 3.75112997, -0.37001483))
    yc_low_mid = mix_component(context, yc_low, yc_mid, step_component(context, constant_socket(context, 2222.0, "float").socket, temperature))
    yc = mix_component(context, yc_low_mid, yc_high, step_component(context, constant_socket(context, 4000.0, "float").socket, temperature))
    safe_yc = math_socket(context, "MAXIMUM", yc, constant_socket(context, 1e-6, "float").socket)
    x_xyz = math_socket(context, "DIVIDE", xc, safe_yc)
    y_xyz = constant_socket(context, 1.0, "float").socket
    z_xyz = math_socket(
        context,
        "DIVIDE",
        math_socket(
            context,
            "SUBTRACT",
            math_socket(context, "SUBTRACT", constant_socket(context, 1.0, "float").socket, xc),
            yc,
        ),
        safe_yc,
    )
    red = matrix_row_socket(context, (3.2406, -1.5372, -0.4986), (x_xyz, y_xyz, z_xyz))
    green = matrix_row_socket(context, (-0.9689, 1.8758, 0.0415), (x_xyz, y_xyz, z_xyz))
    blue = matrix_row_socket(context, (0.0557, -0.2040, 1.0570), (x_xyz, y_xyz, z_xyz))
    zero = constant_socket(context, 0.0, "float").socket
    return combine_components(
        context,
        [
            math_socket(context, "MAXIMUM", red, zero),
            math_socket(context, "MAXIMUM", green, zero),
            math_socket(context, "MAXIMUM", blue, zero),
        ],
        "color3",
    )
