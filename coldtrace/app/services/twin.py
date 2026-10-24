"""Reefer thermal model driven by REAL weather.

There is no public dataset of real reefer telemetry, so instead of inventing sensor noise we compute what a
reefer's return-air probe would read, given:
  * the real hourly air temperature, humidity and solar radiation (ERA5) at the truck's position and time,
  * a two-node heat balance (air <-> cargo <-> ambient) and a proportional-control refrigeration unit.
Every reading produced here is stored with source='twin' and labelled "model-derived" in the UI. Real devices
post to /api/readings with source='device' and go through exactly the same pipeline.

Heat balance (hours as time unit, all coefficients per hour):
    dT_air   = K_AMB*(T_ambient_eff - T_air) + K_AC*(T_cargo - T_air) - K_REF*duty*eff*(T_air - T_coil)
    dT_cargo = K_CA*(T_air - T_cargo)
    T_ambient_eff = T_ambient + SOLAR_GAIN * shortwave_radiation      (sun-loaded roof and walls)
    K_AMB is multiplied up while doors are open.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from ..domain.commodities import get as get_commodity
from ..domain.lanes import Lane
from .geo import position_at
from .weather import WeatherStore, lane_stations, to_epoch, to_iso

K_AMB = 0.22
K_AC = 0.60
K_CA = 0.12
K_REF = 2.6
K_DOOR = 0.8
SOLAR_GAIN = 0.006      # deg C of equivalent ambient rise per W/m2
COIL_DELTA = 4.0        # supply coil sits this far below set-point
STEP_S = 600            # 10-minute reading interval
DOCK_SEAL = 0.35        # effective door-opening factor at a dock shelter/seal vs an open door on the road


def door_factor(phase: str, door_open: int | float) -> float:
    if not door_open:
        return 0.0
    return 1.0 if phase == "transit" else DOCK_SEAL

LOAD_NOMINAL_MIN = 45
DOCK_QUEUE_NOMINAL_MIN = 15
UNLOAD_MIN = 30

SCENARIOS: dict[str, dict] = {
    "nominal": {"label": "Healthy trip", "precool": 0.95},
    "poor_precool": {"label": "Cargo loaded warm", "precool": 0.30},
    "compressor_degradation": {"label": "Reefer unit degrades mid-route", "precool": 0.95,
                               "degrade": {"start_frac": 0.35, "ramp_h": 1.5, "floor": 0.20}},
    "door_ajar": {"label": "Door left open in transit", "precool": 0.95, "door": [{"at_frac": 0.5, "minutes": 45}]},
    "receiver_delay": {"label": "Long queue at receiver dock", "precool": 0.95,
                       "dock_queue_min": 210, "reefer_off_in_queue": True},
}


@dataclass
class Step:
    ts: float
    amb: float
    solar: float
    door: float          # 0 closed, DOCK_SEAL at a sealed dock, 1.0 open door in transit
    eff: float
    phase: str


def run_model(steps: list[Step], setpoint: float, t0: float) -> list[tuple[float, float]]:
    """Integrate the heat balance. Returns (return_air_temp, compressor_duty) per step."""
    t_air = t_cargo = t0
    out: list[tuple[float, float]] = []
    prev = None
    for s in steps:
        if prev is not None:
            dt_h_total = (s.ts - prev) / 3600.0
            n = max(1, math.ceil(dt_h_total / 0.1))
            h = dt_h_total / n
            for _ in range(n):
                amb_eff = s.amb + SOLAR_GAIN * s.solar
                k_amb = K_AMB + K_DOOR * s.door
                duty = min(1.0, max(0.0, (t_air - (setpoint - 0.5)) / 1.5)) * (1.0 if s.eff > 0 else 0.0)
                cool = K_REF * duty * s.eff * (t_air - (setpoint - COIL_DELTA))
                d_air = k_amb * (amb_eff - t_air) + K_AC * (t_cargo - t_air) - cool
                d_cargo = K_CA * (t_air - t_cargo)
                t_air += h * d_air
                t_cargo += h * d_cargo
        prev = s.ts
        duty_now = min(1.0, max(0.0, (t_air - (setpoint - 0.5)) / 1.5)) * (1.0 if s.eff > 0 else 0.0)
        out.append((t_air, duty_now))
    return out


def initial_temp(amb0: float, setpoint: float, precool: float) -> float:
    return amb0 + precool * (setpoint - amb0)


def _eff_at(sc: dict, t_h_since_depart: float, trip_h: float) -> float:
    d = sc.get("degrade")
    if not d:
        return 1.0
    start = d["start_frac"] * trip_h
    if t_h_since_depart <= start:
        return 1.0
    return max(d["floor"], 1.0 - (1.0 - d["floor"]) * min(1.0, (t_h_since_depart - start) / d["ramp_h"]))


def simulate_trip(lane: Lane, route: dict, depart_ts: str, commodity_code: str, scenario: str,
                  weather: WeatherStore, setpoint: float | None = None) -> dict:
    """Return {'frames': [...], 'events': [...], 'meta': {...}} for one shipment."""
    sc = SCENARIOS[scenario]
    com = get_commodity(commodity_code)
    sp = com.t_opt if setpoint is None else setpoint
    stations = lane_stations(lane)
    depart = to_epoch(depart_ts)
    load_min = sc.get("load_min", LOAD_NOMINAL_MIN)
    trip_s = route["duration_min"] * 60.0
    arrive = depart + trip_s
    queue_min = sc.get("dock_queue_min", DOCK_QUEUE_NOMINAL_MIN)
    unload_start = arrive + queue_min * 60
    end = unload_start + UNLOAD_MIN * 60
    start = depart - load_min * 60
    trip_h = trip_s / 3600.0
    door_windows = [(depart + w["at_frac"] * trip_s, depart + w["at_frac"] * trip_s + w["minutes"] * 60) for w in sc.get("door", [])]

    steps: list[Step] = []
    meta_pos: list[tuple[float, float]] = []
    meta_rh: list[float] = []
    t = start
    while t <= end + 1:
        if t < depart:
            phase, lat, lon = "loading", route["points"][0][0], route["points"][0][1]
        elif t < arrive:
            phase = "transit"
            km = route["cum"][-1] * (t - depart) / trip_s
            lat, lon = position_at(route["points"], route["cum"], km)
        else:
            phase, lat, lon = "unloading", route["points"][-1][0], route["points"][-1][1]
        w = weather.ambient(stations, lat, lon, t)
        if phase == "loading":
            door, eff = DOCK_SEAL, 1.0
        elif phase == "transit":
            door = 1.0 if any(a <= t < b for a, b in door_windows) else 0.0
            eff = _eff_at(sc, (t - depart) / 3600.0, trip_h)
        else:
            door = DOCK_SEAL if t >= unload_start else 0.0
            eff = 0.0 if (sc.get("reefer_off_in_queue") and t >= arrive + 30 * 60) else 1.0
        steps.append(Step(t, w["temp_c"], w["solar_wm2"], door, eff, phase))
        meta_pos.append((lat, lon))
        meta_rh.append(w["rh"])
        t += STEP_S

    t0 = initial_temp(steps[0].amb, sp, sc["precool"])
    sim = run_model(steps, sp, t0)
    frames = []
    for i, (s, (temp, duty), (lat, lon), rh) in enumerate(zip(steps, sim, meta_pos, meta_rh)):
        frames.append({"seq": i, "ts": to_iso(s.ts), "lat": round(lat, 5), "lon": round(lon, 5),
                       "temp_c": round(temp, 1), "setpoint_c": sp, "ambient_c": round(s.amb, 1),
                       "solar_wm2": round(s.solar, 0), "rh": round(rh, 0), "door_open": 1 if s.door > 0 else 0,
                       "duty": round(duty, 2), "phase": s.phase, "eff": round(s.eff, 3)})
    events = [
        {"ts": to_iso(start), "party": "shipper", "event": "loading_started", "note": "Loading began; reefer running."},
        {"ts": to_iso(depart), "party": "carrier", "event": "departed", "note": f"Departed {lane.origin.name}."},
        {"ts": to_iso(arrive), "party": "carrier", "event": "arrived", "note": f"Arrived {lane.dest.name}; waiting for dock."},
        {"ts": to_iso(unload_start), "party": "receiver", "event": "unloading_started", "note": "Doors opened for unloading."},
        {"ts": to_iso(end), "party": "receiver", "event": "unloaded", "note": "Cargo received."},
    ]
    for a, b in door_windows:
        events.append({"ts": to_iso(a), "party": "carrier", "event": "door_opened", "note": "Door opened in transit (no inspection logged)."})
        events.append({"ts": to_iso(b), "party": "carrier", "event": "door_closed", "note": "Door closed."})
    events.sort(key=lambda e: e["ts"])
    meta = {"depart_ts": to_iso(depart), "arrive_ts": to_iso(arrive), "unload_start_ts": to_iso(unload_start),
            "end_ts": to_iso(end), "setpoint_c": sp, "scenario": scenario, "trip_hours": round(trip_h, 2)}
    return {"frames": frames, "events": events, "meta": meta}


def divert_plan(plan: dict, cursor: int, hub_name: str, hub_lat: float, hub_lon: float, stations: list,
                weather: WeatherStore, decided_ts: str | None = None) -> dict:
    """Replace the un-driven remainder of a plan with a drive to a cold-storage hub, then a plug-in phase.

    Physics continue from the last driven frame (same reefer efficiency, real weather along the new path)."""
    from .geo import cumulative_km, densify, haversine_km      # local: avoid import cycle at module load

    frames = plan["frames"][:cursor]
    last = frames[-1]
    sp = last["setpoint_c"]
    base = [(last["lat"], last["lon"]), (hub_lat, hub_lon)]
    pts = densify(base, 2.0)
    cum = [c * 1.25 for c in cumulative_km(pts)]
    drive_s = cum[-1] / 42.0 * 3600.0
    t = to_epoch(last["ts"])
    eff = last.get("eff", 1.0)
    steps: list[Step] = []
    pos: list[tuple[float, float]] = []
    tt = t + STEP_S
    while tt < t + drive_s:
        lat, lon = position_at([list(p) for p in pts], cum, cum[-1] * (tt - t) / drive_s)
        w = weather.ambient(stations, lat, lon, tt)
        steps.append(Step(tt, w["temp_c"], w["solar_wm2"], 0.0, eff, "transit"))
        pos.append((lat, lon))
        tt += STEP_S
    arrive = t + drive_s
    n_dock = 4
    for k in range(n_dock):                     # plugged into cold-store shore power: full cooling, doors closed
        tk = arrive + (k + 1) * STEP_S
        w = weather.ambient(stations, hub_lat, hub_lon, tk)
        steps.append(Step(tk, w["temp_c"], w["solar_wm2"], 0.0, 1.0, "unloading"))
        pos.append((hub_lat, hub_lon))
    # continue physics from the last driven reading (air and cargo assumed equal: slight simplification)
    sim = run_model([Step(t, last["ambient_c"], last.get("solar_wm2") or 0.0, 0.0, eff, "transit")] + steps, sp, last["temp_c"])[1:]
    seq0 = last["seq"] + 1
    new = []
    for i, (s, (temp, duty), (lat, lon)) in enumerate(zip(steps, sim, pos)):
        new.append({"seq": seq0 + i, "ts": to_iso(s.ts), "lat": round(lat, 5), "lon": round(lon, 5), "temp_c": round(temp, 1),
                    "setpoint_c": sp, "ambient_c": round(s.amb, 1), "solar_wm2": round(s.solar, 0), "rh": last.get("rh"),
                    "door_open": 0, "duty": round(duty, 2), "phase": s.phase, "eff": round(s.eff, 3)})
    keep_events = [e for e in plan["events"] if e["ts"] <= last["ts"]]
    first_unload = next(f for f in new if f["phase"] == "unloading")
    keep_events += [
        {"ts": to_iso(arrive), "party": "carrier", "event": "arrived", "note": f"Arrived at diversion hub {hub_name}."},
        {"ts": first_unload["ts"], "party": "receiver", "event": "unloading_started", "note": "Reefer plugged into cold-store power."},
        {"ts": new[-1]["ts"], "party": "receiver", "event": "unloaded", "note": f"Cargo accepted into cold storage at {hub_name}."},
    ]
    keep_events.sort(key=lambda e: e["ts"])
    meta = dict(plan["meta"], diverted_to=hub_name, arrive_ts=to_iso(arrive), end_ts=new[-1]["ts"])
    return {"frames": frames + new, "events": keep_events, "meta": meta}
