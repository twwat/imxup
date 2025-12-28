#!/usr/bin/env python3
"""
Update Dialog for IMXuploader

Modal dialog showing available update information with download option.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QTextEdit, QPushButton, QCheckBox, QApplication
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QDesktopServices, QFont
from PyQt6.QtCore import QUrl


class UpdateDialog(QDialog):
    """Dialog showing available update information with download option.

    Displays version comparison, release date, release notes, and provides
    options to download or skip the update.

    Args:
        parent: Parent widget.
        current_version: Currently installed version string.
        new_version: New available version string.
        release_url: URL to the release page for download.
        release_notes: Markdown/text content of release notes.
        release_date: Date string when the release was published.
    """

    def __init__(
        self,
        parent,
        current_version: str,
        new_version: str,
        release_url: str,
        release_notes: str,
        release_date: str
    ):
        super().__init__(parent)
        self._release_url = release_url
        self._setup_dialog()
        self._create_ui(current_version, new_version, release_date, release_notes)
        self._center_on_parent()

    def _setup_dialog(self):
        """Configure dialog window properties."""
        self.setWindowTitle("Update Available")
        self.setModal(True)
        self.setMinimumSize(500, 400)
        self.resize(500, 450)

    def _create_ui(
        self,
        current_version: str,
        new_version: str,
        release_date: str,
        release_notes: str
    ):
        """Create and arrange UI components.

        Args:
            current_version: Currently installed version.
            new_version: New available version.
            release_date: Release date string.
            release_notes: Release notes content.
        """
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        # Header label
        header_label = QLabel("A new version is available!")
        header_font = QFont()
        header_font.setBold(True)
        header_font.setPointSize(14)
        header_label.setFont(header_font)
        header_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(header_label)

        # Version info
        version_label = QLabel(f"Current: {current_version}  ->  New: {new_version}")
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version_font = QFont()
        version_font.setPointSize(11)
        version_label.setFont(version_font)
        layout.addWidget(version_label)

        # Release date
        date_label = QLabel(f"Released: {release_date}")
        date_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        date_label.setStyleSheet("color: gray;")
        layout.addWidget(date_label)

        # Spacing before release notes
        layout.addSpacing(10)

        # Release notes label
        notes_header = QLabel("Release Notes:")
        notes_header.setStyleSheet("font-weight: bold;")
        layout.addWidget(notes_header)

        # Release notes content (scrollable, read-only)
        self._notes_viewer = QTextEdit()
        self._notes_viewer.setReadOnly(True)
        self._notes_viewer.setPlainText(release_notes)
        self._notes_viewer.setMaximumHeight(200)
        self._notes_viewer.setMinimumHeight(150)
        layout.addWidget(self._notes_viewer)

        # Skip checkbox
        self._skip_checkbox = QCheckBox("Don't remind me about this version")
        layout.addWidget(self._skip_checkbox)

        # Spacing before buttons
        layout.addStretch()

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        remind_later_btn = QPushButton("Remind Me Later")
        remind_later_btn.clicked.connect(self._on_remind_later_clicked)
        button_layout.addWidget(remind_later_btn)

        download_btn = QPushButton("Download Update")
        download_btn.setDefault(True)
        download_btn.clicked.connect(self._on_download_clicked)
        button_layout.addWidget(download_btn)

        layout.addLayout(button_layout)

    def _on_download_clicked(self):
        """Open release URL in browser and close dialog."""
        QDesktopServices.openUrl(QUrl(self._release_url))
        self.accept()

    def _on_remind_later_clicked(self):
        """Close dialog without action."""
        self.reject()

    @property
    def skip_version(self) -> bool:
        """Return True if user checked 'Don't remind me about this version'.

        Returns:
            True if the skip checkbox is checked, False otherwise.
        """
        return self._skip_checkbox.isChecked()

    def _center_on_parent(self):
        """Center dialog on parent window or screen."""
        if self.parent():
            parent_geo = self.parent().geometry()
            self.move(
                parent_geo.x() + (parent_geo.width() - self.width()) // 2,
                parent_geo.y() + (parent_geo.height() - self.height()) // 2
            )
        else:
            screen_geo = QApplication.primaryScreen().availableGeometry()
            self.move(
                (screen_geo.width() - self.width()) // 2,
                (screen_geo.height() - self.height()) // 2
            )
