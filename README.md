# Europe Crop Suitability MVP

Runnable MVP for selecting high-suitability cultivation points inside a supported European country.

## What it does

- Accepts `country` and `crop` as inputs.
- Generates 100 deterministic candidate points.
- Collects weather features from Open-Meteo.
- Collects soil features from SoilGrids.
- Computes suitability score `[0, 100]` with confidence.
- Optionally uses local Llama 3 (Ollama) to reason and rerank candidates.
- Exports ranked recommendations and run diagnostics.

## Quick start

1. Create and activate a Python virtual environment.
2. Copy environment defaults:

```bash
cp .env.example .env
```

3. Run demo:

```bash
python -m src.main --country France --crop wheat --demo-safe
```

Run with Llama 3 thinker mode (optional):

```bash
python -m src.main --country France --crop wheat --demo-safe --use-llm
```

## Web application UI

Run the browser UI:

```bash
python -m src.webapp --host 127.0.0.1 --port 8080
```

Then open:

- `http://127.0.0.1:8080`

The UI lets you insert country/crop/points/top-N/seed and run the analysis directly from the page.
Enable **Use Llama 3 reasoning** in the UI to use LLM-based candidate rating.

## Llama 3 setup (optional)

Install and run Ollama locally, then pull a model:

```bash
ollama serve
ollama pull llama3
```

Default config uses:
- endpoint: `http://127.0.0.1:11434`
- model: `llama3`

You can customize with `.env`:
- `OLLAMA_ENDPOINT`
- `OLLAMA_MODEL`
- `LLM_TIMEOUT_SECONDS`
- `LLM_MAX_POINTS`

## Supported crops

- `wheat`
- `corn`
- `sunflower`

## Supported countries (MVP catalog)

France, Spain, Italy, Germany, Romania, Poland, Netherlands, Belgium, Portugal, Hungary.

## Output artifacts

Each run writes into `runs/<run_id>/`:

- `candidates.csv`: merged feature table for sampled points
- `top_candidates.csv`: ranked shortlist
- `recommendation.json`: best point, top candidates, score explanation, diagnostics

## Judge-friendly one-command demo

```bash
python -m src.main --country France --crop wheat --points 100 --seed 42 --top-n 10 --demo-safe
```

This mode applies conservative request pacing and low concurrency for safer live demo execution.

## Reliability notes

- Request timeout, retry, and exponential backoff are enabled for both APIs.
- API payloads are cached locally in `.cache/` to speed reruns.
- Partial failures degrade scores with confidence penalties instead of hard crash.
- Run aborts if too many points fail both weather and soil data retrieval.

