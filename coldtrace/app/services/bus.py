"""Tiny in-process pub/sub used to push live events to the dashboard over Server-Sent Events."""
from __future__ import annotations

import asyncio
import threading
from typing import Any

_subscribers: set[asyncio.Queue] = set()
_loop: asyncio.AbstractEventLoop | None = None
_lock = threading.Lock()


def bind_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=500)
    with _lock:
        _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    with _lock:
        _subscribers.discard(q)


def publish(event: str, data: Any) -> None:
    """Thread-safe: may be called from worker threads."""
    msg = {"event": event, "data": data}
    loop = _loop
    if loop is None:
        return
    with _lock:
        subs = list(_subscribers)
    for q in subs:
        def _put(q=q):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass
        try:
            loop.call_soon_threadsafe(_put)
        except RuntimeError:
            pass
