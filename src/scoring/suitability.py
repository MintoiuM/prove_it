from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.models.crop_profiles import CropProfile, FeatureRequirement


@dataclass(frozen=True)
class ScoreDetails:
    score: float
    score_band: str
    confidence: float
    missing_features: list[str]
    hard_violations: list[str]


def score_point(features: dict[str, Any], profile: CropProfile) -> ScoreDetails:
    weighted_score_sum = 0.0
    used_weight_sum = 0.0
    missing_features: list[str] = []
    hard_violations: list[str] = []

    for feature_name, requirement in profile.requirements.items():
        raw_value = features.get(feature_name)
        if raw_value is None:
            missing_features.append(feature_name)
            continue

        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            missing_features.append(feature_name)
            continue

        contribution, violated = _score_feature(value, requirement)
        weighted_score_sum += contribution * requirement.weight
        used_weight_sum += requirement.weight
        if violated:
            hard_violations.append(feature_name)

    if used_weight_sum == 0:
        return ScoreDetails(
            score=0.0,
            score_band=_score_band(0.0),
            confidence=0.0,
            missing_features=missing_features,
            hard_violations=hard_violations,
        )

    base_score = 100.0 * (weighted_score_sum / used_weight_sum)
    missing_ratio = len(missing_features) / len(profile.requirements)
    # Calibrated scoring: keep relative ranking while reducing overly harsh penalties.
    calibrated_base = 15.0 + (0.85 * base_score)
    missing_penalty = 12.0 * missing_ratio
    hard_penalty = min(24.0, 8.0 * len(hard_violations))
    final_score = _clamp(calibrated_base - missing_penalty - hard_penalty, 0.0, 100.0)

    confidence = 1.0 - (0.45 * missing_ratio) - (0.07 * len(hard_violations))
    confidence = _clamp(confidence, 0.0, 1.0)

    return ScoreDetails(
        score=round(final_score, 3),
        score_band=_score_band(final_score),
        confidence=round(confidence, 3),
        missing_features=missing_features,
        hard_violations=hard_violations,
    )


def rank_candidates(
    candidate_rows: list[dict[str, Any]],
    profile: CropProfile,
    top_n: int = 10,
) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for row in candidate_rows:
        details = score_point(row, profile)
        enriched = dict(row)
        enriched["score"] = details.score
        enriched["score_band"] = details.score_band
        enriched["confidence"] = details.confidence
        enriched["missing_features"] = details.missing_features
        enriched["hard_violations"] = details.hard_violations
        ranked.append(enriched)

    ranked.sort(
        key=lambda item: (
            -float(item["score"]),
            -float(item["confidence"]),
            item["point_id"],
        )
    )
    return ranked[:top_n]


def _score_feature(value: float, requirement: FeatureRequirement) -> tuple[float, bool]:
    if requirement.hard_min <= value <= requirement.hard_max:
        if requirement.ideal_min <= value <= requirement.ideal_max:
            return 1.0, False
        if value < requirement.ideal_min:
            score = (value - requirement.hard_min) / (
                requirement.ideal_min - requirement.hard_min
            )
            return _clamp(score, 0.0, 1.0), False
        score = (requirement.hard_max - value) / (
            requirement.hard_max - requirement.ideal_max
        )
        return _clamp(score, 0.0, 1.0), False
    return 0.0, True


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _score_band(score: float) -> str:
    if score >= 80.0:
        return "excellent"
    if score >= 60.0:
        return "good"
    if score >= 40.0:
        return "fair"
    return "poor"

