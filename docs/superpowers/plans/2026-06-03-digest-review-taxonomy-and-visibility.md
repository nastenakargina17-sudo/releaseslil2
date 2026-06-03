# Digest Review Taxonomy And Visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add separate change-type and digest-visibility fields so review, Tracker import, and digest publication use the same taxonomy.

**Architecture:** Keep the existing `ItemType` enum as the change-type field to minimize schema churn, replacing the old broad `CHANGE` meaning with new explicit values. Add a new `DigestVisibility` enum and `digest_visibility` field on `DigestItem`; use it as the publication gate while preserving current review-card shape. Extend import, storage, review updates, and publication in small layers with regression tests around every behavioral boundary.

**Tech Stack:** FastAPI, Jinja2 templates, SQLite storage, dataclasses/enums, pytest/unittest with FastAPI TestClient.

---

## File Structure

- Modify `app/models.py`: add `DigestVisibility`; expand `ItemType` with `PRODUCT_IMPROVEMENT`, `CLIENT_CUSTOMIZATION`, and `INTERNAL_CHANGE`; keep stored string values explicit.
- Modify `app/review_utils.py`: update labels, descriptionless rules, default category, default visibility helper, and digest blockers if needed.
- Modify `app/storage.py`: migrate `digest_items.digest_visibility`, hydrate/persist it, update item save paths, split paths, and bulk operations where relevant.
- Modify `app/clients/tracker.py`: map Tracker issues to the new change types and initial visibility.
- Modify `app/services/ingest.py`: carry source visibility into digest items, preserve grouping behavior, generate descriptions for all non-descriptionless change types.
- Modify `app/services/importers.py`: preserve manual change type and visibility for unchanged reviewed items.
- Modify `app/main.py`: pass new enum/labels to templates; accept `item_type` for all primary change types; accept `digest_visibility` in review item updates.
- Modify `templates/review.html`: show filters for change type and visibility; show both controls on cards; keep all existing fields visible according to current type-based rules only.
- Modify `app/services/publication.py`: build public digest from `digest_visibility == PUBLIC`, with client-friendly section grouping.
- Modify `app/notifications/telegram.py`: update release status counts and labels to the new taxonomy.
- Modify tests in `tests/test_review_page_logic.py`, `tests/test_importer_copy_preservation.py`, and `tests/test_ingest_ai_generation.py`.

---

### Task 1: Model, Labels, And Description Rules

**Files:**
- Modify: `app/models.py`
- Modify: `app/review_utils.py`
- Test: `tests/test_review_page_logic.py`

- [ ] **Step 1: Write failing tests for labels, defaults, and description rules**

Add these tests near `ReviewPageLogicTests.test_client_value_category_labels_are_human_readable`:

```python
def test_change_type_labels_are_human_readable(self) -> None:
    from app.models import ItemType
    from app.review_utils import ITEM_TYPE_LABELS

    self.assertEqual(ITEM_TYPE_LABELS[ItemType.NEW_FEATURE], "Новый функционал")
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
    self.assertEqual(default_digest_visibility(ItemType.PRODUCT_IMPROVEMENT), DigestVisibility.PUBLIC)
    self.assertEqual(default_digest_visibility(ItemType.CLIENT_CUSTOMIZATION), DigestVisibility.INTERNAL)
    self.assertEqual(default_digest_visibility(ItemType.INTERNAL_CHANGE), DigestVisibility.INTERNAL)
    self.assertEqual(default_digest_visibility(ItemType.TECHNICAL_IMPROVEMENT), DigestVisibility.INTERNAL)
    self.assertEqual(default_digest_visibility(ItemType.BUGFIX), DigestVisibility.INTERNAL)

def test_description_generation_rules_follow_change_type_only(self) -> None:
    from app.models import ItemType
    from app.review_utils import should_collect_description

    self.assertTrue(should_collect_description(ItemType.NEW_FEATURE))
    self.assertTrue(should_collect_description(ItemType.PRODUCT_IMPROVEMENT))
    self.assertTrue(should_collect_description(ItemType.CLIENT_CUSTOMIZATION))
    self.assertTrue(should_collect_description(ItemType.INTERNAL_CHANGE))
    self.assertFalse(should_collect_description(ItemType.TECHNICAL_IMPROVEMENT))
    self.assertFalse(should_collect_description(ItemType.BUGFIX))
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `pytest tests/test_review_page_logic.py::ReviewPageLogicTests::test_change_type_labels_are_human_readable tests/test_review_page_logic.py::ReviewPageLogicTests::test_visibility_labels_and_defaults_are_human_readable tests/test_review_page_logic.py::ReviewPageLogicTests::test_description_generation_rules_follow_change_type_only -v`

Expected: FAIL because `DigestVisibility` and the new `ItemType` values do not exist yet.

- [ ] **Step 3: Add model enum values and review helpers**

In `app/models.py`, update `ItemType` and add `DigestVisibility`:

```python
class ItemType(str, Enum):
    NEW_FEATURE = "new_feature"
    PRODUCT_IMPROVEMENT = "product_improvement"
    CLIENT_CUSTOMIZATION = "client_customization"
    INTERNAL_CHANGE = "internal_change"
    BUGFIX = "bugfix"
    TECHNICAL_IMPROVEMENT = "technical_improvement"
    RELEASE_CANDIDATE = "release_candidate"


class DigestVisibility(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
```

Add `digest_visibility` to `DigestItem` after `type`:

```python
    digest_visibility: DigestVisibility = DigestVisibility.INTERNAL
```

Import `DigestVisibility` in `app/review_utils.py`, then replace the label/default blocks with:

```python
DIGEST_VISIBILITY_LABELS = {
    DigestVisibility.PUBLIC: "Публичный дайджест",
    DigestVisibility.INTERNAL: "Внутренний обзор",
}

ITEM_TYPE_LABELS = {
    ItemType.NEW_FEATURE: "Новый функционал",
    ItemType.PRODUCT_IMPROVEMENT: "Продуктовое улучшение",
    ItemType.CLIENT_CUSTOMIZATION: "Клиентская доработка",
    ItemType.INTERNAL_CHANGE: "Внутреннее изменение",
    ItemType.BUGFIX: "Исправление",
    ItemType.TECHNICAL_IMPROVEMENT: "Техническая итерация",
    ItemType.RELEASE_CANDIDATE: "Задачи из \"Нет\"",
}

DESCRIPTIONLESS_ITEM_TYPES = {
    ItemType.BUGFIX,
    ItemType.TECHNICAL_IMPROVEMENT,
    ItemType.RELEASE_CANDIDATE,
}

def default_digest_visibility(item_type: ItemType) -> DigestVisibility:
    if item_type in {ItemType.NEW_FEATURE, ItemType.PRODUCT_IMPROVEMENT}:
        return DigestVisibility.PUBLIC
    return DigestVisibility.INTERNAL

def default_item_category(item_type: ItemType) -> Optional[ValueCategory]:
    if item_type == ItemType.NEW_FEATURE:
        return ValueCategory.DAILY_WORK_CONVENIENCE
    if item_type in {
        ItemType.PRODUCT_IMPROVEMENT,
        ItemType.CLIENT_CUSTOMIZATION,
        ItemType.INTERNAL_CHANGE,
    }:
        return ValueCategory.CLARITY_TRANSPARENCY
    return None
```

- [ ] **Step 4: Run the focused tests and verify they pass**

Run: `pytest tests/test_review_page_logic.py::ReviewPageLogicTests::test_change_type_labels_are_human_readable tests/test_review_page_logic.py::ReviewPageLogicTests::test_visibility_labels_and_defaults_are_human_readable tests/test_review_page_logic.py::ReviewPageLogicTests::test_description_generation_rules_follow_change_type_only -v`

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add app/models.py app/review_utils.py tests/test_review_page_logic.py
git commit -m "Add digest taxonomy model"
```

---

### Task 2: Storage Persistence And Review Updates

**Files:**
- Modify: `app/storage.py`
- Modify: `app/main.py`
- Test: `tests/test_review_page_logic.py`

- [ ] **Step 1: Write failing storage/update tests**

Add a storage round-trip test:

```python
def test_digest_item_visibility_round_trips_through_storage(self) -> None:
    from app.models import DigestItem, DigestVisibility, ItemStatus, ItemType
    from app.storage import list_items, replace_release_items, upsert_release
    from app.models import DigestRelease

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
            digest_visibility=DigestVisibility.INTERNAL,
            category=None,
            status=ItemStatus.DRAFT,
        )
    ])

    [item] = list_items("2026-04")
    self.assertEqual(item.digest_visibility, DigestVisibility.INTERNAL)
```

Add a review update test near existing item update tests:

```python
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
```

- [ ] **Step 2: Run focused tests and verify they fail**

Run: `pytest tests/test_review_page_logic.py::ReviewPageLogicTests::test_digest_item_visibility_round_trips_through_storage tests/test_review_page_logic.py::DigestGuardTests::test_review_item_can_update_type_and_visibility -v`

Expected: FAIL because storage and update paths do not persist `digest_visibility`.

- [ ] **Step 3: Implement storage migration and update path**

In `app/storage.py`, import `DigestVisibility`, add a column in `init_db()`:

```python
_ensure_column(conn, "digest_items", "digest_visibility", "TEXT NOT NULL DEFAULT 'internal'")
```

Include `digest_visibility` in all `INSERT` and `SELECT` statements for `digest_items`. In `_row_to_item`, set:

```python
digest_visibility=DigestVisibility(row["digest_visibility"]),
```

Update `update_item` signature and SQL:

```python
def update_item(
    item_id: str,
    title: str,
    description: str,
    category: Optional[str],
    status: str,
    is_paid_feature: bool,
    item_type: Optional[str] = None,
    digest_visibility: Optional[str] = None,
    expected_version: Optional[int] = None,
) -> None:
    ...
    SET title = ?, description = ?, category = ?, status = ?, is_paid_feature = ?,
        type = COALESCE(?, type),
        digest_visibility = COALESCE(?, digest_visibility),
        version = version + 1, updated_at = ?
```

When splitting epic items, pass through `digest_visibility=item.digest_visibility` and insert it.

In `app/main.py`, import `DigestVisibility`, add `digest_visibility: Optional[str] = Form(None)` to `update_review_item`, validate it:

```python
effective_visibility = item.digest_visibility
if digest_visibility in {visibility.value for visibility in DigestVisibility}:
    effective_visibility = DigestVisibility(digest_visibility)
```

Pass `digest_visibility=effective_visibility.value` to `update_item`, and include it in JSON:

```python
"digest_visibility": effective_visibility.value,
```

- [ ] **Step 4: Run focused tests and verify they pass**

Run: `pytest tests/test_review_page_logic.py::ReviewPageLogicTests::test_digest_item_visibility_round_trips_through_storage tests/test_review_page_logic.py::DigestGuardTests::test_review_item_can_update_type_and_visibility -v`

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add app/storage.py app/main.py tests/test_review_page_logic.py
git commit -m "Persist digest item visibility"
```

---

### Task 3: Tracker Mapping And Ingest Defaults

**Files:**
- Modify: `app/models.py`
- Modify: `app/clients/tracker.py`
- Modify: `app/services/ingest.py`
- Modify: `app/services/mock_data.py`
- Test: `tests/test_review_page_logic.py`
- Test: `tests/test_ingest_ai_generation.py`

- [ ] **Step 1: Write failing Tracker mapping tests**

Add tests near `test_story_with_no_release_description_becomes_release_candidate`:

```python
def test_tracker_maps_client_task_to_client_customization_public(self) -> None:
    from app.clients.tracker import _classify_tracker_item
    from app.models import DigestVisibility, ItemType

    result = _classify_tracker_item({
        "type": {"key": "story"},
        "tags": [],
        "inTheReleaseDescription": "Клиентский и внутренний",
        "project": {"primary": {"display": "Client Project"}},
        "components": [{"display": "Client Task"}],
    })

    self.assertEqual(result, (ItemType.CLIENT_CUSTOMIZATION, DigestVisibility.PUBLIC))

def test_tracker_maps_public_product_story_to_product_improvement(self) -> None:
    from app.clients.tracker import _classify_tracker_item
    from app.models import DigestVisibility, ItemType

    result = _classify_tracker_item({
        "type": {"key": "story"},
        "tags": [],
        "inTheReleaseDescription": "Клиентский и внутренний",
        "project": {"primary": {"display": "Other Project"}},
        "components": [{"display": "ATSCore"}],
    })

    self.assertEqual(result, (ItemType.PRODUCT_IMPROVEMENT, DigestVisibility.PUBLIC))
```

- [ ] **Step 2: Run the mapping tests and verify they fail**

Run: `pytest tests/test_review_page_logic.py::ReviewPageLogicTests::test_tracker_maps_client_task_to_client_customization_public tests/test_review_page_logic.py::ReviewPageLogicTests::test_tracker_maps_public_product_story_to_product_improvement -v`

Expected: FAIL because `_classify_tracker_item` does not exist.

- [ ] **Step 3: Implement Tracker classification tuple**

Add `digest_visibility` to `SourceItem` in `app/models.py`:

```python
    digest_visibility: DigestVisibility = DigestVisibility.INTERNAL
```

In `app/clients/tracker.py`, replace `_classify_item_type` with `_classify_tracker_item` returning `Optional[tuple[ItemType, DigestVisibility]]`:

```python
def _classify_tracker_item(item: dict[str, Any]) -> Optional[tuple[ItemType, DigestVisibility]]:
    raw_type = ((item.get("type") or {}).get("key") or "").strip()
    tags_set = {str(tag) for tag in (item.get("tags") or [])}
    in_release = str(item.get("inTheReleaseDescription") or "").strip()
    project_primary = (((item.get("project") or {}).get("primary") or {}).get("display") or "").strip()
    module = _map_module_name(item.get("components") or [])

    if raw_type == "osibkaS":
        return ItemType.BUGFIX, DigestVisibility.INTERNAL

    if raw_type != "story":
        return None

    if "Tech🔧" in tags_set:
        return ItemType.TECHNICAL_IMPROVEMENT, DigestVisibility.INTERNAL
    if in_release == "Нет":
        return ItemType.RELEASE_CANDIDATE, DigestVisibility.INTERNAL
    if in_release == "Только внутренний":
        return ItemType.INTERNAL_CHANGE, DigestVisibility.INTERNAL
    if in_release == "Клиентский и внутренний":
        if project_primary == "Product Development":
            return ItemType.NEW_FEATURE, DigestVisibility.PUBLIC
        if module == "Клиентский запрос":
            return ItemType.CLIENT_CUSTOMIZATION, DigestVisibility.PUBLIC
        return ItemType.PRODUCT_IMPROVEMENT, DigestVisibility.PUBLIC

    return None
```

In `_map_source_item`, call this helper and pass both fields into `SourceItem`.

Keep a compatibility wrapper if old tests still import `_classify_item_type`:

```python
def _classify_item_type(item: dict[str, Any]) -> Optional[ItemType]:
    classified = _classify_tracker_item(item)
    return classified[0] if classified else None
```

- [ ] **Step 4: Carry source visibility into ingest output**

In `app/services/ingest.py`, when constructing `DigestItem`, pass:

```python
digest_visibility=source_item.digest_visibility,
```

For epic groups, use the primary item visibility:

```python
digest_visibility=primary.digest_visibility,
```

In `app/services/mock_data.py`, set explicit `digest_visibility` on sample items so local pages show realistic defaults.

- [ ] **Step 5: Run ingest and mapping tests**

Run: `pytest tests/test_review_page_logic.py::ReviewPageLogicTests::test_tracker_maps_client_task_to_client_customization_public tests/test_review_page_logic.py::ReviewPageLogicTests::test_tracker_maps_public_product_story_to_product_improvement tests/test_ingest_ai_generation.py -v`

Expected: PASS after updating any old `ItemType.CHANGE` expectations to `ItemType.PRODUCT_IMPROVEMENT`.

- [ ] **Step 6: Commit**

Run:

```bash
git add app/models.py app/clients/tracker.py app/services/ingest.py app/services/mock_data.py tests/test_review_page_logic.py tests/test_ingest_ai_generation.py
git commit -m "Map Tracker tasks to digest taxonomy"
```

---

### Task 4: Preserve Manual Classification On Reimport

**Files:**
- Modify: `app/services/importers.py`
- Test: `tests/test_importer_copy_preservation.py`

- [ ] **Step 1: Write failing preservation test**

Add a test that creates an existing reviewed item with changed taxonomy fields, reimports the same item, and expects the manual values to stay:

```python
def test_reimport_preserves_manual_type_and_visibility_when_content_unchanged(self) -> None:
    from app.models import DigestItem, DigestRelease, DigestVisibility, ItemStatus, ItemType
    from app.services.importers import _preserve_review_state_when_content_is_unchanged

    existing_release = DigestRelease(id="2026-04", release_date="2026-04-30", summary="Summary")
    release = DigestRelease(id="2026-04", release_date="2026-04-30", summary="Summary")
    existing = DigestItem(
        id="old",
        release_id="2026-04",
        source_item_ids=["DEV-1"],
        title="Generate vacancy text",
        description="Generate vacancy text faster",
        module="AI",
        type=ItemType.CLIENT_CUSTOMIZATION,
        digest_visibility=DigestVisibility.PUBLIC,
        category=None,
        status=ItemStatus.APPROVED,
    )
    incoming = DigestItem(
        id="new",
        release_id="2026-04",
        source_item_ids=["DEV-1"],
        title="Generate vacancy text",
        description="Generate vacancy text faster",
        module="AI",
        type=ItemType.NEW_FEATURE,
        digest_visibility=DigestVisibility.PUBLIC,
        category=None,
        status=ItemStatus.DRAFT,
    )

    _preserve_review_state_when_content_is_unchanged(existing_release, [existing], release, [incoming])

    self.assertEqual(incoming.status, ItemStatus.APPROVED)
    self.assertEqual(incoming.type, ItemType.CLIENT_CUSTOMIZATION)
    self.assertEqual(incoming.digest_visibility, DigestVisibility.PUBLIC)
```

- [ ] **Step 2: Run the preservation test and verify it fails**

Run: `pytest tests/test_importer_copy_preservation.py::ImporterCopyPreservationTests::test_reimport_preserves_manual_type_and_visibility_when_content_unchanged -v`

Expected: FAIL because `_item_signature` includes `type`, so the manual type prevents a match.

- [ ] **Step 3: Preserve taxonomy fields after source-id match**

In `app/services/importers.py`, change `_item_signature` to omit `type`:

```python
def _item_signature(item) -> tuple:
    return (
        item.grouping_mode.value,
        tuple(sorted(item.source_item_ids)),
    )
```

Update `_can_match_review_item` to require `digest_visibility`.

Update `_reviewed_item_content_matches` to compare source content and review copy but not taxonomy fields:

```python
return (
    existing_item.title == item.title
    and existing_item.description == item.description
    and existing_item.module == item.module
    and existing_item.category == item.category
    and existing_item.is_paid_feature == item.is_paid_feature
)
```

After status preservation, copy manual taxonomy:

```python
item.status = existing_item.status
item.type = existing_item.type
item.digest_visibility = existing_item.digest_visibility
```

- [ ] **Step 4: Run preservation tests**

Run: `pytest tests/test_importer_copy_preservation.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add app/services/importers.py tests/test_importer_copy_preservation.py
git commit -m "Preserve digest taxonomy on reimport"
```

---

### Task 5: Review UI Filters And Controls

**Files:**
- Modify: `app/main.py`
- Modify: `templates/review.html`
- Test: `tests/test_review_page_logic.py`

- [ ] **Step 1: Write failing UI render test**

Add:

```python
def test_review_page_renders_change_type_and_visibility_controls(self) -> None:
    from app.models import DigestItem, DigestVisibility, ItemStatus, ItemType
    from app.storage import replace_release_items

    replace_release_items("2026-04", [
        DigestItem(
            id="client-flow",
            release_id="2026-04",
            source_item_ids=["DEV-1"],
            title="Client flow",
            description="Client flow text",
            module="AI",
            type=ItemType.CLIENT_CUSTOMIZATION,
            digest_visibility=DigestVisibility.INTERNAL,
            category=None,
            status=ItemStatus.DRAFT,
        )
    ])

    response = self.client.get("/review/2026-04")

    self.assertEqual(response.status_code, 200)
    self.assertIn("Тип изменения", response.text)
    self.assertIn("Клиентская доработка", response.text)
    self.assertIn("Видимость", response.text)
    self.assertIn("Внутренний обзор", response.text)
    self.assertIn('data-visibility-filter', response.text)
```

- [ ] **Step 2: Run the UI test and verify it fails**

Run: `pytest tests/test_review_page_logic.py::DigestGuardTests::test_review_page_renders_change_type_and_visibility_controls -v`

Expected: FAIL because the template still has the old two-option type select and no visibility controls.

- [ ] **Step 3: Pass visibility context to the template**

In `app/main.py`, import `DIGEST_VISIBILITY_LABELS` and pass:

```python
"digest_visibilities": list(DigestVisibility),
"digest_visibility_labels": DIGEST_VISIBILITY_LABELS,
```

- [ ] **Step 4: Update review filter panel**

In `templates/review.html`, keep the existing type filter loop but change it to the new primary types:

```jinja2
{% for item_type in [ItemType.NEW_FEATURE, ItemType.PRODUCT_IMPROVEMENT, ItemType.CLIENT_CUSTOMIZATION, ItemType.INTERNAL_CHANGE, ItemType.TECHNICAL_IMPROVEMENT, ItemType.BUGFIX] %}
```

Add a second filter row:

```jinja2
<div class="filter-row" data-visibility-filter-bar>
  <span class="filter-label">Видимость</span>
  {% for visibility in digest_visibilities %}
    <label class="type-filter">
      <input
        type="checkbox"
        value="{{ visibility.value }}"
        data-visibility-filter
        checked
      >
      {{ digest_visibility_labels[visibility] }}
    </label>
  {% endfor %}
</div>
```

- [ ] **Step 5: Update card data and controls**

On primary cards, add:

```jinja2
data-digest-visibility="{{ item.digest_visibility.value }}"
```

In the meta grid, add:

```jinja2
<span class="mini-pill" data-digest-visibility-pill>{{ digest_visibility_labels[item.digest_visibility] }}</span>
```

Replace the old `if item.type in [ItemType.NEW_FEATURE, ItemType.CHANGE]` block with always-visible controls for primary items:

```jinja2
<div class="field-row">
  <div class="field-group">
    <label for="item_type-{{ item.id }}">Тип изменения</label>
    <select name="item_type" id="item_type-{{ item.id }}" data-item-type-select>
      {% for option_type in [ItemType.NEW_FEATURE, ItemType.PRODUCT_IMPROVEMENT, ItemType.CLIENT_CUSTOMIZATION, ItemType.INTERNAL_CHANGE, ItemType.TECHNICAL_IMPROVEMENT, ItemType.BUGFIX] %}
        <option value="{{ option_type.value }}" {% if item.type == option_type %}selected{% endif %}>{{ item_type_labels[option_type] }}</option>
      {% endfor %}
    </select>
  </div>
  <div class="field-group">
    <label for="digest_visibility-{{ item.id }}">Видимость</label>
    <select name="digest_visibility" id="digest_visibility-{{ item.id }}" data-digest-visibility-select>
      {% for visibility in digest_visibilities %}
        <option value="{{ visibility.value }}" {% if item.digest_visibility == visibility %}selected{% endif %}>{{ digest_visibility_labels[visibility] }}</option>
      {% endfor %}
    </select>
  </div>
</div>
```

Do not hide paid feature, category, media, or status controls based on visibility.

Treat the review screen as the internal overview for this implementation. Do not add a separate internal digest route; reviewers get the internal view by filtering `Видимость = Внутренний обзор` and grouping mentally by `Тип изменения`.

- [ ] **Step 6: Update client-side filtering/save payload**

In the script, collect `data-visibility-filter` inputs exactly like `typeFilters`, add visibility matching to card filtering, and update the AJAX success handler:

```javascript
if (card && payload.digest_visibility) {
  card.dataset.digestVisibility = payload.digest_visibility;
  const visibilityPill = card.querySelector("[data-digest-visibility-pill]");
  const visibilitySelect = form.querySelector("[data-digest-visibility-select]");
  const visibilityLabel = visibilitySelect?.selectedOptions?.[0]?.textContent?.trim();
  if (visibilityPill && visibilityLabel) {
    visibilityPill.textContent = visibilityLabel;
  }
}
```

- [ ] **Step 7: Run UI tests**

Run: `pytest tests/test_review_page_logic.py::DigestGuardTests::test_review_page_renders_change_type_and_visibility_controls tests/test_review_page_logic.py::DigestGuardTests::test_review_item_can_update_type_and_visibility -v`

Expected: PASS.

- [ ] **Step 8: Commit**

Run:

```bash
git add app/main.py templates/review.html tests/test_review_page_logic.py
git commit -m "Add review taxonomy controls"
```

---

### Task 6: Public Digest Uses Visibility

**Files:**
- Modify: `app/services/publication.py`
- Test: `tests/test_review_page_logic.py`

- [ ] **Step 1: Write failing publication test**

Add:

```python
def test_public_digest_uses_visibility_not_change_type(self) -> None:
    from app.models import DigestItem, DigestVisibility, ItemStatus, ItemType
    from app.services.publication import build_live_digest_content

    content = build_live_digest_content([
        DigestItem(id="public-client", release_id="2026-04", source_item_ids=[], title="Client capability", description="Useful broadly", module="AI", type=ItemType.CLIENT_CUSTOMIZATION, digest_visibility=DigestVisibility.PUBLIC, category=None, status=ItemStatus.APPROVED),
        DigestItem(id="internal-feature", release_id="2026-04", source_item_ids=[], title="Hidden feature", description="Internal only", module="Admin", type=ItemType.NEW_FEATURE, digest_visibility=DigestVisibility.INTERNAL, category=None, status=ItemStatus.APPROVED),
        DigestItem(id="public-fix", release_id="2026-04", source_item_ids=[], title="More stable reports", description="", module="Отчеты", type=ItemType.BUGFIX, digest_visibility=DigestVisibility.PUBLIC, category=None, status=ItemStatus.APPROVED),
    ])

    titles = [item["title"] for section in content["sections"] for item in section["items"]]
    section_titles = [section["title"] for section in content["sections"]]

    self.assertIn("Client capability", titles)
    self.assertIn("More stable reports", titles)
    self.assertNotIn("Hidden feature", titles)
    self.assertNotIn("Баги", section_titles)
```

- [ ] **Step 2: Run the publication test and verify it fails**

Run: `pytest tests/test_review_page_logic.py::DigestGuardTests::test_public_digest_uses_visibility_not_change_type -v`

Expected: FAIL because publication still includes approved items by type, not visibility.

- [ ] **Step 3: Update public digest sections**

In `app/services/publication.py`, filter approved public items:

```python
approved_public_items = [
    item for item in items
    if item.status == ItemStatus.APPROVED
    and item.type != ItemType.RELEASE_CANDIDATE
    and item.digest_visibility == DigestVisibility.PUBLIC
]
```

Group:

```python
new_feature_items = [item for item in approved_public_items if item.type == ItemType.NEW_FEATURE]
client_items = [item for item in approved_public_items if item.type == ItemType.CLIENT_CUSTOMIZATION]
improvement_items = [
    item for item in approved_public_items
    if item.type in {
        ItemType.PRODUCT_IMPROVEMENT,
        ItemType.INTERNAL_CHANGE,
        ItemType.BUGFIX,
        ItemType.TECHNICAL_IMPROVEMENT,
    }
]
```

Build sections:

```python
sections = [
    _section("new_features", "Что нового", new_feature_items, include_tracker=False),
    _section("improvements", "Что улучшили", improvement_items, include_tracker=False),
    _section("client_scenarios", "Клиентские сценарии", client_items, include_tracker=False),
]
```

Update metrics to count public items only and keep legacy metric keys with new meaning where templates need them:

```python
"items_count": len(approved_public_items),
"new_features_count": len(new_feature_items),
"changes_count": len(improvement_items),
"technical_count": 0,
"product_items_count": len(new_feature_items) + len(improvement_items) + len(client_items),
```

Update `normalize_published_digest_content` to support legacy `changes` and `support` snapshots without rewriting historical content unexpectedly, while normalizing new `improvements` and `client_scenarios` sections.

- [ ] **Step 4: Run publication tests**

Run: `pytest tests/test_review_page_logic.py::DigestGuardTests::test_public_digest_uses_visibility_not_change_type tests/test_review_page_logic.py::DigestGuardTests::test_digest_publishes_only_approved_items_in_public_sections tests/test_review_page_logic.py::DigestGuardTests::test_digest_support_section_is_collapsed_by_default -v`

Expected: PASS after updating tests that still expect the old support section for new live digests. Legacy snapshot tests should continue to pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add app/services/publication.py tests/test_review_page_logic.py
git commit -m "Build public digest from visibility"
```

---

### Task 7: Notifications And Full Regression

**Files:**
- Modify: `app/notifications/telegram.py`
- Test: `tests/test_telegram_webhook.py`
- Test: all tests

- [ ] **Step 1: Update notification labels and counts test**

Add or update a test to expect the new labels in `build_review_status_message` output:

```python
def test_review_status_message_uses_digest_taxonomy_labels(self) -> None:
    from app.models import DigestItem, DigestRelease, DigestVisibility, ItemStatus, ItemType
    from app.notifications.telegram import build_review_status_message

    message = build_review_status_message(
        DigestRelease(id="2026-04", release_date="2026-04-30", summary="Summary"),
        [
            DigestItem(id="feature", release_id="2026-04", source_item_ids=[], title="Feature", description="", module="Core", type=ItemType.NEW_FEATURE, digest_visibility=DigestVisibility.PUBLIC, category=None, status=ItemStatus.APPROVED),
            DigestItem(id="fix", release_id="2026-04", source_item_ids=[], title="Fix", description="", module="Core", type=ItemType.BUGFIX, digest_visibility=DigestVisibility.INTERNAL, category=None, status=ItemStatus.APPROVED),
        ],
    )

    self.assertIn("Новый функционал: 1", message)
    self.assertIn("Исправления: 1", message)
```

- [ ] **Step 2: Run notification test and verify it fails**

Run: `pytest tests/test_telegram_webhook.py::TelegramWebhookTests::test_review_status_message_uses_digest_taxonomy_labels -v`

Expected: FAIL because labels still mention old фичи/изменения/багфиксы wording.

- [ ] **Step 3: Update notification counts**

In `app/notifications/telegram.py`, count all six change types and use labels from `ITEM_TYPE_LABELS`:

```python
type_counts = Counter(item.type for item in items if item.type != ItemType.RELEASE_CANDIDATE)
lines.extend(
    f"{ITEM_TYPE_LABELS[item_type]}: {type_counts[item_type]}"
    for item_type in [
        ItemType.NEW_FEATURE,
        ItemType.PRODUCT_IMPROVEMENT,
        ItemType.CLIENT_CUSTOMIZATION,
        ItemType.INTERNAL_CHANGE,
        ItemType.TECHNICAL_IMPROVEMENT,
        ItemType.BUGFIX,
    ]
)
```

Keep release candidate counts separate if the current message includes them.

- [ ] **Step 4: Run full test suite**

Run: `pytest -v`

Expected: PASS.

- [ ] **Step 5: Manual smoke test review page**

Run the app using the project's current dev command. If the README does not define one, use:

```bash
uvicorn app.main:app --reload --port 8000
```

Open `http://127.0.0.1:8000/admin/releases/DEV-47111/digest/review` if that route exists in the local app, or `http://127.0.0.1:8000/review/DEV-47111` for the current FastAPI route. Verify:

- cards show both `Тип изменения` and `Видимость`;
- filters can narrow by both dimensions;
- technical iterations and fixes still have no description textarea;
- other change types keep the description textarea;
- changing visibility does not hide paid/category/media/status controls.

- [ ] **Step 6: Commit**

Run:

```bash
git add app/notifications/telegram.py tests/test_telegram_webhook.py
git commit -m "Update notifications for digest taxonomy"
```

---

## Final Verification

- [ ] Run `pytest -v` and confirm PASS.
- [ ] Run `git status --short` and confirm only intentional files are changed.
- [ ] Review the final diff for accidental edits to generated `output/` or `tmp/`.
- [ ] If all implementation commits are complete, use `superpowers:verification-before-completion` before telling the user the implementation is done.
