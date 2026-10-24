"""A deliberately small agent runtime: plain Python, typed tools, JSON-schema validation, full audit trail.

* `Registry` holds tools; arguments are validated against each tool's JSON schema before it runs.
* `Run` records every step (tool / rule / llm) with inputs, outputs, timing and whether an LLM was used.
  The trace is stored in `agent_runs` and streamed to the dashboard, so any decision can be audited months later.
* `llm_step` asks the model for schema-constrained JSON, checks that it only quotes numbers present in the
  supplied facts (grounding), and otherwise falls back to a deterministic template.
The LLM never does arithmetic and never chooses an action: it explains what the code decided.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

import jsonschema

from .. import db
from ..services import bus
from .llm import llm


@dataclass
class Tool:
    name: str
    fn: Callable[..., Any]
    description: str
    schema: dict = field(default_factory=lambda: {"type": "object", "properties": {}, "additionalProperties": False})


class Registry:
    def __init__(self) -> None:
        self.tools: dict[str, Tool] = {}

    def register(self, name: str, description: str, schema: dict | None = None):
        def deco(fn):
            self.tools[name] = Tool(name, fn, description, schema or {"type": "object", "properties": {}, "additionalProperties": False})
            return fn
        return deco

    def call(self, name: str, **args) -> Any:
        t = self.tools[name]
        jsonschema.validate(args, t.schema)
        return t.fn(**args)

    def describe(self) -> list[dict]:
        return [{"name": t.name, "description": t.description, "args": t.schema} for t in self.tools.values()]


_NUM = re.compile(r"\d+(?:\.\d+)?")


def _numbers(text: str) -> list[float]:
    return [float(x) for x in _NUM.findall(text.replace(",", ""))]


def numbers_grounded(text: str, facts: Any, always_ok: tuple[float, ...] = (0, 1, 2, 3)) -> tuple[bool, list[float]]:
    """True if every number in `text` also appears in `facts` (any rounding to 0-2 decimals)."""
    import json
    allowed = set(_numbers(json.dumps(facts, default=str)))
    allowed.update(always_ok)
    ungrounded = []
    for n in _numbers(text):
        if not any(abs(n - a) <= max(0.051, abs(a) * 0.005) for a in allowed):
            ungrounded.append(n)
    return (not ungrounded, ungrounded)


class Run:
    def __init__(self, kind: str, shipment_id: int | None = None, dispute_id: int | None = None) -> None:
        self.kind, self.shipment_id, self.dispute_id = kind, shipment_id, dispute_id
        self.steps: list[dict] = []
        self.llm_used = False
        self.id = db.run("INSERT INTO agent_runs(kind,shipment_id,dispute_id,started_at,status,steps_json) VALUES(?,?,?,?,?,?)",
                         (kind, shipment_id, dispute_id, datetime.now(timezone.utc).isoformat(), "running", "[]"))
        bus.publish("agent_run", {"id": self.id, "kind": kind, "shipment_id": shipment_id, "dispute_id": dispute_id, "status": "running"})

    def _record(self, step: dict) -> None:
        self.steps.append(step)
        db.run("UPDATE agent_runs SET steps_json=?, llm_used=? WHERE id=?", (db.jdump(self.steps), int(self.llm_used), self.id))
        bus.publish("agent_step", {"run_id": self.id, "kind": self.kind, "shipment_id": self.shipment_id, "step": step})

    def tool(self, registry: Registry, name: str, **args) -> Any:
        t0 = time.time()
        out = registry.call(name, **args)
        self._record({"type": "tool", "name": name, "input": args, "output_preview": _preview(out), "ms": int((time.time() - t0) * 1000)})
        return out

    def rule(self, name: str, fn: Callable[[], Any], note: str = "") -> Any:
        t0 = time.time()
        out = fn()
        self._record({"type": "rule", "name": name, "note": note, "output_preview": _preview(out), "ms": int((time.time() - t0) * 1000)})
        return out

    def llm_step(self, name: str, system: str, facts: dict, instruction: str, schema: dict,
                 fallback: Callable[[], dict], text_fields: tuple[str, ...] = ()) -> dict:
        """Ask the LLM for schema-valid JSON grounded in `facts`; otherwise use the deterministic fallback."""
        import json
        t0 = time.time()
        out = llm.chat_json(system, f"FACTS (JSON):\n{json.dumps(facts, default=str)}\n\nTASK: {instruction}", schema)
        used, note = False, "deterministic template (LLM unavailable)"
        if out is not None:
            bad: list[float] = []
            for f in text_fields:
                ok, ung = numbers_grounded(str(out.get(f, "")), facts)
                bad += ung
            if bad:
                note, out = f"LLM output rejected: ungrounded numbers {bad}; used template", None
            else:
                used, note = True, f"LLM ({llm.status()['model']}), grounding check passed"
        if out is None:
            out = fallback()
        self.llm_used = self.llm_used or used
        self._record({"type": "llm", "name": name, "llm_used": used, "note": note, "output_preview": _preview(out), "ms": int((time.time() - t0) * 1000)})
        out["_generated_by"] = "llm" if used else "template"
        return out

    def finish(self, status: str, result: Any = None) -> None:
        db.run("UPDATE agent_runs SET status=?, finished_at=?, result_json=?, llm_used=? WHERE id=?",
               (status, datetime.now(timezone.utc).isoformat(), db.jdump(result), int(self.llm_used), self.id))
        bus.publish("agent_run", {"id": self.id, "kind": self.kind, "shipment_id": self.shipment_id,
                                  "dispute_id": self.dispute_id, "status": status})


def _preview(o: Any, limit: int = 600) -> Any:
    import json
    s = json.dumps(o, default=str)
    return o if len(s) <= limit else s[:limit] + "..."
