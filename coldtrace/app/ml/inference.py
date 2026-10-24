from __future__ import annotations

import json
import threading

import joblib
import numpy as np

from ..config import settings
from ..domain.commodities import Commodity
from .features import ANOMALY_COLS, HORIZON, trip_features

ALERT_MARGIN_C = 1.0
CONSEC_NEEDED = 2   # forecast must exceed the band for 2 consecutive 10-min readings before we call it a breach


class Models:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.reg = None
        self.iso = None
        self.thr = None

    def load(self) -> bool:
        with self._lock:
            f, a = settings.models_dir / "forecaster.joblib", settings.models_dir / "anomaly.joblib"
            if not (f.exists() and a.exists()):
                self.reg = self.iso = self.thr = None
                return False
            self.reg = joblib.load(f)
            d = joblib.load(a)
            self.iso, self.thr = d["model"], d["threshold"]
            return True

    @property
    def ready(self) -> bool:
        return self.reg is not None

    def card(self) -> dict | None:
        p = settings.models_dir / "model_card.json"
        return json.loads(p.read_text()) if p.exists() else None

    def forecast(self, readings: list[dict], com: Commodity) -> dict | None:
        if not self.ready or len(readings) < 3 + CONSEC_NEEDED:
            return None
        rows = readings[-(12 + CONSEC_NEEDED):]
        X = trip_features(rows, com)
        preds = self.reg.predict(X)
        pred_maxes = X[:, 0] * 0  # placeholder to keep shape; replaced below
        temps = np.array([r["temp_c"] for r in rows])
        pred_max_series = temps + preds
        over = pred_max_series > (com.t_max + ALERT_MARGIN_C)
        sustained = bool(over[-CONSEC_NEEDED:].all())
        temp = rows[-1]["temp_c"]
        pred_max = float(pred_max_series[-1])
        slope = (rows[-1]["temp_c"] - rows[-4]["temp_c"]) / 3.0 if len(rows) >= 4 else 0.0     # deg C per reading
        eta = None
        if temp <= com.t_max and slope > 0.02:
            eta = round(max(0.0, (com.t_max - temp) / slope) * 10.0, 0)
        return {"pred_max_c": round(pred_max, 2), "horizon_min": HORIZON * 10, "breach_predicted": sustained,
                "eta_to_breach_min": eta}

    def anomaly(self, readings: list[dict], com: Commodity) -> dict | None:
        if not self.ready or len(readings) < 6:
            return None
        rows = readings[-12:]
        X = trip_features(rows, com)[:, ANOMALY_COLS]
        scores = self.iso.score_samples(X)
        flags = scores < self.thr
        return {"score": round(float(scores[-1]), 4), "flag": bool(flags[-1]), "recent_flags": int(flags[-3:].sum())}


models = Models()
