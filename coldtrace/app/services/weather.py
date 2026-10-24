"""Real weather (ERA5 reanalysis via Open-Meteo) sampled at stations along each lane."""
from __future__ import annotations

import threading
from datetime import datetime, timezone

import numpy as np

from .. import db
from ..domain.lanes import Lane
from .geo import haversine_km


class WeatherUnavailable(RuntimeError):
    pass


def station_key(lat: float, lon: float) -> str:
    return f"{lat:.2f},{lon:.2f}"


def lane_stations(lane: Lane) -> list[tuple[str, float, float, str]]:
    seen: dict[str, tuple[str, float, float, str]] = {}
    for p in lane.path:
        seen.setdefault(station_key(p.lat, p.lon), (station_key(p.lat, p.lon), p.lat, p.lon, p.name))
    return list(seen.values())


def to_epoch(ts: str) -> float:
    """ISO timestamp (UTC, 'Z' or naive) -> epoch seconds."""
    d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.timestamp()


def to_iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class WeatherStore:
    """In-memory hourly series per station with linear time interpolation."""

    def __init__(self) -> None:
        self._series: dict[str, dict[str, np.ndarray]] = {}
        self._lock = threading.Lock()

    def clear(self) -> None:
        with self._lock:
            self._series.clear()

    def _load(self, key: str) -> dict[str, np.ndarray]:
        with self._lock:
            if key in self._series:
                return self._series[key]
        rows = db.all_("SELECT ts,temp_c,rh,solar_wm2,precip_mm FROM weather_hourly WHERE station_key=? ORDER BY ts", (key,))
        if not rows:
            raise WeatherUnavailable(f"No weather for station {key}. Run: python scripts/fetch_data.py --weather")
        t = np.array([to_epoch(r["ts"]) for r in rows])
        s = {"t": t}
        for col in ("temp_c", "rh", "solar_wm2", "precip_mm"):
            s[col] = np.array([np.nan if r[col] is None else r[col] for r in rows], dtype=float)
        with self._lock:
            self._series[key] = s
        return s

    def window(self, keys: list[str]) -> tuple[float, float]:
        lo, hi = -1e18, 1e18
        for k in keys:
            t = self._load(k)["t"]
            lo, hi = max(lo, float(t[0])), min(hi, float(t[-1]))
        return lo, hi

    def at(self, key: str, epoch: float) -> dict[str, float]:
        s = self._load(key)
        if epoch < s["t"][0] - 1 or epoch > s["t"][-1] + 1:
            raise WeatherUnavailable(f"{to_iso(epoch)} is outside the downloaded weather window for {key}")
        return {c: float(np.interp(epoch, s["t"], s[c])) for c in ("temp_c", "rh", "solar_wm2", "precip_mm")}

    def ambient(self, stations: list[tuple[str, float, float, str]], lat: float, lon: float, epoch: float) -> dict[str, float]:
        """Inverse-distance blend of the two nearest stations."""
        ranked = sorted(stations, key=lambda st: haversine_km(lat, lon, st[1], st[2]))[:2]
        ws = [1.0 / (haversine_km(lat, lon, st[1], st[2]) + 5.0) for st in ranked]
        vals = [self.at(st[0], epoch) for st in ranked]
        tot = sum(ws)
        return {c: sum(w * v[c] for w, v in zip(ws, vals)) / tot for c in vals[0]}


store = WeatherStore()
