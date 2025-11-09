"""
Context menu helper for gallery table operations.
Helps organize context menu functionality to avoid bloating main_window.py.
"""

from PyQt6.QtWidgets import QMenu
from PyQt6.QtCore import QObject, pyqtSignal, Qt, QMutexLocker


class GalleryContextMenuHelper(QObject):
    """Helper class for managing gallery table context menu operations"""
    
    # Signals for communicating with main window
    template_change_requested = pyqtSignal(list, str)  # paths, template_name
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = None
    
    def set_main_window(self, main_window):
        """Set reference to main window for accessing queue manager, etc."""
        self.main_window = main_window
    
    def create_context_menu(self, position, selected_paths):
        """Create and return the complete context menu"""
        menu = QMenu()
        
        if selected_paths:
            # Add all menu items for selected galleries
            self._add_action_items(menu, selected_paths)
            self._add_file_operations(menu, selected_paths)
            self._add_status_operations(menu, selected_paths)
            self._add_template_submenu(menu, selected_paths)
            self._add_move_to_submenu(menu, selected_paths)
        else:
            # No selection: offer Add Folders
            self._add_no_selection_items(menu)
        
        return menu
    
    def show_context_menu_for_table(self, table_widget, position):
        """Show context menu for a specific table widget"""
        from PyQt6.QtCore import Qt
        
        # Position is already in viewport coordinates
        viewport_pos = position
        global_pos = table_widget.viewport().mapToGlobal(position)

        # Select row under cursor if not already selected using model index for reliability
        index = table_widget.indexAt(viewport_pos)
        if index.isValid():
            row = index.row()
            if row != table_widget.currentRow():
                table_widget.clearSelection()
                table_widget.selectRow(row)
        
        # Build selected rows robustly via selection model (target column 1)
        selected_paths = []
        sel_model = table_widget.selectionModel()
        if sel_model is not None:
            for idx in sel_model.selectedRows(1):
                row = idx.row()
                name_item = table_widget.item(row, 1)
                if name_item:
                    path = name_item.data(Qt.ItemDataRole.UserRole)
                    if path:
                        selected_paths.append(path)

        # Create and show the context menu
        menu = self.create_context_menu(position, selected_paths)
        
        # Only show menu if there are actions
        if menu.actions():
            menu.exec(global_pos)
    
    def _add_action_items(self, menu, selected_paths):
        """Add start/delete/cancel actions"""
        if not self.main_window:
            return
            
        # Start Selected
        can_start_any = self._check_can_start(selected_paths)
        start_action = menu.addAction("Start Selected")
        start_action.setEnabled(can_start_any)
        start_action.triggered.connect(lambda: self._delegate_to_main_window('start_selected_via_menu'))
        
        # Delete
        delete_action = menu.addAction("Delete Selected")
        delete_action.triggered.connect(lambda: self._delegate_to_main_window('delete_selected_via_menu'))
        
        # Cancel (for queued items)
        queued_paths = self._get_paths_by_status(selected_paths, "queued")
        if queued_paths:
            cancel_action = menu.addAction("Cancel Upload")
            cancel_action.triggered.connect(lambda: self._delegate_to_main_window('cancel_selected_via_menu', queued_paths))
    
    def _add_file_operations(self, menu, selected_paths):
        """Add file operation actions"""
        if not self.main_window:
            return
            
        # Open Folder
        open_action = menu.addAction("Open Folder")
        open_action.triggered.connect(lambda: self._delegate_to_main_window('open_folders_via_menu', selected_paths))
        
        # Manage Files (single selection only)
        if len(selected_paths) == 1:
            manage_files_action = menu.addAction("Manage Files...")
            manage_files_action.triggered.connect(lambda: self._delegate_to_main_window('manage_gallery_files', selected_paths[0]))

            # Rename Gallery (single selection only)
            rename_action = menu.addAction("✏️ Rename Gallery")
            rename_action.triggered.connect(lambda: self._delegate_to_main_window('rename_gallery', selected_paths[0]))
    
    def _add_status_operations(self, menu, selected_paths):
        """Add retry/rescan/reset actions"""
        if not self.main_window:
            return
            
        # Get paths by status for conditional menus
        failed_paths = self._get_paths_by_status(selected_paths, ["scan_failed", "upload_failed", "failed"])
        rescannable_paths = self._get_rescannable_paths(selected_paths)
        rescan_all_paths = self._get_rescan_all_paths(selected_paths)
        
        # Retry actions
        upload_failed_paths = self._get_paths_by_status(selected_paths, "upload_failed")
        if upload_failed_paths:
            retry_action = menu.addAction("🔄 Retry Upload")
            retry_action.setToolTip("Retry failed upload")
            retry_action.triggered.connect(lambda: self._delegate_to_main_window('retry_selected_via_menu', upload_failed_paths))
        
        generic_failed_paths = self._get_paths_by_status(selected_paths, "failed")
        if generic_failed_paths:
            retry_generic_action = menu.addAction("🔄 Retry")
            retry_generic_action.setToolTip("Retry failed operation")
            retry_generic_action.triggered.connect(lambda: self._delegate_to_main_window('retry_selected_via_menu', generic_failed_paths))
        
        # Rescan actions
        if rescannable_paths:
            rescan_action = menu.addAction("🔍 Rescan for New Images")
            rescan_action.setToolTip("Scan for new images added to folder (preserves existing uploads)")
            rescan_action.triggered.connect(lambda: self._delegate_to_main_window('rescan_additive_via_menu', rescannable_paths))
        
        if rescan_all_paths:
            rescan_all_action = menu.addAction("🔄 Rescan All Items")
            rescan_all_action.setToolTip("Rescan all items in gallery (preserves successful uploads)")
            rescan_all_action.triggered.connect(lambda: self._delegate_to_main_window('rescan_all_items_via_menu', rescan_all_paths))
        
        # Reset action
        reset_action = menu.addAction("🗑️ Reset Gallery")
        reset_action.setToolTip("Completely reset gallery and rescan from scratch")
        reset_action.triggered.connect(lambda: self._delegate_to_main_window('reset_gallery_via_menu', selected_paths))
        
        # Copy BBCode and open links for completed items
        completed_paths = self._get_paths_by_status(selected_paths, "completed")
        if completed_paths:
            # View BBCode (single selection only)
            if len(completed_paths) == 1:
                view_bbcode_action = menu.addAction("View BBCode")
                view_bbcode_action.triggered.connect(lambda: self._delegate_to_main_window('handle_view_button', completed_paths[0]))

            copy_action = menu.addAction("Copy BBCode")
            copy_action.triggered.connect(lambda: self._delegate_to_main_window('copy_bbcode_via_menu_multi', completed_paths))

            # Regenerate BBCode
            regenerate_action = menu.addAction("Regenerate BBCode")
            if len(completed_paths) == 1:
                regenerate_action.triggered.connect(lambda: self._delegate_to_main_window('regenerate_bbcode_for_gallery', completed_paths[0]))
            else:
                regenerate_action.triggered.connect(lambda: self._delegate_to_main_window('regenerate_bbcode_for_gallery_multi', completed_paths))

            open_link_action = menu.addAction("Open Gallery Link")
            open_link_action.triggered.connect(lambda: self._delegate_to_main_window('open_gallery_links_via_menu', completed_paths))
    
    def _add_move_to_submenu(self, menu, selected_paths):
        """Add Move to... submenu"""
        if not self.main_window or not hasattr(self.main_window, 'tab_manager'):
            return
        
        tab_manager = self.main_window.tab_manager
        if not tab_manager:
            return
            
        available_tabs = tab_manager.get_visible_tab_names()
        current_tab = getattr(self.main_window, 'current_tab', 'Main')
        
        # Create "Move to" submenu with tabs other than the current one and excluding "All Tabs"
        other_tabs = [tab for tab in available_tabs if tab != current_tab and tab != "All Tabs"]
        if other_tabs:
            move_menu = menu.addMenu("Move to tab...")
            for tab_name in other_tabs:
                move_action = move_menu.addAction(tab_name)
                move_action.triggered.connect(
                    lambda checked, target_tab=tab_name: self._delegate_to_main_window('_move_selected_to_tab', selected_paths, target_tab)
                )
    
    def _add_no_selection_items(self, menu):
        """Add menu items when no galleries are selected"""
        add_action = menu.addAction("Add Folders...")
        add_action.triggered.connect(lambda: self._delegate_to_main_window('browse_for_folders'))
    
    def _check_can_start(self, selected_paths):
        """Check if any selected items can be started"""
        if not self.main_window or not hasattr(self.main_window, 'queue_manager'):
            return False
            
        for path in selected_paths:
            item = self.main_window.queue_manager.get_item(path)
            if item and item.status in ("ready", "paused", "incomplete"):
                return True
        return False
    
    def _get_paths_by_status(self, selected_paths, statuses):
        """Get paths that match the given status(es)"""
        if not self.main_window or not hasattr(self.main_window, 'queue_manager'):
            return []
        
        if isinstance(statuses, str):
            statuses = [statuses]
            
        matching_paths = []
        for path in selected_paths:
            item = self.main_window.queue_manager.get_item(path)
            if item and item.status in statuses:
                matching_paths.append(path)
        return matching_paths
    
    def _get_rescannable_paths(self, selected_paths):
        """Get paths that can benefit from additive rescan"""
        return self._get_paths_by_status(selected_paths, 
            ["scan_failed", "completed", "incomplete", "upload_failed", "failed", "scanning", "ready"])
    
    def _get_rescan_all_paths(self, selected_paths):
        """Get paths that can benefit from full rescan"""
        if not self.main_window or not hasattr(self.main_window, 'queue_manager'):
            return []
        
        rescan_all_paths = []
        for path in selected_paths:
            item = self.main_window.queue_manager.get_item(path)
            if item:
                # Check if gallery is 100% complete
                total_images = getattr(item, 'total_images', 0) or 0
                uploaded_images = getattr(item, 'uploaded_images', 0) or 0
                is_100_percent_complete = (item.status == "completed" and 
                                         total_images > 0 and 
                                         uploaded_images >= total_images)
                
                # Allow rescan all for stuck scanning galleries (0 images counted)
                is_stuck_scanning = (item.status == "scanning" and total_images == 0)
                
                if not is_100_percent_complete and (item.status in ["scan_failed", "completed", "incomplete", "upload_failed", "failed", "ready"] or is_stuck_scanning):
                    rescan_all_paths.append(path)
        
        return rescan_all_paths
    
    def _delegate_to_main_window(self, method_name, *args):
        """Delegate action to table widget or main window method"""
        if not self.main_window:
            return
            
        # First try to find the method on the table widget
        table_widget = None
        if hasattr(self.main_window, 'gallery_table'):
            if hasattr(self.main_window.gallery_table, 'table'):
                # Tabbed widget case
                table_widget = self.main_window.gallery_table.table
            else:
                # Direct table case
                table_widget = self.main_window.gallery_table
        
        # Try table widget first, then main window
        if table_widget and hasattr(table_widget, method_name):
            method = getattr(table_widget, method_name)
        elif hasattr(self.main_window, method_name):
            method = getattr(self.main_window, method_name)
        else:
            print(f"Warning: Method {method_name} not found on table or main window")
            return
            
        if args:
            method(*args)
        else:
            method()
    
    def _add_template_submenu(self, menu: QMenu, selected_paths: list):
        """Add 'Set template to...' submenu to the context menu"""
        if not selected_paths:
            return
            
        try:
            from imxup import load_templates
            templates = load_templates()
            template_names = list(templates.keys())
            
            if template_names:
                template_menu = menu.addMenu("Set template to...")
                for template_name in template_names:
                    template_action = template_menu.addAction(template_name)
                    template_action.triggered.connect(
                        lambda checked, target_template=template_name: 
                        self._handle_template_selection(selected_paths, target_template)
                    )
        except Exception as e:
            print(f"Error loading templates for context menu: {e}")
    
    def _handle_template_selection(self, gallery_paths: list, template_name: str):
        """Handle template selection for multiple galleries"""
        self.template_change_requested.emit(gallery_paths, template_name)
    
    def set_template_for_galleries(self, gallery_paths: list, template_name: str):
        """Update template for multiple galleries - called by main window"""
        if not gallery_paths or not template_name or not self.main_window:
            return
        
        updated_count = 0
        bbcode_regenerated = 0
        
        try:
            from imxup import timestamp
            import os
            
            # Update each gallery's template
            for gallery_path in gallery_paths:
                try:
                    # Update database
                    success = self.main_window.queue_manager.store.update_item_template(
                        gallery_path, template_name
                    )
                    
                    if success:
                        updated_count += 1
                        
                        # Update in-memory queue item (thread-safe)
                        gallery_item = None
                        with QMutexLocker(self.main_window.queue_manager.mutex):
                            if gallery_path in self.main_window.queue_manager.items:
                                gallery_item = self.main_window.queue_manager.items[gallery_path]
                                gallery_item.template_name = template_name
                                self.main_window.queue_manager._inc_version()

                        # For completed galleries, regenerate BBCode
                        if gallery_item and gallery_item.status == "completed":
                            try:
                                # Use existing regenerate_gallery_bbcode method
                                self.main_window.regenerate_gallery_bbcode(gallery_path, template_name)
                                bbcode_regenerated += 1
                            except Exception as e:
                                print(f"Failed to regenerate BBCode for {gallery_path}: {e}")
                                
                except Exception as e:
                    print(f"Error updating template for {gallery_path}: {e}")
            
            # Update table display for visible items
            self._update_table_display(gallery_paths, template_name)
            
            # Add log message
            if updated_count > 0:
                galleries_word = "gallery" if updated_count == 1 else "galleries"
                message = f"{timestamp()} Template changed to '{template_name}' for {updated_count} {galleries_word}"
                
                if bbcode_regenerated > 0:
                    bbcode_word = "gallery" if bbcode_regenerated == 1 else "galleries"
                    message += f", BBCode regenerated for {bbcode_regenerated} {bbcode_word}"
                
                self.main_window.add_log_message(message)
                
        except Exception as e:
            print(f"Error in batch template update: {e}")
    
    def _update_table_display(self, gallery_paths: list, template_name: str):
        """Update table display for galleries with new template"""
        if not self.main_window:
            return
            
        try:
            # Get table reference (handle both tabbed and direct table)
            if hasattr(self.main_window.gallery_table, 'table'):
                table = self.main_window.gallery_table.table
            else:
                table = self.main_window.gallery_table
                
            if not table:
                return
                
            # Update visible rows where gallery path matches
            for row in range(table.rowCount()):
                name_item = table.item(row, 1)  # Gallery name column
                if name_item:
                    gallery_path = name_item.data(table.UserRole)
                    if gallery_path in gallery_paths:
                        # Update template column (column 10)
                        template_item = table.item(row, 10)
                        if template_item:
                            template_item.setText(template_name)
                            
        except Exception as e:
            print(f"Error updating table display: {e}")
