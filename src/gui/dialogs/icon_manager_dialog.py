#!/usr/bin/env python3
"""
Icon Manager Dialog - Standalone dialog for managing application icons
"""

import os
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QPushButton, QLabel, QListWidget, QListWidgetItem, QSplitter,
    QFileDialog, QPlainTextEdit, QFrame, QMessageBox, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QDragEnterEvent, QDropEvent

from src.utils.format_utils import timestamp
from src.utils.logger import log
from src.gui.dialogs.message_factory import MessageBoxFactory, show_info, show_error, show_warning


class IconDropFrame(QFrame):
    """Drop-enabled frame for icon files"""

    icon_dropped = pyqtSignal(str)  # Emits file path when icon is dropped

    def __init__(self, variant_type):
        super().__init__()
        self.variant_type = variant_type
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent | None) -> None:
        """Handle drag enter event"""
        if event is None:
            return
        mime_data = event.mimeData()
        if mime_data is not None and mime_data.hasUrls():
            urls = mime_data.urls()
            if len(urls) == 1:
                file_path = urls[0].toLocalFile()
                if file_path.lower().endswith(('.png', '.ico', '.svg', '.jpg', '.jpeg')):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event: QDropEvent | None) -> None:
        """Handle drop event"""
        if event is None:
            return
        mime_data = event.mimeData()
        if mime_data is None:
            event.ignore()
            return
        urls = mime_data.urls()
        if len(urls) == 1:
            file_path = urls[0].toLocalFile()
            if file_path.lower().endswith(('.png', '.ico', '.svg', '.jpg', '.jpeg')):
                self.icon_dropped.emit(file_path)
                event.acceptProposedAction()
                return
        event.ignore()


class IconManagerDialog(QDialog):
    """Standalone dialog for managing application icons"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.setWindowTitle("Icon Manager")
        self.resize(800, 600)

        # Initialize icon data storage
        self.icon_data = {}

        # Setup UI
        self.setup_ui()

    def setup_ui(self):
        """Setup the Icon Manager UI"""
        layout = QVBoxLayout(self)

        # Header info
        info_label = QLabel("Customize application icons. Single icons auto-adapt to themes, pairs give full control.")
        info_label.setWordWrap(True)
        info_label.setProperty("class", "tab-description")
        info_label.setMaximumHeight(40)
        info_label.setSizePolicy(info_label.sizePolicy().horizontalPolicy(),
                                QSizePolicy.Policy.Fixed)
        layout.addWidget(info_label)

        layout.addSpacing(8)

        # Create splitter for icon categories and preview
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        # Left side - Icon categories tree
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)

        category_group = QGroupBox("Icon Categories")
        category_layout = QVBoxLayout(category_group)

        self.icon_tree = QListWidget()
        self.icon_tree.itemSelectionChanged.connect(self.on_icon_selection_changed)
        category_layout.addWidget(self.icon_tree)

        left_layout.addWidget(category_group)
        splitter.addWidget(left_widget)

        # Right side - Icon details and customization
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)

        # Icon Details group
        details_group = QGroupBox("Icon Details")
        details_layout = QVBoxLayout(details_group)

        self.icon_name_label = QLabel("Select an icon to customize")
        self.icon_name_label.setProperty("class", "label-icon-name")
        details_layout.addWidget(self.icon_name_label)

        self.icon_description_label = QLabel("")
        self.icon_description_label.setWordWrap(True)
        self.icon_description_label.setProperty("class", "label-icon-description")
        details_layout.addWidget(self.icon_description_label)

        right_layout.addWidget(details_group)

        # Light/Dark Icon Preview
        preview_group = QGroupBox("Icon Preview")
        preview_layout = QVBoxLayout(preview_group)

        # Create side-by-side preview boxes
        preview_boxes_layout = QHBoxLayout()

        # Light theme box
        light_box = QGroupBox("Light Theme")
        light_box_layout = QVBoxLayout(light_box)

        self.light_icon_frame = IconDropFrame('light')
        self.light_icon_frame.setFixedSize(100, 100)
        self.light_icon_frame.setProperty("class", "light-icon-frame")
        self.light_icon_frame.icon_dropped.connect(lambda path: self.handle_icon_drop_variant(path, 'light'))
        light_frame_layout = QVBoxLayout(self.light_icon_frame)
        light_frame_layout.setContentsMargins(0, 0, 0, 0)

        self.light_icon_label = QLabel()
        self.light_icon_label.setFixedSize(96, 96)
        self.light_icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.light_icon_label.setProperty("class", "label-icon-preview")
        self.light_icon_label.setScaledContents(True)
        light_frame_layout.addWidget(self.light_icon_label)

        light_box_layout.addWidget(self.light_icon_frame, 0, Qt.AlignmentFlag.AlignCenter)

        self.light_status_label = QLabel("No icon")
        self.light_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.light_status_label.setProperty("class", "label-icon-status")
        light_box_layout.addWidget(self.light_status_label)

        light_controls = QHBoxLayout()
        self.light_browse_btn = QPushButton("Browse")
        self.light_browse_btn.clicked.connect(lambda: self.browse_for_icon_variant('light'))
        self.light_browse_btn.setEnabled(False)
        light_controls.addWidget(self.light_browse_btn)

        self.light_reset_btn = QPushButton("Reset")
        self.light_reset_btn.clicked.connect(lambda: self.reset_icon_variant('light'))
        self.light_reset_btn.setEnabled(False)
        light_controls.addWidget(self.light_reset_btn)

        light_box_layout.addLayout(light_controls)
        preview_boxes_layout.addWidget(light_box)

        # Dark theme box
        dark_box = QGroupBox("Dark Theme")
        dark_box_layout = QVBoxLayout(dark_box)

        self.dark_icon_frame = IconDropFrame('dark')
        self.dark_icon_frame.setFixedSize(100, 100)
        self.dark_icon_frame.setProperty("class", "dark-icon-frame")
        self.dark_icon_frame.icon_dropped.connect(lambda path: self.handle_icon_drop_variant(path, 'dark'))
        dark_frame_layout = QVBoxLayout(self.dark_icon_frame)
        dark_frame_layout.setContentsMargins(0, 0, 0, 0)

        self.dark_icon_label = QLabel()
        self.dark_icon_label.setFixedSize(96, 96)
        self.dark_icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.dark_icon_label.setProperty("class", "label-icon-preview")
        self.dark_icon_label.setScaledContents(True)
        dark_frame_layout.addWidget(self.dark_icon_label)

        dark_box_layout.addWidget(self.dark_icon_frame, 0, Qt.AlignmentFlag.AlignCenter)

        self.dark_status_label = QLabel("No icon")
        self.dark_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.dark_status_label.setProperty("class", "label-icon-status")
        dark_box_layout.addWidget(self.dark_status_label)

        dark_controls = QHBoxLayout()
        self.dark_browse_btn = QPushButton("Browse")
        self.dark_browse_btn.clicked.connect(lambda: self.browse_for_icon_variant('dark'))
        self.dark_browse_btn.setEnabled(False)
        dark_controls.addWidget(self.dark_browse_btn)

        self.dark_reset_btn = QPushButton("Reset")
        self.dark_reset_btn.clicked.connect(lambda: self.reset_icon_variant('dark'))
        self.dark_reset_btn.setEnabled(False)
        dark_controls.addWidget(self.dark_reset_btn)

        dark_box_layout.addLayout(dark_controls)
        preview_boxes_layout.addWidget(dark_box)

        preview_layout.addLayout(preview_boxes_layout)

        # Configuration indicator
        self.config_type_label = QLabel("Configuration: Unknown")
        self.config_type_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.config_type_label.setProperty("class", "label-icon-config")
        preview_layout.addWidget(self.config_type_label)

        right_layout.addWidget(preview_group)

        # Global Actions group
        global_actions_group = QGroupBox("Global Actions")
        global_actions_layout = QVBoxLayout(global_actions_group)

        global_button_layout = QHBoxLayout()

        reset_all_btn = QPushButton("Reset All Icons")
        reset_all_btn.clicked.connect(self.reset_all_icons)
        global_button_layout.addWidget(reset_all_btn)

        validate_btn = QPushButton("Validate Icons")
        validate_btn.clicked.connect(self.validate_all_icons)
        global_button_layout.addWidget(validate_btn)

        global_actions_layout.addLayout(global_button_layout)
        right_layout.addWidget(global_actions_group)

        right_layout.addStretch()
        splitter.addWidget(right_widget)

        # Set splitter proportions
        splitter.setSizes([300, 500])

        # Close button at bottom
        close_layout = QHBoxLayout()
        close_layout.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        close_layout.addWidget(close_btn)
        layout.addLayout(close_layout)

        # Initialize icon list
        self.populate_icon_list()

    def populate_icon_list(self):
        """Populate the icon list with all available icons"""
        from src.gui.icon_manager import IconManager

        # Get icon categories from the icon manager
        icon_categories = {
            "Status Icons": [
                ("status_completed", "Completed", "Gallery upload completed successfully"),
                ("status_failed", "Failed", "Gallery upload failed"),
                ("status_uploading", "Uploading", "Currently uploading gallery"),
                ("status_paused", "Paused", "Upload paused by user"),
                ("status_queued", "Queued", "Waiting in upload queue"),
                ("status_ready", "Ready", "Ready to start upload"),
                ("status_pending", "Pending", "Preparing for upload"),
                ("status_incomplete", "Incomplete", "Upload partially completed"),
                ("status_scan_failed", "Scan Failed", "Failed to scan gallery images"),
                ("status_scanning", "Scanning", "Currently scanning gallery"),
            ],
            "Action Icons": [
                ("action_start", "Start", "Start gallery upload"),
                ("action_stop", "Stop", "Stop current upload"),
                ("action_view", "View", "View gallery online"),
                ("action_view_error", "View Error", "View error details"),
                ("action_cancel", "Cancel", "Cancel upload"),
                ("action_resume", "Resume", "Resume paused upload"),
            ],
            "UI Icons": [
                ("settings", "Settings", "Settings management icon"),
                ("templates", "Templates", "Template management icon"),
                ("credentials", "Credentials", "Login credentials icon"),
                ("hooks", "Hooks", "Hooks configuration icon"),
                ("log_viewer", "Log Viewer", "Log viewer icon"),
                ("toggle_theme", "Toggle Theme", "Theme toggle icon"),
                ("main_window", "Main Window", "Application window icon"),
                ("app_icon", "Application", "Main application icon"),
            ]
        }

        self.icon_tree.clear()
        self.icon_data = {}

        for category, icons in icon_categories.items():
            # Add category header
            category_item = QListWidgetItem(f"=== {category} ===")
            category_item.setFlags(Qt.ItemFlag.NoItemFlags)

            # Set theme-aware background color
            try:
                pal = self.palette()
                bg = pal.window().color()
                is_dark = (0.2126 * bg.redF() + 0.7152 * bg.greenF() + 0.0722 * bg.blueF()) < 0.5
                if is_dark:
                    category_item.setBackground(QColor(64, 64, 64))
                else:
                    category_item.setBackground(QColor(240, 240, 240))
            except Exception:
                category_item.setBackground(QColor(240, 240, 240))

            font = category_item.font()
            font.setBold(True)
            category_item.setFont(font)
            self.icon_tree.addItem(category_item)

            # Add icons in category
            for icon_key, display_name, description in icons:
                item = QListWidgetItem(f"  {display_name}")
                item.setData(Qt.ItemDataRole.UserRole, icon_key)
                self.icon_tree.addItem(item)

                self.icon_data[icon_key] = {
                    'display_name': display_name,
                    'description': description,
                    'category': category
                }

    def on_icon_selection_changed(self):
        """Handle icon selection change"""
        current_item = self.icon_tree.currentItem()
        if not current_item or not current_item.data(Qt.ItemDataRole.UserRole):
            # Category header or no selection
            self.icon_name_label.setText("Select an icon to customize")
            self.icon_description_label.setText("")
            self.config_type_label.setText("Configuration: Unknown")

            self.light_icon_label.clear()
            self.light_status_label.setText("No icon")
            self.light_browse_btn.setEnabled(False)
            self.light_reset_btn.setEnabled(False)

            self.dark_icon_label.clear()
            self.dark_status_label.setText("No icon")
            self.dark_browse_btn.setEnabled(False)
            self.dark_reset_btn.setEnabled(False)
            return

        icon_key = current_item.data(Qt.ItemDataRole.UserRole)
        icon_info = self.icon_data.get(icon_key, {})

        self.icon_name_label.setText(icon_info.get('display_name', icon_key))
        self.icon_description_label.setText(icon_info.get('description', ''))

        self.update_icon_previews_dual(icon_key)

        self.light_browse_btn.setEnabled(True)
        self.light_reset_btn.setEnabled(True)
        self.dark_browse_btn.setEnabled(True)
        self.dark_reset_btn.setEnabled(True)

    def update_icon_previews_dual(self, icon_key):
        """Update both light and dark icon previews"""
        try:
            from src.gui.icon_manager import get_icon_manager
            icon_manager = get_icon_manager()

            if not icon_manager:
                self.light_status_label.setText("Manager unavailable")
                self.dark_status_label.setText("Manager unavailable")
                self.config_type_label.setText("Configuration: Error")
                return

            icon_config = icon_manager.ICON_MAP.get(icon_key, "Unknown")

            # Determine configuration type
            if isinstance(icon_config, str):
                self.config_type_label.setText("Configuration: Single icon (auto-adapts)")
                self.config_type_label.setProperty("icon-config", "single")
                self.config_type_label.style().unpolish(self.config_type_label)
                self.config_type_label.style().polish(self.config_type_label)
            elif isinstance(icon_config, list):
                self.config_type_label.setText("Configuration: Light/Dark pair (manual control)")
                self.config_type_label.setProperty("icon-config", "pair")
                self.config_type_label.style().unpolish(self.config_type_label)
                self.config_type_label.style().polish(self.config_type_label)
            else:
                self.config_type_label.setText("Configuration: Invalid")
                self.config_type_label.setProperty("icon-config", "invalid")
                self.config_type_label.style().unpolish(self.config_type_label)
                self.config_type_label.style().polish(self.config_type_label)

            # Update light theme preview
            light_icon = icon_manager.get_icon(icon_key, theme_mode='light', is_selected=False, requested_size=96)
            if not light_icon.isNull():
                pixmap = light_icon.pixmap(96, 96)
                self.light_icon_label.setPixmap(pixmap)

                if isinstance(icon_config, str):
                    self.light_status_label.setText("Original")
                    self.light_status_label.setProperty("icon-status", "available")
                    self.light_status_label.style().unpolish(self.light_status_label)
                    self.light_status_label.style().polish(self.light_status_label)
                else:
                    self.light_status_label.setText("Light variant")
                    self.light_status_label.setProperty("icon-status", "available")
                    self.light_status_label.style().unpolish(self.light_status_label)
                    self.light_status_label.style().polish(self.light_status_label)
            else:
                self.light_icon_label.setText("Missing")
                self.light_status_label.setText("Qt fallback")
                self.light_status_label.setProperty("icon-status", "fallback")
                self.light_status_label.style().unpolish(self.light_status_label)
                self.light_status_label.style().polish(self.light_status_label)

            # Update dark theme preview
            dark_icon = icon_manager.get_icon(icon_key, theme_mode='dark', is_selected=False, requested_size=96)
            if not dark_icon.isNull():
                pixmap = dark_icon.pixmap(96, 96)
                self.dark_icon_label.setPixmap(pixmap)

                if isinstance(icon_config, str):
                    self.dark_status_label.setText("Original")
                    self.dark_status_label.setProperty("icon-status", "available")
                    self.dark_status_label.style().unpolish(self.dark_status_label)
                    self.dark_status_label.style().polish(self.dark_status_label)
                else:
                    self.dark_status_label.setText("Dark variant")
                    self.dark_status_label.setProperty("icon-status", "available")
                    self.dark_status_label.style().unpolish(self.dark_status_label)
                    self.dark_status_label.style().polish(self.dark_status_label)
            else:
                self.dark_icon_label.setText("Missing")
                self.dark_status_label.setText("Qt fallback")
                self.dark_status_label.setProperty("icon-status", "fallback")
                self.dark_status_label.style().unpolish(self.dark_status_label)
                self.dark_status_label.style().polish(self.dark_status_label)

            self._update_reset_button_states(icon_key, icon_config)

        except Exception as e:
            log(f"Error updating dual icon previews: {e}", level="warning", category="ui")
            self.light_status_label.setText("Error")
            self.dark_status_label.setText("Error")
            self.config_type_label.setText("Configuration: Error")

    def _update_reset_button_states(self, icon_key, icon_config):
        """Update reset button states"""
        from src.gui.icon_manager import get_icon_manager
        import os

        icon_manager = get_icon_manager()
        if not icon_manager:
            return

        try:
            if isinstance(icon_config, str):
                icon_path = os.path.join(icon_manager.assets_dir, icon_config)
                backup_exists = os.path.exists(icon_path + ".backup")

                self.light_reset_btn.setEnabled(backup_exists)
                self.dark_reset_btn.setEnabled(backup_exists)

            elif isinstance(icon_config, list):
                light_path = os.path.join(icon_manager.assets_dir, icon_config[0])
                dark_path = os.path.join(icon_manager.assets_dir, icon_config[1]) if len(icon_config) > 1 else None

                light_backup_exists = os.path.exists(light_path + ".backup")
                dark_backup_exists = bool(dark_path and os.path.exists(dark_path + ".backup"))

                self.light_reset_btn.setEnabled(light_backup_exists)
                self.dark_reset_btn.setEnabled(dark_backup_exists)
            else:
                self.light_reset_btn.setEnabled(False)
                self.dark_reset_btn.setEnabled(False)

        except Exception as e:
            log(f"Error updating reset button states: {e}", level="warning", category="ui")
            self.light_reset_btn.setEnabled(True)
            self.dark_reset_btn.setEnabled(True)

    def handle_icon_drop_variant(self, file_path, variant):
        """Handle dropped icon file for specific variant"""
        current_item = self.icon_tree.currentItem()
        if not current_item or not current_item.data(Qt.ItemDataRole.UserRole):
            show_warning(self, "No Icon Selected",
                              "Please select an icon from the list first.")
            return

        icon_key = current_item.data(Qt.ItemDataRole.UserRole)

        if not file_path.lower().endswith(('.png', '.ico', '.svg', '.jpg', '.jpeg')):
            show_warning(self, "Invalid File Type",
                              "Please select a valid image file (PNG, ICO, SVG, JPG).")
            return

        variant_name = "Light" if variant == 'light' else "Dark"
        confirmation_text = f"Replace the {variant_name.lower()} theme icon for '{self.icon_data[icon_key]['display_name']}' with the selected file?"
        detailed_text = f"File: {file_path}"

        if MessageBoxFactory.question(
            self, "Replace Icon", confirmation_text, detailed_text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            self.replace_icon_file_variant(icon_key, file_path, variant)

    def browse_for_icon_variant(self, variant):
        """Browse for icon file for specific variant"""
        current_item = self.icon_tree.currentItem()
        if not current_item or not current_item.data(Qt.ItemDataRole.UserRole):
            return

        icon_key = current_item.data(Qt.ItemDataRole.UserRole)

        file_dialog = QFileDialog(self)
        file_dialog.setWindowTitle(f"Select {variant.title()} Theme Icon")
        file_dialog.setFileMode(QFileDialog.FileMode.ExistingFile)
        file_dialog.setNameFilter("Image files (*.png *.ico *.svg *.jpg *.jpeg)")

        if file_dialog.exec() == QFileDialog.DialogCode.Accepted:
            selected_files = file_dialog.selectedFiles()
            if selected_files:
                self.replace_icon_file_variant(icon_key, selected_files[0], variant)

    def replace_icon_file_variant(self, icon_key, new_file_path, variant):
        """Replace an icon file for a specific variant"""
        try:
            from src.gui.icon_manager import get_icon_manager
            import shutil
            import os

            icon_manager = get_icon_manager()
            if not icon_manager:
                show_warning(self, "Error", "Icon manager not available.")
                return

            icon_config = icon_manager.ICON_MAP.get(icon_key)
            if not icon_config:
                show_warning(self, "Error", f"Unknown icon key: {icon_key}")
                return

            # Determine target filename
            if isinstance(icon_config, str):
                if variant == 'light':
                    target_filename = icon_config
                else:
                    base, ext = os.path.splitext(icon_config)
                    target_filename = f"{base}-dark{ext}"
                    new_config = [icon_config, target_filename]
                    icon_manager.ICON_MAP[icon_key] = new_config
            elif isinstance(icon_config, list) and len(icon_config) >= 2:
                if variant == 'light':
                    target_filename = icon_config[0]
                else:
                    target_filename = icon_config[1]
            elif isinstance(icon_config, list) and len(icon_config) == 1:
                target_filename = icon_config[0]
            else:
                show_warning(self, "Error", "Invalid icon configuration.")
                return

            target_path = os.path.join(icon_manager.assets_dir, target_filename)

            # Create backup
            if os.path.exists(target_path):
                backup_path = target_path + ".backup"
                shutil.copy2(target_path, backup_path)

            # Copy new file
            shutil.copy2(new_file_path, target_path)

            # Clear cache and refresh
            icon_manager.refresh_cache()
            self.update_icon_previews_dual(icon_key)

            if self.parent and hasattr(self.parent, 'refresh_icons'):
                self.parent.refresh_icons()

            variant_name = f"{variant.title()} theme"
            icon_name = self.icon_data[icon_key]['display_name']
            show_info(self, "Icon Updated",
                                  f"{variant_name} icon for '{icon_name}' has been updated successfully.")

        except Exception as e:
            show_error(self, "Error", f"Failed to replace {variant} icon: {str(e)}")

    def reset_icon_variant(self, variant):
        """Reset a specific variant to default"""
        current_item = self.icon_tree.currentItem()
        if not current_item or not current_item.data(Qt.ItemDataRole.UserRole):
            return

        icon_key = current_item.data(Qt.ItemDataRole.UserRole)
        icon_name = self.icon_data[icon_key]['display_name']
        variant_name = f"{variant.title()} theme"

        question_text = f"Reset the {variant_name.lower()} icon for '{icon_name}' to default?"

        if MessageBoxFactory.question(
            self, "Reset Icon Variant", question_text,
            buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            self.restore_default_icon_variant(icon_key, variant)

    def restore_default_icon_variant(self, icon_key, variant):
        """Restore a specific variant to default"""
        try:
            from src.gui.icon_manager import get_icon_manager
            import os

            icon_manager = get_icon_manager()
            if not icon_manager:
                return

            icon_config = icon_manager.ICON_MAP.get(icon_key)
            if not icon_config:
                return

            # Determine target filename
            if isinstance(icon_config, str):
                target_filename = icon_config
            elif isinstance(icon_config, list):
                if variant == 'light' and len(icon_config) > 0:
                    target_filename = icon_config[0]
                elif variant == 'dark' and len(icon_config) > 1:
                    target_filename = icon_config[1]
                else:
                    show_info(self, "No Reset Needed",
                                          f"No {variant} variant defined for this icon.")
                    return
            else:
                return

            target_path = os.path.join(icon_manager.assets_dir, target_filename)
            backup_path = target_path + ".backup"

            restored = False
            if os.path.exists(backup_path):
                import shutil
                shutil.move(backup_path, target_path)
                restored = True
            else:
                show_warning(self, "Cannot Reset",
                                  f"No backup available for this icon. Original file was not backed up.\n\n"
                                  f"To reset, you'll need to manually restore the original {target_filename} file.")
                return

            if restored:
                icon_manager.refresh_cache()
                self.update_icon_previews_dual(icon_key)

                if self.parent and hasattr(self.parent, 'refresh_icons'):
                    self.parent.refresh_icons()

                icon_name = self.icon_data[icon_key]['display_name']
                variant_name = f"{variant.title()} theme"
                show_info(self, "Icon Reset",
                                      f"{variant_name} icon for '{icon_name}' has been reset to default.")

        except Exception as e:
            show_error(self, "Error", f"Failed to reset {variant} icon: {str(e)}")

    def reset_all_icons(self):
        """Reset all icons to defaults"""
        if MessageBoxFactory.question(
            self, "Reset All Icons", "Reset ALL icons to their default state?",
            detailed_text="This will remove all custom icon files and restore defaults.",
            buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            default_button=QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            try:
                from src.gui.icon_manager import get_icon_manager

                icon_manager = get_icon_manager()
                if not icon_manager:
                    return

                reset_count = 0
                for icon_key in icon_manager.ICON_MAP.keys():
                    try:
                        # Reset both variants if applicable
                        self.restore_default_icon_variant(icon_key, 'light')
                        self.restore_default_icon_variant(icon_key, 'dark')
                        reset_count += 1
                    except Exception as e:
                        log(f"Failed to reset {icon_key}: {e}", level="warning", category="ui")

                # Update current preview
                current_item = self.icon_tree.currentItem()
                if current_item and current_item.data(Qt.ItemDataRole.UserRole):
                    icon_key = current_item.data(Qt.ItemDataRole.UserRole)
                    self.update_icon_previews_dual(icon_key)

                show_info(self, "Reset Complete",
                                      f"Reset {reset_count} icons to default state.")

            except Exception as e:
                show_error(self, "Error", f"Failed to reset icons: {str(e)}")

    def validate_all_icons(self):
        """Validate all icon files"""
        try:
            from src.gui.icon_manager import get_icon_manager

            icon_manager = get_icon_manager()
            if not icon_manager:
                show_warning(self, "Error", "Icon manager not available.")
                return

            result = icon_manager.validate_icons(report=False)

            dialog = QDialog(self)
            dialog.setWindowTitle("Icon Validation Report")
            dialog.resize(500, 400)

            layout = QVBoxLayout(dialog)

            summary_label = QLabel(f"Total icons: {len(icon_manager.ICON_MAP)}\n"
                                 f"Found: {len(result['found'])}\n"
                                 f"Missing: {len(result['missing'])}")
            summary_label.setProperty("class", "label-validation-summary")
            layout.addWidget(summary_label)

            details = QPlainTextEdit()
            details.setReadOnly(True)

            if result['found']:
                details.appendPlainText("=== FOUND ICONS ===")
                for item in result['found']:
                    details.appendPlainText(f"[OK] {item}")
                details.appendPlainText("")

            if result['missing']:
                details.appendPlainText("=== MISSING ICONS ===")
                for item in result['missing']:
                    details.appendPlainText(f"[X] {item}")

            layout.addWidget(details)

            close_btn = QPushButton("Close")
            close_btn.clicked.connect(dialog.accept)
            layout.addWidget(close_btn)

            dialog.exec()

        except Exception as e:
            show_error(self, "Error", f"Failed to validate icons: {str(e)}")
