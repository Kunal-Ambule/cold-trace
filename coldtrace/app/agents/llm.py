"""Ollama client with strict JSON-schema output. Every caller has a deterministic fallback, so the platform
works (and can be demoed) with no LLM at all; the LLM only improves wording and reads driver notes."""
from __future__ import annotations

import json
import logging
import time

import httpx
import jsonschema

from ..config import settings

log = logging.getLogger("coldtrace.llm")


class LLM:
    def __init__(self) -> None:
        self._checked_at = 0.0
        self._ok = False
        self.last_error: str | None = None

    def available(self) -> bool:
        if settings.llm_provider != "ollama":
            return False
        if time.time() - self._checked_at < 30:
            return self._ok
        self._checked_at = time.time()
        try:
            r = httpx.get(f"{settings.ollama_url}/api/tags", timeout=1.5)
            names = [m["name"] for m in r.json().get("models", [])]
            base = settings.ollama_model.split(":")[0]
            self._ok = any(n == settings.ollama_model or n.split(":")[0] == base for n in names)
            self.last_error = None if self._ok else f"model '{settings.ollama_model}' not pulled (run: ollama pull {settings.ollama_model})"
        except Exception as e:  # noqa: BLE001
            self._ok, self.last_error = False, f"Ollama not reachable at {settings.ollama_url}: {e}"
        return self._ok

    def status(self) -> dict:
        ok = self.available()
        return {"provider": settings.llm_provider, "model": settings.ollama_model, "available": ok, "detail": self.last_error}

    def chat_json(self, system: str, user: str, schema: dict, temperature: float = 0.1, max_tokens: int = 700) -> dict | None:
        """Returns a schema-valid dict or None (caller then uses its fallback)."""
        if not self.available():
            return None
        try:
            r = httpx.post(f"{settings.ollama_url}/api/chat", timeout=settings.llm_timeout_s, json={
                "model": settings.ollama_model, "stream": False, "format": schema,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "options": {"temperature": temperature, "num_predict": max_tokens}})
            r.raise_for_status()
            out = json.loads(r.json()["message"]["content"])
            jsonschema.validate(out, schema)
            return out
        except Exception as e:  # noqa: BLE001
            log.warning("LLM call failed or returned invalid JSON: %s", e)
            self.last_error = str(e)
            return None


llm = LLM()
