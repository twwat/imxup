#!/usr/bin/env python3
"""
Upload worker threads for imxup
Handles gallery uploads and completion tracking in background threads
"""

import os
import time
from typing import Optional, Dict, Any

from PyQt6.QtCore import QThread, pyqtSignal, QMutex

from imxup import (
    timestamp, load_user_defaults, rename_all_unnamed_with_session,
    save_gallery_artifacts, get_unnamed_galleries
)
from src.network.client import GUIImxToUploader
from src.storage.queue_manager import GalleryQueueItem


class UploadWorker(QThread):
    """Worker thread for uploading galleries"""
    
    # Signals for communication with GUI
    progress_updated = pyqtSignal(str, int, int, int, str)  # path, completed, total, progress%, current_image
    gallery_started = pyqtSignal(str, int)  # path, total_images
    gallery_completed = pyqtSignal(str, dict)  # path, results
    gallery_failed = pyqtSignal(str, str)  # path, error_message
    gallery_exists = pyqtSignal(str, list)  # gallery_name, existing_files
    gallery_renamed = pyqtSignal(str)  # gallery_id
    log_message = pyqtSignal(str)
    bandwidth_updated = pyqtSignal(float)  # current KB/s across active uploads
    queue_stats = pyqtSignal(dict)  # aggregate status stats for GUI updates
    
    def __init__(self, queue_manager):
        """Initialize upload worker with queue manager"""
        super().__init__()
        self.queue_manager = queue_manager
        self.uploader = None
        self.running = True
        self.current_item = None
        self._soft_stop_requested_for = None
        self.auto_rename_enabled = True
        self._bw_last_emit = 0.0
        self._stats_last_emit = 0.0
        
        # Thread-safe request flags
        self._request_mutex = QMutex()
        self._retry_login_requested = False
        self._retry_credentials_only = False
        
    def stop(self):
        """Stop the worker thread"""
        self.running = False
        self.wait()
    
    def request_soft_stop_current(self):
        """Request to stop the current item after in-flight uploads finish"""
        if self.current_item:
            self._soft_stop_requested_for = self.current_item.path
    
    def request_retry_login(self, credentials_only: bool = False):
        """Request the worker to retry login on its own thread
        Safe to call from the GUI thread
        """
        try:
            self._request_mutex.lock()
            self._retry_login_requested = True
            self._retry_credentials_only = bool(credentials_only)
        finally:
            try:
                self._request_mutex.unlock()
            except Exception:
                pass
    
    def run(self):
        """Main worker thread loop"""
        try:
            # Initialize uploader and perform initial login
            self._initialize_uploader()
            
            # Main processing loop
            while self.running:
                # Handle any pending login retry requests
                self._maybe_handle_login_retry()
                
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
            traceback.print_exc()
            self.log_message.emit(f"{timestamp()} Worker error: {str(e)}")
    
    def _initialize_uploader(self):
        """Initialize uploader and perform initial login"""
        self.uploader = GUIImxToUploader(worker_thread=self)
        
        # Attempt login
        self.log_message.emit(f"{timestamp()} [auth] Logging in...")
        try:
            login_success = self.uploader.login()
        except Exception as e:
            login_success = False
            self.log_message.emit(f"{timestamp()} [auth] Login error: {e}")
        
        # Report login method and handle post-login tasks
        self._handle_login_result(login_success)
    
    def _handle_login_result(self, login_success: bool):
        """Handle login result and perform post-login tasks"""
        if not login_success:
            self.log_message.emit(f"{timestamp()} [auth] Login failed - using API-only mode")
            return
        
        # Get login method used
        method = getattr(self.uploader, 'last_login_method', None)
        
        # Report authentication method
        if method == 'cookies':
            self.log_message.emit(f"{timestamp()} [auth] Authenticated using cookies")
        elif method == 'credentials':
            self.log_message.emit(f"{timestamp()} [auth] Authenticated using username/password")
        elif method == 'api_key':
            self.log_message.emit(f"{timestamp()} [auth] Using API key authentication (no web login)")
        elif method == 'none':
            self.log_message.emit(f"{timestamp()} [auth] No credentials available; proceeding without web login")
        
        # Handle auto-rename for web sessions
        if method in ('cookies', 'credentials'):
            self.log_message.emit(f"{timestamp()} [auth] Login successful using {method}")
            self._perform_auto_rename()
        elif method == 'api_key':
            self.log_message.emit(f"{timestamp()} [auth] API key loaded; web login skipped")
            self.log_message.emit(f"{timestamp()} [auth] Skipping auto-rename; web session required")
    
    def _perform_auto_rename(self):
        """Perform auto-rename of unnamed galleries if enabled"""
        if not self.auto_rename_enabled:
            return
        
        try:
            renamed = rename_all_unnamed_with_session(self.uploader)
            if renamed > 0:
                self.log_message.emit(f"{timestamp()} Auto-renamed {renamed} gallery(ies) after login")
            else:
                # Check if there are actually unnamed galleries
                if not get_unnamed_galleries():
                    self.log_message.emit(f"{timestamp()} No unnamed galleries to auto-rename")
        except Exception as e:
            self.log_message.emit(f"{timestamp()} Auto-rename error: {e}")
    
    def _maybe_handle_login_retry(self):
        """Handle any pending login retry requests"""
        need_retry = False
        cred_only = False
        
        try:
            self._request_mutex.lock()
            if self._retry_login_requested:
                need_retry = True
                cred_only = bool(self._retry_credentials_only)
                self._retry_login_requested = False
                self._retry_credentials_only = False
        finally:
            try:
                self._request_mutex.unlock()
            except Exception:
                pass
        
        if not need_retry:
            return
        
        # Perform login retry
        try:
            self.log_message.emit(f"{timestamp()} [auth] Re-attempting login{' (credentials only)' if cred_only else ''}...")
            
            if not self.uploader:
                self.uploader = GUIImxToUploader(worker_thread=self)
            
            if cred_only and hasattr(self.uploader, 'login_with_credentials_only'):
                ok = self.uploader.login_with_credentials_only()
            else:
                ok = self.uploader.login()
            
            if ok:
                method = getattr(self.uploader, 'last_login_method', None)
                self.log_message.emit(f"{timestamp()} [auth] Login successful using {method or 'unknown method'}")
                self._perform_auto_rename()
            else:
                self.log_message.emit(f"{timestamp()} [auth] Login retry failed")
                
        except Exception as e:
            self.log_message.emit(f"{timestamp()} [auth] Login retry error: {e}")
    
    def upload_gallery(self, item: GalleryQueueItem):
        """Upload a single gallery"""
        try:
            # Clear previous soft-stop request
            self._soft_stop_requested_for = None
            self.log_message.emit(f"{timestamp()} Starting upload: {item.name or os.path.basename(item.path)}")
            
            # Update status to uploading
            self.queue_manager.update_item_status(item.path, "uploading")
            item.start_time = time.time()
            
            # Emit start signal
            self.gallery_started.emit(item.path, item.total_images or 0)
            self._emit_queue_stats(force=True)
            
            # Check for early soft stop request
            if getattr(self, '_soft_stop_requested_for', None) == item.path:
                self.queue_manager.update_item_status(item.path, "incomplete")
                return
            
            # Get upload settings
            defaults = load_user_defaults()
            
            # Perform upload
            results = self.uploader.upload_folder(
                item.path,
                gallery_name=item.name,
                thumbnail_size=defaults.get('thumbnail_size', 3),
                thumbnail_format=defaults.get('thumbnail_format', 2),
                max_retries=defaults.get('max_retries', 3),
                parallel_batch_size=defaults.get('parallel_batch_size', 4),
                template_name=item.template_name
            )
            
            # Handle paused state
            if item.status == "paused":
                self.log_message.emit(f"{timestamp()} Upload paused: {item.name}")
                return
            
            # Process results
            self._process_upload_results(item, results)
            
        except Exception as e:
            error_msg = str(e)
            self.log_message.emit(f"{timestamp()} Error uploading {item.name}: {error_msg}")
            item.error_message = error_msg
            self.queue_manager.mark_upload_failed(item.path, error_msg)
            self.gallery_failed.emit(item.path, error_msg)
    
    def _process_upload_results(self, item: GalleryQueueItem, results: Optional[Dict[str, Any]]):
        """Process upload results and update item status"""
        if not results:
            # Handle failed upload
            if self._soft_stop_requested_for == item.path:
                self.queue_manager.update_item_status(item.path, "incomplete")
                item.status = "incomplete"
                self.log_message.emit(f"{timestamp()} Marked incomplete: {item.name}")
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
            self.log_message.emit(f"{timestamp()} Marked incomplete: {item.name}")
            return
        
        # Save artifacts
        self._save_artifacts_for_result(item, results)
        
        # Determine final status
        failed_count = results.get('failed_count', 0)
        if failed_count and results.get('successful_count', 0) > 0:
            # Partial failure - some images uploaded successfully but others failed
            failed_files = results.get('failed_details', [])
            self.queue_manager.mark_upload_failed(item.path, f"Partial upload failure: {failed_count} images failed", failed_files)
        else:
            # Complete success
            self.queue_manager.update_item_status(item.path, "completed")
        
        # Notify GUI
        self.gallery_completed.emit(item.path, results)
        self._emit_queue_stats(force=True)
    
    def _save_artifacts_for_result(self, item: GalleryQueueItem, results: dict):
        """Save gallery artifacts (BBCode, JSON) in worker thread"""
        try:
            written = save_gallery_artifacts(
                folder_path=item.path,
                results=results,
                template_name=item.template_name or "default",
            )
            # Artifact save successful, no need to log details here
        except Exception as e:
            self.log_message.emit(f"{timestamp()} Artifact save error: {e}")
    
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
            self.log_message.emit(f"{timestamp()} Completion processing error: {e}")
    
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
                self.log_message.emit(f"{timestamp()} [artifacts] Saved to {', '.join(parts)}")
                
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