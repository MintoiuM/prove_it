"""Land vs ocean filtering for candidate points (ray-casting helpers)."""

from __future__ import annotations

import src.geo.grid as grid


def test_point_in_triangle_island() -> None:
    island = [(40.0, 20.0), (40.0, 22.0), (38.0, 21.0)]
    assert grid._point_in_any_polygon(39.5, 21.0, [island])
    assert not grid._point_in_any_polygon(36.0, 21.0, [island])


def test_bbox_intersects_bbox() -> None:
    poly = (39.0, 41.0, 19.0, 21.0)
    assert grid._bbox_intersects_bbox(poly, (40.0, 42.0, 20.0, 22.0))
    assert not grid._bbox_intersects_bbox(poly, (50.0, 51.0, 20.0, 22.0))


def test_cached_land_file_marks_mediterranean_as_sea() -> None:
    """Uses Natural Earth land cache if present (first pipeline run downloads it)."""
    land_path = grid.natural_earth_land_cache_path()
    if not land_path.is_file():
        import pytest

        pytest.skip(f"{land_path.name} not cached yet")
    grid._clear_land_rings_cache()
    rings = grid._load_all_land_rings()
    assert len(rings) > 10
    # Open Libyan Sea — not on land in NE 110m
    lat, lon = 34.2, 20.5
    assert not grid._point_in_any_polygon(lat, lon, rings)
