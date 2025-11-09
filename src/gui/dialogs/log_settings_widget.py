#!/usr/bin/env python3
"""
Log Settings Widget for imxup
Provides log configuration UI that can be embedded in settings dialog
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QGridLayout, QCheckBox,
    QComboBox, QSpinBox, QLabel, QPushButton
)
from PyQt6.QtCore import pyqtSignal


class LogSettingsWidget(QWidget):
    """Widget for configuring log settings"""

    settings_changed = pyqtSignal()  # Emitted when any setting changes

    def __init__(self, parent=None):
        super().__init__(parent)
        self._logger = None
        self._log_cat_widgets = {}
        self.setup_ui()
        # Don't load settings in __init__ to avoid blocking
        # Load them lazily when the tab is shown

    def setup_ui(self):
        """Setup the UI"""
        layout = QVBoxLayout(self)

        # Top buttons row
        top_buttons = QHBoxLayout()
        view_log_btn = QPushButton("Open Log Viewer")
        view_log_btn.clicked.connect(self.open_log_viewer)
        open_dir_btn = QPushButton("Open Logs Folder")
        open_dir_btn.clicked.connect(self.open_logs_folder)
        top_buttons.addWidget(view_log_btn)
        top_buttons.addWidget(open_dir_btn)
        top_buttons.addStretch()
        layout.addLayout(top_buttons)

        levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

        # Define categories for GUI Log section
        cats = [
            ("uploads", "Uploads"),
            ("auth", "Authentication"),
            ("network", "Network"),
            ("ui", "UI"),
            ("queue", "Queue"),
            ("renaming", "Renaming"),
            ("fileio", "File I/O"),
            ("db", "Database"),
            ("timing", "Timing"),
            ("general", "General"),
        ]

        # GUI Log group (moved to top)
        gui_group = QGroupBox("GUI Log")
        gui_grid = QGridLayout(gui_group)

        self.cmb_log_gui_level = QComboBox()
        self.cmb_log_gui_level.addItems(levels)
        gui_level_label = QLabel("Log level:")
        gui_level_label.setStyleSheet("font-weight: bold;")
        gui_grid.addWidget(gui_level_label, 0, 0)
        gui_grid.addWidget(self.cmb_log_gui_level, 0, 1)

        gui_upload_label = QLabel("Upload success detail:")
        gui_upload_label.setStyleSheet("font-weight: bold;")
        gui_grid.addWidget(gui_upload_label, 0, 2)
        self.cmb_log_gui_upload_mode = QComboBox()
        self.cmb_log_gui_upload_mode.addItems(["none", "file", "gallery", "both"])
        gui_grid.addWidget(self.cmb_log_gui_upload_mode, 0, 3)

        # GUI display formatting options
        self.chk_show_level_gui = QCheckBox("Show log level prefix (DEBUG:, ERROR:, etc.)")
        self.chk_show_category_gui = QCheckBox("Show category tags ([network], [uploads], etc.)")
        gui_grid.addWidget(self.chk_show_level_gui, 1, 0, 1, 2)
        gui_grid.addWidget(self.chk_show_category_gui, 1, 2, 1, 2)
        # GUI categories header
        gui_cat_label = QLabel("Categories:")
        gui_cat_label.setStyleSheet("margin-top: 10px;")
        gui_grid.addWidget(gui_cat_label, 2, 0, 1, 5)

        # GUI categories in 2 rows of 5
        for idx, (cat_key, cat_label) in enumerate(cats):
            gui_key = f"cats_gui_{cat_key}"
            chk_gui = QCheckBox(cat_label)
            row = 3 + (idx // 5)
            col = idx % 5
            gui_grid.addWidget(chk_gui, row, col)
            self._log_cat_widgets[gui_key] = chk_gui

        layout.addWidget(gui_group)

        # File Logging group (moved to bottom, categories removed)
        file_group = QGroupBox("File Logging")
        file_grid = QGridLayout(file_group)

        self.chk_log_enabled = QCheckBox("Enable file logging")
        file_grid.addWidget(self.chk_log_enabled, 0, 0, 1, 2)

        self.cmb_log_rotation = QComboBox()
        self.cmb_log_rotation.addItems(["daily", "size"])
        file_grid.addWidget(QLabel("Rotation:"), 1, 0)
        file_grid.addWidget(self.cmb_log_rotation, 1, 1)

        self.spn_log_backup = QSpinBox()
        self.spn_log_backup.setRange(0, 3650)
        file_grid.addWidget(QLabel("Backups to keep:"), 1, 2)
        file_grid.addWidget(self.spn_log_backup, 1, 3)

        self.chk_log_compress = QCheckBox("Compress rotated logs (.gz)")
        file_grid.addWidget(self.chk_log_compress, 2, 0, 1, 2)

        self.spn_log_max_bytes = QSpinBox()
        self.spn_log_max_bytes.setRange(1024, 1024 * 1024 * 1024)
        self.spn_log_max_bytes.setSingleStep(1024 * 1024)
        file_grid.addWidget(QLabel("Max size (bytes, size mode):"), 2, 2)
        file_grid.addWidget(self.spn_log_max_bytes, 2, 3)

        self.cmb_log_file_level = QComboBox()
        self.cmb_log_file_level.addItems(levels)
        level_label = QLabel("Log level:")
        level_label.setStyleSheet("font-weight: bold;")
        file_grid.addWidget(level_label, 3, 0)
        file_grid.addWidget(self.cmb_log_file_level, 3, 1)

        upload_label = QLabel("Upload success detail:")
        upload_label.setStyleSheet("font-weight: bold;")
        file_grid.addWidget(upload_label, 3, 2)
        self.cmb_log_file_upload_mode = QComboBox()
        self.cmb_log_file_upload_mode.addItems(["none", "file", "gallery", "both"])
        file_grid.addWidget(self.cmb_log_file_upload_mode, 3, 3)

        # Note: File logging categories removed since filtering is done elsewhere
        # Store empty file category widgets to maintain compatibility
        for cat_key, _ in cats:
            file_key = f"cats_file_{cat_key}"
            # Create hidden checkboxes to maintain compatibility with existing settings
            chk_file = QCheckBox()
            chk_file.setVisible(False)
            chk_file.setChecked(True)  # Default to all categories enabled
            self._log_cat_widgets[file_key] = chk_file

        layout.addWidget(file_group)
        layout.addStretch()

        # Connect all controls to emit changed signal
        self.chk_log_enabled.toggled.connect(self.settings_changed.emit)
        self.cmb_log_rotation.currentIndexChanged.connect(self.settings_changed.emit)
        self.spn_log_backup.valueChanged.connect(self.settings_changed.emit)
        self.chk_log_compress.toggled.connect(self.settings_changed.emit)
        self.spn_log_max_bytes.valueChanged.connect(self.settings_changed.emit)
        self.cmb_log_gui_level.currentIndexChanged.connect(self.settings_changed.emit)
        self.cmb_log_file_level.currentIndexChanged.connect(self.settings_changed.emit)
        self.cmb_log_gui_upload_mode.currentIndexChanged.connect(self.settings_changed.emit)
        self.cmb_log_file_upload_mode.currentIndexChanged.connect(self.settings_changed.emit)
        self.chk_show_level_gui.toggled.connect(self.settings_changed.emit)
        self.chk_show_category_gui.toggled.connect(self.settings_changed.emit)
        for widget in self._log_cat_widgets.values():
            widget.toggled.connect(self.settings_changed.emit)

    def load_settings(self):
        """Load current log settings"""
        try:
            from src.utils.logging import get_logger
            self._logger = get_logger()
            settings = self._logger.get_settings()
        except Exception:
            settings = {
                'enabled': True,
                'rotation': 'daily',
                'backup_count': 7,
                'compress': True,
                'max_bytes': 10485760,
                'level_file': 'INFO',
                'level_gui': 'INFO',
            }

        # Block signals on all widgets during loading to prevent triggering "unsaved changes"
        self.chk_log_enabled.blockSignals(True)
        self.cmb_log_rotation.blockSignals(True)
        self.spn_log_backup.blockSignals(True)
        self.chk_log_compress.blockSignals(True)
        self.spn_log_max_bytes.blockSignals(True)
        self.cmb_log_gui_level.blockSignals(True)
        self.cmb_log_file_level.blockSignals(True)
        self.cmb_log_gui_upload_mode.blockSignals(True)
        self.cmb_log_file_upload_mode.blockSignals(True)
        self.chk_show_level_gui.blockSignals(True)
        self.chk_show_category_gui.blockSignals(True)
        for widget in self._log_cat_widgets.values():
            widget.blockSignals(True)

        self.chk_log_enabled.setChecked(bool(settings.get('enabled', True)))
        try:
            idx = ["daily", "size"].index(str(settings.get('rotation', 'daily')).lower())
            self.cmb_log_rotation.setCurrentIndex(idx)
        except Exception:
            pass
        self.spn_log_backup.setValue(int(settings.get('backup_count', 7)))
        self.chk_log_compress.setChecked(bool(settings.get('compress', True)))
        self.spn_log_max_bytes.setValue(int(settings.get('max_bytes', 10485760)))

        levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        try:
            self.cmb_log_gui_level.setCurrentIndex(levels.index(str(settings.get('level_gui', 'INFO')).upper()))
        except Exception:
            pass
        try:
            self.cmb_log_file_level.setCurrentIndex(levels.index(str(settings.get('level_file', 'INFO')).upper()))
        except Exception:
            pass

        for key, widget in self._log_cat_widgets.items():
            widget.setChecked(bool(settings.get(key, True)))

        self.cmb_log_gui_upload_mode.setCurrentText(str(settings.get("upload_success_mode_gui", "gallery")))
        self.cmb_log_file_upload_mode.setCurrentText(str(settings.get("upload_success_mode_file", "gallery")))

        # Load GUI display formatting options (already normalized to bool by get_settings())
        self.chk_show_level_gui.setChecked(settings.get("show_log_level_gui", False))
        self.chk_show_category_gui.setChecked(settings.get("show_category_gui", False))
        # Re-enable signals after loading
        self.chk_log_enabled.blockSignals(False)
        self.cmb_log_rotation.blockSignals(False)
        self.spn_log_backup.blockSignals(False)
        self.chk_log_compress.blockSignals(False)
        self.spn_log_max_bytes.blockSignals(False)
        self.cmb_log_gui_level.blockSignals(False)
        self.cmb_log_file_level.blockSignals(False)
        self.cmb_log_gui_upload_mode.blockSignals(False)
        self.cmb_log_file_upload_mode.blockSignals(False)
        self.chk_show_level_gui.blockSignals(False)
        self.chk_show_category_gui.blockSignals(False)
        for widget in self._log_cat_widgets.values():
            widget.blockSignals(False)

    def save_settings(self):
        """Save log settings"""
        if not self._logger:
            return

        try:
            cat_kwargs = {}
            for key, widget in self._log_cat_widgets.items():
                cat_kwargs[key] = widget.isChecked()

            self._logger.update_settings(
                enabled=self.chk_log_enabled.isChecked(),
                rotation=self.cmb_log_rotation.currentText().lower(),
                backup_count=self.spn_log_backup.value(),
                compress=self.chk_log_compress.isChecked(),
                max_bytes=self.spn_log_max_bytes.value(),
                level_gui=self.cmb_log_gui_level.currentText(),
                level_file=self.cmb_log_file_level.currentText(),
                upload_success_mode_gui=self.cmb_log_gui_upload_mode.currentText(),
                upload_success_mode_file=self.cmb_log_file_upload_mode.currentText(),
                show_log_level_gui=self.chk_show_level_gui.isChecked(),
                show_category_gui=self.chk_show_category_gui.isChecked(),
                **cat_kwargs,
            )
        except Exception:
            pass

    def open_log_viewer(self):
        """Open the log viewer dialog"""
        try:
            from src.gui.dialogs.log_viewer import LogViewerDialog
            initial_text = self._logger.read_current_log(tail_bytes=2 * 1024 * 1024) if self._logger else ""
            dialog = LogViewerDialog(initial_text, self)
            dialog.exec()
        except Exception:
            pass

    def open_logs_folder(self):
        """Open the logs folder in file explorer"""
        try:
            import os
            from PyQt6.QtGui import QDesktopServices
            from PyQt6.QtCore import QUrl
            logs_dir = self._logger.get_logs_dir() if self._logger else None
            if logs_dir and os.path.exists(logs_dir):
                QDesktopServices.openUrl(QUrl.fromLocalFile(logs_dir))
        except Exception:
            pass
