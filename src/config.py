from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path


def _load_dotenv_if_present(override: bool = False) -> None:
    dotenv_path = Path(".env")
    if not dotenv_path.exists():
        return
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            if override or key not in os.environ:
                os.environ[key] = value

_load_dotenv_if_present(override=False)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _default_date_range() -> tuple[str, str]:
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=365 * 3)
    return start.isoformat(), end.isoformat()


@dataclass(frozen=True)
class Settings:
    weather_endpoint: str
    soil_endpoint: str
    request_timeout_seconds: float
    request_retries: int
    request_backoff_base_seconds: float
    request_backoff_max_seconds: float
    weather_min_interval_seconds: float
    soil_min_interval_seconds: float
    weather_workers: int
    failure_abort_ratio: float
    cache_dir: Path
    runs_dir: Path
    default_seed: int
    default_points: int
    default_top_n: int
    default_start_date: str
    default_end_date: str
    ollama_endpoint: str
    ollama_model: str
    llm_timeout_seconds: float
    llm_max_points: int

    @classmethod
    def from_env(cls) -> "Settings":
        # Reload .env on each read so web app picks up edits without restart.
        _load_dotenv_if_present(override=True)
        default_start, default_end = _default_date_range()
        return cls(
            weather_endpoint=os.getenv(
                "WEATHER_ENDPOINT", "https://archive-api.open-meteo.com/v1/archive"
            ),
            soil_endpoint=os.getenv(
                "SOIL_ENDPOINT",
                "https://rest.isric.org/soilgrids/v2.0/properties/query",
            ),
            request_timeout_seconds=_env_float("REQUEST_TIMEOUT_SECONDS", 15.0),
            request_retries=_env_int("REQUEST_RETRIES", 3),
            request_backoff_base_seconds=_env_float(
                "REQUEST_BACKOFF_BASE_SECONDS", 0.8
            ),
            request_backoff_max_seconds=_env_float("REQUEST_BACKOFF_MAX_SECONDS", 8.0),
            weather_min_interval_seconds=_env_float(
                "WEATHER_MIN_INTERVAL_SECONDS", 0.08
            ),
            soil_min_interval_seconds=_env_float("SOIL_MIN_INTERVAL_SECONDS", 0.7),
            weather_workers=_env_int("WEATHER_WORKERS", 8),
            failure_abort_ratio=_env_float("FAILURE_ABORT_RATIO", 0.45),
            cache_dir=Path(os.getenv("CACHE_DIR", ".cache")),
            runs_dir=Path(os.getenv("RUNS_DIR", "runs")),
            default_seed=_env_int("DEFAULT_SEED", 42),
            default_points=_env_int("DEFAULT_POINTS", 100),
            default_top_n=_env_int("DEFAULT_TOP_N", 10),
            default_start_date=os.getenv("DEFAULT_START_DATE", default_start),
            default_end_date=os.getenv("DEFAULT_END_DATE", default_end),
            ollama_endpoint=os.getenv("OLLAMA_ENDPOINT", "http://127.0.0.1:11434"),
            ollama_model=os.getenv("OLLAMA_MODEL", "llama3"),
            llm_timeout_seconds=_env_float("LLM_TIMEOUT_SECONDS", 20.0),
            llm_max_points=_env_int("LLM_MAX_POINTS", 25),
        )

