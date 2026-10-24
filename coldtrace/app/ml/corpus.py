"""Builds the training corpus by replaying the thermal model over REAL weather for every lane."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from .. import db
from ..domain.commodities import get as get_com
from ..domain.lanes import LANES
from ..services import routing, twin
from ..services.weather import WeatherStore, WeatherUnavailable, lane_stations, to_epoch, to_iso

log = logging.getLogger("coldtrace.ml")


@dataclass
class Trip:
    lane_id: str
    commodity: str
    scenario: str
    depart_epoch: float
    frames: list[dict]


def build_corpus(weather: WeatherStore, depart_every_h: int = 12, lanes=None, commodities_per_lane: int = 3) -> list[Trip]:
    trips: list[Trip] = []
    for lane in (lanes or LANES):
        route = routing.ensure_route(lane)
        keys = [k for k, *_ in lane_stations(lane)]
        try:
            lo, hi = weather.window(keys)
        except WeatherUnavailable:
            log.warning("skip lane %s: no weather", lane.id)
            continue
        span = (route["duration_min"] + 60 + 240 + 60) * 60          # load + trip + longest queue + unload
        t = lo + 2 * 3600 + 45 * 60
        while t + span < hi:
            for comm in lane.commodities[:commodities_per_lane]:
                for sc in twin.SCENARIOS:
                    try:
                        r = twin.simulate_trip(lane, route, to_iso(t), comm, sc, weather)
                    except WeatherUnavailable:
                        continue
                    trips.append(Trip(lane.id, comm, sc, t, r["frames"]))
            t += depart_every_h * 3600
    return trips
