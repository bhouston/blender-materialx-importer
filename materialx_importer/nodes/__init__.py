from __future__ import annotations

from . import color, geometry, logic, math, matrix, mix, noise, ramps, structure, texture


def register_all(registry) -> None:
    geometry.register(registry)
    structure.register(registry)
    texture.register(registry)
    math.register(registry)
    matrix.register(registry)
    logic.register(registry)
    ramps.register(registry)
    color.register(registry)
    noise.register(registry)
    mix.register(registry)
