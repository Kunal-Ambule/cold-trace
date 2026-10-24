#!/usr/bin/env python3
"""Train the breach-forecast and anomaly models from a thermal-model replay over REAL weather.

Usage:
    python scripts/train.py                  # default: a departure every 12 hours, all lanes
    python scripts/train.py --every-hours 6  # denser corpus (slower, more trips)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import bootstrap, db  # noqa: E402
from app.ml.train import train_and_evaluate  # noqa: E402
from app.services.dataload import weather_status  # noqa: E402
from app.services.weather import store  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--every-hours", type=int, default=12, help="hours between simulated departures per lane (default 12)")
    args = ap.parse_args()

    db.init_db()
    ws = weather_status()
    if not ws["ready"]:
        print("Real weather is not loaded yet. Run: python scripts/fetch_data.py --weather")
        sys.exit(1)

    print("Building training corpus from the thermal model replayed over real ERA5 weather...")
    card = train_and_evaluate(store, depart_every_h=args.every_hours)
    print(json.dumps(card, indent=2))
    print("\nSaved: models/forecaster.joblib, models/anomaly.joblib, models/model_card.json")


if __name__ == "__main__":
    main()
