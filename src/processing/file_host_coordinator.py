"""
File host upload coordinator for managing connection limits and upload queue.

Enforces global and per-host connection limits using semaphores, ensuring
uploads don't overwhelm the system or violate host-specific rate limits.
"""

import threading
from typing import Dict, Optional, List, Set
from contextlib import contextmanager

from src.utils.logger import log


class FileHostCoordinator:
    """Manages file host upload workers and enforces connection limits."""

    def __init__(self, global_limit: int = 3, per_host_limit: int = 2):
        """Initialize coordinator with connection limits.

        Args:
            global_limit: Maximum total concurrent file host uploads
            per_host_limit: Maximum concurrent uploads per individual host
        """
        self.global_limit = global_limit
        self.per_host_limit = per_host_limit

        # Global semaphore for total uploads
        self.global_semaphore = threading.Semaphore(global_limit)

        # Per-host semaphores
        self.host_semaphores: Dict[str, threading.Semaphore] = {}
        self.host_semaphore_lock = threading.Lock()

        # Active uploads tracking
        self.active_uploads: Set[tuple] = set()  # Set of (gallery_id, host_name)
        self.active_uploads_lock = threading.Lock()

        # Statistics
        self.total_uploads_started = 0
        self.total_uploads_completed = 0
        self.total_uploads_failed = 0
        self.stats_lock = threading.Lock()

    def update_limits(self, global_limit: Optional[int] = None, per_host_limit: Optional[int] = None):
        """Update connection limits (affects new uploads, not active ones).

        Args:
            global_limit: New global limit (if provided)
            per_host_limit: New per-host limit (if provided)
        """
        if global_limit is not None and global_limit != self.global_limit:
            log(
                f"Updating global file host limit: {self.global_limit} → {global_limit}",
                level="info",
                category="file_hosts"
            )
            self.global_limit = global_limit
            self.global_semaphore = threading.Semaphore(global_limit)

        if per_host_limit is not None and per_host_limit != self.per_host_limit:
            log(
                f"Updating per-host limit: {self.per_host_limit} → {per_host_limit}",
                level="info",
                category="file_hosts"
            )
            self.per_host_limit = per_host_limit

            # Recreate host semaphores with new limit
            with self.host_semaphore_lock:
                self.host_semaphores.clear()

    def _get_host_semaphore(self, host_name: str) -> threading.Semaphore:
        """Get or create semaphore for a specific host.

        Args:
            host_name: Name of the host

        Returns:
            Semaphore for the host
        """
        with self.host_semaphore_lock:
            if host_name not in self.host_semaphores:
                self.host_semaphores[host_name] = threading.Semaphore(self.per_host_limit)
            return self.host_semaphores[host_name]

    @contextmanager
    def acquire_slot(self, gallery_id: int, host_name: str, timeout: Optional[float] = None):
        """Context manager to acquire upload slots (global + per-host).

        Usage:
            with coordinator.acquire_slot(gallery_id, 'rapidgator'):
                # Perform upload
                pass

        Args:
            gallery_id: Gallery ID
            host_name: Host name
            timeout: Optional timeout in seconds

        Yields:
            True if slots acquired

        Raises:
            TimeoutError: If slots couldn't be acquired within timeout
        """
        upload_key = (gallery_id, host_name)

        # Acquire global slot
        global_acquired = self.global_semaphore.acquire(timeout=timeout)
        if not global_acquired:
            raise TimeoutError(f"Could not acquire global upload slot within {timeout}s")

        host_semaphore = self._get_host_semaphore(host_name)

        # Acquire host-specific slot
        host_acquired = False
        try:
            host_acquired = host_semaphore.acquire(timeout=timeout)
            if not host_acquired:
                raise TimeoutError(f"Could not acquire upload slot for {host_name} within {timeout}s")

            # Mark as active
            with self.active_uploads_lock:
                self.active_uploads.add(upload_key)

            with self.stats_lock:
                self.total_uploads_started += 1

            log(
                f"Acquired upload slots for {host_name} (gallery {gallery_id})",
                level="debug",
                category="file_hosts"
            )

            yield True

        finally:
            # Release slots
            if host_acquired:
                host_semaphore.release()

            self.global_semaphore.release()

            # Remove from active
            with self.active_uploads_lock:
                self.active_uploads.discard(upload_key)

            log(
                f"Released upload slots for {host_name} (gallery {gallery_id})",
                level="debug",
                category="file_hosts"
            )

    def is_upload_active(self, gallery_id: int, host_name: str) -> bool:
        """Check if a specific upload is currently active.

        Args:
            gallery_id: Gallery ID
            host_name: Host name

        Returns:
            True if upload is active
        """
        with self.active_uploads_lock:
            return (gallery_id, host_name) in self.active_uploads

    def get_active_upload_count(self, host_name: Optional[str] = None) -> int:
        """Get count of active uploads, optionally filtered by host.

        Args:
            host_name: Optional host name to filter by

        Returns:
            Number of active uploads
        """
        with self.active_uploads_lock:
            if host_name:
                return sum(1 for _, h in self.active_uploads if h == host_name)
            return len(self.active_uploads)

    def get_active_uploads(self) -> List[tuple]:
        """Get list of all active uploads.

        Returns:
            List of (gallery_id, host_name) tuples
        """
        with self.active_uploads_lock:
            return list(self.active_uploads)

    def record_completion(self, success: bool):
        """Record upload completion for statistics.

        Args:
            success: True if upload succeeded, False if failed
        """
        with self.stats_lock:
            if success:
                self.total_uploads_completed += 1
            else:
                self.total_uploads_failed += 1

    def get_statistics(self) -> Dict:
        """Get upload statistics.

        Returns:
            Dictionary with statistics
        """
        with self.stats_lock:
            return {
                'total_started': self.total_uploads_started,
                'total_completed': self.total_uploads_completed,
                'total_failed': self.total_uploads_failed,
                'active_count': self.get_active_upload_count(),
                'global_limit': self.global_limit,
                'per_host_limit': self.per_host_limit
            }

    def get_available_slots(self, host_name: Optional[str] = None) -> int:
        """Get number of available upload slots.

        Args:
            host_name: Optional host name to check specific host availability

        Returns:
            Number of available slots (minimum of global and per-host)
        """
        # Note: Semaphore doesn't expose current value in Python's implementation,
        # so we estimate based on active uploads
        active_total = self.get_active_upload_count()
        global_available = max(0, self.global_limit - active_total)

        if host_name:
            active_host = self.get_active_upload_count(host_name)
            host_available = max(0, self.per_host_limit - active_host)
            return min(global_available, host_available)

        return global_available

    def can_start_upload(self, host_name: str) -> bool:
        """Check if an upload can start immediately without blocking.

        Args:
            host_name: Host name

        Returns:
            True if upload can start without waiting
        """
        return self.get_available_slots(host_name) > 0


# Global singleton instance
_coordinator: Optional[FileHostCoordinator] = None
_coordinator_lock = threading.Lock()


def get_coordinator() -> FileHostCoordinator:
    """Get or create the global FileHostCoordinator instance.

    Returns:
        Global FileHostCoordinator instance
    """
    global _coordinator

    if _coordinator is None:
        with _coordinator_lock:
            if _coordinator is None:
                # Default limits - will be overridden from settings
                _coordinator = FileHostCoordinator(global_limit=3, per_host_limit=2)

    return _coordinator
