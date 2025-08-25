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
import json


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
    # Create core schema first (without tab_name initially)
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
            insertion_order INTEGER DEFAULT 0,
            failed_files TEXT
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

        CREATE TABLE IF NOT EXISTS unnamed_galleries (
            gallery_id TEXT PRIMARY KEY,
            intended_name TEXT NOT NULL,
            discovered_ts INTEGER DEFAULT (strftime('%s', 'now'))
        );
        CREATE INDEX IF NOT EXISTS unnamed_galleries_ts_idx ON unnamed_galleries(discovered_ts DESC);

        CREATE TABLE IF NOT EXISTS tabs (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            tab_type TEXT NOT NULL CHECK (tab_type IN ('system','user')),
            display_order INTEGER NOT NULL DEFAULT 0,
            color_hint TEXT,
            created_ts INTEGER DEFAULT (strftime('%s', 'now')),
            updated_ts INTEGER DEFAULT (strftime('%s', 'now')),
            is_active INTEGER DEFAULT 1
        );
        CREATE INDEX IF NOT EXISTS tabs_display_order_idx ON tabs(display_order ASC, created_ts ASC);
        CREATE INDEX IF NOT EXISTS tabs_type_idx ON tabs(tab_type);
        CREATE INDEX IF NOT EXISTS tabs_active_idx ON tabs(is_active, display_order ASC);
        """
    )
    # Run migrations after core schema creation (this adds tab_name column and indexes)
    _run_migrations(conn)

def _run_migrations(conn: sqlite3.Connection) -> None:
    """Run database migrations to add new columns/features."""
    try:
        # Migration 1: Add failed_files column if it doesn't exist
        cursor = conn.execute("PRAGMA table_info(galleries)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'failed_files' not in columns:
            print("Adding failed_files column to galleries table...")
            conn.execute("ALTER TABLE galleries ADD COLUMN failed_files TEXT")
            print("+ Added failed_files column")
            
        # Migration 2: Add tab_name column if it doesn't exist
        cursor = conn.execute("PRAGMA table_info(galleries)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'tab_name' not in columns:
            print("Adding tab_name column to galleries table...")
            conn.execute("ALTER TABLE galleries ADD COLUMN tab_name TEXT DEFAULT 'Main'")
            print("+ Added tab_name column")
            
            # Add indexes for tab_name after column creation
            print("Adding tab_name indexes...")
            conn.execute("CREATE INDEX IF NOT EXISTS galleries_tab_idx ON galleries(tab_name)")
            conn.execute("CREATE INDEX IF NOT EXISTS galleries_tab_status_idx ON galleries(tab_name, status)")
            print("+ Added tab_name indexes")
            
        # Migration 3: Move unnamed galleries from config file to database
        _migrate_unnamed_galleries_to_db(conn)
        
        # Migration 4: Replace tab_name with tab_id for referential integrity
        cursor = conn.execute("PRAGMA table_info(galleries)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'tab_name' in columns and 'tab_id' not in columns:
            print("Migrating from tab_name to tab_id for referential integrity...")
            
            # Add tab_id column
            conn.execute("ALTER TABLE galleries ADD COLUMN tab_id INTEGER")
            
            # Get all tab names and their IDs
            cursor = conn.execute("SELECT id, name FROM tabs")
            tab_name_to_id = {name: id for id, name in cursor.fetchall()}
            
            # Update tab_id based on existing tab_name
            for tab_name, tab_id in tab_name_to_id.items():
                conn.execute(
                    "UPDATE galleries SET tab_id = ? WHERE tab_name = ?",
                    (tab_id, tab_name)
                )
            
            # Set default tab_id for any galleries without a valid tab assignment
            main_tab_id = tab_name_to_id.get('Main', 1)  # Fallback to ID 1 if Main not found
            conn.execute(
                "UPDATE galleries SET tab_id = ? WHERE tab_id IS NULL",
                (main_tab_id,)
            )
            
            # Add indexes for tab_id
            conn.execute("CREATE INDEX IF NOT EXISTS galleries_tab_id_idx ON galleries(tab_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS galleries_tab_id_status_idx ON galleries(tab_id, status)")
            
            # Note: We keep tab_name column for now for backwards compatibility
            # but tab_id becomes the primary reference
            print("+ Migrated to tab_id-based references")
        
        # Migration 4: Initialize default tabs
        _initialize_default_tabs(conn)
            
    except Exception as e:
        print(f"Warning: Migration failed: {e}")
        # Continue anyway - the app should still work


def _initialize_default_tabs(conn: sqlite3.Connection) -> None:
    """Initialize default system tabs (one-time migration)."""
    try:
        # Check if we've already initialized default tabs
        cursor = conn.execute("SELECT COUNT(*) FROM tabs WHERE tab_type = 'system'")
        existing_count = cursor.fetchone()[0]
        
        if existing_count > 0:
            # Already initialized
            return
            
        print("Initializing default system tabs...")
        
        # Default system tabs with proper ordering
        default_tabs = [
            ('Main', 'system', 0, None),
            ('Archive', 'system', 1000, '#666666'),  # Gray hint for archived items
        ]
        
        # Insert default tabs
        for name, tab_type, display_order, color_hint in default_tabs:
            conn.execute(
                "INSERT OR IGNORE INTO tabs (name, tab_type, display_order, color_hint) VALUES (?, ?, ?, ?)",
                (name, tab_type, display_order, color_hint)
            )
        
        print(f"+ Initialized {len(default_tabs)} default system tabs")
        
    except Exception as e:
        print(f"Warning: Could not initialize default tabs: {e}")
        # Continue anyway - not critical for app function


def _migrate_unnamed_galleries_to_db(conn: sqlite3.Connection) -> None:
    """Migrate unnamed galleries from config file to database (one-time migration)."""
    try:
        # Check if we've already migrated
        cursor = conn.execute("SELECT COUNT(*) FROM unnamed_galleries")
        existing_count = cursor.fetchone()[0]
        
        if existing_count > 0:
            # Already migrated
            return
            
        # Try to read from config file
        import configparser
        import os
        
        # Use the same config path logic as the original function
        from imxup import get_config_path
        config_file = get_config_path()
        
        if not os.path.exists(config_file):
            return  # No config file, nothing to migrate
            
        config = configparser.ConfigParser()
        config.read(config_file)
        
        if 'UNNAMED_GALLERIES' not in config:
            return  # No unnamed galleries section
            
        unnamed_galleries = dict(config['UNNAMED_GALLERIES'])
        if not unnamed_galleries:
            return  # Empty section
            
        print(f"Migrating {len(unnamed_galleries)} unnamed galleries from config file to database...")
        
        # Insert all unnamed galleries into database
        for gallery_id, intended_name in unnamed_galleries.items():
            conn.execute(
                "INSERT OR REPLACE INTO unnamed_galleries (gallery_id, intended_name) VALUES (?, ?)",
                (gallery_id, intended_name)
            )
        
        print(f"+ Migrated {len(unnamed_galleries)} unnamed galleries to database")
        
        # Optional: Remove from config file after successful migration
        # (Commented out for safety - users can manually clean up)
        # if 'UNNAMED_GALLERIES' in config:
        #     config.remove_section('UNNAMED_GALLERIES')
        #     with open(config_file, 'w') as f:
        #         config.write(f)
        
    except Exception as e:
        print(f"Warning: Could not migrate unnamed galleries: {e}")
        # Continue anyway - not critical for app function


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
        failed_files = json.dumps(item.get('failed_files', []))
        tab_name = item.get('tab_name', 'Main')
        print(f"DEBUG: _upsert_gallery_row called with tab_name='{tab_name}' for path='{item.get('path', 'unknown')}'", flush=True)
        
        # Get tab_id for the tab_name
        cursor = conn.execute("SELECT id FROM tabs WHERE name = ? AND is_active = 1", (tab_name,))
        row = cursor.fetchone()
        tab_id = row[0] if row else None
        
        # If tab doesn't exist, default to Main tab
        if tab_id is None:
            print(f"DEBUG: Tab lookup failed for '{tab_name}', checking available tabs...")
            cursor = conn.execute("SELECT name, is_active FROM tabs ORDER BY name")
            all_tabs = cursor.fetchall()
            print(f"DEBUG: Available tabs: {all_tabs}")
            cursor = conn.execute("SELECT id FROM tabs WHERE name = 'Main' AND is_active = 1")
            row = cursor.fetchone()
            tab_id = row[0] if row else 1  # Fallback to ID 1
            print(f"DEBUG: Falling back to Main tab (id={tab_id}) from original tab '{tab_name}'")
            tab_name = 'Main'

        # Check if tab_id column exists
        cursor = conn.execute("PRAGMA table_info(galleries)")
        columns = [column[1] for column in cursor.fetchall()]
        has_tab_id = 'tab_id' in columns
        
        if has_tab_id:
            # New schema with tab_id column
            conn.execute(
                """
                INSERT INTO galleries(
                    path, name, status, added_ts, finished_ts, template, total_images, uploaded_images,
                    total_size, scan_complete, uploaded_bytes, final_kibps, gallery_id, gallery_url, insertion_order, failed_files, tab_name, tab_id
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
                    insertion_order=excluded.insertion_order,
                    failed_files=excluded.failed_files,
                    tab_name=excluded.tab_name,
                    tab_id=excluded.tab_id
                """,
                (
                    path, name, status, added_ts, finished_ts, template, total_images, uploaded_images,
                    total_size, scan_complete, uploaded_bytes, final_kibps, gallery_id, gallery_url, insertion_order, failed_files, tab_name, tab_id
                ),
            )
        else:
            # Old schema without tab_id column
            conn.execute(
                """
                INSERT INTO galleries(
                    path, name, status, added_ts, finished_ts, template, total_images, uploaded_images,
                    total_size, scan_complete, uploaded_bytes, final_kibps, gallery_id, gallery_url, insertion_order, failed_files, tab_name
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
                    insertion_order=excluded.insertion_order,
                    failed_files=excluded.failed_files,
                    tab_name=excluded.tab_name
                """,
                (
                    path, name, status, added_ts, finished_ts, template, total_images, uploaded_images,
                    total_size, scan_complete, uploaded_bytes, final_kibps, gallery_id, gallery_url, insertion_order, failed_files, tab_name
                ),
            )

    def bulk_upsert(self, items: Iterable[Dict[str, Any]]) -> None:
        try:
            with _connect(self.db_path) as conn:
                _ensure_schema(conn)
                conn.execute("BEGIN")
                try:
                    for it in items:
                        try:
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
                        except Exception as item_error:
                            print(f"Warning: Failed to upsert item {it.get('path', 'unknown')}: {item_error}")
                            # Continue with other items instead of failing completely
                            continue
                    conn.execute("COMMIT")
                except Exception as tx_error:
                    conn.execute("ROLLBACK")
                    print(f"Transaction failed: {tx_error}")
                    raise
        except Exception as e:
            # Log via print to avoid importing logging from GUI thread
            print(f"ERROR: bulk_upsert failed: {e}", flush=True)
            import traceback
            traceback.print_exc()

    def bulk_upsert_async(self, items: Iterable[Dict[str, Any]]) -> None:
        # Snapshot to avoid mutation while persisting
        items_list = [dict(it) for it in items]
        self._executor.submit(self.bulk_upsert, items_list)

    def load_all_items(self) -> List[Dict[str, Any]]:
        with _connect(self.db_path) as conn:
            _ensure_schema(conn)
            
            # Check if failed_files column exists
            cursor = conn.execute("PRAGMA table_info(galleries)")
            columns = [column[1] for column in cursor.fetchall()]
            has_failed_files = 'failed_files' in columns
            
            if has_failed_files:
                # New schema with failed_files column
                # Check if tab_id column exists
                has_tab_id = 'tab_id' in columns
                if has_tab_id:
                    cur = conn.execute(
                        """
                        SELECT path, name, status, added_ts, finished_ts, template, total_images, uploaded_images,
                               total_size, scan_complete, uploaded_bytes, final_kibps, gallery_id, gallery_url, insertion_order, failed_files, tab_name, tab_id
                        FROM galleries
                        ORDER BY insertion_order ASC, added_ts ASC
                        """
                    )
                else:
                    cur = conn.execute(
                        """
                        SELECT path, name, status, added_ts, finished_ts, template, total_images, uploaded_images,
                               total_size, scan_complete, uploaded_bytes, final_kibps, gallery_id, gallery_url, insertion_order, failed_files, tab_name
                        FROM galleries
                        ORDER BY insertion_order ASC, added_ts ASC
                        """
                    )
            else:
                # Old schema without failed_files column
                # Check if tab_id column exists
                has_tab_id = 'tab_id' in columns
                if has_tab_id:
                    cur = conn.execute(
                        """
                        SELECT path, name, status, added_ts, finished_ts, template, total_images, uploaded_images,
                               total_size, scan_complete, uploaded_bytes, final_kibps, gallery_id, gallery_url, insertion_order, tab_name, tab_id
                        FROM galleries
                        ORDER BY insertion_order ASC, added_ts ASC
                        """
                    )
                else:
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
                if has_failed_files:
                    if has_tab_id:
                        # New schema with tab_id - 18 columns
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
                            'failed_files': json.loads(r[15]) if r[15] else [],
                            'tab_name': r[16] or 'Main',
                            'tab_id': int(r[17] or 1),
                        }
                    else:
                        # New schema without tab_id - 17 columns
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
                            'failed_files': json.loads(r[15]) if r[15] else [],
                            'tab_name': r[16] or 'Main',
                            'tab_id': 1,  # Default to Main tab
                        }
                else:
                    if has_tab_id:
                        # Old schema with tab_id - 16 columns
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
                            'failed_files': [],  # Default empty list for old schema
                            'tab_name': r[15] or 'Main',
                            'tab_id': int(r[16] or 1),
                        }
                    else:
                        # Old schema without tab_id - 15 columns
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
                            'failed_files': [],  # Default empty list for old schema
                            'tab_name': 'Main',  # Default tab for old schema
                            'tab_id': 1,  # Default to Main tab
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

    # Unnamed Galleries Database Methods
    def get_unnamed_galleries(self) -> Dict[str, str]:
        """Get all unnamed galleries from database (much faster than config file)."""
        with _connect(self.db_path) as conn:
            _ensure_schema(conn)
            cursor = conn.execute("SELECT gallery_id, intended_name FROM unnamed_galleries ORDER BY discovered_ts DESC")
            return dict(cursor.fetchall())

    def add_unnamed_gallery(self, gallery_id: str, intended_name: str) -> None:
        """Add an unnamed gallery to the database."""
        with _connect(self.db_path) as conn:
            _ensure_schema(conn)
            conn.execute(
                "INSERT OR REPLACE INTO unnamed_galleries (gallery_id, intended_name) VALUES (?, ?)",
                (gallery_id, intended_name)
            )

    def remove_unnamed_gallery(self, gallery_id: str) -> bool:
        """Remove an unnamed gallery from the database. Returns True if removed."""
        with _connect(self.db_path) as conn:
            _ensure_schema(conn)
            cursor = conn.execute("DELETE FROM unnamed_galleries WHERE gallery_id = ?", (gallery_id,))
            return cursor.rowcount > 0

    def clear_unnamed_galleries(self) -> int:
        """Clear all unnamed galleries. Returns count of removed items."""
        with _connect(self.db_path) as conn:
            _ensure_schema(conn)
            cursor = conn.execute("DELETE FROM unnamed_galleries")
            return cursor.rowcount if hasattr(cursor, 'rowcount') else 0

    # Tab Management Methods
    def get_all_tabs(self) -> List[Dict[str, Any]]:
        """Get all tabs ordered by display_order. Returns list of tab dictionaries."""
        with _connect(self.db_path) as conn:
            _ensure_schema(conn)
            cursor = conn.execute("""
                SELECT id, name, tab_type, display_order, color_hint, created_ts, updated_ts, is_active
                FROM tabs 
                WHERE is_active = 1 
                ORDER BY display_order ASC, created_ts ASC
            """)
            
            tabs = []
            for row in cursor.fetchall():
                tabs.append({
                    'id': row[0],
                    'name': row[1],
                    'tab_type': row[2],
                    'display_order': row[3],
                    'color_hint': row[4],
                    'created_ts': row[5],
                    'updated_ts': row[6],
                    'is_active': bool(row[7]),
                })
            return tabs

    def get_tab_gallery_counts(self) -> Dict[str, int]:
        """Get gallery counts for each tab. Optimized for fast lookups with single query.
        
        Returns: Dict mapping tab_name -> gallery_count
        """
        with _connect(self.db_path) as conn:
            _ensure_schema(conn)
            
            # Single optimized query using LEFT JOIN - much faster than UNION
            cursor = conn.execute("""
                SELECT 
                    t.name as tab_name,
                    COUNT(g.path) as gallery_count
                FROM tabs t
                LEFT JOIN galleries g ON t.name = COALESCE(g.tab_name, 'Main')
                WHERE t.is_active = 1
                GROUP BY t.name, t.display_order
                ORDER BY t.display_order ASC, t.name ASC
            """)
            
            # Convert to dictionary
            counts = {}
            for row in cursor.fetchall():
                tab_name, count = row[0], row[1]
                counts[tab_name] = count
            
            # Handle edge case: if no tabs exist yet, ensure Main tab is included
            if not counts:
                counts['Main'] = 0
                
            return counts

    def load_items_by_tab(self, tab_name: str) -> List[Dict[str, Any]]:
        """Load galleries filtered by tab name. Uses tab_id for fast filtering.
        
        Args:
            tab_name: Name of the tab to filter by
            
        Returns: List of gallery items belonging to the specified tab
        """
        with _connect(self.db_path) as conn:
            _ensure_schema(conn)
            
            # Get tab_id for the given tab_name
            cursor = conn.execute("SELECT id FROM tabs WHERE name = ? AND is_active = 1", (tab_name,))
            row = cursor.fetchone()
            if not row:
                return []  # Tab doesn't exist, return empty list
            
            tab_id = row[0]
            
            # Check if failed_files and tab_id columns exist
            cursor = conn.execute("PRAGMA table_info(galleries)")
            columns = [column[1] for column in cursor.fetchall()]
            has_failed_files = 'failed_files' in columns
            has_tab_id = 'tab_id' in columns
            
            if has_failed_files:
                # New schema with failed_files column
                if has_tab_id:
                    # Use tab_id for precise filtering
                    cur = conn.execute(
                        """
                        SELECT path, name, status, added_ts, finished_ts, template, total_images, uploaded_images,
                               total_size, scan_complete, uploaded_bytes, final_kibps, gallery_id, gallery_url, insertion_order, failed_files, tab_name
                        FROM galleries
                        WHERE COALESCE(tab_id, (SELECT id FROM tabs WHERE name = 'Main' LIMIT 1)) = ?
                        ORDER BY insertion_order ASC, added_ts ASC
                        """,
                        (tab_id,)
                    )
                else:
                    # Fallback to tab_name filtering
                    cur = conn.execute(
                        """
                        SELECT path, name, status, added_ts, finished_ts, template, total_images, uploaded_images,
                               total_size, scan_complete, uploaded_bytes, final_kibps, gallery_id, gallery_url, insertion_order, failed_files, tab_name
                        FROM galleries
                        WHERE COALESCE(tab_name, 'Main') = ?
                        ORDER BY insertion_order ASC, added_ts ASC
                        """,
                        (tab_name,)
                    )
            else:
                # Old schema without failed_files column
                if has_tab_id:
                    # Use tab_id for precise filtering
                    cur = conn.execute(
                        """
                        SELECT path, name, status, added_ts, finished_ts, template, total_images, uploaded_images,
                               total_size, scan_complete, uploaded_bytes, final_kibps, gallery_id, gallery_url, insertion_order
                        FROM galleries
                        WHERE COALESCE(tab_id, (SELECT id FROM tabs WHERE name = 'Main' LIMIT 1)) = ?
                        ORDER BY insertion_order ASC, added_ts ASC
                        """,
                        (tab_id,)
                    )
                else:
                    # Fallback to tab_name filtering
                    cur = conn.execute(
                        """
                        SELECT path, name, status, added_ts, finished_ts, template, total_images, uploaded_images,
                               total_size, scan_complete, uploaded_bytes, final_kibps, gallery_id, gallery_url, insertion_order
                        FROM galleries
                        WHERE COALESCE(tab_name, 'Main') = ?
                        ORDER BY insertion_order ASC, added_ts ASC
                        """,
                        (tab_name,)
                    )
            
            rows = cur.fetchall()
            items: List[Dict[str, Any]] = []
            for r in rows:
                if has_failed_files:
                    # New schema - 17 columns (with tab_name)
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
                        'failed_files': json.loads(r[15]) if r[15] else [],
                        'tab_name': r[16] or 'Main',
                    }
                else:
                    # Old schema - 15 columns
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
                        'failed_files': [],  # Default empty list for old schema
                        'tab_name': tab_name,  # Use the filtered tab name
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

    def create_tab(self, name: str, color_hint: Optional[str] = None, display_order: Optional[int] = None) -> int:
        """Create a new user tab.
        
        Args:
            name: Tab name (must be unique)
            color_hint: Optional hex color code (e.g., '#FF5733')
            display_order: Order position (default: auto-calculated)
            
        Returns: Tab ID of created tab
        
        Raises:
            sqlite3.IntegrityError: If tab name already exists
        """
        with _connect(self.db_path) as conn:
            _ensure_schema(conn)
            
            try:
                # Auto-calculate display_order if not provided
                if display_order is None:
                    cursor = conn.execute("SELECT MAX(display_order) FROM tabs WHERE tab_type = 'user'")
                    max_order = cursor.fetchone()[0] or 0
                    display_order = max_order + 10  # Leave room for reordering
                
                # Insert new tab (always user type for public API)
                cursor = conn.execute(
                    "INSERT INTO tabs (name, tab_type, display_order, color_hint) VALUES (?, 'user', ?, ?)",
                    (name, display_order, color_hint)
                )
                return cursor.lastrowid
                
            except sqlite3.IntegrityError as e:
                if "UNIQUE constraint failed" in str(e):
                    raise sqlite3.IntegrityError(f"Tab name '{name}' already exists") from e
                raise

    def update_tab(self, tab_id: int, name: Optional[str] = None, display_order: Optional[int] = None, color_hint: Optional[str] = None) -> bool:
        """Update an existing tab.
        
        Args:
            tab_id: ID of tab to update
            name: New name (optional)
            display_order: New display order (optional)
            color_hint: New color hint (optional)
            
        Returns: True if tab was updated, False if not found
        
        Raises:
            sqlite3.IntegrityError: If name already exists
            ValueError: If tab_id is invalid or no updates provided
        """
        if tab_id <= 0:
            raise ValueError("tab_id must be a positive integer")
            
        with _connect(self.db_path) as conn:
            _ensure_schema(conn)
            
            try:
                updates = []
                params = []
                
                if name is not None:
                    # Check if it's a system tab - don't allow renaming system tabs
                    cursor = conn.execute("SELECT tab_type FROM tabs WHERE id = ?", (tab_id,))
                    row = cursor.fetchone()
                    if not row:
                        return False
                    if row[0] == 'system':
                        raise ValueError("Cannot rename system tabs")
                    
                    updates.append("name = ?")
                    params.append(name)
                    
                if display_order is not None:
                    updates.append("display_order = ?")
                    params.append(display_order)
                    
                if color_hint is not None:
                    updates.append("color_hint = ?")
                    params.append(color_hint)
                
                if not updates:
                    raise ValueError("No updates provided")
                    
                updates.append("updated_ts = strftime('%s', 'now')")
                params.append(tab_id)
                
                # If renaming the tab, also update galleries assigned to this tab
                if name is not None:
                    # Get the current tab name before updating
                    cursor = conn.execute("SELECT name FROM tabs WHERE id = ?", (tab_id,))
                    row = cursor.fetchone()
                    if row:
                        old_name = row[0]
                        
                        # Update the tab
                        sql = f"UPDATE tabs SET {', '.join(updates)} WHERE id = ?"
                        cursor = conn.execute(sql, params)
                        
                        if cursor.rowcount > 0:
                            # Update all galleries assigned to this tab (both tab_name and tab_id if exists)
                            # Check if tab_id column exists first
                            cursor = conn.execute("PRAGMA table_info(galleries)")
                            columns = [column[1] for column in cursor.fetchall()]
                            has_tab_id = 'tab_id' in columns
                            
                            if has_tab_id:
                                # Update tab_name for galleries with this tab_id
                                conn.execute(
                                    "UPDATE galleries SET tab_name = ? WHERE tab_id = ?",
                                    (name, tab_id)
                                )
                            else:
                                # Fallback to tab_name-based update
                                conn.execute(
                                    "UPDATE galleries SET tab_name = ? WHERE tab_name = ?",
                                    (name, old_name)
                                )
                            return True
                        return False
                else:
                    # No name change, just update other fields
                    sql = f"UPDATE tabs SET {', '.join(updates)} WHERE id = ?"
                    cursor = conn.execute(sql, params)
                    return cursor.rowcount > 0
                
            except sqlite3.IntegrityError as e:
                if "UNIQUE constraint failed" in str(e):
                    raise sqlite3.IntegrityError(f"Tab name '{name}' already exists") from e
                raise

    def delete_tab(self, tab_id: int, reassign_to: str = 'Main') -> Tuple[bool, int]:
        """Delete a tab and reassign its galleries to another tab.
        
        Args:
            tab_id: ID of tab to delete
            reassign_to: Tab name to reassign galleries to (default: 'Main')
            
        Returns: Tuple of (success, galleries_reassigned_count)
        
        Raises:
            ValueError: If trying to delete a system tab or invalid tab_id
        """
        if tab_id <= 0:
            raise ValueError("tab_id must be a positive integer")
            
        with _connect(self.db_path) as conn:
            _ensure_schema(conn)
            conn.execute("BEGIN")
            
            try:
                # Get tab info before deletion
                cursor = conn.execute("SELECT name, tab_type FROM tabs WHERE id = ?", (tab_id,))
                row = cursor.fetchone()
                if not row:
                    conn.execute("ROLLBACK")
                    return False, 0
                
                tab_name, tab_type = row[0], row[1]
                
                # Prevent deletion of system tabs
                if tab_type == 'system':
                    conn.execute("ROLLBACK")
                    raise ValueError(f"Cannot delete system tab '{tab_name}'")
                
                # Verify destination tab exists
                cursor = conn.execute("SELECT COUNT(*) FROM tabs WHERE name = ? AND is_active = 1", (reassign_to,))
                if cursor.fetchone()[0] == 0:
                    conn.execute("ROLLBACK")
                    raise ValueError(f"Destination tab '{reassign_to}' does not exist")
                
                # Get reassign_to tab_id
                cursor = conn.execute("SELECT id FROM tabs WHERE name = ? AND is_active = 1", (reassign_to,))
                reassign_row = cursor.fetchone()
                reassign_tab_id = reassign_row[0] if reassign_row else None
                
                # Reassign galleries to new tab using tab_id if available
                cursor = conn.execute("PRAGMA table_info(galleries)")
                columns = [column[1] for column in cursor.fetchall()]
                has_tab_id = 'tab_id' in columns
                
                if has_tab_id and reassign_tab_id:
                    # Use tab_id for reassignment
                    cursor = conn.execute(
                        "UPDATE galleries SET tab_id = ?, tab_name = ? WHERE tab_id = ?",
                        (reassign_tab_id, reassign_to, tab_id)
                    )
                else:
                    # Fallback to tab_name-based reassignment
                    cursor = conn.execute(
                        "UPDATE galleries SET tab_name = ? WHERE tab_name = ?",
                        (reassign_to, tab_name)
                    )
                galleries_moved = cursor.rowcount if hasattr(cursor, 'rowcount') else 0
                
                # Delete the tab
                cursor = conn.execute("DELETE FROM tabs WHERE id = ?", (tab_id,))
                tab_deleted = cursor.rowcount > 0 if hasattr(cursor, 'rowcount') else False
                
                if tab_deleted:
                    conn.execute("COMMIT")
                    return True, galleries_moved
                else:
                    conn.execute("ROLLBACK")
                    return False, 0
                    
            except Exception as e:
                conn.execute("ROLLBACK")
                if isinstance(e, ValueError):
                    raise  # Re-raise ValueError with original message
                print(f"Error deleting tab {tab_id}: {e}")
                return False, 0

    def move_galleries_to_tab(self, gallery_paths: List[str], new_tab_name: str) -> int:
        """Move multiple galleries to a different tab.
        
        Args:
            gallery_paths: List of gallery paths to move
            new_tab_name: Name of destination tab
            
        Returns: Number of galleries moved
        
        Raises:
            ValueError: If new_tab_name is invalid or gallery_paths is empty
        """
        if not gallery_paths:
            return 0
            
        if not new_tab_name or not new_tab_name.strip():
            raise ValueError("new_tab_name cannot be empty")
        
        # Strip count from tab name (e.g., "Archive (0)" -> "Archive")
        import re
        clean_tab_name = re.sub(r'\s*\(\d+\)$', '', new_tab_name.strip())
            
        with _connect(self.db_path) as conn:
            _ensure_schema(conn)
            conn.execute("BEGIN")
            
            try:
                # Get destination tab ID using clean tab name
                cursor = conn.execute("SELECT id FROM tabs WHERE name = ? AND is_active = 1", (clean_tab_name,))
                row = cursor.fetchone()
                if not row:
                    conn.execute("ROLLBACK")
                    raise ValueError(f"Destination tab '{clean_tab_name}' does not exist")
                
                tab_id = row[0]
                
                # Build parameterized query for bulk update using tab_id and clean name
                placeholders = ','.join(['?'] * len(gallery_paths))
                sql = f"UPDATE galleries SET tab_id = ?, tab_name = ? WHERE path IN ({placeholders})"
                params = [tab_id, clean_tab_name] + gallery_paths
                
                cursor = conn.execute(sql, params)
                moved_count = cursor.rowcount if hasattr(cursor, 'rowcount') else 0
                
                conn.execute("COMMIT")
                return moved_count
                
            except Exception as e:
                print(f"DEBUG: Exception type: {type(e)}")
                print(f"DEBUG: Exception message: {e}")
                print(f"DEBUG: Gallery paths: {gallery_paths}")
                print(f"DEBUG: New tab name: '{new_tab_name}' -> clean: '{clean_tab_name}'")
                import traceback
                traceback.print_exc()
                conn.execute("ROLLBACK")
                if isinstance(e, ValueError):
                    raise  # Re-raise ValueError with original message
                print(f"Error moving galleries to tab '{new_tab_name}': {e}")
                return 0

    def reorder_tabs(self, tab_orders: List[Tuple[int, int]]) -> None:
        """Reorder tabs by updating display_order for multiple tabs.
        
        Args:
            tab_orders: List of (tab_id, new_display_order) tuples
            
        Raises:
            ValueError: If tab_orders is invalid or contains invalid tab IDs
        """
        if not tab_orders:
            return
            
        # Validate input
        for tab_id, new_order in tab_orders:
            if not isinstance(tab_id, int) or tab_id <= 0:
                raise ValueError(f"Invalid tab_id: {tab_id}")
            if not isinstance(new_order, int) or new_order < 0:
                raise ValueError(f"Invalid display_order: {new_order}")
            
        with _connect(self.db_path) as conn:
            _ensure_schema(conn)
            conn.execute("BEGIN")
            
            try:
                updated_count = 0
                for tab_id, new_order in tab_orders:
                    cursor = conn.execute(
                        "UPDATE tabs SET display_order = ?, updated_ts = strftime('%s', 'now') WHERE id = ?",
                        (new_order, tab_id)
                    )
                    if cursor.rowcount == 0:
                        print(f"Warning: Tab ID {tab_id} not found during reordering")
                    else:
                        updated_count += 1
                        
                conn.execute("COMMIT")
                
            except Exception as e:
                conn.execute("ROLLBACK")
                print(f"Error reordering tabs: {e}")
                raise

    def initialize_default_tabs(self) -> None:
        """Initialize default system tabs if they don't exist.
        
        This creates the default 'Main' and 'Archive' system tabs with proper ordering.
        Safe to call multiple times - will not create duplicates.
        """
        with _connect(self.db_path) as conn:
            _ensure_schema(conn)
            _initialize_default_tabs(conn)
    
    def ensure_migrations_complete(self) -> None:
        """Ensure all database migrations have been run.
        
        This method can be called explicitly if you need to ensure migrations
        are up to date without creating a new connection.
        """
        with _connect(self.db_path) as conn:
            _run_migrations(conn)


