"""TEST-ONLY synthetic weather. The application never uses this; it exists so the test-suite runs offline.
Production data comes from scripts/fetch_data.py (real ERA5 reanalysis via Open-Meteo)."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from app import db
from app.domain.lanes import LANES
from app.services.weather import lane_stations, store


def seed_fake_weather(start="2026-09-01", days=14, base=27.0, amp=8.0):
    t0 = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
    seen = set()
    rows = []
    for lane in LANES:
        for key, lat, lon, name in lane_stations(lane):
            if key in seen:
                continue
            seen.add(key)
            db.run("INSERT OR REPLACE INTO weather_stations(key,name,lat,lon) VALUES(?,?,?,?)", (key, name, lat, lon))
            for h in range(days * 24):
                t = t0 + timedelta(hours=h)
                ist = (t.hour + 5.5) % 24
                temp = base + amp * math.sin((ist - 9) / 24 * 2 * math.pi) + (lat - 18) * -0.2
                sw = max(0.0, 850 * math.sin((ist - 6) / 12 * math.pi)) if 6 < ist < 18 else 0.0
                rows.append((key, t.strftime("%Y-%m-%dT%H:%M:%SZ"), temp, 55.0, sw, 0.0))
    with db.tx() as c:
        c.executemany("INSERT OR REPLACE INTO weather_hourly(station_key,ts,temp_c,rh,solar_wm2,precip_mm) VALUES(?,?,?,?,?,?)", rows)
    store.clear()
