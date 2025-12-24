#!/usr/bin/env python3
"""
Image Status Checker

Coordinates checking image online status on IMX.to for galleries.
Handles dialog display, worker callbacks, and database updates.
"""

import os
from typing import List, Optional, Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QMessageBox

from src.gui.dialogs.image_status_dialog import ImageStatusDialog
from src.gui.widgets.gallery_table import GalleryTableWidget
from src.utils.logger import log


class ImageStatusChecker:
    """Coordinates image status checking for galleries.

    This class handles:
    - Gathering gallery data and image URLs from the queue manager
    - Displaying the ImageStatusDialog
    - Setting up callbacks for the rename worker
    - Updating the database and gallery table with results
    """

    def __init__(
        self,
        parent: QWidget,
        queue_manager: Any,
        rename_worker: Any,
        gallery_table: GalleryTableWidget
    ):
        """Initialize the status checker.

        Args:
            parent: Parent widget for dialogs
            queue_manager: Queue manager instance for database access
            rename_worker: RenameWorker instance for status checking
            gallery_table: Gallery table widget for display updates
        """
        self.parent = parent
        self.queue_manager = queue_manager
        self.rename_worker = rename_worker
        self.gallery_table = gallery_table
        self.dialog: Optional[ImageStatusDialog] = None

    def check_galleries(self, paths: List[str]) -> None:
        """Check image status for the specified gallery paths.

        Args:
            paths: List of gallery paths to check
        """
        if not paths:
            return

        if self.dialog is not None and self.dialog.isVisible():
            return  # Already checking

        # Gather gallery info and image URLs
        galleries_data = []
        for path in paths:
            item = self.queue_manager.get_item(path)
            if not item or item.status != "completed":
                continue

            # Get image URLs from database
            image_urls = self.queue_manager.store.get_image_urls_for_galleries([path])
            urls = [img['url'] for img in image_urls.get(path, []) if img.get('url')]

            if urls:
                galleries_data.append({
                    'db_id': item.db_id,
                    'path': path,
                    'name': item.name or os.path.basename(path),
                    'total_images': len(urls),
                    'image_urls': urls
                })

        if not galleries_data:
            QMessageBox.information(
                self.parent, "No Images",
                "No image URLs found for the selected galleries."
            )
            return

        # Create and show dialog
        self.dialog = ImageStatusDialog(self.parent)
        self.dialog.set_galleries(galleries_data)
        self.dialog.show_progress(True)
        self.dialog.show()

        # Connect dialog finished signal for cleanup when closed
        self.dialog.finished.connect(self._on_dialog_finished)

        # Connect cancel signal
        self.dialog.cancelled.connect(self._on_cancel)

        # Connect signals for thread-safe cross-thread communication
        self.rename_worker.status_check_progress.connect(self._on_progress)
        self.rename_worker.status_check_completed.connect(self._on_completed)
        self.rename_worker.status_check_error.connect(self._on_error)

        # Start the check
        self.rename_worker.check_image_status(galleries_data)

    def _cleanup_connections(self) -> None:
        """Disconnect signal connections to prevent memory leaks."""
        try:
            self.rename_worker.status_check_progress.disconnect(self._on_progress)
            self.rename_worker.status_check_completed.disconnect(self._on_completed)
            self.rename_worker.status_check_error.disconnect(self._on_error)
        except TypeError:
            # Signals already disconnected
            pass

    def _on_dialog_finished(self, result: int) -> None:
        """Handle dialog close/finish - ensure signal cleanup.

        Args:
            result: Dialog result code (ignored)
        """
        self._cleanup_connections()
        self.dialog = None

    def _on_progress(self, current: int, total: int) -> None:
        """Handle progress updates from the worker.

        Args:
            current: Current progress value
            total: Total progress value
        """
        if self.dialog:
            self.dialog.update_progress(current, total)

    def _on_completed(self, results: dict) -> None:
        """Handle completion of status check.

        Args:
            results: Dict keyed by gallery path with status results
        """
        if not self.dialog:
            return

        self.dialog.set_results(results)

        # Update database and table for each gallery
        check_timestamp = self.dialog.get_checked_timestamp()
        check_datetime = self.dialog.format_check_datetime(check_timestamp)

        for path, result in results.items():
            online = result.get('online', 0)
            total = result.get('total', 0)

            # Build status text
            if total == 0:
                status_text = ""
            elif online == total:
                status_text = f"Online ({online}/{total})"
            elif online == 0:
                status_text = f"Offline (0/{total})"
            else:
                status_text = f"Partial ({online}/{total})"

            # Update database
            try:
                self.queue_manager.store.update_gallery_imx_status(
                    path, status_text, check_timestamp
                )
            except Exception as e:
                log(f"Failed to update imx status in database: {e}",
                    level="error", category="status_check")

            # Update table display
            self._update_table_display(path, online, total, check_datetime)

        # Cleanup signal connections
        self._cleanup_connections()
        self.dialog = None

    def _on_error(self, error_msg: str) -> None:
        """Handle error from the worker.

        Args:
            error_msg: Error message string
        """
        if not self.dialog:
            return

        self.dialog.show_progress(False)
        QMessageBox.critical(
            self.parent, "Check Failed",
            f"Failed to check image status: {error_msg}"
        )

        # Cleanup signal connections
        self._cleanup_connections()
        self.dialog = None

    def _on_cancel(self) -> None:
        """Handle cancel request from dialog."""
        self.rename_worker.cancel_status_check()
        self._cleanup_connections()

    def _update_table_display(
        self, path: str, online: int, total: int, check_datetime: str
    ) -> None:
        """Update the gallery table to show IMX status.

        Args:
            path: Gallery path
            online: Number of online images
            total: Total images
            check_datetime: Formatted datetime string
        """
        # Find the row for this gallery path
        for row in range(self.gallery_table.rowCount()):
            name_item = self.gallery_table.item(row, GalleryTableWidget.COL_NAME)
            if name_item and name_item.data(Qt.ItemDataRole.UserRole) == path:
                self.gallery_table.set_online_imx_status(row, online, total, check_datetime)
                break
