from __future__ import annotations

import os
from pathlib import Path

from src.config import resolve_bundled_data_csv
from src.models.crop_needs_loader import build_profiles_from_csv, normalize_crop_key
from src.models.crop_schema import CropProfile, FeatureRequirement

# Re-export for callers that import from crop_profiles.
__all__ = (
    "CropProfile",
    "FeatureRequirement",
    "crop_display_labels",
    "get_crop_profile",
    "list_crop_names",
    "reload_crop_profiles",
)

# Crops not covered by crop_needs_clean.csv (kept as hand-tuned profiles).
_BUILTIN_PROFILES: dict[str, CropProfile] = {
    "corn": CropProfile(
        name="Corn",
        requirements={
            "mean_temp_c": FeatureRequirement(18.0, 27.0, 10.0, 35.0, 0.24),
            "rainfall_mm": FeatureRequirement(450.0, 900.0, 250.0, 1300.0, 0.2),
            "frost_risk": FeatureRequirement(0.0, 0.12, 0.0, 0.3, 0.12),
            "humidity_pct": FeatureRequirement(45.0, 75.0, 30.0, 92.0, 0.06),
            "et0_mm": FeatureRequirement(650.0, 1250.0, 400.0, 1700.0, 0.06),
            "wind_speed_10m_kmh": FeatureRequirement(2.0, 16.0, 0.0, 32.0, 0.03),
            "soil_moisture_1_3cm": FeatureRequirement(0.2, 0.42, 0.06, 0.62, 0.03),
            "weather_stress_ratio": FeatureRequirement(0.0, 0.07, 0.0, 0.28, 0.03),
            "soil_ph": FeatureRequirement(5.8, 7.2, 5.0, 8.0, 0.18),
            "soil_organic_carbon_gkg": FeatureRequirement(11.0, 28.0, 4.0, 50.0, 0.12),
            "clay_pct": FeatureRequirement(12.0, 38.0, 4.0, 55.0, 0.08),
            "sand_pct": FeatureRequirement(20.0, 60.0, 5.0, 85.0, 0.06),
        },
    ),
    "sunflower": CropProfile(
        name="Sunflower",
        requirements={
            "mean_temp_c": FeatureRequirement(16.0, 27.0, 8.0, 34.0, 0.25),
            "rainfall_mm": FeatureRequirement(300.0, 700.0, 180.0, 1100.0, 0.18),
            "frost_risk": FeatureRequirement(0.0, 0.1, 0.0, 0.25, 0.13),
            "humidity_pct": FeatureRequirement(38.0, 68.0, 22.0, 88.0, 0.06),
            "et0_mm": FeatureRequirement(650.0, 1300.0, 350.0, 1800.0, 0.06),
            "wind_speed_10m_kmh": FeatureRequirement(2.0, 17.0, 0.0, 34.0, 0.03),
            "soil_moisture_1_3cm": FeatureRequirement(0.15, 0.35, 0.05, 0.58, 0.03),
            "weather_stress_ratio": FeatureRequirement(0.0, 0.09, 0.0, 0.32, 0.03),
            "soil_ph": FeatureRequirement(6.0, 7.8, 5.2, 8.5, 0.18),
            "soil_organic_carbon_gkg": FeatureRequirement(8.0, 24.0, 3.0, 45.0, 0.12),
            "clay_pct": FeatureRequirement(10.0, 35.0, 3.0, 60.0, 0.08),
            "sand_pct": FeatureRequirement(25.0, 65.0, 5.0, 90.0, 0.06),
        },
    ),
}


def _resolve_crop_needs_csv_path() -> Path | None:
    raw = os.getenv("CROP_NEEDS_CSV")
    if raw is not None:
        stripped = raw.strip()
        if not stripped or stripped.lower() in ("none", "off", "0", "false"):
            return None
        candidate = Path(stripped)
        return candidate.resolve() if candidate.is_file() else None
    return resolve_bundled_data_csv("crop_needs_clean.csv")


def _merged_profiles() -> dict[str, CropProfile]:
    merged = dict(_BUILTIN_PROFILES)
    path = _resolve_crop_needs_csv_path()
    if path is not None:
        csv_profiles = build_profiles_from_csv(path)
        merged.update(csv_profiles)
    return merged


_PROFILES_CACHE: dict[str, CropProfile] | None = None


def _profiles() -> dict[str, CropProfile]:
    global _PROFILES_CACHE
    if _PROFILES_CACHE is None:
        _PROFILES_CACHE = _merged_profiles()
    return _PROFILES_CACHE


def reload_crop_profiles() -> None:
    """Clear cached profiles (e.g. after changing CROP_NEEDS_CSV or the file on disk)."""
    global _PROFILES_CACHE
    _PROFILES_CACHE = None


def list_crop_names() -> list[str]:
    return sorted(_profiles().keys())


def crop_display_labels() -> dict[str, str]:
    return {key: prof.name for key, prof in _profiles().items()}


def get_crop_profile(crop: str) -> CropProfile:
    key = normalize_crop_key(crop)
    profiles = _profiles()
    if key not in profiles:
        supported = ", ".join(list_crop_names())
        raise ValueError(f"Unsupported crop '{crop}'. Supported crops: {supported}.")
    return profiles[key]
