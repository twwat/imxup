#!/usr/bin/env python3
"""
Image Status Dialog
Shows results of checking image online status on IMX.to
"""

import time
from typing import List, Dict, Any
from datetime import datetime

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QPushButton, QLabel, QProgressBar, QWidget, QFrame,
    QAbstractItemView, QApplication, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter, QPaintEvent

from src.gui.theme_manager import get_online_status_colors
from src.utils.logger import log


class ProportionalBar(QWidget):
    """A progress bar that shows multiple colored segments proportionally.

    Can display 2 segments (online/offline for images) or 3 segments
    (online/partial/offline for galleries).
    """

    def __init__(self, parent=None):
        """Initialize the proportional bar.

        Args:
            parent: Parent widget
        """
        super().__init__(parent)
        self.setMinimumHeight(20)
        self.setMaximumHeight(24)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        # Segment values (will be normalized to percentages)
        self._segments: List[tuple] = []  # List of (value, QColor)
        self._total = 0
        self._indeterminate = True
        self._animation_offset = 0

        # Animation timer for indeterminate state
        self._animation_timer = QTimer(self)
        self._animation_timer.timeout.connect(self._animate)

    def set_indeterminate(self, indeterminate: bool) -> None:
        """Set whether the bar shows indeterminate (pulsing) animation.

        Args:
            indeterminate: True for pulsing animation, False for segments
        """
        self._indeterminate = indeterminate
        if indeterminate:
            self._animation_timer.start(50)
        else:
            self._animation_timer.stop()
        self.update()

    def set_segments(self, segments: List[tuple]) -> None:
        """Set the colored segments to display.

        Args:
            segments: List of (value, QColor) tuples. Values are counts,
                     will be normalized to percentages automatically.
        """
        self._segments = segments
        self._total = sum(s[0] for s in segments)
        self._indeterminate = False
        self._animation_timer.stop()
        self.update()

    def _animate(self) -> None:
        """Animate the indeterminate state."""
        self._animation_offset = (self._animation_offset + 5) % 200
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        """Paint the proportional bar.

        Args:
            event: Paint event
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect()
        width = rect.width()
        height = rect.height()

        # Draw background
        bg_color = QColor("#3a3a3a") if self._is_dark_mode() else QColor("#e0e0e0")
        painter.fillRect(rect, bg_color)

        # Clip to widget bounds to prevent painting outside
        painter.setClipRect(rect)

        if self._indeterminate:
            # Draw pulsing animation
            pulse_color = QColor("#4a90d9")
            pulse_width = width // 3
            x = (self._animation_offset - 100) * width // 100
            painter.fillRect(x, 0, pulse_width, height, pulse_color)
        elif self._total > 0:
            # Draw proportional segments
            x = 0
            for i, (value, color) in enumerate(self._segments):
                segment_width = int(width * value / self._total)
                # Last non-zero segment takes remaining width to avoid rounding gaps
                if i == len(self._segments) - 1 or (
                    i < len(self._segments) - 1 and
                    all(s[0] == 0 for s in self._segments[i+1:])
                ):
                    segment_width = width - x
                if value > 0:
                    painter.fillRect(x, 0, segment_width, height, color)
                    x += segment_width

        # Draw border
        border_color = QColor("#555") if self._is_dark_mode() else QColor("#999")
        painter.setPen(border_color)
        painter.drawRect(0, 0, width - 1, height - 1)

        painter.end()

    def _is_dark_mode(self) -> bool:
        """Check if dark mode is active."""
        from src.gui.theme_manager import is_dark_mode
        return is_dark_mode()

    def stop_animation(self) -> None:
        """Stop any running animation."""
        self._animation_timer.stop()


class NumericTableItem(QTableWidgetItem):
    """QTableWidgetItem subclass that sorts numerically instead of alphabetically."""

    def __lt__(self, other: QTableWidgetItem) -> bool:
        """Compare items numerically for sorting."""
        try:
            return int(self.text()) < int(other.text())
        except ValueError:
            return super().__lt__(other)


class ImageStatusDialog(QDialog):
    """Dialog showing image online status check results.

    Features a two-bar display for images and galleries status,
    with a detailed statistics panel and results table.
    """

    check_requested = pyqtSignal(list)
    cancelled = pyqtSignal()

    def __init__(self, parent=None):
        """Initialize the Image Status Dialog."""
        super().__init__(parent)
        self.setWindowTitle("Check Image Status - IMX.to")
        self.setModal(True)
        self.setMinimumSize(750, 450)
        self.resize(900, 550)
        self._center_on_parent()

        self._results: Dict[str, Dict[str, Any]] = {}
        self._start_time: float = 0
        self._setup_ui()

    def _center_on_parent(self) -> None:
        """Center dialog on parent window or screen."""
        parent_widget = self.parent()
        if parent_widget and hasattr(parent_widget, 'geometry'):
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
        """Initialize the dialog UI with new layout."""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Get theme colors
        self._colors = get_online_status_colors()

        # === Top Section: Progress Bars ===
        bars_widget = QWidget()
        bars_layout = QGridLayout(bars_widget)
        bars_layout.setContentsMargins(0, 0, 0, 0)
        bars_layout.setSpacing(8)

        # Images bar row
        images_label = QLabel("Images:")
        images_label.setFixedWidth(70)
        self.images_bar = ProportionalBar()
        self.images_status_label = QLabel("")
        self.images_status_label.setMinimumWidth(200)

        bars_layout.addWidget(images_label, 0, 0)
        bars_layout.addWidget(self.images_bar, 0, 1)
        bars_layout.addWidget(self.images_status_label, 0, 2)

        # Galleries bar row
        galleries_label = QLabel("Galleries:")
        galleries_label.setFixedWidth(70)
        self.galleries_bar = ProportionalBar()
        self.galleries_status_label = QLabel("")
        self.galleries_status_label.setMinimumWidth(200)

        bars_layout.addWidget(galleries_label, 1, 0)
        bars_layout.addWidget(self.galleries_bar, 1, 1)
        bars_layout.addWidget(self.galleries_status_label, 1, 2)

        # Elapsed time (top right)
        self.elapsed_label = QLabel("Elapsed: 0.0s")
        self.elapsed_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        bars_layout.addWidget(self.elapsed_label, 0, 3)

        # Spinner status
        self.spinner_label = QLabel("")
        self.spinner_label.setProperty("class", "status-muted")
        bars_layout.addWidget(self.spinner_label, 1, 3)

        bars_layout.setColumnStretch(1, 1)  # Bar column stretches
        layout.addWidget(bars_widget)

        # Elapsed time timer
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.timeout.connect(self._update_elapsed)

        # === Statistics Section (3 columns) ===
        self.stats_frame = QFrame()
        self.stats_frame.setFrameStyle(QFrame.Shape.StyledPanel)
        stats_layout = QGridLayout(self.stats_frame)
        stats_layout.setSpacing(8)
        stats_layout.setContentsMargins(10, 10, 10, 10)

        # Column 1: Totals
        stats_layout.addWidget(QLabel("<b>Summary</b>"), 0, 0)
        self.stat_galleries_scanned = self._create_stat_row("Galleries Scanned:", "—")
        self.stat_images_checked = self._create_stat_row("Images Checked:", "—")
        stats_layout.addWidget(self.stat_galleries_scanned, 1, 0)
        stats_layout.addWidget(self.stat_images_checked, 2, 0)

        # Column 2: Gallery breakdown
        stats_layout.addWidget(QLabel("<b>Galleries</b>"), 0, 1)
        self.stat_online_galleries = self._create_stat_row("Online:", "—", "online")
        self.stat_partial_galleries = self._create_stat_row("Partial:", "—", "partial")
        self.stat_offline_galleries = self._create_stat_row("Offline:", "—", "offline")
        stats_layout.addWidget(self.stat_online_galleries, 1, 1)
        stats_layout.addWidget(self.stat_partial_galleries, 2, 1)
        stats_layout.addWidget(self.stat_offline_galleries, 3, 1)

        # Column 3: Image breakdown
        stats_layout.addWidget(QLabel("<b>Images</b>"), 0, 2)
        self.stat_online_images = self._create_stat_row("Online:", "—", "online")
        self.stat_offline_images = self._create_stat_row("Offline:", "—", "offline")
        stats_layout.addWidget(self.stat_online_images, 1, 2)
        stats_layout.addWidget(self.stat_offline_images, 2, 2)

        # Equal column widths
        for col in range(3):
            stats_layout.setColumnStretch(col, 1)

        layout.addWidget(self.stats_frame)

        # === Results Table (hidden initially) ===
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["DB ID", "Name", "Images", "Online", "Offline", "Status"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)

        self.table.verticalHeader().setVisible(False)
        self.table.setVisible(False)  # Hidden until scan complete
        layout.addWidget(self.table)

        # === Buttons ===
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self._on_cancel)
        self.cancel_btn.setVisible(False)
        button_layout.addWidget(self.cancel_btn)

        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.accept)
        button_layout.addWidget(self.close_btn)

        layout.addLayout(button_layout)

    def _create_stat_row(self, label: str, value: str, status: str = None) -> QWidget:
        """Create a stat row widget with label and value.

        Args:
            label: Label text
            value: Value text
            status: Optional status for styling ('online', 'partial', 'offline')

        Returns:
            Widget containing the stat row
        """
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        label_widget = QLabel(label)
        value_widget = QLabel(value)
        value_widget.setAlignment(Qt.AlignmentFlag.AlignRight)

        if status:
            value_widget.setProperty("online-status", status)
            value_widget.style().unpolish(value_widget)
            value_widget.style().polish(value_widget)

        layout.addWidget(label_widget)
        layout.addStretch()
        layout.addWidget(value_widget)

        # Store reference to value label for updates
        widget.value_label = value_widget
        return widget

    def _update_stat(self, stat_widget: QWidget, value: str) -> None:
        """Update a stat widget's value.

        Args:
            stat_widget: The stat row widget
            value: New value text
        """
        if hasattr(stat_widget, 'value_label'):
            stat_widget.value_label.setText(value)

    def set_galleries(self, galleries: List[Dict[str, Any]]) -> None:
        """Set galleries to be checked and display in table.

        Args:
            galleries: List of dicts with keys: db_id, path, name, total_images
        """
        self.table.setRowCount(len(galleries))

        for row, gallery in enumerate(galleries):
            db_id = gallery.get('db_id', 0)
            name = gallery.get('name', '')
            total = gallery.get('total_images', 0)
            path = gallery.get('path', '')

            id_item = QTableWidgetItem(str(db_id))
            id_item.setData(Qt.ItemDataRole.UserRole, path)
            id_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, 0, id_item)

            name_item = QTableWidgetItem(name)
            name_item.setData(Qt.ItemDataRole.UserRole, path)
            self.table.setItem(row, 1, name_item)

            images_item = NumericTableItem(str(total))
            images_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, 2, images_item)

            online_item = NumericTableItem("0")
            online_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, 3, online_item)

            offline_item = NumericTableItem("0")
            offline_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, 4, offline_item)

            status_item = QTableWidgetItem("Pending...")
            self.table.setItem(row, 5, status_item)

        self.table.sortItems(4, Qt.SortOrder.DescendingOrder)

    def show_progress(self, visible: bool = True) -> None:
        """Show or hide the progress indicators.

        Args:
            visible: Whether to show the progress indicators
        """
        if visible:
            self.cancel_btn.setVisible(True)
            self.cancel_btn.setEnabled(True)
            self.cancel_btn.setText("Cancel")
            self.close_btn.setVisible(False)

            # Start with indeterminate bars
            self.images_bar.set_indeterminate(True)
            self.galleries_bar.set_indeterminate(True)
            self.images_status_label.setText("Scanning...")
            self.galleries_status_label.setText("Scanning...")
            self.spinner_label.setText("Checking image status...")

            # Start elapsed timer
            self._start_time = time.time()
            self._elapsed_timer.start(100)  # Update every 100ms
        else:
            self.cancel_btn.setVisible(False)
            self.close_btn.setVisible(True)
            self._elapsed_timer.stop()
            self.spinner_label.setText("")

    def _update_elapsed(self) -> None:
        """Update the elapsed time display."""
        if self._start_time > 0:
            elapsed = time.time() - self._start_time
            self.elapsed_label.setText(f"Elapsed: {elapsed:.1f}s")

    def update_progress(self, current: int, total: int) -> None:
        """Legacy method for progress updates.

        Progress is now shown via proportional bars and quick_count.
        This method exists for backward compatibility with the checker.

        Args:
            current: Current progress value (unused)
            total: Total progress value (unused)
        """
        pass  # Progress now communicated via show_quick_count() and set_results()

    def show_quick_count(self, online: int, total: int) -> None:
        """Display quick count result as soon as it's available.

        Args:
            online: Number of images found online
            total: Total images submitted for checking
        """
        if total <= 0:
            return

        offline = total - online
        pct = (online * 100) // total

        # Update images bar with green/red segments
        self.images_bar.set_segments([
            (online, self._colors["online"]),
            (offline, self._colors["offline"])
        ])

        # Update images status label
        self.images_status_label.setText(
            f"<span style='color:{self._colors["online"].name()}'>{online:,} online</span>, "
            f"<span style='color:{self._colors["offline"].name()}'>{offline:,} offline</span> "
            f"({pct}%)"
        )
        self.images_status_label.setTextFormat(Qt.TextFormat.RichText)

        # Update stats
        self._update_stat(self.stat_images_checked, f"{total:,}")
        self._update_stat(self.stat_online_images, f"{online:,} ({pct}%)")
        self._update_stat(self.stat_offline_images, f"{offline:,} ({100-pct}%)")

        if online == total:
            # All online - can update galleries too
            galleries_count = self.table.rowCount()
            self.galleries_bar.set_segments([
                (galleries_count, self._colors["online"]),
                (0, self._colors["partial"]),
                (0, self._colors["offline"])
            ])
            self.galleries_status_label.setText(
                f"<span style='color:{self._colors["online"].name()}'>{galleries_count:,} online</span>"
            )
            self.galleries_status_label.setTextFormat(Qt.TextFormat.RichText)
            self._update_stat(self.stat_galleries_scanned, f"{galleries_count:,}")
            self._update_stat(self.stat_online_galleries, f"{galleries_count:,} (100%)")
            self._update_stat(self.stat_partial_galleries, "0")
            self._update_stat(self.stat_offline_galleries, "0")
            self.spinner_label.setText("All images online!")
        else:
            # Still scanning to identify which galleries have offline images
            self.spinner_label.setText(f"Identifying {offline:,} offline images...")

    def set_results(self, results: Dict[str, Dict[str, Any]], elapsed_time: float = 0.0) -> None:
        """Set check results and update the table.

        Args:
            results: Dict keyed by gallery path with check results
            elapsed_time: Time taken for the check in seconds
        """
        self._elapsed_timer.stop()
        colors = get_online_status_colors()
        self._results = results

        # Build path-to-row index
        path_to_row: Dict[str, int] = {}
        for row in range(self.table.rowCount()):
            id_item = self.table.item(row, 0)
            if id_item:
                path = id_item.data(Qt.ItemDataRole.UserRole)
                if path:
                    path_to_row[path] = row

        # Disable updates for performance
        self.table.setUpdatesEnabled(False)
        self.table.setSortingEnabled(False)
        self.table.blockSignals(True)

        header = self.table.horizontalHeader()
        original_modes = []
        for col in range(self.table.columnCount()):
            original_modes.append(header.sectionResizeMode(col))
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)

        try:
            # Calculate aggregates
            total_galleries = 0
            total_images = 0
            total_online = 0
            total_offline = 0
            galleries_online = 0
            galleries_partial = 0
            galleries_offline = 0

            for path, result in results.items():
                row = path_to_row.get(path)
                if row is None:
                    continue

                total_galleries += 1
                online = result.get('online', 0)
                offline = result.get('offline', 0)
                total = result.get('total', 0)

                total_images += total
                total_online += online
                total_offline += offline

                if total > 0:
                    if online == total:
                        galleries_online += 1
                    elif online == 0:
                        galleries_offline += 1
                    else:
                        galleries_partial += 1

                # Update table cells
                online_item = self.table.item(row, 3)
                offline_item = self.table.item(row, 4)
                status_item = self.table.item(row, 5)

                if online_item:
                    online_item.setText(str(online))

                if offline_item:
                    offline_item.setText(str(offline))
                    if offline > 0:
                        offline_item.setForeground(colors['offline'])
                        bold_font = QFont()
                        bold_font.setBold(True)
                        offline_item.setFont(bold_font)

                if status_item:
                    if total == 0:
                        status_text, color = "No images", colors['gray']
                    elif online == total:
                        status_text, color = "Online", colors['online']
                    elif online == 0:
                        status_text, color = "Offline", colors['offline']
                    else:
                        status_text, color = "Partial", colors['partial']

                    status_item.setText(status_text)
                    status_item.setForeground(color)

            # Update galleries bar
            self.galleries_bar.set_segments([
                (galleries_online, colors['online']),
                (galleries_partial, colors['partial']),
                (galleries_offline, colors['offline'])
            ])

            # Update galleries status label
            gal_parts = []
            if galleries_online > 0:
                gal_parts.append(f"<span style='color:{colors['online'].name()}'>{galleries_online:,} online</span>")
            if galleries_partial > 0:
                gal_parts.append(f"<span style='color:{colors['partial'].name()}'>{galleries_partial:,} partial</span>")
            if galleries_offline > 0:
                gal_parts.append(f"<span style='color:{colors['offline'].name()}'>{galleries_offline:,} offline</span>")
            self.galleries_status_label.setText(", ".join(gal_parts))
            self.galleries_status_label.setTextFormat(Qt.TextFormat.RichText)

            # Update images bar (in case quick count wasn't available)
            self.images_bar.set_segments([
                (total_online, colors['online']),
                (total_offline, colors['offline'])
            ])

            img_pct = (total_online * 100 // total_images) if total_images else 0
            self.images_status_label.setText(
                f"<span style='color:{colors['online'].name()}'>{total_online:,} online</span>, "
                f"<span style='color:{colors['offline'].name()}'>{total_offline:,} offline</span> "
                f"({img_pct}%)"
            )
            self.images_status_label.setTextFormat(Qt.TextFormat.RichText)

            # Update all stats
            self._update_stat(self.stat_galleries_scanned, f"{total_galleries:,}")
            self._update_stat(self.stat_images_checked, f"{total_images:,}")

            gal_total = total_galleries if total_galleries > 0 else 1
            self._update_stat(self.stat_online_galleries, f"{galleries_online:,} ({galleries_online*100//gal_total}%)")
            self._update_stat(self.stat_partial_galleries, f"{galleries_partial:,} ({galleries_partial*100//gal_total}%)")
            self._update_stat(self.stat_offline_galleries, f"{galleries_offline:,} ({galleries_offline*100//gal_total}%)")

            img_total = total_images if total_images > 0 else 1
            self._update_stat(self.stat_online_images, f"{total_online:,} ({total_online*100//img_total}%)")
            self._update_stat(self.stat_offline_images, f"{total_offline:,} ({total_offline*100//img_total}%)")

            # Update elapsed time with final value
            self.elapsed_label.setText(f"Elapsed: {elapsed_time:.1f}s")
            self.spinner_label.setText("Scan complete")

        finally:
            for col, mode in enumerate(original_modes):
                header.setSectionResizeMode(col, mode)

            self.table.blockSignals(False)
            self.table.setUpdatesEnabled(True)
            self.table.setSortingEnabled(True)

        # Sort and show table
        self.table.sortItems(4, Qt.SortOrder.DescendingOrder)
        self.table.setVisible(True)

        # Update buttons
        self.cancel_btn.setVisible(False)
        self.close_btn.setVisible(True)

    def _on_cancel(self) -> None:
        """Handle cancel button click."""
        self.cancelled.emit()
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setText("Cancelling...")

    def get_checked_timestamp(self) -> int:
        """Get current timestamp for storing in database."""
        return int(datetime.now().timestamp())

    def format_check_datetime(self, timestamp: int) -> str:
        """Format timestamp for display."""
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")

    def closeEvent(self, event) -> None:
        """Handle dialog close - ensure timers are stopped."""
        self._elapsed_timer.stop()
        self.images_bar.stop_animation()
        self.galleries_bar.stop_animation()
        super().closeEvent(event)

    def reject(self) -> None:
        """Handle dialog rejection (ESC key) - ensure timers are stopped."""
        self._elapsed_timer.stop()
        self.images_bar.stop_animation()
        self.galleries_bar.stop_animation()
        super().reject()
