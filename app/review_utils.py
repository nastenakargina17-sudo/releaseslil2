import re
from typing import Iterable, Optional

from app.models import DigestItem, DigestRelease, DigestVisibility, ItemStatus, ItemType, SummaryStatus, ValueCategory


CATEGORY_LABELS = {
    ValueCategory.TIME_SAVING: "Экономия времени",
    ValueCategory.ERROR_REDUCTION: "Снижение ошибок",
    ValueCategory.CLARITY_TRANSPARENCY: "Понятность и прозрачность",
    ValueCategory.DAILY_WORK_CONVENIENCE: "Удобство ежедневной работы",
    ValueCategory.BETTER_CONTROL: "Больше контроля",
    ValueCategory.LESS_COMMUNICATION_OVERHEAD: "Меньше лишней коммуникации",
}

CLIENT_CATEGORY_LABELS = {
    ValueCategory.TIME_SAVING: "Экономия времени",
    ValueCategory.ERROR_REDUCTION: "Меньше ошибок",
    ValueCategory.CLARITY_TRANSPARENCY: "Больше прозрачности",
    ValueCategory.DAILY_WORK_CONVENIENCE: "Удобнее в ежедневной работе",
    ValueCategory.BETTER_CONTROL: "Больше контроля",
    ValueCategory.LESS_COMMUNICATION_OVERHEAD: "Меньше ручных согласований",
}

STATUS_LABELS = {
    ItemStatus.DRAFT: "Черновик",
    ItemStatus.REVIEWED: "На ревью",
    ItemStatus.APPROVED: "Подтверждено",
    ItemStatus.EXCLUDED: "Исключено",
    SummaryStatus.DRAFT: "Черновик",
    SummaryStatus.REVIEWED: "На ревью",
    SummaryStatus.APPROVED: "Подтверждено",
}

DIGEST_VISIBILITY_LABELS = {
    DigestVisibility.PUBLIC: "Публичный дайджест",
    DigestVisibility.INTERNAL: "Внутренний обзор",
}

ITEM_TYPE_LABELS = {
    ItemType.NEW_FEATURE: "Новый функционал",
    ItemType.CHANGE: "Продуктовое улучшение",
    ItemType.PRODUCT_IMPROVEMENT: "Продуктовое улучшение",
    ItemType.CLIENT_CUSTOMIZATION: "Клиентская доработка",
    ItemType.INTERNAL_CHANGE: "Внутреннее изменение",
    ItemType.BUGFIX: "Исправление",
    ItemType.TECHNICAL_IMPROVEMENT: "Техническая итерация",
    ItemType.RELEASE_CANDIDATE: "Задачи из \"Нет\"",
}

DESCRIPTIONLESS_ITEM_TYPES = {
    ItemType.BUGFIX,
    ItemType.TECHNICAL_IMPROVEMENT,
    ItemType.RELEASE_CANDIDATE,
}
TRACKER_TITLE_PREFIX_RE = re.compile(r"^[A-Z][A-Z0-9_]*-\d+\s*[:\-–]?\s*")


def sanitize_digest_title(title: str) -> str:
    cleaned = TRACKER_TITLE_PREFIX_RE.sub("", (title or "").strip(), count=1).strip()
    return cleaned or (title or "").strip()


def normalize_tracker_issue_url(issue_key: str, fallback_url: str) -> str:
    normalized_key = (issue_key or "").strip()
    if normalized_key:
        return f"https://tracker.yandex.ru/{normalized_key}"
    return (fallback_url or "").strip()


def is_video_media_path(path: str) -> bool:
    return (path or "").lower().split("?", 1)[0].endswith((".mp4", ".webm"))


def default_item_status(item_type: ItemType) -> ItemStatus:
    if item_type in DESCRIPTIONLESS_ITEM_TYPES:
        return ItemStatus.APPROVED
    return ItemStatus.DRAFT


def default_digest_visibility(item_type: ItemType) -> DigestVisibility:
    if item_type in {ItemType.NEW_FEATURE, ItemType.CHANGE, ItemType.PRODUCT_IMPROVEMENT}:
        return DigestVisibility.PUBLIC
    return DigestVisibility.INTERNAL


def default_item_category(item_type: ItemType) -> Optional[ValueCategory]:
    if item_type == ItemType.NEW_FEATURE:
        return ValueCategory.DAILY_WORK_CONVENIENCE
    if item_type in {
        ItemType.CHANGE,
        ItemType.PRODUCT_IMPROVEMENT,
        ItemType.CLIENT_CUSTOMIZATION,
        ItemType.INTERNAL_CHANGE,
    }:
        return ValueCategory.CLARITY_TRANSPARENCY
    return None


def should_collect_description(item_type: ItemType) -> bool:
    return item_type not in DESCRIPTIONLESS_ITEM_TYPES


def digest_blockers(release: DigestRelease, items: Iterable[DigestItem]) -> list[str]:
    blockers: list[str] = []
    if release.summary_status != SummaryStatus.APPROVED:
        blockers.append("Summary не подтвержден")
    for item in items:
        if item.type == ItemType.RELEASE_CANDIDATE:
            continue
        if item.status not in {ItemStatus.APPROVED, ItemStatus.EXCLUDED}:
            blockers.append(item.id)
    return blockers
