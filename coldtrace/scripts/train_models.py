#!/usr/bin/env python3
"""Train the forecaster (breach prediction) and anomaly detector on weather-driven trip simulations.
Requires real weather: run scripts/fetch_data.py --weather first."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import bootstrap, db  # noqa: E402
from app.ml.train import train_and_evaluate  # noqa: E402
from app.services.dataload import weather_status  # noqa: E402
from app.services.weather import store  # noqa: E402


def main() -> None:
    db.init_db()
    bootstrap.seed_reference()
    st = weather_status()
    if not st["ready"]:
        print(f"Weather not fully downloaded ({st['stations_loaded']}/{st['stations_needed']} stations). "
              "Run: python scripts/fetch_data.py --weather")
        if st["stations_loaded"] == 0:
            sys.exit(1)
    print("Building training corpus from real weather and training models (this can take a minute)...")
    card = train_and_evaluate(store)
    print(json.dumps(card, indent=2))
    print("\nSaved to models/forecaster.joblib, models/anomaly.joblib, models/model_card.json")


if __name__ == "__main__":
    main()
