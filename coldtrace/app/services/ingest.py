"""Single entry point for readings and custody events. Devices, the driver PWA and the replay engine
all go through here, so validation, idempotency, the ledger and detection behave identically."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from .. import db
from . import alerts, bus, ledger
from .weather import to_epoch

log = logging.getLogger("coldtrace.ingest")

VALID_SOURCES = {"device", "twin", "manual"}


class IngestError(ValueError):
    pass


def _validate(r: dict) -> None:
    if "temp_c" not in r or r["temp_c"] is None:
        raise IngestError("temp_c is required")
    if not -40.0 <= float(r["temp_c"]) <= 80.0:
        raise IngestError("temp_c outside sensor range -40..80")
    if "ts" not in r:
        raise IngestError("ts is required")
    try:
        to_epoch(r["ts"])
    except Exception as e:  # noqa: BLE001
        raise IngestError(f"bad ts: {e}") from e
    if r.get("lat") is not None and not -90 <= float(r["lat"]) <= 90:
        raise IngestError("lat out of range")
    if r.get("lon") is not None and not -180 <= float(r["lon"]) <= 180:
        raise IngestError("lon out of range")


def ingest_readings(shipment_id: int, readings: list[dict], source: str, actor: str | None = None, publish: bool = True) -> dict:
    ship = db.one("SELECT * FROM shipments WHERE id=?", (shipment_id,))
    if not ship:
        raise IngestError("unknown shipment")
    if source not in VALID_SOURCES:
        raise IngestError("bad source")
    accepted = dup = 0
    rejected: list[dict] = []
    last_sealed = db.one("SELECT COALESCE(MAX(last_seq),-1) m FROM ledger_blocks WHERE shipment_id=?", (shipment_id,))["m"]
    with db.tx() as c:
        nxt = c.execute("SELECT COALESCE(MAX(seq),-1)+1 n FROM readings WHERE shipment_id=?", (shipment_id,)).fetchone()["n"]
        for i, r in enumerate(readings):
            try:
                _validate(r)
                seq = r.get("seq")
                if seq is None:
                    seq = nxt
                idem = r.get("idem_key") or (f"{shipment_id}:{seq}" if r.get("seq") is not None else f"{shipment_id}:{source}:{r['ts']}")
                if c.execute("SELECT 1 FROM readings WHERE idem_key=?", (idem,)).fetchone():
                    dup += 1
                    continue
                if c.execute("SELECT 1 FROM readings WHERE shipment_id=? AND seq=?", (shipment_id, seq)).fetchone():
                    dup += 1
                    continue
                if seq <= last_sealed:
                    raise IngestError(f"seq {seq} is at or below the sealed ledger height ({last_sealed}); resend in order")
                c.execute(
                    "INSERT INTO readings(shipment_id,seq,ts,lat,lon,temp_c,setpoint_c,ambient_c,solar_wm2,rh,door_open,duty,phase,source,idem_key) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (shipment_id, seq, r["ts"], r.get("lat"), r.get("lon"), float(r["temp_c"]),
                     r.get("setpoint_c", ship["setpoint_c"]), r.get("ambient_c"), r.get("solar_wm2"), r.get("rh"),
                     1 if r.get("door_open") else 0, r.get("duty"), r.get("phase") or "transit", source, idem))
                accepted += 1
                nxt = max(nxt, seq + 1)
            except IngestError as e:
                rejected.append({"index": i, "reason": str(e)})
            except Exception as e:  # noqa: BLE001
                rejected.append({"index": i, "reason": f"{type(e).__name__}: {e}"})
        if ship["status"] in ("scheduled",) and accepted:
            c.execute("UPDATE shipments SET status='in_transit' WHERE id=?", (shipment_id,))
    if accepted:
        ledger.seal(shipment_id)
        new_alerts = alerts.evaluate(shipment_id)
        if publish:
            last = db.one("SELECT * FROM readings WHERE shipment_id=? ORDER BY seq DESC LIMIT 1", (shipment_id,))
            bus.publish("reading", {"shipment_id": shipment_id, "reading": last, "summary": alerts.summarize(shipment_id)})
    return {"accepted": accepted, "duplicates": dup, "rejected": rejected}


def add_event(shipment_id: int, ts: str, party: str, event: str, note: str | None = None, actor: str | None = None,
              transcript: str | None = None, lat: float | None = None, lon: float | None = None,
              temp_c: float | None = None, source: str = "manual", idem_key: str | None = None) -> int | None:
    if idem_key and db.one("SELECT id FROM custody_events WHERE idem_key=?", (idem_key,)):
        return None
    eid = db.run(
        "INSERT INTO custody_events(shipment_id,ts,party,actor,event,note,transcript,lat,lon,temp_c,source,idem_key) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (shipment_id, ts, party, actor, event, note, transcript, lat, lon, temp_c, source, idem_key))
    bus.publish("event", {"shipment_id": shipment_id, "id": eid, "ts": ts, "party": party, "event": event, "note": note})
    return eid


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
