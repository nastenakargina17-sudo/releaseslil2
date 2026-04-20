import importlib
import tempfile
import unittest
from typing import Optional
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


class TelegramWebhookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        import app.config
        import app.main

        self.config = importlib.reload(app.config)
        temp_path = Path(self.temp_dir.name)
        self.config.DATA_DIR = temp_path / "data"
        self.config.UPLOADS_DIR = temp_path / "uploads"
        self.main = importlib.reload(app.main)
        self.client = TestClient(self.main.app)

    def tearDown(self) -> None:
        self.client.close()
        self.temp_dir.cleanup()

    def test_duplicate_update_is_ignored(self) -> None:
        bot_instance = MagicMock()

        with patch.object(self.main, "TelegramBotService", return_value=bot_instance):
            first = self.client.post(
                "/telegram/webhook",
                json={
                    "update_id": 42,
                    "message": {"chat": {"id": 390144191}, "text": "/start"},
                },
            )
            second = self.client.post(
                "/telegram/webhook",
                json={
                    "update_id": 42,
                    "message": {"chat": {"id": 390144191}, "text": "/start"},
                },
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json(), {"ok": True})
        self.assertEqual(second.json(), {"ok": True, "duplicate": True})
        bot_instance.handle_message.assert_called_once()

    def test_release_callback_acknowledged_before_import(self) -> None:
        import_calls = []

        class OrderedNotifier:
            def __init__(self) -> None:
                self.calls = []

            def answer_callback_query(self, callback_query_id: str, text: Optional[str] = None) -> None:
                self.calls.append(("answer", callback_query_id, text))

            def send_message(self, text: str, chat_id: Optional[str] = None, reply_markup=None) -> None:
                self.calls.append(("send", chat_id, text))

        with patch("app.services.telegram_bot.get_app_settings") as get_app_settings, patch(
            "app.services.telegram_bot.get_telegram_settings"
        ), patch("app.services.telegram_bot.get_confluence_settings"), patch(
            "app.services.telegram_bot.ConfluenceAPIClient"
        ), patch("app.services.telegram_bot.TelegramNotifier") as notifier_cls, patch(
            "app.services.telegram_bot.import_release_from_apis"
        ) as import_release, patch("app.services.telegram_bot.get_release") as get_release, patch(
            "app.services.telegram_bot.list_items"
        ) as list_items:
            notifier = OrderedNotifier()
            notifier_cls.return_value = notifier
            get_app_settings.return_value.base_url = "https://skillaz"
            get_release.return_value = None
            list_items.return_value = []

            def import_side_effect(release_id: str) -> None:
                import_calls.append(release_id)
                notifier.calls.append(("import", release_id))

            import_release.side_effect = import_side_effect

            response = self.client.post(
                "/telegram/webhook",
                json={
                    "update_id": 100,
                    "callback_query": {
                        "id": "cbq-1",
                        "data": "release:2026-04",
                        "message": {"chat": {"id": 390144191}},
                    },
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(import_calls, ["2026-04"])
        self.assertEqual(notifier.calls[0][0], "answer")
        self.assertEqual(notifier.calls[1], ("import", "2026-04"))


if __name__ == "__main__":
    unittest.main()
