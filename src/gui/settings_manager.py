"""Settings management for IMXuploader GUI.

This module handles application settings persistence extracted from main_window.py
to improve maintainability and separation of concerns.

Handles:
    - Window geometry and splitter state persistence
    - Table column configuration (widths, visibility, order)
    - Quick settings auto-save to INI file
    - Theme and font size restoration
"""

import json
import configparser
import os
from typing import TYPE_CHECKING

from PyQt6.QtCore import QObject, QTimer

from src.utils.logger import log
from imxup import load_user_defaults, get_config_path

if TYPE_CHECKING:
    from src.gui.main_window import ImxUploadGUI


class SettingsManager(QObject):
    """Manages application settings persistence for the main window.

    This manager handles all settings-related operations including:
    - Window geometry and splitter state
    - Table column configuration
    - Quick settings (thumbnails, templates, etc.)
    - Theme and font preferences

    Attributes:
        _main_window: Reference to the main ImxUploadGUI window
    """

    def __init__(self, main_window: 'ImxUploadGUI'):
        """Initialize the SettingsManager.

        Args:
            main_window: Reference to the main ImxUploadGUI window
        """
        super().__init__()
        self._main_window = main_window

    # =========================================================================
    # Window Settings Methods
    # =========================================================================

    def restore_settings(self):
        """Restore window settings from QSettings.

        Restores window geometry, splitter states, right panel collapsed state,
        table column configuration, theme, and font size from persistent storage.
        """
        mw = self._main_window
        settings = mw.settings

        # Restore window geometry
        geometry = settings.value("geometry")
        if geometry:
            mw.restoreGeometry(geometry)

        # Restore splitter states for resizable dividers
        if hasattr(mw, 'top_splitter'):
            splitter_state = settings.value("splitter/state")
            if splitter_state:
                mw.top_splitter.restoreState(splitter_state)

        # Restore vertical splitter state (Settings/Log divider)
        if hasattr(mw, 'right_vertical_splitter'):
            vertical_splitter_state = settings.value("splitter/vertical_state")
            if vertical_splitter_state:
                mw.right_vertical_splitter.restoreState(vertical_splitter_state)

        # Restore right panel collapsed state
        is_collapsed = settings.value("right_panel/collapsed", False, type=bool)
        if is_collapsed and hasattr(mw, 'action_toggle_right_panel'):
            # Collapse after a short delay to allow UI to initialize
            QTimer.singleShot(100, lambda: mw.toggle_right_panel())
        elif hasattr(mw, 'action_toggle_right_panel'):
            mw.action_toggle_right_panel.setChecked(True)

        # Load settings from .ini file (for reference by other components)
        defaults = load_user_defaults()

        # Restore table columns (widths and visibility)
        self.restore_table_settings()

        # Apply saved theme
        try:
            theme = str(settings.value('ui/theme', 'dark'))
            mw.apply_theme(theme)
        except Exception as e:
            log(f"Exception in settings_manager restore_settings (theme): {e}",
                level="error", category="ui")
            raise

        # Apply saved font size
        try:
            font_size = int(settings.value('ui/font_size', 9))
            mw.apply_font_size(font_size)
        except Exception as e:
            log(f"Error loading font size: {e}", category="ui", level="debug")

    def save_settings(self):
        """Save window settings to QSettings.

        Persists window geometry, splitter states, right panel collapsed state,
        and table column configuration.
        """
        mw = self._main_window
        settings = mw.settings

        # Save window geometry
        settings.setValue("geometry", mw.saveGeometry())

        # Save splitter states for resizable dividers
        if hasattr(mw, 'top_splitter'):
            settings.setValue("splitter/state", mw.top_splitter.saveState())

        # Save vertical splitter state (Settings/Log divider)
        if hasattr(mw, 'right_vertical_splitter'):
            settings.setValue("splitter/vertical_state",
                            mw.right_vertical_splitter.saveState())

        # Save right panel collapsed state
        if hasattr(mw, 'action_toggle_right_panel'):
            is_collapsed = not mw.action_toggle_right_panel.isChecked()
            settings.setValue("right_panel/collapsed", is_collapsed)

        # Save table column settings
        self.save_table_settings()

    # =========================================================================
    # Table Column Settings Methods
    # =========================================================================

    def save_table_settings(self):
        """Persist table column widths, visibility, and order to settings.

        Saves the current state of all table columns including:
        - Column widths (in pixels)
        - Column visibility (shown/hidden)
        - Column order (visual position of each logical column)

        Data is stored as JSON strings in QSettings.
        """
        mw = self._main_window
        settings = mw.settings

        try:
            column_count = mw.gallery_table.columnCount()
            widths = [mw.gallery_table.columnWidth(i) for i in range(column_count)]
            visibility = [not mw.gallery_table.isColumnHidden(i)
                         for i in range(column_count)]

            # Persist header order (visual indices by logical section)
            header = mw.gallery_table.horizontalHeader()
            order = [header.visualIndex(i) for i in range(column_count)]

            settings.setValue("table/column_widths", json.dumps(widths))
            settings.setValue("table/column_visible", json.dumps(visibility))
            settings.setValue("table/column_order", json.dumps(order))

        except Exception as e:
            log(f"Exception in settings_manager save_table_settings: {e}",
                level="error", category="ui")
            raise

    def restore_table_settings(self):
        """Restore table column widths, visibility, and order from settings.

        Reads saved column configuration from QSettings and applies it to the
        gallery table. Handles column widths, visibility, and reordering.
        """
        mw = self._main_window
        settings = mw.settings

        try:
            column_count = mw.gallery_table.columnCount()
            widths_raw = settings.value("table/column_widths")
            visible_raw = settings.value("table/column_visible")
            order_raw = settings.value("table/column_order")

            # Restore column widths
            if widths_raw:
                try:
                    widths = json.loads(widths_raw)
                    for i in range(min(column_count, len(widths))):
                        if isinstance(widths[i], int) and widths[i] > 0:
                            mw.gallery_table.setColumnWidth(i, widths[i])
                except Exception as e:
                    log(f"Exception restoring column widths: {e}",
                        level="error", category="ui")
                    raise

            # Restore column visibility
            if visible_raw:
                try:
                    visible = json.loads(visible_raw)
                    for i in range(min(column_count, len(visible))):
                        mw.gallery_table.setColumnHidden(i, not bool(visible[i]))
                except Exception as e:
                    log(f"Exception restoring column visibility: {e}",
                        level="error", category="ui")
                    raise

            # Restore column order
            if order_raw:
                try:
                    header = mw.gallery_table.horizontalHeader()
                    order = json.loads(order_raw)

                    # order is list of visualIndex for each logical section
                    # Build inverse mapping: target_visual_index -> logical
                    target_visual_to_logical = {
                        v: i for i, v in enumerate(order) if isinstance(v, int)
                    }

                    # Move sections in order of target visual positions
                    for target_visual in range(min(column_count, len(order))):
                        logical = target_visual_to_logical.get(target_visual)
                        if logical is None:
                            continue
                        current_visual = header.visualIndex(logical)
                        if current_visual != target_visual:
                            header.moveSection(current_visual, target_visual)

                except Exception as e:
                    log(f"Exception restoring column order: {e}",
                        level="error", category="ui")
                    raise

        except Exception as e:
            log(f"Exception in settings_manager restore_table_settings: {e}",
                level="error", category="ui")
            raise

    # =========================================================================
    # Quick Settings Methods
    # =========================================================================

    def on_setting_changed(self):
        """Handle when any quick setting is changed - auto-save immediately.

        This is triggered by signal connections from quick settings controls
        (thumbnail size, format, template, auto-start, etc.) to persist
        changes immediately without requiring a save button.
        """
        self.save_upload_settings()

    def save_upload_settings(self):
        """Save upload settings to INI file.

        Persists quick settings including:
        - Thumbnail size and format
        - Template selection
        - Auto-start upload preference
        - Artifact storage options (uploaded folder, central store)
        - Central store path

        Also preserves existing settings (max_retries, parallel_batch_size)
        that are only editable in the comprehensive settings dialog.
        """
        from PyQt6.QtWidgets import QMessageBox

        mw = self._main_window

        try:
            # Get current values from UI controls
            thumbnail_size = mw.thumbnail_size_combo.currentIndex() + 1
            thumbnail_format = mw.thumbnail_format_combo.currentIndex() + 1

            # Max retries and batch size are only in comprehensive settings
            defaults = load_user_defaults()
            max_retries = defaults.get('max_retries', 3)
            parallel_batch_size = defaults.get('parallel_batch_size', 4)

            template_name = mw.template_combo.currentText()
            auto_start_upload = mw.auto_start_upload_check.isChecked()
            store_in_uploaded = mw.store_in_uploaded_check.isChecked()
            store_in_central = mw.store_in_central_check.isChecked()
            central_store_path = (mw.central_store_path_value or "").strip()

            # Load existing config
            config = configparser.ConfigParser()
            config_file = get_config_path()

            if os.path.exists(config_file):
                config.read(config_file, encoding='utf-8')

            # Ensure DEFAULTS section exists
            if 'DEFAULTS' not in config:
                config['DEFAULTS'] = {}

            # Update settings
            config['DEFAULTS']['thumbnail_size'] = str(thumbnail_size)
            config['DEFAULTS']['thumbnail_format'] = str(thumbnail_format)
            config['DEFAULTS']['max_retries'] = str(max_retries)
            config['DEFAULTS']['parallel_batch_size'] = str(parallel_batch_size)
            config['DEFAULTS']['template_name'] = template_name
            config['DEFAULTS']['auto_start_upload'] = str(auto_start_upload)
            config['DEFAULTS']['store_in_uploaded'] = str(store_in_uploaded)
            config['DEFAULTS']['store_in_central'] = str(store_in_central)
            # Persist central store path (empty string implies default)
            config['DEFAULTS']['central_store_path'] = central_store_path

            # Save to file
            with open(config_file, 'w', encoding='utf-8') as f:
                config.write(f)

            log("Quick settings saved successfully", level="info", category="ui")

        except Exception as e:
            log(f"Exception saving settings: {str(e)}", level="error", category="ui")
            QMessageBox.warning(mw, "Error", f"Failed to save settings: {str(e)}")
