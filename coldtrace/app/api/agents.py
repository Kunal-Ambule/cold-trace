from __future__ import annotations

from fastapi import APIRouter, Depends

from .. import db
from ..agents.llm import llm
from ..agents.tools import registry
from ..security import current_user

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("/status")
def status(_: dict = Depends(current_user)):
    return {"llm": llm.status(), "tools": registry.describe()}


@router.get("/runs")
def runs(shipment_id: int | None = None, dispute_id: int | None = None, limit: int = 30, _: dict = Depends(current_user)):
    q, args = "SELECT * FROM agent_runs", []
    where = []
    if shipment_id:
        where.append("shipment_id=?")
        args.append(shipment_id)
    if dispute_id:
        where.append("dispute_id=?")
        args.append(dispute_id)
    if where:
        q += " WHERE " + " AND ".join(where)
    rows = db.all_(q + " ORDER BY id DESC LIMIT ?", args + [limit])
    for r in rows:
        r["steps"] = db.jload(r["steps_json"], [])
        r["result"] = db.jload(r["result_json"])
        del r["steps_json"], r["result_json"]
    return rows


@router.get("/runs/{run_id}")
def run_detail(run_id: int, _: dict = Depends(current_user)):
    r = db.one("SELECT * FROM agent_runs WHERE id=?", (run_id,))
    if r:
        r["steps"] = db.jload(r["steps_json"], [])
        r["result"] = db.jload(r["result_json"])
        del r["steps_json"], r["result_json"]
    return r
