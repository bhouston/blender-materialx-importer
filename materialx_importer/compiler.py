from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from .blender_nodes import combine_components, component_socket, constant_socket
from .document import attribute, category, connected_node, get_input, get_output, input_value, type_name
from .nodes import register_all
from .nodes.geometry import compile_geometry_category
from .types import CompileContext, CompiledMatrix, CompiledSocket, CompiledValue
from .values import COMPONENT_TYPES, component_count

NodeHandler = Callable[[CompileContext, Any, str, Any | None], CompiledValue | None]


class NodeRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, NodeHandler] = {}

    def register(self, category_name: str, handler: NodeHandler) -> None:
        self._handlers[category_name] = handler

    def register_many(self, category_names: set[str], handler: NodeHandler) -> None:
        for category_name in category_names:
            self.register(category_name, handler)

    def register_categories(self, category_names: Iterable[str], handler: NodeHandler) -> None:
        for category_name in category_names:
            self.register(category_name, handler)

    def handler_for(self, category_name: str) -> NodeHandler | None:
        return self._handlers.get(category_name)


def create_default_registry() -> NodeRegistry:
    registry = NodeRegistry()
    register_all(registry)
    return registry


class GraphCompiler:
    def __init__(self, context: CompileContext, registry: NodeRegistry | None = None) -> None:
        self.context = context
        self.registry = registry or create_default_registry()
        self.context.compiler = self

    def compile_input(self, input_element: Any, scope: Any | None = None) -> CompiledValue | None:
        nodegraph_name = attribute(input_element, "nodegraph")
        if nodegraph_name:
            nodegraph = self.context.document.getChild(nodegraph_name)
            if nodegraph is None:
                self.context.warnings.append(f"Nodegraph not found: {nodegraph_name}")
                return None
            output = get_output(nodegraph, attribute(input_element, "output") or "out")
            if output is None:
                self.context.warnings.append(f"Output not found on nodegraph {nodegraph_name}.")
                return None
            return self.compile_input(output, nodegraph)

        interface_name = attribute(input_element, "interfacename")
        if interface_name and scope is not None:
            interface_input = get_input(scope, interface_name)
            if interface_input is None:
                self.context.warnings.append(f"Interface input not found on {scope.getName()}: {interface_name}")
                return None
            return self.compile_input(interface_input, scope)

        connected = connected_node(self.context.document, input_element, scope=scope)
        if connected is not None:
            return self.compile_node(connected, attribute(input_element, "output") or "out", scope)

        value = input_value(input_element)
        if value is None:
            return None
        return constant_socket(self.context, value, type_name(input_element))

    def compile_node(self, node: Any, output_name: str = "out", scope: Any | None = None) -> CompiledValue | None:
        key = self._cache_key(node, output_name, scope)
        cached = self.context.cache.get(key)
        if cached is not None:
            return cached

        node_category = category(node)
        node_type = type_name(node)

        if node_category == "constant":
            source = get_input(node, "value")
            compiled = self.compile_input(source, scope) if source is not None else None
        elif node_category == "convert":
            compiled = self._compile_convert(node, scope)
        else:
            handler = self.registry.handler_for(node_category)
            if handler is None:
                raise RuntimeError(f"Unsupported MaterialX node category: {node_category}")
            compiled = handler(self.context, node, output_name, scope)

        if compiled is None:
            node_name = getattr(node, "getName", lambda: "")()
            label = f"{node_category} ({node_name})" if node_name else node_category
            raise RuntimeError(f"Failed to compile MaterialX node: {label}")

        if not compiled.type_name:
            compiled.type_name = node_type
        self.context.cache[key] = compiled
        return compiled

    def compile_geometry(self, category_name: str) -> CompiledValue | None:
        return compile_geometry_category(self.context, category_name)

    def _compile_convert(self, node: Any, scope: Any | None) -> CompiledValue | None:
        source_input = get_input(node, "in")
        compiled = self.compile_input(source_input, scope) if source_input is not None else None
        if compiled is None:
            return None

        output_type = type_name(node) or compiled.type_name
        if isinstance(compiled, CompiledMatrix):
            if output_type == compiled.type_name:
                return compiled
            raise RuntimeError(f"Unsupported MaterialX convert from {compiled.type_name} to {output_type}")

        if not isinstance(compiled, CompiledSocket):
            return None

        if output_type == compiled.type_name:
            return compiled
        if output_type in COMPONENT_TYPES:
            components = [component_socket(self.context, compiled, index) for index in range(component_count(output_type))]
            return combine_components(self.context, components, output_type)
        if output_type in {"float", "integer", "boolean"}:
            return CompiledSocket(component_socket(self.context, compiled, 0), output_type)
        raise RuntimeError(f"Unsupported MaterialX convert from {compiled.type_name} to {output_type}")

    def _cache_key(self, node: Any, output_name: str, scope: Any | None) -> tuple[str, str, str]:
        return (_stable_element_name(node), output_name, _stable_element_name(scope) if scope is not None else "")


def _stable_element_name(element: Any) -> str:
    for method_name in ("getNamePath", "getName"):
        method = getattr(element, method_name, None)
        if method is None:
            continue
        try:
            value = method()
        except Exception:
            continue
        if value:
            return str(value)
    return str(id(element))
