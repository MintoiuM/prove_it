from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FeatureRequirement:
    ideal_min: float
    ideal_max: float
    hard_min: float
    hard_max: float
    weight: float


@dataclass(frozen=True)
class CropProfile:
    name: str
    requirements: dict[str, FeatureRequirement]
