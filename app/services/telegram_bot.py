from app.clients.confluence import ConfluenceAPIClient
from app.config import get_app_settings, get_confluence_settings, get_telegram_settings
from app.notifications.telegram import (
    TelegramNotifier,
    build_bot_menu_keyboard,
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
        command = _extract_bot_command(text)
        if command == "/start":
            welcome_message = build_bot_welcome_message()
            reply_markup = build_start_keyboard()
            welcome_image_path = self.notifier.settings.welcome_image_path
            if welcome_image_path:
                self.notifier.send_photo(
                    welcome_image_path,
                    caption=welcome_message,
                    chat_id=chat_id,
                    reply_markup=reply_markup,
                )
                return
            self.notifier.send_message(
                welcome_message,
                chat_id=chat_id,
                reply_markup=reply_markup,
            )
            return

        if command == "/releases" or text.casefold() in {"показать релизы", "релизы"}:
            self._send_release_list(chat_id)

    def handle_callback_query(self, callback_query: dict) -> None:
        callback_query_id = str(callback_query.get("id") or "")
        data = str(callback_query.get("data") or "")
        message = callback_query.get("message") or {}
        chat_id = str((message.get("chat") or {}).get("id") or "")
        if not callback_query_id or not chat_id:
            return

        if data == "list_releases":
            self.notifier.answer_callback_query(callback_query_id)
            self._send_release_list(chat_id)
            return

        if data.startswith("release:"):
            release_id = data.split(":", 1)[1]
            self.notifier.answer_callback_query(
                callback_query_id,
                text=f"Импортирую релиз {release_id}…",
            )
            import_release_from_apis(release_id, preserve_existing_copy=True)
            release = get_release(release_id)
            items = list_items(release_id)
            release_date = release.release_date if release else "—"
            review_path = f"/review/{release_id}"
            review_url = _build_absolute_app_url(self.app_settings.base_url, review_path)
            self.notifier.send_message(
                build_release_review_message(release_id, release_date, review_url),
                chat_id=chat_id,
                reply_markup=build_bot_menu_keyboard(),
            )

    def _send_release_list(self, chat_id: str) -> None:
        releases = self.confluence.list_releases()
        keyboard_entries = [(entry.release_id, entry.release_date) for entry in releases]
        self.notifier.send_message(
            build_release_list_message(),
            chat_id=chat_id,
            reply_markup=build_release_list_keyboard(keyboard_entries),
        )


def _extract_bot_command(text: str) -> str:
    first_token = text.split(maxsplit=1)[0].casefold() if text else ""
    if not first_token.startswith("/"):
        return ""
    return first_token.split("@", 1)[0]


def _build_absolute_app_url(base_url: str, path: str) -> str:
    if not base_url:
        return path
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"
