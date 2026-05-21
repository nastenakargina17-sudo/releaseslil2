# Release Digest MVP

MVP for transforming tracker tasks into a reviewed monthly digest.

## Stack

- Python
- FastAPI
- Jinja templates
- SQLite
- httpx

## Planned Integrations

- Tracker API for source items
- Confluence API for release date

## Local Run

1. Create a virtualenv.
2. Install dependencies from `requirements.txt`.
3. Start the app with `uvicorn app.main:app --reload`.
4. Copy `.env.example` to `.env` and fill real values for Tracker, Confluence, and Telegram.

## Environment

Configure integrations through environment variables:

- `TRACKER_API_BASE_URL`
- `TRACKER_API_TOKEN`
- `TRACKER_ORG_ID`

- `CONFLUENCE_API_BASE_URL`
- `CONFLUENCE_API_TOKEN`
- `CONFLUENCE_RELEASE_SCHEDULE_PAGE_ID`
- `OPENAI_API_KEY`
- `OPENAI_MODEL`
- `OPENAI_TIMEOUT_SECONDS`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `SESSION_SECRET`
- `SESSION_HTTPS_ONLY`
- `YANDEX_CLIENT_ID`
- `YANDEX_CLIENT_SECRET`
- `YANDEX_REDIRECT_URI`
- `YANDEX_ALLOWED_EMAILS`

The MVP now supports:

- collecting release tasks from linked Tracker issues;
- classifying task type from Tracker fields and tags;
- mapping Tracker components into public module names;
- extracting release dates from the Confluence release schedule page;
- preparing Telegram delivery as a follow-up notification layer.

## Deployment

The currently used production deployment is Railway.

- Project: `releaseslil2`
- Service: `ReleaseCraft`
- Production domain: `skillaz-digest.up.railway.app`
- Telegram bot webhook is handled by the main web app at `/telegram/webhook`

Important notes:

1. The Telegram bot does not run as a separate worker in this repo.
2. Bot callbacks are handled by the FastAPI app in `app.main`.
3. If the bot behaves differently from local code, check the deployed Railway service first.
4. For GPT-generated release copy to work in production, the Railway service must have `OPENAI_API_KEY`, `OPENAI_MODEL`, and `OPENAI_TIMEOUT_SECONDS` configured.

The repository also still includes [render.yaml](/Users/user/Downloads/релиз%20ноутс2/render.yaml:1) from an earlier deployment option, but the active environment we verified is Railway.

## Telegram Bot Smoke Test

Use this when the bot stops responding and you need to know whether the problem is code, Railway, or Telegram webhook configuration.

1. Check that Railway serves the app:

   ```bash
   curl -sS -o /tmp/releasecraft_root.out -w '%{http_code}\n' https://skillaz-digest.up.railway.app/
   ```

   Expected: `200`.

2. Check that the Telegram webhook endpoint is reachable:

   ```bash
   curl -sS -X POST https://skillaz-digest.up.railway.app/telegram/webhook \
     -H 'content-type: application/json' \
     -d '{"update_id":999999999,"message":{"chat":{"id":0},"text":"/start"}}'
   ```

   Expected: `{"ok":true}`.

3. Check Railway HTTP logs for real Telegram hits:

   ```bash
   railway logs --service ReleaseCraft --environment production --http --path /telegram/webhook --lines 20
   ```

   If there are no recent Telegram requests, the app is probably healthy but Telegram webhook is pointed at the wrong URL or the bot token/webhook was changed.

4. Check the local webhook tests without installing pytest:

   ```bash
   .venv/bin/python -m unittest tests.test_telegram_webhook -v
   ```

Local `.env` must include `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` if you want to send real Telegram messages from the local app. Without those values, local web requests can work while the bot cannot answer in Telegram.

## Current Scope

- In-memory/SQLite-backed MVP structure
- Review screen
- Final digest screen
- Mock import pipeline

## Review Access

The `/review/*` area is protected with Yandex OAuth and an email allowlist.

Setup notes:

1. Configure your Yandex OAuth app callback to `https://<your-domain>/auth/yandex/callback`.
2. Put approved employee emails into `YANDEX_ALLOWED_EMAILS` as a comma-separated list.
3. Set `SESSION_SECRET` to a long random value.
4. Set `SESSION_HTTPS_ONLY=true` in production behind HTTPS.

Only the review routes require login. The landing page and `/digest/*` stay public.
