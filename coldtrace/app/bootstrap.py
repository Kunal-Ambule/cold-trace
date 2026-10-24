"""Idempotent start-up: schema, real price data, SLA, hubs, users, routes."""
from __future__ import annotations

import logging

from . import db, security
from .domain import lanes, sla
from .services import dataload, routing

log = logging.getLogger("coldtrace.boot")


def seed_reference() -> None:
    if not db.one("SELECT 1 x FROM market_prices LIMIT 1"):
        n = dataload.load_prices_csv()
        log.info("loaded %d real Agmarknet listings", n)
    if not db.one("SELECT 1 x FROM sla_clauses LIMIT 1"):
        for no, title, body, k, v in sla.CLAUSES:
            cid = db.run("INSERT INTO sla_clauses(contract_id,clause_no,title,body,param_key,param_value) VALUES(?,?,?,?,?,?)",
                         (sla.CONTRACT_ID, no, title, body, k, v))
            db.run("INSERT INTO sla_fts(rowid,title,body) VALUES(?,?,?)", (cid, title, body))
    for h in lanes.HUBS:
        db.run("INSERT OR IGNORE INTO hubs(id,name,lat,lon,verified) VALUES(?,?,?,?,0)", (h.name, h.name, h.lat, h.lon))
    security.seed_users()


def init_all(with_routes: bool = True) -> None:
    db.init_db()
    seed_reference()
    if with_routes:
        routing.ensure_all_routes()
