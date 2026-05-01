from __future__ import annotations

from typing import Any

try:
    import MaterialX as mx
except ImportError as exc:  # pragma: no cover - exercised inside Blender prerequisite checks.
    raise RuntimeError("Blender's bundled MaterialX Python module is required.") from exc


def create_document() -> Any:
    document = mx.createDocument()
    load_standard_libraries(document)
    return document


def load_standard_libraries(document: Any) -> None:
    libraries = mx.createDocument()
    search_path = mx.getDefaultDataSearchPath()
    library_folders = mx.getDefaultDataLibraryFolders()
    mx.loadLibraries(library_folders, search_path, libraries)
    document.importLibrary(libraries)


def read_xml_file(document: Any, mtlx_path: str) -> None:
    mx.readFromXmlFile(document, mtlx_path)


def find_surface_shader(document: Any) -> Any | None:
    material_nodes = call_list(document, "getMaterialNodes")
    for material_node in material_nodes:
        surface_input = get_input(material_node, "surfaceshader")
        if surface_input is None:
            continue
        surface_node = connected_node(document, surface_input)
        if surface_node is not None and category(surface_node) in {"standard_surface", "gltf_pbr", "open_pbr_surface"}:
            return surface_node

    for node in call_list(document, "getNodes"):
        if category(node) in {"standard_surface", "gltf_pbr", "open_pbr_surface"}:
            return node
    return None


def connected_node(document: Any, input_element: Any, scope: Any | None = None) -> Any | None:
    node_name = attribute(input_element, "nodename")
    if not node_name:
        return None
    parent = scope if scope is not None else document
    node = parent.getChild(node_name)
    if node is not None:
        return node
    return document.getChild(node_name)


def get_input(node: Any, name: str) -> Any | None:
    try:
        return node.getInput(name)
    except AttributeError:
        for input_element in call_list(node, "getInputs"):
            if input_element.getName() == name:
                return input_element
    return None


def get_declaration_input(node: Any, name: str) -> Any | None:
    declaration = call_optional(node, "getDeclaration")
    return find_inherited_input(declaration, name)


def find_inherited_input(interface: Any | None, name: str, visited: set[int] | None = None) -> Any | None:
    if interface is None:
        return None
    visited = visited or set()
    interface_id = id(interface)
    if interface_id in visited:
        return None
    visited.add(interface_id)

    input_element = get_input(interface, name)
    if input_element is not None:
        return input_element

    inherited = call_optional(interface, "getInheritsFrom")
    return find_inherited_input(inherited, name, visited)


def input_value_or_default(node: Any, name: str) -> str | None:
    input_element = get_input(node, name)
    value = input_value(input_element)
    if value is not None:
        return value
    return input_value(get_declaration_input(node, name))


def input_type_or_default(node: Any, name: str) -> str:
    input_element = get_input(node, name)
    value_type = type_name(input_element)
    if value_type:
        return value_type
    return type_name(get_declaration_input(node, name))


def get_output(node: Any, name: str) -> Any | None:
    try:
        return node.getOutput(name)
    except AttributeError:
        for output_element in call_list(node, "getOutputs"):
            if output_element.getName() == name:
                return output_element
    return None


def input_value(input_element: Any | None) -> str | None:
    if input_element is None:
        return None
    value = attribute(input_element, "value")
    if value is not None:
        return value
    try:
        value_string = input_element.getValueString()
    except Exception:
        return None
    return value_string if value_string else None


def attribute(element: Any, name: str) -> str | None:
    try:
        value = element.getAttribute(name)
    except Exception:
        return None
    return value if value else None


def category(element: Any) -> str:
    try:
        return element.getCategory()
    except Exception:
        return ""


def type_name(element: Any | None) -> str:
    if element is None:
        return ""
    try:
        value = element.getType()
    except Exception:
        return ""
    return value if value else ""


def call_list(element: Any, method_name: str) -> list[Any]:
    method = getattr(element, method_name, None)
    if method is None:
        return []
    try:
        return list(method())
    except Exception:
        return []


def call_optional(element: Any | None, method_name: str) -> Any | None:
    if element is None:
        return None
    method = getattr(element, method_name, None)
    if method is None:
        return None
    try:
        return method()
    except Exception:
        return None


def is_connected(input_element: Any) -> bool:
    return bool(attribute(input_element, "nodename") or attribute(input_element, "nodegraph"))
