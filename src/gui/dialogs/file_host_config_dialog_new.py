#!/usr/bin/env python3
"""
File Host Configuration Dialog
Provides credential setup, testing, and configuration for file host uploads
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QGroupBox,
    QPushButton, QLineEdit, QCheckBox, QProgressBar, QComboBox, QWidget, QListWidget, QSplitter, QSpinBox
)
from PyQt6.QtCore import QSettings, QTimer, Qt
from PyQt6.QtGui import QPixmap
from datetime import datetime
from typing import Optional
import time

from src.utils.format_utils import format_binary_size


class AsteriskPasswordEdit(QLineEdit):
    """Custom QLineEdit that shows asterisks (*) instead of password dots when masked"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_masked = True
        self._actual_text = ""
        self.textChanged.connect(self._on_text_changed)

    def _on_text_changed(self, text):
        """Track actual text separately when masked"""
        if not self._is_masked:
            self._actual_text = text

    def setText(self, text):
        """Override setText to handle initial value loading"""
        self._actual_text = text
        if self._is_masked:
            super().setText("*" * len(text))
        else:
            super().setText(text)

    def text(self):
        """Override text() to return actual text, not asterisks"""
        return self._actual_text if self._is_masked else super().text()

    def set_masked(self, masked: bool):
        """Toggle between masked (asterisks) and visible mode"""
        self._is_masked = masked
        if masked:
            # Save actual text before masking
            self._actual_text = super().text()
            super().setText("*" * len(self._actual_text))
            self.setReadOnly(True)  # Prevent editing while masked
        else:
            # Show actual text
            super().setText(self._actual_text)
            self.setReadOnly(False)  # Allow editing when visible


# Continue with rest of file content - I'll add this in parts due to length
