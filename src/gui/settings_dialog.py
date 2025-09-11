#!/usr/bin/env python3
"""
Settings management module for imxup GUI
Contains all settings-related dialogs and configuration management
"""

import os
import sys
import configparser
import subprocess
from typing import List, Dict, Any, Optional

from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout,
    QTabWidget, QPushButton, QCheckBox, QComboBox, QSpinBox,
    QLabel, QGroupBox, QLineEdit, QMessageBox, QFileDialog,
    QListWidget, QListWidgetItem, QPlainTextEdit, QInputDialog,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QButtonGroup, QFrame, QSplitter, QRadioButton, QApplication
)
from PyQt6.QtCore import Qt, QSettings, pyqtSignal
from PyQt6.QtGui import QIcon, QFont, QColor, QTextCharFormat, QPixmap, QPainter, QPen, QDragEnterEvent, QDropEvent
from PyQt6.QtGui import QSyntaxHighlighter

# Import local modules
from imxup import load_user_defaults, get_config_path, encrypt_password, decrypt_password
from src.gui.dialogs.message_factory import MessageBoxFactory, show_info, show_error, show_warning


class IconDropFrame(QFrame):
    """Drop-enabled frame for icon files"""
    
    icon_dropped = pyqtSignal(str)  # Emits file path when icon is dropped
    
    def __init__(self, variant_type):
        super().__init__()
        self.variant_type = variant_type
        self.setAcceptDrops(True)
        
    def dragEnterEvent(self, event: QDragEnterEvent):
        """Handle drag enter event"""
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if len(urls) == 1:
                file_path = urls[0].toLocalFile()
                if file_path.lower().endswith(('.png', '.ico', '.svg', '.jpg', '.jpeg')):
                    event.acceptProposedAction()
                    return
        event.ignore()
        
    def dropEvent(self, event: QDropEvent):
        """Handle drop event"""
        urls = event.mimeData().urls()
        if len(urls) == 1:
            file_path = urls[0].toLocalFile()
            if file_path.lower().endswith(('.png', '.ico', '.svg', '.jpg', '.jpeg')):
                self.icon_dropped.emit(file_path)
                event.acceptProposedAction()
                return
        event.ignore()


class ComprehensiveSettingsDialog(QDialog):
    """Comprehensive settings dialog with tabbed interface"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        
        # Track dirty state per tab
        self.tab_dirty_states = {}
        self.current_tab_index = 0
        
        self.setup_ui()
        self.load_settings()
        
        # Connect tab change signal to check for unsaved changes
        self.tab_widget.currentChanged.connect(self.on_tab_changed)
        
    def setup_ui(self):
        """Setup the tabbed settings interface"""
        self.setWindowTitle("Settings & Preferences")
        self.setModal(True)
        self.resize(800, 600)
        
        layout = QVBoxLayout(self)
        
        # Create tab widget
        self.tab_widget = QTabWidget()
        self.tab_widget.currentChanged.connect(self.on_tab_changed)
        layout.addWidget(self.tab_widget)
        
        # Create tabs
        self.setup_general_tab()
        self.setup_credentials_tab()
        self.setup_templates_tab()
        self.setup_tabs_tab()
        self.setup_icons_tab()
        self.setup_logs_tab()
        self.setup_scanning_tab()
        
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
        upload_group = QGroupBox("Upload Settings")
        upload_layout = QGridLayout(upload_group)
        
        # Thumbnail size
        upload_layout.addWidget(QLabel("Thumbnail Size:"), 0, 0)
        self.thumbnail_size_combo = QComboBox()
        self.thumbnail_size_combo.addItems([
            "100x100", "180x180", "250x250", "300x300", "150x150"
        ])
        self.thumbnail_size_combo.setCurrentIndex(defaults.get('thumbnail_size', 3) - 1)
        upload_layout.addWidget(self.thumbnail_size_combo, 0, 1)
        
        # Thumbnail format
        upload_layout.addWidget(QLabel("Thumbnail Format:"), 1, 0)
        self.thumbnail_format_combo = QComboBox()
        self.thumbnail_format_combo.addItems([
            "Fixed width", "Proportional", "Square", "Fixed height"
        ])
        self.thumbnail_format_combo.setCurrentIndex(defaults.get('thumbnail_format', 2) - 1)
        upload_layout.addWidget(self.thumbnail_format_combo, 1, 1)
        
        # Max retries
        upload_layout.addWidget(QLabel("Max Retries:"), 2, 0)
        self.max_retries_spin = QSpinBox()
        self.max_retries_spin.setRange(1, 10)
        self.max_retries_spin.setValue(defaults.get('max_retries', 3))
        upload_layout.addWidget(self.max_retries_spin, 2, 1)
        
        # Concurrent uploads
        upload_layout.addWidget(QLabel("Concurrent Uploads:"), 3, 0)
        self.batch_size_spin = QSpinBox()
        self.batch_size_spin.setRange(1, 25)
        self.batch_size_spin.setValue(defaults.get('parallel_batch_size', 4))
        self.batch_size_spin.setToolTip("Number of images to upload simultaneously. Higher values = faster uploads but more server load.")
        upload_layout.addWidget(self.batch_size_spin, 3, 1)
        
        # Upload timeouts
        upload_layout.addWidget(QLabel("Connect Timeout (s):"), 4, 0)
        self.connect_timeout_spin = QSpinBox()
        self.connect_timeout_spin.setRange(5, 300)
        self.connect_timeout_spin.setValue(defaults.get('upload_connect_timeout', 30))
        self.connect_timeout_spin.setToolTip("Maximum time to wait for server connection. Increase if you have slow internet.")
        upload_layout.addWidget(self.connect_timeout_spin, 4, 1)
        
        upload_layout.addWidget(QLabel("Read Timeout (s):"), 5, 0)
        self.read_timeout_spin = QSpinBox()
        self.read_timeout_spin.setRange(10, 600)
        self.read_timeout_spin.setValue(defaults.get('upload_read_timeout', 120))
        self.read_timeout_spin.setToolTip("Maximum time to wait for server response. Increase for large images or slow servers.")
        upload_layout.addWidget(self.read_timeout_spin, 5, 1)
        
        # General settings group
        general_group = QGroupBox("General Settings")
        general_layout = QGridLayout(general_group)
        
        # Confirm delete
        self.confirm_delete_check = QCheckBox("Confirm before deleting")
        self.confirm_delete_check.setChecked(defaults.get('confirm_delete', True))
        general_layout.addWidget(self.confirm_delete_check, 0, 0)
        
        # Auto-rename
        self.auto_rename_check = QCheckBox("Auto-rename galleries")
        self.auto_rename_check.setChecked(defaults.get('auto_rename', True))
        general_layout.addWidget(self.auto_rename_check, 0, 1)
        
        # Storage options group
        storage_group = QGroupBox("Storage Options")
        storage_layout = QGridLayout(storage_group)
        
        # Store in uploaded folder
        self.store_in_uploaded_check = QCheckBox("Save artifacts in .uploaded folder")
        self.store_in_uploaded_check.setChecked(defaults.get('store_in_uploaded', True))
        storage_layout.addWidget(self.store_in_uploaded_check, 0, 0, 1, 3)
        
        # Store in central location
        self.store_in_central_check = QCheckBox("Save artifacts in central store")
        self.store_in_central_check.setChecked(defaults.get('store_in_central', True))
        storage_layout.addWidget(self.store_in_central_check, 1, 0, 1, 3)
        
        # Data location section
        location_label = QLabel("Data location:")
        storage_layout.addWidget(location_label, 2, 0, 1, 3)
        
        # Import path functions
        from imxup import get_central_store_base_path, get_default_central_store_base_path
        
        # Get current path and determine mode
        current_path = defaults.get('central_store_path') or get_central_store_base_path()
        home_path = get_default_central_store_base_path()
        app_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        portable_path = os.path.join(app_root, '.imxup')
        
        # Radio buttons for location selection
        self.home_radio = QRadioButton(f"Home folder: {home_path}")
        self.portable_radio = QRadioButton(f"Portable install: {portable_path}")
        self.custom_radio = QRadioButton("Custom location:")
        
        # Determine which radio to check based on current path
        storage_mode = defaults.get('storage_mode', 'home')
        if storage_mode == 'portable':
            self.portable_radio.setChecked(True)
        elif storage_mode == 'custom':
            self.custom_radio.setChecked(True)
        else:
            self.home_radio.setChecked(True)
        
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
        
        # Theme & Display group
        theme_group = QGroupBox("Theme and Display")
        theme_layout = QGridLayout(theme_group)
        
        # Theme setting
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["system", "light", "dark"])
        
        # Load current theme from QSettings
        if self.parent and hasattr(self.parent, 'settings'):
            current_theme = self.parent.settings.value('ui/theme', 'system')
            index = self.theme_combo.findText(current_theme)
            if index >= 0:
                self.theme_combo.setCurrentIndex(index)
        
        # Add theme controls
        theme_label = QLabel("Theme mode:")
        theme_layout.addWidget(theme_label, 0, 0)
        theme_layout.addWidget(self.theme_combo, 0, 1)
        
        # Font size setting
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(6, 24)  # Reasonable range for UI fonts
        self.font_size_spin.setSuffix(" pt")
        self.font_size_spin.setToolTip("Base font size for the interface (affects table, labels, buttons)")
        
        # Load current font size from QSettings (default to 9pt)
        if self.parent and hasattr(self.parent, 'settings'):
            current_font_size = int(self.parent.settings.value('ui/font_size', 9))
            self.font_size_spin.setValue(current_font_size)
        else:
            self.font_size_spin.setValue(9)
        
        # Add font size controls
        font_label = QLabel("Font size:")
        theme_layout.addWidget(font_label, 1, 0)
        theme_layout.addWidget(self.font_size_spin, 1, 1)
        
        # Set column stretch for 50/50 split
        theme_layout.setColumnStretch(0, 1)  # Label column 50%
        theme_layout.setColumnStretch(1, 1)  # Control column 50%
        
        # Add all groups to layout in 2x2 grid with 40/60 split
        grid_layout = QGridLayout()
        grid_layout.addWidget(upload_group, 0, 0)      # Top left
        grid_layout.addWidget(general_group, 0, 1)     # Top right
        grid_layout.addWidget(theme_group, 1, 0)       # Bottom left
        grid_layout.addWidget(storage_group, 1, 1)     # Bottom right
        
        # Set column stretch factors for 40/60 split
        grid_layout.setColumnStretch(0, 40)  # Left column gets 40%
        grid_layout.setColumnStretch(1, 60)  # Right column gets 60%
        
        layout.addLayout(grid_layout)
        layout.addStretch()
        
        # Connect change signals to mark tab as dirty
        self.thumbnail_size_combo.currentIndexChanged.connect(lambda: self.mark_tab_dirty(0))
        self.thumbnail_format_combo.currentIndexChanged.connect(lambda: self.mark_tab_dirty(0))
        self.max_retries_spin.valueChanged.connect(lambda: self.mark_tab_dirty(0))
        self.batch_size_spin.valueChanged.connect(lambda: self.mark_tab_dirty(0))
        self.connect_timeout_spin.valueChanged.connect(lambda: self.mark_tab_dirty(0))
        self.read_timeout_spin.valueChanged.connect(lambda: self.mark_tab_dirty(0))
        self.confirm_delete_check.toggled.connect(lambda: self.mark_tab_dirty(0))
        self.auto_rename_check.toggled.connect(lambda: self.mark_tab_dirty(0))
        self.store_in_uploaded_check.toggled.connect(lambda: self.mark_tab_dirty(0))
        self.store_in_central_check.toggled.connect(lambda: self.mark_tab_dirty(0))
        self.home_radio.toggled.connect(lambda: self.mark_tab_dirty(0))
        self.portable_radio.toggled.connect(lambda: self.mark_tab_dirty(0))
        self.custom_radio.toggled.connect(lambda: self.mark_tab_dirty(0))
        self.path_edit.textChanged.connect(lambda: self.mark_tab_dirty(0))
        self.theme_combo.currentIndexChanged.connect(lambda: self.mark_tab_dirty(0))
        self.font_size_spin.valueChanged.connect(lambda: self.mark_tab_dirty(0))
        
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
        layout = QVBoxLayout(tabs_widget)
        
        # Initialize tab manager reference
        self.tab_manager = None
        if self.parent and hasattr(self.parent, 'tab_manager'):
            self.tab_manager = self.parent.tab_manager
        
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
        
        # Right side - Auto-archive settings
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        
        # Auto-archive group
        auto_archive_group = QGroupBox("Auto-Archive Settings")
        auto_archive_layout = QVBoxLayout(auto_archive_group)
        
        # Enable auto-archive
        self.auto_archive_enabled_check = QCheckBox("Enable automatic archiving")
        self.auto_archive_enabled_check.toggled.connect(self.on_auto_archive_enabled_changed)
        auto_archive_layout.addWidget(self.auto_archive_enabled_check)
        
        # Auto-archive configuration
        config_frame = QFrame()
        config_layout = QGridLayout(config_frame)
        
        # Days threshold
        config_layout.addWidget(QLabel("Archive completed galleries after:"), 0, 0)
        self.auto_archive_days_spin = QSpinBox()
        self.auto_archive_days_spin.setRange(1, 365)
        self.auto_archive_days_spin.setValue(30)
        self.auto_archive_days_spin.setSuffix(" days")
        self.auto_archive_days_spin.valueChanged.connect(self.on_auto_archive_days_changed)
        config_layout.addWidget(self.auto_archive_days_spin, 0, 1)
        
        # Status criteria
        config_layout.addWidget(QLabel("Archive galleries with status:"), 1, 0, 1, 2)
        
        self.archive_completed_check = QCheckBox("Completed")
        self.archive_completed_check.setChecked(True)
        self.archive_completed_check.toggled.connect(self.on_auto_archive_criteria_changed)
        config_layout.addWidget(self.archive_completed_check, 2, 0)
        
        self.archive_failed_check = QCheckBox("Failed")
        self.archive_failed_check.setChecked(True)
        self.archive_failed_check.toggled.connect(self.on_auto_archive_criteria_changed)
        config_layout.addWidget(self.archive_failed_check, 2, 1)
        
        self.archive_cancelled_check = QCheckBox("Cancelled")
        self.archive_cancelled_check.toggled.connect(self.on_auto_archive_criteria_changed)
        config_layout.addWidget(self.archive_cancelled_check, 3, 0)
        
        auto_archive_layout.addWidget(config_frame)
        
        # Manual archive actions
        manual_frame = QFrame()
        manual_layout = QVBoxLayout(manual_frame)
        
        # Preview candidates
        self.preview_archive_btn = QPushButton("Preview Archive Candidates")
        self.preview_archive_btn.clicked.connect(self.preview_archive_candidates)
        manual_layout.addWidget(self.preview_archive_btn)
        
        # Execute archive
        self.execute_archive_btn = QPushButton("Archive Now")
        self.execute_archive_btn.clicked.connect(self.execute_archive_now)
        manual_layout.addWidget(self.execute_archive_btn)
        
        auto_archive_layout.addWidget(manual_frame)
        
        # Archive status
        self.archive_status_label = QLabel("Auto-archive is disabled")
        self.archive_status_label.setStyleSheet("color: #666; font-style: italic;")
        auto_archive_layout.addWidget(self.archive_status_label)
        
        right_layout.addWidget(auto_archive_group)
        right_layout.addStretch()
        
        # Add to splitter
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setSizes([400, 300])  # Give more space to left side
        
        # Load current tabs and settings
        self.load_tabs_settings()
        
        self.tab_widget.addTab(tabs_widget, "Tabs")
    
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
            
            # Load auto-archive settings
            enabled, days, statuses = self.tab_manager.get_auto_archive_config()
            self.auto_archive_enabled_check.setChecked(enabled)
            self.auto_archive_days_spin.setValue(days)
            
            # Update status checkboxes
            self.archive_completed_check.setChecked("completed" in statuses)
            self.archive_failed_check.setChecked("failed" in statuses)
            self.archive_cancelled_check.setChecked("cancelled" in statuses)
            
            self._update_auto_archive_status()
            
        except Exception as e:
            print(f"Error loading tabs settings: {e}")
            self._disable_tab_controls()
    
    def _disable_tab_controls(self):
        """Disable all tab management controls"""
        controls = [
            self.create_tab_btn, self.rename_tab_btn, self.delete_tab_btn,
            self.move_tab_up_btn, self.move_tab_down_btn, self.hide_tab_check,
            self.reset_order_btn, self.auto_archive_enabled_check,
            self.preview_archive_btn, self.execute_archive_btn
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
        can_delete = is_user_tab and tab_info.name not in ['Main', 'Archive']
        
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
        
        # Don't allow deleting Main or Archive
        if tab_info.name in ['Main', 'Archive']:
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
    
    def on_auto_archive_enabled_changed(self, enabled):
        """Handle auto-archive enabled state change"""
        if self.tab_manager:
            self.tab_manager.auto_archive_enabled = enabled
            self._update_auto_archive_status()
    
    def on_auto_archive_days_changed(self, days):
        """Handle auto-archive days threshold change"""
        if self.tab_manager:
            self.tab_manager.auto_archive_days = days
            self._update_auto_archive_status()
    
    def on_auto_archive_criteria_changed(self):
        """Handle auto-archive criteria change"""
        if not self.tab_manager:
            return
        
        # Get current settings
        enabled, days, _ = self.tab_manager.get_auto_archive_config()
        
        # Build new status set
        statuses = set()
        if self.archive_completed_check.isChecked():
            statuses.add("completed")
        if self.archive_failed_check.isChecked():
            statuses.add("failed")
        if self.archive_cancelled_check.isChecked():
            statuses.add("cancelled")
        
        # Update configuration
        self.tab_manager.set_auto_archive_config(enabled, days, statuses)
        self._update_auto_archive_status()
    
    def _update_auto_archive_status(self):
        """Update auto-archive status display"""
        if not self.tab_manager:
            self.archive_status_label.setText("Tab management not available")
            return
        
        enabled, days, statuses = self.tab_manager.get_auto_archive_config()
        
        if enabled:
            status_list = ", ".join(sorted(statuses)) if statuses else "none"
            self.archive_status_label.setText(
                f"Auto-archive enabled: {days} days, statuses: {status_list}"
            )
            self.archive_status_label.setStyleSheet("color: #27ae60; font-weight: bold;")
            
            # Enable manual actions
            self.preview_archive_btn.setEnabled(True)
            self.execute_archive_btn.setEnabled(True)
        else:
            self.archive_status_label.setText("Auto-archive is disabled")
            self.archive_status_label.setStyleSheet("color: #666; font-style: italic;")
            
            # Disable manual actions
            self.preview_archive_btn.setEnabled(False)
            self.execute_archive_btn.setEnabled(False)
    
    def preview_archive_candidates(self):
        """Preview galleries that would be auto-archived"""
        if not self.tab_manager:
            return
        
        try:
            candidates = self.tab_manager.check_auto_archive_candidates()
            
            if not candidates:
                msg_box = QMessageBox(self)
                msg_box.setWindowTitle("Preview Results")
                msg_box.setText("No galleries meet the auto-archive criteria.")
                msg_box.open()
                return
            
            # Show preview dialog
            preview_text = f"Found {len(candidates)} galleries that would be archived:\n\n"
            preview_text += "\n".join(f"• {path}" for path in candidates[:20])
            if len(candidates) > 20:
                preview_text += f"\n... and {len(candidates) - 20} more"
            
            MessageBoxFactory.information(
                self, "Archive Preview", preview_text, 
                detailed_text="\n".join(candidates)
            )
            
        except Exception as e:
            show_error(self, "Error", f"Failed to preview archive candidates: {e}")
    
    def execute_archive_now(self):
        """Execute auto-archive operation immediately"""
        if not self.tab_manager:
            return
        
        # Confirm execution
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Icon.Question)
        msg_box.setWindowTitle("Execute Auto-Archive")
        msg_box.setText("Execute auto-archive operation now?\n\n"
                       "This will move qualifying galleries to the Archive tab.")
        msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg_box.setDefaultButton(QMessageBox.StandardButton.No)
        
        # Use non-blocking approach
        msg_box.finished.connect(self._handle_execute_archive_confirmation)
        msg_box.open()
    
    def _handle_execute_archive_confirmation(self, result):
        """Handle execute archive confirmation"""
        if result != QMessageBox.StandardButton.Yes:
            return
        
        try:
            moved_count = self.tab_manager.execute_auto_archive()
            
            # Refresh tabs display
            self.load_tabs_settings()
            
            # Show result message
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Archive Complete")
            if moved_count > 0:
                msg_box.setText(f"Successfully archived {moved_count} galleries to Archive tab.")
            else:
                msg_box.setText("No galleries met the auto-archive criteria.")
            msg_box.open()
            
        except Exception as e:
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Icon.Warning)
            msg_box.setWindowTitle("Error")
            msg_box.setText(f"Failed to execute auto-archive: {e}")
            msg_box.open()
        
    def setup_logs_tab(self):
        """Setup the Logs tab with integrated log viewer"""
        logs_widget = QWidget()
        layout = QVBoxLayout(logs_widget)
        
        # Create and integrate the log viewer dialog
        try:
            # Get initial log text
            from src.utils.logging import get_logger
            initial_text = get_logger().read_current_log(tail_bytes=2 * 1024 * 1024) or ""
        except Exception:
            initial_text = ""
        
        self.log_dialog = LogViewerDialog(initial_text, self)
        self.log_dialog.setParent(logs_widget)
        self.log_dialog.setWindowFlags(Qt.WindowType.Widget)  # Make it a child widget
        self.log_dialog.setModal(False)  # Not modal when embedded
        
        # Add the log dialog to the layout
        layout.addWidget(self.log_dialog)
        
        self.tab_widget.addTab(logs_widget, "Logs")
        
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
        
        # PIL sampling
        self.pil_sampling_label = QLabel("PIL sampling for min/max calculations:")
        strategy_layout.addWidget(self.pil_sampling_label)
        
        self.pil_sampling_combo = QComboBox()
        self.pil_sampling_combo.addItems([
            "1 image (first only)",
            "2 images (first + last)",
            "4 images (first + 2 middle + last)",
            "8 images (strategic sampling)",
            "16 images (extended sampling)",
            "All images (full PIL scan)"
        ])
        self.pil_sampling_combo.setCurrentIndex(2)  # Default to 4 images
        strategy_layout.addWidget(self.pil_sampling_combo)
        
        # Performance info
        perf_info = QLabel("Fast mode uses imghdr for corruption detection and PIL only on sampled images for dimension calculations.")
        perf_info.setWordWrap(True)
        perf_info.setStyleSheet("color: #666; font-style: italic;")
        strategy_layout.addWidget(perf_info)
        
        layout.addWidget(strategy_group)
        layout.addStretch()
        
        # Connect change signals to mark tab as dirty (tab index 5 for scanning)
        self.fast_scan_check.toggled.connect(lambda: self.mark_tab_dirty(5))
        self.pil_sampling_combo.currentIndexChanged.connect(lambda: self.mark_tab_dirty(5))
        
        self.tab_widget.addTab(scanning_widget, "Image Scanning")
    
    def setup_icons_tab(self):
        """Setup the Icon Manager tab with improved side-by-side light/dark preview"""
        icons_widget = QWidget()
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
        
        self.tab_widget.addTab(icons_widget, "Icon Manager")
        
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
        dialog.directorySelected.connect(self._handle_directory_selected)
        dialog.open()
    
    def _handle_directory_selected(self, directory):
        """Handle selected directory"""
        if directory:
            self.custom_radio.setChecked(True)
            self.path_edit.setText(directory)
            self.mark_tab_dirty(0)
            

            
    def load_settings(self):
        """Load current settings"""
        # Settings are loaded in setup_ui for each tab
        # Load scanning settings from QSettings
        self._load_scanning_settings()
        # Load tabs settings
        self._load_tabs_settings()
    
    def _load_scanning_settings(self):
        """Load scanning settings from QSettings"""
        try:
            if self.parent and hasattr(self.parent, 'settings'):
                # Load fast scan setting
                fast_scan = self.parent.settings.value('scanning/fast_scan', True, type=bool)
                self.fast_scan_check.setChecked(fast_scan)
                
                # Load PIL sampling strategy
                sampling_index = self.parent.settings.value('scanning/pil_sampling', 2, type=int)
                if 0 <= sampling_index < self.pil_sampling_combo.count():
                    self.pil_sampling_combo.setCurrentIndex(sampling_index)
                    
        except Exception as e:
            print(f"Failed to load scanning settings: {e}")
    
    def _load_tabs_settings(self):
        """Load tabs settings if available"""
        try:
            if hasattr(self, 'load_tabs_settings'):
                self.load_tabs_settings()
        except Exception as e:
            print(f"Failed to load tabs settings: {e}")
        
    def save_settings(self):
        """Save all settings"""
        try:
            # Save to .ini file via parent
            if self.parent:
                # Update parent's settings objects for checkboxes
                self.parent.confirm_delete_check.setChecked(self.confirm_delete_check.isChecked())
                self.parent.auto_rename_check.setChecked(self.auto_rename_check.isChecked())
                self.parent.store_in_uploaded_check.setChecked(self.store_in_uploaded_check.isChecked())
                self.parent.store_in_central_check.setChecked(self.store_in_central_check.isChecked())
                
                # Update parent's settings objects for upload settings
                self.parent.thumbnail_size_combo.setCurrentIndex(self.thumbnail_size_combo.currentIndex())
                self.parent.thumbnail_format_combo.setCurrentIndex(self.thumbnail_format_combo.currentIndex())
                self.parent.max_retries_spin.setValue(self.max_retries_spin.value())
                self.parent.batch_size_spin.setValue(self.batch_size_spin.value())
                # Template selection is now handled in the Templates tab
                
                # Save via parent
                self.parent.save_upload_settings()
                
                # Save theme
                if hasattr(self.parent, 'settings'):
                    self.parent.settings.setValue('ui/theme', self.theme_combo.currentText())
                    self.parent.apply_theme(self.theme_combo.currentText())
                
                # Save font size
                if hasattr(self.parent, 'settings'):
                    font_size = self.font_size_spin.value()
                    print(f"Saving font size to settings: {font_size}")
                    self.parent.settings.setValue('ui/font_size', font_size)
                    if hasattr(self.parent, 'apply_font_size'):
                        print(f"Applying font size: {font_size}")
                        self.parent.apply_font_size(font_size)
                
                # Save scanning settings
                self._save_scanning_settings()
                
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
        """Save scanning settings to QSettings"""
        try:
            if self.parent and hasattr(self.parent, 'settings'):
                # Save fast scan setting
                self.parent.settings.setValue('scanning/fast_scan', self.fast_scan_check.isChecked())
                
                # Save PIL sampling strategy
                sampling_index = self.pil_sampling_combo.currentIndex()
                self.parent.settings.setValue('scanning/pil_sampling', sampling_index)
                
        except Exception as e:
            print(f"Failed to save scanning settings: {e}")
    
    def _save_tabs_settings(self):
        """Save tabs settings - handled by TabManager automatically"""
        # TabManager automatically persists settings through QSettings
        # No additional saving needed here as all tab operations
        # in the UI immediately update the TabManager which handles persistence
        pass
    
    def _reset_tabs_settings(self):
        """Reset tabs settings to defaults"""
        try:
            if hasattr(self, 'tab_manager') and self.tab_manager:
                # Reset auto-archive settings
                self.auto_archive_enabled_check.setChecked(False)
                self.auto_archive_days_spin.setValue(30)
                self.archive_completed_check.setChecked(True)
                self.archive_failed_check.setChecked(True)
                self.archive_cancelled_check.setChecked(False)
                
                # Reset tab order
                self.tab_manager.reset_tab_order()
                
                # Reset auto-archive configuration
                self.tab_manager.set_auto_archive_config(False, 30, {"completed", "failed"})
                
                # Set default tab to Main
                self.tab_manager.last_active_tab = "Main"
                
                # Refresh display
                self.load_tabs_settings()
        except Exception as e:
            print(f"Failed to reset tabs settings: {e}")
            
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
            self.max_retries_spin.setValue(3)  # 3 retries (default)
            self.batch_size_spin.setValue(4)  # 4 concurrent (default)
            self.connect_timeout_spin.setValue(30)  # 30 seconds (default)
            self.read_timeout_spin.setValue(120)  # 120 seconds (default)
            # Template selection is now handled in the Templates tab
            
            # Reset checkboxes
            self.confirm_delete_check.setChecked(True)
            self.auto_rename_check.setChecked(True)
            self.store_in_uploaded_check.setChecked(True)
            self.store_in_central_check.setChecked(True)
            
            # Reset theme
            self.theme_combo.setCurrentText("system")
            
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
            print(f"Applied changes for {tab_name} tab")
    
    def save_current_tab(self):
        """Save only the current tab's settings"""
        current_index = self.tab_widget.currentIndex()
        
        try:
            if current_index == 0:  # General tab
                return self._save_general_tab()
            elif current_index == 1:  # Credentials tab  
                return self._save_credentials_tab()
            elif current_index == 2:  # Templates tab
                return self._save_templates_tab()
            elif current_index == 3:  # Tabs tab
                return self._save_tabs_tab()
            elif current_index == 4:  # Logs tab
                return self._save_logs_tab()
            elif current_index == 5:  # Scanning tab
                return self._save_scanning_tab()
            elif current_index == 6:  # Icons tab
                return self._save_icons_tab()
            else:
                return True
        except Exception as e:
            print(f"Error saving tab {current_index}: {e}")
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
        elif current_index == 5:  # Scanning tab  
            self._reload_scanning_tab()
        # Other tabs don't have form controls that need reloading
    
    def _reload_general_tab(self):
        """Reload General tab form values from saved settings"""
        defaults = load_user_defaults()
        
        # Reload upload settings
        self.thumbnail_size_combo.setCurrentIndex(defaults.get('thumbnail_size', 3) - 1)
        self.thumbnail_format_combo.setCurrentIndex(defaults.get('thumbnail_format', 2) - 1)
        self.max_retries_spin.setValue(defaults.get('max_retries', 3))
        self.batch_size_spin.setValue(defaults.get('parallel_batch_size', 4))
        self.connect_timeout_spin.setValue(defaults.get('upload_connect_timeout', 30))
        self.read_timeout_spin.setValue(defaults.get('upload_read_timeout', 120))
        
        # Reload general settings
        self.confirm_delete_check.setChecked(defaults.get('confirm_delete', True))
        self.auto_rename_check.setChecked(defaults.get('auto_rename', True))
        
        # Reload storage settings
        self.store_in_uploaded_check.setChecked(defaults.get('store_in_uploaded', True))
        self.store_in_central_check.setChecked(defaults.get('store_in_central', True))
        
        from imxup import get_central_store_base_path
        current_path = defaults.get('central_store_path') or get_central_store_base_path()
        self.path_edit.setText(current_path)
        
        # Reload theme
        if self.parent and hasattr(self.parent, 'settings'):
            current_theme = self.parent.settings.value('ui/theme', 'system')
            index = self.theme_combo.findText(current_theme)
            if index >= 0:
                self.theme_combo.setCurrentIndex(index)
        
        # Reload font size
        if self.parent and hasattr(self.parent, 'settings'):
            current_font_size = int(self.parent.settings.value('ui/font_size', 9))
            self.font_size_spin.setValue(current_font_size)
    
    def _reload_scanning_tab(self):
        """Reload Scanning tab form values from saved settings"""
        # Reload scanning settings from QSettings
        if self.parent and hasattr(self.parent, 'settings'):
            fast_scan = self.parent.settings.value('scanning/fast_scan', True, type=bool)
            self.fast_scan_check.setChecked(fast_scan)
            
            sampling_index = self.parent.settings.value('scanning/pil_sampling_index', 2, type=int)
            if 0 <= sampling_index < self.pil_sampling_combo.count():
                self.pil_sampling_combo.setCurrentIndex(sampling_index)
    
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
            config.set('DEFAULTS', 'max_retries', str(self.max_retries_spin.value()))
            config.set('DEFAULTS', 'parallel_batch_size', str(self.batch_size_spin.value()))
            
            # Save timeout settings
            config.set('DEFAULTS', 'upload_connect_timeout', str(self.connect_timeout_spin.value()))
            config.set('DEFAULTS', 'upload_read_timeout', str(self.read_timeout_spin.value()))
            
            # Save general settings
            config.set('DEFAULTS', 'confirm_delete', str(self.confirm_delete_check.isChecked()))
            config.set('DEFAULTS', 'auto_rename', str(self.auto_rename_check.isChecked()))
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
                app_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                new_path = os.path.join(app_root, '.imxup')
            elif self.custom_radio.isChecked():
                storage_mode = 'custom'
                new_path = self.path_edit.text().strip()
            
            # Check if path is actually changing
            if new_path and os.path.normpath(new_path) != os.path.normpath(current_active_path):
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
                    
                    # Save new settings
                    config.set('DEFAULTS', 'storage_mode', storage_mode)
                    config.set('DEFAULTS', 'central_store_path', new_path)
                    with open(config_file, 'w') as f:
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
                    config.set('DEFAULTS', 'storage_mode', storage_mode)
                    config.set('DEFAULTS', 'central_store_path', new_path)
                    with open(config_file, 'w') as f:
                        config.write(f)
            else:
                # Path not changing, just save other settings
                config.set('DEFAULTS', 'storage_mode', storage_mode)
                if new_path:
                    config.set('DEFAULTS', 'central_store_path', new_path)
                with open(config_file, 'w') as f:
                    config.write(f)
            
            # Update parent GUI controls
            if self.parent:
                self.parent.thumbnail_size_combo.setCurrentIndex(self.thumbnail_size_combo.currentIndex())
                self.parent.thumbnail_format_combo.setCurrentIndex(self.thumbnail_format_combo.currentIndex())
                self.parent.max_retries_spin.setValue(self.max_retries_spin.value())
                self.parent.batch_size_spin.setValue(self.batch_size_spin.value())
                
                # Update storage settings (only those that exist in parent)
                if hasattr(self.parent, 'confirm_delete_check'):
                    self.parent.confirm_delete_check.setChecked(self.confirm_delete_check.isChecked())
                if hasattr(self.parent, 'auto_rename_check'):
                    self.parent.auto_rename_check.setChecked(self.auto_rename_check.isChecked())
                if hasattr(self.parent, 'store_in_uploaded_check'):
                    self.parent.store_in_uploaded_check.setChecked(self.store_in_uploaded_check.isChecked())
                if hasattr(self.parent, 'store_in_central_check'):
                    self.parent.store_in_central_check.setChecked(self.store_in_central_check.isChecked())
                if storage_mode == 'custom':
                    self.parent.central_store_path_value = new_path
                
                # Save theme and font size to QSettings
                if hasattr(self.parent, 'settings'):
                    font_size = self.font_size_spin.value()
                    print(f"_save_general_tab: Saving font size to settings: {font_size}")
                    self.parent.settings.setValue('ui/theme', self.theme_combo.currentText())
                    self.parent.settings.setValue('ui/font_size', font_size)
                    
                    # Apply theme and font size immediately
                    self.parent.apply_theme(self.theme_combo.currentText())
                    if hasattr(self.parent, 'apply_font_size'):
                        print(f"_save_general_tab: Applying font size: {font_size}")
                        self.parent.apply_font_size(font_size)
            
            return True
        except Exception as e:
            print(f"Error saving general settings: {e}")
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
            if self.parent and hasattr(self.parent, 'queue_manager'):
                progress.setLabelText("Closing database connection...")
                try:
                    self.parent.queue_manager.shutdown()
                except:
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
            if self.parent:
                self.parent.close()
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
            print(f"Error saving upload settings: {e}")
            return False
    
    def _save_templates_tab(self):
        """Save Templates tab settings only"""
        try:
            if hasattr(self, 'template_dialog') and self.template_dialog.unsaved_changes:
                return self.template_dialog.save_template()
            return True
        except Exception as e:
            print(f"Error saving template settings: {e}")
            return False
    
    def _save_scanning_tab(self):
        """Save Scanning tab settings only"""
        try:
            config = configparser.ConfigParser()
            config_file = get_config_path()
            
            if os.path.exists(config_file):
                config.read(config_file)
            
            if 'SCANNING' not in config:
                config.add_section('SCANNING')
            
            # Save scanning settings
            config.set('SCANNING', 'fast_scanning', str(self.fast_scanning_cb.isChecked()))
            config.set('SCANNING', 'pil_sample_count', str(self.pil_sample_spin.value()))
            
            with open(config_file, 'w') as f:
                config.write(f)
            
            return True
        except Exception as e:
            print(f"Error saving scanning settings: {e}")
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
            print(f"Error saving tab settings: {e}")
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
                if hasattr(self, 'parent') and self.parent and hasattr(self.parent, 'refresh_all_status_icons'):
                    self.parent.refresh_all_status_icons()
                elif hasattr(self, 'parent') and self.parent and hasattr(self.parent, '_update_all_status_icons'):
                    self.parent._update_all_status_icons()
                
                print("Icon changes applied successfully")
                return True
            else:
                print("Warning: IconManager not available")
                return True
                
        except Exception as e:
            print(f"Error saving icons tab: {e}")
            from PyQt6.QtWidgets import QMessageBox
            show_error(self, "Error", f"Failed to apply icon changes: {str(e)}")
            return False
    
    def _save_logs_tab(self):
        """Save Logs tab settings (placeholder for now)"""
        try:
            # The logs tab is mostly for viewing, not configuration
            # Add any logs-specific settings here if needed in the future
            return True
        except Exception as e:
            print(f"Error saving logs tab: {e}")
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
            is_dark_theme = "Dark" in theme_text
            is_selected = "Selected" in theme_text
            
            # Get icon based on current theme settings
            icon = icon_manager.get_icon(icon_key, None, is_dark_theme, is_selected)
            
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
            print(f"Error updating icon preview: {e}")
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
                self.config_type_label.setStyleSheet("font-weight: bold; font-size: 10px; color: #0066cc; padding: 5px;")
            elif isinstance(icon_config, list):
                self.config_type_label.setText("Configuration: Light/Dark pair (manual control)")
                self.config_type_label.setStyleSheet("font-weight: bold; font-size: 10px; color: #cc6600; padding: 5px;")
            else:
                self.config_type_label.setText("Configuration: Invalid")
                self.config_type_label.setStyleSheet("font-weight: bold; font-size: 10px; color: #cc0000; padding: 5px;")
            
            # Update light theme preview (unselected light theme)
            light_icon = icon_manager.get_icon(icon_key, None, is_dark_theme=False, is_selected=False, requested_size=96)
            if not light_icon.isNull():
                pixmap = light_icon.pixmap(96, 96)  # Match the label size
                self.light_icon_label.setPixmap(pixmap)
                
                # Check if this is inverted from original
                if isinstance(icon_config, str):
                    # Single icon - check if this would be inverted
                    if icon_manager._needs_inversion(is_dark_theme=False, is_selected=False):
                        self.light_status_label.setText("Original (inverted)")
                        self.light_status_label.setStyleSheet("font-size: 9px; color: #cc6600;")
                    else:
                        self.light_status_label.setText("Original")
                        self.light_status_label.setStyleSheet("font-size: 9px; color: #006600;")
                else:
                    self.light_status_label.setText("Light variant")
                    self.light_status_label.setStyleSheet("font-size: 9px; color: #006600;")
            else:
                self.light_icon_label.setText("Missing")
                self.light_status_label.setText("Qt fallback")
                self.light_status_label.setStyleSheet("font-size: 9px; color: #cc0000;")
            
            # Update dark theme preview (unselected dark theme) 
            dark_icon = icon_manager.get_icon(icon_key, None, is_dark_theme=True, is_selected=False, requested_size=96)
            if not dark_icon.isNull():
                pixmap = dark_icon.pixmap(96, 96)  # Match the label size
                self.dark_icon_label.setPixmap(pixmap)
                
                # Check if this is inverted from original
                if isinstance(icon_config, str):
                    # Single icon - check if this would be inverted
                    if icon_manager._needs_inversion(is_dark_theme=True, is_selected=False):
                        self.dark_status_label.setText("Original (inverted)")
                        self.dark_status_label.setStyleSheet("font-size: 9px; color: #cc6600;")
                    else:
                        self.dark_status_label.setText("Original")
                        self.dark_status_label.setStyleSheet("font-size: 9px; color: #006600;")
                else:
                    self.dark_status_label.setText("Dark variant")
                    self.dark_status_label.setStyleSheet("font-size: 9px; color: #006600;")
            else:
                self.dark_icon_label.setText("Missing")
                self.dark_status_label.setText("Qt fallback")
                self.dark_status_label.setStyleSheet("font-size: 9px; color: #cc0000;")
            
            # Update reset button states based on whether icons are default
            self._update_reset_button_states(icon_key, icon_config)
                
        except Exception as e:
            print(f"Error updating dual icon previews: {e}")
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
                dark_backup_exists = dark_path and os.path.exists(dark_path + ".backup")
                
                self.light_reset_btn.setEnabled(light_backup_exists)
                self.dark_reset_btn.setEnabled(dark_backup_exists if dark_path else False)
            else:
                # Invalid config
                self.light_reset_btn.setEnabled(False)
                self.dark_reset_btn.setEnabled(False)
                
        except Exception as e:
            print(f"Error updating reset button states: {e}")
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
            if self.parent and hasattr(self.parent, 'refresh_icons'):
                self.parent.refresh_icons()
            
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
            if self.parent and hasattr(self.parent, 'refresh_icons'):
                self.parent.refresh_icons()
            
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
                if self.parent and hasattr(self.parent, 'refresh_icons'):
                    self.parent.refresh_icons()
                
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
                self.mark_tab_dirty(6)  # Icons tab
                
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
                        print(f"Failed to reset {icon_key}: {e}")
                
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


# Import the dialog classes that will be moved to imxup_dialogs.py
# For now, we'll keep them here to avoid circular imports
# TODO: Move these to imxup_dialogs.py in Phase 3

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
            "#galleryLink#", "#allImages#", "#custom1#", "#custom2#", "#custom3#", "#custom4#"
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
            "IMX.to credentials:\n\n"
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
        save_btn.clicked.connect(dialog.accept)
        button_layout.addWidget(save_btn)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(dialog.reject)
        button_layout.addWidget(cancel_btn)
        
        layout.addLayout(button_layout)
        
        # Use non-blocking approach
        dialog.finished.connect(lambda result: self._handle_username_dialog_result(result, username_edit.text().strip()))
        dialog.open()
    
    def _handle_username_dialog_result(self, result, username):
        """Handle username dialog result"""
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
                    # Create non-blocking message box
                    msg_box = QMessageBox(self)
                    msg_box.setWindowTitle("Success")
                    msg_box.setText("Username saved successfully!")
                    msg_box.open()
                    
                except Exception as e:
                    # Create non-blocking error message box
                    msg_box = QMessageBox(self)
                    msg_box.setIcon(QMessageBox.Icon.Critical)
                    msg_box.setWindowTitle("Error")
                    msg_box.setText(f"Failed to save credentials: {str(e)}")
                    msg_box.open()
            else:
                # Create non-blocking warning message box
                msg_box = QMessageBox(self)
                msg_box.setIcon(QMessageBox.Icon.Warning)
                msg_box.setWindowTitle("Missing Information")
                msg_box.setText("Please enter a username.")
                msg_box.open()

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
        save_btn.clicked.connect(dialog.accept)
        button_layout.addWidget(save_btn)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(dialog.reject)
        button_layout.addWidget(cancel_btn)
        
        layout.addLayout(button_layout)
        
        # Use non-blocking approach
        dialog.finished.connect(lambda result: self._handle_password_dialog_result(result, password_edit.text()))
        dialog.open()
    
    def _handle_password_dialog_result(self, result, password):
        """Handle password dialog result"""
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
                    # Create non-blocking message box
                    msg_box = QMessageBox(self)
                    msg_box.setWindowTitle("Success")
                    msg_box.setText("Password saved successfully!")
                    msg_box.open()
                    
                except Exception as e:
                    # Create non-blocking error message box
                    msg_box = QMessageBox(self)
                    msg_box.setIcon(QMessageBox.Icon.Critical)
                    msg_box.setWindowTitle("Error")
                    msg_box.setText(f"Failed to save password: {str(e)}")
                    msg_box.open()
            else:
                # Create non-blocking warning message box
                msg_box = QMessageBox(self)
                msg_box.setIcon(QMessageBox.Icon.Warning)
                msg_box.setWindowTitle("Missing Information")
                msg_box.setText("Please enter a password.")
                msg_box.open()
    
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
        
        # Use non-blocking approach
        dialog.finished.connect(lambda result: self._handle_api_key_dialog_result(result, api_key_edit.text().strip()))
        dialog.open()
    
    def _handle_api_key_dialog_result(self, result, api_key):
        """Handle API key dialog result"""
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
                    # Create non-blocking message box
                    msg_box = QMessageBox(self)
                    msg_box.setWindowTitle("Success")
                    msg_box.setText("API key saved successfully!")
                    msg_box.open()
                    
                except Exception as e:
                    # Create non-blocking error message box
                    msg_box = QMessageBox(self)
                    msg_box.setIcon(QMessageBox.Icon.Critical)
                    msg_box.setWindowTitle("Error")
                    msg_box.setText(f"Failed to save API key: {str(e)}")
                    msg_box.open()
            else:
                # Create non-blocking warning message box
                msg_box = QMessageBox(self)
                msg_box.setIcon(QMessageBox.Icon.Warning)
                msg_box.setWindowTitle("Missing Information")
                msg_box.setText("Please enter your API key.")
                msg_box.open()

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
            # Create non-blocking error message
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Icon.Critical)
            msg_box.setWindowTitle("Error")
            msg_box.setText(f"Failed to enable cookies: {str(e)}")
            msg_box.open()

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
            # Create non-blocking error message
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Icon.Critical)
            msg_box.setWindowTitle("Error")
            msg_box.setText(f"Failed to disable cookies: {str(e)}")
            msg_box.open()

    def remove_username(self):
        """Remove stored username with confirmation"""
        # Create non-blocking confirmation dialog
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Icon.Question)
        msg_box.setWindowTitle("Remove Username")
        msg_box.setText("Without username/password, all galleries will be titled 'untitled gallery'.\n\nRemove the stored username?")
        msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg_box.setDefaultButton(QMessageBox.StandardButton.No)
        msg_box.finished.connect(lambda result: self._handle_remove_username_confirmation(result))
        msg_box.open()
    
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
            # Create non-blocking success message
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Removed")
            msg_box.setText("Username removed.")
            msg_box.open()
        except Exception as e:
            # Create non-blocking error message
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Icon.Critical)
            msg_box.setWindowTitle("Error")
            msg_box.setText(f"Failed to remove username: {str(e)}")
            msg_box.open()

    def remove_password(self):
        """Remove stored password with confirmation"""
        # Create non-blocking confirmation dialog
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Icon.Question)
        msg_box.setWindowTitle("Remove Password")
        msg_box.setText("Without username/password, all galleries will be titled 'untitled gallery'.\n\nRemove the stored password?")
        msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg_box.setDefaultButton(QMessageBox.StandardButton.No)
        msg_box.finished.connect(lambda result: self._handle_remove_password_confirmation(result))
        msg_box.open()
    
    def _handle_remove_password_confirmation(self, result):
        """Handle password removal confirmation"""
        if result != QMessageBox.StandardButton.Yes:
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
            # Create non-blocking success message
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Removed")
            msg_box.setText("Password removed.")
            msg_box.open()
        except Exception as e:
            # Create non-blocking error message
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Icon.Critical)
            msg_box.setWindowTitle("Error")
            msg_box.setText(f"Failed to remove password: {str(e)}")
            msg_box.open()

    def remove_api_key(self):
        """Remove stored API key with confirmation"""
        # Create non-blocking confirmation dialog
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Icon.Question)
        msg_box.setWindowTitle("Remove API Key")
        msg_box.setText("Without an API key, it is not possible to upload anything.\n\nRemove the stored API key?")
        msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg_box.setDefaultButton(QMessageBox.StandardButton.No)
        msg_box.finished.connect(lambda result: self._handle_remove_api_key_confirmation(result))
        msg_box.open()
    
    def _handle_remove_api_key_confirmation(self, result):
        """Handle API key removal confirmation"""
        if result != QMessageBox.StandardButton.Yes:
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
            # Create non-blocking success message
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Removed")
            msg_box.setText("API key removed.")
            msg_box.open()
        except Exception as e:
            # Create non-blocking error message
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Icon.Critical)
            msg_box.setWindowTitle("Error")
            msg_box.setText(f"Failed to remove API key: {str(e)}")
            msg_box.open()

    def remove_all_credentials(self):
        """Remove username, password, and API key with confirmation"""
        # Create non-blocking confirmation dialog
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Icon.Question)
        msg_box.setWindowTitle("Remove All Credentials")
        msg_box.setText("This will remove your username, password, and API key.\n\n- Without username/password, all galleries will be titled 'untitled gallery'.\n- Without an API key, uploads are not possible.\n\nProceed?")
        msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg_box.setDefaultButton(QMessageBox.StandardButton.No)
        msg_box.finished.connect(lambda result: self._handle_remove_all_credentials_confirmation(result))
        msg_box.open()
    
    def _handle_remove_all_credentials_confirmation(self, result):
        """Handle all credentials removal confirmation"""
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
            config['CREDENTIALS']['password'] = ''
            config['CREDENTIALS']['api_key'] = ''
            with open(config_file, 'w') as f:
                config.write(f)
            self.load_current_credentials()
            # Create non-blocking success message
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Removed")
            msg_box.setText("All credentials removed.")
            msg_box.open()
        except Exception as e:
            # Create non-blocking error message
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Icon.Critical)
            msg_box.setWindowTitle("Error")
            msg_box.setText(f"Failed to remove all credentials: {str(e)}")
            msg_box.open()
    

    
    def validate_and_close(self):
        """Close the dialog - no validation required"""
        self.accept()
    
    def save_credentials(self):
        """Save credentials securely - this is now handled by individual change buttons"""
        self.accept()


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
        
        self.save_btn = QPushButton("Save Template")
        if not self.save_btn.text().startswith(" "):
            self.save_btn.setText(" " + self.save_btn.text())
        self.save_btn.clicked.connect(self.save_template)
        self.save_btn.setEnabled(False)
        actions_layout.addWidget(self.save_btn)
        
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
            ("#allImages#", "All Images"),
            ("#custom1#", "Custom 1"),
            ("#custom2#", "Custom 2"),
            ("#custom3#", "Custom 3"),
            ("#custom4#", "Custom 4")
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
                # Create non-blocking unsaved changes confirmation dialog
                msg_box = QMessageBox(self)
                msg_box.setIcon(QMessageBox.Icon.Question)
                msg_box.setWindowTitle("Unsaved Changes")
                msg_box.setText(f"You have unsaved changes to template '{self.current_template_name}'. Do you want to save them before switching?")
                msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel)
                msg_box.setDefaultButton(QMessageBox.StandardButton.Yes)
                msg_box.finished.connect(lambda result: self._handle_template_switch_unsaved_changes(result, template_name))
                msg_box.open()
                return
            
            self._switch_to_template(template_name)
        else:
            self.template_editor.clear()
            self.current_template_name = None
            self.unsaved_changes = False
            self.rename_btn.setEnabled(False)
            self.delete_btn.setEnabled(False)
    
    def _handle_template_switch_unsaved_changes(self, result, new_template_name):
        """Handle unsaved changes confirmation for template switching"""
        if result == QMessageBox.StandardButton.Yes:
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
                # After saving, switch to new template
                self._switch_to_template(new_template_name)
            except Exception as e:
                # Create non-blocking error message
                msg_box = QMessageBox(self)
                msg_box.setIcon(QMessageBox.Icon.Warning)
                msg_box.setWindowTitle("Error")
                msg_box.setText(f"Failed to save template: {str(e)}")
                msg_box.open()
                # Restore the previous selection if save failed
                self._restore_previous_template_selection()
        elif result == QMessageBox.StandardButton.No:
            # Don't save, but switch to new template
            self._switch_to_template(new_template_name)
        else:  # Cancel
            # Restore the previous selection
            self._restore_previous_template_selection()
    
    def _restore_previous_template_selection(self):
        """Restore the previous template selection"""
        for i in range(self.template_list.count()):
            if self.template_list.item(i).text() == self.current_template_name:
                self.template_list.setCurrentRow(i)
                return
    
    def _switch_to_template(self, template_name):
        """Switch to the specified template"""
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
            # Create non-blocking unsaved changes confirmation dialog
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Icon.Question)
            msg_box.setWindowTitle("Unsaved Changes")
            msg_box.setText(f"You have unsaved changes to template '{self.current_template_name}'. Do you want to save them before creating a new template?")
            msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel)
            msg_box.setDefaultButton(QMessageBox.StandardButton.Yes)
            msg_box.finished.connect(lambda result: self._handle_new_template_unsaved_changes(result))
            msg_box.open()
            return
        
        # Proceed directly to new template creation
        self._show_new_template_input()
    
    def _handle_new_template_unsaved_changes(self, result):
        """Handle unsaved changes confirmation for new template creation"""
        if result == QMessageBox.StandardButton.Yes:
            self.save_template()
            # After saving, proceed to new template creation
            self._show_new_template_input()
        elif result == QMessageBox.StandardButton.No:
            # Don't save, but proceed to new template creation
            self._show_new_template_input()
        # Cancel - do nothing
    
    def _show_new_template_input(self):
        """Show new template name input dialog"""
        
        # Create non-blocking input dialog
        input_dialog = QInputDialog(self)
        input_dialog.setWindowTitle("New Template")
        input_dialog.setLabelText("Template name:")
        input_dialog.setTextValue("")
        input_dialog.finished.connect(lambda result: self._handle_new_template_result(result, input_dialog.textValue().strip()))
        input_dialog.open()
    
    def _handle_new_template_result(self, result, name):
        """Handle new template dialog result"""
        if result == QInputDialog.DialogCode.Accepted and name:
            # Check if template already exists
            from imxup import load_templates
            templates = load_templates()
            if name in templates:
                # Create non-blocking warning message box
                msg_box = QMessageBox(self)
                msg_box.setIcon(QMessageBox.Icon.Warning)
                msg_box.setWindowTitle("Error")
                msg_box.setText(f"Template '{name}' already exists!")
                msg_box.open()
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
            # Create non-blocking warning message
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Icon.Warning)
            msg_box.setWindowTitle("Error")
            msg_box.setText("Cannot rename the default template!")
            msg_box.open()
            return
        
        # Create non-blocking input dialog
        input_dialog = QInputDialog(self)
        input_dialog.setWindowTitle("Rename Template")
        input_dialog.setLabelText("New name:")
        input_dialog.setTextValue(old_name)
        input_dialog.finished.connect(lambda result: self._handle_rename_template_result(result, input_dialog.textValue().strip(), old_name, current_item))
        input_dialog.open()
    
    def _handle_rename_template_result(self, result, new_name, old_name, current_item):
        """Handle rename template dialog result"""
        if result == QInputDialog.DialogCode.Accepted and new_name:
            # Check if new name already exists
            from imxup import load_templates
            templates = load_templates()
            if new_name in templates:
                # Create non-blocking warning message box
                msg_box = QMessageBox(self)
                msg_box.setIcon(QMessageBox.Icon.Warning)
                msg_box.setWindowTitle("Error")
                msg_box.setText(f"Template '{new_name}' already exists!")
                msg_box.open()
                return
            
            # Rename the template file
            from imxup import get_template_path
            template_path = get_template_path()
            old_file = os.path.join(template_path, f".template {old_name}.txt")
            new_file = os.path.join(template_path, f".template {new_name}.txt")
            
            try:
                os.rename(old_file, new_file)
                current_item.setText(new_name)
                # Create non-blocking success message box
                msg_box = QMessageBox(self)
                msg_box.setWindowTitle("Success")
                msg_box.setText(f"Template renamed to '{new_name}'")
                msg_box.open()
            except Exception as e:
                # Create non-blocking error message box
                msg_box = QMessageBox(self)
                msg_box.setIcon(QMessageBox.Icon.Warning)
                msg_box.setWindowTitle("Error")
                msg_box.setText(f"Failed to rename template: {str(e)}")
                msg_box.open()
    
    def delete_template(self):
        """Delete the current template"""
        current_item = self.template_list.currentItem()
        if not current_item:
            return
        
        template_name = current_item.text()
        if template_name == "default":
            # Create non-blocking warning message
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Icon.Warning)
            msg_box.setWindowTitle("Error")
            msg_box.setText("Cannot delete the default template!")
            msg_box.open()
            return
        
        # Check for unsaved changes before deleting
        if self.unsaved_changes and self.current_template_name == template_name:
            # Create non-blocking unsaved changes confirmation dialog
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Icon.Question)
            msg_box.setWindowTitle("Unsaved Changes")
            msg_box.setText(f"You have unsaved changes to template '{template_name}'. Do you want to save them before deleting?")
            msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel)
            msg_box.setDefaultButton(QMessageBox.StandardButton.Yes)
            msg_box.finished.connect(lambda result: self._handle_delete_template_unsaved_changes(result, template_name))
            msg_box.open()
        else:
            # Proceed directly to delete confirmation
            self._show_delete_template_confirmation(template_name)
    
    def _handle_delete_template_unsaved_changes(self, result, template_name):
        """Handle unsaved changes confirmation for template deletion"""
        if result == QMessageBox.StandardButton.Yes:
            self.save_template()
            # After saving, proceed to delete confirmation
            self._show_delete_template_confirmation(template_name)
        elif result == QMessageBox.StandardButton.No:
            # Don't save, but proceed to delete confirmation
            self._show_delete_template_confirmation(template_name)
        # Cancel - do nothing
    
    def _show_delete_template_confirmation(self, template_name):
        """Show delete template confirmation dialog"""
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Icon.Question)
        msg_box.setWindowTitle("Delete Template")
        msg_box.setText(f"Are you sure you want to delete template '{template_name}'?")
        msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg_box.setDefaultButton(QMessageBox.StandardButton.No)
        msg_box.finished.connect(lambda result: self._handle_delete_template_confirmation(result, template_name))
        msg_box.open()
    
    def _handle_delete_template_confirmation(self, result, template_name):
        """Handle delete template confirmation"""
        if result == QMessageBox.StandardButton.Yes:
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
                # Create non-blocking success message
                msg_box = QMessageBox(self)
                msg_box.setWindowTitle("Success")
                msg_box.setText(f"Template '{template_name}' deleted")
                msg_box.open()
            except Exception as e:
                # Create non-blocking error message
                msg_box = QMessageBox(self)
                msg_box.setIcon(QMessageBox.Icon.Warning)
                msg_box.setWindowTitle("Error")
                msg_box.setText(f"Failed to delete template: {str(e)}")
                msg_box.open()
    
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
            # Create non-blocking success message
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Success")
            msg_box.setText(f"Template '{template_name}' saved")
            msg_box.open()
        except Exception as e:
            # Create non-blocking error message
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Icon.Warning)
            msg_box.setWindowTitle("Error")
            msg_box.setText(f"Failed to save template: {str(e)}")
            msg_box.open()
    
    def closeEvent(self, event):
        """Handle dialog closing with unsaved changes check"""
        if self.unsaved_changes and self.current_template_name:
            # Create non-blocking unsaved changes confirmation dialog
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Icon.Question)
            msg_box.setWindowTitle("Unsaved Changes")
            msg_box.setText(f"You have unsaved changes to template '{self.current_template_name}'. Do you want to save them before closing?")
            msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel)
            msg_box.setDefaultButton(QMessageBox.StandardButton.Yes)
            msg_box.finished.connect(lambda result: self._handle_close_unsaved_changes(result, event))
            msg_box.open()
            # Ignore the event for now - the handler will decide whether to close
            event.ignore()
        else:
            event.accept()
    
    def _handle_close_unsaved_changes(self, result, event):
        """Handle unsaved changes confirmation for dialog closing"""
        if result == QMessageBox.StandardButton.Yes:
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
                    self.accept()  # Close the dialog
                except Exception as e:
                    # Create non-blocking error message
                    msg_box = QMessageBox(self)
                    msg_box.setIcon(QMessageBox.Icon.Warning)
                    msg_box.setWindowTitle("Error")
                    msg_box.setText(f"Failed to save template: {str(e)}")
                    msg_box.open()
                    # Don't close the dialog if save failed
            else:
                self.accept()  # Close the dialog
        elif result == QMessageBox.StandardButton.No:
            self.accept()  # Close the dialog without saving
        # Cancel - do nothing (dialog stays open)


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
        
    def append_message(self, message: str):
        """Append a message to the log viewer"""
        if self.follow_check.isChecked():
            self.log_text.appendPlainText(message)
            # Auto-scroll to bottom
            cursor = self.log_text.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            self.log_text.setTextCursor(cursor)
