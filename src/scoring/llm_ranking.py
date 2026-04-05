from __future__ import annotations

import json
from typing import Any

# Keys sent to the LLM for per-candidate scoring (lat/lon + agronomic features).
_LLM_SCORING_KEYS: tuple[str, ...] = (
    "lat",
    "lon",
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
)

# Subset used for confidence and compact comparison payloads (no coordinates).
_LLM_DATA_KEYS: tuple[str, ...] = _LLM_SCORING_KEYS[2:]


def _row_features_for_prompt(row: dict[str, Any]) -> dict[str, Any]:
    return {key: row.get(key) for key in _LLM_SCORING_KEYS}


def _parse_json_object(text: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()

    try:
        candidate = json.loads(text)
        if isinstance(candidate, dict):
            return candidate
    except json.JSONDecodeError:
        pass

    search_start = 0
    while True:
        start = text.find("{", search_start)
        if start < 0:
            break
        try:
            candidate, _end_idx = decoder.raw_decode(text[start:])
            if isinstance(candidate, dict):
                return candidate
        except json.JSONDecodeError:
            search_start = start + 1
            continue
        search_start = start + 1

    raise ValueError("Could not parse JSON object from LLM output.")


def _score_band(score: float) -> str:
    if score >= 80.0:
        return "excellent"
    if score >= 60.0:
        return "good"
    if score >= 40.0:
        return "fair"
    return "poor"


def _compact_features(row: dict[str, Any]) -> dict[str, Any]:
    return {key: row.get(key) for key in _LLM_DATA_KEYS if row.get(key) is not None}


def _data_confidence(row: dict[str, Any]) -> float:
    available = sum(1 for key in _LLM_DATA_KEYS if row.get(key) is not None)
    return round(available / len(_LLM_DATA_KEYS), 3)
