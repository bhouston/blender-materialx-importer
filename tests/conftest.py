from __future__ import annotations

import sys
import types


def pytest_configure() -> None:
    if "MaterialX" not in sys.modules:
        sys.modules["MaterialX"] = types.SimpleNamespace()
