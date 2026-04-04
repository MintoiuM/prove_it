from __future__ import annotations

import csv
import statistics
from collections import Counter
from pathlib import Path

from src.models.crop_schema import CropProfile, FeatureRequirement


def normalize_crop_key(name: str) -> str:
    return "_".join(name.strip().lower().split())


# Typical texture targets (clay %, sand %) for agronomic soil classes in the dataset.
_SOIL_TEXTURE: dict[str, tuple[float, float]] = {
    "sandy": (12.0, 68.0),
    "loamy": (28.0, 38.0),
    "clayey": (42.0, 28.0),
    "black": (35.0, 32.0),
    "red": (32.0, 42.0),
}

# Features not present in crop_needs_clean.csv: wide flat bands so observed values score fully,
# with small weights so CSV-driven signals dominate ranking.
_NEUTRAL_SPECS: dict[str, tuple[float, float, float]] = {
    "rainfall_mm": (150.0, 1400.0, 0.05),
    "frost_risk": (0.0, 0.5, 0.06),
    "et0_mm": (400.0, 1600.0, 0.05),
    "wind_speed_10m_kmh": (0.0, 40.0, 0.04),
    "weather_stress_ratio": (0.0, 0.35, 0.04),
    "soil_ph": (5.0, 8.5, 0.05),
    "soil_organic_carbon_gkg": (4.0, 50.0, 0.05),
}


def _median(nums: list[float]) -> float:
    if not nums:
        return 0.0
    return float(statistics.median(nums))


def _mode_str(values: list[str]) -> str:
    if not values:
        return "loamy"
    return Counter(values).most_common(1)[0][0].strip().lower()


def _temp_column(fieldnames: list[str] | None) -> str | None:
    if not fieldnames:
        return None
    lower = {f.strip().lower(): f for f in fieldnames}
    for key in ("temparature", "temperature", "temp"):
        if key in lower:
            return lower[key]
    return None


def build_profiles_from_csv(path: Path) -> dict[str, CropProfile]:
    text = path.read_text(encoding="utf-8")
    reader = csv.DictReader(text.splitlines())
    if not reader.fieldnames:
        return {}

    temp_col = _temp_column(list(reader.fieldnames))
    if not temp_col:
        raise ValueError(
            f"{path}: expected a temperature column (temparature/temperature/temp), "
            f"got {reader.fieldnames!r}"
        )

    groups: dict[str, dict[str, list]] = {}
    display_names: dict[str, str] = {}

    for row in reader:
        raw_name = (row.get("crop_name") or "").strip()
        if not raw_name:
            continue
        key = normalize_crop_key(raw_name)
        if key not in display_names:
            display_names[key] = raw_name.strip().title()

        bucket = groups.setdefault(
            key,
            {"temp": [], "humidity": [], "moisture": [], "soil_types": []},
        )
        try:
            bucket["temp"].append(float((row.get(temp_col) or "").strip()))
        except (TypeError, ValueError):
            pass
        try:
            bucket["humidity"].append(float((row.get("humidity") or "").strip()))
        except (TypeError, ValueError):
            pass
        try:
            bucket["moisture"].append(float((row.get("moisture") or "").strip()))
        except (TypeError, ValueError):
            pass
        st = (row.get("soil_type") or "").strip()
        if st:
            bucket["soil_types"].append(st.lower())

    profiles: dict[str, CropProfile] = {}
    for key, bucket in groups.items():
        t = _median(bucket["temp"])
        h = _median(bucket["humidity"])
        m_pct = _median(bucket["moisture"])
        soil_key = _mode_str(bucket["soil_types"])
        clay_t, sand_t = _SOIL_TEXTURE.get(soil_key, _SOIL_TEXTURE["loamy"])

        t_lo = max(-5.0, t - 18.0)
        t_hi = min(48.0, t + 18.0)
        t_ideal_lo, t_ideal_hi = t - 5.0, t + 5.0
        t_ideal_lo = max(t_lo, min(t_ideal_lo, t_ideal_hi))
        t_ideal_hi = min(t_hi, max(t_ideal_lo, t_ideal_hi))

        h_lo, h_hi = 15.0, 98.0
        h_ideal_lo = max(h_lo, h - 12.0)
        h_ideal_hi = min(h_hi, h + 12.0)

        m_vol = max(0.05, min(0.65, m_pct / 100.0))
        m_span = 0.1
        m_ideal_lo = max(0.05, m_vol - m_span)
        m_ideal_hi = min(0.65, m_vol + m_span)
        m_hard_lo, m_hard_hi = 0.05, 0.65

        clay_ideal_lo = max(0.0, clay_t - 12.0)
        clay_ideal_hi = min(100.0, clay_t + 12.0)
        sand_ideal_lo = max(0.0, sand_t - 12.0)
        sand_ideal_hi = min(100.0, sand_t + 12.0)

        name = display_names.get(key, key.replace("_", " ").title())
        requirements: dict[str, FeatureRequirement] = {
            "mean_temp_c": FeatureRequirement(
                t_ideal_lo, t_ideal_hi, t_lo, t_hi, 0.22
            ),
            "humidity_pct": FeatureRequirement(
                h_ideal_lo, h_ideal_hi, h_lo, h_hi, 0.12
            ),
            "soil_moisture_1_3cm": FeatureRequirement(
                m_ideal_lo, m_ideal_hi, m_hard_lo, m_hard_hi, 0.12
            ),
            "clay_pct": FeatureRequirement(
                clay_ideal_lo, clay_ideal_hi, 0.0, 100.0, 0.1
            ),
            "sand_pct": FeatureRequirement(
                sand_ideal_lo, sand_ideal_hi, 0.0, 100.0, 0.08
            ),
        }
        for feat, (hard_lo, hard_hi, w) in _NEUTRAL_SPECS.items():
            requirements[feat] = FeatureRequirement(
                hard_lo, hard_hi, hard_lo, hard_hi, w
            )

        profiles[key] = CropProfile(name=name, requirements=requirements)

    return profiles
