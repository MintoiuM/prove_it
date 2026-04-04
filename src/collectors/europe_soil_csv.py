from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any

from src.types import CandidatePoint

# Typical conversion: organic matter % → organic carbon % → g/kg (×10 per %C).
_OM_TO_SOC_GKG = 0.58 * 10.0


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
    return r * c


class EuropeSoilCsvStore:
    """In-memory rows from europe_soil_climate_dataset.csv (or compatible schema)."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._rows: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        text = self._path.read_text(encoding="utf-8")
        reader = csv.DictReader(text.splitlines())
        if not reader.fieldnames:
            return
        fields = {f.strip().lower(): f for f in reader.fieldnames}

        def col(*names: str) -> str | None:
            for n in names:
                if n.lower() in fields:
                    return fields[n.lower()]
            return None

        clat = col("latitude", "lat", "y")
        clon = col("longitude", "lon", "x")
        if not clat or not clon:
            raise ValueError(
                f"{self._path}: need Latitude/Longitude (or lat/lon) columns, got {reader.fieldnames!r}"
            )
        cph = col("ph", "soil_ph", "phh2o")
        cclay = col("clay_percent", "clay", "clay_pct")
        com = col("organic_matter_percent", "om", "organicmatter_percent")

        for raw in reader:
            try:
                lat = float((raw.get(clat) or "").strip())
                lon = float((raw.get(clon) or "").strip())
            except (TypeError, ValueError):
                continue
            row: dict[str, Any] = {"lat": lat, "lon": lon, "_raw": raw}
            if cph and raw.get(cph) not in (None, ""):
                try:
                    row["ph"] = float(raw[cph])
                except (TypeError, ValueError):
                    pass
            if cclay and raw.get(cclay) not in (None, ""):
                try:
                    row["clay_pct"] = float(raw[cclay])
                except (TypeError, ValueError):
                    pass
            if com and raw.get(com) not in (None, ""):
                try:
                    row["om_pct"] = float(raw[com])
                except (TypeError, ValueError):
                    pass
            self._rows.append(row)

    def nearest(self, lat: float, lon: float) -> tuple[dict[str, Any] | None, float | None]:
        if not self._rows:
            return None, None
        best: dict[str, Any] | None = None
        best_d: float | None = None
        for row in self._rows:
            d = _haversine_km(lat, lon, row["lat"], row["lon"])
            if best_d is None or d < best_d:
                best_d = d
                best = row
        return best, best_d


class EuropeCsvSoilWorker:
    """Soil features from a European CSV grid; nearest row by Haversine distance."""

    def __init__(self, path: Path):
        self._store = EuropeSoilCsvStore(path)

    def collect(self, point: CandidatePoint) -> tuple[dict[str, float], dict[str, Any]]:
        diagnostics: dict[str, Any] = {
            "ok": False,
            "source": "europe_soil_csv",
            "error": None,
        }
        nearest, dist_km = self._store.nearest(point.lat, point.lon)
        if nearest is None or dist_km is None:
            diagnostics["error"] = "Soil CSV is empty or could not be read."
            return {}, diagnostics

        diagnostics["nearest_distance_km"] = round(dist_km, 3)
        diagnostics["nearest_dataset_lat"] = nearest["lat"]
        diagnostics["nearest_dataset_lon"] = nearest["lon"]

        features: dict[str, float] = {}
        if "ph" in nearest:
            ph = float(nearest["ph"])
            features["soil_ph"] = round(min(14.0, max(0.0, ph)), 3)
        if "clay_pct" in nearest:
            features["clay_pct"] = round(min(100.0, max(0.0, float(nearest["clay_pct"]))), 3)
        if "om_pct" in nearest:
            om = float(nearest["om_pct"])
            features["soil_organic_carbon_gkg"] = round(max(0.0, om * _OM_TO_SOC_GKG), 3)

        diagnostics["ok"] = bool(features)
        if not features:
            diagnostics["error"] = "Nearest CSV row had no usable pH, clay, or organic matter."
        return features, diagnostics
