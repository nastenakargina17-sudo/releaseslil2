import importlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from fastapi.responses import Response

from app.models import DigestItem, DigestRelease, GroupingMode, ItemStatus, ItemType, PublicationStatus, SourceItem, SummaryStatus, ValueCategory
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

    def test_client_value_category_labels_are_human_readable(self) -> None:
        from app.models import ValueCategory
        from app.review_utils import CLIENT_CATEGORY_LABELS

        self.assertEqual(CLIENT_CATEGORY_LABELS[ValueCategory.TIME_SAVING], "Экономия времени")
        self.assertEqual(CLIENT_CATEGORY_LABELS[ValueCategory.ERROR_REDUCTION], "Меньше ошибок")
        self.assertEqual(CLIENT_CATEGORY_LABELS[ValueCategory.CLARITY_TRANSPARENCY], "Больше прозрачности")
        self.assertEqual(CLIENT_CATEGORY_LABELS[ValueCategory.DAILY_WORK_CONVENIENCE], "Удобнее в ежедневной работе")
        self.assertEqual(CLIENT_CATEGORY_LABELS[ValueCategory.BETTER_CONTROL], "Больше контроля")
        self.assertEqual(CLIENT_CATEGORY_LABELS[ValueCategory.LESS_COMMUNICATION_OVERHEAD], "Меньше ручных согласований")

    def test_digest_media_helper_detects_video_paths(self) -> None:
        from app.review_utils import is_video_media_path

        self.assertTrue(is_video_media_path("/uploads/demo.mp4"))
        self.assertTrue(is_video_media_path("/uploads/demo.WEBM"))
        self.assertFalse(is_video_media_path("/uploads/demo.png"))
        self.assertFalse(is_video_media_path(""))


class DigestGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        os.environ["SESSION_SECRET"] = "test-session-secret"
        os.environ["SESSION_HTTPS_ONLY"] = "false"
        os.environ["YANDEX_CLIENT_ID"] = "test-client-id"
        os.environ["YANDEX_CLIENT_SECRET"] = "test-client-secret"
        os.environ["YANDEX_REDIRECT_URI"] = "http://testserver/auth/yandex/callback"
        os.environ["YANDEX_ALLOWED_EMAILS"] = "employee@example.com,other@example.com"

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
        self._authenticate_client(self.client, "employee@example.com", "Employee")

    def _authenticate_client(self, client: TestClient, email: str, name: str) -> None:
        response = Response()
        save_session(
            response,
            {"user": {"email": email, "name": name}},
            self.main.auth_settings,
        )
        client.cookies.set(SESSION_COOKIE_NAME, response.headers["set-cookie"].split(";", 1)[0].split("=", 1)[1])

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
        self.assertIn('Задачи из "Нет"', response.text)
        self.assertIn("На странице сейчас", response.text)
        self.assertNotIn("Выйти из ревью", response.text)

    def test_release_defaults_to_draft_publication_status(self) -> None:
        release = self.storage.get_release("2026-04")

        self.assertEqual(release.publication_status, PublicationStatus.DRAFT)
        self.assertEqual(release.publication_status_note, "")
        self.assertEqual(release.preview_prepared_by, "")
        self.assertEqual(release.preview_prepared_at, "")

    def test_publication_status_can_be_updated_with_a_note(self) -> None:
        self.storage.update_release_publication_status(
            release_id="2026-04",
            status=PublicationStatus.PREVIEW,
            note="Preview сформирован.",
            preview_prepared_by="Employee",
        )

        release = self.storage.get_release("2026-04")

        self.assertEqual(release.publication_status, PublicationStatus.PREVIEW)
        self.assertEqual(release.publication_status_note, "Preview сформирован.")
        self.assertEqual(release.preview_prepared_by, "Employee")
        self.assertNotEqual(release.preview_prepared_at, "")

    def test_published_digest_snapshot_round_trips(self) -> None:
        from app.models import PublishedDigest

        snapshot = PublishedDigest(
            release_id="2026-04",
            release_date="2026-04-30",
            summary="Published summary",
            content={
                "sections": [
                    {
                        "id": "new_features",
                        "title": "Что нового",
                        "items": [{"title": "Published feature", "media": []}],
                    }
                ],
                "metrics": {"items_count": 1},
            },
            published_by="Employee",
            published_at="1710000000",
        )

        self.storage.save_published_digest(snapshot)
        loaded = self.storage.get_published_digest("2026-04")
        archive = self.storage.list_published_digests()

        self.assertEqual(loaded.release_id, "2026-04")
        self.assertEqual(loaded.summary, "Published summary")
        self.assertEqual(loaded.content["sections"][0]["items"][0]["title"], "Published feature")
        self.assertEqual(loaded.published_by, "Employee")
        self.assertEqual(archive[0].release_id, "2026-04")

    def test_publication_snapshot_contains_card_fields_and_copies_media(self) -> None:
        media_source = self.config.UPLOADS_DIR / "source.png"
        media_source.write_bytes(b"image-bytes")
        self.storage.update_item(
            item_id="item-1",
            title="Feature title",
            description="Feature description",
            category=ValueCategory.TIME_SAVING.value,
            status=ItemStatus.APPROVED.value,
            is_paid_feature=True,
        )
        self.storage.add_item_image("item-1", "/uploads/source.png")

        from app.services.publication import build_published_digest_snapshot

        release = self.storage.get_release("2026-04")
        items = self.storage.list_items("2026-04")
        snapshot = build_published_digest_snapshot(
            release=release,
            items=items,
            published_by="Employee",
            uploads_dir=self.config.UPLOADS_DIR,
        )

        first_item = snapshot.content["sections"][0]["items"][0]
        self.assertEqual(first_item["title"], "Feature title")
        self.assertEqual(first_item["module"], "Core")
        self.assertEqual(first_item["value_category_label"], "Экономия времени")
        self.assertEqual(first_item["is_paid_feature"], True)
        self.assertEqual(len(first_item["media"]), 1)
        self.assertTrue(first_item["media"][0]["path"].startswith("/uploads/published/2026-04/"))
        copied_path = self.config.UPLOADS_DIR / Path(first_item["media"][0]["path"].replace("/uploads/", ""))
        self.assertEqual(copied_path.read_bytes(), b"image-bytes")

    def test_publication_snapshot_fails_when_media_file_is_missing(self) -> None:
        self.storage.update_item(
            item_id="item-1",
            title="Feature title",
            description="Feature description",
            category=ValueCategory.TIME_SAVING.value,
            status=ItemStatus.APPROVED.value,
            is_paid_feature=False,
        )
        self.storage.add_item_image("item-1", "/uploads/missing.png")

        from app.services.publication import PublicationError, build_published_digest_snapshot

        release = self.storage.get_release("2026-04")
        items = self.storage.list_items("2026-04")
        with self.assertRaises(PublicationError):
            build_published_digest_snapshot(
                release=release,
                items=items,
                published_by="Employee",
                uploads_dir=self.config.UPLOADS_DIR,
            )

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

    def test_digest_publishes_only_approved_items_in_public_sections(self) -> None:
        self.storage.replace_release_items(
            "2026-04",
            [
                DigestItem(
                    id="feature-approved",
                    release_id="2026-04",
                    source_item_ids=["DEV-10"],
                    title="Approved feature",
                    description="Client-facing feature text",
                    module="Подбор",
                    type=ItemType.NEW_FEATURE,
                    category=ValueCategory.TIME_SAVING,
                    status=ItemStatus.APPROVED,
                    tracker_urls=["https://tracker.yandex.ru/DEV-10"],
                    grouping_mode=GroupingMode.SINGLE_TASK,
                ),
                DigestItem(
                    id="change-approved",
                    release_id="2026-04",
                    source_item_ids=["DEV-11"],
                    title="Approved change",
                    description="Client-facing change text",
                    module="Отчеты",
                    type=ItemType.CHANGE,
                    category=ValueCategory.CLARITY_TRANSPARENCY,
                    status=ItemStatus.APPROVED,
                    tracker_urls=["https://tracker.yandex.ru/DEV-11"],
                    grouping_mode=GroupingMode.SINGLE_TASK,
                ),
                DigestItem(
                    id="feature-excluded",
                    release_id="2026-04",
                    source_item_ids=["DEV-12"],
                    title="Excluded feature",
                    description="Hidden text",
                    module="Подбор",
                    type=ItemType.NEW_FEATURE,
                    category=ValueCategory.TIME_SAVING,
                    status=ItemStatus.EXCLUDED,
                    tracker_urls=["https://tracker.yandex.ru/DEV-12"],
                    grouping_mode=GroupingMode.SINGLE_TASK,
                ),
                DigestItem(
                    id="bugfix-approved",
                    release_id="2026-04",
                    source_item_ids=["DEV-13"],
                    title="Approved fix",
                    description="",
                    module="Интеграции",
                    type=ItemType.BUGFIX,
                    category=None,
                    status=ItemStatus.APPROVED,
                    tracker_urls=["https://tracker.yandex.ru/DEV-13"],
                    grouping_mode=GroupingMode.SINGLE_TASK,
                ),
            ],
        )

        response = self.client.get("/digest/2026-04")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Что нового", response.text)
        self.assertIn("Что стало удобнее", response.text)
        self.assertIn("Исправления и технические улучшения", response.text)
        self.assertIn("Approved feature", response.text)
        self.assertIn("Approved change", response.text)
        self.assertIn("Approved fix", response.text)
        self.assertNotIn("Excluded feature", response.text)

    def test_digest_hides_tracker_links_for_product_items_but_shows_support_links(self) -> None:
        self.storage.replace_release_items(
            "2026-04",
            [
                DigestItem(
                    id="feature-approved",
                    release_id="2026-04",
                    source_item_ids=["DEV-20"],
                    title="New analytics",
                    description="Teams can understand progress faster.",
                    module="Аналитика",
                    type=ItemType.NEW_FEATURE,
                    category=ValueCategory.CLARITY_TRANSPARENCY,
                    status=ItemStatus.APPROVED,
                    tracker_urls=["https://tracker.yandex.ru/DEV-20"],
                    grouping_mode=GroupingMode.SINGLE_TASK,
                ),
                DigestItem(
                    id="bugfix-approved",
                    release_id="2026-04",
                    source_item_ids=["DEV-21"],
                    title="Fixed export",
                    description="",
                    module="Экспорт",
                    type=ItemType.BUGFIX,
                    category=None,
                    status=ItemStatus.APPROVED,
                    tracker_urls=["https://tracker.yandex.ru/DEV-21"],
                    grouping_mode=GroupingMode.SINGLE_TASK,
                ),
            ],
        )

        response = self.client.get("/digest/2026-04")

        self.assertEqual(response.status_code, 200)
        self.assertIn("New analytics", response.text)
        self.assertNotIn("https://tracker.yandex.ru/DEV-20", response.text)
        self.assertIn("https://tracker.yandex.ru/DEV-21", response.text)

    def test_digest_renders_value_badge_and_paid_feature_badge(self) -> None:
        self.storage.update_item(
            item_id="item-1",
            title="Feature title",
            description="Feature description",
            category=ValueCategory.TIME_SAVING.value,
            status=ItemStatus.APPROVED.value,
            is_paid_feature=True,
        )

        response = self.client.get("/digest/2026-04")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Экономия времени", response.text)
        self.assertIn("Платная функция", response.text)

    def test_digest_support_section_is_collapsed_by_default(self) -> None:
        self.storage.replace_release_items(
            "2026-04",
            [
                DigestItem(
                    id="bugfix-approved",
                    release_id="2026-04",
                    source_item_ids=["DEV-30"],
                    title="Fixed notification",
                    description="",
                    module="Уведомления",
                    type=ItemType.BUGFIX,
                    category=None,
                    status=ItemStatus.APPROVED,
                    tracker_urls=["https://tracker.yandex.ru/DEV-30"],
                    grouping_mode=GroupingMode.SINGLE_TASK,
                ),
            ],
        )

        response = self.client.get("/digest/2026-04")

        self.assertEqual(response.status_code, 200)
        self.assertIn("<details", response.text)
        self.assertIn("Исправления и технические улучшения", response.text)
        self.assertNotIn("<details open", response.text)

    def test_digest_omits_empty_publication_sections(self) -> None:
        self.storage.replace_release_items(
            "2026-04",
            [
                DigestItem(
                    id="bugfix-approved",
                    release_id="2026-04",
                    source_item_ids=["DEV-40"],
                    title="Fixed reminder",
                    description="",
                    module="Напоминания",
                    type=ItemType.BUGFIX,
                    category=None,
                    status=ItemStatus.APPROVED,
                    tracker_urls=["https://tracker.yandex.ru/DEV-40"],
                    grouping_mode=GroupingMode.SINGLE_TASK,
                ),
            ],
        )

        response = self.client.get("/digest/2026-04")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Нет новых фич", response.text)
        self.assertNotIn("Нет изменений", response.text)
        self.assertNotIn('id="new-features-heading"', response.text)
        self.assertNotIn('id="changes-heading"', response.text)
        self.assertIn("Исправления и технические улучшения", response.text)

    def test_item_save_supports_ajax_without_redirect(self) -> None:
        item = self.storage.get_item("item-1")
        response = self.client.post(
            "/review/2026-04/items/item-1",
            data={
                "title": "Updated title",
                "description": "Updated description",
                "category": "",
                "status": "approved",
                "object_version": str(item.version),
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["ok"], True)
        self.assertEqual(self.storage.get_item("item-1").title, "Updated title")
        self.assertEqual(self.storage.get_item("item-1").status, ItemStatus.APPROVED)
        self.assertGreater(response.json()["version"], item.version)

    def test_item_save_rejects_stale_version(self) -> None:
        item = self.storage.get_item("item-1")
        self.storage.update_item(
            item_id="item-1",
            title="Someone else title",
            description="Feature description",
            category=None,
            status=ItemStatus.DRAFT.value,
            is_paid_feature=False,
            expected_version=item.version,
        )

        response = self.client.post(
            "/review/2026-04/items/item-1",
            data={
                "title": "My stale title",
                "description": "Updated description",
                "category": "",
                "status": "approved",
                "object_version": str(item.version),
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn("уже изменил другой ревьюер", response.json()["message"])
        self.assertEqual(self.storage.get_item("item-1").title, "Someone else title")

    def test_summary_save_rejects_stale_version(self) -> None:
        release = self.storage.get_release("2026-04")
        self.storage.update_release_summary(
            "2026-04",
            "Someone else summary",
            SummaryStatus.APPROVED.value,
            expected_version=release.version,
        )

        response = self.client.post(
            "/review/2026-04/summary",
            data={
                "summary": "My stale summary",
                "summary_status": SummaryStatus.REVIEWED.value,
                "object_version": str(release.version),
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn("Summary уже изменил другой ревьюер", response.json()["message"])
        self.assertEqual(self.storage.get_release("2026-04").summary, "Someone else summary")

    def test_review_lock_shows_current_editor_and_allows_takeover(self) -> None:
        first_response = self.client.post(
            "/review/2026-04/locks",
            data={"object_type": "item", "object_id": "item-1"},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(first_response.json()["lock"]["owner_name"], "Employee")

        other_client = TestClient(self.main.app)
        self.addCleanup(other_client.close)
        self._authenticate_client(other_client, "other@example.com", "Other")

        blocked_response = other_client.post(
            "/review/2026-04/locks",
            data={"object_type": "item", "object_id": "item-1"},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

        self.assertEqual(blocked_response.status_code, 409)
        self.assertEqual(blocked_response.json()["lock"]["owner_name"], "Employee")
        self.assertFalse(blocked_response.json()["lock"]["is_mine"])

        takeover_response = other_client.post(
            "/review/2026-04/locks",
            data={"object_type": "item", "object_id": "item-1", "force": "true"},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

        self.assertEqual(takeover_response.status_code, 200)
        self.assertEqual(takeover_response.json()["lock"]["owner_name"], "Other")

    def test_review_presence_lists_users_on_page(self) -> None:
        first_response = self.client.post(
            "/review/2026-04/presence",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(first_response.json()["users"][0]["owner_name"], "Employee")

        other_client = TestClient(self.main.app)
        self.addCleanup(other_client.close)
        self._authenticate_client(other_client, "other@example.com", "Other")
        second_response = other_client.post(
            "/review/2026-04/presence",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(
            {user["owner_name"] for user in second_response.json()["users"]},
            {"Employee", "Other"},
        )

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
