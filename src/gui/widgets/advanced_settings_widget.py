"""Advanced settings widget for power users."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QCheckBox,
    QSpinBox, QDoubleSpinBox, QComboBox, QStyledItemDelegate,
    QStyleOptionViewItem
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor

# Schema for advanced settings
# Each setting has: key, description, default, type, and optional constraints
ADVANCED_SETTINGS = [
    {
        "key": "gui/log_font_size",
        "description": "Font size for the GUI log display",
        "default": 10,
        "type": "int",
        "min": 6,
        "max": 24
    },
    {
        "key": "uploads/retry_delay_seconds",
        "description": "Seconds to wait before retrying a failed upload",
        "default": 5,
        "type": "int",
        "min": 1,
        "max": 300
    },
    {
        "key": "scanning/skip_hidden_files",
        "description": "Skip hidden files (starting with .) when scanning folders",
        "default": True,
        "type": "bool"
    },
]


class AdvancedSettingsWidget(QWidget):
    """Widget for displaying and editing advanced settings."""

    settings_changed = pyqtSignal()  # Emitted when any setting changes

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_values = {}  # key -> current value
        self._setup_ui()
        self._load_defaults()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        # Warning header
        warning = QLabel(
            "⚠️ Advanced Settings - For experienced users only! "
            "Only change these if you understand what they do."
        )
        warning.setStyleSheet(
            "background-color: #fff3cd; color: #856404; "
            "padding: 10px; border-radius: 4px; font-weight: bold;"
        )
        warning.setWordWrap(True)
        layout.addWidget(warning)

        # Filter box
        filter_layout = QHBoxLayout()
        filter_label = QLabel("Filter:")
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Type to filter settings...")
        self.filter_edit.textChanged.connect(self._apply_filter)
        filter_layout.addWidget(filter_label)
        filter_layout.addWidget(self.filter_edit)
        layout.addLayout(filter_layout)

        # Settings table
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Key", "Description", "Value"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.table)

        self._populate_table()

    def _populate_table(self):
        """Populate the table with all advanced settings."""
        self.table.setRowCount(len(ADVANCED_SETTINGS))
        self._value_widgets = {}  # key -> widget

        for row, setting in enumerate(ADVANCED_SETTINGS):
            key = setting["key"]

            # Key column
            key_item = QTableWidgetItem(key)
            key_item.setFlags(key_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, key_item)

            # Description column
            desc_item = QTableWidgetItem(setting["description"])
            desc_item.setFlags(desc_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 1, desc_item)

            # Value column - create appropriate widget
            widget = self._create_value_widget(setting)
            self._value_widgets[key] = widget
            self.table.setCellWidget(row, 2, widget)

    def _create_value_widget(self, setting):
        """Create the appropriate widget for a setting type."""
        setting_type = setting.get("type", "str")
        key = setting["key"]
        default = setting.get("default", "")

        if setting_type == "bool":
            widget = QCheckBox()
            widget.setChecked(bool(default))
            widget.toggled.connect(lambda val, k=key: self._on_value_changed(k, val))

        elif setting_type == "int":
            widget = QSpinBox()
            widget.setMinimum(setting.get("min", 0))
            widget.setMaximum(setting.get("max", 99999))
            widget.setValue(int(default))
            widget.valueChanged.connect(lambda val, k=key: self._on_value_changed(k, val))

        elif setting_type == "float":
            widget = QDoubleSpinBox()
            widget.setMinimum(setting.get("min", 0.0))
            widget.setMaximum(setting.get("max", 99999.0))
            widget.setDecimals(setting.get("decimals", 2))
            widget.setValue(float(default))
            widget.valueChanged.connect(lambda val, k=key: self._on_value_changed(k, val))

        elif setting_type == "choice":
            widget = QComboBox()
            choices = setting.get("choices", [])
            widget.addItems(choices)
            if default in choices:
                widget.setCurrentText(str(default))
            widget.currentTextChanged.connect(lambda val, k=key: self._on_value_changed(k, val))

        else:  # Default to string
            widget = QLineEdit()
            widget.setText(str(default))
            widget.textChanged.connect(lambda val, k=key: self._on_value_changed(k, val))

        return widget

    def _on_value_changed(self, key, value):
        """Handle when a setting value changes."""
        self._current_values[key] = value
        self.settings_changed.emit()

    def _load_defaults(self):
        """Load default values into current_values."""
        for setting in ADVANCED_SETTINGS:
            self._current_values[setting["key"]] = setting.get("default", "")

    def _apply_filter(self, text):
        """Filter table rows based on search text."""
        text = text.lower()
        for row in range(self.table.rowCount()):
            key_item = self.table.item(row, 0)
            desc_item = self.table.item(row, 1)
            key_text = key_item.text().lower() if key_item else ""
            desc_text = desc_item.text().lower() if desc_item else ""

            matches = text in key_text or text in desc_text
            self.table.setRowHidden(row, not matches)

    def get_values(self) -> dict:
        """Get all current setting values."""
        return self._current_values.copy()

    def get_non_default_values(self) -> dict:
        """Get only values that differ from defaults."""
        result = {}
        for setting in ADVANCED_SETTINGS:
            key = setting["key"]
            default = setting.get("default", "")
            current = self._current_values.get(key)
            if current != default:
                result[key] = current
        return result

    def set_values(self, values: dict):
        """Set values from a dictionary (e.g., loaded from INI)."""
        for key, value in values.items():
            if key in self._value_widgets:
                self._current_values[key] = value
                widget = self._value_widgets[key]

                # Find the setting schema for type info
                setting = next((s for s in ADVANCED_SETTINGS if s["key"] == key), None)
                if not setting:
                    continue

                setting_type = setting.get("type", "str")

                # Block signals to avoid triggering settings_changed
                widget.blockSignals(True)

                try:
                    if setting_type == "bool":
                        widget.setChecked(bool(value) if not isinstance(value, str) else value.lower() == 'true')
                    elif setting_type == "int":
                        widget.setValue(int(value))
                    elif setting_type == "float":
                        widget.setValue(float(value))
                    elif setting_type == "choice":
                        widget.setCurrentText(str(value))
                    else:
                        widget.setText(str(value))
                except (ValueError, TypeError):
                    # Invalid value, keep widget at current/default value
                    pass

                widget.blockSignals(False)

    def reset_to_defaults(self):
        """Reset all settings to their default values."""
        defaults = {s["key"]: s.get("default", "") for s in ADVANCED_SETTINGS}
        self.set_values(defaults)
        self._current_values = defaults.copy()
        self.settings_changed.emit()
