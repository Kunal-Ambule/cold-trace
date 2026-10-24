from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from .. import db, security
from ..domain.commodities import get as get_com
from ..services import alerts as alert_svc
from ..services import attribution, ingest, ledger, shipments
from ..services.weather import WeatherUnavailable
from .schemas import AdvanceReq, CreateShipmentReq, EventIn, ReadingsIn, UpdateShipmentReq

log = logging.getLogger("coldtrace.api.shipments")
router = APIRouter(prefix="/api/shipments", tags=["shipments"])


@router.get("")
def list_shipments(status: str | None = None, user: dict = Depends(security.current_user)):
    q = "SELECT id,code,lane_id,commodity_code,qty_kg,declared_value_inr,carrier,setpoint_c,depart_ts,status,scenario,data_source,cursor,created_at FROM shipments"
    args = ()
    if status:
        q += " WHERE status=?"
        args = (status,)
    rows = db.all_(q + " ORDER BY id DESC", args)
    for r in rows:
        last = db.one("SELECT ts,temp_c,lat,lon,phase FROM readings WHERE shipment_id=? ORDER BY seq DESC LIMIT 1", (r["id"],))
        r["last_reading"] = last
        if last:
            com = get_com(r["commodity_code"])
            r["out_of_band"] = last["temp_c"] > com.t_max or last["temp_c"] < com.t_min
        else:
            r["out_of_band"] = False
    return rows


@router.post("")
def create_shipment(body: CreateShipmentReq, user: dict = Depends(security.require("dispatcher", "admin"))):
    try:
        return shipments.create(body.lane_id, body.commodity_code, body.depart_ts, body.scenario, body.qty_kg,
                                body.declared_value_inr, body.carrier)
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e)) from e
    except WeatherUnavailable as e:
        raise HTTPException(400, f"{e} (run scripts/fetch_data.py --weather once, with internet access, to load real ERA5 weather)") from e


@router.get("/{shipment_id}")
def get_shipment(shipment_id: int, user: dict = Depends(security.current_user)):
    s = shipments.get(shipment_id)
    if not s:
        raise HTTPException(404, "Unknown shipment")
    return s


@router.patch("/{shipment_id}")
def update_shipment(shipment_id: int, body: UpdateShipmentReq, user: dict = Depends(security.require("dispatcher", "admin"))):
    try:
        return shipments.update(shipment_id, qty_kg=body.qty_kg, declared_value_inr=body.declared_value_inr,
                                 carrier=body.carrier, receiver=body.receiver)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.delete("/{shipment_id}")
def delete_shipment(shipment_id: int, user: dict = Depends(security.require("dispatcher", "admin"))):
    try:
        shipments.delete(shipment_id)
    except ValueError as e:
        raise HTTPException(404 if "unknown shipment" in str(e) else 400, str(e))
    return {"deleted": True}


@router.get("/{shipment_id}/readings")
def get_readings(shipment_id: int, since_seq: int = -1, limit: int = 2000, user: dict = Depends(security.current_user)):
    return db.all_("SELECT * FROM readings WHERE shipment_id=? AND seq>? ORDER BY seq LIMIT ?", (shipment_id, since_seq, limit))


@router.get("/{shipment_id}/events")
def get_events(shipment_id: int, user: dict = Depends(security.current_user)):
    return db.all_("SELECT * FROM custody_events WHERE shipment_id=? ORDER BY ts", (shipment_id,))


@router.get("/{shipment_id}/alerts")
def get_alerts(shipment_id: int, user: dict = Depends(security.current_user)):
    return db.all_("SELECT * FROM alerts WHERE shipment_id=? ORDER BY ts", (shipment_id,))


@router.get("/{shipment_id}/summary")
def get_summary(shipment_id: int, user: dict = Depends(security.current_user)):
    if not shipments.get(shipment_id):
        raise HTTPException(404, "Unknown shipment")
    return alert_svc.summarize(shipment_id)


@router.get("/{shipment_id}/route")
def get_route(shipment_id: int, user: dict = Depends(security.current_user)):
    s = shipments.get(shipment_id)
    if not s:
        raise HTTPException(404, "Unknown shipment")
    return db.jload(db.one("SELECT route_json r FROM lanes WHERE id=?", (s["lane_id"],))["r"])


@router.get("/{shipment_id}/ledger")
def get_ledger(shipment_id: int, user: dict = Depends(security.current_user)):
    return ledger.verify(shipment_id)


@router.get("/{shipment_id}/attribution")
def get_attribution(shipment_id: int, user: dict = Depends(security.current_user)):
    if not shipments.get(shipment_id):
        raise HTTPException(404, "Unknown shipment")
    return attribution.apportion(shipment_id)


@router.get("/{shipment_id}/actions")
def get_actions(shipment_id: int, user: dict = Depends(security.current_user)):
    rows = db.all_("SELECT * FROM actions WHERE shipment_id=? ORDER BY id DESC", (shipment_id,))
    for r in rows:
        r["proposal"] = db.jload(r["proposal_json"])
    return rows


@router.get("/{shipment_id}/agent-runs")
def get_runs(shipment_id: int, user: dict = Depends(security.current_user)):
    rows = db.all_("SELECT * FROM agent_runs WHERE shipment_id=? ORDER BY id DESC", (shipment_id,))
    for r in rows:
        r["steps"] = db.jload(r["steps_json"], [])
        r["result"] = db.jload(r["result_json"])
    return rows


@router.post("/{shipment_id}/readings")
def post_readings(shipment_id: int, body: ReadingsIn, user: dict = Depends(security.require("driver", "dispatcher", "admin"))):
    if not shipments.get(shipment_id):
        raise HTTPException(404, "Unknown shipment")
    try:
        return ingest.ingest_readings(shipment_id, [r.model_dump() for r in body.readings], body.source, actor=user["username"])
    except ingest.IngestError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/{shipment_id}/events")
def post_event(shipment_id: int, body: EventIn, user: dict = Depends(security.require("driver", "dispatcher", "admin"))):
    if not shipments.get(shipment_id):
        raise HTTPException(404, "Unknown shipment")
    eid = ingest.add_event(shipment_id, body.ts, body.party, body.event, body.note, actor=user["username"],
                          transcript=body.transcript, lat=body.lat, lon=body.lon, temp_c=body.temp_c,
                          source="manual", idem_key=body.idem_key)
    return {"id": eid}


@router.post("/{shipment_id}/advance")
def advance(shipment_id: int, body: AdvanceReq, user: dict = Depends(security.require("dispatcher", "admin"))):
    """Replay demo control: feed the next n frames of a model-derived (data_source='twin') shipment."""
    s = shipments.get(shipment_id)
    if not s:
        raise HTTPException(404, "Unknown shipment")
    if s["data_source"] != "twin":
        raise HTTPException(400, "advance is only for model-derived (twin) shipments; device shipments post live readings")
    return shipments.advance(shipment_id, body.n)


@router.post("/{shipment_id}/fast-forward")
def fast_forward(shipment_id: int, user: dict = Depends(security.require("dispatcher", "admin"))):
    s = shipments.get(shipment_id)
    if not s:
        raise HTTPException(404, "Unknown shipment")
    if s["data_source"] != "twin":
        raise HTTPException(400, "fast-forward is only for model-derived (twin) shipments")
    return shipments.fast_forward(shipment_id)
