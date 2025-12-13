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
import traceback
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
    QProgressDialog, QListView, QTreeView, QStyledItemDelegate, QStyleOptionViewItem
)
from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QTimer, QMimeData, QUrl,
    QMutex, QMutexLocker, QSettings, QSize, QObject, pyqtSlot,
    QRunnable, QThreadPool, QPoint, QDir
)
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QIcon, QFont, QPixmap, QPainter, QColor, QSyntaxHighlighter, QTextCharFormat, QDesktopServices, QPainterPath, QPen, QFontMetrics, QTextDocument, QActionGroup, QDrag

# Import the core uploader functionality
from imxup import ImxToUploader, get_project_root, load_user_defaults, sanitize_gallery_name, encrypt_password, decrypt_password, rename_all_unnamed_with_session, get_config_path, build_gallery_filenames, get_central_storage_path
from imxup import create_windows_context_menu, remove_windows_context_menu
from src.utils.format_utils import format_binary_size, format_binary_rate, timestamp
from src.utils.logger import log, set_main_window
from src.gui.splash_screen import SplashScreen
from src.gui.icon_manager import IconManager, init_icon_manager, get_icon_manager
from src.gui.dialogs.log_viewer import LogViewerDialog
from src.gui.dialogs.bbcode_viewer import BBCodeViewerDialog
from src.gui.dialogs.help_dialog import HelpDialog


from src.core.engine import UploadEngine
from src.core.constants import IMAGE_EXTENSIONS
from src.storage.database import QueueStore
from src.utils.logging import get_logger
from src.gui.settings_dialog import ComprehensiveSettingsDialog
from src.gui.tab_manager import TabManager

# Import widget classes from module
from src.gui.widgets.custom_widgets import TableProgressWidget, ActionButtonWidget, OverallProgressWidget
from src.gui.widgets.context_menu_helper import GalleryContextMenuHelper
from src.gui.widgets.gallery_table import GalleryTableWidget, NumericColumnDelegate
from src.gui.widgets.tabbed_gallery import TabbedGalleryWidget, DropEnabledTabBar
from src.gui.widgets.adaptive_settings_panel import AdaptiveQuickSettingsPanel
from src.gui.widgets.worker_status_widget import WorkerStatusWidget


class AdaptiveGroupBox(QGroupBox):
    """
    Custom QGroupBox that properly propagates child widget minimum size hints to QSplitter.

    QSplitter queries the direct child widget's minimumSizeHint() to determine resize limits.
    This custom GroupBox overrides minimumSizeHint() to query its layout's minimum size,
    which includes all child widgets and their constraints.

    This ensures that when the splitter is dragged, it respects the minimum height needed
    by nested widgets (like AdaptiveQuickSettingsPanel) and prevents button overlap.
    """

    def minimumSizeHint(self):
        """
        Override to return the layout's minimum size hint.

        This propagates minimum size constraints from child widgets up to QSplitter.
        Without this, QSplitter only sees the hardcoded setMinimumHeight() value
        and doesn't know about dynamic child widget requirements.
        """
        # Get the layout's minimum size hint, which aggregates all child constraints
        layout = self.layout()
        if layout:
            layout_hint = layout.minimumSize()
            # Add small margin for GroupBox frame and title
            frame_margin = 30  # ~10px top for title, ~10px for frame, ~10px safety
            return QSize(layout_hint.width(), layout_hint.height() + frame_margin)

        # Fallback to default behavior if no layout
        return super().minimumSizeHint()


# Import queue manager classes - adding one at a time
from src.storage.queue_manager import GalleryQueueItem, QueueManager

# Import background task classes one at a time
from src.processing.tasks import (
    BackgroundTaskSignals, BackgroundTask, ProgressUpdateBatcher,
    IconCache, TableRowUpdateTask, TableUpdateQueue
)
from src.processing.upload_workers import UploadWorker

# Import dialog classes
from src.gui.dialogs.template_manager import TemplateManagerDialog, PlaceholderHighlighter
from src.gui.dialogs.log_viewer import LogViewerDialog
from src.gui.dialogs.credential_setup import CredentialSetupDialog
from src.gui.dialogs.bbcode_viewer import BBCodeViewerDialog
from src.gui.dialogs.help_dialog import HelpDialog

# Import archive support
from src.services.archive_service import ArchiveService
from src.processing.archive_coordinator import ArchiveCoordinator
from src.processing.archive_worker import ArchiveExtractionWorker
from src.utils.archive_utils import is_archive_file
from src.utils.system_utils import convert_to_wsl_path, is_wsl2


def format_timestamp_for_display(timestamp_value, include_seconds=False):
    """Format timestamp for table display with optional tooltip"""
    if not timestamp_value:
        return "", ""
    
    try:
        dt = datetime.fromtimestamp(timestamp_value)
        display_text = dt.strftime("%Y-%m-%d %H:%M")
        tooltip_text = dt.strftime("%Y-%m-%d %H:%M:%S")
        return display_text, tooltip_text
    except (ValueError, OSError, OverflowError):
        return "", ""

# Import network classes
from src.network.client import GUIImxToUploader

# Single instance communication port
COMMUNICATION_PORT = 27849

def get_assets_dir():
    """Get the correct path to the assets directory from anywhere in the module structure"""
    # Get the project root directory (go up from src/gui/ to root)
    #current_dir = os.path.dirname(os.path.abspath(__file__))  # src/gui/
    #project_root = os.path.dirname(os.path.dirname(current_dir))  # go up to root
    return os.path.join(get_project_root(), "assets")

# Simple icon helper - just passes through to IconManager
def get_icon(icon_key: str, theme_mode: str | None = None) -> QIcon:
    """Get an icon from IconManager.

    Args:
        icon_key: Icon identifier (supports legacy names like 'start', 'completed')
        theme_mode: Optional theme mode ('light'/'dark'), None = auto-detect

    Returns:
        QIcon instance
    """
    icon_mgr = get_icon_manager()
    if icon_mgr:
        return icon_mgr.get_icon(icon_key, theme_mode=theme_mode)
    return QIcon()

def check_stored_credentials():
    """Check if credentials are stored in QSettings (Registry)"""
    from imxup import get_credential

    username = get_credential('username')
    encrypted_password = get_credential('password')
    encrypted_api_key = get_credential('api_key')

    # Have username+password OR api_key
    if (username and encrypted_password) or encrypted_api_key:
        return True
    return False

def api_key_is_set() -> bool:
    """Return True if an API key exists in QSettings (Registry)."""
    from imxup import get_credential
    encrypted_api_key = get_credential('api_key')
    return bool(encrypted_api_key)

    

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
                log(f" ERROR: Completion processing error: {e}")
    
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
                    existing_unnamed = get_unnamed_galleries()  # Returns Dict[str, str]
                    if gallery_id not in existing_unnamed:
                        save_unnamed_gallery(gallery_id, gallery_name)
                        log(f" [rename] Tracking gallery for auto-rename: {gallery_name}")
            except Exception as e:
                log(f"Exception in main_window: {e}", level="error", category="ui")
                raise
                
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

            # Get template name and custom fields from the item
            item = gui_parent.queue_manager.get_item(path)
            template_name = item.template_name if item else "default"
            
            # Prepare custom fields dict
            custom_fields = {
                'custom1': item.custom1 if item else '',
                'custom2': item.custom2 if item else '',
                'custom3': item.custom3 if item else '',
                'custom4': item.custom4 if item else '',
                'ext1': item.ext1 if item else '',
                'ext2': item.ext2 if item else '',
                'ext3': item.ext3 if item else '',
                'ext4': item.ext4 if item else ''
            }
            
            # Use centralized save_gallery_artifacts function
            try:
                from imxup import save_gallery_artifacts
                written = save_gallery_artifacts(
                    folder_path=path,
                    results={
                        **results,
                        'started_at': datetime.fromtimestamp(gui_parent.queue_manager.items[path].start_time).strftime('%Y-%m-%d %H:%M:%S') if path in gui_parent.queue_manager.items and gui_parent.queue_manager.items[path].start_time else None,
                        'thumbnail_size': gui_parent.thumbnail_size_combo.currentIndex() + 1,
                        'thumbnail_format': gui_parent.thumbnail_format_combo.currentIndex() + 1,
                        'parallel_batch_size': load_user_defaults().get('parallel_batch_size', 4),
                    },
                    template_name=template_name,
                    custom_fields=custom_fields
                )
                try:
                    parts = []
                    if written.get('central'):
                        parts.append(f"central: {os.path.dirname(list(written['central'].values())[0])}")
                    if written.get('uploaded'):
                        parts.append(f"folder: {os.path.dirname(list(written['uploaded'].values())[0])}")
                    if parts:
                        log(f" [fileio] INFO: Saved gallery files to {', '.join(parts)}", category="fileio", level="debug")
                except Exception as e:
                    log(f"Exception in main_window: {e}", level="error", category="ui")
                    raise
            except Exception as e:
                log(f" ERROR: Artifact save error: {e}")
                
        except Exception as e:
            log(f" ERROR: Background completion processing error: {e}")


class LogTextEdit(QTextEdit):
    """Text edit for logs that emits a signal on double-click."""
    doubleClicked = pyqtSignal()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            try:
                self.doubleClicked.emit()
            except Exception as e:
                log(f"Exception in main_window: {e}", level="error", category="ui")
                raise
        super().mouseDoubleClickEvent(event)

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
                        print(f"ERROR: Server error: {e}")
                        
            server_socket.close()
        except Exception as e:
            print(f"ERROR: Failed to start server: {e}")
    
    def stop(self):
        self.running = False
        self.wait()

class ImxUploadGUI(QMainWindow):
    """Main GUI application"""

    # Type hints for attributes that mypy needs to see
    _current_theme_mode: str
    _cached_base_qss: str

    def __init__(self, splash=None):
        self._initializing = True  # Block recursive calls during init
        super().__init__()

        # Initialize log display settings BEFORE set_main_window() to avoid AttributeError
        self._log_show_level = False
        self._log_show_category = False

        set_main_window(self)
        self.splash = splash

        # EMERGENCY FIX: Add abort flag for clean shutdown during background loading
        self._loading_abort = False
        self._loading_phase = 0  # Track loading progress (0=not started, 1=phase1, 2=phase2, 3=complete)

        # Thread-safe file host startup tracking
        from PyQt6.QtCore import QMutex
        self._file_host_startup_mutex = QMutex()
        self._file_host_startup_expected = 0
        self._file_host_startup_completed = 0
        self._file_host_startup_complete = False

        # MILESTONE 4: Track which rows have widgets created for viewport-based lazy loading
        self._rows_with_widgets = set()  # Rows that have progress/action widgets created

        # Initialize IconManager
        if self.splash:
            self.splash.set_status("Icon Manager")
        try:
            assets_dir = get_assets_dir()
            # Setup Qt search path for stylesheet image URLs
            QDir.addSearchPath('assets', assets_dir)
            icon_mgr = init_icon_manager(assets_dir)
            # Validate icons and report any issues
            validation_result = icon_mgr.validate_icons(report=True)
        except Exception as e:
            print(f"ERROR: Failed to initialize IconManager: {e}")
            
            
        # Set main window icon
        try:
            icon = get_icon('main_window')
            if not icon.isNull():
                self.setWindowIcon(icon)
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise
        if self.splash:
            self.splash.set_status("SQLite database")
        self.queue_manager = QueueManager()
        self.queue_manager.parent = self  # Give QueueManager access to parent for settings

        # Connect queue loaded signal to refresh filter
        self.queue_manager.queue_loaded.connect(self.refresh_filter)

        # Initialize archive support
        temp_dir = Path(get_config_path()).parent / "temp"
        archive_service = ArchiveService(temp_dir)
        self.archive_coordinator = ArchiveCoordinator(archive_service, parent_widget=self)
        if self.splash:
            self.splash.set_status("QueueManager")
        
        # Initialize tab manager
        if self.splash:
            self.splash.set_status("TabManager")
        self.tab_manager = TabManager(self.queue_manager.store)
        
        # Connect queue status changes to update table display
        self.queue_manager.status_changed.connect(self.on_queue_item_status_changed)
        
        self.worker = None
        
        # Initialize completion worker for background processing
        self.completion_worker = CompletionWorker(self)

        self.completion_worker.completion_processed.connect(self.on_completion_processed)
        self.completion_worker.log_message.connect(self.add_log_message)
        self.completion_worker.start()
        if self.splash:
            self.splash.set_status("Upload Completion Worker")

        # Create worker status widget early (before FileHostWorkerManager)
        # This ensures it exists when manager tries to connect signals
        if self.splash:
            self.splash.set_status("Worker Status Widget")
        self.worker_status_widget = WorkerStatusWidget()

        # Initialize file host worker manager for background file host uploads
        if self.splash:
            self.splash.set_status("File Host Worker Manager")
        # Guard against double initialization
        if hasattr(self, 'file_host_manager') and self.file_host_manager is not None:
            log("FileHost Worker Manager already initialized, skipping", level="warning", category="file_hosts")
        else:
            try:
                from src.processing.file_host_worker_manager import FileHostWorkerManager
                self.file_host_manager = FileHostWorkerManager(self.queue_manager.store)
                self.splash.set_status("Connecting FileHostWorkerManager's signals to UI handlers")
                # Connect manager signals to UI handlers
                self.file_host_manager.test_completed.connect(self.on_file_host_test_completed)
                self.file_host_manager.upload_started.connect(self.on_file_host_upload_started)
                self.file_host_manager.upload_progress.connect(self.on_file_host_upload_progress)
                self.file_host_manager.upload_completed.connect(self.on_file_host_upload_completed)
                self.file_host_manager.upload_failed.connect(self.on_file_host_upload_failed)
                self.file_host_manager.bandwidth_updated.connect(self.on_file_host_bandwidth_updated)

                # Connect to worker status widget
                self.file_host_manager.upload_started.connect(self._on_filehost_worker_started)
                self.file_host_manager.upload_progress.connect(self._on_filehost_worker_progress)
                self.file_host_manager.upload_completed.connect(self._on_filehost_worker_completed)
                self.file_host_manager.upload_failed.connect(self._on_filehost_worker_failed)
                self.file_host_manager.storage_updated.connect(self.worker_status_widget.update_worker_storage)
                self.file_host_manager.enabled_workers_changed.connect(self._on_file_hosts_enabled_changed)
                self.file_host_manager.spinup_complete.connect(self._on_file_host_startup_spinup)

                # Connect MetricsStore signals for IMX and file host metrics display
                from src.utils.metrics_store import get_metrics_store
                metrics_store = get_metrics_store()
                if metrics_store and hasattr(metrics_store, 'signals'):
                    metrics_store.signals.host_metrics_updated.connect(
                        self.worker_status_widget._on_host_metrics_updated
                    )
                    log("MetricsStore signals connected to WorkerStatusWidget", level="debug", category="ui")

                # NOTE: init_enabled_hosts() called AFTER GUI shown (see launch_gui())
                log("FileHost Worker Manager started", level="info", category="file_hosts")
            except Exception as e:
                log(f"Failed to start FileHostWorkerManager: {e}", level="error", category="file_hosts")
                self.file_host_manager = None

        self.table_progress_widgets = {}
        self.settings = QSettings("ImxUploader", "ImxUploadGUI")
        
        # Track path-to-row mapping to avoid expensive table rebuilds
        self.path_to_row = {}  # Maps gallery path to table row number
        self.row_to_path = {}  # Maps table row number to gallery path
        self._path_mapping_mutex = QMutex()  # Thread safety for mapping access
        
        # Track scanning completion for targeted updates
        self._last_scan_states = {}  # Maps path -> scan_complete status

        # Cache expensive operations to improve responsiveness
        self._format_functions_cached = False
        
        # Pre-cache formatting functions to avoid blocking imports during progress updates
        if self.splash:
            self.splash.set_status("Pre-caching formatting functions to avoid blocking")
        self._cache_format_functions()
        
        # Initialize non-blocking components
        if self.splash:
            self.splash.set_status("QThreadPool()")
        self._thread_pool = QThreadPool()
        self._thread_pool.setMaxThreadCount(4)  # Limit background threads
        if self.splash:
            self.splash.set_status("IconCache()")
        self._icon_cache = IconCache()
        
        # Initialize progress update batcher
        if self.splash:
            self.splash.set_status("Progress Update Batcher")
        self._progress_batcher = ProgressUpdateBatcher(
            self._process_batched_progress_update,
            batch_interval=0.05  # 50ms batching
        )
        
        # Initialize table update queue
        self._table_update_queue = None  # Will be set after table creation
        
        # Enable drag and drop on main window
        self.setAcceptDrops(True)
        
        # Single instance server
        if self.splash:
            self.splash.set_status("SingleInstanceServer()")
        self.server = SingleInstanceServer()
        self.server.folder_received.connect(self.add_folder_from_command_line)
        self.server.start()
        
        if self.splash:
            self.splash.set_status("Running setup_ui()")
        self.setup_ui()
        
        # Initialize context menu helper and connect to the actual table widget
        if self.splash:
            self.splash.set_status("context menus")
        self.context_menu_helper = GalleryContextMenuHelper(self)
        self.context_menu_helper.set_main_window(self)
        self.context_menu_helper.template_change_requested.connect(
            self.context_menu_helper.set_template_for_galleries
        )
        
        # Connect context menu helper to the actual table widget used by the tabbed interface
        try:
            if hasattr(self.gallery_table, 'table'):
                # Replace the existing context menu implementation with our helper
                actual_table = self.gallery_table.table
                if hasattr(actual_table, 'show_context_menu'):
                    # Override the show_context_menu method to use our helper
                    original_show_context_menu = actual_table.show_context_menu
                    def new_show_context_menu(position):
                        self.context_menu_helper.show_context_menu_for_table(actual_table, position)
                    actual_table.show_context_menu = new_show_context_menu
        except Exception as e:
            print(f"ERROR: Could not connect context menu helper: {e}")
        
        if self.splash:
            self.splash.set_status("menu bar (setup_menu_bar())")
            self.splash.update_status("random")
        self.setup_menu_bar()
        if self.splash:
            self.splash.set_status("Running setup_system_tray()")
        self.setup_system_tray()
        if self.splash:
            self.splash.set_status("Restoring saved settings and galleries")
        self.restore_settings()
       
        # Easter egg - quick gremlin flash
        if self.splash:
            self.splash.set_status("Wiping front to back")
            QApplication.processEvents()
        
        # Initialize table update queue after table creation
        self._table_update_queue = TableUpdateQueue(self.gallery_table, self.path_to_row)
        
        # Initialize background tab update system
        self._background_tab_updates = {}  # Track updates for non-visible tabs
        self._background_update_timer = QTimer()
        self._background_update_timer.timeout.connect(self._process_background_tab_updates)
        self._background_update_timer.setSingleShot(True)

        # Uploading status icon animation (7 frames, 200ms each)
        self._upload_animation_frame = 0
        self._upload_animation_timer = QTimer()
        self._upload_animation_timer.timeout.connect(self._advance_upload_animation)
        self._upload_animation_timer.start(200)  # Animate every 200ms

        # Speed updates timer for regular refresh - COMPLETELY DISABLED
        # There's a critical issue with _update_transfer_speed_display causing hangs
        pass  # Removed timer completely

        # Sliding window for accurate bandwidth tracking
        self._bandwidth_history = []  # List of (timestamp, bytes) tuples
        self._bandwidth_window_size = 3.0  # 3 second sliding window
        
        # Connect tab manager to the tabbed gallery widget  
        #print(f"Debug: Setting TabManager in TabbedGalleryWidget: {self.tab_manager}")
        self.gallery_table.set_tab_manager(self.tab_manager)
        
        # Connect tab change signal to refresh filter and update button counts and progress
        if hasattr(self.gallery_table, 'tab_changed'):
            self.gallery_table.tab_changed.connect(self.refresh_filter)
            self.gallery_table.tab_changed.connect(self._update_button_counts)
            self.gallery_table.tab_changed.connect(self.update_progress_display)
        
        # Connect gallery move signal to handle tab assignments
        # Connect tab bar drag-drop signal directly to our handler
        if hasattr(self.gallery_table, 'tab_bar') and hasattr(self.gallery_table.tab_bar, 'galleries_dropped'):
            self.gallery_table.tab_bar.galleries_dropped.connect(self.on_galleries_moved_to_tab)
        
        # Connect selection change to refresh icons for proper light/dark variant display
        # For tabbed gallery system, connect to the inner table's selection model
        if hasattr(self.gallery_table, 'table'):
            inner_table = self.gallery_table.table
            if hasattr(inner_table, 'selectionModel'):
                selection_model = inner_table.selectionModel()
                if selection_model:
                    selection_model.selectionChanged.connect(self._on_selection_changed)

            # Connect cell click handler for template column editing
            inner_table.cellClicked.connect(self.on_gallery_cell_clicked)

            # Connect itemChanged for custom columns persistence
            inner_table.itemChanged.connect(self._on_table_item_changed)

            # MILESTONE 4: Connect scroll handler for viewport-based lazy loading
            if hasattr(inner_table, 'verticalScrollBar'):
                scrollbar = inner_table.verticalScrollBar()
                scrollbar.valueChanged.connect(self._on_table_scrolled)
                log("Connected scroll handler for viewport-based widget creation", level="debug", category="performance")
        elif hasattr(self.gallery_table, 'cellClicked'):
            # Direct connection if it's not a tabbed widget
            self.gallery_table.cellClicked.connect(self.on_gallery_cell_clicked)

            # Connect itemChanged for custom columns persistence
            self.gallery_table.itemChanged.connect(self._on_table_item_changed)

            # MILESTONE 4: Connect scroll handler for non-tabbed gallery
            if hasattr(self.gallery_table, 'verticalScrollBar'):
                scrollbar = self.gallery_table.verticalScrollBar()
                scrollbar.valueChanged.connect(self._on_table_scrolled)
                log("Connected scroll handler for viewport-based widget creation", level="debug", category="performance")
        
        # Set reference to update queue in tabbed widget for cache invalidation
        if hasattr(self.gallery_table, '_update_queue'):
            self.gallery_table._update_queue = self._table_update_queue
        
        # Ensure initial filter is applied once UI is ready
        try:
            self.refresh_filter()
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise
        
        log(f"GUI loaded", level="info", category="ui")

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
                    except Exception as e:
                        log(f"Exception in main_window: {e}", level="error", category="ui")
                        raise
                    try:
                        if hasattr(self.gallery_table, '_update_tab_tooltips'):
                            self.gallery_table._update_tab_tooltips()
                    except Exception as e:
                        log(f"Exception in main_window: {e}", level="error", category="ui")
                        raise
                
                # Progress display will update via tab_changed signal and status change events

                # Scan status
                try:
                    self._update_scan_status()
                except Exception as e:
                    log(f"Exception in main_window: {e}", level="error", category="ui")
                    raise
                
            except Exception as e:
                print(f"Timer error: {e}")

        self.update_timer.timeout.connect(_tick)
        self.update_timer.start(500)  # Start the timer
        self.check_credentials() # Check for stored credentials (only prompt if API key missing)
        self.start_worker() # Start worker thread
        # Gallery loading moved to main() with progress dialog for better perceived performance
        # Button counts and progress will be updated by refresh_filter() after filter is applied
        self.gallery_table.setFocus() # Ensure table has focus for keyboard shortcuts

        # Refresh log display settings (already initialized early to avoid AttributeError)
        self._refresh_log_display_settings()
        self._initializing = False # Clear initialization flag to allow normal tooltip updates
        log(f"ImxUploadGUI.__init__ Completed", level="debug")

    def _load_galleries_phase1(self):
        """OPTIMIZED: Phase 1 - Load critical gallery data in single pass

        This method loads gallery names and status for all items in one pass with
        setUpdatesEnabled(False) to prevent paint events, achieving 24-60x speedup.
        Expected time: 2-5 seconds for 997 galleries (was 120 seconds with batching).
        """
        if self._loading_abort:
            log("Gallery loading aborted by user", level="info", category="performance")
            return

        self._loading_phase = 1
        log("Phase 1: Loading critical gallery data...", level="info", category="performance")

        # Clear any existing mappings
        self.path_to_row.clear()
        self.row_to_path.clear()

        # MILESTONE 4: Clear widget tracking for viewport-based lazy loading
        self._rows_with_widgets.clear()

        # Get all items
        items = self.queue_manager.get_all_items()
        total_items = len(items)
        log(f"Loading {total_items} galleries from queue", level="info", category="ui")

        if total_items == 0:
            self._loading_phase = 3
            log("No galleries to load", level="info", category="performance")
            return

        # Batch load file host uploads (this is already optimized)
        try:
            self._file_host_uploads_cache = self.queue_manager.store.get_all_file_host_uploads_batch()
            log(f"Batch loaded file host uploads for {len(self._file_host_uploads_cache)} galleries",
                level="debug", category="performance")
        except Exception as e:
            log(f"Failed to batch load file host uploads: {e}", level="warning", category="performance")
            self._file_host_uploads_cache = {}

        # CRITICAL FIX: Disable table updates during bulk insert to prevent 12,961 paint events
        # This prevents Qt from repainting after EVERY QTableWidgetItem creation (50ms each)
        # Expected impact: 648 seconds → ~20 seconds (4.5× faster)
        self.gallery_table.setUpdatesEnabled(False)
        self.gallery_table.setSortingEnabled(False)
        log("Table updates disabled for bulk insert", level="debug", category="performance")

        # Set row count once
        self.gallery_table.setRowCount(total_items)

        # Set flag to defer expensive widget creation
        self._initializing = True

        try:
            # OPTIMIZATION: Process all items in ONE pass (no batching/yielding)
            # This eliminates 50 event loop cycles and reduces Phase 1 from 120s to 2-5s
            log(f"Processing all {total_items} galleries in single pass...", level="info", category="performance")

            for row, item in enumerate(items):
                # Update mappings
                self.path_to_row[item.path] = row
                self.row_to_path[row] = item.path

                # Populate row with MINIMAL data (no expensive widgets yet)
                self._populate_table_row_minimal(row, item)

                # Initialize scan state tracking
                self._last_scan_states[item.path] = item.scan_complete

        except Exception as e:
            log(f"Error in Phase 1 table population: {e}", level="error", category="performance")
            raise
        finally:
            # CRITICAL: ALWAYS re-enable updates, even on exceptions (prevents permanent UI freeze)
            self.gallery_table.setSortingEnabled(True)
            self.gallery_table.setUpdatesEnabled(True)
            log("Table updates re-enabled - Phase 1 complete", level="info", category="performance")

        # Start phase 2
        self._initializing = False
        QTimer.singleShot(50, self._load_galleries_phase2)

    def _load_galleries_phase2(self):
        """MILESTONE 4: Phase 2 - Create widgets ONLY for visible rows (viewport-based lazy loading)

        This creates progress bars and action buttons ONLY for rows currently visible
        in the viewport, drastically reducing initial load time.
        Previous: Created 997 widgets (140 seconds)
        Now: Creates ~30-40 widgets (<5 seconds)
        """
        if self._loading_abort:
            log("Phase 2 loading aborted", level="info", category="performance")
            return

        self._loading_phase = 2
        log("Phase 2: Creating widgets for VISIBLE rows only (viewport-based)...", level="info", category="performance")

        # Get visible row range
        first_visible, last_visible = self._get_visible_row_range()
        visible_rows = list(range(first_visible, last_visible + 1))

        log(f"Phase 2: Creating widgets for {len(visible_rows)} visible rows (rows {first_visible}-{last_visible})",
            level="info", category="performance")

        # CRITICAL FIX: Disable updates during widget creation
        self.gallery_table.setUpdatesEnabled(False)
        log("Table updates disabled for Phase 2 widget creation", level="debug", category="performance")

        total_visible = len(visible_rows)
        batch_size = 10  # Smaller batches for widget creation
        current_batch = 0

        def _create_widgets_batch():
            """Create widgets for the next batch of VISIBLE rows"""
            if self._loading_abort:
                log("Phase 2 widget creation aborted", level="info", category="performance")
                # Re-enable updates on abort
                self.gallery_table.setUpdatesEnabled(True)
                return

            nonlocal current_batch
            start_idx = current_batch * batch_size
            end_idx = min(start_idx + batch_size, total_visible)

            try:
                # Create widgets only for visible rows in this batch
                for i in range(start_idx, end_idx):
                    row = visible_rows[i]
                    self._create_row_widgets(row)
                    self._rows_with_widgets.add(row)

                # Update progress
                progress_pct = int((end_idx / total_visible) * 100) if total_visible > 0 else 100
                log(f"Phase 2 progress: {end_idx}/{total_visible} visible rows ({progress_pct}%)",
                    level="debug", category="performance")

                current_batch += 1

                if end_idx < total_visible:
                    # Schedule next batch (yield to event loop)
                    QTimer.singleShot(20, _create_widgets_batch)
                else:
                    # Phase 2 complete - RE-ENABLE UPDATES
                    self.gallery_table.setUpdatesEnabled(True)
                    log(f"Phase 2 complete - created widgets for {len(self._rows_with_widgets)} rows",
                        level="info", category="performance")

                    # Finalize
                    QTimer.singleShot(10, self._finalize_gallery_load)

            except Exception as e:
                log(f"Error in Phase 2 widget creation batch: {e}", level="error", category="performance")
                # CRITICAL: Re-enable updates even on exception (prevents permanent UI freeze)
                self.gallery_table.setUpdatesEnabled(True)
                raise

        # Start creating widgets for visible rows
        _create_widgets_batch()

    def _get_visible_row_range(self) -> tuple[int, int]:
        """MILESTONE 4: Calculate the range of visible rows in the table viewport

        Returns:
            Tuple of (first_visible_row, last_visible_row) with ±5 row buffer
        """
        try:
            # Get the actual table widget (handle tabbed interface)
            table = self.gallery_table
            if hasattr(self.gallery_table, 'table'):
                table = self.gallery_table.table

            # Get viewport and scroll position
            viewport = table.viewport()
            viewport_height = viewport.height()
            vertical_scrollbar = table.verticalScrollBar()
            scroll_value = vertical_scrollbar.value()

            # Calculate row height (use first row or default)
            row_height = table.rowHeight(0) if table.rowCount() > 0 else 30

            # Calculate visible range with buffer
            buffer = 5
            first_visible = max(0, (scroll_value // row_height) - buffer)
            visible_rows = (viewport_height // row_height) + 1
            last_visible = min(table.rowCount() - 1, first_visible + visible_rows + buffer)

            log(f"Viewport: rows {first_visible}-{last_visible} (total: {table.rowCount()})",
                level="debug", category="performance")

            return (first_visible, last_visible)
        except Exception as e:
            log(f"Error calculating visible row range: {e}", level="error", category="performance")
            # Return full range as fallback
            return (0, table.rowCount() - 1 if hasattr(self, 'gallery_table') else 0)

    def _on_table_scrolled(self):
        """MILESTONE 4: Handle table scroll events - create widgets for newly visible rows"""
        if self._loading_phase < 2:
            # Phase 2 not started yet
            return

        try:
            first_visible, last_visible = self._get_visible_row_range()

            # Create widgets for visible rows that don't have them yet
            widgets_created = 0
            for row in range(first_visible, last_visible + 1):
                if row not in self._rows_with_widgets:
                    self._create_row_widgets(row)
                    self._rows_with_widgets.add(row)
                    widgets_created += 1

            if widgets_created > 0:
                log(f"Created widgets for {widgets_created} newly visible rows",
                    level="debug", category="performance")

        except Exception as e:
            log(f"Error in scroll handler: {e}", level="error", category="performance")

    def _create_row_widgets(self, row: int):
        """MILESTONE 4: Create progress and action widgets for a single row

        Args:
            row: The row number to create widgets for
        """
        try:
            path = self.row_to_path.get(row)
            if not path:
                return

            item = self.queue_manager.get_item(path)
            if not item:
                return

            # Get the actual table widget (handle tabbed interface)
            table = self.gallery_table
            if hasattr(self.gallery_table, 'table'):
                table = self.gallery_table.table

            # Create progress widget if needed
            progress_widget = table.cellWidget(row, GalleryTableWidget.COL_PROGRESS)
            if not isinstance(progress_widget, TableProgressWidget):
                progress_widget = TableProgressWidget()
                table.setCellWidget(row, GalleryTableWidget.COL_PROGRESS, progress_widget)
                progress_widget.update_progress(item.progress, item.status)

            # Create action buttons if needed
            action_widget = table.cellWidget(row, GalleryTableWidget.COL_ACTION)
            if not isinstance(action_widget, ActionButtonWidget):
                action_widget = ActionButtonWidget()
                table.setCellWidget(row, GalleryTableWidget.COL_ACTION, action_widget)
                action_widget.update_buttons(item.status)

        except Exception as e:
            log(f"Error creating widgets for row {row}: {e}", level="error", category="performance")

    def _finalize_gallery_load(self):
        """EMERGENCY FIX: Finalize gallery loading - apply filters and update UI"""
        if self._loading_abort:
            return

        log("Finalizing gallery load...", level="info", category="performance")

        # Apply filter and emit signals
        if hasattr(self.gallery_table, 'refresh_filter'):
            self.gallery_table.refresh_filter()
            if hasattr(self.gallery_table, 'tab_changed') and hasattr(self.gallery_table, 'current_tab'):
                self.gallery_table.tab_changed.emit(self.gallery_table.current_tab)

        # MILESTONE 4: Ensure visible rows have widgets after filtering
        QTimer.singleShot(100, self._on_table_scrolled)

        self._loading_phase = 3
        log(f"Gallery loading COMPLETE - {len(self._rows_with_widgets)} rows with widgets created",
            level="info", category="performance")

    def _populate_table_row_minimal(self, row: int, item: GalleryQueueItem):
        """EMERGENCY FIX: Populate row with MINIMAL data only (no expensive widgets)

        This is used during Phase 1 loading to show gallery names and basic info
        without creating expensive progress bars or action buttons.
        """
        try:
            # Name column (always visible)
            name_item = QTableWidgetItem(item.name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.gallery_table.setItem(row, GalleryTableWidget.COL_NAME, name_item)

            # Status text (lightweight)
            status_text_item = QTableWidgetItem(item.status)
            status_text_item.setFlags(status_text_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.gallery_table.setItem(row, GalleryTableWidget.COL_STATUS_TEXT, status_text_item)

            # Upload count - CRITICAL FIX: Always create item (even if empty) so it can be updated later
            # Before: Only created if total_images > 0, which broke updates when scan completes
            # After: Always create item, with empty text if total_images == 0
            if item.total_images > 0:
                uploaded_text = f"{item.uploaded_images}/{item.total_images}"
            else:
                uploaded_text = ""  # Empty but item exists for later updates
            uploaded_item = QTableWidgetItem(uploaded_text)
            uploaded_item.setFlags(uploaded_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.gallery_table.setItem(row, GalleryTableWidget.COL_UPLOADED, uploaded_item)

            # Size
            if item.total_size > 0:
                size_text = self._format_size_consistent(item.total_size)
                size_item = QTableWidgetItem(size_text)
                size_item.setFlags(size_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.gallery_table.setItem(row, GalleryTableWidget.COL_SIZE, size_item)

            # SKIP expensive widgets (progress bars, action buttons, file host widgets)
            # These will be created in Phase 2

        except Exception as e:
            log(f"Error in _populate_table_row_minimal for row {row}: {e}",
                level="warning", category="performance")

    def _refresh_log_display_settings(self):
        """Cache log display settings to avoid repeated lookups on every log message.
        
        This method is called during initialization and whenever log settings change.
        Caching these boolean values prevents creating a new dictionary copy on every
        log message, which is a hot path that can be called hundreds of times per second.
        """
        try:
            from src.utils.logging import get_logger
            settings = get_logger().get_settings()
            # get_settings() already normalizes these to Python bool
            self._log_show_level = settings.get("show_log_level_gui", False)
            self._log_show_category = settings.get("show_category_gui", False)
        except Exception:
            # Fallback to defaults if settings unavailable
            self._log_show_level = False
            self._log_show_category = False
    
    def refresh_log_display(self):
        """Re-render all log messages with current display settings.
        
        This method is called when log display settings change to update
        existing messages in the GUI log list with the new formatting.
        """
        try:
            # Don't refresh if log_text doesn't exist yet (during init)
            if not hasattr(self, 'log_text'):
                return
            
            # Refresh cache first
            self._refresh_log_display_settings()
            
            # Get all current messages (newest to oldest)
            # Note: Messages in log_text are already formatted, so we can't
            # re-parse them accurately. This limitation means existing messages
            # won't update when settings change. New messages will use new settings.
            # Future enhancement: Store raw messages separately for re-rendering.
            
        except Exception:
            pass  # Silently fail to avoid disrupting user experience
    def refresh_filter(self):
        """Refresh current tab filter on the embedded tabbed gallery widget."""
        try:
            if hasattr(self, 'gallery_table') and hasattr(self.gallery_table, 'refresh_filter'):
                self.gallery_table.refresh_filter()

            # MILESTONE 4: Ensure visible rows have widgets after filter/sort
            if self._loading_phase >= 2:
                QTimer.singleShot(100, self._on_table_scrolled)
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise
    
    def on_galleries_moved_to_tab(self, new_tab_name, gallery_paths):
        """Handle galleries being moved to a different tab - DATABASE ALREADY UPDATED BY DRAG-DROP HANDLER"""
        #print(f"DEBUG: on_galleries_moved_to_tab called with {len(gallery_paths)} paths to '{new_tab_name}' - database already updated", flush=True)
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
                        #print(f"DEBUG: Drag-drop updated MAIN WINDOW item {path} tab: '{old_tab}' -> '{new_tab_name}'", flush=True)
            
            # Invalidate cache and refresh MAIN WINDOW display
            if hasattr(self, 'tab_manager'):
                self.tab_manager.invalidate_tab_cache()
                if hasattr(self, 'gallery_table') and hasattr(self.gallery_table, '_update_tab_tooltips'):
                    self.gallery_table._update_tab_tooltips()
                
        except Exception as e:
            log(f"Error handling gallery move to tab '{new_tab_name}': {e}", level="error")
    
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
    

        
    def resizeEvent(self, event):
        """Update right panel maximum width when window is resized"""
        super().resizeEvent(event)
        try:
            # Update right panel max width to 75% of current window width
            if hasattr(self, 'right_panel'):
                window_width = self.width()
                if window_width > 0:
                    max_width = int(window_width * 0.75)
                    self.right_panel.setMaximumWidth(max_width)
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise
    
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
        # Theme cache
        self._current_theme_mode = str(self.settings.value('ui/theme', 'dark'))
    
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

    def _update_bandwidth_status(self):
        """Update bandwidth status bar with aggregate speed."""
        if not hasattr(self, 'worker_status_widget'):
            return

        total_speed_bps = self.worker_status_widget.get_total_speed()
        total_speed_mbps = total_speed_bps / (1024 * 1024)

        active_count = self.worker_status_widget.get_active_count()

        # Build tooltip with per-host breakdown
        tooltip_lines = ["Total Upload Bandwidth", ""]

        # Get worker statuses for breakdown
        for worker_id, status in self.worker_status_widget._workers.items():
            if status.speed_bps > 0:
                speed_mbps = status.speed_bps / (1024 * 1024)
                tooltip_lines.append(f"{status.display_name}: {speed_mbps:.2f} MiB/s")

        if not any(line for line in tooltip_lines[2:]):
            tooltip_lines.append("No active uploads")

        tooltip = "\n".join(tooltip_lines)

        if active_count > 0:
            self.bandwidth_status_label.setText(
                f"Uploading: {total_speed_mbps:.2f} MiB/s ({active_count} active)"
            )
            self.bandwidth_status_label.setStyleSheet("color: green; font-weight: bold;")
        else:
            self.bandwidth_status_label.setText("Bandwidth: 0.00 MiB/s")
            self.bandwidth_status_label.setStyleSheet("")

        self.bandwidth_status_label.setToolTip(tooltip)

    def _set_status_cell_icon(self, row: int, status: str):
        """Render the Status column as an icon only, without background/text.
        Explicitly handles all possible statuses with clear icon assignments.
        """
        # Validate row bounds to prevent setting icons on wrong rows
        if row < 0 or row >= self.gallery_table.rowCount():
            log(f"_set_status_cell_icon: Invalid row {row}, table has {self.gallery_table.rowCount()} rows", level="debug")
            return

        try:
            # Check if this row is selected - use inner table for tabbed system consistency
            table_widget = getattr(self.gallery_table, 'table', self.gallery_table)
            selected_rows = {item.row() for item in table_widget.selectedItems()}
            is_selected = row in selected_rows

            icon_mgr = get_icon_manager()
            if not icon_mgr:
                log(f"ERROR: IconManager not initialized, cannot set icon for status: {status}", level="error")
                return

            # Use IconManager with explicit theme and selection awareness
            # Pass animation frame for uploading status
            animation_frame = self._upload_animation_frame if status == "uploading" else 0
            icon = icon_mgr.get_status_icon(status, theme_mode=self._current_theme_mode, is_selected=is_selected, animation_frame=animation_frame)
            tooltip = icon_mgr.get_status_tooltip(status)

            # Apply the icon to the table cell
            self._apply_icon_to_cell(row, GalleryTableWidget.COL_STATUS, icon, tooltip, status)

        except Exception as e:
            print(f"Warning: Failed to set status icon for {status}: {e}")

    def _set_status_text_cell(self, row: int, status: str):
        """Set the status text column with capitalized status string.

        Args:
            row: The table row index
            status: The status string to display (will be capitalized)
        """
        # Validate row bounds
        if row < 0 or row >= self.gallery_table.rowCount():
            log(f"_set_status_text_cell: Invalid row {row}, table has {self.gallery_table.rowCount()} rows", level="debug")
            return

        try:
            # Create capitalized status text
            status_text = status.capitalize() if status else ""

            # Create table item with centered alignment
            status_item = QTableWidgetItem(status_text)
            status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            # Set the item in the STATUS_TEXT column
            self.gallery_table.setItem(row, GalleryTableWidget.COL_STATUS_TEXT, status_item)

        except Exception as e:
            log(f"Warning: Failed to set status text for {status}: {e}", level="debug")

    def _on_selection_changed(self, selected, deselected):
        """Handle gallery table selection changes to refresh icons"""
        try:
            # For tabbed gallery system, use the inner table
            inner_table = getattr(self.gallery_table, 'table', None)
            if not inner_table or not hasattr(inner_table, 'rowCount'):
                return
                
            # Refresh icons for all visible rows (selection state might have changed)
            for row in range(inner_table.rowCount()):
                # Get status from the queue item
                name_item = inner_table.item(row, GalleryTableWidget.COL_NAME)
                if name_item:
                    path = name_item.data(Qt.ItemDataRole.UserRole)
                    if path and path in self.queue_manager.items:
                        item = self.queue_manager.items[path]
                        self._set_status_cell_icon(row, item.status)
                        self._set_status_text_cell(row, item.status)

        except Exception as e:
            print(f"Warning: Error in selection change handler: {e}")

    def _confirm_removal(self, paths: list, names: list | None = None, operation_type: str = "delete") -> bool:
        """
        Shared confirmation dialog for removal operations.

        Args:
            paths: List of gallery paths to remove
            names: Optional list of gallery names (for better messaging)
            operation_type: Type of operation ("delete", "clear", etc.)

        Returns:
            True if user confirmed, False otherwise
        """
        count = len(paths)
        if count == 0:
            return False

        # Check if confirmation is needed
        defaults = load_user_defaults()
        confirm_delete = defaults.get('confirm_delete', True)

        # Always confirm if removing more than 50 galleries
        needs_confirmation = confirm_delete or count > 50

        if not needs_confirmation:
            return True

        # Build confirmation message
        if operation_type == "clear":
            # For clear completed, distinguish between completed and failed
            if count == 1:
                message = "Remove 1 completed/failed gallery from the queue?"
            else:
                message = f"Remove {count} completed/failed galleries from the queue?"
        else:
            # For delete operations
            if count == 1 and names:
                message = f"Delete '{names[0]}'?"
            else:
                message = f"Delete {count} selected {'gallery' if count == 1 else 'galleries'}?"

        # Add warning for large deletions
        if count > 50:
            message += f"\n\n⚠️ This will remove {count} galleries."

        reply = QMessageBox.question(
            self,
            "Confirm Removal" if operation_type == "clear" else "Confirm Delete",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No  # Default to No for safety
        )

        return reply == QMessageBox.StandardButton.Yes

    def _remove_galleries_batch(self, paths_to_remove: list, callback=None):
        """
        Non-blocking batch removal of galleries from table.

        Args:
            paths_to_remove: List of gallery paths to remove
            callback: Optional function to call when complete
        """
        if not paths_to_remove:
            if callback:
                callback()
            return

        # Process table removals in batches to avoid UI freeze
        batch_size = 10
        total_count = len(paths_to_remove)

        def process_batch(index):
            try:
                # Process one batch
                batch_end = min(index + batch_size, total_count)
                batch = paths_to_remove[index:batch_end]

                for path in batch:
                    self._remove_gallery_from_table(path)

                # Check if more batches remain
                if batch_end < total_count:
                    # Schedule next batch (yields to event loop)
                    QTimer.singleShot(0, lambda: process_batch(batch_end))
                else:
                    # All done - call completion callback
                    if callback:
                        callback()
            except Exception as e:
                log(f"Error in batch removal: {e}", level="error", category="ui")
                if callback:
                    callback()

        # Start batch processing
        QTimer.singleShot(0, lambda: process_batch(0))

    def _advance_upload_animation(self):
        """Advance the upload animation frame and update uploading icons"""
        # Increment frame (0-6, cycling through 7 frames)
        self._upload_animation_frame = (self._upload_animation_frame + 1) % 7

        # Get the actual table (handle tabbed interface)
        table = self.gallery_table
        if hasattr(self.gallery_table, 'table'):
            table = self.gallery_table.table

        # Update only rows with "uploading" status (efficient since there's typically only 1)
        try:
            for row in range(table.rowCount()):
                # Check if row is hidden (filtered out by tab)
                if table.isRowHidden(row):
                    continue

                name_item = table.item(row, GalleryTableWidget.COL_NAME)
                if name_item:
                    path = name_item.data(Qt.ItemDataRole.UserRole)
                    if path and path in self.queue_manager.items:
                        item = self.queue_manager.items[path]
                        if item.status == "uploading":
                            # Update only uploading icons with new frame
                            self._set_status_cell_icon(row, item.status)
        except Exception as e:
            # Silently ignore errors (table might be updating)
            pass

    def refresh_icons(self):
        """Alias for refresh_all_status_icons - called from settings dialog"""
        self.refresh_all_status_icons()
    
    def refresh_all_status_icons(self):
        """Refresh all status icons and action button icons after icon changes in settings"""
        try:
            icon_mgr = get_icon_manager()
            if icon_mgr:
                # Clear icon cache to force reload of changed icons
                icon_mgr.refresh_cache()

                # Get the actual table (handle tabbed interface)
                table = self.gallery_table
                if hasattr(self.gallery_table, 'table'):
                    table = self.gallery_table.table

                # Only update VISIBLE rows for fast theme switching
                # Get visible row range
                viewport = table.viewport()
                first_visible = table.rowAt(0)
                last_visible = table.rowAt(viewport.height())

                # Handle edge cases
                if first_visible == -1:
                    first_visible = 0
                if last_visible == -1:
                    last_visible = table.rowCount() - 1

                # Add buffer rows above and below visible area for smooth scrolling
                first_visible = max(0, first_visible - 5)
                last_visible = min(table.rowCount() - 1, last_visible + 5)

                # Update only visible status icons and action button icons
                for row in range(first_visible, last_visible + 1):
                    # Get the gallery path from the name column (UserRole data)
                    name_item = table.item(row, GalleryTableWidget.COL_NAME)
                    if name_item:
                        path = name_item.data(Qt.ItemDataRole.UserRole)
                        if path and path in self.queue_manager.items:
                            item = self.queue_manager.items[path]
                            # Refresh the status icon for this row
                            self._set_status_cell_icon(row, item.status)
                            self._set_status_text_cell(row, item.status)

                    # Refresh action button icons
                    action_widget = table.cellWidget(row, GalleryTableWidget.COL_ACTION)
                    if action_widget and hasattr(action_widget, 'refresh_icons'):
                        action_widget.refresh_icons()

                # Set flag so scrolling will refresh newly visible rows
                if hasattr(table, '_needs_full_icon_refresh'):
                    table._needs_full_icon_refresh = True

                # Refresh quick settings button icons
                if hasattr(self, 'comprehensive_settings_btn'):
                    settings_icon = icon_mgr.get_icon('settings')
                    if not settings_icon.isNull():
                        self.comprehensive_settings_btn.setIcon(settings_icon)

                if hasattr(self, 'manage_templates_btn'):
                    templates_icon = icon_mgr.get_icon('templates')
                    if not templates_icon.isNull():
                        self.manage_templates_btn.setIcon(templates_icon)

                if hasattr(self, 'manage_credentials_btn'):
                    credentials_icon = icon_mgr.get_icon('credentials')
                    if not credentials_icon.isNull():
                        self.manage_credentials_btn.setIcon(credentials_icon)

                if hasattr(self, 'log_viewer_btn'):
                    log_viewer_icon = icon_mgr.get_icon('log_viewer')
                    if not log_viewer_icon.isNull():
                        self.log_viewer_btn.setIcon(log_viewer_icon)

                if hasattr(self, 'hooks_btn'):
                    hooks_icon = icon_mgr.get_icon('hooks')
                    if not hooks_icon.isNull():
                        self.hooks_btn.setIcon(hooks_icon)

                if hasattr(self, 'theme_toggle_btn'):
                    theme_icon = icon_mgr.get_icon('toggle_theme')
                    #if not theme_icon.isNull():
                    #    self.theme_toggle_btn.setIcon(theme_icon)

                # Refresh worker status widget icons
                if hasattr(self, 'worker_status_widget') and hasattr(self.worker_status_widget, 'refresh_icons'):
                    self.worker_status_widget.refresh_icons()

        except Exception as e:
            print(f"Error refreshing icons: {e}")
    
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
            
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise

    def _show_failed_gallery_details(self, row: int):
        """Show detailed error information for a failed gallery."""
        try:
            path = self.gallery_table.item(row, GalleryTableWidget.COL_NAME).data(Qt.ItemDataRole.UserRole)
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
        # NOTE: Traceback extraction disabled for performance (was taking 700ms for 48 rows during theme changes)
        # import traceback
        # stack = traceback.extract_stack()
        # caller_chain = " -> ".join([frame.name for frame in stack[-4:-1]])
        # print(f"DEBUG: _set_renamed_cell_icon: {caller_chain}: row={row}, is_renamed={is_renamed}")
        try:
            col = 11
            
            # Create a simple table item with icon using central configuration
            item = QTableWidgetItem()
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            
            # Determine icon and tooltip based on rename status
            if is_renamed is True:
                icon = get_icon('renamed_true')
                tooltip = "Renamed"
                if icon is not None and not icon.isNull():
                    item.setIcon(icon)
                    item.setText("")
                else:
                    item.setText("✓")
                    log(f"Using fallback text for renamed_true", level="debug")
            elif is_renamed is False:
                icon = get_icon('renamed_false')
                tooltip = "Pending rename"
                #print(f"DEBUG: renamed_false icon - isNull: {icon.isNull() if icon else 'None'}")
                if icon is not None and not icon.isNull():
                    item.setIcon(icon)
                    item.setText("")
                else:
                    item.setText("⏳")
                    log(f"Using fallback text for renamed_false", level="debug")
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
            except Exception as e:
                log(f"Exception in main_window: {e}", level="error", category="ui")
                raise

    def showEvent(self, event):
        try:
            super().showEvent(event)
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise
        # Post-show pass no longer needed - targeted updates handle icon refreshes
        try:
            pass  # Removed deprecated update_queue_display call that overwrites correct rename status
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise

        # Start worker status monitoring (deferred to avoid blocking GUI startup)
        if hasattr(self, 'worker_status_widget'):
            QTimer.singleShot(100, self.worker_status_widget.start_monitoring)

        # Start queue polling for worker status widget (updates Files Left and Remaining columns)
        if hasattr(self, 'worker_status_widget') and hasattr(self, 'queue_manager'):
            self._queue_stats_timer = QTimer()
            self._queue_stats_timer.timeout.connect(self._update_worker_queue_stats)
            self._queue_stats_timer.start(2000)  # Poll every 2 seconds

        # Refresh button icons with correct theme now that palette is ready
        # Deferred to avoid blocking GUI startup with large gallery counts
        QTimer.singleShot(0, self._refresh_button_icons)
    
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
            self.setWindowTitle(f"IMXup {__version__}")
        except Exception:
            self.setWindowTitle("IMXup")
        self.setMinimumSize(800, 650)  # Allow log to shrink to accommodate Settings
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Add scanning status indicator to status bar
        self.scan_status_label = QLabel("Scanning: 0")
        self.scan_status_label.setVisible(False)
        self.statusBar().addPermanentWidget(self.scan_status_label)

        # Add real-time bandwidth display to status bar
        self.bandwidth_status_label = QLabel("Bandwidth: 0.00 MiB/s")
        self.bandwidth_status_label.setToolTip("Total upload bandwidth across all workers")
        self.statusBar().addPermanentWidget(self.bandwidth_status_label)

        self._log_viewer_dialog = None # Log viewer dialog reference
        self._current_transfer_kbps = 0.0 # Current transfer speed tracking
        self._bandwidth_samples = []  # Rolling window of recent samples (max 20 = 4 seconds at 200ms)
        
        # Main layout - vertical to stack queue and progress
        main_layout = QVBoxLayout(central_widget)
        # Tight outer margins/spacing to keep boxes close to each other
        try:
            main_layout.setContentsMargins(6, 6, 6, 6)
            main_layout.setSpacing(6)
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise
        
        # Top section with queue and settings - using splitter for resizable divider
        self.top_splitter = QSplitter(Qt.Orientation.Horizontal)
        try:
            self.top_splitter.setContentsMargins(0, 0, 0, 0)
            self.top_splitter.setHandleWidth(6)
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise
        
        # Left panel - Queue and controls (wider now)
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        try:
            left_layout.setContentsMargins(0, 0, 0, 0)
            left_layout.setSpacing(6)
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise
        
        # Queue section
        queue_group = QGroupBox("Upload Queue")
        queue_layout = QVBoxLayout(queue_group)
        try:
            queue_layout.setContentsMargins(10, 10, 10, 10)
            queue_layout.setSpacing(8)
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise
        
        # Drag-and-drop is handled at the window level; no dedicated drop label
        # (Moved Browse button into controls row below)
        
        # Tabbed gallery widget (replaces single table)
        self.gallery_table = TabbedGalleryWidget()
        self.gallery_table.setProperty("class", "gallery-table")
        queue_layout.addWidget(self.gallery_table, 1)  # Give it stretch priority

        # MILESTONE 4: Connect scroll handler for viewport-based lazy loading
        self.gallery_table.table.verticalScrollBar().valueChanged.connect(self._on_table_scrolled)

        # Header context menu for column visibility + persist widths/visibility
        # Access the internal table for header operations
        try:
            header = self.gallery_table.table.horizontalHeader()
            header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            header.customContextMenuRequested.connect(self.show_header_context_menu)
            header.sectionResized.connect(self._on_header_section_resized)
            header.sectionMoved.connect(self._on_header_section_moved)

        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise
        
        # Add keyboard shortcut hint
        shortcut_hint = QLabel("💡 Tips: <b>Ctrl-C</b>: Copy BBCode | <b>F2</b>: Rename | <b>Ctrl</b>+<b>Tab</b>: Next Tab | <b>Drag-and-drop</b>: Add folders")
        shortcut_hint.setProperty("class", "status-muted")
        shortcut_hint.setStyleSheet("font-size: 11px; color: #999999; font-style: italic;")
        #shortcut_hint.style().polish(shortcut_hint)
        shortcut_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        queue_layout.addWidget(shortcut_hint)
        
        # Queue controls
        controls_layout = QHBoxLayout()
        
        self.start_all_btn = QPushButton("Start All")
        if not self.start_all_btn.text().startswith(" "):
            self.start_all_btn.setText(" " + self.start_all_btn.text())
        self.start_all_btn.clicked.connect(self.start_all_uploads)
        self.start_all_btn.setProperty("class", "main-action-btn")
        controls_layout.addWidget(self.start_all_btn)
        
        self.pause_all_btn = QPushButton("Pause All")
        if not self.pause_all_btn.text().startswith(" "):
            self.pause_all_btn.setText(" " + self.pause_all_btn.text())
        self.pause_all_btn.clicked.connect(self.pause_all_uploads)
        self.pause_all_btn.setProperty("class", "main-action-btn")
        controls_layout.addWidget(self.pause_all_btn)
        
        self.clear_completed_btn = QPushButton("Clear Completed")
        if not self.clear_completed_btn.text().startswith(" "):
            self.clear_completed_btn.setText(" " + self.clear_completed_btn.text())
        self.clear_completed_btn.clicked.connect(self.clear_completed)
        self.clear_completed_btn.setProperty("class", "main-action-btn")
        controls_layout.addWidget(self.clear_completed_btn)

        # Browse button (moved here to be to the right of Clear Completed)
        self.browse_btn = QPushButton(" Browse ")
        self.browse_btn.clicked.connect(self.browse_for_folders)
        self.browse_btn.setProperty("class", "main-action-btn")
        controls_layout.addWidget(self.browse_btn)
        

        
        queue_layout.addLayout(controls_layout)
        left_layout.addWidget(queue_group)
        
        # Set minimum width for left panel (Upload Queue)
        # Reduced to allow splitter to move further left (up to ~3/4 of window width)
        left_panel.setMinimumWidth(250)
        self.top_splitter.addWidget(left_panel)
        
        # Right panel - Settings and logs (with vertical splitter between them)
        self.right_panel = QWidget()
        right_panel_outer_layout = QVBoxLayout(self.right_panel)
        right_panel_outer_layout.setContentsMargins(0, 0, 0, 0)
        right_panel_outer_layout.setSpacing(0)

        # Create vertical splitter for Settings and Log
        self.right_vertical_splitter = QSplitter(Qt.Orientation.Vertical)
        right_panel_outer_layout.addWidget(self.right_vertical_splitter)

        # Set maximum width to 75% of window to keep queue panel visible
        try:
            # Calculate 75% of current window width as max width
            window_width = self.width() if self.width() > 0 else 1000  # fallback for initial sizing
            max_width = int(window_width * 0.75)
            self.right_panel.setMaximumWidth(max_width)
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise
        
        
        # Settings section - using AdaptiveGroupBox to propagate child minimum size hints
        self.settings_group = AdaptiveGroupBox("Quick Settings")
        self.settings_group.setProperty("class", "settings-group")

        # Set size policy with minimum size to prevent splitter from shrinking too small
        size_policy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        size_policy.setVerticalStretch(0)
        self.settings_group.setSizePolicy(size_policy)
        # Removed setMinimumSize - QSplitter respects minimumSizeHint() of child widget instead

        settings_layout = QGridLayout(self.settings_group)
        try:
            settings_layout.setContentsMargins(5, 8, 5, 5)  # Reduced left/right/bottom by 3px
            settings_layout.setHorizontalSpacing(12)
            settings_layout.setVerticalSpacing(8)
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise
        
        settings_layout.setVerticalSpacing(5)
        settings_layout.setHorizontalSpacing(5)
        
        # Set fixed row heights to prevent shifting when save button appears
        settings_layout.setRowMinimumHeight(0, 28)  # Thumbnail Size row
        settings_layout.setRowMinimumHeight(1, 28)  # Thumbnail Format row  
        #settings_layout.setRowMinimumHeight(2, 28)  # Max Retries row
        #settings_layout.setRowMinimumHeight(3, 28)  # Concurrent Uploads row
        settings_layout.setRowMinimumHeight(2, 28)  # BBCode Template row
        settings_layout.setRowMinimumHeight(3, 28)  # Checkboxes row
        settings_layout.setRowMinimumHeight(4, 3)   # Small spacer before save button
        # Row 5 is the Save Settings button - let it appear/disappear freely
        # Row 6 is Comprehensive Settings
        # Row 7 is Templates/Credentials

        # Row 10 no longer gets stretch - all vertical space goes to row 6 (adaptive panel)
        # This makes the adaptive panel's height match the total available vertical space
        settings_layout.setRowStretch(10, 0)
        
        # Load defaults
        defaults = load_user_defaults()
        
        # Thumbnail size
        settings_layout.addWidget(QLabel("<span style=\"font-weight: 600\">Thumbnail Size</span>:"), 0, 0)
        self.thumbnail_size_combo = QComboBox()
        self.thumbnail_size_combo.addItems([
            "100x100", "180x180", "250x250", "300x300", "150x150"
        ])
        self.thumbnail_size_combo.setCurrentIndex(defaults.get('thumbnail_size', 3) - 1)
        self.thumbnail_size_combo.currentIndexChanged.connect(self.on_setting_changed)
        settings_layout.addWidget(self.thumbnail_size_combo, 0, 1)
        
        # Thumbnail format
        settings_layout.addWidget(QLabel("<span style=\"font-weight: 600\">Thumbnail Format</span>:"), 1, 0)
        self.thumbnail_format_combo = QComboBox()
        self.thumbnail_format_combo.addItems([
            "Fixed width", "Proportional", "Square", "Fixed height"
        ])
        self.thumbnail_format_combo.setCurrentIndex(defaults.get('thumbnail_format', 2) - 1)
        self.thumbnail_format_combo.currentIndexChanged.connect(self.on_setting_changed)
        settings_layout.addWidget(self.thumbnail_format_combo, 1, 1)
        
        # Max retries
        #settings_layout.addWidget(QLabel("<b>Max Retries</b>:"), 2, 0)
        #self.max_retries_spin = QSpinBox()
        #self.max_retries_spin.setRange(1, 10)
        #self.max_retries_spin.setValue(defaults.get('max_retries', 3))
        #self.max_retries_spin.valueChanged.connect(self.on_setting_changed)
        #settings_layout.addWidget(self.max_retries_spin, 2, 1)
        
        # Parallel upload batch size
        #settings_layout.addWidget(QLabel("<b>Concurrent Uploads</b>:"), 3, 0)
        #self.batch_size_spin = QSpinBox()
        #self.batch_size_spin.setRange(1, 50)
        #self.batch_size_spin.setValue(defaults.get('parallel_batch_size', 4))
        #self.batch_size_spin.setToolTip("Number of images to upload simultaneously. Higher values = faster uploads but more server load.")
        #self.batch_size_spin.valueChanged.connect(self.on_setting_changed)
        #settings_layout.addWidget(self.batch_size_spin, 3, 1)
        
        # Template selection
        settings_layout.addWidget(QLabel("<span style=\"font-weight: 600\">Template</span>:"), 2, 0)
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
        settings_layout.addWidget(self.template_combo, 2, 1)

        # Watch template directory for changes and refresh dropdown automatically
        try:
            from PyQt6.QtCore import QFileSystemWatcher
            from imxup import get_template_path
            self._template_watcher = QFileSystemWatcher([get_template_path()])
            self._template_watcher.directoryChanged.connect(self._on_templates_directory_changed)
        except Exception:
            self._template_watcher = None # If watcher isn't available, we simply won't auto-refresh
        
        # Public gallery setting moved to comprehensive settings only

        # Auto-start uploads checkbox
        self.auto_start_upload_check = QCheckBox("Start uploads automatically")
        self.auto_start_upload_check.setChecked(defaults.get('auto_start_upload', False))
        self.auto_start_upload_check.setToolTip("Automatically start uploads when scanning completes instead of waiting for manual start")
        self.auto_start_upload_check.toggled.connect(self.on_setting_changed)
        settings_layout.addWidget(self.auto_start_upload_check, 3, 0, 1, 2)  # Span 2 columns

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

        # Comprehensive Settings button (will be added to horizontal layout below)
        self.comprehensive_settings_btn = QPushButton(" Settings") # ⚙️
        if not self.comprehensive_settings_btn.text().startswith(" "):
            self.comprehensive_settings_btn.setText(" " + self.comprehensive_settings_btn.text())
        self.comprehensive_settings_btn.clicked.connect(self.open_comprehensive_settings)
        self.comprehensive_settings_btn.setMinimumHeight(30)
        self.comprehensive_settings_btn.setMaximumHeight(34)
        self.comprehensive_settings_btn.setProperty("class", "comprehensive-settings")
        # Note: Now added to horizontal layout with icon buttons (see below)

        # Manage templates and credentials buttons
        self.manage_templates_btn = QPushButton("") # previously  QPushButton(" Templates")
        self.manage_templates_btn.setToolTip("Manage BBCode templates for gallery output")
        self.manage_credentials_btn = QPushButton("") # previously  QPushButton(" Credentials")
        self.manage_credentials_btn.setToolTip("Configure imx.to API key and login credentials")

        # Add icons if available
    
        try:
            icon_mgr = get_icon_manager()
            if icon_mgr:
                templates_icon = icon_mgr.get_icon('templates')
                if not templates_icon.isNull():
                    self.manage_templates_btn.setIcon(templates_icon)
                    self.manage_templates_btn.setIconSize(QSize(22, 22))

                credentials_icon = icon_mgr.get_icon('credentials')
                if not credentials_icon.isNull():
                    self.manage_credentials_btn.setIcon(credentials_icon)
                    self.manage_credentials_btn.setIconSize(QSize(22, 22))

                settings_icon = icon_mgr.get_icon('settings')
                if not settings_icon.isNull():
                    self.comprehensive_settings_btn.setIcon(settings_icon)
                    self.comprehensive_settings_btn.setIconSize(QSize(22, 22))
                
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise
        self.manage_templates_btn.clicked.connect(self.manage_templates)
        self.manage_credentials_btn.clicked.connect(self.manage_credentials)

        for btn in [self.manage_templates_btn, self.manage_credentials_btn]:
            btn.setProperty("class", "quick-settings-btn")

        # Log viewer button (icon-only, small)
        self.log_viewer_btn = QPushButton()
        self.log_viewer_btn.setProperty("class", "log-viewer-btn")
        self.log_viewer_btn.setToolTip("Open Log Viewer")
        try:
            icon_mgr = get_icon_manager()
            if icon_mgr:
                log_viewer_icon = icon_mgr.get_icon('log_viewer')
                if not log_viewer_icon.isNull():
                    self.log_viewer_btn.setIcon(log_viewer_icon)
                    self.log_viewer_btn.setIconSize(QSize(20, 20))
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise
        self.log_viewer_btn.clicked.connect(self.open_log_viewer_popup)

        # Hooks button (opens comprehensive settings to Hooks tab)
        self.hooks_btn = QPushButton()
        self.hooks_btn.setProperty("class", "hooks-btn")
        self.hooks_btn.setToolTip("Configure external application hooks")
        try:
            icon_mgr = get_icon_manager()
            if icon_mgr:
                hooks_icon = icon_mgr.get_icon('hooks')
                if not hooks_icon.isNull():
                    self.hooks_btn.setIcon(hooks_icon)
                    self.hooks_btn.setIconSize(QSize(22, 22))
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise
        self.hooks_btn.clicked.connect(lambda: self.open_comprehensive_settings(tab_index=5))

        # File Hosts button (opens comprehensive settings to File Hosts tab)
        self.file_hosts_btn = QPushButton("")
        self.file_hosts_btn.setToolTip("Configure file host credentials and settings")
        try:
            icon_mgr = get_icon_manager()
            if icon_mgr:
                filehosts_icon = icon_mgr.get_icon('filehosts')
                if not filehosts_icon.isNull():
                    self.file_hosts_btn.setIcon(filehosts_icon)
                    self.file_hosts_btn.setIconSize(QSize(24, 24))
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise
        self.file_hosts_btn.clicked.connect(self.manage_file_hosts)
        self.file_hosts_btn.setProperty("class", "quick-settings-btn")

        # Theme toggle button (icon-only, small)
        self.theme_toggle_btn = QPushButton()
        self.theme_toggle_btn.setProperty("class", "theme-toggle-btn")
        # Set initial tooltip based on current theme
        current_theme = str(self.settings.value('ui/theme', 'dark'))
        initial_tooltip = "Switch to Light Mode" if current_theme == 'dark' else "Switch to Dark Mode"
        self.theme_toggle_btn.setToolTip(initial_tooltip)
        try:
            icon_mgr = get_icon_manager()
            if icon_mgr:
                theme_icon = icon_mgr.get_icon('toggle_theme')
                if not theme_icon.isNull():
                    self.theme_toggle_btn.setIcon(theme_icon)
                    self.theme_toggle_btn.setIconSize(QSize(22, 22))
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise
        self.theme_toggle_btn.clicked.connect(self.toggle_theme)

        # Help button (opens help documentation dialog)
        self.help_btn = QPushButton("")
        self.help_btn.setToolTip("Open help documentation")
        try:
            icon_mgr = get_icon_manager()
            if icon_mgr:
                help_icon = icon_mgr.get_icon('help')
                if not help_icon.isNull():
                    self.help_btn.setIcon(help_icon)
                    self.help_btn.setIconSize(QSize(20, 20))
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise
        self.help_btn.clicked.connect(self.open_help_dialog)
        self.help_btn.setProperty("class", "quick-settings-btn")

        # Create adaptive panel for quick settings buttons
        # Automatically adjusts layout based on available width AND height:
        # - Compact: 1 row, icon-only (when both dimensions constrained)
        # - Expanded: 2 rows with labels (when vertical or horizontal room available)
        self.adaptive_settings_panel = AdaptiveQuickSettingsPanel()
        self.adaptive_settings_panel.set_buttons(
            self.comprehensive_settings_btn,
            self.manage_credentials_btn,    # Credentials
            self.manage_templates_btn,      # Templates
            self.file_hosts_btn,            # File Hosts
            self.hooks_btn,                 # Hooks
            self.log_viewer_btn,            # Logs
            self.help_btn,                  # Help
            self.theme_toggle_btn           # Theme
        )

        # Apply icons-only mode if setting is enabled
        icons_only = self.settings.value('ui/quick_settings_icons_only', False, type=bool)
        self.adaptive_settings_panel.set_icons_only_mode(icons_only)

        settings_layout.addWidget(self.adaptive_settings_panel, 6, 0, 1, 2)  # Row 6, spanning 2 columns

        # AdaptiveGroupBox automatically propagates adaptive panel's minimum size to QSplitter
        # No need for hardcoded setMinimumHeight - the custom minimumSizeHint() handles it dynamically
        # This ensures buttons remain accessible when splitter is dragged to minimum position

        # Give row 6 a stretch factor so the adaptive panel can expand vertically
        # This allows it to detect when vertical space is available and switch layouts
        settings_layout.setRowStretch(6, 1)

        # Worker Status section (add between settings and log)
        # Note: worker_status_widget was created early in __init__ before FileHostWorkerManager
        worker_status_group = QGroupBox("Upload Workers")
        worker_status_layout = QVBoxLayout(worker_status_group)
        worker_status_layout.setContentsMargins(5, 5, 5, 5)

        # Add the already-created worker status widget to the layout
        worker_status_layout.addWidget(self.worker_status_widget)

        # Connect worker status widget signals
        self.worker_status_widget.open_settings_tab_requested.connect(self.open_comprehensive_settings)
        self.worker_status_widget.open_host_config_requested.connect(self._open_host_config_from_worker)

        # Worker monitoring started in showEvent() to avoid blocking startup
        # with database queries from _populate_initial_metrics()

        # Setup bandwidth status update timer
        self.bandwidth_status_timer = QTimer()
        self.bandwidth_status_timer.timeout.connect(self._update_bandwidth_status)
        self.bandwidth_status_timer.start(500)  # Update every 500ms

        # Set minimum height for worker status group
        worker_status_group.setMinimumHeight(150)
        worker_status_group.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Minimum
        )

        # Log section (add first)
        log_group = QGroupBox("Log")
        log_layout = QVBoxLayout(log_group)
        try:
            log_layout.setContentsMargins(5, 10, 5, 5)  # Reduced left/right/bottom by 3px
            log_layout.setSpacing(8)
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise
        
        # Use QListWidget instead of QTextEdit for simpler, more reliable log display
        from src.gui.widgets.custom_widgets import CopyableLogListWidget
        self.log_text = CopyableLogListWidget()
        self.log_text.setAlternatingRowColors(False)
        self.log_text.setSelectionMode(CopyableLogListWidget.SelectionMode.ExtendedSelection)

        # Set monospace font
        _log_font = QFont("Consolas", 9)
        _log_font.setStyleHint(QFont.StyleHint.Monospace)
        self.log_text.setFont(_log_font)

        # Scrolling behavior
        self.log_text.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.log_text.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        # Double-click to open popout viewer
        try:
            self.log_text.doubleClicked.connect(self.open_log_viewer_popup)
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise

        # QListWidget manages items differently than QTextEdit - no document() method needed
        # The item count is naturally limited by memory, not a block count setting
        log_layout.addWidget(self.log_text)

        # Add all three groups to the vertical splitter
        self.right_vertical_splitter.addWidget(self.settings_group)
        self.right_vertical_splitter.addWidget(worker_status_group)
        self.right_vertical_splitter.addWidget(log_group)

        # Configure vertical splitter - prevent all from collapsing
        self.right_vertical_splitter.setCollapsible(0, False)  # Settings group cannot collapse
        self.right_vertical_splitter.setCollapsible(1, False)  # Worker Status group cannot collapse
        self.right_vertical_splitter.setCollapsible(2, False)  # Log group cannot collapse

        # Use stretch factors to control resize behavior
        # Higher stretch factor = gets more space and resists shrinking more
        self.right_vertical_splitter.setStretchFactor(0, 0)  # Settings: no stretch, maintains size
        self.right_vertical_splitter.setStretchFactor(1, 0)  # Worker Status: no stretch, maintains size
        self.right_vertical_splitter.setStretchFactor(2, 1)  # Log: stretches to fill space

        # Set initial vertical splitter sizes [settings, worker_status, log]
        self.right_vertical_splitter.setSizes([400, 180, 270])

        # Set minimum width for right panel (Settings + Log) - reduced for better resizing
        self.right_panel.setMinimumWidth(270)
        self.top_splitter.addWidget(self.right_panel)

        # Configure main horizontal splitter
        self.top_splitter.setCollapsible(0, False)  # Left panel (queue) cannot collapse
        self.top_splitter.setCollapsible(1, True)   # Right panel (settings+log) CAN now collapse

        # Set initial horizontal splitter sizes (roughly 60/40 split)
        self.top_splitter.setSizes([600, 400])
        
        main_layout.addWidget(self.top_splitter)
        
        # Bottom section - Overall progress (left) and Help (right)
        bottom_layout = QHBoxLayout()
        try:
            bottom_layout.setContentsMargins(0, 0, 0, 0)
            bottom_layout.setSpacing(6)
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise

        # Current tab progress group (left)
        progress_group = QGroupBox("Current Tab Progress")
        progress_layout = QVBoxLayout(progress_group)
        try:
            progress_layout.setContentsMargins(10, 10, 10, 10)
            progress_layout.setSpacing(8)
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise

        overall_layout = QHBoxLayout()
        overall_layout.addWidget(QLabel("Progress:"))
        self.overall_progress = OverallProgressWidget()
        self.overall_progress.setProgressProperty("status", "ready")
        overall_layout.addWidget(self.overall_progress)
        progress_layout.addLayout(overall_layout)

        # Statistics
        self.stats_label = QLabel("Ready to upload galleries")
        self.stats_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stats_label.setStyleSheet("font-style: italic;")  # Let styles.qss handle the color
        progress_layout.addWidget(self.stats_label)

        # Keep bottom short like the original progress box
        progress_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        progress_group.setProperty("class", "progress-group")
        bottom_layout.addWidget(progress_group, 3)  # Match left/right ratio (3:1)

        # Help group (right) -> repurpose as Stats details
        stats_group = QGroupBox("Info")
        stats_layout = QGridLayout(stats_group)
        try:
            stats_layout.setContentsMargins(10, 8, 10, 8)
            stats_layout.setHorizontalSpacing(10)
            stats_layout.setVerticalSpacing(6)
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise
        
        # Detailed stats labels (split into label and value for right-aligned values)
        self.stats_unnamed_text_label = QLabel("Unnamed galleries:")
        self.stats_unnamed_value_label = QLabel("0")

        # Make unnamed galleries labels clickable
        self.stats_unnamed_text_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stats_unnamed_value_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stats_unnamed_text_label.setToolTip("Click to view unrenamed galleries")
        self.stats_unnamed_value_label.setToolTip("Click to view unrenamed galleries")
        self.stats_unnamed_text_label.mousePressEvent = lambda e: self.open_unrenamed_galleries_dialog()
        self.stats_unnamed_value_label.mousePressEvent = lambda e: self.open_unrenamed_galleries_dialog()

        self.stats_total_galleries_text_label = QLabel("Galleries uploaded:")
        self.stats_total_galleries_value_label = QLabel("0")
        self.stats_total_images_text_label = QLabel("Images uploaded:")
        self.stats_total_images_value_label = QLabel("0")
        for lbl in (
            self.stats_unnamed_value_label,
            self.stats_total_galleries_value_label,
            self.stats_total_images_value_label,
        ):
            try:
                lbl.setProperty("class", "console")
            except Exception as e:
                log(f"Exception in main_window: {e}", level="error", category="ui")
                raise
            try:
                lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            except Exception as e:
                log(f"Exception in main_window: {e}", level="error", category="ui")
                raise
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
            stats_group.setFixedWidth(230)
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise
        stats_group.setMinimumWidth(160)
        stats_group.setProperty("class", "stats-group")

        bottom_layout.addWidget(stats_group, 1)

        speed_group = QGroupBox("Speed")
        speed_layout = QGridLayout(speed_group)
        try:
            speed_layout.setContentsMargins(10, 10, 10, 10)
            speed_layout.setHorizontalSpacing(12)
            speed_layout.setVerticalSpacing(8)
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise
        
        # Detailed speed labels (split into label and value for right-aligned values)
        self.speed_current_text_label = QLabel("Current:")
        self.speed_current_value_label = QLabel("0.0 KiB/s")
        self.speed_fastest_text_label = QLabel("Fastest:")
        self.speed_fastest_value_label = QLabel("0.0 KiB/s")
        self.speed_transferred_text_label = QLabel("Transferred:")
        self.speed_transferred_value_label = QLabel("0 B")
        for lbl in (
            self.speed_current_value_label,
            self.speed_fastest_value_label,
            self.speed_transferred_value_label,
        ):
            try:
                lbl.setProperty("class", "console")
            except Exception as e:
                log(f"Exception in main_window: {e}", level="error", category="ui")
                raise
            try:
                lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            except Exception as e:
                log(f"Exception in main_window: {e}", level="error", category="ui")
                raise

        # Make current transfer speed value 1px larger than others
        try:
            self.speed_current_value_label.setProperty("class", "console-large")
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise

        speed_layout.addWidget(self.speed_current_text_label, 0, 0)
        speed_layout.addWidget(self.speed_current_value_label, 0, 1)
        speed_layout.addWidget(self.speed_fastest_text_label, 1, 0)
        speed_layout.addWidget(self.speed_fastest_value_label, 1, 1)
        speed_layout.addWidget(self.speed_transferred_text_label, 2, 0)
        speed_layout.addWidget(self.speed_transferred_value_label, 2, 1)
        
        # Keep bottom short like the original progress box; fix width to avoid jitter
        speed_group.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        try:
            speed_group.setFixedWidth(230)  # Increased from 200 to 240 to prevent digit truncation
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise
        speed_group.setProperty("class", "speed-group")
        bottom_layout.addWidget(speed_group, 1)

        main_layout.addLayout(bottom_layout)
        # Ensure the top section takes remaining space and bottom stays compact
        try:
            main_layout.setStretch(0, 1)  # top_layout
            main_layout.setStretch(1, 0)  # bottom_layout
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise

    def open_central_store_folder(self):
        """Open the central store folder in the OS file manager"""
        try:
            central_path = self._get_central_store_base_path()
            if os.path.isdir(central_path):
                QDesktopServices.openUrl(QUrl.fromLocalFile(central_path))
            else:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "Folder Not Found",
                                  f"Central store folder does not exist:\n{central_path}")
        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Error", f"Could not open central store folder:\n{str(e)}")

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
            action_open_store = file_menu.addAction("Open Central Store Folder")
            action_open_store.triggered.connect(self.open_central_store_folder)
            file_menu.addSeparator()
            action_exit = file_menu.addAction("Exit")
            action_exit.triggered.connect(self.close)

            # View menu
            view_menu = menu_bar.addMenu("View")
            action_log = view_menu.addAction("Open Log Viewer (Settings)")
            action_log.triggered.connect(self.open_log_viewer)

            # Standalone log viewer popup
            action_log_popup = view_menu.addAction("Open Log Viewer (Popup)")
            action_log_popup.triggered.connect(self.open_log_viewer_popup)

            # Icon Manager
            action_icon_manager = view_menu.addAction("Icon Manager")
            action_icon_manager.triggered.connect(self.open_icon_manager)

            view_menu.addSeparator()

            # Toggle right panel visibility
            self.action_toggle_right_panel = view_menu.addAction("Toggle Right Panel")
            self.action_toggle_right_panel.setShortcut("Ctrl+R")
            self.action_toggle_right_panel.setCheckable(True)
            self.action_toggle_right_panel.setChecked(True)  # Initially visible
            self.action_toggle_right_panel.triggered.connect(self.toggle_right_panel)

            view_menu.addSeparator()

            # Theme submenu: System / Light / Dark
            theme_menu = view_menu.addMenu("Theme")
            theme_group = QActionGroup(self)
            theme_group.setExclusive(True)
            self._theme_action_light = theme_menu.addAction("Light")
            self._theme_action_light.setCheckable(True)
            self._theme_action_dark = theme_menu.addAction("Dark")
            self._theme_action_dark.setCheckable(True)
            theme_group.addAction(self._theme_action_light)
            theme_group.addAction(self._theme_action_dark)
            self._theme_action_light.triggered.connect(lambda: self.set_theme_mode('light'))
            self._theme_action_dark.triggered.connect(lambda: self.set_theme_mode('dark'))
            # Initialize checked state from settings
            current_theme = str(self.settings.value('ui/theme', 'dark'))
            if current_theme == 'light':
                self._theme_action_light.setChecked(True)
            else:
                self._theme_action_dark.setChecked(True)

            # Settings menu
            settings_menu = menu_bar.addMenu("Settings")
            action_general = settings_menu.addAction("General")
            action_general.triggered.connect(lambda: self.open_comprehensive_settings(tab_index=0))
            action_credentials = settings_menu.addAction("Credentials")
            action_credentials.triggered.connect(lambda: self.open_comprehensive_settings(tab_index=1))
            action_templates = settings_menu.addAction("Templates")
            action_templates.triggered.connect(lambda: self.open_comprehensive_settings(tab_index=2))
            # Tabs and Icons menu items removed - functionality hidden
            action_logs = settings_menu.addAction("Log Settings")
            action_logs.triggered.connect(lambda: self.open_comprehensive_settings(tab_index=3))
            action_scanning = settings_menu.addAction("Image Scanning")
            action_scanning.triggered.connect(lambda: self.open_comprehensive_settings(tab_index=4))
            action_external_apps = settings_menu.addAction("Hooks (External Apps)")
            action_external_apps.triggered.connect(lambda: self.open_comprehensive_settings(tab_index=5))
            action_file_hosts = settings_menu.addAction("File Hosts")
            action_file_hosts.triggered.connect(lambda: self.open_comprehensive_settings(tab_index=6))

            # Tools menu
            tools_menu = menu_bar.addMenu("Tools")
            #action_templates = tools_menu.addAction("Manage Templates")
            #action_templates.triggered.connect(self.manage_templates)
            #action_credentials = tools_menu.addAction("Manage Credentials")
            #action_credentials.triggered.connect(self.manage_credentials)
            #tools_menu.addSeparator()
            action_unrenamed = tools_menu.addAction("Unnamed Galleries")
            action_unrenamed.triggered.connect(self.open_unrenamed_galleries_dialog)

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
            action_license = help_menu.addAction("License")
            action_license.triggered.connect(self.show_license_dialog)
            action_about = help_menu.addAction("About")
            action_about.triggered.connect(self.show_about_dialog)
        except Exception:
            # If menu bar creation fails, continue without it
            pass

    def show_about_dialog(self):
        """Show a custom About dialog with logo."""
        import os
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QTextBrowser, QPushButton
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QPixmap
        
        try:
            from imxup import __version__
            version = f"{__version__}"
        except Exception:
            version = "69"
            
        dialog = QDialog(self)
        dialog.setWindowTitle("About IMXup")
        dialog.setFixedSize(400, 500)
        dialog.setModal(True)
        
        layout = QVBoxLayout(dialog)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Add logo at top
        try:
            logo_path = os.path.join(get_project_root(), 'assets', 'imxup.png')
            logo_pixmap = QPixmap(logo_path)
            if not logo_pixmap.isNull():
                logo_label = QLabel()
                # Scale logo to reasonable size
                scaled_logo = logo_pixmap.scaledToHeight(80, Qt.TransformationMode.SmoothTransformation)
                logo_label.setPixmap(scaled_logo)
                logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                layout.addWidget(logo_label)
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise
        
        # Add title
        title_label = QLabel("IMXup")
        title_label.setProperty("class", "about-title")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)
        
        # Add subtitle
        subtitle_label = QLabel("IMX.to Gallery Uploader")
        subtitle_label.setProperty("class", "about-subtitle")
        subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle_label)
        
        # Add version
        version_label = QLabel(version)
        version_label.setProperty("class", "about-version")
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version_label)
        
        # Add info text
        info_text = QTextBrowser()
        info_text.setProperty("class", "about-info")
        info_html = """
        <div align="center">
        <p><strong>Copyright © 2025, twat</strong></p>
        <p><strong>License:</strong> Apache 2.0</p>
        <br>
        <p style="color: #666; font-size: 9px;">
        We are not affiliated with IMX.to in any way, but use of the software
        to interact with the IMX.to service is subject to their terms of use
        and privacy policy:<br>
        <a href="https://imx.to/page/terms">https://imx.to/page/terms</a><br>
        <a href="https://imx.to/page/terms">https://imx.to/page/privacy</a>
        </p>
        </div>
        """
        info_text.setHtml(info_html)
        layout.addWidget(info_text)
        
        # Add close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        close_btn.setStyleSheet("QPushButton { min-width: 80px; }")
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        
        dialog.exec()

    def show_license_dialog(self):
        """Show the LICENSE file in a dialog."""
        import os
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QPushButton
        from PyQt6.QtCore import Qt

        dialog = QDialog(self)
        dialog.setWindowTitle("License")
        dialog.resize(700, 600)
        dialog.setModal(True)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(10, 10, 10, 10)

        # Text display for license
        license_text = QTextEdit()
        license_text.setReadOnly(True)
        license_text.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)

        # Load LICENSE file
        try:
            from imxup import get_project_root
            license_path = os.path.join(get_project_root(), 'LICENSE')
            if os.path.exists(license_path):
                with open(license_path, 'r', encoding='utf-8') as f:
                    license_content = f.read()
                license_text.setPlainText(license_content)
            else:
                license_text.setPlainText("LICENSE file not found. See https://spdx.org/licenses/Apache-2.0.html")
        except Exception as e:
            license_text.setPlainText(f"Error loading LICENSE file: {e}")

        # Scroll to top
        cursor = license_text.textCursor()
        cursor.movePosition(cursor.MoveOperation.Start)
        license_text.setTextCursor(cursor)

        layout.addWidget(license_text)

        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        close_btn.setStyleSheet("QPushButton { min-width: 80px; }")
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        dialog.exec()

    def check_credentials(self):
        """Prompt to set credentials only if API key is not set."""
        if not api_key_is_set():
            log(f"No API key set. Showing credential dialog...", level="warning", category="auth")
            self.credential_dialog = CredentialSetupDialog(self, standalone=True)
            # Use non-blocking show() instead of blocking exec() to prevent GUI freezing
            self.credential_dialog.show()
            self.credential_dialog.finished.connect(lambda result: self._handle_credential_dialog_result(result))
            # Auto-cleanup when dialog is destroyed
            self.credential_dialog.finished.connect(lambda: setattr(self, 'credential_dialog', None))
        else:
            log(f"API key found", category="auth", level="info")
        
    
    def _handle_credential_dialog_result(self, result):
        """Handle credential dialog result without blocking GUI"""
        if result == QDialog.DialogCode.Accepted:
            log(f"Credentials saved securely", category="auth", level="info")
        else:
            log(f"Credential setup cancelled", category="ui", level="debug")
    
    def retry_login(self, credentials_only: bool = False):
        """Invalidate RenameWorker session to force re-login on next rename."""
        try:
            # Invalidate RenameWorker session so it re-logins on next rename
            if self.worker is not None and hasattr(self.worker, 'rename_worker'):
                if self.worker.rename_worker is not None:
                    try:
                        self.worker.rename_worker.invalidate_session()
                        log(f"Invalidated RenameWorker session - will re-login on next rename", category="auth", level="debug")
                    except Exception as e:
                        log(f"Failed to invalidate RenameWorker session: {e}", category="auth", level="debug")
                else:
                    log(f"No RenameWorker available", category="auth", level="debug")
            else:
                if self.worker is None or not self.worker.isRunning():
                    log(f"Worker not running", category="auth", level="debug")
                else:
                    log(f"Worker has no RenameWorker", category="auth", level="debug")
        except Exception as e:
            try:
                log(f"Failed to invalidate session: {e}", category="auth", level="debug")
            except Exception as e:
                log(f"Exception in main_window: {e}", level="error", category="ui")
                raise

    def install_context_menu(self):
        """Install Windows Explorer context menu integration."""
        try:
            ok = create_windows_context_menu()
            if ok:
                QMessageBox.information(self, "Context Menu", "Windows Explorer context menu installed successfully.")
                log(f"Installed Windows context menu", category="system", level="debug")
            else:
                QMessageBox.warning(self, "Context Menu", "Failed to install Windows Explorer context menu.")
                log(f"Failed to install Windows context menu", category="system", level="debug")
        except Exception as e:
            QMessageBox.warning(self, "Context Menu", f"Error installing context menu: {e}")
            log(f"Error installing context menu: {e}", category="system", level="debug")
            pass

    def remove_context_menu(self):
        """Remove Windows Explorer context menu integration."""
        try:
            ok = remove_windows_context_menu()
            if ok:
                QMessageBox.information(self, "Context Menu", "Windows Explorer context menu removed successfully.")
                log(f"Removed Windows context menu", category="system", level="debug")
            else:
                QMessageBox.warning(self, "Context Menu", "Failed to remove Windows Explorer context menu.")
                log(f"Failed to remove Windows context menu", category="system", level="warning")
        except Exception as e:
            QMessageBox.warning(self, "Context Menu", f"Error removing context menu: {e}")
            try:
                log(f"Error removing context menu: {e}", category="system", level="error")
            except Exception as e:
                log(f"Exception in main_window: {e}", level="error", category="ui")
                raise
    
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

    def manage_file_hosts(self):
        """Open comprehensive settings to file hosts tab"""
        self.open_comprehensive_settings(tab_index=6)  # File Hosts tab

    def open_comprehensive_settings(self, tab_index=0):
        """Open comprehensive settings dialog to specific tab"""
        # Pass file_host_manager to settings dialog
        file_host_manager = getattr(self, 'file_host_manager', None)
        dialog = ComprehensiveSettingsDialog(self, file_host_manager=file_host_manager)
        if 0 <= tab_index < dialog.tab_widget.count():
            dialog.tab_widget.setCurrentIndex(tab_index)

        # Use non-blocking show() to prevent GUI freezing
        dialog.show()
        dialog.finished.connect(lambda result: self._handle_settings_dialog_result(result))

    def _open_host_config_from_worker(self, host_id: str):
        """Open file host config dialog from worker status widget.

        Args:
            host_id: Host identifier (e.g., 'rapidgator', 'katfile')
        """
        from src.gui.dialogs.file_host_config_dialog import FileHostConfigDialog
        from src.core.file_host_config import get_config_manager

        config_manager = get_config_manager()
        if not config_manager or host_id not in config_manager.hosts:
            log(f"Cannot open config for unknown host: {host_id}", level="warning", category="ui")
            return

        host_config = config_manager.hosts[host_id]
        file_host_manager = getattr(self, 'file_host_manager', None)

        # Create dialog with minimal required parameters
        dialog = FileHostConfigDialog(
            parent=self,
            host_id=host_id,
            host_config=host_config,
            main_widgets={},
            worker_manager=file_host_manager
        )
        result = dialog.exec()

        # Refresh worker status table when dialog closes (accepted or rejected)
        # to update auto-upload icon if trigger settings changed
        if hasattr(self, 'worker_status_widget') and self.worker_status_widget:
            self.worker_status_widget.refresh_icons()

    def show_help_shortcuts_tab(self):
        """Open help dialog and switch to keyboard shortcuts tab"""
        from src.gui.dialogs.help_dialog import HelpDialog
        dialog = HelpDialog(self)

        # Find and switch to the Keyboard Shortcuts tab
        for i in range(dialog.tabs.count()):
            if dialog.tabs.tabText(i) == "Keyboard Shortcuts":
                dialog.tabs.setCurrentIndex(i)
                break

        dialog.show()
    
    def _handle_settings_dialog_result(self, result):
        """Handle settings dialog result without blocking GUI"""
        if result == QDialog.DialogCode.Accepted:
            log(f"Comprehensive settings updated successfully",level="debug")
            # Reload settings into quick settings UI
            from imxup import load_user_defaults
            defaults = load_user_defaults()
            self.auto_start_upload_check.setChecked(defaults.get('auto_start_upload', False))
        else:
            log(f"Comprehensive settings cancelled", level="debug", category="ui")

    def open_help_dialog(self):
        """Open the help/documentation dialog"""
        dialog = HelpDialog(self)
        # Use non-blocking show() for help dialog
        dialog.show()

    def toggle_theme(self):
        """Toggle between light and dark theme."""
        current_theme = self._current_theme_mode
        new_theme = 'dark' if current_theme == 'light' else 'light'
        self.set_theme_mode(new_theme)

    def toggle_right_panel(self):
        """Toggle visibility of the right panel (Settings + Log)."""
        try:
            # Get current sizes
            sizes = self.top_splitter.sizes()

            # Check if right panel is collapsed (size is 0 or very small)
            is_collapsed = sizes[1] < 50

            if is_collapsed:
                # Restore panel - use saved size or default to 30% of window width
                saved_size = self.settings.value("right_panel/width", 400, type=int)
                total_width = sum(sizes)

                # Ensure saved size is reasonable (between 250 and 50% of window)
                max_width = int(total_width * 0.5)
                restored_width = min(max(saved_size, 250), max_width)

                # Set new sizes
                self.top_splitter.setSizes([total_width - restored_width, restored_width])

                # Update menu action
                self.action_toggle_right_panel.setChecked(True)
                log("Right panel expanded", level="info", category="ui")
            else:
                # Save current width before collapsing
                self.settings.setValue("right_panel/width", sizes[1])

                # Collapse panel
                self.top_splitter.setSizes([sum(sizes), 0])

                # Update menu action
                self.action_toggle_right_panel.setChecked(False)
                log("Right panel collapsed", level="info", category="ui")

        except Exception as e:
            log(f"Error toggling right panel: {e}", level="error", category="ui")

    def set_theme_mode(self, mode: str):
        """Switch theme mode and persist. mode in {'light','dark'}."""
        try:
            mode = mode if mode in ('light','dark') else 'dark'
            self.settings.setValue('ui/theme', mode)
            self._current_theme_mode = mode  # Update cached theme state
            self.apply_theme(mode)

            # Update tabbed gallery widget theme
            if hasattr(self, 'gallery_table') and hasattr(self.gallery_table, 'update_theme'):
                self.gallery_table.update_theme()

            # Refresh all icons to use correct light/dark variants for new theme
            self.refresh_all_status_icons()

            # Update theme toggle button tooltip
            if hasattr(self, 'theme_toggle_btn'):
                tooltip = "Switch to light theme" if mode == 'dark' else "Switch to dark theme"
                self.theme_toggle_btn.setToolTip(tooltip)

            # Update checked menu items if available
            try:
                if mode == 'light':
                    self._theme_action_light.setChecked(True)
                else:
                    self._theme_action_dark.setChecked(True)
            except Exception as e:
                log(f"Exception in main_window: {e}", level="error", category="ui")
                raise
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise

    def _load_base_stylesheet(self) -> str:
        """Load the base QSS stylesheet for consistent fonts and styling."""
        # Cache the base stylesheet to avoid repeated disk I/O
        if hasattr(self, '_cached_base_qss'):
            return self._cached_base_qss

        try:
            # Load styles.qss file from assets directory
            qss_path = os.path.join(get_assets_dir(), "styles.qss")
            if os.path.exists(qss_path):
                with open(qss_path, 'r', encoding='utf-8') as f:
                    full_content = f.read()
                    # Extract base styles (everything before LIGHT_THEME_START)
                    light_start = full_content.find('/* LIGHT_THEME_START')
                    if light_start != -1:
                        self._cached_base_qss = full_content[:light_start].strip()
                        return self._cached_base_qss
                    # Fallback: everything before DARK_THEME_START
                    dark_start = full_content.find('/* DARK_THEME_START')
                    if dark_start != -1:
                        self._cached_base_qss = full_content[:dark_start].strip()
                        return self._cached_base_qss
                    self._cached_base_qss = full_content
                    return self._cached_base_qss
        except Exception as e:
            log(f"Error loading styles.qss: {e}", level="error", category="ui")
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

    def _load_theme_styles(self, theme_type: str) -> str:
        """Load theme styles from styles.qss file."""
        # Cache theme stylesheets to avoid repeated disk I/O
        cache_key = f'_cached_{theme_type}_qss'
        if hasattr(self, cache_key):
            return getattr(self, cache_key)

        start_marker = f'/* {theme_type.upper()}_THEME_START'
        end_marker = f'/* {theme_type.upper()}_THEME_END */'

        try:
            # Load styles.qss from assets directory
            qss_path = os.path.join(get_assets_dir(), "styles.qss")
            if os.path.exists(qss_path):
                with open(qss_path, 'r', encoding='utf-8') as f:
                    full_content = f.read()
                    # Extract theme styles (between START and END markers)
                    theme_start = full_content.find(start_marker)
                    theme_end = full_content.find(end_marker)
                    if theme_start != -1 and theme_end != -1:
                        theme_content = full_content[theme_start:theme_end]
                        lines = theme_content.split('\n') # Remove the marker comment line
                        cached_content = '\n'.join(lines[1:])
                        setattr(self, cache_key, cached_content)
                        return cached_content

        except Exception as e:
            log(f"Error loading styles.qss: {e}", level="error", category="ui")
        
        # Fallback: inline theme styles
        if theme_type == 'dark':
            return """
                QWidget { color: #e6e6e6; }
                QToolTip { color: #e6e6e6; background-color: #333333; border: 1px solid #555; }
                QTableWidget { background-color: #1e1e1e; color: #e6e6e6; gridline-color: #555555; border: 1px solid #555555; }
                QTableWidget::item { background-color: #1e1e1e; color: #e6e6e6; }
                QTableWidget::item:selected { background-color: #2f5f9f; color: #ffffff; }
                QHeaderView::section { background-color: #2d2d2d; color: #e6e6e6; }
                QMenu { background-color: #2d2d2d; color: #e6e6e6; border: 1px solid #555; font-size: 12px; }
                QMenu::item { background-color: transparent; }
                QMenu::item:selected { background-color: #2f5f9f; }
                QLabel { color: #e6e6e6; }
            """
        else:  # light theme
            return """
                QWidget { color: #333333; }
                QToolTip { color: #333333; background-color: #ffffcc; border: 1px solid #999; }
                QTableWidget { background-color: #ffffff; color: #333333; gridline-color: #cccccc; border: 1px solid #cccccc; }
                QTableWidget::item { background-color: #ffffff; color: #333333; }
                QTableWidget::item:selected { background-color: #3399ff; color: #ffffff; }
                QHeaderView::section { background-color: #f0f0f0; color: #333333; }
                QMenu { background-color: #ffffff; color: #333333; border: 1px solid #999; font-size: 12px; }
                QMenu::item { background-color: transparent; }
                QMenu::item:selected { background-color: #3399ff; }
                QLabel { color: #333333; }
            """

    def apply_theme(self, mode: str):
        """Apply theme. Only 'light' and 'dark' modes supported.
        Sets application palette and stylesheet for consistent theming.
        """
        try:
            qapp = QApplication.instance()
            if qapp is None or not isinstance(qapp, QApplication):
                return

            # Load base QSS stylesheet
            base_qss = self._load_base_stylesheet()

            if mode == 'dark':
                # Simple dark palette and base stylesheet
                palette = qapp.palette()
                try:
                    palette.setColor(palette.ColorRole.Window, QColor(30,30,30))
                    palette.setColor(palette.ColorRole.WindowText, QColor(230,230,230))
                    palette.setColor(palette.ColorRole.Base, QColor(25,25,25))
                    palette.setColor(palette.ColorRole.Text, QColor(230,230,230))
                    palette.setColor(palette.ColorRole.Button, QColor(45,45,45))
                    palette.setColor(palette.ColorRole.ButtonText, QColor(230,230,230))
                    palette.setColor(palette.ColorRole.Highlight, QColor(47,106,160))
                    palette.setColor(palette.ColorRole.HighlightedText, QColor(255,255,255))
                except Exception as e:
                    log(f"Exception in main_window: {e}", level="error", category="ui")
                    raise
                qapp.setPalette(palette)

                # Load dark theme styles from styles.qss
                theme_qss = self._load_theme_styles('dark')
                qapp.setStyleSheet(base_qss + "\n" + theme_qss)
            elif mode == 'light':
                palette = qapp.palette()
                try:
                    palette.setColor(palette.ColorRole.Window, QColor(255,255,255))
                    palette.setColor(palette.ColorRole.WindowText, QColor(33,33,33))
                    palette.setColor(palette.ColorRole.Base, QColor(255,255,255))
                    palette.setColor(palette.ColorRole.Text, QColor(33,33,33))
                    palette.setColor(palette.ColorRole.Button, QColor(245,245,245))
                    palette.setColor(palette.ColorRole.ButtonText, QColor(33,33,33))
                    palette.setColor(palette.ColorRole.Highlight, QColor(41,128,185))
                    palette.setColor(palette.ColorRole.HighlightedText, QColor(255,255,255))
                except Exception as e:
                    log(f"Exception in main_window: {e}", level="error", category="ui")
                    raise
                qapp.setPalette(palette)

                # Load light theme styles from styles.qss
                theme_qss = self._load_theme_styles('light')
                qapp.setStyleSheet(base_qss + "\n" + theme_qss)
            else:
                # Default to dark if unknown mode
                return self.apply_theme('dark')

            self._current_theme_mode = mode
            # Trigger a light refresh on key widgets
            try:
                #import time
                #t1 = time.time()
                # Just apply font sizes instead of full refresh when changing theme
                if hasattr(self, 'gallery_table') and self.gallery_table:
                    font_size = self._get_current_font_size()
                    self.apply_font_size(font_size)
                #t2 = time.time()
                #log(f"apply_font_size took {(t2-t1)*1000:.1f}ms", level="debug", category="ui")

                # Refresh all button icons that use the icon manager for theme changes
                self._refresh_button_icons()
                #t3 = time.time()
                #log(f"_refresh_button_icons took {(t3-t2)*1000:.1f}ms", level="debug", category="ui")

                self.refresh_all_status_icons()
                #t4 = time.time()
                #log(f"refresh_all_status_icons took {(t4-t3)*1000:.1f}ms", level="debug", category="ui")
                #log(f"TOTAL widget refresh: {(t4-t1)*1000:.1f}ms", level="debug", category="ui")
            except Exception as e:
                log(f"Exception in main_window: {e}", level="error", category="ui")
                raise
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise
    
    def apply_font_size(self, font_size: int):
        """Apply the specified font size throughout the application"""
        try:
            # Update application-wide font sizes
            self._current_font_size = font_size

            # Update table font sizes - set on the actual table widget
            if hasattr(self, 'gallery_table') and hasattr(self.gallery_table, 'table'):
                table = self.gallery_table.table  # This is the actual QTableWidget
                table_font_size = max(font_size - 1, 6)  # Table 1pt smaller, minimum 6pt
                header_font_size = max(font_size - 2, 6)  # Headers even smaller

                # Set font directly on the table widget - this affects all items
                table_font = QFont()
                table_font.setPointSize(table_font_size)
                table.setFont(table_font)

                # Set smaller font on each header item
                header_font = QFont()
                header_font.setPointSize(header_font_size)

                # Use the actual table (table = self.gallery_table.table)
                for col in range(table.columnCount()):
                    header_item = table.horizontalHeaderItem(col)
                    if header_item:
                        header_item.setFont(header_font)

            # Update log text font
            if hasattr(self, 'log_text'):
                log_font = QFont("Consolas")
                log_font_size = max(font_size - 1, 6)  # Log text 1pt smaller
                log_font.setPointSize(log_font_size)
                try:
                    log_font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 98.0)
                except Exception as e:
                    log(f"Exception in main_window: {e}", level="error", category="ui")
                    raise
                self.log_text.setFont(log_font)

            # Save the current font size
            if hasattr(self, 'settings'):
                self.settings.setValue('ui/font_size', font_size)
            
        except Exception as e:
            log(f"Error applying font size: {e}", level="warning", category="ui")
    
    def _get_current_font_size(self) -> int:
        """Get the current font size setting"""
        if hasattr(self, '_current_font_size'):
            return self._current_font_size
        
        # Load from settings
        if hasattr(self, 'settings'):
            return int(self.settings.value('ui/font_size', 9))
        
        return 9  # Default

    def _get_table_font_sizes(self) -> tuple:
        """Get appropriate font sizes for table elements based on current setting"""
        base_font_size = self._get_current_font_size()
        table_font_size = max(base_font_size - 1, 6)  # Table 1pt smaller, minimum 6pt
        name_font_size = base_font_size  # Name column same as base
        return table_font_size, name_font_size

    def setup_system_tray(self):
        """Setup system tray icon"""
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon = QSystemTrayIcon(self)
            
            # Create a simple icon
            pixmap = QPixmap(16, 16)
            pixmap.fill(Qt.GlobalColor.blue)
            self.tray_icon.setIcon(QIcon(pixmap))
            
            # Tray menu
            if self.splash:
                self.splash.set_status("tray menu")
            tray_menu = QMenu()
            
            show_action = tray_menu.addAction("Show")
            show_action.triggered.connect(self.show)
            
            quit_action = tray_menu.addAction("Quit")
            quit_action.triggered.connect(self.close)
            
            if self.splash:
                self.splash.set_status("context menu")
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
            log(f"Creating new UploadWorker (old worker: {id(self.worker) if self.worker else 'None'}{(", running: " and self.worker.isRunning()) if self.worker else ''})", level="debug", category="uploads")
            self.worker = UploadWorker(self.queue_manager)
            log(f"New UploadWorker created ({id(self.worker)})", level="debug", category="uploads")
            self.worker.progress_updated.connect(self.on_progress_updated)
            self.worker.gallery_started.connect(self.on_gallery_started)
            self.worker.gallery_completed.connect(self.on_gallery_completed)
            self.worker.gallery_failed.connect(self.on_gallery_failed)
            self.worker.gallery_exists.connect(self.on_gallery_exists)
            self.worker.gallery_renamed.connect(self.on_gallery_renamed)
            self.worker.ext_fields_updated.connect(self.on_ext_fields_updated)
            self.worker.log_message.connect(self.add_log_message)
            self.worker.queue_stats.connect(self.on_queue_stats)
            self.worker.bandwidth_updated.connect(self.on_bandwidth_updated)

            # Connect to worker status widget
            self.worker.gallery_started.connect(self._on_imx_worker_started)
            self.worker.bandwidth_updated.connect(self._on_imx_worker_speed)
            self.worker.gallery_completed.connect(self._on_imx_worker_finished)
            self.worker.gallery_failed.connect(self._on_imx_worker_finished)

            self.worker.start()
            
            log(f"DEBUG: Worker.isRunning(): {self.worker.isRunning()}", level="debug")
            #log(f"Worker thread started", level="debug")

    def on_queue_item_status_changed(self, path: str, old_status: str, new_status: str):
        """Handle individual queue item status changes"""
        item = self.queue_manager.get_item(path)
        scan_status = item.scan_complete if item else "NO_ITEM"
        in_mapping = path in self.path_to_row
        log(f"DEBUG: GUI received status change signal: {path} from {old_status} to {new_status}, scan_complete={scan_status}, in_path_to_row={in_mapping}", level="debug", category="ui")
        
        # When an item goes from scanning to ready, just update tab counts
        if old_status == "scanning" and new_status == "ready":
            #print(f"DEBUG: Item completed scanning, updating tab counts")
            # Just update the tab counts, don't refresh the filter which hides items
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(150, lambda: self.gallery_table._update_tab_tooltips() if hasattr(self.gallery_table, '_update_tab_tooltips') else None)
        
        # Debug the item data before updating table
        item = self.queue_manager.get_item(path)
        if item:
            log(f"DEBUG: Item data: total_images={getattr(item, 'total_images', 'NOT SET')}, progress={getattr(item, 'progress', 'NOT SET')}, status={getattr(item, 'status', 'NOT SET')}, added_time={getattr(item, 'added_time', 'NOT SET')}", level="debug", category="ui")
        
        # Update table display for this specific item
        self._update_specific_gallery_display(path)
    
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

    def on_bandwidth_updated(self, instant_kbps: float):
        """Update Speed box with rolling average + compression-style smoothing"""
        try:
            # Add to rolling window (keep last 20 samples = 4 seconds at 200ms polling)
            self._bandwidth_samples.append(instant_kbps)
            if len(self._bandwidth_samples) > 20:
                self._bandwidth_samples.pop(0)

            # Calculate average of recent samples to smooth out file completion spikes
            if self._bandwidth_samples:
                averaged_kbps = sum(self._bandwidth_samples) / len(self._bandwidth_samples)
            else:
                averaged_kbps = instant_kbps

            # Apply compression-style smoothing to the averaged value
            if averaged_kbps > self._current_transfer_kbps:
                # Moderate attack - follow increases reasonably fast
                alpha = 0.3
            else:
                # Very slow release - heavily smooth out drops from file completion
                alpha = 0.05

            # Exponential moving average with asymmetric alpha
            self._current_transfer_kbps = alpha * averaged_kbps + (1 - alpha) * self._current_transfer_kbps

            # Always show MiB/s with 3 decimal places
            mib_per_sec = self._current_transfer_kbps / 1024.0
            speed_str = f"{mib_per_sec:.3f} MiB/s"

            # Dim the text if speed is essentially zero (use opacity instead of color)
            if mib_per_sec < 0.001:  # Essentially zero
                self.speed_current_value_label.setStyleSheet("opacity: 0.4;")
            else:
                self.speed_current_value_label.setStyleSheet("opacity: 1.0;")

            self.speed_current_value_label.setText(speed_str)

            # Track fastest speed (still in KiB/s internally for compatibility)
            settings = QSettings("ImxUploader", "ImxUploadGUI")
            fastest_kbps = settings.value("fastest_kbps", 0.0, type=float)
            if self._current_transfer_kbps > fastest_kbps and self._current_transfer_kbps < 10000:  # Sanity check
                settings.setValue("fastest_kbps", self._current_transfer_kbps)
                # Save timestamp when new record is set
                from datetime import datetime
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                settings.setValue("fastest_kbps_timestamp", timestamp)
                fastest_mib = self._current_transfer_kbps / 1024.0  # Use NEW value for display
                fastest_str = f"{fastest_mib:.3f} MiB/s"
                self.speed_fastest_value_label.setText(fastest_str)
                # Update tooltip with timestamp
                self.speed_fastest_value_label.setToolTip(f"Record set: {timestamp}")
        except Exception:
            pass

    # File Host Upload Signal Handlers
    def on_file_host_upload_started(self, gallery_id: int, host_name: str):
        """Handle file host upload started - ASYNC to prevent blocking main thread"""
        log(f"File host upload started: {host_name} for gallery {gallery_id}", level="debug", category="file_hosts")
        # Defer UI refresh to avoid blocking signal emission
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, lambda: self._refresh_file_host_widgets_for_gallery_id(gallery_id))

    def on_file_host_upload_progress(self, gallery_id: int, host_name: str, uploaded_bytes: int, total_bytes: int, speed_bps: float = 0.0):
        """Handle file host upload progress with detailed display"""
        try:
            # Calculate percentage
            if total_bytes > 0:
                percent = int((uploaded_bytes / total_bytes) * 100)
            else:
                percent = 0

            # Format progress info for tooltip/status
            from src.utils.format_utils import format_binary_size
            uploaded_str = format_binary_size(uploaded_bytes)
            total_str = format_binary_size(total_bytes)

            status = f"{host_name}: {percent}% ({uploaded_str} / {total_str})"

            # Log detailed progress at debug level
            log(
                f"File host upload progress: {status}",
                level="debug",
                category="file_hosts"
            )

            # Progress updates are frequent, so we avoid full refresh
            # The file host widgets will poll status and update themselves
        except Exception as e:
            log(f"Error handling file host upload progress: {e}", level="error", category="file_hosts")

    def on_file_host_upload_completed(self, gallery_id: int, host_name: str, result: dict):
        """Handle file host upload completed - ASYNC to prevent blocking main thread"""
        log(f"File host upload completed: {host_name} for gallery {gallery_id}", level="info", category="file_hosts")
        # Defer UI refresh to avoid blocking signal emission
        # Use QTimer.singleShot(0) to schedule on next event loop iteration
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, lambda: self._refresh_file_host_widgets_for_gallery_id(gallery_id))
        # Trigger artifact regeneration if auto-regenerate is enabled (non-blocking, after UI refresh)
        QTimer.singleShot(100, lambda: self._auto_regenerate_for_gallery_id(gallery_id))

    def on_file_host_upload_failed(self, gallery_id: int, host_name: str, error_message: str):
        """Handle file host upload failed - ASYNC to prevent blocking main thread"""
        log(f"File host upload failed: {host_name} for gallery {gallery_id}: {error_message}", level="warning", category="file_hosts")
        # Defer UI refresh to avoid blocking signal emission
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, lambda: self._refresh_file_host_widgets_for_gallery_id(gallery_id))

    def on_file_host_bandwidth_updated(self, kbps: float):
        """Handle file host bandwidth update with smoothing.

        Uses the same rolling average + compression-style smoothing algorithm
        as the IMX.to bandwidth handler for consistent display behavior.

        Args:
            kbps: Instantaneous bandwidth in KB/s
        """
        try:
            # Initialize tracking variables on first call
            if not hasattr(self, '_fh_bandwidth_samples'):
                self._fh_bandwidth_samples = []
                self._fh_current_transfer_kbps = 0.0

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
            self._fh_current_transfer_kbps = alpha * averaged_kbps + (1 - alpha) * self._fh_current_transfer_kbps

            # Convert to MiB/s for display
            mib_per_sec = self._fh_current_transfer_kbps / 1024.0

            # Aggregate with IMX.to bandwidth for total speed display
            # The Speed box shows combined upload speed from both IMX.to and file hosts
            total_kbps = self._current_transfer_kbps + self._fh_current_transfer_kbps
            total_mib = total_kbps / 1024.0
            speed_str = f"{total_mib:.3f} MiB/s"

            # Dim the text if speed is essentially zero
            if total_mib < 0.001:
                self.speed_current_value_label.setStyleSheet("opacity: 0.4;")
            else:
                self.speed_current_value_label.setStyleSheet("opacity: 1.0;")

            self.speed_current_value_label.setText(speed_str)

            # Update fastest speed record if needed
            settings = QSettings("ImxUploader", "ImxUploadGUI")
            fastest_kbps = settings.value("fastest_kbps", 0.0, type=float)
            if total_kbps > fastest_kbps and total_kbps < 10000:  # Sanity check
                settings.setValue("fastest_kbps", total_kbps)
                # Save timestamp when new record is set
                from datetime import datetime
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                settings.setValue("fastest_kbps_timestamp", timestamp)
                fastest_mib = total_kbps / 1024.0
                fastest_str = f"{fastest_mib:.3f} MiB/s"
                self.speed_fastest_value_label.setText(fastest_str)
                # Update tooltip with timestamp
                self.speed_fastest_value_label.setToolTip(f"Record set: {timestamp}")

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
        if not hasattr(self, 'worker_status_widget'):
            return  # Widget disabled, skip update

        self.worker_status_widget.update_worker_status(
            worker_id="imx_worker_1",
            worker_type="imx",
            hostname="imx.to",
            speed_bps=0.0,
            status="uploading"
        )

    def _on_imx_worker_speed(self, speed_kbps: float):
        """Handle imx.to worker speed update."""
        if not hasattr(self, 'worker_status_widget'):
            return  # Widget disabled, skip update

        self.worker_status_widget.update_worker_status(
            worker_id="imx_worker_1",
            worker_type="imx",
            hostname="imx.to",
            speed_bps=speed_kbps * 1024,  # Convert KB/s to bytes/s
            status="uploading"
        )

    def _on_imx_worker_finished(self, *args):
        """Handle imx.to worker upload finished."""
        if not hasattr(self, 'worker_status_widget'):
            return  # Widget disabled, skip update

        self.worker_status_widget.update_worker_status(
            worker_id="imx_worker_1",
            worker_type="imx",
            hostname="imx.to",
            speed_bps=0.0,
            status="idle"
        )

    def _on_filehost_worker_started(self, gallery_id: int, host_name: str):
        """Handle file host worker upload started."""
        if not hasattr(self, 'worker_status_widget'):
            return  # Widget disabled, skip update

        worker_id = f"filehost_{host_name.lower().replace(' ', '_')}"
        self.worker_status_widget.update_worker_status(
            worker_id=worker_id,
            worker_type="filehost",
            hostname=host_name,
            speed_bps=0.0,
            status="uploading"
        )

    def _on_filehost_worker_progress(self, gallery_id: int, host_name: str,
                                      uploaded: int, total: int, speed_bps: float):
        """Handle file host worker upload progress."""
        if not hasattr(self, 'worker_status_widget'):
            return  # Widget disabled, skip update

        worker_id = f"filehost_{host_name.lower().replace(' ', '_')}"
        self.worker_status_widget.update_worker_status(
            worker_id=worker_id,
            worker_type="filehost",
            hostname=host_name,
            speed_bps=speed_bps,
            status="uploading"
        )
        self.worker_status_widget.update_worker_progress(
            worker_id=worker_id,
            gallery_id=gallery_id,
            progress_bytes=uploaded,
            total_bytes=total
        )

    def _on_filehost_worker_completed(self, gallery_id: int, host_name: str, result: dict):
        """Handle file host worker upload completion."""
        if not hasattr(self, 'worker_status_widget'):
            return  # Widget disabled, skip update

        worker_id = f"filehost_{host_name.lower().replace(' ', '_')}"
        self.worker_status_widget.update_worker_status(
            worker_id=worker_id,
            worker_type="filehost",
            hostname=host_name,
            speed_bps=0.0,
            status="idle"
        )

    def _on_filehost_worker_failed(self, gallery_id: int, host_name: str, error: str):
        """Handle file host worker upload failure."""
        if not hasattr(self, 'worker_status_widget'):
            return  # Widget disabled, skip update

        worker_id = f"filehost_{host_name.lower().replace(' ', '_')}"
        self.worker_status_widget.update_worker_error(worker_id, error)

    def _on_file_host_startup_spinup(self, host_id: str, error: str):
        """Track worker spinup during startup to know when all are ready."""
        from PyQt6.QtCore import QMutexLocker

        with QMutexLocker(self._file_host_startup_mutex):
            if self._file_host_startup_complete:
                return

            self._file_host_startup_completed += 1
            if self._file_host_startup_completed >= self._file_host_startup_expected:
                self._file_host_startup_complete = True

    def _update_worker_queue_stats(self):
        """Poll queue manager and update worker status widget with queue statistics.

        Calculates total files and bytes remaining across all galleries in queue
        and updates the worker status widget's Files Left and Remaining columns.

        Called by QTimer every 2 seconds.
        """
        if not hasattr(self, 'queue_manager') or not hasattr(self, 'worker_status_widget'):
            return

        try:
            # Calculate totals from queue
            total_files_remaining = 0
            total_bytes_remaining = 0

            for item in self.queue_manager.get_all_items():
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
            self.worker_status_widget.update_queue_columns(total_files_remaining, total_bytes_remaining)

        except Exception as e:
            log(f"Error updating worker queue stats: {e}", level="error", category="ui")

    def _refresh_file_host_widgets_for_gallery_id(self, gallery_id: int):
        """Refresh file host widgets for a specific gallery ID - OPTIMIZED VERSION

        This method is called asynchronously via QTimer to avoid blocking signal emission.
        Optimized to use O(1) lookups instead of iterating all items.
        """
        try:
            # OPTIMIZATION 1: Use cached gallery_id -> path mapping if available
            # This avoids iterating through all queue items
            if not hasattr(self, '_gallery_id_to_path'):
                self._gallery_id_to_path = {}

            gallery_path = self._gallery_id_to_path.get(gallery_id)

            # If not cached, fall back to search (only on first miss)
            if not gallery_path:
                for item in self.queue_manager.get_all_items():
                    if item.gallery_id and str(item.gallery_id) == str(gallery_id):
                        gallery_path = item.path
                        # Cache for future lookups
                        self._gallery_id_to_path[gallery_id] = gallery_path
                        break

            if not gallery_path:
                return

            # OPTIMIZATION 2: O(1) row lookup via path_to_row dict
            row = self.path_to_row.get(gallery_path)
            if row is None:
                return

            # OPTIMIZATION 3: Get widget reference first, skip DB query if widget missing
            from src.gui.widgets.custom_widgets import FileHostsStatusWidget
            status_widget = self.gallery_table.table.cellWidget(row, GalleryTableWidget.COL_HOSTS_STATUS)
            if not isinstance(status_widget, FileHostsStatusWidget):
                log(f"File host status widget not found at row {row} for gallery_id {gallery_id}", level="debug", category="file_hosts")
                return  # Widget not present, skip expensive DB query

            # Only do DB query if we have a valid widget to update
            host_uploads = {}
            try:
                uploads_list = self.queue_manager.store.get_file_host_uploads(gallery_path)
                host_uploads = {upload['host_name']: upload for upload in uploads_list}
            except Exception as e:
                log(f"Failed to load file host uploads: {e}", level="warning", category="file_hosts")
                return

            # Update widget (already confirmed it exists and is correct type)
            status_widget.update_hosts(host_uploads)
            status_widget.update()  # Force visual refresh

        except Exception as e:
            log(f"Error refreshing file host widgets: {e}", level="error", category="file_hosts")
            import traceback
            traceback.print_exc()


    def browse_for_folders(self):
        """Open folder browser to select galleries or archives (supports multiple selection)"""
        # Create file dialog with multi-selection support
        file_dialog = QFileDialog(self)
        file_dialog.setWindowTitle("Select Gallery Folders and/or Archives")
        file_dialog.setFileMode(QFileDialog.FileMode.Directory)  # Allow directory selection
        file_dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        file_dialog.setOption(QFileDialog.Option.ShowDirsOnly, False)  # Allow both folders and files
        file_dialog.setNameFilter("All Files and Folders (*)")
        
        # Enable proper multi-selection on internal views (Ctrl+click, Shift+click)
        list_view = file_dialog.findChild(QListView, 'listView')
        if list_view:
            list_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            # Apply the app's stylesheet to match theme selection colors
            list_view.setStyleSheet(self.styleSheet())
        
        tree_view = file_dialog.findChild(QTreeView)
        if tree_view:
            tree_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            # Apply the app's stylesheet to match theme selection colors
            tree_view.setStyleSheet(self.styleSheet())
        
        # Execute dialog and add selected items (folders or archives)
        if file_dialog.exec() == QFileDialog.DialogCode.Accepted:
            selected_paths = file_dialog.selectedFiles()
            if selected_paths:
                self.add_folders_or_archives(selected_paths)
    
    def add_folders_or_archives(self, paths: List[str]):
        """Add folders or archives to upload queue"""
        folders = []
        archives = []

        for path in paths:
            if os.path.isdir(path):
                folders.append(path)
            elif os.path.isfile(path) and is_archive_file(path):
                archives.append(path)

        # Process folders normally
        if folders:
            self.add_folders(folders)

        # Process archives in background threads
        for archive_path in archives:
            worker = ArchiveExtractionWorker(archive_path, self.archive_coordinator)
            worker.signals.finished.connect(self.on_archive_extraction_finished)
            worker.signals.error.connect(self.on_archive_extraction_error)
            self._thread_pool.start(worker)
            log(f"DEBUG: Started background extraction for: {os.path.basename(archive_path)}", level="debug", category="ui")

    def add_folders(self, folder_paths: List[str]):
        """Add folders to the upload queue with duplicate detection"""
        log(f"add_folders called with {len(folder_paths)} paths", level="trace", category="queue")

        if len(folder_paths) == 1:
            # Single folder - use the old method for backward compatibility
            self._add_single_folder(folder_paths[0])
        else:
            # Multiple folders - use new duplicate detection system
            self._add_multiple_folders_with_duplicate_detection(folder_paths)
    
    def _add_single_folder(self, path: str):
        """Add a single folder with duplicate detection."""
        log(f"_add_single_folder called with path={path}", level="trace", category="queue")
        
        # Use duplicate detection for single folders too
        folder_name = os.path.basename(path)
        
        # Check if already in queue
        existing_item = self.queue_manager.get_item(path)
        if existing_item:
            from PyQt6.QtWidgets import QMessageBox
            
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Icon.Question)
            msg.setWindowTitle("Already in Queue")
            msg.setText(f"'{folder_name}' is already in the queue.")
            msg.setInformativeText(f"Current status: {existing_item.status}\n\nDo you want to replace it?")
            msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            msg.setDefaultButton(QMessageBox.StandardButton.No)
            
            if msg.exec() == QMessageBox.StandardButton.Yes:
                # Replace existing
                self.queue_manager.remove_item(path)
                log(f"DEBUG: Replaced {folder_name} in queue", level="debug", category="queue")
            else:
                return  # User chose not to replace
        
        # Check if previously uploaded
        existing_files = self._check_if_gallery_exists(folder_name)
        if existing_files:
            from PyQt6.QtWidgets import QMessageBox
            
            files_text = ', '.join(existing_files) if existing_files else "gallery files"
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Icon.Warning)
            msg.setWindowTitle("Previously Uploaded")
            msg.setText(f"'{folder_name}' appears to have been uploaded before.")
            msg.setInformativeText(f"Found: {files_text}\n\nAre you sure you want to upload it again?")
            msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            msg.setDefaultButton(QMessageBox.StandardButton.No)
            
            if msg.exec() != QMessageBox.StandardButton.Yes:
                return  # User chose not to upload
        
        # Proceed with adding
        template_name = self.template_combo.currentText()
        # Get current tab BEFORE adding item ("All Tabs" is virtual, default to Main)
        current_tab = self.gallery_table.current_tab if hasattr(self.gallery_table, 'current_tab') else "Main"
        actual_tab = "Main" if current_tab == "All Tabs" else current_tab
        #print(f"{timestamp()} DEBUG: Single folder - adding to tab: {actual_tab}")
        result = self.queue_manager.add_item(path, template_name=template_name, tab_name=actual_tab)
        
        if result == True:
            log(f"Added to queue: {os.path.basename(path)}", category="queue", level="info")
            # Add to table display
            item = self.queue_manager.get_item(path)
            if item:
                self._add_gallery_to_table(item)
                # Force immediate table refresh to ensure visibility and update tab counts
                # TESTING: Comment out _update_scanned_rows to see if it's causing race condition
                #QTimer.singleShot(50, self._update_scanned_rows)
                QTimer.singleShot(100, lambda: self._update_tab_tooltips() if hasattr(self, '_update_tab_tooltips') else None)
        else:
            log(f"Failed to add: {os.path.basename(path)} (no images found)", category="queue", level="warning")

    def _add_archive_folder(self, folder_path: str, archive_path: str):
        """Add a folder from extracted archive to queue"""
        template_name = self.template_combo.currentText()
        current_tab = self.gallery_table.current_tab if hasattr(self.gallery_table, 'current_tab') else "Main"

        # Derive gallery name from folder, removing "extract_" prefix if present
        folder_name = os.path.basename(folder_path)
        if folder_name.startswith('extract_'):
            gallery_name = folder_name[8:]  # Remove "extract_" prefix
        else:
            gallery_name = folder_name

        # "All Tabs" is virtual, default to Main
        actual_tab = "Main" if current_tab == "All Tabs" else current_tab
        result = self.queue_manager.add_item(folder_path, name=gallery_name, template_name=template_name, tab_name=actual_tab)

        if result:
            # Mark as from archive
            item = self.queue_manager.get_item(folder_path)
            if item:
                item.source_archive_path = archive_path
                item.is_from_archive = True
                self.queue_manager.save_persistent_queue([folder_path])
                self._add_gallery_to_table(item)
                log(f"Added from archive: {gallery_name}", category="queue", level="info")

    def on_archive_extraction_finished(self, archive_path: str, selected_folders: List[str]):
        """Handle successful archive extraction (called from worker thread signal)"""
        log(f"Archive extraction completed: {os.path.basename(archive_path)} ({len(selected_folders)} folders)", 
            level="info", category="fileio")
        
        # Add all selected folders to queue
        for folder_path in selected_folders:
            self._add_archive_folder(folder_path, archive_path)

    def on_archive_extraction_error(self, archive_path: str, error_message: str):
        """Handle archive extraction error (called from worker thread signal)"""
        log(f"Archive extraction failed for {os.path.basename(archive_path)}: {error_message}", 
            level="warning", category="fileio")
        
        # Only show message box if it's a real error (not user cancellation)
        if "cancelled" not in error_message.lower() and "no folders selected" not in error_message.lower():
            QMessageBox.warning(
                self,
                "Archive Extraction Failed",
                f"Failed to extract {os.path.basename(archive_path)}:\n\n{error_message}"
            )
            
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
            log(f"Error checking gallery existence: {e}", category="queue", level="error")
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
            log(f"Skipped: {os.path.basename(path)} (user cancelled)", category="queue", level="debug")
    
    def _force_add_gallery(self, path: str, gallery_name: str, template_name: str):
        """Force add gallery to queue and update display"""
        # Get current tab ("All Tabs" is virtual, default to Main)
        current_tab = self.gallery_table.current_tab if hasattr(self.gallery_table, 'current_tab') else "Main"
        actual_tab = "Main" if current_tab == "All Tabs" else current_tab

        # Add to queue with correct tab
        self.queue_manager.add_item(path, name=gallery_name, template_name=template_name, tab_name=actual_tab)

        # Get the item for display
        item = self.queue_manager.get_item(path)
        
        log(f"Added to queue (user confirmed): {os.path.basename(path)}", category="queue", level="")
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
            # "All Tabs" is virtual, filter it out for post-add tab assignment
            current_tab = self.gallery_table.current_tab if hasattr(self.gallery_table, 'current_tab') else "Main"
            actual_tab = "Main" if current_tab == "All Tabs" else current_tab
            if actual_tab != "Main" and results['added_paths']:
                tab_info = self.tab_manager.get_tab_by_name(actual_tab)
                if tab_info:
                    for path in results['added_paths']:
                        item = self.queue_manager.get_item(path)
                        if item:
                            item.tab_name = actual_tab
                            item.tab_id = tab_info.id
                            self.queue_manager._save_single_item(item)
            
            # Update progress
            progress.setValue(len(folder_paths))
            
            # Show results
            if results['added'] > 0:
                log(f"Added {results['added']} galleries to queue", category="queue", level="info")
            if results['duplicates'] > 0:
                log(f"Skipped {results['duplicates']} duplicate galleries", category="queue", level="info")
            if results['failed'] > 0:
                log(f"Failed to add {results['failed']} galleries", category="queue")
                # Show detailed errors if any
                for error in results['errors'][:5]:  # Show first 5 errors
                    log(f"WARNING: {error}", category="queue", level="warning")
                if len(results['errors']) > 5:
                    log(f"... and {len(results['errors']) - 5} more errors", category="queue", level="warning")
            
            # Add all successfully added items to table
            for path in results.get('added_paths', []):
                item = self.queue_manager.get_item(path)
                if item:
                    self._add_gallery_to_table(item)
            
            # Force immediate table refresh to ensure visibility
            if results.get('added_paths'):
                # TESTING: Comment out _update_scanned_rows to see if it's causing race condition
                #QTimer.singleShot(50, self._update_scanned_rows)
                pass
            
        except Exception as e:
            log(f"ERROR: Adding multiple folders: {str(e)}", category="queue", level="error")
        finally:
            progress.close()
    
    def _add_multiple_folders_with_duplicate_detection(self, folder_paths: List[str]):
        """Add multiple folders with duplicate detection dialogs"""
        from src.gui.dialogs.duplicate_detection_dialogs import show_duplicate_detection_dialogs
        from imxup import timestamp
        
        try:
            # Show duplicate detection dialogs and get processed lists
            folders_to_add_normally, folders_to_replace_in_queue = show_duplicate_detection_dialogs(
                folders_to_add=folder_paths,
                check_gallery_exists_func=self._check_if_gallery_exists,
                queue_manager=self.queue_manager,
                parent=self
            )
            
            # Process folders that passed duplicate checks
            if folders_to_add_normally:
                #print(f"DEBUG: Adding {len(folders_to_add_normally)} folders normally")
                template_name = self.template_combo.currentText()
                # Get current tab BEFORE adding items ("All Tabs" is virtual, default to Main)
                current_tab = self.gallery_table.current_tab if hasattr(self.gallery_table, 'current_tab') else "Main"
                actual_tab = "Main" if current_tab == "All Tabs" else current_tab
                log(f"Multiple folders - adding to tab: {actual_tab}", level="debug", category="queue")

                for folder_path in folders_to_add_normally:
                    try:
                        result = self.queue_manager.add_item(folder_path, template_name=template_name, tab_name=actual_tab)
                        if result:
                            # Get the created item and immediately add to table display
                            item = self.queue_manager.get_item(folder_path)
                            if item:
                                # Add to table display immediately (like single folder does)
                                self._add_gallery_to_table(item)
                            
                            log(f"Added to queue: {os.path.basename(folder_path)}", category="queue", level="debug")
                    except Exception as e:
                        log(f"Error while adding folder: {os.path.basename(folder_path)}: {e}", level="error", category="queue")
            
            # Process folders that should replace existing queue items
            if folders_to_replace_in_queue:
                log(f"Replacing {len(folders_to_replace_in_queue)} folders in queue", level="debug", category="queue")
                template_name = self.template_combo.currentText()
                # Get current tab for replacements too ("All Tabs" is virtual, default to Main)
                if 'actual_tab' not in locals():
                    current_tab = self.gallery_table.current_tab if hasattr(self.gallery_table, 'current_tab') else "Main"
                    actual_tab = "Main" if current_tab == "All Tabs" else current_tab
                    log(f"Multiple folders replacement - adding to tab: {actual_tab}", level="debug", category="queue")
                for folder_path in folders_to_replace_in_queue:
                    try:
                        # Remove existing item from both queue and table
                        self.queue_manager.remove_item(folder_path)
                        self._remove_gallery_from_table(folder_path)

                        # Add new item with correct tab
                        result = self.queue_manager.add_item(folder_path, template_name=template_name, tab_name=actual_tab)
                        if result:
                            # Get the created item and immediately add to table display
                            item = self.queue_manager.get_item(folder_path)
                            if item:
                                # Add to table display immediately
                                self._add_gallery_to_table(item)
                        
                        log(f"Replaced {os.path.basename(folder_path)} in queue", level="debug", category="queue")
                    except Exception as e:
                        log(f"Error while replacing {os.path.basename(folder_path)}: {e}", level="error", category="queue")
            
            # Update display
            total_processed = len(folders_to_add_normally) + len(folders_to_replace_in_queue)
            if total_processed > 0:
                log(f"Added {total_processed} galleries to queue", level="info", category="queue")
                # Trigger table refresh and update tab counts/tooltips
                # TESTING: Comment out _update_scanned_rows to see if it's causing race condition
                #QTimer.singleShot(50, self._update_scanned_rows)
                QTimer.singleShot(100, lambda: self._update_tab_tooltips() if hasattr(self, '_update_tab_tooltips') else None)
            
        except Exception as e:
            log(f"Error while processing folders: {e}", level="error", category="queue")
    
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
        log(f"_add_gallery_to_table called for {item.path} with tab_name={item.tab_name}", level="debug", category="queue")

        # CRITICAL FIX: Check if path already exists in table to prevent duplicates
        if item.path in self.path_to_row:
            existing_row = self.path_to_row[item.path]
            log(f"Gallery already in table at row {existing_row}, updating instead of adding duplicate", level="debug", category="queue")
            # Update existing row instead of creating duplicate
            self._populate_table_row(existing_row, item)
            return

        row = self.gallery_table.rowCount()
        self.gallery_table.setRowCount(row + 1)
        log(f"Adding NEW gallery to table at row {row}", level="debug", category="queue")

        # Update mappings
        self.path_to_row[item.path] = row
        self.row_to_path[row] = item.path
        log(f"Added {item.path} to path_to_row at row {row}, scan_complete={item.scan_complete}, status={item.status}", level="debug", category="queue")

        # Initialize scan state tracking
        self._last_scan_states[item.path] = item.scan_complete
        log(f"Initialized _last_scan_states[{item.path}] = {item.scan_complete}", level="debug", category="queue")
        
        # Populate the new row
        self._populate_table_row(row, item)
        
        # Make sure the row is visible if it belongs to the current tab
        current_tab = self.gallery_table.current_tab if hasattr(self.gallery_table, 'current_tab') else None
        if current_tab and (current_tab == "All Tabs" or item.tab_name == current_tab):
            self.gallery_table.setRowHidden(row, False)
            log(f"Row {row} set VISIBLE for current tab '{current_tab}' (item tab: '{item.tab_name}')", level="trace", category="queue")
        else:
            self.gallery_table.setRowHidden(row, True)
            log(f"Row {row} set HIDDEN - item tab '{item.tab_name}' != current tab '{current_tab}'", level="trace", category="queue")
        
        # Invalidate TabManager's cache for this tab so it reloads from database
        if hasattr(self.gallery_table, 'tab_manager') and item.tab_name:
            self.gallery_table.tab_manager.invalidate_tab_cache(item.tab_name)
            log(f"Invalidated TabManager cache for tab {item.tab_name}", level="debug", category="queue")

        # CRITICAL FIX: Invalidate table update queue visibility cache so new visible rows get updates
        if hasattr(self, '_table_update_queue') and self._table_update_queue:
            self._table_update_queue.invalidate_visibility_cache()
            log(f"Invalidated table update queue visibility cache after adding row {row}", level="debug", category="queue")
    
    def _remove_gallery_from_table(self, path: str):
        """Remove a gallery from the table and update mappings"""
        if path not in self.path_to_row:
            return

        row_to_remove = self.path_to_row[path]
        # Get the actual table (handle tabbed interface)
        table = self.gallery_table
        if hasattr(self.gallery_table, 'table'):
            table = self.gallery_table.table
        table.removeRow(row_to_remove)
        
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
            name_item = self.gallery_table.item(row, GalleryTableWidget.COL_NAME)
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
        
        # Get current font sizes

        # If item not in table, skip update (it should be added explicitly via add_folders)
        # This prevents duplicate additions via status change signals
        if path not in self.path_to_row:
            log(f"Item {path} not in path_to_row, skipping update (prevents duplicates)", level="debug")
            return
        
        # Check if row is currently visible for performance optimization
        row = self.path_to_row.get(path)
        log(f"DEBUG: _update_specific_gallery_display - row={row}, path_to_row has path: {path in self.path_to_row}", level="debug", category="queue")
        if row is not None and 0 <= row < self.gallery_table.rowCount():
            #log(f"Row {row} is valid, checking update queue", level="debug")
            # Use table update queue for visible rows (includes hidden row filtering)
            if hasattr(self, '_table_update_queue'):
                #print(f"DEBUG: Using _table_update_queue to update row {row}")
                self._table_update_queue.queue_update(path, item, 'full')
            else:
                log(f"No _table_update_queue, using direct update for row {row}", level="debug")
                # Fallback to direct update
                QTimer.singleShot(0, lambda: self._populate_table_row(row, item))
        else:
            # If update fails, refresh filter as fallback
            log(f"Row update failed for {path}, refreshing filter", level="warning", category="queue")
            if hasattr(self.gallery_table, 'refresh_filter'):
                QTimer.singleShot(0, self.gallery_table.refresh_filter)
    
    
    def _refresh_button_icons(self):
        """Refresh all button icons that use the icon manager for correct theme"""
        try:
            #import time
            #t_start = time.time()

            icon_mgr = get_icon_manager()
            if not icon_mgr:
                return
            #t1 = time.time()
            #log(f"  get_icon_manager: {(t1-t_start)*1000:.1f}ms", level="debug", category="ui")

            # Map of button attributes to their icon keys
            button_icon_map = [
                ('manage_templates_btn', 'templates'),
                ('manage_credentials_btn', 'credentials'),
                ('hooks_btn', 'hooks'),
                ('log_viewer_btn', 'log_viewer'),
                ('theme_toggle_btn', 'toggle_theme'),
                # Add more buttons here as needed when they get icon manager support
            ]

            # Update each button's icon if it exists
            for button_attr, icon_key in button_icon_map:
                if hasattr(self, button_attr):
                    button = getattr(self, button_attr)
                    icon = icon_mgr.get_icon(icon_key)
                    if not icon.isNull():
                        button.setIcon(icon)
            #t2 = time.time()
            #log(f"button icons updated: {(t2-t1)*1000:.1f}ms", level="trace", category="ui")

            # Refresh renamed column icons - ONLY VISIBLE ROWS for fast theme switching
            table = self.gallery_table
            if hasattr(self.gallery_table, 'table'):
                table = self.gallery_table.table

            # Get visible row range
            viewport = table.viewport()
            viewport_height = viewport.height()
            total_rows = table.rowCount()
            first_visible = table.rowAt(0)
            last_visible = table.rowAt(viewport_height - 1)  # -1 to stay within bounds

            #log(f"  Table has {total_rows} rows, viewport height={viewport_height}px", level="debug", category="ui")
            #log(f"  rowAt(0)={first_visible}, rowAt({viewport_height-1})={last_visible}", level="debug", category="ui")

            # Handle edge cases
            if first_visible == -1:
                first_visible = 0
            if last_visible == -1:
                # Viewport extends past last row - just use the actual last row
                last_visible = min(total_rows - 1, first_visible + 20)  # Max 20 visible rows

            # Add buffer rows for smooth scrolling
            first_visible = max(0, first_visible - 5)
            last_visible = min(total_rows - 1, last_visible + 5)
            #t3 = time.time()
            #log(f"  Final visible range ({first_visible}-{last_visible}) = {last_visible - first_visible + 1} rows: {(t3-t2)*1000:.1f}ms", level="debug", category="ui")

            # Only refresh renamed icons for visible rows (not hidden by tab filtering)
            row_count = 0
            for row in range(first_visible, last_visible + 1):
                # Skip rows hidden by tab filtering
                if table.isRowHidden(row):
                    continue

                item = table.item(row, GalleryTableWidget.COL_RENAMED)
                if item and not item.icon().isNull():
                    is_renamed = item.toolTip() == "Renamed"
                    self._set_renamed_cell_icon(row, is_renamed)
                    row_count += 1
            #t4 = time.time()
            #log(f"  refreshed {row_count} renamed icons: {(t4-t3)*1000:.1f}ms", level="debug", category="ui")

            # Set flag so scrolling will refresh newly visible renamed icons
            if hasattr(table, '_needs_full_icon_refresh'):
                table._needs_full_icon_refresh = True

            #log(f"  TOTAL _refresh_button_icons: {(t4-t_start)*1000:.1f}ms", level="debug", category="ui")
        except Exception as e:
            log(f"ERROR: Exception refreshing button icons: {e}", level="warning", category="ui")

    def _populate_table_row(self, row: int, item: GalleryQueueItem, total: int = 0):
        """Update row data immediately with proper font consistency - COMPLETE VERSION"""
        # Update splash screen during startup (only every 10 rows to avoid constant repaints)
        if hasattr(self, 'splash') and self.splash and row % 10 == 0:
            try:
                if total > 0:
                    percentage = int((row / total) * 100)
                    self.splash.update_status(f"Loading gallery {row}/{total} ({percentage}%)")
                else:
                    self.splash.update_status(f"Loading gallery {row}")
            except Exception as e:
                log(f"ERROR: Exception in main_window: {e}", level="error", category="ui")
                raise

        # CRITICAL: Verify row is still valid for this item (table may have changed due to deletions)
        # Always use the current mapping as the source of truth
        actual_row = self.path_to_row.get(item.path)

        if actual_row is None:
            # Item was removed from table entirely
            log(f"Skipping update - {os.path.basename(item.path)} no longer in table", level="debug", category="queue")
            return

        if actual_row != row:
            # Table was modified (row deletions/insertions), use current row
            log(f"Row adjusted for {os.path.basename(item.path)}: {row} → {actual_row}", level="trace", category="queue")
            row = actual_row

        theme_mode = self._current_theme_mode

        # Order number - show database ID (persistent, matches logs like "gallery 1555")
        order_item = NumericTableWidgetItem(item.db_id if item.db_id else 0)
        order_item.setFlags(order_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        order_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.gallery_table.setItem(row, GalleryTableWidget.COL_ORDER, order_item)

        # Gallery name and path
        display_name = item.name or os.path.basename(item.path) or "Unknown"
        name_item = QTableWidgetItem(display_name)
        name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        name_item.setData(Qt.ItemDataRole.UserRole, item.path)
        self.gallery_table.setItem(row, GalleryTableWidget.COL_NAME, name_item)

        # Upload progress - always create cell, blank until images are counted
        total_images = getattr(item, 'total_images', 0) or 0
        uploaded_images = getattr(item, 'uploaded_images', 0) or 0
        uploaded_text = ""
        if total_images > 0:
            uploaded_text = f"{uploaded_images}/{total_images}"
        uploaded_item = QTableWidgetItem(uploaded_text)
        uploaded_item.setFlags(uploaded_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        uploaded_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.gallery_table.setItem(row, GalleryTableWidget.COL_UPLOADED, uploaded_item)

        # Progress bar - defer creation during initial load for speed
        if not hasattr(self, '_initializing') or not self._initializing:
            progress_widget = self.gallery_table.cellWidget(row, 3)
            if not isinstance(progress_widget, TableProgressWidget):
                progress_widget = TableProgressWidget()
                self.gallery_table.setCellWidget(row, 3, progress_widget)
            progress_widget.update_progress(item.progress, item.status)

        # Status icon and text
        self._set_status_cell_icon(row, item.status)
        # Skip STATUS_TEXT column (5) if hidden - optimization to avoid creating unused QTableWidgetItems
        if not self.gallery_table.isColumnHidden(GalleryTableWidget.COL_STATUS_TEXT):
            self._set_status_text_cell(row, item.status)


        # Added time
        added_text, added_tooltip = format_timestamp_for_display(item.added_time)
        added_item = QTableWidgetItem(added_text)
        added_item.setFlags(added_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        added_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if added_tooltip:
            added_item.setToolTip(added_tooltip)
        self.gallery_table.setItem(row, GalleryTableWidget.COL_ADDED, added_item)

        # Finished time
        finished_text, finished_tooltip = format_timestamp_for_display(item.finished_time)
        finished_item = QTableWidgetItem(finished_text)
        finished_item.setFlags(finished_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        finished_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if finished_tooltip:
            finished_item.setToolTip(finished_tooltip)
        self.gallery_table.setItem(row, GalleryTableWidget.COL_FINISHED, finished_item)
        
        # Size column with consistent binary formatting
        size_bytes = getattr(item, 'total_size', 0) or 0
        size_text = ""
        if size_bytes > 0:
            size_text = self._format_size_consistent(size_bytes)
        size_item = QTableWidgetItem(size_text)
        size_item.setFlags(size_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        size_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        # PyQt is retarded, manually set font
        self.gallery_table.setItem(row, GalleryTableWidget.COL_SIZE, size_item)
        
        # Transfer speed column - Skip TRANSFER column (10) if hidden to avoid creating unused QTableWidgetItems
        if not self.gallery_table.isColumnHidden(GalleryTableWidget.COL_TRANSFER):
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
            xfer_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if item.status == "uploading" and transfer_text:
                xfer_item.setForeground(QColor(173, 216, 255, 255) if theme_mode == 'dark' else QColor(20, 90, 150, 255))
            elif item.status in ("completed", "failed") and transfer_text:
                xfer_item.setForeground(QColor(255, 255, 255, 230) if theme_mode == 'dark' else QColor(0, 0, 0, 190))
            self.gallery_table.setItem(row, GalleryTableWidget.COL_TRANSFER, xfer_item)
        
        # Template name (always left-aligned for consistency)
        template_text = item.template_name or ""
        tmpl_item = QTableWidgetItem(template_text)
        tmpl_item.setFlags(tmpl_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        tmpl_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.gallery_table.setItem(row, GalleryTableWidget.COL_TEMPLATE, tmpl_item)
        
        # Renamed status: Set icon based on whether gallery has been renamed
        # Check if gallery is in the unnamed galleries list (pending rename)
        from imxup import check_gallery_renamed
        is_renamed = check_gallery_renamed(item.gallery_id) if item.gallery_id else None
        self._set_renamed_cell_icon(row, is_renamed)

        # Custom columns and Gallery ID: Load from database
        # Get the actual table object (same logic as in _on_table_item_changed)
        actual_table = getattr(self.gallery_table, 'table', self.gallery_table)

        # Temporarily block signals to prevent itemChanged during initialization
        signals_blocked = actual_table.signalsBlocked()
        actual_table.blockSignals(True)
        try:
            # Gallery ID column (13) - read-only, skip if hidden to avoid creating unused QTableWidgetItems
            if not self.gallery_table.isColumnHidden(GalleryTableWidget.COL_GALLERY_ID):
                gallery_id_text = item.gallery_id or ""
                gallery_id_item = QTableWidgetItem(gallery_id_text)
                gallery_id_item.setFlags(gallery_id_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                gallery_id_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                actual_table.setItem(row, GalleryTableWidget.COL_GALLERY_ID, gallery_id_item)

            # Custom columns (14-17) - editable, skip hidden ones to avoid creating unused QTableWidgetItems
            for col_idx, field_name in [
                (GalleryTableWidget.COL_CUSTOM1, 'custom1'),
                (GalleryTableWidget.COL_CUSTOM2, 'custom2'),
                (GalleryTableWidget.COL_CUSTOM3, 'custom3'),
                (GalleryTableWidget.COL_CUSTOM4, 'custom4')
            ]:
                if not self.gallery_table.isColumnHidden(col_idx):
                    value = getattr(item, field_name, '') or ''
                    custom_item = QTableWidgetItem(str(value))
                    # Make custom columns editable
                    custom_item.setFlags(custom_item.flags() | Qt.ItemFlag.ItemIsEditable)
                    custom_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                    actual_table.setItem(row, col_idx, custom_item)

            # Ext columns (18-21) - editable (populated by external apps or user), skip hidden ones
            for col_idx, field_name in [
                (GalleryTableWidget.COL_EXT1, 'ext1'),
                (GalleryTableWidget.COL_EXT2, 'ext2'),
                (GalleryTableWidget.COL_EXT3, 'ext3'),
                (GalleryTableWidget.COL_EXT4, 'ext4')
            ]:
                if not self.gallery_table.isColumnHidden(col_idx):
                    value = getattr(item, field_name, '') or ''
                    ext_item = QTableWidgetItem(str(value))
                    # Make ext columns editable
                    ext_item.setFlags(ext_item.flags() | Qt.ItemFlag.ItemIsEditable)
                    ext_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                    actual_table.setItem(row, col_idx, ext_item)
        finally:
            # Restore original signal state
            actual_table.blockSignals(signals_blocked)
        
        # Action buttons - CREATE MISSING ACTION BUTTONS FOR NEW ITEMS
        try:
            existing_widget = self.gallery_table.cellWidget(row, GalleryTableWidget.COL_ACTION)
            if not isinstance(existing_widget, ActionButtonWidget):
                action_widget = ActionButtonWidget(parent=self)
                # Connect button signals with proper closure capture
                action_widget.start_btn.setEnabled(item.status != "scanning")
                action_widget.start_btn.clicked.connect(lambda checked, path=item.path: self.start_single_item(path))
                action_widget.stop_btn.clicked.connect(lambda checked, path=item.path: self.stop_single_item(path))
                action_widget.view_btn.clicked.connect(lambda checked, path=item.path: self.handle_view_button(path))
                action_widget.cancel_btn.clicked.connect(lambda checked, path=item.path: self.cancel_single_item(path))
                action_widget.update_buttons(item.status)
                self.gallery_table.setCellWidget(row, GalleryTableWidget.COL_ACTION, action_widget)
            else:
                # Update existing widget status
                existing_widget.update_buttons(item.status)
                existing_widget.start_btn.setEnabled(item.status != "scanning")
        except Exception as e:
            print(f"ERROR: Failed to create action buttons for row {row}: {e}")
            import traceback
            traceback.print_exc()

        # File host widgets - CREATE/UPDATE FILE HOST STATUS AND ACTION WIDGETS
        try:
            from src.gui.widgets.custom_widgets import FileHostsStatusWidget, FileHostsActionWidget

            # Get file host upload data from database
            # PERFORMANCE: Use cached batch data if available (startup optimization)
            host_uploads = {}
            try:
                if hasattr(self, '_file_host_uploads_cache'):
                    # Use pre-loaded batch cache (989 queries → 1 query)
                    uploads_list = self._file_host_uploads_cache.get(item.path, [])
                else:
                    # Fallback to individual query (used after startup)
                    uploads_list = self.queue_manager.store.get_file_host_uploads(item.path)
                host_uploads = {upload['host_name']: upload for upload in uploads_list}
            except Exception as e:
                log(f"Failed to load file host uploads for {item.path}: {e}", level="warning", category="file_hosts")

            # HOSTS_STATUS widget (icons)
            existing_status_widget = self.gallery_table.cellWidget(row, GalleryTableWidget.COL_HOSTS_STATUS)
            if not isinstance(existing_status_widget, FileHostsStatusWidget):
                status_widget = FileHostsStatusWidget(item.path, parent=self)
                status_widget.update_hosts(host_uploads)
                # Connect signal to show host details dialog
                status_widget.host_clicked.connect(self._on_file_host_icon_clicked)
                self.gallery_table.setCellWidget(row, GalleryTableWidget.COL_HOSTS_STATUS, status_widget)
            else:
                # Update existing widget
                existing_status_widget.update_hosts(host_uploads)

            # HOSTS_ACTION widget (manage button)
            existing_action_widget = self.gallery_table.cellWidget(row, GalleryTableWidget.COL_HOSTS_ACTION)
            if not isinstance(existing_action_widget, FileHostsActionWidget):
                hosts_action_widget = FileHostsActionWidget(item.path, parent=self)
                # Connect signal to show file host details dialog
                hosts_action_widget.manage_clicked.connect(self._on_file_hosts_manage_clicked)
                self.gallery_table.setCellWidget(row, GalleryTableWidget.COL_HOSTS_ACTION, hosts_action_widget)

        except Exception as e:
            log(f"Failed to create file host widgets for row {row}: {e}", level="error", category="file_hosts")
            import traceback
            traceback.print_exc()


    def _populate_table_row_detailed(self, row: int, item: GalleryQueueItem):
        """Complete row formatting in background - TRULY NON-BLOCKING"""
        # Use background thread for expensive formatting operations
        def format_row_data():
            """Prepare formatted data in background thread"""
            try:
                # Prepare all data without touching GUI
                formatted_data = {}
                
                # Order number data - show database ID (persistent, matches logs)
                formatted_data['order'] = item.db_id if item.db_id else 0
                
                # Time formatting (expensive datetime operations)
                formatted_data['added_text'], formatted_data['added_tooltip'] = format_timestamp_for_display(item.added_time)
                formatted_data['finished_text'], formatted_data['finished_tooltip'] = format_timestamp_for_display(item.finished_time)
                
                return formatted_data
            except Exception:
                return None
        
        def apply_formatted_data(formatted_data):
            """Apply formatted data to table - runs on main thread"""
            if formatted_data is None or row >= self.gallery_table.rowCount():
                return
                
            try:
                # Get current font sizes
                # Order number (column 0) - quick operation
                order_item = NumericTableWidgetItem(formatted_data['order'])
                order_item.setFlags(order_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                order_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                # Apply font size
                self.gallery_table.setItem(row, GalleryTableWidget.COL_ORDER, order_item)
                
                # Added time (column 6)
                added_item = QTableWidgetItem(formatted_data['added_text'])
                added_item.setFlags(added_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                added_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if formatted_data['added_tooltip']:
                    added_item.setToolTip(formatted_data['added_tooltip'])
                # Apply font size
                self.gallery_table.setItem(row, GalleryTableWidget.COL_ADDED, added_item)

                # Finished time (column 7)
                finished_item = QTableWidgetItem(formatted_data['finished_text'])
                finished_item.setFlags(finished_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                finished_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if formatted_data['finished_tooltip']:
                    finished_item.setToolTip(formatted_data['finished_tooltip'])
                self.gallery_table.setItem(row, GalleryTableWidget.COL_FINISHED, finished_item)
                
                # Apply minimal styling to uploaded count
                uploaded_item = self.gallery_table.item(row, GalleryTableWidget.COL_UPLOADED)
                if uploaded_item:
                    uploaded_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                
            except Exception as e:
                log(f"Exception in main_window: {e}", level="error", category="ui")
                raise  # Fail silently
        
        # Execute formatting in background, then apply on main thread
        task = BackgroundTask(format_row_data)
        task.signals.finished.connect(apply_formatted_data)
        task.signals.error.connect(lambda err: None)  # Ignore errors
        self._thread_pool.start(task, priority=-2)  # Lower priority than icon tasks
        
        # Size and transfer rate (expensive formatting) - only call if not already set
        # Check if size column already has a value to avoid unnecessary updates during uploads
        size_item_existing = self.gallery_table.item(row, GalleryTableWidget.COL_SIZE)
        if (item.scan_complete and hasattr(item, 'total_size') and item.total_size > 0 and 
            (not size_item_existing or not size_item_existing.text().strip())):
            theme_mode = self._current_theme_mode
            self._update_size_and_transfer_columns(row, item, theme_mode)
    
    def _update_size_and_transfer_columns(self, row: int, item: GalleryQueueItem, theme_mode: str):
        """Update size and transfer columns with proper formatting"""
        # Size (column 9)
        size_bytes = int(getattr(item, 'total_size', 0) or 0)
        if not self._format_functions_cached:
            try:
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
        self.gallery_table.setItem(row, GalleryTableWidget.COL_SIZE, size_item)

        # Transfer rate (column 10)
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
            if item.status == "uploading" and transfer_text:
                xfer_item.setForeground(QColor(173, 216, 255, 255) if theme_mode == 'dark' else QColor(20, 90, 150, 255))
            else:
                if transfer_text:
                    xfer_item.setForeground(QColor(0, 0, 0, 160))
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise
        self.gallery_table.setItem(row, GalleryTableWidget.COL_TRANSFER, xfer_item)
    

    def _initialize_table_from_queue(self, progress_callback=None):
        """Initialize table from existing queue items - called once on startup

        Args:
            progress_callback: Optional callable(current, total) for progress updates
        """
        log(f"_initialize_table_from_queue() called", level="debug", category="ui")

        # Clear any existing mappings
        self.path_to_row.clear()
        self.row_to_path.clear()

        # Get all items and build table
        items = self.queue_manager.get_all_items()
        log(f"Loading {len(items)} galleries from queue", level="info", category="ui")
        self.gallery_table.setRowCount(len(items))

        # PERFORMANCE OPTIMIZATION: Batch load all file host uploads in ONE query
        # This replaces 989 individual queries with a single batch query,
        # reducing startup time by 40-70 seconds
        try:
            self._file_host_uploads_cache = self.queue_manager.store.get_all_file_host_uploads_batch()
            log(f"Batch loaded file host uploads for {len(self._file_host_uploads_cache)} galleries",
                level="debug", category="performance")
        except Exception as e:
            log(f"Failed to batch load file host uploads: {e}", level="warning", category="performance")
            self._file_host_uploads_cache = {}

        # Set flag to defer expensive widget creation during initial load
        self._initializing = True

        # PERFORMANCE OPTIMIZATION: Disable table updates during bulk load
        # This prevents per-row repaints and dramatically speeds up startup
        self.gallery_table.setUpdatesEnabled(False)
        self.gallery_table.setSortingEnabled(False)

        try:
            total_items = len(items)
            for row, item in enumerate(items):
                # Update mappings
                self.path_to_row[item.path] = row
                self.row_to_path[row] = item.path

                # Populate the row (progress widgets deferred)
                self._populate_table_row(row, item, total_items)

                # Initialize scan state tracking
                self._last_scan_states[item.path] = item.scan_complete

                # Update progress every 10 galleries (batching for performance)
                if progress_callback and (row + 1) % 10 == 0:
                    try:
                        progress_callback(row + 1, total_items)
                    except Exception as e:
                        log(f"Progress callback error at row {row+1}: {e}", level="error")

            # Report final progress at completion
            if progress_callback:
                progress_callback(len(items), len(items))

        except Exception as e:
            log(f"Error in _initialize_table_from_queue: {e}", level="error", category="performance")
            raise
        finally:
            # CRITICAL: ALWAYS re-enable updates, even on exceptions (prevents permanent UI freeze)
            self.gallery_table.setSortingEnabled(True)
            self.gallery_table.setUpdatesEnabled(True)

        # Create progress widgets in background after initial load
        self._initializing = False
        QTimer.singleShot(100, lambda: self._create_deferred_widgets(len(items)))

        # After building the table, apply the current tab filter and emit tab_changed to update counts
        if hasattr(self.gallery_table, 'refresh_filter'):
            def _apply_initial_filter():
                self.gallery_table.refresh_filter()
                # Emit tab_changed signal to trigger button count and progress updates
                if hasattr(self.gallery_table, 'tab_changed') and hasattr(self.gallery_table, 'current_tab'):
                    self.gallery_table.tab_changed.emit(self.gallery_table.current_tab)
            QTimer.singleShot(0, _apply_initial_filter)

    def _create_deferred_widgets(self, total_rows: int):
        """Create deferred widgets (progress bars, action buttons) after initial load"""
        log(f"Creating deferred widgets for {total_rows} items...", level="debug", category="ui")

        for row in range(min(total_rows, self.gallery_table.rowCount())):
            path = self.row_to_path.get(row)
            if path:
                item = self.queue_manager.get_item(path)
                if item:
                    # Create progress widget
                    progress_widget = self.gallery_table.cellWidget(row, GalleryTableWidget.COL_PROGRESS)
                    if not isinstance(progress_widget, TableProgressWidget):
                        progress_widget = TableProgressWidget()
                        self.gallery_table.setCellWidget(row, GalleryTableWidget.COL_PROGRESS, progress_widget)
                        progress_widget.update_progress(item.progress, item.status)

            # Process events every 20 rows to keep UI responsive during background creation
            if row % 20 == 0:
                QApplication.processEvents()
            if row % 100 == 0:
                log(f"{row}/{total_rows} deferred widgets created...", level="debug", category="ui")
        log(f"Finished creating {total_rows} deferred widgets", level="debug", category="ui")

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
                #print(f"DEBUG: _update_scanned_rows - Scan state changed for {item.path}: {last_state} -> {current_state}, status={item.status}")
                # Scan state changed
                
                # Only update the specific row that changed
                row = self.path_to_row.get(item.path)
                if row is not None and row < self.gallery_table.rowCount():
                    # Update only the columns that need updating for this specific item
                    # Upload count (column 2) - ONLY update existing items, never create new ones
                    if item.total_images > 0:
                        uploaded_text = f"{item.uploaded_images}/{item.total_images}"
                        existing_item = self.gallery_table.item(row, GalleryTableWidget.COL_UPLOADED)
                        if existing_item:
                            existing_item.setText(uploaded_text)
                        # DO NOT create new items - font issues
                    
                    # Size (column 9) - ONLY update existing items, never create new ones
                    if item.total_size > 0:
                        size_text = self._format_size_consistent(item.total_size)
                        existing_item = self.gallery_table.item(row, GalleryTableWidget.COL_SIZE)
                        if existing_item:
                            existing_item.setText(size_text)

                        # DO NOT create new items - font issues
                    
                    # Update status column
                    self._set_status_cell_icon(row, item.status)
                    self._set_status_text_cell(row, item.status)

                    # Update action column for any status change
                    action_widget = self.gallery_table.cellWidget(row, GalleryTableWidget.COL_ACTION)
                    if isinstance(action_widget, ActionButtonWidget):
                        log(f"Updating action buttons for {item.path}, status: {item.status}", level="debug")
                        action_widget.update_buttons(item.status)
                        if item.status == "ready":
                            action_widget.start_btn.setEnabled(True)
        
        # Update button counts if any scans completed (status may have changed to ready)
        if updated_any:
            QTimer.singleShot(0, self._update_button_counts)

    def _get_current_tab_items(self):
        """Get items filtered by current tab"""
        current_tab = getattr(self.gallery_table, 'current_tab', 'Main')
        
        if current_tab == "All Tabs":
            return self.queue_manager.get_all_items()
        elif current_tab == "Main" or not self.tab_manager:
            # For Main tab, get items with no tab assignment or explicit Main assignment
            all_items = self.queue_manager.get_all_items()
            return [item for item in all_items if not item.tab_name or item.tab_name == "Main"]
        else:
            # For custom tabs, get items assigned to that tab
            try:
                tab_galleries = self.tab_manager.load_tab_galleries(current_tab)
                tab_paths = {g.get('path') for g in tab_galleries if g.get('path')}
                all_items = self.queue_manager.get_all_items()
                return [item for item in all_items if item.path in tab_paths]
            except Exception:
                return []

    def _update_counts_and_progress(self):
        """Update both button counts and progress display together"""
        self._update_button_counts()
        self.update_progress_display()
    
    def _update_button_counts(self):
        """Update button counts and states based on currently visible items (respecting filter)"""
        try:
            # Get items that are currently visible (not filtered out)
            visible_items = []
            all_items = self.queue_manager.get_all_items()
            
            # Build path to row mapping for quick lookup
            path_to_row = {}
            for row in range(self.gallery_table.rowCount()):
                name_item = self.gallery_table.item(row, GalleryTableWidget.COL_NAME)
                if name_item:
                    path = name_item.data(Qt.ItemDataRole.UserRole)
                    if path:
                        path_to_row[path] = row
            
            # Only count items that are visible in the current filter
            for item in all_items:
                row = path_to_row.get(item.path)
                if row is not None and not self.gallery_table.isRowHidden(row):
                    visible_items.append(item)
            
            # Count statuses from visible items only
            count_startable = sum(1 for item in visible_items if item.status in ("ready", "paused", "incomplete", "scanning"))
            count_pausable = sum(1 for item in visible_items if item.status in ("uploading", "queued"))
            count_completed = sum(1 for item in visible_items if item.status == "completed")

            # Update button texts with counts (preserve leading space for visual alignment)
            self.start_all_btn.setText(" Start All " + (f"({count_startable})" if count_startable else ""))
            self.pause_all_btn.setText(" Pause All " + (f"({count_pausable})" if count_pausable else ""))
            self.clear_completed_btn.setText(" Clear Completed " + (f"({count_completed})" if count_completed else ""))

            # Enable/disable based on counts
            self.start_all_btn.setEnabled(count_startable > 0)
            self.pause_all_btn.setEnabled(count_pausable > 0)
            self.clear_completed_btn.setEnabled(count_completed > 0)
        except Exception:
            # Controls may not be initialized yet during early calls
            pass
    
    def update_progress_display(self):
        """Update current tab progress and statistics"""
        items = self._get_current_tab_items()
        
        if not items:
            self.overall_progress.setValue(0)
            self.overall_progress.setText("Ready")
            # Blue for active/ready
            self.overall_progress.setProgressProperty("status", "ready")
            current_tab_name = getattr(self.gallery_table, 'current_tab', 'All Tabs')
            self.stats_label.setText(f"No galleries in {current_tab_name}")
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
            self.overall_progress.setText(f"{overall_percent}% ({uploaded_images}/{total_images})")
            # Blue while in progress, green when 100%
            if overall_percent >= 100:
                self.overall_progress.setProgressProperty("status", "completed")
            else:
                self.overall_progress.setProgressProperty("status", "uploading")
        else:
            self.overall_progress.setValue(0)
            self.overall_progress.setText("Preparing...")
            # Blue while preparing
            self.overall_progress.setProgressProperty("status", "uploading")
        
        # Update stats label with current tab status counts
        current_tab_name = getattr(self.gallery_table, 'current_tab', 'All Tabs')
        status_counts = {
            'uploading': sum(1 for item in items if item.status == 'uploading'),
            'queued': sum(1 for item in items if item.status == 'queued'),
            'completed': sum(1 for item in items if item.status == 'completed'),
            'ready': sum(1 for item in items if item.status in ('ready', 'paused', 'incomplete', 'scanning')),
            'failed': sum(1 for item in items if item.status == 'failed')
        }
        
        # Build status summary - only show non-zero counts
        status_parts = []
        if status_counts['uploading'] > 0:
            status_parts.append(f"Uploading: {status_counts['uploading']}")
        if status_counts['queued'] > 0:
            status_parts.append(f"Queued: {status_counts['queued']}")
        if status_counts['completed'] > 0:
            status_parts.append(f"Completed: {status_counts['completed']}")
        if status_counts['ready'] > 0:
            status_parts.append(f"Ready: {status_counts['ready']}")
        if status_counts['failed'] > 0:
            status_parts.append(f"Error: {status_counts['failed']}")
        
        if status_parts:
            self.stats_label.setText(" | ".join(status_parts))
        else:
            self.stats_label.setText(f"No galleries in {current_tab_name}")
        
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
        # Show transferred and fastest speed in Speed box
        try:
            self.speed_transferred_value_label.setText(f"{total_size_str}")
            # Display fastest speed (convert KiB/s to MiB/s)
            fastest_mib = fastest_kbps / 1024.0
            fastest_str = f"{fastest_mib:.3f} MiB/s"
            self.speed_fastest_value_label.setText(fastest_str)
            # Set tooltip with timestamp only if there's a record and timestamp
            fastest_timestamp = settings.value("fastest_kbps_timestamp", "", type=str)
            if fastest_kbps > 0 and fastest_timestamp:
                self.speed_fastest_value_label.setToolTip(f"Record set: {fastest_timestamp}")
            else:
                self.speed_fastest_value_label.setToolTip("")  # Clear tooltip
        except Exception as e:
            log(f"ERROR: Exception in main_window: {e}", level="error", category="ui")
            raise
        # Current transfer speed: calculate from ALL uploading items (not tab-filtered)
        all_items = self.queue_manager.get_all_items()
        current_kibps = 0.0
        uploading_count = 0
        for item in all_items:
            if item.status == "uploading":
                item_speed = float(getattr(item, 'current_kibps', 0.0) or 0.0)
                current_kibps += item_speed
                uploading_count += 1
        
        # Speed labels are now updated ONLY by on_bandwidth_updated() signal handler
        # Fastest speed is tracked there and persists across all uploads

        # Clear bandwidth samples when no uploads are active to reset display
        if uploading_count == 0:
            self._bandwidth_samples.clear()
            self._current_transfer_kbps = 0.0
            self.speed_current_value_label.setText("0.000 MiB/s")
            self.speed_current_value_label.setStyleSheet("opacity: 0.4;")
        # Status summary text is updated via signal handlers to avoid timer-driven churn
    
    
    
    # Removed _refresh_active_upload_indicators to prevent GUI blocking
    
    def on_gallery_started(self, path: str, total_images: int):
        """Handle gallery start"""
        with QMutexLocker(self.queue_manager.mutex):
            if path in self.queue_manager.items:
                item = self.queue_manager.items[path]
                item.total_images = total_images
                item.uploaded_images = 0

        # Check for file host auto-upload triggers (on_started)
        try:
            from src.core.file_host_config import get_config_manager
            config_manager = get_config_manager()
            triggered_hosts = config_manager.get_hosts_by_trigger('started')

            if triggered_hosts:
                log(f"Gallery started trigger: Found {len(triggered_hosts)} enabled hosts with 'On Started' trigger",
                    level="info", category="file_hosts")

                for host_id, host_config in triggered_hosts.items():
                    # Queue upload to this file host (use host_id, not display name)
                    upload_id = self.queue_manager.store.add_file_host_upload(
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
            log(f"Error checking file host triggers on gallery start: {e}", level="error", category="file_hosts")

        # Update only the specific row status instead of full table refresh
        # Also ensure settings are disabled while uploads are active
        #try:
        #    self.settings_group.setEnabled(False)
        #except Exception as e:
        #    log(f"ERROR: Exception in main_window: {e}", level="error", category="ui")
        #    raise

        for row in range(self.gallery_table.rowCount()):
            name_item = self.gallery_table.item(row, GalleryTableWidget.COL_NAME)
            if name_item and name_item.data(Qt.ItemDataRole.UserRole) == path:
                # Update uploaded count
                uploaded_text = f"0/{total_images}"
                uploaded_item = QTableWidgetItem(uploaded_text)
                uploaded_item.setFlags(uploaded_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                uploaded_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.gallery_table.setItem(row, GalleryTableWidget.COL_UPLOADED, uploaded_item)
                
                # Update status cell
                current_status = item.status
                self._set_status_cell_icon(row, current_status)
                self._set_status_text_cell(row, current_status)
                
                
                # Update action buttons
                action_widget = self.gallery_table.cellWidget(row, GalleryTableWidget.COL_ACTION)
                if isinstance(action_widget, ActionButtonWidget):
                    action_widget.update_buttons(current_status)
                break
        
        # Update button counts and progress after gallery starts
        QTimer.singleShot(0, self._update_counts_and_progress)
    
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
                except Exception as e:
                    log(f"Exception in main_window: {e}", level="error", category="ui")
                    raise

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
            self.gallery_table.setItem(matched_row, GalleryTableWidget.COL_UPLOADED, uploaded_item)
            
            # Progress bar (column 3)
            progress_widget = self.gallery_table.cellWidget(matched_row, 3)
            if isinstance(progress_widget, TableProgressWidget):
                progress_widget.update_progress(progress_percent, item.status)
            
            # Transfer speed column (column 10) - show live speed for uploading items
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
                # Use live transfer color
                theme_mode = self._current_theme_mode
                xfer_item.setForeground(QColor(173, 216, 255, 255) if theme_mode == 'dark' else QColor(20, 90, 150, 255))
                self.gallery_table.setItem(matched_row, GalleryTableWidget.COL_TRANSFER, xfer_item)
            
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
                # Final icon and text
                self._set_status_cell_icon(matched_row, item.status)
                self._set_status_text_cell(matched_row, item.status)

                # Update action buttons for completed status
                action_widget = self.gallery_table.cellWidget(matched_row, GalleryTableWidget.COL_ACTION)
                if isinstance(action_widget, ActionButtonWidget):
                    action_widget.update_buttons(item.status)
                
                # Update finished time column
                finished_text, finished_tooltip = format_timestamp_for_display(item.finished_time)
                finished_item = QTableWidgetItem(finished_text)
                finished_item.setFlags(finished_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                finished_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if finished_tooltip:
                    finished_item.setToolTip(finished_tooltip)
                    pass
                self.gallery_table.setItem(matched_row, GalleryTableWidget.COL_FINISHED, finished_item)

                # Compute and freeze final transfer speed for this item
                try:
                    elapsed = max(float(item.finished_time or time.time()) - float(item.start_time or item.finished_time), 0.001)
                    item.final_kibps = (float(getattr(item, 'uploaded_bytes', 0) or 0) / elapsed) / 1024.0
                    item.current_kibps = 0.0
                except Exception as e:
                    log(f"Exception in main_window: {e}", level="error", category="ui")
                    raise
                
                # Render Transfer column (10) - use cached function
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
                    if final_text:
                        xfer_item.setForeground(QColor(0, 0, 0, 160))
                except Exception as e:
                    log(f"ERROR: Exception in main_window: {e}", level="error", category="ui")
                    raise
                self.gallery_table.setItem(matched_row, GalleryTableWidget.COL_TRANSFER, xfer_item)
                
            # Update overall progress bar and info/speed displays after individual table updates
            self.update_progress_display()
                
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise  # Fail silently to prevent blocking
    
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
                except Exception as e:
                    log(f"ERROR: Exception in main_window: {e}", level="error", category="ui")
                    raise

        # Check for file host auto-upload triggers (on_completed)
        try:
            from src.core.file_host_config import get_config_manager
            config_manager = get_config_manager()
            triggered_hosts = config_manager.get_hosts_by_trigger('completed')

            if triggered_hosts:
                log(f"Gallery completed trigger: Found {len(triggered_hosts)} enabled hosts with 'On Completed' trigger",
                    level="info", category="file_hosts")

                for host_id, host_config in triggered_hosts.items():
                    # Queue upload to this file host (use host_id, not display name)
                    upload_id = self.queue_manager.store.add_file_host_upload(
                        gallery_path=path,
                        host_name=host_id,  # host_id like 'filedot', not display name
                        status='pending'
                    )

                    if upload_id:
                        log(f"Queued file host upload for {path} to {host_config.name} (upload_id={upload_id})", level="info", category="file_hosts")
                    else:
                        log(f"Failed to queue file host upload for {path} to {host_config.name}", level="error", category="file_hosts")
        except Exception as e:
            log(f"Error checking file host triggers on gallery completion: {e}", level="error", category="file_hosts")

        # Force final progress update to show 100% completion
        if path in self.queue_manager.items:
            final_item = self.queue_manager.items[path]
            self._progress_batcher.add_update(path, final_item.uploaded_images, final_item.total_images, 100, "")
        
        # Cleanup temp folder if from archive
        if path in self.queue_manager.items:
            itm = self.queue_manager.items[path]
            if getattr(itm, 'is_from_archive', False):
                QTimer.singleShot(0, lambda p=path: self.archive_coordinator.service.cleanup_temp_dir(p))

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
        except Exception as e:
            log(f"ERROR: Exception in main_window: {e}", level="error", category="ui")
            raise
        
        # Re-enable settings if no remaining active items (defer to avoid blocking)
        #QTimer.singleShot(5, self._check_and_enable_settings)

        # Update display with targeted update instead of full rebuild
        self._update_specific_gallery_display(path)

        # Auto-clear completed gallery if enabled
        from imxup import load_user_defaults
        defaults = load_user_defaults()
        if defaults.get('auto_clear_completed', False):
            # Get item to check if it's actually completed (not failed)
            item = self.queue_manager.get_item(path)
            if item and item.status == "completed":
                QTimer.singleShot(100, lambda: self._remove_gallery_from_table(path))


        # Update button counts and progress after status change
        QTimer.singleShot(0, self._update_counts_and_progress)

        # Defer only the heavy stats update to avoid blocking
        QTimer.singleShot(50, lambda: self._update_stats_deferred(results))
    
    #def _check_and_enable_settings(self):
    #    """Check if settings should be enabled - deferred to avoid blocking GUI"""
    #    try:
    #        remaining = self.queue_manager.get_all_items()
    #        any_active = any(i.status in ("queued", "uploading") for i in remaining)
    #        self.settings_group.setEnabled(not any_active)
    #    except Exception as e:
    #        log(f"ERROR: Exception in main_window: {e}", level="error", category="ui")
    #        raise
    
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
        except Exception as e:
            log(f"ERROR: Exception in main_window: {e}", level="error", category="ui")
            raise

    def on_ext_fields_updated(self, path: str, ext_fields: dict):
        """Handle ext fields update from external hooks"""
        try:
            log(f"on_ext_fields_updated called: path={path}, ext_fields={ext_fields}", level="info", category="hooks")

            # Update the item in the queue manager (already done by worker)
            # Just need to refresh the table row to show the new values
            with QMutexLocker(self.queue_manager.mutex):
                if path in self.queue_manager.items:
                    item = self.queue_manager.items[path]
                    log(f"Found item in queue_manager: {item.name}", level="debug", category="hooks")

                    # Get the actual table widget - SAME PATTERN AS _populate_table_row
                    actual_table = getattr(self.gallery_table, 'table', self.gallery_table)
                    log(f"Using actual_table: {type(actual_table).__name__}", level="debug", category="hooks")

                    # Find the table row for this gallery
                    if actual_table:
                        log(f"Table has {actual_table.rowCount()} rows", level="debug", category="hooks")
                        for row in range(actual_table.rowCount()):
                            name_item = actual_table.item(row, GalleryTableWidget.COL_NAME)
                            if name_item and name_item.data(Qt.ItemDataRole.UserRole) == path:
                                log(f"Found matching row {row} for path {path}", level="debug", category="hooks")

                                # Block signals to prevent itemChanged events during update
                                signals_blocked = actual_table.signalsBlocked()
                                actual_table.blockSignals(True)
                                try:
                                    # Update ext columns
                                    for ext_field, value in ext_fields.items():
                                        log(f"Processing ext_field={ext_field}, value={value}", level="debug", category="hooks")
                                        if ext_field == 'ext1':
                                            ext_item = QTableWidgetItem(str(value))
                                            ext_item.setFlags(ext_item.flags() | Qt.ItemFlag.ItemIsEditable)
                                            ext_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                                            actual_table.setItem(row, GalleryTableWidget.COL_EXT1, ext_item)
                                            log(f"Set COL_EXT1 (col {GalleryTableWidget.COL_EXT1}) to: {value}", level="trace", category="hooks")
                                        elif ext_field == 'ext2':
                                            ext_item = QTableWidgetItem(str(value))
                                            ext_item.setFlags(ext_item.flags() | Qt.ItemFlag.ItemIsEditable)
                                            ext_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                                            actual_table.setItem(row, GalleryTableWidget.COL_EXT2, ext_item)
                                            log(f"Set COL_EXT2 (col {GalleryTableWidget.COL_EXT2}) to: {value}", level="trace", category="hooks")
                                        elif ext_field == 'ext3':
                                            ext_item = QTableWidgetItem(str(value))
                                            ext_item.setFlags(ext_item.flags() | Qt.ItemFlag.ItemIsEditable)
                                            ext_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                                            actual_table.setItem(row, GalleryTableWidget.COL_EXT3, ext_item)
                                            log(f"Set COL_EXT3 (col {GalleryTableWidget.COL_EXT3}) to: {value}", level="trace", category="hooks")
                                        elif ext_field == 'ext4':
                                            ext_item = QTableWidgetItem(str(value))
                                            ext_item.setFlags(ext_item.flags() | Qt.ItemFlag.ItemIsEditable)
                                            ext_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                                            actual_table.setItem(row, GalleryTableWidget.COL_EXT4, ext_item)
                                            log(f"Set COL_EXT4 (col {GalleryTableWidget.COL_EXT4}) to: {value}", level="trace", category="hooks")
                                finally:
                                    # Restore original signal state
                                    actual_table.blockSignals(signals_blocked)

                                log(f"Updated ext fields in GUI for {item.name}: {ext_fields}", level="info", category="hooks")
                                # Trigger artifact regeneration for ext field changes if enabled
                                QTimer.singleShot(100, lambda p=path: self.regenerate_bbcode_for_gallery(p, force=False) if self._should_auto_regenerate_bbcode(p) else None)
                                break
                    else:
                        log(f"WARNING: Table is None!", level="debug", category="hooks")
                else:
                    log(f"Path {path} not found in queue_manager.items", level="debug", category="hooks")
        except Exception as e:
            log(f"Error updating ext fields in GUI: {e}", level="error", category="hooks")
            import traceback
            traceback.print_exc()

    
    def on_completion_processed(self, path: str):
        """Handle when background completion processing is done"""
        # Background file generation is complete, nothing specific needed here
        # but could trigger additional UI updates if needed in the future
        pass
    
    
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
            log(f"Upload cancelled by user due to existing gallery", level="info", category="ui")
            # TODO: Implement proper cancellation mechanism
        else:
            log("User chose to continue with existing gallery", level="info", category="ui")

    def on_gallery_renamed(self, gallery_id: str):
        """Mark cells for the given gallery_id as renamed (check icon) - optimized version."""
        # Update unnamed gallery count
        self._update_unnamed_count_background()
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
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise

    def on_gallery_failed(self, path: str, error_message: str):
        """Handle gallery failure"""
        with QMutexLocker(self.queue_manager.mutex):
            if path in self.queue_manager.items:
                item = self.queue_manager.items[path]
                item.status = "failed"
                item.error_message = error_message
        
        # Re-enable settings if no remaining active (queued/uploading) items
        #try:
        #    remaining = self.queue_manager.get_all_items()
        #    any_active = any(i.status in ("queued", "uploading") for i in remaining)
        #    self.settings_group.setEnabled(not any_active)
        #except Exception as e:
        #    log(f"ERROR: Exception in main_window: {e}", level="error", category="ui")
        #    raise

        # Update display when status changes  
        self._update_specific_gallery_display(path)
        
        # Update button counts and progress after status change
        QTimer.singleShot(0, self._update_counts_and_progress)
        
        gallery_name = os.path.basename(path)
        log(f"Failed: {gallery_name} - {error_message}", level="warning")
    
    def _ensure_log_visible(self):
        """Ensure log is scrolled to bottom - called via QTimer for thread safety"""
        try:
            vbar = self.log_text.verticalScrollBar()
            if vbar:
                vbar.setValue(vbar.maximum())
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise

    def add_log_message(self, message: str):
        """
        Add message to GUI log list (simple display only).

        Filtering is already done by logger.py before this is called.
        This method formats the message based on cached display settings:
        - Strips log level prefix (DEBUG:, etc.) if show_log_level_gui=false
        - Strips category tags ([network], etc.) if show_category_gui=false
        - Always preserves timestamp prefix (HH:MM:SS)

        Settings are cached in _log_show_level and _log_show_category for performance.
        """
        try:
            # Use cached settings instead of lookup (performance optimization)
            # Start with the original message
            display = message
            prefix = ""

            # Extract timestamp prefix if present (HH:MM:SS)
            parts = message.split(" ", 1)
            if len(parts) > 1 and parts[0].count(":") == 2:
                prefix = parts[0] + " "
                rest = parts[1]
            else:
                rest = message

            # ALWAYS strip log level prefix from GUI display (keep in log viewer only)
            level_prefixes = ["TRACE: ", "DEBUG: ", "INFO: ", "WARNING: ", "ERROR: ", "CRITICAL: "]
            for level_prefix in level_prefixes:
                if rest.startswith(level_prefix):
                    rest = rest[len(level_prefix):]
                    break

            # Strip [category] or [category:subtype] tag if setting is disabled (cached value)
            if not self._log_show_category:
                if rest.startswith("[") and "]" in rest:
                    close_idx = rest.find("]")
                    rest = rest[close_idx + 1:].lstrip()

            display = prefix + rest

            # Prepend to top of list (newest first)
            self.log_text.insertItem(0, display)

            # Limit to 5000 items
            if self.log_text.count() > 5000:
                self.log_text.takeItem(5000)
        except Exception as e:
            # Fallback: add raw message if stripping fails
            self.log_text.insertItem(0, message)

    def show_status_message(self, message: str, timeout: int = 2500):
        """
        Show a temporary message in the status bar.

        Args:
            message: Message to display
            timeout: Duration in milliseconds (default 2500ms = 2.5 seconds)
        """
        status_bar = self.statusBar()
        if status_bar:
            status_bar.showMessage(message, timeout)

    def open_log_viewer(self):
        """Open comprehensive settings to logs tab"""
        self.open_comprehensive_settings(tab_index=5)  # Logs tab

    def open_log_viewer_popup(self):
        """Open standalone log viewer dialog popup"""
        try:
            log(f"Opening log viewer dialog popup", level="debug", category="ui")
            from src.utils.logging import get_logger
            initial_text = get_logger().read_current_log(tail_bytes=2 * 1024 * 1024) or ""
        except Exception as e:
            log("Error opening log viewer dialog popup: {e}", level="error", category="ui")
            initial_text = ""

        dialog = LogViewerDialog(initial_text, self)
        dialog.show()  # Non-modal dialog

    def open_icon_manager(self):
        """Open Icon Manager dialog"""
        from src.gui.dialogs.icon_manager_dialog import IconManagerDialog

        dialog = IconManagerDialog(self)
        dialog.exec()

    def open_unrenamed_galleries_dialog(self):
        """Open dialog to manage unrenamed galleries"""
        from src.gui.dialogs.unrenamed_galleries import UnrenamedGalleriesDialog

        dialog = UnrenamedGalleriesDialog(self)

        # Connect signal to update count when galleries are removed
        dialog.galleries_changed.connect(self._update_unnamed_count_background)

        dialog.exec()

    def start_single_item(self, path: str):
        """Start a single item"""
        if self.queue_manager.start_item(path):
            log(f"Started: {os.path.basename(path)}", level="info", category="queue")
            self._update_specific_gallery_display(path)
            # Update button counts after status change
            QTimer.singleShot(0, self._update_button_counts)
        else:
            log(f"Failed to start: {os.path.basename(path)}", level="warning", category="queue")
    
    def pause_single_item(self, path: str):
        """Pause a single item"""
        if self.queue_manager.pause_item(path):
            log(f"Paused: {os.path.basename(path)}", level="info", category="queue")
            self._update_specific_gallery_display(path)
            # Update button counts after status change
            QTimer.singleShot(0, self._update_button_counts)
        else:
            log(f"Failed to pause: {os.path.basename(path)}", level="warning", category="queue")
    
    def stop_single_item(self, path: str):
        """Mark current uploading item to finish in-flight transfers, then become incomplete."""
        if self.worker and self.worker.current_item and self.worker.current_item.path == path:
            self.worker.request_soft_stop_current()
            # Optimistically reflect intent in UI without persisting as failed later
            self.queue_manager.update_item_status(path, "incomplete")
            self._update_specific_gallery_display(path)
            # Update button counts after status change
            QTimer.singleShot(0, self._update_button_counts)
            log(f"Will stop after current transfers: {os.path.basename(path)}", level="debug", category="queue")
        else:
            # If not the actively uploading one, nothing to do
            log(f"Stop requested but item not currently uploading: {os.path.basename(path)}", level="debug", category="queue")
        # Controls will be updated by the targeted display update above
    
    def cancel_single_item(self, path: str):
        """Cancel a queued item and put it back to ready state"""
        if path in self.queue_manager.items:
            item = self.queue_manager.items[path]
            if item.status == "queued":
                self.queue_manager.update_item_status(path, "ready")
                log(f"Canceled queued item: {os.path.basename(path)}", level="debug", category="queue")
                
                # Force immediate action widget update
                if path in self.path_to_row:
                    row = self.path_to_row[path]
                    if 0 <= row < self.gallery_table.rowCount():
                        action_widget = self.gallery_table.cellWidget(row, GalleryTableWidget.COL_ACTION)
                        if isinstance(action_widget, ActionButtonWidget):
                            action_widget.update_buttons("ready")
                
                self._update_specific_gallery_display(path)
                # Force immediate button count and progress update
                self._update_counts_and_progress()
    
    def cancel_multiple_items(self, paths: list):
        """Cancel multiple queued items using batch processing to prevent GUI hang"""
        if not paths:
            return
        
        canceled_paths = []
        
        # Use batch mode to group all database operations
        with self.queue_manager.batch_updates():
            for path in paths:
                if path in self.queue_manager.items:
                    item = self.queue_manager.items[path]
                    if item.status == "queued":
                        self.queue_manager.update_item_status(path, "ready")
                        canceled_paths.append(path)
        
        # Log batch operation
        if canceled_paths:
            log(f"Canceled {len(canceled_paths)} queued item(s)", level="info", category="queue")
            
            # Update UI for all affected items
            for path in canceled_paths:
                # Update action widgets
                if path in self.path_to_row:
                    row = self.path_to_row[path]
                    if 0 <= row < self.gallery_table.rowCount():
                        action_widget = self.gallery_table.cellWidget(row, GalleryTableWidget.COL_ACTION)
                        if isinstance(action_widget, ActionButtonWidget):
                            action_widget.update_buttons("ready")
                
                # Update display for each item
                self._update_specific_gallery_display(path)
            
            # Single update for button counts and progress
            self._update_counts_and_progress()
    
    def start_upload_for_item(self, path: str):
        """Start upload for a specific item"""
        try:
            item = self.queue_manager.get_item(path)
            if not item:
                return False
            
            if item.status in ("ready", "paused", "incomplete", "upload_failed"):
                success = self.queue_manager.start_item(path)
                if success:
                    self._update_specific_gallery_display(path)  # Update only this item
                    return True
                else:
                    log(f"Failed to start upload for: {path}", level="warning", category="queue")
                    return False
            else:
                log(f"Cannot start upload for item with status: {item.status}", level="debug", category="queue")
                return False
        except Exception as e:
            log(f"Exception starting upload for {path}: {e}", level="error", category="queue")
            return False

    def _on_file_host_icon_clicked(self, gallery_path: str, host_name: str):
        """Handle file host icon click - show link if completed, queue upload if not"""
        from PyQt6.QtWidgets import QMessageBox
        from PyQt6.QtGui import QClipboard
        from PyQt6.QtWidgets import QApplication

        log(f"File host icon clicked: {host_name} for {os.path.basename(gallery_path)}", level="debug", category="file_hosts")

        # Check if upload exists and get status
        try:
            uploads = self.queue_manager.store.get_file_host_uploads(gallery_path)
            upload = next((u for u in uploads if u['host_name'] == host_name), None)

            if upload and upload['status'] == 'completed' and upload.get('download_url'):
                # Show download link
                download_link = upload['download_url']
                msg = QMessageBox(self)
                msg.setWindowTitle(f"{host_name} Download Link")
                msg.setText(f"Gallery uploaded successfully!\n\nDownload link:")
                msg.setInformativeText(download_link)
                msg.setStandardButtons(QMessageBox.StandardButton.Ok)

                # Add copy button
                copy_btn = msg.addButton("Copy Link", QMessageBox.ButtonRole.ActionRole)

                msg.exec()

                # If copy button was clicked, copy to clipboard
                if msg.clickedButton() == copy_btn:
                    clipboard = QApplication.clipboard()
                    if clipboard:
                        clipboard.setText(download_link)
                        log(f"Copied {host_name} link to clipboard", level="info", category="file_hosts")
            else:
                # Queue manual upload
                log(f"Queueing manual upload to {host_name} for {os.path.basename(gallery_path)}", level="info", category="file_hosts")

                # Get host config to confirm it exists
                from src.core.file_host_config import get_config_manager
                config_manager = get_config_manager()
                host_config = config_manager.get_host(host_name)

                if not host_config:
                    QMessageBox.warning(self, "Error", f"Host configuration not found: {host_name}")
                    return

                # Queue the upload (use host_name which is the host_id, not display name)
                upload_id = self.queue_manager.store.add_file_host_upload(
                    gallery_path=gallery_path,
                    host_name=host_name,  # host_id like 'filedot', not display name like 'FileDot.to'
                    status='pending'
                )

                log(f"Queued manual upload (upload_id={upload_id}) for {os.path.basename(gallery_path)} to {host_name}", level="info", category="file_hosts")

                # Refresh the row to show updated status
                self._update_specific_gallery_display(gallery_path)

                QMessageBox.information(
                    self,
                    "Upload Queued",
                    f"Gallery queued for upload to {host_name}.\n\nThe upload will begin shortly."
                )

        except Exception as e:
            log(f"Error handling file host icon click: {e}", level="error", category="file_hosts")
            QMessageBox.critical(self, "Error", f"Failed to process click: {str(e)}")

    def _on_file_hosts_manage_clicked(self, gallery_path: str):
        """Handle 'Manage' button click - show File Host Details Dialog"""
        log(f"File hosts manage clicked for {os.path.basename(gallery_path)}", level="debug", category="file_hosts")

        # TODO: Phase 6 - Implement File Host Details Dialog
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.information(
            self,
            "File Hosts",
            f"File Host Details Dialog will be implemented in Phase 6.\n\nGallery: {os.path.basename(gallery_path)}"
        )

    def _on_file_hosts_enabled_changed(self, _enabled_worker_ids: list):
        """Refresh all file host widgets when enabled hosts change."""
        # Skip during startup - icons are created via normal widget creation
        if not self._file_host_startup_complete:
            return

        # Get all gallery paths
        items = self.queue_manager.get_all_items()

        # Batch query for all file host uploads
        file_host_uploads_map = {}
        for item in items:
            uploads = self.queue_manager.store.get_file_host_uploads(item.path)
            file_host_uploads_map[item.path] = {u['host_name']: u for u in uploads}

        # Update all FileHostsStatusWidget instances
        for row in range(self.gallery_table.rowCount()):
            path = self.row_to_path.get(row)
            if path:
                status_widget = self.gallery_table.cellWidget(row, GalleryTableWidget.COL_HOSTS_STATUS)
                if status_widget and hasattr(status_widget, 'update_hosts'):
                    host_uploads = file_host_uploads_map.get(path, {})
                    status_widget.update_hosts(host_uploads)

    def handle_view_button(self, path: str):
        """Handle view button click - show BBCode for completed, start upload for ready, retry/file manager for failed"""
        item = self.queue_manager.get_item(path)
        #return
        if not item:
            return
        
        if item.status == "completed":
            self.view_bbcode_files(path)
        elif item.status == "ready":
            # For ready items, start the upload
            self.start_upload_for_item(path)
        elif item.status == "upload_failed":
            # For upload failures, retry the upload
            self.start_upload_for_item(path)
        elif item.status == "scan_failed" or item.status == "failed":
            # For scan failures or generic failures, open gallery file manager
            # The manage_gallery_files method is in GalleryTableWidget (self.gallery_table.table)
            if hasattr(self.gallery_table, 'table') and hasattr(self.gallery_table.table, 'manage_gallery_files'):
                self.gallery_table.table.manage_gallery_files(path)
                return
        else:
            # For other statuses (uploading, paused, etc.), open gallery file manager
            # The manage_gallery_files method is in GalleryTableWidget (self.gallery_table.table)
            if hasattr(self.gallery_table, 'table') and hasattr(self.gallery_table.table, 'manage_gallery_files'):
                self.gallery_table.table.manage_gallery_files(path)
                return
    
    
    def view_bbcode_files(self, path: str):
        """Open BBCode viewer/editor for completed item"""
        # Check if item is completed
        item = self.queue_manager.get_item(path)
        if not item or item.status != "completed":
            QMessageBox.warning(self, "Not Available", "BBCode files are only available for completed galleries.")
            log(f"BBCode files are only available for completed galleries.", level="debug", category="fileio")
            return
        
        # Open the viewer dialog
        dialog = BBCodeViewerDialog(path, self)
        dialog.exec()
    
    def copy_bbcode_to_clipboard(self, path: str):
        """Copy BBCode content to clipboard for the given item"""
        # Check if item is completed
        item = self.queue_manager.get_item(path)
        if not item or item.status != "completed":
            log(f"BBcode copy failed: {os.path.basename(path)} is not completed", level="debug", category="fileio")
            return
        
        folder_name = os.path.basename(path)
        
        # Import here to avoid circular imports  
        from imxup import get_central_storage_path
        central_path = get_central_storage_path()
        
        # Try central location first with standardized naming, fallback to legacy
        from imxup import build_gallery_filenames
        item = self.queue_manager.get_item(path)
        if item and item.gallery_id and (item.name or folder_name):
            log(f"BBcode copy: item.name='{item.name}', folder_name='{folder_name}', gallery_id='{item.gallery_id}'", level="debug", category="fileio")
            _, _, bbcode_filename = build_gallery_filenames(item.name or folder_name, item.gallery_id)
            central_bbcode = os.path.join(central_path, bbcode_filename)
            log(f"BBcode copy: central_bbcode path='{central_bbcode}' Exists={os.path.exists(central_bbcode)}", level="debug", category="fileio")
        else:
            central_bbcode = os.path.join(central_path, f"{folder_name}_bbcode.txt") # Fallback to old format for existing files
        
        content = ""
        source_file = None
        
        if os.path.exists(central_bbcode):
            with open(central_bbcode, 'r', encoding='utf-8') as f:
                content = f.read()
            source_file = central_bbcode
        else:
            # Try pattern-based lookup using gallery_id if exact filename fails
            if item and item.gallery_id:
                import glob
                log(f"BBcode copy: exact filename not found, trying pattern-based lookup for gallery_id '{item.gallery_id}'", level="debug", category="fileio")
                pattern = os.path.join(central_path, f"*_{item.gallery_id}_bbcode.txt")
                matches = glob.glob(pattern)
                log(f"BBcode copy, found {len(matches)} matches for '{pattern}': {matches}", level="debug", category="fileio")
                if matches:
                    central_bbcode = matches[0]  # Use first match
                    log(f"BBcode copy using pattern match: {central_bbcode}", level="debug", category="fileio")
                    if os.path.exists(central_bbcode):
                        with open(central_bbcode, 'r', encoding='utf-8') as f:
                            content = f.read()
                        source_file = central_bbcode

        if not content:
            import glob # Try folder location (existing format)
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
            if clipboard:
                clipboard.setText(content)
                log(f"Copied BBCode to clipboard from: {source_file}", level="info", category="fileio")
        else:
            log(f"No BBCode file found for: {folder_name}", level="info", category="fileio")
    
    def start_all_uploads(self):
        """Start all ready uploads in currently visible rows"""
        start_time = time.time()
        log(f"start_all_uploads() started at {start_time:.6f}", level="debug", category="timing")

        get_items_start = time.time()
        # Get items that are currently visible (not filtered out) - same logic as _update_button_counts()
        visible_items = []
        all_items = self.queue_manager.get_all_items()

        # Build path to row mapping for quick lookup
        path_to_row = {}
        for row in range(self.gallery_table.rowCount()):
            name_item = self.gallery_table.item(row, GalleryTableWidget.COL_NAME)
            if name_item:
                path = name_item.data(Qt.ItemDataRole.UserRole)
                if path:
                    path_to_row[path] = row

        # Only process items that are visible in the current filter
        for item in all_items:
            row = path_to_row.get(item.path)
            if row is not None and not self.gallery_table.isRowHidden(row):
                visible_items.append(item)

        items = visible_items
        get_items_duration = time.time() - get_items_start
        log(f"Getting visible items took {get_items_duration:.6f}s, found {len(items)} visible items", level="debug", category="timing")
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
                        log(f"start_item({item.path}) took {start_item_duration:.6f}s", category="timing", level="debug")
                        started_count += 1
                        started_paths.append(item.path)
                    else:
                        start_item_duration = time.time() - start_item_begin
                        log(f"start_item({item.path}) failed in {start_item_duration:.6f}s", category="timing", level="debug")
        
        item_processing_duration = time.time() - item_processing_start
        log(f"Processing all items took {item_processing_duration:.6f}s", category="timing", level="info")
        
        ui_update_start = time.time()
        if started_count > 0:
            log(f"Started {started_count} uploads", level="info")
            # Update all affected items individually instead of rebuilding table
            for path in started_paths:
                self._update_specific_gallery_display(path)
            # Update button counts and progress after state changes
            QTimer.singleShot(0, self._update_counts_and_progress)
        else:
            log(f"No items to start", category="queue", level="info")
        
        ui_update_duration = time.time() - ui_update_start
        log(f"UI updates took {ui_update_duration:.6f}s", category="timing", level="debug")
        
        total_duration = time.time() - start_time
        log(f"start_all_uploads() completed in {total_duration:.6f}s total", category="timing", level="debug")
    
    def pause_all_uploads(self):
        """Reset all queued items back to ready (acts like Cancel for queued) - tab-specific"""
        items = self._get_current_tab_items()
        reset_count = 0
        reset_paths = []
        with QMutexLocker(self.queue_manager.mutex):
            for item in items:
                if item.status == "queued" and item.path in self.queue_manager.items:
                    self.queue_manager.items[item.path].status = "ready"
                    reset_count += 1
                    reset_paths.append(item.path)
        
        if reset_count > 0:
            log(f"Reset {reset_count} queued item(s) to Ready", level="info", category="queue")
            # Update all affected items individually instead of rebuilding table
            for path in reset_paths:
                self._update_specific_gallery_display(path)
            # Update button counts and progress after state changes
            QTimer.singleShot(0, self._update_counts_and_progress)
        else:
            log(f"No queued items to reset", level="info", category="queue")
    
    def clear_completed(self):
        """Clear completed/failed uploads - non-blocking with confirmation"""
        log(f"clear_completed() called", category="queue", level="debug")

        # Get items to clear
        items_snapshot = self._get_current_tab_items()
        log(f"Got {len(items_snapshot)} items from current tab", category="queue", level="debug")

        comp_paths = [it.path for it in items_snapshot if it.status in ("completed", "failed")]
        log(f"Found {len(comp_paths)} completed/failed galleries", category="queue", level="debug")

        if not comp_paths:
            log(f"No completed uploads to clear", category="queue", level="info")
            return

        # Use shared confirmation method
        log(f"Requesting user confirmation", category="queue", level="debug")
        if not self._confirm_removal(comp_paths, operation_type="clear"):
            log(f"User cancelled clear operation", category="queue", level="info")
            return

        log(f"User confirmed - proceeding with clear", category="queue", level="debug")

        # User confirmed - proceed with removal
        count_completed = sum(1 for it in items_snapshot if it.status == "completed")
        count_failed = sum(1 for it in items_snapshot if it.status == "failed")
        log(f"Clearing (user confirmed): completed={count_completed}, failed={count_failed}", category="queue", level="debug")

        # Remove from queue manager (same pattern as delete_selected_items)
        removed_paths = []
        for path in comp_paths:
            # Remove from memory
            with QMutexLocker(self.queue_manager.mutex):
                if path in self.queue_manager.items:
                    del self.queue_manager.items[path]
                    removed_paths.append(path)
                    log(f"Removed item (user confirmed): {os.path.basename(path)}", category="queue", level="debug")

        if not removed_paths:
            log(f"No items actually removed", level="info", category="queue")
            return

        log(f"Removed {len(removed_paths)} items from queue manager", category="queue", level="info")

        # Completion callback
        def on_clear_complete():
            # Renumber remaining items
            self.queue_manager._renumber_items()

            # Delete from database
            try:
                self.queue_manager.store._executor.submit(self.queue_manager.store.delete_by_paths, removed_paths)
            except Exception as e:
                log(f"Exception while deleting from database: {e}", level="error", category="db")

            # Update button counts and progress
            QTimer.singleShot(0, self._update_counts_and_progress)

            # Update tab tooltips
            if hasattr(self.gallery_table, '_update_tab_tooltips'):
                self.gallery_table._update_tab_tooltips()

            # Save queue
            QTimer.singleShot(100, self.queue_manager.save_persistent_queue)
            log(f"Cleared {len(removed_paths)} completed/failed uploads", category="queue", level="info")

        # Use non-blocking batch removal for table updates
        self._remove_galleries_batch(removed_paths, callback=on_clear_complete)
    
    def delete_selected_items(self):
        """Delete selected items from the queue - non-blocking"""
        log(f"Delete method called", level="debug", category="queue")

        # Get the actual table (handle tabbed interface)
        table = self.gallery_table
        if hasattr(self.gallery_table, 'table'):
            table = self.gallery_table.table

        selected_rows = set()
        for item in table.selectedItems():
            selected_rows.add(item.row())

        if not selected_rows:
            log(f"No rows selected", level="debug", category="queue")
            return

        # Get paths directly from the table cells to handle sorting correctly
        selected_paths = []
        selected_names = []

        for row in selected_rows:
            name_item = table.item(row, GalleryTableWidget.COL_NAME)
            if name_item:
                path = name_item.data(Qt.ItemDataRole.UserRole)
                if path:
                    selected_paths.append(path)
                    selected_names.append(name_item.text())
                else:
                    log(f"No path data for row {row}", level="debug", category="queue")
            else:
                log(f"No name item for row {row}", level="debug", category="queue")

        if not selected_paths:
            log(f"No valid paths found", level="debug", category="queue")
            return

        # Use shared confirmation method
        if not self._confirm_removal(selected_paths, selected_names, operation_type="delete"):
            log(f"User cancelled delete", level="debug", category="ui")
            return
        
        # Remove from queue manager first (filter out uploading items)
        removed_paths = []
        log(f"Attempting to delete {len(selected_paths)} paths", level="debug", category="queue")

        for path in selected_paths:
            # Check if item is currently uploading
            item = self.queue_manager.get_item(path)
            if item:
                if item.status == "uploading":
                    log(f"Skipping uploading item: {path}")
                    continue
            else:
                log(f"Item not found in queue manager: {path}", level="debug", category="queue")
                continue

            # Remove from memory
            with QMutexLocker(self.queue_manager.mutex):
                if path in self.queue_manager.items:
                    del self.queue_manager.items[path]
                    removed_paths.append(path)
                    log(f"Deleted: {os.path.basename(path)}", category="queue", level="debug")

        if not removed_paths:
            log(f"No items removed (all were uploading or not found)", level="debug", category="queue")
            return

        # Completion callback to run after batch removal finishes
        def on_deletion_complete():
            # Renumber remaining items
            self.queue_manager._renumber_items()

            # Delete from database to prevent reloading
            try:
                self.queue_manager.store._executor.submit(self.queue_manager.store.delete_by_paths, removed_paths)
            except Exception as e:
                log(f"Exception deleting from database: {e}", level="error", category="database")

            # Update button counts and progress
            QTimer.singleShot(0, self._update_counts_and_progress)

            # Update tab tooltips to reflect new counts
            if hasattr(self.gallery_table, '_update_tab_tooltips'):
                self.gallery_table._update_tab_tooltips()

            # Defer database save to prevent GUI freeze
            QTimer.singleShot(100, self.queue_manager.save_persistent_queue)
            log(f"Deleted {len(removed_paths)} items from queue", level="info", category="queue")

        # Use non-blocking batch removal for table updates
        self._remove_galleries_batch(removed_paths, callback=on_deletion_complete)
    

    
    def restore_settings(self):
        """Restore window settings"""
        geometry = self.settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        
        # Restore splitter states for resizable dividers
        if hasattr(self, 'top_splitter'):
            splitter_state = self.settings.value("splitter/state")
            if splitter_state:
                self.top_splitter.restoreState(splitter_state)

        # Restore vertical splitter state (Settings/Log divider)
        if hasattr(self, 'right_vertical_splitter'):
            vertical_splitter_state = self.settings.value("splitter/vertical_state")
            if vertical_splitter_state:
                self.right_vertical_splitter.restoreState(vertical_splitter_state)

        # Restore right panel collapsed state
        is_collapsed = self.settings.value("right_panel/collapsed", False, type=bool)
        if is_collapsed and hasattr(self, 'action_toggle_right_panel'):
            # Collapse after a short delay to allow UI to initialize
            QTimer.singleShot(100, lambda: self.toggle_right_panel())
        elif hasattr(self, 'action_toggle_right_panel'):
            self.action_toggle_right_panel.setChecked(True)
        
        # Load settings from .ini file
        defaults = load_user_defaults()

        # Restore table columns (widths and visibility)
        self.restore_table_settings()
        # Apply saved theme
        try:
            theme = str(self.settings.value('ui/theme', 'dark'))
            self.apply_theme(theme)
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise
        
        # Apply saved font size
        try:
            font_size = int(self.settings.value('ui/font_size', 9))
            self.apply_font_size(font_size)
        except Exception as e:
            log(f"Error loading font size: {e}", category="ui", level="debug")
            pass
    
    def save_settings(self):
        """Save window settings"""
        self.settings.setValue("geometry", self.saveGeometry())

        # Save splitter states for resizable dividers
        if hasattr(self, 'top_splitter'):
            self.settings.setValue("splitter/state", self.top_splitter.saveState())

        # Save vertical splitter state (Settings/Log divider)
        if hasattr(self, 'right_vertical_splitter'):
            self.settings.setValue("splitter/vertical_state", self.right_vertical_splitter.saveState())

        # Save right panel collapsed state
        if hasattr(self, 'action_toggle_right_panel'):
            is_collapsed = not self.action_toggle_right_panel.isChecked()
            self.settings.setValue("right_panel/collapsed", is_collapsed)

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
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise

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
                except Exception as e:
                    log(f"Exception in main_window: {e}", level="error", category="ui")
                    raise
            if visible_raw:
                try:
                    visible = json.loads(visible_raw)
                    for i in range(min(column_count, len(visible))):
                        self.gallery_table.setColumnHidden(i, not bool(visible[i]))
                except Exception as e:
                    log(f"Exception in main_window: {e}", level="error", category="ui")
                    raise
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
                except Exception as e:
                    log(f"Exception in main_window: {e}", level="error", category="ui")
                    raise
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise

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
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise

    def _on_header_section_moved(self, logicalIndex, oldVisualIndex, newVisualIndex):
        """Persist order when user drags columns."""
        try:
            self.save_table_settings()
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise

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
        """Set column visibility and populate data if column is being shown"""
        was_hidden = self.gallery_table.isColumnHidden(column_index)
        self.gallery_table.setColumnHidden(column_index, not visible)

        # If column was hidden and is now being shown, populate data for all visible rows
        if was_hidden and visible:
            self._populate_column_data(column_index)

        self.save_table_settings()

    def _populate_column_data(self, column_index: int):
        """Populate data for a specific column across all rows (used when showing hidden columns)"""
        from src.gui.widgets.gallery_table import GalleryTableWidget

        # Get theme mode for styling
        theme_mode = self._current_theme_mode

        # Get the actual table object
        actual_table = getattr(self.gallery_table, 'table', self.gallery_table)

        # Populate all rows in the table
        for row in range(self.gallery_table.rowCount()):
            # Get the gallery path from row mapping
            path = self.row_to_path.get(row)
            if not path:
                continue

            # Get the queue item for this row
            item = self.queue_manager.get_item(path)
            if not item:
                continue

            # Populate based on column type
            if column_index == GalleryTableWidget.COL_STATUS_TEXT:
                # Status text column (5)
                self._set_status_text_cell(row, item.status)

            elif column_index == GalleryTableWidget.COL_TRANSFER:
                # Transfer speed column (10)
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
                xfer_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if item.status == "uploading" and transfer_text:
                    xfer_item.setForeground(QColor(173, 216, 255, 255) if theme_mode == 'dark' else QColor(20, 90, 150, 255))
                elif item.status in ("completed", "failed") and transfer_text:
                    xfer_item.setForeground(QColor(255, 255, 255, 230) if theme_mode == 'dark' else QColor(0, 0, 0, 190))
                self.gallery_table.setItem(row, GalleryTableWidget.COL_TRANSFER, xfer_item)

            elif column_index == GalleryTableWidget.COL_GALLERY_ID:
                # Gallery ID column (13) - read-only
                signals_blocked = actual_table.signalsBlocked()
                actual_table.blockSignals(True)
                try:
                    gallery_id_text = item.gallery_id or ""
                    gallery_id_item = QTableWidgetItem(gallery_id_text)
                    gallery_id_item.setFlags(gallery_id_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    gallery_id_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                    actual_table.setItem(row, GalleryTableWidget.COL_GALLERY_ID, gallery_id_item)
                finally:
                    actual_table.blockSignals(signals_blocked)

            elif GalleryTableWidget.COL_CUSTOM1 <= column_index <= GalleryTableWidget.COL_CUSTOM4:
                # Custom columns (14-17) - editable
                field_map = {
                    GalleryTableWidget.COL_CUSTOM1: 'custom1',
                    GalleryTableWidget.COL_CUSTOM2: 'custom2',
                    GalleryTableWidget.COL_CUSTOM3: 'custom3',
                    GalleryTableWidget.COL_CUSTOM4: 'custom4'
                }
                field_name = field_map.get(column_index)
                if field_name:
                    signals_blocked = actual_table.signalsBlocked()
                    actual_table.blockSignals(True)
                    try:
                        value = getattr(item, field_name, '') or ''
                        custom_item = QTableWidgetItem(str(value))
                        custom_item.setFlags(custom_item.flags() | Qt.ItemFlag.ItemIsEditable)
                        custom_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                        actual_table.setItem(row, column_index, custom_item)
                    finally:
                        actual_table.blockSignals(signals_blocked)

            elif GalleryTableWidget.COL_EXT1 <= column_index <= GalleryTableWidget.COL_EXT4:
                # Ext columns (18-21) - editable
                field_map = {
                    GalleryTableWidget.COL_EXT1: 'ext1',
                    GalleryTableWidget.COL_EXT2: 'ext2',
                    GalleryTableWidget.COL_EXT3: 'ext3',
                    GalleryTableWidget.COL_EXT4: 'ext4'
                }
                field_name = field_map.get(column_index)
                if field_name:
                    signals_blocked = actual_table.signalsBlocked()
                    actual_table.blockSignals(True)
                    try:
                        value = getattr(item, field_name, '') or ''
                        ext_item = QTableWidgetItem(str(value))
                        ext_item.setFlags(ext_item.flags() | Qt.ItemFlag.ItemIsEditable)
                        ext_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                        actual_table.setItem(row, column_index, ext_item)
                    finally:
                        actual_table.blockSignals(signals_blocked)

    def on_setting_changed(self):
        """Handle when any quick setting is changed - auto-save immediately"""
        self.save_upload_settings()
    
    def save_upload_settings(self):
        """Save upload settings to .ini file"""
        try:
            import configparser
            import os
            
            # Get current values
            thumbnail_size = self.thumbnail_size_combo.currentIndex() + 1
            thumbnail_format = self.thumbnail_format_combo.currentIndex() + 1
            # Max retries and batch size are now only in comprehensive settings
            from imxup import load_user_defaults
            defaults = load_user_defaults()
            max_retries = defaults.get('max_retries', 3)
            parallel_batch_size = defaults.get('parallel_batch_size', 4)
            template_name = self.template_combo.currentText()
            auto_start_upload = self.auto_start_upload_check.isChecked()
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
            config['DEFAULTS']['auto_start_upload'] = str(auto_start_upload)
            config['DEFAULTS']['store_in_uploaded'] = str(store_in_uploaded)
            config['DEFAULTS']['store_in_central'] = str(store_in_central)
            # Persist central store path (empty string implies default)
            config['DEFAULTS']['central_store_path'] = central_store_path
            
            # Save to file
            with open(config_file, 'w') as f:
                config.write(f)

            # Quick settings auto-saved (no button to update)
            log(f"Quick settings saved successfully",level="info", category="ui")
            
        except Exception as e:
            log(f"Exception saving settings: {str(e)}")
            QMessageBox.warning(self, "Error", f"Failed to save settings: {str(e)}")
    
    def dragEnterEvent(self, event):
        """Handle drag enter - WSL2 PERMISSIVE VERSION

        Accept all drags that have URLs or text (which may contain Windows paths).
        Actual validation happens in dropEvent after WSL path conversion.
        """
        mime_data = event.mimeData()

        # Log mime data for debugging
        log(f"dragEnterEvent: hasUrls={mime_data.hasUrls()}, hasText={mime_data.hasText()}, formats={mime_data.formats()}", level="trace", category="drag_drop")

        # Accept if there are URLs
        if mime_data.hasUrls():
            log(f"dragEnterEvent: Accepting drag with {len(mime_data.urls())} URLs", level="trace", category="drag_drop")
            event.acceptProposedAction()
            return

        # Also accept if there's text (WSL2 might pass paths as text)
        if mime_data.hasText():
            text = mime_data.text()
            log(f"dragEnterEvent: Accepting text-based drag", level="trace", category="drag_drop")
            event.acceptProposedAction()
            return

        # Reject only if no URLs or text
        log("dragEnterEvent: Rejecting drag - no valid data", level="trace", category="drag_drop")
        event.ignore()
    
    def dragMoveEvent(self, event):
        """Handle drag move - WSL2 PERMISSIVE VERSION

        Accept all drags that have URLs or text.
        Actual validation happens in dropEvent after WSL path conversion.
        """
        mime_data = event.mimeData()

        # Accept if there are URLs or text (WSL2 might pass paths as text)
        if mime_data.hasUrls() or mime_data.hasText():
            event.acceptProposedAction()
        else:
            event.ignore()
    
    def dragLeaveEvent(self, event):
        """Handle drag leave"""
        
    def dropEvent(self, event):
        """Handle drop with WSL2 path conversion support"""
        mime_data = event.mimeData()

        log(f"dropEvent: Received drop with hasUrls={mime_data.hasUrls()}, hasText={mime_data.hasText()}", level="trace", category="drag_drop")

        if mime_data.hasUrls():
            urls = mime_data.urls()
            paths = []

            log(f"dropEvent: Processing {len(urls)} URL(s)", level="trace", category="drag_drop")

            for url in urls:
                # Get the original path from the URL
                original_path = url.toLocalFile()

                log(f"dropEvent: Processing URL: {original_path}", level="trace", category="drag_drop")

                # Convert Windows paths to WSL2 format if running on WSL2
                converted_path = str(convert_to_wsl_path(original_path))

                # Log WSL conversion for debugging
                if is_wsl2() and original_path != converted_path:
                    log(f"dropEvent: WSL2 conversion: {original_path} → {converted_path}", level="trace", category="drag_drop")

                # Validate the converted path
                if os.path.isdir(converted_path) or is_archive_file(converted_path):
                    paths.append(converted_path)
                    log(f"dropEvent: Path validated: {converted_path}", level="trace", category="drag_drop")
                else:
                    # Log validation failures for debugging
                    log(f"dropEvent: Path validation failed: {converted_path}", level="trace", category="drag_drop")

            if paths:
                log(f"dropEvent: Adding {len(paths)} valid path(s) to queue", level="trace", category="drag_drop")
                self.add_folders_or_archives(paths)
                event.acceptProposedAction()
            else:
                log("dropEvent: No valid paths found", level="trace", category="drag_drop")
                event.ignore()
        else:
            log(f"dropEvent: Processing text-based drop: {mime_data.text()[:100]}...", level="trace", category="drag_drop")
            event.ignore()

    def closeEvent(self, event):
        """Handle window close"""
        # Check if there are active uploads
        try:
            all_items = self.queue_manager.get_all_items()
            uploading_items = [item for item in all_items if item.status == "uploading"]

            if uploading_items:
                from PyQt6.QtWidgets import QMessageBox
                reply = QMessageBox.question(
                    self,
                    "Exit Confirmation",
                    f"{len(uploading_items)} gallery(s) currently uploading. Exit anyway?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No
                )

                if reply == QMessageBox.StandardButton.No:
                    event.ignore()
                    return
        except Exception as e:
            log(f"ERROR: Exception in main_window: {e}", level="error", category="ui")
            raise

        self.save_settings()

        # shutdown() handles saving the queue state
        self.queue_manager.shutdown()

        # Stop batchers and cleanup timers
        if hasattr(self, '_progress_batcher'):
            self._progress_batcher.cleanup()
        if hasattr(self, '_table_update_queue'):
            self._table_update_queue.cleanup()
        if hasattr(self, '_background_update_timer') and self._background_update_timer.isActive():
            self._background_update_timer.stop()
        if hasattr(self, 'update_timer') and self.update_timer.isActive():
            self.update_timer.stop()
        if hasattr(self, 'bandwidth_status_timer') and self.bandwidth_status_timer.isActive():
            self.bandwidth_status_timer.stop()

        # Stop worker monitoring
        if hasattr(self, 'worker_status_widget'):
            self.worker_status_widget.stop_monitoring()

        # Always stop workers and server on close
        if self.worker:
            self.worker.stop()

        # Stop completion worker
        if hasattr(self, 'completion_worker'):
            self.completion_worker.stop()
            self.completion_worker.wait(3000)  # Wait up to 3 seconds for shutdown

        # Stop file host worker manager
        if hasattr(self, 'file_host_manager') and self.file_host_manager:
            self.file_host_manager.shutdown_all()

        self.server.stop()

        # Accept the close event to ensure app exits
        event.accept()

    def on_gallery_cell_clicked(self, row, column):
        """Handle clicks on gallery table cells for template editing and custom/ext column editing."""

        # Handle custom columns (14-17) and ext columns (18-21) with single-click editing
        if (GalleryTableWidget.COL_CUSTOM1 <= column <= GalleryTableWidget.COL_CUSTOM4) or \
           (GalleryTableWidget.COL_EXT1 <= column <= GalleryTableWidget.COL_EXT4):
            # Get the correct table and trigger edit mode
            table = getattr(self.gallery_table, 'table', self.gallery_table)
            if table:
                item = table.item(row, column)
                if item:
                    table.editItem(item)
            return

        # Only handle clicks on template column for template editing
        if column != GalleryTableWidget.COL_TEMPLATE:
            return

        # Get the table widget
        if hasattr(self.gallery_table, 'table'):
            table = self.gallery_table.table
        else:
            table = self.gallery_table

        # Get gallery path the same way as context menu - from name column UserRole data
        name_item = table.item(row, GalleryTableWidget.COL_NAME)
        if not name_item:
            log(f"DEBUG: Mouseclick -> No item found at row {row}, column {GalleryTableWidget.COL_NAME}", category="ui", level="debug")
            return
        
        gallery_path = name_item.data(Qt.ItemDataRole.UserRole)
        if not gallery_path:
            log(f"DEBUG: No UserRole data in gallery name column", category="ui", level="debug")
            return

        # Get current template
        template_item = table.item(row, GalleryTableWidget.COL_TEMPLATE)
        current_template = template_item.text() if template_item else "default"
        
        # Show simple dialog instead of inline combo
        from PyQt6.QtWidgets import QInputDialog
        from imxup import load_templates
        
        try:
            templates = load_templates()
            template_list = list(templates.keys())
            
            new_template, ok = QInputDialog.getItem(
                self, 
                "Select Template", 
                "Choose template for gallery:", 
                template_list, 
                template_list.index(current_template) if current_template in template_list else 0,
                False
            )
            
            if ok and new_template != current_template:
                self.update_gallery_template(row, gallery_path, new_template, None)
                
        except Exception as e:
            log(f"ERROR: Exception loading templates: {e}", category="ui", level="error")

    def update_gallery_template(self, row, gallery_path, new_template, combo_widget):
        """Update template for a gallery and regenerate BBCode if needed."""
        log(f"DEBUG: update_gallery_template called - row={row}, path={gallery_path}, new_template={new_template}", category="db", level="debug")
        try:
            
            # Get table reference
            if hasattr(self.gallery_table, 'table'):
                table = self.gallery_table.table
            else:
                table = self.gallery_table
            
            log(f"DEBUG: About to update database with path: '{gallery_path}' and template: '{new_template}'", level="debug", category="db")
            
            # Check what's actually in the database
            try:
                all_db_items = self.queue_manager.get_all_items()
                db_paths = [item.path for item in all_db_items[:5]]  # First 5 paths
                log(f"DEBUG: Sample database paths: {db_paths}", level="debug", category="db")
                log(f"DEBUG: Does our path exist in DB? {gallery_path in [item.path for item in all_db_items]}", level="debug", category="db")
            except Exception as e:
                log(f"ERROR: Exception checking database: {e}", category="db", level="error")
            
            # Update database
            success = self.queue_manager.store.update_item_template(gallery_path, new_template)
            log(f"DEBUG: Database update success: {success}", category="db", level="debug")

            # Update in-memory item
            with QMutexLocker(self.queue_manager.mutex):
                if gallery_path in self.queue_manager.items:
                    self.queue_manager.items[gallery_path].template_name = new_template
                    self.queue_manager._inc_version()

            # Update the table cell display
            template_item = table.item(row, GalleryTableWidget.COL_TEMPLATE)
            if template_item:
                template_item.setText(new_template)
            else:
                log(f"No template item found at row {row}, column {GalleryTableWidget.COL_TEMPLATE}", category="ui", level="debug")
            
            log(f"Template updated", category="ui", level="info")
            
            # Get the actual gallery item to check real status
            gallery_item = self.queue_manager.get_item(gallery_path)
            if not gallery_item:
                log(f"DEBUG: Could not get gallery item from queue manager", category="ui", level="debug")
                status = ""
            else:
                status = gallery_item.status
            
            log(f"DEBUG: Gallery status from queue manager: '{status}'", category="ui", level="debug")
            
            if status == "completed":
                log(f"DEBUG: Gallery is completed, attempting BBCode regeneration", level="debug", category="fileio")
                # Try to regenerate BBCode from JSON artifact
                try:
                    self.regenerate_gallery_bbcode(gallery_path, new_template)
                    log(f"Template changed to '{new_template}' and BBCode regenerated for {os.path.basename(gallery_path)}", level="info", category="fileio")
                    #print(f"DEBUG: BBCode regeneration successful")
                except Exception as e:
                    log(f"WARNING: Template changed to '{new_template}' for {os.path.basename(gallery_path)}, but BBCode regeneration failed: {e}", category="fileio", level="warning")
            else:
                log(f"Gallery not completed, skipping BBCode regeneration", category="fileio", level="info")
                #log(f"Template changed to '{new_template}' for {os.path.basename(gallery_path)}")
            
            # Remove combo box and update display
            table.removeCellWidget(row, GalleryTableWidget.COL_TEMPLATE)
            template_item = table.item(row, GalleryTableWidget.COL_TEMPLATE)
            if template_item:
                template_item.setText(new_template)
            
            # Force table refresh to ensure data is updated
            # Note: refresh_gallery_display doesn't exist, removing this call
            
        except Exception as e:
            log(f"ERROR: Exception updating gallery template: {e}", category="fileio", level="error")
            # Remove combo box on error
            try:
                table = self.gallery_table.table
                table.removeCellWidget(row, GalleryTableWidget.COL_TEMPLATE)
            except:
                pass

    def regenerate_bbcode_for_gallery(self, gallery_path: str, force: bool = False):
        """Regenerate BBCode for a gallery using its current template"""
        # Check if auto-regeneration is enabled (unless forced)
        if not force and not self._should_auto_regenerate_bbcode(gallery_path):
            return

        # Get the current template for this gallery
        item = self.queue_manager.get_item(gallery_path)
        if item and item.template_name:
            template_name = item.template_name
        else:
            # Fall back to default template
            template_name = "default"

        # Call the existing regeneration method
        self.regenerate_gallery_bbcode(gallery_path, template_name)

    def regenerate_bbcode_for_gallery_multi(self, paths):
        """Regenerate BBCode for multiple completed galleries using their current templates"""
        log(f"DEBUG: regenerate_bbcode_for_gallery_multi called with {len(paths)} paths", category="fileio", level="debug")

        # Find the main GUI window
        widget = self
        while widget and not hasattr(widget, 'queue_manager'):
            widget = widget.parent()
        if not widget:
            log(f"DEBUG: No widget with queue_manager found", category="fileio", level="debug")
            return

        success_count = 0
        error_count = 0

        for path in paths:
            try:
                log(f"DEBUG: Processing path: {path}", level="debug", category="fileio")
                item = widget.queue_manager.get_item(path)
                if not item:
                    log(f"DEBUG: No item found for path: {path}", category="fileio", level="debug")
                    continue

                if item.status != "completed":
                    log(f"DEBUG: Skipping non-completed item: {item.status}", category="fileio", level="debug")
                    continue

                # Get template for this gallery (same logic as single version)
                if item and item.template_name:
                    template_name = item.template_name
                else:
                    template_name = "default"

                # Call the existing regeneration method (force=True since this is explicit user action)
                widget.regenerate_gallery_bbcode(path, template_name)
                success_count += 1
                log(f"DEBUG: Successfully regenerated BBCode for {path}", category="fileio", level="debug")

            except Exception as e:
                error_count += 1
                log(f"WARNING: Error regenerating BBCode for {path}: {e}", category="fileio", level="warning")

        # Show summary message
        if success_count > 0 or error_count > 0:
            if error_count == 0:
                self.show_message("Success", f"Regenerated BBCode for {success_count} galleries.")
            else:
                self.show_message("Partial Success", f"Regenerated BBCode for {success_count} galleries. {error_count} failed.")
        else:
            self.show_message("No Action", "No completed galleries found to regenerate.")

    def regenerate_gallery_bbcode(self, gallery_path, new_template):
        """Regenerate BBCode for an uploaded gallery using its JSON artifact."""
        from imxup import get_central_storage_path, build_gallery_filenames, save_gallery_artifacts
        import json
        import glob
        import os
        
        # Get gallery info
        item = self.queue_manager.get_item(gallery_path)
        if not item:
            raise Exception("Gallery not found in database")
        
        # Find JSON artifact file by gallery ID
        from src.utils.artifact_finder import find_gallery_json_by_id

        gallery_id = getattr(item, 'gallery_id', None)
        if not gallery_id:
            raise Exception("Gallery ID not found in database")

        json_path = find_gallery_json_by_id(gallery_id, gallery_path)
        if not json_path:
            raise Exception(f"No JSON artifact file found for gallery ID {gallery_id}")
        
        # Load JSON data
        with open(json_path, 'r', encoding='utf-8') as f:
            json_data = json.load(f)
        
        # Reuse existing save_gallery_artifacts function with the new template
        # It will handle BBCode generation, file saving, and JSON updates
        # Use current gallery name from database (which could be renamed), not from old JSON
        current_gallery_name = item.name if item.name else json_data['meta']['gallery_name']
        #print(f"DEBUG regenerate_gallery_bbcode: Using current_gallery_name='{current_gallery_name}' from database, old JSON had='{json_data['meta']['gallery_name']}'")
        results = {
            'gallery_id': json_data['meta']['gallery_id'],
            'gallery_name': current_gallery_name,
            'images': json_data.get('images', []),
            'total_size': json_data['stats']['total_size'],
            'successful_count': json_data['stats']['successful_count'],
            'failed_count': json_data['stats'].get('failed_count', 0),
            'failed_details': [(img.get('filename', ''), 'Previous failure') for img in json_data.get('failures', [])],
            'avg_width': json_data['stats']['avg_width'],
            'avg_height': json_data['stats']['avg_height'],
            'max_width': json_data['stats']['max_width'],
            'max_height': json_data['stats']['max_height'],
            'min_width': json_data['stats']['min_width'],
            'min_height': json_data['stats']['min_height']
        }
        
        # Prepare custom fields dict from the item
        custom_fields = {
            'custom1': getattr(item, 'custom1', ''),
            'custom2': getattr(item, 'custom2', ''),
            'custom3': getattr(item, 'custom3', ''),
            'custom4': getattr(item, 'custom4', ''),
            'ext1': getattr(item, 'ext1', ''),
            'ext2': getattr(item, 'ext2', ''),
            'ext3': getattr(item, 'ext3', ''),
            'ext4': getattr(item, 'ext4', '')
        }
        
        # Use existing save_gallery_artifacts function to regenerate with new template
        save_gallery_artifacts(
            folder_path=gallery_path,
            results=results,
            template_name=new_template,
            custom_fields=custom_fields
        )
    
    def _on_table_item_changed(self, item):
        """Handle table item changes to persist custom columns"""
        try:
            # Prevent recursion - use a simple flag
            if hasattr(self, '_in_item_changed_handler') and self._in_item_changed_handler:
                return

            self._in_item_changed_handler = True
            try:
                # Handle custom columns (14-17) and ext columns (18-21)
                column = item.column()
                is_custom = GalleryTableWidget.COL_CUSTOM1 <= column <= GalleryTableWidget.COL_CUSTOM4
                is_ext = GalleryTableWidget.COL_EXT1 <= column <= GalleryTableWidget.COL_EXT4

                if not (is_custom or is_ext):
                    return

                # Get the actual table that contains this item (important for tabbed galleries!)
                table = item.tableWidget()
                if not table:
                    log(f"WARNING: Item has no parent table widget, skipping", level="debug", category="ui")
                    return

                # Skip if table signals are blocked (indicates programmatic update)
                if table.signalsBlocked():
                    return

                # Get the gallery path from the name column (UserRole data)
                row = item.row()
                name_item = table.item(row, GalleryTableWidget.COL_NAME)
                if not name_item:
                    return

                path = name_item.data(Qt.ItemDataRole.UserRole)
                if not path:
                    return

                # Map column to field name
                field_names = {
                    GalleryTableWidget.COL_CUSTOM1: 'custom1',
                    GalleryTableWidget.COL_CUSTOM2: 'custom2',
                    GalleryTableWidget.COL_CUSTOM3: 'custom3',
                    GalleryTableWidget.COL_CUSTOM4: 'custom4',
                    GalleryTableWidget.COL_EXT1: 'ext1',
                    GalleryTableWidget.COL_EXT2: 'ext2',
                    GalleryTableWidget.COL_EXT3: 'ext3',
                    GalleryTableWidget.COL_EXT4: 'ext4',
                }
                field_name = field_names.get(column)
                if not field_name:
                    return

                # Get the new value and update the database
                new_value = item.text() or ''
                field_type = "ext" if is_ext else "custom"
                log(f"DEBUG: {field_type.capitalize()} field changed: {field_name}={new_value} for {os.path.basename(path)}", level="debug", category="ui")

                if self.queue_manager:
                    # Block signals while updating to prevent cascade
                    signals_blocked = table.signalsBlocked()
                    table.blockSignals(True)
                    try:
                        # Update in-memory item
                        with QMutexLocker(self.queue_manager.mutex):
                            if path in self.queue_manager.items:
                                item_obj = self.queue_manager.items[path]
                                setattr(item_obj, field_name, new_value)

                        # Save to database (outside mutex to avoid deadlock)
                        self.queue_manager.store.update_item_custom_field(path, field_name, new_value)

                        # Increment version
                        with QMutexLocker(self.queue_manager.mutex):
                            self.queue_manager._inc_version()
                    finally:
                        table.blockSignals(signals_blocked)
            finally:
                self._in_item_changed_handler = False

        except Exception as e:
            log(f"ERROR: Exception handling table item change: {e}", category="ui", level="error")
            import traceback
            traceback.print_exc()

    def _should_auto_regenerate_bbcode(self, path: str) -> bool:
        """Check if BBCode should be auto-regenerated for a gallery"""
        # Check if auto-regeneration is enabled
        from imxup import load_user_defaults
        defaults = load_user_defaults()
        if not defaults.get('auto_regenerate_bbcode', True):
            return False

        # Check if gallery is completed
        item = self.queue_manager.get_item(path)
        if not item or item.status != "completed":
            return False

        return True

    def _auto_regenerate_for_gallery_id(self, gallery_id: int):
        """Auto-regenerate artifacts for gallery by ID if setting enabled"""
        path = self._gallery_id_to_path.get(gallery_id)
        if path and self._should_auto_regenerate_bbcode(path):
            self.regenerate_bbcode_for_gallery(path, force=False)

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
    """Main function - EMERGENCY PERFORMANCE FIX: Show window first, load in background"""
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)  # Exit when window closes

    # Show splash screen immediately
    print(f"{timestamp()} Loading splash screen")
    splash = SplashScreen()
    splash.show()
    splash.update_status("Initialization sequence")

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
            print(f"{timestamp()} WARNING: ImxUp GUI already running, attempting to bring existing instance to front.")
            splash.finish_and_hide()
            return

    splash.set_status("Qt")

    # Create main window with splash updates
    window = ImxUploadGUI(splash)

    # Add folder from command line if provided
    if folders_to_add:
        window.add_folders(folders_to_add)

    # EMERGENCY FIX: Hide splash and show main window IMMEDIATELY (< 2 seconds)
    splash.finish_and_hide()
    window.show()
    QApplication.processEvents()  # Force window to render NOW

    print(f"{timestamp()} Window visible - starting background gallery load")
    log(f"Window shown, starting background gallery load", level="info", category="performance")

    # EMERGENCY FIX: Load galleries in background with non-blocking progress
    # Phase 1: Load critical data (gallery names, status) - batched with yields
    # Phase 2: Create expensive widgets in background
    QTimer.singleShot(50, lambda: window._load_galleries_phase1())

    # Initialize file host workers AFTER GUI is loaded and displayed
    if hasattr(window, "file_host_manager") and window.file_host_manager:
        QTimer.singleShot(100, lambda: window.file_host_manager.init_enabled_hosts())
        # Count how many workers we're waiting for
        enabled_hosts = [h for h in window.file_host_manager.config_manager.hosts
                         if window.file_host_manager.is_enabled(h)]
        window._file_host_startup_expected = len(enabled_hosts)
        if window._file_host_startup_expected == 0:
            window._file_host_startup_complete = True
        log("File Host Manager workers will spawn after initial load", level="debug", category="file_hosts")

    try:
        sys.exit(app.exec())
    except KeyboardInterrupt:

        # Clean shutdown
        if hasattr(window, 'worker') and window.worker:
            window.worker.stop()
        if hasattr(window, 'server') and window.server:
            window.server.stop()
        if hasattr(window, '_loading_abort'):
            window._loading_abort = True  # Stop background loading
        app.quit()





# ComprehensiveSettingsDialog moved to imxup_settings.py

if __name__ == "__main__":
    main()
