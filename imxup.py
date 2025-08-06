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
        
        # Create registry entries for command line upload
        key_path = r"Directory\Background\shell\UploadToImx"
        key = winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, key_path)
        winreg.SetValue(key, "", winreg.REG_SZ, "Upload to imx.to")
        
        # Create command
        command_key = winreg.CreateKey(key, "command")
        winreg.SetValue(command_key, "", winreg.REG_SZ, f'"{exe_path}" "%V"')
        
        winreg.CloseKey(command_key)
        winreg.CloseKey(key)
        
        # Create registry entries for GUI mode
        gui_key_path = r"Directory\Background\shell\UploadToImxGUI"
        gui_key = winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, gui_key_path)
        winreg.SetValue(gui_key, "", winreg.REG_SZ, "Upload to imx.to (GUI)")
        
        # Create GUI command
        gui_command_key = winreg.CreateKey(gui_key, "command")
        winreg.SetValue(gui_command_key, "", winreg.REG_SZ, f'"{exe_path}" --gui "%V"')
        
        winreg.CloseKey(gui_command_key)
        winreg.CloseKey(gui_key)
        
        print(f"Context menu created successfully!")
        print(f"Right-click on any folder and select:")
        print(f"  - 'Upload to imx.to' for command line mode")
        print(f"  - 'Upload to imx.to (GUI)' for graphical interface")
        return True
        
    except Exception as e:
        print(f"Error creating context menu: {e}")
        return False

def remove_windows_context_menu():
    """Remove Windows context menu integration"""
    try:
        # Remove command line context menu
        try:
            key_path = r"Directory\Background\shell\UploadToImx"
            winreg.DeleteKey(winreg.HKEY_CLASSES_ROOT, key_path + r"\command")
            winreg.DeleteKey(winreg.HKEY_CLASSES_ROOT, key_path)
        except FileNotFoundError:
            pass  # Key doesn't exist
        
        # Remove GUI context menu
        try:
            gui_key_path = r"Directory\Background\shell\UploadToImxGUI"
            winreg.DeleteKey(winreg.HKEY_CLASSES_ROOT, gui_key_path + r"\command")
            winreg.DeleteKey(winreg.HKEY_CLASSES_ROOT, gui_key_path)
        except FileNotFoundError:
            pass  # Key doesn't exist
        
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
        print("You can test the credentials by running an upload.")
        return True
    else:
        print("[ERROR] Failed to save credentials.")
        return False

def _save_credentials(username, password):
    """Save credentials to config file"""
    config = configparser.ConfigParser()
    config_file = os.path.join(os.path.expanduser("~"), ".imxup.ini")
    
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
    config_file = os.path.join(os.path.expanduser("~"), ".imxup.ini")
    
    if os.path.exists(config_file):
        config.read(config_file)
    
    if 'UNNAMED_GALLERIES' not in config:
        config['UNNAMED_GALLERIES'] = {}
    
    config['UNNAMED_GALLERIES'][gallery_id] = intended_name
    
    with open(config_file, 'w') as f:
        config.write(f)
    
    print(f"Saved unnamed gallery {gallery_id} for later renaming to '{intended_name}'")

def get_central_storage_path():
    """Get central storage path for gallery files"""
    central_path = os.path.join(os.path.expanduser("~"), "imxup_galleries")
    os.makedirs(central_path, exist_ok=True)
    return central_path

def sanitize_gallery_name(name):
    """Remove invalid characters from gallery name"""
    import re
    # Keep alphanumeric, spaces, hyphens, dashes, round brackets
    # Remove everything else (square brackets, periods, number signs, etc.)
    sanitized = re.sub(r'[^a-zA-Z0-9\s\-\(\)]', '', name)
    # Remove multiple spaces
    sanitized = re.sub(r'\s+', ' ', sanitized)
    # Trim spaces
    sanitized = sanitized.strip()
    return sanitized

def check_if_gallery_exists(folder_name):
    """Check if gallery files already exist for this folder"""
    central_path = get_central_storage_path()
    
    # Check central location
    central_files = [
        os.path.join(central_path, f"{folder_name}.url"),
        os.path.join(central_path, f"{folder_name}_bbcode.txt")
    ]
    
    # Check folder location
    folder_files = [
        os.path.join(folder_name, f"gallery_*.url"),
        os.path.join(folder_name, f"gallery_*_bbcode.txt")
    ]
    
    existing_files = []
    for file_path in central_files:
        if os.path.exists(file_path):
            existing_files.append(file_path)
    
    for pattern in folder_files:
        if glob.glob(pattern):
            existing_files.extend(glob.glob(pattern))
    
    return existing_files

def get_unnamed_galleries():
    """Get list of unnamed galleries"""
    config = configparser.ConfigParser()
    config_file = os.path.join(os.path.expanduser("~"), ".imxup.ini")
    
    if os.path.exists(config_file):
        config.read(config_file)
        if 'UNNAMED_GALLERIES' in config:
            return dict(config['UNNAMED_GALLERIES'])
    return {}

def remove_unnamed_gallery(gallery_id):
    """Remove gallery from unnamed list after successful renaming"""
    config = configparser.ConfigParser()
    config_file = os.path.join(os.path.expanduser("~"), ".imxup.ini")
    
    if os.path.exists(config_file):
        config.read(config_file)
        
        if 'UNNAMED_GALLERIES' in config and gallery_id in config['UNNAMED_GALLERIES']:
            del config['UNNAMED_GALLERIES'][gallery_id]
            
            with open(config_file, 'w') as f:
                config.write(f)
            
            print(f"{timestamp()} Removed {gallery_id} from unnamed galleries list")

def get_firefox_cookies(domain="imx.to"):
    """Extract cookies from Firefox browser for the given domain"""
    try:
        # Find Firefox profile directory
        if platform.system() == "Windows":
            firefox_dir = os.path.join(os.environ['APPDATA'], 'Mozilla', 'Firefox', 'Profiles')
        else:
            firefox_dir = os.path.join(os.path.expanduser("~"), '.mozilla', 'firefox')
        
        if not os.path.exists(firefox_dir):
            print(f"Firefox profiles directory not found: {firefox_dir}")
            return {}
        
        # Find the default profile (usually ends with .default-release)
        profiles = [d for d in os.listdir(firefox_dir) if d.endswith('.default-release')]
        if not profiles:
            # Try any profile that contains 'default'
            profiles = [d for d in os.listdir(firefox_dir) if 'default' in d]
        
        if not profiles:
            print(f"{timestamp()} No Firefox profile found")
            return {}
        
        profile_dir = os.path.join(firefox_dir, profiles[0])
        cookie_file = os.path.join(profile_dir, 'cookies.sqlite')
        
        if not os.path.exists(cookie_file):
            print(f"{timestamp()} Firefox cookie file not found: {cookie_file}")
            return {}
        
        # Extract cookies from the database
        cookies = {}
        conn = sqlite3.connect(cookie_file)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT name, value, host, path, expiry, isSecure
            FROM moz_cookies 
            WHERE host LIKE ?
        """, (f'%{domain}%',))
        
        for row in cursor.fetchall():
            name, value, host, path, expires, secure = row
            cookies[name] = {
                'value': value,
                'domain': host,
                'path': path,
                'secure': bool(secure)
            }
        
        conn.close()
        
        return cookies
        
    except Exception as e:
        print(f"{timestamp()} Error extracting Firefox cookies: {e}")
        return {}

def load_cookies_from_file(cookie_file="cookies.txt"):
    """Load cookies from a text file in Netscape format"""
    cookies = {}
    try:
        if os.path.exists(cookie_file):
            with open(cookie_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '\t' in line:
                        parts = line.split('\t')
                        if len(parts) >= 7 and 'imx.to' in parts[0]:
                            domain, subdomain, path, secure, expiry, name, value = parts[:7]
                            cookies[name] = {
                                'value': value,
                                'domain': domain,
                                'path': path,
                                'secure': secure == 'TRUE'
                            }
            print(f"{timestamp()} Loaded {len(cookies)} cookies from {cookie_file}")
        else:
            print(f"{timestamp()} Cookie file not found: {cookie_file}")
    except Exception as e:
        print(f"{timestamp()} Error loading cookies: {e}")
    return cookies

class ImxToUploader:
    def _get_credentials(self):
        """Get username and password from stored config"""
        config = configparser.ConfigParser()
        config_file = os.path.join(os.path.expanduser("~"), ".imxup.ini")
        
        if os.path.exists(config_file):
            config.read(config_file)
            if 'CREDENTIALS' in config:
                username = config['CREDENTIALS'].get('username')
                encrypted_password = config['CREDENTIALS'].get('password', '')
                
                if username and encrypted_password:
                    password = decrypt_password(encrypted_password)
                    if password:
                        return username, password
        
        return None, None
    
    def __init__(self):
        self.api_key = os.getenv('IMX_API')
        
        if not self.api_key:
            raise ValueError("IMX_API key not found in environment variables")
        
        # Get credentials from stored config
        self.username, self.password = self._get_credentials()
        
        if not self.username or not self.password:
            print(f"{timestamp()} Failed to get credentials. Please run --setup-secure first.")
            sys.exit(1)
        
        self.base_url = "https://api.imx.to/v1"
        self.web_url = "https://imx.to"
        self.upload_url = f"{self.base_url}/upload.php"
        self.headers = {
            "X-API-Key": self.api_key
        }
        
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

    parser.add_argument('--install-context-menu', action='store_true',
                       help='Install Windows context menu integration')
    parser.add_argument('--remove-context-menu', action='store_true',
                       help='Remove Windows context menu integration')
    parser.add_argument('--gui', action='store_true',
                       help='Launch graphical user interface')
    
    args = parser.parse_args()
    
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
        
        # Process multiple galleries
        for folder_path in expanded_paths:
            # Use folder name as gallery name if not specified
            gallery_name = args.name if args.name else None
            
            try:
                print(f"{timestamp()} Starting upload: {os.path.basename(folder_path)}")
                results = uploader.upload_folder(
                    folder_path, 
                    gallery_name,
                    thumbnail_size=args.thumbnail_size,
                    thumbnail_format=args.thumbnail_format,
                    max_retries=args.max_retries,
                    public_gallery=public_gallery
                )
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
    except KeyboardInterrupt:
        print("\nExiting gracefully...")
        sys.exit(0)
    except SystemExit:
        # Handle argparse errors gracefully in PyInstaller
        pass
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)