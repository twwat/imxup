"""Progress tracking and bandwidth monitoring for IMXuploader GUI.

This module handles all progress-related operations extracted from main_window.py
to improve maintainability and separation of concerns.
"""

import time
from datetime import datetime
from typing import TYPE_CHECKING

from PyQt6.QtCore import QObject, QTimer, QSettings, Qt, QMutexLocker
from PyQt6.QtWidgets import QTableWidgetItem
from PyQt6.QtGui import QColor

from src.utils.logger import log
from src.gui.widgets.gallery_table import GalleryTableWidget
from src.gui.widgets.custom_widgets import TableProgressWidget, ActionButtonWidget

if TYPE_CHECKING:
    from src.gui.main_window import ImxUploadGUI


def format_timestamp_for_display(timestamp_value, include_seconds=False):
    """Format Unix timestamp for table display."""
    if not timestamp_value:
        return "", ""
    try:
        dt = datetime.fromtimestamp(timestamp_value)
        display_text = dt.strftime("%Y-%m-%d %H:%M")
        tooltip_text = dt.strftime("%Y-%m-%d %H:%M:%S")
        return display_text, tooltip_text
    except (ValueError, OSError, OverflowError):
        return "", ""


class ProgressTracker(QObject):
    """Handles progress tracking and bandwidth monitoring for the main window."""

    def __init__(self, main_window: 'ImxUploadGUI'):
        """Initialize the ProgressTracker."""
        super().__init__()
        self._main_window = main_window
        self._current_transfer_kbps = 0.0
        self._bandwidth_samples = []

        # Cache QSettings instances to avoid disk/registry I/O on every call
        self._stats_settings = QSettings("ImxUploader", "Stats")
        self._gui_settings = QSettings("ImxUploader", "ImxUploadGUI")

        # Cache stats values with periodic refresh
        self._cached_stats: dict = {}
        self._stats_cache_time: float = 0.0

    def _get_cached_stats(self) -> dict:
        """Get cached statistics with periodic refresh (every 5 seconds).

        Returns:
            dict: Cached statistics including total_galleries, total_images,
                  total_size_bytes, fastest_kbps, and fastest_kbps_timestamp.
        """
        now = time.time()
        if now - self._stats_cache_time > 5.0:  # Refresh every 5s
            settings = self._stats_settings
            self._cached_stats = {
                'total_galleries': settings.value("total_galleries", 0, type=int),
                'total_images': settings.value("total_images", 0, type=int),
                'total_size_bytes_v2': settings.value("total_size_bytes_v2", "0"),
                'total_size_bytes': settings.value("total_size_bytes", 0, type=int),
                'fastest_kbps': settings.value("fastest_kbps", 0.0, type=float),
                'fastest_kbps_timestamp': settings.value("fastest_kbps_timestamp", ""),
            }
            self._stats_cache_time = now
        return self._cached_stats

    def _update_counts_and_progress(self):
        """Update both button counts and progress display together."""
        self._update_button_counts()
        self.update_progress_display()

    def _update_button_counts(self):
        """Update button counts and states based on currently visible items."""
        try:
            visible_items = []
            all_items = self._main_window.queue_manager.get_all_items()

            path_to_row = {}
            for row in range(self._main_window.gallery_table.rowCount()):
                name_item = self._main_window.gallery_table.item(row, GalleryTableWidget.COL_NAME)
                if name_item:
                    path = name_item.data(Qt.ItemDataRole.UserRole)
                    if path:
                        path_to_row[path] = row

            for item in all_items:
                row = path_to_row.get(item.path)
                if row is not None and not self._main_window.gallery_table.isRowHidden(row):
                    visible_items.append(item)

            count_startable = sum(1 for item in visible_items if item.status in ("ready", "paused", "incomplete", "scanning"))
            count_pausable = sum(1 for item in visible_items if item.status in ("uploading", "queued"))
            count_completed = sum(1 for item in visible_items if item.status == "completed")

            self._main_window.start_all_btn.setText(" Start All " + (f"({count_startable})" if count_startable else ""))
            self._main_window.pause_all_btn.setText(" Pause All " + (f"({count_pausable})" if count_pausable else ""))
            self._main_window.clear_completed_btn.setText(" Clear Completed " + (f"({count_completed})" if count_completed else ""))

            self._main_window.start_all_btn.setEnabled(count_startable > 0)
            self._main_window.pause_all_btn.setEnabled(count_pausable > 0)
            self._main_window.clear_completed_btn.setEnabled(count_completed > 0)
        except Exception:
            pass

    def update_progress_display(self):
        """Update current tab progress and statistics."""
        items = self._main_window._get_current_tab_items()

        if not items:
            self._main_window.overall_progress.setValue(0)
            self._main_window.overall_progress.setText("Ready")
            self._main_window.overall_progress.setProgressProperty("status", "ready")
            current_tab_name = getattr(self._main_window.gallery_table, 'current_tab', 'All Tabs')
            self._main_window.stats_label.setText(f"No galleries in {current_tab_name}")
            return

        total_images = sum(item.total_images for item in items if item.total_images > 0)
        uploaded_images = 0
        for item in items:
            if item.total_images > 0:
                base_uploaded = item.uploaded_images
                if hasattr(item, 'uploaded_files') and item.uploaded_files:
                    base_uploaded = max(base_uploaded, len(item.uploaded_files))
                uploaded_images += base_uploaded

        if total_images > 0:
            overall_percent = int((uploaded_images / total_images) * 100)
            self._main_window.overall_progress.setValue(overall_percent)
            self._main_window.overall_progress.setText(f"{overall_percent}% ({uploaded_images}/{total_images})")
            if overall_percent >= 100:
                self._main_window.overall_progress.setProgressProperty("status", "completed")
            else:
                self._main_window.overall_progress.setProgressProperty("status", "uploading")
        else:
            self._main_window.overall_progress.setValue(0)
            self._main_window.overall_progress.setText("Preparing...")
            self._main_window.overall_progress.setProgressProperty("status", "uploading")

        current_tab_name = getattr(self._main_window.gallery_table, 'current_tab', 'All Tabs')
        status_counts = {
            'uploading': sum(1 for item in items if item.status == 'uploading'),
            'queued': sum(1 for item in items if item.status == 'queued'),
            'completed': sum(1 for item in items if item.status == 'completed'),
            'ready': sum(1 for item in items if item.status in ('ready', 'paused', 'incomplete', 'scanning')),
            'failed': sum(1 for item in items if item.status == 'failed')
        }

        status_parts = []
        if status_counts['uploading'] > 0:
            status_parts.append(f"Uploading: {status_counts['uploading']}")
        if status_counts['queued'] > 0:
            status_parts.append(f"Queued: {status_counts['queued']}")
        if status_counts['completed'] > 0:
            status_parts.append(f"Completed: {status_counts['completed']}")
        if status_counts['ready'] > 0:
            status_parts.append(f"Ready: {status_counts['ready']}")
        if status_counts['failed'] > 0:
            status_parts.append(f"Error: {status_counts['failed']}")

        if status_parts:
            self._main_window.stats_label.setText(" | ".join(status_parts))
        else:
            self._main_window.stats_label.setText(f"No galleries in {current_tab_name}")

        QTimer.singleShot(100, self._update_unnamed_count_background)

        # Use cached stats to avoid disk/registry I/O on every progress update
        cached = self._get_cached_stats()
        total_galleries = cached['total_galleries']
        total_images_acc = cached['total_images']
        total_size_bytes_v2 = cached['total_size_bytes_v2']
        try:
            total_size_acc = int(str(total_size_bytes_v2))
        except Exception:
            total_size_acc = cached['total_size_bytes']
        fastest_kbps = cached['fastest_kbps']

        self._main_window.stats_total_galleries_value_label.setText(f"{total_galleries}")
        self._main_window.stats_total_images_value_label.setText(f"{total_images_acc}")
        total_size_str = self._main_window._format_size_consistent(total_size_acc)

        try:
            self._main_window.speed_transferred_value_label.setText(f"{total_size_str}")
            fastest_mib = fastest_kbps / 1024.0
            fastest_str = f"{fastest_mib:.3f} MiB/s"
            self._main_window.speed_fastest_value_label.setText(fastest_str)
            fastest_timestamp = cached['fastest_kbps_timestamp']
            if fastest_kbps > 0 and fastest_timestamp:
                self._main_window.speed_fastest_value_label.setToolTip(f"Record set: {fastest_timestamp}")
            else:
                self._main_window.speed_fastest_value_label.setToolTip("")
        except Exception as e:
            log(f"ERROR: Exception in progress_tracker: {e}", level="error", category="ui")

        all_items = self._main_window.queue_manager.get_all_items()
        uploading_count = sum(1 for item in all_items if item.status == "uploading")

        if uploading_count == 0:
            self._bandwidth_samples.clear()
            self._current_transfer_kbps = 0.0
            self._main_window.speed_current_value_label.setText("0.000 MiB/s")
            self._main_window.speed_current_value_label.setStyleSheet("opacity: 0.4;")

    def on_bandwidth_updated(self, instant_kbps: float):
        """Update Speed box with rolling average + compression-style smoothing."""
        try:
            self._bandwidth_samples.append(instant_kbps)
            if len(self._bandwidth_samples) > 20:
                self._bandwidth_samples.pop(0)

            if self._bandwidth_samples:
                averaged_kbps = sum(self._bandwidth_samples) / len(self._bandwidth_samples)
            else:
                averaged_kbps = instant_kbps

            if averaged_kbps > self._current_transfer_kbps:
                alpha = 0.3
            else:
                alpha = 0.05

            self._current_transfer_kbps = alpha * averaged_kbps + (1 - alpha) * self._current_transfer_kbps

            mib_per_sec = self._current_transfer_kbps / 1024.0
            speed_str = f"{mib_per_sec:.3f} MiB/s"

            if mib_per_sec < 0.001:
                self._main_window.speed_current_value_label.setStyleSheet("opacity: 0.4;")
            else:
                self._main_window.speed_current_value_label.setStyleSheet("opacity: 1.0;")

            self._main_window.speed_current_value_label.setText(speed_str)

            # Use cached QSettings instance to avoid disk/registry I/O on every bandwidth update
            # Note: We read from _gui_settings but writes go to _stats_settings for consistency
            # with how update_progress_display reads from Stats
            cached = self._get_cached_stats()
            fastest_kbps = cached['fastest_kbps']
            if self._current_transfer_kbps > fastest_kbps and self._current_transfer_kbps < 10000:
                # Write new record to Stats settings (same location where update_progress_display reads)
                self._stats_settings.setValue("fastest_kbps", self._current_transfer_kbps)
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self._stats_settings.setValue("fastest_kbps_timestamp", timestamp)
                # Invalidate cache so next read picks up the new value
                self._stats_cache_time = 0.0
                fastest_mib = self._current_transfer_kbps / 1024.0
                fastest_str = f"{fastest_mib:.3f} MiB/s"
                self._main_window.speed_fastest_value_label.setText(fastest_str)
                self._main_window.speed_fastest_value_label.setToolTip(f"Record set: {timestamp}")
        except Exception:
            pass

    def _update_unnamed_count_background(self):
        """Update unnamed gallery count in background."""
        try:
            from imxup import get_unnamed_galleries
            unnamed_galleries = get_unnamed_galleries()
            unnamed_count = len(unnamed_galleries)
            QTimer.singleShot(0, lambda: self._main_window.stats_unnamed_value_label.setText(f"{unnamed_count}"))
        except Exception:
            QTimer.singleShot(0, lambda: self._main_window.stats_unnamed_value_label.setText("0"))
