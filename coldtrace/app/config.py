"""Central configuration. Every value can be overridden with an environment variable or a .env file."""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


def _bool(key: str, default: bool) -> bool:
    return _env(key, "1" if default else "0").lower() in {"1", "true", "yes", "on"}


def _jwt_secret(data_dir: Path) -> str:
    if os.environ.get("JWT_SECRET"):
        return os.environ["JWT_SECRET"]
    f = data_dir / ".jwt_secret"
    if not f.exists():
        data_dir.mkdir(parents=True, exist_ok=True)
        f.write_text(secrets.token_hex(32))
    return f.read_text().strip()


@dataclass(frozen=True)
class Settings:
    db_path: Path
    data_dir: Path
    models_dir: Path
    jwt_secret: str
    jwt_ttl_min: int
    demo_password: str
    llm_provider: str          # "ollama" | "none"
    ollama_url: str
    ollama_model: str
    llm_timeout_s: float
    weather_start: str         # ISO date, inclusive
    weather_end: str
    replay_interval_s: float   # seconds between live replay ticks
    replay_frames_per_tick: int
    allow_tamper_demo: bool
    osrm_url: str
    data_gov_api_key: str
    maptiler_key: str          # optional - if set, use MapTiler's bright "streets" style (Google Maps-like); else free OSM tiles


def load() -> Settings:
    data_dir = Path(_env("DATA_DIR", str(ROOT / "data")))
    # default weather window = the 14 days ending 6 days ago (ERA5 archive lags ~5 days)
    end = date.today() - timedelta(days=6)
    start = end - timedelta(days=13)
    return Settings(
        db_path=Path(_env("DB_PATH", str(data_dir / "coldtrace.db"))),
        data_dir=data_dir,
        models_dir=Path(_env("MODELS_DIR", str(ROOT / "models"))),
        jwt_secret=_jwt_secret(data_dir),
        jwt_ttl_min=int(_env("JWT_TTL_MIN", "720")),
        demo_password=_env("DEMO_PASSWORD", "coldtrace"),
        llm_provider=_env("LLM_PROVIDER", "ollama"),
        ollama_url=_env("OLLAMA_URL", "http://localhost:11434"),
        ollama_model=_env("OLLAMA_MODEL", "llama3.2:3b"),
        llm_timeout_s=float(_env("LLM_TIMEOUT_S", "60")),
        weather_start=_env("WEATHER_START", start.isoformat()),
        weather_end=_env("WEATHER_END", end.isoformat()),
        replay_interval_s=float(_env("REPLAY_INTERVAL_S", "1.0")),
        replay_frames_per_tick=int(_env("REPLAY_FRAMES_PER_TICK", "1")),
        allow_tamper_demo=_bool("ALLOW_TAMPER_DEMO", True),
        osrm_url=_env("OSRM_URL", "https://router.project-osrm.org"),
        data_gov_api_key=_env("DATA_GOV_IN_API_KEY", ""),
        maptiler_key=_env("MAPTILER_KEY", ""),
    )


settings = load()
