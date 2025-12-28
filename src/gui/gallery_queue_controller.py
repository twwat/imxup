"""Gallery queue controller for IMXuploader GUI.

This module handles gallery queue addition and action operations extracted from main_window.py
to improve maintainability and separation of concerns.

Handles:
    - Adding folders to queue (single, multiple, archives)
    - Duplicate detection and confirmation dialogs
    - Queue actions (start all, pause all, clear completed, delete selected)
    - Command-line folder additions
"""

import os
import time
from typing import TYPE_CHECKING, List

from PyQt6.QtCore import QObject, QTimer, Qt, QMutexLocker
from PyQt6.QtWidgets import (
    QFileDialog, QListView, QTreeView, QAbstractItemView,
    QProgressDialog, QMessageBox
)

from src.utils.logger import log
from src.utils.archive_utils import is_archive_file
from src.processing.archive_worker import ArchiveExtractionWorker
from src.storage.queue_manager import GalleryQueueItem

if TYPE_CHECKING:
    from src.gui.main_window import ImxUploadGUI
    from src.gui.widgets.gallery_table import GalleryTableWidget

# Column index constant (mirrors GalleryTableWidget.COL_NAME)
# Avoids circular import by defining locally
COL_NAME = 1


class GalleryQueueController(QObject):
    """Handles gallery queue operations for the main window.

    This controller manages all queue addition and action operations including:
    - Browsing and adding folders/archives
    - Duplicate detection with user confirmation
    - Batch queue operations (start, pause, clear, delete)

    Attributes:
        _main_window: Reference to the main ImxUploadGUI window
    """

    def __init__(self, main_window: 'ImxUploadGUI'):
        """Initialize the GalleryQueueController.

        Args:
            main_window: Reference to the main ImxUploadGUI window
        """
        super().__init__()
        self._main_window = main_window

    # =========================================================================
    # Queue Addition Methods
    # =========================================================================

    def browse_for_folders(self):
        """Open folder browser to select galleries or archives (supports multiple selection).

        Creates a file dialog with extended selection support for both folders
        and archive files. Selected items are processed via add_folders_or_archives().
        """
        mw = self._main_window

        # Create file dialog with multi-selection support
        file_dialog = QFileDialog(mw)
        file_dialog.setWindowTitle("Select Gallery Folders and/or Archives")
        file_dialog.setFileMode(QFileDialog.FileMode.Directory)
        file_dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        file_dialog.setOption(QFileDialog.Option.ShowDirsOnly, False)
        file_dialog.setNameFilter("All Files and Folders (*)")

        # Enable proper multi-selection on internal views (Ctrl+click, Shift+click)
        list_view = file_dialog.findChild(QListView, 'listView')
        if list_view:
            list_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            list_view.setStyleSheet(mw.styleSheet())

        tree_view = file_dialog.findChild(QTreeView)
        if tree_view:
            tree_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            tree_view.setStyleSheet(mw.styleSheet())

        # Execute dialog and add selected items (folders or archives)
        if file_dialog.exec() == QFileDialog.DialogCode.Accepted:
            selected_paths = file_dialog.selectedFiles()
            if selected_paths:
                self.add_folders_or_archives(selected_paths)

    def add_folders_or_archives(self, paths: List[str]):
        """Add folders or archives to upload queue.

        Separates paths into folders and archives, then processes each appropriately.
        Folders are added directly, archives are extracted in background threads.

        Args:
            paths: List of folder or archive file paths to add
        """
        mw = self._main_window
        folders = []
        archives = []

        for path in paths:
            if os.path.isdir(path):
                folders.append(path)
            elif os.path.isfile(path) and is_archive_file(path):
                archives.append(path)

        # Process folders normally
        if folders:
            self.add_folders(folders)

        # Process archives in background threads
        for archive_path in archives:
            worker = ArchiveExtractionWorker(archive_path, mw.archive_coordinator)
            worker.signals.finished.connect(mw.on_archive_extraction_finished)
            worker.signals.error.connect(mw.on_archive_extraction_error)
            mw._thread_pool.start(worker)
            log(f"Started background extraction for: {os.path.basename(archive_path)}",
                level="debug", category="ui")

    def add_folders(self, folder_paths: List[str]):
        """Add folders to the upload queue with duplicate detection.

        Routes to appropriate handler based on folder count:
        - Single folder: Uses _add_single_folder for backward compatibility
        - Multiple folders: Uses _add_multiple_folders_with_duplicate_detection

        Args:
            folder_paths: List of folder paths to add to queue
        """
        log(f"add_folders called with {len(folder_paths)} paths",
            level="trace", category="queue")

        if len(folder_paths) == 1:
            self._add_single_folder(folder_paths[0])
        else:
            self._add_multiple_folders_with_duplicate_detection(folder_paths)

    def _add_single_folder(self, path: str):
        """Add a single folder with duplicate detection.

        Checks if folder is already in queue or was previously uploaded,
        prompting user for confirmation before adding.

        Args:
            path: Path to the folder to add
        """
        mw = self._main_window
        log(f"_add_single_folder called with path={path}", level="trace", category="queue")

        folder_name = os.path.basename(path)

        # Check if already in queue
        existing_item = mw.queue_manager.get_item(path)
        if existing_item:
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Icon.Question)
            msg.setWindowTitle("Already in Queue")
            msg.setText(f"'{folder_name}' is already in the queue.")
            msg.setInformativeText(
                f"Current status: {existing_item.status}\n\nDo you want to replace it?"
            )
            msg.setStandardButtons(
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            msg.setDefaultButton(QMessageBox.StandardButton.No)

            if msg.exec() == QMessageBox.StandardButton.Yes:
                mw.queue_manager.remove_item(path)
                log(f"Replaced {folder_name} in queue", level="debug", category="queue")
            else:
                return  # User chose not to replace

        # Check if previously uploaded
        existing_files = mw._check_if_gallery_exists(folder_name)
        if existing_files:
            files_text = ', '.join(existing_files) if existing_files else "gallery files"
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Icon.Warning)
            msg.setWindowTitle("Previously Uploaded")
            msg.setText(f"'{folder_name}' appears to have been uploaded before.")
            msg.setInformativeText(
                f"Found: {files_text}\n\nAre you sure you want to upload it again?"
            )
            msg.setStandardButtons(
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            msg.setDefaultButton(QMessageBox.StandardButton.No)

            if msg.exec() != QMessageBox.StandardButton.Yes:
                return  # User chose not to upload

        # Proceed with adding
        template_name = mw.template_combo.currentText()
        current_tab = (
            mw.gallery_table.current_tab
            if hasattr(mw.gallery_table, 'current_tab')
            else "Main"
        )
        actual_tab = "Main" if current_tab == "All Tabs" else current_tab

        result = mw.queue_manager.add_item(
            path, template_name=template_name, tab_name=actual_tab
        )

        if result:
            log(f"Added to queue: {os.path.basename(path)}",
                category="queue", level="info")
            item = mw.queue_manager.get_item(path)
            if item:
                mw._add_gallery_to_table(item)
                QTimer.singleShot(
                    100,
                    lambda: (
                        mw.gallery_table._update_tab_tooltips()
                        if hasattr(mw.gallery_table, '_update_tab_tooltips')
                        else None
                    )
                )
        else:
            log(f"Failed to add: {os.path.basename(path)} (no images found)",
                category="queue", level="warning")

    def _add_archive_folder(self, folder_path: str, archive_path: str):
        """Add a folder from extracted archive to queue.

        Args:
            folder_path: Path to the extracted folder
            archive_path: Path to the source archive file
        """
        mw = self._main_window
        template_name = mw.template_combo.currentText()
        current_tab = (
            mw.gallery_table.current_tab
            if hasattr(mw.gallery_table, 'current_tab')
            else "Main"
        )

        # Derive gallery name from folder, removing "extract_" prefix if present
        folder_name = os.path.basename(folder_path)
        if folder_name.startswith('extract_'):
            gallery_name = folder_name[8:]
        else:
            gallery_name = folder_name

        actual_tab = "Main" if current_tab == "All Tabs" else current_tab
        result = mw.queue_manager.add_item(
            folder_path,
            name=gallery_name,
            template_name=template_name,
            tab_name=actual_tab
        )

        if result:
            item = mw.queue_manager.get_item(folder_path)
            if item:
                item.source_archive_path = archive_path
                item.is_from_archive = True
                mw.queue_manager.save_persistent_queue([folder_path])
                mw._add_gallery_to_table(item)
                log(f"Added from archive: {gallery_name}",
                    category="queue", level="info")

    def _add_multiple_folders(self, folder_paths: List[str]):
        """Add multiple folders efficiently using the batch method.

        Shows a progress dialog during addition and assigns items to the current tab.

        Args:
            folder_paths: List of folder paths to add
        """
        mw = self._main_window
        template_name = mw.template_combo.currentText()

        # Show progress dialog for multiple folders
        progress = QProgressDialog(
            "Adding galleries...", "Cancel", 0, len(folder_paths), mw
        )
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setAutoClose(True)
        progress.setValue(0)

        try:
            results = mw.queue_manager.add_multiple_items(folder_paths, template_name)

            # Set all added items to current active tab
            current_tab = (
                mw.gallery_table.current_tab
                if hasattr(mw.gallery_table, 'current_tab')
                else "Main"
            )
            actual_tab = "Main" if current_tab == "All Tabs" else current_tab

            if actual_tab != "Main" and results['added_paths']:
                tab_info = mw.tab_manager.get_tab_by_name(actual_tab)
                if tab_info:
                    for path in results['added_paths']:
                        item = mw.queue_manager.get_item(path)
                        if item:
                            item.tab_name = actual_tab
                            mw.queue_manager._save_single_item(item)

            progress.setValue(len(folder_paths))

            # Show results
            if results['added'] > 0:
                log(f"Added {results['added']} galleries to queue",
                    category="queue", level="info")
            if results['duplicates'] > 0:
                log(f"Skipped {results['duplicates']} duplicate galleries",
                    category="queue", level="info")
            if results['failed'] > 0:
                log(f"Failed to add {results['failed']} galleries", category="queue")
                for error in results['errors'][:5]:
                    log(f"WARNING: {error}", category="queue", level="warning")
                if len(results['errors']) > 5:
                    log(f"... and {len(results['errors']) - 5} more errors",
                        category="queue", level="warning")

            # Add all successfully added items to table
            for path in results.get('added_paths', []):
                item = mw.queue_manager.get_item(path)
                if item:
                    mw._add_gallery_to_table(item)

        except Exception as e:
            log(f"Adding multiple folders: {str(e)}", category="queue", level="error")
        finally:
            progress.close()

    def _add_multiple_folders_with_duplicate_detection(self, folder_paths: List[str]):
        """Add multiple folders with duplicate detection dialogs.

        Shows dialogs for duplicate detection before adding folders to queue.

        Args:
            folder_paths: List of folder paths to add
        """
        mw = self._main_window
        from src.gui.dialogs.duplicate_detection_dialogs import show_duplicate_detection_dialogs

        try:
            # Show duplicate detection dialogs and get processed lists
            folders_to_add_normally, folders_to_replace_in_queue = show_duplicate_detection_dialogs(
                folders_to_add=folder_paths,
                check_gallery_exists_func=mw._check_if_gallery_exists,
                queue_manager=mw.queue_manager,
                parent=mw
            )

            # Get current tab before adding items
            current_tab = (
                mw.gallery_table.current_tab
                if hasattr(mw.gallery_table, 'current_tab')
                else "Main"
            )
            actual_tab = "Main" if current_tab == "All Tabs" else current_tab

            # Process folders that passed duplicate checks
            if folders_to_add_normally:
                template_name = mw.template_combo.currentText()
                log(f"Multiple folders - adding to tab: {actual_tab}",
                    level="debug", category="queue")

                for folder_path in folders_to_add_normally:
                    try:
                        result = mw.queue_manager.add_item(
                            folder_path,
                            template_name=template_name,
                            tab_name=actual_tab
                        )
                        if result:
                            item = mw.queue_manager.get_item(folder_path)
                            if item:
                                mw._add_gallery_to_table(item)
                            log(f"Added to queue: {os.path.basename(folder_path)}",
                                category="queue", level="debug")
                    except Exception as e:
                        log(f"Error while adding folder: {os.path.basename(folder_path)}: {e}",
                            level="error", category="queue")

            # Process folders that should replace existing queue items
            if folders_to_replace_in_queue:
                log(f"Replacing {len(folders_to_replace_in_queue)} folders in queue",
                    level="debug", category="queue")
                template_name = mw.template_combo.currentText()
                log(f"Multiple folders replacement - adding to tab: {actual_tab}",
                    level="debug", category="queue")

                for folder_path in folders_to_replace_in_queue:
                    try:
                        # Remove existing item from both queue and table
                        mw.queue_manager.remove_item(folder_path)
                        mw._remove_gallery_from_table(folder_path)

                        # Add new item with correct tab
                        result = mw.queue_manager.add_item(
                            folder_path,
                            template_name=template_name,
                            tab_name=actual_tab
                        )
                        if result:
                            item = mw.queue_manager.get_item(folder_path)
                            if item:
                                mw._add_gallery_to_table(item)
                        log(f"Replaced {os.path.basename(folder_path)} in queue",
                            level="debug", category="queue")
                    except Exception as e:
                        log(f"Error while replacing {os.path.basename(folder_path)}: {e}",
                            level="error", category="queue")

            # Update display
            total_processed = len(folders_to_add_normally) + len(folders_to_replace_in_queue)
            if total_processed > 0:
                log(f"Added {total_processed} galleries to queue",
                    level="info", category="queue")
                QTimer.singleShot(
                    100,
                    lambda: (
                        mw.gallery_table._update_tab_tooltips()
                        if hasattr(mw.gallery_table, '_update_tab_tooltips')
                        else None
                    )
                )

        except Exception as e:
            log(f"Error while processing folders: {e}", level="error", category="queue")

    def add_folder_from_command_line(self, folder_path: str):
        """Add folder from command line (single instance).

        Also brings the window to focus if hidden.

        Args:
            folder_path: Path to the folder to add
        """
        mw = self._main_window

        if folder_path and os.path.isdir(folder_path):
            self.add_folders([folder_path])

        # Show window if hidden or bring to front
        if not mw.isVisible():
            mw.show()
        mw.raise_()
        mw.activateWindow()

    # =========================================================================
    # Queue Action Methods
    # =========================================================================

    def start_all_uploads(self):
        """Start all ready uploads in currently visible rows.

        Starts items with status 'ready', 'paused', or 'incomplete' that are
        visible in the current tab/filter. Uses batch updates for efficiency.
        """
        mw = self._main_window
        start_time = time.time()
        log(f"start_all_uploads() started at {start_time:.6f}",
            level="debug", category="timing")

        get_items_start = time.time()

        # Get items that are currently visible (not filtered out)
        visible_items = []
        all_items = mw.queue_manager.get_all_items()

        # Build path to row mapping for quick lookup
        path_to_row = {}
        for row in range(mw.gallery_table.rowCount()):
            name_item = mw.gallery_table.item(row, COL_NAME)
            if name_item:
                path = name_item.data(Qt.ItemDataRole.UserRole)
                if path:
                    path_to_row[path] = row

        # Only process items that are visible in the current filter
        for item in all_items:
            row = path_to_row.get(item.path)
            if row is not None and not mw.gallery_table.isRowHidden(row):
                visible_items.append(item)

        items = visible_items
        get_items_duration = time.time() - get_items_start
        log(f"Getting visible items took {get_items_duration:.6f}s, "
            f"found {len(items)} visible items",
            level="debug", category="timing")

        started_count = 0
        started_paths = []
        item_processing_start = time.time()

        # Use batch context to group all database saves into a single transaction
        with mw.queue_manager.batch_updates():
            for item in items:
                if item.status in ("ready", "paused", "incomplete"):
                    start_item_begin = time.time()
                    if mw.queue_manager.start_item(item.path):
                        start_item_duration = time.time() - start_item_begin
                        log(f"start_item({item.path}) took {start_item_duration:.6f}s",
                            category="timing", level="debug")
                        started_count += 1
                        started_paths.append(item.path)
                    else:
                        start_item_duration = time.time() - start_item_begin
                        log(f"start_item({item.path}) failed in {start_item_duration:.6f}s",
                            category="timing", level="debug")

        item_processing_duration = time.time() - item_processing_start
        log(f"Processing all items took {item_processing_duration:.6f}s",
            category="timing", level="info")

        ui_update_start = time.time()
        if started_count > 0:
            log(f"Started {started_count} uploads", level="info")
            # Update all affected items individually instead of rebuilding table
            for path in started_paths:
                mw._update_specific_gallery_display(path)
            # Update button counts and progress after state changes
            QTimer.singleShot(0, mw.progress_tracker._update_counts_and_progress)
        else:
            log(f"No items to start", category="queue", level="info")

        ui_update_duration = time.time() - ui_update_start
        log(f"UI updates took {ui_update_duration:.6f}s", category="timing", level="debug")

        total_duration = time.time() - start_time
        log(f"start_all_uploads() completed in {total_duration:.6f}s total",
            category="timing", level="debug")

    def pause_all_uploads(self):
        """Reset all queued items back to ready (acts like Cancel for queued).

        Operates on items in the current tab only.
        """
        mw = self._main_window
        items = mw._get_current_tab_items()
        reset_count = 0
        reset_paths = []

        with QMutexLocker(mw.queue_manager.mutex):
            for item in items:
                if item.status == "queued" and item.path in mw.queue_manager.items:
                    mw.queue_manager.items[item.path].status = "ready"
                    reset_count += 1
                    reset_paths.append(item.path)

        if reset_count > 0:
            log(f"Reset {reset_count} queued item(s) to Ready",
                level="info", category="queue")
            # Update all affected items individually instead of rebuilding table
            for path in reset_paths:
                mw._update_specific_gallery_display(path)
            # Update button counts and progress after state changes
            QTimer.singleShot(0, mw.progress_tracker._update_counts_and_progress)
        else:
            log(f"No queued items to reset", level="info", category="queue")

    def clear_completed(self):
        """Clear completed/failed uploads with confirmation.

        Shows a confirmation dialog before removing items. Uses non-blocking
        batch removal for table updates.
        """
        mw = self._main_window
        log(f"clear_completed() called", category="queue", level="debug")

        # Get items to clear
        items_snapshot = mw._get_current_tab_items()
        log(f"Got {len(items_snapshot)} items from current tab",
            category="queue", level="debug")

        comp_paths = [
            it.path for it in items_snapshot
            if it.status in ("completed", "failed")
        ]
        log(f"Found {len(comp_paths)} completed/failed galleries",
            category="queue", level="debug")

        if not comp_paths:
            log(f"No completed uploads to clear", category="queue", level="info")
            return

        # Use shared confirmation method
        log(f"Requesting user confirmation", category="queue", level="debug")
        if not mw._confirm_removal(comp_paths, operation_type="clear"):
            log(f"User cancelled clear operation", category="queue", level="info")
            return

        log(f"User confirmed - proceeding with clear", category="queue", level="debug")

        # User confirmed - proceed with removal
        count_completed = sum(1 for it in items_snapshot if it.status == "completed")
        count_failed = sum(1 for it in items_snapshot if it.status == "failed")
        log(f"Clearing (user confirmed): completed={count_completed}, failed={count_failed}",
            category="queue", level="debug")

        # Remove from queue manager
        removed_paths = []
        for path in comp_paths:
            with QMutexLocker(mw.queue_manager.mutex):
                if path in mw.queue_manager.items:
                    del mw.queue_manager.items[path]
                    removed_paths.append(path)
                    log(f"Removed item (user confirmed): {os.path.basename(path)}",
                        category="queue", level="debug")

        if not removed_paths:
            log(f"No items actually removed", level="info", category="queue")
            return

        log(f"Removed {len(removed_paths)} items from queue manager",
            category="queue", level="info")

        # Completion callback
        def on_clear_complete():
            # Renumber remaining items
            mw.queue_manager._renumber_items()

            # Delete from database
            try:
                mw.queue_manager.store._executor.submit(
                    mw.queue_manager.store.delete_by_paths, removed_paths
                )
            except Exception as e:
                log(f"Exception while deleting from database: {e}",
                    level="error", category="db")

            # Update button counts and progress
            QTimer.singleShot(0, mw.progress_tracker._update_counts_and_progress)

            # Update tab tooltips
            if hasattr(mw.gallery_table, '_update_tab_tooltips'):
                mw.gallery_table._update_tab_tooltips()

            # Save queue
            QTimer.singleShot(100, mw.queue_manager.save_persistent_queue)
            log(f"Cleared {len(removed_paths)} completed/failed uploads",
                category="queue", level="info")

        # Use non-blocking batch removal for table updates
        mw._remove_galleries_batch(removed_paths, callback=on_clear_complete)

    def delete_selected_items(self):
        """Delete selected items from the queue.

        Shows confirmation dialog and uses non-blocking batch removal.
        Skips items that are currently uploading.
        """
        mw = self._main_window
        log(f"Delete method called", level="debug", category="queue")

        # Get the actual table (handle tabbed interface)
        table = mw.gallery_table
        if hasattr(mw.gallery_table, 'table'):
            table = mw.gallery_table.table

        selected_rows = set()
        for item in table.selectedItems():
            selected_rows.add(item.row())

        if not selected_rows:
            log(f"No rows selected", level="debug", category="queue")
            return

        # Get paths directly from the table cells to handle sorting correctly
        selected_paths = []
        selected_names = []

        for row in selected_rows:
            name_item = table.item(row, COL_NAME)
            if name_item:
                path = name_item.data(Qt.ItemDataRole.UserRole)
                if path:
                    selected_paths.append(path)
                    selected_names.append(name_item.text())
                else:
                    log(f"No path data for row {row}", level="debug", category="queue")
            else:
                log(f"No name item for row {row}", level="debug", category="queue")

        if not selected_paths:
            log(f"No valid paths found", level="debug", category="queue")
            return

        # Use shared confirmation method
        if not mw._confirm_removal(selected_paths, selected_names, operation_type="delete"):
            log(f"User cancelled delete", level="debug", category="ui")
            return

        # Remove from queue manager first (filter out uploading items)
        removed_paths = []
        log(f"Attempting to delete {len(selected_paths)} paths",
            level="debug", category="queue")

        for path in selected_paths:
            # Check if item is currently uploading
            item = mw.queue_manager.get_item(path)
            if item:
                if item.status == "uploading":
                    log(f"Skipping uploading item: {path}")
                    continue
            else:
                log(f"Item not found in queue manager: {path}",
                    level="debug", category="queue")
                continue

            # Remove from memory
            with QMutexLocker(mw.queue_manager.mutex):
                if path in mw.queue_manager.items:
                    del mw.queue_manager.items[path]
                    removed_paths.append(path)
                    log(f"Deleted: {os.path.basename(path)}",
                        category="queue", level="debug")

        if not removed_paths:
            log(f"No items removed (all were uploading or not found)",
                level="debug", category="queue")
            return

        # Completion callback to run after batch removal finishes
        def on_deletion_complete():
            # Renumber remaining items
            mw.queue_manager._renumber_items()

            # Delete from database to prevent reloading
            try:
                mw.queue_manager.store._executor.submit(
                    mw.queue_manager.store.delete_by_paths, removed_paths
                )
            except Exception as e:
                log(f"Exception deleting from database: {e}",
                    level="error", category="database")

            # Update button counts and progress
            QTimer.singleShot(0, mw.progress_tracker._update_counts_and_progress)

            # Update tab tooltips to reflect new counts
            if hasattr(mw.gallery_table, '_update_tab_tooltips'):
                mw.gallery_table._update_tab_tooltips()

            # Defer database save to prevent GUI freeze
            QTimer.singleShot(100, mw.queue_manager.save_persistent_queue)
            log(f"Deleted {len(removed_paths)} items from queue",
                level="info", category="queue")

        # Use non-blocking batch removal for table updates
        mw._remove_galleries_batch(removed_paths, callback=on_deletion_complete)
