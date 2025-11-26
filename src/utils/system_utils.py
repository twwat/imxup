"""
System utility functions for platform detection, environment handling, and system operations.

This module provides cross-platform utilities for system-level operations
used throughout the imxup application.
"""

import os
import sys
import platform
import tempfile
import shutil
from typing import Optional, Dict, Any
from pathlib import Path
import subprocess


def get_platform_info() -> Dict[str, str]:
    """
    Get detailed information about the current platform.

    Returns:
        Dict containing platform information:
        - system: OS name (Windows, Linux, Darwin)
        - release: OS release version
        - version: OS version details
        - machine: Machine type (x86_64, etc.)
        - processor: Processor name
        - python_version: Python version
    """
    return {
        'system': platform.system(),
        'release': platform.release(),
        'version': platform.version(),
        'machine': platform.machine(),
        'processor': platform.processor(),
        'python_version': platform.python_version(),
    }


def is_windows() -> bool:
    """Check if running on Windows."""
    return platform.system() == 'Windows'


def is_linux() -> bool:
    """Check if running on Linux."""
    return platform.system() == 'Linux'


def is_macos() -> bool:
    """Check if running on macOS."""
    return platform.system() == 'Darwin'


def get_home_directory() -> Path:
    """
    Get the user's home directory in a cross-platform way.

    Returns:
        Path: User's home directory
    """
    return Path.home()


def get_app_data_directory(app_name: str = 'imxup') -> Path:
    """
    Get the appropriate application data directory for the current platform.

    On Windows: %APPDATA%/imxup
    On macOS: ~/Library/Application Support/imxup
    On Linux: ~/.config/imxup

    Args:
        app_name: Name of the application

    Returns:
        Path: Application data directory (created if it doesn't exist)
    """
    if is_windows():
        base = Path(os.getenv('APPDATA', Path.home() / 'AppData' / 'Roaming'))
    elif is_macos():
        base = Path.home() / 'Library' / 'Application Support'
    else:  # Linux and other Unix-like
        base = Path(os.getenv('XDG_CONFIG_HOME', Path.home() / '.config'))

    app_dir = base / app_name
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir


def get_temp_directory(app_name: str = 'imxup') -> Path:
    """
    Get a temporary directory for the application.

    Args:
        app_name: Name of the application

    Returns:
        Path: Temporary directory (created if it doesn't exist)
    """
    temp_base = Path(tempfile.gettempdir())
    app_temp = temp_base / app_name
    app_temp.mkdir(parents=True, exist_ok=True)
    return app_temp


def get_executable_path() -> Path:
    """
    Get the path to the current executable or script.

    Returns:
        Path: Path to the executable or main script
    """
    if getattr(sys, 'frozen', False):
        # Running as compiled executable
        return Path(sys.executable)
    else:
        # Running as script
        return Path(sys.argv[0]).resolve()


def get_resource_path(relative_path: str) -> Path:
    """
    Get the absolute path to a resource file.

    Works both when running as script and as frozen executable.

    Args:
        relative_path: Relative path to the resource

    Returns:
        Path: Absolute path to the resource
    """
    if getattr(sys, 'frozen', False):
        # Running as compiled executable
        base_path = Path(sys._MEIPASS)
    else:
        # Running as script
        base_path = Path(__file__).parent.parent.parent

    return base_path / relative_path


def get_available_disk_space(path: Path) -> int:
    """
    Get available disk space at the given path.

    Args:
        path: Path to check

    Returns:
        int: Available space in bytes
    """
    stat = shutil.disk_usage(path)
    return stat.free


def format_bytes(bytes_count: int, precision: int = 2) -> str:
    """
    Format bytes as human-readable string.

    Args:
        bytes_count: Number of bytes
        precision: Decimal precision

    Returns:
        str: Formatted string (e.g., "1.23 GB")
    """
    for unit in ['B', 'KB', 'MB', 'GB', 'TB', 'PB']:
        if abs(bytes_count) < 1024.0:
            return f"{bytes_count:.{precision}f} {unit}"
        bytes_count /= 1024.0
    return f"{bytes_count:.{precision}f} PB"


def ensure_directory_exists(path: Path) -> Path:
    """
    Ensure a directory exists, creating it if necessary.

    Args:
        path: Directory path

    Returns:
        Path: The directory path
    """
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_remove_file(path: Path) -> bool:
    """
    Safely remove a file, ignoring errors if it doesn't exist.

    Args:
        path: File path to remove

    Returns:
        bool: True if file was removed, False otherwise
    """
    try:
        Path(path).unlink(missing_ok=True)
        return True
    except Exception:
        return False


def safe_remove_directory(path: Path, recursive: bool = False) -> bool:
    """
    Safely remove a directory.

    Args:
        path: Directory path to remove
        recursive: If True, remove directory and all contents

    Returns:
        bool: True if directory was removed, False otherwise
    """
    try:
        path = Path(path)
        if not path.exists():
            return True

        if recursive:
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.rmdir()
        return True
    except Exception:
        return False


def get_environment_variable(name: str, default: Optional[str] = None) -> Optional[str]:
    """
    Get an environment variable with optional default.

    Args:
        name: Environment variable name
        default: Default value if not set

    Returns:
        str or None: Environment variable value or default
    """
    return os.getenv(name, default)


def set_environment_variable(name: str, value: str) -> None:
    """
    Set an environment variable.

    Args:
        name: Environment variable name
        value: Value to set
    """
    os.environ[name] = value


def execute_command(command: list[str], timeout: Optional[int] = None) -> tuple[int, str, str]:
    """
    Execute a system command safely.

    Args:
        command: Command and arguments as a list
        timeout: Optional timeout in seconds

    Returns:
        tuple: (return_code, stdout, stderr)
    """
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"Command timed out after {timeout} seconds"
    except Exception as e:
        return -1, "", str(e)


def get_system_hostname() -> str:
    """
    Get the system hostname.

    Returns:
        str: System hostname
    """
    return platform.node()


def get_system_username() -> str:
    """
    Get the current system username.

    Returns:
        str: Username
    """
    if is_windows():
        return os.getenv('USERNAME', 'unknown')
    else:
        return os.getenv('USER', 'unknown')


def is_admin() -> bool:
    """
    Check if the current process has administrator/root privileges.

    Returns:
        bool: True if running with elevated privileges
    """
    try:
        if is_windows():
            import ctypes
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        else:
            return os.geteuid() == 0
    except Exception:
        return False


def get_cpu_count() -> int:
    """
    Get the number of CPU cores available.

    Returns:
        int: Number of CPU cores
    """
    return os.cpu_count() or 1


def get_optimal_thread_count(max_threads: Optional[int] = None) -> int:
    """
    Get an optimal thread count for parallel operations.

    Args:
        max_threads: Optional maximum thread count

    Returns:
        int: Recommended thread count
    """
    cpu_count = get_cpu_count()
    # Use CPU count, but leave one core free for system operations
    optimal = max(1, cpu_count - 1)

    if max_threads is not None:
        optimal = min(optimal, max_threads)

    return optimal


def is_wsl2() -> bool:
    """
    Detect if running on Windows Subsystem for Linux 2 (WSL2).

    Returns:
        bool: True if running on WSL2, False otherwise
    """
    if not is_linux():
        return False

    try:
        release = platform.release().lower()
        return 'microsoft' in release or 'wsl' in release
    except Exception:
        return False


def convert_to_wsl_path(path: str | Path) -> Path:
    """
    Convert Windows path to WSL2 format if running on WSL2.

    Converts: C:/path/to/file -> /mnt/c/path/to/file

    Args:
        path: Path to convert (can be Windows or Linux format)

    Returns:
        Path: Converted path in WSL2 format if applicable, otherwise original path
    """
    path_str = str(path)

    # No conversion needed if not on WSL2
    if not is_wsl2():
        return Path(path_str)

    # Convert Windows drive paths (C:/, C:\, etc.) to WSL2 mount format
    import re
    pattern = r'^([A-Za-z]):[/\\](.*)$'
    match = re.match(pattern, path_str)

    if match:
        drive = match.group(1).lower()
        rest = match.group(2).replace('\\', '/')
        wsl_path = f'/mnt/{drive}/{rest}'
        return Path(wsl_path)

    # Path is already in Linux format or relative
    return Path(path_str)


def convert_from_wsl_path(path: str | Path) -> Path:
    """
    Convert WSL2 path to Windows format if needed.

    Converts: /mnt/c/path/to/file -> C:/path/to/file

    Args:
        path: WSL2 path to convert

    Returns:
        Path: Converted path in Windows format if applicable, otherwise original path
    """
    path_str = str(path)

    # Convert WSL2 mount paths (/mnt/c/) to Windows format
    import re
    pattern = r'^/mnt/([a-z])/(.*)$'
    match = re.match(pattern, path_str)

    if match:
        drive = match.group(1).upper()
        rest = match.group(2)
        windows_path = f'{drive}:/{rest}'
        return Path(windows_path)

    # Path is already in Windows format or not a WSL mount
    return Path(path_str)
