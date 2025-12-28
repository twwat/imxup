"""Theme management for IMXuploader GUI.

This module handles theme switching and font size management extracted from
main_window.py to improve maintainability and separation of concerns.

Handles:
    - Dark/light theme switching with QPalette and QSS
    - Font size management throughout the application
    - Stylesheet caching for performance
"""

import os
from typing import TYPE_CHECKING

from PyQt6.QtCore import QObject, QTimer
from PyQt6.QtGui import QColor, QFont, QPalette
from PyQt6.QtWidgets import QApplication

from src.utils.logger import log

if TYPE_CHECKING:
    from src.gui.main_window import ImxUploadGUI


def get_assets_dir() -> str:
    """Get the absolute path to the assets directory.

    Returns:
        str: Absolute path to project_root/assets directory
    """
    from imxup import get_project_root
    return os.path.join(get_project_root(), "assets")


class ThemeManager(QObject):
    """Manages theme and font settings for the main window.

    This manager handles all theme-related operations including:
    - Dark/light theme switching with QPalette and stylesheet
    - Font size management for table and log widgets
    - Stylesheet caching for performance

    Attributes:
        _main_window: Reference to the main ImxUploadGUI window
        _cached_base_qss: Cached base stylesheet content
        _cached_dark_qss: Cached dark theme stylesheet content
        _cached_light_qss: Cached light theme stylesheet content
    """

    def __init__(self, main_window: 'ImxUploadGUI'):
        """Initialize the ThemeManager.

        Args:
            main_window: Reference to the main ImxUploadGUI window
        """
        super().__init__()
        self._main_window = main_window
        # Cache for stylesheets
        self._cached_base_qss: str | None = None
        self._cached_dark_qss: str | None = None
        self._cached_light_qss: str | None = None

    # =========================================================================
    # Theme Toggle Methods
    # =========================================================================

    def toggle_theme(self):
        """Toggle between light and dark theme."""
        mw = self._main_window
        current_theme = mw._current_theme_mode
        new_theme = 'dark' if current_theme == 'light' else 'light'
        self.set_theme_mode(new_theme)

    def set_theme_mode(self, mode: str):
        """Switch theme mode and persist. mode in {'light','dark'}.

        Args:
            mode: Theme mode to apply ('light' or 'dark')
        """
        mw = self._main_window
        try:
            mode = mode if mode in ('light', 'dark') else 'dark'
            mw.settings.setValue('ui/theme', mode)
            mw._current_theme_mode = mode  # Update cached theme state

            self.apply_theme(mode)

            # Update tabbed gallery widget theme
            if hasattr(mw, 'gallery_table') and hasattr(mw.gallery_table, 'update_theme'):
                mw.gallery_table.update_theme()

            # Note: refresh_all_status_icons() is already called inside apply_theme()

            # Update theme toggle button tooltip
            if hasattr(mw, 'theme_toggle_btn'):
                tooltip = "Switch to light theme" if mode == 'dark' else "Switch to dark theme"
                mw.theme_toggle_btn.setToolTip(tooltip)

            # Update checked menu items if available
            if mode == 'light' and hasattr(mw, '_theme_action_light'):
                mw._theme_action_light.setChecked(True)
            elif mode == 'dark' and hasattr(mw, '_theme_action_dark'):
                mw._theme_action_dark.setChecked(True)
        except Exception as e:
            log(f"Exception in theme_manager set_theme_mode: {e}",
                level="error", category="ui")
            raise

    # =========================================================================
    # Stylesheet Loading Methods
    # =========================================================================

    def _load_base_stylesheet(self) -> str:
        """Load the base QSS stylesheet for consistent fonts and styling.

        Returns:
            str: Base QSS stylesheet content
        """
        # Cache the base stylesheet to avoid repeated disk I/O
        if self._cached_base_qss is not None:
            return self._cached_base_qss

        try:
            # Load styles.qss file from assets directory
            qss_path = os.path.join(get_assets_dir(), "styles.qss")
            if os.path.exists(qss_path):
                with open(qss_path, 'r', encoding='utf-8') as f:
                    full_content = f.read()
                    # Extract base styles (everything before LIGHT_THEME_START)
                    light_start = full_content.find('/* LIGHT_THEME_START')
                    if light_start != -1:
                        self._cached_base_qss = full_content[:light_start].strip()
                        return self._cached_base_qss
                    # Fallback: everything before DARK_THEME_START
                    dark_start = full_content.find('/* DARK_THEME_START')
                    if dark_start != -1:
                        self._cached_base_qss = full_content[:dark_start].strip()
                        return self._cached_base_qss
                    self._cached_base_qss = full_content
                    return self._cached_base_qss
        except Exception as e:
            log(f"Error loading styles.qss: {e}", level="error", category="ui")

        # Fallback: minimal inline QSS for font consistency
        fallback = """
            /* Fallback QSS for font consistency */
            QTableWidget { font-size: 8pt; }
            QTableWidget::item { font-size: 8pt; }
            QTableWidget::item:nth-column(1) { font-size: 9pt; }
            QHeaderView::section { font-size: 8pt; font-weight: bold; }
            QPushButton { font-size: 9pt; }
            QLabel { font-size: 9pt; }
        """
        self._cached_base_qss = fallback
        return fallback

    def _load_theme_styles(self, theme_type: str) -> str:
        """Load theme styles from styles.qss file.

        Args:
            theme_type: Theme type ('dark' or 'light')

        Returns:
            str: Theme-specific QSS stylesheet content
        """
        # Cache theme stylesheets to avoid repeated disk I/O
        if theme_type == 'dark' and self._cached_dark_qss is not None:
            return self._cached_dark_qss
        if theme_type == 'light' and self._cached_light_qss is not None:
            return self._cached_light_qss

        start_marker = f'/* {theme_type.upper()}_THEME_START'
        end_marker = f'/* {theme_type.upper()}_THEME_END */'

        try:
            # Load styles.qss from assets directory
            qss_path = os.path.join(get_assets_dir(), "styles.qss")
            if os.path.exists(qss_path):
                with open(qss_path, 'r', encoding='utf-8') as f:
                    full_content = f.read()
                    # Extract theme styles (between START and END markers)
                    theme_start = full_content.find(start_marker)
                    theme_end = full_content.find(end_marker)
                    if theme_start != -1 and theme_end != -1:
                        theme_content = full_content[theme_start:theme_end]
                        lines = theme_content.split('\n')  # Remove the marker comment line
                        cached_content = '\n'.join(lines[1:])
                        # Cache the result
                        if theme_type == 'dark':
                            self._cached_dark_qss = cached_content
                        else:
                            self._cached_light_qss = cached_content
                        return cached_content

        except Exception as e:
            log(f"Error loading styles.qss: {e}", level="error", category="ui")

        # Fallback: inline theme styles
        if theme_type == 'dark':
            fallback = """
                QWidget { color: #e6e6e6; }
                QToolTip { color: #e6e6e6; background-color: #333333; border: 1px solid #555; }
                QTableWidget { background-color: #1e1e1e; color: #e6e6e6; gridline-color: #555555; border: 1px solid #555555; }
                QTableWidget::item { background-color: #1e1e1e; color: #e6e6e6; }
                QTableWidget::item:selected { background-color: #2f5f9f; color: #ffffff; }
                QHeaderView::section { background-color: #2d2d2d; color: #e6e6e6; }
                QMenu { background-color: #2d2d2d; color: #e6e6e6; border: 1px solid #555; font-size: 12px; }
                QMenu::item { background-color: transparent; }
                QMenu::item:selected { background-color: #2f5f9f; }
                QLabel { color: #e6e6e6; }
            """
            self._cached_dark_qss = fallback
            return fallback
        else:  # light theme
            fallback = """
                QWidget { color: #333333; }
                QToolTip { color: #333333; background-color: #ffffcc; border: 1px solid #999; }
                QTableWidget { background-color: #ffffff; color: #333333; gridline-color: #cccccc; border: 1px solid #cccccc; }
                QTableWidget::item { background-color: #ffffff; color: #333333; }
                QTableWidget::item:selected { background-color: #3399ff; color: #ffffff; }
                QHeaderView::section { background-color: #f0f0f0; color: #333333; }
                QMenu { background-color: #ffffff; color: #333333; border: 1px solid #999; font-size: 12px; }
                QMenu::item { background-color: transparent; }
                QMenu::item:selected { background-color: #3399ff; }
                QLabel { color: #333333; }
            """
            self._cached_light_qss = fallback
            return fallback

    # =========================================================================
    # Theme Application Methods
    # =========================================================================

    def apply_theme(self, mode: str):
        """Apply theme. Only 'light' and 'dark' modes supported.

        Sets application palette and stylesheet for consistent theming.

        Args:
            mode: Theme mode to apply ('light' or 'dark')
        """
        mw = self._main_window
        try:
            qapp = QApplication.instance()
            if qapp is None or not isinstance(qapp, QApplication):
                return

            # Disable updates during theme switch to prevent intermediate repaints
            mw.setUpdatesEnabled(False)
            try:
                # Load base QSS stylesheet
                base_qss = self._load_base_stylesheet()

                if mode == 'dark':
                    # Simple dark palette and base stylesheet
                    palette = qapp.palette()
                    try:
                        palette.setColor(palette.ColorRole.Window, QColor(30, 30, 30))
                        palette.setColor(palette.ColorRole.WindowText, QColor(230, 230, 230))
                        palette.setColor(palette.ColorRole.Base, QColor(25, 25, 25))
                        palette.setColor(palette.ColorRole.Text, QColor(230, 230, 230))
                        palette.setColor(palette.ColorRole.Button, QColor(45, 45, 45))
                        palette.setColor(palette.ColorRole.ButtonText, QColor(230, 230, 230))
                        palette.setColor(palette.ColorRole.Highlight, QColor(47, 106, 160))
                        palette.setColor(palette.ColorRole.HighlightedText, QColor(255, 255, 255))
                    except Exception as e:
                        log(f"Exception in theme_manager apply_theme: {e}",
                            level="error", category="ui")
                        raise
                    qapp.setPalette(palette)

                    # Load dark theme styles from styles.qss
                    theme_qss = self._load_theme_styles('dark')
                    qapp.setStyleSheet(base_qss + "\n" + theme_qss)
                elif mode == 'light':
                    palette = qapp.palette()
                    try:
                        palette.setColor(palette.ColorRole.Window, QColor(255, 255, 255))
                        palette.setColor(palette.ColorRole.WindowText, QColor(33, 33, 33))
                        palette.setColor(palette.ColorRole.Base, QColor(255, 255, 255))
                        palette.setColor(palette.ColorRole.Text, QColor(33, 33, 33))
                        palette.setColor(palette.ColorRole.Button, QColor(245, 245, 245))
                        palette.setColor(palette.ColorRole.ButtonText, QColor(33, 33, 33))
                        palette.setColor(palette.ColorRole.Highlight, QColor(41, 128, 185))
                        palette.setColor(palette.ColorRole.HighlightedText, QColor(255, 255, 255))
                    except Exception as e:
                        log(f"Exception in theme_manager apply_theme: {e}",
                            level="error", category="ui")
                        raise
                    qapp.setPalette(palette)

                    # Load light theme styles from styles.qss
                    theme_qss = self._load_theme_styles('light')
                    qapp.setStyleSheet(base_qss + "\n" + theme_qss)
                else:
                    # Default to dark if unknown mode
                    return self.apply_theme('dark')

                mw._current_theme_mode = mode
                # Trigger a light refresh on key widgets
                try:
                    # Just apply font sizes instead of full refresh when changing theme
                    if hasattr(mw, 'gallery_table') and mw.gallery_table:
                        font_size = self._get_current_font_size()
                        self.apply_font_size(font_size)

                    # Defer icon refresh to next event loop iteration
                    # This allows the stylesheet to render first, making UI immediately responsive
                    QTimer.singleShot(0, mw._refresh_button_icons)
                    QTimer.singleShot(0, mw.refresh_all_status_icons)
                except Exception as e:
                    log(f"Exception in theme_manager apply_theme: {e}",
                        level="error", category="ui")
                    raise
            finally:
                mw.setUpdatesEnabled(True)
        except Exception as e:
            log(f"Exception in theme_manager apply_theme: {e}",
                level="error", category="ui")
            raise

    # =========================================================================
    # Font Size Methods
    # =========================================================================

    def apply_font_size(self, font_size: int):
        """Apply the specified font size throughout the application.

        Args:
            font_size: Font size in points to apply
        """
        mw = self._main_window
        try:
            # Update application-wide font sizes
            mw._current_font_size = font_size

            # Update table font sizes - set on the actual table widget
            if hasattr(mw, 'gallery_table') and hasattr(mw.gallery_table, 'table'):
                table = mw.gallery_table.table  # This is the actual QTableWidget
                table_font_size = max(font_size - 1, 6)  # Table 1pt smaller, minimum 6pt
                header_font_size = max(font_size - 2, 6)  # Headers even smaller

                # Set font directly on the table widget - this affects all items
                table_font = QFont()
                table_font.setPointSize(table_font_size)
                table.setFont(table_font)

                # Set smaller font on each header item
                header_font = QFont()
                header_font.setPointSize(header_font_size)

                # Use the actual table (table = mw.gallery_table.table)
                for col in range(table.columnCount()):
                    header_item = table.horizontalHeaderItem(col)
                    if header_item:
                        header_item.setFont(header_font)

            # Update log text font
            if hasattr(mw, 'log_text'):
                log_font = QFont("Consolas")
                log_font_size = max(font_size - 1, 6)  # Log text 1pt smaller
                log_font.setPointSize(log_font_size)
                try:
                    log_font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 98.0)
                except Exception as e:
                    log(f"Exception in theme_manager apply_font_size: {e}",
                        level="error", category="ui")
                    raise
                mw.log_text.setFont(log_font)

            # Save the current font size
            if hasattr(mw, 'settings'):
                mw.settings.setValue('ui/font_size', font_size)

        except Exception as e:
            log(f"Error applying font size: {e}", level="warning", category="ui")

    def _get_current_font_size(self) -> int:
        """Get the current font size setting.

        Returns:
            int: Current font size in points
        """
        mw = self._main_window
        if hasattr(mw, '_current_font_size'):
            return mw._current_font_size

        # Load from settings
        if hasattr(mw, 'settings'):
            return int(mw.settings.value('ui/font_size', 9))

        return 9  # Default

    def _get_table_font_sizes(self) -> tuple:
        """Get appropriate font sizes for table elements based on current setting.

        Returns:
            tuple: (table_font_size, name_font_size) in points
        """
        base_font_size = self._get_current_font_size()
        table_font_size = max(base_font_size - 1, 6)  # Table 1pt smaller, minimum 6pt
        name_font_size = base_font_size  # Name column same as base
        return table_font_size, name_font_size
