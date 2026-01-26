"""Inheritable Proxy Control Widget - Hierarchical proxy settings with override support."""

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QComboBox, QLabel, QCheckBox
)
from PyQt6.QtCore import pyqtSignal, Qt
from typing import Optional, List, Literal

from src.proxy.models import ProxyPool
from src.proxy.storage import ProxyStorage


class InheritableProxyControl(QWidget):
    """
    Widget for hierarchical proxy settings with inheritance override.

    Features:
    - Override checkbox (unchecked = inherit from parent, checked = custom value)
    - Combo with options: Direct Connection, OS Proxy, [Pool list...]
    - Inherited display label (grayed, shows parent value when not overriding)
    - Icons: chain for inheriting, pencil for overriding
    - Support for hierarchy levels: global, category, service

    Special Values:
    - "__direct__" - Direct connection (no proxy)
    - "__os_proxy__" - Use OS system proxy
    - UUID string - Pool ID

    Signals:
        value_changed: Emitted when the effective value changes
    """

    # Signal emitted when value changes
    value_changed = pyqtSignal()

    # Special value constants
    VALUE_DIRECT = "__direct__"
    VALUE_OS_PROXY = "__os_proxy__"

    # Hierarchy levels
    LEVEL_GLOBAL = "global"
    LEVEL_CATEGORY = "category"
    LEVEL_SERVICE = "service"

    def __init__(
        self,
        parent=None,
        level: Literal["global", "category", "service"] = "service",
        category: Optional[str] = None,
        service_id: Optional[str] = None,
        show_label: bool = True,
        label_text: str = "Proxy:",
        compact: bool = False
    ):
        """Initialize inheritable proxy control.

        Args:
            parent: Parent widget
            level: Hierarchy level - "global", "category", or "service"
            category: Category name (required for category/service levels)
            service_id: Service ID (required for service level)
            show_label: Show label before controls
            label_text: Custom label text
            compact: Use compact layout
        """
        super().__init__(parent)
        self.storage = ProxyStorage()
        self.level = level
        self.category = category
        self.service_id = service_id

        self._pools: List[ProxyPool] = []
        self._parent_value: Optional[str] = None
        self._parent_source: str = ""
        self._is_overriding: bool = False

        self._setup_ui(show_label, label_text, compact)
        self._load_pools()
        self._load_parent_value()
        self._load_current_value()
        self._update_display()

    def _setup_ui(self, show_label: bool, label_text: str, compact: bool):
        """Setup the UI layout."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4 if compact else 8)

        # Optional label
        if show_label:
            self.label = QLabel(label_text)
            layout.addWidget(self.label)

        # Override checkbox (only for non-global levels)
        self.override_checkbox = None
        if self.level != self.LEVEL_GLOBAL:
            self.override_checkbox = QCheckBox("Override")
            self.override_checkbox.setToolTip(
                "Check to override inherited value, uncheck to inherit from parent"
            )
            self.override_checkbox.stateChanged.connect(self._on_override_changed)
            layout.addWidget(self.override_checkbox)

        # Inherited value display (grayed label showing parent value)
        self.inherited_label = QLabel()
        self.inherited_label.setStyleSheet("color: gray; font-style: italic;")
        self.inherited_label.setVisible(False)
        layout.addWidget(self.inherited_label, 1)

        # Value combo box
        self.combo = QComboBox()
        self.combo.setMinimumWidth(120 if compact else 150)
        self.combo.currentIndexChanged.connect(self._on_combo_changed)
        layout.addWidget(self.combo, 1)

        # Status icon label
        self.status_icon = QLabel()
        self.status_icon.setFixedSize(16, 16)
        layout.addWidget(self.status_icon)

    def _load_pools(self):
        """Load available proxy pools."""
        self._pools = self.storage.list_pools()
        self._populate_combo()

    def _populate_combo(self):
        """Populate combo box with options."""
        self.combo.blockSignals(True)
        self.combo.clear()

        # Direct connection option
        self.combo.addItem("Direct Connection", self.VALUE_DIRECT)

        # OS Proxy option
        self.combo.addItem("OS System Proxy", self.VALUE_OS_PROXY)

        # Separator and pool options
        if self._pools:
            self.combo.insertSeparator(self.combo.count())
            for pool in self._pools:
                if pool.enabled:
                    proxy_count = len(pool.proxies) if pool.proxies else 0
                    display = f"{pool.name} ({proxy_count} proxies)"
                    self.combo.addItem(display, pool.id)

        self.combo.blockSignals(False)

    def _load_parent_value(self):
        """Load the inherited value from parent level."""
        if self.level == self.LEVEL_GLOBAL:
            self._parent_value = None
            self._parent_source = ""
            return

        if self.level == self.LEVEL_SERVICE and self.category:
            # Service inherits from category first
            pool_id = self.storage.get_pool_assignment(self.category, None)
            if pool_id:
                self._parent_value = pool_id
                self._parent_source = f"Category: {self.category}"
                return

        # Fall back to global defaults
        global_pool = self.storage.get_global_default_pool()
        if global_pool:
            self._parent_value = global_pool
            self._parent_source = "Global default"
            return

        # Check if OS proxy is enabled
        if self.storage.get_use_os_proxy():
            self._parent_value = self.VALUE_OS_PROXY
            self._parent_source = "Global (OS Proxy)"
            return

        # Default to direct connection
        self._parent_value = self.VALUE_DIRECT
        self._parent_source = "Global (Direct)"

    def _load_current_value(self):
        """Load the current value for this level."""
        current_value = None

        if self.level == self.LEVEL_GLOBAL:
            current_value = self.storage.get_global_default_pool()
            if not current_value and self.storage.get_use_os_proxy():
                current_value = self.VALUE_OS_PROXY
            self._is_overriding = True  # Global always "overrides"
        elif self.level == self.LEVEL_CATEGORY and self.category:
            current_value = self.storage.get_pool_assignment(self.category, None)
            self._is_overriding = current_value is not None
        elif self.level == self.LEVEL_SERVICE and self.category and self.service_id:
            current_value = self.storage.get_pool_assignment(self.category, self.service_id)
            self._is_overriding = current_value is not None

        if self._is_overriding and current_value:
            self._set_combo_value(current_value)
        elif self._parent_value:
            self._set_combo_value(self._parent_value)

    def _set_combo_value(self, value: str):
        """Set combo box to a specific value."""
        self.combo.blockSignals(True)
        for i in range(self.combo.count()):
            if self.combo.itemData(i) == value:
                self.combo.setCurrentIndex(i)
                break
        self.combo.blockSignals(False)

    def _update_display(self):
        """Update visual display based on override state."""
        if self.level == self.LEVEL_GLOBAL:
            self.combo.setEnabled(True)
            self.combo.setVisible(True)
            self.inherited_label.setVisible(False)
            self._update_status_icon(overriding=True)
            return

        if self.override_checkbox:
            self.override_checkbox.blockSignals(True)
            self.override_checkbox.setChecked(self._is_overriding)
            self.override_checkbox.blockSignals(False)

        if self._is_overriding:
            self.combo.setEnabled(True)
            self.combo.setVisible(True)
            self.inherited_label.setVisible(False)
            self._update_status_icon(overriding=True)
        else:
            self.combo.setEnabled(False)
            self.combo.setVisible(False)
            self.inherited_label.setVisible(True)
            display_name = self._get_display_name(self._parent_value)
            self.inherited_label.setText(f"→ {display_name} (from {self._parent_source})")
            self._update_status_icon(overriding=False)

    def _update_status_icon(self, overriding: bool):
        """Update the status icon based on override state."""
        # Use simple text-based status indicator
        self.status_icon.setText("✏" if overriding else "🔗")
        self.status_icon.setToolTip(
            "Custom value (overriding)" if overriding else "Inherited from parent"
        )

    def _get_display_name(self, value: Optional[str]) -> str:
        """Get human-readable display name for a value."""
        if value is None:
            return "None"
        if value == self.VALUE_DIRECT:
            return "Direct Connection"
        if value == self.VALUE_OS_PROXY:
            return "OS System Proxy"

        for pool in self._pools:
            if pool.id == value:
                return pool.name

        # Pool ID not found in current list - may have been deleted
        return "(Deleted pool)"

    def _on_override_changed(self, state: int):
        """Handle override checkbox state change."""
        self._is_overriding = state == Qt.CheckState.Checked.value
        self._update_display()

        if not self._is_overriding:
            self._clear_assignment()
        else:
            self._save_assignment()

        self.value_changed.emit()

    def _on_combo_changed(self):
        """Handle combo box selection change."""
        if self._is_overriding or self.level == self.LEVEL_GLOBAL:
            self._save_assignment()
            self.value_changed.emit()

    def _save_assignment(self):
        """Save the current selection to storage."""
        value = self.combo.currentData()
        if value is None:
            return

        if self.level == self.LEVEL_GLOBAL:
            if value == self.VALUE_DIRECT:
                self.storage.set_global_default_pool(None)
                self.storage.set_use_os_proxy(False)
            elif value == self.VALUE_OS_PROXY:
                self.storage.set_global_default_pool(None)
                self.storage.set_use_os_proxy(True)
            else:
                self.storage.set_global_default_pool(value)
                self.storage.set_use_os_proxy(False)
        elif self.level == self.LEVEL_CATEGORY and self.category:
            # Store special values directly - storage and resolver support them
            self.storage.set_pool_assignment(value, self.category, None)
        elif self.level == self.LEVEL_SERVICE and self.category and self.service_id:
            # Store special values directly - storage and resolver support them
            self.storage.set_pool_assignment(value, self.category, self.service_id)

    def _clear_assignment(self):
        """Clear the override assignment (revert to inherit)."""
        if self.level == self.LEVEL_CATEGORY and self.category:
            self.storage.set_pool_assignment(None, self.category, None)
        elif self.level == self.LEVEL_SERVICE and self.category and self.service_id:
            self.storage.set_pool_assignment(None, self.category, self.service_id)

    def get_effective_value(self) -> Optional[str]:
        """Get the effective proxy value (considering inheritance)."""
        if self._is_overriding or self.level == self.LEVEL_GLOBAL:
            return self.combo.currentData()
        return self._parent_value

    def is_overriding(self) -> bool:
        """Check if this level is overriding the parent value."""
        return self._is_overriding

    def set_override(self, override: bool):
        """Set the override state."""
        if self.override_checkbox:
            self.override_checkbox.setChecked(override)

    def refresh(self):
        """Refresh the control from storage."""
        self._load_pools()
        self._load_parent_value()
        self._load_current_value()
        self._update_display()
