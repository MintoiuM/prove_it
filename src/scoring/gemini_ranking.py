from __future__ import annotations

import json
import socket
import urllib.request
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote

from src.scoring.llm_ranking import (
    _compact_features,
    _data_confidence,
    _parse_json_object,
    _row_features_for_prompt,
    _score_band,
)


def rank_with_gemini(
    candidate_rows: list[dict[str, Any]],
    crop: str,
    api_key: str,
    model: str,
    timeout_seconds: float,
    max_points: int | None = None,
    extended_reasoning: bool = False,
) -> list[dict[str, Any]]:
    if not candidate_rows:
        return []

    eval_count = len(candidate_rows) if max_points is None else min(
        max(1, max_points), len(candidate_rows)
    )
    to_evaluate = candidate_rows[:eval_count]

    llm_rows = [
        _evaluate_candidate_with_gemini(
            row=row,
            crop=crop,
            api_key=api_key,
            model=model,
            timeout_seconds=timeout_seconds,
            extended_reasoning=extended_reasoning,
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
    _attach_selection_reasoning_gemini(
        ranked_rows=llm_rows,
        crop=crop,
        api_key=api_key,
        model=model,
        timeout_seconds=timeout_seconds,
        extended_reasoning=extended_reasoning,
    )
    return llm_rows


def _evaluate_candidate_with_gemini(
    row: dict[str, Any],
    crop: str,
    api_key: str,
    model: str,
    timeout_seconds: float,
    extended_reasoning: bool,
) -> dict[str, Any]:
    enriched = dict(row)
    try:
        llm_eval = _call_gemini_json(
            api_key=api_key,
            model=model,
            timeout_seconds=timeout_seconds,
            prompt=_candidate_eval_prompt(row, crop, extended_reasoning),
        )
    except Exception as exc:
        raise RuntimeError(_humanize_gemini_error(exc, model=model)) from exc
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


def _candidate_eval_prompt(
    row: dict[str, Any], crop: str, extended_reasoning: bool
) -> str:
    features = _row_features_for_prompt(row)
    return (
        "You are an agronomy evaluator. Rate crop suitability for a single location.\n"
        "Return ONLY valid JSON, no markdown.\n"
        'Schema: {"llm_score": number 0-100, "rating": "poor|fair|good|excellent", '
        f'"reasoning": "max {120 if extended_reasoning else 50} words"}}\n'
        f"Crop: {crop}\n"
        f"Location features: {json.dumps(features, ensure_ascii=True)}\n"
        "Base score only on agronomic weather-soil fit for this crop. "
        "Mention strongest positive and strongest limiting factor. "
        + (
            "Also mention expected operational risks and mitigation hints."
            if extended_reasoning
            else ""
        )
    )


def _attach_selection_reasoning_gemini(
    ranked_rows: list[dict[str, Any]],
    crop: str,
    api_key: str,
    model: str,
    timeout_seconds: float,
    extended_reasoning: bool,
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
        f'Return ONLY valid JSON: {{"selection_reasoning":"max {140 if extended_reasoning else 70} words"}}\n'
        f"Data: {json.dumps(comparison_payload, ensure_ascii=True)}"
    )
    try:
        response = _call_gemini_raw(
            api_key=api_key,
            model=model,
            timeout_seconds=timeout_seconds,
            prompt=prompt,
        )
        parsed = _parse_json_object(response)
        reason = str(parsed.get("selection_reasoning", "")).strip()
        if reason:
            best["llm_reasoning"] = reason
    except Exception:
        return


def _call_gemini_json(
    api_key: str,
    model: str,
    timeout_seconds: float,
    prompt: str,
) -> dict[str, Any]:
    text = _call_gemini_raw(api_key, model, timeout_seconds, prompt)
    return _parse_json_object(text)


def _call_gemini_raw(
    api_key: str,
    model: str,
    timeout_seconds: float,
    prompt: str,
) -> str:
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={quote(api_key, safe='')}"
    )
    body: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0},
    }
    request = urllib.request.Request(
        url=url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"Gemini HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Gemini request failed: {exc}") from exc

    candidates = data.get("candidates") or []
    if not candidates:
        block = data.get("promptFeedback") or data
        raise RuntimeError(f"Gemini returned no candidates: {block}")

    parts = candidates[0].get("content", {}).get("parts") or []
    return "".join(str(p.get("text", "")) for p in parts).strip()


def _humanize_gemini_error(exc: Exception, model: str) -> str:
    prefix = "Gemini LLM failed: "
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return (
            f"{prefix}request timed out for model '{model}'. "
            "Increase LLM_TIMEOUT_SECONDS or reduce LLM_MAX_POINTS."
        )
    text = str(exc).strip() or "Unknown error."
    low = text.lower()
    if "api key not valid" in low or ("400" in text and "api key" in low):
        return (
            f"{prefix}{text}\n\n"
            "The server rejected the API key. Fix: use a key from Google AI Studio (Generative Language API), "
            "put it in GEMINI_API_KEY in the project’s .env at the repo root (or set DOTENV_PATH), "
            "avoid pasting a Maps-only key, remove spaces/newlines, and restart the web app. "
            "Optional: GEMINI_API_KEY_FILE=/path/to/key.txt"
        )
    if "429" in text or "resource exhausted" in low or "quota" in low:
        return (
            f"{prefix}{text}\n\n"
            "Rate limited: wait and retry, reduce LLM_MAX_POINTS, or check quota on the API key."
        )
    if "403" in text or "permission" in low:
        return (
            f"{prefix}{text}\n\n"
            "Enable the Generative Language API for the Google Cloud project that owns this API key."
        )
    if "404" in text and "model" in low:
        return (
            f"{prefix}{text}\n\n"
            f"Try GEMINI_MODEL=gemini-2.0-flash or gemini-1.5-flash — '{model}' may be unavailable for this key."
        )
    return f"{prefix}{text}"
