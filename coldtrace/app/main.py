"""ColdTrace: AI-powered autonomous cold-chain intelligence. FastAPI entry point."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import bootstrap
from .api import actions_api, auth, disputes_api, ml_api, reference, shipments_api, stream
from .config import ROOT
from .ml.inference import models
from .services import bus

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("coldtrace")

WEB_DIR = ROOT / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    bootstrap.init_all()
    models.load()
    bus.bind_loop(asyncio.get_event_loop())
    log.info("ColdTrace ready. Model loaded: %s", models.ready)
    yield


app = FastAPI(title="ColdTrace", version="1.0.0", lifespan=lifespan)

for r in (auth.router, shipments_api.router, actions_api.router, disputes_api.router, reference.router, ml_api.router, stream.router):
    app.include_router(r)

app.mount("/vendor", StaticFiles(directory=str(WEB_DIR / "vendor")), name="vendor")
app.mount("/css", StaticFiles(directory=str(WEB_DIR / "css")), name="css")
app.mount("/js", StaticFiles(directory=str(WEB_DIR / "js")), name="js")
app.mount("/driver", StaticFiles(directory=str(WEB_DIR / "driver"), html=True), name="driver")


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(str(WEB_DIR / "index.html"))
