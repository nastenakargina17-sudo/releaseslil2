import importlib
import io
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

    def test_tracker_module_mapping_uses_custom_business_labels(self) -> None:
        from app.clients.tracker import _map_module_name

        self.assertEqual(
            _map_module_name([{"display": "Client Task"}]),
            "Клиентский запрос",
        )
        self.assertEqual(
            _map_module_name([{"display": "MS Marketplace"}]),
            "Микросервисы",
        )
        self.assertEqual(
            _map_module_name([]),
            "Клиентский запрос",
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

    def test_story_with_no_release_description_becomes_release_candidate(self) -> None:
        from app.clients.tracker import _classify_item_type

        item_type = _classify_item_type(
            {
                "type": {"key": "story"},
                "tags": [],
                "inTheReleaseDescription": "Нет",
                "project": {"primary": {"display": "Product Development"}},
            }
        )

        self.assertEqual(item_type, ItemType.RELEASE_CANDIDATE)


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
                ),
                DigestItem(
                    id="item-2",
                    release_id="2026-04",
                    source_item_ids=["DEV-2"],
                    title="Candidate title",
                    description="",
                    module="Core",
                    type=ItemType.RELEASE_CANDIDATE,
                    category=None,
                    status=ItemStatus.APPROVED,
                    tracker_urls=["https://tracker.yandex.ru/DEV-2"],
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
        self.assertIn('Кандидаты из "Нет"', response.text)

    def test_digest_route_rejects_non_final_items(self) -> None:
        response = self.client.get("/digest/2026-04")

        self.assertEqual(response.status_code, 400)
        self.assertIn("Не все задачи находятся в статусе подтверждения", response.text)

    def test_release_candidate_does_not_block_digest_when_main_items_are_final(self) -> None:
        self.storage.update_item(
            item_id="item-1",
            title="Feature title",
            description="Feature description",
            category=None,
            status=ItemStatus.APPROVED.value,
            is_paid_feature=False,
        )

        response = self.client.get("/digest/2026-04")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Feature title", response.text)
        self.assertNotIn("Candidate title", response.text)

    def test_item_save_supports_ajax_without_redirect(self) -> None:
        response = self.client.post(
            "/review/2026-04/items/item-1",
            data={
                "title": "Updated title",
                "description": "Updated description",
                "category": "",
                "status": "approved",
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["ok"], True)
        self.assertEqual(self.storage.get_item("item-1").title, "Updated title")
        self.assertEqual(self.storage.get_item("item-1").status, ItemStatus.APPROVED)

    def test_release_candidate_can_be_promoted_to_main_release_list(self) -> None:
        response = self.client.post(
            "/review/2026-04/items/item-2",
            data={
                "title": "Candidate title",
                "description": "",
                "category": "",
                "status": "approved",
                "release_candidate_action": "change",
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reload"], True)
        item = self.storage.get_item("item-2")
        self.assertEqual(item.type, ItemType.CHANGE)
        self.assertEqual(item.status, ItemStatus.DRAFT)
        self.assertEqual(item.description, "")

    def test_upload_validates_media_type_and_size(self) -> None:
        response = self.client.post(
            "/review/2026-04/items/item-1/image",
            files={"image": ("notes.txt", io.BytesIO(b"hello"), "text/plain")},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Поддерживаются JPG, PNG, WEBP, GIF, MP4 и WEBM.", response.text)

    def test_uploaded_media_can_be_deleted(self) -> None:
        upload_response = self.client.post(
            "/review/2026-04/items/item-1/image",
            files={"image": ("preview.webp", io.BytesIO(b"fake-image"), "image/webp")},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

        self.assertEqual(upload_response.status_code, 200)
        media_path = upload_response.json()["media_paths"][0]
        stored_path = self.main.UPLOADS_DIR / Path(media_path).name
        self.assertTrue(stored_path.exists())

        delete_response = self.client.post(
            "/review/2026-04/items/item-1/image/delete",
            data={"image_path": media_path},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

        self.assertEqual(delete_response.status_code, 200)
        self.assertEqual(delete_response.json()["media_paths"], [])
        self.assertFalse(stored_path.exists())


if __name__ == "__main__":
    unittest.main()
