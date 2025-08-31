#!/usr/bin/env python3
"""
Configuration utilities for imxup
Handles config file management, credential encryption, and settings
"""

import os
import configparser
import hashlib
import platform
import socket
from pathlib import Path
from typing import Dict, Any, Optional

# Try to import cryptography for encryption
try:
    from cryptography.fernet import Fernet
    ENCRYPTION_AVAILABLE = True
except ImportError:
    ENCRYPTION_AVAILABLE = False


def get_config_path() -> str:
    """Return the canonical path to the application's config file
    
    Returns:
        Path to config file (~/.imxup/imxup.ini)
    """
    base_dir = os.path.join(os.path.expanduser("~"), ".imxup")
    os.makedirs(base_dir, exist_ok=True)
    return os.path.join(base_dir, "imxup.ini")


def get_legacy_config_path() -> str:
    """Return legacy config path
    
    Returns:
        Path to legacy config file (~/.imxup.ini)
    """
    return os.path.join(os.path.expanduser("~"), ".imxup.ini")


def get_central_storage_path() -> str:
    """Get the central storage path for galleries
    
    Returns:
        Path to central galleries directory
    """
    base_dir = os.path.join(os.path.expanduser("~"), ".imxup")
    galleries_dir = os.path.join(base_dir, "galleries")
    os.makedirs(galleries_dir, exist_ok=True)
    return galleries_dir


def get_templates_path() -> str:
    """Get the templates directory path
    
    Returns:
        Path to templates directory
    """
    base_dir = os.path.join(os.path.expanduser("~"), ".imxup")
    templates_dir = os.path.join(base_dir, "templates")
    os.makedirs(templates_dir, exist_ok=True)
    return templates_dir


def get_encryption_key() -> bytes:
    """Generate a machine-specific encryption key
    
    Uses hostname and username to create a deterministic key
    
    Returns:
        32-byte encryption key
    """
    hostname = socket.gethostname()
    username = os.environ.get('USER', os.environ.get('USERNAME', 'default'))
    key_source = f"{hostname}:{username}:imxup"
    
    # Generate a 32-byte key using SHA256
    key = hashlib.sha256(key_source.encode()).digest()
    
    # For Fernet, we need to encode it as base64
    if ENCRYPTION_AVAILABLE:
        import base64
        return base64.urlsafe_b64encode(key)
    
    return key


def encrypt_password(password: str) -> str:
    """Encrypt a password using machine-specific key
    
    Args:
        password: Plain text password
        
    Returns:
        Encrypted password string
    """
    if not ENCRYPTION_AVAILABLE:
        # Fallback to simple obfuscation if cryptography not available
        import base64
        return base64.b64encode(password.encode()).decode()
    
    try:
        key = get_encryption_key()
        fernet = Fernet(key)
        encrypted = fernet.encrypt(password.encode())
        return encrypted.decode()
    except Exception:
        # Fallback to base64 encoding
        import base64
        return base64.b64encode(password.encode()).decode()


def decrypt_password(encrypted_password: str) -> str:
    """Decrypt a password using machine-specific key
    
    Args:
        encrypted_password: Encrypted password string
        
    Returns:
        Plain text password
    """
    if not ENCRYPTION_AVAILABLE:
        # Fallback to simple deobfuscation
        import base64
        try:
            return base64.b64decode(encrypted_password.encode()).decode()
        except Exception:
            return encrypted_password
    
    try:
        key = get_encryption_key()
        fernet = Fernet(key)
        decrypted = fernet.decrypt(encrypted_password.encode())
        return decrypted.decode()
    except Exception:
        # Try base64 decoding as fallback
        import base64
        try:
            return base64.b64decode(encrypted_password.encode()).decode()
        except Exception:
            return encrypted_password


def load_user_defaults() -> Dict[str, Any]:
    """Load user default settings from config file
    
    Returns:
        Dictionary of user settings with defaults
    """
    defaults = {
        'thumbnail_size': 3,
        'thumbnail_format': 2,
        'max_retries': 3,
        'parallel_batch_size': 4,
        'template_name': 'default',
        'auto_rename': True,
        'use_firefox_cookies': False,
        'theme': 'auto',
        'minimize_to_tray': False,
        'show_notifications': True,
        'confirm_exit': True,
        'auto_start_queue': False,
        'save_window_geometry': True
    }
    
    config = configparser.ConfigParser()
    config_file = get_config_path()
    
    if os.path.exists(config_file):
        config.read(config_file)
        
        # Load settings section
        if 'SETTINGS' in config:
            for key in defaults:
                if key in config['SETTINGS']:
                    value = config['SETTINGS'][key]
                    
                    # Convert to appropriate type
                    if key in ['thumbnail_size', 'thumbnail_format', 'max_retries', 
                               'parallel_batch_size']:
                        try:
                            defaults[key] = int(value)
                        except ValueError:
                            pass
                    elif key in ['auto_rename', 'use_firefox_cookies', 'minimize_to_tray',
                                 'show_notifications', 'confirm_exit', 'auto_start_queue',
                                 'save_window_geometry']:
                        defaults[key] = value.lower() in ('true', '1', 'yes', 'on')
                    else:
                        defaults[key] = value
    
    return defaults


def save_user_defaults(settings: Dict[str, Any]) -> None:
    """Save user default settings to config file
    
    Args:
        settings: Dictionary of settings to save
    """
    config = configparser.ConfigParser()
    config_file = get_config_path()
    
    # Read existing config
    if os.path.exists(config_file):
        config.read(config_file)
    
    # Ensure SETTINGS section exists
    if 'SETTINGS' not in config:
        config['SETTINGS'] = {}
    
    # Update settings
    for key, value in settings.items():
        if isinstance(value, bool):
            config['SETTINGS'][key] = 'true' if value else 'false'
        else:
            config['SETTINGS'][key] = str(value)
    
    # Write config
    with open(config_file, 'w') as f:
        config.write(f)


def get_credentials() -> Dict[str, Optional[str]]:
    """Load credentials from config file
    
    Returns:
        Dictionary with username, password (decrypted), and api_key
    """
    credentials = {
        'username': None,
        'password': None,
        'api_key': None,
        'use_firefox_cookies': False
    }
    
    config = configparser.ConfigParser()
    config_file = get_config_path()
    
    if os.path.exists(config_file):
        config.read(config_file)
        
        if 'CREDENTIALS' in config:
            credentials['username'] = config.get('CREDENTIALS', 'username', fallback=None)
            
            encrypted_password = config.get('CREDENTIALS', 'password', fallback=None)
            if encrypted_password:
                credentials['password'] = decrypt_password(encrypted_password)
            
            credentials['api_key'] = config.get('CREDENTIALS', 'api_key', fallback=None)
            credentials['use_firefox_cookies'] = config.getboolean(
                'CREDENTIALS', 'use_firefox_cookies', fallback=False
            )
    
    return credentials


def save_credentials(credentials: Dict[str, Any]) -> None:
    """Save credentials to config file
    
    Args:
        credentials: Dictionary with username, password, and api_key
    """
    config = configparser.ConfigParser()
    config_file = get_config_path()
    
    # Read existing config
    if os.path.exists(config_file):
        config.read(config_file)
    
    # Ensure CREDENTIALS section exists
    if 'CREDENTIALS' not in config:
        config['CREDENTIALS'] = {}
    
    # Save credentials
    if 'username' in credentials and credentials['username']:
        config['CREDENTIALS']['username'] = credentials['username']
    
    if 'password' in credentials and credentials['password']:
        encrypted = encrypt_password(credentials['password'])
        config['CREDENTIALS']['password'] = encrypted
    
    if 'api_key' in credentials and credentials['api_key']:
        config['CREDENTIALS']['api_key'] = credentials['api_key']
    
    if 'use_firefox_cookies' in credentials:
        config['CREDENTIALS']['use_firefox_cookies'] = str(credentials['use_firefox_cookies']).lower()
    
    # Write config
    with open(config_file, 'w') as f:
        config.write(f)


def migrate_legacy_config() -> bool:
    """Migrate legacy config file to new location
    
    Returns:
        True if migration was performed, False otherwise
    """
    legacy_path = get_legacy_config_path()
    new_path = get_config_path()
    
    if os.path.exists(legacy_path) and not os.path.exists(new_path):
        try:
            # Read legacy config
            config = configparser.ConfigParser()
            config.read(legacy_path)
            
            # Write to new location
            with open(new_path, 'w') as f:
                config.write(f)
            
            # Optionally remove legacy file
            try:
                os.remove(legacy_path)
            except Exception:
                pass
            
            return True
        except Exception:
            pass
    
    return False