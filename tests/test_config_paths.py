"""Tests for bundled dataset path resolution."""

from __future__ import annotations

from src.config import resolve_bundled_data_csv


def test_resolve_bundled_crop_needs_exists() -> None:
    """Repo ships crop_needs under datasets/ or root."""
    p = resolve_bundled_data_csv("crop_needs_clean.csv")
    assert p is not None
    assert p.is_file()
    assert p.name == "crop_needs_clean.csv"


def test_resolve_bundled_missing_returns_none() -> None:
    assert resolve_bundled_data_csv("definitely_not_a_real_file_12345.csv") is None
