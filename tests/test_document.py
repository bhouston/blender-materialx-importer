from __future__ import annotations

from materialx_importer.document import inherited_attribute


class FakeElement:
    def __init__(self, attributes: dict[str, str] | None = None, parent: "FakeElement | None" = None) -> None:
        self._attributes = attributes or {}
        self._parent = parent

    def getAttribute(self, name: str) -> str:
        return self._attributes.get(name, "")

    def getParent(self) -> "FakeElement | None":
        return self._parent


def test_inherited_attribute_prefers_local_scope() -> None:
    root = FakeElement({"colorspace": "lin_rec709"})
    image = FakeElement({"colorspace": "srgb_texture"}, root)
    file_input = FakeElement(parent=image)

    assert inherited_attribute(file_input, "colorspace") == "srgb_texture"


def test_inherited_attribute_falls_back_to_enclosing_scope() -> None:
    root = FakeElement({"colorspace": "lin_rec709"})
    nodegraph = FakeElement(parent=root)
    image = FakeElement(parent=nodegraph)
    file_input = FakeElement(parent=image)

    assert inherited_attribute(file_input, "colorspace") == "lin_rec709"


def test_inherited_attribute_returns_none_when_absent() -> None:
    file_input = FakeElement()

    assert inherited_attribute(file_input, "colorspace") is None
