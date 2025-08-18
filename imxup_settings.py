#!/usr/bin/env python3
"""
Settings management module for imxup GUI
Contains all settings-related dialogs and configuration management
"""

import os
import sys
import configparser
from typing import List, Dict, Any, Optional

from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QTabWidget, QPushButton, QCheckBox, QComboBox, QSpinBox,
    QLabel, QGroupBox, QLineEdit, QMessageBox, QFileDialog,
    QListWidget, QListWidgetItem, QPlainTextEdit, QInputDialog
)
from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtGui import QIcon, QFont, QColor, QTextCharFormat
from PyQt6.QtGui import QSyntaxHighlighter

# Import local modules
from imxup import load_user_defaults, get_config_path, encrypt_password, decrypt_password


class ComprehensiveSettingsDialog(QDialog):
    """Comprehensive settings dialog with tabbed interface"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.setup_ui()
        self.load_settings()
        
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
        self.setup_logs_tab()
        self.setup_scanning_tab()
        
        # Buttons
        button_layout = QHBoxLayout()
        
        # Reset button on the left
        self.reset_btn = QPushButton("Reset to Defaults")
        self.reset_btn.clicked.connect(self.reset_to_defaults)
        button_layout.addWidget(self.reset_btn)
        
        button_layout.addStretch()
        
        # Standard button order: OK, Cancel
        self.ok_btn = QPushButton("OK")
        self.ok_btn.clicked.connect(self.save_and_close)
        button_layout.addWidget(self.ok_btn)
        
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
        
        # General settings group
        general_group = QGroupBox("General Settings")
        general_layout = QGridLayout(general_group)
        
        # Confirm delete
        self.confirm_delete_check = QCheckBox("Confirm before deleting")
        self.confirm_delete_check.setChecked(defaults.get('confirm_delete', True))
        general_layout.addWidget(self.confirm_delete_check, 0, 0)
        
        # Public gallery
        self.public_gallery_check = QCheckBox("Make galleries public")
        self.public_gallery_check.setChecked(defaults.get('public_gallery', 1) == 1)
        general_layout.addWidget(self.public_gallery_check, 0, 1)
        
        # Auto-rename
        self.auto_rename_check = QCheckBox("Auto-rename galleries")
        self.auto_rename_check.setChecked(defaults.get('auto_rename', True))
        general_layout.addWidget(self.auto_rename_check, 1, 0, 1, 2)
        
        # Storage options group
        storage_group = QGroupBox("Storage Options")
        storage_layout = QGridLayout(storage_group)
        
        # Store in uploaded folder
        self.store_in_uploaded_check = QCheckBox("Save artifacts in .uploaded folder")
        self.store_in_uploaded_check.setChecked(defaults.get('store_in_uploaded', True))
        storage_layout.addWidget(self.store_in_uploaded_check, 0, 0, 1, 2)
        
        # Store in central location
        self.store_in_central_check = QCheckBox("Save artifacts in central store")
        self.store_in_central_check.setChecked(defaults.get('store_in_central', True))
        storage_layout.addWidget(self.store_in_central_check, 1, 0, 1, 2)
        
        # Central store path
        from imxup import get_central_store_base_path, get_default_central_store_base_path
        current_path = defaults.get('central_store_path') or get_central_store_base_path()
        
        path_label = QLabel("Central store path:")
        self.path_edit = QLineEdit(current_path)
        self.path_edit.setReadOnly(True)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self.browse_central_store)
        
        storage_layout.addWidget(path_label, 2, 0)
        storage_layout.addWidget(self.path_edit, 2, 1)
        storage_layout.addWidget(browse_btn, 2, 2)
        
        # Enable/disable path controls based on central store checkbox
        def set_path_controls_enabled(enabled):
            path_label.setEnabled(enabled)
            self.path_edit.setEnabled(enabled)
            browse_btn.setEnabled(enabled)
        
        set_path_controls_enabled(self.store_in_central_check.isChecked())
        self.store_in_central_check.toggled.connect(set_path_controls_enabled)
        
        # Theme group
        theme_group = QGroupBox("Theme")
        theme_layout = QHBoxLayout(theme_group)
        
        theme_label = QLabel("Theme mode:")
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["system", "light", "dark"])
        
        # Load current theme from QSettings
        if self.parent and hasattr(self.parent, 'settings'):
            current_theme = self.parent.settings.value('ui/theme', 'system')
            index = self.theme_combo.findText(current_theme)
            if index >= 0:
                self.theme_combo.setCurrentIndex(index)
        
        theme_layout.addWidget(theme_label)
        theme_layout.addWidget(self.theme_combo)
        theme_layout.addStretch()
        
        # Add all groups to layout
        layout.addWidget(upload_group)
        layout.addWidget(general_group)
        layout.addWidget(storage_group)
        layout.addWidget(theme_group)
        layout.addStretch()
        
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
        
    def setup_logs_tab(self):
        """Setup the Logs tab with integrated log viewer"""
        logs_widget = QWidget()
        layout = QVBoxLayout(logs_widget)
        
        # Create and integrate the log viewer dialog
        try:
            # Get initial log text
            from imxup_logging import get_logger
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
        self.tab_widget.addTab(scanning_widget, "Image Scanning")
        
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
            self.path_edit.setText(directory)
            

            
    def load_settings(self):
        """Load current settings"""
        # Settings are loaded in setup_ui for each tab
        # Load scanning settings from QSettings
        self._load_scanning_settings()
    
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
        
    def save_settings(self):
        """Save all settings"""
        try:
            # Save to .ini file via parent
            if self.parent:
                # Update parent's settings objects for checkboxes
                self.parent.confirm_delete_check.setChecked(self.confirm_delete_check.isChecked())
                self.parent.public_gallery_check.setChecked(self.public_gallery_check.isChecked())
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
                
                # Save scanning settings
                self._save_scanning_settings()
                    
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
            # Template selection is now handled in the Templates tab
            
            # Reset checkboxes
            self.confirm_delete_check.setChecked(True)
            self.public_gallery_check.setChecked(True)
            self.auto_rename_check.setChecked(True)
            self.store_in_uploaded_check.setChecked(True)
            self.store_in_central_check.setChecked(True)
            
            # Reset theme
            self.theme_combo.setCurrentText("system")
            
            # Reset scanning
            self.fast_scan_check.setChecked(True)
            self.pil_sampling_combo.setCurrentIndex(2)
            
    def save_and_close(self):
        """Save settings and close dialog"""
        if self.save_settings():
            self.accept()
        else:
            # Stay open if save failed
            pass
    
    def on_tab_changed(self, new_index):
        """Handle tab change - simplified approach"""
        # For now, we only check on dialog close/cancel
        pass
    
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
        # Check if Templates tab has unsaved changes
        if hasattr(self, 'template_dialog') and self.template_dialog.unsaved_changes:
            self._check_unsaved_changes_before_close(lambda: self.accept())
            event.ignore()  # Ignore for now, will be handled by callback
        else:
            # No unsaved changes, proceed with normal close
            event.accept()


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
