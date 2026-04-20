import os
from pathlib import Path
from dataclasses import dataclass


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
TEMPLATES_DIR = BASE_DIR / "templates"
UPLOADS_DIR = BASE_DIR / "uploads"
DB_PATH = DATA_DIR / "release_digest.db"
ENV_PATH = BASE_DIR / ".env"


def ensure_directories() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    UPLOADS_DIR.mkdir(exist_ok=True)


@dataclass(frozen=True)
class TrackerSettings:
    api_base_url: str
    api_token: str
    org_id: str


@dataclass(frozen=True)
class ConfluenceSettings:
    api_base_url: str
    api_token: str
    release_schedule_page_id: str


@dataclass(frozen=True)
class TelegramSettings:
    bot_token: str
    chat_id: str


@dataclass(frozen=True)
class AppSettings:
    base_url: str


def load_env_file() -> None:
    if not ENV_PATH.exists():
        return
    for raw_line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def get_tracker_settings() -> TrackerSettings:
    return TrackerSettings(
        api_base_url=os.getenv("TRACKER_API_BASE_URL", "").rstrip("/"),
        api_token=os.getenv("TRACKER_API_TOKEN", ""),
        org_id=os.getenv("TRACKER_ORG_ID", ""),
    )


def get_confluence_settings() -> ConfluenceSettings:
    return ConfluenceSettings(
        api_base_url=os.getenv("CONFLUENCE_API_BASE_URL", "").rstrip("/"),
        api_token=os.getenv("CONFLUENCE_API_TOKEN", ""),
        release_schedule_page_id=os.getenv("CONFLUENCE_RELEASE_SCHEDULE_PAGE_ID", ""),
    )


def get_telegram_settings() -> TelegramSettings:
    return TelegramSettings(
        bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
    )


def get_app_settings() -> AppSettings:
    return AppSettings(
        base_url=os.getenv("APP_BASE_URL", "").rstrip("/"),
    )
