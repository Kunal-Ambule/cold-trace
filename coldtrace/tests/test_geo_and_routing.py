"""Geometry helpers and the waypoint-fallback router (used whenever OSRM is unreachable)."""
from app.domain.lanes import LANES
from app.services import routing
from app.services.geo import cumulative_km, densify, haversine_km, position_at


def test_haversine_known_distance():
    # Mumbai to Pune, roughly 120-150 km straight-line
    d = haversine_km(19.0760, 72.8777, 18.5204, 73.8567)
    assert 110 < d < 160


def test_densify_preserves_endpoints():
    pts = [(0.0, 0.0), (1.0, 1.0)]
    out = densify(pts, step_km=50)
    assert out[0] == pts[0]
    assert abs(out[-1][0] - pts[-1][0]) < 1e-9


def test_position_at_interpolates_along_path():
    pts = [[0.0, 0.0], [0.0, 1.0]]
    cum = cumulative_km([(p[0], p[1]) for p in pts])
    lat, lon = position_at(pts, cum, cum[-1] / 2)
    assert 0.0 <= lon <= 1.0


def test_fallback_route_has_positive_distance_for_every_lane():
    for lane in LANES:
        r = routing._fallback(lane)
        assert r["distance_km"] > 0
        assert r["duration_min"] > 0
        assert len(r["points"]) >= 2
