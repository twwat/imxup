#!/usr/bin/env python3
"""
Archive processing coordinator
Orchestrates extraction, folder selection, and cleanup
"""

from pathlib import Path
from typing import Optional

from src.services.archive_service import ArchiveService
from src.utils.archive_utils import get_archive_name
from src.gui.dialogs.archive_folder_selector import ArchiveFolderSelector


class ArchiveCoordinator:
    """Coordinates archive processing workflow"""

    def __init__(self, archive_service: ArchiveService, parent_widget=None):
        """Initialize coordinator

        Args:
            archive_service: Service for extraction and cleanup
            parent_widget: Parent widget for dialogs
        """
        self.service = archive_service
        self.parent = parent_widget

    def process_archive(self, archive_path: str | Path) -> Optional[list[Path]]:
        """Process archive and return selected folders

        Args:
            archive_path: Path to archive file

        Returns:
            List of selected folder paths, or None if cancelled/failed
        """
        archive_path = Path(archive_path)
        archive_name = get_archive_name(archive_path)

        # Extract archive
        temp_dir = self.service.extract_archive(archive_path)
        if not temp_dir:
            return None

        # Get folders with files (queue manager will validate images)
        folders = self.service.get_folders(temp_dir)

        if not folders:
            # No folders found - cleanup and return
            self.service.cleanup_temp_dir(temp_dir)
            return None

        # If only one folder, return it directly
        if len(folders) == 1:
            return folders

        # Multiple folders - show selector dialog
        dialog = ArchiveFolderSelector(archive_name, folders, self.parent)
        if dialog.exec():
            selected = dialog.get_selected_folders()
            if selected:
                return selected

        # User cancelled or no selection
        self.service.cleanup_temp_dir(temp_dir)
        return None
