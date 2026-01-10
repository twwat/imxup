#!/usr/bin/env python3
"""
Statistics Dialog
Shows comprehensive application usage statistics from QSettings and MetricsStore
"""

import time
from typing import Optional

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QDialogButtonBox, QApplication, QGridLayout, QGroupBox,
    QTabWidget, QWidget, QTableWidget, QTableWidgetItem, QHeaderView,
    QComboBox
)
from PyQt6.QtCore import Qt, QSettings

from src.utils.format_utils import format_binary_size, format_binary_rate, format_duration
from src.utils.logger import log


class StatisticsDialog(QDialog):
    """Dialog displaying comprehensive application statistics.

    Shows upload totals, scanner stats, session information, speed records,
    and per-host file upload statistics. Uses a tabbed interface with
    General stats and File Hosts tabs.

    Attributes:
        _session_start_time: Time when the current session started (for live calculation)
    """

    def __init__(self, parent=None, session_start_time: Optional[float] = None):
        """Initialize the Statistics Dialog.

        Args:
            parent: Parent widget for the dialog
            session_start_time: Unix timestamp when current session started.
                               Falls back to current time if not provided.
        """
        super().__init__(parent)
        self._session_start_time = session_start_time or time.time()

        self.setWindowTitle("Application Statistics")
        self.setModal(True)
        self.setMinimumSize(700, 420)
        self.resize(750, 480)
        self._center_on_parent()

        self._setup_ui()
        self._load_stats()

    def _center_on_parent(self) -> None:
        """Center dialog on parent window or screen."""
        parent_widget = self.parent()
        if parent_widget:
            if hasattr(parent_widget, 'geometry'):
                parent_geo = parent_widget.geometry()
                dialog_geo = self.frameGeometry()
                x = parent_geo.x() + (parent_geo.width() - dialog_geo.width()) // 2
                y = parent_geo.y() + (parent_geo.height() - dialog_geo.height()) // 2
                self.move(x, y)
        else:
            screen = QApplication.primaryScreen()
            if screen:
                screen_geo = screen.geometry()
                dialog_geo = self.frameGeometry()
                x = (screen_geo.width() - dialog_geo.width()) // 2
                y = (screen_geo.height() - dialog_geo.height()) // 2
                self.move(x, y)

    def _setup_ui(self) -> None:
        """Initialize the dialog UI with tabbed layout."""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)

        # Create tab widget
        self._tab_widget = QTabWidget()

        # Tab 1: General Statistics
        general_tab = self._create_general_tab()
        self._tab_widget.addTab(general_tab, "General")

        # Tab 2: File Host Statistics
        file_hosts_tab = self._create_file_hosts_tab()
        self._tab_widget.addTab(file_hosts_tab, "File Hosts")

        main_layout.addWidget(self._tab_widget)

        # Close button
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.rejected.connect(self.reject)
        main_layout.addWidget(button_box)

    def _create_general_tab(self) -> QWidget:
        """Create the General statistics tab content.

        Returns:
            QWidget containing Session, Uploads, and Scanner groups
        """
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)

        # Two-column layout
        columns_layout = QHBoxLayout()
        columns_layout.setSpacing(15)

        # Left column: Session + Uploads
        left_column = QVBoxLayout()
        left_column.setSpacing(10)
        left_column.addWidget(self._create_session_group())
        left_column.addWidget(self._create_upload_group())
        left_column.addStretch()

        # Right column: IMX Status Scanner
        right_column = QVBoxLayout()
        right_column.setSpacing(10)
        right_column.addWidget(self._create_scanner_group())
        right_column.addStretch()

        columns_layout.addLayout(left_column, 1)
        columns_layout.addLayout(right_column, 1)

        layout.addLayout(columns_layout)
        return tab

    def _create_file_hosts_tab(self) -> QWidget:
        """Create the File Hosts statistics tab content.

        Returns:
            QWidget containing file host statistics table with timeframe filter
        """
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)

        # Timeframe filter row
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Timeframe:"))

        self._timeframe_combo = QComboBox()
        self._timeframe_combo.addItem("All Time", "all_time")
        self._timeframe_combo.addItem("This Session", "session")
        self._timeframe_combo.addItem("Today", "today")
        self._timeframe_combo.addItem("Last 7 Days", "week")
        self._timeframe_combo.addItem("Last 30 Days", "month")
        self._timeframe_combo.setCurrentIndex(0)  # Default to All Time
        self._timeframe_combo.setMinimumWidth(120)
        self._timeframe_combo.currentIndexChanged.connect(self._on_timeframe_changed)

        filter_layout.addWidget(self._timeframe_combo)
        filter_layout.addStretch()
        layout.addLayout(filter_layout)

        # Create table
        self._file_hosts_table = QTableWidget()
        self._file_hosts_table.setColumnCount(7)
        self._file_hosts_table.setHorizontalHeaderLabels([
            "Host", "Files", "Failed",
            "Data Uploaded", "Peak Speed", "Avg Speed", "Success"
        ])

        # Configure table appearance
        self._file_hosts_table.setAlternatingRowColors(True)
        self._file_hosts_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._file_hosts_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._file_hosts_table.verticalHeader().setVisible(False)

        # Configure column widths
        header = self._file_hosts_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)  # Host stretches
        for col in range(1, 7):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)

        layout.addWidget(self._file_hosts_table)
        return tab

    def _create_session_group(self) -> QGroupBox:
        """Create the session statistics group box.

        Returns:
            QGroupBox containing session stats
        """
        group = QGroupBox("Session")
        grid = QGridLayout(group)
        grid.setColumnStretch(1, 1)

        self._app_startups_label = QLabel("0")
        self._first_startup_label = QLabel("N/A")
        self._current_session_label = QLabel("0s")
        self._total_time_label = QLabel("0s")
        self._avg_session_label = QLabel("0s")

        grid.addWidget(QLabel("App Startups:"), 0, 0)
        grid.addWidget(self._app_startups_label, 0, 1, Qt.AlignmentFlag.AlignRight)

        grid.addWidget(QLabel("First Startup:"), 1, 0)
        grid.addWidget(self._first_startup_label, 1, 1, Qt.AlignmentFlag.AlignRight)

        grid.addWidget(QLabel("Current Session:"), 2, 0)
        grid.addWidget(self._current_session_label, 2, 1, Qt.AlignmentFlag.AlignRight)

        grid.addWidget(QLabel("Total Time Open:"), 3, 0)
        grid.addWidget(self._total_time_label, 3, 1, Qt.AlignmentFlag.AlignRight)

        grid.addWidget(QLabel("Avg Session Length:"), 4, 0)
        grid.addWidget(self._avg_session_label, 4, 1, Qt.AlignmentFlag.AlignRight)

        return group

    def _create_upload_group(self) -> QGroupBox:
        """Create the upload statistics group box.

        Returns:
            QGroupBox containing upload stats
        """
        group = QGroupBox("Uploads")
        grid = QGridLayout(group)
        grid.setColumnStretch(1, 1)

        self._total_galleries_label = QLabel("0")
        self._total_images_label = QLabel("0")
        self._total_size_label = QLabel("0 B")
        self._fastest_speed_label = QLabel("N/A")
        self._fastest_timestamp_label = QLabel("")

        grid.addWidget(QLabel("Total Galleries:"), 0, 0)
        grid.addWidget(self._total_galleries_label, 0, 1, Qt.AlignmentFlag.AlignRight)

        grid.addWidget(QLabel("Total Images:"), 1, 0)
        grid.addWidget(self._total_images_label, 1, 1, Qt.AlignmentFlag.AlignRight)

        grid.addWidget(QLabel("Total Data:"), 2, 0)
        grid.addWidget(self._total_size_label, 2, 1, Qt.AlignmentFlag.AlignRight)

        grid.addWidget(QLabel("Fastest Speed:"), 3, 0)
        grid.addWidget(self._fastest_speed_label, 3, 1, Qt.AlignmentFlag.AlignRight)

        grid.addWidget(QLabel("Record Set:"), 4, 0)
        grid.addWidget(self._fastest_timestamp_label, 4, 1, Qt.AlignmentFlag.AlignRight)

        return group

    def _create_scanner_group(self) -> QGroupBox:
        """Create the image scanner statistics group box.

        Returns:
            QGroupBox containing scanner stats
        """
        group = QGroupBox("IMX Status Scanner")
        grid = QGridLayout(group)
        grid.setColumnStretch(1, 1)

        self._total_scans_label = QLabel("0")
        self._galleries_scanned_label = QLabel("0")
        self._images_checked_label = QLabel("0")
        self._online_galleries_label = QLabel("0")
        self._partial_galleries_label = QLabel("0")
        self._offline_galleries_label = QLabel("0")
        self._online_images_label = QLabel("0")
        self._offline_images_label = QLabel("0")

        row = 0
        grid.addWidget(QLabel("Total Scans:"), row, 0)
        grid.addWidget(self._total_scans_label, row, 1, Qt.AlignmentFlag.AlignRight)

        row += 1
        grid.addWidget(QLabel("Galleries Scanned:"), row, 0)
        grid.addWidget(self._galleries_scanned_label, row, 1, Qt.AlignmentFlag.AlignRight)

        row += 1
        grid.addWidget(QLabel("Images Checked:"), row, 0)
        grid.addWidget(self._images_checked_label, row, 1, Qt.AlignmentFlag.AlignRight)

        # Galleries breakdown
        row += 1
        grid.addWidget(QLabel("Online Galleries:"), row, 0)
        grid.addWidget(self._online_galleries_label, row, 1, Qt.AlignmentFlag.AlignRight)

        row += 1
        grid.addWidget(QLabel("Partial Galleries:"), row, 0)
        grid.addWidget(self._partial_galleries_label, row, 1, Qt.AlignmentFlag.AlignRight)

        row += 1
        grid.addWidget(QLabel("Offline Galleries:"), row, 0)
        grid.addWidget(self._offline_galleries_label, row, 1, Qt.AlignmentFlag.AlignRight)

        # Images breakdown
        row += 1
        grid.addWidget(QLabel("Online Images:"), row, 0)
        grid.addWidget(self._online_images_label, row, 1, Qt.AlignmentFlag.AlignRight)

        row += 1
        grid.addWidget(QLabel("Offline Images:"), row, 0)
        grid.addWidget(self._offline_images_label, row, 1, Qt.AlignmentFlag.AlignRight)

        return group

    def _load_stats(self) -> None:
        """Load all statistics from QSettings and display."""
        settings = QSettings("ImxUploader", "Stats")
        # Session stats
        app_startups = settings.value("app_startup_count", 0, type=int)
        first_startup = settings.value("first_startup_timestamp", "")
        stored_time = settings.value("total_session_time_seconds", 0, type=int)

        # Calculate and display current session time
        current_session = int(time.time() - self._session_start_time)
        total_time = stored_time + current_session

        self._app_startups_label.setText(f"{app_startups:,}")
        self._first_startup_label.setText(first_startup if first_startup else "N/A")
        self._current_session_label.setText(format_duration(current_session))
        self._total_time_label.setText(format_duration(total_time))

        # Calculate and display average session length
        avg_session_seconds = total_time // max(1, app_startups)
        self._avg_session_label.setText(format_duration(avg_session_seconds))

        # Upload stats
        total_galleries = settings.value("total_galleries", 0, type=int)
        total_images = settings.value("total_images", 0, type=int)

        # Handle both v2 (string) and legacy (int) formats
        total_size_str = settings.value("total_size_bytes_v2", "0")
        try:
            total_size = int(total_size_str)
        except (ValueError, TypeError):
            total_size = settings.value("total_size_bytes", 0, type=int)

        fastest_kbps = settings.value("fastest_kbps", 0.0, type=float)
        fastest_timestamp = settings.value("fastest_kbps_timestamp", "")

        self._total_galleries_label.setText(f"{total_galleries:,}")
        self._total_images_label.setText(f"{total_images:,}")
        self._total_size_label.setText(format_binary_size(total_size))

        if fastest_kbps > 0:
            # Use format_binary_rate for consistency with File Hosts tab
            self._fastest_speed_label.setText(format_binary_rate(fastest_kbps))
        else:
            self._fastest_speed_label.setText("N/A")

        self._fastest_timestamp_label.setText(fastest_timestamp if fastest_timestamp else "N/A")

        # Scanner stats
        total_scans = settings.value("checker_total_scans", 0, type=int)
        online_galleries = settings.value("checker_online_galleries", 0, type=int)
        partial_galleries = settings.value("checker_partial_galleries", 0, type=int)
        offline_galleries = settings.value("checker_offline_galleries", 0, type=int)
        online_images = settings.value("checker_online_images", 0, type=int)
        offline_images = settings.value("checker_offline_images", 0, type=int)

        # Calculate totals
        galleries_scanned = online_galleries + partial_galleries + offline_galleries
        images_checked = online_images + offline_images

        self._total_scans_label.setText(f"{total_scans:,}")
        self._galleries_scanned_label.setText(f"{galleries_scanned:,}")
        self._images_checked_label.setText(f"{images_checked:,}")

        self._online_galleries_label.setText(f"{online_galleries:,}")
        self._partial_galleries_label.setText(f"{partial_galleries:,}")
        self._offline_galleries_label.setText(f"{offline_galleries:,}")

        self._online_images_label.setText(f"{online_images:,}")
        self._offline_images_label.setText(f"{offline_images:,}")

        # Apply theme-aware colors to status labels via QSS properties
        self._online_galleries_label.setProperty("online-status", "online")
        self._online_galleries_label.style().unpolish(self._online_galleries_label)
        self._online_galleries_label.style().polish(self._online_galleries_label)
        
        self._online_images_label.setProperty("online-status", "online")
        self._online_images_label.style().unpolish(self._online_images_label)
        self._online_images_label.style().polish(self._online_images_label)
        
        self._partial_galleries_label.setProperty("online-status", "partial")
        self._partial_galleries_label.style().unpolish(self._partial_galleries_label)
        self._partial_galleries_label.style().polish(self._partial_galleries_label)
        
        self._offline_galleries_label.setProperty("online-status", "offline")
        self._offline_galleries_label.style().unpolish(self._offline_galleries_label)
        self._offline_galleries_label.style().polish(self._offline_galleries_label)
        
        self._offline_images_label.setProperty("online-status", "offline")
        self._offline_images_label.style().unpolish(self._offline_images_label)
        self._offline_images_label.style().polish(self._offline_images_label)

        # Load file host statistics
        self._load_file_host_stats()

    def _on_timeframe_changed(self, index: int) -> None:
        """Handle timeframe filter selection change.

        Args:
            index: New combo box index (unused, we read currentData instead)
        """
        self._load_file_host_stats()

    def _load_file_host_stats(self) -> None:
        """Load file host statistics into the table for the selected timeframe."""
        # Get selected period from combo box
        period = "all_time"
        if hasattr(self, '_timeframe_combo'):
            period = self._timeframe_combo.currentData() or "all_time"

        try:
            from src.utils.metrics_store import get_metrics_store
            metrics_store = get_metrics_store()
            host_stats = metrics_store.get_hosts_for_period(period)
        except (ImportError, RuntimeError, OSError) as e:
            log(f"Failed to load file host metrics: {type(e).__name__}: {e}",
                level="warning", category="stats")
            self._file_hosts_table.setRowCount(1)
            item = QTableWidgetItem("Unable to load file host statistics")
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._file_hosts_table.setItem(0, 0, item)
            self._file_hosts_table.setSpan(0, 0, 1, 7)
            return

        if not host_stats:
            self._file_hosts_table.setRowCount(1)
            period_name = self._timeframe_combo.currentText() if hasattr(self, '_timeframe_combo') else "All Time"
            item = QTableWidgetItem(f"No file host uploads for {period_name}")
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._file_hosts_table.setItem(0, 0, item)
            self._file_hosts_table.setSpan(0, 0, 1, 7)
            return

        # Sort hosts by files_uploaded descending
        sorted_hosts = sorted(
            host_stats.items(),
            key=lambda x: x[1].get('files_uploaded', 0),
            reverse=True
        )

        self._file_hosts_table.setRowCount(len(sorted_hosts))

        for row, (host_name, metrics) in enumerate(sorted_hosts):
            # Host name (capitalize for display)
            host_item = QTableWidgetItem(host_name.title())
            self._file_hosts_table.setItem(row, 0, host_item)

            # Files Uploaded
            files_up = QTableWidgetItem(f"{metrics.get('files_uploaded', 0):,}")
            files_up.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._file_hosts_table.setItem(row, 1, files_up)

            # Files Failed
            files_fail = QTableWidgetItem(f"{metrics.get('files_failed', 0):,}")
            files_fail.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._file_hosts_table.setItem(row, 2, files_fail)

            # Data Uploaded (bytes)
            data_up = QTableWidgetItem(format_binary_size(metrics.get('bytes_uploaded', 0)))
            data_up.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._file_hosts_table.setItem(row, 3, data_up)

            # Peak Speed: MetricsStore stores B/s, format_binary_rate expects KiB/s
            peak_speed_bps = metrics.get('peak_speed', 0)
            peak_kbps = peak_speed_bps / 1024
            peak_item = QTableWidgetItem(format_binary_rate(peak_kbps))
            peak_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._file_hosts_table.setItem(row, 4, peak_item)

            # Avg Speed: MetricsStore stores B/s, format_binary_rate expects KiB/s
            avg_speed_bps = metrics.get('avg_speed', 0)
            avg_kbps = avg_speed_bps / 1024
            avg_item = QTableWidgetItem(format_binary_rate(avg_kbps))
            avg_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._file_hosts_table.setItem(row, 5, avg_item)

            # Success Rate
            success_rate = metrics.get('success_rate', 100.0)
            rate_item = QTableWidgetItem(f"{success_rate:.1f}%")
            rate_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._file_hosts_table.setItem(row, 6, rate_item)

