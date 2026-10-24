#!/usr/bin/env python3
"""Convenience launcher: init DB, ensure routes, start the API with reload. For quick local dev only."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import bootstrap  # noqa: E402

if __name__ == "__main__":
    bootstrap.init_all()
    subprocess.run([sys.executable, "-m", "uvicorn", "app.main:app", "--reload", "--port", "8000"])
