"""
Unified logging system for imxup.

Provides a single, simple logging interface that works everywhere:
- Main thread (CLI or GUI)
- Worker threads
- Any module or class

Usage:
    from src.utils.logger import log, trace, debug

    log("Simple message")                              # INFO level, general category
    log("Error occurred", level="error")               # ERROR level
    log("Auth successful", category="auth")            # INFO level, auth category
    log("Debug info", level="debug", category="network")  # DEBUG level, network category
    trace("Verbose details")                           # TRACE level (never logged to file)

Log Levels (lowest to highest):
    - TRACE (5): Extremely verbose, never written to file, only console/GUI
    - DEBUG (10): Development debugging info
    - INFO (20): General informational messages
    - WARNING (30): Warning messages
    - ERROR (40): Error messages
    - CRITICAL (50): Critical failures

The logger automatically:
- Routes to GUI log viewer when GUI is active
- Routes to console when in CLI mode
- Writes to file log (if enabled) - EXCEPT trace level
- Handles thread safety
- Adds timestamps
- Detects categories from [tags] for backwards compatibility
- Detects log levels from message prefixes for backwards compatibility
"""

from __future__ import annotations
import threading
import logging
import sys
from typing import Optional, TYPE_CHECKING
from datetime import datetime

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QWidget

# Thread safety
_lock = threading.Lock()

# GUI reference (set by main window on startup)
_main_window: Optional['QWidget'] = None

# Log viewer references (registered when dialogs open)
_log_viewers: list = []

# Lazy import holder for AppLogger
_app_logger = None

# Debug mode flag - when True, bypass all filters and print everything to console
# Set via --debug command line flag
_debug_mode = '--debug' in sys.argv

# Custom TRACE level (below DEBUG, never logged to file)
TRACE = 5
logging.addLevelName(TRACE, "TRACE")

# Log level mapping
LEVEL_MAP = {
    "trace": TRACE,  # Custom level, never logged to file
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "warn": logging.WARNING,  # Alias
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}


def timestamp() -> str:
    """Return current timestamp in HH:MM:SS format."""
    return datetime.now().strftime("%H:%M:%S")


def set_main_window(main_window: 'QWidget') -> None:
    """
    Set the main window reference for GUI logging.
    Called by main window on startup.

    Args:
        main_window: Reference to ImxUploadGUI main window
    """
    global _main_window
    with _lock:
        _main_window = main_window


def register_log_viewer(viewer) -> None:
    """
    Register a log viewer dialog to receive log messages with metadata.
    Called by LogViewerDialog on open.

    Args:
        viewer: LogViewerDialog instance
    """
    global _log_viewers
    with _lock:
        if viewer not in _log_viewers:
            _log_viewers.append(viewer)


def unregister_log_viewer(viewer) -> None:
    """
    Unregister a log viewer dialog.
    Called by LogViewerDialog on close.

    Args:
        viewer: LogViewerDialog instance
    """
    global _log_viewers
    with _lock:
        if viewer in _log_viewers:
            _log_viewers.remove(viewer)


def _get_app_logger():
    """Get the AppLogger singleton lazily to avoid circular imports."""
    global _app_logger
    if _app_logger is None:
        try:
            from src.utils.logging import get_logger
            _app_logger = get_logger()
        except ImportError:
            # Fallback if logging module not available
            _app_logger = None
    return _app_logger


def _detect_level_from_message(message: str) -> Optional[str]:
    """
    Auto-detect log level from message content for backwards compatibility.

    Returns:
        Log level string or None if not detected
    """
    message_upper = message.upper()

    # Check for explicit prefixes
    if message_upper.startswith("CRITICAL:") or "CRITICAL" in message_upper[:20]:
        return "critical"
    elif message_upper.startswith("ERROR:") or "ERROR" in message_upper[:20]:
        return "error"
    elif message_upper.startswith("WARNING:") or message_upper.startswith("WARN:") or "WARNING" in message_upper[:20]:
        return "warning"
    elif message_upper.startswith("DEBUG:") or "DEBUG" in message_upper[:20]:
        return "debug"
    elif message_upper.startswith("TRACE:") or "TRACE" in message_upper[:20]:
        return "trace"

    return None


def _detect_category_from_message(message: str) -> tuple[str, Optional[str], str]:
    """
    Auto-detect category from [tag] format for backwards compatibility.

    Returns:
        Tuple of (category, subtype, cleaned_message)
    """
    # Skip timestamp if present
    parts = message.split(" ", 1)
    if len(parts) > 1 and parts[0].count(":") == 2:
        # Has timestamp, work with rest
        header = parts[1]
        timestamp_part = parts[0] + " "
    else:
        header = message
        timestamp_part = ""

    # Check for [category] or [category:subtype] format
    if header.startswith("[") and "]" in header:
        close_idx = header.find("]")
        tag = header[1:close_idx]
        rest = header[close_idx + 1:].lstrip()

        # Parse category and subtype
        if ":" in tag:
            category, subtype = tag.split(":", 1)
        else:
            category = tag
            subtype = None

        # Return cleaned message without the tag
        cleaned_message = timestamp_part + rest
        return category, subtype, cleaned_message

    return "general", None, message


def log(message: str,
        level: Optional[str] = None,
        category: Optional[str] = None) -> None:
    """
    Universal logging function that works everywhere.

    Args:
        message: The log message to output
        level: Log level (trace/debug/info/warning/error/critical).
               If None, auto-detects from message or defaults to 'info'
               NOTE: 'trace' level is never written to log files
        category: Category for filtering (general/auth/uploads/network/etc).
                  If None, auto-detects from [tag] or defaults to 'general'

    Examples:
        log("Starting application")
        log("Connection failed", level="error")
        log("User logged in", category="auth")
        log("[uploads] File uploaded successfully")  # Auto-detects category
        log("ERROR: Database connection lost")       # Auto-detects level
        log("Verbose details", level="trace")        # TRACE: console/GUI only, never to file

    The function will:
        - Add timestamp if not present
        - Route to GUI log viewer when GUI is active
        - Route to console when in CLI mode
        - Write to file log if enabled (EXCEPT trace level)
        - Handle thread safety automatically
    """
    with _lock:
        # Auto-detect level if not provided
        if level is None:
            detected_level = _detect_level_from_message(message)
            level = detected_level or "info"

        # Normalize level
        level = level.lower()
        if level not in LEVEL_MAP:
            level = "info"

        # Get numeric log level
        log_level = LEVEL_MAP[level]

        # Auto-detect category if not provided
        if category is None:
            detected_cat, subtype, cleaned_msg = _detect_category_from_message(message)
            category = detected_cat
            # Don't clean the message if category was explicitly provided
            # This preserves backwards compatibility with [tag] format
        else:
            # Parse category:subtype if colon is present (e.g., "uploads:file")
            if ":" in category:
                category, subtype = category.split(":", 1)
            else:
                subtype = None
            cleaned_msg = message

        # Add log level prefix (unless already present)
        level_prefix = ""
        # Check if message already has the level prefix anywhere in first 50 chars
        msg_upper = cleaned_msg.upper()[:50]
        if level == "trace" and "TRACE:" not in msg_upper:
            level_prefix = "TRACE: "
        elif level == "debug" and "DEBUG:" not in msg_upper:
            level_prefix = "DEBUG: "
        elif level == "info" and "INFO:" not in msg_upper:
            level_prefix = "INFO: "
        elif level == "warning" and "WARNING:" not in msg_upper and "WARN:" not in msg_upper:
            level_prefix = "WARNING: "
        elif level == "error" and "ERROR:" not in msg_upper:
            level_prefix = "ERROR: "
        elif level == "critical" and "CRITICAL:" not in msg_upper:
            level_prefix = "CRITICAL: "

        # Ensure timestamp
        if not (cleaned_msg and len(cleaned_msg) > 8 and cleaned_msg[2] == ":" and cleaned_msg[5] == ":"):
            # No timestamp detected, add one
            formatted_message = f"{timestamp()} {level_prefix}{cleaned_msg}"
        else:
            # Timestamp exists, insert level prefix after it
            parts = cleaned_msg.split(" ", 1)
            if len(parts) > 1:
                formatted_message = f"{parts[0]} {level_prefix}{parts[1]}"
            else:
                formatted_message = f"{cleaned_msg} {level_prefix}"

        # Add category tag if it's not general and wasn't in original
        if category != "general" and not message.startswith("["):
            # Build tag with subtype if present
            tag = f"[{category}:{subtype}]" if subtype else f"[{category}]"
            # Find where to insert the tag (after timestamp and level prefix)
            parts = formatted_message.split(" ", 2)
            if len(parts) >= 2 and parts[0].count(":") == 2:
                # Has timestamp
                if parts[1].endswith(":"):
                    # Has level prefix
                    formatted_message = f"{parts[0]} {parts[1]} {tag} {' '.join(parts[2:])}"
                else:
                    # No level prefix
                    formatted_message = f"{parts[0]} {tag} {' '.join(parts[1:])}"
            else:
                formatted_message = f"{tag} {formatted_message}"

        # Get AppLogger for file logging
        app_logger = _get_app_logger()

        # Check upload success filtering EARLY (applies to ALL outputs: file, console, GUI)
        if category == "uploads" and subtype and app_logger:
            if subtype == "file" and not app_logger.should_log_upload_file_success("gui"):
                return  # Block file-level upload success messages everywhere
            if subtype == "gallery" and not app_logger.should_log_upload_gallery_success("gui"):
                return  # Block gallery-level upload success messages everywhere

        # 1. Always try file logging (if enabled)
        if app_logger:
            try:
                if app_logger.should_emit_file(category, log_level):
                    app_logger.log_to_file(formatted_message, log_level, category)
            except Exception:
                # Don't let file logging errors break the app
                pass

        # 2. Route to appropriate display
        # Debug mode: print everything to console
        if _debug_mode:
            print(formatted_message, file=sys.stderr if log_level >= logging.WARNING else sys.stdout, flush=True)

        # CRITICAL: Always print ERROR and CRITICAL to console, even in GUI mode
        # This ensures crash messages are always visible
        elif log_level >= logging.ERROR:
            print(formatted_message, file=sys.stderr, flush=True)

        # Also print WARNING to console so issues are visible
        elif log_level == logging.WARNING and not _main_window:
            print(formatted_message, file=sys.stderr, flush=True)

        if _main_window:
            # GUI is available: Send to main window's simple log display
            try:
                # Check if should show in GUI based on filters
                if app_logger and not app_logger.should_emit_gui(category, log_level):
                    return

                # Send to main window's simple log display (Qt handles cross-thread signals safely)
                if hasattr(_main_window, 'add_log_message'):
                    _main_window.add_log_message(formatted_message)
            except Exception:
                # Fallback to console if GUI logging fails
                print(formatted_message, file=sys.stderr if log_level >= logging.WARNING else sys.stdout, flush=True)

        # Send to all registered log viewers with metadata (independent of main window)
        for viewer in _log_viewers[:]:  # Copy to avoid modification during iteration
            try:
                if hasattr(viewer, 'append_message'):
                    viewer.append_message(
                        message=formatted_message,
                        level=level,
                        category=category
                    )
            except Exception:
                # Viewer may have been closed/deleted, remove it
                try:
                    with _lock:
                        if viewer in _log_viewers:
                            _log_viewers.remove(viewer)
                except Exception:
                    pass

        # Only print to console if there's NO GUI at all (CLI mode)
        if not _main_window and not _debug_mode and log_level < logging.WARNING:
            # CLI mode - print info/debug to console
            print(formatted_message, flush=True)


# Convenience functions for specific log levels
def trace(message: str, category: Optional[str] = None) -> None:
    """Log a trace message (never written to file, only console/GUI)."""
    log(message, level="trace", category=category)


def debug(message: str, category: Optional[str] = None) -> None:
    """Log a debug message."""
    log(message, level="debug", category=category)


def info(message: str, category: Optional[str] = None) -> None:
    """Log an info message."""
    log(message, level="info", category=category)


def warning(message: str, category: Optional[str] = None) -> None:
    """Log a warning message."""
    log(message, level="warning", category=category)


def error(message: str, category: Optional[str] = None) -> None:
    """Log an error message."""
    log(message, level="error", category=category)


def critical(message: str, category: Optional[str] = None) -> None:
    """Log a critical message."""
    log(message, level="critical", category=category)


def install_exception_hook() -> None:
    """
    Install global exception hook to ensure unhandled exceptions are always visible.
    Call this early in application startup.
    """
    original_hook = sys.excepthook

    def exception_handler(exc_type, exc_value, exc_traceback):
        """Handle uncaught exceptions by forcing them to console."""
        import traceback

        # Format the exception
        tb_lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
        error_msg = ''.join(tb_lines)

        # ALWAYS print to stderr (bypass all filters)
        print(f"\n{'='*70}", file=sys.stderr, flush=True)
        print("UNHANDLED EXCEPTION:", file=sys.stderr, flush=True)
        print(error_msg, file=sys.stderr, flush=True)
        print(f"{'='*70}\n", file=sys.stderr, flush=True)

        # Try to log it too (but don't fail if logging is broken)
        try:
            critical(f"Unhandled exception: {exc_type.__name__}: {exc_value}", category="general")
        except Exception:
            pass

        # Call original hook
        original_hook(exc_type, exc_value, exc_traceback)

    sys.excepthook = exception_handler