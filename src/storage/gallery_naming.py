"""
Gallery naming utilities and helpers.

Provides functions for generating, validating, and managing gallery names
with support for templates, auto-naming, and collision handling.
"""

import re
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime
import hashlib


class GalleryNamingError(Exception):
    """Raised when gallery naming operations fail."""
    pass


class GalleryNameGenerator:
    """
    Generate gallery names using various strategies.
    """

    def __init__(self, default_prefix: str = "Gallery"):
        """
        Initialize gallery name generator.

        Args:
            default_prefix: Default prefix for auto-generated names
        """
        self._default_prefix = default_prefix

    def from_folder_name(self, folder_path: Path | str) -> str:
        """
        Generate gallery name from folder name.

        Args:
            folder_path: Path to the folder

        Returns:
            str: Gallery name based on folder name
        """
        folder_path = Path(folder_path)
        name = folder_path.name

        # Clean the name
        name = self._clean_name(name)

        if not name:
            name = self._default_prefix

        return name

    def from_template(
        self,
        template: str,
        folder_path: Path | str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Generate gallery name from a template.

        Supported placeholders:
        - {folder}: Folder name
        - {date}: Current date (YYYY-MM-DD)
        - {time}: Current time (HH-MM-SS)
        - {timestamp}: Unix timestamp
        - {count}: Image count (if provided in metadata)
        - {size}: Folder size (if provided in metadata)

        Args:
            template: Template string with placeholders
            folder_path: Path to the folder
            metadata: Optional metadata dictionary

        Returns:
            str: Generated gallery name
        """
        folder_path = Path(folder_path)
        metadata = metadata or {}

        now = datetime.now()

        replacements = {
            'folder': folder_path.name,
            'date': now.strftime('%Y-%m-%d'),
            'time': now.strftime('%H-%M-%S'),
            'timestamp': str(int(now.timestamp())),
            'count': str(metadata.get('image_count', 0)),
            'size': str(metadata.get('folder_size', 0))
        }

        # Add any custom metadata
        for key, value in metadata.items():
            if key not in replacements:
                replacements[key] = str(value)

        # Replace placeholders
        name = template
        for key, value in replacements.items():
            name = name.replace(f'{{{key}}}', value)

        # Clean the result
        name = self._clean_name(name)

        if not name:
            name = self._default_prefix

        return name

    def with_timestamp(self, base_name: str) -> str:
        """
        Add timestamp to a gallery name.

        Args:
            base_name: Base gallery name

        Returns:
            str: Name with timestamp appended
        """
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        return f"{base_name}_{timestamp}"

    def with_hash(self, base_name: str, source: str = "") -> str:
        """
        Add a short hash to a gallery name for uniqueness.

        Args:
            base_name: Base gallery name
            source: Optional source string for hash (default: current time)

        Returns:
            str: Name with hash appended
        """
        if not source:
            source = str(datetime.now().timestamp())

        hash_obj = hashlib.md5(source.encode())
        short_hash = hash_obj.hexdigest()[:8]

        return f"{base_name}_{short_hash}"

    def auto_generate(
        self,
        folder_path: Path | str,
        strategy: str = "folder",
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Auto-generate a gallery name using the specified strategy.

        Strategies:
        - "folder": Use folder name
        - "timestamp": Use folder name + timestamp
        - "hash": Use folder name + hash
        - "date": Use folder name + date

        Args:
            folder_path: Path to the folder
            strategy: Naming strategy
            metadata: Optional metadata

        Returns:
            str: Generated gallery name

        Raises:
            GalleryNamingError: If strategy is invalid
        """
        folder_path = Path(folder_path)
        base_name = self.from_folder_name(folder_path)

        if strategy == "folder":
            return base_name
        elif strategy == "timestamp":
            return self.with_timestamp(base_name)
        elif strategy == "hash":
            return self.with_hash(base_name, str(folder_path))
        elif strategy == "date":
            date_str = datetime.now().strftime('%Y-%m-%d')
            return f"{base_name}_{date_str}"
        else:
            raise GalleryNamingError(f"Unknown naming strategy: {strategy}")

    def _clean_name(self, name: str) -> str:
        """
        Clean a gallery name by removing invalid characters.

        Args:
            name: Name to clean

        Returns:
            str: Cleaned name
        """
        # Remove leading/trailing whitespace
        name = name.strip()

        # Replace invalid characters with underscores
        name = re.sub(r'[<>:"|?*\x00-\x1f/\\]', '_', name)

        # Replace multiple underscores/spaces with single underscore
        name = re.sub(r'[_\s]+', '_', name)

        # Remove leading/trailing underscores
        name = name.strip('_')

        return name


class GalleryNameValidator:
    """
    Validate gallery names against rules and constraints.
    """

    def __init__(
        self,
        min_length: int = 1,
        max_length: int = 200,
        allow_unicode: bool = True
    ):
        """
        Initialize validator.

        Args:
            min_length: Minimum name length
            max_length: Maximum name length
            allow_unicode: Whether to allow Unicode characters
        """
        self._min_length = min_length
        self._max_length = max_length
        self._allow_unicode = allow_unicode

    def validate(self, name: str) -> tuple[bool, List[str]]:
        """
        Validate a gallery name.

        Args:
            name: Gallery name to validate

        Returns:
            tuple: (is_valid, list_of_issues)
        """
        issues = []

        # Check length
        if len(name) < self._min_length:
            issues.append(f"Name must be at least {self._min_length} characters")

        if len(name) > self._max_length:
            issues.append(f"Name must not exceed {self._max_length} characters")

        # Check for empty after stripping
        if not name.strip():
            issues.append("Name cannot be empty or whitespace only")

        # Check for invalid characters
        invalid_chars = r'[<>:"|?*\x00-\x1f/\\]'
        if re.search(invalid_chars, name):
            issues.append("Name contains invalid characters")

        # Check Unicode if not allowed
        if not self._allow_unicode and not name.isascii():
            issues.append("Name must contain only ASCII characters")

        # Check for reserved names (Windows)
        reserved_names = {'CON', 'PRN', 'AUX', 'NUL', 'COM1', 'COM2', 'COM3', 'COM4',
                         'COM5', 'COM6', 'COM7', 'COM8', 'COM9', 'LPT1', 'LPT2',
                         'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9'}

        if name.upper() in reserved_names:
            issues.append(f"Name '{name}' is a reserved system name")

        return len(issues) == 0, issues

    def is_valid(self, name: str) -> bool:
        """
        Check if a gallery name is valid.

        Args:
            name: Gallery name to check

        Returns:
            bool: True if valid
        """
        is_valid, _ = self.validate(name)
        return is_valid


class GalleryNameRegistry:
    """
    Track used gallery names and handle collisions.
    """

    def __init__(self):
        """Initialize name registry."""
        self._used_names: set[str] = set()

    def register(self, name: str) -> None:
        """
        Register a gallery name as used.

        Args:
            name: Gallery name to register
        """
        self._used_names.add(name.lower())

    def is_used(self, name: str) -> bool:
        """
        Check if a gallery name is already used.

        Args:
            name: Gallery name to check

        Returns:
            bool: True if name is used
        """
        return name.lower() in self._used_names

    def get_unique_name(
        self,
        base_name: str,
        max_attempts: int = 1000
    ) -> str:
        """
        Get a unique gallery name by appending numbers if necessary.

        Args:
            base_name: Base name to make unique
            max_attempts: Maximum number of attempts

        Returns:
            str: Unique gallery name

        Raises:
            GalleryNamingError: If cannot find unique name
        """
        if not self.is_used(base_name):
            return base_name

        # Try appending numbers
        for i in range(1, max_attempts):
            candidate = f"{base_name} ({i})"
            if not self.is_used(candidate):
                return candidate

        raise GalleryNamingError(
            f"Cannot find unique name after {max_attempts} attempts"
        )

    def clear(self) -> None:
        """Clear all registered names."""
        self._used_names.clear()

    def get_all_names(self) -> List[str]:
        """
        Get all registered names.

        Returns:
            List[str]: List of registered names
        """
        return list(self._used_names)


def suggest_gallery_names(
    folder_path: Path | str,
    count: int = 5,
    metadata: Optional[Dict[str, Any]] = None
) -> List[str]:
    """
    Suggest multiple gallery name options.

    Args:
        folder_path: Path to the folder
        count: Number of suggestions to generate
        metadata: Optional metadata

    Returns:
        List[str]: List of suggested names
    """
    generator = GalleryNameGenerator()
    suggestions = []

    # Strategy 1: Folder name
    suggestions.append(generator.from_folder_name(folder_path))

    # Strategy 2: Folder name + date
    suggestions.append(generator.auto_generate(folder_path, "date"))

    # Strategy 3: Folder name + timestamp
    suggestions.append(generator.auto_generate(folder_path, "timestamp"))

    # Strategy 4: Template with count if available
    if metadata and 'image_count' in metadata:
        template = "{folder} - {count} images"
        suggestions.append(generator.from_template(template, folder_path, metadata))

    # Strategy 5: Template with date and count
    if metadata and 'image_count' in metadata:
        template = "{folder} ({date}) - {count} images"
        suggestions.append(generator.from_template(template, folder_path, metadata))

    # Return unique suggestions up to count
    unique_suggestions = []
    seen = set()

    for suggestion in suggestions:
        if suggestion not in seen:
            unique_suggestions.append(suggestion)
            seen.add(suggestion)

        if len(unique_suggestions) >= count:
            break

    return unique_suggestions


def normalize_gallery_name(name: str) -> str:
    """
    Normalize a gallery name to standard format.

    Args:
        name: Gallery name to normalize

    Returns:
        str: Normalized name
    """
    # Trim whitespace
    name = name.strip()

    # Replace multiple spaces with single space
    name = re.sub(r'\s+', ' ', name)

    # Replace invalid characters
    name = re.sub(r'[<>:"|?*\x00-\x1f/\\]', '_', name)

    return name
