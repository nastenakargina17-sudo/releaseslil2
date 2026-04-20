from pathlib import Path
from uuid import uuid4

from collections import defaultdict
from typing import Optional
from urllib.parse import urlencode

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.auth import (
    AuthConfigurationError,
    OAuthExchangeError,
    build_review_entry_url,
    build_yandex_login_url,
    exchange_code_for_token,
    extract_display_name,
    extract_user_email,
    fetch_yandex_user,
    generate_state_token,
    is_allowed_email,
)

from app.config import (
    TEMPLATES_DIR,
    UPLOADS_DIR,
    ensure_directories,
    get_app_settings,
    get_auth_settings,
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
from app.session import clear_session, load_session, save_session
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
load_env_file()
auth_settings = get_auth_settings()
ensure_directories()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.middleware("http")
async def require_review_auth(request: Request, call_next):
    if not request.url.path.startswith("/review/"):
        return await call_next(request)

    session = load_session(request, auth_settings)
    user = session.get("user")
    user_email = (user or {}).get("email", "").strip().lower()
    if user and is_allowed_email(user_email, auth_settings):
        request.state.review_session = session
        return await call_next(request)

    next_url = request.url.path
    if request.url.query:
        next_url = f"{next_url}?{request.url.query}"
    login_url = app.url_path_for("login_with_yandex")
    response = RedirectResponse(
        url=f"{login_url}?{urlencode({'next': next_url})}",
        status_code=303,
    )
    if user:
        clear_session(response)
    return response


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    release_id = "2026-04"
    release = get_release(release_id)
    items = list_items(release_id) if release else []
    error = request.query_params.get("error")
    auth_error = request.query_params.get("auth_error")
    review_user = load_session(request, auth_settings).get("user")
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "release": release,
            "items": items,
            "error": error,
            "auth_error": auth_error,
            "review_user": review_user,
        },
    )


@app.get("/auth/yandex/login", name="login_with_yandex")
def login_with_yandex(request: Request, next: str = "/") -> RedirectResponse:
    state = generate_state_token()
    session = load_session(request, auth_settings)
    session["oauth_state"] = state
    session["post_auth_redirect"] = next or "/"
    try:
        login_url = build_yandex_login_url(auth_settings, state)
    except AuthConfigurationError:
        raise HTTPException(status_code=500, detail="Yandex OAuth is not configured")
    response = RedirectResponse(url=login_url, status_code=303)
    save_session(response, session, auth_settings)
    return response


@app.get("/auth/yandex/callback")
async def yandex_callback(request: Request, code: str, state: str) -> RedirectResponse:
    session = load_session(request, auth_settings)
    expected_state = session.get("oauth_state")
    if not expected_state or state != expected_state:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    session.pop("oauth_state", None)
    next_url = session.pop("post_auth_redirect", "/")

    try:
        access_token = await exchange_code_for_token(code, auth_settings)
        user_info = await fetch_yandex_user(access_token)
    except (AuthConfigurationError, OAuthExchangeError) as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    email = extract_user_email(user_info)
    if not is_allowed_email(email, auth_settings):
        session.pop("user", None)
        response = RedirectResponse(url="/?auth_error=access_denied", status_code=303)
        save_session(response, session, auth_settings)
        return response

    session["user"] = {
        "email": email,
        "name": extract_display_name(user_info, email),
    }
    response = RedirectResponse(url=next_url or "/", status_code=303)
    save_session(response, session, auth_settings)
    return response


@app.post("/auth/logout")
def logout(request: Request) -> RedirectResponse:
    response = RedirectResponse(url="/", status_code=303)
    clear_session(response)
    return response


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
        request,
        "review.html",
        {
            "release": release,
            "items": items,
            "statuses": list(ItemStatus),
            "summary_statuses": list(SummaryStatus),
            "categories": list(ValueCategory),
            "flash": flash,
            "digest_ready": digest_ready,
            "review_user": getattr(request.state, "review_session", {}).get("user"),
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
    review_path = f"/review/{release_id}"
    review_url = (
        build_review_entry_url(app_settings.base_url, review_path)
        if app_settings.base_url
        else None
    )
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
        request,
        "digest.html",
        {
            "release": release,
            "new_features": new_features,
            "changes": changes,
            "grouped_bugfixes": dict(grouped_bugfixes),
            "grouped_technical": dict(grouped_technical),
        },
    )
