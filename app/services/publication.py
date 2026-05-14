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
    sections = [
        _section(
            "new_features",
            "Что нового",
            [item for item in approved_items if item.type == ItemType.NEW_FEATURE],
            include_tracker=False,
        ),
        _section(
            "changes",
            "Что стало удобнее",
            [item for item in approved_items if item.type == ItemType.CHANGE],
            include_tracker=False,
        ),
        _section(
            "support",
            "Исправления и технические улучшения",
            [item for item in approved_items if item.type in {ItemType.BUGFIX, ItemType.TECHNICAL_IMPROVEMENT}],
            include_tracker=True,
            collapsed=True,
        ),
    ]
    visible_sections = [section for section in sections if section["items"]]
    return {
        "sections": visible_sections,
        "metrics": {
            "items_count": sum(len(section["items"]) for section in visible_sections),
            "product_items_count": sum(
                len(section["items"])
                for section in visible_sections
                if section["id"] in {"new_features", "changes"}
            ),
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
        "items": [_item_payload(item, include_tracker) for item in items],
    }


def _item_payload(item: DigestItem, include_tracker: bool) -> dict:
    payload = {
        "title": item.title,
        "description": item.description,
        "module": item.module,
        "type": item.type.value,
        "value_category": item.category.value if item.category else "",
        "value_category_label": CLIENT_CATEGORY_LABELS.get(item.category, "") if item.category else "",
        "is_paid_feature": item.is_paid_feature,
        "media": [_media_payload(path) for path in item.image_paths],
    }
    if include_tracker:
        payload["tracker_urls"] = list(item.tracker_urls)
    return payload


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
