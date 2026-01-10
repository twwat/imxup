"""Table row management for IMXuploader GUI.

This module handles table row population, loading, and status icon operations
extracted from main_window.py to improve maintainability and separation of concerns.

Handles:
    - Table row population (full, minimal, detailed)
    - Gallery loading phases (1, 2, finalize)
    - Viewport-based lazy widget loading
    - Background tab update processing
    - Status icon management and animation
    - Size and transfer column updates
"""

import os
import re
import time
from datetime import datetime
from typing import TYPE_CHECKING, Dict, Any, Optional, Set, Tuple

from PyQt6.QtCore import QObject, QTimer, Qt
from PyQt6.QtGui import QColor, QIcon
from PyQt6.QtWidgets import QTableWidgetItem, QApplication

from src.utils.logger import log
from src.utils.format_utils import format_binary_size, format_binary_rate
from src.storage.queue_manager import GalleryQueueItem
from src.gui.widgets.custom_widgets import TableProgressWidget, ActionButtonWidget
from src.gui.icon_manager import get_icon_manager
from src.processing.tasks import BackgroundTask
from imxup import check_gallery_renamed

if TYPE_CHECKING:
    from src.gui.main_window import ImxUploadGUI
    from src.gui.widgets.gallery_table import GalleryTableWidget


# Column index constants (mirrors GalleryTableWidget.COL_*)
# Avoids circular import by defining locally
class _Col:
    """Column indices mirroring GalleryTableWidget.COL_* constants."""
    ORDER = 0
    NAME = 1
    UPLOADED = 2
    PROGRESS = 3
    STATUS = 4
    STATUS_TEXT = 5
    ADDED = 6
    FINISHED = 7
    ACTION = 8
    SIZE = 9
    TRANSFER = 10
    RENAMED = 11
    TEMPLATE = 12
    GALLERY_ID = 13
    CUSTOM1 = 14
    CUSTOM2 = 15
    CUSTOM3 = 16
    CUSTOM4 = 17
    EXT1 = 18
    EXT2 = 19
    EXT3 = 20
    EXT4 = 21
    HOSTS_STATUS = 22
    HOSTS_ACTION = 23
    ONLINE_IMX = 24


def format_timestamp_for_display(timestamp_value, include_seconds=False):
    """Format Unix timestamp for table display with optional tooltip.

    Args:
        timestamp_value: Unix timestamp (float/int) or None
        include_seconds: Currently unused, kept for API compatibility

    Returns:
        tuple: (display_text, tooltip_text) where both are formatted datetime strings,
               or ("", "") if timestamp is invalid/None

    Note:
        Display format: "YYYY-MM-DD HH:MM"
        Tooltip format: "YYYY-MM-DD HH:MM:SS"
    """
    if not timestamp_value:
        return "", ""

    try:
        dt = datetime.fromtimestamp(timestamp_value)
        display_text = dt.strftime("%Y-%m-%d %H:%M")
        tooltip_text = dt.strftime("%Y-%m-%d %H:%M:%S")
        return display_text, tooltip_text
    except (ValueError, OSError, OverflowError):
        return "", ""


def get_icon(icon_key: str, theme_mode: str | None = None) -> QIcon:
    """Get an icon from IconManager.

    Args:
        icon_key: Icon identifier (supports legacy names like 'start', 'completed')
        theme_mode: Optional theme mode ('light'/'dark'), None = auto-detect

    Returns:
        QIcon instance
    """
    icon_mgr = get_icon_manager()
    if icon_mgr:
        return icon_mgr.get_icon(icon_key, theme_mode=theme_mode)
    return QIcon()


class NumericTableWidgetItem(QTableWidgetItem):
    """QTableWidgetItem subclass that sorts numerically instead of lexicographically.

    Used for columns containing numeric data like order numbers, sizes, etc.
    """

    def __lt__(self, other):
        """Compare items numerically for sorting."""
        try:
            return float(self.text() or 0) < float(other.text() or 0)
        except (ValueError, TypeError):
            return super().__lt__(other)


class TableRowManager(QObject):
    """Handles table row population and management for the main window.

    This manager handles all row-related operations including:
    - Initial table population during startup
    - Incremental row updates during uploads
    - Status icon rendering and animation
    - Viewport-based lazy widget loading
    - Background tab update processing

    Attributes:
        _main_window: Reference to the main ImxUploadGUI window
    """

    def __init__(self, main_window: 'ImxUploadGUI'):
        """Initialize the TableRowManager.

        Args:
            main_window: Reference to the main ImxUploadGUI window
        """
        super().__init__()
        self._main_window = main_window

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _update_imx_status_cell(self, row: int, item: GalleryQueueItem) -> bool:
        """Update IMX status column from item data.

        Parses the imx_status string (e.g., "Online (87/87)") and updates
        the table cell with online/total counts and check timestamp.

        Args:
            row: Table row index to update
            item: Gallery queue item containing imx_status data

        Returns:
            True if status was updated, False if no status data or parse failed
        """
        if not item.imx_status or not item.imx_status_checked:
            return False

        match = re.match(r'\w+\s*\((\d+)/(\d+)\)', item.imx_status)
        if not match:
            return False

        online = int(match.group(1))
        total = int(match.group(2))
        check_datetime = datetime.fromtimestamp(item.imx_status_checked).strftime('%Y-%m-%d %H:%M')
        self._main_window.gallery_table.set_online_imx_status(row, online, total, check_datetime)
        return True

    # =========================================================================
    # Table Row Population Methods
    # =========================================================================

    def _populate_table_row(self, row: int, item: GalleryQueueItem, total: int = 0):
        """Update row data immediately with proper font consistency - COMPLETE VERSION.

        Args:
            row: Table row index
            item: Gallery queue item to display
            total: Total number of items (for progress updates)
        """
        mw = self._main_window

        # Update splash screen during startup (only every 10 rows to avoid constant repaints)
        if hasattr(mw, 'splash') and mw.splash and row % 10 == 0:
            try:
                if total > 0:
                    percentage = int((row / total) * 100)
                    mw.splash.update_status(f"Loading gallery {row}/{total} ({percentage}%)")
                else:
                    mw.splash.update_status(f"Loading gallery {row}")
            except Exception as e:
                log(f"ERROR: Exception in table row manager: {e}", level="error", category="ui")
                raise

        # CRITICAL: Verify row is still valid for this item (table may have changed due to deletions)
        # Always use the current mapping as the source of truth (thread-safe access)
        actual_row = mw._get_row_for_path(item.path)

        if actual_row is None:
            # Item was removed from table entirely
            log(f"Skipping update - {os.path.basename(item.path)} no longer in table", level="debug", category="queue")
            return

        if actual_row != row:
            # Table was modified (row deletions/insertions), use current row
            log(f"Row adjusted for {os.path.basename(item.path)}: {row} -> {actual_row}", level="trace", category="queue")
            row = actual_row

        theme_mode = mw._current_theme_mode

        # Order number - show database ID (persistent, matches logs like "gallery 1555")
        order_item = NumericTableWidgetItem(str(item.db_id) if item.db_id else "0")
        order_item.setFlags(order_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        order_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        mw.gallery_table.setItem(row, _Col.ORDER, order_item)

        # Gallery name and path
        display_name = item.name or os.path.basename(item.path) or "Unknown"
        name_item = QTableWidgetItem(display_name)
        name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        name_item.setData(Qt.ItemDataRole.UserRole, item.path)
        mw.gallery_table.setItem(row, _Col.NAME, name_item)

        # Upload progress - always create cell, blank until images are counted
        total_images = getattr(item, 'total_images', 0) or 0
        uploaded_images = getattr(item, 'uploaded_images', 0) or 0
        uploaded_text = ""
        if total_images > 0:
            uploaded_text = f"{uploaded_images}/{total_images}"
        uploaded_item = QTableWidgetItem(uploaded_text)
        uploaded_item.setFlags(uploaded_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        uploaded_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        mw.gallery_table.setItem(row, _Col.UPLOADED, uploaded_item)

        # Progress bar - defer creation during initial load for speed
        if not hasattr(mw, '_initializing') or not mw._initializing:
            progress_widget = mw.gallery_table.cellWidget(row, 3)
            if not isinstance(progress_widget, TableProgressWidget):
                progress_widget = TableProgressWidget()
                mw.gallery_table.setCellWidget(row, 3, progress_widget)
            progress_widget.update_progress(item.progress, item.status)

        # Status icon and text
        self._set_status_cell_icon(row, item.status)
        # Skip STATUS_TEXT column (5) if hidden - optimization to avoid creating unused QTableWidgetItems
        if not mw.gallery_table.isColumnHidden(_Col.STATUS_TEXT):
            self._set_status_text_cell(row, item.status)

        # Added time
        added_text, added_tooltip = format_timestamp_for_display(item.added_time)
        added_item = QTableWidgetItem(added_text)
        added_item.setFlags(added_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        added_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if added_tooltip:
            added_item.setToolTip(added_tooltip)
        mw.gallery_table.setItem(row, _Col.ADDED, added_item)

        # Finished time
        finished_text, finished_tooltip = format_timestamp_for_display(item.finished_time)
        finished_item = QTableWidgetItem(finished_text)
        finished_item.setFlags(finished_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        finished_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if finished_tooltip:
            finished_item.setToolTip(finished_tooltip)
        mw.gallery_table.setItem(row, _Col.FINISHED, finished_item)

        # Size column with consistent binary formatting
        size_bytes = getattr(item, 'total_size', 0) or 0
        size_text = ""
        if size_bytes > 0:
            size_text = mw._format_size_consistent(size_bytes)
        size_item = QTableWidgetItem(size_text)
        size_item.setFlags(size_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        size_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        mw.gallery_table.setItem(row, _Col.SIZE, size_item)

        # Transfer speed column - Skip TRANSFER column (10) if hidden
        if not mw.gallery_table.isColumnHidden(_Col.TRANSFER):
            transfer_text = ""
            current_rate_kib = float(getattr(item, 'current_kibps', 0.0) or 0.0)
            final_rate_kib = float(getattr(item, 'final_kibps', 0.0) or 0.0)
            try:
                if item.status == "uploading" and current_rate_kib > 0:
                    transfer_text = format_binary_rate(current_rate_kib, precision=2)
                elif final_rate_kib > 0:
                    transfer_text = format_binary_rate(final_rate_kib, precision=2)
            except Exception:
                rate = current_rate_kib if item.status == "uploading" else final_rate_kib
                transfer_text = mw._format_rate_consistent(rate) if rate > 0 else ""

            xfer_item = QTableWidgetItem(transfer_text)
            xfer_item.setFlags(xfer_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            xfer_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if item.status == "uploading" and transfer_text:
                xfer_item.setForeground(QColor(173, 216, 255, 255) if theme_mode == 'dark' else QColor(20, 90, 150, 255))
            elif item.status in ("completed", "failed") and transfer_text:
                xfer_item.setForeground(QColor(255, 255, 255, 230) if theme_mode == 'dark' else QColor(0, 0, 0, 190))
            mw.gallery_table.setItem(row, _Col.TRANSFER, xfer_item)

        # Template name (always left-aligned for consistency)
        template_text = item.template_name or ""
        tmpl_item = QTableWidgetItem(template_text)
        tmpl_item.setFlags(tmpl_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        tmpl_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        mw.gallery_table.setItem(row, _Col.TEMPLATE, tmpl_item)

        # Renamed status: Set icon based on whether gallery has been renamed
        is_renamed = check_gallery_renamed(item.gallery_id) if item.gallery_id else None
        self._set_renamed_cell_icon(row, is_renamed)

        # Custom columns and Gallery ID: Load from database
        actual_table = getattr(mw.gallery_table, 'table', mw.gallery_table)

        # Temporarily block signals to prevent itemChanged during initialization
        signals_blocked = actual_table.signalsBlocked()
        actual_table.blockSignals(True)
        try:
            # Gallery ID column (13) - read-only, skip if hidden
            if not mw.gallery_table.isColumnHidden(_Col.GALLERY_ID):
                gallery_id_text = item.gallery_id or ""
                gallery_id_item = QTableWidgetItem(gallery_id_text)
                gallery_id_item.setFlags(gallery_id_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                gallery_id_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                actual_table.setItem(row, _Col.GALLERY_ID, gallery_id_item)

            # Custom columns (14-17) - editable, skip hidden ones
            for col_idx, field_name in [
                (_Col.CUSTOM1, 'custom1'),
                (_Col.CUSTOM2, 'custom2'),
                (_Col.CUSTOM3, 'custom3'),
                (_Col.CUSTOM4, 'custom4')
            ]:
                if not mw.gallery_table.isColumnHidden(col_idx):
                    value = getattr(item, field_name, '') or ''
                    custom_item = QTableWidgetItem(str(value))
                    custom_item.setFlags(custom_item.flags() | Qt.ItemFlag.ItemIsEditable)
                    custom_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                    actual_table.setItem(row, col_idx, custom_item)

            # Ext columns (18-21) - editable (populated by external apps or user), skip hidden ones
            for col_idx, field_name in [
                (_Col.EXT1, 'ext1'),
                (_Col.EXT2, 'ext2'),
                (_Col.EXT3, 'ext3'),
                (_Col.EXT4, 'ext4')
            ]:
                if not mw.gallery_table.isColumnHidden(col_idx):
                    value = getattr(item, field_name, '') or ''
                    ext_item = QTableWidgetItem(str(value))
                    ext_item.setFlags(ext_item.flags() | Qt.ItemFlag.ItemIsEditable)
                    ext_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                    actual_table.setItem(row, col_idx, ext_item)

            # IMX Status column - restore from database
            self._update_imx_status_cell(row, item)
        finally:
            actual_table.blockSignals(signals_blocked)

        # Action buttons - CREATE MISSING ACTION BUTTONS FOR NEW ITEMS
        try:
            existing_widget = mw.gallery_table.cellWidget(row, _Col.ACTION)
            if not isinstance(existing_widget, ActionButtonWidget):
                action_widget = ActionButtonWidget(parent=mw)
                action_widget.start_btn.setEnabled(item.status != "scanning")
                action_widget.start_btn.clicked.connect(lambda checked, path=item.path: mw.start_single_item(path))
                action_widget.stop_btn.clicked.connect(lambda checked, path=item.path: mw.stop_single_item(path))
                action_widget.view_btn.clicked.connect(lambda checked, path=item.path: mw.handle_view_button(path))
                action_widget.cancel_btn.clicked.connect(lambda checked, path=item.path: mw.cancel_single_item(path))
                action_widget.update_buttons(item.status)
                mw.gallery_table.setCellWidget(row, _Col.ACTION, action_widget)
            else:
                existing_widget.update_buttons(item.status)
                existing_widget.start_btn.setEnabled(item.status != "scanning")
        except Exception as e:
            log(f"ERROR: Failed to create action buttons for row {row}: {e}", level="error", category="ui")

        # File host widgets - CREATE/UPDATE FILE HOST STATUS AND ACTION WIDGETS
        try:
            from src.gui.widgets.custom_widgets import FileHostsStatusWidget, FileHostsActionWidget

            # Get file host upload data from database
            host_uploads = {}
            try:
                if hasattr(mw, '_file_host_uploads_cache'):
                    uploads_list = mw._file_host_uploads_cache.get(item.path, [])
                else:
                    uploads_list = mw.queue_manager.store.get_file_host_uploads(item.path)
                host_uploads = {upload['host_name']: upload for upload in uploads_list}
            except Exception as e:
                log(f"Failed to load file host uploads for {item.path}: {e}", level="warning", category="file_hosts")

            # HOSTS_STATUS widget (icons)
            existing_status_widget = mw.gallery_table.cellWidget(row, _Col.HOSTS_STATUS)
            if not isinstance(existing_status_widget, FileHostsStatusWidget):
                status_widget = FileHostsStatusWidget(item.path, parent=mw)
                status_widget.update_hosts(host_uploads)
                status_widget.host_clicked.connect(mw._on_file_host_icon_clicked)
                mw.gallery_table.setCellWidget(row, _Col.HOSTS_STATUS, status_widget)
            else:
                existing_status_widget.update_hosts(host_uploads)

            # HOSTS_ACTION widget (manage button)
            existing_action_widget = mw.gallery_table.cellWidget(row, _Col.HOSTS_ACTION)
            if not isinstance(existing_action_widget, FileHostsActionWidget):
                hosts_action_widget = FileHostsActionWidget(item.path, parent=mw)
                hosts_action_widget.manage_clicked.connect(mw._on_file_hosts_manage_clicked)
                mw.gallery_table.setCellWidget(row, _Col.HOSTS_ACTION, hosts_action_widget)

        except Exception as e:
            log(f"Failed to create file host widgets for row {row}: {e}", level="error", category="file_hosts")

    def _populate_table_row_detailed(self, row: int, item: GalleryQueueItem):
        """Complete row formatting in background - TRULY NON-BLOCKING.

        Args:
            row: Table row index
            item: Gallery queue item to display
        """
        mw = self._main_window

        def format_row_data():
            """Prepare formatted data in background thread"""
            try:
                formatted_data = {}
                formatted_data['order'] = str(item.db_id) if item.db_id else "0"
                formatted_data['added_text'], formatted_data['added_tooltip'] = format_timestamp_for_display(item.added_time)
                formatted_data['finished_text'], formatted_data['finished_tooltip'] = format_timestamp_for_display(item.finished_time)
                return formatted_data
            except Exception:
                return None

        def apply_formatted_data(formatted_data):
            """Apply formatted data to table - runs on main thread"""
            if formatted_data is None or row >= mw.gallery_table.rowCount():
                return

            try:
                # Order number (column 0)
                order_item = NumericTableWidgetItem(formatted_data['order'])
                order_item.setFlags(order_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                order_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                mw.gallery_table.setItem(row, _Col.ORDER, order_item)

                # Added time (column 6)
                added_item = QTableWidgetItem(formatted_data['added_text'])
                added_item.setFlags(added_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                added_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if formatted_data['added_tooltip']:
                    added_item.setToolTip(formatted_data['added_tooltip'])
                mw.gallery_table.setItem(row, _Col.ADDED, added_item)

                # Finished time (column 7)
                finished_item = QTableWidgetItem(formatted_data['finished_text'])
                finished_item.setFlags(finished_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                finished_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if formatted_data['finished_tooltip']:
                    finished_item.setToolTip(formatted_data['finished_tooltip'])
                mw.gallery_table.setItem(row, _Col.FINISHED, finished_item)

                # Apply minimal styling to uploaded count
                uploaded_item = mw.gallery_table.item(row, _Col.UPLOADED)
                if uploaded_item:
                    uploaded_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            except Exception as e:
                log(f"Exception in table row manager: {e}", level="error", category="ui")
                raise

        # Execute formatting in background, then apply on main thread
        task = BackgroundTask(format_row_data)
        task.signals.finished.connect(apply_formatted_data)
        task.signals.error.connect(lambda err: None)  # Ignore errors
        mw._thread_pool.start(task, priority=-2)  # Lower priority than icon tasks

        # Size and transfer rate (expensive formatting) - only call if not already set
        size_item_existing = mw.gallery_table.item(row, _Col.SIZE)
        if (item.scan_complete and hasattr(item, 'total_size') and item.total_size > 0 and
            (not size_item_existing or not size_item_existing.text().strip())):
            theme_mode = mw._current_theme_mode
            self._update_size_and_transfer_columns(row, item, theme_mode)

    def _populate_table_row_minimal(self, row: int, item: GalleryQueueItem):
        """Populate row with MINIMAL data only (no expensive widgets).

        This is used during Phase 1 loading to show gallery names and basic info
        without creating expensive progress bars or action buttons.

        Args:
            row: Table row index
            item: Gallery queue item to display
        """
        mw = self._main_window
        try:
            # Order number (column 0) - use db_id for consistent ordering
            order_item = NumericTableWidgetItem(str(item.db_id) if item.db_id else "0")
            order_item.setFlags(order_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            order_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            mw.gallery_table.setItem(row, _Col.ORDER, order_item)

            # Name column (always visible)
            name_item = QTableWidgetItem(item.name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            mw.gallery_table.setItem(row, _Col.NAME, name_item)

            # Status text (lightweight)
            status_text_item = QTableWidgetItem(item.status)
            status_text_item.setFlags(status_text_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            mw.gallery_table.setItem(row, _Col.STATUS_TEXT, status_text_item)

            # Upload count - Always create item (even if empty) so it can be updated later
            if item.total_images > 0:
                uploaded_text = f"{item.uploaded_images}/{item.total_images}"
            else:
                uploaded_text = ""
            uploaded_item = QTableWidgetItem(uploaded_text)
            uploaded_item.setFlags(uploaded_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            uploaded_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            mw.gallery_table.setItem(row, _Col.UPLOADED, uploaded_item)

            # Store path in name cell's UserRole for later lookups
            name_item.setData(Qt.ItemDataRole.UserRole, item.path)

        except Exception as e:
            log(f"Error in _populate_table_row_minimal for row {row}: {e}", level="error", category="ui")

    def _update_size_and_transfer_columns(self, row: int, item: GalleryQueueItem, theme_mode: str):
        """Update size and transfer columns with proper formatting.

        Args:
            row: Table row index
            item: Gallery queue item
            theme_mode: Current theme mode ('dark' or 'light')
        """
        mw = self._main_window

        # Size (column 9)
        size_bytes = int(getattr(item, 'total_size', 0) or 0)
        if not mw._format_functions_cached:
            try:
                mw._format_binary_size = format_binary_size
                mw._format_binary_rate = format_binary_rate
                mw._format_functions_cached = True
            except Exception:
                mw._format_binary_size = lambda x, **kwargs: f"{x} B"
                mw._format_binary_rate = lambda x, **kwargs: mw._format_rate_consistent(x, 2)

        try:
            size_text = mw._format_binary_size(size_bytes, precision=2)
        except Exception:
            size_text = f"{size_bytes} B" if size_bytes else ""
        size_item = QTableWidgetItem(size_text)
        size_item.setFlags(size_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        size_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        mw.gallery_table.setItem(row, _Col.SIZE, size_item)

        # Transfer rate (column 10)
        if item.status == "uploading" and hasattr(item, 'current_kibps') and item.current_kibps:
            try:
                transfer_text = mw._format_binary_rate(float(item.current_kibps), precision=1)
            except Exception:
                transfer_text = f"{item.current_kibps:.1f} KiB/s" if item.current_kibps else ""
        elif hasattr(item, 'final_kibps') and item.final_kibps:
            try:
                transfer_text = mw._format_binary_rate(float(item.final_kibps), precision=1)
            except Exception:
                transfer_text = f"{item.final_kibps:.1f} KiB/s"
        else:
            transfer_text = ""

        xfer_item = QTableWidgetItem(transfer_text)
        xfer_item.setFlags(xfer_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        xfer_item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        try:
            if item.status == "uploading" and transfer_text:
                xfer_item.setForeground(QColor(173, 216, 255, 255) if theme_mode == 'dark' else QColor(20, 90, 150, 255))
            else:
                if transfer_text:
                    xfer_item.setForeground(QColor(0, 0, 0, 160))
        except Exception as e:
            log(f"Exception in table row manager: {e}", level="error", category="ui")
            raise
        mw.gallery_table.setItem(row, _Col.TRANSFER, xfer_item)

    def _create_row_widgets(self, row: int):
        """Create progress and action widgets for a single row.

        Args:
            row: The row number to create widgets for
        """
        mw = self._main_window
        try:
            path = mw.row_to_path.get(row)
            if not path:
                return

            item = mw.queue_manager.get_item(path)
            if not item:
                return

            # Get the actual table widget (handle tabbed interface)
            table = mw.gallery_table
            if hasattr(mw.gallery_table, 'table'):
                table = mw.gallery_table.table

            # Create progress widget if needed
            progress_widget = table.cellWidget(row, _Col.PROGRESS)
            if not isinstance(progress_widget, TableProgressWidget):
                progress_widget = TableProgressWidget()
                table.setCellWidget(row, _Col.PROGRESS, progress_widget)
                progress_widget.update_progress(item.progress, item.status)

            # Create action buttons if needed
            action_widget = table.cellWidget(row, _Col.ACTION)
            if not isinstance(action_widget, ActionButtonWidget):
                action_widget = ActionButtonWidget()
                table.setCellWidget(row, _Col.ACTION, action_widget)
                action_widget.update_buttons(item.status)

            # Populate IMX status column if data exists (was missing from phased loading)
            self._update_imx_status_cell(row, item)

        except Exception as e:
            log(f"Error creating widgets for row {row}: {e}", level="error", category="performance")

    # =========================================================================
    # Table Loading Methods
    # =========================================================================

    def _initialize_table_from_queue(self, progress_callback=None):
        """Initialize table from existing queue items - called once on startup.

        Args:
            progress_callback: Optional callable(current, total) for progress updates
        """
        mw = self._main_window
        log(f"_initialize_table_from_queue() called", level="debug", category="ui")

        # Clear any existing mappings
        mw.path_to_row.clear()
        mw.row_to_path.clear()

        # Get all items and build table
        items = mw.queue_manager.get_all_items()
        log(f"Loading {len(items)} galleries from queue", level="info", category="ui")
        mw.gallery_table.setRowCount(len(items))

        # PERFORMANCE OPTIMIZATION: Batch load all file host uploads in ONE query
        try:
            mw._file_host_uploads_cache = mw.queue_manager.store.get_all_file_host_uploads_batch()
            log(f"Batch loaded file host uploads for {len(mw._file_host_uploads_cache)} galleries",
                level="debug", category="performance")
        except Exception as e:
            log(f"Failed to batch load file host uploads: {e}", level="warning", category="performance")
            mw._file_host_uploads_cache = {}

        # Set flag to defer expensive widget creation during initial load
        mw._initializing = True

        # PERFORMANCE OPTIMIZATION: Disable table updates during bulk load
        mw.gallery_table.setUpdatesEnabled(False)
        mw.gallery_table.setSortingEnabled(False)

        try:
            total_items = len(items)
            for row, item in enumerate(items):
                # Update mappings (thread-safe)
                mw._set_path_row_mapping(item.path, row)

                # Populate the row (progress widgets deferred)
                self._populate_table_row(row, item, total_items)

                # Initialize scan state tracking
                mw._last_scan_states[item.path] = item.scan_complete

                # Update progress every 10 galleries (batching for performance)
                if progress_callback and (row + 1) % 10 == 0:
                    try:
                        progress_callback(row + 1, total_items)
                    except Exception as e:
                        log(f"Progress callback error at row {row+1}: {e}", level="error")

            # Report final progress at completion
            if progress_callback:
                progress_callback(len(items), len(items))

        except Exception as e:
            log(f"Error in _initialize_table_from_queue: {e}", level="error", category="performance")
            raise
        finally:
            # CRITICAL: ALWAYS re-enable updates, even on exceptions
            mw.gallery_table.setSortingEnabled(True)
            mw.gallery_table.setUpdatesEnabled(True)

        # Create progress widgets in background after initial load
        mw._initializing = False
        QTimer.singleShot(100, lambda: self._create_deferred_widgets(len(items)))

        # After building the table, apply the current tab filter
        if hasattr(mw.gallery_table, 'refresh_filter'):
            def _apply_initial_filter():
                mw.gallery_table.refresh_filter()
                if hasattr(mw.gallery_table, 'tab_changed') and hasattr(mw.gallery_table, 'current_tab'):
                    mw.gallery_table.tab_changed.emit(mw.gallery_table.current_tab)
            QTimer.singleShot(0, _apply_initial_filter)

    def _create_deferred_widgets(self, total_rows: int):
        """Create deferred widgets (progress bars) after initial load.

        Optimized for performance with viewport-first loading:
        - Phase 1: Create widgets for visible rows first (~25 rows, ~50ms)
        - Phase 2: Create remaining widgets in background
        - Timer paused during batch operation to prevent _update_scanned_rows interference
        - setUpdatesEnabled(False) prevents 1144 repaints -> ~11 repaints total
        - processEvents() every 100 rows instead of 20 for reduced overhead

        Args:
            total_rows: Total number of rows in the table
        """
        mw = self._main_window
        actual_rows = min(total_rows, mw.gallery_table.rowCount())

        if actual_rows == 0:
            log("No rows to create widgets for", level="debug", category="ui")
            return

        log(f"Creating deferred widgets for {actual_rows} items...", level="debug", category="ui")

        # Get visible rows first for prioritized creation
        first_visible, last_visible = self._get_visible_row_range()
        visible_rows = set(range(first_visible, min(last_visible + 1, actual_rows)))

        log(f"Visible row range: {first_visible}-{last_visible} ({len(visible_rows)} rows)",
            level="debug", category="ui")

        # PERFORMANCE: Pause update timer during batch operation
        # This prevents _update_scanned_rows from iterating all items during widget creation
        timer_was_active = False
        timer_interval = 500  # default fallback
        if hasattr(mw, 'update_timer'):
            timer_was_active = mw.update_timer.isActive()
            timer_interval = mw.update_timer.interval()
            if timer_was_active:
                mw.update_timer.stop()
                log("Paused update_timer during widget creation", level="debug", category="performance")

        # PERFORMANCE: Disable table updates to prevent 1144 repaints
        mw.gallery_table.setUpdatesEnabled(False)

        try:
            # PHASE 1: Create widgets for VISIBLE rows first (user sees these immediately)
            visible_created = 0
            for row in range(first_visible, min(last_visible + 1, actual_rows)):
                self._create_progress_widget_for_row(row)
                visible_created += 1

            # Re-enable updates and show visible widgets immediately
            mw.gallery_table.setUpdatesEnabled(True)
            QApplication.processEvents()
            log(f"Phase 1 complete: {visible_created} visible widgets (rows {first_visible}-{last_visible})",
                level="debug", category="ui")

            # Disable updates again for Phase 2
            mw.gallery_table.setUpdatesEnabled(False)

            # PHASE 2: Create remaining widgets in background
            remaining_created = 0
            for row in range(actual_rows):
                if row not in visible_rows:
                    self._create_progress_widget_for_row(row)
                    remaining_created += 1

                    # PERFORMANCE: Process events every 100 rows instead of 20
                    # This reduces overhead from event processing while keeping UI responsive
                    if remaining_created % 100 == 0:
                        mw.gallery_table.setUpdatesEnabled(True)
                        QApplication.processEvents()
                        mw.gallery_table.setUpdatesEnabled(False)
                        log(f"Phase 2 progress: {remaining_created} remaining widgets created...",
                            level="debug", category="ui")

        finally:
            # CRITICAL: Always restore table updates and timer
            # Use nested try/finally to ensure timer is always restored even if setUpdatesEnabled fails
            try:
                mw.gallery_table.setUpdatesEnabled(True)
            except Exception as e:
                log(f"Warning: Failed to re-enable table updates: {e}", level="warning", category="ui")
            finally:
                if timer_was_active:
                    mw.update_timer.start(timer_interval)
                    log("Restored update_timer after widget creation", level="debug", category="performance")

        log(f"Finished creating {actual_rows} deferred widgets "
            f"({visible_created} visible + {remaining_created} background)",
            level="debug", category="ui")

    def _create_progress_widget_for_row(self, row: int):
        """Create progress widget for a single row if not already present.

        This is a helper method to avoid code duplication in _create_deferred_widgets.

        Args:
            row: Table row index to create widget for
        """
        mw = self._main_window
        try:
            path = mw.row_to_path.get(row)
            if path:
                item = mw.queue_manager.get_item(path)
                if item:
                    progress_widget = mw.gallery_table.cellWidget(row, _Col.PROGRESS)
                    if not isinstance(progress_widget, TableProgressWidget):
                        progress_widget = TableProgressWidget()
                        mw.gallery_table.setCellWidget(row, _Col.PROGRESS, progress_widget)
                        progress_widget.update_progress(item.progress, item.status)
        except Exception as e:
            log(f"Failed to create progress widget for row {row}: {e}", level="warning", category="ui")

    def _update_scanned_rows(self):
        """Update only rows where scan completion status has changed."""
        mw = self._main_window
        items = mw.queue_manager.get_all_items()
        updated_any = False

        for item in items:
            last_state = mw._last_scan_states.get(item.path, False)
            current_state = item.scan_complete

            if last_state != current_state:
                mw._last_scan_states[item.path] = current_state
                updated_any = True

                row = mw._get_row_for_path(item.path)
                if row is not None and row < mw.gallery_table.rowCount():
                    # Update upload count - ONLY update existing items
                    if item.total_images > 0:
                        uploaded_text = f"{item.uploaded_images}/{item.total_images}"
                        existing_item = mw.gallery_table.item(row, _Col.UPLOADED)
                        if existing_item:
                            existing_item.setText(uploaded_text)

                    # Size - ONLY update existing items
                    if item.total_size > 0:
                        size_text = mw._format_size_consistent(item.total_size)
                        existing_item = mw.gallery_table.item(row, _Col.SIZE)
                        if existing_item:
                            existing_item.setText(size_text)

                    # Update status column
                    self._set_status_cell_icon(row, item.status)
                    self._set_status_text_cell(row, item.status)

                    # Update action column
                    action_widget = mw.gallery_table.cellWidget(row, _Col.ACTION)
                    if isinstance(action_widget, ActionButtonWidget):
                        log(f"Updating action buttons for {item.path}, status: {item.status}", level="debug")
                        action_widget.update_buttons(item.status)
                        if item.status == "ready":
                            action_widget.start_btn.setEnabled(True)

        # Update button counts if any scans completed
        if updated_any:
            QTimer.singleShot(0, mw.progress_tracker._update_button_counts)

    def _load_galleries_phase1(self):
        """Phase 1 - Load critical gallery data in single pass.

        This method loads gallery names and status for all items in one pass with
        setUpdatesEnabled(False) to prevent paint events, achieving 24-60x speedup.
        """
        mw = self._main_window
        if mw._loading_abort:
            log("Gallery loading aborted by user", level="info", category="performance")
            return

        mw._loading_phase = 1
        log("Phase 1: Loading critical gallery data...", level="info", category="performance")

        # Clear any existing mappings
        mw.path_to_row.clear()
        mw.row_to_path.clear()
        mw._rows_with_widgets.clear()

        # Get all items
        items = mw.queue_manager.get_all_items()
        total_items = len(items)
        log(f"Loading {total_items} galleries from queue", level="info", category="ui")

        if total_items == 0:
            mw._loading_phase = 3
            log("No galleries to load", level="info", category="performance")
            return

        # Batch load file host uploads
        try:
            mw._file_host_uploads_cache = mw.queue_manager.store.get_all_file_host_uploads_batch()
            log(f"Batch loaded file host uploads for {len(mw._file_host_uploads_cache)} galleries",
                level="debug", category="performance")
        except Exception as e:
            log(f"Failed to batch load file host uploads: {e}", level="warning", category="performance")
            mw._file_host_uploads_cache = {}

        # Disable table updates during bulk insert
        mw.gallery_table.setUpdatesEnabled(False)
        mw.gallery_table.setSortingEnabled(False)
        log("Table updates disabled for bulk insert", level="debug", category="performance")

        # Set row count once
        mw.gallery_table.setRowCount(total_items)
        mw._initializing = True

        try:
            log(f"Processing all {total_items} galleries in single pass...", level="info", category="performance")

            for row, item in enumerate(items):
                mw._set_path_row_mapping(item.path, row)
                self._populate_table_row_minimal(row, item)
                mw._last_scan_states[item.path] = item.scan_complete

        except Exception as e:
            log(f"Error in Phase 1 table population: {e}", level="error", category="performance")
            raise
        finally:
            mw.gallery_table.setSortingEnabled(True)
            mw.gallery_table.setUpdatesEnabled(True)
            log("Table updates re-enabled - Phase 1 complete", level="info", category="performance")

        mw._initializing = False
        QTimer.singleShot(50, self._load_galleries_phase2)

    def _load_galleries_phase2(self):
        """Phase 2 - Create widgets ONLY for visible rows (viewport-based lazy loading).

        This creates progress bars and action buttons ONLY for rows currently visible
        in the viewport, drastically reducing initial load time.
        """
        mw = self._main_window
        if mw._loading_abort:
            log("Phase 2 loading aborted", level="info", category="performance")
            return

        mw._loading_phase = 2
        log("Phase 2: Creating widgets for VISIBLE rows only (viewport-based)...", level="info", category="performance")

        first_visible, last_visible = self._get_visible_row_range()
        visible_rows = list(range(first_visible, last_visible + 1))

        log(f"Phase 2: Creating widgets for {len(visible_rows)} visible rows (rows {first_visible}-{last_visible})",
            level="info", category="performance")

        mw.gallery_table.setUpdatesEnabled(False)
        log("Table updates disabled for Phase 2 widget creation", level="debug", category="performance")

        total_visible = len(visible_rows)
        batch_size = 10
        current_batch = 0

        def _create_widgets_batch():
            """Create widgets for the next batch of VISIBLE rows"""
            if mw._loading_abort:
                log("Phase 2 widget creation aborted", level="info", category="performance")
                mw.gallery_table.setUpdatesEnabled(True)
                return

            nonlocal current_batch
            start_idx = current_batch * batch_size
            end_idx = min(start_idx + batch_size, total_visible)

            try:
                for i in range(start_idx, end_idx):
                    row = visible_rows[i]
                    self._create_row_widgets(row)
                    mw._rows_with_widgets.add(row)

                progress_pct = int((end_idx / total_visible) * 100) if total_visible > 0 else 100
                log(f"Phase 2 progress: {end_idx}/{total_visible} visible rows ({progress_pct}%)",
                    level="debug", category="performance")

                current_batch += 1

                if end_idx < total_visible:
                    QTimer.singleShot(20, _create_widgets_batch)
                else:
                    mw.gallery_table.setUpdatesEnabled(True)
                    log(f"Phase 2 complete - created widgets for {len(mw._rows_with_widgets)} rows",
                        level="info", category="performance")
                    QTimer.singleShot(10, self._finalize_gallery_load)

            except Exception as e:
                log(f"Error in Phase 2 widget creation batch: {e}", level="error", category="performance")
                mw.gallery_table.setUpdatesEnabled(True)
                raise

        _create_widgets_batch()

    def _get_visible_row_range(self) -> Tuple[int, int]:
        """Calculate the range of visible rows in the table viewport.

        Returns:
            Tuple of (first_visible_row, last_visible_row) with +/-5 row buffer
        """
        mw = self._main_window
        try:
            table = mw.gallery_table
            if hasattr(mw.gallery_table, 'table'):
                table = mw.gallery_table.table

            viewport = table.viewport()
            viewport_height = viewport.height()
            vertical_scrollbar = table.verticalScrollBar()
            scroll_value = vertical_scrollbar.value()

            row_height = table.rowHeight(0) if table.rowCount() > 0 else 30

            buffer = 5
            first_visible = max(0, (scroll_value // row_height) - buffer)
            visible_rows = (viewport_height // row_height) + 1
            last_visible = min(table.rowCount() - 1, first_visible + visible_rows + buffer)

            log(f"Viewport: rows {first_visible}-{last_visible} (total: {table.rowCount()})",
                level="debug", category="performance")

            return (first_visible, last_visible)
        except Exception as e:
            log(f"Error calculating visible row range: {e}", level="error", category="performance")
            return (0, mw.gallery_table.rowCount() - 1 if hasattr(mw, 'gallery_table') else 0)

    def _finalize_gallery_load(self):
        """Finalize gallery loading - apply filters and update UI."""
        mw = self._main_window
        if mw._loading_abort:
            return

        log("Finalizing gallery load...", level="info", category="performance")

        if hasattr(mw.gallery_table, 'refresh_filter'):
            mw.gallery_table.refresh_filter()
            if hasattr(mw.gallery_table, 'tab_changed') and hasattr(mw.gallery_table, 'current_tab'):
                mw.gallery_table.tab_changed.emit(mw.gallery_table.current_tab)

        # Ensure visible rows have widgets after filtering
        QTimer.singleShot(100, mw._on_table_scrolled)

        mw._loading_phase = 3
        log(f"Gallery loading COMPLETE - {len(mw._rows_with_widgets)} rows with widgets created",
            level="info", category="performance")

    # =========================================================================
    # Background Tab Update Methods
    # =========================================================================

    def _process_background_tab_updates(self):
        """Process queued updates for non-visible tabs in background."""
        mw = self._main_window
        if not mw._background_tab_updates:
            return

        start_time = time.time()
        TIME_BUDGET = 0.005  # 5ms budget for background processing

        updates_processed = 0
        paths_to_remove = []

        for path, (item, update_type, timestamp) in list(mw._background_tab_updates.items()):
            if time.time() - start_time > TIME_BUDGET:
                break

            # Skip very old updates (>5 seconds) to prevent memory buildup
            if time.time() - timestamp > 5.0:
                paths_to_remove.append(path)
                continue

            try:
                row = mw._get_row_for_path(path)
                if row is not None:
                    if update_type == 'progress' and hasattr(item, 'progress'):
                        pass  # Update progress tracking without UI
                    elif update_type == 'status' and hasattr(item, 'status'):
                        pass  # Update status tracking without UI

                paths_to_remove.append(path)
                updates_processed += 1

            except Exception:
                paths_to_remove.append(path)

        for path in paths_to_remove:
            mw._background_tab_updates.pop(path, None)

        if hasattr(mw.gallery_table, '_perf_metrics') and updates_processed > 0:
            mw.gallery_table._perf_metrics['background_updates_processed'] += updates_processed

        if mw._background_tab_updates and not mw._background_update_timer.isActive():
            mw._background_update_timer.start(100)

    def queue_background_tab_update(self, path: str, item, update_type: str = 'progress'):
        """Queue an update for galleries not currently visible in tabs.

        Args:
            path: Gallery path
            item: Gallery queue item
            update_type: Type of update ('progress' or 'status')

        Returns:
            True if update was queued, False otherwise
        """
        mw = self._main_window
        row = mw._get_row_for_path(path)
        if row is not None and hasattr(mw.gallery_table, 'isRowHidden'):
            if mw.gallery_table.isRowHidden(row):
                mw._background_tab_updates[path] = (item, update_type, time.time())

                if not mw._background_update_timer.isActive():
                    mw._background_update_timer.start(100)
                return True
        return False

    def clear_background_tab_updates(self):
        """Clear all background tab updates (e.g., when switching tabs)."""
        mw = self._main_window
        mw._background_tab_updates.clear()
        if mw._background_update_timer.isActive():
            mw._background_update_timer.stop()

    # =========================================================================
    # Status Icon Methods
    # =========================================================================

    def _set_status_cell_icon(self, row: int, status: str):
        """Render the Status column as an icon only, without background/text.

        Args:
            row: Table row index
            status: Status string to display
        """
        mw = self._main_window

        # Validate row bounds
        if row < 0 or row >= mw.gallery_table.rowCount():
            log(f"_set_status_cell_icon: Invalid row {row}, table has {mw.gallery_table.rowCount()} rows", level="debug")
            return

        try:
            # Check if this row is selected
            table_widget = getattr(mw.gallery_table, 'table', mw.gallery_table)
            selected_rows = {item.row() for item in table_widget.selectedItems()}
            is_selected = row in selected_rows

            icon_mgr = get_icon_manager()
            if not icon_mgr:
                log(f"ERROR: IconManager not initialized, cannot set icon for status: {status}", level="error")
                return

            # Use IconManager with explicit theme and selection awareness
            animation_frame = mw._upload_animation_frame if status == "uploading" else 0
            icon = icon_mgr.get_status_icon(status, theme_mode=mw._current_theme_mode, is_selected=is_selected, animation_frame=animation_frame)
            tooltip = icon_mgr.get_status_tooltip(status)

            self._apply_icon_to_cell(row, _Col.STATUS, icon, tooltip, status)

        except Exception as e:
            log(f"Warning: Failed to set status icon for {status}: {e}", level="warning")

    def _set_status_text_cell(self, row: int, status: str):
        """Set the status text column with capitalized status string.

        Args:
            row: The table row index
            status: The status string to display (will be capitalized)
        """
        mw = self._main_window

        # Validate row bounds
        if row < 0 or row >= mw.gallery_table.rowCount():
            log(f"_set_status_text_cell: Invalid row {row}, table has {mw.gallery_table.rowCount()} rows", level="debug")
            return

        try:
            status_text = status.capitalize() if status else ""
            status_item = QTableWidgetItem(status_text)
            status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            mw.gallery_table.setItem(row, _Col.STATUS_TEXT, status_item)

        except Exception as e:
            log(f"Warning: Failed to set status text for {status}: {e}", level="debug")

    def _set_renamed_cell_icon(self, row: int, is_renamed: bool | None):
        """Set the Renamed column cell to an icon (check/pending) if available.

        Args:
            row: Table row index
            is_renamed: True for renamed, False for pending, None for blank
        """
        mw = self._main_window
        try:
            col = 11

            item = QTableWidgetItem()
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            if is_renamed is True:
                icon = get_icon('renamed_true')
                tooltip = "Renamed"
                if icon is not None and not icon.isNull():
                    item.setIcon(icon)
                    item.setText("")
                else:
                    item.setText("OK")
                    log(f"Using fallback text for renamed_true", level="debug")
            elif is_renamed is False:
                icon = get_icon('renamed_false')
                tooltip = "Pending rename"
                if icon is not None and not icon.isNull():
                    item.setIcon(icon)
                    item.setText("")
                else:
                    item.setText("...")
                    log(f"Using fallback text for renamed_false", level="debug")
            else:
                item.setIcon(QIcon())
                item.setText("")
                tooltip = ""

            item.setToolTip(tooltip)
            mw.gallery_table.setItem(row, col, item)

        except Exception as e:
            try:
                item = QTableWidgetItem("")
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                mw.gallery_table.setItem(row, col, item)
            except Exception as e2:
                log(f"Exception in table row manager: {e2}", level="error", category="ui")
                raise

    def _apply_icon_to_cell(self, row: int, col: int, icon, tooltip: str, status: str):
        """Apply icon to table cell - runs on main thread.

        Args:
            row: Table row index
            col: Table column index
            icon: QIcon to apply
            tooltip: Tooltip text
            status: Status string (for fallback text)
        """
        mw = self._main_window
        try:
            if row < 0 or row >= mw.gallery_table.rowCount():
                return

            mw.gallery_table.removeCellWidget(row, col)

            item = QTableWidgetItem()
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setToolTip(tooltip)

            if icon is not None and not icon.isNull():
                item.setIcon(icon)
            else:
                item.setText(status.title() if isinstance(status, str) else "")

            mw.gallery_table.setItem(row, col, item)

        except Exception as e:
            log(f"Exception in table row manager: {e}", level="error", category="ui")
            raise

    def refresh_icons(self):
        """Alias for refresh_all_status_icons - called from settings dialog."""
        self.refresh_all_status_icons()

    def refresh_all_status_icons(self):
        """Refresh all status icons and action button icons after icon changes in settings."""
        mw = self._main_window
        try:
            icon_mgr = get_icon_manager()
            if icon_mgr:
                table = mw.gallery_table
                if hasattr(mw.gallery_table, 'table'):
                    table = mw.gallery_table.table

                # Only update VISIBLE rows for fast theme switching
                viewport = table.viewport()
                first_visible = table.rowAt(0)
                last_visible = table.rowAt(viewport.height())

                if first_visible == -1:
                    first_visible = 0
                if last_visible == -1:
                    last_visible = table.rowCount() - 1

                # Add buffer rows
                first_visible = max(0, first_visible - 5)
                last_visible = min(table.rowCount() - 1, last_visible + 5)

                # Update only visible status icons, action button icons, and Online IMX colors
                for row in range(first_visible, last_visible + 1):
                    name_item = table.item(row, _Col.NAME)
                    if name_item:
                        path = name_item.data(Qt.ItemDataRole.UserRole)
                        if path and path in mw.queue_manager.items:
                            item = mw.queue_manager.items[path]
                            self._set_status_cell_icon(row, item.status)
                            self._set_status_text_cell(row, item.status)
                            # Refresh Online IMX column colors (theme-aware)
                            self._update_imx_status_cell(row, item)

                    action_widget = table.cellWidget(row, _Col.ACTION)
                    if action_widget and hasattr(action_widget, 'refresh_icons'):
                        action_widget.refresh_icons()

                # Set flag so scrolling will refresh newly visible rows
                if hasattr(table, '_needs_full_icon_refresh'):
                    table._needs_full_icon_refresh = True

                # Refresh quick settings button icons
                if hasattr(mw, 'comprehensive_settings_btn'):
                    settings_icon = icon_mgr.get_icon('settings')
                    if not settings_icon.isNull():
                        mw.comprehensive_settings_btn.setIcon(settings_icon)

                if hasattr(mw, 'manage_templates_btn'):
                    templates_icon = icon_mgr.get_icon('templates')
                    if not templates_icon.isNull():
                        mw.manage_templates_btn.setIcon(templates_icon)

                if hasattr(mw, 'manage_credentials_btn'):
                    credentials_icon = icon_mgr.get_icon('credentials')
                    if not credentials_icon.isNull():
                        mw.manage_credentials_btn.setIcon(credentials_icon)

                if hasattr(mw, 'log_viewer_btn'):
                    log_viewer_icon = icon_mgr.get_icon('log_viewer')
                    if not log_viewer_icon.isNull():
                        mw.log_viewer_btn.setIcon(log_viewer_icon)

                if hasattr(mw, 'hooks_btn'):
                    hooks_icon = icon_mgr.get_icon('hooks')
                    if not hooks_icon.isNull():
                        mw.hooks_btn.setIcon(hooks_icon)

                # Refresh worker status widget icons
                if hasattr(mw, 'worker_status_widget') and hasattr(mw.worker_status_widget, 'refresh_icons'):
                    mw.worker_status_widget.refresh_icons()

        except Exception as e:
            log(f"Error refreshing icons: {e}", level="error", category="ui")

    def _advance_upload_animation(self):
        """Advance the upload animation frame and update uploading icons."""
        mw = self._main_window

        # Increment frame (0-6, cycling through 7 frames)
        mw._upload_animation_frame = (mw._upload_animation_frame + 1) % 7

        table = mw.gallery_table
        if hasattr(mw.gallery_table, 'table'):
            table = mw.gallery_table.table

        # Update only rows with "uploading" status
        try:
            for row in range(table.rowCount()):
                if table.isRowHidden(row):
                    continue

                name_item = table.item(row, _Col.NAME)
                if name_item:
                    path = name_item.data(Qt.ItemDataRole.UserRole)
                    if path and path in mw.queue_manager.items:
                        item = mw.queue_manager.items[path]
                        if item.status == "uploading":
                            self._set_status_cell_icon(row, item.status)
        except Exception:
            pass  # Silently ignore errors (table might be updating)
