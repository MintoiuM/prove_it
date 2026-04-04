from __future__ import annotations

from typing import Any

from src.collectors.http_utils import HttpJsonClient
from src.types import CandidatePoint


SOIL_PROPERTIES = ("phh2o", "soc", "sand", "clay")


class SoilWorker:
    def __init__(self, client: HttpJsonClient, endpoint: str):
        self.client = client
        self.endpoint = endpoint

    def collect(self, point: CandidatePoint) -> tuple[dict[str, float], dict[str, Any]]:
        params = {
            "lat": point.lat,
            "lon": point.lon,
            "property": list(SOIL_PROPERTIES),
            "depth": "0-5cm",
            "value": "mean",
        }
        diagnostics: dict[str, Any] = {"ok": False, "source": "soilgrids", "error": None}

        try:
            payload = self.client.get_json(self.endpoint, params=params, use_cache=True)
            layers = payload.get("properties", {}).get("layers", [])

            raw_ph = _extract_property_value(layers, "phh2o")
            raw_soc = _extract_property_value(layers, "soc")
            raw_sand = _extract_property_value(layers, "sand")
            raw_clay = _extract_property_value(layers, "clay")

            features: dict[str, float] = {}
            if raw_ph is not None:
                features["soil_ph"] = round(_normalize_ph(raw_ph), 3)
            if raw_soc is not None:
                features["soil_organic_carbon_gkg"] = round(_normalize_soc(raw_soc), 3)
            if raw_sand is not None:
                features["sand_pct"] = round(_normalize_percent(raw_sand), 3)
            if raw_clay is not None:
                features["clay_pct"] = round(_normalize_percent(raw_clay), 3)

            diagnostics["ok"] = bool(features)
            if not features:
                diagnostics["error"] = "No soil metrics returned by API payload."
            return features, diagnostics
        except Exception as exc:
            diagnostics["error"] = str(exc)
            return {}, diagnostics


def _extract_property_value(layers: list[dict[str, Any]], property_name: str) -> float | None:
    for layer in layers:
        if layer.get("name") != property_name:
            continue
        depths = layer.get("depths", [])
        for depth in depths:
            values = depth.get("values", {})
            if "mean" not in values:
                continue
            value = values["mean"]
            try:
                return float(value)
            except (TypeError, ValueError):
                return None
    return None


def _normalize_ph(value: float) -> float:
    # SoilGrids often stores pH in deci-units for this property.
    normalized = value / 10.0 if value > 14.0 else value
    return min(14.0, max(0.0, normalized))


def _normalize_soc(value: float) -> float:
    normalized = value / 10.0 if value > 300.0 else value
    return max(0.0, normalized)


def _normalize_percent(value: float) -> float:
    normalized = value / 10.0 if value > 100.0 else value
    return min(100.0, max(0.0, normalized))

