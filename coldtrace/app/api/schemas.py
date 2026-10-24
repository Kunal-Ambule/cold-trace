"""Pydantic request models. Kept separate from domain dataclasses so the API can evolve independently."""
from __future__ import annotations

from pydantic import BaseModel, Field


class LoginReq(BaseModel):
    username: str
    password: str


class CreateShipmentReq(BaseModel):
    lane_id: str
    commodity_code: str
    depart_ts: str
    scenario: str = "nominal"
    qty_kg: float | None = None
    declared_value_inr: float | None = None
    carrier: str | None = None


class UpdateShipmentReq(BaseModel):
    """Only operational details that don't invalidate the already-computed physics/route replay can be
    edited after creation. Lane, commodity, departure time, and scenario are fixed at creation - like a
    real waybill, changing the trip itself means creating a new shipment."""
    qty_kg: float | None = None
    declared_value_inr: float | None = None
    carrier: str | None = None
    receiver: str | None = None


class ReadingIn(BaseModel):
    ts: str
    temp_c: float
    seq: int | None = None
    lat: float | None = None
    lon: float | None = None
    setpoint_c: float | None = None
    ambient_c: float | None = None
    solar_wm2: float | None = None
    rh: float | None = None
    door_open: bool = False
    duty: float | None = None
    phase: str | None = None
    idem_key: str | None = None


class ReadingsIn(BaseModel):
    readings: list[ReadingIn]
    source: str = "device"


class EventIn(BaseModel):
    ts: str
    party: str
    event: str
    note: str | None = None
    transcript: str | None = None
    lat: float | None = None
    lon: float | None = None
    temp_c: float | None = None
    idem_key: str | None = None


class ActionDecisionReq(BaseModel):
    approve: bool
    note: str | None = None


class DisputeCreateReq(BaseModel):
    shipment_id: int
    claimant: str
    respondent: str | None = None
    claim_amount_inr: float | None = None
    description: str | None = None


class AdvanceReq(BaseModel):
    n: int = Field(default=1, ge=1, le=500)


class TrainReq(BaseModel):
    depart_every_h: int = Field(default=12, ge=4, le=48)
