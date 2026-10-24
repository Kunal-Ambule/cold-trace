"""Feature engineering shared by training and live inference (one code path = no train/serve skew)."""
from __future__ import annotations

import numpy as np

from ..domain.commodities import Commodity

FEATURES = ["dev_sp", "dev_max", "dev_min", "d1", "d3", "d6", "std6", "amb_minus_t", "solar", "duty",
            "door", "ph_load", "ph_transit", "ph_unload", "mins_door", "band_w"]
HORIZON = 6            # readings ahead (6 x 10 min = 60 min)
ANOMALY_COLS = [FEATURES.index(c) for c in ("dev_sp", "d1", "d3", "std6", "duty", "amb_minus_t")]


def trip_features(rows: list[dict], com: Commodity) -> np.ndarray:
    n = len(rows)
    t = np.array([r["temp_c"] for r in rows], dtype=float)
    sp = np.array([r.get("setpoint_c") if r.get("setpoint_c") is not None else com.t_opt for r in rows], dtype=float)
    amb = np.array([r.get("ambient_c") if r.get("ambient_c") is not None else np.nan for r in rows], dtype=float)
    amb = np.where(np.isnan(amb), t, amb)
    solar = np.array([r.get("solar_wm2") or 0.0 for r in rows], dtype=float)
    duty = np.array([r.get("duty") if r.get("duty") is not None else 0.0 for r in rows], dtype=float)
    door = np.array([1.0 if r.get("door_open") else 0.0 for r in rows])
    ph = [r.get("phase") or "transit" for r in rows]

    def lag(k: int) -> np.ndarray:
        idx = np.maximum(np.arange(n) - k, 0)
        return t - t[idx]

    std6 = np.array([np.std(t[max(0, i - 5):i + 1]) for i in range(n)])
    since = np.zeros(n)
    last = -1e9
    for i in range(n):
        if door[i]:
            last = i
        since[i] = min((i - last) * 10.0, 120.0)
    X = np.column_stack([
        t - sp, t - com.t_max, t - com.t_min, lag(1), lag(3), lag(6), std6, amb - t, solar, duty, door,
        [p == "loading" for p in ph], [p == "transit" for p in ph], [p == "unloading" for p in ph],
        since, np.full(n, com.t_max - com.t_min),
    ]).astype(float)
    return X


def future_max_delta(temps: list[float]) -> np.ndarray:
    """Target: max temperature over the next HORIZON readings minus current temperature."""
    t = np.array(temps, dtype=float)
    n = len(t)
    out = np.zeros(n)
    for i in range(n):
        seg = t[i + 1:i + 1 + HORIZON]
        out[i] = (seg.max() - t[i]) if len(seg) else 0.0
    return out
