"""Commodity storage profiles.

The temperature bands are indicative post-harvest storage recommendations compiled from public
guidance (NHB / ICAR-CIPHET / FAO handling manuals). They vary by variety and maturity: confirm
them with your agronomist before commercial use. Edit here and the whole platform follows.

Shelf-life model
----------------
Respiration-driven deterioration follows a Q10 relationship: every +10 C multiplies the rate by
`q10` (2.0-3.0 for most fresh produce). Storing at `t_opt` consumes `1 / shelf_days` of shelf life
per day. Time above `t_opt` burns life faster; that *excess* burn is what we price as loss.
Chilling-sensitive crops also lose value below `t_min` (chilling injury).
Biologics use a different, product-specific rule: a cumulative minutes-out-of-range budget.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Commodity:
    code: str
    name: str
    agmarknet: str | None        # exact commodity string in the Agmarknet data
    t_min: float
    t_max: float
    t_opt: float
    shelf_days: float            # shelf life at t_opt
    q10: float = 2.5
    chill_sensitive: bool = False
    chill_coeff: float = 0.004   # fraction of value lost per degree-hour below t_min (if sensitive)
    mode: str = "shelf"          # "shelf" | "budget"
    budget_min: float = 0.0      # minutes out of range tolerated (budget mode)
    note: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


_SRC = "Indicative range from public post-harvest guidance; verify per variety."

COMMODITIES: dict[str, Commodity] = {c.code: c for c in [
    Commodity("tomato", "Tomato", "Tomato", 9, 12, 10.5, 14, chill_sensitive=True, note=_SRC),
    Commodity("onion", "Onion", "Onion", 0, 4, 2, 120, note=_SRC),
    Commodity("potato", "Potato", "Potato", 7, 10, 8, 60, chill_sensitive=True, note=_SRC),
    Commodity("banana", "Banana", "Banana", 13, 15, 14, 14, chill_sensitive=True, chill_coeff=0.01, note=_SRC),
    Commodity("green_chilli", "Green chilli", "Green Chilli", 7, 10, 8, 14, chill_sensitive=True, note=_SRC),
    Commodity("okra", "Okra (bhindi)", "Bhindi(Ladies Finger)", 7, 10, 8, 7, chill_sensitive=True, note=_SRC),
    Commodity("brinjal", "Brinjal", "Brinjal", 10, 12, 11, 10, chill_sensitive=True, note=_SRC),
    Commodity("cabbage", "Cabbage", "Cabbage", 0, 2, 1, 30, note=_SRC),
    Commodity("carrot", "Carrot", "Carrot", 0, 2, 1, 60, note=_SRC),
    Commodity("cauliflower", "Cauliflower", "Cauliflower", 0, 2, 1, 21, note=_SRC),
    Commodity("bottle_gourd", "Bottle gourd", "Bottle gourd", 10, 13, 12, 14, chill_sensitive=True, note=_SRC),
    Commodity("bitter_gourd", "Bitter gourd", "Bitter gourd", 10, 12, 11, 10, chill_sensitive=True, note=_SRC),
    Commodity("ginger", "Ginger (green)", "Ginger(Green)", 12, 14, 13, 60, chill_sensitive=True, note=_SRC),
    Commodity("biologics", "Vaccines / biologics (2-8 C)", None, 2, 8, 5, 0, mode="budget", budget_min=120,
              note="Cold-chain medicines: the loss budget (minutes out of range) must come from the "
                   "manufacturer's stability data. 120 min is a placeholder."),
]}


def get(code: str) -> Commodity:
    return COMMODITIES[code]
