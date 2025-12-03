"""
Metrics storage for file host upload tracking.

Provides persistent storage and real-time tracking of upload metrics
across different time periods (session, daily, all-time).

Uses buffered writes for performance and PyQt6 signals for UI updates.
"""

from __future__ import annotations

import atexit
import logging
import os
import sqlite3
import threading
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from queue import Queue, Empty
from typing import Any, Dict, Optional

from PyQt6.QtCore import QObject, pyqtSignal, QTimer

# Access central data dir path from shared helper
from imxup import get_central_store_base_path

logger = logging.getLogger(__name__)


class MetricsSignals(QObject):
    """Signals for metrics updates to UI components."""

    # Emitted when a specific host's metrics are updated
    # Args: host_name (str), metrics (dict)
    host_metrics_updated = pyqtSignal(str, dict)


class MetricsStore:
    """
    Singleton store for file host upload metrics.

    Features:
    - SQLite persistence with buffered async writes
    - In-memory session cache for fast reads
    - Thread-safe operations
    - PyQt6 signal emissions for UI updates
    - Period-based aggregation (session, daily, weekly, monthly, all-time)

    Usage:
        store = MetricsStore.instance()
        store.record_transfer("rapidgator", bytes_uploaded=1024000,
                             transfer_time=5.2, success=True)
        metrics = store.get_session_metrics("rapidgator")
    """

    _instance: Optional[MetricsStore] = None
    _lock = threading.Lock()

    def __new__(cls) -> MetricsStore:
        """Ensure singleton pattern."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    @classmethod
    def instance(cls) -> MetricsStore:
        """Get the singleton instance."""
        return cls()

    def __init__(self):
        """Initialize the metrics store (only runs once due to singleton)."""
        # CRITICAL: Protect initialization check with class lock to prevent
        # multiple threads from running __init__ simultaneously
        with self._lock:
            if getattr(self, '_initialized', False):
                return

            self._initialized = True
            self._db_path = self._get_db_path()

            # Thread safety
            self._cache_lock = threading.RLock()
            self._db_lock = threading.RLock()  # ✅ Allows nested acquisition by same thread

            # Session cache for fast reads
            # Structure: {host_name: {bytes_uploaded, files_uploaded, files_failed,
            #                         total_transfer_time, peak_speed, avg_speed}}
            self._session_cache: Dict[str, Dict[str, Any]] = {}

            # Today's metrics cache for fast access
            # Structure: {host_name: {bytes_uploaded, files_uploaded, files_failed,
            #                         total_transfer_time, peak_speed, avg_speed, success_rate}}
            self._today_cache: Dict[str, Dict[str, Any]] = {}

            # All-time metrics cache for fast access
            # Structure: {host_name: {bytes_uploaded, files_uploaded, files_failed,
            #                         total_transfer_time, peak_speed, avg_speed, success_rate}}
            self._all_time_cache: Dict[str, Dict[str, Any]] = {}

            # Write buffer queue
            self._write_queue: Queue = Queue()
            # CRITICAL FIX: Don't use ThreadPoolExecutor - use a manual daemon thread
            # ThreadPoolExecutor creates non-daemon threads that block Python shutdown
            # when combined with PyQt6's cleanup sequence, causing hangs.
            self._executor = None  # Will be replaced by manual thread
            self._worker_thread = None
            self._running = True

            # PyQt signals
            self.signals = MetricsSignals()

            # Initialize database schema BEFORE starting worker thread
            # This prevents race condition where worker tries to acquire
            # _db_lock while schema creation is in progress
            self._ensure_schema()

            # Start background writer as a DAEMON thread AFTER schema is ready
            # Daemon threads don't block Python shutdown
            self._worker_thread = threading.Thread(
                target=self._write_worker,
                name="MetricsWriter-daemon",
                daemon=True  # Key fix: daemon thread won't block shutdown
            )
            self._worker_thread.start()

            # Register cleanup on application exit
            atexit.register(self.close)

            logger.debug(f"MetricsStore initialized with database at {self._db_path}")

    def __del__(self):
        """
        Destructor to ensure cleanup even if atexit handler doesn't run.

        This is a safety net for cases where Python interpreter shutdown
        happens before atexit handlers execute (e.g., during complex PyQt6 cleanup).
        """
        try:
            self.close()
        except Exception:
            pass  # Silently ignore errors during cleanup

    def _get_db_path(self) -> str:
        """Get the path to the metrics database file."""
        base_dir = get_central_store_base_path()
        return os.path.join(base_dir, "metrics.db")

    def _connect(self) -> sqlite3.Connection:
        """Create a new database connection with optimal settings."""
        conn = sqlite3.connect(self._db_path, timeout=5, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        """Create database tables if they don't exist."""
        with self._db_lock:
            conn = self._connect()
            try:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS host_metrics (
                        id INTEGER PRIMARY KEY,
                        host_name TEXT NOT NULL,
                        bytes_uploaded INTEGER DEFAULT 0,
                        files_uploaded INTEGER DEFAULT 0,
                        files_failed INTEGER DEFAULT 0,
                        total_transfer_time REAL DEFAULT 0,
                        peak_speed REAL DEFAULT 0,
                        period_type TEXT NOT NULL CHECK (period_type IN ('session', 'daily', 'all_time')),
                        period_date TEXT,
                        created_ts INTEGER DEFAULT (strftime('%s', 'now')),
                        updated_ts INTEGER DEFAULT (strftime('%s', 'now')),
                        UNIQUE(host_name, period_type, period_date)
                    );

                    CREATE INDEX IF NOT EXISTS idx_host_metrics_host
                        ON host_metrics(host_name);
                    CREATE INDEX IF NOT EXISTS idx_host_metrics_period
                        ON host_metrics(period_type, period_date);
                    CREATE INDEX IF NOT EXISTS idx_host_metrics_updated
                        ON host_metrics(updated_ts DESC);
                    CREATE INDEX IF NOT EXISTS idx_host_metrics_host_period
                        ON host_metrics(host_name, period_type, period_date);
                """)
                logger.debug("Metrics database schema ensured")
            except Exception as e:
                logger.error(f"Failed to create metrics schema: {e}")
                raise
            finally:
                conn.close()

    def record_transfer(self, host_name: str, bytes_uploaded: int,
                       transfer_time: float, success: bool) -> None:
        """
        Record a completed transfer.

        Updates session cache immediately and queues database write.
        Emits signals for UI updates.

        Args:
            host_name: The file host identifier (e.g., 'rapidgator', 'keep2share')
            bytes_uploaded: Number of bytes transferred
            transfer_time: Time taken for transfer in seconds
            success: Whether the transfer completed successfully
        """
        if transfer_time <= 0:
            transfer_time = 0.001  # Avoid division by zero

        # Calculate speed in bytes/second
        speed = bytes_uploaded / transfer_time if transfer_time > 0 else 0

        # Update session cache
        with self._cache_lock:
            if host_name not in self._session_cache:
                self._session_cache[host_name] = {
                    'bytes_uploaded': 0,
                    'files_uploaded': 0,
                    'files_failed': 0,
                    'total_transfer_time': 0.0,
                    'peak_speed': 0.0,
                    'speeds': [],  # Rolling window for average calculation
                }

            cache = self._session_cache[host_name]
            cache['bytes_uploaded'] += bytes_uploaded
            cache['total_transfer_time'] += transfer_time

            if success:
                cache['files_uploaded'] += 1
            else:
                cache['files_failed'] += 1

            # Track peak speed
            if speed > cache['peak_speed']:
                cache['peak_speed'] = speed

            # Keep rolling window of speeds for average (last 10)
            cache['speeds'].append(speed)
            if len(cache['speeds']) > 10:
                cache['speeds'] = cache['speeds'][-10:]

            # Calculate average speed
            if cache['speeds']:
                cache['avg_speed'] = sum(cache['speeds']) / len(cache['speeds'])
            else:
                cache['avg_speed'] = 0.0

            # Update today_cache (initialize empty if not present)
            today = datetime.now().strftime('%Y-%m-%d')
            if host_name not in self._today_cache:
                # Initialize empty cache - avoid blocking DB query during record
                # Actual historical data loaded via _populate_initial_metrics() in worker_status_widget
                self._today_cache[host_name] = {
                    'bytes_uploaded': 0,
                    'files_uploaded': 0,
                    'files_failed': 0,
                    'total_transfer_time': 0.0,
                    'peak_speed': 0.0,
                    'speeds': [],
                    'avg_speed': 0.0
                }

            today_cache = self._today_cache[host_name]
            today_cache['bytes_uploaded'] += bytes_uploaded
            today_cache['total_transfer_time'] += transfer_time
            if success:
                today_cache['files_uploaded'] += 1
            else:
                today_cache['files_failed'] += 1
            if speed > today_cache['peak_speed']:
                today_cache['peak_speed'] = speed
            today_cache['speeds'].append(speed)
            if len(today_cache['speeds']) > 10:
                today_cache['speeds'] = today_cache['speeds'][-10:]
            if today_cache['speeds']:
                today_cache['avg_speed'] = sum(today_cache['speeds']) / len(today_cache['speeds'])
            else:
                today_cache['avg_speed'] = 0.0

            # Update all_time_cache (initialize empty if not present)
            if host_name not in self._all_time_cache:
                # Initialize empty cache - avoid blocking DB query during record
                # Actual historical data loaded via _populate_initial_metrics() in worker_status_widget
                self._all_time_cache[host_name] = {
                    'bytes_uploaded': 0,
                    'files_uploaded': 0,
                    'files_failed': 0,
                    'total_transfer_time': 0.0,
                    'peak_speed': 0.0,
                    'speeds': [],
                    'avg_speed': 0.0
                }

            all_time_cache = self._all_time_cache[host_name]
            all_time_cache['bytes_uploaded'] += bytes_uploaded
            all_time_cache['total_transfer_time'] += transfer_time
            if success:
                all_time_cache['files_uploaded'] += 1
            else:
                all_time_cache['files_failed'] += 1
            if speed > all_time_cache['peak_speed']:
                all_time_cache['peak_speed'] = speed
            all_time_cache['speeds'].append(speed)
            if len(all_time_cache['speeds']) > 10:
                all_time_cache['speeds'] = all_time_cache['speeds'][-10:]
            if all_time_cache['speeds']:
                all_time_cache['avg_speed'] = sum(all_time_cache['speeds']) / len(all_time_cache['speeds'])
            else:
                all_time_cache['avg_speed'] = 0.0

            # Copy all three caches for signal emission
            metrics_copy = self._format_metrics(cache)
            today_metrics_copy = self._format_metrics(today_cache)
            all_time_metrics_copy = self._format_metrics(all_time_cache)

        # Queue database write
        self._write_queue.put({
            'type': 'transfer',
            'host_name': host_name,
            'bytes_uploaded': bytes_uploaded,
            'transfer_time': transfer_time,
            'success': success,
            'speed': speed,
            'timestamp': time.time()
        })

        # Emit signals for UI updates
        try:
            # Wrap in nested format with all three metric periods
            nested_metrics = {
                'session': metrics_copy,
                'today': today_metrics_copy,
                'all_time': all_time_metrics_copy
            }
            self.signals.host_metrics_updated.emit(host_name, nested_metrics)
        except Exception as e:
            logger.debug(f"Failed to emit metrics signals: {e}")

    def _format_metrics(self, cache: Dict[str, Any]) -> Dict[str, Any]:
        """Format cache data into a clean metrics dict."""
        files_uploaded = cache.get('files_uploaded', 0)
        files_failed = cache.get('files_failed', 0)
        total_files = files_uploaded + files_failed

        return {
            'bytes_uploaded': cache.get('bytes_uploaded', 0),
            'files_uploaded': files_uploaded,
            'files_failed': files_failed,
            'total_transfer_time': cache.get('total_transfer_time', 0.0),
            'peak_speed': cache.get('peak_speed', 0.0),
            'avg_speed': cache.get('avg_speed', 0.0),
            'success_rate': (files_uploaded / max(1, total_files)) * 100
        }

    def get_session_metrics(self, host_name: str) -> Dict[str, Any]:
        """
        Get current session metrics for a host.

        This is a fast operation that reads from the in-memory cache.

        Args:
            host_name: The file host identifier

        Returns:
            Dict with metrics: bytes_uploaded, files_uploaded, files_failed,
            total_transfer_time, peak_speed, avg_speed, success_rate
        """
        with self._cache_lock:
            if host_name not in self._session_cache:
                return {
                    'bytes_uploaded': 0,
                    'files_uploaded': 0,
                    'files_failed': 0,
                    'total_transfer_time': 0.0,
                    'peak_speed': 0.0,
                    'avg_speed': 0.0,
                    'success_rate': 100.0
                }
            return self._format_metrics(self._session_cache[host_name])

    def get_aggregated_metrics(self, host_name: str, period: str) -> Dict[str, Any]:
        """
        Get metrics for a specific time period.

        Args:
            host_name: The file host identifier
            period: One of 'session', 'today', 'week', 'month', 'all_time'

        Returns:
            Dict with aggregated metrics for the period
        """
        if period == 'session':
            return self.get_session_metrics(host_name)

        with self._db_lock:
            conn = self._connect()
            try:
                if period == 'today':
                    # Get today's date
                    today = datetime.now().strftime('%Y-%m-%d')
                    cursor = conn.execute("""
                        SELECT
                            COALESCE(SUM(bytes_uploaded), 0) as bytes_uploaded,
                            COALESCE(SUM(files_uploaded), 0) as files_uploaded,
                            COALESCE(SUM(files_failed), 0) as files_failed,
                            COALESCE(SUM(total_transfer_time), 0) as total_transfer_time,
                            COALESCE(MAX(peak_speed), 0) as peak_speed
                        FROM host_metrics
                        WHERE host_name = ? AND period_type = 'daily' AND period_date = ?
                    """, (host_name, today))

                elif period == 'week':
                    # Get last 7 days
                    week_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
                    cursor = conn.execute("""
                        SELECT
                            COALESCE(SUM(bytes_uploaded), 0) as bytes_uploaded,
                            COALESCE(SUM(files_uploaded), 0) as files_uploaded,
                            COALESCE(SUM(files_failed), 0) as files_failed,
                            COALESCE(SUM(total_transfer_time), 0) as total_transfer_time,
                            COALESCE(MAX(peak_speed), 0) as peak_speed
                        FROM host_metrics
                        WHERE host_name = ? AND period_type = 'daily' AND period_date >= ?
                    """, (host_name, week_ago))

                elif period == 'month':
                    # Get last 30 days
                    month_ago = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
                    cursor = conn.execute("""
                        SELECT
                            COALESCE(SUM(bytes_uploaded), 0) as bytes_uploaded,
                            COALESCE(SUM(files_uploaded), 0) as files_uploaded,
                            COALESCE(SUM(files_failed), 0) as files_failed,
                            COALESCE(SUM(total_transfer_time), 0) as total_transfer_time,
                            COALESCE(MAX(peak_speed), 0) as peak_speed
                        FROM host_metrics
                        WHERE host_name = ? AND period_type = 'daily' AND period_date >= ?
                    """, (host_name, month_ago))

                elif period == 'all_time':
                    cursor = conn.execute("""
                        SELECT
                            COALESCE(SUM(bytes_uploaded), 0) as bytes_uploaded,
                            COALESCE(SUM(files_uploaded), 0) as files_uploaded,
                            COALESCE(SUM(files_failed), 0) as files_failed,
                            COALESCE(SUM(total_transfer_time), 0) as total_transfer_time,
                            COALESCE(MAX(peak_speed), 0) as peak_speed
                        FROM host_metrics
                        WHERE host_name = ? AND period_type = 'all_time'
                    """, (host_name,))

                else:
                    logger.warning(f"Unknown period type: {period}")
                    return self.get_session_metrics(host_name)

                row = cursor.fetchone()
                if row:
                    total_files = row['files_uploaded'] + row['files_failed']
                    success_rate = (row['files_uploaded'] / max(1, total_files)) * 100
                    avg_speed = (row['bytes_uploaded'] / max(0.001, row['total_transfer_time']))

                    return {
                        'bytes_uploaded': row['bytes_uploaded'],
                        'files_uploaded': row['files_uploaded'],
                        'files_failed': row['files_failed'],
                        'total_transfer_time': row['total_transfer_time'],
                        'peak_speed': row['peak_speed'],
                        'avg_speed': avg_speed,
                        'success_rate': success_rate
                    }

            except Exception as e:
                logger.error(f"Failed to get aggregated metrics: {e}")
            finally:
                conn.close()

        # Return empty metrics on error
        return {
            'bytes_uploaded': 0,
            'files_uploaded': 0,
            'files_failed': 0,
            'total_transfer_time': 0.0,
            'peak_speed': 0.0,
            'avg_speed': 0.0,
            'success_rate': 100.0
        }

    def get_all_host_stats(self) -> Dict[str, Dict[str, Any]]:
        """
        Get metrics for all hosts that have any activity.

        Returns:
            Dict mapping host names to their session metrics
        """
        result = {}

        with self._cache_lock:
            for host_name, cache in self._session_cache.items():
                result[host_name] = self._format_metrics(cache)

        return result

    def get_active_hosts(self) -> list[str]:
        """
        Get list of hosts with activity in current session.

        Returns:
            List of host names
        """
        with self._cache_lock:
            return list(self._session_cache.keys())

    def get_hosts_with_history(self) -> Dict[str, Dict[str, Any]]:
        """
        Get all hosts that have historical data in the database.

        Returns:
            Dict mapping host names to their all-time metrics
        """
        result = {}

        # Step 1: Get host names snapshot (brief lock acquisition)
        # Note: Lock released before calling get_aggregated_metrics() to prevent deadlock
        with self._db_lock:
            conn = self._connect()
            try:
                cursor = conn.execute("""
                    SELECT DISTINCT host_name FROM host_metrics
                    WHERE period_type = 'all_time'
                """)
                host_names = [row['host_name'] for row in cursor]
            except Exception as e:
                logger.error(f"Failed to query hosts with history: {e}")
                return {}  # Return empty dict if database query fails
            finally:
                conn.close()

        # Step 2: Fetch metrics for each host (lock released, no nested acquisition)
        # Each call to get_aggregated_metrics() manages its own lock safely
        for host_name in host_names:
            try:
                result[host_name] = self.get_aggregated_metrics(host_name, 'all_time')
            except Exception as e:
                # Log error but continue processing other hosts
                logger.error(f"Failed to get metrics for host '{host_name}': {e}")
                # Note: Failed hosts are excluded from results

        logger.debug(f"Retrieved metrics for {len(result)}/{len(host_names)} hosts")
        return result

    def _write_worker(self) -> None:
        """Background worker that processes buffered writes."""
        logger.debug("Metrics write worker started")

        while self._running:
            try:
                # Wait for items with timeout
                try:
                    item = self._write_queue.get(timeout=1.0)
                except Empty:
                    continue

                if item is None:  # Shutdown signal
                    break

                self._process_write(item)
                self._write_queue.task_done()

            except Exception as e:
                logger.error(f"Error in metrics write worker: {e}")

        # Process remaining items on shutdown
        while not self._write_queue.empty():
            try:
                item = self._write_queue.get_nowait()
                if item is not None:
                    self._process_write(item)
                self._write_queue.task_done()
            except Empty:
                break
            except Exception as e:
                logger.error(f"Error processing remaining writes: {e}")

        logger.debug("Metrics write worker stopped")

    def _process_write(self, item: Dict[str, Any]) -> None:
        """Process a single write item from the queue."""
        if item['type'] != 'transfer':
            return

        host_name = item['host_name']
        bytes_uploaded = item['bytes_uploaded']
        transfer_time = item['transfer_time']
        success = item['success']
        speed = item['speed']
        today = datetime.now().strftime('%Y-%m-%d')

        with self._db_lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN TRANSACTION")

                # Update daily metrics
                conn.execute("""
                    INSERT INTO host_metrics
                        (host_name, bytes_uploaded, files_uploaded, files_failed,
                         total_transfer_time, peak_speed, period_type, period_date)
                    VALUES (?, ?, ?, ?, ?, ?, 'daily', ?)
                    ON CONFLICT(host_name, period_type, period_date) DO UPDATE SET
                        bytes_uploaded = bytes_uploaded + excluded.bytes_uploaded,
                        files_uploaded = files_uploaded + excluded.files_uploaded,
                        files_failed = files_failed + excluded.files_failed,
                        total_transfer_time = total_transfer_time + excluded.total_transfer_time,
                        peak_speed = MAX(peak_speed, excluded.peak_speed),
                        updated_ts = strftime('%s', 'now')
                """, (
                    host_name,
                    bytes_uploaded,
                    1 if success else 0,
                    0 if success else 1,
                    transfer_time,
                    speed,
                    today
                ))

                # Update all-time metrics
                conn.execute("""
                    INSERT INTO host_metrics
                        (host_name, bytes_uploaded, files_uploaded, files_failed,
                         total_transfer_time, peak_speed, period_type, period_date)
                    VALUES (?, ?, ?, ?, ?, ?, 'all_time', NULL)
                    ON CONFLICT(host_name, period_type, period_date) DO UPDATE SET
                        bytes_uploaded = bytes_uploaded + excluded.bytes_uploaded,
                        files_uploaded = files_uploaded + excluded.files_uploaded,
                        files_failed = files_failed + excluded.files_failed,
                        total_transfer_time = total_transfer_time + excluded.total_transfer_time,
                        peak_speed = MAX(peak_speed, excluded.peak_speed),
                        updated_ts = strftime('%s', 'now')
                """, (
                    host_name,
                    bytes_uploaded,
                    1 if success else 0,
                    0 if success else 1,
                    transfer_time,
                    speed
                ))

                conn.execute("COMMIT")

            except Exception as e:
                conn.execute("ROLLBACK")
                logger.error(f"Failed to write metrics to database: {e}")
            finally:
                conn.close()

    def flush(self) -> None:
        """
        Force write all pending metrics to database.

        Blocks until all queued writes are processed.
        """
        logger.debug("Flushing metrics store...")
        self._write_queue.join()
        logger.debug("Metrics store flushed")

    def reset_session(self) -> None:
        """
        Clear the session cache to start fresh metrics.

        This does not affect persistent database metrics.
        """
        with self._cache_lock:
            self._session_cache.clear()
            self._today_cache.clear()
            self._all_time_cache.clear()

        logger.debug("Session metrics reset")

    def close(self) -> None:
        """
        Shutdown the worker thread and flush pending writes.

        Should be called on application exit.
        """
        # Idempotent - safe to call multiple times
        if not self._running:
            return

        logger.debug("Closing MetricsStore...")

        self._running = False
        self._write_queue.put(None)  # Signal worker to stop

        # Wait for worker thread to complete (with timeout)
        # Worker exits quickly: _running=False, None sentinel, 1s timeout on queue.get()
        if self._worker_thread and self._worker_thread.is_alive():
            try:
                self._worker_thread.join(timeout=2.0)
                if self._worker_thread.is_alive():
                    logger.warning("MetricsWriter thread did not stop within 2 seconds")
            except Exception as e:
                logger.error(f"Error waiting for metrics worker thread: {e}")

        logger.debug("MetricsStore closed")

    def get_daily_breakdown(self, host_name: str, days: int = 7) -> list[Dict[str, Any]]:
        """
        Get daily breakdown of metrics for a host.

        Args:
            host_name: The file host identifier
            days: Number of days to retrieve (default 7)

        Returns:
            List of dicts with date and metrics for each day
        """
        result = []
        start_date = (datetime.now() - timedelta(days=days-1)).strftime('%Y-%m-%d')

        with self._db_lock:
            conn = self._connect()
            try:
                cursor = conn.execute("""
                    SELECT
                        period_date,
                        bytes_uploaded,
                        files_uploaded,
                        files_failed,
                        total_transfer_time,
                        peak_speed
                    FROM host_metrics
                    WHERE host_name = ?
                        AND period_type = 'daily'
                        AND period_date >= ?
                    ORDER BY period_date DESC
                """, (host_name, start_date))

                for row in cursor:
                    total_files = row['files_uploaded'] + row['files_failed']
                    result.append({
                        'date': row['period_date'],
                        'bytes_uploaded': row['bytes_uploaded'],
                        'files_uploaded': row['files_uploaded'],
                        'files_failed': row['files_failed'],
                        'total_transfer_time': row['total_transfer_time'],
                        'peak_speed': row['peak_speed'],
                        'success_rate': (row['files_uploaded'] / max(1, total_files)) * 100
                    })

            except Exception as e:
                logger.error(f"Failed to get daily breakdown: {e}")
            finally:
                conn.close()

        return result

    def cleanup_old_metrics(self, days_to_keep: int = 90) -> int:
        """
        Remove daily metrics older than specified days.

        Args:
            days_to_keep: Number of days of daily data to retain

        Returns:
            Number of rows deleted
        """
        cutoff_date = (datetime.now() - timedelta(days=days_to_keep)).strftime('%Y-%m-%d')
        deleted = 0

        with self._db_lock:
            conn = self._connect()
            try:
                cursor = conn.execute("""
                    DELETE FROM host_metrics
                    WHERE period_type = 'daily' AND period_date < ?
                """, (cutoff_date,))
                deleted = cursor.rowcount
                logger.info(f"Cleaned up {deleted} old daily metric records")
            except Exception as e:
                logger.error(f"Failed to cleanup old metrics: {e}")
            finally:
                conn.close()

        return deleted


# Module-level convenience function
def get_metrics_store() -> MetricsStore:
    """Get the singleton MetricsStore instance."""
    return MetricsStore.instance()
