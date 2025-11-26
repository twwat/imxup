"""
Cross-platform path management utilities.

Handles path resolution, normalization, and management across different
operating systems and file systems.
"""

import os
from pathlib import Path
from typing import Optional, List
import re


class PathError(Exception):
    """Raised when path operations fail."""
    pass


class PathManager:
    """
    Manage application paths in a cross-platform way.
    """

    def __init__(self, base_path: Optional[Path] = None):
        """
        Initialize path manager.

        Args:
            base_path: Base path for relative path resolution (default: cwd)
        """
        self._base_path = Path(base_path) if base_path else Path.cwd()

    def normalize_path(self, path: str | Path) -> Path:
        """
        Normalize a path to canonical form.

        On WSL2, automatically converts Windows paths (C:/) to Linux format (/mnt/c/).

        Args:
            path: Path to normalize

        Returns:
            Path: Normalized path
        """
        from src.utils.system_utils import convert_to_wsl_path

        # Convert Windows paths to WSL2 format if running on WSL2
        path_obj = convert_to_wsl_path(path)

        # Expand user home directory
        if str(path).startswith('~'):
            path_obj = path_obj.expanduser()

        # Resolve to absolute path
        if not path_obj.is_absolute():
            path_obj = self._base_path / path_obj

        # Resolve symlinks and normalize
        try:
            return path_obj.resolve()
        except (OSError, RuntimeError):
            # If resolve fails, at least return absolute path
            return path_obj.absolute()

    def ensure_directory(self, path: Path | str, mode: int = 0o755) -> Path:
        """
        Ensure a directory exists, creating it if necessary.

        Args:
            path: Directory path
            mode: Directory permissions (Unix only)

        Returns:
            Path: The directory path

        Raises:
            PathError: If directory cannot be created
        """
        dir_path = self.normalize_path(path)

        try:
            dir_path.mkdir(parents=True, exist_ok=True, mode=mode)
            return dir_path
        except Exception as e:
            raise PathError(f"Failed to create directory {dir_path}: {e}")

    def ensure_parent_directory(self, file_path: Path | str, mode: int = 0o755) -> Path:
        """
        Ensure the parent directory of a file exists.

        Args:
            file_path: File path
            mode: Directory permissions (Unix only)

        Returns:
            Path: The parent directory path
        """
        file_path_obj = self.normalize_path(file_path)
        return self.ensure_directory(file_path_obj.parent, mode)

    def safe_join(self, *parts: str | Path) -> Path:
        """
        Safely join path components, preventing path traversal.

        Args:
            *parts: Path components to join

        Returns:
            Path: Joined path

        Raises:
            PathError: If resulting path would escape base path
        """
        # Join all parts
        result = self._base_path
        for part in parts:
            result = result / part

        # Normalize
        result = self.normalize_path(result)

        # Ensure result is under base path (prevent traversal)
        try:
            result.relative_to(self._base_path)
        except ValueError:
            raise PathError(
                f"Path traversal detected: {result} is outside {self._base_path}"
            )

        return result

    def get_relative_path(self, path: Path | str, base: Optional[Path | str] = None) -> Path:
        """
        Get a path relative to a base path.

        Args:
            path: The path to make relative
            base: Base path (default: manager's base path)

        Returns:
            Path: Relative path

        Raises:
            PathError: If path cannot be made relative to base
        """
        path_obj = self.normalize_path(path)
        base_obj = self.normalize_path(base) if base else self._base_path

        try:
            return path_obj.relative_to(base_obj)
        except ValueError as e:
            raise PathError(f"Cannot make {path} relative to {base_obj}: {e}")

    def is_safe_path(self, path: Path | str) -> bool:
        """
        Check if a path is safe (no traversal, exists under base).

        Args:
            path: Path to check

        Returns:
            bool: True if path is safe
        """
        try:
            normalized = self.normalize_path(path)
            normalized.relative_to(self._base_path)
            return True
        except (PathError, ValueError):
            return False

    def find_files(
        self,
        pattern: str,
        directory: Optional[Path | str] = None,
        recursive: bool = True
    ) -> List[Path]:
        """
        Find files matching a pattern.

        Args:
            pattern: Glob pattern to match
            directory: Directory to search (default: base path)
            recursive: If True, search recursively

        Returns:
            List[Path]: List of matching file paths
        """
        search_dir = self.normalize_path(directory) if directory else self._base_path

        if not search_dir.exists():
            return []

        if recursive:
            matches = list(search_dir.rglob(pattern))
        else:
            matches = list(search_dir.glob(pattern))

        # Filter to files only
        return [p for p in matches if p.is_file()]

    def get_size(self, path: Path | str) -> int:
        """
        Get the size of a file or directory.

        Args:
            path: Path to measure

        Returns:
            int: Size in bytes

        Raises:
            PathError: If path doesn't exist
        """
        path_obj = self.normalize_path(path)

        if not path_obj.exists():
            raise PathError(f"Path does not exist: {path_obj}")

        if path_obj.is_file():
            return path_obj.stat().st_size

        # For directories, sum all file sizes
        total_size = 0
        for item in path_obj.rglob('*'):
            if item.is_file():
                try:
                    total_size += item.stat().st_size
                except (OSError, PermissionError):
                    # Skip files we can't access
                    pass

        return total_size

    def clean_filename(self, filename: str, replacement: str = '_') -> str:
        """
        Clean a filename by removing/replacing invalid characters.

        Args:
            filename: Filename to clean
            replacement: Character to use for replacements

        Returns:
            str: Cleaned filename
        """
        # Remove path components
        filename = os.path.basename(filename)

        # Replace invalid characters for Windows and Unix
        invalid_chars = r'[<>:"|?*\x00-\x1f/\\]'
        cleaned = re.sub(invalid_chars, replacement, filename)

        # Remove leading/trailing dots and spaces
        cleaned = cleaned.strip('. ')

        # Ensure not empty
        if not cleaned:
            cleaned = 'unnamed'

        # Limit length (255 is max for most filesystems)
        if len(cleaned) > 255:
            name, ext = os.path.splitext(cleaned)
            max_name_len = 255 - len(ext)
            cleaned = name[:max_name_len] + ext

        return cleaned

    def get_unique_path(self, path: Path | str, suffix: str = "") -> Path:
        """
        Get a unique path by appending numbers if necessary.

        Args:
            path: Desired path
            suffix: Optional suffix to add before extension

        Returns:
            Path: Unique path that doesn't exist
        """
        path_obj = self.normalize_path(path)

        if not path_obj.exists():
            return path_obj

        # Split into stem and suffix
        stem = path_obj.stem
        suffixes = path_obj.suffixes
        parent = path_obj.parent

        # Try appending numbers
        counter = 1
        while True:
            if suffix:
                new_stem = f"{stem}_{suffix}_{counter}"
            else:
                new_stem = f"{stem}_{counter}"

            new_path = parent / (new_stem + ''.join(suffixes))

            if not new_path.exists():
                return new_path

            counter += 1

            if counter > 10000:
                raise PathError("Cannot find unique filename after 10000 attempts")


def get_common_ancestor(*paths: Path | str) -> Optional[Path]:
    """
    Find the common ancestor directory of multiple paths.

    Args:
        *paths: Paths to find common ancestor of

    Returns:
        Path or None: Common ancestor, or None if no common ancestor
    """
    if not paths:
        return None

    # Convert all to absolute paths
    abs_paths = [Path(p).resolve() for p in paths]

    if len(abs_paths) == 1:
        return abs_paths[0].parent if abs_paths[0].is_file() else abs_paths[0]

    # Find common parts
    common_parts = []
    for parts in zip(*[p.parts for p in abs_paths]):
        if len(set(parts)) == 1:
            common_parts.append(parts[0])
        else:
            break

    if not common_parts:
        return None

    return Path(*common_parts)


def is_subdirectory(child: Path | str, parent: Path | str) -> bool:
    """
    Check if a path is a subdirectory of another.

    Args:
        child: Potential child path
        parent: Potential parent path

    Returns:
        bool: True if child is under parent
    """
    try:
        child_path = Path(child).resolve()
        parent_path = Path(parent).resolve()
        child_path.relative_to(parent_path)
        return True
    except ValueError:
        return False


def format_path_for_display(path: Path | str, max_length: int = 50) -> str:
    """
    Format a path for display, truncating if necessary.

    Args:
        path: Path to format
        max_length: Maximum display length

    Returns:
        str: Formatted path
    """
    path_str = str(path)

    if len(path_str) <= max_length:
        return path_str

    # Try to show start and end
    if max_length < 10:
        return path_str[:max_length]

    # Show first and last parts with ellipsis
    show_chars = (max_length - 3) // 2
    return f"{path_str[:show_chars]}...{path_str[-show_chars:]}"
