"""Shipment lifecycle: creation (with real-price valuation), replay, completion."""
from __future__ import annotations

import logging
import zlib
from datetime import datetime, timezone

from .. import db
from ..domain import commodities
from ..domain.lanes import LANE_BY_ID
from . import ingest, ledger, prices, routing, twin
from .weather import store as weather_store

log = logging.getLogger("coldtrace.shipments")

DEFAULT_QTY_KG = {"biologics": 800.0}


def _next_code(lane_id: str, depart_ts: str) -> str:
    n = db.one("SELECT COUNT(*) n FROM shipments WHERE lane_id=?", (lane_id,))["n"] + 1
    return f"CT-{lane_id}-{depart_ts[:10].replace('-', '')}-{n:02d}"


def create(lane_id: str, commodity_code: str, depart_ts: str, scenario: str = "nominal", qty_kg: float | None = None,
           declared_value_inr: float | None = None, carrier: str | None = None, data_source: str = "twin") -> dict:
    lane = LANE_BY_ID[lane_id]
    com = commodities.get(commodity_code)
    if scenario not in twin.SCENARIOS:
        raise ValueError(f"unknown scenario {scenario}")
    qty = qty_kg or DEFAULT_QTY_KG.get(commodity_code, 8000.0)
    basis = prices.lookup(commodity_code, lane.origin_market, lane.origin_state)
    if declared_value_inr is None:
        if basis is None:
            raise ValueError("declared_value_inr is required for commodities without market prices")
        declared_value_inr = round(qty / 100.0 * basis["modal_inr_per_quintal"], 2)
    elif basis is None:
        basis = {"basis": "declared by shipper"}
    route = routing.ensure_route(lane)
    plan = None
    if data_source == "twin":
        plan = twin.simulate_trip(lane, route, depart_ts, commodity_code, scenario, weather_store)
    code = _next_code(lane_id, depart_ts)
    sid = db.run(
        "INSERT INTO shipments(code,lane_id,commodity_code,variety,qty_kg,declared_value_inr,price_basis,shipper,carrier,receiver,reefer_id,"
        "setpoint_c,depart_ts,status,scenario,data_source,plan_json,cursor,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (code, lane_id, commodity_code, None, qty, declared_value_inr, db.jdump(basis), lane.shipper, carrier or lane.carrier,
         lane.receiver, f"RF-{zlib.crc32(code.encode()) % 9000 + 1000}", com.t_opt, depart_ts, "scheduled", scenario, data_source,
         db.jdump(plan) if plan else None, 0, datetime.now(timezone.utc).isoformat()))
    if data_source == "twin":
        # Seed an hour of real telemetry immediately so the dashboard isn't blank the moment a
        # shipment is created - the dispatcher can keep advancing manually (or use Play) from here.
        advance(sid, 6)
    return get(sid)


def get(shipment_id: int) -> dict | None:
    s = db.one("SELECT id,code,lane_id,commodity_code,variety,qty_kg,declared_value_inr,price_basis,shipper,carrier,receiver,reefer_id,"
               "setpoint_c,depart_ts,status,scenario,data_source,cursor,created_at, "
               "CASE WHEN plan_json IS NULL THEN 0 ELSE 1 END has_plan FROM shipments WHERE id=?", (shipment_id,))
    if s:
        s["price_basis"] = db.jload(s["price_basis"], {})
    return s


def update(shipment_id: int, qty_kg: float | None = None, declared_value_inr: float | None = None,
           carrier: str | None = None, receiver: str | None = None) -> dict:
    """Edit operational fields only (quantity, declared value, carrier, receiver) - the trip itself
    (lane/commodity/depart time/scenario) is immutable once created, same as a real waybill."""
    if not get(shipment_id):
        raise ValueError("unknown shipment")
    sets, args = [], []
    for col, val in [("qty_kg", qty_kg), ("declared_value_inr", declared_value_inr), ("carrier", carrier), ("receiver", receiver)]:
        if val is not None:
            sets.append(f"{col}=?")
            args.append(val)
    if sets:
        args.append(shipment_id)
        db.run(f"UPDATE shipments SET {', '.join(sets)} WHERE id=?", tuple(args))
    return get(shipment_id)


def delete(shipment_id: int) -> None:
    """Only allowed while nothing has been sealed into the tamper-evident ledger yet - once even one
    block is sealed, deleting the shipment would erase real evidence, so we refuse (cancel it instead
    by leaving it 'scheduled' with no further advances, or file a dispute if something went wrong)."""
    s = get(shipment_id)
    if not s:
        raise ValueError("unknown shipment")
    n_blocks = db.one("SELECT COUNT(*) n FROM ledger_blocks WHERE shipment_id=?", (shipment_id,))["n"]
    if n_blocks:
        raise ValueError("cannot delete a shipment that already has sealed ledger blocks - it's part of the audit trail")
    for table in ("readings", "custody_events", "alerts", "agent_runs", "actions", "disputes"):
        db.run(f"DELETE FROM {table} WHERE shipment_id=?", (shipment_id,))
    db.run("DELETE FROM shipments WHERE id=?", (shipment_id,))


def _plan(shipment_id: int) -> dict | None:
    r = db.one("SELECT plan_json FROM shipments WHERE id=?", (shipment_id,))
    return db.jload(r["plan_json"]) if r and r["plan_json"] else None


def advance(shipment_id: int, n: int = 1) -> dict:
    """Feed the next n frames of the shipment's plan through the normal ingestion path."""
    ship = db.one("SELECT status,cursor FROM shipments WHERE id=?", (shipment_id,))
    plan = _plan(shipment_id)
    if not plan or ship["status"] in ("completed",):
        return {"done": True, "cursor": ship["cursor"] if ship else 0}
    frames, events = plan["frames"], plan["events"]
    cur = ship["cursor"]
    chunk = frames[cur:cur + n]
    if chunk:
        ingest.ingest_readings(shipment_id, chunk, "twin")
        cur += len(chunk)
        horizon = chunk[-1]["ts"]
        for ev in events:
            if ev["ts"] <= horizon:
                ingest.add_event(shipment_id, ev["ts"], ev["party"], ev["event"], ev["note"], source="twin",
                                 idem_key=f"{shipment_id}:twin:{ev['event']}:{ev['ts']}")
    done = cur >= len(frames)
    db.run("UPDATE shipments SET cursor=?, status=? WHERE id=?", (cur, "completed" if done else "in_transit", shipment_id))
    if done:
        ledger.seal(shipment_id, force=True)
    return {"done": done, "cursor": cur, "total": len(frames)}


def fast_forward(shipment_id: int, upto_fraction: float = 1.0) -> dict:
    plan = _plan(shipment_id)
    total = len(plan["frames"])
    target = total if upto_fraction >= 1 else int(total * upto_fraction)
    cur = db.one("SELECT cursor FROM shipments WHERE id=?", (shipment_id,))["cursor"]
    res = {"cursor": cur}
    step = 12
    while cur < target:
        res = advance(shipment_id, min(step, target - cur))
        cur = res["cursor"]
        if res.get("done"):
            break
    return res


def set_status(shipment_id: int, status: str) -> None:
    db.run("UPDATE shipments SET status=? WHERE id=?", (status, shipment_id))
