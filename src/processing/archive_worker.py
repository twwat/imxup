"""
Archive extraction worker for non-blocking ZIP/CBZ processing.
Handles archive extraction in background thread to keep GUI responsive.
"""

from pathlib import Path
from typing import Optional, List
from PyQt6.QtCore import QObject, QRunnable, pyqtSignal


class ArchiveExtractionSignals(QObject):
    """Signals for archive extraction worker"""
    # Emitted when extraction completes successfully with selected folders
    finished = pyqtSignal(str, list)  # archive_path, selected_folder_paths
    # Emitted if extraction fails or user cancels
    error = pyqtSignal(str, str)  # archive_path, error_message
    # Emitted for progress updates (optional, for future progress dialog)
    progress = pyqtSignal(str, int)  # archive_path, progress_percent


class ArchiveExtractionWorker(QRunnable):
    """
    Worker for extracting archives in background thread.

    This prevents GUI freezing when extracting large ZIP/CBZ files.
    The worker handles extraction, folder discovery, and user selection dialog.
    """

    def __init__(self, archive_path: str, coordinator):
        """
        Initialize archive extraction worker.

        Args:
            archive_path: Path to archive file (.zip, .cbz)
            coordinator: ArchiveCoordinator instance for processing
        """
        super().__init__()
        self.archive_path = archive_path
        self.coordinator = coordinator
        self.signals = ArchiveExtractionSignals()

    def run(self):
        """Execute archive extraction in background thread"""
        try:
            # Process archive (extraction + folder selection)
            selected_folders = self.coordinator.process_archive(self.archive_path)

            if selected_folders:
                # Convert Path objects to strings for signal
                folder_paths = [str(folder) for folder in selected_folders]
                self.signals.finished.emit(self.archive_path, folder_paths)
            else:
                # User cancelled or no folders found
                self.signals.error.emit(
                    self.archive_path,
                    "No folders selected or extraction cancelled"
                )

        except Exception as e:
            # Extraction or processing failed
            self.signals.error.emit(
                self.archive_path,
                f"Archive extraction failed: {str(e)}"
            )
