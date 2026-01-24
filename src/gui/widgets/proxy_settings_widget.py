"""Proxy Settings Widget - Manage proxy pools and assignments."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QMessageBox, QListWidget, QListWidgetItem
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QColor
from typing import Optional, List

from src.proxy.models import ProxyPool
from src.proxy.storage import ProxyStorage
from src.gui.widgets.inheritable_proxy_control import InheritableProxyControl


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

        # Intro text
        intro_label = QLabel(
            "Create proxy pools and assign them to services. "
            "Each pool contains your proxy servers and rotation settings."
        )
        intro_label.setWordWrap(True)
        layout.addWidget(intro_label)

        # Global Settings Group
        global_group = QGroupBox("Global Settings")
        global_layout = QVBoxLayout(global_group)

        global_info = QLabel(
            "Set the default proxy for all connections. Categories and services can override this."
        )
        global_info.setWordWrap(True)
        global_layout.addWidget(global_info)

        self.global_proxy_control = InheritableProxyControl(
            parent=self,
            level="global",
            show_label=True,
            label_text="Default Proxy:"
        )
        self.global_proxy_control.value_changed.connect(self._on_settings_changed)
        global_layout.addWidget(self.global_proxy_control)

        layout.addWidget(global_group)

        # Proxy Pools Group
        pools_group = QGroupBox("Proxy Pools")
        pools_layout = QVBoxLayout(pools_group)

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

        layout.addWidget(pools_group)

        # Category Overrides Group
        category_group = QGroupBox("Category Overrides")
        category_layout = QVBoxLayout(category_group)

        category_info = QLabel(
            "Override the global proxy for specific categories. "
            "Uncheck 'Override' to inherit from global settings."
        )
        category_info.setWordWrap(True)
        category_layout.addWidget(category_info)

        # File Hosts category
        self.file_hosts_control = InheritableProxyControl(
            parent=self,
            level="category",
            category="file_hosts",
            show_label=True,
            label_text="File Hosts:"
        )
        self.file_hosts_control.value_changed.connect(self._on_settings_changed)
        category_layout.addWidget(self.file_hosts_control)

        # Forums category
        self.forums_control = InheritableProxyControl(
            parent=self,
            level="category",
            category="forums",
            show_label=True,
            label_text="Forums:"
        )
        self.forums_control.value_changed.connect(self._on_settings_changed)
        category_layout.addWidget(self.forums_control)

        # API category
        self.api_control = InheritableProxyControl(
            parent=self,
            level="category",
            category="api",
            show_label=True,
            label_text="API:"
        )
        self.api_control.value_changed.connect(self._on_settings_changed)
        category_layout.addWidget(self.api_control)

        layout.addWidget(category_group)
        layout.addStretch()

    def load_pools(self):
        """Load proxy pools from storage."""
        # Load pools into list widget
        pools = self.storage.list_pools()

        self.pools_list.clear()
        for pool in pools:
            self._add_pool_to_list(pool)

        # Refresh all InheritableProxyControl widgets
        self.global_proxy_control.refresh()
        self.file_hosts_control.refresh()
        self.forums_control.refresh()
        self.api_control.refresh()

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
