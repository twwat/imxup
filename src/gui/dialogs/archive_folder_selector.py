#!/usr/bin/env python3
"""
Archive folder selector dialog
Shows folders extracted from archive and lets user select which to add
"""

from pathlib import Path
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QDialogButtonBox
)
from PyQt6.QtCore import Qt


class ArchiveFolderSelector(QDialog):
    """Dialog for selecting folders from extracted archive"""

    def __init__(self, archive_name: str, folders: list[Path], parent=None):
        """Initialize folder selector dialog

        Args:
            archive_name: Name of the archive file
            folders: List of folder paths to choose from
            parent: Parent widget
        """
        super().__init__(parent)
        self.folders = folders
        self.selected_folders: list[Path] = []

        self.setWindowTitle(f"Select Folders - {archive_name}")
        self.setMinimumSize(600, 400)

        self._init_ui()

    def _init_ui(self):
        """Initialize the UI"""
        layout = QVBoxLayout()

        # Info label
        info_label = QLabel(
            f"Found {len(self.folders)} folder(s) with images.\n"
            "Select which folders to add to the upload queue:"
        )
        layout.addWidget(info_label)

        # Folder list
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)

        for folder in self.folders:
            item = QListWidgetItem(str(folder.name))
            item.setData(Qt.ItemDataRole.UserRole, folder)
            self.list_widget.addItem(item)

        # Select all by default
        self.list_widget.selectAll()

        layout.addWidget(self.list_widget)

        # Selection buttons
        button_layout = QHBoxLayout()
        select_all_btn = QPushButton("Select All")
        select_all_btn.clicked.connect(self.list_widget.selectAll)
        button_layout.addWidget(select_all_btn)

        clear_btn = QPushButton("Clear Selection")
        clear_btn.clicked.connect(self.list_widget.clearSelection)
        button_layout.addWidget(clear_btn)

        button_layout.addStretch()
        layout.addLayout(button_layout)

        # Dialog buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.setLayout(layout)

    def accept(self):
        """Handle dialog acceptance - save selected folders"""
        selected_items = self.list_widget.selectedItems()
        self.selected_folders = [
            item.data(Qt.ItemDataRole.UserRole) for item in selected_items
        ]
        super().accept()

    def get_selected_folders(self) -> list[Path]:
        """Get the list of selected folders

        Returns:
            List of selected folder paths
        """
        return self.selected_folders
