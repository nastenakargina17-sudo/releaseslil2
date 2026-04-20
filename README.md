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
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

The MVP now supports:

- collecting release tasks from linked Tracker issues;
- classifying task type from Tracker fields and tags;
- mapping Tracker components into public module names;
- extracting release dates from the Confluence release schedule page;
- preparing Telegram delivery as a follow-up notification layer.

## Deployment

The repository includes [render.yaml](/Users/user/Downloads/релиз%20ноутс2/render.yaml:1) for a first public deployment on Render.

Before deploying:

1. Push the repo to GitHub.
2. Create a Render Blueprint or Web Service from the repo.
3. Fill all secret env vars in Render.
4. Set `APP_BASE_URL` to the public service URL.

## Current Scope

- In-memory/SQLite-backed MVP structure
- Review screen
- Final digest screen
- Mock import pipeline
