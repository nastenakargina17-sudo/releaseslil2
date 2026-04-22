import json
import httpx
from pathlib import Path
from typing import Any, Optional

from app.config import TelegramSettings
from app.models import DigestItem, DigestRelease, ItemStatus, ItemType, SummaryStatus


class TelegramNotificationError(RuntimeError):
    pass


class TelegramNotifier:
    def __init__(self, settings: TelegramSettings) -> None:
        self.settings = settings

    def send_message(
        self,
        text: str,
        chat_id: Optional[str] = None,
        reply_markup: Optional[dict[str, Any]] = None,
    ) -> None:
        target_chat_id = chat_id or self.settings.chat_id
        if not self.settings.bot_token or not target_chat_id:
            raise TelegramNotificationError("Telegram settings are not configured")
        url = f"https://api.telegram.org/bot{self.settings.bot_token}/sendMessage"
        payload = {
            "chat_id": target_chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        with httpx.Client(timeout=30.0) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()

    def send_photo(
        self,
        photo_path: str,
        caption: Optional[str] = None,
        chat_id: Optional[str] = None,
        reply_markup: Optional[dict[str, Any]] = None,
    ) -> None:
        target_chat_id = chat_id or self.settings.chat_id
        if not self.settings.bot_token or not target_chat_id:
            raise TelegramNotificationError("Telegram settings are not configured")
        path = Path(photo_path)
        if not path.is_file():
            raise TelegramNotificationError(f"Telegram photo is not available: {path}")
        url = f"https://api.telegram.org/bot{self.settings.bot_token}/sendPhoto"
        data: dict[str, Any] = {"chat_id": target_chat_id}
        if caption:
            data["caption"] = caption
        if reply_markup:
            data["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
        with path.open("rb") as photo_file, httpx.Client(timeout=30.0) as client:
            response = client.post(
                url,
                data=data,
                files={"photo": (path.name, photo_file, "image/png")},
            )
            response.raise_for_status()

    def answer_callback_query(self, callback_query_id: str, text: Optional[str] = None) -> None:
        if not self.settings.bot_token:
            raise TelegramNotificationError("Telegram settings are not configured")
        url = f"https://api.telegram.org/bot{self.settings.bot_token}/answerCallbackQuery"
        payload: dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        with httpx.Client(timeout=30.0) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()

    def set_webhook(self, webhook_url: str) -> None:
        if not self.settings.bot_token:
            raise TelegramNotificationError("Telegram settings are not configured")
        url = f"https://api.telegram.org/bot{self.settings.bot_token}/setWebhook"
        payload = {"url": webhook_url}
        with httpx.Client(timeout=30.0) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()


def build_release_import_message(release_id: str, release_date: str, item_count: int) -> str:
    del release_date
    return (
        f"☑️ Релиз {release_id} импортирован.\n"
        f"Подготовлено пунктов для ревью: {item_count}.\n"
        "Собираю итоговую версию для ревью..."
    )


def build_bot_welcome_message() -> str:
    return (
        "Привет. Я Нотис — архивариус релизов.\n\n"
        "Я собираю изменения, привожу их в порядок и превращаю в понятные "
        "релиз-дайджесты.\n\n"
        "Ниже ты найдёшь список доступных релизов."
    )


def build_release_list_message() -> str:
    return "Доступные релизы уже собраны. Выбери нужный."


def build_release_review_message(release_id: str, release_date: str, review_url: str) -> str:
    return (
        f"Релиз {release_id} готов к ревью.\n"
        f"Плановая дата релиза: {release_date}\n"
        f"Открыть страницу ревью: {review_url}"
    )


def build_release_list_keyboard(entries: list[tuple[str, str]]) -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [{"text": release_date, "callback_data": f"release:{release_id}"}]
            for release_id, release_date in entries
        ]
    }


def build_start_keyboard() -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [{"text": "Показать список релизов", "callback_data": "list_releases"}]
        ]
    }


def build_review_status_message(
    release: DigestRelease,
    items: list[DigestItem],
    review_url: Optional[str] = None,
) -> str:
    approved = sum(1 for item in items if item.status == ItemStatus.APPROVED)
    excluded = sum(1 for item in items if item.status == ItemStatus.EXCLUDED)
    reviewed = sum(1 for item in items if item.status == ItemStatus.REVIEWED)
    draft = sum(1 for item in items if item.status == ItemStatus.DRAFT)
    total = len(items)
    lines = [
        f"Ревью релиза {release.id}",
        f"Плановая дата релиза: {release.release_date}",
        f"Summary: {release.summary_status.value}",
        f"Пункты: всего {total}, approved {approved}, excluded {excluded}, reviewed {reviewed}, draft {draft}",
    ]
    if review_url:
        lines.append(f"Открыть ревью: {review_url}")
    return "\n".join(lines)


def build_digest_ready_message(
    release: DigestRelease,
    items: list[DigestItem],
    digest_url: Optional[str] = None,
) -> str:
    new_features = sum(1 for item in items if item.type == ItemType.NEW_FEATURE)
    changes = sum(1 for item in items if item.type == ItemType.CHANGE)
    bugfixes = sum(1 for item in items if item.type == ItemType.BUGFIX)
    technical = sum(1 for item in items if item.type == ItemType.TECHNICAL_IMPROVEMENT)
    lines = [
        f"Дайджест по релизу {release.id} готов",
        f"Плановая дата релиза: {release.release_date}",
        f"Summary: {release.summary_status.value}",
        f"Новые фичи: {new_features}",
        f"Изменения: {changes}",
        f"Багфиксы: {bugfixes}",
        f"Технические доработки: {technical}",
    ]
    narrative_items = [
        item for item in items if item.type in {ItemType.NEW_FEATURE, ItemType.CHANGE}
    ]
    if narrative_items:
        lines.append("")
        lines.append("Коротко по содержанию:")
        for item in narrative_items[:5]:
            paid = " [платно]" if item.is_paid_feature else ""
            lines.append(f"- {item.title}{paid} ({item.module})")
    if digest_url:
        lines.append(f"Открыть digest: {digest_url}")
    return "\n".join(lines)


def release_is_ready_for_digest(release: DigestRelease, items: list[DigestItem]) -> bool:
    if release.summary_status != SummaryStatus.APPROVED:
        return False
    return all(
        item.type == ItemType.RELEASE_CANDIDATE
        or item.status in {ItemStatus.APPROVED, ItemStatus.EXCLUDED}
        for item in items
    )
