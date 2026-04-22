import re
from typing import Iterable, Optional

from app.models import DigestItem, DigestRelease, ItemStatus, ItemType, SummaryStatus, ValueCategory


CATEGORY_LABELS = {
    ValueCategory.TIME_SAVING: "Экономия времени",
    ValueCategory.ERROR_REDUCTION: "Снижение ошибок",
    ValueCategory.CLARITY_TRANSPARENCY: "Понятность и прозрачность",
    ValueCategory.DAILY_WORK_CONVENIENCE: "Удобство ежедневной работы",
    ValueCategory.BETTER_CONTROL: "Больше контроля",
    ValueCategory.LESS_COMMUNICATION_OVERHEAD: "Меньше лишней коммуникации",
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

ITEM_TYPE_LABELS = {
    ItemType.NEW_FEATURE: "Новая фича",
    ItemType.CHANGE: "Изменение",
    ItemType.BUGFIX: "Багфикс",
    ItemType.TECHNICAL_IMPROVEMENT: "Техническая доработка",
    ItemType.RELEASE_CANDIDATE: "Кандидат из \"Нет\"",
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


def default_item_status(item_type: ItemType) -> ItemStatus:
    if item_type in DESCRIPTIONLESS_ITEM_TYPES:
        return ItemStatus.APPROVED
    return ItemStatus.DRAFT


def default_item_category(item_type: ItemType) -> Optional[ValueCategory]:
    if item_type == ItemType.NEW_FEATURE:
        return ValueCategory.DAILY_WORK_CONVENIENCE
    if item_type == ItemType.CHANGE:
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
