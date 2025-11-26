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

        # Instance tracking for diagnostics
        self._instance_id = id(self)
        log(f"RenameWorker instance created (ID: {self._instance_id})", level="debug", category="renaming")

        # Queue for rename requests
        self.queue = queue.Queue()
        self.running = True

        # Login synchronization
        self.login_complete = threading.Event()
        self.login_successful = False

        # Re-authentication rate limiting (prevent auth storms)
        self.reauth_lock = threading.Lock()
        self.last_reauth_attempt = 0
        self.min_reauth_interval = 5.0  # Minimum 5 seconds between re-auth attempts
        self.reauth_in_progress = False

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
        self._session_id = id(self.session)
        log(f"RenameWorker (ID {self._instance_id}) created session #{self._session_id}", level="debug", category="renaming")

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

    def _attempt_reauth_with_rate_limit(self) -> bool:
        """
        Attempt re-authentication with rate limiting to prevent auth storms.

        When session expires (403), multiple galleries may try to re-auth simultaneously.
        This method ensures only one re-auth happens at a time with minimum 5s between attempts.

        Returns:
            True if re-authentication succeeded, False otherwise
        """
        current_time = time.time()

        with self.reauth_lock:
            # Check if another thread is already re-authenticating
            if self.reauth_in_progress:
                log("Another thread is already re-authenticating, waiting...", level="debug", category="renaming")
                # Release lock and wait a bit for the other thread to finish
                time.sleep(0.5)
                # Check if that thread succeeded
                return self.login_successful

            # Check if we attempted re-auth too recently
            time_since_last = current_time - self.last_reauth_attempt
            if time_since_last < self.min_reauth_interval:
                log(f"Re-auth attempted {time_since_last:.1f}s ago, waiting {self.min_reauth_interval}s between attempts",
                    level="debug", category="auth")
                return False

            # Mark re-auth in progress
            self.reauth_in_progress = True
            self.last_reauth_attempt = current_time

        try:
            log("Attempting rate-limited re-authentication", level="debug", category="auth")
            success = self.login()
            self.login_successful = success
            if success:
                log("Re-authentication successful", level="info", category="auth")
            else:
                log("Re-authentication failed - session will remain unauthenticated", level="debug", category="auth")
            return success
        finally:
            with self.reauth_lock:
                self.reauth_in_progress = False

    def _initial_login(self):
        """Login once and handle auto-rename of unnamed galleries."""
        try:
            self.login_successful = self.login()

            if self.login_successful:
                log("RenameWorker login successful", level="debug", category="renaming")
                # Auto-rename unnamed galleries
                try:
                    unnamed = self._get_unnamed_galleries()
                    if unnamed:
                        log(f"Auto-renaming {len(unnamed)} galleries", category="renaming", level="info")
                        for gallery_id, gallery_name in list(unnamed.items()):
                            if self.rename_gallery_with_session(gallery_id, gallery_name):
                                self._remove_unnamed_gallery(gallery_id)
                except Exception as e:
                    log(f"ERROR: Auto-rename error: {e}", level="error", category="renaming")
            else:
                log("RenameWorker login failed: galleries queued for later renaming", level="debug", category="renaming")
        finally:
            # Signal that login attempt is complete (success or failure)
            self.login_complete.set()

    # Login with DDoS-Guard bypass support
    def login(self):
        """Login to imx.to web interface with DDoS-Guard bypass"""
        from src.network.cookies import get_firefox_cookies, load_cookies_from_file
        #from src.utils.ddos_bypass import get_ddos_bypass

        # Define required secure cookies for imx.to authentication
        REQUIRED_COOKIES = ["continue", "PHPSESSID", "user_id", "user_key", "user_name"]

        if not self.username or not self.password:
            # Try cookies only
            try:
                firefox_cookies = get_firefox_cookies("imx.to", cookie_names=REQUIRED_COOKIES)
                file_cookies = load_cookies_from_file("cookies.txt")
                all_cookies = {}
                if firefox_cookies:
                    all_cookies.update(firefox_cookies)
                if file_cookies:
                    all_cookies.update(file_cookies)
                if all_cookies:
                    log(f"RenameWorker (no credentials) found {len(all_cookies)} cookies (Firefox: {len(firefox_cookies or {})}, File: {len(file_cookies or {})}), attempting cookie auth", level="debug", category="auth")
                    for name, cookie_data in all_cookies.items():
                        try:
                            self.session.cookies.set(
                                name,
                                cookie_data['value'],
                                domain=cookie_data['domain'],
                                path=cookie_data['path'],
                                secure=cookie_data.get('secure', False)  # CRITICAL: Match Firefox cookie's secure flag
                            )
                        except Exception:
                            pass
                    test_response = self.session.get(f"{self.web_url}/user/gallery/manage")
                    if 'login' not in test_response.url and 'DDoS-Guard' not in test_response.text:
                        log("RenameWorker authenticated using cookies", category="auth", level="info")
                        return True
                    else:
                        log(f"RenameWorker cookie auth failed (test URL: {test_response.url})", level="debug", category="auth")
            except Exception as e:
                log(f"RenameWorker cookie auth exception: {e}", level="debug", category="auth")
            log("No credentials available for RenameWorker", level="info", category="auth")
            return False

        max_retries = 1
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    log(f"RenameWorker login retry {attempt + 1}/{max_retries}", level="debug", category="auth")
                    time.sleep(1)

                # Try cookies first (using same REQUIRED_COOKIES from above)
                firefox_cookies = get_firefox_cookies("imx.to", cookie_names=REQUIRED_COOKIES)
                file_cookies = load_cookies_from_file("cookies.txt")
                all_cookies = {}
                if firefox_cookies:
                    all_cookies.update(firefox_cookies)
                if file_cookies:
                    all_cookies.update(file_cookies)

                if all_cookies:
                    log(f"RenameWorker found {len(all_cookies)} cookies (Firefox: {len(firefox_cookies or {})}, File: {len(file_cookies or {})}), attempting cookie auth", level="debug", category="auth")
                    for name, cookie_data in all_cookies.items():
                        try:
                            self.session.cookies.set(
                                name,
                                cookie_data['value'],
                                domain=cookie_data['domain'],
                                path=cookie_data['path'],
                                secure=cookie_data.get('secure', False)  # CRITICAL: Match Firefox cookie's secure flag
                            )
                        except Exception:
                            pass
                    test_response = self.session.get(f"{self.web_url}/user/gallery/manage")
                    if 'login' not in test_response.url and 'DDoS-Guard' not in test_response.text:
                        log("RenameWorker authenticated using cookies", category="auth", level="info")
                        return True
                    else:
                        log(f"RenameWorker cookie auth failed (test URL: {test_response.url}, has DDoS-Guard: {'DDoS-Guard' in test_response.text}), falling back to credentials", level="debug", category="auth")
                else:
                    log("RenameWorker: no cookies found, will use credentials", level="debug", category="auth")

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
                    log("DDoS-Guard detected: galleries will be queued for auto-rename", level="info", category="auth")
                    # Note: axios-ddos-guard-bypass has a bug where it doesn't maintain
                    # session cookies (PHPSESSID) when the interceptor triggers, causing
                    # login failures. Rather than fight a buggy library, we queue galleries
                    # for auto-rename on next startup when DDoS-Guard isn't active.
                    if attempt < max_retries - 1:
                        continue
                    else:
                        return False

                # Check if login was successful
                if 'user' in response.url or 'dashboard' in response.url or 'gallery' in response.url:
                    log("RenameWorker authenticated using credentials", category="auth", level="info")
                    return True
                else:
                    log("RenameWorker credential login failed", level="debug", category="auth")
                    if attempt < max_retries - 1:
                        continue
                    else:
                        return False

            except Exception as e:
                log(f"ERROR: RenameWorker login error: {str(e)}", level="error", category="auth")
                if attempt < max_retries - 1:
                    continue
                else:
                    return False

        return False

    # EXACT COPY of ImxToUploader.rename_gallery_with_session() - lines 1300-1365 from imxup.py
    def rename_gallery_with_session(self, gallery_id, new_name, retry_on_auth_failure=True):
        """Rename gallery using existing session (will re-login on 403)"""
        log(f"RenameWorker (ID: {self._instance_id}) using session {id(self.session)} for rename of {gallery_id} ({new_name})", level="debug", category="renaming")
        try:
            # Sanitize the gallery name
            original_name = new_name
            new_name = self._sanitize_gallery_name(new_name)
            if original_name != new_name:
                log(f"Sanitized '{original_name}' -> '{new_name}'", level="debug", category="renaming")

            # Get the edit gallery page
            edit_page = self.session.get(f"{self.web_url}/user/gallery/edit?id={gallery_id}")

            # Check if we can access the edit page
            if edit_page.status_code == 403:
                log(f"DEBUG: Authentication expired (HTTP 403)", level="debug", category="renaming")
                # Try re-auth with rate limiting to prevent auth storms
                if retry_on_auth_failure and self._attempt_reauth_with_rate_limit():
                    log("Re-authenticated successfully, retrying rename", level="info", category="renaming")
                    return self.rename_gallery_with_session(gallery_id, new_name, retry_on_auth_failure=False)
                else:
                    log("Re-authentication failed - marking session as dead", level="debug", category="renaming")
                    self.login_successful = False  # Mark session as dead to stop queue processing
                    return False

            if edit_page.status_code != 200:
                log(f"Cannot access edit page (HTTP {edit_page.status_code})", level="debug", category="renaming")
                return False

            if 'DDoS-Guard' in edit_page.text:
                log("DDoS-Guard detected", level="warning", category="renaming")
                return False

            if 'login' in edit_page.url or 'login' in edit_page.text.lower():
                log("Not logged in - attempting re-authentication", level="warning", category="renaming")
                if retry_on_auth_failure and self._attempt_reauth_with_rate_limit():
                    return self.rename_gallery_with_session(gallery_id, new_name, retry_on_auth_failure=False)
                else:
                    log("Re-authentication failed - marking session as dead", level="warning", category="renaming")
                    self.login_successful = False  # Mark session as dead to stop queue processing
                return False

            # Submit gallery rename form
            rename_data = {
                'gallery_name': new_name,
                'submit_new_gallery': 'Rename Gallery',
            }

            response = self.session.post(f"{self.web_url}/user/gallery/edit?id={gallery_id}", data=rename_data)

            if response.status_code == 200:
                log(f"Successfully renamed gallery '{gallery_id}' to '{new_name}'", category="renaming", level="info")
                return True
            else:
                log(f"DEBUG: Rename failed (HTTP {response.status_code})", level="debug", category="renaming")
                return False

        except Exception as e:
            log(f"Error renaming gallery: {str(e)}", level="debug", category="renaming")
            return False

    def queue_rename(self, gallery_id: str, gallery_name: str):
        """Queue a rename request."""
        log(f"RenameWorker {self._instance_id} queue_rename called for '{gallery_name}' ({gallery_id})", level="trace", category="renaming")
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

                # Wait for initial login to complete (max 30 seconds)
                if not self.login_complete.wait(timeout=30):
                    log("Login timeout - queuing for later", level="debug", category="renaming")
                    try:
                        save_unnamed_gallery(gallery_id, gallery_name)
                    except Exception as e:
                        log(f"Failed to queue for auto-rename: {e}", level="error", category="renaming")
                    self.queue.task_done()
                    continue

                # If login failed, queue for later
                if not self.login_successful:
                    log("Not authenticated - queuing for later", level="debug", category="renaming")
                    try:
                        save_unnamed_gallery(gallery_id, gallery_name)
                    except Exception as e:
                        log(f"Failed to queue for auto-rename: {e}", level="error", category="renaming")
                    self.queue.task_done()
                    continue

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
                    except Exception as e:
                        log(f"Failed to queue for auto-rename: {e}", level="error", category="renaming")

                    # If authentication is dead, stop processing queue to avoid hammering server
                    if not self.login_successful:
                        log("Authentication failed - stopping queue processing and saving remaining galleries", level="warning", category="renaming")
                        self.queue.task_done()

                        # Drain remaining queue and save all for later
                        while not self.queue.empty():
                            try:
                                remaining = self.queue.get_nowait()
                                if remaining:
                                    save_unnamed_gallery(remaining['gallery_id'], remaining['gallery_name'])
                                self.queue.task_done()
                            except queue.Empty:
                                break
                        break  # Exit processing loop

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
