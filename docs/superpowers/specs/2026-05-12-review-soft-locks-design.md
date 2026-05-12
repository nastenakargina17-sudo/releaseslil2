# Review Soft Locks Design

## Goal

Allow multiple product reviewers to work on the same release review page without silently overwriting each other's edits.

## Decision

Use soft locks on individual review objects: the release summary and each digest item. A user who focuses a form claims that object for a short time. Other users can still read the content, but they see who is editing it and can intentionally take over editing if needed.

## User Experience

- Show only the Yandex session display name in the review page lock banner.
- Claim a lock when a reviewer focuses or changes a summary/item form.
- Refresh active locks periodically from the browser.
- Expire locks automatically after a short timeout so a closed tab does not block work.
- Let another reviewer override a lock explicitly with a "take over" action.
- Protect saved data with a version check. If a form was opened with an old version, the server rejects the save with a conflict response instead of silently overwriting newer content.

## Technical Shape

- Store `version` and `updated_at` for releases and items.
- Store active review locks in SQLite with object scope, owner name, owner session id, and expiry timestamp.
- Add JSON endpoints for claiming, releasing, overriding, and listing locks.
- Keep the implementation AJAX-friendly and compatible with the existing non-JavaScript form fallback where possible.
- Use polling instead of WebSockets because the current app is a small FastAPI/Jinja MVP and two product reviewers are the expected case.

## Error Handling

- Saving with a stale version returns `409 Conflict` and a Russian message asking the reviewer to refresh before saving.
- Expired locks are ignored and cleaned opportunistically.
- A reviewer can refresh or take over a stale/foreign lock without administrator involvement.

