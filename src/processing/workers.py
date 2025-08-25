"""
Worker threads for ImxUp application.
Handles background upload and completion tasks.
"""

import os
import time
import traceback
import queue
from queue import Queue
from typing import Dict, Any, Optional, Set
from PyQt6.QtCore import QThread, pyqtSignal, QMutex, QMutexLocker

from imxup import ImxToUploader, save_gallery_artifacts, generate_bbcode_from_template
from imxup import rename_all_unnamed_with_session, get_central_storage_path
from src.core.engine import UploadEngine
from src.core.constants import (
    QUEUE_STATE_UPLOADING, QUEUE_STATE_COMPLETED, QUEUE_STATE_FAILED,
    QUEUE_STATE_PAUSED, QUEUE_STATE_READY
)


class UploadWorker(QThread):
    """Worker thread for handling gallery uploads"""
    
    # Signals
    progress_updated = pyqtSignal(str, int, int, int, str)  # path, completed, total, percent, current_image
    gallery_started = pyqtSignal(str, int)  # path, total_images
    gallery_completed = pyqtSignal(str, dict)  # path, results
    gallery_failed = pyqtSignal(str, str)  # path, error
    gallery_exists = pyqtSignal(str, str)  # path, gallery_url
    gallery_renamed = pyqtSignal(str, str)  # gallery_id, new_name
    log_message = pyqtSignal(str)
    bandwidth_updated = pyqtSignal(float)  # Current upload speed in KB/s
    queue_stats = pyqtSignal(dict)  # Queue statistics
    
    def __init__(self, queue_manager):
        super().__init__()
        self.queue_manager = queue_manager
        self.uploader = None
        self.current_item = None
        self.mutex = QMutex()
        self.running = True
        self.paused = False
        self._stop_current = False
        self._soft_stop_requested_for = None
        
        # Bandwidth tracking
        self._bw_last_emit = 0
        self._stats_last_emit = 0
        
        # Auto-rename preference
        self.auto_rename_enabled = False
    
    def run(self):
        """Main worker thread loop"""
        # Create uploader instance in the thread
        from src.network.client import GUIImxToUploader
        self.uploader = GUIImxToUploader(self)
        
        # Initialize session
        self._init_session()
        
        while self.running:
            try:
                # Check for pause
                with QMutexLocker(self.mutex):
                    if self.paused:
                        time.sleep(0.1)
                        continue
                
                # Get next item from queue
                item = self._get_next_item()
                if not item:
                    # Try auto-rename if enabled
                    if self.auto_rename_enabled:
                        self._try_auto_rename()
                    time.sleep(0.5)
                    continue
                
                # Set current item
                with QMutexLocker(self.mutex):
                    self.current_item = item
                    self._stop_current = False
                    self._soft_stop_requested_for = None
                
                # Update status to uploading
                self.queue_manager.update_item_status(item.path, QUEUE_STATE_UPLOADING)
                
                # Perform upload
                self._upload_gallery(item)
                
                # Clear current item
                with QMutexLocker(self.mutex):
                    self.current_item = None
                    
            except Exception as e:
                self.log_message.emit(f"Worker error: {e}")
                traceback.print_exc()
    
    def _init_session(self):
        """Initialize uploader session"""
        try:
            success = self.uploader.init_session()
            if success:
                self.log_message.emit("Session initialized successfully")
            else:
                self.log_message.emit("Failed to initialize session")
        except Exception as e:
            self.log_message.emit(f"Session initialization error: {e}")
    
    def _get_next_item(self):
        """Get next item from queue"""
        items = self.queue_manager.get_all_items()
        
        # Find first ready or paused item (paused can be resumed)
        for item in items:
            if item.status in [QUEUE_STATE_READY, "queued"]:
                return item
        
        # Check for incomplete uploads to resume
        for item in items:
            if item.status == "incomplete":
                return item
        
        return None
    
    def _upload_gallery(self, item):
        """Upload a gallery"""
        try:
            # Check if gallery exists
            if item.gallery_id:
                gallery_url = f"https://imx.to/g/{item.gallery_id}"
                if self._check_gallery_exists(gallery_url):
                    self.gallery_exists.emit(item.path, gallery_url)
                    self.queue_manager.update_item_status(item.path, QUEUE_STATE_COMPLETED)
                    return
            
            # Start upload
            item.start_time = time.time()
            item.uploaded_files = set()
            item.uploaded_images_data = []
            item.uploaded_bytes = 0
            
            # Perform upload using uploader
            results = self.uploader.upload_folder(
                folder_path=item.path,
                gallery_name=item.name,
                template_name=item.template_name
            )
            
            # Check if stopped
            with QMutexLocker(self.mutex):
                if self._stop_current:
                    self.queue_manager.update_item_status(item.path, "incomplete")
                    return
            
            # Handle results
            if results and results.get('gallery_id'):
                item.gallery_id = results['gallery_id']
                item.gallery_url = f"https://imx.to/g/{results['gallery_id']}"
                item.uploaded_images = results.get('successful_count', 0)
                item.finished_time = time.time()
                
                # Calculate final transfer rate
                if item.start_time:
                    elapsed = item.finished_time - item.start_time
                    if elapsed > 0 and item.uploaded_bytes > 0:
                        item.final_kibps = (item.uploaded_bytes / elapsed) / 1024.0
                
                self.gallery_completed.emit(item.path, results)
                self.queue_manager.update_item_status(item.path, QUEUE_STATE_COMPLETED)
            else:
                error_msg = results.get('error', 'Unknown error') if results else 'Upload failed'
                self.gallery_failed.emit(item.path, error_msg)
                self.queue_manager.update_item_status(item.path, QUEUE_STATE_FAILED)
                
        except Exception as e:
            error_msg = str(e)
            self.gallery_failed.emit(item.path, error_msg)
            self.queue_manager.update_item_status(item.path, QUEUE_STATE_FAILED)
            self.log_message.emit(f"Upload error for {item.path}: {error_msg}")
    
    def _check_gallery_exists(self, gallery_url: str) -> bool:
        """Check if a gallery already exists"""
        try:
            import requests
            response = requests.head(gallery_url, timeout=5)
            return response.status_code == 200
        except:
            return False
    
    def _try_auto_rename(self):
        """Try to auto-rename unnamed galleries"""
        try:
            if self.uploader and self.uploader.session:
                renamed = rename_all_unnamed_with_session(self.uploader.session)
                if renamed:
                    for gallery_id, new_name in renamed:
                        self.gallery_renamed.emit(gallery_id, new_name)
                        self.log_message.emit(f"Gallery {gallery_id} renamed to: {new_name}")
        except Exception as e:
            self.log_message.emit(f"Auto-rename error: {e}")
    
    def _emit_queue_stats(self):
        """Emit queue statistics"""
        try:
            stats = self.queue_manager.get_statistics()
            self.queue_stats.emit(stats)
        except:
            pass
    
    def request_soft_stop(self, gallery_path: str):
        """Request a soft stop for the current upload"""
        with QMutexLocker(self.mutex):
            if self.current_item and self.current_item.path == gallery_path:
                self._soft_stop_requested_for = gallery_path
    
    def request_retry_login(self, credentials_only: bool = False):
        """Request a login retry"""
        if self.uploader:
            try:
                self.uploader.retry_login(credentials_only)
                self.log_message.emit("Login retry requested")
            except Exception as e:
                self.log_message.emit(f"Login retry failed: {e}")
    
    def pause(self):
        """Pause the worker"""
        with QMutexLocker(self.mutex):
            self.paused = True
    
    def resume(self):
        """Resume the worker"""
        with QMutexLocker(self.mutex):
            self.paused = False
    
    def stop(self):
        """Stop the worker thread"""
        with QMutexLocker(self.mutex):
            self.running = False
            self._stop_current = True
        self.wait()


class CompletionWorker(QThread):
    """Worker thread for handling gallery completion processing to avoid GUI blocking"""
    
    # Signals
    completion_processed = pyqtSignal(str)  # path - signals when completion processing is done
    log_message = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.completion_queue = Queue()
        self.running = True
    
    def stop(self):
        self.running = False
        self.completion_queue.put(None)  # Signal to exit
        
    def process_completion(self, path: str, results: dict, gui_parent):
        """Queue a completion for background processing"""
        self.completion_queue.put((path, results, gui_parent))
    
    def run(self):
        """Process completions in background thread"""
        while self.running:
            try:
                item = self.completion_queue.get(timeout=1.0)
                if item is None:  # Exit signal
                    break
                    
                path, results, gui_parent = item
                self._process_completion_background(path, results, gui_parent)
                self.completion_processed.emit(path)
                
            except queue.Empty:
                continue
            except Exception as e:
                from imxup import timestamp
                self.log_message.emit(f"{timestamp()} Completion processing error: {e}")
    
    def _process_completion_background(self, path: str, results: dict, gui_parent):
        """Do the heavy completion processing in background thread"""
        try:
            from imxup import timestamp, save_unnamed_gallery, get_unnamed_galleries, check_gallery_renamed
            from datetime import datetime
            
            # Create gallery files with new naming format
            gallery_id = results.get('gallery_id', '')
            gallery_name = results.get('gallery_name', os.path.basename(path))
            
            if not gallery_id or not gallery_name:
                return
            
            # Only track for renaming if gallery is actually unnamed
            try:
                # Check if gallery is already renamed
                is_renamed = check_gallery_renamed(gallery_id)
                if not is_renamed:
                    # Check if already in unnamed tracking
                    existing_unnamed = get_unnamed_galleries()
                    if gallery_id not in [g['gallery_id'] for g in existing_unnamed]:
                        save_unnamed_gallery(gallery_id, gallery_name)
                        self.log_message.emit(f"{timestamp()} [rename] Tracking gallery for auto-rename: {gallery_name}")
            except Exception:
                pass
                
            # Generate BBCode and save artifacts - simplified version
            try:
                # Get template name from the item
                item = gui_parent.queue_manager.get_item(path)
                template_name = item.template_name if item else "default"
                
                # Save artifacts
                written = save_gallery_artifacts(
                    folder_path=path,
                    results=results,
                    template_name=template_name,
                )
                
                if written:
                    self.log_message.emit(f"{timestamp()} [fileio] Saved gallery files")
                    
            except Exception as e:
                self.log_message.emit(f"{timestamp()} Artifact save error: {e}")
                
        except Exception as e:
            from imxup import timestamp
            self.log_message.emit(f"{timestamp()} Background completion processing error: {e}")


class BandwidthTracker:
    """Track upload bandwidth with sliding window"""
    
    def __init__(self, window_size: int = 10):
        self.window_size = window_size
        self.samples = []
        self.mutex = QMutex()
    
    def add_sample(self, bytes_uploaded: int, time_elapsed: float):
        """Add a bandwidth sample"""
        with QMutexLocker(self.mutex):
            if time_elapsed > 0:
                kbps = (bytes_uploaded / time_elapsed) / 1024.0
                self.samples.append(kbps)
                if len(self.samples) > self.window_size:
                    self.samples.pop(0)
    
    def get_average_kbps(self) -> float:
        """Get average bandwidth in KB/s"""
        with QMutexLocker(self.mutex):
            if self.samples:
                return sum(self.samples) / len(self.samples)
            return 0.0
    
    def reset(self):
        """Reset bandwidth tracking"""
        with QMutexLocker(self.mutex):
            self.samples.clear()