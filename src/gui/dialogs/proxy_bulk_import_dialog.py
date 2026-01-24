"""Bulk Proxy Import Dialog - Import proxies from text, CSV, or JSON."""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QGroupBox,
    QPushButton, QPlainTextEdit, QComboBox, QCheckBox, QTableWidget,
    QTableWidgetItem, QDialogButtonBox, QHeaderView, QFileDialog,
    QMessageBox, QTabWidget, QWidget, QProgressBar
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from typing import List, Optional, Tuple

from src.proxy.models import ProxyProfile, ProxyType
from src.proxy.bulk import (
    BulkProxyParser, ParseResult, ParseFormat,
    parse_csv_proxies, parse_json_proxies
)
from src.proxy.storage import ProxyStorage
from src.proxy.credentials import set_proxy_password


class ProxyBulkImportDialog(QDialog):
    """Dialog for bulk importing proxies from various formats."""

    def __init__(self, parent):
        """Initialize dialog.

        Args:
            parent: Parent widget
        """
        super().__init__(parent)
        self.storage = ProxyStorage()
        self.parser = BulkProxyParser()
        self.parse_results: List[ParseResult] = []

        self.setWindowTitle("Bulk Import Proxies")
        self.setModal(True)
        self.resize(700, 600)

        self.setup_ui()

    def setup_ui(self):
        """Setup the dialog UI."""
        layout = QVBoxLayout(self)

        # Tab widget for different import methods
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # Tab 1: Text Input
        text_tab = QWidget()
        text_layout = QVBoxLayout(text_tab)

        text_label = QLabel(
            "Paste proxies below (one per line). Supported formats:\n"
            "- IP:PORT (e.g., 192.168.1.1:8080)\n"
            "- IP:PORT:USER:PASS (e.g., 192.168.1.1:8080:myuser:mypass)\n"
            "- URL (e.g., http://user:pass@proxy.example.com:8080)\n"
            "- Lines starting with # are ignored as comments"
        )
        text_label.setWordWrap(True)
        text_layout.addWidget(text_label)

        self.text_input = QPlainTextEdit()
        self.text_input.setPlaceholderText(
            "192.168.1.1:8080\n"
            "10.0.0.1:3128:username:password\n"
            "socks5://user:pass@socks.example.com:1080"
        )
        self.text_input.setFont(QFont("Consolas", 10))
        text_layout.addWidget(self.text_input)

        # Default proxy type for IP:PORT format
        type_layout = QHBoxLayout()
        type_layout.addWidget(QLabel("Default proxy type (for IP:PORT format):"))
        self.default_type_combo = QComboBox()
        self.default_type_combo.addItem("HTTP", ProxyType.HTTP)
        self.default_type_combo.addItem("HTTPS", ProxyType.HTTPS)
        self.default_type_combo.addItem("SOCKS4", ProxyType.SOCKS4)
        self.default_type_combo.addItem("SOCKS5", ProxyType.SOCKS5)
        type_layout.addWidget(self.default_type_combo)
        type_layout.addStretch()
        text_layout.addLayout(type_layout)

        # Name prefix
        prefix_layout = QHBoxLayout()
        prefix_layout.addWidget(QLabel("Name prefix:"))
        from PyQt6.QtWidgets import QLineEdit
        self.prefix_input = QLineEdit("Imported")
        self.prefix_input.setMaximumWidth(200)
        prefix_layout.addWidget(self.prefix_input)
        prefix_layout.addStretch()
        text_layout.addLayout(prefix_layout)

        self.tabs.addTab(text_tab, "Text Input")

        # Tab 2: File Import
        file_tab = QWidget()
        file_layout = QVBoxLayout(file_tab)

        file_label = QLabel(
            "Import proxies from a file (CSV or JSON format).\n\n"
            "CSV columns: name, type, host, port, auth_required, username, password, enabled, bypass_list\n"
            "JSON: Array of proxy objects with same fields"
        )
        file_label.setWordWrap(True)
        file_layout.addWidget(file_label)

        # File selection
        file_select_layout = QHBoxLayout()
        self.file_path_label = QLabel("No file selected")
        self.file_path_label.setStyleSheet("color: gray;")
        file_select_layout.addWidget(self.file_path_label, 1)

        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_file)
        file_select_layout.addWidget(browse_btn)
        file_layout.addLayout(file_select_layout)

        # File content preview
        self.file_preview = QPlainTextEdit()
        self.file_preview.setReadOnly(True)
        self.file_preview.setFont(QFont("Consolas", 9))
        self.file_preview.setMaximumHeight(150)
        file_layout.addWidget(self.file_preview)

        file_layout.addStretch()
        self.tabs.addTab(file_tab, "File Import")

        # Parse button
        parse_layout = QHBoxLayout()
        parse_layout.addStretch()
        self.parse_btn = QPushButton("Parse Proxies")
        self.parse_btn.clicked.connect(self._parse_proxies)
        parse_layout.addWidget(self.parse_btn)
        layout.addLayout(parse_layout)

        # Results Group
        results_group = QGroupBox("Parse Results (Preview)")
        results_layout = QVBoxLayout(results_group)

        # Results table
        self.results_table = QTableWidget()
        self.results_table.setColumnCount(5)
        self.results_table.setHorizontalHeaderLabels(
            ["Status", "Name", "Type", "Proxy", "Error/Format"]
        )
        self.results_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Fixed)
        self.results_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Interactive)
        self.results_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Fixed)
        self.results_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch)
        self.results_table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.Interactive)
        self.results_table.setColumnWidth(0, 60)
        self.results_table.setColumnWidth(1, 120)
        self.results_table.setColumnWidth(2, 70)
        self.results_table.verticalHeader().setVisible(False)
        results_layout.addWidget(self.results_table)

        # Stats row
        self.stats_label = QLabel("No proxies parsed yet")
        results_layout.addWidget(self.stats_label)

        layout.addWidget(results_group)

        # Options
        options_layout = QHBoxLayout()
        self.skip_invalid_checkbox = QCheckBox("Skip invalid entries")
        self.skip_invalid_checkbox.setChecked(True)
        options_layout.addWidget(self.skip_invalid_checkbox)

        self.skip_duplicates_checkbox = QCheckBox("Skip duplicates (same host:port)")
        self.skip_duplicates_checkbox.setChecked(True)
        options_layout.addWidget(self.skip_duplicates_checkbox)
        options_layout.addStretch()
        layout.addLayout(options_layout)

        # Dialog buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel
        )
        button_box.button(QDialogButtonBox.StandardButton.Save).setText("Import")
        button_box.button(QDialogButtonBox.StandardButton.Save).setEnabled(False)
        button_box.accepted.connect(self._on_import)
        button_box.rejected.connect(self.reject)
        self.button_box = button_box
        layout.addWidget(button_box)

    def _browse_file(self):
        """Open file browser for CSV/JSON import."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Proxy File",
            "",
            "Proxy Files (*.csv *.json);;CSV Files (*.csv);;JSON Files (*.json);;All Files (*)"
        )

        if file_path:
            self.file_path_label.setText(file_path)
            self.file_path_label.setStyleSheet("")

            # Preview file content
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    # Show first 2000 chars
                    preview = content[:2000]
                    if len(content) > 2000:
                        preview += "\n... (truncated)"
                    self.file_preview.setPlainText(preview)
            except Exception as e:
                self.file_preview.setPlainText(f"Error reading file: {e}")

    def _parse_proxies(self):
        """Parse proxies from current input method."""
        self.parse_results.clear()

        current_tab = self.tabs.currentIndex()

        if current_tab == 0:  # Text Input
            text = self.text_input.toPlainText().strip()
            if not text:
                QMessageBox.warning(
                    self, "No Input",
                    "Please enter some proxies to parse."
                )
                return

            # Update parser default type
            self.parser.default_type = self.default_type_combo.currentData()
            prefix = self.prefix_input.text().strip() or "Imported"

            self.parse_results = self.parser.parse_text(text, prefix)

        else:  # File Import
            file_path = self.file_path_label.text()
            if file_path == "No file selected":
                QMessageBox.warning(
                    self, "No File",
                    "Please select a file to import."
                )
                return

            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                if file_path.lower().endswith('.csv'):
                    self.parse_results = parse_csv_proxies(content)
                elif file_path.lower().endswith('.json'):
                    self.parse_results = parse_json_proxies(content)
                else:
                    # Try to detect format
                    content_stripped = content.strip()
                    if content_stripped.startswith('[') or content_stripped.startswith('{'):
                        self.parse_results = parse_json_proxies(content)
                    else:
                        self.parse_results = parse_csv_proxies(content)

            except Exception as e:
                QMessageBox.critical(
                    self, "Parse Error",
                    f"Failed to parse file: {e}"
                )
                return

        # Display results
        self._display_results()

    def _display_results(self):
        """Display parse results in the table."""
        self.results_table.setRowCount(len(self.parse_results))

        success_count = 0
        error_count = 0

        for row, result in enumerate(self.parse_results):
            if result.success:
                success_count += 1
                status_item = QTableWidgetItem("OK")
                status_item.setForeground(QColor(0, 150, 0))

                name_item = QTableWidgetItem(result.profile.name)
                type_item = QTableWidgetItem(result.profile.proxy_type.value.upper())
                proxy_item = QTableWidgetItem(result.profile.get_proxy_url())
                format_item = QTableWidgetItem(result.format_detected.name if result.format_detected else "")
            else:
                error_count += 1
                status_item = QTableWidgetItem("ERROR")
                status_item.setForeground(QColor(200, 0, 0))

                name_item = QTableWidgetItem("-")
                type_item = QTableWidgetItem("-")
                proxy_item = QTableWidgetItem(result.original_line[:50] + "..." if len(result.original_line) > 50 else result.original_line)
                format_item = QTableWidgetItem(result.error or "Unknown error")
                format_item.setForeground(QColor(200, 0, 0))

            # Make items non-editable
            for item in [status_item, name_item, type_item, proxy_item, format_item]:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)

            self.results_table.setItem(row, 0, status_item)
            self.results_table.setItem(row, 1, name_item)
            self.results_table.setItem(row, 2, type_item)
            self.results_table.setItem(row, 3, proxy_item)
            self.results_table.setItem(row, 4, format_item)

        # Update stats
        self.stats_label.setText(
            f"Parsed: {len(self.parse_results)} | "
            f"Valid: {success_count} | "
            f"Errors: {error_count}"
        )

        # Enable import button if there are valid results
        self.button_box.button(QDialogButtonBox.StandardButton.Save).setEnabled(success_count > 0)

    def _on_import(self):
        """Import the parsed proxies."""
        if not self.parse_results:
            return

        # Get existing profiles for duplicate detection
        existing_profiles = self.storage.list_profiles()
        existing_hosts = {
            (p.host, p.port) for p in existing_profiles
        }

        imported_count = 0
        skipped_count = 0
        error_count = 0

        for result in self.parse_results:
            if not result.success:
                if not self.skip_invalid_checkbox.isChecked():
                    error_count += 1
                continue

            profile = result.profile

            # Check for duplicates
            if self.skip_duplicates_checkbox.isChecked():
                if (profile.host, profile.port) in existing_hosts:
                    skipped_count += 1
                    continue

            try:
                # Save profile
                self.storage.save_profile(profile)

                # Save password if available
                if result.password:
                    set_proxy_password(profile.id, result.password)

                # Add to existing hosts for future duplicate checks
                existing_hosts.add((profile.host, profile.port))
                imported_count += 1

            except Exception as e:
                error_count += 1

        # Show result message
        message = f"Imported {imported_count} proxies successfully."
        if skipped_count > 0:
            message += f"\nSkipped {skipped_count} duplicates."
        if error_count > 0:
            message += f"\n{error_count} errors occurred."

        if error_count > 0:
            QMessageBox.warning(self, "Import Complete", message)
        else:
            QMessageBox.information(self, "Import Complete", message)

        self.accept()

    def get_imported_count(self) -> int:
        """Get the number of successfully imported proxies."""
        return sum(1 for r in self.parse_results if r.success)
