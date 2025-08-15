#!/usr/bin/env python3
"""
PyQt6 GUI for imx.to gallery uploader
Provides drag-and-drop interface with queue management and progress tracking
"""

import sys
import os
import json
import logging
import socket
import threading
import time
import configparser
from pathlib import Path
from datetime import datetime
import sys
import ctypes
from functools import cmp_to_key
import queue
from queue import Queue
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
    QLineEdit, QInputDialog, QSpacerItem, QStyle, QAbstractItemView,
    QProgressDialog
)
from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QTimer, QMimeData, QUrl, 
    QMutex, QMutexLocker, QSettings, QSize, QObject, pyqtSlot
)
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QIcon, QFont, QPixmap, QPainter, QColor, QSyntaxHighlighter, QTextCharFormat, QDesktopServices, QPainterPath, QPen, QFontMetrics, QTextDocument, QActionGroup

# Import the core uploader functionality
from imxup import ImxToUploader, load_user_defaults, timestamp, sanitize_gallery_name, encrypt_password, decrypt_password, rename_all_unnamed_with_session, get_config_path, build_gallery_filenames, get_central_storage_path
from imxup import create_windows_context_menu, remove_windows_context_menu
from imxup_core import UploadEngine
from imxup_storage import QueueStore
from imxup_logging import get_logger

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
    max_width: float = 0.0
    max_height: float = 0.0
    min_width: float = 0.0
    min_height: float = 0.0
    scan_complete: bool = False
    # Failed validation details
    failed_files: list = field(default_factory=list)  # List of (filename, error_message) tuples
    # Resume support
    uploaded_files: set = field(default_factory=set)
    uploaded_images_data: list = field(default_factory=list)
    uploaded_bytes: int = 0
    # Runtime transfer metrics (set by worker thread)
    current_kibps: float = 0.0  # live speed while uploading (KiB/s)
    final_kibps: float = 0.0    # average speed after completion (KiB/s)
    
class GUIImxToUploader(ImxToUploader):
    """Custom uploader for GUI that doesn't block on user input"""
    
    def __init__(self, worker_thread=None):
        super().__init__()
        self.gui_mode = True
        self.worker_thread = worker_thread
    
    def upload_folder(self, folder_path, gallery_name=None, thumbnail_size=3, thumbnail_format=2, max_retries=3, public_gallery=1, parallel_batch_size=4, template_name="default"):
        """GUI-friendly upload delegating to the shared UploadEngine."""
        # Non-blocking signals and resume support
        current_item = self.worker_thread.current_item if self.worker_thread else None
        already_uploaded = set(getattr(current_item, 'uploaded_files', set())) if current_item else set()

        # Emit start with original total
        try:
            image_extensions = ('.jpg', '.jpeg', '.png', '.gif')
            # Match Windows Explorer order for total determination (stable across views)
            def _natural_key(n: str):
                import re as _re
                parts = _re.split(r"(\d+)", n)
                out = []
                for p in parts:
                    out.append(int(p) if p.isdigit() else p.lower())
                return tuple(out)
            def _explorer_sort(names):
                if sys.platform != 'win32':
                    return sorted(names, key=_natural_key)
                try:
                    _cmp = ctypes.windll.shlwapi.StrCmpLogicalW
                    _cmp.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
                    _cmp.restype = ctypes.c_int
                    return sorted(names, key=cmp_to_key(lambda a, b: _cmp(a, b)))
                except Exception:
                    return sorted(names, key=_natural_key)
            names = [
                f for f in os.listdir(folder_path)
                if f.lower().endswith(image_extensions) and os.path.isfile(os.path.join(folder_path, f))
            ]
            original_total = len(_explorer_sort(names))
            if self.worker_thread:
                self.worker_thread.gallery_started.emit(folder_path, original_total)
        except Exception:
            pass

        # Sanitize name like CLI
        if not gallery_name:
            gallery_name = os.path.basename(folder_path)
        original_name = gallery_name
        gallery_name = sanitize_gallery_name(gallery_name)
        if original_name != gallery_name and self.worker_thread:
            self.worker_thread.log_message.emit(f"{timestamp()} Sanitized gallery name: '{original_name}' -> '{gallery_name}'")
        
        engine = UploadEngine(self)

        def on_progress(completed: int, total: int, percent: int, current_image: str):
            if not self.worker_thread:
                return
            self.worker_thread.progress_updated.emit(folder_path, completed, total, percent, current_image)
            # Throttled bandwidth: approximate from uploaded_bytes
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
                # Also update this item's instantaneous rate for the Transfer column
                try:
                    if self.worker_thread.current_item and self.worker_thread.current_item.path == folder_path:
                        elapsed = max(now_ts - float(self.worker_thread.current_item.start_time or now_ts), 0.001)
                        self.worker_thread.current_item.current_kibps = (float(getattr(self.worker_thread.current_item, 'uploaded_bytes', 0) or 0) / elapsed) / 1024.0
                except Exception:
                    pass
                if now_ts - self.worker_thread._stats_last_emit >= 0.5:
                    self.worker_thread._emit_queue_stats()
                    self.worker_thread._stats_last_emit = now_ts
            except Exception:
                pass
                    
        def on_log(message: str):
            if self.worker_thread:
                # Pass through categorized messages from engine
                self.worker_thread.log_message.emit(f"{timestamp()} {message}")

        def should_soft_stop() -> bool:
            if self.worker_thread and self.worker_thread.current_item and self.worker_thread.current_item.path == folder_path:
                return getattr(self.worker_thread, '_soft_stop_requested_for', None) == folder_path
            return False

        def on_image_uploaded(fname: str, data: Dict[str, Any], size_bytes: int):
            if self.worker_thread and self.worker_thread.current_item and self.worker_thread.current_item.path == folder_path:
                try:
                    self.worker_thread.current_item.uploaded_files.add(fname)
                    self.worker_thread.current_item.uploaded_images_data.append((fname, data))
                    self.worker_thread.current_item.uploaded_bytes += int(size_bytes or 0)
                except Exception:
                    pass

        results = engine.run(
            folder_path=folder_path,
            gallery_name=gallery_name,
            thumbnail_size=thumbnail_size,
            thumbnail_format=thumbnail_format,
            max_retries=max_retries,
            public_gallery=public_gallery,
            parallel_batch_size=parallel_batch_size,
            template_name=template_name,
            already_uploaded=already_uploaded,
            on_progress=on_progress,
            on_log=on_log,
            should_soft_stop=should_soft_stop,
            on_image_uploaded=on_image_uploaded,
        )
        # Merge previously uploaded images (from earlier partial runs) with this run's results
        try:
            if self.worker_thread and self.worker_thread.current_item and self.worker_thread.current_item.path == folder_path:
                item = self.worker_thread.current_item
                # Build ordering map based on Explorer order (match engine)
                image_extensions = ('.jpg', '.jpeg', '.png', '.gif')
                def _natural_key(n: str):
                    import re as _re
                    parts = _re.split(r"(\d+)", n)
                    out = []
                    for p in parts:
                        out.append(int(p) if p.isdigit() else p.lower())
                    return tuple(out)
                def _explorer_sort(names):
                    if sys.platform != 'win32':
                        return sorted(names, key=_natural_key)
                    try:
                        _cmp = ctypes.windll.shlwapi.StrCmpLogicalW
                        _cmp.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
                        _cmp.restype = ctypes.c_int
                        return sorted(names, key=cmp_to_key(lambda a, b: _cmp(a, b)))
                    except Exception:
                        return sorted(names, key=_natural_key)
                all_image_files = _explorer_sort([
                    f for f in os.listdir(folder_path)
                    if f.lower().endswith(image_extensions) and os.path.isfile(os.path.join(folder_path, f))
                ])
                file_position = {fname: idx for idx, fname in enumerate(all_image_files)}
                # Collect enriched image data from accumulated uploads across runs
                combined_by_name = {}
                for fname, data in getattr(item, 'uploaded_images_data', []):
                    try:
                        base, ext = os.path.splitext(fname)
                        fname_norm = base + ext.lower()
                    except Exception:
                        fname_norm = fname
                    enriched = dict(data)
                    # Ensure required fields present
                    enriched.setdefault('original_filename', fname_norm)
                    # Best-effort thumb_url (mirrors engine)
                    if not enriched.get('thumb_url') and enriched.get('image_url'):
                        try:
                            parts = enriched.get('image_url').split('/i/')
                            if len(parts) == 2 and parts[1]:
                                img_id = parts[1].split('/')[0]
                                _, ext2 = os.path.splitext(fname_norm)
                                ext_use = (ext2.lower() or '.jpg') if ext2 else '.jpg'
                                enriched['thumb_url'] = f"https://imx.to/u/t/{img_id}{ext_use}"
                        except Exception:
                            pass
                    # Size bytes
                    try:
                        enriched.setdefault('size_bytes', os.path.getsize(os.path.join(folder_path, fname)))
                    except Exception:
                        enriched.setdefault('size_bytes', 0)
                    combined_by_name[fname] = enriched
                # Order by original folder order (Explorer sort)
                ordered = sorted(combined_by_name.items(), key=lambda kv: file_position.get(kv[0], 10**9))
                merged_images = [data for _fname, data in ordered]
                if merged_images:
                    # Replace images in results so downstream BBCode includes all
                    results = dict(results)  # shallow copy
                    results['images'] = merged_images
                    results['successful_count'] = len(merged_images)
                    # Uploaded size across all merged images
                    try:
                        results['uploaded_size'] = sum(int(img.get('size_bytes') or 0) for img in merged_images)
                    except Exception:
                        pass
                    # Ensure total_images reflects full set
                    results['total_images'] = len(all_image_files)
        except Exception:
            pass

        return results

class UploadWorker(QThread):
    """Worker thread for uploading galleries"""
    
    # Signals
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
        super().__init__()
        self.queue_manager = queue_manager
        self.uploader = None
        self.running = True
        self.current_item = None
        self._soft_stop_requested_for = None
        self.auto_rename_enabled = True
        self._bw_last_emit = 0.0
        self._stats_last_emit = 0.0
        # Cross-thread request flags
        self._request_mutex = QMutex()
        self._retry_login_requested = False
        self._retry_credentials_only = False
        
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
            self.log_message.emit(f"{timestamp()} [auth] Logging in...")
            login_success = self.uploader.login()
            # Report the login method used (cookies, credentials, api_key, none)
            try:
                method = getattr(self.uploader, 'last_login_method', None)
                if method == 'cookies':
                    self.log_message.emit(f"{timestamp()} [auth] Authenticated using cookies")
                elif method == 'credentials':
                    self.log_message.emit(f"{timestamp()} [auth] Authenticated using username/password")
                elif method == 'api_key':
                    self.log_message.emit(f"{timestamp()} [auth] Using API key authentication (no web login)")
                elif method == 'none':
                    self.log_message.emit(f"{timestamp()} [auth] No credentials available; proceeding without web login")
            except Exception:
                pass
            if not login_success:
                self.log_message.emit(f"{timestamp()} [auth] Login failed - using API-only mode")
            else:
                # Method-specific post-login messaging and auto-rename gating
                try:
                    method = getattr(self.uploader, 'last_login_method', None)
                except Exception:
                    method = None

                if method in ('cookies', 'credentials'):
                    self.log_message.emit(f"{timestamp()} [auth] Login successful using {method}")
                    # Auto-rename unnamed galleries only when a web session exists
                    try:
                        if self.auto_rename_enabled:
                            renamed = rename_all_unnamed_with_session(self.uploader)
                            if renamed > 0:
                                self.log_message.emit(f"{timestamp()} Auto-renamed {renamed} gallery(ies) after login")
                            else:
                                # Only report none if the unnamed list is actually empty.
                                try:
                                    from imxup import get_unnamed_galleries
                                    if not get_unnamed_galleries():
                                        self.log_message.emit(f"{timestamp()} No unnamed galleries to auto-rename")
                                except Exception:
                                    # Fall back to quiet if we cannot check
                                    pass
                    except Exception as e:
                        self.log_message.emit(f"{timestamp()} Auto-rename error: {e}")
                elif method == 'api_key':
                    # API key present; no web session to rename galleries
                    self.log_message.emit(f"{timestamp()} [auth] API key loaded; web login skipped")
                    try:
                        if self.auto_rename_enabled:
                            self.log_message.emit(f"{timestamp()} [auth] Skipping auto-rename; web session required")
                    except Exception:
                        pass
                else:
                    # Fallback: unknown method but login reported success; do not auto-rename
                    self.log_message.emit(f"{timestamp()} [auth] Login successful")
            
            while self.running:
                # Handle requested login retries from GUI
                try:
                    self._maybe_handle_login_retry()
                except Exception:
                    pass
                # Get next item from queue
                item = self.queue_manager.get_next_item()
                if item is None:
                    # Periodically emit queue stats even when idle
                    try:
                        self._emit_queue_stats()
                    except Exception:
                        pass
                    time.sleep(0.1)
                    continue
                
                # Only process items that are queued to upload
                if item.status == "queued":
                    self.current_item = item
                    self.upload_gallery(item)
                elif item.status == "paused":
                    # Skip paused items
                    try:
                        self._emit_queue_stats()
                    except Exception:
                        pass
                    time.sleep(0.1)
                else:
                    # Put item back in queue if not ready
                    try:
                        self._emit_queue_stats()
                    except Exception:
                        pass
                    time.sleep(0.1)
                
        except Exception as e:
            self.log_message.emit(f"{timestamp()} Worker error: {str(e)}")

    def _maybe_handle_login_retry(self):
        """If a retry has been requested from the GUI, perform it now in the worker thread."""
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
        # Perform the login attempt
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
                # Optionally perform auto-rename of any unnamed galleries
                try:
                    if self.auto_rename_enabled:
                        renamed = rename_all_unnamed_with_session(self.uploader)
                        if renamed > 0:
                            self.log_message.emit(f"{timestamp()} Auto-renamed {renamed} gallery(ies) after login")
                except Exception:
                    pass
            else:
                self.log_message.emit(f"{timestamp()} [auth] Login retry failed")
        except Exception as e:
            self.log_message.emit(f"{timestamp()} [auth] Login retry error: {e}")

    def request_retry_login(self, credentials_only: bool = False) -> None:
        """Request the worker to retry login on its own thread soon.
        Safe to call from the GUI thread.
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
    
    def upload_gallery(self, item: GalleryQueueItem):
        """Upload a single gallery"""
        try:
            # Clear any previous soft-stop request when starting a new item
            self._soft_stop_requested_for = None
            self.log_message.emit(f"{timestamp()} Starting upload: {item.name or os.path.basename(item.path)}")
            
            # Set status to uploading and update display (single source of truth here)
            self.queue_manager.update_item_status(item.path, "uploading")
            item.start_time = time.time()
            
            # Emit signal to update display immediately
            self.gallery_started.emit(item.path, item.total_images or 0)
            # Also emit queue stats since states changed
            try:
                self._emit_queue_stats(force=True)
            except Exception:
                pass
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
            # Defer artifact writing to on_gallery_completed where UI context is available
            
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
                        # Save artifacts in worker thread to avoid blocking UI
                        try:
                            self._save_artifacts_for_result(item, results)
                        except Exception:
                            pass
                        # Notify GUI
                        self.gallery_completed.emit(item.path, results)
                        # Redundant legacy line; replaced by engine summary tagged [uploads]
                        pass
                        try:
                            self._emit_queue_stats(force=True)
                        except Exception:
                            pass
                    else:
                        self.queue_manager.update_item_status(item.path, "completed")
                        # Save artifacts in worker thread to avoid blocking UI
                        try:
                            self._save_artifacts_for_result(item, results)
                        except Exception:
                            pass
                        # Notify GUI
                        self.gallery_completed.emit(item.path, results)
                        # Redundant legacy line; replaced by engine summary tagged [uploads:gallery]
                        pass
                        try:
                            self._emit_queue_stats(force=True)
                        except Exception:
                            pass
            else:
                # If soft stop was requested, do NOT mark failed; mark incomplete instead
                if self._soft_stop_requested_for == item.path:
                    self.queue_manager.update_item_status(item.path, "incomplete")
                    item.status = "incomplete"
                    self.log_message.emit(f"{timestamp()} Marked incomplete: {item.name}")
                    try:
                        self._emit_queue_stats(force=True)
                    except Exception:
                        pass
                else:
                    self.queue_manager.update_item_status(item.path, "failed")
                    self.gallery_failed.emit(item.path, "Upload failed")
                    try:
                        self._emit_queue_stats(force=True)
                    except Exception:
                        pass
                
        except Exception as e:
            error_msg = str(e)
            self.log_message.emit(f"{timestamp()} Error uploading {item.name}: {error_msg}")
            item.error_message = error_msg
            self.queue_manager.update_item_status(item.path, "failed")
            self.gallery_failed.emit(item.path, error_msg)
    
    # Write artifacts from the worker to avoid blocking the GUI thread
    def _save_artifacts_for_result(self, item: GalleryQueueItem, results: dict) -> None:
        try:
            from imxup import save_gallery_artifacts
            written = save_gallery_artifacts(
                folder_path=item.path,
                results=results,
                template_name=item.template_name or "default",
            )
            try:
                parts = []
                if written.get('central'):
                    central_dir = os.path.dirname(list(written['central'].values())[0])
                    parts.append(f"central: {central_dir}")
                if written.get('uploaded'):
                    uploaded_dir = os.path.dirname(list(written['uploaded'].values())[0])
                    parts.append(f"folder: {uploaded_dir}")
                if parts:
                    self.log_message.emit(f"{timestamp()} [fileio] Saved gallery files to {', '.join(parts)}")
            except Exception:
                pass
        except Exception as e:
            self.log_message.emit(f"{timestamp()} Artifact save error: {e}")
    


class QueueManager:
    """Manages the gallery upload queue"""
    
    def __init__(self):
        self.items: Dict[str, GalleryQueueItem] = {}
        self.queue = Queue()
        self.mutex = QMutex()
        self.settings = QSettings("ImxUploader", "QueueManager")
        # SQLite-backed store for durable state
        self.store = QueueStore()
        self._next_order = 0  # Track insertion order
        self._version = 0  # Bumped on any change for cheap UI polling
        
        # Single sequential worker for processing galleries
        self._scan_worker = None
        self._scan_queue = Queue()
        self._scan_worker_running = False
        
        # One-time migration from legacy QSettings into SQLite, then load from DB
        try:
            self.store.migrate_from_qsettings_if_needed(self.settings)
        except Exception:
            pass
        self.load_persistent_queue()
        
        # Start the single scan worker
        self._start_scan_worker()

    def _start_scan_worker(self):
        """Start the single sequential scan worker thread."""
        if not self._scan_worker_running:
            self._scan_worker_running = True
            self._scan_worker = threading.Thread(target=self._sequential_scan_worker, daemon=True)
            self._scan_worker.start()

    def _sequential_scan_worker(self):
        """Single worker that processes galleries sequentially to avoid disk I/O bottlenecks."""
        while self._scan_worker_running:
            try:
                # Get next item to scan (blocking)
                path = self._scan_queue.get(timeout=1.0)
                if path is None:  # Shutdown signal
                    break
                
                # Process this gallery
                self._comprehensive_scan_item(path)
                
                # Mark task as done
                self._scan_queue.task_done()
                
            except queue.Empty:
                # No items to process, continue loop
                continue
            except Exception as e:
                print(f"Scan worker error processing {path}: {e}")
                # Mark task as done even on error to prevent blocking
                try:
                    self._scan_queue.task_done()
                except:
                    pass
                continue

    def _inc_version(self):
        self._version += 1

    def get_version(self) -> int:
        with QMutexLocker(self.mutex):
            return self._version
    
    def save_persistent_queue(self):
        """Save queue state (non-blocking) using SQLite store."""
        queue_data = []
        for item in self.items.values():
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
                    # Intentionally omit heavy per-image lists from GUI thread snapshot
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
                })
        try:
            self.store.bulk_upsert_async(queue_data)
        except Exception:
            pass
    
    def load_persistent_queue(self):
        """Load queue state from SQLite store (post-migration)."""
        try:
            queue_data = self.store.load_all_items()
        except Exception:
            queue_data = []
        if queue_data:
            for item_data in queue_data:
                path = item_data.get('path', '')
                status = item_data.get('status', 'ready')
                # For completed items, don't check path existence
                if status == "completed" or (os.path.exists(path) and os.path.isdir(path)):
                    if status == "completed":
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
                    else:
                        load_status = "ready" if status in ["queued", "uploading"] else status
                        item = GalleryQueueItem(
                            path=path,
                            name=item_data.get('name'),
                            status=load_status,
                            total_images=int(item_data.get('total_images', 0) or 0),
                            template_name=item_data.get('template_name', load_user_defaults().get('template_name', 'default')),
                            insertion_order=item_data.get('insertion_order', self._next_order),
                            added_time=item_data.get('added_time')
                        )
                    # Restore optional fields
                    try:
                        item.total_size = int(item_data.get('total_size', 0) or 0)
                        item.avg_width = float(item_data.get('avg_width', 0.0) or 0.0)
                        item.avg_height = float(item_data.get('avg_height', 0.0) or 0.0)
                        item.max_width = float(item_data.get('max_width', 0.0) or 0.0)
                        item.max_height = float(item_data.get('max_height', 0.0) or 0.0)
                        item.min_width = float(item_data.get('min_width', 0.0) or 0.0)
                        item.min_height = float(item_data.get('min_height', 0.0) or 0.0)
                        item.scan_complete = bool(item_data.get('scan_complete', False))
                        item.uploaded_bytes = int(item_data.get('uploaded_bytes', 0) or 0)
                        item.final_kibps = float(item_data.get('final_kibps', 0.0) or 0.0)
                        # uploaded_files may be a list (from store)
                        uploaded_files = set(item_data.get('uploaded_files', []))
                        if uploaded_files:
                            item.uploaded_files = uploaded_files
                        uploaded_images_data = item_data.get('uploaded_images_data', [])
                        if uploaded_images_data:
                            item.uploaded_images_data = uploaded_images_data
                        failed_files = item_data.get('failed_files', [])
                        if failed_files:
                            item.failed_files = failed_files
                    except Exception:
                        pass
                    self._next_order = max(self._next_order, item.insertion_order + 1)
                    self.items[path] = item
                else:
                    print(f"DEBUG: Skipped item (path doesn't exist): {path}")
        
        
    
    def clear_persistent_queue(self):
        """Clear persistent queue storage (for testing)"""
        self.settings.remove("queue_items")
        self.settings.sync()
        
        
    def add_item(self, path: str, name: Optional[str] = None, template_name: str = "default") -> bool:
        """Add a gallery to the queue"""
        with QMutexLocker(self.mutex):
            if path in self.items:
                return False  # Already exists
                
            # Validate path
            if not os.path.exists(path) or not os.path.isdir(path):
                return False
                
            # Check for images and count them (quick check only)
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
                
            # Create item in scanning state; start comprehensive background scan after releasing lock
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
        # Add to scan queue for sequential processing
        self._scan_queue.put(path)
        return True
    
    def add_multiple_items(self, paths: List[str], template_name: str = "default") -> dict:
        """Add multiple galleries efficiently, avoiding UI blocking."""
        results = {
            'added': 0,
            'duplicates': 0,
            'failed': 0,
            'errors': []
        }
        
        # First pass: validate and create items (fast, non-blocking)
        items_to_scan = []
        with QMutexLocker(self.mutex):
            for path in paths:
                try:
                    if path in self.items:
                        results['duplicates'] += 1
                        continue
                        
                    # Validate path
                    if not os.path.exists(path) or not os.path.isdir(path):
                        results['failed'] += 1
                        results['errors'].append(f"Path not found: {path}")
                        continue
                        
                    # Quick image count check
                    image_extensions = ('.jpg', '.jpeg', '.png', '.gif')
                    image_files = [f for f in os.listdir(path) 
                                 if f.lower().endswith(image_extensions) and 
                                 os.path.isfile(os.path.join(path, f))]
                    
                    if not image_files:
                        results['failed'] += 1
                        results['errors'].append(f"No images found: {path}")
                        continue
                    
                    # Check for existing gallery files
                    gallery_name = sanitize_gallery_name(os.path.basename(path))
                    from imxup import check_if_gallery_exists
                    existing_files = check_if_gallery_exists(gallery_name)
                    
                    if existing_files:
                        results['duplicates'] += 1
                        continue
                    
                    # Create item
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
                    items_to_scan.append(path)
                    results['added'] += 1
                    
                except Exception as e:
                    results['failed'] += 1
                    results['errors'].append(f"Error processing {path}: {str(e)}")
        
        # Save all items at once
        if items_to_scan:
            self.save_persistent_queue()
            self._inc_version()
            
            # Add all items to scan queue for sequential processing
            for path in items_to_scan:
                self._scan_queue.put(path)
        
        return results

    def _comprehensive_scan_item(self, path: str):
        """Comprehensive scan of ALL images to validate them before allowing upload."""
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
            failed_files: List[tuple[str, str]] = []  # (filename, error_message)
            
            # Scan ALL images comprehensively
            for f in files:
                fp = os.path.join(path, f)
                try:
                    file_size = os.path.getsize(fp)
                    total_size += file_size
                    
                    # Validate image with PIL - this is the critical validation step
                    from PIL import Image
                    with Image.open(fp) as img:
                        # Force PIL to actually read the image data to catch corruption
                        img.verify()
                        # Reopen for dimensions since verify() closes the image
                        with Image.open(fp) as img2:
                            w, h = img2.size
                            dims.append((w, h))
                            
                except Exception as e:
                    # Record failed files with specific error messages
                    error_msg = f"Failed to validate {f}: {str(e)}"
                    failed_files.append((f, error_msg))
                    # Continue scanning other files to get complete picture
            
            # If any files failed validation, mark gallery as failed
            if failed_files:
                with QMutexLocker(self.mutex):
                    if path in self.items:
                        item = self.items[path]
                        item.status = "failed"
                        item.error_message = f"Image validation failed: {len(failed_files)}/{len(files)} images invalid"
                        # Store detailed failure information for user reference
                        item.failed_files = failed_files
                        item.total_size = total_size
                        item.scan_complete = True
                self.save_persistent_queue()
                self._inc_version()
                return
            
            # All images validated successfully - calculate statistics
            if dims:
                avg_w = sum(w for w, _ in dims) / len(dims)
                avg_h = sum(h for _, h in dims) / len(dims)
                max_w = max(w for w, _ in dims)
                max_h = max(h for _, h in dims)
                min_w = min(w for w, _ in dims)
                min_h = min(h for _, h in dims)
            else:
                avg_w = avg_h = max_w = max_h = min_w = min_h = 0.0
            
            with QMutexLocker(self.mutex):
                if path in self.items:
                    item = self.items[path]
                    item.total_size = total_size
                    item.avg_width = avg_w
                    item.avg_height = avg_h
                    item.max_width = max_w
                    item.max_height = max_h
                    item.min_width = min_w
                    item.min_height = min_h
                    item.scan_complete = True
                    # Only flip to ready if not already moved forward
                    if item.status == "scanning":
                        item.status = "ready"
            
            # Persist update
            self.save_persistent_queue()
            self._inc_version()
            
        except Exception as e:
            with QMutexLocker(self.mutex):
                if path in self.items:
                    self.items[path].status = "failed"
                    self.items[path].error_message = f"Scan error: {str(e)}"
                    self.items[path].scan_complete = True
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
    
    def get_scan_queue_status(self) -> dict:
        """Get status of the scan queue for monitoring."""
        return {
            'queue_size': self._scan_queue.qsize(),
            'worker_running': self._scan_worker_running,
            'items_pending_scan': sum(1 for item in self.items.values() if item.status == "scanning")
        }
    
    def shutdown(self):
        """Shutdown the scan worker gracefully."""
        self._scan_worker_running = False
        # Send shutdown signal to worker
        try:
            self._scan_queue.put(None, timeout=1.0)
        except:
            pass
        # Wait for worker to finish
        if self._scan_worker and self._scan_worker.is_alive():
            self._scan_worker.join(timeout=2.0)
    
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
            self._renumber_insertion_orders_locked()

    def _renumber_insertion_orders_locked(self):
        """Internal: caller must hold self.mutex. Renumber and persist order."""
        # Sort items by current insertion order to maintain relative order
        sorted_items = sorted(self.items.values(), key=lambda x: x.insertion_order)
        # Renumber starting from 1
        for i, item in enumerate(sorted_items, 1):
            item.insertion_order = i
        # Update the next order counter
        self._next_order = len(self.items) + 1
        # Persist ordering asynchronously
        try:
            ordered_paths = [it.path for it in sorted_items]
            self.store._executor.submit(self.store.update_insertion_orders, ordered_paths)
        except Exception:
            pass
    
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
                self._renumber_insertion_orders_locked()
        # Purge from SQLite in background (by status is simple and safe)
        try:
            self.store._executor.submit(self.store.delete_by_status, ["completed", "failed"])
        except Exception:
            pass
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
        # Purge from SQLite in background
        try:
            self.store._executor.submit(self.store.delete_by_paths, list(paths))
        except Exception:
            pass
        return removed_count

class GalleryTableWidget(QTableWidget):
    """Table widget for gallery queue with resizable columns, sorting, and action buttons"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Setup table
        # Columns: 0 #, 1 gallery name, 2 uploaded, 3 progress, 4 status, 5 added, 6 finished, 7 action,
        #          8 size, 9 transfer, 10 template, 11 title
        self.setColumnCount(12)
        self.setHorizontalHeaderLabels([
            "#", "gallery name", "uploaded", "progress", "status", "added", "finished", "action",
            "size", "transfer", "template", "title"
        ])
        try:
            # Left-align the 'gallery name' header specifically
            hn = self.horizontalHeaderItem(1)
            if hn:
                hn.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        except Exception:
            pass
        
        # Configure columns
        header = self.horizontalHeader()
        header.setStretchLastSection(False)
        try:
            header.setCascadingSectionResizes(True)
        except Exception:
            pass
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)         # Order - fixed
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)   # Gallery Name - user-resizable
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)   # Uploaded - resizable
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)   # Progress - resizable
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)   # Status - resizable
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Interactive)   # Added - resizable
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Interactive)   # Finished - resizable
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.Fixed)         # action - fixed
        header.setSectionResizeMode(8, QHeaderView.ResizeMode.Interactive)   # size - resizable
        header.setSectionResizeMode(9, QHeaderView.ResizeMode.Interactive)   # transfer - resizable
        header.setSectionResizeMode(10, QHeaderView.ResizeMode.Interactive)  # template - resizable
        header.setSectionResizeMode(11, QHeaderView.ResizeMode.Interactive)  # title - resizable
        try:
            # Allow headers to shrink more
            header.setMinimumSectionSize(24)
        except Exception:
            pass
        # Keep widths fixed unless user drags; prevent automatic shuffling
        try:
            header.setSectionsClickable(True)
            header.setHighlightSections(False)
            header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        except Exception:
            pass
        
        # Set initial column widths
        self.setColumnWidth(0, 40)   # Order (narrow)
        self.setColumnWidth(1, 300)  # Gallery Name (wider)
        self.setColumnWidth(2, 100)  # Uploaded (wider)
        self.setColumnWidth(3, 200)  # Progress (slightly narrower)
        self.setColumnWidth(4, 120)  # Status (wider)
        self.setColumnWidth(5, 140)  # Added (wider for YYYY-MM-DD format)
        self.setColumnWidth(6, 140)  # Finished (wider for YYYY-MM-DD format)
        self.setColumnWidth(7, 80)   # action
        self.setColumnWidth(8, 110)  # size
        self.setColumnWidth(9, 120)  # transfer
        self.setColumnWidth(10, 140) # template
        self.setColumnWidth(11, 90)  # named
        
        # Enable sorting but start with no sorting (insertion order)
        self.setSortingEnabled(True)
        self.horizontalHeader().setSortIndicatorShown(False)  # No initial sort indicator
        
        # Styling - theme-aware stylesheet for light/dark modes
        try:
            pal = self.palette()
            bg = pal.window().color()
            is_dark = (0.2126 * bg.redF() + 0.7152 * bg.greenF() + 0.0722 * bg.blueF()) < 0.5
        except Exception:
            is_dark = False
        table_bg = "#1e1e1e" if is_dark else "white"
        gridline = "rgba(255, 255, 255, 0.08)" if is_dark else "rgba(128, 128, 128, 0.1)"
        alt_bg = "rgba(64, 64, 64, 0.35)" if is_dark else "rgba(240, 240, 240, 0.3)"
        border = "#444444" if is_dark else "#cccccc"
        header_bg = "#333333" if is_dark else "#f0f0f0"
        header_hover = "#3a3a3a" if is_dark else "#e0e0e0"
        header_bottom = "#3498db" if not is_dark else "#2d6ea3"
        selected_bg = "#1f6aa5" if is_dark else "#2980b9"
        self.setStyleSheet(f"""
            QTableWidget {{
                gridline-color: {gridline};
                alternate-background-color: {alt_bg};
                border: 1px solid {border};
                border-radius: 4px;
                background-color: {table_bg};
            }}
            QTableWidget::item {{
                padding: 0px 4px;
                border: none;
            }}
            QTableWidget::item:selected {{
                background-color: {selected_bg};
                color: white;
            }}
            QHeaderView::section {{
                background-color: {header_bg};
                padding: 1px 3px; /* tighter header padding */
                border: none;
                font-weight: bold;
                font-size: 10px; /* slightly smaller header text */
                border-bottom: 2px solid {header_bottom};
            }}
            QHeaderView::section:hover {{
                background-color: {header_hover};
            }}
        """)
        self.setShowGrid(True)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(28)  # Slightly shorter rows
        
        # Column visibility is managed by window settings; defaults applied in restore_table_settings

        # Disable auto-expansion behavior; make columns behave like Excel (no auto-resize of others)
        try:
            header.setSectionsMovable(True)
            header.setStretchLastSection(False)
            self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        except Exception:
            pass

    # Remove auto-expansion/resize coupling to keep Excel-like behavior
    def resizeEvent(self, event):
        super().resizeEvent(event)
        
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
    
    def resizeEvent(self, event):
        """Auto-expand Gallery Name (col 1) when there is extra horizontal space.
        Keep it otherwise user-resizable and clamp to a reasonable minimum when shrinking."""
        super().resizeEvent(event)
        try:
            name_col_index = 1
            if self.isColumnHidden(name_col_index):
                return
            # Calculate available space for the name column
            viewport_width = self.viewport().width()
            other_widths = 0
            for col in range(self.columnCount()):
                if col == name_col_index or self.isColumnHidden(col):
                    continue
                other_widths += self.columnWidth(col)
            # Do not subtract vertical scrollbar width; viewport width excludes it already
            available = viewport_width - other_widths
            # Clamp and apply
            min_width = 120
            current = self.columnWidth(name_col_index)
            target = max(min_width, available)
            if target != current and target > 0:
                self.setColumnWidth(name_col_index, target)
        except Exception:
            pass
    
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
                # Open gallery link(s) for completed items
                open_link_action = menu.addAction("Open Gallery Link")
                open_link_action.triggered.connect(lambda: self.open_gallery_links_via_menu(completed_paths))
        
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

    def open_gallery_links_via_menu(self, paths):
        """Open gallery link(s) in the system browser for completed items."""
        # Find the main GUI window for access to queue_manager and logging
        widget = self
        while widget and not hasattr(widget, 'queue_manager'):
            widget = widget.parent()
        if not widget:
            return
        opened = 0
        for path in paths:
            try:
                item = widget.queue_manager.get_item(path)
            except Exception:
                item = None
            if not item or item.status != "completed":
                continue
            url = (item.gallery_url or "").strip()
            if not url:
                # Fallback: attempt to read JSON and extract meta.gallery_url
                try:
                    folder_name = os.path.basename(path)
                    from imxup import get_central_storage_path, build_gallery_filenames
                    json_path_candidates = []
                    uploaded_subdir = os.path.join(path, ".uploaded")
                    if item.gallery_id and (item.name or folder_name):
                        _, json_filename, _ = build_gallery_filenames(item.name or folder_name, item.gallery_id)
                        json_path_candidates.append(os.path.join(uploaded_subdir, json_filename))
                        json_path_candidates.append(os.path.join(get_central_storage_path(), json_filename))
                    # As a last resort, consider any JSON inside .uploaded
                    if os.path.isdir(uploaded_subdir):
                        for fname in os.listdir(uploaded_subdir):
                            if fname.lower().endswith('.json'):
                                json_path_candidates.append(os.path.join(uploaded_subdir, fname))
                    for jp in json_path_candidates:
                        if os.path.exists(jp):
                            with open(jp, 'r', encoding='utf-8') as f:
                                data = json.load(f)
                                url = ((data.get('meta') or {}).get('gallery_url') or "").strip()
                            if url:
                                break
                except Exception:
                    url = ""
            if url:
                try:
                    QDesktopServices.openUrl(QUrl(url))
                    opened += 1
                except Exception:
                    pass
        # Brief user feedback
        try:
            if opened:
                message = f"Opened {opened} gallery link" + ("s" if opened != 1 else "")
            else:
                message = "No gallery link found to open"
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
        layout.setContentsMargins(0, 2, 0, 2)  # remove left/right padding in Actions cell
        layout.setSpacing(4)
        
        
        self.start_btn = QPushButton("Start")
        self.start_btn.setFixedSize(65, 25)
        # Set icon and hover style
        try:
            assets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
            def _make_icon(names: list[str], fallback_std: Optional[QStyle.StandardPixmap] = None) -> QIcon:
                for name in names:
                    p = os.path.join(assets_dir, name)
                    if os.path.exists(p):
                        return QIcon(p)
                return self.style().standardIcon(fallback_std) if fallback_std is not None else QIcon()
            self.start_btn.setIcon(_make_icon(["start.png", "play.png"], QStyle.StandardPixmap.SP_MediaPlay))
            self.start_btn.setIconSize(QSize(16, 16))
            self.start_btn.setText("")
            self.start_btn.setToolTip("Start")
            icon_btn_style = (
                "QPushButton { background-color: transparent; border: none; padding: 2px; }"
                "QPushButton:hover { background-color: rgba(0,0,0,0.06); border-radius: 4px; }"
                "QPushButton:pressed { background-color: rgba(0,0,0,0.12); }"
            )
            self.start_btn.setStyleSheet(icon_btn_style)
        except Exception:
            pass
        
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
        try:
            assets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
            def _make_icon(names: list[str], fallback_std: Optional[QStyle.StandardPixmap] = None) -> QIcon:
                for name in names:
                    p = os.path.join(assets_dir, name)
                    if os.path.exists(p):
                        return QIcon(p)
                return self.style().standardIcon(fallback_std) if fallback_std is not None else QIcon()
            self.stop_btn.setIcon(_make_icon(["stop.png"], QStyle.StandardPixmap.SP_MediaStop))
            self.stop_btn.setIconSize(QSize(16, 16))
            self.stop_btn.setText("")
            self.stop_btn.setToolTip("Stop")
            self.stop_btn.setStyleSheet(icon_btn_style)
        except Exception:
            pass
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
        try:
            assets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
            def _make_icon(names: list[str], fallback_std: Optional[QStyle.StandardPixmap] = None) -> QIcon:
                for name in names:
                    p = os.path.join(assets_dir, name)
                    if os.path.exists(p):
                        return QIcon(p)
                return self.style().standardIcon(fallback_std) if fallback_std is not None else QIcon()
            self.view_btn.setIcon(_make_icon(["view.png"], QStyle.StandardPixmap.SP_DirOpenIcon))
            self.view_btn.setIconSize(QSize(16, 16))
            self.view_btn.setText("")
            self.view_btn.setToolTip("View")
            self.view_btn.setStyleSheet(icon_btn_style)
        except Exception:
            pass
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
        try:
            assets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
            def _make_icon(names: list[str], fallback_std: Optional[QStyle.StandardPixmap] = None) -> QIcon:
                for name in names:
                    p = os.path.join(assets_dir, name)
                    if os.path.exists(p):
                        return QIcon(p)
                return self.style().standardIcon(fallback_std) if fallback_std is not None else QIcon()
            # Use pause.png as requested
            self.cancel_btn.setIcon(_make_icon(["pause.png"], QStyle.StandardPixmap.SP_MediaPause))
            self.cancel_btn.setIconSize(QSize(16, 16))
            self.cancel_btn.setText("")
            self.cancel_btn.setToolTip("Pause/Cancel queued item")
            self.cancel_btn.setStyleSheet(icon_btn_style)
        except Exception:
            pass    
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
        
        layout.addWidget(self.start_btn)
        layout.addWidget(self.stop_btn)
        layout.addWidget(self.view_btn)
        layout.addWidget(self.cancel_btn)
        # Default to left alignment; will auto-center only if content fits
        layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self._layout = layout

    def resizeEvent(self, event):
        super().resizeEvent(event)
        try:
            # Auto-center actions only if all visible buttons fit in the available width
            visible_buttons = [b for b in (self.start_btn, self.stop_btn, self.view_btn, self.cancel_btn) if b.isVisible()]
            if not visible_buttons:
                return
            spacing = self._layout.spacing() or 0
            content_width = sum(btn.width() for btn in visible_buttons) + spacing * (len(visible_buttons) - 1)
            if content_width <= self.width():
                self._layout.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
            else:
                self._layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        except Exception:
            pass
    
    def update_buttons(self, status: str):
        """Update button visibility based on status"""
        if status == "ready":
            self.start_btn.setVisible(True)
            self.start_btn.setToolTip("Start")
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
            self.stop_btn.setToolTip("Stop")
            self.view_btn.setVisible(False)
            self.cancel_btn.setVisible(False)
        elif status == "paused":
            self.start_btn.setVisible(True)
            self.start_btn.setToolTip("Resume")
            self.stop_btn.setVisible(False)
            self.view_btn.setVisible(False)
            self.cancel_btn.setVisible(False)
        elif status == "incomplete":
            self.start_btn.setVisible(True)
            self.start_btn.setToolTip("Resume")
            self.stop_btn.setVisible(False)
            self.view_btn.setVisible(False)
            self.cancel_btn.setVisible(False)
        elif status == "completed":
            self.start_btn.setVisible(False)
            self.stop_btn.setVisible(False)
            self.view_btn.setVisible(True)
            self.view_btn.setToolTip("View")
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

        # Theme-aware colors
        try:
            pal = self.palette()
            bg = pal.window().color()
            # Simple luminance check
            is_dark = (0.2126 * bg.redF() + 0.7152 * bg.greenF() + 0.0722 * bg.blueF()) < 0.5
        except Exception:
            is_dark = False
        self._muted_color = "#aaaaaa" if is_dark else "#666666"
        self._text_color = "#dddddd" if is_dark else "#333333"
        self._panel_bg = "#2e2e2e" if is_dark else "#f0f8ff"
        self._panel_border = "#444444" if is_dark else "#cccccc"
        
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
        info_text.setStyleSheet(f"padding: 10px; background-color: {self._panel_bg}; border: 1px solid {self._panel_border}; border-radius: 5px; color: {self._text_color};")
        layout.addWidget(info_text)
        

        
        # Credential status display
        status_group = QGroupBox("Current Credentials")
        status_layout = QVBoxLayout(status_group)
        
        # Username status
        username_status_layout = QHBoxLayout()
        username_status_layout.addWidget(QLabel("Username: "))
        self.username_status_label = QLabel("NOT SET")
        self.username_status_label.setStyleSheet(f"color: {self._muted_color}; font-style: italic;")
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
        self.password_status_label.setStyleSheet(f"color: {self._muted_color}; font-style: italic;")
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
        self.api_key_status_label.setStyleSheet(f"color: {self._muted_color}; font-style: italic;")
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
        self.cookies_status_label.setStyleSheet(f"color: {self._muted_color}; font-style: italic;")
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
            _, json_filename, bbcode_filename = build_gallery_filenames(gallery_name, gallery_id)
            central_bbcode = os.path.join(self.central_path, bbcode_filename)
            central_url = None
        else:
            # Fallback to legacy naming detection for read-only purposes
            central_bbcode = os.path.join(self.central_path, f"{self.folder_name}_bbcode.txt")
            central_url = os.path.join(self.central_path, f"{self.folder_name}.url")

        # Folder location files: standardized names under .uploaded (fallback to legacy glob)
        import glob
        uploaded_dir = os.path.join(self.folder_path, ".uploaded")
        if gallery_id and gallery_name:
            _, json_filename, bbcode_filename = build_gallery_filenames(gallery_name, gallery_id)
            folder_bbcode_files = glob.glob(os.path.join(uploaded_dir, bbcode_filename))
            folder_url_files = []
        else:
            folder_bbcode_files = glob.glob(os.path.join(uploaded_dir, f"{self.folder_name}_bbcode.txt"))
            folder_url_files = []
        
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

class LogTextEdit(QTextEdit):
    """Text edit for logs that emits a signal on double-click."""
    doubleClicked = pyqtSignal()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            try:
                self.doubleClicked.emit()
            except Exception:
                pass
        super().mouseDoubleClickEvent(event)

class LogViewerDialog(QDialog):
    """Popout viewer for application logs."""
    def __init__(self, initial_text: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Log Viewer")
        self.setModal(False)
        self.resize(1000, 720)

        self.follow_enabled = True

        layout = QVBoxLayout(self)

        # Prepare logger and settings (used by both tabs)
        try:
            from imxup_logging import get_logger as _get_logger
            self._logger = _get_logger()
            settings = self._logger.get_settings()
        except Exception:
            self._logger = None
            settings = {
                'enabled': True,
                'rotation': 'daily',
                'backup_count': 7,
                'compress': True,
                'max_bytes': 10485760,
                'level_file': 'INFO',
                'level_gui': 'INFO',
            }

        # Build Settings tab content
        header = QGroupBox("Log Settings")
        grid = QGridLayout(header)

        self.chk_enabled = QCheckBox("Enable file logging")
        self.chk_enabled.setChecked(bool(settings.get('enabled', True)))
        grid.addWidget(self.chk_enabled, 0, 0, 1, 2)

        self.cmb_rotation = QComboBox()
        self.cmb_rotation.addItems(["daily", "size"])
        try:
            idx = ["daily", "size"].index(str(settings.get('rotation', 'daily')).lower())
        except Exception:
            idx = 0
        self.cmb_rotation.setCurrentIndex(idx)
        grid.addWidget(QLabel("Rotation:"), 1, 0)
        grid.addWidget(self.cmb_rotation, 1, 1)

        self.spn_backup = QSpinBox()
        self.spn_backup.setRange(0, 3650)
        self.spn_backup.setValue(int(settings.get('backup_count', 7)))
        grid.addWidget(QLabel("Backups to keep:"), 1, 2)
        grid.addWidget(self.spn_backup, 1, 3)

        self.chk_compress = QCheckBox("Compress rotated logs (.gz)")
        self.chk_compress.setChecked(bool(settings.get('compress', True)))
        grid.addWidget(self.chk_compress, 2, 0, 1, 2)

        self.spn_max_bytes = QSpinBox()
        self.spn_max_bytes.setRange(1024, 1024 * 1024 * 1024)
        self.spn_max_bytes.setSingleStep(1024 * 1024)
        self.spn_max_bytes.setValue(int(settings.get('max_bytes', 10485760)))
        grid.addWidget(QLabel("Max size (bytes, size mode):"), 2, 2)
        grid.addWidget(self.spn_max_bytes, 2, 3)

        self.cmb_gui_level = QComboBox()
        levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        self.cmb_gui_level.addItems(levels)
        try:
            self.cmb_gui_level.setCurrentIndex(levels.index(str(settings.get('level_gui', 'INFO')).upper()))
        except Exception:
            pass
        grid.addWidget(QLabel("GUI level:"), 3, 0)
        grid.addWidget(self.cmb_gui_level, 3, 1)

        self.cmb_file_level = QComboBox()
        self.cmb_file_level.addItems(levels)
        try:
            self.cmb_file_level.setCurrentIndex(levels.index(str(settings.get('level_file', 'INFO')).upper()))
        except Exception:
            pass
        grid.addWidget(QLabel("File level:"), 3, 2)
        grid.addWidget(self.cmb_file_level, 3, 3)

        buttons_row = QHBoxLayout()
        self.btn_apply = QPushButton("Apply Settings")
        self.btn_open_dir = QPushButton("Open Logs Folder")
        buttons_row.addWidget(self.btn_apply)
        buttons_row.addWidget(self.btn_open_dir)
        grid.addLayout(buttons_row, 4, 0, 1, 4)

        # Category toggles section
        cats = [
            ("uploads", "Uploads"),
            ("auth", "Authentication"),
            ("network", "Network"),
            ("ui", "UI"),
            ("queue", "Queue"),
            ("general", "General"),
        ]
        row = 5
        for cat_key, cat_label in cats:
            try:
                gui_key = f"cats_gui_{cat_key}"
                file_key = f"cats_file_{cat_key}"
                chk_gui = QCheckBox(f"Show {cat_label} in GUI log")
                chk_file = QCheckBox(f"Write {cat_label} to file log")
                chk_gui.setObjectName(gui_key)
                chk_file.setObjectName(file_key)
                chk_gui.setChecked(bool(settings.get(gui_key, True)))
                chk_file.setChecked(bool(settings.get(file_key, True)))
                grid.addWidget(chk_gui, row, 0, 1, 2)
                grid.addWidget(chk_file, row, 2, 1, 2)
                row += 1
            except Exception:
                pass

        # Upload success modes
        grid.addWidget(QLabel("Upload success detail (GUI):"), row, 0)
        self.cmb_gui_upload_mode = QComboBox()
        self.cmb_gui_upload_mode.addItems(["none", "file", "gallery", "both"])
        try:
            self.cmb_gui_upload_mode.setCurrentText(str(settings.get("upload_success_mode_gui", "gallery")))
        except Exception:
            pass
        grid.addWidget(self.cmb_gui_upload_mode, row, 1)
        grid.addWidget(QLabel("Upload success detail (File):"), row, 2)
        self.cmb_file_upload_mode = QComboBox()
        self.cmb_file_upload_mode.addItems(["none", "file", "gallery", "both"])
        try:
            self.cmb_file_upload_mode.setCurrentText(str(settings.get("upload_success_mode_file", "gallery")))
        except Exception:
            pass
        grid.addWidget(self.cmb_file_upload_mode, row, 3)
        row += 1

        def on_apply():
            if not self._logger:
                return
            try:
                # Collect category toggles
                cat_kwargs = {}
                for cat_key, _label in cats:
                    gui_key = f"cats_gui_{cat_key}"
                    file_key = f"cats_file_{cat_key}"
                    w_gui = header.findChild(QCheckBox, gui_key)
                    w_file = header.findChild(QCheckBox, file_key)
                    if w_gui is not None:
                        cat_kwargs[gui_key] = w_gui.isChecked()
                    if w_file is not None:
                        cat_kwargs[file_key] = w_file.isChecked()
                self._logger.update_settings(
                    enabled=self.chk_enabled.isChecked(),
                    rotation=self.cmb_rotation.currentText().lower(),
                    backup_count=self.spn_backup.value(),
                    compress=self.chk_compress.isChecked(),
                    max_bytes=self.spn_max_bytes.value(),
                    level_gui=self.cmb_gui_level.currentText(),
                    level_file=self.cmb_file_level.currentText(),
                    upload_success_mode_gui=self.cmb_gui_upload_mode.currentText(),
                    upload_success_mode_file=self.cmb_file_upload_mode.currentText(),
                    **cat_kwargs,
                )
                # Reload log content to reflect format changes
                try:
                    self.log_view.setPlainText(self._logger.read_current_log(tail_bytes=2 * 1024 * 1024))
                except Exception:
                    pass
            except Exception:
                pass

        def on_open_dir():
            try:
                from PyQt6.QtGui import QDesktopServices
                from PyQt6.QtCore import QUrl
                logs_dir = self._logger.get_logs_dir() if self._logger else None
                if logs_dir and os.path.exists(logs_dir):
                    QDesktopServices.openUrl(QUrl.fromLocalFile(logs_dir))
            except Exception:
                pass

        self.btn_apply.clicked.connect(on_apply)
        self.btn_open_dir.clicked.connect(on_open_dir)

        # Build Logs tab
        logs_container = QWidget()
        logs_vbox = QVBoxLayout(logs_container)

        # Toolbar row
        toolbar = QHBoxLayout()
        self.cmb_file_select = QComboBox()
        self.cmb_tail = QComboBox()
        self.cmb_tail.addItems(["128 KB", "512 KB", "2 MB", "Full"])
        self.cmb_tail.setCurrentIndex(2)
        self.chk_follow = QCheckBox("Follow")
        self.chk_follow.setChecked(True)
        self.btn_refresh = QPushButton("Refresh")
        self.btn_clear = QPushButton("Clear View")
        self.find_input = QLineEdit()
        self.find_input.setPlaceholderText("Find...")
        self.btn_find = QPushButton("Find Next")
        toolbar.addWidget(QLabel("File:"))
        toolbar.addWidget(self.cmb_file_select, 2)
        toolbar.addWidget(QLabel("Tail:"))
        toolbar.addWidget(self.cmb_tail)
        toolbar.addStretch()
        toolbar.addWidget(self.chk_follow)
        toolbar.addWidget(self.btn_refresh)
        toolbar.addWidget(self.btn_clear)
        toolbar.addWidget(self.find_input, 1)
        toolbar.addWidget(self.btn_find)
        logs_vbox.addLayout(toolbar)

        # Filters row (separate line): 1 x 6
        self._filters_row: Dict[str, QCheckBox] = {}
        filters_bar = QHBoxLayout()
        filters_bar.addWidget(QLabel("View:"))
        for cat_key, cat_label in cats:
            cb = QCheckBox(cat_label)
            cb.setChecked(True)
            self._filters_row[cat_key] = cb
            filters_bar.addWidget(cb)
        filters_bar.addStretch()
        logs_vbox.addLayout(filters_bar)

        # Body: log view only (filters moved to toolbar)
        body_hbox = QHBoxLayout()
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        try:
            self.log_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        except Exception:
            pass
        self.log_view.setFont(QFont("Consolas", 10))
        body_hbox.addWidget(self.log_view, 1)
        logs_vbox.addLayout(body_hbox)

        # Tabs: Logs | Settings
        tabs = QTabWidget(self)
        # Settings tab
        settings_container = QWidget()
        sc_vbox = QVBoxLayout(settings_container)
        sc_vbox.addWidget(header)
        sc_vbox.addStretch()
        tabs.addTab(logs_container, "Logs")
        tabs.addTab(settings_container, "Log Settings")
        layout.addWidget(tabs)

        # Populate initial log content via loader (with tail selection default)
        def _tail_bytes_from_choice(text: str) -> int | None:
            t = (text or "").lower()
            if "full" in t:
                return None
            if "128" in t:
                return 128 * 1024
            if "512" in t:
                return 512 * 1024
            return 2 * 1024 * 1024

        def _normalize_dates(block: str) -> str:
            if not block:
                return ""
            try:
                from datetime import datetime as _dt
                today = _dt.now().strftime("%Y-%m-%d ")
                lines = block.splitlines()
                out = []
                for line in lines:
                    if len(line) >= 8 and line[2:3] == ":" and line[5:6] == ":":
                        out.append(today + line)
                    else:
                        out.append(line)
                return "\n".join(out)
            except Exception:
                return block

        def _load_logs_list():
            self.cmb_file_select.clear()
            self.cmb_file_select.addItem("Current (imxup.log)", userData="__current__")
            try:
                if self._logger:
                    logs_dir = self._logger.get_logs_dir()
                    files = []
                    for name in os.listdir(logs_dir):
                        if name.startswith("imxup.log"):
                            files.append(name)
                    files.sort(reverse=True)
                    for name in files:
                        self.cmb_file_select.addItem(name, userData=os.path.join(logs_dir, name))
            except Exception:
                pass

        def _read_selected_file() -> str:
            # Read according to file selection and tail size
            tail = _tail_bytes_from_choice(self.cmb_tail.currentText())
            try:
                if self.cmb_file_select.currentData() == "__current__" and self._logger:
                    return self._logger.read_current_log(tail_bytes=tail) or ""
                # Else fallback to reading the selected path
                path = self.cmb_file_select.currentData()
                if not path:
                    return ""
                if str(path).endswith(".gz"):
                    import gzip
                    with gzip.open(path, "rb") as f:
                        data = f.read()
                    if tail:
                        data = data[-int(tail):]
                    return data.decode("utf-8", errors="replace")
                else:
                    if tail and os.path.exists(path):
                        size = os.path.getsize(path)
                        with open(path, "rb") as f:
                            if size > tail:
                                f.seek(-tail, os.SEEK_END)
                            data = f.read()
                        return data.decode("utf-8", errors="replace")
                    with open(path, "r", encoding="utf-8", errors="replace") as f:
                        return f.read()
            except Exception:
                return ""

        def _apply_initial_content():
            try:
                block = initial_text or _read_selected_file()
            except Exception:
                block = initial_text
            norm = _normalize_dates(block)
            self.log_view.setPlainText(norm)

        _load_logs_list()
        _apply_initial_content()

        # Wire toolbar actions
        def _strip_datetime_prefix(s: str) -> str:
            try:
                t = s.lstrip()
                # YYYY-MM-DD HH:MM:SS
                if len(t) >= 19 and t[4] == '-' and t[7] == '-' and t[10] == ' ' and t[13] == ':' and t[16] == ':':
                    return t[19:].lstrip()
                # HH:MM:SS
                if len(t) >= 8 and t[2] == ':' and t[5] == ':':
                    return t[8:].lstrip()
                return s
            except Exception:
                return s

        def _filter_block_by_view_cats(block: str) -> str:
            if not block:
                return ""
            try:
                lines = block.splitlines()
                out = []
                for line in lines:
                    # Extract token after optional date/time prefix
                    head = _strip_datetime_prefix(line)
                    cat = "general"
                    if head.startswith("[") and "]" in head:
                        token = head[1:head.find("]")]
                        cat = token.split(":")[0] or "general"
                    if cat in self._filters_row and not self._filters_row[cat].isChecked():
                        continue
                    out.append(line)
                return "\n".join(out)
            except Exception:
                return block

        def on_refresh():
            text = _normalize_dates(_read_selected_file())
            text = _filter_block_by_view_cats(text)
            self.log_view.setPlainText(text)

        self.btn_refresh.clicked.connect(on_refresh)
        self.cmb_file_select.currentIndexChanged.connect(on_refresh)
        self.cmb_tail.currentIndexChanged.connect(on_refresh)

        # Changing view filters should refilter the current view
        def on_filter_changed(_=None):
            # Re-apply filtering to current content by simulating a refresh
            on_refresh()
        # Bind filters row checkboxes
        for _key, cb in self._filters_row.items():
            try:
                cb.toggled.connect(on_filter_changed)
            except Exception:
                pass

        def on_clear():
            self.log_view.clear()
        self.btn_clear.clicked.connect(on_clear)

        def on_follow_toggle(_=None):
            self.follow_enabled = self.chk_follow.isChecked()
        self.chk_follow.toggled.connect(on_follow_toggle)

        # Find functionality
        def on_find_next():
            pattern = (self.find_input.text() or "").strip()
            if not pattern:
                return
            doc: QTextDocument = self.log_view.document()
            cursor = self.log_view.textCursor()
            # Move one char to avoid matching the same selection
            if cursor.hasSelection():
                cursor.setPosition(cursor.selectionEnd())
            found = doc.find(pattern, cursor)
            if not found.isNull():
                self.log_view.setTextCursor(found)
                self.log_view.ensureCursorVisible()
        self.btn_find.clicked.connect(on_find_next)
        self.find_input.returnPressed.connect(on_find_next)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.rejected.connect(self.reject)
        button_box.accepted.connect(self.accept)
        layout.addWidget(button_box)

    def append_message(self, message: str):
        try:
            # Determine category like [uploads], [uploads:file], [auth], etc.
            category = "general"
            head = message
            try:
                parts = message.split(" ", 1)
                if len(parts) > 1 and parts[0].count(":") == 2:
                    head = parts[1]
                if head.startswith("[") and "]" in head:
                    token = head[1:head.find("]")]
                    category = token.split(":")[0] or "general"
            except Exception:
                pass
            # Apply viewer-only filters
            # Apply viewer-only filters (toolbar row)
            if category in getattr(self, '_filters_row', {}) and not self._filters_row[category].isChecked():
                return
            # Ensure date is visible in the log viewer if time-only
            from datetime import datetime as _dt
            if isinstance(message, str) and len(message) >= 9 and message[2:3] == ":":
                today = _dt.now().strftime("%Y-%m-%d ")
                line = today + message
            else:
                line = message
            # Append and optionally follow
            self.log_view.appendPlainText(line)
            if self.follow_enabled:
                cursor = self.log_view.textCursor()
                cursor.movePosition(cursor.MoveOperation.End)
                self.log_view.setTextCursor(cursor)
                self.log_view.ensureCursorVisible()
        except Exception:
            pass

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
        self.progress_bar.setMinimumHeight(17)  # +1px height
        self.progress_bar.setMaximumHeight(19)  # +1px height
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

class NumericTableWidgetItem(QTableWidgetItem):
    """Table widget item that sorts numerically based on an integer value."""
    def __init__(self, value: int):
        super().__init__(str(value))
        try:
            self._numeric_value = int(value)
        except Exception:
            self._numeric_value = 0

    def __lt__(self, other: "QTableWidgetItem") -> bool:  # type: ignore[override]
        if isinstance(other, NumericTableWidgetItem):
            return self._numeric_value < other._numeric_value
        try:
            return self._numeric_value < int(other.text())
        except Exception:
            return super().__lt__(other)

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
        self.setup_menu_bar()
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
            self._update_scan_status()
        self.update_timer.timeout.connect(_tick)
        self.update_timer.start(500)  # 2Hz tick
        
        # Add scanning status indicator to status bar
        self.scan_status_label = QLabel("Scanning: 0")
        self.scan_status_label.setVisible(False)
        self.statusBar().addPermanentWidget(self.scan_status_label)
        # Log viewer dialog reference
        self._log_viewer_dialog = None
        # Lazy-loaded status icons (check/pending/uploading/failed)
        self._icon_check = None
        # Theme cache
        self._current_theme_mode = str(self.settings.value('ui/theme', 'system'))
        self._icon_pending = None
        self._icon_up = None
        self._icon_stop = None
        # Preload icons so first render has them
        try:
            self._load_status_icons_if_needed()
        except Exception:
            pass
    
    def _update_scan_status(self):
        """Update the scanning status indicator in the status bar."""
        try:
            scan_status = self.queue_manager.get_scan_queue_status()
            queue_size = scan_status['queue_size']
            items_pending = scan_status['items_pending_scan']
            
            if queue_size > 0 or items_pending > 0:
                self.scan_status_label.setText(f"Scanning: {items_pending} pending, {queue_size} in queue")
                self.scan_status_label.setVisible(True)
            else:
                self.scan_status_label.setVisible(False)
        except Exception:
            # Hide on error
            self.scan_status_label.setVisible(False)

    def _load_status_icons_if_needed(self):
        try:
            if self._icon_check is None or self._icon_pending is None or self._icon_up is None or self._icon_stop is None:
                base_dir = os.path.dirname(os.path.abspath(__file__))
                try:
                    import sys as _sys
                    app_dir = os.path.dirname(os.path.abspath(_sys.argv[0]))
                except Exception:
                    app_dir = None
                candidates = [
                    os.path.join(base_dir, "check16.png"),
                    os.path.join(os.getcwd(), "check16.png"),
                    os.path.join(base_dir, "assets", "check16.png"),
                    os.path.join(app_dir, "check16.png") if app_dir else None,
                    os.path.join(app_dir, "assets", "check16.png") if app_dir else None,
                ]
                candidates_pending = [
                    os.path.join(base_dir, "pending.png"),
                    os.path.join(os.getcwd(), "pending.png"),
                    os.path.join(base_dir, "assets", "pending.png"),
                    os.path.join(app_dir, "pending.png") if app_dir else None,
                    os.path.join(app_dir, "assets", "pending.png") if app_dir else None,
                ]
                candidates_up = [
                    os.path.join(base_dir, "up.png"),
                    os.path.join(os.getcwd(), "up.png"),
                    os.path.join(base_dir, "assets", "up.png"),
                    os.path.join(app_dir, "up.png") if app_dir else None,
                    os.path.join(app_dir, "assets", "up.png") if app_dir else None,
                ]
                candidates_stop = [
                    os.path.join(base_dir, "error.png"),
                    os.path.join(os.getcwd(), "error.png"),
                    os.path.join(base_dir, "assets", "error.png"),
                    os.path.join(app_dir, "error.png") if app_dir else None,
                    os.path.join(app_dir, "assets", "error.png") if app_dir else None,
                ]
                chk = QPixmap()
                for p in candidates:
                    if not p:
                        continue
                    if os.path.exists(p):
                        chk = QPixmap(p)
                        if not chk.isNull():
                            break
                pen = QPixmap()
                for p in candidates_pending:
                    if not p:
                        continue
                    if os.path.exists(p):
                        pen = QPixmap(p)
                        if not pen.isNull():
                            break
                upm = QPixmap()
                for p in candidates_up:
                    if not p:
                        continue
                    if os.path.exists(p):
                        upm = QPixmap(p)
                        if not upm.isNull():
                            break
                stm = QPixmap()
                for p in candidates_stop:
                    if not p:
                        continue
                    if os.path.exists(p):
                        stm = QPixmap(p)
                        if not stm.isNull():
                            break
                self._icon_check = chk if not chk.isNull() else None
                self._icon_pending = pen if not pen.isNull() else None
                self._icon_up = upm if not upm.isNull() else None
                self._icon_stop = stm if not stm.isNull() else None

                # Fallback: draw simple vector icons if PNG loading fails (e.g., missing imageformat plugins)
                if self._icon_check is None:
                    try:
                        pm = QPixmap(24, 24)
                        pm.fill(Qt.GlobalColor.transparent)
                        painter = QPainter(pm)
                        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                        painter.setBrush(QColor(46, 204, 113))  # green
                        painter.setPen(Qt.PenStyle.NoPen)
                        painter.drawEllipse(0, 0, 24, 24)
                        painter.setPen(QColor(255, 255, 255))
                        painter.setBrush(Qt.BrushStyle.NoBrush)
                        painter.setPen(QColor(255, 255, 255))
                        painter.setPen(Qt.PenStyle.SolidLine)
                        painter.setPen(QColor(255, 255, 255))
                        # Draw a simple checkmark
                        path = QPainterPath()
                        path.moveTo(6, 13)
                        path.lineTo(10, 17)
                        path.lineTo(18, 8)
                        painter.setPen(QPen(QColor(255, 255, 255), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                        painter.drawPath(path)
                        painter.end()
                        self._icon_check = pm
                    except Exception:
                        self._icon_check = None
                if self._icon_pending is None:
                    try:
                        pm = QPixmap(24, 24)
                        pm.fill(Qt.GlobalColor.transparent)
                        painter = QPainter(pm)
                        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                        painter.setBrush(QColor(241, 196, 15))  # yellow
                        painter.setPen(Qt.PenStyle.NoPen)
                        painter.drawEllipse(0, 0, 24, 24)
                        # clock hands
                        painter.setPen(QPen(QColor(0, 0, 0), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                        painter.drawLine(12, 12, 12, 6)
                        painter.drawLine(12, 12, 17, 12)
                        painter.end()
                        self._icon_pending = pm
                    except Exception:
                        self._icon_pending = None
        except Exception:
            # Leave icons as None if loading fails
            self._icon_check = self._icon_check or None
            self._icon_pending = self._icon_pending or None
            self._icon_up = self._icon_up or None
            self._icon_stop = self._icon_stop or None

    def _set_status_cell_icon(self, row: int, status: str):
        """Render the Status column as an icon only, without background/text.
        Supported statuses: completed, failed, uploading, paused, queued, ready, incomplete, scanning.
        Others fall back to pending icon.
        """
        try:
            self._load_status_icons_if_needed()
            col = 4
            # Clear any existing widget/item first
            try:
                self.gallery_table.removeCellWidget(row, col)
            except Exception:
                pass
            icon = None
            tooltip = ""
            
            if status == "completed" and self._icon_check is not None:
                icon = self._icon_check
                tooltip = "Completed"
            elif status == "failed" and self._icon_stop is not None:
                icon = self._icon_stop
                # Get error details for failed galleries
                try:
                    path = self.gallery_table.item(row, 1).data(Qt.ItemDataRole.UserRole)
                    if path and path in self.queue_manager.items:
                        item = self.queue_manager.items[path]
                        if item.error_message:
                            tooltip = f"Failed: {item.error_message}"
                            # Add failed files details if available
                            if hasattr(item, 'failed_files') and item.failed_files:
                                failed_count = len(item.failed_files)
                                tooltip += f"\n\nFailed files ({failed_count}):"
                                for filename, error in item.failed_files[:3]:  # Show first 3
                                    tooltip += f"\n• {filename}: {error}"
                                if failed_count > 3:
                                    tooltip += f"\n... and {failed_count - 3} more"
                        else:
                            tooltip = "Failed"
                    else:
                        tooltip = "Failed"
                except Exception:
                    tooltip = "Failed"
            elif status == "uploading" and self._icon_up is not None:
                icon = self._icon_up
                tooltip = "Uploading"
            else:
                icon = self._icon_pending if self._icon_pending is not None else None
                tooltip = status.title() if isinstance(status, str) else ""
            
            if icon is not None:
                label = QLabel()
                label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                if tooltip:
                    label.setToolTip(tooltip)
                
                # For failed galleries, make the icon clickable to show detailed error info
                if status == "failed":
                    label.setCursor(Qt.CursorShape.PointingHandCursor)
                    label.mousePressEvent = lambda event, row=row: self._show_failed_gallery_details(row)
                
                try:
                    row_h = self.gallery_table.rowHeight(row)
                    if not row_h or row_h <= 0:
                        row_h = self.gallery_table.verticalHeader().defaultSectionSize()
                    size = max(12, min(20, row_h - 6))
                except Exception:
                    size = 16
                label.setPixmap(icon.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                self.gallery_table.setCellWidget(row, col, label)
            else:
                item = QTableWidgetItem(status.title() if isinstance(status, str) else "")
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                try:
                    font = item.font()
                    font.setPointSize(8)
                    item.setFont(font)
                except Exception:
                    pass
                self.gallery_table.setItem(row, col, item)
        except Exception:
            pass

    def _show_failed_gallery_details(self, row: int):
        """Show detailed error information for a failed gallery."""
        try:
            path = self.gallery_table.item(row, 1).data(Qt.ItemDataRole.UserRole)
            if not path or path not in self.queue_manager.items:
                return
            
            item = self.queue_manager.items[path]
            if item.status != "failed":
                return
            
            # Build detailed error message
            error_details = f"Gallery: {item.name or 'Unknown'}\n"
            error_details += f"Path: {item.path}\n"
            error_details += f"Status: {item.status}\n\n"
            
            if item.error_message:
                error_details += f"Error: {item.error_message}\n\n"
            
            if hasattr(item, 'failed_files') and item.failed_files:
                error_details += f"Failed Files ({len(item.failed_files)}):\n"
                for filename, error in item.failed_files:
                    error_details += f"\n• {filename}\n  {error}\n"
            else:
                error_details += "No specific file error details available."
            
            # Show in a dialog
            from PyQt6.QtWidgets import QMessageBox
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Icon.Information)
            msg_box.setWindowTitle("Failed Gallery Details")
            msg_box.setText(error_details)
            msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg_box.exec()
            
        except Exception as e:
            # Fallback to simple error message
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Error", f"Failed to show error details: {str(e)}")

    def _set_renamed_cell_icon(self, row: int, is_renamed: bool | None):
        """Set the Renamed column cell to an icon (check/pending) if available; fallback to text.
        is_renamed=True -> check, False -> pending, None -> blank
        """
        try:
            self._load_status_icons_if_needed()
            col = 11
            # Clear any existing widget/item first for consistency
            try:
                self.gallery_table.removeCellWidget(row, col)
            except Exception:
                pass
            # Determine icon and tooltip
            if is_renamed is True and self._icon_check is not None:
                icon = self._icon_check
                tooltip = "Renamed"
            elif is_renamed is False and self._icon_pending is not None:
                icon = self._icon_pending
                tooltip = "Pending rename"
            else:
                icon = None
                tooltip = ""
            if icon is not None:
                label = QLabel()
                label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                if tooltip:
                    label.setToolTip(tooltip)
                # Scale icon to fit current row height of this row if available; fallback to default
                try:
                    row_h = self.gallery_table.rowHeight(row)
                    if not row_h or row_h <= 0:
                        row_h = self.gallery_table.verticalHeader().defaultSectionSize()
                    size = max(12, min(20, row_h - 6))
                except Exception:
                    size = 16
                label.setPixmap(icon.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                self.gallery_table.setCellWidget(row, col, label)
            else:
                # Fallback to text symbols
                txt = "✔" if is_renamed is True else ("⏳" if is_renamed is False else "")
                item = QTableWidgetItem(txt)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                try:
                    item.setFont(QFont("Arial", 11))
                except Exception:
                    pass
                if tooltip:
                    item.setToolTip(tooltip)
                self.gallery_table.setItem(row, col, item)
                if getattr(self, '_icon_up', None) is None:
                    try:
                        pm = QPixmap(24, 24)
                        pm.fill(Qt.GlobalColor.transparent)
                        painter = QPainter(pm)
                        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                        painter.setPen(Qt.PenStyle.NoPen)
                        painter.setBrush(QColor(41, 128, 185))
                        # Draw an up arrow
                        path = QPainterPath()
                        path.moveTo(12, 2)
                        path.lineTo(22, 14)
                        path.lineTo(16, 14)
                        path.lineTo(16, 22)
                        path.lineTo(8, 22)
                        path.lineTo(8, 14)
                        path.lineTo(2, 14)
                        path.closeSubpath()
                        painter.drawPath(path)
                        painter.end()
                        self._icon_up = pm
                    except Exception:
                        self._icon_up = None
        except Exception:
            pass

    def _load_icon_generic(self, name_pairs: list[tuple[str, str]]):
        """Utility to load a pixmap by trying multiple relative candidates.
        name_pairs: list of (name, assets/name)
        """
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            try:
                import sys as _sys
                app_dir = os.path.dirname(os.path.abspath(_sys.argv[0]))
            except Exception:
                app_dir = None
            search = []
            for nm, asset in name_pairs:
                search.extend([
                    os.path.join(base_dir, nm),
                    os.path.join(os.getcwd(), nm),
                    os.path.join(base_dir, asset),
                    os.path.join(app_dir, nm) if app_dir else None,
                    os.path.join(app_dir, asset) if app_dir else None,
                ])
            for p in search:
                if not p:
                    continue
                if os.path.exists(p):
                    pm = QPixmap(p)
                    if not pm.isNull():
                        return pm
        except Exception:
            pass
        return None

    def showEvent(self, event):
        try:
            super().showEvent(event)
        except Exception:
            pass
        # Ensure a post-show pass updates icon cells when the table is fully realized
        try:
            QTimer.singleShot(0, self.update_queue_display)
        except Exception:
            pass
        
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
        # Tight outer margins/spacing to keep boxes close to each other
        try:
            main_layout.setContentsMargins(6, 6, 6, 6)
            main_layout.setSpacing(6)
        except Exception:
            pass
        
        # Top section with queue and settings
        top_layout = QHBoxLayout()
        try:
            top_layout.setContentsMargins(0, 0, 0, 0)
            top_layout.setSpacing(6)
        except Exception:
            pass
        
        
        # Left panel - Queue and controls (wider now)
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        try:
            left_layout.setContentsMargins(0, 0, 0, 0)
            left_layout.setSpacing(6)
        except Exception:
            pass
        
        
        # Queue section
        queue_group = QGroupBox("Upload Queue")
        queue_layout = QVBoxLayout(queue_group)
        try:
            queue_layout.setContentsMargins(10, 10, 10, 10)
            queue_layout.setSpacing(8)
        except Exception:
            pass
        
        
        # Drag-and-drop is handled at the window level; no dedicated drop label
        
        # (Moved Browse button into controls row below)
        
        # Gallery table
        self.gallery_table = GalleryTableWidget()
        self.gallery_table.setMinimumHeight(400)  # Taller table
        queue_layout.addWidget(self.gallery_table, 1)  # Give it stretch priority
        # Header context menu for column visibility + persist widths/visibility
        try:
            header = self.gallery_table.horizontalHeader()
            header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            header.customContextMenuRequested.connect(self.show_header_context_menu)
            header.sectionResized.connect(self._on_header_section_resized)
            header.sectionMoved.connect(self._on_header_section_moved)
        except Exception:
            pass
        
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

        # Browse button (moved here to be to the right of Clear Completed)
        self.browse_btn = QPushButton("Browse")
        if not self.browse_btn.text().startswith(" "):
            self.browse_btn.setText(" " + self.browse_btn.text())
        self.browse_btn.clicked.connect(self.browse_for_folders)
        self.browse_btn.setMinimumHeight(34)
        controls_layout.addWidget(self.browse_btn)
        

        
        queue_layout.addLayout(controls_layout)
        left_layout.addWidget(queue_group)
        
        top_layout.addWidget(left_panel, 3)  # 3/4 width for queue (more space)
        
        # Right panel - Settings and logs
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        try:
            # Keep the settings/log area from expanding too wide on large windows
            right_panel.setMaximumWidth(520)
        except Exception:
            pass
        try:
            right_layout.setContentsMargins(0, 0, 0, 0)
            right_layout.setSpacing(6)
        except Exception:
            pass
        
        
        # Settings section
        self.settings_group = QGroupBox("Settings")
        settings_layout = QGridLayout(self.settings_group)
        try:
            settings_layout.setContentsMargins(10, 10, 10, 10)
            settings_layout.setHorizontalSpacing(12)
            settings_layout.setVerticalSpacing(8)
        except Exception:
            pass
        
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
        self.batch_size_spin.setRange(1, 25)
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
        self.confirm_delete_check = QCheckBox("Confirm before deleting")
        self.confirm_delete_check.setChecked(defaults.get('confirm_delete', True))  # Load from defaults
        self.confirm_delete_check.toggled.connect(self.on_setting_changed)
        settings_layout.addWidget(self.confirm_delete_check, 5, 1)

        # Auto-rename unnamed galleries after successful login
        self.auto_rename_check = QCheckBox("Auto-rename galleries")
        # Default enabled
        self.auto_rename_check.setChecked(defaults.get('auto_rename', True))
        self.auto_rename_check.toggled.connect(self.on_setting_changed)
        settings_layout.addWidget(self.auto_rename_check, 6, 0, 1, 2)

        # Artifact storage location options (moved to dialog; keep hidden for persistence wiring)
        self.store_in_uploaded_check = QCheckBox("Save artifacts in .uploaded folder")
        self.store_in_uploaded_check.setChecked(defaults.get('store_in_uploaded', True))
        self.store_in_uploaded_check.setVisible(False)
        self.store_in_uploaded_check.toggled.connect(self.on_setting_changed)

        self.store_in_central_check = QCheckBox("Save artifacts in central store")
        self.store_in_central_check.setChecked(defaults.get('store_in_central', True))
        self.store_in_central_check.setVisible(False)
        self.store_in_central_check.toggled.connect(self.on_setting_changed)

        # Track central store path (from defaults)
        self.central_store_path_value = defaults.get('central_store_path', None)
        

        
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

        # Manage file locations button (between Save Settings and Manage Templates)
        self.manage_file_locations_btn = QPushButton("Manage File Locations")
        if not self.manage_file_locations_btn.text().startswith(" "):
            self.manage_file_locations_btn.setText(" " + self.manage_file_locations_btn.text())
        self.manage_file_locations_btn.clicked.connect(self.manage_file_locations)
        self.manage_file_locations_btn.setMinimumHeight(30)
        self.manage_file_locations_btn.setMaximumHeight(34)
        settings_layout.addWidget(self.manage_file_locations_btn, 9, 0, 1, 2)
        
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
        settings_layout.addWidget(self.manage_templates_btn, 10, 0, 1, 2)
        
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
        settings_layout.addWidget(self.manage_credentials_btn, 11, 0, 1, 2)
        
        right_layout.addWidget(self.settings_group)
        

        
        # Log section
        log_group = QGroupBox("Log")
        log_layout = QVBoxLayout(log_group)
        try:
            log_layout.setContentsMargins(10, 10, 10, 10)
            log_layout.setSpacing(8)
        except Exception:
            pass
        
        
        self.log_text = LogTextEdit()
        self.log_text.setMinimumHeight(300)  # Much taller
        # Slightly larger font with reduced letter spacing
        _log_font = QFont("Consolas")
        try:
            _log_font.setPointSizeF(8.5)
        except Exception:
            _log_font.setPointSize(9)
        try:
            _log_font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 98.0)
        except Exception:
            pass
        self.log_text.setFont(_log_font)
        try:
            # Do not wrap long lines; allow horizontal scrolling
            self.log_text.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
            self.log_text.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.AsNeeded)
        except Exception:
            pass
        # Double-click to open popout viewer
        try:
            self.log_text.doubleClicked.connect(self.open_log_viewer)
        except Exception:
            pass
        # Keep a long history in the GUI log
        try:
            self.log_text.document().setMaximumBlockCount(200000)  # ~200k lines
        except Exception:
            pass
        log_layout.addWidget(self.log_text)
        
        right_layout.addWidget(log_group, 1)  # Give it stretch priority
        
        top_layout.addWidget(right_panel, 0)  # Do not give extra stretch; obey max width
        
        main_layout.addLayout(top_layout)
        
        # Bottom section - Overall progress (left) and Help (right)
        bottom_layout = QHBoxLayout()
        try:
            bottom_layout.setContentsMargins(0, 0, 0, 0)
            bottom_layout.setSpacing(6)
        except Exception:
            pass
        

        # Overall progress group (left)
        progress_group = QGroupBox("Overall Progress")
        progress_layout = QVBoxLayout(progress_group)
        try:
            progress_layout.setContentsMargins(10, 10, 10, 10)
            progress_layout.setSpacing(8)
        except Exception:
            pass
        

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
        stats_group = QGroupBox("Info")
        stats_layout = QGridLayout(stats_group)
        try:
            stats_layout.setContentsMargins(10, 8, 10, 8)
            stats_layout.setHorizontalSpacing(10)
            stats_layout.setVerticalSpacing(6)
        except Exception:
            pass
        
        # Detailed stats labels (split into label and value for right-aligned values)
        self.stats_unnamed_text_label = QLabel("Unnamed galleries:")
        self.stats_unnamed_value_label = QLabel("0")
        self.stats_total_galleries_text_label = QLabel("Galleries uploaded:")
        self.stats_total_galleries_value_label = QLabel("0")
        self.stats_total_images_text_label = QLabel("Images uploaded:")
        self.stats_total_images_value_label = QLabel("0")
        #self.stats_current_speed_label = QLabel("Current speed: 0.0 KiB/s")
        #self.stats_fastest_speed_label = QLabel("Fastest speed: 0.0 KiB/s")
        for lbl in (
            self.stats_unnamed_text_label,
            self.stats_total_galleries_text_label,
            self.stats_total_images_text_label,
        ):
            try:
                pal = self.palette()
                bg = pal.window().color()
                is_dark = (0.2126 * bg.redF() + 0.7152 * bg.greenF() + 0.0722 * bg.blueF()) < 0.5
            except Exception:
                is_dark = False
            lbl.setStyleSheet(f"color: {'#dddddd' if is_dark else '#333333'};")
        for lbl in (
            self.stats_unnamed_value_label,
            self.stats_total_galleries_value_label,
            self.stats_total_images_value_label,
        ):
            try:
                pal = self.palette()
                bg = pal.window().color()
                is_dark = (0.2126 * bg.redF() + 0.7152 * bg.greenF() + 0.0722 * bg.blueF()) < 0.5
            except Exception:
                is_dark = False
            lbl.setStyleSheet(f"color: {'#eeeeee' if is_dark else '#333333'};")
            try:
                lbl.setFont(QFont("Consolas", 10))
            except Exception:
                pass
            try:
                lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            except Exception:
                pass
        # Arrange in two columns, three rows
        stats_layout.addWidget(self.stats_unnamed_text_label, 0, 0)
        stats_layout.addWidget(self.stats_unnamed_value_label, 0, 1)
        stats_layout.addWidget(self.stats_total_galleries_text_label, 1, 0)
        stats_layout.addWidget(self.stats_total_galleries_value_label, 1, 1)
        stats_layout.addWidget(self.stats_total_images_text_label, 2, 0)
        stats_layout.addWidget(self.stats_total_images_value_label, 2, 1)
        #stats_layout.addWidget(self.stats_current_speed_label, 1, 1)
        #stats_layout.addWidget(self.stats_fastest_speed_label, 2, 1)
        
        # Keep bottom short like the original progress box; fix width to avoid jitter
        stats_group.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        try:
            stats_group.setFixedWidth(260)
        except Exception:
            pass
        stats_group.setMinimumWidth(160)
        stats_group.setMaximumHeight(100)

        bottom_layout.addWidget(stats_group, 1)

        speed_group = QGroupBox("Speed")
        speed_layout = QGridLayout(speed_group)
        try:
            speed_layout.setContentsMargins(10, 10, 10, 10)
            speed_layout.setHorizontalSpacing(12)
            speed_layout.setVerticalSpacing(8)
        except Exception:
            pass
        
        # Detailed speed labels (split into label and value for right-aligned values)
        self.speed_current_text_label = QLabel("Current:")
        self.speed_current_value_label = QLabel("0.0 KiB/s")
        self.speed_fastest_text_label = QLabel("Fastest:")
        self.speed_fastest_value_label = QLabel("0.0 KiB/s")
        self.speed_transferred_text_label = QLabel("Transferred:")
        self.speed_transferred_value_label = QLabel("0 B")
        for lbl in (
            self.speed_current_text_label,
            self.speed_fastest_text_label,
            self.speed_transferred_text_label,
        ):
            try:
                pal = self.palette()
                bg = pal.window().color()
                is_dark = (0.2126 * bg.redF() + 0.7152 * bg.greenF() + 0.0722 * bg.blueF()) < 0.5
            except Exception:
                is_dark = False
            lbl.setStyleSheet(f"color: {'#dddddd' if is_dark else '#333333'};")
        for lbl in (
            self.speed_current_value_label,
            self.speed_fastest_value_label,
            self.speed_transferred_value_label,
        ):
            try:
                pal = self.palette()
                bg = pal.window().color()
                is_dark = (0.2126 * bg.redF() + 0.7152 * bg.greenF() + 0.0722 * bg.blueF()) < 0.5
            except Exception:
                is_dark = False
            lbl.setStyleSheet(f"color: {'#eeeeee' if is_dark else '#333333'};")
            try:
                lbl.setFont(QFont("Consolas", 10))
            except Exception:
                pass
            try:
                lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            except Exception:
                pass

        # Make current transfer speed value 1px larger than others
        try:
            self.speed_current_value_label.setFont(QFont("Consolas", 11))
        except Exception:
            pass

        speed_layout.addWidget(self.speed_current_text_label, 0, 0)
        speed_layout.addWidget(self.speed_current_value_label, 0, 1)
        speed_layout.addWidget(self.speed_fastest_text_label, 1, 0)
        speed_layout.addWidget(self.speed_fastest_value_label, 1, 1)
        speed_layout.addWidget(self.speed_transferred_text_label, 2, 0)
        speed_layout.addWidget(self.speed_transferred_value_label, 2, 1)

        
        # Keep bottom short like the original progress box; fix width to avoid jitter
        speed_group.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        try:
            speed_group.setFixedWidth(200)
        except Exception:
            pass
        speed_group.setMaximumHeight(100)
        bottom_layout.addWidget(speed_group, 1)

        main_layout.addLayout(bottom_layout)
        # Ensure the top section takes remaining space and bottom stays compact
        try:
            main_layout.setStretch(0, 1)  # top_layout
            main_layout.setStretch(1, 0)  # bottom_layout
        except Exception:
            pass
        
    def setup_menu_bar(self):
        """Create a simple application menu bar."""
        try:
            menu_bar = self.menuBar()

            # File menu
            file_menu = menu_bar.addMenu("File")
            action_add = file_menu.addAction("Add Folders...")
            action_add.triggered.connect(self.browse_for_folders)
            file_menu.addSeparator()
            action_start_all = file_menu.addAction("Start All")
            action_start_all.triggered.connect(self.start_all_uploads)
            action_pause_all = file_menu.addAction("Pause All")
            action_pause_all.triggered.connect(self.pause_all_uploads)
            action_clear_completed = file_menu.addAction("Clear Completed")
            action_clear_completed.triggered.connect(self.clear_completed)
            file_menu.addSeparator()
            action_exit = file_menu.addAction("Exit")
            action_exit.triggered.connect(self.close)

            # View menu
            view_menu = menu_bar.addMenu("View")
            action_log = view_menu.addAction("Open Log Viewer")
            action_log.triggered.connect(self.open_log_viewer)
            # Theme submenu: System / Light / Dark
            theme_menu = view_menu.addMenu("Theme")
            theme_group = QActionGroup(self)
            theme_group.setExclusive(True)
            self._theme_action_system = theme_menu.addAction("System")
            self._theme_action_system.setCheckable(True)
            self._theme_action_light = theme_menu.addAction("Light")
            self._theme_action_light.setCheckable(True)
            self._theme_action_dark = theme_menu.addAction("Dark")
            self._theme_action_dark.setCheckable(True)
            theme_group.addAction(self._theme_action_system)
            theme_group.addAction(self._theme_action_light)
            theme_group.addAction(self._theme_action_dark)
            self._theme_action_system.triggered.connect(lambda: self.set_theme_mode('system'))
            self._theme_action_light.triggered.connect(lambda: self.set_theme_mode('light'))
            self._theme_action_dark.triggered.connect(lambda: self.set_theme_mode('dark'))
            # Initialize checked state from settings
            current_theme = str(self.settings.value('ui/theme', 'system'))
            if current_theme == 'light':
                self._theme_action_light.setChecked(True)
            elif current_theme == 'dark':
                self._theme_action_dark.setChecked(True)
            else:
                self._theme_action_system.setChecked(True)

            # Tools menu
            tools_menu = menu_bar.addMenu("Tools")
            action_templates = tools_menu.addAction("Manage BBCode Templates")
            action_templates.triggered.connect(self.manage_templates)
            action_credentials = tools_menu.addAction("Manage Credentials")
            action_credentials.triggered.connect(self.manage_credentials)
            action_locations = tools_menu.addAction("Manage File Locations")
            action_locations.triggered.connect(self.manage_file_locations)

            # Authentication submenu
            auth_menu = tools_menu.addMenu("Authentication")
            action_retry_login = auth_menu.addAction("Reattempt Login")
            action_retry_login.triggered.connect(lambda: self.retry_login(False))
            action_retry_login_creds = auth_menu.addAction("Reattempt Login (Credentials Only)")
            action_retry_login_creds.triggered.connect(lambda: self.retry_login(True))

            # Windows context menu integration
            context_menu = tools_menu.addMenu("Windows Explorer Integration")
            action_install_ctx = context_menu.addAction("Install Context Menu…")
            action_install_ctx.triggered.connect(self.install_context_menu)
            action_remove_ctx = context_menu.addAction("Remove Context Menu…")
            action_remove_ctx.triggered.connect(self.remove_context_menu)

            # Help menu
            help_menu = menu_bar.addMenu("Help")
            action_help = help_menu.addAction("Help")
            action_help.triggered.connect(self.open_help_dialog)
            action_about = help_menu.addAction("About")
            action_about.triggered.connect(self.show_about_dialog)
        except Exception:
            # If menu bar creation fails, continue without it
            pass

    def show_about_dialog(self):
        """Show a minimal About dialog."""
        try:
            from imxup import __version__
            version = f"{__version__}"
        except Exception:
            version = ""
        text = "IMX.to Gallery Uploader"
        if version:
            text = f"{text}\n\nVersion {version}\n\nCopyright © 2025, twat\n\nLicense: Apache 2.0\n\nIMX.to name and logo are property of IMX.to. Use of the IMX.to service is subject to their terms of service:\nhttps://imx.to/page/terms"
        try:
            QMessageBox.about(self, "About", text)
        except Exception:
            # Fallback if about() not available
            QMessageBox.information(self, "About", text)

    def check_credentials(self):
        """Prompt to set credentials only if API key is not set."""
        if not api_key_is_set():
            dialog = CredentialSetupDialog(self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.add_log_message(f"{timestamp()} [auth] Credentials saved securely")
            else:
                self.add_log_message(f"{timestamp()} [auth] Credential setup cancelled")
        else:
            self.add_log_message(f"{timestamp()} [auth] API key found; skipping credential setup dialog")
    
    def retry_login(self, credentials_only: bool = False):
        """Ask the worker to retry login soon (optionally credentials-only)."""
        try:
            if self.worker is None or not self.worker.isRunning():
                self.add_log_message(f"{timestamp()} [auth] Worker not running; starting worker first")
                self.start_worker()
            if self.worker is not None:
                self.worker.request_retry_login(credentials_only)
                self.add_log_message(f"{timestamp()} [auth] Queued login reattempt{' (credentials only)' if credentials_only else ''}")
        except Exception as e:
            try:
                self.add_log_message(f"{timestamp()} [auth] Failed to queue login retry: {e}")
            except Exception:
                pass

    def install_context_menu(self):
        """Install Windows Explorer context menu integration."""
        try:
            ok = create_windows_context_menu()
            if ok:
                QMessageBox.information(self, "Context Menu", "Windows Explorer context menu installed successfully.")
                self.add_log_message(f"{timestamp()} [system] Installed Windows context menu")
            else:
                QMessageBox.warning(self, "Context Menu", "Failed to install Windows Explorer context menu.")
                self.add_log_message(f"{timestamp()} [system] Failed to install Windows context menu")
        except Exception as e:
            QMessageBox.warning(self, "Context Menu", f"Error installing context menu: {e}")
            try:
                self.add_log_message(f"{timestamp()} [system] Error installing context menu: {e}")
            except Exception:
                pass

    def remove_context_menu(self):
        """Remove Windows Explorer context menu integration."""
        try:
            ok = remove_windows_context_menu()
            if ok:
                QMessageBox.information(self, "Context Menu", "Windows Explorer context menu removed successfully.")
                self.add_log_message(f"{timestamp()} [system] Removed Windows context menu")
            else:
                QMessageBox.warning(self, "Context Menu", "Failed to remove Windows Explorer context menu.")
                self.add_log_message(f"{timestamp()} [system] Failed to remove Windows context menu")
        except Exception as e:
            QMessageBox.warning(self, "Context Menu", f"Error removing context menu: {e}")
            try:
                self.add_log_message(f"{timestamp()} [system] Error removing context menu: {e}")
            except Exception:
                pass
    
    def manage_templates(self):
        """Open template management dialog"""
        # Get current template from combo box
        current_template = self.template_combo.currentText()
        dialog = TemplateManagerDialog(self, current_template)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Refresh template combo box and keep selection when possible
            self.refresh_template_combo(preferred=current_template)

    def manage_file_locations(self):
        """Open dialog to manage artifact storage locations and central path."""
        try:
            dialog = QDialog(self)
            dialog.setWindowTitle("Manage File Locations")
            dialog.setModal(True)
            dialog.resize(600, 220)

            vbox = QVBoxLayout(dialog)

            # Informational section (theme-aware for readability)
            info_text = QLabel()
            info_text.setWordWrap(True)
            try:
                pal = dialog.palette()
                bg = pal.window().color()
                is_dark = (0.2126 * bg.redF() + 0.7152 * bg.greenF() + 0.0722 * bg.blueF()) < 0.5
            except Exception:
                is_dark = False
            panel_bg = "#2e2e2e" if is_dark else "#f0f8ff"
            panel_border = "#444444" if is_dark else "#cccccc"
            text_color = "#dddddd" if is_dark else "#333333"
            info_text.setStyleSheet(f"padding: 10px; background-color: {panel_bg}; border: 1px solid {panel_border}; border-radius: 5px; color: {text_color};")
            vbox.addWidget(info_text)

            # Options group
            group = QGroupBox("Storage Options")
            grid = QGridLayout(group)

            # Checkboxes mirror hidden settings checkboxes
            uploaded_check = QCheckBox("Save artifacts in .uploaded folder")
            uploaded_check.setChecked(self.store_in_uploaded_check.isChecked())
            grid.addWidget(uploaded_check, 0, 0, 1, 2)

            central_check = QCheckBox("Save artifacts in central store")
            central_check.setChecked(self.store_in_central_check.isChecked())
            grid.addWidget(central_check, 1, 0, 1, 2)

            # Central store path selector
            from imxup import (
                get_central_store_base_path,
                get_default_central_store_base_path,
            )
            current_path = self.central_store_path_value or get_central_store_base_path()

            path_label = QLabel("Central store path:")
            path_edit = QLineEdit(current_path)
            path_edit.setReadOnly(True)
            browse_btn = QPushButton("Browse…")
            open_btn = QPushButton("Open Central Store")

            def on_browse():
                directory = QFileDialog.getExistingDirectory(dialog, "Select Central Store Directory", current_path, QFileDialog.Option.ShowDirsOnly)
                if directory:
                    path_edit.setText(directory)

            browse_btn.clicked.connect(on_browse)

            grid.addWidget(path_label, 2, 0)
            grid.addWidget(path_edit, 2, 1)
            grid.addWidget(browse_btn, 2, 2)
            grid.addWidget(open_btn, 2, 3)

            def set_path_controls_enabled(enabled: bool):
                path_label.setEnabled(enabled)
                path_edit.setEnabled(enabled)
                browse_btn.setEnabled(enabled)
                open_btn.setEnabled(enabled)

            set_path_controls_enabled(central_check.isChecked())
            central_check.toggled.connect(set_path_controls_enabled)

            # Dynamic info text
            def update_info_label():
                base = path_edit.text().strip() or get_central_store_base_path() or get_default_central_store_base_path()
                galleries_path = os.path.join(base, "galleries")
                templates_path = os.path.join(base, "templates")
                info_text.setText(
                    "Galleries and templates are stored in the central store:\n\n"
                    f"Galleries folder: {galleries_path}\n"
                    f"Templates folder: {templates_path}\n\n"
                    f"Default base path (if unset): {get_default_central_store_base_path()}"
                )

            update_info_label()
            # Update info when path changes via browse or programmatically
            path_edit.textChanged.connect(lambda _=None: update_info_label())

            # Open in OS file browser
            def on_open_folder():
                base = path_edit.text().strip() or get_central_store_base_path()
                try:
                    os.makedirs(base, exist_ok=True)
                except Exception:
                    pass
                QDesktopServices.openUrl(QUrl.fromLocalFile(base))

            open_btn.clicked.connect(on_open_folder)

            vbox.addWidget(group)

            # Buttons (match credentials dialog layout)
            button_layout = QHBoxLayout()
            button_layout.addStretch()
            save_btn = QPushButton("Save")
            if not save_btn.text().startswith(" "):
                save_btn.setText(" " + save_btn.text())
            close_btn = QPushButton("Close")
            if not close_btn.text().startswith(" "):
                close_btn.setText(" " + close_btn.text())
            button_layout.addWidget(save_btn)
            button_layout.addWidget(close_btn)
            vbox.addLayout(button_layout)

            def on_save():
                # Push values back to hidden settings and mark settings dirty
                self.store_in_uploaded_check.setChecked(uploaded_check.isChecked())
                self.store_in_central_check.setChecked(central_check.isChecked())
                self.central_store_path_value = path_edit.text().strip()
                self.on_setting_changed()
                dialog.accept()

            def on_close():
                dialog.reject()

            save_btn.clicked.connect(on_save)
            close_btn.clicked.connect(on_close)

            dialog.exec()
        except Exception as e:
            try:
                self.add_log_message(f"{timestamp()} Error opening File Locations dialog: {e}")
            except Exception:
                pass

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

    def set_theme_mode(self, mode: str):
        """Switch theme mode and persist. mode in {'system','light','dark'}."""
        try:
            mode = mode if mode in ('system','light','dark') else 'system'
            self.settings.setValue('ui/theme', mode)
            self.apply_theme(mode)
            # Update checked menu items if available
            try:
                if mode == 'light':
                    self._theme_action_light.setChecked(True)
                elif mode == 'dark':
                    self._theme_action_dark.setChecked(True)
                else:
                    self._theme_action_system.setChecked(True)
            except Exception:
                pass
        except Exception:
            pass

    def apply_theme(self, mode: str):
        """Apply theme. 'system' uses palette-based inference; 'light'/'dark' set an application stylesheet.
        Only adjusts high-level palette/stylesheet so existing widgets that consult palette keep working.
        """
        try:
            app = QApplication.instance()
            if app is None:
                return
            if mode == 'dark':
                # Simple dark palette and base stylesheet
                palette = app.palette()
                try:
                    palette.setColor(palette.ColorRole.Window, QColor(30,30,30))
                    palette.setColor(palette.ColorRole.WindowText, QColor(230,230,230))
                    palette.setColor(palette.ColorRole.Base, QColor(25,25,25))
                    palette.setColor(palette.ColorRole.Text, QColor(230,230,230))
                    palette.setColor(palette.ColorRole.Button, QColor(45,45,45))
                    palette.setColor(palette.ColorRole.ButtonText, QColor(230,230,230))
                    palette.setColor(palette.ColorRole.Highlight, QColor(47,106,160))
                    palette.setColor(palette.ColorRole.HighlightedText, QColor(255,255,255))
                except Exception:
                    pass
                app.setPalette(palette)
                app.setStyleSheet("""
                    QWidget { color: #e6e6e6; }
                    QToolTip { color: #e6e6e6; background-color: #333333; border: 1px solid #555; }
                """)
            elif mode == 'light':
                palette = app.palette()
                try:
                    palette.setColor(palette.ColorRole.Window, QColor(255,255,255))
                    palette.setColor(palette.ColorRole.WindowText, QColor(33,33,33))
                    palette.setColor(palette.ColorRole.Base, QColor(255,255,255))
                    palette.setColor(palette.ColorRole.Text, QColor(33,33,33))
                    palette.setColor(palette.ColorRole.Button, QColor(245,245,245))
                    palette.setColor(palette.ColorRole.ButtonText, QColor(33,33,33))
                    palette.setColor(palette.ColorRole.Highlight, QColor(41,128,185))
                    palette.setColor(palette.ColorRole.HighlightedText, QColor(255,255,255))
                except Exception:
                    pass
                app.setPalette(palette)
                app.setStyleSheet("")
            else:
                # system: clear stylesheet so platform theme/palette prevail
                app.setStyleSheet("")
                # Leave palette as-is (system)
            self._current_theme_mode = mode
            # Trigger a light refresh on key widgets
            try:
                self.update_queue_display()
            except Exception:
                pass
        except Exception:
            pass

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
            self.worker.gallery_renamed.connect(self.on_gallery_renamed)
            self.worker.log_message.connect(self.add_log_message)
            self.worker.bandwidth_updated.connect(self.on_bandwidth_updated)
            self.worker.queue_stats.connect(self.on_queue_stats)
            self.worker.start()
            self.add_log_message(f"{timestamp()} [general] Worker thread started")
            # Propagate auto-rename preference to worker
            try:
                self.worker.auto_rename_enabled = self.auto_rename_check.isChecked()
            except Exception:
                pass

    def on_bandwidth_updated(self, kbps: float):
        """Receive current aggregate bandwidth from worker (KB/s)."""
        self._current_transfer_kbps = kbps

    def on_queue_stats(self, stats: dict):
        """Render aggregate queue stats beneath the overall progress bar.
        Example: "1 uploading (100 images / 111 MB) • 12 queued (912 images / 1.9 GB) • 4 ready (192 images / 212 MB) • 63 completed (2245 images / 1.5 GB)"
        """
        try:
            def fmt_section(label: str, s: dict) -> str:
                count = int(s.get('count', 0) or 0)
                if count <= 0:
                    return ""
                images = int(s.get('images', 0) or 0)
                by = int(s.get('bytes', 0) or 0)
                try:
                    from imxup import format_binary_size
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
            self.stats_label.setText(" • ".join(parts) if parts else "No galleries in queue")
        except Exception:
            # Fall back to previous text if formatting fails
            pass
    
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
        """Add folders to the upload queue efficiently"""
        if len(folder_paths) == 1:
            # Single folder - use the old method for backward compatibility
            self._add_single_folder(folder_paths[0])
        else:
            # Multiple folders - use the new efficient method
            self._add_multiple_folders(folder_paths)
    
    def _add_single_folder(self, path: str):
        """Add a single folder using the old method."""
        template_name = self.template_combo.currentText()
        result = self.queue_manager.add_item(path, template_name=template_name)
        
        if result == True:
            self.add_log_message(f"{timestamp()} [queue] Added to queue: {os.path.basename(path)}")
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
                self.add_log_message(f"{timestamp()} [queue] Added to queue (user confirmed): {os.path.basename(path)}")
            else:
                self.add_log_message(f"{timestamp()} [queue] Skipped: {os.path.basename(path)} (user cancelled)")
        else:
            self.add_log_message(f"{timestamp()} [queue] Failed to add: {os.path.basename(path)} (no images or already in queue)")
        
        self.update_queue_display()
    
    def _add_multiple_folders(self, folder_paths: List[str]):
        """Add multiple folders efficiently using the new method."""
        template_name = self.template_combo.currentText()
        
        # Show progress dialog for multiple folders
        progress = QProgressDialog("Adding galleries...", "Cancel", 0, len(folder_paths), self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setAutoClose(True)
        progress.setValue(0)
        
        try:
            # Use the new efficient method
            results = self.queue_manager.add_multiple_items(folder_paths, template_name)
            
            # Update progress
            progress.setValue(len(folder_paths))
            
            # Show results
            if results['added'] > 0:
                self.add_log_message(f"{timestamp()} [queue] Added {results['added']} galleries to queue")
            if results['duplicates'] > 0:
                self.add_log_message(f"{timestamp()} [queue] Skipped {results['duplicates']} duplicate galleries")
            if results['failed'] > 0:
                self.add_log_message(f"{timestamp()} [queue] Failed to add {results['failed']} galleries")
                # Show detailed errors if any
                for error in results['errors'][:5]:  # Show first 5 errors
                    self.add_log_message(f"{timestamp()} [queue] Error: {error}")
                if len(results['errors']) > 5:
                    self.add_log_message(f"{timestamp()} [queue] ... and {len(results['errors']) - 5} more errors")
            
            # Update display
            self.update_queue_display()
            
        except Exception as e:
            self.add_log_message(f"{timestamp()} [queue] Error adding multiple folders: {str(e)}")
        finally:
            progress.close()
    
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
        # Minimize UI stall for large refreshes
        try:
            prev_updates_enabled = self.gallery_table.updatesEnabled()
            prev_sorting_enabled = self.gallery_table.isSortingEnabled()
            self.gallery_table.setUpdatesEnabled(False)
            self.gallery_table.setSortingEnabled(False)
            self.gallery_table.blockSignals(True)
        except Exception:
            prev_updates_enabled = True
            prev_sorting_enabled = False
        
        
        # Determine theme for contrast-aware rendering
        try:
            pal = self.palette()
            _bg = pal.window().color()
            _is_dark_mode = (0.2126 * _bg.redF() + 0.7152 * _bg.greenF() + 0.0722 * _bg.blueF()) < 0.5
        except Exception:
            _is_dark_mode = False
        _light_fg = QColor(255, 255, 255)
        _dark_fg = QColor(0, 0, 0)

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
        
        
        # Load pending-rename map once for this refresh
        try:
            from imxup import get_unnamed_galleries
            _unnamed_map = get_unnamed_galleries()
        except Exception:
            _unnamed_map = {}
        
        # Populate the table with current items
        for row, item in enumerate(items):
            
            # Order number (numeric-sorting item)
            order_item = NumericTableWidgetItem(item.insertion_order)
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
            # Pseudo-center with compact font size (no monospacing)
            try:
                font = uploaded_item.font()
                font.setPointSize(8)
                uploaded_item.setFont(font)
            except Exception:
                pass
            uploaded_item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
            self.gallery_table.setItem(row, 2, uploaded_item)
            
            # Progress bar - always create fresh widget to avoid sorting issues
            progress_widget = TableProgressWidget()
            progress_widget.update_progress(item.progress, item.status)
            self.gallery_table.setCellWidget(row, 3, progress_widget)
            
            # Status: icon-only, no background/text
            self._set_status_cell_icon(row, item.status)
            
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
            
            # Size (from scanned total_size)
            size_text = ""
            try:
                from imxup import format_binary_size
                size_text = format_binary_size(int(getattr(item, 'total_size', 0) or 0), precision=2)
            except Exception:
                try:
                    size_text = f"{int(getattr(item, 'total_size', 0) or 0)} B"
                except Exception:
                    size_text = ""
            size_item = QTableWidgetItem(size_text)
            size_item.setFlags(size_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            try:
                font = size_item.font()
                font.setPointSize(8)
                size_item.setFont(font)
            except Exception:
                pass
            size_item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
            try:
                font = size_item.font()
                size_item.setFont(font)
            except Exception:
                pass
            self.gallery_table.setItem(row, 8, size_item)

            # Transfer speed
            # - Uploading: current_kibps live value
            # - Completed/Failed: final_kibps if present; else compute from uploaded_bytes and elapsed
            transfer_text = ""
            current_rate_kib = float(getattr(item, 'current_kibps', 0.0) or 0.0)
            final_rate_kib = float(getattr(item, 'final_kibps', 0.0) or 0.0)
            try:
                from imxup import format_binary_rate
                if item.status == "uploading" and current_rate_kib > 0:
                    transfer_text = format_binary_rate(current_rate_kib, precision=1)
                elif final_rate_kib > 0:
                    transfer_text = format_binary_rate(final_rate_kib, precision=1)
                else:
                    transfer_text = ""
            except Exception:
                # Fallback formatting
                rate = current_rate_kib if item.status == "uploading" else final_rate_kib
                transfer_text = f"{rate:.1f} KiB/s" if rate > 0 else ""
            xfer_item = QTableWidgetItem(transfer_text)
            xfer_item.setFlags(xfer_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            try:
                font = xfer_item.font()
                font.setPointSize(8)
                xfer_item.setFont(font)
            except Exception:
                pass
            xfer_item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
            try:
                # Active transfers bold and full opacity; completed/failed semi-opaque and not bold
                font = xfer_item.font()
                font.setPointSize(8)
                if item.status == "uploading" and transfer_text:
                    font.setBold(True)
                    xfer_item.setFont(font)
                    # Highlight active transfer in blue-ish to match header accent, keep contrast in both themes
                    xfer_item.setForeground(QColor(173, 216, 255, 255) if _is_dark_mode else QColor(20, 90, 150, 255))
                elif item.status in ("completed", "failed") and transfer_text:
                    font.setBold(False)
                    xfer_item.setFont(font)
                    # Slightly more opaque for finished items (+0.2 alpha)
                    xfer_item.setForeground(QColor(255, 255, 255, 230) if _is_dark_mode else QColor(0, 0, 0, 190))
            except Exception:
                pass
            self.gallery_table.setItem(row, 9, xfer_item)

            # Template name: center only if it fits; otherwise left-align so the start is visible
            template_text = item.template_name or ""
            tmpl_item = QTableWidgetItem(template_text)
            tmpl_item.setFlags(tmpl_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            try:
                col_width = self.gallery_table.columnWidth(10)
                fm = QFontMetrics(tmpl_item.font())
                text_w = fm.horizontalAdvance(template_text) + 8
                if text_w <= col_width:
                    tmpl_item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
                else:
                    tmpl_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            except Exception:
                tmpl_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            try:
                font = tmpl_item.font()
                font.setPointSize(8)
                tmpl_item.setFont(font)
            except Exception:
                pass
            self.gallery_table.setItem(row, 10, tmpl_item)

            # Renamed status: prefer icons (check/pending) if available; fallback to text
            try:
                is_renamed = None
                if item.gallery_id:
                    # If gallery_id is recorded as unnamed, then it's pending; otherwise when completed mark as renamed
                    if item.gallery_id in _unnamed_map:
                        is_renamed = False
                    elif item.status in ("completed", "failed"):
                        is_renamed = True
                self._set_renamed_cell_icon(row, is_renamed)
            except Exception:
                # Fallback: clear cell
                self._set_renamed_cell_icon(row, None)

            # Action buttons - always create fresh widget to avoid sorting issues
            action_widget = ActionButtonWidget()
            # Connect button signals with proper closure capture
            # Disable Start while scanning
            action_widget.start_btn.setEnabled(item.status != "scanning")
            action_widget.start_btn.clicked.connect(lambda checked, path=item.path: self.start_single_item(path))
            action_widget.stop_btn.clicked.connect(lambda checked, path=item.path: self.stop_single_item(path))
            action_widget.view_btn.clicked.connect(lambda checked, path=item.path: self.view_bbcode_files(path))
            action_widget.cancel_btn.clicked.connect(lambda checked, path=item.path: self.cancel_single_item(path))
            # Optional: use the pause action when item is uploading, cancel when queued
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
        
        # Enable/disable top-level controls and update counts on buttons
        try:
            count_startable = sum(1 for item in items if item.status in ("ready", "paused", "incomplete"))
            count_queued = sum(1 for item in items if item.status == "queued")
            count_completed = sum(1 for item in items if item.status == "completed")

            # Update button texts with counts (preserve leading space for visual alignment)
            self.start_all_btn.setText(f" Start All ({count_startable})")
            self.pause_all_btn.setText(f" Pause All ({count_queued})")
            self.clear_completed_btn.setText(f" Clear Completed ({count_completed})")

            # Enable/disable based on counts
            self.start_all_btn.setEnabled(count_startable > 0)
            self.pause_all_btn.setEnabled(count_queued > 0)
            self.clear_completed_btn.setEnabled(count_completed > 0)

            # Disable settings when any items are queued or uploading
            has_uploading = any(item.status == "uploading" for item in items)
            try:
                self.settings_group.setEnabled(not (count_queued > 0 or has_uploading))
            except Exception:
                pass
        except Exception:
            # Controls may not be initialized yet during early calls
            pass
        finally:
            # Restore table UI state
            try:
                self.gallery_table.blockSignals(False)
                self.gallery_table.setSortingEnabled(prev_sorting_enabled)
                self.gallery_table.setUpdatesEnabled(prev_updates_enabled)
            except Exception:
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
        # Update Stats and Speed box values
        try:
            from imxup import get_unnamed_galleries
            unnamed_count = len(get_unnamed_galleries())
        except Exception:
            unnamed_count = 0
        self.stats_unnamed_value_label.setText(f"{unnamed_count}")
        # Totals persisted in QSettings
        settings = QSettings("ImxUploader", "Stats")
        total_galleries = settings.value("total_galleries", 0, type=int)
        total_images_acc = settings.value("total_images", 0, type=int)
        # Prefer v2 string key to avoid int-size issues; fall back to legacy
        total_size_bytes_v2 = settings.value("total_size_bytes_v2", "0")
        try:
            total_size_acc = int(str(total_size_bytes_v2))
        except Exception:
            total_size_acc = settings.value("total_size_bytes", 0, type=int)
        fastest_kbps = settings.value("fastest_kbps", 0.0, type=float)
        self.stats_total_galleries_value_label.setText(f"{total_galleries}")
        self.stats_total_images_value_label.setText(f"{total_images_acc}")
        try:
            from imxup import format_binary_size
            total_size_str = format_binary_size(total_size_acc, precision=1)
        except Exception:
            total_size_str = f"{total_size_acc} B"
        # Show transferred in Speed
        try:
            self.speed_transferred_value_label.setText(f"{total_size_str}")
        except Exception:
            pass
        # Current transfer speed: 0 if no active uploads; else latest emitted from worker
        any_uploading = any(it.status == "uploading" for it in items)
        if not any_uploading:
            self._current_transfer_kbps = 0.0
        current_kibps = float(getattr(self, "_current_transfer_kbps", 0.0))
        try:
            from imxup import format_binary_rate
            current_speed_str = format_binary_rate(current_kibps, precision=1)
            fastest_speed_str = format_binary_rate(float(fastest_kbps), precision=1)
        except Exception:
            current_speed_str = f"{current_kibps:.1f} KiB/s"
            fastest_speed_str = f"{fastest_kbps:.1f} KiB/s"
        self.speed_current_value_label.setText(f"{current_speed_str}")
        self.speed_fastest_value_label.setText(f"{fastest_speed_str}")
        # Status summary text is updated via signal handlers to avoid timer-driven churn
    
    def on_gallery_started(self, path: str, total_images: int):
        """Handle gallery start"""
        with QMutexLocker(self.queue_manager.mutex):
            if path in self.queue_manager.items:
                item = self.queue_manager.items[path]
                item.total_images = total_images
                item.uploaded_images = 0
        
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
                
                # Update status cell (icon-only)
                current_status = item.status
                self._set_status_cell_icon(row, current_status)
                
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
                # Update live transfer speed based on bytes and elapsed since start_time
                try:
                    if item.start_time:
                        elapsed = max(time.time() - float(item.start_time), 0.001)
                        # current KiB/s across this item only
                        item.current_kibps = (float(getattr(item, 'uploaded_bytes', 0) or 0) / elapsed) / 1024.0
                except Exception:
                    pass

                # Do not override status here; worker owns authoritative status

                # Find and update the correct row in the table
                matched_row = None
                for row in range(self.gallery_table.rowCount()):
                    name_item = self.gallery_table.item(row, 1)  # Gallery name is now column 1
                    if name_item and name_item.data(Qt.ItemDataRole.UserRole) == path:
                        matched_row = row
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

                        # Update Transfer column (9)
                        try:
                            from imxup import format_binary_rate
                            rate_text = format_binary_rate(float(getattr(item, 'current_kibps', 0.0) or 0.0), precision=1)
                            if float(getattr(item, 'current_kibps', 0.0) or 0.0) <= 0:
                                rate_text = ""
                        except Exception:
                            rate = float(getattr(item, 'current_kibps', 0.0) or 0.0)
                            rate_text = f"{rate:.1f} KiB/s" if rate > 0 else ""
                        xfer_item = QTableWidgetItem(rate_text)
                        xfer_item.setFlags(xfer_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        xfer_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                        try:
                            font = xfer_item.font()
                            if rate_text:
                                font.setBold(True)
                                xfer_item.setFont(font)
                                xfer_item.setForeground(QColor(0, 0, 0, 255))
                            else:
                                font.setBold(False)
                                xfer_item.setFont(font)
                        except Exception:
                            pass
                        self.gallery_table.setItem(row, 9, xfer_item)

                        # Show icon-only status during in-progress
                        if 0 < progress_percent < 100:
                            self._set_status_cell_icon(row, item.status)
                        break

                # Update status if it's completed (100%)
                if progress_percent >= 100 and matched_row is not None:
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
                    # Final icon
                    self._set_status_cell_icon(matched_row, item.status)

                    # Update the finished time column
                    finished_dt = datetime.fromtimestamp(item.finished_time)
                    finished_text = finished_dt.strftime("%Y-%m-%d %H:%M:%S")
                    finished_item = QTableWidgetItem(finished_text)
                    finished_item.setFlags(finished_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    finished_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    finished_item.setFont(QFont("Arial", 8))  # Smaller font
                    self.gallery_table.setItem(matched_row, 6, finished_item)

                    # Compute and freeze final transfer speed for this item
                    try:
                        elapsed = max(float(item.finished_time or time.time()) - float(item.start_time or item.finished_time), 0.001)
                        item.final_kibps = (float(getattr(item, 'uploaded_bytes', 0) or 0) / elapsed) / 1024.0
                        item.current_kibps = 0.0
                        # Render Transfer column (9)
                        from imxup import format_binary_rate
                        final_text = format_binary_rate(item.final_kibps, precision=1) if item.final_kibps > 0 else ""
                    except Exception:
                        final_text = ""
                    xfer_item = QTableWidgetItem(final_text)
                    xfer_item.setFlags(xfer_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    xfer_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    try:
                        font = xfer_item.font()
                        font.setBold(False)
                        xfer_item.setFont(font)
                        if final_text:
                            xfer_item.setForeground(QColor(0, 0, 0, 160))
                    except Exception:
                        pass
                    self.gallery_table.setItem(matched_row, 9, xfer_item)
                    # Update Renamed icon at completion (may be finalized later via auto-rename)
                    try:
                        state = True if (item.gallery_id or "") else None
                        self._set_renamed_cell_icon(matched_row, state)
                    except Exception:
                        pass
                    # Update Size and Transfer columns without disk reads on GUI thread
                    try:
                        size_bytes = int(getattr(item, 'total_size', 0) or 0)
                        # Render Size col (8)
                        try:
                            from imxup import format_binary_size
                            size_text = format_binary_size(size_bytes, precision=2)
                        except Exception:
                            size_text = f"{size_bytes} B" if size_bytes else ""
                        size_item = QTableWidgetItem(size_text)
                        size_item.setFlags(size_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        size_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                        self.gallery_table.setItem(matched_row, 8, size_item)
                    except Exception:
                        pass
                    return
    
    def on_gallery_completed(self, path: str, results: dict):
        """Handle gallery completion"""
        with QMutexLocker(self.queue_manager.mutex):
            if path in self.queue_manager.items:
                item = self.queue_manager.items[path]
                # Sync counts with merged results to avoid inconsistent UI (e.g., 450/520 but 100%)
                total = int(results.get('total_images') or 0)
                success = int(results.get('successful_count') or len(results.get('images', [])))
                item.total_images = total or item.total_images
                item.uploaded_images = success
                # Mark as completed only if all succeeded; otherwise keep failed/incomplete state
                if success >= (total or success):
                    item.status = "completed"
                    item.progress = 100
                else:
                    # Partial success: progress proportional
                    item.status = item.status if item.status in ("failed", "incomplete") else "failed"
                    item.progress = int((success / max(total, 1)) * 100)
                item.gallery_url = results.get('gallery_url', '')
                item.gallery_id = results.get('gallery_id', '')
                item.finished_time = time.time()  # Set completion timestamp
                # Finalize transfer metrics
                try:
                    elapsed = max(float(item.finished_time or time.time()) - float(item.start_time or item.finished_time), 0.001)
                    item.final_kibps = (float(results.get('uploaded_size') or getattr(item, 'uploaded_bytes', 0) or 0) / elapsed) / 1024.0
                    item.current_kibps = 0.0
                except Exception:
                    pass
        
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
        try:
            from imxup import format_binary_size
            folder_size = format_binary_size(total_size, precision=1)
        except Exception:
            folder_size = f"{total_size} B"
        avg_width = (queue_item.avg_width if queue_item and getattr(queue_item, 'avg_width', 0) else 0) or results.get('avg_width', 0)
        avg_height = (queue_item.avg_height if queue_item and getattr(queue_item, 'avg_height', 0) else 0) or results.get('avg_height', 0)
        max_width = (queue_item.max_width if queue_item and getattr(queue_item, 'max_width', 0) else 0) or results.get('max_width', 0)
        max_height = (queue_item.max_height if queue_item and getattr(queue_item, 'max_height', 0) else 0) or results.get('max_height', 0)
        min_width = (queue_item.min_width if queue_item and getattr(queue_item, 'min_width', 0) else 0) or results.get('min_width', 0)
        min_height = (queue_item.min_height if queue_item and getattr(queue_item, 'min_height', 0) else 0) or results.get('min_height', 0)

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
                #'width': int(avg_width),
                #'height': int(avg_height),
                #'longest': int(max(avg_width, avg_height)),
                'longest': int(max(max_width, max_height)),
                'shortest': int(min(min_width, min_height)),
                'avg_width': int(avg_width),
                'avg_height': int(avg_height),

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
            
            # Save artifacts through shared core helper
            try:
                from imxup import save_gallery_artifacts
                written = save_gallery_artifacts(
                    folder_path=path,
                    results={
                        **results,
                    'started_at': datetime.fromtimestamp(self.queue_manager.items[path].start_time).strftime('%Y-%m-%d %H:%M:%S') if path in self.queue_manager.items and self.queue_manager.items[path].start_time else None,
                    'thumbnail_size': self.thumbnail_size_combo.currentIndex() + 1,
                    'thumbnail_format': self.thumbnail_format_combo.currentIndex() + 1,
                    'public_gallery': 1 if self.public_gallery_check.isChecked() else 0,
                        'parallel_batch_size': self.batch_size_spin.value(),
                    },
                    template_name=template_name,
                )
                try:
                    parts = []
                    if written.get('central'):
                        parts.append(f"central: {os.path.dirname(list(written['central'].values())[0])}")
                    if written.get('uploaded'):
                        parts.append(f"folder: {os.path.dirname(list(written['uploaded'].values())[0])}")
                    if parts:
                        self.add_log_message(f"{timestamp()} [fileio] Saved gallery files to {', '.join(parts)}")
                except Exception:
                    pass
            except Exception as e:
                self.add_log_message(f"{timestamp()} Artifact save error: {e}")
        
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
        try:
            from imxup import format_binary_size
            total_size_str = format_binary_size(total_size, precision=1)
        except Exception:
            total_size_str = f"{total_size} B"
        self.add_log_message(f"{timestamp()} Uploaded {successful_count} images ({total_size_str}) in {upload_time:.1f}s")
        # Update cumulative stats
        try:
            settings = QSettings("ImxUploader", "Stats")
            total_galleries = settings.value("total_galleries", 0, type=int) + 1
            total_images_acc = settings.value("total_images", 0, type=int) + successful_count
            # Read v2 string key; fall back to legacy numeric, then add this run's uploaded_size
            base_total_str = settings.value("total_size_bytes_v2", "0")
            try:
                base_total = int(str(base_total_str))
            except Exception:
                base_total = settings.value("total_size_bytes", 0, type=int)
            total_size_acc = base_total + int(results.get('uploaded_size', 0) or 0)
            # Current and fastest speeds in KB/s
            transfer_speed = float(results.get('transfer_speed', 0) or 0)
            current_kbps = transfer_speed / 1024.0
            fastest_kbps = settings.value("fastest_kbps", 0.0, type=float)
            if current_kbps > fastest_kbps:
                fastest_kbps = current_kbps
            settings.setValue("total_galleries", total_galleries)
            settings.setValue("total_images", total_images_acc)
            # Store as string to avoid platform int limits
            settings.setValue("total_size_bytes_v2", str(total_size_acc))
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
        
        json_count = sum(1 for f in existing_files if f.lower().endswith('.json'))
        message = f"Gallery '{gallery_name}' already exists with {json_count} .json file{'' if json_count == 1 else 's'}.\n\nContinue with upload anyway?"
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

    def on_gallery_renamed(self, gallery_id: str):
        """Mark cells for the given gallery_id as renamed (check icon)."""
        try:
            items = self.queue_manager.get_all_items()
            id_to_row = {}
            for row, item in enumerate(items):
                if item.gallery_id:
                    id_to_row[item.gallery_id] = row
            if gallery_id in id_to_row:
                row = id_to_row[gallery_id]
                self._set_renamed_cell_icon(row, True)
        except Exception:
            pass

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
        # Determine category and subtype for GUI gating and file logging
        category = "general"
        subtype = None
        try:
            # message may start with timestamp; strip it first for token parse
            head = message
            parts = message.split(" ", 1)
            if len(parts) > 1 and parts[0].count(":") == 2:
                head = parts[1]
            if head.startswith("[") and "]" in head:
                token = head[1:head.find("]")]
                bits = token.split(":")
                category = bits[0] or "general"
                subtype = bits[1] if len(bits) > 1 else None
        except Exception:
            pass

        # GUI visibility based on settings
        show_in_gui = True
        try:
            logger = get_logger()
            if not logger.should_emit_gui(category, logging.INFO):
                show_in_gui = False
            if category == "uploads" and show_in_gui:
                if subtype == "file" and not logger.should_log_upload_file_success("gui"):
                    show_in_gui = False
                if subtype == "gallery" and not logger.should_log_upload_gallery_success("gui"):
                    show_in_gui = False
        except Exception:
            pass

        # Append to GUI log without category tags and auto-follow
        if show_in_gui:
            try:
                display = message
                # Strip leading category tag [xxx] if present (after optional time)
                head = message
                prefix = ""
                parts = message.split(" ", 1)
                if len(parts) > 1 and parts[0].count(":") == 2:
                    prefix = parts[0] + " "
                    head = parts[1]
                if head.startswith("[") and "]" in head:
                    head = head[head.find("]") + 1:].lstrip()
                display = prefix + head
                # Append and auto-follow vertically; keep horizontal view at line start
                self.log_text.append(display)
                try:
                    cursor = self.log_text.textCursor()
                    cursor.movePosition(cursor.MoveOperation.End)
                    self.log_text.setTextCursor(cursor)
                    self.log_text.ensureCursorVisible()
                    # Reset horizontal scrollbar to show start of lines
                    hbar = self.log_text.horizontalScrollBar()
                    if hbar is not None:
                        hbar.setValue(hbar.minimum())
                except Exception:
                    pass
            except Exception:
                self.log_text.append(message)

        # Always write to centralized rolling logfile using category (file sink can be filtered separately)
        try:
            get_logger().log_to_file(message, level=logging.INFO, category=category)
        except Exception:
            pass
        # Retain long history; no aggressive trimming
        try:
            if getattr(self, "_log_viewer_dialog", None) is not None and self._log_viewer_dialog.isVisible():
                self._log_viewer_dialog.append_message(message)
        except Exception:
            pass

    def open_log_viewer(self):
        """Open or focus the popout log viewer dialog"""
        try:
            if self._log_viewer_dialog is None or not self._log_viewer_dialog.isVisible():
                # Initialize with current on-disk log if available, otherwise current GUI text
                try:
                    initial_text = get_logger().read_current_log(tail_bytes=2 * 1024 * 1024) or self.log_text.toPlainText()
                except Exception:
                    initial_text = self.log_text.toPlainText()
                self._log_viewer_dialog = LogViewerDialog(initial_text, self)
                self._log_viewer_dialog.show()
            else:
                self._log_viewer_dialog.activateWindow()
                self._log_viewer_dialog.raise_()
        except Exception:
            pass
    
    def start_single_item(self, path: str):
        """Start a single item"""
        if self.queue_manager.start_item(path):
            self.add_log_message(f"{timestamp()} [queue] Started: {os.path.basename(path)}")
            self.update_queue_display()
        else:
            self.add_log_message(f"{timestamp()} [queue] Failed to start: {os.path.basename(path)}")
    
    def pause_single_item(self, path: str):
        """Pause a single item"""
        if self.queue_manager.pause_item(path):
            self.add_log_message(f"{timestamp()} [queue] Paused: {os.path.basename(path)}")
            self.update_queue_display()
        else:
            self.add_log_message(f"{timestamp()} [queue] Failed to pause: {os.path.basename(path)}")
    
    def stop_single_item(self, path: str):
        """Mark current uploading item to finish in-flight transfers, then become incomplete."""
        if self.worker and self.worker.current_item and self.worker.current_item.path == path:
            self.worker.request_soft_stop_current()
            # Optimistically reflect intent in UI without persisting as failed later
            self.queue_manager.update_item_status(path, "incomplete")
            self.update_queue_display()
            self.add_log_message(f"{timestamp()} [queue] Will stop after current transfers: {os.path.basename(path)}")
        else:
            # If not the actively uploading one, nothing to do
            self.add_log_message(f"{timestamp()} [queue] Stop requested but item not currently uploading: {os.path.basename(path)}")
        # Ensure controls reflect latest state promptly
        self.update_queue_display()
    
    def cancel_single_item(self, path: str):
        """Cancel a queued item and put it back to ready state"""
        with QMutexLocker(self.queue_manager.mutex):
            if path in self.queue_manager.items:
                item = self.queue_manager.items[path]
                if item.status == "queued":
                    item.status = "ready"
                    self.add_log_message(f"{timestamp()} [queue] Canceled queued item: {os.path.basename(path)}")
        
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
        """Clear completed uploads from queue with minimal UI work"""
        try:
            self.clear_completed_btn.setEnabled(False)
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        except Exception:
            pass
        # Pause periodic updates to avoid contention
        try:
            self.update_timer.stop()
        except Exception:
            pass
        try:
            # Pre-check counts for diagnostics
            items_snapshot = self.queue_manager.get_all_items()
            count_completed = sum(1 for it in items_snapshot if it.status == "completed")
            count_failed = sum(1 for it in items_snapshot if it.status == "failed")
            self.add_log_message(f"{timestamp()} [queue] Attempting clear: completed={count_completed}, failed={count_failed}")

            removed_count = self.queue_manager.clear_completed()
            # Fallback: if nothing removed but UI shows completed, try explicit path removal
            if removed_count == 0 and (count_completed or count_failed):
                comp_paths = [it.path for it in items_snapshot if it.status in ("completed", "failed")]
                if comp_paths:
                    self.add_log_message(f"{timestamp()} [queue] Retrying clear via explicit path delete for {len(comp_paths)} item(s)")
                    try:
                        removed_count = self.queue_manager.remove_items(comp_paths)
                    except Exception:
                        removed_count = 0
            if removed_count > 0:
                self.update_queue_display()
                self.add_log_message(f"{timestamp()} [queue] Cleared {removed_count} completed uploads")
                # Persist in the background
                self.queue_manager.save_persistent_queue()
            else:
                self.add_log_message(f"{timestamp()} [queue] No completed uploads to clear")
        finally:
            try:
                self.update_timer.start(500)
                QApplication.restoreOverrideCursor()
                self.clear_completed_btn.setEnabled(True)
            except Exception:
                pass
    
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
                    self.add_log_message(f"{timestamp()} [queue] Deleted: {path}")
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
        # Restore table columns (widths and visibility)
        self.restore_table_settings()
        # Apply saved theme
        try:
            theme = str(self.settings.value('ui/theme', 'system'))
            self.apply_theme(theme)
        except Exception:
            pass
    
    def save_settings(self):
        """Save window settings"""
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("confirm_delete", self.confirm_delete_check.isChecked())
        self.save_table_settings()

    def save_table_settings(self):
        """Persist table column widths, visibility, and order to settings"""
        try:
            column_count = self.gallery_table.columnCount()
            widths = [self.gallery_table.columnWidth(i) for i in range(column_count)]
            visibility = [not self.gallery_table.isColumnHidden(i) for i in range(column_count)]
            # Persist header order (visual indices by logical section)
            header = self.gallery_table.horizontalHeader()
            order = [header.visualIndex(i) for i in range(column_count)]
            self.settings.setValue("table/column_widths", json.dumps(widths))
            self.settings.setValue("table/column_visible", json.dumps(visibility))
            self.settings.setValue("table/column_order", json.dumps(order))
        except Exception:
            pass

    def restore_table_settings(self):
        """Restore table column widths, visibility, and order from settings"""
        try:
            column_count = self.gallery_table.columnCount()
            widths_raw = self.settings.value("table/column_widths")
            visible_raw = self.settings.value("table/column_visible")
            order_raw = self.settings.value("table/column_order")
            if widths_raw:
                try:
                    widths = json.loads(widths_raw)
                    for i in range(min(column_count, len(widths))):
                        if isinstance(widths[i], int) and widths[i] > 0:
                            self.gallery_table.setColumnWidth(i, widths[i])
                except Exception:
                    pass
            if visible_raw:
                try:
                    visible = json.loads(visible_raw)
                    for i in range(min(column_count, len(visible))):
                        self.gallery_table.setColumnHidden(i, not bool(visible[i]))
                except Exception:
                    pass
            if order_raw:
                try:
                    header = self.gallery_table.horizontalHeader()
                    order = json.loads(order_raw)
                    # order is list of visualIndex for each logical section; apply by moving sections
                    # Build inverse mapping target_visual_index -> logical
                    target_visual_to_logical = {v: i for i, v in enumerate(order) if isinstance(v, int)}
                    # Move sections in order of target visual positions
                    for target_visual in range(min(column_count, len(order))):
                        logical = target_visual_to_logical.get(target_visual)
                        if logical is None:
                            continue
                        current_visual = header.visualIndex(logical)
                        if current_visual != target_visual:
                            header.moveSection(current_visual, target_visual)
                except Exception:
                    pass
        except Exception:
            pass

    def _on_header_section_resized(self, logicalIndex, oldSize, newSize):
        """Save widths on resize events"""
        self.save_table_settings()

    def _on_any_section_resized(self, logicalIndex, oldSize, newSize):
        """Auto-expand Gallery Name column to absorb available space while staying interactive."""
        try:
            # Only respond to table's horizontal header resizes
            # Compute total width of all visible columns except Name column
            header = self.gallery_table.horizontalHeader()
            table_width = self.gallery_table.viewport().width()
            name_col = getattr(self, '_name_col_index', 1)
            visible_other_width = 0
            for col in range(self.gallery_table.columnCount()):
                if col == name_col:
                    continue
                if not self.gallery_table.isColumnHidden(col):
                    visible_other_width += self.gallery_table.columnWidth(col)
            available = max(table_width - visible_other_width - 2, 0)
            # Respect a minimum width recorded when user resizes the name column manually
            if logicalIndex == name_col and newSize != oldSize:
                # Update user-preferred minimum
                self._user_name_col_min_width = max(120, newSize)
            target = max(int(getattr(self, '_user_name_col_min_width', 300)), available)
            # Only expand; don't force shrink under user's chosen width
            current = self.gallery_table.columnWidth(name_col)
            if available > current and available > 0:
                self.gallery_table.setColumnWidth(name_col, available)
        except Exception:
            pass

    def _on_header_section_moved(self, logicalIndex, oldVisualIndex, newVisualIndex):
        """Persist order when user drags columns."""
        try:
            self.save_table_settings()
        except Exception:
            pass

    def show_header_context_menu(self, position):
        """Right-click on header: toggle column visibility"""
        from PyQt6.QtWidgets import QMenu
        header = self.gallery_table.horizontalHeader()
        menu = QMenu(self)
        for col in range(self.gallery_table.columnCount()):
            header_item = self.gallery_table.horizontalHeaderItem(col)
            title = header_item.text() if header_item else f"Column {col}"
            action = menu.addAction(title)
            action.setCheckable(True)
            action.setChecked(not self.gallery_table.isColumnHidden(col))
            action.triggered.connect(lambda checked, c=col: self._set_column_visibility(c, checked))
        global_pos = header.mapToGlobal(position)
        if menu.actions():
            menu.exec(global_pos)

    def _set_column_visibility(self, column_index: int, visible: bool):
        self.gallery_table.setColumnHidden(column_index, not visible)
        # Let our name-column auto-expand handle whitespace on next layout pass
        try:
            self.gallery_table.auto_expand_name_column()
        except Exception:
            pass
        self.save_table_settings()
    
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
            central_store_path = (self.central_store_path_value or "").strip()
            
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
            # Persist central store path (empty string implies default)
            config['DEFAULTS']['central_store_path'] = central_store_path
            
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
        
        if event.mimeData().hasUrls():
            
            event.acceptProposedAction()
        else:
            
            event.ignore()
    
    def dragMoveEvent(self, event):
        """Handle drag move"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()
    
    def dragLeaveEvent(self, event):
        """Handle drag leave"""
        
    
    def dropEvent(self, event):
        """Handle drop - EXACTLY like your working test"""
        
        
        if event.mimeData().hasUrls():
            
            urls = event.mimeData().urls()
            paths = []
            for url in urls:
                path = url.toLocalFile()
                
                if os.path.isdir(path):
                    
                    paths.append(path)
            
            if paths:
                
                self.add_folders(paths)
                event.acceptProposedAction()
            else:
                
                event.ignore()
        else:
            
            event.ignore()

    def closeEvent(self, event):
        """Handle window close"""
        self.save_settings()
        
        # Save queue state
        self.queue_manager.save_persistent_queue()
        
        # Shutdown scan worker gracefully
        if self.queue_manager:
            self.queue_manager.shutdown()
        
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