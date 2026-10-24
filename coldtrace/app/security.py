"""JWT auth with three roles. Passwords are PBKDF2-SHA256 hashed."""
from __future__ import annotations

import hashlib
import hmac
import os
import time

import jwt
from fastapi import Depends, HTTPException, Query, Request

from . import db
from .config import settings

ROLES = ("dispatcher", "driver", "auditor", "admin")


def hash_password(pw: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 200_000)
    return salt.hex() + "$" + dk.hex()


def check_password(pw: str, stored: str) -> bool:
    salt_hex, _ = stored.split("$", 1)
    return hmac.compare_digest(hash_password(pw, bytes.fromhex(salt_hex)), stored)


def make_token(user: dict) -> str:
    now = int(time.time())
    return jwt.encode({"sub": user["username"], "role": user["role"], "name": user.get("display_name"),
                       "iat": now, "exp": now + settings.jwt_ttl_min * 60}, settings.jwt_secret, algorithm="HS256")


def current_user(request: Request, token: str | None = Query(default=None)) -> dict:
    """Bearer header, or ?token= (needed by EventSource, which cannot set headers)."""
    auth = request.headers.get("authorization", "")
    raw = auth[7:] if auth.lower().startswith("bearer ") else token
    if not raw:
        raise HTTPException(401, "Missing token")
    try:
        p = jwt.decode(raw, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as e:
        raise HTTPException(401, f"Invalid token: {e}") from e
    return {"username": p["sub"], "role": p["role"], "name": p.get("name")}


def require(*roles: str):
    def dep(user: dict = Depends(current_user)) -> dict:
        if user["role"] not in roles and user["role"] != "admin":
            raise HTTPException(403, f"Requires role: {', '.join(roles)}")
        return user
    return dep


def seed_users() -> None:
    demo = [("dispatcher", "dispatcher", "Fleet dispatcher"), ("driver", "driver", "Driver (demo)"),
            ("auditor", "auditor", "Claims auditor"), ("admin", "admin", "Administrator")]
    for username, role, name in demo:
        if not db.one("SELECT id FROM users WHERE username=?", (username,)):
            db.run("INSERT INTO users(username,password_hash,role,display_name) VALUES(?,?,?,?)",
                   (username, hash_password(settings.demo_password), role, name))
