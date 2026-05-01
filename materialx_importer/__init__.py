from __future__ import annotations

from typing import TYPE_CHECKING

__all__ = ["MaterialImportResult", "load_materialx_as_blender_material"]

if TYPE_CHECKING:
    from .importer import load_materialx_as_blender_material
    from .types import MaterialImportResult


def __getattr__(name: str):
    if name == "load_materialx_as_blender_material":
        from .importer import load_materialx_as_blender_material

        return load_materialx_as_blender_material
    if name == "MaterialImportResult":
        from .types import MaterialImportResult

        return MaterialImportResult
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
