"""
SQLite-backed storage for uploader internal state.

Responsibilities:
- Initialize database in the central data dir (e.g., ~/.imxup/imxup.db)
- Provide CRUD for galleries and images used by the queue
- Migrate legacy QSettings queue to SQLite on first use
- Keep operations short and safe for concurrent readers with WAL

Note: All heavy work should be triggered from worker/manager threads, not GUI.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Iterable, List, Optional, Tuple


# Access central data dir path from shared helper
from imxup import get_central_store_base_path


def _get_db_path() -> str:
    base_dir = get_central_store_base_path()
    return os.path.join(base_dir, "imxup.db")


def _connect(db_path: Optional[str] = None) -> sqlite3.Connection:
    path = db_path or _get_db_path()
    conn = sqlite3.connect(path, timeout=5, isolation_level=None)  # autocommit by default
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS galleries (
            id INTEGER PRIMARY KEY,
            path TEXT NOT NULL UNIQUE,
            name TEXT,
            status TEXT NOT NULL CHECK (status IN ('scanning','ready','queued','uploading','paused','incomplete','completed','failed')),
            added_ts INTEGER NOT NULL,
            finished_ts INTEGER,
            template TEXT,
            total_images INTEGER DEFAULT 0,
            uploaded_images INTEGER DEFAULT 0,
            total_size INTEGER DEFAULT 0,
            scan_complete INTEGER DEFAULT 0,
            uploaded_bytes INTEGER DEFAULT 0,
            final_kibps REAL DEFAULT 0.0,
            gallery_id TEXT,
            gallery_url TEXT,
            insertion_order INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS galleries_status_idx ON galleries(status);
        CREATE INDEX IF NOT EXISTS galleries_added_idx ON galleries(added_ts DESC);
        CREATE INDEX IF NOT EXISTS galleries_order_idx ON galleries(insertion_order);

        CREATE TABLE IF NOT EXISTS images (
            id INTEGER PRIMARY KEY,
            gallery_fk INTEGER NOT NULL REFERENCES galleries(id) ON DELETE CASCADE,
            filename TEXT NOT NULL,
            size_bytes INTEGER DEFAULT 0,
            width INTEGER DEFAULT 0,
            height INTEGER DEFAULT 0,
            uploaded_ts INTEGER,
            url TEXT,
            thumb_url TEXT,
            UNIQUE(gallery_fk, filename)
        );
        CREATE INDEX IF NOT EXISTS images_gallery_idx ON images(gallery_fk);

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value_text TEXT
        );
        """
    )


class QueueStore:
    """Storage facade for queue state in SQLite."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path or _get_db_path()
        # Ensure directory exists
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        # Initialize schema once
        with _connect(self.db_path) as conn:
            _ensure_schema(conn)
        # Single writer background pool for non-blocking persistence
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="queue-store")

    # ------------------------------ Migration ------------------------------
    def _is_migrated(self, conn: sqlite3.Connection) -> bool:
        cur = conn.execute("SELECT value_text FROM settings WHERE key = ?", ("queue_migrated_v1",))
        row = cur.fetchone()
        return bool(row and str(row[0]) == "1")

    def _mark_migrated(self, conn: sqlite3.Connection) -> None:
        conn.execute("INSERT OR REPLACE INTO settings(key, value_text) VALUES(?, ?)", ("queue_migrated_v1", "1"))

    def migrate_from_qsettings_if_needed(self, qsettings: Any) -> None:
        """One-time migration from existing QSettings queue list to SQLite.

        qsettings is expected to be a QSettings instance scoped to the old queue,
        providing .value("queue_items", []) as a list of dicts.
        """
        try:
            with _connect(self.db_path) as conn:
                _ensure_schema(conn)
                if self._is_migrated(conn):
                    return
                legacy = qsettings.value("queue_items", []) if qsettings else []
                if not legacy:
                    self._mark_migrated(conn)
                    return
                conn.execute("BEGIN")
                try:
                    for item in legacy:
                        self._upsert_gallery_row(conn, item)
                        # Persist uploaded_files and uploaded_images_data if present
                        uploaded_files = item.get('uploaded_files', []) or []
                        uploaded_images_data = item.get('uploaded_images_data', []) or []
                        # Map fname -> data for convenient URL extraction
                        data_map = {}
                        for tup in uploaded_images_data:
                            try:
                                fname, data = tup
                                data_map[fname] = data or {}
                            except Exception:
                                continue
                        # Insert filenames (and urls if available)
                        cur = conn.execute("SELECT id FROM galleries WHERE path = ?", (item.get('path', ''),))
                        row = cur.fetchone()
                        if not row:
                            continue
                        g_id = int(row[0])
                        for fname in uploaded_files:
                            d = data_map.get(fname, {})
                            conn.execute(
                                """
                                INSERT OR IGNORE INTO images(gallery_fk, filename, size_bytes, width, height, uploaded_ts, url, thumb_url)
                                VALUES(?,?,?,?,?,?,?,?)
                                """,
                                (
                                    g_id,
                                    fname,
                                    int(d.get('size_bytes', 0) or 0),
                                    int(d.get('width', 0) or 0),
                                    int(d.get('height', 0) or 0),
                                    None,
                                    d.get('image_url') or d.get('url') or "",
                                    d.get('thumb_url') or "",
                                ),
                            )
                    self._mark_migrated(conn)
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
        except Exception:
            # Best-effort migration; do not block app startup
            pass

    # ----------------------------- CRUD helpers ----------------------------
    def _upsert_gallery_row(self, conn: sqlite3.Connection, item: Dict[str, Any]) -> None:
        # Normalize names
        path = item.get('path', '')
        name = item.get('name')
        status = item.get('status', 'ready')
        added_ts = int((item.get('added_time') or 0) or 0)
        finished_ts = int((item.get('finished_time') or 0) or 0) or None
        template = item.get('template_name')
        total_images = int(item.get('total_images', 0) or 0)
        uploaded_images = int(item.get('uploaded_images', 0) or 0)
        total_size = int(item.get('total_size', 0) or 0)
        scan_complete = 1 if bool(item.get('scan_complete', False)) else 0
        uploaded_bytes = int(item.get('uploaded_bytes', 0) or 0)
        final_kibps = float(item.get('final_kibps', 0.0) or 0.0)
        gallery_id = item.get('gallery_id')
        gallery_url = item.get('gallery_url')
        insertion_order = int(item.get('insertion_order', 0) or 0)

        conn.execute(
            """
            INSERT INTO galleries(
                path, name, status, added_ts, finished_ts, template, total_images, uploaded_images,
                total_size, scan_complete, uploaded_bytes, final_kibps, gallery_id, gallery_url, insertion_order
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(path) DO UPDATE SET
                name=excluded.name,
                status=excluded.status,
                added_ts=excluded.added_ts,
                finished_ts=excluded.finished_ts,
                template=excluded.template,
                total_images=excluded.total_images,
                uploaded_images=excluded.uploaded_images,
                total_size=excluded.total_size,
                scan_complete=excluded.scan_complete,
                uploaded_bytes=excluded.uploaded_bytes,
                final_kibps=excluded.final_kibps,
                gallery_id=excluded.gallery_id,
                gallery_url=excluded.gallery_url,
                insertion_order=excluded.insertion_order
            """,
            (
                path, name, status, added_ts, finished_ts, template, total_images, uploaded_images,
                total_size, scan_complete, uploaded_bytes, final_kibps, gallery_id, gallery_url, insertion_order,
            ),
        )

    def bulk_upsert(self, items: Iterable[Dict[str, Any]]) -> None:
        try:
            with _connect(self.db_path) as conn:
                _ensure_schema(conn)
                conn.execute("BEGIN")
                try:
                    for it in items:
                        self._upsert_gallery_row(conn, it)
                        # Optionally persist per-image resume info when provided
                        uploaded_files = it.get('uploaded_files') or []
                        uploaded_images_data = it.get('uploaded_images_data') or []
                        if uploaded_files:
                            # Lookup gallery id for images insertion
                            cur = conn.execute("SELECT id FROM galleries WHERE path = ?", (it.get('path', ''),))
                            row = cur.fetchone()
                            if not row:
                                continue
                            g_id = int(row[0])
                            data_map = {}
                            for tup in uploaded_images_data:
                                try:
                                    fname, data = tup
                                    data_map[fname] = data or {}
                                except Exception:
                                    continue
                            for fname in uploaded_files:
                                d = data_map.get(fname, {})
                                conn.execute(
                                    """
                                    INSERT OR IGNORE INTO images(gallery_fk, filename, size_bytes, width, height, uploaded_ts, url, thumb_url)
                                    VALUES(?,?,?,?,?,?,?,?)
                                    """,
                                    (
                                        g_id,
                                        fname,
                                        int(d.get('size_bytes', 0) or 0),
                                        int(d.get('width', 0) or 0),
                                        int(d.get('height', 0) or 0),
                                        None,
                                        d.get('image_url') or d.get('url') or "",
                                        d.get('thumb_url') or "",
                                    ),
                                )
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
        except Exception:
            # Log via print to avoid importing logging from GUI thread
            print("ERROR: bulk_upsert failed", flush=True)

    def bulk_upsert_async(self, items: Iterable[Dict[str, Any]]) -> None:
        # Snapshot to avoid mutation while persisting
        items_list = [dict(it) for it in items]
        self._executor.submit(self.bulk_upsert, items_list)

    def load_all_items(self) -> List[Dict[str, Any]]:
        with _connect(self.db_path) as conn:
            _ensure_schema(conn)
            cur = conn.execute(
                """
                SELECT path, name, status, added_ts, finished_ts, template, total_images, uploaded_images,
                       total_size, scan_complete, uploaded_bytes, final_kibps, gallery_id, gallery_url, insertion_order
                FROM galleries
                ORDER BY insertion_order ASC, added_ts ASC
                """
            )
            rows = cur.fetchall()
            items: List[Dict[str, Any]] = []
            for r in rows:
                item: Dict[str, Any] = {
                    'path': r[0],
                    'name': r[1],
                    'status': r[2],
                    'added_time': int(r[3] or 0),
                    'finished_time': int(r[4] or 0) or None,
                    'template_name': r[5],
                    'total_images': int(r[6] or 0),
                    'uploaded_images': int(r[7] or 0),
                    'total_size': int(r[8] or 0),
                    'scan_complete': bool(r[9] or 0),
                    'uploaded_bytes': int(r[10] or 0),
                    'final_kibps': float(r[11] or 0.0),
                    'gallery_id': r[12] or "",
                    'gallery_url': r[13] or "",
                    'insertion_order': int(r[14] or 0),
                }
                # Rehydrate resume helpers from images table (filenames only)
                try:
                    gcur = conn.execute("SELECT id FROM galleries WHERE path = ?", (item['path'],))
                    grow = gcur.fetchone()
                    if grow:
                        gid = int(grow[0])
                        icur = conn.execute("SELECT filename FROM images WHERE gallery_fk = ?", (gid,))
                        files = [row[0] for row in icur.fetchall()]
                        item['uploaded_files'] = files
                except Exception:
                    item['uploaded_files'] = []
                items.append(item)
            return items

    def delete_by_status(self, statuses: Iterable[str]) -> int:
        with _connect(self.db_path) as conn:
            _ensure_schema(conn)
            sql = "DELETE FROM galleries WHERE status IN (%s)" % ",".join(["?"] * len(list(statuses)))
            cur = conn.execute(sql, tuple(statuses))
            return cur.rowcount if hasattr(cur, 'rowcount') else 0

    def delete_by_paths(self, paths: Iterable[str]) -> int:
        paths = list(paths)
        if not paths:
            return 0
        with _connect(self.db_path) as conn:
            _ensure_schema(conn)
            sql = "DELETE FROM galleries WHERE path IN (%s)" % ",".join(["?"] * len(paths))
            cur = conn.execute(sql, tuple(paths))
            return cur.rowcount if hasattr(cur, 'rowcount') else 0

    def update_insertion_orders(self, ordered_paths: List[str]) -> None:
        if not ordered_paths:
            return
        with _connect(self.db_path) as conn:
            _ensure_schema(conn)
            conn.execute("BEGIN")
            try:
                for idx, path in enumerate(ordered_paths, 1):
                    conn.execute("UPDATE galleries SET insertion_order = ? WHERE path = ?", (idx, path))
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def clear_all(self) -> None:
        with _connect(self.db_path) as conn:
            _ensure_schema(conn)
            conn.execute("DELETE FROM images")
            conn.execute("DELETE FROM galleries")
            conn.execute("DELETE FROM settings WHERE key = 'queue_migrated_v1'")


