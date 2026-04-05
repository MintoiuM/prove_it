from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from src.collectors.http_utils import HttpJsonClient
from src.collectors.weather_worker import (
    features_from_open_meteo_hourly,
    open_meteo_archive_query_params,
)


def resolve_open_meteo_archive_endpoint(weather_endpoint: str) -> str:
    """Use configured archive URL when it looks like Open-Meteo archive; else default."""
    u = (weather_endpoint or "").strip().lower()
    if "archive-api.open-meteo.com" in u or "/v1/archive" in u:
        return weather_endpoint.strip()
    raw = os.getenv("OPEN_METEO_ARCHIVE_ENDPOINT", "").strip()
    if raw:
        return raw
    return "https://archive-api.open-meteo.com/v1/archive"


def fetch_open_meteo_history_features(
    lat: float,
    lon: float,
    *,
    client: HttpJsonClient,
    archive_endpoint: str,
    start_date: str,
    end_date: str,
) -> tuple[dict[str, float], dict[str, Any]]:
    params = open_meteo_archive_query_params(lat, lon, start_date, end_date)
    diagnostics: dict[str, Any] = {
        "ok": False,
        "source": "open-meteo-archive-validation",
        "error": None,
    }
    try:
        payload = client.get_json(archive_endpoint, params=params, use_cache=True)
        hourly = payload.get("hourly", {})
        features = features_from_open_meteo_hourly(hourly)
        diagnostics["ok"] = bool(features)
        if not features:
            diagnostics["error"] = "Open-Meteo archive returned no usable hourly series."
        return features, diagnostics
    except Exception as exc:
        diagnostics["error"] = str(exc)
        return {}, diagnostics


def _compare_metric(
    key: str,
    scored: float | None,
    hist: float | None,
    *,
    temp_close_c: float = 3.0,
    rain_rel_close: float = 0.35,
) -> tuple[str | None, str | None]:
    if scored is None or hist is None:
        return None, None
    if key == "mean_temp_c":
        d = abs(float(scored) - float(hist))
        note = f"{key}: run {scored:.1f} °C vs archive {hist:.1f} °C (Δ {d:.1f})"
        return note, "close" if d <= temp_close_c else "divergent"
    if key == "rainfall_mm":
        s, h = float(scored), float(hist)
        if h <= 1e-6:
            rel = 1.0 if s > 1 else 0.0
        else:
            rel = abs(s - h) / h
        note = f"{key}: run {s:.0f} mm/yr eq. vs archive {h:.0f} mm/yr eq. (rel Δ {rel:.0%})"
        return note, "close" if rel <= rain_rel_close else "divergent"
    if key == "humidity_pct":
        d = abs(float(scored) - float(hist))
        note = f"{key}: run {scored:.0f}% vs archive {hist:.0f}% (Δ {d:.0f})"
        return note, "close" if d <= 12.0 else "divergent"
    if key == "frost_risk":
        d = abs(float(scored) - float(hist))
        note = f"{key}: run {scored:.3f} vs archive {hist:.3f} (Δ {d:.3f})"
        return note, "close" if d <= 0.08 else "divergent"
    return None, None


def build_validation_payload(
    scored_row: dict[str, Any],
    hist_features: dict[str, float],
) -> dict[str, Any]:
    notes: list[str] = []
    divergent = 0
    compared = 0
    for key in ("mean_temp_c", "rainfall_mm", "humidity_pct", "frost_risk"):
        sv = scored_row.get(key)
        hv = hist_features.get(key)
        if sv is None or hv is None:
            continue
        try:
            sf = float(sv)
            hf = float(hv)
        except (TypeError, ValueError):
            continue
        note, grade = _compare_metric(key, sf, hf)
        if note:
            notes.append(note)
            compared += 1
            if grade == "divergent":
                divergent += 1

    if divergent == 0 and compared > 0:
        overall = "aligned"
    elif divergent <= 1 and compared > 0:
        overall = "mostly_aligned"
    elif compared > 0:
        overall = "review"
    else:
        overall = "insufficient_overlap"

    return {
        "open_meteo_history_vs_run_grade": overall,
        "open_meteo_history_comparison_lines": notes,
    }


def attach_open_meteo_history_to_top_candidates(
    ranked_rows: list[dict[str, Any]],
    merged_by_point_id: dict[str, dict[str, Any]],
    *,
    client: HttpJsonClient,
    archive_endpoint: str,
    start_date: str,
    end_date: str,
    max_workers: int = 4,
) -> dict[str, Any]:
    """
    For each top candidate, fetch Open-Meteo archive over [start_date, end_date] with the same
    hourly parameters as WeatherWorker, and compare to the weather used in scoring.
    """
    summary_ok = 0
    summary_fail = 0

    def job(row: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        pid = str(row.get("point_id", ""))
        scored = merged_by_point_id.get(pid, row)
        lat = float(scored["lat"])
        lon = float(scored["lon"])
        hist, diag = fetch_open_meteo_history_features(
            lat,
            lon,
            client=client,
            archive_endpoint=archive_endpoint,
            start_date=start_date,
            end_date=end_date,
        )
        out: dict[str, Any] = {
            "open_meteo_history_ok": diag.get("ok", False),
            "open_meteo_history_error": diag.get("error"),
            "open_meteo_history_features": hist,
            "open_meteo_history_start_date": start_date,
            "open_meteo_history_end_date": end_date,
            "open_meteo_history_endpoint": archive_endpoint,
        }
        if hist:
            cmp_payload = build_validation_payload(scored, hist)
            out.update(cmp_payload)
            lines = cmp_payload.get("open_meteo_history_comparison_lines") or []
            out["open_meteo_history_validation_text"] = (
                "Open-Meteo archive (" + start_date + " → " + end_date + "): " + " ".join(lines)
                if lines
                else "Open-Meteo archive fetched; limited overlap with scored metrics for comparison."
            )
        else:
            out["open_meteo_history_vs_run_grade"] = None
            out["open_meteo_history_comparison_lines"] = []
            out["open_meteo_history_validation_text"] = (
                "Open-Meteo archive unavailable: " + str(diag.get("error") or "no data")
            )
        return pid, out

    updates: dict[str, dict[str, Any]] = {}
    workers = max(1, min(max_workers, len(ranked_rows)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(job, row): row for row in ranked_rows}
        for future in as_completed(futures):
            pid, payload = future.result()
            updates[pid] = payload

    for row in ranked_rows:
        pid = str(row.get("point_id", ""))
        extra = updates.get(pid, {})
        row.update(extra)
        if extra.get("open_meteo_history_ok"):
            summary_ok += 1
        else:
            summary_fail += 1

    return {
        "open_meteo_validation_endpoint": archive_endpoint,
        "open_meteo_validation_date_range": f"{start_date}..{end_date}",
        "open_meteo_validation_top_n_ok": summary_ok,
        "open_meteo_validation_top_n_failed": summary_fail,
    }
