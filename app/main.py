from pathlib import Path
from uuid import uuid4

from collections import defaultdict
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import (
    TEMPLATES_DIR,
    UPLOADS_DIR,
    ensure_directories,
    get_app_settings,
    get_telegram_settings,
    load_env_file,
)
from app.models import ItemStatus, ItemType, SummaryStatus, ValueCategory
from app.notifications.telegram import (
    TelegramNotifier,
    build_digest_ready_message,
    build_review_status_message,
    release_is_ready_for_digest,
)
from app.services.ingest import build_release
from app.services.importers import import_release_from_apis
from app.services.mock_data import sample_source_items
from app.services.telegram_bot import TelegramBotService
from app.storage import (
    add_item_image,
    get_release,
    init_db,
    get_item,
    list_items,
    replace_release_items,
    update_item,
    update_release_summary,
    upsert_release,
)


app = FastAPI(title="Release Digest MVP")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
load_env_file()
ensure_directories()
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    release_id = "2026-04"
    release = get_release(release_id)
    items = list_items(release_id) if release else []
    error = request.query_params.get("error")
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "release": release,
            "items": items,
            "error": error,
        },
    )


@app.post("/releases/bootstrap")
def bootstrap_release() -> RedirectResponse:
    release_id = "2026-04"
    release_date = "2026-04-30"
    release, items = build_release(sample_source_items(), release_id, release_date)
    upsert_release(release)
    replace_release_items(release_id, items)
    return RedirectResponse(url="/review/2026-04", status_code=303)


@app.post("/releases/import")
def import_release(release_id: str = Form(...)) -> RedirectResponse:
    try:
        import_release_from_apis(release_id)
    except Exception as exc:
        return RedirectResponse(url=f"/?error={str(exc)}", status_code=303)
    return RedirectResponse(url=f"/review/{release_id}", status_code=303)


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request) -> JSONResponse:
    payload = await request.json()
    bot = TelegramBotService()
    if "message" in payload:
        bot.handle_message(payload["message"])
    elif "callback_query" in payload:
        bot.handle_callback_query(payload["callback_query"])
    return JSONResponse({"ok": True})


@app.get("/review/{release_id}", response_class=HTMLResponse)
def review_release(request: Request, release_id: str) -> HTMLResponse:
    release = get_release(release_id)
    if release is None:
        raise HTTPException(status_code=404, detail="Release not found")
    items = list_items(release_id)
    flash = request.query_params.get("flash")
    digest_ready = release_is_ready_for_digest(release, items)
    return templates.TemplateResponse(
        "review.html",
        {
            "request": request,
            "release": release,
            "items": items,
            "statuses": list(ItemStatus),
            "summary_statuses": list(SummaryStatus),
            "categories": list(ValueCategory),
            "flash": flash,
            "digest_ready": digest_ready,
        },
    )


@app.post("/review/{release_id}/summary")
def update_summary(
    release_id: str,
    summary: str = Form(...),
    summary_status: str = Form(...),
) -> RedirectResponse:
    update_release_summary(release_id, summary, summary_status)
    return RedirectResponse(url=f"/review/{release_id}", status_code=303)


@app.post("/review/{release_id}/items/{item_id}")
def update_review_item(
    release_id: str,
    item_id: str,
    title: str = Form(...),
    description: str = Form(""),
    category: Optional[str] = Form(None),
    status: str = Form(...),
    is_paid_feature: Optional[str] = Form(None),
) -> RedirectResponse:
    update_item(
        item_id=item_id,
        title=title,
        description=description,
        category=category or None,
        status=status,
        is_paid_feature=is_paid_feature == "on",
    )
    return RedirectResponse(url=f"/review/{release_id}", status_code=303)


@app.post("/review/{release_id}/items/{item_id}/image")
async def upload_item_image(
    release_id: str,
    item_id: str,
    image: UploadFile = File(...),
) -> RedirectResponse:
    item = get_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Digest item not found")

    suffix = Path(image.filename or "upload").suffix or ".bin"
    safe_name = f"{release_id}_{item_id}_{uuid4().hex[:8]}{suffix}"
    destination = UPLOADS_DIR / safe_name
    content = await image.read()
    destination.write_bytes(content)
    add_item_image(item_id, f"/uploads/{safe_name}")
    return RedirectResponse(url=f"/review/{release_id}?flash=image_uploaded", status_code=303)


@app.post("/review/{release_id}/notify-review")
def notify_review_status(release_id: str) -> RedirectResponse:
    release = get_release(release_id)
    if release is None:
        raise HTTPException(status_code=404, detail="Release not found")
    items = list_items(release_id)
    app_settings = get_app_settings()
    review_url = f"{app_settings.base_url}/review/{release_id}" if app_settings.base_url else None
    notifier = TelegramNotifier(get_telegram_settings())
    notifier.send_message(build_review_status_message(release, items, review_url))
    return RedirectResponse(url=f"/review/{release_id}?flash=review_notified", status_code=303)


@app.post("/review/{release_id}/notify-digest")
def notify_digest_ready(release_id: str) -> RedirectResponse:
    release = get_release(release_id)
    if release is None:
        raise HTTPException(status_code=404, detail="Release not found")
    items = list_items(release_id)
    if not release_is_ready_for_digest(release, items):
        return RedirectResponse(url=f"/review/{release_id}?flash=digest_not_ready", status_code=303)
    approved_items = [item for item in items if item.status == ItemStatus.APPROVED]
    app_settings = get_app_settings()
    digest_url = f"{app_settings.base_url}/digest/{release_id}" if app_settings.base_url else None
    notifier = TelegramNotifier(get_telegram_settings())
    notifier.send_message(build_digest_ready_message(release, approved_items, digest_url))
    return RedirectResponse(url=f"/review/{release_id}?flash=digest_notified", status_code=303)


@app.get("/digest/{release_id}", response_class=HTMLResponse)
def final_digest(request: Request, release_id: str) -> HTMLResponse:
    release = get_release(release_id)
    if release is None:
        raise HTTPException(status_code=404, detail="Release not found")

    items = [item for item in list_items(release_id) if item.status == ItemStatus.APPROVED]
    if release.summary_status != SummaryStatus.APPROVED:
        raise HTTPException(status_code=400, detail="Summary is not approved")

    grouped_bugfixes = defaultdict(list)
    grouped_technical = defaultdict(list)
    new_features = []
    changes = []

    for item in items:
        if item.type == ItemType.NEW_FEATURE:
            new_features.append(item)
        elif item.type == ItemType.CHANGE:
            changes.append(item)
        elif item.type == ItemType.BUGFIX:
            grouped_bugfixes[item.module].append(item)
        elif item.type == ItemType.TECHNICAL_IMPROVEMENT:
            grouped_technical[item.module].append(item)

    return templates.TemplateResponse(
        "digest.html",
        {
            "request": request,
            "release": release,
            "new_features": new_features,
            "changes": changes,
            "grouped_bugfixes": dict(grouped_bugfixes),
            "grouped_technical": dict(grouped_technical),
        },
    )
