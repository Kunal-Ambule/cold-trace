"""Shelf-life burn and value-at-risk. Pure functions: easy to test, no I/O."""
from __future__ import annotations

from ..domain.commodities import Commodity
from .weather import to_epoch

MAX_INTERVAL_H = 1.0     # never extrapolate a reading across more than one hour of silence

LEVELS = [(0.001, "low"), (0.005, "moderate"), (0.02, "high")]   # loss fraction thresholds (critical above)


def level_for(loss_frac: float) -> str:
    for limit, name in LEVELS:
        if loss_frac < limit:
            return name
    return "critical"


def burn_rate_per_h(c: Commodity, temp_c: float) -> float:
    """Fraction of value lost per hour at this temperature (beyond what the allowed band would cost)."""
    return interval_burn(c, temp_c, 1.0)


def interval_burn(c: Commodity, temp_c: float, dt_h: float) -> float:
    if dt_h <= 0:
        return 0.0
    if c.mode == "budget":
        out = temp_c > c.t_max or temp_c < c.t_min
        return (dt_h * 60.0) / c.budget_min if out and c.budget_min > 0 else 0.0
    burn = 0.0
    if temp_c > c.t_max:
        r_now = c.q10 ** ((temp_c - c.t_opt) / 10.0)
        r_cap = c.q10 ** ((c.t_max - c.t_opt) / 10.0)
        burn += (r_now - r_cap) * dt_h / (c.shelf_days * 24.0)
    if c.chill_sensitive and temp_c < c.t_min:
        burn += (c.t_min - temp_c) * dt_h * c.chill_coeff
    return burn


def interval_burns(c: Commodity, ts: list[float], temps: list[float]) -> list[float]:
    """Burn attributed to each reading (interval starting at that reading)."""
    out: list[float] = []
    for i, t in enumerate(temps):
        dt = min((ts[i + 1] - ts[i]) / 3600.0, MAX_INTERVAL_H) if i + 1 < len(ts) else 0.0
        out.append(interval_burn(c, t, dt))
    return out


def assess(c: Commodity, readings: list[dict], declared_value: float) -> dict:
    """Summarise exposure for a shipment from its readings (ordered by seq)."""
    if not readings:
        return {"n": 0, "loss_frac": 0.0, "loss_pct": 0.0, "value_at_risk_inr": 0.0, "risk_level": "low",
                "minutes_out_of_band": 0.0, "minutes_above": 0.0, "minutes_below": 0.0,
                "max_temp_c": None, "min_temp_c": None, "first_breach_ts": None, "burn_pct_per_h": 0.0,
                "current_temp_c": None}
    ts = [to_epoch(r["ts"]) for r in readings]
    temps = [r["temp_c"] for r in readings]
    burns = interval_burns(c, ts, temps)
    above = below = 0.0
    first = None
    for i, t in enumerate(temps):
        dt = min((ts[i + 1] - ts[i]) / 60.0, MAX_INTERVAL_H * 60) if i + 1 < len(ts) else 0.0
        if t > c.t_max:
            above += dt
        elif t < c.t_min:
            below += dt
        if first is None and (t > c.t_max or t < c.t_min):
            first = readings[i]["ts"]
    loss = min(1.0, sum(burns))
    return {
        "n": len(readings), "loss_frac": loss, "loss_pct": round(loss * 100, 2),
        "value_at_risk_inr": round(loss * declared_value, 2), "risk_level": level_for(loss),
        "minutes_out_of_band": round(above + below, 1), "minutes_above": round(above, 1), "minutes_below": round(below, 1),
        "max_temp_c": max(temps), "min_temp_c": min(temps), "first_breach_ts": first,
        "burn_pct_per_h": round(burn_rate_per_h(c, temps[-1]) * 100, 3), "current_temp_c": temps[-1],
    }
