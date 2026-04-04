from __future__ import annotations

import csv
import math
import re
from pathlib import Path
from typing import Any

# Columns in nuts2_crop_yields_all_regions.csv
_COL_CORN = "Corn(tons/ha)"
_COL_SUN = "Sunflower(tons/ha)"
_COL_WHEAT = "Wheat(tons/ha)"


def crop_slug_to_yield_column(crop_slug: str) -> str | None:
    key = crop_slug.strip().lower().replace(" ", "_")
    if key in ("corn", "maize"):
        return _COL_CORN
    if key == "wheat":
        return _COL_WHEAT
    if key == "sunflower":
        return _COL_SUN
    return None


def _clean_region_label(raw: str) -> str:
    return raw.strip()


def _strip_nuts_parenthetical(name: str) -> str:
    return re.sub(r"\s*\([^)]*\bNUTS\b[^)]*\)\s*$", "", name, flags=re.I).strip()


def _parse_yield_cell(raw: str) -> float | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or s.lower() in ("nan", "none", "n/a"):
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    if not math.isfinite(v) or v < 0:
        return None
    return v


class Nuts2YieldStore:
    """Latest-year yield (tons/ha) per region label from Eurostat-style CSV."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._by_region: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        text = self._path.read_text(encoding="utf-8")
        reader = csv.DictReader(text.splitlines())
        if not reader.fieldnames:
            return
        by_key: dict[str, dict[str, Any]] = {}
        for row in reader:
            region = _clean_region_label(row.get("Region", "") or "")
            if not region:
                continue
            region = _strip_nuts_parenthetical(region)
            try:
                year = int(str(row.get("Year", "")).strip())
            except ValueError:
                continue
            key = region.casefold()
            prev = by_key.get(key)
            if prev is None or year >= prev["year"]:
                by_key[key] = {
                    "year": year,
                    "region": region,
                    "corn": _parse_yield_cell(row.get(_COL_CORN)),
                    "sunflower": _parse_yield_cell(row.get(_COL_SUN)),
                    "wheat": _parse_yield_cell(row.get(_COL_WHEAT)),
                }
        self._by_region = by_key

    def lookup_yield_tons_ha(self, region_label: str, crop_slug: str) -> float | None:
        col = crop_slug_to_yield_column(crop_slug)
        if col is None:
            return None
        key = _strip_nuts_parenthetical(region_label.strip()).casefold()
        row = self._by_region.get(key)
        if row is None:
            return None
        if col == _COL_CORN:
            return row.get("corn")
        if col == _COL_SUN:
            return row.get("sunflower")
        if col == _COL_WHEAT:
            return row.get("wheat")
        return None

    def unique_region_labels(self) -> list[str]:
        return sorted({v["region"] for v in self._by_region.values()}, key=str.casefold)

    def latest_year(self, region_label: str) -> int | None:
        key = _strip_nuts_parenthetical(region_label.strip()).casefold()
        row = self._by_region.get(key)
        return int(row["year"]) if row else None


def yield_to_score_0_100(tons_ha: float, crop_slug: str) -> float:
    """Map observed yield to 0–100 using coarse plausible EU ranges (tons/ha)."""
    key = crop_slug.strip().lower().replace(" ", "_")
    if key in ("corn", "maize"):
        lo, hi = 3.0, 14.0
    elif key == "wheat":
        lo, hi = 2.0, 9.0
    elif key == "sunflower":
        lo, hi = 0.8, 3.5
    else:
        lo, hi = 2.0, 12.0
    if hi <= lo:
        return 50.0
    t = (tons_ha - lo) / (hi - lo)
    return max(0.0, min(100.0, 100.0 * t))


def blend_rules_score_with_yield(rules_score: float, yield_score: float | None) -> float:
    """Slightly tilt the rules score using regional yield quality (same for all points in a run)."""
    if yield_score is None:
        return rules_score
    w = 0.18
    mix = (1.0 - w) * rules_score + w * yield_score
    return round(max(0.0, min(100.0, mix)), 3)
