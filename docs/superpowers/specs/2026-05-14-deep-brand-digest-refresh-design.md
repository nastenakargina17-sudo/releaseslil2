# Deep Brand Digest Refresh Design

## Goal

Refresh the public and preview digest pages into an aesthetic, branded release report. The page should feel polished and client-facing, while staying clearly informational rather than becoming a marketing landing page.

## Visual Direction

Use the "Deep Brand Report" direction:

- dark branded gradient page background built from deep ink and navy tones;
- Skillaz green as the main action/accent color, with a restrained yellow premium accent;
- richer task cards with stronger contrast, subtle borders, and controlled highlights;
- compact, report-like structure with high readability.

The current Skillaz SVG logo should be replaced on digest pages with the supplied black PNG logo:

`/Users/user/Desktop/Подбор/Logo_Skillaz 2/Logo_Skillaz/RGB/PNG/Logo_Skillaz_Black.png`

The PNG should be copied into `static/brand` and referenced from the digest/archive templates.

## Header And Metrics

The digest header becomes a two-zone report header.

Left zone:

- Skillaz logo;
- release date;
- "Дайджест релиза";
- release summary.

Right zone on desktop, stacked under the summary on mobile:

- a distinct "Итоги релиза" metrics block;
- four counters:
  - "Всего изменений";
  - "Новые функции";
  - "Улучшения";
  - "Техническая база".

The publication content builder should expose these counts in `metrics` for both live preview and published snapshots. The counters count only approved, non-release-candidate items that are included in the digest.

## Navigation

The table of contents should feel like report tabs instead of pale pills:

- darker translucent container;
- stronger hover/focus state;
- green active/accent styling;
- section counts when available.

Navigation remains simple anchors and must work without JavaScript.

## Task Cards

Task cards should become visually richer and more branded:

- graphitic or deep-surface card backgrounds instead of flat white;
- clear typography hierarchy for module, title, description, and media;
- a module row with a small module icon and the module name;
- value category badge remains visible but styled more intentionally;
- media should sit in a high-quality framed preview area.

Module icons should be implemented locally, without new frontend dependencies. A small mapping can live in the digest template or publication helper for known module labels such as integrations, подбор, analytics, settings, communications, core/platform, and a generic fallback.

## Paid Feature Label

The paid feature marker should become a premium label, not a generic badge:

- use a yellow/accented pill or ribbon treatment;
- label text: "Платная функция";
- make it visually distinct but not noisy.

## Support Section

Keep the current support section at the end of the page, but make it feel intentional.

Rename:

- from "Исправления и технические улучшения";
- to "Стабильность и техническая база".

Presentation:

- visually separate section near the bottom;
- compact cards;
- module, title, and tracker link remain clear;
- include bugfix and technical-improvement items there;
- section should be highlighted enough to feel designed, but should not compete with product feature cards.

## Media Quality

The current preview quality loss is caused by the review page client-side upload flow. It converts JPG, PNG, and WEBP files to WEBP through canvas at quality `0.82` and limits the largest side to 2200 pixels before upload.

Change upload behavior:

- do not automatically convert or recompress JPG, PNG, or WEBP files before upload;
- preserve original image bytes when the file is within the existing server limit;
- keep existing limits:
  - images: 5 MB;
  - GIF: 8 MB;
  - video: 20 MB;
- keep GIF and video behavior unchanged;
- published digest should continue copying media into `/uploads/published/{release_id}/...` byte-for-byte.

This keeps preview and public digest quality consistent with the uploaded source file while preserving upload safety.

## Scope

In scope:

- digest preview page;
- public digest page;
- digest archive branding where it shares logo and page shell;
- publication metrics payload;
- review upload JavaScript quality fix;
- focused tests for metrics and no client-side recompression.

Out of scope:

- changing review authentication;
- changing publication workflow states;
- changing server-side upload size limits;
- adding a new frontend framework or icon dependency;
- deploying automatically as part of the implementation step.

## Validation

Implementation should be verified by:

- unit tests for the new metrics fields;
- existing digest publication tests;
- a test or targeted check confirming upload JavaScript no longer recompresses images;
- local browser review of `/review/{release_id}/digest-preview`, `/digest/{release_id}`, and `/digests`;
- visual check that text does not overflow on mobile and desktop widths.
