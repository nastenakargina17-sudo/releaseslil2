# Client Digest Publication Page Design

## Goal

Build the final publication view for a release digest at `/digest/{release_id}`.

The page is a read-only client-facing digest created from the already reviewed release data. It must not act as an editor, preview workflow, or second review surface. Reviewers make all decisions on `/review/{release_id}`; the digest page only displays the approved result.

## Audience

The page serves a mixed audience:

- clients and product users, who need clear value-oriented release information;
- internal account, CSM, and product teammates, who may use the page when discussing the release with clients.

The page should read as a client digest first. Internal details should appear only where they are useful and safe.

## Publication Readiness

The digest page may show the final publication only when the release is ready:

- `DigestRelease.summary_status` is `approved`;
- published items are limited to `DigestItem.status = approved`;
- `draft`, `reviewed`, and `excluded` items are never displayed;
- `release_candidate` items are never displayed unless review has converted them to a normal digest type and approved them.

If the release is not ready, `/digest/{release_id}` shows a short not-published state instead of a partial digest. The message should not expose unnecessary internal review details to ordinary viewers. If a safe review link is already available to authorized reviewers, the page may include it for them.

## Page Structure

The page has a fixed publication structure:

1. Header
   - digest title;
   - release date;
   - approved summary.

2. Main open sections
   - `new_feature` appears as "Что нового";
   - `change` appears as "Что стало удобнее".

3. Collapsed support section
   - `bugfix` and `technical_improvement` are combined into one section named "Исправления и технические улучшения";
   - this section is collapsed by default;
   - users can expand it if they need details.

Empty sections are hidden. The page should not render placeholder text such as "Нет новых фич" because the digest is a finished publication, not an operational report.

## Published Item Cards

For `new_feature` and `change`, each approved item is displayed as a client digest card with:

- title;
- module;
- value category as a human-readable badge;
- description;
- paid feature badge when `is_paid_feature = true`;
- media gallery when `image_paths` is not empty.

Tracker links are not shown for `new_feature` or `change`.

The value category must use client-friendly labels rather than enum values. Examples:

- `time_saving` -> "Экономия времени";
- `error_reduction` -> "Меньше ошибок";
- `clarity_transparency` -> "Больше прозрачности";
- `daily_work_convenience` -> "Удобнее в ежедневной работе";
- `better_control` -> "Больше контроля";
- `less_communication_overhead` -> "Меньше ручных согласований".

## Media Behavior

Media attached during review should make the digest more presentational:

- the first image is shown as the primary large preview;
- additional images are shown as secondary previews;
- video files, if present in `image_paths`, are displayed with playback controls;
- GIF files are displayed as images;
- media load failures must not make the text unreadable or break the page layout.

For the collapsed support section, media is optional and should remain compact if shown after expansion.

## Collapsed Support Section

The "Исправления и технические улучшения" section combines:

- approved `bugfix` items;
- approved `technical_improvement` items.

It is collapsed by default to keep the page focused on product changes. After expansion, each item should show:

- module;
- title;
- Tracker link when available;
- value category only if it exists and helps understanding.

Unlike `new_feature` and `change`, Tracker links are allowed here because this section also serves internal teammates who may need source details.

## Non-Goals

This change must not:

- add editing controls to `/digest/{release_id}`;
- add new review statuses;
- create a separate persisted publication model;
- duplicate release data into another table;
- change the review workflow;
- change import or AI generation behavior.

The implementation should use the existing `DigestRelease` and `DigestItem` fields.

## Testing Expectations

Tests should cover:

- `/digest/{release_id}` only publishes approved items;
- `draft`, `reviewed`, and `excluded` items are hidden;
- an unapproved summary prevents publication;
- `new_feature` and `change` do not show Tracker links;
- `bugfix` and `technical_improvement` appear together in a collapsed section;
- value categories render with human-readable labels;
- empty sections are omitted.

