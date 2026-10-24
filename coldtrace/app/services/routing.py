"""Road geometry for each lane. Tries OSRM; falls back to the waypoint polyline (flagged)."""
from __future__ import annotations

import logging

import httpx

from .. import db
from ..config import settings
from ..domain.lanes import LANES, Lane
from .geo import cumulative_km, densify

log = logging.getLogger("coldtrace.routing")

ROAD_FACTOR = 1.25        # straight-line -> road distance when OSRM is unavailable
TRUCK_KMH = 42.0          # average loaded reefer speed including stops
TRUCK_SLOWDOWN = 1.25     # OSRM returns car speeds; trucks are slower


def _decimate(pts: list[list[float]], max_pts: int = 900) -> list[list[float]]:
    if len(pts) <= max_pts:
        return pts
    step = len(pts) / max_pts
    out = [pts[int(i * step)] for i in range(max_pts)]
    out.append(pts[-1])
    return out


def _osrm(lane: Lane) -> dict | None:
    coords = ";".join(f"{p.lon:.5f},{p.lat:.5f}" for p in lane.path)
    url = f"{settings.osrm_url}/route/v1/driving/{coords}"
    try:
        r = httpx.get(url, params={"overview": "full", "geometries": "geojson"}, timeout=12)
        r.raise_for_status()
        route = r.json()["routes"][0]
    except Exception as e:  # noqa: BLE001 - any network problem means fallback
        log.warning("OSRM unavailable for %s (%s); using waypoint polyline", lane.id, e)
        return None
    pts = _decimate([[lat, lon] for lon, lat in route["geometry"]["coordinates"]])
    cum = cumulative_km([(p[0], p[1]) for p in pts])
    scale = (route["distance"] / 1000.0) / max(cum[-1], 1e-6)
    cum = [c * scale for c in cum]
    return {"points": pts, "cum": cum, "distance_km": route["distance"] / 1000.0,
            "duration_min": route["duration"] / 60.0 * TRUCK_SLOWDOWN, "source": "osrm"}


def _fallback(lane: Lane) -> dict:
    base = [(p.lat, p.lon) for p in lane.path]
    pts = densify(base, 2.0)
    cum = [c * ROAD_FACTOR for c in cumulative_km(pts)]
    dist = cum[-1]
    return {"points": [[a, b] for a, b in pts], "cum": cum, "distance_km": dist,
            "duration_min": dist / TRUCK_KMH * 60.0, "source": "waypoints"}


def ensure_route(lane: Lane, refresh: bool = False) -> dict:
    row = db.one("SELECT route_json, route_source FROM lanes WHERE id=?", (lane.id,))
    if row and row["route_json"] and not refresh:
        return db.jload(row["route_json"])
    route = _osrm(lane) or _fallback(lane)
    db.run(
        "INSERT INTO lanes(id,name,origin_name,dest_name,route_json,distance_km,duration_min,route_source) "
        "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET route_json=excluded.route_json, "
        "distance_km=excluded.distance_km, duration_min=excluded.duration_min, route_source=excluded.route_source",
        (lane.id, lane.name, lane.origin.name, lane.dest.name, db.jdump(route),
         route["distance_km"], route["duration_min"], route["source"]),
    )
    return route


def ensure_all_routes() -> None:
    for lane in LANES:
        ensure_route(lane)
