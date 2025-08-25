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
from typing import Callable, Tuple
from contextlib import contextmanager
import weakref

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QListWidget, QListWidgetItem, QPushButton, QProgressBar, QLabel, 
    QGroupBox, QSplitter, QTextEdit, QComboBox, QSpinBox, QCheckBox,
    QMessageBox, QSystemTrayIcon, QMenu, QFrame, QScrollArea,
    QGridLayout, QSizePolicy, QTabWidget, QTabBar, QFileDialog, QTableWidget,
    QTableWidgetItem, QHeaderView, QDialog, QDialogButtonBox, QPlainTextEdit,
    QLineEdit, QInputDialog, QSpacerItem, QStyle, QAbstractItemView,
    QProgressDialog
)
from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QTimer, QMimeData, QUrl, 
    QMutex, QMutexLocker, QSettings, QSize, QObject, pyqtSlot,
    QRunnable, QThreadPool, QPoint
)
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QIcon, QFont, QPixmap, QPainter, QColor, QSyntaxHighlighter, QTextCharFormat, QDesktopServices, QPainterPath, QPen, QFontMetrics, QTextDocument, QActionGroup, QDrag

# Import the core uploader functionality
from imxup import ImxToUploader, load_user_defaults, timestamp, sanitize_gallery_name, encrypt_password, decrypt_password, rename_all_unnamed_with_session, get_config_path, build_gallery_filenames, get_central_storage_path
from imxup import create_windows_context_menu, remove_windows_context_menu
from imxup_splash import SplashScreen


from imxup_core import UploadEngine
from imxup_storage import QueueStore
from imxup_logging import get_logger
from imxup_settings import ComprehensiveSettingsDialog
from imxup_tab_manager import TabManager
from imxup_auto_archive import AutoArchiveEngine

# Import widget classes from module - starting with just TableProgressWidget
from imxup_widgets import TableProgressWidget

# Import queue manager classes - adding one at a time
from imxup_queue_manager import GalleryQueueItem, QueueManager

# Import background task classes one at a time
from imxup_background_tasks import (
    BackgroundTaskSignals, BackgroundTask, ProgressUpdateBatcher,
    IconCache, TableRowUpdateTask, TableUpdateQueue
)

# Import network classes
from imxup_network import GUIImxToUploader

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
        print(f"DEBUG: UploadWorker.__init__ called")
        super().__init__()
        print(f"DEBUG: QThread.__init__ completed")
        self.queue_manager = queue_manager
        print(f"DEBUG: queue_manager assigned")
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
        print(f"DEBUG: UploadWorker.__init__ completed")
        
    def stop(self):
        self.running = False
        self.wait()
    
    def request_soft_stop_current(self):
        """Request to stop the current item after in-flight uploads finish."""
        if self.current_item:
            self._soft_stop_requested_for = self.current_item.path
        
    def run(self):
        """Main worker thread loop"""
        print(f"DEBUG: Worker thread starting")
        try:
            # Initialize custom GUI uploader with reference to this worker
            print(f"DEBUG: Initializing uploader")
            self.uploader = GUIImxToUploader(worker_thread=self)
            
            # Login once for session reuse
            print(f"DEBUG: Starting login process")
            self.log_message.emit(f"{timestamp()} [auth] Logging in...")
            print(f"DEBUG: About to call uploader.login()")
            try:
                login_success = self.uploader.login()
                print(f"DEBUG: Login completed, success: {login_success}")
            except Exception as e:
                print(f"DEBUG: Login failed with exception: {e}")
                import traceback
                traceback.print_exc()
                login_success = False
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
            
            print(f"DEBUG: Entering main worker loop")
            while self.running:
                # Handle requested login retries from GUI
                try:
                    self._maybe_handle_login_retry()
                except Exception:
                    pass
                # Get next item from queue
                get_item_start = time.time()
                item = self.queue_manager.get_next_item()
                get_item_duration = time.time() - get_item_start
                
                if item is None:
                    # Only log timing if get_next_item took significant time
                    if get_item_duration > 0.001:
                        print(f"[TIMING] get_next_item() took {get_item_duration:.6f}s (returned None)")
                    # Periodically emit queue stats even when idle
                    try:
                        self._emit_queue_stats()
                    except Exception:
                        pass
                    time.sleep(0.1)
                    continue
                
                print(f"[TIMING] get_next_item() took {get_item_duration:.6f}s (got item: {item.path})")
                print(f"DEBUG: Worker got item: {item.path}, status: {item.status}")
                
                # Only process items that are queued to upload
                if item.status == "queued":
                    print(f"DEBUG: Starting upload for {item.path}")
                    upload_start = time.time()
                    self.current_item = item
                    self.upload_gallery(item)
                    upload_duration = time.time() - upload_start
                    print(f"[TIMING] upload_gallery({item.path}) took {upload_duration:.6f}s")
                    print(f"DEBUG: Upload finished for {item.path}")
                elif item.status == "paused":
                    print(f"DEBUG: Skipping paused item {item.path}")
                    # Skip paused items
                    try:
                        self._emit_queue_stats()
                    except Exception:
                        pass
                    time.sleep(0.1)
                else:
                    print(f"DEBUG: Item {item.path} has unexpected status: {item.status}")
                    # Put item back in queue if not ready
                    try:
                        self._emit_queue_stats()
                    except Exception:
                        pass
                    time.sleep(0.1)
                
        except Exception as e:
            print(f"DEBUG: Worker thread crashed with error: {e}")
            import traceback
            traceback.print_exc()
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
        method_start = time.time()
        print(f"[TIMING] upload_gallery({item.path}) method started at {method_start:.6f}")
        
        try:
            # Clear any previous soft-stop request when starting a new item
            self._soft_stop_requested_for = None
            self.log_message.emit(f"{timestamp()} Starting upload: {item.name or os.path.basename(item.path)}")
            
            # Set status to uploading and update display (single source of truth here)
            status_update_start = time.time()
            self.queue_manager.update_item_status(item.path, "uploading")
            item.start_time = time.time()
            status_update_duration = time.time() - status_update_start
            print(f"[TIMING] Status update to 'uploading' took {status_update_duration:.6f}s")
            
            # Emit signal to update display immediately
            signal_start = time.time()
            self.gallery_started.emit(item.path, item.total_images or 0)
            # Also emit queue stats since states changed
            try:
                self._emit_queue_stats(force=True)
            except Exception:
                pass
            signal_duration = time.time() - signal_start
            print(f"[TIMING] Signal emissions took {signal_duration:.6f}s")
            
            # If soft stop already requested by the time we start, reflect status to incomplete in UI
            if getattr(self, '_soft_stop_requested_for', None) == item.path:
                self.queue_manager.update_item_status(item.path, "incomplete")
            
            # Get default settings
            defaults_start = time.time()
            defaults = load_user_defaults()
            defaults_duration = time.time() - defaults_start
            print(f"[TIMING] load_user_defaults() took {defaults_duration:.6f}s")
            
            # Upload with progress tracking
            upload_start = time.time()
            print(f"[TIMING] About to call uploader.upload_folder() at {upload_start:.6f}")
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
            upload_duration = time.time() - upload_start
            print(f"[TIMING] uploader.upload_folder() took {upload_duration:.6f}s")
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
            # This runs on worker thread, import is acceptable here but should be cached
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
                # Don't log here - logging is handled by background completion worker to avoid duplicates
            except Exception:
                pass
        except Exception as e:
            self.log_message.emit(f"{timestamp()} Artifact save error: {e}")
    


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
                self.log_message.emit(f"{timestamp()} Completion processing error: {e}")
    
    def _process_completion_background(self, path: str, results: dict, gui_parent):
        """Do the heavy completion processing in background thread"""
        try:
            # Create gallery files with new naming format
            gallery_id = results.get('gallery_id', '')
            gallery_name = results.get('gallery_name', os.path.basename(path))
            
            if not gallery_id or not gallery_name:
                return
            
            # Only track for renaming if gallery is actually unnamed
            try:
                from imxup import save_unnamed_gallery, get_unnamed_galleries, check_gallery_renamed
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
                
            # Use cached template functions to avoid blocking import
            generate_bbcode_from_template = getattr(self, '_generate_bbcode_from_template', lambda *args, **kwargs: "")
            
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
            queue_item = gui_parent.queue_manager.get_item(path)
            total_size = results.get('total_size', 0) or (queue_item.total_size if queue_item and getattr(queue_item, 'total_size', 0) else 0)
            try:
                format_binary_size = getattr(self, '_format_binary_size', lambda size, precision=2: f"{size} B" if size else "")
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

            # Prepare template data
            template_data = {
                'folder_name': gallery_name,
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
            item = gui_parent.queue_manager.get_item(path)
            template_name = item.template_name if item else "default"
            
            # Generate bbcode using the item's template
            bbcode_content = generate_bbcode_from_template(template_name, template_data)
            
            # Save artifacts through shared core helper
            try:
                save_gallery_artifacts = getattr(self, '_save_gallery_artifacts', lambda *args, **kwargs: {})
                written = save_gallery_artifacts(
                    folder_path=path,
                    results={
                        **results,
                        'started_at': datetime.fromtimestamp(gui_parent.queue_manager.items[path].start_time).strftime('%Y-%m-%d %H:%M:%S') if path in gui_parent.queue_manager.items and gui_parent.queue_manager.items[path].start_time else None,
                        'thumbnail_size': gui_parent.thumbnail_size_combo.currentIndex() + 1,
                        'thumbnail_format': gui_parent.thumbnail_format_combo.currentIndex() + 1,
                        'public_gallery': 1 if gui_parent.public_gallery_check.isChecked() else 0,
                        'parallel_batch_size': gui_parent.batch_size_spin.value(),
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
                        self.log_message.emit(f"{timestamp()} [fileio] Saved gallery files to {', '.join(parts)}")
                except Exception:
                    pass
            except Exception as e:
                self.log_message.emit(f"{timestamp()} Artifact save error: {e}")
                
        except Exception as e:
            self.log_message.emit(f"{timestamp()} Background completion processing error: {e}")


class DropEnabledTabBar(QTabBar):
    """Custom tab bar that accepts gallery drops and provides visual feedback"""
    
    # Signal for when galleries are dropped on a tab
    galleries_dropped = pyqtSignal(str, list)  # tab_name, gallery_paths
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._drag_highlight_index = -1
    
    def dragEnterEvent(self, event):
        """Handle drag enter events"""
        if event.mimeData().hasFormat("application/x-imxup-galleries"):
            event.acceptProposedAction()
            self._update_drag_highlight(event.position().toPoint())
        else:
            super().dragEnterEvent(event)
    
    def dragMoveEvent(self, event):
        """Handle drag move events"""
        if event.mimeData().hasFormat("application/x-imxup-galleries"):
            event.acceptProposedAction()
            self._update_drag_highlight(event.position().toPoint())
        else:
            super().dragMoveEvent(event)
    
    def dragLeaveEvent(self, event):
        """Handle drag leave events"""
        self._clear_drag_highlight()
        super().dragLeaveEvent(event)
    
    def dropEvent(self, event):
        """Handle drop events"""
        if event.mimeData().hasFormat("application/x-imxup-galleries"):
            # Find the tab at drop position
            drop_index = self.tabAt(event.position().toPoint())
            if drop_index >= 0:
                tab_text = self.tabText(drop_index)
                tab_name = tab_text.split(' (')[0] if ' (' in tab_text else tab_text
                
                # Extract gallery paths from mime data
                gallery_data = event.mimeData().data("application/x-imxup-galleries")
                gallery_paths = gallery_data.data().decode('utf-8').split('\n')
                gallery_paths = [path.strip() for path in gallery_paths if path.strip()]
                
                if gallery_paths:
                    self.galleries_dropped.emit(tab_name, gallery_paths)
                    event.acceptProposedAction()
                else:
                    event.ignore()
            else:
                event.ignore()
        else:
            super().dropEvent(event)
        
        self._clear_drag_highlight()
    
    def _update_drag_highlight(self, position):
        """Update visual highlight for drag feedback"""
        new_index = self.tabAt(position)
        if new_index != self._drag_highlight_index:
            self._drag_highlight_index = new_index
            self.update()  # Trigger repaint for visual feedback
    
    def _clear_drag_highlight(self):
        """Clear drag highlight"""
        if self._drag_highlight_index != -1:
            self._drag_highlight_index = -1
            self.update()
    
    def paintEvent(self, event):
        """Custom paint to show drag highlight"""
        super().paintEvent(event)
        
        # Draw drag highlight if needed
        if self._drag_highlight_index >= 0:
            from PyQt6.QtGui import QPainter, QPen
            painter = QPainter(self)
            painter.setPen(QPen(QColor(52, 152, 219), 3))  # Blue highlight
            
            rect = self.tabRect(self._drag_highlight_index)
            painter.drawRoundedRect(rect.adjusted(2, 2, -2, -2), 4, 4)
            painter.end()


class TabbedGalleryWidget(QWidget):
    """Tabbed gallery widget that provides efficient tab switching while maintaining all table functionality"""
    
    # Signals
    tab_changed = pyqtSignal(str)  # tab_name
    tab_renamed = pyqtSignal(str, str)  # old_name, new_name
    tab_deleted = pyqtSignal(str)  # tab_name
    tab_created = pyqtSignal(str)  # tab_name
    galleries_dropped = pyqtSignal(str, list)  # tab_name, gallery_paths
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Initialize tab manager reference
        self.tab_manager = None
        self.current_tab = "Main"
        
        # Enhanced filter result caching system
        self._filter_cache = {}  # Cache filtered row visibility per tab
        self._filter_cache_timestamps = {}  # Track cache freshness per tab
        self._path_to_tab_cache = {}  # Cache gallery path to tab mappings
        self._cache_version = 0  # Version counter for cache invalidation
        self._cache_ttl = 10.0  # Cache time-to-live in seconds
        
        # Performance monitoring system
        self._perf_metrics = {
            'tab_switches': 0,
            'filter_cache_hits': 0,
            'filter_cache_misses': 0,
            'filter_times': [],  # Track filter performance
            'tab_switch_times': [],  # Track tab switch performance
            'emergency_fallbacks': 0,  # Track when filtering exceeds budget
            'background_updates_processed': 0
        }
        self._perf_start_time = time.time()
        
        self._init_ui()
        self._setup_connections()
    
    def _init_ui(self):
        """Initialize the UI components"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        
        # Tab bar setup with drop support
        self.tab_bar = DropEnabledTabBar()
        self.tab_bar.setTabsClosable(False)  # We'll handle closing via context menu
        self.tab_bar.setMovable(True)  # Allow drag reordering
        self.tab_bar.setExpanding(False)
        self.tab_bar.setUsesScrollButtons(True)
        
        # Add "+" button for new tabs with enhanced styling
        self.new_tab_btn = QPushButton("+")
        self.new_tab_btn.setFixedSize(32, 25)
        self.new_tab_btn.setToolTip("Add new tab (Ctrl+T)")
        
        # Tab bar styling - set after button creation
        self._setup_tab_styling()
        
        # Tab bar container
        tab_container = QHBoxLayout()
        tab_container.setContentsMargins(0, 0, 0, 0)
        tab_container.addWidget(self.tab_bar)
        tab_container.addWidget(self.new_tab_btn)
        tab_container.addStretch()
        
        tab_widget = QWidget()
        tab_widget.setLayout(tab_container)
        tab_widget.setMaximumHeight(35)
        
        layout.addWidget(tab_widget)
        
        # Gallery table (reuse existing implementation)
        self.gallery_table = GalleryTableWidget()
        layout.addWidget(self.gallery_table, 1)  # Give it stretch priority
        
        # Tabs will be initialized when TabManager is set
        # Don't add hardcoded tabs here
    
    def _setup_connections(self):
        """Setup signal connections"""
        self.tab_bar.currentChanged.connect(self._on_tab_changed)
        self.tab_bar.tabBarDoubleClicked.connect(self._on_tab_double_clicked)
        # Connect tab bar signal to parent's handler (will be connected by parent)
        self.new_tab_btn.clicked.connect(self._add_new_tab)
        
        # Connect tab bar drag-drop signal to own handler for GUI updates
        self.tab_bar.galleries_dropped.connect(self._on_galleries_dropped)
        
        # Context menu for tabs
        self.tab_bar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tab_bar.customContextMenuRequested.connect(self._show_tab_context_menu)
        
        # Setup keyboard shortcuts
        self._setup_keyboard_shortcuts()
        
        # Setup discoverability hints
        self._setup_discoverability_hints()
    
    def set_tab_manager(self, tab_manager):
        """Set the tab manager reference"""
        self.tab_manager = tab_manager
        self._refresh_tabs()
    
    def _refresh_tabs(self):
        """Refresh tabs from tab manager"""
        if not self.tab_manager:
            print("Warning: No tab manager available for TabbedGalleryWidget")
            return
        
        # Clear existing tabs first
        while self.tab_bar.count() > 0:
            self.tab_bar.removeTab(0)
        
        # Get tabs from manager
        manager_tabs = self.tab_manager.get_visible_tab_names()
        print(f"Debug: TabManager returned {len(manager_tabs)} tabs: {manager_tabs}")
        
        # Add all tabs from manager
        for tab_name in manager_tabs:
                self.tab_bar.addTab(tab_name)
        
        # Add "All Tabs" at the end
        self.tab_bar.addTab("All Tabs")
        
        # Set current tab to the last active tab from manager, or Main if none
        if manager_tabs:
            # Try to set to last active tab
            last_active = self.tab_manager.last_active_tab
            if last_active in manager_tabs:
                index = manager_tabs.index(last_active)
                self.tab_bar.setCurrentIndex(index)
            else:
                # Default to first tab
                self.tab_bar.setCurrentIndex(0)
        else:
            # No tabs available, create a default Main tab
            print("Warning: No tabs available, creating default Main tab")
            self.tab_bar.addTab("Main")
            self.tab_bar.setCurrentIndex(0)
        
        # Update current_tab attribute to match the selected tab
        if self.tab_bar.count() > 0:
            tab_text = self.tab_bar.tabText(self.tab_bar.currentIndex())
            # Extract base tab name (remove count if present)
            base_tab_name = tab_text.split(' (')[0] if ' (' in tab_text else tab_text
            self.current_tab = base_tab_name
            print(f"Debug: Current tab set to: {self.current_tab}")
        
        # Update tooltips after refreshing tabs
        self._update_tab_tooltips()
        
        print(f"Debug: TabbedGalleryWidget now has {self.tab_bar.count()} tabs")
    
    def _on_tab_changed(self, index):
        """Handle tab change with performance tracking"""
        if index < 0 or index >= self.tab_bar.count():
            return
        
        # Performance monitoring
        switch_start_time = time.time()
        
        tab_text = self.tab_bar.tabText(index)
        tab_name = tab_text.split(' (')[0] if ' (' in tab_text else tab_text
        old_tab = self.current_tab
        
        self.current_tab = tab_name
        
        # Invalidate update queue visibility cache when switching tabs
        update_queue = getattr(self.gallery_table, '_update_queue', None)
        if update_queue and hasattr(update_queue, 'invalidate_visibility_cache'):
            update_queue.invalidate_visibility_cache()
        
        self._apply_filter(tab_name)
        self.tab_changed.emit(tab_name)
        
        # Update performance metrics
        switch_time = (time.time() - switch_start_time) * 1000
        self._perf_metrics['tab_switches'] += 1
        self._perf_metrics['tab_switch_times'].append(switch_time)
        
        # Keep only recent measurements
        if len(self._perf_metrics['tab_switch_times']) > 50:
            self._perf_metrics['tab_switch_times'] = self._perf_metrics['tab_switch_times'][-25:]
            
        # Log slow tab switches
        if switch_time > 16:
            print(f"Slow tab switch from '{old_tab}' to '{tab_name}': {switch_time:.1f}ms")
    
    def _on_galleries_dropped(self, tab_name, gallery_paths):
        """Handle galleries being dropped on a tab"""
        print(f"DEBUG: _on_galleries_dropped called with tab_name='{tab_name}', {len(gallery_paths)} paths", flush=True)
        if not self.tab_manager or not gallery_paths:
            print(f"DEBUG: Early return - tab_manager={bool(self.tab_manager)}, gallery_paths={len(gallery_paths) if gallery_paths else 0}", flush=True)
            return
        
        try:
            # Move galleries to the target tab (tab_name is already clean from dropEvent)
            moved_count = self.tab_manager.move_galleries_to_tab(gallery_paths, tab_name)
            print(f"DEBUG: move_galleries_to_tab returned moved_count={moved_count}", flush=True)
            
            # Update queue manager's in-memory items to match database
            print(f"DEBUG: moved_count={moved_count}, has_queue_manager={hasattr(self, 'queue_manager')}, has_tab_manager={bool(self.tab_manager)}")
            if moved_count > 0 and hasattr(self, 'queue_manager') and self.tab_manager:
                updated_count = 0
                for path in gallery_paths:
                    item = self.queue_manager.get_item(path)
                    if item:
                        old_tab = item.tab_name
                        item.tab_name = tab_name
                        updated_count += 1
                        print(f"DEBUG: Drag-drop updated item {path} tab: '{old_tab}' -> '{tab_name}'", flush=True)
                        # Verify the change stuck
                        print(f"DEBUG: Verification - item.tab_name is now '{item.tab_name}'", flush=True)
                    else:
                        print(f"DEBUG: No item found for path: {path}", flush=True)
                print(f"DEBUG: Updated {updated_count} in-memory items out of {len(gallery_paths)} paths")
                
                # Don't call save_persistent_queue() here - database is already updated
                # and is the source of truth. QueueManager loads from database on startup.
            
            # Invalidate TabManager's cache for affected tabs
            if moved_count > 0:
                self.tab_manager.invalidate_tab_cache()  # Invalidate all tabs
            
            # Refresh the current view to reflect changes
            self.refresh_filter()
            
            # Emit signal to notify main GUI about gallery moves
            if moved_count > 0:
                self.galleries_dropped.emit(tab_name, gallery_paths)
                
                # Optional: Show feedback message
                gallery_word = "gallery" if moved_count == 1 else "galleries"
                print(f"DEBUG: DRAG-DROP PATH - Moved {moved_count} {gallery_word} to '{tab_name}' tab")
                
        except Exception as e:
            print(f"Error moving galleries to tab '{tab_name}': {e}")
    
    def _apply_filter(self, tab_name):
        """Apply filtering to show only rows belonging to the specified tab with intelligent caching"""
        if not self.tab_manager:
            # No filtering if no tab manager
            print("Warning: No tab manager available for filtering")
            for row in range(self.gallery_table.rowCount()):
                self.gallery_table.setRowHidden(row, False)
            return
        
        if not tab_name:
            print("Warning: No tab name specified for filtering")
            return
        
        print(f"Debug: Applying filter for tab: {tab_name}")
        
        start_time = time.time()
        row_count = self.gallery_table.rowCount()
        
        if row_count == 0:
            print("Debug: Table is empty, no filtering needed")
            return
        
        # Check if we have a valid cached result
        cache_key = f"{tab_name}_{row_count}_{self._cache_version}"
        current_time = time.time()
        
        if (cache_key in self._filter_cache and 
            tab_name in self._filter_cache_timestamps and
            current_time - self._filter_cache_timestamps[tab_name] < self._cache_ttl):
            # Use cached result for instant filtering
            cached_visibility = self._filter_cache[cache_key]
            for row, should_show in cached_visibility.items():
                self.gallery_table.setRowHidden(row, not should_show)
            
            # Notify update queue to invalidate visibility cache
            update_queue = getattr(self.gallery_table, '_update_queue', None)
            if update_queue and hasattr(update_queue, 'invalidate_visibility_cache'):
                update_queue.invalidate_visibility_cache()
            
            # Performance tracking - cache hit
            elapsed = (time.time() - start_time) * 1000
            self._perf_metrics['filter_cache_hits'] += 1
            self._perf_metrics['filter_times'].append(elapsed)
            if len(self._perf_metrics['filter_times']) > 100:
                self._perf_metrics['filter_times'] = self._perf_metrics['filter_times'][-50:]
            return
        
        # Get gallery paths for this tab (use cached if available)
        tab_paths_set = self._get_cached_tab_paths(tab_name)
        
        # Performance optimization: batch row visibility changes
        TIME_BUDGET = 0.010  # 10ms budget for filtering (2ms reserved for caching)
        
        # Track visibility changes to batch setRowHidden calls
        visibility_map = {}  # row -> should_show
        
        for row in range(row_count):
            if time.time() - start_time > TIME_BUDGET:
                # Emergency fallback: process remaining rows in next frame
                self._perf_metrics['emergency_fallbacks'] += 1
                QTimer.singleShot(1, lambda: self._continue_filter_with_cache(row, row_count, tab_name, tab_paths_set, cache_key, visibility_map))
                return
                
            name_item = self.gallery_table.item(row, 1)  # Gallery name column
            if name_item:
                path = name_item.data(Qt.ItemDataRole.UserRole)
                if tab_name == "All Tabs":
                    # Special "All Tabs" shows all galleries
                    should_show = True
                else:
                    # All tabs (including Main) show only their assigned galleries
                    should_show = path in tab_paths_set
                    
                visibility_map[row] = should_show
                self.gallery_table.setRowHidden(row, not should_show)
            else:
                # Hide rows without valid path data
                visibility_map[row] = False
                self.gallery_table.setRowHidden(row, True)
        
        # Cache the result for future use
        self._filter_cache[cache_key] = visibility_map
        self._filter_cache_timestamps[tab_name] = current_time
        
        # Clean old cache entries periodically
        if len(self._filter_cache) > 20:  # Keep max 20 cached filters
            self._cleanup_filter_cache()
        
        # Notify update queue to invalidate visibility cache
        update_queue = getattr(self.gallery_table, '_update_queue', None)
        if update_queue and hasattr(update_queue, 'invalidate_visibility_cache'):
            update_queue.invalidate_visibility_cache()
        
        # Performance tracking - cache miss
        elapsed = (time.time() - start_time) * 1000
        self._perf_metrics['filter_cache_misses'] += 1
        self._perf_metrics['filter_times'].append(elapsed)
        if len(self._perf_metrics['filter_times']) > 100:
            self._perf_metrics['filter_times'] = self._perf_metrics['filter_times'][-50:]
            
        if elapsed > 16:  # Log if slower than 60fps
            print(f"Tab filter took {elapsed:.1f}ms for {row_count} rows")
            
    def _continue_filter(self, start_row, total_rows, tab_name, tab_paths_set):
        """Continue filtering from where we left off to avoid blocking main thread"""
        TIME_BUDGET = 0.008  # Smaller budget for continuation
        start_time = time.time()
        
        for row in range(start_row, total_rows):
            if time.time() - start_time > TIME_BUDGET:
                # Schedule next batch if needed
                QTimer.singleShot(1, lambda: self._continue_filter(row, total_rows, tab_name, tab_paths_set))
                return
                
            name_item = self.gallery_table.item(row, 1)
            if name_item:
                path = name_item.data(Qt.ItemDataRole.UserRole)
                if tab_name == "All Tabs":
                    self.gallery_table.setRowHidden(row, False)
                else:
                    should_show = path in tab_paths_set
                    self.gallery_table.setRowHidden(row, not should_show)
            else:
                self.gallery_table.setRowHidden(row, True)
                
    def _get_cached_tab_paths(self, tab_name):
        """Get cached tab paths or load and cache them"""
        # Special case for "All Tabs" - return empty set to show all
        if tab_name == "All Tabs":
            return set()
        
        if not self.tab_manager:
            print("Warning: No tab manager available for loading tab galleries")
            return set()
            
        cache_key = f"{tab_name}_{self._cache_version}"
        current_time = time.time()
        
        # Check if we have fresh cached paths
        if (cache_key in self._path_to_tab_cache and 
            tab_name in self._filter_cache_timestamps and
            current_time - self._filter_cache_timestamps[tab_name] < self._cache_ttl):
            return self._path_to_tab_cache[cache_key]
        
        # Load and cache tab galleries
        try:
            tab_galleries = self.tab_manager.load_tab_galleries(tab_name)
            tab_paths_set = {gallery.get('path') for gallery in tab_galleries if gallery.get('path')}
            print(f"Debug: Loaded {len(tab_paths_set)} galleries for tab '{tab_name}'")
        except Exception as e:
            print(f"Error loading galleries for tab '{tab_name}': {e}")
            tab_paths_set = set()
        
        # Cache the result
        self._path_to_tab_cache[cache_key] = tab_paths_set
        return tab_paths_set
        
    def _continue_filter_with_cache(self, start_row, total_rows, tab_name, tab_paths_set, cache_key, visibility_map):
        """Continue filtering with caching support"""
        TIME_BUDGET = 0.006  # Smaller budget for continuation
        start_time = time.time()
        
        for row in range(start_row, total_rows):
            if time.time() - start_time > TIME_BUDGET:
                # Schedule next batch if needed
                QTimer.singleShot(1, lambda: self._continue_filter_with_cache(row, total_rows, tab_name, tab_paths_set, cache_key, visibility_map))
                return
                
            name_item = self.gallery_table.item(row, 1)
            if name_item:
                path = name_item.data(Qt.ItemDataRole.UserRole)
                if tab_name == "All Tabs":
                    should_show = True
                else:
                    should_show = path in tab_paths_set
                    
                visibility_map[row] = should_show
                self.gallery_table.setRowHidden(row, not should_show)
            else:
                visibility_map[row] = False
                self.gallery_table.setRowHidden(row, True)
        
        # Cache the completed result
        self._filter_cache[cache_key] = visibility_map
        self._filter_cache_timestamps[tab_name] = time.time()
        
    def _cleanup_filter_cache(self):
        """Clean up old filter cache entries"""
        current_time = time.time()
        
        # Remove expired entries
        expired_keys = []
        for cache_key in self._filter_cache:
            # Extract tab name from cache key
            tab_name = cache_key.split('_')[0]
            if (tab_name in self._filter_cache_timestamps and
                current_time - self._filter_cache_timestamps[tab_name] > self._cache_ttl):
                expired_keys.append(cache_key)
        
        for key in expired_keys:
            self._filter_cache.pop(key, None)
            
        # Also clean path cache
        expired_path_keys = []
        for cache_key in self._path_to_tab_cache:
            tab_name = cache_key.split('_')[0]
            if (tab_name in self._filter_cache_timestamps and
                current_time - self._filter_cache_timestamps[tab_name] > self._cache_ttl):
                expired_path_keys.append(cache_key)
                
        for key in expired_path_keys:
            self._path_to_tab_cache.pop(key, None)
    
    def invalidate_filter_cache(self, tab_name=None):
        """Invalidate filter cache for specific tab or all tabs"""
        if tab_name:
            # Remove specific tab entries
            keys_to_remove = [key for key in self._filter_cache if key.startswith(f"{tab_name}_")]
            for key in keys_to_remove:
                self._filter_cache.pop(key, None)
            self._filter_cache_timestamps.pop(tab_name, None)
            
            path_keys_to_remove = [key for key in self._path_to_tab_cache if key.startswith(f"{tab_name}_")]
            for key in path_keys_to_remove:
                self._path_to_tab_cache.pop(key, None)
        else:
            # Clear all caches
            self._filter_cache.clear()
            self._filter_cache_timestamps.clear()
            self._path_to_tab_cache.clear()
            self._cache_version += 1  # Increment version to invalidate all cache keys
    
    def get_performance_metrics(self):
        """Get performance metrics summary for tabbed interface"""
        uptime = time.time() - self._perf_start_time
        
        metrics = {
            'uptime_seconds': uptime,
            'tab_switches_total': self._perf_metrics['tab_switches'],
            'tab_switches_per_minute': (self._perf_metrics['tab_switches'] / uptime * 60) if uptime > 0 else 0,
            'cache_hit_rate': (
                self._perf_metrics['filter_cache_hits'] / 
                max(1, self._perf_metrics['filter_cache_hits'] + self._perf_metrics['filter_cache_misses'])
            ),
            'emergency_fallbacks': self._perf_metrics['emergency_fallbacks'],
            'background_updates_processed': self._perf_metrics['background_updates_processed']
        }
        
        # Calculate average times
        if self._perf_metrics['tab_switch_times']:
            metrics['avg_tab_switch_ms'] = sum(self._perf_metrics['tab_switch_times']) / len(self._perf_metrics['tab_switch_times'])
            metrics['max_tab_switch_ms'] = max(self._perf_metrics['tab_switch_times'])
        else:
            metrics['avg_tab_switch_ms'] = 0
            metrics['max_tab_switch_ms'] = 0
            
        if self._perf_metrics['filter_times']:
            metrics['avg_filter_ms'] = sum(self._perf_metrics['filter_times']) / len(self._perf_metrics['filter_times'])
            metrics['max_filter_ms'] = max(self._perf_metrics['filter_times'])
        else:
            metrics['avg_filter_ms'] = 0
            metrics['max_filter_ms'] = 0
            
        return metrics
    
    def log_performance_summary(self):
        """Log a performance summary to console"""
        metrics = self.get_performance_metrics()
        print("\n=== Tabbed Interface Performance Summary ===")
        print(f"Uptime: {metrics['uptime_seconds']:.1f}s")
        print(f"Tab switches: {metrics['tab_switches_total']} ({metrics['tab_switches_per_minute']:.1f}/min)")
        print(f"Cache hit rate: {metrics['cache_hit_rate']:.1%}")
        print(f"Avg tab switch time: {metrics['avg_tab_switch_ms']:.1f}ms")
        print(f"Max tab switch time: {metrics['max_tab_switch_ms']:.1f}ms")
        print(f"Avg filter time: {metrics['avg_filter_ms']:.1f}ms")
        print(f"Max filter time: {metrics['max_filter_ms']:.1f}ms")
        print(f"Emergency fallbacks: {metrics['emergency_fallbacks']}")
        print(f"Background updates: {metrics['background_updates_processed']}")
        print("============================================\n")
    
    def _on_tab_double_clicked(self, index):
        """Handle tab double-click for renaming"""
        if index < 0 or index >= self.tab_bar.count():
            return
        
        current_text = self.tab_bar.tabText(index)
        current_name = current_text.split(' (')[0] if ' (' in current_text else current_text
        if current_name in ["Main", "All Tabs"]:
            return  # Don't allow renaming Main tab or All Tabs
        
        from PyQt6.QtWidgets import QInputDialog
        new_name, ok = QInputDialog.getText(
            self, 
            "Rename Tab", 
            "Enter new tab name:", 
            text=current_name
        )
        
        if ok and new_name.strip() and new_name.strip() != current_name:
            new_name = new_name.strip()
            if self._is_valid_tab_name(new_name):
                self._rename_tab(index, current_name, new_name)
    
    def _add_new_tab(self):
        """Add a new tab"""
        from PyQt6.QtWidgets import QInputDialog
        tab_name, ok = QInputDialog.getText(
            self, 
            "New Tab", 
            "Enter tab name:"
        )
        
        if ok and tab_name.strip():
            tab_name = tab_name.strip()
            if self._is_valid_tab_name(tab_name):
                self.tab_bar.addTab(tab_name)
                new_index = self.tab_bar.count() - 1
                self.tab_bar.setCurrentIndex(new_index)
                
                # Create tab in manager
                if self.tab_manager:
                    self.tab_manager.create_tab(tab_name)
                
                self.tab_created.emit(tab_name)
                self._update_tab_tooltips()
    
    def _is_valid_tab_name(self, name):
        """Check if tab name is valid and unique"""
        if not name or name.strip() != name:
            return False
        
        # Check for duplicates
        for i in range(self.tab_bar.count()):
            tab_text = self.tab_bar.tabText(i)
            # Extract base tab name (remove count if present)
            base_tab_name = tab_text.split(' (')[0] if ' (' in tab_text else tab_text
            if base_tab_name == name:
                return False
        
        return True
    
    def _rename_tab(self, index, old_name, new_name):
        """Rename a tab"""
        self.tab_bar.setTabText(index, new_name)
        
        # Update in manager
        if self.tab_manager:
            self.tab_manager.rename_tab(old_name, new_name)
        
        if self.current_tab == old_name:
            self.current_tab = new_name
        
        self.tab_renamed.emit(old_name, new_name)
        self._update_tab_tooltips()
    
    def _show_tab_context_menu(self, position):
        """Show enhanced context menu for tab bar"""
        index = self.tab_bar.tabAt(position)
        if index < 0:
            # Clicked on empty area - show general options
            self._show_general_tab_menu(position)
            return
        
        tab_text = self.tab_bar.tabText(index)
        tab_name = tab_text.split(' (')[0] if ' (' in tab_text else tab_text
        self._show_specific_tab_menu(position, index, tab_name)
    
    def _show_general_tab_menu(self, position):
        """Show context menu for empty tab bar area"""
        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtGui import QIcon
        
        menu = QMenu()
        menu.setTitle("Tab Options")
        
        # New tab option
        new_tab_action = menu.addAction("New Tab")
        new_tab_action.setShortcut("Ctrl+T")
        new_tab_action.triggered.connect(self._add_new_tab)
        
        menu.addSeparator()
        
        # Tab management options
        if self.tab_bar.count() > 1:  # Only show if there are user tabs
            organize_menu = menu.addMenu("Organize Tabs")
            
            sort_action = organize_menu.addAction("Sort Alphabetically")
            sort_action.triggered.connect(self._sort_tabs_alphabetically)
            
            close_all_action = organize_menu.addAction("Close All Tabs (except Main)")
            close_all_action.triggered.connect(self._close_all_user_tabs)
        
        global_pos = self.tab_bar.mapToGlobal(position)
        menu.exec(global_pos)
    
    def _show_specific_tab_menu(self, position, index, tab_name):
        """Show context menu for specific tab"""
        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtGui import QIcon
        
        menu = QMenu()
        menu.setTitle(f"Tab: {tab_name}")
        
        # Extract base tab name (remove count if present)
        base_tab_name = tab_name.split(' (')[0] if ' (' in tab_name else tab_name
        
        # Get gallery count for this tab
        gallery_count = 0
        if self.tab_manager and base_tab_name not in ["Main", "All Tabs"]:
            galleries = self.tab_manager.load_tab_galleries(base_tab_name)
            gallery_count = len(galleries)
        elif base_tab_name == "Main":
            if self.tab_manager:
                galleries = self.tab_manager.load_tab_galleries("Main")
                gallery_count = len(galleries)
            else:
                gallery_count = 0
        elif base_tab_name == "All Tabs":
            gallery_count = self.gallery_table.rowCount()
        
        # Add tab info at top
        info_action = menu.addAction(f"{gallery_count} galleries")
        info_action.setEnabled(False)
        menu.addSeparator()
        
        if base_tab_name not in ["Main", "All Tabs"]:  # Don't allow operations on Main tab or All Tabs
            # Primary actions
            rename_action = menu.addAction("Rename Tab")
            rename_action.setShortcut("F2")
            rename_action.triggered.connect(lambda: self._on_tab_double_clicked(index))
            
            duplicate_action = menu.addAction("Duplicate Tab")
            duplicate_action.triggered.connect(lambda: self._duplicate_tab(base_tab_name))
            
            menu.addSeparator()
            
            # Merge options (if other tabs exist)
            other_tabs = [self.tab_bar.tabText(i).split(' (')[0] for i in range(self.tab_bar.count()) 
                         if i != index and self.tab_bar.tabText(i).split(' (')[0] != "All Tabs"]
            
            if other_tabs:
                merge_menu = menu.addMenu("Merge Into...")
                for other_tab in other_tabs:
                    merge_action = merge_menu.addAction(other_tab)
                    merge_action.triggered.connect(
                        lambda checked, target=other_tab: self._merge_tabs(base_tab_name, target)
                    )
                menu.addSeparator()
            
            # Dangerous actions at bottom
            delete_action = menu.addAction("Delete Tab...")
            delete_action.setShortcut("Ctrl+W")
            if gallery_count > 0:
                delete_action.setText(f"Delete Tab... ({gallery_count} galleries will move to Main)")
            delete_action.triggered.connect(lambda: self._delete_tab_with_confirmation(index, base_tab_name, gallery_count))
        
        elif base_tab_name == "Main":
            # Main tab specific options
            if self.tab_bar.count() > 2:  # Account for All Tabs
                clear_action = menu.addAction("Move All Galleries to Other Tabs...")
                clear_action.triggered.connect(self._move_all_from_main)
        
        elif base_tab_name == "All Tabs":
            # All Tabs has no special operations
            pass
        
        global_pos = self.tab_bar.mapToGlobal(position)
        menu.exec(global_pos)
    
    def _delete_tab(self, index, tab_name):
        """Delete a tab (legacy method - use _delete_tab_with_confirmation)"""
        # Calculate gallery count for confirmation
        gallery_count = 0
        if self.tab_manager:
            galleries = self.tab_manager.load_tab_galleries(tab_name)
            gallery_count = len(galleries)
        
        self._delete_tab_with_confirmation(index, tab_name, gallery_count)
    
    def _merge_tabs(self, source_tab, target_tab):
        """Merge source tab into target tab"""
        from PyQt6.QtWidgets import QMessageBox
        
        reply = QMessageBox.question(
            self,
            "Merge Tabs",
            f"Merge '{source_tab}' into '{target_tab}'?\n\n"
            "All galleries will be moved and the source tab will be deleted.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes and self.tab_manager:
            # Move all galleries from source to target
            tab_galleries = self.tab_manager.load_tab_galleries(source_tab)
            if tab_galleries:
                for gallery in tab_galleries:
                    gallery_path = gallery.get('path')
                    if gallery_path:
                        self.tab_manager.move_galleries_to_tab([gallery_path], target_tab)
            
            # Delete source tab
            source_index = self._find_tab_index(source_tab)
            if source_index >= 0:
                self._delete_tab(source_index, source_tab)
    
    def _find_tab_index(self, tab_name):
        """Find the index of a tab by name"""
        for i in range(self.tab_bar.count()):
            tab_text = self.tab_bar.tabText(i)
            # Extract base tab name (remove count if present)
            base_tab_name = tab_text.split(' (')[0] if ' (' in tab_text else tab_text
            if base_tab_name == tab_name:
                return i
        return -1
    
    def refresh_filter(self):
        """Refresh the current filter (call after gallery assignments change)"""
        if not self.current_tab:
            print("Warning: No current tab set for filter refresh")
            return
            
        print(f"Debug: Refreshing filter for current tab: {self.current_tab}")
        
        # Invalidate cache first to ensure fresh data after gallery moves
        self.invalidate_filter_cache()
        self._apply_filter(self.current_tab)
        # Force table to update display immediately
        self.gallery_table.update()
        self.gallery_table.repaint()
        # Update tooltips when gallery assignments change
        self._update_tab_tooltips()
    
    def assign_gallery_to_current_tab(self, gallery_path):
        """Assign a gallery to the currently active tab"""
        if self.tab_manager and self.current_tab not in ["All Tabs"]:
            moved_count = self.tab_manager.move_galleries_to_tab([gallery_path], self.current_tab)
            if moved_count > 0:
                # Update queue manager's in-memory items to match database
                if hasattr(self, 'queue_manager'):
                    # Get the tab_id for the current tab
                    tab_info = self.tab_manager.get_tab_by_name(self.current_tab)
                    tab_id = tab_info.id if tab_info else 1
                    
                    item = self.queue_manager.get_item(gallery_path)
                    if item:
                        item.tab_name = self.current_tab
                        item.tab_id = tab_id
                
                self.tab_manager.invalidate_tab_cache()
            self.refresh_filter()
    
    def get_current_tab(self):
        """Get the name of the currently active tab"""
        return self.current_tab
    
    def switch_to_tab(self, tab_name):
        """Switch to a specific tab"""
        index = self._find_tab_index(tab_name)
        if index >= 0:
            self.tab_bar.setCurrentIndex(index)
    
    def _setup_tab_styling(self):
        """Setup theme-aware tab styling with enhanced visual feedback"""
        # Check if we're in dark mode
        app = QApplication.instance()
        is_dark = False
        if app:
            palette = app.palette()
            window_color = palette.color(palette.ColorRole.Window)
            is_dark = window_color.lightness() < 128
        
        if is_dark:
            tab_style = """
                QTabBar::tab {
                    background: #2b2b2b;
                    border: 1px solid #404040;
                    border-bottom: none;
                    padding: 8px 16px;
                    margin-right: 1px;
                    min-width: 80px;
                    border-top-left-radius: 4px;
                    border-top-right-radius: 4px;
                    color: #e6e6e6;
                    font-weight: 500;
                }
                QTabBar::tab:selected {
                    background: #3d3d3d;
                    border-bottom: 3px solid #3498db;
                    color: #ffffff;
                    font-weight: 600;
                }
                QTabBar::tab:hover:!selected {
                    background: #353535;
                    border-color: #505050;
                }
                QTabBar::tab:!selected:hover {
                    color: #f0f0f0;
                }
                QTabBar::tab[data-tab-type="system"] {
                    font-style: italic;
                }
                QTabBar::tab[data-modified="true"] {
                    color: #f39c12;
                }
                QTabBar::tab[data-drag-highlight="true"] {
                    border: 2px solid #3498db;
                    background: #404040;
                }
            """
        else:
            tab_style = """
                QTabBar::tab {
                    background: #f8f9fa;
                    border: 1px solid #dee2e6;
                    border-bottom: none;
                    padding: 8px 16px;
                    margin-right: 1px;
                    min-width: 80px;
                    border-top-left-radius: 4px;
                    border-top-right-radius: 4px;
                    color: #495057;
                    font-weight: 500;
                }
                QTabBar::tab:selected {
                    background: #ffffff;
                    border-bottom: 3px solid #3498db;
                    color: #212529;
                    font-weight: 600;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                }
                QTabBar::tab:hover:!selected {
                    background: #e9ecef;
                    border-color: #adb5bd;
                }
                QTabBar::tab:!selected:hover {
                    color: #212529;
                }
                QTabBar::tab[data-tab-type="system"] {
                    font-style: italic;
                }
                QTabBar::tab[data-modified="true"] {
                    color: #e67e22;
                }
                QTabBar::tab[data-drag-highlight="true"] {
                    border: 2px solid #3498db;
                    background: #e3f2fd;
                }
            """
        
        self.tab_bar.setStyleSheet(tab_style)
        self._update_new_tab_button_style(is_dark)
    
    def _update_new_tab_button_style(self, is_dark=False):
        """Update the new tab button styling to match current theme"""
        if is_dark:
            button_style = """
                QPushButton {
                    background: #2b2b2b;
                    border: 1px solid #404040;
                    border-radius: 4px;
                    color: #e6e6e6;
                    font-weight: bold;
                    font-size: 16px;
                    padding: 2px;
                }
                QPushButton:hover {
                    background: #353535;
                    border-color: #505050;
                    color: #3498db;
                }
                QPushButton:pressed {
                    background: #1e1e1e;
                    border-color: #3498db;
                }
            """
        else:
            button_style = """
                QPushButton {
                    background: #f8f9fa;
                    border: 1px solid #dee2e6;
                    border-radius: 4px;
                    color: #495057;
                    font-weight: bold;
                    font-size: 16px;
                    padding: 2px;
                }
                QPushButton:hover {
                    background: #e9ecef;
                    border-color: #adb5bd;
                    color: #3498db;
                }
                QPushButton:pressed {
                    background: #dee2e6;
                    border-color: #3498db;
                }
            """
        
        self.new_tab_btn.setStyleSheet(button_style)
    
    def update_theme(self):
        """Update tab styling when theme changes"""
        self._setup_tab_styling()
    
    def _setup_keyboard_shortcuts(self):
        """Setup keyboard shortcuts for tab operations"""
        from PyQt6.QtGui import QShortcut, QKeySequence
        
        # Ctrl+T: New tab
        new_tab_shortcut = QShortcut(QKeySequence("Ctrl+T"), self)
        new_tab_shortcut.activated.connect(self._add_new_tab)
        
        # Ctrl+W: Close current tab (if not Main)
        close_tab_shortcut = QShortcut(QKeySequence("Ctrl+W"), self)
        close_tab_shortcut.activated.connect(self._close_current_tab)
        
        # Ctrl+Tab / Ctrl+Shift+Tab: Switch between tabs
        next_tab_shortcut = QShortcut(QKeySequence("Ctrl+Tab"), self)
        next_tab_shortcut.activated.connect(self._next_tab)
        
        prev_tab_shortcut = QShortcut(QKeySequence("Ctrl+Shift+Tab"), self)
        prev_tab_shortcut.activated.connect(self._prev_tab)
        
        # F2: Rename current tab
        rename_shortcut = QShortcut(QKeySequence("F2"), self)
        rename_shortcut.activated.connect(self._rename_current_tab)
    
    def _setup_discoverability_hints(self):
        """Setup visual hints for tab operations"""
        # Update tab bar to show double-click hint
        self.tab_bar.setWhatsThis(
            "Double-click any tab to rename it.\n"
            "Right-click for more options.\n"
            "Drag tabs to reorder them."
        )
        
        # Enhanced tooltip for Main tab
        self._update_tab_tooltips()
    
    def _update_tab_tooltips(self):
        """Update tooltips and tab text with gallery counts for all tabs"""
        # Removed traceback debug output
        
        # Prevent recursive calls completely - return immediately if called again
        if hasattr(self, '_updating_tooltips') and self._updating_tooltips:
            print(f"DEBUG: _update_tab_tooltips already running, skipping recursion", flush=True)
            return
        
        # Block ALL calls during initialization to prevent infinite loops
        if hasattr(self, '_initializing') and self._initializing:
            print(f"DEBUG: Still initializing, skipping _update_tab_tooltips", flush=True)
            return
        
        self._updating_tooltips = True
        try:
            for i in range(self.tab_bar.count()):
                current_text = self.tab_bar.tabText(i)
                # Extract base tab name (remove count if present)
                base_name = current_text.split(' (')[0] if ' (' in current_text else current_text
            
                if base_name == "All Tabs":
                    total_galleries = self.gallery_table.rowCount() if hasattr(self, 'gallery_table') else 0
                    # Update tab text with count
                    self.tab_bar.setTabText(i, f"All Tabs ({total_galleries})")
                    self.tab_bar.setTabToolTip(i, 
                        f"All Tabs shows all galleries ({total_galleries} total)\n"
                        "This tab cannot be modified"
                    )
                else:
                    gallery_count = 0
                    active_count = 0
                    if self.tab_manager and base_name != "All Tabs":
                        galleries = self.tab_manager.load_tab_galleries(base_name)
                        gallery_count = len(galleries)
                        print(f"DEBUG: Tab '{base_name}' load_tab_galleries returned {gallery_count} galleries", flush=True)
                        # Count active uploads (simplified status check)
                        active_count = sum(1 for g in galleries if g.get('status') in ['uploading', 'pending'])
                    
                    # Update tab text with count
                    old_text = self.tab_bar.tabText(i)
                    new_text = f"{base_name} ({gallery_count})"
                    if old_text != new_text:  # Only update if changed
                        print(f"DEBUG: About to update tab {i} text: '{old_text}' -> '{new_text}'", flush=True)
                        self.tab_bar.setTabText(i, new_text)
                        print(f"DEBUG: Updated tab {i} text", flush=True)
                
                    status_text = ""
                    if active_count > 0:
                        status_text = f" ({active_count} active)"
                
                    if base_name == "Main":
                        self.tab_bar.setTabToolTip(i, 
                            f"Main tab ({gallery_count} galleries{status_text})\n"
                            "Right-click for options"
                        )
                    else:
                        self.tab_bar.setTabToolTip(i, 
                            f"{base_name} ({gallery_count} galleries{status_text})\n"
                            "Double-click to rename (F2)\n"
                            "Right-click for options\n"
                            "Drag to reorder"
                        )
                
                    # Update tab visual state based on content
                    self._update_tab_visual_state(i, base_name, gallery_count, active_count)
        finally:
            self._updating_tooltips = False
    
    def _update_tab_visual_state(self, tab_index, tab_name, gallery_count, active_count):
        """Update visual state of a tab based on its content"""
        # This could set different styling based on tab state
        # For now, we'll use the standard styling but this allows future enhancements
        # like colored indicators for tabs with active uploads, etc.
        
        # Example: Could add different styling for:
        # - Empty tabs (gallery_count == 0)
        # - Active upload tabs (active_count > 0)
        # - System vs user tabs
        # - Recently modified tabs
        
        # For now, just ensure proper styling is applied
        pass
    
    def _close_current_tab(self):
        """Close the current tab via keyboard shortcut"""
        current_index = self.tab_bar.currentIndex()
        tab_name = self.tab_bar.tabText(current_index)
        # Extract base tab name (remove count if present)
        base_name = tab_name.split(' (')[0] if ' (' in tab_name else tab_name
        if base_name != "Main":
            self._delete_tab(current_index, base_name)
    
    def _next_tab(self):
        """Switch to next tab"""
        current = self.tab_bar.currentIndex()
        next_index = (current + 1) % self.tab_bar.count()
        self.tab_bar.setCurrentIndex(next_index)
    
    def _prev_tab(self):
        """Switch to previous tab"""
        current = self.tab_bar.currentIndex()
        prev_index = (current - 1) % self.tab_bar.count()
        self.tab_bar.setCurrentIndex(prev_index)
    
    def _rename_current_tab(self):
        """Rename current tab via keyboard shortcut"""
        current_index = self.tab_bar.currentIndex()
        if current_index >= 0:
            self._on_tab_double_clicked(current_index)
    
    def _duplicate_tab(self, tab_name):
        """Create a duplicate of the specified tab"""
        if not self.tab_manager:
            return
        
        # Get galleries from source tab
        galleries = self.tab_manager.load_tab_galleries(tab_name)
        
        # Create new tab with incremented name
        base_name = tab_name
        counter = 2
        new_name = f"{base_name} Copy"
        
        while not self._is_valid_tab_name(new_name):
            new_name = f"{base_name} Copy {counter}"
            counter += 1
        
        # Create the new tab
        self.tab_bar.addTab(new_name)
        new_index = self.tab_bar.count() - 1
        self.tab_manager.create_tab(new_name)
        
        # Copy galleries to new tab
        if galleries:
            gallery_paths = [g.get('path') for g in galleries if g.get('path')]
            self.tab_manager.move_galleries_to_tab(gallery_paths, new_name)
        
        # Switch to new tab
        self.tab_bar.setCurrentIndex(new_index)
        self.tab_created.emit(new_name)
        self._update_tab_tooltips()
    
    def _sort_tabs_alphabetically(self):
        """Sort user tabs alphabetically (excluding Main)"""
        # Get all tab names except Main
        tab_names = []
        for i in range(self.tab_bar.count()):
            name = self.tab_bar.tabText(i)
            # Extract base tab name (remove count if present)
            base_name = name.split(' (')[0] if ' (' in name else name
            if base_name != "Main":
                tab_names.append(name)
        
        if len(tab_names) <= 1:
            return
        
        # Sort alphabetically
        tab_names.sort()
        
        # Rebuild tab bar with sorted order
        current_tab = self.current_tab
        
        # Remove all non-Main tabs
        for i in range(self.tab_bar.count() - 1, -1, -1):
            tab_text = self.tab_bar.tabText(i)
            # Extract base tab name (remove count if present)
            base_name = tab_text.split(' (')[0] if ' (' in tab_text else tab_text
            if base_name != "Main":
                self.tab_bar.removeTab(i)
        
        # Add sorted tabs
        for name in tab_names:
            self.tab_bar.addTab(name)
        
        # Restore current tab selection
        if current_tab in tab_names:
            self.switch_to_tab(current_tab)
        
        self._update_tab_tooltips()
    
    def _close_all_user_tabs(self):
        """Close all user tabs, keeping only Main"""
        from PyQt6.QtWidgets import QMessageBox
        
        user_tabs = []
        for i in range(self.tab_bar.count()):
            tab_text = self.tab_bar.tabText(i)
            # Extract base tab name (remove count if present)
            base_name = tab_text.split(' (')[0] if ' (' in tab_text else tab_text
            if base_name != "Main":
                user_tabs.append(tab_text)
        
        if not user_tabs:
            return
        
        reply = QMessageBox.question(
            self,
            "Close All Tabs",
            f"Are you sure you want to close all {len(user_tabs)} user tabs?\n"
            "All galleries will be moved to the Main tab.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            # Close tabs in reverse order to maintain indices
            for i in range(self.tab_bar.count() - 1, -1, -1):
                tab_name = self.tab_bar.tabText(i)
                # Extract base tab name (remove count if present)
                base_name = tab_name.split(' (')[0] if ' (' in tab_name else tab_name
                if base_name != "Main":
                    self._delete_tab_without_confirmation(i, tab_name)
            
            # Switch to Main tab
            self.tab_bar.setCurrentIndex(0)
            self._update_tab_tooltips()
    
    def _move_all_from_main(self):
        """Move all galleries from Main tab to other tabs"""
        # This would open a dialog to distribute galleries
        # Implementation would depend on specific requirements
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.information(
            self,
            "Feature Not Implemented",
            "Gallery distribution feature is not yet implemented."
        )
    
    def _delete_tab_with_confirmation(self, index, tab_name, gallery_count):
        """Delete tab with appropriate confirmation dialog"""
        from PyQt6.QtWidgets import QMessageBox
        
        if gallery_count > 0:
            reply = QMessageBox.question(
                self,
                "Delete Tab",
                f"Are you sure you want to delete the '{tab_name}' tab?\n\n"
                f"{gallery_count} galleries will be moved to the Main tab.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
        else:
            reply = QMessageBox.question(
                self,
                "Delete Tab",
                f"Are you sure you want to delete the '{tab_name}' tab?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
        
        if reply == QMessageBox.StandardButton.Yes:
            self._delete_tab_without_confirmation(index, tab_name)
    
    def _delete_tab_without_confirmation(self, index, tab_name):
        """Delete tab without confirmation (for internal use)"""
        # Move galleries to Main tab if tab manager exists
        if self.tab_manager:
            galleries = self.tab_manager.load_tab_galleries(tab_name)
            if galleries:
                gallery_paths = [g.get('path') for g in galleries if g.get('path')]
                self.tab_manager.move_galleries_to_tab(gallery_paths, "Main")
            
            # Delete tab from manager
            self.tab_manager.delete_tab(tab_name)
        
        # Remove tab from UI
        self.tab_bar.removeTab(index)
        
        # Emit signal
        self.tab_deleted.emit(tab_name)
        
        # Update tooltips
        self._update_tab_tooltips()
        
        # Refresh current filter
        self.refresh_filter()
    
    # Delegate table methods to maintain compatibility
    def __getattr__(self, name):
        """Delegate unknown attributes to the gallery table"""
        # Avoid recursion during initialization by checking __dict__ directly
        if 'gallery_table' in self.__dict__ and hasattr(self.gallery_table, name):
            return getattr(self.gallery_table, name)
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")


class GalleryTableWidget(QTableWidget):
    """Table widget for gallery queue with resizable columns, sorting, and action buttons"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Drag and drop state
        self._drag_start_position = None
        self._is_dragging = False
        
        # Enable drag and drop for internal gallery moves only
        self.setDragEnabled(True)
        self.setAcceptDrops(False)  # Don't accept drops on table - only on tabs
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        
        # Setup table
        # Columns: 0 #, 1 gallery name, 2 uploaded, 3 progress, 4 status, 5 added, 6 finished, 7 action,
        #          8 size, 9 transfer, 10 template, 11 title
        self.setColumnCount(12)
        self.setHorizontalHeaderLabels([
            "#", "gallery name", "uploaded", "progress", "status", "added", "finished", "action",
            "size", "transfer", "template", "title"
        ])
        
        # Set larger icon size for Status column icons (default is usually 16x16)
        self.setIconSize(QSize(20, 20))
        
        # Set global font styles for table items to prevent size changes
        self.setStyleSheet("""
            QTableWidget::item {
                font-size: 8pt !important;
                font-family: system;
                padding: 2px;
            }
            QTableWidget::item:selected {
                font-size: 8pt !important;
            }
            QTableWidgetItem {
                font-size: 8pt !important;
            }
        """)
        try:
            # Left-align the 'gallery name' header specifically
            hn = self.horizontalHeaderItem(1)
            if hn:
                hn.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                # Gallery name column gets slightly larger font
                hn.setFont(QFont(hn.font().family(), 9))
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
            # Store position for potential drag start
            self._drag_start_position = event.position().toPoint()
        super().mousePressEvent(event)
    
    def mouseMoveEvent(self, event):
        """Handle mouse move events for drag and drop"""
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            super().mouseMoveEvent(event)
            return
        
        if self._drag_start_position is None:
            super().mouseMoveEvent(event)
            return
        
        # Check if we've moved far enough to start a drag
        if ((event.position().toPoint() - self._drag_start_position).manhattanLength() < 
            QApplication.startDragDistance()):
            super().mouseMoveEvent(event)
            return
        
        # Start drag if we have selected items
        selected_items = self.selectedItems()
        if selected_items:
            self._start_gallery_drag()
        
        super().mouseMoveEvent(event)
    
    def _start_gallery_drag(self):
        """Start a drag operation with selected galleries"""
        # Get selected gallery paths
        selected_rows = sorted({item.row() for item in self.selectedItems()})
        gallery_paths = []
        gallery_names = []
        
        for row in selected_rows:
            name_item = self.item(row, 1)  # Gallery name column
            if name_item:
                path = name_item.data(Qt.ItemDataRole.UserRole)
                if path:
                    gallery_paths.append(path)
                    gallery_names.append(name_item.text())
        
        if not gallery_paths:
            return
        
        # Create mime data for internal gallery transfer
        mime_data = QMimeData()
        mime_data.setData("application/x-imxup-galleries", 
                         "\n".join(gallery_paths).encode('utf-8'))
        
        # Add text representation for debugging
        if len(gallery_names) == 1:
            mime_data.setText(f"Gallery: {gallery_names[0]}")
        else:
            mime_data.setText(f"{len(gallery_names)} galleries")
        
        # Create drag object
        drag = QDrag(self)
        drag.setMimeData(mime_data)
        
        # Set up drag pixmap (visual feedback)
        pixmap = self._create_drag_pixmap(gallery_names)
        drag.setPixmap(pixmap)
        drag.setHotSpot(QPoint(pixmap.width() // 2, 10))
        
        # Execute drag
        self._is_dragging = True
        drop_action = drag.exec(Qt.DropAction.MoveAction)
        self._is_dragging = False
    
    def _create_drag_pixmap(self, gallery_names):
        """Create a pixmap for drag visual feedback"""
        from PyQt6.QtGui import QPainter, QFont, QFontMetrics
        
        # Calculate pixmap size
        font = QFont(self.font())
        font.setPointSize(9)
        metrics = QFontMetrics(font)
        
        if len(gallery_names) == 1:
            text = gallery_names[0][:30]  # Truncate long names
            if len(gallery_names[0]) > 30:
                text += "..."
        else:
            text = f"{len(gallery_names)} galleries"
        
        text_width = metrics.horizontalAdvance(text)
        text_height = metrics.height()
        
        # Create pixmap with padding
        pixmap_width = text_width + 20
        pixmap_height = text_height + 10
        pixmap = QPixmap(pixmap_width, pixmap_height)
        pixmap.fill(QColor(100, 150, 200, 180))  # Semi-transparent blue
        
        # Draw text
        painter = QPainter(pixmap)
        painter.setFont(font)
        painter.setPen(Qt.GlobalColor.white)
        painter.drawText(10, text_height + 2, text)
        painter.end()
        
        return pixmap
    
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
        # Filter for completed items only (like context menu does)
        widget = self
        while widget and not hasattr(widget, 'queue_manager'):
            widget = widget.parent()
        completed_paths = []
        if widget and hasattr(widget, 'queue_manager'):
            for path in paths:
                item = widget.queue_manager.get_item(path)
                if item and item.status == "completed":
                    completed_paths.append(path)
        # Delegate to the multi-copy helper to aggregate
        self.copy_bbcode_via_menu_multi(completed_paths)
    
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
            
            # Add "Move to" submenu for all selected galleries
            # Find the tabbed gallery widget to get available tabs
            tabbed_widget = self
            while tabbed_widget and not hasattr(tabbed_widget, 'tab_manager'):
                tabbed_widget = tabbed_widget.parent()
            
            if tabbed_widget and hasattr(tabbed_widget, 'tab_manager') and tabbed_widget.tab_manager:
                available_tabs = tabbed_widget.tab_manager.get_visible_tab_names()
                current_tab = getattr(tabbed_widget, 'current_tab', 'Main')
                
                # Create "Move to" submenu with tabs other than the current one and excluding "All Tabs"
                other_tabs = [tab for tab in available_tabs if tab != current_tab and tab != "All Tabs"]
                if other_tabs:
                    move_menu = menu.addMenu("Move to...")
                    for tab_name in other_tabs:
                        move_action = move_menu.addAction(tab_name)
                        move_action.triggered.connect(
                            lambda checked, target_tab=tab_name: self._move_selected_to_tab(selected_paths, target_tab)
                        )
        
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
    
    def _move_selected_to_tab(self, gallery_paths, target_tab):
        """Move selected galleries to the specified tab"""
        if not gallery_paths or not target_tab:
            return
        
        # Find the tabbed gallery widget to access tab manager
        tabbed_widget = self
        while tabbed_widget and not hasattr(tabbed_widget, 'tab_manager'):
            tabbed_widget = tabbed_widget.parent()
        
        if tabbed_widget and hasattr(tabbed_widget, 'tab_manager') and tabbed_widget.tab_manager:
            try:
                moved_count = tabbed_widget.tab_manager.move_galleries_to_tab(gallery_paths, target_tab)
                print(f"DEBUG: Right-click move_galleries_to_tab returned moved_count={moved_count}", flush=True)
                
                # Update queue manager's in-memory items to match database
                print(f"DEBUG: Checking conditions - moved_count={moved_count}, has_queue_manager={hasattr(tabbed_widget, 'queue_manager')}, has_tab_manager={bool(tabbed_widget.tab_manager)}", flush=True)
                
                # Find the widget with queue_manager
                queue_widget = tabbed_widget
                while queue_widget and not hasattr(queue_widget, 'queue_manager'):
                    queue_widget = queue_widget.parent()
                
                print(f"DEBUG: Found queue_widget={bool(queue_widget)}, has_queue_manager={hasattr(queue_widget, 'queue_manager') if queue_widget else False}", flush=True)
                
                if moved_count > 0 and queue_widget and hasattr(queue_widget, 'queue_manager') and tabbed_widget.tab_manager:
                    # Get the tab_id for the target tab
                    tab_info = tabbed_widget.tab_manager.get_tab_by_name(target_tab)
                    tab_id = tab_info.id if tab_info else 1
                    
                    for path in gallery_paths:
                        item = queue_widget.queue_manager.get_item(path)
                        if item:
                            old_tab = item.tab_name
                            item.tab_name = target_tab
                            item.tab_id = tab_id
                            print(f"DEBUG: Right-click updated item {path} tab: '{old_tab}' -> '{target_tab}'", flush=True)
                            # Verify the change stuck
                            print(f"DEBUG: Verification - item.tab_name is now '{item.tab_name}'", flush=True)
                
                # Invalidate caches and refresh display
                if moved_count > 0:
                    print(f"DEBUG: RIGHT-CLICK calling invalidate_tab_cache() on {type(tabbed_widget).__name__}", flush=True)
                    
                    # Check database counts BEFORE cache invalidation
                    main_count_before = len(tabbed_widget.tab_manager.load_tab_galleries('Main'))
                    target_count_before = len(tabbed_widget.tab_manager.load_tab_galleries(target_tab))
                    print(f"DEBUG: RIGHT-CLICK BEFORE invalidate - Main={main_count_before}, {target_tab}={target_count_before}", flush=True)
                    
                    tabbed_widget.tab_manager.invalidate_tab_cache()
                    
                    # Check database counts AFTER cache invalidation
                    main_count_after = len(tabbed_widget.tab_manager.load_tab_galleries('Main'))
                    target_count_after = len(tabbed_widget.tab_manager.load_tab_galleries(target_tab))
                    print(f"DEBUG: RIGHT-CLICK AFTER invalidate - Main={main_count_after}, {target_tab}={target_count_after}", flush=True)
                    
                    print(f"DEBUG: RIGHT-CLICK calling refresh_filter() on {type(tabbed_widget).__name__}", flush=True)
                    tabbed_widget.refresh_filter()
                    
                    # Show feedback message
                    gallery_word = "gallery" if moved_count == 1 else "galleries"
                    print(f"DEBUG: RIGHT-CLICK PATH - Moved {moved_count} {gallery_word} to '{target_tab}' tab")
                    
            except Exception as e:
                print(f"Error moving galleries to tab '{target_tab}': {e}")
    
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
        # Use batch context to group all database saves into a single transaction
        with widget.queue_manager.batch_updates():
            for path in paths_in_order:
                if widget.queue_manager.start_item(path):
                    started += 1
        if started:
            if hasattr(widget, 'add_log_message'):
                timestamp_func = getattr(widget, '_timestamp', lambda: time.strftime("%H:%M:%S"))
                widget.add_log_message(f"{timestamp_func()} Started {started} selected item(s)")
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
        print(f"DEBUG: copy_bbcode_via_menu_multi called with {len(paths)} paths")
        # Find the main GUI window
        widget = self
        while widget and not hasattr(widget, 'queue_manager'):
            widget = widget.parent()
        if not widget:
            print("DEBUG: No widget with queue_manager found")
            return
        # Aggregate BBCode contents; reuse copy function to centralize path lookup
        contents = []
        for path in paths:
            print(f"DEBUG: Processing path: {path}")
            item = widget.queue_manager.get_item(path)
            if not item:
                print(f"DEBUG: No item found for path: {path}")
                continue
            print(f"DEBUG: Item status: {item.status}, gallery_id: {getattr(item, 'gallery_id', 'MISSING')}")
            if item.status != "completed":
                print(f"DEBUG: Skipping non-completed item: {item.status}")
                continue
            # Inline read similar to copy_bbcode_to_clipboard to avoid changing it
            folder_name = os.path.basename(path)
            print(f"DEBUG: folder_name: {folder_name}")
            # Use cached functions or fallbacks
            if hasattr(widget, '_get_central_storage_path'):
                base_path = widget._get_central_storage_path()
                central_path = os.path.join(base_path, "galleries")
                print(f"DEBUG: Using widget._get_central_storage_path: {central_path}")
            else:
                central_path = os.path.expanduser("~/.imxup/galleries")
                print(f"DEBUG: Using fallback central_path: {central_path}")
            if item.gallery_id and (item.name or folder_name):
                print(f"DEBUG: Has gallery_id and name, item.name: {getattr(item, 'name', 'MISSING')}")
                if hasattr(widget, '_build_gallery_filenames'):
                    _, _, bbcode_filename = widget._build_gallery_filenames(item.name or folder_name, item.gallery_id)
                    print(f"DEBUG: Using widget._build_gallery_filenames: {bbcode_filename}")
                else:
                    # Use sanitize_gallery_name like the real function does
                    safe_name = sanitize_gallery_name(item.name or folder_name)
                    bbcode_filename = f"{safe_name}_{item.gallery_id}_bbcode.txt"
                    print(f"DEBUG: Using fallback filename: {bbcode_filename}")
                central_bbcode = os.path.join(central_path, bbcode_filename)
            else:
                central_bbcode = os.path.join(central_path, f"{folder_name}_bbcode.txt")
                print(f"DEBUG: Using folder_name fallback: {central_bbcode}")
            print(f"DEBUG: Looking for BBCode file: {central_bbcode}")
            print(f"DEBUG: File exists: {os.path.exists(central_bbcode)}")
            # Move file I/O to background to avoid blocking GUI
            def _read_bbcode_async():
                text = ""
                if os.path.exists(central_bbcode):
                    try:
                        with open(central_bbcode, 'r', encoding='utf-8') as f:
                            text = f.read().strip()
                    except Exception:
                        text = ""
                return text
            
            # For now, read synchronously but this should be moved to a background worker
            text = _read_bbcode_async()
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
        
        # Store reference to username_edit for callback and use non-blocking show()
        def handle_username_result(result):
            self._handle_username_dialog_result(result, username_edit.text().strip())
        
        dialog.show()
        dialog.finished.connect(handle_username_result)
    
    def _handle_username_dialog_result(self, result, username):
        """Handle username dialog result without blocking GUI"""
        if result == QDialog.DialogCode.Accepted:
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
        
        # Store reference to password_edit for callback and use non-blocking show()
        def handle_password_result(result):
            self._handle_password_dialog_result(result, password_edit.text())
        
        dialog.show()
        dialog.finished.connect(handle_password_result)
    
    def _handle_password_dialog_result(self, result, password):
        """Handle password dialog result without blocking GUI"""
        if result == QDialog.DialogCode.Accepted:
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
        
        # Store reference to api_key_edit for callback and use non-blocking show()
        def handle_api_key_result(result):
            self._handle_api_key_dialog_result(result, api_key_edit.text().strip())
        
        dialog.show()
        dialog.finished.connect(handle_api_key_result)
    
    def _handle_api_key_dialog_result(self, result, api_key):
        """Handle API key dialog result without blocking GUI"""
        if result == QDialog.DialogCode.Accepted:
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
        msgbox = QMessageBox(self)
        msgbox.setWindowTitle("Remove Username")
        msgbox.setText("Without username/password, all galleries will be titled 'untitled gallery'.\n\nRemove the stored username?")
        msgbox.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msgbox.setDefaultButton(QMessageBox.StandardButton.No)
        msgbox.open()
        msgbox.finished.connect(self._handle_remove_username_confirmation)
    
    def _handle_remove_username_confirmation(self, result):
        """Handle username removal confirmation"""
        if result != QMessageBox.StandardButton.Yes:
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
            # Keep information dialog simple and non-blocking
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
                    # Emit signal for both folder paths and empty messages (window focus)
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
    
    def __init__(self, splash=None):
        print(f"DEBUG: ImxUploadGUI.__init__ starting")
        self._initializing = True  # Block recursive calls during init
        super().__init__()
        print(f"DEBUG: QMainWindow.__init__ completed")
        self.splash = splash
        # Set main window icon
        try:
            icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "imxup.ico")
            if os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))
        except Exception:
            pass
        if self.splash:
            self.splash.set_status("SQLite database")
        print(f"DEBUG: About to create QueueManager")
        self.queue_manager = QueueManager()
        print(f"DEBUG: QueueManager created")
        self.queue_manager.parent = self  # Give QueueManager access to parent for settings
        
        # Connect queue loaded signal to refresh filter
        self.queue_manager.queue_loaded.connect(self.refresh_filter)
        print(f"DEBUG: Queue loaded signal connected")
        
        # Initialize tab manager
        if self.splash:
            self.splash.set_status("TabManager")
        print(f"DEBUG: About to create TabManager")
        self.tab_manager = TabManager(self.queue_manager.store)
        print(f"DEBUG: TabManager created")
        
        # Auto-archive engine disabled for now
        self.auto_archive_engine = None
        print(f"DEBUG: AutoArchive disabled")
        
        # Connect queue status changes to update table display
        self.queue_manager.status_changed.connect(self.on_queue_item_status_changed)
        
        self.worker = None
        
        # Initialize completion worker for background processing
        print(f"DEBUG: Creating CompletionWorker")
        self.completion_worker = CompletionWorker(self)
        print(f"DEBUG: CompletionWorker created")
        self.completion_worker.completion_processed.connect(self.on_completion_processed)
        self.completion_worker.log_message.connect(self.add_log_message)
        self.completion_worker.start()
        self.table_progress_widgets = {}
        self.settings = QSettings("ImxUploader", "ImxUploadGUI")
        
        # Track path-to-row mapping to avoid expensive table rebuilds
        self.path_to_row = {}  # Maps gallery path to table row number
        self.row_to_path = {}  # Maps table row number to gallery path
        self._path_mapping_mutex = QMutex()  # Thread safety for mapping access
        
        # Track scanning completion for targeted updates
        self._last_scan_states = {}  # Maps path -> scan_complete status
        
        # Cache expensive operations to improve responsiveness
        self._cached_is_dark_mode = False
        self._theme_cache_time = 0
        self._format_functions_cached = False
        
        # Pre-cache formatting functions to avoid blocking imports during progress updates
        self._cache_format_functions()
        
        # Initialize non-blocking components
        self._thread_pool = QThreadPool()
        self._thread_pool.setMaxThreadCount(4)  # Limit background threads
        self._icon_cache = IconCache()
        
        # Initialize progress update batcher
        self._progress_batcher = ProgressUpdateBatcher(
            self._process_batched_progress_update,
            batch_interval=0.05  # 50ms batching
        )
        
        # Initialize table update queue
        self._table_update_queue = None  # Will be set after table creation
        
        # Enable drag and drop on main window
        self.setAcceptDrops(True)
        
        # Single instance server
        self.server = SingleInstanceServer()
        self.server.folder_received.connect(self.add_folder_from_command_line)
        self.server.start()
        
        if self.splash:
            self.splash.set_status("user interface")
        self.setup_ui()
        if self.splash:
            self.splash.set_status("menu bar")
        self.setup_menu_bar()
        if self.splash:
            self.splash.set_status("system tray")
        self.setup_system_tray()
        if self.splash:
            self.splash.set_status("saved settings")
        self.restore_settings()
        
        # Easter egg - quick gremlin flash
        if self.splash:
            self.splash.set_status("gremlins")
            QApplication.processEvents()
            time.sleep(0.01)  # Very brief
        
        # Initialize table update queue after table creation
        self._table_update_queue = TableUpdateQueue(self.gallery_table, self.path_to_row)
        
        # Initialize background tab update system
        self._background_tab_updates = {}  # Track updates for non-visible tabs
        self._background_update_timer = QTimer()
        self._background_update_timer.timeout.connect(self._process_background_tab_updates)
        self._background_update_timer.setSingleShot(True)
        
        # Connect tab manager to the tabbed gallery widget  
        print(f"Debug: Setting TabManager in TabbedGalleryWidget: {self.tab_manager}")
        self.gallery_table.set_tab_manager(self.tab_manager)
        
        # Connect tab change signal to refresh filter
        if hasattr(self.gallery_table, 'tab_changed'):
            self.gallery_table.tab_changed.connect(self.refresh_filter)
        
        # Connect gallery move signal to handle tab assignments
        # Connect tab bar drag-drop signal directly to our handler
        if hasattr(self.gallery_table, 'tab_bar') and hasattr(self.gallery_table.tab_bar, 'galleries_dropped'):
            self.gallery_table.tab_bar.galleries_dropped.connect(self.on_galleries_moved_to_tab)
        
        # Set reference to update queue in tabbed widget for cache invalidation
        if hasattr(self.gallery_table, '_update_queue'):
            self.gallery_table._update_queue = self._table_update_queue
        
        # Ensure initial filter is applied once UI is ready
        try:
            self.refresh_filter()
        except Exception:
            pass
        
        # Initialize update timer for automatic updates
        self.update_timer = QTimer()
        self._last_queue_version = self.queue_manager.get_version()
        def _tick():
            try:
                # Version-based lightweight updates only
                current = self.queue_manager.get_version()
                if current != self._last_queue_version:
                    self._last_queue_version = current
                    try:
                        self._update_scanned_rows()
                    except Exception:
                        pass
                    try:
                        if hasattr(self.gallery_table, '_update_tab_tooltips'):
                            self.gallery_table._update_tab_tooltips()
                    except Exception:
                        pass
                
                # Lightweight progress display
                try:
                    self.update_progress_display()
                except Exception:
                    pass
                    
                # Scan status
                try:
                    self._update_scan_status()
                except Exception:
                    pass
            except Exception as e:
                print(f"Timer error: {e}")
        self.update_timer.timeout.connect(_tick)
        self.update_timer.start(500)  # Start the timer
        
        # Check for stored credentials (only prompt if API key missing)
        print(f"DEBUG: About to check credentials")
        self.check_credentials()
        print(f"DEBUG: Credentials checked")
        
        # Start worker thread
        print(f"DEBUG: About to start worker thread")
        self.start_worker()
        print(f"DEBUG: start_worker() call completed")
        
        # Initial table build with proper path mapping
        self._initialize_table_from_queue()
        
        # Initial stats and progress display
        self.update_progress_display()
        
        # Initial button count update
        self._update_button_counts()
        
        # Ensure table has focus for keyboard shortcuts
        self.gallery_table.setFocus()
        
        # Clear initialization flag to allow normal tooltip updates
        self._initializing = False
        print("DEBUG: ImxUploadGUI.__init__ COMPLETED")

    def refresh_filter(self):
        """Refresh current tab filter on the embedded tabbed gallery widget."""
        try:
            if hasattr(self, 'gallery_table') and hasattr(self.gallery_table, 'refresh_filter'):
                self.gallery_table.refresh_filter()
        except Exception:
            pass
    
    def on_galleries_moved_to_tab(self, new_tab_name, gallery_paths):
        """Handle galleries being moved to a different tab - DATABASE ALREADY UPDATED BY DRAG-DROP HANDLER"""
        print(f"DEBUG: on_galleries_moved_to_tab called with {len(gallery_paths)} paths to '{new_tab_name}' - database already updated", flush=True)
        try:
            # Update the MAIN WINDOW queue manager's in-memory items to match database
            if hasattr(self, 'queue_manager') and hasattr(self, 'tab_manager'):
                tab_info = self.tab_manager.get_tab_by_name(new_tab_name)
                tab_id = tab_info.id if tab_info else 1
                
                for path in gallery_paths:
                    item = self.queue_manager.get_item(path)
                    if item:
                        old_tab = item.tab_name
                        item.tab_name = new_tab_name
                        item.tab_id = tab_id
                        print(f"DEBUG: Drag-drop updated MAIN WINDOW item {path} tab: '{old_tab}' -> '{new_tab_name}'", flush=True)
            
            # Invalidate cache and refresh MAIN WINDOW display
            if hasattr(self, 'tab_manager'):
                print(f"DEBUG: DRAG-DROP invalidating MAIN WINDOW cache and refreshing display", flush=True)
                self.tab_manager.invalidate_tab_cache()
                if hasattr(self, 'gallery_table') and hasattr(self.gallery_table, '_update_tab_tooltips'):
                    self.gallery_table._update_tab_tooltips()
                    print(f"DEBUG: DRAG-DROP updated main window tab tooltips", flush=True)
                
        except Exception as e:
            print(f"Error handling gallery move to tab '{new_tab_name}': {e}")
    
    # ----------------------------- Background Tab Update System -----------------------------
    
    def _process_background_tab_updates(self):
        """Process queued updates for non-visible tabs in background"""
        if not self._background_tab_updates:
            return
        
        start_time = time.time()
        TIME_BUDGET = 0.005  # 5ms budget for background processing
        
        # Process a few background updates per cycle
        updates_processed = 0
        paths_to_remove = []
        
        for path, (item, update_type, timestamp) in list(self._background_tab_updates.items()):
            if time.time() - start_time > TIME_BUDGET:
                break
                
            # Skip very old updates (>5 seconds) to prevent memory buildup
            if time.time() - timestamp > 5.0:
                paths_to_remove.append(path)
                continue
            
            # Process the background update (simplified, no UI updates)
            try:
                # Update internal state without UI operations
                row = self.path_to_row.get(path)
                if row is not None:
                    # Only update critical state information
                    if update_type == 'progress' and hasattr(item, 'progress'):
                        # Update progress tracking without UI
                        pass
                    elif update_type == 'status' and hasattr(item, 'status'):
                        # Update status tracking without UI  
                        pass
                        
                paths_to_remove.append(path)
                updates_processed += 1
                
            except Exception:
                # Remove problematic updates
                paths_to_remove.append(path)
        
        # Clean up processed/expired updates
        for path in paths_to_remove:
            self._background_tab_updates.pop(path, None)
        
        # Update performance metrics in tabbed widget if available
        if hasattr(self.gallery_table, '_perf_metrics') and updates_processed > 0:
            self.gallery_table._perf_metrics['background_updates_processed'] += updates_processed
            
        # Schedule next batch if there are more updates
        if self._background_tab_updates and not self._background_update_timer.isActive():
            self._background_update_timer.start(100)  # Process every 100ms
    
    def queue_background_tab_update(self, path: str, item, update_type: str = 'progress'):
        """Queue an update for galleries not currently visible in tabs"""
        # Only queue if row is likely hidden
        row = self.path_to_row.get(path)
        if row is not None and hasattr(self.gallery_table, 'isRowHidden'):
            if self.gallery_table.isRowHidden(row):
                # Queue for background processing
                self._background_tab_updates[path] = (item, update_type, time.time())
                
                # Start background timer if not running
                if not self._background_update_timer.isActive():
                    self._background_update_timer.start(100)
                return True
        return False
    
    def clear_background_tab_updates(self):
        """Clear all background tab updates (e.g., when switching tabs)"""
        self._background_tab_updates.clear()
        if self._background_update_timer.isActive():
            self._background_update_timer.stop()
    
    # ----------------------------- End Background Tab Update System -----------------------------
    
    def closeEvent(self, event):
        """Clean shutdown with proper thread cleanup"""
        try:
            # Stop background processing
            if hasattr(self, '_thread_pool'):
                self._thread_pool.clear()
                self._thread_pool.waitForDone(1000)  # Wait up to 1 second
                
            # Clean up progress batcher
            if hasattr(self, '_progress_batcher'):
                if hasattr(self._progress_batcher, '_timer'):
                    self._progress_batcher._timer.stop()
                    
            # Clean up table update queue
            if hasattr(self, '_table_update_queue'):
                if hasattr(self._table_update_queue, '_timer'):
                    self._table_update_queue._timer.stop()
                    
            # Clear icon cache
            if hasattr(self, '_icon_cache'):
                self._icon_cache.clear()
            
            # Stop auto-archive engine
            if hasattr(self, 'auto_archive_engine'):
                self.auto_archive_engine.stop()
                
        except Exception:
            pass  # Ignore cleanup errors
            
        # Call parent closeEvent
        super().closeEvent(event)
        
        # Add scanning status indicator to status bar
        self.scan_status_label = QLabel("Scanning: 0")
        self.scan_status_label.setVisible(False)
        self.statusBar().addPermanentWidget(self.scan_status_label)
        # Log viewer dialog reference
        self._log_viewer_dialog = None
        # Current transfer speed tracking
        self._current_transfer_kbps = 0.0
        
    def _format_rate_consistent(self, rate_kbps, precision=2):
        """Consistent rate formatting everywhere"""
        if rate_kbps >= 1000:  # Switch to MiB/s at 1000 KiB/s for readability
            return f"{rate_kbps / 1024:.{precision}f} MiB/s"
        else:
            return f"{rate_kbps:.{precision}f} KiB/s" if rate_kbps > 0 else f"0.{'0' * precision} KiB/s"
    
    def _format_size_consistent(self, size_bytes, precision=2):
        """Consistent size formatting everywhere"""
        if not size_bytes:
            return ""
        if size_bytes >= 1024**3:
            return f"{size_bytes / (1024**3):.{precision}f} GiB"
        elif size_bytes >= 1024**2:
            return f"{size_bytes / (1024**2):.{precision}f} MiB"
        elif size_bytes >= 1024:
            return f"{size_bytes / 1024:.{precision}f} KiB"
        else:
            return f"{size_bytes} B"
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
        # Validate row bounds to prevent setting icons on wrong rows
        if row < 0 or row >= self.gallery_table.rowCount():
            print(f"DEBUG: _set_status_cell_icon: Invalid row {row}, table has {self.gallery_table.rowCount()} rows")
            return
# Removed debug output - Status column working correctly
        
        # Use the same simple icon loading approach as Action column buttons
        try:
            assets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
            
            def _make_status_icon(names: list[str], fallback_std = None) -> QIcon:
                for name in names:
                    p = os.path.join(assets_dir, name)
                    if os.path.exists(p):
                        return QIcon(p)
                if fallback_std:
                    return self.style().standardIcon(fallback_std)
                return QIcon()
            
            # Map status to icon files and fallbacks
            icon = QIcon()
            tooltip = ""
            
            if status == "completed":
                icon = _make_status_icon(["check16.png", "check.png"], QStyle.StandardPixmap.SP_DialogApplyButton)
                tooltip = "Completed"
            elif status == "failed":
                icon = _make_status_icon(["error.png"], QStyle.StandardPixmap.SP_DialogCancelButton)
                tooltip = "Failed"
            elif status == "uploading":
                icon = _make_status_icon(["start.png"], QStyle.StandardPixmap.SP_MediaPlay)
                tooltip = "Uploading"
            elif status == "paused":
                icon = _make_status_icon(["pause.png"], QStyle.StandardPixmap.SP_MediaPause)
                tooltip = "Paused"
            elif status == "ready":
                icon = _make_status_icon(["ready.png", "pending.png"], QStyle.StandardPixmap.SP_DialogOkButton)
                tooltip = "Ready"
            else:
                # Default for queued, incomplete, scanning, etc.
                icon = _make_status_icon(["pending.png"], QStyle.StandardPixmap.SP_ComputerIcon)
                tooltip = status.title() if isinstance(status, str) else "Pending"
            
            # Apply the icon directly to the table cell
            self._apply_icon_to_cell(row, 4, icon, tooltip, status)
            
        except Exception:
            pass
        
    def _apply_icon_to_cell(self, row: int, col: int, icon, tooltip: str, status: str):
        """Apply icon to table cell - runs on main thread"""
        try:
            # Quick validation
            if row < 0 or row >= self.gallery_table.rowCount():
                return
                
            # Clear existing widget (in case there was one)
            self.gallery_table.removeCellWidget(row, col)
            
            # Create a simple table item with icon - much simpler than custom widgets
            item = QTableWidgetItem()
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setToolTip(tooltip)
            
            if icon is not None and not icon.isNull():
                item.setIcon(icon)
            else:
                # Fallback to text when no icon available
                item.setText(status.title() if isinstance(status, str) else "")
            
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
        import traceback
        stack = traceback.extract_stack()
        caller_chain = " -> ".join([frame.name for frame in stack[-4:-1]])
        print(f"DEBUG: _set_renamed_cell_icon: {caller_chain}: row={row}, is_renamed={is_renamed}")
        try:
            col = 11
            
            # Use the same simple icon loading approach as Status column
            assets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
            
            def _make_rename_icon(names: list[str], fallback_std = None) -> QIcon:
                for name in names:
                    p = os.path.join(assets_dir, name)
                    if os.path.exists(p):
                        return QIcon(p)
                if fallback_std:
                    return self.style().standardIcon(fallback_std)
                return QIcon()
            
            # Create a simple table item with icon
            item = QTableWidgetItem()
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            
            # Determine icon and tooltip based on rename status
            if is_renamed is True:
                icon = _make_rename_icon(["check16.png", "check.png"], QStyle.StandardPixmap.SP_DialogApplyButton)
                tooltip = "Renamed"
                if icon is not None and not icon.isNull():
                    item.setIcon(icon)
                    item.setText("")
                else:
                    item.setText("OK")
            elif is_renamed is False:
                icon = _make_rename_icon(["pending.png"], QStyle.StandardPixmap.SP_ComputerIcon)
                tooltip = "Pending rename"
                if icon is not None and not icon.isNull():
                    item.setIcon(icon)
                    item.setText("")
                else:
                    item.setText("...")
            else:
                # None/blank - no icon or text
                item.setIcon(QIcon())
                item.setText("")
                tooltip = ""
            
            item.setToolTip(tooltip)
            self.gallery_table.setItem(row, col, item)
            
        except Exception as e:
            # Set a basic item as fallback
            try:
                item = QTableWidgetItem("")
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.gallery_table.setItem(row, col, item)
            except Exception:
                pass

    def showEvent(self, event):
        try:
            super().showEvent(event)
        except Exception:
            pass
        # Post-show pass no longer needed - targeted updates handle icon refreshes
        try:
            pass  # Removed deprecated update_queue_display call that overwrites correct rename status
        except Exception:
            pass
    
    def _cache_format_functions(self):
        """Pre-cache ALL imxup functions to avoid blocking imports during runtime"""
        try:
            from imxup import (
                format_binary_rate, format_binary_size, get_unnamed_galleries,
                check_if_gallery_exists, timestamp, get_central_storage_path, 
                build_gallery_filenames, save_gallery_artifacts, generate_bbcode_from_template,
                load_templates, get_template_path, __version__, 
                get_central_store_base_path, set_central_store_base_path
            )
            self._format_binary_rate = format_binary_rate
            self._format_binary_size = format_binary_size
            self._get_unnamed_galleries = get_unnamed_galleries
            self._check_if_gallery_exists = check_if_gallery_exists
            self._timestamp = timestamp
            self._get_central_storage_path = get_central_storage_path
            self._build_gallery_filenames = build_gallery_filenames
            self._save_gallery_artifacts = save_gallery_artifacts
            self._generate_bbcode_from_template = generate_bbcode_from_template
            self._load_templates = load_templates
            self._get_template_path = get_template_path
            self._version = __version__
            self._get_central_store_base_path = get_central_store_base_path
            self._set_central_store_base_path = set_central_store_base_path
        except Exception:
            # Fallback functions if import fails
            self._format_binary_rate = lambda rate, precision=2: self._format_rate_consistent(rate, precision)
            self._format_binary_size = lambda size, precision=2: f"{size} B" if size else ""
            self._get_unnamed_galleries = lambda: {}
            self._check_if_gallery_exists = lambda name: []
            self._timestamp = lambda: time.strftime("%H:%M:%S")
            self._get_central_storage_path = lambda: os.path.expanduser("~/.imxup")
            self._build_gallery_filenames = lambda name, id: (f"{name}_{id}.json", f"{name}_{id}.json", f"{name}_{id}_bbcode.txt")
            self._save_gallery_artifacts = lambda *args, **kwargs: {}
            self._generate_bbcode_from_template = lambda *args, **kwargs: ""
            self._load_templates = lambda: {"default": ""}
            self._get_template_path = lambda: os.path.expanduser("~/.imxup/templates")
            self._version = "unknown"
            self._get_central_store_base_path = lambda: os.path.expanduser("~/.imxup")
            self._set_central_store_base_path = lambda path: None
        
    def setup_ui(self):
        try:
            from imxup import __version__
            self.setWindowTitle(f"IMX.to Gallery Uploader v{__version__}")
        except Exception:
            self.setWindowTitle("IMX.to Gallery Uploader")
        self.setMinimumSize(800, 650)  # Allow log to shrink to accommodate Settings
        
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
        
        # Tabbed gallery widget (replaces single table)
        self.gallery_table = TabbedGalleryWidget()
        self.gallery_table.setMinimumHeight(400)  # Taller table
        queue_layout.addWidget(self.gallery_table, 1)  # Give it stretch priority
        
        # Header context menu for column visibility + persist widths/visibility
        # Access the internal table for header operations
        try:
            header = self.gallery_table.gallery_table.horizontalHeader()
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
            right_layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetMinimumSize)
        except Exception:
            pass
        
        
        # Settings section
        self.settings_group = QGroupBox("Settings")
        self.settings_group.setMinimumHeight(350)  # Prevent button overlap when window is resized
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
        
        # Comprehensive Settings button
        self.comprehensive_settings_btn = QPushButton("⚙️ Comprehensive Settings")
        if not self.comprehensive_settings_btn.text().startswith(" "):
            self.comprehensive_settings_btn.setText(" " + self.comprehensive_settings_btn.text())
        self.comprehensive_settings_btn.clicked.connect(self.open_comprehensive_settings)
        self.comprehensive_settings_btn.setMinimumHeight(30)
        self.comprehensive_settings_btn.setMaximumHeight(34)
        self.comprehensive_settings_btn.setStyleSheet("""
            QPushButton {
                background-color: #9b59b6;
                color: white;
                border: 1px solid #8e44ad;
                border-radius: 3px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #8e44ad;
            }
            QPushButton:pressed {
                background-color: #7d3c98;
            }
        """)
        settings_layout.addWidget(self.comprehensive_settings_btn, 7, 0, 1, 2)
        
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

        # Manage templates and credentials buttons (same row)
        self.manage_templates_btn = QPushButton("Templates")
        self.manage_credentials_btn = QPushButton("Credentials")
        
        # Add icons if available
        try:
            assets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
            templates_icon_path = os.path.join(assets_dir, "templates.svg")
            credentials_icon_path = os.path.join(assets_dir, "credentials.svg")
            
            if os.path.exists(templates_icon_path):
                self.manage_templates_btn.setIcon(QIcon(templates_icon_path))
                self.manage_templates_btn.setIconSize(QSize(16, 16))
            if os.path.exists(credentials_icon_path):
                self.manage_credentials_btn.setIcon(QIcon(credentials_icon_path))
                self.manage_credentials_btn.setIconSize(QSize(16, 16))
        except Exception:
            pass
        
        self.manage_templates_btn.clicked.connect(self.manage_templates)
        self.manage_credentials_btn.clicked.connect(self.manage_credentials)
        
        for btn in [self.manage_templates_btn, self.manage_credentials_btn]:
            btn.setMinimumHeight(30)
            btn.setMaximumHeight(34)
        
        settings_layout.addWidget(self.manage_templates_btn, 9, 0)
        settings_layout.addWidget(self.manage_credentials_btn, 9, 1)
        
        # Log section (add first)
        log_group = QGroupBox("Log")
        log_layout = QVBoxLayout(log_group)
        try:
            log_layout.setContentsMargins(10, 10, 10, 10)
            log_layout.setSpacing(8)
        except Exception:
            pass
        
        
        self.log_text = LogTextEdit()
        # No minimum height - let it shrink as needed
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
        
        right_layout.addWidget(self.settings_group)
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
        print(f"DEBUG: check_credentials() called")
        if not api_key_is_set():
            print(f"DEBUG: No API key, showing credential dialog")
            dialog = CredentialSetupDialog(self)
            # Use non-blocking show() instead of blocking exec() to prevent GUI freezing
            dialog.show()
            dialog.finished.connect(lambda result: self._handle_credential_dialog_result(result))
        else:
            print(f"DEBUG: API key found, skipping dialog")
            self.add_log_message(f"{timestamp()} [auth] API key found; skipping credential setup dialog")
        print(f"DEBUG: check_credentials() completed")
    
    def _handle_credential_dialog_result(self, result):
        """Handle credential dialog result without blocking GUI"""
        if result == QDialog.DialogCode.Accepted:
            self.add_log_message(f"{timestamp()} [auth] Credentials saved securely")
        else:
            self.add_log_message(f"{timestamp()} [auth] Credential setup cancelled")
    
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
        """Open comprehensive settings to templates tab"""
        self.open_comprehensive_settings(tab_index=2)  # Templates tab
        # Refresh template combo box after dialog closes
        current_template = self.template_combo.currentText()
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
        """Open comprehensive settings to credentials tab"""
        self.open_comprehensive_settings(tab_index=1)  # Credentials tab

    def open_comprehensive_settings(self, tab_index=0):
        """Open comprehensive settings dialog to specific tab"""
        dialog = ComprehensiveSettingsDialog(self)
        if 0 <= tab_index < dialog.tab_widget.count():
            dialog.tab_widget.setCurrentIndex(tab_index)
        
        # Use non-blocking show() to prevent GUI freezing
        dialog.show()
        dialog.finished.connect(lambda result: self._handle_settings_dialog_result(result))
    
    def _handle_settings_dialog_result(self, result):
        """Handle settings dialog result without blocking GUI"""
        if result == QDialog.DialogCode.Accepted:
            self.add_log_message(f"{timestamp()} Comprehensive settings updated successfully")
        else:
            self.add_log_message(f"{timestamp()} Comprehensive settings cancelled")

    def open_help_dialog(self):
        """Open the help/documentation dialog"""
        dialog = HelpDialog(self)
        # Use non-blocking show() for help dialog
        dialog.show()

    def set_theme_mode(self, mode: str):
        """Switch theme mode and persist. mode in {'system','light','dark'}."""
        try:
            mode = mode if mode in ('system','light','dark') else 'system'
            self.settings.setValue('ui/theme', mode)
            self.apply_theme(mode)
            
            # Update tabbed gallery widget theme
            if hasattr(self, 'gallery_table') and hasattr(self.gallery_table, 'update_theme'):
                self.gallery_table.update_theme()
            
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

    def _load_base_stylesheet(self) -> str:
        """Load the base QSS stylesheet for consistent fonts and styling."""
        try:
            # Try to load from styles.qss file in the same directory as this script
            script_dir = os.path.dirname(os.path.abspath(__file__))
            qss_path = os.path.join(script_dir, "styles.qss")
            if os.path.exists(qss_path):
                with open(qss_path, 'r', encoding='utf-8') as f:
                    return f.read()
        except Exception:
            pass
        
        # Fallback: minimal inline QSS for font consistency
        return """
            /* Fallback QSS for font consistency */
            QTableWidget { font-size: 8pt; }
            QTableWidget::item { font-size: 8pt; }
            QTableWidget::item:nth-column(1) { font-size: 9pt; }
            QHeaderView::section { font-size: 8pt; font-weight: bold; }
            QPushButton { font-size: 9pt; }
            QLabel { font-size: 9pt; }
        """

    def apply_theme(self, mode: str):
        """Apply theme. 'system' uses palette-based inference; 'light'/'dark' set an application stylesheet.
        Only adjusts high-level palette/stylesheet so existing widgets that consult palette keep working.
        """
        try:
            app = QApplication.instance()
            if app is None:
                return
            
            # Load base QSS stylesheet
            base_qss = self._load_base_stylesheet()
            
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
                dark_theme_qss = """
                    QWidget { color: #e6e6e6; }
                    QToolTip { color: #e6e6e6; background-color: #333333; border: 1px solid #555; }
                """
                app.setStyleSheet(base_qss + "\n" + dark_theme_qss)
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
                app.setStyleSheet(base_qss)
            else:
                # system: apply base stylesheet but use system palette
                app.setStyleSheet(base_qss)
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
        print(f"DEBUG: start_worker called")
        if self.worker is None or not self.worker.isRunning():
            print(f"DEBUG: Creating new worker thread")
            self.worker = UploadWorker(self.queue_manager)
            print(f"DEBUG: Connecting worker signals")
            self.worker.progress_updated.connect(self.on_progress_updated)
            self.worker.gallery_started.connect(self.on_gallery_started)
            self.worker.gallery_completed.connect(self.on_gallery_completed)
            self.worker.gallery_failed.connect(self.on_gallery_failed)
            self.worker.gallery_exists.connect(self.on_gallery_exists)
            self.worker.gallery_renamed.connect(self.on_gallery_renamed)
            self.worker.log_message.connect(self.add_log_message)
            self.worker.bandwidth_updated.connect(self.on_bandwidth_updated)
            self.worker.queue_stats.connect(self.on_queue_stats)
            print(f"DEBUG: Starting worker thread")
            self.worker.start()
            print(f"DEBUG: Worker.start() called")
            print(f"DEBUG: Worker.isRunning():", self.worker.isRunning())
            print(f"DEBUG: Worker thread started successfully")
            self.add_log_message(f"{timestamp()} [general] Worker thread started")
            # Propagate auto-rename preference to worker
            try:
                self.worker.auto_rename_enabled = self.auto_rename_check.isChecked()
            except Exception:
                pass

    def on_bandwidth_updated(self, kbps: float):
        """Receive current aggregate bandwidth from worker (KB/s)."""
        self._current_transfer_kbps = kbps

    def on_queue_item_status_changed(self, path: str, old_status: str, new_status: str):
        """Handle individual queue item status changes"""
        print(f"DEBUG: GUI received status change signal: {path} from {old_status} to {new_status}")
        
        # Debug the item data before updating table
        item = self.queue_manager.get_item(path)
        if item:
            print(f"DEBUG: Item data - total_images: {getattr(item, 'total_images', 'NOT SET')}")
            print(f"DEBUG: Item data - progress: {getattr(item, 'progress', 'NOT SET')}")
            print(f"DEBUG: Item data - status: {getattr(item, 'status', 'NOT SET')}")
            print(f"DEBUG: Item data - added_time: {getattr(item, 'added_time', 'NOT SET')}")
        
        # Update table display for this specific item
        print(f"DEBUG: About to call _update_specific_gallery_display")
        self._update_specific_gallery_display(path)
        print(f"DEBUG: _update_specific_gallery_display completed")
    
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
        print(f"DEBUG: add_folders called with {len(folder_paths)} paths")
        if len(folder_paths) == 1:
            # Single folder - use the old method for backward compatibility
            self._add_single_folder(folder_paths[0])
        else:
            # Multiple folders - add each one individually for now
            for folder_path in folder_paths:
                self._add_single_folder(folder_path)
    
    def _add_single_folder(self, path: str):
        """Add a single folder using the old method."""
        print(f"DEBUG: _add_single_folder called with path={path}")
        template_name = self.template_combo.currentText()
        result = self.queue_manager.add_item(path, template_name=template_name)
        
        # Set the item to current active tab after creation
        if result == True:
            current_tab = self.gallery_table.current_tab if hasattr(self.gallery_table, 'current_tab') else "Main"
            item = self.queue_manager.get_item(path)
            if item and current_tab != "Main":
                # Get tab info for proper tab_id assignment
                tab_info = self.tab_manager.get_tab_by_name(current_tab)
                if tab_info:
                    item.tab_name = current_tab
                    item.tab_id = tab_info.id
                    self.queue_manager._save_single_item(item)
        
        if result == True:
            self.add_log_message(f"{timestamp()} [queue] Added to queue: {os.path.basename(path)}")
            # Add to table display
            item = self.queue_manager.get_item(path)
            if item:
                self._add_gallery_to_table(item)
                # Force immediate table refresh to ensure visibility
                QTimer.singleShot(50, self._update_scanned_rows)
        elif result == "duplicate":
            # Handle duplicate gallery - move network call to background
            gallery_name = sanitize_gallery_name(os.path.basename(path))
            
            # Show immediate message and defer network check
            self.add_log_message(f"{timestamp()} [queue] Checking for existing gallery '{gallery_name}'...")
            QTimer.singleShot(1, lambda: self._check_gallery_exists_background(path, gallery_name, template_name))
        else:
            self.add_log_message(f"{timestamp()} [queue] Failed to add: {os.path.basename(path)} (no images or already in queue)")
    
    def _check_gallery_exists_background(self, path: str, gallery_name: str, template_name: str):
        """Check if gallery exists in background and show dialog on main thread"""
        # This runs in a deferred timer, but the network call should be in a proper thread
        # For now, we'll do the check but it's still somewhat blocking
        # TODO: Move to a proper worker thread for complete non-blocking operation
        try:
            from imxup import check_if_gallery_exists
            existing_files = check_if_gallery_exists(gallery_name)
            
            # Use QTimer to ensure dialog shows on main thread
            QTimer.singleShot(0, lambda: self._show_gallery_exists_dialog(path, gallery_name, template_name, existing_files))
        except Exception as e:
            self.add_log_message(f"{timestamp()} [queue] Error checking gallery existence: {e}")
            # On error, allow the addition
            QTimer.singleShot(0, lambda: self._force_add_gallery(path, gallery_name, template_name))
    
    def _show_gallery_exists_dialog(self, path: str, gallery_name: str, template_name: str, existing_files: list):
        """Show gallery exists dialog on main thread"""
        message = f"Gallery '{gallery_name}' already exists with {len(existing_files)} files.\n\nContinue with upload anyway?"
        msgbox = QMessageBox(self)
        msgbox.setWindowTitle("Gallery Already Exists")
        msgbox.setText(message)
        msgbox.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msgbox.setDefaultButton(QMessageBox.StandardButton.No)
        msgbox.open()
        msgbox.finished.connect(lambda result: self._handle_gallery_exists_confirmation(result, path, gallery_name, template_name))
    
    def _handle_gallery_exists_confirmation(self, result, path: str, gallery_name: str, template_name: str):
        """Handle gallery exists confirmation"""
        if result == QMessageBox.StandardButton.Yes:
            self._force_add_gallery(path, gallery_name, template_name)
        else:
            self.add_log_message(f"{timestamp()} [queue] Skipped: {os.path.basename(path)} (user cancelled)")
    
    def _force_add_gallery(self, path: str, gallery_name: str, template_name: str):
        """Force add gallery to queue and update display"""
        self.queue_manager._force_add_item(path, gallery_name, template_name)
        
        # Set the item to current active tab
        current_tab = self.gallery_table.current_tab if hasattr(self.gallery_table, 'current_tab') else "Main"
        item = self.queue_manager.get_item(path)
        if item and current_tab != "Main":
            tab_info = self.tab_manager.get_tab_by_name(current_tab)
            if tab_info:
                item.tab_name = current_tab
                item.tab_id = tab_info.id
                self.queue_manager._save_single_item(item)
        
        self.add_log_message(f"{timestamp()} [queue] Added to queue (user confirmed): {os.path.basename(path)}")
        # Add to table display
        if item:
            self._add_gallery_to_table(item)
    
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
            
            # Set all added items to current active tab
            current_tab = self.gallery_table.current_tab if hasattr(self.gallery_table, 'current_tab') else "Main"
            if current_tab != "Main" and results['added_paths']:
                tab_info = self.tab_manager.get_tab_by_name(current_tab)
                if tab_info:
                    for path in results['added_paths']:
                        item = self.queue_manager.get_item(path)
                        if item:
                            item.tab_name = current_tab
                            item.tab_id = tab_info.id
                            self.queue_manager._save_single_item(item)
            
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
            
            # Add all successfully added items to table
            for path in results.get('added_paths', []):
                item = self.queue_manager.get_item(path)
                if item:
                    self._add_gallery_to_table(item)
            
            # Force immediate table refresh to ensure visibility
            if results.get('added_paths'):
                QTimer.singleShot(50, self._update_scanned_rows)
            
        except Exception as e:
            self.add_log_message(f"{timestamp()} [queue] Error adding multiple folders: {str(e)}")
        finally:
            progress.close()
    
    def add_folder_from_command_line(self, folder_path: str):
        """Add folder from command line (single instance)"""
        if folder_path and os.path.isdir(folder_path):
            self.add_folders([folder_path])
        
        # Show window if hidden or bring to front
        if not self.isVisible():
            self.show()
        self.raise_()
        self.activateWindow()
    
    def _add_gallery_to_table(self, item: GalleryQueueItem):
        """Add a new gallery item to the table without rebuilding"""
        row = self.gallery_table.rowCount()
        self.gallery_table.setRowCount(row + 1)
        
        # Update mappings
        self.path_to_row[item.path] = row
        self.row_to_path[row] = item.path
        
        # Initialize scan state tracking
        self._last_scan_states[item.path] = item.scan_complete
        
        # Populate the new row
        self._populate_table_row(row, item)
    
    def _remove_gallery_from_table(self, path: str):
        """Remove a gallery from the table and update mappings"""
        if path not in self.path_to_row:
            return
            
        row_to_remove = self.path_to_row[path]
        self.gallery_table.removeRow(row_to_remove)
        
        # Update mappings - shift all rows after the removed one
        del self.path_to_row[path]
        del self.row_to_path[row_to_remove]
        
        # Clean up scan state tracking
        self._last_scan_states.pop(path, None)
        
        # Shift mappings for all rows after the removed one
        new_path_to_row = {}
        new_row_to_path = {}
        for old_row, path_val in self.row_to_path.items():
            new_row = old_row if old_row < row_to_remove else old_row - 1
            new_path_to_row[path_val] = new_row
            new_row_to_path[new_row] = path_val
        
        self.path_to_row = new_path_to_row
        self.row_to_path = new_row_to_path
    
    def _update_path_mappings_after_removal(self, removed_row: int):
        """Update path mappings after a row is removed"""
        # Remove the mapping for the removed row
        removed_path = self.row_to_path.get(removed_row)
        if removed_path:
            self.path_to_row.pop(removed_path, None)
        self.row_to_path.pop(removed_row, None)
        
        # Shift all mappings for rows after the removed one
        new_path_to_row = {}
        new_row_to_path = {}
        
        for old_row, path in self.row_to_path.items():
            new_row = old_row if old_row < removed_row else old_row - 1
            new_path_to_row[path] = new_row
            new_row_to_path[new_row] = path
        
        self.path_to_row = new_path_to_row
        self.row_to_path = new_row_to_path
    
    def _get_row_for_path(self, path: str) -> Optional[int]:
        """Thread-safe getter for path-to-row mapping"""
        with QMutexLocker(self._path_mapping_mutex):
            return self.path_to_row.get(path)
    
    def _set_path_row_mapping(self, path: str, row: int):
        """Thread-safe setter for path-to-row mapping"""
        with QMutexLocker(self._path_mapping_mutex):
            self.path_to_row[path] = row
            self.row_to_path[row] = path
    
    def _rebuild_path_mappings(self):
        """Rebuild path mappings from current table state"""
        new_path_to_row = {}
        new_row_to_path = {}
        
        for row in range(self.gallery_table.rowCount()):
            name_item = self.gallery_table.item(row, 1)
            if name_item:
                path = name_item.data(Qt.ItemDataRole.UserRole)
                if path:
                    new_path_to_row[path] = row
                    new_row_to_path[row] = path
        
        with QMutexLocker(self._path_mapping_mutex):
            self.path_to_row = new_path_to_row
            self.row_to_path = new_row_to_path
    
    def _update_specific_gallery_display(self, path: str):
        """Update a specific gallery's display with background tab support - NON-BLOCKING"""
        item = self.queue_manager.get_item(path)
        if not item:
            return
            
        # If this is a new item, add it to the table
        if path not in self.path_to_row:
            self._add_gallery_to_table(item)
            return
        
        # Check if row is currently visible for performance optimization
        row = self.path_to_row.get(path)
        print(f"DEBUG: _update_specific_gallery_display - row={row}, path_to_row has path: {path in self.path_to_row}")
        if row is not None and 0 <= row < self.gallery_table.rowCount():
            print(f"DEBUG: Row {row} is valid, checking update queue")
            # Use table update queue for visible rows (includes hidden row filtering)
            if hasattr(self, '_table_update_queue'):
                print(f"DEBUG: Using _table_update_queue to update row {row}")
                self._table_update_queue.queue_update(path, item, 'full')
            else:
                print(f"DEBUG: No _table_update_queue, using direct update for row {row}")
                # Fallback to direct update
                QTimer.singleShot(0, lambda: self._populate_table_row(row, item))
        else:
            # If update fails, try full table refresh as last resort
            QTimer.singleShot(0, self.update_queue_display)
    
    def _get_cached_theme(self):
        """Get cached theme info to avoid expensive palette calculations"""
        current_time = time.time()
        if current_time - self._theme_cache_time > 1.0:  # Cache for 1 second
            try:
                pal = self.palette()
                _bg = pal.window().color()
                self._cached_is_dark_mode = (0.2126 * _bg.redF() + 0.7152 * _bg.greenF() + 0.0722 * _bg.blueF()) < 0.5
                self._theme_cache_time = current_time
            except Exception:
                pass
        return self._cached_is_dark_mode

    def _populate_table_row(self, row: int, item: GalleryQueueItem):
        """Update row data immediately with proper font consistency - COMPLETE VERSION"""
        _is_dark_mode = self._get_cached_theme()
        
        # Order number (numeric-sorting item)
        order_item = NumericTableWidgetItem(item.insertion_order)
        order_item.setFlags(order_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        order_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        font = order_item.font()
        font.setPointSize(8)
        order_item.setFont(font)
        self.gallery_table.setItem(row, 0, order_item)
        
        # Gallery name and path
        display_name = item.name or os.path.basename(item.path) or "Unknown"
        name_item = QTableWidgetItem(display_name)
        name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        name_item.setData(Qt.ItemDataRole.UserRole, item.path)
        # Gallery name column gets font size 9 (1pt larger than others)
        font = name_item.font()
        font.setPointSize(9)
        name_item.setFont(font)
        self.gallery_table.setItem(row, 1, name_item)
        
        # Upload progress - start blank until images are counted
        total_images = getattr(item, 'total_images', 0) or 0
        uploaded_images = getattr(item, 'uploaded_images', 0) or 0
        print(f"DEBUG: _populate_table_row for {item.path}: total_images={total_images}, uploaded_images={uploaded_images}")
        if total_images > 0:
            uploaded_text = f"{uploaded_images}/{total_images}"
            uploaded_item = QTableWidgetItem(uploaded_text)
            uploaded_item.setFlags(uploaded_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            uploaded_item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
            # PyQt is retarded, manually set font
            font = uploaded_item.font()
            font.setPointSize(8)
            uploaded_item.setFont(font)
            self.gallery_table.setItem(row, 2, uploaded_item)
        else:
            print(f"DEBUG: No uploaded column set because total_images={total_images} <= 0")
        
        # Progress bar
        progress_widget = self.gallery_table.cellWidget(row, 3)
        if not isinstance(progress_widget, TableProgressWidget):
            progress_widget = TableProgressWidget()
            self.gallery_table.setCellWidget(row, 3, progress_widget)
        progress_widget.update_progress(item.progress, item.status)
        
        # Status icon
        self._set_status_cell_icon(row, item.status)
        
        
        # Added time
        added_text = ""
        if item.added_time:
            try:
                added_dt = datetime.fromtimestamp(item.added_time)
                added_text = added_dt.strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, OSError, OverflowError):
                added_text = ""
        added_item = QTableWidgetItem(added_text)
        print(f"DEBUG: Setting added column for {item.path}: text='{added_text}', font will be 8pt")
        added_item.setFlags(added_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        added_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        font = added_item.font()
        font.setPointSize(8)
        added_item.setFont(font)
        self.gallery_table.setItem(row, 5, added_item)
        
        # Finished time
        finished_text = ""
        if item.finished_time:
            try:
                finished_dt = datetime.fromtimestamp(item.finished_time)
                finished_text = finished_dt.strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, OSError, OverflowError):
                finished_text = ""
        finished_item = QTableWidgetItem(finished_text)
        finished_item.setFlags(finished_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        finished_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        font = finished_item.font()
        font.setPointSize(8)
        finished_item.setFont(font)
        self.gallery_table.setItem(row, 6, finished_item)
        
        # Size column with consistent binary formatting
        size_bytes = getattr(item, 'total_size', 0) or 0
        size_text = ""
        if size_bytes > 0:
            size_text = self._format_size_consistent(size_bytes)
        size_item = QTableWidgetItem(size_text)
        size_item.setFlags(size_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        size_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        # PyQt is retarded, manually set font
        font = size_item.font()
        font.setPointSize(8)
        size_item.setFont(font)
        self.gallery_table.setItem(row, 8, size_item)
        
        # Transfer speed column
        transfer_text = ""
        current_rate_kib = float(getattr(item, 'current_kibps', 0.0) or 0.0)
        final_rate_kib = float(getattr(item, 'final_kibps', 0.0) or 0.0)
        try:
            from imxup import format_binary_rate
            if item.status == "uploading" and current_rate_kib > 0:
                transfer_text = format_binary_rate(current_rate_kib, precision=2)
            elif final_rate_kib > 0:
                transfer_text = format_binary_rate(final_rate_kib, precision=2)
        except Exception:
            rate = current_rate_kib if item.status == "uploading" else final_rate_kib
            transfer_text = self._format_rate_consistent(rate) if rate > 0 else ""
        
        xfer_item = QTableWidgetItem(transfer_text)
        xfer_item.setFlags(xfer_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        xfer_item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        font = xfer_item.font()
        font.setPointSize(8)
        if item.status == "uploading" and transfer_text:
            font.setBold(True)
            xfer_item.setForeground(QColor(173, 216, 255, 255) if _is_dark_mode else QColor(20, 90, 150, 255))
        elif item.status in ("completed", "failed") and transfer_text:
            font.setBold(False)
            xfer_item.setForeground(QColor(255, 255, 255, 230) if _is_dark_mode else QColor(0, 0, 0, 190))
        xfer_item.setFont(font)
        self.gallery_table.setItem(row, 9, xfer_item)
        
        # Template name
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
        font = tmpl_item.font()
        font.setPointSize(8)
        tmpl_item.setFont(font)
        self.gallery_table.setItem(row, 10, tmpl_item)
        
        # Renamed status: handled by _populate_table_row() and on_gallery_renamed() signal
        # No need to duplicate the logic here
        
        # Action buttons - CREATE MISSING ACTION BUTTONS FOR NEW ITEMS
        try:
            existing_widget = self.gallery_table.cellWidget(row, 7)
            if not isinstance(existing_widget, ActionButtonWidget):
                action_widget = ActionButtonWidget()
                # Connect button signals with proper closure capture
                action_widget.start_btn.setEnabled(item.status != "scanning")
                action_widget.start_btn.clicked.connect(lambda checked, path=item.path: self.start_single_item(path))
                action_widget.stop_btn.clicked.connect(lambda checked, path=item.path: self.stop_single_item(path))
                action_widget.view_btn.clicked.connect(lambda checked, path=item.path: self.view_bbcode_files(path))
                action_widget.cancel_btn.clicked.connect(lambda checked, path=item.path: self.cancel_single_item(path))
                action_widget.update_buttons(item.status)
                self.gallery_table.setCellWidget(row, 7, action_widget)
            else:
                # Update existing widget status
                existing_widget.update_buttons(item.status)
                existing_widget.start_btn.setEnabled(item.status != "scanning")
        except Exception:
            pass
    
    def _populate_table_row_detailed(self, row: int, item: GalleryQueueItem):
        """Complete row formatting in background - TRULY NON-BLOCKING"""
        # Use background thread for expensive formatting operations
        def format_row_data():
            """Prepare formatted data in background thread"""
            try:
                # Prepare all data without touching GUI
                formatted_data = {}
                
                # Order number data
                formatted_data['order'] = item.insertion_order
                
                # Time formatting (expensive datetime operations)
                if item.added_time:
                    added_dt = datetime.fromtimestamp(item.added_time)
                    formatted_data['added_text'] = added_dt.strftime("%Y-%m-%d %H:%M:%S")
                else:
                    formatted_data['added_text'] = ""
                    
                if item.finished_time:
                    finished_dt = datetime.fromtimestamp(item.finished_time)
                    formatted_data['finished_text'] = finished_dt.strftime("%Y-%m-%d %H:%M:%S")
                else:
                    formatted_data['finished_text'] = ""
                
                return formatted_data
            except Exception:
                return None
        
        def apply_formatted_data(formatted_data):
            """Apply formatted data to table - runs on main thread"""
            if formatted_data is None or row >= self.gallery_table.rowCount():
                return
                
            try:
                # Order number (column 0) - quick operation
                order_item = NumericTableWidgetItem(formatted_data['order'])
                order_item.setFlags(order_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                order_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.gallery_table.setItem(row, 0, order_item)
                
                # Added time (column 5)
                added_item = QTableWidgetItem(formatted_data['added_text'])
                added_item.setFlags(added_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                added_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.gallery_table.setItem(row, 5, added_item)
                
                # Finished time (column 6)
                finished_item = QTableWidgetItem(formatted_data['finished_text'])
                finished_item.setFlags(finished_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                finished_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                try:
                    font = finished_item.font()
                    font.setPointSize(8)
                    finished_item.setFont(font)
                except Exception:
                    pass
                self.gallery_table.setItem(row, 6, finished_item)
                
                # Apply minimal styling to uploaded count
                uploaded_item = self.gallery_table.item(row, 2)
                if uploaded_item:
                    uploaded_item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
                
            except Exception:
                pass  # Fail silently
        
        # Execute formatting in background, then apply on main thread
        task = BackgroundTask(format_row_data)
        task.signals.finished.connect(apply_formatted_data)
        task.signals.error.connect(lambda err: None)  # Ignore errors
        self._thread_pool.start(task, priority=-2)  # Lower priority than icon tasks
        
        # Size and transfer rate (expensive formatting) - only call if not already set
        # Check if size column already has a value to avoid unnecessary updates during uploads
        size_item_existing = self.gallery_table.item(row, 8)
        if (item.scan_complete and hasattr(item, 'total_size') and item.total_size > 0 and 
            (not size_item_existing or not size_item_existing.text().strip())):
            self._update_size_and_transfer_columns(row, item, _is_dark_mode)
    
    def _update_size_and_transfer_columns(self, row: int, item: GalleryQueueItem, _is_dark_mode: bool):
        """Update size and transfer columns with proper formatting"""
        # Size (column 8)
        size_bytes = int(getattr(item, 'total_size', 0) or 0)
        if not self._format_functions_cached:
            try:
                from imxup import format_binary_size, format_binary_rate
                self._format_binary_size = format_binary_size
                self._format_binary_rate = format_binary_rate
                self._format_functions_cached = True
            except Exception:
                self._format_binary_size = lambda x, **kwargs: f"{x} B"
                self._format_binary_rate = lambda x, **kwargs: self._format_rate_consistent(x, 2)
        
        try:
            size_text = self._format_binary_size(size_bytes, precision=2)
        except Exception:
            size_text = f"{size_bytes} B" if size_bytes else ""
        size_item = QTableWidgetItem(size_text)
        size_item.setFlags(size_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        size_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        try:
            font = size_item.font()
            font.setPointSize(8)
            size_item.setFont(font)
        except Exception:
            pass
        self.gallery_table.setItem(row, 8, size_item)
        
        # Transfer rate (column 9)
        if item.status == "uploading" and hasattr(item, 'current_kibps') and item.current_kibps:
            try:
                transfer_text = self._format_binary_rate(float(item.current_kibps), precision=1)
            except Exception:
                transfer_text = f"{item.current_kibps:.1f} KiB/s" if item.current_kibps else ""
        elif hasattr(item, 'final_kibps') and item.final_kibps:
            try:
                transfer_text = self._format_binary_rate(float(item.final_kibps), precision=1)
            except Exception:
                transfer_text = f"{item.final_kibps:.1f} KiB/s"
        else:
            transfer_text = ""
        
        xfer_item = QTableWidgetItem(transfer_text)
        xfer_item.setFlags(xfer_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        xfer_item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        try:
            font = xfer_item.font()
            font.setPointSize(8)
            if item.status == "uploading" and transfer_text:
                font.setBold(True)
                xfer_item.setForeground(QColor(173, 216, 255, 255) if _is_dark_mode else QColor(20, 90, 150, 255))
            else:
                font.setBold(False)
                if transfer_text:
                    xfer_item.setForeground(QColor(0, 0, 0, 160))
            xfer_item.setFont(font)
        except Exception:
            pass
        self.gallery_table.setItem(row, 9, xfer_item)
    
    def _populate_table_row_working(self, row: int, item: GalleryQueueItem):
        """Just use the full table refresh - it works"""
        QTimer.singleShot(0, self.update_queue_display)

    def _initialize_table_from_queue(self):
        """Initialize table from existing queue items - called once on startup"""
        # Clear any existing mappings
        self.path_to_row.clear()
        self.row_to_path.clear()
        
        # Get all items and build table
        items = self.queue_manager.get_all_items()
        self.gallery_table.setRowCount(len(items))
        
        for row, item in enumerate(items):
            # Update mappings
            self.path_to_row[item.path] = row
            self.row_to_path[row] = item.path
            
            # Populate the row
            self._populate_table_row(row, item)
            
            # Initialize scan state tracking
            self._last_scan_states[item.path] = item.scan_complete
        
        # After building the table, apply the current tab filter
        if hasattr(self.gallery_table, 'refresh_filter'):
            QTimer.singleShot(0, self.gallery_table.refresh_filter)

    def _update_scanned_rows(self):
        """Update only rows where scan completion status has changed - ORIGINAL VERSION"""
        items = self.queue_manager.get_all_items()
        updated_any = False
        
        for item in items:
            # Check if scan completion status changed
            last_state = self._last_scan_states.get(item.path, False)
            current_state = item.scan_complete
            
            # Check for scan completion changes
            
            if last_state != current_state:
                # Scan completion status changed, update this row
                self._last_scan_states[item.path] = current_state
                updated_any = True
                # Scan state changed
                
                # Only update the specific row that changed
                row = self.path_to_row.get(item.path)
                if row is not None and row < self.gallery_table.rowCount():
                    # Update only the columns that need updating for this specific item
                    # Upload count (column 2) - ONLY update existing items, never create new ones
                    if item.total_images > 0:
                        uploaded_text = f"{item.uploaded_images}/{item.total_images}"
                        existing_item = self.gallery_table.item(row, 2)
                        if existing_item:
                            existing_item.setText(uploaded_text)
                        # DO NOT create new items - font issues
                    
                    # Size (column 8) - ONLY update existing items, never create new ones
                    if item.total_size > 0:
                        size_text = self._format_size_consistent(item.total_size)
                        existing_item = self.gallery_table.item(row, 8)
                        if existing_item:
                            existing_item.setText(size_text)
                            # No need to fix font - should be correct from creation
                        # DO NOT create new items - font issues
                    
                    # Update status column (column 4)
                    self._set_status_cell_icon(row, item.status)
                    
                    
                    # Update action column (column 7) for any status change
                    action_widget = self.gallery_table.cellWidget(row, 7)
                    if isinstance(action_widget, ActionButtonWidget):
                        print(f"DEBUG: Updating action buttons for {item.path}, status: {item.status}")
                        action_widget.update_buttons(item.status)
                        if item.status == "ready":
                            action_widget.start_btn.setEnabled(True)
        
        # Update button counts if any scans completed (status may have changed to ready)
        if updated_any:
            QTimer.singleShot(0, self._update_button_counts)

    def update_queue_display(self):
        """Update the gallery table display - DEPRECATED: Use targeted updates instead"""
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
            # Gallery name column gets font size 9 (1px larger than others)
            try:
                font = name_item.font()
                font.setPointSize(9)
                name_item.setFont(font)
            except Exception:
                pass
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
            try:
                font = finished_item.font()
                font.setPointSize(8)
                finished_item.setFont(font)
            except Exception:
                pass
            self.gallery_table.setItem(row, 6, finished_item)
            
            # Size (from scanned total_size) - ONLY set if not already set to avoid unnecessary updates
            existing_size_item = self.gallery_table.item(row, 8)
            if existing_size_item is None or not existing_size_item.text().strip():
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
                size_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)  # Consistent with other method
                try:
                    font = size_item.font()
                    font.setPointSize(8)
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
                    transfer_text = format_binary_rate(current_rate_kib, precision=2)
                elif final_rate_kib > 0:
                    transfer_text = format_binary_rate(final_rate_kib, precision=2)
                else:
                    transfer_text = ""
            except Exception:
                # Fallback formatting
                rate = current_rate_kib if item.status == "uploading" else final_rate_kib
                transfer_text = self._format_rate_consistent(rate) if rate > 0 else ""
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

            # Renamed status: handled by _populate_table_row() and on_gallery_renamed() signal
            # No need to duplicate the logic here

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
            count_startable = sum(1 for item in items if item.status in ("ready", "paused", "incomplete", "scanning"))
            count_pausable = sum(1 for item in items if item.status in ("uploading", "queued"))
            count_completed = sum(1 for item in items if item.status == "completed")

            # Update button texts with counts (preserve leading space for visual alignment)
            self.start_all_btn.setText(f" Start All ({count_startable})")
            self.pause_all_btn.setText(f" Pause All ({count_pausable})")
            self.clear_completed_btn.setText(f" Clear Completed ({count_completed})")

            # Enable/disable based on counts
            self.start_all_btn.setEnabled(count_startable > 0)
            self.pause_all_btn.setEnabled(count_pausable > 0)
            self.clear_completed_btn.setEnabled(count_completed > 0)

            # Disable settings when any items are queued or uploading
            count_queued = sum(1 for item in items if item.status == "queued")
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
    
    def _update_button_counts(self):
        """Update button counts and states without rebuilding the table"""
        try:
            # Periodically rebuild status counts to prevent drift
            if not hasattr(self, '_last_counter_rebuild') or time.time() - self._last_counter_rebuild > 5.0:
                self.queue_manager._rebuild_status_counts()
                self._last_counter_rebuild = time.time()
                
            # Use efficient status counters instead of iterating through all items
            status_counts = self.queue_manager.get_status_counts()
            count_startable = (status_counts.get("ready", 0) + 
                             status_counts.get("paused", 0) + 
                             status_counts.get("incomplete", 0) + 
                             status_counts.get("scanning", 0))
            count_pausable = (status_counts.get("uploading", 0) + 
                            status_counts.get("queued", 0))
            count_completed = status_counts.get("completed", 0)

            # Update button texts with counts (preserve leading space for visual alignment)
            self.start_all_btn.setText(f" Start All ({count_startable})")
            self.pause_all_btn.setText(f" Pause All ({count_pausable})")
            self.clear_completed_btn.setText(f" Clear Completed ({count_completed})")

            # Enable/disable based on counts
            self.start_all_btn.setEnabled(count_startable > 0)
            self.pause_all_btn.setEnabled(count_pausable > 0)
            self.clear_completed_btn.setEnabled(count_completed > 0)
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
        # Update Stats and Speed box values
        # Skip expensive network call for unnamed count - defer to background update
        QTimer.singleShot(100, self._update_unnamed_count_background)
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
        # Use consistent size formatting
        total_size_str = self._format_size_consistent(total_size_acc)
        # Show transferred in Speed
        try:
            self.speed_transferred_value_label.setText(f"{total_size_str}")
        except Exception:
            pass
        # Current transfer speed: calculate live from uploading items
        current_kibps = 0.0
        any_uploading = any(it.status == "uploading" for it in items)
        if any_uploading:
            # Calculate current speed from all uploading items
            for item in items:
                if item.status == "uploading":
                    item_speed = float(getattr(item, 'current_kibps', 0.0) or 0.0)
                    current_kibps += item_speed
            # Also use the worker's reported speed if available
            worker_speed = float(getattr(self, "_current_transfer_kbps", 0.0))
            current_kibps = max(current_kibps, worker_speed)
        
        # Format speeds with consistent binary units
        try:
            from imxup import format_binary_rate
            current_speed_str = format_binary_rate(current_kibps, precision=2) if current_kibps > 0 else "0.00 KiB/s"
            fastest_speed_str = format_binary_rate(float(fastest_kbps), precision=2) if fastest_kbps > 0 else "0.00 KiB/s"
        except Exception:
            current_speed_str = self._format_rate_consistent(current_kibps)
            fastest_speed_str = self._format_rate_consistent(fastest_kbps)
        
        self.speed_current_value_label.setText(current_speed_str)
        self.speed_fastest_value_label.setText(fastest_speed_str)
        # Status summary text is updated via signal handlers to avoid timer-driven churn
    
    
    
    # Removed _refresh_active_upload_indicators to prevent GUI blocking
    
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
        
        # Update button counts after gallery starts
        QTimer.singleShot(0, self._update_button_counts)
    
    def on_progress_updated(self, path: str, completed: int, total: int, progress_percent: int, current_image: str):
        """Handle progress updates from worker - NON-BLOCKING"""
        # Only update the data model (fast operation)
        with QMutexLocker(self.queue_manager.mutex):
            if path in self.queue_manager.items:
                item = self.queue_manager.items[path]
                item.uploaded_images = completed
                item.total_images = total
                item.progress = progress_percent
                item.current_image = current_image
                # Update live transfer speed based on progress and estimated bytes
                try:
                    if item.start_time and item.total_size > 0:
                        elapsed = max(time.time() - float(item.start_time), 0.001)
                        # Estimate uploaded bytes from progress percentage and total size
                        estimated_uploaded = (progress_percent / 100.0) * item.total_size
                        item.current_kibps = (estimated_uploaded / elapsed) / 1024.0
                except Exception:
                    pass

        # Add to batched progress updates for non-blocking GUI updates
        self._progress_batcher.add_update(path, completed, total, progress_percent, current_image)
        
    def _process_batched_progress_update(self, path: str, completed: int, total: int, progress_percent: int, current_image: str):
        """Process batched progress updates on main thread - minimal operations only"""
        try:
            # Get fresh data from model
            item = self.queue_manager.get_item(path)
            if not item:
                return
                
            # Find row (thread-safe lookup)
            matched_row = self._get_row_for_path(path)
            if matched_row is None or matched_row >= self.gallery_table.rowCount():
                return
                
            # Update essential columns directly since table update queue may not work
            # Upload progress column (column 2)
            uploaded_text = f"{completed}/{total}" if total > 0 else "0/?"
            uploaded_item = QTableWidgetItem(uploaded_text)
            uploaded_item.setFlags(uploaded_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            uploaded_item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
            font = uploaded_item.font()
            font.setPointSize(8)
            uploaded_item.setFont(font)
            self.gallery_table.setItem(matched_row, 2, uploaded_item)
            
            # Progress bar (column 3)
            progress_widget = self.gallery_table.cellWidget(matched_row, 3)
            if isinstance(progress_widget, TableProgressWidget):
                progress_widget.update_progress(progress_percent, item.status)
            
            # Transfer speed column (column 9) - show live speed for uploading items
            if item.status == "uploading":
                current_rate_kib = float(getattr(item, 'current_kibps', 0.0) or 0.0)
                try:
                    from imxup import format_binary_rate
                    if current_rate_kib > 0:
                        transfer_text = format_binary_rate(current_rate_kib, precision=2)
                    else:
                        # Show visual indicator even when speed is 0
                        transfer_text = "Uploading..."
                except Exception:
                    if current_rate_kib > 0:
                        transfer_text = self._format_rate_consistent(current_rate_kib)
                    else:
                        transfer_text = "Uploading..."
                
                xfer_item = QTableWidgetItem(transfer_text)
                xfer_item.setFlags(xfer_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                xfer_item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
                font = xfer_item.font()
                font.setPointSize(8)
                font.setBold(True)
                xfer_item.setFont(font)
                # Use live transfer color
                _is_dark_mode = self._get_cached_theme()
                xfer_item.setForeground(QColor(173, 216, 255, 255) if _is_dark_mode else QColor(20, 90, 150, 255))
                self.gallery_table.setItem(matched_row, 9, xfer_item)
            
            # Handle completion when all images uploaded OR progress reaches 100%
            if completed >= total or progress_percent >= 100:
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
                
                # Update action buttons for completed status
                action_widget = self.gallery_table.cellWidget(matched_row, 7)
                if isinstance(action_widget, ActionButtonWidget):
                    action_widget.update_buttons(item.status)
                
                # Update finished time column
                finished_dt = datetime.fromtimestamp(item.finished_time)
                finished_text = finished_dt.strftime("%Y-%m-%d %H:%M:%S")
                finished_item = QTableWidgetItem(finished_text)
                finished_item.setFlags(finished_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                finished_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                try:
                    font = finished_item.font()
                    font.setPointSize(8)
                    finished_item.setFont(font)
                except Exception:
                    pass
                self.gallery_table.setItem(matched_row, 6, finished_item)

                # Compute and freeze final transfer speed for this item
                try:
                    elapsed = max(float(item.finished_time or time.time()) - float(item.start_time or item.finished_time), 0.001)
                    item.final_kibps = (float(getattr(item, 'uploaded_bytes', 0) or 0) / elapsed) / 1024.0
                    item.current_kibps = 0.0
                except Exception:
                    pass
                
                # Render Transfer column (9) - use cached function
                try:
                    if hasattr(self, '_format_binary_rate'):
                        final_text = self._format_binary_rate(item.final_kibps, precision=1) if item.final_kibps > 0 else ""
                    else:
                        final_text = f"{item.final_kibps:.1f} KiB/s" if item.final_kibps > 0 else ""
                except Exception:
                    final_text = ""
                xfer_item = QTableWidgetItem(final_text)
                xfer_item.setFlags(xfer_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                xfer_item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
                try:
                    font = xfer_item.font()
                    font.setPointSize(8)
                    font.setBold(False)
                    xfer_item.setFont(font)
                    if final_text:
                        xfer_item.setForeground(QColor(0, 0, 0, 160))
                except Exception:
                    pass
                self.gallery_table.setItem(matched_row, 9, xfer_item)
                
        except Exception:
            pass  # Fail silently to prevent blocking
    
    def on_gallery_completed(self, path: str, results: dict):
        """Handle gallery completion - minimal GUI thread work, everything else deferred"""
        # ONLY critical GUI updates on the main thread - keep this minimal!
        with QMutexLocker(self.queue_manager.mutex):
            if path in self.queue_manager.items:
                item = self.queue_manager.items[path]
                # Essential status update only
                total = int(results.get('total_images') or 0)
                success = int(results.get('successful_count') or len(results.get('images', [])))
                item.total_images = total or item.total_images
                item.uploaded_images = success
                item.status = "completed" if success >= (total or success) else "failed"
                item.progress = 100 if success >= (total or success) else int((success / max(total, 1)) * 100)
                item.gallery_url = results.get('gallery_url', '')
                item.gallery_id = results.get('gallery_id', '')
                item.finished_time = time.time()
                # Quick transfer rate calculation
                try:
                    elapsed = max(float(item.finished_time or time.time()) - float(item.start_time or item.finished_time), 0.001)
                    item.final_kibps = (float(results.get('uploaded_size', 0) or 0) / elapsed) / 1024.0
                    item.current_kibps = 0.0
                except Exception:
                    pass
        
        # Force final progress update to show 100% completion
        if path in self.queue_manager.items:
            final_item = self.queue_manager.items[path]
            self._progress_batcher.add_update(path, final_item.uploaded_images, final_item.total_images, 100, "")
        
        # Delegate heavy file I/O to background thread immediately
        self.completion_worker.process_completion(path, results, self)
        
        # Handle other completion work synchronously to avoid UI race conditions
        self._handle_completion_immediate(path, results)
    
    def _handle_completion_immediate(self, path: str, results: dict):
        """Handle completion work immediately on GUI thread to maintain UI consistency"""
        # Core engine already logs upload completion details, no need to duplicate
        
        # Update current transfer speed immediately
        try:
            transfer_speed = float(results.get('transfer_speed', 0) or 0)
            self._current_transfer_kbps = transfer_speed / 1024.0
            # Also update the item's speed for consistency
            with QMutexLocker(self.queue_manager.mutex):
                if path in self.queue_manager.items:
                    item = self.queue_manager.items[path]
                    item.final_kibps = self._current_transfer_kbps
        except Exception:
            pass
        
        # Re-enable settings if no remaining active items (defer to avoid blocking)
        QTimer.singleShot(5, self._check_and_enable_settings)

        # Update display with targeted update instead of full rebuild
        self._update_specific_gallery_display(path)
        
        # Update button counts after status change
        QTimer.singleShot(0, self._update_button_counts)
        
        # Defer only the heavy stats update to avoid blocking
        QTimer.singleShot(50, lambda: self._update_stats_deferred(results))
    
    def _check_and_enable_settings(self):
        """Check if settings should be enabled - deferred to avoid blocking GUI"""
        try:
            remaining = self.queue_manager.get_all_items()
            any_active = any(i.status in ("queued", "uploading") for i in remaining)
            self.settings_group.setEnabled(not any_active)
        except Exception:
            pass
    
    def _update_unnamed_count_background(self):
        """Update unnamed gallery count in background"""
        try:
            from imxup import get_unnamed_galleries
            unnamed_galleries = get_unnamed_galleries()
            unnamed_count = len(unnamed_galleries)
            # Update on main thread
            QTimer.singleShot(0, lambda: self.stats_unnamed_value_label.setText(f"{unnamed_count}"))
        except Exception:
            # On error, show 0 and don't retry
            QTimer.singleShot(0, lambda: self.stats_unnamed_value_label.setText("0"))
    
    def _update_stats_deferred(self, results: dict):
        """Update cumulative stats in background"""
        try:
            successful_count = results.get('successful_count', 0)
            settings = QSettings("ImxUploader", "Stats")
            total_galleries = settings.value("total_galleries", 0, type=int) + 1
            total_images_acc = settings.value("total_images", 0, type=int) + successful_count
            base_total_str = settings.value("total_size_bytes_v2", "0")
            try:
                base_total = int(str(base_total_str))
            except Exception:
                base_total = settings.value("total_size_bytes", 0, type=int)
            total_size_acc = base_total + int(results.get('uploaded_size', 0) or 0)
            transfer_speed = float(results.get('transfer_speed', 0) or 0)
            current_kbps = transfer_speed / 1024.0
            fastest_kbps = settings.value("fastest_kbps", 0.0, type=float)
            if current_kbps > fastest_kbps:
                fastest_kbps = current_kbps
            settings.setValue("total_galleries", total_galleries)
            settings.setValue("total_images", total_images_acc)
            settings.setValue("total_size_bytes_v2", str(total_size_acc))
            settings.setValue("fastest_kbps", fastest_kbps)
            settings.sync()
            # Refresh progress display to show updated stats
            self.update_progress_display()
        except Exception:
            pass
    
    def on_completion_processed(self, path: str):
        """Handle when background completion processing is done"""
        # Background file generation is complete, nothing specific needed here
        # but could trigger additional UI updates if needed in the future
        pass
    
    def on_galleries_auto_archived(self, gallery_paths: List[str], reason: str):
        """Handle galleries being auto-archived"""
        try:
            count = len(gallery_paths)
            if count > 0:
                # Add log message about auto-archive
                self.add_log_message(f"{timestamp()} Auto-archived {count} galleries to Archive tab: {reason}")
                
                # Update table to reflect changes (galleries moved to Archive tab)
                self.update_table()
                
                # Show notification if enabled in settings
                if hasattr(self, 'settings') and self.settings.value("show_auto_archive_notifications", True, type=bool):
                    gallery_names = [os.path.basename(path) for path in gallery_paths[:3]]  # Show first 3
                    if count > 3:
                        names_text = ", ".join(gallery_names) + f" and {count - 3} more"
                    else:
                        names_text = ", ".join(gallery_names)
                    
                    self.add_log_message(f"{timestamp()} Auto-archived: {names_text}")
                    
        except Exception as e:
            self.add_log_message(f"{timestamp()} Error handling auto-archive notification: {e}")
    
    def on_auto_archive_error(self, error_message: str):
        """Handle auto-archive errors"""
        try:
            self.add_log_message(f"{timestamp()} Auto-archive error: {error_message}")
        except Exception as e:
            print(f"Error handling auto-archive error: {e}")
    
    def on_gallery_exists(self, gallery_name: str, existing_files: list):
        """Handle existing gallery detection"""
        json_count = sum(1 for f in existing_files if f.lower().endswith('.json'))
        message = f"Gallery '{gallery_name}' already exists with {json_count} .json file{'' if json_count == 1 else 's'}.\n\nContinue with upload anyway?"
        msgbox = QMessageBox(self)
        msgbox.setWindowTitle("Gallery Already Exists")
        msgbox.setText(message)
        msgbox.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msgbox.setDefaultButton(QMessageBox.StandardButton.No)
        msgbox.open()
        msgbox.finished.connect(lambda result: self._handle_upload_gallery_exists_confirmation(result))
    
    def _handle_upload_gallery_exists_confirmation(self, result):
        """Handle upload gallery exists confirmation"""
        if result != QMessageBox.StandardButton.Yes:
            # Cancel the upload
            self.add_log_message(f"{timestamp()} Upload cancelled by user due to existing gallery")
            # TODO: Implement proper cancellation mechanism
        else:
            self.add_log_message(f"{timestamp()} User chose to continue with existing gallery")

    def on_gallery_renamed(self, gallery_id: str):
        """Mark cells for the given gallery_id as renamed (check icon) - optimized version."""
        # Defer the expensive operation to avoid blocking GUI
        QTimer.singleShot(1, lambda: self._handle_gallery_renamed_background(gallery_id))
    
    def _handle_gallery_renamed_background(self, gallery_id: str):
        """Handle gallery renamed in background to avoid blocking"""
        try:
            # Find the gallery by ID using path mapping instead of full traversal
            found_row = None
            for path, row in self.path_to_row.items():
                item = self.queue_manager.get_item(path)
                if item and item.gallery_id == gallery_id:
                    found_row = row
                    break
            
            if found_row is not None:
                self._set_renamed_cell_icon(found_row, True)
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
        self._update_specific_gallery_display(path)
        
        # Update button counts after status change
        QTimer.singleShot(0, self._update_button_counts)
        
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
        """Open comprehensive settings to logs tab"""
        self.open_comprehensive_settings(tab_index=3)  # Logs tab
    
    def start_single_item(self, path: str):
        """Start a single item"""
        if self.queue_manager.start_item(path):
            self.add_log_message(f"{timestamp()} [queue] Started: {os.path.basename(path)}")
            self._update_specific_gallery_display(path)
            # Update button counts after status change
            QTimer.singleShot(0, self._update_button_counts)
        else:
            self.add_log_message(f"{timestamp()} [queue] Failed to start: {os.path.basename(path)}")
    
    def pause_single_item(self, path: str):
        """Pause a single item"""
        if self.queue_manager.pause_item(path):
            self.add_log_message(f"{timestamp()} [queue] Paused: {os.path.basename(path)}")
            self._update_specific_gallery_display(path)
            # Update button counts after status change
            QTimer.singleShot(0, self._update_button_counts)
        else:
            self.add_log_message(f"{timestamp()} [queue] Failed to pause: {os.path.basename(path)}")
    
    def stop_single_item(self, path: str):
        """Mark current uploading item to finish in-flight transfers, then become incomplete."""
        if self.worker and self.worker.current_item and self.worker.current_item.path == path:
            self.worker.request_soft_stop_current()
            # Optimistically reflect intent in UI without persisting as failed later
            self.queue_manager.update_item_status(path, "incomplete")
            self._update_specific_gallery_display(path)
            # Update button counts after status change
            QTimer.singleShot(0, self._update_button_counts)
            self.add_log_message(f"{timestamp()} [queue] Will stop after current transfers: {os.path.basename(path)}")
        else:
            # If not the actively uploading one, nothing to do
            self.add_log_message(f"{timestamp()} [queue] Stop requested but item not currently uploading: {os.path.basename(path)}")
        # Controls will be updated by the targeted display update above
    
    def cancel_single_item(self, path: str):
        """Cancel a queued item and put it back to ready state"""
        if path in self.queue_manager.items:
            item = self.queue_manager.items[path]
            if item.status == "queued":
                self.queue_manager.update_item_status(path, "ready")
                self.add_log_message(f"{timestamp()} [queue] Canceled queued item: {os.path.basename(path)}")
                
                # Force immediate action widget update
                if path in self.path_to_row:
                    row = self.path_to_row[path]
                    if 0 <= row < self.gallery_table.rowCount():
                        action_widget = self.gallery_table.cellWidget(row, 7)
                        if isinstance(action_widget, ActionButtonWidget):
                            action_widget.update_buttons("ready")
                
                self._update_specific_gallery_display(path)
                # Force immediate button count update
                self._update_button_counts()
    
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
        start_time = time.time()
        print(f"[TIMING] start_all_uploads() started at {start_time:.6f}")
        
        get_items_start = time.time()
        items = self.queue_manager.get_all_items()
        get_items_duration = time.time() - get_items_start
        print(f"[TIMING] get_all_items() took {get_items_duration:.6f}s")
        
        started_count = 0
        started_paths = []
        item_processing_start = time.time()
        
        # Use batch context to group all database saves into a single transaction
        with self.queue_manager.batch_updates():
            for item in items:
                if item.status in ("ready", "paused", "incomplete"):
                    start_item_begin = time.time()
                    if self.queue_manager.start_item(item.path):
                        start_item_duration = time.time() - start_item_begin
                        print(f"[TIMING] start_item({item.path}) took {start_item_duration:.6f}s")
                        started_count += 1
                        started_paths.append(item.path)
                    else:
                        start_item_duration = time.time() - start_item_begin
                        print(f"[TIMING] start_item({item.path}) failed in {start_item_duration:.6f}s")
        
        item_processing_duration = time.time() - item_processing_start
        print(f"[TIMING] Processing all items took {item_processing_duration:.6f}s")
        
        ui_update_start = time.time()
        if started_count > 0:
            self.add_log_message(f"{timestamp()} Started {started_count} uploads")
            # Update all affected items individually instead of rebuilding table
            for path in started_paths:
                self._update_specific_gallery_display(path)
            # Update button counts after state changes
            QTimer.singleShot(0, self._update_button_counts)
        else:
            self.add_log_message(f"{timestamp()} No items to start")
        
        ui_update_duration = time.time() - ui_update_start
        print(f"[TIMING] UI updates took {ui_update_duration:.6f}s")
        
        total_duration = time.time() - start_time
        print(f"[TIMING] start_all_uploads() completed in {total_duration:.6f}s total")
    
    def pause_all_uploads(self):
        """Reset all queued items back to ready (acts like Cancel for queued)"""
        items = self.queue_manager.get_all_items()
        reset_count = 0
        reset_paths = []
        with QMutexLocker(self.queue_manager.mutex):
            for item in items:
                if item.status == "queued" and item.path in self.queue_manager.items:
                    self.queue_manager.items[item.path].status = "ready"
                    reset_count += 1
                    reset_paths.append(item.path)
        
        if reset_count > 0:
            self.add_log_message(f"{timestamp()} Reset {reset_count} queued item(s) to Ready")
            # Update all affected items individually instead of rebuilding table
            for path in reset_paths:
                self._update_specific_gallery_display(path)
            # Update button counts after state changes
            QTimer.singleShot(0, self._update_button_counts)
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

            # Get paths to remove before clearing them
            comp_paths = [it.path for it in items_snapshot if it.status in ("completed", "failed")]
            
            removed_count = self.queue_manager.clear_completed()
            # Fallback: if nothing removed but UI shows completed, try explicit path removal
            if removed_count == 0 and (count_completed or count_failed):
                if comp_paths:
                    self.add_log_message(f"{timestamp()} [queue] Retrying clear via explicit path delete for {len(comp_paths)} item(s)")
                    try:
                        removed_count = self.queue_manager.remove_items(comp_paths)
                    except Exception:
                        removed_count = 0
            
            if removed_count > 0:
                # Remove items from table using targeted removal
                for path in comp_paths:
                    self._remove_gallery_from_table(path)
                
                self.add_log_message(f"{timestamp()} [queue] Cleared {removed_count} completed uploads")
                # Defer database save to prevent GUI freeze
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(100, self.queue_manager.save_persistent_queue)
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
        removed_paths = []
        self.add_log_message(f"{timestamp()} Attempting to delete {len(selected_paths)} paths")
        
        for path in selected_paths:
            # Check if item is currently uploading
            item = self.queue_manager.get_item(path)
            if item:
                self.add_log_message(f"{timestamp()} Item found with status: {item.status}")
                if item.status == "uploading":
                    self.add_log_message(f"{timestamp()} Skipping uploading item: {path}")
                    continue
            else:
                self.add_log_message(f"{timestamp()} Item not found in queue manager: {path}")
                continue
            
            # Remove from memory
            with QMutexLocker(self.queue_manager.mutex):
                if path in self.queue_manager.items:
                    del self.queue_manager.items[path]
                    removed_count += 1
                    removed_paths.append(path)
                    self.add_log_message(f"{timestamp()} [queue] Deleted: {os.path.basename(path)}")
                else:
                    self.add_log_message(f"{timestamp()} Item not found in items dict: {path}")
        
        # Update table display AFTER all deletions to avoid mapping conflicts
        if removed_paths:
            self.add_log_message(f"{timestamp()} Updating table display for {len(removed_paths)} deleted items")
            
            # Get rows to remove and sort in descending order to avoid index shifting issues
            rows_to_remove = []
            for path in removed_paths:
                if path in self.path_to_row:
                    row_to_remove = self.path_to_row[path]
                    rows_to_remove.append((row_to_remove, path))
                    self.add_log_message(f"{timestamp()} Will remove table row {row_to_remove} for {os.path.basename(path)}")
                else:
                    self.add_log_message(f"{timestamp()} No table row mapping found for {os.path.basename(path)}")
            
            # Sort by row number descending (highest first) to avoid index problems
            rows_to_remove.sort(key=lambda x: x[0], reverse=True)
            
            # Remove rows from highest to lowest
            for row_to_remove, path in rows_to_remove:
                self.add_log_message(f"{timestamp()} Removing table row {row_to_remove}")
                self.gallery_table.removeRow(row_to_remove)
            
            # Rebuild path mappings after all removals
            self._rebuild_path_mappings()
            
            # Force immediate table update
            QApplication.processEvents()
        
        if removed_count > 0:
            # Renumber remaining items
            self.queue_manager.renumber_insertion_orders()
            
            # Delete from database to prevent reloading
            try:
                self.queue_manager.store._executor.submit(self.queue_manager.store.delete_by_paths, selected_paths)
            except Exception:
                pass
            
            # Display updated by row removal above
            self.add_log_message(f"{timestamp()} Updated display")
            
            # Force GUI update
            QApplication.processEvents()
            
            # Defer database save to prevent GUI freeze
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(100, self.queue_manager.save_persistent_queue)
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
        
        # Save queue state (deferred to prevent blocking shutdown)
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(10, self.queue_manager.save_persistent_queue)
        
        # DEBUG: Check item tab_name values before shutdown
        if self.queue_manager:
            print(f"DEBUG: Before shutdown, checking a few items' tab_name values:", flush=True)
            count = 0
            for path, item in self.queue_manager.items.items():
                if count < 5:  # Check first 5 items
                    print(f"DEBUG: Item {path} has tab_name='{item.tab_name}'", flush=True)
                    count += 1
                else:
                    break
            
            self.queue_manager.shutdown()
        
        # Always stop workers and server on close
        if self.worker:
            self.worker.stop()
        
        # Stop completion worker
        if hasattr(self, 'completion_worker'):
            self.completion_worker.stop()
            self.completion_worker.wait(3000)  # Wait up to 3 seconds for shutdown
            
        self.server.stop()
        
        # Accept the close event to ensure app exits
        event.accept()

def check_single_instance(folder_path=None):
    """Check if another instance is running and send folder if needed"""
    try:
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_socket.connect(('localhost', COMMUNICATION_PORT))
        
        # Send folder path or empty string to bring window to front
        message = folder_path if folder_path else ""
        client_socket.send(message.encode('utf-8'))
        
        client_socket.close()
        return True  # Another instance is running
    except ConnectionRefusedError:
        return False  # No other instance running


def main():
    """Main function"""
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)  # Exit when window closes
    
    # Show splash screen immediately
    splash = SplashScreen()
    splash.show()
    splash.update_status("Initializing")
    
    # Handle command line arguments
    folders_to_add = []
    if len(sys.argv) > 1:
        # Accept multiple folder args (Explorer passes all selections to %V)
        for arg in sys.argv[1:]:
            if os.path.isdir(arg):
                folders_to_add.append(arg)
        # If another instance is running, forward the first folder (server is single-path)
        if folders_to_add and check_single_instance(folders_to_add[0]):
            splash.finish_and_hide()
            return
    else:
        # Check for existing instance even when no folders provided
        if check_single_instance():
            print("GUI is already running, bringing existing window to front")
            splash.finish_and_hide()
            return
    
    splash.set_status("PyQt6")
    
    # Create main window with splash updates
    window = ImxUploadGUI(splash)
    
    # Add folder from command line if provided
    if folders_to_add:
        window.add_folders(folders_to_add)
    
    # Hide splash and show main window
    splash.finish_and_hide()
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


# ComprehensiveSettingsDialog moved to imxup_settings.py

if __name__ == "__main__":
    main()