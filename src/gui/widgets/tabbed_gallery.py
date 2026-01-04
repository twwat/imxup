#!/usr/bin/env python3
"""
Tabbed Gallery Widget
Provides tab-based organization for gallery queue with filtering and drag-and-drop
"""

import time
from pathlib import Path
from typing import Optional, Set, Dict, List

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTabBar,
    QMessageBox, QInputDialog, QMenu
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QMimeData, QUrl, QPoint, QSettings
from PyQt6.QtGui import (
    QPainter, QColor, QPainterPath, QPen, QDragEnterEvent, 
    QDropEvent, QDragMoveEvent, QDragLeaveEvent, QShortcut, QKeySequence
)

# Import the table widget we extracted
from src.gui.widgets.gallery_table import GalleryTableWidget
from src.utils.logger import log
from src.gui.dialogs.message_factory import show_warning, show_info


class DropEnabledTabBar(QTabBar):
    """Custom tab bar that accepts gallery drops and provides visual feedback"""
    
    # Signal for when galleries are dropped on a tab
    galleries_dropped = pyqtSignal(str, list)  # tab_name, gallery_paths
    # Signal for when tab order changes
    tab_order_changed = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._drag_highlight_index = -1
        # Connect to tab moved signal to enforce "All Tabs" position
        self.tabMoved.connect(self._on_tab_moved)
    
    def _on_tab_moved(self, from_index, to_index):
        """Ensure 'All Tabs' stays at position 0 and save tab order"""
        # If "All Tabs" was moved from position 0, move it back
        if from_index == 0 and self.tabText(to_index).split(' (')[0] == "All Tabs":
            self.moveTab(to_index, 0)
        # If something was moved to position 0 and it's not "All Tabs", find "All Tabs" and move it back
        elif to_index == 0 and self.tabText(0).split(' (')[0] != "All Tabs":
            # Find "All Tabs" and move it to position 0
            for i in range(self.count()):
                if self.tabText(i).split(' (')[0] == "All Tabs":
                    self.moveTab(i, 0)
                    break
        
        # Emit signal that tab order has changed
        self.tab_order_changed.emit()
    
    def dragEnterEvent(self, event):
        """Handle drag enter events"""
        if event.mimeData().hasFormat("application/x-imxup-galleries"):
            event.acceptProposedAction()
            self._update_drag_highlight(event.position().toPoint())
        else:
            super().dragEnterEvent(event)
    
    def dragMoveEvent(self, event):
        """Handle drag move events"""
        if event.mimeData().hasFormat("application/x-imxup-galleries"):
            event.acceptProposedAction()
            self._update_drag_highlight(event.position().toPoint())
        else:
            super().dragMoveEvent(event)
    
    def dragLeaveEvent(self, event):
        """Handle drag leave events"""
        self._clear_drag_highlight()
        super().dragLeaveEvent(event)
    
    def dropEvent(self, event):
        """Handle drop events"""
        if event.mimeData().hasFormat("application/x-imxup-galleries"):
            # Find the tab at drop position
            drop_index = self.tabAt(event.position().toPoint())
            if drop_index >= 0:
                tab_text = self.tabText(drop_index)
                tab_name = tab_text.split(' (')[0] if ' (' in tab_text else tab_text
                
                # Extract gallery paths from mime data
                gallery_data = event.mimeData().data("application/x-imxup-galleries")
                gallery_paths = gallery_data.data().decode('utf-8').split('\n')
                gallery_paths = [path.strip() for path in gallery_paths if path.strip()]
                
                if gallery_paths:
                    self.galleries_dropped.emit(tab_name, gallery_paths)
                    event.acceptProposedAction()
                else:
                    event.ignore()
            else:
                event.ignore()
        else:
            super().dropEvent(event)
        
        self._clear_drag_highlight()
    
    def _update_drag_highlight(self, position):
        """Update visual highlight for drag feedback"""
        new_index = self.tabAt(position)
        if new_index != self._drag_highlight_index:
            self._drag_highlight_index = new_index
            self.update()  # Trigger repaint for visual feedback
    
    def _clear_drag_highlight(self):
        """Clear drag highlight"""
        if self._drag_highlight_index != -1:
            self._drag_highlight_index = -1
            self.update()
    
    def paintEvent(self, event):
        """Custom paint to show drag highlight"""
        super().paintEvent(event)

        # Draw drag highlight if needed
        if self._drag_highlight_index >= 0:
            from PyQt6.QtGui import QPainter, QPen
            painter = QPainter(self)
            if not painter.isActive():
                # QPainter failed to begin - widget not ready for painting
                return
            painter.setPen(QPen(QColor(52, 152, 219), 3))  # Blue highlight

            rect = self.tabRect(self._drag_highlight_index)
            painter.drawRoundedRect(rect.adjusted(2, 2, -2, -2), 4, 4)
            painter.end()


class TabbedGalleryWidget(QWidget):
    """Tabbed gallery widget that provides efficient tab switching while maintaining all table functionality"""
    
    # Signals
    tab_changed = pyqtSignal(str)  # tab_name
    tab_renamed = pyqtSignal(str, str)  # old_name, new_name
    tab_deleted = pyqtSignal(str)  # tab_name
    tab_created = pyqtSignal(str)  # tab_name
    galleries_dropped = pyqtSignal(str, list)  # tab_name, gallery_paths
    
    def __init__(self, parent=None):
        super().__init__(parent)

        # Initialize tab manager reference
        self.tab_manager = None
        self.current_tab = "Main"
        self._restoring_tabs = False  # Flag to prevent saving during tab restoration

        # PER-TAB STATE ISOLATION: Each tab maintains independent state
        self._tab_states = {}  # Dict[tab_name, TabState] - stores per-tab state
        self._saving_state = False  # Flag to prevent recursion during state save/restore

        # Enhanced filter result caching system
        self._filter_cache = {}  # Cache filtered row visibility per tab
        self._filter_cache_timestamps = {}  # Track cache freshness per tab
        self._path_to_tab_cache = {}  # Cache gallery path to tab mappings
        self._cache_version = 0  # Version counter for cache invalidation
        self._cache_ttl = 10.0  # Cache time-to-live in seconds
        
        # Performance monitoring system
        self._perf_metrics = {
            'tab_switches': 0,
            'filter_cache_hits': 0,
            'filter_cache_misses': 0,
            'filter_times': [],  # Track filter performance
            'tab_switch_times': [],  # Track tab switch performance
            'emergency_fallbacks': 0,  # Track when filtering exceeds budget
            'background_updates_processed': 0
        }
        self._perf_start_time = time.time()
        
        self._init_ui()
        self._setup_connections()
    
    def _init_ui(self):
        """Initialize the UI components"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        
        # Tab bar setup with drop support
        self.tab_bar = DropEnabledTabBar()
        self.tab_bar.setTabsClosable(False)  # We'll handle closing via context menu
        self.tab_bar.setMovable(True)  # Allow drag reordering
        self.tab_bar.setExpanding(False)
        self.tab_bar.setUsesScrollButtons(True)
        
        # Add "+" button for new tabs with enhanced styling
        self.new_tab_btn = QPushButton("+")
        self.new_tab_btn.setFixedSize(32, 25)
        self.new_tab_btn.setToolTip("Add new tab (Ctrl+T)")
        self.new_tab_btn.setProperty("class", "new-tab-button")
        
        # Tab bar styling - set after button creation
        self._setup_tab_styling()
        
        # Tab bar container
        tab_container = QHBoxLayout()
        tab_container.setContentsMargins(0, 0, 0, 0)
        tab_container.addWidget(self.tab_bar)
        tab_container.addWidget(self.new_tab_btn)
        tab_container.addStretch()
        
        tab_widget = QWidget()
        tab_widget.setLayout(tab_container)
        
        layout.addWidget(tab_widget)
        
        # Gallery table (reuse existing implementation)
        self.table = GalleryTableWidget()
        layout.addWidget(self.table, 1)  # Give it stretch priority

        # Connect selection changes to auto-save state
        self.table.itemSelectionChanged.connect(self._on_selection_changed)

        # Tabs will be initialized when TabManager is set
        # Don't add hardcoded tabs here
    
    def _setup_connections(self):
        """Setup signal connections"""
        self.tab_bar.currentChanged.connect(self._on_tab_changed)
        self.tab_bar.tabBarDoubleClicked.connect(self._on_tab_double_clicked)
        self.tab_bar.tab_order_changed.connect(self._save_tab_order)
        # Connect tab bar signal to parent's handler (will be connected by parent)
        self.new_tab_btn.clicked.connect(self._add_new_tab)
        
        # Connect tab bar drag-drop signal to own handler for GUI updates
        self.tab_bar.galleries_dropped.connect(self._on_galleries_dropped)
        
        # Context menu for tabs
        self.tab_bar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tab_bar.customContextMenuRequested.connect(self._show_tab_context_menu)
        
        # Setup keyboard shortcuts
        self._setup_keyboard_shortcuts()
        
        # Setup discoverability hints
        self._setup_discoverability_hints()
    
    def set_tab_manager(self, tab_manager):
        """Set the tab manager reference"""
        self.tab_manager = tab_manager
        self._refresh_tabs()
    
    def _refresh_tabs(self):
        """Refresh tabs from tab manager"""
        if not self.tab_manager:
            log(f"No tab manager available for TabbedGalleryWidget", level="warning")
            return

        # Block tab change signals from saving during restoration
        self._restoring_tabs = True

        # Clear existing tabs first
        while self.tab_bar.count() > 0:
            self.tab_bar.removeTab(0)
        
        # Add "All Tabs" first (position 0)
        self.tab_bar.addTab("All Tabs")
        
        # Get tabs from manager
        manager_tabs = self.tab_manager.get_visible_tab_names()
        
        # Restore saved tab order if available
        settings = QSettings()
        saved_order = settings.value("tabs/display_order", [])
        if saved_order and isinstance(saved_order, list):
            # Reorder manager_tabs to match saved order
            ordered_tabs = []
            for name in saved_order:
                if name in manager_tabs:
                    ordered_tabs.append(name)
            # Add any new tabs not in saved order
            for name in manager_tabs:
                if name not in ordered_tabs:
                    ordered_tabs.append(name)
            manager_tabs = ordered_tabs
        
        # Add all tabs from manager after "All Tabs"
        for tab_name in manager_tabs:
                self.tab_bar.addTab(tab_name)
        
        # Set current tab to the last active tab from manager, or Main if none
        if manager_tabs:
            # Try to set to last active tab (add 1 to account for "All Tabs" at position 0)
            last_active = self.tab_manager.last_active_tab
            if last_active in manager_tabs:
                index = manager_tabs.index(last_active) + 1  # +1 for "All Tabs" at position 0
                self.tab_bar.setCurrentIndex(index)
            else:
                # Default to first non-"All Tabs" tab (position 1)
                self.tab_bar.setCurrentIndex(1)
        else:
            # No tabs available, create a default Main tab after "All Tabs"
            log(f"No tabs available, creating default Main tab", level="warning")
            self.tab_bar.addTab("Main")
            self.tab_bar.setCurrentIndex(1)  # Select Main tab, not "All Tabs"
        
        # Update current_tab attribute to match the selected tab
        if self.tab_bar.count() > 0:
            tab_text = self.tab_bar.tabText(self.tab_bar.currentIndex())
            # Extract base tab name (remove count if present)
            base_tab_name = tab_text.split(' (')[0] if ' (' in tab_text else tab_text
            self.current_tab = base_tab_name

        # Update tooltips after refreshing tabs
        self._update_tab_tooltips()

        # Re-enable tab change signal saving after restoration is complete
        self._restoring_tabs = False
    
    def _on_tab_changed(self, index):
        """Handle tab change with performance tracking and state isolation"""
        if index < 0 or index >= self.tab_bar.count():
            return

        # Performance monitoring
        switch_start_time = time.time()

        tab_text = self.tab_bar.tabText(index)
        tab_name = tab_text.split(' (')[0] if ' (' in tab_text else tab_text
        old_tab = self.current_tab

        # CRITICAL: Save state of old tab BEFORE switching
        if old_tab and old_tab != tab_name:
            self._save_tab_state(old_tab)

        self.current_tab = tab_name

        # Invalidate update queue visibility cache when switching tabs
        update_queue = getattr(self.table, '_update_queue', None)
        if update_queue and hasattr(update_queue, 'invalidate_visibility_cache'):
            update_queue.invalidate_visibility_cache()

        # CRITICAL: Restore state FIRST while rows are visible
        self._restore_tab_state(tab_name)

        # Apply filter AFTER restoring state (preserves selections on hidden rows)
        self._apply_filter(tab_name)

        self.tab_changed.emit(tab_name)

        # Update performance metrics
        switch_time = (time.time() - switch_start_time) * 1000
        self._perf_metrics['tab_switches'] += 1
        self._perf_metrics['tab_switch_times'].append(switch_time)

        # Keep only recent measurements
        if len(self._perf_metrics['tab_switch_times']) > 50:
            self._perf_metrics['tab_switch_times'] = self._perf_metrics['tab_switch_times'][-25:]

        # Log slow tab switches
        #if switch_time > 16:
        #    print(f"Slow tab switch from '{old_tab}' to '{tab_name}': {switch_time:.1f}ms")

        # Save active tab to settings (excluding "All Tabs")
        # Don't save during tab restoration to prevent overwriting the saved preference
        if self.tab_manager and tab_name != "All Tabs" and not self._restoring_tabs:
            self.tab_manager.last_active_tab = tab_name
    
    def _save_tab_state(self, tab_name: str):
        """Save current table state for a specific tab"""
        if self._saving_state or not tab_name:
            return

        try:
            self._saving_state = True

            # Capture current state
            state = {
                'scroll_position': self.table.verticalScrollBar().value(),
                'selected_rows': set(),
                'current_row': self.table.currentRow(),
                'horizontal_scroll': self.table.horizontalScrollBar().value()
            }

            # Save selected row indices (only for visible rows in this tab)
            # FIX: Use selectedRows() instead of selectedItems() for proper row-based selection
            selection_model = self.table.selectionModel()
            if selection_model:
                selected_indexes = selection_model.selectedRows()
                for index in selected_indexes:
                    row = index.row()
                    if not self.table.isRowHidden(row):
                        state['selected_rows'].add(row)

            # Store state for this tab
            self._tab_states[tab_name] = state

        finally:
            self._saving_state = False

    def _restore_tab_state(self, tab_name: str):
        """Restore saved state for a specific tab"""
        if self._saving_state or not tab_name:
            return

        try:
            self._saving_state = True

            # Get saved state or create default
            state = self._tab_states.get(tab_name, {
                'scroll_position': 0,
                'selected_rows': set(),
                'current_row': -1,
                'horizontal_scroll': 0
            })

            # Block selection signals during restoration to prevent deselection on Start
            self.table.blockSignals(True)
            try:
                # Clear current selection first
                self.table.clearSelection()

                # Restore multi-selection using QItemSelectionModel for proper batch selection
                # FIX: Build complete selection first, then apply all at once to prevent flickering
                selection_model = self.table.selectionModel()
                if selection_model and state['selected_rows']:
                    from PyQt6.QtCore import QItemSelectionModel, QItemSelection
                    selection = QItemSelection()

                    for row in state['selected_rows']:
                        if row < self.table.rowCount():
                            # Don't check isRowHidden here - restore selections BEFORE filter applies
                            # Build selection range for entire row
                            index_first = self.table.model().index(row, 0)
                            index_last = self.table.model().index(row, self.table.columnCount() - 1)
                            selection.select(index_first, index_last)

                    # Apply all selections at once using ClearAndSelect to replace previous selections
                    selection_model.select(selection, QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows)

                # Restore current row
                if state['current_row'] >= 0 and state['current_row'] < self.table.rowCount():
                    if not self.table.isRowHidden(state['current_row']):
                        self.table.setCurrentCell(state['current_row'], self.table.currentColumn())

            finally:
                self.table.blockSignals(False)

            # Restore scroll positions (after unblocking signals)
            self.table.verticalScrollBar().setValue(state['scroll_position'])
            self.table.horizontalScrollBar().setValue(state['horizontal_scroll'])

        finally:
            self._saving_state = False

    def _on_selection_changed(self):
        """Auto-save selection state when it changes (prevents deselection on Start)"""
        if self._saving_state or self._restoring_tabs:
            return

        # Save state for current tab whenever selection changes
        if self.current_tab:
            # Use a lightweight state update (don't block signals)
            state = self._tab_states.get(self.current_tab, {})
            state['selected_rows'] = set()

            # Only save visible selected rows
            # FIX: Use selectedRows() instead of selectedItems() for proper row-based selection
            selection_model = self.table.selectionModel()
            if selection_model:
                selected_indexes = selection_model.selectedRows()
                for index in selected_indexes:
                    row = index.row()
                    if not self.table.isRowHidden(row):
                        state['selected_rows'].add(row)

            state['current_row'] = self.table.currentRow()
            self._tab_states[self.current_tab] = state

    def _save_tab_order(self):
        """Save current tab bar order to QSettings"""
        order = []
        for i in range(1, self.tab_bar.count()):  # Skip "All Tabs" at position 0
            tab_text = self.tab_bar.tabText(i)
            # Extract base tab name (remove count if present)
            tab_name = tab_text.split(' (')[0] if ' (' in tab_text else tab_text
            order.append(tab_name)
        settings = QSettings()
        settings.setValue("tabs/display_order", order)
    
    def _on_galleries_dropped(self, tab_name, gallery_paths):
        """Handle galleries being dropped on a tab"""
        log(f"_on_galleries_dropped called with tab_name='{tab_name}', {len(gallery_paths)} paths", level="debug")
        if not self.tab_manager or not gallery_paths:
            log(f"Early return - tab_manager={bool(self.tab_manager)}, gallery_paths={len(gallery_paths) if gallery_paths else 0}", level="debug")
            return
        
        try:
            # Move galleries to the target tab (tab_name is already clean from dropEvent)
            moved_count = self.tab_manager.move_galleries_to_tab(gallery_paths, tab_name)
            #print(f"DEBUG: move_galleries_to_tab returned moved_count={moved_count}", flush=True)
            
            # Update queue manager's in-memory items to match database
            #print(f"DEBUG: moved_count={moved_count}, has_queue_manager={hasattr(self, 'queue_manager')}, has_tab_manager={bool(self.tab_manager)}")
            if moved_count > 0 and hasattr(self, 'queue_manager') and self.tab_manager:
                # Get the tab_id for the target tab (same pattern as right-click path)
                tab_info = self.tab_manager.get_tab_by_name(tab_name)
                tab_id = tab_info.id if tab_info else 1

                updated_count = 0
                for path in gallery_paths:
                    item = self.queue_manager.get_item(path)
                    if item:
                        old_tab = item.tab_name
                        item.tab_name = tab_name
                        item.tab_id = tab_id
                        updated_count += 1
                        # Verify the change stuck
                        log(f"Drag-drop updated item {path} tab '{old_tab}' -> '{tab_name}' (item.tab_name is now '{item.tab_name}', tab_id={tab_id})", level="debug", category="ui")
                    else:
                        log(f" [ui] INFO: No item found for path: {path}")
                log(f"Updated {updated_count} in-memory items out of {len(gallery_paths)} paths", level="debug")
                
                # Don't call save_persistent_queue() here - database is already updated
                # and is the source of truth. QueueManager loads from database on startup.
            
            # Invalidate TabManager's cache for affected tabs
            if moved_count > 0:
                self.tab_manager.invalidate_tab_cache()  # Invalidate all tabs
            
            # Refresh the current view to reflect changes
            self.refresh_filter()
            
            # Emit signal to notify main GUI about gallery moves
            if moved_count > 0:
                self.galleries_dropped.emit(tab_name, gallery_paths)
                
                # Optional: Show feedback message
                gallery_word = "gallery" if moved_count == 1 else "galleries"
                log(f"DRAG-DROP PATH - Moved {moved_count} {gallery_word} to '{tab_name}' tab", level="debug", category="ui")
                
        except Exception as e:
            log(f"Error moving galleries to tab '{tab_name}': {e}", level="error")
            
    
    def _apply_filter(self, tab_name):
        """Apply filtering to show only rows belonging to the specified tab with intelligent caching"""
        if not self.tab_manager:
            # No filtering if no tab manager
            log(f"Error: No tab manager available for filtering", level="debug")
            for row in range(self.table.rowCount()):
                self.table.setRowHidden(row, False)
            return
        
        if not tab_name:
            log(f"No tab name specified for filtering", level="debug")
            return
        
        #print(f"Debug: Applying filter for tab: {tab_name}")
        
        start_time = time.time()
        row_count = self.table.rowCount()
        log(f"_apply_filter: rowCount() returned {row_count}", level="trace", category="ui")
        
        if row_count == 0:
            return
        
        # Check if we have a valid cached result
        cache_key = f"{tab_name}_{row_count}_{self._cache_version}"
        current_time = time.time()
        
        if (cache_key in self._filter_cache and 
            tab_name in self._filter_cache_timestamps and
            current_time - self._filter_cache_timestamps[tab_name] < self._cache_ttl):
            # Use cached result for instant filtering
            cached_visibility = self._filter_cache[cache_key]
            for row, should_show in cached_visibility.items():
                self.table.setRowHidden(row, not should_show)
            
            # Notify update queue to invalidate visibility cache
            update_queue = getattr(self.table, '_update_queue', None)
            if update_queue and hasattr(update_queue, 'invalidate_visibility_cache'):
                update_queue.invalidate_visibility_cache()
            
            # Performance tracking - cache hit
            elapsed = (time.time() - start_time) * 1000
            self._perf_metrics['filter_cache_hits'] += 1
            self._perf_metrics['filter_times'].append(elapsed)
            if len(self._perf_metrics['filter_times']) > 100:
                self._perf_metrics['filter_times'] = self._perf_metrics['filter_times'][-50:]
            return
        
        # Get gallery paths for this tab (use cached if available)
        tab_paths_set = self._get_cached_tab_paths(tab_name)
        
        # Performance optimization: batch row visibility changes
        TIME_BUDGET = 0.010  # 10ms budget for filtering (2ms reserved for caching)
        
        # Track visibility changes to batch setRowHidden calls
        visibility_map = {}  # row -> should_show
        
        for row in range(row_count):
            if time.time() - start_time > TIME_BUDGET:
                # Emergency fallback: process remaining rows in next frame
                self._perf_metrics['emergency_fallbacks'] += 1
                QTimer.singleShot(1, lambda: self._continue_filter_with_cache(row, row_count, tab_name, tab_paths_set, cache_key, visibility_map))
                return

            name_item = self.table.item(row, GalleryTableWidget.COL_NAME)
            if name_item:
                path = name_item.data(Qt.ItemDataRole.UserRole)
                if tab_name == "All Tabs":
                    # Special "All Tabs" shows all galleries
                    should_show = True
                else:
                    # Check if in database OR in queue manager with matching tab
                    should_show = path in tab_paths_set
                    if not should_show:
                        # Try to get queue_manager from parent window
                        parent_window = self.window()
                        
                        if hasattr(parent_window, 'queue_manager'):
                            # Also check in-memory items that haven't been saved yet
                            qm = parent_window.queue_manager
                            
                            item = qm.get_item(path)
                            if item:
                                if item.tab_name == tab_name:
                                    should_show = True
                        else:
                            log(f"_apply_filter: parent_window has no queue_manager attribute", level="warning")
                    
                visibility_map[row] = should_show
                self.table.setRowHidden(row, not should_show)
            else:
                # Hide rows without valid path data
                visibility_map[row] = False
                self.table.setRowHidden(row, True)
        
        # Cache the result for future use
        self._filter_cache[cache_key] = visibility_map
        self._filter_cache_timestamps[tab_name] = current_time
        
        # Clean old cache entries periodically
        if len(self._filter_cache) > 20:  # Keep max 20 cached filters
            self._cleanup_filter_cache()
        
        # Notify update queue to invalidate visibility cache
        update_queue = getattr(self.table, '_update_queue', None)
        if update_queue and hasattr(update_queue, 'invalidate_visibility_cache'):
            update_queue.invalidate_visibility_cache()
        
        # Performance tracking - cache miss
        elapsed = (time.time() - start_time) * 1000
        self._perf_metrics['filter_cache_misses'] += 1
        self._perf_metrics['filter_times'].append(elapsed)
        if len(self._perf_metrics['filter_times']) > 100:
            self._perf_metrics['filter_times'] = self._perf_metrics['filter_times'][-50:]
            
    def _continue_filter(self, start_row, total_rows, tab_name, tab_paths_set):
        """Continue filtering from where we left off to avoid blocking main thread"""
        TIME_BUDGET = 0.008  # Smaller budget for continuation
        start_time = time.time()
        
        for row in range(start_row, total_rows):
            if time.time() - start_time > TIME_BUDGET:
                # Schedule next batch if needed
                QTimer.singleShot(1, lambda: self._continue_filter(row, total_rows, tab_name, tab_paths_set))
                return
                
            name_item = self.table.item(row, GalleryTableWidget.COL_NAME)
            if name_item:
                path = name_item.data(Qt.ItemDataRole.UserRole)
                if tab_name == "All Tabs":
                    self.table.setRowHidden(row, False)
                else:
                    should_show = path in tab_paths_set
                    self.table.setRowHidden(row, not should_show)
            else:
                self.table.setRowHidden(row, True)
                
    def _get_cached_tab_paths(self, tab_name):
        """Get tab paths - CACHING DISABLED FOR DEBUGGING"""
        # Special case for "All Tabs" - return empty set to show all
        if tab_name == "All Tabs":
            return set()
        
        if not self.tab_manager:
            log(f"No tab manager available for loading tab galleries", level="warning")
            return set()
        
        # CACHING DISABLED - always load fresh from database
        try:
            tab_galleries = self.tab_manager.load_tab_galleries(tab_name)
            tab_paths_set = {gallery.get('path') for gallery in tab_galleries if gallery.get('path')}
            #print(f"Debug: Loaded {len(tab_paths_set)} galleries for tab '{tab_name}' (NO CACHE)")
        except Exception as e:
            log(f"Error loading galleries for tab '{tab_name}': {e}", level="error")
            tab_paths_set = set()
        
        return tab_paths_set
        
    def _continue_filter_with_cache(self, start_row, total_rows, tab_name, tab_paths_set, cache_key, visibility_map):
        """Continue filtering with caching support"""
        TIME_BUDGET = 0.006  # Smaller budget for continuation
        start_time = time.time()
        
        for row in range(start_row, total_rows):
            if time.time() - start_time > TIME_BUDGET:
                # Schedule next batch if needed
                QTimer.singleShot(1, lambda: self._continue_filter_with_cache(row, total_rows, tab_name, tab_paths_set, cache_key, visibility_map))
                return
                
            name_item = self.table.item(row, GalleryTableWidget.COL_NAME)
            if name_item:
                path = name_item.data(Qt.ItemDataRole.UserRole)
                if tab_name == "All Tabs":
                    should_show = True
                else:
                    should_show = path in tab_paths_set
                    
                visibility_map[row] = should_show
                self.table.setRowHidden(row, not should_show)
            else:
                visibility_map[row] = False
                self.table.setRowHidden(row, True)
        
        # Cache the completed result
        self._filter_cache[cache_key] = visibility_map
        self._filter_cache_timestamps[tab_name] = time.time()
        
    def _cleanup_filter_cache(self):
        """Clean up old filter cache entries"""
        current_time = time.time()
        
        # Remove expired entries
        expired_keys = []
        for cache_key in self._filter_cache:
            # Extract tab name from cache key
            tab_name = cache_key.split('_')[0]
            if (tab_name in self._filter_cache_timestamps and
                current_time - self._filter_cache_timestamps[tab_name] > self._cache_ttl):
                expired_keys.append(cache_key)
        
        for key in expired_keys:
            self._filter_cache.pop(key, None)
            
        # Also clean path cache
        expired_path_keys = []
        for cache_key in self._path_to_tab_cache:
            tab_name = cache_key.split('_')[0]
            if (tab_name in self._filter_cache_timestamps and
                current_time - self._filter_cache_timestamps[tab_name] > self._cache_ttl):
                expired_path_keys.append(cache_key)
                
        for key in expired_path_keys:
            self._path_to_tab_cache.pop(key, None)
    
    def invalidate_filter_cache(self, tab_name=None):
        """Invalidate filter cache for specific tab or all tabs"""
        if tab_name:
            # Remove specific tab entries
            keys_to_remove = [key for key in self._filter_cache if key.startswith(f"{tab_name}_")]
            for key in keys_to_remove:
                self._filter_cache.pop(key, None)
            self._filter_cache_timestamps.pop(tab_name, None)
            
            path_keys_to_remove = [key for key in self._path_to_tab_cache if key.startswith(f"{tab_name}_")]
            for key in path_keys_to_remove:
                self._path_to_tab_cache.pop(key, None)
        else:
            # Clear all caches
            self._filter_cache.clear()
            self._filter_cache_timestamps.clear()
            self._path_to_tab_cache.clear()
            self._cache_version += 1  # Increment version to invalidate all cache keys
    
    def get_performance_metrics(self):
        """Get performance metrics summary for tabbed interface"""
        uptime = time.time() - self._perf_start_time
        
        metrics = {
            'uptime_seconds': uptime,
            'tab_switches_total': self._perf_metrics['tab_switches'],
            'tab_switches_per_minute': (self._perf_metrics['tab_switches'] / uptime * 60) if uptime > 0 else 0,
            'cache_hit_rate': (
                self._perf_metrics['filter_cache_hits'] / 
                max(1, self._perf_metrics['filter_cache_hits'] + self._perf_metrics['filter_cache_misses'])
            ),
            'emergency_fallbacks': self._perf_metrics['emergency_fallbacks'],
            'background_updates_processed': self._perf_metrics['background_updates_processed']
        }
        
        # Calculate average times
        if self._perf_metrics['tab_switch_times']:
            metrics['avg_tab_switch_ms'] = sum(self._perf_metrics['tab_switch_times']) / len(self._perf_metrics['tab_switch_times'])
            metrics['max_tab_switch_ms'] = max(self._perf_metrics['tab_switch_times'])
        else:
            metrics['avg_tab_switch_ms'] = 0
            metrics['max_tab_switch_ms'] = 0
            
        if self._perf_metrics['filter_times']:
            metrics['avg_filter_ms'] = sum(self._perf_metrics['filter_times']) / len(self._perf_metrics['filter_times'])
            metrics['max_filter_ms'] = max(self._perf_metrics['filter_times'])
        else:
            metrics['avg_filter_ms'] = 0
            metrics['max_filter_ms'] = 0
            
        return metrics
    
    def log_performance_summary(self):
        """Log a performance summary to console"""
        metrics = self.get_performance_metrics()
        print("\n=== Tabbed Interface Performance Summary ===")
        print(f"Uptime: {metrics['uptime_seconds']:.1f}s")
        print(f"Tab switches: {metrics['tab_switches_total']} ({metrics['tab_switches_per_minute']:.1f}/min)")
        print(f"Cache hit rate: {metrics['cache_hit_rate']:.1%}")
        print(f"Avg tab switch time: {metrics['avg_tab_switch_ms']:.1f}ms")
        print(f"Max tab switch time: {metrics['max_tab_switch_ms']:.1f}ms")
        print(f"Avg filter time: {metrics['avg_filter_ms']:.1f}ms")
        print(f"Max filter time: {metrics['max_filter_ms']:.1f}ms")
        print(f"Emergency fallbacks: {metrics['emergency_fallbacks']}")
        print(f"Background updates: {metrics['background_updates_processed']}")
        print("============================================\n")
    
    def _on_tab_double_clicked(self, index):
        """Handle tab double-click for renaming"""
        if index < 0 or index >= self.tab_bar.count():
            return
        
        current_text = self.tab_bar.tabText(index)
        current_name = current_text.split(' (')[0] if ' (' in current_text else current_text
        if current_name in ["Main", "All Tabs"]:
            return  # Don't allow renaming system tabs
        
        from PyQt6.QtWidgets import QInputDialog
        new_name, ok = QInputDialog.getText(
            self, 
            "Rename Tab", 
            "Enter new tab name:", 
            text=current_name
        )
        
        if ok and new_name.strip() and new_name.strip() != current_name:
            new_name = new_name.strip()
            if self._is_valid_tab_name(new_name):
                self._rename_tab(index, current_name, new_name)
    
    def _add_new_tab(self):
        """Add a new tab"""
        from PyQt6.QtWidgets import QInputDialog
        tab_name, ok = QInputDialog.getText(
            self, 
            "New Tab", 
            "Enter tab name:"
        )
        
        if ok and tab_name.strip():
            tab_name = tab_name.strip()
            if self._is_valid_tab_name(tab_name):
                self.tab_bar.addTab(tab_name)
                new_index = self.tab_bar.count() - 1
                self.tab_bar.setCurrentIndex(new_index)
                
                # Create tab in manager
                if self.tab_manager:
                    self.tab_manager.create_tab(tab_name)
                
                self.tab_created.emit(tab_name)
                self._update_tab_tooltips()
    
    def _is_valid_tab_name(self, name):
        """Check if tab name is valid and unique"""
        if not name or name.strip() != name:
            return False
        
        # Check for duplicates
        for i in range(self.tab_bar.count()):
            tab_text = self.tab_bar.tabText(i)
            # Extract base tab name (remove count if present)
            base_tab_name = tab_text.split(' (')[0] if ' (' in tab_text else tab_text
            if base_tab_name == name:
                return False
        
        return True
    
    def _rename_tab(self, index, old_name, new_name):
        """Rename a tab"""
        self.tab_bar.setTabText(index, new_name)
        
        # Update in manager
        if self.tab_manager:
            self.tab_manager.rename_tab(old_name, new_name)
        
        if self.current_tab == old_name:
            self.current_tab = new_name
        
        self.tab_renamed.emit(old_name, new_name)
        self._update_tab_tooltips()
    
    def _show_tab_context_menu(self, position):
        """Show enhanced context menu for tab bar"""
        index = self.tab_bar.tabAt(position)
        if index < 0:
            # Clicked on empty area - show general options
            self._show_general_tab_menu(position)
            return
        
        tab_text = self.tab_bar.tabText(index)
        tab_name = tab_text.split(' (')[0] if ' (' in tab_text else tab_text
        self._show_specific_tab_menu(position, index, tab_name)
    
    def _show_general_tab_menu(self, position):
        """Show context menu for empty tab bar area"""
        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtGui import QIcon
        
        menu = QMenu()
        menu.setTitle("Tab Options")
        
        # New tab option
        new_tab_action = menu.addAction("New Tab")
        new_tab_action.setShortcut("Ctrl+T")
        new_tab_action.triggered.connect(self._add_new_tab)
        
        menu.addSeparator()
        
        # Tab management options
        if self.tab_bar.count() > 1:  # Only show if there are user tabs
            organize_menu = menu.addMenu("Organize Tabs")
            
            sort_action = organize_menu.addAction("Sort Alphabetically")
            sort_action.triggered.connect(self._sort_tabs_alphabetically)
            
            close_all_action = organize_menu.addAction("Close All Tabs (except Main)")
            close_all_action.triggered.connect(self._close_all_user_tabs)
        
        global_pos = self.tab_bar.mapToGlobal(position)
        menu.exec(global_pos)
    
    def _show_specific_tab_menu(self, position, index, tab_name):
        """Show context menu for specific tab"""
        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtGui import QIcon
        
        menu = QMenu()
        menu.setTitle(f"Tab: {tab_name}")
        
        # Extract base tab name (remove count if present)
        base_tab_name = tab_name.split(' (')[0] if ' (' in tab_name else tab_name
        
        # Get gallery count for this tab
        gallery_count = 0
        if self.tab_manager and base_tab_name not in ["Main", "All Tabs"]:
            galleries = self.tab_manager.load_tab_galleries(base_tab_name)
            gallery_count = len(galleries)
        elif base_tab_name == "Main":
            if self.tab_manager:
                galleries = self.tab_manager.load_tab_galleries("Main")
                gallery_count = len(galleries)
            else:
                gallery_count = 0
        elif base_tab_name == "All Tabs":
            gallery_count = self.table.rowCount()
        
        # Add tab info at top
        info_action = menu.addAction(f"{gallery_count} galleries")
        info_action.setEnabled(False)
        menu.addSeparator()
        
        if base_tab_name not in ["Main", "All Tabs"]:  # Don't allow operations on Main tab or All Tabs
            # Primary actions
            rename_action = menu.addAction("Rename Tab")
            rename_action.setShortcut("F2")
            rename_action.triggered.connect(lambda: self._on_tab_double_clicked(index))
            
            #duplicate_action = menu.addAction("Duplicate Tab")
            #duplicate_action.triggered.connect(lambda: self._duplicate_tab(base_tab_name))
            
            menu.addSeparator()
            
            # Merge options (if other tabs exist)
            other_tabs = [self.tab_bar.tabText(i).split(' (')[0] for i in range(self.tab_bar.count()) 
                         if i != index and self.tab_bar.tabText(i).split(' (')[0] != "All Tabs"]
            
            if other_tabs:
                merge_menu = menu.addMenu("Merge Into...")
                for other_tab in other_tabs:
                    merge_action = merge_menu.addAction(other_tab)
                    merge_action.triggered.connect(
                        lambda checked, target=other_tab: self._merge_tabs(base_tab_name, target)
                    )
                menu.addSeparator()
            
            # Dangerous actions at bottom
            delete_action = menu.addAction("Delete Tab...")
            delete_action.setShortcut("Ctrl+W")
            if gallery_count > 0:
                delete_action.setText(f"Delete Tab... ({gallery_count} galleries will move to Main)")
            delete_action.triggered.connect(lambda: self._delete_tab_with_confirmation(index, base_tab_name, gallery_count))
        
        elif base_tab_name == "Main":
            # Main tab specific options
            if self.tab_bar.count() > 2:  # Account for All Tabs
                clear_action = menu.addAction("Move All Galleries to Other Tabs...")
                clear_action.triggered.connect(self._move_all_from_main)
        
        elif base_tab_name == "All Tabs":
            # All Tabs has no special operations
            pass
        
        global_pos = self.tab_bar.mapToGlobal(position)
        menu.exec(global_pos)
    
    def _delete_tab(self, index, tab_name):
        """Delete a tab (legacy method - use _delete_tab_with_confirmation)"""
        # Calculate gallery count for confirmation
        gallery_count = 0
        if self.tab_manager:
            galleries = self.tab_manager.load_tab_galleries(tab_name)
            gallery_count = len(galleries)
        
        self._delete_tab_with_confirmation(index, tab_name, gallery_count)
    
    def _merge_tabs(self, source_tab, target_tab):
        """Merge source tab into target tab"""
        from PyQt6.QtWidgets import QMessageBox
        
        reply = QMessageBox.question(
            self,
            "Merge Tabs",
            f"Merge '{source_tab}' into '{target_tab}'?\n\n"
            "All galleries will be moved and the source tab will be deleted.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes and self.tab_manager:
            # Move all galleries from source to target
            tab_galleries = self.tab_manager.load_tab_galleries(source_tab)
            if tab_galleries:
                for gallery in tab_galleries:
                    gallery_path = gallery.get('path')
                    if gallery_path:
                        self.tab_manager.move_galleries_to_tab([gallery_path], target_tab)
            
            # Delete source tab
            source_index = self._find_tab_index(source_tab)
            if source_index >= 0:
                self._delete_tab(source_index, source_tab)

    def refresh_filter(self):
        """Refresh the current filter (call after gallery assignments change)"""
        if not self.current_tab:
            log("Warning: No current tab set for filter refresh", level="warning")
            return

        # Invalidate cache first to ensure fresh data after gallery moves
        self.invalidate_filter_cache()
        self._apply_filter(self.current_tab)
        # Force table to update display immediately
        self.table.update()
        self.table.repaint()
        # Update tooltips when gallery assignments change
        self._update_tab_tooltips()
    
    def assign_gallery_to_current_tab(self, gallery_path):
        """Assign a gallery to the currently active tab"""
        if self.tab_manager and self.current_tab not in ["All Tabs"]:
            moved_count = self.tab_manager.move_galleries_to_tab([gallery_path], self.current_tab)
            if moved_count > 0:
                # Update queue manager's in-memory items to match database
                if hasattr(self, 'queue_manager'):
                    # Get the tab_id for the current tab
                    tab_info = self.tab_manager.get_tab_by_name(self.current_tab)
                    tab_id = tab_info.id if tab_info else 1
                    
                    item = self.queue_manager.get_item(gallery_path)
                    if item:
                        item.tab_name = self.current_tab
                        item.tab_id = tab_id
                
                self.tab_manager.invalidate_tab_cache()
            self.refresh_filter()
    
    def get_current_tab(self):
        """Get the name of the currently active tab"""
        return self.current_tab
    
    def switch_to_tab(self, tab_name):
        """Switch to a specific tab"""
        index = self._find_tab_index(tab_name)
        if index >= 0:
            self.tab_bar.setCurrentIndex(index)
    
    def _setup_tab_styling(self, theme_mode='dark'):
        """Setup special tab data attributes not handled by styles.qss"""

        # Only apply special data attribute styling - main styling comes from styles.qss
        special_style = """
            QTabBar::tab[data-tab-type="system"] {
                font-style: italic;
            }
            QTabBar::tab[data-modified="true"] {
                color: %s;
            }
            QTabBar::tab[data-drag-highlight="true"] {
                border: 2px solid #3498db;
                background: %s;
            }
        """ % (
            "#f39c12" if theme_mode == 'dark' else "#e67e22",  # modified color
            "#404040" if theme_mode == 'dark' else "#e3f2fd"   # drag highlight background
        )

        self.tab_bar.setStyleSheet(special_style)
        self._update_new_tab_button_style(theme_mode == 'dark')
    
    def _update_new_tab_button_style(self, is_dark=False):
        """Update the new tab button styling to match current theme"""
        # Force style update to apply theme from styles.qss
        style = self.new_tab_btn.style()
        if style:
            style.polish(self.new_tab_btn)
    
    def update_theme(self):
        """Update tab styling when theme changes"""
        self._setup_tab_styling()
    
    def _setup_keyboard_shortcuts(self):
        """Setup keyboard shortcuts for tab operations"""
        from PyQt6.QtGui import QShortcut, QKeySequence
        
        # Ctrl+T: New tab
        new_tab_shortcut = QShortcut(QKeySequence("Ctrl+T"), self)
        new_tab_shortcut.activated.connect(self._add_new_tab)
        
        # Ctrl+W: Close current tab (if not Main)
        close_tab_shortcut = QShortcut(QKeySequence("Ctrl+W"), self)
        close_tab_shortcut.activated.connect(self._close_current_tab)
        
        # Ctrl+Tab / Ctrl+Shift+Tab: Switch between tabs
        next_tab_shortcut = QShortcut(QKeySequence("Ctrl+Tab"), self)
        next_tab_shortcut.activated.connect(self._next_tab)
        
        prev_tab_shortcut = QShortcut(QKeySequence("Ctrl+Shift+Tab"), self)
        prev_tab_shortcut.activated.connect(self._prev_tab)
        
        # F2: Rename selected gallery
        rename_shortcut = QShortcut(QKeySequence("F2"), self)
        rename_shortcut.activated.connect(self._rename_selected_gallery)

        # Ctrl+,: Open Comprehensive Settings
        settings_shortcut = QShortcut(QKeySequence("Ctrl+,"), self)
        settings_shortcut.activated.connect(self._open_settings_from_shortcut)

        # Ctrl+.: Show keyboard shortcuts help
        help_shortcuts_shortcut = QShortcut(QKeySequence("Ctrl+."), self)
        help_shortcuts_shortcut.activated.connect(self._show_help_from_shortcut)
    
    def _setup_discoverability_hints(self):
        """Setup visual hints for tab operations"""
        # Update tab bar to show double-click hint
        self.tab_bar.setWhatsThis(
            "Double-click any tab to rename it.\n"
            "Right-click for more options.\n"
            "Drag tabs to reorder them."
        )
        
        # Enhanced tooltip for Main tab
        self._update_tab_tooltips()
    
    def _update_tab_tooltips(self):
        """Update tooltips and tab text with gallery counts for all tabs"""
        # Removed traceback debug output
        
        # Prevent recursive calls completely - return immediately if called again
        if hasattr(self, '_updating_tooltips') and self._updating_tooltips:
            log(f"_update_tab_tooltips already running, skipping recursion", level="debug")
            return
        
        # Block ALL calls during initialization to prevent infinite loops
        if hasattr(self, '_initializing') and self._initializing:
            log("Still initializing, skipping _update_tab_tooltips", level="debug")
            return
        
        self._updating_tooltips = True
        try:
            for i in range(self.tab_bar.count()):
                current_text = self.tab_bar.tabText(i)
                # Extract base tab name (remove count if present)
                base_name = current_text.split(' (')[0] if ' (' in current_text else current_text
            
                if base_name == "All Tabs":
                    total_galleries = self.table.rowCount() if hasattr(self, 'table') else 0
                    # Update tab text with count
                    self.tab_bar.setTabText(i, f"All Tabs ({total_galleries})")
                    self.tab_bar.setTabToolTip(i, 
                        f"All Tabs shows all galleries ({total_galleries} total)\n"
                        "This tab cannot be modified"
                    )
                else:
                    gallery_count = 0
                    active_count = 0
                    if self.tab_manager and base_name != "All Tabs":
                        # Count from in-memory queue_manager instead of database
                        # This ensures counts match what's actually displayed in the table
                        parent_window = self.parent()
                        while parent_window and not hasattr(parent_window, 'queue_manager'):
                            parent_window = parent_window.parent()

                        if parent_window and hasattr(parent_window, 'queue_manager'):
                            # Count items in memory that belong to this tab
                            all_items = parent_window.queue_manager.get_all_items()
                            gallery_count = sum(1 for item in all_items if item.tab_name == base_name)
                            # Count active uploads
                            active_count = sum(1 for item in all_items
                                             if item.tab_name == base_name
                                             and item.status in ['uploading', 'pending'])
                        else:
                            # Fallback to database if queue_manager not accessible
                            galleries = self.tab_manager.load_tab_galleries(base_name)
                            gallery_count = len(galleries)
                            active_count = sum(1 for g in galleries if g.get('status') in ['uploading', 'pending'])
                    
                    # Update tab text with count
                    old_text = self.tab_bar.tabText(i)
                    new_text = f"{base_name} ({gallery_count})"
                    if old_text != new_text:  # Only update if changed
                        self.tab_bar.setTabText(i, new_text)
                
                    status_text = ""
                    if active_count > 0:
                        status_text = f" ({active_count} active)"
                
                    if base_name == "Main":
                        self.tab_bar.setTabToolTip(i, 
                            f"Main tab ({gallery_count} galleries{status_text})\n"
                            "Right-click for options"
                        )
                    else:
                        self.tab_bar.setTabToolTip(i,
                            f"{base_name} ({gallery_count} galleries{status_text})\n"
                            "Double-click to rename\n"
                            "Right-click for options\n"
                            "Drag to reorder"
                        )
                
                    # Update tab visual state based on content
                    self._update_tab_visual_state(i, base_name, gallery_count, active_count)
        finally:
            self._updating_tooltips = False
    
    def _update_tab_visual_state(self, tab_index, tab_name, gallery_count, active_count):
        """Update visual state of a tab based on its content"""
        # This could set different styling based on tab state
        # For now, we'll use the standard styling but this allows future enhancements
        # like colored indicators for tabs with active uploads, etc.
        
        # Example: Could add different styling for:
        # - Empty tabs (gallery_count == 0)
        # - Active upload tabs (active_count > 0)
        # - System vs user tabs
        # - Recently modified tabs
        
        # For now, just ensure proper styling is applied
        pass
    
    def _close_current_tab(self):
        """Close the current tab via keyboard shortcut"""
        current_index = self.tab_bar.currentIndex()
        tab_name = self.tab_bar.tabText(current_index)
        # Extract base tab name (remove count if present)
        base_name = tab_name.split(' (')[0] if ' (' in tab_name else tab_name
        if base_name != "Main":
            self._delete_tab(current_index, base_name)
    
    def _next_tab(self):
        """Switch to next tab"""
        current = self.tab_bar.currentIndex()
        next_index = (current + 1) % self.tab_bar.count()
        self.tab_bar.setCurrentIndex(next_index)
    
    def _prev_tab(self):
        """Switch to previous tab"""
        current = self.tab_bar.currentIndex()
        prev_index = (current - 1) % self.tab_bar.count()
        self.tab_bar.setCurrentIndex(prev_index)
    
    def _rename_current_tab(self):
        """Rename current tab via keyboard shortcut"""
        current_index = self.tab_bar.currentIndex()
        if current_index >= 0:
            self._on_tab_double_clicked(current_index)

    def _rename_selected_gallery(self):
        """Rename selected gallery via F2 shortcut"""
        # Get the current gallery table
        table_widget = None

        """Rename selected gallery via F2 shortcut"""
        # Since we ARE the TabbedGalleryWidget, directly access our table
        table_widget = self.table

        if not table_widget:
            return

        # Get currently selected row
        current_row = table_widget.currentRow()
        if current_row < 0:
            return

        # Get the path from the name column (column 1) like the context menu does
        name_item = table_widget.item(current_row, GalleryTableWidget.COL_NAME)
        if not name_item:
            return

        path = name_item.data(Qt.ItemDataRole.UserRole)
        if path:
            table_widget.rename_gallery(path)
























    def _open_settings_from_shortcut(self):
        """Open comprehensive settings via Ctrl+, shortcut"""
        # Find the main window by traversing up the widget hierarchy
        widget = self
        while widget and not hasattr(widget, 'open_comprehensive_settings'):
            widget = widget.parent()

        if widget and hasattr(widget, 'open_comprehensive_settings'):
            widget.open_comprehensive_settings()

    def _show_help_from_shortcut(self):
        """Show keyboard shortcuts help via Ctrl+. shortcut"""
        # Find the main window by traversing up the widget hierarchy
        widget = self
        while widget and not hasattr(widget, 'show_help_shortcuts_tab'):
            widget = widget.parent()

        if widget and hasattr(widget, 'show_help_shortcuts_tab'):
            widget.show_help_shortcuts_tab()

    def _sort_tabs_alphabetically(self):
        """Sort user tabs alphabetically (excluding All Tabs and Main)"""
        # Get all tab names except system tabs
        tab_names = []
        for i in range(self.tab_bar.count()):
            name = self.tab_bar.tabText(i)
            # Extract base tab name (remove count if present)
            base_name = name.split(' (')[0] if ' (' in name else name
            if base_name not in ["All Tabs", "Main"]:
                tab_names.append(name)
        
        if len(tab_names) <= 1:
            return
        
        # Sort alphabetically
        tab_names.sort()
        
        # Rebuild tab bar with sorted order
        current_tab = self.current_tab
        
        # Remove all non-system tabs (preserve All Tabs and Main)
        for i in range(self.tab_bar.count() - 1, -1, -1):
            tab_text = self.tab_bar.tabText(i)
            # Extract base tab name (remove count if present)
            base_name = tab_text.split(' (')[0] if ' (' in tab_text else tab_text
            if base_name not in ["All Tabs", "Main"]:
                self.tab_bar.removeTab(i)
        
        # Add sorted tabs
        for name in tab_names:
            self.tab_bar.addTab(name)
        
        # Restore current tab selection
        if current_tab in tab_names:
            self.switch_to_tab(current_tab)
        
        self._update_tab_tooltips()
    
    def _find_tab_index(self, tab_name):
        """Find the index of a tab by name"""
        for i in range(self.tab_bar.count()):
            tab_text = self.tab_bar.tabText(i)
            base_name = tab_text.split(' (')[0] if ' (' in tab_text else tab_text
            if base_name == tab_name:
                return i
        return -1
    
    def _close_all_user_tabs(self):
        """Close all user tabs, keeping only system tabs (All Tabs and Main)"""
        from PyQt6.QtWidgets import QMessageBox
        
        user_tabs = []
        for i in range(self.tab_bar.count()):
            tab_text = self.tab_bar.tabText(i)
            # Extract base tab name (remove count if present)
            base_name = tab_text.split(' (')[0] if ' (' in tab_text else tab_text
            if base_name not in ["All Tabs", "Main"]:
                user_tabs.append(tab_text)
        
        if not user_tabs:
            return
        
        reply = QMessageBox.question(
            self,
            "Close All Tabs",
            f"Are you sure you want to close all {len(user_tabs)} user tabs?\n"
            "All galleries will be moved to the Main tab.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            # Close tabs in reverse order to maintain indices
            for i in range(self.tab_bar.count() - 1, -1, -1):
                tab_name = self.tab_bar.tabText(i)
                # Extract base tab name (remove count if present)
                base_name = tab_name.split(' (')[0] if ' (' in tab_name else tab_name
                if base_name not in ["All Tabs", "Main"]:
                    self._delete_tab_without_confirmation(i, tab_name)
            
            # Switch to Main tab (position 1, since All Tabs is at position 0)
            main_index = self._find_tab_index("Main")
            if main_index >= 0:
                self.tab_bar.setCurrentIndex(main_index)
            self._update_tab_tooltips()
    
    def _move_all_from_main(self):
        """Move all galleries from Main tab to other tabs"""
        # This would open a dialog to distribute galleries
        # Implementation would depend on specific requirements
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.information(
            self,
            "Feature Not Implemented",
            "Gallery distribution feature is not yet implemented."
        )
    
    def _delete_tab_with_confirmation(self, index, tab_name, gallery_count):
        """Delete tab with appropriate confirmation dialog"""
        from PyQt6.QtWidgets import QMessageBox
        
        if gallery_count > 0:
            reply = QMessageBox.question(
                self,
                "Delete Tab",
                f"Are you sure you want to delete the '{tab_name}' tab?\n\n"
                f"{gallery_count} galleries will be moved to the Main tab.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
        else:
            reply = QMessageBox.question(
                self,
                "Delete Tab",
                f"Are you sure you want to delete the '{tab_name}' tab?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
        
        if reply == QMessageBox.StandardButton.Yes:
            self._delete_tab_without_confirmation(index, tab_name)
    
    def _delete_tab_without_confirmation(self, index, tab_name):
        """Delete tab without confirmation (for internal use)"""
        # Move galleries to Main tab if tab manager exists
        if self.tab_manager:
            galleries = self.tab_manager.load_tab_galleries(tab_name)
            if galleries:
                gallery_paths = [g.get('path') for g in galleries if g.get('path')]
                self.tab_manager.move_galleries_to_tab(gallery_paths, "Main")
            
            # Delete tab from manager
            self.tab_manager.delete_tab(tab_name)
        
        # Remove tab from UI
        self.tab_bar.removeTab(index)
        
        # Emit signal
        self.tab_deleted.emit(tab_name)
        
        # Update tooltips
        self._update_tab_tooltips()
        
        # Refresh current filter
        self.refresh_filter()
    
    # Delegate table methods to maintain compatibility
    def __getattr__(self, name):
        """Delegate unknown attributes to the gallery table"""
        # Avoid recursion during initialization by checking __dict__ directly
        if 'table' in self.__dict__ and hasattr(self.table, name):
            return getattr(self.table, name)
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")

