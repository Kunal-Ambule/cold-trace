"""Chatbot API endpoint — powered by OpenRouter (OpenAI-compatible)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/chat", tags=["chat"])

# ---------------------------------------------------------------------------
# Ensure .env is read even if uvicorn started before .env was created
# ---------------------------------------------------------------------------
def _ensure_env():
    if not os.environ.get("OPENROUTER_API_KEY"):
        env_path = Path(__file__).resolve().parent.parent.parent / ".env"
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

_ensure_env()

# ---------------------------------------------------------------------------
# System prompt — gives the model context about the ColdTrace platform
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are ColdBot, the AI assistant built into ColdTrace — an AI-powered
autonomous cold-chain & agri-perishable logistics intelligence platform.

You help operators, dispatchers, drivers, auditors and admins understand and navigate the platform.

ColdTrace features:
• Fleet tab — live map of all refrigerated trucks, their temperature, humidity, GPS location,
  current shipment, route, ETA, and anomaly alerts.
• Disputes tab — manage quality disputes on delivered shipments; AI auto-classifies root cause
  (spoilage, transit damage, fraud, etc.) and assigns a ledger credit.
• Market Prices tab — current wholesale agri-commodity prices (Agmarknet / data.gov.in).
• Data & Models tab (Admin) — retrain the ML spoilage-risk model, ingest weather data, view
  model metrics (accuracy, precision, recall, F1).
• Shipment detail panel — telemetry charts (temperature, humidity over time), route map,
  event timeline, recommended actions (reroute, precool, escalate, reject).
• AI agent actions — autonomous recommendations: rerouting around weather/traffic, precooling
  alerts, spoilage risk scores, dispute auto-resolution, fraud detection.
• Supported roles: dispatcher (full fleet access), driver (own vehicle), auditor (read-only),
  admin (everything including ML admin).

Answer questions accurately, clearly, and concisely about these features, how to use them, what the data
means, and how the AI works. Keep answers professional and formatted with clean bullet points where appropriate.
"""

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
CANDIDATE_MODELS = [
    "minimax/minimax-m3.1-flash:free",
    "nvidia/nemotron-3.5-super-vl:free",
    "nvidia/nemotron-3.5-lightning:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
]


class ChatMessage(BaseModel):
    role: str      # "user" | "assistant" | "model"
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


class ChatResponse(BaseModel):
    reply: str
    error: Optional[str] = None


def _openrouter_chat(messages: list[ChatMessage]) -> str:
    """Call OpenRouter API using the OpenAI-compatible SDK with automatic model fallback."""
    _ensure_env()
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise ValueError(
            "OPENROUTER_API_KEY is not set. Add it to your .env file:\n"
            "  OPENROUTER_API_KEY=sk-or-v1-..."
        )

    try:
        from openai import OpenAI
    except ImportError:
        raise ValueError("openai package not installed. Run: pip install openai")

    client = OpenAI(
        api_key=api_key,
        base_url=OPENROUTER_BASE_URL,
    )

    # Build message list: system prompt + conversation history
    openai_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for msg in messages:
        role = "assistant" if msg.role == "model" else msg.role
        openai_messages.append({"role": role, "content": msg.content})

    last_error = None
    for model_name in CANDIDATE_MODELS:
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=openai_messages,
                temperature=0.4,
                max_tokens=800,
                extra_headers={
                    "HTTP-Referer": "http://localhost:8000",
                    "X-Title": "ColdTrace ColdBot",
                },
                timeout=25,
            )
            msg = response.choices[0].message
            content = msg.content or getattr(msg, "reasoning", "") or ""
            if content.strip():
                return content.strip()
        except Exception as e:
            last_error = e
            continue

    if last_error:
        raise last_error
    return "I'm sorry, I couldn't generate a response at this moment. Please try asking again."


@router.post("", response_model=ChatResponse)
def chat(req: ChatRequest):
    if not req.messages:
        raise HTTPException(400, "No messages provided")
    try:
        reply = _openrouter_chat(req.messages)
        return ChatResponse(reply=reply)
    except ValueError as e:
        return ChatResponse(reply="", error=str(e))
    except Exception as e:
        return ChatResponse(reply="", error=f"OpenRouter error: {e}")
