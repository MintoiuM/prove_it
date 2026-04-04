# Europe Crop Suitability MVP

This project evaluates cultivation suitability for a chosen crop in a selected European country.

## Vision

Build a reliability-first decision support MVP that:
- samples 100 deterministic candidate points inside a country boundary envelope
- retrieves climate and soil features per point
- scores each point against crop requirements
- returns the best point, ranked alternatives, and a 100 km operational zone

## Current MVP assumptions

- Objective: agronomic suitability only (no market-demand or price layer yet).
- Geography: only countries mapped in the built-in Europe country catalog are accepted.
- Data sources:
  - Open-Meteo for weather aggregates
  - SoilGrids for soil properties
- Determinism: fixed seed generates the same candidate points and ranking order.
- Reliability over complexity: simple interpretable scoring beats black-box modeling in this phase.

## Constraints and non-goals

- External APIs may be slow or intermittently unavailable; fail-soft behavior is mandatory.
- We avoid heavy geospatial dependencies for the MVP and use country envelopes.
- No live map UI in core scope.
- No financial/profitability optimization in this version.

## Delivery principles

- Keep one-command demo flow for judges.
- Persist intermediate outputs for transparency (`CSV` + run diagnostics).
- Add confidence scoring so partial data still produces useful output.
- Keep architecture modular (collectors, scoring, output) for easy phase-2 upgrades.

## Near-term roadmap after MVP

1. Add country polygon sampling from official boundaries for tighter geospatial accuracy.
2. Introduce uncertainty intervals and confidence explanations.
3. Add market-demand/profitability as a second scoring head.
4. Add lightweight visualization of top points and operational zone.
