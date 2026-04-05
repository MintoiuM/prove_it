from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from src.data.nuts2_yields import Nuts2YieldStore

# Eurostat GISCO NUTS 2021, 20M — small enough to cache (~0.6MB + ~0.2MB per level).
_NUTS_BASE = (
    "https://gisco-services.ec.europa.eu/distribution/v2/nuts/geojson/"
    "NUTS_RG_20M_2021_4326_LEVL_{lev}.geojson"
)
_CACHE_DIR = Path(".cache") / "nuts"
_CACHE_PATHS = {lev: _CACHE_DIR / f"NUTS_RG_20M_2021_4326_LEVL_{lev}.geojson" for lev in (1, 2)}


def _bbox_for_polygon(polygon: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    lats = [item[0] for item in polygon]
    lons = [item[1] for item in polygon]
    return min(lats), max(lats), min(lons), max(lons)


def _bbox_for_polygons(
    polygons: list[list[tuple[float, float]]],
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


def _point_in_polygon(lat: float, lon: float, polygon: list[tuple[float, float]]) -> bool:
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

# Natural Earth admin country name -> Eurostat CNTR_CODE (Greece uses EL).
_COUNTRY_NAME_TO_ISO: dict[str, str] = {
    "france": "FR",
    "germany": "DE",
    "spain": "ES",
    "italy": "IT",
    "romania": "RO",
    "poland": "PL",
    "netherlands": "NL",
    "belgium": "BE",
    "portugal": "PT",
    "hungary": "HU",
    "greece": "EL",
    "belgium": "BE",
}

_features_cache: dict[int, list[dict[str, Any]]] | None = None


def country_name_to_nuts_iso(normalized_country_key: str) -> str | None:
    return _COUNTRY_NAME_TO_ISO.get(normalized_country_key.strip().lower())


def _ensure_cache_dir() -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _load_nuts_features(level: int) -> list[dict[str, Any]]:
    global _features_cache
    if _features_cache is None:
        _features_cache = {}
    if level in _features_cache:
        return _features_cache[level]

    _ensure_cache_dir()
    path = _CACHE_PATHS[level]
    if not path.exists():
        url = _NUTS_BASE.format(lev=level)
        with urlopen(url, timeout=120) as response:
            path.write_bytes(response.read())

    raw = path.read_text(encoding="utf-8")
    geo = json.loads(raw)
    feats = geo.get("features", [])
    if not isinstance(feats, list):
        feats = []
    _features_cache[level] = feats
    return feats


def _normalize_label(label: str) -> str:
    s = label.strip()
    s = re.sub(r"\s*\([^)]*\bNUTS\b[^)]*\)\s*$", "", s, flags=re.I).strip()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.replace("—", "-").replace("–", "-").replace("ş", "s").replace("Ş", "S")
    s = s.lower()
    # Keep letters/digits from any script (Greek, Cyrillic, …). ASCII-only [a-z0-9]
    # strips exonyms like "Aττική" down to a single Latin "a" and breaks matching.
    s = "".join(ch if (ch.isalnum() or ch.isspace()) else " " for ch in s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _fold_key(label: str) -> str:
    return re.sub(r"\s+", "", _normalize_label(label))


def _features_for_iso(iso: str, level: int) -> list[dict[str, Any]]:
    iso = iso.strip().upper()
    out: list[dict[str, Any]] = []
    for feat in _load_nuts_features(level):
        props = feat.get("properties") or {}
        if str(props.get("CNTR_CODE", "")).upper() != iso:
            continue
        out.append(feat)
    return out


def find_nuts_feature_names_for_iso(iso: str) -> list[str]:
    names: set[str] = set()
    for lev in (2, 1):
        for feat in _features_for_iso(iso, lev):
            props = feat.get("properties") or {}
            n = props.get("NUTS_NAME") or props.get("NAME_LATN")
            if isinstance(n, str) and n.strip():
                names.add(n.strip())
    return sorted(names, key=str.casefold)


def _match_features(iso: str, region_label: str) -> list[dict[str, Any]]:
    folded = _fold_key(region_label)
    if len(folded) < 2:
        return []

    for lev in (2, 1):
        feats = _features_for_iso(iso, lev)
        exact = [
            f
            for f in feats
            if _fold_key(str((f.get("properties") or {}).get("NUTS_NAME", ""))) == folded
        ]
        if exact:
            return exact
        exact = [
            f
            for f in feats
            if _fold_key(str((f.get("properties") or {}).get("NAME_LATN", ""))) == folded
        ]
        if exact:
            return exact

    if len(folded) >= 5:
        for lev in (2, 1):
            feats = _features_for_iso(iso, lev)
            loose: list[dict[str, Any]] = []
            for f in feats:
                props = f.get("properties") or {}
                # Prefer Latin exonyms first (typical CSV / UI labels).
                for key in ("NAME_LATN", "NUTS_NAME"):
                    nk = _fold_key(str(props.get(key, "")))
                    if not nk:
                        continue
                    short = min(len(nk), len(folded))
                    if short < 4:
                        continue
                    if nk in folded or folded in nk:
                        loose.append(f)
                        break
            if loose:
                return loose
    return []


def _ring_geojson_to_latlon_ring(ring: list) -> list[tuple[float, float]]:
    poly: list[tuple[float, float]] = []
    for pair in ring:
        if not isinstance(pair, list) or len(pair) < 2:
            continue
        try:
            lon, lat = float(pair[0]), float(pair[1])
        except (TypeError, ValueError):
            continue
        poly.append((lat, lon))
    return poly if len(poly) >= 3 else []


def geometry_to_latlon_polygons(geometry: dict[str, Any]) -> list[list[tuple[float, float]]]:
    gtype = geometry.get("type")
    coords = geometry.get("coordinates", [])
    polygons: list[list[tuple[float, float]]] = []

    if gtype == "Polygon":
        if isinstance(coords, list) and coords:
            outer = _ring_geojson_to_latlon_ring(coords[0])
            if outer:
                polygons.append(outer)
    elif gtype == "MultiPolygon":
        if isinstance(coords, list):
            for poly_coords in coords:
                if isinstance(poly_coords, list) and poly_coords:
                    outer = _ring_geojson_to_latlon_ring(poly_coords[0])
                    if outer:
                        polygons.append(outer)
    return polygons


def region_label_to_polygons(iso: str, region_label: str) -> list[list[tuple[float, float]]]:
    """Return sampling polygons (lat, lon outer rings) for a NUTS region name."""
    feats = _match_features(iso, region_label)
    polygons: list[list[tuple[float, float]]] = []
    for feat in feats:
        geom = feat.get("geometry")
        if isinstance(geom, dict):
            polygons.extend(geometry_to_latlon_polygons(geom))
    return polygons


def list_csv_regions_matching_iso(
    iso: str, csv_region_names: list[str], country_display_name: str
) -> list[str]:
    """CSV region labels that resolve to NUTS geometry for this country, plus national aggregate."""
    iso = iso.strip().upper()
    country_fold = _fold_key(country_display_name)
    matched: list[str] = []
    seen: set[str] = set()
    for raw in csv_region_names:
        label = raw.strip()
        if not label:
            continue
        if _fold_key(label) == country_fold:
            key = label.casefold()
            if key not in seen:
                seen.add(key)
                matched.append(label)
            continue
        polys = region_label_to_polygons(iso, label)
        if polys:
            key = label.casefold()
            if key not in seen:
                seen.add(key)
                matched.append(label)
    return sorted(matched, key=str.casefold)


def bbox_intersection(
    a: tuple[float, float, float, float], b: tuple[float, float, float, float]
) -> tuple[float, float, float, float] | None:
    lat_min = max(a[0], b[0])
    lat_max = min(a[1], b[1])
    lon_min = max(a[2], b[2])
    lon_max = min(a[3], b[3])
    if lat_min >= lat_max or lon_min >= lon_max:
        return None
    return lat_min, lat_max, lon_min, lon_max


def point_in_any_region_polygon(
    lat: float, lon: float, region_polys: list[list[tuple[float, float]]]
) -> bool:
    return any(_point_in_polygon(lat, lon, poly) for poly in region_polys)


def sampling_bbox_for_region_polys(
    region_polys: list[list[tuple[float, float]]],
    country_polys: list[list[tuple[float, float]]],
) -> tuple[float, float, float, float] | None:
    rb = _bbox_for_polygons(region_polys)
    cb = _bbox_for_polygons(country_polys)
    return bbox_intersection(rb, cb)


def fold_region_key(label: str) -> str:
    """Public alias for matching regional CSV labels to NUTS names."""
    return _fold_key(label)


def find_nuts_region_name_for_point(lat: float, lon: float, iso: str) -> str | None:
    """Return NUTS_NAME for the finest polygon (LEVL 2 before LEVL 1) containing the point."""
    iso_u = iso.strip().upper()
    for lev in (2, 1):
        for feat in _features_for_iso(iso_u, lev):
            geom = feat.get("geometry")
            if not isinstance(geom, dict):
                continue
            for poly in geometry_to_latlon_polygons(geom):
                if len(poly) >= 3 and _point_in_polygon(lat, lon, poly):
                    props = feat.get("properties") or {}
                    latn = props.get("NAME_LATN")
                    if isinstance(latn, str) and latn.strip():
                        return latn.strip()
                    name = props.get("NUTS_NAME")
                    if isinstance(name, str) and name.strip():
                        return name.strip()
    return None


def region_dropdown_choices(
    country: str,
    store: Nuts2YieldStore | None,
) -> list[dict[str, str]]:
    """Whole country plus CSV region labels that resolve to NUTS geometry for the country."""
    from src.geo.grid import ensure_supported_european_country, normalize_country_name

    choices: list[dict[str, str]] = [{"value": "", "label": "Whole country"}]
    try:
        envelope = ensure_supported_european_country(country)
    except ValueError:
        return choices
    normalized = normalize_country_name(country)
    iso = country_name_to_nuts_iso(normalized)
    if store is None or not iso:
        return choices
    matched = list_csv_regions_matching_iso(
        iso, store.unique_region_labels(), envelope.name
    )
    for label in matched:
        choices.append({"value": label, "label": label})
    return choices
