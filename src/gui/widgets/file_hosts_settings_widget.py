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
        """Create UI row for a single host using compact single-row layout.

        Args:
            host_id: Host identifier
            host_config: HostConfig instance
        """
        from PyQt6.QtWidgets import QSizePolicy
        from src.core.file_host_config import get_file_host_setting

        # Container frame
        host_frame = QFrame()
        host_frame.setFrameShape(QFrame.Shape.StyledPanel)
        host_frame.setFrameShadow(QFrame.Shadow.Raised)
        frame_layout = QHBoxLayout(host_frame)
        frame_layout.setContentsMargins(8, 4, 8, 4)  # Tighter vertical spacing
        frame_layout.setSpacing(8)

        # 1. Status Icon (20×20px) - enabled/disabled indicator
        status_icon = QLabel()
        status_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_icon.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        frame_layout.addWidget(status_icon)

        # 2. Logo Container (160px fixed width) - logos scaled to 28px height, centered
        logo_container = QWidget()
        logo_container.setFixedWidth(150)
        logo_container.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        logo_layout = QHBoxLayout(logo_container)
        logo_layout.setContentsMargins(0, 0, 0, 0)
        logo_layout.setSpacing(0)
        #logo_layout.addStretch()  # Center the logo

        logo_label = self._load_host_logo(host_id, host_config, height=22)
        if logo_label:
            logo_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            logo_layout.addWidget(logo_label)
        else:
            # Fallback: Show host name if no logo available
            fallback_label = QLabel(host_config.name)
            #fallback_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
            logo_layout.addWidget(fallback_label)

        #logo_layout.addStretch()  # Center the logo
        frame_layout.addWidget(logo_container)

        # 3. Configure Button (100px width) - for all hosts
        configure_btn = QPushButton("Configure")
        configure_btn.setFixedWidth(80)
        configure_btn.setToolTip(f"Configuration settings for {host_config.name}")
        configure_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        configure_btn.clicked.connect(lambda: self._show_host_config_dialog(host_id, host_config))
        frame_layout.addWidget(configure_btn)

        # 4. Storage Bar (expanding, shows amount free)
        storage_bar = None
        if host_config.user_info_url and (host_config.storage_left_path or host_config.storage_regex):
            storage_bar = QProgressBar()
            storage_bar.setMinimumWidth(280)
            storage_bar.setMaximumHeight(20)
            storage_bar.setMaximum(100)
            storage_bar.setValue(0)
            storage_bar.setTextVisible(True)
            storage_bar.setFormat("")
            storage_bar.setProperty("class", "storage-bar")
            storage_bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            # Tooltip will show full details
            #storage_bar.setToolTip("Storage information loading...")
            frame_layout.addWidget(storage_bar)

        # 5. Status Display (expanding, shows Ready/Disabled status)
        status_label = QLabel()
        status_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        # Set initial semantic status
        status_text = self._get_status_text(host_id, host_config)
        status_label.setText(status_text)
        self._update_status_label_style(host_id, host_config, status_label)
        frame_layout.addWidget(status_label)

        # Store widgets for later access
        self.host_widgets[host_id] = {
            "frame": host_frame,
            "status_icon": status_icon,
            "status_label": status_label,
            "storage_bar": storage_bar,
            "logo_label": logo_label,  # Store logo for theme updates
            "configure_btn": configure_btn,
            "enable_btn": None  # Removed - redundant with status icon
        }

        # Load cached storage immediately for this host
        self.refresh_storage_display(host_id)

        # Update status icon to reflect current enabled state
        self._update_status_icon(host_id)

        # Add to layout
        self.hosts_container_layout.addWidget(host_frame)

    def _load_host_logo(self, host_id: str, host_config: HostConfig, height: int = 40) -> Optional[QLabel]:
        """Load and create a clickable QLabel with the host's logo.

        Args:
            host_id: Host identifier (used to find logo file)
            host_config: HostConfig instance (for referral URL)
            height: Target height in pixels (default 40 for dialogs, 28 for settings tab).
                   Maintains aspect ratio.

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

            # Scale logo to specified height, maintaining aspect ratio
            scaled_pixmap = pixmap.scaledToHeight(height, Qt.TransformationMode.SmoothTransformation)

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

                logo_label.mousePressEvent = open_referral_url  # type: ignore[method-assign]

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

        # Set pixmap (20x20 size for inline status indicator)
        pixmap = icon.pixmap(20, 20)
        status_icon.setPixmap(pixmap)

        # Set tooltip
        tooltip = "Host enabled" if is_enabled else "Host disabled"
        status_icon.setToolTip(tooltip)

    def _get_status_text(self, host_id: str, host_config) -> str:
        """Get semantic status text for a host.

        Returns: "Ready (Auto)", "Ready (Manual)", "Credentials Required", or "Disabled"
        """
        from src.core.file_host_config import get_file_host_setting

        # Check if host is enabled
        is_enabled = get_file_host_setting(host_id, "enabled", "bool")

        if not is_enabled:
            # Check if credentials exist
            test_results = self._load_test_results_from_settings(host_id)
            has_credentials = test_results and test_results.get('credentials_valid', False)

            if not has_credentials and host_config.requires_auth:
                return "Credentials Required"
            else:
                return "Disabled"

        # Host is enabled - check auto-upload trigger
        trigger = get_file_host_setting(host_id, "trigger", "str")
        is_auto = trigger in ["on_added", "on_started", "on_completed"]

        if is_auto:
            map = {"on_added": "Add", "on_started": "Start", "on_completed": "Done"}
            automsg = trigger.replace("on_","").capitalize()
            return f"Ready (AUTO: On-{map[trigger]})"
        else:
            return "Ready (Manual)"

    def _update_status_label_style(self, host_id: str, host_config, status_label: QLabel):
        """Update status label styling based on current status.

        Args:
            host_id: Host identifier
            host_config: HostConfig instance
            status_label: QLabel to update
        """
        from src.core.file_host_config import get_file_host_setting

        # Get current status
        is_enabled = get_file_host_setting(host_id, "enabled", "bool")

        if not is_enabled:
            status_label.setProperty("class", "status-disabled")
        elif not host_config.requires_auth:
            status_label.setProperty("class", "status-success-light")
        else:
            test_results = self._load_test_results_from_settings(host_id)
            if not test_results:
                status_label.setProperty("class", "status-warning-light")
            else:
                tests_passed = sum([
                    test_results['credentials_valid'],
                    test_results['user_info_valid'],
                    test_results['upload_success'],
                    test_results['delete_success']
                ])

                if tests_passed == 4:
                    status_label.setProperty("class", "status-success")
                elif tests_passed > 0:
                    status_label.setProperty("class", "status-warning")
                else:
                    status_label.setProperty("class", "status-error")

        # Force style refresh
        label_style = status_label.style()
        if label_style:
            label_style.unpolish(status_label)
            label_style.polish(status_label)

    def _update_status_label(self, host_id: str, host_config, status_label: QLabel):
        """Update status label with semantic status text.

        Args:
            host_id: Host identifier
            host_config: HostConfig instance
            status_label: QLabel to update
        """
        status_text = self._get_status_text(host_id, host_config)
        status_label.setText(status_text)
        self._update_status_label_style(host_id, host_config, status_label)

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

    def _format_storage_compact(self, left: int, total: int) -> str:
        """Format storage as compact string showing amount free.

        Args:
            left: Free storage in bytes
            total: Total storage in bytes

        Returns:
            Compact storage string showing free amount (e.g., "15.2 GB free")
        """
        if total <= 0:
            return "Unknown"

        # Format free space with human-readable size
        left_formatted = format_binary_size(left)

        # Show amount free (e.g., "15.2 GB free")
        return f"{left_formatted} free"

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

        # Format strings for compact display and tooltip
        left_formatted = format_binary_size(left)
        total_formatted = format_binary_size(total)
        used_formatted = format_binary_size(used)

        # Compact format: show amount free (e.g., "15.2 GB free")
        compact_format = self._format_storage_compact(left, total)

        # Update progress bar with compact format
        storage_bar.setValue(percent_free)
        storage_bar.setFormat(compact_format)  # Shows "15.2 GB free"

        # Detailed tooltip
        tooltip = f"Storage: {left_formatted} free / {total_formatted} total\nUsed: {used_formatted} ({percent_used}%)"
        storage_bar.setToolTip(tooltip)

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

        # Update status label with semantic status (NOT test results)
        from src.core.file_host_config import get_config_manager
        config_manager = get_config_manager()
        host_config = config_manager.hosts.get(host_id)
        if host_config:
            status_text = self._get_status_text(host_id, host_config)
            status_label.setText(status_text)
            self._update_status_label_style(host_id, host_config, status_label)

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
        # Update status labels and icons for all hosts
        from src.core.file_host_config import get_config_manager
        config_manager = get_config_manager()

        for host_id, host_config in config_manager.hosts.items():
            widgets = self.host_widgets.get(host_id)
            if widgets:
                # Update status label
                if widgets.get('status_label'):
                    self._update_status_label(host_id, host_config, widgets['status_label'])
                # Update status icon
                self._update_status_icon(host_id)

    def _update_enable_button_state(self, host_id: str):
        """Legacy method - no longer used with compact layout.

        The enable/disable button has been removed from the compact layout.
        Enable/disable is now done through the Configure dialog.

        Args:
            host_id: Host identifier
        """
        # Method kept for backward compatibility but does nothing
        pass

    def _on_enable_disable_clicked(self, host_id: str):
        """Legacy method - no longer used with compact layout.

        Args:
            host_id: Host identifier
        """
        # Method kept for backward compatibility but does nothing
        pass
