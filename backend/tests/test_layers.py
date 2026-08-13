"""Synchronous invariants of the vector-tile layer registry.

Kept apart from test_api.py because that module pins everything to a
session event loop, which does not apply to plain functions.
"""

import pytest

from app.services.layers import ALL_LAYERS


def test_layer_names_are_unique():
    names = [layer.name for layer in ALL_LAYERS]
    assert len(names) == len(set(names))


def test_every_project_has_a_polygon_and_a_line_layer():
    """The brief requires both geometry kinds in every project."""
    by_project: dict[str, set[str]] = {}
    for layer in ALL_LAYERS:
        by_project.setdefault(layer.project, set()).add(layer.geom_kind)
    for project, kinds in by_project.items():
        assert "polygon" in kinds, f"{project} has no polygon layer"
        assert "line" in kinds, f"{project} has no line layer"


def test_layer_specs_reject_unsafe_identifiers():
    from app.services.layers import LayerSpec

    with pytest.raises(ValueError, match="Unsafe SQL identifier"):
        LayerSpec(
            name="evil", project="x", title="x", schema="agri",
            table="fields; DROP TABLE auth.users --", geom_kind="polygon",
            permission="agriculture:read", columns=("id",),
        )


