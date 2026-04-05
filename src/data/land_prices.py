from __future__ import annotations

import csv
import math
import re
from pathlib import Path

from src.geo.nuts import fold_region_key

_COL_PRICE = "Price_EUR_per_Hectare"


def _strip_nuts_parenthetical(name: str) -> str:
    return re.sub(r"\s*\([^)]*\bNUTS\b[^)]*\)\s*$", "", name, flags=re.I).strip()


def _parse_price_cell(raw: str) -> float | None:
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


class LandPriceStore:
    """Latest-year land purchase value (EUR/ha) per region from Price_EUR_per_Hectare."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._by_fold: dict[str, dict[str, str | int | float]] = {}
        self._load()

    def _load(self) -> None:
        text = self._path.read_text(encoding="utf-8")
        reader = csv.DictReader(text.splitlines())
        if not reader.fieldnames:
            return
        for row in reader:
            region = _strip_nuts_parenthetical((row.get("Region") or "").strip())
            if not region:
                continue
            try:
                year = int(str(row.get("Year", "")).strip())
            except ValueError:
                continue
            price = _parse_price_cell(row.get(_COL_PRICE))
            if price is None:
                continue
            key = fold_region_key(region)
            prev = self._by_fold.get(key)
            if prev is None or year >= int(prev["year"]):
                self._by_fold[key] = {
                    "region": region,
                    "year": year,
                    "buyout_eur_per_ha": price,
                }

    def lookup(self, region_label: str) -> tuple[float, int, str] | None:
        """Return (purchase EUR per hectare, data year, canonical CSV region name)."""
        key = fold_region_key(_strip_nuts_parenthetical(region_label.strip()))
        row = self._by_fold.get(key)
        if row is None:
            return None
        return (
            float(row["buyout_eur_per_ha"]),
            int(row["year"]),
            str(row["region"]),
        )

    def unique_region_labels(self) -> list[str]:
        return sorted({str(v["region"]) for v in self._by_fold.values()}, key=str.casefold)
