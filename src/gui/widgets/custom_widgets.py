"""
Custom widget classes for ImxUp application.
Provides specialized UI components.
"""

import os
from typing import Optional, List, Dict, Any
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QProgressBar,
    QLabel, QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QStyle, QMenu, QMessageBox, QTabBar, QListWidget, QApplication
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QMimeData, QPoint, QSize
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QDragEnterEvent, QDropEvent, QKeyEvent

from src.core.constants import (
    QUEUE_STATE_READY, QUEUE_STATE_QUEUED, QUEUE_STATE_UPLOADING,
    QUEUE_STATE_COMPLETED, QUEUE_STATE_FAILED, QUEUE_STATE_PAUSED,
    QUEUE_STATE_INCOMPLETE, ICON_SIZE, TABLE_UPDATE_INTERVAL
)


class TableProgressWidget(QWidget):
    """Custom progress bar widget for table cells"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.progress = 0
        self.status_text = ""
        self.setup_ui()
    
    def setup_ui(self):
        """Initialize the UI"""
        layout = QVBoxLayout()
        layout.setContentsMargins(2, 2, 2, 2)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setProperty("class", "table-progress")
        
        layout.addWidget(self.progress_bar)
        self.setLayout(layout)
    
    def set_progress(self, value: int, text: str = ""):
        """Set progress value and optional text"""
        self.progress = value
        self.status_text = text
        self.progress_bar.setValue(value)
        
        if text:
            self.progress_bar.setFormat(f"{text} - {value}%")
        else:
            self.progress_bar.setFormat(f"{value}%")
    
    def get_progress(self) -> int:
        """Get current progress value"""
        return self.progress
    
    def update_progress(self, value: int, status: str = ""):
        """Update progress value with status-based styling"""
        self.progress_bar.setValue(value)
        
        # Set CSS class-like properties for theme-based styling via styles.qss
        self.progress_bar.setProperty("status", status)
        
        # Force style update to apply new property
        self.progress_bar.style().polish(self.progress_bar)


class ActionButtonWidget(QWidget):
    """Action buttons widget for table cells"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        from src.gui.icon_manager import get_icon_manager
        self.icon_manager = get_icon_manager()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 1, 4, 1)  # Better horizontal padding, minimal vertical
        layout.setSpacing(3)  # Slightly better spacing between buttons
        layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)  # left-align and center vertically
        
        # Set consistent minimum height for the widget to match table row height
        self.setProperty("class", "status-row")
        
        self.start_btn = QPushButton("Start")
        self.start_btn.setFixedSize(22, 22)  # smaller icon-only buttons
        # Set icon and hover style
        try:
            self.start_btn.setIcon(self.icon_manager.get_icon('start'))
            self.start_btn.setIconSize(QSize(18, 18))
            self.start_btn.setText("")
            self.start_btn.setToolTip("Start")
            self.start_btn.setProperty("class", "icon-btn")
        except Exception:
            pass
        
        #self.start_btn.setStyleSheet("""
        #    QPushButton {
        #        background-color: #d8f0e2;
        #        border: 1px solid #85a190;
        #        border-radius: 3px;
        #        font-size: 12px;
        #    }
        #    QPushButton:hover {
        #        background-color: #bee6cf;
        #        border: 1px solid #85a190;
        #    }
        #    QPushButton:pressed {
        #        background-color: #6495ed;
        #        border: 1px solid #1e2c47;
        #    }
        #""")
        
        self.stop_btn = QPushButton("Stop")
        
        self.stop_btn.setFixedSize(22, 22)  # smaller icon-only buttons
        self.stop_btn.setVisible(False)
        try:
            self.stop_btn.setIcon(self.icon_manager.get_icon('stop'))
            self.stop_btn.setIconSize(QSize(18, 18))
            self.stop_btn.setText("")
            self.stop_btn.setToolTip("Stop")
            self.stop_btn.setProperty("class", "icon-btn")
        except Exception:
            pass
        #self.stop_btn.setStyleSheet("""
        #    QPushButton {
        #        background-color: #f0938a;

        #        border: 1px solid #cf4436;
        #        border-radius: 3px;
        #        font-size: 12px;

        #    }
        #    QPushButton:hover {
        #        background-color: #c0392b;
        #    }
        #    QPushButton:pressed {
        #        background-color: #a93226;
        #        border: 1px solid #8b291a;
        #    }
        #""")
        
        self.view_btn = QPushButton("View")
        self.view_btn.setFixedSize(22, 22)  # smaller icon-only buttons
        self.view_btn.setVisible(False)
        try:
            self.view_btn.setIcon(self.icon_manager.get_icon('view'))
            self.view_btn.setIconSize(QSize(18, 18))
            self.view_btn.setText("")
            self.view_btn.setToolTip("View")
            self.view_btn.setProperty("class", "icon-btn")
        except Exception:
            pass
        #self.view_btn.setStyleSheet("""
        #    QPushButton {
        #        background-color: #dfe9fb;
        #        border: 1px solid #999;
        #        border-radius: 3px;
        #        font-size: 12px;

        #    }
        #    QPushButton:hover {
        #        background-color: #c8d9f8;
        #        border: 1px solid #7b8dac;
        #    }
        #    QPushButton:pressed {
        #        background-color: #072213;
        #    }
        #""")
        
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setFixedSize(22, 22)  # smaller icon-only buttons
        self.cancel_btn.setVisible(False)
        try:
            # Use pause.png as requested
            self.cancel_btn.setIcon(self.icon_manager.get_icon('cancel'))
            self.cancel_btn.setIconSize(QSize(18, 18))
            self.cancel_btn.setText("")
            self.cancel_btn.setToolTip("Pause/Cancel queued item")
            self.cancel_btn.setProperty("class", "icon-btn")
        except Exception:
            pass    
        #self.cancel_btn.setStyleSheet("""
        #    QPushButton {
        #        background-color: #f7c370;
        #        border: 1px solid #aa6d0c;
        #        border-radius: 3px;
        #        font-size: 12px;
        #    }
        #    QPushButton:hover {
        #        background-color: #f5af41;
        #        border: 1px solid #794e09;
        #    }
        #    QPushButton:pressed {
        #        background-color: #f39c12;
        #        border: 1px solid #482e05;
        #    }
        #""")
        
        layout.addWidget(self.start_btn)
        layout.addWidget(self.stop_btn)
        layout.addWidget(self.view_btn)
        layout.addWidget(self.cancel_btn)
        # Default to left alignment; will auto-center only if content fits
        layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self._layout = layout

    def resizeEvent(self, event):
        super().resizeEvent(event)
        try:
            # Auto-center actions only if all visible buttons fit in the available width
            visible_buttons = [b for b in (self.start_btn, self.stop_btn, self.view_btn, self.cancel_btn) if b.isVisible()]
            if not visible_buttons:
                return
            spacing = self._layout.spacing() or 3
            content_width = sum(btn.width() for btn in visible_buttons) + spacing * (len(visible_buttons) - 1)
            if content_width <= self.width():
                self._layout.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
            else:
                self._layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        except Exception:
            pass
    
    def update_buttons(self, status: str):
        """Update button visibility based on status"""
        if status == "ready":
            self.start_btn.setVisible(True)
            self.start_btn.setToolTip("Start")
            self.stop_btn.setVisible(False)
            self.view_btn.setVisible(False)
            self.cancel_btn.setVisible(False)
        elif status == "queued":
            self.start_btn.setVisible(False)
            self.stop_btn.setVisible(False)
            self.view_btn.setVisible(False)
            self.cancel_btn.setVisible(True)
        elif status == "uploading":
            self.start_btn.setVisible(False)
            self.stop_btn.setVisible(True)
            self.stop_btn.setToolTip("Stop")
            self.view_btn.setVisible(False)
            self.cancel_btn.setVisible(False)
        elif status == "paused":
            self.start_btn.setVisible(True)
            self.start_btn.setToolTip("Resume")
            self.stop_btn.setVisible(False)
            self.view_btn.setVisible(False)
            self.cancel_btn.setVisible(False)
        elif status == "incomplete":
            self.start_btn.setVisible(True)
            self.start_btn.setToolTip("Resume")
            self.stop_btn.setVisible(False)
            self.view_btn.setVisible(False)
            self.cancel_btn.setVisible(False)
        elif status == "completed":
            self.start_btn.setVisible(False)
            self.stop_btn.setVisible(False)
            self.view_btn.setVisible(True)
            self.view_btn.setIcon(self.icon_manager.get_icon('view'))
            self.view_btn.setToolTip("View BBCode")
            self.cancel_btn.setVisible(False)
        elif status == "failed":
            self.start_btn.setVisible(False)
            self.stop_btn.setVisible(False)
            self.view_btn.setVisible(True)
            self.view_btn.setIcon(self.icon_manager.get_icon('view_error'))
            self.view_btn.setToolTip("View error details")
            self.cancel_btn.setVisible(False)
        else:  # other statuses
            self.start_btn.setVisible(False)
            self.stop_btn.setVisible(False)
            self.view_btn.setVisible(False)
            self.cancel_btn.setVisible(False)

    def refresh_icons(self):
        """Refresh all button icons for theme changes"""
        try:
            # Refresh all button icons
            self.start_btn.setIcon(self.icon_manager.get_icon('start'))
            self.stop_btn.setIcon(self.icon_manager.get_icon('stop'))
            self.view_btn.setIcon(self.icon_manager.get_icon('view'))
            self.cancel_btn.setIcon(self.icon_manager.get_icon('cancel'))

            # If view button is currently showing error icon, update that too
            if self.view_btn.isVisible() and self.view_btn.toolTip() == "View error details":
                self.view_btn.setIcon(self.icon_manager.get_icon('view_error'))
        except Exception:
            pass


class StatusIconWidget(QWidget):
    """Widget for displaying status with an icon"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.status = QUEUE_STATE_READY
        self.setup_ui()
    
    def setup_ui(self):
        """Initialize the UI"""
        layout = QHBoxLayout()
        layout.setContentsMargins(2, 2, 2, 2)
        
        self.icon_label = QLabel()
        self.status_label = QLabel("Ready")
        
        layout.addWidget(self.icon_label)
        layout.addWidget(self.status_label)
        layout.addStretch()
        
        self.setLayout(layout)
        self.update_status(QUEUE_STATE_READY)
    
    def update_status(self, status: str):
        """Update status display"""
        self.status = status
        
        # Set icon based on status
        style = self.style()
        if status == QUEUE_STATE_READY:
            icon = style.standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton)
            self.status_label.setText("Ready")
            
        elif status == QUEUE_STATE_QUEUED:
            icon = style.standardIcon(QStyle.StandardPixmap.SP_ArrowRight)
            self.status_label.setText("Queued")
            
        elif status == QUEUE_STATE_UPLOADING:
            icon = style.standardIcon(QStyle.StandardPixmap.SP_ArrowUp)
            self.status_label.setText("Uploading")
            
        elif status == QUEUE_STATE_PAUSED:
            icon = style.standardIcon(QStyle.StandardPixmap.SP_MediaPause)
            self.status_label.setText("Paused")
            
        elif status == QUEUE_STATE_COMPLETED:
            icon = style.standardIcon(QStyle.StandardPixmap.SP_DialogYesButton)
            self.status_label.setText("Completed")
            
        elif status == QUEUE_STATE_FAILED:
            icon = style.standardIcon(QStyle.StandardPixmap.SP_DialogCancelButton)
            self.status_label.setText("Failed")
            
        elif status == QUEUE_STATE_INCOMPLETE:
            icon = style.standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning)
            self.status_label.setText("Incomplete")
            
        else:
            icon = style.standardIcon(QStyle.StandardPixmap.SP_MessageBoxQuestion)
            self.status_label.setText("Unknown")
        
        pixmap = icon.pixmap(ICON_SIZE, ICON_SIZE)
        self.icon_label.setPixmap(pixmap)


class NumericTableWidgetItem(QTableWidgetItem):
    """Table widget item that sorts numerically"""
    
    def __init__(self, value: Any = ""):
        super().__init__(str(value))
        self._sort_value = value
    
    def __lt__(self, other):
        """Compare for sorting"""
        if isinstance(other, NumericTableWidgetItem):
            # Try numeric comparison first
            try:
                return float(self._sort_value) < float(other._sort_value)
            except (ValueError, TypeError):
                # Fall back to string comparison
                return str(self._sort_value) < str(other._sort_value)
        return super().__lt__(other)
    
    def set_value(self, value: Any):
        """Set the value and display text"""
        self._sort_value = value
        self.setText(str(value))


class DropEnabledTabBar(QTabBar):
    """Tab bar that accepts drag and drop of folders"""
    
    files_dropped = pyqtSignal(list, int)  # files, tab_index
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
    
    def dragEnterEvent(self, event: QDragEnterEvent):
        """Handle drag enter event"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
    
    def dragMoveEvent(self, event):
        """Handle drag move event"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
    
    def dropEvent(self, event: QDropEvent):
        """Handle drop event"""
        if event.mimeData().hasUrls():
            # Determine which tab the drop occurred on
            drop_pos = event.position().toPoint()
            tab_index = self.tabAt(drop_pos)
            
            if tab_index == -1:
                # Dropped outside any tab, use current tab
                tab_index = self.currentIndex()
            
            # Extract folder paths
            folders = []
            for url in event.mimeData().urls():
                path = url.toLocalFile()
                if os.path.isdir(path):
                    folders.append(path)
            
            if folders:
                self.files_dropped.emit(folders, tab_index)
                event.acceptProposedAction()


class GalleryTableWidget(QTableWidget):
    """Custom table widget for displaying gallery queue"""
    
    # Signals
    selection_changed = pyqtSignal(list)  # selected paths
    context_menu_requested = pyqtSignal(QPoint, list)  # position, selected paths
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
    
    def setup_ui(self):
        """Initialize the UI"""
        # Set table properties
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setSortingEnabled(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        
        # Connect signals
        self.itemSelectionChanged.connect(self.on_selection_changed)
        self.customContextMenuRequested.connect(self.on_context_menu)
        
        # Set up columns
        self.setup_columns()
    
    def setup_columns(self):
        """Set up table columns"""
        columns = [
            "Status", "Gallery Name", "Path", "Images", "Size",
            "Progress", "Speed", "Time", "Template", "Actions"
        ]
        
        self.setColumnCount(len(columns))
        self.setHorizontalHeaderLabels(columns)
        
        # Set column widths
        header = self.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)  # Status
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)  # Gallery Name
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)  # Path
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)  # Progress
        header.setSectionResizeMode(9, QHeaderView.ResizeMode.Fixed)  # Actions
        
        self.setColumnWidth(5, 150)  # Progress
        self.setColumnWidth(9, 200)  # Actions
    
    def on_selection_changed(self):
        """Handle selection change"""
        selected_paths = []
        for item in self.selectedItems():
            if item.column() == 0:  # Only count once per row
                row = item.row()
                path_item = self.item(row, 2)  # Path column
                if path_item:
                    selected_paths.append(path_item.text())
        
        self.selection_changed.emit(selected_paths)
    
    def on_context_menu(self, position: QPoint):
        """Handle context menu request"""
        selected_paths = []
        for item in self.selectedItems():
            if item.column() == 0:  # Only count once per row
                row = item.row()
                path_item = self.item(row, 2)  # Path column
                if path_item:
                    selected_paths.append(path_item.text())
        
        if selected_paths:
            self.context_menu_requested.emit(position, selected_paths)
    
    def add_gallery_row(self, gallery_data: Dict[str, Any]) -> int:
        """Add a new gallery row to the table"""
        row = self.rowCount()
        self.insertRow(row)
        
        # Status
        status_widget = StatusIconWidget()
        status_widget.update_status(gallery_data.get('status', QUEUE_STATE_READY))
        self.setCellWidget(row, 0, status_widget)
        
        # Gallery Name
        self.setItem(row, 1, QTableWidgetItem(gallery_data.get('name', '')))
        
        # Path
        self.setItem(row, 2, QTableWidgetItem(gallery_data.get('path', '')))
        
        # Images
        images_item = NumericTableWidgetItem(gallery_data.get('total_images', 0))
        self.setItem(row, 3, images_item)
        
        # Size
        size_mb = gallery_data.get('total_size', 0) / (1024 * 1024)
        size_item = NumericTableWidgetItem(f"{size_mb:.1f} MB")
        size_item.set_value(gallery_data.get('total_size', 0))
        self.setItem(row, 4, size_item)
        
        # Progress
        progress_widget = TableProgressWidget()
        progress_widget.set_progress(gallery_data.get('progress', 0))
        self.setCellWidget(row, 5, progress_widget)
        
        # Speed
        self.setItem(row, 6, QTableWidgetItem(""))
        
        # Time
        self.setItem(row, 7, QTableWidgetItem(""))
        
        # Template
        self.setItem(row, 8, QTableWidgetItem(gallery_data.get('template_name', 'default')))
        
        # Actions
        actions_widget = ActionButtonWidget()
        actions_widget.update_state(gallery_data.get('status', QUEUE_STATE_READY))
        self.setCellWidget(row, 9, actions_widget)
        
        return row
    
    def update_gallery_row(self, row: int, gallery_data: Dict[str, Any]):
        """Update an existing gallery row"""
        # Status
        status_widget = self.cellWidget(row, 0)
        if isinstance(status_widget, StatusIconWidget):
            status_widget.update_status(gallery_data.get('status', QUEUE_STATE_READY))
        
        # Progress
        progress_widget = self.cellWidget(row, 5)
        if isinstance(progress_widget, TableProgressWidget):
            progress_widget.set_progress(
                gallery_data.get('progress', 0),
                gallery_data.get('current_image', '')
            )
        
        # Speed
        speed_item = self.item(row, 6)
        if speed_item:
            speed_text = gallery_data.get('speed', '')
            speed_item.setText(speed_text)
        
        # Time
        time_item = self.item(row, 7)
        if time_item:
            time_text = gallery_data.get('time', '')
            time_item.setText(time_text)
        
        # Actions
        actions_widget = self.cellWidget(row, 9)
        if isinstance(actions_widget, ActionButtonWidget):
            actions_widget.update_state(gallery_data.get('status', QUEUE_STATE_READY))
    
    def find_row_by_path(self, path: str) -> Optional[int]:
        """Find table row by gallery path"""
        for row in range(self.rowCount()):
            path_item = self.item(row, 2)
            if path_item and path_item.text() == path:
                return row
        return None


class CopyableLogListWidget(QListWidget):
    """QListWidget with copy support for log messages"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

    def keyPressEvent(self, event: QKeyEvent):
        """Handle Ctrl+C to copy selected log entries"""
        if event.key() == Qt.Key.Key_C and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            self.copy_selected_items()
        else:
            super().keyPressEvent(event)

    def copy_selected_items(self):
        """Copy selected log entries to clipboard"""
        selected_items = self.selectedItems()
        if not selected_items:
            return

        # Get text from all selected items
        texts = [item.text() for item in selected_items]

        # Join with newlines and copy to clipboard
        content = "\n".join(texts)
        clipboard = QApplication.clipboard()
        clipboard.setText(content)

        # Show status bar feedback
        count = len(selected_items)
        entry_word = "entry" if count == 1 else "entries"
        message = f"Copied {count} log {entry_word} to clipboard"

        # Find parent window with status bar
        widget = self.parent()
        while widget:
            if hasattr(widget, 'statusBar') and widget.statusBar():
                widget.statusBar().showMessage(message, 2500)
                break
            widget = widget.parent() if hasattr(widget, 'parent') else None

    def show_context_menu(self, position):
        """Show context menu with copy, log viewer, and log settings options"""
        selected_items = self.selectedItems()

        menu = QMenu(self)

        # Add Copy action only if items are selected
        copy_action = None
        if selected_items:
            copy_action = menu.addAction("Copy")
            copy_action.setShortcut("Ctrl+C")
            menu.addSeparator()

        # Add Log Viewer and Log Settings (always available)
        log_viewer_action = menu.addAction("Log Viewer")
        log_settings_action = menu.addAction("Log Settings")

        action = menu.exec(self.mapToGlobal(position))

        if action == copy_action:
            self.copy_selected_items()
        elif action == log_viewer_action:
            self._open_log_viewer_popup()
        elif action == log_settings_action:
            self._open_log_settings()

    def _open_log_viewer_popup(self):
        """Open the standalone log viewer popup"""
        # Find parent main window
        widget = self.parent()
        while widget:
            if hasattr(widget, 'open_log_viewer_popup'):
                widget.open_log_viewer_popup()
                break
            widget = widget.parent() if hasattr(widget, 'parent') else None

    def _open_log_settings(self):
        """Open comprehensive settings to logs tab"""
        # Find parent main window
        widget = self.parent()
        while widget:
            if hasattr(widget, 'open_log_viewer'):
                widget.open_log_viewer()
                break
            widget = widget.parent() if hasattr(widget, 'parent') else None


class CopyableLogTableWidget(QTableWidget):
    """QTableWidget with copy support for log viewer"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

    def keyPressEvent(self, event: QKeyEvent):
        """Handle Ctrl+C to copy selected log entries"""
        if event.key() == Qt.Key.Key_C and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            self.copy_selected_rows()
        else:
            super().keyPressEvent(event)

    def copy_selected_rows(self):
        """Copy selected log rows to clipboard as plain text"""
        selected_rows = set()
        for item in self.selectedItems():
            selected_rows.add(item.row())

        if not selected_rows:
            return

        # Sort rows in display order
        sorted_rows = sorted(selected_rows)

        # Build text from selected rows (timestamp + category + message)
        lines = []
        for row in sorted_rows:
            row_parts = []

            # Get timestamp (column 0)
            timestamp_item = self.item(row, 0)
            if timestamp_item and timestamp_item.text():
                row_parts.append(timestamp_item.text())

            # Get category (column 1) in brackets
            category_item = self.item(row, 1)
            if category_item and category_item.text():
                row_parts.append(f"[{category_item.text()}]")

            # Get message (column 2)
            message_item = self.item(row, 2)
            if message_item:
                row_parts.append(message_item.text())

            # Join parts with space and add to lines
            if row_parts:
                lines.append(" ".join(row_parts))

        # Join all lines and copy to clipboard
        content = "\n".join(lines)
        clipboard = QApplication.clipboard()
        clipboard.setText(content)

        # Show status bar feedback
        count = len(sorted_rows)
        entry_word = "entry" if count == 1 else "entries"
        message = f"Copied {count} log {entry_word} to clipboard"

        # Find parent window with status bar
        widget = self.parent()
        while widget:
            if hasattr(widget, 'statusBar') and widget.statusBar():
                widget.statusBar().showMessage(message, 2500)
                break
            widget = widget.parent() if hasattr(widget, 'parent') else None

    def show_context_menu(self, position):
        """Show context menu with copy option"""
        selected_items = self.selectedItems()
        if not selected_items:
            return

        menu = QMenu(self)
        copy_action = menu.addAction("Copy")
        copy_action.setShortcut("Ctrl+C")

        action = menu.exec(self.mapToGlobal(position))
        if action == copy_action:
            self.copy_selected_rows()