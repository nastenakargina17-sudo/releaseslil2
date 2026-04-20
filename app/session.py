from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any

from fastapi import Request
from fastapi.responses import Response

from app.config import AuthSettings


SESSION_COOKIE_NAME = "review_session"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 12


def load_session(request: Request, settings: AuthSettings) -> dict[str, Any]:
    raw_cookie = request.cookies.get(SESSION_COOKIE_NAME, "")
    if not raw_cookie or "." not in raw_cookie:
        return {}

    encoded_payload, encoded_signature = raw_cookie.split(".", 1)
    expected_signature = _sign(encoded_payload, settings.session_secret)
    if not hmac.compare_digest(encoded_signature, expected_signature):
        return {}

    try:
        payload = base64.urlsafe_b64decode(_pad_base64(encoded_payload)).decode("utf-8")
        session = json.loads(payload)
    except (ValueError, json.JSONDecodeError):
        return {}

    if not isinstance(session, dict):
        return {}
    return session


def save_session(response: Response, session: dict[str, Any], settings: AuthSettings) -> None:
    payload = json.dumps(session, separators=(",", ":"), ensure_ascii=True)
    encoded_payload = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")
    encoded_signature = _sign(encoded_payload, settings.session_secret)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        f"{encoded_payload}.{encoded_signature}",
        httponly=True,
        samesite="lax",
        secure=settings.session_https_only,
        max_age=SESSION_MAX_AGE_SECONDS,
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE_NAME)


def _sign(encoded_payload: str, secret: str) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        encoded_payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _pad_base64(value: str) -> str:
    return value + "=" * (-len(value) % 4)
