"""Two-role login: the admin does everything; the sender only reads, rewrites,
and sends the drafted emails.

Users come from .env:
  ADMIN_EMAIL / ADMIN_PASSWORD     full access (import, research, delete)
  SENDER_EMAIL / SENDER_PASSWORD   view, rewrite drafts, open in Gmail, mark sent
  SESSION_SECRET                   any long random string (signs the login cookie)
"""

import hashlib
import hmac
import os
import time

from fastapi import HTTPException, Request

COOKIE = "session"
MAX_AGE = 30 * 24 * 3600  # stay logged in for 30 days


def _users() -> dict[str, tuple[str, str]]:
    """email -> (password, role)"""
    users = {}
    for prefix, role in (("ADMIN", "admin"), ("SENDER", "sender")):
        email = os.getenv(f"{prefix}_EMAIL", "").strip().lower()
        password = os.getenv(f"{prefix}_PASSWORD", "")
        if email and password:
            users[email] = (password, role)
    return users


def _sign(payload: str) -> str:
    secret = os.getenv("SESSION_SECRET", "")
    if not secret:
        raise RuntimeError("Set SESSION_SECRET in backend/.env")
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def login(email: str, password: str) -> tuple[str, str]:
    """Check credentials. Returns (cookie value, role)."""
    email = email.strip().lower()
    user = _users().get(email)
    if not user or not hmac.compare_digest(user[0], password):
        raise HTTPException(401, "Wrong email or password")
    payload = f"{email}|{user[1]}|{int(time.time()) + MAX_AGE}"
    return f"{payload}|{_sign(payload)}", user[1]


def current_user(request: Request) -> dict[str, str] | None:
    try:
        email, role, expires, sig = request.cookies.get(COOKIE, "").split("|")
    except ValueError:
        return None
    payload = f"{email}|{role}|{expires}"
    if not hmac.compare_digest(sig, _sign(payload)) or int(expires) < time.time():
        return None
    # A user removed from .env loses access even with an old cookie.
    if _users().get(email, (None, None))[1] != role:
        return None
    return {"email": email, "role": role}


def require_admin(request: Request) -> None:
    if request.state.user["role"] != "admin":
        raise HTTPException(403, "Only the admin can do this")


def extension_token_ok(token: str) -> bool:
    """The Apollo duplicate-checker extension sends EXTENSION_TOKEN from .env."""
    expected = os.getenv("EXTENSION_TOKEN", "")
    return bool(expected) and hmac.compare_digest(token.strip(), expected)
