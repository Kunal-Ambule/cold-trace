from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from .. import db, security
from ..agents import monitor
from .schemas import ActionDecisionReq

router = APIRouter(prefix="/api/actions", tags=["actions"])


@router.get("/pending")
def pending(user: dict = Depends(security.current_user)):
    return db.all_("SELECT a.*, s.code as shipment_code FROM actions a JOIN shipments s ON s.id=a.shipment_id "
                   "WHERE a.status='proposed' ORDER BY a.id DESC")


@router.post("/{action_id}/decide")
def decide(action_id: int, body: ActionDecisionReq, user: dict = Depends(security.require("dispatcher", "admin"))):
    try:
        return monitor.decide_action(action_id, body.approve, user["username"], body.note)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
