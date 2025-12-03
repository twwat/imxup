"""
Custom widget classes for ImxUp application.
Provides specialized UI components.
"""

import os
from pathlib import Path
from typing import Optional, List, Dict, Any
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QProgressBar,
    QLabel, QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QStyle, QMenu, QMessageBox, QTabBar, QListWidget, QApplication,
    QAbstractItemView
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QMimeData, QPoint, QSize
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QPen, QDragEnterEvent, QDropEvent, QKeyEvent

from src.core.constants import (
    QUEUE_STATE_READY, QUEUE_STATE_QUEUED, QUEUE_STATE_UPLOADING,
    QUEUE_STATE_COMPLETED, QUEUE_STATE_FAILED, QUEUE_STATE_PAUSED,
    QUEUE_STATE_INCOMPLETE, ICON_SIZE, TABLE_UPDATE_INTERVAL
)
from src.utils.logger import log


class OverallProgressWidget(QWidget):
    """Custom progress bar widget for overall progress with label overlay"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        """Initialize the UI with progress bar and text label overlay"""
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        # Progress bar (text disabled, we'll use label instead)
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setProperty("class", "overall-progress")

        # Text label overlay - parent it to the progress bar so it overlays properly
        self.text_label = QLabel("Ready", self.progress_bar)
        self.text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.text_label.setProperty("class", "progress-text-large")  # Different class for larger font
        self.text_label.setGeometry(0, 0, 100, 25)

        layout.addWidget(self.progress_bar)
        self.setLayout(layout)

    def resizeEvent(self, event):
        """Update label size when widget is resized"""
        super().resizeEvent(event)
        if hasattr(self, 'text_label') and hasattr(self, 'progress_bar'):
            self.text_label.setGeometry(0, 0, self.progress_bar.width(), self.progress_bar.height())

    def setValue(self, value: int):
        """Set progress value"""
        self.progress_bar.setValue(value)

    def setText(self, text: str):
        """Set progress text"""
        self.text_label.setText(text)

    def setProgressProperty(self, name: str, value) -> None:
        """Set property on progress bar"""
        self.progress_bar.setProperty(name, value)
        if name == "status":
            style = self.progress_bar.style()
            if style is not None:
                style.polish(self.progress_bar)


class TableProgressWidget(QWidget):
    """Custom progress bar widget for table cells with label overlay for text positioning control"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.progress = 0
        self.status_text = ""
        self.setup_ui()

    def setup_ui(self):
        """Initialize the UI with progress bar and text label overlay"""
        # Main layout
        layout = QVBoxLayout()
        layout.setContentsMargins(2, 2, 2, 2)

        # Progress bar (text disabled, we'll use label instead)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setProperty("class", "table-progress")
        self.progress_bar.setMinimumHeight(15)

        # Text label overlay - parent it to the progress bar so it overlays properly
        self.text_label = QLabel("0%", self.progress_bar)
        self.text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.text_label.setProperty("class", "progress-text")
        # Don't set color inline - let styles.qss handle theme-aware colors

        # Initially size the label to match progress bar (will update in resizeEvent)
        self.text_label.setGeometry(0, 0, 100, 15)

        layout.addWidget(self.progress_bar)
        self.setLayout(layout)

    def resizeEvent(self, event):
        """Update label size when widget is resized"""
        super().resizeEvent(event)
        # Make label match progress bar size exactly
        if hasattr(self, 'text_label') and hasattr(self, 'progress_bar'):
            self.text_label.setGeometry(0, 0, self.progress_bar.width(), self.progress_bar.height())
    
    def set_progress(self, value: int, text: str = ""):
        """Set progress value and optional text"""
        self.progress = value
        self.status_text = text
        self.progress_bar.setValue(value)

        # Update label text instead of progress bar format
        if text:
            self.text_label.setText(f"{text} - {value}%")
        else:
            self.text_label.setText(f"{value}%")
    
    def get_progress(self) -> int:
        """Get current progress value"""
        return self.progress
    
    def update_progress(self, value: int, status: str = ""):
        """Update progress value with status-based styling"""
        self.progress_bar.setValue(value)

        # Update label text
        self.text_label.setText(f"{value}%")

        # Set CSS class-like properties for theme-based styling via styles.qss
        self.progress_bar.setProperty("status", status)

        # Force style update to apply new property
        style = self.progress_bar.style()
        if style is not None:
            style.polish(self.progress_bar)


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
        if style is None:
            return

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
    
    def dragEnterEvent(self, event: QDragEnterEvent | None) -> None:
        """Handle drag enter event"""
        if event is None:
            return
        mime_data = event.mimeData()
        if mime_data is not None and mime_data.hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        """Handle drag move event"""
        if event is None:
            return
        mime_data = event.mimeData()
        if mime_data is not None and mime_data.hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent | None) -> None:
        """Handle drop event"""
        if event is None:
            return
        mime_data = event.mimeData()
        if mime_data is None or not mime_data.hasUrls():
            return

        # Determine which tab the drop occurred on
        drop_pos = event.position().toPoint()
        tab_index = self.tabAt(drop_pos)

        if tab_index == -1:
            # Dropped outside any tab, use current tab
            tab_index = self.currentIndex()

        # Extract folder paths
        folders = []
        for url in mime_data.urls():
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
        actions_widget.update_buttons(gallery_data.get('status', QUEUE_STATE_READY))
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
            actions_widget.update_buttons(gallery_data.get('status', QUEUE_STATE_READY))
    
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
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

    def keyPressEvent(self, event: QKeyEvent | None) -> None:
        """Handle Ctrl+C to copy selected log entries"""
        if event is None:
            return
        if event.key() == Qt.Key.Key_C and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            self.copy_selected_items()
        else:
            super().keyPressEvent(event)

    def copy_selected_items(self):
        """Copy selected log entries to clipboard"""
        selected_items = self.selectedItems()
        if not selected_items:
            return

        # Sort by row index to ensure consistent order
        sorted_items = sorted(selected_items, key=lambda item: self.row(item))
        texts = [item.text() for item in sorted_items]
        # Reverse to get chronological order (display is reverse chronological)
        texts = list(reversed(texts))

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

    def keyPressEvent(self, event: QKeyEvent | None) -> None:
        """Handle Ctrl+C to copy selected log entries"""
        if event is None:
            return
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

        # Sort rows and reverse for chronological order (display is newest-first)
        sorted_rows = sorted(selected_rows, reverse=True)

        # Build text from selected rows (timestamp + level + category + message)
        lines = []
        for row in sorted_rows:
            # Get timestamp (column 0)
            timestamp_item = self.item(row, 0)
            timestamp = timestamp_item.text() if timestamp_item else ""

            # Get level (column 1)
            level_item = self.item(row, 1)
            level = level_item.text() if level_item else ""

            # Get category (column 2)
            category_item = self.item(row, 2)
            category = category_item.text() if category_item else ""

            # Get message (column 3)
            message_item = self.item(row, 3)
            message = message_item.text() if message_item else ""

            # Format: "2025-11-20 00:49:47 DEBUG [template]: Message text"
            if timestamp or level or category or message:
                line = f"{timestamp} {level} [{category}]: {message}"
                lines.append(line)

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


class FileHostsStatusWidget(QWidget):
    """Widget showing file host upload status icons for a gallery"""

    # Signal emitted when a host icon is clicked
    host_clicked = pyqtSignal(str, str)  # gallery_path, host_name

    def __init__(self, gallery_path: str, parent=None):
        super().__init__(parent)
        self.gallery_path = gallery_path
        self.host_buttons: dict[str, QPushButton] = {}  # {host_name: QPushButton}

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 1, 4, 1)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.setLayout(layout)

        # Will be populated by update_hosts()
        self._initialized = False

    def update_hosts(self, host_uploads: Dict[str, Dict[str, Any]]):
        """Update host status icons - OPTIMIZED to reuse existing widgets.

        Args:
            host_uploads: Dict of {host_name: upload_data}
        """
        from src.core.file_host_config import get_config_manager
        from src.gui.icon_manager import get_icon_manager

        config_manager = get_config_manager()
        icon_manager = get_icon_manager()

        layout = self.layout()
        if layout is None:
            return

        if icon_manager is None:
            return

        # Get all enabled hosts
        enabled_hosts = config_manager.get_enabled_hosts()

        # Also include hosts that have uploads (even if now disabled)
        all_hosts_to_show = set(enabled_hosts.keys())
        all_hosts_to_show.update(host_uploads.keys())
        sorted_hosts = sorted(all_hosts_to_show)

        # OPTIMIZATION: Reuse existing buttons instead of deleting/recreating
        if self._initialized:
            existing_hosts = set(self.host_buttons.keys())

            # Remove buttons ONLY for hosts that are no longer needed
            hosts_to_remove = existing_hosts - all_hosts_to_show
            for host_name in hosts_to_remove:
                btn = self.host_buttons.pop(host_name)
                layout.removeWidget(btn)
                btn.deleteLater()

        # Update or create buttons
        for idx, host_name in enumerate(sorted_hosts):
            # Get host config
            host_config = config_manager.get_host(host_name)
            if not host_config:
                continue

            # Get upload status
            upload = host_uploads.get(host_name, {})
            has_upload = bool(upload)
            status = upload.get('status', 'not_uploaded')

            # Calculate tooltip based on upload state
            if has_upload:
                if status == 'completed':
                    tooltip = f"{host_config.name}: Click to view download link"
                else:
                    tooltip = f"{host_config.name}: {status}"
            else:
                tooltip = f"{host_config.name}: Click to upload"

            # Load host icon - use -dim variant for not_uploaded status
            if status == 'not_uploaded':
                host_icon_path = f"hosts/logo/{host_name}-icon-dim.png"
            else:
                host_icon_path = f"hosts/logo/{host_name}-icon.png"

            try:
                # Try to load host-specific icon
                icon_path = Path(icon_manager.assets_dir) / host_icon_path
                if icon_path.exists():
                    base_icon = QIcon(str(icon_path))
                else:
                    # Fallback to regular icon
                    if status == 'not_uploaded':
                        fallback_path = Path(icon_manager.assets_dir) / f"hosts/logo/{host_name}-icon.png"
                    else:
                        fallback_path = Path(icon_manager.assets_dir) / f"hosts/logo/{host_name}.png"

                    if fallback_path.exists():
                        base_icon = QIcon(str(fallback_path))
                    else:
                        # Final fallback to generic icon
                        base_icon = icon_manager.get_icon('action_view')
            except (OSError, IOError, ValueError) as e:
                log(f"Failed to load icon for {host_name}: {e}", level="warning", category="file_hosts")
                base_icon = icon_manager.get_icon('action_view')

            # Apply status overlay
            final_icon = self._apply_status_overlay(base_icon, status, icon_manager)

            # Reuse existing button or create new one
            if host_name in self.host_buttons:
                # REUSE existing button - just update its properties
                btn = self.host_buttons[host_name]

                # Update icon and tooltip (fast operations)
                btn.setIcon(final_icon)
                btn.setToolTip(tooltip)
            else:
                # CREATE new button only if needed
                btn = QPushButton()
                btn.setFixedSize(24, 24)
                btn.setToolTip(tooltip)
                btn.setProperty("class", "icon-btn")
                btn.setIcon(final_icon)
                btn.setIconSize(QSize(19, 19))

                # Connect click handler
                btn.clicked.connect(lambda checked, h=host_name: self.host_clicked.emit(self.gallery_path, h))

                self.host_buttons[host_name] = btn
                layout.addWidget(btn)

        # Ensure stretch is at the end
        from PyQt6.QtWidgets import QHBoxLayout
        if isinstance(layout, QHBoxLayout):
            # Remove existing stretch items
            for i in range(layout.count() - 1, -1, -1):
                item = layout.itemAt(i)
                if item and item.spacerItem():
                    layout.removeItem(item)
            # Add stretch at the end
            layout.addStretch()

        self._initialized = True
        self.update()  # Force visual refresh after icon updates

    def _apply_status_overlay(self, base_icon: QIcon, status: str, icon_manager) -> QIcon:
        """Apply status overlay to host icon.

        Args:
            base_icon: Base host icon
            status: Upload status ('not_uploaded', 'pending', 'uploading', 'completed', 'failed')
            icon_manager: IconManager instance

        Returns:
            QIcon with status overlay applied
        """
        # Get base pixmap (create copy to avoid modifying original)
        pixmap = base_icon.pixmap(QSize(24, 24)).copy()

        # Create painter for overlays
        painter = QPainter(pixmap)

        if status == 'not_uploaded':
            # No overlay - using pre-dimmed -icon-dim.png variant
            pass
        elif status == 'pending':
            # Light grey overlay for queued uploads
            painter.setOpacity(0.3)
            painter.fillRect(pixmap.rect(), QColor(128, 128, 128, 150))
        elif status == 'uploading':
            # Blue tint overlay for active uploads
            painter.setOpacity(0.3)
            painter.fillRect(pixmap.rect(), QColor(0, 120, 255, 100))
        elif status == 'completed':
            # No overlay - full color, ready to click for download link
            pass
        elif status == 'failed':
            # Red X overlay for failed uploads
            painter.setOpacity(1.0)
            painter.setPen(QPen(QColor(255, 0, 0), 3))
            painter.drawLine(4, 4, 20, 20)
            painter.drawLine(20, 4, 4, 20)

        painter.end()

        return QIcon(pixmap)


class FileHostsActionWidget(QWidget):
    """Widget with 'Manage Hosts' button for file host actions"""

    # Signal emitted when manage button is clicked
    manage_clicked = pyqtSignal(str)  # gallery_path

    def __init__(self, gallery_path: str, parent=None):
        super().__init__(parent)
        self.gallery_path = gallery_path

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 1, 4, 1)
        layout.setSpacing(3)
        layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        # Manage button
        self.manage_btn = QPushButton("Manage")
        self.manage_btn.setFixedSize(60, 22)
        self.manage_btn.setToolTip("Manage file host uploads for this gallery")
        self.manage_btn.setProperty("class", "icon-btn")
        self.manage_btn.clicked.connect(lambda: self.manage_clicked.emit(self.gallery_path))

        layout.addWidget(self.manage_btn)
        layout.addStretch()

        self.setLayout(layout)


class StorageProgressBar(QWidget):
    """Reusable storage progress bar with compact 'X.X TiB free' format.

    Matches the File Hosts settings tab display exactly:
    - Shows free space only ("9.4 TiB free")
    - Green when plenty of space (< 75% used)
    - Yellow when medium space (75-90% used)
    - Red when low space (>= 90% used)
    - Tooltip with detailed storage information

    Widget Lifecycle:
    1. Construction: __init__() creates widget and sets up UI
    2. Pre-insertion: update_storage() MUST be called BEFORE setCellWidget()
       to populate data and avoid race conditions
    3. Insertion: setCellWidget() adds widget to table (triggers geometry events)
    4. Updates: update_storage() can be called any time to refresh data
    5. Resize: Responsive text formatting adjusts to available width

    Thread Safety:
    - All methods MUST be called from the main GUI thread only
    - Use QMetaObject.invokeMethod for cross-thread updates
    """

    def __init__(self, parent=None):
        """Initialize storage progress bar widget."""
        super().__init__(parent)

        # Cache storage values for responsive text formatting
        self._total_bytes = 0
        self._left_bytes = 0
        self._left_formatted = ""  # Cache formatted string for performance

        self._setup_ui()

    def _setup_ui(self):
        """Initialize the UI with progress bar matching File Hosts tab style."""
        from PyQt6.QtWidgets import QSizePolicy

        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(0)

        # Create progress bar with exact settings from file_hosts_settings_widget.py
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimumWidth(50)
        self.progress_bar.setMaximumHeight(20)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("")
        self.progress_bar.setProperty("class", "storage-bar")
        self.progress_bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout.addWidget(self.progress_bar)

    def update_storage(self, total_bytes: int, left_bytes: int):
        """Update storage display with new values.

        Thread Safety: This method MUST be called from the main GUI thread only.
        Calling from worker threads will cause Qt assertion failures and crashes.
        Use QMetaObject.invokeMethod with Qt.ConnectionType.QueuedConnection for
        cross-thread updates.

        Args:
            total_bytes: Total storage capacity in bytes
            left_bytes: Free storage remaining in bytes
        """
        from PyQt6.QtCore import QThread
        assert QThread.currentThread() == self.thread(), \
            "update_storage() must be called from main GUI thread"
        from src.utils.format_utils import format_binary_size

        # Validate inputs
        if total_bytes <= 0:
            # Unknown storage - show empty neutral bar with no text
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("")  # Empty bar, no "Unknown" text

            # Informative tooltip explaining why storage is unavailable
            tooltip = (
                "Storage information unavailable\n\n"
                "Possible reasons:\n"
                "• Host doesn't report storage quota\n"
                "• Credentials not configured\n"
                "• Quota check not yet performed"
            )
            self.progress_bar.setToolTip(tooltip)

            # Use new "unknown" status for neutral gray styling
            self.progress_bar.setProperty("storage_status", "unknown")

            # Cache as invalid so resizeEvent doesn't try to format
            self._total_bytes = 0
            self._left_bytes = 0

            self._refresh_style()
            return

        if left_bytes < 0 or left_bytes > total_bytes:
            # Invalid data - keep current display unchanged
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Invalid storage data: left_bytes={left_bytes}, total_bytes={total_bytes}")
            return

        # Cache values for responsive text formatting during resize
        self._total_bytes = total_bytes
        self._left_bytes = left_bytes

        # Cache formatted string for performance (avoid re-formatting on resize)
        self._left_formatted = format_binary_size(left_bytes)

        # Calculate percentages
        used_bytes = total_bytes - left_bytes
        percent_used = int((used_bytes / total_bytes) * 100) if total_bytes > 0 else 0
        percent_free = 100 - percent_used

        # Format strings for tooltip
        left_formatted = self._left_formatted
        total_formatted = format_binary_size(total_bytes)
        used_formatted = format_binary_size(used_bytes)

        # Update progress bar - setValue shows FREE percentage (green when high)
        self.progress_bar.setValue(percent_free)

        # Set responsive text format based on current width
        self._update_text_format(self.width())

        # Detailed tooltip matching File Hosts tab format
        tooltip = f"Storage: {left_formatted} free / {total_formatted} total\nUsed: {used_formatted} ({percent_used}%)"
        self.progress_bar.setToolTip(tooltip)

        # Color coding based on usage (EXACT thresholds from file_hosts_settings_widget.py)
        if percent_used >= 90:
            self.progress_bar.setProperty("storage_status", "low")  # Red - critical
        elif percent_used >= 75:
            self.progress_bar.setProperty("storage_status", "medium")  # Yellow - warning
        else:
            self.progress_bar.setProperty("storage_status", "plenty")  # Green - good

        # Refresh styling to apply storage_status property
        self._refresh_style()

    def _update_text_format(self, width: int):
        """Update text format based on available width.

        Responsive tiers:
        - width >= 70px: "X.X TiB free"
        - 50px <= width < 70px: "X.X TiB" (remove "free")
        - width < 50px: "" (no text)

        Args:
            width: Current widget width in pixels
        """
        # If no valid storage data, don't update format
        if self._total_bytes <= 0:
            return

        # Use cached formatted string (set in update_storage) instead of re-formatting
        left_formatted = self._left_formatted

        if width >= 70:
            # Normal width: "X.X TiB free"
            text = f"{left_formatted} free"
        elif width >= 50:
            # Narrow width: "X.X TiB" (drop "free")
            text = left_formatted
        else:
            # Very narrow: No text (tooltip still available)
            text = ""

        self.progress_bar.setFormat(text)

    def set_unlimited(self):
        """Set storage display to unlimited/infinity mode for hosts with no storage limit.

        This displays a full green bar with an infinity symbol (∞) to indicate
        that the host has no storage quota restrictions (e.g., IMX.to).

        Thread Safety: This method MUST be called from the main GUI thread only.
        """
        from PyQt6.QtCore import QThread
        assert QThread.currentThread() == self.thread(), \
            "set_unlimited() must be called from main GUI thread"

        # Cache as unlimited state
        self._total_bytes = -1  # Special sentinel value for unlimited
        self._left_bytes = -1
        self._left_formatted = "∞"

        # Full bar (100%) to indicate maximum available space
        self.progress_bar.setValue(100)

        # Show infinity symbol - responsive to width
        self._update_unlimited_text_format(self.width())

        # Tooltip explaining unlimited storage
        self.progress_bar.setToolTip("Unlimited storage - no quota restrictions")

        # Green color to indicate "plenty" of space
        self.progress_bar.setProperty("storage_status", "plenty")

        self._refresh_style()

    def _update_unlimited_text_format(self, width: int):
        """Update text format for unlimited storage based on width.

        Args:
            width: Current widget width in pixels
        """
        if width >= 50:
            # Show infinity symbol
            self.progress_bar.setFormat("∞")
        else:
            # Very narrow: No text
            self.progress_bar.setFormat("")

    def resizeEvent(self, event):
        """Update text format when widget is resized.

        Args:
            event: QResizeEvent containing old and new sizes
        """
        super().resizeEvent(event)

        # Check if unlimited mode (sentinel value)
        if self._total_bytes == -1:
            self._update_unlimited_text_format(event.size().width())
        elif self._total_bytes > 0:
            # Normal storage mode
            self._update_text_format(event.size().width())

    def _refresh_style(self):
        """Force style refresh to apply property changes."""
        # Use update() instead of unpolish/polish for better performance
        self.progress_bar.update()