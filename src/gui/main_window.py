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
from src.utils.archive_utils import is_archive_file


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
                'custom4': item.custom4 if item else ''
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


class DropEnabledTabBar(QTabBar):
    """Custom tab bar that accepts gallery drops and provides visual feedback"""
    
    # Signal for when galleries are dropped on a tab
    galleries_dropped = pyqtSignal(str, list)  # tab_name, gallery_paths
    # Signal for when tab order changes
    tab_order_changed = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._drag_highlight_index = -1
        # Connect to tab moved signal to enforce "All Tabs" position
        self.tabMoved.connect(self._on_tab_moved)
    
    def _on_tab_moved(self, from_index, to_index):
        """Ensure 'All Tabs' stays at position 0 and save tab order"""
        # If "All Tabs" was moved from position 0, move it back
        if from_index == 0 and self.tabText(to_index).split(' (')[0] == "All Tabs":
            self.moveTab(to_index, 0)
        # If something was moved to position 0 and it's not "All Tabs", find "All Tabs" and move it back
        elif to_index == 0 and self.tabText(0).split(' (')[0] != "All Tabs":
            # Find "All Tabs" and move it to position 0
            for i in range(self.count()):
                if self.tabText(i).split(' (')[0] == "All Tabs":
                    self.moveTab(i, 0)
                    break
        
        # Emit signal that tab order has changed
        self.tab_order_changed.emit()
    
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
            if not painter.isActive():
                # QPainter failed to begin - widget not ready for painting
                return
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
        self._restoring_tabs = False  # Flag to prevent saving during tab restoration

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
        self.new_tab_btn.setProperty("class", "new-tab-button")
        
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
        self.tab_bar.tab_order_changed.connect(self._save_tab_order)
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
            log(f"No tab manager available for TabbedGalleryWidget", level="warning")
            return

        # Block tab change signals from saving during restoration
        self._restoring_tabs = True

        # Clear existing tabs first
        while self.tab_bar.count() > 0:
            self.tab_bar.removeTab(0)
        
        # Add "All Tabs" first (position 0)
        self.tab_bar.addTab("All Tabs")
        
        # Get tabs from manager
        manager_tabs = self.tab_manager.get_visible_tab_names()
        
        # Restore saved tab order if available
        settings = QSettings()
        saved_order = settings.value("tabs/display_order", [])
        if saved_order and isinstance(saved_order, list):
            # Reorder manager_tabs to match saved order
            ordered_tabs = []
            for name in saved_order:
                if name in manager_tabs:
                    ordered_tabs.append(name)
            # Add any new tabs not in saved order
            for name in manager_tabs:
                if name not in ordered_tabs:
                    ordered_tabs.append(name)
            manager_tabs = ordered_tabs
        
        # Add all tabs from manager after "All Tabs"
        for tab_name in manager_tabs:
                self.tab_bar.addTab(tab_name)
        
        # Set current tab to the last active tab from manager, or Main if none
        if manager_tabs:
            # Try to set to last active tab (add 1 to account for "All Tabs" at position 0)
            last_active = self.tab_manager.last_active_tab
            if last_active in manager_tabs:
                index = manager_tabs.index(last_active) + 1  # +1 for "All Tabs" at position 0
                self.tab_bar.setCurrentIndex(index)
            else:
                # Default to first non-"All Tabs" tab (position 1)
                self.tab_bar.setCurrentIndex(1)
        else:
            # No tabs available, create a default Main tab after "All Tabs"
            log(f"No tabs available, creating default Main tab", level="warning")
            self.tab_bar.addTab("Main")
            self.tab_bar.setCurrentIndex(1)  # Select Main tab, not "All Tabs"
        
        # Update current_tab attribute to match the selected tab
        if self.tab_bar.count() > 0:
            tab_text = self.tab_bar.tabText(self.tab_bar.currentIndex())
            # Extract base tab name (remove count if present)
            base_tab_name = tab_text.split(' (')[0] if ' (' in tab_text else tab_text
            self.current_tab = base_tab_name

        # Update tooltips after refreshing tabs
        self._update_tab_tooltips()

        # Re-enable tab change signal saving after restoration is complete
        self._restoring_tabs = False
    
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
        #if switch_time > 16:
        #    print(f"Slow tab switch from '{old_tab}' to '{tab_name}': {switch_time:.1f}ms")

        # Save active tab to settings (excluding "All Tabs")
        # Don't save during tab restoration to prevent overwriting the saved preference
        if self.tab_manager and tab_name != "All Tabs" and not self._restoring_tabs:
            self.tab_manager.last_active_tab = tab_name
    
    def _save_tab_order(self):
        """Save current tab bar order to QSettings"""
        order = []
        for i in range(1, self.tab_bar.count()):  # Skip "All Tabs" at position 0
            tab_text = self.tab_bar.tabText(i)
            # Extract base tab name (remove count if present)
            tab_name = tab_text.split(' (')[0] if ' (' in tab_text else tab_text
            order.append(tab_name)
        settings = QSettings()
        settings.setValue("tabs/display_order", order)
    
    def _on_galleries_dropped(self, tab_name, gallery_paths):
        """Handle galleries being dropped on a tab"""
        log(f"_on_galleries_dropped called with tab_name='{tab_name}', {len(gallery_paths)} paths", level="debug")
        if not self.tab_manager or not gallery_paths:
            log(f"Early return - tab_manager={bool(self.tab_manager)}, gallery_paths={len(gallery_paths) if gallery_paths else 0}", level="debug")
            return
        
        try:
            # Move galleries to the target tab (tab_name is already clean from dropEvent)
            moved_count = self.tab_manager.move_galleries_to_tab(gallery_paths, tab_name)
            #print(f"DEBUG: move_galleries_to_tab returned moved_count={moved_count}", flush=True)
            
            # Update queue manager's in-memory items to match database
            #print(f"DEBUG: moved_count={moved_count}, has_queue_manager={hasattr(self, 'queue_manager')}, has_tab_manager={bool(self.tab_manager)}")
            if moved_count > 0 and hasattr(self, 'queue_manager') and self.tab_manager:
                updated_count = 0
                for path in gallery_paths:
                    item = self.queue_manager.get_item(path)
                    if item:
                        old_tab = item.tab_name
                        item.tab_name = tab_name
                        updated_count += 1
                        # Verify the change stuck
                        log(f"Drag-drop updated item {path} tab '{old_tab}' -> '{tab_name}' (item.tab_name is now '{item.tab_name}')", level="debug", category="ui")
                    else:
                        log(f" [ui] INFO: No item found for path: {path}")
                log(f"Updated {updated_count} in-memory items out of {len(gallery_paths)} paths", level="debug")
                
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
                log(f"DRAG-DROP PATH - Moved {moved_count} {gallery_word} to '{tab_name}' tab", level="debug", category="ui")
                
        except Exception as e:
            log(f"Error moving galleries to tab '{tab_name}': {e}", level="error")
            
    
    def _apply_filter(self, tab_name):
        """Apply filtering to show only rows belonging to the specified tab with intelligent caching"""
        if not self.tab_manager:
            # No filtering if no tab manager
            log(f"Error: No tab manager available for filtering", level="debug")
            for row in range(self.gallery_table.rowCount()):
                self.gallery_table.setRowHidden(row, False)
            return
        
        if not tab_name:
            log(f"No tab name specified for filtering", level="debug")
            return
        
        #print(f"Debug: Applying filter for tab: {tab_name}")
        
        start_time = time.time()
        row_count = self.gallery_table.rowCount()
        log(f"_apply_filter: rowCount() returned {row_count}", level="debug")
        
        if row_count == 0:
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

            name_item = self.gallery_table.item(row, GalleryTableWidget.COL_NAME)
            if name_item:
                path = name_item.data(Qt.ItemDataRole.UserRole)
                if tab_name == "All Tabs":
                    # Special "All Tabs" shows all galleries
                    should_show = True
                else:
                    # Check if in database OR in queue manager with matching tab
                    should_show = path in tab_paths_set
                    if not should_show:
                        # Try to get queue_manager from parent window
                        parent_window = self.window()
                        
                        if hasattr(parent_window, 'queue_manager'):
                            # Also check in-memory items that haven't been saved yet
                            qm = parent_window.queue_manager
                            
                            item = qm.get_item(path)
                            if item:
                                if item.tab_name == tab_name:
                                    should_show = True
                        else:
                            log(f"_apply_filter: parent_window has no queue_manager attribute", level="warning")
                    
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
            
    def _continue_filter(self, start_row, total_rows, tab_name, tab_paths_set):
        """Continue filtering from where we left off to avoid blocking main thread"""
        TIME_BUDGET = 0.008  # Smaller budget for continuation
        start_time = time.time()
        
        for row in range(start_row, total_rows):
            if time.time() - start_time > TIME_BUDGET:
                # Schedule next batch if needed
                QTimer.singleShot(1, lambda: self._continue_filter(row, total_rows, tab_name, tab_paths_set))
                return
                
            name_item = self.gallery_table.item(row, GalleryTableWidget.COL_NAME)
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
        """Get tab paths - CACHING DISABLED FOR DEBUGGING"""
        # Special case for "All Tabs" - return empty set to show all
        if tab_name == "All Tabs":
            return set()
        
        if not self.tab_manager:
            log(f"No tab manager available for loading tab galleries", level="warning")
            return set()
        
        # CACHING DISABLED - always load fresh from database
        try:
            tab_galleries = self.tab_manager.load_tab_galleries(tab_name)
            tab_paths_set = {gallery.get('path') for gallery in tab_galleries if gallery.get('path')}
            #print(f"Debug: Loaded {len(tab_paths_set)} galleries for tab '{tab_name}' (NO CACHE)")
        except Exception as e:
            log(f"Error loading galleries for tab '{tab_name}': {e}", level="error")
            tab_paths_set = set()
        
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
                
            name_item = self.gallery_table.item(row, GalleryTableWidget.COL_NAME)
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
            return  # Don't allow renaming system tabs
        
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
            
            #duplicate_action = menu.addAction("Duplicate Tab")
            #duplicate_action.triggered.connect(lambda: self._duplicate_tab(base_tab_name))
            
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

    def refresh_filter(self):
        """Refresh the current filter (call after gallery assignments change)"""
        if not self.current_tab:
            log("Warning: No current tab set for filter refresh", level="warning")
            return

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
    
    def _setup_tab_styling(self, theme_mode='dark'):
        """Setup special tab data attributes not handled by styles.qss"""

        # Only apply special data attribute styling - main styling comes from styles.qss
        special_style = """
            QTabBar::tab[data-tab-type="system"] {
                font-style: italic;
            }
            QTabBar::tab[data-modified="true"] {
                color: %s;
            }
            QTabBar::tab[data-drag-highlight="true"] {
                border: 2px solid #3498db;
                background: %s;
            }
        """ % (
            "#f39c12" if theme_mode == 'dark' else "#e67e22",  # modified color
            "#404040" if theme_mode == 'dark' else "#e3f2fd"   # drag highlight background
        )

        self.tab_bar.setStyleSheet(special_style)
        self._update_new_tab_button_style(theme_mode == 'dark')
    
    def _update_new_tab_button_style(self, is_dark=False):
        """Update the new tab button styling to match current theme"""
        # Force style update to apply theme from styles.qss
        style = self.new_tab_btn.style()
        if style:
            style.polish(self.new_tab_btn)
    
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
        
        # F2: Rename selected gallery
        rename_shortcut = QShortcut(QKeySequence("F2"), self)
        rename_shortcut.activated.connect(self._rename_selected_gallery)

        # Ctrl+,: Open Comprehensive Settings
        settings_shortcut = QShortcut(QKeySequence("Ctrl+,"), self)
        settings_shortcut.activated.connect(self._open_settings_from_shortcut)

        # Ctrl+.: Show keyboard shortcuts help
        help_shortcuts_shortcut = QShortcut(QKeySequence("Ctrl+."), self)
        help_shortcuts_shortcut.activated.connect(self._show_help_from_shortcut)
    
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
            log(f"_update_tab_tooltips already running, skipping recursion", level="debug")
            return
        
        # Block ALL calls during initialization to prevent infinite loops
        if hasattr(self, '_initializing') and self._initializing:
            log("Still initializing, skipping _update_tab_tooltips", level="debug")
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
                        # Count from in-memory queue_manager instead of database
                        # This ensures counts match what's actually displayed in the table
                        parent_window = self.parent()
                        while parent_window and not hasattr(parent_window, 'queue_manager'):
                            parent_window = parent_window.parent()

                        if parent_window and hasattr(parent_window, 'queue_manager'):
                            # Count items in memory that belong to this tab
                            all_items = parent_window.queue_manager.get_all_items()
                            gallery_count = sum(1 for item in all_items if item.tab_name == base_name)
                            # Count active uploads
                            active_count = sum(1 for item in all_items
                                             if item.tab_name == base_name
                                             and item.status in ['uploading', 'pending'])
                        else:
                            # Fallback to database if queue_manager not accessible
                            galleries = self.tab_manager.load_tab_galleries(base_name)
                            gallery_count = len(galleries)
                            active_count = sum(1 for g in galleries if g.get('status') in ['uploading', 'pending'])
                    
                    # Update tab text with count
                    old_text = self.tab_bar.tabText(i)
                    new_text = f"{base_name} ({gallery_count})"
                    if old_text != new_text:  # Only update if changed
                        self.tab_bar.setTabText(i, new_text)
                
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
                            "Double-click to rename\n"
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

    def _rename_selected_gallery(self):
        """Rename selected gallery via F2 shortcut"""
        # Get the current gallery table
        table_widget = None
        if hasattr(self, 'gallery_table'):
            if hasattr(self.gallery_table, 'gallery_table'):
                # Tabbed widget case
                table_widget = self.gallery_table.gallery_table
            else:
                # Direct table case
                table_widget = self.gallery_table

        if not table_widget:
            return

        # Get currently selected row
        current_row = table_widget.currentRow()
        if current_row < 0:
            return

        # Get the path from the name column (column 1) like the context menu does
        name_item = table_widget.item(current_row, GalleryTableWidget.COL_NAME)
        if not name_item:
            return

        path = name_item.data(Qt.ItemDataRole.UserRole)
        if path:
            self.rename_gallery(path)

    def _open_settings_from_shortcut(self):
        """Open comprehensive settings via Ctrl+, shortcut"""
        # Find the main window by traversing up the widget hierarchy
        widget = self
        while widget and not hasattr(widget, 'open_comprehensive_settings'):
            widget = widget.parent()

        if widget and hasattr(widget, 'open_comprehensive_settings'):
            widget.open_comprehensive_settings()

    def _show_help_from_shortcut(self):
        """Show keyboard shortcuts help via Ctrl+. shortcut"""
        # Find the main window by traversing up the widget hierarchy
        widget = self
        while widget and not hasattr(widget, 'show_help_shortcuts_tab'):
            widget = widget.parent()

        if widget and hasattr(widget, 'show_help_shortcuts_tab'):
            widget.show_help_shortcuts_tab()

    def _sort_tabs_alphabetically(self):
        """Sort user tabs alphabetically (excluding All Tabs and Main)"""
        # Get all tab names except system tabs
        tab_names = []
        for i in range(self.tab_bar.count()):
            name = self.tab_bar.tabText(i)
            # Extract base tab name (remove count if present)
            base_name = name.split(' (')[0] if ' (' in name else name
            if base_name not in ["All Tabs", "Main"]:
                tab_names.append(name)
        
        if len(tab_names) <= 1:
            return
        
        # Sort alphabetically
        tab_names.sort()
        
        # Rebuild tab bar with sorted order
        current_tab = self.current_tab
        
        # Remove all non-system tabs (preserve All Tabs and Main)
        for i in range(self.tab_bar.count() - 1, -1, -1):
            tab_text = self.tab_bar.tabText(i)
            # Extract base tab name (remove count if present)
            base_name = tab_text.split(' (')[0] if ' (' in tab_text else tab_text
            if base_name not in ["All Tabs", "Main"]:
                self.tab_bar.removeTab(i)
        
        # Add sorted tabs
        for name in tab_names:
            self.tab_bar.addTab(name)
        
        # Restore current tab selection
        if current_tab in tab_names:
            self.switch_to_tab(current_tab)
        
        self._update_tab_tooltips()
    
    def _find_tab_index(self, tab_name):
        """Find the index of a tab by name"""
        for i in range(self.tab_bar.count()):
            tab_text = self.tab_bar.tabText(i)
            base_name = tab_text.split(' (')[0] if ' (' in tab_text else tab_text
            if base_name == tab_name:
                return i
        return -1
    
    def _close_all_user_tabs(self):
        """Close all user tabs, keeping only system tabs (All Tabs and Main)"""
        from PyQt6.QtWidgets import QMessageBox
        
        user_tabs = []
        for i in range(self.tab_bar.count()):
            tab_text = self.tab_bar.tabText(i)
            # Extract base tab name (remove count if present)
            base_name = tab_text.split(' (')[0] if ' (' in tab_text else tab_text
            if base_name not in ["All Tabs", "Main"]:
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
                if base_name not in ["All Tabs", "Main"]:
                    self._delete_tab_without_confirmation(i, tab_name)
            
            # Switch to Main tab (position 1, since All Tabs is at position 0)
            main_index = self._find_tab_index("Main")
            if main_index >= 0:
                self.tab_bar.setCurrentIndex(main_index)
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


class NumericColumnDelegate(QStyledItemDelegate):
    """Delegate for numeric/timestamp columns with smaller font (0.95em) and right alignment"""

    def paint(self, painter, option, index):
        # Create a copy of the option and scale font to 0.95 of current size
        new_option = QStyleOptionViewItem(option)
        font = new_option.font
        if font.pointSizeF() > 0:
            font.setPointSizeF(font.pointSizeF() * 0.95)
        elif font.pixelSize() > 0:
            font.setPixelSize(int(font.pixelSize() * 0.95))
        new_option.font = font

        # Right-align text
        new_option.displayAlignment = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter

        # Paint with modified options
        super().paint(painter, new_option, index)


class GalleryTableWidget(QTableWidget):
    """Table widget for gallery queue with resizable columns, sorting, and action buttons
    """

    # Type hints for attributes set externally by parent (ImxUploadGUI)
    queue_manager: 'QueueManager'  # Set by parent after instantiation
    tab_manager: Optional['TabManager']  # Set by parent after instantiation
    icon_manager: Optional['IconManager']  # Set by parent after instantiation

    # Column definitions - single source of truth for all column metadata
    COLUMNS = [
        # (index, name, header_label, default_width, resize_mode, hidden_by_default, header_align_left)
        (0,  'ORDER',       '#',            40,  'Fixed',       False, False),
        (1,  'NAME',        'gallery name', 300, 'Interactive', False, True),
        (2,  'UPLOADED',    'uploaded',     100, 'Interactive', False, False),
        (3,  'PROGRESS',    'progress',     200, 'Interactive', False, False),
        (4,  'STATUS',      'status',       40,  'Interactive', False, False),
        (5,  'STATUS_TEXT', 'status text',  100, 'Interactive', True,  False),
        (6,  'ADDED',       'added',        120, 'Interactive', False, False),
        (7,  'FINISHED',    'finished',     120, 'Interactive', False, False),
        (8,  'ACTION',      'action',       50,  'Interactive', False, True),
        (9,  'SIZE',        'size',         110, 'Interactive', False, False),
        (10, 'TRANSFER',    'transfer',     120, 'Interactive', True,  False),
        (11, 'RENAMED',     'renamed',      40,  'Interactive', False, True),
        (12, 'TEMPLATE',    'template',     140, 'Interactive', False, True),
        (13, 'GALLERY_ID',  'gallery_id',   90,  'Interactive', True,  True),
        (14, 'CUSTOM1',     'Custom1',      100, 'Interactive', True,  True),
        (15, 'CUSTOM2',     'Custom2',      100, 'Interactive', True,  True),
        (16, 'CUSTOM3',     'Custom3',      100, 'Interactive', True,  True),
        (17, 'CUSTOM4',     'Custom4',      100, 'Interactive', True,  True),
    ]

    # Create class attributes dynamically from COLUMNS definition
    for idx, name, *_ in COLUMNS:
        locals()[f'COL_{name}'] = idx

    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Drag and drop state
        self._drag_start_position = None
        self._is_dragging = False
        
        # Enable drag and drop for internal gallery moves and file drops
        self.setDragEnabled(True)
        self.setAcceptDrops(True)  # Accept drops for adding files to galleries
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        
        # Setup table from COLUMNS definition
        self.setColumnCount(len(self.COLUMNS))
        self.setHorizontalHeaderLabels([col[2] for col in self.COLUMNS])
        
        # Set icon size for Status column icons
        self.setIconSize(QSize(20, 20))
        try:
            # Left-align the 'gallery name' header specifically
            hn = self.horizontalHeaderItem(1)
            if hn:
                hn.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                # Gallery name column gets slightly larger font
                hn.setFont(QFont(hn.font().family(), 9))
            
            # Left-align headers as specified in COLUMNS definition
            for idx, name, label, width, resize_mode, hidden, align_left in self.COLUMNS:
                if align_left:
                    header_item = self.horizontalHeaderItem(idx)
                    if header_item:
                        header_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise
        
        # Configure columns from COLUMNS definition
        header = self.horizontalHeader()
        header.setStretchLastSection(False)
        try:
            # Disable cascading resizes for Excel-like behavior (independent column resizing)
            header.setCascadingSectionResizes(False)
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise

        # Set resize modes from COLUMNS definition
        for idx, _, _, _, resize_mode, _, _ in self.COLUMNS:
            mode = getattr(QHeaderView.ResizeMode, resize_mode)
            header.setSectionResizeMode(idx, mode)
        try:
            # Allow headers to shrink more
            header.setMinimumSectionSize(24)
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise
        # Keep widths fixed unless user drags; prevent automatic shuffling
        try:
            header.setSectionsClickable(True)
            header.setHighlightSections(False)
            header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise
        
        # Set column widths and visibility from COLUMNS definition
        for idx, _, _, width, _, hidden, _ in self.COLUMNS:
            self.setColumnWidth(idx, width)
            if hidden:
                self.setColumnHidden(idx, True)

        # Apply numeric column delegate for smaller font and right alignment
        numeric_delegate = NumericColumnDelegate(self)
        for col in [self.COL_UPLOADED, self.COL_ADDED, self.COL_FINISHED, self.COL_SIZE, self.COL_TRANSFER, self.COL_STATUS_TEXT, self.COL_GALLERY_ID, self.COL_CUSTOM1, self.COL_CUSTOM2, self.COL_CUSTOM3, self.COL_CUSTOM4]:
            self.setItemDelegateForColumn(col, numeric_delegate)

        # Make Status and Action columns non-resizable
        header = self.horizontalHeader()
        #header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)  # Status column
        #header.setSectionResizeMode(7, QHeaderView.ResizeMode.Fixed)  # Action column
        
        # Enable sorting but start with no sorting (insertion order)
        self.setSortingEnabled(True)
        self.horizontalHeader().setSortIndicatorShown(False)  # No initial sort indicator
        
        # Let styles.qss handle the styling for proper theme support
        self.setShowGrid(True)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(24)  # Slightly shorter rows
        
        # Column visibility is managed by window settings; defaults applied in restore_table_settings

        # Disable auto-expansion behavior; make columns behave like Excel (no auto-resize of others)
        try:
            header.setSectionsMovable(True)
            header.setStretchLastSection(False)
            self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise

        # Connect vertical scrollbar to refresh icons when scrolling
        self.verticalScrollBar().valueChanged.connect(self._on_scroll)

        # Track if we need full icon refresh (after theme change)
        self._needs_full_icon_refresh = False

    def _on_scroll(self):
        """Refresh icons for newly visible rows when scrolling (only if needed after theme change)"""
        if self._needs_full_icon_refresh:
            # Find parent ImxUploadGUI to call refresh
            parent = self.parent()
            while parent and not isinstance(parent, QWidget):
                parent = parent.parent()
            if parent:
                # Refresh both status icons and renamed icons for newly visible rows
                if hasattr(parent, 'refresh_all_status_icons'):
                    parent.refresh_all_status_icons()
                if hasattr(parent, '_refresh_button_icons'):
                    parent._refresh_button_icons()
                # Note: flag stays True so scrolling continues to refresh new rows
                # It will be cleared when all rows are eventually visible or manually cleared

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
        #elif event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
        #    # Handle Enter key for completed items
        #    self.handle_enter_or_double_click()
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
            name_item = self.item(row, GalleryTableWidget.COL_NAME)
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

        # Create font for text measurement
        font = QFont()
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
        painter.setPen(Qt.GlobalColor.white)
        painter.drawText(10, text_height + 2, text)
        painter.end()
        
        return pixmap
    
    def resizeEvent(self, event):
        """Excel-like behavior - columns don't auto-resize on window resize.
        User manually resizes columns, horizontal scrollbar appears if needed."""
        super().resizeEvent(event)
        # Removed auto-resize logic to maintain Excel-like independent column behavior
        # Columns now stay at their user-defined widths regardless of window size
    
    def handle_enter_or_double_click(self):
        """Handle Enter key or double-click for viewing items (BBCode for completed, file manager for others)"""
        current_row = self.currentRow()
        if current_row >= 0:
            name_item = self.item(current_row, GalleryTableWidget.COL_NAME)
            if name_item:
                path = name_item.data(Qt.ItemDataRole.UserRole)
                if path:
                    # Find the main GUI window and use the smart view handler
                    widget = self
                    while widget:
                        if hasattr(widget, 'handle_view_button'):
                            widget.handle_view_button(path)
                            return
                        widget = widget.parent()
    
    def handle_copy_bbcode(self):
        """Handle Ctrl+C for copying BBCode for all selected completed items"""
        # Collect selected completed item paths
        selected_rows = sorted({it.row() for it in self.selectedItems()})
        paths = []
        for row in selected_rows:
            name_item = self.item(row, GalleryTableWidget.COL_NAME)
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
                name_item = self.item(row, GalleryTableWidget.COL_NAME)
                if name_item:
                    path = name_item.data(Qt.ItemDataRole.UserRole)
                    if path:
                        selected_paths.append(path)

        # Use context menu helper to create the menu
        if hasattr(self, 'context_menu_helper'):
            # Find the main window reference
            widget = self
            while widget and not hasattr(widget, 'queue_manager'):
                widget = widget.parent()
            
            if widget:
                self.context_menu_helper.main_window = widget
                menu = self.context_menu_helper.create_context_menu(position, selected_paths)
                
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
                log(f"Right-click move_galleries_to_tab returned moved_count={moved_count}", level="debug", category="queue")
                
                # Update queue manager's in-memory items to match database
                log(f"Checking conditions - moved_count={moved_count}, has_queue_manager={hasattr(tabbed_widget, 'queue_manager')}, has_tab_manager={bool(tabbed_widget.tab_manager)}", level="debug", category="queue")
                
                # Find the widget with queue_manager
                queue_widget = tabbed_widget
                while queue_widget and not hasattr(queue_widget, 'queue_manager'):
                    queue_widget = queue_widget.parent()
                
                log(f"Found queue_widget={bool(queue_widget)}, has_queue_manager={hasattr(queue_widget, 'queue_manager') if queue_widget else False}", level="debug", category="queue")
                
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
                            log(f"Right-click updated item {path} tab: '{old_tab}' -> '{target_tab}' (item.tab_name is now '{item.tab_name}')", level="debug", category="ui")
                
                # Invalidate caches and refresh display
                if moved_count > 0:
                    #log(f"RIGHT-CLICK calling invalidate_tab_cache() on {type(tabbed_widget).__name__}", level="debug", category="ui")
                    
                    # Check database counts BEFORE cache invalidation
                    #main_count_before = len(tabbed_widget.tab_manager.load_tab_galleries('Main'))
                    #target_count_before = len(tabbed_widget.tab_manager.load_tab_galleries(target_tab))
                    #log(f"RIGHT-CLICK BEFORE invalidate - Main={main_count_before}, {target_tab}={target_count_before}", level="debug", category="ui")
                    
                    tabbed_widget.tab_manager.invalidate_tab_cache()

                    # Check database counts AFTER cache invalidation
                    #main_count_after = len(tabbed_widget.tab_manager.load_tab_galleries('Main'))
                    #target_count_after = len(tabbed_widget.tab_manager.load_tab_galleries(target_tab))

                    tabbed_widget.refresh_filter()

                    # Update tab tooltips to reflect new counts
                    if hasattr(tabbed_widget, '_update_tab_tooltips'):
                        tabbed_widget._update_tab_tooltips()
                    log(f"RIGHT-CLICK PATH - Moved {moved_count} galler{'y' if moved_count == 1 else 'ies'} to '{target_tab}' tab", level="debug", category="ui")
                    
            except Exception as e:
                print(e)
                log(f"Error moving galleries to tab '{target_tab}': {e}", level="error")
                
    
    def manage_gallery_files(self, path: str):
        """Open the file manager dialog for a gallery"""
        # Find the parent ImxUploadGUI window
        parent_window = self
        while parent_window and not isinstance(parent_window, QMainWindow):
            parent_window = parent_window.parent()
        
        if parent_window:
            # Create and show the file manager dialog
            from src.gui.dialogs.gallery_file_manager import GalleryFileManagerDialog
            dialog = GalleryFileManagerDialog(path, parent_window.queue_manager, parent_window)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                # Refresh the gallery display if files were modified
                if hasattr(parent_window, 'refresh_filter'):
                    parent_window.refresh_filter()

    def rename_gallery(self, path: str):
        """Handle gallery rename from context menu"""
        # Find the parent ImxUploadGUI window
        parent_window = self
        while parent_window and not isinstance(parent_window, QMainWindow):
            parent_window = parent_window.parent()

        if not parent_window:
            return

        item = parent_window.queue_manager.get_item(path)
        if not item:
            return

        current_name = item.name or os.path.basename(path)
        from PyQt6.QtWidgets import QInputDialog

        # Create a properly sized input dialog
        dialog = QInputDialog(parent_window)
        dialog.setWindowTitle("Rename Gallery")
        dialog.setLabelText("New gallery name:")
        dialog.setTextValue(current_name)

        # Make dialog wide enough to show the full gallery name
        # Calculate width based on text length, with reasonable min/max bounds
        text_width = len(current_name) * 8  # Approximate character width
        dialog_width = max(400, min(800, text_width + 100))  # Min 400px, max 800px
        dialog.resize(dialog_width, dialog.sizeHint().height())

        ok = dialog.exec()
        new_name = dialog.textValue()

        if ok and new_name and new_name.strip() != current_name:
            new_name = new_name.strip()
            # Update in queue manager
            if parent_window.queue_manager.update_gallery_name(path, new_name):
                # Update table display for this specific item
                if hasattr(parent_window, '_update_specific_gallery_display'):
                    parent_window._update_specific_gallery_display(path)
                # Log the change
                log(f"Renamed gallery to: {new_name}", level="debug")

                # Auto-regenerate BBCode (setting checked inside function)
                try:
                    parent_window.regenerate_bbcode_for_gallery(path)
                    # Only log if regeneration actually happened (could check if enabled first)
                    from imxup import load_user_defaults
                    defaults = load_user_defaults()
                    if defaults.get('auto_regenerate_bbcode', True):
                        log(f"BBCode regenerated for renamed gallery: {new_name}", level="debug")
                except Exception as e:
                    log(f"Error auto-regenerating BBCode for renamed gallery {path}: {e}", level="error")

    def dragEnterEvent(self, event):
        """Handle drag enter events"""
        # Check if we're dragging files
        if event.mimeData().hasUrls():
            # Check if any URLs are image files
            has_images = False
            for url in event.mimeData().urls():
                path = url.toLocalFile()
                if os.path.isfile(path) and path.lower().endswith(IMAGE_EXTENSIONS):
                    has_images = True
                    break
            
            if has_images:
                event.acceptProposedAction()
                return
        
        # Otherwise, use default handling for gallery moves
        super().dragEnterEvent(event)
    
    def dragMoveEvent(self, event):
        """Handle drag move events"""
        if event.mimeData().hasUrls():
            # Highlight the row under cursor
            pos = event.position().toPoint()
            index = self.indexAt(pos)
            if index.isValid():
                event.acceptProposedAction()
            else:
                event.ignore()
        else:
            super().dragMoveEvent(event)
    
    def dropEvent(self, event):
        """Handle drop events - both gallery moves and file drops"""
        # Check if we're dropping files
        if event.mimeData().hasUrls():
            # Get the row where files are being dropped
            pos = event.position().toPoint()
            index = self.indexAt(pos)
            
            if index.isValid():
                row = index.row()
                # Get the gallery path from the row
                name_item = self.item(row, GalleryTableWidget.COL_NAME)
                if name_item:
                    gallery_path = name_item.data(Qt.ItemDataRole.UserRole)
                    if gallery_path:
                        # Filter for image files
                        image_files = []
                        for url in event.mimeData().urls():
                            path = url.toLocalFile()
                            if os.path.isfile(path) and path.lower().endswith(IMAGE_EXTENSIONS):
                                image_files.append(path)
                        
                        if image_files:
                            # Ask for confirmation
                            gallery_name = os.path.basename(gallery_path)
                            file_word = "file" if len(image_files) == 1 else "files"
                            reply = QMessageBox.question(
                                self,
                                "Add Files to Gallery",
                                f"Add {len(image_files)} {file_word} to '{gallery_name}'?",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                            )
                            
                            if reply == QMessageBox.StandardButton.Yes:
                                # Add files to the gallery
                                self.add_files_to_gallery(gallery_path, image_files)
                                event.acceptProposedAction()
                                return
            
            event.ignore()
        else:
            # Default handling for gallery moves
            super().dropEvent(event)
    
    def add_files_to_gallery(self, gallery_path: str, files: List[str]):
        """Add files to a gallery"""
        import shutil
        
        # Find the parent ImxUploadGUI window to access queue manager
        parent_window = self
        while parent_window and not isinstance(parent_window, QMainWindow):
            parent_window = parent_window.parent()
        
        if not parent_window or not hasattr(parent_window, 'queue_manager'):
            return
        
        queue_manager = parent_window.queue_manager
        gallery_item = queue_manager.get_item(gallery_path)
        
        if not gallery_item:
            return
        
        # Copy files to gallery folder
        added_count = 0
        failed_files = []
        
        for filepath in files:
            filename = os.path.basename(filepath)
            dest_path = os.path.join(gallery_path, filename)
            
            try:
                # Copy file if not already there
                if filepath != dest_path:
                    shutil.copy2(filepath, dest_path)
                added_count += 1
            except Exception as e:
                failed_files.append((filename, str(e)))
        
        # Update gallery based on status
        if added_count > 0:
            # Always trigger additive rescan to properly detect and count new files
            queue_manager.rescan_gallery_additive(gallery_path)
            
            # For completed galleries, also mark as incomplete so they can be resumed
            if gallery_item.status == "completed":
                gallery_item.status = "incomplete"
                queue_manager.update_item_status(gallery_path, "incomplete")
            
            # Show success message
            gallery_name = os.path.basename(gallery_path)
            log(f"Added {added_count} file(s) to {gallery_name}", level="info")
            
            # Refresh display to show updated status
            if hasattr(parent_window, 'refresh_filter'):
                parent_window.refresh_filter()
            elif hasattr(parent_window, '_update_specific_gallery_display'):
                parent_window._update_specific_gallery_display(gallery_path)
        
        # Show error if any files failed
        if failed_files:
            error_msg = f"Failed to add {len(failed_files)} file(s):\n"
            for filename, error in failed_files[:5]:  # Show first 5 errors
                error_msg += f"\n• {filename}: {error}"
            if len(failed_files) > 5:
                error_msg += f"\n... and {len(failed_files) - 5} more"
            QMessageBox.warning(self, "Some Files Failed", error_msg)
    
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
            name_item = self.item(row, GalleryTableWidget.COL_NAME)
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
        started_paths = []
        # Use batch context to group all database saves into a single transaction
        with widget.queue_manager.batch_updates():
            for path in paths_in_order:
                if widget.queue_manager.start_item(path):
                    started += 1
                    started_paths.append(path)
        if started:
            log(f"Started {started} selected item(s)", level="info")
            # Update only the affected rows instead of full table refresh
            if hasattr(widget, '_update_specific_gallery_display'):
                for path in started_paths:
                    widget._update_specific_gallery_display(path)
    
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
            # Use batch processing for multiple cancellations to prevent GUI hang
            if len(queued_paths) > 1:
                widget.cancel_multiple_items(queued_paths)
            else:
                widget.cancel_single_item(queued_paths[0])
    
    def retry_selected_via_menu(self, failed_paths):
        """Retry failed uploads for selected items"""
        widget = self
        while widget and not hasattr(widget, 'queue_manager'):
            widget = widget.parent()
        
        if widget and hasattr(widget, 'queue_manager'):
            for path in failed_paths:
                try:
                    widget.queue_manager.retry_failed_upload(path)
                    item = widget.queue_manager.get_item(path)
                    gallery_name = item.name if item else os.path.basename(path)
                    log(f"Retrying upload for {gallery_name}", level="info")
                except Exception as e:
                    log(f"Error retrying {path}: {e}", level="info")
    
    def rescan_additive_via_menu(self, paths):
        """Smart rescan - only detect new images, preserve existing uploads"""
        widget = self
        while widget and not hasattr(widget, 'queue_manager'):
            widget = widget.parent()
        
        if widget and hasattr(widget, 'queue_manager'):
            for path in paths:
                try:
                    # Use the worker queue instead of blocking direct scan
                    widget.queue_manager._scan_queue.put(path)
                    item = widget.queue_manager.get_item(path)
                    gallery_name = item.name if item else os.path.basename(path)
                    log(f"Queued {gallery_name} for rescan", level="info")
                except Exception as e:
                    log(f"Error queuing scan for {path}: {e}", level="info")

    def rescan_all_items_via_menu(self, paths):
        """Rescan all items in gallery - refresh failed/incomplete items while preserving successful uploads"""
        widget = self
        while widget and not hasattr(widget, 'queue_manager'):
            widget = widget.parent()
        
        if widget and hasattr(widget, 'queue_manager'):
            for path in paths:
                try:
                    # Use the worker queue instead of blocking methods
                    widget.queue_manager._scan_queue.put(path)
                    item = widget.queue_manager.get_item(path)
                    gallery_name = item.name if item else os.path.basename(path)
                    log(f"Queued {gallery_name} for complete rescan", level="info")
                except Exception as e:
                    log(f"Error queuing rescan for {path}: {e}", level="error")
    
    def reset_gallery_via_menu(self, paths):
        """Complete gallery reset with confirmation dialog"""
        from PyQt6.QtWidgets import QMessageBox
        
        # Show confirmation dialog
        count = len(paths)
        gallery_word = "gallery" if count == 1 else "galleries"
        
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setWindowTitle("Reset Gallery")
        msg.setText(f"Reset {count} {gallery_word}?")
        msg.setInformativeText(
            "This will permanently clear all upload progress and rescan from scratch.\n"
            "Any existing gallery links will be lost.\n\n"
            "Use this when you've replaced/renamed files or want to re-upload everything."
        )
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        msg.setDefaultButton(QMessageBox.StandardButton.Cancel)
        
        if msg.exec() == QMessageBox.StandardButton.Yes:
            widget = self
            while widget and not hasattr(widget, 'queue_manager'):
                widget = widget.parent()
            
            if widget and hasattr(widget, 'queue_manager'):
                for path in paths:
                    try:
                        widget.queue_manager.reset_gallery_complete(path)
                        item = widget.queue_manager.get_item(path)
                        gallery_name = item.name if item else os.path.basename(path)
                        log(f"Reset {gallery_name} - starting fresh scan", level="info")
                    except Exception as e:
                        log(f"Error resetting {path}: {e}", level="info", category="queue")
                
                # Force refresh of the display to show scanning status
                if hasattr(widget, 'refresh_filter'):
                    QTimer.singleShot(200, widget.refresh_filter)
                
                # Trigger scanning using the worker queue for each reset path
                for path in paths:
                    try:
                        # Add to scan queue to trigger actual scanning
                        widget.queue_manager._scan_queue.put(path)
                        log(f"Added {path} to scan queue after reset", level="debug", category="queue")
                    except Exception as e:
                        log(f"Error queuing scan for {path}: {e}", level="info", category="queue")
    
    def rescan_selected_via_menu(self, scan_failed_paths):
        """Legacy method - redirect to additive rescan"""
        self.rescan_additive_via_menu(scan_failed_paths)

    def copy_bbcode_via_menu_multi(self, paths):
        """Copy BBCode for multiple completed items (concatenated with separators)"""
        # Find the main GUI window
        widget = self
        while widget and not hasattr(widget, 'queue_manager'):
            widget = widget.parent()
        if not widget:
            log(f"No widget with queue_manager found", level="warning", category="fileio")
            return
        # Aggregate BBCode contents; reuse copy function to centralize path lookup
        contents = []
        for path in paths:
            item = widget.queue_manager.get_item(path)
            if not item:
                log(f"No item found for path: {path}", level="debug")
                continue
            #print(f"DEBUG: Item status: {item.status}, gallery_id: {getattr(item, 'gallery_id', 'MISSING')}")
            if item.status != "completed":
                continue
            # Inline read similar to copy_bbcode_to_clipboard to avoid changing it
            folder_name = os.path.basename(path)
            # Use cached functions or fallbacks
            if hasattr(widget, '_get_central_storage_path'):
                base_path = widget._get_central_storage_path()
                central_path = os.path.join(base_path, "galleries")
                #print(f"DEBUG: Using widget._get_central_storage_path: {central_path}")
            else:
                central_path = os.path.expanduser("~/.imxup/galleries")
                log(f"Using fallback central_path: {central_path}", level="debug")
            if item.gallery_id and (item.name or folder_name):
                #print(f"DEBUG: Has gallery_id and name, item.name: {getattr(item, 'name', 'MISSING')}")
                if hasattr(widget, '_build_gallery_filenames'):
                    _, _, bbcode_filename = widget._build_gallery_filenames(item.name or folder_name, item.gallery_id)
                else:
                    # No sanitization - only rename worker should sanitize
                    gallery_name = item.name or folder_name
                    bbcode_filename = f"{gallery_name}_{item.gallery_id}_bbcode.txt"
                    log(f"Using fallback filename: {bbcode_filename}", level="debug")
                central_bbcode = os.path.join(central_path, bbcode_filename)
            else:
                central_bbcode = os.path.join(central_path, f"{folder_name}_bbcode.txt")
                log(f"Using folder_name fallback: {central_bbcode}", level="debug")
            #print(f"DEBUG: Looking for BBCode file: {central_bbcode}  File exists: {os.path.exists(central_bbcode)}")

            # If exact file doesn't exist, try pattern-based lookup
            if not os.path.exists(central_bbcode) and item.gallery_id:
                import glob
                #print(f"DEBUG: Exact file not found, trying pattern for gallery_id: {item.gallery_id}")
                pattern = os.path.join(central_path, f"*_{item.gallery_id}_bbcode.txt")
                matches = glob.glob(pattern)
                #print(f"DEBUG: Pattern '{pattern}' found {len(matches)} matches: {matches}")
                if matches:
                    central_bbcode = matches[0]
                    #print(f"DEBUG: Using pattern match: {central_bbcode}")

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
                log(f"{message}", level="info")
                # Status bar brief message
                if hasattr(widget, 'statusBar') and widget.statusBar():
                    widget.statusBar().showMessage(message, 2500)
            except Exception as e:
                log(f"Exception in main_window: {e}", level="error", category="ui")
                raise
        else:
            # Inform user nothing was copied
            try:
                message = "No completed posts selected to copy BBCode"
                log(f"{message}", level="warning")
                if hasattr(widget, 'statusBar') and widget.statusBar():
                    widget.statusBar().showMessage(message, 2500)
            except Exception as e:
                log(f"Exception in main_window: {e}", level="error", category="ui")
                raise

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
                except Exception as e:
                    log(f"Exception in main_window: {e}", level="error", category="ui")
                    raise
        # Brief user feedback
        try:
            if opened:
                message = f"Opened {opened} gallery link" + ("s" if opened != 1 else "")
            else:
                message = "No gallery link found to open"
                log(f"{message}", level="debug")
            if hasattr(widget, 'statusBar') and widget.statusBar():
                widget.statusBar().showMessage(message, 2500)
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise


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
    
    def __init__(self, splash=None):
        self._initializing = True  # Block recursive calls during init
        super().__init__()
        set_main_window(self)
        self.splash = splash
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
            self.splash.set_status("Queue Manager")
        
        # Initialize tab manager
        if self.splash:
            self.splash.set_status("Tab Manager")
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
        self.table_progress_widgets = {}
        self.settings = QSettings("ImxUploader", "ImxUploadGUI")
        
        # Track path-to-row mapping to avoid expensive table rebuilds
        self.path_to_row = {}  # Maps gallery path to table row number
        self.row_to_path = {}  # Maps table row number to gallery path
        self._path_mapping_mutex = QMutex()  # Thread safety for mapping access
        
        # Track scanning completion for targeted updates
        self._last_scan_states = {}  # Maps path -> scan_complete status
        
        # Cache expensive operations to improve responsiveness
        if self.splash:
            self.splash.set_status("cache")
        self._format_functions_cached = False
        
        # Pre-cache formatting functions to avoid blocking imports during progress updates
        self._cache_format_functions()
        
        # Initialize non-blocking components
        if self.splash:
            self.splash.set_status("Thread Pool")
        self._thread_pool = QThreadPool()
        self._thread_pool.setMaxThreadCount(4)  # Limit background threads
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
            self.splash.set_status("Single Instance Server")
        self.server = SingleInstanceServer()
        self.server.folder_received.connect(self.add_folder_from_command_line)
        self.server.start()
        
        if self.splash:
            self.splash.set_status("User Interface")
        self.setup_ui()
        
        # Initialize context menu helper and connect to the actual table widget
        if self.splash:
            self.splash.set_status("Context Menus")
        self.context_menu_helper = GalleryContextMenuHelper(self)
        self.context_menu_helper.set_main_window(self)
        self.context_menu_helper.template_change_requested.connect(
            self.context_menu_helper.set_template_for_galleries
        )
        
        # Connect context menu helper to the actual table widget used by the tabbed interface
        try:
            if hasattr(self.gallery_table, 'gallery_table'):
                # Replace the existing context menu implementation with our helper
                actual_table = self.gallery_table.gallery_table
                if hasattr(actual_table, 'show_context_menu'):
                    # Override the show_context_menu method to use our helper
                    original_show_context_menu = actual_table.show_context_menu
                    def new_show_context_menu(position):
                        self.context_menu_helper.show_context_menu_for_table(actual_table, position)
                    actual_table.show_context_menu = new_show_context_menu
        except Exception as e:
            print(f"ERROR: Could not connect context menu helper: {e}")
        
        if self.splash:
            self.splash.set_status("Menu Bar")
        self.setup_menu_bar()
        self.setup_system_tray()
        if self.splash:
            self.splash.set_status("Saved Settings")
        self.restore_settings()
       
        # Easter egg - quick gremlin flash
        if self.splash:
            self.splash.set_status("gremlins")
            QApplication.processEvents()
        
        # Initialize table update queue after table creation
        self._table_update_queue = TableUpdateQueue(self.gallery_table, self.path_to_row)
        
        # Initialize background tab update system
        self._background_tab_updates = {}  # Track updates for non-visible tabs
        self._background_update_timer = QTimer()
        self._background_update_timer.timeout.connect(self._process_background_tab_updates)
        self._background_update_timer.setSingleShot(True)

        # Uploading status icon animation (4 frames, 200ms each)
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
        if hasattr(self.gallery_table, 'gallery_table'):
            inner_table = self.gallery_table.gallery_table
            if hasattr(inner_table, 'selectionModel'):
                selection_model = inner_table.selectionModel()
                if selection_model:
                    selection_model.selectionChanged.connect(self._on_selection_changed)
            
            # Connect cell click handler for template column editing
            inner_table.cellClicked.connect(self.on_gallery_cell_clicked)
            
            # Connect itemChanged for custom columns persistence
            inner_table.itemChanged.connect(self._on_table_item_changed)
        elif hasattr(self.gallery_table, 'cellClicked'):
            # Direct connection if it's not a tabbed widget
            self.gallery_table.cellClicked.connect(self.on_gallery_cell_clicked)
            
            # Connect itemChanged for custom columns persistence
            self.gallery_table.itemChanged.connect(self._on_table_item_changed)
        
        # Set reference to update queue in tabbed widget for cache invalidation
        if hasattr(self.gallery_table, '_update_queue'):
            self.gallery_table._update_queue = self._table_update_queue
        
        # Ensure initial filter is applied once UI is ready
        try:
            self.refresh_filter()
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise
        
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
        self._initialize_table_from_queue() # Initial table build with proper path mapping
        # Button counts and progress will be updated by refresh_filter() after filter is applied
        self.gallery_table.setFocus() # Ensure table has focus for keyboard shortcuts
        self._initializing = False # Clear initialization flag to allow normal tooltip updates
        log(f"ImxUploadGUI.__init__ Completed", level="debug")

    def refresh_filter(self):
        """Refresh current tab filter on the embedded tabbed gallery widget."""
        try:
            if hasattr(self, 'gallery_table') and hasattr(self.gallery_table, 'refresh_filter'):
                self.gallery_table.refresh_filter()
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
            # Update right panel max width to 50% of current window width
            if hasattr(self, 'right_panel'):
                window_width = self.width()
                if window_width > 0:
                    max_width = int(window_width * 0.5)
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
            table_widget = getattr(self.gallery_table, 'gallery_table', self.gallery_table)
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

            # Debug: Log when setting scanning icons
            if status == "scanning":
                print(f"[ICON DEBUG] Setting scanning icon: row={row}, theme={self._current_theme_mode}, selected={is_selected}, icon_null={icon.isNull()}")

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
            inner_table = getattr(self.gallery_table, 'gallery_table', None)
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

    def _confirm_removal(self, paths: list, names: list = None, operation_type: str = "delete") -> bool:
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
        # Increment frame (0-3, cycling)
        self._upload_animation_frame = (self._upload_animation_frame + 1) % 4

        # Get the actual table (handle tabbed interface)
        table = self.gallery_table
        if hasattr(self.gallery_table, 'gallery_table'):
            table = self.gallery_table.gallery_table

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
                if hasattr(self.gallery_table, 'gallery_table'):
                    table = self.gallery_table.gallery_table

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

                if hasattr(self, 'theme_toggle_btn'):
                    theme_icon = icon_mgr.get_icon('toggle_theme')
                    if not theme_icon.isNull():
                        self.theme_toggle_btn.setIcon(theme_icon)

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

        # Refresh button icons with correct theme now that palette is ready
        try:
            self._refresh_button_icons()
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise
    
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
        
        # Header context menu for column visibility + persist widths/visibility
        # Access the internal table for header operations
        try:
            header = self.gallery_table.gallery_table.horizontalHeader()
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
        left_panel.setMinimumWidth(400)
        self.top_splitter.addWidget(left_panel)
        
        # Right panel - Settings and logs
        self.right_panel = QWidget()
        right_layout = QVBoxLayout(self.right_panel)
        # Set maximum width to 50% of window to keep queue panel visible
        try:
            # Calculate 50% of current window width as max width
            window_width = self.width() if self.width() > 0 else 1000  # fallback for initial sizing
            max_width = int(window_width * 0.5)
            self.right_panel.setMaximumWidth(max_width)
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise
        try:
            right_layout.setContentsMargins(0, 0, 0, 0)
            right_layout.setSpacing(6)
            right_layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetMinimumSize)
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise
        
        
        # Settings section
        self.settings_group = QGroupBox("Quick Settings")
        self.settings_group.setProperty("class", "settings-group")
        settings_layout = QGridLayout(self.settings_group)
        try:
            settings_layout.setContentsMargins(8, 8, 8, 8)
            settings_layout.setHorizontalSpacing(12)
            settings_layout.setVerticalSpacing(8)
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise
        
        settings_layout.setVerticalSpacing(5)
        settings_layout.setHorizontalSpacing(8)
        
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
        
        # Add stretch to bottom so extra space goes there instead of compressing rows
        settings_layout.setRowStretch(10, 1)
        
        # Load defaults
        defaults = load_user_defaults()
        
        # Thumbnail size
        settings_layout.addWidget(QLabel("<b>Thumbnail Size</b>:"), 0, 0)
        self.thumbnail_size_combo = QComboBox()
        self.thumbnail_size_combo.addItems([
            "100x100", "180x180", "250x250", "300x300", "150x150"
        ])
        self.thumbnail_size_combo.setCurrentIndex(defaults.get('thumbnail_size', 3) - 1)
        self.thumbnail_size_combo.currentIndexChanged.connect(self.on_setting_changed)
        settings_layout.addWidget(self.thumbnail_size_combo, 0, 1)
        
        # Thumbnail format
        settings_layout.addWidget(QLabel("<b>Thumbnail Format</b>:"), 1, 0)
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
        settings_layout.addWidget(QLabel("<b>BBCode Template</b>:"), 2, 0)
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
        self.auto_start_upload_check = QCheckBox("Auto-start uploads")
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
        
        # Comprehensive Settings button
        self.comprehensive_settings_btn = QPushButton("Settings && Preferences") # ⚙️ 
        if not self.comprehensive_settings_btn.text().startswith(" "):
            self.comprehensive_settings_btn.setText(" " + self.comprehensive_settings_btn.text())
        self.comprehensive_settings_btn.clicked.connect(self.open_comprehensive_settings)
        self.comprehensive_settings_btn.setMinimumHeight(30)
        self.comprehensive_settings_btn.setMaximumHeight(34)
        self.comprehensive_settings_btn.setProperty("class", "comprehensive-settings")
        settings_layout.addWidget(self.comprehensive_settings_btn, 6, 0, 1, 2)
        
        # Manage templates and credentials buttons (same row)
        self.manage_templates_btn = QPushButton(" Templates")
        self.manage_templates_btn.setToolTip("Manage BBCode templates for gallery output")
        self.manage_credentials_btn = QPushButton(" Credentials")
        self.manage_credentials_btn.setToolTip("Configure imx.to login credentials")

        # Add icons if available
    
        try:
            icon_mgr = get_icon_manager()
            if icon_mgr:
                templates_icon = icon_mgr.get_icon('templates')
                if not templates_icon.isNull():
                    self.manage_templates_btn.setIcon(templates_icon)
                    self.manage_templates_btn.setIconSize(QSize(16, 16))

                credentials_icon = icon_mgr.get_icon('credentials')
                if not credentials_icon.isNull():
                    self.manage_credentials_btn.setIcon(credentials_icon)
                    self.manage_credentials_btn.setIconSize(QSize(16, 16))

                settings_icon = icon_mgr.get_icon('settings')
                if not settings_icon.isNull():
                    self.comprehensive_settings_btn.setIcon(settings_icon)
                    self.comprehensive_settings_btn.setIconSize(QSize(18, 18))
                
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

        # Theme toggle button (icon-only, small)
        self.theme_toggle_btn = QPushButton()
        self.theme_toggle_btn.setProperty("class", "theme-toggle-btn")
        # Set initial tooltip based on current theme
        current_theme = str(self.settings.value('ui/theme', 'dark'))
        initial_tooltip = "Switch to light theme" if current_theme == 'dark' else "Switch to dark theme"
        self.theme_toggle_btn.setToolTip(initial_tooltip)
        try:
            icon_mgr = get_icon_manager()
            if icon_mgr:
                theme_icon = icon_mgr.get_icon('toggle_theme')
                if not theme_icon.isNull():
                    self.theme_toggle_btn.setIcon(theme_icon)
                    self.theme_toggle_btn.setIconSize(QSize(20, 20))
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise
        self.theme_toggle_btn.clicked.connect(self.toggle_theme)

        # Create horizontal layout for Templates, Credentials, Log Viewer, and Theme Toggle
        templates_creds_layout = QHBoxLayout()
        templates_creds_layout.addWidget(self.manage_templates_btn)
        templates_creds_layout.addWidget(self.manage_credentials_btn)
        templates_creds_layout.addWidget(self.log_viewer_btn)
        templates_creds_layout.addWidget(self.theme_toggle_btn)
        templates_creds_layout.setSpacing(6)

        settings_layout.addLayout(templates_creds_layout, 9, 0, 1, 2)
        
        # Log section (add first)
        log_group = QGroupBox("Log")
        log_layout = QVBoxLayout(log_group)
        try:
            log_layout.setContentsMargins(10, 10, 10, 10)
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
        
        right_layout.addWidget(self.settings_group)
        right_layout.addWidget(log_group, 1)  # Give it stretch priority
        
        # Set minimum width for right panel (Settings + Log) - reduced for better resizing
        self.right_panel.setMinimumWidth(250)
        self.top_splitter.addWidget(self.right_panel)
        
        # Configure splitter to prevent panels from disappearing
        self.top_splitter.setCollapsible(0, False)  # Left panel (queue) cannot collapse
        self.top_splitter.setCollapsible(1, False)  # Right panel (settings+log) cannot collapse
        
        # Set initial splitter sizes (roughly 60/40 split)
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
        self.overall_progress.setProperty("status", "ready")
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
            action_tabs = settings_menu.addAction("Tabs")
            action_tabs.triggered.connect(lambda: self.open_comprehensive_settings(tab_index=3))
            action_icons = settings_menu.addAction("Icons")
            action_icons.triggered.connect(lambda: self.open_comprehensive_settings(tab_index=4))
            action_logs = settings_menu.addAction("Logs")
            action_logs.triggered.connect(lambda: self.open_comprehensive_settings(tab_index=5))
            action_scanning = settings_menu.addAction("Image Scanning")
            action_scanning.triggered.connect(lambda: self.open_comprehensive_settings(tab_index=6))

            # Tools menu
            tools_menu = menu_bar.addMenu("Tools")
            action_templates = tools_menu.addAction("Manage Templates")
            action_templates.triggered.connect(self.manage_templates)
            action_credentials = tools_menu.addAction("Manage Credentials")
            action_credentials.triggered.connect(self.manage_credentials)
            tools_menu.addSeparator()
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

    def open_comprehensive_settings(self, tab_index=0):
        """Open comprehensive settings dialog to specific tab"""
        dialog = ComprehensiveSettingsDialog(self)
        if 0 <= tab_index < dialog.tab_widget.count():
            dialog.tab_widget.setCurrentIndex(tab_index)

        # Use non-blocking show() to prevent GUI freezing
        dialog.show()
        dialog.finished.connect(lambda result: self._handle_settings_dialog_result(result))

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
                except Exception as e:
                    log(f"Exception in main_window: {e}", level="error", category="ui")
                    raise
                app.setPalette(palette)
                
                # Load dark theme styles from styles.qss
                theme_qss = self._load_theme_styles('dark')
                app.setStyleSheet(base_qss + "\n" + theme_qss)
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
                except Exception as e:
                    log(f"Exception in main_window: {e}", level="error", category="ui")
                    raise
                app.setPalette(palette)
                
                # Load light theme styles from styles.qss
                theme_qss = self._load_theme_styles('light')
                app.setStyleSheet(base_qss + "\n" + theme_qss)
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
            if hasattr(self, 'gallery_table') and hasattr(self.gallery_table, 'gallery_table'):
                table = self.gallery_table.gallery_table  # This is the actual QTableWidget
                table_font_size = max(font_size - 1, 6)  # Table 1pt smaller, minimum 6pt
                header_font_size = max(font_size - 2, 6)  # Headers even smaller

                # Set font directly on the table widget - this affects all items
                table_font = QFont()
                table_font.setPointSize(table_font_size)
                table.setFont(table_font)

                # Set smaller font on each header item
                header_font = QFont()
                header_font.setPointSize(header_font_size)

                # Use the actual table (table = self.gallery_table.gallery_table)
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
            self.worker.queue_stats.connect(self.on_queue_stats)
            self.worker.bandwidth_updated.connect(self.on_bandwidth_updated)
            self.worker.start()
            
            log(f"Worker.isRunning(): {self.worker.isRunning()}", level="debug")
            log(f"Worker thread started", level="debug")

    def on_queue_item_status_changed(self, path: str, old_status: str, new_status: str):
        """Handle individual queue item status changes"""
        item = self.queue_manager.get_item(path)
        scan_status = item.scan_complete if item else "NO_ITEM"
        in_mapping = path in self.path_to_row
        log(f"GUI received status change signal: {path} from {old_status} to {new_status}, scan_complete={scan_status}, in_path_to_row={in_mapping}", level="debug", category="ui")
        
        # When an item goes from scanning to ready, just update tab counts
        if old_status == "scanning" and new_status == "ready":
            #print(f"DEBUG: Item completed scanning, updating tab counts")
            # Just update the tab counts, don't refresh the filter which hides items
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(150, lambda: self.gallery_table._update_tab_tooltips() if hasattr(self.gallery_table, '_update_tab_tooltips') else None)
        
        # Debug the item data before updating table
        item = self.queue_manager.get_item(path)
        if item:
            log(f"Item data: total_images={getattr(item, 'total_images', 'NOT SET')}, progress={getattr(item, 'progress', 'NOT SET')}, status={getattr(item, 'status', 'NOT SET')}, added_time={getattr(item, 'added_time', 'NOT SET')}", level="debug", category="ui")
        
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


    def browse_for_folders(self):
        """Open folder browser to select galleries or archives (supports multiple selection)"""
        # Create file dialog with multi-selection support
        file_dialog = QFileDialog(self)
        file_dialog.setWindowTitle("Select Gallery Folders or Archives")
        file_dialog.setFileMode(QFileDialog.FileMode.AnyFile)  # Allow both folders and files
        file_dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        file_dialog.setNameFilter("Folders and Archives (*.zip *.cbz);;All Files (*)")
        
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

        # Process archives
        for archive_path in archives:
            selected_folders = self.archive_coordinator.process_archive(archive_path)
            if selected_folders:
                # Mark folders as from archive and add to queue
                for folder_path in selected_folders:
                    self._add_archive_folder(str(folder_path), str(archive_path))

    def add_folders(self, folder_paths: List[str]):
        """Add folders to the upload queue with duplicate detection"""
        log(f"add_folders called with {len(folder_paths)} paths", level="debug", category="queue")

        if len(folder_paths) == 1:
            # Single folder - use the old method for backward compatibility
            self._add_single_folder(folder_paths[0])
        else:
            # Multiple folders - use new duplicate detection system
            self._add_multiple_folders_with_duplicate_detection(folder_paths)
    
    def _add_single_folder(self, path: str):
        """Add a single folder with duplicate detection."""
        log(f"_add_single_folder called with path={path}", level="debug", category="queue")
        
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
                log(f"Replaced {folder_name} in queue", level="debug", category="queue")
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
        # Get current tab BEFORE adding item
        current_tab = self.gallery_table.current_tab if hasattr(self.gallery_table, 'current_tab') else "Main"
        #print(f"{timestamp()} DEBUG: Single folder - adding to tab: {current_tab}")
        result = self.queue_manager.add_item(path, template_name=template_name, tab_name=current_tab)
        
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

        result = self.queue_manager.add_item(folder_path, name=gallery_name, template_name=template_name, tab_name=current_tab)

        if result:
            # Mark as from archive
            item = self.queue_manager.get_item(folder_path)
            if item:
                item.source_archive_path = archive_path
                item.is_from_archive = True
                self.queue_manager.save_persistent_queue([folder_path])
                self._add_gallery_to_table(item)
                log(f"Added from archive: {gallery_name}", category="queue")

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
                log(f"Added {results['added']} galleries to queue", category="queue")
            if results['duplicates'] > 0:
                log(f"Skipped {results['duplicates']} duplicate galleries", category="queue")
            if results['failed'] > 0:
                log(f"Failed to add {results['failed']} galleries", category="queue")
                # Show detailed errors if any
                for error in results['errors'][:5]:  # Show first 5 errors
                    log(f"{error}", category="queue", level="error")
                if len(results['errors']) > 5:
                    log(f"... and {len(results['errors']) - 5} more errors", category="queue")
            
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
            log(f"Error adding multiple folders: {str(e)}", category="queue")
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
                # Get current tab BEFORE adding items
                current_tab = self.gallery_table.current_tab if hasattr(self.gallery_table, 'current_tab') else "Main"
                log(f"Multiple folders - adding to tab: {current_tab}", level="debug")
                
                for folder_path in folders_to_add_normally:
                    try:
                        result = self.queue_manager.add_item(folder_path, template_name=template_name, tab_name=current_tab)
                        if result:
                            # Get the created item and immediately add to table display
                            item = self.queue_manager.get_item(folder_path)
                            if item:
                                # Add to table display immediately (like single folder does)
                                self._add_gallery_to_table(item)
                            
                            log(f"Added to queue: {os.path.basename(folder_path)}", category="queue", level="info")
                    except Exception as e:
                        log(f"Error adding folder: {os.path.basename(folder_path)}: {e}", level="error", category="queue")
            
            # Process folders that should replace existing queue items
            if folders_to_replace_in_queue:
                log(f"Replacing {len(folders_to_replace_in_queue)} folders in queue", level="debug")
                template_name = self.template_combo.currentText()
                # Get current tab for replacements too
                if 'current_tab' not in locals():
                    current_tab = self.gallery_table.current_tab if hasattr(self.gallery_table, 'current_tab') else "Main"
                    log(f"Multiple folders replacement - adding to tab: {current_tab}", level="debug")
                
                for folder_path in folders_to_replace_in_queue:
                    try:
                        # Remove existing item from both queue and table
                        self.queue_manager.remove_item(folder_path)
                        self._remove_gallery_from_table(folder_path)
                        
                        # Add new item with correct tab
                        result = self.queue_manager.add_item(folder_path, template_name=template_name, tab_name=current_tab)
                        if result:
                            # Get the created item and immediately add to table display
                            item = self.queue_manager.get_item(folder_path)
                            if item:
                                # Add to table display immediately
                                self._add_gallery_to_table(item)
                        
                        log(f"Replaced {os.path.basename(folder_path)} in queue", level="debug")
                    except Exception as e:
                        log(f"Error replacing {os.path.basename(folder_path)}: {e}", level="warning")
            
            # Update display
            total_processed = len(folders_to_add_normally) + len(folders_to_replace_in_queue)
            if total_processed > 0:
                log(f"Added {total_processed} galleries to queue", level="info")
                # Trigger table refresh and update tab counts/tooltips
                # TESTING: Comment out _update_scanned_rows to see if it's causing race condition
                #QTimer.singleShot(50, self._update_scanned_rows)
                QTimer.singleShot(100, lambda: self._update_tab_tooltips() if hasattr(self, '_update_tab_tooltips') else None)
            
        except Exception as e:
            log(f"Error processing folders: {e}", level="error")
    
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
        log(f"_add_gallery_to_table called for {item.path} with tab_name={item.tab_name}", level="debug")

        # CRITICAL FIX: Check if path already exists in table to prevent duplicates
        if item.path in self.path_to_row:
            existing_row = self.path_to_row[item.path]
            log(f"Gallery already in table at row {existing_row}, updating instead of adding duplicate", level="debug")
            # Update existing row instead of creating duplicate
            self._populate_table_row(existing_row, item)
            return

        row = self.gallery_table.rowCount()
        self.gallery_table.setRowCount(row + 1)
        log(f"Adding NEW gallery to table at row {row}", level="debug")

        # Update mappings
        self.path_to_row[item.path] = row
        self.row_to_path[row] = item.path
        log(f"Added {item.path} to path_to_row at row {row}, scan_complete={item.scan_complete}, status={item.status}", level="debug")

        # Initialize scan state tracking
        self._last_scan_states[item.path] = item.scan_complete
        log(f"Initialized _last_scan_states[{item.path}] = {item.scan_complete}", level="debug")
        
        # Populate the new row
        self._populate_table_row(row, item)
        
        # Make sure the row is visible if it belongs to the current tab
        current_tab = self.gallery_table.current_tab if hasattr(self.gallery_table, 'current_tab') else None
        if current_tab and (current_tab == "All Tabs" or item.tab_name == current_tab):
            self.gallery_table.setRowHidden(row, False)
            log(f"Row {row} set VISIBLE for current tab '{current_tab}' (item tab: '{item.tab_name}')", level="debug")
        else:
            self.gallery_table.setRowHidden(row, True)
            log(f"Row {row} set HIDDEN - item tab '{item.tab_name}' != current tab '{current_tab}'", level="debug")
        
        # Invalidate TabManager's cache for this tab so it reloads from database
        if hasattr(self.gallery_table, 'tab_manager') and item.tab_name:
            self.gallery_table.tab_manager.invalidate_tab_cache(item.tab_name)
            log(f"Invalidated TabManager cache for tab {item.tab_name}", level="debug")

        # CRITICAL FIX: Invalidate table update queue visibility cache so new visible rows get updates
        if hasattr(self, '_table_update_queue') and self._table_update_queue:
            self._table_update_queue.invalidate_visibility_cache()
            log(f"Invalidated table update queue visibility cache after adding row {row}", level="debug")
    
    def _remove_gallery_from_table(self, path: str):
        """Remove a gallery from the table and update mappings"""
        if path not in self.path_to_row:
            return

        row_to_remove = self.path_to_row[path]
        # Get the actual table (handle tabbed interface)
        table = self.gallery_table
        if hasattr(self.gallery_table, 'gallery_table'):
            table = self.gallery_table.gallery_table
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
        log(f"_update_specific_gallery_display - row={row}, path_to_row has path: {path in self.path_to_row}", level="debug")
        if row is not None and 0 <= row < self.gallery_table.rowCount():
            #print(f"DEBUG: Row {row} is valid, checking update queue")
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
            log(f"Row update failed for {path}, refreshing filter", level="warning", category="ui")
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
            #log(f"  button icons updated: {(t2-t1)*1000:.1f}ms", level="debug", category="ui")

            # Refresh renamed column icons - ONLY VISIBLE ROWS for fast theme switching
            table = self.gallery_table
            if hasattr(self.gallery_table, 'gallery_table'):
                table = self.gallery_table.gallery_table

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
            log(f"Error refreshing button icons: {e}", level="debug")

    def _populate_table_row(self, row: int, item: GalleryQueueItem):
        """Update row data immediately with proper font consistency - COMPLETE VERSION"""
        # Update splash screen during startup
        if hasattr(self, 'splash') and self.splash:
            try:
                self.splash.update_status(f"Populating row {row}")
            except Exception as e:
                
                log(f"Exception in main_window: {e}", level="error", category="ui")
                raise

        # CRITICAL: Verify row is still valid for this item (table may have changed due to deletions)
        # Always use the current mapping as the source of truth
        actual_row = self.path_to_row.get(item.path)

        if actual_row is None:
            # Item was removed from table entirely
            log(f"Skipping update - {os.path.basename(item.path)} no longer in table", level="debug")
            return

        if actual_row != row:
            # Table was modified (row deletions/insertions), use current row
            log(f"Row adjusted for {os.path.basename(item.path)}: {row} → {actual_row}", level="debug")
            row = actual_row

        theme_mode = self._current_theme_mode

        # Order number (numeric-sorting item)
        order_item = NumericTableWidgetItem(item.insertion_order)
        order_item.setFlags(order_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        order_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.gallery_table.setItem(row, GalleryTableWidget.COL_ORDER, order_item)

        # Gallery name and path
        display_name = item.name or os.path.basename(item.path) or "Unknown"
        name_item = QTableWidgetItem(display_name)
        name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        name_item.setData(Qt.ItemDataRole.UserRole, item.path)
        self.gallery_table.setItem(row, GalleryTableWidget.COL_NAME, name_item)

        # Upload progress - start blank until images are counted
        total_images = getattr(item, 'total_images', 0) or 0
        uploaded_images = getattr(item, 'uploaded_images', 0) or 0
        if total_images > 0:
            uploaded_text = f"{uploaded_images}/{total_images}"
            uploaded_item = QTableWidgetItem(uploaded_text)
            uploaded_item.setFlags(uploaded_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            uploaded_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            # PyQt is retarded, manually set font
            self.gallery_table.setItem(row, GalleryTableWidget.COL_UPLOADED, uploaded_item)
        else:
            log(f"No uploaded column set because total_images={total_images} <= 0", level="debug")

        # Progress bar
        progress_widget = self.gallery_table.cellWidget(row, 3)
        if not isinstance(progress_widget, TableProgressWidget):
            progress_widget = TableProgressWidget()
            self.gallery_table.setCellWidget(row, 3, progress_widget)
        progress_widget.update_progress(item.progress, item.status)

        # Status icon and text
        self._set_status_cell_icon(row, item.status)
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
        xfer_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if item.status == "uploading" and transfer_text:
            xfer_item.setForeground(QColor(173, 216, 255, 255) if theme_mode == 'dark' else QColor(20, 90, 150, 255))
        elif item.status in ("completed", "failed") and transfer_text:
            xfer_item.setForeground(QColor(255, 255, 255, 230) if theme_mode == 'dark' else QColor(0, 0, 0, 190))
        self.gallery_table.setItem(row, GalleryTableWidget.COL_TRANSFER, xfer_item)
        
        # Template name
        template_text = item.template_name or ""
        tmpl_item = QTableWidgetItem(template_text)
        tmpl_item.setFlags(tmpl_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        try:
            col_width = self.gallery_table.columnWidth(GalleryTableWidget.COL_TEMPLATE)
            fm = QFontMetrics(tmpl_item.font())
            text_w = fm.horizontalAdvance(template_text) + 8
            if text_w <= col_width:
                tmpl_item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
            else:
                tmpl_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        except Exception:
            tmpl_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.gallery_table.setItem(row, GalleryTableWidget.COL_TEMPLATE, tmpl_item)
        
        # Renamed status: Set icon based on whether gallery has been renamed
        # Check if gallery is in the unnamed galleries list (pending rename)
        from imxup import check_gallery_renamed
        is_renamed = check_gallery_renamed(item.gallery_id) if item.gallery_id else None
        self._set_renamed_cell_icon(row, is_renamed)

        # Custom columns and Gallery ID: Load from database
        # Get the actual table object (same logic as in _on_table_item_changed)
        actual_table = getattr(self.gallery_table, 'gallery_table', self.gallery_table)

        # Temporarily block signals to prevent itemChanged during initialization
        signals_blocked = actual_table.signalsBlocked()
        actual_table.blockSignals(True)
        try:
            # Gallery ID column - read-only
            gallery_id_text = item.gallery_id or ""
            gallery_id_item = QTableWidgetItem(gallery_id_text)
            gallery_id_item.setFlags(gallery_id_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            gallery_id_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            actual_table.setItem(row, GalleryTableWidget.COL_GALLERY_ID, gallery_id_item)

            # Custom columns - editable
            for col_idx, field_name in [
                (GalleryTableWidget.COL_CUSTOM1, 'custom1'),
                (GalleryTableWidget.COL_CUSTOM2, 'custom2'),
                (GalleryTableWidget.COL_CUSTOM3, 'custom3'),
                (GalleryTableWidget.COL_CUSTOM4, 'custom4')
            ]:
                value = getattr(item, field_name, '') or ''
                custom_item = QTableWidgetItem(str(value))
                # Make custom columns editable
                custom_item.setFlags(custom_item.flags() | Qt.ItemFlag.ItemIsEditable)
                custom_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                actual_table.setItem(row, col_idx, custom_item)
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

        # After building the table, apply the current tab filter and emit tab_changed to update counts
        if hasattr(self.gallery_table, 'refresh_filter'):
            def _apply_initial_filter():
                self.gallery_table.refresh_filter()
                # Emit tab_changed signal to trigger button count and progress updates
                if hasattr(self.gallery_table, 'tab_changed') and hasattr(self.gallery_table, 'current_tab'):
                    self.gallery_table.tab_changed.emit(self.gallery_table.current_tab)
            QTimer.singleShot(0, _apply_initial_filter)

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
            self.overall_progress.setProperty("status", "ready")
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
                self.overall_progress.setProperty("status", "completed")
            else:
                self.overall_progress.setProperty("status", "uploading")
        else:
            self.overall_progress.setValue(0)
            self.overall_progress.setText("Preparing...")
            # Blue while preparing
            self.overall_progress.setProperty("status", "uploading")
        
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
            log(f"Exception in main_window: {e}", level="error", category="ui")
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
        
        # Update only the specific row status instead of full table refresh
        # Also ensure settings are disabled while uploads are active
        try:
            self.settings_group.setEnabled(False)
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise

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
                    log(f"Exception in main_window: {e}", level="error", category="ui")
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
                    log(f"Exception in main_window: {e}", level="error", category="ui")
                    raise
        
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
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise
        
        # Re-enable settings if no remaining active items (defer to avoid blocking)
        QTimer.singleShot(5, self._check_and_enable_settings)

        # Update display with targeted update instead of full rebuild
        self._update_specific_gallery_display(path)

        # Auto-clear completed gallery if enabled
        from imxup import load_user_defaults
        defaults = load_user_defaults()
        if defaults.get('auto_clear_completed', False):
            # Get item to check if it's actually completed (not failed)
            item = self.queue_manager.get_item(path)
            if item and item.status == "completed":
                QTimer.singleShot(100, lambda: self.remove_gallery(path))


        # Update button counts and progress after status change
        QTimer.singleShot(0, self._update_counts_and_progress)

        # Defer only the heavy stats update to avoid blocking
        QTimer.singleShot(50, lambda: self._update_stats_deferred(results))
    
    def _check_and_enable_settings(self):
        """Check if settings should be enabled - deferred to avoid blocking GUI"""
        try:
            remaining = self.queue_manager.get_all_items()
            any_active = any(i.status in ("queued", "uploading") for i in remaining)
            self.settings_group.setEnabled(not any_active)
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise
    
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
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise
    
    
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
            log(f"Upload cancelled by user due to existing gallery", level="debug", category="ui")
            # TODO: Implement proper cancellation mechanism
        else:
            log("User chose to continue with existing gallery", level="debug", category="ui")

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
        try:
            remaining = self.queue_manager.get_all_items()
            any_active = any(i.status in ("queued", "uploading") for i in remaining)
            self.settings_group.setEnabled(not any_active)
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise

        # Update display when status changes  
        self._update_specific_gallery_display(path)
        
        # Update button counts and progress after status change
        QTimer.singleShot(0, self._update_counts_and_progress)
        
        gallery_name = os.path.basename(path)
        log(f"✗ Failed: {gallery_name} - {error_message}", level="error")
    
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
        """Add message to log"""
        # Determine category and subtype for GUI gating and file logging
        # Auto-detect log level from message keywords
        log_level = logging.INFO  # Default
        message_upper = message.upper()
        if "CRITICAL" in message_upper or "FATAL" in message_upper:
            log_level = logging.CRITICAL
        elif "ERROR" in message_upper:
            log_level = logging.ERROR
        elif "WARNING" in message_upper or "WARN" in message_upper:
            log_level = logging.WARNING
        elif "DEBUG" in message_upper:
            log_level = logging.DEBUG

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
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise

        # GUI visibility based on settings
        show_in_gui = True
        try:
            logger = get_logger()
            if not logger.should_emit_gui(category, log_level):
                show_in_gui = False
            if category == "uploads" and show_in_gui:
                if subtype == "file" and not logger.should_log_upload_file_success("gui"):
                    show_in_gui = False
                if subtype == "gallery" and not logger.should_log_upload_gallery_success("gui"):
                    show_in_gui = False
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise

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

                # Prepend to top of list (newest first)
                self.log_text.insertItem(0, display)

                # Limit to 5000 items
                if self.log_text.count() > 5000:
                    self.log_text.takeItem(5000)
            except Exception:
                self.log_text.insertItem(0, message)

        # NO FILE LOGGING HERE - the log() function already did that!
        # Retain long history; no aggressive trimming
        try:
            if getattr(self, "_log_viewer_dialog", None) is not None and self._log_viewer_dialog.isVisible():
                self._log_viewer_dialog.append_message(message)
        except Exception as e:
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise

    def show_status_message(self, message: str, timeout: int = 2500):
        """
        Show a temporary message in the status bar.

        Args:
            message: Message to display
            timeout: Duration in milliseconds (default 2500ms = 2.5 seconds)
        """
        self.statusBar().showMessage(message, timeout)

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
            log(f"Error starting upload for {path}: {e}", level="error", category="queue")
            return False

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
            # The manage_gallery_files method is in GalleryTableWidget (self.gallery_table.gallery_table)
            if hasattr(self.gallery_table, 'gallery_table') and hasattr(self.gallery_table.gallery_table, 'manage_gallery_files'):
                self.gallery_table.gallery_table.manage_gallery_files(path)
                return
        else:
            # For other statuses (uploading, paused, etc.), open gallery file manager
            # The manage_gallery_files method is in GalleryTableWidget (self.gallery_table.gallery_table)
            if hasattr(self.gallery_table, 'gallery_table') and hasattr(self.gallery_table.gallery_table, 'manage_gallery_files'):
                self.gallery_table.gallery_table.manage_gallery_files(path)
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
            log(f"BBcode copy failed: {os.path.basename(path)} is not completed", level="warning", category="fileio")
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
            clipboard.setText(content)
            log(f"Copied BBCode to clipboard from: {source_file}", level="info", category="fileio")
        else:
            log(f"No BBCode file found for: {folder_name}", level="info", category="fileio")
    
    def start_all_uploads(self):
        """Start all ready uploads"""
        start_time = time.time()
        log(f"start_all_uploads() started at {start_time:.6f}", level="debug", category="timing")
        
        get_items_start = time.time()
        items = self._get_current_tab_items()
        get_items_duration = time.time() - get_items_start
        log(f"_get_current_tab_items() took {get_items_duration:.6f}s", level="debug", category="timing")
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
                        log(f"start_item({item.path}) failed in {start_item_duration:.6f}s", category="timing", level="warning")
        
        item_processing_duration = time.time() - item_processing_start
        log(f"Processing all items took {item_processing_duration:.6f}s", category="timing", level="info")
        
        ui_update_start = time.time()
        if started_count > 0:
            log(f"Started {started_count} uploads")
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
            log(f"Reset {reset_count} queued item(s) to Ready", level="debug", category="queue")
            # Update all affected items individually instead of rebuilding table
            for path in reset_paths:
                self._update_specific_gallery_display(path)
            # Update button counts and progress after state changes
            QTimer.singleShot(0, self._update_counts_and_progress)
        else:
            log(f"No queued items to reset", level="debug", category="queue")
    
    def clear_completed(self):
        """Clear completed/failed uploads - non-blocking with confirmation"""
        log(f"clear_completed() called", category="queue", level="info")

        # Get items to clear
        items_snapshot = self._get_current_tab_items()
        log(f"Got {len(items_snapshot)} items from current tab", category="queue", level="info")

        comp_paths = [it.path for it in items_snapshot if it.status in ("completed", "failed")]
        log(f"Found {len(comp_paths)} completed/failed galleries", category="queue", level="info")

        if not comp_paths:
            log(f"No completed uploads to clear", category="queue", level="info")
            return

        # Use shared confirmation method
        log(f"Requesting user confirmation", category="queue", level="info")
        if not self._confirm_removal(comp_paths, operation_type="clear"):
            log(f"User cancelled clear operation", category="queue", level="info")
            return

        log(f"User confirmed - proceeding with clear", category="queue", level="info")

        # User confirmed - proceed with removal
        count_completed = sum(1 for it in items_snapshot if it.status == "completed")
        count_failed = sum(1 for it in items_snapshot if it.status == "failed")
        log(f"Clearing: completed={count_completed}, failed={count_failed}", category="queue", level="info")

        # Remove from queue manager (same pattern as delete_selected_items)
        removed_paths = []
        for path in comp_paths:
            # Remove from memory
            with QMutexLocker(self.queue_manager.mutex):
                if path in self.queue_manager.items:
                    del self.queue_manager.items[path]
                    removed_paths.append(path)
                    log(f"Removed: {os.path.basename(path)}", category="queue", level="debug")

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
                log(f"Error deleting from database: {e}", level="error", category="queue")

            # Update button counts and progress
            QTimer.singleShot(0, self._update_counts_and_progress)

            # Update tab tooltips
            if hasattr(self.gallery_table, '_update_tab_tooltips'):
                self.gallery_table._update_tab_tooltips()

            # Save queue
            QTimer.singleShot(100, self.queue_manager.save_persistent_queue)
            log(f"✓ Cleared {len(removed_paths)} completed/failed uploads", category="queue", level="info")

        # Use non-blocking batch removal for table updates
        self._remove_galleries_batch(removed_paths, callback=on_clear_complete)
    
    def delete_selected_items(self):
        """Delete selected items from the queue - non-blocking"""
        log(f"Delete method called", level="debug", category="queue")

        # Get the actual table (handle tabbed interface)
        table = self.gallery_table
        if hasattr(self.gallery_table, 'gallery_table'):
            table = self.gallery_table.gallery_table

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
                log(f"Error deleting from database: {e}", level="error", category="ui")

            # Update button counts and progress
            QTimer.singleShot(0, self._update_counts_and_progress)

            # Update tab tooltips to reflect new counts
            if hasattr(self.gallery_table, '_update_tab_tooltips'):
                self.gallery_table._update_tab_tooltips()

            # Defer database save to prevent GUI freeze
            QTimer.singleShot(100, self.queue_manager.save_persistent_queue)
            log(f"✓ Deleted {len(removed_paths)} items from queue", level="info", category="queue")

        # Use non-blocking batch removal for table updates
        self._remove_galleries_batch(removed_paths, callback=on_deletion_complete)
    

    
    def restore_settings(self):
        """Restore window settings"""
        geometry = self.settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        
        # Restore splitter state for resizable divider between queue and settings
        if hasattr(self, 'top_splitter'):
            splitter_state = self.settings.value("splitter/state")
            if splitter_state:
                self.top_splitter.restoreState(splitter_state)
        
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
        # Save splitter state for resizable divider between queue and settings
        if hasattr(self, 'top_splitter'):
            self.settings.setValue("splitter/state", self.top_splitter.saveState())
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
        self.gallery_table.setColumnHidden(column_index, not visible)
        self.save_table_settings()
    
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
            log(f"Error saving settings: {str(e)}")
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

                if os.path.isdir(path) or is_archive_file(path):
                    paths.append(path)

            if paths:
                self.add_folders_or_archives(paths)
                event.acceptProposedAction()
            else:
                
                event.ignore()
        else:
            
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
            log(f"Exception in main_window: {e}", level="error", category="ui")
            raise

        self.save_settings()

        # Save queue state (deferred to prevent blocking shutdown)
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(10, self.queue_manager.save_persistent_queue)

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

    def on_gallery_cell_clicked(self, row, column):
        """Handle clicks on gallery table cells for template editing and custom column editing."""
       
        # Handle custom columns (13-16) with single-click editing
        if GalleryTableWidget.COL_CUSTOM1 <= column <= GalleryTableWidget.COL_CUSTOM4:
            # Get the correct table and trigger edit mode
            table = getattr(self.gallery_table, 'gallery_table', self.gallery_table)
            if table:
                item = table.item(row, column)
                if item:
                    table.editItem(item)
            return
            
        # Only handle clicks on template column for template editing
        if column != GalleryTableWidget.COL_TEMPLATE:
            return

        # Get the table widget
        if hasattr(self.gallery_table, 'gallery_table'):
            table = self.gallery_table.gallery_table
        else:
            table = self.gallery_table

        # Get gallery path the same way as context menu - from name column UserRole data
        name_item = table.item(row, GalleryTableWidget.COL_NAME)
        if not name_item:
            log(f"Mouseclick -> No item found at row {row}, column {GalleryTableWidget.COL_NAME}", category="ui", level="debug")
            return
        
        gallery_path = name_item.data(Qt.ItemDataRole.UserRole)
        if not gallery_path:
            log(f"No UserRole data in gallery name column", category="ui", level="debug")
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
            log(f"Error loading templates: {e}", category="ui", level="error")

    def update_gallery_template(self, row, gallery_path, new_template, combo_widget):
        """Update template for a gallery and regenerate BBCode if needed."""
        log(f"update_gallery_template called - row={row}, path={gallery_path}, new_template={new_template}", category="db", level="debug")
        try:
            
            # Get table reference
            if hasattr(self.gallery_table, 'gallery_table'):
                table = self.gallery_table.gallery_table
            else:
                table = self.gallery_table
            
            log(f"About to update database with path: '{gallery_path}' and template: '{new_template}'", level="debug")
            
            # Check what's actually in the database
            try:
                all_db_items = self.queue_manager.get_all_items()
                db_paths = [item.path for item in all_db_items[:5]]  # First 5 paths
                log(f"Sample database paths: {db_paths}", level="debug")
                log(f"Does our path exist in DB? {gallery_path in [item.path for item in all_db_items]}", level="debug")
            except Exception as e:
                log(f"Error checking database: {e}", category="db", level="error")
            
            # Update database
            success = self.queue_manager.store.update_item_template(gallery_path, new_template)
            log(f"Database update success: {success}", category="db", level="debug")
            
            # Update the table cell display
            template_item = table.item(row, GalleryTableWidget.COL_TEMPLATE)
            if template_item:
                template_item.setText(new_template)
            else:
                log(f"No template item found at row {row}, column {GalleryTableWidget.COL_TEMPLATE}", category="ui", level="debug")
            
            log(f"Template update completed", category="ui", level="debug")
            
            # Get the actual gallery item to check real status
            gallery_item = self.queue_manager.get_item(gallery_path)
            if not gallery_item:
                log(f"Could not get gallery item from queue manager", category="ui", level="debug")
                status = ""
            else:
                status = gallery_item.status
            
            log(f"Gallery status from queue manager: '{status}'", category="ui", level="debug")
            
            if status == "completed":
                log(f"Gallery is completed, attempting BBCode regeneration", level="debug", category="fileio")
                # Try to regenerate BBCode from JSON artifact
                try:
                    self.regenerate_gallery_bbcode(gallery_path, new_template)
                    log(f"Template changed to '{new_template}' and BBCode regenerated for {os.path.basename(gallery_path)}", level="info", category="fileio")
                    #print(f"DEBUG: BBCode regeneration successful")
                except Exception as e:
                    log(f"Template changed to '{new_template}' for {os.path.basename(gallery_path)}, but BBCode regeneration failed: {e}", category="fileio", level="error")
            else:
                log(f"Gallery not completed, skipping BBCode regeneration", category="fileio", level="debug")
                #log(f"Template changed to '{new_template}' for {os.path.basename(gallery_path)}")
            
            # Remove combo box and update display
            table.removeCellWidget(row, GalleryTableWidget.COL_TEMPLATE)
            template_item = table.item(row, GalleryTableWidget.COL_TEMPLATE)
            if template_item:
                template_item.setText(new_template)
            
            # Force table refresh to ensure data is updated
            # Note: refresh_gallery_display doesn't exist, removing this call
            
        except Exception as e:
            log(f"Error updating gallery template: {e}", category="fileio", level="error")
            # Remove combo box on error
            try:
                table = self.gallery_table.gallery_table
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
        log(f"regenerate_bbcode_for_gallery_multi called with {len(paths)} paths", category="fileio", level="debug")

        # Find the main GUI window
        widget = self
        while widget and not hasattr(widget, 'queue_manager'):
            widget = widget.parent()
        if not widget:
            log(f"No widget with queue_manager found", category="fileio", level="debug")
            return

        success_count = 0
        error_count = 0

        for path in paths:
            try:
                log(f"Processing path: {path}", level="debug", category="fileio")
                item = widget.queue_manager.get_item(path)
                if not item:
                    log(f"No item found for path: {path}", category="fileio", level="debug")
                    continue

                if item.status != "completed":
                    log(f"Skipping non-completed item: {item.status}", category="fileio", level="debug")
                    continue

                # Get template for this gallery (same logic as single version)
                if item and item.template_name:
                    template_name = item.template_name
                else:
                    template_name = "default"

                # Call the existing regeneration method (force=True since this is explicit user action)
                widget.regenerate_gallery_bbcode(path, template_name)
                success_count += 1
                log(f"Successfully regenerated BBCode for {path}", category="fileio", level="debug")

            except Exception as e:
                error_count += 1
                log(f"Error regenerating BBCode for {path}: {e}", category="fileio", level="warning")

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
            'custom4': getattr(item, 'custom4', '')
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
            # Only handle custom columns (13-16: Custom1, Custom2, Custom3, Custom4)
            column = item.column()
            if column < GalleryTableWidget.COL_CUSTOM1 or column > GalleryTableWidget.COL_CUSTOM4:
                return
            
            # Skip if this is just table population/refresh (signals should be blocked during those operations)
            table = getattr(self.gallery_table, 'gallery_table', self.gallery_table)
            if not table:
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
                GalleryTableWidget.COL_CUSTOM4: 'custom4'
            }
            field_name = field_names.get(column)
            if not field_name:
                return
                
            # Get the new value and update the database
            new_value = item.text() or ''
            if self.queue_manager:
                self.queue_manager.update_custom_field(path, field_name, new_value)
            
        except Exception as e:
            log(f"Error handling table item change: {e}", category="ui", level="error")

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
    print(f"{timestamp()} INFO: Loading splash screen")
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
            print(f"{timestamp()} INFO: ImxUp GUI already running, attempting to bring existing instance to front.")
            splash.finish_and_hide()
            return
    
    splash.set_status("Qt ")
    
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





# ComprehensiveSettingsDialog moved to imxup_settings.py

if __name__ == "__main__":
    main()
