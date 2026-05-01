from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from materialx_importer import load_materialx_as_blender_material


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    result = load_materialx_as_blender_material(args.mtlx_path)

    mesh = create_preview_mesh()
    mesh.data.materials.append(result.material)

    for warning in result.warnings:
        print(f"MaterialX importer warning: {warning}")

    bpy.ops.wm.save_as_mainfile(filepath=args.output_blend_path)
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    passthrough_args = argv[argv.index("--") + 1 :] if "--" in argv else []
    parser = argparse.ArgumentParser(description="Import a MaterialX material into a simple Blender scene.")
    parser.add_argument("mtlx_path")
    parser.add_argument("output_blend_path")
    return parser.parse_args(passthrough_args)


def create_preview_mesh() -> bpy.types.Object:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()
    bpy.ops.mesh.primitive_uv_sphere_add(segments=64, ring_count=32)
    mesh = bpy.context.object
    mesh.name = "MaterialX_Preview"
    return mesh


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
