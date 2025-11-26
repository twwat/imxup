#!/usr/bin/env python3
"""
Archive utilities for imxup
Handles archive detection, validation, and path inspection
"""

import os
from pathlib import Path
from typing import Optional


# Supported archive extensions (ZIP format only - uses Python's built-in zipfile)
SUPPORTED_ARCHIVE_EXTENSIONS = {
    '.zip',
    '.cbz',  # Comic book ZIP archive
}


def is_archive_file(path: str | Path) -> bool:
    """Check if a file is a supported archive format

    Args:
        path: Path to file to check

    Returns:
        True if file has supported archive extension
    """
    if not path:
        return False

    path_obj = Path(path)
    suffix = path_obj.suffix.lower()

    # Handle edge case: ".zip" (hidden file) should be treated as having .zip extension
    if not suffix and str(path_obj.name).startswith('.'):
        # Check if the entire name (without leading dot) is a supported extension
        potential_ext = '.' + str(path_obj.name).lstrip('.')
        if potential_ext.lower() in SUPPORTED_ARCHIVE_EXTENSIONS:
            return True

    return suffix in SUPPORTED_ARCHIVE_EXTENSIONS


def is_valid_archive(path: str | Path) -> bool:
    """Check if path is a valid, existing archive file

    Args:
        path: Path to file to check

    Returns:
        True if file exists and is a supported archive
    """
    if not path:
        return False

    path_obj = Path(path)
    return path_obj.is_file() and is_archive_file(path_obj)


def get_archive_name(path: str | Path) -> str:
    """Get the base name of an archive without extension

    Args:
        path: Path to archive file

    Returns:
        Archive name without extension
    """
    if not path:
        return "archive"

    # Convert to string to handle both POSIX and Windows paths uniformly
    path_str = str(path)

    # Normalize path separators (handle both / and \)
    path_str = path_str.replace('\\', '/')

    # Get the filename component (everything after last separator)
    filename = path_str.split('/')[-1] if '/' in path_str else path_str

    # Remove extension
    if '.' in filename:
        # Handle edge case: ".zip" should return ".zip" not ""
        if filename.startswith('.') and filename.count('.') == 1:
            return filename
        # Normal case: remove extension
        return filename.rsplit('.', 1)[0]

    return filename


def get_archive_size(path: str | Path) -> int:
    """Get the size of an archive file in bytes

    Args:
        path: Path to archive file

    Returns:
        File size in bytes, or 0 if file doesn't exist
    """
    try:
        path_obj = Path(path)
        if path_obj.is_file():
            return path_obj.stat().st_size
    except Exception:
        pass

    return 0


def validate_temp_extraction_path(base_temp_dir: str | Path, archive_path: str | Path) -> Path:
    """Generate a safe, unique temp directory path for archive extraction

    Args:
        base_temp_dir: Base temporary directory (e.g., ~/.imxup/temp)
        archive_path: Path to the archive file

    Returns:
        Path object for temp extraction directory
    """
    base_dir = Path(base_temp_dir)
    archive_name = get_archive_name(archive_path)

    # Create base name with sanitized archive name
    temp_dir = base_dir / f"extract_{archive_name}"

    # If directory exists, append a counter
    counter = 1
    original_temp_dir = temp_dir
    while temp_dir.exists():
        temp_dir = Path(f"{original_temp_dir}_{counter}")
        counter += 1

    return temp_dir


def find_folders_with_files(root_dir: str | Path) -> list[Path]:
    """Find all folders that directly contain files (not just subfolders)

    Args:
        root_dir: Root directory to scan

    Returns:
        List of folder paths that contain files
    """
    root_path = Path(root_dir)
    if not root_path.is_dir():
        return []

    folders_with_files = []

    try:
        for dirpath, dirnames, filenames in os.walk(root_path):
            # If this folder has files, add it
            if filenames:
                folders_with_files.append(Path(dirpath))

    except Exception:
        pass

    return folders_with_files


