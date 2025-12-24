#!/usr/bin/env python3
"""
Formatting utilities for imxup
Handles binary size formatting, timestamps, and string sanitization
"""

from datetime import datetime


def timestamp() -> str:
    """Return current timestamp for logging
    
    Returns:
        Current time formatted as HH:MM:SS
    """
    return datetime.now().strftime("%H:%M:%S")


def format_binary_size(num_bytes: int | float, precision: int = 1) -> str:
    """Format a byte count using binary prefixes (B, KiB, MiB, GiB, TiB).

    Uses 1024 as the step size
    Shows no decimals for bytes; otherwise uses the given precision

    Args:
        num_bytes: Number of bytes to format
        precision: Number of decimal places for non-byte units

    Returns:
        Formatted string with appropriate unit
    """
    try:
        value = float(num_bytes or 0)
    except Exception:
        value = 0.0

    # Handle negative values
    if value < 0:
        return "0\u00A0B"

    units = ["B", "K", "M", "G", "T", "P"]
    unit_index = 0

    while value >= 1024.0 and unit_index < len(units) - 1:
        value /= 1024.0
        unit_index += 1

    if units[unit_index] == "B":
        return f"{int(value)}\u00A0B"

    return f"{value:.{precision}f}\u00A0{units[unit_index]}"


def format_binary_rate(kib_per_s: float | int, precision: int = 1) -> str:
    """Format a transfer rate given in KiB/s using binary prefixes.
    
    Input is expected to be in KiB/s
    Scales to MiB/s, GiB/s, etc. as appropriate
    
    Args:
        kib_per_s: Transfer rate in KiB/s
        precision: Number of decimal places
        
    Returns:
        Formatted rate string with appropriate unit
    """
    try:
        rate = float(kib_per_s or 0)
    except Exception:
        rate = 0.0
    
    units = ["K/s", "M/s", "G/s", "T/s"]
    unit_index = 0

    while rate >= 1024.0 and unit_index < len(units) - 1:
        rate /= 1024.0
        unit_index += 1

    return f"{rate:.{precision}f}\u00A0{units[unit_index]}"


def format_duration(seconds: float) -> str:
    """Format a duration in seconds to a human-readable string
    
    Args:
        seconds: Duration in seconds
        
    Returns:
        Formatted duration string (e.g., "2h 15m 30s")
    """
    if seconds < 0:
        return "0s"
    
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    
    parts = []
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    if secs > 0 or not parts:
        parts.append(f"{secs}s")
    
    return " ".join(parts)


def sanitize_gallery_name(name: str) -> str:
    """Sanitize gallery name to remove characters not accepted in gallery name by imx.to

    Replaces characters <>:"/\\|?* with _

    Args:
        name: Original gallery name

    Returns:
        Sanitized name safe for use as filename
    """
    if name is None:
        return "untitled gallery"

    if not name:
        return "untitled"

    # Replace invalid characters
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        name = name.replace(char, '_')

    # Remove control characters
    name = ''.join(char for char in name if ord(char) >= 32)

    # Trim whitespace and dots
    name = name.strip('. ')

    # Ensure name is not empty or only underscores
    if not name or name.replace('_', '').strip() == '':
        name = "untitled"

    # Limit length
    if len(name) > 200:
        name = name[:200]

    return name


def truncate_string(text: str, max_length: int, suffix: str = "...") -> str:
    """Truncate a string to a maximum length with suffix
    
    Args:
        text: Text to truncate
        max_length: Maximum length including suffix
        suffix: Suffix to append when truncating
        
    Returns:
        Truncated string
    """
    if len(text) <= max_length:
        return text
    
    if max_length <= len(suffix):
        return suffix[:max_length]
    
    return text[:max_length - len(suffix)] + suffix


def format_percentage(value: float, precision: int = 1) -> str:
    """Format a float as a percentage string
    
    Args:
        value: Value between 0 and 1
        precision: Number of decimal places
        
    Returns:
        Formatted percentage string
    """
    percentage = value * 100
    return f"{percentage:.{precision}f}%"