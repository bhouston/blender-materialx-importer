# Contributing

Thanks for helping improve Blender MaterialX Importer.

## Development Goals

This project optimizes for faithful Blender rendering of MaterialX materials. It is not a MaterialX document editor and does not try to preserve a 1:1 graph mapping when Blender has a clearer or more accurate representation.

When making changes:

- Prefer visual fidelity over source graph preservation.
- Keep warnings explicit when behavior is approximate or unsupported.
- Keep the public API small and Blender-focused.
- Avoid coupling the importer to any one render harness, sample suite, or CLI.

## Node Support Workflow

For a new MaterialX node or surface input:

1. Add the importer/compiler support in `materialx_importer`.
2. Use Blender-native nodes when they are accurate enough.
3. Feature-detect custom `ShaderNodeMx*` nodes when exact support depends on a patched Blender build.
4. Fall back with a clear warning when stock Blender cannot reproduce the node exactly.
5. Add or update a small sample in the downstream fidelity suite.
6. Validate with both Cycles and Eevee when the behavior is renderer-visible.

## Testing

Pure-Python tests can run with:

```bash
python -m pytest
```

Blender integration and image-fidelity testing live in `material-fidelity`. Use that suite for render-output changes, especially changes to nodes, surface mappings, texture handling, color handling, or fallback behavior.

## Documentation

Please document:

- New supported surface inputs or node categories.
- Known approximations.
- New custom Blender node requirements.
- Any expected changes in fidelity results.
