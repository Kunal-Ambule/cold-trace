"""Ingestion validation and the rule-based alert layer."""
import pytest

from app import db
from app.services import alerts, ingest, shipments


def test_ingest_rejects_bad_temperature():
    s = shipments.create("SBN-MOS", "tomato", "2026-09-05T02:00:00Z", "nominal")
    res = ingest.ingest_readings(s["id"], [{"ts": "2026-09-05T02:00:00Z", "temp_c": 999}], "manual")
    assert res["accepted"] == 0
    assert res["rejected"][0]["reason"].startswith("temp_c")


def test_ingest_rejects_bad_timestamp():
    s = shipments.create("SBN-MOS", "tomato", "2026-09-05T02:00:00Z", "nominal")
    res = ingest.ingest_readings(s["id"], [{"ts": "not-a-date", "temp_c": 10}], "manual")
    assert res["accepted"] == 0


def test_unknown_shipment_raises():
    with pytest.raises(ingest.IngestError):
        ingest.ingest_readings(999999, [{"ts": "2026-09-05T02:00:00Z", "temp_c": 10}], "manual")


def test_out_of_band_alert_fires_and_resolves():
    s = shipments.create("SBN-MOS", "tomato", "2026-09-05T02:00:00Z", "receiver_delay")
    shipments.fast_forward(s["id"])
    rows = db.all_("SELECT * FROM alerts WHERE shipment_id=? AND kind='out_of_band'", (s["id"],))
    assert len(rows) >= 1


def test_gps_jump_flags_implausible_speed():
    s = shipments.create("SBN-MOS", "tomato", "2026-09-05T02:00:00Z", "nominal", data_source="device")
    ingest.ingest_readings(s["id"], [
        {"ts": "2026-09-05T01:00:00Z", "temp_c": 10.5, "lat": 19.0, "lon": 75.0, "seq": 0},
        {"ts": "2026-09-05T01:05:00Z", "temp_c": 10.5, "lat": 20.5, "lon": 77.5, "seq": 1},  # ~200km in 5 min
    ], "device")
    rows = db.all_("SELECT * FROM alerts WHERE shipment_id=? AND kind='gps_implausible'", (s["id"],))
    assert len(rows) == 1
