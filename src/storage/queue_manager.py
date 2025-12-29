"""
Queue Manager for ImxUp application.
Manages the gallery upload queue with persistence and state tracking.
"""

import os
import time
import threading
import queue
from queue import Queue
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from contextlib import contextmanager

from PyQt6.QtCore import QObject, pyqtSignal, QMutex, QMutexLocker, QSettings, QTimer

from src.storage.database import QueueStore
from imxup import sanitize_gallery_name, load_user_defaults, timestamp
from src.utils.logger import log
from src.core.constants import (
    QUEUE_STATE_READY, QUEUE_STATE_QUEUED, QUEUE_STATE_UPLOADING,
    QUEUE_STATE_COMPLETED, QUEUE_STATE_FAILED, QUEUE_STATE_SCAN_FAILED,
    QUEUE_STATE_UPLOAD_FAILED, QUEUE_STATE_PAUSED, QUEUE_STATE_INCOMPLETE,
    QUEUE_STATE_SCANNING, QUEUE_STATE_VALIDATING,
    IMAGE_EXTENSIONS
)


@dataclass
class GalleryQueueItem:
    """Represents a gallery in the upload queue"""
    path: str
    name: Optional[str] = None
    status: str = QUEUE_STATE_READY
    progress: int = 0
    total_images: int = 0
    uploaded_images: int = 0
    current_image: str = ""
    gallery_url: str = ""
    gallery_id: str = ""
    db_id: Optional[int] = None  # Database primary key ID
    error_message: str = ""
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    insertion_order: int = 0
    added_time: Optional[float] = None
    finished_time: Optional[float] = None
    template_name: str = "default"
    
    # Pre-scan metadata
    total_size: int = 0
    avg_width: float = 0.0
    avg_height: float = 0.0
    max_width: float = 0.0
    max_height: float = 0.0
    min_width: float = 0.0
    min_height: float = 0.0
    scan_complete: bool = False
    
    # Failed validation details
    failed_files: list = field(default_factory=list)
    
    # Resume support
    uploaded_files: set = field(default_factory=set)
    uploaded_images_data: list = field(default_factory=list)
    uploaded_bytes: int = 0
    
    # Runtime transfer metrics
    current_kibps: float = 0.0
    final_kibps: float = 0.0
    
    
    # Tab organization
    tab_name: str = "Main"
    
    # Custom fields
    custom1: str = ""
    custom2: str = ""
    custom3: str = ""
    custom4: str = ""

    # External program result fields
    ext1: str = ""
    ext2: str = ""
    ext3: str = ""
    ext4: str = ""

    # Archive support
    source_archive_path: Optional[str] = None
    is_from_archive: bool = False

    # IMX status fields
    imx_status: str = ""
    imx_status_checked: Optional[int] = None


class QueueManager(QObject):
    """Manages the gallery upload queue with persistence"""
    
    # Signals
    status_changed = pyqtSignal(str, str, str)  # path, old_status, new_status
    queue_loaded = pyqtSignal()
    log_message = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self.items: Dict[str, GalleryQueueItem] = {}
        self.queue = Queue()
        self.mutex = QMutex()
        self.settings = QSettings("ImxUploader", "QueueManager")
        self.store = QueueStore()
        self._next_order = 0
        self._next_db_id = 1  # Track next database ID for predictive assignment
        self._version = 0
        
        # Batch mode for deferred database saves
        self._batch_mode = False
        self._batched_changes = set()
        
        # Guard against overlapping saves
        self._pending_save_timer = None
        
        # Status counters for efficient updates
        self._status_counts = {
            QUEUE_STATE_READY: 0,
            QUEUE_STATE_PAUSED: 0,
            QUEUE_STATE_INCOMPLETE: 0,
            QUEUE_STATE_SCANNING: 0,
            QUEUE_STATE_UPLOADING: 0,
            QUEUE_STATE_QUEUED: 0,
            QUEUE_STATE_COMPLETED: 0,
            QUEUE_STATE_FAILED: 0,
            QUEUE_STATE_VALIDATING: 0
        }
        
        # Sequential scan worker
        self._scan_worker = None
        self._scan_queue = Queue()
        self._scan_worker_running = False
        
        # Migration and initialization
        try:
            self.store.migrate_from_qsettings_if_needed(self.settings)
        except Exception:
            pass
        self.load_persistent_queue()
        self._start_scan_worker()
    
    def _start_scan_worker(self):
        """Start the sequential scan worker thread"""
        #log(f" _start_scan_worker called, running={self._scan_worker_running}")
        if not self._scan_worker_running:
            self._scan_worker_running = True
            self._scan_worker = threading.Thread(
                target=self._sequential_scan_worker,
                daemon=True
            )
            self._scan_worker.start()
            import traceback
            caller = traceback.extract_stack()[-2]
            log(f"Scan Worker: thread started (called from {caller.filename}:{caller.lineno} in {caller.name})", level="debug", category="scan")
    
    def _sequential_scan_worker(self):
        """Worker that processes galleries sequentially"""
        #log(f" Scan worker starting")
        while self._scan_worker_running:
            try:
                path = self._scan_queue.get(timeout=1.0)
                if path is None:  # Shutdown signal
                    break
                #print(f"DEBUG: About to scan path: {path}")
                self._comprehensive_scan_item(path)
                #log(f" Scan completed for {path}")
                log(f"Scan Worker: Scan completed for {path}", category="scan", level="debug")
                self._scan_queue.task_done()
                
            except queue.Empty:
                continue
            except Exception as e:
                # Already logged above with log()
                log(f"Scan Worker: Error scanning {path}: {e}", level="error", category="scan")
                try:
                    self._scan_queue.task_done()
                except ValueError:
                    pass
    
    def _comprehensive_scan_item(self, path: str):
        """Scan and validate a gallery item"""
        try:
            # Validation
            if not os.path.exists(path) or not os.path.isdir(path):
                self._mark_item_failed(path, "Path does not exist or is not a directory")
                #log(f" Scan completed for {path}")
                #log(f" [scan] Path does not exist or is not a directory: {path}")
                log(f"Scan Worker: Path does not exist or is not a directory: {path}", level="warning", category="scan")
                return
            
            # Find images
            files = self._get_image_files(path)
            if not files:
                self.mark_scan_failed(path, "No images found")
                log(f"Scan Worker: No images found: {path}", level="warning", category="scan")
                #log(f" [scan] No images found: {path}")
                return
            
            # Check for existing gallery
            with QMutexLocker(self.mutex):
                if path not in self.items:
                    return
                item = self.items[path]
                
                # Duplicate checking now handled at GUI level with user dialogs
                # No longer silently failing duplicates here
                
                item.total_images = len(files)
                item.status = QUEUE_STATE_SCANNING
            
            # Scan images
            scan_result = self._scan_images(path, files)
            
            if scan_result['failed_files']:
                self._mark_item_failed(
                    path,
                    f"Validation failed: {len(scan_result['failed_files'])}/{len(files)} images invalid",
                    scan_result['failed_files']
                )
                log(f"Scan Worker: Validation failed: {len(scan_result['failed_files'])}/{len(files)} images invalid", level="warning", category="scan")
                return
            
            # Update item with scan results
            with QMutexLocker(self.mutex):
                if path in self.items:
                    item = self.items[path]
                    item.total_size = scan_result['total_size']
                    item.avg_width = scan_result['avg_width']
                    item.avg_height = scan_result['avg_height']
                    item.max_width = scan_result['max_width']
                    item.max_height = scan_result['max_height']
                    item.min_width = scan_result['min_width']
                    item.min_height = scan_result['min_height']
                    item.scan_complete = True
                    
                    if item.status == QUEUE_STATE_SCANNING:
                        log(f"Scan Worker: Scan complete, updating status to ready for {path}", level="debug", category="scan")
                        #print(f"DEBUG: Item tab_name is still: '{item.tab_name}'")
                        old_status = item.status
                        item.status = QUEUE_STATE_READY
                        log(f"Scan Worker: Status changed from {old_status} to {QUEUE_STATE_READY}", level="debug", category="scan")
                        #print(f"DEBUG: After status change - item tab_name = '{item.tab_name}'")
                        
                        # CRITICAL: Save immediately now that status is "ready" (no longer "validating")
                        # This ensures the gallery is saved to the correct tab in the database
                        #print(f"DEBUG: SAVING TO DATABASE NOW - status is ready, tab_name='{item.tab_name}'")
                        
                        # Check if auto-start uploads is enabled
                        # load_user_defaults already imported from imxup at top of file
                        defaults = load_user_defaults()
                        if defaults.get('auto_start_upload', False):
                            log(f"Auto-start enabled: queuing {path} for upload", level="debug", category="queue")
                            
                            # Auto-start the upload by changing status to queued and adding to queue
                            self._update_status_count(old_status, QUEUE_STATE_QUEUED)
                            item.status = QUEUE_STATE_QUEUED
                            self.queue.put(item)  # CRITICAL: Add to queue so worker picks it up
                            log(f"Auto-queued {path} for immediate upload", level="debug", category="queue")

                        # Emit signal directly (we're already in mutex lock)
                        #print(f"DEBUG: EMITTING status_changed signal for {path}")
                        self.status_changed.emit(path, old_status, item.status)
                        #print(f"DEBUG: status_changed signal emitted")
            
            # Save to database immediately now that scan is complete and status is "ready"
            from PyQt6.QtCore import QTimer
            #print(f"DEBUG: Scheduling IMMEDIATE save for {path} with tab_name='{item.tab_name}'")
            # Capture the path in a closure-safe way
            saved_path = path
            # Save and then refresh the filter to show the item in the correct tab
            def save_and_refresh():
                #print(f"DEBUG: Executing save_and_refresh for {saved_path}")
                self.save_persistent_queue([saved_path])
                #print(f"DEBUG: Saved {saved_path} to database, emitting refresh signal")
                # Emit a signal to refresh the tab filter after save
                from PyQt6.QtCore import QTimer as QT2
                QT2.singleShot(50, lambda: self.status_changed.emit(saved_path, "save_complete", "refresh_filter"))
            QTimer.singleShot(0, save_and_refresh)
            self._inc_version()
            
        except Exception as e:
            self.mark_scan_failed(path, f"Scan error: {e}")
            log(f"Scan Worker: Scan error: {e}", level="error", category="scan")
    
    def _get_image_files(self, path: str) -> List[str]:
        """Get list of image files in directory"""
        files = []
        for f in os.listdir(path):
            if f.lower().endswith(IMAGE_EXTENSIONS):
                fp = os.path.join(path, f)
                if os.path.isfile(fp):
                    files.append(f)
        return files
    
    def _scan_images(self, path: str, files: List[str]) -> dict:
        """Scan images for validation and metadata"""
        gallery_name = os.path.basename(path)

        result: dict[str, Any] = {
            'total_size': 0,
            'failed_files': [],
            'avg_width': 0.0,
            'avg_height': 0.0,
            'max_width': 0.0,
            'max_height': 0.0,
            'min_width': 0.0,
            'min_height': 0.0
        }

        # Get scan configuration
        config = self._get_scanning_config()
        use_fast = config.get('fast_scan', True)
        sampling = config.get('pil_sampling', 2)

        log(f"Scan Worker: Starting scan of {len(files)} files for '{gallery_name}' (fast_scan={use_fast}, sampling={sampling})", level="debug", category="scan")
        
        # Scan files
        if use_fast:
            # Try to import imghdr, fall back to PIL-only if unavailable
            try:
                import imghdr
                has_imghdr = True
            except ImportError:
                has_imghdr = False
                log("imghdr not available, using PIL-only validation", level="debug", category="scan")

            from PIL import Image

            for i, f in enumerate(files):
                fp = os.path.join(path, f)
                try:
                    result['total_size'] += os.path.getsize(fp)

                    # Validate with imghdr if available, otherwise use PIL directly
                    if has_imghdr:
                        with open(fp, 'rb') as img:
                            if not imghdr.what(img):
                                # imghdr failed - verify with PIL (more robust for some formats)
                                try:
                                    with Image.open(fp) as pil_img:
                                        pil_img.verify()  # Checks image integrity
                                except Exception as pil_error:
                                    # Both imghdr and PIL failed - mark as invalid
                                    result['failed_files'].append((f, f"Invalid image: {str(pil_error)}"))
                    else:
                        # No imghdr - use PIL-only validation
                        try:
                            with Image.open(fp) as pil_img:
                                pil_img.verify()  # Checks image integrity
                        except Exception as pil_error:
                            result['failed_files'].append((f, f"Invalid image: {str(pil_error)}"))

                except Exception as e:
                    result['failed_files'].append((f, str(e)))

                if i % 10 == 0:
                    time.sleep(0.001)  # Yield

        # Log validation results
        failed_count = len(result['failed_files'])
        if failed_count > 0:
            log(f"Scan Worker: Validation complete for '{gallery_name}': {failed_count}/{len(files)} files failed", level="warning", category="scan")
        else:
            log(f"Scan Worker: Validation complete for '{gallery_name}': All {len(files)} files valid, total size: {result['total_size'] / 1024 / 1024:.2f} MB", level="debug", category="scan")

        # Calculate dimensions with sampling
        if not result['failed_files']:
            dims = self._calculate_dimensions(path, files, sampling)
            if dims:
                # Use the outlier exclusion utility if configured
                from src.utils.sampling_utils import calculate_dimensions_with_outlier_exclusion
                settings = QSettings("ImxUploader", "ImxUploadGUI")
                exclude_outliers = settings.value('scanning/stats_exclude_outliers', False, type=bool)
                use_median = settings.value('scanning/use_median', True, type=bool)

                stats = calculate_dimensions_with_outlier_exclusion(dims, exclude_outliers, use_median)
                result['avg_width'] = stats['avg_width']
                result['avg_height'] = stats['avg_height']
                result['max_width'] = stats['max_width']
                result['max_height'] = stats['max_height']
                result['min_width'] = stats['min_width']
                result['min_height'] = stats['min_height']
        
        return result
    
    def _calculate_dimensions(self, path: str, files: List[str], sampling: int) -> List[tuple]:
        """Calculate image dimensions with sampling"""
        gallery_name = os.path.basename(path)
        dims = []

        try:
            from PIL import Image

            # Use new sampling utility
            from src.utils.sampling_utils import get_sample_indices, calculate_dimensions_with_outlier_exclusion

            # Get enhanced config from settings (use same location as main GUI)
            settings = QSettings("ImxUploader", "ImxUploadGUI")
            enhanced_config = {
                'sampling_method': settings.value('scanning/sampling_method', 0, type=int),
                'sampling_fixed_count': settings.value('scanning/sampling_fixed_count', 25, type=int),
                'sampling_percentage': settings.value('scanning/sampling_percentage', 10, type=int),
                'exclude_first': settings.value('scanning/exclude_first', False, type=bool),
                'exclude_last': settings.value('scanning/exclude_last', False, type=bool),
                'exclude_small_images': settings.value('scanning/exclude_small_images', False, type=bool),
                'exclude_small_threshold': settings.value('scanning/exclude_small_threshold', 50, type=int),
                'exclude_patterns': settings.value('scanning/exclude_patterns', False, type=bool),
                'exclude_patterns_text': settings.value('scanning/exclude_patterns_text', '', type=str),
            }

            log(f"Scan Worker: Dimension sampling: method={enhanced_config['sampling_method']}, fixed={enhanced_config['sampling_fixed_count']}, pct={enhanced_config['sampling_percentage']}% for '{gallery_name}'", level="debug", category="scan")

            # Get sample indices using new logic
            sample_indices = get_sample_indices(files, enhanced_config, path)
            samples = [files[i] for i in sample_indices]

            log(f"Scan Worker: Sampling {len(samples)} of {len(files)} files for dimensions for '{gallery_name}'", level="debug", category="scan")

            # Process samples
            for f in samples:
                fp = os.path.join(path, f)
                try:
                    with Image.open(fp) as img:
                        dims.append(img.size)
                except (OSError, IOError):
                    continue

            log(f"Scan Worker: Successfully read dimensions from {len(dims)}/{len(samples)} sampled files for '{gallery_name}'", level="debug", category="scan")

        except ImportError as e:
            log(f"Scan Worker: Import error in dimension calculation for '{gallery_name}': {e}", level="error", category="scan")
        except Exception as e:
            log(f"Scan Worker: Error calculating dimensions for '{gallery_name}': {e}", level="error", category="scan")

        return dims
    
    def _mark_item_failed(self, path: str, error: str, failed_files: list | None = None):
        """Mark an item as failed (generic)"""
        with QMutexLocker(self.mutex):
            if path in self.items:
                item = self.items[path]
                item.status = QUEUE_STATE_FAILED
                item.error_message = error
                item.scan_complete = True
                if failed_files:
                    item.failed_files = failed_files
        
        self._schedule_debounced_save([path])
        self._inc_version()
    
    def mark_scan_failed(self, path: str, error: str):
        """Mark an item as scan failed (folder issues, no images, permissions)"""
        with QMutexLocker(self.mutex):
            if path in self.items:
                item = self.items[path]
                item.status = QUEUE_STATE_SCAN_FAILED
                item.error_message = error
                item.scan_complete = True
                
                # Log scan failure
                from imxup import timestamp
                log(f"Scan failed - {item.name or os.path.basename(path)}: {error}", level="warning", category="scan")
                
        
        self._schedule_debounced_save([path])
        self._inc_version()
    
    def mark_upload_failed(self, path: str, error: str, failed_files: list | None = None):
        """Mark an item as upload failed (network issues, API problems, server errors)"""
        with QMutexLocker(self.mutex):
            if path in self.items:
                item = self.items[path]
                item.status = QUEUE_STATE_UPLOAD_FAILED
                item.error_message = error
                item.scan_complete = True
                if failed_files:
                    item.failed_files = failed_files
                
                # Log upload failure with details
                log_msg = f"{item.name or os.path.basename(path)}: {error}"
                if failed_files:
                    log_msg += f" ({len(failed_files)} files failed)"
                log(log_msg, level="error", category="uploads")
        
        self._schedule_debounced_save([path])
        self._inc_version()
    
    def retry_failed_upload(self, path: str):
        """Retry a failed upload, preserving successful uploads for partial failures"""
        with QMutexLocker(self.mutex):
            if path in self.items:
                item = self.items[path]
                if item.status in [QUEUE_STATE_UPLOAD_FAILED, QUEUE_STATE_FAILED]:
                    old_status = item.status
                    
                    # Check if this was a partial failure with some successful uploads
                    has_successful_uploads = (
                        hasattr(item, 'gallery_id') and item.gallery_id and
                        hasattr(item, 'uploaded_images') and item.uploaded_images > 0
                    )
                    
                    if has_successful_uploads:
                        # Partial failure - mark as incomplete to preserve successful uploads
                        item.status = QUEUE_STATE_INCOMPLETE
                        # Keep gallery_id and gallery_url
                        # Keep uploaded_images count
                        # Only clear error message and failed_files for retry
                        item.error_message = ""
                        failed_count = len(item.failed_files) if hasattr(item, 'failed_files') and item.failed_files else 0
                        remaining_images = (item.total_images or 0) - (item.uploaded_images or 0)
                        
                        from imxup import timestamp
                        log(f"Retrying {item.name or os.path.basename(path)}: {remaining_images} images ({item.uploaded_images} already uploaded)", category="queue")
                        
                        # Clear failed files list so they can be retried
                        item.failed_files = []
                    else:
                        # Complete failure - reset everything
                        item.status = QUEUE_STATE_READY
                        item.error_message = ""
                        item.failed_files = []
                        # Reset upload progress
                        item.uploaded_images = 0
                        item.progress = 0
                        
                        from imxup import timestamp
                        log(f"Full retry for {item.name or os.path.basename(path)}", level="debug", category="queue")
                    
                    # Emit status change signal
                    if hasattr(self, 'status_changed'):
                        QTimer.singleShot(0, lambda: self.status_changed.emit(path, old_status, item.status))
        
        self._schedule_debounced_save([path])
        self._inc_version()
    
    def rescan_gallery_additive(self, path: str):
        """Smart rescan - only detect new images, preserve existing uploads"""
        with QMutexLocker(self.mutex):
            if path in self.items:
                item = self.items[path]
                old_status = item.status
                
                try:
                    # Get current images in folder
                    current_files = set(self._get_image_files(path))
                    current_count = len(current_files)
                    previous_count = item.total_images or 0
                    
                    if current_count > previous_count:
                        # New images detected
                        new_images = current_count - previous_count
                        item.total_images = current_count
                        
                        # Update status appropriately
                        if item.status == QUEUE_STATE_COMPLETED:
                            item.status = QUEUE_STATE_INCOMPLETE
                        elif item.status in [QUEUE_STATE_SCAN_FAILED, QUEUE_STATE_UPLOAD_FAILED, QUEUE_STATE_FAILED]:
                            item.status = QUEUE_STATE_INCOMPLETE if (item.uploaded_images or 0) > 0 else QUEUE_STATE_READY
                        
                        # Update progress
                        if item.total_images > 0:
                            item.progress = int((item.uploaded_images or 0) / item.total_images * 100)
                        
                        item.scan_complete = True
                        item.error_message = ""
                        
                        from imxup import timestamp
                        uploaded = item.uploaded_images or 0
                        log(f"Rescan of {item.name or os.path.basename(path)}: Found {new_images} new images ({uploaded} uploaded, {current_count - uploaded} remaining)", category="scan")
                        
                    elif current_count < previous_count:
                        # Images were removed
                        removed = previous_count - current_count
                        item.total_images = current_count
                        
                        # Adjust uploaded count if necessary
                        if (item.uploaded_images or 0) > current_count:
                            item.uploaded_images = current_count
                        
                        # Recalculate progress
                        if item.total_images > 0:
                            item.progress = int((item.uploaded_images or 0) / item.total_images * 100)
                        
                        from imxup import timestamp
                        log(f"{item.name or os.path.basename(path)}: {removed} images removed, {current_count} total", category="scan")
                    else:
                        # Same count - just clear error if any, but preserve completed status
                        if item.status in [QUEUE_STATE_SCAN_FAILED, QUEUE_STATE_FAILED]:
                            item.status = QUEUE_STATE_INCOMPLETE if (item.uploaded_images or 0) > 0 else QUEUE_STATE_READY
                        # Keep completed galleries as completed if no changes
                        elif item.status == QUEUE_STATE_COMPLETED:
                            pass  # Don't change completed status when no files changed
                        item.error_message = ""
                        
                        from imxup import timestamp
                        log(f"{item.name or os.path.basename(path)}: No changes detected, cleared errors", category="scan")
                    
                    # Emit status change if changed
                    if hasattr(self, 'status_changed') and item.status != old_status:
                        QTimer.singleShot(0, lambda: self.status_changed.emit(path, old_status, item.status))
                    
                except Exception as e:
                    from imxup import timestamp
                    self.mark_scan_failed(path, f"Additive rescan error: {e}")
                    log(f"Additive rescan error: {e}", level="error", category="scan")
        
        self._schedule_debounced_save([path])
        self._inc_version()
    
    def reset_gallery_complete(self, path: str):
        """Complete gallery reset - clear everything and rescan from scratch"""
        with QMutexLocker(self.mutex):
            if path in self.items:
                item = self.items[path]
                old_status = item.status
                
                # Nuclear reset - clear everything
                item.status = QUEUE_STATE_SCANNING
                item.gallery_id = ""
                item.gallery_url = ""
                item.uploaded_images = 0
                item.total_images = 0
                item.progress = 0
                item.error_message = ""
                item.failed_files = []
                item.scan_complete = False
                item.start_time = None
                item.end_time = None
                item.uploaded_files = set()  # CRITICAL: Clear the set of uploaded filenames
                item.uploaded_images_data = []  # Clear uploaded image metadata
                item.uploaded_bytes = 0  # Clear uploaded bytes counter
                
                from imxup import timestamp
                log(f"{item.name or os.path.basename(path)}: Complete reset, starting fresh scan", category="scan")
                
                # Emit status change signal
                if hasattr(self, 'status_changed'):
                    QTimer.singleShot(0, lambda: self.status_changed.emit(path, old_status, QUEUE_STATE_SCANNING))
                
                # Trigger full rescan
                QTimer.singleShot(100, lambda: self._initiate_scan(path))
        
        self._inc_version()
    
    def rescan_failed_folder(self, path: str):
        """Legacy method - redirect to additive rescan for scan failures"""
        # For backwards compatibility, redirect scan failures to additive rescan
        with QMutexLocker(self.mutex):
            if path in self.items:
                item = self.items[path]
                if item.status in [QUEUE_STATE_SCAN_FAILED, QUEUE_STATE_FAILED]:
                    # For pure scan failures with no uploads, do complete reset
                    if not (hasattr(item, 'uploaded_images') and item.uploaded_images):
                        self.reset_gallery_complete(path)
                        return
        
        # Otherwise do additive rescan
        self.rescan_gallery_additive(path)
    
    def _initiate_scan(self, path: str):
        """Initiate background scan for a path using existing scan infrastructure"""
        # Use existing scan queue system if available
        if hasattr(self, 'request_folder_scan') and callable(self.request_folder_scan):
            self.request_folder_scan(path)
        else:
            # Fallback: add to scan queue directly
            QTimer.singleShot(0, lambda: self._add_to_scan_queue(path))
    
    def _add_to_scan_queue(self, path: str):
        """Add path to existing scan queue without duplicating logic"""
        try:
            # Use the existing scanning infrastructure
            if hasattr(self, 'scan_queue') and hasattr(self, 'scan_queue'):
                self.scan_queue.put(path)
            else:
                # If no scan queue system, just mark as ready and let existing validation catch issues
                with QMutexLocker(self.mutex):
                    if path in self.items:
                        item = self.items[path]
                        item.status = QUEUE_STATE_READY
                        item.scan_complete = True
                        from imxup import timestamp
                        log(f"{item.name or os.path.basename(path)}: Marked ready for validation", level="debug", category="scan")
                
                self._schedule_debounced_save([path])
                self._inc_version()
        except Exception as e:
            self.mark_scan_failed(path, f"Rescan queue error: {e}")
    
    def _get_scanning_config(self) -> dict:
        """Get scanning configuration"""
        try:
            settings = QSettings("ImxUploader", "ImxUploadGUI")
            return {
                'fast_scan': settings.value('scanning/fast_scan', True, type=bool),
                'pil_sampling': settings.value('scanning/pil_sampling', 2, type=int)
            }
        except Exception:
            return {'fast_scan': True, 'pil_sampling': 2}
    
    def _inc_version(self):
        """Increment version for change tracking"""
        self._version += 1
    
    def _schedule_debounced_save(self, paths: List[str]):
        """Schedule a debounced save to prevent overlapping database operations"""
        from PyQt6.QtCore import QTimer, QThread, QCoreApplication

        # Check if we're on the main thread
        app = QCoreApplication.instance()
        if app and QThread.currentThread() != app.thread():
            # We're not on the main thread, defer to main thread
            QTimer.singleShot(0, lambda: self._schedule_debounced_save(paths))
            return

        # Cancel any pending save
        if self._pending_save_timer:
            self._pending_save_timer.stop()
            self._pending_save_timer.deleteLater()
            self._pending_save_timer = None

        # Create new timer for debounced save (only on main thread)
        self._pending_save_timer = QTimer()
        self._pending_save_timer.setSingleShot(True)
        self._pending_save_timer.timeout.connect(lambda: self.save_persistent_queue(paths))
        self._pending_save_timer.start(100)  # 100ms debounce
    
    def get_version(self) -> int:
        """Get current version"""
        with QMutexLocker(self.mutex):
            return self._version
    
    @contextmanager
    def batch_updates(self):
        """Context manager for batching updates"""
        old_batch = self._batch_mode
        self._batch_mode = True
        self._batched_changes.clear()
        try:
            yield
        finally:
            if self._batched_changes:
                self.save_persistent_queue(list(self._batched_changes))
            self._batch_mode = old_batch
            self._batched_changes.clear()
    
    def _save_single_item(self, item):
        """Save a single item without iterating through all items"""
        try:
            item_data = {
                'path': item.path,
                'name': item.name,
                'status': item.status,
                'gallery_url': item.gallery_url,
                'gallery_id': item.gallery_id,
                'progress': item.progress,
                'uploaded_images': item.uploaded_images,
                'total_images': item.total_images,
                'template_name': item.template_name,
                'insertion_order': item.insertion_order,
                'added_time': item.added_time,
                'finished_time': item.finished_time,
                'tab_name': getattr(item, 'tab_name', ''),  # Include tab assignment
                'total_size': int(getattr(item, 'total_size', 0) or 0),
                'avg_width': float(getattr(item, 'avg_width', 0.0) or 0.0),
                'avg_height': float(getattr(item, 'avg_height', 0.0) or 0.0),
                'max_width': float(getattr(item, 'max_width', 0.0) or 0.0),
                'max_height': float(getattr(item, 'max_height', 0.0) or 0.0),
                'min_width': float(getattr(item, 'min_width', 0.0) or 0.0),
                'min_height': float(getattr(item, 'min_height', 0.0) or 0.0),
                'scan_complete': bool(getattr(item, 'scan_complete', False)),
                'uploaded_bytes': int(getattr(item, 'uploaded_bytes', 0) or 0),
                'final_kibps': float(getattr(item, 'final_kibps', 0.0) or 0.0),
                'failed_files': getattr(item, 'failed_files', []),
                'error_message': getattr(item, 'error_message', ''),
                'ext1': getattr(item, 'ext1', ''),
                'ext2': getattr(item, 'ext2', ''),
                'ext3': getattr(item, 'ext3', ''),
                'ext4': getattr(item, 'ext4', ''),
            }
            
            self.store.bulk_upsert_async([item_data])
            log(f"_save_single_item saved: {item.path}", level="debug", category="queue")
        except Exception as e:
            log(f"_save_single_item failed for {item.path}: {e}", level="error", category="queue")

    def save_persistent_queue(self, specific_paths: List[str] | None = None):
        """Save queue state to database"""
        log(f"save_persistent_queue called with {len(specific_paths) if specific_paths else 'all'} items", level="debug", category="queue")
        if self._batch_mode and specific_paths:
            log(f" In batch mode, adding to batched changes")
            self._batched_changes.update(specific_paths)
            return
        
        #print(f"DEBUG: Acquiring mutex for database save")
        with QMutexLocker(self.mutex):
            #print(f"DEBUG: Mutex acquired, preparing items list")
            if specific_paths:
                items = [self.items[p] for p in specific_paths if p in self.items]
                log(f"Found {len(items)} items for specific paths", level="debug", category="db")
            else:
                items = list(self.items.values())
                #print(f"DEBUG: Saving all {len(items)} items")
            
            queue_data = []
            log(f"Mutex acquired, building queue data for {len(items)} items", level="debug", category="db")
            for item in items:
                if item.status in [QUEUE_STATE_READY, QUEUE_STATE_QUEUED, QUEUE_STATE_PAUSED,
                                  QUEUE_STATE_COMPLETED, QUEUE_STATE_INCOMPLETE, QUEUE_STATE_FAILED,
                                  QUEUE_STATE_SCANNING, QUEUE_STATE_SCAN_FAILED, QUEUE_STATE_UPLOAD_FAILED]:
                    queue_data.append(self._item_to_dict(item))
            #print(f"DEBUG: Built queue data with {len(queue_data)} items to save")
            
            try:
                log(f"DEBUG: About to call store.bulk_upsert_async", level="debug", category="db")
                self.store.bulk_upsert_async(queue_data)
                log(f"DEBUG: SQLite: bulk_upsert_async database save completed", level="debug", category="db")
            except Exception as e:
                log(f"Database save failed: {e}", level="error", category="db")
                pass
    
    def _item_to_dict(self, item: GalleryQueueItem) -> dict:
        """Convert item to dictionary for storage"""
        #log(f"_item_to_dict converting {item.path} with tab_name='{item.tab_name}'", level="debug")
        return {
            'path': item.path,
            'name': item.name,
            'status': item.status,
            'gallery_url': item.gallery_url,
            'gallery_id': item.gallery_id,
            'db_id': item.db_id,
            'progress': item.progress,
            'uploaded_images': item.uploaded_images,
            'total_images': item.total_images,
            'template_name': item.template_name,
            'insertion_order': item.insertion_order,
            'added_time': item.added_time,
            'finished_time': item.finished_time,
            'tab_name': item.tab_name,
            'total_size': item.total_size,
            'avg_width': item.avg_width,
            'avg_height': item.avg_height,
            'max_width': item.max_width,
            'max_height': item.max_height,
            'min_width': item.min_width,
            'min_height': item.min_height,
            'scan_complete': item.scan_complete,
            'uploaded_bytes': item.uploaded_bytes,
            'final_kibps': item.final_kibps,
            'failed_files': item.failed_files,
            'error_message': item.error_message,
            'uploaded_files': list(item.uploaded_files),
            'uploaded_images_data': item.uploaded_images_data,
            'custom1': item.custom1,
            'custom2': item.custom2,
            'custom3': item.custom3,
            'custom4': item.custom4,
            'ext1': item.ext1,
            'ext2': item.ext2,
            'ext3': item.ext3,
            'ext4': item.ext4,
            'source_archive_path': item.source_archive_path,
            'is_from_archive': item.is_from_archive
        }
    
    def load_persistent_queue(self):
        """Load queue from database"""
        try:
            queue_data = self.store.load_all_items()
        except Exception:
            queue_data = []
        
        for data in queue_data:
            path = data.get('path', '')
            status = data.get('status', QUEUE_STATE_READY)
            
            # Skip invalid paths unless completed
            if status != QUEUE_STATE_COMPLETED:
                if not os.path.exists(path) or not os.path.isdir(path):
                    continue
            
            # Create item from data
            item = self._dict_to_item(data)
            self._next_order = max(self._next_order, item.insertion_order + 1)
            # Track next db_id for predictive assignment to new galleries
            if item.db_id:
                self._next_db_id = max(self._next_db_id, item.db_id + 1)
            self.items[path] = item
        
        self._rebuild_status_counts()
        self.queue_loaded.emit()
    
    def _dict_to_item(self, data: dict) -> GalleryQueueItem:
        """Create item from dictionary"""
        status = data.get('status', QUEUE_STATE_READY)
        if status in [QUEUE_STATE_QUEUED, QUEUE_STATE_UPLOADING]:
            status = QUEUE_STATE_READY
        
        # Ensure completed items have 100% progress
        progress = data.get('progress', 0)
        if status == 'completed':
            progress = 100
        elif status == QUEUE_STATE_INCOMPLETE:
            # For incomplete items, recalculate progress from uploaded/total images
            uploaded_images = data.get('uploaded_images', 0)
            total_images = data.get('total_images', 0)
            if total_images > 0 and uploaded_images > 0:
                progress = int((uploaded_images / total_images) * 100)
            else:
                progress = 0
        
        item = GalleryQueueItem(
            path=data.get('path', ''),
            name=data.get('name'),
            status=status,
            gallery_url=data.get('gallery_url', ''),
            gallery_id=data.get('gallery_id', ''),
            db_id=data.get('db_id'),  # Load database ID from persisted data
            progress=progress,
            uploaded_images=data.get('uploaded_images', 0),
            total_images=data.get('total_images', 0),
            template_name=data.get('template_name', 'default'),
            insertion_order=data.get('insertion_order', self._next_order),
            added_time=data.get('added_time'),
            finished_time=data.get('finished_time'),
            tab_name=data.get('tab_name', 'Main'),
            custom1=data.get('custom1', ''),
            custom2=data.get('custom2', ''),
            custom3=data.get('custom3', ''),
            custom4=data.get('custom4', ''),
            ext1=data.get('ext1', ''),
            ext2=data.get('ext2', ''),
            ext3=data.get('ext3', ''),
            ext4=data.get('ext4', '')
        )

        # Restore optional fields
        for field in ['total_size', 'avg_width', 'avg_height', 'max_width',
                     'max_height', 'min_width', 'min_height', 'scan_complete',
                     'uploaded_bytes', 'final_kibps', 'error_message',
                     'source_archive_path', 'is_from_archive',
                     'imx_status', 'imx_status_checked']:
            if field in data:
                setattr(item, field, data[field])

        if 'uploaded_files' in data:
            item.uploaded_files = set(data['uploaded_files'])
        if 'uploaded_images_data' in data:
            item.uploaded_images_data = data['uploaded_images_data']
        if 'failed_files' in data:
            item.failed_files = data['failed_files']
        
        return item
    
    def add_item(self, path: str, name: str | None = None, template_name: str = "default", tab_name: str = "Main") -> bool:
        """Add gallery to queue"""
        log(f"DEBUG: QueueManager.add_item called with path={path}, tab_name={tab_name}", level="debug", category="queue")
        with QMutexLocker(self.mutex):
            if path in self.items:
                return False
            
            gallery_name = name or os.path.basename(path)
            log(f"DEBUG: Creating GalleryQueueItem for {gallery_name} ({path}) with tab_name={tab_name}...", level="debug", category="queue")
            item = GalleryQueueItem(
                path=path,
                name=gallery_name,
                status=QUEUE_STATE_VALIDATING,
                insertion_order=self._next_order,
                db_id=self._next_db_id,  # Pre-assign predicted database ID
                added_time=time.time(),
                template_name=template_name,
                tab_name=tab_name
            )
            log(f"DEBUG: GalleryQueueItem created successfully", level="debug", category="queue")
            self._next_order += 1
            self._next_db_id += 1  # Increment for next gallery
            
            self.items[path] = item
            log(f"DEBUG: Item added to dict, updating status count...", level="debug", category="queue")
            self._update_status_count("", QUEUE_STATE_VALIDATING)
            log(f"DEBUG: Scheduling deferred database save...", level="debug", category="database")
            # Use QTimer to defer database save to prevent blocking GUI thread
            from PyQt6.QtCore import QTimer
            self._schedule_debounced_save([path])
            self._inc_version()
        
        log(f"DEBUG: Adding to scan queue: {path}", category="scanning", level="debug")
        self._scan_queue.put(path)

        # Execute "added" hook in background
        from src.processing.hooks_executor import execute_gallery_hooks
        import threading
        def run_added_hook():
            try:
                ext_fields = execute_gallery_hooks(
                    event_type='added',
                    gallery_path=path,
                    gallery_name=gallery_name,
                    tab_name=tab_name,
                    image_count=0  # Not scanned yet
                )
                # Update ext fields if hook returned any
                if ext_fields:
                    with QMutexLocker(self.mutex):
                        if path in self.items:
                            for key, value in ext_fields.items():
                                setattr(self.items[path], key, value)
                            self._schedule_debounced_save([path])
                    log(f"Updated fields from 'gallery added' hook: {ext_fields}", level="info", category="hooks")
                    # Emit signal through parent if available
                    if hasattr(self, 'parent') and self.parent and hasattr(self.parent, 'on_ext_fields_updated'):
                        self.parent.on_ext_fields_updated(path, ext_fields)
            except Exception as e:
                log(f"Error executing added hook: {e}", level="warning", category="hooks")

        threading.Thread(target=run_added_hook, daemon=True).start()

        # Check for file host auto-upload triggers (on_added)
        try:
            from src.core.file_host_config import get_config_manager
            config_manager = get_config_manager()
            triggered_hosts = config_manager.get_hosts_by_trigger('added')

            if triggered_hosts:
                log(f"Gallery added trigger: Found {len(triggered_hosts)} enabled hosts with 'On Added' trigger",
                    level="info", category="file_hosts")

                for host_id, host_config in triggered_hosts.items():
                    # Queue upload to this file host (use host_id, not display name)
                    upload_id = self.store.add_file_host_upload(
                        gallery_path=path,
                        host_name=host_id,  # host_id like 'filedot', not display name
                        status='pending'
                    )

                    if upload_id:
                        log(f"Queued file host upload for {path} to {host_config.name} (upload_id={upload_id})",
                            level="info", category="file_hosts")
                    else:
                        log(f"Failed to queue file host upload for {path} to {host_config.name}",
                            level="error", category="file_hosts")
        except Exception as e:
            log(f"Error checking file host triggers on gallery added: {e}", level="error", category="file_hosts")

        #print(f"DEBUG: add_item returning True")
        return True
    
    def start_item(self, path: str) -> bool:
        """Queue an item for upload"""
        with QMutexLocker(self.mutex):
            if path not in self.items:
                return False
            
            item = self.items[path]
            if item.status not in [QUEUE_STATE_READY, QUEUE_STATE_PAUSED, QUEUE_STATE_INCOMPLETE]:
                return False
            
            old_status = item.status
            item.status = QUEUE_STATE_QUEUED
            self._update_status_count(old_status, QUEUE_STATE_QUEUED)
            self.queue.put(item)
            self._schedule_debounced_save([path])
            self._inc_version()
            return True
    
    def get_next_item(self) -> Optional[GalleryQueueItem]:
        """Get next queued item"""
        try:
            item = self.queue.get_nowait()
            if item.path in self.items:
                if self.items[item.path].status in [QUEUE_STATE_QUEUED, QUEUE_STATE_UPLOADING]:
                    return item
            return self.get_next_item()  # Try next
        except queue.Empty:
            return None
    
    def update_custom_field(self, path: str, field_name: str, value: str):
        """Update a custom field for an item"""
        with QMutexLocker(self.mutex):
            if path in self.items and field_name in ['custom1', 'custom2', 'custom3', 'custom4']:
                # Update in-memory item
                old_value = getattr(self.items[path], field_name, '')
                setattr(self.items[path], field_name, value)

                # Update in database
                self.store.update_item_custom_field(path, field_name, value)

                self._inc_version()

                return True
        return False

    def update_item_status(self, path: str, status: str):
        """Update item status"""
        with QMutexLocker(self.mutex):
            if path in self.items:
                old_status = self.items[path].status
                self.items[path].status = status
                
                # When marking as completed, ensure progress is 100%
                if status == "completed":
                    self.items[path].progress = 100
                    
                self._update_status_count(old_status, status)
                
                # Only schedule save if not in batch mode
                if not self._batch_mode:
                    self._schedule_debounced_save([path])
                else:
                    # In batch mode, just add to batched changes
                    self._batched_changes.add(path)
                    
                self._inc_version()
                
                if old_status != status:
                    # Emit signal asynchronously to avoid timer conflicts
                    QTimer.singleShot(0, lambda: self.status_changed.emit(path, old_status, status))
    
    def remove_item(self, path: str) -> bool:
        """Remove item from queue"""
        with QMutexLocker(self.mutex):
            if path not in self.items:
                return False
            
            if self.items[path].status == QUEUE_STATE_UPLOADING:
                return False
            
            old_status = self.items[path].status
            self._update_status_count(old_status, "")
            del self.items[path]
            self._renumber_items()
            self._inc_version()
        
        try:
            self.store._executor.submit(self.store.delete_by_paths, [path])
        except (RuntimeError, AttributeError):
            pass
        
        return True
    
    def get_all_items(self) -> List[GalleryQueueItem]:
        """Get all items sorted by order"""
        with QMutexLocker(self.mutex):
            return sorted(self.items.values(), key=lambda x: x.insertion_order)
    
    def get_item(self, path: str) -> Optional[GalleryQueueItem]:
        """Get specific item"""
        with QMutexLocker(self.mutex):
            return self.items.get(path)

    def update_gallery_name(self, path: str, new_name: str) -> bool:
        """Update gallery display name"""
        with QMutexLocker(self.mutex):
            if path not in self.items:
                return False

            old_name = self.items[path].name
            self.items[path].name = new_name
            self._schedule_debounced_save([path])

            self._inc_version()

            return True

    def _rebuild_status_counts(self):
        """Rebuild status counters"""
        self._status_counts.clear()
        for item in self.items.values():
            status = item.status
            self._status_counts[status] = self._status_counts.get(status, 0) + 1
    
    def _update_status_count(self, old: str, new: str):
        """Update status counters"""
        if old:
            self._status_counts[old] = max(0, self._status_counts.get(old, 0) - 1)
        if new:
            self._status_counts[new] = self._status_counts.get(new, 0) + 1
    
    def _renumber_items(self):
        """Renumber insertion orders"""
        sorted_items = sorted(self.items.values(), key=lambda x: x.insertion_order)
        for i, item in enumerate(sorted_items, 1):
            item.insertion_order = i
        self._next_order = len(self.items) + 1
    
    
    def shutdown(self):
        """Shutdown queue manager"""
        # Process any pending saves before shutting down
        if self._pending_save_timer:
            try:
                if self._pending_save_timer.isActive():
                    self._pending_save_timer.stop()
                # Execute the save immediately if there was a pending one
                self.save_persistent_queue()
            except RuntimeError:
                # Timer might be from another thread, just do a direct save
                self.save_persistent_queue()
            finally:
                self._pending_save_timer = None

        self._scan_worker_running = False
        try:
            self._scan_queue.put(None, timeout=1.0)
        except (queue.Full, AttributeError):
            pass
        if self._scan_worker and self._scan_worker.is_alive():
            self._scan_worker.join(timeout=2.0)