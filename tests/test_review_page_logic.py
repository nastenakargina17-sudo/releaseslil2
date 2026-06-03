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

    def test_change_type_labels_are_human_readable(self) -> None:
        from app.models import ItemType
        from app.review_utils import ITEM_TYPE_LABELS

        self.assertEqual(ITEM_TYPE_LABELS[ItemType.NEW_FEATURE], "Новый функционал")
        self.assertEqual(ITEM_TYPE_LABELS[ItemType.CHANGE], "Продуктовое улучшение")
        self.assertEqual(ITEM_TYPE_LABELS[ItemType.PRODUCT_IMPROVEMENT], "Продуктовое улучшение")
        self.assertEqual(ITEM_TYPE_LABELS[ItemType.CLIENT_CUSTOMIZATION], "Клиентская доработка")
        self.assertEqual(ITEM_TYPE_LABELS[ItemType.INTERNAL_CHANGE], "Внутреннее изменение")
        self.assertEqual(ITEM_TYPE_LABELS[ItemType.TECHNICAL_IMPROVEMENT], "Техническая итерация")
        self.assertEqual(ITEM_TYPE_LABELS[ItemType.BUGFIX], "Исправление")

    def test_visibility_labels_and_defaults_are_human_readable(self) -> None:
        from app.models import DigestVisibility, ItemType
        from app.review_utils import DIGEST_VISIBILITY_LABELS, default_digest_visibility

        self.assertEqual(DIGEST_VISIBILITY_LABELS[DigestVisibility.PUBLIC], "Публичный дайджест")
        self.assertEqual(DIGEST_VISIBILITY_LABELS[DigestVisibility.INTERNAL], "Внутренний обзор")
        self.assertEqual(default_digest_visibility(ItemType.NEW_FEATURE), DigestVisibility.PUBLIC)
        self.assertEqual(default_digest_visibility(ItemType.CHANGE), DigestVisibility.PUBLIC)
        self.assertEqual(default_digest_visibility(ItemType.PRODUCT_IMPROVEMENT), DigestVisibility.PUBLIC)
        self.assertEqual(default_digest_visibility(ItemType.CLIENT_CUSTOMIZATION), DigestVisibility.INTERNAL)
        self.assertEqual(default_digest_visibility(ItemType.INTERNAL_CHANGE), DigestVisibility.INTERNAL)
        self.assertEqual(default_digest_visibility(ItemType.TECHNICAL_IMPROVEMENT), DigestVisibility.INTERNAL)
        self.assertEqual(default_digest_visibility(ItemType.BUGFIX), DigestVisibility.INTERNAL)

    def test_legacy_change_defaults_to_product_improvement_category(self) -> None:
        from app.models import ItemType, ValueCategory
        from app.review_utils import default_item_category

        self.assertEqual(default_item_category(ItemType.CHANGE), ValueCategory.CLARITY_TRANSPARENCY)

    def test_description_generation_rules_follow_change_type_only(self) -> None:
        from app.models import ItemType
        from app.review_utils import should_collect_description

        self.assertTrue(should_collect_description(ItemType.NEW_FEATURE))
        self.assertTrue(should_collect_description(ItemType.CHANGE))
        self.assertTrue(should_collect_description(ItemType.PRODUCT_IMPROVEMENT))
        self.assertTrue(should_collect_description(ItemType.CLIENT_CUSTOMIZATION))
        self.assertTrue(should_collect_description(ItemType.INTERNAL_CHANGE))
        self.assertFalse(should_collect_description(ItemType.TECHNICAL_IMPROVEMENT))
        self.assertFalse(should_collect_description(ItemType.BUGFIX))

    def test_digest_media_helper_detects_video_paths(self) -> None:
        from app.review_utils import is_video_media_path

        self.assertTrue(is_video_media_path("/uploads/demo.mp4"))
        self.assertTrue(is_video_media_path("/uploads/demo.WEBM"))
        self.assertFalse(is_video_media_path("/uploads/demo.png"))
        self.assertFalse(is_video_media_path(""))

    def test_digest_item_visibility_round_trips_through_storage(self) -> None:
        from app.models import DigestItem, DigestRelease, DigestVisibility, ItemStatus, ItemType
        from app.storage import init_db, list_items, replace_release_items, upsert_release
        import app.config
        import app.storage

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.db"
            app.config.DB_PATH = db_path
            app.storage.DB_PATH = db_path
            init_db()

            upsert_release(DigestRelease(id="2026-04", release_date="2026-04-30", summary="Summary"))
            replace_release_items("2026-04", [
                DigestItem(
                    id="item-1",
                    release_id="2026-04",
                    source_item_ids=["DEV-1"],
                    title="Internal admin update",
                    description="Updated admin behavior",
                    module="Админка",
                    type=ItemType.INTERNAL_CHANGE,
                    digest_visibility=DigestVisibility.PUBLIC,
                    category=None,
                    status=ItemStatus.DRAFT,
                )
            ])

            [item] = list_items("2026-04")
            self.assertEqual(item.digest_visibility, DigestVisibility.PUBLIC)


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

    def _set_release_preview_ready(self) -> None:
        release = self.storage.get_release("2026-04")
        self.storage.update_release_summary(
            "2026-04",
            release.summary,
            SummaryStatus.APPROVED.value,
            expected_version=release.version,
        )
        self.storage.update_release_publication_status(
            "2026-04",
            PublicationStatus.PREVIEW,
            note="Preview сформирован.",
            preview_prepared_by="Employee",
        )

    def tearDown(self) -> None:
        self.client.close()
        self.temp_dir.cleanup()

    def test_review_page_renders_updated_controls(self) -> None:
        response = self.client.get("/review/2026-04")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Дайджест в подготовке", response.text)
        self.assertIn("Сформировать preview", response.text)
        self.assertIn("Сохранить изменения", response.text)
        self.assertIn("Исключить из релиза", response.text)
        self.assertIn("Категория ценности", response.text)
        self.assertIn('Задачи из "Нет"', response.text)
        self.assertIn("На странице сейчас", response.text)
        self.assertNotIn("Выйти из ревью", response.text)

    def test_prepare_preview_button_remains_clickable_when_review_has_blockers(self) -> None:
        response = self.client.get("/review/2026-04")

        self.assertEqual(response.status_code, 200)
        self.assertIn('<button type="submit" class="button button-primary">Сформировать preview</button>', response.text)
        self.assertIn('card.dataset.itemType === "release_candidate"', response.text)

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

    def test_live_digest_metrics_count_release_categories(self) -> None:
        from app.services.publication import build_live_digest_content

        items = [
            DigestItem(id="feature", release_id="2026-04", source_item_ids=[], title="Feature", description="Feature text", module="Подбор", type=ItemType.NEW_FEATURE, category=None, status=ItemStatus.APPROVED),
            DigestItem(id="change", release_id="2026-04", source_item_ids=[], title="Change", description="Change text", module="Интеграции", type=ItemType.CHANGE, category=None, status=ItemStatus.APPROVED),
            DigestItem(id="tech", release_id="2026-04", source_item_ids=[], title="Tech", description="", module="Платформа", type=ItemType.TECHNICAL_IMPROVEMENT, category=None, status=ItemStatus.APPROVED),
            DigestItem(id="bug", release_id="2026-04", source_item_ids=[], title="Bug", description="", module="Ядро", type=ItemType.BUGFIX, category=None, status=ItemStatus.APPROVED),
            DigestItem(id="draft", release_id="2026-04", source_item_ids=[], title="Draft", description="", module="Ядро", type=ItemType.NEW_FEATURE, category=None, status=ItemStatus.DRAFT),
        ]

        content = build_live_digest_content(items)

        self.assertEqual(
            content["metrics"],
            {
                "items_count": 4,
                "new_features_count": 1,
                "changes_count": 1,
                "technical_count": 2,
                "product_items_count": 2,
            },
        )
        support = next(section for section in content["sections"] if section["id"] == "support")
        self.assertEqual(support["title"], "Стабильность и техническая база")
        self.assertEqual(support["items_count"], 2)

    def test_item_payload_includes_module_icon_key(self) -> None:
        from app.services.publication import build_live_digest_content

        item = DigestItem(
            id="integration",
            release_id="2026-04",
            source_item_ids=[],
            title="Integration",
            description="Integration text",
            module="Интеграции",
            type=ItemType.NEW_FEATURE,
            category=None,
            status=ItemStatus.APPROVED,
        )

        content = build_live_digest_content([item])
        first_item = content["sections"][0]["items"][0]

        self.assertEqual(first_item["module_icon"], "integrations")

    def test_prepare_preview_requires_ready_release(self) -> None:
        response = self.client.post("/review/2026-04/prepare-digest-preview", follow_redirects=False)

        self.assertEqual(response.status_code, 303)
        self.assertIn("digest_not_ready", response.headers["location"])
        self.assertEqual(self.storage.get_release("2026-04").publication_status, PublicationStatus.DRAFT)

    def test_prepare_preview_sets_preview_status_when_ready(self) -> None:
        self.storage.update_item(
            item_id="item-1",
            title="Feature title",
            description="Feature description",
            category=ValueCategory.TIME_SAVING.value,
            status=ItemStatus.APPROVED.value,
            is_paid_feature=False,
        )

        response = self.client.post("/review/2026-04/prepare-digest-preview", follow_redirects=False)

        self.assertEqual(response.status_code, 303)
        self.assertIn("/review/2026-04/digest-preview", response.headers["location"])
        release = self.storage.get_release("2026-04")
        self.assertEqual(release.publication_status, PublicationStatus.PREVIEW)
        self.assertEqual(release.preview_prepared_by, "Employee")

    def test_review_edit_resets_preview_to_draft_with_explanation(self) -> None:
        self.storage.update_release_publication_status(
            "2026-04",
            PublicationStatus.PREVIEW,
            note="Preview сформирован.",
            preview_prepared_by="Employee",
        )
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
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        release = self.storage.get_release("2026-04")
        self.assertEqual(release.publication_status, PublicationStatus.DRAFT)
        self.assertIn("Preview сброшен", release.publication_status_note)

    def test_published_release_blocks_review_edits(self) -> None:
        self.storage.update_release_publication_status(
            "2026-04",
            PublicationStatus.PUBLISHED,
            note="Дайджест опубликован.",
            published_by="Employee",
        )
        item = self.storage.get_item("item-1")

        response = self.client.post(
            "/review/2026-04/items/item-1",
            data={
                "title": "Should not save",
                "description": "Should not save",
                "category": "",
                "status": "approved",
                "object_version": str(item.version),
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn("уже опубликован", response.json()["message"])
        self.assertNotEqual(self.storage.get_item("item-1").title, "Should not save")

    def test_digest_public_page_shows_preparation_until_published(self) -> None:
        response = self.client.get("/digest/2026-04")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Дайджест в подготовке", response.text)
        self.assertNotIn("Feature title", response.text)

    def test_preview_route_requires_preview_status(self) -> None:
        response = self.client.get("/review/2026-04/digest-preview")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Preview еще не сформирован", response.text)

    def test_preview_route_renders_live_approved_data(self) -> None:
        self.storage.update_item(
            item_id="item-1",
            title="Preview feature",
            description="Preview description",
            category=ValueCategory.TIME_SAVING.value,
            status=ItemStatus.APPROVED.value,
            is_paid_feature=False,
        )
        self.storage.update_release_publication_status(
            "2026-04",
            PublicationStatus.PREVIEW,
            note="Preview сформирован.",
            preview_prepared_by="Employee",
        )

        response = self.client.get("/review/2026-04/digest-preview")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Предпросмотр", response.text)
        self.assertIn("Preview feature", response.text)
        self.assertIn("Опубликовать дайджест", response.text)

    def test_public_digest_reads_published_snapshot_not_live_review(self) -> None:
        from app.models import PublishedDigest

        self.storage.save_published_digest(
            PublishedDigest(
                release_id="2026-04",
                release_date="2026-04-30",
                summary="Published summary",
                content={
                    "sections": [
                        {
                            "id": "new_features",
                            "title": "Что нового",
                            "collapsed": False,
                            "items": [{"title": "Snapshot feature", "description": "Snapshot text", "module": "Core", "value_category_label": "", "is_paid_feature": False, "media": []}],
                        }
                    ],
                    "metrics": {"items_count": 1, "product_items_count": 1},
                },
                published_by="Employee",
                published_at="1710000000",
            )
        )
        self.storage.update_release_publication_status(
            "2026-04",
            PublicationStatus.PUBLISHED,
            note="Дайджест опубликован.",
            published_by="Employee",
        )
        self.storage.update_release_publication_status(
            "2026-04",
            PublicationStatus.DRAFT,
            note="",
        )
        self.storage.update_item(
            item_id="item-1",
            title="Live changed feature",
            description="Live text",
            category="",
            status=ItemStatus.APPROVED.value,
            is_paid_feature=False,
        )

        response = self.client.get("/digest/2026-04")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Snapshot feature", response.text)
        self.assertNotIn("Live changed feature", response.text)
        self.assertNotIn("Employee", response.text)

    def test_archive_lists_only_published_snapshots(self) -> None:
        from app.models import PublishedDigest

        self.storage.save_published_digest(
            PublishedDigest(
                release_id="2026-04",
                release_date="2026-04-30",
                summary="Published summary",
                content={"sections": [], "metrics": {"items_count": 0, "product_items_count": 0}},
                published_by="Employee",
                published_at="1710000000",
            )
        )

        response = self.client.get("/digests")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Архив дайджестов", response.text)
        self.assertIn("2026-04", response.text)
        self.assertIn("Published summary", response.text)

    def test_review_page_shows_prepare_preview_action_when_ready(self) -> None:
        self.storage.update_item(
            item_id="item-1",
            title="Feature title",
            description="Feature description",
            category=ValueCategory.TIME_SAVING.value,
            status=ItemStatus.APPROVED.value,
            is_paid_feature=False,
        )

        response = self.client.get("/review/2026-04")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Сформировать preview", response.text)
        self.assertNotIn("Отправить готовый дайджест в Telegram", response.text)

    def test_review_page_shows_publish_action_in_preview_state(self) -> None:
        self.storage.update_release_publication_status(
            "2026-04",
            PublicationStatus.PREVIEW,
            note="Preview сформирован.",
            preview_prepared_by="Employee",
        )

        response = self.client.get("/review/2026-04")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Открыть preview", response.text)
        self.assertIn("Опубликовать дайджест", response.text)
        self.assertIn("зафиксирует версию и закроет релиз", response.text)

    def test_review_page_shows_published_audit_and_open_digest_action(self) -> None:
        self.storage.update_release_publication_status(
            "2026-04",
            PublicationStatus.PUBLISHED,
            note="Дайджест опубликован.",
            published_by="Employee",
        )

        response = self.client.get("/review/2026-04")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Дайджест опубликован", response.text)
        self.assertIn("Employee", response.text)
        self.assertIn("Открыть опубликованный дайджест", response.text)
        self.assertNotIn("Сформировать preview", response.text)

    def test_public_digest_uses_brand_assets_and_toc(self) -> None:
        from app.models import PublishedDigest

        self.storage.save_published_digest(
            PublishedDigest(
                release_id="2026-04",
                release_date="2026-04-30",
                summary="Published summary",
                content={
                    "sections": [
                        {
                            "id": "new_features",
                            "title": "Что нового",
                            "collapsed": False,
                            "items": [
                                {
                                    "title": "Snapshot feature",
                                    "description": "Snapshot text",
                                    "module": "Core",
                                    "value_category_label": "Экономия времени",
                                    "is_paid_feature": True,
                                    "media": [],
                                }
                            ],
                        }
                    ],
                    "metrics": {"items_count": 1, "product_items_count": 1},
                },
                published_by="Employee",
                published_at="1710000000",
            )
        )

        response = self.client.get("/digest/2026-04")

        self.assertEqual(response.status_code, 200)
        self.assertIn("/static/brand/Logo_Skillaz_Black.png", response.text)
        self.assertIn("Подбор", response.text)
        self.assertIn("Оглавление", response.text)
        self.assertIn("#49DE4E", response.text)

    def test_public_digest_normalizes_legacy_snapshot_metrics_and_support_title(self) -> None:
        from app.models import PublishedDigest

        self.storage.save_published_digest(
            PublishedDigest(
                release_id="2026-04",
                release_date="2026-04-30",
                summary="Published summary",
                content={
                    "sections": [
                        {
                            "id": "new_features",
                            "title": "Что нового",
                            "collapsed": False,
                            "items": [
                                {
                                    "title": "Legacy feature",
                                    "description": "Snapshot text",
                                    "module": "Интеграции",
                                    "value_category_label": "",
                                    "is_paid_feature": False,
                                    "media": [],
                                }
                            ],
                        },
                        {
                            "id": "support",
                            "title": "Исправления и технические улучшения",
                            "collapsed": True,
                            "items": [
                                {
                                    "title": "Legacy fix",
                                    "description": "",
                                    "module": "Ядро",
                                    "value_category_label": "",
                                    "is_paid_feature": False,
                                    "media": [],
                                    "tracker_urls": ["https://tracker.yandex.ru/DEV-1"],
                                }
                            ],
                        },
                    ],
                    "metrics": {"items_count": 2, "product_items_count": 1},
                },
                published_by="Employee",
                published_at="1710000000",
            )
        )

        response = self.client.get("/digest/2026-04")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Новые функции", response.text)
        self.assertIn("<strong>1</strong><span>Новые функции</span>", response.text)
        self.assertIn("<strong>0</strong><span>Улучшения</span>", response.text)
        self.assertIn("<strong>1</strong><span>Техническая база</span>", response.text)
        self.assertIn("Стабильность и техническая база", response.text)
        self.assertNotIn("Исправления и технические улучшения", response.text)
        self.assertIn('class="module-icon module-icon-integrations"', response.text)

    def test_digest_uses_deep_brand_report_markup(self) -> None:
        self.storage.update_release_publication_status("2026-04", PublicationStatus.PREVIEW)
        item = DigestItem(
            id="feature-paid",
            release_id="2026-04",
            source_item_ids=[],
            title="Paid feature",
            description="Paid feature text",
            module="Интеграции",
            type=ItemType.NEW_FEATURE,
            category=ValueCategory.TIME_SAVING,
            status=ItemStatus.APPROVED,
            is_paid_feature=True,
        )
        self.storage.replace_release_items("2026-04", [item])

        response = self.client.get("/review/2026-04/digest-preview")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Logo_Skillaz_Black.png", response.text)
        self.assertIn("Итоги релиза", response.text)
        self.assertIn("Всего изменений", response.text)
        self.assertIn("Новые функции", response.text)
        self.assertIn("Улучшения", response.text)
        self.assertIn("Техническая база", response.text)
        self.assertIn('class="module-icon module-icon-integrations"', response.text)
        self.assertIn('class="premium-badge"', response.text)

    def test_multiple_media_render_as_carousel(self) -> None:
        from app.models import PublishedDigest

        self.storage.save_published_digest(
            PublishedDigest(
                release_id="2026-04",
                release_date="2026-04-30",
                summary="Published summary",
                content={
                    "sections": [
                        {
                            "id": "new_features",
                            "title": "Что нового",
                            "collapsed": False,
                            "items": [
                                {
                                    "title": "Media feature",
                                    "description": "Snapshot text",
                                    "module": "Core",
                                    "value_category_label": "",
                                    "is_paid_feature": False,
                                    "media": [
                                        {"path": "/uploads/published/2026-04/a.png", "kind": "image"},
                                        {"path": "/uploads/published/2026-04/b.png", "kind": "image"},
                                    ],
                                }
                            ],
                        }
                    ],
                    "metrics": {"items_count": 1, "product_items_count": 1},
                },
                published_by="Employee",
                published_at="1710000000",
            )
        )

        response = self.client.get("/digest/2026-04")

        self.assertEqual(response.status_code, 200)
        self.assertIn('class="media-carousel"', response.text)
        self.assertIn("data-carousel", response.text)

    def test_digest_route_rejects_non_final_items(self) -> None:
        response = self.client.get("/digest/2026-04")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Дайджест в подготовке", response.text)
        self.assertNotIn("Feature title", response.text)

    def test_release_candidate_does_not_block_digest_when_main_items_are_final(self) -> None:
        self.storage.update_item(
            item_id="item-1",
            title="Feature title",
            description="Feature description",
            category=None,
            status=ItemStatus.APPROVED.value,
            is_paid_feature=False,
        )
        self._set_release_preview_ready()

        response = self.client.get("/review/2026-04/digest-preview")

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
        self._set_release_preview_ready()

        response = self.client.get("/review/2026-04/digest-preview")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Что нового", response.text)
        self.assertIn("Что стало удобнее", response.text)
        self.assertIn("Стабильность и техническая база", response.text)
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
        self._set_release_preview_ready()

        response = self.client.get("/review/2026-04/digest-preview")

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
        self._set_release_preview_ready()

        response = self.client.get("/review/2026-04/digest-preview")

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
        self._set_release_preview_ready()

        response = self.client.get("/review/2026-04/digest-preview")

        self.assertEqual(response.status_code, 200)
        self.assertIn("<details", response.text)
        self.assertIn("Стабильность и техническая база", response.text)
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
        self._set_release_preview_ready()

        response = self.client.get("/review/2026-04/digest-preview")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Нет новых фич", response.text)
        self.assertNotIn("Нет изменений", response.text)
        self.assertNotIn('id="new-features-heading"', response.text)
        self.assertNotIn('id="changes-heading"', response.text)
        self.assertIn("Стабильность и техническая база", response.text)

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

    def test_item_can_be_excluded_without_status_field(self) -> None:
        item = self.storage.get_item("item-1")
        response = self.client.post(
            "/review/2026-04/items/item-1",
            data={
                "title": "Feature title",
                "description": "Feature description",
                "category": "",
                "exclude_from_release": "on",
                "object_version": str(item.version),
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], ItemStatus.EXCLUDED.value)
        self.assertEqual(self.storage.get_item("item-1").status, ItemStatus.EXCLUDED)

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

    def test_item_type_can_change_between_feature_and_change(self) -> None:
        item = self.storage.get_item("item-1")
        response = self.client.post(
            "/review/2026-04/items/item-1",
            data={
                "title": "Feature title",
                "description": "Feature description",
                "category": "",
                "status": "draft",
                "item_type": "change",
                "object_version": str(item.version),
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["item_type"], ItemType.CHANGE.value)
        self.assertEqual(self.storage.get_item("item-1").type, ItemType.CHANGE)

    def test_review_item_can_update_type_and_visibility(self) -> None:
        from app.models import DigestItem, DigestVisibility, ItemStatus, ItemType
        from app.storage import replace_release_items

        replace_release_items("2026-04", [
            DigestItem(
                id="feature",
                release_id="2026-04",
                source_item_ids=["DEV-1"],
                title="Feature",
                description="Feature text",
                module="Ядро",
                type=ItemType.NEW_FEATURE,
                digest_visibility=DigestVisibility.PUBLIC,
                category=None,
                status=ItemStatus.DRAFT,
            )
        ])

        response = self.client.post(
            "/review/2026-04/items/feature",
            data={
                "title": "Feature",
                "description": "Feature text",
                "item_type": "client_customization",
                "digest_visibility": "internal",
                "status": "approved",
            },
            headers={"Accept": "application/json"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["item_type"], "client_customization")
        self.assertEqual(payload["digest_visibility"], "internal")

    def test_bulk_exclude_items(self) -> None:
        response = self.client.post(
            "/review/2026-04/bulk-exclude",
            content="item_ids=item-1&item_ids=item-2",
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], ItemStatus.EXCLUDED.value)
        self.assertEqual(self.storage.get_item("item-1").status, ItemStatus.EXCLUDED)
        self.assertEqual(self.storage.get_item("item-2").status, ItemStatus.EXCLUDED)

    def test_epic_item_can_be_split_into_source_tasks(self) -> None:
        self.storage.replace_release_items(
            "2026-04",
            [
                DigestItem(
                    id="epic-item",
                    release_id="2026-04",
                    source_item_ids=["DEV-10", "DEV-11"],
                    title="Epic title",
                    description="Epic description",
                    module="Core",
                    type=ItemType.NEW_FEATURE,
                    category=ValueCategory.DAILY_WORK_CONVENIENCE,
                    status=ItemStatus.DRAFT,
                    tracker_urls=["https://tracker.yandex.ru/DEV-10", "https://tracker.yandex.ru/DEV-11"],
                    grouping_mode=GroupingMode.EPIC_GROUP,
                    source_item_titles=["First tracker task", "Second tracker task"],
                    source_item_descriptions=["First description", "Second description"],
                    source_item_modules=["Core", "Reports"],
                ),
            ],
        )

        response = self.client.post(
            "/review/2026-04/items/epic-item/split",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

        self.assertEqual(response.status_code, 200)
        items = self.storage.list_items("2026-04")
        self.assertEqual([item.title for item in items], ["First tracker task", "Second tracker task"])
        self.assertEqual([item.grouping_mode for item in items], [GroupingMode.SINGLE_TASK, GroupingMode.SINGLE_TASK])

    def test_split_button_only_renders_for_multi_task_epic_items(self) -> None:
        self.storage.replace_release_items(
            "2026-04",
            [
                DigestItem(
                    id="single-source-epic",
                    release_id="2026-04",
                    source_item_ids=["DEV-10"],
                    title="Single source epic",
                    description="Epic description",
                    module="Core",
                    type=ItemType.NEW_FEATURE,
                    category=ValueCategory.DAILY_WORK_CONVENIENCE,
                    status=ItemStatus.DRAFT,
                    tracker_urls=["https://tracker.yandex.ru/DEV-10"],
                    grouping_mode=GroupingMode.EPIC_GROUP,
                    source_item_titles=["First tracker task"],
                    source_item_descriptions=["First description"],
                    source_item_modules=["Core"],
                ),
                DigestItem(
                    id="multi-source-epic",
                    release_id="2026-04",
                    source_item_ids=["DEV-11", "DEV-12"],
                    title="Multi source epic",
                    description="Epic description",
                    module="Core",
                    type=ItemType.NEW_FEATURE,
                    category=ValueCategory.DAILY_WORK_CONVENIENCE,
                    status=ItemStatus.DRAFT,
                    tracker_urls=["https://tracker.yandex.ru/DEV-11", "https://tracker.yandex.ru/DEV-12"],
                    grouping_mode=GroupingMode.EPIC_GROUP,
                    source_item_titles=["Second tracker task", "Third tracker task"],
                    source_item_descriptions=["Second description", "Third description"],
                    source_item_modules=["Core", "Core"],
                ),
            ],
        )

        response = self.client.get("/review/2026-04")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('/items/single-source-epic/split', response.text)
        self.assertIn('/items/multi-source-epic/split', response.text)

    def test_upload_validates_media_type_and_size(self) -> None:
        response = self.client.post(
            "/review/2026-04/items/item-1/image",
            files={"image": ("notes.txt", io.BytesIO(b"hello"), "text/plain")},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Поддерживаются JPG, PNG, WEBP, GIF, MP4 и WEBM.", response.text)

    def test_review_upload_javascript_preserves_original_images(self) -> None:
        response = self.client.get("/review/2026-04")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("canvas.toBlob", response.text)
        self.assertNotIn("image/webp\", 0.82", response.text)
        self.assertNotIn("convertImageToWebp", response.text)
        self.assertIn("return file;", response.text)

    def test_review_supports_pasting_images_from_clipboard(self) -> None:
        response = self.client.get("/review/2026-04")

        self.assertEqual(response.status_code, 200)
        self.assertIn("data-paste-target", response.text)
        self.assertIn("Вставить скрин из буфера", response.text)
        self.assertIn("clipboardData.items", response.text)
        self.assertIn("uploadMediaFile(row, clipboardFile,", response.text)

    def test_review_translates_missing_item_errors_and_deduplicates_toasts(self) -> None:
        response = self.client.get("/review/2026-04")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Карточка уже обновилась на сервере. Обновите страницу и попробуйте снова.", response.text)
        self.assertIn("lastToast.key === toastKey", response.text)

    def test_uploaded_media_can_be_deleted(self) -> None:
        initial_version = self.storage.get_item("item-1").version
        upload_response = self.client.post(
            "/review/2026-04/items/item-1/image",
            files={"image": ("preview.webp", io.BytesIO(b"fake-image"), "image/webp")},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

        self.assertEqual(upload_response.status_code, 200)
        self.assertGreater(upload_response.json()["version"], initial_version)
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
        self.assertGreater(delete_response.json()["version"], upload_response.json()["version"])
        self.assertFalse(stored_path.exists())


if __name__ == "__main__":
    unittest.main()
