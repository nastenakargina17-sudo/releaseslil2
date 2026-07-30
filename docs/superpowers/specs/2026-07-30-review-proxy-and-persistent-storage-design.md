# Review Proxy and Persistent Storage Design

**Date:** 2026-07-30

## Goal

Make the complete ReleaseCraft review workflow available through
`releasecraft-proxy.skillaz-release.workers.dev` while keeping review data and
uploaded media persistent across Railway deployments.

## Proxy behavior

The Cloudflare Worker acts as a same-origin reverse proxy to Railway.

Allowed public read routes:

- `/`
- `/digests`
- `/digest/*`
- `/static/*`
- `/uploads/*`

Allowed authenticated workflow routes:

- `/review/*` with `GET`, `HEAD`, and `POST`
- `/auth/*` with `GET`, `HEAD`, and `POST`

The Worker forwards session cookies and upstream `Set-Cookie` headers, preserves
request bodies, and rewrites Railway-origin redirects to the Worker origin.
External OAuth redirects remain unchanged.

Unrelated mutation routes such as `/telegram/webhook`, `/releases/import`, and
`/releases/bootstrap` are not exposed through the Worker.

## OAuth

Railway uses:

```text
APP_BASE_URL=https://releasecraft-proxy.skillaz-release.workers.dev
YANDEX_REDIRECT_URI=https://releasecraft-proxy.skillaz-release.workers.dev/auth/yandex/callback
```

The same callback is registered in the Yandex OAuth application. Existing
email-allowlist enforcement remains the authorization boundary for `/review/*`.

## Persistence

Railway mounts one persistent Volume at `/app/data`.

- SQLite remains at `/app/data/release_digest.db`.
- `UPLOADS_DIR=/app/data/uploads` stores all future review and exported media on
  the same Volume.

The application keeps the local development default `<repo>/uploads` when the
environment variable is absent.

## Recovery

The latest complete pre-deployment backup restores:

- `DEV-46754`: 94 items, published;
- `DEV-46757`: 71 items, preview;
- `DEV-47111`: 71 items, draft.

The backup does not contain the final published snapshot for `DEV-46757`.
Therefore its public page returns the preparation state until a new static ZIP
is generated or a snapshot is reconstructed.

## Verification

- Python configuration and application suite passes.
- Worker tests verify cookie forwarding, POST bodies, redirect rewriting, and
  blocked mutation routes.
- Railway is verified after deployment to retain 71 `DEV-46757` items.
- The Worker is verified to issue the Yandex OAuth redirect with the neutral
  callback and a secure session cookie.
