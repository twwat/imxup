#!/usr/bin/env python3
"""
Gallery Table Widget
Displays gallery queue with sortable columns, progress tracking, and interactive controls
"""

import os
import json
from pathlib import Path
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.storage.queue_manager import QueueManager
    from src.gui.tab_manager import TabManager
    from src.gui.icon_manager import IconManager

from PyQt6.QtWidgets import (
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QStyledItemDelegate, QStyleOptionViewItem, QMessageBox, QFileDialog,
    QDialog, QApplication, QInputDialog
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QUrl, QMimeData, QTimer
from PyQt6.QtGui import (
    QDragEnterEvent, QDropEvent, QIcon, QFont, QColor,
    QPainter, QDrag, QPen, QPixmap, QFontMetrics, QDesktopServices
)

# Import existing utilities
from src.core.constants import IMAGE_EXTENSIONS
from src.utils.logger import log
from src.gui.widgets.custom_widgets import TableProgressWidget, ActionButtonWidget
from src.gui.icon_manager import get_icon_manager

# Import dialogs
from src.gui.dialogs.gallery_file_manager import GalleryFileManagerDialog
from src.gui.dialogs.message_factory import show_warning


class NumericColumnDelegate(QStyledItemDelegate):
    """Delegate for numeric/timestamp columns with smaller font (0.95em) and right alignment"""

    def paint(self, painter, option, index):
        # Create a copy of the option and scale font to 0.95 of current size
        new_option = QStyleOptionViewItem(option)
        font = new_option.font
        if font.pointSizeF() > 0:
            font.setPointSizeF(font.pointSizeF() * 0.95)
        elif font.pixelSize() > 0:
            font.setPixelSize(int(font.pixelSize() * 0.95))
        new_option.font = font

        # Right-align text
        new_option.displayAlignment = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter

        # Paint with modified options
        super().paint(painter, new_option, index)


class GalleryTableWidget(QTableWidget):
    """Table widget for gallery queue with resizable columns, sorting, and action buttons
    """

    # Type hints for attributes set externally by parent (ImxUploadGUI)
    queue_manager: 'QueueManager'  # Set by parent after instantiation
    tab_manager: Optional['TabManager']  # Set by parent after instantiation
    icon_manager: Optional['IconManager']  # Set by parent after instantiation

    # Column index type hints for mypy (values set dynamically below)
    COL_ORDER: int
    COL_NAME: int
    COL_UPLOADED: int
    COL_PROGRESS: int
    COL_STATUS: int
    COL_STATUS_TEXT: int
    COL_ADDED: int
    COL_FINISHED: int
    COL_ACTION: int
    COL_SIZE: int
    COL_TRANSFER: int
    COL_RENAMED: int
    COL_TEMPLATE: int
    COL_GALLERY_ID: int
    COL_CUSTOM1: int
    COL_CUSTOM2: int
    COL_CUSTOM3: int
    COL_CUSTOM4: int
    COL_EXT1: int
    COL_EXT2: int
    COL_EXT3: int
    COL_EXT4: int
    COL_HOSTS_STATUS: int
    COL_HOSTS_ACTION: int

    # Column definitions - single source of truth for all column metadata
    COLUMNS = [
        # (index, name, header_label, default_width, resize_mode, hidden_by_default, header_align_left)
        (0,  'ORDER',       '#',            40,  'Fixed',       False, False),
        (1,  'NAME',        'gallery name', 300, 'Interactive', False, True),
        (2,  'UPLOADED',    'uploaded',     100, 'Interactive', False, False),
        (3,  'PROGRESS',    'progress',     200, 'Interactive', False, False),
        (4,  'STATUS',      'status',       40,  'Interactive', False, False),
        (5,  'STATUS_TEXT', 'status text',  100, 'Interactive', True,  False),
        (6,  'ADDED',       'added',        120, 'Interactive', False, False),
        (7,  'FINISHED',    'finished',     120, 'Interactive', False, False),
        (8,  'ACTION',      'action',       50,  'Interactive', False, True),
        (9,  'SIZE',        'size',         110, 'Interactive', False, False),
        (10, 'TRANSFER',    'transfer',     120, 'Interactive', True,  False),
        (11, 'RENAMED',     'renamed',      40,  'Interactive', False, True),
        (12, 'TEMPLATE',    'template',     140, 'Interactive', False, True),
        (13, 'GALLERY_ID',  'gallery_id',   90,  'Interactive', True,  True),
        (14, 'CUSTOM1',     'Custom1',      100, 'Interactive', True,  True),
        (15, 'CUSTOM2',     'Custom2',      100, 'Interactive', True,  True),
        (16, 'CUSTOM3',     'Custom3',      100, 'Interactive', True,  True),
        (17, 'CUSTOM4',     'Custom4',      100, 'Interactive', True,  True),
        (18, 'EXT1',          'ext1',         100, 'Interactive', True,  True),
        (19, 'EXT2',          'ext2',         100, 'Interactive', True,  True),
        (20, 'EXT3',          'ext3',         100, 'Interactive', True,  True),
        (21, 'EXT4',          'ext4',         100, 'Interactive', True,  True),
        (22, 'HOSTS_STATUS',  'file hosts',   150, 'Interactive', False, True),
        (23, 'HOSTS_ACTION',  'hosts action', 80,  'Interactive', False, True),
    ]

    # Create class attributes dynamically from COLUMNS definition
    for idx, name, *_ in COLUMNS:
        locals()[f'COL_{name}'] = idx

    def __init__(self, parent=None):
        super().__init__(parent)

        # Drag and drop state
        self._drag_start_position = None
        self._is_dragging = False

        # Enable drag and drop for internal gallery moves and file drops
        self.setDragEnabled(True)
        self.setAcceptDrops(True)  # Accept drops for adding files to galleries
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)

        # Setup table from COLUMNS definition
        self.setColumnCount(len(self.COLUMNS))
        self.setHorizontalHeaderLabels([col[2] for col in self.COLUMNS])

        # Set icon size for Status column icons
        self.setIconSize(QSize(20, 20))
        try:
            # Left-align the 'gallery name' header specifically
            hn = self.horizontalHeaderItem(1)
            if hn:
                hn.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                # Gallery name column gets slightly larger font
                hn.setFont(QFont(hn.font().family(), 9))

            # Left-align headers as specified in COLUMNS definition
            for idx, name, label, width, resize_mode, hidden, align_left in self.COLUMNS:
                if align_left:
                    header_item = self.horizontalHeaderItem(idx)
                    if header_item:
                        header_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        except Exception as e:
            log(f"Exception in gallery_table: {e}", level="error", category="ui")
            raise

        # Configure columns from COLUMNS definition
        header = self.horizontalHeader()
        header.setStretchLastSection(False)
        try:
            # Disable cascading resizes for Excel-like behavior (independent column resizing)
            header.setCascadingSectionResizes(False)
        except Exception as e:
            log(f"Exception in gallery_table: {e}", level="error", category="ui")
            raise

        # Set resize modes from COLUMNS definition
        for idx, _, _, _, resize_mode, _, _ in self.COLUMNS:
            mode = getattr(QHeaderView.ResizeMode, resize_mode)
            header.setSectionResizeMode(idx, mode)
        try:
            # Allow headers to shrink more
            header.setMinimumSectionSize(24)
        except Exception as e:
            log(f"Exception in gallery_table: {e}", level="error", category="ui")
            raise
        # Keep widths fixed unless user drags; prevent automatic shuffling
        try:
            header.setSectionsClickable(True)
            header.setHighlightSections(False)
            header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        except Exception as e:
            log(f"Exception in gallery_table: {e}", level="error", category="ui")
            raise

        # Set column widths and visibility from COLUMNS definition
        for idx, _, _, width, _, hidden, _ in self.COLUMNS:
            self.setColumnWidth(idx, width)
            if hidden:
                self.setColumnHidden(idx, True)

        # Apply numeric column delegate for smaller font and right alignment
        numeric_delegate = NumericColumnDelegate(self)
        for col in [self.COL_UPLOADED, self.COL_ADDED, self.COL_FINISHED, self.COL_SIZE, self.COL_TRANSFER, self.COL_STATUS_TEXT, self.COL_GALLERY_ID, self.COL_CUSTOM1, self.COL_CUSTOM2, self.COL_CUSTOM3, self.COL_CUSTOM4, self.COL_EXT1, self.COL_EXT2, self.COL_EXT3, self.COL_EXT4]:
            self.setItemDelegateForColumn(col, numeric_delegate)

        # Make Status and Action columns non-resizable
        header = self.horizontalHeader()
        #header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)  # Status column
        #header.setSectionResizeMode(7, QHeaderView.ResizeMode.Fixed)  # Action column

        # Enable sorting but start with no sorting (insertion order)
        self.setSortingEnabled(True)
        self.horizontalHeader().setSortIndicatorShown(False)  # No initial sort indicator

        # Let styles.qss handle the styling for proper theme support
        self.setShowGrid(True)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(24)  # Slightly shorter rows

        # Column visibility is managed by window settings; defaults applied in restore_table_settings

        # Disable auto-expansion behavior; make columns behave like Excel (no auto-resize of others)
        try:
            header.setSectionsMovable(True)
            header.setStretchLastSection(False)
            self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        except Exception as e:
            log(f"Exception in gallery_table: {e}", level="error", category="ui")
            raise

        # Connect vertical scrollbar to refresh icons when scrolling
        self.verticalScrollBar().valueChanged.connect(self._on_scroll)

        # Track if we need full icon refresh (after theme change)
        self._needs_full_icon_refresh = False

    def _on_scroll(self):
        """Refresh icons for newly visible rows when scrolling (only if needed after theme change)"""
        if self._needs_full_icon_refresh:
            # Find parent ImxUploadGUI to call refresh
            from PyQt6.QtWidgets import QWidget, QMainWindow
            parent = self.parent()
            while parent and not isinstance(parent, QMainWindow):
                parent = parent.parent()
            if parent:
                # Refresh both status icons and renamed icons for newly visible rows
                if hasattr(parent, 'refresh_all_status_icons'):
                    parent.refresh_all_status_icons()
                if hasattr(parent, '_refresh_button_icons'):
                    parent._refresh_button_icons()
                # Note: flag stays True so scrolling continues to refresh new rows
                # It will be cleared when all rows are eventually visible or manually cleared

    def _edit_next_cell(self, row, column):
        """Helper to start editing a specific cell (used after Enter key)"""
        item = self.item(row, column)
        if item:
            self.setCurrentItem(item)
            self.editItem(item)

    def keyPressEvent(self, event):
        """Handle key press events with per-tab isolation"""
        # HOME/END KEYS: Only affect VISIBLE rows in the current tab
        if event.key() == Qt.Key.Key_Home:
            # Find first visible row
            for row in range(self.rowCount()):
                if not self.isRowHidden(row):
                    self.selectRow(row)
                    self.setCurrentCell(row, self.currentColumn())
                    return
        elif event.key() == Qt.Key.Key_End:
            # Find last visible row
            for row in range(self.rowCount() - 1, -1, -1):
                if not self.isRowHidden(row):
                    self.selectRow(row)
                    self.setCurrentCell(row, self.currentColumn())
                    return
        elif event.key() == Qt.Key.Key_Delete:
            # Find the main GUI window by walking up the parent chain
            widget = self
            while widget:
                if hasattr(widget, 'delete_selected_items'):
                    widget.delete_selected_items()
                    return
                widget = widget.parent()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            # Check if we're editing a custom or ext column
            current_index = self.currentIndex()
            if current_index.isValid():
                column = current_index.column()
                row = current_index.row()

                # Handle Enter key for editable columns (custom1-4, ext1-4)
                if (GalleryTableWidget.COL_CUSTOM1 <= column <= GalleryTableWidget.COL_CUSTOM4) or \
                   (GalleryTableWidget.COL_EXT1 <= column <= GalleryTableWidget.COL_EXT4):
                    # Let Qt's default behavior commit the data FIRST (closes editor if open)
                    super().keyPressEvent(event)

                    # Find the next VISIBLE row (skip hidden rows when table is filtered)
                    next_row = row + 1
                    while next_row < self.rowCount() and self.isRowHidden(next_row):
                        next_row += 1

                    # If we found a visible row, edit it
                    if next_row < self.rowCount():
                        # Verify the next row has a valid item at this column
                        next_item = self.item(next_row, column)
                        if next_item is not None:
                            QTimer.singleShot(0, lambda r=next_row, c=column: self._edit_next_cell(r, c))
                    # If no next visible row or no valid item, we're done (already called super, so it's saved)

                    return  # Event handled

            # For other columns, use default Enter behavior (commented out above)
            # self.handle_enter_or_double_click()
        elif event.modifiers() == Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_C:
            # Handle Ctrl+C for copying BBCode
            self.handle_copy_bbcode()
            return  # Don't call super() to prevent default table copy behavior

        super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event):
        """Handle double-click events"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.handle_enter_or_double_click()
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):
        """Keep focus behavior on left-click; do not interfere with context menu events"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
            # Store position for potential drag start
            self._drag_start_position = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """Handle mouse move events for drag and drop"""
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            super().mouseMoveEvent(event)
            return

        if self._drag_start_position is None:
            super().mouseMoveEvent(event)
            return

        # Check if we've moved far enough to start a drag
        if ((event.position().toPoint() - self._drag_start_position).manhattanLength() <
            QApplication.startDragDistance()):
            super().mouseMoveEvent(event)
            return

        # Start drag if we have selected items
        selected_items = self.selectedItems()
        if selected_items:
            self._start_gallery_drag()

        super().mouseMoveEvent(event)

    def _start_gallery_drag(self):
        """Start a drag operation with selected galleries"""
        # Get selected gallery paths
        selected_rows = sorted({item.row() for item in self.selectedItems()})
        gallery_paths = []
        gallery_names = []

        for row in selected_rows:
            name_item = self.item(row, GalleryTableWidget.COL_NAME)
            if name_item:
                path = name_item.data(Qt.ItemDataRole.UserRole)
                if path:
                    gallery_paths.append(path)
                    gallery_names.append(name_item.text())

        if not gallery_paths:
            return

        # Create mime data for internal gallery transfer
        mime_data = QMimeData()
        mime_data.setData("application/x-imxup-galleries",
                         "\n".join(gallery_paths).encode('utf-8'))

        # Add text representation for debugging
        if len(gallery_names) == 1:
            mime_data.setText(f"Gallery: {gallery_names[0]}")
        else:
            mime_data.setText(f"{len(gallery_names)} galleries")

        # Create drag object
        drag = QDrag(self)
        drag.setMimeData(mime_data)

        # Set up drag pixmap (visual feedback)
        pixmap = self._create_drag_pixmap(gallery_names)
        drag.setPixmap(pixmap)
        from PyQt6.QtCore import QPoint
        drag.setHotSpot(QPoint(pixmap.width() // 2, 10))

        # Execute drag
        self._is_dragging = True
        drop_action = drag.exec(Qt.DropAction.MoveAction)
        self._is_dragging = False

    def _create_drag_pixmap(self, gallery_names):
        """Create a pixmap for drag visual feedback"""
        # Create font for text measurement
        font = QFont()
        metrics = QFontMetrics(font)

        if len(gallery_names) == 1:
            text = gallery_names[0][:30]  # Truncate long names
            if len(gallery_names[0]) > 30:
                text += "..."
        else:
            text = f"{len(gallery_names)} galleries"

        text_width = metrics.horizontalAdvance(text)
        text_height = metrics.height()

        # Create pixmap with padding
        pixmap_width = text_width + 20
        pixmap_height = text_height + 10
        pixmap = QPixmap(pixmap_width, pixmap_height)
        pixmap.fill(QColor(100, 150, 200, 180))  # Semi-transparent blue

        # Draw text
        painter = QPainter(pixmap)
        painter.setPen(Qt.GlobalColor.white)
        painter.drawText(10, text_height + 2, text)
        painter.end()

        return pixmap

    def resizeEvent(self, event):
        """Excel-like behavior - columns don't auto-resize on window resize.
        User manually resizes columns, horizontal scrollbar appears if needed."""
        super().resizeEvent(event)
        # Removed auto-resize logic to maintain Excel-like independent column behavior
        # Columns now stay at their user-defined widths regardless of window size

    def handle_enter_or_double_click(self):
        """Handle Enter key or double-click for viewing items (BBCode for completed, file manager for others)"""
        current_row = self.currentRow()
        if current_row >= 0:
            name_item = self.item(current_row, GalleryTableWidget.COL_NAME)
            if name_item:
                path = name_item.data(Qt.ItemDataRole.UserRole)
                if path:
                    # Find the main GUI window and use the smart view handler
                    widget = self
                    while widget:
                        if hasattr(widget, 'handle_view_button'):
                            widget.handle_view_button(path)
                            return
                        widget = widget.parent()

    def handle_copy_bbcode(self):
        """Handle Ctrl+C for copying BBCode for all selected completed items"""
        # Collect selected completed item paths
        selected_rows = sorted({it.row() for it in self.selectedItems()})
        paths = []
        for row in selected_rows:
            name_item = self.item(row, GalleryTableWidget.COL_NAME)
            if name_item:
                path = name_item.data(Qt.ItemDataRole.UserRole)
                if path:
                    paths.append(path)
        if not paths:
            return
        # Filter for completed items only (like context menu does)
        widget = self
        while widget and not hasattr(widget, 'queue_manager'):
            widget = widget.parent()
        completed_paths = []
        if widget and hasattr(widget, 'queue_manager'):
            for path in paths:
                item = widget.queue_manager.get_item(path)
                if item and item.status == "completed":
                    completed_paths.append(path)
        # Delegate to the multi-copy helper to aggregate
        self.copy_bbcode_via_menu_multi(completed_paths)

    def show_context_menu(self, position):
        """Show context menu for table items"""
        # Position is already in viewport coordinates
        viewport_pos = position
        global_pos = self.viewport().mapToGlobal(position)

        # Select row under cursor if not already selected using model index for reliability
        index = self.indexAt(viewport_pos)
        if index.isValid():
            row = index.row()
            if row != self.currentRow():
                self.clearSelection()
                self.selectRow(row)

        # Build selected rows robustly via selection model (target column 1)
        selected_paths = []
        sel_model = self.selectionModel()
        if sel_model is not None:
            for idx in sel_model.selectedRows(1):
                row = idx.row()
                name_item = self.item(row, GalleryTableWidget.COL_NAME)
                if name_item:
                    path = name_item.data(Qt.ItemDataRole.UserRole)
                    if path:
                        selected_paths.append(path)

        # Use context menu helper to create the menu
        if hasattr(self, 'context_menu_helper'):
            # Find the main window reference
            from PyQt6.QtWidgets import QMainWindow
            widget = self
            while widget and not hasattr(widget, 'queue_manager'):
                widget = widget.parent()

            if widget:
                self.context_menu_helper.main_window = widget
                menu = self.context_menu_helper.create_context_menu(position, selected_paths)

                # Only show menu if there are actions
                if menu.actions():
                    menu.exec(global_pos)

    def _move_selected_to_tab(self, gallery_paths, target_tab):
        """Move selected galleries to the specified tab"""
        if not gallery_paths or not target_tab:
            return

        # Find the tabbed gallery widget to access tab manager
        tabbed_widget = self
        while tabbed_widget and not hasattr(tabbed_widget, 'tab_manager'):
            tabbed_widget = tabbed_widget.parent()

        if tabbed_widget and hasattr(tabbed_widget, 'tab_manager') and tabbed_widget.tab_manager:
            try:
                moved_count = tabbed_widget.tab_manager.move_galleries_to_tab(gallery_paths, target_tab)
                log(f"Right-click move_galleries_to_tab returned moved_count={moved_count}", level="debug", category="queue")

                # Update queue manager's in-memory items to match database
                log(f"Checking conditions - moved_count={moved_count}, has_queue_manager={hasattr(tabbed_widget, 'queue_manager')}, has_tab_manager={bool(tabbed_widget.tab_manager)}", level="debug", category="queue")

                # Find the widget with queue_manager
                queue_widget = tabbed_widget
                while queue_widget and not hasattr(queue_widget, 'queue_manager'):
                    queue_widget = queue_widget.parent()

                log(f"Found queue_widget={bool(queue_widget)}, has_queue_manager={hasattr(queue_widget, 'queue_manager') if queue_widget else False}", level="debug", category="queue")

                if moved_count > 0 and queue_widget and hasattr(queue_widget, 'queue_manager') and tabbed_widget.tab_manager:
                    # Get the tab_id for the target tab
                    tab_info = tabbed_widget.tab_manager.get_tab_by_name(target_tab)
                    tab_id = tab_info.id if tab_info else 1

                    for path in gallery_paths:
                        item = queue_widget.queue_manager.get_item(path)
                        if item:
                            old_tab = item.tab_name
                            item.tab_name = target_tab
                            item.tab_id = tab_id
                            log(f"Right-click updated item {path} tab: '{old_tab}' -> '{target_tab}' (item.tab_name is now '{item.tab_name}')", level="debug", category="ui")

                # Invalidate caches and refresh display
                if moved_count > 0:
                    #log(f"RIGHT-CLICK calling invalidate_tab_cache() on {type(tabbed_widget).__name__}", level="debug", category="ui")

                    # Check database counts BEFORE cache invalidation
                    #main_count_before = len(tabbed_widget.tab_manager.load_tab_galleries('Main'))
                    #target_count_before = len(tabbed_widget.tab_manager.load_tab_galleries(target_tab))
                    #log(f"RIGHT-CLICK BEFORE invalidate - Main={main_count_before}, {target_tab}={target_count_before}", level="debug", category="ui")

                    tabbed_widget.tab_manager.invalidate_tab_cache()

                    # Check database counts AFTER cache invalidation
                    #main_count_after = len(tabbed_widget.tab_manager.load_tab_galleries('Main'))
                    #target_count_after = len(tabbed_widget.tab_manager.load_tab_galleries(target_tab))

                    tabbed_widget.refresh_filter()

                    # Update tab tooltips to reflect new counts
                    if hasattr(tabbed_widget, '_update_tab_tooltips'):
                        tabbed_widget._update_tab_tooltips()
                    log(f"RIGHT-CLICK PATH - Moved {moved_count} galler{'y' if moved_count == 1 else 'ies'} to '{target_tab}' tab", level="debug", category="ui")

            except Exception as e:
                print(e)
                log(f"Error moving galleries to tab '{target_tab}': {e}", level="error")


    def manage_gallery_files(self, path: str):
        """Open the file manager dialog for a gallery"""
        # Find the parent ImxUploadGUI window
        from PyQt6.QtWidgets import QMainWindow
        parent_window = self
        while parent_window and not isinstance(parent_window, QMainWindow):
            parent_window = parent_window.parent()

        if parent_window:
            # Create and show the file manager dialog
            dialog = GalleryFileManagerDialog(path, parent_window.queue_manager, parent_window)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                # Refresh the gallery display if files were modified
                if hasattr(parent_window, 'refresh_filter'):
                    parent_window.refresh_filter()

    def rename_gallery(self, path: str):
        """Handle gallery rename from context menu"""
        # Find the parent ImxUploadGUI window
        from PyQt6.QtWidgets import QMainWindow
        parent_window = self
        while parent_window and not isinstance(parent_window, QMainWindow):
            parent_window = parent_window.parent()

        if not parent_window:
            return

        item = parent_window.queue_manager.get_item(path)
        if not item:
            return

        current_name = item.name or os.path.basename(path)

        # Create a properly sized input dialog
        dialog = QInputDialog(parent_window)
        dialog.setWindowTitle("Rename Gallery")
        dialog.setLabelText("New gallery name:")
        dialog.setTextValue(current_name)

        # Make dialog wide enough to show the full gallery name
        # Calculate width based on text length, with reasonable min/max bounds
        text_width = len(current_name) * 8  # Approximate character width
        dialog_width = max(400, min(800, text_width + 100))  # Min 400px, max 800px
        dialog.resize(dialog_width, dialog.sizeHint().height())

        ok = dialog.exec()
        new_name = dialog.textValue()

        if ok and new_name and new_name.strip() != current_name:
            new_name = new_name.strip()
            # Update in queue manager
            if parent_window.queue_manager.update_gallery_name(path, new_name):
                # Update table display for this specific item
                if hasattr(parent_window, '_update_specific_gallery_display'):
                    parent_window._update_specific_gallery_display(path)
                # Log the change
                log(f"Renamed gallery to: {new_name}", level="debug")

                # Auto-regenerate BBCode (setting checked inside function)
                try:
                    parent_window.regenerate_bbcode_for_gallery(path)
                    # Only log if regeneration actually happened (could check if enabled first)
                    from imxup import load_user_defaults
                    defaults = load_user_defaults()
                    if defaults.get('auto_regenerate_bbcode', True):
                        log(f"BBCode regenerated for renamed gallery: {new_name}", level="debug")
                except Exception as e:
                    log(f"Error auto-regenerating BBCode for renamed gallery {path}: {e}", level="error")

    def dragEnterEvent(self, event):
        """Handle drag enter events"""
        # Check if we're dragging files
        if event.mimeData().hasUrls():
            # Check if any URLs are image files
            has_images = False
            for url in event.mimeData().urls():
                path = url.toLocalFile()
                if os.path.isfile(path) and path.lower().endswith(IMAGE_EXTENSIONS):
                    has_images = True
                    break

            if has_images:
                event.acceptProposedAction()
                return

        # Otherwise, use default handling for gallery moves
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        """Handle drag move events"""
        if event.mimeData().hasUrls():
            # Highlight the row under cursor
            pos = event.position().toPoint()
            index = self.indexAt(pos)
            if index.isValid():
                event.acceptProposedAction()
            else:
                event.ignore()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        """Handle drop events - both gallery moves and file drops"""
        # Check if we're dropping files
        if event.mimeData().hasUrls():
            # Get the row where files are being dropped
            pos = event.position().toPoint()
            index = self.indexAt(pos)

            if index.isValid():
                row = index.row()
                # Get the gallery path from the row
                name_item = self.item(row, GalleryTableWidget.COL_NAME)
                if name_item:
                    gallery_path = name_item.data(Qt.ItemDataRole.UserRole)
                    if gallery_path:
                        # Filter for image files
                        image_files = []
                        for url in event.mimeData().urls():
                            path = url.toLocalFile()
                            if os.path.isfile(path) and path.lower().endswith(IMAGE_EXTENSIONS):
                                image_files.append(path)

                        if image_files:
                            # Ask for confirmation
                            gallery_name = os.path.basename(gallery_path)
                            file_word = "file" if len(image_files) == 1 else "files"
                            reply = QMessageBox.question(
                                self,
                                "Add Files to Gallery",
                                f"Add {len(image_files)} {file_word} to '{gallery_name}'?",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                            )

                            if reply == QMessageBox.StandardButton.Yes:
                                # Add files to the gallery
                                self.add_files_to_gallery(gallery_path, image_files)
                                event.acceptProposedAction()
                                return

            event.ignore()
        else:
            # Default handling for gallery moves
            super().dropEvent(event)

    def add_files_to_gallery(self, gallery_path: str, files: List[str]):
        """Add files to a gallery"""
        import shutil

        # Find the parent ImxUploadGUI window to access queue manager
        from PyQt6.QtWidgets import QMainWindow
        parent_window = self
        while parent_window and not isinstance(parent_window, QMainWindow):
            parent_window = parent_window.parent()

        if not parent_window or not hasattr(parent_window, 'queue_manager'):
            return

        queue_manager = parent_window.queue_manager
        gallery_item = queue_manager.get_item(gallery_path)

        if not gallery_item:
            return

        # Copy files to gallery folder
        added_count = 0
        failed_files = []

        for filepath in files:
            filename = os.path.basename(filepath)
            dest_path = os.path.join(gallery_path, filename)

            try:
                # Copy file if not already there
                if filepath != dest_path:
                    shutil.copy2(filepath, dest_path)
                added_count += 1
            except Exception as e:
                failed_files.append((filename, str(e)))

        # Update gallery based on status
        if added_count > 0:
            # Always trigger additive rescan to properly detect and count new files
            queue_manager.rescan_gallery_additive(gallery_path)

            # For completed galleries, also mark as incomplete so they can be resumed
            if gallery_item.status == "completed":
                gallery_item.status = "incomplete"
                queue_manager.update_item_status(gallery_path, "incomplete")

            # Show success message
            gallery_name = os.path.basename(gallery_path)
            log(f"Added {added_count} file(s) to {gallery_name}", level="info")

            # Refresh display to show updated status
            if hasattr(parent_window, 'refresh_filter'):
                parent_window.refresh_filter()
            elif hasattr(parent_window, '_update_specific_gallery_display'):
                parent_window._update_specific_gallery_display(gallery_path)

        # Show error if any files failed
        if failed_files:
            error_msg = f"Failed to add {len(failed_files)} file(s):\n"
            for filename, error in failed_files[:5]:  # Show first 5 errors
                error_msg += f"\n• {filename}: {error}"
            if len(failed_files) > 5:
                error_msg += f"\n... and {len(failed_files) - 5} more"
            QMessageBox.warning(self, "Some Files Failed", error_msg)

    def contextMenuEvent(self, event):
        """Fallback to ensure context menu always appears on right-click"""
        try:
            viewport_pos = self.viewport().mapFromGlobal(event.globalPos())
        except Exception:
            viewport_pos = event.pos()
        self.show_context_menu(viewport_pos)

    def delete_selected_via_menu(self):
        """Delete selected items via context menu"""
        # Find the main GUI window
        widget = self
        while widget:
            if hasattr(widget, 'delete_selected_items'):
                widget.delete_selected_items()
                return
            widget = widget.parent()

    def start_selected_via_menu(self):
        """Start selected items in their current visual order"""
        # Determine selected rows in visual order as shown
        selected_rows = sorted({it.row() for it in self.selectedItems()})
        if not selected_rows:
            return
        # Gather paths from column 1 for those rows
        paths_in_order = []
        for row in selected_rows:
            name_item = self.item(row, GalleryTableWidget.COL_NAME)
            if name_item:
                path = name_item.data(Qt.ItemDataRole.UserRole)
                if path:
                    paths_in_order.append(path)
        if not paths_in_order:
            return
        # Delegate to main window to start items individually preserving order
        widget = self
        while widget and not hasattr(widget, 'queue_manager'):
            widget = widget.parent()
        if not widget:
            return
        started = 0
        started_paths = []
        # Use batch context to group all database saves into a single transaction
        with widget.queue_manager.batch_updates():
            for path in paths_in_order:
                if widget.queue_manager.start_item(path):
                    started += 1
                    started_paths.append(path)
        if started:
            log(f"Started {started} selected item(s)", level="info")
            # Update only the affected rows instead of full table refresh
            if hasattr(widget, '_update_specific_gallery_display'):
                for path in started_paths:
                    widget._update_specific_gallery_display(path)

    def open_folders_via_menu(self, paths):
        """Open the given gallery folders in the OS file manager"""
        for path in paths:
            if os.path.isdir(path):
                QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def cancel_selected_via_menu(self, queued_paths):
        """Cancel upload for selected queued items"""
        widget = self
        while widget and not hasattr(widget, 'cancel_single_item'):
            widget = widget.parent()
        if widget and hasattr(widget, 'cancel_single_item'):
            # Use batch processing for multiple cancellations to prevent GUI hang
            if len(queued_paths) > 1:
                widget.cancel_multiple_items(queued_paths)
            else:
                widget.cancel_single_item(queued_paths[0])

    def retry_selected_via_menu(self, failed_paths):
        """Retry failed uploads for selected items"""
        widget = self
        while widget and not hasattr(widget, 'queue_manager'):
            widget = widget.parent()

        if widget and hasattr(widget, 'queue_manager'):
            for path in failed_paths:
                try:
                    widget.queue_manager.retry_failed_upload(path)
                    item = widget.queue_manager.get_item(path)
                    gallery_name = item.name if item else os.path.basename(path)
                    log(f"Retrying upload for {gallery_name}", level="info")
                except Exception as e:
                    log(f"Error retrying {path}: {e}", level="info")

    def rescan_additive_via_menu(self, paths):
        """Smart rescan - only detect new images, preserve existing uploads"""
        widget = self
        while widget and not hasattr(widget, 'queue_manager'):
            widget = widget.parent()

        if widget and hasattr(widget, 'queue_manager'):
            for path in paths:
                try:
                    # Use the worker queue instead of blocking direct scan
                    widget.queue_manager._scan_queue.put(path)
                    item = widget.queue_manager.get_item(path)
                    gallery_name = item.name if item else os.path.basename(path)
                    log(f"Queued {gallery_name} for rescan", level="info")
                except Exception as e:
                    log(f"Error queuing scan for {path}: {e}", level="info")

    def rescan_all_items_via_menu(self, paths):
        """Rescan all items in gallery - refresh failed/incomplete items while preserving successful uploads"""
        widget = self
        while widget and not hasattr(widget, 'queue_manager'):
            widget = widget.parent()

        if widget and hasattr(widget, 'queue_manager'):
            for path in paths:
                try:
                    # Use the worker queue instead of blocking methods
                    widget.queue_manager._scan_queue.put(path)
                    item = widget.queue_manager.get_item(path)
                    gallery_name = item.name if item else os.path.basename(path)
                    log(f"Queued {gallery_name} for complete rescan", level="info")
                except Exception as e:
                    log(f"Error queuing rescan for {path}: {e}", level="error")

    def reset_gallery_via_menu(self, paths):
        """Complete gallery reset with confirmation dialog"""
        # Show confirmation dialog
        count = len(paths)
        gallery_word = "gallery" if count == 1 else "galleries"

        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setWindowTitle("Reset Gallery")
        msg.setText(f"Reset {count} {gallery_word}?")
        msg.setInformativeText(
            "This will permanently clear all upload progress and rescan from scratch.\n"
            "Any existing gallery links will be lost.\n\n"
            "Use this when you've replaced/renamed files or want to re-upload everything."
        )
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        msg.setDefaultButton(QMessageBox.StandardButton.Cancel)

        if msg.exec() == QMessageBox.StandardButton.Yes:
            widget = self
            while widget and not hasattr(widget, 'queue_manager'):
                widget = widget.parent()

            if widget and hasattr(widget, 'queue_manager'):
                for path in paths:
                    try:
                        widget.queue_manager.reset_gallery_complete(path)
                        item = widget.queue_manager.get_item(path)
                        gallery_name = item.name if item else os.path.basename(path)
                        log(f"Reset {gallery_name} - starting fresh scan", level="info")
                    except Exception as e:
                        log(f"Error resetting {path}: {e}", level="info", category="queue")

                # Force refresh of the display to show scanning status
                if hasattr(widget, 'refresh_filter'):
                    QTimer.singleShot(200, widget.refresh_filter)

                # Trigger scanning using the worker queue for each reset path
                for path in paths:
                    try:
                        # Add to scan queue to trigger actual scanning
                        widget.queue_manager._scan_queue.put(path)
                        log(f"Added {path} to scan queue after reset", level="debug", category="queue")
                    except Exception as e:
                        log(f"Error queuing scan for {path}: {e}", level="info", category="queue")

    def rescan_selected_via_menu(self, scan_failed_paths):
        """Legacy method - redirect to additive rescan"""
        self.rescan_additive_via_menu(scan_failed_paths)

    def copy_bbcode_via_menu_multi(self, paths):
        """Copy BBCode for multiple completed items (concatenated with separators)"""
        # Find the main GUI window
        widget = self
        while widget and not hasattr(widget, 'queue_manager'):
            widget = widget.parent()
        if not widget:
            log(f"No widget with queue_manager found", level="warning", category="fileio")
            return
        # Aggregate BBCode contents; reuse copy function to centralize path lookup
        contents = []
        for path in paths:
            item = widget.queue_manager.get_item(path)
            if not item:
                log(f"No item found for path: {path}", level="debug")
                continue
            #print(f"DEBUG: Item status: {item.status}, gallery_id: {getattr(item, 'gallery_id', 'MISSING')}")
            if item.status != "completed":
                continue
            # Inline read similar to copy_bbcode_to_clipboard to avoid changing it
            folder_name = os.path.basename(path)
            # Use cached functions or fallbacks
            if hasattr(widget, '_get_central_storage_path'):
                base_path = widget._get_central_storage_path()
                central_path = os.path.join(base_path, "galleries")
                #print(f"DEBUG: Using widget._get_central_storage_path: {central_path}")
            else:
                central_path = os.path.expanduser("~/.imxup/galleries")
                log(f"Using fallback central_path: {central_path}", level="debug")
            if item.gallery_id and (item.name or folder_name):
                #print(f"DEBUG: Has gallery_id and name, item.name: {getattr(item, 'name', 'MISSING')}")
                if hasattr(widget, '_build_gallery_filenames'):
                    _, _, bbcode_filename = widget._build_gallery_filenames(item.name or folder_name, item.gallery_id)
                else:
                    # No sanitization - only rename worker should sanitize
                    gallery_name = item.name or folder_name
                    bbcode_filename = f"{gallery_name}_{item.gallery_id}_bbcode.txt"
                    log(f"Using fallback filename: {bbcode_filename}", level="debug")
                central_bbcode = os.path.join(central_path, bbcode_filename)
            else:
                central_bbcode = os.path.join(central_path, f"{folder_name}_bbcode.txt")
                log(f"Using folder_name fallback: {central_bbcode}", level="debug")
            #print(f"DEBUG: Looking for BBCode file: {central_bbcode}  File exists: {os.path.exists(central_bbcode)}")

            # If exact file doesn't exist, try pattern-based lookup
            if not os.path.exists(central_bbcode) and item.gallery_id:
                import glob
                #print(f"DEBUG: Exact file not found, trying pattern for gallery_id: {item.gallery_id}")
                pattern = os.path.join(central_path, f"*_{item.gallery_id}_bbcode.txt")
                matches = glob.glob(pattern)
                #print(f"DEBUG: Pattern '{pattern}' found {len(matches)} matches: {matches}")
                if matches:
                    central_bbcode = matches[0]
                    #print(f"DEBUG: Using pattern match: {central_bbcode}")

            # Move file I/O to background to avoid blocking GUI
            def _read_bbcode_async():
                text = ""
                if os.path.exists(central_bbcode):
                    try:
                        with open(central_bbcode, 'r', encoding='utf-8') as f:
                            text = f.read().strip()
                    except Exception:
                        text = ""
                return text

            # For now, read synchronously but this should be moved to a background worker
            text = _read_bbcode_async()
            if text:
                contents.append(text)
        num_posts = len(contents)
        if num_posts:
            QApplication.clipboard().setText("\n\n".join(contents))
            # Notify user via log and brief status message
            try:
                message = f"Copied BBCode to clipboard for {num_posts} post" + ("s" if num_posts != 1 else "")
                log(f"{message}", level="info")
                # Status bar brief message
                if hasattr(widget, 'statusBar') and widget.statusBar():
                    widget.statusBar().showMessage(message, 2500)
            except Exception as e:
                log(f"Exception in gallery_table: {e}", level="error", category="ui")
                raise
        else:
            # Inform user nothing was copied
            try:
                message = "No completed posts selected to copy BBCode"
                log(f"{message}", level="warning")
                if hasattr(widget, 'statusBar') and widget.statusBar():
                    widget.statusBar().showMessage(message, 2500)
            except Exception as e:
                log(f"Exception in gallery_table: {e}", level="error", category="ui")
                raise

    def open_gallery_links_via_menu(self, paths):
        """Open gallery link(s) in the system browser for completed items."""
        # Find the main GUI window for access to queue_manager and logging
        widget = self
        while widget and not hasattr(widget, 'queue_manager'):
            widget = widget.parent()
        if not widget:
            return
        opened = 0
        for path in paths:
            try:
                item = widget.queue_manager.get_item(path)
            except Exception:
                item = None
            if not item or item.status != "completed":
                continue
            url = (item.gallery_url or "").strip()
            if not url:
                # Fallback: attempt to read JSON and extract meta.gallery_url
                try:
                    folder_name = os.path.basename(path)
                    from imxup import get_central_storage_path, build_gallery_filenames
                    json_path_candidates = []
                    uploaded_subdir = os.path.join(path, ".uploaded")
                    if item.gallery_id and (item.name or folder_name):
                        _, json_filename, _ = build_gallery_filenames(item.name or folder_name, item.gallery_id)
                        json_path_candidates.append(os.path.join(uploaded_subdir, json_filename))
                        json_path_candidates.append(os.path.join(get_central_storage_path(), json_filename))
                    # As a last resort, consider any JSON inside .uploaded
                    if os.path.isdir(uploaded_subdir):
                        for fname in os.listdir(uploaded_subdir):
                            if fname.lower().endswith('.json'):
                                json_path_candidates.append(os.path.join(uploaded_subdir, fname))
                    for jp in json_path_candidates:
                        if os.path.exists(jp):
                            with open(jp, 'r', encoding='utf-8') as f:
                                data = json.load(f)
                                url = ((data.get('meta') or {}).get('gallery_url') or "").strip()
                            if url:
                                break
                except Exception:
                    url = ""
            if url:
                try:
                    QDesktopServices.openUrl(QUrl(url))
                    opened += 1
                except Exception as e:
                    log(f"Exception in gallery_table: {e}", level="error", category="ui")
                    raise
        # Brief user feedback
        try:
            if opened:
                message = f"Opened {opened} gallery link" + ("s" if opened != 1 else "")
            else:
                message = "No gallery link found to open"
                log(f"{message}", level="debug")
            if hasattr(widget, 'statusBar') and widget.statusBar():
                widget.statusBar().showMessage(message, 2500)
        except Exception as e:
            log(f"Exception in gallery_table: {e}", level="error", category="ui")
            raise
