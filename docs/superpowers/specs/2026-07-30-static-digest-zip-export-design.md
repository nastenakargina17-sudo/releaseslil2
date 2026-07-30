# Static Digest ZIP Export Design

**Date:** 2026-07-30

## Goal

Replace the final publication action for future release digests with a repeatable
static export. A reviewer prepares and previews a digest, then downloads a ZIP
archive that can be hosted on another web server without depending on the
ReleaseCraft application or its Railway domain.

## User flow

The intended workflow is:

```text
review -> preview -> generate and download ZIP -> return to review
                                      |
                                      +-> edit -> preview -> download a new ZIP
```

On the preview page, the current `Опубликовать дайджест` action becomes
`Сформировать ZIP`.

Generating an archive is not publication:

- it does not change the release to `published`;
- it does not create a public digest snapshot;
- it does not lock the release against editing;
- it can be repeated after any subsequent review changes.

The existing `Вернуться к ревью` action remains available.

## Export format

The response is a ZIP file named from the release identifier, for example:

```text
DEV-46757.zip
```

Its layout is:

```text
DEV-46757/
  index.html
  assets/
    Logo_Skillaz_Black.png
    OnestRegular1602-hint.ttf
    OnestBold1602-hint.ttf
    <digest images and videos>
```

`index.html` is a final client-facing digest page. It contains the current
approved digest content and no preview controls, review links, filters, or
application-only actions.

All fonts, branding, images, and videos use relative paths under `assets/`.
The resulting directory can therefore be copied to an arbitrary path on a
standard static web server.

## Content source

Every export is built from the current review state:

- only approved items are included;
- release candidates remain excluded;
- the current release summary is used;
- current metrics and section grouping are recalculated;
- current review media files are copied into the archive.

The export does not read from or write to `published_digests`. This keeps the
new export lifecycle independent from the legacy public publication lifecycle.

## Rendering architecture

The existing digest visual design remains the source of truth. Static export
uses the same public-page presentation and item-card partials, with an explicit
static export mode that:

- renders the final public appearance rather than preview chrome;
- emits relative asset paths;
- omits all application navigation and forms.

Archive construction belongs in a dedicated service. The service:

1. builds the live digest content;
2. validates every required media and brand asset;
3. assigns collision-safe filenames inside `assets/`;
4. renders `index.html`;
5. writes the HTML and assets to an in-memory or temporary ZIP;
6. returns the completed archive only after all steps succeed.

Temporary files must be isolated and cleaned up after the response is complete.
No generated archive needs to be persisted by the application.

## Route and interface behavior

A protected review route generates the archive for a release in preview state.
The route uses the same authentication boundary as the rest of `/review/*`.

The preview page submits to that route. A successful response downloads the ZIP
without changing publication status. The reviewer can then return to review,
edit the release, prepare preview again if required by the current workflow, and
generate another archive.

The first version retains the existing requirement that the digest must be
ready and in preview before it can be exported. Invalid or stale requests return
the reviewer to the review page with a clear status message.

## Existing published digests

Existing published snapshots and public routes remain intact for compatibility,
including previously shared client links.

This change does not migrate, delete, or republish existing digests. It changes
the primary preview action for future work from public publication to static ZIP
generation.

## Failure handling

The archive is not returned if any required file cannot be read or copied.
Expected failures include:

- a referenced review image or video is missing;
- a required brand asset is missing;
- template rendering fails;
- ZIP construction fails.

The user receives a clear export error and can return to review. A partial
archive is never presented as successful, and release state remains unchanged.

## Security

- The export endpoint is protected as a review endpoint.
- Archive paths are generated internally and never derived directly as
  filesystem destinations from user-controlled paths.
- Media filenames are sanitized or replaced with generated safe names.
- ZIP entries cannot contain absolute paths or `..` traversal segments.
- The generated page includes only final digest content and intentionally omits
  authentication/session information.

## Verification

Automated tests cover:

- successful download with the expected filename and ZIP content type;
- expected `index.html` and `assets/` structure;
- final-page rendering without preview or publication controls;
- relative paths for logo, fonts, images, and videos;
- byte-for-byte inclusion of media assets;
- collision-safe media naming;
- rejection when the release is not ready for preview/export;
- graceful failure when referenced media is missing;
- unchanged release publication status after export;
- the ability to edit and export again;
- preservation of legacy published digest routes.

## Out of scope

- uploading the ZIP to the target hosting provider;
- choosing or configuring the final public domain;
- automatic deployment after export;
- removing legacy public digest routes or stored snapshots;
- exporting all releases as one static archive.
