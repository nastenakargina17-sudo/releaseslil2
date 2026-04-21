from app.clients.confluence import ConfluenceAPIClient
from app.clients.tracker import TrackerAPIClient
from app.config import get_confluence_settings, get_openai_settings, get_telegram_settings, get_tracker_settings
from app.notifications.telegram import (
    TelegramNotificationError,
    TelegramNotifier,
    build_release_import_message,
)
from app.services.ingest import build_release
from app.services.openai_generation import OpenAIReleaseCopyGenerator
from app.storage import replace_release_items, upsert_release


def import_release_from_apis(release_id: str) -> None:
    tracker_client = TrackerAPIClient(get_tracker_settings())
    confluence_client = ConfluenceAPIClient(get_confluence_settings())
    copy_generator = OpenAIReleaseCopyGenerator(get_openai_settings())

    source_items = tracker_client.fetch_release_items(release_id)
    release_date = confluence_client.fetch_release_date(release_id)
    release, digest_items = build_release(
        source_items,
        release_id,
        release_date,
        copy_generator=copy_generator,
    )

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
