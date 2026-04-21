import json
import sqlite3
from typing import Iterable, List, Optional

from app.config import DB_PATH, ensure_directories
from app.models import (
    DigestItem,
    DigestRelease,
    GroupingMode,
    ItemStatus,
    ItemType,
    SummaryStatus,
    ValueCategory,
)


def connect() -> sqlite3.Connection:
    ensure_directories()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS digest_releases (
                id TEXT PRIMARY KEY,
                release_date TEXT NOT NULL,
                summary TEXT NOT NULL,
                summary_status TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS digest_items (
                id TEXT PRIMARY KEY,
                release_id TEXT NOT NULL,
                source_item_ids TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                module TEXT NOT NULL,
                type TEXT NOT NULL,
                category TEXT,
                status TEXT NOT NULL,
                is_paid_feature INTEGER NOT NULL DEFAULT 0,
                image_paths TEXT NOT NULL,
                tracker_urls TEXT NOT NULL,
                grouping_mode TEXT NOT NULL,
                FOREIGN KEY (release_id) REFERENCES digest_releases(id)
            );
            """
        )


def upsert_release(release: DigestRelease) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO digest_releases (id, release_date, summary, summary_status)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                release_date = excluded.release_date,
                summary = excluded.summary,
                summary_status = excluded.summary_status
            """,
            (release.id, release.release_date, release.summary, release.summary_status.value),
        )


def replace_release_items(release_id: str, items: Iterable[DigestItem]) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM digest_items WHERE release_id = ?", (release_id,))
        conn.executemany(
            """
            INSERT INTO digest_items (
                id, release_id, source_item_ids, title, description, module, type,
                category, status, is_paid_feature, image_paths, tracker_urls, grouping_mode
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item.id,
                    item.release_id,
                    json.dumps(item.source_item_ids),
                    item.title,
                    item.description,
                    item.module,
                    item.type.value,
                    item.category.value if item.category else None,
                    item.status.value,
                    1 if item.is_paid_feature else 0,
                    json.dumps(item.image_paths),
                    json.dumps(item.tracker_urls),
                    item.grouping_mode.value,
                )
                for item in items
            ],
        )


def get_release(release_id: str) -> Optional[DigestRelease]:
    with connect() as conn:
        row = conn.execute(
            "SELECT id, release_date, summary, summary_status FROM digest_releases WHERE id = ?",
            (release_id,),
        ).fetchone()
    if row is None:
        return None
    return DigestRelease(
        id=row["id"],
        release_date=row["release_date"],
        summary=row["summary"],
        summary_status=SummaryStatus(row["summary_status"]),
    )


def list_items(release_id: str) -> List[DigestItem]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, release_id, source_item_ids, title, description, module, type,
                   category, status, is_paid_feature, image_paths, tracker_urls, grouping_mode
            FROM digest_items
            WHERE release_id = ?
            ORDER BY module, title
            """,
            (release_id,),
        ).fetchall()
    return [_row_to_item(row) for row in rows]


def get_item(item_id: str) -> Optional[DigestItem]:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT id, release_id, source_item_ids, title, description, module, type,
                   category, status, is_paid_feature, image_paths, tracker_urls, grouping_mode
            FROM digest_items
            WHERE id = ?
            """,
            (item_id,),
        ).fetchone()
    if row is None:
        return None
    return _row_to_item(row)


def update_item(
    item_id: str,
    title: str,
    description: str,
    category: Optional[str],
    status: str,
    is_paid_feature: bool,
) -> None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE digest_items
            SET title = ?, description = ?, category = ?, status = ?, is_paid_feature = ?
            WHERE id = ?
            """,
            (title, description, category, status, 1 if is_paid_feature else 0, item_id),
        )


def update_release_summary(release_id: str, summary: str, summary_status: str) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE digest_releases SET summary = ?, summary_status = ? WHERE id = ?",
            (summary, summary_status, release_id),
        )


def add_item_image(item_id: str, image_path: str) -> None:
    item = get_item(item_id)
    if item is None:
        return
    image_paths = list(item.image_paths)
    image_paths.append(image_path)
    with connect() as conn:
        conn.execute(
            "UPDATE digest_items SET image_paths = ? WHERE id = ?",
            (json.dumps(image_paths), item_id),
        )


def remove_item_image(item_id: str, image_path: str) -> None:
    item = get_item(item_id)
    if item is None:
        return
    image_paths = [path for path in item.image_paths if path != image_path]
    with connect() as conn:
        conn.execute(
            "UPDATE digest_items SET image_paths = ? WHERE id = ?",
            (json.dumps(image_paths), item_id),
        )


def _row_to_item(row: sqlite3.Row) -> DigestItem:
    category = row["category"]
    return DigestItem(
        id=row["id"],
        release_id=row["release_id"],
        source_item_ids=json.loads(row["source_item_ids"]),
        title=row["title"],
        description=row["description"],
        module=row["module"],
        type=ItemType(row["type"]),
        category=ValueCategory(category) if category else None,
        status=ItemStatus(row["status"]),
        is_paid_feature=bool(row["is_paid_feature"]),
        image_paths=json.loads(row["image_paths"]),
        tracker_urls=json.loads(row["tracker_urls"]),
        grouping_mode=GroupingMode(row["grouping_mode"]),
    )
