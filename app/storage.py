import json
import sqlite3
import time
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

            CREATE TABLE IF NOT EXISTS review_locks (
                release_id TEXT NOT NULL,
                object_type TEXT NOT NULL,
                object_id TEXT NOT NULL,
                owner_key TEXT NOT NULL,
                owner_name TEXT NOT NULL,
                expires_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (release_id, object_type, object_id)
            );
            """
        )
        _ensure_column(conn, "digest_releases", "version", "INTEGER NOT NULL DEFAULT 1")
        _ensure_column(conn, "digest_releases", "updated_at", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "digest_items", "version", "INTEGER NOT NULL DEFAULT 1")
        _ensure_column(conn, "digest_items", "updated_at", "TEXT NOT NULL DEFAULT ''")


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _now_text() -> str:
    return str(int(time.time()))


def upsert_release(release: DigestRelease) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO digest_releases (id, release_date, summary, summary_status, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                release_date = excluded.release_date,
                summary = excluded.summary,
                summary_status = excluded.summary_status,
                version = digest_releases.version + 1,
                updated_at = excluded.updated_at
            """,
            (release.id, release.release_date, release.summary, release.summary_status.value, _now_text()),
        )


def replace_release_items(release_id: str, items: Iterable[DigestItem]) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM digest_items WHERE release_id = ?", (release_id,))
        conn.executemany(
            """
            INSERT INTO digest_items (
                id, release_id, source_item_ids, title, description, module, type,
                category, status, is_paid_feature, image_paths, tracker_urls, grouping_mode,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    _now_text(),
                )
                for item in items
            ],
        )


def get_release(release_id: str) -> Optional[DigestRelease]:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT id, release_date, summary, summary_status, version, updated_at
            FROM digest_releases
            WHERE id = ?
            """,
            (release_id,),
        ).fetchone()
    if row is None:
        return None
    return DigestRelease(
        id=row["id"],
        release_date=row["release_date"],
        summary=row["summary"],
        summary_status=SummaryStatus(row["summary_status"]),
        version=row["version"],
        updated_at=row["updated_at"],
    )


def list_items(release_id: str) -> List[DigestItem]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, release_id, source_item_ids, title, description, module, type,
                   category, status, is_paid_feature, image_paths, tracker_urls, grouping_mode,
                   version, updated_at
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
                   category, status, is_paid_feature, image_paths, tracker_urls, grouping_mode,
                   version, updated_at
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
    item_type: Optional[str] = None,
    expected_version: Optional[int] = None,
) -> None:
    with connect() as conn:
        sql = """
            UPDATE digest_items
            SET title = ?, description = ?, category = ?, status = ?, is_paid_feature = ?,
                type = COALESCE(?, type), version = version + 1, updated_at = ?
            WHERE id = ?
        """
        params = [title, description, category, status, 1 if is_paid_feature else 0, item_type, _now_text(), item_id]
        if expected_version is not None:
            sql += " AND version = ?"
            params.append(expected_version)
        cursor = conn.execute(
            sql,
            params,
        )
        if expected_version is not None and cursor.rowcount == 0:
            raise StaleObjectError("Digest item was updated by another reviewer")


def update_release_summary(
    release_id: str,
    summary: str,
    summary_status: str,
    expected_version: Optional[int] = None,
) -> None:
    with connect() as conn:
        sql = """
            UPDATE digest_releases
            SET summary = ?, summary_status = ?, version = version + 1, updated_at = ?
            WHERE id = ?
        """
        params = [summary, summary_status, _now_text(), release_id]
        if expected_version is not None:
            sql += " AND version = ?"
            params.append(expected_version)
        cursor = conn.execute(sql, params)
        if expected_version is not None and cursor.rowcount == 0:
            raise StaleObjectError("Release summary was updated by another reviewer")


class StaleObjectError(Exception):
    pass


def claim_review_lock(
    release_id: str,
    object_type: str,
    object_id: str,
    owner_key: str,
    owner_name: str,
    ttl_seconds: int = 90,
    force: bool = False,
) -> dict:
    now = time.time()
    expires_at = now + ttl_seconds
    with connect() as conn:
        _delete_expired_locks(conn, now)
        existing = conn.execute(
            """
            SELECT release_id, object_type, object_id, owner_key, owner_name, expires_at, updated_at
            FROM review_locks
            WHERE release_id = ? AND object_type = ? AND object_id = ?
            """,
            (release_id, object_type, object_id),
        ).fetchone()
        if existing and existing["owner_key"] != owner_key and not force:
            lock = _row_to_lock(existing, owner_key)
            lock["claimed"] = False
            return lock

        conn.execute(
            """
            INSERT INTO review_locks (
                release_id, object_type, object_id, owner_key, owner_name, expires_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(release_id, object_type, object_id) DO UPDATE SET
                owner_key = excluded.owner_key,
                owner_name = excluded.owner_name,
                expires_at = excluded.expires_at,
                updated_at = excluded.updated_at
            """,
            (release_id, object_type, object_id, owner_key, owner_name, expires_at, now),
        )
    return {
        "release_id": release_id,
        "object_type": object_type,
        "object_id": object_id,
        "owner_name": owner_name,
        "expires_at": expires_at,
        "is_mine": True,
        "claimed": True,
    }


def release_review_lock(
    release_id: str,
    object_type: str,
    object_id: str,
    owner_key: str,
) -> None:
    with connect() as conn:
        conn.execute(
            """
            DELETE FROM review_locks
            WHERE release_id = ? AND object_type = ? AND object_id = ? AND owner_key = ?
            """,
            (release_id, object_type, object_id, owner_key),
        )


def list_review_locks(release_id: str, owner_key: str) -> List[dict]:
    now = time.time()
    with connect() as conn:
        _delete_expired_locks(conn, now)
        rows = conn.execute(
            """
            SELECT release_id, object_type, object_id, owner_key, owner_name, expires_at, updated_at
            FROM review_locks
            WHERE release_id = ?
            ORDER BY updated_at DESC
            """,
            (release_id,),
        ).fetchall()
    return [_row_to_lock(row, owner_key) for row in rows]


def _delete_expired_locks(conn: sqlite3.Connection, now: float) -> None:
    conn.execute("DELETE FROM review_locks WHERE expires_at <= ?", (now,))


def _row_to_lock(row: sqlite3.Row, owner_key: str) -> dict:
    return {
        "release_id": row["release_id"],
        "object_type": row["object_type"],
        "object_id": row["object_id"],
        "owner_name": row["owner_name"],
        "expires_at": row["expires_at"],
        "is_mine": row["owner_key"] == owner_key,
    }


def add_item_image(item_id: str, image_path: str) -> None:
    item = get_item(item_id)
    if item is None:
        return
    image_paths = list(item.image_paths)
    image_paths.append(image_path)
    with connect() as conn:
        conn.execute(
            "UPDATE digest_items SET image_paths = ?, version = version + 1, updated_at = ? WHERE id = ?",
            (json.dumps(image_paths), _now_text(), item_id),
        )


def remove_item_image(item_id: str, image_path: str) -> None:
    item = get_item(item_id)
    if item is None:
        return
    image_paths = [path for path in item.image_paths if path != image_path]
    with connect() as conn:
        conn.execute(
            "UPDATE digest_items SET image_paths = ?, version = version + 1, updated_at = ? WHERE id = ?",
            (json.dumps(image_paths), _now_text(), item_id),
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
        version=row["version"],
        updated_at=row["updated_at"],
    )
