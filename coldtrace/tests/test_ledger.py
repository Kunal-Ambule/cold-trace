"""Tamper-evident ledger: sealing, verification, and tamper detection (the 'false transit logs' requirement)."""
from app import db
from app.services import ingest, ledger, shipments


def _make_shipment():
    s = shipments.create("SBN-MOS", "tomato", "2026-09-05T02:00:00Z", "nominal")
    return s["id"]


def test_seal_and_verify_clean_trip():
    sid = _make_shipment()
    shipments.fast_forward(sid)
    v = ledger.verify(sid)
    assert v["ok"] is True
    assert v["n_blocks"] > 0
    assert v["tampered_seqs"] == []


def test_detects_value_tamper():
    sid = _make_shipment()
    shipments.fast_forward(sid)
    row = db.all_("SELECT id,seq FROM readings WHERE shipment_id=? ORDER BY seq", (sid,))[10]
    db.run("UPDATE readings SET temp_c=? WHERE id=?", (99.0, row["id"]))
    v = ledger.verify(sid)
    assert v["ok"] is False
    assert row["seq"] in v["tampered_seqs"]


def test_detects_deleted_reading():
    sid = _make_shipment()
    shipments.fast_forward(sid)
    row = db.all_("SELECT id,seq FROM readings WHERE shipment_id=? ORDER BY seq", (sid,))[5]
    db.run("DELETE FROM readings WHERE id=?", (row["id"],))
    v = ledger.verify(sid)
    assert v["ok"] is False
    assert row["seq"] in v["tampered_seqs"]


def test_idempotent_ingest_rejects_duplicate_seq():
    sid = _make_shipment()
    r = db.all_("SELECT * FROM readings WHERE shipment_id=? ORDER BY seq LIMIT 1", (sid,))
    # ingest a fresh reading, then try to replay the exact same seq again
    res1 = ingest.ingest_readings(sid, [{"ts": "2026-09-05T01:00:00Z", "temp_c": 10.0, "seq": 500}], "manual")
    assert res1["accepted"] == 1
    res2 = ingest.ingest_readings(sid, [{"ts": "2026-09-05T01:00:00Z", "temp_c": 10.0, "seq": 500}], "manual")
    assert res2["accepted"] == 0 and res2["duplicates"] == 1


def test_first_reading_seq_zero_is_accepted():
    """Regression test for an off-by-one: seq 0 must not be rejected as 'at or below sealed height'."""
    s = shipments.create("SBN-MOS", "tomato", "2026-09-05T02:00:00Z", "nominal", data_source="device")
    res = ingest.ingest_readings(s["id"], [{"ts": "2026-09-05T01:00:00Z", "temp_c": 10.0, "seq": 0}], "twin")
    assert res["accepted"] == 1
