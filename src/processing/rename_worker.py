"""
Background worker for gallery renames and image status checking.

Uses EXACT working code from ImxToUploader for renames.
Extends with image status checking via imx.to/user/moderate endpoint.
"""

import threading
import queue
import time
import requests
import configparser
import os
from typing import List, Dict, Callable, Optional, Any
from PyQt6.QtCore import QObject, pyqtSignal
from src.utils.logger import log


def save_session_cookies_to_keyring(session_cookies):
    """Save session cookies to OS keyring for reuse across sessions.

    Stores cookies as JSON string under the 'imxup' service with 48-hour expiry.
    """
    import json
    try:
        import keyring
        # Extract required cookies
        required = ["continue", "PHPSESSID", "user_id", "user_key", "user_name"]
        cookies_dict = {}
        for cookie in session_cookies:
            if cookie.name in required:
                cookies_dict[cookie.name] = {
                    'value': cookie.value,
                    'domain': cookie.domain,
                    'path': cookie.path,
                    'secure': cookie.secure,
                    'expiry': int(time.time()) + 172800  # 48 hours
                }
        if cookies_dict:
            keyring.set_password("imxup", "session_cookies", json.dumps(cookies_dict))
            log("Session cookies saved to keyring", level="debug", category="auth")
    except ImportError:
        log("keyring not available, cookies not saved", level="debug", category="auth")
    except Exception as e:
        log(f"Failed to save cookies to keyring: {e}", level="debug", category="auth")


def load_session_cookies_from_keyring():
    """Load session cookies from OS keyring.

    Returns dict of valid, non-expired cookie data or empty dict if not found.
    Validates JSON structure and filters out expired cookies.
    """
    import json
    try:
        import keyring
        cookies_json = keyring.get_password("imxup", "session_cookies")
        if cookies_json:
            try:
                cookies = json.loads(cookies_json)
                if not isinstance(cookies, dict):
                    log("Invalid keyring cookie format (not a dict), clearing", level="debug", category="auth")
                    clear_session_cookies_from_keyring()
                    return {}

                # Validate and filter expired cookies
                current_time = int(time.time())
                valid_cookies = {}
                for name, data in cookies.items():
                    if not isinstance(data, dict):
                        continue
                    if not all(k in data for k in ['value', 'domain', 'path']):
                        continue
                    if data.get('expiry', 0) <= current_time:
                        continue
                    valid_cookies[name] = data

                if not valid_cookies:
                    log("All keyring cookies expired, clearing", level="debug", category="auth")
                    clear_session_cookies_from_keyring()
                    return {}

                log(f"Loaded {len(valid_cookies)} valid session cookies from keyring", level="debug", category="auth")
                return valid_cookies
            except json.JSONDecodeError as e:
                log(f"Corrupted keyring cookie data (JSON error: {e}), clearing", level="debug", category="auth")
                clear_session_cookies_from_keyring()
                return {}
    except ImportError:
        pass
    except Exception as e:
        log(f"Failed to load cookies from keyring: {e}", level="debug", category="auth")
    return {}


def clear_session_cookies_from_keyring():
    """Clear stored session cookies from keyring."""
    try:
        import keyring
        keyring.delete_password("imxup", "session_cookies")
        log("Cleared session cookies from keyring", level="debug", category="auth")
    except Exception:
        pass


class RenameWorker(QObject):
    """Background worker that handles gallery renames and image status checking on imx.to.

    Uses its own web session for authentication to imx.to.
    Supports both rename operations and image status checking via the /user/moderate endpoint.
    """

    # Status check signals (thread-safe cross-thread communication)
    status_check_progress = pyqtSignal(int, int)  # current, total
    status_check_completed = pyqtSignal(dict)     # results dict
    status_check_error = pyqtSignal(str)          # error_message

    def __init__(self):
        """Initialize RenameWorker with own web session.

        Sets up:
        - Credential loading from keyring/QSettings
        - HTTP session with retry strategy
        - Queue for rename requests
        - Queue for status check requests
        - Signals for status check progress/completion/error
        """
        super().__init__()
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

        # Queue for status check requests (separate from renames)
        self.status_check_queue: queue.Queue = queue.Queue()

        # Cancellation flag for status check operations (thread-safe)
        self._status_check_cancelled = threading.Event()

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

        # Start status check worker thread
        self.status_check_thread = threading.Thread(
            target=self._process_status_checks, daemon=True, name="StatusCheckWorker"
        )
        self.status_check_thread.start()

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
            # Try keyring cookies first (from previous successful login)
            keyring_cookies = load_session_cookies_from_keyring()
            if keyring_cookies:
                for name, cookie_data in keyring_cookies.items():
                    try:
                        self.session.cookies.set(
                            name,
                            cookie_data['value'],
                            domain=cookie_data['domain'],
                            path=cookie_data['path'],
                            secure=cookie_data.get('secure', False)
                        )
                    except Exception as e:
                        log(f"Cookie operation failed: {e}", level="debug", category="rename_worker")

                # Test if keyring cookies work
                test_response = self.session.get(f"{self.web_url}/user/gallery/manage")
                if 'login' not in test_response.url and 'DDoS-Guard' not in test_response.text:
                    log("RenameWorker (no credentials) authenticated using keyring cookies", category="auth", level="info")
                    return True
                else:
                    log("Keyring cookies expired, trying other methods", level="debug", category="auth")
                    self.session.cookies.clear()  # Clear expired cookies

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
                        except Exception as e:
                            log(f"Cookie operation failed: {e}", level="debug", category="rename_worker")
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

                # Try keyring cookies first (from previous successful login)
                keyring_cookies = load_session_cookies_from_keyring()
                if keyring_cookies:
                    for name, cookie_data in keyring_cookies.items():
                        try:
                            self.session.cookies.set(
                                name,
                                cookie_data['value'],
                                domain=cookie_data['domain'],
                                path=cookie_data['path'],
                                secure=cookie_data.get('secure', False)
                            )
                        except Exception as e:
                            log(f"Cookie operation failed: {e}", level="debug", category="rename_worker")

                    # Test if keyring cookies work
                    test_response = self.session.get(f"{self.web_url}/user/gallery/manage")
                    if 'login' not in test_response.url and 'DDoS-Guard' not in test_response.text:
                        log("RenameWorker authenticated using keyring cookies", category="auth", level="info")
                        return True
                    else:
                        log("Keyring cookies expired, trying other methods", level="debug", category="auth")
                        self.session.cookies.clear()  # Clear expired cookies

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
                        except Exception as e:
                            log(f"Cookie operation failed: {e}", level="debug", category="rename_worker")
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
                    # Save session cookies to keyring for next time
                    save_session_cookies_to_keyring(self.session.cookies)
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

    # =========================================================================
    # Image Status Checking Methods
    # =========================================================================

    def cancel_status_check(self) -> None:
        """Cancel any in-progress status check."""
        self._status_check_cancelled.set()

    def check_image_status(self, galleries_data: List[Dict[str, Any]]) -> None:
        """Queue image status check for multiple galleries.

        Collects all image URLs from galleries and checks their online status
        via imx.to/moderate endpoint. Results are returned via signals.

        Args:
            galleries_data: List of dicts, each containing:
                - db_id: int - Database ID of gallery
                - path: str - Gallery path (used as key in results)
                - name: str - Gallery display name
                - image_urls: List[str] - List of imx.to image URLs

        Results are delivered via the status_check_completed signal with structure:
            {
                path: {
                    "db_id": int,
                    "name": str,
                    "total": int,
                    "online": int,
                    "offline": int,
                    "online_urls": List[str],
                    "offline_urls": List[str]
                },
                ...
            }
        """
        if not galleries_data:
            log("check_image_status called with empty galleries_data", level="debug", category="status_check")
            self.status_check_completed.emit({})
            return

        # Queue the status check request
        self.status_check_queue.put(galleries_data)
        log(f"Queued status check for {len(galleries_data)} galleries", level="debug", category="status_check")

    def _process_status_checks(self) -> None:
        """Background thread that processes status check queue.

        Waits for login, then processes status check requests one at a time.
        Uses the same session as rename operations.
        """
        while self.running:
            try:
                # Wait for a status check request (timeout allows checking self.running)
                try:
                    galleries_data = self.status_check_queue.get(timeout=1.0)
                except queue.Empty:
                    continue

                if galleries_data is None:
                    # Shutdown signal
                    break

                # Wait for login to complete before processing
                if not self.login_complete.wait(timeout=30):
                    log("Status check: Login timeout", level="warning", category="status_check")
                    self.status_check_error.emit("Login timeout - please try again later")
                    self.status_check_queue.task_done()
                    continue

                if not self.login_successful:
                    log("Status check: Not authenticated", level="warning", category="status_check")
                    self.status_check_error.emit("Not authenticated - please login first")
                    self.status_check_queue.task_done()
                    continue

                # Perform the status check
                try:
                    results = self._perform_status_check(galleries_data)
                    self.status_check_completed.emit(results)
                except Exception as e:
                    log(f"Status check error: {e}", level="error", category="status_check")
                    self.status_check_error.emit(str(e))

                self.status_check_queue.task_done()

            except Exception as e:
                log(f"StatusCheckWorker error: {e}", level="error", category="status_check")
                continue

    def _perform_status_check(self, galleries_data: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """Perform the actual status check against imx.to/user/moderate.

        Args:
            galleries_data: List of gallery dicts with image_urls

        Returns:
            Dict mapping gallery path to status results

        Raises:
            Exception: On network or parsing errors
        """
        # Reset cancellation flag at start
        self._status_check_cancelled.clear()

        # Collect all URLs and build mapping back to galleries
        all_urls: List[str] = []
        url_to_gallery: Dict[str, str] = {}  # URL -> gallery path
        gallery_info: Dict[str, Dict[str, Any]] = {}  # path -> {db_id, name, urls}

        for gallery in galleries_data:
            path = gallery.get('path', '')
            db_id = gallery.get('db_id', 0)
            name = gallery.get('name', '')
            image_urls = gallery.get('image_urls', [])

            if not path or not image_urls:
                continue

            gallery_info[path] = {
                'db_id': db_id,
                'name': name,
                'urls': image_urls
            }

            for url in image_urls:
                if url and isinstance(url, str):
                    # Normalize URL (strip whitespace)
                    url = url.strip()
                    if url:
                        all_urls.append(url)
                        url_to_gallery[url] = path

        if not all_urls:
            log("No valid URLs to check", level="debug", category="status_check")
            return {}

        total_urls = len(all_urls)
        log(f"Checking status of {total_urls} URLs from {len(gallery_info)} galleries",
            level="info", category="status_check")

        # Emit initial progress
        self.status_check_progress.emit(0, total_urls)

        # Check if cancelled before making the request
        if self._status_check_cancelled.is_set():
            log("Status check cancelled before request", level="debug", category="status_check")
            return {}

        # POST to imx.to/user/moderate with all URLs
        form_data = {
            'imagesid': '\n'.join(all_urls)
        }

        log(f"POSTing to {self.web_url}/user/moderate with {total_urls} URLs", level="debug", category="status_check")

        response = self.session.post(
            f"{self.web_url}/user/moderate",
            data=form_data,
            timeout=300,  # 5 minute timeout for large requests with thousands of galleries
            verify=True
        )

        if response.status_code == 403:
            # Session expired - try re-auth
            log("Status check: Session expired (403), attempting re-auth", level="debug", category="status_check")
            if self._attempt_reauth_with_rate_limit():
                # Check if cancelled before retry
                if self._status_check_cancelled.is_set():
                    log("Status check cancelled before retry", level="debug", category="status_check")
                    return {}
                # Retry the request
                response = self.session.post(
                    f"{self.web_url}/user/moderate",
                    data=form_data,
                    timeout=300,  # 5 minute timeout for large requests
                    verify=True
                )
            else:
                raise Exception("Authentication expired and re-auth failed")

        if response.status_code != 200:
            raise Exception(f"Server returned HTTP {response.status_code}")

        if 'DDoS-Guard' in response.text:
            raise Exception("DDoS-Guard protection active - please try again later")

        # Get response text for URL presence checking
        response_text = response.text

        # Emit progress (all URLs processed)
        self.status_check_progress.emit(total_urls, total_urls)

        # Build results per gallery by checking if each URL appears in the response
        # URLs that are online will be present in the response textarea
        results: Dict[str, Dict[str, Any]] = {}
        total_online = 0

        for path, info in gallery_info.items():
            gallery_urls = info['urls']
            online_list = [u for u in gallery_urls if u in response_text]
            offline_list = [u for u in gallery_urls if u not in response_text]
            total_online += len(online_list)

            results[path] = {
                'db_id': info['db_id'],
                'name': info['name'],
                'total': len(gallery_urls),
                'online': len(online_list),
                'offline': len(offline_list),
                'online_urls': online_list,
                'offline_urls': offline_list
            }

        log(f"Found {total_online} online URLs out of {total_urls} submitted",
            level="info", category="status_check")

        return results

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
        """Stop the rename worker and status check worker.

        Args:
            timeout: Maximum time to wait for each thread to stop (in seconds)
        """
        self.running = False

        # Signal rename queue to stop
        try:
            self.queue.put(None)
        except Exception:
            pass

        # Signal status check queue to stop
        try:
            self.status_check_queue.put(None)
        except Exception:
            pass

        # Wait for rename thread
        if self.thread.is_alive():
            self.thread.join(timeout=timeout)

        # Wait for status check thread
        if hasattr(self, 'status_check_thread') and self.status_check_thread.is_alive():
            self.status_check_thread.join(timeout=timeout)

        # Close session
        if self.session:
            try:
                self.session.close()
            except Exception:
                pass

    def is_running(self) -> bool:
        """Check if worker is running."""
        return self.running and self.thread.is_alive()

    def queue_size(self) -> int:
        """Get rename queue size."""
        return self.queue.qsize()

    def status_check_queue_size(self) -> int:
        """Get status check queue size."""
        return self.status_check_queue.qsize()

    def is_authenticated(self) -> bool:
        """Check if worker has successfully authenticated.

        Returns:
            True if login completed successfully, False otherwise
        """
        return self.login_complete.is_set() and self.login_successful
