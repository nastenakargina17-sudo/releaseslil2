# Review Soft Locks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add soft per-card review locks and version conflict protection to the current review page.

**Architecture:** Persist lock and version metadata in SQLite. Extend the existing FastAPI review routes with small JSON endpoints and add client-side polling/claiming behavior to `templates/review.html`.

**Tech Stack:** Python, FastAPI, SQLite, Jinja, vanilla JavaScript, unittest/TestClient.

---

### Task 1: Storage Metadata

**Files:**
- Modify: `app/models.py`
- Modify: `app/storage.py`
- Test: `tests/test_review_page_logic.py`

- [ ] Add `version` and `updated_at` fields to release and item dataclasses.
- [ ] Migrate existing SQLite tables with `ALTER TABLE` guarded by column inspection.
- [ ] Increment versions on summary and item saves.
- [ ] Add stale-version tests for item and summary saves.

### Task 2: Review Locks

**Files:**
- Modify: `app/storage.py`
- Modify: `app/main.py`
- Test: `tests/test_review_page_logic.py`

- [ ] Add a `review_locks` table scoped by release, object type, and object id.
- [ ] Add claim, release, list, and override helpers that use the Yandex session user name.
- [ ] Add JSON routes under `/review/{release_id}/locks`.
- [ ] Test claiming, foreign lock rejection, takeover, expiry behavior through route-level tests.

### Task 3: Review Page UI

**Files:**
- Modify: `templates/review.html`
- Test: `tests/test_review_page_logic.py`

- [ ] Render object metadata on summary and item forms.
- [ ] Add lock banners and take-over controls.
- [ ] Claim locks on focus/input and poll active locks every 12 seconds.
- [ ] Send object version with saves and show `409 Conflict` messages without overwriting the form.

### Task 4: Verification

**Files:**
- Test: `tests/test_review_page_logic.py`

- [ ] Run `python3 -B -m pytest tests/test_review_page_logic.py`.
- [ ] Run `python3 -B -m pytest`.
- [ ] Manually inspect the review page if a dev server is already available.

