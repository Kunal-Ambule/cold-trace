# ColdTrace — AI-Powered Autonomous Cold-Chain & Agri-Perishable Logistics

Built for **Fireblaze Tech League 5.0 — Cold-Chain Intelligence 2026**.

> Over 30% of India's perishable produce spoils before reaching the market — not because the food is bad,
> but because the cold chain breaks silently: fragmented logistics, unverifiable transit logs, and reefer
> failures nobody catches until it's too late. ColdTrace is a working, end-to-end platform for the three
> hackathon tracks (ML & anomaly detection, GenAI/LLM agents & disputes, full stack) built on **real** Indian
> agricultural market data and **real** weather, with an autonomous monitoring agent and a multi-agent
> dispute-resolution pipeline.

![Python](https://img.shields.io/badge/python-3.12-blue) ![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688) ![SQLite](https://img.shields.io/badge/SQLite-WAL-003B57) ![Tests](https://img.shields.io/badge/tests-25%20passing-brightgreen)

---

## Why this is not a "demo with fake data"

Every number in ColdTrace either comes from a real, cited source, or is computed deterministically from one.
Nothing is `random.uniform()`-flavored noise dressed up to look plausible.

| Data | Source | Where |
|---|---|---|
| Commodity prices | **Agmarknet** (Govt. of India, Ministry of Agriculture) mandi price listings, via data.gov.in | `data/agmarknet_cleaned.csv` (9,600+ real listings, 176 commodities, 23 states) |
| Weather | **ERA5 reanalysis** (real historical hourly temperature, humidity, solar radiation), via the free [Open-Meteo](https://open-meteo.com) archive API | fetched live by `scripts/fetch_data.py --weather` |
| Freight lanes | Real markets that appear in the Agmarknet data, real cities, real approximate coordinates | `app/domain/lanes.py` |
| Road routing | **OSRM** (public demo router) for real road geometry and distance/duration, with a documented waypoint-polyline fallback if OSRM is unreachable | `app/services/routing.py` |
| Sensor telemetry | **Not** hand-rolled random noise. A physical two-node reefer thermal model (heat balance between air, cargo and sun-loaded ambient, with a proportional-control compressor) is *driven by the real ERA5 weather above*. Fault scenarios (compressor degradation, door left open, poor pre-cooling, receiver dock delay) perturb the physics, not the output. | `app/services/twin.py` |
| Commodity storage bands | Public post-harvest handling guidance (indicative; the code comments flag this and invite you to swap in your agronomist's numbers) | `app/domain/commodities.py` |

This matters because it means the ML model card, the alert lead-times, and the liability amounts in this
README are all things you can reproduce and interrogate — not made-up hackathon-slide numbers.

---

## What it does

### 1. Real-time monitoring & ML (Data Science / ML track)
- A **thermal digital twin** replays real weather along nine real India freight lanes to generate temperature,
  humidity, door, and GPS telemetry — the same ingestion path a real IoT sensor would use.
- **Rule-based detection**: out-of-band temperature, door-open-in-transit, implausible GPS jumps (spoofing /
  corrupted logs), connectivity gaps.
- **ML detection**: a `HistGradientBoostingRegressor` forecasts the temperature 60 minutes ahead (with an
  honest chronological train/test split and a persistence-baseline comparison), and an `IsolationForest`
  (trained only on healthy trips) flags anomalous behavior. Both are documented in an auto-generated
  **model card** (`models/model_card.json`) with real precision/recall/lead-time numbers, not vibes.

### 2. Autonomous agents (GenAI / LLM agents track)
- **Monitoring agent** (`app/agents/monitor.py`): detect → estimate the cost of continuing vs. diverting to
  a real cold-storage hub → decide (deterministic cost minimization) → explain in plain language (local LLM
  via **Ollama**, with a grounding check that rejects any sentence containing a number not present in the
  underlying facts, falling back to a template) → propose the action for a human dispatcher to approve.
  Every step is logged and streamed live to the dashboard.
- **Dispute pipeline** (`app/agents/dispute.py`): five auditable stages — Evidence Collector → Timeline
  Reconstructor → SLA Analyst (BM25 full-text search over the contract) → Liability Apportioner
  (deterministic counterfactual thermal-model replay, see below) → Report Writer, with a Verifier baked
  into every narration step. **The LLM never computes a number** — it explains numbers the code already
  computed, and any ungrounded number gets stripped and replaced by a template sentence.
- **Tamper-evident ledger** (`app/services/ledger.py`): readings are hash-chained in sealed blocks of 6.
  Any edit, deletion, or insertion after sealing is detected down to the exact sequence number — this is
  the direct answer to the brief's "false transit logs."

### 3. Full stack
- FastAPI backend, SQLite (WAL mode), JWT auth with roles (dispatcher / driver / auditor / admin).
- Dispatcher **control-room dashboard**: live map, temperature-vs-band chart, alerts, pending-decision
  cards, agent-run trace viewer, tamper-evident ledger viewer, liability breakdown, real Agmarknet price
  explorer — plain HTML/CSS/JS, no build step, no framework, Server-Sent Events for live push.
- **Offline-first driver PWA** (`web/driver/`): big-button check-ins (loading, departed, door events,
  arrived, unloading) plus a voice-note field, queued in IndexedDB and synced automatically when
  connectivity returns — built and tested for exactly the "low-connectivity, high-variability rural"
  condition the brief calls out.
- **Insurance-ready incident dockets**: a one-click PDF (ReportLab) with the loss assessment, ledger
  integrity status, liability apportionment, cited SLA clauses, and a full timeline.

---

## Tech stack

| Layer | Choice |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy-free (plain SQL via a thin `db.py`), Pydantic |
| Database | SQLite (WAL mode, FTS5 for SLA clause search) |
| ML | scikit-learn (HistGradientBoostingRegressor, IsolationForest) |
| Agents | Plain Python orchestrator with a typed tool registry and JSON-schema validation (`app/agents/orchestrator.py`) — deliberately not a heavyweight framework, so every step is inspectable in one file |
| LLM | **Ollama** (local, free, offline-capable) — `llama3.2:3b` by default; the whole platform works with zero LLM (deterministic templates) if Ollama isn't running |
| Frontend | HTML5, CSS3 (custom design system, no Tailwind/Bootstrap), vanilla ES modules, Leaflet (maps), Chart.js (telemetry) — all vendored locally, no CDN dependency at runtime |
| PDF | ReportLab |
| Auth | PyJWT, PBKDF2-SHA256 password hashing |

---

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 1. Load real data (needs internet the first time)
python scripts/fetch_data.py --all

# 2. (Optional but recommended) train the ML models on the real-weather corpus
python scripts/train.py

# 3. (Optional) run a local LLM for agent narration - the app works fine without this
ollama pull llama3.2:3b
ollama serve

# 4. Run
python run.py --reload
# open http://127.0.0.1:8000
```

Demo accounts (password `coldtrace` for all): `dispatcher`, `driver`, `auditor`, `admin`.
The driver PWA is at `/driver/` — open it on a phone (or Chrome DevTools device mode) to see the
offline-first check-in flow.

### Opening this in Antigravity
This is a plain Python + static-HTML project with no build step. Open the `coldtrace/` folder directly;
`app/main.py` is the FastAPI entry point and `run.py` is the launch script. `.agent/rules/coldtrace.md`
documents the project's non-negotiable design invariants (no synthetic data, LLM never computes numbers,
every agent step is audited, single ingestion path, append-only ledger) for any agent working in this repo.

### Docker
```bash
docker compose up --build
docker compose exec app python scripts/fetch_data.py --all
docker compose exec ollama ollama pull llama3.2:3b
```

### Running the test suite
```bash
pytest -q       # 25 tests, runs in under a second (no network - uses a test-only synthetic weather fixture,
                # clearly separated from the real data path; see tests/weather_fixture.py)
```

---

## A worked example

1. `POST /api/shipments` with lane `Bhusaval → Pune (Pimpri)`, commodity `banana`, scenario
   `compressor_degradation`. The banana's real Agmarknet price at Bhusaval APMC sets the declared cargo
   value automatically.
2. The twin replays real August weather along the route. As the simulated compressor loses capacity, the
   rule engine raises an `out_of_band` alert, and the monitoring agent runs: it pulls the shipment snapshot,
   estimates the cost of continuing vs. diverting to the nearest real cold-storage hub, and — because in
   this case no hub is reachable in time and the loss is significant — proposes **escalate to roadside
   service**, with a plain-language explanation grounded in the actual temperature and cost figures.
3. A wholesale buyer, unhappy with the delivered cargo, files a dispute. The pipeline reconstructs the
   timeline, retrieves SLA clauses 3.1 ("reefer unit maintenance") via full-text search, and the liability
   engine replays the trip under three counterfactuals (compliant load, healthy reefer, no rogue door
   events) to isolate exactly how much loss is attributable to the carrier's equipment versus the
   environment — then generates a cited, numbered incident docket as a PDF in one click.

---

## Design notes & honest limitations

- **The ML model card tells you what it actually measured**, not a marketing number: it's trained and
  evaluated on model-derived telemetry (real weather, simulated reefer physics), so its precision/recall
  figures demonstrate the *pipeline* — swap in real device readings (`source='device'`) and re-run
  `scripts/train.py` to get a model card that reflects your real fleet.
- **The LLM is optional and never authoritative.** Every number a person can act on (money, percentages,
  temperatures) is computed by deterministic Python and checked against the LLM's prose before display.
  Turn Ollama off entirely and the platform is fully functional with template-based explanations.
- **Commodity temperature bands are indicative**, compiled from public post-harvest guidance — replace them
  with your own agronomist-verified figures in `app/domain/commodities.py` before using this for real
  procurement decisions.
- **OSRM's public demo server** is used for routing; it's rate-limited and not meant for production traffic.
  Self-host OSRM or swap in a commercial routing API for real deployment (one function to change:
  `app/services/routing.py::_osrm`).

## Project layout
```
app/
  domain/       commodities, lanes, SLA template — static reference data
  services/     geo, routing, weather, thermal twin, spoilage math, ledger, ingest, alerts, attribution, PDF
  ml/           features, corpus building, training + model card, live inference
  agents/       orchestrator runtime, tool registry, monitoring agent, dispute pipeline, Ollama client
  api/          FastAPI routers (thin - logic lives in services/agents)
web/
  index.html, css/, js/     dispatcher control-room dashboard (no build step)
  driver/                   offline-first driver PWA
scripts/        fetch_data.py, train.py, seed_demo.py
tests/          pytest suite (25 tests) + a test-only synthetic weather fixture
```
