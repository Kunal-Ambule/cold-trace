"""Detection layer: rules + ML on every new reading. Opens/closes alerts and kicks the monitoring agent."""
from __future__ import annotations

import logging
import threading

from .. import db
from ..domain.commodities import get as get_com
from ..ml.inference import models
from . import bus, spoilage
from .geo import haversine_km
from .weather import to_epoch

log = logging.getLogger("coldtrace.alerts")
_agent_lock = threading.Lock()
_agent_running: set[int] = set()


_SEV_RANK = {"info": 0, "warning": 1, "critical": 2}
REEVAL_EVERY_READINGS = 6      # while an alert stays open, re-run the monitor agent this often (worsening conditions)


def _open(shipment_id: int, kind: str) -> dict | None:
    return db.one("SELECT * FROM alerts WHERE shipment_id=? AND kind=? AND status='open' ORDER BY id DESC LIMIT 1", (shipment_id, kind))


def raise_alert(shipment_id: int, ts: str, kind: str, severity: str, message: str, data: dict | None = None) -> dict | None:
    """Returns the alert (and triggers the monitor) on first raise OR when severity escalates while still open."""
    existing = _open(shipment_id, kind)
    if existing:
        if _SEV_RANK.get(severity, 0) > _SEV_RANK.get(existing["severity"], 0):
            db.run("UPDATE alerts SET severity=?, message=?, data_json=? WHERE id=?", (severity, message, db.jdump(data or {}), existing["id"]))
            alert = dict(existing, severity=severity, message=message, data=data or {})
            bus.publish("alert", alert)
            return alert
        n = db.one("SELECT COUNT(*) c FROM readings WHERE shipment_id=? AND ts>=?", (shipment_id, existing["ts"]))["c"]
        if n and n % REEVAL_EVERY_READINGS == 0:
            return dict(existing, message=message, data=data or {})
        return None
    aid = db.run("INSERT INTO alerts(shipment_id,ts,kind,severity,message,data_json) VALUES(?,?,?,?,?,?)",
                 (shipment_id, ts, kind, severity, message, db.jdump(data or {})))
    alert = {"id": aid, "shipment_id": shipment_id, "ts": ts, "kind": kind, "severity": severity, "message": message,
             "data": data or {}, "status": "open"}
    bus.publish("alert", alert)
    return alert


def resolve(shipment_id: int, kind: str) -> None:
    a = _open(shipment_id, kind)
    if a:
        db.run("UPDATE alerts SET status='resolved' WHERE id=?", (a["id"],))
        bus.publish("alert_resolved", {"id": a["id"], "shipment_id": shipment_id, "kind": kind})


def evaluate(shipment_id: int) -> list[dict]:
    ship = db.one("SELECT * FROM shipments WHERE id=?", (shipment_id,))
    com = get_com(ship["commodity_code"])
    rows = db.all_("SELECT * FROM readings WHERE shipment_id=? ORDER BY seq", (shipment_id,))
    if not rows:
        return []
    cur, new = rows[-1], []
    temp = cur["temp_c"]
    ts = cur["ts"]

    # 1. Out-of-band (rule). Resolve after two consecutive in-band readings.
    if temp > com.t_max or temp < com.t_min:
        side = "above" if temp > com.t_max else "below"
        gap = temp - com.t_max if temp > com.t_max else com.t_min - temp
        sev = "critical" if gap >= 3 or com.mode == "budget" else "warning"
        a = raise_alert(shipment_id, ts, "out_of_band", sev,
                        f"Cargo temperature {temp:.1f} C is {gap:.1f} C {side} the {com.t_min:g}-{com.t_max:g} C band.",
                        {"temp_c": temp, "t_min": com.t_min, "t_max": com.t_max, "phase": cur["phase"]})
        if a:
            new.append(a)
            _maybe_run_monitor(shipment_id, "out_of_band")
    elif len(rows) >= 2 and com.t_min <= rows[-2]["temp_c"] <= com.t_max:
        resolve(shipment_id, "out_of_band")

    # 2. ML: predicted breach in the next hour (only while still in band, only in transit)
    fc = models.forecast(rows, com)
    if fc and fc["breach_predicted"] and com.t_min <= temp <= com.t_max and cur["phase"] == "transit":
        a = raise_alert(shipment_id, ts, "breach_forecast", "warning",
                        f"Forecast: {fc['pred_max_c']:.1f} C within {fc['horizon_min']} min (limit {com.t_max:g} C)."
                        + (f" Estimated breach in about {int(fc['eta_to_breach_min'])} min." if fc["eta_to_breach_min"] is not None else ""),
                        fc)
        if a:
            new.append(a)
            _maybe_run_monitor(shipment_id, "breach_forecast")
    elif fc and not fc["breach_predicted"]:
        resolve(shipment_id, "breach_forecast")

    # 3. ML: unsupervised anomaly (3 consecutive flags)
    an = models.anomaly(rows, com)
    if an and an["recent_flags"] >= 3:
        a = raise_alert(shipment_id, ts, "anomaly", "warning",
                        "Temperature behaviour deviates from healthy reefer trips (anomaly detector).", an)
        if a:
            new.append(a)
    elif an and an["recent_flags"] == 0:
        resolve(shipment_id, "anomaly")

    # 4. Door open in transit
    if len(rows) >= 2 and cur["phase"] == "transit" and cur["door_open"] and rows[-2]["door_open"]:
        a = raise_alert(shipment_id, ts, "door_open_transit", "warning", "Door has been open for 20+ minutes while in transit.", {})
        if a:
            new.append(a)
    elif not cur["door_open"]:
        resolve(shipment_id, "door_open_transit")

    # 5. Log integrity: impossible movement between consecutive GPS fixes
    if len(rows) >= 2 and rows[-2]["lat"] is not None and cur["lat"] is not None:
        dt_h = max((to_epoch(cur["ts"]) - to_epoch(rows[-2]["ts"])) / 3600.0, 1e-6)
        speed = haversine_km(rows[-2]["lat"], rows[-2]["lon"], cur["lat"], cur["lon"]) / dt_h
        if speed > 130:
            a = raise_alert(shipment_id, ts, "gps_implausible", "critical",
                            f"GPS jump implies {speed:.0f} km/h: possible spoofed or corrupted location log.", {"speed_kmh": round(speed)})
            if a:
                new.append(a)
        gap_min = (to_epoch(cur["ts"]) - to_epoch(rows[-2]["ts"])) / 60.0
        if gap_min > 30 and cur["source"] == "device":
            a = raise_alert(shipment_id, ts, "data_gap", "info", f"No readings for {gap_min:.0f} minutes (connectivity gap).", {"gap_min": round(gap_min)})
            if a:
                new.append(a)
    return new


def _maybe_run_monitor(shipment_id: int, reason: str) -> None:
    from ..agents import monitor        # local import: agents depend on services

    with _agent_lock:
        if shipment_id in _agent_running:
            return
        if db.one("SELECT id FROM actions WHERE shipment_id=? AND status='proposed'", (shipment_id,)):
            return
        _agent_running.add(shipment_id)

    def _job() -> None:
        try:
            monitor.run(shipment_id, reason)
        except Exception:  # noqa: BLE001
            log.exception("monitor agent failed")
        finally:
            with _agent_lock:
                _agent_running.discard(shipment_id)

    threading.Thread(target=_job, name=f"monitor-{shipment_id}", daemon=True).start()


def summarize(shipment_id: int) -> dict:
    ship = db.one("SELECT * FROM shipments WHERE id=?", (shipment_id,))
    com = get_com(ship["commodity_code"])
    rows = db.all_("SELECT ts,temp_c FROM readings WHERE shipment_id=? ORDER BY seq", (shipment_id,))
    return spoilage.assess(com, rows, ship["declared_value_inr"])
