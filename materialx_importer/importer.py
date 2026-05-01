from __future__ import annotations

from pathlib import Path

import bpy

from .compiler import GraphCompiler
from .document import create_document, find_surface_shader, read_xml_file
from .surfaces import apply_surface_inputs, create_fallback_material, get_principled_node
from .types import CompileContext, MaterialImportResult
from .values import safe_name


def load_materialx_as_blender_material(mtlx_path: str) -> MaterialImportResult:
    document = create_document()
    read_xml_file(document, mtlx_path)

    warnings: list[str] = []
    surface_node = find_surface_shader(document)
    if surface_node is None:
        warnings.append("No supported standard_surface, gltf_pbr, or open_pbr_surface node found; using fallback material.")
        return MaterialImportResult(create_fallback_material("MaterialX_Fallback"), warnings)

    material_name = safe_name(surface_node.getName() or Path(mtlx_path).stem)
    material = bpy.data.materials.new(name=material_name)
    material.use_nodes = True
    principled = get_principled_node(material)
    if principled is None:
        warnings.append("Unable to find Blender Principled BSDF node; using fallback material.")
        return MaterialImportResult(material, warnings)

    base_dir = Path(mtlx_path).resolve().parent
    context = CompileContext(document=document, material=material, base_dir=base_dir, warnings=warnings)
    GraphCompiler(context)
    apply_surface_inputs(context, surface_node, principled)
    return MaterialImportResult(material, warnings)
