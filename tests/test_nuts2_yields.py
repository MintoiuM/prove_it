"""Tests for NUTS2 yield helpers (pure logic + optional CSV smoke)."""

from __future__ import annotations

import pytest

from src.config import resolve_bundled_data_csv
from src.data.nuts2_yields import (
    Nuts2YieldStore,
    blend_rules_score_with_yield,
    crop_slug_to_yield_column,
    yield_to_score_0_100,
)


@pytest.mark.parametrize(
    ("slug", "expected_col_piece"),
    [
        ("wheat", "Wheat"),
        ("corn", "Corn"),
        ("sunflower", "Sunflower"),
        ("unknown_crop_xyz", None),
    ],
)
def test_crop_slug_to_yield_column(slug: str, expected_col_piece: str | None) -> None:
    col = crop_slug_to_yield_column(slug)
    if expected_col_piece is None:
        assert col is None
    else:
        assert col is not None
        assert expected_col_piece in col


def test_yield_to_score_clamped() -> None:
    assert yield_to_score_0_100(0.0, "wheat") == 0.0
    assert yield_to_score_0_100(100.0, "wheat") == 100.0


def test_blend_rules_score_with_yield() -> None:
    mixed = blend_rules_score_with_yield(80.0, 50.0)
    assert 50.0 < mixed < 80.0


def test_nuts2_store_loads_when_csv_present() -> None:
    path = resolve_bundled_data_csv("nuts2_crop_yields_all_regions.csv")
    if path is None:
        pytest.skip("NUTS2 CSV not in tree")
    store = Nuts2YieldStore(path)
    labels = store.unique_region_labels()
    assert len(labels) > 0
