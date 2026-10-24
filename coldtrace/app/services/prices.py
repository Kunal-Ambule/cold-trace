"""Real Agmarknet mandi prices: lookups used to value cargo, plus the price explorer API."""
from __future__ import annotations

import statistics

from .. import db
from ..domain.commodities import get as get_com


def _clean(rows: list[dict]) -> list[dict]:
    return [r for r in rows if not r["price_outlier"] and not r["unit_error"] and r["modal_price"]]


def _display_variety(variety: str | None) -> str | None:
    """Agmarknet's raw 'Variety' column uses 'Deshi' (Hindi for 'local/country') as a varietal name.
    Relabelled to 'Indian' for the UI only; the underlying real CSV data is left untouched."""
    if not variety:
        return variety
    return " ".join("Indian" if w == "Deshi" else w for w in variety.split(" "))


def lookup(commodity_code: str, market: str | None, state: str | None) -> dict | None:
    """Modal price (INR per quintal) with the basis used. None for commodities without market prices."""
    com = get_com(commodity_code)
    if not com.agmarknet:
        return None
    base = "SELECT market,state,arrival_date,modal_price,price_outlier,unit_error FROM market_prices WHERE commodity=?"
    rows = _clean(db.all_(base + " AND market=?", (com.agmarknet, market))) if market else []
    basis = "origin market"
    if not rows and state:
        rows, basis = _clean(db.all_(base + " AND state=?", (com.agmarknet, state))), "state median"
    if not rows:
        rows, basis = _clean(db.all_(base, (com.agmarknet,))), "all-India median"
    if not rows:
        return None
    mod = statistics.median(r["modal_price"] for r in rows)
    return {"modal_inr_per_quintal": float(mod), "basis": basis, "n_listings": len(rows),
            "market": market if basis == "origin market" else None, "as_of": rows[0]["arrival_date"],
            "source": "Agmarknet via data.gov.in"}


def explorer(commodity_code: str, state: str | None = None, limit: int = 40) -> dict:
    com = get_com(commodity_code)
    if not com.agmarknet:
        return {"commodity": commodity_code, "rows": [], "summary": None}
    q = ("SELECT state,district,market,variety,grade,arrival_date,min_price,max_price,modal_price,price_outlier,unit_error "
         "FROM market_prices WHERE commodity=?")
    args: list = [com.agmarknet]
    if state:
        q += " AND state=?"
        args.append(state)
    rows = _clean(db.all_(q + " ORDER BY modal_price DESC", args))
    if not rows:
        return {"commodity": commodity_code, "rows": [], "summary": None}
    for r in rows:
        r["variety"] = _display_variety(r["variety"])
    modal = [r["modal_price"] for r in rows]
    return {"commodity": commodity_code, "name": com.name, "unit": "INR per quintal (100 kg)",
            "summary": {"n": len(rows), "median": statistics.median(modal), "min": min(modal), "max": max(modal),
                        "as_of": rows[0]["arrival_date"]},
            "rows": rows[:limit]}


def states_for(commodity_code: str) -> list[str]:
    com = get_com(commodity_code)
    if not com.agmarknet:
        return []
    return [r["state"] for r in db.all_("SELECT DISTINCT state FROM market_prices WHERE commodity=? ORDER BY state", (com.agmarknet,))]
