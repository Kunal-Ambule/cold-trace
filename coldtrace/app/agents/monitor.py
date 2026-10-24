"""Monitoring agent: detect -> assess -> option-generation -> decision -> explain -> propose (human approves)."""
from __future__ import annotations

import logging

from .. import db
from ..services import bus, ingest, twin
from ..services.weather import lane_stations
from ..services.weather import store as weather_store
from ..domain.lanes import LANE_BY_ID
from . import tools
from .orchestrator import Run

log = logging.getLogger("coldtrace.monitor")

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["headline", "rationale", "driver_instruction"],
          "properties": {"headline": {"type": "string", "maxLength": 110},
                         "rationale": {"type": "string", "maxLength": 420},
                         "driver_instruction": {"type": "string", "maxLength": 220}}}

SYSTEM = ("You are the monitoring agent of a cold-chain control room. A deterministic engine has already chosen the action. "
          "Explain it to the dispatcher in plain language. Use ONLY numbers that appear in FACTS; never calculate, estimate or invent "
          "facilities, prices or times. Keep the driver instruction to one short imperative sentence.")


def _decide(snap: dict, est: dict) -> dict:
    value = snap["shipment"]["declared_value_inr"]
    cont = est["continue"]
    best = min(est["diversions"], key=lambda d: d["total_cost_inr"], default=None)
    at_risk = snap["assessment"]["risk_level"] != "low" or (snap["forecast"] or {}).get("breach_predicted") or \
        snap["now"]["temp_c"] > snap["band"]["t_max"] or snap["now"]["temp_c"] < snap["band"]["t_min"]
    if best and at_risk:
        saving = cont["total_cost_inr"] - best["total_cost_inr"]
        if saving >= max(5000.0, 0.01 * value):
            return {"kind": "divert", "hub": best["hub"], "expected_loss_continue_inr": cont["expected_loss_inr"],
                    "expected_loss_divert_inr": best["expected_loss_inr"], "extra_cost_inr": best["extra_cost_inr"],
                    "net_saving_inr": round(saving, 0), "eta_min": best["hub"]["eta_min"]}
    gap = max(snap["now"]["temp_c"] - snap["band"]["t_max"], snap["band"]["t_min"] - snap["now"]["temp_c"])
    severe_gap = gap >= max(3.0, 0.5 * (snap["band"]["t_max"] - snap["band"]["t_min"]))
    high_value_risk = snap["assessment"]["risk_level"] in ("high", "critical") and cont["expected_loss_inr"] >= 0.01 * value
    if at_risk and (severe_gap or (best is None and high_value_risk)):
        return {"kind": "escalate", "expected_loss_continue_inr": cont["expected_loss_inr"], "net_saving_inr": 0.0}
    return {"kind": "continue", "expected_loss_continue_inr": cont["expected_loss_inr"], "net_saving_inr": 0.0}


def _fallback(snap: dict, dec: dict) -> dict:
    n, b = snap["now"], snap["band"]
    if dec["kind"] == "divert":
        h = dec["hub"]
        return {"headline": f"Divert {snap['shipment']['code']} to {h['name']} cold store",
                "rationale": (f"Temperature is {n['temp_c']:.1f} C against a {b['t_min']:g}-{b['t_max']:g} C band. "
                              f"Continuing risks about INR {dec['expected_loss_continue_inr']:,.0f}; diverting to {h['name']} "
                              f"({h['drive_km']:g} km, about {h['eta_min']:.0f} min) limits loss to INR {dec['expected_loss_divert_inr']:,.0f} "
                              f"plus INR {dec['extra_cost_inr']:,.0f} extra cost, a net saving of INR {dec['net_saving_inr']:,.0f}."),
                "driver_instruction": f"Proceed to {h['name']} cold store now and keep the reefer running."}
    if dec["kind"] == "escalate":
        return {"headline": f"Reefer fault suspected on {snap['shipment']['code']}: send roadside service",
                "rationale": f"Temperature is {n['temp_c']:.1f} C, well above the {b['t_max']:g} C limit, and no cold-store hub is reachable ahead of the truck.",
                "driver_instruction": "Pull over safely and call the dispatcher."}
    return {"headline": f"{snap['shipment']['code']}: keep going, monitor closely",
            "rationale": f"Temperature is {n['temp_c']:.1f} C (band {b['t_min']:g}-{b['t_max']:g} C). Diversion would cost more than it saves.",
            "driver_instruction": "Continue to destination and check the reefer display at the next stop."}


def run(shipment_id: int, reason: str) -> int | None:
    run_ = Run("monitor", shipment_id=shipment_id)
    try:
        snap = run_.tool(tools.registry, "shipment_snapshot", shipment_id=shipment_id)
        est = run_.tool(tools.registry, "estimate_outcomes", shipment_id=shipment_id)
        dec = run_.rule("decide", lambda: _decide(snap, est), note="min(expected loss + extra cost) with a saving threshold")
        facts = {"trigger": reason, "shipment": snap["shipment"], "band": snap["band"], "now": snap["now"], "forecast": snap["forecast"],
                 "decision": dec, "options": est}
        text = run_.llm_step("explain_decision", SYSTEM, facts, "Write headline, rationale, driver_instruction.", SCHEMA,
                             lambda: _fallback(snap, dec), text_fields=("headline", "rationale", "driver_instruction"))
        proposal = dict(dec, at_ts=snap["now"]["ts"], trigger=reason, explanation={k: text[k] for k in ("headline", "rationale", "driver_instruction")},
                        explained_by=text["_generated_by"], assumptions=est["assumptions"], alternatives=est["diversions"])
        status = "proposed" if dec["kind"] in ("divert", "escalate") else "auto_logged"
        aid = db.run("INSERT INTO actions(shipment_id,run_id,kind,proposal_json,status,created_at) VALUES(?,?,?,?,?,?)",
                     (shipment_id, run_.id, dec["kind"], db.jdump(proposal), status, ingest.now_iso()))
        bus.publish("action", {"id": aid, "shipment_id": shipment_id, "kind": dec["kind"], "status": status, "proposal": proposal})
        run_.finish("done", {"action_id": aid, "kind": dec["kind"]})
        return aid
    except Exception as e:  # noqa: BLE001
        log.exception("monitor run failed")
        run_.finish("failed", {"error": str(e)})
        return None


def decide_action(action_id: int, approve: bool, user: str, note: str | None = None) -> dict:
    a = db.one("SELECT * FROM actions WHERE id=?", (action_id,))
    if not a or a["status"] != "proposed":
        raise ValueError("action is not awaiting a decision")
    p = db.jload(a["proposal_json"], {})
    sid = a["shipment_id"]
    new_status = "approved" if approve else "rejected"
    db.run("UPDATE actions SET status=?, decided_by=?, decided_at=?, decision_note=? WHERE id=?", (new_status, user, ingest.now_iso(), note, action_id))
    ship = db.one("SELECT * FROM shipments WHERE id=?", (sid,))
    cur = db.one("SELECT ts FROM readings WHERE shipment_id=? ORDER BY seq DESC LIMIT 1", (sid,))
    ts = cur["ts"] if cur else ingest.now_iso()
    if approve and a["kind"] == "divert":
        hub = p["hub"]
        ingest.add_event(sid, ts, "dispatcher", "diversion_approved", f"{user} approved diversion to {hub['name']}. {p['explanation']['driver_instruction']}",
                         actor=user, source="manual")
        plan = db.jload(ship["plan_json"]) if ship["plan_json"] else None
        if plan and ship["cursor"] > 0:
            lane = LANE_BY_ID[ship["lane_id"]]
            newplan = twin.divert_plan(plan, ship["cursor"], hub["name"], hub["lat"], hub["lon"], lane_stations(lane), weather_store)
            db.run("UPDATE shipments SET plan_json=? WHERE id=?", (db.jdump(newplan), sid))
    else:
        ingest.add_event(sid, ts, "dispatcher", f"action_{new_status}", f"{user} {new_status} agent proposal '{a['kind']}'.", actor=user, source="manual")
    bus.publish("action", {"id": action_id, "shipment_id": sid, "kind": a["kind"], "status": new_status, "proposal": p})
    return {"id": action_id, "status": new_status}
