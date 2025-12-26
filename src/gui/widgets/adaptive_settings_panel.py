"""
Adaptive Quick Settings Panel Widget
Dynamically adjusts button layout based on available space
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSizePolicy
)
from PyQt6.QtCore import QTimer, QSize


class AdaptiveQuickSettingsPanel(QWidget):
    """
    A widget that adapts its button layout based on available height (2, 3, or 4 rows).
    Each button independently decides whether to show text based on its own width.

    Layout System:
    - Vertical space (height) → determines NUMBER OF ROWS (2, 3, or 4)
    - Individual button width → determines TEXT vs ICON per button

    Result: 3 possible layout modes:
    - 2 rows: Row 1: Settings + Theme (icon) | Row 2: Credentials, Templates, File Hosts, Hooks, Logs, Help (icons only)
    - 3 rows: Row 1: Settings + Theme (icon) | Row 2: Credentials, Templates, File Hosts | Row 3: Hooks, Logs, Help
    - 4 rows: Row 1: Settings + Theme (icon) | Row 2: Credentials, Templates | Row 3: File Hosts, Hooks | Row 4: Logs, Help
    """

    # Vertical thresholds - determine NUMBER OF ROWS (2, 3, or 4)
    HEIGHT_2_ROW = 100        # px - below this, use 2 row layout
    HEIGHT_3_ROW = 140        # px - below this, use 3 rows
    HEIGHT_4_ROW = 180        # px - at or above this, use 4 rows
    MIN_HEIGHT = 110          # px - minimum height (2-row layout with safety margin)

    # Per-button text threshold - each button checks its own width
    BUTTON_TEXT_WIDTH = 92    # px - above this width, button shows text; below = icon only

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
        self.help_btn = None
        self.theme_toggle_btn = None

        # Layout mode tracking
        self._current_mode = None
        self._num_rows = 2       # Number of rows: 2, 3, or 4 (minimum 2)

        # Main layout container
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # Button container (will be recreated on resize)
        self.button_container = None

        self._icons_only_mode = False  # Override adaptive text when True

        # Set size policy to Expanding vertically so this widget grows when parent grows
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

    def _calculate_num_rows(self, height: int) -> int:
        """Calculate number of rows based on available height."""
        if height < self.HEIGHT_2_ROW:
            return 2
        elif height < self.HEIGHT_3_ROW:
            return 3
        elif height < self.HEIGHT_4_ROW:
            return 4
        return 4

    def minimumSizeHint(self):
        """
        Return minimum size needed for smallest layout (2-row mode).

        Always returns 2-row minimum so the panel can shrink freely
        between all layout modes without getting trapped.
        """
        return QSize(0, self.MIN_HEIGHT)

    def set_buttons(self, settings_btn, credentials_btn, templates_btn, file_hosts_btn,
                    hooks_btn, log_viewer_btn, help_btn, theme_toggle_btn):
        """
        Set the button references to manage

        Args:
            settings_btn: Comprehensive Settings button
            credentials_btn: Credentials manager button
            templates_btn: Templates manager button
            file_hosts_btn: File Hosts manager button
            hooks_btn: Hooks configuration button
            log_viewer_btn: Log viewer button
            help_btn: Help/documentation button
            theme_toggle_btn: Theme toggle button
        """
        self.settings_btn = settings_btn
        self.credentials_btn = credentials_btn
        self.templates_btn = templates_btn
        self.file_hosts_btn = file_hosts_btn
        self.hooks_btn = hooks_btn
        self.log_viewer_btn = log_viewer_btn
        self.help_btn = help_btn
        self.theme_toggle_btn = theme_toggle_btn

        # Store original button text for restoration
        self._button_labels = {
            'settings': ' Settings',
            'credentials': ' Credentials',
            'templates': ' Templates',
            'file_hosts': ' File Hosts',
            'hooks': ' App Hooks',
            'log_viewer': ' View Logs',
            'help': ' Help',
            'theme': ''  # Theme button never shows text in 2-row/3-row/4-row modes
        }

        # Initialize state based on current height
        self._num_rows = self._calculate_num_rows(self.height())

        # Initial layout
        self._update_layout(force=True)

    def set_icons_only_mode(self, enabled: bool):
        """
        Enable/disable icons-only mode

        Args:
            enabled: If True, all buttons show icons only regardless of width
        """
        self._icons_only_mode = enabled
        self._update_button_text()  # Re-evaluate all button text

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
        self._num_rows = self._calculate_num_rows(self.height())

        # Create mode identifier
        target_mode = f"{self._num_rows}row"

        # Only update if mode changed or forced
        if target_mode == self._current_mode and not force:
            return

        self._current_mode = target_mode

        # Rebuild layout based on row count
        if self._num_rows == 2:
            self._build_2_row()
        elif self._num_rows == 3:
            self._build_3_row()
        else:  # 4 rows
            self._build_4_row()

        # Notify Qt that our size constraints have changed
        # This forces QSplitter to re-query minimumSizeHint()
        self.updateGeometry()

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

        # In 2-row, 3-row, and 4-row modes, theme button is always icon-only
        # Other buttons check their width to determine text vs icon-only

        buttons_to_check = []

        if self._num_rows == 2:
            # Row 1: Settings checks width, Theme is icon-only
            # Row 2: All buttons are icon-only (per spec)
            buttons_to_check = [
                (self.settings_btn, 'settings'),
            ]
        elif self._num_rows == 3:
            # Row 1: Settings checks width, Theme is icon-only
            # Row 2: Credentials, Templates, File Hosts check width
            # Row 3: Hooks, Logs, Help check width
            buttons_to_check = [
                (self.settings_btn, 'settings'),
                (self.credentials_btn, 'credentials'),
                (self.templates_btn, 'templates'),
                (self.file_hosts_btn, 'file_hosts'),
                (self.hooks_btn, 'hooks'),
                (self.log_viewer_btn, 'log_viewer'),
                (self.help_btn, 'help'),
            ]
        elif self._num_rows == 4:
            # Row 1: Settings checks width, Theme is icon-only
            # Row 2: Credentials, Templates check width
            # Row 3: File Hosts, Hooks check width
            # Row 4: Logs, Help check width
            buttons_to_check = [
                (self.settings_btn, 'settings'),
                (self.credentials_btn, 'credentials'),
                (self.templates_btn, 'templates'),
                (self.file_hosts_btn, 'file_hosts'),
                (self.hooks_btn, 'hooks'),
                (self.log_viewer_btn, 'log_viewer'),
                (self.help_btn, 'help'),
            ]

        for btn, label_key in buttons_to_check:
            if btn:
                # If icons-only mode is enabled, always hide text
                if self._icons_only_mode:
                    btn.setText("")
                else:
                    # Normal adaptive behavior based on width
                    current_width = btn.width()
                    if current_width >= self.BUTTON_TEXT_WIDTH:
                        btn.setText(self._button_labels[label_key])
                    else:
                        btn.setText("")

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

        # Second row: Credentials, Templates, File Hosts, Hooks, Logs, Help (all icon-only per spec)
        row2 = QHBoxLayout()
        row2.setSpacing(6)

        row2_buttons = [
            self.credentials_btn,
            self.templates_btn,
            self.file_hosts_btn,
            self.hooks_btn,
            self.log_viewer_btn,
            self.help_btn
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

        # Second row: Credentials, Templates, File Hosts (equal width, check own width for text)
        row2 = QHBoxLayout()
        row2.setSpacing(6)

        row2_buttons = [
            self.credentials_btn,
            self.templates_btn,
            self.file_hosts_btn
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

        # Third row: Hooks, Logs, Help (equal width, check own width for text)
        row3 = QHBoxLayout()
        row3.setSpacing(6)

        row3_buttons = [
            self.hooks_btn,
            self.log_viewer_btn,
            self.help_btn
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

    def _build_4_row(self):
        """Build 4 row layout
        Row 1: Settings (expanding) + Theme (icon-only, square, right)
        Row 2: Credentials, Templates (equal width, check own width for text)
        Row 3: File Hosts, Hooks (equal width, check own width for text)
        Row 4: Logs, Help (equal width, check own width for text)
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

        # Third row: File Hosts, Hooks (equal width, check own width for text)
        row3 = QHBoxLayout()
        row3.setSpacing(6)

        row3_buttons = [
            self.file_hosts_btn,
            self.hooks_btn
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

        # Fourth row: Logs, Help (equal width, check own width for text)
        row4 = QHBoxLayout()
        row4.setSpacing(6)

        row4_buttons = [
            self.log_viewer_btn,
            self.help_btn
        ]

        for btn in row4_buttons:
            if btn:
                btn.setText("")  # Will be updated by _update_button_text
                btn.setProperty("class", "quick-settings-btn")
                btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                btn.style().unpolish(btn)
                btn.style().polish(btn)
                row4.addWidget(btn, 1)

        main.addLayout(row4)

        self.main_layout.addWidget(self.button_container)
        self.main_layout.addStretch(1)

    def get_current_mode(self):
        """Return current layout mode (e.g., '2row', '3row', '4row')"""
        return self._current_mode
