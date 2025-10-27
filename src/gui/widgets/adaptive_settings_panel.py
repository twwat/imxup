"""
Adaptive Quick Settings Panel Widget
Dynamically adjusts button layout based on available space
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSizePolicy
)
from PyQt6.QtCore import QTimer


class AdaptiveQuickSettingsPanel(QWidget):
    """
    A widget that adapts its button layout based on available height (1, 2, or 3 rows).
    Each button independently decides whether to show text based on its own width.

    Layout System:
    - Vertical space (height) → determines NUMBER OF ROWS (1, 2, or 3)
    - Individual button width → determines TEXT vs ICON per button

    Result: 3 possible layout modes:
    - 1 row:  All 6 buttons (Settings, Credentials, Templates, Hooks, Logs, Theme)
    - 2 rows: Row 1: Settings + Theme (icon) | Row 2: Credentials, Templates, Hooks, Logs (icons only)
    - 3 rows: Row 1: Settings + Theme (icon) | Row 2: Credentials, Templates | Row 3: Hooks, Logs
    """

    # Vertical thresholds - determine NUMBER OF ROWS (1, 2, or 3)
    HEIGHT_1_ROW = 65         # px - below this, use 1 row layout
    HEIGHT_2_ROW = 97         # px - below this, use 2 rows; above = 3 rows

    # Per-button text threshold - each button checks its own width
    BUTTON_TEXT_WIDTH = 87    # px - above this width, button shows text; below = icon only

    # Qt's maximum widget size (2^24 - 1) - means "unlimited width/height"
    MAX_SIZE = 16777215

    def __init__(self, parent=None):
        super().__init__(parent)

        # Button storage
        self.settings_btn = None
        self.credentials_btn = None
        self.templates_btn = None
        self.hooks_btn = None
        self.log_viewer_btn = None
        self.theme_toggle_btn = None

        # Layout mode tracking
        self._current_mode = None
        self._num_rows = 1       # Number of rows: 1, 2, or 3

        # Main layout container
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # Button container (will be recreated on resize)
        self.button_container = None

        # Set size policy to Expanding vertically so this widget grows when parent grows
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

    def set_buttons(self, settings_btn, credentials_btn, templates_btn,
                    hooks_btn, log_viewer_btn, theme_toggle_btn):
        """
        Set the button references to manage

        Args:
            settings_btn: Comprehensive Settings button
            credentials_btn: Credentials manager button
            templates_btn: Templates manager button
            hooks_btn: Hooks configuration button
            log_viewer_btn: Log viewer button
            theme_toggle_btn: Theme toggle button
        """
        self.settings_btn = settings_btn
        self.credentials_btn = credentials_btn
        self.templates_btn = templates_btn
        self.hooks_btn = hooks_btn
        self.log_viewer_btn = log_viewer_btn
        self.theme_toggle_btn = theme_toggle_btn

        # Store original button text for restoration
        self._button_labels = {
            'settings': ' Settings',
            'credentials': ' Credentials',
            'templates': ' Templates',
            'hooks': ' Hooks',
            'log_viewer': ' Logs',
            'theme': ''  # Theme button never shows text in 2-row/3-row modes
        }

        # Initialize state based on current height
        current_height = self.height()
        if current_height < self.HEIGHT_1_ROW:
            self._num_rows = 1
        elif current_height < self.HEIGHT_2_ROW:
            self._num_rows = 2
        else:
            self._num_rows = 3

        # Initial layout
        self._update_layout(force=True)

    def resizeEvent(self, event):
        """Handle resize events to adapt layout and update button text"""
        super().resizeEvent(event)
        self._update_layout()
        # Schedule button text update after layout has settled
        QTimer.singleShot(0, self._update_button_text)

    def _update_layout(self, force=False):
        """
        Update button layout based on available height

        Args:
            force: Force layout update even if mode hasn't changed
        """
        if not self.settings_btn:
            return  # Buttons not set yet

        # Measure height to determine row count
        height = self.height()

        # Determine number of rows based on height
        if height < self.HEIGHT_1_ROW:
            self._num_rows = 1
        elif height < self.HEIGHT_2_ROW:
            self._num_rows = 2
        else:
            self._num_rows = 3

        # Create mode identifier
        target_mode = f"{self._num_rows}row"

        # Only update if mode changed or forced
        if target_mode == self._current_mode and not force:
            return

        self._current_mode = target_mode

        # Rebuild layout based on row count
        if self._num_rows == 1:
            self._build_1_row()
        elif self._num_rows == 2:
            self._build_2_row()
        else:  # 3 rows
            self._build_3_row()

    def _clear_layout(self):
        """Remove all widgets and spacers from the main layout"""
        while self.main_layout.count():
            item = self.main_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.spacerItem():
                pass

        self.button_container = None

    def _update_button_text(self):
        """Update each button's text based on its current width"""
        if not self.settings_btn:
            return

        # In 2-row and 3-row modes, theme button is always icon-only
        # In 1-row mode, all buttons check their width

        buttons_to_check = []

        if self._num_rows == 1:
            # All buttons check their width
            buttons_to_check = [
                (self.settings_btn, 'settings'),
                (self.credentials_btn, 'credentials'),
                (self.templates_btn, 'templates'),
                (self.hooks_btn, 'hooks'),
                (self.log_viewer_btn, 'log_viewer'),
                (self.theme_toggle_btn, 'theme')
            ]
        elif self._num_rows == 2:
            # Row 1: Settings checks width, Theme is icon-only
            # Row 2: All buttons are icon-only (per spec)
            buttons_to_check = [
                (self.settings_btn, 'settings'),
            ]
        elif self._num_rows == 3:
            # Row 1: Settings checks width, Theme is icon-only
            # Row 2: Credentials, Templates check width
            # Row 3: Hooks, Logs check width
            buttons_to_check = [
                (self.settings_btn, 'settings'),
                (self.credentials_btn, 'credentials'),
                (self.templates_btn, 'templates'),
                (self.hooks_btn, 'hooks'),
                (self.log_viewer_btn, 'log_viewer'),
            ]

        for btn, label_key in buttons_to_check:
            if btn:
                current_width = btn.width()
                if current_width >= self.BUTTON_TEXT_WIDTH:
                    btn.setText(self._button_labels[label_key])
                else:
                    btn.setText("")

    def _build_1_row(self):
        """Build 1 row layout: All 6 buttons in order"""
        self._clear_layout()

        # Create horizontal layout
        self.button_container = QWidget()
        self.button_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(self.button_container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # All 6 buttons in order: Settings, Credentials, Templates, Hooks, Logs, Theme
        buttons = [
            (self.settings_btn, "comprehensive-settings"),
            (self.credentials_btn, "quick-settings-btn"),
            (self.templates_btn, "quick-settings-btn"),
            (self.hooks_btn, "quick-settings-btn"),
            (self.log_viewer_btn, "quick-settings-btn"),
            (self.theme_toggle_btn, "quick-settings-btn")
        ]

        for btn, btn_class in buttons:
            if btn:
                btn.setText("")  # Start with icon-only, _update_button_text will add text if wide enough
                btn.setProperty("class", btn_class)
                btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                btn.style().unpolish(btn)
                btn.style().polish(btn)
                layout.addWidget(btn, 1)  # Equal stretch

        self.main_layout.addWidget(self.button_container)
        self.main_layout.addStretch(1)

    def _build_2_row(self):
        """Build 2 row layout
        Row 1: Settings (expanding) + Theme (icon-only, square, right)
        Row 2: Credentials, Templates, Hooks, Logs (all icon-only)
        """
        self._clear_layout()

        # Create container
        self.button_container = QWidget()
        self.button_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        main = QVBoxLayout(self.button_container)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(4)

        # First row: Settings (expanding) + Theme (icon-only, square)
        row1 = QHBoxLayout()
        row1.setSpacing(6)

        if self.settings_btn:
            self.settings_btn.setText("")  # Will be updated by _update_button_text
            self.settings_btn.setProperty("class", "comprehensive-settings")
            self.settings_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.settings_btn.style().unpolish(self.settings_btn)
            self.settings_btn.style().polish(self.settings_btn)
            row1.addWidget(self.settings_btn, 1)  # Expanding

        if self.theme_toggle_btn:
            self.theme_toggle_btn.setText("")  # Always icon-only
            self.theme_toggle_btn.setProperty("class", "quick-settings-btn")
            self.theme_toggle_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            self.theme_toggle_btn.setMinimumWidth(30)
            self.theme_toggle_btn.setMaximumWidth(40)
            self.theme_toggle_btn.style().unpolish(self.theme_toggle_btn)
            self.theme_toggle_btn.style().polish(self.theme_toggle_btn)
            row1.addWidget(self.theme_toggle_btn, 0)  # Fixed width

        main.addLayout(row1)

        # Second row: Credentials, Templates, Hooks, Logs (all icon-only per spec)
        row2 = QHBoxLayout()
        row2.setSpacing(6)

        row2_buttons = [
            self.credentials_btn,
            self.templates_btn,
            self.hooks_btn,
            self.log_viewer_btn
        ]

        for btn in row2_buttons:
            if btn:
                btn.setText("")  # Icon-only
                btn.setProperty("class", "quick-settings-btn")
                btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                btn.style().unpolish(btn)
                btn.style().polish(btn)
                row2.addWidget(btn, 1)

        main.addLayout(row2)

        self.main_layout.addWidget(self.button_container)
        self.main_layout.addStretch(1)

    def _build_3_row(self):
        """Build 3 row layout
        Row 1: Settings (expanding) + Theme (icon-only, square, right)
        Row 2: Credentials, Templates (each checks own width for text)
        Row 3: Hooks, Logs (each checks own width for text)
        """
        self._clear_layout()

        # Create container
        self.button_container = QWidget()
        self.button_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        main = QVBoxLayout(self.button_container)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(4)

        # First row: Settings (expanding) + Theme (icon-only, square)
        row1 = QHBoxLayout()
        row1.setSpacing(6)

        if self.settings_btn:
            self.settings_btn.setText("")  # Will be updated by _update_button_text
            self.settings_btn.setProperty("class", "comprehensive-settings")
            self.settings_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.settings_btn.style().unpolish(self.settings_btn)
            self.settings_btn.style().polish(self.settings_btn)
            row1.addWidget(self.settings_btn, 1)  # Expanding

        if self.theme_toggle_btn:
            self.theme_toggle_btn.setText("")  # Always icon-only
            self.theme_toggle_btn.setProperty("class", "quick-settings-btn")
            self.theme_toggle_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            self.theme_toggle_btn.setMinimumWidth(30)
            self.theme_toggle_btn.setMaximumWidth(40)
            self.theme_toggle_btn.style().unpolish(self.theme_toggle_btn)
            self.theme_toggle_btn.style().polish(self.theme_toggle_btn)
            row1.addWidget(self.theme_toggle_btn, 0)  # Fixed width

        main.addLayout(row1)

        # Second row: Credentials, Templates (equal width, check own width for text)
        row2 = QHBoxLayout()
        row2.setSpacing(6)

        row2_buttons = [
            self.credentials_btn,
            self.templates_btn
        ]

        for btn in row2_buttons:
            if btn:
                btn.setText("")  # Will be updated by _update_button_text
                btn.setProperty("class", "quick-settings-btn")
                btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                btn.style().unpolish(btn)
                btn.style().polish(btn)
                row2.addWidget(btn, 1)

        main.addLayout(row2)

        # Third row: Hooks, Logs (equal width, check own width for text)
        row3 = QHBoxLayout()
        row3.setSpacing(6)

        row3_buttons = [
            self.hooks_btn,
            self.log_viewer_btn
        ]

        for btn in row3_buttons:
            if btn:
                btn.setText("")  # Will be updated by _update_button_text
                btn.setProperty("class", "quick-settings-btn")
                btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                btn.style().unpolish(btn)
                btn.style().polish(btn)
                row3.addWidget(btn, 1)

        main.addLayout(row3)

        self.main_layout.addWidget(self.button_container)
        self.main_layout.addStretch(1)

    def get_current_mode(self):
        """Return current layout mode (e.g., '1row', '2row', '3row')"""
        return self._current_mode
