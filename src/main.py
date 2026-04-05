from __future__ import annotations

import argparse
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

from src.collectors.europe_soil_csv import EuropeCsvSoilWorker
from src.collectors.google_weather_worker import GoogleForecastWeatherWorker
from src.collectors.http_utils import HttpJsonClient, RetryPolicy
from src.collectors.open_meteo_validation import (
    attach_open_meteo_history_to_top_candidates,
    resolve_open_meteo_archive_endpoint,
)
from src.collectors.soil_worker import SoilWorker
from src.collectors.weather_worker import WeatherWorker
from src.config import Settings, resolve_land_prices_csv_path, resolve_nuts2_yields_csv_path
from src.data.land_prices import LandPriceStore
from src.data.nuts2_yields import (
    Nuts2YieldStore,
    blend_rules_score_with_yield,
    crop_slug_to_yield_column,
    yield_to_score_0_100,
)
from src.geo.grid import generate_candidate_points, normalize_country_name
from src.geo.nuts import country_name_to_nuts_iso, find_nuts_region_name_for_point
from src.io.cache import FileCache
from src.models.crop_profiles import get_crop_profile, list_crop_names
from src.output.recommendation import (
    build_recommendation_payload,
    ensure_run_dir,
    write_csv,
    write_json,
)
from src.output.rules_reasoning import build_site_reasoning
from src.scoring.gemini_ranking import rank_with_gemini
from src.scoring.llm_ranking import rank_with_llama3
from src.scoring.suitability import rank_candidates
from src.types import CandidatePoint


def parse_args() -> argparse.Namespace:
    settings = Settings.from_env()
    parser = argparse.ArgumentParser(description="Europe crop suitability MVP")
    parser.add_argument("--country", required=True, help="Supported European country name")
    parser.add_argument(
        "--crop",
        required=True,
        choices=list_crop_names(),
        help="Crop profile to evaluate",
    )
    parser.add_argument("--points", type=int, default=settings.default_points)
    parser.add_argument("--seed", type=int, default=settings.default_seed)
    parser.add_argument("--top-n", type=int, default=settings.default_top_n)
    parser.add_argument("--start-date", default=settings.default_start_date)
    parser.add_argument("--end-date", default=settings.default_end_date)
    parser.add_argument(
        "--demo-safe",
        action="store_true",
        help="Use conservative throttling and low parallelism.",
    )
    parser.add_argument(
        "--use-llm",
        action="store_true",
        help="Use Llama 3 (Ollama) to score and rank candidates.",
    )
    parser.add_argument(
        "--risk-analysis",
        action="store_true",
        help="Compute risk profile and risk level for each candidate.",
    )
    parser.add_argument(
        "--extended-reasoning",
        action="store_true",
        help="Ask LLM for longer agronomic explanations.",
    )
    parser.add_argument(
        "--region",
        default="",
        help="NUTS / Eurostat region label from nuts2_crop_yields_all_regions.csv (optional).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_pipeline(
        country=args.country,
        crop=args.crop,
        points=args.points,
        seed=args.seed,
        top_n=args.top_n,
        start_date=args.start_date,
        end_date=args.end_date,
        demo_safe=args.demo_safe,
        use_llm=args.use_llm,
        risk_analysis=args.risk_analysis,
        extended_reasoning=args.extended_reasoning,
        region=(args.region.strip() or None),
    )
    best_point = result["best_point"]

    print(f"Run completed: {result['run_id']}")
    reg = result.get("region")
    reg_part = f", Region: {reg}" if reg else ""
    print(f"Country: {result['country']}{reg_part}, Crop: {result['crop']}")
    print(
        "Best point: "
        f"{best_point['point_id']} ({best_point['lat']}, {best_point['lon']}) "
        f"score={best_point['score']} confidence={best_point['confidence']}"
    )
    print(f"Artifacts: {result['run_dir']}")
    return 0


def _field_size_hectares() -> float:
    raw = os.getenv("FIELD_RENT_HECTARES", "10")
    try:
        v = float(raw)
    except ValueError:
        return 10.0
    return max(0.01, min(1_000_000.0, v))


def _land_monthly_rent_fraction_of_buyout() -> float:
    """Monthly rent = this fraction × total field buy-out (default 1.8% per month)."""
    raw = os.getenv("LAND_MONTHLY_RENT_PCT", "1.8")
    try:
        pct = float(raw)
    except ValueError:
        pct = 1.8
    return max(0.0, min(100.0, pct)) / 100.0


def _attach_land_rent_to_top_candidates(
    rows: list[dict[str, Any]],
    country_name: str,
    land_store: LandPriceStore | None,
    field_ha: float,
) -> None:
    """Attach buy-out (CSV €/ha purchase) and modelled monthly rent for top-N rows only."""
    monthly_frac = _land_monthly_rent_fraction_of_buyout()
    for row in rows:
        row["field_hectares_for_land_estimate"] = field_ha
        if land_store is None:
            row["land_price_matched_region"] = None
            row["land_buyout_eur_per_ha"] = None
            row["land_value_data_year"] = None
            row["land_buyout_field_eur"] = None
            row["land_monthly_rent_eur"] = None
            continue
        try:
            lat = float(row["lat"])
            lon = float(row["lon"])
        except (TypeError, ValueError, KeyError):
            row["land_price_matched_region"] = None
            row["land_buyout_eur_per_ha"] = None
            row["land_value_data_year"] = None
            row["land_buyout_field_eur"] = None
            row["land_monthly_rent_eur"] = None
            continue

        iso = country_name_to_nuts_iso(normalize_country_name(country_name))
        region_hint: str | None = None
        if iso:
            region_hint = find_nuts_region_name_for_point(lat, lon, iso)
        if not region_hint and row.get("nuts_region"):
            region_hint = str(row["nuts_region"]).strip() or None
        if not region_hint:
            region_hint = country_name

        hit = land_store.lookup(region_hint) if region_hint else None
        if hit is None:
            hit = land_store.lookup(country_name)
        if hit is None:
            row["land_price_matched_region"] = None
            row["land_buyout_eur_per_ha"] = None
            row["land_value_data_year"] = None
            row["land_buyout_field_eur"] = None
            row["land_monthly_rent_eur"] = None
            continue

        buyout_per_ha, year, csv_label = hit
        buyout_field = buyout_per_ha * field_ha
        row["land_price_matched_region"] = csv_label
        row["land_buyout_eur_per_ha"] = round(buyout_per_ha, 2)
        row["land_value_data_year"] = year
        row["land_buyout_field_eur"] = round(buyout_field, 2)
        row["land_monthly_rent_eur"] = round(monthly_frac * buyout_field, 2)


def _nuts2_yield_lookup_label(points: list[CandidatePoint]) -> str | None:
    if not points:
        return None
    if points[0].region:
        return points[0].region
    return points[0].country


def _apply_nuts2_yield_scores(
    rows: list[dict[str, Any]],
    crop_slug: str,
    yield_label: str | None,
    store: Nuts2YieldStore | None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "nuts2_yield_tons_ha": None,
        "nuts2_yield_year": None,
        "nuts2_yield_score": None,
        "nuts2_yield_applied": False,
        "nuts2_crop_in_file": crop_slug_to_yield_column(crop_slug) is not None,
    }
    if store is None or not yield_label:
        return meta
    if crop_slug_to_yield_column(crop_slug) is None:
        return meta
    tons = store.lookup_yield_tons_ha(yield_label, crop_slug)
    year = store.latest_year(yield_label)
    if tons is None:
        return meta
    yscore = yield_to_score_0_100(tons, crop_slug)
    meta.update(
        {
            "nuts2_yield_tons_ha": tons,
            "nuts2_yield_year": year,
            "nuts2_yield_score": round(yscore, 2),
            "nuts2_yield_applied": True,
        }
    )
    for row in rows:
        base = float(row.get("score", 0.0) or 0.0)
        row["rules_score_before_nuts2"] = base
        row["score"] = blend_rules_score_with_yield(base, yscore)
    return meta


def run_pipeline(
    country: str,
    crop: str,
    points: int,
    seed: int,
    top_n: int,
    start_date: str,
    end_date: str,
    demo_safe: bool,
    use_llm: bool = False,
    risk_analysis: bool = False,
    extended_reasoning: bool = False,
    region: str | None = None,
) -> dict[str, Any]:
    settings = Settings.from_env()
    run_id = f"run_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:6]}"
    run_dir = ensure_run_dir(settings.runs_dir, run_id)
    cache = FileCache(settings.cache_dir)

    crop_profile = get_crop_profile(crop)
    nuts2_path = resolve_nuts2_yields_csv_path()
    nuts2_store = Nuts2YieldStore(nuts2_path) if nuts2_path else None

    generated_points = generate_candidate_points(
        country, point_count=points, seed=seed, region=region
    )

    weather_workers = 2 if demo_safe else settings.weather_workers
    weather_client = HttpJsonClient(
        retry_policy=RetryPolicy(
            timeout_seconds=settings.request_timeout_seconds,
            retries=settings.request_retries,
            backoff_base_seconds=settings.request_backoff_base_seconds,
            backoff_max_seconds=settings.request_backoff_max_seconds,
            min_interval_seconds=max(
                settings.weather_min_interval_seconds, 0.3 if demo_safe else 0.0
            ),
        ),
        cache=cache,
    )
    if settings.weather_backend == "google_forecast" and settings.google_maps_api_key:
        weather_worker = GoogleForecastWeatherWorker(
            weather_client, settings.google_maps_api_key
        )
    else:
        weather_worker = WeatherWorker(
            client=weather_client,
            endpoint=settings.weather_endpoint,
            start_date=start_date,
            end_date=end_date,
        )
    if settings.soil_dataset_csv_path is not None:
        soil_worker = EuropeCsvSoilWorker(settings.soil_dataset_csv_path)
    else:
        soil_client = HttpJsonClient(
            retry_policy=RetryPolicy(
                timeout_seconds=settings.request_timeout_seconds,
                retries=settings.request_retries,
                backoff_base_seconds=settings.request_backoff_base_seconds,
                backoff_max_seconds=settings.request_backoff_max_seconds,
                min_interval_seconds=max(
                    settings.soil_min_interval_seconds, 1.2 if demo_safe else 0.0
                ),
            ),
            cache=cache,
        )
        soil_worker = SoilWorker(client=soil_client, endpoint=settings.soil_endpoint)

    stage_start = time.perf_counter()
    merged_rows = _collect_features(
        points=generated_points,
        weather_worker=weather_worker,
        soil_worker=soil_worker,
        weather_workers=weather_workers,
    )
    collect_elapsed = round(time.perf_counter() - stage_start, 3)

    weather_failures = sum(1 for row in merged_rows if not row["weather_ok"])
    soil_failures = sum(1 for row in merged_rows if not row["soil_ok"])
    failed_points = sum(
        1 for row in merged_rows if not row["weather_ok"] and not row["soil_ok"]
    )
    if failed_points / len(merged_rows) > settings.failure_abort_ratio:
        raise RuntimeError(
            "Aborting run: too many points failed both weather and soil "
            f"({failed_points}/{len(merged_rows)}), above FAILURE_ABORT_RATIO "
            f"({settings.failure_abort_ratio}). "
            "SoilGrids often rate-limits or returns 5xx. Try: Safe demo mode in the UI "
            "(cached/throttled), increase REQUEST_RETRIES and REQUEST_TIMEOUT_SECONDS, "
            "raise SOIL_MIN_INTERVAL_SECONDS (e.g. 1.0–1.5s), reduce WEATHER_WORKERS, "
            "or lower FAILURE_ABORT_RATIO only if you accept scoring on sparse data."
        )

    stage_start = time.perf_counter()
    ranking_engine = "rules"
    if use_llm:
        # Rules order picks which points go to the LLM; LLM re-ranks that slice only.
        # Remaining shortlist positions use rules scores so top_n (and the map) still
        # show the requested number of sites when LLM_MAX_POINTS is small.
        rules_first = rank_candidates(
            merged_rows, profile=crop_profile, top_n=len(merged_rows)
        )
        llm_cap = min(max(1, settings.llm_max_points), len(rules_first))
        llm_slice = rules_first[:llm_cap]
        if settings.llm_provider == "gemini":
            if not settings.gemini_api_key:
                raise RuntimeError(
                    "GEMINI_API_KEY is required when LLM_PROVIDER=gemini (or use LLM_PROVIDER=ollama)."
                )
            llm_ranked = rank_with_gemini(
                candidate_rows=llm_slice,
                crop=crop_profile.name,
                api_key=settings.gemini_api_key,
                model=settings.gemini_model,
                timeout_seconds=settings.llm_timeout_seconds,
                max_points=llm_cap,
                extended_reasoning=extended_reasoning,
            )
            ranking_engine = "gemini"
        else:
            llm_ranked = rank_with_llama3(
                candidate_rows=llm_slice,
                crop=crop_profile.name,
                ollama_endpoint=settings.ollama_endpoint,
                ollama_model=settings.ollama_model,
                timeout_seconds=settings.llm_timeout_seconds,
                max_points=llm_cap,
                extended_reasoning=extended_reasoning,
            )
            ranking_engine = "llama3"
        for row in llm_ranked:
            row["score"] = row["llm_score"]
            row["score_band"] = row["llm_rating"]
        tail = rules_first[llm_cap:]
        for row in tail:
            row.setdefault("decision_source", "rules")
        all_ranked = llm_ranked + tail
    else:
        all_ranked = rank_candidates(merged_rows, profile=crop_profile, top_n=len(merged_rows))

    if risk_analysis:
        _attach_risk_metrics(all_ranked)

    nuts_meta = _apply_nuts2_yield_scores(
        all_ranked,
        crop,
        _nuts2_yield_lookup_label(generated_points),
        nuts2_store,
    )

    score_elapsed = round(time.perf_counter() - stage_start, 3)
    ranked_points = all_ranked[: max(1, top_n)]
    # One list may mix LLM scores with rules scores (hybrid mode); order by numeric score
    # so best_point, exports, and UI "top score" match the highest value in the shortlist.
    ranked_points.sort(
        key=lambda r: (-float(r.get("score") or 0.0), str(r.get("point_id", "")))
    )
    field_ha_for_rent = _field_size_hectares()
    land_path = resolve_land_prices_csv_path()
    land_store = LandPriceStore(land_path) if land_path else None
    _attach_land_rent_to_top_candidates(
        ranked_points,
        country_name=generated_points[0].country,
        land_store=land_store,
        field_ha=field_ha_for_rent,
    )

    om_validation_meta: dict[str, Any] = {}
    if os.getenv("OPEN_METEO_VALIDATION", "1").strip().lower() not in (
        "0",
        "false",
        "off",
        "no",
    ):
        merged_by_id = {str(r["point_id"]): r for r in merged_rows}
        archive_ep = resolve_open_meteo_archive_endpoint(settings.weather_endpoint)
        validation_client = HttpJsonClient(
            retry_policy=RetryPolicy(
                timeout_seconds=settings.request_timeout_seconds,
                retries=settings.request_retries,
                backoff_base_seconds=settings.request_backoff_base_seconds,
                backoff_max_seconds=settings.request_backoff_max_seconds,
                min_interval_seconds=max(
                    settings.weather_min_interval_seconds,
                    0.25 if demo_safe else 0.12,
                ),
            ),
            cache=cache,
        )
        om_validation_meta = attach_open_meteo_history_to_top_candidates(
            ranked_points,
            merged_by_id,
            client=validation_client,
            archive_endpoint=archive_ep,
            start_date=start_date,
            end_date=end_date,
            max_workers=3 if demo_safe else 6,
        )

    best_point = ranked_points[0]
    best_point["rules_reasoning"] = build_site_reasoning(best_point, crop_profile)

    summary = {
        "total_points": len(generated_points),
        "successful_weather_fetches": len(generated_points) - weather_failures,
        "successful_soil_fetches": len(generated_points) - soil_failures,
        "points_scored_fully": sum(1 for row in merged_rows if row.get("weather_ok") and row.get("soil_ok")),
        "points_scored_partially": sum(
            1 for row in merged_rows if row.get("weather_ok") or row.get("soil_ok")
        ),
        "elapsed_seconds": {
            "collect_features": collect_elapsed,
            "score_and_rank": score_elapsed,
        },
        "ranking_engine": ranking_engine,
        "risk_analysis_enabled": risk_analysis,
        "extended_reasoning_enabled": extended_reasoning,
        "region": generated_points[0].region,
        "field_hectares_for_land_estimate": field_ha_for_rent,
        "land_monthly_rent_pct_of_buyout": _land_monthly_rent_fraction_of_buyout() * 100.0,
        "land_prices_csv_loaded": land_path is not None,
        **nuts_meta,
        **om_validation_meta,
    }

    recommendation = build_recommendation_payload(
        run_id=run_id,
        country=generated_points[0].country,
        crop=crop_profile.name,
        best_point=best_point,
        ranked_points=ranked_points,
        summary=summary,
        ranking_engine=ranking_engine,
        llm_model=(
            (
                settings.gemini_model
                if settings.llm_provider == "gemini"
                else settings.ollama_model
            )
            if use_llm
            else None
        ),
    )

    write_csv(run_dir / "candidates.csv", merged_rows)
    write_csv(run_dir / "top_candidates.csv", ranked_points)
    write_json(run_dir / "recommendation.json", recommendation)

    return {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "country": generated_points[0].country,
        "crop": crop_profile.name,
        "region": generated_points[0].region,
        "best_point": best_point,
        "top_candidates": ranked_points,
        "summary": summary,
        "recommendation": recommendation,
        "ranking_engine": ranking_engine,
    }


def _attach_risk_metrics(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        frost = float(row.get("frost_risk", 0.0) or 0.0)
        stress = float(row.get("weather_stress_ratio", 0.0) or 0.0)
        wind = float(row.get("wind_speed_10m_kmh", 0.0) or 0.0)
        moisture = row.get("soil_moisture_1_3cm")
        moisture_val = float(moisture) if moisture is not None else None

        risk_index = (
            min(1.0, frost * 1.2) * 0.35
            + min(1.0, stress * 3.0) * 0.35
            + min(1.0, wind / 35.0) * 0.2
            + (0.1 if moisture_val is None else min(1.0, abs(0.28 - moisture_val) / 0.28) * 0.1)
        )
        risk_index = max(0.0, min(1.0, risk_index))
        if risk_index < 0.33:
            risk_level = "low"
        elif risk_index < 0.66:
            risk_level = "medium"
        else:
            risk_level = "high"

        reasons: list[str] = []
        if frost > 0.1:
            reasons.append("elevated frost exposure")
        if stress > 0.05:
            reasons.append("frequent severe weather codes")
        if wind > 20.0:
            reasons.append("high average wind speed")
        if moisture_val is not None and (moisture_val < 0.14 or moisture_val > 0.42):
            reasons.append("surface soil moisture outside ideal range")
        if not reasons:
            reasons.append("balanced climate and stress indicators")

        row["risk_index"] = round(risk_index, 3)
        row["risk_level"] = risk_level
        row["risk_summary"] = "; ".join(reasons)


def _collect_features(
    points: list[Any],
    weather_worker: WeatherWorker,
    soil_worker: SoilWorker,
    weather_workers: int,
) -> list[dict[str, Any]]:
    weather_by_point: dict[str, tuple[dict[str, float], dict[str, Any]]] = {}
    with ThreadPoolExecutor(max_workers=max(1, weather_workers)) as executor:
        futures = {executor.submit(weather_worker.collect, point): point for point in points}
        for future in as_completed(futures):
            point = futures[future]
            weather_by_point[point.point_id] = future.result()

    merged_rows: list[dict[str, Any]] = []
    for point in points:
        weather_features, weather_diag = weather_by_point[point.point_id]
        soil_features, soil_diag = soil_worker.collect(point)

        row: dict[str, Any] = {
            "point_id": point.point_id,
            "country": point.country,
            "lat": point.lat,
            "lon": point.lon,
            "weather_ok": weather_diag.get("ok", False),
            "soil_ok": soil_diag.get("ok", False),
            "weather_error": weather_diag.get("error"),
            "soil_error": soil_diag.get("error"),
        }
        row.update(weather_features)
        row.update(soil_features)
        row["nuts_region"] = point.region
        merged_rows.append(row)
    return merged_rows


if __name__ == "__main__":
    raise SystemExit(main())

