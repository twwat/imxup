"""Proxy Settings Widget - Manage proxy pools and assignments."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QMessageBox, QListWidget, QListWidgetItem, QRadioButton, QButtonGroup
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QColor
from typing import Optional, List
import logging
import re

from src.proxy.models import ProxyPool
from src.proxy.storage import ProxyStorage
from .simple_proxy_dropdown import SimpleProxyDropdown

logger = logging.getLogger(__name__)


class ProxySettingsWidget(QWidget):
    """Widget for configuring proxy settings - pools and assignments."""

    settings_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.storage = ProxyStorage()

        self.setup_ui()
        self.load_pools()

    def setup_ui(self):
        """Setup the proxy settings UI."""
        layout = QVBoxLayout(self)

        # Proxy Mode Selection Group
        mode_group = QGroupBox("Proxy Configuration")
        mode_layout = QVBoxLayout(mode_group)

        # Radio buttons for proxy modes
        self.proxy_mode_group = QButtonGroup(self)

        self.no_proxy_radio = QRadioButton("No proxy")
        self.no_proxy_radio.setToolTip("Direct connection - no proxy used")
        self.proxy_mode_group.addButton(self.no_proxy_radio, 0)
        mode_layout.addWidget(self.no_proxy_radio)

        self.system_proxy_radio = QRadioButton("Use system proxy settings")
        self.system_proxy_radio.setToolTip("Use operating system's configured proxy")
        self.proxy_mode_group.addButton(self.system_proxy_radio, 1)
        mode_layout.addWidget(self.system_proxy_radio)

        self.custom_proxy_radio = QRadioButton("Custom proxy configuration")
        self.custom_proxy_radio.setToolTip("Configure custom proxy pools and assignments")
        self.proxy_mode_group.addButton(self.custom_proxy_radio, 2)
        mode_layout.addWidget(self.custom_proxy_radio)

        # Connect radio button change signal
        self.proxy_mode_group.buttonClicked.connect(self._on_proxy_mode_changed)

        layout.addWidget(mode_group)

        # Proxy Pools Group (disabled unless custom mode)
        self.pools_group = QGroupBox("Proxy Pools")
        pools_layout = QVBoxLayout(self.pools_group)

        pools_info = QLabel(
            "Each pool contains your proxy servers. Create a pool, paste your proxies, done."
        )
        pools_info.setWordWrap(True)
        pools_layout.addWidget(pools_info)

        # Pools list
        self.pools_list = QListWidget()
        self.pools_list.setMinimumHeight(150)
        self.pools_list.itemSelectionChanged.connect(self._on_pool_selected)
        self.pools_list.itemDoubleClicked.connect(self._on_pool_edit)
        pools_layout.addWidget(self.pools_list)

        # Pool buttons
        pool_btn_layout = QHBoxLayout()

        self.add_pool_btn = QPushButton("New Pool")
        self.add_pool_btn.clicked.connect(self._on_add_pool)
        pool_btn_layout.addWidget(self.add_pool_btn)

        self.edit_pool_btn = QPushButton("Edit")
        self.edit_pool_btn.setEnabled(False)
        self.edit_pool_btn.clicked.connect(self._on_edit_pool)
        pool_btn_layout.addWidget(self.edit_pool_btn)

        self.delete_pool_btn = QPushButton("Delete")
        self.delete_pool_btn.setEnabled(False)
        self.delete_pool_btn.clicked.connect(self._on_delete_pool)
        pool_btn_layout.addWidget(self.delete_pool_btn)

        self.test_pool_btn = QPushButton("Test")
        self.test_pool_btn.setEnabled(False)
        self.test_pool_btn.setToolTip("Test first proxy in pool")
        self.test_pool_btn.clicked.connect(self._on_test_pool)
        pool_btn_layout.addWidget(self.test_pool_btn)

        pool_btn_layout.addStretch()
        pools_layout.addLayout(pool_btn_layout)

        layout.addWidget(self.pools_group)

        # Category Overrides Group (disabled unless custom mode)
        self.category_group = QGroupBox("Category Overrides")
        category_layout = QVBoxLayout(self.category_group)

        category_info = QLabel(
            "Override the global proxy for specific categories."
        )
        category_info.setWordWrap(True)
        category_layout.addWidget(category_info)

        # File Hosts category
        fh_layout = QHBoxLayout()
        fh_layout.addWidget(QLabel("File Hosts:"))
        self.file_hosts_dropdown = SimpleProxyDropdown(category="file_hosts")
        self.file_hosts_dropdown.value_changed.connect(self._on_settings_changed)
        fh_layout.addWidget(self.file_hosts_dropdown, 1)
        category_layout.addLayout(fh_layout)

        # Forums category
        forums_layout = QHBoxLayout()
        forums_layout.addWidget(QLabel("Forums:"))
        self.forums_dropdown = SimpleProxyDropdown(category="forums")
        self.forums_dropdown.value_changed.connect(self._on_settings_changed)
        forums_layout.addWidget(self.forums_dropdown, 1)
        category_layout.addLayout(forums_layout)

        # API category
        api_layout = QHBoxLayout()
        api_layout.addWidget(QLabel("API:"))
        self.api_dropdown = SimpleProxyDropdown(category="api")
        self.api_dropdown.value_changed.connect(self._on_settings_changed)
        api_layout.addWidget(self.api_dropdown, 1)
        category_layout.addLayout(api_layout)

        layout.addWidget(self.category_group)
        layout.addStretch()

        # Set initial proxy mode based on current settings
        self._load_proxy_mode()
        self._update_ui_state()

    def load_pools(self):
        """Load proxy pools from storage."""
        try:
            # Load pools into list widget
            pools = self.storage.list_pools()

            self.pools_list.clear()
            for pool in pools:
                self._add_pool_to_list(pool)

            # Refresh all SimpleProxyDropdown widgets
            self.file_hosts_dropdown.refresh()
            self.forums_dropdown.refresh()
            self.api_dropdown.refresh()
        except Exception as e:
            logger.error(f"Failed to load proxy pools: {e}")
            QMessageBox.critical(
                self,
                "Error Loading Pools",
                f"Failed to load proxy pools from storage.\n\nError: {e}"
            )

    def _add_pool_to_list(self, pool: ProxyPool):
        """Add a pool to the list widget."""
        proxy_count = len(pool.proxies)
        display = f"{pool.name} ({proxy_count} proxies, {pool.rotation_strategy.value})"
        if pool.sticky_sessions:
            display += " [Sticky]"
        if not pool.enabled:
            display += " [Disabled]"

        item = QListWidgetItem(display)
        item.setData(Qt.ItemDataRole.UserRole, pool.id)

        if not pool.enabled:
            item.setForeground(QColor(128, 128, 128))

        self.pools_list.addItem(item)

    def _on_settings_changed(self):
        """Handle any settings change from InheritableProxyControl widgets."""
        self.settings_changed.emit()

    def _load_proxy_mode(self):
        """Load and set the appropriate proxy mode radio button."""
        # Block signals during initialization to prevent triggering _on_proxy_mode_changed
        self.proxy_mode_group.blockSignals(True)

        try:
            # Check current global settings to determine mode
            use_os_proxy = self.storage.get_use_os_proxy()
            default_pool = self.storage.get_global_default_pool()

            if use_os_proxy:
                self.system_proxy_radio.setChecked(True)
            elif default_pool:
                # Has pool assigned = custom mode
                self.custom_proxy_radio.setChecked(True)
            else:
                # No proxy configured
                self.no_proxy_radio.setChecked(True)
        finally:
            # Always re-enable signals
            self.proxy_mode_group.blockSignals(False)

    def _on_proxy_mode_changed(self):
        """Handle proxy mode radio button change."""
        selected_mode = self.proxy_mode_group.checkedId()

        if selected_mode == 0:  # No proxy
            # Set global to direct connection
            self.storage.set_global_default_pool(None)
            self.storage.set_use_os_proxy(False)
        elif selected_mode == 1:  # System proxy
            # Set global to use OS proxy
            self.storage.set_global_default_pool(None)
            self.storage.set_use_os_proxy(True)
        # For custom mode (2), don't change anything - let user configure

        self._update_ui_state()
        self.settings_changed.emit()

    def _update_ui_state(self):
        """Enable/disable proxy configuration sections based on selected mode."""
        is_custom_mode = self.custom_proxy_radio.isChecked()

        # Enable/disable all proxy configuration sections
        self.pools_group.setEnabled(is_custom_mode)
        self.category_group.setEnabled(is_custom_mode)

    def _on_pool_selected(self):
        """Handle pool selection change."""
        has_selection = len(self.pools_list.selectedItems()) > 0
        self.edit_pool_btn.setEnabled(has_selection)
        self.delete_pool_btn.setEnabled(has_selection)
        self.test_pool_btn.setEnabled(has_selection)

    def _on_pool_edit(self, item: QListWidgetItem):
        """Handle double-click to edit pool."""
        self._on_edit_pool()

    def _on_add_pool(self):
        """Show dialog to create new pool."""
        from src.gui.dialogs.proxy_pool_dialog import ProxyPoolDialog

        dialog = ProxyPoolDialog(self)
        if dialog.exec():
            pool = dialog.get_pool()
            self.storage.save_pool(pool)
            self.load_pools()
            self.settings_changed.emit()

    def _on_edit_pool(self):
        """Show dialog to edit selected pool."""
        items = self.pools_list.selectedItems()
        if not items:
            return

        pool_id = items[0].data(Qt.ItemDataRole.UserRole)
        pool = self.storage.load_pool(pool_id)
        if not pool:
            QMessageBox.warning(self, "Error", "Could not load pool.")
            return

        from src.gui.dialogs.proxy_pool_dialog import ProxyPoolDialog

        dialog = ProxyPoolDialog(self, pool=pool)
        if dialog.exec():
            updated = dialog.get_pool()
            self.storage.save_pool(updated)
            self.load_pools()
            self.settings_changed.emit()

    def _on_delete_pool(self):
        """Delete selected pool."""
        items = self.pools_list.selectedItems()
        if not items:
            return

        pool_id = items[0].data(Qt.ItemDataRole.UserRole)
        pool = self.storage.load_pool(pool_id)
        if not pool:
            return

        reply = QMessageBox.question(
            self,
            "Delete Pool",
            f"Delete proxy pool '{pool.name}' with {len(pool.proxies)} proxies?\n\n"
            "This will clear any assignments using this pool.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.storage.delete_pool(pool_id)
            self.load_pools()
            self.settings_changed.emit()

    def _validate_proxy_host(self, host: str) -> bool:
        """Validate proxy host to prevent injection attacks.

        Args:
            host: Proxy hostname or IP address

        Returns:
            True if host is valid, False otherwise
        """
        # Allow alphanumeric, dots, hyphens, and underscores for hostnames
        # Allow IPv4 addresses (e.g., 192.168.1.1)
        hostname_pattern = r'^[a-zA-Z0-9._-]+$'
        ipv4_pattern = r'^(\d{1,3}\.){3}\d{1,3}$'

        if not host or len(host) > 253:  # Max DNS hostname length
            return False

        return bool(re.match(hostname_pattern, host) or re.match(ipv4_pattern, host))

    def _on_test_pool(self):
        """Test first proxy in selected pool."""
        items = self.pools_list.selectedItems()
        if not items:
            return

        pool_id = items[0].data(Qt.ItemDataRole.UserRole)
        pool = self.storage.load_pool(pool_id)
        if not pool or not pool.proxies:
            QMessageBox.warning(self, "Error", "Pool has no proxies.")
            return

        proxy = pool.proxies[0]

        # Validate proxy host before testing
        if not self._validate_proxy_host(proxy.host):
            logger.error(f"Invalid proxy host detected: {proxy.host}")
            QMessageBox.critical(
                self,
                "Security Error",
                "Invalid proxy host configuration. Please check proxy settings."
            )
            return

        try:
            import pycurl
            from io import BytesIO

            buffer = BytesIO()
            curl = pycurl.Curl()
            curl.setopt(pycurl.URL, "https://httpbin.org/ip")
            curl.setopt(pycurl.WRITEDATA, buffer)
            curl.setopt(pycurl.TIMEOUT, 10)
            curl.setopt(pycurl.CONNECTTIMEOUT, 5)

            # Set proxy
            proxy_url = proxy.get_full_url()
            curl.setopt(pycurl.PROXY, f"{proxy.host}:{proxy.port}")

            if proxy.proxy_type.value in ('socks4', 'socks5'):
                curl.setopt(pycurl.PROXYTYPE,
                    pycurl.PROXYTYPE_SOCKS5 if proxy.proxy_type.value == 'socks5'
                    else pycurl.PROXYTYPE_SOCKS4)

            if proxy.username:
                curl.setopt(pycurl.PROXYUSERPWD, f"{proxy.username}:{proxy.password}")

            curl.perform()
            status_code = curl.getinfo(pycurl.RESPONSE_CODE)
            curl.close()

            if status_code == 200:
                response = buffer.getvalue().decode('utf-8')
                QMessageBox.information(
                    self,
                    "Proxy Test Successful",
                    f"Connection through pool '{pool.name}' successful!\n\n"
                    f"Tested: {proxy.get_display_url()}\n"
                    f"Response:\n{response}"
                )
            else:
                QMessageBox.warning(
                    self,
                    "Proxy Test Failed",
                    f"Connection returned status {status_code}"
                )

        except Exception as e:
            logger.error(f"Proxy test failed for pool {pool.name}: {e}")
            QMessageBox.critical(
                self,
                "Proxy Test Failed",
                f"Connection error: {e}"
            )

    def load_settings(self, settings: dict):
        """Load settings - called by parent settings dialog."""
        self.load_pools()

    def get_settings(self) -> dict:
        """Get settings - called by parent settings dialog."""
        return {}
