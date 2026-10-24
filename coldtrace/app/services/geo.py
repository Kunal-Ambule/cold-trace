from __future__ import annotations

import math
from bisect import bisect_left

R_EARTH_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R_EARTH_KM * math.asin(math.sqrt(a))


def densify(points: list[tuple[float, float]], step_km: float = 2.0) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = [points[0]]
    for (la1, lo1), (la2, lo2) in zip(points, points[1:]):
        d = haversine_km(la1, lo1, la2, lo2)
        n = max(1, int(d // step_km))
        for i in range(1, n + 1):
            f = i / n
            out.append((la1 + (la2 - la1) * f, lo1 + (lo2 - lo1) * f))
    return out


def cumulative_km(points: list[tuple[float, float]]) -> list[float]:
    cum = [0.0]
    for (la1, lo1), (la2, lo2) in zip(points, points[1:]):
        cum.append(cum[-1] + haversine_km(la1, lo1, la2, lo2))
    return cum


def position_at(points: list[list[float]], cum: list[float], km: float) -> tuple[float, float]:
    if km <= 0:
        return points[0][0], points[0][1]
    if km >= cum[-1]:
        return points[-1][0], points[-1][1]
    i = bisect_left(cum, km)
    f = (km - cum[i - 1]) / max(cum[i] - cum[i - 1], 1e-9)
    la1, lo1 = points[i - 1]
    la2, lo2 = points[i]
    return la1 + (la2 - la1) * f, lo1 + (lo2 - lo1) * f


def nearest_index(points: list[list[float]], lat: float, lon: float) -> int:
    best, bi = 1e18, 0
    for i, (la, lo) in enumerate(points):
        d = (la - lat) ** 2 + ((lo - lon) * math.cos(math.radians(lat))) ** 2
        if d < best:
            best, bi = d, i
    return bi
