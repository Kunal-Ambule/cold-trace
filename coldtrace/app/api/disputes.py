from __future__ import annotations

import logging
import threading

from fastapi import APIRouter, Depends, HTTPException

from .. import db
from ..agents import dispute as dispute_agent
from ..security import current_user, require
from ..services import ingest
from .deps import get_shipment_or_404
from .schemas import DisputeCreateReq

log = logging.getLogger("coldtrace.api.disputes")
router = APIRouter(prefix="/api/disputes", tags=["disputes"])


@router.get("")
def list_disputes(_: dict = Depends(current_user)):
    rows = db.all_("SELECT d.id,d.shipment_id,s.code shipment_code,d.claimant,d.respondent,d.status,d.created_at "
                   "FROM disputes d JOIN shipments s ON s.id=d.shipment_id ORDER BY d.id DESC")
    return rows


@router.post("")
def create_dispute(req: DisputeCreateReq, user: dict = Depends(require("dispatcher", "auditor", "admin"))):
    get_shipment_or_404(req.shipment_id)
    did = db.run("INSERT INTO disputes(shipment_id,claimant,respondent,claim_amount_inr,description,status,created_by,created_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (req.shipment_id, req.claimant, req.respondent, req.claim_amount_inr, req.description, "running",
                 user["username"], ingest.now_iso()))

    def _job() -> None:
        try:
            dispute_agent.run(did)
        except Exception:  # noqa: BLE001
            log.exception("dispute agent failed")

    threading.Thread(target=_job, name=f"dispute-{did}", daemon=True).start()
    return {"id": did, "status": "running"}


@router.get("/{dispute_id}")
def get_dispute(dispute_id: int, _: dict = Depends(current_user)):
    d = db.one("SELECT d.*, s.code shipment_code FROM disputes d JOIN shipments s ON s.id=d.shipment_id WHERE d.id=?", (dispute_id,))
    if not d:
        raise HTTPException(404, "Dispute not found")
    d["report"] = db.jload(d["report_json"])
    del d["report_json"]
    return d


@router.post("/{dispute_id}/rerun")
def rerun(dispute_id: int, user: dict = Depends(require("dispatcher", "auditor", "admin"))):
    d = db.one("SELECT id FROM disputes WHERE id=?", (dispute_id,))
    if not d:
        raise HTTPException(404, "Dispute not found")
    db.run("UPDATE disputes SET status='running' WHERE id=?", (dispute_id,))
    threading.Thread(target=lambda: dispute_agent.run(dispute_id), daemon=True).start()
    return {"id": dispute_id, "status": "running"}


@router.get("/{dispute_id}/docket.pdf")
def docket_pdf(dispute_id: int, _: dict = Depends(current_user)):
    from fastapi.responses import Response

    from ..services.docket import build_pdf
    d = db.one("SELECT d.*, s.code shipment_code FROM disputes d JOIN shipments s ON s.id=d.shipment_id WHERE d.id=?", (dispute_id,))
    if not d or not d["report_json"]:
        raise HTTPException(404, "Report not ready")
    pdf = build_pdf(d, db.jload(d["report_json"]))
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f"inline; filename=docket-{d['shipment_code']}.pdf"})
