#!/usr/bin/env python3
"""
Core upload functionality extracted from imxup.py
Contains the main ImxToUploader class and related utilities
"""

import os
import requests
import json
import sys
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import concurrent.futures
import time
from tqdm import tqdm
import configparser
import hashlib
import getpass
import platform
import sqlite3
import glob
import base64
from cryptography.fernet import Fernet


# Application version
__version__ = "0.2.4"

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

# Placeholder for ImxToUploader class - will be extracted from original file
class ImxToUploader:
    """Main uploader class - to be extracted from original imxup.py"""
    pass