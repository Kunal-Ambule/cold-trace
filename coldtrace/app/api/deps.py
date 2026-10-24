from __future__ import annotations

from fastapi import HTTPException

from .. import db


def get_shipment_or_404(shipment_id: int) -> dict:
    s = db.one("SELECT * FROM shipments WHERE id=?", (shipment_id,))
    if not s:
        raise HTTPException(404, "Shipment not found")
    return s
