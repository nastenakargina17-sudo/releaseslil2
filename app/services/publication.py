from pathlib import Path
import shutil
from typing import Iterable, Optional

from app.models import DigestItem, DigestRelease, ItemStatus, ItemType, PublishedDigest
from app.review_utils import CLIENT_CATEGORY_LABELS, is_video_media_path
from app.storage import _now_text


class PublicationError(Exception):
    pass


def build_live_digest_content(items: Iterable[DigestItem]) -> dict:
    approved_items = [
        item for item in items
        if item.status == ItemStatus.APPROVED and item.type != ItemType.RELEASE_CANDIDATE
    ]
    new_feature_items = [item for item in approved_items if item.type == ItemType.NEW_FEATURE]
    change_items = [item for item in approved_items if item.type == ItemType.CHANGE]
    support_items = [item for item in approved_items if item.type in {ItemType.BUGFIX, ItemType.TECHNICAL_IMPROVEMENT}]
    sections = [
        _section(
            "new_features",
            "Что нового",
            new_feature_items,
            include_tracker=False,
        ),
        _section(
            "changes",
            "Что стало удобнее",
            change_items,
            include_tracker=False,
        ),
        _section(
            "support",
            "Стабильность и техническая база",
            support_items,
            include_tracker=True,
            collapsed=True,
        ),
    ]
    visible_sections = [section for section in sections if section["items"]]
    return {
        "sections": visible_sections,
        "metrics": {
            "items_count": len(approved_items),
            "new_features_count": len(new_feature_items),
            "changes_count": len(change_items),
            "technical_count": len(support_items),
            "product_items_count": len(new_feature_items) + len(change_items),
        },
    }


def build_published_digest_snapshot(
    release: DigestRelease,
    items: Iterable[DigestItem],
    published_by: str,
    uploads_dir: Path,
) -> PublishedDigest:
    content = build_live_digest_content(items)
    content["sections"] = [
        _copy_section_media(section, release.id, uploads_dir)
        for section in content["sections"]
    ]
    return PublishedDigest(
        release_id=release.id,
        release_date=release.release_date,
        summary=release.summary,
        content=content,
        published_by=published_by,
        published_at=_now_text(),
    )


def _section(section_id: str, title: str, items: list[DigestItem], include_tracker: bool, collapsed: bool = False) -> dict:
    return {
        "id": section_id,
        "title": title,
        "collapsed": collapsed,
        "items_count": len(items),
        "items": [_item_payload(item, include_tracker) for item in items],
    }


def _item_payload(item: DigestItem, include_tracker: bool) -> dict:
    payload = {
        "title": item.title,
        "description": item.description,
        "module": item.module,
        "module_icon": _module_icon_key(item.module),
        "type": item.type.value,
        "value_category": item.category.value if item.category else "",
        "value_category_label": CLIENT_CATEGORY_LABELS.get(item.category, "") if item.category else "",
        "is_paid_feature": item.is_paid_feature,
        "media": [_media_payload(path) for path in item.image_paths],
    }
    if include_tracker:
        payload["tracker_urls"] = list(item.tracker_urls)
    return payload


def _module_icon_key(module: str) -> str:
    normalized = module.casefold()
    icon_keywords = (
        ("integrations", ("интеграц", "api", "маркетплейс", "marketplace")),
        ("hiring", ("подбор", "кандидат", "воронк")),
        ("analytics", ("аналит", "отчет", "дашборд", "метрик")),
        ("settings", ("настрой", "админ", "конфиг")),
        ("communications", ("коммуникац", "уведом", "telegram", "почт")),
        ("platform", ("ядро", "платформ", "core")),
    )
    for icon_key, keywords in icon_keywords:
        if any(keyword in normalized for keyword in keywords):
            return icon_key
    return "module"


def _media_payload(path: str) -> dict:
    return {
        "path": path,
        "kind": "video" if is_video_media_path(path) else "image",
    }


def _copy_section_media(section: dict, release_id: str, uploads_dir: Path) -> dict:
    copied_section = dict(section)
    copied_items = []
    for item in section["items"]:
        copied_item = dict(item)
        copied_item["media"] = [
            _copy_media(media, release_id, uploads_dir)
            for media in item["media"]
        ]
        copied_items.append(copied_item)
    copied_section["items"] = copied_items
    return copied_section


def _copy_media(media: dict, release_id: str, uploads_dir: Path) -> dict:
    source_path = _source_path_for_media(media["path"], uploads_dir)
    if source_path is None or not source_path.exists():
        raise PublicationError(f"Не удалось найти медиафайл для публикации: {media['path']}")
    target_dir = uploads_dir / "published" / release_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / source_path.name
    if target_path.exists():
        target_path = target_dir / f"{source_path.stem}-{_now_text()}{source_path.suffix}"
    shutil.copy2(source_path, target_path)
    return {
        "path": f"/uploads/published/{release_id}/{target_path.name}",
        "kind": media["kind"],
    }


def _source_path_for_media(public_path: str, uploads_dir: Path) -> Optional[Path]:
    if not public_path.startswith("/uploads/"):
        return None
    relative = public_path.replace("/uploads/", "", 1)
    if relative.startswith("published/"):
        return None
    return uploads_dir / relative
