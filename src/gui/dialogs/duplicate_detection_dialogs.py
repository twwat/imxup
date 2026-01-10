"""
Duplicate detection dialogs for ImxUp application.
Handles two types of duplicates: previously uploaded galleries and queue duplicates.
"""

import os
from typing import List, Dict, Tuple, Any
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QScrollArea, QWidget, QFrame, QMessageBox, QApplication
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont


class PreviouslyUploadedDialog(QDialog):
    """Dialog for handling previously uploaded galleries"""
    
    def __init__(self, duplicates: List[Dict[str, Any]], parent: QWidget | None = None):
        super().__init__(parent)
        self.duplicates = duplicates
        self.selected_paths: List[str] = []
        self.checkboxes: Dict[str, QCheckBox] = {}

        self.setWindowTitle("Previously Uploaded Galleries")
        self.setModal(True)
        self.setMinimumSize(500, 400)
        self.setMaximumSize(800, 600)
        self._center_on_parent()

        self._setup_ui()
        self._connect_signals()

    def _center_on_parent(self) -> None:
        """Center dialog on parent window or screen"""
        parent_widget = self.parent()
        if parent_widget:
            # Center on parent window
            if hasattr(parent_widget, 'geometry'):
                parent_geo = parent_widget.geometry()  # type: ignore[union-attr]
                dialog_geo = self.frameGeometry()
                x = parent_geo.x() + (parent_geo.width() - dialog_geo.width()) // 2
                y = parent_geo.y() + (parent_geo.height() - dialog_geo.height()) // 2
                self.move(x, y)
        else:
            # Center on screen if no parent
            screen = QApplication.primaryScreen()
            if screen:
                screen_geo = screen.geometry()
                dialog_geo = self.frameGeometry()
                x = (screen_geo.width() - dialog_geo.width()) // 2
                y = (screen_geo.height() - dialog_geo.height()) // 2
                self.move(x, y)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Header message
        count = len(self.duplicates)
        gallery_word = "gallery" if count == 1 else "galleries"
        
        header = QLabel(f"⚠️ {count} {gallery_word} were uploaded previously")
        header_font = QFont()
        header_font.setPointSize(12)
        header_font.setBold(True)
        header.setFont(header_font)
        layout.addWidget(header)
        
        description = QLabel(
            "These folders have existing gallery files, indicating they were uploaded before.\n"
            "Select which ones you want to upload again:"
        )
        description.setWordWrap(True)
        description.setProperty("class", "dialog-description")
        layout.addWidget(description)
        
        # Scrollable list of duplicates
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setContentsMargins(10, 10, 10, 10)
        scroll_layout.setSpacing(8)
        
        # Add checkboxes for each duplicate
        for duplicate in self.duplicates:
            self._add_duplicate_item(scroll_layout, duplicate)
        
        scroll_area.setWidget(scroll_widget)
        layout.addWidget(scroll_area)
        
        # Selection controls
        selection_layout = QHBoxLayout()
        
        select_all_btn = QPushButton("Select All")
        select_all_btn.clicked.connect(self._select_all)
        selection_layout.addWidget(select_all_btn)
        
        select_none_btn = QPushButton("Select None")  
        select_none_btn.clicked.connect(self._select_none)
        selection_layout.addWidget(select_none_btn)
        
        selection_layout.addStretch()
        layout.addLayout(selection_layout)
        
        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(separator)
        
        # Dialog buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        no_btn = QPushButton("No, Skip All")
        no_btn.setProperty("class", "dialog-btn-secondary")
        no_btn.clicked.connect(self.reject)
        button_layout.addWidget(no_btn)

        yes_btn = QPushButton("Yes, Upload Selected")
        yes_btn.setProperty("class", "dialog-btn-primary")
        yes_btn.clicked.connect(self.accept)
        yes_btn.setDefault(True)
        button_layout.addWidget(yes_btn)
        
        layout.addLayout(button_layout)
    
    def _add_duplicate_item(self, layout: QVBoxLayout, duplicate: Dict):
        """Add a single duplicate item with checkbox"""
        item_widget = QWidget()
        item_layout = QHBoxLayout(item_widget)
        item_layout.setContentsMargins(5, 5, 5, 5)
        
        # Checkbox
        checkbox = QCheckBox()
        checkbox.setChecked(True)  # All selected by default
        path = duplicate['path']
        self.checkboxes[path] = checkbox
        item_layout.addWidget(checkbox)
        
        # Gallery info
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)
        
        # Gallery name
        name = duplicate.get('name', os.path.basename(path))
        name_label = QLabel(name)
        name_label.setProperty("class", "label-bold")
        info_layout.addWidget(name_label)

        # Path
        path_label = QLabel(path)
        path_label.setProperty("class", "label-path")
        path_label.setWordWrap(True)
        info_layout.addWidget(path_label)

        # Existing files info
        existing_files = duplicate.get('existing_files', [])
        if existing_files:
            files_text = f"Found: {', '.join(existing_files)}"
            files_label = QLabel(files_text)
            files_label.setProperty("class", "label-warning-hint")
            files_label.setWordWrap(True)
            info_layout.addWidget(files_label)

        item_layout.addLayout(info_layout)
        item_layout.addStretch()

        # Add subtle border
        item_widget.setProperty("class", "list-item-frame")
        
        layout.addWidget(item_widget)
    
    def _connect_signals(self):
        """Connect checkbox signals to update selection count"""
        for checkbox in self.checkboxes.values():
            checkbox.toggled.connect(self._update_button_text)
        self._update_button_text()
    
    def _select_all(self):
        """Select all checkboxes"""
        for checkbox in self.checkboxes.values():
            checkbox.setChecked(True)
    
    def _select_none(self):
        """Deselect all checkboxes"""
        for checkbox in self.checkboxes.values():
            checkbox.setChecked(False)
    
    def _update_button_text(self):
        """Update the 'Yes' button text with selection count"""
        selected_count = sum(1 for cb in self.checkboxes.values() if cb.isChecked())
        total_count = len(self.checkboxes)
        
        yes_btn = self.findChild(QPushButton, "")  # Find the Yes button
        # Update button text in all Yes buttons found
        for button in self.findChildren(QPushButton):
            if "Upload" in button.text():
                if selected_count == 0:
                    button.setText("Yes, Upload Selected (0)")
                    button.setEnabled(False)
                elif selected_count == total_count:
                    button.setText("Yes, Upload All")
                    button.setEnabled(True)
                else:
                    button.setText(f"Yes, Upload Selected ({selected_count})")
                    button.setEnabled(True)
                break
    
    def get_selected_paths(self) -> List[str]:
        """Get list of selected paths"""
        return [path for path, checkbox in self.checkboxes.items() if checkbox.isChecked()]


class QueueDuplicatesDialog(QDialog):
    """Dialog for handling items already in queue"""

    def __init__(self, duplicates: List[Dict[str, Any]], parent: QWidget | None = None):
        super().__init__(parent)
        self.duplicates = duplicates
        self.selected_paths: List[str] = []
        self.checkboxes: Dict[str, QCheckBox] = {}

        self.setWindowTitle("Already in Queue")
        self.setModal(True)
        self.setMinimumSize(500, 300)
        self.setMaximumSize(800, 500)

        self._setup_ui()
        self._connect_signals()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Header message
        count = len(self.duplicates)
        item_word = "item" if count == 1 else "items"
        
        header = QLabel(f"📋 {count} {item_word} already in queue")
        header_font = QFont()
        header_font.setPointSize(12)
        header_font.setBold(True)
        header.setFont(header_font)
        layout.addWidget(header)
        
        description = QLabel(
            "These folders are already in your upload queue.\n"
            "Select which ones you want to replace:"
        )
        description.setWordWrap(True)
        description.setProperty("class", "dialog-description")
        layout.addWidget(description)
        
        # Scrollable list of duplicates
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setContentsMargins(10, 10, 10, 10)
        scroll_layout.setSpacing(8)
        
        # Add checkboxes for each duplicate
        for duplicate in self.duplicates:
            self._add_duplicate_item(scroll_layout, duplicate)
        
        scroll_area.setWidget(scroll_widget)
        layout.addWidget(scroll_area)
        
        # Selection controls
        selection_layout = QHBoxLayout()
        
        select_all_btn = QPushButton("Select All")
        select_all_btn.clicked.connect(self._select_all)
        selection_layout.addWidget(select_all_btn)
        
        select_none_btn = QPushButton("Select None")  
        select_none_btn.clicked.connect(self._select_none)
        selection_layout.addWidget(select_none_btn)
        
        selection_layout.addStretch()
        layout.addLayout(selection_layout)
        
        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(separator)
        
        # Dialog buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        no_btn = QPushButton("No, Keep Existing")
        no_btn.setProperty("class", "dialog-btn-secondary")
        no_btn.clicked.connect(self.reject)
        button_layout.addWidget(no_btn)

        yes_btn = QPushButton("Yes, Replace Selected")
        yes_btn.setProperty("class", "dialog-btn-warning")
        yes_btn.clicked.connect(self.accept)
        yes_btn.setDefault(True)
        button_layout.addWidget(yes_btn)
        
        layout.addLayout(button_layout)
    
    def _add_duplicate_item(self, layout: QVBoxLayout, duplicate: Dict):
        """Add a single duplicate item with checkbox"""
        item_widget = QWidget()
        item_layout = QHBoxLayout(item_widget)
        item_layout.setContentsMargins(5, 5, 5, 5)
        
        # Checkbox
        checkbox = QCheckBox()
        checkbox.setChecked(True)  # All selected by default
        path = duplicate['path']
        self.checkboxes[path] = checkbox
        item_layout.addWidget(checkbox)
        
        # Gallery info
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)
        
        # Gallery name
        name = duplicate.get('name', os.path.basename(path))
        name_label = QLabel(name)
        name_label.setProperty("class", "label-bold")
        info_layout.addWidget(name_label)

        # Path
        path_label = QLabel(path)
        path_label.setProperty("class", "label-path")
        path_label.setWordWrap(True)
        info_layout.addWidget(path_label)

        # Current status
        current_status = duplicate.get('status', 'unknown')
        status_label = QLabel(f"Current status: {current_status}")
        status_label.setProperty("class", "label-info-hint")
        info_layout.addWidget(status_label)

        item_layout.addLayout(info_layout)
        item_layout.addStretch()

        # Add subtle border with different color for queue items
        item_widget.setProperty("class", "list-item-frame-info")
        
        layout.addWidget(item_widget)
    
    def _connect_signals(self):
        """Connect checkbox signals to update selection count"""
        for checkbox in self.checkboxes.values():
            checkbox.toggled.connect(self._update_button_text)
        self._update_button_text()
    
    def _select_all(self):
        """Select all checkboxes"""
        for checkbox in self.checkboxes.values():
            checkbox.setChecked(True)
    
    def _select_none(self):
        """Deselect all checkboxes"""
        for checkbox in self.checkboxes.values():
            checkbox.setChecked(False)
    
    def _update_button_text(self):
        """Update the 'Yes' button text with selection count"""
        selected_count = sum(1 for cb in self.checkboxes.values() if cb.isChecked())
        total_count = len(self.checkboxes)
        
        # Update button text in all Yes buttons found
        for button in self.findChildren(QPushButton):
            if "Replace" in button.text():
                if selected_count == 0:
                    button.setText("Yes, Replace Selected (0)")
                    button.setEnabled(False)
                elif selected_count == total_count:
                    button.setText("Yes, Replace All")
                    button.setEnabled(True)
                else:
                    button.setText(f"Yes, Replace Selected ({selected_count})")
                    button.setEnabled(True)
                break
    
    def get_selected_paths(self) -> List[str]:
        """Get list of selected paths"""
        return [path for path, checkbox in self.checkboxes.items() if checkbox.isChecked()]


def show_duplicate_detection_dialogs(
    folders_to_add: List[str], 
    check_gallery_exists_func, 
    queue_manager, 
    parent=None
) -> Tuple[List[str], List[str]]:
    """
    Show appropriate duplicate detection dialogs and return lists of folders to process.
    
    Args:
        folders_to_add: List of folder paths to add
        check_gallery_exists_func: Function to check if gallery files exist
        queue_manager: Queue manager to check for existing items
        parent: Parent widget for dialogs
        
    Returns:
        Tuple of (folders_to_add_normally, folders_to_replace_in_queue)
    """
    # Categorize the folders
    previously_uploaded = []
    already_in_queue = []
    folders_to_add_normally = []
    
    for folder_path in folders_to_add:
        folder_name = os.path.basename(folder_path)
        
        # Check if already in queue
        existing_item = queue_manager.get_item(folder_path)
        if existing_item:
            already_in_queue.append({
                'path': folder_path,
                'name': existing_item.name or folder_name,
                'status': existing_item.status
            })
            continue
        
        # Check if previously uploaded
        existing_files = check_gallery_exists_func(folder_name)
        if existing_files:
            previously_uploaded.append({
                'path': folder_path,
                'name': folder_name,
                'existing_files': existing_files
            })
            continue
        
        # No conflicts - add normally
        folders_to_add_normally.append(folder_path)
    
    # Show previously uploaded dialog if needed
    if previously_uploaded:
        prev_dialog = PreviouslyUploadedDialog(previously_uploaded, parent)
        if prev_dialog.exec() == QDialog.DialogCode.Accepted:
            selected_paths = prev_dialog.get_selected_paths()
            folders_to_add_normally.extend(selected_paths)

    # Show queue duplicates dialog if needed
    folders_to_replace_in_queue: List[str] = []
    if already_in_queue:
        queue_dialog = QueueDuplicatesDialog(already_in_queue, parent)
        if queue_dialog.exec() == QDialog.DialogCode.Accepted:
            folders_to_replace_in_queue = queue_dialog.get_selected_paths()
    
    return folders_to_add_normally, folders_to_replace_in_queue
