from __future__ import annotations

import threading

from fastapi import APIRouter, Depends, HTTPException

from .. import db, security
from ..agents import dispute as dispute_agent
from ..services import ingest
from .schemas import DisputeCreateReq

router = APIRouter(prefix="/api/disputes", tags=["disputes"])


@router.get("")
def list_disputes(user: dict = Depends(security.current_user)):
    rows = db.all_("SELECT id,shipment_id,claimant,respondent,claim_amount_inr,description,status,created_by,created_at FROM disputes ORDER BY id DESC")
    for r in rows:
        r["shipment_code"] = db.one("SELECT code FROM shipments WHERE id=?", (r["shipment_id"],))["code"]
    return rows


@router.post("")
def create_dispute(body: DisputeCreateReq, user: dict = Depends(security.require("dispatcher", "auditor", "admin"))):
    if not db.one("SELECT id FROM shipments WHERE id=?", (body.shipment_id,)):
        raise HTTPException(404, "Unknown shipment")
    did = db.run("INSERT INTO disputes(shipment_id,claimant,respondent,claim_amount_inr,description,status,created_by,created_at) "
                 "VALUES(?,?,?,?,?,?,?,?)", (body.shipment_id, body.claimant, body.respondent, body.claim_amount_inr,
                 body.description, "processing", user["username"], ingest.now_iso()))

    def _job() -> None:
        try:
            dispute_agent.run_dispute(did)
        except Exception:  # noqa: BLE001
            pass

    threading.Thread(target=_job, name=f"dispute-{did}", daemon=True).start()
    return {"id": did, "status": "processing"}


@router.get("/{dispute_id}")
def get_dispute(dispute_id: int, user: dict = Depends(security.current_user)):
    d = db.one("SELECT * FROM disputes WHERE id=?", (dispute_id,))
    if not d:
        raise HTTPException(404, "Unknown dispute")
    d["report"] = db.jload(d["report_json"])
    d["shipment_code"] = db.one("SELECT code FROM shipments WHERE id=?", (d["shipment_id"],))["code"]
    return d


@router.post("/{dispute_id}/recompute")
def recompute(dispute_id: int, user: dict = Depends(security.require("auditor", "dispatcher", "admin"))):
    d = db.one("SELECT id FROM disputes WHERE id=?", (dispute_id,))
    if not d:
        raise HTTPException(404, "Unknown dispute")
    db.run("UPDATE disputes SET status='processing' WHERE id=?", (dispute_id,))
    report = dispute_agent.run_dispute(dispute_id)
    return report


@router.get("/{dispute_id}/docket.pdf")
def docket_pdf(dispute_id: int, user: dict = Depends(security.current_user)):
    from fastapi.responses import Response
    from ..services.docket import render_docket_pdf
    d = db.one("SELECT * FROM disputes WHERE id=?", (dispute_id,))
    if not d or not d["report_json"]:
        raise HTTPException(404, "Dispute has no report yet")
    pdf_bytes = render_docket_pdf(db.jload(d["report_json"]))
    return Response(pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": f"inline; filename=docket-{dispute_id}.pdf"})
