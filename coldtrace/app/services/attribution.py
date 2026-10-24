"""Liability apportionment by incremental counterfactual replay.  ALL arithmetic lives here, not in the LLM.

Idea: replay the trip through the thermal model under progressively "less compliant" conditions and price the
extra shelf-life burn each step adds. Stages (each keeps everything from the previous stage):

  E0  compliant everything: pre-cooled load, healthy reefer, no undocumented door events, dock handled on time
  E1  + the cargo condition / loading behaviour actually observed          -> Shipper   (SLA 2.1, 2.2)
  E2  + door-open events actually observed in transit                      -> Carrier   (SLA 3.2)
  E   the measured readings; the remainder E - E2 is what a compliant load with closed doors could not explain
      -> Carrier reefer underperformance (SLA 3.1) if before dock free time expired, else Receiver (SLA 4.1)
  E0 itself is the burn that would have occurred anyway                    -> Shared / environmental (SLA 5.1)

Per reading interval i the burn e_i is split into non-negative parts that sum to e_i. Party shares are the
summed parts; money = share x total assessed loss. Only readings in ledger-verified blocks are used (SLA 6.1).
"""
from __future__ import annotations

import dataclasses
from collections import defaultdict

from .. import db
from ..domain import sla as sla_mod
from ..domain.commodities import get as get_com
from . import ledger, spoilage, twin
from .weather import to_epoch

TOL_C = 0.1     # widen the band by 0.1 C in attribution so 0.1 C sensor rounding cannot flip a verdict


def sla_params(contract_id: str = sla_mod.CONTRACT_ID) -> dict[str, float]:
    rows = db.all_("SELECT param_key,param_value FROM sla_clauses WHERE contract_id=? AND param_key IS NOT NULL", (contract_id,))
    p = {r["param_key"]: r["param_value"] for r in rows}
    p.setdefault("dock_free_minutes", 30.0)
    p.setdefault("load_free_minutes", 45.0)
    p.setdefault("precool_tolerance_c", 1.5)
    p.setdefault("cap_fraction_of_value", 1.0)
    return p


def _ranges(seqs: list[int]) -> list[list[int]]:
    out: list[list[int]] = []
    for s in sorted(set(seqs)):
        if out and s == out[-1][1] + 1:
            out[-1][1] = s
        else:
            out.append([s, s])
    return out


def apportion(shipment_id: int, contract_id: str = sla_mod.CONTRACT_ID) -> dict:
    ship = db.one("SELECT * FROM shipments WHERE id=?", (shipment_id,))
    com = get_com(ship["commodity_code"])
    value = ship["declared_value_inr"]
    prm = sla_params(contract_id)
    vr = ledger.verify(shipment_id)
    ok_ranges = [(b["first_seq"], b["last_seq"]) for b in vr["blocks"] if b["ok"]]
    all_rows = db.all_("SELECT * FROM readings WHERE shipment_id=? ORDER BY seq", (shipment_id,))
    rows = [r for r in all_rows if any(a <= r["seq"] <= b for a, b in ok_ranges)]
    unverified = [r["seq"] for r in all_rows if r not in rows]
    events = db.all_("SELECT * FROM custody_events WHERE shipment_id=? ORDER BY ts", (shipment_id,))
    result: dict = {"shipment_id": shipment_id, "contract_id": contract_id,
                    "evidence": {"readings_total": len(all_rows), "readings_verified": len(rows),
                                 "unverified_seqs": _ranges(unverified), "ledger_ok": vr["ok"],
                                 "ledger_head": vr["head_hash"]},
                    "method": "Incremental counterfactual replay of the thermal model over the recorded weather."}
    if len(rows) < 3:
        result.update({"totals": None, "parties": {}, "findings": [], "assumptions": ["Too few verified readings to apportion."]})
        return result

    sp = ship["setpoint_c"]
    adj = dataclasses.replace(com, t_max=com.t_max + TOL_C, t_min=com.t_min - TOL_C)
    ts = [to_epoch(r["ts"]) for r in rows]
    temps = [r["temp_c"] for r in rows]
    e_act = spoilage.interval_burns(adj, ts, temps)

    ev = {e["event"]: to_epoch(e["ts"]) for e in events}
    arrived = ev.get("arrived") or next((to_epoch(r["ts"]) for r in rows if r["phase"] == "unloading"), None)
    load_start = ts[0]
    dock_free_end = (arrived + prm["dock_free_minutes"] * 60) if arrived else float("inf")
    nominal_unload = (arrived + twin.DOCK_QUEUE_NOMINAL_MIN * 60, arrived + (twin.DOCK_QUEUE_NOMINAL_MIN + twin.UNLOAD_MIN) * 60) if arrived else None

    def steps(actual_load: bool, actual_transit_doors: bool) -> list[twin.Step]:
        out = []
        for r, t in zip(rows, ts):
            ph = r["phase"] or "transit"
            if ph == "loading":
                if actual_load:
                    door = twin.DOCK_SEAL if r["door_open"] else 0.0
                else:
                    door = twin.DOCK_SEAL if (t - load_start) < prm["load_free_minutes"] * 60 else 0.0
            elif ph == "transit":
                door = twin.door_factor("transit", r["door_open"]) if actual_transit_doors else 0.0
            else:
                door = twin.DOCK_SEAL if (nominal_unload and nominal_unload[0] <= t < nominal_unload[1]) else 0.0
            amb = r["ambient_c"] if r["ambient_c"] is not None else r["temp_c"]
            out.append(twin.Step(t, amb, r["solar_wm2"] or 0.0, door, 1.0, ph))
        return out

    amb0 = rows[0]["ambient_c"] if rows[0]["ambient_c"] is not None else rows[0]["temp_c"]
    t0_actual = rows[0]["temp_c"]
    t0_nominal = min(t0_actual, twin.initial_temp(amb0, sp, 0.95))

    def burns(st: list[twin.Step], t0: float) -> list[float]:
        temps_cf = [round(t, 1) for t, _ in twin.run_model(st, sp, t0)]
        return spoilage.interval_burns(adj, ts, temps_cf)

    e0 = burns(steps(False, False), t0_nominal)
    e1 = burns(steps(True, False), t0_actual)
    e2 = burns(steps(True, True), t0_actual)

    cats = ("environment", "shipper", "carrier_door", "carrier_reefer", "receiver_dwell")
    parts: dict[str, list[float]] = {c: [0.0] * len(rows) for c in cats}
    for i, e in enumerate(e_act):
        if e <= 0:
            continue
        c0 = min(e0[i], e)
        c1 = max(0.0, e1[i] - e0[i])
        c2 = max(0.0, e2[i] - e1[i])
        c3 = max(0.0, e - e2[i])
        tot = c0 + c1 + c2 + c3
        if tot <= 0:
            continue
        k = e / tot
        parts["environment"][i] = c0 * k
        parts["shipper"][i] = c1 * k
        parts["carrier_door"][i] = c2 * k
        (parts["receiver_dwell"] if ts[i] >= dock_free_end else parts["carrier_reefer"])[i] = c3 * k

    total_e = sum(e_act)
    assessed = spoilage.assess(com, rows, value)
    loss_frac = assessed["loss_frac"]
    minutes_i = [min((ts[i + 1] - ts[i]) / 60.0, 60.0) if i + 1 < len(ts) else 0.0 for i in range(len(ts))]

    cause_meta = {
        "environment": ("shared", "5.1", "Ambient conditions exceeded what a compliant load and healthy unit can hold"),
        "shipper": ("shipper", None, "Cargo condition at loading and loading duration"),
        "carrier_door": ("carrier", "3.2", "Door open in transit without a logged inspection"),
        "carrier_reefer": ("carrier", "3.1", "Refrigeration unit could not hold set-point"),
        "receiver_dwell": ("receiver", "4.1", "Excursion after the receiver's free dock time"),
    }
    if t0_actual - sp > prm["precool_tolerance_c"]:
        cause_meta["shipper"] = ("shipper", "2.1", f"Cargo loaded {t0_actual - sp:.1f} C above set-point (tolerance {prm['precool_tolerance_c']:g} C)")
    elif any(r["phase"] == "loading" for r in rows) and sum(1 for r in rows if r["phase"] == "loading") * 10 > prm["load_free_minutes"]:
        cause_meta["shipper"] = ("shipper", "2.2", "Loading took longer than the free loading time")

    findings, party_tot = [], defaultdict(lambda: {"share": 0.0, "minutes": 0.0, "amount_inr": 0.0})
    n = 0
    for cat in cats:
        vals = parts[cat]
        s = sum(vals)
        if s <= 1e-9 or total_e <= 0:
            continue
        party, clause, desc = cause_meta[cat]
        share = s / total_e
        mins = sum(minutes_i[i] * (vals[i] / e_act[i]) for i in range(len(rows)) if e_act[i] > 0 and vals[i] > 0)
        seqs = [rows[i]["seq"] for i in range(len(rows)) if vals[i] > 1e-9]
        amount = share * loss_frac * value
        n += 1
        ev_ids = [e["id"] for e in events if (cat == "carrier_door" and e["event"] in ("door_opened", "door_closed"))
                  or (cat == "receiver_dwell" and e["event"] in ("arrived", "unloading_started"))
                  or (cat == "shipper" and e["event"] in ("loading_started", "departed"))]
        findings.append({"id": f"F{n}", "cause": cat, "party": party, "clause": clause, "description": desc,
                         "share_pct": round(share * 100, 1), "minutes": round(mins, 0), "amount_inr": round(amount, 2),
                         "seq_ranges": _ranges(seqs), "event_ids": ev_ids})
        p = party_tot[party]
        p["share"] += share
        p["minutes"] += mins
        p["amount_inr"] += amount

    cap = prm["cap_fraction_of_value"] * value
    parties = {}
    for party, p in party_tot.items():
        amt = p["amount_inr"] if party == "shared" else min(p["amount_inr"], cap)
        parties[party] = {"share_pct": round(p["share"] * 100, 1), "minutes": round(p["minutes"], 0),
                          "amount_inr": round(amt, 2), "capped": party != "shared" and p["amount_inr"] > cap}
    result.update({
        "totals": {"loss_frac": loss_frac, "loss_pct": assessed["loss_pct"], "loss_inr": assessed["value_at_risk_inr"],
                   "declared_value_inr": value, "minutes_out_of_band": assessed["minutes_out_of_band"],
                   "first_breach_ts": assessed["first_breach_ts"], "max_temp_c": assessed["max_temp_c"]},
        "parties": parties, "findings": findings,
        "assumptions": [
            "Loss = shelf-life consumed beyond the allowed band, valued at the declared cargo value.",
            "Counterfactuals use a calibrated thermal model; for device data, model error is absorbed by the carrier/receiver residual.",
            f"Band widened by {TOL_C} C in attribution to ignore sensor rounding.",
            "Environmental share is not attributed to any party (SLA 5.1).",
        ],
    })
    return result
