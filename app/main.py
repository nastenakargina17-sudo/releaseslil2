from pathlib import Path
from uuid import uuid4

from collections import defaultdict, deque
import mimetypes
from typing import Optional
from urllib.parse import urlencode

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
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
from app.review_utils import (
    CATEGORY_LABELS,
    DESCRIPTIONLESS_ITEM_TYPES,
    ITEM_TYPE_LABELS,
    STATUS_LABELS,
    default_item_category,
    digest_blockers,
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
    remove_item_image,
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
app.state.processed_telegram_update_ids = set()
app.state.processed_telegram_update_order = deque()
app.state.processed_telegram_update_limit = 1000

IMAGE_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
GIF_CONTENT_TYPES = {"image/gif"}
VIDEO_CONTENT_TYPES = {"video/mp4", "video/webm"}
IMAGE_MAX_BYTES = 5 * 1024 * 1024
GIF_MAX_BYTES = 8 * 1024 * 1024
VIDEO_MAX_BYTES = 20 * 1024 * 1024


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
async def yandex_callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    error_description: Optional[str] = None,
) -> RedirectResponse:
    if error:
        return RedirectResponse(
            url=f"/?auth_error={error_description or error}",
            status_code=303,
        )
    if not code or not state:
        return RedirectResponse(url="/?auth_error=missing_oauth_code", status_code=303)

    session = load_session(request, auth_settings)
    expected_state = session.get("oauth_state")
    if not expected_state or state != expected_state:
        return RedirectResponse(url="/?auth_error=invalid_oauth_state", status_code=303)

    session.pop("oauth_state", None)
    next_url = session.pop("post_auth_redirect", "/")

    try:
        access_token = await exchange_code_for_token(code, auth_settings)
        user_info = await fetch_yandex_user(access_token)
    except (AuthConfigurationError, OAuthExchangeError) as exc:
        return RedirectResponse(url=f"/?auth_error={str(exc)}", status_code=303)

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
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks) -> JSONResponse:
    payload = await request.json()
    update_id = payload.get("update_id")
    if isinstance(update_id, int) and _telegram_update_seen(request.app, update_id):
        return JSONResponse({"ok": True, "duplicate": True})

    background_tasks.add_task(_process_telegram_update, payload)
    return JSONResponse({"ok": True})


def _process_telegram_update(payload: dict) -> None:
    bot = TelegramBotService()
    try:
        if "message" in payload:
            bot.handle_message(payload["message"])
        elif "callback_query" in payload:
            bot.handle_callback_query(payload["callback_query"])
    except Exception as exc:
        chat_id = _extract_telegram_chat_id(payload)
        if chat_id:
            try:
                bot.notifier.send_message(
                    f"Не удалось обработать Telegram-событие: {exc}",
                    chat_id=chat_id,
                )
            except Exception:
                pass


def _extract_telegram_chat_id(payload: dict) -> Optional[str]:
    message = payload.get("message") or {}
    callback_query = payload.get("callback_query") or {}
    callback_message = callback_query.get("message") or {}
    for candidate in (message, callback_message):
        chat_id = str((candidate.get("chat") or {}).get("id") or "").strip()
        if chat_id:
            return chat_id
    return None


def _telegram_update_seen(app: FastAPI, update_id: int) -> bool:
    processed_ids = app.state.processed_telegram_update_ids
    processed_order = app.state.processed_telegram_update_order
    if update_id in processed_ids:
        return True

    processed_ids.add(update_id)
    processed_order.append(update_id)
    limit = app.state.processed_telegram_update_limit
    while len(processed_order) > limit:
        oldest = processed_order.popleft()
        processed_ids.discard(oldest)
    return False


@app.get("/review/{release_id}", response_class=HTMLResponse)
def review_release(request: Request, release_id: str) -> HTMLResponse:
    release = get_release(release_id)
    if release is None:
        raise HTTPException(status_code=404, detail="Release not found")
    items = list_items(release_id)
    primary_items = [item for item in items if item.type != ItemType.RELEASE_CANDIDATE]
    candidate_items = [item for item in items if item.type == ItemType.RELEASE_CANDIDATE]
    flash = request.query_params.get("flash")
    digest_ready = release_is_ready_for_digest(release, items)
    return templates.TemplateResponse(
        request,
        "review.html",
        {
            "release": release,
            "items": items,
            "primary_items": primary_items,
            "candidate_items": candidate_items,
            "statuses": list(ItemStatus),
            "summary_statuses": list(SummaryStatus),
            "categories": list(ValueCategory),
            "status_labels": STATUS_LABELS,
            "category_labels": CATEGORY_LABELS,
            "item_type_labels": ITEM_TYPE_LABELS,
            "descriptionless_item_types": {item_type.value for item_type in DESCRIPTIONLESS_ITEM_TYPES},
            "editable_statuses": [status for status in ItemStatus if status != ItemStatus.EXCLUDED],
            "approved_status": ItemStatus.APPROVED.value,
            "excluded_status": ItemStatus.EXCLUDED.value,
            "approved_summary_status": SummaryStatus.APPROVED.value,
            "flash": flash,
            "digest_ready": digest_ready,
            "review_user": getattr(request.state, "review_session", {}).get("user"),
            "media_limits": {
                "image_mb": IMAGE_MAX_BYTES // (1024 * 1024),
                "gif_mb": GIF_MAX_BYTES // (1024 * 1024),
                "video_mb": VIDEO_MAX_BYTES // (1024 * 1024),
            },
        },
    )


@app.post("/review/{release_id}/summary")
def update_summary(
    request: Request,
    release_id: str,
    summary: str = Form(...),
    summary_status: str = Form(...),
) -> Response:
    update_release_summary(release_id, summary, summary_status)
    if _wants_json(request):
        return JSONResponse(
            {
                "ok": True,
                "message": "Summary успешно сохранено.",
                "summary_status": summary_status,
            }
        )
    return RedirectResponse(url=f"/review/{release_id}", status_code=303)


@app.post("/review/{release_id}/items/{item_id}")
def update_review_item(
    request: Request,
    release_id: str,
    item_id: str,
    title: str = Form(...),
    description: str = Form(""),
    category: Optional[str] = Form(None),
    status: str = Form(...),
    is_paid_feature: Optional[str] = Form(None),
    exclude_from_release: Optional[str] = Form(None),
    release_candidate_action: Optional[str] = Form(None),
) -> Response:
    item = get_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Digest item not found")

    effective_status = ItemStatus.EXCLUDED.value if exclude_from_release == "on" else status
    effective_type = item.type
    effective_category = category or None
    effective_description = description
    moved_to_primary = False

    if item.type == ItemType.RELEASE_CANDIDATE:
        if release_candidate_action in {ItemType.NEW_FEATURE.value, ItemType.CHANGE.value}:
            effective_type = ItemType(release_candidate_action)
            effective_status = ItemStatus.DRAFT.value
            effective_category = default_item_category(effective_type).value if default_item_category(effective_type) else None
            effective_description = ""
            moved_to_primary = True
        else:
            effective_status = ItemStatus.APPROVED.value
            effective_category = None
            effective_description = ""

    update_item(
        item_id=item_id,
        title=title,
        description=effective_description,
        category=effective_category,
        status=effective_status,
        is_paid_feature=is_paid_feature == "on",
        item_type=effective_type.value,
    )
    if _wants_json(request):
        return JSONResponse(
            {
                "ok": True,
                "message": "Пункт успешно сохранен.",
                "item_id": item_id,
                "status": effective_status,
                "item_type": effective_type.value,
                "reload": moved_to_primary,
            }
        )
    return RedirectResponse(url=f"/review/{release_id}", status_code=303)


@app.post("/review/{release_id}/items/{item_id}/image")
async def upload_item_image(
    request: Request,
    release_id: str,
    item_id: str,
    image: UploadFile = File(...),
) -> Response:
    item = get_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Digest item not found")

    content = await image.read()
    content_type = (image.content_type or "").lower()
    size_limit = _max_bytes_for_upload(content_type)
    if size_limit is None:
        raise HTTPException(status_code=400, detail="Поддерживаются JPG, PNG, WEBP, GIF, MP4 и WEBM.")
    if len(content) > size_limit:
        raise HTTPException(status_code=400, detail=_file_too_large_message(content_type, size_limit))

    suffix = Path(image.filename or "upload").suffix.lower()
    if not suffix:
        suffix = mimetypes.guess_extension(content_type) or ".bin"
    safe_name = f"{release_id}_{item_id}_{uuid4().hex[:8]}{suffix}"
    destination = UPLOADS_DIR / safe_name
    destination.write_bytes(content)
    add_item_image(item_id, f"/uploads/{safe_name}")
    updated_item = get_item(item_id)
    if _wants_json(request):
        return JSONResponse(
            {
                "ok": True,
                "message": "Файл успешно загружен.",
                "item_id": item_id,
                "media_paths": updated_item.image_paths if updated_item else [],
            }
        )
    return RedirectResponse(url=f"/review/{release_id}?flash=image_uploaded", status_code=303)


@app.post("/review/{release_id}/items/{item_id}/image/delete")
def delete_item_image(
    request: Request,
    release_id: str,
    item_id: str,
    image_path: str = Form(...),
) -> Response:
    item = get_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Digest item not found")
    if image_path not in item.image_paths:
        raise HTTPException(status_code=404, detail="Файл не найден")

    remove_item_image(item_id, image_path)
    local_path = _upload_path_from_public_path(image_path)
    if local_path and local_path.exists():
        local_path.unlink()

    updated_item = get_item(item_id)
    if _wants_json(request):
        return JSONResponse(
            {
                "ok": True,
                "message": "Файл удален.",
                "item_id": item_id,
                "media_paths": updated_item.image_paths if updated_item else [],
            }
        )
    return RedirectResponse(url=f"/review/{release_id}", status_code=303)


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

    all_items = list_items(release_id)
    blockers = digest_blockers(release, all_items)
    item_blockers = [blocker for blocker in blockers if blocker != "Summary не подтвержден"]
    if item_blockers:
        raise HTTPException(
            status_code=400,
            detail=(
                "Не все задачи находятся в статусе подтверждения. "
                "Для генерации дайджеста все задачи должны быть подтверждены."
            ),
        )
    if blockers:
        raise HTTPException(status_code=400, detail="Сначала подтвердите summary релиза.")

    items = [item for item in all_items if item.status == ItemStatus.APPROVED]

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


def _wants_json(request: Request) -> bool:
    return request.headers.get("x-requested-with") == "XMLHttpRequest"


def _max_bytes_for_upload(content_type: str) -> Optional[int]:
    if content_type in IMAGE_CONTENT_TYPES:
        return IMAGE_MAX_BYTES
    if content_type in GIF_CONTENT_TYPES:
        return GIF_MAX_BYTES
    if content_type in VIDEO_CONTENT_TYPES:
        return VIDEO_MAX_BYTES
    return None


def _file_too_large_message(content_type: str, size_limit: int) -> str:
    size_mb = size_limit // (1024 * 1024)
    if content_type in GIF_CONTENT_TYPES:
        return f"GIF должен быть не больше {size_mb} МБ."
    if content_type in VIDEO_CONTENT_TYPES:
        return f"Видео должно быть не больше {size_mb} МБ."
    return f"Изображение должно быть не больше {size_mb} МБ."


def _upload_path_from_public_path(image_path: str) -> Optional[Path]:
    if not image_path.startswith("/uploads/"):
        return None
    return UPLOADS_DIR / Path(image_path).name
