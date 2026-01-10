#!/usr/bin/env python3
"""
imx.to gallery uploader
Upload image folders to imx.to as galleries
"""

import sys
import os
from datetime import datetime

# Console hiding moved to after GUI window appears (see line ~2220)

# Check for --debug flag early (before heavy imports)
DEBUG_MODE = '--debug' in sys.argv

def debug_print(msg):
    """Print debug message if DEBUG_MODE is enabled, otherwise print on same line"""
    # Skip printing if no console exists (console=False build)
    if sys.stdout is None:
        return
    try:
        if DEBUG_MODE:
            timestamp = datetime.now().strftime("%H:%M:%S")
            print(f"{timestamp} {msg}")
            sys.stdout.flush()
        else:
            # Print on same line, overwriting previous output
            try:
                terminal_width = os.get_terminal_size().columns
            except (OSError, AttributeError):
                terminal_width = 80  # Fallback for no terminal
            print(f"\r{msg:<{terminal_width}}", end='', flush=True)
    except (OSError, AttributeError):
        # Console operations failed, silently ignore
        pass

import requests
from requests.adapters import HTTPAdapter
import pycurl
import io
import json
import argparse
import sys
from pathlib import Path
from typing import Optional, Any

from concurrent.futures import ThreadPoolExecutor, as_completed
import concurrent.futures
import time
import threading
from tqdm import tqdm
from src.utils.format_utils import format_binary_size, format_binary_rate
from src.utils.logger import log
import configparser
import hashlib
import getpass
import platform
import sqlite3
import glob
try:
    import winreg  # Windows-only
except ImportError:
    winreg = None  # Not available on Linux/Mac
import mimetypes

__version__ = "0.7.2"  # Application version number

# GitHub repository info for update checker
GITHUB_OWNER = "twwat"
GITHUB_REPO = "imxup"

# Lazy User-Agent string builder to avoid platform.system() hang during module import
# (platform.system() can hang on some Windows systems, breaking splash screen initialization)
_user_agent_cache = None

def get_user_agent() -> str:
    """Get User-Agent string, building it lazily on first call to avoid import-time hangs."""
    global _user_agent_cache
    if _user_agent_cache is None:
        try:
            _system = platform.system()
            _release = platform.release()
            _machine = platform.machine()
            _version = platform.version()
            _user_agent_cache = f"Mozilla/5.0 (ImxUp {__version__}; {_system} {_release} {_version}; {_machine}; rv:141.0) Gecko/20100101 Firefox/141.0"
        except Exception:
            # Fallback if platform calls fail
            _user_agent_cache = f"Mozilla/5.0 (ImxUp {__version__}; Windows; rv:141.0) Gecko/20100101 Firefox/141.0"
    return _user_agent_cache

def get_version() -> str:
    return __version__

def timestamp() -> str:
    """Return current timestamp for logging"""
    return datetime.now().strftime("%H:%M:%S")

def get_project_root() -> str:
    """Return the project root directory.

    When running as PyInstaller frozen executable:
        Returns the directory containing the .exe (where assets/, docs/, src/ are located)
    When running as Python script:
        Returns the directory containing imxup.py
    """
    if getattr(sys, 'frozen', False):
        # Running as PyInstaller executable - use .exe location
        # This ensures we find assets/, docs/, src/ next to the .exe
        return os.path.dirname(os.path.abspath(sys.executable))
    else:
        # Running as Python script - use imxup.py location
        return os.path.dirname(os.path.abspath(__file__))

def get_base_path() -> str:
    """Get the base path for all app data (config, galleries, templates).

    Checks QSettings for custom base path (bootstrap), falls back to default ~/.imxup
    """
    try:
        # Check QSettings for custom base path (bootstrap location)
        from PyQt6.QtCore import QSettings
        settings = QSettings("ImxUploader", "ImxUploadGUI")
        custom_base = settings.value("config/base_path", "", type=str)

        if custom_base and os.path.isdir(custom_base):
            return custom_base
    except Exception:
        pass  # QSettings not available (CLI mode)

    # Default location
    return os.path.join(os.path.expanduser("~"), ".imxup")


def get_config_path() -> str:
    """Return the canonical path to the application's config file."""
    base_dir = get_base_path()
    os.makedirs(base_dir, exist_ok=True)
    return os.path.join(base_dir, "imxup.ini")

def _unique_destination_path(dest_dir: str, filename: str) -> str:
    """Generate a unique destination path within dest_dir.
    If a file with the same name exists, append _1, _2, ... before the extension.
    """
    name, ext = os.path.splitext(filename)
    candidate = os.path.join(dest_dir, filename)
    if not os.path.exists(candidate):
        return candidate
    suffix = 1
    while True:
        new_name = f"{name}_{suffix}{ext}"
        candidate = os.path.join(dest_dir, new_name)
        if not os.path.exists(candidate):
            return candidate
        suffix += 1

def create_windows_context_menu():
    """Create Windows context menu integration"""
    # Skip if not on Windows or winreg not available
    if winreg is None or platform.system() != 'Windows':
        return False

    try:
        # Resolve executables and scripts based on frozen/unfrozen state
        is_frozen = getattr(sys, 'frozen', False)

        if is_frozen:
            # Running as .exe - use the executable directly
            script_dir = os.path.dirname(os.path.abspath(sys.executable))
            exe_path = sys.executable
            # For frozen exe, both CLI and GUI use the same exe with different flags
            cli_script = f'"{exe_path}"'
            gui_script = f'"{exe_path}" --gui'
            python_exe = None  # Not needed for .exe
            pythonw_exe = None
        else:
            # Running as Python script - use .py files with python.exe
            script_dir = get_project_root()
            cli_script = os.path.join(script_dir, 'imxup.py')
            gui_script = os.path.join(script_dir, 'imxup.py')  # Use imxup.py --gui for consistency
            # Prefer python.exe for CLI and pythonw.exe for GUI
            python_exe = sys.executable or 'python.exe'
            if python_exe.lower().endswith('pythonw.exe'):
                pythonw_exe = python_exe
                python_cli_exe = python_exe[:-1]  # replace 'w' -> ''
                if not os.path.exists(python_cli_exe):
                    python_cli_exe = python_exe  # best effort
            else:
                python_cli_exe = python_exe
                pythonw_exe = python_exe.replace('python.exe', 'pythonw.exe')
                if not os.path.exists(pythonw_exe):
                    pythonw_exe = python_exe  # fallback to python.exe if pythonw not present

        # Create registry entries for GUI uploader (directory right-click)
        gui_key_path_dir = r"Directory\shell\UploadToImxGUI"
        gui_key_dir = winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, gui_key_path_dir)
        winreg.SetValue(gui_key_dir, "", winreg.REG_SZ, "IMX Uploader")
        try:
            winreg.SetValueEx(gui_key_dir, "MultiSelectModel", 0, winreg.REG_SZ, "Document")
        except Exception:
            pass
        gui_command_key_dir = winreg.CreateKey(gui_key_dir, "command")

        # Build command based on frozen/unfrozen state
        if is_frozen:
            # For .exe, pass folder path as argument (--gui flag already in gui_script variable)
            gui_command = f'{gui_script} "%V"'
        else:
            # For Python script, use pythonw.exe with imxup.py --gui
            gui_command = f'"{pythonw_exe}" "{gui_script}" --gui "%V"'

        winreg.SetValue(gui_command_key_dir, "", winreg.REG_SZ, gui_command)
        winreg.CloseKey(gui_command_key_dir)
        winreg.CloseKey(gui_key_dir)
        
        print("Context menu created successfully!")
        print("Right-click on any folder (or background) and select:")
        print("  - 'Upload to imx.to' for command line mode")
        print("  - 'Upload to imx.to (GUI)' for graphical interface")
        return True
        
    except Exception as e:
        log(f"Error creating context menu: {e}", level="error")
        return False

def remove_windows_context_menu():
    """Remove Windows context menu integration"""
    # Skip if not on Windows or winreg not available
    if winreg is None or platform.system() != 'Windows':
        return False

    try:
        # Remove command line context menu (background)
        try:
            key_path_bg = r"Directory\Background\shell\UploadToImx"
            winreg.DeleteKey(winreg.HKEY_CLASSES_ROOT, key_path_bg + r"\command")
            winreg.DeleteKey(winreg.HKEY_CLASSES_ROOT, key_path_bg)
        except FileNotFoundError:
            pass  # Key doesn't exist
        
        # Remove GUI context menu (background)
        try:
            gui_key_path_bg = r"Directory\Background\shell\UploadToImxGUI"
            winreg.DeleteKey(winreg.HKEY_CLASSES_ROOT, gui_key_path_bg + r"\command")
            winreg.DeleteKey(winreg.HKEY_CLASSES_ROOT, gui_key_path_bg)
        except FileNotFoundError:
            pass  # Key doesn't exist

        # Remove command line context menu (directory items)
        try:
            key_path_dir = r"Directory\shell\UploadToImx"
            winreg.DeleteKey(winreg.HKEY_CLASSES_ROOT, key_path_dir + r"\command")
            winreg.DeleteKey(winreg.HKEY_CLASSES_ROOT, key_path_dir)
        except FileNotFoundError:
            pass

        # Remove GUI context menu (directory items)
        try:
            gui_key_path_dir = r"Directory\shell\UploadToImxGUI"
            winreg.DeleteKey(winreg.HKEY_CLASSES_ROOT, gui_key_path_dir + r"\command")
            winreg.DeleteKey(winreg.HKEY_CLASSES_ROOT, gui_key_path_dir)
        except FileNotFoundError:
            pass
        
        log("Context menu removed successfully.", level="info", category="ui")
        return True
    except Exception as e:
        log(f"Error removing context menu: {e}", level="error", category="ui")
        return False

import base64
from cryptography.fernet import Fernet
import hashlib

class NestedProgressBar:
    """Custom progress bar with nested levels for better upload tracking"""
    
    def __init__(self, total, desc, level=0, parent=None):
        self.total = total
        self.desc = desc
        self.level = level
        self.parent = parent
        self.current = 0
        self.pbar = None
        self.children = []
        
    def __enter__(self):
        indent = "  " * self.level
        self.pbar = tqdm(
            total=self.total,
            desc=f"{indent}{self.desc}",
            unit="img",
            leave=False,
            position=self.level
        )
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.pbar:
            self.pbar.close()
    
    def update(self, n=1):
        self.current += n
        if self.pbar:
            self.pbar.update(n)
    
    def set_postfix_str(self, text):
        if self.pbar:
            self.pbar.set_postfix_str(text)
    
    def add_child(self, child):
        self.children.append(child)
        child.parent = self



class CredentialDecryptionError(Exception):
    """Raised when credential decryption fails"""
    pass

def get_encryption_key():
    """Generate encryption key from system info (LEGACY - WEAK SECURITY).

    WARNING: This uses hostname+username which is predictable and insecure.
    Kept only for backward compatibility. New credentials should use keyring.
    """
    # Use username and hostname to create a consistent key
    # NOTE: platform.node() can HANG on systems with WMI/network issues
    # Use COMPUTERNAME environment variable instead (Windows-specific but safer)
    hostname = os.getenv('COMPUTERNAME') or os.getenv('HOSTNAME') or 'localhost'
    username = os.getenv('USERNAME') or os.getenv('USER') or 'user'
    system_info = f"{username}{hostname}"
    key = hashlib.sha256(system_info.encode()).digest()
    return base64.urlsafe_b64encode(key)

def encrypt_password(password):
    """Encrypt password using legacy Fernet encryption.

    NOTE: This is kept for backward compatibility only.
    New code should store credentials directly via keyring (see set_credential).
    """
    key = get_encryption_key()
    f = Fernet(key)
    return f.encrypt(password.encode()).decode()

def decrypt_password(encrypted_password):
    """Decrypt password with proper error handling.

    Raises CredentialDecryptionError on failure to prevent silent auth failures.
    """
    if not encrypted_password:
        raise CredentialDecryptionError("No encrypted password provided")

    try:
        key = get_encryption_key()
        f = Fernet(key)
        return f.decrypt(encrypted_password.encode()).decode()
    except Exception as e:
        log(f"Failed to decrypt password: {e}", level="error", category="auth")
        raise CredentialDecryptionError(
            "Credential decryption failed. Your credentials may be corrupted. "
            "Please reconfigure via Settings > Credentials."
        ) from e

def get_credential(key):
    """Get credential using OS-native secure storage (keyring).

    Falls back to QSettings/Registry for backward compatibility.
    """
    try:
        # Try keyring first (secure OS-native storage)
        import keyring
        value = keyring.get_password("imxup", key)
        if value:
            return value
    except ImportError:
        pass  # Fall through to legacy storage
    except Exception:
        pass  # Keyring not available, fall through to QSettings (normal)

    # Fallback to legacy QSettings/Registry storage
    from PyQt6.QtCore import QSettings
    settings = QSettings("imxup", "imxup")
    settings.beginGroup("Credentials")
    value = settings.value(key, "")
    settings.endGroup()
    return value

def set_credential(key, value):
    """Set credential using OS-native secure storage (keyring).

    Also stores in QSettings/Registry for backward compatibility.
    """
    try:
        # Try to use keyring (secure OS-native storage)
        import keyring
        keyring.set_password("imxup", key, value)
        log(f"Credential '{key}' stored securely in OS keyring", level="debug", category="auth")
    except ImportError:
        log("keyring not available, using QSettings only", level="warning", category="auth")
    except Exception as e:
        log(f"Keyring storage failed: {e}, falling back to QSettings", level="warning", category="auth")

    # Also store in QSettings/Registry for backward compatibility
    from PyQt6.QtCore import QSettings
    settings = QSettings("imxup", "imxup")
    settings.beginGroup("Credentials")
    settings.setValue(key, value)
    settings.endGroup()
    settings.sync()

def remove_credential(key):
    """Remove credential from QSettings"""
    from PyQt6.QtCore import QSettings
    settings = QSettings("imxup", "imxup")
    settings.beginGroup("Credentials")
    settings.remove(key)
    settings.endGroup()
    settings.sync()

def migrate_credentials_from_ini():
    """Migrate credentials from INI file to QSettings, then remove from INI"""
    import configparser
    config = configparser.ConfigParser()
    config_file = get_config_path()

    if not os.path.exists(config_file):
        return

    config.read(config_file)
    if 'CREDENTIALS' not in config:
        return

    # Migrate only actual credentials (not cookies_enabled which stays in INI as a preference)
    migrated = False
    cookies_val = config['CREDENTIALS'].get('cookies_enabled', '')

    for key in ['username', 'password', 'api_key']:
        value = config['CREDENTIALS'].get(key, '')
        if value:
            set_credential(key, value)
            migrated = True

    # Update INI file - remove credentials but keep cookies_enabled
    if migrated:
        config.remove_section('CREDENTIALS')
        if cookies_val:
            config['CREDENTIALS'] = {'cookies_enabled': cookies_val}
        with open(config_file, 'w') as f:
            config.write(f)
        log("Migrated credentials from INI to Registry", level="info", category="auth")

def load_user_defaults():
    """Load user defaults from config file

    Returns:
        Dictionary of user settings with defaults
    """
    # Default values for all settings
    defaults = {
        'thumbnail_size': 3,
        'thumbnail_format': 2,
        'max_retries': 3,
        'parallel_batch_size': 4,
        'template_name': 'default',
        'confirm_delete': True,
        'auto_rename': True,
        'auto_start_upload': False,
        'auto_regenerate_bbcode': False,
        'store_in_uploaded': True,
        'store_in_central': True,
        'central_store_path': get_default_central_store_base_path(),
        'upload_connect_timeout': 30,
        'upload_read_timeout': 120,
        'use_median': True,
        'stats_exclude_outliers': False,
        'check_updates_on_startup': True,
    }

    config = configparser.ConfigParser()
    config_file = get_config_path()

    if os.path.exists(config_file):
        config.read(config_file)

        if 'DEFAULTS' in config:
            # Load integer settings
            for key in ['thumbnail_size', 'thumbnail_format', 'max_retries',
                       'parallel_batch_size', 'upload_connect_timeout', 'upload_read_timeout']:
                defaults[key] = config.getint('DEFAULTS', key, fallback=defaults[key])

            # Load boolean settings
            for key in ['confirm_delete', 'auto_rename', 'auto_start_upload',
                       'auto_regenerate_bbcode', 'store_in_uploaded', 'store_in_central',
                       'use_median', 'stats_exclude_outliers', 'check_updates_on_startup']:
                defaults[key] = config.getboolean('DEFAULTS', key, fallback=defaults[key])

            # Load string settings
            defaults['template_name'] = config.get('DEFAULTS', 'template_name', fallback='default')

            # Load central store path with fallback handling
            try:
                defaults['central_store_path'] = config.get('DEFAULTS', 'central_store_path',
                                                           fallback=get_default_central_store_base_path())
            except Exception:
                defaults['central_store_path'] = get_default_central_store_base_path()

    return defaults



def setup_secure_password():
    """Interactive setup for secure password storage"""
    print("Setting up secure password storage for imx.to")
    print("This will store a hashed version of your password in ~/.imxup/imxup.ini")
    print("")
    
    username = input("Enter your imx.to username: ")
    password = getpass.getpass("Enter your imx.to password: ")
    
    # Save credentials without testing (since DDoS-Guard might block login)
    print("Saving credentials...")
    if _save_credentials(username, password):
        print("[OK] Credentials saved successfully!")
        print("Note: Login test was skipped due to potential DDoS-Guard protection.")
        print("You can test the credentials by running an upload.")
        return True
    else:
        log("Failed to save credentials.", level="error", category="auth")
        return False

def _save_credentials(username, password):
    """Save credentials to QSettings (Registry)"""
    set_credential('username', username)
    set_credential('password', encrypt_password(password))
    log("Username and encrypted password saved to Registry", level="info", category="auth")
    return True

def save_unnamed_gallery(gallery_id, intended_name):
    """Save unnamed gallery for later renaming (now uses database for speed)"""
    try:
        from src.storage.database import QueueStore
        store = QueueStore()
        store.add_unnamed_gallery(gallery_id, intended_name)
        log(f"Gallery '{gallery_id}' to be renamed '{intended_name}' later", level="debug", category="renaming")
    except Exception as e:
        # Fallback to config file
        log(f"Database save failed, using config file fallback: {e}", level="error", category="renaming")
        config = configparser.ConfigParser()
        config_file = get_config_path()
        
        if os.path.exists(config_file):
            config.read(config_file)
        
        if 'UNNAMED_GALLERIES' not in config:
            config['UNNAMED_GALLERIES'] = {}
        
        config['UNNAMED_GALLERIES'][gallery_id] = intended_name
        
        with open(config_file, 'w') as f:
            config.write(f)
        
        log(f"Saved unnamed gallery {gallery_id} for later renaming to '{intended_name}'", level="info", category="renaming")

def get_default_central_store_base_path():
    """Return the default central store BASE path. Alias for get_base_path default."""
    return os.path.join(os.path.expanduser("~"), ".imxup")


def get_central_store_base_path():
    """Get the configured central store BASE path (parent of galleries/templates)."""
    base_path = get_base_path()
    os.makedirs(base_path, exist_ok=True)
    return base_path


def get_central_storage_path():
    """Get the galleries subfolder inside the central store base path.

    Ensures the directory exists before returning.
    """
    base = get_central_store_base_path()
    galleries_path = os.path.join(base, "galleries")
    os.makedirs(galleries_path, exist_ok=True)
    return galleries_path

def sanitize_gallery_name(name):
    """Remove invalid characters from gallery name"""
    import re
    # Keep alphanumeric, spaces, hyphens, dashes, round brackets, periods, underscores
    # Remove everything else (square brackets, number signs, etc.)
    sanitized = re.sub(r'[^a-zA-Z0-9,\.\s\-_\(\)]', '', name)
    # Remove multiple spaces
    sanitized = re.sub(r'\s+', ' ', sanitized)
    # Trim spaces
    sanitized = sanitized.strip()
    return sanitized

def build_gallery_filenames(gallery_name, gallery_id):
    """Return standardized filenames for gallery artifacts.
    - JSON filename: {Gallery Name}_{GalleryID}.json
    - BBCode filename: {Gallery Name}_{GalleryID}_bbcode.txt
    Returns (gallery_name, json_filename, bbcode_filename).
    """
    # Use gallery name directly - no sanitization for filenames
    json_filename = f"{gallery_name}_{gallery_id}.json"
    bbcode_filename = f"{gallery_name}_{gallery_id}_bbcode.txt"
    return gallery_name, json_filename, bbcode_filename

def check_if_gallery_exists(folder_name):
    """Check if gallery files already exist for this folder"""
    central_path = get_central_storage_path()
    
    # Check central location
    central_files = glob.glob(os.path.join(central_path, f"{folder_name}_*_bbcode.txt")) + \
                    glob.glob(os.path.join(central_path, f"{folder_name}_*.json"))
    
    # Check within .uploaded subfolder directly under this folder
    folder_files = [
        os.path.join(folder_name, ".uploaded", f"{folder_name}_*.json"),
        os.path.join(folder_name, ".uploaded", f"{folder_name}_*_bbcode.txt")
    ]
    
    existing_files = []
    existing_files.extend(central_files)
    for pattern in folder_files:
        existing_files.extend(glob.glob(pattern))
    
    return existing_files

def get_unnamed_galleries():
    """Get list of unnamed galleries from database (much faster than config file)"""
    try:
        from src.storage.database import QueueStore
        store = QueueStore()
        return store.get_unnamed_galleries()
    except Exception:
        # Fallback to config file if database fails
        config = configparser.ConfigParser()
        config_file = get_config_path()
        
        if os.path.exists(config_file):
            config.read(config_file)
            if 'UNNAMED_GALLERIES' in config:
                return dict(config['UNNAMED_GALLERIES'])
        return {}

def rename_all_unnamed_with_session(uploader: 'ImxToUploader') -> int:
    """Rename all unnamed galleries using an already logged-in uploader session.
    Returns the number of successfully renamed galleries. Stops early on HTTP 403 or DDoS-Guard block.
    """
    unnamed_galleries = get_unnamed_galleries()
    if not unnamed_galleries:
        return 0
    success_count = 0
    attempted = 0
    for gallery_id, intended_name in unnamed_galleries.items():
        attempted += 1
        ok = uploader.rename_gallery_with_session(gallery_id, intended_name)
        # If blocked by DDoS-Guard or got 403, stop further attempts
        status = getattr(uploader, '_last_rename_status_code', None)
        ddos = bool(getattr(uploader, '_last_rename_ddos', False))
        if status == 403 or ddos:
            # If we used cookies and credentials exist, try credentials-only once for this gallery
            try:
                last_method = getattr(uploader, 'last_login_method', None)
            except Exception:
                last_method = None
            has_creds = bool(getattr(uploader, 'username', None) and getattr(uploader, 'password', None))
            retried_ok = False
            if last_method == 'cookies' and has_creds:
                if getattr(uploader, 'login_with_credentials_only', None) and uploader.login_with_credentials_only():
                    retried_ok = uploader.rename_gallery_with_session(gallery_id, intended_name)
                    status = getattr(uploader, '_last_rename_status_code', None)
                    ddos = bool(getattr(uploader, '_last_rename_ddos', False))
            if retried_ok:
                ok = True
            else:
                # Hard stop further renames to avoid hammering while blocked
                try:
                    if hasattr(uploader, 'worker_thread') and uploader.worker_thread is not None:
                        log(f"Stopping auto-rename due to {'DDoS-Guard' if ddos else 'HTTP 403'}", level="debug", category="renaming")
                except Exception:
                    pass
                # Do not continue processing additional galleries
                break
        if ok:
            try:
                if hasattr(uploader, 'worker_thread') and uploader.worker_thread is not None:
                    log(f"Successfully renamed gallery '{gallery_id}' to '{intended_name}'", level="info", category="renaming")
                    try:
                        # Notify GUI to update Renamed column if available
                        if hasattr(uploader.worker_thread, 'gallery_renamed'):
                            uploader.worker_thread.gallery_renamed.emit(gallery_id)
                    except Exception:
                        pass
            except Exception:
                pass
            # Only remove if rename succeeded definitively
            remove_unnamed_gallery(gallery_id)
            success_count += 1
        else:
            # Log explicit failure for visibility
            try:
                if hasattr(uploader, 'worker_thread') and uploader.worker_thread is not None:
                    reason = "DDoS-Guard" if ddos else (f"HTTP {status}" if status else "unknown error")
                    log(f"Failed to rename gallery '{gallery_id}' to '{intended_name}' ({reason})", level="warning", category="renaming")
            except Exception:
                pass
            # Keep it in unnamed list for future attempts
    return success_count

def check_gallery_renamed(gallery_id):
    """Check if a gallery has been renamed (not in unnamed galleries list)"""
    try:
        from src.storage.database import QueueStore
        store = QueueStore()
        unnamed_galleries = store.get_unnamed_galleries()
        return gallery_id not in unnamed_galleries
    except Exception:
        # Fallback to config file if database fails
        unnamed_galleries = get_unnamed_galleries()
        return gallery_id not in unnamed_galleries

def remove_unnamed_gallery(gallery_id):
    """Remove gallery from unnamed list after successful renaming (now uses database)"""
    try:
        from src.storage.database import QueueStore
        store = QueueStore()
        removed = store.remove_unnamed_gallery(gallery_id)
        if removed:
            log(f"Removed {gallery_id} from unnamed galleries list", level="debug")
    except Exception as e:
        # Fallback to config file
        log(f"Database removal failed, using config file fallback: {e}", level="warning")
        config = configparser.ConfigParser()
        config_file = get_config_path()
        
        if os.path.exists(config_file):
            config.read(config_file)
            
            if 'UNNAMED_GALLERIES' in config and gallery_id in config['UNNAMED_GALLERIES']:
                del config['UNNAMED_GALLERIES'][gallery_id]
                
                with open(config_file, 'w') as f:
                    config.write(f)
                
                log(f"Removed {gallery_id} from unnamed galleries list", level="debug", category="renaming")

from src.network.cookies import get_firefox_cookies, load_cookies_from_file

def get_template_path():
    """Get the template directory path (uses configured central store location)."""
    base_path = get_central_store_base_path()  # Use configured path, not hardcoded
    template_path = os.path.join(base_path, "templates")
    os.makedirs(template_path, exist_ok=True)
    return template_path

def get_default_template():
    """Get the default template content"""
    return "#folderName#\n#allImages#"

def load_templates():
    """Load all available templates from the template directory"""
    template_path = get_template_path()
    templates = {}
    
    # Add default template
    templates["default"] = get_default_template()

    # Add Extended Example template
    templates["Extended Example"] = """#folderName#
[hr][/hr]
[center][size=4][b][color=#11c153]#folderName#[/color][/b][/size]

[size=3][b][color="#888"]#pictureCount# IMAGES • #extension# • #width#x#height# • #folderSize# [/color] [/b][/font][/size]
[/center][hr][/hr]#allImages#
[if galleryLink][b]Gallery link[/b]: #galleryLink#[else][i][size=1]Sorry, no gallery link available.[/size][/i][/if]
ext1: [if ext1]#ext1#[else]no ext1 value set[/if]
ext2: [if ext2]#ext2#[else]no ext2 value set[/if]
ext3: [if ext3]#ext3#[else]no ext3 value set[/if]
ext4: [if ext4]#ext4#[else]no ext4 value set[/if]
custom1: [if custom1]#custom1#[else]no custom1 value set[/if]
custom2: [if custom2]#custom2#[else]no custom2 value set[/if]
custom3: [if custom3]#custom3#[else]no custom3 value set[/if]
custom4: [if custom4]#custom4#[else]no custom4 value set[/if]
[if hostLinks][b]Download links:[/b]
#hostLinks#[/if]"""

    # Load custom templates
    if os.path.exists(template_path):
        for filename in os.listdir(template_path):
            template_name = filename
            if template_name.startswith(".template"):
                template_name = template_name[10:]  # Remove ".template " prefix
            # Remove .txt extension if present
            if template_name.endswith('.template.txt'):
                template_name = template_name[:-13]
            if template_name.endswith('.txt'):
                template_name = template_name[:-4]
            if template_name:  # Skip empty names
                template_file = os.path.join(template_path, filename)
                try:
                    with open(template_file, 'r', encoding='utf-8') as f:
                        templates[template_name] = f.read()
                except Exception as e:
                    log(f"Could not load template '{template_name}': {e}", level="error")
    
    return templates

def process_conditionals(template_content, data):
    """Process conditional logic in templates before placeholder replacement.

    Supports two syntax forms:
    1. [if placeholder]content[/if] - shows content if placeholder value is non-empty
    2. [if placeholder=value]content[else]alternative[/if] - shows content if placeholder equals value

    Features:
    - Multiple inline conditionals on the same line
    - Nested conditionals (processed inside-out)
    - Empty lines from removed conditionals are stripped
    """
    import re

    # Process conditionals iteratively until no more found
    max_iterations = 50  # Prevent infinite loops
    iteration = 0

    while iteration < max_iterations:
        # Look for innermost conditional pattern (no nested [if] tags inside)
        # This regex matches [if...] followed by content WITHOUT another [if, then [/if]
        if_pattern = r'\[if\s+(\w+)(=([^\]]+))?\]((?:(?!\[if).)*?)\[/if\]'
        match = re.search(if_pattern, template_content, re.DOTALL)

        if not match:
            # No more conditionals found
            break

        placeholder_name = match.group(1)
        expected_value = match.group(3)  # None if no = comparison
        conditional_block = match.group(4)  # Content between [if] and [/if]

        # Get the actual value from data
        actual_value = data.get(placeholder_name, '')

        # Check for [else] clause (only at top level, not nested)
        else_pattern = r'^(.*?)\[else\](.*?)$'
        else_match = re.match(else_pattern, conditional_block, re.DOTALL)

        if else_match:
            true_content = else_match.group(1)
            false_content = else_match.group(2)
        else:
            true_content = conditional_block
            false_content = ''

        # Determine condition
        if expected_value is not None:
            # Equality check: [if placeholder=value]
            condition_met = (str(actual_value).strip() == expected_value.strip())
        else:
            # Existence check: [if placeholder]
            condition_met = bool(str(actual_value).strip())

        # Select content based on condition
        selected_content = true_content if condition_met else false_content

        # Replace the entire conditional block with selected content
        template_content = template_content[:match.start()] + selected_content + template_content[match.end():]

        iteration += 1

    # Clean up empty lines
    lines = template_content.split('\n')
    cleaned_lines = [line for line in lines if line.strip() or line == '']  # Keep intentional blank lines

    # Remove consecutive empty lines and leading/trailing empty lines
    result_lines = []
    prev_empty = False
    for line in cleaned_lines:
        is_empty = not line.strip()
        if is_empty:
            if not prev_empty and result_lines:  # Keep one empty line
                result_lines.append(line)
            prev_empty = True
        else:
            result_lines.append(line)
            prev_empty = False

    # Remove trailing empty lines
    while result_lines and not result_lines[-1].strip():
        result_lines.pop()

    return '\n'.join(result_lines)

def apply_template(template_content, data):
    """Apply a template with data replacement"""
    # Process conditional logic first (before placeholder replacement)
    result = process_conditionals(template_content, data)

    # Replace placeholders with actual data
    replacements = {
        '#folderName#': data.get('folder_name', ''),
        '#width#': str(data.get('width', 0)),
        '#height#': str(data.get('height', 0)),
        '#longest#': str(data.get('longest', 0)),
        '#extension#': data.get('extension', ''),
        '#pictureCount#': str(data.get('picture_count', 0)),
        '#folderSize#': data.get('folder_size', ''),
        '#galleryLink#': data.get('gallery_link', ''),
        '#allImages#': data.get('all_images', ''),
        '#hostLinks#': data.get('host_links', ''),
        '#custom1#': data.get('custom1', ''),
        '#custom2#': data.get('custom2', ''),
        '#custom3#': data.get('custom3', ''),
        '#custom4#': data.get('custom4', ''),
        '#ext1#': data.get('ext1', ''),
        '#ext2#': data.get('ext2', ''),
        '#ext3#': data.get('ext3', ''),
        '#ext4#': data.get('ext4', '')
    }
    
    for placeholder, value in replacements.items():
        result = result.replace(placeholder, value)
    
    return result

def generate_bbcode_from_template(template_name, data):
    """Generate bbcode content using a specific template"""
    templates = load_templates()
    
    if template_name not in templates:
        log(f" Warning: Template '{template_name}' not found, using default")
        template_name = "default"
    
    template_content = templates[template_name]
    return apply_template(template_content, data)

from typing import Optional

def save_gallery_artifacts(
    folder_path: str,
    results: dict,
    template_name: str = "default",
    store_in_uploaded: Optional[bool] = None,
    store_in_central: Optional[bool] = None,
    custom_fields: Optional[dict] = None,
) -> dict:
    """Save BBCode and JSON artifacts for a completed gallery.

    Parameters:
    - folder_path: path to the source image folder
    - results: the results dict returned by upload_folder (must contain keys used below)
    - template_name: which template to use for full bbcode generation
    - store_in_uploaded/store_in_central: overrides for storage locations. When None, read defaults
    - custom_fields: optional dict with custom1-4 and ext1-4 values

    Returns: dict with paths written: { 'uploaded': {'bbcode': str, 'json': str}, 'central': {...}}
    """
    # Determine storage preferences
    defaults = load_user_defaults()
    if store_in_uploaded is None:
        store_in_uploaded = defaults.get('store_in_uploaded', True)
    if store_in_central is None:
        store_in_central = defaults.get('store_in_central', True)

    gallery_id = results.get('gallery_id', '')
    gallery_name = results.get('gallery_name') or os.path.basename(folder_path)
    if not gallery_id or not gallery_name:
        return {}

    # Ensure .uploaded exists if needed
    uploaded_subdir = os.path.join(folder_path, ".uploaded")
    if store_in_uploaded:
        os.makedirs(uploaded_subdir, exist_ok=True)

    # Build filenames
    safe_gallery_name, json_filename, bbcode_filename = build_gallery_filenames(gallery_name, gallery_id)

    # Prepare template data from results for full bbcode
    total_size = results.get('total_size', 0)
    successful_images = results.get('successful_count', len(results.get('images', [])))
    avg_width = int(results.get('avg_width', 0) or 0)
    avg_height = int(results.get('avg_height', 0) or 0)

    # Fallback: Calculate from files if dimensions are missing
    if (avg_width == 0 or avg_height == 0) and os.path.isdir(folder_path):
        from src.utils.sampling_utils import calculate_folder_dimensions
        calc = calculate_folder_dimensions(folder_path)
        if calc:
            avg_width = int(calc.get('avg_width', 0))
            avg_height = int(calc.get('avg_height', 0))

    extension = "JPG"
    try:
        # Best-effort derive the most common extension from images if present
        exts = []
        for img in results.get('images', []):
            orig = img.get('original_filename') or ''
            if orig:
                _, ext = os.path.splitext(orig)
                if ext:
                    exts.append(ext.upper().lstrip('.'))
        if exts:
            extension = max(set(exts), key=exts.count)
    except Exception:
        pass

    # All-images bbcode (space-separated)
    all_images_bbcode = "".join([(img.get('bbcode') or '') + "  " for img in results.get('images', [])]).strip()

    # Get file host download links (if available)
    host_links = ''
    try:
        from src.storage.database import QueueStore
        from src.utils.template_utils import get_file_host_links_for_template
        queue_store = QueueStore()
        host_links = get_file_host_links_for_template(queue_store, folder_path)
    except (sqlite3.Error, OSError) as e:
        log(f"Failed to get file host links: {e}", level="warning", category="template")
    template_data = {
        'folder_name': gallery_name,
        'width': avg_width,
        'height': avg_height,
        'longest': max(avg_width, avg_height),
        'extension': extension,
        'picture_count': successful_images,
        'folder_size': f"{total_size / (1024*1024):.1f} MB",
        'gallery_link': f"https://imx.to/g/{gallery_id}",
        'all_images': all_images_bbcode,
        'host_links': host_links,
        'custom1': (custom_fields or {}).get('custom1', ''),
        'custom2': (custom_fields or {}).get('custom2', ''),
        'custom3': (custom_fields or {}).get('custom3', ''),
        'custom4': (custom_fields or {}).get('custom4', ''),
        'ext1': (custom_fields or {}).get('ext1', ''),
        'ext2': (custom_fields or {}).get('ext2', ''),
        'ext3': (custom_fields or {}).get('ext3', ''),
        'ext4': (custom_fields or {}).get('ext4', '')
    }
    bbcode_content = generate_bbcode_from_template(template_name, template_data)

    # Compose JSON payload (align with CLI structure)
    json_payload = {
        'meta': {
            'gallery_name': gallery_name,
            'gallery_id': gallery_id,
            'gallery_url': f"https://imx.to/g/{gallery_id}",
            'status': 'completed',
            'started_at': results.get('started_at') or None,
            'finished_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'uploader_version': __version__,
        },
        'settings': {
            'thumbnail_size': results.get('thumbnail_size'),
            'thumbnail_format': results.get('thumbnail_format'),
            'template_name': template_name,
            'parallel_batch_size': results.get('parallel_batch_size'),
        },
        'stats': {
            'total_images': results.get('total_images') or (successful_images + results.get('failed_count', 0)),
            'successful_count': successful_images,
            'failed_count': results.get('failed_count', 0),
            'upload_time': results.get('upload_time', 0),
            'total_size': total_size,
            'uploaded_size': results.get('uploaded_size', 0),
            'avg_width': results.get('avg_width', 0),
            'avg_height': results.get('avg_height', 0),
            'max_width': results.get('max_width', 0),
            'max_height': results.get('max_height', 0),
            'min_width': results.get('min_width', 0),
            'min_height': results.get('min_height', 0),
            'transfer_speed_mb_s': (results.get('transfer_speed', 0) / (1024*1024)) if results.get('transfer_speed', 0) else 0,
        },
        'images': results.get('images', []),
        'failures': [
            {
                'filename': fname,
                'failed_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'reason': reason,
            }
            for fname, reason in results.get('failed_details', [])
        ],
        'bbcode_full': bbcode_content,
    }

    written_paths = {}
    # Save BBCode and JSON to .uploaded
    if store_in_uploaded:
        with open(os.path.join(uploaded_subdir, bbcode_filename), 'w', encoding='utf-8') as f:
            f.write(bbcode_content)
        with open(os.path.join(uploaded_subdir, json_filename), 'w', encoding='utf-8') as jf:
            json.dump(json_payload, jf, ensure_ascii=False, indent=2)
        written_paths.setdefault('uploaded', {})['bbcode'] = os.path.join(uploaded_subdir, bbcode_filename)
        written_paths.setdefault('uploaded', {})['json'] = os.path.join(uploaded_subdir, json_filename)

    # Save to central location as well
    if store_in_central:
        central_path = get_central_storage_path()
        os.makedirs(central_path, exist_ok=True)
        with open(os.path.join(central_path, bbcode_filename), 'w', encoding='utf-8') as f:
            f.write(bbcode_content)
        with open(os.path.join(central_path, json_filename), 'w', encoding='utf-8') as jf:
            json.dump(json_payload, jf, ensure_ascii=False, indent=2)
        written_paths.setdefault('central', {})['bbcode'] = os.path.join(central_path, bbcode_filename)
        written_paths.setdefault('central', {})['json'] = os.path.join(central_path, json_filename)

    return written_paths


class UploadProgressWrapper:
    """File-like wrapper that tracks bytes during network transmission.

    When requests.post() uploads multipart form data, it calls read() on this
    wrapper repeatedly during HTTP transmission. This allows accurate tracking
    of actual network bytes sent (not disk reads).
    """

    def __init__(self, file_data: bytes, callback=None):
        """Initialize wrapper with file data and optional progress callback.

        Args:
            file_data: Raw bytes to upload
            callback: Optional callable(bytes_sent, total_bytes) invoked on each read()
        """
        import io
        self._bytesio = io.BytesIO(file_data)
        self.callback = callback
        self.total_size = len(file_data)

    def read(self, size=-1):
        """Read chunk from buffer and invoke callback. Called by requests during upload."""
        chunk = self._bytesio.read(size)
        if chunk and self.callback:
            try:
                # Report cumulative bytes sent
                self.callback(self._bytesio.tell(), self.total_size)
            except Exception:
                pass  # Silently ignore callback failures
        return chunk

    def __len__(self):
        """Return total size for Content-Length header."""
        return self.total_size

    def seek(self, offset, whence=0):
        """Seek to position (required for retry logic)."""
        return self._bytesio.seek(offset, whence)

    def tell(self):
        """Return current position."""
        return self._bytesio.tell()

    def __getattr__(self, name):
        """Proxy any missing attributes to underlying BytesIO."""
        return getattr(self._bytesio, name)


class ProgressEstimator:
    """Estimates upload progress during network transmission using a background thread."""

    def __init__(self, file_size, callback):
        self.file_size = file_size
        self.callback = callback
        self.start_time = time.time()
        self.stop_flag = False
        self.thread = None

    def start(self):
        """Start progress estimation thread."""
        import threading
        self.stop_flag = False
        self.thread = threading.Thread(target=self._estimate_progress, daemon=True)
        self.thread.start()

    def stop(self):
        """Stop progress estimation thread."""
        self.stop_flag = True
        if self.thread:
            self.thread.join(timeout=0.5)

    def _estimate_progress(self):
        """Estimate upload progress based on typical upload speed."""
        # Assume 2 MB/s average upload speed for estimation
        estimated_speed_bps = 2 * 1024 * 1024  #  2 MB/s

        while not self.stop_flag:
            elapsed = time.time() - self.start_time
            estimated_bytes = min(int(elapsed * estimated_speed_bps), self.file_size)

            if self.callback:
                try:
                    self.callback(estimated_bytes, self.file_size)
                except Exception:
                    pass

            if estimated_bytes >= self.file_size:
                break

            time.sleep(0.1)  # Update every 100ms


class ImxToUploader:
    # Type hints for attributes set externally by GUI worker threads
    worker_thread: Optional[Any] = None  # Set by UploadWorker when used in GUI mode

    def _get_credentials(self):
        """Get credentials from stored config (username/password or API key)"""
        # Read from QSettings (Registry) - migration happens at app startup
        username = get_credential('username')
        encrypted_password = get_credential('password')
        encrypted_api_key = get_credential('api_key')

        # Decrypt if they exist
        password = decrypt_password(encrypted_password) if encrypted_password else None
        api_key = decrypt_password(encrypted_api_key) if encrypted_api_key else None

        # Return what we have
        if username and password:
            return username, password, api_key
        elif api_key:
            return None, None, api_key

        return None, None, None
    
    def _setup_resilient_session(self, parallel_batch_size=4):
        """Create a session with connection pooling (no automatic retries to avoid timeout conflicts)"""
        # Configure connection pooling - use at least parallel_batch_size connections
        pool_size = max(10, parallel_batch_size)
        adapter = HTTPAdapter(
            pool_connections=pool_size,  # Number of connection pools to cache
            pool_maxsize=pool_size       # Max connections per pool
        )

        # Create session and mount adapters
        session = requests.Session()
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        return session

    def refresh_session_pool(self):
        """Refresh session connection pool with current parallel_batch_size setting"""
        try:
            defaults = load_user_defaults()
            current_batch_size = defaults.get('parallel_batch_size', 4)

            # Recreate session with updated pool size
            old_cookies = self.session.cookies if hasattr(self, 'session') else None
            self.session = self._setup_resilient_session(current_batch_size)
            self.session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:141.0) Gecko/20100101 Firefox/141.0',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US',
                'Accept-Encoding': 'gzip, deflate, br, zstd',
                'DNT': '1'
            })

            # Preserve cookies from old session
            if old_cookies:
                self.session.cookies.update(old_cookies)

        except Exception as e:
            log(f"Warning: Failed to refresh session pool: {e}", level="warning")

    def __init__(self):
        # Get credentials from stored config
        self.username, self.password, self.api_key = self._get_credentials()

        # Fallback to environment variable for API key if not in config
        #if not self.api_key:
        #    self.api_key = os.getenv('IMX_API')

        # Check if we have either username/password or API key
        has_credentials = (self.username and self.password) or self.api_key

        if not has_credentials:
            log(f"Failed to get credentials. Please set up credentials in the GUI or run --setup-secure first.", level="warning", category="auth")
            # Don't exit in GUI mode - let the user set credentials through the dialog
            # Only exit if running in CLI mode (when there's no way to set credentials interactively)
            is_gui_mode = os.environ.get('IMXUP_GUI_MODE') == '1'
            if not is_gui_mode:
                sys.exit(1)

        # Load timeout settings
        defaults = load_user_defaults()
        self.upload_connect_timeout = defaults.get('upload_connect_timeout', 30)
        self.upload_read_timeout = defaults.get('upload_read_timeout', 120)
        log(f"Timeout settings loaded: connect={self.upload_connect_timeout}s, read={self.upload_read_timeout}s", level="debug", category="network")

        self.base_url = "https://api.imx.to/v1"
        self.web_url = "https://imx.to"
        self.upload_url = f"{self.base_url}/upload.php"

        # Connection tracking for visibility
        self._upload_count = 0
        self._connection_info_logged = False

        # Thread-local storage for curl handles (connection reuse)
        self._curl_local = threading.local()

        # Set headers based on authentication method
        if self.api_key:
            self.headers = {
                "X-API-Key": self.api_key,
                "User-Agent": get_user_agent()
            }
        else:
            self.headers = {}

        # Session for web interface with connection pooling
        parallel_batch_size = defaults.get('parallel_batch_size', 4)
        self.session = self._setup_resilient_session(parallel_batch_size)
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:141.0) Gecko/20100101 Firefox/141.0',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US',
            'Accept-Encoding': 'gzip, deflate, br, zstd',
            'DNT': '1'
        })
    
    def _get_thread_curl(self):
        """Get or create a thread-local curl handle for connection reuse.

        Each thread gets its own curl handle that persists across uploads,
        allowing TCP connection reuse for better performance.
        """
        if not hasattr(self._curl_local, 'curl'):
            # Create new curl handle for this thread
            import pycurl
            import certifi
            self._curl_local.curl = pycurl.Curl()

            # CRITICAL: Thread safety for multi-threaded uploads
            # NOSIGNAL prevents signal-based timeouts which don't work in multi-threaded programs
            self._curl_local.curl.setopt(pycurl.NOSIGNAL, 1)

            # SECURITY: Enable SSL/TLS certificate verification to prevent MITM attacks
            # Uses certifi's trusted CA bundle for certificate validation
            self._curl_local.curl.setopt(pycurl.CAINFO, certifi.where())
            self._curl_local.curl.setopt(pycurl.SSL_VERIFYPEER, 1)
            self._curl_local.curl.setopt(pycurl.SSL_VERIFYHOST, 2)

            log(f"Created new curl handle for thread {threading.current_thread().name}", level="debug", category="network")
        return self._curl_local.curl

    def clear_api_cookies(self):
        """Clear pycurl cookies before starting new gallery upload.

        CRITICAL: Must be called before each new gallery to prevent PHP session
        reuse that causes multiple galleries to share the same gallery_id.

        This clears API cookies (pycurl), NOT web session cookies (requests.Session).
        """
        if hasattr(self._curl_local, 'curl'):
            import pycurl
            curl = self._curl_local.curl
            curl.setopt(pycurl.COOKIELIST, "ALL")
            log("Cleared pycurl API cookies for new gallery", level="debug", category="uploads")

    # ============================================================================
    # WEB OPERATIONS - DISABLED
    # ============================================================================
    # All web-based operations (login, rename, visibility) are now handled by
    # RenameWorker which maintains a separate long-lived web session.
    # ImxToUploader is API-only and uses X-API-Key for uploads.
    #
    # The following methods raise NotImplementedError to ensure ONE RENAMEWORKER
    # handles all web operations consistently.
    # ============================================================================
    #
    # def login(self):
    #     """Login to imx.to web interface
    # 
    #     DEPRECATED: Use RenameWorker for all web-based authentication.
    #     ImxToUploader is now API-only.
    #     """
    #     raise NotImplementedError(
    #         "ImxToUploader.login() is deprecated. Use RenameWorker for all web operations. "
    #         "ImxToUploader is API-only and uses X-API-Key for uploads."
    #     )
    # 
    #     if not self.username or not self.password:
    #     Attempt cookie-based session login even without stored username/password if enabled
    #         use_cookies = True
    #         try:
    #             cfg = configparser.ConfigParser()
    #             cfg_path = get_config_path()
    #             if os.path.exists(cfg_path):
    #                 cfg.read(cfg_path)
    #                 if 'CREDENTIALS' in cfg:
    #                     use_cookies = str(cfg['CREDENTIALS'].get('cookies_enabled', 'true')).lower() != 'false'
    #         except Exception:
    #             use_cookies = True
    #         if use_cookies:
    #             try:
    #                login_start = time.time()
    #                log(f" DEBUG: Starting cookie-based login process...")
    #                log(f" Attempting to use cookies to bypass DDoS-Guard...")
    # 
    #                 cookies_start = time.time()
    #                 firefox_cookies = get_firefox_cookies("imx.to", cookie_names=REQUIRED_COOKIES)
    #                 firefox_time = time.time() - cookies_start
    #                 log(f" DEBUG: Firefox cookies took {firefox_time:.3f}s")
    #                 
    #                 file_start = time.time()
    #                 file_cookies = load_cookies_from_file("cookies.txt")
    #                 file_time = time.time() - file_start
    #                 log(f" DEBUG: File cookies took {file_time:.3f}s")
    #                 all_cookies = {}
    #                 if firefox_cookies:
    #                    log(f" Found {len(firefox_cookies)} Firefox cookies for imx.to")
    #                     all_cookies.update(firefox_cookies)
    #                 if file_cookies:
    #                     log(f" Loaded cookies from cookies.txt")
    #                     all_cookies.update(file_cookies)
    #                 if all_cookies:
    #                     for name, cookie_data in all_cookies.items():
    #                         try:
    #                             self.session.cookies.set(name, cookie_data['value'], domain=cookie_data['domain'], path=cookie_data['path'])
    #                         except Exception:
    #                             pass
    #                     test_response = self.session.get(f"{self.web_url}/user/gallery/manage")
    #                     if 'login' not in test_response.url and 'DDoS-Guard' not in test_response.text:
    #                         log(f"Successfully authenticated using cookies (no password login)", level="debug", category="auth")
    #                         try:
    #                             self.last_login_method = "cookies"
    #                         except Exception:
    #                             pass
    #                         return True
    #             except Exception:
    #                 Ignore cookie errors and fall back
    #                 pass
    #         if self.api_key:
    #             log(f"Using API key authentication - gallery naming may be limited", level="debug", category="info")
    #             try:
    #                 self.last_login_method = "api_key"
    #             except Exception:
    #                 pass
    #             return True
    #         else:
    #             log(f"No stored credentials, gallery naming disabled", level="warning", category="auth")
    #             try:
    #                 self.last_login_method = "none"
    #             except Exception:
    #                 pass
    #             return False
    #     
    #     max_retries = 1
    #     for attempt in range(max_retries):
    #         try:
    #             if attempt > 0:
    #                 log(f" Retry attempt {attempt + 1}/{max_retries}")
    #                 time.sleep(1)
    #             
    #             Try to get cookies first (browser + file) if enabled
    #             use_cookies = True
    #             try:
    #                 cfg = configparser.ConfigParser()
    #                 cfg_path = get_config_path()
    #                 if os.path.exists(cfg_path):
    #                     cfg.read(cfg_path)
    #                     if 'CREDENTIALS' in cfg:
    #                         use_cookies = str(cfg['CREDENTIALS'].get('cookies_enabled', 'true')).lower() != 'false'
    #             except Exception:
    #                 use_cookies = True
    #             if use_cookies:
    #                 log(f" Attempting to use cookies to bypass DDoS-Guard...")
    #                 firefox_cookies = get_firefox_cookies("imx.to", cookie_names=REQUIRED_COOKIES)
    #                 file_cookies = load_cookies_from_file("cookies.txt")
    #                 all_cookies = {}
    #                 if firefox_cookies:
    #                     log(f" Found {len(firefox_cookies)} Firefox cookies for imx.to")
    #                     all_cookies.update(firefox_cookies)
    #                 if file_cookies:
    #                     log(f" Loaded cookies from cookies.txt")
    #                     all_cookies.update(file_cookies)
    #                 if all_cookies:
    #                    # Add cookies to session
    #                     for name, cookie_data in all_cookies.items():
    #                         try:
    #                             self.session.cookies.set(name, cookie_data['value'], domain=cookie_data['domain'], path=cookie_data['path'])
    #                         except Exception:
    #                             #Best effort
    #                             pass
    #                     Test if we're already logged in with cookies
    #                     test_response = self.session.get(f"{self.web_url}/user/gallery/manage")
    #                     if 'login' not in test_response.url and 'DDoS-Guard' not in test_response.text:
    #                         log(f"Successfully authenticated using cookies (no password login)", level="info", category="auth")
    #                         try:
    #                             self.last_login_method = "cookies"
    #                         except Exception:
    #                             pass
    #                         return True
    #             else:
    #                 log(f" Skipping Firefox cookies per settings")
    #             
    #             #Fall back to regular login
    #             log(f" Attempting login to {self.web_url}/login.php")
    #             login_page = self.session.get(f"{self.web_url}/login.php")
    #             
    #             Submit login form
    #             login_data = {
    #                 'usr_email': self.username,
    #                 'pwd': self.password,
    #                 'remember': '1',
    #                 'doLogin': 'Login'
    #             }
    #             
    #             response = self.session.post(f"{self.web_url}/login.php", data=login_data)
    #             
    #            # Check if we hit DDoS-Guard
    #             if 'DDoS-Guard' in response.text or 'ddos-guard' in response.text:
    #                 log(f"DDoS-Guard detected", level="warning", category="auth")
    # 
    #                # If bypass didn't work, try browser cookies fallback
    #             log(f"Trying browser cookies...", level="debug", category="auth")
    #             firefox_cookies = get_firefox_cookies("imx.to", cookie_names=REQUIRED_COOKIES) if use_cookies else {}
    #             file_cookies = load_cookies_from_file("cookies.txt") if use_cookies else {}
    #             all_cookies = {**firefox_cookies, **file_cookies} if use_cookies else {}
    # 
    #             if all_cookies:
    #                 log(f"Retrying with browser cookies...", level="debug", category="auth")
    #                # Clear session and try with cookies (use resilient session)
    #                 defaults = load_user_defaults()
    #                 parallel_batch_size = defaults.get('parallel_batch_size', 4)
    #                 self.session = self._setup_resilient_session(parallel_batch_size)
    #                 self.session.headers.update({
    #                     'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:141.0) Gecko/20100101 Firefox/141.0',
    #                     'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    #                     'Accept-Language': 'en-US',
    #                     'Accept-Encoding': 'gzip, deflate, br, zstd',
    #                     'DNT': '1'
    #                 })
    # 
    #                 for name, cookie_data in all_cookies.items():
    #                     self.session.cookies.set(name, cookie_data['value'],
    #                                           domain=cookie_data['domain'],
    #                                           path=cookie_data['path'])
    # 
    #                 #Try login again with cookies
    #                 response = self.session.post(f"{self.web_url}/login.php", data=login_data)
    # 
    #                # If we still hit DDoS-Guard but have cookies, test if we can access user pages
    #                 if 'DDoS-Guard' in response.text or 'ddos-guard' in response.text:
    #                     log(f"DDoS-Guard detected but cookies loaded - testing access to user pages...", level="debug", category="auth")
    #                     #Test if we can access a user page
    #                     test_response = self.session.get(f"{self.web_url}/user/gallery/manage")
    #                     if test_response.status_code == 200 and 'login' not in test_response.url:
    #                         log(f"Successfully accessed user pages with cookies", level="debug", category="auth")
    #                         try:
    #                             self.last_login_method = "cookies"
    #                         except Exception:
    #                             pass
    #                         return True
    #                     else:
    #                         log(f"Cannot access user pages despite cookies - login may have failed", level="debug", category="auth")
    #                         if attempt < max_retries - 1:
    #                             continue
    #                         else:
    #                             return False
    #                 
    #                 if 'DDoS-Guard' in response.text or 'ddos-guard' in response.text:
    #                     log(f"DDoS-Guard still detected, falling back to API-only upload...", level="debug", category="auth")
    #                     if attempt < max_retries - 1:
    #                         continue
    #                     else:
    #                         return False
    #             
    #            # Check if login was successful
    #             if 'user' in response.url or 'dashboard' in response.url or 'gallery' in response.url:
    #                 log(f"Successfully logged in", level="info", category="auth")
    #                 try:
    #                     self.last_login_method = "credentials"
    #                 except Exception:
    #                     pass
    #                 return True
    #             else:
    #                 log(f"Login failed - check username/password", level="warning", category="auth")
    #                 if attempt < max_retries - 1:
    #                     continue
    #                 else:
    #                     return False
    #                 
    #         except Exception as e:
    #             log(f"Login error: {str(e)}", level="error", category="auth")
    #             if attempt < max_retries - 1:
    #                 continue
    #             else:
    #                 return False
    #     
    #     return False

    #def login_with_credentials_only(self) -> bool:
    #    """Login using stored username/password without attempting cookies.
    #
    #    Returns True on success and sets last_login_method to 'credentials'.
    #    """
    #    if not self.username or not self.password:
    #        return False
    #    try:
    #        # Fresh resilient session without any cookie loading
    #        defaults = load_user_defaults()
    #        parallel_batch_size = defaults.get('parallel_batch_size', 4)
    #        self.session = self._setup_resilient_session(parallel_batch_size)
    #        self.session.headers.update({
    #            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:141.0) Gecko/20100101 Firefox/141.0',
    #            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    #            'Accept-Language': 'en-US',
    #            'Accept-Encoding': 'gzip, deflate, br, zstd',
    #            'DNT': '1'
    #        })
    #        # Submit login form directly
    #        login_data = {
    #            'usr_email': self.username,
    #            'pwd': self.password,
    #            'remember': '1',
    #            'doLogin': 'Login'
    #        }
    #        response = self.session.post(f"{self.web_url}/login.php", data=login_data)
    #        if 'user' in response.url or 'dashboard' in response.url or 'gallery' in response.url:
    #            try:
    #                self.last_login_method = "credentials"
    #            except Exception:
    #                pass
    #            return True
    #        return False
    #    except Exception:
    #        return False
    
    #def create_gallery_with_name(self, gallery_name, skip_login=False):
    #    """Create a gallery with a specific name using web interface"""
    #    if not skip_login and not self.login():
    #        log(f"Login failed - cannot create gallery with name", level="debug", category="auth")
    #        return None
    #    
    #    try:
    #        # Get the add gallery page
    #        add_page = self.session.get(f"{self.web_url}/user/gallery/add")
    #        
    #        # Submit gallery creation form
    #        gallery_data = {
    #            'gallery_name': gallery_name,
    #            'public_gallery': '1',  # Always public for now
    #            'submit_new_gallery': 'Add'
    #        }
    #        
    #        response = self.session.post(f"{self.web_url}/user/gallery/add", data=gallery_data)
    #        
    #        # Extract gallery ID from redirect URL
    #        if 'gallery/manage?id=' in response.url:
    #            gallery_id = response.url.split('id=')[1]
    #            log(f"Created gallery '{gallery_name}' with ID '{gallery_id}'", level="debug", category="auth")
    #            return gallery_id
    #        else:
    #            log(f"Failed to create gallery", level="debug", category="auth")
    #            log(f"- Response URL: {response.url}", level="debug", category="auth")
    #            log(f"- Response status: {response.status_code}", level="debug", category="auth")
    #            if 'DDoS-Guard' in response.text:
    #                log(f"DDoS-Guard detected in gallery creation", level="debug", category="auth")
    #            return None
    #            
    #    except Exception as e:
    #        log(f"Error creating gallery: {str(e)}", level="error")
    #        return None
    
    # REMOVED: _upload_without_named_gallery — unified into upload_folder
    
    #def rename_gallery(self, gallery_id, new_name):
    #    """Rename an existing gallery"""
    #    if not self.login():
    #        return False
    #    
    #    try:
    #        # Get the edit gallery page
    #        edit_page = self.session.get(f"{self.web_url}/user/gallery/edit?id={gallery_id}")
    #        
    #        # Submit gallery rename form
    #        rename_data = {
    #            'gallery_name': new_name,
    #            'submit_new_gallery': 'Rename Gallery',
    #            'public_gallery': '1'
    #        }
    #        
    #        response = self.session.post(f"{self.web_url}/user/gallery/edit?id={gallery_id}", data=rename_data)
    #        
    #        if response.status_code == 200:
    #            log(f"Successfully renamed gallery '{gallery_id}' to '{new_name}'", level="info")
    #            return True
    #        else:
    #            log(f"Failed to rename gallery", level="debug", category="renaming")
    #            return False
    #            
    #    except Exception as e:
    #        log(f"Error renaming gallery: {str(e)}", level="error", category="renaming")
    #        return False
    
    #def rename_gallery_with_session(self, gallery_id, new_name):
    #    """Rename an existing gallery using existing session (no login call)"""
    #    try:
    #        # Sanitize the gallery name
    #        original_name = new_name
    #        new_name = sanitize_gallery_name(new_name)
    #        if original_name != new_name:
    #            log(f"Sanitized gallery name: '{original_name}' -> '{new_name}'", level="debug", category="renaming")
    #        
    #        # Get the edit gallery page
    #        edit_page = self.session.get(f"{self.web_url}/user/gallery/edit?id={gallery_id}")
    #        # Track last rename status for caller logic
    #        try:
    #            self._last_rename_status_code = getattr(edit_page, 'status_code', None)
    #            self._last_rename_ddos = bool('DDoS-Guard' in (edit_page.text or ''))
    #        except Exception:
    #            self._last_rename_status_code = None
    #            self._last_rename_ddos = False
    #        
    #        # Check if we can access the edit page
    #        if edit_page.status_code != 200:
    #            if 'DDoS-Guard' in edit_page.text:
    #                log(f"DDoS-Guard detected while accessing edit page for gallery {gallery_id} (status: {edit_page.status_code})", level="debug", category="network")
    #            else:
    #                log(f"Failed to access edit page for gallery {gallery_id} (status: {edit_page.status_code})", level="debug", category="network")
    #            return False
    #
    #        # Check if we're actually logged in by looking for login form
    #        if 'login' in edit_page.url or 'login' in edit_page.text.lower():
    #            log(f"Not logged in - redirecting to login page", level="debug", category="auth")
    #            return False
    #        
    #        # Submit gallery rename form
    #        rename_data = {
    #            'gallery_name': new_name,
    #            'submit_new_gallery': 'Rename Gallery',
    #            'public_gallery': '1'
    #        }
    #        
    #        response = self.session.post(f"{self.web_url}/user/gallery/edit?id={gallery_id}", data=rename_data)
    #        # Track last rename status for caller logic
    #        try:
    #            self._last_rename_status_code = getattr(response, 'status_code', None)
    #            self._last_rename_ddos = bool('DDoS-Guard' in (response.text or ''))
    #        except Exception:
    #            self._last_rename_status_code = None
    #            self._last_rename_ddos = False
    #        
    #        if response.status_code == 200:
    #            # Check if the rename was actually successful
    #            if 'success' in response.text.lower() or 'gallery' in response.url:
    #                log(f"Rename Worker: Successfully renamed gallery on imx.to ({gallery_id}) --> '{new_name}'", level="info", category="renaming")
    #                return True
    #            else:
    #                log(f"Rename request returned 200 but may have failed", level="debug", category="renaming")
    #                if 'DDoS-Guard' in response.text:
    #                    log(f"DDoS-Guard detected in rename response", level="debug", category="renaming")
    #                return False
    #        else:
    #            log(f"Failed to rename gallery (status: {response.status_code})", level="debug", category="renaming")
    #            if 'DDoS-Guard' in response.text:
    #                log(f"DDoS-Guard detected in error response", level="debug", category="renaming")
    #            return False
    #            
    #    except Exception as e:
    #        log(f"Error renaming gallery: {str(e)}", level="error", category="renaming")
    #        return False
    
    #def set_gallery_visibility(self, gallery_id, visibility):
    #    """Set gallery visibility (public/private)
    #
    #    Args:
    #        gallery_id: Gallery ID
    #        visibility: 1 for public, 0 for private
    #    """
    #    if not self.login():
    #        return False
    #
    #    try:
    #        # Get the edit gallery page
    #        edit_page = self.session.get(f"{self.web_url}/user/gallery/edit?id={gallery_id}")
    #
    #        # Submit gallery visibility form
    #        visibility_data = {
    #            'public_gallery': str(visibility),
    #            'submit_new_gallery': 'Update Gallery'
    #        }
    #        
    #        response = self.session.post(f"{self.web_url}/user/gallery/edit?id={gallery_id}", data=visibility_data)
    #        
    #        if response.status_code == 200:
    #            log(f"Successfully set gallery {gallery_id} visibility", level="debug")
    #            return True
    #        else:
    #            log(f"Failed to update gallery visibility", level="warning")
    #            return False
    #            
    #    except Exception as e:
    #        log(f"Error updating gallery visibility: {str(e)}", level="error")
    #        return False
    
    def upload_image(self, image_path, create_gallery=False, gallery_id=None, thumbnail_size=3, thumbnail_format=2, thread_session=None, progress_callback=None):
        """
        Upload a single image to imx.to

        Args:
            image_path (str): Path to the image file
            create_gallery (bool): Whether to create a new gallery
            gallery_id (str): ID of existing gallery to add image to
            thumbnail_size (int): Thumbnail size (1=100x100, 2=180x180, 3=250x250, 4=300x300, 6=150x150)
            thumbnail_format (int): Thumbnail format (1=Fixed width, 2=Proportional, 3=Square, 4=Fixed height)
            thread_session (requests.Session): Optional thread-local session for concurrent uploads
            progress_callback (callable): Optional callback(bytes_sent, total_bytes) for bandwidth tracking

        Returns:
            dict: API response
        """
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Image file not found: {image_path}")

        # Use thread-local session if provided, otherwise use shared session
        session = thread_session if thread_session else self.session

        # Read file into memory BEFORE POST to enable true concurrent uploads
        # Keeping file handles open during network I/O causes Python's file I/O to serialize
        # the reads even though HTTP operations can be concurrent (7x performance penalty)
        file_read_start = time.time()
        with open(image_path, 'rb') as f:
            file_data = f.read()
        file_read_time = time.time() - file_read_start

        if not hasattr(self, '_first_read_logged'):
            log(f"Read {os.path.basename(image_path)} ({len(file_data)/1024/1024:.1f}MB) in {file_read_time:.3f}s", level="debug", category="fileio")
            self._first_read_logged = True

        # Use pycurl for upload with real progress tracking
        content_type = mimetypes.guess_type(image_path)[0] or 'application/octet-stream'

        try:
            self._upload_count += 1

            # Setup progress callback wrapper
            callback_count = [0]  # Mutable to track in closure

            def curl_progress_callback(download_total, downloaded, upload_total, uploaded):
                callback_count[0] += 1

                if progress_callback and upload_total > 0:
                    try:
                        progress_callback(int(uploaded), int(upload_total))
                    except Exception:
                        pass  # Silently ignore callback errors
                return 0

            # Get or create thread-local curl handle (connection reuse)
            curl = self._get_thread_curl()

            # Reset curl handle to clear previous settings (but keep connection alive)
            curl.reset()

            # NOTE: Cookies are cleared per-gallery (via clear_api_cookies()), NOT per-image.
            # This maintains PHP session continuity within a single gallery upload.
            # Clearing cookies here would break gallery_id association for subsequent images.

            response_buffer = io.BytesIO()

            # Set URL
            curl.setopt(pycurl.URL, self.upload_url)

            # Set headers
            headers_list = [f'{k}: {v}' for k, v in self.headers.items()]
            curl.setopt(pycurl.HTTPHEADER, headers_list)

            # Prepare multipart form data
            form_data = [
                ('image', (
                    pycurl.FORM_BUFFER, os.path.basename(image_path),
                    pycurl.FORM_BUFFERPTR, file_data,
                    pycurl.FORM_CONTENTTYPE, content_type
                )),
                ('format', 'all'),
                ('thumbnail_size', str(thumbnail_size)),
                ('thumbnail_format', str(thumbnail_format))
            ]

            if create_gallery:
                form_data.append(('create_gallery', 'true'))
            if gallery_id:
                form_data.append(('gallery_id', gallery_id))

            curl.setopt(pycurl.HTTPPOST, form_data)

            # Set progress tracking
            if progress_callback:
                curl.setopt(pycurl.NOPROGRESS, 0)
                curl.setopt(pycurl.XFERINFOFUNCTION, curl_progress_callback)

            # Capture response
            curl.setopt(pycurl.WRITEDATA, response_buffer)

            # Set timeouts
            curl.setopt(pycurl.CONNECTTIMEOUT, self.upload_connect_timeout)
            curl.setopt(pycurl.TIMEOUT, self.upload_read_timeout)

            # Perform upload
            curl.perform()

            # Get response
            status_code = curl.getinfo(pycurl.RESPONSE_CODE)
            # NOTE: Don't close curl handle - keep connection alive for reuse

            if status_code == 200:
                json_response = json.loads(response_buffer.getvalue())
                return json_response
            else:
                response_text = response_buffer.getvalue().decode('utf-8', errors='replace')
                raise Exception(f"Upload failed with status code {status_code}: {response_text}")

        except pycurl.error as e:
            # pycurl error codes: 28=timeout, 7=connection failed, etc.
            error_code, error_msg = e.args if len(e.args) == 2 else (0, str(e))
            if error_code == 28:
                raise Exception(f"Upload timeout (connect={self.upload_connect_timeout}s, read={self.upload_read_timeout}s): {error_msg}")
            elif error_code == 7:
                raise Exception(f"Connection error during upload: {error_msg}")
            else:
                raise Exception(f"Network error during upload (code {error_code}): {error_msg}")
    
    def upload_folder(self, folder_path, gallery_name=None, thumbnail_size=3, thumbnail_format=2, max_retries=3, parallel_batch_size=4, template_name="default", queue_store=None):
        """
        Upload all images in a folder as a gallery
    def upload_folder(self, folder_path, gallery_name=None, thumbnail_size=3, thumbnail_format=2, max_retries=3, parallel_batch_size=4, template_name="default"):
        Args:
            folder_path (str): Path to folder containing images
            gallery_name (str): Name for the gallery (optional)
            thumbnail_size (int): Thumbnail size setting
            thumbnail_format (int): Thumbnail format setting
            max_retries (int): Maximum retry attempts for failed uploads
            
        Returns:
            dict: Contains gallery URL and individual image URLs
        """
        start_time = time.time()
        log(f"upload_folder({folder_path}) started at {start_time:.6f}", level="debug", category="timing")
        
        if not os.path.exists(folder_path):
            raise FileNotFoundError(f"Folder not found: {folder_path}")
        
        # Get all image files in folder and calculate total size
        scan_start = time.time()
        image_extensions = ('.jpg', '.jpeg', '.png', '.gif')
        image_files = []
        total_size = 0
        image_dimensions = []
        
        for f in os.listdir(folder_path):
            if f.lower().endswith(image_extensions) and os.path.isfile(os.path.join(folder_path, f)):
                image_files.append(f)
                file_path = os.path.join(folder_path, f)
                file_size = os.path.getsize(file_path)
                total_size += file_size
                
                # Get image dimensions using PIL
                try:
                    from PIL import Image
                    with Image.open(file_path) as img:
                        width, height = img.size
                        image_dimensions.append((width, height))
                except ImportError:
                    image_dimensions.append((0, 0))  # PIL not available
                except Exception:
                    image_dimensions.append((0, 0))  # Error reading image
        
        scan_duration = time.time() - scan_start
        log(f" [TIMING] File scanning and PIL processing took {scan_duration:.6f}s for {len(image_files)} files")
        
        if not image_files:
            raise ValueError(f"No image files found in {folder_path}")
        
        # Create gallery with name (default to folder name if not provided)
        if not gallery_name:
            gallery_name = os.path.basename(folder_path)
        
        # Keep original gallery name - sanitization only happens in rename worker
        original_name = gallery_name
        
        # Check if gallery already exists
        check_start = time.time()
        existing_files = check_if_gallery_exists(gallery_name)
        check_duration = time.time() - check_start
        log(f" [TIMING] Gallery existence check took {check_duration:.6f}s")
        
        if existing_files:
            log(f" Found existing gallery files for '{gallery_name}':")
            for file_path in existing_files:
                log(f"   {file_path}")
            
            response = input(f"{timestamp()} Gallery appears to already exist. Continue anyway? (y/N): ")
            if response.lower() != 'y':
                log(f" Skipping {folder_path}")
                return None
        
        # Create gallery (skip login since it's already done). If creation fails, fall back to API-only
        create_start = time.time()
        gallery_id = self.create_gallery_with_name(gallery_name, skip_login=True)
        create_duration = time.time() - create_start
        log(f" [TIMING] Gallery creation took {create_duration:.6f}s")
        initial_completed = 0
        initial_uploaded_size = 0
        preseed_images = []
        files_to_upload = []
        if not gallery_id:
            log(f" Failed to create named gallery, falling back to API-only upload...")
            # Upload first image to create gallery
            first_file = image_files[0]
            first_image_path = os.path.join(folder_path, first_file)
            log(f" Uploading first image: {first_file}")
            first_response = self.upload_image(
                first_image_path,
                create_gallery=True,
                thumbnail_size=thumbnail_size,
                thumbnail_format=thumbnail_format
            )
            if first_response.get('status') != 'success':
                raise Exception(f"{timestamp()} Failed to create gallery: {first_response}")
            gallery_id = first_response['data'].get('gallery_id')
            # Save for later renaming (with sanitized name)
            save_unnamed_gallery(gallery_id, gallery_name)
            preseed_images = [first_response['data']]
            initial_completed = 1
            try:
                initial_uploaded_size = os.path.getsize(first_image_path)
            except Exception:
                initial_uploaded_size = 0
            files_to_upload = image_files[1:]
        else:
            files_to_upload = image_files
        
        gallery_url = f"https://imx.to/g/{gallery_id}"
        
        # Store results
        results = {
            'gallery_url': gallery_url,
            'images': list(preseed_images)
        }
        
        # Upload all images to the created gallery with progress bars
        def upload_single_image(image_file, attempt=1, pbar=None):
            image_path = os.path.join(folder_path, image_file)
            
            try:
                response = self.upload_image(
                    image_path, 
                    gallery_id=gallery_id,
                    thumbnail_size=thumbnail_size,
                    thumbnail_format=thumbnail_format
                )
                
                if response.get('status') == 'success':
                    if pbar:
                        pbar.set_postfix_str(f"✓ {image_file}")
                    return image_file, response['data'], None
                else:
                    error_msg = f"API error: {response}"
                    if pbar:
                        pbar.set_postfix_str(f"✗ {image_file}")
                    return image_file, None, error_msg
                    
            except Exception as e:
                error_msg = f"Network error: {str(e)}"
                if pbar:
                    pbar.set_postfix_str(f"✗ {image_file}")
                return image_file, None, error_msg
        
        # Upload images with retries, maintaining order
        uploaded_images = []
        failed_images = []
        
        # Rolling concurrency: keep N workers busy until all submitted
        with tqdm(total=len(image_files), initial=initial_completed, desc=f"Uploading to {gallery_name}", unit="img", leave=False) as pbar:
            with ThreadPoolExecutor(max_workers=parallel_batch_size) as executor:
                import queue
                remaining = queue.Queue()
                for f in files_to_upload:
                    remaining.put(f)
                futures_map = {}
                # Prime the pool
                for _ in range(min(parallel_batch_size, remaining.qsize())):
                    img = remaining.get()
                    futures_map[executor.submit(upload_single_image, img, 1, pbar)] = img
                
                while futures_map:
                    done, _ = concurrent.futures.wait(list(futures_map.keys()), return_when=concurrent.futures.FIRST_COMPLETED)
                    for fut in done:
                        img = futures_map.pop(fut)
                        image_file, image_data, error = fut.result()
                        if image_data:
                            uploaded_images.append((image_file, image_data))
                        else:
                            failed_images.append((image_file, error))
                        pbar.update(1)
                        # Submit next if any left
                        if not remaining.empty():
                            nxt = remaining.get()
                            futures_map[executor.submit(upload_single_image, nxt, 1, pbar)] = nxt
        
        # Retry failed uploads with progress bar
        retry_count = 0
        while failed_images and retry_count < max_retries:
            retry_count += 1
            retry_failed = []
            
            with tqdm(total=len(failed_images), desc=f"Retry {retry_count}/{max_retries}", unit="img", leave=False) as retry_pbar:
                with ThreadPoolExecutor(max_workers=parallel_batch_size) as executor:
                    import queue
                    remaining = queue.Queue()
                    for img, _ in failed_images:
                        remaining.put(img)
                    futures_map = {}
                    for _ in range(min(parallel_batch_size, remaining.qsize())):
                        img = remaining.get()
                        futures_map[executor.submit(upload_single_image, img, retry_count + 1, retry_pbar)] = img
                    
                    while futures_map:
                        done, _ = concurrent.futures.wait(list(futures_map.keys()), return_when=concurrent.futures.FIRST_COMPLETED)
                        for fut in done:
                            img = futures_map.pop(fut)
                            image_file, image_data, error = fut.result()
                            if image_data:
                                uploaded_images.append((image_file, image_data))
                            else:
                                retry_failed.append((image_file, error))
                            retry_pbar.update(1)
                            if not remaining.empty():
                                nxt = remaining.get()
                                futures_map[executor.submit(upload_single_image, nxt, retry_count + 1, retry_pbar)] = nxt
            
            failed_images = retry_failed
        
        # Sort uploaded images by original file order
        uploaded_images.sort(key=lambda x: image_files.index(x[0]))
        
        # Add to results in correct order
        for _, image_data in uploaded_images:
            results['images'].append(image_data)
        
        # Calculate statistics
        end_time = time.time()
        upload_time = end_time - start_time
        
        # Calculate transfer speed
        uploaded_size = initial_uploaded_size + sum(os.path.getsize(os.path.join(folder_path, img_file)) 
                           for img_file, _ in uploaded_images)
        transfer_speed = uploaded_size / upload_time if upload_time > 0 else 0
        
        # Calculate image dimension statistics
        successful_dimensions = []
        if initial_completed == 1:
            try:
                successful_dimensions.append(image_dimensions[image_files.index(image_files[0])])
            except Exception:
                pass
        successful_dimensions.extend([image_dimensions[image_files.index(img_file)] 
                               for img_file, _ in uploaded_images])
        avg_width = sum(w for w, h in successful_dimensions) / len(successful_dimensions) if successful_dimensions else 0
        avg_height = sum(h for w, h in successful_dimensions) / len(successful_dimensions) if successful_dimensions else 0
        log(f" Successful dimensions: {successful_dimensions}")
        max_width = max(w for w, h in successful_dimensions) if successful_dimensions else 0
        max_height = max(h for w, h in successful_dimensions) if successful_dimensions else 0
        min_width = min(w for w, h in successful_dimensions) if successful_dimensions else 0
        min_height = min(h for w, h in successful_dimensions) if successful_dimensions else 0
        
        # Add statistics to results
        log(f"Returning original_name='{original_name}' as gallery_name, actual upload name was='{gallery_name}'", level="debug")
        results.update({
            'gallery_id': gallery_id,
            'gallery_name': original_name,
            'upload_time': upload_time,
            'total_size': total_size,
            'uploaded_size': uploaded_size,
            'transfer_speed': transfer_speed,
            'avg_width': avg_width,
            'avg_height': avg_height,
            'max_width': max_width,
            'max_height': max_height,
            'min_width': min_width,
            'min_height': min_height,
            'successful_count': initial_completed + len(uploaded_images),
            'failed_count': len(failed_images)
        })
        
        # Ensure .uploaded exists; do not create separate gallery_{id} folder
        uploaded_subdir = os.path.join(folder_path, ".uploaded")
        os.makedirs(uploaded_subdir, exist_ok=True)
        
        # Build filenames
        _, json_filename, bbcode_filename = build_gallery_filenames(gallery_name, gallery_id)
        
        # Prepare template data
        all_images_bbcode = ""
        for image_data in results['images']:
            all_images_bbcode += image_data['bbcode'] + "  "
        
        # Calculate folder size (binary units)
        try:
            folder_size = format_binary_size(total_size, precision=1)
        except Exception:
            folder_size = f"{int(total_size)} B"
        
        # Get most common extension
        extensions = []
        if initial_completed == 1:
            try:
                extensions.append(os.path.splitext(image_files[0])[1].upper().lstrip('.'))
            except Exception:
                pass
        extensions.extend([os.path.splitext(img_file)[1].upper().lstrip('.') 
                     for img_file, _ in uploaded_images])
        extension = max(set(extensions), key=extensions.count) if extensions else "JPG"
        
        # Prepare template data
        log(f"Template: original_name='{original_name}', gallery_name='{gallery_name}'", level="debug")
        template_data = {
            'folder_name': original_name,
            'width': int(avg_width),
            'height': int(avg_height),
            'longest': int(max(avg_width, avg_height)),
            'extension': extension,
            'picture_count': initial_completed + len(uploaded_images),
            'folder_size': folder_size,
            'gallery_link': f"https://imx.to/g/{gallery_id}",
            'all_images': all_images_bbcode.strip()
        }
        
        # Generate bbcode using specified template and save artifacts centrally
        bbcode_content = generate_bbcode_from_template(template_name, template_data)
        try:
            log(f"About to save artifacts with original_name='{original_name}', upload_name='{gallery_name}'", level="debug")
            save_gallery_artifacts(
                folder_path=folder_path,
                results={
                    'gallery_id': gallery_id,
                    'gallery_name': original_name,
                    'images': results['images'],
                    'total_size': total_size,
                    'successful_count': results.get('successful_count', 0),
                    'failed_count': results.get('failed_count', 0),
                    'upload_time': upload_time,
                    'uploaded_size': uploaded_size,
                    'transfer_speed': transfer_speed,
                    'avg_width': avg_width,
                    'avg_height': avg_height,
                    'max_width': max_width,
                    'max_height': max_height,
                    'min_width': min_width,
                    'min_height': min_height,
                    'failed_details': failed_images,
                    'thumbnail_size': thumbnail_size,
                    'thumbnail_format': thumbnail_format,
                    'parallel_batch_size': parallel_batch_size,
                    'total_images': len(image_files),
                    'started_at': datetime.fromtimestamp(start_time).strftime('%Y-%m-%d %H:%M:%S'),
                },
                template_name=template_name,
            )
            log(f" Saved gallery files to central and/or .uploaded as configured")
        except Exception as e:
            log(f" Error writing artifacts: {e}")

        # Compose and save JSON artifact at both locations
        try:
            # Per-image dimensions are known in image_dimensions; map filenames
            dims_by_name = {}
            for idx, (w, h) in enumerate(image_dimensions):
                if idx < len(image_files):
                    dims_by_name[image_files[idx]] = (w, h)

            # Build images list
            images_payload = []
            # Include preseeded first image in JSON payload if present
            if initial_completed == 1 and preseed_images:
                first_fname = image_files[0]
                w, h = dims_by_name.get(first_fname, (0, 0))
                try:
                    size_bytes = os.path.getsize(os.path.join(folder_path, first_fname))
                except Exception:
                    size_bytes = 0
                data0 = preseed_images[0]
                # Ensure lowercase extension
                try:
                    base0, ext0 = os.path.splitext(first_fname)
                    first_fname_norm = base0 + ext0.lower()
                except Exception:
                    first_fname_norm = first_fname
                # Derive thumb_url from image_url if missing
                t0 = data0.get('thumb_url')
                if not t0 and data0.get('image_url'):
                    try:
                        parts = data0.get('image_url').split('/i/')
                        if len(parts) == 2 and parts[1]:
                            img_id = parts[1].split('/')[0]
                            ext_use = ext0.lower() if ext0 else '.jpg'
                            t0 = f"https://imx.to/u/t/{img_id}{ext_use}"
                    except Exception:
                        pass
                images_payload.append({
                    'filename': first_fname_norm,
                    'uploaded_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'image_url': data0.get('image_url'),
                    'thumb_url': t0,
                    'bbcode': data0.get('bbcode'),
                    'width': w,
                    'height': h,
                    'size_bytes': size_bytes
                })

            for fname, data in uploaded_images:
                w, h = dims_by_name.get(fname, (0, 0))
                try:
                    size_bytes = os.path.getsize(os.path.join(folder_path, fname))
                except Exception:
                    size_bytes = 0
                # Lowercase extension for filename
                try:
                    base, ext = os.path.splitext(fname)
                    fname_norm = base + ext.lower()
                except Exception:
                    fname_norm = fname
                # Derive thumb_url from image_url if missing
                t = data.get('thumb_url')
                if not t and data.get('image_url'):
                    try:
                        parts = data.get('image_url').split('/i/')
                        if len(parts) == 2 and parts[1]:
                            img_id = parts[1].split('/')[0]
                            ext_use = ext.lower() if ext else '.jpg'
                            t = f"https://imx.to/u/t/{img_id}{ext_use}"
                    except Exception:
                        pass
                images_payload.append({
                    'filename': fname_norm,
                    'uploaded_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'image_url': data.get('image_url'),
                    'thumb_url': t,
                    'bbcode': data.get('bbcode'),
                    'width': w,
                    'height': h,
                    'size_bytes': size_bytes
                })

            failures_payload = [
                {
                    'filename': fname,
                    'failed_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'reason': reason
                }
                for fname, reason in failed_images
            ]

            json_payload = {
                'meta': {
                    'gallery_name': gallery_name,
                    'gallery_id': gallery_id,
                    'gallery_url': gallery_url,
                    'status': 'completed',
                    'started_at': datetime.fromtimestamp(start_time).strftime('%Y-%m-%d %H:%M:%S'),
                    'finished_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'uploader_version': __version__,
                },
                'settings': {
                    'thumbnail_size': thumbnail_size,
                    'thumbnail_format': thumbnail_format,
                    'template_name': template_name,
                    'parallel_batch_size': parallel_batch_size
                },
                'stats': {
                    'total_images': len(image_files),
                    'successful_count': initial_completed + len(uploaded_images),
                    'failed_count': len(failed_images),
                    'upload_time': upload_time,
                    'total_size': total_size,
                    'uploaded_size': uploaded_size,
                    'avg_width': avg_width,
                    'avg_height': avg_height,
                    'max_width': max_width,
                    'max_height': max_height,
                    'min_width': min_width,
                    'min_height': min_height,
                    'transfer_speed_mb_s': transfer_speed / (1024*1024) if transfer_speed else 0
                },
                'images': images_payload,
                'failures': failures_payload,
                'bbcode_full': bbcode_content
            }

            # Save JSON to .uploaded
            uploaded_json_path = os.path.join(uploaded_subdir, json_filename)
            with open(uploaded_json_path, 'w', encoding='utf-8') as jf:
                json.dump(json_payload, jf, ensure_ascii=False, indent=2)

            # Save JSON to central (use helper paths; central_path defined earlier may not exist here)
            try:
                central_path = get_central_storage_path()
                central_json_path = os.path.join(central_path, json_filename)
                with open(central_json_path, 'w', encoding='utf-8') as jf:
                    json.dump(json_payload, jf, ensure_ascii=False, indent=2)
            except Exception:
                pass
        except Exception as e:
            log(f" Error writing JSON artifact: {e}")
        
        return results

def main():
    # Migrate credentials from INI to Registry (runs once, safe to call multiple times)
    migrate_credentials_from_ini()

    # Auto-launch GUI if double-clicked (no arguments, no other console processes)
    if len(sys.argv) == 1:  # No arguments provided
        try:
            # Check if this is the only process attached to the console
            import ctypes
            kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
            process_array = (ctypes.c_uint * 1)()
            num_processes = kernel32.GetConsoleProcessList(process_array, 1)
            # If num_processes <= 2, likely double-clicked (only this process and conhost)
            # If num_processes > 2, launched from terminal (cmd.exe/powershell also attached)
            if num_processes <= 2:
                sys.argv.append('--gui')
        except (AttributeError, OSError, TypeError):
            pass  # Not Windows or check failed, don't auto-launch GUI

    # Load user defaults
    user_defaults = load_user_defaults()

    parser = argparse.ArgumentParser(description='Upload image folders to imx.to as galleries and generate bbcode.\n\nSettings file: ' + get_config_path())
    parser.add_argument('-v', '--version', action='store_true', help='Show version and exit')
    parser.add_argument('folder_paths', nargs='*', help='Paths to folders containing images')
    parser.add_argument('--name', help='Gallery name (optional, uses folder name if not specified)')
    parser.add_argument('--size', type=int, choices=[1, 2, 3, 4, 6], 
                       default=user_defaults.get('thumbnail_size', 3),
                       help='Thumbnail size: 1=100x100, 2=180x180, 3=250x250, 4=300x300, 6=150x150 (default: 3)')
    parser.add_argument('--format', type=int, choices=[1, 2, 3, 4], 
                       default=user_defaults.get('thumbnail_format', 2),
                       help='Thumbnail format: 1=Fixed width, 2=Proportional, 3=Square, 4=Fixed height (default: 2)')
    parser.add_argument('--max-retries', type=int,
                       default=user_defaults.get('max_retries', 3),
                       help='Maximum retry attempts for failed uploads (default: 3)')
    parser.add_argument('--parallel', type=int,
                       default=user_defaults.get('parallel_batch_size', 4),
                       help='Number of images to upload simultaneously (default: 4)')
    parser.add_argument('--setup-secure', action='store_true',
                       help='Set up secure password storage (interactive)')
    parser.add_argument('--rename-unnamed', action='store_true',
                       help='Rename all unnamed galleries from previous uploads')
    parser.add_argument('--template', '-t', 
                       help='Template name to use for bbcode generation (default: "default")')

    parser.add_argument('--install-context-menu', action='store_true',
                       help='Install Windows context menu integration')
    parser.add_argument('--remove-context-menu', action='store_true',
                       help='Remove Windows context menu integration')
    parser.add_argument('--gui', action='store_true',
                       help='Launch graphical user interface')
    parser.add_argument('--debug', action='store_true',
                       help='Enable debug mode: print all log messages to console')

    args = parser.parse_args()
    if args.version:
        print(f"imxup {__version__}")
        return
    
    # Handle GUI launch
    if args.gui:
        debug_print(f"Launching ImxUp v{__version__} in GUI mode...")
        try:
            # Set environment variable to indicate GUI mode BEFORE stripping --gui from sys.argv
            # This allows ImxToUploader to detect GUI mode even after sys.argv is modified
            os.environ['IMXUP_GUI_MODE'] = '1'

            # Import only lightweight PyQt6 basics for splash screen FIRST
            debug_print("Importing PyQt6.QtWidgets...")
            from PyQt6.QtWidgets import QApplication, QProgressDialog
            from PyQt6.QtCore import Qt, QTimer
            #debug_print("Importing splash screen...")
            from src.gui.splash_screen import SplashScreen

            # Check if folder paths were provided for GUI
            if args.folder_paths:
                # Pass folder paths to GUI for initial loading
                sys.argv = [sys.argv[0]] + args.folder_paths
            else:
                # Remove GUI arg to avoid conflicts with Qt argument parsing
                sys.argv = [sys.argv[0]]

            # Create QApplication and show splash IMMEDIATELY (before heavy imports)
            debug_print("Creating QApplication...")
            app = QApplication(sys.argv)
            #debug_print("Setting Fusion style...")
            app.setStyle("Fusion")
            #debug_print("Setting setQuitOnLastWindowClosed to True...")
            app.setQuitOnLastWindowClosed(True)

            # Install Qt message handler to suppress QPainter warnings
            from PyQt6.QtCore import qInstallMessageHandler, QtMsgType
            def qt_message_handler(msg_type, context, message):
                del context  # Required by Qt signature but unused
                # Suppress QPainter warnings - they're handled gracefully in code
                if "QPainter" in message:
                    return
                # Allow other Qt warnings through
                if msg_type == QtMsgType.QtWarningMsg:
                    print(f"Qt Warning: {message}")

            qInstallMessageHandler(qt_message_handler)

            # Install global exception handler for Qt event loop
            debug_print("Installing exception hook...")
            def qt_exception_hook(exctype, value, traceback_obj):
                import traceback as tb_module
                tb_lines = tb_module.format_exception(exctype, value, traceback_obj)
                tb_text = ''.join(tb_lines)
                print(f"\n{'='*60}")
                print(f"UNCAUGHT EXCEPTION IN QT EVENT LOOP:")
                print(f"{'='*60}")
                print(tb_text)
                print(f"{'='*60}\n")
                # Also try to write to a crash log file
                try:
                    crash_log = os.path.join(os.path.expanduser("~"), ".imxup", "crash.log")
                    with open(crash_log, 'a', encoding='utf-8') as f:
                        f.write(f"\n{'='*60}\n")
                        f.write(f"CRASH AT {datetime.now()}\n")
                        f.write(tb_text)
                        f.write(f"{'='*60}\n")
                    print(f"Crash details written to: {crash_log}")
                except Exception:
                    pass

            sys.excepthook = qt_exception_hook
            #debug_print("Exception hook installed")

            debug_print("Creating splash screen...")
            splash = SplashScreen()
            #debug_print("Showing splash screen...")
            splash.show()
            splash.update_status("Starting ImxUp...")
            debug_print("Processing events...")
            app.processEvents()  # Force splash to appear NOW
            #debug_print("Events processed")

            # NOW import the heavy main_window module (while splash is visible)
            splash.set_status("Loading modules")
            debug_print(f"Launching GUI for ImxUp v{__version__}...")
            if sys.stdout is not None:
                try:
                    sys.stdout.flush()
                except (OSError, AttributeError):
                    pass
            debug_print("Importing main_window...")
            from src.gui.main_window import ImxUploadGUI, check_single_instance

            # Check for existing instance
            folders_to_add = []
            if len(sys.argv) > 1:
                for arg in sys.argv[1:]:
                    if os.path.isdir(arg):
                        folders_to_add.append(arg)
                if folders_to_add and check_single_instance(folders_to_add[0]):
                    splash.finish_and_hide()
                    return
            else:
                if check_single_instance():
                    print(f"{timestamp()} INFO: ImxUp GUI already running, bringing existing instance to front.")
                    splash.finish_and_hide()
                    return

            splash.set_status("Creating main window")

            # Create main window (pass splash for progress updates)
            window = ImxUploadGUI(splash)

            # Now set Fusion style after widgets are initialized
            splash.set_status("Setting Fusion style...")
            app.setStyle("Fusion")

            # Add folders from command line if provided
            if folders_to_add:
                window.add_folders(folders_to_add)

            # Hide splash BEFORE loading galleries
            splash.finish_and_hide()

            # Get gallery count to set up progress dialog properly
            gallery_count = len(window.queue_manager.get_all_items())

            # Load saved galleries with progress dialog (window exists but not shown yet)
            debug_print(f"{timestamp()} Loading {gallery_count} galleries with progress dialog")
            progress = QProgressDialog("Loading saved galleries...", None, 0, gallery_count, None)
            progress.setWindowTitle("ImxUp")
            progress.setWindowModality(Qt.WindowModality.ApplicationModal)
            progress.setMinimumDuration(0)  # Show immediately
            progress.show()
            QApplication.processEvents()

            # Progress callback to update dialog with count
            def update_progress(current, total):
                progress.setValue(current)
                progress.setLabelText(f"{current}/{total} galleries loaded")
                # Process events to keep UI responsive (already batched every 10 galleries)
                QApplication.processEvents()

            window._initialize_table_from_queue(progress_callback=update_progress)

            # DO NOT call processEvents() here - it would force immediate execution of the
            # QTimer.singleShot(100, _create_deferred_widgets) callback, creating 997 widgets
            # synchronously and blocking the UI for 10+ seconds BEFORE the window is shown.
            # Let the deferred widget creation happen naturally after window.show().

            progress.close()

            # NOW show the main window (galleries already loaded)
            window.show()
            window.raise_()        # Bring to front of window stack

            # Defer window activation to avoid blocking the event loop
            QTimer.singleShot(0, window.activateWindow)

            # Initialize file host workers AFTER GUI is loaded and displayed
            if hasattr(window, "file_host_manager") and window.file_host_manager:
                # Count enabled hosts BEFORE starting them (read from INI directly)
                from src.core.file_host_config import get_config_manager, get_file_host_setting
                config_manager = get_config_manager()
                enabled_count = 0
                for host_id in config_manager.hosts:
                    if get_file_host_setting(host_id, 'enabled', 'bool'):
                        enabled_count += 1

                window._file_host_startup_expected = enabled_count
                if window._file_host_startup_expected == 0:
                    window._file_host_startup_complete = True
                    log("No file host workers enabled, skipping startup tracking", level="debug", category="startup")
                else:
                    log(f"Expecting {window._file_host_startup_expected} file host workers to complete spinup",
                        level="debug", category="startup")

                # Now start the workers
                QTimer.singleShot(100, lambda: window.file_host_manager.init_enabled_hosts())

            # Now that GUI is visible, hide the console window (unless --debug)
            if os.name == 'nt' and '--debug' not in sys.argv:
                try:
                    import ctypes
                    kernel32 = ctypes.WinDLL('kernel32')
                    user32 = ctypes.WinDLL('user32')
                    console_window = kernel32.GetConsoleWindow()
                    if console_window:
                        # Try multiple methods to hide the console
                        user32.ShowWindow(console_window, 0)  # SW_HIDE
                        # Also try moving it off-screen
                        user32.SetWindowPos(console_window, 0, -32000, -32000, 0, 0, 0x0001)  # SWP_NOSIZE
                except (AttributeError, OSError):
                    pass

            sys.exit(app.exec())

        except ImportError as e:
            debug_print(f"CRITICAL: Import error: {e}")
            sys.exit(1)
        except Exception as e:
            debug_print(f"CRITICAL: Error launching GUI: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
    
    # Handle secure setup
    if args.setup_secure:
            if setup_secure_password():
                debug_print(f"{timestamp()} Setup complete! You can now use the script without storing passwords in plaintext.")
            else:
                debug_print(f"{timestamp()} ERROR: Setup failed. Please try again.")
            return
    
    # Handle context menu installation
    if args.install_context_menu:
        if create_windows_context_menu():
            debug_print(f"{timestamp()} Context Menu: Installed successfully")
        else:
            debug_print(f"{timestamp()} Context Menu: ERROR: Failed to install context menu.")
        return
    
    # Handle context menu removal
    if args.remove_context_menu:
        if remove_windows_context_menu():
            debug_print(f"{timestamp()} Context Menu: Removed successfully")
        else:
            debug_print(f"{timestamp()} Context Menu: Failed to removeFailed to remove context menu.")
        return
    
    # Handle gallery visibility changes
    if len(args.folder_paths) == 1 and args.folder_paths[0].startswith('--'):
        # This is a gallery ID for visibility change
        gallery_id = args.folder_paths[0][2:]  # Remove -- prefix
        
        uploader = ImxToUploader()
        
        if args.public:
            if uploader.set_gallery_visibility(gallery_id, 1):
                debug_print(f"{timestamp()} Gallery {gallery_id} set to public")
            else:
                debug_print(f"{timestamp()} ERROR: Failed to set gallery {gallery_id} to public")
        elif args.private:
            if uploader.set_gallery_visibility(gallery_id, 0):
                debug_print(f"{timestamp()} Gallery {gallery_id} set to private")
            else:
                debug_print(f"{timestamp()} ERROR: Failed to set gallery {gallery_id} to private")
        else:
            debug_print("{timestamp()} WARNING: Please specify --public or --private")
        return
    
    # Handle unnamed gallery renaming
    if args.rename_unnamed:
        unnamed_galleries = get_unnamed_galleries()

        if not unnamed_galleries:
            #log(f" No unnamed galleries found to rename")
            return

        debug_print(f"{timestamp()} Found {len(unnamed_galleries)} unnamed galleries to rename:")
        for gallery_id, intended_name in unnamed_galleries.items():
            debug_print(f"   {gallery_id} -> '{intended_name}'")

        # Use RenameWorker for all web-based rename operations
        try:
            from src.processing.rename_worker import RenameWorker
            rename_worker = RenameWorker()

            # Wait for initial login (RenameWorker logs in automatically on init)
            import time
            if not rename_worker.login_complete.wait(timeout=30):
                debug_print(f"RenameWorker: Login timeout")
                debug_print(f" To rename galleries manually:")
                debug_print(f" 1. Log in to https://imx.to in your browser")
                debug_print(f" 2. Navigate to each gallery and rename it manually")
                debug_print(f" Gallery IDs to rename: {', '.join(unnamed_galleries.keys())}")
                return 1

            if not rename_worker.login_successful:
                debug_print(f"RenameWorker: Login failed")
                debug_print(f" DDoS-Guard protection may be blocking automated login.")
                debug_print(f" To rename galleries manually:")
                debug_print(f" 1. Log in to https://imx.to in your browser")
                debug_print(f" 2. Navigate to each gallery and rename it manually")
                debug_print(f" 3. Or export cookies from browser and place in cookies.txt file")
                debug_print(f" Gallery IDs to rename: {', '.join(unnamed_galleries.keys())}")
                return 1

            # Queue all renames
            for gallery_id, intended_name in unnamed_galleries.items():
                rename_worker.queue_rename(gallery_id, intended_name)

            # Wait for all renames to complete
            debug_print(f"{timestamp()} Processing {len(unnamed_galleries)} rename requests...")
            while rename_worker.queue_size() > 0:
                time.sleep(0.1)

            # Count successes by checking which galleries are still in unnamed list
            remaining_unnamed = get_unnamed_galleries()
            success_count = len(unnamed_galleries) - len(remaining_unnamed)

            debug_print(f"{timestamp()} Successfully renamed {success_count}/{len(unnamed_galleries)} galleries")

            # Cleanup
            rename_worker.stop()

            return 0 if success_count == len(unnamed_galleries) else 1

        except Exception as e:
            debug_print(f"{timestamp()} Failed to initialize RenameWorker: {e}")
            return 1
    
    # Check if folder paths are provided (required for upload)
    if not args.folder_paths:
        parser.print_help()
        return 0
    
    # Expand wildcards in folder paths
    expanded_paths = []
    for path in args.folder_paths:
        if '*' in path or '?' in path:
            # Expand wildcards
            expanded = glob.glob(path)
            if not expanded:
                debug_print(f"{timestamp()} Warning: No folders found matching pattern: {path}")
            expanded_paths.extend(expanded)
        else:
            expanded_paths.append(path)
    
    if not expanded_paths:
        debug_print(f"{timestamp()} No valid folders found to upload.")
        return 1  # No valid folders
    
    # Determine public gallery setting
    # public_gallery is deprecated but kept for compatibility
    # All galleries are public now
    
    try:
        uploader = ImxToUploader()
        all_results = []

        # ImxToUploader is now API-only (no web login needed)
        # RenameWorker handles all web operations and logs in automatically

        # Use shared UploadEngine for consistent behavior
        from src.core.engine import UploadEngine
        
        # Create RenameWorker for background renaming
        rename_worker = None
        try:
            from src.processing.rename_worker import RenameWorker
            rename_worker = RenameWorker()
            debug_print(f"{timestamp()} Rename Worker: Background worker initialized")
        except Exception as e:
            debug_print(f"{timestamp()} Rename Worker: Error trying to initialize RenameWorker: {e}")
            
        engine = UploadEngine(uploader, rename_worker)

        # Process multiple galleries
        for folder_path in expanded_paths:
            gallery_name = args.name if args.name else None

            try:
                debug_print(f"{timestamp()} Starting upload: {os.path.basename(folder_path)}")
                results = engine.run(
                    folder_path=folder_path,
                    gallery_name=gallery_name,
                    thumbnail_size=args.size,
                    thumbnail_format=args.format,
                    max_retries=args.max_retries,
                    parallel_batch_size=args.parallel,
                    template_name=args.template or "default",
                )

                # Save artifacts through shared helper
                try:
                    save_gallery_artifacts(
                        folder_path=folder_path,
                        results=results,
                        template_name=args.template or "default",
                    )
                except Exception as e:
                    debug_print(f"{timestamp()} WARNING: Artifact save error: {e}")

                all_results.append(results)

            except KeyboardInterrupt:
                debug_print("{timestamp()} Upload interrupted by user")
                # Cleanup RenameWorker on interrupt
                if rename_worker:
                    rename_worker.stop()
                    debug_print(f"{timestamp()} Background RenameWorker stopped")
                break
            except Exception as e:
                debug_print(f"{timestamp()} Error uploading {folder_path}: {str(e)}")
                continue
        
        # Display summary for all galleries
        if all_results:
            print("\n" + "="*60)
            print("UPLOAD SUMMARY")
            print("="*60)
            
            total_images = sum(len(r['images']) for r in all_results)
            total_time = sum(r['upload_time'] for r in all_results)
            total_size = sum(r['total_size'] for r in all_results)
            total_uploaded = sum(r['uploaded_size'] for r in all_results)
            
            print(f"Total galleries: {len(all_results)}")
            print(f"Total images: {total_images}")
            print(f"Total time: {total_time:.1f} seconds")
            try:
                total_size_str = format_binary_size(total_size, precision=1)
            except Exception:
                total_size_str = f"{int(total_size)} B"
            print(f"Total size: {total_size_str}")
            if total_time > 0:
                try:
                    avg_kib_s = (total_uploaded / total_time) / 1024.0
                    avg_speed_str = format_binary_rate(avg_kib_s, precision=1)
                except Exception:
                    avg_speed_str = f"{(total_uploaded / total_time) / 1024.0:.1f} KiB/s"
                print(f"Average speed: {avg_speed_str}")
            else:
                print("Average speed: 0 KiB/s")
            
            for i, results in enumerate(all_results, 1):
                total_attempted = results['successful_count'] + results['failed_count']
                print(f"\nGallery {i}: {results['gallery_name']}")
                print(f"  URL: {results['gallery_url']}")
                print(f"  Images: {results['successful_count']}/{total_attempted}")
                print(f"  Time: {results['upload_time']:.1f}s")
                try:
                    size_str = format_binary_size(results['uploaded_size'], precision=1)
                except Exception:
                    size_str = f"{int(results['uploaded_size'])} B"
                print(f"  Size: {size_str}")
                try:
                    kib_s = (results['transfer_speed'] or 0) / 1024.0
                    speed_str = format_binary_rate(kib_s, precision=1)
                except Exception:
                    speed_str = f"{((results['transfer_speed'] or 0) / 1024.0):.1f} KiB/s"
                print(f"  Speed: {speed_str}")
            
            # Cleanup RenameWorker
            if rename_worker:
                rename_worker.stop()
                debug_print(f"{timestamp()} Rename Worker: Background worker stopped")
                
            return 0  # Success
        else:
            # Cleanup RenameWorker
            if rename_worker:
                rename_worker.stop()
                debug_print(f"{timestamp()} Background RenameWorker stopped")
                
            debug_print("{timestamp()} No galleries were successfully uploaded.")
            return 1  # No galleries uploaded
            
    except Exception as e:
        # Cleanup RenameWorker on exception
        try:
            if 'rename_worker' in locals() and rename_worker:
                rename_worker.stop()
                debug_print(f"{timestamp()} ERROR: Rename Worker: Error: Background worker stopped on exception: {e}")
        except Exception:
            pass  # Ignore cleanup errors
        debug_print(f"{timestamp()} ERROR: Rename Worker: Error: {str(e)}")
        return 1  # Error occurred

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("{timestamp()} KeyboardInterrupt: Exiting gracefully...", level="debug", category="ui")
        sys.exit(0)
    except SystemExit:
        # Handle argparse errors gracefully
        pass
    except Exception as e:
        # Log crash to file when running with --noconsole (so we can debug it)
        try:
            import traceback
            with open('imxup_crash.log', 'w') as f:
                f.write(f"ImxUp crashed:\n")
                f.write(f"{traceback.format_exc()}\n")
        except (OSError, IOError):
            pass
        # Also try to log it normally
        try:
            log(f"CRITICAL: Fatal Error: {e}", level="critical", category="ui")
        except Exception:
            pass
        sys.exit(1)
