"""
File host worker lifecycle manager.

Manages one persistent worker per enabled file host. Handles worker spawning/killing,
signal relay to GUI, and host enable/disable operations.
"""

import threading
from typing import Dict, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from src.core.file_host_config import get_config_manager
from src.processing.file_host_workers import FileHostWorker
from src.storage.database import QueueStore
from src.utils.logger import log


class FileHostWorkerManager(QObject):
    """Manages lifecycle of file host workers (one per enabled host).

    Architecture:
    - Workers are persistent - live until host is disabled
    - Owned by main application, not by settings dialog
    - Settings dialog gets references via get_worker()
    - Manager relays all worker signals to GUI
    """

    # Relay all worker signals to GUI
    storage_updated = pyqtSignal(str, object, object)  # host_id, total_bytes, left_bytes (object avoids 32-bit overflow)
    test_completed = pyqtSignal(str, dict)  # host_id, results_dict
    spinup_complete = pyqtSignal(str, str)  # host_id, error_message
    enabled_workers_changed = pyqtSignal(list)  # List of enabled host_ids
    upload_started = pyqtSignal(int, str)  # gallery_id, host_name
    upload_progress = pyqtSignal(int, str, int, int, float)  # gallery_id, host_name, uploaded, total, speed_bps
    upload_completed = pyqtSignal(int, str, dict)  # gallery_id, host_name, result
    upload_failed = pyqtSignal(int, str, str)  # gallery_id, host_name, error
    bandwidth_updated = pyqtSignal(float)  # KB/s
    worker_status_updated = pyqtSignal(str, str)  # host_id, status_text

    def __init__(self, queue_store: QueueStore):
        """Initialize worker manager.

        Args:
            queue_store: Database queue store (shared by all workers)
        """
        super().__init__()
        self.queue_store = queue_store
        self.workers: Dict[str, FileHostWorker] = {}  # Enabled workers (spinup succeeded)
        self.pending_workers: Dict[str, FileHostWorker] = {}  # Workers spinning up (testing credentials)
        self._pending_lock = threading.Lock()  # Protects pending_workers dict

        import traceback
        caller = traceback.extract_stack()[-2]
        log(f"File Host Manager initialized (called from {caller.filename}:{caller.lineno} in {caller.name})", level="debug", category="file_hosts")

    def init_enabled_hosts(self) -> None:
        """Spawn workers for all enabled file hosts at startup.

        Reads the INI file ONCE to get all enabled hosts, then initializes workers.
        Skips redundant persistence writes since values are already in INI.

        Called at application startup.
        """
        from imxup import get_config_path
        import configparser
        import os

        log("Initializing file host workers on startup...", level="debug", category="file_hosts")

        config_manager = get_config_manager()

        # Read INI file ONCE to get all enabled hosts
        enabled_hosts = []
        config_file = get_config_path()

        if os.path.exists(config_file):
            # Single INI read for all hosts
            from src.core.file_host_config import _ini_file_lock
            with _ini_file_lock:
                config = configparser.ConfigParser()
                config.read(config_file)

                # Check each host's enabled state from INI
                for host_id in config_manager.hosts:
                    try:
                        if config.has_section("FILE_HOSTS"):
                            ini_key = f"{host_id}_enabled"
                            if config.has_option("FILE_HOSTS", ini_key):
                                if config.getboolean("FILE_HOSTS", ini_key):
                                    enabled_hosts.append(host_id)
                    except (ValueError, configparser.Error) as e:
                        log(f"Invalid enabled value for {host_id} in INI: {e}",
                            level="warning", category="file_hosts")
        else:
            log(f"INI file does not exist at {config_file}, no hosts enabled by default",
                level="debug", category="file_hosts")

        log(f"Found {len(enabled_hosts)} enabled hosts: {enabled_hosts}", level="debug", category="file_hosts")

        # Initialize workers for enabled hosts
        for host_id in enabled_hosts:
            try:
                # enable_host() already handles worker creation and spinup
                # Skip persistence during startup (values already in INI)
                self.enable_host(host_id, persist=False)
            except Exception as e:
                log(f"Failed to enable host {host_id}: {e}", level="error", category="file_hosts")

        log(f"[File Host Manager] After init_enabled_hosts: {len(self.workers)} in workers, {len(self.pending_workers)} pending", level="debug", category="file_hosts")

    def enable_host(self, host_id: str, persist: bool = True) -> None:
        """Spawn and start worker for a host.

        Worker tests credentials during its own spinup process.
        Manager waits for spinup_complete signal before marking as enabled.

        Args:
            host_id: Host identifier (e.g., 'rapidgator')
            persist: Whether to persist enabled state to INI (default: True)
                     Set to False during startup to avoid redundant writes
        """
        if host_id in self.workers:
            log(
                f"[File Host Manager] {host_id} Worker already running",
                level="debug",
                category="file_hosts"
            )
            return

        with self._pending_lock:
            if host_id in self.pending_workers:
                log(
                    f"[File Host Manager] {host_id} Worker already spinning up",
                    level="debug",
                    category="file_hosts"
                )
                return

            #  Create and configure worker
            worker = FileHostWorker(host_id, self.queue_store)
            self._connect_worker_signals(worker)

            # Add to pending_workers (NOT workers yet - not enabled until spinup succeeds)
            self.pending_workers[host_id] = worker

        # Store persist flag for use in _on_spinup_complete
        worker._persist_on_spinup = persist

        log(
            f"[File Host Manager] Starting worker spinup for {host_id}...",
            level="debug",
            category="file_hosts"
        )

        # Start worker thread (will test credentials during spinup)
        worker.start()
    def disable_host(self, host_id: str) -> None:
        """Stop and remove worker for a host.

        Args:
            host_id: Host identifier
        """
        worker = self.workers.pop(host_id, None)
        if not worker:
            log(
                f"[File Host Manager] Worker not found: No worker found for {host_id}",
                level="debug",
                category="file_hosts"
            )
            return

        log(
            f"[File Host Manager] Stopping {host_id} Worker...",
            level="debug",
            category="file_hosts"
        )

        # Connect finished signal for cleanup, then stop (non-blocking)
        worker.finished.connect(lambda w=worker: w.deleteLater())
        worker.stop()
        # Don't wait() - let it finish in background

        log(f"[File Host Manager] {host_id} Worker stopped (remaining workers: {len(self.workers)})",
            level="info",
            category="file_hosts"
        )

        # Persist disabled state to INI immediately (synchronous operation)
        self._persist_enabled_state(host_id, enabled=False)

        # Emit enabled workers list change (for tab view and dialog sync)
        self.enabled_workers_changed.emit(list(self.workers.keys()))

    def get_worker(self, host_id: str) -> Optional[FileHostWorker]:
        """Get worker reference for a host.

        Args:
            host_id: Host identifier

        Returns:
            Worker instance if host is enabled, None otherwise
        """
        return self.workers.get(host_id)

    def is_enabled(self, host_id: str) -> bool:
        """Check if host has a running worker.

        Args:
            host_id: Host identifier

        Returns:
            True if worker exists and is running
        """
        return host_id in self.workers

    def shutdown_all(self) -> None:
        """Gracefully stop all workers.

        Called at application shutdown.
        """
        if not self.workers:
            log("[File Host Manager] No workers to shutdown", level="debug", category="file_hosts")
            return

        log(f"[File Host Manager] Shutting down all file host workers ({len(self.workers)} total)...",
            level="info",
            category="file_hosts"
        )

        # Stop all workers
        for host_id, worker in self.workers.items():
            log(f"[File Host Manager] Stopping worker: {host_id}", level="debug", category="file_hosts")
            worker.stop()

        # Wait for all threads to finish
        for worker in self.workers.values():
            worker.wait()

        self.workers.clear()

        log("[File Host Manager] All file host workers shutdown complete", level="info", category="file_hosts")

    def _on_spinup_complete(self, host_id: str, error: str) -> None:
        """Handle worker spinup result (success or failure).

        Coordinates transition from pending to enabled/disabled.

        Args:
            host_id: Host identifier
            error: Error message from worker (empty string = success)
        """
        # Get worker from pending
        with self._pending_lock:
            worker = self.pending_workers.pop(host_id, None)

        if not worker:
            log(
                f"[File Host Manager] Received spinup_complete for unknown worker: {host_id}",
                level="warning",
                category="file_hosts"
            )
            return

        # Check if we should persist this change (skip during startup)
        persist = getattr(worker, '_persist_on_spinup', True)

        if error:
            # Spinup failed - kill dead worker
            log(
                f"[File Host Manager] Worker spinup failed for {host_id}: {error}",
                level="warning",
                category="file_hosts"
            )

            # Worker already emits failed status before spinup_complete signal
            # No need to emit here - would cause double status update to UI

            worker.wait()  # Clean up thread
            # Do NOT persist state - keep previous INI value on failure
        else:
            # Spinup succeeded - move to enabled workers
            log(
                f"[File Host Manager] Worker started successfully for {host_id}",
                level="debug",
                category="file_hosts"
            )

            self.workers[host_id] = worker

            # Only persist if requested (skip during startup to avoid redundant writes)
            if persist:
                self._persist_enabled_state(host_id, enabled=True)

        # Emit enabled workers list change (for tab view and dialog sync)
        self.enabled_workers_changed.emit(list(self.workers.keys()))

        # Always relay signal to GUI/dialog (they need to know the result)
        self.spinup_complete.emit(host_id, error)

    def _connect_worker_signals(self, worker: FileHostWorker) -> None:
        """Connect worker signals to manager signals (relay to GUI).

        Args:
            worker: Worker instance to connect
        """
        # Storage and testing signals
        # Storage and testing signals
        worker.storage_updated.connect(self.storage_updated)
        worker.test_completed.connect(self.test_completed)
        worker.spinup_complete.connect(self._on_spinup_complete)
        # Upload signals
        worker.upload_started.connect(self.upload_started)
        worker.upload_progress.connect(self.upload_progress)
        worker.upload_completed.connect(self.upload_completed)
        worker.upload_failed.connect(self.upload_failed)

        # Bandwidth signal
        worker.bandwidth_updated.connect(self.bandwidth_updated)

        # Status signal
        worker.status_updated.connect(self.worker_status_updated.emit)

    def pause_all(self):
        """Pause all workers (stop processing new uploads)."""
        for host_id, worker in self.workers.items():
            log(f"[File Host Manager] Pausing worker: {host_id}", level="debug", category="file_hosts")
            worker.pause()

    def resume_all(self):
        """Resume all workers (continue processing uploads)."""
        for host_id, worker in self.workers.items():
            log(f"[File Host Manager] Resuming worker: {host_id}", level="debug", category="file_hosts")
            worker.resume()

    def get_worker_count(self) -> int:
        """Get number of active workers.

        Returns:
            Number of running workers
        """
        return len(self.workers)

    def get_enabled_hosts(self) -> list:
        """Get list of enabled host IDs.

        Returns:
            List of host IDs with running workers
        """
        return list(self.workers.keys())

    def _persist_enabled_state(self, host_id: str, enabled: bool) -> None:
        """Persist enabled state to INI file using centralized API.

        This ensures that on next startup, init_enabled_hosts() will spawn
        the correct workers based on the last known enabled state.

        Args:
            host_id: Host identifier (e.g., 'rapidgator')
            enabled: True if host should be enabled, False otherwise
        """
        try:
            from src.core.file_host_config import save_file_host_setting
            save_file_host_setting(host_id, "enabled", enabled)

            log(
                f"[File Host Manager] Persisted enabled state for {host_id}: {enabled}",
                level="debug",
                category="file_hosts"
            )

        except Exception as e:
            log(
                f"[File Host Manager] Failed to persist enabled state for {host_id}: {e}",
                level="error",
                category="file_hosts"
            )
