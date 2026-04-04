from __future__ import annotations

from statistics import mean, pstdev
from typing import Any

from src.collectors.http_utils import HttpJsonClient
from src.types import CandidatePoint


class WeatherWorker:
    def __init__(
        self,
        client: HttpJsonClient,
        endpoint: str,
        start_date: str,
        end_date: str,
    ):
        self.client = client
        self.endpoint = endpoint
        self.start_date = start_date
        self.end_date = end_date

    def collect(self, point: CandidatePoint) -> tuple[dict[str, float], dict[str, Any]]:
        params = {
            "latitude": point.lat,
            "longitude": point.lon,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "hourly": [
                "temperature_2m",
                "precipitation",
                "relative_humidity_2m",
                "weather_code",
                "evapotranspiration",
                "wind_speed_10m",
                "soil_moisture_1_to_3cm",
            ],
            "timezone": "UTC",
        }

        diagnostics: dict[str, Any] = {"ok": False, "source": "open-meteo", "error": None}
        try:
            payload = self.client.get_json(self.endpoint, params=params, use_cache=True)
            hourly = payload.get("hourly", {})
            temperatures = _safe_float_list(hourly.get("temperature_2m"))
            precipitation = _safe_float_list(hourly.get("precipitation"))
            humidity = _safe_float_list(hourly.get("relative_humidity_2m"))
            weather_codes = _safe_float_list(hourly.get("weather_code"))
            evapotranspiration = _safe_float_list(hourly.get("evapotranspiration"))
            wind_speed = _safe_float_list(hourly.get("wind_speed_10m"))
            soil_moisture_1_3cm = _safe_float_list(hourly.get("soil_moisture_1_to_3cm"))

            features: dict[str, float] = {}
            if temperatures:
                features["mean_temp_c"] = round(mean(temperatures), 3)
                features["temp_std_c"] = round(pstdev(temperatures), 3)
                frost_hours = sum(1 for value in temperatures if value <= 0.0)
                features["frost_risk"] = round(frost_hours / len(temperatures), 3)

            if precipitation:
                features["rainfall_mm"] = round(_annualized_sum(precipitation), 3)
            if humidity:
                features["humidity_pct"] = round(mean(humidity), 3)
            if evapotranspiration:
                features["et0_mm"] = round(_annualized_sum(evapotranspiration), 3)
            if wind_speed:
                features["wind_speed_10m_kmh"] = round(mean(wind_speed), 3)
            if soil_moisture_1_3cm:
                features["soil_moisture_1_3cm"] = round(mean(soil_moisture_1_3cm), 4)
            if weather_codes:
                severe_codes = {65.0, 67.0, 75.0, 82.0, 86.0, 95.0, 96.0, 99.0}
                severe_ratio = sum(1 for code in weather_codes if code in severe_codes) / len(
                    weather_codes
                )
                features["weather_stress_ratio"] = round(severe_ratio, 3)

            diagnostics["ok"] = bool(features)
            if not features:
                diagnostics["error"] = "No weather metrics returned by API payload."
            return features, diagnostics
        except Exception as exc:
            diagnostics["error"] = str(exc)
            return {}, diagnostics


def _safe_float_list(values: Any) -> list[float]:
    if not isinstance(values, list):
        return []
    output: list[float] = []
    for item in values:
        if item is None:
            continue
        try:
            output.append(float(item))
        except (TypeError, ValueError):
            continue
    return output


def _annualized_sum(hourly_values: list[float]) -> float:
    # Convert an hourly cumulative series over arbitrary interval to yearly-equivalent.
    hours = len(hourly_values)
    if hours <= 0:
        return 0.0
    return (sum(hourly_values) / hours) * (24.0 * 365.0)

