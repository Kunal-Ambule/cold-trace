"""Read-only reference data: lanes, hubs, commodities, prices, model card, LLM status."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from .. import db, security
from ..config import settings
from ..domain.commodities import COMMODITIES
from ..domain.lanes import LANES
from ..ml.inference import models
from ..services import dataload, prices
from ..agents.llm import llm

router = APIRouter(prefix="/api/ref", tags=["reference"])


@router.get("/config")
def ui_config(user: dict = Depends(security.current_user)):
    """Frontend display config that isn't secret-sensitive per se, but shouldn't be hardcoded in JS."""
    if settings.maptiler_key:
        # MapTiler's "streets" style: bright, high-detail, Google Maps-like. Free tier at maptiler.com,
        # no billing required for demo/low traffic. Set MAPTILER_KEY in .env to use it.
        tile_url = f"https://api.maptiler.com/maps/streets-v2/{{z}}/{{x}}/{{y}}.png?key={settings.maptiler_key}"
        attribution = '\u00a9 <a href="https://www.maptiler.com/copyright/">MapTiler</a> \u00a9 OpenStreetMap contributors'
    else:
        # Standard OpenStreetMap tiles: always free, no signup, no API key - the reliable default.
        tile_url = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        attribution = '\u00a9 <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    return {"map_tile_url": tile_url, "map_attribution": attribution, "map_max_zoom": 19}


@router.get("/lanes")
def lanes(user: dict = Depends(security.current_user)):
    out = []
    for l in LANES:
        row = db.one("SELECT distance_km,duration_min,route_source FROM lanes WHERE id=?", (l.id,))
        out.append({"id": l.id, "name": l.name, "origin": {"name": l.origin.name, "lat": l.origin.lat, "lon": l.origin.lon},
                    "dest": {"name": l.dest.name, "lat": l.dest.lat, "lon": l.dest.lon},
                    "origin_market": l.origin_market, "origin_state": l.origin_state, "commodities": list(l.commodities),
                    "shipper": l.shipper, "carrier": l.carrier, "receiver": l.receiver,
                    "distance_km": row["distance_km"] if row else None, "duration_min": row["duration_min"] if row else None,
                    "route_source": row["route_source"] if row else None})
    return out


@router.get("/lanes/{lane_id}/route")
def lane_route(lane_id: str, user: dict = Depends(security.current_user)):
    row = db.one("SELECT route_json FROM lanes WHERE id=?", (lane_id,))
    if not row:
        raise HTTPException(404, "Unknown lane")
    return db.jload(row["route_json"])


@router.get("/hubs")
def hubs(user: dict = Depends(security.current_user)):
    return db.all_("SELECT id,name,lat,lon,verified FROM hubs")


@router.get("/commodities")
def commodities(user: dict = Depends(security.current_user)):
    return [c.as_dict() for c in COMMODITIES.values()]


@router.get("/scenarios")
def scenarios(user: dict = Depends(security.current_user)):
    from ..services.twin import SCENARIOS
    return {k: v["label"] for k, v in SCENARIOS.items()}


@router.get("/prices/{commodity_code}")
def price_lookup(commodity_code: str, market: str | None = None, state: str | None = None, user: dict = Depends(security.current_user)):
    return prices.lookup(commodity_code, market, state)


@router.get("/prices/{commodity_code}/explorer")
def price_explorer(commodity_code: str, state: str | None = None, user: dict = Depends(security.current_user)):
    return prices.explorer(commodity_code, state)


@router.get("/prices/{commodity_code}/states")
def price_states(commodity_code: str, user: dict = Depends(security.current_user)):
    return prices.states_for(commodity_code)


@router.get("/data-status")
def data_status(user: dict = Depends(security.current_user)):
    n_prices = db.one("SELECT COUNT(*) n, COUNT(DISTINCT commodity) c, COUNT(DISTINCT state) s FROM market_prices")
    return {"prices": {"listings": n_prices["n"], "commodities": n_prices["c"], "states": n_prices["s"],
                       "source": "Agmarknet (Govt. of India) via data.gov.in"},
            "weather": dataload.weather_status(), "model": models.card(), "llm": llm.status()}


@router.get("/sla")
def sla(user: dict = Depends(security.current_user)):
    return db.all_("SELECT contract_id,clause_no,title,body,param_key,param_value FROM sla_clauses ORDER BY clause_no")
