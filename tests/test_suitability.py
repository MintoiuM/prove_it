"""Tests for rule-based scoring and ranking."""

from __future__ import annotations

import pytest

from src.models.crop_schema import CropProfile, FeatureRequirement
from src.scoring.suitability import rank_candidates, score_point


@pytest.fixture
def tiny_profile() -> CropProfile:
    """Single-feature profile for predictable assertions."""
    return CropProfile(
        name="TestCrop",
        requirements={
            "mean_temp_c": FeatureRequirement(
                ideal_min=18.0,
                ideal_max=24.0,
                hard_min=5.0,
                hard_max=35.0,
                weight=1.0,
            ),
        },
    )


def test_score_point_ideal_in_range(tiny_profile: CropProfile) -> None:
    d = score_point({"mean_temp_c": 20.0}, tiny_profile)
    assert d.score >= 80.0
    assert d.score_band == "excellent"
    assert d.confidence > 0.9
    assert d.missing_features == []
    assert d.hard_violations == []


def test_score_point_hard_violation_lowers_score(tiny_profile: CropProfile) -> None:
    d = score_point({"mean_temp_c": 2.0}, tiny_profile)
    assert d.hard_violations == ["mean_temp_c"]
    assert d.score < 50.0


def test_score_point_missing_feature(tiny_profile: CropProfile) -> None:
    d = score_point({}, tiny_profile)
    assert "mean_temp_c" in d.missing_features
    assert d.confidence < 1.0


def test_score_point_non_numeric_treated_as_missing(tiny_profile: CropProfile) -> None:
    d = score_point({"mean_temp_c": "n/a"}, tiny_profile)
    assert "mean_temp_c" in d.missing_features


def test_rank_candidates_order_and_slice(tiny_profile: CropProfile) -> None:
    # 22 is in ideal band; 17 is below ideal (partial credit); 10 is lower still
    rows = [
        {"point_id": "P001", "mean_temp_c": 17.0},
        {"point_id": "P002", "mean_temp_c": 22.0},
        {"point_id": "P003", "mean_temp_c": 10.0},
    ]
    ranked = rank_candidates(rows, tiny_profile, top_n=2)
    assert len(ranked) == 2
    assert ranked[0]["point_id"] == "P002"
    assert ranked[0]["score"] >= ranked[1]["score"]
