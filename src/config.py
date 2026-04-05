from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

# Repo root (parent of `src/`) so .env is found even if the process cwd is elsewhere.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _dotenv_paths() -> list[Path]:
    """Order: explicit path, project root, then current working directory."""
    paths: list[Path] = []
    env_path = os.getenv("DOTENV_PATH", "").strip()
    if env_path:
        paths.append(Path(env_path).expanduser())
    paths.append(_PROJECT_ROOT / ".env")
    paths.append(Path.cwd() / ".env")
    return paths


def _parse_dotenv_value(raw: str) -> str:
    value = raw.strip().strip('"').strip("'")
    if "#" in value and not (raw.strip().startswith('"') or raw.strip().startswith("'")):
        value = value.split("#", 1)[0].rstrip()
    return value.strip().strip('"').strip("'")


def _sanitize_gemini_api_key(raw: str) -> str:
    s = raw.strip().replace("\ufeff", "").replace("\r", "").replace("\n", "")
    return s.strip()


def _load_dotenv_if_present(override: bool = False) -> None:
    for dotenv_path in _dotenv_paths():
        if not dotenv_path.is_file():
            continue
        try:
            text = dotenv_path.read_text(encoding="utf-8")
        except OSError:
            continue
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = _parse_dotenv_value(value)
            if key:
                if override or key not in os.environ:
                    os.environ[key] = value
        break

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


def resolve_bundled_data_csv(filename: str) -> Path | None:
    """Find a repo CSV under ``datasets/`` or the project root (legacy layout)."""
    search_roots = (
        _PROJECT_ROOT / "datasets",
        _PROJECT_ROOT,
        Path.cwd() / "datasets",
        Path.cwd(),
    )
    for root in search_roots:
        candidate = (root / filename).resolve()
        if candidate.is_file():
            return candidate
    return None


def _resolve_soil_dataset_csv_path() -> Path | None:
    """Use europe_soil_climate_dataset.csv when present unless SOIL_DATASET_CSV disables it."""
    raw = os.getenv("SOIL_DATASET_CSV")
    if raw is not None:
        stripped = raw.strip()
        if not stripped or stripped.lower() in (
            "none",
            "off",
            "0",
            "false",
            "soilgrids",
        ):
            return None
        candidate = Path(stripped)
        return candidate.resolve() if candidate.is_file() else None
    return resolve_bundled_data_csv("europe_soil_climate_dataset.csv")


def resolve_nuts2_yields_csv_path() -> Path | None:
    """Eurostat-style regional yields CSV (optional)."""
    raw = os.getenv("NUTS2_YIELDS_CSV")
    if raw is not None:
        stripped = raw.strip()
        if not stripped or stripped.lower() in ("none", "off", "0", "false"):
            return None
        candidate = Path(stripped)
        return candidate.resolve() if candidate.is_file() else None
    return resolve_bundled_data_csv("nuts2_crop_yields_all_regions.csv")


def resolve_land_prices_csv_path() -> Path | None:
    """Regional land purchase value EUR/ha (optional; used for buy-out + modelled rent)."""
    raw = os.getenv("LAND_PRICES_CSV")
    if raw is not None:
        stripped = raw.strip()
        if not stripped or stripped.lower() in ("none", "off", "0", "false"):
            return None
        candidate = Path(stripped)
        return candidate.resolve() if candidate.is_file() else None
    return resolve_bundled_data_csv("land_prices_clean.csv")


@dataclass(frozen=True)
class Settings:
    weather_endpoint: str
    weather_backend: str
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
    llm_timeout_seconds: float
    llm_max_points: int
    google_maps_api_key: str | None
    gemini_api_key: str | None
    gemini_model: str
    soil_dataset_csv_path: Path | None

    @classmethod
    def from_env(cls) -> "Settings":
        # Reload .env on each read so web app picks up edits without restart.
        _load_dotenv_if_present(override=True)
        default_start, default_end = _default_date_range()
        _gemini_raw = _sanitize_gemini_api_key(os.getenv("GEMINI_API_KEY", ""))
        if not _gemini_raw:
            _kf = os.getenv("GEMINI_API_KEY_FILE", "").strip()
            if _kf:
                _kp = Path(_kf).expanduser()
                if _kp.is_file():
                    try:
                        _gemini_raw = _sanitize_gemini_api_key(
                            _kp.read_text(encoding="utf-8")
                        )
                    except OSError:
                        pass
        gemini_api_key = _gemini_raw if _gemini_raw else None
        _maps_raw = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()
        google_maps_api_key = _maps_raw if _maps_raw else None
        _force_open_meteo = (
            os.getenv("WEATHER_PROVIDER", "").strip().lower() == "open_meteo"
        )
        weather_backend = (
            "open_meteo"
            if _force_open_meteo or not google_maps_api_key
            else "google_forecast"
        )
        return cls(
            weather_endpoint=os.getenv(
                "WEATHER_ENDPOINT", "https://archive-api.open-meteo.com/v1/archive"
            ),
            weather_backend=weather_backend,
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
            llm_timeout_seconds=_env_float("LLM_TIMEOUT_SECONDS", 20.0),
            llm_max_points=_env_int("LLM_MAX_POINTS", 25),
            google_maps_api_key=google_maps_api_key,
            gemini_api_key=gemini_api_key,
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
            or "gemini-2.5-flash",
            soil_dataset_csv_path=_resolve_soil_dataset_csv_path(),
        )

