"""Proxy Selector Widget - Reusable dropdown for proxy/pool selection."""

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QComboBox, QLabel, QPushButton, QToolButton,
    QVBoxLayout, QMenu
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QAction
from typing import Optional, List

from src.proxy.models import ProxyProfile, ProxyPool
from src.proxy.storage import ProxyStorage


class ProxySelector(QWidget):
    """
    Reusable widget for selecting a proxy profile or pool.

    Features:
    - Dropdown with profiles and pools
    - "Inherit" option to use parent/global default
    - "Direct" option for no proxy
    - Quick test button
    - Compact and full layout modes

    Usage:
        selector = ProxySelector(parent, category="file_hosts", service_id="rapidgator")
        selector.selection_changed.connect(self._on_proxy_changed)

        # Get selection
        profile_id, pool_id, use_inherit = selector.get_selection()
    """

    selection_changed = pyqtSignal()  # Emitted when selection changes

    # Selection types
    TYPE_INHERIT = "inherit"
    TYPE_DIRECT = "direct"
    TYPE_PROFILE = "profile"
    TYPE_POOL = "pool"

    def __init__(
        self,
        parent=None,
        category: Optional[str] = None,
        service_id: Optional[str] = None,
        show_test_button: bool = False,
        show_label: bool = True,
        label_text: str = "Proxy:",
        compact: bool = False,
        allow_inherit: bool = True
    ):
        """Initialize proxy selector.

        Args:
            parent: Parent widget
            category: Category for inheritance (e.g., "file_hosts")
            service_id: Service ID for service-level assignment
            show_test_button: Show quick test button
            show_label: Show label before dropdown
            label_text: Custom label text
            compact: Use compact layout
            allow_inherit: Allow "Inherit" option
        """
        super().__init__(parent)
        self.storage = ProxyStorage()
        self.category = category
        self.service_id = service_id
        self.allow_inherit = allow_inherit

        self._profiles: List[ProxyProfile] = []
        self._pools: List[ProxyPool] = []

        self.setup_ui(show_label, label_text, show_test_button, compact)
        self.load_options()

        # Load current selection if service_id is provided
        if service_id and category:
            self._load_service_selection()

    def setup_ui(self, show_label: bool, label_text: str,
                 show_test_button: bool, compact: bool):
        """Setup the UI."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        if compact:
            layout.setSpacing(4)

        # Optional label
        if show_label:
            self.label = QLabel(label_text)
            layout.addWidget(self.label)

        # Dropdown
        self.combo = QComboBox()
        self.combo.setMinimumWidth(150 if not compact else 120)
        self.combo.currentIndexChanged.connect(self._on_selection_changed)
        layout.addWidget(self.combo, 1)

        # Optional test button
        if show_test_button:
            self.test_btn = QToolButton()
            self.test_btn.setText("Test")
            self.test_btn.setToolTip("Test proxy connection")
            self.test_btn.clicked.connect(self._on_test_clicked)
            layout.addWidget(self.test_btn)

    def load_options(self):
        """Load available profiles and pools into combo box."""
        self._profiles = self.storage.list_profiles()
        self._pools = self.storage.list_pools()

        self.combo.blockSignals(True)
        self.combo.clear()

        # Inherit option (if allowed and has context)
        if self.allow_inherit:
            inherit_label = "(Inherit from parent)"
            if self.category:
                inherit_label = f"(Inherit from {self.category})"
            self.combo.addItem(inherit_label, (self.TYPE_INHERIT, None))

        # Direct connection
        self.combo.addItem("Direct Connection (no proxy)", (self.TYPE_DIRECT, None))

        # Separator after system options
        self.combo.insertSeparator(self.combo.count())

        # Profiles
        if self._profiles:
            for profile in self._profiles:
                if profile.enabled:
                    icon_prefix = self._get_proxy_type_icon(profile.proxy_type)
                    display = f"{icon_prefix} {profile.name}"
                    self.combo.addItem(display, (self.TYPE_PROFILE, profile.id))

        # Pools (with separator if we have both)
        if self._pools and self._profiles:
            self.combo.insertSeparator(self.combo.count())

        if self._pools:
            for pool in self._pools:
                if pool.enabled:
                    display = f"[Pool] {pool.name} ({len(pool.proxies)} proxies)"
                    self.combo.addItem(display, (self.TYPE_POOL, pool.id))

        self.combo.blockSignals(False)

    def _get_proxy_type_icon(self, proxy_type) -> str:
        """Get icon/prefix for proxy type."""
        type_icons = {
            "http": "HTTP",
            "https": "HTTPS",
            "socks4": "S4",
            "socks5": "S5",
        }
        return type_icons.get(proxy_type.value, "")

    def _load_service_selection(self):
        """Load current selection for service from storage."""
        if not self.service_id or not self.category:
            return

        # Check for pool assignment first
        pool_id = self.storage.get_pool_assignment(self.category, self.service_id)
        if pool_id:
            self._set_selection(self.TYPE_POOL, pool_id)
            return

        # Check for profile assignment
        profile_id = self.storage.get_assignment(self.category, self.service_id)
        if profile_id:
            self._set_selection(self.TYPE_PROFILE, profile_id)
            return

        # Default to inherit
        self._set_selection(self.TYPE_INHERIT, None)

    def _set_selection(self, selection_type: str, selection_id: Optional[str]):
        """Set combo box selection by type and ID."""
        self.combo.blockSignals(True)
        for i in range(self.combo.count()):
            data = self.combo.itemData(i)
            if data and data[0] == selection_type and data[1] == selection_id:
                self.combo.setCurrentIndex(i)
                break
        self.combo.blockSignals(False)

    def _on_selection_changed(self):
        """Handle selection change."""
        # Save selection if we have service context
        if self.service_id and self.category:
            sel_type, sel_id = self.get_selection_type()

            if sel_type == self.TYPE_INHERIT:
                # Clear both assignments
                self.storage.set_assignment(None, self.category, self.service_id)
                self.storage.set_pool_assignment(None, self.category, self.service_id)
            elif sel_type == self.TYPE_DIRECT:
                # Clear pool, set profile to empty string (explicit direct)
                self.storage.set_assignment("__direct__", self.category, self.service_id)
                self.storage.set_pool_assignment(None, self.category, self.service_id)
            elif sel_type == self.TYPE_PROFILE:
                self.storage.set_assignment(sel_id, self.category, self.service_id)
                self.storage.set_pool_assignment(None, self.category, self.service_id)
            elif sel_type == self.TYPE_POOL:
                self.storage.set_assignment(None, self.category, self.service_id)
                self.storage.set_pool_assignment(sel_id, self.category, self.service_id)

        self.selection_changed.emit()

    def get_selection_type(self) -> tuple:
        """Get current selection as (type, id) tuple."""
        data = self.combo.currentData()
        if data:
            return data
        return (self.TYPE_INHERIT, None)

    def get_selection(self) -> tuple:
        """Get current selection details.

        Returns:
            (profile_id, pool_id, use_inherit) tuple
        """
        sel_type, sel_id = self.get_selection_type()

        if sel_type == self.TYPE_INHERIT:
            return (None, None, True)
        elif sel_type == self.TYPE_DIRECT:
            return (None, None, False)
        elif sel_type == self.TYPE_PROFILE:
            return (sel_id, None, False)
        elif sel_type == self.TYPE_POOL:
            return (None, sel_id, False)

        return (None, None, True)

    def set_selection_by_profile(self, profile_id: Optional[str]):
        """Set selection to a specific profile."""
        if profile_id:
            self._set_selection(self.TYPE_PROFILE, profile_id)
        else:
            self._set_selection(self.TYPE_DIRECT, None)

    def set_selection_by_pool(self, pool_id: str):
        """Set selection to a specific pool."""
        self._set_selection(self.TYPE_POOL, pool_id)

    def set_inherit(self):
        """Set selection to inherit."""
        self._set_selection(self.TYPE_INHERIT, None)

    def set_direct(self):
        """Set selection to direct connection."""
        self._set_selection(self.TYPE_DIRECT, None)

    def _on_test_clicked(self):
        """Handle test button click."""
        sel_type, sel_id = self.get_selection_type()

        if sel_type == self.TYPE_DIRECT:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(
                self, "Direct Connection",
                "Direct connection selected - no proxy to test."
            )
            return

        if sel_type == self.TYPE_INHERIT:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(
                self, "Inherited Proxy",
                "Proxy is inherited from parent settings.\n"
                "Test from the parent configuration."
            )
            return

        if sel_type == self.TYPE_PROFILE:
            profile = self.storage.load_profile(sel_id)
            if profile:
                self._test_proxy(profile)

        elif sel_type == self.TYPE_POOL:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(
                self, "Pool Test",
                "Pool testing tests all proxies in the pool.\n"
                "Use the Pool Manager to test individual proxies."
            )

    def _test_proxy(self, profile: ProxyProfile):
        """Test a proxy connection."""
        try:
            import pycurl
            from io import BytesIO
            from src.proxy.pycurl_adapter import PyCurlProxyAdapter

            buffer = BytesIO()
            curl = pycurl.Curl()
            curl.setopt(pycurl.URL, "https://httpbin.org/ip")
            curl.setopt(pycurl.WRITEDATA, buffer)
            curl.setopt(pycurl.TIMEOUT, 10)
            curl.setopt(pycurl.CONNECTTIMEOUT, 5)

            PyCurlProxyAdapter.configure_proxy(curl, profile)

            curl.perform()
            status_code = curl.getinfo(pycurl.RESPONSE_CODE)
            curl.close()

            from PyQt6.QtWidgets import QMessageBox
            if status_code == 200:
                response = buffer.getvalue().decode('utf-8')
                QMessageBox.information(
                    self,
                    "Proxy Test Successful",
                    f"Connection through '{profile.name}' successful!\n\n"
                    f"Response: {response[:200]}"
                )
            else:
                QMessageBox.warning(
                    self,
                    "Proxy Test Failed",
                    f"Connection returned status {status_code}"
                )

        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(
                self,
                "Proxy Test Failed",
                f"Connection error: {e}"
            )

    def refresh(self):
        """Refresh the options from storage."""
        current_selection = self.get_selection_type()
        self.load_options()

        # Restore selection if still valid
        self._set_selection(current_selection[0], current_selection[1])
