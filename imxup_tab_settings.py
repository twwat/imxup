#!/usr/bin/env python3
"""
Tab Settings Widget for ComprehensiveSettingsDialog integration.

Provides UI components for managing tab preferences:
- Tab visibility management
- Auto-archive configuration
- Tab ordering preferences  
- Tab creation/deletion
- Color customization

Integrates with TabManager for unified preference handling.
"""

from __future__ import annotations

from typing import Dict, List, Set, Optional
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QListWidget, 
    QListWidgetItem, QPushButton, QCheckBox, QSpinBox, QLabel,
    QComboBox, QLineEdit, QColorDialog, QMessageBox, QInputDialog,
    QSplitter, QFormLayout, QFrame, QScrollArea, QButtonGroup
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QColor, QPalette

from imxup_tab_manager import TabManager, TabInfo


class TabListWidget(QListWidget):
    """Custom list widget for tab management with drag-and-drop reordering"""
    
    tabs_reordered = pyqtSignal(list)  # List[str] tab names in new order
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        
    def dropEvent(self, event):
        super().dropEvent(event)
        # Emit reorder signal with new tab order
        tab_names = []
        for i in range(self.count()):
            item = self.item(i)
            if item:
                tab_names.append(item.text())
        self.tabs_reordered.emit(tab_names)


class ColorButton(QPushButton):
    """Button that displays and allows selection of colors"""
    
    color_changed = pyqtSignal(str)  # Hex color string
    
    def __init__(self, color: Optional[str] = None, parent=None):
        super().__init__(parent)
        self._color = color or "#FFFFFF"
        self.clicked.connect(self._select_color)
        self._update_appearance()
        
    def set_color(self, color: str) -> None:
        """Set the button color"""
        if color and color != self._color:
            self._color = color
            self._update_appearance()
            
    def get_color(self) -> str:
        """Get current color as hex string"""
        return self._color
        
    def _select_color(self) -> None:
        """Open color dialog"""
        initial_color = QColor(self._color)
        color = QColorDialog.getColor(initial_color, self, "Select Tab Color")
        
        if color.isValid():
            self._color = color.name()
            self._update_appearance()
            self.color_changed.emit(self._color)
            
    def _update_appearance(self) -> None:
        """Update button appearance to show current color"""
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {self._color};
                border: 2px solid #888888;
                border-radius: 4px;
                min-width: 40px;
                min-height: 20px;
            }}
            QPushButton:hover {{
                border: 2px solid #000000;
            }}
        """)
        self.setText("")  # No text, just color


class TabSettingsWidget(QWidget):
    """
    Tab settings widget for integration with ComprehensiveSettingsDialog.
    
    Provides comprehensive tab management interface:
    - Tab visibility controls
    - Auto-archive configuration
    - Tab creation/deletion/modification
    - Color customization
    - Ordering preferences
    """
    
    def __init__(self, tab_manager: TabManager, parent=None):
        super().__init__(parent)
        self.tab_manager = tab_manager
        self._setup_ui()
        self._connect_signals()
        self._load_settings()
        
    def _setup_ui(self) -> None:
        """Set up the user interface"""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        
        # Create main splitter for left/right panels
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)
        
        # Left panel: Tab management
        left_panel = self._create_tab_management_panel()
        splitter.addWidget(left_panel)
        
        # Right panel: Preferences
        right_panel = self._create_preferences_panel()
        splitter.addWidget(right_panel)
        
        # Set splitter proportions
        splitter.setSizes([300, 400])
        
    def _create_tab_management_panel(self) -> QWidget:
        """Create left panel for tab management"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # Tab List Group
        tabs_group = QGroupBox("Tabs")
        tabs_layout = QVBoxLayout(tabs_group)
        
        # Tab list with visibility checkboxes
        self.tab_list = TabListWidget()
        self.tab_list.setAlternatingRowColors(True)
        tabs_layout.addWidget(self.tab_list)
        
        # Tab management buttons
        buttons_layout = QHBoxLayout()
        
        self.add_tab_btn = QPushButton("Add Tab")
        self.edit_tab_btn = QPushButton("Edit")
        self.delete_tab_btn = QPushButton("Delete")
        
        buttons_layout.addWidget(self.add_tab_btn)
        buttons_layout.addWidget(self.edit_tab_btn)
        buttons_layout.addWidget(self.delete_tab_btn)
        buttons_layout.addStretch()
        
        tabs_layout.addLayout(buttons_layout)
        layout.addWidget(tabs_group)
        
        # Visibility Group
        visibility_group = QGroupBox("Visibility")
        visibility_layout = QVBoxLayout(visibility_group)
        
        self.show_all_btn = QPushButton("Show All Tabs")
        self.hide_empty_cb = QCheckBox("Auto-hide empty tabs")
        
        visibility_layout.addWidget(self.show_all_btn)
        visibility_layout.addWidget(self.hide_empty_cb)
        
        layout.addWidget(visibility_group)
        layout.addStretch()
        
        return panel
        
    def _create_preferences_panel(self) -> QWidget:
        """Create right panel for preferences"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # Auto-Archive Group
        archive_group = QGroupBox("Auto-Archive")
        archive_layout = QFormLayout(archive_group)
        
        self.auto_archive_enabled_cb = QCheckBox("Enable auto-archive")
        archive_layout.addRow(self.auto_archive_enabled_cb)
        
        self.auto_archive_days_spin = QSpinBox()
        self.auto_archive_days_spin.setRange(1, 365)
        self.auto_archive_days_spin.setSuffix(" days")
        archive_layout.addRow("Archive after:", self.auto_archive_days_spin)
        
        # Status selection
        status_label = QLabel("Archive statuses:")
        archive_layout.addRow(status_label)
        
        self.status_completed_cb = QCheckBox("Completed")
        self.status_failed_cb = QCheckBox("Failed")
        self.status_incomplete_cb = QCheckBox("Incomplete")
        
        status_layout = QVBoxLayout()
        status_layout.addWidget(self.status_completed_cb)
        status_layout.addWidget(self.status_failed_cb)
        status_layout.addWidget(self.status_incomplete_cb)
        
        status_widget = QWidget()
        status_widget.setLayout(status_layout)
        archive_layout.addRow(status_widget)
        
        # Manual archive button
        self.manual_archive_btn = QPushButton("Run Auto-Archive Now")
        archive_layout.addRow(self.manual_archive_btn)
        
        layout.addWidget(archive_group)
        
        # Default Tab Group
        defaults_group = QGroupBox("Defaults")
        defaults_layout = QFormLayout(defaults_group)
        
        self.default_tab_combo = QComboBox()
        defaults_layout.addRow("Default tab for new galleries:", self.default_tab_combo)
        
        self.startup_tab_combo = QComboBox()
        defaults_layout.addRow("Startup tab:", self.startup_tab_combo)
        
        layout.addWidget(defaults_group)
        
        # Tab Colors Group
        colors_group = QGroupBox("Tab Colors")
        colors_layout = QVBoxLayout(colors_group)
        
        colors_scroll = QScrollArea()
        self.colors_widget = QWidget()
        self.colors_layout = QFormLayout(self.colors_widget)
        colors_scroll.setWidget(self.colors_widget)
        colors_scroll.setWidgetResizable(True)
        colors_scroll.setMaximumHeight(200)
        
        colors_layout.addWidget(colors_scroll)
        layout.addWidget(colors_group)
        
        layout.addStretch()
        return panel
        
    def _connect_signals(self) -> None:
        """Connect widget signals to handlers"""
        # Tab management
        self.add_tab_btn.clicked.connect(self._add_tab)
        self.edit_tab_btn.clicked.connect(self._edit_tab)
        self.delete_tab_btn.clicked.connect(self._delete_tab)
        
        # List selection
        self.tab_list.itemSelectionChanged.connect(self._update_button_states)
        self.tab_list.tabs_reordered.connect(self._handle_tab_reorder)
        
        # Visibility
        self.show_all_btn.clicked.connect(self._show_all_tabs)
        self.hide_empty_cb.toggled.connect(self._save_preferences)
        
        # Auto-archive  
        self.auto_archive_enabled_cb.toggled.connect(self._save_auto_archive)
        self.auto_archive_days_spin.valueChanged.connect(self._save_auto_archive)
        self.status_completed_cb.toggled.connect(self._save_auto_archive)
        self.status_failed_cb.toggled.connect(self._save_auto_archive)
        self.status_incomplete_cb.toggled.connect(self._save_auto_archive)
        self.manual_archive_btn.clicked.connect(self._run_manual_archive)
        
        # Defaults
        self.default_tab_combo.currentTextChanged.connect(self._save_preferences)
        self.startup_tab_combo.currentTextChanged.connect(self._save_startup_tab)
        
        # Tab manager signals
        self.tab_manager.tab_created.connect(self._refresh_tabs)
        self.tab_manager.tab_updated.connect(self._refresh_tabs)  
        self.tab_manager.tab_deleted.connect(self._refresh_tabs)
        self.tab_manager.auto_archive_triggered.connect(self._show_archive_results)
        
    def _load_settings(self) -> None:
        """Load current settings into UI"""
        self._refresh_tabs()
        self._load_auto_archive_settings()
        self._update_button_states()
        
    def _refresh_tabs(self) -> None:
        """Refresh tab list and related UI components"""
        # Save current selection
        current_tab = None
        current_item = self.tab_list.currentItem()
        if current_item:
            current_tab = current_item.text()
            
        # Clear and repopulate
        self.tab_list.clear()
        
        # Get all tabs including hidden ones
        all_tabs = self.tab_manager.get_all_tabs(include_hidden=True)
        
        for tab in all_tabs:
            item = QListWidgetItem(tab.name)
            
            # Set item properties
            if tab.is_hidden:
                item.setCheckState(Qt.CheckState.Unchecked)
                item.setForeground(QColor("#888888"))  # Gray out hidden tabs
            else:
                item.setCheckState(Qt.CheckState.Checked)
                
            # Add color indicator
            if tab.color_hint:
                item.setBackground(QColor(tab.color_hint))
                
            # System tabs are not deletable
            if tab.tab_type == 'system':
                item.setToolTip(f"System tab - {tab.gallery_count} galleries")
            else:
                item.setToolTip(f"User tab - {tab.gallery_count} galleries")
                
            self.tab_list.addItem(item)
            
        # Update combo boxes
        self._update_tab_combos()
        
        # Update color controls
        self._update_color_controls()
        
        # Restore selection
        if current_tab:
            for i in range(self.tab_list.count()):
                item = self.tab_list.item(i)
                if item and item.text() == current_tab:
                    self.tab_list.setCurrentItem(item)
                    break
                    
    def _update_tab_combos(self) -> None:
        """Update tab selection combo boxes"""
        visible_tabs = self.tab_manager.get_visible_tab_names()
        
        # Update default tab combo
        current_default = self.default_tab_combo.currentText()
        self.default_tab_combo.clear()
        self.default_tab_combo.addItems(visible_tabs)
        if current_default in visible_tabs:
            self.default_tab_combo.setCurrentText(current_default)
            
        # Update startup tab combo
        current_startup = self.startup_tab_combo.currentText()
        self.startup_tab_combo.clear()
        self.startup_tab_combo.addItem("Last Active")
        self.startup_tab_combo.addItems(visible_tabs)
        if current_startup:
            self.startup_tab_combo.setCurrentText(current_startup)
        else:
            self.startup_tab_combo.setCurrentText("Last Active")
            
    def _update_color_controls(self) -> None:
        """Update color customization controls"""
        # Clear existing color controls
        while self.colors_layout.rowCount() > 0:
            self.colors_layout.removeRow(0)
            
        # Add color control for each tab
        for tab in self.tab_manager.get_all_tabs(include_hidden=True):
            if tab.tab_type == 'user':  # Only allow color customization for user tabs
                color_btn = ColorButton(tab.color_hint)
                color_btn.color_changed.connect(
                    lambda color, name=tab.name: self._update_tab_color(name, color)
                )
                self.colors_layout.addRow(f"{tab.name}:", color_btn)
                
    def _load_auto_archive_settings(self) -> None:
        """Load auto-archive settings"""
        enabled, days, statuses = self.tab_manager.get_auto_archive_config()
        
        self.auto_archive_enabled_cb.setChecked(enabled)
        self.auto_archive_days_spin.setValue(days)
        
        self.status_completed_cb.setChecked("completed" in statuses)
        self.status_failed_cb.setChecked("failed" in statuses)
        self.status_incomplete_cb.setChecked("incomplete" in statuses)
        
    def _update_button_states(self) -> None:
        """Update button enabled states based on selection"""
        current_item = self.tab_list.currentItem()
        has_selection = current_item is not None
        
        self.edit_tab_btn.setEnabled(has_selection)
        
        # Only allow deletion of user tabs
        if has_selection:
            tab_info = self.tab_manager.get_tab_by_name(current_item.text())
            can_delete = tab_info and tab_info.tab_type == 'user'
            self.delete_tab_btn.setEnabled(can_delete)
        else:
            self.delete_tab_btn.setEnabled(False)
            
    # ----------------------------- Event Handlers -----------------------------
    
    def _add_tab(self) -> None:
        """Add new tab"""
        name, ok = QInputDialog.getText(self, "Add Tab", "Tab name:")
        if ok and name.strip():
            try:
                self.tab_manager.create_tab(name.strip())
            except ValueError as e:
                QMessageBox.warning(self, "Error", str(e))
                
    def _edit_tab(self) -> None:
        """Edit selected tab"""
        current_item = self.tab_list.currentItem()
        if not current_item:
            return
            
        tab_name = current_item.text()
        tab_info = self.tab_manager.get_tab_by_name(tab_name)
        
        if not tab_info:
            return
            
        # Only allow editing user tabs
        if tab_info.tab_type == 'system':
            QMessageBox.information(self, "Information", "System tabs cannot be renamed.")
            return
            
        new_name, ok = QInputDialog.getText(self, "Edit Tab", "Tab name:", text=tab_name)
        if ok and new_name.strip() and new_name.strip() != tab_name:
            try:
                self.tab_manager.update_tab(tab_name, new_name=new_name.strip())
            except ValueError as e:
                QMessageBox.warning(self, "Error", str(e))
                
    def _delete_tab(self) -> None:
        """Delete selected tab"""
        current_item = self.tab_list.currentItem()
        if not current_item:
            return
            
        tab_name = current_item.text()
        tab_info = self.tab_manager.get_tab_by_name(tab_name)
        
        if not tab_info or tab_info.tab_type == 'system':
            QMessageBox.information(self, "Information", "System tabs cannot be deleted.")
            return
            
        # Confirm deletion
        reply = QMessageBox.question(
            self, "Confirm Deletion",
            f"Delete tab '{tab_name}'?\n\n"
            f"All galleries in this tab will be moved to the Main tab.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                success, moved_count = self.tab_manager.delete_tab(tab_name)
                if success:
                    QMessageBox.information(
                        self, "Tab Deleted",
                        f"Tab '{tab_name}' deleted.\n{moved_count} galleries moved to Main tab."
                    )
            except ValueError as e:
                QMessageBox.warning(self, "Error", str(e))
                
    def _handle_tab_reorder(self, tab_names: List[str]) -> None:
        """Handle tab reordering from drag-and-drop"""
        # Create custom ordering mapping
        order_mapping = {name: i * 10 for i, name in enumerate(tab_names)}
        self.tab_manager.set_custom_tab_order(order_mapping)
        
    def _show_all_tabs(self) -> None:
        """Show all hidden tabs"""
        for i in range(self.tab_list.count()):
            item = self.tab_list.item(i)
            if item and item.checkState() == Qt.CheckState.Unchecked:
                tab_name = item.text()
                self.tab_manager.set_tab_hidden(tab_name, False)
                
        self._refresh_tabs()
        
    def _save_preferences(self) -> None:
        """Save general preferences"""
        # Handle tab visibility changes
        for i in range(self.tab_list.count()):
            item = self.tab_list.item(i)
            if item:
                tab_name = item.text()
                is_hidden = item.checkState() == Qt.CheckState.Unchecked
                self.tab_manager.set_tab_hidden(tab_name, is_hidden)
                
    def _save_startup_tab(self) -> None:
        """Save startup tab preference"""
        startup_tab = self.startup_tab_combo.currentText()
        if startup_tab and startup_tab != "Last Active":
            self.tab_manager.last_active_tab = startup_tab
            
    def _save_auto_archive(self) -> None:
        """Save auto-archive configuration"""
        enabled = self.auto_archive_enabled_cb.isChecked()
        days = self.auto_archive_days_spin.value()
        
        statuses = set()
        if self.status_completed_cb.isChecked():
            statuses.add("completed")
        if self.status_failed_cb.isChecked():
            statuses.add("failed")
        if self.status_incomplete_cb.isChecked():
            statuses.add("incomplete")
            
        self.tab_manager.set_auto_archive_config(enabled, days, statuses)
        
    def _run_manual_archive(self) -> None:
        """Run manual auto-archive operation"""
        candidates = self.tab_manager.check_auto_archive_candidates()
        
        if not candidates:
            QMessageBox.information(
                self, "Auto-Archive",
                "No galleries meet the auto-archive criteria."
            )
            return
            
        reply = QMessageBox.question(
            self, "Confirm Auto-Archive",
            f"Archive {len(candidates)} galleries to the Archive tab?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            moved_count = self.tab_manager.execute_auto_archive()
            QMessageBox.information(
                self, "Auto-Archive Complete",
                f"Moved {moved_count} galleries to Archive tab."
            )
            
    def _update_tab_color(self, tab_name: str, color: str) -> None:
        """Update tab color"""
        try:
            self.tab_manager.update_tab(tab_name, color_hint=color)
        except ValueError as e:
            QMessageBox.warning(self, "Error", str(e))
            
    def _show_archive_results(self, gallery_paths: List[str]) -> None:
        """Show results of auto-archive operation"""
        if gallery_paths:
            QMessageBox.information(
                self, "Auto-Archive Triggered",
                f"Automatically archived {len(gallery_paths)} galleries."
            )
            
    # ----------------------------- Public Interface -----------------------------
    
    def save_settings(self) -> None:
        """Save all current settings (called when dialog is closed)"""
        self._save_preferences()
        self._save_auto_archive()
        
    def validate_settings(self) -> bool:
        """Validate current settings"""
        # Ensure at least one tab is visible
        visible_count = 0
        for i in range(self.tab_list.count()):
            item = self.tab_list.item(i)
            if item and item.checkState() == Qt.CheckState.Checked:
                visible_count += 1
                
        if visible_count == 0:
            QMessageBox.warning(
                self, "Validation Error",
                "At least one tab must be visible."
            )
            return False
            
        return True