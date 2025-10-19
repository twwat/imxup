#!/usr/bin/env python3
"""
Archive extraction and cleanup service
Handles extracting archives and cleaning up temp directories
"""

import shutil
import zipfile
from pathlib import Path
from typing import Optional

from src.utils.archive_utils import (
    is_valid_archive,
    validate_temp_extraction_path,
    find_folders_with_files
)


class ArchiveService:
    """Service for extracting archives and managing temp directories"""

    def __init__(self, base_temp_dir: str | Path):
        """Initialize with base temporary directory

        Args:
            base_temp_dir: Base directory for temp extractions (e.g., ~/.imxup/temp)
        """
        self.base_temp_dir = Path(base_temp_dir)
        self.base_temp_dir.mkdir(parents=True, exist_ok=True)

    def extract_archive(self, archive_path: str | Path) -> Optional[Path]:
        """Extract archive to temp directory

        Args:
            archive_path: Path to archive file

        Returns:
            Path to extraction directory, or None if extraction failed
        """
        if not is_valid_archive(archive_path):
            return None

        # Get unique temp directory
        temp_dir = validate_temp_extraction_path(self.base_temp_dir, archive_path)

        try:
            # Create extraction directory
            temp_dir.mkdir(parents=True, exist_ok=True)

            # Extract ZIP archive (works for both .zip and .cbz)
            archive_path = Path(archive_path)
            with zipfile.ZipFile(archive_path, 'r') as archive:
                archive.extractall(path=temp_dir)

            return temp_dir

        except Exception:
            # Clean up on failure
            self.cleanup_temp_dir(temp_dir)
            return None

    def get_folders(self, temp_dir: Path) -> list[Path]:
        """Find folders with files in extracted directory

        Note: Queue manager handles image validation after folders are added

        Args:
            temp_dir: Extracted archive directory

        Returns:
            List of folder paths containing files
        """
        return find_folders_with_files(temp_dir)

    def cleanup_temp_dir(self, temp_dir: str | Path) -> bool:
        """Remove temp directory

        Args:
            temp_dir: Path to directory to remove

        Returns:
            True if successful
        """
        try:
            temp_path = Path(temp_dir)
            if temp_path.exists() and temp_path.is_dir():
                shutil.rmtree(temp_path)
            return True
        except Exception:
            return False
