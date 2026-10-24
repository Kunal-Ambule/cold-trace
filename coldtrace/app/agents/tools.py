"""Tools available to agents. Each is a plain function with a JSON schema; results are plain JSON."""
from __future__ import annotations

from .. import db
from ..domain.commodities import get as get_com
from ..domain.lanes import LANE_BY_ID
from ..ml.inference import models
from ..services import alerts as alert_svc
from ..services import attribution, ledger, spoilage
from ..services.geo import haversine_km, nearest_index
from .orchestrator import Registry

registry = Registry()
_SHIP = {"type": "object", "properties": {"shipment_id": {"type": "integer"}}, "required": ["shipment_id"], "additionalProperties": False}

TRUCK_KMH = 42.0
FREIGHT_INR_PER_KM = 30.0       # editable assumption: reefer freight cost per extra km
DELAY_INR_PER_H = 600.0         # editable assumption: cost of each hour of delay


@registry.register("shipment_snapshot", "Current position, temperature, band, forecast, exposure and route progress of a shipment.", _SHIP)
def shipment_snapshot(shipment_id: int) -> dict:
    ship = db.one("SELECT * FROM shipments WHERE id=?", (shipment_id,))
    com = get_com(ship["commodity_code"])
    lane = LANE_BY_ID[ship["lane_id"]]
    rows = db.all_("SELECT * FROM readings WHERE shipment_id=? ORDER BY seq", (shipment_id,))
    lane_row = db.one("SELECT route_json,duration_min FROM lanes WHERE id=?", (ship["lane_id"],))
    route = db.jload(lane_row["route_json"])
    cur = rows[-1]
    idx = nearest_index(route["points"], cur["lat"], cur["lon"])
    km_done, km_total = route["cum"][idx], route["cum"][-1]
    a = spoilage.assess(com, rows, ship["declared_value_inr"])
    slope_h = ((rows[-1]["temp_c"] - rows[-4]["temp_c"]) / 3.0 * 6.0) if len(rows) >= 4 else 0.0     # deg C per hour
    return {
        "shipment": {"id": shipment_id, "code": ship["code"], "commodity": com.name, "lane": lane.name, "qty_kg": ship["qty_kg"],
                     "declared_value_inr": ship["declared_value_inr"], "carrier": ship["carrier"], "scenario_label": None},
        "band": {"t_min": com.t_min, "t_max": com.t_max, "setpoint_c": ship["setpoint_c"]},
        "now": {"ts": cur["ts"], "temp_c": cur["temp_c"], "lat": cur["lat"], "lon": cur["lon"], "phase": cur["phase"],
                "ambient_c": cur["ambient_c"], "trend_c_per_h": round(slope_h, 2)},
        "assessment": a,
        "forecast": models.forecast(rows, com),
        "route": {"km_done": round(km_done, 1), "km_total": round(km_total, 1), "km_remaining": round(km_total - km_done, 1),
                  "eta_min_remaining": round((km_total - km_done) / max(km_total, 1e-6) * lane_row["duration_min"], 0),
                  "dest": {"name": lane.dest.name, "lat": lane.dest.lat, "lon": lane.dest.lon}},
    }


@registry.register("diversion_options", "Candidate cold-storage hubs ahead of the truck, with drive distance and time.", _SHIP)
def diversion_options(shipment_id: int) -> list[dict]:
    snap = shipment_snapshot(shipment_id)
    ship = db.one("SELECT lane_id FROM shipments WHERE id=?", (shipment_id,))
    route = db.jload(db.one("SELECT route_json FROM lanes WHERE id=?", (ship["lane_id"],))["route_json"])
    now, dest = snap["now"], snap["route"]["dest"]
    km_done, km_rem = snap["route"]["km_done"], snap["route"]["km_remaining"]
    out = []
    for h in db.all_("SELECT * FROM hubs"):
        i = nearest_index(route["points"], h["lat"], h["lon"])
        off_route = haversine_km(h["lat"], h["lon"], route["points"][i][0], route["points"][i][1])
        if off_route > 30 or route["cum"][i] < km_done - 2:
            continue
        drive_km = haversine_km(now["lat"], now["lon"], h["lat"], h["lon"]) * 1.25
        to_dest = haversine_km(h["lat"], h["lon"], dest["lat"], dest["lon"]) * 1.25
        if drive_km < 3 or haversine_km(h["lat"], h["lon"], dest["lat"], dest["lon"]) < 8 or drive_km > km_rem:
            continue
        out.append({"name": h["name"], "lat": h["lat"], "lon": h["lon"], "verified": bool(h["verified"]),
                    "drive_km": round(drive_km, 1), "eta_min": round(drive_km / TRUCK_KMH * 60, 0),
                    "hub_to_destination_km": round(to_dest, 1), "extra_km": round(max(0.0, drive_km + to_dest - km_rem), 1)})
    return sorted(out, key=lambda o: o["eta_min"])[:4]


@registry.register("estimate_outcomes", "Expected loss if the truck continues versus diverting to each hub.",
                   {"type": "object", "properties": {"shipment_id": {"type": "integer"}}, "required": ["shipment_id"], "additionalProperties": False})
def estimate_outcomes(shipment_id: int) -> dict:
    snap = shipment_snapshot(shipment_id)
    opts = diversion_options(shipment_id)
    com = get_com(db.one("SELECT commodity_code c FROM shipments WHERE id=?", (shipment_id,))["c"])
    value = snap["shipment"]["declared_value_inr"]
    now, fc = snap["now"], snap["forecast"]

    def proj_temp(hours: float) -> float:
        p = now["temp_c"] + max(0.0, now["trend_c_per_h"]) * min(hours, 3.0)
        if fc:
            p = max(p, fc["pred_max_c"])
        return min(p, max(now["ambient_c"] or p, now["temp_c"]))

    def loss(hours: float) -> float:
        return min(value, spoilage.interval_burn(com, proj_temp(hours), hours) * value)

    hrs_left = snap["route"]["eta_min_remaining"] / 60.0 + 0.75
    cont = {"option": "continue", "expected_loss_inr": round(loss(hrs_left), 0), "extra_cost_inr": 0.0,
            "total_cost_inr": round(loss(hrs_left), 0), "hours": round(hrs_left, 2)}
    div = []
    for o in opts:
        h = o["eta_min"] / 60.0
        extra = o["extra_km"] * FREIGHT_INR_PER_KM + max(0.0, (o["eta_min"] + 60 + o["hub_to_destination_km"] / TRUCK_KMH * 60 - snap["route"]["eta_min_remaining"]) / 60.0) * DELAY_INR_PER_H
        lo = loss(h)
        div.append({"option": f"divert:{o['name']}", "hub": o, "expected_loss_inr": round(lo, 0), "extra_cost_inr": round(extra, 0),
                    "total_cost_inr": round(lo + extra, 0), "hours": round(h, 2)})
    return {"continue": cont, "diversions": div,
            "assumptions": [f"Freight INR {FREIGHT_INR_PER_KM:g}/km for extra distance", f"Delay cost INR {DELAY_INR_PER_H:g}/hour",
                            "Loss = shelf-life burn at the projected temperature (current trend or forecast, whichever is higher)"]}


@registry.register("collect_evidence", "All recorded evidence for a shipment: readings, ledger status, custody events, alerts, agent actions.", _SHIP)
def collect_evidence(shipment_id: int) -> dict:
    v = ledger.verify(shipment_id)
    return {
        "ledger": {"ok": v["ok"], "blocks": v["n_blocks"], "pending_readings": v["pending_readings"], "head_hash": v["head_hash"],
                   "tampered_seqs": v["tampered_seqs"], "first_broken_height": v["first_broken_height"]},
        "readings": db.one("SELECT COUNT(*) n, MIN(ts) first_ts, MAX(ts) last_ts, SUM(source='device') device, SUM(source='twin') model FROM readings WHERE shipment_id=?", (shipment_id,)),
        "events": db.all_("SELECT id,ts,party,actor,event,note,transcript,source FROM custody_events WHERE shipment_id=? ORDER BY ts", (shipment_id,)),
        "alerts": db.all_("SELECT id,ts,kind,severity,message FROM alerts WHERE shipment_id=? ORDER BY ts", (shipment_id,)),
        "actions": db.all_("SELECT id,kind,status,created_at,decided_by,decided_at FROM actions WHERE shipment_id=? ORDER BY id", (shipment_id,)),
    }


@registry.register("build_timeline", "Chronological, evidence-linked timeline of what happened.", _SHIP)
def build_timeline(shipment_id: int) -> list[dict]:
    ship = db.one("SELECT * FROM shipments WHERE id=?", (shipment_id,))
    com = get_com(ship["commodity_code"])
    items: list[dict] = []
    for e in db.all_("SELECT * FROM custody_events WHERE shipment_id=?", (shipment_id,)):
        items.append({"ts": e["ts"], "kind": "custody", "label": f"[{e['party']}] {e['event'].replace('_', ' ')}: {e['note'] or ''}".strip(), "ref": {"event_id": e["id"]}})
    rows = db.all_("SELECT seq,ts,temp_c,phase FROM readings WHERE shipment_id=? ORDER BY seq", (shipment_id,))
    first_out = next((r for r in rows if r["temp_c"] > com.t_max or r["temp_c"] < com.t_min), None)
    if first_out:
        items.append({"ts": first_out["ts"], "kind": "breach", "label": f"First reading outside {com.t_min:g}-{com.t_max:g} C: {first_out['temp_c']:.1f} C ({first_out['phase']}).", "ref": {"seq": first_out["seq"]}})
        peak = max(rows, key=lambda r: r["temp_c"])
        items.append({"ts": peak["ts"], "kind": "peak", "label": f"Peak temperature {peak['temp_c']:.1f} C.", "ref": {"seq": peak["seq"]}})
        rec = next((r for r in rows if r["seq"] > first_out["seq"] and com.t_min <= r["temp_c"] <= com.t_max), None)
        if rec:
            items.append({"ts": rec["ts"], "kind": "recovery", "label": f"Temperature back inside band ({rec['temp_c']:.1f} C).", "ref": {"seq": rec["seq"]}})
    seen = set()
    for a in db.all_("SELECT * FROM alerts WHERE shipment_id=? ORDER BY ts", (shipment_id,)):
        if a["kind"] in seen:
            continue
        seen.add(a["kind"])
        items.append({"ts": a["ts"], "kind": "alert", "label": f"Alert ({a['severity']}): {a['message']}", "ref": {"alert_id": a["id"]}})
    for ac in db.all_("SELECT * FROM actions WHERE shipment_id=? ORDER BY id", (shipment_id,)):
        p = db.jload(ac["proposal_json"], {})
        items.append({"ts": p.get("at_ts") or (rows[-1]["ts"] if rows else ac["created_at"]),
                      "kind": "agent", "label": f"Agent proposed {ac['kind']} ({ac['status']}).", "ref": {"action_id": ac["id"]}})
    return sorted(items, key=lambda i: i["ts"])


_CAUSE_QUERY = {
    "environment": "environmental force majeure ambient", "shipper": "pre-cooling shipper loading",
    "carrier_door": "door open transit inspection", "carrier_reefer": "refrigeration unit maintenance",
    "receiver_dwell": "receiver dock dwell unloading",
}


@registry.register("retrieve_clauses", "Full-text search (BM25) over the contract's SLA clauses.",
                   {"type": "object", "properties": {"query": {"type": "string"}, "k": {"type": "integer", "minimum": 1, "maximum": 8}},
                    "required": ["query"], "additionalProperties": False})
def retrieve_clauses(query: str, k: int = 3) -> list[dict]:
    terms = " OR ".join(t for t in "".join(ch if ch.isalnum() else " " for ch in query).split() if len(t) > 2)
    if not terms:
        return []
    return db.all_("SELECT c.clause_no, c.title, c.body FROM sla_fts f JOIN sla_clauses c ON c.id=f.rowid "
                   "WHERE sla_fts MATCH ? ORDER BY bm25(sla_fts) LIMIT ?", (terms, k))


@registry.register("apportion_liability", "Deterministic liability apportionment from verified readings (counterfactual replay).", _SHIP)
def apportion_liability(shipment_id: int) -> dict:
    return attribution.apportion(shipment_id)


def cause_query(cause: str) -> str:
    return _CAUSE_QUERY[cause]
