PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('dispatcher','driver','auditor','admin')), display_name TEXT
);

-- REAL DATA: Agmarknet (Govt. of India) mandi price listings
CREATE TABLE IF NOT EXISTS market_prices (
  id INTEGER PRIMARY KEY, state TEXT, district TEXT, market TEXT, commodity TEXT, variety TEXT,
  grade TEXT, arrival_date TEXT, min_price REAL, max_price REAL, modal_price REAL,
  price_outlier INTEGER DEFAULT 0, unit_error INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_prices_comm ON market_prices(commodity, market);

-- REAL DATA: hourly reanalysis weather (ERA5 via Open-Meteo) at points along each lane
CREATE TABLE IF NOT EXISTS weather_stations (
  key TEXT PRIMARY KEY, name TEXT, lat REAL NOT NULL, lon REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS weather_hourly (
  station_key TEXT NOT NULL, ts TEXT NOT NULL, temp_c REAL, rh REAL, precip_mm REAL, solar_wm2 REAL,
  PRIMARY KEY (station_key, ts)
);

CREATE TABLE IF NOT EXISTS lanes (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, origin_name TEXT, dest_name TEXT,
  route_json TEXT, distance_km REAL, duration_min REAL, route_source TEXT
);

CREATE TABLE IF NOT EXISTS hubs (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, lat REAL NOT NULL, lon REAL NOT NULL, verified INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS shipments (
  id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL, lane_id TEXT NOT NULL REFERENCES lanes(id),
  commodity_code TEXT NOT NULL, variety TEXT, qty_kg REAL NOT NULL, declared_value_inr REAL NOT NULL,
  price_basis TEXT, shipper TEXT, carrier TEXT, receiver TEXT, reefer_id TEXT,
  setpoint_c REAL NOT NULL, depart_ts TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'scheduled',
  scenario TEXT NOT NULL DEFAULT 'nominal', data_source TEXT NOT NULL DEFAULT 'twin',
  plan_json TEXT, cursor INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS readings (
  id INTEGER PRIMARY KEY, shipment_id INTEGER NOT NULL REFERENCES shipments(id) ON DELETE CASCADE,
  seq INTEGER NOT NULL, ts TEXT NOT NULL, lat REAL, lon REAL, temp_c REAL NOT NULL, setpoint_c REAL,
  ambient_c REAL, solar_wm2 REAL, rh REAL, door_open INTEGER DEFAULT 0, duty REAL, phase TEXT,
  source TEXT NOT NULL, idem_key TEXT UNIQUE, block_id INTEGER,
  UNIQUE (shipment_id, seq)
);
CREATE INDEX IF NOT EXISTS ix_readings_ship ON readings(shipment_id, seq);

CREATE TABLE IF NOT EXISTS ledger_blocks (
  id INTEGER PRIMARY KEY, shipment_id INTEGER NOT NULL REFERENCES shipments(id) ON DELETE CASCADE,
  height INTEGER NOT NULL, first_seq INTEGER NOT NULL, last_seq INTEGER NOT NULL,
  prev_hash TEXT NOT NULL, payload_hash TEXT NOT NULL, block_hash TEXT NOT NULL, leaf_hashes TEXT NOT NULL, created_at TEXT NOT NULL,
  UNIQUE (shipment_id, height)
);

CREATE TABLE IF NOT EXISTS custody_events (
  id INTEGER PRIMARY KEY, shipment_id INTEGER NOT NULL REFERENCES shipments(id) ON DELETE CASCADE,
  ts TEXT NOT NULL, party TEXT NOT NULL, actor TEXT, event TEXT NOT NULL, note TEXT, transcript TEXT,
  lat REAL, lon REAL, temp_c REAL, source TEXT NOT NULL DEFAULT 'twin', idem_key TEXT UNIQUE
);
CREATE INDEX IF NOT EXISTS ix_events_ship ON custody_events(shipment_id, ts);

CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY, shipment_id INTEGER NOT NULL REFERENCES shipments(id) ON DELETE CASCADE,
  ts TEXT NOT NULL, kind TEXT NOT NULL, severity TEXT NOT NULL, message TEXT NOT NULL,
  data_json TEXT, status TEXT NOT NULL DEFAULT 'open'
);
CREATE INDEX IF NOT EXISTS ix_alerts_ship ON alerts(shipment_id, ts);

CREATE TABLE IF NOT EXISTS agent_runs (
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, shipment_id INTEGER, dispute_id INTEGER,
  started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL, llm_used INTEGER DEFAULT 0,
  steps_json TEXT, result_json TEXT
);

CREATE TABLE IF NOT EXISTS actions (
  id INTEGER PRIMARY KEY, shipment_id INTEGER NOT NULL REFERENCES shipments(id) ON DELETE CASCADE,
  run_id INTEGER, kind TEXT NOT NULL, proposal_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'proposed',
  created_at TEXT NOT NULL, decided_by TEXT, decided_at TEXT, decision_note TEXT
);

CREATE TABLE IF NOT EXISTS sla_clauses (
  id INTEGER PRIMARY KEY, contract_id TEXT NOT NULL, clause_no TEXT NOT NULL, title TEXT NOT NULL,
  body TEXT NOT NULL, param_key TEXT, param_value REAL, UNIQUE (contract_id, clause_no)
);
CREATE VIRTUAL TABLE IF NOT EXISTS sla_fts USING fts5(title, body, content='sla_clauses', content_rowid='id');

CREATE TABLE IF NOT EXISTS disputes (
  id INTEGER PRIMARY KEY, shipment_id INTEGER NOT NULL REFERENCES shipments(id) ON DELETE CASCADE,
  claimant TEXT NOT NULL, respondent TEXT, claim_amount_inr REAL, description TEXT,
  status TEXT NOT NULL DEFAULT 'open', created_by TEXT, created_at TEXT NOT NULL, report_json TEXT
);
