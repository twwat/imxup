"""
Background worker for gallery renames - uses EXACT working code from ImxToUploader.
"""

import threading
import queue
import time
import requests
import configparser
import os
from src.utils.logger import log


class RenameWorker:
    """Background worker that handles gallery renames using its own web session."""

    def __init__(self):
        """Initialize RenameWorker with own web session."""
        # Import existing functions
        from imxup import (get_config_path, decrypt_password, get_firefox_cookies,
                          load_cookies_from_file, get_unnamed_galleries,
                          remove_unnamed_gallery, sanitize_gallery_name, get_credential)

        # Store references to these functions
        self._get_config_path = get_config_path
        self._decrypt_password = decrypt_password
        self._get_firefox_cookies = get_firefox_cookies
        self._load_cookies_from_file = load_cookies_from_file
        self._get_unnamed_galleries = get_unnamed_galleries
        self._remove_unnamed_gallery = remove_unnamed_gallery
        self._sanitize_gallery_name = sanitize_gallery_name

        # Queue for rename requests
        self.queue = queue.Queue()
        self.running = True

        # Web session and credentials
        self.username = None
        self.password = None
        self.web_url = "https://imx.to"
        self.session = None

        # Load credentials from QSettings (Registry)
        self.username = get_credential('username')
        encrypted_password = get_credential('password')
        if self.username and encrypted_password:
            self.password = decrypt_password(encrypted_password)

        # Create session using EXACT same setup as ImxToUploader
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        retry_strategy = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=1, pool_maxsize=1)

        self.session = requests.Session()
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:141.0) Gecko/20100101 Firefox/141.0',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US',
            'Accept-Encoding': 'gzip, deflate, br, zstd',
            'DNT': '1'
        })

        # Start background worker thread
        self.thread = threading.Thread(target=self._process_renames, daemon=True, name="RenameWorker")
        self.thread.start()

        # Login and auto-rename in background
        threading.Thread(target=self._initial_login, daemon=True).start()

    def _initial_login(self):
        """Login once and handle auto-rename of unnamed galleries."""
        if self.login():
            # Auto-rename unnamed galleries
            try:
                unnamed = self._get_unnamed_galleries()
                if unnamed:
                    log(f"Auto-renaming {len(unnamed)} galleries", category="renaming")
                    for gallery_id, gallery_name in list(unnamed.items()):
                        if self.rename_gallery_with_session(gallery_id, gallery_name):
                            self._remove_unnamed_gallery(gallery_id)
            except Exception as e:
                log(f"Auto-rename error: {e}", level="error", category="renaming")

    # EXACT COPY of ImxToUploader.login() - lines 985-1197 from imxup.py
    def login(self):
        """Login to imx.to web interface"""
        from src.network.cookies import get_firefox_cookies, load_cookies_from_file

        if not self.username or not self.password:
            # Try cookies only
            try:
                firefox_cookies = get_firefox_cookies("imx.to")
                file_cookies = load_cookies_from_file("cookies.txt")
                all_cookies = {}
                if firefox_cookies:
                    all_cookies.update(firefox_cookies)
                if file_cookies:
                    all_cookies.update(file_cookies)
                if all_cookies:
                    for name, cookie_data in all_cookies.items():
                        try:
                            self.session.cookies.set(name, cookie_data['value'], domain=cookie_data['domain'], path=cookie_data['path'])
                        except Exception:
                            pass
                    test_response = self.session.get(f"{self.web_url}/user/gallery/manage")
                    if 'login' not in test_response.url and 'DDoS-Guard' not in test_response.text:
                        log("Authenticated using cookies", category="auth")
                        return True
            except Exception:
                pass
            log("No credentials available", level="warning", category="auth")
            return False

        max_retries = 1
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    log(f"Retry attempt {attempt + 1}/{max_retries}", level="debug", category="auth")
                    time.sleep(1)

                # Try cookies first
                firefox_cookies = get_firefox_cookies("imx.to")
                file_cookies = load_cookies_from_file("cookies.txt")
                all_cookies = {}
                if firefox_cookies:
                    all_cookies.update(firefox_cookies)
                if file_cookies:
                    all_cookies.update(file_cookies)
                if all_cookies:
                    for name, cookie_data in all_cookies.items():
                        try:
                            self.session.cookies.set(name, cookie_data['value'], domain=cookie_data['domain'], path=cookie_data['path'])
                        except Exception:
                            pass
                    test_response = self.session.get(f"{self.web_url}/user/gallery/manage")
                    if 'login' not in test_response.url and 'DDoS-Guard' not in test_response.text:
                        log("Authenticated using cookies", category="auth")
                        return True

                # Submit login form
                login_data = {
                    'usr_email': self.username,
                    'pwd': self.password,
                    'remember': '1',
                    'doLogin': 'Login'
                }

                response = self.session.post(f"{self.web_url}/login.php", data=login_data)

                # Check if login was successful
                if 'user' in response.url or 'dashboard' in response.url or 'gallery' in response.url:
                    log("Authenticated using credentials", category="auth", level="info")
                    return True
                else:
                    log("Login failed (probably just hit DDoS-Guard, don't worry about this if you're sure the credentials are correct)", level="debug", category="auth")
                    if attempt < max_retries - 1:
                        continue
                    else:
                        return False

            except Exception as e:
                log(f"Login error: {str(e)}", level="error", category="auth")
                if attempt < max_retries - 1:
                    continue
                else:
                    return False

        return False

    # EXACT COPY of ImxToUploader.rename_gallery_with_session() - lines 1300-1365 from imxup.py
    def rename_gallery_with_session(self, gallery_id, new_name):
        """Rename gallery using existing session (no login call)"""
        try:
            # Sanitize the gallery name
            original_name = new_name
            new_name = self._sanitize_gallery_name(new_name)
            if original_name != new_name:
                log(f"Sanitized '{original_name}' -> '{new_name}'", level="debug", category="renaming")

            # Get the edit gallery page
            edit_page = self.session.get(f"{self.web_url}/user/gallery/edit?id={gallery_id}")

            # Check if we can access the edit page
            if edit_page.status_code != 200:
                log(f"Cannot access edit page (HTTP {edit_page.status_code})", level="error", category="renaming")
                return False

            if 'DDoS-Guard' in edit_page.text:
                log("DDoS-Guard detected", level="warning", category="renaming")
                return False

            if 'login' in edit_page.url or 'login' in edit_page.text.lower():
                log("Not logged in", level="warning", category="renaming")
                return False

            # Submit gallery rename form
            rename_data = {
                'gallery_name': new_name,
                'submit_new_gallery': 'Rename Gallery',
            }

            response = self.session.post(f"{self.web_url}/user/gallery/edit?id={gallery_id}", data=rename_data)

            if response.status_code == 200:
                log(f"Successfully renamed gallery '{gallery_id}' to '{new_name}'", category="renaming")
                return True
            else:
                log(f"Rename failed (HTTP {response.status_code})", level="error", category="renaming")
                return False

        except Exception as e:
            log(f"Error renaming gallery: {str(e)}", level="error", category="renaming")
            return False

    def queue_rename(self, gallery_id: str, gallery_name: str):
        """Queue a rename request."""
        if gallery_id and gallery_name:
            self.queue.put({'gallery_id': gallery_id, 'gallery_name': gallery_name})

    def _process_renames(self):
        """Background thread that processes rename queue."""
        from imxup import save_unnamed_gallery

        while self.running:
            try:
                request = self.queue.get(timeout=1.0)
                if request is None:
                    break

                gallery_id = request['gallery_id']
                gallery_name = request['gallery_name']

                # Attempt rename
                success = self.rename_gallery_with_session(gallery_id, gallery_name)

                if success:
                    # Remove from unnamed list
                    try:
                        self._remove_unnamed_gallery(gallery_id)
                    except Exception:
                        pass
                else:
                    # Queue for later auto-rename
                    try:
                        save_unnamed_gallery(gallery_id, gallery_name)
                        log(f"Queued for auto-rename: '{gallery_name}'", level="debug", category="renaming")
                    except Exception as e:
                        log(f"Failed to queue for auto-rename: {e}", level="error", category="renaming")

                self.queue.task_done()

            except queue.Empty:
                continue
            except Exception as e:
                log(f"RenameWorker error: {e}", level="error", category="renaming")
                continue

    def stop(self, timeout: float = 5.0):
        """Stop the rename worker."""
        self.running = False
        try:
            self.queue.put(None)
        except Exception:
            pass
        if self.thread.is_alive():
            self.thread.join(timeout=timeout)
        if self.session:
            try:
                self.session.close()
            except Exception:
                pass

    def is_running(self) -> bool:
        """Check if worker is running."""
        return self.running and self.thread.is_alive()

    def queue_size(self) -> int:
        """Get queue size."""
        return self.queue.qsize()
