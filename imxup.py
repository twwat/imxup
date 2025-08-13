#!/usr/bin/env python3
"""
imx.to gallery uploader
Upload image folders to imx.to as galleries
"""

import os
import requests
import json
from dotenv import load_dotenv
import argparse
import sys
from pathlib import Path
#import re
#import asyncio

from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import concurrent.futures
import time
from tqdm import tqdm
import configparser
import hashlib
import getpass
#import subprocess
#import tempfile
import json
#import zipfile
#import urllib.request
import platform
import sqlite3
#import shutil
import glob
import winreg

# Load environment variables
load_dotenv()

# Application version
__version__ = "0.2.3"

def timestamp():
    """Return current timestamp for logging"""
    return datetime.now().strftime("%H:%M:%S")

def format_binary_size(num_bytes: int | float, precision: int = 1) -> str:
    """Format a byte count using binary prefixes (B, KiB, MiB, GiB, TiB).

    - Uses 1024 as the step size
    - Shows no decimals for bytes; otherwise uses the given precision
    """
    try:
        value = float(num_bytes or 0)
    except Exception:
        value = 0.0
    units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]
    unit_index = 0
    while value >= 1024.0 and unit_index < len(units) - 1:
        value /= 1024.0
        unit_index += 1
    if units[unit_index] == "B":
        return f"{int(value)} B"
    return f"{value:.{precision}f} {units[unit_index]}"

def format_binary_rate(kib_per_s: float | int, precision: int = 1) -> str:
    """Format a transfer rate given in KiB/s using binary prefixes.

    - Input is expected to be in KiB/s
    - Scales to MiB/s, GiB/s, etc. as appropriate
    """
    try:
        rate = float(kib_per_s or 0)
    except Exception:
        rate = 0.0
    units = ["KiB/s", "MiB/s", "GiB/s", "TiB/s"]
    unit_index = 0
    while rate >= 1024.0 and unit_index < len(units) - 1:
        rate /= 1024.0
        unit_index += 1
    return f"{rate:.{precision}f} {units[unit_index]}"

def get_config_path() -> str:
    """Return the canonical path to the application's config file (~/.imxup/imxup.ini)."""
    base_dir = os.path.join(os.path.expanduser("~"), ".imxup")
    os.makedirs(base_dir, exist_ok=True)
    return os.path.join(base_dir, "imxup.ini")

def get_legacy_config_path() -> str:
    """Return legacy config path (~/.imxup.ini)."""
    return os.path.join(os.path.expanduser("~"), ".imxup.ini")

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

def migrate_legacy_storage() -> None:
    """Migrate legacy folders/files to new structure.

    - Move templates from ~/imxup_galleries files starting with '.template' to ~/.imxup/templates
    - Move remaining files from ~/imxup_galleries to ~/.imxup/galleries with conflict-safe suffixing
    - Move ~/.imxup.ini to ~/.imxup/imxup.ini (backup new if both exist)
    - Remove legacy ~/imxup_galleries when empty
    """
    try:
        home_dir = os.path.expanduser("~")
        legacy_dir = os.path.join(home_dir, "imxup_galleries")
        new_base = os.path.join(home_dir, ".imxup")
        new_galleries = os.path.join(new_base, "galleries")
        new_templates = os.path.join(new_base, "templates")

        # Ensure new directories exist
        os.makedirs(new_galleries, exist_ok=True)
        os.makedirs(new_templates, exist_ok=True)

        # 1) Migrate legacy folder contents (if present)
        if os.path.isdir(legacy_dir):
            # Walk recursively and move files only (flatten into destination roots)
            for root, _dirs, files in os.walk(legacy_dir):
                for filename in files:
                    src_path = os.path.join(root, filename)
                    if filename.startswith(".template"):
                        dest_dir = new_templates
                    else:
                        dest_dir = new_galleries
                    dest_path = _unique_destination_path(dest_dir, filename)
                    try:
                        os.replace(src_path, dest_path)
                        print(f"{timestamp()} Migrated '{src_path}' -> '{dest_path}'")
                    except Exception as e:
                        print(f"{timestamp()} Warning: failed to migrate '{src_path}': {e}")

            # Attempt to remove empty directories bottom-up and finally legacy root if empty
            for root, dirs, files in os.walk(legacy_dir, topdown=False):
                try:
                    if not dirs and not files:
                        os.rmdir(root)
                except Exception:
                    pass
            # Remove legacy root if now empty
            try:
                if os.path.isdir(legacy_dir) and not os.listdir(legacy_dir):
                    os.rmdir(legacy_dir)
                    print(f"{timestamp()} Removed empty legacy folder '{legacy_dir}'")
            except Exception:
                pass

        # 2) Migrate config file from legacy path to new path
        legacy_cfg = get_legacy_config_path()
        new_cfg = get_config_path()

        if os.path.exists(legacy_cfg):
            # If new already exists, back it up to imxup.ini.bak (with numeric suffix if needed)
            if os.path.exists(new_cfg):
                base_bak = new_cfg + ".bak"
                bak_path = base_bak
                idx = 1
                while os.path.exists(bak_path):
                    bak_path = f"{base_bak}.{idx}"
                    idx += 1
                try:
                    os.replace(new_cfg, bak_path)
                    print(f"{timestamp()} Existing new config found. Backed up to '{bak_path}'")
                except Exception as e:
                    print(f"{timestamp()} Warning: failed to backup existing config '{new_cfg}': {e}")
            # Move legacy into place
            try:
                os.replace(legacy_cfg, new_cfg)
                print(f"{timestamp()} Migrated config to '{new_cfg}'")
            except Exception as e:
                print(f"{timestamp()} Warning: failed to migrate legacy config '{legacy_cfg}': {e}")
    except Exception as e:
        print(f"{timestamp()} Migration error: {e}")

# Perform migration at import time so all subsequent code uses the new locations
migrate_legacy_storage()

def create_windows_context_menu():
    """Create Windows context menu integration"""
    try:
        # Resolve Python executables and scripts
        script_dir = os.path.dirname(os.path.abspath(__file__))
        cli_script = os.path.join(script_dir, 'imxup.py')
        gui_script = os.path.join(script_dir, 'launch_gui.py')
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
        
        # Create registry entries for command line upload (background right-click)
        key_path_bg = r"Directory\Background\shell\UploadToImx"
        key_bg = winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, key_path_bg)
        winreg.SetValue(key_bg, "", winreg.REG_SZ, "Upload to imx.to")
        command_key_bg = winreg.CreateKey(key_bg, "command")
        winreg.SetValue(command_key_bg, "", winreg.REG_SZ, f'"{python_cli_exe}" "{cli_script}" "%V"')
        winreg.CloseKey(command_key_bg)
        winreg.CloseKey(key_bg)

        # Create registry entries for GUI mode (background right-click)
        gui_key_path_bg = r"Directory\Background\shell\UploadToImxGUI"
        gui_key_bg = winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, gui_key_path_bg)
        winreg.SetValue(gui_key_bg, "", winreg.REG_SZ, "Upload to imx.to (GUI)")
        gui_command_key_bg = winreg.CreateKey(gui_key_bg, "command")
        winreg.SetValue(gui_command_key_bg, "", winreg.REG_SZ, f'"{pythonw_exe}" "{gui_script}" "%V"')
        winreg.CloseKey(gui_command_key_bg)
        winreg.CloseKey(gui_key_bg)

        # Create entries for right-click on folders (selected items)
        key_path_dir = r"Directory\shell\UploadToImx"
        key_dir = winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, key_path_dir)
        winreg.SetValue(key_dir, "", winreg.REG_SZ, "Upload to imx.to")
        # Enable multi-select model (Explorer passes all selections to %V)
        try:
            winreg.SetValueEx(key_dir, "MultiSelectModel", 0, winreg.REG_SZ, "Document")
        except Exception:
            pass
        command_key_dir = winreg.CreateKey(key_dir, "command")
        winreg.SetValue(command_key_dir, "", winreg.REG_SZ, f'"{python_cli_exe}" "{cli_script}" "%V"')
        winreg.CloseKey(command_key_dir)
        winreg.CloseKey(key_dir)

        gui_key_path_dir = r"Directory\shell\UploadToImxGUI"
        gui_key_dir = winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, gui_key_path_dir)
        winreg.SetValue(gui_key_dir, "", winreg.REG_SZ, "Upload to imx.to (GUI)")
        try:
            winreg.SetValueEx(gui_key_dir, "MultiSelectModel", 0, winreg.REG_SZ, "Document")
        except Exception:
            pass
        gui_command_key_dir = winreg.CreateKey(gui_key_dir, "command")
        winreg.SetValue(gui_command_key_dir, "", winreg.REG_SZ, f'"{pythonw_exe}" "{gui_script}" "%V"')
        winreg.CloseKey(gui_command_key_dir)
        winreg.CloseKey(gui_key_dir)
        
        print(f"Context menu created successfully!")
        print(f"Right-click on any folder (or background) and select:")
        print(f"  - 'Upload to imx.to' for command line mode")
        print(f"  - 'Upload to imx.to (GUI)' for graphical interface")
        return True
        
    except Exception as e:
        print(f"Error creating context menu: {e}")
        return False

def remove_windows_context_menu():
    """Remove Windows context menu integration"""
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
        
        print("Context menu removed successfully!")
        return True
    except Exception as e:
        print(f"Error removing context menu: {e}")
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



def get_encryption_key():
    """Generate encryption key from system info"""
    # Use username and hostname to create a consistent key
    system_info = f"{os.getenv('USERNAME', '')}{platform.node()}"
    key = hashlib.sha256(system_info.encode()).digest()
    return base64.urlsafe_b64encode(key)

def encrypt_password(password):
    """Encrypt password with system-derived key"""
    key = get_encryption_key()
    f = Fernet(key)
    return f.encrypt(password.encode()).decode()

def decrypt_password(encrypted_password):
    """Decrypt password with system-derived key"""
    try:
        key = get_encryption_key()
        f = Fernet(key)
        return f.decrypt(encrypted_password.encode()).decode()
    except:
        return None

def load_user_defaults():
    """Load user defaults from config file"""
    config = configparser.ConfigParser()
    config_file = get_config_path()
    
    if os.path.exists(config_file):
        config.read(config_file)
        defaults = {}
        
        if 'DEFAULTS' in config:
            defaults['thumbnail_size'] = config.getint('DEFAULTS', 'thumbnail_size', fallback=3)
            defaults['thumbnail_format'] = config.getint('DEFAULTS', 'thumbnail_format', fallback=2)
            defaults['max_retries'] = config.getint('DEFAULTS', 'max_retries', fallback=3)
            defaults['parallel_batch_size'] = config.getint('DEFAULTS', 'parallel_batch_size', fallback=4)
            defaults['public_gallery'] = config.getint('DEFAULTS', 'public_gallery', fallback=1)
            defaults['template_name'] = config.get('DEFAULTS', 'template_name', fallback='default')
            defaults['confirm_delete'] = config.getboolean('DEFAULTS', 'confirm_delete', fallback=True)
            # Auto-rename unnamed galleries after successful login (GUI feature)
            defaults['auto_rename'] = config.getboolean('DEFAULTS', 'auto_rename', fallback=True)
            # Storage locations for artifacts
            defaults['store_in_uploaded'] = config.getboolean('DEFAULTS', 'store_in_uploaded', fallback=True)
            defaults['store_in_central'] = config.getboolean('DEFAULTS', 'store_in_central', fallback=True)
            # Optional central store path (falls back to default if not set)
            try:
                defaults['central_store_path'] = config.get('DEFAULTS', 'central_store_path', fallback=get_default_central_store_base_path())
            except Exception:
                # If any parsing issue occurs, use default base path
                defaults['central_store_path'] = get_default_central_store_base_path()
        
        return defaults
    return {}



def setup_secure_password():
    """Interactive setup for secure password storage"""
    print("Setting up secure password storage for imx.to")
    print("This will store a hashed version of your password in ~/.imxup/imxup.ini")
    print()
    
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
        print("[ERROR] Failed to save credentials.")
        return False

def _save_credentials(username, password):
    """Save credentials to config file"""
    config = configparser.ConfigParser()
    config_file = get_config_path()
    
    if os.path.exists(config_file):
        config.read(config_file)
    
    if 'CREDENTIALS' not in config:
        config['CREDENTIALS'] = {}
    
    config['CREDENTIALS']['username'] = username
    config['CREDENTIALS']['password'] = encrypt_password(password)
    
    with open(config_file, 'w') as f:
        config.write(f)
    
    print(f"[OK] Credentials saved to {config_file}")
    return True

def save_unnamed_gallery(gallery_id, intended_name):
    """Save unnamed gallery for later renaming"""
    config = configparser.ConfigParser()
    config_file = get_config_path()
    
    if os.path.exists(config_file):
        config.read(config_file)
    
    if 'UNNAMED_GALLERIES' not in config:
        config['UNNAMED_GALLERIES'] = {}
    
    config['UNNAMED_GALLERIES'][gallery_id] = intended_name
    
    with open(config_file, 'w') as f:
        config.write(f)
    
    print(f"Saved unnamed gallery {gallery_id} for later renaming to '{intended_name}'")

def get_default_central_store_base_path():
    """Return the default central store BASE path (parent of galleries/templates)."""
    return os.path.join(os.path.expanduser("~"), ".imxup")


def get_central_store_base_path():
    """Get the configured central store BASE path (parent of galleries/templates)."""
    try:
        import configparser
        config = configparser.ConfigParser()
        config_file = get_config_path()
        base_path = None
        if os.path.exists(config_file):
            config.read(config_file)
            if 'DEFAULTS' in config and 'central_store_path' in config['DEFAULTS']:
                base_path = config.get('DEFAULTS', 'central_store_path', fallback=None)
        if not base_path:
            base_path = get_default_central_store_base_path()
    except Exception:
        base_path = get_default_central_store_base_path()
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
    Returns (safe_gallery_name, json_filename, bbcode_filename).
    """
    safe_gallery_name = sanitize_gallery_name(gallery_name)
    json_filename = f"{safe_gallery_name}_{gallery_id}.json"
    bbcode_filename = f"{safe_gallery_name}_{gallery_id}_bbcode.txt"
    return safe_gallery_name, json_filename, bbcode_filename

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
    """Get list of unnamed galleries"""
    config = configparser.ConfigParser()
    config_file = get_config_path()
    
    if os.path.exists(config_file):
        config.read(config_file)
        if 'UNNAMED_GALLERIES' in config:
            return dict(config['UNNAMED_GALLERIES'])
    return {}

def rename_all_unnamed_with_session(uploader: 'ImxToUploader') -> int:
    """Rename all unnamed galleries using an already logged-in uploader session.
    Returns the number of successfully renamed galleries.
    """
    unnamed_galleries = get_unnamed_galleries()
    if not unnamed_galleries:
        return 0
    success_count = 0
    for gallery_id, intended_name in unnamed_galleries.items():
        if uploader.rename_gallery_with_session(gallery_id, intended_name):
            # Inform GUI (if present) about the rename
            try:
                if hasattr(uploader, 'worker_thread') and uploader.worker_thread is not None:
                    uploader.worker_thread.log_message.emit(
                        f"{timestamp()} Successfully renamed gallery '{gallery_id}' to '{intended_name}'"
                    )
            except Exception:
                pass
            remove_unnamed_gallery(gallery_id)
            success_count += 1
    return success_count

def remove_unnamed_gallery(gallery_id):
    """Remove gallery from unnamed list after successful renaming"""
    config = configparser.ConfigParser()
    config_file = get_config_path()
    
    if os.path.exists(config_file):
        config.read(config_file)
        
        if 'UNNAMED_GALLERIES' in config and gallery_id in config['UNNAMED_GALLERIES']:
            del config['UNNAMED_GALLERIES'][gallery_id]
            
            with open(config_file, 'w') as f:
                config.write(f)
            
            print(f"{timestamp()} Removed {gallery_id} from unnamed galleries list")

from imxup_cookies import get_firefox_cookies, load_cookies_from_file

def get_template_path():
    """Get the template directory path (~/.imxup/templates)."""
    template_path = os.path.join(os.path.expanduser("~"), ".imxup", "templates")
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
    
    # Load custom templates
    if os.path.exists(template_path):
        for filename in os.listdir(template_path):
            if filename.startswith(".template"):
                template_name = filename[10:]  # Remove ".template " prefix
                # Remove .txt extension if present
                if template_name.endswith('.txt'):
                    template_name = template_name[:-4]
                if template_name:  # Skip empty names
                    template_file = os.path.join(template_path, filename)
                    try:
                        with open(template_file, 'r', encoding='utf-8') as f:
                            templates[template_name] = f.read()
                    except Exception as e:
                        print(f"{timestamp()} Warning: Could not load template '{template_name}': {e}")
    
    return templates

def apply_template(template_content, data):
    """Apply a template with data replacement"""
    result = template_content
    
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
        '#allImages#': data.get('all_images', '')
    }
    
    for placeholder, value in replacements.items():
        result = result.replace(placeholder, value)
    
    return result

def generate_bbcode_from_template(template_name, data):
    """Generate bbcode content using a specific template"""
    templates = load_templates()
    
    if template_name not in templates:
        print(f"{timestamp()} Warning: Template '{template_name}' not found, using default")
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
) -> dict:
    """Save BBCode and JSON artifacts for a completed gallery.

    Parameters:
    - folder_path: path to the source image folder
    - results: the results dict returned by upload_folder (must contain keys used below)
    - template_name: which template to use for full bbcode generation
    - store_in_uploaded/store_in_central: overrides for storage locations. When None, read defaults

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
            'public_gallery': results.get('public_gallery'),
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

class ImxToUploader:
    def _get_credentials(self):
        """Get credentials from stored config (username/password or API key)"""
        config = configparser.ConfigParser()
        config_file = get_config_path()
        
        if os.path.exists(config_file):
            config.read(config_file)
            if 'CREDENTIALS' in config:
                auth_type = config['CREDENTIALS'].get('auth_type', 'username_password')
                
                if auth_type == 'username_password':
                    username = config['CREDENTIALS'].get('username')
                    encrypted_password = config['CREDENTIALS'].get('password', '')
                    
                    if username and encrypted_password:
                        password = decrypt_password(encrypted_password)
                        if password:
                            return username, password, None
                
                elif auth_type == 'api_key':
                    encrypted_api_key = config['CREDENTIALS'].get('api_key', '')
                    
                    if encrypted_api_key:
                        api_key = decrypt_password(encrypted_api_key)
                        if api_key:
                            return None, None, api_key
        
        return None, None, None
    
    def __init__(self):
        # Get credentials from stored config
        self.username, self.password, self.api_key = self._get_credentials()
        
        # Fallback to environment variable for API key if not in config
        if not self.api_key:
            self.api_key = os.getenv('IMX_API')
        
        # Check if we have either username/password or API key
        has_credentials = (self.username and self.password) or self.api_key
        
        if not has_credentials:
            print(f"{timestamp()} Failed to get credentials. Please set up credentials in the GUI or run --setup-secure first.")
            sys.exit(1)
        
        self.base_url = "https://api.imx.to/v1"
        self.web_url = "https://imx.to"
        self.upload_url = f"{self.base_url}/upload.php"
        
        # Set headers based on authentication method
        if self.api_key:
            self.headers = {
                "X-API-Key": self.api_key
            }
        else:
            self.headers = {}
        
        # Session for web interface
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:141.0) Gecko/20100101 Firefox/141.0',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US',
            'Accept-Encoding': 'gzip, deflate, br, zstd',
            'DNT': '1'
        })
    
    def login(self):
        """Login to imx.to web interface"""
        if not self.username or not self.password:
            # Attempt cookie-based session login even without stored username/password if enabled
            use_cookies = True
            try:
                cfg = configparser.ConfigParser()
                cfg_path = get_config_path()
                if os.path.exists(cfg_path):
                    cfg.read(cfg_path)
                    if 'CREDENTIALS' in cfg:
                        use_cookies = str(cfg['CREDENTIALS'].get('cookies_enabled', 'true')).lower() != 'false'
            except Exception:
                use_cookies = True
            if use_cookies:
                try:
                    print(f"{timestamp()} Attempting to use cookies to bypass DDoS-Guard...")
                    firefox_cookies = get_firefox_cookies("imx.to")
                    file_cookies = load_cookies_from_file("cookies.txt")
                    all_cookies = {}
                    if firefox_cookies:
                        print(f"{timestamp()} Found {len(firefox_cookies)} Firefox cookies for imx.to")
                        all_cookies.update(firefox_cookies)
                    if file_cookies:
                        print(f"{timestamp()} Found {len(file_cookies)} cookies from cookies.txt")
                        all_cookies.update(file_cookies)
                    if all_cookies:
                        for name, cookie_data in all_cookies.items():
                            try:
                                self.session.cookies.set(name, cookie_data['value'], domain=cookie_data['domain'], path=cookie_data['path'])
                            except Exception:
                                pass
                        test_response = self.session.get(f"{self.web_url}/user/gallery/manage")
                        if 'login' not in test_response.url and 'DDoS-Guard' not in test_response.text:
                            print(f"{timestamp()} Successfully authenticated using cookies (no password login)")
                            try:
                                self.last_login_method = "cookies"
                            except Exception:
                                pass
                            return True
                except Exception:
                    # Ignore cookie errors and fall back
                    pass
            if self.api_key:
                print(f"{timestamp()} Using API key authentication - gallery naming may be limited")
                try:
                    self.last_login_method = "api_key"
                except Exception:
                    pass
                return True
            else:
                print(f"{timestamp()} Warning: No stored credentials, gallery naming disabled")
                try:
                    self.last_login_method = "none"
                except Exception:
                    pass
                return False
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    print(f"{timestamp()} Retry attempt {attempt + 1}/{max_retries}")
                    time.sleep(2 ** attempt)  # Exponential backoff
                
                # Try to get cookies first (browser + file) if enabled
                use_cookies = True
                try:
                    cfg = configparser.ConfigParser()
                    cfg_path = get_config_path()
                    if os.path.exists(cfg_path):
                        cfg.read(cfg_path)
                        if 'CREDENTIALS' in cfg:
                            use_cookies = str(cfg['CREDENTIALS'].get('cookies_enabled', 'true')).lower() != 'false'
                except Exception:
                    use_cookies = True
                if use_cookies:
                    print(f"{timestamp()} Attempting to use cookies to bypass DDoS-Guard...")
                    firefox_cookies = get_firefox_cookies("imx.to")
                    file_cookies = load_cookies_from_file("cookies.txt")
                    all_cookies = {}
                    if firefox_cookies:
                        print(f"{timestamp()} Found {len(firefox_cookies)} Firefox cookies for imx.to")
                        all_cookies.update(firefox_cookies)
                    if file_cookies:
                        print(f"{timestamp()} Found {len(file_cookies)} cookies from cookies.txt")
                        all_cookies.update(file_cookies)
                    if all_cookies:
                        # Add cookies to session
                        for name, cookie_data in all_cookies.items():
                            try:
                                self.session.cookies.set(name, cookie_data['value'], domain=cookie_data['domain'], path=cookie_data['path'])
                            except Exception:
                                # Best effort
                                pass
                        # Test if we're already logged in with cookies
                        test_response = self.session.get(f"{self.web_url}/user/gallery/manage")
                        if 'login' not in test_response.url and 'DDoS-Guard' not in test_response.text:
                            print(f"{timestamp()} Successfully authenticated using cookies (no password login)")
                            try:
                                self.last_login_method = "cookies"
                            except Exception:
                                pass
                            return True
                else:
                    print(f"{timestamp()} Skipping Firefox cookies per settings")
                
                # Fall back to regular login
                print(f"{timestamp()} Attempting login to {self.web_url}/login.php")
                login_page = self.session.get(f"{self.web_url}/login.php")
                
                # Submit login form
                login_data = {
                    'usr_email': self.username,
                    'pwd': self.password,
                    'remember': '1',
                    'doLogin': 'Login'
                }
                
                response = self.session.post(f"{self.web_url}/login.php", data=login_data)
                
                # Check if we hit DDoS-Guard
                if 'DDoS-Guard' in response.text or 'ddos-guard' in response.text:
                    print(f"{timestamp()} DDoS-Guard detected, trying browser cookies...")
                    firefox_cookies = get_firefox_cookies("imx.to") if use_cookies else {}
                    file_cookies = load_cookies_from_file("cookies.txt") if use_cookies else {}
                    all_cookies = {**firefox_cookies, **file_cookies} if use_cookies else {}
                    
                    if all_cookies:
                        print(f"{timestamp()} Retrying with browser cookies...")
                        # Clear session and try with cookies
                        self.session = requests.Session()
                        self.session.headers.update({
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:141.0) Gecko/20100101 Firefox/141.0',
                            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                            'Accept-Language': 'en-US',
                            'Accept-Encoding': 'gzip, deflate, br, zstd',
                            'DNT': '1'
                        })
                        
                        for name, cookie_data in all_cookies.items():
                            self.session.cookies.set(name, cookie_data['value'], 
                                                  domain=cookie_data['domain'], 
                                                  path=cookie_data['path'])
                        
                        # Try login again with cookies
                        response = self.session.post(f"{self.web_url}/login.php", data=login_data)
                        
                        # If we still hit DDoS-Guard but have cookies, test if we can access user pages
                        if 'DDoS-Guard' in response.text or 'ddos-guard' in response.text:
                            print(f"{timestamp()} DDoS-Guard detected but cookies loaded - testing access to user pages...")
                            # Test if we can access a user page
                            test_response = self.session.get(f"{self.web_url}/user/gallery/manage")
                            if test_response.status_code == 200 and 'login' not in test_response.url:
                                print(f"{timestamp()} Successfully accessed user pages with cookies")
                                try:
                                    self.last_login_method = "cookies"
                                except Exception:
                                    pass
                                return True
                            else:
                                print(f"{timestamp()} Cannot access user pages despite cookies - login may have failed")
                                if attempt < max_retries - 1:
                                    continue
                                else:
                                    return False
                    
                    if 'DDoS-Guard' in response.text or 'ddos-guard' in response.text:
                        print(f"{timestamp()} DDoS-Guard still detected, falling back to API-only upload...")
                        if attempt < max_retries - 1:
                            continue
                        else:
                            return False
                
                # Check if login was successful
                if 'user' in response.url or 'dashboard' in response.url or 'gallery' in response.url:
                    print(f"{timestamp()} Successfully logged in with username/password")
                    try:
                        self.last_login_method = "credentials"
                    except Exception:
                        pass
                    return True
                else:
                    print(f"{timestamp()} Login failed - check username/password")
                    if attempt < max_retries - 1:
                        continue
                    else:
                        return False
                    
            except Exception as e:
                print(f"{timestamp()} Login error: {str(e)}")
                if attempt < max_retries - 1:
                    continue
                else:
                    return False
        
        return False
    
    def create_gallery_with_name(self, gallery_name, public_gallery=1, skip_login=False):
        """Create a gallery with a specific name using web interface"""
        if not skip_login and not self.login():
            print(f"{timestamp()} Login failed - cannot create gallery with name")
            return None
        
        try:
            # Get the add gallery page
            add_page = self.session.get(f"{self.web_url}/user/gallery/add")
            
            # Submit gallery creation form
            gallery_data = {
                'gallery_name': gallery_name,
                'public_gallery': str(public_gallery),
                'submit_new_gallery': 'Add'
            }
            
            response = self.session.post(f"{self.web_url}/user/gallery/add", data=gallery_data)
            
            # Extract gallery ID from redirect URL
            if 'gallery/manage?id=' in response.url:
                gallery_id = response.url.split('id=')[1]
                visibility = "public" if public_gallery else "private"
                print(f"{timestamp()} Created {visibility} gallery '{gallery_name}' with ID: {gallery_id}")
                return gallery_id
            else:
                print(f"{timestamp()} Failed to create gallery")
                print(f"{timestamp()} Response URL: {response.url}")
                print(f"{timestamp()} Response status: {response.status_code}")
                if 'DDoS-Guard' in response.text:
                    print(f"{timestamp()} DDoS-Guard detected in gallery creation")
                return None
                
        except Exception as e:
            print(f"{timestamp()} Error creating gallery: {str(e)}")
            return None
    
    # REMOVED: _upload_without_named_gallery — unified into upload_folder
    
    def rename_gallery(self, gallery_id, new_name):
        """Rename an existing gallery"""
        if not self.login():
            return False
        
        try:
            # Get the edit gallery page
            edit_page = self.session.get(f"{self.web_url}/user/gallery/edit?id={gallery_id}")
            
            # Submit gallery rename form
            rename_data = {
                'gallery_name': new_name,
                'submit_new_gallery': 'Rename Gallery',
                'public_gallery': '1'
            }
            
            response = self.session.post(f"{self.web_url}/user/gallery/edit?id={gallery_id}", data=rename_data)
            
            if response.status_code == 200:
                print(f"{timestamp()} Successfully renamed gallery to '{new_name}'")
                return True
            else:
                print(f"{timestamp()} Failed to rename gallery")
                return False
                
        except Exception as e:
            print(f"{timestamp()} Error renaming gallery: {str(e)}")
            return False
    
    def rename_gallery_with_session(self, gallery_id, new_name):
        """Rename an existing gallery using existing session (no login call)"""
        try:
            # Sanitize the gallery name
            original_name = new_name
            new_name = sanitize_gallery_name(new_name)
            if original_name != new_name:
                print(f"{timestamp()} Sanitized gallery name: '{original_name}' -> '{new_name}'")
            
            # Get the edit gallery page
            edit_page = self.session.get(f"{self.web_url}/user/gallery/edit?id={gallery_id}")
            
            # Check if we can access the edit page
            if edit_page.status_code != 200:
                print(f"{timestamp()} Failed to access edit page for gallery {gallery_id} (status: {edit_page.status_code})")
                if 'DDoS-Guard' in edit_page.text:
                    print(f"{timestamp()} DDoS-Guard detected on edit page")
                return False
            
            # Check if we're actually logged in by looking for login form
            if 'login' in edit_page.url or 'login' in edit_page.text.lower():
                print(f"{timestamp()} Not logged in - redirecting to login page")
                return False
            
            # Submit gallery rename form
            rename_data = {
                'gallery_name': new_name,
                'submit_new_gallery': 'Rename Gallery',
                'public_gallery': '1'
            }
            
            response = self.session.post(f"{self.web_url}/user/gallery/edit?id={gallery_id}", data=rename_data)
            
            if response.status_code == 200:
                # Check if the rename was actually successful
                if 'success' in response.text.lower() or 'gallery' in response.url:
                    print(f"{timestamp()} Successfully renamed gallery to '{new_name}'")
                    return True
                else:
                    print(f"{timestamp()} Rename request returned 200 but may have failed")
                    if 'DDoS-Guard' in response.text:
                        print(f"{timestamp()} DDoS-Guard detected in response")
                    return False
            else:
                print(f"{timestamp()} Failed to rename gallery (status: {response.status_code})")
                if 'DDoS-Guard' in response.text:
                    print(f"{timestamp()} DDoS-Guard detected in response")
                return False
                
        except Exception as e:
            print(f"{timestamp()} Error renaming gallery: {str(e)}")
            return False
    
    def set_gallery_visibility(self, gallery_id, public_gallery=1):
        """Set gallery visibility (public/private)"""
        if not self.login():
            return False
        
        try:
            # Get the edit gallery page
            edit_page = self.session.get(f"{self.web_url}/user/gallery/edit?id={gallery_id}")
            
            # Submit gallery visibility form
            visibility_data = {
                'public_gallery': str(public_gallery),
                'submit_new_gallery': 'Update Gallery'
            }
            
            response = self.session.post(f"{self.web_url}/user/gallery/edit?id={gallery_id}", data=visibility_data)
            
            if response.status_code == 200:
                visibility = "public" if public_gallery else "private"
                print(f"{timestamp()} Successfully set gallery {gallery_id} to {visibility}")
                return True
            else:
                print(f"{timestamp()} Failed to update gallery visibility")
                return False
                
        except Exception as e:
            print(f"{timestamp()} Error updating gallery visibility: {str(e)}")
            return False
    
    def upload_image(self, image_path, create_gallery=False, gallery_id=None, thumbnail_size=3, thumbnail_format=2):
        """
        Upload a single image to imx.to
        
        Args:
            image_path (str): Path to the image file
            create_gallery (bool): Whether to create a new gallery
            gallery_id (str): ID of existing gallery to add image to
            thumbnail_size (int): Thumbnail size (1=100x100, 2=180x180, 3=250x250, 4=300x300, 6=150x150)
            thumbnail_format (int): Thumbnail format (1=Fixed width, 2=Proportional, 3=Square, 4=Fixed height)
            
        Returns:
            dict: API response
        """
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Image file not found: {image_path}")
        
        # Prepare files and data for upload
        with open(image_path, 'rb') as f:
            files = {'image': f}
            data = {}
            
            if create_gallery:
                data['create_gallery'] = 'true'
            
            if gallery_id:
                data['gallery_id'] = gallery_id
                
            # Request output format as JSON with all data
            data['format'] = 'all'
            data['thumbnail_size'] = str(thumbnail_size)
            data['thumbnail_format'] = str(thumbnail_format)
            
            try:
                response = requests.post(
                    self.upload_url,
                    headers=self.headers,
                    files=files,
                    data=data
                )
                
                if response.status_code == 200:
                    return response.json()
                else:
                    raise Exception(f"Upload failed with status code {response.status_code}: {response.text}")
                    
            except requests.exceptions.RequestException as e:
                raise Exception(f"Network error during upload: {str(e)}")
    
    def upload_folder(self, folder_path, gallery_name=None, thumbnail_size=3, thumbnail_format=2, max_retries=3, public_gallery=1, parallel_batch_size=4, template_name="default"):
        """
        Upload all images in a folder as a gallery
        
        Args:
            folder_path (str): Path to folder containing images
            gallery_name (str): Name for the gallery (optional)
            thumbnail_size (int): Thumbnail size setting
            thumbnail_format (int): Thumbnail format setting
            max_retries (int): Maximum retry attempts for failed uploads
            public_gallery (int): Gallery visibility (0=private, 1=public)
            
        Returns:
            dict: Contains gallery URL and individual image URLs
        """
        start_time = time.time()
        
        if not os.path.exists(folder_path):
            raise FileNotFoundError(f"Folder not found: {folder_path}")
        
        # Get all image files in folder and calculate total size
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
        
        if not image_files:
            raise ValueError(f"No image files found in {folder_path}")
        
        # Create gallery with name (default to folder name if not provided)
        if not gallery_name:
            gallery_name = os.path.basename(folder_path)
        
        # Sanitize gallery name
        original_name = gallery_name
        gallery_name = sanitize_gallery_name(gallery_name)
        if original_name != gallery_name:
            print(f"{timestamp()} Sanitized gallery name: '{original_name}' -> '{gallery_name}'")
        
        # Check if gallery already exists
        existing_files = check_if_gallery_exists(gallery_name)
        if existing_files:
            print(f"{timestamp()} Found existing gallery files for '{gallery_name}':")
            for file_path in existing_files:
                print(f"{timestamp()}   {file_path}")
            
            response = input(f"{timestamp()} Gallery appears to already exist. Continue anyway? (y/N): ")
            if response.lower() != 'y':
                print(f"{timestamp()} Skipping {folder_path}")
                return None
        
        # Create gallery (skip login since it's already done). If creation fails, fall back to API-only
        gallery_id = self.create_gallery_with_name(gallery_name, public_gallery, skip_login=True)
        initial_completed = 0
        initial_uploaded_size = 0
        preseed_images = []
        files_to_upload = []
        if not gallery_id:
            print("Failed to create named gallery, falling back to API-only upload...")
            # Upload first image to create gallery
            first_file = image_files[0]
            first_image_path = os.path.join(folder_path, first_file)
            print(f"{timestamp()} Uploading first image: {first_file}")
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
        print(f"{timestamp()} Successful dimensions: {successful_dimensions}")
        max_width = max(w for w, h in successful_dimensions) if successful_dimensions else 0
        max_height = max(h for w, h in successful_dimensions) if successful_dimensions else 0
        min_width = min(w for w, h in successful_dimensions) if successful_dimensions else 0
        min_height = min(h for w, h in successful_dimensions) if successful_dimensions else 0
        
        # Add statistics to results
        results.update({
            'gallery_id': gallery_id,
            'gallery_name': gallery_name,
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
        template_data = {
            'folder_name': gallery_name,
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
            save_gallery_artifacts(
                folder_path=folder_path,
                results={
                    'gallery_id': gallery_id,
                    'gallery_name': gallery_name,
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
                    'public_gallery': public_gallery,
                    'parallel_batch_size': parallel_batch_size,
                    'total_images': len(image_files),
                    'started_at': datetime.fromtimestamp(start_time).strftime('%Y-%m-%d %H:%M:%S'),
                },
                template_name=template_name,
            )
            print(f"{timestamp()} Saved gallery files to central and/or .uploaded as configured")
        except Exception as e:
            print(f"{timestamp()} Error writing artifacts: {e}")

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
                    'public_gallery': public_gallery,
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
            print(f"{timestamp()} Error writing JSON artifact: {e}")
        
        return results

def main():
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
    parser.add_argument('--public-gallery', type=int, choices=[0, 1], 
                       default=user_defaults.get('public_gallery', 1),
                       help='Gallery visibility: 0=private, 1=public (default: 1)')
    parser.add_argument('--parallel', type=int, 
                       default=user_defaults.get('parallel_batch_size', 4),
                       help='Number of images to upload simultaneously (default: 4)')
    parser.add_argument('--private', action='store_true',
                       help='Make galleries private (overrides --public-gallery)')
    parser.add_argument('--public', action='store_true',
                       help='Make galleries public (overrides --public-gallery)')
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
    
    args = parser.parse_args()
    if args.version:
        print(f"imxup {__version__}")
        return
    
    # Handle GUI launch
    if args.gui:
        try:
            # Try to import GUI module
            import imxup_gui
            
            # Check if folder paths were provided for GUI
            if args.folder_paths:
                # Pass folder paths to GUI for initial loading
                sys.argv = [sys.argv[0]] + args.folder_paths
            else:
                # Remove GUI arg to avoid conflicts
                sys.argv = [sys.argv[0]]
            
            # Launch GUI
            imxup_gui.main()
            return
        except ImportError as e:
            print(f"{timestamp()} Error: PyQt6 is required for GUI mode. Install with: pip install PyQt6")
            print(f"{timestamp()} Import error: {e}")
            sys.exit(1)
        except Exception as e:
            print(f"{timestamp()} Error launching GUI: {e}")
            sys.exit(1)
    
    # Handle secure setup
    if args.setup_secure:
            if setup_secure_password():
                print(f"{timestamp()} Setup complete! You can now use the script without storing passwords in plaintext.")
            else:
                print(f"{timestamp()} Setup failed. Please try again.")
            return
    
    # Handle context menu installation
    if args.install_context_menu:
        if create_windows_context_menu():
            print(f"{timestamp()} Context menu installed successfully!")
        else:
            print(f"{timestamp()} Failed to install context menu.")
        return
    
    # Handle context menu removal
    if args.remove_context_menu:
        if remove_windows_context_menu():
            print(f"{timestamp()} Context menu removed successfully!")
        else:
            print(f"{timestamp()} Failed to remove context menu.")
        return
    
    # Handle gallery visibility changes
    if len(args.folder_paths) == 1 and args.folder_paths[0].startswith('--'):
        # This is a gallery ID for visibility change
        gallery_id = args.folder_paths[0][2:]  # Remove -- prefix
        
        uploader = ImxToUploader()
        
        if args.public:
            if uploader.set_gallery_visibility(gallery_id, 1):
                print(f"Gallery {gallery_id} set to public")
            else:
                print(f"Failed to set gallery {gallery_id} to public")
        elif args.private:
            if uploader.set_gallery_visibility(gallery_id, 0):
                print(f"Gallery {gallery_id} set to private")
            else:
                print(f"Failed to set gallery {gallery_id} to private")
        else:
            print("Please specify --public or --private")
        return
    
    # Handle unnamed gallery renaming
    if args.rename_unnamed:
        uploader = ImxToUploader()
        unnamed_galleries = get_unnamed_galleries()
        
        if not unnamed_galleries:
            print(f"{timestamp()} No unnamed galleries found to rename")
            return
        
        print(f"{timestamp()} Found {len(unnamed_galleries)} unnamed galleries to rename:")
        for gallery_id, intended_name in unnamed_galleries.items():
            print(f"{timestamp()}   {gallery_id} -> '{intended_name}'")
        
        if uploader.login():
            success_count = 0
            for gallery_id, intended_name in unnamed_galleries.items():
                if uploader.rename_gallery_with_session(gallery_id, intended_name):
                    remove_unnamed_gallery(gallery_id)
                    success_count += 1
            
            print(f"{timestamp()} Successfully renamed {success_count}/{len(unnamed_galleries)} galleries")
        else:
            print(f"{timestamp()} Login failed - cannot rename galleries")
            print(f"{timestamp()} DDoS-Guard protection is blocking automated login.")
            print(f"{timestamp()} To rename galleries manually:")
            print(f"{timestamp()} 1. Log in to https://imx.to in your browser")
            print(f"{timestamp()} 2. Navigate to each gallery and rename it manually")
            print(f"{timestamp()} 3. Or export cookies from browser and place in cookies.txt file")
            print(f"{timestamp()} Gallery IDs to rename: {', '.join(unnamed_galleries.keys())}")
        return
    
    # Check if folder paths are provided (required for upload)
    if not args.folder_paths:
        parser.error("folder_paths is required for upload operations")
    
    # Expand wildcards in folder paths
    expanded_paths = []
    for path in args.folder_paths:
        if '*' in path or '?' in path:
            # Expand wildcards
            expanded = glob.glob(path)
            if not expanded:
                print(f"Warning: No folders found matching pattern: {path}")
            expanded_paths.extend(expanded)
        else:
            expanded_paths.append(path)
    
    if not expanded_paths:
        print("No valid folders found to upload.")
        return
    
    # Determine public gallery setting
    public_gallery = args.public_gallery
    if args.private:
        public_gallery = 0
    elif args.public:
        public_gallery = 1
    
    try:
        uploader = ImxToUploader()
        all_results = []

        # Login once for all galleries
        print(f"{timestamp()} Logging in for all galleries...")
        if not uploader.login():
            print(f"{timestamp()} Login failed - falling back to API-only uploads")

        # Use shared UploadEngine for consistent behavior
        from imxup_core import UploadEngine
        engine = UploadEngine(uploader)

        # Process multiple galleries
        for folder_path in expanded_paths:
            gallery_name = args.name if args.name else None

            try:
                print(f"{timestamp()} Starting upload: {os.path.basename(folder_path)}")
                results = engine.run(
                    folder_path=folder_path,
                    gallery_name=gallery_name,
                    thumbnail_size=args.size,
                    thumbnail_format=args.format,
                    max_retries=args.max_retries,
                    public_gallery=public_gallery,
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
                    print(f"{timestamp()} Artifact save error: {e}")

                all_results.append(results)

            except KeyboardInterrupt:
                print(f"\n{timestamp()} Upload interrupted by user")
                break
            except Exception as e:
                print(f"Error uploading {folder_path}: {str(e)}", file=sys.stderr)
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
                
        else:
            print("No galleries were successfully uploaded.")
            
    except Exception as e:
        print(f"Error: {str(e)}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nExiting gracefully...")
        sys.exit(0)
    except SystemExit:
        # Handle argparse errors gracefully in PyInstaller
        pass
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)