#!/usr/bin/env python3
"""
Settings management module for imxup GUI
Contains all settings-related dialogs and configuration management

SETTINGS STORAGE ARCHITECTURE:
==============================
This application uses TWO separate settings storage systems with clear separation of concerns:

1. QSettings (Qt's built-in system) - FOR UI STATE ONLY:
   - Window geometry/position
   - Column widths/visibility
   - Splitter positions
   - Last active tab
   - Theme choice
   - Font size
   - Sort order
   - Any transient "where did I leave the UI" state

   Location: Platform-specific (Windows Registry, macOS plist, Linux conf files)
   Managed by: Qt automatically via QSettings("ImxUploader", "ImxUploadGUI")

2. INI File (~/.imxup/imxup.ini) - FOR USER CONFIGURATION:
   - Credentials (username, password, API key)
   - Templates
   - Scanning settings (fast scan, sampling, exclusions, etc.)
   - Upload behavior (timeouts, retries, batch size)
   - Storage paths
   - Auto-start/auto-clear preferences
   - Thumbnail settings

   Location: ~/.imxup/imxup.ini (portable, human-editable)
   Managed by: ConfigParser (manual read/write)

WHY THIS SEPARATION:
- Portability: INI file can be copied to other machines
- Transparency: Users can manually edit INI settings
- Qt Best Practice: QSettings handles platform-specific UI state
- Clear semantics: "How it looks" (QSettings) vs "How it behaves" (INI)
"""

import os
import sys
import configparser
import subprocess
from typing import List, Dict, Any, Optional

from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout,
    QTabWidget, QPushButton, QCheckBox, QComboBox, QSpinBox, QSlider,
    QLabel, QGroupBox, QLineEdit, QMessageBox, QFileDialog,
    QListWidget, QListWidgetItem, QPlainTextEdit, QInputDialog,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QButtonGroup, QFrame, QSplitter, QRadioButton, QApplication, QScrollArea,
    QProgressBar
)
from PyQt6.QtCore import Qt, QSettings, pyqtSignal, QTimer
from PyQt6.QtGui import QIcon, QFont, QColor, QTextCharFormat, QPixmap, QPainter, QPen, QDragEnterEvent, QDropEvent
from PyQt6.QtGui import QSyntaxHighlighter

# Import local modules
from imxup import load_user_defaults, get_config_path, encrypt_password, decrypt_password
from src.utils.format_utils import timestamp, format_binary_size
from src.utils.logger import log
from src.gui.dialogs.message_factory import MessageBoxFactory, show_info, show_error, show_warning
from src.gui.dialogs.template_manager import TemplateManagerDialog, PlaceholderHighlighter
from src.gui.dialogs.credential_setup import CredentialSetupDialog
from src.gui.widgets.advanced_settings_widget import AdvancedSettingsWidget


class IconDropFrame(QFrame):
    """Drop-enabled frame for icon files"""
    
    icon_dropped = pyqtSignal(str)  # Emits file path when icon is dropped
    
    def __init__(self, variant_type):
        super().__init__()
        self.variant_type = variant_type
        self.setAcceptDrops(True)
        
    def dragEnterEvent(self, event: QDragEnterEvent | None) -> None:
        """Handle drag enter event"""
        if event is None:
            return
        mime_data = event.mimeData()
        if mime_data and mime_data.hasUrls():
            urls = mime_data.urls()
            if len(urls) == 1:
                file_path = urls[0].toLocalFile()
                if file_path.lower().endswith(('.png', '.ico', '.svg', '.jpg', '.jpeg')):
                    event.acceptProposedAction()
                    return
        event.ignore()
        
    def dropEvent(self, event: QDropEvent | None) -> None:
        """Handle drop event"""
        if event is None:
            return
        mime_data = event.mimeData()
        if not mime_data:
            if event:
                event.ignore()
            return
        urls = mime_data.urls()
        if len(urls) == 1:
            file_path = urls[0].toLocalFile()
            if file_path.lower().endswith(('.png', '.ico', '.svg', '.jpg', '.jpeg')):
                self.icon_dropped.emit(file_path)
                event.acceptProposedAction()
                return
        event.ignore()


class HostTestDialog(QDialog):
    """Dialog showing file host test progress with checklist"""

    def __init__(self, host_name: str, parent=None):
        super().__init__(parent)
        self.host_name = host_name
        self.test_items: Dict[str, Dict[str, Any]] = {}
        self.setup_ui()

    def setup_ui(self):
        """Setup the test dialog UI"""
        self.setWindowTitle(f"Testing {self.host_name}")
        self.setModal(True)
        self.resize(400, 250)

        layout = QVBoxLayout(self)

        # Title
        title_label = QLabel(f"<b>Testing {self.host_name}</b>")
        layout.addWidget(title_label)

        layout.addSpacing(10)

        # Test items list
        self.tests_layout = QVBoxLayout()

        # Add test items
        test_names = [
            ("login", "Logging in..."),
            ("credentials", "Validating credentials..."),
            ("user_info", "Retrieving account info..."),
            ("upload", "Testing upload..."),
            ("cleanup", "Cleaning up test file...")
        ]

        for test_id, test_name in test_names:
            test_row = QHBoxLayout()

            status_label = QLabel("⏳")  # Waiting
            status_label.setFixedWidth(30)

            name_label = QLabel(test_name)

            test_row.addWidget(status_label)
            test_row.addWidget(name_label)
            test_row.addStretch()

            self.tests_layout.addLayout(test_row)

            # Store references
            self.test_items[test_id] = {
                'status_label': status_label,
                'name_label': name_label,
                'row': test_row
            }

        layout.addLayout(self.tests_layout)
        layout.addStretch()

        # Close button (initially hidden)
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.accept)
        self.close_btn.setVisible(False)
        layout.addWidget(self.close_btn)

    def update_test_status(self, test_id: str, status: str, message: Optional[str] = None):
        """Update status of a test

        Args:
            test_id: Test identifier
            status: 'running', 'success', 'failure', 'skipped'
            message: Optional status message
        """
        if test_id not in self.test_items:
            return

        item = self.test_items[test_id]

        status_label = item['status_label']
        if status == 'running':
            status_label.setText("⏳")
            status_label.setProperty("status", "running")
        elif status == 'success':
            status_label.setText("✓")
            status_label.setProperty("status", "success")
        elif status == 'failure':
            status_label.setText("✗")
            status_label.setProperty("status", "failure")
        elif status == 'skipped':
            status_label.setText("○")
            status_label.setProperty("status", "skipped")
        # Reapply stylesheet to pick up property change
        status_label.style().unpolish(status_label)
        status_label.style().polish(status_label)

        if message:
            item['name_label'].setText(message)

        # Force UI update
        self.repaint()
        QApplication.processEvents()

    def set_complete(self, success: bool):
        """Mark testing as complete

        Args:
            success: True if all tests passed
        """
        self.close_btn.setVisible(True)
        if success:
            self.setWindowTitle(f"Testing {self.host_name} - Complete ✓")
        else:
            self.setWindowTitle(f"Testing {self.host_name} - Failed ✗")


class ComprehensiveSettingsDialog(QDialog):
    """Comprehensive settings dialog with tabbed interface"""

    def __init__(self, parent=None, file_host_manager=None):
        super().__init__(parent)
        self.parent_window = parent
        self.file_host_manager = file_host_manager

        # Track dirty state per tab
        self.tab_dirty_states = {}
        self.current_tab_index = 0

        # Initialize QSettings for storing test results and cache
        self.settings = QSettings("ImxUploader", "ImxUploadGUI")

        self.setup_ui()
        self.load_settings()

        # Connect tab change signal to check for unsaved changes
        self.tab_widget.currentChanged.connect(self.on_tab_changed)
        
    def setup_ui(self):
        """Setup the tabbed settings interface"""
        self.setWindowTitle("Settings & Preferences")
        self.setModal(True)
        self.resize(900, 600)

        # Center dialog on parent window or screen
        self._center_on_parent()
        
        layout = QVBoxLayout(self)
        
        # Create tab widget
        self.tab_widget = QTabWidget()
        self.tab_widget.currentChanged.connect(self.on_tab_changed)
        layout.addWidget(self.tab_widget)

        # Create tabs
        self.setup_general_tab()
        self.setup_credentials_tab()
        self.setup_templates_tab()
        self.setup_tabs_tab()  # Create widgets but don't add tab
        self.setup_icons_tab()  # Create widgets but don't add tab
        self.setup_logs_tab()
        self.setup_scanning_tab()
        self.setup_external_apps_tab()
        self.setup_file_hosts_tab()
        self.setup_advanced_tab()

        # Buttons
        button_layout = QHBoxLayout()
        
        # Reset button on the left
        self.reset_btn = QPushButton("Reset to Defaults")
        self.reset_btn.clicked.connect(self.reset_to_defaults)
        button_layout.addWidget(self.reset_btn)
        
        button_layout.addStretch()
        
        # Standard button order: OK, Apply, Cancel
        self.ok_btn = QPushButton("OK")
        self.ok_btn.clicked.connect(self.save_and_close)
        button_layout.addWidget(self.ok_btn)
        
        self.apply_btn = QPushButton("Apply")
        self.apply_btn.clicked.connect(self.apply_current_tab)
        self.apply_btn.setEnabled(False)  # Initially disabled
        button_layout.addWidget(self.apply_btn)
        
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.on_cancel_clicked)
        button_layout.addWidget(self.cancel_btn)
        
        layout.addLayout(button_layout)
        
    def setup_general_tab(self):
        """Setup the General settings tab"""
        general_widget = QWidget()
        layout = QVBoxLayout(general_widget)
        
        # Load defaults
        defaults = load_user_defaults()
        
        # Upload settings group
        upload_group = QGroupBox("Connection")
        upload_layout = QGridLayout(upload_group)
        
        # Max retries
        upload_layout.addWidget(QLabel("<b>Max Retries</b>:"), 0, 0)
        retries_widget = QWidget()
        retries_layout = QHBoxLayout(retries_widget)
        retries_layout.setContentsMargins(0, 0, 0, 0)
        self.max_retries_slider = QSlider(Qt.Orientation.Horizontal)
        self.max_retries_slider.setRange(1, 5)
        self.max_retries_slider.setValue(defaults.get('max_retries', 3))
        self.max_retries_value = QLabel(str(defaults.get('max_retries', 3)))
        self.max_retries_value.setMinimumWidth(20)
        retries_layout.addWidget(self.max_retries_slider)
        retries_layout.addWidget(self.max_retries_value)
        self.max_retries_slider.valueChanged.connect(lambda v: self.max_retries_value.setText(str(v)))
        upload_layout.addWidget(retries_widget, 0, 1)
        
        # Concurrent uploads
        upload_layout.addWidget(QLabel("<b>Concurrent Uploads</b>:"), 1, 0)
        concurrent_widget = QWidget()
        concurrent_layout = QHBoxLayout(concurrent_widget)
        concurrent_layout.setContentsMargins(0, 0, 0, 0)
        self.batch_size_slider = QSlider(Qt.Orientation.Horizontal)
        self.batch_size_slider.setRange(1, 8)
        self.batch_size_slider.setValue(defaults.get('parallel_batch_size', 4))
        self.batch_size_slider.setToolTip("Number of images to upload simultaneously. Higher values = faster uploads but more server load.")
        self.batch_size_value = QLabel(str(defaults.get('parallel_batch_size', 4)))
        self.batch_size_value.setMinimumWidth(20)
        concurrent_layout.addWidget(self.batch_size_slider)
        concurrent_layout.addWidget(self.batch_size_value)
        self.batch_size_slider.valueChanged.connect(lambda v: self.batch_size_value.setText(str(v)))
        upload_layout.addWidget(concurrent_widget, 1, 1)
        
        # Upload timeouts
        upload_layout.addWidget(QLabel("<b>Connect Timeout (s)</b>:"), 2, 0)
        connect_timeout_widget = QWidget()
        connect_timeout_layout = QHBoxLayout(connect_timeout_widget)
        connect_timeout_layout.setContentsMargins(0, 0, 0, 0)
        self.connect_timeout_slider = QSlider(Qt.Orientation.Horizontal)
        self.connect_timeout_slider.setRange(10, 180)
        self.connect_timeout_slider.setValue(defaults.get('upload_connect_timeout', 30))
        self.connect_timeout_slider.setToolTip("Maximum time to wait for server connection. Increase if you have slow internet.")
        self.connect_timeout_value = QLabel(str(defaults.get('upload_connect_timeout', 30)))
        self.connect_timeout_value.setMinimumWidth(30)
        connect_timeout_layout.addWidget(self.connect_timeout_slider)
        connect_timeout_layout.addWidget(self.connect_timeout_value)
        self.connect_timeout_slider.valueChanged.connect(lambda v: self.connect_timeout_value.setText(str(v)))
        upload_layout.addWidget(connect_timeout_widget, 2, 1)
        
        upload_layout.addWidget(QLabel("<b>Read Timeout (s)</b>:"), 3, 0)
        read_timeout_widget = QWidget()
        read_timeout_layout = QHBoxLayout(read_timeout_widget)
        read_timeout_layout.setContentsMargins(0, 0, 0, 0)
        self.read_timeout_slider = QSlider(Qt.Orientation.Horizontal)
        self.read_timeout_slider.setRange(20, 600)
        self.read_timeout_slider.setValue(defaults.get('upload_read_timeout', 90))
        self.read_timeout_slider.setToolTip("Maximum time to wait for server response. Increase for large images or slow servers.")
        self.read_timeout_value = QLabel(str(defaults.get('upload_read_timeout', 90)))
        self.read_timeout_value.setMinimumWidth(30)
        read_timeout_layout.addWidget(self.read_timeout_slider)
        read_timeout_layout.addWidget(self.read_timeout_value)
        self.read_timeout_slider.valueChanged.connect(lambda v: self.read_timeout_value.setText(str(v)))
        upload_layout.addWidget(read_timeout_widget, 3, 1)


        # Thumbnail settings
        thumb_group = QGroupBox("Thumbnails")
        thumb_layout = QGridLayout(thumb_group)
        
        # Thumbnail size
        thumb_layout.addWidget(QLabel("<b>Thumbnail Size</b>:"), 0, 0)
        self.thumbnail_size_combo = QComboBox()
        self.thumbnail_size_combo.addItems([
            "100x100", "180x180", "250x250", "300x300", "150x150"
        ])
        self.thumbnail_size_combo.setCurrentIndex(defaults.get('thumbnail_size', 3) - 1)
        thumb_layout.addWidget(self.thumbnail_size_combo, 0, 1)
        
        # Thumbnail format
        thumb_layout.addWidget(QLabel("<b>Thumbnail Format</b>:"), 1, 0)
        self.thumbnail_format_combo = QComboBox()
        self.thumbnail_format_combo.addItems([
            "Fixed width", "Proportional", "Square", "Fixed height"
        ])
        self.thumbnail_format_combo.setCurrentIndex(defaults.get('thumbnail_format', 2) - 1)
        thumb_layout.addWidget(self.thumbnail_format_combo, 1, 1)
        
        
        
        # General settings group
        general_group = QGroupBox("General Options")
        general_layout = QGridLayout(general_group)
        
        # Confirm delete
        self.confirm_delete_check = QCheckBox("Confirm when removing galleries")
        self.confirm_delete_check.setChecked(defaults.get('confirm_delete', True))
        general_layout.addWidget(self.confirm_delete_check, 0, 0)
        
        # Auto-rename
        self.auto_rename_check = QCheckBox("Automatically rename galleries on imx.to")
        self.auto_rename_check.setChecked(defaults.get('auto_rename', True))
        general_layout.addWidget(self.auto_rename_check, 1, 0)

        # Auto-regenerate BBCode
        self.auto_regenerate_bbcode_check = QCheckBox("Auto-regenerate artifacts when data changes")
        self.auto_regenerate_bbcode_check.setChecked(defaults.get('auto_regenerate_bbcode', True))
        self.auto_regenerate_bbcode_check.setToolTip("Automatically regenerate BBCode when template, gallery name, or custom fields change")
        general_layout.addWidget(self.auto_regenerate_bbcode_check, 2, 0)

        # Auto-start uploads
        self.auto_start_upload_check = QCheckBox("Start uploads automatically")
        self.auto_start_upload_check.setChecked(defaults.get('auto_start_upload', False))
        self.auto_start_upload_check.setToolTip("Automatically start uploads when scanning completes instead of waiting for manual start")
        general_layout.addWidget(self.auto_start_upload_check, 3, 0)

        # Auto-clear completed uploads
        self.auto_clear_completed_check = QCheckBox("Clear completed items automatically")
        self.auto_clear_completed_check.setChecked(defaults.get('auto_clear_completed', False))
        self.auto_clear_completed_check.setToolTip("Automatically remove completed galleries from the queue")
        general_layout.addWidget(self.auto_clear_completed_check, 4, 0)

        # Check for updates on startup
        self.check_updates_checkbox = QCheckBox("Check for updates on startup")
        self.check_updates_checkbox.setChecked(defaults.get('check_updates_on_startup', True))
        self.check_updates_checkbox.setToolTip("Automatically check for new versions when the application starts")
        general_layout.addWidget(self.check_updates_checkbox, 5, 0)

        # Storage options group
        storage_group = QGroupBox("Central Storage")
        storage_layout = QGridLayout(storage_group)
        
        
        # Data location section
        location_label = QLabel("<b>Choose location to save data</b> <i>(database, artifacts, settings, etc.)</i>")
        storage_layout.addWidget(location_label, 2, 0, 1, 3)
        
        # Import path functions
        from imxup import get_central_store_base_path, get_default_central_store_base_path, get_project_root, get_base_path

        # Get ACTUAL current path from QSettings (source of truth)
        current_path = get_base_path()
        home_path = get_default_central_store_base_path()
        app_root = get_project_root()
        portable_path = os.path.join(app_root, '.imxup')

        # Radio buttons for location selection
        self.home_radio = QRadioButton(f"Home folder: {home_path}")
        self.portable_radio = QRadioButton(f"App folder (portable): {portable_path}")
        self.custom_radio = QRadioButton("Custom location:")

        # Determine which radio to check based on ACTUAL current path
        current_norm = os.path.normpath(current_path)
        home_norm = os.path.normpath(home_path)
        portable_norm = os.path.normpath(portable_path)

        if current_norm == portable_norm:
            self.portable_radio.setChecked(True)
            storage_mode = 'portable'
        elif current_norm == home_norm:
            self.home_radio.setChecked(True)
            storage_mode = 'home'
        else:
            self.custom_radio.setChecked(True)
            storage_mode = 'custom'

        # Custom path input and browse button
        self.path_edit = QLineEdit(current_path if storage_mode == 'custom' else '')
        self.path_edit.setReadOnly(True)
        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.clicked.connect(self.browse_central_store)
        
        # Layout radio buttons and custom path controls
        storage_layout.addWidget(self.home_radio, 3, 0, 1, 3)
        storage_layout.addWidget(self.portable_radio, 4, 0, 1, 3)
        storage_layout.addWidget(self.custom_radio, 5, 0)
        storage_layout.addWidget(self.path_edit, 5, 1)
        storage_layout.addWidget(self.browse_btn, 5, 2)
        
        # Enable/disable custom path controls based on radio selection
        def update_custom_path_controls():
            is_custom = self.custom_radio.isChecked()
            self.path_edit.setReadOnly(not is_custom)
            self.browse_btn.setEnabled(is_custom)
            if not is_custom:
                self.path_edit.clear()
        
        # Connect radio button changes
        self.home_radio.toggled.connect(update_custom_path_controls)
        self.portable_radio.toggled.connect(update_custom_path_controls)
        self.custom_radio.toggled.connect(update_custom_path_controls)
        
        # Initialize custom path controls state
        update_custom_path_controls()
        
        # Artifacts group
        artifacts_group = QGroupBox("Gallery Artifacts")
        artifacts_layout = QVBoxLayout(artifacts_group)
        artifacts_info = QLabel("JSON / BBcode files containing uploaded gallery details.")
        artifacts_info.setWordWrap(True)
        artifacts_info.setStyleSheet("color: #666; font-style: italic;")
        artifacts_layout.addWidget(artifacts_info)
        # Store in uploaded folder
        self.store_in_uploaded_check = QCheckBox("Save artifacts in '.uploaded' subfolder within the gallery")
        self.store_in_uploaded_check.setChecked(defaults.get('store_in_uploaded', True))
        artifacts_layout.addWidget(self.store_in_uploaded_check)

        # Store in central location
        self.store_in_central_check = QCheckBox("Save artifacts in central storage")
        self.store_in_central_check.setChecked(defaults.get('store_in_central', True))
        artifacts_layout.addWidget(self.store_in_central_check)

        # Theme & Display group
        theme_group = QGroupBox("Appearance / Theme")
        theme_layout = QGridLayout(theme_group)
        
        # Theme setting
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["light", "dark"])

        # Load current theme from QSettings
        if self.parent_window and hasattr(self.parent_window, 'settings'):
            current_theme = self.parent_window.settings.value('ui/theme', 'dark')
            index = self.theme_combo.findText(current_theme)
            if index >= 0:
                self.theme_combo.setCurrentIndex(index)
        
        # Add theme controls
        theme_label = QLabel("<b>Theme mode</b>:")
        theme_layout.addWidget(theme_label, 0, 0)
        theme_layout.addWidget(self.theme_combo, 0, 1)
        
        # Font size setting
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(6, 24)  # Reasonable range for UI fonts
        self.font_size_spin.setSuffix(" pt")
        self.font_size_spin.setToolTip("Base font size for the interface (affects table, labels, buttons)")
        
        # Load current font size from QSettings (default to 9pt)
        if self.parent_window and hasattr(self.parent_window, 'settings'):
            current_font_size = int(self.parent_window.settings.value('ui/font_size', 9))
            self.font_size_spin.setValue(current_font_size)
        else:
            self.font_size_spin.setValue(9)
        
        # Add font size controls
        font_label = QLabel("<b>Text size</b>:")
        theme_layout.addWidget(font_label, 1, 0)
        theme_layout.addWidget(self.font_size_spin, 1, 1)

        # Icons-only mode for quick settings buttons
        self.quick_settings_icons_only_check = QCheckBox("Show icons only on quick settings buttons")
        self.quick_settings_icons_only_check.setToolTip(
            "When enabled, quick settings buttons will always show icons only,\n"
            "regardless of available space (overrides adaptive text display)"
        )

        # Load current setting from QSettings
        if self.parent_window and hasattr(self.parent_window, 'settings'):
            icons_only = self.parent_window.settings.value('ui/quick_settings_icons_only', False, type=bool)
            self.quick_settings_icons_only_check.setChecked(icons_only)

        theme_layout.addWidget(self.quick_settings_icons_only_check, 2, 0, 1, 2)  # Row 2, span 2 columns

        # Show file host logos in worker table (default: True)
        self.show_worker_logos_check = QCheckBox("Show file host logos in upload workers table")
        self.show_worker_logos_check.setToolTip(
            "When enabled, shows file host logos instead of text names\n"
            "in the upload workers status table"
        )
        if self.parent_window and hasattr(self.parent_window, 'settings'):
            show_logos = self.parent_window.settings.value('ui/show_worker_logos', True, type=bool)
            self.show_worker_logos_check.setChecked(show_logos)

        theme_layout.addWidget(self.show_worker_logos_check, 3, 0, 1, 2)  # Row 3, span 2 columns

        # Set column stretch for 50/50 split
        theme_layout.setColumnStretch(0, 1)  # Label column 50%
        theme_layout.setColumnStretch(1, 1)  # Control column 50%
        
        # Add all groups to layout in 2x2 grid with 40/60 split
        grid_layout = QGridLayout()
        grid_layout.setVerticalSpacing(12)  # Extra vertical spacing between groups
        grid_layout.addWidget(upload_group, 0, 0)      # Top left
        grid_layout.addWidget(general_group, 0, 1)     # Top Right
        grid_layout.addWidget(thumb_group, 1, 0)       # Bottom left
        grid_layout.addWidget(theme_group, 1, 1)       # Bottom right
        grid_layout.addWidget(storage_group, 2, 0)     # Row 2 left
        grid_layout.addWidget(artifacts_group, 2, 1)   # Row 2 right

        # Set column stretch factors for 40/60 split
        grid_layout.setColumnStretch(0, 50)  # Left column 50%
        grid_layout.setColumnStretch(1, 50)  # Right column 50%
        
        layout.addLayout(grid_layout)
        layout.addStretch()
        
        # Connect change signals to mark tab as dirty
        self.thumbnail_size_combo.currentIndexChanged.connect(lambda: self.mark_tab_dirty(0))
        self.thumbnail_format_combo.currentIndexChanged.connect(lambda: self.mark_tab_dirty(0))
        self.max_retries_slider.valueChanged.connect(lambda: self.mark_tab_dirty(0))
        self.batch_size_slider.valueChanged.connect(lambda: self.mark_tab_dirty(0))
        self.connect_timeout_slider.valueChanged.connect(lambda: self.mark_tab_dirty(0))
        self.read_timeout_slider.valueChanged.connect(lambda: self.mark_tab_dirty(0))
        self.confirm_delete_check.toggled.connect(lambda: self.mark_tab_dirty(0))
        self.auto_rename_check.toggled.connect(lambda: self.mark_tab_dirty(0))
        self.auto_regenerate_bbcode_check.toggled.connect(lambda: self.mark_tab_dirty(0))
        self.auto_start_upload_check.toggled.connect(lambda: self.mark_tab_dirty(0))
        self.auto_clear_completed_check.toggled.connect(lambda: self.mark_tab_dirty(0))
        self.check_updates_checkbox.toggled.connect(lambda: self.mark_tab_dirty(0))
        self.store_in_uploaded_check.toggled.connect(lambda: self.mark_tab_dirty(0))
        self.store_in_central_check.toggled.connect(lambda: self.mark_tab_dirty(0))
        self.home_radio.toggled.connect(lambda: self.mark_tab_dirty(0))
        self.portable_radio.toggled.connect(lambda: self.mark_tab_dirty(0))
        self.custom_radio.toggled.connect(lambda: self.mark_tab_dirty(0))
        self.path_edit.textChanged.connect(lambda: self.mark_tab_dirty(0))
        self.theme_combo.currentIndexChanged.connect(lambda: self.mark_tab_dirty(0))
        self.font_size_spin.valueChanged.connect(lambda: self.mark_tab_dirty(0))
        self.quick_settings_icons_only_check.toggled.connect(lambda: self.mark_tab_dirty(0))
        self.show_worker_logos_check.toggled.connect(lambda: self.mark_tab_dirty(0))

        self.tab_widget.addTab(general_widget, "General")
        
    def setup_credentials_tab(self):
        """Setup the Credentials tab with integrated credential management"""
        credentials_widget = QWidget()
        layout = QVBoxLayout(credentials_widget)
        
        # Create and integrate the credential setup dialog
        self.credential_dialog = CredentialSetupDialog(self)
        self.credential_dialog.setParent(credentials_widget)
        self.credential_dialog.setWindowFlags(Qt.WindowType.Widget)  # Make it a child widget
        self.credential_dialog.setModal(False)  # Not modal when embedded

        # Add the credential dialog to the layout
        layout.addWidget(self.credential_dialog)
        
        self.tab_widget.addTab(credentials_widget, "Credentials")
        
    def setup_templates_tab(self):
        """Setup the Templates tab with integrated template management and selection"""
        templates_widget = QWidget()
        layout = QVBoxLayout(templates_widget)
        
        # Create and integrate the template manager dialog
        self.template_dialog = TemplateManagerDialog(self)
        self.template_dialog.setParent(templates_widget)
        self.template_dialog.setWindowFlags(Qt.WindowType.Widget)  # Make it a child widget
        self.template_dialog.setModal(False)  # Not modal when embedded
        
        # Add the template dialog to the layout
        layout.addWidget(self.template_dialog)
        
        self.tab_widget.addTab(templates_widget, "Templates")
        
    def setup_tabs_tab(self):
        """Setup the Tabs management tab"""
        tabs_widget = QWidget()
        # Keep a reference to prevent garbage collection
        self.tabs_widget_ref = tabs_widget
        layout = QVBoxLayout(tabs_widget)
        
        # Initialize tab manager reference
        self.tab_manager = None
        if self.parent_window and hasattr(self.parent_window, 'tab_manager'):
            self.tab_manager = self.parent_window.tab_manager
        
        # Create splitter for better layout
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)
        
        # Left side - Tab management
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        
        # Tab list group
        tab_list_group = QGroupBox("Tab Management")
        tab_list_layout = QVBoxLayout(tab_list_group)
        
        # Tab table
        self.tabs_table = QTableWidget()
        self.tabs_table.setColumnCount(4)
        self.tabs_table.setHorizontalHeaderLabels(["Name", "Type", "Count", "Hidden"])
        self.tabs_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tabs_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tabs_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tabs_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.tabs_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabs_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tabs_table.itemSelectionChanged.connect(self.on_tab_selection_changed)
        tab_list_layout.addWidget(self.tabs_table)
        
        # Tab action buttons
        tab_buttons_layout = QHBoxLayout()
        
        self.create_tab_btn = QPushButton("Create Tab")
        self.create_tab_btn.clicked.connect(self.create_new_tab)
        tab_buttons_layout.addWidget(self.create_tab_btn)
        
        self.rename_tab_btn = QPushButton("Rename")
        self.rename_tab_btn.clicked.connect(self.rename_selected_tab)
        self.rename_tab_btn.setEnabled(False)
        tab_buttons_layout.addWidget(self.rename_tab_btn)
        
        self.delete_tab_btn = QPushButton("Delete")
        self.delete_tab_btn.clicked.connect(self.delete_selected_tab)
        self.delete_tab_btn.setEnabled(False)
        tab_buttons_layout.addWidget(self.delete_tab_btn)
        
        tab_buttons_layout.addStretch()
        
        self.move_tab_up_btn = QPushButton("Move Up")
        self.move_tab_up_btn.clicked.connect(self.move_tab_up)
        self.move_tab_up_btn.setEnabled(False)
        tab_buttons_layout.addWidget(self.move_tab_up_btn)
        
        self.move_tab_down_btn = QPushButton("Move Down")
        self.move_tab_down_btn.clicked.connect(self.move_tab_down)
        self.move_tab_down_btn.setEnabled(False)
        tab_buttons_layout.addWidget(self.move_tab_down_btn)
        
        tab_list_layout.addLayout(tab_buttons_layout)
        left_layout.addWidget(tab_list_group)
        
        # Tab preferences group
        tab_prefs_group = QGroupBox("Tab Preferences")
        tab_prefs_layout = QGridLayout(tab_prefs_group)
        
        # Default tab for new galleries
        tab_prefs_layout.addWidget(QLabel("Default tab for new galleries:"), 0, 0)
        self.default_tab_combo = QComboBox()
        self.default_tab_combo.currentTextChanged.connect(self.on_default_tab_changed)
        tab_prefs_layout.addWidget(self.default_tab_combo, 0, 1)
        
        # Hide/Show selected tab
        self.hide_tab_check = QCheckBox("Hide selected tab")
        self.hide_tab_check.setEnabled(False)
        self.hide_tab_check.toggled.connect(self.on_hide_tab_toggled)
        tab_prefs_layout.addWidget(self.hide_tab_check, 1, 0, 1, 2)
        
        # Reset tab order button
        self.reset_order_btn = QPushButton("Reset to Default Order")
        self.reset_order_btn.clicked.connect(self.reset_tab_order)
        tab_prefs_layout.addWidget(self.reset_order_btn, 2, 0, 1, 2)
        
        left_layout.addWidget(tab_prefs_group)
        left_layout.addStretch()
        
        # Add to splitter
        splitter.addWidget(left_widget)
        splitter.setSizes([700])  # Single widget takes full space
        
        # Load current tabs and settings
        self.load_tabs_settings()

        # Tab management temporarily hidden while deciding on functionality
        # self.tab_widget.addTab(tabs_widget, "Tabs")
    
    def load_tabs_settings(self):
        """Load current tabs and settings"""
        # Clear existing table
        self.tabs_table.setRowCount(0)
        
        if not self.tab_manager:
            # Show message if no tab manager available
            self.tabs_table.setRowCount(1)
            item = QTableWidgetItem("Tab management not available")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.tabs_table.setItem(0, 0, item)
            self._disable_tab_controls()
            return
        
        try:
            # Load all tabs (including hidden)
            tabs = self.tab_manager.get_all_tabs(include_hidden=True)
            
            # Populate table
            self.tabs_table.setRowCount(len(tabs))
            for row, tab in enumerate(tabs):
                # Name
                name_item = QTableWidgetItem(tab.name)
                name_item.setData(Qt.ItemDataRole.UserRole, tab)  # Store tab info
                self.tabs_table.setItem(row, 0, name_item)
                
                # Type
                type_item = QTableWidgetItem(tab.tab_type.capitalize())
                if tab.tab_type == 'system':
                    type_item.setBackground(QColor("#f0f8ff"))
                self.tabs_table.setItem(row, 1, type_item)
                
                # Gallery count
                count_item = QTableWidgetItem(str(tab.gallery_count))
                count_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.tabs_table.setItem(row, 2, count_item)
                
                # Hidden status
                hidden_item = QTableWidgetItem("Yes" if tab.is_hidden else "No")
                hidden_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if tab.is_hidden:
                    hidden_item.setBackground(QColor("#ffe6e6"))
                self.tabs_table.setItem(row, 3, hidden_item)
            
            # Update default tab combo
            self.default_tab_combo.clear()
            visible_tabs = [tab.name for tab in tabs if not tab.is_hidden]
            self.default_tab_combo.addItems(visible_tabs)
            
            # Set current default tab
            current_default = self.tab_manager.last_active_tab
            index = self.default_tab_combo.findText(current_default)
            if index >= 0:
                self.default_tab_combo.setCurrentIndex(index)
            
            
        except Exception as e:
            log(f"Error loading tabs settings: {e}", level="error", category="settings")
            self._disable_tab_controls()
    
    def _disable_tab_controls(self):
        """Disable all tab management controls"""
        controls = [
            self.create_tab_btn, self.rename_tab_btn, self.delete_tab_btn,
            self.move_tab_up_btn, self.move_tab_down_btn, self.hide_tab_check,
            self.reset_order_btn
        ]
        for control in controls:
            control.setEnabled(False)
    
    def on_tab_selection_changed(self):
        """Handle tab selection change"""
        selected_items = self.tabs_table.selectedItems()
        if not selected_items or not self.tab_manager:
            self._update_tab_buttons(None)
            return
        
        # Get selected tab info
        row = selected_items[0].row()
        name_item = self.tabs_table.item(row, 0)
        tab_info = name_item.data(Qt.ItemDataRole.UserRole)
        
        self._update_tab_buttons(tab_info)
    
    def _update_tab_buttons(self, tab_info):
        """Update tab action buttons based on selection"""
        if not tab_info:
            self.rename_tab_btn.setEnabled(False)
            self.delete_tab_btn.setEnabled(False)
            self.move_tab_up_btn.setEnabled(False)
            self.move_tab_down_btn.setEnabled(False)
            self.hide_tab_check.setEnabled(False)
            return
        
        # Can only edit user tabs (not system tabs)
        is_user_tab = tab_info.tab_type == 'user'
        can_delete = is_user_tab and tab_info.name not in ['Main']
        
        self.rename_tab_btn.setEnabled(is_user_tab)
        self.delete_tab_btn.setEnabled(can_delete)
        
        # Movement buttons - can move any tab
        current_row = self.tabs_table.currentRow()
        can_move_up = current_row > 0
        can_move_down = current_row < (self.tabs_table.rowCount() - 1)
        
        self.move_tab_up_btn.setEnabled(can_move_up)
        self.move_tab_down_btn.setEnabled(can_move_down)
        
        # Hide/show functionality
        self.hide_tab_check.setEnabled(True)
        self.hide_tab_check.blockSignals(True)
        self.hide_tab_check.setChecked(tab_info.is_hidden)
        self.hide_tab_check.blockSignals(False)
    
    def create_new_tab(self):
        """Create a new user tab"""
        if not self.tab_manager:
            return
        
        # Get tab name from user
        name, ok = QInputDialog.getText(self, "Create New Tab", "Tab name:")
        if not ok or not name.strip():
            return
        
        name = name.strip()
        
        try:
            # Create tab using TabManager
            tab_info = self.tab_manager.create_tab(name)
            
            # Refresh the display
            self.load_tabs_settings()
            
            # Select the new tab
            for row in range(self.tabs_table.rowCount()):
                item = self.tabs_table.item(row, 0)
                if item and item.text() == name:
                    self.tabs_table.selectRow(row)
                    break
            
            # Show success message
            show_info(self, "Success", f"Tab '{name}' created successfully!")
            
        except ValueError as e:
            # Show error message
            show_error(self, "Error", str(e))
    
    def rename_selected_tab(self):
        """Rename the selected tab"""
        if not self.tab_manager:
            return
        
        current_row = self.tabs_table.currentRow()
        if current_row < 0:
            return
        
        name_item = self.tabs_table.item(current_row, 0)
        tab_info = name_item.data(Qt.ItemDataRole.UserRole)
        
        if not tab_info or tab_info.tab_type != 'user':
            return
        
        # Get new name from user
        new_name, ok = QInputDialog.getText(
            self, "Rename Tab", "New name:", text=tab_info.name
        )
        if not ok or not new_name.strip() or new_name.strip() == tab_info.name:
            return
        
        new_name = new_name.strip()
        
        try:
            # Rename using TabManager
            success = self.tab_manager.update_tab(tab_info.name, new_name=new_name)
            
            if success:
                # Refresh the display
                self.load_tabs_settings()
                
                # Show success message
                show_info(self, "Success", f"Tab renamed to '{new_name}' successfully!")
            
        except ValueError as e:
            # Show error message
            show_error(self, "Error", str(e))
    
    def delete_selected_tab(self):
        """Delete the selected tab"""
        if not self.tab_manager:
            return
        
        current_row = self.tabs_table.currentRow()
        if current_row < 0:
            return
        
        name_item = self.tabs_table.item(current_row, 0)
        tab_info = name_item.data(Qt.ItemDataRole.UserRole)
        
        if not tab_info or tab_info.tab_type != 'user':
            return
        
        # Don't allow deleting Main
        if tab_info.name in ['Main']:
            show_warning(self, "Cannot Delete", f"Cannot delete the {tab_info.name} tab.")
            return
        
        # Confirm deletion
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Icon.Question)
        msg_box.setWindowTitle("Confirm Delete")
        msg_box.setText(f"Delete tab '{tab_info.name}'?\n\n"
                       f"All galleries in this tab will be moved to the Main tab.")
        msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg_box.setDefaultButton(QMessageBox.StandardButton.No)
        
        # Use non-blocking approach - keep existing pattern for async behavior
        msg_box.finished.connect(lambda result: self._handle_delete_confirmation(result, tab_info))
        msg_box.open()
    
    def _handle_delete_confirmation(self, result, tab_info):
        """Handle tab deletion confirmation"""
        if result != QMessageBox.StandardButton.Yes:
            return
        
        try:
            # Delete using TabManager
            success, gallery_count = self.tab_manager.delete_tab(tab_info.name, "Main")
            
            if success:
                # Refresh the display
                self.load_tabs_settings()
                
                # Show success message
                success_text = f"Tab '{tab_info.name}' deleted successfully!\n{gallery_count} galleries moved to Main tab."
                show_info(self, "Success", success_text)
            
        except ValueError as e:
            # Show error message
            show_error(self, "Error", str(e))
    
    def move_tab_up(self):
        """Move selected tab up in display order"""
        self._move_tab(-1)
    
    def move_tab_down(self):
        """Move selected tab down in display order"""
        self._move_tab(1)
    
    def _move_tab(self, direction):
        """Move tab up (-1) or down (1) in display order"""
        if not self.tab_manager:
            return
        
        current_row = self.tabs_table.currentRow()
        if current_row < 0:
            return
        
        new_row = current_row + direction
        if new_row < 0 or new_row >= self.tabs_table.rowCount():
            return
        
        # Get current custom ordering
        custom_order = self.tab_manager.get_custom_tab_order()
        
        # Get tab names at current and target positions
        current_tab_name = self.tabs_table.item(current_row, 0).text()
        target_tab_name = self.tabs_table.item(new_row, 0).text()
        
        # Assign new order values
        if not custom_order:
            # Create initial ordering based on current table order
            for row in range(self.tabs_table.rowCount()):
                tab_name = self.tabs_table.item(row, 0).text()
                custom_order[tab_name] = row * 10  # Leave gaps for insertion
        
        # Swap the order values
        current_order = custom_order.get(current_tab_name, current_row * 10)
        target_order = custom_order.get(target_tab_name, new_row * 10)
        
        custom_order[current_tab_name] = target_order
        custom_order[target_tab_name] = current_order
        
        # Apply the new ordering
        self.tab_manager.set_custom_tab_order(custom_order)
        
        # Refresh display and maintain selection
        self.load_tabs_settings()
        self.tabs_table.selectRow(new_row)
    
    def reset_tab_order(self):
        """Reset tab order to database defaults"""
        if not self.tab_manager:
            return
        
        # Confirm reset
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Icon.Question)
        msg_box.setWindowTitle("Reset Tab Order")
        msg_box.setText("Reset tab order to defaults?")
        msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg_box.setDefaultButton(QMessageBox.StandardButton.No)
        
        # Use non-blocking approach
        msg_box.finished.connect(self._handle_reset_order_confirmation)
        msg_box.open()
    
    def _handle_reset_order_confirmation(self, result):
        """Handle reset order confirmation"""
        if result == QMessageBox.StandardButton.Yes:
            self.tab_manager.reset_tab_order()
            self.load_tabs_settings()
    
    def on_default_tab_changed(self, tab_name):
        """Handle default tab selection change"""
        if self.tab_manager and tab_name:
            self.tab_manager.last_active_tab = tab_name
    
    def on_hide_tab_toggled(self, hidden):
        """Handle hide/show tab toggle"""
        if not self.tab_manager:
            return
        
        current_row = self.tabs_table.currentRow()
        if current_row < 0:
            return
        
        name_item = self.tabs_table.item(current_row, 0)
        tab_name = name_item.text()
        
        # Update tab visibility
        self.tab_manager.set_tab_hidden(tab_name, hidden)
        
        # Refresh display
        self.load_tabs_settings()
    
        
    def setup_logs_tab(self):
        """Setup the Logs tab with log settings"""
        from src.gui.dialogs.log_settings_widget import LogSettingsWidget
        self.log_settings_widget = LogSettingsWidget(self)
        self.log_settings_widget.settings_changed.connect(lambda: self.mark_tab_dirty(3))  # Logs tab is at index 3 (Tabs/Icons hidden)
        self.log_settings_widget.load_settings()  # Load current settings
        self.tab_widget.addTab(self.log_settings_widget, "Logs")
        
    def setup_scanning_tab(self):
        """Setup the Image Scanning tab"""
        scanning_widget = QWidget()
        layout = QVBoxLayout(scanning_widget)
        
        # Info label
        info_label = QLabel("Configure image scanning behavior for performance optimization.")
        info_label.setWordWrap(True)
        info_label.setProperty("class", "tab-description")
        info_label.setMaximumHeight(40)  # Consistent with Icon Manager tab
        from PyQt6.QtWidgets import QSizePolicy
        info_label.setSizePolicy(info_label.sizePolicy().horizontalPolicy(), 
                                QSizePolicy.Policy.Fixed)  # Fixed vertical size policy
        layout.addWidget(info_label)
        
        # Scanning strategy group
        strategy_group = QGroupBox("Scanning Strategy")
        strategy_layout = QVBoxLayout(strategy_group)
        
        # Fast scanning with imghdr
        self.fast_scan_check = QCheckBox("Use fast corruption checking (imghdr)")
        self.fast_scan_check.setChecked(True)  # Default enabled
        strategy_layout.addWidget(self.fast_scan_check)
        
        # Separator line
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        strategy_layout.addWidget(separator)

        # PIL Sampling Section
        sampling_label = QLabel("<b>Dimension Calculation Sampling</b>")
        strategy_layout.addWidget(sampling_label)

        # Sampling Method
        method_layout = QHBoxLayout()
        method_label = QLabel("Method:")
        method_layout.addWidget(method_label)

        self.sampling_fixed_radio = QRadioButton("Fixed count")
        self.sampling_fixed_radio.setProperty("class", "scanning-radio")
        self.sampling_fixed_radio.setChecked(True)
        method_layout.addWidget(self.sampling_fixed_radio)

        self.sampling_fixed_spin = QSpinBox()
        self.sampling_fixed_spin.setRange(1, 100)
        self.sampling_fixed_spin.setValue(25)
        self.sampling_fixed_spin.setSuffix(" images")
        method_layout.addWidget(self.sampling_fixed_spin)

        self.sampling_percent_radio = QRadioButton("Percentage")
        self.sampling_percent_radio.setProperty("class", "scanning-radio")
        method_layout.addWidget(self.sampling_percent_radio)

        self.sampling_percent_spin = QSpinBox()
        self.sampling_percent_spin.setRange(1, 100)
        self.sampling_percent_spin.setValue(10)
        self.sampling_percent_spin.setSuffix("%")
        self.sampling_percent_spin.setEnabled(False)
        method_layout.addWidget(self.sampling_percent_spin)

        method_layout.addStretch()
        strategy_layout.addLayout(method_layout)

        # Create button group for sampling method (Fixed vs Percentage)
        self.sampling_method_group = QButtonGroup(self)
        self.sampling_method_group.addButton(self.sampling_fixed_radio)
        self.sampling_method_group.addButton(self.sampling_percent_radio)

        # Connect radio buttons to enable/disable spinboxes
        self.sampling_fixed_radio.toggled.connect(lambda checked: self.sampling_fixed_spin.setEnabled(checked))
        self.sampling_fixed_radio.toggled.connect(lambda checked: self.sampling_percent_spin.setEnabled(not checked))

        # Exclusions Section
        exclusions_label = QLabel("<b>Exclusions</b> (skip these images from sampling)")
        exclusions_label.setStyleSheet("margin-top: 10px;")
        strategy_layout.addWidget(exclusions_label)

        # Exclude first/last checkboxes
        position_layout = QHBoxLayout()
        self.exclude_first_check = QCheckBox("Skip first image")
        self.exclude_first_check.setToolTip("Often cover/poster image")
        position_layout.addWidget(self.exclude_first_check)

        self.exclude_last_check = QCheckBox("Skip last image")
        self.exclude_last_check.setToolTip("Often credits/logo image")
        position_layout.addWidget(self.exclude_last_check)
        position_layout.addStretch()
        strategy_layout.addLayout(position_layout)

        # Exclude small images
        small_layout = QHBoxLayout()
        self.exclude_small_check = QCheckBox("Skip images smaller than")
        small_layout.addWidget(self.exclude_small_check)

        self.exclude_small_spin = QSpinBox()
        self.exclude_small_spin.setRange(10, 90)
        self.exclude_small_spin.setValue(50)
        self.exclude_small_spin.setSuffix("% of largest")
        self.exclude_small_spin.setEnabled(False)
        small_layout.addWidget(self.exclude_small_spin)

        small_layout.addWidget(QLabel("(thumbnails, previews)"))
        small_layout.addStretch()
        strategy_layout.addLayout(small_layout)

        self.exclude_small_check.toggled.connect(self.exclude_small_spin.setEnabled)

        # Exclude filename patterns
        pattern_layout = QVBoxLayout()
        pattern_h_layout = QHBoxLayout()
        self.exclude_patterns_check = QCheckBox("Skip filenames matching:")
        pattern_h_layout.addWidget(self.exclude_patterns_check)
        pattern_h_layout.addStretch()
        pattern_layout.addLayout(pattern_h_layout)

        self.exclude_patterns_edit = QLineEdit()
        self.exclude_patterns_edit.setPlaceholderText("e.g., cover*, poster*, thumb*, *_small.* (comma-separated patterns)")
        self.exclude_patterns_edit.setEnabled(False)
        pattern_layout.addWidget(self.exclude_patterns_edit)
        strategy_layout.addLayout(pattern_layout)

        self.exclude_patterns_check.toggled.connect(self.exclude_patterns_edit.setEnabled)

        # Statistics Calculation
        stats_label = QLabel("<b>Statistics Calculation</b>")
        stats_label.setStyleSheet("margin-top: 10px;")
        strategy_layout.addWidget(stats_label)

        stats_layout = QHBoxLayout()
        self.stats_exclude_outliers_check = QCheckBox("Exclude outliers (±1.5 IQR)")
        self.stats_exclude_outliers_check.setToolTip("Remove images with dimensions outside 1.5x interquartile range")
        stats_layout.addWidget(self.stats_exclude_outliers_check)
        stats_layout.addStretch()
        strategy_layout.addLayout(stats_layout)

        # Average Method
        avg_layout = QHBoxLayout()
        avg_layout.addWidget(QLabel("Average method:"))
        self.avg_mean_radio = QRadioButton("Mean")
        self.avg_mean_radio.setProperty("class", "scanning-radio")
        self.avg_mean_radio.setToolTip("Arithmetic mean (sum / count)")
        # Default is median, not mean
        avg_layout.addWidget(self.avg_mean_radio)

        self.avg_median_radio = QRadioButton("Median")
        self.avg_median_radio.setProperty("class", "scanning-radio")
        self.avg_median_radio.setToolTip("Middle value (more robust to outliers)")
        self.avg_median_radio.setChecked(True)
        avg_layout.addWidget(self.avg_median_radio)
        avg_layout.addStretch()
        strategy_layout.addLayout(avg_layout)
        

        # Create button group for average method (Mean vs Median)
        self.avg_method_group = QButtonGroup(self)
        self.avg_method_group.addButton(self.avg_mean_radio)
        self.avg_method_group.addButton(self.avg_median_radio)
        
        # Performance info
        perf_info = QLabel("Fast mode uses imghdr for corruption detection and PIL for dimension calculations and to rescan images that fail imghdr test.")
        perf_info.setWordWrap(True)
        perf_info.setStyleSheet("color: #666; font-style: italic;")
        strategy_layout.addWidget(perf_info)
        
        layout.addWidget(strategy_group)
        layout.addStretch()
        
        # Connect change signals to mark tab as dirty (tab index 4 for scanning after hiding Tabs/Icons)
        self.fast_scan_check.toggled.connect(lambda: self.mark_tab_dirty(4))

        # Connect new sampling controls
        self.sampling_fixed_radio.toggled.connect(lambda: self.mark_tab_dirty(4))
        self.sampling_percent_radio.toggled.connect(lambda: self.mark_tab_dirty(4))
        self.sampling_fixed_spin.valueChanged.connect(lambda: self.mark_tab_dirty(4))
        self.sampling_percent_spin.valueChanged.connect(lambda: self.mark_tab_dirty(4))

        # Connect exclusion controls
        self.exclude_first_check.toggled.connect(lambda: self.mark_tab_dirty(4))
        self.exclude_last_check.toggled.connect(lambda: self.mark_tab_dirty(4))
        self.exclude_small_check.toggled.connect(lambda: self.mark_tab_dirty(4))
        self.exclude_small_spin.valueChanged.connect(lambda: self.mark_tab_dirty(4))
        self.exclude_patterns_check.toggled.connect(lambda: self.mark_tab_dirty(4))
        self.exclude_patterns_edit.textChanged.connect(lambda: self.mark_tab_dirty(4))

        # Connect stats calculation controls
        self.stats_exclude_outliers_check.toggled.connect(lambda: self.mark_tab_dirty(4))
        self.avg_mean_radio.toggled.connect(lambda: self.mark_tab_dirty(4))
        self.avg_median_radio.toggled.connect(lambda: self.mark_tab_dirty(4))
        
        self.tab_widget.addTab(scanning_widget, "Image Scan")

    def setup_external_apps_tab(self):
        """Setup the External Apps tab for running external programs on gallery events"""
        external_widget = QWidget()
        layout = QVBoxLayout(external_widget)

        # Intro text
        intro_label = QLabel("Run external programs at different stages of gallery processing. "
                            "Programs can output JSON to populate ext1-4 fields for use in templates.")
        intro_label.setWordWrap(True)
        layout.addWidget(intro_label)

        # Execution mode
        exec_mode_group = QGroupBox("Execution Mode")
        exec_mode_layout = QHBoxLayout(exec_mode_group)
        self.hooks_parallel_radio = QRadioButton("Run hooks in parallel")
        self.hooks_sequential_radio = QRadioButton("Run hooks sequentially")
        self.hooks_parallel_radio.setChecked(True)
        exec_mode_layout.addWidget(self.hooks_parallel_radio)
        exec_mode_layout.addWidget(self.hooks_sequential_radio)
        exec_mode_layout.addStretch()
        layout.addWidget(exec_mode_group)

        # Create hook sections
        self._create_hook_section(layout, "On Gallery Added", "added")
        self._create_hook_section(layout, "On Gallery Started", "started")
        self._create_hook_section(layout, "On Gallery Completed", "completed")

        layout.addStretch()
        self.tab_widget.addTab(external_widget, "Hooks")

        # Connect signals to mark tab as dirty (tab index 5 after hiding Tabs and Icons)
        self.hooks_parallel_radio.toggled.connect(lambda: self.mark_tab_dirty(5))
        self.hooks_sequential_radio.toggled.connect(lambda: self.mark_tab_dirty(5))
        for hook_type in ['added', 'started', 'completed']:
            getattr(self, f'hook_{hook_type}_enabled').toggled.connect(lambda: self.mark_tab_dirty(5))
            getattr(self, f'hook_{hook_type}_command').textChanged.connect(lambda: self.mark_tab_dirty(5))
            getattr(self, f'hook_{hook_type}_show_console').toggled.connect(lambda: self.mark_tab_dirty(5))

    def _create_hook_section(self, parent_layout, title, hook_type):
        """Create a compact section for configuring a single hook"""
        from PyQt6.QtGui import QFontDatabase

        group = QGroupBox(title)
        layout = QVBoxLayout(group)
        hook_titles = {
            'added': 'added to the queue',
            'started': 'started',
            'completed': 'finished uploading'
        }
        # Top row: Enable checkbox + Configure button
        top_row = QHBoxLayout()
        enable_check = QCheckBox(f"Enable this hook: called when galleries are {hook_titles.get(hook_type, hook_type.title())}")
        setattr(self, f'hook_{hook_type}_enabled', enable_check)
        top_row.addWidget(enable_check, 2)  # Stretch factor 2 (left 2/3)

        # Configure button - use descriptive hook title
        configure_btn = QPushButton(f"Configure Hook")
        configure_btn.setToolTip(f"Configure and test '{hook_titles.get(hook_type, hook_type.title())}' hook - set up command, test execution, and map JSON output")
        configure_btn.clicked.connect(lambda: self._show_json_mapping_dialog(hook_type))
        top_row.addWidget(configure_btn, 1)  # Stretch factor 1 (right 1/3)

        layout.addLayout(top_row)

        # Command row with monospace font
        command_layout = QHBoxLayout()
        command_layout.addWidget(QLabel("Command:"))

        command_input = QLineEdit()
        command_input.setPlaceholderText(f'python script.py "%p" or muh.py gofile "%z"')
        # Apply monospace font
        mono_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        command_input.setFont(mono_font)
        setattr(self, f'hook_{hook_type}_command', command_input)
        command_layout.addWidget(command_input, 1)  # Stretch factor 1
        layout.addLayout(command_layout)

        # Hidden storage for settings
        show_console_check = QCheckBox()
        show_console_check.setVisible(False)
        setattr(self, f'hook_{hook_type}_show_console', show_console_check)

        for i in range(1, 5):
            key_input = QLineEdit()
            key_input.setVisible(False)
            setattr(self, f'hook_{hook_type}_key{i}', key_input)

        parent_layout.addWidget(group)

    def _get_available_vars(self, hook_type):
        """Get available variables for a hook type"""
        base_vars = "%N, %T, %p, %C, %s, %t, %e1-%e4, %c1-%c4"
        if hook_type == "completed":
            return f"{base_vars}, %g, %j, %b, %z"
        else:
            return base_vars

    def _browse_for_program(self, hook_type):
        """Browse for executable program"""
        from PyQt6.QtWidgets import QFileDialog
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Program",
            "",
            "Executables (*.exe *.bat *.cmd *.py);;All Files (*.*)"
        )
        if file_path:
            command_input = getattr(self, f'hook_{hook_type}_command')
            command_input.setText(f'"{file_path}"')

    def _show_variable_menu(self, hook_type):
        """Show menu to insert variable at cursor position"""
        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtGui import QCursor

        menu = QMenu(self)

        # Define variables and their descriptions
        variables = [
            ("%N", "Gallery name"),
            ("%T", "Tab name"),
            ("%p", "Gallery folder path"),
            ("%C", "Number of images"),
        ]

        # Add completed-only variables
        if hook_type == "completed":
            variables.extend([
                ("%g", "Gallery ID"),
                ("%j", "JSON artifact path"),
                ("%b", "BBCode artifact path"),
                ("%z", "ZIP archive path (if exists)"),
            ])

        # Create menu actions
        for var, desc in variables:
            action = menu.addAction(f"{var}  -  {desc}")
            action.triggered.connect(lambda checked, v=var: self._insert_variable(hook_type, v))

        menu.exec(QCursor.pos())

    def _insert_variable(self, hook_type, variable):
        """Insert variable at cursor position in command input"""
        command_input = getattr(self, f'hook_{hook_type}_command')
        cursor_pos = command_input.cursorPosition()
        current_text = command_input.text()
        new_text = current_text[:cursor_pos] + variable + current_text[cursor_pos:]
        command_input.setText(new_text)
        command_input.setCursorPosition(cursor_pos + len(variable))
        command_input.setFocus()

    def _show_json_mapping_dialog(self, hook_type):
        """Show dialog for configuring JSON key mappings"""
        from PyQt6.QtWidgets import QDialog, QTextEdit
        from PyQt6.QtGui import QFont, QFontDatabase

        # Map hook types to friendly names
        hook_names = {
            'added': 'On Gallery Added',
            'started': 'On Gallery Started',
            'completed': 'On Gallery Completed'
        }

        dialog = QDialog(self)
        dialog.setWindowTitle(f"Command Builder & JSON Mapper - {hook_names.get(hook_type, hook_type.title())}")
        dialog.setModal(True)
        dialog.resize(850, 750)

        layout = QVBoxLayout(dialog)

        # Command Builder section (moved to top)
        command_group = QGroupBox(f"Command Builder - {hook_names.get(hook_type, hook_type.title())}")
        command_layout = QVBoxLayout(command_group)

        # Command input with helper - Now using larger multiline editor
        command_input_layout = QHBoxLayout()
        command_label = QLabel("Command Template:")
        command_label.setStyleSheet("font-weight: bold;")
        command_input_layout.addWidget(command_label)

        # Insert variable button
        insert_var_btn = QPushButton("Insert % Variable ▼")
        insert_var_btn.setToolTip("Insert a variable at cursor position (or type % to see options)")
        command_input_layout.addWidget(insert_var_btn)

        # Run test button (moved up here)
        test_btn = QPushButton("▶ Run Test Command")
        test_btn.setToolTip("Execute the command with test data")
        test_btn.setStyleSheet("font-weight: bold;")
        command_input_layout.addWidget(test_btn)

        command_input_layout.addStretch()
        command_layout.addLayout(command_input_layout)

        # Variable definitions for both menu and autocomplete (defined early for use in class)
        base_variables = [
            ("%N", "Gallery name"),
            ("%T", "Tab name"),
            ("%p", "Gallery folder path"),
            ("%C", "Number of images"),
            ("%s", "Gallery size in bytes"),
            ("%t", "Template name"),
            ("", ""),  # Separator
            ("%e1", "ext1 field value"),
            ("%e2", "ext2 field value"),
            ("%e3", "ext3 field value"),
            ("%e4", "ext4 field value"),
            ("", ""),  # Separator
            ("%c1", "custom1 field value"),
            ("%c2", "custom2 field value"),
            ("%c3", "custom3 field value"),
            ("%c4", "custom4 field value"),
        ]

        # Additional variables for completed events
        if hook_type == "completed":
            base_variables.insert(4, ("%g", "Gallery ID"))
            base_variables.insert(5, ("%j", "JSON artifact path"))
            base_variables.insert(6, ("%b", "BBCode artifact path"))
            base_variables.insert(7, ("%z", "ZIP archive path"))

        # Custom QTextEdit with autocomplete support
        class AutoCompleteTextEdit(QTextEdit):
            """QTextEdit with variable autocomplete on % key"""
            def __init__(self, variables, parent=None):
                super().__init__(parent)
                self.variables = [(var, desc) for var, desc in variables if var]
                self.completer = None
                self.setup_completer()

            def setup_completer(self):
                from PyQt6.QtWidgets import QCompleter
                from PyQt6.QtCore import Qt, QStringListModel

                # Create list of completion items with descriptions
                self.completion_items = [f"{var}  -  {desc}" for var, desc in self.variables]
                self.var_only = [var for var, _ in self.variables]

                model = QStringListModel(self.completion_items)
                self.completer = QCompleter(model, self)
                self.completer.setWidget(self)
                self.completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
                self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseSensitive)
                self.completer.activated.connect(self.insert_completion)

            def insert_completion(self, completion):
                """Insert the selected variable at cursor"""
                # Extract just the variable part (before the ' - ')
                var = completion.split('  -  ')[0]

                cursor = self.textCursor()

                # Remove the % and any partial text after it
                cursor.movePosition(cursor.MoveOperation.Left, cursor.MoveMode.KeepAnchor,
                                  len(self.completer.completionPrefix()) + 1)
                cursor.removeSelectedText()

                # Insert the variable
                cursor.insertText(var)
                self.setTextCursor(cursor)

            def keyPressEvent(self, event):
                from PyQt6.QtCore import Qt

                # Handle completer popup navigation
                if self.completer and self.completer.popup().isVisible():
                    if event.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return,
                                      Qt.Key.Key_Escape, Qt.Key.Key_Tab):
                        event.ignore()
                        return

                # Call parent to handle normal key input
                super().keyPressEvent(event)

                # Show completer when % is typed
                if event.text() == '%':
                    self.show_completions('')
                # Update completer filter as user types after %
                elif self.completer and self.completer.popup().isVisible():
                    # Get text after the last %
                    cursor = self.textCursor()
                    cursor.select(cursor.SelectionType.LineUnderCursor)
                    line_text = cursor.selectedText()

                    # Find the last % before cursor
                    cursor_pos = self.textCursor().positionInBlock()
                    last_percent = line_text.rfind('%', 0, cursor_pos)

                    if last_percent >= 0:
                        prefix = line_text[last_percent + 1:cursor_pos]
                        self.show_completions(prefix)
                    else:
                        self.completer.popup().hide()

            def show_completions(self, prefix):
                """Show completion popup with filtered results"""
                from PyQt6.QtCore import QRect

                self.completer.setCompletionPrefix(prefix)
                self.completer.complete()

                # Position popup at cursor
                cursor_rect = self.cursorRect()
                cursor_rect.setWidth(self.completer.popup().sizeHintForColumn(0)
                                   + self.completer.popup().verticalScrollBar().sizeHint().width())
                self.completer.complete(cursor_rect)

        # Get current command and create autocomplete text editor
        command_input = AutoCompleteTextEdit(base_variables, dialog)
        current_command = getattr(self, f'hook_{hook_type}_command').text()
        command_input.setPlainText(current_command)
        command_input.setPlaceholderText(f'e.g., python script.py "%p" "%N"\nor: C:\\program.exe "%g" --output "%j"')

        # Apply monospace font with larger size
        mono_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        mono_font.setPointSize(11)  # Larger font
        command_input.setFont(mono_font)
        command_input.setMaximumHeight(120)  # Limit height but allow multiple lines
        command_input.setObjectName("commandInput")
        command_layout.addWidget(command_input)

        def show_var_menu():
            from PyQt6.QtWidgets import QMenu
            from PyQt6.QtGui import QCursor
            menu = QMenu(dialog)

            for var, desc in base_variables:
                if not var:  # Separator
                    menu.addSeparator()
                else:
                    action = menu.addAction(f"{var}  -  {desc}")
                    action.triggered.connect(lambda checked, v=var: insert_variable_in_dialog(v))

            menu.exec(QCursor.pos())

        def insert_variable_in_dialog(variable):
            cursor = command_input.textCursor()
            cursor.insertText(variable)
            command_input.setFocus()

        insert_var_btn.clicked.connect(show_var_menu)

        # Preview section - shows resolved command
        preview_label = QLabel("Preview (with test data):")
        preview_label.setStyleSheet("font-weight: bold; margin-top: 8px;")
        command_layout.addWidget(preview_label)

        # Preview display with larger font
        preview_display = QTextEdit()
        preview_display.setReadOnly(True)
        preview_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        preview_font.setPointSize(10)  # Slightly larger preview font
        preview_display.setFont(preview_font)
        preview_display.setObjectName("commandPreview")
        preview_display.setMaximumHeight(80)
        command_layout.addWidget(preview_display)

        layout.addWidget(command_group)

        # Function to update preview in real-time with syntax highlighting
        def update_preview():
            command = command_input.toPlainText()

            # Define all substitutions (longest first to handle multi-char vars)
            substitutions = {
                # Multi-char variables first
                '%e1': 'val1', '%e2': 'val2', '%e3': 'val3', '%e4': 'val4',
                '%c1': 'cval1', '%c2': 'cval2', '%c3': 'cval3', '%c4': 'cval4',
                # Single-char variables
                '%N': 'Test Gallery',
                '%T': 'Main',
                '%p': 'C:\\test\\path',
                '%C': '10',
                '%s': '1048576',
                '%t': 'Main',
            }

            # Add completed-specific substitutions
            if hook_type == "completed":
                substitutions.update({
                    '%g': 'TEST123',
                    '%j': 'C:\\test\\artifact.json',
                    '%b': 'C:\\test\\bbcode.txt',
                    '%z': '',
                })

            # Sort by length (descending) to handle multi-char vars first
            sorted_subs = sorted(substitutions.items(), key=lambda x: len(x[0]), reverse=True)

            preview_command = command
            for var, value in sorted_subs:
                preview_command = preview_command.replace(var, value)

            preview_display.setPlainText(preview_command)

        # Enhanced syntax highlighter with color-coded variables
        class CommandHighlighter(QSyntaxHighlighter):
            def __init__(self, parent=None, hook_type=''):
                super().__init__(parent)
                from PyQt6.QtGui import QColor

                # Define color formats for different variable types
                # Gallery info variables (blue/cyan)
                self.gallery_format = QTextCharFormat()
                self.gallery_format.setFontWeight(QFont.Weight.Bold)
                self.gallery_format.setForeground(QColor(41, 128, 185))  # Blue
                self.gallery_vars = ['%N', '%T', '%p', '%C', '%s', '%t']

                # Upload result variables (green)
                self.upload_format = QTextCharFormat()
                self.upload_format.setFontWeight(QFont.Weight.Bold)
                self.upload_format.setForeground(QColor(39, 174, 96))  # Green
                self.upload_vars = ['%g', '%j', '%b', '%z']

                # Ext field variables (orange)
                self.ext_format = QTextCharFormat()
                self.ext_format.setFontWeight(QFont.Weight.Bold)
                self.ext_format.setForeground(QColor(230, 126, 34))  # Orange
                self.ext_vars = ['%e1', '%e2', '%e3', '%e4']

                # Custom field variables (purple)
                self.custom_format = QTextCharFormat()
                self.custom_format.setFontWeight(QFont.Weight.Bold)
                self.custom_format.setForeground(QColor(142, 68, 173))  # Purple
                self.custom_vars = ['%c1', '%c2', '%c3', '%c4']

                # Build complete variable list sorted by length (longest first)
                all_vars = self.gallery_vars + self.upload_vars + self.ext_vars + self.custom_vars
                all_vars.sort(key=len, reverse=True)
                self.all_variables = all_vars

            def highlightBlock(self, text):
                # Highlight variables with color-coding
                for var in self.all_variables:
                    # Determine which format to use
                    if var in self.gallery_vars:
                        var_format = self.gallery_format
                    elif var in self.upload_vars:
                        var_format = self.upload_format
                    elif var in self.ext_vars:
                        var_format = self.ext_format
                    elif var in self.custom_vars:
                        var_format = self.custom_format
                    else:
                        continue

                    # Find and highlight all occurrences
                    index = text.find(var)
                    while index >= 0:
                        self.setFormat(index, len(var), var_format)
                        index = text.find(var, index + len(var))

        # Apply highlighter
        highlighter = CommandHighlighter(command_input.document())

        # Connect for real-time updates
        command_input.textChanged.connect(update_preview)
        update_preview()  # Initial update

        # JSON Key Mapping section - compact 2-row layout with reduced height
        mapping_group = QGroupBox("JSON Key Mappings")
        mapping_layout = QVBoxLayout(mapping_group)
        mapping_layout.setSpacing(4)  # Tighter spacing

        mapping_info = QLabel("Map program output to ext1-4 columns to make data available in bbcode template (e.g. download links from filehosts).")
        mapping_info.setStyleSheet("font-size: 10px;")
        mapping_layout.addWidget(mapping_info)

        key_inputs = {}
        # Two rows of ext1-4
        for row in range(1):
            row_layout = QHBoxLayout()
            row_layout.setSpacing(8)
            for col in range(4):
                i = row * 2 + col + 1  # ext1-4
                label = QLabel(f"<b>ext{i}</b>:")
                label.setMinimumWidth(35)
                row_layout.addWidget(label)
                key_input = QLineEdit()
                current_value = getattr(self, f'hook_{hook_type}_key{i}').text()
                key_input.setText(current_value)
                #key_input.setPlaceholderText(f'e.g., "url", "filename"')
                key_inputs[f'ext{i}'] = key_input
                row_layout.addWidget(key_input, 1)  # Stretch
            mapping_layout.addLayout(row_layout)

        # Set maximum height to make it more compact
        mapping_group.setMaximumHeight(110)
        layout.addWidget(mapping_group)

        # Console/execution options
        options_layout = QHBoxLayout()
        show_console_check = QCheckBox("Show console window when executing")
        show_console_check.setToolTip("If enabled, a console window will appear when the command runs (Windows only)")
        # Load current setting
        current_show_console = getattr(self, f'hook_{hook_type}_show_console').isChecked()
        show_console_check.setChecked(current_show_console)
        options_layout.addWidget(show_console_check)
        options_layout.addStretch()
        layout.addLayout(options_layout)

        # Test section - simplified to only show results when available
        test_group = QGroupBox("Test Output")
        test_layout = QVBoxLayout(test_group)

        # Split view: table left (40%), raw output right (60%)
        from PyQt6.QtWidgets import QSplitter
        results_splitter = QSplitter(Qt.Orientation.Horizontal)

        # Table widget for JSON results (left side) - hidden by default
        table_container = QWidget()
        table_layout = QVBoxLayout(table_container)
        table_layout.setContentsMargins(0, 0, 0, 0)

        results_table = QTableWidget()
        results_table.setColumnCount(2)
        results_table.setHorizontalHeaderLabels(["Key", "Value"])
        # Larger header font
        header_font = results_table.horizontalHeader().font()
        header_font.setPointSize(header_font.pointSize() + 1)
        header_font.setBold(True)
        results_table.horizontalHeader().setFont(header_font)
        results_table.horizontalHeader().setStretchLastSection(True)
        results_table.setAlternatingRowColors(True)
        results_table.setVisible(False)  # Hidden until JSON is detected
        table_layout.addWidget(results_table)

        results_splitter.addWidget(table_container)

        # Text output widget for raw output (right side)
        output_container = QWidget()
        output_layout = QVBoxLayout(output_container)
        output_layout.setContentsMargins(0, 0, 0, 0)

        test_output = QTextEdit()
        test_output.setReadOnly(True)
        test_output.setPlaceholderText("Click '▶ Run Test Command' button above to execute and see output...")
        mono_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        test_output.setFont(mono_font)
        output_layout.addWidget(test_output)

        results_splitter.addWidget(output_container)

        # Set initial sizes (40/60 split - more space for raw output)
        results_splitter.setSizes([300, 500])

        def run_test():
            import subprocess
            import json
            import re

            # Get the command from the live preview display (already has substitutions)
            test_command = preview_display.toPlainText()

            if not test_command or not command_input.toPlainText():
                test_output.setPlainText("Error: No command configured")
                results_table.setVisible(False)
                return

            try:
                test_output.setText(f"Running: {test_command}\n\nPlease wait...")
                QApplication.processEvents()  # Update UI

                # SECURITY: Use shlex.split to safely parse command and prevent injection
                # shell=False prevents command injection attacks via shell metacharacters
                import shlex
                try:
                    command_parts = shlex.split(test_command)
                except ValueError as e:
                    test_output.setText(f"ERROR: Invalid command syntax: {e}\n\n" +
                                      "Command must use proper quoting for arguments with spaces.")
                    return

                result = subprocess.run(
                    command_parts,
                    shell=False,  # SECURITY: Prevents command injection
                    capture_output=True,
                    text=True,
                    timeout=30
                )

                # Always show raw output
                output_text = f"=== STDOUT ===\n{result.stdout if result.stdout else '(empty)'}\n\n"
                if result.stderr:
                    output_text += f"=== STDERR ===\n{result.stderr}\n\n"

                # Smart detection variables
                detected_data = {}
                auto_map_suggestions = {}

                # Try to parse as JSON first
                if result.stdout.strip():
                    is_json = False
                    try:
                        json_data = json.loads(result.stdout.strip())
                        is_json = True

                        # Check if JSON indicates an error response
                        is_error_response = False
                        error_message = None

                        # Common error patterns in JSON responses
                        if isinstance(json_data, dict):
                            # Pattern 1: {"error": "message", "status": "failed"}
                            if 'error' in json_data and 'status' in json_data:
                                if json_data.get('status') in ['failed', 'error', 'fail']:
                                    is_error_response = True
                                    error_message = json_data.get('error', 'Unknown error')
                            # Pattern 2: {"error": "message"} (no status field)
                            elif 'error' in json_data and not any(k in json_data for k in ['url', 'link', 'data', 'result', 'success']):
                                is_error_response = True
                                error_message = json_data.get('error', 'Unknown error')
                            # Pattern 3: {"status": "error", "message": "..."}
                            elif json_data.get('status') in ['failed', 'error', 'fail'] and 'message' in json_data:
                                is_error_response = True
                                error_message = json_data.get('message', 'Unknown error')
                            # Pattern 4: {"success": false, "error": "..."}
                            elif json_data.get('success') == False and 'error' in json_data:
                                is_error_response = True
                                error_message = json_data.get('error', 'Unknown error')

                        # If this is an error response, show error dialog and stop processing
                        if is_error_response:
                            from PyQt6.QtWidgets import QMessageBox
                            results_table.setVisible(False)
                            output_text += f"❌ Command returned an error response\n\n"
                            test_output.setPlainText(output_text)

                            QMessageBox.critical(
                                dialog,
                                "External App Test Failed",
                                f"The external application returned an error:\n\n{error_message}"
                            )
                            return

                        # If we got valid JSON (and not an error), populate the table
                        results_table.setRowCount(0)

                        # Add each key-value pair to the table
                        for key, value in json_data.items():
                            row_position = results_table.rowCount()
                            results_table.insertRow(row_position)

                            # Key column
                            key_item = QTableWidgetItem(str(key))
                            key_item.setToolTip(str(key))
                            results_table.setItem(row_position, 0, key_item)

                            # Value column - format based on type
                            if isinstance(value, dict) or isinstance(value, list):
                                value_text = json.dumps(value, indent=2)
                            else:
                                value_text = str(value)

                            value_item = QTableWidgetItem(value_text)
                            value_item.setToolTip(value_text)
                            results_table.setItem(row_position, 1, value_item)

                            # Store for auto-mapping suggestions
                            detected_data[key] = value_text

                        # Resize columns to content
                        results_table.resizeColumnsToContents()

                        # Show table if we have results
                        if results_table.rowCount() > 0:
                            results_table.setVisible(True)
                            output_text += "✓ Valid JSON detected and parsed in left panel\n\n"

                            # Smart auto-mapping suggestions for JSON
                            suggest_json_mapping(json_data, auto_map_suggestions)
                        else:
                            results_table.setVisible(False)
                            output_text += "⚠ JSON was valid but empty\n\n"

                        test_output.setPlainText(output_text)

                    except json.JSONDecodeError:
                        # Not valid JSON - try smart pattern detection
                        is_json = False
                        results_table.setVisible(False)

                        # Detect URLs, file paths, and other useful data
                        detect_patterns(result.stdout, detected_data, auto_map_suggestions)

                        if detected_data:
                            output_text += f"ℹ️ Output is not JSON, but found {len(detected_data)} useful value(s)\n\n"
                        else:
                            output_text += "⚠ Output is not JSON and no recognizable patterns found\n\n"

                        test_output.setPlainText(output_text)

                    # Show auto-mapping suggestion dialog if we found anything useful
                    if auto_map_suggestions:
                        show_auto_map_dialog(auto_map_suggestions, detected_data, is_json)

                else:
                    # No output
                    results_table.setVisible(False)
                    test_output.setPlainText(output_text + "⚠ Command produced no stdout")

            except subprocess.TimeoutExpired:
                results_table.setVisible(False)
                test_output.setPlainText("Error: Command timed out after 30 seconds")
            except Exception as e:
                results_table.setVisible(False)
                test_output.setPlainText(f"Error: {e}")

        def suggest_json_mapping(json_data, suggestions):
            """Suggest JSON key to ext field mappings based on common patterns"""
            # Common patterns for URLs
            url_keys = ['url', 'link', 'href', 'download_url', 'file_url', 'upload_url', 'direct_url']
            # Common patterns for filenames
            filename_keys = ['filename', 'name', 'file', 'title']
            # Common patterns for IDs
            id_keys = ['id', 'file_id', 'upload_id', 'unique_id']
            # Common patterns for sizes
            size_keys = ['size', 'filesize', 'bytes', 'length']

            priority_order = []

            for key, value in json_data.items():
                key_lower = key.lower()

                # Prioritize URL fields
                if any(pattern in key_lower for pattern in url_keys):
                    priority_order.append((1, key, value, "URL/Link"))
                # Then filename fields
                elif any(pattern in key_lower for pattern in filename_keys):
                    priority_order.append((2, key, value, "Filename"))
                # Then ID fields
                elif any(pattern in key_lower for pattern in id_keys):
                    priority_order.append((3, key, value, "ID"))
                # Then size fields
                elif any(pattern in key_lower for pattern in size_keys):
                    priority_order.append((4, key, value, "Size"))
                # Everything else
                else:
                    priority_order.append((5, key, value, "Data"))

            # Sort by priority and assign to ext1-4
            priority_order.sort(key=lambda x: x[0])
            for i, (priority, key, value, data_type) in enumerate(priority_order[:4]):
                suggestions[f'ext{i+1}'] = {
                    'json_key': key,
                    'value': value,
                    'type': data_type
                }

        def detect_patterns(text, detected_data, suggestions):
            """Detect URLs, file paths, and other patterns in plain text output"""
            import re

            # URL pattern (http, https, ftp)
            url_pattern = r'https?://[^\s<>"\'\)]+|ftp://[^\s<>"\'\)]+'
            urls = re.findall(url_pattern, text)

            # File path pattern (Windows and Unix)
            file_pattern = r'(?:[A-Za-z]:\\(?:[^\\\/:*?"<>|\r\n]+\\)*[^\\\/:*?"<>|\r\n]*)|(?:/[^\s:*?"<>|\r\n]+)'
            file_paths = re.findall(file_pattern, text)

            # Look for key:value or key=value patterns
            kv_pattern = r'(\w+)\s*[:=]\s*([^\s,;\n]+)'
            key_values = re.findall(kv_pattern, text)

            ext_counter = 1

            # Prioritize URLs
            for url in urls[:4]:  # Limit to first 4 URLs
                if ext_counter <= 4:
                    detected_data[f'url_{ext_counter}'] = url
                    suggestions[f'ext{ext_counter}'] = {
                        'json_key': None,
                        'value': url,
                        'type': 'URL'
                    }
                    ext_counter += 1

            # Then file paths that look like actual files (have extensions)
            for path in file_paths:
                if ext_counter <= 4 and '.' in path.split('/')[-1].split('\\')[-1]:
                    detected_data[f'file_{ext_counter}'] = path
                    suggestions[f'ext{ext_counter}'] = {
                        'json_key': None,
                        'value': path,
                        'type': 'File Path'
                    }
                    ext_counter += 1

            # Then key-value pairs
            for key, value in key_values:
                if ext_counter <= 4:
                    detected_data[key] = value
                    suggestions[f'ext{ext_counter}'] = {
                        'json_key': key,
                        'value': value,
                        'type': 'Data'
                    }
                    ext_counter += 1

        def show_auto_map_dialog(suggestions, detected_data, is_json):
            """Show a simple dialog asking if user wants to auto-map detected values"""
            from PyQt6.QtWidgets import QMessageBox, QCheckBox, QVBoxLayout, QLabel

            msg_box = QMessageBox(dialog)
            msg_box.setWindowTitle("Auto-Map Detected Values?")
            msg_box.setIcon(QMessageBox.Icon.Question)

            # Build the message
            if is_json:
                message = "✓ Found useful data in the JSON output!\n\n"
            else:
                message = "✓ Found useful data in the output!\n\n"

            message += "Would you like to automatically map these values to ext fields?\n\n"

            for ext_field, info in sorted(suggestions.items()):
                value = info['value']
                data_type = info['type']

                # Truncate long values
                if len(str(value)) > 50:
                    display_value = str(value)[:47] + "..."
                else:
                    display_value = str(value)

                if is_json and info['json_key']:
                    message += f"• {ext_field}: {info['json_key']} = {display_value}\n   ({data_type})\n\n"
                else:
                    message += f"• {ext_field}: {display_value}\n   ({data_type})\n\n"

            msg_box.setText(message)
            msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            msg_box.setDefaultButton(QMessageBox.StandardButton.Yes)

            # Add "Don't ask again" checkbox
            dont_ask_cb = QCheckBox("Don't ask me again (always auto-map)")
            msg_box.setCheckBox(dont_ask_cb)

            response = msg_box.exec()

            if response == QMessageBox.StandardButton.Yes:
                # Apply the mappings
                for ext_field, info in suggestions.items():
                    ext_num = ext_field[-1]  # Get the number (1-4)

                    # Set the JSON key mapping (if it's JSON)
                    if is_json and info['json_key']:
                        key_inputs[ext_field].setText(info['json_key'])
                    elif info['json_key']:  # Plain text key-value
                        key_inputs[ext_field].setText(info['json_key'])
                    # For plain URLs/paths without keys, leave the mapping empty
                    # The value will still be accessible via the detected pattern

                # Show confirmation
                QMessageBox.information(
                    dialog,
                    "Mappings Applied",
                    f"✓ Successfully mapped {len(suggestions)} value(s) to ext fields!\n\n"
                    "Click 'Save' to keep these mappings."
                )

        test_btn.clicked.connect(run_test)
        test_layout.addWidget(results_splitter)
        layout.addWidget(test_group)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        save_btn = QPushButton("Save")
        save_btn.setDefault(True)  # Make it the default button
        def save_mapping():
            # Save the command from the command builder (QTextEdit now)
            new_command = command_input.toPlainText().strip()
            getattr(self, f'hook_{hook_type}_command').setText(new_command)

            # Save the show console checkbox
            getattr(self, f'hook_{hook_type}_show_console').setChecked(show_console_check.isChecked())

            # Save the JSON key mappings
            for i in range(1, 5):
                key = f'ext{i}'
                value = key_inputs[key].text().strip()
                getattr(self, f'hook_{hook_type}_key{i}').setText(value)

            self.mark_tab_dirty(5)  # External Apps tab is now at index 5 after hiding Tabs and Icons
            dialog.accept()

        save_btn.clicked.connect(save_mapping)
        button_layout.addWidget(save_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(dialog.reject)
        button_layout.addWidget(cancel_btn)

        layout.addLayout(button_layout)

        dialog.exec()

    # ===== File Host Settings (Widget-based) =====

    def setup_file_hosts_tab(self):
        """Setup the File Hosts tab using dedicated widget"""
        from src.gui.widgets.file_hosts_settings_widget import FileHostsSettingsWidget

        if not self.file_host_manager:
            # No manager available - show error
            error_widget = QWidget()
            layout = QVBoxLayout(error_widget)
            error_label = QLabel("File host manager not available. Please restart the application.")
            error_label.setWordWrap(True)
            error_label.setStyleSheet("color: red; font-weight: bold;")
            layout.addWidget(error_label)
            layout.addStretch()
            self.tab_widget.addTab(error_widget, "File Hosts")
            return

        # Create file hosts widget (no signals - reads from QSettings cache)
        self.file_hosts_widget = FileHostsSettingsWidget(self, self.file_host_manager)


        # Add tab
        self.tab_widget.addTab(self.file_hosts_widget, "File Hosts")

    def setup_advanced_tab(self):
        """Setup the Advanced settings tab."""
        self.advanced_widget = AdvancedSettingsWidget()
        self.advanced_widget.settings_changed.connect(lambda: self.mark_tab_dirty(7))
        self.tab_widget.addTab(self.advanced_widget, "Advanced")

    def _load_advanced_settings(self):
        """Load advanced settings from INI file."""
        from imxup import get_config_path

        config = configparser.ConfigParser()
        config_file = get_config_path()

        if os.path.exists(config_file):
            config.read(config_file)
            if config.has_section('Advanced'):
                values = {}
                for key, value in config.items('Advanced'):
                    # Convert string values back to appropriate types
                    if value.lower() in ('true', 'false'):
                        values[key] = value.lower() == 'true'
                    else:
                        try:
                            values[key] = int(value)
                        except ValueError:
                            try:
                                values[key] = float(value)
                            except ValueError:
                                values[key] = value
                self.advanced_widget.set_values(values)

    def _save_advanced_settings(self):
        """Save advanced settings to INI file (only non-default values)."""
        from imxup import get_config_path

        config = configparser.ConfigParser()
        config_file = get_config_path()

        if os.path.exists(config_file):
            config.read(config_file)

        # Remove existing Advanced section and recreate with current values
        if config.has_section('Advanced'):
            config.remove_section('Advanced')

        non_defaults = self.advanced_widget.get_non_default_values()
        if non_defaults:
            config.add_section('Advanced')
            for key, value in non_defaults.items():
                config.set('Advanced', key, str(value))

        with open(config_file, 'w') as f:
            config.write(f)

        return True

    def setup_icons_tab(self):
        """Setup the Icon Manager tab with improved side-by-side light/dark preview"""
        icons_widget = QWidget()
        # Keep a reference to prevent garbage collection
        self.icons_widget_ref = icons_widget
        layout = QVBoxLayout(icons_widget)
        
        # Header info
        info_label = QLabel("Customize application icons. Single icons auto-adapt to themes, pairs give full control.")
        info_label.setWordWrap(True)
        info_label.setProperty("class", "tab-description")
        info_label.setMaximumHeight(40)  # Limit height to prevent it from taking too much space
        from PyQt6.QtWidgets import QSizePolicy
        info_label.setSizePolicy(info_label.sizePolicy().horizontalPolicy(), 
                                QSizePolicy.Policy.Fixed)  # Fixed vertical size policy
        layout.addWidget(info_label)
        
        # Add spacing to match QGroupBox margin in other tabs
        layout.addSpacing(8)
        
        # Create splitter for icon categories and preview
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)
        
        # Left side - Icon categories tree
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        
        category_group = QGroupBox("Icon Categories")
        category_layout = QVBoxLayout(category_group)
        
        self.icon_tree = QListWidget()
        self.icon_tree.itemSelectionChanged.connect(self.on_icon_selection_changed)
        category_layout.addWidget(self.icon_tree)
        
        left_layout.addWidget(category_group)
        splitter.addWidget(left_widget)
        
        # Right side - Icon details and customization
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        
        # Icon Details group
        details_group = QGroupBox("Icon Details")
        details_layout = QVBoxLayout(details_group)
        
        self.icon_name_label = QLabel("Select an icon to customize")
        self.icon_name_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        details_layout.addWidget(self.icon_name_label)
        
        self.icon_description_label = QLabel("")
        self.icon_description_label.setWordWrap(True)
        self.icon_description_label.setStyleSheet("color: #666; font-size: 11px; padding: 2px;")
        details_layout.addWidget(self.icon_description_label)
        
        right_layout.addWidget(details_group)
        
        
        # Light/Dark Icon Preview - REDESIGNED
        preview_group = QGroupBox("Icon Preview")
        preview_layout = QVBoxLayout(preview_group)
        
        # Create side-by-side preview boxes
        preview_boxes_layout = QHBoxLayout()
        
        # Light theme box
        light_box = QGroupBox("Light Theme")
        light_box_layout = QVBoxLayout(light_box)
        
        self.light_icon_frame = IconDropFrame('light')
        self.light_icon_frame.setFixedSize(100, 100)
        self.light_icon_frame.setStyleSheet("border: 2px dashed #ddd; background: #ffffff; border-radius: 8px;")
        self.light_icon_frame.icon_dropped.connect(lambda path: self.handle_icon_drop_variant(path, 'light'))
        light_frame_layout = QVBoxLayout(self.light_icon_frame)
        light_frame_layout.setContentsMargins(0, 0, 0, 0)
        
        self.light_icon_label = QLabel()
        self.light_icon_label.setFixedSize(96, 96)
        self.light_icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.light_icon_label.setStyleSheet("border: none; background: transparent;")
        self.light_icon_label.setScaledContents(True)  # Ensure proper scaling
        light_frame_layout.addWidget(self.light_icon_label)
        
        light_box_layout.addWidget(self.light_icon_frame, 0, Qt.AlignmentFlag.AlignCenter)
        
        self.light_status_label = QLabel("No icon")
        self.light_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.light_status_label.setStyleSheet("font-size: 10px; color: #666; padding: 3px;")
        light_box_layout.addWidget(self.light_status_label)
        
        light_controls = QHBoxLayout()
        self.light_browse_btn = QPushButton("Browse")
        self.light_browse_btn.clicked.connect(lambda: self.browse_for_icon_variant('light'))
        self.light_browse_btn.setEnabled(False)
        light_controls.addWidget(self.light_browse_btn)
        
        self.light_reset_btn = QPushButton("Reset")
        self.light_reset_btn.clicked.connect(lambda: self.reset_icon_variant('light'))
        self.light_reset_btn.setEnabled(False)
        light_controls.addWidget(self.light_reset_btn)
        
        light_box_layout.addLayout(light_controls)
        preview_boxes_layout.addWidget(light_box)
        
        # Dark theme box - FIXED SIZE TO MATCH LIGHT
        dark_box = QGroupBox("Dark Theme")
        dark_box_layout = QVBoxLayout(dark_box)
        
        self.dark_icon_frame = IconDropFrame('dark')
        self.dark_icon_frame.setFixedSize(100, 100)  # Same size as light
        self.dark_icon_frame.setStyleSheet("border: 2px dashed #555; background: #2b2b2b; border-radius: 8px;")
        self.dark_icon_frame.icon_dropped.connect(lambda path: self.handle_icon_drop_variant(path, 'dark'))
        dark_frame_layout = QVBoxLayout(self.dark_icon_frame)
        dark_frame_layout.setContentsMargins(0, 0, 0, 0)
        
        self.dark_icon_label = QLabel()
        self.dark_icon_label.setFixedSize(96, 96)  # Same size as light
        self.dark_icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.dark_icon_label.setStyleSheet("border: none; background: transparent;")
        self.dark_icon_label.setScaledContents(True)  # Ensure proper scaling
        dark_frame_layout.addWidget(self.dark_icon_label)
        
        dark_box_layout.addWidget(self.dark_icon_frame, 0, Qt.AlignmentFlag.AlignCenter)
        
        self.dark_status_label = QLabel("No icon")
        self.dark_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.dark_status_label.setStyleSheet("font-size: 10px; color: #666; padding: 3px;")
        dark_box_layout.addWidget(self.dark_status_label)
        
        dark_controls = QHBoxLayout()
        self.dark_browse_btn = QPushButton("Browse")
        self.dark_browse_btn.clicked.connect(lambda: self.browse_for_icon_variant('dark'))
        self.dark_browse_btn.setEnabled(False)
        dark_controls.addWidget(self.dark_browse_btn)
        
        self.dark_reset_btn = QPushButton("Reset")
        self.dark_reset_btn.clicked.connect(lambda: self.reset_icon_variant('dark'))
        self.dark_reset_btn.setEnabled(False)
        dark_controls.addWidget(self.dark_reset_btn)
        
        dark_box_layout.addLayout(dark_controls)
        preview_boxes_layout.addWidget(dark_box)
        
        preview_layout.addLayout(preview_boxes_layout)
        
        # Configuration indicator
        self.config_type_label = QLabel("Configuration: Unknown")
        self.config_type_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.config_type_label.setStyleSheet("font-weight: bold; font-size: 11px; color: #333; padding: 5px;")
        preview_layout.addWidget(self.config_type_label)
        
        right_layout.addWidget(preview_group)
        
        # Global Actions group (simplified)
        global_actions_group = QGroupBox("Global Actions")
        global_actions_layout = QVBoxLayout(global_actions_group)
        
        global_button_layout = QHBoxLayout()
        
        reset_all_btn = QPushButton("Reset All Icons")
        reset_all_btn.clicked.connect(self.reset_all_icons)
        global_button_layout.addWidget(reset_all_btn)
        
        validate_btn = QPushButton("Validate Icons")
        validate_btn.clicked.connect(self.validate_all_icons)
        global_button_layout.addWidget(validate_btn)
        
        global_actions_layout.addLayout(global_button_layout)
        right_layout.addWidget(global_actions_group)
        
        right_layout.addStretch()
        splitter.addWidget(right_widget)
        
        # Set splitter proportions
        splitter.setSizes([300, 500])
        
        # Initialize icon list
        self.populate_icon_list()
        
        # Connect change signals - no need to mark dirty since icon replacement handles this
        # self.light_icon_frame.icon_dropped.connect(lambda: self.mark_tab_dirty(6))
        # self.dark_icon_frame.icon_dropped.connect(lambda: self.mark_tab_dirty(6))

        # Icons management temporarily hidden while deciding on functionality
        # self.tab_widget.addTab(icons_widget, "Icons")
        
    def browse_central_store(self):
        """Browse for central store directory"""
        from imxup import get_default_central_store_base_path
        current_path = self.path_edit.text() or get_default_central_store_base_path()
        
        # Use non-blocking file dialog
        dialog = QFileDialog(self)
        dialog.setWindowTitle("Select Central Store Directory")
        dialog.setFileMode(QFileDialog.FileMode.Directory)
        dialog.setOption(QFileDialog.Option.ShowDirsOnly, True)
        dialog.setDirectory(current_path)
        
        # Connect to slot for non-blocking execution
        # PyQt6 uses fileSelected for directory mode, not directorySelected
        dialog.fileSelected.connect(self._handle_directory_selected)
        dialog.open()
    
    def _handle_directory_selected(self, directory):
        """Handle selected directory"""
        if directory:
            self.custom_radio.setChecked(True)
            self.path_edit.setText(directory)
            self.mark_tab_dirty(0)


    def _center_on_parent(self):
        """Center dialog on parent window or screen"""
        if self.parent():
            # Center on parent window
            parent_geo = self.parent().geometry()
            dialog_geo = self.frameGeometry()
            x = parent_geo.x() + (parent_geo.width() - dialog_geo.width()) // 2
            y = parent_geo.y() + (parent_geo.height() - dialog_geo.height()) // 2
            self.move(x, y)
        else:
            # Center on screen if no parent
            screen = QApplication.primaryScreen()
            if screen:
                screen_geo = screen.geometry()
                dialog_geo = self.frameGeometry()
                x = (screen_geo.width() - dialog_geo.width()) // 2
                y = (screen_geo.height() - dialog_geo.height()) // 2
                self.move(x, y)

    def load_settings(self):
        """Load current settings"""
        # Settings are loaded in setup_ui for each tab
        # Load scanning settings from QSettings
        self._load_scanning_settings()
        # Load tabs settings
        self._load_tabs_settings()
        # Load external apps settings
        self._load_external_apps_settings()
        # Load file hosts settings
        self._load_file_hosts_settings()
        # Load advanced settings
        self._load_advanced_settings()

    def _load_scanning_settings(self):
        """Load scanning settings from INI file"""
        try:
            config = configparser.ConfigParser()
            config_file = get_config_path()

            if os.path.exists(config_file):
                config.read(config_file)

            # Block ALL signals during loading to prevent marking tab as dirty
            controls_to_block = [
                self.fast_scan_check, self.sampling_fixed_radio, self.sampling_percent_radio,
                self.sampling_fixed_spin, self.sampling_percent_spin, self.exclude_first_check,
                self.exclude_last_check, self.exclude_small_check, self.exclude_small_spin,
                self.exclude_patterns_check, self.exclude_patterns_edit,
                self.stats_exclude_outliers_check, self.avg_mean_radio, self.avg_median_radio
            ]
            for control in controls_to_block:
                control.blockSignals(True)

            # Load fast scan setting
            fast_scan = config.getboolean('SCANNING', 'fast_scanning', fallback=True)
            self.fast_scan_check.setChecked(fast_scan)

            # Load sampling method and values
            sampling_method = config.getint('SCANNING', 'sampling_method', fallback=0)
            if sampling_method == 0:
                self.sampling_fixed_radio.setChecked(True)
                self.sampling_fixed_spin.setEnabled(True)
                self.sampling_percent_spin.setEnabled(False)
            else:
                self.sampling_percent_radio.setChecked(True)
                self.sampling_fixed_spin.setEnabled(False)
                self.sampling_percent_spin.setEnabled(True)

            self.sampling_fixed_spin.setValue(
                config.getint('SCANNING', 'sampling_fixed_count', fallback=25))
            self.sampling_percent_spin.setValue(
                config.getint('SCANNING', 'sampling_percentage', fallback=10))

            # Load exclusion settings
            self.exclude_first_check.setChecked(
                config.getboolean('SCANNING', 'exclude_first', fallback=False))
            self.exclude_last_check.setChecked(
                config.getboolean('SCANNING', 'exclude_last', fallback=False))
            exclude_small = config.getboolean('SCANNING', 'exclude_small_images', fallback=False)
            self.exclude_small_check.setChecked(exclude_small)
            self.exclude_small_spin.setEnabled(exclude_small)
            self.exclude_small_spin.setValue(
                config.getint('SCANNING', 'exclude_small_threshold', fallback=50))
            self.exclude_patterns_check.setChecked(
                config.getboolean('SCANNING', 'exclude_patterns', fallback=False))
            self.exclude_patterns_edit.setText(
                config.get('SCANNING', 'exclude_patterns_text', fallback=''))

            # Load statistics calculation setting
            self.stats_exclude_outliers_check.setChecked(
                config.getboolean('SCANNING', 'stats_exclude_outliers', fallback=False))

            # Load average method setting
            use_median = config.getboolean('SCANNING', 'use_median', fallback=True)
            if use_median:
                self.avg_median_radio.setChecked(True)
            else:
                self.avg_mean_radio.setChecked(True)

            # Unblock signals
            for control in controls_to_block:
                control.blockSignals(False)

        except Exception as e:
            log(f"Failed to load scanning settings: {e}", level="warning", category="settings")
    
    def _load_tabs_settings(self):
        """Load tabs settings if available"""
        try:
            if hasattr(self, 'load_tabs_settings'):
                self.load_tabs_settings()
        except Exception as e:
            # Silently skip any errors since tabs functionality may be hidden
            pass

    def _load_external_apps_settings(self):
        """Load external apps settings from INI file"""
        try:
            config = configparser.ConfigParser()
            config_file = get_config_path()

            #print(f"{timestamp()} DEBUG: Loading external apps settings from {config_file}")

            if os.path.exists(config_file):
                config.read(config_file)
            else:
                log(f"Config file does not exist: {config_file}", level="warning", category="settings")
                return

            # Check if EXTERNAL_APPS section exists
            if 'EXTERNAL_APPS' not in config:
                log(f"No EXTERNAL_APPS section in config, using defaults", level="info", category="settings")
                return

            # Block signals during loading
            controls = [self.hooks_parallel_radio, self.hooks_sequential_radio]
            for hook_type in ['added', 'started', 'completed']:
                controls.extend([
                    getattr(self, f'hook_{hook_type}_enabled'),
                    getattr(self, f'hook_{hook_type}_command'),
                    getattr(self, f'hook_{hook_type}_show_console'),
                ])

            for control in controls:
                control.blockSignals(True)

            # Load execution mode
            parallel = config.getboolean('EXTERNAL_APPS', 'parallel_execution', fallback=True)
            if parallel:
                self.hooks_parallel_radio.setChecked(True)
            else:
                self.hooks_sequential_radio.setChecked(True)

            # Load hook settings
            for hook_type in ['added', 'started', 'completed']:
                enabled = config.getboolean('EXTERNAL_APPS', f'hook_{hook_type}_enabled', fallback=False)
                command = config.get('EXTERNAL_APPS', f'hook_{hook_type}_command', fallback='')
                show_console = config.getboolean('EXTERNAL_APPS', f'hook_{hook_type}_show_console', fallback=False)

                # ConfigParser automatically unescapes %% to % when reading

                #print(f"{timestamp()} DEBUG: Loading {hook_type}: enabled={enabled}, command='{command}', show_console={show_console}")

                getattr(self, f'hook_{hook_type}_enabled').setChecked(enabled)
                getattr(self, f'hook_{hook_type}_command').setText(command)
                getattr(self, f'hook_{hook_type}_show_console').setChecked(show_console)

                # Load JSON key mappings
                for i in range(1, 5):
                    key_mapping = config.get('EXTERNAL_APPS', f'hook_{hook_type}_key{i}', fallback='')
                    #if key_mapping:
                    #    print(f"{timestamp()} DEBUG: Loading {hook_type}_key{i}='{key_mapping}'")
                    getattr(self, f'hook_{hook_type}_key{i}').setText(key_mapping)

            # Unblock signals
            for control in controls:
                control.blockSignals(False)

            #print(f"{timestamp()} DEBUG: External apps settings loaded successfully")

        except Exception as e:
            import traceback
            log(f"Failed to load external apps settings: {e}", level="error", category="settings")
            traceback.print_exc()

    def _load_file_hosts_settings(self):
        """Load file hosts settings from INI file and encrypted credentials from QSettings"""
        try:
            # Check if widget exists
            if not hasattr(self, 'file_hosts_widget') or not self.file_hosts_widget:
                return

            from src.core.file_host_config import get_config_manager
            from imxup import get_credential, decrypt_password

            config = configparser.ConfigParser()
            config_file = get_config_path()

            if os.path.exists(config_file):
                config.read(config_file)

            # Prepare settings dict
            settings_dict = {
                'global_limit': 3,
                'per_host_limit': 2,
                'hosts': {}
            }

            # Load connection limits
            if 'FILE_HOSTS' in config:
                settings_dict['global_limit'] = config.getint('FILE_HOSTS', 'global_limit', fallback=3)
                settings_dict['per_host_limit'] = config.getint('FILE_HOSTS', 'per_host_limit', fallback=2)

            # Load per-host settings
            config_manager = get_config_manager()
            for host_id in config_manager.hosts.keys():
                # Use new API for layered config (INI → JSON defaults → hardcoded)
                from src.core.file_host_config import get_file_host_setting

                host_settings = {
                    'enabled': get_file_host_setting(host_id, 'enabled', 'bool'),
                    'credentials': '',
                    'trigger': get_file_host_setting(host_id, 'trigger', 'str')  # Single string value
                }

                # Load encrypted credentials from QSettings
                encrypted_creds = get_credential(f'file_host_{host_id}_credentials')
                if encrypted_creds:
                    decrypted = decrypt_password(encrypted_creds)
                    if decrypted:
                        host_settings['credentials'] = decrypted

                settings_dict['hosts'][host_id] = host_settings

            # Apply settings to widget
            self.file_hosts_widget.load_settings(settings_dict)

        except Exception as e:
            import traceback
            log(f"Failed to load file hosts settings: {e}", level="error", category="settings")
            traceback.print_exc()

    def _save_file_hosts_settings(self):
        """Save file hosts settings to INI file and encrypt credentials to QSettings"""
        try:
            # Get settings from widget if available
            if not hasattr(self, 'file_hosts_widget') or not self.file_hosts_widget:
                return

            from imxup import set_credential, encrypt_password

            config = configparser.ConfigParser()
            config_file = get_config_path()

            if os.path.exists(config_file):
                config.read(config_file)

            if 'FILE_HOSTS' not in config:
                config.add_section('FILE_HOSTS')

            # Get settings from widget
            widget_settings = self.file_hosts_widget.get_settings()

            # Save connection limits
            config.set('FILE_HOSTS', 'global_limit', str(widget_settings['global_limit']))
            config.set('FILE_HOSTS', 'per_host_limit', str(widget_settings['per_host_limit']))

            # Save per-host settings using new API
            from src.core.file_host_config import save_file_host_setting
            for host_id, host_settings in widget_settings['hosts'].items():
                # Save enabled state and trigger (single string value)
                save_file_host_setting(host_id, 'enabled', host_settings['enabled'])
                save_file_host_setting(host_id, 'trigger', host_settings['trigger'])

                # Save encrypted credentials to QSettings
                creds_text = host_settings.get('credentials', '')
                if creds_text:
                    encrypted = encrypt_password(creds_text)
                    set_credential(f'file_host_{host_id}_credentials', encrypted)
                else:
                    # Clear credentials if empty
                    set_credential(f'file_host_{host_id}_credentials', '')

            # Write INI file
            with open(config_file, 'w') as f:
                config.write(f)

        except Exception as e:
            log(f"Failed to save file hosts settings: {e}", level="warning", category="settings")

    def save_settings(self):
        """Save all settings"""
        try:
            # Save to .ini file via parent
            if self.parent_window:
                # Update parent's settings objects for checkboxes
                self.parent_window.confirm_delete_check.setChecked(self.confirm_delete_check.isChecked())
                self.parent_window.auto_rename_check.setChecked(self.auto_rename_check.isChecked())
                self.parent_window.store_in_uploaded_check.setChecked(self.store_in_uploaded_check.isChecked())
                self.parent_window.store_in_central_check.setChecked(self.store_in_central_check.isChecked())
                
                # Update parent's settings objects for upload settings
                self.parent_window.thumbnail_size_combo.setCurrentIndex(self.thumbnail_size_combo.currentIndex())
                self.parent_window.thumbnail_format_combo.setCurrentIndex(self.thumbnail_format_combo.currentIndex())
                # Template selection is now handled in the Templates tab
                
                # Save via parent
                self.parent_window.save_upload_settings()
                
                # Save theme
                if hasattr(self.parent_window, 'settings'):
                    theme = self.theme_combo.currentText()
                    self.parent_window.settings.setValue('ui/theme', theme)
                    self.parent_window.apply_theme(theme)
                    # Update theme toggle button tooltip
                    if hasattr(self.parent_window, 'theme_toggle_btn'):
                        tooltip = "Switch to light theme" if theme == 'dark' else "Switch to dark theme"
                        self.parent_window.theme_toggle_btn.setToolTip(tooltip)

                # Save font size
                if hasattr(self.parent_window, 'settings'):
                    font_size = self.font_size_spin.value()
                    #print(f"Saving font size to settings: {font_size}")
                    self.parent_window.settings.setValue('ui/font_size', font_size)
                    if hasattr(self.parent_window, 'apply_font_size'):
                        #print(f"Applying font size: {font_size}")
                        self.parent_window.apply_font_size(font_size)

                # Save icons-only setting
                icons_only = self.quick_settings_icons_only_check.isChecked()
                self.parent_window.settings.setValue('ui/quick_settings_icons_only', icons_only)

                # Apply to adaptive panel immediately
                if hasattr(self.parent_window, 'adaptive_settings_panel'):
                    self.parent_window.adaptive_settings_panel.set_icons_only_mode(icons_only)

                # Save worker logos setting
                show_logos = self.show_worker_logos_check.isChecked()
                self.parent_window.settings.setValue('ui/show_worker_logos', show_logos)
                
                # Save scanning settings
                self._save_scanning_settings()

                # Save external apps settings
                self._save_external_apps_settings()

                # Save file hosts settings
                self._save_file_hosts_settings()

                # Save tabs settings
                self._save_tabs_settings()
                    
            return True
        except Exception as e:
            # Create non-blocking error message
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Icon.Critical)
            msg_box.setWindowTitle("Error")
            msg_box.setText(f"Failed to save settings: {str(e)}")
            msg_box.open()
            return False
    
    def _save_scanning_settings(self):
        """Save scanning settings to INI file"""
        try:
            config = configparser.ConfigParser()
            config_file = get_config_path()

            if os.path.exists(config_file):
                config.read(config_file)

            if 'SCANNING' not in config:
                config.add_section('SCANNING')

            # Save all scanning settings
            config.set('SCANNING', 'fast_scanning', str(self.fast_scan_check.isChecked()))
            config.set('SCANNING', 'sampling_method', '0' if self.sampling_fixed_radio.isChecked() else '1')
            config.set('SCANNING', 'sampling_fixed_count', str(self.sampling_fixed_spin.value()))
            config.set('SCANNING', 'sampling_percentage', str(self.sampling_percent_spin.value()))
            config.set('SCANNING', 'exclude_first', str(self.exclude_first_check.isChecked()))
            config.set('SCANNING', 'exclude_last', str(self.exclude_last_check.isChecked()))
            config.set('SCANNING', 'exclude_small_images', str(self.exclude_small_check.isChecked()))
            config.set('SCANNING', 'exclude_small_threshold', str(self.exclude_small_spin.value()))
            config.set('SCANNING', 'exclude_patterns', str(self.exclude_patterns_check.isChecked()))
            config.set('SCANNING', 'exclude_patterns_text', self.exclude_patterns_edit.text())
            config.set('SCANNING', 'stats_exclude_outliers', str(self.stats_exclude_outliers_check.isChecked()))
            config.set('SCANNING', 'use_median', str(self.avg_median_radio.isChecked()))

            with open(config_file, 'w') as f:
                config.write(f)

        except Exception as e:
            log(f"Failed to save scanning settings: {e}", level="warning", category="settings")
    
    def _save_tabs_settings(self):
        """Save tabs settings - handled by TabManager automatically"""
        # TabManager automatically persists settings through QSettings
        # No additional saving needed here as all tab operations
        # in the UI immediately update the TabManager which handles persistence
        pass

    def _save_external_apps_settings(self):
        """Save external apps settings to INI file"""
        try:
            config = configparser.ConfigParser()
            config_file = get_config_path()

            if os.path.exists(config_file):
                config.read(config_file)

            if 'EXTERNAL_APPS' not in config:
                config.add_section('EXTERNAL_APPS')

            # Save execution mode
            config.set('EXTERNAL_APPS', 'parallel_execution', str(self.hooks_parallel_radio.isChecked()))

            # Save hook settings
            for hook_type in ['added', 'started', 'completed']:
                enabled = getattr(self, f'hook_{hook_type}_enabled').isChecked()
                command = getattr(self, f'hook_{hook_type}_command').text()
                show_console = getattr(self, f'hook_{hook_type}_show_console').isChecked()

                #print(f"{timestamp()} DEBUG: Saving {hook_type}: enabled={enabled}, command='{command}', show_console={show_console}")

                # Escape % characters by doubling them for ConfigParser
                # ConfigParser uses % for interpolation, so % needs to be %%
                escaped_command = command.replace('%', '%%')

                config.set('EXTERNAL_APPS', f'hook_{hook_type}_enabled', str(enabled))
                config.set('EXTERNAL_APPS', f'hook_{hook_type}_command', escaped_command)
                config.set('EXTERNAL_APPS', f'hook_{hook_type}_show_console', str(show_console))

                # Save JSON key mappings
                for i in range(1, 5):
                    key_mapping = getattr(self, f'hook_{hook_type}_key{i}').text()
                    config.set('EXTERNAL_APPS', f'hook_{hook_type}_key{i}', key_mapping)

            with open(config_file, 'w') as f:
                config.write(f)

        except Exception as e:
            log(f"Failed to save external apps settings: {e}", level="warning", category="settings")

    def _reset_tabs_settings(self):
        """Reset tabs settings to defaults"""
        try:
            if hasattr(self, 'tab_manager') and self.tab_manager:
                # Reset tab order
                self.tab_manager.reset_tab_order()
                
                # Set default tab to Main
                self.tab_manager.last_active_tab = "Main"
                
                # Refresh display
                self.load_tabs_settings()
        except Exception as e:
            log(f"Failed to reset tabs settings: {e}", level="warning", category="settings")
            
    def reset_to_defaults(self):
        """Reset all settings to defaults"""
        # Create a non-blocking message box
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Reset Settings")
        msg_box.setText("Are you sure you want to reset all settings to defaults?")
        msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg_box.setDefaultButton(QMessageBox.StandardButton.No)
        
        # Connect to slot for non-blocking execution
        msg_box.finished.connect(lambda result: self._handle_reset_confirmation(result))
        msg_box.open()
    
    def _handle_reset_confirmation(self, result):
        """Handle the reset confirmation result"""
        if result == QMessageBox.StandardButton.Yes:
            # Reset upload settings
            self.thumbnail_size_combo.setCurrentIndex(2)  # 250x250 (default)
            self.thumbnail_format_combo.setCurrentIndex(1)  # Proportional (default)
            self.max_retries_slider.setValue(3)  # 3 retries (default)
            self.batch_size_slider.setValue(4)  # 4 concurrent (default)
            self.connect_timeout_slider.setValue(30)  # 30 seconds (default)
            self.read_timeout_slider.setValue(120)  # 120 seconds (default)
            # Template selection is now handled in the Templates tab
            
            # Reset checkboxes
            self.confirm_delete_check.setChecked(True)
            self.auto_rename_check.setChecked(True)
            self.store_in_uploaded_check.setChecked(True)
            self.store_in_central_check.setChecked(True)
            
            # Reset theme
            self.theme_combo.setCurrentText("dark")
            
            # Reset font size
            self.font_size_spin.setValue(9)
            
            # Reset scanning
            self.fast_scan_check.setChecked(True)
            self.pil_sampling_combo.setCurrentIndex(2)
            
            # Reset tabs settings
            self._reset_tabs_settings()
            
    def save_and_close(self):
        """Save settings and close dialog"""
        # Check for unsaved changes in current tab first
        if self.has_unsaved_changes():
            # Save current tab
            if not self.save_current_tab():
                return  # Failed to save, stay open
            self.mark_tab_clean()
        
        # Check all other tabs for unsaved changes
        unsaved_tabs = []
        for i in range(self.tab_widget.count()):
            if i != self.current_tab_index and self.tab_dirty_states.get(i, False):
                unsaved_tabs.append((i, self.tab_widget.tabText(i)))
        
        if unsaved_tabs:
            # Ask user about unsaved changes in other tabs
            tab_names = ", ".join([name for _, name in unsaved_tabs])
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Icon.Question)
            msg_box.setWindowTitle("Unsaved Changes")
            msg_box.setText(f"You have unsaved changes in other tabs: {tab_names}")
            msg_box.setInformativeText("Do you want to save all changes before closing?")
            
            save_all_btn = msg_box.addButton("Save All", QMessageBox.ButtonRole.AcceptRole)
            discard_btn = msg_box.addButton("Discard All", QMessageBox.ButtonRole.DestructiveRole)
            cancel_btn = msg_box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
            
            msg_box.setDefaultButton(save_all_btn)
            result = msg_box.exec()
            
            if msg_box.clickedButton() == save_all_btn:
                # Save all dirty tabs
                for tab_index, _ in unsaved_tabs:
                    old_index = self.current_tab_index
                    self.current_tab_index = tab_index
                    if not self.save_current_tab():
                        self.current_tab_index = old_index
                        return  # Failed to save, stay open
                    self.mark_tab_clean(tab_index)
                    self.current_tab_index = old_index
            elif msg_box.clickedButton() == cancel_btn:
                return  # Cancel, stay open
            # Discard - just continue to close
        
        self.accept()
    
    def on_tab_changed(self, new_index):
        """Handle tab change - check for unsaved changes first"""
        if hasattr(self, 'current_tab_index') and self.current_tab_index != new_index:
            if self.has_unsaved_changes(self.current_tab_index):
                # Block the tab change and ask user about unsaved changes
                self.tab_widget.blockSignals(True)
                self.tab_widget.setCurrentIndex(self.current_tab_index)
                self.tab_widget.blockSignals(False)
                
                self._ask_about_unsaved_changes(
                    lambda: self._change_to_tab(new_index),
                    lambda: None  # Stay on current tab
                )
                return
        
        # No unsaved changes or same tab, proceed with change
        self.current_tab_index = new_index
        self._update_apply_button()
    
    def _change_to_tab(self, new_index):
        """Actually change to the new tab after handling unsaved changes"""
        self.current_tab_index = new_index
        self.tab_widget.blockSignals(True)
        self.tab_widget.setCurrentIndex(new_index)
        self.tab_widget.blockSignals(False)
        self._update_apply_button()
    
    def has_unsaved_changes(self, tab_index=None):
        """Check if the specified tab (or current tab) has unsaved changes"""
        if tab_index is None:
            tab_index = self.tab_widget.currentIndex()
        
        return self.tab_dirty_states.get(tab_index, False)
    
    def mark_tab_dirty(self, tab_index=None):
        """Mark a tab as having unsaved changes"""
        if tab_index is None:
            tab_index = self.tab_widget.currentIndex()
        
        self.tab_dirty_states[tab_index] = True
        self._update_apply_button()
    
    def mark_tab_clean(self, tab_index=None):
        """Mark a tab as having no unsaved changes"""
        if tab_index is None:
            tab_index = self.tab_widget.currentIndex()
        
        self.tab_dirty_states[tab_index] = False
        self._update_apply_button()
    
    def _update_apply_button(self):
        """Update Apply button state based on current tab's dirty state"""
        if hasattr(self, 'apply_btn'):
            self.apply_btn.setEnabled(self.has_unsaved_changes())
    
    def apply_current_tab(self):
        """Apply changes for the current tab only"""
        current_index = self.tab_widget.currentIndex()
        tab_name = self.tab_widget.tabText(current_index)
        
        if self.save_current_tab():
            self.mark_tab_clean(current_index)
            # Show brief success message in status or log
            #print(f"Applied changes for {tab_name} tab")
    
    def save_current_tab(self):
        """Save only the current tab's settings"""
        current_index = self.tab_widget.currentIndex()

        try:
            # NOTE: Tabs and Icons tabs are created but not added to tab widget
            # Actual tab order: General(0), Credentials(1), Templates(2), Logs(3), Image Scanning(4), External Apps(5)
            if current_index == 0:  # General tab
                return self._save_general_tab()
            elif current_index == 1:  # Credentials tab
                return self._save_credentials_tab()
            elif current_index == 2:  # Templates tab
                return self._save_templates_tab()
            elif current_index == 3:  # Logs tab (Tabs/Icons hidden, so this shifts to index 3)
                return self._save_logs_tab()
            elif current_index == 4:  # Image Scanning tab
                self._save_scanning_settings()
                return True
            elif current_index == 5:  # External Apps tab
                self._save_external_apps_settings()
                return True
            elif current_index == 6:  # File Hosts tab
                self._save_file_hosts_settings()
                return True
            elif current_index == 7:  # Advanced tab
                return self._save_advanced_settings()
            else:
                return True
        except Exception as e:
            log(f"Error saving tab {current_index}: {e}", level="warning", category="settings")
            return False
    
    def on_cancel_clicked(self):
        """Handle cancel button click - check for unsaved changes first"""
        self._check_unsaved_changes_before_close(lambda: self.reject())
    
    def _check_unsaved_changes_before_close(self, close_callback):
        """Check for unsaved changes and handle closing"""
        if hasattr(self, 'template_dialog') and self.template_dialog.unsaved_changes:
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Icon.Question)
            msg_box.setWindowTitle("Unsaved Changes")
            msg_box.setText(f"You have unsaved changes to template '{self.template_dialog.current_template_name}'. Do you want to save them before closing?")
            msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel)
            msg_box.setDefaultButton(QMessageBox.StandardButton.Yes)
            msg_box.finished.connect(lambda result: self._handle_unsaved_changes_result(result, close_callback))
            msg_box.open()
        else:
            # No unsaved changes, proceed with close
            close_callback()
    
    def _handle_unsaved_changes_result(self, result, close_callback):
        """Handle the result of unsaved changes dialog"""
        if result == QMessageBox.StandardButton.Yes:
            # Save the template first, then close
            self.template_dialog.save_template()
            close_callback()
        elif result == QMessageBox.StandardButton.No:
            # Don't save, but close
            close_callback()
        # Cancel - do nothing (dialog stays open)
    
    def closeEvent(self, event):
        """Handle dialog closing with unsaved changes check"""
        
        # Check for unsaved changes in any tab
        has_unsaved = False
        for i in range(self.tab_widget.count()):
            if self.tab_dirty_states.get(i, False):
                has_unsaved = True
                break
        
        # Also check if Templates tab has unsaved changes (legacy check)
        if hasattr(self, 'template_dialog') and self.template_dialog.unsaved_changes:
            has_unsaved = True
        
        if has_unsaved:
            # Use the same logic as save_and_close but for close
            event.ignore()  # Prevent immediate close
            self._handle_close_with_unsaved_changes()
        else:
            # No unsaved changes, proceed with normal close
            event.accept()
    
    def _handle_close_with_unsaved_changes(self):
        """Handle close with unsaved changes - reuse save_and_close logic"""
        # Check for unsaved changes in current tab first
        if self.has_unsaved_changes():
            # Save current tab
            if not self.save_current_tab():
                return  # Failed to save, stay open
            self.mark_tab_clean()
        
        # Check all other tabs for unsaved changes
        unsaved_tabs = []
        for i in range(self.tab_widget.count()):
            if i != self.current_tab_index and self.tab_dirty_states.get(i, False):
                unsaved_tabs.append((i, self.tab_widget.tabText(i)))
        
        if unsaved_tabs:
            # Ask user about unsaved changes in other tabs
            tab_names = ", ".join([name for _, name in unsaved_tabs])
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Icon.Question)
            msg_box.setWindowTitle("Unsaved Changes")
            msg_box.setText(f"You have unsaved changes in other tabs: {tab_names}")
            msg_box.setInformativeText("Do you want to save all changes before closing?")
            
            save_all_btn = msg_box.addButton("Save All", QMessageBox.ButtonRole.AcceptRole)
            discard_btn = msg_box.addButton("Discard All", QMessageBox.ButtonRole.DestructiveRole)
            cancel_btn = msg_box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
            
            msg_box.setDefaultButton(save_all_btn)
            msg_box.finished.connect(lambda result: self._handle_close_unsaved_result(result, msg_box.clickedButton(), save_all_btn, discard_btn, cancel_btn))
            msg_box.open()
        else:
            # No other unsaved tabs, proceed with close
            self.accept()
    
    def _handle_close_unsaved_result(self, result, clicked_button, save_all_btn, discard_btn, cancel_btn):
        """Handle result of close unsaved changes dialog"""
        if clicked_button == save_all_btn:
            # Save all dirty tabs
            unsaved_tabs = []
            for i in range(self.tab_widget.count()):
                if i != self.current_tab_index and self.tab_dirty_states.get(i, False):
                    unsaved_tabs.append((i, self.tab_widget.tabText(i)))
            
            for tab_index, _ in unsaved_tabs:
                old_index = self.current_tab_index
                self.current_tab_index = tab_index
                if not self.save_current_tab():
                    self.current_tab_index = old_index
                    return  # Failed to save, stay open
                self.mark_tab_clean(tab_index)
                self.current_tab_index = old_index
            
            # All saved successfully, close
            self.accept()
        elif clicked_button == discard_btn:
            # Discard all changes and close
            self.accept()
        # Cancel - do nothing, stay open
    
    def _ask_about_unsaved_changes(self, save_callback, cancel_callback):
        """Ask user about unsaved changes with save/discard/cancel options"""
        current_index = self.tab_widget.currentIndex()
        tab_name = self.tab_widget.tabText(current_index)
        
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Icon.Question)
        msg_box.setWindowTitle("Unsaved Changes")
        msg_box.setText(f"You have unsaved changes in the '{tab_name}' tab.")
        msg_box.setInformativeText("Do you want to save your changes before switching tabs?")
        
        save_btn = msg_box.addButton("Save", QMessageBox.ButtonRole.AcceptRole)
        discard_btn = msg_box.addButton("Discard", QMessageBox.ButtonRole.DestructiveRole)
        cancel_btn = msg_box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        
        msg_box.setDefaultButton(save_btn)
        
        # Use exec() for blocking dialog instead of open() with signals
        result = msg_box.exec()
        clicked_button = msg_box.clickedButton()
        
        if clicked_button == save_btn:
            # Save current tab first, then proceed
            if self.save_current_tab():
                self.mark_tab_clean()
                save_callback()
        elif clicked_button == discard_btn:
            # Discard changes by reloading the tab and proceed
            self._reload_current_tab()
            self.mark_tab_clean()
            save_callback()
        # Cancel button - do nothing, stay on current tab
    
    def _reload_current_tab(self):
        """Reload current tab's form values from saved settings (discard changes)"""
        current_index = self.tab_widget.currentIndex()
        
        if current_index == 0:  # General tab
            self._reload_general_tab()
        elif current_index == 6:  # Image Scanning tab
            self._reload_scanning_tab()
        # Other tabs don't have form controls that need reloading
    
    def _reload_general_tab(self):
        """Reload General tab form values from saved settings"""
        defaults = load_user_defaults()
        
        # Reload upload settings
        self.thumbnail_size_combo.setCurrentIndex(defaults.get('thumbnail_size', 3) - 1)
        self.thumbnail_format_combo.setCurrentIndex(defaults.get('thumbnail_format', 2) - 1)
        self.max_retries_slider.setValue(defaults.get('max_retries', 3))
        self.batch_size_slider.setValue(defaults.get('parallel_batch_size', 4))
        self.connect_timeout_slider.setValue(defaults.get('upload_connect_timeout', 30))
        self.read_timeout_slider.setValue(defaults.get('upload_read_timeout', 120))


        # Reload general settings
        self.confirm_delete_check.setChecked(defaults.get('confirm_delete', True))
        self.auto_rename_check.setChecked(defaults.get('auto_rename', True))
        self.check_updates_checkbox.setChecked(defaults.get('check_updates_on_startup', True))

        # Reload storage settings
        self.store_in_uploaded_check.setChecked(defaults.get('store_in_uploaded', True))
        self.store_in_central_check.setChecked(defaults.get('store_in_central', True))
        
        from imxup import get_central_store_base_path
        current_path = defaults.get('central_store_path') or get_central_store_base_path()
        self.path_edit.setText(current_path)
        
        # Reload theme
        if self.parent_window and hasattr(self.parent_window, 'settings'):
            current_theme = self.parent_window.settings.value('ui/theme', 'dark')
            index = self.theme_combo.findText(current_theme)
            if index >= 0:
                self.theme_combo.setCurrentIndex(index)
        
        # Reload font size
        if self.parent_window and hasattr(self.parent_window, 'settings'):
            current_font_size = int(self.parent_window.settings.value('ui/font_size', 9))
            self.font_size_spin.setValue(current_font_size)
    
    def _reload_scanning_tab(self):
        """Reload Scanning tab form values from saved settings"""
        # Reload scanning settings from QSettings
        if self.parent_window and hasattr(self.parent_window, 'settings'):
            # Just call the main load function - it handles everything
            self._load_scanning_settings()
    
    def _save_general_tab(self):
        """Save General tab settings only"""
        try:
            config = configparser.ConfigParser()
            config_file = get_config_path()
            
            if os.path.exists(config_file):
                config.read(config_file)
            
            if 'UPLOAD' not in config:
                config.add_section('UPLOAD')
            
            if 'DEFAULTS' not in config:
                config.add_section('DEFAULTS')
                
            # Save thumbnail settings
            config.set('DEFAULTS', 'thumbnail_size', str(self.thumbnail_size_combo.currentIndex() + 1))
            config.set('DEFAULTS', 'thumbnail_format', str(self.thumbnail_format_combo.currentIndex() + 1))
            config.set('DEFAULTS', 'max_retries', str(self.max_retries_slider.value()))

            # Check if batch size changed to trigger connection pool refresh
            # load_user_defaults already imported from imxup at top of file
            current_defaults = load_user_defaults()
            old_batch_size = current_defaults.get('parallel_batch_size', 4)
            new_batch_size = self.batch_size_slider.value()
            config.set('DEFAULTS', 'parallel_batch_size', str(new_batch_size))

            # Signal uploader to refresh connection pool if batch size changed
            if old_batch_size != new_batch_size and self.parent_window and hasattr(self.parent_window, 'uploader'):
                try:
                    self.parent_window.uploader.refresh_session_pool()
                except Exception as e:
                    log(f"Failed to refresh connection pool: {e}", level="warning", category="settings")

            # Save timeout settings
            config.set('DEFAULTS', 'upload_connect_timeout', str(self.connect_timeout_slider.value()))
            config.set('DEFAULTS', 'upload_read_timeout', str(self.read_timeout_slider.value()))


            # Save general settings
            config.set('DEFAULTS', 'confirm_delete', str(self.confirm_delete_check.isChecked()))
            config.set('DEFAULTS', 'auto_rename', str(self.auto_rename_check.isChecked()))
            config.set('DEFAULTS', 'auto_regenerate_bbcode', str(self.auto_regenerate_bbcode_check.isChecked()))
            config.set('DEFAULTS', 'auto_start_upload', str(self.auto_start_upload_check.isChecked()))
            config.set('DEFAULTS', 'auto_clear_completed', str(self.auto_clear_completed_check.isChecked()))
            config.set('DEFAULTS', 'check_updates_on_startup', str(self.check_updates_checkbox.isChecked()))
            config.set('DEFAULTS', 'store_in_uploaded', str(self.store_in_uploaded_check.isChecked()))
            config.set('DEFAULTS', 'store_in_central', str(self.store_in_central_check.isChecked()))
            
            # Determine storage mode and path
            from imxup import get_central_store_base_path, get_default_central_store_base_path
            
            # Get the CURRENT active path (what's actually being used)
            current_active_path = get_central_store_base_path()
            
            # Determine what the new path should be
            new_path = None
            storage_mode = 'home'
            
            if self.home_radio.isChecked():
                storage_mode = 'home'
                new_path = get_default_central_store_base_path()
            elif self.portable_radio.isChecked():
                storage_mode = 'portable'
                from imxup import get_project_root
                app_root = get_project_root()  # Use centralized function that handles frozen exe correctly
                new_path = os.path.join(app_root, '.imxup')
            elif self.custom_radio.isChecked():
                storage_mode = 'custom'
                new_path = self.path_edit.text().strip()
            
            # Check if path is actually changing
            if new_path and os.path.normpath(new_path) != os.path.normpath(current_active_path):
                # Check if NEW location already has a config file
                new_config_file = os.path.join(new_path, 'imxup.ini')
                if os.path.exists(new_config_file):
                    # NEW location already has config - ask what to do
                    conflict_msg = QMessageBox(self)
                    conflict_msg.setIcon(QMessageBox.Icon.Warning)
                    conflict_msg.setWindowTitle("Existing Configuration Found")
                    conflict_msg.setText(f"The new location already contains an imxup.ini file:\n{new_config_file}")
                    conflict_msg.setInformativeText("How would you like to handle this?")

                    keep_btn = conflict_msg.addButton("Keep Existing", QMessageBox.ButtonRole.YesRole)
                    overwrite_btn = conflict_msg.addButton("Overwrite with Current", QMessageBox.ButtonRole.NoRole)
                    cancel_btn = conflict_msg.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)

                    conflict_msg.setDefaultButton(keep_btn)
                    conflict_msg.exec()

                    if conflict_msg.clickedButton() == cancel_btn:
                        return True  # Cancel the save
                    elif conflict_msg.clickedButton() == keep_btn:
                        # Just update QSettings, don't write new config file
                        if self.parent_window and hasattr(self.parent_window, 'settings'):
                            if storage_mode == 'home':
                                self.parent_window.settings.remove("config/base_path")
                            else:
                                self.parent_window.settings.setValue("config/base_path", new_path)
                        QMessageBox.information(self, "Restart Required",
                                              "Please restart the application to use the new storage location.")
                        return True
                    # else: overwrite_btn - continue with migration logic below

                # Path is changing - handle migration
                if os.path.exists(current_active_path):
                    # Ask about migration
                    msg_box = QMessageBox(self)
                    msg_box.setIcon(QMessageBox.Icon.Question)
                    msg_box.setWindowTitle("Storage Location Change")
                    msg_box.setText(f"You're changing the data location from:\n{current_active_path}\nto:\n{new_path}")
                    msg_box.setInformativeText("Would you like to migrate your existing data?\n\nNote: The application will need to restart after migration.")
                    
                    yes_btn = msg_box.addButton("Yes - Migrate & Restart", QMessageBox.ButtonRole.YesRole)
                    no_btn = msg_box.addButton("No - Fresh Start", QMessageBox.ButtonRole.NoRole)
                    cancel_btn = msg_box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
                    
                    msg_box.setDefaultButton(yes_btn)
                    result = msg_box.exec()
                    
                    if msg_box.clickedButton() == cancel_btn:
                        # Don't save changes
                        return True

                    # CRITICAL: Save base path to QSettings FIRST (before writing config file)
                    if self.parent_window and hasattr(self.parent_window, 'settings'):
                        if storage_mode == 'home':
                            self.parent_window.settings.remove("config/base_path")
                        else:
                            self.parent_window.settings.setValue("config/base_path", new_path)

                    # Save new settings to INI file in NEW location
                    config.set('DEFAULTS', 'storage_mode', storage_mode)
                    config.set('DEFAULTS', 'central_store_path', new_path)
                    # Write to NEW location (not config_file which is old location)
                    new_config_file = os.path.join(new_path, 'imxup.ini')
                    os.makedirs(new_path, exist_ok=True)
                    with open(new_config_file, 'w') as f:
                        config.write(f)

                    if msg_box.clickedButton() == yes_btn:
                        # Perform migration then restart
                        self._perform_migration_and_restart(current_active_path, new_path)
                    else:
                        # Just restart with new location
                        QMessageBox.information(self, "Restart Required", 
                                              "Please restart the application to use the new storage location.")
                else:
                    # Old path doesn't exist, just save
                    # CRITICAL: Save base path to QSettings FIRST
                    if self.parent_window and hasattr(self.parent_window, 'settings'):
                        if storage_mode == 'home':
                            self.parent_window.settings.remove("config/base_path")
                        else:
                            self.parent_window.settings.setValue("config/base_path", new_path)

                    config.set('DEFAULTS', 'storage_mode', storage_mode)
                    config.set('DEFAULTS', 'central_store_path', new_path)
                    # Write to NEW location
                    new_config_file = os.path.join(new_path, 'imxup.ini')
                    os.makedirs(new_path, exist_ok=True)
                    with open(new_config_file, 'w') as f:
                        config.write(f)
            else:
                # Path not changing, just save other settings
                config.set('DEFAULTS', 'storage_mode', storage_mode)
                if new_path:
                    config.set('DEFAULTS', 'central_store_path', new_path)
                with open(config_file, 'w') as f:
                    config.write(f)

                # CRITICAL: Save base path to QSettings for bootstrap
                if self.parent_window and hasattr(self.parent_window, 'settings'):
                    if storage_mode == 'home':
                        # Clear custom path - use default home folder
                        self.parent_window.settings.remove("config/base_path")
                    elif new_path:
                        # Save custom/portable path
                        self.parent_window.settings.setValue("config/base_path", new_path)
            
            # Update parent GUI controls
            if self.parent_window:
                self.parent_window.thumbnail_size_combo.setCurrentIndex(self.thumbnail_size_combo.currentIndex())
                self.parent_window.thumbnail_format_combo.setCurrentIndex(self.thumbnail_format_combo.currentIndex())
                
                # Update storage settings (only those that exist in parent)
                if hasattr(self.parent_window, 'confirm_delete_check'):
                    self.parent_window.confirm_delete_check.setChecked(self.confirm_delete_check.isChecked())
                if hasattr(self.parent_window, 'auto_rename_check'):
                    self.parent_window.auto_rename_check.setChecked(self.auto_rename_check.isChecked())
                if hasattr(self.parent_window, 'store_in_uploaded_check'):
                    self.parent_window.store_in_uploaded_check.setChecked(self.store_in_uploaded_check.isChecked())
                if hasattr(self.parent_window, 'store_in_central_check'):
                    self.parent_window.store_in_central_check.setChecked(self.store_in_central_check.isChecked())
                if storage_mode == 'custom':
                    self.parent_window.central_store_path_value = new_path
                
                # Save theme and font size to QSettings
                if hasattr(self.parent_window, 'settings'):
                    font_size = self.font_size_spin.value()
                    theme = self.theme_combo.currentText()
                    #print(f"_save_general_tab: Saving font size to settings: {font_size}")
                    self.parent_window.settings.setValue('ui/theme', theme)
                    self.parent_window.settings.setValue('ui/font_size', font_size)

                    # Save icons-only setting
                    icons_only = self.quick_settings_icons_only_check.isChecked()
                    self.parent_window.settings.setValue('ui/quick_settings_icons_only', icons_only)

                    # Apply to adaptive panel immediately
                    if hasattr(self.parent_window, 'adaptive_settings_panel'):
                        self.parent_window.adaptive_settings_panel.set_icons_only_mode(icons_only)

                    # Save worker logos setting
                    show_logos = self.show_worker_logos_check.isChecked()
                    self.parent_window.settings.setValue('ui/show_worker_logos', show_logos)

                    # Apply theme and font size immediately
                    self.parent_window.apply_theme(theme)
                    # Update theme toggle button tooltip
                    if hasattr(self.parent_window, 'theme_toggle_btn'):
                        tooltip = "Switch to light theme" if theme == 'dark' else "Switch to dark theme"
                        self.parent_window.theme_toggle_btn.setToolTip(tooltip)
                    if hasattr(self.parent_window, 'apply_font_size'):
                        #print(f"_save_general_tab: Applying font size: {font_size}")
                        self.parent_window.apply_font_size(font_size)
            
            return True
        except Exception as e:
            log(f"Error saving general settings: {e}", level="warning", category="settings")
            return False
    
    def _perform_migration_and_restart(self, old_path, new_path):
        """Perform migration of data and restart the application"""
        import shutil
        from PyQt6.QtWidgets import QProgressDialog
        import subprocess
        
        progress = QProgressDialog("Migrating data...", None, 0, 5, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setCancelButton(None)  # Can't cancel during migration
        progress.setValue(0)
        
        try:
            # Create new directory if needed
            os.makedirs(new_path, exist_ok=True)
            
            # Close database connection if parent has one
            if self.parent_window and hasattr(self.parent_window, 'queue_manager'):
                progress.setLabelText("Closing database connection...")
                try:
                    self.parent_window.queue_manager.shutdown()
                except (AttributeError, RuntimeError):
                    pass
            
            progress.setValue(1)
            
            # Migrate database files (all of them)
            progress.setLabelText("Migrating database...")
            for db_file in ['imxup.db', 'imxup.db-shm', 'imxup.db-wal']:
                old_db = os.path.join(old_path, db_file)
                new_db = os.path.join(new_path, db_file)
                if os.path.exists(old_db):
                    shutil.copy2(old_db, new_db)
            
            progress.setValue(2)
            
            # Migrate templates
            progress.setLabelText("Migrating templates...")
            old_templates = os.path.join(old_path, 'templates')
            new_templates = os.path.join(new_path, 'templates')
            if os.path.exists(old_templates):
                if os.path.exists(new_templates):
                    shutil.rmtree(new_templates)
                shutil.copytree(old_templates, new_templates)
            
            progress.setValue(3)
            
            # Migrate galleries
            progress.setLabelText("Migrating galleries...")
            old_galleries = os.path.join(old_path, 'galleries')
            new_galleries = os.path.join(new_path, 'galleries')
            if os.path.exists(old_galleries):
                if os.path.exists(new_galleries):
                    shutil.rmtree(new_galleries)
                shutil.copytree(old_galleries, new_galleries)
            
            progress.setValue(4)
            
            # Migrate logs
            progress.setLabelText("Migrating logs...")
            old_logs = os.path.join(old_path, 'logs')
            new_logs = os.path.join(new_path, 'logs')
            if os.path.exists(old_logs):
                if os.path.exists(new_logs):
                    shutil.rmtree(new_logs)
                shutil.copytree(old_logs, new_logs)
            
            progress.setValue(5)
            progress.close()
            
            # Show success and restart
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Icon.Information)
            msg.setWindowTitle("Migration Complete")
            msg.setText(f"Data successfully migrated to:\n{new_path}")
            msg.setInformativeText("The application will now restart to use the new location.")
            msg.exec()
            
            # Restart the application
            if self.parent_window:
                self.parent_window.close()
            python = sys.executable
            subprocess.Popen([python, "imxup.py", "--gui"])
            QApplication.quit()
            
        except Exception as e:
            progress.close()
            QMessageBox.critical(self, "Migration Failed", 
                               f"Failed to migrate data: {str(e)}\n\nThe settings have been saved but data was not migrated.\nPlease manually copy your data or revert the settings.")
    
    def _save_upload_tab(self):
        """Save Upload/Credentials tab settings only"""
        try:
            # Credentials are saved through their individual button handlers
            # This tab doesn't have bulk settings to save
            return True
        except Exception as e:
            log(f"Error saving upload settings: {e}", level="warning", category="settings")
            return False
    
    def _save_templates_tab(self):
        """Save Templates tab settings only"""
        try:
            if hasattr(self, 'template_dialog') and self.template_dialog.unsaved_changes:
                return self.template_dialog.save_template()
            return True
        except Exception as e:
            log(f"Error saving template settings: {e}", level="warning", category="settings")
            return False
    
    def _save_tabs_tab(self):
        """Save Tabs tab settings only"""
        try:
            config = configparser.ConfigParser()
            config_file = get_config_path()
            
            if os.path.exists(config_file):
                config.read(config_file)
            
            if 'TABS' not in config:
                config.add_section('TABS')
            
            # Save tab manager settings (if any specific settings exist)
            # This tab is mostly for viewing/managing tabs, not configuration
            return True
        except Exception as e:
            log(f"Error saving tab settings: {e}", level="warning", category="settings")
            return False
    
    def _save_icons_tab(self):
        """Save Icons tab settings and refresh main window icons"""
        try:
            # Import here to avoid circular imports
            from .icon_manager import get_icon_manager
            
            # Get the icon manager instance
            icon_manager = get_icon_manager()
            if icon_manager:
                # Refresh the icon cache to ensure changes are loaded
                icon_manager.refresh_cache()
                
                # Signal the main window to refresh all status icons
                if hasattr(self, 'parent') and self.parent_window and hasattr(self.parent_window, 'refresh_all_status_icons'):
                    self.parent_window.refresh_all_status_icons()
                elif hasattr(self, 'parent') and self.parent_window and hasattr(self.parent_window, '_update_all_status_icons'):
                    self.parent_window._update_all_status_icons()
                
                #print("Icon changes applied successfully")
                return True
            else:
                log("IconManager not available", level="warning", category="ui")
                return True
                
        except Exception as e:
            log(f"Error saving icons tab: {e}", level="error", category="settings")
            from PyQt6.QtWidgets import QMessageBox
            show_error(self, "Error", f"Failed to apply icon changes: {str(e)}")
            return False
    
    def _save_logs_tab(self):
        """Save Logs tab settings"""
        try:
            if hasattr(self, 'log_settings_widget'):
                self.log_settings_widget.save_settings()
                # Cache refresh and re-rendering handled by main_window._handle_settings_dialog_result()
            return True
        except Exception as e:
            log(f"Error saving logs tab: {e}", level="warning", category="settings")
            return False

    def populate_icon_list(self):
        """Populate the icon list with all available icons"""
        from .icon_manager import IconManager
        
        # Get icon categories from the icon manager
        icon_categories = {
            "Status Icons": [
                ("status_completed", "Completed", "Gallery upload completed successfully"),
                ("status_failed", "Failed", "Gallery upload failed"),
                ("status_uploading", "Uploading", "Currently uploading gallery"),
                ("status_paused", "Paused", "Upload paused by user"),
                ("status_queued", "Queued", "Waiting in upload queue"),
                ("status_ready", "Ready", "Ready to start upload"),
                ("status_pending", "Pending", "Preparing for upload"),
                ("status_incomplete", "Incomplete", "Upload partially completed"),
                ("status_scan_failed", "Scan Failed", "Failed to scan gallery images"),
                ("status_scanning", "Scanning", "Currently scanning gallery"),
            ],
            "Action Icons": [
                ("action_start", "Start", "Start gallery upload"),
                ("action_stop", "Stop", "Stop current upload"),
                ("action_view", "View", "View gallery online"),
                ("action_view_error", "View Error", "View error details"),
                ("action_cancel", "Cancel", "Cancel upload"),
                ("action_resume", "Resume", "Resume paused upload"),
            ],
            "UI Icons": [
                ("templates", "Templates", "Template management icon"),
                ("credentials", "Credentials", "Login credentials icon"),
                ("main_window", "Main Window", "Application window icon"),
                ("app_icon", "Application", "Main application icon"),
            ]
        }
        
        self.icon_tree.clear()
        self.icon_data = {}  # Store full icon information
        
        for category, icons in icon_categories.items():
            # Add category header
            category_item = QListWidgetItem(f"=== {category} ===")
            category_item.setFlags(Qt.ItemFlag.NoItemFlags)  # Not selectable
            
            # Set theme-aware background color
            try:
                pal = self.palette()
                bg = pal.window().color()
                is_dark = (0.2126 * bg.redF() + 0.7152 * bg.greenF() + 0.0722 * bg.blueF()) < 0.5
                if is_dark:
                    category_item.setBackground(QColor(64, 64, 64))  # Dark theme
                else:
                    category_item.setBackground(QColor(240, 240, 240))  # Light theme
            except Exception:
                category_item.setBackground(QColor(240, 240, 240))  # Fallback
            
            font = category_item.font()
            font.setBold(True)
            category_item.setFont(font)
            self.icon_tree.addItem(category_item)
            
            # Add icons in category
            for icon_key, display_name, description in icons:
                item = QListWidgetItem(f"  {display_name}")
                item.setData(Qt.ItemDataRole.UserRole, icon_key)
                self.icon_tree.addItem(item)
                
                # Store full data
                self.icon_data[icon_key] = {
                    'display_name': display_name,
                    'description': description,
                    'category': category
                }
    
    def on_icon_selection_changed(self):
        """Handle icon selection change - now updates both light and dark previews"""
        current_item = self.icon_tree.currentItem()
        if not current_item or not current_item.data(Qt.ItemDataRole.UserRole):
            # Category header or no selection - clear everything
            self.icon_name_label.setText("Select an icon to customize")
            self.icon_description_label.setText("")
            self.config_type_label.setText("Configuration: Unknown")
            
            # Clear light preview
            self.light_icon_label.clear()
            self.light_status_label.setText("No icon")
            self.light_browse_btn.setEnabled(False)
            self.light_reset_btn.setEnabled(False)
            
            # Clear dark preview
            self.dark_icon_label.clear()
            self.dark_status_label.setText("No icon")
            self.dark_browse_btn.setEnabled(False)
            self.dark_reset_btn.setEnabled(False)
            return
        
        icon_key = current_item.data(Qt.ItemDataRole.UserRole)
        icon_info = self.icon_data.get(icon_key, {})
        
        # Update basic info
        self.icon_name_label.setText(icon_info.get('display_name', icon_key))
        self.icon_description_label.setText(icon_info.get('description', ''))
        
        # Update both light and dark previews
        self.update_icon_previews_dual(icon_key)
        
        # Enable controls
        self.light_browse_btn.setEnabled(True)
        self.light_reset_btn.setEnabled(True)
        self.dark_browse_btn.setEnabled(True) 
        self.dark_reset_btn.setEnabled(True)
    
    def update_selected_icon_preview(self, icon_key):
        """Update the preview of the selected icon"""
        try:
            from .icon_manager import get_icon_manager
            icon_manager = get_icon_manager()
            
            if not icon_manager:
                self.current_icon_label.setText("N/A")
                return
            
            # Get theme state from combo
            theme_text = self.theme_preview_combo.currentText()
            theme_mode = 'dark' if "Dark" in theme_text else 'light'
            is_selected = "Selected" in theme_text

            # Get icon based on current theme settings
            icon = icon_manager.get_icon(icon_key, theme_mode=theme_mode, is_selected=is_selected)
            
            if not icon.isNull():
                # Display icon
                pixmap = icon.pixmap(24, 24)
                self.current_icon_label.setPixmap(pixmap)
            else:
                self.current_icon_label.setText("Missing")
            
            # Update status information
            icon_config = icon_manager.ICON_MAP.get(icon_key, "Unknown")
            
            if isinstance(icon_config, str):
                self.theme_info_label.setText("Single icon (auto-adapt)")
                # Check if file exists
                import os
                icon_path = os.path.join(icon_manager.assets_dir, icon_config)
                if os.path.exists(icon_path):
                    self.default_status_label.setText("Using: Default file")
                else:
                    self.default_status_label.setText("Using: Qt fallback")
            elif isinstance(icon_config, list):
                self.theme_info_label.setText("Light/Dark pair")
                # Check if files exist
                import os
                light_exists = os.path.exists(os.path.join(icon_manager.assets_dir, icon_config[0]))
                dark_exists = len(icon_config) > 1 and os.path.exists(os.path.join(icon_manager.assets_dir, icon_config[1]))
                
                if light_exists and dark_exists:
                    self.default_status_label.setText("Using: Both files")
                elif light_exists:
                    self.default_status_label.setText("Using: Light only")
                else:
                    self.default_status_label.setText("Using: Qt fallback")
            else:
                self.theme_info_label.setText("Invalid config")
                self.default_status_label.setText("Using: Qt fallback")
                
        except Exception as e:
            log(f"Error updating icon preview: {e}", level="warning", category="ui")
            self.current_icon_label.setText("Error")
    
    def update_icon_previews(self):
        """Update all icon previews when theme changes (legacy compatibility)"""
        current_item = self.icon_tree.currentItem()
        if current_item and current_item.data(Qt.ItemDataRole.UserRole):
            icon_key = current_item.data(Qt.ItemDataRole.UserRole)
            self.update_icon_previews_dual(icon_key)
    
    def update_icon_previews_dual(self, icon_key):
        """Update both light and dark icon previews with proper state detection"""
        try:
            from .icon_manager import get_icon_manager
            icon_manager = get_icon_manager()
            
            if not icon_manager:
                self.light_status_label.setText("Manager unavailable")
                self.dark_status_label.setText("Manager unavailable")
                self.config_type_label.setText("Configuration: Error")
                return
            
            # Get icon configuration
            icon_config = icon_manager.ICON_MAP.get(icon_key, "Unknown")
            
            # Determine configuration type and update label
            if isinstance(icon_config, str):
                self.config_type_label.setText("Configuration: Single icon (auto-adapts)")
                self.config_type_label.setProperty("icon-config", "single")
                self.config_type_label.style().unpolish(self.config_type_label)
                self.config_type_label.style().polish(self.config_type_label)
            elif isinstance(icon_config, list):
                self.config_type_label.setText("Configuration: Light/Dark pair (manual control)")
                self.config_type_label.setProperty("icon-config", "pair")
                self.config_type_label.style().unpolish(self.config_type_label)
                self.config_type_label.style().polish(self.config_type_label)
            else:
                self.config_type_label.setText("Configuration: Invalid")
                self.config_type_label.setProperty("icon-config", "invalid")
                self.config_type_label.style().unpolish(self.config_type_label)
                self.config_type_label.style().polish(self.config_type_label)
            
            # Update light theme preview (unselected light theme)
            light_icon = icon_manager.get_icon(icon_key, theme_mode='light', is_selected=False, requested_size=96)
            if not light_icon.isNull():
                pixmap = light_icon.pixmap(96, 96)  # Match the label size
                self.light_icon_label.setPixmap(pixmap)
                
                # Check if this is inverted from original
                if isinstance(icon_config, str):
                    # Single icon - check if this would be inverted
                    self.light_status_label.setText("Original")
                    self.light_status_label.setProperty("icon-status", "available")
                    self.light_status_label.style().unpolish(self.light_status_label)
                    self.light_status_label.style().polish(self.light_status_label)
                else:
                    self.light_status_label.setText("Light variant")
                    self.light_status_label.setProperty("icon-status", "available")
                    self.light_status_label.style().unpolish(self.light_status_label)
                    self.light_status_label.style().polish(self.light_status_label)
            else:
                self.light_icon_label.setText("Missing")
                self.light_status_label.setText("Qt fallback")
                self.light_status_label.setProperty("icon-status", "fallback")
                self.light_status_label.style().unpolish(self.light_status_label)
                self.light_status_label.style().polish(self.light_status_label)
            
            # Update dark theme preview (unselected dark theme) 
            dark_icon = icon_manager.get_icon(icon_key, theme_mode='dark', is_selected=False, requested_size=96)
            if not dark_icon.isNull():
                pixmap = dark_icon.pixmap(96, 96)  # Match the label size
                self.dark_icon_label.setPixmap(pixmap)
                
                # Check if this is inverted from original
                if isinstance(icon_config, str):
                    # Single icon - original file used directly
                    self.dark_status_label.setText("Original")
                    self.dark_status_label.setProperty("icon-status", "available")
                    self.dark_status_label.style().unpolish(self.dark_status_label)
                    self.dark_status_label.style().polish(self.dark_status_label)
                else:
                    self.dark_status_label.setText("Dark variant")
                    self.dark_status_label.setProperty("icon-status", "available")
                    self.dark_status_label.style().unpolish(self.dark_status_label)
                    self.dark_status_label.style().polish(self.dark_status_label)
            else:
                self.dark_icon_label.setText("Missing")
                self.dark_status_label.setText("Qt fallback")
                self.dark_status_label.setProperty("icon-status", "fallback")
                self.dark_status_label.style().unpolish(self.dark_status_label)
                self.dark_status_label.style().polish(self.dark_status_label)
            
            # Update reset button states based on whether icons are default
            self._update_reset_button_states(icon_key, icon_config)
                
        except Exception as e:
            log(f"Error updating dual icon previews: {e}", level="warning", category="ui")
            self.light_status_label.setText("Error")
            self.dark_status_label.setText("Error")
            self.config_type_label.setText("Configuration: Error")
    
    def _update_reset_button_states(self, icon_key, icon_config):
        """Update reset button states based on whether icons are at default state"""
        from .icon_manager import get_icon_manager
        import os
        
        icon_manager = get_icon_manager()
        if not icon_manager:
            return
        
        try:
            if isinstance(icon_config, str):
                # Single icon - check if file exists (custom) vs using default
                icon_path = os.path.join(icon_manager.assets_dir, icon_config)
                has_custom_file = os.path.exists(icon_path)
                
                # Enable reset only if we have a backup (can actually restore)
                backup_exists = os.path.exists(icon_path + ".backup")
                
                self.light_reset_btn.setEnabled(backup_exists)
                self.dark_reset_btn.setEnabled(backup_exists)
                
            elif isinstance(icon_config, list):
                # Light/dark pair - check each file
                light_path = os.path.join(icon_manager.assets_dir, icon_config[0])
                dark_path = os.path.join(icon_manager.assets_dir, icon_config[1]) if len(icon_config) > 1 else None

                light_backup_exists = os.path.exists(light_path + ".backup")
                dark_backup_exists = bool(dark_path and os.path.exists(dark_path + ".backup"))

                self.light_reset_btn.setEnabled(light_backup_exists)
                self.dark_reset_btn.setEnabled(dark_backup_exists)
            else:
                # Invalid config
                self.light_reset_btn.setEnabled(False)
                self.dark_reset_btn.setEnabled(False)
                
        except Exception as e:
            log(f"Error updating reset button states: {e}", level="warning", category="ui")
            # Enable by default if we can't determine state
            self.light_reset_btn.setEnabled(True)
            self.dark_reset_btn.setEnabled(True)
    
    def handle_icon_drop(self, file_path):
        """Handle dropped icon file"""
        current_item = self.icon_tree.currentItem()
        if not current_item or not current_item.data(Qt.ItemDataRole.UserRole):
            show_warning(self, "No Icon Selected", 
                              "Please select an icon from the list first.")
            return
        
        icon_key = current_item.data(Qt.ItemDataRole.UserRole)
        
        # Validate file type
        if not file_path.lower().endswith(('.png', '.ico', '.svg', '.jpg', '.jpeg')):
            show_warning(self, "Invalid File Type", 
                              "Please select a valid image file (PNG, ICO, SVG, JPG).")
            return
        
        # Show confirmation
        confirmation_text = f"Replace the icon for '{self.icon_data[icon_key]['display_name']}' with the selected file?"
        detailed_text = f"File: {file_path}"
        
        if MessageBoxFactory.question(
            self, "Replace Icon", confirmation_text, detailed_text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            self.replace_icon_file(icon_key, file_path)
    
    def handle_icon_drop_variant(self, file_path, variant):
        """Handle dropped icon file for specific variant (light/dark)"""
        current_item = self.icon_tree.currentItem()
        if not current_item or not current_item.data(Qt.ItemDataRole.UserRole):
            show_warning(self, "No Icon Selected", 
                              "Please select an icon from the list first.")
            return
        
        icon_key = current_item.data(Qt.ItemDataRole.UserRole)
        
        # Validate file type
        if not file_path.lower().endswith(('.png', '.ico', '.svg', '.jpg', '.jpeg')):
            show_warning(self, "Invalid File Type", 
                              "Please select a valid image file (PNG, ICO, SVG, JPG).")
            return
        
        # Show confirmation
        variant_name = "Light" if variant == 'light' else "Dark"
        confirmation_text = f"Replace the {variant_name.lower()} theme icon for '{self.icon_data[icon_key]['display_name']}' with the selected file?"
        detailed_text = f"File: {file_path}"
        
        if MessageBoxFactory.question(
            self, "Replace Icon", confirmation_text, detailed_text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            self.replace_icon_file_variant(icon_key, file_path, variant)
    
    def browse_for_icon_variant(self, variant):
        """Browse for icon file for specific light/dark variant"""
        current_item = self.icon_tree.currentItem()
        if not current_item or not current_item.data(Qt.ItemDataRole.UserRole):
            return
        
        icon_key = current_item.data(Qt.ItemDataRole.UserRole)
        
        file_dialog = QFileDialog(self)
        file_dialog.setWindowTitle(f"Select {variant.title()} Theme Icon")
        file_dialog.setFileMode(QFileDialog.FileMode.ExistingFile)
        file_dialog.setNameFilter("Image files (*.png *.ico *.svg *.jpg *.jpeg)")
        
        if file_dialog.exec() == QFileDialog.DialogCode.Accepted:
            selected_files = file_dialog.selectedFiles()
            if selected_files:
                self.replace_icon_file_variant(icon_key, selected_files[0], variant)
    
    def browse_for_icon(self):
        """Browse for icon file (legacy compatibility - defaults to light variant)"""
        self.browse_for_icon_variant('light')
    
    def replace_icon_file(self, icon_key, new_file_path):
        """Replace an icon file with a new one"""
        try:
            from .icon_manager import get_icon_manager
            import shutil
            import os
            
            icon_manager = get_icon_manager()
            if not icon_manager:
                show_warning(self, "Error", "Icon manager not available.")
                return
            
            # Get current icon configuration
            icon_config = icon_manager.ICON_MAP.get(icon_key)
            if not icon_config:
                show_warning(self, "Error", f"Unknown icon key: {icon_key}")
                return
            
            # Determine target filename
            if isinstance(icon_config, str):
                target_filename = icon_config
            elif isinstance(icon_config, list) and len(icon_config) > 0:
                target_filename = icon_config[0]  # Replace light version for now
            else:
                show_warning(self, "Error", "Invalid icon configuration.")
                return
            
            target_path = os.path.join(icon_manager.assets_dir, target_filename)
            
            # Create backup if original exists
            if os.path.exists(target_path):
                backup_path = target_path + ".backup"
                shutil.copy2(target_path, backup_path)
            
            # Copy new file
            shutil.copy2(new_file_path, target_path)
            
            # Clear icon cache to force reload
            icon_manager.refresh_cache()
            
            # Update preview and refresh main window icons
            self.update_selected_icon_preview(icon_key)
            
            # Refresh main window if it exists
            if self.parent_window and hasattr(self.parent_window, 'refresh_icons'):
                self.parent_window.refresh_icons()
            
            # Don't mark tab as dirty - icon changes are saved immediately
            
            show_info(self, "Icon Updated", 
                                  f"Icon '{self.icon_data[icon_key]['display_name']}' has been updated successfully.")
            
        except Exception as e:
            show_error(self, "Error", f"Failed to replace icon: {str(e)}")
    
    def replace_icon_file_variant(self, icon_key, new_file_path, variant):
        """Replace an icon file for a specific light/dark variant"""
        try:
            from .icon_manager import get_icon_manager
            import shutil
            import os
            
            icon_manager = get_icon_manager()
            if not icon_manager:
                show_warning(self, "Error", "Icon manager not available.")
                return
            
            # Get current icon configuration
            icon_config = icon_manager.ICON_MAP.get(icon_key)
            if not icon_config:
                show_warning(self, "Error", f"Unknown icon key: {icon_key}")
                return
            
            # Determine target filename based on variant and current config
            if isinstance(icon_config, str):
                # Single icon - create dark variant filename when needed
                if variant == 'light':
                    target_filename = icon_config
                else:  # dark variant
                    # Create dark variant filename (add -dark before extension)
                    base, ext = os.path.splitext(icon_config)
                    target_filename = f"{base}-dark{ext}"
                    
                    # Always convert to light/dark pair for consistency
                    new_config = [icon_config, target_filename]
                    icon_manager.ICON_MAP[icon_key] = new_config
            elif isinstance(icon_config, list) and len(icon_config) >= 2:
                # Icon pair - choose based on variant
                if variant == 'light':
                    target_filename = icon_config[0]
                else:  # dark
                    target_filename = icon_config[1]
            elif isinstance(icon_config, list) and len(icon_config) == 1:
                # Single item list - treat as single icon
                target_filename = icon_config[0]
            else:
                show_warning(self, "Error", "Invalid icon configuration.")
                return
            
            target_path = os.path.join(icon_manager.assets_dir, target_filename)
            
            # Create backup if original exists
            if os.path.exists(target_path):
                backup_path = target_path + ".backup"
                shutil.copy2(target_path, backup_path)
            
            # Copy new file
            shutil.copy2(new_file_path, target_path)
            
            # Clear icon cache to force reload
            icon_manager.refresh_cache()
            
            # Update both previews and refresh main window icons
            self.update_icon_previews_dual(icon_key)
            
            # Refresh main window if it exists
            if self.parent_window and hasattr(self.parent_window, 'refresh_icons'):
                self.parent_window.refresh_icons()
            
            # Don't mark tab as dirty - icon changes are saved immediately
            
            variant_name = f"{variant.title()} theme"
            icon_name = self.icon_data[icon_key]['display_name']
            show_info(self, "Icon Updated", 
                                  f"{variant_name} icon for '{icon_name}' has been updated successfully.")
            
        except Exception as e:
            show_error(self, "Error", f"Failed to replace {variant} icon: {str(e)}")
    
    def reset_icon_variant(self, variant):
        """Reset a specific light/dark icon variant to default"""
        current_item = self.icon_tree.currentItem()
        if not current_item or not current_item.data(Qt.ItemDataRole.UserRole):
            return
        
        icon_key = current_item.data(Qt.ItemDataRole.UserRole)
        icon_name = self.icon_data[icon_key]['display_name']
        variant_name = f"{variant.title()} theme"
        
        question_text = f"Reset the {variant_name.lower()} icon for '{icon_name}' to default?"
        
        if MessageBoxFactory.question(
            self, "Reset Icon Variant", question_text,
            buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            self.restore_default_icon_variant(icon_key, variant)
    
    def restore_default_icon_variant(self, icon_key, variant):
        """Restore a specific light/dark icon variant to its default state"""
        try:
            from .icon_manager import get_icon_manager
            import os
            
            icon_manager = get_icon_manager()
            if not icon_manager:
                return
            
            # Get current icon configuration
            icon_config = icon_manager.ICON_MAP.get(icon_key)
            if not icon_config:
                return
            
            # Determine target filename based on variant
            if isinstance(icon_config, str):
                # Single icon - reset applies to the single file
                target_filename = icon_config
            elif isinstance(icon_config, list):
                if variant == 'light' and len(icon_config) > 0:
                    target_filename = icon_config[0]
                elif variant == 'dark' and len(icon_config) > 1:
                    target_filename = icon_config[1]
                else:
                    show_info(self, "No Reset Needed", 
                                          f"No {variant} variant defined for this icon.")
                    return
            else:
                return
            
            target_path = os.path.join(icon_manager.assets_dir, target_filename)
            backup_path = target_path + ".backup"
            
            restored = False
            if os.path.exists(backup_path):
                # Restore from backup
                import shutil
                shutil.move(backup_path, target_path)
                restored = True
            else:
                # No backup available - cannot reset to original
                show_warning(self, "Cannot Reset", 
                                  f"No backup available for this icon. Original file was not backed up.\n\n"
                                  f"To reset, you'll need to manually restore the original {target_filename} file.")
                return
            
            if restored:
                # Clear icon cache to force reload
                icon_manager.refresh_cache()
                
                # Update both previews and refresh main window icons
                self.update_icon_previews_dual(icon_key)
                
                # Refresh main window if it exists
                if self.parent_window and hasattr(self.parent_window, 'refresh_icons'):
                    self.parent_window.refresh_icons()
                
                # Don't mark tab as dirty - reset is an immediate filesystem operation
                
                icon_name = self.icon_data[icon_key]['display_name']
                variant_name = f"{variant.title()} theme"
                show_info(self, "Icon Reset", 
                                      f"{variant_name} icon for '{icon_name}' has been reset to default.")
            else:
                show_info(self, "No Changes", 
                                      f"No custom {variant} icon found to reset.")
            
        except Exception as e:
            show_error(self, "Error", f"Failed to reset {variant} icon: {str(e)}")
    
    def reset_selected_icon(self):
        """Reset selected icon to default"""
        current_item = self.icon_tree.currentItem()
        if not current_item or not current_item.data(Qt.ItemDataRole.UserRole):
            return
        
        icon_key = current_item.data(Qt.ItemDataRole.UserRole)
        
        question_text = f"Reset the icon for '{self.icon_data[icon_key]['display_name']}' to default?"
        
        if MessageBoxFactory.question(
            self, "Reset Icon", question_text,
            buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            self.restore_default_icon(icon_key)
    
    def restore_default_icon(self, icon_key):
        """Restore an icon to its default state"""
        try:
            from .icon_manager import get_icon_manager
            import os
            
            icon_manager = get_icon_manager()
            if not icon_manager:
                return
            
            # Get current icon configuration
            icon_config = icon_manager.ICON_MAP.get(icon_key)
            if not icon_config:
                return
            
            # Determine target filename(s)
            filenames = []
            if isinstance(icon_config, str):
                filenames = [icon_config]
            elif isinstance(icon_config, list):
                filenames = icon_config
            
            # Restore from backup if available
            restored = False
            for filename in filenames:
                target_path = os.path.join(icon_manager.assets_dir, filename)
                backup_path = target_path + ".backup"
                
                if os.path.exists(backup_path):
                    os.rename(backup_path, target_path)
                    restored = True
                elif os.path.exists(target_path):
                    # If no backup, just remove custom file to use fallback
                    os.remove(target_path)
                    restored = True
            
            if restored:
                # Clear icon cache to force reload
                icon_manager.refresh_cache()
                
                # Update preview
                self.update_selected_icon_preview(icon_key)
                
                # Mark tab as dirty
                self.mark_tab_dirty(4)  # Icons tab
                
                show_info(self, "Icon Reset", 
                                      f"Icon '{self.icon_data[icon_key]['display_name']}' has been reset to default.")
            else:
                show_info(self, "No Changes", 
                                      "No custom icon found to reset.")
            
        except Exception as e:
            show_error(self, "Error", f"Failed to reset icon: {str(e)}")
    
    def reset_all_icons(self):
        """Reset all icons to defaults"""
        if MessageBoxFactory.question(
            self, "Reset All Icons", "Reset ALL icons to their default state?",
            detailed_text="This will remove all custom icon files and restore defaults.",
            buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            default_button=QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            try:
                from .icon_manager import get_icon_manager
                
                icon_manager = get_icon_manager()
                if not icon_manager:
                    return
                
                reset_count = 0
                for icon_key in icon_manager.ICON_MAP.keys():
                    try:
                        self.restore_default_icon(icon_key)
                        reset_count += 1
                    except Exception as e:
                        log(f"Failed to reset {icon_key}: {e}", level="warning", category="ui")
                
                # Update current preview if any
                current_item = self.icon_tree.currentItem()
                if current_item and current_item.data(Qt.ItemDataRole.UserRole):
                    icon_key = current_item.data(Qt.ItemDataRole.UserRole)
                    self.update_selected_icon_preview(icon_key)
                
                show_info(self, "Reset Complete", 
                                      f"Reset {reset_count} icons to default state.")
                
            except Exception as e:
                show_error(self, "Error", f"Failed to reset icons: {str(e)}")
    
    def validate_all_icons(self):
        """Validate all icon files and show report"""
        try:
            from .icon_manager import get_icon_manager
            
            icon_manager = get_icon_manager()
            if not icon_manager:
                show_warning(self, "Error", "Icon manager not available.")
                return
            
            # Run validation
            result = icon_manager.validate_icons(report=False)
            
            # Show results in a dialog
            dialog = QDialog(self)
            dialog.setWindowTitle("Icon Validation Report")
            dialog.resize(500, 400)
            
            layout = QVBoxLayout(dialog)
            
            # Summary
            summary_label = QLabel(f"Total icons: {len(icon_manager.ICON_MAP)}\n"
                                 f"Found: {len(result['found'])}\n"
                                 f"Missing: {len(result['missing'])}")
            summary_label.setStyleSheet("font-weight: bold; padding: 10px;")
            layout.addWidget(summary_label)
            
            # Details
            details = QPlainTextEdit()
            details.setReadOnly(True)
            
            if result['found']:
                details.appendPlainText("=== FOUND ICONS ===")
                for item in result['found']:
                    details.appendPlainText(f"✓ {item}")
                details.appendPlainText("")
            
            if result['missing']:
                details.appendPlainText("=== MISSING ICONS ===")
                for item in result['missing']:
                    details.appendPlainText(f"✗ {item}")
            
            layout.addWidget(details)
            
            # Close button
            close_btn = QPushButton("Close")
            close_btn.clicked.connect(dialog.accept)
            layout.addWidget(close_btn)
            
            dialog.exec()
            
        except Exception as e:
            show_error(self, "Error", f"Failed to validate icons: {str(e)}")


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
            from src.utils.logging import get_logger as _get_logger
            self._logger: Any = _get_logger()
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
        grid.addWidget(QLabel("<span style='font-weight: 600'>Backups to keep</span>:"), 1, 2)
        grid.addWidget(self.spn_backup, 1, 3)

        self.chk_compress = QCheckBox("Compress rotated logs (.gz)")
        self.chk_compress.setChecked(bool(settings.get('compress', True)))
        grid.addWidget(self.chk_compress, 2, 0, 1, 2)

        self.spn_max_bytes = QSpinBox()
        self.spn_max_bytes.setRange(1024, 1024 * 1024 * 1024)
        self.spn_max_bytes.setSingleStep(1024 * 1024)
        self.spn_max_bytes.setValue(int(settings.get('max_bytes', 10485760)))
        grid.addWidget(QLabel("<span style='font-weight: 600'>Max size (bytes, size mode)</span>:"), 2, 2)
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

        # Add the settings to the layout
        layout.addWidget(header)
        
        # Add log content viewer
        log_group = QGroupBox("Log Content")
        log_layout = QVBoxLayout(log_group)
        
        # Log text area
        self.log_text = QPlainTextEdit()
        self.log_text.setPlainText(initial_text)
        self.log_text.setReadOnly(True)
        log_layout.addWidget(self.log_text)
        
        # Follow checkbox
        self.follow_check = QCheckBox("Follow log updates")
        self.follow_check.setChecked(True)
        log_layout.addWidget(self.follow_check)
        
        layout.addWidget(log_group)
        
        # Connect signals
        self.btn_apply.clicked.connect(self.apply_settings)
        self.btn_open_dir.clicked.connect(self.open_logs_folder)
        
    def apply_settings(self):
        """Apply log settings"""
        # Implementation would go here
        pass
        
    def open_logs_folder(self):
        """Open the logs folder"""
        # Implementation would go here
        pass
