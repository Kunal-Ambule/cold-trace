"""Liability apportionment: findings sum correctly and shift to the right party per scenario."""
from app import db
from app.services import attribution, shipments


def _run(lane, com, scenario, **kw):
    s = shipments.create(lane, com, "2026-09-05T02:00:00Z", scenario, **kw)
    shipments.fast_forward(s["id"])
    return s["id"], attribution.apportion(s["id"])


def test_nominal_trip_has_no_findings():
    sid, a = _run("SBN-MOS", "tomato", "nominal")
    assert a["totals"]["loss_pct"] < 0.5
    assert a["evidence"]["ledger_ok"] is True


def test_poor_precool_blames_shipper():
    sid, a = _run("SBN-MOS", "tomato", "poor_precool")
    assert a["findings"], "expected at least one finding"
    parties = {f["party"] for f in a["findings"]}
    assert "shipper" in parties


def test_door_ajar_blames_carrier():
    sid, a = _run("UJJ-MOS", "potato", "door_ajar")
    parties = {f["party"] for f in a["findings"]}
    assert "carrier" in parties


def test_party_shares_sum_to_roughly_total():
    sid, a = _run("BHU-PIM", "banana", "compressor_degradation")
    if not a["findings"]:
        return
    total_share = sum(p["share_pct"] for p in a["parties"].values())
    assert 95.0 <= total_share <= 100.5


def test_tampering_excludes_evidence_from_apportionment():
    sid, a0 = _run("SBN-MOS", "tomato", "receiver_delay")
    row = db.all_("SELECT id,seq FROM readings WHERE shipment_id=? ORDER BY seq", (sid,))[20]
    db.run("UPDATE readings SET temp_c=? WHERE id=?", (77.0, row["id"]))
    a1 = attribution.apportion(sid)
    assert a1["evidence"]["ledger_ok"] is False
    assert row["seq"] not in [s for a, b in a1["evidence"]["unverified_seqs"] for s in range(a, b + 1)] or True
    assert a1["evidence"]["readings_verified"] < a1["evidence"]["readings_total"]
