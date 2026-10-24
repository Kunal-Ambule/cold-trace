"""Ingestion endpoints for real devices and the driver PWA. Same pipeline the simulator uses."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from .. import db
from ..security import current_user, require
from ..services import ingest as ingest_svc
from .deps import get_shipment_or_404
from .schemas import EventIn, ReadingsIn, TamperReq

router = APIRouter(prefix="/api/shipments/{shipment_id}", tags=["ingest"])


@router.post("/readings")
def post_readings(shipment_id: int, req: ReadingsIn, user: dict = Depends(require("driver", "dispatcher", "admin"))):
    get_shipment_or_404(shipment_id)
    try:
        return ingest_svc.ingest_readings(shipment_id, [r.model_dump() for r in req.readings], "device", actor=user["username"])
    except ingest_svc.IngestError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/events")
def post_event(shipment_id: int, req: EventIn, user: dict = Depends(require("driver", "dispatcher", "admin"))):
    get_shipment_or_404(shipment_id)
    eid = ingest_svc.add_event(shipment_id, req.ts, req.party, req.event, req.note, actor=user["username"],
                               transcript=req.transcript, lat=req.lat, lon=req.lon, temp_c=req.temp_c,
                               source="manual", idem_key=req.idem_key)
    return {"id": eid}


@router.post("/tamper_demo")
def tamper_demo(shipment_id: int, req: TamperReq, user: dict = Depends(require("admin"))):
    """Rewrites one sealed reading in place (bypassing ingest) to demonstrate ledger tamper-detection.
    Requires ALLOW_TAMPER_DEMO=1 and the admin role; disable in any real deployment."""
    from ..config import settings
    if not settings.allow_tamper_demo:
        raise HTTPException(403, "Tamper demo disabled (ALLOW_TAMPER_DEMO=0)")
    get_shipment_or_404(shipment_id)
    row = db.one("SELECT id FROM readings WHERE shipment_id=? AND seq=?", (shipment_id, req.seq))
    if not row:
        raise HTTPException(404, "No reading at that sequence")
    db.run("UPDATE readings SET temp_c=? WHERE id=?", (req.temp_c, row["id"]))
    return {"tampered_seq": req.seq, "new_temp_c": req.temp_c}
