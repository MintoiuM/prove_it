# Europe Crop Suitability MVP

Runnable tool for ranking candidate cultivation sites inside supported European countries: sample points, pull weather and soil signals, score agronomic fit, and export a shortlist with diagnostics.

## What it does

- Samples a configurable number of deterministic candidate points per country (and optional NUTS-style sub-region).
- **Land-only sampling:** after country (and optional NUTS) polygon checks, points must lie on a **Natural Earth land** layer (default **`ne_50m_land`** — `ne_110m_land` bridges narrow seas and is not used by default). Country outlines prefer **`ne_50m_admin_0_countries`**, falling back to 110m. Override land detail with **`NATURAL_EARTH_LAND_RESOLUTION=10`** for `ne_10m_land` (~10 MB) if you still see coastal artefacts. Files cache under `.cache/boundaries/`; if download fails, a warning is issued and sampling falls back to country polygons only.
- **Weather:** Open-Meteo archive by default; optional **Google Maps** forecast window when `GOOGLE_MAPS_API_KEY` is set (see `.env.example`).
- **Soil:** SoilGrids API and/or bundled **`datasets/europe_soil_climate_dataset.csv`** (nearest-neighbour rows) when configured.
- Scores each site with rule-based suitability `[0, 100]`, confidence, and optional **risk** metrics (`--risk-analysis`).
- Optional **NUTS2 regional yields** and **land buy-out / rent** estimates from bundled CSVs under `datasets/` when those files are present.
- Optional **Google Gemini** reranking of the top `LLM_MAX_POINTS` candidates after rules ordering (`--use-llm`, needs `GEMINI_API_KEY`).
- Writes **`runs/<run_id>/`** CSV + JSON artifacts; optional Open-Meteo archive cross-check for top sites (see `OPEN_METEO_VALIDATION` in `.env.example`).

## Requirements

- **Python 3.10+** (3.11+ recommended).
- Run commands from the **repository root** (or set `DOTENV_PATH` so `.env` is found—loading also checks the repo root next to `src/`).

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
cp .env.example .env
python3 -m src.main --country France --crop wheat --demo-safe
```

The pipeline uses the Python standard library only (no `pip install` required for core runs).

## Tests

Install the dev dependency (once per venv), then run **pytest** from the repo root:

```bash
pip install -r requirements-dev.txt
python3 -m pytest
```

Verbose output: `python3 -m pytest -v`. One file: `python3 -m pytest tests/test_suitability.py`.

Tests cover rule scoring, LLM JSON helpers (no API calls), bundled CSV path resolution, and NUTS2 helpers. They require **`datasets/crop_needs_clean.csv`** (and for the NUTS2 smoke test, **`datasets/nuts2_crop_yields_all_regions.csv`**) to be present as in this repo.

Gemini reranking (after setting `GEMINI_API_KEY` in `.env`):

```bash
python3 -m src.main --country France --crop wheat --demo-safe --use-llm
```

## Configuration

Environment variables are documented in **`.env.example`**. Notable groups:

| Area | Examples |
|------|----------|
| Weather / soil APIs | `WEATHER_ENDPOINT`, `SOIL_ENDPOINT`, `WEATHER_PROVIDER`, `SOIL_DATASET_CSV` |
| Bundled CSV overrides | `CROP_NEEDS_CSV`, `NUTS2_YIELDS_CSV`, `LAND_PRICES_CSV` |
| HTTP pacing | `REQUEST_*`, `WEATHER_WORKERS`, `SOIL_MIN_INTERVAL_SECONDS`, `FAILURE_ABORT_RATIO` |
| LLM | `GEMINI_API_KEY`, `GEMINI_API_KEY_FILE`, `GEMINI_MODEL`, `LLM_MAX_POINTS`, `LLM_TIMEOUT_SECONDS` |
| Maps UI | `GOOGLE_MAPS_API_KEY` (Leaflet map in the web app) |

Default bundled data files are resolved from **`datasets/`** first, then the repo root (legacy layout).

## CLI

```text
python3 -m src.main --country <name> --crop <slug> [options]
```

| Option | Role |
|--------|------|
| `--points`, `--seed`, `--top-n` | Sample size, RNG seed, shortlist length |
| `--start-date`, `--end-date` | Weather window (defaults: rolling ~3 years) |
| `--demo-safe` | Slower, gentler throttling for live demos |
| `--region` | Optional NUTS label for regional yield blending (see NUTS2 CSV) |
| `--use-llm` | Gemini rescores top slice (requires API key) |
| `--risk-analysis` | Adds computed risk fields per candidate |
| `--extended-reasoning` | Longer LLM explanations when `--use-llm` is on |

Crop choices are defined by **`datasets/crop_needs_clean.csv`** when present, plus built-in profiles (e.g. corn, sunflower). List valid `--crop` values with:

```bash
python3 -m src.main --help
```

## Web application UI

```bash
python3 -m src.web --host 127.0.0.1 --port 8080
```

Then open `http://127.0.0.1:8080`. The same server is available as **`python3 -m src.webapp`** (compatibility shim).

Enable **AI recommendations** in the UI for Gemini-based scoring when a key is configured.

## Project layout

| Path | Purpose |
|------|---------|
| `src/main.py` | CLI entry; orchestrates the pipeline |
| `src/web/` | HTTP server and `templates/site_provit.html` |
| `src/collectors/` | Weather, soil, HTTP client, Open-Meteo validation helpers |
| `src/geo/` | Country envelopes, point sampling, NUTS helpers |
| `src/models/` | Crop profiles and CSV-backed crop needs |
| `src/scoring/` | Rules engine, Gemini integration, shared LLM JSON helpers |
| `src/data/` | Land price and NUTS2 yield stores |
| `src/output/` | Run directory layout, CSV/JSON export, reasoning text |
| `datasets/` | Bundled CSV inputs (crop needs, optional soil/yields/land) |
| `runs/` | Per-run outputs (created at runtime) |
| `.cache/` | HTTP response cache (created at runtime) |

More architecture and data-model detail: **`TECHNICAL_DOCUMENTATION.md`**.

## Gemini (optional)

1. Create a key in [Google AI Studio](https://aistudio.google.com/).
2. Enable the **Generative Language API** for the Google Cloud project tied to that key.
3. Set `GEMINI_API_KEY` or `GEMINI_API_KEY_FILE` in `.env`; tune `GEMINI_MODEL`, `LLM_TIMEOUT_SECONDS`, and `LLM_MAX_POINTS` as needed.

## Supported countries (MVP catalog)

France, Spain, Italy, Germany, Romania, Poland, Netherlands, Belgium, Portugal, Hungary.

## Output artifacts

Each run writes under **`runs/<run_id>/`**:

- **`candidates.csv`** — full feature table for sampled points  
- **`top_candidates.csv`** — ranked shortlist  
- **`recommendation.json`** — best point, top candidates, summary metadata  

## One-command demo

```bash
python3 -m src.main --country France --crop wheat --points 100 --seed 42 --top-n 10 --demo-safe
```

## Reliability

- Retries, timeouts, and exponential backoff on outbound HTTP.
- Responses cached under **`.cache/`** to speed repeated runs.
- Partial missing data lowers confidence instead of failing the whole row.
- The pipeline can abort if too many points fail **both** weather and soil fetches (`FAILURE_ABORT_RATIO`).
