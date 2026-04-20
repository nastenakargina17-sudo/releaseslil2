from collections import defaultdict
from typing import Dict, Iterable, List
from uuid import uuid4

from app.models import (
    DigestItem,
    DigestRelease,
    GroupingMode,
    ItemType,
    SourceItem,
    SummaryStatus,
    ValueCategory,
)
from app.review_utils import default_item_status, sanitize_digest_title, should_collect_description


def build_release(source_items: Iterable[SourceItem], release_id: str, release_date: str) -> tuple[DigestRelease, List[DigestItem]]:
    items = list(source_items)
    grouped: Dict[str, List[SourceItem]] = defaultdict(list)
    singles: List[SourceItem] = []

    for item in items:
        if item.type in {ItemType.NEW_FEATURE, ItemType.CHANGE} and item.parent_epic_id:
            grouped[item.parent_epic_id].append(item)
        else:
            singles.append(item)

    digest_items: List[DigestItem] = []

    for epic_id, epic_items in grouped.items():
        digest_items.append(_build_epic_digest_item(release_id, epic_id, epic_items))

    for source_item in singles:
        digest_items.append(_build_single_digest_item(release_id, source_item))

    release = DigestRelease(
        id=release_id,
        release_date=release_date,
        summary=generate_summary(digest_items),
        summary_status=SummaryStatus.DRAFT,
    )
    return release, digest_items


def generate_summary(items: List[DigestItem]) -> str:
    new_features = sum(1 for item in items if item.type == ItemType.NEW_FEATURE)
    changes = sum(1 for item in items if item.type == ItemType.CHANGE)
    modules = sorted({item.module for item in items})
    modules_text = ", ".join(modules[:3]) if modules else "ключевых модулях"
    return (
        f"В этом релизе сфокусировались на развитии модулей {modules_text}: "
        f"подготовили {new_features} новых фич и {changes} изменений, которые помогают "
        "сделать ежедневную работу понятнее и удобнее."
    )


def _build_epic_digest_item(release_id: str, epic_id: str, epic_items: List[SourceItem]) -> DigestItem:
    primary = epic_items[0]
    item_type = primary.type
    title = sanitize_digest_title(primary.parent_epic_title or primary.title)
    description = _narrative_for_feature_or_change(item_type, primary.module, title)
    category = _default_category(item_type)
    return DigestItem(
        id=f"digest-{uuid4().hex[:10]}",
        release_id=release_id,
        source_item_ids=[item.id for item in epic_items],
        title=title,
        description=description,
        module=primary.module,
        type=item_type,
        category=category,
        status=default_item_status(item_type),
        tracker_urls=[item.url for item in epic_items],
        grouping_mode=GroupingMode.EPIC_GROUP,
    )


def _build_single_digest_item(release_id: str, source_item: SourceItem) -> DigestItem:
    title = sanitize_digest_title(source_item.title)
    description = ""
    category = None
    if should_collect_description(source_item.type):
        description = _narrative_for_feature_or_change(source_item.type, source_item.module, title)
        category = _default_category(source_item.type)
    return DigestItem(
        id=f"digest-{uuid4().hex[:10]}",
        release_id=release_id,
        source_item_ids=[source_item.id],
        title=title,
        description=description,
        module=source_item.module,
        type=source_item.type,
        category=category,
        status=default_item_status(source_item.type),
        tracker_urls=[source_item.url],
        grouping_mode=GroupingMode.SINGLE_TASK,
    )


def _narrative_for_feature_or_change(item_type: ItemType, module: str, title: str) -> str:
    if item_type == ItemType.NEW_FEATURE:
        return (
            f"В модуле {module} добавили новое улучшение вокруг сценария \"{title}\", "
            "чтобы пользователям было проще выполнять ежедневные операции и быстрее проходить рабочие шаги."
        )
    return (
        f"В модуле {module} обновили сценарий \"{title}\", чтобы сделать поведение системы понятнее "
        "и сократить лишние действия в ежедневной работе."
    )


def _default_category(item_type: ItemType) -> ValueCategory:
    if item_type == ItemType.NEW_FEATURE:
        return ValueCategory.DAILY_WORK_CONVENIENCE
    return ValueCategory.CLARITY_TRANSPARENCY
