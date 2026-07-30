# Static Digest ZIP Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the primary digest publication action with a repeatable download of a self-contained ZIP containing `index.html` and all required assets.

**Architecture:** Add a focused static-export service that builds current approved digest content, rewrites media to safe relative asset names, renders the existing digest template in a final `export` mode, and writes the HTML plus binary assets to an in-memory ZIP. Expose it through a protected preview-state review endpoint; keep legacy published snapshots and public routes untouched for existing links.

**Tech Stack:** Python 3, FastAPI, Jinja2, standard-library `io` and `zipfile`, SQLite-backed review state, `unittest` and FastAPI `TestClient`.

## Global Constraints

- The downloaded layout is `<release-id>/index.html` plus `<release-id>/assets/`.
- ZIP generation is repeatable and must not change the release to `published`.
- Export content comes from the current review state and includes approved non-release-candidate items only.
- All fonts, branding, images, and videos must use relative `assets/...` paths.
- A missing required asset fails the whole export; no partial ZIP is returned.
- Existing published snapshots, `/digest/{release_id}`, and `/digests` remain compatible.
- No new third-party runtime dependency is added.

---

## File map

- Create `app/services/static_export.py`: validate assets, generate safe unique archive names, rewrite media paths, render final HTML, and build ZIP bytes.
- Modify `templates/digest.html`: support final `export` rendering and configurable brand/font paths while preserving preview and public modes.
- Modify `app/main.py`: add the protected ZIP download endpoint and map export errors to the review UI.
- Modify `templates/review.html`: replace the primary publication action and explanatory copy with ZIP generation.
- Modify `tests/test_review_page_logic.py`: cover service output, endpoint state behavior, repeatability, failure handling, UI copy, and legacy route compatibility.

### Task 1: Build the deterministic static-export service

**Files:**
- Create: `app/services/static_export.py`
- Modify: `templates/digest.html`
- Test: `tests/test_review_page_logic.py`

**Interfaces:**
- Consumes: `DigestRelease`, `Iterable[DigestItem]`, `build_live_digest_content(items)`, filesystem paths for uploads/static assets, and a Jinja `Environment`.
- Produces: `StaticExportError`; `build_static_digest_zip(release: DigestRelease, items: Iterable[DigestItem], uploads_dir: Path, static_dir: Path, template_env: jinja2.Environment) -> bytes`.

- [ ] **Step 1: Read the test-quality rules before editing tests**

Read completely:

```text
/Users/user/.codex/plugins/cache/openai-curated-remote/superpowers/6.2.0/skills/writing-good-tests.md
```

- [ ] **Step 2: Add failing service tests**

Add imports to `tests/test_review_page_logic.py`:

```python
import zipfile
```

Add these tests to `DigestGuardTests`:

```python
def test_static_export_zip_contains_final_html_and_relative_assets(self) -> None:
    media_source = self.config.UPLOADS_DIR / "screen.png"
    media_source.write_bytes(b"image-bytes")
    self.storage.update_item(
        item_id="item-1",
        title="Exported feature",
        description="Exported description",
        category=ValueCategory.TIME_SAVING.value,
        status=ItemStatus.APPROVED.value,
        is_paid_feature=False,
    )
    self.storage.add_item_image("item-1", "/uploads/screen.png")

    from app.services.static_export import build_static_digest_zip

    archive_bytes = build_static_digest_zip(
        release=self.storage.get_release("2026-04"),
        items=self.storage.list_items("2026-04"),
        uploads_dir=self.config.UPLOADS_DIR,
        static_dir=self.config.STATIC_DIR,
        template_env=self.main.templates.env,
    )

    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        names = set(archive.namelist())
        html = archive.read("2026-04/index.html").decode("utf-8")
        self.assertIn("2026-04/assets/Logo_Skillaz_Black.png", names)
        self.assertIn("2026-04/assets/OnestRegular1602-hint.ttf", names)
        self.assertIn("2026-04/assets/OnestBold1602-hint.ttf", names)
        self.assertIn("2026-04/assets/screen.png", names)
        self.assertEqual(archive.read("2026-04/assets/screen.png"), b"image-bytes")
        self.assertIn("Exported feature", html)
        self.assertIn('src="assets/screen.png"', html)
        self.assertIn('src="assets/Logo_Skillaz_Black.png"', html)
        self.assertIn('url("assets/OnestRegular1602-hint.ttf")', html)
        self.assertNotIn("/uploads/", html)
        self.assertNotIn("/static/", html)
        self.assertNotIn("Предпросмотр", html)
        self.assertNotIn("Опубликовать дайджест", html)

def test_static_export_uses_collision_safe_media_names(self) -> None:
    first_dir = self.config.UPLOADS_DIR / "one"
    second_dir = self.config.UPLOADS_DIR / "two"
    first_dir.mkdir()
    second_dir.mkdir()
    (first_dir / "screen.png").write_bytes(b"first")
    (second_dir / "screen.png").write_bytes(b"second")
    self.storage.update_item(
        item_id="item-1",
        title="Exported feature",
        description="Exported description",
        category="",
        status=ItemStatus.APPROVED.value,
        is_paid_feature=False,
    )
    self.storage.add_item_image("item-1", "/uploads/one/screen.png")
    self.storage.add_item_image("item-1", "/uploads/two/screen.png")

    from app.services.static_export import build_static_digest_zip

    archive_bytes = build_static_digest_zip(
        self.storage.get_release("2026-04"),
        self.storage.list_items("2026-04"),
        self.config.UPLOADS_DIR,
        self.config.STATIC_DIR,
        self.main.templates.env,
    )

    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        media_names = sorted(
            name for name in archive.namelist()
            if name.startswith("2026-04/assets/screen") and name.endswith(".png")
        )
        self.assertEqual(media_names, [
            "2026-04/assets/screen-2.png",
            "2026-04/assets/screen.png",
        ])
        self.assertEqual(
            {archive.read(name) for name in media_names},
            {b"first", b"second"},
        )

def test_static_export_fails_when_review_media_is_missing(self) -> None:
    self.storage.update_item(
        item_id="item-1",
        title="Exported feature",
        description="Exported description",
        category="",
        status=ItemStatus.APPROVED.value,
        is_paid_feature=False,
    )
    self.storage.add_item_image("item-1", "/uploads/missing.png")

    from app.services.static_export import StaticExportError, build_static_digest_zip

    with self.assertRaises(StaticExportError):
        build_static_digest_zip(
            self.storage.get_release("2026-04"),
            self.storage.list_items("2026-04"),
            self.config.UPLOADS_DIR,
            self.config.STATIC_DIR,
            self.main.templates.env,
        )
```

- [ ] **Step 3: Run the service tests and verify RED**

Run:

```bash
python3 -m unittest \
  tests.test_review_page_logic.DigestGuardTests.test_static_export_zip_contains_final_html_and_relative_assets \
  tests.test_review_page_logic.DigestGuardTests.test_static_export_uses_collision_safe_media_names \
  tests.test_review_page_logic.DigestGuardTests.test_static_export_fails_when_review_media_is_missing -v
```

Expected: all three error with `ModuleNotFoundError: No module named 'app.services.static_export'`.

- [ ] **Step 4: Implement the service**

Create `app/services/static_export.py` with:

```python
from copy import deepcopy
import io
from pathlib import Path, PurePosixPath
from typing import Iterable
import zipfile

from jinja2 import Environment

from app.models import DigestItem, DigestRelease
from app.services.publication import build_live_digest_content


class StaticExportError(Exception):
    pass


BRAND_ASSETS = (
    "brand/Logo_Skillaz_Black.png",
    "brand/OnestRegular1602-hint.ttf",
    "brand/OnestBold1602-hint.ttf",
)


def build_static_digest_zip(
    release: DigestRelease,
    items: Iterable[DigestItem],
    uploads_dir: Path,
    static_dir: Path,
    template_env: Environment,
) -> bytes:
    root = _safe_release_root(release.id)
    content = deepcopy(build_live_digest_content(items))
    archive_assets: list[tuple[str, Path]] = []
    used_names: set[str] = set()

    for relative_path in BRAND_ASSETS:
        source = static_dir / relative_path
        if not source.is_file():
            raise StaticExportError(f"Missing brand asset: {relative_path}")
        asset_name = Path(relative_path).name
        used_names.add(asset_name.casefold())
        archive_assets.append((asset_name, source))

    for section in content["sections"]:
        for item in section["items"]:
            for media in item["media"]:
                source = _resolve_upload(media["path"], uploads_dir)
                if not source.is_file():
                    raise StaticExportError(f"Missing digest media: {media['path']}")
                asset_name = _unique_asset_name(source.name, used_names)
                archive_assets.append((asset_name, source))
                media["path"] = f"assets/{asset_name}"

    html = template_env.get_template("digest.html").render(
        release=release,
        page_mode="export",
        sections=content["sections"],
        metrics=content["metrics"],
        metric_labels=content["metric_labels"],
        brand_asset_prefix="assets",
    )

    output = io.BytesIO()
    try:
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(f"{root}/index.html", html.encode("utf-8"))
            for asset_name, source in archive_assets:
                archive.writestr(f"{root}/assets/{asset_name}", source.read_bytes())
    except (OSError, zipfile.BadZipFile) as exc:
        raise StaticExportError("Could not build digest archive") from exc
    return output.getvalue()


def _safe_release_root(release_id: str) -> str:
    safe = "".join(
        character if character.isalnum() or character in {"-", "_"} else "-"
        for character in release_id
    ).strip("-")
    return safe or "digest"


def _resolve_upload(public_path: str, uploads_dir: Path) -> Path:
    prefix = "/uploads/"
    if not public_path.startswith(prefix):
        raise StaticExportError(f"Unsupported media path: {public_path}")
    relative = PurePosixPath(public_path[len(prefix):])
    if relative.is_absolute() or ".." in relative.parts:
        raise StaticExportError(f"Unsafe media path: {public_path}")
    candidate = uploads_dir.joinpath(*relative.parts)
    try:
        candidate.resolve().relative_to(uploads_dir.resolve())
    except ValueError as exc:
        raise StaticExportError(f"Unsafe media path: {public_path}") from exc
    return candidate


def _unique_asset_name(original_name: str, used_names: set[str]) -> str:
    source_name = Path(original_name).name
    stem = Path(source_name).stem or "media"
    suffix = Path(source_name).suffix
    candidate = f"{stem}{suffix}"
    number = 2
    while candidate.casefold() in used_names:
        candidate = f"{stem}-{number}{suffix}"
        number += 1
    used_names.add(candidate.casefold())
    return candidate
```

Modify `templates/digest.html` so the font and logo URLs are configurable and export uses the live summary without preview actions:

```jinja2
{% set digest_asset_prefix = brand_asset_prefix|default("/static/brand") %}
```

Use:

```jinja2
url("{{ digest_asset_prefix }}/OnestRegular1602-hint.ttf")
url("{{ digest_asset_prefix }}/OnestBold1602-hint.ttf")
src="{{ digest_asset_prefix }}/Logo_Skillaz_Black.png"
```

Change summary selection to:

```jinja2
{{ release.summary if page_mode in ["preview", "export"] else snapshot.summary }}
```

Keep preview-only forms and filters guarded by the existing
`page_mode == "preview"` checks.

- [ ] **Step 5: Run the service tests and verify GREEN**

Run the three-test command from Step 3.

Expected: `OK`, three tests pass.

- [ ] **Step 6: Run existing digest rendering tests**

Run:

```bash
python3 -m unittest \
  tests.test_review_page_logic.DigestGuardTests.test_preview_route_renders_live_approved_data \
  tests.test_review_page_logic.DigestGuardTests.test_public_digest_uses_brand_assets_and_toc \
  tests.test_review_page_logic.DigestGuardTests.test_published_digest_does_not_render_preview_filters_or_type_badges -v
```

Expected: `OK`, legacy preview and public output remain unchanged.

- [ ] **Step 7: Commit the service**

```bash
git add app/services/static_export.py templates/digest.html tests/test_review_page_logic.py
git commit -m "Add static digest ZIP builder"
```

### Task 2: Add the protected repeatable download endpoint

**Files:**
- Modify: `app/main.py`
- Modify: `templates/review.html`
- Test: `tests/test_review_page_logic.py`

**Interfaces:**
- Consumes: `build_static_digest_zip(...) -> bytes`, `StaticExportError`, existing `get_release`, `list_items`, `digest_blockers`, `UPLOADS_DIR`, `STATIC_DIR`, and `templates.env`.
- Produces: `POST /review/{release_id}/export-digest` returning `application/zip` with an attachment filename; redirects with `preview_required` or `export_media_error` on failure.

- [ ] **Step 1: Add failing endpoint tests**

Add to `DigestGuardTests`:

```python
def test_export_endpoint_downloads_zip_without_publishing_release(self) -> None:
    self.storage.update_item(
        item_id="item-1",
        title="Exported feature",
        description="Exported description",
        category="",
        status=ItemStatus.APPROVED.value,
        is_paid_feature=False,
    )
    self._set_release_preview_ready()

    response = self.client.post(
        "/review/2026-04/export-digest",
        follow_redirects=False,
    )

    self.assertEqual(response.status_code, 200)
    self.assertEqual(response.headers["content-type"], "application/zip")
    self.assertIn('filename="2026-04.zip"', response.headers["content-disposition"])
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        self.assertIn("2026-04/index.html", archive.namelist())
    release = self.storage.get_release("2026-04")
    self.assertEqual(release.publication_status, PublicationStatus.PREVIEW)
    self.assertIsNone(self.storage.get_published_digest("2026-04"))

def test_export_endpoint_requires_ready_preview(self) -> None:
    response = self.client.post(
        "/review/2026-04/export-digest",
        follow_redirects=False,
    )

    self.assertEqual(response.status_code, 303)
    self.assertEqual(
        response.headers["location"],
        "/review/2026-04?flash=preview_required",
    )

def test_export_endpoint_redirects_when_media_is_missing(self) -> None:
    self.storage.update_item(
        item_id="item-1",
        title="Exported feature",
        description="Exported description",
        category="",
        status=ItemStatus.APPROVED.value,
        is_paid_feature=False,
    )
    self.storage.add_item_image("item-1", "/uploads/missing.png")
    self._set_release_preview_ready()

    response = self.client.post(
        "/review/2026-04/export-digest",
        follow_redirects=False,
    )

    self.assertEqual(response.status_code, 303)
    self.assertEqual(
        response.headers["location"],
        "/review/2026-04?flash=export_media_error",
    )
    self.assertEqual(
        self.storage.get_release("2026-04").publication_status,
        PublicationStatus.PREVIEW,
    )
```

- [ ] **Step 2: Run endpoint tests and verify RED**

Run:

```bash
python3 -m unittest \
  tests.test_review_page_logic.DigestGuardTests.test_export_endpoint_downloads_zip_without_publishing_release \
  tests.test_review_page_logic.DigestGuardTests.test_export_endpoint_requires_ready_preview \
  tests.test_review_page_logic.DigestGuardTests.test_export_endpoint_redirects_when_media_is_missing -v
```

Expected: all three fail because the route returns `404`.

- [ ] **Step 3: Implement the endpoint**

In `app/main.py`, import:

```python
from app.services.static_export import StaticExportError, build_static_digest_zip
```

Add before `digest_preview`:

```python
@app.post("/review/{release_id}/export-digest")
def export_digest(release_id: str) -> Response:
    release = get_release(release_id)
    if release is None:
        raise HTTPException(status_code=404, detail="Release not found")
    items = list_items(release_id)
    if release.publication_status != PublicationStatus.PREVIEW or digest_blockers(release, items):
        return RedirectResponse(
            url=f"/review/{release_id}?flash=preview_required",
            status_code=303,
        )
    try:
        archive = build_static_digest_zip(
            release=release,
            items=items,
            uploads_dir=UPLOADS_DIR,
            static_dir=STATIC_DIR,
            template_env=templates.env,
        )
    except StaticExportError:
        return RedirectResponse(
            url=f"/review/{release_id}?flash=export_media_error",
            status_code=303,
        )
    safe_filename = "".join(
        character if character.isalnum() or character in {"-", "_"} else "-"
        for character in release_id
    ).strip("-") or "digest"
    return Response(
        content=archive,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{safe_filename}.zip"'},
    )
```

Do not call `save_published_digest` or `update_release_publication_status` from
this endpoint.

- [ ] **Step 4: Run endpoint tests and verify GREEN**

Run the three-test command from Step 2.

Expected: `OK`, three tests pass.

- [ ] **Step 5: Commit the endpoint**

```bash
git add app/main.py tests/test_review_page_logic.py
git commit -m "Add repeatable digest ZIP endpoint"
```

### Task 3: Replace publication controls with export controls

**Files:**
- Modify: `templates/review.html`
- Modify: `templates/digest.html`
- Test: `tests/test_review_page_logic.py`

**Interfaces:**
- Consumes: `POST /review/{release_id}/export-digest`.
- Produces: Russian UI copy that describes ZIP generation as repeatable and does not claim the release will be locked or publicly published.

- [ ] **Step 1: Replace old UI expectations with failing export expectations**

Update `test_preview_route_renders_live_approved_data`:

```python
self.assertIn("Сформировать ZIP", response.text)
self.assertIn('action="/review/2026-04/export-digest"', response.text)
self.assertNotIn("Опубликовать дайджест", response.text)
```

Rename `test_review_page_shows_publish_action_in_preview_state` to
`test_review_page_shows_repeatable_export_action_in_preview_state` and assert:

```python
self.assertIn("Открыть preview", response.text)
self.assertIn("Сформировать ZIP", response.text)
self.assertIn('action="/review/2026-04/export-digest"', response.text)
self.assertIn("можно сформировать повторно", response.text)
self.assertNotIn("зафиксирует версию и закроет релиз", response.text)
```

Add:

```python
def test_review_page_explains_export_failure(self) -> None:
    response = self.client.get("/review/2026-04?flash=export_media_error")

    self.assertEqual(response.status_code, 200)
    self.assertIn("Не удалось сформировать ZIP", response.text)
    self.assertIn("медиафайлов", response.text)
```

- [ ] **Step 2: Run UI tests and verify RED**

Run:

```bash
python3 -m unittest \
  tests.test_review_page_logic.DigestGuardTests.test_preview_route_renders_live_approved_data \
  tests.test_review_page_logic.DigestGuardTests.test_review_page_shows_repeatable_export_action_in_preview_state \
  tests.test_review_page_logic.DigestGuardTests.test_review_page_explains_export_failure -v
```

Expected: failures show the existing publication action and missing export error copy.

- [ ] **Step 3: Update the review and preview controls**

In the preview-state branch of `templates/review.html`, replace the publish form
with:

```jinja2
<form method="post" action="/review/{{ release.id }}/export-digest">
  <button type="submit" class="button button-dark" {% if not digest_ready %}disabled{% endif %}>Сформировать ZIP</button>
</form>
```

Replace its hint with:

```jinja2
<small class="publish-hint">ZIP можно сформировать повторно после изменений; релиз останется доступен для редактирования.</small>
```

Add the flash branch:

```jinja2
{% elif flash == "export_media_error" %}
  <div class="flash error">Не удалось сформировать ZIP: один из медиафайлов или файлов оформления недоступен.</div>
```

In the preview actions inside `templates/digest.html`, replace the publication
form with the same `/export-digest` form and `Сформировать ZIP` label. Preserve
the `Вернуться к ревью` form.

- [ ] **Step 4: Run UI tests and verify GREEN**

Run the three-test command from Step 2.

Expected: `OK`, three tests pass.

- [ ] **Step 5: Commit the UI change**

```bash
git add templates/review.html templates/digest.html tests/test_review_page_logic.py
git commit -m "Replace digest publication action with ZIP export"
```

### Task 4: Verify repeat editing/export and legacy compatibility

**Files:**
- Modify: `tests/test_review_page_logic.py`

**Interfaces:**
- Consumes: existing item edit route, preview reset behavior, preview preparation, ZIP export endpoint, and legacy public digest routes.
- Produces: regression evidence that export is repeatable and old published pages still render.

- [ ] **Step 1: Add a repeat-export integration test**

Add to `DigestGuardTests`:

```python
def test_digest_can_be_edited_and_exported_again(self) -> None:
    self.storage.update_item(
        item_id="item-1",
        title="First export",
        description="Export description",
        category="",
        status=ItemStatus.APPROVED.value,
        is_paid_feature=False,
    )
    self._set_release_preview_ready()

    first_response = self.client.post("/review/2026-04/export-digest")
    with zipfile.ZipFile(io.BytesIO(first_response.content)) as archive:
        first_html = archive.read("2026-04/index.html").decode("utf-8")
    self.assertIn("First export", first_html)

    return_response = self.client.post(
        "/review/2026-04/return-digest-to-review",
        follow_redirects=False,
    )
    self.assertEqual(return_response.status_code, 303)
    item = self.storage.get_item("item-1")
    edit_response = self.client.post(
        "/review/2026-04/items/item-1",
        data={
            "title": "Second export",
            "description": "Updated export description",
            "category": "",
            "status": "approved",
            "object_version": str(item.version),
        },
        follow_redirects=False,
    )
    self.assertEqual(edit_response.status_code, 303)
    self._set_release_preview_ready()

    second_response = self.client.post("/review/2026-04/export-digest")
    with zipfile.ZipFile(io.BytesIO(second_response.content)) as archive:
        second_html = archive.read("2026-04/index.html").decode("utf-8")
    self.assertIn("Second export", second_html)
    self.assertNotIn("First export", second_html)
    self.assertEqual(
        self.storage.get_release("2026-04").publication_status,
        PublicationStatus.PREVIEW,
    )
```

- [ ] **Step 2: Run the repeat-export and legacy tests**

Run:

```bash
python3 -m unittest \
  tests.test_review_page_logic.DigestGuardTests.test_digest_can_be_edited_and_exported_again \
  tests.test_review_page_logic.DigestGuardTests.test_public_digest_reads_published_snapshot_not_live_review \
  tests.test_review_page_logic.DigestGuardTests.test_archive_lists_only_published_snapshots -v
```

Expected: `OK`, all three pass.

- [ ] **Step 3: Run the complete test suite**

Run:

```bash
python3 -m unittest discover -s tests -v
```

Expected: all tests pass with no errors or failures.

- [ ] **Step 4: Inspect the complete diff**

Run:

```bash
git diff --check
git status --short
git diff -- app/services/static_export.py app/main.py templates/digest.html templates/review.html tests/test_review_page_logic.py
```

Expected: no whitespace errors; only intentional feature files are modified.
Do not stage the pre-existing `cloudflare-proxy/`, `output/`, or `tmp/`
directories.

- [ ] **Step 5: Commit final integration coverage**

```bash
git add tests/test_review_page_logic.py
git commit -m "Test repeatable digest ZIP exports"
```

- [ ] **Step 6: Manually inspect one generated archive**

Use the test fixture or local application to generate a ZIP, extract it into a
temporary directory, serve that directory with a simple static HTTP server, and
open `index.html`. Verify:

- the logo and both Onest font files load locally;
- images and videos load without requests to Railway;
- the page contains no review, preview, or publication controls;
- table-of-contents links work;
- the page remains usable at mobile width.

Record any visual defect as a failing regression test before changing code.
