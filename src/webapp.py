from __future__ import annotations

import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from src.config import Settings, resolve_nuts2_yields_csv_path
from src.data.nuts2_yields import Nuts2YieldStore
from src.geo.grid import COUNTRY_ENVELOPES
from src.geo.nuts import region_dropdown_choices
from src.main import run_pipeline
from src.models.crop_profiles import crop_display_labels, list_crop_names

LAST_RESULT: dict | None = None
LAST_ERROR: str | None = None
TEMPLATE_PATH = Path("site_provit.html")


class CropSuitabilityHandler(BaseHTTPRequestHandler):
    def send_error(self, code, message=None, explain=None) -> None:  # type: ignore[override]
        try:
            super().send_error(code, message, explain)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/favicon.ico":
            self.send_response(HTTPStatus.NO_CONTENT.value)
            self.end_headers()
            return
        if path == "/api/regions":
            self._handle_regions_api(parsed.query)
            return
        if path not in ("/", "/index.html"):
            self.send_error(HTTPStatus.NOT_FOUND, "Page not found")
            return
        self._send_html(_render_page(result=LAST_RESULT, error=LAST_ERROR))

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/run-json":
            self._handle_run_json()
            return
        if path == "/run":
            self._handle_legacy_form_post()
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Page not found")

    def _handle_regions_api(self, query: str) -> None:
        qs = parse_qs(query)
        country = str(qs.get("country", [""])[0]).strip()
        path = resolve_nuts2_yields_csv_path()
        store = Nuts2YieldStore(path) if path else None
        try:
            regions = region_dropdown_choices(country, store)
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        self._send_json({"ok": True, "regions": regions})

    def _handle_run_json(self) -> None:
        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length).decode("utf-8")
        payload = json.loads(body or "{}")
        settings = Settings.from_env()

        try:
            country = str(payload.get("country", "")).strip()
            crop = str(payload.get("crop", "")).strip().lower()
            points = _coerce_int(payload.get("points"), 1, 500, settings.default_points)
            top_n = _coerce_int(payload.get("top_n"), 1, 100, settings.default_top_n)
            seed = _coerce_int(payload.get("seed"), 1, 10_000_000, settings.default_seed)
            demo_safe = bool(payload.get("demo_safe", True))
            use_llm = bool(payload.get("use_llm", False))
            risk_analysis = bool(payload.get("risk_analysis", False))
            extended_reasoning = bool(payload.get("extended_reasoning", False))
            region_raw = payload.get("region")
            region = (
                str(region_raw).strip()
                if region_raw is not None and str(region_raw).strip()
                else None
            )

            if not country:
                raise ValueError("Country is required.")
            if not crop:
                raise ValueError("Crop is required.")

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
                risk_analysis=risk_analysis,
                extended_reasoning=extended_reasoning,
                region=region,
            )
            self._set_last_state(result=result, error=None)
            self._send_json({"ok": True, "result": result})
        except Exception as exc:
            self._set_last_state(result=None, error=str(exc))
            self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    def _handle_legacy_form_post(self) -> None:
        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length).decode("utf-8")
        form = parse_qs(body)
        settings = Settings.from_env()
        try:
            region_form = str(form.get("region", [""])[0]).strip()
            result = run_pipeline(
                country=str(form.get("country", [""])[0]),
                crop=str(form.get("crop", [""])[0]).lower(),
                region=region_form or None,
                points=_coerce_int(form.get("points", [settings.default_points])[0], 1, 500, settings.default_points),
                seed=_coerce_int(form.get("seed", [settings.default_seed])[0], 1, 10_000_000, settings.default_seed),
                top_n=_coerce_int(form.get("top_n", [settings.default_top_n])[0], 1, 100, settings.default_top_n),
                start_date=settings.default_start_date,
                end_date=settings.default_end_date,
                demo_safe=form.get("demo_safe", ["off"])[0] == "on",
                use_llm=form.get("use_llm", ["off"])[0] == "on",
                risk_analysis=form.get("risk_analysis", ["off"])[0] == "on",
                extended_reasoning=form.get("extended_reasoning", ["off"])[0] == "on",
            )
            self._set_last_state(result=result, error=None)
            self._redirect_to_home()
        except Exception as exc:
            self._set_last_state(result=None, error=str(exc))
            self._redirect_to_home()

    def log_message(self, fmt: str, *args) -> None:
        return

    def _send_html(self, payload: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = payload.encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        try:
            self.wfile.write(encoded)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        try:
            self.wfile.write(encoded)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _redirect_to_home(self) -> None:
        self.send_response(HTTPStatus.SEE_OTHER.value)
        self.send_header("Location", "/")
        self.end_headers()

    def _set_last_state(self, result: dict | None, error: str | None) -> None:
        global LAST_RESULT, LAST_ERROR
        LAST_RESULT = result
        LAST_ERROR = error


def _coerce_int(raw: object, min_value: int, max_value: int, default: int) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(min_value, min(max_value, value))


def _render_page(result: dict | None = None, error: str | None = None) -> str:
    if not TEMPLATE_PATH.exists():
        return "<h1>Template file site_provit.html not found.</h1>"

    settings = Settings.from_env()
    llm_backend_help = (
        f"Gemini ({settings.gemini_model})"
        if settings.llm_provider == "gemini"
        else f"Ollama: {settings.ollama_model}"
    )
    crop_names = list_crop_names()
    default_crop = "wheat" if "wheat" in crop_names else (crop_names[0] if crop_names else "corn")
    app_state = {
        "countries": sorted(item.name for item in COUNTRY_ENVELOPES.values()),
        "crops": crop_names,
        "crop_labels": crop_display_labels(),
        "defaults": {
            "country": "France",
            "crop": default_crop,
            "region": "",
            "points": settings.default_points,
            "top_n": settings.default_top_n,
            "seed": settings.default_seed,
            "demo_safe": True,
            "use_llm": False,
            "risk_analysis": True,
            "extended_reasoning": False,
            "ollama_model": settings.ollama_model,
            "llm_max_points": settings.llm_max_points,
            "llm_provider": settings.llm_provider,
            "llm_backend_help": llm_backend_help,
        },
        "initial_result": result,
        "initial_error": error,
        "google_maps_api_key": settings.google_maps_api_key,
    }
    template_html = TEMPLATE_PATH.read_text(encoding="utf-8")
    bridge = _build_bridge_script(app_state)
    return template_html.replace("</body>", f"{bridge}\n</body>")


def _build_bridge_script(app_state: dict) -> str:
    state_json = json.dumps(app_state, ensure_ascii=True).replace("</", "<\\/")
    return f"""
<script>
const APP_STATE = {state_json};

let _resultMap = null;
let _gmMarkers = [];
let _mapsLoadPromise = null;

let _resultsRows = [];
let _lastPayloadForResults = null;
let _sortState = {{ key: null, dir: 1 }};

function _numericField(row, field) {{
  const v = row[field];
  if (v == null) return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}}

function _compareResultsRows(a, b, key) {{
  if (key === 'rank') return a.__origIndex - b.__origIndex;
  if (key === 'coord') {{
    const la = Number(a.lat), lb = Number(b.lat);
    const lo = Number(a.lon), lbo = Number(b.lon);
    const ala = Number.isFinite(la) ? la : 0;
    const alb = Number.isFinite(lb) ? lb : 0;
    const alo = Number.isFinite(lo) ? lo : 0;
    const albo = Number.isFinite(lbo) ? lbo : 0;
    if (ala !== alb) return ala - alb;
    return alo - albo;
  }}
  if (key === 'ph') {{
    const na = _numericField(a, 'soil_ph'), nb = _numericField(b, 'soil_ph');
    if (na == null && nb == null) return 0;
    if (na == null) return 1;
    if (nb == null) return -1;
    return na - nb;
  }}
  if (key === 'temp') {{
    const na = _numericField(a, 'mean_temp_c'), nb = _numericField(b, 'mean_temp_c');
    if (na == null && nb == null) return 0;
    if (na == null) return 1;
    if (nb == null) return -1;
    return na - nb;
  }}
  if (key === 'rain') {{
    const na = _numericField(a, 'rainfall_mm'), nb = _numericField(b, 'rainfall_mm');
    if (na == null && nb == null) return 0;
    if (na == null) return 1;
    if (nb == null) return -1;
    return na - nb;
  }}
  if (key === 'score') {{
    return (Number(a.score) || 0) - (Number(b.score) || 0);
  }}
  return 0;
}}

function _sortedResultsRows() {{
  if (!_sortState.key) return _resultsRows.slice();
  const rows = _resultsRows.slice();
  rows.sort((a, b) => _compareResultsRows(a, b, _sortState.key) * _sortState.dir);
  return rows;
}}

function _updateSortHeaders() {{
  document.querySelectorAll('.results-table thead th[data-sort]').forEach((th) => {{
    th.classList.remove('sorted', 'sorted--asc', 'sorted--desc');
    const k = th.getAttribute('data-sort');
    if (_sortState.key === k) {{
      th.classList.add('sorted', _sortState.dir === 1 ? 'sorted--asc' : 'sorted--desc');
      th.setAttribute('aria-sort', _sortState.dir === 1 ? 'ascending' : 'descending');
    }} else {{
      th.setAttribute('aria-sort', 'none');
    }}
  }});
}}

function _paintResultsTableBody() {{
  const rows = _sortedResultsRows();
  const html = rows.map((item, index) => {{
    const rank = index + 1;
    const lat = Number(item.lat || 0).toFixed(4);
    const lon = Number(item.lon || 0).toFixed(4);
    const ph = item.soil_ph != null ? Number(item.soil_ph).toFixed(2) : 'n/a';
    const temp = item.mean_temp_c != null ? Number(item.mean_temp_c).toFixed(1) + 'C' : 'n/a';
    const rain = item.rainfall_mm != null ? Number(item.rainfall_mm).toFixed(0) + ' mm' : 'n/a';
    const score = Number(item.score || 0);
    const pct = Math.max(0, Math.min(100, score));
    return `
      <tr>
        <td><div class="rank-num ${{rank === 1 ? 'top' : ''}}">${{rank}}</div></td>
        <td><span class="coord">${{lat}}, ${{lon}}</span></td>
        <td>${{ph}}</td>
        <td>${{temp}}</td>
        <td>${{rain}}</td>
        <td>
          <div class="score-cell">
            <div class="bar-track"><div class="bar-fill" style="width:${{pct}}%"></div></div>
            <span class="score-pct">${{score.toFixed(1)}}%</span>
          </div>
        </td>
      </tr>`;
  }}).join('');
  document.getElementById('results-tbody').innerHTML = html;
  _updateSortHeaders();
  void _renderResultMap(rows);
}}

function onResultsSortHeaderClick(key) {{
  if (!_resultsRows.length) return;
  if (_sortState.key === key) {{
    _sortState.dir = -_sortState.dir;
  }} else {{
    _sortState.key = key;
    _sortState.dir = key === 'score' ? -1 : 1;
  }}
  _paintResultsTableBody();
}}

function initResultsTableSorting() {{
  const thead = document.querySelector('.results-table thead');
  if (!thead) return;
  thead.querySelectorAll('th[data-sort]').forEach((th) => {{
    th.addEventListener('click', () => onResultsSortHeaderClick(th.getAttribute('data-sort')));
    th.addEventListener('keydown', (e) => {{
      if (e.key === 'Enter' || e.key === ' ') {{
        e.preventDefault();
        onResultsSortHeaderClick(th.getAttribute('data-sort'));
      }}
    }});
  }});
}}

function _destroyResultMap() {{
  _gmMarkers.forEach((m) => m.setMap && m.setMap(null));
  _gmMarkers = [];
  if (_resultMap) {{
    if (typeof _resultMap.remove === 'function') {{
      _resultMap.remove();
    }}
    _resultMap = null;
  }}
  const el = document.getElementById('result-map');
  if (el) el.replaceChildren();
}}

function _ensureGoogleMaps() {{
  if (window.google && google.maps) return Promise.resolve();
  const key = APP_STATE.google_maps_api_key;
  if (!key) return Promise.reject(new Error('No Google Maps API key'));
  if (_mapsLoadPromise) return _mapsLoadPromise;
  _mapsLoadPromise = new Promise((resolve, reject) => {{
    const cbName = '_gmapsInit_' + Math.random().toString(36).slice(2);
    window[cbName] = () => {{
      delete window[cbName];
      resolve();
    }};
    const s = document.createElement('script');
    s.src = 'https://maps.googleapis.com/maps/api/js?key=' + encodeURIComponent(key)
      + '&loading=async&callback=' + encodeURIComponent(cbName);
    s.async = true;
    s.onerror = () => {{
      delete window[cbName];
      _mapsLoadPromise = null;
      reject(new Error('Failed to load Google Maps'));
    }};
    document.head.appendChild(s);
  }});
  return _mapsLoadPromise;
}}

async function _renderResultMap(top) {{
  const wrap = document.getElementById('result-map-wrap');
  const el = document.getElementById('result-map');
  if (!wrap || !el) return;
  const markers = [];
  (top || []).forEach((item, index) => {{
    const lat = Number(item.lat);
    const lon = Number(item.lon);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
    markers.push({{ lat, lon, rank: index + 1 }});
  }});
  if (markers.length === 0) {{
    wrap.style.display = 'none';
    wrap.setAttribute('aria-hidden', 'true');
    _destroyResultMap();
    return;
  }}
  wrap.style.display = 'block';
  wrap.setAttribute('aria-hidden', 'false');
  _destroyResultMap();

  if (APP_STATE.google_maps_api_key) {{
    try {{
      await _ensureGoogleMaps();
    }} catch (e) {{
      el.textContent = 'Map error: ' + (e && e.message ? e.message : String(e));
      return;
    }}
    const map = new google.maps.Map(el, {{
      zoom: 8,
      center: {{ lat: markers[0].lat, lng: markers[0].lon }},
      mapTypeControl: true,
      scrollwheel: false
    }});
    const bounds = new google.maps.LatLngBounds();
    markers.forEach((m) => {{
      const isTop = m.rank === 1;
      const marker = new google.maps.Marker({{
        position: {{ lat: m.lat, lng: m.lon }},
        map,
        title: '#' + m.rank + ' · ' + m.lat.toFixed(4) + ', ' + m.lon.toFixed(4),
        icon: {{
          path: google.maps.SymbolPath.CIRCLE,
          scale: isTop ? 11 : 7,
          fillColor: isTop ? '#5A8A40' : '#6B5240',
          fillOpacity: 0.9,
          strokeColor: '#ffffff',
          strokeWeight: 2
        }}
      }});
      _gmMarkers.push(marker);
      bounds.extend({{ lat: m.lat, lng: m.lon }});
    }});
    map.fitBounds(bounds);
    google.maps.event.addListenerOnce(map, 'bounds_changed', () => {{
      if (map.getZoom() > 11) map.setZoom(11);
    }});
    _resultMap = map;
    setTimeout(() => google.maps.event.trigger(map, 'resize'), 50);
    setTimeout(() => google.maps.event.trigger(map, 'resize'), 350);
    return;
  }}

  if (typeof L === 'undefined') {{
    el.textContent = 'Add GOOGLE_MAPS_API_KEY to .env or include Leaflet for the map.';
    return;
  }}
  const map = L.map(el, {{ scrollWheelZoom: false }});
  L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors'
  }}).addTo(map);
  const bounds = L.latLngBounds([]);
  markers.forEach((m) => {{
    const isTop = m.rank === 1;
    const cm = L.circleMarker([m.lat, m.lon], {{
      radius: isTop ? 11 : 7,
      fillColor: isTop ? '#5A8A40' : '#6B5240',
      color: '#fff',
      weight: 2,
      opacity: 1,
      fillOpacity: 0.9
    }});
    cm.bindPopup('#' + m.rank + ' · ' + m.lat.toFixed(4) + ', ' + m.lon.toFixed(4));
    cm.addTo(map);
    bounds.extend([m.lat, m.lon]);
  }});
  if (bounds.isValid()) {{
    map.fitBounds(bounds, {{ padding: [28, 28], maxZoom: 11 }});
  }} else {{
    map.setView([markers[0].lat, markers[0].lon], 8);
  }}
  _resultMap = map;
  setTimeout(() => map.invalidateSize(), 50);
  setTimeout(() => map.invalidateSize(), 350);
}}

function _escAttr(s) {{
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/"/g, '&quot;');
}}

async function refreshRegions() {{
  const country = document.getElementById('country').value;
  const sel = document.getElementById('region');
  if (!sel) return;
  sel.innerHTML = '<option value="">Whole country</option>';
  try {{
    const r = await fetch('/api/regions?country=' + encodeURIComponent(country));
    const data = await r.json();
    if (!r.ok || !data.ok || !data.regions) return;
    sel.innerHTML = data.regions.map(o =>
      `<option value="${{_escAttr(o.value)}}">${{_escAttr(o.label)}}</option>`
    ).join('');
  }} catch (e) {{
    sel.innerHTML = '<option value="">Whole country</option>';
  }}
}}

function updateBreadcrumb() {{
  const country = document.getElementById('country').value;
  document.querySelector('.breadcrumb').textContent = 'Europe / ' + country;
  document.getElementById('loading-country').textContent = country;
}}

function selectMode(el) {{
  document.querySelectorAll('.mode-card').forEach(c => {{
    c.classList.remove('active');
    c.querySelector('.mode-indicator').innerHTML = '';
  }});
  el.classList.add('active');
  el.querySelector('.mode-indicator').innerHTML = '<div class="mode-dot"></div>';
}}

function _isDemoSafe() {{
  const active = document.querySelector('.mode-card.active .mode-name');
  return active && active.textContent.toLowerCase().includes('safe');
}}

function _isUseLlm() {{
  const firstToggle = document.querySelector('.toggle-list .toggle-btn');
  return !!(firstToggle && firstToggle.classList.contains('on'));
}}

function _isRiskAnalysis() {{
  const toggles = document.querySelectorAll('.toggle-list .toggle-btn');
  return !!(toggles[1] && toggles[1].classList.contains('on'));
}}

function _isExtendedReasoning() {{
  const toggles = document.querySelectorAll('.toggle-list .toggle-btn');
  return !!(toggles[2] && toggles[2].classList.contains('on'));
}}

async function handleRun() {{
  const btn = document.getElementById('run-btn');
  const dot = document.getElementById('status-dot');
  const statusText = document.getElementById('status-text');
  const pointsSlider = document.querySelectorAll('.slider-wrap input[type="range"]')[0];
  const topSlider = document.querySelectorAll('.slider-wrap input[type="range"]')[1];

  btn.disabled = true;
  dot.className = 'status-dot busy';
  statusText.textContent = 'Running...';
  document.getElementById('results-empty').style.display = 'none';
  document.getElementById('results-loading').style.display = 'flex';
  document.getElementById('results-content').style.display = 'none';
  updateBreadcrumb();

  const payload = {{
    country: document.getElementById('country').value,
    crop: document.getElementById('crop').value,
    region: document.getElementById('region') ? document.getElementById('region').value : '',
    points: Number(pointsSlider.value),
    top_n: Number(topSlider.value),
    seed: Number(document.getElementById('seed').value),
    demo_safe: _isDemoSafe(),
    use_llm: _isUseLlm(),
    risk_analysis: _isRiskAnalysis(),
    extended_reasoning: _isExtendedReasoning()
  }};

  try {{
    const response = await fetch('/run-json', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify(payload)
    }});
    const data = await response.json();
    if (!response.ok || !data.ok) {{
      throw new Error(data.error || 'Run failed');
    }}
    renderResults(data.result, payload);
    dot.className = 'status-dot';
    statusText.textContent = 'Ready';
  }} catch (err) {{
    const wrap = document.getElementById('result-map-wrap');
    if (wrap) {{
      wrap.style.display = 'none';
      wrap.setAttribute('aria-hidden', 'true');
    }}
    _destroyResultMap();
    const ai = document.getElementById('ai-text');
    ai.className = 'ai-text';
    ai.textContent = 'Error: ' + err.message;
    dot.className = 'status-dot';
    statusText.textContent = 'Error';
  }} finally {{
    btn.disabled = false;
    document.getElementById('results-loading').style.display = 'none';
    document.getElementById('results-content').style.display = 'flex';
  }}
}}

function renderResults(result, payload) {{
  const top = result.top_candidates || [];
  const best = result.best_point || {{}};
  _lastPayloadForResults = payload;
  document.getElementById('stat-sampled').textContent = String(payload.points);
  document.getElementById('stat-returned').textContent = String(top.length);
  document.getElementById('stat-top').innerHTML = (best.score ?? 0).toFixed(1) + '<span class="stat-unit"> %</span>';
  document.getElementById('stat-seed').textContent = String(payload.seed);
  const reg = result.region ? ` (${{result.region}})` : '';
  document.getElementById('results-title').textContent = `Top sites - ${{result.crop}} in ${{result.country}}${{reg}}`;

  _resultsRows = top.map((item, i) => Object.assign({{}}, item, {{ __origIndex: i }}));
  _sortState = {{ key: null, dir: 1 }};
  _paintResultsTableBody();
  const ai = document.getElementById('ai-text');
  ai.className = 'ai-text';
  const reasonParts = [];
  if (best.llm_reasoning) {{
    reasonParts.push(best.llm_reasoning);
  }}
  if (best.rules_reasoning) {{
    if (best.llm_reasoning) reasonParts.push('—');
    reasonParts.push(best.rules_reasoning);
  }} else if (!best.llm_reasoning) {{
    reasonParts.push('Rules-based ranking completed.');
  }}
  if (payload.risk_analysis && best.risk_level) {{
    reasonParts.push(`Risk level: ${{best.risk_level.toUpperCase()}} (${{
      Number(best.risk_index || 0).toFixed(2)
    }}).`);
    if (best.risk_summary) {{
      reasonParts.push(`Risk insight: ${{best.risk_summary}}`);
    }}
  }}
  const sum = result.summary || {{}};
  if (sum.nuts2_yield_applied) {{
    reasonParts.push(
      `Regional yield benchmark (NUTS2 file): ${{sum.nuts2_yield_tons_ha}} t/ha` +
      (sum.nuts2_yield_year ? ` (${{sum.nuts2_yield_year}})` : '') +
      ', blended into suitability score.'
    );
  }} else if (sum.nuts2_crop_in_file === false) {{
    reasonParts.push('Selected crop has no yield column in the NUTS2 file; regional yield was not applied.');
  }}
  ai.textContent = reasonParts.join('\\n\\n');
}}

(function initTemplateBinding() {{
  const countries = APP_STATE.countries || [];
  const crops = APP_STATE.crops || [];
  const cropLabels = APP_STATE.crop_labels || {{}};
  const defaults = APP_STATE.defaults || {{}};
  const countryEl = document.getElementById('country');
  const cropEl = document.getElementById('crop');
  countryEl.innerHTML = countries.map(c => `<option value="${{c}}">${{c}}</option>`).join('');
  cropEl.innerHTML = crops.map(c => {{
    const label = cropLabels[c] || c.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
    return `<option value="${{c}}">${{label}}</option>`;
  }}).join('');
  countryEl.value = defaults.country || countries[0];
  cropEl.value = defaults.crop || crops[0];

  countryEl.addEventListener('change', () => {{ updateBreadcrumb(); refreshRegions(); }});
  refreshRegions().then(() => {{
    const regEl = document.getElementById('region');
    if (regEl && defaults.region) regEl.value = defaults.region;
  }});

  const sliders = document.querySelectorAll('.slider-wrap input[type="range"]');
  if (sliders.length >= 2) {{
    sliders[0].value = String(defaults.points || 10);
    sliders[1].value = String(defaults.top_n || 5);
    document.getElementById('pts-val').textContent = String(sliders[0].value);
    document.getElementById('top-val').textContent = String(sliders[1].value);
  }}
  document.getElementById('seed').value = String(defaults.seed || 42);
  updateBreadcrumb();

  const help = document.querySelector('.toggle-item .toggle-sub');
  if (help) {{
    help.textContent = `${{defaults.llm_backend_help}} — max LLM-scored points: ${{defaults.llm_max_points}}`;
  }}
  const riskHelp = document.querySelectorAll('.toggle-item .toggle-sub')[1];
  if (riskHelp) {{
    riskHelp.textContent = 'Adds computed drought/frost/weather risk profile to results';
  }}
  const extendedHelp = document.querySelectorAll('.toggle-item .toggle-sub')[2];
  if (extendedHelp) {{
    extendedHelp.textContent = 'When LLM is enabled, asks for longer reasoning and mitigation tips';
  }}

  const toggles = document.querySelectorAll('.toggle-list .toggle-btn');
  if (toggles[0] && defaults.use_llm) toggles[0].classList.add('on');
  if (toggles[1] && defaults.risk_analysis) toggles[1].classList.add('on');
  if (toggles[2] && defaults.extended_reasoning) toggles[2].classList.add('on');

  if (APP_STATE.initial_error) {{
    const wrap = document.getElementById('result-map-wrap');
    if (wrap) {{
      wrap.style.display = 'none';
      wrap.setAttribute('aria-hidden', 'true');
    }}
    _destroyResultMap();
    const ai = document.getElementById('ai-text');
    ai.className = 'ai-text';
    ai.textContent = 'Last error: ' + APP_STATE.initial_error;
  }}
  if (APP_STATE.initial_result) {{
    renderResults(APP_STATE.initial_result, {{
      points: defaults.points || 10,
      top_n: defaults.top_n || 5,
      seed: defaults.seed || 42,
      risk_analysis: !!defaults.risk_analysis
    }});
    document.getElementById('results-empty').style.display = 'none';
    document.getElementById('results-content').style.display = 'flex';
  }}
  initResultsTableSorting();
}})();
</script>
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

