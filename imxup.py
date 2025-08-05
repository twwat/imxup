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
import re
import asyncio
import aiohttp
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
from tqdm import tqdm
import configparser
import hashlib
import getpass
import subprocess
import tempfile
import json
import zipfile
import urllib.request
import platform
import sqlite3
import shutil
import glob
import winreg

# Load environment variables
load_dotenv()

def timestamp():
    """Return current timestamp for logging"""
    return datetime.now().strftime("%H:%M:%S")

def create_windows_context_menu():
    """Create Windows context menu integration"""
    try:
        # Get the path to the executable
        exe_path = os.path.abspath(sys.argv[0])
        if exe_path.endswith('.py'):
            # If running as script, use the compiled exe
            exe_path = os.path.join(os.path.dirname(exe_path), 'imx2.exe')
        
        # Create registry entries
        key_path = r"Directory\Background\shell\UploadToImx"
        key = winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, key_path)
        winreg.SetValue(key, "", winreg.REG_SZ, "Upload to imx.to")
        
        # Set icon (optional)
        # winreg.SetValue(key, "Icon", winreg.REG_SZ, exe_path)
        
        # Create command
        command_key = winreg.CreateKey(key, "command")
        winreg.SetValue(command_key, "", winreg.REG_SZ, f'"{exe_path}" "%V"')
        
        winreg.CloseKey(command_key)
        winreg.CloseKey(key)
        
        print(f"Context menu created successfully!")
        print(f"Right-click on any folder and select 'Upload to imx.to'")
        return True
        
    except Exception as e:
        print(f"Error creating context menu: {e}")
        return False

def remove_windows_context_menu():
    """Remove Windows context menu integration"""
    try:
        key_path = r"Directory\Background\shell\UploadToImx"
        winreg.DeleteKey(winreg.HKEY_CLASSES_ROOT, key_path)
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

class AsyncImxToUploader:
    """Async version of ImxToUploader using aiohttp"""
    
    def __init__(self):
        self.upload_url = "https://imx.to/api/upload"
        self.web_url = "https://imx.to"
        self.username = None
        self.password = None
        self.session = None
        self._get_credentials()
        
        # Default headers for API requests
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:141.0) Gecko/20100101 Firefox/141.0'
        }
    
    def _get_credentials(self):
        """Load stored credentials"""
        config = configparser.ConfigParser()
        config_file = os.path.join(os.path.expanduser("~"), ".imxup.ini")
        
        if os.path.exists(config_file):
            config.read(config_file)
            if 'CREDENTIALS' in config:
                self.username = config.get('CREDENTIALS', 'username', fallback=None)
                encrypted_password = config.get('CREDENTIALS', 'password', fallback=None)
                if encrypted_password:
                    self.password = decrypt_password(encrypted_password)
    
    async def upload_image_async(self, session, image_path, gallery_id=None, thumbnail_size=3, thumbnail_format=2):
        """Upload a single image asynchronously"""
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Image file not found: {image_path}")
        
        # Prepare form data
        data = aiohttp.FormData()
        
        # Add image file
        with open(image_path, 'rb') as f:
            data.add_field('image', f, filename=os.path.basename(image_path))
        
        # Add other parameters
        if gallery_id:
            data.add_field('gallery_id', str(gallery_id))
        
        data.add_field('format', 'all')
        data.add_field('thumbnail_size', str(thumbnail_size))
        data.add_field('thumbnail_format', str(thumbnail_format))
        
        try:
            async with session.post(self.upload_url, data=data, headers=self.headers) as response:
                if response.status == 200:
                    result = await response.json()
                    return result
                else:
                    text = await response.text()
                    raise Exception(f"Upload failed with status {response.status}: {text}")
        except Exception as e:
            raise Exception(f"Network error during upload: {str(e)}")
    
    async def upload_folder_async(self, folder_path, gallery_name=None, thumbnail_size=3, thumbnail_format=2, max_retries=3, public_gallery=1, max_concurrent=4):
        """Upload all images in a folder asynchronously with nested progress tracking"""
        start_time = time.time()
        
        if not os.path.exists(folder_path):
            raise FileNotFoundError(f"Folder not found: {folder_path}")
        
        # Get all image files and calculate total size
        image_extensions = ('.jpg', '.jpeg', '.png', '.gif')
        image_files = []
        total_size = 0
        
        for f in os.listdir(folder_path):
            if f.lower().endswith(image_extensions) and os.path.isfile(os.path.join(folder_path, f)):
                image_files.append(f)
                file_path = os.path.join(folder_path, f)
                total_size += os.path.getsize(file_path)
        
        if not image_files:
            raise ValueError(f"No image files found in {folder_path}")
        
        # Create gallery name
        if not gallery_name:
            gallery_name = os.path.basename(folder_path)
        
        original_name = gallery_name
        gallery_name = sanitize_gallery_name(gallery_name)
        if original_name != gallery_name:
            print(f"{timestamp()} Sanitized gallery name: '{original_name}' -> '{gallery_name}'")
        
        # Create gallery (this would need to be implemented as async)
        # For now, we'll use the sync version
        uploader = ImxToUploader()
        gallery_id = uploader.create_gallery_with_name(gallery_name, public_gallery, skip_login=True)
        
        if not gallery_id:
            print("Failed to create named gallery, falling back to API-only upload...")
            # For async mode, we'll create galleries without names and upload directly
            # This bypasses the web interface entirely
            async with aiohttp.ClientSession() as session:
                return await self._upload_without_named_gallery_async(
                    session, folder_path, image_files, thumbnail_size, thumbnail_format, max_retries, max_concurrent
                )
        
        gallery_url = f"https://imx.to/g/{gallery_id}"
        
        # Results storage
        results = {
            'gallery_url': gallery_url,
            'gallery_id': gallery_id,
            'gallery_name': gallery_name,
            'images': []
        }
        
        # Create semaphore for limiting concurrent uploads
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def upload_single_with_semaphore(image_file, attempt=1):
            async with semaphore:
                image_path = os.path.join(folder_path, image_file)
                try:
                    response = await self.upload_image_async(
                        session, image_path, gallery_id, thumbnail_size, thumbnail_format
                    )
                    
                    if response.get('status') == 'success':
                        return image_file, response['data'], None
                    else:
                        return image_file, None, f"API error: {response}"
                        
                except Exception as e:
                    return image_file, None, f"Network error: {str(e)}"
        
        # Main upload with nested progress tracking
        async with aiohttp.ClientSession() as session:
            self.session = session
            
            # Main progress bar
            with NestedProgressBar(len(image_files), f"Uploading to {gallery_name}", level=0) as main_pbar:
                uploaded_images = []
                failed_images = []
                
                # Upload all images concurrently
                tasks = [upload_single_with_semaphore(img_file) for img_file in image_files]
                
                # Process results as they complete
                for coro in asyncio.as_completed(tasks):
                    image_file, image_data, error = await coro
                    
                    if image_data:
                        uploaded_images.append((image_file, image_data))
                        main_pbar.set_postfix_str(f"✓ {image_file}")
                    else:
                        failed_images.append((image_file, error))
                        main_pbar.set_postfix_str(f"✗ {image_file}")
                    
                    main_pbar.update(1)
                
                # Retry failed uploads
                retry_count = 0
                while failed_images and retry_count < max_retries:
                    retry_count += 1
                    retry_failed = []
                    
                    with NestedProgressBar(len(failed_images), f"Retry {retry_count}/{max_retries}", level=1) as retry_pbar:
                        retry_tasks = [upload_single_with_semaphore(img_file, retry_count + 1) 
                                     for img_file, _ in failed_images]
                        
                        for coro in asyncio.as_completed(retry_tasks):
                            image_file, image_data, error = await coro
                            
                            if image_data:
                                uploaded_images.append((image_file, image_data))
                                retry_pbar.set_postfix_str(f"✓ {image_file}")
                            else:
                                retry_failed.append((image_file, error))
                                retry_pbar.set_postfix_str(f"✗ {image_file}")
                            
                            retry_pbar.update(1)
                    
                    failed_images = retry_failed
        
        # Sort uploaded images by original file order
        uploaded_images.sort(key=lambda x: image_files.index(x[0]))
        
        # Add to results
        for _, image_data in uploaded_images:
            results['images'].append(image_data)
        
        # Calculate statistics
        end_time = time.time()
        upload_time = end_time - start_time
        
        uploaded_size = sum(os.path.getsize(os.path.join(folder_path, img_file)) 
                           for img_file, _ in uploaded_images)
        transfer_speed = uploaded_size / upload_time if upload_time > 0 else 0
        
        results.update({
            'upload_time': upload_time,
            'total_size': total_size,
            'uploaded_size': uploaded_size,
            'transfer_speed': transfer_speed,
            'successful_count': len(uploaded_images),
            'failed_count': len(failed_images)
        })
        
        # Create gallery folder and files
        gallery_folder = os.path.join(folder_path, f"gallery_{gallery_id}")
        os.makedirs(gallery_folder, exist_ok=True)
        
        # Create shortcut file
        shortcut_content = f"""[InternetShortcut]
URL=https://imx.to/g/{gallery_id}
"""
        shortcut_path = os.path.join(gallery_folder, f"gallery_{gallery_id}.url")
        with open(shortcut_path, 'w', encoding='utf-8') as f:
            f.write(shortcut_content)
        
        # Create bbcode file
        bbcode_content = ""
        for image_data in results['images']:
            bbcode_content += image_data['bbcode'] + "\n"
        
        bbcode_path = os.path.join(gallery_folder, f"gallery_{gallery_id}_bbcode.txt")
        with open(bbcode_path, 'w', encoding='utf-8') as f:
            f.write(bbcode_content)
        
        return results
    
    async def _upload_without_named_gallery_async(self, session, folder_path, image_files, thumbnail_size, thumbnail_format, max_retries, max_concurrent):
        """Upload images without creating a named gallery (API-only)"""
        start_time = time.time()
        
        # Calculate total size
        total_size = sum(os.path.getsize(os.path.join(folder_path, f)) for f in image_files)
        
        # Create semaphore for limiting concurrent uploads
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def upload_single_with_semaphore(image_file, attempt=1):
            async with semaphore:
                image_path = os.path.join(folder_path, image_file)
                try:
                    response = await self.upload_image_async(
                        session, image_path, None, thumbnail_size, thumbnail_format
                    )
                    
                    if response.get('status') == 'success':
                        return image_file, response['data'], None
                    else:
                        return image_file, None, f"API error: {response}"
                        
                except Exception as e:
                    return image_file, None, f"Network error: {str(e)}"
        
        # Main upload with nested progress tracking
        with NestedProgressBar(len(image_files), "Uploading images (API-only)", level=0) as main_pbar:
            uploaded_images = []
            failed_images = []
            
            # Upload all images concurrently
            tasks = [upload_single_with_semaphore(img_file) for img_file in image_files]
            
            # Process results as they complete
            for coro in asyncio.as_completed(tasks):
                image_file, image_data, error = await coro
                
                if image_data:
                    uploaded_images.append((image_file, image_data))
                    main_pbar.set_postfix_str(f"✓ {image_file}")
                else:
                    failed_images.append((image_file, error))
                    main_pbar.set_postfix_str(f"✗ {image_file}")
                
                main_pbar.update(1)
            
            # Retry failed uploads
            retry_count = 0
            while failed_images and retry_count < max_retries:
                retry_count += 1
                retry_failed = []
                
                with NestedProgressBar(len(failed_images), f"Retry {retry_count}/{max_retries}", level=1) as retry_pbar:
                    retry_tasks = [upload_single_with_semaphore(img_file, retry_count + 1) 
                                 for img_file, _ in failed_images]
                    
                    for coro in asyncio.as_completed(retry_tasks):
                        image_file, image_data, error = await coro
                        
                        if image_data:
                            uploaded_images.append((image_file, image_data))
                            retry_pbar.set_postfix_str(f"✓ {image_file}")
                        else:
                            retry_failed.append((image_file, error))
                            retry_pbar.set_postfix_str(f"✗ {image_file}")
                        
                        retry_pbar.update(1)
                
                failed_images = retry_failed
        
        # Sort uploaded images by original file order
        uploaded_images.sort(key=lambda x: image_files.index(x[0]))
        
        # Calculate statistics
        end_time = time.time()
        upload_time = end_time - start_time
        
        uploaded_size = sum(os.path.getsize(os.path.join(folder_path, img_file)) 
                           for img_file, _ in uploaded_images)
        transfer_speed = uploaded_size / upload_time if upload_time > 0 else 0
        
        # Create results
        results = {
            'gallery_url': None,  # No gallery URL for API-only uploads
            'gallery_id': None,
            'gallery_name': None,
            'images': [image_data for _, image_data in uploaded_images],
            'upload_time': upload_time,
            'total_size': total_size,
            'uploaded_size': uploaded_size,
            'transfer_speed': transfer_speed,
            'successful_count': len(uploaded_images),
            'failed_count': len(failed_images)
        }
        
        return results

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
    config_file = os.path.join(os.path.expanduser("~"), ".imxup.ini")
    
    if os.path.exists(config_file):
        config.read(config_file)
        defaults = {}
        
        if 'DEFAULTS' in config:
            defaults['thumbnail_size'] = config.getint('DEFAULTS', 'thumbnail_size', fallback=3)
            defaults['thumbnail_format'] = config.getint('DEFAULTS', 'thumbnail_format', fallback=2)
            defaults['max_retries'] = config.getint('DEFAULTS', 'max_retries', fallback=3)
            defaults['public_gallery'] = config.getint('DEFAULTS', 'public_gallery', fallback=1)
        
        return defaults
    return {}

def setup_secure_password():
    """Interactive setup for secure password storage"""
    print("Setting up secure password storage for imx.to")
    print("This will store a hashed version of your password in ~/.imxup.ini")
    print()
    
    username = input("Enter your imx.to username: ")
    password = getpass.getpass("Enter your imx.to password: ")
    
    # Save credentials without testing (since DDoS-Guard might block login)
    print("Saving credentials...")
    if _save_credentials(username, password):
        print("[OK] Credentials saved successfully!")
        print("Note: Login test was skipped due to potential DDoS-Guard protection.")
        return True
    else:
        print("[ERROR] Failed to save credentials")
        return False

def _save_credentials(username, password):
    """Save encrypted credentials to config file"""
    try:
        config = configparser.ConfigParser()
        config_file = os.path.join(os.path.expanduser("~"), ".imxup.ini")
        
        if os.path.exists(config_file):
            config.read(config_file)
        
        if 'CREDENTIALS' not in config:
            config.add_section('CREDENTIALS')
        
        config.set('CREDENTIALS', 'username', username)
        config.set('CREDENTIALS', 'password', encrypt_password(password))
        
        with open(config_file, 'w') as f:
            config.write(f)
        
        return True
    except Exception as e:
        print(f"Error saving credentials: {str(e)}")
        return False

def save_unnamed_gallery(gallery_id, intended_name):
    """Save an unnamed gallery ID with its intended name for later renaming"""
    config = configparser.ConfigParser()
    config_file = os.path.join(get_central_storage_path(), "unnamed_galleries.ini")
    
    if os.path.exists(config_file):
        config.read(config_file)
    
    if 'GALLERIES' not in config:
        config.add_section('GALLERIES')
    
    config.set('GALLERIES', gallery_id, intended_name)
    
    with open(config_file, 'w') as f:
        config.write(f)

def get_central_storage_path():
    """Get the central storage path for configuration files"""
    return os.path.expanduser("~")

def sanitize_gallery_name(name):
    """Sanitize gallery name for imx.to"""
    # Remove or replace invalid characters
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    # Limit length
    if len(name) > 100:
        name = name[:97] + "..."
    return name

def check_if_gallery_exists(folder_name):
    """Check if a gallery with this name already exists by looking for files"""
    sanitized_name = sanitize_gallery_name(folder_name)
    pattern = f"gallery_*_{sanitized_name}*"
    
    existing_files = []
    for root, dirs, files in os.walk("."):
        for file in files:
            if file.startswith("gallery_") and sanitized_name.lower() in file.lower():
                existing_files.append(os.path.join(root, file))
    
    return existing_files

def get_unnamed_galleries():
    """Get all unnamed galleries that need renaming"""
    config = configparser.ConfigParser()
    config_file = os.path.join(get_central_storage_path(), "unnamed_galleries.ini")
    
    if not os.path.exists(config_file):
        return {}
    
    config.read(config_file)
    
    if 'GALLERIES' not in config:
        return {}
    
    return dict(config.items('GALLERIES'))

def remove_unnamed_gallery(gallery_id):
    """Remove an unnamed gallery from the list after successful renaming"""
    config = configparser.ConfigParser()
    config_file = os.path.join(get_central_storage_path(), "unnamed_galleries.ini")
    
    if not os.path.exists(config_file):
        return
    
    config.read(config_file)
    
    if 'GALLERIES' in config and config.has_option('GALLERIES', gallery_id):
        config.remove_option('GALLERIES', gallery_id)
        
        with open(config_file, 'w') as f:
            config.write(f)

def get_firefox_cookies(domain="imx.to"):
    """Extract cookies from Firefox browser"""
    cookies = {}
    
    try:
        # Try to find Firefox profile directory
        if platform.system() == "Windows":
            appdata = os.getenv('APPDATA')
            firefox_path = os.path.join(appdata, "Mozilla", "Firefox", "Profiles")
        else:
            home = os.path.expanduser("~")
            firefox_path = os.path.join(home, ".mozilla", "firefox")
        
        if not os.path.exists(firefox_path):
            return cookies
        
        # Find the default profile
        profiles = [d for d in os.listdir(firefox_path) if d.endswith('.default') or d.endswith('.default-release')]
        if not profiles:
            return cookies
        
        profile_dir = os.path.join(firefox_path, profiles[0])
        cookies_file = os.path.join(profile_dir, "cookies.sqlite")
        
        if not os.path.exists(cookies_file):
            return cookies
        
        # Copy cookies file to temp location (Firefox locks the original)
        import tempfile
        import shutil
        
        temp_cookies = tempfile.NamedTemporaryFile(delete=False, suffix='.sqlite')
        shutil.copy2(cookies_file, temp_cookies.name)
        temp_cookies.close()
        
        try:
            # Read cookies from SQLite database
            conn = sqlite3.connect(temp_cookies.name)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT name, value, host, path, expiry 
                FROM moz_cookies 
                WHERE host LIKE ?
            """, (f"%{domain}%",))
            
            for name, value, host, path, expiry in cursor.fetchall():
                cookies[name] = {
                    'value': value,
                    'domain': host,
                    'path': path,
                    'expiry': expiry
                }
            
            conn.close()
            
        finally:
            # Clean up temp file
            os.unlink(temp_cookies.name)
            
    except Exception as e:
        print(f"Error reading Firefox cookies: {str(e)}")
    
    return cookies

def load_cookies_from_file(cookie_file="cookies.txt"):
    """Load cookies from a cookies.txt file"""
    cookies = {}
    
    if not os.path.exists(cookie_file):
        print(f"Cookie file not found: {cookie_file}")
        return cookies
    
    try:
        with open(cookie_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line.startswith('#') or not line:
                    continue
                
                parts = line.split('\t')
                if len(parts) >= 7:
                    domain, _, path, secure, expiry, name, value = parts[:7]
                    cookies[name] = {
                        'value': value,
                        'domain': domain,
                        'path': path,
                        'expiry': expiry
                    }
    except Exception as e:
        print(f"Error reading cookie file: {str(e)}")
    
    return cookies

class ImxToUploader:
    def _get_credentials(self):
        """Load stored credentials"""
        config = configparser.ConfigParser()
        config_file = os.path.join(os.path.expanduser("~"), ".imxup.ini")
        
        if os.path.exists(config_file):
            config.read(config_file)
            if 'CREDENTIALS' in config:
                self.username = config.get('CREDENTIALS', 'username', fallback=None)
                encrypted_password = config.get('CREDENTIALS', 'password', fallback=None)
                if encrypted_password:
                    self.password = decrypt_password(encrypted_password)
    
    def __init__(self):
        self.upload_url = "https://imx.to/api/upload"
        self.web_url = "https://imx.to"
        self.username = None
        self.password = None
        self.session = None
        self._get_credentials()
        
        # Default headers for API requests
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:141.0) Gecko/20100101 Firefox/141.0'
        }
        
        # Initialize session
        self.session = requests.Session()
        self.session.headers.update(self.headers)
    
    def login(self):
        """Login to imx.to web interface"""
        if not self.username or not self.password:
            print(f"{timestamp()} Warning: No stored credentials, gallery naming disabled")
            return False
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    print(f"{timestamp()} Retry attempt {attempt + 1}/{max_retries}")
                    time.sleep(2 ** attempt)  # Exponential backoff
                
                # Try to get Firefox cookies first
                print(f"{timestamp()} Attempting to use Firefox cookies to bypass DDoS-Guard...")
                firefox_cookies = get_firefox_cookies("imx.to")
                
                # Also try loading from cookies.txt file as backup
                file_cookies = load_cookies_from_file("cookies.txt")
                
                # Combine cookies (file cookies take precedence)
                all_cookies = {**firefox_cookies, **file_cookies}
                
                if firefox_cookies:
                    print(f"{timestamp()} Found {len(firefox_cookies)} Firefox cookies for imx.to")
                elif file_cookies:
                    print(f"{timestamp()} Found {len(file_cookies)} cookies from cookies.txt")
                elif all_cookies:
                    print(f"{timestamp()} Found {len(all_cookies)} total cookies for imx.to")
                    # Add cookies to session
                    for name, cookie_data in all_cookies.items():
                        self.session.cookies.set(name, cookie_data['value'], 
                                              domain=cookie_data['domain'], 
                                              path=cookie_data['path'])
                    
                    # Test if we're already logged in with cookies
                    test_response = self.session.get(f"{self.web_url}/user/gallery/manage")
                    if 'login' not in test_response.url and 'DDoS-Guard' not in test_response.text:
                        print(f"{timestamp()} Successfully logged in using browser cookies")
                        return True
                
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
                    firefox_cookies = get_firefox_cookies("imx.to")
                    file_cookies = load_cookies_from_file("cookies.txt")
                    all_cookies = {**firefox_cookies, **file_cookies}
                    
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
                    print(f"{timestamp()} Successfully logged in to imx.to")
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
    
    def _upload_without_named_gallery(self, folder_path, image_files, thumbnail_size, thumbnail_format, max_retries):
        """Fallback upload method without gallery naming"""
        start_time = time.time()
        print(f"{timestamp()} Using API-only upload (no gallery naming)")
        
        # Upload first image and create gallery
        first_image_path = os.path.join(folder_path, image_files[0])
        print(f"{timestamp()} Uploading first image: {image_files[0]}")
        
        first_response = self.upload_image(first_image_path, create_gallery=True, 
                                          thumbnail_size=thumbnail_size, thumbnail_format=thumbnail_format)
        
        if first_response.get('status') != 'success':
            raise Exception(f"{timestamp()} Failed to create gallery: {first_response}")
        
        # Get gallery ID from first upload
        gallery_id = first_response['data'].get('gallery_id')
        gallery_url = f"https://imx.to/g/{gallery_id}"
        
        # Save for later renaming (with sanitized name)
        folder_name = sanitize_gallery_name(os.path.basename(folder_path))
        save_unnamed_gallery(gallery_id, folder_name)
        print(f"{timestamp()} Saved unnamed gallery {gallery_id} for later renaming to '{folder_name}'")
        
        # Store results
        results = {
            'gallery_url': gallery_url,
            'images': [first_response['data']]
        }
        
        # Upload remaining images with progress bars and concurrency
        def upload_single_image(image_file, attempt=1, pbar=None):
            image_path = os.path.join(folder_path, image_file)
            
            try:
                response = self.upload_image(image_path, gallery_id=gallery_id,
                                           thumbnail_size=thumbnail_size, thumbnail_format=thumbnail_format)
                
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
        
        # Upload remaining images with retries, maintaining order
        uploaded_images = []
        failed_images = []
        
        # Main upload progress bar
        with tqdm(total=len(image_files[1:]), desc="Uploading remaining images", 
                 unit="img", leave=False) as pbar:
            
            # Process images in batches of 8 for concurrent uploads
            batch_size = 5
            remaining_images = image_files[1:]  # Skip first image (already uploaded)
            for i in range(0, len(remaining_images), batch_size):
                batch = remaining_images[i:i + batch_size]
                
                # Upload batch concurrently
                with ThreadPoolExecutor(max_workers=batch_size) as executor:
                    # Submit all uploads in the batch
                    future_to_file = {
                        executor.submit(upload_single_image, image_file, 1, pbar): image_file 
                        for image_file in batch
                    }
                    
                    # Collect results as they complete
                    batch_results = []
                    for future in as_completed(future_to_file):
                        image_file, image_data, error = future.result()
                        batch_results.append((image_file, image_data, error))
                        pbar.update(1)
                
                # Process batch results
                for image_file, image_data, error in batch_results:
                    if image_data:
                        uploaded_images.append((image_file, image_data))
                    else:
                        failed_images.append((image_file, error))
        
        # Retry failed uploads with progress bar
        retry_count = 0
        while failed_images and retry_count < max_retries:
            retry_count += 1
            retry_failed = []
            
            with tqdm(total=len(failed_images), desc=f"Retry {retry_count}/{max_retries}", 
                     unit="img", leave=False) as retry_pbar:
                
                with ThreadPoolExecutor(max_workers=4) as executor:
                    future_to_file = {
                        executor.submit(upload_single_image, image_file, retry_count + 1, retry_pbar): image_file 
                        for image_file, _ in failed_images
                    }
                    
                    for future in as_completed(future_to_file):
                        image_file, image_data, error = future.result()
                        if image_data:
                            uploaded_images.append((image_file, image_data))
                        else:
                            retry_failed.append((image_file, error))
                        retry_pbar.update(1)
            
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
        uploaded_size = sum(os.path.getsize(os.path.join(folder_path, img_file)) 
                           for img_file, _ in uploaded_images)
        total_size = sum(os.path.getsize(os.path.join(folder_path, img_file)) 
                        for img_file in image_files)
        transfer_speed = uploaded_size / upload_time if upload_time > 0 else 0
        
        # Calculate image dimension statistics
        image_dimensions = []
        for f in image_files:
            file_path = os.path.join(folder_path, f)
            try:
                from PIL import Image
                with Image.open(file_path) as img:
                    width, height = img.size
                    image_dimensions.append((width, height))
            except ImportError:
                image_dimensions.append((0, 0))  # PIL not available
            except Exception:
                image_dimensions.append((0, 0))  # Error reading image
        
        successful_dimensions = [image_dimensions[image_files.index(img_file)] 
                               for img_file, _ in uploaded_images]
        avg_width = sum(w for w, h in successful_dimensions) / len(successful_dimensions) if successful_dimensions else 0
        avg_height = sum(h for w, h in successful_dimensions) / len(successful_dimensions) if successful_dimensions else 0
        
        # Add statistics to results
        results.update({
            'gallery_id': gallery_id,
            'gallery_name': os.path.basename(folder_path),
            'upload_time': upload_time,
            'total_size': total_size,
            'uploaded_size': uploaded_size,
            'transfer_speed': transfer_speed,
            'avg_width': avg_width,
            'avg_height': avg_height,
            'successful_count': len(uploaded_images) + 1,  # +1 for the first image that created the gallery
            'failed_count': len(failed_images)
        })
        
        # Create gallery folder and files
        gallery_folder = os.path.join(folder_path, f"gallery_{gallery_id}")
        os.makedirs(gallery_folder, exist_ok=True)
        
        # Create shortcut file (.url) to the gallery
        shortcut_content = f"""[InternetShortcut]
URL=https://imx.to/g/{gallery_id}
"""
        shortcut_path = os.path.join(gallery_folder, f"gallery_{gallery_id}.url")
        with open(shortcut_path, 'w', encoding='utf-8') as f:
            f.write(shortcut_content)
        
        # Create .txt file with combined bbcode
        # replacement tags: #folderName #pictureCount #extension #width #height #folderSize# #allImages# #longestSide# #fileDownload# #cover# 
        
        bbcode_content = ""
        for image_data in results['images']:
            bbcode_content += image_data['bbcode'] + " "
        
        bbcode_path = os.path.join(gallery_folder, f"gallery_{gallery_id}_bbcode.txt")
        with open(bbcode_path, 'w', encoding='utf-8') as f:
            f.write(bbcode_content)
        
        # Also save to central location
        central_path = get_central_storage_path()
        folder_name = os.path.basename(folder_path)
        
        central_shortcut_path = os.path.join(central_path, f"{folder_name}.url")
        with open(central_shortcut_path, 'w', encoding='utf-8') as f:
            f.write(shortcut_content)
        
        central_bbcode_path = os.path.join(central_path, f"{folder_name}_bbcode.txt")
        with open(central_bbcode_path, 'w', encoding='utf-8') as f:
            f.write(bbcode_content)
        
        print(f"{timestamp()} Saved gallery files to central location: {central_path}")
        
        return results
    
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
    
    def upload_folder(self, folder_path, gallery_name=None, thumbnail_size=3, thumbnail_format=2, max_retries=3, public_gallery=1):
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
        
        # Create gallery (skip login since it's already done)
        gallery_id = self.create_gallery_with_name(gallery_name, public_gallery, skip_login=True)
        
        if not gallery_id:
            print("Failed to create named gallery, falling back to API-only upload...")
            # Fallback to API-only upload (no gallery naming)
            return self._upload_without_named_gallery(folder_path, image_files, thumbnail_size, thumbnail_format, max_retries)
        
        gallery_url = f"https://imx.to/g/{gallery_id}"
        
        # Store results
        results = {
            'gallery_url': gallery_url,
            'images': []
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
        
        # Main upload progress bar
        with tqdm(total=len(image_files), desc=f"Uploading to {gallery_name}", 
                 unit="img", leave=False) as pbar:
            
            # Process images in batches of 4 for concurrent uploads
            batch_size = 4
            for i in range(0, len(image_files), batch_size):
                batch = image_files[i:i + batch_size]
                
                # Upload batch concurrently
                with ThreadPoolExecutor(max_workers=batch_size) as executor:
                    # Submit all uploads in the batch
                    future_to_file = {
                        executor.submit(upload_single_image, image_file, 1, pbar): image_file 
                        for image_file in batch
                    }
                    
                    # Collect results as they complete
                    batch_results = []
                    for future in as_completed(future_to_file):
                        image_file, image_data, error = future.result()
                        batch_results.append((image_file, image_data, error))
                        pbar.update(1)
                
                # Process batch results
                for image_file, image_data, error in batch_results:
                    if image_data:
                        uploaded_images.append((image_file, image_data))
                    else:
                        failed_images.append((image_file, error))
        
        # Retry failed uploads with progress bar
        retry_count = 0
        while failed_images and retry_count < max_retries:
            retry_count += 1
            retry_failed = []
            
            with tqdm(total=len(failed_images), desc=f"Retry {retry_count}/{max_retries}", 
                     unit="img", leave=False) as retry_pbar:
                
                with ThreadPoolExecutor(max_workers=4) as executor:
                    future_to_file = {
                        executor.submit(upload_single_image, image_file, retry_count + 1, retry_pbar): image_file 
                        for image_file, _ in failed_images
                    }
                    
                    for future in as_completed(future_to_file):
                        image_file, image_data, error = future.result()
                        if image_data:
                            uploaded_images.append((image_file, image_data))
                        else:
                            retry_failed.append((image_file, error))
                        retry_pbar.update(1)
            
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
        uploaded_size = sum(os.path.getsize(os.path.join(folder_path, img_file)) 
                           for img_file, _ in uploaded_images)
        transfer_speed = uploaded_size / upload_time if upload_time > 0 else 0
        
        # Calculate image dimension statistics
        successful_dimensions = [image_dimensions[image_files.index(img_file)] 
                               for img_file, _ in uploaded_images]
        avg_width = sum(w for w, h in successful_dimensions) / len(successful_dimensions) if successful_dimensions else 0
        avg_height = sum(h for w, h in successful_dimensions) / len(successful_dimensions) if successful_dimensions else 0
        
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
            'successful_count': len(uploaded_images),
            'failed_count': len(failed_images)
        })
        
        # Create gallery folder and files
        gallery_folder = os.path.join(folder_path, f"gallery_{gallery_id}")
        os.makedirs(gallery_folder, exist_ok=True)
        
        # Create shortcut file (.url) to the gallery
        shortcut_content = f"""[InternetShortcut]
URL=https://imx.to/g/{gallery_id}
"""
        shortcut_path = os.path.join(gallery_folder, f"gallery_{gallery_id}.url")
        with open(shortcut_path, 'w', encoding='utf-8') as f:
            f.write(shortcut_content)
        
        # Create .txt file with combined bbcode
        bbcode_content = ""
        for image_data in results['images']:
            bbcode_content += image_data['bbcode'] + "\n"
        
        bbcode_path = os.path.join(gallery_folder, f"gallery_{gallery_id}_bbcode.txt")
        with open(bbcode_path, 'w', encoding='utf-8') as f:
            f.write(bbcode_content)
        
        # Also save to central location
        central_path = get_central_storage_path()
        folder_name = os.path.basename(folder_path)
        
        central_shortcut_path = os.path.join(central_path, f"{folder_name}.url")
        with open(central_shortcut_path, 'w', encoding='utf-8') as f:
            f.write(shortcut_content)
        
        central_bbcode_path = os.path.join(central_path, f"{folder_name}_bbcode.txt")
        with open(central_bbcode_path, 'w', encoding='utf-8') as f:
            f.write(bbcode_content)
        
        print(f"{timestamp()} Saved gallery files to central location: {central_path}")
        
        return results

def main():
    # Load user defaults
    user_defaults = load_user_defaults()
    
    parser = argparse.ArgumentParser(description='Upload image folders to imx.to as galleries')
    parser.add_argument('folder_paths', nargs='*', help='Paths to folders containing images')
    parser.add_argument('--name', help='Gallery name (optional, uses folder name if not specified)')
    parser.add_argument('--thumbnail-size', type=int, choices=[1, 2, 3, 4, 6], 
                       default=user_defaults.get('thumbnail_size', 3),
                       help='Thumbnail size: 1=100x100, 2=180x180, 3=250x250, 4=300x300, 6=150x150 (default: 3)')
    parser.add_argument('--thumbnail-format', type=int, choices=[1, 2, 3, 4], 
                       default=user_defaults.get('thumbnail_format', 2),
                       help='Thumbnail format: 1=Fixed width, 2=Proportional, 3=Square, 4=Fixed height (default: 2)')
    parser.add_argument('--max-retries', type=int, 
                       default=user_defaults.get('max_retries', 3), 
                       help='Maximum retry attempts for failed uploads (default: 3)')
    parser.add_argument('--public-gallery', type=int, choices=[0, 1], 
                       default=user_defaults.get('public_gallery', 1),
                       help='Gallery visibility: 0=private, 1=public (default: 1)')
    parser.add_argument('--private', action='store_true',
                       help='Make galleries private (overrides --public-gallery)')
    parser.add_argument('--public', action='store_true',
                       help='Make galleries public (overrides --public-gallery)')
    parser.add_argument('--setup-secure', action='store_true',
                       help='Set up secure password storage (interactive)')
    parser.add_argument('--rename-unnamed', action='store_true',
                       help='Rename all unnamed galleries from previous uploads')
    parser.add_argument('--use-async', action='store_true',
                       help='Use async upload implementation (experimental)')
    parser.add_argument('--max-concurrent', type=int, default=4,
                       help='Maximum concurrent uploads for async mode (default: 4)')
    parser.add_argument('--install-context-menu', action='store_true',
                       help='Install Windows context menu integration')
    parser.add_argument('--remove-context-menu', action='store_true',
                       help='Remove Windows context menu integration')
    
    args = parser.parse_args()
    
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
        
        # Process multiple galleries
        if args.use_async:
            # Use async uploader
            async_uploader = AsyncImxToUploader()
            
            async def upload_all_folders():
                for folder_path in expanded_paths:
                    gallery_name = args.name if args.name else None
                    
                    try:
                        results = await async_uploader.upload_folder_async(
                            folder_path,
                            gallery_name,
                            thumbnail_size=args.thumbnail_size,
                            thumbnail_format=args.thumbnail_format,
                            max_retries=args.max_retries,
                            public_gallery=public_gallery,
                            max_concurrent=args.max_concurrent
                        )
                        if results:
                            all_results.append(results)
                        
                    except Exception as e:
                        print(f"Error uploading {folder_path}: {str(e)}", file=sys.stderr)
                        continue
                
                return all_results
            
            # Run async upload
            all_results = asyncio.run(upload_all_folders())
        else:
            # Use sync uploader
            for folder_path in expanded_paths:
                gallery_name = args.name if args.name else None
                
                try:
                    results = uploader.upload_folder(
                        folder_path, 
                        gallery_name,
                        thumbnail_size=args.thumbnail_size,
                        thumbnail_format=args.thumbnail_format,
                        max_retries=args.max_retries,
                        public_gallery=public_gallery
                    )
                    all_results.append(results)
                    
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
            print(f"Total size: {total_size / (1024*1024):.1f} MB")
            print(f"Average speed: {(total_uploaded / total_time) / (1024*1024):.1f} MB/s" if total_time > 0 else "Average speed: 0 MB/s")
            
            for i, results in enumerate(all_results, 1):
                total_attempted = results['successful_count'] + results['failed_count']
                print(f"\nGallery {i}: {results['gallery_name']}")
                print(f"  URL: {results['gallery_url']}")
                print(f"  Images: {results['successful_count']}/{total_attempted}")
                print(f"  Time: {results['upload_time']:.1f}s")
                print(f"  Size: {results['uploaded_size'] / (1024*1024):.1f} MB")
                print(f"  Speed: {results['transfer_speed'] / (1024*1024):.1f} MB/s")
                
        else:
            print("No galleries were successfully uploaded.")
            
    except Exception as e:
        print(f"Error: {str(e)}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        # Handle argparse errors gracefully in PyInstaller
        pass
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)