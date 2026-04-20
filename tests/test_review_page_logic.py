import importlib
import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from fastapi.responses import Response

from app.models import DigestItem, DigestRelease, GroupingMode, ItemStatus, ItemType, SourceItem, SummaryStatus
from app.session import SESSION_COOKIE_NAME, save_session


class ReviewPageLogicTests(unittest.TestCase):
    def test_sanitize_digest_title_removes_tracker_prefix(self) -> None:
        from app.review_utils import sanitize_digest_title

        self.assertEqual(
            sanitize_digest_title("DEV-45172: Не отрабатывает значение по умолчанию в Потребности"),
            "Не отрабатывает значение по умолчанию в Потребности",
        )

    def test_normalize_tracker_issue_url_uses_public_tracker_domain(self) -> None:
        from app.review_utils import normalize_tracker_issue_url

        self.assertEqual(
            normalize_tracker_issue_url("DEV-31469", "https://api.tracker.yandex.net/v3/issues/DEV-31469"),
            "https://tracker.yandex.ru/DEV-31469",
        )

    def test_bugfix_and_technical_items_default_to_approved(self) -> None:
        from app.services.ingest import build_release

        _, items = build_release(
            [
                SourceItem(
                    id="DEV-1",
                    url="https://tracker.yandex.ru/DEV-1",
                    title="DEV-1: Исправить ошибку",
                    description="",
                    module="Ядро",
                    type=ItemType.BUGFIX,
                ),
                SourceItem(
                    id="DEV-2",
                    url="https://tracker.yandex.ru/DEV-2",
                    title="DEV-2: Техническая доработка",
                    description="",
                    module="Ядро",
                    type=ItemType.TECHNICAL_IMPROVEMENT,
                ),
            ],
            release_id="2026-04",
            release_date="2026-04-30",
        )

        self.assertEqual([item.status for item in items], [ItemStatus.APPROVED, ItemStatus.APPROVED])
        self.assertEqual(items[0].title, "Исправить ошибку")
        self.assertEqual(items[1].title, "Техническая доработка")


class DigestGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        os.environ["SESSION_SECRET"] = "test-session-secret"
        os.environ["SESSION_HTTPS_ONLY"] = "false"
        os.environ["YANDEX_CLIENT_ID"] = "test-client-id"
        os.environ["YANDEX_CLIENT_SECRET"] = "test-client-secret"
        os.environ["YANDEX_REDIRECT_URI"] = "http://testserver/auth/yandex/callback"
        os.environ["YANDEX_ALLOWED_EMAILS"] = "employee@example.com"

        import app.config
        import app.storage
        import app.main

        self.config = importlib.reload(app.config)
        self.storage = importlib.reload(app.storage)
        self.main = importlib.reload(app.main)

        temp_path = Path(self.temp_dir.name)
        db_path = temp_path / "test.db"
        uploads_dir = temp_path / "uploads"

        self.config.DB_PATH = db_path
        self.storage.DB_PATH = db_path
        self.config.UPLOADS_DIR = uploads_dir
        self.main.UPLOADS_DIR = uploads_dir

        self.config.ensure_directories()
        self.storage.init_db()
        self.storage.upsert_release(
            DigestRelease(
                id="2026-04",
                release_date="2026-04-30",
                summary="Summary",
                summary_status=SummaryStatus.APPROVED,
            )
        )
        self.storage.replace_release_items(
            "2026-04",
            [
                DigestItem(
                    id="item-1",
                    release_id="2026-04",
                    source_item_ids=["DEV-1"],
                    title="Feature title",
                    description="Feature description",
                    module="Core",
                    type=ItemType.NEW_FEATURE,
                    category=None,
                    status=ItemStatus.DRAFT,
                    tracker_urls=["https://tracker.yandex.ru/DEV-1"],
                    grouping_mode=GroupingMode.SINGLE_TASK,
                )
            ],
        )
        self.client = TestClient(self.main.app)
        response = Response()
        save_session(
            response,
            {"user": {"email": "employee@example.com", "name": "Employee"}},
            self.main.auth_settings,
        )
        self.client.cookies.set(SESSION_COOKIE_NAME, response.headers["set-cookie"].split(";", 1)[0].split("=", 1)[1])

    def tearDown(self) -> None:
        self.client.close()
        self.temp_dir.cleanup()

    def test_review_page_renders_updated_controls(self) -> None:
        response = self.client.get("/review/2026-04")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Подтвердить дайджест", response.text)
        self.assertIn("Сохранить изменения", response.text)
        self.assertIn("Исключить из релиза", response.text)
        self.assertIn("Категория ценности", response.text)

    def test_digest_route_rejects_non_final_items(self) -> None:
        response = self.client.get("/digest/2026-04")

        self.assertEqual(response.status_code, 400)
        self.assertIn("Не все задачи находятся в статусе подтверждения", response.text)


if __name__ == "__main__":
    unittest.main()
