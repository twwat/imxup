"""
Validation and sanitization utilities for user inputs.

This module provides comprehensive validation and sanitization functions
for various input types used throughout the imxup application.
"""

import os
import re
from typing import Optional, List, Any, Dict
from pathlib import Path
import urllib.parse


class ValidationError(Exception):
    """Raised when validation fails."""
    pass


def validate_path(path: str, must_exist: bool = False, must_be_dir: bool = False) -> Path:
    """
    Validate and sanitize a file system path.

    Args:
        path: The path to validate
        must_exist: If True, path must exist on filesystem
        must_be_dir: If True, path must be a directory

    Returns:
        Path: Validated and normalized Path object

    Raises:
        ValidationError: If path is invalid or doesn't meet requirements
    """
    if not path or not isinstance(path, (str, Path)):
        raise ValidationError("Path must be a non-empty string or Path object")

    try:
        normalized_path = Path(path).resolve()
    except (ValueError, OSError) as e:
        raise ValidationError(f"Invalid path format: {e}")

    # Check for path traversal attempts
    try:
        normalized_path.relative_to(Path.cwd())
    except ValueError:
        # Path is outside CWD - this is allowed but log it
        pass

    if must_exist and not normalized_path.exists():
        raise ValidationError(f"Path does not exist: {normalized_path}")

    if must_be_dir and normalized_path.exists() and not normalized_path.is_dir():
        raise ValidationError(f"Path is not a directory: {normalized_path}")

    return normalized_path


def validate_url(url: str, allowed_schemes: Optional[List[str]] = None) -> str:
    """
    Validate and sanitize a URL.

    Args:
        url: The URL to validate
        allowed_schemes: List of allowed URL schemes (default: ['http', 'https'])

    Returns:
        str: Validated URL

    Raises:
        ValidationError: If URL is invalid
    """
    if not url or not isinstance(url, str):
        raise ValidationError("URL must be a non-empty string")

    if allowed_schemes is None:
        allowed_schemes = ['http', 'https']

    try:
        parsed = urllib.parse.urlparse(url)
    except Exception as e:
        raise ValidationError(f"Invalid URL format: {e}")

    if not parsed.scheme:
        raise ValidationError("URL must include a scheme (http:// or https://)")

    if parsed.scheme not in allowed_schemes:
        raise ValidationError(
            f"URL scheme '{parsed.scheme}' not allowed. "
            f"Allowed schemes: {', '.join(allowed_schemes)}"
        )

    if not parsed.netloc:
        raise ValidationError("URL must include a domain name")

    return url


def validate_filename(filename: str, max_length: int = 255) -> str:
    """
    Validate and sanitize a filename.

    Args:
        filename: The filename to validate
        max_length: Maximum allowed filename length

    Returns:
        str: Sanitized filename

    Raises:
        ValidationError: If filename is invalid
    """
    if not filename or not isinstance(filename, str):
        raise ValidationError("Filename must be a non-empty string")

    # Remove any path separators to prevent directory traversal
    sanitized = os.path.basename(filename)

    if not sanitized or sanitized in ('.', '..'):
        raise ValidationError("Invalid filename")

    # Check for invalid characters (Windows + Unix)
    invalid_chars = r'[<>:"|?*\x00-\x1f]'
    if re.search(invalid_chars, sanitized):
        raise ValidationError("Filename contains invalid characters")

    if len(sanitized) > max_length:
        raise ValidationError(f"Filename too long (max {max_length} characters)")

    return sanitized


def validate_gallery_name(name: str, min_length: int = 1, max_length: int = 200) -> str:
    """
    Validate a gallery name.

    Args:
        name: The gallery name to validate
        min_length: Minimum allowed length
        max_length: Maximum allowed length

    Returns:
        str: Validated gallery name

    Raises:
        ValidationError: If name is invalid
    """
    if not name or not isinstance(name, str):
        raise ValidationError("Gallery name must be a non-empty string")

    # Strip whitespace
    name = name.strip()

    if len(name) < min_length:
        raise ValidationError(f"Gallery name must be at least {min_length} characters")

    if len(name) > max_length:
        raise ValidationError(f"Gallery name must not exceed {max_length} characters")

    # Check for potentially problematic characters
    if re.search(r'[\x00-\x1f\x7f-\x9f]', name):
        raise ValidationError("Gallery name contains control characters")

    return name


def validate_image_extensions(extensions: List[str]) -> List[str]:
    """
    Validate a list of image file extensions.

    Args:
        extensions: List of file extensions (with or without leading dot)

    Returns:
        List[str]: Normalized extensions (lowercase, with leading dot)

    Raises:
        ValidationError: If any extension is invalid
    """
    if not extensions:
        raise ValidationError("Extension list cannot be empty")

    valid_extensions = []
    for ext in extensions:
        if not isinstance(ext, str):
            raise ValidationError("Extensions must be strings")

        # Normalize: lowercase, ensure leading dot
        ext = ext.lower().strip()
        if not ext.startswith('.'):
            ext = f'.{ext}'

        # Validate format (alphanumeric only)
        if not re.match(r'^\.[a-z0-9]+$', ext):
            raise ValidationError(f"Invalid extension format: {ext}")

        valid_extensions.append(ext)

    return list(set(valid_extensions))  # Remove duplicates


def validate_credentials(username: str, password: str) -> tuple[str, str]:
    """
    Validate username and password credentials.

    Args:
        username: Username to validate
        password: Password to validate

    Returns:
        tuple: (validated_username, validated_password)

    Raises:
        ValidationError: If credentials are invalid
    """
    if not username or not isinstance(username, str):
        raise ValidationError("Username must be a non-empty string")

    if not password or not isinstance(password, str):
        raise ValidationError("Password must be a non-empty string")

    username = username.strip()

    if len(username) < 1:
        raise ValidationError("Username cannot be empty")

    if len(username) > 255:
        raise ValidationError("Username too long (max 255 characters)")

    if len(password) < 1:
        raise ValidationError("Password cannot be empty")

    # Don't validate password format - let the service decide
    # Just ensure it's not empty and not too long to prevent DoS
    if len(password) > 1000:
        raise ValidationError("Password too long (max 1000 characters)")

    return username, password


def validate_port(port: Any) -> int:
    """
    Validate a network port number.

    Args:
        port: Port number to validate (int or str)

    Returns:
        int: Validated port number

    Raises:
        ValidationError: If port is invalid
    """
    try:
        port_int = int(port)
    except (ValueError, TypeError):
        raise ValidationError("Port must be a valid integer")

    if port_int < 1 or port_int > 65535:
        raise ValidationError("Port must be between 1 and 65535")

    return port_int


def validate_positive_int(value: Any, name: str = "Value", max_value: Optional[int] = None) -> int:
    """
    Validate a positive integer value.

    Args:
        value: Value to validate
        name: Name of the value for error messages
        max_value: Optional maximum allowed value

    Returns:
        int: Validated integer

    Raises:
        ValidationError: If value is invalid
    """
    try:
        int_value = int(value)
    except (ValueError, TypeError):
        raise ValidationError(f"{name} must be a valid integer")

    if int_value < 1:
        raise ValidationError(f"{name} must be positive")

    if max_value is not None and int_value > max_value:
        raise ValidationError(f"{name} must not exceed {max_value}")

    return int_value


def sanitize_html(text: str) -> str:
    """
    Sanitize text by removing HTML tags and potentially dangerous content.

    Args:
        text: Text to sanitize

    Returns:
        str: Sanitized text
    """
    if not text:
        return ""

    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)

    # Remove script and style content
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)

    # Decode HTML entities
    import html
    text = html.unescape(text)

    return text.strip()


def validate_config_dict(config: Dict[str, Any], required_keys: List[str]) -> Dict[str, Any]:
    """
    Validate that a configuration dictionary contains required keys.

    Args:
        config: Configuration dictionary to validate
        required_keys: List of required key names

    Returns:
        Dict[str, Any]: The validated config dictionary

    Raises:
        ValidationError: If required keys are missing
    """
    if not isinstance(config, dict):
        raise ValidationError("Configuration must be a dictionary")

    missing_keys = [key for key in required_keys if key not in config]

    if missing_keys:
        raise ValidationError(
            f"Missing required configuration keys: {', '.join(missing_keys)}"
        )

    return config
