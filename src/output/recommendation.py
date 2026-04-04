from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


def ensure_run_dir(base_dir: Path, run_id: str) -> Path:
    run_dir = base_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            normalized = dict(row)
            for key, value in normalized.items():
                if isinstance(value, (list, dict)):
                    normalized[key] = json.dumps(value, ensure_ascii=True)
            writer.writerow(normalized)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=True)


def build_recommendation_payload(
    run_id: str,
    country: str,
    crop: str,
    best_point: dict[str, Any],
    ranked_points: list[dict[str, Any]],
    summary: dict[str, Any],
    ranking_engine: str,
    llm_model: str | None = None,
) -> dict[str, Any]:
    payload = {
        "run_id": run_id,
        "country": country,
        "crop": crop,
        "ranking_engine": ranking_engine,
        "best_point": best_point,
        "top_candidates": ranked_points,
        "operational_area": {
            "center_lat": best_point["lat"],
            "center_lon": best_point["lon"],
            "radius_km": 100.0,
            "geometry_type": "circle",
        },
        "summary": summary,
        "score_explanation": (
            "Score combines weather and soil fit against crop-specific ideal ranges, "
            "then applies calibrated penalties for missing features and hard-threshold "
            "violations. Score bands: poor (<40), fair (40-59), good (60-79), "
            "excellent (80-100)."
        ),
    }
    if llm_model:
        payload["llm_model"] = llm_model
    return payload

