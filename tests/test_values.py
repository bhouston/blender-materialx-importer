from __future__ import annotations

from pathlib import Path

from materialx_importer.values import (
    identity_matrix_values,
    parse_bool_float,
    parse_color,
    parse_float,
    parse_float_sequence,
    parse_matrix,
    parse_vector,
    resolve_asset_path,
    safe_name,
)


def test_parse_float_accepts_scalars_and_comma_values() -> None:
    assert parse_float(3) == 3.0
    assert parse_float("1.5, 2.0") == 1.5
    assert parse_float("not-a-number") == 0.0


def test_parse_bool_float_accepts_materialx_booleans() -> None:
    assert parse_bool_float(True) == 1.0
    assert parse_bool_float(False) == 0.0
    assert parse_bool_float("true") == 1.0
    assert parse_bool_float("false") == 0.0


def test_parse_vector_expands_short_values() -> None:
    assert parse_vector("0.25") == [0.25, 0.25, 0.25]
    assert parse_vector("0.25, 0.5") == [0.25, 0.5, 0.0]
    assert parse_vector("0.25, 0.5, 0.75, 1.0") == [0.25, 0.5, 0.75]


def test_parse_color_expands_alpha() -> None:
    assert parse_color("0.25") == (0.25, 0.25, 0.25, 1.0)
    assert parse_color("0.25, 0.5, 0.75") == (0.25, 0.5, 0.75, 1.0)
    assert parse_color((0.25, 0.5, 0.75, 0.8)) == (0.25, 0.5, 0.75, 0.8)


def test_parse_matrix_uses_materialx_column_major_order() -> None:
    assert identity_matrix_values(2) == [[1.0, 0.0], [0.0, 1.0]]
    assert parse_float_sequence("1 2, 3 4") == [1.0, 2.0, 3.0, 4.0]
    assert parse_matrix("1 2 3 4", 2) == [[1.0, 3.0], [2.0, 4.0]]
    assert parse_matrix("1 2 3", 2) == [[1.0, 0.0], [0.0, 1.0]]


def test_safe_name_and_asset_resolution() -> None:
    assert safe_name("Material X/Test") == "Material_X_Test"
    assert resolve_asset_path(Path("/materials"), "textures/base.png") == Path("/materials/textures/base.png")
