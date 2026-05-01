from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from .document import input_value_or_default


COMPONENT_TYPES = {"color3", "color4", "vector2", "vector3", "vector4"}
MATRIX_TYPES = {"matrix33": 3, "matrix44": 4}


def parse_float(value: Any) -> float:
    if isinstance(value, (float, int)):
        return float(value)
    try:
        return float(str(value).split(",")[0].strip())
    except ValueError:
        return 0.0


def parse_bool_float(value: Any) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    text = str(value).strip().lower()
    if text in {"true", "1"}:
        return 1.0
    if text in {"false", "0"}:
        return 0.0
    return parse_float(value)


def static_int_input(node: Any, name: str, default: int) -> int:
    value = input_value_or_default(node, name)
    if value is None:
        return default
    return int(parse_float(value))


def static_bool_input(node: Any, name: str, default: bool) -> bool:
    value = input_value_or_default(node, name)
    if value is None:
        return default
    return parse_bool_float(value) != 0.0


def parse_vector(value: Any) -> list[float]:
    if isinstance(value, (float, int, bool)):
        scalar = parse_bool_float(value)
        return [scalar, scalar, scalar]
    if isinstance(value, (list, tuple)):
        pieces = [float(piece) for piece in value]
    else:
        pieces = [float(piece.strip()) for piece in str(value).split(",") if piece.strip()]
    if not pieces:
        return [0.0, 0.0, 0.0]
    if len(pieces) == 1:
        return [pieces[0], pieces[0], pieces[0]]
    if len(pieces) == 2:
        return [pieces[0], pieces[1], 0.0]
    return pieces[:3]


def parse_float_sequence(value: Any) -> list[float]:
    if isinstance(value, (float, int, bool)):
        return [parse_bool_float(value)]
    if isinstance(value, (list, tuple)):
        return [float(piece) for piece in value]
    pieces = []
    for piece in re.split(r"[,\s]+", str(value).strip()):
        if piece:
            pieces.append(float(piece))
    return pieces


def identity_matrix_values(size: int) -> list[list[float]]:
    return [[1.0 if row == column else 0.0 for column in range(size)] for row in range(size)]


def parse_matrix(value: Any, size: int) -> list[list[float]]:
    pieces = parse_float_sequence(value)
    expected = size * size
    if len(pieces) != expected:
        return identity_matrix_values(size)
    return [[pieces[column * size + row] for column in range(size)] for row in range(size)]


def matrix_size(type_name: str | None) -> int | None:
    return MATRIX_TYPES.get(type_name or "")


def component_count(type_name: str) -> int:
    if type_name in {"color3", "vector3", "color4", "vector4"}:
        return 3
    if type_name == "vector2":
        return 2
    return 1


def parse_color(value: Any) -> tuple[float, float, float, float]:
    if isinstance(value, (list, tuple)):
        pieces = [float(piece) for piece in value]
    else:
        pieces = [float(piece.strip()) for piece in str(value).split(",") if piece.strip()]
    if len(pieces) == 0:
        return (0.0, 0.0, 0.0, 1.0)
    if len(pieces) == 1:
        return (pieces[0], pieces[0], pieces[0], 1.0)
    if len(pieces) == 2:
        return (pieces[0], pieces[1], 0.0, 1.0)
    if len(pieces) == 3:
        return (pieces[0], pieces[1], pieces[2], 1.0)
    return (pieces[0], pieces[1], pieces[2], pieces[3])


def default_component_value(type_name: str, value: float) -> float | tuple[float, ...]:
    count = component_count(type_name)
    if count == 1:
        return value
    if type_name in {"color4", "vector4"}:
        return (value, value, value, value)
    return tuple(value for _ in range(count))


def default_type_for_value(value: Any) -> str:
    if isinstance(value, tuple):
        if len(value) == 2:
            return "vector2"
        if len(value) == 4:
            return "color4"
        if len(value) == 3:
            return "vector3"
    return "float"


def resolve_asset_path(base_dir: Path, value: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate
    return (base_dir / candidate).resolve()


def safe_name(value: str) -> str:
    return "".join(character if character.isalnum() or character in "_-" else "_" for character in value)
