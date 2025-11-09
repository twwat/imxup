#!/usr/bin/env python3
"""File Hosts Settings Widget - Multi-host upload configuration"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QPushButton,
    QLineEdit, QCheckBox, QFrame, QProgressBar, QScrollArea, QGroupBox,
    QSpinBox, QMessageBox, QFileDialog, QDialog
)
from PyQt6.QtCore import pyqtSignal, QSettings, Qt
from PyQt6.QtGui import QFont, QPixmap
from datetime import datetime
from typing import Dict, Any, Optional

from src.utils.format_utils import format_binary_size
from src.core.file_host_config import get_config_manager, HostConfig
from src.gui.icon_manager import get_icon_manager


class FileHostsSettingsWidget(QWidget):
    """Widget for configuring file host settings - PASSIVE: only displays and collects data"""
    settings_changed = pyqtSignal()  # Notify parent of unsaved changes

    def __init__(self, parent, worker_manager):
        """Initialize file hosts settings widget.

        Args:
            parent: Parent settings dialog
            worker_manager: FileHostWorkerManager instance
        """
        super().__init__(parent)
        self.parent_dialog = parent
        self.worker_manager = worker_manager
        self.settings = QSettings("ImxUploader", "ImxUploadGUI")
        self.host_widgets: Dict[str, Dict[str, Any]] = {}

        # Icon manager for status icons
        self.icon_manager = get_icon_manager()

        # Track storage load state
        self.storage_loaded_this_session = False

        # Connect to manager signals for real-time updates
        if self.worker_manager:
            self.worker_manager.storage_updated.connect(self._on_storage_updated)
            self.worker_manager.enabled_workers_changed.connect(self._on_enabled_workers_changed)

        self.setup_ui()

    def setup_ui(self):
        """Setup the file hosts settings UI"""
        layout = QVBoxLayout(self)

        # Intro text
        intro_label = QLabel(
            "Configure file hosts. Galleries will be uploaded to enabled hosts "
            "as ZIP files (automatically or manually, as per settings)"
        )
        intro_label.setWordWrap(True)
        layout.addWidget(intro_label)

        # Connection Limits Group
        limits_group = QGroupBox("Connection Limits")
        limits_layout = QFormLayout(limits_group)

        self.global_limit_spin = QSpinBox()
        self.global_limit_spin.setMinimum(1)
        self.global_limit_spin.setMaximum(10)
        self.global_limit_spin.setToolTip(
            "Maximum total concurrent file host uploads across all hosts"
        )
        # Block signals during initial value set, then connect
        self.global_limit_spin.blockSignals(True)
        self.global_limit_spin.setValue(3)
        self.global_limit_spin.blockSignals(False)
        self.global_limit_spin.valueChanged.connect(lambda: self.settings_changed.emit())
        limits_layout.addRow("Global upload limit:", self.global_limit_spin)

        self.per_host_limit_spin = QSpinBox()
        self.per_host_limit_spin.setMinimum(1)
        self.per_host_limit_spin.setMaximum(5)
        self.per_host_limit_spin.setToolTip(
            "Maximum concurrent uploads per individual host"
        )
        # Block signals during initial value set, then connect
        self.per_host_limit_spin.blockSignals(True)
        self.per_host_limit_spin.setValue(2)
        self.per_host_limit_spin.blockSignals(False)
        self.per_host_limit_spin.valueChanged.connect(lambda: self.settings_changed.emit())
        limits_layout.addRow("Per-host limit:", self.per_host_limit_spin)

        layout.addWidget(limits_group)

        # Available Hosts Group
        hosts_group = QGroupBox("Available Hosts")
        hosts_layout = QVBoxLayout(hosts_group)

        # Create scrollable area for hosts list
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)  # Remove scroll area border
        scroll_area.setMinimumHeight(200)

        hosts_container = QWidget()
        self.hosts_container_layout = QVBoxLayout(hosts_container)
        self.hosts_container_layout.setSpacing(8)  # Increased spacing for better separation

        # Load hosts and create UI
        config_manager = get_config_manager()
        for host_id, host_config in config_manager.hosts.items():
            self._create_host_row(host_id, host_config)

        self.hosts_container_layout.addStretch()
        scroll_area.setWidget(hosts_container)
        hosts_layout.addWidget(scroll_area)

        # Add custom host button
        add_custom_btn = QPushButton("+ Add Custom Host")
        add_custom_btn.setToolTip("Add a custom host configuration from JSON file")
        add_custom_btn.clicked.connect(self._add_custom_host)
        hosts_layout.addWidget(add_custom_btn)

        layout.addWidget(hosts_group)

        # Load initial storage for enabled hosts
        self._load_initial_storage()

    def _create_host_row(self, host_id: str, host_config):
        """Create UI row for a single host.

        Args:
            host_id: Host identifier
            host_config: HostConfig instance
        """
        # Container frame
        host_frame = QFrame()
        host_frame.setFrameShape(QFrame.Shape.StyledPanel)
        host_frame.setFrameShadow(QFrame.Shadow.Raised)
        frame_layout = QVBoxLayout(host_frame)
        frame_layout.setContentsMargins(8, 8, 8, 8)
        frame_layout.setSpacing(4)

        # Top row: Status indicator + Configure button
        top_row = QHBoxLayout()

        # Status indicator (enabled/disabled) - icon set by _update_status_icon
        status_icon = QLabel()
        status_icon.setFixedWidth(20)
        status_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top_row.addWidget(status_icon)

        host_label = QLabel(host_config.name)
        # Apply class based on enabled/disabled state - let QSS handle all styling
        from src.core.file_host_config import get_file_host_setting
        host_enabled = get_file_host_setting(host_id, "enabled", "bool")
        if not host_enabled:
            host_label.setProperty("class", "host-name-disabled")
        else:
            host_label.setProperty("class", "host-name-enabled")
        # Force style refresh
        host_label.style().unpolish(host_label)
        host_label.style().polish(host_label)
        top_row.addWidget(host_label)

        # Host logo (if available) - centered with spacing
        logo_label = self._load_host_logo(host_id, host_config)
        if logo_label:
            top_row.addStretch(1)  # Push logo toward center
            top_row.addWidget(logo_label)
            top_row.addStretch(1)  # Balance on the right side

        # Test status label
        status_label = QLabel()
        self._update_status_label(host_id, host_config, status_label)
        top_row.addWidget(status_label)

        top_row.addStretch()
        frame_layout.addLayout(top_row)

        # Storage progress bar (moved up - was after auto-upload before)
        storage_bar = None
        if host_config.user_info_url and (host_config.storage_left_path or host_config.storage_regex):
            storage_row = QHBoxLayout()

            storage_label_text = QLabel("Storage:")
            # Use QSS class for theme-aware styling
            storage_label_text.setProperty("class", "label-small-muted")
            storage_label_text.setFixedWidth(80)
            storage_row.addWidget(storage_label_text)

            storage_bar = QProgressBar()
            storage_bar.setMaximum(100)
            storage_bar.setValue(0)
            storage_bar.setTextVisible(True)
            storage_bar.setFormat("Loading...")
            storage_bar.setMaximumHeight(16)
            storage_bar.setProperty("class", "storage-bar")
            storage_row.addWidget(storage_bar, 1)

            frame_layout.addLayout(storage_row)

        # Button row (Enable/Disable + Configure) for hosts that require auth
        enable_btn = None
        if host_config.requires_auth:
            button_row = QHBoxLayout()
            button_row.addSpacing(80)  # Align with labels above

            # Enable/Disable button with theme-specific styling
            enable_btn = QPushButton()
            enable_btn.setMinimumWidth(80)
            enable_btn.setMaximumWidth(80)
            enable_btn.clicked.connect(lambda checked=False, hid=host_id: self._on_enable_disable_clicked(hid))
            button_row.addWidget(enable_btn)

            # Configure button
            configure_btn = QPushButton("Configure")
            configure_btn.setToolTip(f"Configure {host_config.name}")
            configure_btn.clicked.connect(lambda: self._show_host_config_dialog(host_id, host_config))
            configure_btn.setMaximumWidth(80)
            button_row.addWidget(configure_btn)

            button_row.addStretch()

            frame_layout.addLayout(button_row)

        # Auto-upload display (read-only text)
        trigger_display = self._get_trigger_display_text(host_id)
        if trigger_display:
            trigger_row = QHBoxLayout()
            trigger_label = QLabel("Auto-upload:")
            # Use QSS class for theme-aware styling
            trigger_label.setProperty("class", "label-small-muted")
            trigger_label.setFixedWidth(80)
            trigger_row.addWidget(trigger_label)

            trigger_value = QLabel(trigger_display)
            # Use QSS class for theme-aware styling
            trigger_value.setProperty("class", "label-small")
            trigger_row.addWidget(trigger_value)
            trigger_row.addStretch()
            frame_layout.addLayout(trigger_row)

        # Store widgets for later access (display-only UI)
        self.host_widgets[host_id] = {
            "frame": host_frame,
            "status_icon": status_icon,
            "status_label": status_label,
            "storage_bar": storage_bar,
            "host_label": host_label,  # Store for theme updates
            "enable_btn": enable_btn if host_config.requires_auth else None
        }

        # Load cached storage immediately for this host
        self.refresh_storage_display(host_id)

        # Update enable button state
        if host_config.requires_auth:
            self._update_enable_button_state(host_id)

        # Update status icon to reflect current enabled state
        self._update_status_icon(host_id)

        # Add to layout
        self.hosts_container_layout.addWidget(host_frame)

    def _load_host_logo(self, host_id: str, host_config: HostConfig) -> Optional[QLabel]:
        """Load and create a clickable QLabel with the host's logo.

        Args:
            host_id: Host identifier (used to find logo file)
            host_config: HostConfig instance (for referral URL)

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

            # Scale logo to max height of 24px while maintaining aspect ratio
            scaled_pixmap = pixmap.scaledToHeight(24, Qt.TransformationMode.SmoothTransformation)

            logo_label = QLabel()
            logo_label.setPixmap(scaled_pixmap)
            logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

            # Make clickable if referral URL exists
            if host_config.referral_url:
                from PyQt6.QtGui import QCursor
                logo_label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
                logo_label.setToolTip(f"Click to visit {host_config.name}")

                # Install event filter to detect clicks
                def open_referral_url(event):
                    if event.type() == event.Type.MouseButtonPress:
                        from PyQt6.QtGui import QDesktopServices
                        from PyQt6.QtCore import QUrl
                        QDesktopServices.openUrl(QUrl(host_config.referral_url))
                        return True
                    return False

                logo_label.mousePressEvent = open_referral_url

            return logo_label
        except Exception:
            return None

    def _update_status_icon(self, host_id: str):
        """Update status icon pixmap based on enabled state and theme.

        Args:
            host_id: Host identifier
        """
        widgets = self.host_widgets.get(host_id)
        if not widgets or not widgets.get('status_icon'):
            return

        status_icon = widgets['status_icon']

        # Get current enabled state from worker_manager (source of truth)
        is_enabled = self.worker_manager.is_enabled(host_id) if self.worker_manager else False

        # Get appropriate icon (IconManager auto-detects theme from palette)
        icon_key = 'host_enabled' if is_enabled else 'host_disabled'
        icon = self.icon_manager.get_icon(icon_key, theme_mode=None)  # None = auto-detect

        # Set pixmap (20x20 size)
        pixmap = icon.pixmap(20, 20)
        status_icon.setPixmap(pixmap)

        # Set tooltip
        tooltip = "Host enabled" if is_enabled else "Host disabled"
        status_icon.setToolTip(tooltip)

    def _update_status_label(self, host_id: str, host_config, status_label: QLabel):
        """Update status label with test results.

        Args:
            host_id: Host identifier
            host_config: HostConfig instance
            status_label: QLabel to update
        """
        if not host_config.requires_auth:
            status_label.setText("✓ No auth required")
            # Use QSS class for theme-aware styling
            status_label.setProperty("class", "status-success-light")
            status_label.style().unpolish(status_label)
            status_label.style().polish(status_label)
            return

        # Load test results directly from QSettings (works even if worker doesn't exist yet)
        test_results = self._load_test_results_from_settings(host_id)
        if test_results:
            test_time = datetime.fromtimestamp(test_results['timestamp'])
            time_str = test_time.strftime("%m/%d %H:%M")

            # Count how many tests passed (out of 4)
            tests_passed = sum([
                test_results['credentials_valid'],
                test_results['user_info_valid'],
                test_results['upload_success'],
                test_results['delete_success']
            ])

            if tests_passed == 4:
                status_label.setText(f"✓ All tests passed ({time_str})")
                # Use QSS class for theme-aware styling
                status_label.setProperty("class", "status-success")
            elif tests_passed > 0:
                status_label.setText(f"⚠ {tests_passed}/4 tests passed ({time_str})")
                # Use QSS class for theme-aware styling
                status_label.setProperty("class", "status-warning")
            else:
                status_label.setText("⚠ Test failed - retest needed")
                # Use QSS class for theme-aware styling
                status_label.setProperty("class", "status-error")
            status_label.style().unpolish(status_label)
            status_label.style().polish(status_label)
            return

        status_label.setText("⚠ Requires credentials")
        # Use QSS class for theme-aware styling
        status_label.setProperty("class", "status-warning-light")
        status_label.style().unpolish(status_label)
        status_label.style().polish(status_label)

    def _load_test_results_from_settings(self, host_id: str) -> Optional[dict]:
        """Load test results directly from QSettings.

        This is used at widget initialization when workers may not exist yet.

        Args:
            host_id: Host identifier

        Returns:
            Dictionary with test results, or None if no results exist
        """
        prefix = f"FileHosts/TestResults/{host_id}"
        ts = self.settings.value(f"{prefix}/timestamp", None, type=int)
        if not ts or ts == 0:
            return None

        return {
            'timestamp': ts,
            'credentials_valid': self.settings.value(f"{prefix}/credentials_valid", False, type=bool),
            'user_info_valid': self.settings.value(f"{prefix}/user_info_valid", False, type=bool),
            'upload_success': self.settings.value(f"{prefix}/upload_success", False, type=bool),
            'delete_success': self.settings.value(f"{prefix}/delete_success", False, type=bool),
            'error_message': self.settings.value(f"{prefix}/error_message", '', type=str)
        }

    def _get_trigger_display_text(self, host_id):
        """Get display text for auto-upload trigger (single string value)."""
        from src.core.file_host_config import get_file_host_setting
        trigger = get_file_host_setting(host_id, "trigger", "str")

        if trigger == "on_added":
            return "On Added"
        elif trigger == "on_started":
            return "On Started"
        elif trigger == "on_completed":
            return "On Completed"
        else:  # "disabled" or any other value
            return "Disabled"

    def _on_test_clicked(self, host_id: str):
        """Handle test button click - delegate to worker.

        Args:
            host_id: Host identifier
        """
        if not self.worker_manager:
            QMessageBox.warning(
                self,
                "Not Available",
                "Worker manager not available"
            )
            return

        worker = self.worker_manager.get_worker(host_id)
        if not worker:
            QMessageBox.warning(
                self,
                "Not Enabled",
                "Please enable the host first to test it."
            )
            return

        # Update UI to show testing
        widgets = self.host_widgets.get(host_id, {})
        status_label = widgets.get('status_label')

        if status_label:
            status_label.setText("⏳ Test started - close and re-open settings to see results")
            # Use QSS class for theme-aware styling
            status_label.setProperty("class", "status-info")
            status_label.style().unpolish(status_label)
            status_label.style().polish(status_label)

        # Trigger test (result will be cached in QSettings)
        worker.test_connection()

    def refresh_storage_display(self, host_id: str):
        """Update storage display by reading from QSettings cache.

        Args:
            host_id: Host identifier
        """
        # Read from QSettings cache (written by worker as strings to avoid Qt 32-bit overflow)
        total_str = self.settings.value(f"FileHosts/{host_id}/storage_total", "0")
        left_str = self.settings.value(f"FileHosts/{host_id}/storage_left", "0")

        try:
            total = int(total_str) if total_str else 0
            left = int(left_str) if left_str else 0
        except (ValueError, TypeError):
            total = 0
            left = 0

        widgets = self.host_widgets.get(host_id, {})
        storage_bar = widgets.get('storage_bar')

        # Skip if no storage bar widget exists
        if not storage_bar:
            return

        # ONLY update if we have valid data - NEVER clear existing display
        if total == 0 and left == 0:
            # No cached data - keep current display unchanged
            # (Initial "Loading..." will stay until first successful update)
            return

        # Validate storage data before updating
        if total <= 0 or left < 0 or left > total:
            # Invalid data - keep current display unchanged (preserve existing good data)
            return

        # Calculate percentages
        used = total - left
        percent_used = int((used / total) * 100) if total > 0 else 0
        percent_free = 100 - percent_used

        # Format strings
        left_str = format_binary_size(left)
        total_str = format_binary_size(total)

        # Update progress bar
        storage_bar.setValue(percent_free)
        storage_bar.setFormat(f"{left_str} / {total_str} free ({percent_free}%)")

        # Color coding based on usage
        if percent_used >= 90:
            storage_bar.setProperty("storage_status", "low")
        elif percent_used >= 75:
            storage_bar.setProperty("storage_status", "medium")
        else:
            storage_bar.setProperty("storage_status", "plenty")

        # Refresh styling
        storage_bar.style().unpolish(storage_bar)
        storage_bar.style().polish(storage_bar)


    def refresh_test_results(self, host_id: str):
        """Update test results display by reading from QSettings cache.

        Args:
            host_id: Host identifier
        """
        # Read from QSettings cache (written by worker) - CONSISTENT keys for all hosts
        prefix = f"FileHosts/TestResults/{host_id}"
        results = {
            "timestamp": self.settings.value(f"{prefix}/timestamp", 0.0, type=float),
            "credentials_valid": self.settings.value(f"{prefix}/credentials_valid", False, type=bool),
            "user_info_valid": self.settings.value(f"{prefix}/user_info_valid", False, type=bool),
            "upload_success": self.settings.value(f"{prefix}/upload_success", False, type=bool),
            "delete_success": self.settings.value(f"{prefix}/delete_success", False, type=bool),
            "error_message": self.settings.value(f"{prefix}/error_message", "", type=str)
        }
        if results["timestamp"] == 0.0:
            return  # No test results cached
        widgets = self.host_widgets.get(host_id, {})
        status_label = widgets.get('status_label')
        test_btn = widgets.get('test_btn')

        # Re-enable test button
        if test_btn:
            test_btn.setEnabled(True)

        if not status_label:
            return

        # Update status label
        test_time = datetime.fromtimestamp(results['timestamp'])
        time_str = test_time.strftime("%m/%d %H:%M")

        tests_passed = sum([
            results['credentials_valid'],
            results['user_info_valid'],
            results['upload_success'],
            results['delete_success']
        ])

        if tests_passed == 4:
            status_label.setText(f"✓ All tests passed ({time_str})")
            # Use QSS class for theme-aware styling
            status_label.setProperty("class", "status-success")
        elif tests_passed > 0:
            status_label.setText(f"⚠ {tests_passed}/4 tests passed ({time_str})")
            # Use QSS class for theme-aware styling
            status_label.setProperty("class", "status-warning")
        else:
            error = results.get('error_message', 'Unknown error')
            status_label.setText(f"✗ Test failed: {error}")
            # Use QSS class for theme-aware styling
            status_label.setProperty("class", "status-error")
        status_label.style().unpolish(status_label)
        status_label.style().polish(status_label)

    def _show_host_config_dialog(self, host_id: str, host_config):
        """Show detailed configuration dialog for a host.

        Args:
            host_id: Host identifier
            host_config: HostConfig instance
        """
        from src.gui.dialogs.file_host_config_dialog import FileHostConfigDialog

        # Get main widgets for this host
        main_widgets = self.host_widgets.get(host_id, {})

        # Create and show config dialog with worker_manager
        dialog = FileHostConfigDialog(self, host_id, host_config, main_widgets, self.worker_manager)
        result = dialog.exec()

        # Save changes if user clicked Save
        if result == QDialog.DialogCode.Accepted:
            try:
                from src.utils.logger import log
                log(f"Config dialog accepted for {host_id}", level="debug", category="file_hosts")

                from imxup import encrypt_password, set_credential
                import configparser
                import os

                # Get values from dialog
                enabled = dialog.get_enabled_state()
                credentials = dialog.get_credentials()
                trigger_value = dialog.get_trigger_settings()  # Now returns single string
                log(f"Got values: enabled={enabled}, has_creds={bool(credentials)}, trigger={trigger_value}",
                    level="debug", category="file_hosts")

                # Save enabled state and trigger using new API
                from src.core.file_host_config import save_file_host_setting
                save_file_host_setting(host_id, "enabled", enabled)
                save_file_host_setting(host_id, "trigger", trigger_value)
                log(f"Saved settings for {host_id}", level="info", category="file_hosts")

                # Save credentials (encrypted) to QSettings
                if credentials:
                    encrypted = encrypt_password(credentials)
                    set_credential(f"file_host_{host_id}_credentials", encrypted)
                    log("Saved encrypted credentials", level="debug", category="file_hosts")

                # Spawn or kill worker based on enabled state
                if enabled:
                    self.worker_manager.enable_host(host_id)
                else:
                    self.worker_manager.disable_host(host_id)

                # Refresh display in File Hosts tab
                self._refresh_host_display(host_id, host_config, credentials)
                log(f"Refreshed display for {host_id}", level="debug", category="file_hosts")

                # Mark settings as changed
                self.settings_changed.emit()
                log(f"Save complete for {host_id}", level="info", category="file_hosts")

            except Exception as e:
                log(f"Failed to save config for {host_id}: {e}", level="error", category="file_hosts")
                import traceback
                traceback.print_exc()

    def _refresh_host_display(self, host_id: str, host_config, credentials: Optional[str] = None):
        """Refresh display for a host after config changes.

        Args:
            host_id: Host identifier
            host_config: Updated HostConfig
            credentials: New credentials (optional)
        """
        widgets = self.host_widgets.get(host_id)
        if not widgets:
            return

        # Update credentials display if provided
        if credentials and widgets.get("creds_display"):
            widgets["creds_display"].setText(credentials)

        # Refresh status label and storage
        if widgets.get("status_label"):
            self._update_status_label(host_id, host_config, widgets["status_label"])

        self.refresh_storage_display(host_id)
    def _add_custom_host(self):
        """Add a custom host from JSON file"""
        # TODO: Implement custom host loading
        QMessageBox.information(
            self,
            "Not Implemented",
            "Custom host loading will be implemented in a future update."
        )

    def _load_initial_storage(self):
        """Load cached storage ONLY - no workers, no timers"""
        if self.storage_loaded_this_session:
            return

        # Just read from QSettings cache for ALL hosts (enabled or not)
        from src.core.file_host_config import get_config_manager
        config_manager = get_config_manager()

        for host_id in config_manager.hosts.keys():
            self.refresh_storage_display(host_id)
            self.refresh_test_results(host_id)

        self.storage_loaded_this_session = True


    def load_settings(self, settings: dict):
        """Refresh display from current config (display-only UI)."""
        # File Hosts tab is display-only - all data loaded in _create_host_row()
        # This method exists for compatibility but does nothing
        pass

    def get_settings(self) -> dict:
        """Get settings (display-only UI returns empty)."""
        # File Hosts tab is display-only - no settings to get
        # All editing happens in config dialog
        return {"global_limit": 3, "per_host_limit": 2, "hosts": {}}

    def _on_storage_updated(self, host_id: str, total: int, left: int):
        """Handle storage update signal from manager.

        Args:
            host_id: Host that was updated
            total: Total storage in bytes
            left: Free storage in bytes
        """
        # Refresh storage display for this host
        self.refresh_storage_display(host_id)

    def _on_enabled_workers_changed(self, enabled_hosts: list):
        """Handle enabled workers list change from manager.

        Args:
            enabled_hosts: List of enabled host IDs
        """
        # Update status labels and enable buttons for all hosts
        from src.core.file_host_config import get_config_manager
        config_manager = get_config_manager()

        for host_id, host_config in config_manager.hosts.items():
            widgets = self.host_widgets.get(host_id)
            if widgets and widgets.get('status_label'):
                self._update_status_label(host_id, host_config, widgets['status_label'])
            # Update enable button state
            if widgets and widgets.get('enable_btn'):
                self._update_enable_button_state(host_id)

    def _update_enable_button_state(self, host_id: str):
        """Update enable/disable button text and style based on worker state.

        Args:
            host_id: Host identifier
        """
        widgets = self.host_widgets.get(host_id)
        if not widgets or not widgets.get('enable_btn'):
            return

        enable_btn = widgets['enable_btn']
        is_enabled = self.worker_manager.is_enabled(host_id) if self.worker_manager else False

        # Use QSS classes for theme-aware styling (defined in styles.qss)
        if is_enabled:
            enable_btn.setText("Disable")
            enable_btn.setProperty("class", "host-disable-btn")
            enable_btn.style().unpolish(enable_btn)
            enable_btn.style().polish(enable_btn)
        else:
            enable_btn.setText("Enable")
            enable_btn.setProperty("class", "host-enable-btn")
            enable_btn.style().unpolish(enable_btn)
            enable_btn.style().polish(enable_btn)

        # Update host name label styling based on enabled state
        host_label = widgets.get('host_label')
        if host_label:
            if is_enabled:
                host_label.setProperty("class", "host-name-enabled")
            else:
                host_label.setProperty("class", "host-name-disabled")
            host_label.style().unpolish(host_label)
            host_label.style().polish(host_label)

        # Update status icon to match enabled state
        self._update_status_icon(host_id)

    def _on_enable_disable_clicked(self, host_id: str):
        """Handle enable/disable button click.

        Args:
            host_id: Host identifier
        """
        if not self.worker_manager:
            return

        is_enabled = self.worker_manager.is_enabled(host_id)

        if is_enabled:
            # Disable worker
            self.worker_manager.disable_host(host_id)
        else:
            # Enable worker (it will test credentials during spinup)
            self.worker_manager.enable_host(host_id)
