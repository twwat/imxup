"""
Custom widget classes for ImxUp application.
Provides specialized UI components.
"""

import os
from typing import Optional, List, Dict, Any
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QProgressBar,
    QLabel, QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QStyle, QMenu, QMessageBox, QTabBar
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QMimeData, QPoint
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QDragEnterEvent, QDropEvent

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
    """Widget containing action buttons for table rows"""
    
    # Signals
    start_clicked = pyqtSignal(str)
    pause_clicked = pyqtSignal(str)
    stop_clicked = pyqtSignal(str)
    remove_clicked = pyqtSignal(str)
    view_clicked = pyqtSignal(str)
    
    def __init__(self, gallery_path: str, parent=None):
        super().__init__(parent)
        self.gallery_path = gallery_path
        self.current_state = QUEUE_STATE_READY
        self.setup_ui()
    
    def setup_ui(self):
        """Initialize the UI"""
        layout = QHBoxLayout()
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        
        # Start/Resume button
        self.start_btn = QPushButton()
        self.start_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.start_btn.setToolTip("Start Upload")
        self.start_btn.setMaximumWidth(30)
        self.start_btn.clicked.connect(lambda: self.start_clicked.emit(self.gallery_path))
        
        # Pause button
        self.pause_btn = QPushButton()
        self.pause_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause))
        self.pause_btn.setToolTip("Pause Upload")
        self.pause_btn.setMaximumWidth(30)
        self.pause_btn.setEnabled(False)
        self.pause_btn.clicked.connect(lambda: self.pause_clicked.emit(self.gallery_path))
        
        # Stop button
        self.stop_btn = QPushButton()
        self.stop_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaStop))
        self.stop_btn.setToolTip("Stop Upload")
        self.stop_btn.setMaximumWidth(30)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(lambda: self.stop_clicked.emit(self.gallery_path))
        
        # Remove button
        self.remove_btn = QPushButton()
        self.remove_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon))
        self.remove_btn.setToolTip("Remove from Queue")
        self.remove_btn.setMaximumWidth(30)
        self.remove_btn.clicked.connect(lambda: self.remove_clicked.emit(self.gallery_path))
        
        # View button
        self.view_btn = QPushButton()
        self.view_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView))
        self.view_btn.setToolTip("View Details")
        self.view_btn.setMaximumWidth(30)
        self.view_btn.clicked.connect(lambda: self.view_clicked.emit(self.gallery_path))
        
        layout.addWidget(self.start_btn)
        layout.addWidget(self.pause_btn)
        layout.addWidget(self.stop_btn)
        layout.addWidget(self.remove_btn)
        layout.addWidget(self.view_btn)
        layout.addStretch()
        
        self.setLayout(layout)
    
    def update_state(self, state: str):
        """Update button states based on gallery state"""
        self.current_state = state
        
        if state == QUEUE_STATE_READY:
            self.start_btn.setEnabled(True)
            self.pause_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)
            self.remove_btn.setEnabled(True)
            
        elif state == QUEUE_STATE_QUEUED:
            self.start_btn.setEnabled(False)
            self.pause_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.remove_btn.setEnabled(False)
            
        elif state == QUEUE_STATE_UPLOADING:
            self.start_btn.setEnabled(False)
            self.pause_btn.setEnabled(True)
            self.stop_btn.setEnabled(True)
            self.remove_btn.setEnabled(False)
            
        elif state == QUEUE_STATE_PAUSED:
            self.start_btn.setEnabled(True)
            self.start_btn.setToolTip("Resume Upload")
            self.pause_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.remove_btn.setEnabled(True)
            
        elif state in [QUEUE_STATE_COMPLETED, QUEUE_STATE_FAILED]:
            self.start_btn.setEnabled(False)
            self.pause_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)
            self.remove_btn.setEnabled(True)
            
        elif state == QUEUE_STATE_INCOMPLETE:
            self.start_btn.setEnabled(True)
            self.start_btn.setToolTip("Retry Upload")
            self.pause_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)
            self.remove_btn.setEnabled(True)


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
        actions_widget = ActionButtonWidget(gallery_data.get('path', ''))
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