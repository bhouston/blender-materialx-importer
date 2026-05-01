from __future__ import annotations

from materialx_importer.nodes.noise import noise_detail_from_mx_octaves


def test_noise_detail_from_mx_octaves_matches_blender_fbm_semantics() -> None:
    assert noise_detail_from_mx_octaves(0) == 0.0
    assert noise_detail_from_mx_octaves(1) == 0.0
    assert noise_detail_from_mx_octaves(3) == 2.0
    assert noise_detail_from_mx_octaves(16) == 15.0
