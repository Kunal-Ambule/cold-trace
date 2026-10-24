#!/usr/bin/env python3
"""Create a handful of demo shipments across different scenarios, for a quick live demo.

Requires real weather to already be loaded for the chosen --date (see scripts/fetch_data.py --weather).
Usage:
    python scripts/seed_demo.py --date 2026-08-05
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import bootstrap, db  # noqa: E402
from app.services import shipments  # noqa: E402

PLAN = [
    ("SBN-MOS", "tomato", "nominal"),
    ("BHU-PIM", "banana", "compressor_degradation"),
    ("UJJ-MOS", "potato", "door_ajar"),
    ("HOS-CBE", "tomato", "poor_precool"),
    ("PUN-HYD", "biologics", "compressor_degradation"),
]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", required=True, help="departure date, YYYY-MM-DD, must fall inside the loaded weather window")
    ap.add_argument("--advance", type=int, default=30, help="how many 10-minute frames to pre-advance each shipment (default 30)")
    args = ap.parse_args()

    db.init_db()
    bootstrap.seed_reference()
    depart = f"{args.date}T02:30:00Z"
    for lane, com, scenario in PLAN:
        kw = {"declared_value_inr": 2_000_000} if com == "biologics" else {}
        s = shipments.create(lane, com, depart, scenario, **kw)
        shipments.advance(s["id"], args.advance)
        print(f"Created {s['code']} ({lane}, {com}, {scenario}) and advanced {args.advance} frames")
    print("\nDemo shipments ready. Start the server and sign in as 'dispatcher' / 'coldtrace'.")


if __name__ == "__main__":
    main()
