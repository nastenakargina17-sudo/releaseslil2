# Deep Brand Digest Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refresh the digest preview/public/archive pages into a darker branded release report, add release counters, preserve uploaded image quality, and replace the digest logo.

**Architecture:** Keep the existing FastAPI/Jinja flow. Extend `app/services/publication.py` so live preview and published snapshots share richer metrics and section metadata. Update Jinja templates and review upload JavaScript without adding frontend dependencies.

**Tech Stack:** Python, FastAPI, Jinja2, SQLite storage, vanilla HTML/CSS/JavaScript, `unittest`.

---

## File Structure

- Modify `app/services/publication.py`: section titles, section counts, release metrics, module icon key helper.
- Modify `templates/digest.html`: dark branded layout, hero metrics block, report tabs, support section styling.
- Modify `templates/digest_item_card.html`: richer cards, module icon, premium paid label, media framing.
- Modify `templates/digests.html`: use the new PNG logo and darker archive shell.
- Modify `templates/review.html`: remove client-side image recompression from upload flow.
- Add `static/brand/Logo_Skillaz_Black.png`: supplied logo copied from the user-provided local file.
- Modify `tests/test_review_page_logic.py`: cover metrics counts, renamed support section, premium/module markup, and no JS recompression.

## Task 1: Publication Metrics And Section Metadata

**Files:**
- Modify: `app/services/publication.py`
- Test: `tests/test_review_page_logic.py`

- [ ] **Step 1: Write failing tests for metrics and renamed support section**

Add these tests to `DigestGuardTests` in `tests/test_review_page_logic.py`:

```python
    def test_live_digest_metrics_count_release_categories(self) -> None:
        from app.services.publication import build_live_digest_content

        items = [
            DigestItem(id="feature", release_id="2026-04", title="Feature", description="Feature text", module="Подбор", type=ItemType.NEW_FEATURE, status=ItemStatus.APPROVED),
            DigestItem(id="change", release_id="2026-04", title="Change", description="Change text", module="Интеграции", type=ItemType.CHANGE, status=ItemStatus.APPROVED),
            DigestItem(id="tech", release_id="2026-04", title="Tech", description="", module="Платформа", type=ItemType.TECHNICAL_IMPROVEMENT, status=ItemStatus.APPROVED),
            DigestItem(id="bug", release_id="2026-04", title="Bug", description="", module="Ядро", type=ItemType.BUGFIX, status=ItemStatus.APPROVED),
            DigestItem(id="draft", release_id="2026-04", title="Draft", description="", module="Ядро", type=ItemType.NEW_FEATURE, status=ItemStatus.DRAFT),
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
            title="Integration",
            description="Integration text",
            module="Интеграции",
            type=ItemType.NEW_FEATURE,
            status=ItemStatus.APPROVED,
        )

        content = build_live_digest_content([item])
        first_item = content["sections"][0]["items"][0]

        self.assertEqual(first_item["module_icon"], "integrations")
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
/Users/user/Downloads/релиз\ ноутс2/.venv/bin/python -m unittest tests.test_review_page_logic.DigestGuardTests.test_live_digest_metrics_count_release_categories tests.test_review_page_logic.DigestGuardTests.test_item_payload_includes_module_icon_key
```

Expected: failure because `new_features_count`, `changes_count`, `technical_count`, `items_count` on sections, and `module_icon` are not implemented.

- [ ] **Step 3: Implement publication metrics and module icon keys**

In `app/services/publication.py`, update `build_live_digest_content`, `_section`, `_item_payload`, and add `_module_icon_key`:

```python
def build_live_digest_content(items: Iterable[DigestItem]) -> dict:
    approved_items = [
        item for item in items
        if item.status == ItemStatus.APPROVED and item.type != ItemType.RELEASE_CANDIDATE
    ]
    new_feature_items = [item for item in approved_items if item.type == ItemType.NEW_FEATURE]
    change_items = [item for item in approved_items if item.type == ItemType.CHANGE]
    support_items = [
        item for item in approved_items
        if item.type in {ItemType.BUGFIX, ItemType.TECHNICAL_IMPROVEMENT}
    ]
    sections = [
        _section("new_features", "Что нового", new_feature_items, include_tracker=False),
        _section("changes", "Что стало удобнее", change_items, include_tracker=False),
        _section(
            "support",
            "Стабильность и техническая база",
            support_items,
            include_tracker=True,
            collapsed=True,
        ),
    ]
    visible_sections = [section for section in sections if section["items"]]
    return {
        "sections": visible_sections,
        "metrics": {
            "items_count": len(approved_items),
            "new_features_count": len(new_feature_items),
            "changes_count": len(change_items),
            "technical_count": len(support_items),
            "product_items_count": len(new_feature_items) + len(change_items),
        },
    }


def _section(section_id: str, title: str, items: list[DigestItem], include_tracker: bool, collapsed: bool = False) -> dict:
    return {
        "id": section_id,
        "title": title,
        "collapsed": collapsed,
        "items_count": len(items),
        "items": [_item_payload(item, include_tracker) for item in items],
    }


def _item_payload(item: DigestItem, include_tracker: bool) -> dict:
    payload = {
        "title": item.title,
        "description": item.description,
        "module": item.module,
        "module_icon": _module_icon_key(item.module),
        "type": item.type.value,
        "value_category": item.category.value if item.category else "",
        "value_category_label": CLIENT_CATEGORY_LABELS.get(item.category, "") if item.category else "",
        "is_paid_feature": item.is_paid_feature,
        "media": [_media_payload(path) for path in item.image_paths],
    }
    if include_tracker:
        payload["tracker_urls"] = list(item.tracker_urls)
    return payload


def _module_icon_key(module: str) -> str:
    normalized = module.strip().lower()
    if any(token in normalized for token in ("интеграц", "api", "маркетплейс", "marketplace")):
        return "integrations"
    if any(token in normalized for token in ("подбор", "кандидат", "воронк")):
        return "hiring"
    if any(token in normalized for token in ("аналит", "отчет", "дашборд", "метрик")):
        return "analytics"
    if any(token in normalized for token in ("настрой", "админ", "конфиг")):
        return "settings"
    if any(token in normalized for token in ("коммуникац", "уведом", "telegram", "почт")):
        return "communications"
    if any(token in normalized for token in ("ядро", "платформ", "core")):
        return "platform"
    return "module"
```

- [ ] **Step 4: Run targeted tests**

Run the same command from Step 2.

Expected: both tests pass.

- [ ] **Step 5: Commit metrics changes**

```bash
git add app/services/publication.py tests/test_review_page_logic.py
git commit -m "Add digest report metrics"
```

## Task 2: Logo Asset And Digest Layout

**Files:**
- Add: `static/brand/Logo_Skillaz_Black.png`
- Modify: `templates/digest.html`
- Modify: `templates/digest_item_card.html`
- Modify: `templates/digests.html`
- Test: `tests/test_review_page_logic.py`

- [ ] **Step 1: Copy supplied logo into static assets**

Run:

```bash
cp "/Users/user/Desktop/Подбор/Logo_Skillaz 2/Logo_Skillaz/RGB/PNG/Logo_Skillaz_Black.png" static/brand/Logo_Skillaz_Black.png
```

Expected: `static/brand/Logo_Skillaz_Black.png` exists.

- [ ] **Step 2: Write failing markup tests**

Add this test to `DigestGuardTests`:

```python
    def test_digest_uses_deep_brand_report_markup(self) -> None:
        self.storage.update_release_publication_status("2026-04", PublicationStatus.PREVIEW)
        item = DigestItem(
            id="feature-paid",
            release_id="2026-04",
            title="Paid feature",
            description="Paid feature text",
            module="Интеграции",
            type=ItemType.NEW_FEATURE,
            category=ValueCategory.REVENUE,
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
```

- [ ] **Step 3: Run test and verify it fails**

Run:

```bash
/Users/user/Downloads/релиз\ ноутс2/.venv/bin/python -m unittest tests.test_review_page_logic.DigestGuardTests.test_digest_uses_deep_brand_report_markup
```

Expected: failure because the template still references the SVG and old markup.

- [ ] **Step 4: Replace digest page shell and styles**

Update `templates/digest.html` to use:

```jinja2
<img class="brand-logo" src="/static/brand/Logo_Skillaz_Black.png" alt="Skillaz">
```

Add a hero metrics block in the non-preparation branch:

```jinja2
<aside class="metrics-panel" aria-label="Итоги релиза">
  <p class="panel-kicker">Итоги релиза</p>
  <div class="metrics-grid">
    <div class="metric-card"><strong>{{ metrics.items_count or 0 }}</strong><span>Всего изменений</span></div>
    <div class="metric-card"><strong>{{ metrics.new_features_count or 0 }}</strong><span>Новые функции</span></div>
    <div class="metric-card"><strong>{{ metrics.changes_count or 0 }}</strong><span>Улучшения</span></div>
    <div class="metric-card"><strong>{{ metrics.technical_count or 0 }}</strong><span>Техническая база</span></div>
  </div>
</aside>
```

Use a `.hero-layout` grid with `.hero-content` and `.metrics-panel`. Add dark gradient page styles, report tab styles for `.toc`, support-specific section styles via `.section-support`, and keep mobile media queries.

- [ ] **Step 5: Replace digest card markup**

Update `templates/digest_item_card.html` to include:

```jinja2
<article class="card card-{{ section.id if section else 'default' }}">
  <div class="card-meta">
    <span class="module-chip">
      <span class="module-icon module-icon-{{ item.module_icon or 'module' }}" aria-hidden="true"></span>
      {{ item.module }}
    </span>
    {% if item.value_category_label %}
      <span class="value-badge">{{ item.value_category_label }}</span>
    {% endif %}
    {% if item.is_paid_feature %}
      <span class="premium-badge">Платная функция</span>
    {% endif %}
  </div>
  <h3>{{ item.title }}</h3>
  {% if item.description %}
    <p class="card-description">{{ item.description }}</p>
  {% endif %}
  {% if item.tracker_urls %}
    <p class="tracker-link"><a href="{{ item.tracker_urls[0] }}">Задача в трекере</a></p>
  {% endif %}
  ...existing media rendering...
</article>
```

Keep the existing media carousel logic, but wrap images/videos in the richer media styles.

- [ ] **Step 6: Update archive logo and shell**

In `templates/digests.html`, replace the logo reference with `/static/brand/Logo_Skillaz_Black.png` and align the archive background/card colors with the digest page shell.

- [ ] **Step 7: Run markup test**

Run:

```bash
/Users/user/Downloads/релиз\ ноутс2/.venv/bin/python -m unittest tests.test_review_page_logic.DigestGuardTests.test_digest_uses_deep_brand_report_markup
```

Expected: pass.

- [ ] **Step 8: Commit visual template changes**

```bash
git add static/brand/Logo_Skillaz_Black.png templates/digest.html templates/digest_item_card.html templates/digests.html tests/test_review_page_logic.py
git commit -m "Refresh digest brand report UI"
```

## Task 3: Preserve Upload Image Quality

**Files:**
- Modify: `templates/review.html`
- Test: `tests/test_review_page_logic.py`

- [ ] **Step 1: Write failing test for no client-side recompression**

Add this test to `DigestGuardTests`:

```python
    def test_review_upload_javascript_preserves_original_images(self) -> None:
        response = self.client.get("/review/2026-04")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("canvas.toBlob", response.text)
        self.assertNotIn("image/webp\", 0.82", response.text)
        self.assertNotIn("convertImageToWebp", response.text)
        self.assertIn("return file;", response.text)
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
/Users/user/Downloads/релиз\ ноутс2/.venv/bin/python -m unittest tests.test_review_page_logic.DigestGuardTests.test_review_upload_javascript_preserves_original_images
```

Expected: failure because the current template contains `convertImageToWebp` and `canvas.toBlob`.

- [ ] **Step 3: Remove recompression from review upload JavaScript**

In `templates/review.html`, delete the `convertImageToWebp` function and replace `prepareUploadFile` with:

```javascript
      const prepareUploadFile = async (file) => {
        validateMediaFile(file);
        return file;
      };
```

Keep `validateMediaFile` unchanged so current size/type limits remain enforced before upload.

- [ ] **Step 4: Run upload quality test**

Run the same command from Step 2.

Expected: pass.

- [ ] **Step 5: Run upload behavior tests**

Run:

```bash
/Users/user/Downloads/релиз\ ноутс2/.venv/bin/python -m unittest tests.test_review_page_logic.DigestGuardTests.test_upload_validates_media_type_and_size tests.test_review_page_logic.DigestGuardTests.test_uploaded_media_can_be_deleted
```

Expected: pass.

- [ ] **Step 6: Commit upload quality fix**

```bash
git add templates/review.html tests/test_review_page_logic.py
git commit -m "Preserve digest upload image quality"
```

## Task 4: Full Verification And Browser Review

**Files:**
- Verify all modified files.

- [ ] **Step 1: Run full unit suite**

Run:

```bash
/Users/user/Downloads/релиз\ ноутс2/.venv/bin/python -m unittest discover -s tests
```

Expected: all tests pass.

- [ ] **Step 2: Start local server**

Run:

```bash
/Users/user/Downloads/релиз\ ноутс2/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Expected: server starts at `http://127.0.0.1:8000`.

- [ ] **Step 3: Browser-check digest routes**

Open and visually inspect:

```text
http://127.0.0.1:8000/digests
http://127.0.0.1:8000/digest/2026-04
```

If local data has no published release, create mock data through `/releases/bootstrap`, prepare preview through the review flow, or verify the preparation state and archive styling.

Expected:

- logo renders from `Logo_Skillaz_Black.png`;
- dark gradient background is visible;
- header metrics are visible and responsive;
- cards have richer contrast;
- paid feature label is visually distinct when present;
- support section appears at the end as "Стабильность и техническая база";
- media is not visibly blurred by CSS stretching.

- [ ] **Step 4: Stop local server**

Stop the uvicorn process with `Ctrl+C`.

- [ ] **Step 5: Final git status**

Run:

```bash
git status -sb
```

Expected: clean working tree.

## Self-Review

- Spec coverage: logo, metrics, richer cards, paid label, module icons, darker background, support section, and upload quality are covered.
- Completeness scan: no unresolved markers are present.
- Type consistency: metrics names are `items_count`, `new_features_count`, `changes_count`, `technical_count`, and `product_items_count`; templates use those same keys.
