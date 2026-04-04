from __future__ import annotations

import json
import urllib.request
from typing import Any
from urllib.error import HTTPError, URLError


def rank_with_llama3(
    candidate_rows: list[dict[str, Any]],
    crop: str,
    ollama_endpoint: str,
    ollama_model: str,
    timeout_seconds: float,
    max_points: int | None = None,
) -> list[dict[str, Any]]:
    if not candidate_rows:
        return []

    _assert_ollama_ready(
        endpoint=ollama_endpoint,
        model=ollama_model,
        timeout_seconds=timeout_seconds,
    )

    eval_count = len(candidate_rows) if max_points is None else min(
        max(1, max_points), len(candidate_rows)
    )
    to_evaluate = candidate_rows[:eval_count]

    llm_rows = [
        _evaluate_candidate_with_llm(
            row=row,
            crop=crop,
            endpoint=ollama_endpoint,
            model=ollama_model,
            timeout_seconds=timeout_seconds,
        )
        for row in to_evaluate
    ]

    llm_rows.sort(
        key=lambda item: (
            -float(item.get("llm_score", 0.0)),
            -float(item.get("confidence", 0.0)),
            item["point_id"],
        )
    )
    _attach_selection_reasoning(
        ranked_rows=llm_rows,
        crop=crop,
        endpoint=ollama_endpoint,
        model=ollama_model,
        timeout_seconds=timeout_seconds,
    )
    return llm_rows


def _evaluate_candidate_with_llm(
    row: dict[str, Any],
    crop: str,
    endpoint: str,
    model: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    enriched = dict(row)
    llm_eval = _call_ollama_for_candidate(
        row=row,
        crop=crop,
        endpoint=endpoint,
        model=model,
        timeout_seconds=timeout_seconds,
    )
    llm_score = float(llm_eval.get("llm_score", 0.0))
    llm_score = max(0.0, min(100.0, llm_score))
    llm_rating = str(llm_eval.get("rating", _score_band(llm_score))).strip().lower()
    if llm_rating not in {"poor", "fair", "good", "excellent"}:
        llm_rating = _score_band(llm_score)
    reasoning = str(llm_eval.get("reasoning", "LLM evaluated this location.")).strip()

    enriched["llm_score"] = round(llm_score, 3)
    enriched["llm_rating"] = llm_rating
    enriched["llm_reasoning"] = reasoning
    enriched["decision_source"] = "llm"
    enriched["confidence"] = float(enriched.get("confidence", _data_confidence(row)))
    return enriched


def _call_ollama_for_candidate(
    row: dict[str, Any],
    crop: str,
    endpoint: str,
    model: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    endpoint = endpoint.rstrip("/")
    url = f"{endpoint}/api/generate"
    features = {
        "lat": row.get("lat"),
        "lon": row.get("lon"),
        "mean_temp_c": row.get("mean_temp_c"),
        "rainfall_mm": row.get("rainfall_mm"),
        "frost_risk": row.get("frost_risk"),
        "humidity_pct": row.get("humidity_pct"),
        "et0_mm": row.get("et0_mm"),
        "wind_speed_10m_kmh": row.get("wind_speed_10m_kmh"),
        "soil_moisture_1_3cm": row.get("soil_moisture_1_3cm"),
        "weather_stress_ratio": row.get("weather_stress_ratio"),
        "soil_ph": row.get("soil_ph"),
        "soil_organic_carbon_gkg": row.get("soil_organic_carbon_gkg"),
        "sand_pct": row.get("sand_pct"),
        "clay_pct": row.get("clay_pct"),
    }
    prompt = (
        "You are an agronomy evaluator. Rate crop suitability for a single location.\n"
        "Return ONLY valid JSON, no markdown.\n"
        'Schema: {"llm_score": number 0-100, "rating": "poor|fair|good|excellent", '
        '"reasoning": "max 50 words"}\n'
        f"Crop: {crop}\n"
        f"Location features: {json.dumps(features, ensure_ascii=True)}\n"
        "Base score only on agronomic weather-soil fit for this crop. "
        "Mention strongest positive and strongest limiting factor."
    )
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0},
    }
    request = urllib.request.Request(
        url=url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        raw = json.loads(response.read().decode("utf-8"))
    model_response = str(raw.get("response", "")).strip()
    parsed = _parse_json_object(model_response)
    return parsed


def _parse_json_object(text: str) -> dict[str, Any]:
    try:
        candidate = json.loads(text)
        if isinstance(candidate, dict):
            return candidate
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        candidate = json.loads(text[start : end + 1])
        if isinstance(candidate, dict):
            return candidate
    raise ValueError("Could not parse JSON object from LLM output.")


def _assert_ollama_ready(
    endpoint: str,
    model: str,
    timeout_seconds: float,
) -> None:
    endpoint = endpoint.rstrip("/")
    url = f"{endpoint}/api/tags"
    request = urllib.request.Request(url=url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = json.loads(response.read().decode("utf-8"))
        models = raw.get("models", [])
        names = {
            str(item.get("name", "")).strip().lower()
            for item in models
            if isinstance(item, dict)
        }
        model_key = model.strip().lower()
        if model_key in names or any(name.startswith(f"{model_key}:") for name in names):
            return
        raise RuntimeError(f"Ollama model '{model}' not found. Run: ollama pull {model}")
    except Exception as exc:
        raise RuntimeError(_humanize_llm_error(exc, model=model, endpoint=endpoint)) from exc


def _attach_selection_reasoning(
    ranked_rows: list[dict[str, Any]],
    crop: str,
    endpoint: str,
    model: str,
    timeout_seconds: float,
) -> None:
    if len(ranked_rows) < 2:
        return
    best = ranked_rows[0]
    rivals = ranked_rows[1:4]
    comparison_payload = {
        "crop": crop,
        "best_candidate": {
            "point_id": best.get("point_id"),
            "llm_score": best.get("llm_score"),
            "features": _compact_features(best),
        },
        "runner_up_candidates": [
            {
                "point_id": row.get("point_id"),
                "llm_score": row.get("llm_score"),
                "features": _compact_features(row),
            }
            for row in rivals
        ],
    }
    prompt = (
        "You are an agronomy evaluator.\n"
        "Explain why the best candidate is better than the next candidates.\n"
        "Return ONLY valid JSON: {\"selection_reasoning\":\"max 70 words\"}\n"
        f"Data: {json.dumps(comparison_payload, ensure_ascii=True)}"
    )
    response = _call_ollama(endpoint, model, timeout_seconds, prompt)
    parsed = _parse_json_object(response)
    reason = str(parsed.get("selection_reasoning", "")).strip()
    if reason:
        best["llm_reasoning"] = reason


def _humanize_llm_error(exc: Exception, model: str, endpoint: str) -> str:
    prefix = "LLM ranking failed: "
    if isinstance(exc, HTTPError):
        detail = _read_http_error_detail(exc)
        if exc.code == 404:
            return (
                f"{prefix}Ollama endpoint/model not found at {endpoint}. "
                f"Model: {model}. {detail}".strip()
            )
        if exc.code >= 500:
            return (
                f"{prefix}Ollama server error ({exc.code}) while using model '{model}'. "
                f"Try: ollama serve, then ollama pull {model}. {detail}".strip()
            )
        return f"{prefix}Ollama HTTP error ({exc.code}). {detail}".strip()
    if isinstance(exc, URLError):
        return (
            f"{prefix}Cannot reach Ollama at {endpoint}. "
            "Start it with: ollama serve"
        )
    text = str(exc).strip()
    if not text:
        text = "Unknown LLM error."
    return f"{prefix}{text}"


def _read_http_error_detail(exc: HTTPError) -> str:
    try:
        payload = exc.read().decode("utf-8").strip()
    except Exception:
        return ""
    if not payload:
        return ""
    if len(payload) > 180:
        payload = payload[:180] + "..."
    return f"Details: {payload}"


def _score_band(score: float) -> str:
    if score >= 80.0:
        return "excellent"
    if score >= 60.0:
        return "good"
    if score >= 40.0:
        return "fair"
    return "poor"


def _call_ollama(
    endpoint: str,
    model: str,
    timeout_seconds: float,
    prompt: str,
) -> str:
    endpoint = endpoint.rstrip("/")
    url = f"{endpoint}/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0},
    }
    request = urllib.request.Request(
        url=url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        raw = json.loads(response.read().decode("utf-8"))
    return str(raw.get("response", "")).strip()


def _compact_features(row: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "mean_temp_c",
        "rainfall_mm",
        "frost_risk",
        "humidity_pct",
        "et0_mm",
        "wind_speed_10m_kmh",
        "soil_moisture_1_3cm",
        "weather_stress_ratio",
        "soil_ph",
        "soil_organic_carbon_gkg",
        "sand_pct",
        "clay_pct",
    ]
    return {key: row.get(key) for key in keys if row.get(key) is not None}


def _data_confidence(row: dict[str, Any]) -> float:
    keys = [
        "mean_temp_c",
        "rainfall_mm",
        "frost_risk",
        "humidity_pct",
        "et0_mm",
        "wind_speed_10m_kmh",
        "soil_moisture_1_3cm",
        "weather_stress_ratio",
        "soil_ph",
        "soil_organic_carbon_gkg",
        "sand_pct",
        "clay_pct",
    ]
    available = sum(1 for key in keys if row.get(key) is not None)
    return round(available / len(keys), 3)

