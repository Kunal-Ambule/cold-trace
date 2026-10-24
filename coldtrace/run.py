#!/usr/bin/env python3
"""Convenience launcher: python run.py [--port 8000] [--reload]"""
import argparse

import uvicorn

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--reload", action="store_true")
    args = ap.parse_args()
    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload)
