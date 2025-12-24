"""Worker signal handling for IMXuploader GUI.

This module handles all worker-related signal operations extracted from main_window.py
to improve maintainability and separation of concerns.

Handles:
    - Upload worker lifecycle (start, stop, progress)
    - File host worker signal connections
    - Queue item status changes
    - Bandwidth and storage updates
    - Worker status widget updates
"""

from datetime import datetime
from typing import TYPE_CHECKING, Dict, Any

from PyQt6.QtCore import QObject, QTimer, QSettings, QMutexLocker, QMutex

from src.utils.logger import log
from src.utils.format_utils import format_binary_size

if TYPE_CHECKING:
    from src.gui.main_window import ImxUploadGUI


class WorkerSignalHandler(QObject):
    """Handles worker signals and status updates for the main window."""

    def __init__(self, main_window: 'ImxUploadGUI'):
        """Initialize the WorkerSignalHandler.

        Args:
            main_window: Reference to the main ImxUploadGUI window
        """
        super().__init__()
        self._main_window = main_window

        # File host bandwidth tracking
        self._fh_bandwidth_samples = []
        self._fh_current_transfer_kbps = 0.0

    def start_worker(self):
        """Start the upload worker thread."""
        from src.processing.upload_workers import UploadWorker

        mw = self._main_window
        if mw.worker is None or not mw.worker.isRunning():
            log(f"Creating new UploadWorker (old worker: {id(mw.worker) if mw.worker else 'None'}"
                f"{(', running: ' and mw.worker.isRunning()) if mw.worker else ''})",
                level="debug", category="uploads")
            mw.worker = UploadWorker(mw.queue_manager)
            log(f"New UploadWorker created ({id(mw.worker)})", level="debug", category="uploads")
            mw.worker.progress_updated.connect(mw.on_progress_updated)
            mw.worker.gallery_started.connect(mw.on_gallery_started)
            mw.worker.gallery_completed.connect(mw.on_gallery_completed)
            mw.worker.gallery_failed.connect(mw.on_gallery_failed)
            mw.worker.gallery_exists.connect(mw.on_gallery_exists)
            mw.worker.gallery_renamed.connect(mw.on_gallery_renamed)
            mw.worker.ext_fields_updated.connect(mw.on_ext_fields_updated)
            mw.worker.log_message.connect(mw.add_log_message)
            mw.worker.queue_stats.connect(self.on_queue_stats)
            mw.worker.bandwidth_updated.connect(mw.progress_tracker.on_bandwidth_updated)

            # Connect to worker status widget
            mw.worker.gallery_started.connect(self._on_imx_worker_started)
            mw.worker.bandwidth_updated.connect(self._on_imx_worker_speed)
            mw.worker.gallery_completed.connect(self._on_imx_worker_finished)
            mw.worker.gallery_failed.connect(self._on_imx_worker_finished)

            mw.worker.start()

            log(f"DEBUG: Worker.isRunning(): {mw.worker.isRunning()}", level="debug")

    def on_queue_item_status_changed(self, path: str, old_status: str, new_status: str):
        """Handle individual queue item status changes."""
        mw = self._main_window
        item = mw.queue_manager.get_item(path)
        scan_status = item.scan_complete if item else "NO_ITEM"
        in_mapping = path in mw.path_to_row
        log(f"DEBUG: GUI received status change signal: {path} from {old_status} to {new_status}, "
            f"scan_complete={scan_status}, in_path_to_row={in_mapping}", level="debug", category="ui")

        # When an item goes from scanning to ready, just update tab counts
        if old_status == "scanning" and new_status == "ready":
            # Just update the tab counts, don't refresh the filter which hides items
            QTimer.singleShot(150, lambda: mw.gallery_table._update_tab_tooltips()
                             if hasattr(mw.gallery_table, '_update_tab_tooltips') else None)

        # Debug the item data before updating table
        item = mw.queue_manager.get_item(path)
        if item:
            log(f"DEBUG: Item data: total_images={getattr(item, 'total_images', 'NOT SET')}, "
                f"progress={getattr(item, 'progress', 'NOT SET')}, "
                f"status={getattr(item, 'status', 'NOT SET')}, "
                f"added_time={getattr(item, 'added_time', 'NOT SET')}", level="debug", category="ui")

        # Update table display for this specific item
        mw._update_specific_gallery_display(path)

    def on_queue_stats(self, stats: dict):
        """Render aggregate queue stats beneath the overall progress bar.

        Example: "1 uploading (100 images / 111 MB) - 12 queued (912 images / 1.9 GB) - ..."
        """
        mw = self._main_window
        try:
            def fmt_section(label: str, s: dict) -> str:
                count = int(s.get('count', 0) or 0)
                if count <= 0:
                    return ""
                images = int(s.get('images', 0) or 0)
                by = int(s.get('bytes', 0) or 0)
                try:
                    size_str = format_binary_size(by, precision=1)
                except Exception:
                    size_str = f"{by} B"
                return f"{count} {label} ({images} images / {size_str})"

            order = [
                ('uploading', 'uploading'),
                ('queued', 'queued'),
                ('ready', 'ready'),
                ('incomplete', 'incomplete'),
                ('paused', 'paused'),
                ('completed', 'completed'),
                ('failed', 'failed'),
            ]
            parts = []
            for key, label in order:
                sec = stats.get(key, {}) if isinstance(stats, dict) else {}
                txt = fmt_section(label, sec)
                if txt:
                    parts.append(txt)
            mw.stats_label.setText(" - ".join(parts) if parts else "No galleries in queue")
        except Exception:
            # Fall back to previous text if formatting fails
            pass

    # =========================================================================
    # File Host Upload Signal Handlers
    # =========================================================================

    def on_file_host_upload_started(self, db_id: int, host_name: str):
        """Handle file host upload started - ASYNC to prevent blocking main thread."""
        log(f"File host upload started: {host_name} for gallery {db_id}",
            level="debug", category="file_hosts")
        # Defer UI refresh to avoid blocking signal emission
        QTimer.singleShot(0, lambda: self._main_window._refresh_file_host_widgets_for_db_id(db_id))

    def on_file_host_upload_progress(self, db_id: int, host_name: str,
                                      uploaded_bytes: int, total_bytes: int, speed_bps: float = 0.0):
        """Handle file host upload progress with detailed display."""
        try:
            # Calculate percentage
            if total_bytes > 0:
                percent = int((uploaded_bytes / total_bytes) * 100)
            else:
                percent = 0

            # Format progress info for tooltip/status
            uploaded_str = format_binary_size(uploaded_bytes)
            total_str = format_binary_size(total_bytes)

            status = f"{host_name}: {percent}% ({uploaded_str} / {total_str})"

            # Log detailed progress at debug level
            log(f"File host upload progress: {status}", level="debug", category="file_hosts")

            # Progress updates are frequent, so we avoid full refresh
            # The file host widgets will poll status and update themselves
        except Exception as e:
            log(f"Error handling file host upload progress: {e}", level="error", category="file_hosts")

    def on_file_host_upload_completed(self, db_id: int, host_name: str, result: dict):
        """Handle file host upload completed - ASYNC to prevent blocking main thread."""
        log(f"File host upload completed: {host_name} for gallery {db_id}",
            level="info", category="file_hosts")
        mw = self._main_window
        # Defer UI refresh to avoid blocking signal emission
        # Use QTimer.singleShot(0) to schedule on next event loop iteration
        QTimer.singleShot(0, lambda: mw._refresh_file_host_widgets_for_db_id(db_id))
        # Trigger artifact regeneration if auto-regenerate is enabled (non-blocking, after UI refresh)
        QTimer.singleShot(100, lambda: mw._auto_regenerate_for_db_id(db_id))
        # Update queue display for this host (event-driven, not polled)
        self._update_filehost_queue_for_host(host_name)

    def on_file_host_upload_failed(self, db_id: int, host_name: str, error_message: str):
        """Handle file host upload failed - ASYNC to prevent blocking main thread."""
        log(f"File host upload failed: {host_name} for gallery {db_id}: {error_message}",
            level="warning", category="file_hosts")
        # Defer UI refresh to avoid blocking signal emission
        QTimer.singleShot(0, lambda: self._main_window._refresh_file_host_widgets_for_db_id(db_id))
        # Update queue display for this host (event-driven, not polled)
        self._update_filehost_queue_for_host(host_name)

    def _update_filehost_queue_for_host(self, host_name: str):
        """Update queue columns for a specific file host after upload state change.

        Event-driven update: called when uploads complete/fail, not on timer.
        Queries only the affected host's stats for efficiency.

        Args:
            host_name: Name of the file host (e.g., 'rapidgator', 'keep2share')
        """
        mw = self._main_window
        try:
            if mw.queue_manager and mw.queue_manager.store:
                stats = mw.queue_manager.store.get_file_host_pending_stats(host_name)
                mw.worker_status_widget.update_filehost_queue_columns(
                    host_name, stats['files'], stats['bytes']
                )
        except (AttributeError, KeyError) as e:
            # AttributeError: queue_manager not initialized; KeyError: missing stats key
            log(f"Error updating {host_name} queue stats: {e}", level="warning", category="ui")

    def on_file_host_bandwidth_updated(self, kbps: float):
        """Handle file host bandwidth update with smoothing.

        Uses the same rolling average + compression-style smoothing algorithm
        as the IMX.to bandwidth handler for consistent display behavior.

        Args:
            kbps: Instantaneous bandwidth in KB/s
        """
        mw = self._main_window
        try:
            # Add to rolling window (keep last 20 samples = 4 seconds at 200ms polling)
            self._fh_bandwidth_samples.append(kbps)
            if len(self._fh_bandwidth_samples) > 20:
                self._fh_bandwidth_samples.pop(0)

            # Calculate average of recent samples to smooth out file completion spikes
            if self._fh_bandwidth_samples:
                averaged_kbps = sum(self._fh_bandwidth_samples) / len(self._fh_bandwidth_samples)
            else:
                averaged_kbps = kbps

            # Apply compression-style smoothing to the averaged value
            if averaged_kbps > self._fh_current_transfer_kbps:
                # Moderate attack - follow increases reasonably fast
                alpha = 0.3
            else:
                # Very slow release - heavily smooth out drops from file completion
                alpha = 0.05

            # Exponential moving average with asymmetric alpha
            self._fh_current_transfer_kbps = (alpha * averaged_kbps +
                                               (1 - alpha) * self._fh_current_transfer_kbps)

            # Convert to MiB/s for display
            mib_per_sec = self._fh_current_transfer_kbps / 1024.0

            # Aggregate with IMX.to bandwidth for total speed display
            # The Speed box shows combined upload speed from both IMX.to and file hosts
            total_kbps = mw.progress_tracker._current_transfer_kbps + self._fh_current_transfer_kbps
            total_mib = total_kbps / 1024.0
            speed_str = f"{total_mib:.3f} MiB/s"

            # Dim the text if speed is essentially zero
            if total_mib < 0.001:
                mw.speed_current_value_label.setStyleSheet("opacity: 0.4;")
            else:
                mw.speed_current_value_label.setStyleSheet("opacity: 1.0;")

            mw.speed_current_value_label.setText(speed_str)

            # Update fastest speed record if needed
            settings = QSettings("ImxUploader", "ImxUploadGUI")
            fastest_kbps = settings.value("fastest_kbps", 0.0, type=float)
            if total_kbps > fastest_kbps and total_kbps < 10000:  # Sanity check
                settings.setValue("fastest_kbps", total_kbps)
                # Save timestamp when new record is set
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                settings.setValue("fastest_kbps_timestamp", timestamp)
                fastest_mib = total_kbps / 1024.0
                fastest_str = f"{fastest_mib:.3f} MiB/s"
                mw.speed_fastest_value_label.setText(fastest_str)
                # Update tooltip with timestamp
                mw.speed_fastest_value_label.setToolTip(f"Record set: {timestamp}")

        except Exception as e:
            log(f"Error updating file host bandwidth: {e}", level="error", category="file_hosts")

    def on_file_host_storage_updated(self, host_id: str, total, left):
        """Handle file host storage update from worker.

        Args:
            host_id: Host identifier
            total: Total storage in bytes
            left: Free storage in bytes
        """
        # Storage updates are handled by FileHostsSettingsWidget if settings dialog is open
        # Main window doesn't need to display storage info
        log(
            f"[Main Window] Storage updated for {host_id}: {left}/{total} bytes",
            level="debug",
            category="file_hosts"
        )

    def on_file_host_test_completed(self, host_id: str, results: dict):
        """Handle file host test completion from worker.

        Args:
            host_id: Host identifier
            results: Test results dictionary
        """
        # Test results are handled by FileHostsSettingsWidget if settings dialog is open
        # Log result for main window
        tests_passed = sum([
            results.get('credentials_valid', False),
            results.get('user_info_valid', False),
            results.get('upload_success', False),
            results.get('delete_success', False)
        ])

    # =========================================================================
    # Worker Status Widget Signal Handlers
    # =========================================================================

    def _on_imx_worker_started(self, path: str, total_images: int):
        """Handle imx.to worker upload started."""
        mw = self._main_window
        if not hasattr(mw, 'worker_status_widget'):
            return  # Widget disabled, skip update

        mw.worker_status_widget.update_worker_status(
            worker_id="imx_worker_1",
            worker_type="imx",
            hostname="imx.to",
            speed_bps=0.0,
            status="uploading"
        )

    def _on_imx_worker_speed(self, speed_kbps: float):
        """Handle imx.to worker speed update."""
        mw = self._main_window
        if not hasattr(mw, 'worker_status_widget'):
            return  # Widget disabled, skip update

        mw.worker_status_widget.update_worker_status(
            worker_id="imx_worker_1",
            worker_type="imx",
            hostname="imx.to",
            speed_bps=speed_kbps * 1024,  # Convert KB/s to bytes/s
            status="uploading"
        )

    def _on_imx_worker_finished(self, *args):
        """Handle imx.to worker upload finished."""
        mw = self._main_window
        if not hasattr(mw, 'worker_status_widget'):
            return  # Widget disabled, skip update

        mw.worker_status_widget.update_worker_status(
            worker_id="imx_worker_1",
            worker_type="imx",
            hostname="imx.to",
            speed_bps=0.0,
            status="idle"
        )

    def _on_filehost_worker_started(self, db_id: int, host_name: str):
        """Handle file host worker upload started."""
        mw = self._main_window
        if not hasattr(mw, 'worker_status_widget'):
            return  # Widget disabled, skip update

        worker_id = f"filehost_{host_name.lower().replace(' ', '_')}"
        mw.worker_status_widget.update_worker_status(
            worker_id=worker_id,
            worker_type="filehost",
            hostname=host_name,
            speed_bps=0.0,
            status="uploading"
        )

    def _on_filehost_worker_progress(self, db_id: int, host_name: str,
                                      uploaded: int, total: int, speed_bps: float):
        """Handle file host worker upload progress."""
        mw = self._main_window
        if not hasattr(mw, 'worker_status_widget'):
            return  # Widget disabled, skip update

        worker_id = f"filehost_{host_name.lower().replace(' ', '_')}"
        mw.worker_status_widget.update_worker_status(
            worker_id=worker_id,
            worker_type="filehost",
            hostname=host_name,
            speed_bps=speed_bps,
            status="uploading"
        )
        mw.worker_status_widget.update_worker_progress(
            worker_id=worker_id,
            gallery_id=db_id,
            progress_bytes=uploaded,
            total_bytes=total
        )

    def _on_filehost_worker_completed(self, db_id: int, host_name: str, result: dict):
        """Handle file host worker upload completion."""
        mw = self._main_window
        if not hasattr(mw, 'worker_status_widget'):
            return  # Widget disabled, skip update

        worker_id = f"filehost_{host_name.lower().replace(' ', '_')}"
        mw.worker_status_widget.update_worker_status(
            worker_id=worker_id,
            worker_type="filehost",
            hostname=host_name,
            speed_bps=0.0,
            status="idle"
        )

    def _on_filehost_worker_failed(self, db_id: int, host_name: str, error: str):
        """Handle file host worker upload failure."""
        mw = self._main_window
        if not hasattr(mw, 'worker_status_widget'):
            return  # Widget disabled, skip update

        worker_id = f"filehost_{host_name.lower().replace(' ', '_')}"
        mw.worker_status_widget.update_worker_error(worker_id, error)

    def _on_file_host_startup_spinup(self, host_id: str, error: str):
        """Track worker spinup during startup to know when all are ready."""
        mw = self._main_window

        with QMutexLocker(mw._file_host_startup_mutex):
            log(f"Worker {host_id} spinup complete (error={error}), "
                f"completed={mw._file_host_startup_completed+1}/{mw._file_host_startup_expected}",
                level="debug", category="startup")

            if mw._file_host_startup_complete:
                log(f"Already complete, ignoring {host_id}", level="debug", category="startup")
                return

            mw._file_host_startup_completed += 1

            # Initialize queue display for this host (shows pending uploads from DB)
            if not error:
                self._update_filehost_queue_for_host(host_id)

            if mw._file_host_startup_completed >= mw._file_host_startup_expected:
                mw._file_host_startup_complete = True
                log(f"All {mw._file_host_startup_expected} workers complete, startup finished",
                    level="info", category="startup")

    def _on_worker_status_updated(self, host_id: str, status_text: str):
        """Handle worker status updates during spinup."""
        mw = self._main_window
        log(f"Worker {host_id} status: {status_text}", level="debug", category="file_hosts")

        worker_id = f"filehost_{host_id.lower().replace(' ', '_')}"
        if hasattr(mw, 'worker_status_widget') and mw.worker_status_widget:
            # Get worker if exists, or use defaults for new worker
            worker = mw.worker_status_widget._workers.get(worker_id)
            if worker:
                # Update existing worker
                mw.worker_status_widget.update_worker_status(
                    worker_id=worker_id,
                    worker_type='filehost',
                    hostname=worker.hostname,
                    speed_bps=worker.speed_bps,
                    status=status_text
                )
            else:
                # Create new worker with this status
                mw.worker_status_widget.update_worker_status(
                    worker_id=worker_id,
                    worker_type='filehost',
                    hostname=host_id,  # Use host_id as display name
                    speed_bps=0.0,
                    status=status_text
                )

    def _on_enabled_workers_changed(self, enabled_host_ids: list) -> None:
        """Remove workers from status widget when they are disabled.

        Args:
            enabled_host_ids: List of currently enabled file host IDs
        """
        mw = self._main_window
        if not hasattr(mw, 'worker_status_widget') or not mw.worker_status_widget:
            return

        # Build set of currently enabled worker IDs
        enabled_worker_ids = {f"filehost_{host_id.lower().replace(' ', '_')}"
                             for host_id in enabled_host_ids}

        # Find file host workers that are no longer enabled and remove them
        workers_to_remove = []
        for worker_id in list(mw.worker_status_widget._workers.keys()):
            if worker_id.startswith('filehost_') and worker_id not in enabled_worker_ids:
                workers_to_remove.append(worker_id)

        for worker_id in workers_to_remove:
            mw.worker_status_widget.remove_worker(worker_id)

    def _update_worker_queue_stats(self):
        """Poll queue manager and update worker status widget with queue statistics.

        Calculates total files and bytes remaining across all galleries in queue
        and updates the worker status widget's Files Left and Remaining columns.

        Called by QTimer every 2 seconds.
        """
        mw = self._main_window
        if not hasattr(mw, 'queue_manager') or not hasattr(mw, 'worker_status_widget'):
            return

        try:
            # Calculate totals from queue
            total_files_remaining = 0
            total_bytes_remaining = 0

            for item in mw.queue_manager.get_all_items():
                # Count files/bytes for galleries that are uploading or queued
                from src.core.constants import QUEUE_STATE_UPLOADING, QUEUE_STATE_QUEUED
                if item.status in (QUEUE_STATE_UPLOADING, QUEUE_STATE_QUEUED):
                    # Files remaining = total - uploaded
                    files_remaining = item.total_images - item.uploaded_images
                    if files_remaining > 0:
                        total_files_remaining += files_remaining

                    # Bytes remaining = total - uploaded
                    bytes_remaining = item.total_size - item.uploaded_bytes
                    if bytes_remaining > 0:
                        total_bytes_remaining += bytes_remaining

            # Update worker status widget
            mw.worker_status_widget.update_queue_columns(total_files_remaining, total_bytes_remaining)

        except Exception as e:
            log(f"Error updating worker queue stats: {e}", level="error", category="ui")
