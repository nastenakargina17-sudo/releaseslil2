# Digest Publication Flow And Branded Pages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a two-step review-to-publication flow with live protected preview, stable published snapshots, a public digest archive, and branded Skillaz/Подбор public pages.

**Architecture:** Keep review data and published data separate. `digest_releases` owns workflow state (`draft`, `preview`, `published`), while a new `published_digests` table stores the immutable public snapshot JSON and audit fields. Preview renders live approved review data under `/review/*`; public `/digest/{release_id}` and `/digests` render only published snapshots.

**Tech Stack:** Python, FastAPI, Jinja2 templates, SQLite, unittest, local static assets and uploaded media files.

---

## Scope And Sequencing

This plan intentionally implements the feature in layers:

1. Data model and storage.
2. Snapshot builder and media copying.
3. Review publication actions and edit blocking.
4. Preview/public/archive routes.
5. Branded templates, assets, and carousel.
6. Regression tests and verification.

Do not deploy to Railway in this plan. Railway deployment remains a later explicit step.

The repository currently uses `unittest`; do not add `pytest`.

---

## File Structure

- Modify `app/models.py`
  - Add `PublicationStatus`.
  - Add `PublishedDigest`.
  - Add publication fields to `DigestRelease`.

- Modify `app/storage.py`
  - Add publication columns to `digest_releases`.
  - Add `published_digests` table.
  - Add helpers to change publication status and store/read/list snapshots.

- Create `app/services/publication.py`
  - Build live digest view data from approved review data.
  - Copy media into `/uploads/published/{release_id}/...`.
  - Create `PublishedDigest` snapshots.

- Modify `app/config.py`
  - Add `STATIC_DIR`.
  - Ensure `static/` exists.

- Modify `app/main.py`
  - Mount `/static`.
  - Add preview, prepare, publish, return-to-review, archive routes.
  - Make public digest read snapshots only.
  - Block edit/upload/delete once published.
  - Reset preview to draft after review edits.

- Modify `templates/review.html`
  - Replace the current final-action block with publication-state UI.
  - Hide edit controls when release is published.

- Modify `templates/digest.html`
  - Render both preview and public digest contexts.
  - Use branded hero, table of contents, cards, and carousel.

- Modify `templates/digest_item_card.html`
  - Render item data from dictionaries as well as dataclasses.
  - Add carousel behavior for multiple media files.

- Create `templates/digests.html`
  - Public editorial archive of published snapshots.

- Copy selected assets into `static/brand/`
  - Skillaz SVG logo.
  - Onest or TT Hoves regular/bold fonts only.

- Modify tests:
  - `tests/test_review_page_logic.py`

---

### Task 1: Add Publication Models And Storage

**Files:**
- Modify: `app/models.py`
- Modify: `app/storage.py`
- Test: `tests/test_review_page_logic.py`

- [ ] **Step 1: Write failing storage tests**

Add imports at the top of `tests/test_review_page_logic.py`:

```python
import json
```

Extend the existing model import:

```python
from app.models import DigestItem, DigestRelease, GroupingMode, ItemStatus, ItemType, PublicationStatus, SourceItem, SummaryStatus, ValueCategory
```

Add these tests to `DigestGuardTests`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
/Users/user/Downloads/релиз\ ноутс2/.venv/bin/python -m unittest \
  tests.test_review_page_logic.DigestGuardTests.test_release_defaults_to_draft_publication_status \
  tests.test_review_page_logic.DigestGuardTests.test_publication_status_can_be_updated_with_a_note \
  tests.test_review_page_logic.DigestGuardTests.test_published_digest_snapshot_round_trips -v
```

Expected: FAIL because `PublicationStatus`, `PublishedDigest`, and storage helpers do not exist.

- [ ] **Step 3: Add model types**

In `app/models.py`, add after `SummaryStatus`:

```python
class PublicationStatus(str, Enum):
    DRAFT = "draft"
    PREVIEW = "preview"
    PUBLISHED = "published"
```

Update `DigestRelease`:

```python
@dataclass
class DigestRelease:
    id: str
    release_date: str
    summary: str
    summary_status: SummaryStatus = SummaryStatus.DRAFT
    publication_status: PublicationStatus = PublicationStatus.DRAFT
    publication_status_note: str = ""
    preview_prepared_by: str = ""
    preview_prepared_at: str = ""
    published_by: str = ""
    published_at: str = ""
    version: int = 1
    updated_at: str = ""
```

Add this dataclass after `DigestRelease`:

```python
@dataclass
class PublishedDigest:
    release_id: str
    release_date: str
    summary: str
    content: dict
    published_by: str
    published_at: str
```

- [ ] **Step 4: Add storage schema**

In `app/storage.py`, import the new types:

```python
    PublishedDigest,
    PublicationStatus,
```

Inside `init_db()`, add a new table to the `executescript` block:

```sql
            CREATE TABLE IF NOT EXISTS published_digests (
                release_id TEXT PRIMARY KEY,
                release_date TEXT NOT NULL,
                summary TEXT NOT NULL,
                content TEXT NOT NULL,
                published_by TEXT NOT NULL,
                published_at TEXT NOT NULL,
                FOREIGN KEY (release_id) REFERENCES digest_releases(id)
            );
```

After the existing `_ensure_column` calls for `digest_releases`, add:

```python
        _ensure_column(conn, "digest_releases", "publication_status", "TEXT NOT NULL DEFAULT 'draft'")
        _ensure_column(conn, "digest_releases", "publication_status_note", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "digest_releases", "preview_prepared_by", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "digest_releases", "preview_prepared_at", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "digest_releases", "published_by", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "digest_releases", "published_at", "TEXT NOT NULL DEFAULT ''")
```

- [ ] **Step 5: Update release persistence**

In `upsert_release()`, extend the insert/update SQL:

```python
            INSERT INTO digest_releases (
                id, release_date, summary, summary_status, publication_status,
                publication_status_note, preview_prepared_by, preview_prepared_at,
                published_by, published_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                release_date = excluded.release_date,
                summary = excluded.summary,
                summary_status = excluded.summary_status,
                version = digest_releases.version + 1,
                updated_at = excluded.updated_at
```

Use these params:

```python
            (
                release.id,
                release.release_date,
                release.summary,
                release.summary_status.value,
                release.publication_status.value,
                release.publication_status_note,
                release.preview_prepared_by,
                release.preview_prepared_at,
                release.published_by,
                release.published_at,
                _now_text(),
            ),
```

Do not update publication columns on conflict during import; imports should not silently publish or unpublish a release.

In `get_release()`, select the new columns:

```sql
            SELECT id, release_date, summary, summary_status, publication_status,
                   publication_status_note, preview_prepared_by, preview_prepared_at,
                   published_by, published_at, version, updated_at
            FROM digest_releases
```

Return:

```python
    return DigestRelease(
        id=row["id"],
        release_date=row["release_date"],
        summary=row["summary"],
        summary_status=SummaryStatus(row["summary_status"]),
        publication_status=PublicationStatus(row["publication_status"]),
        publication_status_note=row["publication_status_note"],
        preview_prepared_by=row["preview_prepared_by"],
        preview_prepared_at=row["preview_prepared_at"],
        published_by=row["published_by"],
        published_at=row["published_at"],
        version=row["version"],
        updated_at=row["updated_at"],
    )
```

- [ ] **Step 6: Add publication storage helpers**

Add these functions to `app/storage.py` after `update_release_summary()`:

```python
def update_release_publication_status(
    release_id: str,
    status: PublicationStatus,
    note: str = "",
    preview_prepared_by: str = "",
    published_by: str = "",
) -> None:
    now = _now_text()
    preview_at = now if status == PublicationStatus.PREVIEW else ""
    published_at = now if status == PublicationStatus.PUBLISHED else ""
    with connect() as conn:
        conn.execute(
            """
            UPDATE digest_releases
            SET publication_status = ?,
                publication_status_note = ?,
                preview_prepared_by = ?,
                preview_prepared_at = ?,
                published_by = ?,
                published_at = ?,
                version = version + 1,
                updated_at = ?
            WHERE id = ?
            """,
            (
                status.value,
                note,
                preview_prepared_by if status == PublicationStatus.PREVIEW else "",
                preview_at,
                published_by if status == PublicationStatus.PUBLISHED else "",
                published_at,
                now,
                release_id,
            ),
        )


def reset_preview_after_review_change(release_id: str) -> None:
    release = get_release(release_id)
    if release is None or release.publication_status != PublicationStatus.PREVIEW:
        return
    update_release_publication_status(
        release_id,
        PublicationStatus.DRAFT,
        note="Preview сброшен, потому что данные ревью изменились. Сформируйте preview заново перед публикацией.",
    )


def save_published_digest(snapshot: PublishedDigest) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO published_digests (
                release_id, release_date, summary, content, published_by, published_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(release_id) DO UPDATE SET
                release_date = excluded.release_date,
                summary = excluded.summary,
                content = excluded.content,
                published_by = excluded.published_by,
                published_at = excluded.published_at
            """,
            (
                snapshot.release_id,
                snapshot.release_date,
                snapshot.summary,
                json.dumps(snapshot.content, ensure_ascii=False),
                snapshot.published_by,
                snapshot.published_at,
            ),
        )


def get_published_digest(release_id: str) -> Optional[PublishedDigest]:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT release_id, release_date, summary, content, published_by, published_at
            FROM published_digests
            WHERE release_id = ?
            """,
            (release_id,),
        ).fetchone()
    if row is None:
        return None
    return _row_to_published_digest(row)


def list_published_digests() -> List[PublishedDigest]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT release_id, release_date, summary, content, published_by, published_at
            FROM published_digests
            ORDER BY release_date DESC, release_id DESC
            """
        ).fetchall()
    return [_row_to_published_digest(row) for row in rows]


def _row_to_published_digest(row: sqlite3.Row) -> PublishedDigest:
    return PublishedDigest(
        release_id=row["release_id"],
        release_date=row["release_date"],
        summary=row["summary"],
        content=json.loads(row["content"]),
        published_by=row["published_by"],
        published_at=row["published_at"],
    )
```

- [ ] **Step 7: Run storage tests**

Run the same command from Step 2.

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add app/models.py app/storage.py tests/test_review_page_logic.py
git commit -m "Add digest publication storage"
```

---

### Task 2: Build Snapshot Service And Media Copying

**Files:**
- Create: `app/services/publication.py`
- Modify: `app/config.py`
- Test: `tests/test_review_page_logic.py`

- [ ] **Step 1: Write failing publication service tests**

Add these tests to `DigestGuardTests`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
/Users/user/Downloads/релиз\ ноутс2/.venv/bin/python -m unittest \
  tests.test_review_page_logic.DigestGuardTests.test_publication_snapshot_contains_card_fields_and_copies_media \
  tests.test_review_page_logic.DigestGuardTests.test_publication_snapshot_fails_when_media_file_is_missing -v
```

Expected: FAIL because `app.services.publication` does not exist.

- [ ] **Step 3: Add config static directory**

In `app/config.py`, add:

```python
STATIC_DIR = BASE_DIR / "static"
```

Update `ensure_directories()`:

```python
def ensure_directories() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    UPLOADS_DIR.mkdir(exist_ok=True)
    STATIC_DIR.mkdir(exist_ok=True)
```

- [ ] **Step 4: Create publication service**

Create `app/services/publication.py`:

```python
from pathlib import Path
import shutil
from typing import Iterable, Optional

from app.models import DigestItem, DigestRelease, ItemStatus, ItemType, PublishedDigest
from app.review_utils import CLIENT_CATEGORY_LABELS, is_video_media_path
from app.storage import _now_text


class PublicationError(Exception):
    pass


def build_live_digest_content(items: Iterable[DigestItem]) -> dict:
    approved_items = [
        item for item in items
        if item.status == ItemStatus.APPROVED and item.type != ItemType.RELEASE_CANDIDATE
    ]
    sections = [
        _section("new_features", "Что нового", [item for item in approved_items if item.type == ItemType.NEW_FEATURE], include_tracker=False),
        _section("changes", "Что стало удобнее", [item for item in approved_items if item.type == ItemType.CHANGE], include_tracker=False),
        _section(
            "support",
            "Исправления и технические улучшения",
            [item for item in approved_items if item.type in {ItemType.BUGFIX, ItemType.TECHNICAL_IMPROVEMENT}],
            include_tracker=True,
            collapsed=True,
        ),
    ]
    visible_sections = [section for section in sections if section["items"]]
    return {
        "sections": visible_sections,
        "metrics": {
            "items_count": sum(len(section["items"]) for section in visible_sections),
            "product_items_count": sum(len(section["items"]) for section in visible_sections if section["id"] in {"new_features", "changes"}),
        },
    }


def build_published_digest_snapshot(
    release: DigestRelease,
    items: Iterable[DigestItem],
    published_by: str,
    uploads_dir: Path,
) -> PublishedDigest:
    content = build_live_digest_content(items)
    content["sections"] = [
        _copy_section_media(section, release.id, uploads_dir)
        for section in content["sections"]
    ]
    return PublishedDigest(
        release_id=release.id,
        release_date=release.release_date,
        summary=release.summary,
        content=content,
        published_by=published_by,
        published_at=_now_text(),
    )


def _section(section_id: str, title: str, items: list[DigestItem], include_tracker: bool, collapsed: bool = False) -> dict:
    return {
        "id": section_id,
        "title": title,
        "collapsed": collapsed,
        "items": [_item_payload(item, include_tracker) for item in items],
    }


def _item_payload(item: DigestItem, include_tracker: bool) -> dict:
    payload = {
        "title": item.title,
        "description": item.description,
        "module": item.module,
        "type": item.type.value,
        "value_category": item.category.value if item.category else "",
        "value_category_label": CLIENT_CATEGORY_LABELS.get(item.category, "") if item.category else "",
        "is_paid_feature": item.is_paid_feature,
        "media": [_media_payload(path) for path in item.image_paths],
    }
    if include_tracker:
        payload["tracker_urls"] = list(item.tracker_urls)
    return payload


def _media_payload(path: str) -> dict:
    return {
        "path": path,
        "kind": "video" if is_video_media_path(path) else "image",
    }


def _copy_section_media(section: dict, release_id: str, uploads_dir: Path) -> dict:
    copied_section = dict(section)
    copied_items = []
    for item in section["items"]:
        copied_item = dict(item)
        copied_item["media"] = [
            _copy_media(media, release_id, uploads_dir)
            for media in item["media"]
        ]
        copied_items.append(copied_item)
    copied_section["items"] = copied_items
    return copied_section


def _copy_media(media: dict, release_id: str, uploads_dir: Path) -> dict:
    source_path = _source_path_for_media(media["path"], uploads_dir)
    if source_path is None or not source_path.exists():
        raise PublicationError(f"Не удалось найти медиафайл для публикации: {media['path']}")
    target_dir = uploads_dir / "published" / release_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / source_path.name
    if target_path.exists():
        target_path = target_dir / f"{source_path.stem}-{_now_text()}{source_path.suffix}"
    shutil.copy2(source_path, target_path)
    return {
        "path": f"/uploads/published/{release_id}/{target_path.name}",
        "kind": media["kind"],
    }


def _source_path_for_media(public_path: str, uploads_dir: Path) -> Optional[Path]:
    if not public_path.startswith("/uploads/"):
        return None
    relative = public_path.replace("/uploads/", "", 1)
    if relative.startswith("published/"):
        return None
    return uploads_dir / relative
```

- [ ] **Step 5: Run service tests**

Run the same command from Step 2.

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/config.py app/services/publication.py tests/test_review_page_logic.py
git commit -m "Build digest publication snapshots"
```

---

### Task 3: Add Publication Actions And Edit Guards

**Files:**
- Modify: `app/main.py`
- Modify: `app/storage.py`
- Test: `tests/test_review_page_logic.py`

- [ ] **Step 1: Write failing route tests**

Add these tests to `DigestGuardTests`:

```python
    def test_prepare_preview_requires_ready_release(self) -> None:
        response = self.client.post("/review/2026-04/prepare-digest-preview")

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

        response = self.client.post("/review/2026-04/prepare-digest-preview")

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
```

- [ ] **Step 2: Run route tests to verify they fail**

Run:

```bash
/Users/user/Downloads/релиз\ ноутс2/.venv/bin/python -m unittest \
  tests.test_review_page_logic.DigestGuardTests.test_prepare_preview_requires_ready_release \
  tests.test_review_page_logic.DigestGuardTests.test_prepare_preview_sets_preview_status_when_ready \
  tests.test_review_page_logic.DigestGuardTests.test_review_edit_resets_preview_to_draft_with_explanation \
  tests.test_review_page_logic.DigestGuardTests.test_published_release_blocks_review_edits -v
```

Expected: FAIL because routes and edit guards do not exist.

- [ ] **Step 3: Import publication helpers in `app/main.py`**

Add imports:

```python
from app.models import ItemStatus, ItemType, PublicationStatus, SummaryStatus, ValueCategory
```

Add storage imports:

```python
    get_published_digest,
    reset_preview_after_review_change,
    save_published_digest,
    update_release_publication_status,
```

Add publication imports:

```python
from app.services.publication import PublicationError, build_live_digest_content, build_published_digest_snapshot
```

- [ ] **Step 4: Add helper guards in `app/main.py`**

Add these helpers near `_stale_object_response()`:

```python
def _published_release_response(request: Request, release_id: str) -> Response:
    message = "Этот релиз уже опубликован. Редактирование закрыто."
    if _wants_json(request):
        return JSONResponse({"ok": False, "message": message, "detail": message}, status_code=409)
    return RedirectResponse(url=f"/review/{release_id}?flash=release_published", status_code=303)


def _release_is_published(release_id: str) -> bool:
    release = get_release(release_id)
    return bool(release and release.publication_status == PublicationStatus.PUBLISHED)
```

- [ ] **Step 5: Add prepare/publish/return routes**

Add these routes before `final_digest`:

```python
@app.post("/review/{release_id}/prepare-digest-preview")
def prepare_digest_preview(request: Request, release_id: str) -> RedirectResponse:
    release = get_release(release_id)
    if release is None:
        raise HTTPException(status_code=404, detail="Release not found")
    if release.publication_status == PublicationStatus.PUBLISHED:
        return RedirectResponse(url=f"/review/{release_id}?flash=release_published", status_code=303)
    items = list_items(release_id)
    if digest_blockers(release, items):
        return RedirectResponse(url=f"/review/{release_id}?flash=digest_not_ready", status_code=303)
    _, owner_name = _review_lock_owner(request)
    update_release_publication_status(
        release_id,
        PublicationStatus.PREVIEW,
        note="Preview сформирован. Проверьте страницу перед публикацией.",
        preview_prepared_by=owner_name,
    )
    return RedirectResponse(url=f"/review/{release_id}/digest-preview", status_code=303)


@app.post("/review/{release_id}/return-digest-to-review")
def return_digest_to_review(release_id: str) -> RedirectResponse:
    release = get_release(release_id)
    if release is None:
        raise HTTPException(status_code=404, detail="Release not found")
    if release.publication_status == PublicationStatus.PUBLISHED:
        return RedirectResponse(url=f"/review/{release_id}?flash=release_published", status_code=303)
    update_release_publication_status(
        release_id,
        PublicationStatus.DRAFT,
        note="Preview отменен. Можно продолжить ревью и сформировать preview заново.",
    )
    return RedirectResponse(url=f"/review/{release_id}?flash=preview_returned", status_code=303)


@app.post("/review/{release_id}/publish-digest")
def publish_digest(request: Request, release_id: str) -> RedirectResponse:
    release = get_release(release_id)
    if release is None:
        raise HTTPException(status_code=404, detail="Release not found")
    if release.publication_status == PublicationStatus.PUBLISHED:
        return RedirectResponse(url=f"/review/{release_id}?flash=release_published", status_code=303)
    items = list_items(release_id)
    if release.publication_status != PublicationStatus.PREVIEW or digest_blockers(release, items):
        return RedirectResponse(url=f"/review/{release_id}?flash=preview_required", status_code=303)
    _, owner_name = _review_lock_owner(request)
    try:
        snapshot = build_published_digest_snapshot(release, items, owner_name, UPLOADS_DIR)
    except PublicationError:
        return RedirectResponse(url=f"/review/{release_id}?flash=publish_media_error", status_code=303)
    save_published_digest(snapshot)
    update_release_publication_status(
        release_id,
        PublicationStatus.PUBLISHED,
        note="Дайджест опубликован. Релиз закрыт для редактирования.",
        published_by=owner_name,
    )
    return RedirectResponse(url=f"/digest/{release_id}", status_code=303)
```

- [ ] **Step 6: Reset preview after review edits**

In `update_summary()`, after `update_release_summary(...)`, add:

```python
    reset_preview_after_review_change(release_id)
```

In `update_review_item()`, after `update_item(...)`, add:

```python
    reset_preview_after_review_change(release_id)
```

In `upload_item_image()`, after `add_item_image(...)`, add:

```python
    reset_preview_after_review_change(release_id)
```

In `delete_item_image()`, after `remove_item_image(...)`, add:

```python
    reset_preview_after_review_change(release_id)
```

- [ ] **Step 7: Block edits after publish**

At the start of `update_summary()`, `update_review_item()`, `upload_item_image()`, and `delete_item_image()`, after existence checks where needed, add:

```python
    if _release_is_published(release_id):
        return _published_release_response(request, release_id)
```

- [ ] **Step 8: Run route tests**

Run the command from Step 2.

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add app/main.py app/storage.py tests/test_review_page_logic.py
git commit -m "Add digest publication workflow actions"
```

---

### Task 4: Add Preview, Public Snapshot, And Archive Routes

**Files:**
- Modify: `app/main.py`
- Create: `templates/digests.html`
- Modify: `templates/digest.html`
- Test: `tests/test_review_page_logic.py`

- [ ] **Step 1: Write failing route behavior tests**

Add these tests to `DigestGuardTests`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
/Users/user/Downloads/релиз\ ноутс2/.venv/bin/python -m unittest \
  tests.test_review_page_logic.DigestGuardTests.test_digest_public_page_shows_preparation_until_published \
  tests.test_review_page_logic.DigestGuardTests.test_preview_route_requires_preview_status \
  tests.test_review_page_logic.DigestGuardTests.test_preview_route_renders_live_approved_data \
  tests.test_review_page_logic.DigestGuardTests.test_public_digest_reads_published_snapshot_not_live_review \
  tests.test_review_page_logic.DigestGuardTests.test_archive_lists_only_published_snapshots -v
```

Expected: FAIL because routes/templates still use live digest behavior.

- [ ] **Step 3: Add preview route**

Add this route before `final_digest`:

```python
@app.get("/review/{release_id}/digest-preview", response_class=HTMLResponse)
def digest_preview(request: Request, release_id: str) -> HTMLResponse:
    release = get_release(release_id)
    if release is None:
        raise HTTPException(status_code=404, detail="Release not found")
    items = list_items(release_id)
    blockers = digest_blockers(release, items)
    if release.publication_status != PublicationStatus.PREVIEW or blockers:
        return templates.TemplateResponse(
            request,
            "digest.html",
            {
                "release": release,
                "page_mode": "preview_unavailable",
                "preparation_message": "Preview еще не сформирован",
                "sections": [],
                "metrics": {},
                "review_user": getattr(request.state, "review_session", {}).get("user"),
            },
        )
    content = build_live_digest_content(items)
    return templates.TemplateResponse(
        request,
        "digest.html",
        {
            "release": release,
            "page_mode": "preview",
            "sections": content["sections"],
            "metrics": content["metrics"],
            "review_user": getattr(request.state, "review_session", {}).get("user"),
        },
    )
```

- [ ] **Step 4: Replace public digest route**

Replace the body of `final_digest()` after the release lookup with:

```python
    snapshot = get_published_digest(release_id)
    review_user = load_session(request, auth_settings).get("user")
    if snapshot is None:
        return templates.TemplateResponse(
            request,
            "digest.html",
            {
                "release": release,
                "page_mode": "preparation",
                "preparation_message": "Дайджест в подготовке",
                "sections": [],
                "metrics": {},
                "review_user": review_user,
            },
        )

    return templates.TemplateResponse(
        request,
        "digest.html",
        {
            "release": release,
            "snapshot": snapshot,
            "page_mode": "public",
            "sections": snapshot.content.get("sections", []),
            "metrics": snapshot.content.get("metrics", {}),
            "review_user": review_user,
        },
    )
```

- [ ] **Step 5: Add archive route**

Add:

```python
@app.get("/digests", response_class=HTMLResponse)
def digest_archive(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "digests.html",
        {"digests": list_published_digests()},
    )
```

Add `list_published_digests` to storage imports.

- [ ] **Step 6: Replace `templates/digest.html` with mode-aware template**

Use this template as the minimal functional version; branding is expanded in Task 6:

```html
<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Дайджест релиза {{ release.id }}</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 0; background: #f5f7fb; color: #09081e; }
    .page { max-width: 1080px; margin: 0 auto; padding: 40px 20px 64px; }
    .hero, .card, details { background: #fff; border: 1px solid #e6eaf8; border-radius: 8px; padding: 24px; }
    .hero { margin-bottom: 24px; }
    .banner { padding: 12px 16px; border-radius: 8px; background: #d9ffdb; font-weight: 700; margin-bottom: 16px; }
    .toc { display: flex; gap: 10px; flex-wrap: wrap; margin: 20px 0; }
    .toc a { color: #09081e; background: #d9ffdb; border-radius: 999px; padding: 8px 12px; text-decoration: none; font-weight: 700; }
    .section { margin-top: 28px; }
    .grid { display: grid; gap: 16px; }
    .badge { display: inline-block; background: #d9ffdb; border-radius: 999px; padding: 4px 10px; font-weight: 700; font-size: 13px; }
    .actions { display: flex; gap: 12px; flex-wrap: wrap; margin-top: 18px; }
    .button { border: 0; background: #49de4e; color: #09081e; border-radius: 8px; padding: 10px 14px; font-weight: 700; text-decoration: none; cursor: pointer; }
  </style>
</head>
<body>
  <main class="page">
    {% if page_mode == "preview" %}
      <div class="banner">Предпросмотр</div>
    {% endif %}

    {% if page_mode in ["preparation", "preview_unavailable"] %}
      <section class="hero">
        <h1>{{ preparation_message }}</h1>
        <p>Дайджест появится здесь после публикации.</p>
        {% if review_user %}
          <p><a href="/review/{{ release.id }}">Вернуться в ревью</a></p>
        {% endif %}
      </section>
    {% else %}
      <section class="hero">
        <p>Дата релиза: <strong>{{ release.release_date }}</strong></p>
        <h1>Дайджест релиза</h1>
        <p>{{ release.summary if page_mode == "preview" else snapshot.summary }}</p>
        {% if page_mode == "preview" %}
          <div class="actions">
            <form method="post" action="/review/{{ release.id }}/publish-digest">
              <button type="submit" class="button">Опубликовать дайджест</button>
            </form>
            <form method="post" action="/review/{{ release.id }}/return-digest-to-review">
              <button type="submit" class="button">Вернуться к ревью</button>
            </form>
          </div>
        {% endif %}
      </section>

      {% if sections %}
        <nav class="toc" aria-label="Оглавление">
          {% for section in sections %}
            <a href="#{{ section.id }}">{{ section.title }}</a>
          {% endfor %}
        </nav>
      {% endif %}

      {% for section in sections %}
        <section class="section" id="{{ section.id }}">
          {% if section.collapsed %}
            <details>
              <summary>{{ section.title }}</summary>
              <div class="grid">
                {% for item in section["items"] %}
                  {% include "digest_item_card.html" %}
                {% endfor %}
              </div>
            </details>
          {% else %}
            <h2>{{ section.title }}</h2>
            <div class="grid">
              {% for item in section["items"] %}
                {% include "digest_item_card.html" %}
              {% endfor %}
            </div>
          {% endif %}
        </section>
      {% endfor %}
    {% endif %}
  </main>
</body>
</html>
```

- [ ] **Step 7: Update `templates/digest_item_card.html` for dictionary payloads**

Replace it with:

```html
<article class="card">
  <p>{{ item.module }}</p>
  {% if item.value_category_label %}
    <span class="badge">{{ item.value_category_label }}</span>
  {% endif %}
  {% if item.is_paid_feature %}
    <span class="badge">Платная функция</span>
  {% endif %}
  <h3>{{ item.title }}</h3>
  {% if item.description %}
    <p>{{ item.description }}</p>
  {% endif %}
  {% if item.tracker_urls %}
    <p><a href="{{ item.tracker_urls[0] }}">Задача в трекере</a></p>
  {% endif %}
  {% if item.media %}
    <div class="media-strip">
      {% for media in item.media %}
        {% if media.kind == "video" %}
          <video src="{{ media.path }}" controls preload="metadata" style="max-width: 100%;"></video>
        {% else %}
          <img src="{{ media.path }}" alt="Иллюстрация к пункту {{ item.title }}" style="max-width: 100%;">
        {% endif %}
      {% endfor %}
    </div>
  {% endif %}
</article>
```

- [ ] **Step 8: Create archive template**

Create `templates/digests.html`:

```html
<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Архив дайджестов</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 0; background: #f5f7fb; color: #09081e; }
    .page { max-width: 1080px; margin: 0 auto; padding: 48px 20px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 18px; }
    .card { background: #fff; border: 1px solid #e6eaf8; border-radius: 8px; padding: 22px; position: relative; overflow: hidden; }
    .card::after { content: ""; position: absolute; right: -40px; top: -30px; width: 140px; height: 90px; background: #d9ffdb; transform: skewX(-18deg); border-radius: 8px; }
    a { color: #09081e; font-weight: 700; }
  </style>
</head>
<body>
  <main class="page">
    <h1>Архив дайджестов</h1>
    <div class="grid">
      {% for digest in digests %}
        <article class="card">
          <p>{{ digest.release_date }}</p>
          <h2>{{ digest.release_id }}</h2>
          <p>{{ digest.summary }}</p>
          <p>{{ digest.content.metrics.items_count if digest.content.metrics else 0 }} пунктов</p>
          <a href="/digest/{{ digest.release_id }}">Открыть дайджест</a>
        </article>
      {% else %}
        <p>Пока нет опубликованных дайджестов.</p>
      {% endfor %}
    </div>
  </main>
</body>
</html>
```

- [ ] **Step 9: Run route tests**

Run the command from Step 2.

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add app/main.py templates/digest.html templates/digest_item_card.html templates/digests.html tests/test_review_page_logic.py
git commit -m "Add digest preview and archive routes"
```

---

### Task 5: Update Review Publication UI

**Files:**
- Modify: `templates/review.html`
- Modify: `app/main.py`
- Test: `tests/test_review_page_logic.py`

- [ ] **Step 1: Write failing review UI tests**

Add tests to `DigestGuardTests`:

```python
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
```

- [ ] **Step 2: Run UI tests to verify they fail**

Run:

```bash
/Users/user/Downloads/релиз\ ноутс2/.venv/bin/python -m unittest \
  tests.test_review_page_logic.DigestGuardTests.test_review_page_shows_prepare_preview_action_when_ready \
  tests.test_review_page_logic.DigestGuardTests.test_review_page_shows_publish_action_in_preview_state \
  tests.test_review_page_logic.DigestGuardTests.test_review_page_shows_published_audit_and_open_digest_action -v
```

Expected: FAIL because review template still has old action copy and Telegram digest action.

- [ ] **Step 3: Pass publication labels to review template**

In `review_release()`, add to template context:

```python
            "publication_status": release.publication_status,
            "publication_statuses": PublicationStatus,
```

- [ ] **Step 4: Replace review action bar publication area**

In `templates/review.html`, replace the current `.action-copy` and `.action-buttons` content inside `<section class="action-bar">` with:

```html
        <div class="action-copy">
          {% if release.publication_status.value == "published" %}
            <strong>Дайджест опубликован</strong>
            <small>Опубликовал: {{ release.published_by }}{% if release.published_at %}, {{ release.published_at }}{% endif %}. Релиз закрыт для редактирования.</small>
          {% elif release.publication_status.value == "preview" %}
            <strong>Preview сформирован</strong>
            <small>{{ release.publication_status_note or "Проверьте страницу preview перед публикацией." }}</small>
          {% else %}
            <strong>Дайджест в подготовке</strong>
            <small>{{ release.publication_status_note or "Когда все пункты подтверждены или исключены, сформируйте preview." }}</small>
          {% endif %}
        </div>
        <div class="action-buttons">
          {% if release.publication_status.value == "published" %}
            <a href="/digest/{{ release.id }}" class="button button-primary">Открыть опубликованный дайджест</a>
          {% elif release.publication_status.value == "preview" %}
            <a href="/review/{{ release.id }}/digest-preview" class="button button-primary">Открыть preview</a>
            <form method="post" action="/review/{{ release.id }}/publish-digest">
              <button type="submit" class="button button-dark" {% if not digest_ready %}disabled{% endif %}>Опубликовать дайджест</button>
            </form>
            <form method="post" action="/review/{{ release.id }}/return-digest-to-review">
              <button type="submit" class="button button-subtle">Вернуться к ревью</button>
            </form>
            <small class="publish-hint">Публикация зафиксирует версию и закроет релиз от редактирования.</small>
          {% else %}
            <form method="post" action="/review/{{ release.id }}/prepare-digest-preview">
              <button type="submit" class="button button-primary" {% if not digest_ready %}disabled{% endif %}>Сформировать preview</button>
            </form>
            <form method="post" action="/review/{{ release.id }}/notify-review">
              <button type="submit" class="button button-subtle">Отправить статус ревью в Telegram</button>
            </form>
          {% endif %}
        </div>
```

Keep the existing quick filters below this row.

- [ ] **Step 5: Add flash messages**

In `templates/review.html`, extend flash handling:

```html
    {% elif flash == "preview_returned" %}
      <div class="flash success">Preview отменен. Можно продолжить ревью.</div>
    {% elif flash == "preview_required" %}
      <div class="flash error">Сначала сформируйте preview и проверьте его перед публикацией.</div>
    {% elif flash == "publish_media_error" %}
      <div class="flash error">Не удалось опубликовать дайджест: один из медиафайлов недоступен.</div>
    {% elif flash == "release_published" %}
      <div class="flash success">Дайджест уже опубликован. Редактирование закрыто.</div>
```

- [ ] **Step 6: Hide edit controls when published**

Add a helper variable near each editable form or wrap the main editable controls:

```jinja2
{% set release_published = release.publication_status.value == "published" %}
```

For summary and item save buttons, add:

```html
{% if not release_published %}
  <button type="submit" class="button button-primary">Сохранить изменения</button>
{% endif %}
```

For upload/delete controls, render them only if not published:

```jinja2
{% if not release_published %}
  ... upload/delete controls ...
{% endif %}
```

Do not remove the readonly text fields in this task; hiding submit/upload controls is enough because server guards block writes.

- [ ] **Step 7: Run UI tests**

Run the command from Step 2.

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add app/main.py templates/review.html tests/test_review_page_logic.py
git commit -m "Update review publication controls"
```

---

### Task 6: Add Brand Assets And Branded Digest Design

**Files:**
- Modify: `app/config.py`
- Modify: `app/main.py`
- Modify: `templates/digest.html`
- Modify: `templates/digest_item_card.html`
- Modify: `templates/digests.html`
- Create: `static/brand/Logo_Skillaz_RGB.svg`
- Create: `static/brand/OnestRegular1602-hint.ttf`
- Create: `static/brand/OnestBold1602-hint.ttf`
- Test: `tests/test_review_page_logic.py`

- [ ] **Step 1: Copy selected assets**

Run:

```bash
mkdir -p static/brand
cp "/Users/user/Desktop/Подбор/Logo_Skillaz 2/Logo_Skillaz/RGB/Logo_Skillaz_RGB.svg" static/brand/Logo_Skillaz_RGB.svg
cp "/Users/user/Desktop/Подбор/Font_Skillaz 3/Onest (интерфейс и текст)/OnestRegular1602-hint.ttf" static/brand/OnestRegular1602-hint.ttf
cp "/Users/user/Desktop/Подбор/Font_Skillaz 3/Onest (интерфейс и текст)/OnestBold1602-hint.ttf" static/brand/OnestBold1602-hint.ttf
```

Expected: three files exist in `static/brand/`.

- [ ] **Step 2: Mount static assets**

In `app/main.py`, import `STATIC_DIR` from config:

```python
    STATIC_DIR,
```

After the uploads mount, add:

```python
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
```

- [ ] **Step 3: Write failing brand tests**

Add these tests to `DigestGuardTests`:

```python
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
                            "items": [{"title": "Snapshot feature", "description": "Snapshot text", "module": "Core", "value_category_label": "Экономия времени", "is_paid_feature": True, "media": []}],
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
        self.assertIn("/static/brand/Logo_Skillaz_RGB.svg", response.text)
        self.assertIn("Подбор", response.text)
        self.assertIn("Оглавление", response.text)
        self.assertIn("#49DE4E", response.text)

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
                            "items": [{
                                "title": "Media feature",
                                "description": "Snapshot text",
                                "module": "Core",
                                "value_category_label": "",
                                "is_paid_feature": False,
                                "media": [
                                    {"path": "/uploads/published/2026-04/a.png", "kind": "image"},
                                    {"path": "/uploads/published/2026-04/b.png", "kind": "image"},
                                ],
                            }],
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
        self.assertIn('data-carousel', response.text)
```

- [ ] **Step 4: Replace digest visual styling**

Update `templates/digest.html` to keep the same Jinja logic from Task 4, but replace the `<style>` block and hero markup with:

```html
  <style>
    @font-face { font-family: "Onest"; src: url("/static/brand/OnestRegular1602-hint.ttf") format("truetype"); font-weight: 400; }
    @font-face { font-family: "Onest"; src: url("/static/brand/OnestBold1602-hint.ttf") format("truetype"); font-weight: 700; }
    :root {
      --white: #FFFFFF;
      --gray: #EFEFEF;
      --ink: #09081E;
      --ink-soft: #1A234A;
      --muted: #7A85A7;
      --line: #E6EAF8;
      --accent: #49DE4E;
      --accent-soft: #D9FFDB;
    }
    * { box-sizing: border-box; }
    body { margin: 0; font-family: "Onest", Arial, sans-serif; background: var(--gray); color: var(--ink); line-height: 1.55; }
    .page { max-width: 1180px; margin: 0 auto; padding: 28px 20px 72px; }
    .brand-row { display: flex; align-items: center; justify-content: space-between; gap: 18px; margin-bottom: 34px; }
    .brand-logo { width: 132px; max-width: 42vw; }
    .product-badge { display: inline-flex; align-items: center; padding: 8px 18px; border-radius: 8px; transform: skewX(-14deg); background: var(--accent); color: var(--ink); font-weight: 700; }
    .product-badge span { transform: skewX(14deg); }
    .hero { position: relative; overflow: hidden; min-height: 430px; border-radius: 8px; background: var(--white); padding: 42px; display: flex; flex-direction: column; justify-content: center; border: 1px solid var(--line); }
    .hero::before { content: ""; position: absolute; inset: 42px 8% auto auto; width: 260px; height: 180px; background: var(--accent-soft); border-radius: 42px; transform: skewX(-18deg); }
    .hero::after { content: ""; position: absolute; right: 18%; bottom: -80px; width: 280px; height: 220px; background: #E6EAF8; border-radius: 50%; }
    .hero-content { position: relative; z-index: 1; max-width: 760px; }
    .eyebrow { color: var(--muted); font-weight: 700; margin: 0 0 16px; }
    h1 { margin: 0; font-size: 58px; line-height: 1.02; letter-spacing: 0; }
    .summary { margin: 22px 0 0; font-size: 20px; color: var(--ink-soft); max-width: 760px; }
    .banner { padding: 12px 16px; border-radius: 8px; background: var(--accent-soft); font-weight: 700; margin-bottom: 16px; }
    .toc-wrap { margin: 24px 0 8px; }
    .toc-title { margin: 0 0 10px; color: var(--muted); font-weight: 700; }
    .toc { display: flex; gap: 10px; flex-wrap: wrap; }
    .toc a { color: var(--ink); background: var(--white); border: 1px solid var(--line); border-radius: 999px; padding: 9px 14px; text-decoration: none; font-weight: 700; }
    .section { margin-top: 42px; }
    .section h2 { font-size: 32px; margin: 0 0 18px; letter-spacing: 0; }
    .grid { display: grid; gap: 18px; }
    .card, details { background: var(--white); border: 1px solid var(--line); border-radius: 8px; padding: 24px; }
    .badge { display: inline-block; background: var(--accent-soft); border-radius: 999px; padding: 5px 11px; font-weight: 700; font-size: 13px; margin-right: 6px; }
    .actions { display: flex; gap: 12px; flex-wrap: wrap; margin-top: 22px; }
    .button { border: 0; background: var(--accent); color: var(--ink); border-radius: 8px; padding: 11px 16px; font-weight: 700; text-decoration: none; cursor: pointer; }
    @media (max-width: 720px) {
      .hero { min-height: 360px; padding: 28px; }
      h1 { font-size: 40px; }
      .summary { font-size: 17px; }
    }
  </style>
```

Use this hero markup in the non-preparation branch:

```html
      <section class="hero">
        <div class="brand-row">
          <img class="brand-logo" src="/static/brand/Logo_Skillaz_RGB.svg" alt="Skillaz">
          <div class="product-badge"><span>Подбор</span></div>
        </div>
        <div class="hero-content">
          <p class="eyebrow">Дата релиза: <strong>{{ release.release_date }}</strong></p>
          <h1>Дайджест релиза</h1>
          <p class="summary">{{ release.summary if page_mode == "preview" else snapshot.summary }}</p>
          ...
        </div>
      </section>
```

Add the table of contents label:

```html
        <div class="toc-wrap">
          <p class="toc-title">Оглавление</p>
          <nav class="toc" aria-label="Оглавление">
            ...
          </nav>
        </div>
```

- [ ] **Step 5: Add carousel markup**

In `templates/digest_item_card.html`, replace the media block with:

```html
  {% if item.media %}
    {% if item.media|length > 1 %}
      <div class="media-carousel" data-carousel>
        <div class="media-track">
          {% for media in item.media %}
            <div class="media-slide">
              {% if media.kind == "video" %}
                <video src="{{ media.path }}" controls preload="metadata"></video>
              {% else %}
                <img src="{{ media.path }}" alt="Иллюстрация к пункту {{ item.title }}">
              {% endif %}
            </div>
          {% endfor %}
        </div>
        <div class="media-controls" aria-label="Навигация по медиа">
          {% for media in item.media %}
            <span class="media-dot"></span>
          {% endfor %}
        </div>
      </div>
    {% else %}
      <div class="media-single">
        {% set media = item.media[0] %}
        {% if media.kind == "video" %}
          <video src="{{ media.path }}" controls preload="metadata"></video>
        {% else %}
          <img src="{{ media.path }}" alt="Иллюстрация к пункту {{ item.title }}">
        {% endif %}
      </div>
    {% endif %}
  {% endif %}
```

Add CSS to `templates/digest.html`:

```css
    .media-single, .media-carousel { margin-top: 18px; }
    .media-track { display: grid; grid-auto-flow: column; grid-auto-columns: 100%; overflow-x: auto; scroll-snap-type: x mandatory; gap: 12px; }
    .media-slide { scroll-snap-align: start; }
    .media-single img, .media-single video, .media-slide img, .media-slide video { width: 100%; max-height: 520px; object-fit: contain; border-radius: 8px; border: 1px solid var(--line); background: #fff; }
    .media-controls { display: flex; gap: 6px; justify-content: center; margin-top: 10px; }
    .media-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--accent); opacity: .45; }
```

- [ ] **Step 6: Brand archive page**

Update `templates/digests.html` to use the same font-face, logo, product badge, colors, and editorial card styling from digest page. Keep the test strings `Архив дайджестов`, release id, summary, and `/digest/{release_id}` link.

- [ ] **Step 7: Run brand tests**

Run:

```bash
/Users/user/Downloads/релиз\ ноутс2/.venv/bin/python -m unittest \
  tests.test_review_page_logic.DigestGuardTests.test_public_digest_uses_brand_assets_and_toc \
  tests.test_review_page_logic.DigestGuardTests.test_multiple_media_render_as_carousel -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add app/config.py app/main.py templates/digest.html templates/digest_item_card.html templates/digests.html static/brand tests/test_review_page_logic.py
git commit -m "Brand public digest pages"
```

---

### Task 7: Final Regression And Manual Preview

**Files:**
- Modify only if tests reveal a defect.

- [ ] **Step 1: Run focused digest tests**

Run:

```bash
/Users/user/Downloads/релиз\ ноутс2/.venv/bin/python -m unittest tests.test_review_page_logic.DigestGuardTests -v
```

Expected: all tests pass.

- [ ] **Step 2: Run full explicit suite**

Run:

```bash
/Users/user/Downloads/релиз\ ноутс2/.venv/bin/python -m unittest \
  tests.test_importer_copy_preservation \
  tests.test_ingest_ai_generation \
  tests.test_review_auth \
  tests.test_review_page_logic \
  tests.test_telegram_webhook -v
```

Expected: all tests pass.

- [ ] **Step 3: Start local server**

Run:

```bash
/Users/user/Downloads/релиз\ ноутс2/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Expected: server starts at `http://127.0.0.1:8001`.

- [ ] **Step 4: Create demo release**

Run:

```bash
curl -sS -X POST -i http://127.0.0.1:8001/releases/bootstrap
```

Expected: `303 See Other` to `/review/2026-04`.

- [ ] **Step 5: Manually approve demo release for preview**

Run this one-off script:

```bash
/Users/user/Downloads/релиз\ ноутс2/.venv/bin/python -c "from app.storage import get_release, list_items, update_item, update_release_summary; from app.models import ItemStatus, SummaryStatus; release=get_release('2026-04'); update_release_summary('2026-04', release.summary, SummaryStatus.APPROVED.value, expected_version=release.version); [update_item(item_id=i.id, title=i.title, description=i.description, category=i.category.value if i.category else None, status=ItemStatus.APPROVED.value, is_paid_feature=i.is_paid_feature, expected_version=i.version) for i in list_items('2026-04') if i.type.value != 'release_candidate']"
```

Expected: no output.

- [ ] **Step 6: Verify pages manually**

Open:

```text
http://127.0.0.1:8001/review/2026-04
http://127.0.0.1:8001/digest/2026-04
http://127.0.0.1:8001/digests
```

Expected:

- review shows publication block;
- public digest says `Дайджест в подготовке` before publish;
- archive opens and does not show unpublished releases.

Then use the review buttons to prepare preview and publish.

- [ ] **Step 7: Commit any fixes**

If manual verification required fixes, stage the exact files changed during verification. For example, if only digest templates changed:

```bash
git add templates/digest.html templates/digest_item_card.html
git commit -m "Polish digest publication flow"
```

If no fixes were needed, do not create an empty commit.

---

## Self-Review Notes

- Spec coverage:
  - Publication lifecycle: Tasks 1, 3, 5.
  - Live protected preview: Tasks 3, 4.
  - Published snapshot and media copy: Tasks 1, 2, 4.
  - Public digest preparation state: Task 4.
  - Public archive: Task 4 and Task 6.
  - Review edit blocking after publish: Task 3 and Task 5.
  - Preview reset after changes: Task 3 and Task 5.
  - Branded Skillaz/Подбор visual concept: Task 6.
  - Carousel for multiple media: Task 6.
  - Railway boundary: not implemented; explicitly excluded from this plan.
- Scope:
  - No rollback.
  - No multiple published versions inside one release.
  - No AI regeneration on publish.
  - No automatic Railway deploy.
- Test command:
  - Use `python -m unittest`; `pytest` is not installed in the project environment.
