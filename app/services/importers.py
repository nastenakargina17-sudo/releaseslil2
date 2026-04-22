from app.clients.confluence import ConfluenceAPIClient
from app.clients.tracker import TrackerAPIClient
from app.config import get_confluence_settings, get_openai_settings, get_telegram_settings, get_tracker_settings
from app.notifications.telegram import (
    TelegramNotificationError,
    TelegramNotifier,
    build_release_import_message,
)
from app.services.ingest import build_release, generate_fallback_item_description, generate_summary
from app.services.openai_generation import OpenAIReleaseCopyGenerator
from app.storage import get_release, list_items, replace_release_items, upsert_release


def import_release_from_apis(release_id: str, preserve_existing_copy: bool = True) -> None:
    tracker_client = TrackerAPIClient(get_tracker_settings())
    confluence_client = ConfluenceAPIClient(get_confluence_settings())
    copy_generator = OpenAIReleaseCopyGenerator(get_openai_settings())
    existing_release = get_release(release_id)
    existing_items = list_items(release_id)

    source_items = tracker_client.fetch_release_items(release_id)
    release_date = confluence_client.fetch_release_date(release_id)
    release, digest_items = build_release(
        source_items,
        release_id,
        release_date,
        copy_generator=copy_generator,
    )
    if preserve_existing_copy:
        _preserve_existing_copy_when_ai_falls_back(existing_release, existing_items, release, digest_items)

    upsert_release(release)
    replace_release_items(release_id, digest_items)

    telegram_settings = get_telegram_settings()
    if telegram_settings.bot_token and telegram_settings.chat_id:
        notifier = TelegramNotifier(telegram_settings)
        import_message = build_release_import_message(release_id, release_date, len(digest_items))
        if telegram_settings.import_image_path:
            try:
                notifier.send_photo(
                    telegram_settings.import_image_path,
                    caption=import_message,
                )
                return
            except TelegramNotificationError:
                pass
        notifier.send_message(import_message)


def _preserve_existing_copy_when_ai_falls_back(existing_release, existing_items, release, digest_items) -> None:
    fallback_summary = generate_summary(digest_items)
    if existing_release and release.summary == fallback_summary and existing_release.summary != fallback_summary:
        release.summary = existing_release.summary

    existing_by_signature = {
        _item_signature(item): item
        for item in existing_items
    }
    for item in digest_items:
        existing_item = existing_by_signature.get(_item_signature(item))
        if existing_item is None:
            continue
        if item.description == _fallback_description_for_item(item) and existing_item.description != item.description:
            item.description = existing_item.description


def _item_signature(item) -> tuple:
    return (
        item.grouping_mode.value,
        item.type.value,
        tuple(sorted(item.source_item_ids)),
    )


def _fallback_description_for_item(item) -> str:
    if item.type.value == "new_feature":
        return generate_fallback_item_description(
            item.type,
            item.module,
            item.title,
            item.category,
            [],
        )
    if item.type.value == "change":
        return generate_fallback_item_description(
            item.type,
            item.module,
            item.title,
            item.category,
            [],
        )
    return item.description
