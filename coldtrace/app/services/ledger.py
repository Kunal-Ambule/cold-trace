"""Tamper-evident hash chain over sensor readings.

Every 6 readings are sealed into a block:
    leaf_i      = SHA256(canonical_json(reading_i))
    payload     = SHA256(leaf_1 || ... || leaf_n)
    block_hash  = SHA256(prev_block_hash || payload || height || first_seq || last_seq)
Changing, deleting or inserting any reading changes its leaf, hence the payload and every later block
hash. `verify` recomputes everything from the live readings table and reports the first broken block and
the exact reading sequence numbers that no longer match. This addresses the brief's "false transit logs".
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from .. import db

BATCH = 6
GENESIS = "0" * 64
FIELDS = ("seq", "ts", "lat", "lon", "temp_c", "setpoint_c", "ambient_c", "solar_wm2", "rh", "door_open", "duty", "phase", "source")


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def canonical(r: dict) -> str:
    return json.dumps({k: r.get(k) for k in FIELDS}, sort_keys=True, separators=(",", ":"))


def leaf(r: dict) -> str:
    return _sha(canonical(r))


def _block_hash(prev: str, payload: str, height: int, first: int, last: int) -> str:
    return _sha(f"{prev}|{payload}|{height}|{first}|{last}")


def seal(shipment_id: int, force: bool = False) -> int:
    """Seal unsealed readings into blocks. Returns number of blocks created."""
    created = 0
    with db.tx() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT * FROM readings WHERE shipment_id=? AND block_id IS NULL ORDER BY seq", (shipment_id,))]
        last = c.execute("SELECT height, block_hash FROM ledger_blocks WHERE shipment_id=? ORDER BY height DESC LIMIT 1",
                         (shipment_id,)).fetchone()
        height = last["height"] if last else 0
        prev = last["block_hash"] if last else GENESIS
        i = 0
        while len(rows) - i >= BATCH or (force and len(rows) - i > 0):
            chunk = rows[i:i + BATCH]
            i += len(chunk)
            leaves = [leaf(r) for r in chunk]
            payload = _sha("".join(leaves))
            height += 1
            bh = _block_hash(prev, payload, height, chunk[0]["seq"], chunk[-1]["seq"])
            cur = c.execute(
                "INSERT INTO ledger_blocks(shipment_id,height,first_seq,last_seq,prev_hash,payload_hash,block_hash,leaf_hashes,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (shipment_id, height, chunk[0]["seq"], chunk[-1]["seq"], prev, payload, bh,
                 json.dumps([[r["seq"], lf] for r, lf in zip(chunk, leaves)]),
                 datetime.now(timezone.utc).isoformat()))
            c.executemany("UPDATE readings SET block_id=? WHERE id=?", [(cur.lastrowid, r["id"]) for r in chunk])
            prev = bh
            created += 1
    return created


def verify(shipment_id: int) -> dict:
    blocks = db.all_("SELECT * FROM ledger_blocks WHERE shipment_id=? ORDER BY height", (shipment_id,))
    pending = db.one("SELECT COUNT(*) n FROM readings WHERE shipment_id=? AND block_id IS NULL", (shipment_id,))["n"]
    prev = GENESIS
    report, first_break = [], None
    tampered: list[int] = []
    for b in blocks:
        rows = db.all_("SELECT * FROM readings WHERE shipment_id=? AND seq BETWEEN ? AND ? ORDER BY seq",
                       (shipment_id, b["first_seq"], b["last_seq"]))
        stored = {int(sq): h for sq, h in json.loads(b["leaf_hashes"])}
        by_seq = {r["seq"]: leaf(r) for r in rows}
        reasons: list[str] = []
        bad_seqs: list[int] = []
        if b["prev_hash"] != prev:
            reasons.append("chain link broken (a previous block was altered or removed)")
        missing = [sq for sq in stored if sq not in by_seq]
        added = [sq for sq in by_seq if sq not in stored]
        changed = [sq for sq, h in by_seq.items() if sq in stored and stored[sq] != h]
        if missing:
            reasons.append(f"{len(missing)} reading(s) deleted")
        if added:
            reasons.append(f"{len(added)} reading(s) inserted")
        if changed:
            reasons.append("reading values changed after sealing")
        bad_seqs = sorted(set(missing + added + changed))
        ordered = [by_seq[sq] for sq in sorted(by_seq)]
        if not (missing or added or changed) and _sha("".join(ordered)) != b["payload_hash"]:
            reasons.append("payload hash mismatch")
        bh = _block_hash(b["prev_hash"], b["payload_hash"], b["height"], b["first_seq"], b["last_seq"])
        if bh != b["block_hash"]:
            reasons.append("block hash mismatch (block record edited)")
        ok = not reasons
        if not ok:
            tampered.extend(bad_seqs)
            first_break = first_break or b["height"]
        report.append({"height": b["height"], "first_seq": b["first_seq"], "last_seq": b["last_seq"],
                       "block_hash": b["block_hash"], "prev_hash": b["prev_hash"], "ok": ok, "reasons": reasons,
                       "tampered_seqs": bad_seqs})
        prev = b["block_hash"]
    return {"shipment_id": shipment_id, "ok": first_break is None, "blocks": report, "n_blocks": len(blocks),
            "pending_readings": pending, "first_broken_height": first_break,
            "tampered_seqs": sorted(set(tampered)),
            "head_hash": blocks[-1]["block_hash"] if blocks else GENESIS}


def verified_seq_ranges(shipment_id: int) -> list[tuple[int, int]]:
    """Seq ranges whose blocks verify (used to exclude unverified evidence from disputes, SLA 6.1)."""
    v = verify(shipment_id)
    return [(b["first_seq"], b["last_seq"]) for b in v["blocks"] if b["ok"]]
