from __future__ import annotations

from statistics import mean, pstdev
from typing import Any

from src.collectors.http_utils import HttpJsonClient
from src.collectors.weather_worker import _annualized_sum
from src.types import CandidatePoint

_GOOGLE_FORECAST_URL = "https://weather.googleapis.com/v1/forecast/hours:lookup"

# Google WeatherCondition types treated as elevated agronomic stress (storm / heavy precip).
_SEVERE_CONDITION_SUBSTRINGS = (
    "THUNDER",
    "HAIL",
    "TORNADO",
    "HURRICANE",
    "CYCLONE",
    "BLIZZARD",
    "SQUALL",
    "EXTREME",
    "SEVERE",
)
_SEVERE_CONDITION_TYPES = frozenset(
    {
        "HEAVY_RAIN",
        "HEAVY_SNOW",
        "FREEZING_RAIN",
        "ICE_PELLETS",
        "BLOWING_SNOW",
        "DUST_STORM",
        "SMOKE_HEAVY",
    }
)


def _is_severe_google_condition(wtype: str) -> bool:
    u = (wtype or "").strip().upper()
    if not u:
        return False
    if u in _SEVERE_CONDITION_TYPES:
        return True
    return any(s in u for s in _SEVERE_CONDITION_SUBSTRINGS)


class GoogleForecastWeatherWorker:
    """Hourly forecast from Google Weather API (up to 240 h); not historical archive."""

    def __init__(self, client: HttpJsonClient, api_key: str):
        self.client = client
        self.api_key = api_key

    def collect(self, point: CandidatePoint) -> tuple[dict[str, float], dict[str, Any]]:
        diagnostics: dict[str, Any] = {
            "ok": False,
            "source": "google_weather_forecast",
            "error": None,
        }
        try:
            hours = self._fetch_all_hours(point.lat, point.lon)
            if not hours:
                diagnostics["error"] = "Google Weather returned no hourly rows."
                return {}, diagnostics

            temperatures: list[float] = []
            precipitation_mm: list[float] = []
            humidity: list[float] = []
            wind_kmh: list[float] = []
            severe_flags: list[bool] = []

            for block in hours:
                t = block.get("temperature") or {}
                if isinstance(t, dict) and "degrees" in t:
                    try:
                        temperatures.append(float(t["degrees"]))
                    except (TypeError, ValueError):
                        pass
                q_mm = 0.0
                precip = block.get("precipitation")
                if isinstance(precip, dict):
                    qpf = precip.get("qpf")
                    if isinstance(qpf, dict) and qpf.get("quantity") is not None:
                        try:
                            q_mm = float(qpf["quantity"])
                        except (TypeError, ValueError):
                            q_mm = 0.0
                precipitation_mm.append(q_mm)
                rh = block.get("relativeHumidity")
                if rh is not None:
                    try:
                        humidity.append(float(rh))
                    except (TypeError, ValueError):
                        pass
                wind = block.get("wind") or {}
                spd = wind.get("speed") if isinstance(wind, dict) else None
                if isinstance(spd, dict) and "value" in spd:
                    try:
                        wind_kmh.append(float(spd["value"]))
                    except (TypeError, ValueError):
                        pass
                wc = block.get("weatherCondition") or {}
                wtype = wc.get("type", "") if isinstance(wc, dict) else ""
                severe_flags.append(_is_severe_google_condition(str(wtype)))

            features: dict[str, float] = {}
            if temperatures:
                features["mean_temp_c"] = round(mean(temperatures), 3)
                features["temp_std_c"] = round(pstdev(temperatures), 3)
                frost_hours = sum(1 for value in temperatures if value <= 0.0)
                features["frost_risk"] = round(frost_hours / len(temperatures), 3)
            if precipitation_mm:
                features["rainfall_mm"] = round(_annualized_sum(precipitation_mm), 3)
            if humidity:
                features["humidity_pct"] = round(mean(humidity), 3)
            if wind_kmh:
                features["wind_speed_10m_kmh"] = round(mean(wind_kmh), 3)
            if severe_flags:
                severe_ratio = sum(1 for x in severe_flags if x) / len(severe_flags)
                features["weather_stress_ratio"] = round(severe_ratio, 3)

            diagnostics["ok"] = bool(features)
            diagnostics["forecast_hours_used"] = len(hours)
            if not features:
                diagnostics["error"] = "No usable metrics in Google Weather response."
            return features, diagnostics
        except Exception as exc:
            diagnostics["error"] = str(exc)
            return {}, diagnostics

    def _fetch_all_hours(self, lat: float, lon: float) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        page_token: str | None = None
        max_total = 240

        while len(collected) < max_total:
            params: dict[str, Any] = {
                "key": self.api_key,
                "location.latitude": lat,
                "location.longitude": lon,
                "hours": max_total,
                "pageSize": min(100, max_total - len(collected)),
            }
            if page_token:
                params["pageToken"] = page_token
            payload = self.client.get_json(_GOOGLE_FORECAST_URL, params=params, use_cache=True)
            batch = payload.get("forecastHours") or []
            if not isinstance(batch, list) or not batch:
                break
            collected.extend(batch)
            page_token = payload.get("nextPageToken")
            if not page_token:
                break
        return collected[:max_total]
