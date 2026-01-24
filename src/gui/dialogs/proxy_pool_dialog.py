"""Proxy Pool Dialog - Create and edit proxy pools with direct proxy entry."""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QGroupBox,
    QPushButton, QLineEdit, QCheckBox, QComboBox, QSpinBox,
    QPlainTextEdit, QDialogButtonBox, QMessageBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from typing import Optional

from src.proxy.models import ProxyPool, ProxyType, RotationStrategy, ProxyParseResult


class ProxyPoolDialog(QDialog):
    """Dialog for creating or editing a proxy pool.

    Proxies are added directly by pasting them - no separate "profile" creation needed.
    """

    def __init__(self, parent, pool: Optional[ProxyPool] = None, **kwargs):
        """Initialize dialog.

        Args:
            parent: Parent widget
            pool: Existing pool to edit, or None for new pool
        """
        super().__init__(parent)
        self.pool = pool
        self.is_new = pool is None
        self._last_parse_result: Optional[ProxyParseResult] = None

        self.setWindowTitle("New Proxy Pool" if self.is_new else f"Edit Pool: {pool.name}")
        self.setModal(True)
        self.resize(600, 600)

        self.setup_ui()

        if pool:
            self.load_pool(pool)

    def setup_ui(self):
        """Setup the dialog UI."""
        layout = QVBoxLayout(self)

        # Basic Settings Group
        basic_group = QGroupBox("Pool Settings")
        basic_layout = QFormLayout(basic_group)

        # Pool name
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g., Main Pool, EU Proxies")
        basic_layout.addRow("Pool Name:", self.name_input)

        # Default proxy type
        self.type_combo = QComboBox()
        self.type_combo.addItem("HTTP", ProxyType.HTTP)
        self.type_combo.addItem("HTTPS", ProxyType.HTTPS)
        self.type_combo.addItem("SOCKS4", ProxyType.SOCKS4)
        self.type_combo.addItem("SOCKS5", ProxyType.SOCKS5)
        self.type_combo.setToolTip("Default type for proxies without explicit type")
        basic_layout.addRow("Default Type:", self.type_combo)

        # Enabled checkbox
        self.enabled_checkbox = QCheckBox("Pool enabled")
        self.enabled_checkbox.setChecked(True)
        basic_layout.addRow(self.enabled_checkbox)

        layout.addWidget(basic_group)

        # Proxies Group - THE MAIN THING
        proxies_group = QGroupBox("Proxies")
        proxies_layout = QVBoxLayout(proxies_group)

        proxies_label = QLabel(
            "Paste your proxies below (one per line). Supported formats:\n"
            "  host:port\n"
            "  host:port:username:password\n"
            "  http://host:port\n"
            "  socks5://user:pass@host:port"
        )
        proxies_label.setWordWrap(True)
        proxies_layout.addWidget(proxies_label)

        self.proxies_input = QPlainTextEdit()
        self.proxies_input.setFont(QFont("Consolas", 10))
        self.proxies_input.setPlaceholderText(
            "192.168.1.1:8080\n"
            "10.0.0.1:3128:myuser:mypass\n"
            "socks5://proxy.example.com:1080"
        )
        self.proxies_input.setMinimumHeight(150)
        proxies_layout.addWidget(self.proxies_input)

        # Proxy count label
        self.count_label = QLabel("0 proxies")
        self.proxies_input.textChanged.connect(self._update_count)
        proxies_layout.addWidget(self.count_label)

        layout.addWidget(proxies_group)

        # Rotation Settings Group
        rotation_group = QGroupBox("Rotation Settings")
        rotation_layout = QFormLayout(rotation_group)

        # Strategy dropdown
        self.strategy_combo = QComboBox()
        self.strategy_combo.addItem("Round Robin - Cycle through proxies in order",
                                     RotationStrategy.ROUND_ROBIN)
        self.strategy_combo.addItem("Random - Pick randomly",
                                     RotationStrategy.RANDOM)
        self.strategy_combo.addItem("Least Used - Prefer proxies with fewer requests",
                                     RotationStrategy.LEAST_USED)
        self.strategy_combo.addItem("Failover - Use first available, fallback on failure",
                                     RotationStrategy.FAILOVER)
        rotation_layout.addRow("Strategy:", self.strategy_combo)

        # Sticky sessions
        self.sticky_checkbox = QCheckBox("Keep same proxy per service (sticky sessions)")
        self.sticky_checkbox.stateChanged.connect(self._on_sticky_changed)
        rotation_layout.addRow(self.sticky_checkbox)

        # Sticky TTL
        self.sticky_ttl_spin = QSpinBox()
        self.sticky_ttl_spin.setMinimum(60)
        self.sticky_ttl_spin.setMaximum(86400)
        self.sticky_ttl_spin.setValue(3600)
        self.sticky_ttl_spin.setSuffix(" seconds")
        self.sticky_ttl_spin.setEnabled(False)
        rotation_layout.addRow("Sticky TTL:", self.sticky_ttl_spin)

        # Fallback on failure
        self.fallback_checkbox = QCheckBox("Automatically try next proxy on failure")
        self.fallback_checkbox.setChecked(True)
        rotation_layout.addRow(self.fallback_checkbox)

        # Max failures
        self.max_failures_spin = QSpinBox()
        self.max_failures_spin.setMinimum(1)
        self.max_failures_spin.setMaximum(10)
        self.max_failures_spin.setValue(3)
        self.max_failures_spin.setToolTip("Proxy disabled after this many consecutive failures")
        rotation_layout.addRow("Max Failures:", self.max_failures_spin)

        layout.addWidget(rotation_group)

        # Dialog buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self._on_save)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _update_count(self):
        """Update the proxy count label."""
        text = self.proxies_input.toPlainText().strip()
        if not text:
            self.count_label.setText("0 proxies")
            return

        count = 0
        for line in text.split('\n'):
            line = line.strip()
            if line and not line.startswith('#'):
                count += 1

        self.count_label.setText(f"{count} proxies")

    def _on_sticky_changed(self, state):
        """Handle sticky checkbox change."""
        self.sticky_ttl_spin.setEnabled(state == Qt.CheckState.Checked.value)

    def load_pool(self, pool: ProxyPool):
        """Load pool data into form fields."""
        self.name_input.setText(pool.name)
        self.enabled_checkbox.setChecked(pool.enabled)

        # Set default type
        for i in range(self.type_combo.count()):
            if self.type_combo.itemData(i) == pool.proxy_type:
                self.type_combo.setCurrentIndex(i)
                break

        # Load proxies as text
        lines = []
        for proxy in pool.proxies:
            if proxy.username and proxy.password:
                lines.append(f"{proxy.host}:{proxy.port}:{proxy.username}:{proxy.password}")
            else:
                lines.append(f"{proxy.host}:{proxy.port}")
        self.proxies_input.setPlainText('\n'.join(lines))

        # Set strategy
        for i in range(self.strategy_combo.count()):
            if self.strategy_combo.itemData(i) == pool.rotation_strategy:
                self.strategy_combo.setCurrentIndex(i)
                break

        # Other settings
        self.sticky_checkbox.setChecked(pool.sticky_sessions)
        self.sticky_ttl_spin.setValue(pool.sticky_ttl_seconds)
        self.sticky_ttl_spin.setEnabled(pool.sticky_sessions)
        self.fallback_checkbox.setChecked(pool.fallback_on_failure)
        self.max_failures_spin.setValue(pool.max_consecutive_failures)

    def _on_save(self):
        """Validate and accept dialog."""
        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Validation Error", "Pool name is required.")
            self.name_input.setFocus()
            return

        # Check we have at least one proxy
        text = self.proxies_input.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "Validation Error", "Add at least one proxy.")
            self.proxies_input.setFocus()
            return

        # Pre-parse to check for issues
        temp_pool = ProxyPool(proxy_type=self.type_combo.currentData())
        parse_result = temp_pool.add_from_text(text)
        self._last_parse_result = parse_result

        # Check if we have any valid proxies
        if parse_result.total_added == 0:
            error_msg = "No valid proxies found.\n\n"
            if parse_result.invalid_lines:
                error_msg += "All lines had errors:\n"
                for line_num, line, error in parse_result.invalid_lines[:5]:
                    truncated = line[:40] + "..." if len(line) > 40 else line
                    error_msg += f"  Line {line_num}: {truncated}\n    → {error}\n"
                if len(parse_result.invalid_lines) > 5:
                    error_msg += f"  ... and {len(parse_result.invalid_lines) - 5} more errors\n"
            QMessageBox.warning(self, "Parse Error", error_msg)
            self.proxies_input.setFocus()
            return

        # If there are issues, show confirmation
        if parse_result.had_issues:
            msg_parts = [f"Successfully parsed {parse_result.total_added} proxies."]

            if parse_result.skipped_duplicates:
                msg_parts.append(f"\nSkipped {parse_result.total_skipped} duplicates:")
                for dup in parse_result.skipped_duplicates[:3]:
                    truncated = dup[:50] + "..." if len(dup) > 50 else dup
                    msg_parts.append(f"  • {truncated}")
                if len(parse_result.skipped_duplicates) > 3:
                    msg_parts.append(f"  ... and {len(parse_result.skipped_duplicates) - 3} more")

            if parse_result.invalid_lines:
                msg_parts.append(f"\nSkipped {parse_result.total_invalid} invalid lines:")
                for line_num, line, error in parse_result.invalid_lines[:3]:
                    truncated = line[:40] + "..." if len(line) > 40 else line
                    msg_parts.append(f"  • Line {line_num}: {truncated}")
                    msg_parts.append(f"    → {error}")
                if len(parse_result.invalid_lines) > 3:
                    msg_parts.append(f"  ... and {len(parse_result.invalid_lines) - 3} more")

            msg_parts.append("\nSave anyway?")

            reply = QMessageBox.question(
                self, "Import Issues",
                '\n'.join(msg_parts),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self.accept()

    def get_pool(self) -> ProxyPool:
        """Get the configured pool."""
        if self.pool:
            pool = self.pool
            pool.name = self.name_input.text().strip()
            pool.enabled = self.enabled_checkbox.isChecked()
            pool.proxy_type = self.type_combo.currentData()
            pool.rotation_strategy = self.strategy_combo.currentData()
            pool.sticky_sessions = self.sticky_checkbox.isChecked()
            pool.sticky_ttl_seconds = self.sticky_ttl_spin.value()
            pool.fallback_on_failure = self.fallback_checkbox.isChecked()
            pool.max_consecutive_failures = self.max_failures_spin.value()
            pool.proxies.clear()
        else:
            pool = ProxyPool(
                name=self.name_input.text().strip(),
                enabled=self.enabled_checkbox.isChecked(),
                proxy_type=self.type_combo.currentData(),
                rotation_strategy=self.strategy_combo.currentData(),
                sticky_sessions=self.sticky_checkbox.isChecked(),
                sticky_ttl_seconds=self.sticky_ttl_spin.value(),
                fallback_on_failure=self.fallback_checkbox.isChecked(),
                max_consecutive_failures=self.max_failures_spin.value(),
            )

        # Use already-parsed proxies from validation if available
        if self._last_parse_result and self._last_parse_result.added:
            pool.proxies.extend(self._last_parse_result.added)
        else:
            # Fallback: parse again (shouldn't happen in normal flow)
            pool.add_from_text(self.proxies_input.toPlainText())

        return pool

    def get_parse_result(self) -> Optional[ProxyParseResult]:
        """Get the last parse result for feedback purposes."""
        return self._last_parse_result
