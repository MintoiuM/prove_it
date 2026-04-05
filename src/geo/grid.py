from __future__ import annotations

import json
import os
import random
import warnings
from dataclasses import dataclass
from pathlib import Path
from urllib.request import urlopen

from src.types import CandidatePoint

_NE_VECTOR_BASE = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
)


@dataclass(frozen=True)
class CountryEnvelope:
    name: str
    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float


COUNTRY_ENVELOPES: dict[str, CountryEnvelope] = {
    "france": CountryEnvelope("France", 41.3, 51.1, -5.3, 9.8),
    "spain": CountryEnvelope("Spain", 36.0, 43.9, -9.4, 3.3),
    "italy": CountryEnvelope("Italy", 36.5, 47.1, 6.6, 18.6),
    "germany": CountryEnvelope("Germany", 47.2, 55.1, 5.8, 15.1),
    "romania": CountryEnvelope("Romania", 43.6, 48.3, 20.2, 29.8),
    "poland": CountryEnvelope("Poland", 49.0, 54.9, 14.1, 24.2),
    "netherlands": CountryEnvelope("Netherlands", 50.8, 53.7, 3.2, 7.3),
    "belgium": CountryEnvelope("Belgium", 49.4, 51.6, 2.5, 6.4),
    "portugal": CountryEnvelope("Portugal", 36.8, 42.2, -9.6, -6.2),
    "hungary": CountryEnvelope("Hungary", 45.7, 48.6, 16.0, 22.9),
    "greece": CountryEnvelope("Greece", 34.8, 41.8, 19.0, 29.0),
}

# Simplified mainland borders for rejection sampling.
# Coordinates are (lat, lon), ordered clockwise.
COUNTRY_POLYGONS: dict[str, list[tuple[float, float]]] = {
    "france": [
        (51.08, 2.54),
        (50.28, 1.05),
        (49.40, -1.90),
        (48.50, -4.75),
        (46.25, -1.95),
        (43.42, -1.80),
        (42.45, 2.95),
        (43.25, 7.50),
        (45.20, 7.70),
        (46.40, 6.65),
        (47.85, 7.55),
        (49.05, 7.40),
        (49.85, 5.95),
        (50.55, 4.10),
    ],
    "spain": [
        (43.78, 3.30),
        (43.45, -1.75),
        (42.15, -3.15),
        (41.65, -7.35),
        (39.60, -7.45),
        (37.05, -7.25),
        (36.00, -5.20),
        (36.15, -2.10),
        (38.15, -0.25),
        (40.35, 0.80),
        (42.35, 2.75),
    ],
    "italy": [
        (46.75, 12.30),
        (46.20, 8.80),
        (44.95, 7.20),
        (43.75, 10.00),
        (42.55, 12.45),
        (41.70, 14.45),
        (40.65, 16.85),
        (39.40, 17.75),
        (38.25, 15.70),
        (39.10, 14.10),
        (40.00, 12.45),
        (41.20, 11.20),
        (42.95, 10.25),
        (44.45, 12.10),
        (45.55, 13.65),
    ],
    "germany": [
        (54.85, 8.20),
        (54.85, 13.95),
        (53.35, 14.15),
        (51.05, 14.70),
        (49.00, 12.25),
        (47.30, 10.45),
        (47.65, 7.65),
        (49.55, 6.10),
        (51.35, 6.15),
        (52.65, 7.20),
        (53.75, 8.70),
    ],
    "romania": [
        (48.25, 22.70),
        (47.95, 26.55),
        (46.90, 28.20),
        (44.45, 28.75),
        (43.70, 26.05),
        (44.20, 22.00),
        (45.35, 21.00),
        (46.55, 21.20),
    ],
    "poland": [
        (54.85, 18.95),
        (54.40, 22.85),
        (51.05, 24.15),
        (49.00, 22.60),
        (49.05, 19.00),
        (49.60, 15.20),
        (51.10, 14.20),
        (53.70, 14.20),
    ],
    "netherlands": [
        (53.65, 6.95),
        (53.45, 4.65),
        (52.95, 4.25),
        (51.95, 4.05),
        (51.25, 4.35),
        (50.78, 5.85),
        (51.50, 6.95),
        (52.70, 6.95),
    ],
    "belgium": [
        (51.50, 3.05),
        (51.45, 5.90),
        (50.75, 6.35),
        (49.50, 5.60),
        (49.45, 3.10),
        (50.25, 2.55),
    ],
    "portugal": [
        (41.90, -8.85),
        (41.25, -7.35),
        (39.40, -7.05),
        (37.00, -7.45),
        (37.00, -8.95),
        (39.00, -9.50),
        (40.70, -8.95),
    ],
    "hungary": [
        (48.55, 18.85),
        (48.05, 22.70),
        (46.20, 22.10),
        (45.75, 18.85),
        (46.15, 16.15),
        (47.20, 16.05),
        (47.90, 17.10),
    ],
    # Simplified outline (mainland + major islands); Natural Earth overrides when cached.
    "greece": [
        (41.52, 26.35),
        (40.95, 23.85),
        (40.15, 22.35),
        (39.05, 22.05),
        (38.25, 23.15),
        (37.45, 22.95),
        (36.35, 23.55),
        (35.65, 24.85),
        (35.05, 25.95),
        (35.20, 27.35),
        (36.45, 28.15),
        (38.25, 27.45),
        (39.85, 26.55),
        (40.85, 25.45),
        (41.35, 23.85),
        (41.70, 21.75),
        (41.25, 20.35),
    ],
}

COUNTRY_ALIASES = {
    "french republic": "france",
    "deutschland": "germany",
    "españa": "spain",
    "italia": "italy",
    "hellas": "greece",
    "ελλάδα": "greece",
}

# Prefer 50m admin boundaries: 110m coastlines are too coarse and admit sea between islands.
_BOUNDARY_CACHE_PATH_50M = Path(".cache") / "boundaries" / "ne_50m_admin_0_countries.geojson"
_BOUNDARY_SOURCE_URL_50M = _NE_VECTOR_BASE + "ne_50m_admin_0_countries.geojson"
_BOUNDARY_CACHE_PATH_110M = Path(".cache") / "boundaries" / "ne_110m_admin_0_countries.geojson"
_BOUNDARY_SOURCE_URL_110M = _NE_VECTOR_BASE + "ne_110m_admin_0_countries.geojson"

# Land mask cache key + rings (110m land bridges narrow seas; default is 50m).
_LAND_RINGS_CACHE_KEY: str | None = None
_LAND_RINGS_CACHE_RINGS: list[list[tuple[float, float]]] | None = None


def natural_earth_land_cache_path() -> Path:
    """On-disk path for the configured Natural Earth land GeoJSON (for tests / ops)."""
    return _natural_earth_land_spec()[0]


def _natural_earth_land_spec() -> tuple[Path, str, int]:
    """Return (cache_path, download_url, timeout_seconds)."""
    v = os.getenv("NATURAL_EARTH_LAND_RESOLUTION", "50").strip().lower()
    if v in ("10", "10m"):
        return (
            Path(".cache") / "boundaries" / "ne_10m_land.geojson",
            _NE_VECTOR_BASE + "ne_10m_land.geojson",
            240,
        )
    if v in ("110", "110m"):
        return (
            Path(".cache") / "boundaries" / "ne_110m_land.geojson",
            _NE_VECTOR_BASE + "ne_110m_land.geojson",
            90,
        )
    return (
        Path(".cache") / "boundaries" / "ne_50m_land.geojson",
        _NE_VECTOR_BASE + "ne_50m_land.geojson",
        120,
    )


def _clear_land_rings_cache() -> None:
    global _LAND_RINGS_CACHE_KEY, _LAND_RINGS_CACHE_RINGS
    _LAND_RINGS_CACHE_KEY = None
    _LAND_RINGS_CACHE_RINGS = None


def normalize_country_name(country: str) -> str:
    key = country.strip().lower()
    if key in COUNTRY_ENVELOPES:
        return key
    return COUNTRY_ALIASES.get(key, key)


def ensure_supported_european_country(country: str) -> CountryEnvelope:
    normalized = normalize_country_name(country)
    envelope = COUNTRY_ENVELOPES.get(normalized)
    if envelope is None:
        supported = ", ".join(sorted(item.name for item in COUNTRY_ENVELOPES.values()))
        raise ValueError(
            f"Unsupported country '{country}'. Supported countries: {supported}."
        )
    return envelope


def generate_candidate_points(
    country: str,
    point_count: int = 100,
    seed: int = 42,
    region: str | None = None,
) -> list[CandidatePoint]:
    if point_count <= 0:
        raise ValueError("point_count must be a positive integer")

    from src.geo import nuts as nuts_geo

    normalized_country = normalize_country_name(country)
    envelope = ensure_supported_european_country(country)
    polygons = _load_country_polygons(normalized_country, envelope)
    if not polygons:
        polygon = COUNTRY_POLYGONS.get(normalized_country)
        if not polygon:
            raise ValueError(f"No border polygon configured for country '{country}'.")
        polygons = [polygon]

    region_trim = (region or "").strip()
    region_polys: list[list[tuple[float, float]]] | None = None
    point_region: str | None = None

    if region_trim:
        if nuts_geo._fold_key(region_trim) == nuts_geo._fold_key(envelope.name):
            region_polys = None
            point_region = region_trim
        else:
            iso = nuts_geo.country_name_to_nuts_iso(normalized_country)
            if not iso:
                raise ValueError(
                    f"NUTS sub-country regions are not configured for {envelope.name}."
                )
            region_polys = nuts_geo.region_label_to_polygons(iso, region_trim)
            if not region_polys:
                raise ValueError(
                    f"No NUTS geometry matched region '{region_trim}' in {envelope.name}. "
                    "Choose a region from the validated list, use the country name for the "
                    "whole territory, or clear the region field."
                )
            point_region = region_trim

    if region_polys:
        sample_bbox = nuts_geo.sampling_bbox_for_region_polys(region_polys, polygons)
        if sample_bbox is None:
            sample_bbox = nuts_geo._bbox_for_polygons(region_polys)
        lat_min, lat_max, lon_min, lon_max = sample_bbox
    else:
        lat_min, lat_max, lon_min, lon_max = _bbox_for_polygons(polygons)

    land_rings = _land_rings_for_sampling_area(lat_min, lat_max, lon_min, lon_max)

    rng = random.Random(seed)
    points: list[CandidatePoint] = []
    attempts = 0
    max_attempts = point_count * (2500 if land_rings else 800)

    while len(points) < point_count:
        attempts += 1
        if attempts > max_attempts:
            raise RuntimeError(
                f"Unable to sample {point_count} points inside "
                f"{envelope.name}"
                f"{(' — ' + region_trim) if region_trim else ''}."
            )

        lat = rng.uniform(lat_min, lat_max)
        lon = rng.uniform(lon_min, lon_max)
        if not _point_in_any_polygon(lat, lon, polygons):
            continue
        if region_polys and not nuts_geo.point_in_any_region_polygon(
            lat, lon, region_polys
        ):
            continue
        if land_rings and not _point_in_any_polygon(lat, lon, land_rings):
            continue

        index = len(points)
        points.append(
            CandidatePoint(
                point_id=f"P{index + 1:03d}",
                country=envelope.name,
                lat=round(lat, 6),
                lon=round(lon, 6),
                region=point_region,
            )
        )
    return points


def _load_country_polygons(
    country_key: str, envelope: CountryEnvelope
) -> list[list[tuple[float, float]]]:
    try:
        features = _load_natural_earth_features()
    except Exception:
        return []

    country_name = envelope.name
    matching = [
        feature
        for feature in features
        if str(feature.get("properties", {}).get("NAME", "")).strip().lower()
        == country_name.lower()
    ]
    if not matching:
        return []

    polygons: list[list[tuple[float, float]]] = []
    for feature in matching:
        geometry = feature.get("geometry", {})
        gtype = geometry.get("type")
        coordinates = geometry.get("coordinates", [])

        if gtype == "Polygon":
            extracted = _extract_rings_from_polygon(coordinates)
            polygons.extend(extracted)
        elif gtype == "MultiPolygon":
            for poly_coords in coordinates:
                extracted = _extract_rings_from_polygon(poly_coords)
                polygons.extend(extracted)

    # Keep polygons overlapping target region envelope to avoid far overseas territories.
    filtered = [
        polygon
        for polygon in polygons
        if _polygon_overlaps_envelope(polygon, envelope)
    ]
    return filtered or polygons


def _load_natural_earth_features() -> list[dict]:
    """Try 50m admin countries first (tighter coasts), then 110m fallback."""
    _BOUNDARY_CACHE_PATH_50M.parent.mkdir(parents=True, exist_ok=True)
    candidates: list[tuple[Path, str, int]] = [
        (_BOUNDARY_CACHE_PATH_50M, _BOUNDARY_SOURCE_URL_50M, 120),
        (_BOUNDARY_CACHE_PATH_110M, _BOUNDARY_SOURCE_URL_110M, 60),
    ]
    for path, url, timeout in candidates:
        try:
            if not path.exists():
                with urlopen(url, timeout=timeout) as response:
                    path.write_text(response.read().decode("utf-8"), encoding="utf-8")
            raw = path.read_text(encoding="utf-8")
            geojson = json.loads(raw)
            features = geojson.get("features", [])
            if isinstance(features, list) and features:
                return features
        except Exception:
            continue
    return []


def _extract_rings_from_polygon(coords: list) -> list[list[tuple[float, float]]]:
    # GeoJSON polygon: [outer_ring, hole1, ...]; we only sample against outer ring.
    if not coords:
        return []
    outer = coords[0]
    if not isinstance(outer, list):
        return []
    polygon: list[tuple[float, float]] = []
    for pair in outer:
        if not isinstance(pair, list) or len(pair) < 2:
            continue
        lon, lat = pair[0], pair[1]
        try:
            polygon.append((float(lat), float(lon)))
        except (TypeError, ValueError):
            continue
    return [polygon] if len(polygon) >= 3 else []


def _polygon_overlaps_envelope(
    polygon: list[tuple[float, float]], envelope: CountryEnvelope
) -> bool:
    lat_min, lat_max, lon_min, lon_max = _bbox_for_polygon(polygon)
    return not (
        lat_max < envelope.lat_min
        or lat_min > envelope.lat_max
        or lon_max < envelope.lon_min
        or lon_min > envelope.lon_max
    )


def _bbox_for_polygon(polygon: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    lats = [item[0] for item in polygon]
    lons = [item[1] for item in polygon]
    return min(lats), max(lats), min(lons), max(lons)


def _bbox_for_polygons(
    polygons: list[list[tuple[float, float]]]
) -> tuple[float, float, float, float]:
    lat_mins: list[float] = []
    lat_maxs: list[float] = []
    lon_mins: list[float] = []
    lon_maxs: list[float] = []

    for polygon in polygons:
        lat_min, lat_max, lon_min, lon_max = _bbox_for_polygon(polygon)
        lat_mins.append(lat_min)
        lat_maxs.append(lat_max)
        lon_mins.append(lon_min)
        lon_maxs.append(lon_max)
    return min(lat_mins), max(lat_maxs), min(lon_mins), max(lon_maxs)


def _point_in_any_polygon(
    lat: float, lon: float, polygons: list[list[tuple[float, float]]]
) -> bool:
    return any(_point_in_polygon(lat, lon, polygon) for polygon in polygons)


def _point_in_polygon(
    lat: float, lon: float, polygon: list[tuple[float, float]]
) -> bool:
    # Ray-casting on (x=lon, y=lat).
    inside = False
    x = lon
    y = lat
    n = len(polygon)
    j = n - 1

    for i in range(n):
        yi, xi = polygon[i]
        yj, xj = polygon[j]
        intersects = (yi > y) != (yj > y)
        if intersects:
            x_at_y = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < x_at_y:
                inside = not inside
        j = i
    return inside


def _geometry_to_land_rings(geometry: dict) -> list[list[tuple[float, float]]]:
    gtype = geometry.get("type")
    coordinates = geometry.get("coordinates", [])
    if gtype == "Polygon":
        return _extract_rings_from_polygon(coordinates)
    if gtype == "MultiPolygon":
        combined: list[list[tuple[float, float]]] = []
        for poly_coords in coordinates:
            combined.extend(_extract_rings_from_polygon(poly_coords))
        return combined
    return []


def _load_all_land_rings() -> list[list[tuple[float, float]]]:
    global _LAND_RINGS_CACHE_KEY, _LAND_RINGS_CACHE_RINGS
    path, url, timeout = _natural_earth_land_spec()
    cache_key = str(path.resolve())
    if _LAND_RINGS_CACHE_KEY == cache_key and _LAND_RINGS_CACHE_RINGS is not None:
        return _LAND_RINGS_CACHE_RINGS
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with urlopen(url, timeout=timeout) as response:
            path.write_bytes(response.read())
    raw = path.read_text(encoding="utf-8")
    geojson = json.loads(raw)
    features = geojson.get("features", [])
    if not isinstance(features, list):
        rings: list[list[tuple[float, float]]] = []
        _LAND_RINGS_CACHE_KEY = cache_key
        _LAND_RINGS_CACHE_RINGS = rings
        return rings
    rings = []
    for feature in features:
        if not isinstance(feature, dict):
            continue
        geom = feature.get("geometry")
        if not isinstance(geom, dict):
            continue
        for ring in _geometry_to_land_rings(geom):
            if len(ring) >= 3:
                rings.append(ring)
    _LAND_RINGS_CACHE_KEY = cache_key
    _LAND_RINGS_CACHE_RINGS = rings
    return rings


def _bbox_intersects_bbox(
    poly_bbox: tuple[float, float, float, float],
    box: tuple[float, float, float, float],
) -> bool:
    lat_lo, lat_hi, lon_lo, lon_hi = poly_bbox
    b_lat_lo, b_lat_hi, b_lon_lo, b_lon_hi = box
    return not (
        lat_hi < b_lat_lo
        or lat_lo > b_lat_hi
        or lon_hi < b_lon_lo
        or lon_lo > b_lon_hi
    )


def _land_rings_for_sampling_area(
    lat_min: float, lat_max: float, lon_min: float, lon_max: float
) -> list[list[tuple[float, float]]]:
    """Land polygons overlapping the sample bbox (Natural Earth land layer). Empty if load fails."""
    try:
        all_rings = _load_all_land_rings()
    except Exception:
        path, _, _ = _natural_earth_land_spec()
        warnings.warn(
            f"Could not load land mask ({path.name}); candidate points may include ocean. "
            f"Run once online to cache {path}. "
            "For narrow straits use NATURAL_EARTH_LAND_RESOLUTION=10 (ne_10m_land, larger download).",
            UserWarning,
            stacklevel=2,
        )
        return []
    if not all_rings:
        return []

    def pick(box: tuple[float, float, float, float]) -> list[list[tuple[float, float]]]:
        out: list[list[tuple[float, float]]] = []
        for ring in all_rings:
            if _bbox_intersects_bbox(_bbox_for_polygon(ring), box):
                out.append(ring)
        return out

    sample = (lat_min, lat_max, lon_min, lon_max)
    pad = 0.35
    padded = (lat_min - pad, lat_max + pad, lon_min - pad, lon_max + pad)
    selected = pick(padded)
    if not selected:
        selected = pick(sample)
    if not selected:
        return all_rings
    return selected

