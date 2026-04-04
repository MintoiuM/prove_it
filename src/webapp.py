from __future__ import annotations

import argparse
import html
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

from src.config import Settings
from src.geo.grid import COUNTRY_ENVELOPES
from src.main import run_pipeline
from src.models.crop_profiles import list_crop_names

LAST_RESULT: dict | None = None
LAST_ERROR: str | None = None


class CropSuitabilityHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path not in ("/", "/index.html"):
            self.send_error(HTTPStatus.NOT_FOUND, "Page not found")
            return
        self._send_html(_render_page(result=LAST_RESULT, error=LAST_ERROR))

    def do_POST(self) -> None:
        if self.path != "/run":
            self.send_error(HTTPStatus.NOT_FOUND, "Page not found")
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length).decode("utf-8")
        form = parse_qs(body)

        try:
            country = _required_text(form, "country")
            crop = _required_text(form, "crop")
            points = _required_int(form, "points", min_value=1, max_value=500)
            top_n = _required_int(form, "top_n", min_value=1, max_value=100)
            seed = _required_int(form, "seed", min_value=1, max_value=10_000_000)
            demo_safe = form.get("demo_safe", ["off"])[0] == "on"
            use_llm = form.get("use_llm", ["off"])[0] == "on"

            settings = Settings.from_env()
            result = run_pipeline(
                country=country,
                crop=crop,
                points=points,
                seed=seed,
                top_n=top_n,
                start_date=settings.default_start_date,
                end_date=settings.default_end_date,
                demo_safe=demo_safe,
                use_llm=use_llm,
            )
            self._set_last_state(result=result, error=None)
            self._redirect_to_home()
        except Exception as exc:
            self._set_last_state(result=None, error=str(exc))
            self._redirect_to_home()

    def log_message(self, fmt: str, *args) -> None:
        # Keep console output minimal; main results appear in UI.
        return

    def _send_html(self, payload: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = payload.encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _redirect_to_home(self) -> None:
        self.send_response(HTTPStatus.SEE_OTHER.value)
        self.send_header("Location", "/")
        self.end_headers()

    def _set_last_state(self, result: dict | None, error: str | None) -> None:
        global LAST_RESULT, LAST_ERROR
        LAST_RESULT = result
        LAST_ERROR = error


def _required_text(form: dict[str, list[str]], key: str) -> str:
    value = form.get(key, [""])[0].strip()
    if not value:
        raise ValueError(f"Missing required field: {key}")
    return value


def _required_int(
    form: dict[str, list[str]], key: str, min_value: int, max_value: int
) -> int:
    raw = _required_text(form, key)
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"Field '{key}' must be an integer.") from exc
    if not min_value <= value <= max_value:
        raise ValueError(f"Field '{key}' must be in range [{min_value}, {max_value}].")
    return value


def _render_page(result: dict | None = None, error: str | None = None) -> str:
    settings = Settings.from_env()
    countries = sorted(item.name for item in COUNTRY_ENVELOPES.values())
    crops = list_crop_names()

    options_country = "".join(
        f'<option value="{html.escape(country)}">{html.escape(country)}</option>'
        for country in countries
    )
    options_crop = "".join(
        f'<option value="{html.escape(crop)}">{html.escape(crop)}</option>'
        for crop in crops
    )
    error_html = ""
    if error:
        error_html = f'<div class="error">Error: {html.escape(error)}</div>'

    result_html = ""
    map_assets = ""
    if result:
        best = result["best_point"]
        map_data = {
            "country": result["country"],
            "crop": result["crop"],
            "best_point": {
                "point_id": best["point_id"],
                "lat": best["lat"],
                "lon": best["lon"],
                "score": best["score"],
                "score_band": best.get("score_band", "unknown"),
                "confidence": best["confidence"],
            },
            "top_candidates": [
                {
                    "point_id": row["point_id"],
                    "lat": row["lat"],
                    "lon": row["lon"],
                    "score": row["score"],
                    "score_band": row.get("score_band", "unknown"),
                    "confidence": row["confidence"],
                }
                for row in result["top_candidates"]
            ],
        }
        map_json = json.dumps(map_data, ensure_ascii=True).replace("</", "<\\/")
        best_osm_link = (
            f"https://www.openstreetmap.org/?mlat={best['lat']}&mlon={best['lon']}"
            f"#map=7/{best['lat']}/{best['lon']}"
        )
        map_assets = """
        <link
          rel="stylesheet"
          href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
          integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="
          crossorigin=""
        />
        <script
          src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
          integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="
          crossorigin=""
        ></script>
        """
        result_html = f"""
        <section class="card">
          <h2>Run Result</h2>
          <p><strong>Run ID:</strong> {html.escape(result["run_id"])}</p>
          <p><strong>Country:</strong> {html.escape(result["country"])}</p>
          <p><strong>Crop:</strong> {html.escape(result["crop"])}</p>
          <p><strong>Ranking engine:</strong> {html.escape(str(result.get("ranking_engine", "rules")).upper())}</p>
          <p><strong>Best point:</strong> {html.escape(best["point_id"])} ({best["lat"]}, {best["lon"]})</p>
          <p><strong>Score:</strong> {best["score"]} ({html.escape(str(best.get("score_band", "unknown")).title())}) | <strong>Confidence:</strong> {best["confidence"]}</p>
          <p><strong>Reasoning:</strong> {html.escape(str(best.get("llm_reasoning", "Rules-based scoring without LLM reasoning.")))}</p>
          <p><strong>Artifacts:</strong> {html.escape(result["run_dir"])}</p>
          <p><strong>Map link (best point):</strong> <a href="{html.escape(best_osm_link)}" target="_blank" rel="noopener noreferrer">Open in OpenStreetMap</a></p>
          <div id="result-map" class="result-map"></div>
          <div class="field-help">Blue marker = best point. Green markers = other top candidates.</div>
          <script id="map-data" type="application/json">{map_json}</script>
          <script>
            (function () {{
              var mapDataNode = document.getElementById("map-data");
              var mapContainer = document.getElementById("result-map");
              if (!mapDataNode || !mapContainer || typeof L === "undefined") {{
                return;
              }}
              var data = JSON.parse(mapDataNode.textContent);
              var best = data.best_point;
              var candidates = data.top_candidates || [];

              var map = L.map("result-map");
              L.tileLayer("https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png", {{
                maxZoom: 18,
                attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
              }}).addTo(map);

              var bestIcon = L.icon({{
                iconUrl: "https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-blue.png",
                shadowUrl: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/0.7.7/images/marker-shadow.png",
                iconSize: [25, 41],
                iconAnchor: [12, 41],
                popupAnchor: [1, -34],
                shadowSize: [41, 41]
              }});
              var candidateIcon = L.icon({{
                iconUrl: "https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-green.png",
                shadowUrl: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/0.7.7/images/marker-shadow.png",
                iconSize: [25, 41],
                iconAnchor: [12, 41],
                popupAnchor: [1, -34],
                shadowSize: [41, 41]
              }});

              var markers = [];
              var bestMarker = L.marker([best.lat, best.lon], {{ icon: bestIcon }})
                .addTo(map)
                .bindPopup(
                  "<strong>Best point</strong><br/>" +
                  best.point_id + "<br/>" +
                  "Score: " + best.score + "<br/>" +
                  "Band: " + best.score_band + "<br/>" +
                  "Confidence: " + best.confidence
                );
              markers.push(bestMarker);

              for (var i = 0; i < candidates.length; i += 1) {{
                var item = candidates[i];
                if (item.point_id === best.point_id) {{
                  continue;
                }}
                var marker = L.marker([item.lat, item.lon], {{ icon: candidateIcon }})
                  .addTo(map)
                  .bindPopup(
                    "<strong>Candidate</strong><br/>" +
                    item.point_id + "<br/>" +
                    "Score: " + item.score + "<br/>" +
                    "Band: " + item.score_band + "<br/>" +
                    "Confidence: " + item.confidence
                  );
                markers.push(marker);
              }}

              var group = L.featureGroup(markers);
              map.fitBounds(group.getBounds().pad(0.2));
              if (!isFinite(map.getCenter().lat) || !isFinite(map.getCenter().lng)) {{
                map.setView([best.lat, best.lon], 7);
              }}
            }})();
          </script>
          <details>
            <summary>Show recommendation JSON</summary>
            <pre>{html.escape(json.dumps(result["recommendation"], indent=2, ensure_ascii=True))}</pre>
          </details>
        </section>
        """

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Crop Suitability MVP</title>
  {map_assets}
  <style>
    body {{
      font-family: "Inter", "Segoe UI", Arial, sans-serif;
      margin: 0;
      background: #f1f5f9;
      color: #0f172a;
      line-height: 1.5;
    }}
    .page {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 28px 24px 40px;
    }}
    .card {{
      background: #ffffff;
      border-radius: 14px;
      padding: 22px;
      box-shadow: 0 4px 18px rgba(15, 23, 42, 0.08);
      margin-bottom: 18px;
      border: 1px solid #e2e8f0;
    }}
    h1 {{ margin-top: 0; margin-bottom: 8px; font-size: 30px; letter-spacing: 0.2px; }}
    h2 {{ margin-top: 0; margin-bottom: 10px; }}
    .subtitle {{ color: #475569; margin-top: 0; margin-bottom: 14px; font-size: 15px; }}
    .form-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 14px; }}
    .field {{
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-radius: 12px;
      padding: 12px;
    }}
    label {{ display: block; font-size: 13px; color: #1e293b; margin-bottom: 6px; font-weight: 700; }}
    .field-help {{ font-size: 12px; color: #64748b; margin-top: 6px; line-height: 1.4; }}
    input, select {{
      width: 100%;
      box-sizing: border-box;
      padding: 10px 12px;
      border-radius: 10px;
      border: 1px solid #cbd5e1;
      background: #ffffff;
      font-size: 14px;
    }}
    input:focus, select:focus {{
      outline: none;
      border-color: #3b82f6;
      box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.15);
    }}
    button {{
      padding: 12px 18px;
      border: none;
      border-radius: 10px;
      background: #2563eb;
      color: #fff;
      cursor: pointer;
      font-size: 15px;
      font-weight: 600;
    }}
    button:hover {{ background: #1d4ed8; }}
    .error {{ background: #fee2e2; color: #991b1b; border-radius: 10px; padding: 12px; margin-bottom: 12px; }}
    pre {{ overflow: auto; background: #0b1020; color: #d1d5db; padding: 14px; border-radius: 10px; }}
    .result-map {{
      width: 100%;
      min-height: 420px;
      border-radius: 12px;
      border: 1px solid #cbd5e1;
      margin: 12px 0 8px;
    }}
    .legend ul {{ margin: 8px 0 0; padding-left: 20px; color: #334155; }}
    .legend li {{ margin: 6px 0; }}
    .checkbox-row {{ display: flex; align-items: center; gap: 9px; margin-top: 10px; color: #334155; }}
    .checkbox-row input {{ width: auto; margin: 0; transform: scale(1.1); }}
    .full {{ grid-column: 1 / -1; }}
  </style>
</head>
<body>
  <div class="page">
  <section class="card">
    <h1>Europe Crop Suitability MVP</h1>
    <p class="subtitle">Insert inputs and run analysis from the browser.</p>
    {error_html}
    <div class="legend">
      <strong>Input Legend</strong>
      <ul>
        <li><strong>Candidate points:</strong> how many locations to evaluate (recommended: 10 for quick test, 100 for full demo).</li>
        <li><strong>Top results to return:</strong> how many best-ranked points appear in the output shortlist.</li>
        <li><strong>Random seed:</strong> keeps sampling deterministic; same seed + same inputs gives same points.</li>
        <li><strong>Demo-safe mode:</strong> slower but safer API pacing for presentations and unstable networks.</li>
        <li><strong>Llama 3 thinker mode:</strong> asks a local Llama 3 model (Ollama) to rate candidates using weather + soil + crop context.</li>
      </ul>
    </div>
    <form method="post" action="/run" class="form-grid">
      <div class="field">
        <label for="country">Country (European target country)</label>
        <select id="country" name="country">{options_country}</select>
        <div class="field-help">Select the country where cultivation suitability is evaluated.</div>
      </div>
      <div class="field">
        <label for="crop">Crop type</label>
        <select id="crop" name="crop">{options_crop}</select>
        <div class="field-help">Choose the crop profile used by the ranking model.</div>
      </div>
      <div class="field">
        <label for="points">Candidate points (1-500)</label>
        <input id="points" name="points" value="{settings.default_points}" />
        <div class="field-help">More points improve coverage but increase runtime and API calls.</div>
      </div>
      <div class="field">
        <label for="top_n">Top results to return (1-100)</label>
        <input id="top_n" name="top_n" value="{settings.default_top_n}" />
        <div class="field-help">Number of highest-scoring locations shown in final results.</div>
      </div>
      <div class="field">
        <label for="seed">Random seed</label>
        <input id="seed" name="seed" value="{settings.default_seed}" />
        <div class="field-help">Use a fixed value for reproducible rankings across reruns.</div>
      </div>
      <div class="field">
        <label for="demo_safe">Run mode</label>
        <div class="checkbox-row">
          <input id="demo_safe" name="demo_safe" type="checkbox" checked />
          <span>Enable demo-safe mode (recommended)</span>
        </div>
        <div class="field-help">Applies conservative throttling and fewer concurrent requests.</div>
      </div>
      <div class="field">
        <label for="use_llm">Thinking engine</label>
        <div class="checkbox-row">
          <input id="use_llm" name="use_llm" type="checkbox" />
          <span>Use Llama 3 reasoning (requires local Ollama)</span>
        </div>
        <div class="field-help">When enabled, Llama 3 does the ranking decision and explains why the best point was chosen. Current model: {html.escape(settings.ollama_model)} (max points: {settings.llm_max_points}).</div>
      </div>
      <div class="full">
        <button type="submit">Run Suitability Analysis</button>
      </div>
    </form>
  </section>
  {result_html}
  </div>
</body>
</html>
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Web UI for crop suitability MVP")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    server = ThreadingHTTPServer((args.host, args.port), CropSuitabilityHandler)
    print(f"Web app running on http://{args.host}:{args.port}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

