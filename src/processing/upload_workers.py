#!/usr/bin/env python3
"""
Upload worker threads for imxup
Handles gallery uploads and completion tracking in background threads
"""

import os
import time
import threading
from typing import Optional, Dict, Any

from PyQt6.QtCore import QThread, pyqtSignal, QMutex

from imxup import (
    timestamp, load_user_defaults, rename_all_unnamed_with_session,
    save_gallery_artifacts, get_unnamed_galleries
)
from src.network.client import GUIImxToUploader
from src.utils.logger import log
from src.storage.queue_manager import GalleryQueueItem
from src.core.engine import AtomicCounter


class UploadWorker(QThread):
    """Worker thread for uploading galleries"""

    # Signals for communication with GUI
    progress_updated = pyqtSignal(str, int, int, int, str)  # path, completed, total, progress%, current_image
    gallery_started = pyqtSignal(str, int)  # path, total_images
    gallery_completed = pyqtSignal(str, dict)  # path, results
    gallery_failed = pyqtSignal(str, str)  # path, error_message
    gallery_exists = pyqtSignal(str, list)  # gallery_name, existing_files
    gallery_renamed = pyqtSignal(str)  # gallery_id
    ext_fields_updated = pyqtSignal(str, dict)  # path, ext_fields dict (for hook results)
    log_message = pyqtSignal(str)
    queue_stats = pyqtSignal(dict)  # aggregate status stats for GUI updates
    bandwidth_updated = pyqtSignal(float)  # Instantaneous KB/s from pycurl progress callbacks

    def __init__(self, queue_manager):
        """Initialize upload worker with queue manager"""
        super().__init__()
        self.queue_manager = queue_manager
        self.uploader = None
        self.running = True
        self.current_item = None
        self._soft_stop_requested_for = None
        self.auto_rename_enabled = True
        self._stats_last_emit = 0.0

        # Bandwidth tracking counters
        self.global_byte_counter = AtomicCounter()  # Persistent across ALL galleries (Speed box)
        self.current_gallery_counter: Optional[AtomicCounter] = None  # Per-gallery running average

        # Bandwidth calculation state - initialize to current counter to avoid initial spike
        self._bw_last_bytes = self.global_byte_counter.get()
        self._bw_last_time = time.time()
        self._bw_last_emit = 0.0

        # Initialize RenameWorker support
        self.rename_worker = None
        self._rename_worker_available = True
        try:
            from src.processing.rename_worker import RenameWorker
        except Exception as e:
            log(f"RenameWorker import failed: {e}", level="error", category="renaming")
            self._rename_worker_available = False


    def stop(self):
        """Stop the worker thread"""
        self.running = False
        # Cleanup RenameWorker
        if hasattr(self, 'rename_worker') and self.rename_worker:
            try:
                self.rename_worker.stop()
            except Exception as e:
                log(f"Error stopping RenameWorker: {e}", level="error", category="renaming")
        self.wait()

    def request_soft_stop_current(self):
        """Request to stop the current item after in-flight uploads finish"""
        if self.current_item:
            self._soft_stop_requested_for = self.current_item.path

    def run(self):
        """Main worker thread loop"""
        try:
            # Initialize uploader and perform initial login
            self._initialize_uploader()

            # Main processing loop
            while self.running:
                # Get next item from queue
                item = self.queue_manager.get_next_item()

                if item is None:
                    # No items to process, emit stats and wait
                    self._emit_queue_stats()
                    time.sleep(0.1)
                    continue

                # Process items based on status
                if item.status == "queued":
                    self.current_item = item
                    self.upload_gallery(item)
                elif item.status == "paused":
                    # Skip paused items
                    self._emit_queue_stats()
                    time.sleep(0.1)
                else:
                    # Unexpected status, skip
                    self._emit_queue_stats()
                    time.sleep(0.1)

        except Exception as e:
            import traceback
            error_trace = traceback.format_exc()
            log(f"CRITICAL: Worker thread crashed: {error_trace}", level="critical", category="uploads")
            # Also print directly to ensure it's visible
            print(f"\n{'='*70}\nWORKER THREAD CRASH:\n{error_trace}\n{'='*70}\n", flush=True)

    def _initialize_uploader(self):
        """Initialize uploader with API-only mode and separate RenameWorker"""
        # Initialize custom GUI uploader with reference to this worker
        self.uploader = GUIImxToUploader(worker_thread=self)

        # Initialize RenameWorker with independent session
        if self._rename_worker_available:
            try:
                from src.processing.rename_worker import RenameWorker
                self.rename_worker = RenameWorker()
                log(f"UploadWorker (ID: {id(self)}) created RenameWorker (ID: {id(self.rename_worker)})", level="debug", category="renaming")
                log("RenameWorker initialized with independent session", category="renaming", level="debug")
            except Exception as e:
                log(f"ERROR: Failed to initialize RenameWorker: {e}", level="error", category="renaming")
                self.rename_worker = None
        else:
            log("RenameWorker not available (import failed)", level="info", category="renaming")

        # Uploader uses API ONLY - no login needed
        # RenameWorker handles its own login independently
        log("Uploader using API-only mode (no web login)", level="debug", category="auth")


    def upload_gallery(self, item: GalleryQueueItem):
        """Upload a single gallery"""
        # Start bandwidth polling thread for real-time updates
        import threading
        stop_polling = threading.Event()

        def poll_bandwidth():
            """Background thread that polls byte counter and emits bandwidth updates"""
            poll_last_bytes = self.global_byte_counter.get()  # Start from current cumulative value
            poll_last_time = time.time()

            while not stop_polling.is_set():
                time.sleep(0.2)  # Poll every 200ms

                try:
                    current_bytes = self.global_byte_counter.get()
                    current_time = time.time()

                    if current_bytes > poll_last_bytes:
                        time_diff = current_time - poll_last_time
                        if time_diff > 0:
                            instant_kbps = ((current_bytes - poll_last_bytes) / time_diff) / 1024.0
                            self.bandwidth_updated.emit(instant_kbps)
                            poll_last_bytes = current_bytes
                            poll_last_time = current_time
                except Exception:
                    pass

        polling_thread = threading.Thread(target=poll_bandwidth, daemon=True, name="BandwidthPoller")
        polling_thread.start()

        try:
            # Clear previous soft-stop request
            self._soft_stop_requested_for = None

            # Create per-gallery counter for running average
            self.current_gallery_counter = AtomicCounter()

            log(f"Starting upload: {item.name or os.path.basename(item.path)}", category="uploads", level="info")

            # Update status to uploading
            self.queue_manager.update_item_status(item.path, "uploading")
            item.start_time = time.time()

            # Execute "started" hook in background
            from src.processing.hooks_executor import execute_gallery_hooks
            def run_started_hook():
                try:
                    ext_fields = execute_gallery_hooks(
                        event_type='started',
                        gallery_path=item.path,
                        gallery_name=item.name,
                        tab_name=item.tab_name,
                        image_count=item.total_images or 0
                    )
                    # Update ext fields if hook returned any
                    if ext_fields:
                        for key, value in ext_fields.items():
                            setattr(item, key, value)
                        self.queue_manager._schedule_debounced_save([item.path])
                        log(f"Updated ext fields from started hook: {ext_fields}", level="info", category="hooks")
                        # Emit signal to update GUI
                        self.ext_fields_updated.emit(item.path, ext_fields)
                except Exception as e:
                    log(f"Error executing started hook: {e}", level="error", category="hooks")

            threading.Thread(target=run_started_hook, daemon=True).start()

            # Emit start signal
            self.gallery_started.emit(item.path, item.total_images or 0)
            self._emit_queue_stats(force=True)

            # Check for early soft stop request
            if getattr(self, '_soft_stop_requested_for', None) == item.path:
                self.queue_manager.update_item_status(item.path, "incomplete")
                return

            # Get upload settings
            defaults = load_user_defaults()

            # Pass the item directly for precalculated dimensions (engine uses getattr on it)
            if item.scan_complete and (item.avg_width or item.avg_height):
                log(f"Using precalculated dimensions for {item.name}: {item.avg_width}x{item.avg_height}", level="debug", category="uploads")

            # Perform upload with both global and per-gallery counters
            results = self.uploader.upload_folder(
                item.path,
                gallery_name=item.name,
                thumbnail_size=defaults.get('thumbnail_size', 3),
                thumbnail_format=defaults.get('thumbnail_format', 2),
                max_retries=defaults.get('max_retries', 3),
                parallel_batch_size=defaults.get('parallel_batch_size', 4),
                template_name=item.template_name,
                precalculated_dimensions=item,  # Pass item directly, engine extracts dimensions via getattr
                global_byte_counter=self.global_byte_counter,
                gallery_byte_counter=self.current_gallery_counter
            )

            # Handle paused state
            if item.status == "paused":
                log(f"Upload paused: {item.name}", level="info", category="uploads")
                return

            # Process results
            self._process_upload_results(item, results)

        except Exception as e:
            import traceback
            error_msg = str(e)
            error_trace = traceback.format_exc()
            log(f"Error uploading {item.name}: {error_msg}\n{error_trace}", level="error", category="uploads")
            item.error_message = error_msg
            self.queue_manager.mark_upload_failed(item.path, error_msg)
            self.gallery_failed.emit(item.path, error_msg)
        finally:
            # Stop bandwidth polling thread
            stop_polling.set()
            polling_thread.join(timeout=0.5)

            # Clear gallery counter
            self.current_gallery_counter = None

    def _process_upload_results(self, item: GalleryQueueItem, results: Optional[Dict[str, Any]]):
        """Process upload results and update item status"""
        if not results:
            # Handle failed upload
            if self._soft_stop_requested_for == item.path:
                self.queue_manager.update_item_status(item.path, "incomplete")
                item.status = "incomplete"
                log(f"Marked incomplete: {item.name}", level="info", category="uploads")
            else:
                self.queue_manager.mark_upload_failed(item.path, "Upload failed")
                self.gallery_failed.emit(item.path, "Upload failed")

            self._emit_queue_stats(force=True)
            return

        # Update item with results
        item.end_time = time.time()
        item.gallery_url = results.get('gallery_url', '')
        item.gallery_id = results.get('gallery_id', '')

        # Check for incomplete upload due to soft stop
        if (self._soft_stop_requested_for == item.path and
            results.get('successful_count', 0) < (item.total_images or 0)):
            self.queue_manager.update_item_status(item.path, "incomplete")
            item.status = "incomplete"
            log(f"Marked incomplete: {item.name}", level="info", category="uploads")
            return

        # Save artifacts
        artifact_paths = self._save_artifacts_for_result(item, results)

        # Determine final status
        failed_count = results.get('failed_count', 0)
        if failed_count and results.get('successful_count', 0) > 0:
            # Partial failure - some images uploaded successfully but others failed
            failed_files = results.get('failed_details', [])
            self.queue_manager.mark_upload_failed(item.path, f"Partial upload failure: {failed_count} images failed", failed_files)
        else:
            # Complete success
            self.queue_manager.update_item_status(item.path, "completed")

            # Execute "completed" hook in background
            from src.processing.hooks_executor import execute_gallery_hooks
            def run_completed_hook():
                try:
                    # Get artifact paths
                    json_path = ''
                    bbcode_path = ''
                    if artifact_paths:
                        # Try uploaded location first, then central
                        if 'uploaded' in artifact_paths:
                            json_path = artifact_paths['uploaded'].get('json', '')
                            bbcode_path = artifact_paths['uploaded'].get('bbcode', '')
                        elif 'central' in artifact_paths:
                            json_path = artifact_paths['central'].get('json', '')
                            bbcode_path = artifact_paths['central'].get('bbcode', '')

                    ext_fields = execute_gallery_hooks(
                        event_type='completed',
                        gallery_path=item.path,
                        gallery_name=item.name,
                        tab_name=item.tab_name,
                        image_count=results.get('successful_count', 0),
                        gallery_id=results.get('gallery_id', ''),
                        json_path=json_path,
                        bbcode_path=bbcode_path,
                        zip_path=''  # ZIP support not implemented yet
                    )
                    # Update ext fields if hook returned any
                    if ext_fields:
                        for key, value in ext_fields.items():
                            setattr(item, key, value)
                        self.queue_manager._schedule_debounced_save([item.path])
                        log(f"Updated ext fields from completed hook: {ext_fields}", level="info", category="hooks")
                        # Emit signal to update GUI
                        self.ext_fields_updated.emit(item.path, ext_fields)
                except Exception as e:
                    log(f"Error executing completed hook: {e}", level="error", category="hooks")

            threading.Thread(target=run_completed_hook, daemon=True).start()

        # Notify GUI
        self.gallery_completed.emit(item.path, results)
        self._emit_queue_stats(force=True)

    def _save_artifacts_for_result(self, item: GalleryQueueItem, results: dict):
        """Save gallery artifacts (BBCode, JSON) in worker thread. Returns artifact paths dict."""
        try:
            # Build custom fields dict including ext1-4
            custom_fields = {
                'custom1': item.custom1,
                'custom2': item.custom2,
                'custom3': item.custom3,
                'custom4': item.custom4,
                'ext1': item.ext1,
                'ext2': item.ext2,
                'ext3': item.ext3,
                'ext4': item.ext4,
            }
            written = save_gallery_artifacts(
                folder_path=item.path,
                results=results,
                template_name=item.template_name or "default",
                custom_fields=custom_fields,
            )
            # Artifact save successful, no need to log details here
            return written
        except Exception as e:
            log(f"Artifact save error: {e}", level="error", category="fileio")
            return {}

    def _emit_queue_stats(self, force: bool = False):
        """Emit queue statistics if needed"""
        now = time.time()
        if force or (now - self._stats_last_emit) > 1.0:
            try:
                stats = self.queue_manager.get_queue_stats()
                self.queue_stats.emit(stats)
                self._stats_last_emit = now
            except Exception:
                pass

    def _emit_current_bandwidth(self):
        """Calculate and emit current bandwidth from byte counter deltas"""
        try:
            current_time = time.time()
            current_bytes = self.global_byte_counter.get()

            # Throttle emissions to every 200ms minimum
            if (current_time - self._bw_last_emit) < 0.2:
                return

            # Calculate instantaneous bandwidth
            time_diff = current_time - self._bw_last_time
            if time_diff > 0:
                bytes_diff = current_bytes - self._bw_last_bytes
                if bytes_diff > 0:
                    instant_kbps = (bytes_diff / time_diff) / 1024.0
                    self.bandwidth_updated.emit(instant_kbps)
                    self._bw_last_emit = current_time

            # Update tracking
            self._bw_last_bytes = current_bytes
            self._bw_last_time = current_time
        except Exception:
            pass



class CompletionWorker(QThread):
    """Worker thread for handling gallery completion tasks"""

    # Signals for GUI communication
    bbcode_generated = pyqtSignal(str, str)  # path, bbcode
    log_message = pyqtSignal(str)
    artifact_written = pyqtSignal(str, dict)  # path, written_files

    def __init__(self):
        """Initialize completion worker"""
        super().__init__()
        self.queue = []
        self.running = True
        self._mutex = QMutex()

    def add_completion_task(self, item: GalleryQueueItem, results: dict):
        """Add a completion task to the queue"""
        try:
            self._mutex.lock()
            self.queue.append((item, results))
        finally:
            self._mutex.unlock()

    def stop(self):
        """Stop the worker thread"""
        self.running = False
        self.wait()

    def run(self):
        """Main worker loop for processing completion tasks"""
        while self.running:
            task = None

            # Get next task from queue
            try:
                self._mutex.lock()
                if self.queue:
                    task = self.queue.pop(0)
            finally:
                self._mutex.unlock()

            if task:
                item, results = task
                self._process_completion(item, results)
            else:
                time.sleep(0.1)

    def _process_completion(self, item: GalleryQueueItem, results: dict):
        """Process a single completion task"""
        try:
            # Generate BBCode
            from imxup import generate_bbcode_from_results
            bbcode = generate_bbcode_from_results(
                results,
                template_name=item.template_name or "default"
            )

            if bbcode:
                self.bbcode_generated.emit(item.path, bbcode)

            # Log artifact locations if available
            self._log_artifact_locations(results)

        except Exception as e:
            log(f"Completion processing error: {e}", level="error", category="uploads")

    def _log_artifact_locations(self, results: dict):
        """Log artifact save locations from results"""
        try:
            written = results.get('written_artifacts', {})
            if not written:
                return

            parts = []
            if written.get('central'):
                central_dir = os.path.dirname(list(written['central'].values())[0])
                parts.append(f"central: {central_dir}")
            if written.get('uploaded'):
                uploaded_dir = os.path.dirname(list(written['uploaded'].values())[0])
                parts.append(f"folder: {uploaded_dir}")

            if parts:
                log(f"Saved to {', '.join(parts)}", level="debug", category="fileio")

        except Exception:
            pass


class BandwidthTracker(QThread):
    """Background thread for tracking upload bandwidth"""

    bandwidth_updated = pyqtSignal(float)  # KB/s

    def __init__(self, upload_worker: Optional[UploadWorker] = None):
        """Initialize bandwidth tracker"""
        super().__init__()
        self.upload_worker = upload_worker
        self.running = True
        self._last_bytes = 0
        self._last_time = time.time()

    def stop(self):
        """Stop the bandwidth tracker"""
        self.running = False
        self.wait()

    def run(self):
        """Main loop for tracking bandwidth"""
        while self.running:
            try:
                if self.upload_worker and self.upload_worker.uploader:
                    current_bytes = getattr(self.upload_worker.uploader, 'total_bytes_uploaded', 0)
                    current_time = time.time()

                    if self._last_bytes > 0:
                        time_diff = current_time - self._last_time
                        bytes_diff = current_bytes - self._last_bytes

                        if time_diff > 0:
                            kb_per_sec = (bytes_diff / 1024) / time_diff
                            self.bandwidth_updated.emit(kb_per_sec)

                    self._last_bytes = current_bytes
                    self._last_time = current_time

                time.sleep(1.0)  # Update every second

            except Exception:
                pass
