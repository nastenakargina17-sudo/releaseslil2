import importlib
import os
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.auth import build_review_entry_url
from app.models import DigestItem, DigestRelease, GroupingMode, ItemType


class ReviewAuthTests(unittest.TestCase):
    def test_review_entry_url_points_to_auth_login_with_next(self) -> None:
        url = build_review_entry_url("https://skillaz", "/review/2026-04")

        self.assertEqual(
            url,
            "https://skillaz/auth/yandex/login?next=%2Freview%2F2026-04",
        )

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
            )
        )
        self.storage.replace_release_items(
            "2026-04",
            [
                DigestItem(
                    id="item-1",
                    release_id="2026-04",
                    source_item_ids=["TRACKER-1"],
                    title="Feature title",
                    description="Feature description",
                    module="Core",
                    type=ItemType.NEW_FEATURE,
                    category=None,
                    tracker_urls=["https://tracker.example.com/TRACKER-1"],
                    grouping_mode=GroupingMode.SINGLE_TASK,
                )
            ],
        )
        self.client = TestClient(self.main.app)

    def tearDown(self) -> None:
        self.client.close()
        self.temp_dir.cleanup()

    def test_review_requires_login(self) -> None:
        response = self.client.get("/review/2026-04", follow_redirects=False)

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/auth/yandex/login?next=%2Freview%2F2026-04")

    def test_allowlisted_user_can_reach_review_after_yandex_callback(self) -> None:
        login_response = self.client.get(
            "/auth/yandex/login?next=/review/2026-04",
            follow_redirects=False,
        )
        state = parse_qs(urlparse(login_response.headers["location"]).query)["state"][0]

        with patch.object(
            self.main,
            "exchange_code_for_token",
            new=AsyncMock(return_value="access-token"),
        ), patch.object(
            self.main,
            "fetch_yandex_user",
            new=AsyncMock(
                return_value={
                    "default_email": "employee@example.com",
                    "real_name": "Release Reviewer",
                }
            ),
        ):
            callback_response = self.client.get(
                f"/auth/yandex/callback?code=code-123&state={state}",
                follow_redirects=False,
            )

        self.assertEqual(callback_response.status_code, 303)
        self.assertEqual(callback_response.headers["location"], "/review/2026-04")

        review_response = self.client.get("/review/2026-04")

        self.assertEqual(review_response.status_code, 200)
        self.assertIn("Release Reviewer", review_response.text)
        self.assertIn("employee@example.com", review_response.text)

    def test_non_allowlisted_email_is_rejected(self) -> None:
        login_response = self.client.get(
            "/auth/yandex/login?next=/review/2026-04",
            follow_redirects=False,
        )
        state = parse_qs(urlparse(login_response.headers["location"]).query)["state"][0]

        with patch.object(
            self.main,
            "exchange_code_for_token",
            new=AsyncMock(return_value="access-token"),
        ), patch.object(
            self.main,
            "fetch_yandex_user",
            new=AsyncMock(return_value={"default_email": "outsider@example.com"}),
        ):
            callback_response = self.client.get(
                f"/auth/yandex/callback?code=code-123&state={state}",
                follow_redirects=False,
            )

        self.assertEqual(callback_response.status_code, 303)
        self.assertEqual(callback_response.headers["location"], "/?auth_error=access_denied")

    def test_callback_without_code_redirects_with_readable_error(self) -> None:
        response = self.client.get(
            "/auth/yandex/callback?state=test-state",
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/?auth_error=missing_oauth_code")


if __name__ == "__main__":
    unittest.main()
