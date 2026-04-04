from __future__ import annotations

import argparse
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

from src.collectors.http_utils import HttpJsonClient, RetryPolicy
from src.collectors.soil_worker import SoilWorker
from src.collectors.weather_worker import WeatherWorker
from src.config import Settings
from src.geo.grid import generate_candidate_points
from src.io.cache import FileCache
from src.models.crop_profiles import get_crop_profile, list_crop_names
from src.output.recommendation import (
    build_recommendation_payload,
    ensure_run_dir,
    write_csv,
    write_json,
)
from src.scoring.llm_ranking import rank_with_llama3
from src.scoring.suitability import rank_candidates


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
    )
    best_point = result["best_point"]

    print(f"Run completed: {result['run_id']}")
    print(f"Country: {result['country']}, Crop: {result['crop']}")
    print(
        "Best point: "
        f"{best_point['point_id']} ({best_point['lat']}, {best_point['lon']}) "
        f"score={best_point['score']} confidence={best_point['confidence']}"
    )
    print(f"Artifacts: {result['run_dir']}")
    return 0


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
) -> dict[str, Any]:
    settings = Settings.from_env()
    run_id = f"run_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:6]}"
    run_dir = ensure_run_dir(settings.runs_dir, run_id)
    cache = FileCache(settings.cache_dir)

    crop_profile = get_crop_profile(crop)
    generated_points = generate_candidate_points(country, point_count=points, seed=seed)

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
    weather_worker = WeatherWorker(
        client=weather_client,
        endpoint=settings.weather_endpoint,
        start_date=start_date,
        end_date=end_date,
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
            "Aborting run: too many points failed both sources "
            f"({failed_points}/{len(merged_rows)})."
        )

    stage_start = time.perf_counter()
    ranking_engine = "rules"
    if use_llm:
        all_ranked = rank_with_llama3(
            candidate_rows=merged_rows,
            crop=crop_profile.name,
            ollama_endpoint=settings.ollama_endpoint,
            ollama_model=settings.ollama_model,
            timeout_seconds=settings.llm_timeout_seconds,
            max_points=min(settings.llm_max_points, len(merged_rows)),
        )
        for row in all_ranked:
            row["score"] = row["llm_score"]
            row["score_band"] = row["llm_rating"]
        ranking_engine = "llama3"
    else:
        all_ranked = rank_candidates(merged_rows, profile=crop_profile, top_n=len(merged_rows))

    score_elapsed = round(time.perf_counter() - stage_start, 3)
    ranked_points = all_ranked[: max(1, top_n)]
    best_point = ranked_points[0]

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
    }

    recommendation = build_recommendation_payload(
        run_id=run_id,
        country=generated_points[0].country,
        crop=crop_profile.name,
        best_point=best_point,
        ranked_points=ranked_points,
        summary=summary,
        ranking_engine=ranking_engine,
        llm_model=(settings.ollama_model if use_llm else None),
    )

    write_csv(run_dir / "candidates.csv", merged_rows)
    write_csv(run_dir / "top_candidates.csv", ranked_points)
    write_json(run_dir / "recommendation.json", recommendation)

    return {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "country": generated_points[0].country,
        "crop": crop_profile.name,
        "best_point": best_point,
        "top_candidates": ranked_points,
        "summary": summary,
        "recommendation": recommendation,
        "ranking_engine": ranking_engine,
    }


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
        merged_rows.append(row)
    return merged_rows


if __name__ == "__main__":
    raise SystemExit(main())

