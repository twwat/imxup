#!/usr/bin/env python3
"""
Dialog for managing unrenamed galleries (galleries still titled "untitled gallery" on imx.to)
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
    QPushButton, QDialogButtonBox, QAbstractItemView, QHeaderView, QMessageBox, QApplication
)
from PyQt6.QtCore import Qt, pyqtSignal


class UnrenamedGalleriesDialog(QDialog):
    """Dialog to display and manage unrenamed galleries"""

    # Signal emitted when galleries are removed (to update main window count)
    galleries_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Unrenamed Galleries")
        self.setModal(True)
        self.resize(600, 400)
        self._center_on_parent()

        # Main layout
        layout = QVBoxLayout(self)

        # Info label at top
        info_text = (
            "<b>Unrenamed Galleries</b><br>"
            "These are galleries that were uploaded but remain titled \"untitled gallery\" on imx.to.<br>"
            "Common causes: No credentials, incorrect credentials, or blocked by DDoS-Guard."
        )
        info_label = QLabel(info_text)
        info_label.setWordWrap(True)
        info_label.setProperty("class", "info-panel-highlight")
        layout.addWidget(info_label)

        # Table widget
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Gallery ID", "Intended Name"])

        # Table settings
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

        # Adjust column widths
        header = self.table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)

        layout.addWidget(self.table)

        # Button layout
        button_layout = QHBoxLayout()

        # Action buttons
        self.remove_selected_btn = QPushButton("Remove Selected")
        self.remove_selected_btn.clicked.connect(self.remove_selected)
        button_layout.addWidget(self.remove_selected_btn)

        self.clear_all_btn = QPushButton("Clear All")
        self.clear_all_btn.clicked.connect(self.clear_all)
        button_layout.addWidget(self.clear_all_btn)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.load_galleries)
        button_layout.addWidget(self.refresh_btn)

        button_layout.addStretch()

        # Close button
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.accept)
        button_layout.addWidget(self.close_btn)

        layout.addLayout(button_layout)

        # Load data
        self.load_galleries()

    def load_galleries(self):
        """Load unrenamed galleries into the table"""
        try:
            from imxup import get_unnamed_galleries
            unnamed = get_unnamed_galleries()

            # Clear existing rows
            self.table.setRowCount(0)

            # Add galleries to table
            for gallery_id, intended_name in unnamed.items():
                row = self.table.rowCount()
                self.table.insertRow(row)

                # Gallery ID column
                id_item = QTableWidgetItem(gallery_id)
                id_item.setFlags(id_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, 0, id_item)

                # Intended Name column
                name_item = QTableWidgetItem(intended_name)
                name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, 1, name_item)

            # Update button states
            has_items = self.table.rowCount() > 0
            self.remove_selected_btn.setEnabled(has_items)
            self.clear_all_btn.setEnabled(has_items)

        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to load galleries: {str(e)}")

    def remove_selected(self):
        """Remove selected galleries from the unnamed list"""
        selected_rows = set()
        for item in self.table.selectedItems():
            selected_rows.add(item.row())

        if not selected_rows:
            QMessageBox.information(self, "No Selection", "Please select galleries to remove.")
            return

        # Confirm removal
        count = len(selected_rows)
        reply = QMessageBox.question(
            self, "Confirm Removal",
            f"Remove {count} selected gallery{'ies' if count > 1 else 'y'} from the unrenamed list?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            try:
                from imxup import remove_unnamed_gallery

                # Collect gallery IDs before removal
                gallery_ids = []
                for row in selected_rows:
                    gallery_id = self.table.item(row, 0).text()
                    gallery_ids.append(gallery_id)

                # Remove each gallery
                removed_count = 0
                for gallery_id in gallery_ids:
                    if remove_unnamed_gallery(gallery_id):
                        removed_count += 1

                # Reload table
                self.load_galleries()

                # Emit signal to update main window
                self.galleries_changed.emit()

                # Show result
                if removed_count > 0:
                    QMessageBox.information(
                        self, "Success",
                        f"Removed {removed_count} gallery{'ies' if removed_count > 1 else 'y'} from the unrenamed list."
                    )

            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to remove galleries: {str(e)}")

    def clear_all(self):
        """Clear all unrenamed galleries"""
        if self.table.rowCount() == 0:
            return

        # Confirm clearing all
        reply = QMessageBox.question(
            self, "Confirm Clear All",
            f"Remove all {self.table.rowCount()} galleries from the unrenamed list?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            try:
                from imxup import get_config_path
                from src.storage.database import QueueStore

                # Get database instance
                store = QueueStore(get_config_path())
                removed_count = store.clear_unnamed_galleries()

                # Reload table
                self.load_galleries()

                # Emit signal to update main window
                self.galleries_changed.emit()

                # Show result
                QMessageBox.information(
                    self, "Success",
                    f"Cleared {removed_count} gallery{'ies' if removed_count != 1 else 'y'} from the unrenamed list."
                )

            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to clear galleries: {str(e)}")
    def _center_on_parent(self):
        """Center dialog on parent window or screen"""
        if self.parent():
            # Center on parent window
            parent_geo = self.parent().geometry()
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
