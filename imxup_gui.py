#!/usr/bin/env python3
"""
PyQt6 GUI for imx.to gallery uploader
Provides drag-and-drop interface with queue management and progress tracking
"""

import sys
import os
import json
import socket
import threading
import time
import configparser
from pathlib import Path
from datetime import datetime
from queue import Queue, Empty
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QListWidget, QListWidgetItem, QPushButton, QProgressBar, QLabel, 
    QGroupBox, QSplitter, QTextEdit, QComboBox, QSpinBox, QCheckBox,
    QMessageBox, QSystemTrayIcon, QMenu, QFrame, QScrollArea,
    QGridLayout, QSizePolicy, QTabWidget, QFileDialog, QTableWidget,
    QTableWidgetItem, QHeaderView, QDialog, QDialogButtonBox, QPlainTextEdit,
    QLineEdit, QInputDialog, QSpacerItem, QStyle
)
from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QTimer, QMimeData, QUrl, 
    QMutex, QMutexLocker, QSettings, QSize, QObject
)
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QIcon, QFont, QPixmap, QPainter, QColor, QSyntaxHighlighter, QTextCharFormat, QDesktopServices

# Import the core uploader functionality
from imxup import ImxToUploader, load_user_defaults, timestamp, sanitize_gallery_name, encrypt_password, decrypt_password, rename_all_unnamed_with_session, get_config_path

# Single instance communication port
COMMUNICATION_PORT = 27849

def check_stored_credentials():
    """Check if credentials are stored"""
    config = configparser.ConfigParser()
    config_file = get_config_path()
    
    if os.path.exists(config_file):
        config.read(config_file)
        if 'CREDENTIALS' in config:
            auth_type = config.get('CREDENTIALS', 'auth_type', fallback='username_password')
            
            if auth_type == 'username_password':
                username = config.get('CREDENTIALS', 'username', fallback='')
                encrypted_password = config.get('CREDENTIALS', 'password', fallback='')
                if username and encrypted_password:
                    return True
            elif auth_type == 'api_key':
                encrypted_api_key = config.get('CREDENTIALS', 'api_key', fallback='')
                if encrypted_api_key:
                    return True
    return False

def api_key_is_set() -> bool:
    """Return True if an API key exists in the credentials config, regardless of auth_type."""
    config = configparser.ConfigParser()
    config_file = get_config_path()
    if os.path.exists(config_file):
        config.read(config_file)
        if 'CREDENTIALS' in config:
            encrypted_api_key = config.get('CREDENTIALS', 'api_key', fallback='')
            return bool(encrypted_api_key)
    return False

@dataclass
class GalleryQueueItem:
    """Represents a gallery in the upload queue"""
    path: str
    name: Optional[str] = None
    status: str = "ready"  # ready, queued, uploading, completed, failed, paused, incomplete
    progress: int = 0
    total_images: int = 0
    uploaded_images: int = 0
    current_image: str = ""
    gallery_url: str = ""
    gallery_id: str = ""
    error_message: str = ""
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    insertion_order: int = 0  # For maintaining insertion order
    added_time: Optional[float] = None  # When item was added to queue
    finished_time: Optional[float] = None  # When item was completed
    template_name: str = "default"  # Template to use for bbcode generation
    # Pre-scan metadata
    total_size: int = 0
    avg_width: float = 0.0
    avg_height: float = 0.0
    scan_complete: bool = False
    # Resume support
    uploaded_files: set = field(default_factory=set)
    uploaded_images_data: list = field(default_factory=list)
    uploaded_bytes: int = 0
    
class GUIImxToUploader(ImxToUploader):
    """Custom uploader for GUI that doesn't block on user input"""
    
    def __init__(self, worker_thread=None):
        super().__init__()
        self.gui_mode = True
        self.worker_thread = worker_thread
    
    def upload_folder(self, folder_path, gallery_name=None, thumbnail_size=3, thumbnail_format=2, max_retries=3, public_gallery=1, parallel_batch_size=4, template_name="default"):
        """
        Upload folder without interactive prompts
        """
        start_time = time.time()
        
        if not os.path.exists(folder_path):
            raise FileNotFoundError(f"Folder not found: {folder_path}")
        
        # Get all image files in folder
        image_extensions = ('.jpg', '.jpeg', '.png', '.gif')
        all_image_files = [f for f in os.listdir(folder_path) if f.lower().endswith(image_extensions) and os.path.isfile(os.path.join(folder_path, f))]
        # If resuming, skip already uploaded files
        current_item = self.worker_thread.current_item if self.worker_thread else None
        already_uploaded = set()
        if current_item and getattr(current_item, 'uploaded_files', None):
            already_uploaded = set(current_item.uploaded_files)
        image_files = [f for f in all_image_files if f not in already_uploaded]
        # Maintain the original total for progress/percent
        original_total_images = len(all_image_files)
        
        # Pre-scan dimensions and total size for GUI stats (use ALL images for consistency on resume)
        image_dimensions_map = {}
        total_size = 0
        for f in all_image_files:
            fp = os.path.join(folder_path, f)
            try:
                from PIL import Image
                with Image.open(fp) as img:
                    width, height = img.size
                    image_dimensions_map[f] = (width, height)
            except Exception:
                image_dimensions_map[f] = (0, 0)
            try:
                total_size += os.path.getsize(fp)
            except OSError:
                pass
        
        if not image_files:
            raise ValueError(f"No image files found in {folder_path}")
        
        # Signal gallery start with original total count (for accurate resume progress)
        if self.worker_thread:
            self.worker_thread.gallery_started.emit(folder_path, original_total_images)
        
        # Create gallery name (default to folder name if not provided)
        if not gallery_name:
            gallery_name = os.path.basename(folder_path)
        
        # Sanitize gallery name
        from imxup import sanitize_gallery_name
        original_name = gallery_name
        gallery_name = sanitize_gallery_name(gallery_name)
        if original_name != gallery_name and self.worker_thread:
            self.worker_thread.log_message.emit(f"{timestamp()} Sanitized gallery name: '{original_name}' -> '{gallery_name}'")
        
        # Use existing gallery if resuming; otherwise create a new one (skip login since it's already done)
        gallery_id = None
        initial_completed = 0
        initial_uploaded_size = 0
        preseed_images = []  # Preserve first image in API-only fallback
        files_to_upload = []
        if current_item and current_item.gallery_id:
            gallery_id = current_item.gallery_id
            if self.worker_thread:
                self.worker_thread.log_message.emit(f"{timestamp()} Resuming existing gallery {gallery_id}")
            files_to_upload = image_files
        else:
            gallery_id = self.create_gallery_with_name(gallery_name, public_gallery, skip_login=True)
            if not gallery_id:
                # API-only fallback: upload first image to create gallery, then reuse same loop for the rest
                if self.worker_thread:
                    self.worker_thread.log_message.emit(f"{timestamp()} Using API-only upload (no gallery naming)")
                first_file = image_files[0]
                first_image_path = os.path.join(folder_path, first_file)
                if self.worker_thread:
                    self.worker_thread.log_message.emit(f"{timestamp()} Uploading first image: {first_file}")
                first_response = self.upload_image(
                    first_image_path,
                    create_gallery=True,
                    thumbnail_size=thumbnail_size,
                    thumbnail_format=thumbnail_format
                )
                if first_response.get('status') != 'success':
                    raise Exception(f"{timestamp()} Failed to create gallery: {first_response}")
                gallery_id = first_response['data'].get('gallery_id')
                # Save for later renaming (with sanitized name)
                from imxup import save_unnamed_gallery
                save_unnamed_gallery(gallery_id, gallery_name)
                preseed_images = [first_response['data']]
                initial_completed = 1
                try:
                    initial_uploaded_size = os.path.getsize(first_image_path)
                except Exception:
                    initial_uploaded_size = 0
                # Optional: emit a progress update for the first image
                if self.worker_thread:
                    percent_once = int((initial_completed / max(original_total_images, 1)) * 100)
                    self.worker_thread.progress_updated.emit(
                        folder_path, initial_completed, original_total_images, percent_once, first_file
                    )
                # Upload the rest
                files_to_upload = image_files[1:]
            else:
                files_to_upload = image_files
        
        gallery_url = f"https://imx.to/g/{gallery_id}"
        
        # Store results
        results = {
            'gallery_url': gallery_url,
            'images': list(preseed_images)
        }
        
        # Upload all images to the created gallery with progress bars
        def upload_single_image(image_file, attempt=1, pbar=None):
            image_path = os.path.join(folder_path, image_file)
            
            try:
                response = self.upload_image(
                    image_path, 
                    gallery_id=gallery_id,
                    thumbnail_size=thumbnail_size,
                    thumbnail_format=thumbnail_format
                )
                
                if response.get('status') == 'success':
                    return image_file, response['data'], None
                else:
                    error_msg = f"API error: {response}"
                    return image_file, None, error_msg
                    
            except Exception as e:
                error_msg = f"Network error: {str(e)}"
                return image_file, None, error_msg
        
        # Upload images with retries, maintaining order
        uploaded_images = []
        failed_images = []
        # Seed uploaded_images with already uploaded data for correct progress and final aggregation
        if current_item and current_item.uploaded_images_data:
            uploaded_images.extend([(fname, data) for fname, data in current_item.uploaded_images_data])
        # Position map for stable ordering without fragile index lookups
        file_position = {fname: idx for idx, fname in enumerate(all_image_files)}
        
        # Rolling concurrency
        import concurrent.futures, queue
        with ThreadPoolExecutor(max_workers=parallel_batch_size) as executor:
            remaining = queue.Queue()
            for f in files_to_upload:
                remaining.put(f)
            futures_map = {}
            # Prime pool
            for _ in range(min(parallel_batch_size, remaining.qsize())):
                img = remaining.get()
                futures_map[executor.submit(upload_single_image, img, 1)] = img
            
            while futures_map:
                done, _ = concurrent.futures.wait(list(futures_map.keys()), return_when=concurrent.futures.FIRST_COMPLETED)
                for fut in done:
                    img = futures_map.pop(fut)
                    image_file, image_data, error = fut.result()
                    if image_data:
                        uploaded_images.append((image_file, image_data))
                        # Track uploaded file for resume capability
                        if self.worker_thread and self.worker_thread.current_item and self.worker_thread.current_item.path == folder_path:
                            try:
                                self.worker_thread.current_item.uploaded_files.add(image_file)
                                self.worker_thread.current_item.uploaded_images_data.append((image_file, image_data))
                            except Exception:
                                pass
                        if self.worker_thread:
                            # Update uploaded bytes cheaply without repeatedly statting files later
                            try:
                                if self.worker_thread.current_item and self.worker_thread.current_item.path == folder_path:
                                    fp = os.path.join(folder_path, image_file)
                                    self.worker_thread.current_item.uploaded_bytes += os.path.getsize(fp)
                            except Exception:
                                pass
                            self.worker_thread.log_message.emit(f"{timestamp()} ✓ Uploaded: {image_file}")
                    else:
                        failed_images.append((image_file, error))
                        if self.worker_thread:
                            self.worker_thread.log_message.emit(f"{timestamp()} ✗ Failed: {image_file} - {error}")
                    
                    # Update progress
                    completed_count = initial_completed + len(uploaded_images)
                    progress_percent = int((completed_count / max(original_total_images, 1)) * 100)
                    if self.worker_thread:
                        self.worker_thread.progress_updated.emit(
                            folder_path, completed_count, original_total_images, progress_percent, image_file
                        )
                        self.worker_thread.log_message.emit(f"{timestamp()} Progress: {completed_count}/{original_total_images} ({progress_percent}%)")
                        # Emit throttled bandwidth update ~10Hz
                        try:
                            now_ts = time.time()
                            if now_ts - self.worker_thread._bw_last_emit >= 0.1:
                                # Aggregate uploaded_bytes across active items
                                total_bytes = 0
                                max_elapsed = 0.0
                                for it in self.worker_thread.queue_manager.get_all_items():
                                    if it.status == "uploading" and it.start_time:
                                        total_bytes += getattr(it, 'uploaded_bytes', 0)
                                        max_elapsed = max(max_elapsed, now_ts - it.start_time)
                                if max_elapsed > 0:
                                    kbps = (total_bytes / max_elapsed) / 1024.0
                                    self.worker_thread.bandwidth_updated.emit(kbps)
                                    self.worker_thread._bw_last_emit = now_ts
                        except Exception:
                            pass
                    
                    # Only submit new uploads if no soft stop has been requested for this item
                    if not remaining.empty():
                        soft_stop = False
                        if self.worker_thread and self.worker_thread.current_item and self.worker_thread.current_item.path == folder_path:
                            soft_stop = getattr(self.worker_thread, '_soft_stop_requested_for', None) == folder_path
                        if not soft_stop:
                            nxt = remaining.get()
                            futures_map[executor.submit(upload_single_image, nxt, 1)] = nxt
        
        # Retry failed uploads with parallel processing (skip if soft stop requested)
        retry_count = 0
        soft_stop_requested = False
        if self.worker_thread and self.worker_thread.current_item and self.worker_thread.current_item.path == folder_path:
            soft_stop_requested = getattr(self.worker_thread, '_soft_stop_requested_for', None) == folder_path
        while failed_images and retry_count < max_retries and not soft_stop_requested:
            retry_count += 1
            retry_failed = []
            
            if self.worker_thread:
                self.worker_thread.log_message.emit(f"{timestamp()} Retrying {len(failed_images)} failed uploads (attempt {retry_count}/{max_retries})")
            
            # Rolling retries
            import concurrent.futures, queue
            with ThreadPoolExecutor(max_workers=parallel_batch_size) as executor:
                remaining = queue.Queue()
                for img, _ in failed_images:
                    remaining.put(img)
                futures_map = {}
                for _ in range(min(parallel_batch_size, remaining.qsize())):
                    img = remaining.get()
                    futures_map[executor.submit(upload_single_image, img, retry_count + 1)] = img
                
                while futures_map:
                    done, _ = concurrent.futures.wait(list(futures_map.keys()), return_when=concurrent.futures.FIRST_COMPLETED)
                    for fut in done:
                        img = futures_map.pop(fut)
                        image_file, image_data, error = fut.result()
                        if image_data:
                            uploaded_images.append((image_file, image_data))
                            # Track uploaded file for resume capability (retry path)
                            if self.worker_thread and self.worker_thread.current_item and self.worker_thread.current_item.path == folder_path:
                                try:
                                    self.worker_thread.current_item.uploaded_files.add(image_file)
                                    self.worker_thread.current_item.uploaded_images_data.append((image_file, image_data))
                                    # Also update uploaded_bytes incrementally
                                    try:
                                        fp = os.path.join(folder_path, image_file)
                                        self.worker_thread.current_item.uploaded_bytes += os.path.getsize(fp)
                                    except Exception:
                                        pass
                                except Exception:
                                    pass
                            if self.worker_thread:
                                self.worker_thread.log_message.emit(f"{timestamp()} ✓ Retry successful: {image_file}")
                        else:
                            retry_failed.append((image_file, error))
                            if self.worker_thread:
                                self.worker_thread.log_message.emit(f"{timestamp()} ✗ Retry failed: {image_file} - {error}")
                        
                        completed_count = initial_completed + len(uploaded_images)
                        progress_percent = int((completed_count / max(original_total_images, 1)) * 100)
                        if self.worker_thread:
                            self.worker_thread.progress_updated.emit(
                                folder_path, completed_count, original_total_images, progress_percent, image_file
                            )
                            # Emit throttled bandwidth update ~10Hz
                            try:
                                now_ts = time.time()
                                if now_ts - self.worker_thread._bw_last_emit >= 0.1:
                                    total_bytes = 0
                                    max_elapsed = 0.0
                                    for it in self.worker_thread.queue_manager.get_all_items():
                                        if it.status == "uploading" and it.start_time:
                                            total_bytes += getattr(it, 'uploaded_bytes', 0)
                                            max_elapsed = max(max_elapsed, now_ts - it.start_time)
                                    if max_elapsed > 0:
                                        kbps = (total_bytes / max_elapsed) / 1024.0
                                        self.worker_thread.bandwidth_updated.emit(kbps)
                                        self.worker_thread._bw_last_emit = now_ts
                            except Exception:
                                pass
                        if not remaining.empty():
                            nxt = remaining.get()
                            futures_map[executor.submit(upload_single_image, nxt, retry_count + 1)] = nxt
            
            # Re-evaluate soft stop each iteration
            soft_stop_requested = False
            if self.worker_thread and self.worker_thread.current_item and self.worker_thread.current_item.path == folder_path:
                soft_stop_requested = getattr(self.worker_thread, '_soft_stop_requested_for', None) == folder_path
            failed_images = retry_failed
        
        # Sort uploaded images by original file order (use position map; unknowns go last)
        uploaded_images.sort(key=lambda x: file_position.get(x[0], 10**9))
        
        # Add to results in correct order
        for _, image_data in uploaded_images:
            results['images'].append(image_data)
        
        # Calculate statistics
        end_time = time.time()
        upload_time = end_time - start_time
        
        # Calculate transfer speed and dimension stats (robust to edge cases)
        try:
            uploaded_size = initial_uploaded_size + sum(
                os.path.getsize(os.path.join(folder_path, img_file)) for img_file, _ in uploaded_images
            )
        except Exception:
            uploaded_size = 0
        transfer_speed = uploaded_size / upload_time if upload_time > 0 else 0
        
        try:
            successful_dimensions = []
            # Include first image in averages if API-only fallback used
            if initial_completed == 1 and preseed_images:
                first_file = image_files[0]
                w, h = image_dimensions_map.get(first_file, (0, 0))
                if w > 0 and h > 0:
                    successful_dimensions.append((w, h))
            for img_file, _ in uploaded_images:
                w, h = image_dimensions_map.get(img_file, (0, 0))
                if w > 0 and h > 0:
                    successful_dimensions.append((w, h))
            avg_width = sum(w for w, h in successful_dimensions) / len(successful_dimensions) if successful_dimensions else 0
            avg_height = sum(h for w, h in successful_dimensions) / len(successful_dimensions) if successful_dimensions else 0
        except Exception:
            avg_width = 0
            avg_height = 0
        
        # Add statistics to results
        results.update({
            'gallery_id': gallery_id,
            'gallery_name': gallery_name,
            'upload_time': upload_time,
            'total_size': total_size,
            'uploaded_size': uploaded_size,
            'transfer_speed': transfer_speed,
            'avg_width': avg_width,
            'avg_height': avg_height,
            'successful_count': initial_completed + len(uploaded_images),
            'failed_count': len(failed_images),
            'failed_details': failed_images
        })
        
        # Ensure .uploaded exists; do not create a separate gallery_{id} folder here
        uploaded_subdir = os.path.join(folder_path, ".uploaded")
        os.makedirs(uploaded_subdir, exist_ok=True)
        
        # Create shortcut file (.url) to the gallery in .uploaded using standardized naming
        from imxup import build_gallery_filenames
        shortcut_content = f"""[InternetShortcut]
URL=https://imx.to/g/{gallery_id}
"""
        _, url_filename, _ = build_gallery_filenames(gallery_name, gallery_id)
        uploaded_shortcut_path = os.path.join(uploaded_subdir, url_filename)
        with open(uploaded_shortcut_path, 'w', encoding='utf-8') as f:
            f.write(shortcut_content)
        
        # Files will be created in on_gallery_completed when gallery_id is available
        print(f"{timestamp()} Gallery upload completed successfully")
        
        return results

class UploadWorker(QThread):
    """Worker thread for uploading galleries"""
    
    # Signals
    progress_updated = pyqtSignal(str, int, int, int, str)  # path, completed, total, progress%, current_image
    gallery_started = pyqtSignal(str, int)  # path, total_images
    gallery_completed = pyqtSignal(str, dict)  # path, results
    gallery_failed = pyqtSignal(str, str)  # path, error_message
    gallery_exists = pyqtSignal(str, list)  # gallery_name, existing_files
    log_message = pyqtSignal(str)
    bandwidth_updated = pyqtSignal(float)  # current KB/s across active uploads
    
    def __init__(self, queue_manager):
        super().__init__()
        self.queue_manager = queue_manager
        self.uploader = None
        self.running = True
        self.current_item = None
        self._soft_stop_requested_for = None
        self.auto_rename_enabled = True
        self._bw_last_emit = 0.0
        
    def stop(self):
        self.running = False
        self.wait()
    
    def request_soft_stop_current(self):
        """Request to stop the current item after in-flight uploads finish."""
        if self.current_item:
            self._soft_stop_requested_for = self.current_item.path
        
    def run(self):
        """Main worker thread loop"""
        try:
            # Initialize custom GUI uploader with reference to this worker
            self.uploader = GUIImxToUploader(worker_thread=self)
            
            # Login once for session reuse
            self.log_message.emit(f"{timestamp()} Logging in...")
            login_success = self.uploader.login()
            # Report the login method used (cookies, credentials, api_key, none)
            try:
                method = getattr(self.uploader, 'last_login_method', None)
                if method == 'cookies':
                    self.log_message.emit(f"{timestamp()} Authenticated using cookies")
                elif method == 'credentials':
                    self.log_message.emit(f"{timestamp()} Authenticated using username/password")
                elif method == 'api_key':
                    self.log_message.emit(f"{timestamp()} Using API key authentication (no web login)")
                elif method == 'none':
                    self.log_message.emit(f"{timestamp()} No credentials available; proceeding without web login")
            except Exception:
                pass
            if not login_success:
                self.log_message.emit(f"{timestamp()} Login failed - using API-only mode")
            else:
                # Method-specific post-login messaging and auto-rename gating
                try:
                    method = getattr(self.uploader, 'last_login_method', None)
                except Exception:
                    method = None

                if method in ('cookies', 'credentials'):
                    self.log_message.emit(f"{timestamp()} Login successful")
                    # Auto-rename unnamed galleries only when a web session exists
                    try:
                        if self.auto_rename_enabled:
                            renamed = rename_all_unnamed_with_session(self.uploader)
                            if renamed > 0:
                                self.log_message.emit(f"{timestamp()} Auto-renamed {renamed} gallery(ies) after login")
                            else:
                                self.log_message.emit(f"{timestamp()} No unnamed galleries to auto-rename")
                    except Exception as e:
                        self.log_message.emit(f"{timestamp()} Auto-rename error: {e}")
                elif method == 'api_key':
                    # API key present; no web session to rename galleries
                    self.log_message.emit(f"{timestamp()} API key loaded; web login skipped")
                    try:
                        if self.auto_rename_enabled:
                            self.log_message.emit(f"{timestamp()} Skipping auto-rename; web session required")
                    except Exception:
                        pass
                else:
                    # Fallback: unknown method but login reported success; do not auto-rename
                    self.log_message.emit(f"{timestamp()} Login successful")
            
            while self.running:
                # Get next item from queue
                item = self.queue_manager.get_next_item()
                if item is None:
                    time.sleep(0.1)
                    continue
                
                # Only process items that are queued to upload
                if item.status == "queued":
                    self.current_item = item
                    self.upload_gallery(item)
                elif item.status == "paused":
                    # Skip paused items
                    time.sleep(0.1)
                else:
                    # Put item back in queue if not ready
                    time.sleep(0.1)
                
        except Exception as e:
            self.log_message.emit(f"{timestamp()} Worker error: {str(e)}")
    
    def upload_gallery(self, item: GalleryQueueItem):
        """Upload a single gallery"""
        try:
            # Clear any previous soft-stop request when starting a new item
            self._soft_stop_requested_for = None
            self.log_message.emit(f"{timestamp()} Starting upload: {item.name or os.path.basename(item.path)}")
            
            # Set status to uploading and update display
            self.queue_manager.update_item_status(item.path, "uploading")
            item.status = "uploading"
            item.start_time = time.time()
            
            # Emit signal to update display immediately
            self.gallery_started.emit(item.path, item.total_images or 0)
            # If soft stop already requested by the time we start, reflect status to incomplete in UI
            if getattr(self, '_soft_stop_requested_for', None) == item.path:
                self.queue_manager.update_item_status(item.path, "incomplete")
            
            # Get default settings
            defaults = load_user_defaults()
            
            # Upload with progress tracking
            results = self.uploader.upload_folder(
                item.path,
                gallery_name=item.name,
                thumbnail_size=defaults.get('thumbnail_size', 3),
                thumbnail_format=defaults.get('thumbnail_format', 2),
                max_retries=defaults.get('max_retries', 3),
                public_gallery=defaults.get('public_gallery', 1),
                parallel_batch_size=defaults.get('parallel_batch_size', 4),
                template_name=item.template_name
            )
            # Save artifacts in worker thread to avoid blocking GUI
            try:
                self._save_artifacts(item.path, results)
                results['artifacts_saved'] = True
            except Exception as _e:
                # Log but do not fail the upload
                try:
                    self.log_message.emit(f"{timestamp()} Artifact save error: {_e}")
                except Exception:
                    pass
            
            # Check if item was paused during upload
            if item.status == "paused":
                self.log_message.emit(f"{timestamp()} Upload paused: {item.name}")
                return
            
            if results:
                item.end_time = time.time()
                item.gallery_url = results.get('gallery_url', '')
                item.gallery_id = results.get('gallery_id', '')
                # If soft stop requested and not all images uploaded, mark as incomplete
                if self._soft_stop_requested_for == item.path and results.get('successful_count', 0) < (item.total_images or 0):
                    self.queue_manager.update_item_status(item.path, "incomplete")
                    item.status = "incomplete"
                    self.log_message.emit(f"{timestamp()} Marked incomplete: {item.name}")
                    # Do not emit gallery_failed; just return to allow next item
                    return
                else:
                    # If some images failed, mark failed but still emit completed to generate BBCode for successes
                    failed_count = results.get('failed_count', 0)
                    if failed_count and results.get('successful_count', 0) > 0:
                        self.queue_manager.update_item_status(item.path, "failed")
                        # Still generate files and show as failed with partial content
                        self.gallery_completed.emit(item.path, results)
                        self.log_message.emit(f"{timestamp()} Completed with failures: {item.name} -> {item.gallery_url}")
                    else:
                        self.queue_manager.update_item_status(item.path, "completed")
                        self.gallery_completed.emit(item.path, results)
                        self.log_message.emit(f"{timestamp()} Completed: {item.name} -> {item.gallery_url}")
            else:
                # If soft stop was requested, do NOT mark failed; mark incomplete instead
                if self._soft_stop_requested_for == item.path:
                    self.queue_manager.update_item_status(item.path, "incomplete")
                    item.status = "incomplete"
                    self.log_message.emit(f"{timestamp()} Marked incomplete: {item.name}")
                else:
                    self.queue_manager.update_item_status(item.path, "failed")
                    self.gallery_failed.emit(item.path, "Upload failed")
                
        except Exception as e:
            error_msg = str(e)
            self.log_message.emit(f"{timestamp()} Error uploading {item.name}: {error_msg}")
            item.error_message = error_msg
            self.queue_manager.update_item_status(item.path, "failed")
            self.gallery_failed.emit(item.path, error_msg)
    
    def _save_artifacts(self, path: str, results: dict) -> None:
        """Write BBCode and JSON artifacts to disk. Runs in worker thread."""
        try:
            from imxup import (
                build_gallery_filenames,
                get_central_storage_path,
                load_user_defaults,
            )
            # Determine storage preferences
            defaults = load_user_defaults()
            store_in_uploaded = defaults.get('store_in_uploaded', True)
            store_in_central = defaults.get('store_in_central', True)
            gallery_id = results.get('gallery_id', '')
            gallery_name = results.get('gallery_name', os.path.basename(path))
            if not gallery_id or not gallery_name:
                return
            # Ensure .uploaded exists if needed
            uploaded_subdir = os.path.join(path, ".uploaded")
            if store_in_uploaded:
                os.makedirs(uploaded_subdir, exist_ok=True)
            # Build filenames
            _, json_filename, bbcode_filename = build_gallery_filenames(gallery_name, gallery_id)
            # Build BBCode from results images
            all_images_bbcode = ""
            for image_data in results.get('images', []):
                all_images_bbcode += image_data.get('bbcode', '') + "  "
            # Save BBCode
            if store_in_uploaded:
                with open(os.path.join(uploaded_subdir, bbcode_filename), 'w', encoding='utf-8') as f:
                    f.write(all_images_bbcode.strip())
            if store_in_central:
                central_path = get_central_storage_path()
                os.makedirs(central_path, exist_ok=True)
                with open(os.path.join(central_path, bbcode_filename), 'w', encoding='utf-8') as f:
                    f.write(all_images_bbcode.strip())
            # Build images JSON entries
            images_payload = []
            for image_data in results.get('images', []):
                orig_name = image_data.get('original_filename', '') or ''
                try:
                    if '.' in orig_name:
                        base, ext = os.path.splitext(orig_name)
                        filename_norm = base + ext.lower()
                    else:
                        filename_norm = orig_name
                except Exception:
                    filename_norm = orig_name
                img_url = image_data.get('image_url') or ''
                thumb_url = image_data.get('thumb_url')
                try:
                    if not thumb_url and img_url:
                        parts = img_url.split('/i/')
                        if len(parts) == 2 and parts[1]:
                            image_id = parts[1].split('/')[0]
                            _, ext = os.path.splitext(filename_norm)
                            ext = (ext.lower() or '.jpg') if ext else '.jpg'
                            thumb_url = f"https://imx.to/u/t/{image_id}{ext}"
                except Exception:
                    pass
                images_payload.append({
                    'filename': filename_norm,
                    'uploaded_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'image_url': img_url,
                    'thumb_url': thumb_url,
                    'bbcode': image_data.get('bbcode'),
                })
            # Failures
            failures_payload = [
                {
                    'filename': fname,
                    'failed_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'reason': reason
                }
                for fname, reason in results.get('failed_details', [])
            ]
            # Compose JSON
            json_payload = {
                'meta': {
                    'gallery_name': gallery_name,
                    'gallery_id': gallery_id,
                    'gallery_url': f"https://imx.to/g/{gallery_id}",
                    'status': 'completed',
                    'started_at': None,
                    'finished_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                },
                'settings': {
                    'thumbnail_size': results.get('thumbnail_size', 0),
                    'thumbnail_format': results.get('thumbnail_format', 0),
                    'public_gallery': results.get('public_gallery', 1),
                    'template_name': results.get('template_name', 'default'),
                    'parallel_batch_size': results.get('parallel_batch_size', 0)
                },
                'stats': {
                    'total_images': results.get('total_images', 0),
                    'successful_count': results.get('successful_count', 0),
                    'failed_count': results.get('failed_count', 0),
                    'upload_time': results.get('upload_time', 0),
                    'total_size': results.get('total_size', 0),
                    'uploaded_size': results.get('uploaded_size', 0),
                    'avg_width': results.get('avg_width', 0),
                    'avg_height': results.get('avg_height', 0),
                    'transfer_speed_mb_s': (results.get('transfer_speed', 0) / (1024*1024)) if results.get('transfer_speed', 0) else 0
                },
                'images': images_payload,
                'failures': failures_payload,
                'bbcode_full': all_images_bbcode.strip()
            }
            # Write JSON
            if store_in_uploaded:
                with open(os.path.join(uploaded_subdir, json_filename), 'w', encoding='utf-8') as jf:
                    json.dump(json_payload, jf, ensure_ascii=False, indent=2)
            if store_in_central:
                central_path = get_central_storage_path()
                with open(os.path.join(central_path, json_filename), 'w', encoding='utf-8') as jf:
                    json.dump(json_payload, jf, ensure_ascii=False, indent=2)
            try:
                self.log_message.emit(f"{timestamp()} Saved gallery files to central location: {get_central_storage_path()}")
            except Exception:
                pass
        except Exception:
            # Swallow any artifact exceptions here to not impact worker
            pass
    


class QueueManager:
    """Manages the gallery upload queue"""
    
    def __init__(self):
        self.items: Dict[str, GalleryQueueItem] = {}
        self.queue = Queue()
        self.mutex = QMutex()
        self.settings = QSettings("ImxUploader", "QueueManager")
        self._next_order = 0  # Track insertion order
        self._version = 0  # Bumped on any change for cheap UI polling
        self.load_persistent_queue()

    def _inc_version(self):
        self._version += 1

    def get_version(self) -> int:
        with QMutexLocker(self.mutex):
            return self._version
    
    def save_persistent_queue(self):
        """Save queue state to persistent storage"""
        queue_data = []
        for item in self.items.values():
            # Save all items except failed ones (unless they're completed)
            if item.status in ["ready", "queued", "paused", "completed", "incomplete"]:
                queue_data.append({
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
                    'uploaded_files': list(getattr(item, 'uploaded_files', set())),
                    'uploaded_images_data': list(getattr(item, 'uploaded_images_data', []))
                })
        
        self.settings.setValue("queue_items", queue_data)
        self.settings.sync()  # Force sync to disk
        print(f"DEBUG: Saved {len(queue_data)} items to persistent storage")
        #print(f"DEBUG: Current items in memory: {list(self.items.keys())}")
        #print(f"DEBUG: Items being saved: {[item['path'] for item in queue_data]}")
    
    def load_persistent_queue(self):
        """Load queue state from persistent storage"""
        queue_data = self.settings.value("queue_items", [])
        print(f"DEBUG: Loading persistent queue with {len(queue_data)} items")
        if queue_data:
            for item_data in queue_data:
                path = item_data.get('path', '')
                status = item_data.get('status', 'ready')
                
                #print(f"DEBUG: Loading item: {path} (status: {status})")
                
                # For completed items, don't check if path exists (might be moved/deleted)
                if status == "completed" or (os.path.exists(path) and os.path.isdir(path)):
                    if status == "completed":
                        # Restore completed item with saved data
                        item = GalleryQueueItem(
                            path=path,
                            name=item_data.get('name'),
                            status=status,
                            gallery_url=item_data.get('gallery_url', ''),
                            gallery_id=item_data.get('gallery_id', ''),
                            progress=item_data.get('progress', 100),
                            uploaded_images=item_data.get('uploaded_images', 0),
                            total_images=item_data.get('total_images', 0),
                            template_name=item_data.get('template_name', load_user_defaults().get('template_name', 'default')),
                            insertion_order=item_data.get('insertion_order', self._next_order),
                            added_time=item_data.get('added_time'),
                            finished_time=item_data.get('finished_time')
                        )
                        self._next_order = max(self._next_order, item.insertion_order + 1)
                        self.items[path] = item
                        #print(f"DEBUG: Loaded completed item: {path}")
                    else:
                        # Check for images and count them for non-completed items
                        image_extensions = ('.jpg', '.jpeg', '.png', '.gif')
                        image_files = []
                        for f in os.listdir(path):
                            if f.lower().endswith(image_extensions) and os.path.isfile(os.path.join(path, f)):
                                image_files.append(f)
                        
                        if image_files:
                            # Reset status to "ready" when loading to prevent auto-start
                            load_status = "ready" if status in ["queued", "uploading"] else status
                            item = GalleryQueueItem(
                                path=path,
                                name=item_data.get('name'),
                                status=load_status,
                                total_images=len(image_files),  # Set the total count
                                template_name=item_data.get('template_name', load_user_defaults().get('template_name', 'default')),
                                insertion_order=item_data.get('insertion_order', self._next_order),
                                added_time=item_data.get('added_time')
                            )
                            # Restore uploaded_files if present
                            uploaded_files = set(item_data.get('uploaded_files', []))
                            if uploaded_files:
                                item.uploaded_files = uploaded_files
                            # Restore uploaded_images_data if present
                            uploaded_images_data = item_data.get('uploaded_images_data', [])
                            if uploaded_images_data:
                                item.uploaded_images_data = uploaded_images_data
                            self._next_order = max(self._next_order, item.insertion_order + 1)
                            self.items[path] = item
                            #print(f"DEBUG: Loaded item: {path}")
                        else:
                            print(f"DEBUG: Skipped item (no images): {path}")
                else:
                    print(f"DEBUG: Skipped item (path doesn't exist): {path}")
        
        print(f"DEBUG: Loaded {len(self.items)} items total")
    
    def clear_persistent_queue(self):
        """Clear persistent queue storage (for testing)"""
        self.settings.remove("queue_items")
        self.settings.sync()
        print("DEBUG: Cleared persistent queue storage")
        
    def add_item(self, path: str, name: Optional[str] = None, template_name: str = "default") -> bool:
        """Add a gallery to the queue"""
        with QMutexLocker(self.mutex):
            if path in self.items:
                return False  # Already exists
                
            # Validate path
            if not os.path.exists(path) or not os.path.isdir(path):
                return False
                
            # Check for images and count them
            image_extensions = ('.jpg', '.jpeg', '.png', '.gif')
            image_files = []
            for f in os.listdir(path):
                if f.lower().endswith(image_extensions) and os.path.isfile(os.path.join(path, f)):
                    image_files.append(f)
            
            if not image_files:
                return False
            
            # Check for existing gallery files
            gallery_name = name or sanitize_gallery_name(os.path.basename(path))
            from imxup import check_if_gallery_exists
            existing_files = check_if_gallery_exists(gallery_name)
            
            if existing_files:
                # Return special value to indicate duplicate
                return "duplicate"
                
            # Create item in scanning state; start background scan after releasing lock
            item = GalleryQueueItem(
                path=path,
                name=gallery_name,
                status="scanning",
                total_images=len(image_files),
                insertion_order=self._next_order,
                added_time=time.time(),
                template_name=template_name,
                scan_complete=False
            )
            self._next_order += 1
            
            self.items[path] = item
            # Don't add to queue automatically - wait for manual start
            self.save_persistent_queue()
            self._inc_version()
        # Launch background scan outside the lock
        threading.Thread(target=self._scan_item_metadata, args=(path,), daemon=True).start()
        return True

    def _scan_item_metadata(self, path: str):
        """Scan image dimensions and total size without blocking UI, then mark ready."""
        try:
            image_extensions = ('.jpg', '.jpeg', '.png', '.gif')
            files = [f for f in os.listdir(path) if f.lower().endswith(image_extensions) and os.path.isfile(os.path.join(path, f))]
            if not files:
                with QMutexLocker(self.mutex):
                    if path in self.items:
                        self.items[path].status = "failed"
                        self.items[path].error_message = "No images found during scan"
                return
            total_size = 0
            dims: List[tuple[int, int]] = []
            sampled = 0
            for f in files:
                fp = os.path.join(path, f)
                try:
                    total_size += os.path.getsize(fp)
                    # Sample a limited number of images for dimensions to keep scan fast
                    if sampled < 25:
                        from PIL import Image
                        with Image.open(fp) as img:
                            w, h = img.size
                            dims.append((w, h))
                            sampled += 1
                except Exception:
                    # Skip unreadable files
                    continue
            avg_w = sum(w for w, _ in dims) / len(dims) if dims else 0.0
            avg_h = sum(h for _, h in dims) / len(dims) if dims else 0.0
            with QMutexLocker(self.mutex):
                if path in self.items:
                    item = self.items[path]
                    item.total_size = total_size
                    item.avg_width = avg_w
                    item.avg_height = avg_h
                    item.scan_complete = True
                    # Only flip to ready if not already moved forward
                    if item.status == "scanning":
                        item.status = "ready"
            # Persist update
            self.save_persistent_queue()
            self._inc_version()
            # Emit a GUI refresh if available
            # Note: avoid calling into GUI from worker thread; GUI polls or reacts to signals
        except Exception:
            with QMutexLocker(self.mutex):
                if path in self.items:
                    self.items[path].status = "ready"  # Fail open to allow start
                    self.items[path].scan_complete = False
            self.save_persistent_queue()
            self._inc_version()
    
    def start_item(self, path: str) -> bool:
        """Start a specific item in the queue"""
        with QMutexLocker(self.mutex):
            if path in self.items and self.items[path].status in ["ready", "paused", "incomplete"]:
                self.items[path].status = "queued"
                self.queue.put(self.items[path])
                self.save_persistent_queue()
                self._inc_version()
                return True
            return False
    
    def pause_item(self, path: str) -> bool:
        """Pause a specific item"""
        with QMutexLocker(self.mutex):
            if path in self.items and self.items[path].status == "uploading":
                self.items[path].status = "paused"
                self.save_persistent_queue()
                self._inc_version()
                return True
            return False
    
    def remove_item(self, path: str) -> bool:
        """Remove a gallery from the queue"""
        with QMutexLocker(self.mutex):
            if path in self.items:
                # Only prevent deletion of currently uploading items
                if self.items[path].status == "uploading":
                    return False
                del self.items[path]
                self.renumber_insertion_orders()
                self._inc_version()
                return True
            return False
    
    def get_next_item(self) -> Optional[GalleryQueueItem]:
        """Get the next queued item"""
        try:
            item = self.queue.get_nowait()
            # Check if item is still in the right status
            if item.path in self.items and self.items[item.path].status in ["queued", "uploading"]:
                return item
            else:
                # Item status changed, try to get next item
                return self.get_next_item()
        except Empty:
            return None
    
    def update_item_status(self, path: str, status: str):
        """Update item status"""
        with QMutexLocker(self.mutex):
            if path in self.items:
                self.items[path].status = status
                # Persist and bump version so GUI refreshes promptly
                try:
                    self.save_persistent_queue()
                finally:
                    self._inc_version()
    
    def get_all_items(self) -> List[GalleryQueueItem]:
        """Get all items, sorted by insertion order"""
        with QMutexLocker(self.mutex):
            items = sorted(self.items.values(), key=lambda x: x.insertion_order)
            #print(f"DEBUG: get_all_items returning {len(items)} items: {[item.path for item in items]}")
            return items
    
    def get_item(self, path: str) -> Optional[GalleryQueueItem]:
        """Get a specific item by path"""
        with QMutexLocker(self.mutex):
            return self.items.get(path)
    
    def renumber_insertion_orders(self):
        """Renumber insertion orders to be sequential (1, 2, 3, ...)"""
        with QMutexLocker(self.mutex):
            # Sort items by current insertion order to maintain relative order
            sorted_items = sorted(self.items.values(), key=lambda x: x.insertion_order)
            
            # Renumber starting from 1
            for i, item in enumerate(sorted_items, 1):
                item.insertion_order = i
            
            # Update the next order counter
            self._next_order = len(self.items) + 1
    
    def clear_completed(self):
        """Remove completed items"""
        with QMutexLocker(self.mutex):
            to_remove = [
                path for path, item in self.items.items() 
                if item.status in ["completed", "failed"]
            ]
            for path in to_remove:
                del self.items[path]
            
            # Renumber remaining items (don't save persistent queue yet)
            if to_remove:
                self.renumber_insertion_orders()
            
            return len(to_remove)
    
    def remove_items(self, paths: List[str]) -> int:
        """Remove specific items from the queue"""
        with QMutexLocker(self.mutex):
            removed_count = 0
            #print(f"DEBUG: remove_items called with paths: {paths}")
            #print(f"DEBUG: Current items: {list(self.items.keys())}")
            
            for path in paths:
                #print(f"DEBUG: Checking path: {path}")
                if path in self.items:
                    #print(f"DEBUG: Path found, status: {self.items[path].status}")
                    # Only prevent deletion of currently uploading items
                    if self.items[path].status == "uploading":
                        print(f"DEBUG: Skipping uploading item: {path}")
                        continue
                    #print(f"DEBUG: Deleting item: {path}")
                    del self.items[path]
                    removed_count += 1
                else:
                    print(f"DEBUG: Path not found: {path}")
            
            #print(f"DEBUG: Removed count: {removed_count}")
            print(f"DEBUG: {removed_count} items remaining after deletion: {list(self.items.keys())}")
            
            # Verify deletion actually worked
            for path in paths:
                if path in self.items:
                    print(f"ERROR: Item {path} was NOT actually deleted!")
                else:
                    print(f"Item {path} deleted")
            
            # Renumber remaining items (don't save persistent queue yet - let GUI handle it)
            if removed_count > 0:
                self.renumber_insertion_orders()
                #print(f"DEBUG: Renumbered items after deletion")
            
            return removed_count
    
    def _force_add_item(self, path: str, name: str, template_name: str = "default"):
        """Force add an item (for duplicate handling)"""
        with QMutexLocker(self.mutex):
            # Check for images and count them
            image_extensions = ('.jpg', '.jpeg', '.png', '.gif')
            image_files = []
            for f in os.listdir(path):
                if f.lower().endswith(image_extensions) and os.path.isfile(os.path.join(path, f)):
                    image_files.append(f)
            
            if not image_files:
                return False
                
            item = GalleryQueueItem(
                path=path,
                name=name,
                status="ready",  # Items start as ready
                total_images=len(image_files),  # Set the total count immediately
                insertion_order=self._next_order,
                added_time=time.time(),  # Current timestamp
                template_name=template_name
            )
            self._next_order += 1
            
            self.items[path] = item
            self.save_persistent_queue()
            return True

class GalleryTableWidget(QTableWidget):
    """Table widget for gallery queue with resizable columns, sorting, and action buttons"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Setup table
        self.setColumnCount(8)
        self.setHorizontalHeaderLabels(["#", "Gallery Name", "Uploaded", "Progress", "Status", "Added", "Finished", "Actions"])
        
        # Configure columns
        header = self.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)         # Order - fixed
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)       # Gallery Name - stretch to fill space
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)   # Uploaded - resizable
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)   # Progress - resizable
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)   # Status - resizable
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Interactive)   # Added - resizable
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Interactive)   # Finished - resizable
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.Fixed)         # Actions - fixed
        
        # Set initial column widths
        self.setColumnWidth(0, 40)   # Order (narrow)
        self.setColumnWidth(1, 300)  # Gallery Name (wider)
        self.setColumnWidth(2, 100)  # Uploaded (wider)
        self.setColumnWidth(3, 220)  # Progress (wider)
        self.setColumnWidth(4, 120)  # Status (wider)
        self.setColumnWidth(5, 140)  # Added (wider for YYYY-MM-DD format)
        self.setColumnWidth(6, 140)  # Finished (wider for YYYY-MM-DD format)
        self.setColumnWidth(7, 80)   # Actions
        
        # Enable sorting but start with no sorting (insertion order)
        self.setSortingEnabled(True)
        self.horizontalHeader().setSortIndicatorShown(False)  # No initial sort indicator
        
        # Styling - consolidated single stylesheet
        self.setStyleSheet("""
            QTableWidget {
                gridline-color: rgba(128, 128, 128, 0.1);
                alternate-background-color: rgba(240, 240, 240, 0.3);
                border: 1px solid #ccc;
                border-radius: 4px;
                background-color: white;
            }
            QTableWidget::item {
                padding: 0px 4px;
                border: none;
            }
            QTableWidget::item:selected {
                background-color: #2980b9;
                color: white;
            }
            QHeaderView::section {
                background-color: #f0f0f0;
                padding: 5px; /* reduce header height to ~60% */
                border: none;
                font-weight: bold;
                border-bottom: 2px solid #3498db;
            }
            QHeaderView::section:hover {
                background-color: #e0e0e0;
            }
        """)
        self.setShowGrid(True)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(32)  # Compact rows
        
        # Enable multi-selection
        self.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        
        # Set focus policy to ensure keyboard events work
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        
        # Enable context menu on the viewport to get coordinates in viewport space
        self.viewport().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.viewport().customContextMenuRequested.connect(self.show_context_menu)
    
    def keyPressEvent(self, event):
        """Handle key press events"""
        if event.key() == Qt.Key.Key_Delete:
            # Find the main GUI window by walking up the parent chain
            widget = self
            while widget:
                if hasattr(widget, 'delete_selected_items'):
                    widget.delete_selected_items()
                    return
                widget = widget.parent()
        elif event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
            # Handle Enter key for completed items
            self.handle_enter_or_double_click()
        elif event.modifiers() == Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_C:
            # Handle Ctrl+C for copying BBCode
            self.handle_copy_bbcode()
            return  # Don't call super() to prevent default table copy behavior
        
        super().keyPressEvent(event)
    
    def mouseDoubleClickEvent(self, event):
        """Handle double-click events"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.handle_enter_or_double_click()
        super().mouseDoubleClickEvent(event)
    
    def mousePressEvent(self, event):
        """Keep focus behavior on left-click; do not interfere with context menu events"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
        super().mousePressEvent(event)
    
    def handle_enter_or_double_click(self):
        """Handle Enter key or double-click for viewing completed items"""
        current_row = self.currentRow()
        if current_row >= 0:
            name_item = self.item(current_row, 1)  # Gallery name is now column 1
            if name_item:
                path = name_item.data(Qt.ItemDataRole.UserRole)
                if path:
                    # Find the main GUI window and check if item is completed
                    widget = self
                    while widget:
                        if hasattr(widget, 'view_bbcode_files'):
                            widget.view_bbcode_files(path)
                            return
                        widget = widget.parent()
    
    def handle_copy_bbcode(self):
        """Handle Ctrl+C for copying BBCode for all selected completed items"""
        # Collect selected completed item paths
        selected_rows = sorted({it.row() for it in self.selectedItems()})
        paths = []
        for row in selected_rows:
            name_item = self.item(row, 1)
            if name_item:
                path = name_item.data(Qt.ItemDataRole.UserRole)
                if path:
                    paths.append(path)
        if not paths:
            return
        # Delegate to the multi-copy helper to aggregate
        self.copy_bbcode_via_menu_multi(paths)
    
    def show_context_menu(self, position):
        """Show context menu for table items"""
        from PyQt6.QtWidgets import QMenu
        
        menu = QMenu()

        # Position is already in viewport coordinates
        viewport_pos = position
        global_pos = self.viewport().mapToGlobal(position)

        # Select row under cursor if not already selected using model index for reliability
        index = self.indexAt(viewport_pos)
        if index.isValid():
            row = index.row()
            if row != self.currentRow():
                self.clearSelection()
                self.selectRow(row)
        
        # Build selected rows robustly via selection model (target column 1)
        selected_paths = []
        sel_model = self.selectionModel()
        if sel_model is not None:
            for idx in sel_model.selectedRows(1):
                row = idx.row()
                name_item = self.item(row, 1)
                if name_item:
                    path = name_item.data(Qt.ItemDataRole.UserRole)
                    if path:
                        selected_paths.append(path)

        if selected_paths:
            # Start Selected (ready/paused/incomplete -> queued) in display order
            # Determine if any selected items are startable; disable if none are
            widget = self
            while widget and not hasattr(widget, 'queue_manager'):
                widget = widget.parent()
            can_start_any = False
            if widget and hasattr(widget, 'queue_manager'):
                for path in selected_paths:
                    item = widget.queue_manager.get_item(path)
                    if item and item.status in ("ready", "paused", "incomplete"):
                        can_start_any = True
                        break
            start_action = menu.addAction("Start Selected")
            start_action.setEnabled(can_start_any)
            start_action.triggered.connect(self.start_selected_via_menu)

            # Delete
            delete_action = menu.addAction("Delete Selected")
            delete_action.triggered.connect(self.delete_selected_via_menu)

            # Open Folder (always available for selected items)
            open_action = menu.addAction("Open Folder")
            open_action.triggered.connect(lambda: self.open_folders_via_menu(selected_paths))

            # Cancel (for queued items)
            queued_paths = []
            # widget is already resolved above; if not, resolve now
            if not (widget and hasattr(widget, 'queue_manager')):
                widget = self
                while widget and not hasattr(widget, 'queue_manager'):
                    widget = widget.parent()
            if widget and hasattr(widget, 'queue_manager'):
                for path in selected_paths:
                    item = widget.queue_manager.get_item(path)
                    if item and item.status == "queued":
                        queued_paths.append(path)
            if queued_paths:
                cancel_action = menu.addAction("Cancel Upload")
                cancel_action.triggered.connect(lambda: self.cancel_selected_via_menu(queued_paths))

            # Copy BBCode (for completed items)
            completed_paths = []
            if widget and hasattr(widget, 'queue_manager'):
                for path in selected_paths:
                    item = widget.queue_manager.get_item(path)
                    if item and item.status == "completed":
                        completed_paths.append(path)
            if completed_paths:
                copy_action = menu.addAction("Copy BBCode")
                copy_action.triggered.connect(lambda: self.copy_bbcode_via_menu_multi(completed_paths))
        
        else:
            # No selection: offer Add Folders via the same dialog as the toolbar button
            add_action = menu.addAction("Add Folders...")
            def _add_from_menu():
                widget = self
                while widget and not hasattr(widget, 'browse_for_folders'):
                    widget = widget.parent()
                if widget and hasattr(widget, 'browse_for_folders'):
                    widget.browse_for_folders()
            add_action.triggered.connect(_add_from_menu)

        # Only show menu if there are actions
        if menu.actions():
            menu.exec(global_pos)
    
    def contextMenuEvent(self, event):
        """Fallback to ensure context menu always appears on right-click"""
        try:
            viewport_pos = self.viewport().mapFromGlobal(event.globalPos())
        except Exception:
            viewport_pos = event.pos()
        self.show_context_menu(viewport_pos)
    
    def delete_selected_via_menu(self):
        """Delete selected items via context menu"""
        # Find the main GUI window
        widget = self
        while widget:
            if hasattr(widget, 'delete_selected_items'):
                widget.delete_selected_items()
                return
            widget = widget.parent()

    def start_selected_via_menu(self):
        """Start selected items in their current visual order"""
        # Determine selected rows in visual order as shown
        selected_rows = sorted({it.row() for it in self.selectedItems()})
        if not selected_rows:
            return
        # Gather paths from column 1 for those rows
        paths_in_order = []
        for row in selected_rows:
            name_item = self.item(row, 1)
            if name_item:
                path = name_item.data(Qt.ItemDataRole.UserRole)
                if path:
                    paths_in_order.append(path)
        if not paths_in_order:
            return
        # Delegate to main window to start items individually preserving order
        widget = self
        while widget and not hasattr(widget, 'queue_manager'):
            widget = widget.parent()
        if not widget:
            return
        started = 0
        for path in paths_in_order:
            if widget.queue_manager.start_item(path):
                started += 1
        if started:
            if hasattr(widget, 'add_log_message'):
                from imxup import timestamp
                widget.add_log_message(f"{timestamp()} Started {started} selected item(s)")
            if hasattr(widget, 'update_queue_display'):
                widget.update_queue_display()
    
    def open_folders_via_menu(self, paths):
        """Open the given gallery folders in the OS file manager"""
        for path in paths:
            if os.path.isdir(path):
                QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def cancel_selected_via_menu(self, queued_paths):
        """Cancel upload for selected queued items"""
        widget = self
        while widget and not hasattr(widget, 'cancel_single_item'):
            widget = widget.parent()
        if widget and hasattr(widget, 'cancel_single_item'):
            for path in queued_paths:
                widget.cancel_single_item(path)

    def copy_bbcode_via_menu_multi(self, paths):
        """Copy BBCode for multiple completed items (concatenated with separators)"""
        # Find the main GUI window
        widget = self
        while widget and not hasattr(widget, 'copy_bbcode_to_clipboard'):
            widget = widget.parent()
        if not widget:
            return
        # Aggregate BBCode contents; reuse copy function to centralize path lookup
        contents = []
        for path in paths:
            item = widget.queue_manager.get_item(path)
            if not item or item.status != "completed":
                continue
            # Inline read similar to copy_bbcode_to_clipboard to avoid changing it
            folder_name = os.path.basename(path)
            from imxup import get_central_storage_path, build_gallery_filenames
            central_path = get_central_storage_path()
            if item.gallery_id and (item.name or folder_name):
                _, _, bbcode_filename = build_gallery_filenames(item.name or folder_name, item.gallery_id)
                central_bbcode = os.path.join(central_path, bbcode_filename)
            else:
                central_bbcode = os.path.join(central_path, f"{folder_name}_bbcode.txt")
            text = ""
            if os.path.exists(central_bbcode):
                try:
                    with open(central_bbcode, 'r', encoding='utf-8') as f:
                        text = f.read().strip()
                except Exception:
                    text = ""
            if text:
                contents.append(text)
        num_posts = len(contents)
        if num_posts:
            QApplication.clipboard().setText("\n\n".join(contents))
            # Notify user via log and brief status message
            try:
                message = f"Copied BBCode to clipboard for {num_posts} post" + ("s" if num_posts != 1 else "")
                # Log
                if hasattr(widget, 'add_log_message'):
                    from imxup import timestamp
                    widget.add_log_message(f"{timestamp()} {message}")
                # Status bar brief message
                if hasattr(widget, 'statusBar') and widget.statusBar():
                    widget.statusBar().showMessage(message, 2500)
            except Exception:
                pass
        else:
            # Inform user nothing was copied
            try:
                message = "No completed posts selected to copy BBCode"
                if hasattr(widget, 'add_log_message'):
                    from imxup import timestamp
                    widget.add_log_message(f"{timestamp()} {message}")
                if hasattr(widget, 'statusBar') and widget.statusBar():
                    widget.statusBar().showMessage(message, 2500)
            except Exception:
                pass

class ActionButtonWidget(QWidget):
    """Action buttons widget for table cells"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        
        
        self.start_btn = QPushButton("Start")
        self.start_btn.setFixedSize(65, 25)
        
        #self.start_btn.setStyleSheet("""
        #    QPushButton {
        #        background-color: #d8f0e2;
        #        border: 1px solid #85a190;
        #        border-radius: 3px;
        #        font-size: 12px;
        #    }
        #    QPushButton:hover {
        #        background-color: #bee6cf;
        #        border: 1px solid #85a190;
        #    }
        #    QPushButton:pressed {
        #        background-color: #6495ed;
        #        border: 1px solid #1e2c47;
        #    }
        #""")
        
        self.stop_btn = QPushButton("Stop")
        
        self.stop_btn.setFixedSize(65, 25)
        self.stop_btn.setVisible(False)
        #self.stop_btn.setStyleSheet("""
        #    QPushButton {
        #        background-color: #f0938a;

        #        border: 1px solid #cf4436;
        #        border-radius: 3px;
        #        font-size: 12px;

        #    }
        #    QPushButton:hover {
        #        background-color: #c0392b;
        #    }
        #    QPushButton:pressed {
        #        background-color: #a93226;
        #        border: 1px solid #8b291a;
        #    }
        #""")
        
        self.view_btn = QPushButton("View")
        self.view_btn.setFixedSize(65, 25)
        self.view_btn.setVisible(False)
        #self.view_btn.setStyleSheet("""
        #    QPushButton {
        #        background-color: #dfe9fb;
        #        border: 1px solid #999;
        #        border-radius: 3px;
        #        font-size: 12px;

        #    }
        #    QPushButton:hover {
        #        background-color: #c8d9f8;
        #        border: 1px solid #7b8dac;
        #    }
        #    QPushButton:pressed {
        #        background-color: #072213;
        #    }
        #""")
        
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setFixedSize(65, 25)
        self.cancel_btn.setVisible(False)
        #self.cancel_btn.setStyleSheet("""
        #    QPushButton {
        #        background-color: #f7c370;
        #        border: 1px solid #aa6d0c;
        #        border-radius: 3px;
        #        font-size: 12px;
        #    }
        #    QPushButton:hover {
        #        background-color: #f5af41;
        #        border: 1px solid #794e09;
        #    }
        #    QPushButton:pressed {
        #        background-color: #f39c12;
        #        border: 1px solid #482e05;
        #    }
        #""")
        
        layout.addStretch()  # Left stretch
        layout.addWidget(self.start_btn)
        layout.addWidget(self.stop_btn)
        layout.addWidget(self.view_btn)
        layout.addWidget(self.cancel_btn)
        layout.addStretch()  # Right stretch
    
    def update_buttons(self, status: str):
        """Update button visibility based on status"""
        if status == "ready":
            self.start_btn.setVisible(True)
            self.start_btn.setText("Start")
            self.stop_btn.setVisible(False)
            self.view_btn.setVisible(False)
            self.cancel_btn.setVisible(False)
        elif status == "queued":
            self.start_btn.setVisible(False)
            self.stop_btn.setVisible(False)
            self.view_btn.setVisible(False)
            self.cancel_btn.setVisible(True)
        elif status == "uploading":
            self.start_btn.setVisible(False)
            self.stop_btn.setVisible(True)
            self.view_btn.setVisible(False)
            self.cancel_btn.setVisible(False)
        elif status == "paused":
            self.start_btn.setVisible(True)
            self.start_btn.setText("Resume")
            self.stop_btn.setVisible(False)
            self.view_btn.setVisible(False)
            self.cancel_btn.setVisible(False)
        elif status == "incomplete":
            self.start_btn.setVisible(True)
            self.start_btn.setText("Resume")
            self.stop_btn.setVisible(False)
            self.view_btn.setVisible(False)
            self.cancel_btn.setVisible(False)
        elif status == "completed":
            self.start_btn.setVisible(False)
            self.stop_btn.setVisible(False)
            self.view_btn.setVisible(True)
            self.cancel_btn.setVisible(False)
        else:  # failed
            self.start_btn.setVisible(False)
            self.stop_btn.setVisible(False)
            self.view_btn.setVisible(False)
            self.cancel_btn.setVisible(False)

class CredentialSetupDialog(QDialog):
    """Dialog for setting up secure credentials"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Setup Secure Credentials")
        self.setModal(True)
        self.resize(500, 430)
        
        layout = QVBoxLayout(self)
        
        # Info text
        info_text = QLabel(
            "IMX.to Gallery Uploader credentials:\n\n"
            "• API Key: Required for uploading files\n"
            "• Username/Password: Required for naming galleries\n\n"
            "Without username/password, all galleries will be named \'untitled gallery\'\n\n"
            "Credentials are stored in your home directory, encrypted with AES-128-CBC via Fernet using system's hostname/username as the encryption key.\n\n"
            "This means:\n"
            "• They cannot be recovered if forgotten (you'll have to reset on imx.to)\n"
            "• The encrypted data won't work on other computers\n"
            "• Credentials are obfuscated from other users on this system\n\n"
            "Get your API key from: https://imx.to/user/api"
            
            
        )
        info_text.setWordWrap(True)
        info_text.setStyleSheet("padding: 10px; background-color: #f0f8ff; border: 1px solid #ccc; border-radius: 5px;")
        layout.addWidget(info_text)
        

        
        # Credential status display
        status_group = QGroupBox("Current Credentials")
        status_layout = QVBoxLayout(status_group)
        
        # Username status
        username_status_layout = QHBoxLayout()
        username_status_layout.addWidget(QLabel("Username: "))
        self.username_status_label = QLabel("NOT SET")
        self.username_status_label.setStyleSheet("color: #666; font-style: italic;")
        username_status_layout.addWidget(self.username_status_label)
        username_status_layout.addStretch()
        self.username_change_btn = QPushButton("Set")
        if not self.username_change_btn.text().startswith(" "):
            self.username_change_btn.setText(" " + self.username_change_btn.text())
        self.username_change_btn.clicked.connect(self.change_username)
        username_status_layout.addWidget(self.username_change_btn)
        self.username_remove_btn = QPushButton("Unset")
        if not self.username_remove_btn.text().startswith(" "):
            self.username_remove_btn.setText(" " + self.username_remove_btn.text())
        self.username_remove_btn.clicked.connect(self.remove_username)
        username_status_layout.addWidget(self.username_remove_btn)
        status_layout.addLayout(username_status_layout)
        
        # Password status
        password_status_layout = QHBoxLayout()
        password_status_layout.addWidget(QLabel("Password: "))
        self.password_status_label = QLabel("NOT SET")
        self.password_status_label.setStyleSheet("color: #666; font-style: italic;")
        password_status_layout.addWidget(self.password_status_label)
        password_status_layout.addStretch()
        self.password_change_btn = QPushButton("Set")
        if not self.password_change_btn.text().startswith(" "):
            self.password_change_btn.setText(" " + self.password_change_btn.text())
        self.password_change_btn.clicked.connect(self.change_password)
        password_status_layout.addWidget(self.password_change_btn)
        self.password_remove_btn = QPushButton("Unset")
        if not self.password_remove_btn.text().startswith(" "):
            self.password_remove_btn.setText(" " + self.password_remove_btn.text())
        self.password_remove_btn.clicked.connect(self.remove_password)
        password_status_layout.addWidget(self.password_remove_btn)
        status_layout.addLayout(password_status_layout)
        
        # API Key status
        api_key_status_layout = QHBoxLayout()
        api_key_status_layout.addWidget(QLabel("API Key: "))
        self.api_key_status_label = QLabel("NOT SET")
        self.api_key_status_label.setStyleSheet("color: #666; font-style: italic;")
        api_key_status_layout.addWidget(self.api_key_status_label)
        api_key_status_layout.addStretch()
        self.api_key_change_btn = QPushButton("Set")
        if not self.api_key_change_btn.text().startswith(" "):
            self.api_key_change_btn.setText(" " + self.api_key_change_btn.text())
        self.api_key_change_btn.clicked.connect(self.change_api_key)
        api_key_status_layout.addWidget(self.api_key_change_btn)
        self.api_key_remove_btn = QPushButton("Unset")
        if not self.api_key_remove_btn.text().startswith(" "):
            self.api_key_remove_btn.setText(" " + self.api_key_remove_btn.text())
        self.api_key_remove_btn.clicked.connect(self.remove_api_key)
        api_key_status_layout.addWidget(self.api_key_remove_btn)
        status_layout.addLayout(api_key_status_layout)

        # Firefox cookies toggle status
        cookies_status_layout = QHBoxLayout()
        cookies_status_layout.addWidget(QLabel("Firefox cookies: "))
        self.cookies_status_label = QLabel("Unknown")
        self.cookies_status_label.setStyleSheet("color: #666; font-style: italic;")
        cookies_status_layout.addWidget(self.cookies_status_label)
        cookies_status_layout.addStretch()
        self.cookies_enable_btn = QPushButton("Enable")
        if not self.cookies_enable_btn.text().startswith(" "):
            self.cookies_enable_btn.setText(" " + self.cookies_enable_btn.text())
        self.cookies_enable_btn.clicked.connect(self.enable_cookies_setting)
        cookies_status_layout.addWidget(self.cookies_enable_btn)
        self.cookies_disable_btn = QPushButton("Disable")
        if not self.cookies_disable_btn.text().startswith(" "):
            self.cookies_disable_btn.setText(" " + self.cookies_disable_btn.text())
        self.cookies_disable_btn.clicked.connect(self.disable_cookies_setting)
        cookies_status_layout.addWidget(self.cookies_disable_btn)
        status_layout.addLayout(cookies_status_layout)
        
        layout.addWidget(status_group)
        
        # Remove all button under the status group
        destructive_layout = QHBoxLayout()
        # Place on bottom-left to reduce accidental clicks
        destructive_layout.addStretch()  # we'll remove this and add after button to push left
        self.remove_all_btn = QPushButton("Unset All")
        if not self.remove_all_btn.text().startswith(" "):
            self.remove_all_btn.setText(" " + self.remove_all_btn.text())
        self.remove_all_btn.clicked.connect(self.remove_all_credentials)
        destructive_layout.insertWidget(0, self.remove_all_btn)
        destructive_layout.addStretch()
        layout.addLayout(destructive_layout)
        
        # Hidden input fields for editing
        self.username_edit = QLineEdit()
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        
        # Load current credentials
        self.load_current_credentials()
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        self.close_btn = QPushButton("Close")
        if not self.close_btn.text().startswith(" "):
            self.close_btn.setText(" " + self.close_btn.text())
        self.close_btn.clicked.connect(self.validate_and_close)
        button_layout.addWidget(self.close_btn)
        
        layout.addLayout(button_layout)
        

    
    def load_current_credentials(self):
        """Load and display current credentials"""
        config = configparser.ConfigParser()
        config_file = get_config_path()
        
        if os.path.exists(config_file):
            config.read(config_file)
            if 'CREDENTIALS' in config:
                # Check username/password
                username = config.get('CREDENTIALS', 'username', fallback='')
                password = config.get('CREDENTIALS', 'password', fallback='')
                
                if username:
                    self.username_status_label.setText(username)
                    self.username_status_label.setStyleSheet("color: #27ae60; font-weight: bold;")
                    # Buttons: Change/Unset
                    try:
                        txt = " Change"
                        if not txt.startswith(" "):
                            txt = " " + txt
                        self.username_change_btn.setText(txt)
                    except Exception:
                        self.username_change_btn.setText(" Change")
                    self.username_remove_btn.setEnabled(True)
                else:
                    self.username_status_label.setText("NOT SET")
                    self.username_status_label.setStyleSheet("color: #666; font-style: italic;")
                    try:
                        txt = " Set"
                        if not txt.startswith(" "):
                            txt = " " + txt
                        self.username_change_btn.setText(txt)
                    except Exception:
                        self.username_change_btn.setText(" Set")
                    self.username_remove_btn.setEnabled(False)
                
                if password:
                    self.password_status_label.setText("********")
                    self.password_status_label.setStyleSheet("color: #27ae60; font-weight: bold;")
                    try:
                        txt = " Change"
                        if not txt.startswith(" "):
                            txt = " " + txt
                        self.password_change_btn.setText(txt)
                    except Exception:
                        self.password_change_btn.setText(" Change")
                    self.password_remove_btn.setEnabled(True)
                else:
                    self.password_status_label.setText("NOT SET")
                    self.password_status_label.setStyleSheet("color: #666; font-style: italic;")
                    try:
                        txt = " Set"
                        if not txt.startswith(" "):
                            txt = " " + txt
                        self.password_change_btn.setText(txt)
                    except Exception:
                        self.password_change_btn.setText(" Set")
                    self.password_remove_btn.setEnabled(False)
                
                # Check API key
                encrypted_api_key = config.get('CREDENTIALS', 'api_key', fallback='')
                if encrypted_api_key:
                    try:
                        api_key = decrypt_password(encrypted_api_key)
                        if api_key and len(api_key) > 8:
                            masked_key = api_key[:4] + "*" * 20 + api_key[-4:]
                            self.api_key_status_label.setText(masked_key)
                            self.api_key_status_label.setStyleSheet("color: #27ae60; font-weight: bold;")
                            try:
                                txt = " Change"
                                if not txt.startswith(" "):
                                    txt = " " + txt
                                self.api_key_change_btn.setText(txt)
                            except Exception:
                                self.api_key_change_btn.setText(" Change")
                            self.api_key_remove_btn.setEnabled(True)
                        else:
                            self.api_key_status_label.setText("SET")
                            self.api_key_status_label.setStyleSheet("color: #27ae60; font-weight: bold;")
                            try:
                                txt = " Change"
                                if not txt.startswith(" "):
                                    txt = " " + txt
                                self.api_key_change_btn.setText(txt)
                            except Exception:
                                self.api_key_change_btn.setText(" Change")
                            self.api_key_remove_btn.setEnabled(True)
                    except:
                        self.api_key_status_label.setText("SET")
                        self.api_key_status_label.setStyleSheet("color: #27ae60; font-weight: bold;")
                        try:
                            txt = " Change"
                            if not txt.startswith(" "):
                                txt = " " + txt
                            self.api_key_change_btn.setText(txt)
                        except Exception:
                            self.api_key_change_btn.setText(" Change")
                        self.api_key_remove_btn.setEnabled(True)
                else:
                    self.api_key_status_label.setText("NOT SET")
                    self.api_key_status_label.setStyleSheet("color: #666; font-style: italic;")
                     # When not set, offer Set and disable Unset
                    try:
                        txt = " Set"
                        if not txt.startswith(" "):
                            txt = " " + txt
                        self.api_key_change_btn.setText(txt)
                    except Exception:
                        self.api_key_change_btn.setText(" Set")
                    self.api_key_remove_btn.setEnabled(False)

                # Cookies setting
                cookies_enabled_val = str(config['CREDENTIALS'].get('cookies_enabled', 'true')).lower()
                cookies_enabled = cookies_enabled_val != 'false'
                if cookies_enabled:
                    self.cookies_status_label.setText("Enabled")
                    self.cookies_status_label.setStyleSheet("color: #27ae60; font-weight: bold;")
                else:
                    self.cookies_status_label.setText("Disabled")
                    self.cookies_status_label.setStyleSheet("color: #c0392b; font-weight: bold;")
                # Toggle button states
                self.cookies_enable_btn.setEnabled(not cookies_enabled)
                self.cookies_disable_btn.setEnabled(cookies_enabled)
        else:
            # Defaults if no file
            self.cookies_status_label.setText("Enabled")
            self.cookies_status_label.setStyleSheet("color: #27ae60; font-weight: bold;")
            self.cookies_enable_btn.setEnabled(False)
            self.cookies_disable_btn.setEnabled(True)
    
    def change_username(self):
        """Open dialog to change username only"""
        dialog = QDialog(self)
        dialog.setWindowTitle("Set Username")
        dialog.setModal(True)
        dialog.resize(400, 140)
        
        layout = QVBoxLayout(dialog)
        
        # Username input only
        username_layout = QHBoxLayout()
        username_layout.addWidget(QLabel("Username:"))
        username_edit = QLineEdit()
        username_layout.addWidget(username_edit)
        layout.addLayout(username_layout)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        save_btn = QPushButton("Save")
        save_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
        save_btn.setIconSize(QSize(16, 16))
        if not save_btn.text().startswith(" "):
            save_btn.setText(" " + save_btn.text())
        save_btn.clicked.connect(dialog.accept)
        button_layout.addWidget(save_btn)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogCancelButton))
        cancel_btn.setIconSize(QSize(16, 16))
        if not cancel_btn.text().startswith(" "):
            cancel_btn.setText(" " + cancel_btn.text())
        cancel_btn.clicked.connect(dialog.reject)
        button_layout.addWidget(cancel_btn)
        
        layout.addLayout(button_layout)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            username = username_edit.text().strip()
            if username:
                try:
                    config = configparser.ConfigParser()
                    config_file = get_config_path()
                    
                    if os.path.exists(config_file):
                        config.read(config_file)
                    
                    if 'CREDENTIALS' not in config:
                        config['CREDENTIALS'] = {}
                    
                    config['CREDENTIALS']['username'] = username
                    # Don't clear API key - allow both to exist
                    
                    with open(config_file, 'w') as f:
                        config.write(f)
                    
                    self.load_current_credentials()
                    QMessageBox.information(self, "Success", "Username saved successfully!")
                    
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"Failed to save credentials: {str(e)}")
            else:
                QMessageBox.warning(self, "Missing Information", "Please enter a username.")

    def change_password(self):
        """Open dialog to change password only"""
        dialog = QDialog(self)
        dialog.setWindowTitle("Set Password")
        dialog.setModal(True)
        dialog.resize(400, 140)
        
        layout = QVBoxLayout(dialog)
        
        # Password input only
        password_layout = QHBoxLayout()
        password_layout.addWidget(QLabel("Password:"))
        password_edit = QLineEdit()
        password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        password_layout.addWidget(password_edit)
        layout.addLayout(password_layout)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        save_btn = QPushButton("Save")
        save_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
        save_btn.setIconSize(QSize(16, 16))
        if not save_btn.text().startswith(" "):
            save_btn.setText(" " + save_btn.text())
        save_btn.clicked.connect(dialog.accept)
        button_layout.addWidget(save_btn)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogCancelButton))
        cancel_btn.setIconSize(QSize(16, 16))
        if not cancel_btn.text().startswith(" "):
            cancel_btn.setText(" " + cancel_btn.text())
        cancel_btn.clicked.connect(dialog.reject)
        button_layout.addWidget(cancel_btn)
        
        layout.addLayout(button_layout)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            password = password_edit.text()
            if password:
                try:
                    config = configparser.ConfigParser()
                    config_file = get_config_path()
                    
                    if os.path.exists(config_file):
                        config.read(config_file)
                    
                    if 'CREDENTIALS' not in config:
                        config['CREDENTIALS'] = {}
                    
                    config['CREDENTIALS']['password'] = encrypt_password(password)
                    # Don't clear API key - allow both to exist
                    
                    with open(config_file, 'w') as f:
                        config.write(f)
                    
                    self.load_current_credentials()
                    QMessageBox.information(self, "Success", "Password saved successfully!")
                    
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"Failed to save password: {str(e)}")
            else:
                QMessageBox.warning(self, "Missing Information", "Please enter a password.")
    
    def change_api_key(self):
        """Open dialog to change API key"""
        dialog = QDialog(self)
        dialog.setWindowTitle("Change API Key")
        dialog.setModal(True)
        dialog.resize(400, 150)
        
        layout = QVBoxLayout(dialog)
        
        # API Key input
        api_key_layout = QHBoxLayout()
        api_key_layout.addWidget(QLabel("API Key:"))
        api_key_edit = QLineEdit()
        api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        api_key_layout.addWidget(api_key_edit)
        layout.addLayout(api_key_layout)
        
        # Info label
        info_label = QLabel("Get your API key from: https://imx.to/user/api")
        info_label.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(info_label)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(dialog.accept)
        button_layout.addWidget(save_btn)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(dialog.reject)
        button_layout.addWidget(cancel_btn)
        
        layout.addLayout(button_layout)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            api_key = api_key_edit.text().strip()
            
            if api_key:
                try:
                    config = configparser.ConfigParser()
                    config_file = get_config_path()
                    
                    if os.path.exists(config_file):
                        config.read(config_file)
                    
                    if 'CREDENTIALS' not in config:
                        config['CREDENTIALS'] = {}
                    
                    config['CREDENTIALS']['api_key'] = encrypt_password(api_key)
                    # Don't clear username/password - allow both to exist
                    
                    with open(config_file, 'w') as f:
                        config.write(f)
                    
                    self.load_current_credentials()
                    QMessageBox.information(self, "Success", "API key saved successfully!")
                    
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"Failed to save API key: {str(e)}")
            else:
                QMessageBox.warning(self, "Missing Information", "Please enter your API key.")

    def enable_cookies_setting(self):
        """Enable Firefox cookies usage for login"""
        try:
            config = configparser.ConfigParser()
            config_file = get_config_path()
            if os.path.exists(config_file):
                config.read(config_file)
            if 'CREDENTIALS' not in config:
                config['CREDENTIALS'] = {}
            config['CREDENTIALS']['cookies_enabled'] = 'true'
            with open(config_file, 'w') as f:
                config.write(f)
            self.load_current_credentials()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to enable cookies: {str(e)}")

    def disable_cookies_setting(self):
        """Disable Firefox cookies usage for login"""
        try:
            config = configparser.ConfigParser()
            config_file = get_config_path()
            if os.path.exists(config_file):
                config.read(config_file)
            if 'CREDENTIALS' not in config:
                config['CREDENTIALS'] = {}
            config['CREDENTIALS']['cookies_enabled'] = 'false'
            with open(config_file, 'w') as f:
                config.write(f)
            self.load_current_credentials()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to disable cookies: {str(e)}")

    def remove_username(self):
        """Remove stored username with confirmation"""
        reply = QMessageBox.question(
            self,
            "Remove Username",
            "Without username/password, all galleries will be titled 'untitled gallery'.\n\nRemove the stored username?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            config = configparser.ConfigParser()
            config_file = get_config_path()
            if os.path.exists(config_file):
                config.read(config_file)
            if 'CREDENTIALS' not in config:
                config['CREDENTIALS'] = {}
            config['CREDENTIALS']['username'] = ''
            with open(config_file, 'w') as f:
                config.write(f)
            self.load_current_credentials()
            QMessageBox.information(self, "Removed", "Username removed.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to remove username: {str(e)}")

    def remove_password(self):
        """Remove stored password with confirmation"""
        reply = QMessageBox.question(
            self,
            "Remove Password",
            "Without username/password, all galleries will be titled 'untitled gallery'.\n\nRemove the stored password?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            config = configparser.ConfigParser()
            config_file = get_config_path()
            if os.path.exists(config_file):
                config.read(config_file)
            if 'CREDENTIALS' not in config:
                config['CREDENTIALS'] = {}
            config['CREDENTIALS']['password'] = ''
            with open(config_file, 'w') as f:
                config.write(f)
            self.load_current_credentials()
            QMessageBox.information(self, "Removed", "Password removed.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to remove password: {str(e)}")

    def remove_api_key(self):
        """Remove stored API key with confirmation"""
        reply = QMessageBox.question(
            self,
            "Remove API Key",
            "Without an API key, it is not possible to upload anything.\n\nRemove the stored API key?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            config = configparser.ConfigParser()
            config_file = get_config_path()
            if os.path.exists(config_file):
                config.read(config_file)
            if 'CREDENTIALS' not in config:
                config['CREDENTIALS'] = {}
            config['CREDENTIALS']['api_key'] = ''
            with open(config_file, 'w') as f:
                config.write(f)
            self.load_current_credentials()
            QMessageBox.information(self, "Removed", "API key removed.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to remove API key: {str(e)}")

    def remove_all_credentials(self):
        """Remove username, password, and API key with confirmation"""
        reply = QMessageBox.question(
            self,
            "Remove All Credentials",
            "This will remove your username, password, and API key.\n\n- Without username/password, all galleries will be titled 'untitled gallery'.\n- Without an API key, uploads are not possible.\n\nProceed?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            config = configparser.ConfigParser()
            config_file = get_config_path()
            if os.path.exists(config_file):
                config.read(config_file)
            if 'CREDENTIALS' not in config:
                config['CREDENTIALS'] = {}
            config['CREDENTIALS']['username'] = ''
            config['CREDENTIALS']['password'] = ''
            config['CREDENTIALS']['api_key'] = ''
            with open(config_file, 'w') as f:
                config.write(f)
            self.load_current_credentials()
            QMessageBox.information(self, "Removed", "All credentials removed.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to remove all credentials: {str(e)}")
    

    
    def validate_and_close(self):
        """Close the dialog - no validation required"""
        self.accept()
    
    def save_credentials(self):
        """Save credentials securely - this is now handled by individual change buttons"""
        self.accept()

class BBCodeViewerDialog(QDialog):
    """Dialog for viewing and editing BBCode text files"""
    
    def __init__(self, folder_path, parent=None):
        super().__init__(parent)
        self.folder_path = folder_path
        self.folder_name = os.path.basename(folder_path)
        self.central_path = None
        self.folder_files = []
        
        # Import here to avoid circular imports
        from imxup import get_central_storage_path
        self.central_path = get_central_storage_path()
        
        self.setWindowTitle(f"BBCode Files - {self.folder_name}")
        self.setModal(True)
        self.resize(800, 600)
        
        # Setup UI
        layout = QVBoxLayout(self)
        
        # Info label
        self.info_label = QLabel()
        layout.addWidget(self.info_label)
        
        # Text editor
        self.text_edit = QPlainTextEdit()
        self.text_edit.setFont(QFont("Consolas", 10))
        layout.addWidget(self.text_edit)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.copy_btn = QPushButton("Copy to Clipboard")
        self.copy_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton))
        self.copy_btn.setIconSize(QSize(16, 16))
        if not self.copy_btn.text().startswith(" "):
            self.copy_btn.setText(" " + self.copy_btn.text())
        self.copy_btn.clicked.connect(self.copy_to_clipboard)
        button_layout.addWidget(self.copy_btn)
        
        button_layout.addStretch()
        
        # Standard dialog buttons
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.save_files)
        self.button_box.rejected.connect(self.reject)
        button_layout.addWidget(self.button_box)
        
        layout.addLayout(button_layout)
        
        # Load content
        self.load_content()
    
    def get_file_paths(self):
        """Get the BBCode file paths (central and folder locations)"""
        # Try to get gallery info from the main GUI
        gallery_id = None
        gallery_name = None
        
        # Find the main GUI window to get item info
        widget = self.parent()
        while widget:
            if hasattr(widget, 'queue_manager'):
                item = widget.queue_manager.get_item(self.folder_path)
                if item and item.gallery_id:
                    gallery_id = item.gallery_id
                    gallery_name = item.name
                break
            widget = widget.parent()
        
        # Central location files in standardized naming (fallback to legacy if not found)
        from imxup import build_gallery_filenames
        if gallery_id and gallery_name:
            _, url_filename, bbcode_filename = build_gallery_filenames(gallery_name, gallery_id)
            central_bbcode = os.path.join(self.central_path, bbcode_filename)
            central_url = os.path.join(self.central_path, url_filename)
        else:
            # Fallback to legacy naming detection for read-only purposes
            central_bbcode = os.path.join(self.central_path, f"{self.folder_name}_bbcode.txt")
            central_url = os.path.join(self.central_path, f"{self.folder_name}.url")

        # Folder location files: standardized names under .uploaded (fallback to legacy glob)
        import glob
        uploaded_dir = os.path.join(self.folder_path, ".uploaded")
        if gallery_id and gallery_name:
            _, url_filename, bbcode_filename = build_gallery_filenames(gallery_name, gallery_id)
            folder_bbcode_files = glob.glob(os.path.join(uploaded_dir, bbcode_filename))
            folder_url_files = glob.glob(os.path.join(uploaded_dir, url_filename))
        else:
            folder_bbcode_files = glob.glob(os.path.join(uploaded_dir, f"{self.folder_name}_bbcode.txt"))
            folder_url_files = glob.glob(os.path.join(uploaded_dir, f"{self.folder_name}.url"))
        
        return {
            'central_bbcode': central_bbcode,
            'central_url': central_url,
            'folder_bbcode': folder_bbcode_files[0] if folder_bbcode_files else None,
            'folder_url': folder_url_files[0] if folder_url_files else None
        }
    
    def load_content(self):
        """Load BBCode content from files"""
        file_paths = self.get_file_paths()
        
        # Try to load from central location first, then folder location
        content = ""
        source_file = None
        
        if os.path.exists(file_paths['central_bbcode']):
            with open(file_paths['central_bbcode'], 'r', encoding='utf-8') as f:
                content = f.read()
            source_file = file_paths['central_bbcode']
        elif file_paths['folder_bbcode'] and os.path.exists(file_paths['folder_bbcode']):
            with open(file_paths['folder_bbcode'], 'r', encoding='utf-8') as f:
                content = f.read()
            source_file = file_paths['folder_bbcode']
        
        if source_file:
            self.info_label.setText(f"Loaded from: {source_file}")
            self.text_edit.setPlainText(content)
        else:
            self.info_label.setText("No BBCode files found for this gallery")
            self.text_edit.setPlainText("No BBCode content available")
            self.text_edit.setReadOnly(True)
            self.button_box.button(QDialogButtonBox.StandardButton.Save).setEnabled(False)
    
    def copy_to_clipboard(self):
        """Copy content to clipboard"""
        content = self.text_edit.toPlainText()
        clipboard = QApplication.clipboard()
        clipboard.setText(content)
        
        # Show brief confirmation
        self.copy_btn.setText("Copied!")
        QTimer.singleShot(1000, lambda: self.copy_btn.setText("Copy to Clipboard"))
    
    def save_files(self):
        """Save content to both central and folder locations"""
        content = self.text_edit.toPlainText()
        file_paths = self.get_file_paths()
        
        try:
            # Save to central location
            with open(file_paths['central_bbcode'], 'w', encoding='utf-8') as f:
                f.write(content)
            
            # Save to folder location if it exists
            if file_paths['folder_bbcode']:
                with open(file_paths['folder_bbcode'], 'w', encoding='utf-8') as f:
                    f.write(content)
            
            self.accept()
            
        except Exception as e:
            QMessageBox.warning(self, "Save Error", f"Error saving files: {str(e)}")

class HelpDialog(QDialog):
    """Dialog to display program documentation in tabs"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Help & Documentation")
        self.setModal(True)
        self.resize(800, 600)

        layout = QVBoxLayout(self)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # Candidate documentation files in preferred order
        base_dir = os.path.dirname(os.path.abspath(__file__))
        doc_candidates = [
            ("GUI Guide", os.path.join(base_dir, "GUI_README.md")),
            ("Quick Start (GUI)", os.path.join(base_dir, "QUICK_START_GUI.md")),
            ("README", os.path.join(base_dir, "README.md")),
            ("Troubleshooting Drag & Drop", os.path.join(base_dir, "TROUBLESHOOT_DRAG_DROP.md")),
            ("GUI Improvements", os.path.join(base_dir, "GUI_IMPROVEMENTS.md")),
        ]

        any_docs_loaded = False
        for title, path in doc_candidates:
            if os.path.exists(path):
                any_docs_loaded = True
                editor = QTextEdit()
                editor.setReadOnly(True)
                editor.setFont(QFont("Consolas", 10))
                try:
                    # Prefer Markdown rendering if available
                    editor.setMarkdown(open(path, "r", encoding="utf-8").read())
                except Exception:
                    # Fallback to plain text
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            editor.setPlainText(f.read())
                    except Exception as e:
                        editor.setPlainText(f"Failed to load {path}: {e}")
                self.tabs.addTab(editor, title)

        if not any_docs_loaded:
            info = QTextEdit()
            info.setReadOnly(True)
            info.setPlainText("No documentation files found in the application directory.")
            self.tabs.addTab(info, "Info")

        # Close button
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.rejected.connect(self.reject)
        button_box.accepted.connect(self.accept)
        layout.addWidget(button_box)

class TableProgressWidget(QWidget):
    """Progress bar widget for table cells - properly centered and sized"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)  # Minimal margins
        layout.setSpacing(0)  # No spacing between elements
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p%")
        self.progress_bar.setMinimumHeight(24)  # Taller for better visibility
        self.progress_bar.setMaximumHeight(26)  # Control maximum height
        self.progress_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)  # Center the text
        
        # Style for better text visibility and proper sizing
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #ccc;
                border-radius: 3px;
                text-align: center;
                font-size: 11px;
                font-weight: bold;
                margin: 0px;
                padding: 0px;
            }
            QProgressBar::chunk {
                border-radius: 2px;
            }
        """)
        
        # Make progress bar fill the entire cell
        layout.addWidget(self.progress_bar, 1)  # Stretch factor of 1
        
    def update_progress(self, value: int, status: str = ""):
        self.progress_bar.setValue(value)
        
        # Color code by status with better styling
        if status == "completed":
            self.progress_bar.setStyleSheet("""
                QProgressBar {
                    border: 1px solid #67C58F;
                    border-radius: 3px;
                    text-align: center;
                    font-size: 11px;
                    font-weight: bold;
                }
                QProgressBar::chunk {
                    background-color: #67C58F;
                    border-radius: 2px;
                }
            """)
        elif status == "failed":
            self.progress_bar.setStyleSheet("""
                QProgressBar {
                    border: 1px solid #e74c3c;
                    border-radius: 3px;
                    text-align: center;
                    font-size: 12px;
                    font-weight: bold;
                }
                QProgressBar::chunk {
                    background-color: #e74c3c;
                    border-radius: 2px;
                }
            """)
        elif status == "uploading":
            self.progress_bar.setStyleSheet("""
                QProgressBar {
                    border: 1px solid #48a2de;
                    border-radius: 3px;
                    text-align: center;
                    font-size: 12px;
                    font-weight: bold;
                }
                QProgressBar::chunk {
                    background-color: #48a2de;
                    border-radius: 2px;
                }
            """)
        else:
            self.progress_bar.setStyleSheet("""
                QProgressBar {
                    border: 1px solid #ccc;
                    border-radius: 3px;
                    text-align: center;
                    font-size: 12px;
                    font-weight: bold;
                }
                QProgressBar::chunk {
                    background-color: #f0f0f0;
                    border-radius: 2px;
                }
            """)

class SingleInstanceServer(QThread):
    """Server for single instance communication"""
    
    folder_received = pyqtSignal(str)
    
    def __init__(self, port=COMMUNICATION_PORT):
        super().__init__()
        self.port = port
        self.running = True
        
    def run(self):
        try:
            server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_socket.bind(('localhost', self.port))
            server_socket.listen(1)
            server_socket.settimeout(1.0)  # Timeout for checking self.running
            
            while self.running:
                try:
                    client_socket, _ = server_socket.accept()
                    data = client_socket.recv(1024).decode('utf-8')
                    if data:
                        self.folder_received.emit(data)
                    client_socket.close()
                except socket.timeout:
                    continue
                except Exception as e:
                    if self.running:  # Only log if we're supposed to be running
                        print(f"Server error: {e}")
                        
            server_socket.close()
        except Exception as e:
            print(f"Failed to start server: {e}")
    
    def stop(self):
        self.running = False
        self.wait()

class ImxUploadGUI(QMainWindow):
    """Main GUI application"""
    
    def __init__(self):
        super().__init__()
        # Set main window icon
        try:
            icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "imxup.ico")
            if os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))
        except Exception:
            pass
        self.queue_manager = QueueManager()
        self.worker = None
        self.table_progress_widgets = {}
        self.settings = QSettings("ImxUploader", "ImxUploadGUI")
        
        # Enable drag and drop on main window
        self.setAcceptDrops(True)
        
        # Single instance server
        self.server = SingleInstanceServer()
        self.server.folder_received.connect(self.add_folder_from_command_line)
        self.server.start()
        
        self.setup_ui()
        self.setup_system_tray()
        self.restore_settings()
        
        # Check for stored credentials (only prompt if API key missing)
        self.check_credentials()
        
        # Start worker thread
        self.start_worker()
        
        # Initial display update
        self.update_queue_display()
        
        # Ensure table has focus for keyboard shortcuts
        self.gallery_table.setFocus()
        
        # Update timer
        # Lightweight periodic update only when queue version changes
        self.update_timer = QTimer()
        self._last_queue_version = self.queue_manager.get_version()
        def _tick():
            current = self.queue_manager.get_version()
            if current != self._last_queue_version:
                self._last_queue_version = current
                self.update_queue_display()
            self.update_progress_display()
        self.update_timer.timeout.connect(_tick)
        self.update_timer.start(500)  # 2Hz tick
        
    def setup_ui(self):
        try:
            from imxup import __version__
            self.setWindowTitle(f"IMX.to Gallery Uploader v{__version__}")
        except Exception:
            self.setWindowTitle("IMX.to Gallery Uploader")
        self.setMinimumSize(800, 600)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main layout - vertical to stack queue and progress
        main_layout = QVBoxLayout(central_widget)
        # Default margins/spacing (revert to previous look)
        
        # Top section with queue and settings
        top_layout = QHBoxLayout()
        
        
        # Left panel - Queue and controls (wider now)
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        
        
        # Queue section
        queue_group = QGroupBox("Upload Queue")
        queue_layout = QVBoxLayout(queue_group)
        
        
        # Drag-and-drop is handled at the window level; no dedicated drop label
        
        # Add folder button
        add_folder_btn = QPushButton("Browse for Folders...")
        if not add_folder_btn.text().startswith(" "):
            add_folder_btn.setText(" " + add_folder_btn.text())
        add_folder_btn.clicked.connect(self.browse_for_folders)
        queue_layout.addWidget(add_folder_btn)
        
        # Gallery table
        self.gallery_table = GalleryTableWidget()
        self.gallery_table.setMinimumHeight(400)  # Taller table
        queue_layout.addWidget(self.gallery_table, 1)  # Give it stretch priority
        
        # Add keyboard shortcut hint
        shortcut_hint = QLabel("💡 Tips: Press Delete key to remove selected items / drag and drop to add folders")
        shortcut_hint.setStyleSheet("color: #666; font-size: 11px; font-style: italic;")
        shortcut_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        queue_layout.addWidget(shortcut_hint)
        
        # Queue controls
        controls_layout = QHBoxLayout()
        
        self.start_all_btn = QPushButton("Start All")
        if not self.start_all_btn.text().startswith(" "):
            self.start_all_btn.setText(" " + self.start_all_btn.text())
        self.start_all_btn.clicked.connect(self.start_all_uploads)
        self.start_all_btn.setMinimumHeight(34)
        #self.start_all_btn.setStyleSheet("""
        #    QPushButton {
        #        background-color: #bee6cf;
        #        border: 1px solid #5f7367;
        #        border-radius: 3px;

        #    }
        #    QPushButton:hover {
        #        background-color: #abcfba;
        #        border: 1px solid #5f7367;
                
        #    }
        #    QPushButton:pressed {
        #        background-color: #6495ed;
        #        border: 1px solid #1e2c47;
        #    }
        #""")
        controls_layout.addWidget(self.start_all_btn)
        
        self.pause_all_btn = QPushButton("Pause All")
        if not self.pause_all_btn.text().startswith(" "):
            self.pause_all_btn.setText(" " + self.pause_all_btn.text())
        self.pause_all_btn.clicked.connect(self.pause_all_uploads)
        self.pause_all_btn.setMinimumHeight(34)
        controls_layout.addWidget(self.pause_all_btn)
        
        self.clear_completed_btn = QPushButton("Clear Completed")
        if not self.clear_completed_btn.text().startswith(" "):
            self.clear_completed_btn.setText(" " + self.clear_completed_btn.text())
        self.clear_completed_btn.clicked.connect(self.clear_completed)
        self.clear_completed_btn.setMinimumHeight(34)
        controls_layout.addWidget(self.clear_completed_btn)
        

        
        queue_layout.addLayout(controls_layout)
        left_layout.addWidget(queue_group)
        
        top_layout.addWidget(left_panel, 3)  # 3/4 width for queue (more space)
        
        # Right panel - Settings and logs
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        
        
        # Settings section
        self.settings_group = QGroupBox("Settings")
        settings_layout = QGridLayout(self.settings_group)
        
        settings_layout.setVerticalSpacing(3)
        settings_layout.setHorizontalSpacing(10)
        
        # Load defaults
        defaults = load_user_defaults()
        
        # Thumbnail size
        settings_layout.addWidget(QLabel("Thumbnail Size:"), 0, 0)
        self.thumbnail_size_combo = QComboBox()
        self.thumbnail_size_combo.addItems([
            "100x100", "180x180", "250x250", "300x300", "150x150"
        ])
        self.thumbnail_size_combo.setCurrentIndex(defaults.get('thumbnail_size', 3) - 1)
        self.thumbnail_size_combo.currentIndexChanged.connect(self.on_setting_changed)
        settings_layout.addWidget(self.thumbnail_size_combo, 0, 1)
        
        # Thumbnail format
        settings_layout.addWidget(QLabel("Thumbnail Format:"), 1, 0)
        self.thumbnail_format_combo = QComboBox()
        self.thumbnail_format_combo.addItems([
            "Fixed width", "Proportional", "Square", "Fixed height"
        ])
        self.thumbnail_format_combo.setCurrentIndex(defaults.get('thumbnail_format', 2) - 1)
        self.thumbnail_format_combo.currentIndexChanged.connect(self.on_setting_changed)
        settings_layout.addWidget(self.thumbnail_format_combo, 1, 1)
        
        # Max retries
        settings_layout.addWidget(QLabel("Max Retries:"), 2, 0)
        self.max_retries_spin = QSpinBox()
        self.max_retries_spin.setRange(1, 10)
        self.max_retries_spin.setValue(defaults.get('max_retries', 3))
        self.max_retries_spin.valueChanged.connect(self.on_setting_changed)
        settings_layout.addWidget(self.max_retries_spin, 2, 1)
        
        # Parallel upload batch size
        settings_layout.addWidget(QLabel("Concurrent Uploads:"), 3, 0)
        self.batch_size_spin = QSpinBox()
        self.batch_size_spin.setRange(1, 20)
        self.batch_size_spin.setValue(defaults.get('parallel_batch_size', 4))
        self.batch_size_spin.setToolTip("Number of images to upload simultaneously. Higher values = faster uploads but more server load.")
        self.batch_size_spin.valueChanged.connect(self.on_setting_changed)
        settings_layout.addWidget(self.batch_size_spin, 3, 1)
        
        # Template selection
        settings_layout.addWidget(QLabel("BBCode Template:"), 4, 0)
        self.template_combo = QComboBox()
        self.template_combo.setToolTip("Template to use for generating bbcode files")
        # Load available templates
        from imxup import load_templates
        templates = load_templates()
        for template_name in templates.keys():
            self.template_combo.addItem(template_name)
        # Set the saved template
        saved_template = defaults.get('template_name', 'default')
        template_index = self.template_combo.findText(saved_template)
        if template_index >= 0:
            self.template_combo.setCurrentIndex(template_index)
        self.template_combo.currentIndexChanged.connect(self.on_setting_changed)
        settings_layout.addWidget(self.template_combo, 4, 1)

        # Watch template directory for changes and refresh dropdown automatically
        try:
            from PyQt6.QtCore import QFileSystemWatcher
            from imxup import get_template_path
            self._template_watcher = QFileSystemWatcher([get_template_path()])
            self._template_watcher.directoryChanged.connect(self._on_templates_directory_changed)
        except Exception:
            # If watcher isn't available, we simply won't auto-refresh
            self._template_watcher = None
        
        # Public gallery
        self.public_gallery_check = QCheckBox("Make galleries public")
        self.public_gallery_check.setChecked(defaults.get('public_gallery', 1) == 1)
        self.public_gallery_check.toggled.connect(self.on_setting_changed)
        settings_layout.addWidget(self.public_gallery_check, 5, 0)
        
        # Confirm delete
        self.confirm_delete_check = QCheckBox("Confirm before deleting items")
        self.confirm_delete_check.setChecked(defaults.get('confirm_delete', True))  # Load from defaults
        self.confirm_delete_check.toggled.connect(self.on_setting_changed)
        settings_layout.addWidget(self.confirm_delete_check, 5, 1)

        # Auto-rename unnamed galleries after successful login
        self.auto_rename_check = QCheckBox("Auto-rename galleries after login")
        # Default enabled
        self.auto_rename_check.setChecked(defaults.get('auto_rename', True))
        self.auto_rename_check.toggled.connect(self.on_setting_changed)
        settings_layout.addWidget(self.auto_rename_check, 6, 0, 1, 2)

        # Artifact storage location options
        self.store_in_uploaded_check = QCheckBox("Save artifacts in .uploaded folder")
        self.store_in_uploaded_check.setChecked(defaults.get('store_in_uploaded', True))
        self.store_in_uploaded_check.toggled.connect(self.on_setting_changed)
        settings_layout.addWidget(self.store_in_uploaded_check, 7, 0)

        self.store_in_central_check = QCheckBox("Save artifacts in central store")
        self.store_in_central_check.setChecked(defaults.get('store_in_central', True))
        self.store_in_central_check.toggled.connect(self.on_setting_changed)
        settings_layout.addWidget(self.store_in_central_check, 7, 1)
        

        
        # Save settings button
        self.save_settings_btn = QPushButton("Save Settings")
        if not self.save_settings_btn.text().startswith(" "):
            self.save_settings_btn.setText(" " + self.save_settings_btn.text())
        self.save_settings_btn.clicked.connect(self.save_upload_settings)
        self.save_settings_btn.setMinimumHeight(30)
        self.save_settings_btn.setMaximumHeight(34)
        self.save_settings_btn.setEnabled(False)  # Initially disabled
        #self.save_settings_btn.setStyleSheet("""
        #    QPushButton {
        #        background-color: #ffe4b2;
        #        color: black;
        #        border: 1px solid #e67e22;
        #        border-radius: 3px;
        #    }
        #    QPushButton:hover {
        #        background-color: #ffdb99;
        #    }
        #    QPushButton:pressed {
        #        background-color: #ffdb99;
        #    }
        #    QPushButton:disabled {
        #        background-color: #f0f0f0;
        #        color: #999999;
        #        border-color: #bdc3c7;
        #        font-weight: normal;
        #        opacity: 0.2;
        #    }
        #""")
        settings_layout.addWidget(self.save_settings_btn, 8, 0, 1, 2)
        
        # Manage templates button
        self.manage_templates_btn = QPushButton("Manage BBCode Templates")
        if not self.manage_templates_btn.text().startswith(" "):
            self.manage_templates_btn.setText(" " + self.manage_templates_btn.text())
        self.manage_templates_btn.clicked.connect(self.manage_templates)
        self.manage_templates_btn.setMinimumHeight(30)
        self.manage_templates_btn.setMaximumHeight(34)
        #self.manage_templates_btn.setStyleSheet("""
        #    QPushButton {
        #        xbackground-color: #27ae60;
        #        color: black;
        #        border: 1px solid #229954;
        #        border-radius: 3px;
        #    }
        #    QPushButton:hover {
        #        xbackground-color: #229954;
        #    }
        #    QPushButton:pressed {
        #        xbackground-color: #1e8449;
        #    }
        #""")
        settings_layout.addWidget(self.manage_templates_btn, 9, 0, 1, 2)
        
        # Manage credentials button
        self.manage_credentials_btn = QPushButton("Manage Credentials")
        if not self.manage_credentials_btn.text().startswith(" "):
            self.manage_credentials_btn.setText(" " + self.manage_credentials_btn.text())
        self.manage_credentials_btn.clicked.connect(self.manage_credentials)
        self.manage_credentials_btn.setMinimumHeight(30)
        self.manage_credentials_btn.setMaximumHeight(34)
        #self.manage_credentials_btn.setStyleSheet("""
        #    QPushButton {
        #        xbackground-color: #3498db;
        #        color: black;
        #        border: 1px solid #2980b9;
        #        border-radius: 3px;
        #    }
        #    QPushButton:hover {
        #        xbackground-color: #2980b9;
        #    }
        #    QPushButton:pressed {
        #        xbackground-color: #21618c;
        #    }
        #""")
        settings_layout.addWidget(self.manage_credentials_btn, 10, 0, 1, 2)
        
        right_layout.addWidget(self.settings_group)
        

        
        # Log section
        log_group = QGroupBox("Log")
        log_layout = QVBoxLayout(log_group)
        
        
        self.log_text = QTextEdit()
        self.log_text.setMinimumHeight(300)  # Much taller
        self.log_text.setFont(QFont("Consolas", 9))  # Slightly larger font
        # Keep a long history in the GUI log
        try:
            self.log_text.document().setMaximumBlockCount(200000)  # ~200k lines
        except Exception:
            pass
        log_layout.addWidget(self.log_text)
        
        right_layout.addWidget(log_group, 1)  # Give it stretch priority
        
        top_layout.addWidget(right_panel, 1)  # 1/4 width for settings/log (less space)
        
        main_layout.addLayout(top_layout)
        
        # Bottom section - Overall progress (left) and Help (right)
        bottom_layout = QHBoxLayout()
        

        # Overall progress group (left)
        progress_group = QGroupBox("Overall Progress")
        progress_layout = QVBoxLayout(progress_group)
        

        overall_layout = QHBoxLayout()
        overall_layout.addWidget(QLabel("Overall:"))
        self.overall_progress = QProgressBar()
        self.overall_progress.setMinimum(0)
        self.overall_progress.setMaximum(100)
        self.overall_progress.setTextVisible(True)
        self.overall_progress.setFormat("Ready")
        self.overall_progress.setMinimumHeight(24)
        self.overall_progress.setMaximumHeight(26)
        self.overall_progress.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Style to match other progress meters
        self.overall_progress.setStyleSheet("""
            QProgressBar {
                border: 1px solid #ccc;
                border-radius: 3px;
                text-align: center;
                font-size: 11px;
                font-weight: bold;
                margin: 0px;
                padding: 0px;
            }
            QProgressBar::chunk {
                border-radius: 2px;
            }
        """)
        overall_layout.addWidget(self.overall_progress)
        progress_layout.addLayout(overall_layout)

        # Statistics
        self.stats_label = QLabel("Ready to upload galleries")
        self.stats_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stats_label.setStyleSheet("color: #666; font-style: italic;")
        progress_layout.addWidget(self.stats_label)

        # Keep bottom short like the original progress box
        progress_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        progress_group.setMaximumHeight(100)
        bottom_layout.addWidget(progress_group, 3)  # Match left/right ratio (3:1)

        # Help group (right) -> repurpose as Stats details
        stats_group = QGroupBox("Stats")
        stats_layout = QGridLayout(stats_group)
        
        # Detailed stats labels
        self.stats_unnamed_label = QLabel("Unnamed galleries: 0")
        self.stats_total_galleries_label = QLabel("Total galleries uploaded: 0")
        self.stats_total_images_label = QLabel("Total images uploaded: 0")
        self.stats_total_size_label = QLabel("Total size uploaded: 0.0 MB")
        self.stats_current_speed_label = QLabel("Current speed: 0.0 KB/s")
        self.stats_fastest_speed_label = QLabel("Fastest speed: 0.0 KB/s")
        for lbl in (
            self.stats_unnamed_label,
            self.stats_total_galleries_label,
            self.stats_total_images_label,
            self.stats_total_size_label,
            self.stats_current_speed_label,
            self.stats_fastest_speed_label,
        ):
            lbl.setStyleSheet("color: #333;")
        # Arrange in two columns, three rows
        stats_layout.addWidget(self.stats_unnamed_label, 0, 0)
        stats_layout.addWidget(self.stats_total_galleries_label, 1, 0)
        stats_layout.addWidget(self.stats_total_images_label, 2, 0)
        stats_layout.addWidget(self.stats_total_size_label, 0, 1)
        stats_layout.addWidget(self.stats_current_speed_label, 1, 1)
        stats_layout.addWidget(self.stats_fastest_speed_label, 2, 1)
        
        # Keep bottom short like the original progress box
        stats_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        stats_group.setMaximumHeight(120)

        bottom_layout.addWidget(stats_group, 1)

        main_layout.addLayout(bottom_layout)
        # Ensure the top section takes remaining space and bottom stays compact
        try:
            main_layout.setStretch(0, 1)  # top_layout
            main_layout.setStretch(1, 0)  # bottom_layout
        except Exception:
            pass
        
    def check_credentials(self):
        """Prompt to set credentials only if API key is not set."""
        if not api_key_is_set():
            dialog = CredentialSetupDialog(self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.add_log_message(f"{timestamp()} Credentials saved securely")
            else:
                self.add_log_message(f"{timestamp()} Credential setup cancelled")
        else:
            self.add_log_message(f"{timestamp()} API key found; skipping credential setup dialog")
    
    def manage_templates(self):
        """Open template management dialog"""
        # Get current template from combo box
        current_template = self.template_combo.currentText()
        dialog = TemplateManagerDialog(self, current_template)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Refresh template combo box and keep selection when possible
            self.refresh_template_combo(preferred=current_template)

    def _on_templates_directory_changed(self, _path):
        """Handle updates to the templates directory by refreshing the combo box."""
        self.refresh_template_combo()

    def refresh_template_combo(self, preferred: str | None = None):
        """Reload templates into the dropdown, preserving selection when possible."""
        from imxup import load_templates
        templates = load_templates()
        current = preferred if preferred is not None else self.template_combo.currentText()
        self.template_combo.blockSignals(True)
        self.template_combo.clear()
        for template_name in templates.keys():
            self.template_combo.addItem(template_name)
        # Restore selection if available, else default
        index = self.template_combo.findText(current)
        if index < 0:
            index = self.template_combo.findText('default')
        if index >= 0:
            self.template_combo.setCurrentIndex(index)
        self.template_combo.blockSignals(False)
    
    def manage_credentials(self):
        """Open credential management dialog"""
        dialog = CredentialSetupDialog(self)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.add_log_message(f"{timestamp()} Credentials updated successfully")
        else:
            self.add_log_message(f"{timestamp()} Credential management cancelled")

    def open_help_dialog(self):
        """Open the help/documentation dialog"""
        dialog = HelpDialog(self)
        dialog.exec()

    def setup_system_tray(self):
        """Setup system tray icon"""
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon = QSystemTrayIcon(self)
            
            # Create a simple icon
            pixmap = QPixmap(16, 16)
            pixmap.fill(Qt.GlobalColor.blue)
            self.tray_icon.setIcon(QIcon(pixmap))
            
            # Tray menu
            tray_menu = QMenu()
            
            show_action = tray_menu.addAction("Show")
            show_action.triggered.connect(self.show)
            
            quit_action = tray_menu.addAction("Quit")
            quit_action.triggered.connect(self.close)
            
            self.tray_icon.setContextMenu(tray_menu)
            self.tray_icon.activated.connect(self.tray_icon_activated)
            self.tray_icon.show()
    
    def tray_icon_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show()
            self.raise_()
            self.activateWindow()
    
    def start_worker(self):
        """Start the upload worker thread"""
        if self.worker is None or not self.worker.isRunning():
            self.worker = UploadWorker(self.queue_manager)
            self.worker.progress_updated.connect(self.on_progress_updated)
            self.worker.gallery_started.connect(self.on_gallery_started)
            self.worker.gallery_completed.connect(self.on_gallery_completed)
            self.worker.gallery_failed.connect(self.on_gallery_failed)
            self.worker.gallery_exists.connect(self.on_gallery_exists)
            self.worker.log_message.connect(self.add_log_message)
            self.worker.bandwidth_updated.connect(self.on_bandwidth_updated)
            self.worker.start()
            self.add_log_message(f"{timestamp()} Worker started")
            # Propagate auto-rename preference to worker
            try:
                self.worker.auto_rename_enabled = self.auto_rename_check.isChecked()
            except Exception:
                pass

    def on_bandwidth_updated(self, kbps: float):
        """Receive current aggregate bandwidth from worker (KB/s)."""
        self._current_transfer_kbps = kbps
    
    def browse_for_folders(self):
        """Open folder browser to select galleries"""
        folder_path = QFileDialog.getExistingDirectory(
            self,
            "Select Gallery Folder",
            "",
            QFileDialog.Option.ShowDirsOnly
        )
        
        if folder_path:
            self.add_folders([folder_path])
    
    def add_folders(self, folder_paths: List[str]):
        """Add folders to the upload queue"""
        added_count = 0
        # Get selected template
        template_name = self.template_combo.currentText()
        
        for path in folder_paths:
            result = self.queue_manager.add_item(path, template_name=template_name)
            if result == True:
                added_count += 1
                self.add_log_message(f"{timestamp()} Added to queue: {os.path.basename(path)}")
            elif result == "duplicate":
                # Handle duplicate gallery
                gallery_name = sanitize_gallery_name(os.path.basename(path))
                from imxup import check_if_gallery_exists
                existing_files = check_if_gallery_exists(gallery_name)
                
                message = f"Gallery '{gallery_name}' already exists with {len(existing_files)} files.\n\nContinue with upload anyway?"
                reply = QMessageBox.question(
                    self,
                    "Gallery Already Exists",
                    message,
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No
                )
                
                if reply == QMessageBox.StandardButton.Yes:
                    # Force add the item
                    self.queue_manager._force_add_item(path, gallery_name, template_name)
                    added_count += 1
                    self.add_log_message(f"{timestamp()} Added to queue (user confirmed): {os.path.basename(path)}")
                else:
                    self.add_log_message(f"{timestamp()} Skipped: {os.path.basename(path)} (user cancelled)")
            else:
                self.add_log_message(f"{timestamp()} Failed to add: {os.path.basename(path)} (no images or already in queue)")
        
        if added_count > 0:
            self.update_queue_display()
    
    def add_folder_from_command_line(self, folder_path: str):
        """Add folder from command line (single instance)"""
        self.add_folders([folder_path])
        
        # Show window if hidden
        if not self.isVisible():
            self.show()
            self.raise_()
            self.activateWindow()
    
    def update_queue_display(self):
        """Update the gallery table display"""
        items = self.queue_manager.get_all_items()
        print(f"DEBUG: update_queue_display called with {len(items)} items")
        print(f"DEBUG: Item paths: {[item.path for item in items]}")
        
        # Preserve scroll position
        scrollbar = self.gallery_table.verticalScrollBar()
        scroll_position = scrollbar.value()
        
        # Preserve current selection by path (column 1 holds path in UserRole)
        selected_paths = set()
        try:
            selected_rows = {it.row() for it in self.gallery_table.selectedItems()}
            for row in selected_rows:
                name_item = self.gallery_table.item(row, 1)
                if name_item:
                    path = name_item.data(Qt.ItemDataRole.UserRole)
                    if path:
                        selected_paths.add(path)
        except Exception:
            pass
        
        # Clear the table first
        self.gallery_table.clearContents()
        self.gallery_table.setRowCount(len(items))
        print(f"DEBUG: Table cleared and set to {len(items)} rows")
        
        # Populate the table with current items
        
        # Populate the table with current items
        for row, item in enumerate(items):
            
            # Order number
            order_item = QTableWidgetItem(str(item.insertion_order))
            order_item.setFlags(order_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            order_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            order_item.setFont(QFont("Arial", 9))
            self.gallery_table.setItem(row, 0, order_item)
            
            # Gallery name
            name_item = QTableWidgetItem(item.name or "Unknown")
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            name_item.setData(Qt.ItemDataRole.UserRole, item.path)
            self.gallery_table.setItem(row, 1, name_item)
            
            # Uploaded count
            uploaded_text = f"{item.uploaded_images}/{item.total_images}" if item.total_images > 0 else "0/?"
            uploaded_item = QTableWidgetItem(uploaded_text)
            uploaded_item.setFlags(uploaded_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            uploaded_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.gallery_table.setItem(row, 2, uploaded_item)
            
            # Progress bar - always create fresh widget to avoid sorting issues
            progress_widget = TableProgressWidget()
            progress_widget.update_progress(item.progress, item.status)
            self.gallery_table.setCellWidget(row, 3, progress_widget)
            
            # Status - force "Uploading" if item is actually uploading
            # Status text mapping
            if item.status == "uploading":
                status_text = "Uploading"
            elif item.status == "scanning":
                status_text = "Scanning"
            elif item.status == "incomplete":
                status_text = "Incomplete"
            else:
                status_text = item.status.title()
            status_item = QTableWidgetItem(status_text)
            status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            
            # Color code status - use stronger color application
            if item.status == "completed":
                status_item.setBackground(QColor(46, 204, 113))  # Green
                status_item.setForeground(QColor(0, 0, 0))  # Black text
                status_item.setData(Qt.ItemDataRole.BackgroundRole, QColor(46, 204, 113))
                status_item.setData(Qt.ItemDataRole.ForegroundRole, QColor(0, 0, 0))
            elif item.status == "failed":
                status_item.setBackground(QColor(231, 76, 60))  # Red
                status_item.setForeground(QColor(255, 255, 255))  # White text
                status_item.setData(Qt.ItemDataRole.BackgroundRole, QColor(231, 76, 60))
                status_item.setData(Qt.ItemDataRole.ForegroundRole, QColor(255, 255, 255))
            elif item.status == "uploading":
                status_item.setBackground(QColor(52, 152, 219))  # Blue
                status_item.setForeground(QColor(0, 0, 0))  # Black text
                status_item.setData(Qt.ItemDataRole.BackgroundRole, QColor(52, 152, 219))
                status_item.setData(Qt.ItemDataRole.ForegroundRole, QColor(0, 0, 0))
            elif item.status == "paused":
                status_item.setBackground(QColor(241, 196, 15))  # Yellow
                status_item.setForeground(QColor(0, 0, 0))  # Black text
                status_item.setData(Qt.ItemDataRole.BackgroundRole, QColor(241, 196, 15))
                status_item.setData(Qt.ItemDataRole.ForegroundRole, QColor(0, 0, 0))
            elif item.status == "incomplete":
                status_item.setBackground(QColor(241, 196, 15))  # Yellow (same as paused)
                status_item.setForeground(QColor(0, 0, 0))
                status_item.setData(Qt.ItemDataRole.BackgroundRole, QColor(241, 196, 15))
                status_item.setData(Qt.ItemDataRole.ForegroundRole, QColor(0, 0, 0))
            elif item.status == "queued":
                status_item.setBackground(QColor(189, 195, 199))  # Light gray
                status_item.setForeground(QColor(0, 0, 0))  # Black text
                status_item.setData(Qt.ItemDataRole.BackgroundRole, QColor(189, 195, 199))
                status_item.setData(Qt.ItemDataRole.ForegroundRole, QColor(0, 0, 0))
            elif item.status == "scanning":
                status_item.setBackground(QColor(200, 200, 200))  # Neutral gray
                status_item.setForeground(QColor(0, 0, 0))
                status_item.setData(Qt.ItemDataRole.BackgroundRole, QColor(200, 200, 200))
                status_item.setData(Qt.ItemDataRole.ForegroundRole, QColor(0, 0, 0))
            elif item.status == "ready":
                # Default styling for ready items
                pass
            
            self.gallery_table.setItem(row, 4, status_item)
            
            # Added time
            added_text = ""
            if item.added_time:
                added_dt = datetime.fromtimestamp(item.added_time)
                added_text = added_dt.strftime("%Y-%m-%d %H:%M:%S")
            added_item = QTableWidgetItem(added_text)
            added_item.setFlags(added_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            added_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            added_item.setFont(QFont("Arial", 8))  # Smaller font
            self.gallery_table.setItem(row, 5, added_item)
            
            # Finished time
            finished_text = ""
            if item.finished_time:
                finished_dt = datetime.fromtimestamp(item.finished_time)
                finished_text = finished_dt.strftime("%Y-%m-%d %H:%M:%S")
            finished_item = QTableWidgetItem(finished_text)
            finished_item.setFlags(finished_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            finished_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            finished_item.setFont(QFont("Arial", 8))  # Smaller font
            self.gallery_table.setItem(row, 6, finished_item)
            
            # Action buttons - always create fresh widget to avoid sorting issues
            action_widget = ActionButtonWidget()
            # Connect button signals with proper closure capture
            # Disable Start while scanning
            action_widget.start_btn.setEnabled(item.status != "scanning")
            action_widget.start_btn.clicked.connect(lambda checked, path=item.path: self.start_single_item(path))
            action_widget.stop_btn.clicked.connect(lambda checked, path=item.path: self.stop_single_item(path))
            action_widget.view_btn.clicked.connect(lambda checked, path=item.path: self.view_bbcode_files(path))
            action_widget.cancel_btn.clicked.connect(lambda checked, path=item.path: self.cancel_single_item(path))
            action_widget.update_buttons(item.status)
            self.gallery_table.setCellWidget(row, 7, action_widget)
        
        # Restore selection
        if selected_paths:
            try:
                for row in range(self.gallery_table.rowCount()):
                    name_item = self.gallery_table.item(row, 1)
                    if name_item and name_item.data(Qt.ItemDataRole.UserRole) in selected_paths:
                        self.gallery_table.selectRow(row)
            except Exception:
                pass
        
        # Restore scroll position
        scrollbar = self.gallery_table.verticalScrollBar()
        scrollbar.setValue(scroll_position)
        
        # Enable/disable top-level controls based on item statuses
        try:
            has_ready = any(item.status == "ready" for item in items)
            has_queued = any(item.status == "queued" for item in items)
            has_uploading = any(item.status == "uploading" for item in items)
            # Consider 'incomplete' as resumable
            has_resumable = any(item.status == "incomplete" for item in items)
            self.start_all_btn.setEnabled(has_ready or has_resumable)
            self.pause_all_btn.setEnabled(has_queued)
            # Disable settings when any items are queued or uploading
            try:
                self.settings_group.setEnabled(not (has_queued or has_uploading))
            except Exception:
                pass
        except Exception:
            # Controls may not be initialized yet during early calls
            pass
    
    def update_progress_display(self):
        """Update overall progress and statistics"""
        items = self.queue_manager.get_all_items()
        
        if not items:
            self.overall_progress.setValue(0)
            self.overall_progress.setFormat("Ready")
            # Blue for active/ready
            self.overall_progress.setStyleSheet(
                """
                QProgressBar {
                    border: 1px solid #48a2de;
                    border-radius: 3px;
                    text-align: center;
                    font-size: 11px;
                    font-weight: bold;
                }
                QProgressBar::chunk {
                    background-color: #48a2de;
                    border-radius: 2px;
                }
                """
            )
            self.stats_label.setText("Ready to upload galleries")
            return
        
        # Calculate overall progress (account for resumed items' previously uploaded files)
        total_images = sum(item.total_images for item in items if item.total_images > 0)
        uploaded_images = 0
        for item in items:
            if item.total_images > 0:
                base_uploaded = item.uploaded_images
                if hasattr(item, 'uploaded_files') and item.uploaded_files:
                    base_uploaded = max(base_uploaded, len(item.uploaded_files))
                uploaded_images += base_uploaded
        
        if total_images > 0:
            overall_percent = int((uploaded_images / total_images) * 100)
            self.overall_progress.setValue(overall_percent)
            self.overall_progress.setFormat(f"{overall_percent}% ({uploaded_images}/{total_images})")
            # Blue while in progress, green when 100%
            if overall_percent >= 100:
                self.overall_progress.setStyleSheet(
                    """
                    QProgressBar {
                        border: 1px solid #67C58F;
                        border-radius: 3px;
                        text-align: center;
                        font-size: 11px;
                        font-weight: bold;
                    }
                    QProgressBar::chunk {
                        background-color: #67C58F;
                        border-radius: 2px;
                    }
                    """
                )
            else:
                self.overall_progress.setStyleSheet(
                    """
                    QProgressBar {
                        border: 1px solid #48a2de;
                        border-radius: 3px;
                        text-align: center;
                        font-size: 11px;
                        font-weight: bold;
                    }
                    QProgressBar::chunk {
                        background-color: #48a2de;
                        border-radius: 2px;
                    }
                    """
                )
        else:
            self.overall_progress.setValue(0)
            self.overall_progress.setFormat("Preparing...")
            # Blue while preparing
            self.overall_progress.setStyleSheet(
                """
                QProgressBar {
                    border: 1px solid #48a2de;
                    border-radius: 3px;
                    text-align: center;
                    font-size: 11px;
                    font-weight: bold;
                }
                QProgressBar::chunk {
                    background-color: #48a2de;
                    border-radius: 2px;
                }
                """
            )
        # Update Stats box values
        try:
            from imxup import get_unnamed_galleries
            unnamed_count = len(get_unnamed_galleries())
        except Exception:
            unnamed_count = 0
        self.stats_unnamed_label.setText(f"Unnamed galleries: {unnamed_count}")
        # Totals persisted in QSettings
        settings = QSettings("ImxUploader", "Stats")
        total_galleries = settings.value("total_galleries", 0, type=int)
        total_images_acc = settings.value("total_images", 0, type=int)
        total_size_acc = settings.value("total_size_bytes", 0, type=int)
        fastest_kbps = settings.value("fastest_kbps", 0.0, type=float)
        self.stats_total_galleries_label.setText(f"Total galleries uploaded: {total_galleries}")
        self.stats_total_images_label.setText(f"Total images uploaded: {total_images_acc}")
        self.stats_total_size_label.setText(f"Total size uploaded: {total_size_acc / (1024*1024):.1f} MB")
        # Current transfer speed: 0 if no active uploads; else latest emitted from worker
        any_uploading = any(it.status == "uploading" for it in items)
        if not any_uploading:
            self._current_transfer_kbps = 0.0
        current_kbps = float(getattr(self, "_current_transfer_kbps", 0.0))
        self.stats_current_speed_label.setText(f"Current speed: {current_kbps:.1f} KB/s")
        self.stats_fastest_speed_label.setText(f"Fastest speed: {fastest_kbps:.1f} KB/s")
        # Update statistics
        completed = sum(1 for item in items if item.status == "completed")
        uploading = sum(1 for item in items if item.status == "uploading")
        failed = sum(1 for item in items if item.status == "failed")
        incomplete = sum(1 for item in items if item.status == "incomplete")
        queued = len(items) - completed - uploading - failed
        
        stats_parts = []
        if queued > 0:
            stats_parts.append(f"{queued} queued")
        if uploading > 0:
            stats_parts.append(f"{uploading} uploading")
        if completed > 0:
            stats_parts.append(f"{completed} completed")
        if failed > 0:
            stats_parts.append(f"{failed} failed")
        if incomplete > 0:
            stats_parts.append(f"{incomplete} incomplete")
        
        if stats_parts:
            self.stats_label.setText(" • ".join(stats_parts))
        else:
            self.stats_label.setText("No galleries in queue")
    
    def on_gallery_started(self, path: str, total_images: int):
        """Handle gallery start"""
        with QMutexLocker(self.queue_manager.mutex):
            if path in self.queue_manager.items:
                item = self.queue_manager.items[path]
                item.total_images = total_images
                item.uploaded_images = 0
                # Ensure status is set to uploading
                # Respect pre-set statuses like 'incomplete' from a soft stop request
                if item.status not in ["paused", "incomplete"]:
                    item.status = "uploading"
        
        # Update only the specific row status instead of full table refresh
        # Also ensure settings are disabled while uploads are active
        try:
            self.settings_group.setEnabled(False)
        except Exception:
            pass

        for row in range(self.gallery_table.rowCount()):
            name_item = self.gallery_table.item(row, 1)
            if name_item and name_item.data(Qt.ItemDataRole.UserRole) == path:
                # Update uploaded count
                uploaded_text = f"0/{total_images}"
                uploaded_item = QTableWidgetItem(uploaded_text)
                uploaded_item.setFlags(uploaded_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                uploaded_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.gallery_table.setItem(row, 2, uploaded_item)
                
                # Update status cell based on current item status
                current_status = item.status
                if current_status == "incomplete":
                    status_item = QTableWidgetItem("Incomplete")
                    status_item.setBackground(QColor(241, 196, 15))
                    status_item.setForeground(QColor(0, 0, 0))
                    status_item.setData(Qt.ItemDataRole.BackgroundRole, QColor(241, 196, 15))
                    status_item.setData(Qt.ItemDataRole.ForegroundRole, QColor(0, 0, 0))
                else:
                    status_item = QTableWidgetItem("Uploading")
                    status_item.setBackground(QColor(52, 152, 219))
                    status_item.setForeground(QColor(0, 0, 0))
                    status_item.setData(Qt.ItemDataRole.BackgroundRole, QColor(52, 152, 219))
                    status_item.setData(Qt.ItemDataRole.ForegroundRole, QColor(0, 0, 0))
                status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.gallery_table.setItem(row, 4, status_item)
                
                # Update action buttons
                action_widget = self.gallery_table.cellWidget(row, 7)
                if isinstance(action_widget, ActionButtonWidget):
                    action_widget.update_buttons(current_status)
                break
    
    def on_progress_updated(self, path: str, completed: int, total: int, progress_percent: int, current_image: str):
        """Handle progress updates from worker"""
        with QMutexLocker(self.queue_manager.mutex):
            if path in self.queue_manager.items:
                item = self.queue_manager.items[path]
                item.uploaded_images = completed
                item.total_images = total
                item.progress = progress_percent
                item.current_image = current_image
                
                # Ensure status is uploading during progress updates
                if item.status not in ["completed", "failed", "incomplete"]:
                    item.status = "uploading"
                
                # Find and update the correct row in the table
                for row in range(self.gallery_table.rowCount()):
                    name_item = self.gallery_table.item(row, 1)  # Gallery name is now column 1
                    if name_item and name_item.data(Qt.ItemDataRole.UserRole) == path:
                        # Update uploaded count
                        uploaded_text = f"{completed}/{total}"
                        uploaded_item = QTableWidgetItem(uploaded_text)
                        uploaded_item.setFlags(uploaded_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        uploaded_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                        self.gallery_table.setItem(row, 2, uploaded_item)  # Uploaded is now column 2
                        
                        # Update progress bar
                        progress_widget = self.gallery_table.cellWidget(row, 3)  # Progress is now column 3
                        if isinstance(progress_widget, TableProgressWidget):
                            progress_widget.update_progress(progress_percent, item.status)
                        else:
                            # Create new progress widget if missing
                            progress_widget = TableProgressWidget()
                            progress_widget.update_progress(progress_percent, item.status)
                            self.gallery_table.setCellWidget(row, 3, progress_widget)  # Progress is now column 3
                        
                        # Show appropriate status if incomplete requested; otherwise show Uploading
                        if progress_percent > 0 and progress_percent < 100:
                            if item.status == "incomplete":
                                status_item = QTableWidgetItem("Incomplete")
                                status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                                status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                                status_item.setBackground(QColor(241, 196, 15))
                                status_item.setForeground(QColor(0, 0, 0))
                                status_item.setData(Qt.ItemDataRole.BackgroundRole, QColor(241, 196, 15))
                                status_item.setData(Qt.ItemDataRole.ForegroundRole, QColor(0, 0, 0))
                            else:
                                status_item = QTableWidgetItem("Uploading")
                                status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                                status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                                status_item.setBackground(QColor(52, 152, 219))  # Blue background
                                status_item.setForeground(QColor(0, 0, 0))  # Black text
                                status_item.setData(Qt.ItemDataRole.BackgroundRole, QColor(52, 152, 219))
                                status_item.setData(Qt.ItemDataRole.ForegroundRole, QColor(0, 0, 0))
                            self.gallery_table.setItem(row, 4, status_item)
                        
                # Bandwidth updates are now emitted from worker; GUI handler will update labels

                # Update status if it's completed (100%)
                if progress_percent >= 100:
                    # Set finished timestamp if not already set
                    if not item.finished_time:
                        item.finished_time = time.time()
                    
                    # If there were failures (based on item.uploaded_images vs total), show Failed; else Completed
                    final_status_text = "Completed"
                    row_failed = False
                    if item.total_images and item.uploaded_images is not None and item.uploaded_images < item.total_images:
                        final_status_text = "Failed"
                        row_failed = True
                    item.status = "completed" if not row_failed else "failed"
                    status_item = QTableWidgetItem(final_status_text)
                    status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    if row_failed:
                        status_item.setBackground(QColor(231, 76, 60))
                        status_item.setForeground(QColor(255, 255, 255))
                    else:
                        status_item.setBackground(QColor(46, 204, 113))  # Green background
                        status_item.setForeground(QColor(0, 0, 0))  # Black text
                    self.gallery_table.setItem(row, 4, status_item)  # Status is now column 4
                    
                    # Update the finished time column
                    finished_dt = datetime.fromtimestamp(item.finished_time)
                    finished_text = finished_dt.strftime("%Y-%m-%d %H:%M:%S")
                    finished_item = QTableWidgetItem(finished_text)
                    finished_item.setFlags(finished_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    finished_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    finished_item.setFont(QFont("Arial", 8))  # Smaller font
                    self.gallery_table.setItem(row, 6, finished_item)
                    return
    
    def on_gallery_completed(self, path: str, results: dict):
        """Handle gallery completion"""
        with QMutexLocker(self.queue_manager.mutex):
            if path in self.queue_manager.items:
                item = self.queue_manager.items[path]
                item.status = "completed"
                item.progress = 100
                item.gallery_url = results.get('gallery_url', '')
                item.gallery_id = results.get('gallery_id', '')
                item.finished_time = time.time()  # Set completion timestamp
        
        # Create gallery files with new naming format
        gallery_id = results.get('gallery_id', '')
        gallery_name = results.get('gallery_name', os.path.basename(path))
        
        if gallery_id and gallery_name:
            # Import template functions
            from imxup import generate_bbcode_from_template
            
        # Prepare template data (include successes; failed shown separately)
        all_images_bbcode = ""
        for image_data in results.get('images', []):
            all_images_bbcode += image_data.get('bbcode', '') + "  "
        failed_details = results.get('failed_details', [])
        failed_summary = ""
        if failed_details:
            failed_summary_lines = [f"[b]Failed ({len(failed_details)}):[/b]"]
            for fname, reason in failed_details[:20]:
                failed_summary_lines.append(f"- {fname}: {reason}")
            if len(failed_details) > 20:
                failed_summary_lines.append(f"... and {len(failed_details) - 20} more")
            failed_summary = "\n" + "\n".join(failed_summary_lines)

                    # Calculate statistics (always, not only when failures exist)
        queue_item = self.queue_manager.get_item(path)
        total_size = results.get('total_size', 0) or (queue_item.total_size if queue_item and getattr(queue_item, 'total_size', 0) else 0)
        folder_size = f"{(total_size) / (1024*1024):.1f} MB"
        avg_width = (queue_item.avg_width if queue_item and getattr(queue_item, 'avg_width', 0) else 0) or results.get('avg_width', 0)
        avg_height = (queue_item.avg_height if queue_item and getattr(queue_item, 'avg_height', 0) else 0) or results.get('avg_height', 0)

        # Get most common extension from uploaded images
        extensions = []
        for image_data in results.get('images', []):
            if 'image_url' in image_data:
                url = image_data['image_url']
                if '.' in url:
                    ext = url.split('.')[-1].upper()
                    if ext in ['JPG', 'PNG', 'GIF', 'BMP', 'WEBP']:
                        extensions.append(ext)
        extension = max(set(extensions), key=extensions.count) if extensions else "JPG"

        if gallery_id and gallery_name:
            # Prepare template data
            template_data = {
                'folder_name': gallery_name,
                'width': int(avg_width),
                'height': int(avg_height),
                'longest': int(max(avg_width, avg_height)),
                'extension': extension,
                'picture_count': len(results.get('images', [])),
                'folder_size': folder_size,
                'gallery_link': f"https://imx.to/g/{gallery_id}",
                'all_images': (all_images_bbcode.strip() + ("\n\n" + failed_summary if failed_summary else "")).strip()
            }
            
            # Get template name from the item
            item = self.queue_manager.get_item(path)
            template_name = item.template_name if item else "default"
            
            # Generate bbcode using the item's template
            bbcode_content = generate_bbcode_from_template(template_name, template_data)
            
            # Save artifacts as JSON and BBCode according to settings
            from imxup import (
                build_gallery_filenames,
                get_central_storage_path,
                load_user_defaults,
                __version__ as IMXUP_VERSION,
            )
            # Determine storage preferences
            defaults = load_user_defaults()
            store_in_uploaded = defaults.get('store_in_uploaded', True)
            store_in_central = defaults.get('store_in_central', True)

            # Ensure .uploaded exists if needed
            if store_in_uploaded:
                uploaded_subdir = os.path.join(path, ".uploaded")
                os.makedirs(uploaded_subdir, exist_ok=True)

            # Build filenames
            _, json_filename, bbcode_filename = build_gallery_filenames(gallery_name, gallery_id)

            # Compose JSON using results we have in GUI context
            images_payload = []
            for image_data in results.get('images', []):
                orig_name = image_data.get('original_filename', '') or ''
                # Ensure lowercase extension for filename
                try:
                    if '.' in orig_name:
                        base, ext = os.path.splitext(orig_name)
                        filename_norm = base + ext.lower()
                    else:
                        filename_norm = orig_name
                except Exception:
                    filename_norm = orig_name
                img_url = image_data.get('image_url') or ''
                # Derive thumb_url as /u/t/{id}.ext when possible
                thumb_url = image_data.get('thumb_url')
                try:
                    if not thumb_url and img_url:
                        # Extract id from /i/{id}
                        # Accept forms like https://imx.to/i/68uhhf
                        parts = img_url.split('/i/')
                        if len(parts) == 2 and parts[1]:
                            image_id = parts[1].split('/')[0]
                            # Choose extension from filename if available; fallback to jpg
                            _, ext = os.path.splitext(filename_norm)
                            ext = (ext.lower() or '.jpg') if ext else '.jpg'
                            thumb_url = f"https://imx.to/u/t/{image_id}{ext}"
                except Exception:
                    pass
                images_payload.append({
                    'filename': filename_norm,
                    'uploaded_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'image_url': img_url,
                    'thumb_url': thumb_url,
                    'bbcode': image_data.get('bbcode'),
                })

            failures_payload = [
                {
                    'filename': fname,
                    'failed_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'reason': reason
                }
                for fname, reason in results.get('failed_details', [])
            ]

            json_payload = {
                'meta': {
                    'gallery_name': gallery_name,
                    'gallery_id': gallery_id,
                    'gallery_url': f"https://imx.to/g/{gallery_id}",
                    'status': 'completed',
                    'started_at': datetime.fromtimestamp(self.queue_manager.items[path].start_time).strftime('%Y-%m-%d %H:%M:%S') if path in self.queue_manager.items and self.queue_manager.items[path].start_time else None,
                    'finished_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'uploader_version': IMXUP_VERSION,
                },
                'settings': {
                    'thumbnail_size': self.thumbnail_size_combo.currentIndex() + 1,
                    'thumbnail_format': self.thumbnail_format_combo.currentIndex() + 1,
                    'public_gallery': 1 if self.public_gallery_check.isChecked() else 0,
                    'template_name': template_name,
                    'parallel_batch_size': self.batch_size_spin.value()
                },
                'stats': {
                    'total_images': len(results.get('images', [])) + len(results.get('failed_details', [])),
                    'successful_count': results.get('successful_count', len(results.get('images', []))),
                    'failed_count': results.get('failed_count', len(results.get('failed_details', []))),
                    'upload_time': results.get('upload_time', 0),
                    'total_size': results.get('total_size', 0),
                    'uploaded_size': results.get('uploaded_size', 0),
                    'avg_width': results.get('avg_width', 0),
                    'avg_height': results.get('avg_height', 0),
                    'transfer_speed_mb_s': (results.get('transfer_speed', 0) / (1024*1024)) if results.get('transfer_speed', 0) else 0
                },
                'images': images_payload,
                'failures': failures_payload,
                'bbcode_full': bbcode_content
            }

            # Write to .uploaded
            if store_in_uploaded:
                with open(os.path.join(uploaded_subdir, bbcode_filename), 'w', encoding='utf-8') as f:
                    f.write(bbcode_content)
                with open(os.path.join(uploaded_subdir, json_filename), 'w', encoding='utf-8') as jf:
                    json.dump(json_payload, jf, ensure_ascii=False, indent=2)

            # Write to central store
            if store_in_central:
                central_path = get_central_storage_path()
                os.makedirs(central_path, exist_ok=True)
                with open(os.path.join(central_path, bbcode_filename), 'w', encoding='utf-8') as f:
                    f.write(bbcode_content)
                with open(os.path.join(central_path, json_filename), 'w', encoding='utf-8') as jf:
                    json.dump(json_payload, jf, ensure_ascii=False, indent=2)
            
            if store_in_central:
                self.add_log_message(f"{timestamp()} Saved gallery files to central location: {central_path}")
        
        # Re-enable settings if no remaining active (queued/uploading) items
        try:
            remaining = self.queue_manager.get_all_items()
            any_active = any(i.status in ("queued", "uploading") for i in remaining)
            self.settings_group.setEnabled(not any_active)
        except Exception:
            pass

                    # Update display when status changes
        self.update_queue_display()
        
        gallery_url = results.get('gallery_url', '')
        total_size = results.get('total_size', 0)
        upload_time = results.get('upload_time', 0)
        successful_count = results.get('successful_count', 0)
        
        self.add_log_message(f"{timestamp()} ✓ Completed: {gallery_name} ({gallery_id})")
        self.add_log_message(f"{timestamp()} Uploaded {successful_count} images ({total_size / (1024*1024):.1f} MB) in {upload_time:.1f}s")
        # Update cumulative stats
        try:
            settings = QSettings("ImxUploader", "Stats")
            total_galleries = settings.value("total_galleries", 0, type=int) + 1
            total_images_acc = settings.value("total_images", 0, type=int) + successful_count
            total_size_acc = settings.value("total_size_bytes", 0, type=int) + int(results.get('uploaded_size', 0) or 0)
            # Current and fastest speeds in KB/s
            transfer_speed = float(results.get('transfer_speed', 0) or 0)
            current_kbps = transfer_speed / 1024.0
            fastest_kbps = settings.value("fastest_kbps", 0.0, type=float)
            if current_kbps > fastest_kbps:
                fastest_kbps = current_kbps
            settings.setValue("total_galleries", total_galleries)
            settings.setValue("total_images", total_images_acc)
            settings.setValue("total_size_bytes", total_size_acc)
            settings.setValue("fastest_kbps", fastest_kbps)
            settings.sync()
            # Update current speed immediately for Stats box
            self._current_transfer_kbps = current_kbps
            # Refresh stats labels
            self.update_progress_display()
        except Exception:
            pass
    
    def on_gallery_exists(self, gallery_name: str, existing_files: list):
        """Handle existing gallery detection"""
        message = f"Gallery '{gallery_name}' already exists with {len(existing_files)} files.\n\nContinue with upload anyway?"
        reply = QMessageBox.question(
            self,
            "Gallery Already Exists",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            # Cancel the upload
            self.add_log_message(f"{timestamp()} Upload cancelled by user due to existing gallery")
            # TODO: Implement proper cancellation mechanism
        else:
            self.add_log_message(f"{timestamp()} User chose to continue with existing gallery")

    def on_gallery_failed(self, path: str, error_message: str):
        """Handle gallery failure"""
        with QMutexLocker(self.queue_manager.mutex):
            if path in self.queue_manager.items:
                item = self.queue_manager.items[path]
                item.status = "failed"
                item.error_message = error_message
        
        # Re-enable settings if no remaining active (queued/uploading) items
        try:
            remaining = self.queue_manager.get_all_items()
            any_active = any(i.status in ("queued", "uploading") for i in remaining)
            self.settings_group.setEnabled(not any_active)
        except Exception:
            pass

        # Update display when status changes
        self.update_queue_display()
        
        gallery_name = os.path.basename(path)
        self.add_log_message(f"{timestamp()} ✗ Failed: {gallery_name} - {error_message}")
    
    def add_log_message(self, message: str):
        """Add message to log"""
        self.log_text.append(message)
        # Retain long history; no aggressive trimming
    
    def start_single_item(self, path: str):
        """Start a single item"""
        if self.queue_manager.start_item(path):
            self.add_log_message(f"{timestamp()} Started: {os.path.basename(path)}")
            self.update_queue_display()
        else:
            self.add_log_message(f"{timestamp()} Failed to start: {os.path.basename(path)}")
    
    def pause_single_item(self, path: str):
        """Pause a single item"""
        if self.queue_manager.pause_item(path):
            self.add_log_message(f"{timestamp()} Paused: {os.path.basename(path)}")
            self.update_queue_display()
        else:
            self.add_log_message(f"{timestamp()} Failed to pause: {os.path.basename(path)}")
    
    def stop_single_item(self, path: str):
        """Mark current uploading item to finish in-flight transfers, then become incomplete."""
        if self.worker and self.worker.current_item and self.worker.current_item.path == path:
            self.worker.request_soft_stop_current()
            # Optimistically reflect intent in UI without persisting as failed later
            self.queue_manager.update_item_status(path, "incomplete")
            self.update_queue_display()
            self.add_log_message(f"{timestamp()} Will stop after current transfers: {os.path.basename(path)}")
        else:
            # If not the actively uploading one, nothing to do
            self.add_log_message(f"{timestamp()} Stop requested but item not currently uploading: {os.path.basename(path)}")
        # Ensure controls reflect latest state promptly
        self.update_queue_display()
    
    def cancel_single_item(self, path: str):
        """Cancel a queued item and put it back to ready state"""
        with QMutexLocker(self.queue_manager.mutex):
            if path in self.queue_manager.items:
                item = self.queue_manager.items[path]
                if item.status == "queued":
                    item.status = "ready"
                    self.add_log_message(f"{timestamp()} Canceled queued item: {os.path.basename(path)}")
        
        self.update_queue_display()
    
    def view_bbcode_files(self, path: str):
        """Open BBCode viewer/editor for completed item"""
        # Check if item is completed
        item = self.queue_manager.get_item(path)
        if not item or item.status != "completed":
            QMessageBox.warning(self, "Not Available", "BBCode files are only available for completed galleries.")
            return
        
        # Open the viewer dialog
        dialog = BBCodeViewerDialog(path, self)
        dialog.exec()
    
    def copy_bbcode_to_clipboard(self, path: str):
        """Copy BBCode content to clipboard for the given item"""
        # Check if item is completed
        item = self.queue_manager.get_item(path)
        if not item or item.status != "completed":
            self.add_log_message(f"{timestamp()} BBCode copy failed: {os.path.basename(path)} is not completed")
            return
        
        folder_name = os.path.basename(path)
        
        # Import here to avoid circular imports  
        from imxup import get_central_storage_path
        central_path = get_central_storage_path()
        
        # Try central location first with standardized naming, fallback to legacy
        from imxup import build_gallery_filenames
        item = self.queue_manager.get_item(path)
        if item and item.gallery_id and (item.name or folder_name):
            _, _, bbcode_filename = build_gallery_filenames(item.name or folder_name, item.gallery_id)
            central_bbcode = os.path.join(central_path, bbcode_filename)
        else:
            # Fallback to old format for existing files
            central_bbcode = os.path.join(central_path, f"{folder_name}_bbcode.txt")
        
        content = ""
        source_file = None
        
        if os.path.exists(central_bbcode):
            with open(central_bbcode, 'r', encoding='utf-8') as f:
                content = f.read()
            source_file = central_bbcode
        else:
            # Try folder location (existing format)
            import glob
            # Prefer standardized .uploaded location, fallback to legacy
            if item and item.gallery_id and (item.name or folder_name):
                _, _, bbcode_filename = build_gallery_filenames(item.name or folder_name, item.gallery_id)
                folder_bbcode_files = glob.glob(os.path.join(path, ".uploaded", bbcode_filename))
            else:
                folder_bbcode_files = glob.glob(os.path.join(path, "gallery_*_bbcode.txt"))
            
            if folder_bbcode_files and os.path.exists(folder_bbcode_files[0]):
                with open(folder_bbcode_files[0], 'r', encoding='utf-8') as f:
                    content = f.read()
                source_file = folder_bbcode_files[0]
        
        if content:
            clipboard = QApplication.clipboard()
            clipboard.setText(content)
            self.add_log_message(f"{timestamp()} Copied BBCode to clipboard from: {source_file}")
        else:
            self.add_log_message(f"{timestamp()} No BBCode file found for: {folder_name}")
    
    def start_all_uploads(self):
        """Start all ready uploads"""
        items = self.queue_manager.get_all_items()
        started_count = 0
        for item in items:
            if item.status in ("ready", "paused", "incomplete"):
                if self.queue_manager.start_item(item.path):
                    started_count += 1
        
        if started_count > 0:
            self.add_log_message(f"{timestamp()} Started {started_count} uploads")
            self.update_queue_display()
        else:
            self.add_log_message(f"{timestamp()} No items to start")
    
    def pause_all_uploads(self):
        """Reset all queued items back to ready (acts like Cancel for queued)"""
        items = self.queue_manager.get_all_items()
        reset_count = 0
        with QMutexLocker(self.queue_manager.mutex):
            for item in items:
                if item.status == "queued" and item.path in self.queue_manager.items:
                    self.queue_manager.items[item.path].status = "ready"
                    reset_count += 1
        
        if reset_count > 0:
            self.add_log_message(f"{timestamp()} Reset {reset_count} queued item(s) to Ready")
            self.update_queue_display()
        else:
            self.add_log_message(f"{timestamp()} No queued items to reset")
    
    def clear_completed(self):
        """Clear completed uploads from queue"""
        removed_count = self.queue_manager.clear_completed()
        if removed_count > 0:
            self.update_queue_display()
            QApplication.processEvents()
            self.queue_manager.save_persistent_queue()
            self.add_log_message(f"{timestamp()} Cleared {removed_count} completed uploads")
        else:
            self.add_log_message(f"{timestamp()} No completed uploads to clear")
    
    def delete_selected_items(self):
        """Delete selected items from the queue"""
        self.add_log_message(f"{timestamp()} Delete method called")
        
        selected_rows = set()
        for item in self.gallery_table.selectedItems():
            selected_rows.add(item.row())
        
        if not selected_rows:
            self.add_log_message(f"{timestamp()} No rows selected")
            return
        
        # Get paths directly from the table cells to handle sorting correctly
        selected_paths = []
        selected_names = []
        
        for row in selected_rows:
            name_item = self.gallery_table.item(row, 1)  # Gallery name is in column 1
            if name_item:
                path = name_item.data(Qt.ItemDataRole.UserRole)
                if path:
                    selected_paths.append(path)
                    selected_names.append(name_item.text())
                else:
                    self.add_log_message(f"{timestamp()} No path data for row {row}")
            else:
                self.add_log_message(f"{timestamp()} No name item for row {row}")
        
        if not selected_paths:
            self.add_log_message(f"{timestamp()} No valid paths found")
            return
        
        # Check if confirmation is needed
        if self.confirm_delete_check.isChecked():
            if len(selected_paths) == 1:
                message = f"Delete '{selected_names[0]}'?"
            else:
                message = f"Delete {len(selected_paths)} selected items?"
            
            reply = QMessageBox.question(
                self,
                "Confirm Delete",
                message,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            
            if reply != QMessageBox.StandardButton.Yes:
                self.add_log_message(f"{timestamp()} User cancelled delete")
                return
        
        # Delete items using the working approach
        removed_count = 0
        for path in selected_paths:
            # Check if item is currently uploading
            item = self.queue_manager.get_item(path)
            if item and item.status == "uploading":
                self.add_log_message(f"{timestamp()} Skipping uploading item: {path}")
                continue
            
            # Remove from memory
            with QMutexLocker(self.queue_manager.mutex):
                if path in self.queue_manager.items:
                    del self.queue_manager.items[path]
                    removed_count += 1
                    self.add_log_message(f"{timestamp()} Deleted: {path}")
                else:
                    self.add_log_message(f"{timestamp()} Item not found: {path}")
        
        if removed_count > 0:
            # Renumber remaining items
            self.queue_manager.renumber_insertion_orders()
            
            # Update display
            self.update_queue_display()
            self.add_log_message(f"{timestamp()} Updated display")
            
            # Force GUI update
            QApplication.processEvents()
            
            # Save persistent storage
            self.queue_manager.save_persistent_queue()
            self.add_log_message(f"{timestamp()} ✓ Deleted {removed_count} items from queue")
        else:
            self.add_log_message(f"{timestamp()} ⚠ No items were deleted (some may be currently uploading)")
    

    
    def restore_settings(self):
        """Restore window settings"""
        geometry = self.settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        
        # Load settings from .ini file
        defaults = load_user_defaults()
        
        # Restore confirm delete setting from .ini file
        confirm_delete = defaults.get('confirm_delete', True)
        if isinstance(confirm_delete, str):
            confirm_delete = confirm_delete.lower() == 'true'
        self.confirm_delete_check.setChecked(confirm_delete)
    
    def save_settings(self):
        """Save window settings"""
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("confirm_delete", self.confirm_delete_check.isChecked())
    
    def on_setting_changed(self):
        """Handle when any setting is changed"""
        self.save_settings_btn.setEnabled(True)
    
    def save_upload_settings(self):
        """Save upload settings to .ini file"""
        try:
            import configparser
            import os
            
            # Get current values
            thumbnail_size = self.thumbnail_size_combo.currentIndex() + 1
            thumbnail_format = self.thumbnail_format_combo.currentIndex() + 1
            max_retries = self.max_retries_spin.value()
            parallel_batch_size = self.batch_size_spin.value()
            template_name = self.template_combo.currentText()
            public_gallery = 1 if self.public_gallery_check.isChecked() else 0
            confirm_delete = self.confirm_delete_check.isChecked()
            auto_rename = self.auto_rename_check.isChecked()
            store_in_uploaded = self.store_in_uploaded_check.isChecked()
            store_in_central = self.store_in_central_check.isChecked()
            
            # Load existing config
            config = configparser.ConfigParser()
            config_file = get_config_path()
            
            if os.path.exists(config_file):
                config.read(config_file)
            
            # Ensure DEFAULTS section exists
            if 'DEFAULTS' not in config:
                config['DEFAULTS'] = {}
            
            # Update settings
            config['DEFAULTS']['thumbnail_size'] = str(thumbnail_size)
            config['DEFAULTS']['thumbnail_format'] = str(thumbnail_format)
            config['DEFAULTS']['max_retries'] = str(max_retries)
            config['DEFAULTS']['parallel_batch_size'] = str(parallel_batch_size)
            config['DEFAULTS']['template_name'] = template_name
            config['DEFAULTS']['public_gallery'] = str(public_gallery)
            config['DEFAULTS']['confirm_delete'] = str(confirm_delete)
            config['DEFAULTS']['auto_rename'] = str(auto_rename)
            config['DEFAULTS']['store_in_uploaded'] = str(store_in_uploaded)
            config['DEFAULTS']['store_in_central'] = str(store_in_central)
            
            # Save to file
            with open(config_file, 'w') as f:
                config.write(f)
            
            # Disable save button
            self.save_settings_btn.setEnabled(False)
            
            # Show success message
            self.add_log_message(f"{timestamp()} Settings saved successfully")
            
        except Exception as e:
            self.add_log_message(f"{timestamp()} Error saving settings: {str(e)}")
            QMessageBox.warning(self, "Error", f"Failed to save settings: {str(e)}")
    
    def dragEnterEvent(self, event):
        """Handle drag enter - SIMPLE VERSION"""
        print("DEBUG: dragEnterEvent called")
        if event.mimeData().hasUrls():
            print("DEBUG: Has URLs")
            event.acceptProposedAction()
        else:
            print("DEBUG: No URLs")
            event.ignore()
    
    def dragMoveEvent(self, event):
        """Handle drag move"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()
    
    def dragLeaveEvent(self, event):
        """Handle drag leave"""
        print("DEBUG: dragLeaveEvent called")
    
    def dropEvent(self, event):
        """Handle drop - EXACTLY like your working test"""
        print("DEBUG: dropEvent called")
        
        if event.mimeData().hasUrls():
            print("DEBUG: Processing URLs")
            urls = event.mimeData().urls()
            paths = []
            for url in urls:
                path = url.toLocalFile()
                print(f"DEBUG: Checking path: {path}")
                if os.path.isdir(path):
                    print(f"DEBUG: Adding folder: {path}")
                    paths.append(path)
            
            if paths:
                print(f"DEBUG: SUCCESS! Found {len(paths)} folders: {', '.join(os.path.basename(p) for p in paths)}")
                self.add_folders(paths)
                event.acceptProposedAction()
            else:
                print("DEBUG: No valid folders in drop")
                event.ignore()
        else:
            print("DEBUG: No URLs in drop")
            event.ignore()

    def closeEvent(self, event):
        """Handle window close"""
        self.save_settings()
        
        # Save queue state
        self.queue_manager.save_persistent_queue()
        
        # Always stop worker and server on close
        if self.worker:
            self.worker.stop()
        self.server.stop()
        
        # Accept the close event to ensure app exits
        event.accept()

def check_single_instance(folder_path=None):
    """Check if another instance is running and send folder if needed"""
    try:
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_socket.connect(('localhost', COMMUNICATION_PORT))
        
        if folder_path:
            client_socket.send(folder_path.encode('utf-8'))
        
        client_socket.close()
        return True  # Another instance is running
    except ConnectionRefusedError:
        return False  # No other instance running

def main():
    """Main function"""
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)  # Exit when window closes
    
    # Handle command line arguments
    folders_to_add = []
    if len(sys.argv) > 1:
        # Accept multiple folder args (Explorer passes all selections to %V)
        for arg in sys.argv[1:]:
            if os.path.isdir(arg):
                folders_to_add.append(arg)
        # If another instance is running, forward the first folder (server is single-path)
        if folders_to_add and check_single_instance(folders_to_add[0]):
            print(f"Added {folders_to_add[0]} to existing instance")
            return
    
    # Create main window
    window = ImxUploadGUI()
    
    # Add folder from command line if provided
    if folders_to_add:
        window.add_folders(folders_to_add)
    
    window.show()
    
    try:
        sys.exit(app.exec())
    except KeyboardInterrupt:
        print("\nExiting gracefully...")
        # Clean shutdown
        if hasattr(window, 'worker') and window.worker:
            window.worker.stop()
        if hasattr(window, 'server') and window.server:
            window.server.stop()
        app.quit()

class PlaceholderHighlighter(QSyntaxHighlighter):
    """Syntax highlighter for BBCode template placeholders"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.placeholder_format = QTextCharFormat()
        self.placeholder_format.setBackground(QColor("#fff3cd"))  # Light yellow background
        self.placeholder_format.setForeground(QColor("#856404"))  # Dark yellow text
        self.placeholder_format.setFontWeight(QFont.Weight.Bold)
        
        # Define all placeholders
        self.placeholders = [
            "#folderName#", "#width#", "#height#", "#longest#", 
            "#extension#", "#pictureCount#", "#folderSize#", 
            "#galleryLink#", "#allImages#"
        ]
    
    def highlightBlock(self, text):
        """Highlight placeholders in the text block"""
        for placeholder in self.placeholders:
            index = 0
            while True:
                index = text.find(placeholder, index)
                if index == -1:
                    break
                self.setFormat(index, len(placeholder), self.placeholder_format)
                index += len(placeholder)


class TemplateManagerDialog(QDialog):
    """Dialog for managing BBCode templates"""
    
    def __init__(self, parent=None, current_template="default"):
        super().__init__(parent)
        self.setWindowTitle("Manage BBCode Templates")
        self.setModal(True)
        self.resize(900, 700)
        
        # Track unsaved changes
        self.unsaved_changes = False
        self.current_template_name = None
        self.initial_template = current_template
        
        # Setup UI
        layout = QVBoxLayout(self)
        
        # Template list section
        list_group = QGroupBox("Templates")
        list_layout = QHBoxLayout(list_group)
        
        # Template list
        self.template_list = QListWidget()
        self.template_list.setMinimumWidth(200)
        self.template_list.itemSelectionChanged.connect(self.on_template_selected)
        self.template_list.setStyleSheet("""
            QListWidget::item:selected {
                background-color: #2980b9;
                color: white;
            }
        """)
        list_layout.addWidget(self.template_list)
        
        # Template actions
        actions_layout = QVBoxLayout()
        
        self.new_btn = QPushButton("New Template")
        if not self.new_btn.text().startswith(" "):
            self.new_btn.setText(" " + self.new_btn.text())
        self.new_btn.clicked.connect(self.create_new_template)
        actions_layout.addWidget(self.new_btn)
        
        self.rename_btn = QPushButton("Rename Template")
        if not self.rename_btn.text().startswith(" "):
            self.rename_btn.setText(" " + self.rename_btn.text())
        self.rename_btn.clicked.connect(self.rename_template)
        self.rename_btn.setEnabled(False)
        actions_layout.addWidget(self.rename_btn)
        
        self.delete_btn = QPushButton("Delete Template")
        if not self.delete_btn.text().startswith(" "):
            self.delete_btn.setText(" " + self.delete_btn.text())
        self.delete_btn.clicked.connect(self.delete_template)
        self.delete_btn.setEnabled(False)
        actions_layout.addWidget(self.delete_btn)
        
        actions_layout.addStretch()
        list_layout.addLayout(actions_layout)
        
        layout.addWidget(list_group)
        
        # Template editor section
        editor_group = QGroupBox("Template Editor")
        editor_layout = QVBoxLayout(editor_group)
        
        # Placeholder buttons
        placeholder_layout = QHBoxLayout()
        placeholder_layout.addWidget(QLabel("Insert Placeholders:"))
        
        placeholders = [
            ("#folderName#", "Gallery Name"),
            ("#width#", "Width"),
            ("#height#", "Height"),
            ("#longest#", "Longest Side"),
            ("#extension#", "Extension"),
            ("#pictureCount#", "Picture Count"),
            ("#folderSize#", "Folder Size"),
            ("#galleryLink#", "Gallery Link"),
            ("#allImages#", "All Images")
        ]
        
        for placeholder, label in placeholders:
            btn = QPushButton(label)
            if not btn.text().startswith(" "):
                btn.setText(" " + btn.text())
            btn.setToolTip(f"Insert {placeholder}")
            btn.clicked.connect(lambda checked, p=placeholder: self.insert_placeholder(p))
            btn.setStyleSheet("""
                QPushButton {
                    padding: 2px 6px;
                    min-width: 80px;
                    max-height: 24px;
                }
            """)
            placeholder_layout.addWidget(btn)
        
        editor_layout.addLayout(placeholder_layout)
        
        # Template content editor with syntax highlighting
        self.template_editor = QPlainTextEdit()
        self.template_editor.setFont(QFont("Consolas", 10))
        self.template_editor.textChanged.connect(self.on_template_changed)
        
        # Add syntax highlighter for placeholders
        self.highlighter = PlaceholderHighlighter(self.template_editor.document())
        
        editor_layout.addWidget(self.template_editor)
        
        layout.addWidget(editor_group)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.save_btn = QPushButton("Save Template")
        if not self.save_btn.text().startswith(" "):
            self.save_btn.setText(" " + self.save_btn.text())
        self.save_btn.clicked.connect(self.save_template)
        self.save_btn.setEnabled(False)
        button_layout.addWidget(self.save_btn)
        
        button_layout.addStretch()
        
        self.close_btn = QPushButton("Close")
        if not self.close_btn.text().startswith(" "):
            self.close_btn.setText(" " + self.close_btn.text())
        self.close_btn.clicked.connect(self.accept)
        button_layout.addWidget(self.close_btn)
        
        layout.addLayout(button_layout)
        
        # Load templates
        self.load_templates()
    
    def load_templates(self):
        """Load and display available templates"""
        from imxup import load_templates
        templates = load_templates()
        
        self.template_list.clear()
        for template_name in templates.keys():
            self.template_list.addItem(template_name)
        
        # Select the current template if available, otherwise select first template
        if self.template_list.count() > 0:
            # Try to find and select the initial template
            found_template = False
            for i in range(self.template_list.count()):
                if self.template_list.item(i).text() == self.initial_template:
                    self.template_list.setCurrentRow(i)
                    found_template = True
                    break
            
            # If initial template not found, select first template
            if not found_template:
                self.template_list.setCurrentRow(0)
    
    def on_template_selected(self):
        """Handle template selection"""
        current_item = self.template_list.currentItem()
        if current_item:
            template_name = current_item.text()
            
            # Check for unsaved changes before switching
            if self.unsaved_changes and self.current_template_name:
                reply = QMessageBox.question(
                    self,
                    "Unsaved Changes",
                    f"You have unsaved changes to template '{self.current_template_name}'. Do you want to save them before switching?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Yes
                )
                
                if reply == QMessageBox.StandardButton.Yes:
                    # Save to the current template (not the one we're switching to)
                    content = self.template_editor.toPlainText()
                    from imxup import get_template_path
                    template_path = get_template_path()
                    template_file = os.path.join(template_path, f".template {self.current_template_name}.txt")
                    
                    try:
                        with open(template_file, 'w', encoding='utf-8') as f:
                            f.write(content)
                        self.save_btn.setEnabled(False)
                        self.unsaved_changes = False
                    except Exception as e:
                        QMessageBox.warning(self, "Error", f"Failed to save template: {str(e)}")
                        # Restore the previous selection if save failed
                        for i in range(self.template_list.count()):
                            if self.template_list.item(i).text() == self.current_template_name:
                                self.template_list.setCurrentRow(i)
                                return
                        return
                elif reply == QMessageBox.StandardButton.Cancel:
                    # Restore the previous selection
                    for i in range(self.template_list.count()):
                        if self.template_list.item(i).text() == self.current_template_name:
                            self.template_list.setCurrentRow(i)
                            return
                    return
            
            self.load_template_content(template_name)
            self.current_template_name = template_name
            self.unsaved_changes = False
            
            # Disable editing for default template
            is_default = template_name == "default"
            self.template_editor.setReadOnly(is_default)
            self.rename_btn.setEnabled(not is_default)
            self.delete_btn.setEnabled(not is_default)
            self.save_btn.setEnabled(False)  # Will be enabled when content changes (if not default)
            
            if is_default:
                self.template_editor.setStyleSheet("""
                    QPlainTextEdit {
                        background-color: #f8f9fa;
                        color: #6c757d;
                    }
                """)
            else:
                self.template_editor.setStyleSheet("")
        else:
            self.template_editor.clear()
            self.current_template_name = None
            self.unsaved_changes = False
            self.rename_btn.setEnabled(False)
            self.delete_btn.setEnabled(False)
    
    def load_template_content(self, template_name):
        """Load template content into editor"""
        from imxup import load_templates
        templates = load_templates()
        
        if template_name in templates:
            self.template_editor.setPlainText(templates[template_name])
        else:
            self.template_editor.clear()
        
        # Reset unsaved changes flag when loading content
        self.unsaved_changes = False
    
    def insert_placeholder(self, placeholder):
        """Insert a placeholder at cursor position"""
        cursor = self.template_editor.textCursor()
        cursor.insertText(placeholder)
        self.template_editor.setFocus()
    
    def on_template_changed(self):
        """Handle template content changes"""
        # Only allow saving if not the default template
        if self.current_template_name != "default":
            self.save_btn.setEnabled(True)
            self.unsaved_changes = True
    
    def create_new_template(self):
        """Create a new template"""
        # Check for unsaved changes before creating new template
        if self.unsaved_changes and self.current_template_name:
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                f"You have unsaved changes to template '{self.current_template_name}'. Do you want to save them before creating a new template?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                self.save_template()
            elif reply == QMessageBox.StandardButton.Cancel:
                return
        
        name, ok = QInputDialog.getText(self, "New Template", "Template name:")
        if ok and name.strip():
            name = name.strip()
            
            # Check if template already exists
            from imxup import load_templates
            templates = load_templates()
            if name in templates:
                QMessageBox.warning(self, "Error", f"Template '{name}' already exists!")
                return
            
            # Add to list and select it
            self.template_list.addItem(name)
            self.template_list.setCurrentItem(self.template_list.item(self.template_list.count() - 1))
            
            # Clear editor for new template
            self.template_editor.clear()
            self.current_template_name = name
            self.unsaved_changes = True
            self.save_btn.setEnabled(True)
    
    def rename_template(self):
        """Rename the current template"""
        current_item = self.template_list.currentItem()
        if not current_item:
            return
        
        old_name = current_item.text()
        if old_name == "default":
            QMessageBox.warning(self, "Error", "Cannot rename the default template!")
            return
        
        new_name, ok = QInputDialog.getText(self, "Rename Template", "New name:", text=old_name)
        if ok and new_name.strip():
            new_name = new_name.strip()
            
            # Check if new name already exists
            from imxup import load_templates
            templates = load_templates()
            if new_name in templates:
                QMessageBox.warning(self, "Error", f"Template '{new_name}' already exists!")
                return
            
            # Rename the template file
            from imxup import get_template_path
            template_path = get_template_path()
            old_file = os.path.join(template_path, f".template {old_name}.txt")
            new_file = os.path.join(template_path, f".template {new_name}.txt")
            
            try:
                os.rename(old_file, new_file)
                current_item.setText(new_name)
                QMessageBox.information(self, "Success", f"Template renamed to '{new_name}'")
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to rename template: {str(e)}")
    
    def delete_template(self):
        """Delete the current template"""
        current_item = self.template_list.currentItem()
        if not current_item:
            return
        
        template_name = current_item.text()
        if template_name == "default":
            QMessageBox.warning(self, "Error", "Cannot delete the default template!")
            return
        
        # Check for unsaved changes before deleting
        if self.unsaved_changes and self.current_template_name == template_name:
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                f"You have unsaved changes to template '{template_name}'. Do you want to save them before deleting?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                self.save_template()
            elif reply == QMessageBox.StandardButton.Cancel:
                return
        
        reply = QMessageBox.question(
            self,
            "Delete Template",
            f"Are you sure you want to delete template '{template_name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            # Delete the template file
            from imxup import get_template_path
            template_path = get_template_path()
            template_file = os.path.join(template_path, f".template {template_name}.txt")
            
            try:
                os.remove(template_file)
                self.template_list.takeItem(self.template_list.currentRow())
                self.template_editor.clear()
                self.save_btn.setEnabled(False)
                self.unsaved_changes = False
                self.current_template_name = None
                QMessageBox.information(self, "Success", f"Template '{template_name}' deleted")
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to delete template: {str(e)}")
    
    def save_template(self):
        """Save the current template"""
        current_item = self.template_list.currentItem()
        if not current_item:
            return
        
        template_name = current_item.text()
        content = self.template_editor.toPlainText()
        
        # Save the template file
        from imxup import get_template_path
        template_path = get_template_path()
        template_file = os.path.join(template_path, f".template {template_name}.txt")
        
        try:
            with open(template_file, 'w', encoding='utf-8') as f:
                f.write(content)
            self.save_btn.setEnabled(False)
            self.unsaved_changes = False
            QMessageBox.information(self, "Success", f"Template '{template_name}' saved")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to save template: {str(e)}")
    
    def closeEvent(self, event):
        """Handle dialog closing with unsaved changes check"""
        if self.unsaved_changes and self.current_template_name:
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                f"You have unsaved changes to template '{self.current_template_name}'. Do you want to save them before closing?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                # Try to save the template
                current_item = self.template_list.currentItem()
                if current_item:
                    template_name = current_item.text()
                    content = self.template_editor.toPlainText()
                    
                    # Save the template file
                    from imxup import get_template_path
                    template_path = get_template_path()
                    template_file = os.path.join(template_path, f".template {template_name}.txt")
                    
                    try:
                        with open(template_file, 'w', encoding='utf-8') as f:
                            f.write(content)
                        self.save_btn.setEnabled(False)
                        self.unsaved_changes = False
                        event.accept()
                    except Exception as e:
                        QMessageBox.warning(self, "Error", f"Failed to save template: {str(e)}")
                        event.ignore()
                else:
                    event.accept()
            elif reply == QMessageBox.StandardButton.No:
                event.accept()
            else:  # Cancel
                event.ignore()
        else:
            event.accept()

if __name__ == "__main__":
    main()