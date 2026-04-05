"""Tests for shared LLM JSON helpers (no network)."""

from __future__ import annotations

import pytest

from src.scoring.llm_ranking import (
    _compact_features,
    _data_confidence,
    _parse_json_object,
    _row_features_for_prompt,
    _score_band,
)


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (90.0, "excellent"),
        (70.0, "good"),
        (50.0, "fair"),
        (10.0, "poor"),
    ],
)
def test_score_band(score: float, expected: str) -> None:
    assert _score_band(score) == expected


def test_parse_json_object_clean() -> None:
    out = _parse_json_object('{"llm_score": 77, "rating": "good"}')
    assert out["llm_score"] == 77
    assert out["rating"] == "good"


def test_parse_json_object_with_noise() -> None:
    text = 'Here is the result:\n{"llm_score": 55, "x": 1}\ntrailing'
    out = _parse_json_object(text)
    assert out["llm_score"] == 55


def test_parse_json_object_invalid_raises() -> None:
    with pytest.raises(ValueError, match="Could not parse JSON"):
        _parse_json_object("no braces here")


def test_row_features_for_prompt_includes_lat_lon() -> None:
    row = {"lat": 1.5, "lon": 2.5, "mean_temp_c": 20.0, "sand_pct": None}
    feats = _row_features_for_prompt(row)
    assert feats["lat"] == 1.5
    assert feats["lon"] == 2.5
    assert feats["mean_temp_c"] == 20.0
    assert feats.get("sand_pct") is None


def test_compact_features_omits_none() -> None:
    row = {"mean_temp_c": 10.0, "sand_pct": None, "clay_pct": 20.0}
    compact = _compact_features(row)
    assert "mean_temp_c" in compact
    assert "clay_pct" in compact
    assert "sand_pct" not in compact


def test_data_confidence_full_row() -> None:
    row = {k: 1.0 for k in (
        "mean_temp_c",
        "rainfall_mm",
        "frost_risk",
        "humidity_pct",
        "et0_mm",
        "wind_speed_10m_kmh",
        "soil_moisture_1_3cm",
        "weather_stress_ratio",
        "soil_ph",
        "soil_organic_carbon_gkg",
        "sand_pct",
        "clay_pct",
    )}
    assert _data_confidence(row) == 1.0


def test_data_confidence_sparse() -> None:
    assert _data_confidence({}) == 0.0
