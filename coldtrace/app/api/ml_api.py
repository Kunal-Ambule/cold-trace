from __future__ import annotations

import threading

from fastapi import APIRouter, Depends, HTTPException

from .. import security
from ..ml.inference import models
from ..ml.train import train_and_evaluate
from ..services import dataload
from ..services.weather import store as weather_store
from .schemas import TrainReq

router = APIRouter(prefix="/api/ml", tags=["ml"])
_training = {"running": False}


@router.get("/status")
def status(user: dict = Depends(security.current_user)):
    return {"ready": models.ready, "card": models.card(), "training_running": _training["running"],
            "weather": dataload.weather_status()}


@router.post("/train")
def train(body: TrainReq, user: dict = Depends(security.require("admin", "dispatcher"))):
    if _training["running"]:
        raise HTTPException(409, "Training already running")
    ws = dataload.weather_status()
    if not ws["ready"]:
        raise HTTPException(400, "Weather data not loaded. Run: python scripts/fetch_data.py --weather")
    _training["running"] = True

    def _job() -> None:
        try:
            train_and_evaluate(weather_store, depart_every_h=body.depart_every_h)
            models.load()
        finally:
            _training["running"] = False

    threading.Thread(target=_job, name="train", daemon=True).start()
    return {"started": True}


@router.post("/fetch-weather")
def fetch_weather(user: dict = Depends(security.require("admin"))):
    return dataload.fetch_weather()
