"""Server-Sent Events: live push of readings, alerts, actions and agent steps to the dashboard."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends
from sse_starlette.sse import EventSourceResponse

from .. import security
from ..services import bus

router = APIRouter(prefix="/api/stream", tags=["stream"])


@router.get("")
async def stream(user: dict = Depends(security.current_user)):
    q = bus.subscribe()

    async def gen():
        yield {"event": "ready", "data": json.dumps({"ok": True})}
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15)
                    yield {"event": msg["event"], "data": json.dumps(msg["data"], default=str)}
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "{}"}
        finally:
            bus.unsubscribe(q)

    return EventSourceResponse(gen())
