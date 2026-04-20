from __future__ import annotations

from secrets import token_urlsafe
from urllib.parse import urlencode

import httpx

from app.config import AuthSettings


YANDEX_AUTHORIZE_URL = "https://oauth.yandex.com/authorize"
YANDEX_TOKEN_URL = "https://oauth.yandex.com/token"
YANDEX_USERINFO_URL = "https://login.yandex.ru/info"


class AuthConfigurationError(RuntimeError):
    pass


class OAuthExchangeError(RuntimeError):
    pass


def build_yandex_login_url(settings: AuthSettings, state: str) -> str:
    _ensure_oauth_settings(settings)
    query = urlencode(
        {
            "response_type": "code",
            "client_id": settings.yandex_client_id,
            "redirect_uri": settings.yandex_redirect_uri,
            "scope": "login:email login:info",
            "state": state,
        }
    )
    return f"{YANDEX_AUTHORIZE_URL}?{query}"


def build_review_entry_url(base_url: str, review_path: str) -> str:
    normalized_base_url = base_url.rstrip("/")
    query = urlencode({"next": review_path})
    return f"{normalized_base_url}/auth/yandex/login?{query}"


async def exchange_code_for_token(code: str, settings: AuthSettings) -> str:
    _ensure_oauth_settings(settings)
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            YANDEX_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": settings.yandex_client_id,
                "client_secret": settings.yandex_client_secret,
                "redirect_uri": settings.yandex_redirect_uri,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    if response.status_code >= 400:
        raise OAuthExchangeError("Failed to exchange Yandex OAuth code for an access token")
    payload = response.json()
    access_token = payload.get("access_token", "")
    if not access_token:
        raise OAuthExchangeError("Yandex OAuth response did not include an access token")
    return access_token


async def fetch_yandex_user(access_token: str) -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            YANDEX_USERINFO_URL,
            params={"format": "json"},
            headers={"Authorization": f"OAuth {access_token}"},
        )
    if response.status_code >= 400:
        raise OAuthExchangeError("Failed to load Yandex user profile")
    return response.json()


def generate_state_token() -> str:
    return token_urlsafe(24)


def extract_user_email(user_info: dict) -> str:
    default_email = (user_info.get("default_email") or "").strip().lower()
    if default_email:
        return default_email
    emails = user_info.get("emails") or []
    for email in emails:
        normalized = str(email).strip().lower()
        if normalized:
            return normalized
    return ""


def extract_display_name(user_info: dict, fallback_email: str) -> str:
    for field in ("real_name", "display_name", "login"):
        value = str(user_info.get(field) or "").strip()
        if value:
            return value
    return fallback_email


def is_allowed_email(email: str, settings: AuthSettings) -> bool:
    return bool(email) and email.lower() in settings.allowed_review_emails


def _ensure_oauth_settings(settings: AuthSettings) -> None:
    if settings.yandex_client_id and settings.yandex_client_secret and settings.yandex_redirect_uri:
        return
    raise AuthConfigurationError("Yandex OAuth is not configured")
