#!/usr/bin/env python3
"""
File Host Configuration Dialog
Provides credential setup, testing, and configuration for file host uploads
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout, QLabel, QGroupBox,
    QPushButton, QLineEdit, QCheckBox, QProgressBar, QComboBox, QWidget, QListWidget,
    QSplitter, QSpinBox, QSizePolicy, QPlainTextEdit
)
from PyQt6.QtCore import QSettings, QTimer, Qt
from PyQt6.QtGui import QPixmap, QFont
from datetime import datetime
from typing import Optional
import time

from src.utils.format_utils import format_binary_size, format_binary_rate
from src.gui.widgets.custom_widgets import CopyableLogListWidget


class AsteriskPasswordEdit(QLineEdit):
    """Custom QLineEdit that shows asterisks (*) instead of password dots when masked"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_masked = True
        self._actual_text = ""
        self.textChanged.connect(self._on_text_changed)

    def _on_text_changed(self, text):
        """Track actual text separately when masked"""
        if not self._is_masked:
            self._actual_text = text

    def setText(self, text):
        """Override setText to handle initial value loading"""
        self._actual_text = text
        if self._is_masked:
            super().setText("*" * len(text))
        else:
            super().setText(text)

    def text(self):
        """Override text() to return actual text, not asterisks"""
        return self._actual_text if self._is_masked else super().text()

    def set_masked(self, masked: bool):
        """Toggle between masked (asterisks) and visible mode"""
        self._is_masked = masked
        if masked:
            # Save actual text before masking
            self._actual_text = super().text()
            super().setText("*" * len(self._actual_text))
            self.setReadOnly(True)  # Prevent editing while masked
        else:
            # Show actual text
            super().setText(self._actual_text)
            self.setReadOnly(False)  # Allow editing when visible


class FileHostConfigDialog(QDialog):
    """Configuration dialog for a single file host"""

    def __init__(self, parent, host_id: str, host_config, main_widgets: dict, worker_manager=None):
        """
        Args:
            parent: Parent settings dialog or widget
            host_id: Host identifier (e.g., 'rapidgator')
            host_config: HostConfig object
            main_widgets: Dictionary of widgets from main File Hosts tab
            worker_manager: FileHostWorkerManager instance (optional)
        """
        super().__init__(parent)
        self.parent_dialog = parent
        self.host_id = host_id
        self.host_config = host_config
        self.main_widgets = main_widgets
        self.worker_manager = worker_manager
        self.worker = worker_manager.get_worker(host_id) if worker_manager else None

        # Connect to spinup_complete signal for credential failures
        if self.worker_manager:
            self.worker_manager.spinup_complete.connect(self._on_spinup_complete)

        self.settings = QSettings("ImxUploader", "ImxUploadGUI")

        # Initialize saved values for cache (updated when Apply/Enable/Disable clicked)
        # These values are returned by get_*() methods when dialog closes
        from src.core.file_host_config import get_file_host_setting
        self.saved_enabled = get_file_host_setting(host_id, "enabled", "bool")
        self.saved_credentials = None  # Updated in setup_ui() if host requires auth

        # Load trigger setting from INI (single string value, not three booleans)
        self.saved_trigger = get_file_host_setting(host_id, "trigger", "str")

        # Track dirty state (unsaved changes)
        self.has_unsaved_changes = False

        self.setWindowTitle(f"File Host Configuration: {host_config.name}")
        self.setModal(True)
        self.resize(900, 650)  # Wider for horizontal split

        # Connect to worker signals if available (using helper to prevent duplicates)
        self._connect_worker_signals()

        self.setup_ui()

    def setup_ui(self):
        """Setup the dialog UI"""
        # Get actual enabled state from manager (source of truth)
        actual_enabled = self.worker_manager.is_enabled(self.host_id) if self.worker_manager else False

        # Load trigger setting from INI (single string value)
        from src.core.file_host_config import get_file_host_setting
        current_trigger = get_file_host_setting(self.host_id, "trigger", "str")


        layout = QVBoxLayout(self)

        # Host info header with logo
        header_layout = QHBoxLayout()

        # Host name and description (left side)
        info_label = QLabel(f"<h2>{self.host_config.name}</h2><p>Configure host settings, credentials, and test connection</p>")
        header_layout.addWidget(info_label, 1)

        # Host logo (if available) - positioned in top right corner with spacing
        logo_label = self._load_host_logo(self.host_id)
        if logo_label:
            header_layout.addWidget(logo_label)
            header_layout.addSpacing(100)  # 100px empty space to the right of logo

        layout.addLayout(header_layout)

        # Enable/Disable button - power button paradigm
        button_row = QHBoxLayout()

        self.enable_button = QPushButton()
        self.enable_button.setMinimumWidth(200)
        self.enable_button.clicked.connect(self._on_enable_button_clicked)
        button_row.addWidget(self.enable_button)

        # Error label beside button
        self.enable_error_label = QLabel()
        # Use QSS class for theme-aware styling
        self.enable_error_label.setProperty("class", "status-error")
        self.enable_error_label.setWordWrap(True)
        button_row.addWidget(self.enable_error_label, 1)

        layout.addLayout(button_row)

        # Create splitter for resizable horizontal split between controls and logs
        self.content_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.content_container = self.content_splitter  # Alias for compatibility with disable logic
        layout.addWidget(self.content_splitter)

        # Update button text based on whether worker is running
        self._update_enable_button_state(actual_enabled)

        # Left column for existing widgets
        left_widget = QWidget()
        content_layout = QVBoxLayout(left_widget)  # Keep this name for minimal changes below
        content_layout.setContentsMargins(0, 0, 0, 0)

        # Credentials section - Dynamic multi-field layout
        self.creds_api_key_input = None
        self.creds_username_input = None
        self.creds_password_input = None

        if self.host_config.requires_auth:
            from src.gui.icon_manager import get_icon_manager
            icon_manager = get_icon_manager()

            creds_group = QGroupBox("Credentials")
            creds_layout = QFormLayout(creds_group)
            creds_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

            # Load current credentials from encrypted storage
            from imxup import get_credential, decrypt_password
            from src.utils.logger import log

            encrypted_creds = get_credential(f"file_host_{self.host_id}_credentials")
            decrypted = None
            api_key_val = ""
            username_val = ""
            password_val = ""

            if encrypted_creds:
                try:
                    decrypted = decrypt_password(encrypted_creds)
                    if decrypted:
                        # Parse based on auth type
                        if self.host_config.auth_type in ["api_key", "bearer"]:
                            api_key_val = decrypted
                        elif "|" in decrypted:  # Mixed auth: api_key|username:password
                            parts = decrypted.split("|", 1)
                            api_key_val = parts[0]
                            if ":" in parts[1]:
                                username_val, password_val = parts[1].split(":", 1)
                        elif ":" in decrypted:  # username:password
                            username_val, password_val = decrypted.split(":", 1)
                except Exception as e:
                    log(f"Failed to load credentials for {self.host_id}: {e}", level="error", category="file_hosts")

            # Initialize cached credentials
            self.saved_credentials = decrypted if decrypted else None

            # Determine which fields to show based on auth_type
            if self.host_config.auth_type in ["api_key", "bearer"]:
                # API Key only
                self.creds_api_key_input = AsteriskPasswordEdit()
                self.creds_api_key_input.setFont(QFont("Consolas", 10))
                self.creds_api_key_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                self.creds_api_key_input.setPlaceholderText("Enter API key...")
                self.creds_api_key_input.blockSignals(True)
                self.creds_api_key_input.setText(api_key_val)
                self.creds_api_key_input.blockSignals(False)

                api_key_row = QHBoxLayout()
                api_key_row.addWidget(self.creds_api_key_input)

                show_api_btn = QPushButton()
                show_api_btn.setIcon(icon_manager.get_icon('action_view'))
                show_api_btn.setMaximumWidth(30)
                show_api_btn.setCheckable(True)
                show_api_btn.setToolTip("Show/hide API key")
                show_api_btn.clicked.connect(
                    lambda checked: self.creds_api_key_input.set_masked(not checked)
                )
                api_key_row.addWidget(show_api_btn)

                creds_layout.addRow("API Key:", api_key_row)

            elif self.host_config.auth_type == "mixed":
                # Both API key and username/password
                self.creds_api_key_input = AsteriskPasswordEdit()
                self.creds_api_key_input.setFont(QFont("Consolas", 10))
                self.creds_api_key_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                self.creds_api_key_input.setPlaceholderText("Enter API key...")
                self.creds_api_key_input.blockSignals(True)
                self.creds_api_key_input.setText(api_key_val)
                self.creds_api_key_input.blockSignals(False)

                api_key_row = QHBoxLayout()
                api_key_row.addWidget(self.creds_api_key_input)

                show_api_btn = QPushButton()
                show_api_btn.setIcon(icon_manager.get_icon('action_view'))
                show_api_btn.setMaximumWidth(30)
                show_api_btn.setCheckable(True)
                show_api_btn.setToolTip("Show/hide API key")
                show_api_btn.clicked.connect(
                    lambda checked: self.creds_api_key_input.set_masked(not checked)
                )
                api_key_row.addWidget(show_api_btn)

                creds_layout.addRow("API Key:", api_key_row)

                self.creds_username_input = QLineEdit()
                self.creds_username_input.setFont(QFont("Consolas", 10))
                self.creds_username_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                self.creds_username_input.setPlaceholderText("Enter username...")
                self.creds_username_input.blockSignals(True)
                self.creds_username_input.setText(username_val)
                self.creds_username_input.blockSignals(False)
                creds_layout.addRow("Username:", self.creds_username_input)

                self.creds_password_input = AsteriskPasswordEdit()
                self.creds_password_input.setFont(QFont("Consolas", 10))
                self.creds_password_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                self.creds_password_input.setPlaceholderText("Enter password...")
                self.creds_password_input.blockSignals(True)
                self.creds_password_input.setText(password_val)
                self.creds_password_input.blockSignals(False)

                password_row = QHBoxLayout()
                password_row.addWidget(self.creds_password_input)

                show_pass_btn = QPushButton()
                show_pass_btn.setIcon(icon_manager.get_icon('action_view'))
                show_pass_btn.setMaximumWidth(30)
                show_pass_btn.setCheckable(True)
                show_pass_btn.setToolTip("Show/hide password")
                show_pass_btn.clicked.connect(
                    lambda checked: self.creds_password_input.set_masked(not checked)
                )
                password_row.addWidget(show_pass_btn)

                creds_layout.addRow("Password:", password_row)

            else:
                # Username and password only (token_login, session, etc.)
                self.creds_username_input = QLineEdit()
                self.creds_username_input.setFont(QFont("Consolas", 10))
                self.creds_username_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                self.creds_username_input.setPlaceholderText("Enter username...")
                self.creds_username_input.blockSignals(True)
                self.creds_username_input.setText(username_val)
                self.creds_username_input.blockSignals(False)
                creds_layout.addRow("Username:", self.creds_username_input)

                self.creds_password_input = AsteriskPasswordEdit()
                self.creds_password_input.setFont(QFont("Consolas", 10))
                self.creds_password_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                self.creds_password_input.setPlaceholderText("Enter password...")
                self.creds_password_input.blockSignals(True)
                self.creds_password_input.setText(password_val)
                self.creds_password_input.blockSignals(False)

                password_row = QHBoxLayout()
                password_row.addWidget(self.creds_password_input)

                show_pass_btn = QPushButton()
                show_pass_btn.setIcon(icon_manager.get_icon('action_view'))
                show_pass_btn.setMaximumWidth(30)
                show_pass_btn.setCheckable(True)
                show_pass_btn.setToolTip("Show/hide password")
                show_pass_btn.clicked.connect(
                    lambda checked: self.creds_password_input.set_masked(not checked)
                )
                password_row.addWidget(show_pass_btn)

                creds_layout.addRow("Password:", password_row)

            content_layout.addWidget(creds_group)
        # Storage section
        self.storage_bar = None
        if self.host_config.user_info_url and (self.host_config.storage_left_path or self.host_config.storage_regex):
            storage_group = QGroupBox("Storage")
            storage_layout = QVBoxLayout(storage_group)

            self.storage_bar = QProgressBar()
            self.storage_bar.setMaximum(100)
            self.storage_bar.setValue(0)
            self.storage_bar.setTextVisible(True)
            self.storage_bar.setFormat("Loading...")
            self.storage_bar.setMaximumHeight(20)
            self.storage_bar.setProperty("class", "storage-bar")

            storage_layout.addWidget(self.storage_bar)
            content_layout.addWidget(storage_group)

            # Load storage from cache immediately if available
            self._load_storage_from_cache()

        # Trigger settings - SINGLE DROPDOWN (not checkboxes)
        triggers_group = QGroupBox("Auto-Upload Trigger")
        triggers_layout = QVBoxLayout(triggers_group)

        triggers_layout.addWidget(QLabel(
            "Select when to automatically upload galleries to this host:"
        ))

        self.trigger_combo = QComboBox()
        self.trigger_combo.addItem("Disabled / Manual", None)
        self.trigger_combo.addItem("On Added", "on_added")
        self.trigger_combo.addItem("On Started", "on_started")
        self.trigger_combo.addItem("On Completed", "on_completed")

        # Select current trigger (from INI file - single string value)
        # Block signals during initial load to prevent false dirty state
        self.trigger_combo.blockSignals(True)
        if current_trigger == "on_added":
            self.trigger_combo.setCurrentIndex(1)
        elif current_trigger == "on_started":
            self.trigger_combo.setCurrentIndex(2)
        elif current_trigger == "on_completed":
            self.trigger_combo.setCurrentIndex(3)
        else:  # "disabled" or any other value
            self.trigger_combo.setCurrentIndex(0)  # Disabled
        self.trigger_combo.blockSignals(False)

        triggers_layout.addWidget(self.trigger_combo)
        content_layout.addWidget(triggers_group)

        # Connect change signals to mark dirty state
        if self.creds_api_key_input:
            self.creds_api_key_input.textChanged.connect(self._mark_dirty)
        if self.creds_username_input:
            self.creds_username_input.textChanged.connect(self._mark_dirty)
        if self.creds_password_input:
            self.creds_password_input.textChanged.connect(self._mark_dirty)
        self.trigger_combo.currentIndexChanged.connect(self._mark_dirty)

        # Host Settings (editable) - Read from settings layer
        settings_group = QGroupBox("Host Settings")
        settings_layout = QFormLayout(settings_group)

        # Load current values
        auto_retry = get_file_host_setting(self.host_id, "auto_retry", "bool")
        max_retries = get_file_host_setting(self.host_id, "max_retries", "int")
        max_connections = get_file_host_setting(self.host_id, "max_connections", "int")
        max_file_size_mb = get_file_host_setting(self.host_id, "max_file_size_mb", "int")

        # 1. auto_retry - QCheckBox
        self.auto_retry_check = QCheckBox("Enable automatic retry on upload failure")
        self.auto_retry_check.setChecked(auto_retry)
        self.auto_retry_check.stateChanged.connect(self._mark_dirty)
        settings_layout.addRow("Auto-retry:", self.auto_retry_check)

        # 2. max_retries - QSpinBox
        self.max_retries_spin = QSpinBox()
        self.max_retries_spin.setRange(1, 10)
        self.max_retries_spin.setValue(max_retries)
        self.max_retries_spin.setSuffix(" attempts")
        self.max_retries_spin.setToolTip("Maximum number of retry attempts for failed uploads")
        self.max_retries_spin.valueChanged.connect(self._mark_dirty)
        settings_layout.addRow("Max retries:", self.max_retries_spin)
        # Disable max retries when auto-retry is unchecked
        self.auto_retry_check.toggled.connect(self.max_retries_spin.setEnabled)
        # Set initial state based on checkbox
        self.max_retries_spin.setEnabled(self.auto_retry_check.isChecked())


        # 3. max_connections - QSpinBox
        self.max_connections_spin = QSpinBox()
        self.max_connections_spin.setRange(1, 10)
        self.max_connections_spin.setValue(max_connections)
        self.max_connections_spin.setSuffix(" connections")
        self.max_connections_spin.setToolTip("Maximum concurrent upload connections to this host")
        self.max_connections_spin.valueChanged.connect(self._mark_dirty)
        settings_layout.addRow("Max connections:", self.max_connections_spin)

        # 4. max_file_size_mb - QSpinBox (nullable)
        self.max_file_size_spin = QSpinBox()
        self.max_file_size_spin.setRange(0, 10000)
        self.max_file_size_spin.setValue(max_file_size_mb if max_file_size_mb else 0)
        self.max_file_size_spin.setSuffix(" MB")
        self.max_file_size_spin.setSpecialValueText("No limit")
        self.max_file_size_spin.setToolTip("Maximum file size for uploads (0 = no limit)")
        self.max_file_size_spin.valueChanged.connect(self._mark_dirty)
        settings_layout.addRow("Max file size:", self.max_file_size_spin)

        # 5. inactivity_timeout - QSpinBox
        inactivity_timeout = get_file_host_setting(self.host_id, "inactivity_timeout", "int")
        if inactivity_timeout is None:
            # Get from host config if not in INI
            inactivity_timeout = self.host_config.inactivity_timeout if self.host_config else 300

        self.inactivity_timeout_spin = QSpinBox()
        self.inactivity_timeout_spin.setRange(30, 3600)
        self.inactivity_timeout_spin.setValue(inactivity_timeout)
        self.inactivity_timeout_spin.setSuffix(" seconds")
        self.inactivity_timeout_spin.setToolTip("Abort upload if no progress for this many seconds (default: 300)")
        self.inactivity_timeout_spin.valueChanged.connect(self._mark_dirty)
        settings_layout.addRow("Inactivity timeout:", self.inactivity_timeout_spin)

        # 6. upload_timeout - QSpinBox (nullable)
        upload_timeout = get_file_host_setting(self.host_id, "upload_timeout", "int")
        if upload_timeout is None:
            # Get from host config if not in INI
            upload_timeout = self.host_config.upload_timeout if self.host_config else None

        self.upload_timeout_spin = QSpinBox()
        self.upload_timeout_spin.setRange(0, 7200)
        self.upload_timeout_spin.setValue(upload_timeout if upload_timeout else 0)
        self.upload_timeout_spin.setSuffix(" seconds")
        self.upload_timeout_spin.setSpecialValueText("Unlimited")
        self.upload_timeout_spin.setToolTip("Maximum total upload time (0 = unlimited, not recommended)")
        self.upload_timeout_spin.valueChanged.connect(self._mark_dirty)
        settings_layout.addRow("Max upload time:", self.upload_timeout_spin)

        # 7. bbcode_format - QPlainTextEdit (auto-expanding up to 3 lines)
        bbcode_format = get_file_host_setting(self.host_id, "bbcode_format", "str")
        self.bbcode_format_edit = QPlainTextEdit()
        self.bbcode_format_edit.setPlainText(bbcode_format if bbcode_format else "")
        self.bbcode_format_edit.setPlaceholderText("[url=#link#]#hostName#[/url]")
        self.bbcode_format_edit.setToolTip(
            "Format for download links in BBCode. Use #link# for URL and #hostName# for host name. "
            "Leave empty for raw URL. Supports multiple lines."
        )
        # Auto-expand height based on content (1-3 lines)
        self.bbcode_format_edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.bbcode_format_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.bbcode_format_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        line_height = self.bbcode_format_edit.fontMetrics().lineSpacing()
        # Start with 1 line height, expand up to 3
        self.bbcode_format_edit.setMinimumHeight(line_height + 12)
        self.bbcode_format_edit.setMaximumHeight(line_height * 3 + 12)
        self.bbcode_format_edit.textChanged.connect(self._mark_dirty)
        self.bbcode_format_edit.textChanged.connect(self._adjust_bbcode_height)
        self._adjust_bbcode_height()  # Initial adjustment
        settings_layout.addRow("BBCode Format:", self.bbcode_format_edit)

        content_layout.addWidget(settings_group)

        # Test Results section
        self.setup_test_results_section(content_layout)

        content_layout.addStretch()

        # Add left column to splitter
        self.content_splitter.addWidget(left_widget)

        # Right column: Worker logs
        logs_group = QGroupBox("Worker Logs")
        logs_layout = QVBoxLayout(logs_group)

        self.log_list = CopyableLogListWidget()
        self.log_list.setProperty("class", "console")
        logs_layout.addWidget(self.log_list)

        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self.log_list.clear)
        logs_layout.addWidget(clear_btn)

        # Metrics display section with grid layout
        metrics_group = QGroupBox("Host Metrics")
        metrics_layout = QVBoxLayout(metrics_group)

        metrics_grid = QGridLayout()
        metrics_grid.setSpacing(8)

        # Dictionary to store metric value labels for easy updating
        self._metric_labels = {}

        # Row 0: Headers (bold)
        header_font = QFont()
        header_font.setBold(True)

        headers = ["Metric", "Session", "Today", "All Time"]
        for col, header_text in enumerate(headers):
            header = QLabel(header_text)
            header.setFont(header_font)
            header.setAlignment(Qt.AlignmentFlag.AlignCenter if col > 0 else Qt.AlignmentFlag.AlignLeft)
            metrics_grid.addWidget(header, 0, col)

        # Row 1: Uploaded bytes
        metrics_grid.addWidget(QLabel("Uploaded"), 1, 0)
        for i, period in enumerate(['session', 'today', 'alltime']):
            label = QLabel("--")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._metric_labels[f'bytes_{period}'] = label
            metrics_grid.addWidget(label, 1, i + 1)

        # Row 2: Files
        metrics_grid.addWidget(QLabel("Files"), 2, 0)
        for i, period in enumerate(['session', 'today', 'alltime']):
            label = QLabel("--")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._metric_labels[f'files_{period}'] = label
            metrics_grid.addWidget(label, 2, i + 1)

        # Row 3: Avg Speed
        metrics_grid.addWidget(QLabel("Avg Speed"), 3, 0)
        for i, period in enumerate(['session', 'today', 'alltime']):
            label = QLabel("--")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._metric_labels[f'avg_speed_{period}'] = label
            metrics_grid.addWidget(label, 3, i + 1)

        # Row 4: Peak Speed
        metrics_grid.addWidget(QLabel("Peak Speed"), 4, 0)
        for i, period in enumerate(['session', 'today', 'alltime']):
            label = QLabel("--")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._metric_labels[f'peak_speed_{period}'] = label
            metrics_grid.addWidget(label, 4, i + 1)

        # Row 5: Success %
        metrics_grid.addWidget(QLabel("Success %"), 5, 0)
        for i, period in enumerate(['session', 'today', 'alltime']):
            label = QLabel("--")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._metric_labels[f'success_{period}'] = label
            metrics_grid.addWidget(label, 5, i + 1)

        metrics_layout.addLayout(metrics_grid)

        logs_layout.addWidget(metrics_group)

        # Add logs to splitter
        self.content_splitter.addWidget(logs_group)

        # Set initial splitter sizes (50/50 split) and restore saved state
        self.content_splitter.setSizes([450, 450])  # Initial equal split
        settings = QSettings("ImxUploader", "ImxUploadGUI")
        splitter_state = settings.value(f"FileHostConfigDialog/{self.host_id}/splitter_state")
        if splitter_state:
            self.content_splitter.restoreState(splitter_state)

        # Load initial logs (signal connection handled by _connect_worker_signals in constructor)
        self._load_initial_logs()

        # Load initial metrics data (deferred to avoid blocking UI)
        QTimer.singleShot(100, self._update_metrics_display)

        # Button layout
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        self.apply_btn = QPushButton("Apply")
        self.apply_btn.clicked.connect(self._on_apply_clicked)
        self.apply_btn.setEnabled(False)  # Disabled until changes made
        button_layout.addWidget(self.apply_btn)

        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self._on_save_clicked)
        save_btn.setDefault(True)
        button_layout.addWidget(save_btn)

        layout.addLayout(button_layout)

    def setup_test_results_section(self, parent_layout):
        """Setup the test results section with test button"""
        test_group = QGroupBox("Connection Test (optional)")
        test_group_layout = QVBoxLayout(test_group)

        # Test button at top
        test_button_layout = QHBoxLayout()
        self.test_connection_btn = QPushButton("Test Connection")
        self.test_connection_btn.setToolTip("Run full test: credentials, user info, upload, and delete")
        # Set initial state: disabled if host is not enabled (worker is None)
        self.test_connection_btn.setEnabled(self.worker is not None)
        test_button_layout.addWidget(self.test_connection_btn)
        test_button_layout.addStretch()
        test_group_layout.addLayout(test_button_layout)

        # Test results display
        test_results_layout = QFormLayout()

        # Create labels that will be updated
        self.test_timestamp_label = QLabel("Not tested yet")
        self.test_credentials_label = QLabel("○ Not tested")
        self.test_userinfo_label = QLabel("○ Not tested")
        self.test_upload_label = QLabel("○ Not tested")
        self.test_delete_label = QLabel("○ Not tested")
        self.test_error_label = QLabel("")
        self.test_error_label.setWordWrap(True)
        # Use QSS class for theme-aware styling
        self.test_error_label.setProperty("class", "error-small")

        test_results_layout.addRow("Last tested:", self.test_timestamp_label)
        test_results_layout.addRow("Credentials:", self.test_credentials_label)
        test_results_layout.addRow("User info:", self.test_userinfo_label)
        test_results_layout.addRow("Upload test:", self.test_upload_label)
        test_results_layout.addRow("Delete test:", self.test_delete_label)
        test_results_layout.addRow("", self.test_error_label)

        test_group_layout.addLayout(test_results_layout)
        parent_layout.addWidget(test_group)

        # Load and display existing test results
        self.load_and_display_test_results()

        # Connect test button
        self.test_connection_btn.clicked.connect(self.run_full_test)

    def _load_host_logo(self, host_id: str) -> Optional[QLabel]:
        """Load and create a clickable QLabel with the host's logo.

        Args:
            host_id: Host identifier (used to find logo file)

        Returns:
            Clickable QLabel with scaled logo pixmap, or None if logo not found
        """
        from imxup import get_project_root
        import os

        logo_path = os.path.join(get_project_root(), "assets", "hosts", "logo", f"{host_id}.png")
        if not os.path.exists(logo_path):
            return None

        try:
            pixmap = QPixmap(logo_path)
            if pixmap.isNull():
                return None

            # Scale logo to max height of 40px for dialog header
            scaled_pixmap = pixmap.scaledToHeight(40, Qt.TransformationMode.SmoothTransformation)

            logo_label = QLabel()
            logo_label.setPixmap(scaled_pixmap)
            logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

            # Make clickable if referral URL exists
            if self.host_config.referral_url:
                from PyQt6.QtGui import QCursor, QDesktopServices
                from PyQt6.QtCore import QUrl

                logo_label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
                logo_label.setToolTip(f"Click to visit {self.host_config.name}")

                # Install event handler to detect clicks
                def open_referral_url(event):
                    if event.type() == event.Type.MouseButtonPress:
                        QDesktopServices.openUrl(QUrl(self.host_config.referral_url))
                        return True
                    return False

                logo_label.mousePressEvent = open_referral_url

            return logo_label
        except Exception:
            return None

    def _update_enable_button_state(self, enabled: bool):
        """Update button text and style based on worker state"""
        # Use QSS classes for theme-aware styling (defined in styles.qss)
        if enabled:
            self.enable_button.setText(f"Disable {self.host_config.name}")
            self.enable_button.setProperty("class", "host-disable-btn")
            self.enable_button.style().unpolish(self.enable_button)
            self.enable_button.style().polish(self.enable_button)
            # Only enable Test Connection button when worker is enabled
            if hasattr(self, 'test_connection_btn'):
                self.test_connection_btn.setEnabled(True)
        else:
            self.enable_button.setText(f"Enable {self.host_config.name}")
            self.enable_button.setProperty("class", "host-enable-btn")
            self.enable_button.style().unpolish(self.enable_button)
            self.enable_button.style().polish(self.enable_button)
            # Only disable Test Connection button - user needs to edit credentials to enable!
            if hasattr(self, 'test_connection_btn'):
                self.test_connection_btn.setEnabled(False)

    def _on_enable_button_clicked(self):
        """Handle enable/disable button click - power button paradigm"""
        # Warn about unsaved changes
        if not self._check_unsaved_changes("Enabling/disabling the host"):
            return

        # Check if worker is currently running
        is_enabled = self.worker_manager.is_enabled(self.host_id) if self.worker_manager else False

        if is_enabled:
            # Disconnect ALL worker signals before disable
            if self.worker:
                try:
                    self.worker.log_message[str, str].disconnect(self._add_log)
                except TypeError:
                    pass
                try:
                    self.worker.test_completed.disconnect(self._on_worker_test_completed)
                except TypeError:
                    pass
                try:
                    self.worker.storage_updated.disconnect(self._on_worker_storage_updated)
                except TypeError:
                    pass

            # Disable: Manager handles worker shutdown AND INI persistence
            self.worker_manager.disable_host(self.host_id)
            self._update_enable_button_state(False)
            self.enable_error_label.setText("")

            # UPDATE CACHED VALUE - Critical for stale cache bug fix
            self.saved_enabled = False

            # Clear logs (worker is stopped)
            self.log_list.clear()
            self.worker = None
        else:
            # Enable: Manager handles worker spinup AND INI persistence on success
            self.worker_manager.enable_host(self.host_id)

            # Get worker from pending_workers (not workers yet) to catch ALL startup logs
            self.worker = self.worker_manager.pending_workers.get(self.host_id)
            if self.worker:
                self._connect_worker_signals()

            # Show enabling state - wait for spinup_complete signal
            self.enable_button.setText(f"Enabling {self.host_config.name}...")
            self.enable_button.setEnabled(False)
            self.enable_error_label.setText("")

    def _on_spinup_complete(self, host_id: str, error: str) -> None:
        """Handle worker spinup result from manager signal.

        Args:
            host_id: Host that completed spinup
            error: Error message (empty = success)
        """
        # Only handle if this is our host
        if host_id != self.host_id:
            return

        # Re-enable button
        self.enable_button.setEnabled(True)

        if error:
            # Spinup failed - disconnect signals and clear logs
            if self.worker:
                try:
                    self.worker.log_message[str, str].disconnect(self._add_log)
                    self.worker.test_completed.disconnect(self._on_worker_test_completed)
                    self.worker.storage_updated.disconnect(self._on_worker_storage_updated)
                except TypeError:
                    pass

            self._update_enable_button_state(False)
            #self.log_list.clear()  # Clear failed spinup logs
            self.worker = None

            # UPDATE CACHED VALUE - Critical for stale cache bug fix
            self.saved_enabled = False

            MAX_ERROR_LENGTH = 150
            display_error = error if len(error) <= MAX_ERROR_LENGTH else error[:MAX_ERROR_LENGTH] + "..."
            self.enable_error_label.setText(f"Failed to enable: {display_error}")
            self.enable_error_label.setToolTip(f"Failed to enable: {error}")
        else:
            # Spinup succeeded - ensure worker reference is set and signals connected
            # Bug fix: Set worker reference after spinup succeeds
            # Without this, test connection fails with "Host not enabled"
            if not self.worker:
                self.worker = self.worker_manager.get_worker(self.host_id)
                if self.worker:
                    self._connect_worker_signals()
                else:
                    from src.utils.logger import log
                    log(f"Worker spinup succeeded but get_worker returned None for {self.host_id}", level="warning", category="file_hosts")

            self._update_enable_button_state(True)
            self.enable_error_label.setText("")
            self.enable_error_label.setToolTip("")

            # UPDATE CACHED VALUE - Critical for stale cache bug fix
            self.saved_enabled = True



    def _load_storage_from_cache(self):
        """Load and display storage from cache if available"""
        if not self.storage_bar:
            return

        # Read from QSettings cache directly (same as File Hosts tab)
        # Bug fix: Use QSettings instead of worker cache to avoid dependency on worker existence
        total_str = self.settings.value(f"FileHosts/{self.host_id}/storage_total", "0")
        left_str = self.settings.value(f"FileHosts/{self.host_id}/storage_left", "0")

        try:
            total = int(total_str) if total_str else 0
            left = int(left_str) if left_str else 0
        except (ValueError, TypeError) as e:
            from src.utils.logger import log
            log(f"Failed to parse cached storage for {self.host_id}: {e}", level="debug", category="file_hosts")
            return

        # Only update if we have valid cached data
        if total == 0 and left == 0:
            from src.utils.logger import log
            log(f"No cached storage data for {self.host_id}", level="debug", category="file_hosts")
            return

        if total <= 0 or left < 0 or left > total:
            from src.utils.logger import log
            log(f"Invalid cached storage for {self.host_id}: total={total}, left={left}", level="warning", category="file_hosts")
            return

        # Calculate percentages
        used = total - left
        percent_used = int((used / total) * 100) if total > 0 else 0
        percent_free = 100 - percent_used

        # Format with already-imported format_binary_size
        total_str = format_binary_size(total)
        left_str = format_binary_size(left)

        self.storage_bar.setValue(percent_free)
        self.storage_bar.setFormat(f"{left_str} / {total_str} free ({percent_free}%)")

        if percent_used >= 90:
            self.storage_bar.setProperty("storage_status", "low")
        elif percent_used >= 75:
            self.storage_bar.setProperty("storage_status", "medium")
        else:
            self.storage_bar.setProperty("storage_status", "plenty")

        self.storage_bar.style().unpolish(self.storage_bar)
        self.storage_bar.style().polish(self.storage_bar)

    def load_and_display_test_results(self):
        """Load and display existing test results from QSettings cache"""
        # Read directly from QSettings - doesn't require worker to exist
        prefix = f"FileHosts/TestResults/{self.host_id}"
        test_results = {
            'timestamp': self.settings.value(f"{prefix}/timestamp", 0, type=int),
            'credentials_valid': self.settings.value(f"{prefix}/credentials_valid", False, type=bool),
            'user_info_valid': self.settings.value(f"{prefix}/user_info_valid", False, type=bool),
            'upload_success': self.settings.value(f"{prefix}/upload_success", False, type=bool),
            'delete_success': self.settings.value(f"{prefix}/delete_success", False, type=bool),
            'error_message': self.settings.value(f"{prefix}/error_message", '', type=str)
        }

        if test_results['timestamp'] > 0:
            # Format timestamp as YYYY-MM-DD HH:MM
            test_time = datetime.fromtimestamp(test_results['timestamp'])
            time_str = test_time.strftime("%Y-%m-%d %H:%M")

            # Count passed tests
            tests = [
                test_results.get('credentials_valid'),
                test_results.get('user_info_valid'),
                test_results.get('upload_success'),
                test_results.get('delete_success')
            ]
            passed = sum(1 for t in tests if t)
            total = 4

            # Set timestamp with pass count and color
            timestamp_text = f"{time_str} ({passed}/{total} tests passed)"
            self.test_timestamp_label.setText(timestamp_text)

            # Use QSS classes for theme-aware styling
            if passed == total:
                self.test_timestamp_label.setProperty("class", "status-success")
            elif passed == 0:
                self.test_timestamp_label.setProperty("class", "status-error")
            else:
                self.test_timestamp_label.setProperty("class", "status-warning")
            self.test_timestamp_label.style().unpolish(self.test_timestamp_label)
            self.test_timestamp_label.style().polish(self.test_timestamp_label)

            # Set individual test labels with Pass/Fail/Unknown
            self._set_test_label(self.test_credentials_label, test_results.get('credentials_valid'))
            self._set_test_label(self.test_userinfo_label, test_results.get('user_info_valid'))
            self._set_test_label(self.test_upload_label, test_results.get('upload_success'))

            # Delete test can be skipped
            if test_results.get('delete_success'):
                self._set_test_label(self.test_delete_label, True)
            elif test_results.get('upload_success') and not test_results.get('delete_success'):
                self.test_delete_label.setText("Unknown")
                # Use QSS class for theme-aware styling
                self.test_delete_label.setProperty("class", "status-warning-light")
                self.test_delete_label.style().unpolish(self.test_delete_label)
                self.test_delete_label.style().polish(self.test_delete_label)
            else:
                self._set_test_label(self.test_delete_label, False)

            if test_results.get('error_message'):
                self.test_error_label.setText(test_results['error_message'])
            else:
                self.test_error_label.setText("")

    def _set_test_label(self, label, passed: Optional[bool]):
        """Helper to set test label with color"""
        # Use QSS classes for theme-aware styling
        if passed is True:
            label.setText("Pass")
            label.setProperty("class", "status-success")
        elif passed is False:
            label.setText("Fail")
            label.setProperty("class", "status-error")
        else:
            label.setText("Unknown")
            label.setProperty("class", "status-warning-light")
        label.style().unpolish(label)
        label.style().polish(label)

    def run_full_test(self):
        """Run complete test sequence via worker: credentials, user info, upload, delete"""
        # Warn about unsaved changes
        if not self._check_unsaved_changes("Testing connection"):
            return

        # Get credentials from multi-field layout
        credentials = self.get_credentials()
        if not credentials:
            self.test_timestamp_label.setText("Error: No credentials entered")
            # Use QSS class for theme-aware styling
            self.test_timestamp_label.setProperty("class", "status-error")
            self.test_timestamp_label.style().unpolish(self.test_timestamp_label)
            self.test_timestamp_label.style().polish(self.test_timestamp_label)
            return

        # Check if worker available
        if not self.worker:
            self.test_timestamp_label.setText("Error: Host not enabled")
            # Use QSS class for theme-aware styling
            self.test_timestamp_label.setProperty("class", "status-error")
            self.test_timestamp_label.style().unpolish(self.test_timestamp_label)
            self.test_timestamp_label.style().polish(self.test_timestamp_label)
            return

        # Update UI to show testing
        self.test_connection_btn.setEnabled(False)
        self.test_timestamp_label.setText("Testing...")
        self.test_credentials_label.setText("⏳ Running...")
        self.test_userinfo_label.setText("⏳ Waiting...")
        self.test_upload_label.setText("⏳ Waiting...")
        self.test_delete_label.setText("⏳ Waiting...")
        self.test_error_label.setText("")

        # Queue test request to be processed in worker's run() loop (non-blocking)
        # This ensures test executes in worker thread context where it belongs
        self.worker.queue_test_request(credentials)

    def _on_worker_test_completed(self, host_id: str, results: dict):
        """Handle test completion from worker"""
        if host_id != self.host_id:
            return  # Not for us

        # Re-enable button
        self.test_connection_btn.setEnabled(True)

        # Update UI from results
        self._set_test_label(
            self.test_credentials_label,
            results.get('credentials_valid', False)
        )
        self._set_test_label(
            self.test_userinfo_label,
            results.get('user_info_valid', False)
        )
        self._set_test_label(
            self.test_upload_label,
            results.get('upload_success', False)
        )
        self._set_test_label(
            self.test_delete_label,
            results.get('delete_success', False)
        )

        # Show error if any
        error_msg = results.get('error_message', '')
        self.test_error_label.setText(error_msg)

        # Update timestamp
        test_time = datetime.fromtimestamp(results['timestamp'])
        time_str = test_time.strftime("%Y-%m-%d %H:%M")

        tests_passed = sum([
            results.get('credentials_valid', False),
            results.get('user_info_valid', False),
            results.get('upload_success', False),
            results.get('delete_success', False)
        ])

        self.test_timestamp_label.setText(f"{time_str} ({tests_passed}/4 tests passed)")

        # Use QSS classes for theme-aware styling
        if tests_passed == 4:
            self.test_timestamp_label.setProperty("class", "status-success")
        elif tests_passed == 0:
            self.test_timestamp_label.setProperty("class", "status-error")
        else:
            self.test_timestamp_label.setProperty("class", "status-warning")
        self.test_timestamp_label.style().unpolish(self.test_timestamp_label)
        self.test_timestamp_label.style().polish(self.test_timestamp_label)

    def _on_worker_storage_updated(self, host_id: str, total, left):
        """Handle storage update from worker"""
        if host_id != self.host_id or not self.storage_bar:
            return  # Not for us

        # Update storage bar
        used = total - left
        percent_used = int((used / total) * 100) if total > 0 else 0
        percent_free = 100 - percent_used

        total_str = format_binary_size(total)
        left_str = format_binary_size(left)

        self.storage_bar.setValue(percent_free)
        self.storage_bar.setFormat(f"{left_str} / {total_str} free ({percent_free}%)")

        if percent_used >= 90:
            self.storage_bar.setProperty("storage_status", "low")
        elif percent_used >= 75:
            self.storage_bar.setProperty("storage_status", "medium")
        else:
            self.storage_bar.setProperty("storage_status", "plenty")

    def _update_metrics_display(self):
        """Update metrics grid labels from MetricsStore."""
        try:
            from src.utils.metrics_store import get_metrics_store

            store = get_metrics_store()
            if not store:
                return

            # Get metrics for all three periods
            session = store.get_session_metrics(self.host_id) or {}
            today = store.get_aggregated_metrics(self.host_id, 'today') or {}
            all_time = store.get_aggregated_metrics(self.host_id, 'all_time') or {}

            periods = [
                ('session', session),
                ('today', today),
                ('alltime', all_time)
            ]

            # Update all metric labels
            for period_key, metrics in periods:
                # Uploaded bytes
                bytes_val = metrics.get('bytes_uploaded', 0)
                bytes_text = format_binary_size(bytes_val) if bytes_val > 0 else "--"
                self._metric_labels[f'bytes_{period_key}'].setText(bytes_text)

                # Files uploaded
                files_val = metrics.get('files_uploaded', 0)
                files_text = str(files_val) if files_val > 0 else "--"
                self._metric_labels[f'files_{period_key}'].setText(files_text)

                # Avg Speed (convert bytes/s to KiB/s)
                avg_speed = metrics.get('avg_speed', 0)
                avg_text = format_binary_rate(avg_speed / 1024) if avg_speed > 0 else "--"
                self._metric_labels[f'avg_speed_{period_key}'].setText(avg_text)

                # Peak Speed (convert bytes/s to KiB/s)
                peak_speed = metrics.get('peak_speed', 0)
                peak_text = format_binary_rate(peak_speed / 1024) if peak_speed > 0 else "--"
                self._metric_labels[f'peak_speed_{period_key}'].setText(peak_text)

                # Success Rate
                success_rate = metrics.get('success_rate', 0)
                files_uploaded = metrics.get('files_uploaded', 0)
                files_failed = metrics.get('files_failed', 0)
                total_files = files_uploaded + files_failed

                if total_files > 0:
                    success_text = f"{success_rate:.1f}%"
                else:
                    success_text = "--"
                self._metric_labels[f'success_{period_key}'].setText(success_text)

        except Exception as e:
            from src.utils.logger import log
            log(f"Failed to update metrics display: {e}", level="warning", category="file_hosts")
            # Set all labels to error state
            for label in self._metric_labels.values():
                label.setText("--")

    def get_trigger_settings(self):
        """Get trigger setting from dropdown as single string value"""
        # Return saved value if dialog already closed, otherwise read from widget
        if hasattr(self, 'saved_trigger'):
            return self.saved_trigger

        selected_trigger = self.trigger_combo.currentData()
        # Return the trigger string ("disabled", "on_added", "on_started", "on_completed")
        return selected_trigger if selected_trigger else "disabled"

    def get_credentials(self):
        """Get entered credentials from multi-field layout.

        Returns credential string in format:
        - "api_key" for API key only hosts
        - "username:password" for session/token_login hosts
        - "api_key|username:password" for mixed auth hosts
        """
        # Return saved value if dialog already closed
        if hasattr(self, 'saved_credentials'):
            return self.saved_credentials

        # Build credentials from dynamic fields based on auth type
        if self.host_config.auth_type in ["api_key", "bearer"]:
            # API key only
            if self.creds_api_key_input:
                api_key = self.creds_api_key_input.text().strip()
                return api_key if api_key else None
            return None

        elif self.host_config.auth_type == "mixed":
            # Both API key and username/password
            api_key = self.creds_api_key_input.text().strip() if self.creds_api_key_input else ""
            username = self.creds_username_input.text().strip() if self.creds_username_input else ""
            password = self.creds_password_input.text().strip() if self.creds_password_input else ""

            # Build mixed format: api_key|username:password
            if api_key and username and password:
                return f"{api_key}|{username}:{password}"
            elif api_key:
                return api_key  # Partial: API key only
            elif username and password:
                return f"{username}:{password}"  # Partial: session only
            return None

        else:
            # Username and password only (token_login, session, etc.)
            if self.creds_username_input and self.creds_password_input:
                username = self.creds_username_input.text().strip()
                password = self.creds_password_input.text().strip()
                if username and password:
                    return f"{username}:{password}"
            return None


    def get_enabled_state(self):
        """Get enabled checkbox state"""
        # Return saved value if dialog already closed, otherwise read from widget
        if hasattr(self, 'saved_enabled'):
            return self.saved_enabled

        return self.worker_manager.is_enabled(self.host_id) if self.worker_manager else False

    def _load_initial_logs(self):
        """Load existing worker logs from file (called once on dialog open).

        Limits to 100 most recent entries from current session to prevent memory bloat.
        """
        try:
            from src.utils.logging import get_logger
            logger = get_logger()
            log_content = logger.read_current_log()

            # Find most recent "GUI loaded" to mark session start
            lines = log_content.splitlines()
            session_start_index = None
            for i in range(len(lines) - 1, -1, -1):  # Search backwards
                if "GUI loaded" in lines[i]:
                    session_start_index = i
                    break

            # Only process lines from session start onwards (or last 1000 if no marker)
            if session_start_index is not None:
                lines = lines[session_start_index:]
            else:
                lines = lines[-1000:]  # Fallback limit to prevent unbounded loading

            # Filter for this worker's messages (limit to most recent 100)
            worker_identifier = f"{self.host_config.name} Worker"
            matching_lines = [line for line in lines if worker_identifier in line]

            # Take only last 100 (most recent) and insert in reverse order (newest first)
            for line in matching_lines[-100:]:
                # Strip log level prefixes and category tags for cleaner display
                cleaned_line = line.replace("DEBUG: ", "").replace("[file_hosts] ", "")
                self.log_list.insertItem(0, cleaned_line)  # Most recent at top
        except Exception:
            pass  # Silent fail if logging disabled

    def _add_log(self, level: str, message: str):
        """Add new log message from worker signal"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # Replace escaped newlines with actual newlines for proper display
        message = message.replace("\\n", "\n")
        self.log_list.insertItem(0, f"{timestamp} {message}")

        # Limit to 100 entries
        while self.log_list.count() > 100:
            self.log_list.takeItem(100)

    def _connect_worker_signals(self):
        """Connect to worker signals (disconnects first to prevent duplicates).

        This method is idempotent - safe to call multiple times.
        Used in both constructor (initial connection) and spinup callback (reconnection to new worker).
        """
        if not self.worker:
            return

        # Disconnect old connections (prevents duplicate signal connections)
        try:
            self.worker.log_message[str, str].disconnect(self._add_log)
        except TypeError:
            pass  # Not connected yet

        try:
            self.worker.test_completed.disconnect(self._on_worker_test_completed)
        except TypeError:
            pass  # Not connected yet

        try:
            self.worker.storage_updated.disconnect(self._on_worker_storage_updated)
        except TypeError:
            pass  # Not connected yet

        # Connect to current worker with explicit QueuedConnection
        self.worker.log_message[str, str].connect(self._add_log, Qt.ConnectionType.QueuedConnection)
        self.worker.test_completed.connect(self._on_worker_test_completed, Qt.ConnectionType.QueuedConnection)
        self.worker.storage_updated.connect(self._on_worker_storage_updated, Qt.ConnectionType.QueuedConnection)

    def _mark_dirty(self):
        """Mark dialog as having unsaved changes"""
        self.has_unsaved_changes = True
        self.apply_btn.setEnabled(True)

    def _adjust_bbcode_height(self):
        """Adjust BBCode format text edit height based on content (1-3 lines)."""
        doc = self.bbcode_format_edit.document()
        line_count = doc.blockCount()
        line_height = self.bbcode_format_edit.fontMetrics().lineSpacing()
        # Clamp between 1 and 3 lines
        visible_lines = max(1, min(3, line_count))
        new_height = line_height * visible_lines + 12  # 12px for padding/margins
        self.bbcode_format_edit.setFixedHeight(new_height)

    def _check_unsaved_changes(self, action_name: str) -> bool:
        """Check for unsaved changes and warn user.

        Returns:
            True if should proceed (no changes or user confirmed), False otherwise
        """
        if not self.has_unsaved_changes:
            return True

        from PyQt6.QtWidgets import QMessageBox
        reply = QMessageBox.warning(
            self,
            "Unsaved Changes",
            f"You have unsaved changes. {action_name} will use the currently saved settings.\n\n"
            f"Click 'Apply' first to use the new settings, or click 'Proceed' to continue with saved settings.",
            QMessageBox.StandardButton.Apply | QMessageBox.StandardButton.Cancel |
            QMessageBox.StandardButton.Yes,  # Yes = "Proceed"
            QMessageBox.StandardButton.Apply
        )

        if reply == QMessageBox.StandardButton.Apply:
            self._on_apply_clicked()  # Apply changes then proceed
            return True
        elif reply == QMessageBox.StandardButton.Yes:  # Proceed without applying
            return True
        else:  # Cancel
            return False

    def _on_apply_clicked(self):
        """Apply changes without closing dialog.

        Saves credentials to encrypted storage and trigger settings to INI file.
        Only resets dirty flag if all operations succeed. Reports granular errors
        to distinguish partial vs complete failures.
        """
        from PyQt6.QtWidgets import QMessageBox

        # Disable Apply button during save to prevent rapid clicks
        self.apply_btn.setEnabled(False)
        errors = []  # Collect all errors for granular reporting

        # Save credentials from multi-field layout (separate try-except)
        credentials = self.get_credentials()  # Use get_credentials() to build from fields
        if credentials:
                try:
                    # Bug fix: Correct function name is set_credential, not store_credential
                    from imxup import set_credential, encrypt_password
                    encrypted = encrypt_password(credentials)
                    set_credential(f"file_host_{self.host_id}_credentials", encrypted)

                    # Update worker with new credentials (thread-safe via signal)
                    if self.worker:
                        self.worker.credentials_update_requested.emit(credentials)
                except (ValueError, TypeError) as e:
                    errors.append(f"Credentials encryption failed: {str(e)}")
                except IOError as e:
                    errors.append(f"Credentials storage failed: {str(e)}")
                except Exception as e:
                    errors.append(f"Credentials: {str(e)}")

        # Save trigger settings to INI (separate try-except)
        try:
            from src.core.file_host_config import save_file_host_setting

            selected = self.trigger_combo.currentData()
            trigger_value = selected if selected else "disabled"
            save_file_host_setting(self.host_id, "trigger", trigger_value)
        except IOError as e:
            errors.append(f"Trigger settings file I/O failed: {str(e)}")
        except Exception as e:
            errors.append(f"Trigger settings: {str(e)}")

        # Save host settings to INI (separate try-except for granular error reporting)
        try:
            from src.core.file_host_config import save_file_host_setting

            # Save each setting individually
            save_file_host_setting(self.host_id, "auto_retry", self.auto_retry_check.isChecked())
            save_file_host_setting(self.host_id, "max_retries", self.max_retries_spin.value())
            save_file_host_setting(self.host_id, "max_connections", self.max_connections_spin.value())

            # Handle nullable max_file_size_mb (0 = None)
            file_size_value = self.max_file_size_spin.value()
            save_file_host_setting(self.host_id, "max_file_size_mb", file_size_value if file_size_value > 0 else None)

            # Save timeout settings
            save_file_host_setting(self.host_id, "inactivity_timeout", self.inactivity_timeout_spin.value())

            # Handle nullable upload_timeout (0 = None)
            upload_timeout_value = self.upload_timeout_spin.value()
            save_file_host_setting(self.host_id, "upload_timeout", upload_timeout_value if upload_timeout_value > 0 else None)

            # Save BBCode format (empty string if not set)
            bbcode_format_value = self.bbcode_format_edit.toPlainText().strip()
            save_file_host_setting(self.host_id, "bbcode_format", bbcode_format_value if bbcode_format_value else "")

        except IOError as e:
            errors.append(f"Host settings file I/O failed: {str(e)}")
        except Exception as e:
            errors.append(f"Host settings: {str(e)}")

        # Handle results
        if errors:
            # Partial or complete failure - keep dirty flag and re-enable Apply for retry
            self.apply_btn.setEnabled(True)
            error_details = "\n".join(f"• {err}" for err in errors)
            QMessageBox.critical(
                self,
                "Save Failed",
                f"Failed to save the following settings:\n\n{error_details}\n\n"
                f"Your changes have been only partially applied. Please try again or check logs for details.",
                QMessageBox.StandardButton.Ok
            )
            from src.utils.logger import log
            log(f"Failed to apply settings for {self.host_id}: {errors}", level="error", category="file_hosts")
        else:
            # Complete success - mark clean and leave button disabled
            self.has_unsaved_changes = False
            self.apply_btn.setEnabled(False)

            # UPDATE CACHED VALUES - Critical fix for stale cache bug!
            # Parent widget calls get_*() methods which return these cached values.
            # If we don't update them, parent will overwrite INI with stale data.
            # Update cached credentials from multi-field layout
            self.saved_credentials = self.get_credentials()

            selected = self.trigger_combo.currentData()
            self.saved_trigger = selected if selected else "disabled"

            # saved_enabled is updated by enable button click, not here
            # (enable button directly calls worker_manager.enable/disable_host)

            #QMessageBox.information(self, "Settings Applied", "Settings have been applied successfully.", QMessageBox.StandardButton.Ok)

    def _on_save_clicked(self):
        """Handle Save button click - apply changes and close"""
        self._on_apply_clicked()  # Apply changes first
        self.accept()  # Then close

    def accept(self):
        """Override accept to prevent double-saving (values already saved in _on_save_clicked)"""
        # Just close the dialog, values were already saved by _on_save_clicked
        super().accept()

    def closeEvent(self, event):
        """Clean up signal connections when dialog closes"""
        # Check for unsaved changes before closing
        if self.has_unsaved_changes:
            from PyQt6.QtWidgets import QMessageBox
            reply = QMessageBox.warning(
                self,
                "Unsaved Changes",
                "You have unsaved changes. Do you want to save them before closing?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save
            )

            if reply == QMessageBox.StandardButton.Save:
                self._on_apply_clicked()  # Save changes
                # Only close if save succeeded (no errors)
                if self.has_unsaved_changes:
                    event.ignore()  # Save failed, don't close
                    return
            elif reply == QMessageBox.StandardButton.Cancel:
                event.ignore()  # User canceled, don't close
                return
            # Discard falls through to close normally

        # Disconnect ALL worker signals to prevent multiple connections if dialog reopened
        if self.worker:
            try:
                self.worker.log_message[str, str].disconnect(self._add_log)
            except TypeError:
                pass  # Already disconnected or never connected

            try:
                self.worker.test_completed.disconnect(self._on_worker_test_completed)
            except TypeError:
                pass

            try:
                self.worker.storage_updated.disconnect(self._on_worker_storage_updated)
            except TypeError:
                pass

        # Disconnect manager signal
        if self.worker_manager:
            try:
                self.worker_manager.spinup_complete.disconnect(self._on_spinup_complete)
            except TypeError:
                pass  # Already disconnected or never connected

        # Save splitter state to preserve user's layout preference
        settings = QSettings("ImxUploader", "ImxUploadGUI")
        settings.setValue(f"FileHostConfigDialog/{self.host_id}/splitter_state", self.content_splitter.saveState())

        super().closeEvent(event)
