from pathlib import Path
from uuid import uuid4

from collections import deque
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
    build_yandex_login_url,
    exchange_code_for_token,
    extract_display_name,
    fetch_yandex_user,
    find_allowed_email,
    generate_state_token,
    is_allowed_email,
)

from app.config import (
    STATIC_DIR,
    TEMPLATES_DIR,
    UPLOADS_DIR,
    ensure_directories,
    get_app_settings,
    get_auth_settings,
    get_telegram_settings,
    load_env_file,
)
from app.models import DigestVisibility, ItemStatus, ItemType, SummaryStatus, ValueCategory
from app.models import PublicationStatus
from app.notifications.telegram import (
    TelegramNotifier,
    build_digest_ready_message,
    build_review_status_message,
    release_is_ready_for_digest,
)
from app.review_utils import (
    CATEGORY_LABELS,
    CLIENT_CATEGORY_LABELS,
    DESCRIPTIONLESS_ITEM_TYPES,
    DIGEST_VISIBILITY_LABELS,
    ITEM_TYPE_LABELS,
    STATUS_LABELS,
    default_item_category,
    digest_blockers,
    is_video_media_path,
)
from app.services.ingest import build_release
from app.services.importers import import_release_from_apis
from app.services.mock_data import sample_source_items
from app.services.publication import (
    PublicationError,
    build_live_digest_content,
    build_published_digest_snapshot,
    normalize_published_digest_content,
)
from app.services.telegram_bot import TelegramBotService
from app.session import clear_session, load_session, save_session
from app.storage import (
    add_item_image,
    bulk_exclude_items,
    claim_review_lock,
    get_release,
    init_db,
    get_item,
    get_published_digest,
    list_published_digests,
    list_items,
    list_review_presence,
    list_review_locks,
    remove_item_image,
    replace_release_items,
    reset_preview_after_review_change,
    release_review_presence,
    release_review_lock,
    split_epic_item,
    save_published_digest,
    StaleObjectError,
    touch_review_presence,
    update_item,
    update_release_summary,
    update_release_publication_status,
    upsert_release,
)

app = FastAPI(title="Release Digest MVP")
load_env_file()
auth_settings = get_auth_settings()
ensure_directories()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.state.processed_telegram_update_ids = set()
app.state.processed_telegram_update_order = deque()
app.state.processed_telegram_update_limit = 1000

IMAGE_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
GIF_CONTENT_TYPES = {"image/gif"}
VIDEO_CONTENT_TYPES = {"video/mp4", "video/webm"}
IMAGE_MAX_BYTES = 5 * 1024 * 1024
GIF_MAX_BYTES = 8 * 1024 * 1024
VIDEO_MAX_BYTES = 20 * 1024 * 1024
PRIMARY_ITEM_TYPES = {
    ItemType.NEW_FEATURE,
    ItemType.PRODUCT_IMPROVEMENT,
    ItemType.CLIENT_CUSTOMIZATION,
    ItemType.INTERNAL_CHANGE,
    ItemType.TECHNICAL_IMPROVEMENT,
    ItemType.BUGFIX,
    ItemType.CHANGE,
}
REVIEW_ITEM_TYPES = {
    ItemType.TECHNICAL_IMPROVEMENT,
    ItemType.BUGFIX,
    ItemType.INTERNAL_CHANGE,
    ItemType.PRODUCT_IMPROVEMENT,
}


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

    email = find_allowed_email(user_info, auth_settings)
    if not email:
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
            "publication_status": release.publication_status,
            "publication_statuses": PublicationStatus,
            "categories": list(ValueCategory),
            "ItemType": ItemType,
            "digest_visibilities": list(DigestVisibility),
            "status_labels": STATUS_LABELS,
            "category_labels": CATEGORY_LABELS,
            "item_type_labels": ITEM_TYPE_LABELS,
            "digest_visibility_labels": DIGEST_VISIBILITY_LABELS,
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
    object_version: Optional[int] = Form(None),
) -> Response:
    if _release_is_published(release_id):
        return _published_release_response(request, release_id)
    try:
        update_release_summary(release_id, summary, summary_status, expected_version=object_version)
    except StaleObjectError:
        return _stale_object_response("Summary уже изменил другой ревьюер. Обновите страницу перед сохранением.")
    reset_preview_after_review_change(release_id)
    updated_release = get_release(release_id)
    if _wants_json(request):
        return JSONResponse(
            {
                "ok": True,
                "message": "Summary успешно сохранено.",
                "summary_status": summary_status,
                "version": updated_release.version if updated_release else object_version,
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
    status: str = Form(ItemStatus.DRAFT.value),
    is_paid_feature: Optional[str] = Form(None),
    exclude_from_release: Optional[str] = Form(None),
    release_candidate_action: Optional[str] = Form(None),
    item_type: Optional[str] = Form(None),
    digest_visibility: Optional[str] = Form(None),
    object_version: Optional[int] = Form(None),
) -> Response:
    item = get_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Digest item not found")
    if _release_is_published(release_id):
        return _published_release_response(request, release_id)

    effective_status = ItemStatus.EXCLUDED.value if exclude_from_release == "on" else status
    effective_type = item.type
    effective_visibility = item.digest_visibility
    effective_category = category or None
    effective_description = description
    moved_to_primary = False

    if item.type == ItemType.RELEASE_CANDIDATE:
        if release_candidate_action in {item_type.value for item_type in REVIEW_ITEM_TYPES}:
            effective_type = ItemType(release_candidate_action)
            effective_status = ItemStatus.DRAFT.value
            effective_category = default_item_category(effective_type).value if default_item_category(effective_type) else None
            effective_description = ""
            moved_to_primary = True
        else:
            effective_status = ItemStatus.APPROVED.value
            effective_category = None
            effective_description = ""
    elif item.type in PRIMARY_ITEM_TYPES:
        if item_type in {review_type.value for review_type in REVIEW_ITEM_TYPES}:
            effective_type = ItemType(item_type)

    if digest_visibility:
        if digest_visibility not in {visibility.value for visibility in DigestVisibility}:
            return _bad_request_response(request, "Invalid digest_visibility value.")
        effective_visibility = DigestVisibility(digest_visibility)

    try:
        update_item(
            item_id=item_id,
            title=title,
            description=effective_description,
            category=effective_category,
            status=effective_status,
            is_paid_feature=is_paid_feature == "on",
            item_type=effective_type.value,
            digest_visibility=effective_visibility.value,
            expected_version=object_version,
        )
    except StaleObjectError:
        return _stale_object_response("Этот пункт уже изменил другой ревьюер. Обновите страницу перед сохранением.")
    reset_preview_after_review_change(release_id)
    updated_item = get_item(item_id)
    if _wants_json(request):
        return JSONResponse(
            {
                "ok": True,
                "message": "Пункт успешно сохранен.",
                "item_id": item_id,
                "status": effective_status,
                "item_type": effective_type.value,
                "digest_visibility": effective_visibility.value,
                "version": updated_item.version if updated_item else object_version,
                "reload": moved_to_primary,
            }
        )
    return RedirectResponse(url=f"/review/{release_id}", status_code=303)


@app.post("/review/{release_id}/bulk-exclude")
async def bulk_exclude_review_items(
    request: Request,
    release_id: str,
) -> Response:
    form = await request.form()
    item_ids = [str(item_id) for item_id in form.getlist("item_ids") if str(item_id).strip()]
    updated = bulk_exclude_items(release_id, item_ids)
    if _wants_json(request):
        return JSONResponse(
            {
                "ok": True,
                "message": f"Исключено задач: {updated}.",
                "item_ids": item_ids,
                "status": ItemStatus.EXCLUDED.value,
            }
        )
    return RedirectResponse(url=f"/review/{release_id}", status_code=303)


@app.post("/review/{release_id}/items/{item_id}/split")
def split_review_item(
    request: Request,
    release_id: str,
    item_id: str,
) -> Response:
    item = get_item(item_id)
    if item is None or item.release_id != release_id:
        raise HTTPException(status_code=404, detail="Digest item not found")
    split_items = split_epic_item(item_id)
    if not split_items:
        raise HTTPException(
            status_code=400,
            detail="Этот пункт нельзя разделить: нет сохраненных данных по исходным задачам.",
        )
    if _wants_json(request):
        return JSONResponse(
            {
                "ok": True,
                "message": f"Пункт разделен на задач: {len(split_items)}.",
                "reload": True,
            }
        )
    return RedirectResponse(url=f"/review/{release_id}", status_code=303)


@app.get("/review/{release_id}/locks")
def review_locks(request: Request, release_id: str) -> JSONResponse:
    owner_key, _ = _review_lock_owner(request)
    return JSONResponse({"ok": True, "locks": list_review_locks(release_id, owner_key)})


@app.get("/review/{release_id}/presence")
def review_presence(request: Request, release_id: str) -> JSONResponse:
    owner_key, _ = _review_lock_owner(request)
    return JSONResponse({"ok": True, "users": list_review_presence(release_id, owner_key)})


@app.post("/review/{release_id}/presence")
def touch_presence(request: Request, release_id: str) -> JSONResponse:
    owner_key, owner_name = _review_lock_owner(request)
    users = touch_review_presence(release_id, owner_key, owner_name)
    return JSONResponse({"ok": True, "users": users})


@app.post("/review/{release_id}/presence/release")
def release_presence(request: Request, release_id: str) -> JSONResponse:
    owner_key, _ = _review_lock_owner(request)
    release_review_presence(release_id, owner_key)
    return JSONResponse({"ok": True})


@app.post("/review/{release_id}/locks")
def claim_lock(
    request: Request,
    release_id: str,
    object_type: str = Form(...),
    object_id: str = Form(...),
    force: Optional[str] = Form(None),
) -> JSONResponse:
    _validate_lock_object(object_type, object_id, release_id)
    owner_key, owner_name = _review_lock_owner(request)
    lock = claim_review_lock(
        release_id=release_id,
        object_type=object_type,
        object_id=object_id,
        owner_key=owner_key,
        owner_name=owner_name,
        force=force == "true",
    )
    status_code = 200 if lock.get("claimed") else 409
    return JSONResponse({"ok": bool(lock.get("claimed")), "lock": lock}, status_code=status_code)


@app.post("/review/{release_id}/locks/release")
def release_lock(
    request: Request,
    release_id: str,
    object_type: str = Form(...),
    object_id: str = Form(...),
) -> JSONResponse:
    _validate_lock_object(object_type, object_id, release_id)
    owner_key, _ = _review_lock_owner(request)
    release_review_lock(release_id, object_type, object_id, owner_key)
    return JSONResponse({"ok": True})


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
    if _release_is_published(release_id):
        return _published_release_response(request, release_id)

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
    reset_preview_after_review_change(release_id)
    updated_item = get_item(item_id)
    if _wants_json(request):
        return JSONResponse(
            {
                "ok": True,
                "message": "Файл успешно загружен.",
                "item_id": item_id,
                "media_paths": updated_item.image_paths if updated_item else [],
                "version": updated_item.version if updated_item else item.version,
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
    if _release_is_published(release_id):
        return _published_release_response(request, release_id)
    if image_path not in item.image_paths:
        raise HTTPException(status_code=404, detail="Файл не найден")

    remove_item_image(item_id, image_path)
    reset_preview_after_review_change(release_id)
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
                "version": updated_item.version if updated_item else item.version,
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
    review_url = _build_absolute_app_url(app_settings.base_url, review_path)
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
    digest_url = _build_absolute_app_url(app_settings.base_url, f"/digest/{release_id}")
    notifier = TelegramNotifier(get_telegram_settings())
    notifier.send_message(build_digest_ready_message(release, approved_items, digest_url))
    return RedirectResponse(url=f"/review/{release_id}?flash=digest_notified", status_code=303)


@app.post("/review/{release_id}/prepare-digest-preview")
def prepare_digest_preview(request: Request, release_id: str) -> RedirectResponse:
    release = get_release(release_id)
    if release is None:
        raise HTTPException(status_code=404, detail="Release not found")
    if release.publication_status == PublicationStatus.PUBLISHED:
        return RedirectResponse(url=f"/review/{release_id}?flash=release_published", status_code=303)
    items = list_items(release_id)
    if digest_blockers(release, items):
        return RedirectResponse(url=f"/review/{release_id}?flash=digest_not_ready", status_code=303)
    _, owner_name = _review_lock_owner(request)
    update_release_publication_status(
        release_id,
        PublicationStatus.PREVIEW,
        note="Preview сформирован. Проверьте страницу перед публикацией.",
        preview_prepared_by=owner_name,
    )
    return RedirectResponse(url=f"/review/{release_id}/digest-preview", status_code=303)


@app.post("/review/{release_id}/return-digest-to-review")
def return_digest_to_review(release_id: str) -> RedirectResponse:
    release = get_release(release_id)
    if release is None:
        raise HTTPException(status_code=404, detail="Release not found")
    if release.publication_status == PublicationStatus.PUBLISHED:
        return RedirectResponse(url=f"/review/{release_id}?flash=release_published", status_code=303)
    update_release_publication_status(
        release_id,
        PublicationStatus.DRAFT,
        note="Preview отменен. Можно продолжить ревью и сформировать preview заново.",
    )
    return RedirectResponse(url=f"/review/{release_id}?flash=preview_returned", status_code=303)


@app.post("/review/{release_id}/publish-digest")
def publish_digest(request: Request, release_id: str) -> RedirectResponse:
    release = get_release(release_id)
    if release is None:
        raise HTTPException(status_code=404, detail="Release not found")
    if release.publication_status == PublicationStatus.PUBLISHED:
        return RedirectResponse(url=f"/review/{release_id}?flash=release_published", status_code=303)
    items = list_items(release_id)
    if release.publication_status != PublicationStatus.PREVIEW or digest_blockers(release, items):
        return RedirectResponse(url=f"/review/{release_id}?flash=preview_required", status_code=303)
    _, owner_name = _review_lock_owner(request)
    try:
        snapshot = build_published_digest_snapshot(release, items, owner_name, UPLOADS_DIR)
    except PublicationError:
        return RedirectResponse(url=f"/review/{release_id}?flash=publish_media_error", status_code=303)
    save_published_digest(snapshot)
    update_release_publication_status(
        release_id,
        PublicationStatus.PUBLISHED,
        note="Дайджест опубликован. Релиз закрыт для редактирования.",
        published_by=owner_name,
    )
    return RedirectResponse(url=f"/digest/{release_id}", status_code=303)


@app.get("/review/{release_id}/digest-preview", response_class=HTMLResponse)
def digest_preview(request: Request, release_id: str) -> HTMLResponse:
    release = get_release(release_id)
    if release is None:
        raise HTTPException(status_code=404, detail="Release not found")
    items = list_items(release_id)
    blockers = digest_blockers(release, items)
    if release.publication_status != PublicationStatus.PREVIEW or blockers:
        return templates.TemplateResponse(
            request,
            "digest.html",
            {
                "release": release,
                "page_mode": "preview_unavailable",
                "preparation_message": "Preview еще не сформирован",
                "sections": [],
                "metrics": {},
                "review_user": getattr(request.state, "review_session", {}).get("user"),
            },
        )
    content = build_live_digest_content(items)
    return templates.TemplateResponse(
        request,
        "digest.html",
        {
            "release": release,
            "page_mode": "preview",
            "sections": content["sections"],
            "metrics": content["metrics"],
            "review_user": getattr(request.state, "review_session", {}).get("user"),
        },
    )


@app.get("/digests", response_class=HTMLResponse)
def digest_archive(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "digests.html",
        {"digests": list_published_digests()},
    )


@app.get("/digest/{release_id}", response_class=HTMLResponse)
def final_digest(request: Request, release_id: str) -> HTMLResponse:
    release = get_release(release_id)
    if release is None:
        raise HTTPException(status_code=404, detail="Release not found")

    snapshot = get_published_digest(release_id)
    review_user = load_session(request, auth_settings).get("user")
    if snapshot is None:
        return templates.TemplateResponse(
            request,
            "digest.html",
            {
                "release": release,
                "page_mode": "preparation",
                "preparation_message": "Дайджест в подготовке",
                "sections": [],
                "metrics": {},
                "review_user": review_user,
            },
        )

    content = normalize_published_digest_content(snapshot.content)
    return templates.TemplateResponse(
        request,
        "digest.html",
        {
            "release": release,
            "snapshot": snapshot,
            "page_mode": "public",
            "sections": content["sections"],
            "metrics": content["metrics"],
            "review_user": review_user,
        },
    )


def _wants_json(request: Request) -> bool:
    return (
        request.headers.get("x-requested-with") == "XMLHttpRequest"
        or "application/json" in request.headers.get("accept", "")
    )


def _stale_object_response(message: str) -> Response:
    return JSONResponse(
        {"ok": False, "message": message, "detail": message},
        status_code=409,
    )


def _bad_request_response(request: Request, message: str) -> Response:
    if _wants_json(request):
        return JSONResponse(
            {"ok": False, "message": message, "detail": message},
            status_code=400,
        )
    raise HTTPException(status_code=400, detail=message)


def _published_release_response(request: Request, release_id: str) -> Response:
    message = "Этот релиз уже опубликован. Редактирование закрыто."
    if _wants_json(request):
        return JSONResponse({"ok": False, "message": message, "detail": message}, status_code=409)
    return RedirectResponse(url=f"/review/{release_id}?flash=release_published", status_code=303)


def _release_is_published(release_id: str) -> bool:
    release = get_release(release_id)
    return bool(release and release.publication_status == PublicationStatus.PUBLISHED)


def _review_lock_owner(request: Request) -> tuple[str, str]:
    user = getattr(request.state, "review_session", {}).get("user") or {}
    email = str(user.get("email") or "").strip().lower()
    name = str(user.get("name") or "").strip()
    owner_key = email or name or "unknown-reviewer"
    owner_name = name or email or "Ревьюер"
    return owner_key, owner_name


def _build_absolute_app_url(base_url: str, path: str) -> str:
    if not base_url:
        return path
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _validate_lock_object(object_type: str, object_id: str, release_id: str) -> None:
    if object_type == "summary":
        if object_id != release_id:
            raise HTTPException(status_code=400, detail="Некорректный объект блокировки.")
        return
    if object_type == "item":
        item = get_item(object_id)
        if item is None or item.release_id != release_id:
            raise HTTPException(status_code=404, detail="Digest item not found")
        return
    raise HTTPException(status_code=400, detail="Некорректный тип блокировки.")


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
