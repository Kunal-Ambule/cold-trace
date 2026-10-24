from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from .. import db
from ..security import current_user, require
from ..services import alerts as alert_svc
from ..services import ledger, shipments as ship_svc
from .deps import get_shipment_or_404
from .schemas import AdvanceReq, CreateShipmentReq, FastForwardReq

router = APIRouter(prefix="/api/shipments", tags=["shipments"])


@router.get("")
def list_shipments(status: str | None = None, _: dict = Depends(current_user)):
    q = "SELECT id,code,lane_id,commodity_code,qty_kg,declared_value_inr,carrier,setpoint_c,depart_ts,status,scenario,cursor,created_at FROM shipments"
    args: list = []
    if status:
        q += " WHERE status=?"
        args.append(status)
    rows = db.all_(q + " ORDER BY id DESC", args)
    out = []
    for s in rows:
        sm = alert_svc.summarize(s["id"])
        out.append({**s, "risk_level": sm["risk_level"], "loss_pct": sm["loss_pct"], "current_temp_c": sm["current_temp_c"]})
    return out


@router.post("")
def create_shipment(req: CreateShipmentReq, user: dict = Depends(require("dispatcher"))):
    try:
        return ship_svc.create(req.lane_id, req.commodity_code, req.depart_ts, req.scenario, req.qty_kg,
                               req.declared_value_inr, req.carrier)
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e)) from e


@router.get("/{shipment_id}")
def get_shipment(shipment_id: int, _: dict = Depends(current_user)):
    get_shipment_or_404(shipment_id)
    s = ship_svc.get(shipment_id)
    return {**s, "assessment": alert_svc.summarize(shipment_id)}


@router.get("/{shipment_id}/readings")
def readings(shipment_id: int, since_seq: int = -1, limit: int = 2000, _: dict = Depends(current_user)):
    get_shipment_or_404(shipment_id)
    return db.all_("SELECT * FROM readings WHERE shipment_id=? AND seq>? ORDER BY seq LIMIT ?", (shipment_id, since_seq, limit))


@router.get("/{shipment_id}/events")
def events(shipment_id: int, _: dict = Depends(current_user)):
    get_shipment_or_404(shipment_id)
    return db.all_("SELECT * FROM custody_events WHERE shipment_id=? ORDER BY ts", (shipment_id,))


@router.get("/{shipment_id}/alerts")
def shipment_alerts(shipment_id: int, _: dict = Depends(current_user)):
    get_shipment_or_404(shipment_id)
    return db.all_("SELECT * FROM alerts WHERE shipment_id=? ORDER BY ts DESC", (shipment_id,))


@router.get("/{shipment_id}/actions")
def shipment_actions(shipment_id: int, _: dict = Depends(current_user)):
    get_shipment_or_404(shipment_id)
    rows = db.all_("SELECT * FROM actions WHERE shipment_id=? ORDER BY id DESC", (shipment_id,))
    for r in rows:
        r["proposal"] = db.jload(r["proposal_json"])
        del r["proposal_json"]
    return rows


@router.get("/{shipment_id}/ledger")
def shipment_ledger(shipment_id: int, _: dict = Depends(current_user)):
    get_shipment_or_404(shipment_id)
    return ledger.verify(shipment_id)


@router.post("/{shipment_id}/ledger/seal")
def seal_now(shipment_id: int, user: dict = Depends(require("dispatcher", "admin"))):
    get_shipment_or_404(shipment_id)
    n = ledger.seal(shipment_id, force=True)
    return {"blocks_created": n}


@router.post("/{shipment_id}/advance")
def advance(shipment_id: int, req: AdvanceReq, user: dict = Depends(require("dispatcher", "admin"))):
    get_shipment_or_404(shipment_id)
    return ship_svc.advance(shipment_id, req.frames)


@router.post("/{shipment_id}/fast_forward")
def fast_forward(shipment_id: int, req: FastForwardReq, user: dict = Depends(require("dispatcher", "admin"))):
    get_shipment_or_404(shipment_id)
    return ship_svc.fast_forward(shipment_id, req.upto_fraction)
