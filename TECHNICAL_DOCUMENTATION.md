# Technical Documentation - Europe Crop Suitability MVP

## Problem statement

Given a `country` in Europe and a `crop`, the system samples 100 candidate points, collects weather and soil signals, computes suitability, and outputs ranked recommendations.

## Scope (current iteration)

- Focus only on agronomic suitability/yield potential.
- Use external data:
  - Open-Meteo climate aggregates
  - SoilGrids soil properties
- Produce:
  - ranked candidate points
  - best point recommendation
  - 100 km operational area metadata centered on best point

## Architecture

The implementation follows a simple master-worker pattern:

- `geo/grid.py` (sampler): deterministic point generation from country envelope.
- `collectors/weather_worker.py`: weather feature collection with retries/timeouts.
- `collectors/soil_worker.py`: soil feature collection with stricter pacing.
- `scoring/suitability.py` (master): feature normalization, scoring, ranking, confidence.
- `output/recommendation.py`: JSON + CSV artifacts for judge/demo consumption.
- `main.py`: orchestration, diagnostics, and CLI.

## Data model

Each candidate point is represented as:

- `point_id`: deterministic ID (`P001` ... `P100`)
- `lat`, `lon`: coordinates
- `country`: normalized country name
- feature columns (weather + soil)
- `missing_features`: list of unavailable features
- `score`: final suitability in `[0, 100]`
- `confidence`: confidence score in `[0, 1]`

## Scoring model

Crop profiles define:

- ideal feature ranges
- hard minimum/maximum constraints
- feature weights

Master scoring behavior:

- weighted distance-to-ideal contribution per available feature
- hard-constraint penalties for critical violations
- missing-feature penalty and confidence reduction
- deterministic tie-break by `point_id`

## API usage policy

### Open-Meteo
- Endpoint: archive climate API for point-specific daily metrics.
- Moderately parallel worker execution is allowed.
- Retries with exponential backoff + jitter.

### SoilGrids
- Endpoint: soil properties query API.
- Conservative pace (serial/low concurrency) to maximize reliability.
- Retries with exponential backoff + jitter.

## Reliability controls

- Request timeout per call.
- Bounded retries with backoff.
- Local cache for repeated requests by coordinates/endpoint key.
- Fail-soft point handling:
  - if one source fails, continue with missing-feature penalties
  - if failures exceed configured threshold, abort with diagnostics
- Deterministic runs using fixed seed and run-specific output directories.

## CLI and output artifacts

The demo entrypoint:

```bash
python -m src.main --country France --crop wheat --demo-safe
```

Artifacts produced in run folder:

- `candidates.csv`: merged per-point features and diagnostics
- `recommendation.json`: best point, top candidates, confidence, and run summary
- `top_candidates.csv`: human-readable shortlist

## Demo flow for judges

1. Pick country + crop.
2. Run one command.
3. Inspect ranking and recommendation outputs.
4. Review diagnostics (success counts, partial points, elapsed stages).

## Security and secrets

- No API keys are required for default MVP API usage.
- Runtime knobs are controlled via environment variables.
- `.env.example` documents optional overrides and safe defaults.
