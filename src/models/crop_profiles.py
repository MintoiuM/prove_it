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


CROP_PROFILES: dict[str, CropProfile] = {
    "wheat": CropProfile(
        name="wheat",
        requirements={
            "mean_temp_c": FeatureRequirement(10.0, 21.0, 3.0, 30.0, 0.22),
            "rainfall_mm": FeatureRequirement(350.0, 800.0, 220.0, 1200.0, 0.2),
            "frost_risk": FeatureRequirement(0.0, 0.25, 0.0, 0.45, 0.1),
            "humidity_pct": FeatureRequirement(45.0, 72.0, 30.0, 90.0, 0.06),
            "et0_mm": FeatureRequirement(550.0, 1050.0, 350.0, 1500.0, 0.06),
            "wind_speed_10m_kmh": FeatureRequirement(3.0, 18.0, 0.0, 35.0, 0.03),
            "soil_moisture_1_3cm": FeatureRequirement(0.18, 0.38, 0.05, 0.6, 0.03),
            "weather_stress_ratio": FeatureRequirement(0.0, 0.08, 0.0, 0.3, 0.03),
            "soil_ph": FeatureRequirement(6.0, 7.4, 5.0, 8.4, 0.2),
            "soil_organic_carbon_gkg": FeatureRequirement(10.0, 25.0, 4.0, 45.0, 0.14),
            "clay_pct": FeatureRequirement(15.0, 35.0, 5.0, 55.0, 0.09),
            "sand_pct": FeatureRequirement(20.0, 55.0, 5.0, 80.0, 0.05),
        },
    ),
    "corn": CropProfile(
        name="corn",
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
        name="sunflower",
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


def list_crop_names() -> list[str]:
    return sorted(CROP_PROFILES.keys())


def get_crop_profile(crop: str) -> CropProfile:
    key = crop.strip().lower()
    if key not in CROP_PROFILES:
        supported = ", ".join(list_crop_names())
        raise ValueError(f"Unsupported crop '{crop}'. Supported crops: {supported}.")
    return CROP_PROFILES[key]

