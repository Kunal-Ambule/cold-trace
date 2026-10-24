"""Template service-level agreement. Replace with real contracts via POST /api/sla or edit here.

The clause *numbers* are what the dispute agents cite. Numeric parameters are machine-readable so the
liability engine and the contract stay in sync.
"""
from __future__ import annotations

CONTRACT_ID = "TEMPLATE-SLA-001"

# (clause_no, title, body, param_key, param_value)
CLAUSES: list[tuple[str, str, str, str | None, float | None]] = [
    ("1.1", "Temperature band",
     "The Carrier shall maintain the cargo return-air temperature within the band published for the commodity "
     "in Schedule A for the whole period between departure and arrival.", None, None),
    ("2.1", "Pre-cooling by Shipper",
     "The Shipper shall deliver cargo pre-cooled to within 1.5 C of the set-point before loading. Temperature "
     "excursions caused by cargo loaded warm are the Shipper's responsibility.", "precool_tolerance_c", 1.5),
    ("2.2", "Loading dwell",
     "Loading shall not exceed 45 minutes with doors open. Time beyond this is attributed to the Shipper.",
     "load_free_minutes", 45),
    ("3.1", "Reefer unit maintenance",
     "The Carrier warrants that the refrigeration unit is serviced and able to hold the set-point at the "
     "design ambient temperature. Loss caused by refrigeration underperformance is the Carrier's responsibility.",
     None, None),
    ("3.2", "Door-open events in transit",
     "Doors must remain closed in transit except for documented inspections. Excursions overlapping an "
     "undocumented door-open event are the Carrier's responsibility.", None, None),
    ("4.1", "Receiver dock dwell",
     "The Receiver shall begin unloading within 30 minutes of arrival. Excursions occurring after this "
     "period are the Receiver's responsibility.", "dock_free_minutes", 30),
    ("5.1", "Environmental load and force majeure",
     "Where an excursion would have occurred even with a compliant pre-cooled load and a healthy refrigeration "
     "unit (extreme ambient conditions), the resulting loss is shared and is not attributed to any single "
     "party.", None, None),
    ("6.1", "Evidence standard",
     "Temperature logs are admissible evidence only if the tamper-evident ledger verifies without breaks. "
     "Unverified segments are excluded from apportionment and flagged for manual review.", None, None),
    ("7.1", "Liability cap",
     "Total liability of any party for a single shipment is capped at the declared cargo value.",
     "cap_fraction_of_value", 1.0),
    ("7.2", "Claims window",
     "Claims must be lodged within 72 hours of delivery.", "claim_window_hours", 72),
]
