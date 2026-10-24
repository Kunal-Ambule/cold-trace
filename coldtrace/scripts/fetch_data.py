#!/usr/bin/env python3
"""Load REAL data into ColdTrace: Agmarknet mandi prices and ERA5 weather (via Open-Meteo).

Usage:
    python scripts/fetch_data.py --prices            # load the bundled real Agmarknet snapshot
    python scripts/fetch_data.py --prices --refresh   # pull today's prices from data.gov.in (needs an API key)
    python scripts/fetch_data.py --weather            # download real hourly weather for every lane (needs internet)
    python scripts/fetch_data.py --weather --start 2026-08-01 --end 2026-08-14
    python scripts/fetch_data.py --all                # both, in order
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import bootstrap, db  # noqa: E402
from app.services import dataload  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prices", action="store_true", help="load Agmarknet mandi prices")
    ap.add_argument("--refresh", action="store_true", help="with --prices: pull fresh data from data.gov.in instead of the bundled CSV")
    ap.add_argument("--weather", action="store_true", help="download real ERA5 hourly weather for every lane station")
    ap.add_argument("--start", help="weather window start (YYYY-MM-DD), default from .env / config")
    ap.add_argument("--end", help="weather window end (YYYY-MM-DD)")
    ap.add_argument("--force", action="store_true", help="with --weather: re-download even if already cached")
    ap.add_argument("--all", action="store_true", help="run --prices and --weather")
    args = ap.parse_args()

    if not (args.prices or args.weather or args.all):
        ap.print_help()
        return

    db.init_db()

    if args.prices or args.all:
        if args.refresh:
            n = dataload.refresh_prices_from_api()
            print(f"Refreshed {n} price listings from data.gov.in")
        else:
            n = dataload.load_prices_csv()
            print(f"Loaded {n} real Agmarknet price listings (bundled snapshot)")

    if args.weather or args.all:
        print("Downloading real hourly weather (ERA5 reanalysis via Open-Meteo) for every lane station...")
        res = dataload.fetch_weather(start=args.start, end=args.end, only_missing=not args.force)
        print(f"Weather stations: {res['ok']}/{res['stations']} ok, {res['failed']} failed. Window: {res['window']}")
        if res["failed"]:
            print("Some stations failed - check your internet connection and retry. "
                  "The app will show a clear error if a shipment needs a station that has no data.")

    bootstrap.seed_reference()  # ensure SLA/users/hubs exist even if prices already existed
    print("Done.")


if __name__ == "__main__":
    main()
