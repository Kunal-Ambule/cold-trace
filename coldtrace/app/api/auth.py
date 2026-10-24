from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from .. import db, security
from .schemas import LoginReq

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
def login(body: LoginReq):
    u = db.one("SELECT * FROM users WHERE username=?", (body.username,))
    if not u or not security.check_password(body.password, u["password_hash"]):
        raise HTTPException(401, "Invalid username or password")
    return {"token": security.make_token(u), "role": u["role"], "display_name": u["display_name"]}


@router.get("/me")
def me(user: dict = Depends(security.current_user)):
    return user
