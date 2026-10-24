Populated by `python scripts/train.py`:
- `forecaster.joblib` — HistGradientBoostingRegressor (60-minute breach forecast)
- `anomaly.joblib` — IsolationForest (fit on healthy trips only)
- `model_card.json` — honest evaluation metrics (see the README's "Design notes & honest limitations")

Not committed to version control (see `.gitignore`) since they're regenerated from real weather data.
