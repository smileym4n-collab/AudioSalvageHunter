from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from typing import Any

from fastapi import HTTPException, Request
from starlette.responses import RedirectResponse


SAFE_SECRET_MASK = "configured"


def auth_enabled() -> bool:
    return os.getenv("AUTH_ENABLED", "false").lower() == "true"


def verify_password(password: str, stored_hash: str) -> bool:
    if stored_hash.startswith("sha256$"):
        expected = stored_hash.split("$", 1)[1]
        actual = hashlib.sha256(password.encode("utf-8")).hexdigest()
        return hmac.compare_digest(actual, expected)
    if stored_hash.startswith("pbkdf2_sha256$"):
        _, iterations, salt, expected = stored_hash.split("$", 3)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), int(iterations)).hex()
        return hmac.compare_digest(actual, expected)
    return False


def require_login(request: Request) -> None:
    if not auth_enabled():
        return
    if request.session.get("authenticated") is True:
        return
    raise HTTPException(status_code=401, detail="Login required")


def login_redirect(request: Request) -> RedirectResponse | None:
    if not auth_enabled() or request.session.get("authenticated") is True:
        return None
    return RedirectResponse(f"/login?next={request.url.path}", status_code=303)


def csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return str(token)


def validate_csrf(request: Request, form: dict[str, Any]) -> None:
    expected = request.session.get("csrf_token")
    supplied = form.get("csrf_token")
    if not expected or not supplied or not hmac.compare_digest(str(expected), str(supplied)):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")


def secret_status(name: str) -> str:
    return SAFE_SECRET_MASK if os.getenv(name) else "missing"


def safe_next_path(value: object, default: str = "/") -> str:
    text = str(value or default)
    if not text.startswith("/") or text.startswith("//") or "\\" in text:
        return default
    return text
