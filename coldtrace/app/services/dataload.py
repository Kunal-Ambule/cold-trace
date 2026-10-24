"""Loading REAL data: Agmarknet prices (bundled CSV / data.gov.in API) and ERA5 weather (Open-Meteo)."""
from __future__ import annotations

import csv
import logging
import time
from pathlib import Path

import httpx

from .. import db
from ..config import ROOT, settings
from ..domain.lanes import LANES
from .weather import lane_stations, store

log = logging.getLogger("coldtrace.data")

PRICES_CSV = ROOT / "data" / "agmarknet_cleaned.csv"
OPEN_METEO = "https://archive-api.open-meteo.com/v1/archive"
DATA_GOV = "https://api.data.gov.in/resource/9ef84268-d588-465a-a308-a864a43d0070"


def _f(x: str | None) -> float | None:
    try:
        return float(x) if x not in (None, "") else None
    except ValueError:
        return None


def _b(x: str | None) -> int:
    return 1 if str(x).strip().lower() in {"true", "1", "yes"} else 0


def load_prices_csv(path: Path = PRICES_CSV, replace: bool = True) -> int:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    with db.tx() as c:
        if replace:
            c.execute("DELETE FROM market_prices")
        c.executemany(
            "INSERT INTO market_prices(state,district,market,commodity,variety,grade,arrival_date,min_price,max_price,modal_price,price_outlier,unit_error) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            [(r["State"], r["District"], r["Market"], r["Commodity"], r.get("Variety"), r.get("Grade"), r["Arrival_Date"],
              _f(r["Min_Price"]), _f(r["Max_Price"]), _f(r["Modal_Price"]),
              _b(r.get("Price_Outlier_Flag")), _b(r.get("Suspected_Unit_Error"))) for r in rows])
    return len(rows)


def refresh_prices_from_api(state: str | None = None, limit: int = 1000) -> int:
    """Optional: pull the latest daily prices from data.gov.in (needs DATA_GOV_IN_API_KEY)."""
    if not settings.data_gov_api_key:
        raise RuntimeError("Set DATA_GOV_IN_API_KEY (free key from data.gov.in) to refresh prices.")
    params = {"api-key": settings.data_gov_api_key, "format": "json", "limit": limit}
    if state:
        params["filters[State]"] = state
    r = httpx.get(DATA_GOV, params=params, timeout=60)
    r.raise_for_status()
    recs = r.json().get("records", [])
    with db.tx() as c:
        c.execute("DELETE FROM market_prices")
        c.executemany(
            "INSERT INTO market_prices(state,district,market,commodity,variety,grade,arrival_date,min_price,max_price,modal_price) VALUES(?,?,?,?,?,?,?,?,?,?)",
            [(x.get("state"), x.get("district"), x.get("market"), x.get("commodity"), x.get("variety"), x.get("grade"),
              x.get("arrival_date"), _f(x.get("min_price")), _f(x.get("max_price")), _f(x.get("modal_price"))) for x in recs])
    return len(recs)


def fetch_weather(start: str | None = None, end: str | None = None, only_missing: bool = True) -> dict:
    """Download hourly ERA5 reanalysis (temperature, humidity, precipitation, shortwave radiation) for every lane station."""
    start, end = start or settings.weather_start, end or settings.weather_end
    stations: dict[str, tuple[float, float, str]] = {}
    for lane in LANES:
        for key, lat, lon, name in lane_stations(lane):
            stations.setdefault(key, (lat, lon, name))
    ok = failed = 0
    for key, (lat, lon, name) in stations.items():
        have = db.one("SELECT COUNT(*) n, MIN(ts) a, MAX(ts) b FROM weather_hourly WHERE station_key=?", (key,))
        if only_missing and have["n"] and have["a"][:10] <= start and have["b"][:10] >= end:
            ok += 1
            continue
        try:
            r = httpx.get(OPEN_METEO, timeout=60, params={
                "latitude": lat, "longitude": lon, "start_date": start, "end_date": end,
                "hourly": "temperature_2m,relative_humidity_2m,precipitation,shortwave_radiation", "timezone": "UTC"})
            r.raise_for_status()
            h = r.json()["hourly"]
            rows = [(key, t + ":00Z", tc, rh, pr, sw) for t, tc, rh, pr, sw in
                    zip(h["time"], h["temperature_2m"], h["relative_humidity_2m"], h["precipitation"], h["shortwave_radiation"])
                    if tc is not None]
            with db.tx() as c:
                c.execute("INSERT OR REPLACE INTO weather_stations(key,name,lat,lon) VALUES(?,?,?,?)", (key, name, lat, lon))
                c.execute("DELETE FROM weather_hourly WHERE station_key=?", (key,))
                c.executemany("INSERT OR REPLACE INTO weather_hourly(station_key,ts,temp_c,rh,solar_wm2,precip_mm) "
                              "VALUES(?,?,?,?,?,?)", [(k, ts, tc, rh, sw, pr) for k, ts, tc, rh, pr, sw in rows])
            ok += 1
            log.info("weather %s (%s): %d hours", key, name, len(rows))
            time.sleep(0.4)
        except Exception as e:  # noqa: BLE001
            failed += 1
            log.error("weather fetch failed for %s: %s", key, e)
    store.clear()
    return {"stations": len(stations), "ok": ok, "failed": failed, "window": [start, end]}


def weather_status() -> dict:
    r = db.one("SELECT COUNT(DISTINCT station_key) s, COUNT(*) n, MIN(ts) a, MAX(ts) b FROM weather_hourly")
    total = len({k for lane in LANES for k, *_ in lane_stations(lane)})
    return {"stations_loaded": r["s"], "stations_needed": total, "hours": r["n"], "from": r["a"], "to": r["b"],
            "ready": r["s"] >= total and total > 0}
