from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import bpy


@dataclass
class MaterialImportResult:
    material: bpy.types.Material
    warnings: list[str] = field(default_factory=list)


@dataclass
class CompiledSocket:
    socket: bpy.types.NodeSocket
    type_name: str
    semantic: str | None = None
    components: list[bpy.types.NodeSocket] | None = None


@dataclass
class CompiledMatrix:
    size: int
    rows: list[list[bpy.types.NodeSocket]]
    type_name: str
    values: list[list[float]] | None = None


CompiledValue = CompiledSocket | CompiledMatrix


@dataclass
class CompileContext:
    document: Any
    material: bpy.types.Material
    base_dir: Path
    warnings: list[str]
    cache: dict[tuple[str, str, str], CompiledValue] = field(default_factory=dict)
    fallback_warnings: set[str] = field(default_factory=set)
    compiler: Any | None = None
