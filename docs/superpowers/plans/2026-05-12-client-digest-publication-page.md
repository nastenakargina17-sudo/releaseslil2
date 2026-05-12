# Client Digest Publication Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `/digest/{release_id}` into a read-only client digest page that publishes only approved review output.

**Architecture:** Keep the review workflow and storage model unchanged. Add small presentation helpers in `app/review_utils.py`, adjust `app/main.py` to pass publication groups and labels to the template, and replace `templates/digest.html` with a polished read-only publication view. Tests stay in `tests/test_review_page_logic.py` because that file already owns digest route behavior.

**Tech Stack:** Python, FastAPI, Jinja2 templates, SQLite-backed storage, unittest, FastAPI `TestClient`.

---

## File Structure

- Modify `app/review_utils.py`
  - Add client-facing labels for digest sections and value categories.
  - Add a helper that detects video media paths for the template.

- Modify `app/main.py`
  - Keep existing readiness checks.
  - Filter publication data to approved items.
  - Build open product sections for `new_feature` and `change`.
  - Build one collapsed support section from `bugfix` and `technical_improvement`.
  - Pass labels and media helper to the template.

- Replace `templates/digest.html`
  - Render the read-only public page.
  - Hide empty sections.
  - Render value category badges with human-readable labels.
  - Hide Tracker links for `new_feature` and `change`.
  - Render one collapsed support section with Tracker links for bugfix and technical items.
  - Render a large media gallery for product items.

- Modify `tests/test_review_page_logic.py`
  - Extend existing digest tests to cover publication filtering, labels, collapsed support section, and Tracker-link rules.

---

### Task 1: Add Publication Labels And Media Helper

**Files:**
- Modify: `app/review_utils.py`
- Test: `tests/test_review_page_logic.py`

- [ ] **Step 1: Write failing helper tests**

Add these tests to `ReviewPageLogicTests` in `tests/test_review_page_logic.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_review_page_logic.py::ReviewPageLogicTests::test_client_value_category_labels_are_human_readable tests/test_review_page_logic.py::ReviewPageLogicTests::test_digest_media_helper_detects_video_paths -v
```

Expected: fail with import errors for `CLIENT_CATEGORY_LABELS` and `is_video_media_path`.

- [ ] **Step 3: Implement labels and helper**

In `app/review_utils.py`, add this after `CATEGORY_LABELS`:

```python
CLIENT_CATEGORY_LABELS = {
    ValueCategory.TIME_SAVING: "Экономия времени",
    ValueCategory.ERROR_REDUCTION: "Меньше ошибок",
    ValueCategory.CLARITY_TRANSPARENCY: "Больше прозрачности",
    ValueCategory.DAILY_WORK_CONVENIENCE: "Удобнее в ежедневной работе",
    ValueCategory.BETTER_CONTROL: "Больше контроля",
    ValueCategory.LESS_COMMUNICATION_OVERHEAD: "Меньше ручных согласований",
}
```

Add this helper near the other utility functions:

```python
def is_video_media_path(path: str) -> bool:
    return (path or "").lower().split("?", 1)[0].endswith((".mp4", ".webm"))
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest tests/test_review_page_logic.py::ReviewPageLogicTests::test_client_value_category_labels_are_human_readable tests/test_review_page_logic.py::ReviewPageLogicTests::test_digest_media_helper_detects_video_paths -v
```

Expected: both tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/review_utils.py tests/test_review_page_logic.py
git commit -m "Add client digest presentation labels"
```

---

### Task 2: Build Publication Context For The Digest Route

**Files:**
- Modify: `app/main.py`
- Modify: `tests/test_review_page_logic.py`

- [ ] **Step 1: Write failing route test for approved-only publication groups**

Add this test to `DigestGuardTests`:

```python
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
```

Also update the imports at the top of `tests/test_review_page_logic.py` to include `ValueCategory`:

```python
from app.models import DigestItem, DigestRelease, GroupingMode, ItemStatus, ItemType, SourceItem, SummaryStatus, ValueCategory
```

- [ ] **Step 2: Run test to verify current behavior fails on the new publication contract**

Run:

```bash
pytest tests/test_review_page_logic.py::DigestGuardTests::test_digest_publishes_only_approved_items_in_public_sections -v
```

Expected: fail because the current template does not render the combined "Исправления и технические улучшения" section.

- [ ] **Step 3: Update imports in `app/main.py`**

Change the `app.review_utils` import to include the new names:

```python
from app.review_utils import (
    CATEGORY_LABELS,
    CLIENT_CATEGORY_LABELS,
    DESCRIPTIONLESS_ITEM_TYPES,
    ITEM_TYPE_LABELS,
    STATUS_LABELS,
    default_item_category,
    digest_blockers,
    is_video_media_path,
)
```

- [ ] **Step 4: Replace digest grouping in `final_digest`**

Replace the grouping block in `final_digest` with:

```python
    approved_items = [
        item for item in all_items
        if item.status == ItemStatus.APPROVED and item.type != ItemType.RELEASE_CANDIDATE
    ]

    new_features = [item for item in approved_items if item.type == ItemType.NEW_FEATURE]
    changes = [item for item in approved_items if item.type == ItemType.CHANGE]
    support_items = [
        item for item in approved_items
        if item.type in {ItemType.BUGFIX, ItemType.TECHNICAL_IMPROVEMENT}
    ]

    return templates.TemplateResponse(
        request,
        "digest.html",
        {
            "release": release,
            "new_features": new_features,
            "changes": changes,
            "support_items": support_items,
            "category_labels": CLIENT_CATEGORY_LABELS,
            "item_type_labels": ITEM_TYPE_LABELS,
            "is_video_media_path": is_video_media_path,
        },
    )
```

Remove the now-unused `grouped_bugfixes` and `grouped_technical` variables from this route.

- [ ] **Step 5: Run test**

Run:

```bash
pytest tests/test_review_page_logic.py::DigestGuardTests::test_digest_publishes_only_approved_items_in_public_sections -v
```

Expected: still fail until the template renders `support_items`.

- [ ] **Step 6: Commit route context only if tests fail for template-only reasons**

```bash
git add app/main.py tests/test_review_page_logic.py
git commit -m "Prepare client digest publication context"
```

---

### Task 3: Replace The Digest Template With A Read-Only Publication Page

**Files:**
- Replace: `templates/digest.html`
- Test: `tests/test_review_page_logic.py`

- [ ] **Step 1: Write failing display tests**

Add these tests to `DigestGuardTests`:

```python
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
```

- [ ] **Step 2: Run display tests to verify they fail**

Run:

```bash
pytest tests/test_review_page_logic.py::DigestGuardTests::test_digest_hides_tracker_links_for_product_items_but_shows_support_links tests/test_review_page_logic.py::DigestGuardTests::test_digest_renders_value_badge_and_paid_feature_badge tests/test_review_page_logic.py::DigestGuardTests::test_digest_support_section_is_collapsed_by_default -v
```

Expected: fail because the current template shows product Tracker links only indirectly for bugfixes, uses older labels, and has no collapsed support section.

- [ ] **Step 3: Replace `templates/digest.html`**

Use this complete template:

```html
<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Дайджест релиза {{ release.id }}</title>
  <style>
    :root {
      color-scheme: light;
      --ink: #18212f;
      --muted: #667085;
      --line: #d9e2ec;
      --panel: #ffffff;
      --soft: #f5f7fb;
      --accent: #0f766e;
      --accent-soft: #dff7f3;
      --paid: #7c3aed;
      --paid-soft: #eee7ff;
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      font-family: Arial, sans-serif;
      color: var(--ink);
      background: #f3f6fa;
      line-height: 1.55;
    }

    .page {
      max-width: 1080px;
      margin: 0 auto;
      padding: 40px 20px 56px;
    }

    .hero {
      padding: 36px 0 28px;
      border-bottom: 1px solid var(--line);
    }

    .eyebrow {
      margin: 0 0 10px;
      color: var(--muted);
      font-size: 14px;
    }

    h1 {
      margin: 0;
      font-size: 40px;
      line-height: 1.15;
      letter-spacing: 0;
    }

    .summary {
      max-width: 820px;
      margin: 20px 0 0;
      font-size: 18px;
      color: #344054;
    }

    .section {
      margin-top: 38px;
    }

    .section h2 {
      margin: 0 0 18px;
      font-size: 26px;
      letter-spacing: 0;
    }

    .item-grid {
      display: grid;
      gap: 18px;
    }

    .digest-card {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 22px;
    }

    .card-topline {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
      margin-bottom: 12px;
    }

    .module {
      color: var(--muted);
      font-size: 14px;
    }

    .badge {
      display: inline-flex;
      align-items: center;
      min-height: 26px;
      padding: 4px 10px;
      border-radius: 999px;
      font-size: 13px;
      font-weight: 700;
      background: var(--accent-soft);
      color: #0b5f59;
    }

    .badge-paid {
      background: var(--paid-soft);
      color: var(--paid);
    }

    .digest-card h3 {
      margin: 0 0 10px;
      font-size: 22px;
      line-height: 1.25;
      letter-spacing: 0;
    }

    .digest-card p {
      margin: 0;
      color: #344054;
    }

    .media-gallery {
      display: grid;
      gap: 12px;
      margin-top: 18px;
    }

    .media-primary img,
    .media-primary video,
    .media-secondary img,
    .media-secondary video {
      display: block;
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--soft);
    }

    .media-primary img,
    .media-primary video {
      max-height: 560px;
      object-fit: contain;
    }

    .media-secondary {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
    }

    .media-secondary img,
    .media-secondary video {
      aspect-ratio: 16 / 9;
      object-fit: cover;
    }

    details.support {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 0;
    }

    details.support summary {
      cursor: pointer;
      padding: 18px 22px;
      font-size: 20px;
      font-weight: 700;
      list-style-position: inside;
    }

    .support-list {
      display: grid;
      gap: 0;
      border-top: 1px solid var(--line);
    }

    .support-item {
      display: grid;
      grid-template-columns: minmax(120px, 180px) 1fr auto;
      gap: 14px;
      align-items: center;
      padding: 14px 22px;
      border-top: 1px solid #edf1f5;
    }

    .support-item:first-child {
      border-top: 0;
    }

    .support-title {
      font-weight: 700;
    }

    a {
      color: #0f5f89;
      text-decoration: none;
      font-weight: 700;
    }

    a:hover {
      text-decoration: underline;
    }

    @media (max-width: 700px) {
      .page {
        padding: 28px 14px 42px;
      }

      h1 {
        font-size: 32px;
      }

      .summary {
        font-size: 16px;
      }

      .digest-card {
        padding: 18px;
      }

      .support-item {
        grid-template-columns: 1fr;
        gap: 6px;
      }
    }
  </style>
</head>
<body>
  <main class="page">
    <header class="hero">
      <p class="eyebrow">Дата релиза: <strong>{{ release.release_date }}</strong></p>
      <h1>Дайджест релиза</h1>
      <p class="summary">{{ release.summary }}</p>
    </header>

    {% if new_features %}
      <section class="section" aria-labelledby="new-features-heading">
        <h2 id="new-features-heading">Что нового</h2>
        <div class="item-grid">
          {% for item in new_features %}
            {% include "digest_item_card.html" %}
          {% endfor %}
        </div>
      </section>
    {% endif %}

    {% if changes %}
      <section class="section" aria-labelledby="changes-heading">
        <h2 id="changes-heading">Что стало удобнее</h2>
        <div class="item-grid">
          {% for item in changes %}
            {% include "digest_item_card.html" %}
          {% endfor %}
        </div>
      </section>
    {% endif %}

    {% if support_items %}
      <section class="section" aria-labelledby="support-heading">
        <details class="support">
          <summary id="support-heading">Исправления и технические улучшения</summary>
          <div class="support-list">
            {% for item in support_items %}
              <div class="support-item">
                <div class="module">{{ item.module }}</div>
                <div>
                  <div class="support-title">{{ item.title }}</div>
                  {% if item.category %}
                    <span class="badge">{{ category_labels[item.category] }}</span>
                  {% endif %}
                </div>
                {% if item.tracker_urls %}
                  <a href="{{ item.tracker_urls[0] }}">Задача в трекере</a>
                {% endif %}
              </div>
            {% endfor %}
          </div>
        </details>
      </section>
    {% endif %}
  </main>
</body>
</html>
```

- [ ] **Step 4: Create `templates/digest_item_card.html` partial**

Create this new partial to keep the main template readable:

```html
<article class="digest-card">
  <div class="card-topline">
    <span class="module">{{ item.module }}</span>
    {% if item.category %}
      <span class="badge">{{ category_labels[item.category] }}</span>
    {% endif %}
    {% if item.is_paid_feature %}
      <span class="badge badge-paid">Платная функция</span>
    {% endif %}
  </div>
  <h3>{{ item.title }}</h3>
  {% if item.description %}
    <p>{{ item.description }}</p>
  {% endif %}

  {% if item.image_paths %}
    <div class="media-gallery">
      <div class="media-primary">
        {% set primary_media = item.image_paths[0] %}
        {% if is_video_media_path(primary_media) %}
          <video src="{{ primary_media }}" controls preload="metadata"></video>
        {% else %}
          <img src="{{ primary_media }}" alt="Иллюстрация к пункту {{ item.title }}">
        {% endif %}
      </div>
      {% if item.image_paths|length > 1 %}
        <div class="media-secondary">
          {% for media_path in item.image_paths[1:] %}
            {% if is_video_media_path(media_path) %}
              <video src="{{ media_path }}" controls preload="metadata"></video>
            {% else %}
              <img src="{{ media_path }}" alt="Дополнительная иллюстрация к пункту {{ item.title }}">
            {% endif %}
          {% endfor %}
        </div>
      {% endif %}
    </div>
  {% endif %}
</article>
```

- [ ] **Step 5: Run display tests**

Run:

```bash
pytest tests/test_review_page_logic.py::DigestGuardTests::test_digest_publishes_only_approved_items_in_public_sections tests/test_review_page_logic.py::DigestGuardTests::test_digest_hides_tracker_links_for_product_items_but_shows_support_links tests/test_review_page_logic.py::DigestGuardTests::test_digest_renders_value_badge_and_paid_feature_badge tests/test_review_page_logic.py::DigestGuardTests::test_digest_support_section_is_collapsed_by_default -v
```

Expected: all listed tests pass.

- [ ] **Step 6: Commit**

```bash
git add templates/digest.html templates/digest_item_card.html tests/test_review_page_logic.py
git commit -m "Build read-only client digest page"
```

---

### Task 4: Final Guardrails And Regression Test Pass

**Files:**
- Modify: `tests/test_review_page_logic.py`
- Modify if the regression test fails: `templates/digest.html`

- [ ] **Step 1: Add no-empty-placeholder regression test**

Add this test to `DigestGuardTests`:

```python
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
```

- [ ] **Step 2: Run the new regression test**

Run:

```bash
pytest tests/test_review_page_logic.py::DigestGuardTests::test_digest_omits_empty_publication_sections -v
```

Expected: pass if Task 3 template hides empty sections. If it fails, remove placeholder copy and wrap product sections in `{% if new_features %}` and `{% if changes %}` blocks exactly as shown in Task 3.

- [ ] **Step 3: Run digest-related tests**

Run:

```bash
pytest tests/test_review_page_logic.py::DigestGuardTests -v
```

Expected: all `DigestGuardTests` pass.

- [ ] **Step 4: Run the focused full test file**

Run:

```bash
pytest tests/test_review_page_logic.py -v
```

Expected: all tests in the file pass.

- [ ] **Step 5: Commit final test coverage**

```bash
git add tests/test_review_page_logic.py templates/digest.html templates/digest_item_card.html
git commit -m "Cover client digest publication rules"
```

---

## Self-Review Notes

- Spec coverage: approved-only publishing, approved summary gate, hidden empty sections, collapsed support section, value category labels, Tracker-link rules, and media gallery all map to tasks above.
- Scope: the plan does not add a persisted publication model, change import, change AI generation, or alter review actions.
- Type consistency: all snippets use existing `DigestRelease`, `DigestItem`, `ItemStatus`, `ItemType`, `SummaryStatus`, `ValueCategory`, and `GroupingMode` names from `app.models`.
