from app.clients.confluence import ConfluenceAPIClient
from app.auth import build_review_entry_url
from app.config import get_app_settings, get_confluence_settings, get_telegram_settings
from app.notifications.telegram import (
    TelegramNotifier,
    build_bot_welcome_message,
    build_release_list_keyboard,
    build_release_list_message,
    build_release_review_message,
    build_start_keyboard,
)
from app.services.importers import import_release_from_apis
from app.storage import get_release, list_items


class TelegramBotService:
    def __init__(self) -> None:
        self.notifier = TelegramNotifier(get_telegram_settings())
        self.confluence = ConfluenceAPIClient(get_confluence_settings())
        self.app_settings = get_app_settings()

    def handle_message(self, message: dict) -> None:
        chat_id = str((message.get("chat") or {}).get("id") or "")
        text = str(message.get("text") or "").strip()
        if not chat_id:
            return
        if text == "/start":
            self.notifier.send_message(
                build_bot_welcome_message(),
                chat_id=chat_id,
                reply_markup=build_start_keyboard(),
            )

    def handle_callback_query(self, callback_query: dict) -> None:
        callback_query_id = str(callback_query.get("id") or "")
        data = str(callback_query.get("data") or "")
        message = callback_query.get("message") or {}
        chat_id = str((message.get("chat") or {}).get("id") or "")
        if not callback_query_id or not chat_id:
            return

        if data == "list_releases":
            releases = self.confluence.list_releases()
            keyboard_entries = [(entry.release_id, entry.release_date) for entry in releases]
            self.notifier.send_message(
                build_release_list_message(),
                chat_id=chat_id,
                reply_markup=build_release_list_keyboard(keyboard_entries),
            )
            self.notifier.answer_callback_query(callback_query_id)
            return

        if data.startswith("release:"):
            release_id = data.split(":", 1)[1]
            import_release_from_apis(release_id)
            release = get_release(release_id)
            items = list_items(release_id)
            release_date = release.release_date if release else "—"
            review_path = f"/review/{release_id}"
            review_url = (
                build_review_entry_url(self.app_settings.base_url, review_path)
                if self.app_settings.base_url
                else ""
            )
            self.notifier.send_message(
                build_release_review_message(release_id, release_date, review_url),
                chat_id=chat_id,
            )
            self.notifier.answer_callback_query(
                callback_query_id,
                text=f"Релиз {release_id} импортирован ({len(items)} пунктов)",
            )
