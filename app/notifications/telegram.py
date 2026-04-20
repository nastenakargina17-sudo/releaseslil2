import httpx
from typing import Optional

from app.config import TelegramSettings
from app.models import DigestItem, DigestRelease, ItemStatus, ItemType, SummaryStatus


class TelegramNotificationError(RuntimeError):
    pass


class TelegramNotifier:
    def __init__(self, settings: TelegramSettings) -> None:
        self.settings = settings

    def send_message(self, text: str) -> None:
        if not self.settings.bot_token or not self.settings.chat_id:
            raise TelegramNotificationError("Telegram settings are not configured")
        url = f"https://api.telegram.org/bot{self.settings.bot_token}/sendMessage"
        payload = {
            "chat_id": self.settings.chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
        with httpx.Client(timeout=30.0) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()


def build_release_import_message(release_id: str, release_date: str, item_count: int) -> str:
    return (
        f"Импортирован релиз {release_id}\n"
        f"Плановая дата релиза: {release_date}\n"
        f"Подготовлено пунктов для ревью: {item_count}"
    )


def build_review_status_message(
    release: DigestRelease,
    items: list[DigestItem],
    review_url: Optional[str] = None,
) -> str:
    approved = sum(1 for item in items if item.status == ItemStatus.APPROVED)
    excluded = sum(1 for item in items if item.status == ItemStatus.EXCLUDED)
    reviewed = sum(1 for item in items if item.status == ItemStatus.REVIEWED)
    draft = sum(1 for item in items if item.status == ItemStatus.DRAFT)
    total = len(items)
    lines = [
        f"Ревью релиза {release.id}",
        f"Плановая дата релиза: {release.release_date}",
        f"Summary: {release.summary_status.value}",
        f"Пункты: всего {total}, approved {approved}, excluded {excluded}, reviewed {reviewed}, draft {draft}",
    ]
    if review_url:
        lines.append(f"Открыть ревью: {review_url}")
    return "\n".join(lines)


def build_digest_ready_message(
    release: DigestRelease,
    items: list[DigestItem],
    digest_url: Optional[str] = None,
) -> str:
    new_features = sum(1 for item in items if item.type == ItemType.NEW_FEATURE)
    changes = sum(1 for item in items if item.type == ItemType.CHANGE)
    bugfixes = sum(1 for item in items if item.type == ItemType.BUGFIX)
    technical = sum(1 for item in items if item.type == ItemType.TECHNICAL_IMPROVEMENT)
    lines = [
        f"Дайджест по релизу {release.id} готов",
        f"Плановая дата релиза: {release.release_date}",
        f"Summary: {release.summary_status.value}",
        f"Новые фичи: {new_features}",
        f"Изменения: {changes}",
        f"Багфиксы: {bugfixes}",
        f"Технические доработки: {technical}",
    ]
    narrative_items = [
        item for item in items if item.type in {ItemType.NEW_FEATURE, ItemType.CHANGE}
    ]
    if narrative_items:
        lines.append("")
        lines.append("Коротко по содержанию:")
        for item in narrative_items[:5]:
            paid = " [платно]" if item.is_paid_feature else ""
            lines.append(f"- {item.title}{paid} ({item.module})")
    if digest_url:
        lines.append(f"Открыть digest: {digest_url}")
    return "\n".join(lines)


def release_is_ready_for_digest(release: DigestRelease, items: list[DigestItem]) -> bool:
    if release.summary_status != SummaryStatus.APPROVED:
        return False
    return all(item.status in {ItemStatus.APPROVED, ItemStatus.EXCLUDED} for item in items)
