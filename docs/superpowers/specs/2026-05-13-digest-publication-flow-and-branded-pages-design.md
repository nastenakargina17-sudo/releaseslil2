# Digest Publication Flow And Branded Pages Design

## Goal

Build a complete publication flow after release review:

- reviewers finish approving release content;
- reviewers generate an internal live preview;
- reviewers publish a stable client-facing snapshot;
- clients can open a public digest page;
- clients can browse a public archive of published digests.

This design extends the existing review page and digest skeleton. It does not deploy to Railway in this iteration. Railway remains the target production environment for a later explicit deployment step.

## Current Context

The project already has:

- a protected `/review/{release_id}` page;
- item and summary approval statuses;
- uploaded item media;
- a public `/digest/{release_id}` route skeleton;
- Railway as the currently documented production target.

The current digest skeleton is read-only, but it still needs a stronger publication lifecycle, published snapshots, archive behavior, and branded visual design.

## Publication Lifecycle

Each release gets a publication status:

- `draft`: review is in progress, or approved data changed after preview;
- `preview`: an internal preview has been formed from current approved review data;
- `published`: a public snapshot has been created and the release is closed for editing.

The lifecycle is:

```text
review/draft -> preview -> published
```

Reviewers can return from `preview` to `draft`. Reviewers cannot return from `published` to editing.

## Review Page Flow

The final action area on `/review/{release_id}` becomes a publication block.

### Draft State

In `draft`, the block shows that the digest is still in preparation.

If summary or items are not ready, it explains the blockers:

- summary must be approved;
- publishable items must be `approved` or `excluded`;
- release candidates do not publish unless converted to normal publishable item types and approved.

When the release is ready, the primary action is:

- `Сформировать preview`

This action sets publication status to `preview` and gives reviewers access to the preview page.

### Preview State

In `preview`, the block shows that an internal preview exists.

Available actions:

- `Открыть preview`;
- `Опубликовать дайджест`;
- `Вернуться к ревью`.

Publishing can be triggered from both the review page and the preview page. On the review page, the publish action must include a clear hint: publishing will create a fixed snapshot and close the release from further editing.

If a reviewer edits summary, edits an item, uploads media, deletes media, or otherwise changes publishable review content while the release is in `preview`, the publication status resets to `draft`. The user sees:

- a flash message immediately after the change;
- a persistent explanation in the publication block saying that preview was reset because reviewed data changed.

### Published State

In `published`, the block shows that the digest has been published.

The block shows audit details to reviewers only:

- who published;
- when it was published.

Preview and publish buttons disappear. The main action is:

- `Открыть опубликованный дайджест`

After publication, review editing is blocked:

- summary cannot be changed;
- items cannot be changed;
- media cannot be uploaded or deleted;
- release candidates cannot be promoted or changed.

This keeps the published snapshot and review state aligned with the rule that publication is final for that release.

## Internal Preview

The internal preview URL is:

```text
/review/{release_id}/digest-preview
```

It is protected by the existing `/review/*` authentication middleware.

Preview is live. It renders current approved review data and does not create a persisted content copy.

The preview page includes:

- a visible `Предпросмотр` banner;
- the same digest layout as the public page;
- `Опубликовать дайджест`;
- `Вернуться к ревью`.

Preview cannot be accessed unless publication status is `preview` and review content is still ready. If data changed and the status reset to `draft`, the preview page should point reviewers back to review.

## Published Snapshot

Publishing creates a stable snapshot in a separate model/table, conceptually named `published_digests`.

The snapshot stores publication content independently from review tables.

There is one published snapshot per release. If a release is not yet published, it has no snapshot. Since published releases cannot return to editing, this design does not need multiple versions inside the same release.

Release-level fields:

- `release_id`;
- `release_date`;
- `summary`;
- `published_by`;
- `published_at`;
- structured published sections;

Item-level data inside the snapshot:

- `title`;
- `description`;
- `module`;
- `type`;
- `value_category`;
- human-readable value category label;
- `is_paid_feature`;
- media list;
- support-section Tracker links when available and allowed;
- item order at publication time.

The public digest does not show `published_by` or `published_at`. Those fields are for reviewers on the review page.

## Media Snapshot

Publish copies media files from review uploads into a dedicated published media area, for example:

```text
/uploads/published/{release_id}/...
```

The snapshot stores paths to the copied published media, not the original review upload paths.

If any media file cannot be copied, publishing is blocked. The user sees an error and no partial publication is created.

This makes the public digest stable even if review uploads are later changed, deleted, or reorganized.

## Public Digest Page

The public URL remains:

```text
/digest/{release_id}
```

It reads from the published snapshot only.

If no published snapshot exists, it shows a friendly preparation state:

```text
Дайджест в подготовке
```

Ordinary visitors do not see internal links. If a safe reviewer session is present, reviewers may see a link back to review.

The public page contains no review controls and no audit metadata.

## Public Archive

Add a public archive:

```text
/digests
```

The archive lists published digest snapshots only.

It is public because the digests are client-facing publications.

The archive is an editorial page, not an internal table. Each release card includes:

- release date;
- release identifier or title;
- short summary;
- one or two lightweight badges or metrics;
- branded shape/accent treatment;
- link to `/digest/{release_id}`.

The archive does not expose review status, audit metadata, or unpublished releases.

## Digest Visual Concept

The public digest and archive should feel like a light editorial Skillaz publication for the product `Подбор`.

### Brand Assets

Use only the needed assets from:

```text
/Users/user/Desktop/Подбор
```

Expected asset sources:

- Skillaz RGB logo SVG;
- Skillaz icon SVG or PNG if useful;
- product marker/badge for `Подбор`;
- selected font files only.

Do not copy the whole brand folder into the project.

### Typography

Use a small selected subset of brand fonts:

- main text/interface font from Onest or TT Hoves;
- bold weight for headings;
- accent mono font only if it has a clear role.

Avoid copying the full font pack.

### Colors

Use:

- white and light gray backgrounds;
- dark blue base text colors from the brand palette;
- `#49DE4E` as the main product accent;
- `#D9FFDB` as the soft product accent.

Do not mix multiple unrelated accent colors on the same page. The green accent may be used in badges, small graphic details, and 1-2 highlighted words, but not as the color for whole text blocks.

### Hero

The digest hero should include:

- Skillaz logo;
- product badge/marker `Подбор`;
- `Дайджест релиза`;
- release date;
- summary.

The hero uses a light editorial background with brand forms:

- rectangle;
- hexagon;
- diamond;
- oval.

Important text and graphics stay centered and safe from cropping on different screen sizes.

### Content Structure

Below the hero:

- compact table of contents;
- `Что нового`;
- `Что стало удобнее`;
- collapsed `Исправления и технические улучшения`.

The product sections use restrained editorial cards:

- module;
- value category badge;
- title;
- description;
- `Платная функция` badge when `is_paid_feature = true`;
- media.

### Media Carousel

For `new_feature` and `change` cards:

- one media item appears as a large preview;
- multiple media items appear as a carousel;
- desktop uses arrows and indicators or thumbnails;
- mobile uses horizontal scroll/snap;
- video keeps playback controls.

The support section remains compact and does not use a prominent carousel.

## Error Handling

- If `/digest/{release_id}` has no published snapshot, show `Дайджест в подготовке`.
- If `/review/{release_id}/digest-preview` is requested outside `preview`, send reviewers back to review or show a clear internal message.
- If publish fails to copy media, keep the release in `preview` and show an error.
- If review content changes in `preview`, reset to `draft` and explain why.
- If release is `published`, reject edit/upload/delete operations with a clear message.

## Deployment Boundary

Do not deploy to Railway as part of this design's first implementation.

After local and branch review, deployment can happen as a separate step to the existing Railway service:

- project: `releaseslil2`;
- service: `ReleaseCraft`.

## Non-Goals

This design does not add:

- rollback to a previous published version;
- multiple published versions inside one release;
- editing after publication;
- AI regeneration at publish time;
- public audit metadata;
- automatic Railway deployment.
