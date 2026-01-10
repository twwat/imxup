#!/usr/bin/env python3
"""Main window and application entry point for IMXuploader GUI.

This module provides the primary PyQt6-based graphical user interface for the IMXuploader
application, which manages batch image uploads to imx.to galleries with support for
multiple file hosts and advanced queue management.

Key Features:
    - Drag-and-drop gallery folder management
    - Multi-threaded upload processing with worker pools
    - Real-time progress tracking and bandwidth monitoring
    - Template-based BBCode generation
    - Database-backed persistent queue storage
    - Archive extraction support (ZIP, RAR, 7Z)
    - Tab-based gallery organization
    - File host integration (Pixeldrain, Bunkr, etc.)
    - Theme support (light/dark mode)
    - Single-instance application architecture

Main Classes:
    ImxUploadGUI: Primary application window and controller
    CompletionWorker: Background thread for post-upload processing
    SingleInstanceServer: TCP server for single-instance communication
    AdaptiveGroupBox: Custom QGroupBox with proper size hint propagation
    LogTextEdit: QTextEdit subclass with double-click signal support
    NumericTableWidgetItem: QTableWidgetItem with numeric sorting

Architecture:
    The GUI follows an MVC-like pattern where:
    - QueueManager (model) manages gallery queue state and database persistence
    - ImxUploadGUI (view/controller) handles UI rendering and user interactions
    - UploadWorker threads (workers) perform actual upload operations
    - FileHostWorkerManager coordinates parallel file host uploads

    Signal/slot connections enable thread-safe communication between workers
    and the main GUI thread for progress updates and status changes.

Thread Safety:
    All database operations are protected by QMutex locks in QueueManager.
    GUI updates from worker threads use Qt signals to marshal to main thread.
    Path-to-row mappings use dedicated mutex for concurrent access safety.

See Also:
    src.storage.queue_manager: Gallery queue state management
    src.processing.upload_workers: Upload worker thread implementation
    src.gui.widgets: Custom widget components
    src.network.client: IMX.to API client implementation
"""

import sys
import os
import json
import logging
import re
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
from src.gui.progress_tracker import ProgressTracker
from src.gui.worker_signal_handler import WorkerSignalHandler
from src.gui.gallery_queue_controller import GalleryQueueController
from src.gui.table_row_manager import TableRowManager
from src.gui.settings_manager import SettingsManager
from src.gui.theme_manager import ThemeManager
from src.gui.menu_manager import MenuManager


class AdaptiveGroupBox(QGroupBox):
    """
    Custom QGroupBox that properly propagates child widget minimum size hints to QSplitter.

    QSplitter queries the direct child widget's minimumSizeHint() to determine resize limits.
    This custom GroupBox overrides minimumSizeHint() to query its layout's minimum size,
    which includes all child widgets and their constraints.

    This ensures that when the splitter is dragged, it respects the minimum height needed
    by nested widgets (like AdaptiveQuickSettingsPanel) and prevents button overlap.
    """

    FRAME_MARGIN = 40  # Margin for GroupBox frame, title, and safety buffer

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
            return QSize(layout_hint.width(), layout_hint.height() + self.FRAME_MARGIN)

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

# Import artifact handling
from src.processing.artifact_handler import CompletionWorker, ArtifactHandler


def format_timestamp_for_display(timestamp_value, include_seconds=False):
    """Format Unix timestamp for table display with optional tooltip.

    Args:
        timestamp_value: Unix timestamp (float/int) or None
        include_seconds: Currently unused, kept for API compatibility

    Returns:
        tuple: (display_text, tooltip_text) where both are formatted datetime strings,
               or ("", "") if timestamp is invalid/None

    Note:
        Display format: "YYYY-MM-DD HH:MM"
        Tooltip format: "YYYY-MM-DD HH:MM:SS"
    """
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
    """Get the absolute path to the assets directory.

    Returns:
        str: Absolute path to project_root/assets directory

    Note:
        Uses get_project_root() to ensure correct path regardless of CWD.
    """
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
    """Check if valid IMX.to credentials exist in Windows Registry (QSettings).

    Returns:
        bool: True if username+password OR api_key are stored

    Note:
        Credentials are stored encrypted in Windows Registry under
        HKEY_CURRENT_USER\\Software\\ImxUploader\\ImxUploadGUI
    """
    from imxup import get_credential

    username = get_credential('username')
    encrypted_password = get_credential('password')
    encrypted_api_key = get_credential('api_key')

    # Have username+password OR api_key
    if (username and encrypted_password) or encrypted_api_key:
        return True
    return False

def api_key_is_set() -> bool:
    """Check if an API key exists in Windows Registry.

    Returns:
        bool: True if encrypted API key is stored in QSettings

    Note:
        API key authentication is preferred over username/password.
    """
    from imxup import get_credential
    encrypted_api_key = get_credential('api_key')
    return bool(encrypted_api_key)


class LogTextEdit(QTextEdit):
    """QTextEdit subclass that emits signal on double-click for log viewer popup.

    Signals:
        doubleClicked(): Emitted when user double-clicks with left mouse button

    Used to open the full log viewer dialog when double-clicking the log panel.
    """
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
    """Table widget item that sorts numerically instead of lexicographically.

    Stores an integer value internally for proper numeric comparison during
    table sorting, while displaying the value as a string.

    Example:
        Without this class: "10" < "2" (lexicographic)
        With this class: 10 < 2 is False (numeric)

    Attributes:
        _numeric_value (int): Internal integer value for comparison
    """
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
    """TCP server for single-instance application communication.

    Listens on localhost:COMMUNICATION_PORT for messages from new instances.
    When a second instance starts, it sends folder paths to this server and exits.
    This allows handling "Open With" and drag-drop to EXE in Windows Explorer.

    Signals:
        folder_received(str): Emitted when message received (folder path or empty for focus)

    Port:
        Default port is 27849 (COMMUNICATION_PORT constant)

    Protocol:
        Simple UTF-8 text messages over TCP
        - Non-empty string = folder path to add to queue
        - Empty string = focus existing window

    Thread Safety:
        Runs in separate thread to avoid blocking GUI.
        Uses signal/slot for thread-safe communication with main window.
    """
    
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
                        log(f"Server error: {e}", level="error", category="ipc")
                        
            server_socket.close()
        except Exception as e:
            log(f"Failed to start server: {e}", level="error", category="ipc")
    
    def stop(self):
        self.running = False
        self.wait()

class ImxUploadGUI(QMainWindow):
    """Main application window for IMXuploader GUI.

    This is the primary controller class that coordinates all GUI components,
    manages upload workers, handles user interactions, and maintains application state.

    Key Responsibilities:
        - Gallery queue display and management (table view with tabs)
        - Upload worker lifecycle management (start/pause/stop/cancel)
        - Progress tracking and bandwidth monitoring
        - Settings persistence (window geometry, column widths, user preferences)
        - Theme management (light/dark mode with custom stylesheets)
        - File host integration and coordination
        - Archive extraction workflow
        - Template and BBCode management
        - System tray integration
        - Single-instance application coordination

    Architecture:
        Uses QueueManager for persistent storage and state management.
        Communicates with worker threads via Qt signals/slots.
        Updates UI components through event-driven model.

    Major Components:
        - gallery_table: TabbedGalleryWidget showing queue with tab organization
        - queue_manager: QueueManager instance for database operations
        - file_host_manager: FileHostWorkerManager for parallel file host uploads
        - worker_status_widget: WorkerStatusWidget showing real-time worker status
        - archive_coordinator: ArchiveCoordinator for ZIP/RAR/7Z extraction
        - tab_manager: TabManager for tab persistence and organization

    Thread Safety:
        All worker communication uses Qt signals to marshal to main thread.
        Path-to-row mapping protected by _path_mapping_mutex.
        Database operations delegated to QueueManager with internal locking.

    Attributes:
        queue_manager (QueueManager): Persistent queue storage and state
        file_host_manager (FileHostWorkerManager): File host upload coordination
        worker_status_widget (WorkerStatusWidget): Real-time worker display
        gallery_table (TabbedGalleryWidget): Main table view with tabs
        settings (QSettings): Persistent settings storage (Windows Registry)
        path_to_row (dict): Maps gallery path -> table row index
        row_to_path (dict): Maps table row index -> gallery path

    See Also:
        src.storage.queue_manager.QueueManager: Queue state management
        src.processing.upload_workers.UploadWorker: Upload thread implementation
        src.processing.file_host_worker_manager.FileHostWorkerManager: File host coordination
        src.gui.widgets.tabbed_gallery.TabbedGalleryWidget: Main table component
    """

    # Type hints for attributes that mypy needs to see
    _current_theme_mode: str
    _cached_base_qss: str

    def __init__(self, splash=None):
        """Initialize the main GUI window.

        Args:
            splash: Optional SplashScreen instance for startup progress display

        Initialization Flow:
            1. Initialize IconManager and load theme icons
            2. Create QueueManager and restore queue from database
            3. Initialize file host worker manager
            4. Create worker status widget
            5. Build UI components (setup_ui)
            6. Setup menu bar and system tray
            7. Restore saved settings (geometry, column widths, theme)
            8. Connect signal handlers
            9. Initialize background workers (CompletionWorker, etc.)

        Note:
            Includes guards against double initialization.
            Sets up thread pools and progress batchers for performance.
            Configures single-instance server for IPC.
        """
        from src.utils.logger import log  # Import at function start
        import traceback  # Import at function start

        super().__init__()
        self._initializing = True  # Block recursive calls during init

        # Guard against double initialization
        if hasattr(self, '_init_complete'):
            caller = traceback.extract_stack()[-2]
            log(f"WARNING: ImxUploadGUI.__init__ called twice! (from {caller.filename}:{caller.lineno} in {caller.name})",
                level="warning", category="startup")
            return  # Skip re-initialization

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

        # Session time tracking for statistics
        self._session_start_time = time.time()
        self._session_time_saved = False  # Flag to prevent double-saving on close
        self._init_session_stats()

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
            log(f"Failed to initialize IconManager: {e}", level="error", category="ui")
            
            
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
        # Guard against double initialization
        if hasattr(self, 'queue_manager') and self.queue_manager is not None:
            log("QueueManager already initialized, skipping", level="warning", category="startup")
        else:
            from src.storage.queue_manager import QueueManager
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
        # Note: connected after worker_signal_handler initialized, see below
        
        self.worker = None
        
        # Initialize completion worker for background processing
        self.completion_worker = CompletionWorker(self)

        self.completion_worker.completion_processed.connect(self.on_completion_processed)
        self.completion_worker.log_message.connect(self.add_log_message)
        self.completion_worker.start()
        if self.splash:
            self.splash.set_status("Upload Completion Worker")

        # Initialize artifact handler for BBCode regeneration
        self.artifact_handler = ArtifactHandler(self)
        if self.splash:
            self.splash.set_status("Artifact Handler")

        # Create worker status widget early (before FileHostWorkerManager)
        # This ensures it exists when manager tries to connect signals
        if self.splash:
            self.splash.set_status("Worker Status Widget")
        # Guard against double initialization
        if hasattr(self, 'worker_status_widget') and self.worker_status_widget is not None:
            log("WorkerStatusWidget already initialized, skipping", level="warning", category="startup")
        else:
            from src.gui.widgets.worker_status_widget import WorkerStatusWidget
            self.worker_status_widget = WorkerStatusWidget()

        # Initialize progress tracker for bandwidth/progress monitoring
        self.progress_tracker = ProgressTracker(self)

        # Initialize worker signal handler for worker lifecycle management
        self.worker_signal_handler = WorkerSignalHandler(self)

        # Initialize gallery queue controller for queue operations
        self.gallery_queue_controller = GalleryQueueController(self)

        # Initialize table row manager for row population and status icons
        self.table_row_manager = TableRowManager(self)
        self.settings_manager = SettingsManager(self)
        self.theme_manager = ThemeManager(self)
        self.menu_manager = MenuManager(self)
        self._update_checker = None  # Initialize update checker reference

        # Now connect queue status changes (after worker_signal_handler is ready)
        self.queue_manager.status_changed.connect(self.worker_signal_handler.on_queue_item_status_changed)

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
                # Connect manager signals to UI handlers (via worker_signal_handler)
                self.file_host_manager.test_completed.connect(self.worker_signal_handler.on_file_host_test_completed)
                self.file_host_manager.upload_started.connect(self.worker_signal_handler.on_file_host_upload_started)
                self.file_host_manager.upload_progress.connect(self.worker_signal_handler.on_file_host_upload_progress)
                self.file_host_manager.upload_completed.connect(self.worker_signal_handler.on_file_host_upload_completed)
                self.file_host_manager.upload_failed.connect(self.worker_signal_handler.on_file_host_upload_failed)
                self.file_host_manager.bandwidth_updated.connect(self.worker_signal_handler.on_file_host_bandwidth_updated)

                # Connect to worker status widget (via worker_signal_handler)
                self.file_host_manager.upload_started.connect(self.worker_signal_handler._on_filehost_worker_started)
                self.file_host_manager.upload_progress.connect(self.worker_signal_handler._on_filehost_worker_progress)
                self.file_host_manager.upload_completed.connect(self.worker_signal_handler._on_filehost_worker_completed)
                self.file_host_manager.upload_failed.connect(self.worker_signal_handler._on_filehost_worker_failed)
                self.file_host_manager.storage_updated.connect(self.worker_status_widget.update_worker_storage)
                self.file_host_manager.enabled_workers_changed.connect(self._on_file_hosts_enabled_changed)
                self.file_host_manager.spinup_complete.connect(self.worker_signal_handler._on_file_host_startup_spinup)
                self.file_host_manager.worker_status_updated.connect(self.worker_signal_handler._on_worker_status_updated)

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
            self.splash.set_status("Starting SingleInstanceServer...")
        self.server = SingleInstanceServer()
        self.server.folder_received.connect(self.add_folder_from_command_line)
        self.server.start()
        
        if self.splash:
            self.splash.set_status("Setting up UI...")
        self.setup_ui()
        
        # Initialize context menu helper and connect to the actual table widget
        if self.splash:
            self.splash.set_status("Initializing context menu helper...")
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
            log(f"Could not connect context menu helper: {e}", level="error", category="ui")
        
        if self.splash:
            self.splash.set_status("Setting up menu bar...")
            self.splash.update_status("random")
        self.menu_manager.setup_menu_bar()
        if self.splash:
            self.splash.set_status("Running setup_system_tray()")
        self.setup_system_tray()
        if self.splash:
            self.splash.set_status("Restoring settings...")
        self.restore_settings()
       
        # Easter egg - quick gremlin flash
        if self.splash:
            self.splash.set_status("Wiping front to back")
            time.sleep(0.015)
            self.splash.set_status("Processing events...")
            QApplication.processEvents()
        
        # Initialize table update queue after table creation
        self._table_update_queue = TableUpdateQueue(self.gallery_table, self.path_to_row)
        
        # Initialize background tab update system
        self._background_tab_updates = {}  # Track updates for non-visible tabs
        self._background_update_timer = QTimer()
        self._background_update_timer.timeout.connect(self.table_row_manager._process_background_tab_updates)
        self._background_update_timer.setSingleShot(True)

        # Uploading status icon animation (7 frames, 200ms each)
        self._upload_animation_frame = 0
        self._upload_animation_timer = QTimer()
        self._upload_animation_timer.timeout.connect(self.table_row_manager._advance_upload_animation)
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
            self.gallery_table.tab_changed.connect(self.progress_tracker._update_button_counts)
            self.gallery_table.tab_changed.connect(self.progress_tracker.update_progress_display)
        
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
                log(f"Timer error: {e}", level="error", category="ui")

        self.update_timer.timeout.connect(_tick)
        self.update_timer.start(500)  # Start the timer
        self.check_credentials() # Check for stored credentials (only prompt if API key missing)
        self.worker_signal_handler.start_worker() # Start worker thread
        # Gallery loading moved to main() with progress dialog for better perceived performance
        # Button counts and progress will be updated by refresh_filter() after filter is applied
        self.gallery_table.setFocus() # Ensure table has focus for keyboard shortcuts

        # Refresh log display settings (already initialized early to avoid AttributeError)
        self._refresh_log_display_settings()
        self._initializing = False # Clear initialization flag to allow normal tooltip updates

        # Mark initialization complete
        self._init_complete = True
        log(f"ImxUploadGUI.__init__ Completed", level="debug")

    def _load_galleries_phase1(self):
        """Phase 1 - Load critical gallery data in single pass.

        Delegates to TableRowManager._load_galleries_phase1()
        """
        self.table_row_manager._load_galleries_phase1()

    def _load_galleries_phase2(self):
        """Phase 2 - Create widgets ONLY for visible rows (viewport-based lazy loading).

        Delegates to TableRowManager._load_galleries_phase2()
        """
        self.table_row_manager._load_galleries_phase2()

    def _get_visible_row_range(self) -> tuple[int, int]:
        """Calculate the range of visible rows in the table viewport.

        Delegates to TableRowManager._get_visible_row_range()
        """
        return self.table_row_manager._get_visible_row_range()

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
        """Create progress and action widgets for a single row.

        Delegates to TableRowManager._create_row_widgets()
        """
        self.table_row_manager._create_row_widgets(row)

    def _finalize_gallery_load(self):
        """Finalize gallery loading - apply filters and update UI.

        Delegates to TableRowManager._finalize_gallery_load()
        """
        self.table_row_manager._finalize_gallery_load()

    def _populate_table_row_minimal(self, row: int, item: GalleryQueueItem):
        """Populate row with MINIMAL data only (no expensive widgets).

        Delegates to TableRowManager._populate_table_row_minimal()
        """
        self.table_row_manager._populate_table_row_minimal(row, item)

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
        """Process queued updates for non-visible tabs in background.

        Delegates to TableRowManager._process_background_tab_updates()
        """
        self.table_row_manager._process_background_tab_updates()

    def queue_background_tab_update(self, path: str, item, update_type: str = 'progress'):
        """Queue an update for galleries not currently visible in tabs.

        Delegates to TableRowManager.queue_background_tab_update()
        """
        return self.table_row_manager.queue_background_tab_update(path, item, update_type)

    def clear_background_tab_updates(self):
        """Clear all background tab updates (e.g., when switching tabs).

        Delegates to TableRowManager.clear_background_tab_updates()
        """
        self.table_row_manager.clear_background_tab_updates()

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
            self.bandwidth_status_label.setProperty("status", "active")
        else:
            self.bandwidth_status_label.setText("Bandwidth: 0.00 MiB/s")
            self.bandwidth_status_label.setProperty("status", "")
        # Reapply stylesheet to pick up property change
        self.bandwidth_status_label.style().unpolish(self.bandwidth_status_label)
        self.bandwidth_status_label.style().polish(self.bandwidth_status_label)

        self.bandwidth_status_label.setToolTip(tooltip)

    def _set_status_cell_icon(self, row: int, status: str):
        """Render the Status column as an icon.

        Delegates to TableRowManager._set_status_cell_icon()
        """
        self.table_row_manager._set_status_cell_icon(row, status)

    def _set_status_text_cell(self, row: int, status: str):
        """Set the status text column with capitalized status string.

        Delegates to TableRowManager._set_status_text_cell()
        """
        self.table_row_manager._set_status_text_cell(row, status)

    def _on_selection_changed(self, selected, deselected):
        """Handle gallery table selection changes to refresh icons.

        Only updates rows that actually changed selection state (from selected
        and deselected parameters) instead of all rows, avoiding O(N²) complexity
        when using Ctrl+A or other bulk selection operations.
        """
        try:
            # For tabbed gallery system, use the inner table
            inner_table = getattr(self.gallery_table, 'table', None)
            if not inner_table or not hasattr(inner_table, 'rowCount'):
                return

            # Collect unique rows that changed selection state
            changed_rows = set()
            for index in selected.indexes():
                changed_rows.add(index.row())
            for index in deselected.indexes():
                changed_rows.add(index.row())

            # Only refresh icons for rows that actually changed
            for row in changed_rows:
                # Get status from the queue item
                name_item = inner_table.item(row, GalleryTableWidget.COL_NAME)
                if name_item:
                    path = name_item.data(Qt.ItemDataRole.UserRole)
                    if path and path in self.queue_manager.items:
                        item = self.queue_manager.items[path]
                        self._set_status_cell_icon(row, item.status)

        except Exception as e:
            log(f"Error in selection change handler: {e}", level="warning", category="ui")

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
        """Advance the upload animation frame and update uploading icons.

        Delegates to TableRowManager._advance_upload_animation()
        """
        self.table_row_manager._advance_upload_animation()

    def refresh_icons(self):
        """Alias for refresh_all_status_icons - called from settings dialog.

        Delegates to TableRowManager.refresh_icons()
        """
        self.table_row_manager.refresh_icons()

    def refresh_all_status_icons(self):
        """Refresh all status icons and action button icons after icon changes in settings.

        Delegates to TableRowManager.refresh_all_status_icons()
        """
        self.table_row_manager.refresh_all_status_icons()

    def _apply_icon_to_cell(self, row: int, col: int, icon, tooltip: str, status: str):
        """Apply icon to table cell - runs on main thread.

        Delegates to TableRowManager._apply_icon_to_cell()
        """
        self.table_row_manager._apply_icon_to_cell(row, col, icon, tooltip, status)

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
        """Set the Renamed column cell to an icon (check/pending).

        Delegates to TableRowManager._set_renamed_cell_icon()
        """
        self.table_row_manager._set_renamed_cell_icon(row, is_renamed)

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
            self._queue_stats_timer.timeout.connect(self.worker_signal_handler._update_worker_queue_stats)
            self._queue_stats_timer.start(2000)  # Poll every 2 seconds

        # Refresh button icons with correct theme now that palette is ready
        # Deferred to avoid blocking GUI startup with large gallery counts
        QTimer.singleShot(0, self._refresh_button_icons)

        # Schedule startup update check (3 second delay to not block UI)
        if self._should_check_for_updates():
            QTimer.singleShot(3000, self._check_for_updates_silently)
    
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
        self.settings_group.setMinimumHeight(400)

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
                    self.log_viewer_btn.setIconSize(QSize(32, 20))
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
                    self.file_hosts_btn.setIconSize(QSize(22, 22))
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

        # Statistics button (opens statistics dialog)
        self.statistics_btn = QPushButton("")
        self.statistics_btn.setToolTip("View application statistics")
        try:
            icon_mgr = get_icon_manager()
            if icon_mgr:
                stats_icon = icon_mgr.get_icon('statistics')
                if not stats_icon.isNull():
                    self.statistics_btn.setIcon(stats_icon)
                    self.statistics_btn.setIconSize(QSize(20, 20))
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise
        self.statistics_btn.clicked.connect(self.open_statistics_dialog)
        self.statistics_btn.setProperty("class", "quick-settings-btn")

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
            self.theme_toggle_btn,          # Theme
            self.statistics_btn             # Statistics
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

    def show_about_dialog(self):
        """Show About dialog. Delegated to MenuManager."""
        self.menu_manager.show_about_dialog()

    def show_license_dialog(self):
        """Show License dialog. Delegated to MenuManager."""
        self.menu_manager.show_license_dialog()

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
        """Install Windows context menu. Delegated to MenuManager."""
        self.menu_manager.install_context_menu()

    def remove_context_menu(self):
        """Remove Windows context menu. Delegated to MenuManager."""
        self.menu_manager.remove_context_menu()

    def check_for_updates(self, silent: bool = False):
        """Start background update check.

        Launches a background thread to query the GitHub Releases API
        and check if a newer version of the application is available.

        Args:
            silent: If True, don't show dialogs for "up to date" or errors.
                    Only show dialog if update is available.
        """
        from src.network.update_checker import UpdateChecker
        from imxup import __version__, GITHUB_OWNER, GITHUB_REPO

        self._update_checker = UpdateChecker(__version__, GITHUB_OWNER, GITHUB_REPO)
        self._update_checker.update_available.connect(
            lambda v, u, n, d: self._on_update_available(v, u, n, d, silent))
        self._update_checker.no_update.connect(lambda: self._on_no_update(silent))
        self._update_checker.check_failed.connect(lambda e: self._on_check_failed(e, silent))
        self._update_checker.start()

    def _on_update_available(self, version: str, url: str, notes: str, date: str, silent: bool):
        """Handle update available signal.

        Shows a dialog informing the user about the new version unless
        they have previously chosen to skip this specific version.

        Args:
            version: New version string.
            url: Download URL for the release.
            notes: Release notes content.
            date: Release date string.
            silent: Ignored for updates (updates are always shown).
        """
        from src.gui.dialogs.update_dialog import UpdateDialog
        from imxup import __version__

        # Check if user has skipped this version
        skipped_version = self.settings.value('updates/skipped_version', '', type=str)
        if skipped_version == version:
            log(f"Update {version} skipped by user", level="debug", category="updates")
            return

        dialog = UpdateDialog(self, __version__, version, url, notes, date)
        result = dialog.exec()

        if dialog.skip_version:
            self.settings.setValue('updates/skipped_version', version)
            log(f"User chose to skip version {version}", level="info", category="updates")

    def _on_no_update(self, silent: bool):
        """Handle no update available signal.

        Shows an informational message unless running in silent mode.

        Args:
            silent: If True, suppress the dialog.
        """
        if not silent:
            QMessageBox.information(self, "Update Check",
                                   "You're running the latest version!")
        log("No update available", level="debug", category="updates")

    def _on_check_failed(self, error: str, silent: bool):
        """Handle update check failure signal.

        Shows a warning dialog unless running in silent mode.

        Args:
            error: Error message describing the failure.
            silent: If True, suppress the dialog.
        """
        if not silent:
            QMessageBox.warning(self, "Update Check Failed",
                               f"Could not check for updates:\n{error}")
        log(f"Update check failed: {error}", level="warning", category="updates")

    def _should_check_for_updates(self) -> bool:
        """Check if auto-update check should run.

        Returns True only if auto-check is enabled in settings AND
        at least 24 hours have passed since the last check.

        Returns:
            True if update check should proceed, False otherwise.
        """
        # Check if auto-check is enabled in settings
        defaults = load_user_defaults()
        if not defaults.get('check_updates_on_startup', True):
            return False

        # Check 24-hour cooldown
        last_check = self.settings.value('updates/last_check_time', 0, type=int)
        current_time = int(time.time())
        if current_time - last_check < 86400:  # 24 hours
            return False

        return True

    def _check_for_updates_silently(self):
        """Check for updates silently on startup.

        Updates the last check timestamp and runs a silent update check
        that will only show a dialog if an update is available.
        """
        self.settings.setValue('updates/last_check_time', int(time.time()))
        self.check_for_updates(silent=True)

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

        # Refresh worker status widget to apply UI setting changes (e.g., show logos)
        if hasattr(self, 'worker_status_widget') and self.worker_status_widget:
            self.worker_status_widget.refresh_icons()

    def open_help_dialog(self):
        """Open the help/documentation dialog"""
        dialog = HelpDialog(self)
        # Use non-blocking show() for help dialog
        dialog.show()

    def open_statistics_dialog(self) -> None:
        """Open the Statistics dialog.

        Shows comprehensive application statistics including session info,
        upload totals, and image scanner stats.
        """
        from src.gui.dialogs.statistics_dialog import StatisticsDialog
        dialog = StatisticsDialog(self, self._session_start_time)
        dialog.exec()

    def _init_session_stats(self) -> None:
        """Initialize session statistics on app startup.

        Increments app_startup_count and sets first_startup_timestamp
        if not already recorded. Called once during __init__.
        """
        from datetime import datetime
        settings = QSettings("ImxUploader", "Stats")

        # Increment startup count
        count = settings.value("app_startup_count", 0, type=int)
        settings.setValue("app_startup_count", count + 1)

        # Set first startup timestamp if not already set
        if not settings.value("first_startup_timestamp"):
            settings.setValue("first_startup_timestamp",
                              datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        settings.sync()

    def _save_session_time(self) -> None:
        """Save accumulated session time to QSettings.

        Called on app close. Adds current session duration to the stored total.
        Uses a flag to prevent double-saving if called multiple times during shutdown.
        """
        if not hasattr(self, '_session_start_time'):
            return

        # Check if already saved to prevent double-counting during shutdown
        if getattr(self, '_session_time_saved', False):
            return

        duration = int(time.time() - self._session_start_time)
        if duration <= 0:
            return

        settings = QSettings("ImxUploader", "Stats")
        total = settings.value("total_session_time_seconds", 0, type=int)
        settings.setValue("total_session_time_seconds", total + duration)
        settings.sync()

        # Mark as saved to prevent double-counting
        self._session_time_saved = True

    def toggle_theme(self):
        """Toggle between light and dark theme.

        Delegates to ThemeManager.toggle_theme().
        """
        self.theme_manager.toggle_theme()

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
        """Switch theme mode and persist. mode in {'light','dark'}.

        Delegates to ThemeManager.set_theme_mode().

        Args:
            mode: Theme mode to apply ('light' or 'dark')
        """
        self.theme_manager.set_theme_mode(mode)

    def apply_theme(self, mode: str):
        """Apply theme. Only 'light' and 'dark' modes supported.

        Delegates to ThemeManager.apply_theme().

        Args:
            mode: Theme mode to apply ('light' or 'dark')
        """
        self.theme_manager.apply_theme(mode)

    def apply_font_size(self, font_size: int):
        """Apply the specified font size throughout the application.

        Delegates to ThemeManager.apply_font_size().

        Args:
            font_size: Font size in points to apply
        """
        self.theme_manager.apply_font_size(font_size)

    def _get_current_font_size(self) -> int:
        """Get the current font size setting.

        Delegates to ThemeManager._get_current_font_size().

        Returns:
            int: Current font size in points
        """
        return self.theme_manager._get_current_font_size()

    def _get_table_font_sizes(self) -> tuple:
        """Get appropriate font sizes for table elements based on current setting.

        Delegates to ThemeManager._get_table_font_sizes().

        Returns:
            tuple: (table_font_size, name_font_size) in points
        """
        return self.theme_manager._get_table_font_sizes()

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

    # =========================================================================
    # Worker signal handling delegated to WorkerSignalHandler
    # =========================================================================

    def _refresh_file_host_widgets_for_db_id(self, db_id: int):
        """Refresh file host widgets for a specific gallery ID - OPTIMIZED VERSION

        This method is called asynchronously via QTimer to avoid blocking signal emission.
        Optimized to use O(1) lookups instead of iterating all items.
        """
        try:
            # 1. Entry point logging
            log(f"_refresh_file_host_widgets_for_db_id called with db_id={db_id}",
                level="debug", category="file_hosts")

            # OPTIMIZATION 1: Use cached db_id -> path mapping if available
            # This avoids iterating through all queue items
            if not hasattr(self, '_db_id_to_path'):
                self._db_id_to_path = {}

            gallery_path = self._db_id_to_path.get(db_id)

            # 2. Log cache lookup result
            log(f"db_id {db_id} in _db_id_to_path: {db_id in self._db_id_to_path}, "
                f"mapped path: {gallery_path}", level="debug", category="file_hosts")

            # If not cached, fall back to search (only on first miss)
            if not gallery_path:
                log(f"Cache miss for db_id {db_id}, searching queue items",
                    level="debug", category="file_hosts")
                for item in self.queue_manager.get_all_items():
                    if item.db_id and item.db_id == db_id:
                        gallery_path = item.path
                        # Cache for future lookups
                        self._db_id_to_path[db_id] = gallery_path
                        log(f"Found and cached: db_id {db_id} -> path {gallery_path}",
                            level="debug", category="file_hosts")
                        break

            if not gallery_path:
                log(f"No path found for db_id {db_id}, exiting",
                    level="debug", category="file_hosts")
                return

            # OPTIMIZATION 2: O(1) row lookup via path_to_row dict
            row = self.path_to_row.get(gallery_path)

            # 3. Log row lookup result
            log(f"path '{gallery_path}' in path_to_row: {gallery_path in self.path_to_row}, "
                f"mapped row: {row}", level="debug", category="file_hosts")

            if row is None:
                log(f"No row found for path '{gallery_path}', exiting",
                    level="debug", category="file_hosts")
                return

            # OPTIMIZATION 3: Get widget reference first, skip DB query if widget missing
            from src.gui.widgets.custom_widgets import FileHostsStatusWidget
            status_widget = self.gallery_table.table.cellWidget(row, GalleryTableWidget.COL_HOSTS_STATUS)

            # 4. Log widget lookup result
            widget_type = type(status_widget).__name__ if status_widget else "None"
            log(f"cellWidget(row={row}, COL_HOSTS_STATUS) returned: {widget_type}, "
                f"is FileHostsStatusWidget: {isinstance(status_widget, FileHostsStatusWidget)}",
                level="debug", category="file_hosts")

            if not isinstance(status_widget, FileHostsStatusWidget):
                log(f"File host status widget not found at row {row} for db_id {db_id}", level="debug", category="file_hosts")
                return  # Widget not present, skip expensive DB query

            # Only do DB query if we have a valid widget to update
            host_uploads = {}
            try:
                uploads_list = self.queue_manager.store.get_file_host_uploads(gallery_path)
                host_uploads = {upload['host_name']: upload for upload in uploads_list}

                # 5. Log uploads fetched from database
                log(f"Fetched {len(uploads_list)} file host uploads from database for path '{gallery_path}': "
                    f"hosts={list(host_uploads.keys())}", level="debug", category="file_hosts")

            except Exception as e:
                log(f"Failed to load file host uploads: {e}", level="warning", category="file_hosts")
                return

            # Update widget (already confirmed it exists and is correct type)
            status_widget.update_hosts(host_uploads)
            status_widget.update()  # Force visual refresh

            # BUGFIX: Update cache to prevent stale data on future row refreshes
            # Cache is used during row population (table_row_manager.py:370-371)
            # Without this update, rows show incorrect status when re-populated
            # (scrolling, filtering, theme changes would revert to stale cache)
            if hasattr(self, '_file_host_uploads_cache') and gallery_path:
                self._file_host_uploads_cache[gallery_path] = uploads_list

            # 6. Confirm update_hosts was called
            log(f"Called update_hosts() on widget at row {row} with {len(host_uploads)} hosts",
                level="debug", category="file_hosts")

        except Exception as e:
            # 7. Log any exceptions
            log(f"Exception in _refresh_file_host_widgets_for_db_id(db_id={db_id}): {e}",
                level="debug", category="file_hosts")
            log(f"Error refreshing file host widgets: {e}", level="error", category="file_hosts")
            import traceback
            traceback.print_exc()


    def browse_for_folders(self):
        """Open folder browser to select galleries or archives (supports multiple selection).

        Delegates to GalleryQueueController.
        """
        self.gallery_queue_controller.browse_for_folders()
    
    def add_folders_or_archives(self, paths: List[str]):
        """Add folders or archives to upload queue.

        Delegates to GalleryQueueController.

        Args:
            paths: List of folder or archive file paths to add
        """
        self.gallery_queue_controller.add_folders_or_archives(paths)

    def add_folders(self, folder_paths: List[str]):
        """Add folders to the upload queue with duplicate detection.

        Delegates to GalleryQueueController.

        Args:
            folder_paths: List of folder paths to add to queue
        """
        self.gallery_queue_controller.add_folders(folder_paths)
    
    def _add_single_folder(self, path: str):
        """Add a single folder with duplicate detection.

        Delegates to GalleryQueueController.

        Args:
            path: Path to the folder to add
        """
        self.gallery_queue_controller._add_single_folder(path)

    def _add_archive_folder(self, folder_path: str, archive_path: str):
        """Add a folder from extracted archive to queue.

        Delegates to GalleryQueueController.

        Args:
            folder_path: Path to the extracted folder
            archive_path: Path to the source archive file
        """
        self.gallery_queue_controller._add_archive_folder(folder_path, archive_path)

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
        """Add multiple folders efficiently using the batch method.

        Delegates to GalleryQueueController.

        Args:
            folder_paths: List of folder paths to add
        """
        self.gallery_queue_controller._add_multiple_folders(folder_paths)
    
    def _add_multiple_folders_with_duplicate_detection(self, folder_paths: List[str]):
        """Add multiple folders with duplicate detection dialogs.

        Delegates to GalleryQueueController.

        Args:
            folder_paths: List of folder paths to add
        """
        self.gallery_queue_controller._add_multiple_folders_with_duplicate_detection(folder_paths)

    def add_folder_from_command_line(self, folder_path: str):
        """Add folder from command line (single instance).

        Delegates to GalleryQueueController.

        Args:
            folder_path: Path to the folder to add
        """
        self.gallery_queue_controller.add_folder_from_command_line(folder_path)
    
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
        """Update row data immediately with proper font consistency.

        Delegates to TableRowManager._populate_table_row()
        """
        self.table_row_manager._populate_table_row(row, item, total)


    def _populate_table_row_detailed(self, row: int, item: GalleryQueueItem):
        """Complete row formatting in background.

        Delegates to TableRowManager._populate_table_row_detailed()
        """
        self.table_row_manager._populate_table_row_detailed(row, item)

    def _update_size_and_transfer_columns(self, row: int, item: GalleryQueueItem, theme_mode: str):
        """Update size and transfer columns with proper formatting.

        Delegates to TableRowManager._update_size_and_transfer_columns()
        """
        self.table_row_manager._update_size_and_transfer_columns(row, item, theme_mode)

    def _initialize_table_from_queue(self, progress_callback=None):
        """Initialize table from existing queue items.

        Delegates to TableRowManager._initialize_table_from_queue()
        """
        self.table_row_manager._initialize_table_from_queue(progress_callback)

    def _create_deferred_widgets(self, total_rows: int):
        """Create deferred widgets (progress bars, action buttons) after initial load.

        Delegates to TableRowManager._create_deferred_widgets()
        """
        self.table_row_manager._create_deferred_widgets(total_rows)

    def _update_scanned_rows(self):
        """Update only rows where scan completion status has changed.

        Delegates to TableRowManager._update_scanned_rows()
        """
        self.table_row_manager._update_scanned_rows()

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
        # Use O(1) path lookup instead of O(n) row iteration
        row = self._get_row_for_path(path)
        if row is not None:
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
        
        # Update button counts and progress after gallery starts
        QTimer.singleShot(0, self.progress_tracker._update_counts_and_progress)
    
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
            self.progress_tracker.update_progress_display()
                
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
            self.progress_tracker._current_transfer_kbps = transfer_speed / 1024.0
            # Also update the item's speed for consistency
            with QMutexLocker(self.queue_manager.mutex):
                if path in self.queue_manager.items:
                    item = self.queue_manager.items[path]
                    item.final_kibps = self.progress_tracker._current_transfer_kbps
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
        QTimer.singleShot(0, self.progress_tracker._update_counts_and_progress)

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
                # Save timestamp when new record is set
                from datetime import datetime
                settings.setValue("fastest_kbps_timestamp",
                                  datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            settings.setValue("total_galleries", total_galleries)
            settings.setValue("total_images", total_images_acc)
            settings.setValue("total_size_bytes_v2", str(total_size_acc))
            settings.setValue("fastest_kbps", fastest_kbps)
            settings.sync()
            # Refresh progress display to show updated stats
            self.progress_tracker.update_progress_display()
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

                    # Use O(1) path lookup instead of O(n) row iteration
                    row = self._get_row_for_path(path)
                    if row is not None and actual_table:
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
                        QTimer.singleShot(100, lambda p=path: self.artifact_handler.regenerate_bbcode_for_gallery(p, force=False) if self.artifact_handler.should_auto_regenerate_bbcode(p) else None)
                    elif not actual_table:
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
        self.progress_tracker._update_unnamed_count_background()
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
        QTimer.singleShot(0, self.progress_tracker._update_counts_and_progress)
        
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

            # Strip log level prefix if setting is disabled (cached value)
            if not self._log_show_level:
                level_prefixes = ["TRACE: ", "DEBUG: ", "INFO: ", "WARNING: ", "ERROR: ", "CRITICAL: "]
                for level_prefix in level_prefixes:
                    if rest.startswith(level_prefix):
                        rest = rest[len(level_prefix):]
                        break

            # Strip [category] or [category:subtype] tag if setting is disabled (cached value)
            if not self._log_show_category:
                # Find category tag - could be at start or after level prefix
                bracket_idx = rest.find("[")
                if bracket_idx != -1 and "]" in rest:
                    close_idx = rest.find("]", bracket_idx)
                    if close_idx != -1:
                        # Remove the [category] tag and any trailing space
                        rest = rest[:bracket_idx] + rest[close_idx + 1:].lstrip()

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
        dialog.galleries_changed.connect(self.progress_tracker._update_unnamed_count_background)

        dialog.exec()

    def start_single_item(self, path: str):
        """Start a single item"""
        if self.queue_manager.start_item(path):
            log(f"Started: {os.path.basename(path)}", level="info", category="queue")
            self._update_specific_gallery_display(path)
            # Update button counts after status change
            QTimer.singleShot(0, self.progress_tracker._update_button_counts)
        else:
            log(f"Failed to start: {os.path.basename(path)}", level="warning", category="queue")
    
    def pause_single_item(self, path: str):
        """Pause a single item"""
        if self.queue_manager.pause_item(path):
            log(f"Paused: {os.path.basename(path)}", level="info", category="queue")
            self._update_specific_gallery_display(path)
            # Update button counts after status change
            QTimer.singleShot(0, self.progress_tracker._update_button_counts)
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
            QTimer.singleShot(0, self.progress_tracker._update_button_counts)
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
                self.progress_tracker._update_counts_and_progress()
    
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
            self.progress_tracker._update_counts_and_progress()
    
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
                # Validate gallery folder exists before queuing
                if not os.path.isdir(gallery_path):
                    log(f"Cannot upload to {host_name}: gallery folder not found: {gallery_path}", level="warning", category="file_hosts")
                    new_path = self._handle_missing_gallery_folder(gallery_path, host_name)
                    if new_path:
                        # User relocated the gallery, retry with new path
                        gallery_path = new_path
                    else:
                        # User cancelled or removed gallery
                        return

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

    def _handle_missing_gallery_folder(self, gallery_path: str, host_name: str) -> Optional[str]:
        """Handle missing gallery folder - offer to relocate or remove.

        Args:
            gallery_path: Path to the missing gallery
            host_name: Name of the file host (for context in messages)

        Returns:
            New path if user relocated the gallery, None if cancelled/removed
        """
        from PyQt6.QtWidgets import QMessageBox, QFileDialog

        gallery_name = os.path.basename(gallery_path)
        old_parent = os.path.dirname(gallery_path)

        # Create dialog with options
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setWindowTitle("Gallery Folder Not Found")
        msg.setText(f"The gallery folder no longer exists:\n{gallery_path}")
        msg.setInformativeText("Would you like to locate it?")

        browse_btn = msg.addButton("Browse...", QMessageBox.ButtonRole.ActionRole)
        remove_btn = msg.addButton("Remove from Queue", QMessageBox.ButtonRole.DestructiveRole)
        msg.addButton(QMessageBox.StandardButton.Cancel)

        msg.exec()
        clicked = msg.clickedButton()

        if clicked == browse_btn:
            # Let user browse for new location
            new_path = QFileDialog.getExistingDirectory(
                self,
                f"Locate Gallery: {gallery_name}",
                os.path.dirname(old_parent) if os.path.exists(os.path.dirname(old_parent)) else "",
                QFileDialog.Option.ShowDirsOnly
            )

            if new_path and os.path.isdir(new_path):
                # Update database
                success = self.queue_manager.store.update_gallery_path(gallery_path, new_path)

                if success:
                    log(f"User relocated gallery: {gallery_path} -> {new_path}", level="info", category="file_hosts")

                    # Refresh the table to show updated path
                    self._refresh_gallery_table()

                    # Check for sibling galleries that might also need updating
                    self._check_sibling_galleries(old_parent, os.path.dirname(new_path), gallery_path)

                    return new_path
                else:
                    QMessageBox.warning(self, "Error", "Failed to update gallery path in database.")
                    return None

        elif clicked == remove_btn:
            # Remove gallery from queue
            try:
                self.queue_manager.remove_items([gallery_path])
                self._refresh_gallery_table()
                log(f"User removed missing gallery from queue: {gallery_path}", level="info", category="file_hosts")
            except Exception as e:
                log(f"Error removing gallery: {e}", level="error", category="file_hosts")

        return None

    def _check_sibling_galleries(self, old_parent: str, new_parent: str, already_relocated: str):
        """Check if other galleries from the same parent folder need updating.

        Args:
            old_parent: Original parent folder
            new_parent: New parent folder where gallery was relocated
            already_relocated: Path that was just relocated (skip this one)
        """
        from PyQt6.QtWidgets import QMessageBox, QCheckBox, QVBoxLayout, QDialog, QDialogButtonBox, QLabel

        # Get all galleries that were in the same parent folder
        try:
            siblings = self.queue_manager.store.get_galleries_by_parent_folder(old_parent)
        except Exception as e:
            log(f"Error checking sibling galleries: {e}", level="error", category="gui")
            return

        # Filter to only those that are missing but exist in new location
        relocatable = []
        for gal in siblings:
            if gal['path'] == already_relocated:
                continue
            if os.path.isdir(gal['path']):
                continue  # Still exists, no need to relocate

            # Check if it exists under the new parent
            gallery_name = os.path.basename(gal['path'])
            potential_new_path = os.path.join(new_parent, gallery_name)
            if os.path.isdir(potential_new_path):
                relocatable.append({
                    'old_path': gal['path'],
                    'new_path': potential_new_path,
                    'name': gal['name'] or gallery_name
                })

        if not relocatable:
            return

        # Show dialog to update siblings
        dialog = QDialog(self)
        dialog.setWindowTitle("Update Related Galleries")
        layout = QVBoxLayout(dialog)

        layout.addWidget(QLabel(
            f"Found {len(relocatable)} other galleries from the same folder\n"
            f"that also exist in the new location.\n\n"
            f"Select which ones to update:"
        ))

        checkboxes = []
        for item in relocatable:
            cb = QCheckBox(f"{item['name']}")
            cb.setChecked(True)
            cb.setProperty("paths", (item['old_path'], item['new_path']))
            checkboxes.append(cb)
            layout.addWidget(cb)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            updated = 0
            for cb in checkboxes:
                if cb.isChecked():
                    old_path, new_path = cb.property("paths")
                    if self.queue_manager.store.update_gallery_path(old_path, new_path):
                        updated += 1

            if updated > 0:
                log(f"Batch relocated {updated} sibling galleries", level="info", category="file_hosts")
                self._refresh_gallery_table()

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
        from src.utils.logger import log

        # Skip during startup - icons are created via normal widget creation
        if not self._file_host_startup_complete:
            log(f"Skipping file host refresh during startup (complete={self._file_host_startup_complete})",
                level="debug", category="startup")
            return

        log(f"File host refresh triggered (startup_complete={self._file_host_startup_complete})",
            level="debug", category="startup")

        # Remove disabled workers from status widget
        self.worker_signal_handler._on_enabled_workers_changed(_enabled_worker_ids)

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

    def check_image_status_via_menu(self, paths: List[str]):
        """Check image online status for selected completed galleries.

        Delegates to ImageStatusChecker for the actual implementation.

        Args:
            paths: List of gallery paths to check
        """
        from src.gui.dialogs.image_status_checker import ImageStatusChecker

        if not paths:
            return

        # Check if rename_worker is available
        rename_worker = getattr(self.worker, 'rename_worker', None) if self.worker else None
        if not rename_worker:
            QMessageBox.warning(self, "Not Available", "Image status checking requires IMX.to login credentials.")
            return

        # Delegate to ImageStatusChecker
        # Clean up previous checker if exists
        if hasattr(self, '_image_status_checker') and self._image_status_checker:
            self._image_status_checker._cleanup_connections()

        # Store reference on self to prevent garbage collection before callbacks fire
        self._image_status_checker = ImageStatusChecker(
            parent=self,
            queue_manager=self.queue_manager,
            rename_worker=rename_worker,
            gallery_table=self.gallery_table
        )
        self._image_status_checker.check_galleries(paths)

    def start_all_uploads(self):
        """Start all ready uploads in currently visible rows.

        Delegates to GalleryQueueController.
        """
        self.gallery_queue_controller.start_all_uploads()

    def pause_all_uploads(self):
        """Reset all queued items back to ready (acts like Cancel for queued).

        Delegates to GalleryQueueController.
        """
        self.gallery_queue_controller.pause_all_uploads()
    
    def clear_completed(self):
        """Clear completed/failed uploads with confirmation.

        Delegates to GalleryQueueController.
        """
        self.gallery_queue_controller.clear_completed()
    
    def delete_selected_items(self):
        """Delete selected items from the queue.

        Delegates to GalleryQueueController.
        """
        self.gallery_queue_controller.delete_selected_items()
    

    
    def restore_settings(self):
        """Restore window settings from QSettings.

        Delegates to SettingsManager.restore_settings().
        """
        self.settings_manager.restore_settings()

    @pyqtSlot()
    def save_settings(self):
        """Save window settings to QSettings.

        Delegates to SettingsManager.save_settings().
        Can be called from worker threads via QMetaObject.invokeMethod.
        """
        self.settings_manager.save_settings()

    def save_table_settings(self):
        """Persist table column widths, visibility, and order to settings.

        Delegates to SettingsManager.save_table_settings().
        """
        self.settings_manager.save_table_settings()

    def restore_table_settings(self):
        """Restore table column widths, visibility, and order from settings.

        Delegates to SettingsManager.restore_table_settings().
        """
        self.settings_manager.restore_table_settings()

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
        """Handle when any quick setting is changed - auto-save immediately.

        Delegates to SettingsManager.on_setting_changed().
        """
        self.settings_manager.on_setting_changed()

    def save_upload_settings(self):
        """Save upload settings to INI file.

        Delegates to SettingsManager.save_upload_settings().
        """
        self.settings_manager.save_upload_settings()
    
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

    # -------------------------------------------------------------------------
    # Shutdown Helper Methods
    # -------------------------------------------------------------------------

    def _gather_active_transfers(self) -> dict:
        """Gather information about all active transfers.

        Returns:
            Dictionary containing:
            - uploading_galleries: List of currently uploading galleries
            - queued_galleries: List of galleries queued for upload
            - file_host_uploads: Dict mapping host_id to pending count
            - has_active: Boolean indicating if any active transfers exist
        """
        try:
            all_items = self.queue_manager.get_all_items()

            uploading = [
                item for item in all_items
                if item.status == "uploading"
            ]
            queued = [
                item for item in all_items
                if item.status == "queued"
            ]

            # Get file host uploads
            file_host_counts = {}
            if hasattr(self, 'file_host_manager') and self.file_host_manager:
                try:
                    for host_id in self.file_host_manager.get_enabled_hosts():
                        pending = self.queue_manager.store.get_pending_file_host_uploads(host_id)
                        if pending:
                            file_host_counts[host_id] = len(pending)
                except Exception as e:
                    log(f"Error getting file host uploads: {e}", level="warning", category="shutdown")

            return {
                'uploading_galleries': uploading,
                'queued_galleries': queued,
                'file_host_uploads': file_host_counts,
                'has_active': bool(uploading or queued or file_host_counts)
            }
        except Exception as e:
            log(f"Error gathering active transfers: {e}", level="error", category="shutdown")
            return {
                'uploading_galleries': [],
                'queued_galleries': [],
                'file_host_uploads': {},
                'has_active': False
            }

    def _minimize_to_tray(self):
        """Minimize application to system tray."""
        if hasattr(self, 'tray_icon') and self.tray_icon:
            self.hide()
            self.tray_icon.showMessage(
                "IMXuploader",
                "Minimized to tray. Uploads will continue in background.",
                QSystemTrayIcon.MessageIcon.Information,
                2000
            )
        else:
            # Fallback if tray not available
            self.showMinimized()

    @pyqtSlot()
    def _stop_all_timers(self):
        """Stop all timers and batchers (must run on main thread)."""
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
        if hasattr(self, '_upload_animation_timer') and self._upload_animation_timer.isActive():
            self._upload_animation_timer.stop()

    def closeEvent(self, event):
        """Handle window close with graceful shutdown.

        Shows confirmation dialog if active transfers exist,
        then displays shutdown progress with force quit option.
        """
        from src.gui.dialogs.shutdown_dialogs import (
            ExitConfirmationDialog, ShutdownDialog, ShutdownWorker
        )

        # Step 1: Gather active transfer info
        transfers = self._gather_active_transfers()

        # Step 2: Show confirmation if active transfers exist
        if transfers['has_active']:
            dialog = ExitConfirmationDialog(
                parent=self,
                uploading_galleries=transfers['uploading_galleries'],
                queued_galleries=transfers['queued_galleries'],
                file_host_uploads=transfers['file_host_uploads']
            )
            dialog.exec()
            result = dialog.get_result()

            if result == ExitConfirmationDialog.RESULT_CANCEL:
                event.ignore()
                return
            elif result == ExitConfirmationDialog.RESULT_MINIMIZE:
                event.ignore()
                self._minimize_to_tray()
                return
            # else: RESULT_EXIT - continue to shutdown

        # Save session time before shutdown
        self._save_session_time()

        # Step 3: Show shutdown progress dialog
        shutdown_dialog = ShutdownDialog(self)
        shutdown_worker = ShutdownWorker(self)

        # Connect signals with QueuedConnection for thread safety
        shutdown_worker.step_started.connect(
            shutdown_dialog.set_step,
            Qt.ConnectionType.QueuedConnection
        )
        shutdown_worker.step_completed.connect(
            shutdown_dialog.mark_step_complete,
            Qt.ConnectionType.QueuedConnection
        )
        shutdown_worker.shutdown_complete.connect(
            shutdown_dialog.accept,
            Qt.ConnectionType.QueuedConnection
        )
        shutdown_dialog.force_quit_requested.connect(
            shutdown_worker.force_stop
        )

        # Start shutdown worker
        shutdown_worker.start()

        # Show dialog (blocks until complete or force quit)
        shutdown_dialog.exec()

        # Cleanup dialog resources
        shutdown_dialog.cleanup()

        # Wait for worker to finish (with short timeout)
        if not shutdown_worker.wait(1000):
            log("ShutdownWorker did not finish in time, forcing exit",
                level="warning", category="shutdown")

        # Step 4: Accept close event
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
                    self.artifact_handler.regenerate_gallery_bbcode(gallery_path, new_template)
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
            except (AttributeError, RuntimeError):
                pass

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


# ==============================================================================
# ORPHANED MAIN FUNCTION - COMMENTED OUT
# ==============================================================================
# This main() function is never called. The actual application entry is in imxup.py.
# The file host initialization code (lines 7374-7391) has been moved to imxup.py
# around line 2611 where it runs AFTER window.show() but BEFORE app.exec().
#
# def main():
#     """Main function - EMERGENCY PERFORMANCE FIX: Show window first, load in background"""
#     app = QApplication(sys.argv)
#     app.setQuitOnLastWindowClosed(True)  # Exit when window closes
# 
#     # Show splash screen immediately
#     print(f"{timestamp()} Loading splash screen")
#     splash = SplashScreen()
#     splash.show()
#     splash.update_status("Initialization sequence")
# 
#     # Handle command line arguments
#     folders_to_add = []
#     if len(sys.argv) > 1:
#         # Accept multiple folder args (Explorer passes all selections to %V)
#         for arg in sys.argv[1:]:
#             if os.path.isdir(arg):
#                 folders_to_add.append(arg)
#         # If another instance is running, forward the first folder (server is single-path)
#         if folders_to_add and check_single_instance(folders_to_add[0]):
#             splash.finish_and_hide()
#             return
#     else:
#         # Check for existing instance even when no folders provided
#         if check_single_instance():
#             print(f"{timestamp()} WARNING: ImxUp GUI already running, attempting to bring existing instance to front.")
#             splash.finish_and_hide()
#             return
# 
#     splash.set_status("Qt")
# 
#     # Create main window with splash updates
#     window = ImxUploadGUI(splash)
# 
#     # Add folder from command line if provided
#     if folders_to_add:
#         window.add_folders(folders_to_add)
# 
#     # EMERGENCY FIX: Hide splash and show main window IMMEDIATELY (< 2 seconds)
#     splash.finish_and_hide()
#     window.show()
#     QApplication.processEvents()  # Force window to render NOW
# 
#     print(f"{timestamp()} Window visible - starting background gallery load")
#     log(f"Window shown, starting background gallery load", level="info", category="performance")
# 
#     # EMERGENCY FIX: Load galleries in background with non-blocking progress
#     # Phase 1: Load critical data (gallery names, status) - batched with yields
#     # Phase 2: Create expensive widgets in background
#     QTimer.singleShot(50, lambda: window._load_galleries_phase1())
# 
#     # Initialize file host workers AFTER GUI is loaded and displayed
#     if hasattr(window, "file_host_manager") and window.file_host_manager:
#         # Count enabled hosts BEFORE starting them (read from INI directly)
#         enabled_count = 0
#         for host_id in window.file_host_manager.config_manager.hosts:
#             if window.file_host_manager.get_file_host_setting(host_id, 'enabled', 'bool', False):
#                 enabled_count += 1
# 
#         window._file_host_startup_expected = enabled_count
#         if window._file_host_startup_expected == 0:
#             window._file_host_startup_complete = True
#             log("No file host workers enabled, skipping startup tracking", level="debug", category="startup")
#         else:
#             log(f"Expecting {window._file_host_startup_expected} file host workers to complete spinup",
#                 level="debug", category="startup")
# 
#         # Now start the workers
#         QTimer.singleShot(100, lambda: window.file_host_manager.init_enabled_hosts())
# 
#     try:
#         sys.exit(app.exec())
#     except KeyboardInterrupt:
# 
#         # Clean shutdown
#         if hasattr(window, 'worker') and window.worker:
#             window.worker.stop()
#         if hasattr(window, 'server') and window.server:
#             window.server.stop()
#         if hasattr(window, '_loading_abort'):
#             window._loading_abort = True  # Stop background loading
#         app.quit()
# 
# 
# 
# 
# 
# # ComprehensiveSettingsDialog moved to imxup_settings.py
# 
# # if __name__ == "__main__":
# #     main()
