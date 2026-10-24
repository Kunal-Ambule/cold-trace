"""Train + evaluate the forecaster and anomaly detector. Writes models/*.joblib and models/model_card.json."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor, IsolationForest

from ..config import settings
from ..domain.commodities import get as get_com
from ..services.weather import WeatherStore
from .corpus import Trip, build_corpus
from .features import ANOMALY_COLS, FEATURES, HORIZON, future_max_delta, trip_features

log = logging.getLogger("coldtrace.ml")
ALERT_MARGIN_C = 1.0     # forecast must exceed the band by this much before we warn
CONSEC_NEEDED = 2        # ...and stay predicted-over-band for this many consecutive readings (20 min)


def _stack(trips: list[Trip]):
    Xs, ys, meta = [], [], []
    for tr in trips:
        com = get_com(tr.commodity)
        X = trip_features(tr.frames, com)
        y = future_max_delta([f["temp_c"] for f in tr.frames])
        Xs.append(X)
        ys.append(y)
        meta.append((tr, X.shape[0]))
    return np.vstack(Xs), np.concatenate(ys), meta


def _sustained_alert_idx(over: np.ndarray, need: int = CONSEC_NEEDED) -> int | None:
    run = np.convolve(over.astype(int), np.ones(need, dtype=int), mode="valid")
    hit = np.where(run >= need)[0]
    return int(hit[0] + need - 1) if len(hit) else None


def _alert_episode_stats(trips: list[Trip], model, thr_fn) -> dict:
    """Trip-level: was the first out-of-band breach warned about beforehand, and how early?"""
    leads, warned, breaches, false_alert_trips, nominal_trips = [], 0, 0, 0, 0
    for tr in trips:
        com = get_com(tr.commodity)
        X = trip_features(tr.frames, com)
        pred_delta = model.predict(X)
        temps = np.array([f["temp_c"] for f in tr.frames])
        pred_max = temps + pred_delta
        in_band = (temps <= com.t_max) & (temps >= com.t_min)
        breach_idx = next((i for i in range(1, len(temps)) if in_band[i - 1] and temps[i] > com.t_max), None)
        over = in_band & (pred_max > com.t_max + ALERT_MARGIN_C)
        alert_idx = _sustained_alert_idx(over)
        if tr.scenario == "nominal":
            nominal_trips += 1
            if alert_idx is not None:
                false_alert_trips += 1
        if breach_idx is not None:
            breaches += 1
            if alert_idx is not None and alert_idx < breach_idx:
                warned += 1
                leads.append((breach_idx - alert_idx) * 10)
    return {
        "breach_trips": breaches, "warned_before_breach": warned,
        "warned_pct": round(100 * warned / breaches, 1) if breaches else None,
        "lead_time_min_mean": round(float(np.mean(leads)), 1) if leads else None,
        "lead_time_min_median": round(float(np.median(leads)), 1) if leads else None,
        "nominal_trips": nominal_trips,
        "false_alert_trips_pct": round(100 * false_alert_trips / nominal_trips, 1) if nominal_trips else None,
    }


def train_and_evaluate(weather: WeatherStore, depart_every_h: int = 12, lanes=None, persist: bool = True) -> dict:
    trips = build_corpus(weather, depart_every_h=depart_every_h, lanes=lanes)
    if len(trips) < 20:
        raise RuntimeError("Not enough weather-driven trips to train. Run scripts/fetch_data.py --weather first.")
    trips.sort(key=lambda t: t.depart_epoch)
    cut = trips[int(len(trips) * 0.7)].depart_epoch
    train = [t for t in trips if t.depart_epoch < cut]
    test = [t for t in trips if t.depart_epoch >= cut + 12 * 3600]      # 12 h gap: no overlap between splits
    Xtr, ytr, _ = _stack(train)
    Xte, yte, _ = _stack(test)

    reg = HistGradientBoostingRegressor(max_iter=250, learning_rate=0.07, max_depth=6, random_state=7)
    reg.fit(Xtr, ytr)
    pred = reg.predict(Xte)
    mae = float(np.mean(np.abs(pred - yte)))
    mae_persist = float(np.mean(np.abs(yte)))           # baseline: "temperature stays where it is"
    slope = Xte[:, FEATURES.index("d3")] / 3.0
    mae_linear = float(np.mean(np.abs(slope * HORIZON - yte)))

    # row-level breach classification for rows currently in band
    cur = Xte[:, FEATURES.index("dev_max")]
    lo = Xte[:, FEATURES.index("dev_min")]
    in_band = (cur <= 0) & (lo >= 0)
    true_breach = (cur + yte) > 0
    pred_breach = (cur + pred) > ALERT_MARGIN_C
    tp = int(np.sum(in_band & true_breach & pred_breach))
    fp = int(np.sum(in_band & ~true_breach & pred_breach))
    fn = int(np.sum(in_band & true_breach & ~pred_breach))
    prec = tp / (tp + fp) if tp + fp else None
    rec = tp / (tp + fn) if tp + fn else None

    # anomaly detector: fit on healthy trips only
    nominal_tr = [t for t in train if t.scenario == "nominal"]
    Xn, _, _ = _stack(nominal_tr)
    iso = IsolationForest(n_estimators=200, random_state=7, contamination="auto")
    iso.fit(Xn[:, ANOMALY_COLS])
    thr = float(np.percentile(iso.score_samples(Xn[:, ANOMALY_COLS]), 1.0))
    an_by_scn: dict[str, list[float]] = {}
    fpr_rows = []
    for t in test:
        com = get_com(t.commodity)
        X = trip_features(t.frames, com)
        flags = iso.score_samples(X[:, ANOMALY_COLS]) < thr
        run = np.convolve(flags.astype(int), np.ones(3, dtype=int), mode="valid") >= 3
        an_by_scn.setdefault(t.scenario, []).append(1.0 if run.any() else 0.0)
        if t.scenario == "nominal":
            fpr_rows.append(flags.mean())
    episode = _alert_episode_stats(test, reg, None)

    card = {
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "training_data": {
            "source": "Thermal-model replay over REAL ERA5 hourly weather (Open-Meteo) on 9 real lanes.",
            "weather_window": [settings.weather_start, settings.weather_end],
            "trips_total": len(trips), "trips_train": len(train), "trips_test": len(test),
            "rows_train": int(Xtr.shape[0]), "rows_test": int(Xte.shape[0]),
            "split": "chronological (70/30) with a 12 h gap; test trips start strictly after training trips",
        },
        "forecaster": {
            "model": "HistGradientBoostingRegressor", "target": f"max temperature over the next {HORIZON*10} minutes minus now",
            "features": FEATURES, "mae_c": round(mae, 3), "baseline_persistence_mae_c": round(mae_persist, 3),
            "baseline_linear_extrapolation_mae_c": round(mae_linear, 3),
            "row_breach_precision": None if prec is None else round(prec, 3),
            "row_breach_recall": None if rec is None else round(rec, 3),
            "alert_margin_c": ALERT_MARGIN_C, **episode,
        },
        "anomaly_detector": {
            "model": "IsolationForest (fit on healthy trips only)", "threshold": round(thr, 4),
            "row_false_flag_rate_on_healthy_test": round(float(np.mean(fpr_rows)), 4) if fpr_rows else None,
            "trip_detection_rate_by_scenario": {k: round(float(np.mean(v)), 3) for k, v in an_by_scn.items()},
        },
        "limitations": [
            "Trained and tested on model-derived telemetry (real weather, simulated reefer physics). "
            "It shows the pipeline works and how early it can warn; it is not evidence of accuracy on a real fleet.",
            "Re-train with real device readings (source='device') as soon as they exist: the same code path applies.",
            "Scenario faults are injected deliberately, so recall figures describe those specific faults only.",
        ],
    }
    if persist:
        settings.models_dir.mkdir(parents=True, exist_ok=True)
        joblib.dump(reg, settings.models_dir / "forecaster.joblib")
        joblib.dump({"model": iso, "threshold": thr}, settings.models_dir / "anomaly.joblib")
        (settings.models_dir / "model_card.json").write_text(json.dumps(card, indent=2))
    return card
