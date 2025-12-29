"""Menu management for IMXuploader GUI.

This module handles menu bar creation and menu-related dialogs extracted from
main_window.py to improve maintainability and separation of concerns.

Handles:
    - Menu bar creation with File, View, Settings, Tools, Help menus
    - About and License dialog display
    - Windows Explorer context menu integration
"""

import os
from typing import TYPE_CHECKING

from PyQt6.QtCore import QObject, Qt
from PyQt6.QtGui import QActionGroup, QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
)

from src.utils.logger import log

if TYPE_CHECKING:
    from src.gui.main_window import ImxUploadGUI


class MenuManager(QObject):
    """Manages menu bar and menu-related functionality for the main window.

    This manager handles all menu-related operations including:
    - Menu bar creation with all application menus
    - About and License dialog display
    - Windows Explorer context menu integration

    Attributes:
        _main_window: Reference to the main ImxUploadGUI window
        _action_toggle_right_panel: Action for toggling right panel visibility
        _theme_action_light: Action for light theme selection
        _theme_action_dark: Action for dark theme selection
    """

    def __init__(self, main_window: 'ImxUploadGUI'):
        """Initialize the MenuManager.

        Args:
            main_window: Reference to the main ImxUploadGUI window
        """
        super().__init__()
        self._main_window = main_window
        # Action references for external access
        self._action_toggle_right_panel = None
        self._theme_action_light = None
        self._theme_action_dark = None

    # =========================================================================
    # Properties for backward compatibility
    # =========================================================================

    @property
    def action_toggle_right_panel(self):
        """Get the toggle right panel action.

        Returns:
            QAction: The toggle right panel action or None if not created
        """
        return self._action_toggle_right_panel

    @property
    def theme_action_light(self):
        """Get the light theme action.

        Returns:
            QAction: The light theme action or None if not created
        """
        return self._theme_action_light

    @property
    def theme_action_dark(self):
        """Get the dark theme action.

        Returns:
            QAction: The dark theme action or None if not created
        """
        return self._theme_action_dark

    # =========================================================================
    # Menu Bar Setup
    # =========================================================================

    def setup_menu_bar(self):
        """Create a simple application menu bar.

        Creates the complete menu bar with File, View, Settings, Tools,
        and Help menus. Actions are connected to appropriate main window methods.
        """
        mw = self._main_window
        try:
            menu_bar = mw.menuBar()

            # File menu
            file_menu = menu_bar.addMenu("File")
            action_add = file_menu.addAction("Add Folders...")
            action_add.triggered.connect(mw.browse_for_folders)
            file_menu.addSeparator()
            action_start_all = file_menu.addAction("Start All")
            action_start_all.triggered.connect(mw.start_all_uploads)
            action_pause_all = file_menu.addAction("Pause All")
            action_pause_all.triggered.connect(mw.pause_all_uploads)
            action_clear_completed = file_menu.addAction("Clear Completed")
            action_clear_completed.triggered.connect(mw.clear_completed)
            file_menu.addSeparator()
            action_open_store = file_menu.addAction("Open Central Store Folder")
            action_open_store.triggered.connect(mw.open_central_store_folder)
            file_menu.addSeparator()
            action_exit = file_menu.addAction("Exit")
            action_exit.triggered.connect(mw.close)

            # View menu
            view_menu = menu_bar.addMenu("View")
            action_log = view_menu.addAction("Open Log Viewer (Settings)")
            action_log.triggered.connect(mw.open_log_viewer)

            # Standalone log viewer popup
            action_log_popup = view_menu.addAction("Open Log Viewer (Popup)")
            action_log_popup.triggered.connect(mw.open_log_viewer_popup)

            # Icon Manager
            action_icon_manager = view_menu.addAction("Icon Manager")
            action_icon_manager.triggered.connect(mw.open_icon_manager)

            view_menu.addSeparator()

            # Toggle right panel visibility
            self._action_toggle_right_panel = view_menu.addAction("Toggle Right Panel")
            self._action_toggle_right_panel.setShortcut("Ctrl+R")
            self._action_toggle_right_panel.setCheckable(True)
            self._action_toggle_right_panel.setChecked(True)  # Initially visible
            self._action_toggle_right_panel.triggered.connect(mw.toggle_right_panel)

            # Also set on main window for backward compatibility
            mw.action_toggle_right_panel = self._action_toggle_right_panel

            view_menu.addSeparator()

            # Theme submenu: System / Light / Dark
            theme_menu = view_menu.addMenu("Theme")
            theme_group = QActionGroup(mw)
            theme_group.setExclusive(True)
            self._theme_action_light = theme_menu.addAction("Light")
            self._theme_action_light.setCheckable(True)
            self._theme_action_dark = theme_menu.addAction("Dark")
            self._theme_action_dark.setCheckable(True)
            theme_group.addAction(self._theme_action_light)
            theme_group.addAction(self._theme_action_dark)
            self._theme_action_light.triggered.connect(lambda: mw.set_theme_mode('light'))
            self._theme_action_dark.triggered.connect(lambda: mw.set_theme_mode('dark'))

            # Also set on main window for backward compatibility
            mw._theme_action_light = self._theme_action_light
            mw._theme_action_dark = self._theme_action_dark

            # Initialize checked state from settings
            current_theme = str(mw.settings.value('ui/theme', 'dark'))
            if current_theme == 'light':
                self._theme_action_light.setChecked(True)
            else:
                self._theme_action_dark.setChecked(True)

            # Settings menu
            settings_menu = menu_bar.addMenu("Settings")
            action_general = settings_menu.addAction("General")
            action_general.triggered.connect(lambda: mw.open_comprehensive_settings(tab_index=0))
            action_credentials = settings_menu.addAction("Credentials")
            action_credentials.triggered.connect(lambda: mw.open_comprehensive_settings(tab_index=1))
            action_templates = settings_menu.addAction("Templates")
            action_templates.triggered.connect(lambda: mw.open_comprehensive_settings(tab_index=2))
            # Tabs and Icons menu items removed - functionality hidden
            action_logs = settings_menu.addAction("Log Settings")
            action_logs.triggered.connect(lambda: mw.open_comprehensive_settings(tab_index=3))
            action_scanning = settings_menu.addAction("Image Scanning")
            action_scanning.triggered.connect(lambda: mw.open_comprehensive_settings(tab_index=4))
            action_external_apps = settings_menu.addAction("Hooks (External Apps)")
            action_external_apps.triggered.connect(lambda: mw.open_comprehensive_settings(tab_index=5))
            action_file_hosts = settings_menu.addAction("File Hosts")
            action_file_hosts.triggered.connect(lambda: mw.open_comprehensive_settings(tab_index=6))

            # Tools menu
            tools_menu = menu_bar.addMenu("Tools")
            action_unrenamed = tools_menu.addAction("Unnamed Galleries")
            action_unrenamed.triggered.connect(mw.open_unrenamed_galleries_dialog)

            # Authentication submenu
            auth_menu = tools_menu.addMenu("Authentication")
            action_retry_login = auth_menu.addAction("Reattempt Login")
            action_retry_login.triggered.connect(lambda: mw.retry_login(False))
            action_retry_login_creds = auth_menu.addAction("Reattempt Login (Credentials Only)")
            action_retry_login_creds.triggered.connect(lambda: mw.retry_login(True))

            # Windows context menu integration
            context_menu = tools_menu.addMenu("Windows Explorer Integration")
            action_install_ctx = context_menu.addAction("Install Context Menu...")
            action_install_ctx.triggered.connect(self.install_context_menu)
            action_remove_ctx = context_menu.addAction("Remove Context Menu...")
            action_remove_ctx.triggered.connect(self.remove_context_menu)

            # Help menu
            help_menu = menu_bar.addMenu("Help")
            action_help = help_menu.addAction("Help")
            action_help.setShortcut("F1")
            action_help.triggered.connect(mw.open_help_dialog)
            action_license = help_menu.addAction("License")
            action_license.triggered.connect(self.show_license_dialog)
            action_about = help_menu.addAction("About")
            action_about.triggered.connect(self.show_about_dialog)

            # Check for Updates placeholder
            help_menu.addSeparator()
            action_check_updates = help_menu.addAction("Check for Updates...")
            action_check_updates.triggered.connect(mw.check_for_updates)

        except Exception as e:
            # If menu bar creation fails, log the error and continue
            log(f"Menu bar creation failed: {e}", level="error", category="ui")

    # =========================================================================
    # Dialog Methods
    # =========================================================================

    def show_about_dialog(self):
        """Show a custom About dialog with logo."""
        mw = self._main_window

        try:
            from imxup import __version__, get_project_root
            version = f"{__version__}"
        except Exception as e:
            log(f"Failed to get version: {e}", level="warning", category="ui")
            version = "unknown"

        dialog = QDialog(mw)
        dialog.setWindowTitle("About IMXup")
        dialog.setFixedSize(400, 500)
        dialog.setModal(True)

        layout = QVBoxLayout(dialog)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 20, 20, 20)

        # Add logo at top
        try:
            from imxup import get_project_root
            logo_path = os.path.join(get_project_root(), 'assets', 'imxup.png')
            logo_pixmap = QPixmap(logo_path)
            if not logo_pixmap.isNull():
                logo_label = QLabel()
                # Scale logo to reasonable size
                scaled_logo = logo_pixmap.scaledToHeight(80, Qt.TransformationMode.SmoothTransformation)
                logo_label.setPixmap(scaled_logo)
                logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                layout.addWidget(logo_label)
        except Exception as e:
            log(f"Exception in menu_manager show_about_dialog: {e}", level="error", category="ui")
            raise

        # Add title
        title_label = QLabel("IMXup")
        title_label.setProperty("class", "about-title")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)

        # Add subtitle
        subtitle_label = QLabel("IMX.to Gallery Uploader")
        subtitle_label.setProperty("class", "about-subtitle")
        subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle_label)

        # Add version
        version_label = QLabel(version)
        version_label.setProperty("class", "about-version")
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version_label)

        # Add info text
        info_text = QTextBrowser()
        info_text.setProperty("class", "about-info")
        info_html = """
        <div align="center">
        <p><strong>Copyright (C) 2025, twat</strong></p>
        <p><strong>License:</strong> MIT</p>
        <br>
        <p style="color: #666; font-size: 9px;">
        We are not affiliated with IMX.to in any way, but use of the software
        to interact with the IMX.to service is subject to their terms of use
        and privacy policy:<br>
        <a href="https://imx.to/page/terms">https://imx.to/page/terms</a><br>
        <a href="https://imx.to/page/terms">https://imx.to/page/privacy</a>
        </p>
        </div>
        """
        info_text.setHtml(info_html)
        layout.addWidget(info_text)

        # Add close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        close_btn.setStyleSheet("QPushButton { min-width: 80px; }")
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        dialog.exec()

    def show_license_dialog(self):
        """Show the LICENSE file in a dialog."""
        mw = self._main_window

        dialog = QDialog(mw)
        dialog.setWindowTitle("License")
        dialog.resize(700, 600)
        dialog.setModal(True)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(10, 10, 10, 10)

        # Text display for license
        license_text = QTextEdit()
        license_text.setReadOnly(True)
        license_text.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)

        # Load LICENSE file
        try:
            from imxup import get_project_root
            license_path = os.path.join(get_project_root(), 'LICENSE')
            if os.path.exists(license_path):
                with open(license_path, 'r', encoding='utf-8') as f:
                    license_content = f.read()
                license_text.setPlainText(license_content)
            else:
                license_text.setPlainText("LICENSE file not found. See https://spdx.org/licenses/MIT.html")
        except Exception as e:
            license_text.setPlainText(f"Error loading LICENSE file: {e}")

        # Scroll to top
        cursor = license_text.textCursor()
        cursor.movePosition(cursor.MoveOperation.Start)
        license_text.setTextCursor(cursor)

        layout.addWidget(license_text)

        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        close_btn.setStyleSheet("QPushButton { min-width: 80px; }")
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        dialog.exec()

    # =========================================================================
    # Windows Context Menu Integration
    # =========================================================================

    def install_context_menu(self):
        """Install Windows Explorer context menu integration."""
        mw = self._main_window
        try:
            from imxup import create_windows_context_menu
            ok = create_windows_context_menu()
            if ok:
                QMessageBox.information(mw, "Context Menu", "Windows Explorer context menu installed successfully.")
                log("Installed Windows context menu", category="system", level="debug")
            else:
                QMessageBox.warning(mw, "Context Menu", "Failed to install Windows Explorer context menu.")
                log("Failed to install Windows context menu", category="system", level="debug")
        except Exception as e:
            QMessageBox.warning(mw, "Context Menu", f"Error installing context menu: {e}")
            log(f"Error installing context menu: {e}", category="system", level="debug")

    def remove_context_menu(self):
        """Remove Windows Explorer context menu integration."""
        mw = self._main_window
        try:
            from imxup import remove_windows_context_menu
            ok = remove_windows_context_menu()
            if ok:
                QMessageBox.information(mw, "Context Menu", "Windows Explorer context menu removed successfully.")
                log("Removed Windows context menu", category="system", level="debug")
            else:
                QMessageBox.warning(mw, "Context Menu", "Failed to remove Windows Explorer context menu.")
                log("Failed to remove Windows context menu", category="system", level="warning")
        except Exception as e:
            QMessageBox.warning(mw, "Context Menu", f"Error removing context menu: {e}")
            try:
                log(f"Error removing context menu: {e}", category="system", level="error")
            except Exception as e:
                log(f"Exception in menu_manager: {e}", level="error", category="ui")
                raise
