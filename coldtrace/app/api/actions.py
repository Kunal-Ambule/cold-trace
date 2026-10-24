from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from .. import db
from ..agents import monitor
from ..security import current_user, require
from .schemas import ActionDecisionReq

router = APIRouter(prefix="/api/actions", tags=["actions"])


@router.get("")
def list_actions(status: str = "proposed", _: dict = Depends(current_user)):
    rows = db.all_("SELECT a.*, s.code shipment_code FROM actions a JOIN shipments s ON s.id=a.shipment_id "
                   "WHERE a.status=? ORDER BY a.id DESC", (status,))
    for r in rows:
        r["proposal"] = db.jload(r["proposal_json"])
        del r["proposal_json"]
    return rows


@router.post("/{action_id}/decision")
def decide(action_id: int, req: ActionDecisionReq, user: dict = Depends(require("dispatcher", "admin"))):
    try:
        return monitor.decide_action(action_id, req.approve, user["username"], req.note)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
