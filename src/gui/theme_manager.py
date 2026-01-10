"""Theme management for IMXuploader GUI.

This module handles theme switching and font size management extracted from
main_window.py to improve maintainability and separation of concerns.

Handles:
    - Dark/light theme switching with QPalette and QSS
    - Font size management throughout the application
    - Stylesheet caching for performance
    - Design token injection from tokens.json
    - Modular QSS loading from assets/styles/ directory
"""

import json
import os
import re
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import QObject, QTimer
from PyQt6.QtGui import QColor, QFont, QPalette
from PyQt6.QtWidgets import QApplication

from src.utils.logger import log

if TYPE_CHECKING:
    from src.gui.main_window import ImxUploadGUI


# Module-level token cache to avoid repeated file reads
_cached_tokens: dict[str, Any] | None = None

# Component files to load in order (from assets/styles/components/)
COMPONENT_FILES = [
    'buttons.qss',
    'tables.qss',
    'forms.qss',
    'progress.qss',
    'tabs.qss',
    'menus.qss',
    'labels.qss',
]


def get_assets_dir() -> str:
    """Get the absolute path to the assets directory.

    Returns:
        str: Absolute path to project_root/assets directory
    """
    from imxup import get_project_root
    return os.path.join(get_project_root(), "assets")


def is_dark_mode() -> bool:
    """Check if the application is in dark mode.

    Returns:
        True if dark mode, False if light mode.
    """
    from PyQt6.QtCore import QSettings
    # MUST use same org/app name as main_window.py to read from correct registry location
    settings = QSettings("ImxUploader", "ImxUploadGUI")
    return settings.value('ui/theme', 'dark') == 'dark'


def get_online_status_colors(is_dark: bool | None = None) -> dict[str, QColor]:
    """Get theme-aware colors for online status indicators.

    Provides consistent colors for online/partial/offline status display
    across the main gallery table and image status dialog.

    Args:
        is_dark: Override theme detection. If None, uses current theme.

    Returns:
        dict: Color mappings with keys 'online', 'partial', 'offline', 'gray'.
              Each value is a QColor instance appropriate for the current theme.
    """
    if is_dark is None:
        is_dark = is_dark_mode()

    if is_dark:
        # Dark theme: brighter colors for contrast on dark background
        return {
            'online': QColor(85, 208, 165),    # #55D0A5 - bright green
            'partial': QColor(255, 191, 64),   # #FFBF40 - amber/gold
            'offline': QColor(255, 107, 107),  # #FF6B6B - bright red
            'gray': QColor(128, 128, 128),     # #808080 - neutral gray
        }
    else:
        # Light theme: darker colors for contrast on white background
        return {
            'online': QColor(0, 128, 0),       # #008000 - forest green
            'partial': QColor(204, 133, 0),    # #CC8500 - dark amber
            'offline': QColor(204, 0, 0),      # #CC0000 - dark red
            'gray': QColor(128, 128, 128),     # #808080 - neutral gray
        }


class ThemeManager(QObject):
    """Manages theme and font settings for the main window.

    This manager handles all theme-related operations including:
    - Dark/light theme switching with QPalette and stylesheet
    - Font size management for table and log widgets
    - Stylesheet caching for performance
    - Modular QSS loading from assets/styles/ directory structure
    - Design token injection from tokens.json

    The manager supports two QSS loading modes:
    1. Modular (preferred): Loads base.qss + components/*.qss + themes/{theme}.qss
    2. Legacy (fallback): Loads monolithic styles.qss with embedded theme markers

    Attributes:
        _main_window: Reference to the main ImxUploadGUI window
        _cached_base_qss: Cached base stylesheet content (legacy mode)
        _cached_dark_qss: Cached dark theme stylesheet content (legacy mode)
        _cached_light_qss: Cached light theme stylesheet content (legacy mode)
        _cached_modular_dark_qss: Cached modular dark stylesheet (modular mode)
        _cached_modular_light_qss: Cached modular light stylesheet (modular mode)
        _modular_qss_available: Whether modular QSS structure exists
    """

    def __init__(self, main_window: 'ImxUploadGUI'):
        """Initialize the ThemeManager.

        Args:
            main_window: Reference to the main ImxUploadGUI window
        """
        super().__init__()
        self._main_window = main_window
        # Cache for stylesheets (legacy monolithic styles.qss)
        self._cached_base_qss: str | None = None
        self._cached_dark_qss: str | None = None
        self._cached_light_qss: str | None = None
        # Cache for modular QSS (new structure)
        self._cached_modular_dark_qss: str | None = None
        self._cached_modular_light_qss: str | None = None
        self._modular_qss_available: bool | None = None

    # =========================================================================
    # Design Token Methods
    # =========================================================================

    def _load_tokens(self) -> dict[str, Any]:
        """Load design tokens from tokens.json.

        Tokens are cached at module level to avoid repeated file reads.

        Returns:
            dict: Design tokens dictionary, empty dict on error
        """
        global _cached_tokens

        if _cached_tokens is not None:
            return _cached_tokens

        try:
            tokens_path = os.path.join(get_assets_dir(), "tokens.json")
            if os.path.exists(tokens_path):
                with open(tokens_path, 'r', encoding='utf-8') as f:
                    _cached_tokens = json.load(f)
                    log("Design tokens loaded successfully", level="debug", category="ui")
                    return _cached_tokens
            else:
                log(f"Design tokens file not found: {tokens_path}",
                    level="warning", category="ui")
        except json.JSONDecodeError as e:
            log(f"Error parsing tokens.json: {e}", level="error", category="ui")
        except Exception as e:
            log(f"Error loading tokens.json: {e}", level="error", category="ui")

        _cached_tokens = {}
        return _cached_tokens

    def _get_nested_value(self, data: dict[str, Any], path: str) -> str | None:
        """Safely access nested dictionary values using dot notation.

        Args:
            data: Dictionary to traverse
            path: Dot-separated path (e.g., 'colors.light.background.primary')

        Returns:
            str | None: Value at path, or None if not found
        """
        keys = path.split('.')
        current = data

        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return None

        # Return value only if it's a string (actual token value)
        return current if isinstance(current, str) else None

    def _apply_tokens(self, qss: str, theme: str) -> str:
        """Replace $token.path variables in QSS with actual values.

        Supports token references like:
        - $colors.light.background.primary
        - $colors.dark.status.success
        - $typography.fontSize.base
        - $spacing.md
        - $borderRadius.lg

        For colors, the theme parameter determines which color set to use.
        Token paths starting with 'colors.' without a theme prefix will have
        the theme automatically inserted.

        Args:
            qss: QSS stylesheet content with token variables
            theme: Current theme ('light' or 'dark')

        Returns:
            str: QSS with all token variables replaced
        """
        tokens = self._load_tokens()
        if not tokens:
            return qss

        # Pattern to match $token.path variables
        # Matches: $colors.light.background.primary or $typography.fontSize.base
        token_pattern = re.compile(r'\$([a-zA-Z][a-zA-Z0-9_.]*)')

        def replace_token(match: re.Match) -> str:
            """Replace a single token match with its value."""
            token_path = match.group(1)

            # For color tokens, handle theme-specific lookups
            # If path starts with 'colors.' but doesn't have theme, insert it
            if token_path.startswith('colors.'):
                parts = token_path.split('.', 2)
                if len(parts) >= 2:
                    # Check if second part is a theme identifier
                    if parts[1] not in ('light', 'dark'):
                        # Insert the current theme after 'colors.'
                        # e.g., 'colors.background.primary' -> 'colors.dark.background.primary'
                        token_path = f"colors.{theme}.{'.'.join(parts[1:])}"

            value = self._get_nested_value(tokens, token_path)

            if value is not None:
                return value
            else:
                log(f"Missing design token: ${match.group(1)} (resolved as: {token_path})",
                    level="warning", category="ui")
                # Return original token reference so it's visible in output
                return match.group(0)

        return token_pattern.sub(replace_token, qss)

    # =========================================================================
    # Modular QSS Loading Methods
    # =========================================================================

    def _check_modular_qss_available(self) -> bool:
        """Check if modular QSS structure exists.

        Checks for presence of base.qss and themes/dark.qss to determine
        if the new modular structure is available.

        Returns:
            bool: True if modular QSS files exist, False otherwise
        """
        if self._modular_qss_available is not None:
            return self._modular_qss_available

        styles_dir = os.path.join(get_assets_dir(), "styles")
        base_qss = os.path.join(styles_dir, "base.qss")
        dark_theme = os.path.join(styles_dir, "themes", "dark.qss")

        self._modular_qss_available = (
            os.path.exists(base_qss) and os.path.exists(dark_theme)
        )

        if self._modular_qss_available:
            log("Modular QSS structure detected", level="debug", category="ui")
        else:
            log("Modular QSS not found, using legacy styles.qss",
                level="debug", category="ui")

        return self._modular_qss_available

    def _extract_base_styles_from_component(self, content: str) -> str:
        """Extract theme-independent base styles from a component file.

        Component files may contain theme-specific sections marked with
        LIGHT_THEME_START/END and DARK_THEME_START/END. This method extracts
        only the theme-independent portion (everything before the first
        theme marker).

        Args:
            content: Full component file content

        Returns:
            str: Theme-independent base styles only
        """
        # Find the first theme marker
        light_start = content.find('/* LIGHT_THEME_START')
        dark_start = content.find('/* DARK_THEME_START')

        # Determine where base styles end
        if light_start != -1 and dark_start != -1:
            # Both markers exist, take the earlier one
            theme_start = min(light_start, dark_start)
        elif light_start != -1:
            theme_start = light_start
        elif dark_start != -1:
            theme_start = dark_start
        else:
            # No theme markers, entire file is base styles
            return content

        return content[:theme_start].strip()

    def _load_modular_qss(self, theme: str) -> str:
        """Load and concatenate modular QSS files.

        Loads QSS in the following order:
        1. base.qss - Theme-independent base styles
        2. components/*.qss - Component-specific base styles (theme-independent parts)
        3. themes/{theme}.qss - Theme-specific color overrides

        All content is concatenated and token substitution is applied.

        Args:
            theme: Theme to load ('light' or 'dark')

        Returns:
            str: Complete stylesheet with all modules concatenated and tokens applied

        Raises:
            FileNotFoundError: If required files don't exist (caller should fallback)
        """
        # Check cache first
        if theme == 'dark' and self._cached_modular_dark_qss is not None:
            return self._cached_modular_dark_qss
        if theme == 'light' and self._cached_modular_light_qss is not None:
            return self._cached_modular_light_qss

        styles_dir = os.path.join(get_assets_dir(), "styles")
        qss_parts: list[str] = []

        # 1. Load base.qss
        base_qss_path = os.path.join(styles_dir, "base.qss")
        if not os.path.exists(base_qss_path):
            raise FileNotFoundError(f"Base QSS not found: {base_qss_path}")

        with open(base_qss_path, 'r', encoding='utf-8') as f:
            base_content = f.read()
            qss_parts.append(f"/* === BASE STYLES === */\n{base_content}")
            log(f"Loaded base.qss ({len(base_content)} chars)",
                level="debug", category="ui")

        # 2. Load component files (base styles only, no theme-specific parts)
        components_dir = os.path.join(styles_dir, "components")
        loaded_components = []

        for component_file in COMPONENT_FILES:
            component_path = os.path.join(components_dir, component_file)
            if os.path.exists(component_path):
                try:
                    with open(component_path, 'r', encoding='utf-8') as f:
                        component_content = f.read()
                        # Extract only the base (theme-independent) styles
                        base_styles = self._extract_base_styles_from_component(
                            component_content
                        )
                        if base_styles.strip():
                            qss_parts.append(
                                f"\n/* === COMPONENT: {component_file} === */\n{base_styles}"
                            )
                            loaded_components.append(component_file)
                except Exception as e:
                    log(f"Error loading component {component_file}: {e}",
                        level="warning", category="ui")
            else:
                log(f"Component file not found: {component_file}",
                    level="debug", category="ui")

        if loaded_components:
            log(f"Loaded {len(loaded_components)} component files: {', '.join(loaded_components)}",
                level="debug", category="ui")

        # 3. Load theme-specific file
        theme_file = f"{theme}.qss"
        theme_path = os.path.join(styles_dir, "themes", theme_file)
        if not os.path.exists(theme_path):
            raise FileNotFoundError(f"Theme QSS not found: {theme_path}")

        with open(theme_path, 'r', encoding='utf-8') as f:
            theme_content = f.read()
            qss_parts.append(f"\n/* === THEME: {theme.upper()} === */\n{theme_content}")
            log(f"Loaded themes/{theme_file} ({len(theme_content)} chars)",
                level="debug", category="ui")

        # Concatenate all parts
        combined_qss = "\n".join(qss_parts)

        # Apply token substitution
        final_qss = self._apply_tokens(combined_qss, theme)

        # Cache the result
        if theme == 'dark':
            self._cached_modular_dark_qss = final_qss
        else:
            self._cached_modular_light_qss = final_qss

        log(f"Modular QSS loaded for {theme} theme ({len(final_qss)} total chars)",
            level="info", category="ui")

        return final_qss

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

    def _load_base_stylesheet(self, theme: str = 'dark') -> str:
        """Load the base QSS stylesheet for consistent fonts and styling.

        Loads base QSS content (theme-agnostic styles) and applies design token
        substitution. For tokens that require a theme context (like colors),
        the provided theme parameter is used.

        Args:
            theme: Theme context for token resolution ('dark' or 'light').
                   Used when base styles contain theme-dependent tokens.

        Returns:
            str: Base QSS stylesheet content with tokens applied
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
                        raw_content = full_content[:light_start].strip()
                        # Apply token substitution before caching
                        self._cached_base_qss = self._apply_tokens(raw_content, theme)
                        return self._cached_base_qss
                    # Fallback: everything before DARK_THEME_START
                    dark_start = full_content.find('/* DARK_THEME_START')
                    if dark_start != -1:
                        raw_content = full_content[:dark_start].strip()
                        self._cached_base_qss = self._apply_tokens(raw_content, theme)
                        return self._cached_base_qss
                    # Apply tokens to full content if no markers found
                    self._cached_base_qss = self._apply_tokens(full_content, theme)
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

        Loads theme-specific QSS content and applies design token substitution
        before caching. Token variables like $colors.light.background.primary
        are replaced with actual values from tokens.json.

        Args:
            theme_type: Theme type ('dark' or 'light')

        Returns:
            str: Theme-specific QSS stylesheet content with tokens applied
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
                        raw_content = '\n'.join(lines[1:])
                        # Apply design token substitution before caching
                        cached_content = self._apply_tokens(raw_content, theme_type)
                        # Cache the result
                        if theme_type == 'dark':
                            self._cached_dark_qss = cached_content
                        else:
                            self._cached_light_qss = cached_content
                        return cached_content

        except Exception as e:
            log(f"Error loading styles.qss: {e}", level="error", category="ui")

        # Fallback: inline theme styles
        # Note: QTableWidget::item does NOT include color: to allow setForeground() to work
        # for theme-aware colored text (e.g., Online IMX column green/red status)
        if theme_type == 'dark':
            fallback = """
                QWidget { color: #e6e6e6; }
                QToolTip { color: #e6e6e6; background-color: #333333; border: 1px solid #555; }
                QTableWidget { background-color: #1e1e1e; color: #e6e6e6; gridline-color: #555555; border: 1px solid #555555; }
                QTableWidget::item { background-color: #1e1e1e; }
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
                QTableWidget::item { background-color: #ffffff; }
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

    def _get_stylesheet_for_theme(self, theme: str) -> str:
        """Get the complete stylesheet for a theme.

        Tries to load modular QSS first (base + components + theme file).
        Falls back to legacy styles.qss if modular files are not available.

        Args:
            theme: Theme name ('light' or 'dark')

        Returns:
            str: Complete stylesheet content ready for application
        """
        # Try modular QSS first
        if self._check_modular_qss_available():
            try:
                return self._load_modular_qss(theme)
            except FileNotFoundError as e:
                log(f"Modular QSS file missing, falling back to legacy: {e}",
                    level="warning", category="ui")
            except Exception as e:
                log(f"Error loading modular QSS, falling back to legacy: {e}",
                    level="warning", category="ui")

        # Fallback to legacy styles.qss
        log("Using legacy styles.qss", level="debug", category="ui")
        base_qss = self._load_base_stylesheet(theme=theme)
        theme_qss = self._load_theme_styles(theme)
        return base_qss + "\n" + theme_qss

    def apply_theme(self, mode: str):
        """Apply theme. Only 'light' and 'dark' modes supported.

        Sets application palette and stylesheet for consistent theming.
        Uses modular QSS files if available, falls back to legacy styles.qss.

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
                # Try to load modular QSS first, fallback to legacy
                stylesheet = self._get_stylesheet_for_theme(mode)

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
                        # Additional ColorRoles for complete theme support
                        palette.setColor(palette.ColorRole.PlaceholderText, QColor(128, 128, 128))
                        palette.setColor(palette.ColorRole.Link, QColor(80, 160, 220))
                        palette.setColor(palette.ColorRole.LinkVisited, QColor(120, 100, 180))
                        palette.setColor(palette.ColorRole.AlternateBase, QColor(38, 38, 38))  # Slightly different from Button
                        palette.setColor(palette.ColorRole.ToolTipBase, QColor(51, 51, 51))
                        palette.setColor(palette.ColorRole.ToolTipText, QColor(230, 230, 230))
                        # 3D effect and accent colors for complete coverage
                        palette.setColor(palette.ColorRole.Light, QColor(60, 60, 60))
                        palette.setColor(palette.ColorRole.Midlight, QColor(50, 50, 50))
                        palette.setColor(palette.ColorRole.Dark, QColor(20, 20, 20))
                        palette.setColor(palette.ColorRole.Mid, QColor(35, 35, 35))
                        palette.setColor(palette.ColorRole.Shadow, QColor(10, 10, 10))
                        palette.setColor(palette.ColorRole.BrightText, QColor(255, 255, 255))
                        palette.setColor(palette.ColorRole.Accent, QColor(47, 106, 160))
                    except Exception as e:
                        log(f"Exception in theme_manager apply_theme: {e}",
                            level="error", category="ui")
                        raise
                    qapp.setPalette(palette)
                    qapp.setStyleSheet(stylesheet)
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
                        # Additional ColorRoles for complete theme support
                        palette.setColor(palette.ColorRole.PlaceholderText, QColor(128, 128, 128))
                        palette.setColor(palette.ColorRole.Link, QColor(41, 128, 185))
                        palette.setColor(palette.ColorRole.LinkVisited, QColor(120, 80, 150))
                        palette.setColor(palette.ColorRole.AlternateBase, QColor(245, 245, 245))
                        palette.setColor(palette.ColorRole.ToolTipBase, QColor(255, 255, 204))
                        palette.setColor(palette.ColorRole.ToolTipText, QColor(51, 51, 51))
                        # 3D effect and accent colors for complete coverage
                        palette.setColor(palette.ColorRole.Light, QColor(255, 255, 255))
                        palette.setColor(palette.ColorRole.Midlight, QColor(250, 250, 250))
                        palette.setColor(palette.ColorRole.Dark, QColor(180, 180, 180))
                        palette.setColor(palette.ColorRole.Mid, QColor(210, 210, 210))
                        palette.setColor(palette.ColorRole.Shadow, QColor(120, 120, 120))
                        palette.setColor(palette.ColorRole.BrightText, QColor(0, 0, 0))
                        palette.setColor(palette.ColorRole.Accent, QColor(41, 128, 185))
                    except Exception as e:
                        log(f"Exception in theme_manager apply_theme: {e}",
                            level="error", category="ui")
                        raise
                    qapp.setPalette(palette)
                    qapp.setStyleSheet(stylesheet)
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
