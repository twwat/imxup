"""
File host upload client using pycurl for bandwidth tracking and progress callbacks.
"""

import pycurl
import json
import hashlib
import time
import re
import base64
import zipfile
import threading
import functools
from pathlib import Path
from typing import Dict, Any, Optional, Callable, List, Union
from io import BytesIO
from urllib.parse import quote

from src.core.file_host_config import HostConfig
from src.core.engine import AtomicCounter
from src.utils.logger import log


class FileHostClient:
    """pycurl-based file host uploader with bandwidth tracking."""

    def __init__(
        self,
        host_config: HostConfig,
        bandwidth_counter: AtomicCounter,
        credentials: Optional[str] = None,
        host_id: Optional[str] = None,
        log_callback: Optional[Callable[[str, str], None]] = None,
        session_cookies: Optional[Dict[str, str]] = None,
        session_token: Optional[str] = None,
        session_timestamp: Optional[float] = None
    ):
        """Initialize file host client.

        Args:
            host_config: Host configuration
            bandwidth_counter: Atomic counter for bandwidth tracking
            credentials: Optional credentials (username:password or api_key)
            host_id: Optional host identifier for token caching
            log_callback: Optional logging callback from worker
            session_cookies: Optional existing session cookies to reuse
            session_token: Optional existing session token (sess_id) to reuse
            session_timestamp: Optional timestamp when session was created
        """
        self.config = host_config
        self.bandwidth_counter = bandwidth_counter
        self.credentials = credentials
        self.host_id = host_id
        self._log_callback = log_callback

        # Load timeout settings from INI (overrides JSON defaults)
        if host_id:
            from src.core.file_host_config import get_file_host_setting
            inactivity_timeout = get_file_host_setting(host_id, "inactivity_timeout", "int")
            upload_timeout = get_file_host_setting(host_id, "upload_timeout", "int")

            # Override config values if set in INI
            if inactivity_timeout is not None:
                self.config.inactivity_timeout = inactivity_timeout
            if upload_timeout is not None:
                self.config.upload_timeout = upload_timeout
        # Progress tracking
        self.last_uploaded = 0
        self.last_time = 0.0
        self.last_uploaded_for_speed = 0  # Separate tracking for speed calculation
        self.current_speed_bps = 0.0
        self.should_stop_func: Optional[Callable[[], bool]] = None
        self.on_progress_func: Optional[Callable[[int, int, float], None]] = None

        # Authentication token (for token-based auth)
        self.auth_token: Optional[str] = None

        # Session cookies (for session-based auth)
        self.cookie_jar: Dict[str, str] = {}

        # Session token lifecycle tracking
        self._session_token_timestamp: Optional[float] = None  # When sess_id was extracted

        # Thread safety for token operations
        self._token_lock = threading.Lock()

        # Opportunistically cached storage from login (avoids extra API call)
        self._cached_storage_from_login: Optional[Dict[str, Any]] = None

        # Login if credentials provided and auth required
        if self.config.requires_auth and credentials:
            if self.config.auth_type == "api_key":
                # Use credentials directly as permanent API key (no login needed)
                self.auth_token = credentials
                if self._log_callback: self._log_callback(f"Using permanent API key for {self.config.name}", "debug")
            elif self.config.auth_type == "token_login":
                # Try to use cached token first
                if host_id:
                    from src.network.token_cache import get_token_cache
                    token_cache = get_token_cache()
                    cached_token = token_cache.get_token(host_id)
                    if cached_token:
                        if self._log_callback: self._log_callback(f"Using cached token for {self.config.name}", "debug")
                        self.auth_token = cached_token
                    else:
                        # Login and cache the token
                        self.auth_token = self._login_token_based(credentials)
                        if self.auth_token:
                            token_cache.store_token(host_id, self.auth_token, self.config.token_ttl)
                else:
                    # No host_id provided, just login without caching
                    self.auth_token = self._login_token_based(credentials)
            elif self.config.auth_type == "session":
                # Check if session was injected (reuse existing session)
                if session_cookies:
                    # Reuse existing session (no login needed!)
                    self.cookie_jar = session_cookies.copy()
                    self.auth_token = session_token
                    self._session_token_timestamp = session_timestamp
                    if self._log_callback:
                        age = time.time() - (session_timestamp or 0) if session_timestamp else 0
                        self._log_callback(
                            f"Reusing existing session for {self.config.name} (age: {age:.0f}s)",
                            "debug"
                        )
                else:
                    # Fresh login (first time only)
                    self._login_session_based(credentials)

    def _login_token_based(self, credentials: str) -> str:
        """Login to get authentication token.

        Args:
            credentials: username:password

        Returns:
            Authentication token

        Raises:
            ValueError: If login fails
        """
        if ':' not in credentials:
            raise ValueError(f"{self.config.name} requires credentials in format 'username:password'")

        username, password = credentials.split(':', 1)

        # Build login URL with parameters
        login_data = {}
        for field, template in self.config.login_fields.items():
            value = template.replace("{username}", username).replace("{password}", password)
            login_data[field] = value

        login_url = self.config.login_url
        if login_data:
            params = "&".join(f"{k}={quote(str(v))}" for k, v in login_data.items())
            login_url = f"{login_url}?{params}"

        if self._log_callback: self._log_callback(f"Logging in to {self.config.name}...", "debug")

        # Perform login request
        curl = pycurl.Curl()
        response_buffer = BytesIO()

        try:
            curl.setopt(pycurl.URL, login_url)
            curl.setopt(pycurl.WRITEDATA, response_buffer)
            curl.setopt(pycurl.TIMEOUT, 30)
            curl.setopt(pycurl.FOLLOWLOCATION, True)

            curl.perform()
            response_code = curl.getinfo(pycurl.RESPONSE_CODE)

            if response_code != 200:
                raise ValueError(f"Login failed with status {response_code}")

            response_text = response_buffer.getvalue().decode('utf-8')
            data = json.loads(response_text)

            # Check API status
            api_status = data.get("status")
            if api_status and api_status != 200:
                error_msg = self._extract_from_json(data, ["response", "details"]) or \
                           self._extract_from_json(data, ["response", "msg"]) or \
                           f"API returned status {api_status}"
                raise ValueError(f"Login failed: {error_msg}")

            # Extract token
            if not self.config.token_path:
                raise ValueError("token_path not configured")

            token = self._extract_from_json(data, self.config.token_path)
            if not token:
                raise ValueError("Failed to extract token from login response")

            # Opportunistically extract storage info if present in login response
            # This avoids needing a separate /info API call
            storage_info = {}
            if self.config.storage_total_path:
                storage_total = self._extract_from_json(data, self.config.storage_total_path)
                if storage_total is not None:
                    storage_info['storage_total'] = storage_total

            if self.config.storage_left_path:
                storage_left = self._extract_from_json(data, self.config.storage_left_path)
                if storage_left is not None:
                    storage_info['storage_left'] = storage_left

            if self.config.storage_used_path:
                storage_used = self._extract_from_json(data, self.config.storage_used_path)
                if storage_used is not None:
                    storage_info['storage_used'] = storage_used

            # Store for potential access by caller
            if storage_info:
                self._cached_storage_from_login = storage_info

                storage_formatted = json.dumps(storage_info, indent=2).replace(chr(10), '\\n')
                if self._log_callback: self._log_callback(
                    f"Opportunistically cached storage from login: {storage_formatted}",
                    "debug" )

            if self._log_callback: self._log_callback(f"Successfully logged in to {self.config.name}", "debug")
            return token

        finally:
            curl.close()

    def _login_session_based(self, credentials: str) -> None:
        """Login to establish session cookies.

        Args:
            credentials: username:password

        Raises:
            ValueError: If login fails
        """
        if ':' not in credentials:
            raise ValueError(f"{self.config.name} requires credentials in format 'username:password'")

        username, password = credentials.split(':', 1)

        if self._log_callback: self._log_callback(f"Logging in to {self.config.name} (session-based)...", "debug")

        # Step 1: GET login page first (establishes initial cookies, extracts CSRF tokens)
        get_curl = pycurl.Curl()
        get_buffer = BytesIO()
        get_headers = BytesIO()

        try:
            get_curl.setopt(pycurl.URL, self.config.login_url)
            get_curl.setopt(pycurl.WRITEDATA, get_buffer)
            get_curl.setopt(pycurl.HEADERFUNCTION, get_headers.write)
            get_curl.setopt(pycurl.TIMEOUT, 30)
            get_curl.setopt(pycurl.USERAGENT, "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
            get_curl.perform()

            # Extract cookies from GET request
            headers = get_headers.getvalue().decode('utf-8')
            for line in headers.split('\r\n'):
                if line.lower().startswith('set-cookie:'):
                    cookie = line.split(':', 1)[1].strip()
                    cookie_parts = cookie.split(';')[0]
                    if '=' in cookie_parts:
                        name, value = cookie_parts.split('=', 1)
                        self.cookie_jar[name] = value

            # Extract ALL hidden fields from login form
            page_html = get_buffer.getvalue().decode('utf-8', errors='ignore')
            import re
            hidden_fields = {}
            for match in re.finditer(r'<input[^>]+type=["\']hidden["\'][^>]*>', page_html):
                input_tag = match.group(0)
                name_match = re.search(r'name=["\']([^"\']+)["\']', input_tag)
                value_match = re.search(r'value=["\']([^"\']*)["\']', input_tag)
                if name_match:
                    field_name = name_match.group(1)
                    field_value = value_match.group(1) if value_match else ''
                    hidden_fields[field_name] = field_value
            
            if self._log_callback: self._log_callback(f"Extracted hidden fields: {list(hidden_fields.keys())}", "debug")
            
            # Extract captcha if configured 
            captcha_code = None
            if self.config.captcha_regex:
                captcha_match = re.search(self.config.captcha_regex, page_html, re.DOTALL)
                if captcha_match:
                    captcha_area = captcha_match.group(0)
                    
                    # Extract all span tags with padding-left and digit
                    # Format: <span style="...padding-left:26px...">2</span> or &#50;
                    digit_positions = []
                    for span_match in re.finditer(r'<span[^>]*padding-left:\s*(\d+)px[^>]*>([^<]+)</span>', captcha_area):
                        position = int(span_match.group(1))
                        digit_html = span_match.group(2)
                        
                        # Decode HTML entity if present (&#50; -> '2')
                        entity_match = re.search(r'&#(\d+);', digit_html)
                        if entity_match:
                            digit = chr(int(entity_match.group(1)))
                        else:
                            digit = digit_html.strip()
                        
                        digit_positions.append((position, digit))
                    
                    if digit_positions:
                        # Sort by position (left to right)
                        digit_positions.sort(key=lambda x: x[0])
                        captcha_raw = ''.join(d for _, d in digit_positions)
                        
                        # Apply transformation if specified
                        if self.config.captcha_transform == "move_3rd_to_front":
                            # Move 3rd character to front: "1489" -> "8149"
                            if len(captcha_raw) >= 3:
                                captcha_code = captcha_raw[2] + captcha_raw[:2] + captcha_raw[3:]
                            else:
                                captcha_code = captcha_raw
                        elif self.config.captcha_transform == "reverse":
                            captcha_code = captcha_raw[::-1]
                        else:
                            captcha_code = captcha_raw
                        
                        if self._log_callback: self._log_callback(f"Successfully solved CAPTCHA: {captcha_raw} -> {captcha_code} (sorted by 'padding-left' CSS position)", "info")
                    else:
                        if self._log_callback: self._log_callback(f"WARNING: Unable to solve matched CAPTCHA, upload may fail...", "warning")
                else:
                    if self._log_callback: self._log_callback(f"No CAPTCHA found, all good", "debug")

        finally:
            get_curl.close()

        # Step 2: Build login data, starting with hidden fields
        login_data = hidden_fields.copy()  # Start with all hidden fields (token, rand, etc.)
        
        # Override with configured login fields
        for field, template in self.config.login_fields.items():
            value = template.replace("{username}", username).replace("{password}", password)
            login_data[field] = value
        
        # Add captcha if extracted
        if captcha_code:
            login_data[self.config.captcha_field] = captcha_code

        # Step 3: POST login credentials
        post_curl = pycurl.Curl()
        post_buffer = BytesIO()
        post_headers = BytesIO()

        try:
            post_curl.setopt(pycurl.URL, self.config.login_url)
            post_curl.setopt(pycurl.POST, 1)
            post_curl.setopt(pycurl.POSTFIELDS, "&".join(f"{k}={quote(v)}" for k, v in login_data.items()))
            post_curl.setopt(pycurl.WRITEDATA, post_buffer)
            post_curl.setopt(pycurl.HEADERFUNCTION, post_headers.write)
            post_curl.setopt(pycurl.TIMEOUT, 30)
            post_curl.setopt(pycurl.FOLLOWLOCATION, True)
            post_curl.setopt(pycurl.HTTPHEADER, [
                "Content-Type: application/x-www-form-urlencoded",
                "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                f"Referer: {self.config.login_url}"
            ])

            # Send cookies from GET request
            if self.cookie_jar:
                cookie_str = "; ".join(f"{k}={v}" for k, v in self.cookie_jar.items())
                post_curl.setopt(pycurl.COOKIE, cookie_str)

            post_curl.perform()
            response_code = post_curl.getinfo(pycurl.RESPONSE_CODE)

            if response_code not in [200, 302]:
                raise ValueError(f"Login failed with status {response_code}")

            # Extract cookies from POST response
            headers = post_headers.getvalue().decode('utf-8')
            for line in headers.split('\r\n'):
                if line.lower().startswith('set-cookie:'):
                    cookie = line.split(':', 1)[1].strip()
                    cookie_parts = cookie.split(';')[0]
                    if '=' in cookie_parts:
                        name, value = cookie_parts.split('=', 1)
                        self.cookie_jar[name] = value

            if not self.cookie_jar:
                raise ValueError("Login failed: No session cookies received")

            if self._log_callback: self._log_callback(f"Client successfully logged in.", "info")

        finally:
            post_curl.close()

    def _calculate_file_hash(self, file_path: Path) -> str:
        """Calculate MD5 hash of file.

        Args:
            file_path: Path to file

        Returns:
            MD5 hash as hex string
        """
        md5_hash = hashlib.md5()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b""):
                md5_hash.update(chunk)
        return md5_hash.hexdigest()

    def _get_clean_filename(self, filename: str) -> str:
        """Extract clean filename without internal ID prefix.

        Removes 'imxup_{id}_' prefix from ZIP filenames before uploading to hosts.
        This keeps local temp files unique while sending clean names externally.

        Examples:
            'imxup_1555_Test70e.zip' → 'Test70e.zip'
            'imxup_999_My_Gallery-2024.zip' → 'My_Gallery-2024.zip'
            'normal_file.zip' → 'normal_file.zip' (unchanged)
            'imxup_gallery_1555.zip' → 'imxup_gallery_1555.zip' (fallback pattern, unchanged)

        Args:
            filename: Original filename (possibly with imxup prefix)

        Returns:
            Cleaned filename suitable for external hosts
        """
        # Match "imxup_<numbers>_<rest>" and extract <rest>
        match = re.match(r'^imxup_\d+_(.+)$', filename)
        if match:
            return match.group(1)

        # No prefix found, return as-is (safe fallback)
        return filename

    def _refresh_auth_token(self) -> None:
        """Refresh authentication token based on auth type.

        Automatically handles token refresh for all auth types:
        - api_key: No refresh (permanent tokens)
        - token_login: Refresh via login and update cache
        - session: Extract fresh sess_id from upload page
        """
        if self.config.auth_type == "api_key":
            # API keys are permanent, no refresh needed
            return

        elif self.config.auth_type == "token_login":
            # Token-based auth refresh (existing pattern)
            if not self.credentials:
                if self._log_callback:
                    self._log_callback(f"Cannot refresh token: no credentials available", "error")
                return

            from src.network.token_cache import get_token_cache
            token_cache = get_token_cache()
            if self.host_id:
                token_cache.clear_token(self.host_id)

            if self._log_callback:
                self._log_callback(f"Refreshing authentication token for {self.config.name}...", "debug")

            new_token = self._login_token_based(self.credentials)

            # Thread-safe token update
            with self._token_lock:
                self.auth_token = new_token

            if new_token and self.host_id:
                token_cache.store_token(self.host_id, new_token, self.config.token_ttl)

        elif self.config.auth_type == "session":
            # Session-based auth: extract fresh sess_id from upload page

            # Check credentials availability (same pattern as token_login)
            if not self.credentials:
                if self._log_callback:
                    self._log_callback(f"Cannot refresh session: no credentials available", "warning")
                return

            if not self.config.session_id_regex:
                if self._log_callback:
                    self._log_callback(f"No session_id_regex configured for {self.config.name}, cannot refresh", "warning")
                return

            # Log token age for TTL discovery
            with self._token_lock:
                old_timestamp = self._session_token_timestamp

            if old_timestamp:
                age = time.time() - old_timestamp
                if self._log_callback:
                    self._log_callback(
                        f"Refreshing session token for {self.config.name} (token age: {age:.0f}s)",
                        "debug"
                    )
                    # Suggest TTL if not configured
                    if not self.config.session_token_ttl:
                        self._log_callback(
                            f"Session token age: {age:.0f}s when stale detected - "
                            f"consider setting session_token_ttl to {int(age * 0.9)}s",
                            "info"
                        )
            else:
                if self._log_callback:
                    self._log_callback(f"Refreshing session token for {self.config.name}...", "debug")

            upload_page_url = self.config.upload_page_url
            if not upload_page_url:
                # Derive upload page URL from upload endpoint
                import re
                base_url = re.sub(r'/[^/]*$', '', self.config.upload_endpoint)
                upload_page_url = f"{base_url}/upload"

            curl = pycurl.Curl()
            buffer = BytesIO()
            try:
                curl.setopt(pycurl.URL, upload_page_url)
                curl.setopt(pycurl.WRITEDATA, buffer)
                curl.setopt(pycurl.TIMEOUT, 30)

                # Send session cookies for authentication
                if self.cookie_jar:
                    cookie_str = "; ".join(f"{k}={v}" for k, v in self.cookie_jar.items())
                    curl.setopt(pycurl.COOKIE, cookie_str)

                curl.perform()
                page_html = buffer.getvalue().decode('utf-8')

                # Extract fresh sess_id
                import re
                match = re.search(self.config.session_id_regex, page_html)
                if match:
                    new_token = match.group(1)
                    new_timestamp = time.time()

                    # Thread-safe token update
                    with self._token_lock:
                        self.auth_token = new_token
                        self._session_token_timestamp = new_timestamp

                    if self._log_callback:
                        token_preview = new_token[:20] if new_token else "None"
                        self._log_callback(f"Refreshed session token: {token_preview}...", "debug")
                else:
                    if self._log_callback:
                        self._log_callback(f"Failed to extract session token from upload page", "warning")
            finally:
                curl.close()

    def _is_token_stale(self) -> bool:
        """Check if current token is likely stale based on TTL.

        Returns:
            True if token should be refreshed proactively
        """
        # API keys don't expire
        if self.config.auth_type == "api_key":
            return False

        # Check session token TTL (thread-safe read)
        if self.config.auth_type == "session" and self.config.session_token_ttl:
            with self._token_lock:
                timestamp = self._session_token_timestamp

            if timestamp:
                age = time.time() - timestamp
                if age >= self.config.session_token_ttl:
                    if self._log_callback:
                        self._log_callback(f"Session token expired (age: {age:.0f}s, TTL: {self.config.session_token_ttl}s)", "debug")
                    return True

        # token_login TTL is handled by TokenCache.get_token()
        # If we get here with a token, it's still valid
        return False

    def _detect_stale_token_error(self, response_text: str, response_code: int) -> bool:
        """Detect if response indicates stale/expired token.

        Args:
            response_text: Response body text
            response_code: HTTP status code

        Returns:
            True if stale token detected
        """
        # HTTP status codes indicating auth failure
        if response_code in [401, 403]:
            if self._log_callback:
                self._log_callback(f"Stale token detected: HTTP {response_code}", "debug")
            return True

        # Pattern matching (e.g., "Anti-CSRF check failed" on HTTP 200)
        if self.config.stale_token_patterns and response_text:
            for pattern in self.config.stale_token_patterns:
                if re.search(pattern, response_text, re.IGNORECASE | re.DOTALL):
                    if self._log_callback:
                        self._log_callback(f"Stale token detected: matched pattern '{pattern}'", "debug")
                    return True

        return False

    def _with_token_retry(self, operation_func, *args, **kwargs):
        """Execute operation with automatic token refresh on failure.

        Implements two-layer token validation:
        1. Proactive: Check TTL before operation, refresh if expired
        2. Reactive: Detect stale token errors, refresh and retry once

        Args:
            operation_func: Function to execute
            *args: Positional arguments for operation_func
            **kwargs: Keyword arguments for operation_func

        Returns:
            Result from operation_func

        Raises:
            pycurl.error: Network/upload errors
            ValueError: Invalid response or configuration
            ConnectionError: Connection failures
            Exception: Other operation-specific errors
        """
        # Check if we've already retried (prevent infinite loop)
        if kwargs.get('_retry_attempted'):
            # Already retried once, don't retry again
            return operation_func(*args, **kwargs)

        # Layer 1: Proactive TTL check
        if self._is_token_stale():
            if self._log_callback:
                self._log_callback(f"Token TTL expired, refreshing proactively before operation", "debug")
            try:
                self._refresh_auth_token()
            except (pycurl.error, ConnectionError) as e:
                # Transient network error during refresh - continue with old token
                if self._log_callback:
                    self._log_callback(f"Proactive token refresh failed (network error): {e}", "warning")
            except (ValueError, KeyError) as e:
                # Credential/configuration error - this is serious, raise it
                if self._log_callback:
                    self._log_callback(f"Proactive token refresh failed (credential error): {e}", "error")
                raise

        # Attempt operation
        try:
            return operation_func(*args, **kwargs)
        except (pycurl.error, ConnectionError, ValueError) as e:
            # Layer 2: Reactive error detection (only for network/auth errors)
            error_text = str(e)
            response_code = 0

            # Try to extract HTTP code from pycurl exception
            if isinstance(e, pycurl.error):
                # pycurl errors are tuples (error_code, error_message)
                if len(e.args) > 0 and isinstance(e.args[0], int):
                    # Map pycurl error codes to HTTP codes if possible
                    # For HTTP response codes, check if "401" or "403" is in message
                    pass

            # Fallback: extract from error message text
            if "401" in error_text or "Unauthorized" in error_text:
                response_code = 401
            elif "403" in error_text or "Forbidden" in error_text:
                response_code = 403

            # Check if this is a stale token error
            if self._detect_stale_token_error(error_text, response_code):
                if self._log_callback:
                    self._log_callback(f"Stale token detected in error response, refreshing and retrying...", "debug")

                # Refresh token
                try:
                    self._refresh_auth_token()
                except (pycurl.error, ConnectionError, ValueError, OSError) as refresh_error:
                    # If refresh fails (network/auth error), raise the original error
                    if self._log_callback:
                        self._log_callback(f"Token refresh failed: {refresh_error}", "warning")
                    raise e
                # Any other exception (AttributeError, TypeError, etc.) propagates immediately

                # Retry operation ONCE (mark as retried to prevent infinite loop)
                if self._log_callback:
                    self._log_callback(f"Retrying operation with refreshed token...", "debug")
                kwargs['_retry_attempted'] = True
                return operation_func(*args, **kwargs)
            else:
                # Not a token error, re-raise original exception
                raise

    def _extract_from_json(self, data: Any, path: Optional[List[Union[str, int]]]) -> Any:
        """Extract value from JSON using path (supports dict keys and array indices).

        Args:
            data: JSON data
            path: List of keys/indices to traverse (can be None)

        Returns:
            Extracted value or None
        """
        if path is None:
            return None
        result = data
        for key in path:
            if isinstance(result, dict):
                result = result.get(key)
            elif isinstance(result, list) and isinstance(key, int):
                result = result[key] if key < len(result) else None
            else:
                return None
            if result is None:
                return None
        return result

    def _xferinfo_callback(self, download_total, downloaded, upload_total, uploaded):
        """pycurl progress callback.

        Args:
            download_total: Total bytes to download
            downloaded: Bytes downloaded so far
            upload_total: Total bytes to upload
            uploaded: Bytes uploaded so far

        Returns:
            0 to continue, 1 to abort
        """
        # Update bandwidth counter and calculate speed
        current_time = time.time()
        bytes_since_last = uploaded - self.last_uploaded
        if bytes_since_last > 0:
            self.bandwidth_counter.add(bytes_since_last)
            self.last_uploaded = uploaded

        # Calculate speed (bytes per second) - separate tracking to accumulate bytes correctly
        time_delta = current_time - self.last_time
        if time_delta > 0.1:  # Only update speed every 100ms minimum
            bytes_for_speed = uploaded - self.last_uploaded_for_speed
            if bytes_for_speed > 0:
                self.current_speed_bps = bytes_for_speed / time_delta
            self.last_time = current_time
            self.last_uploaded_for_speed = uploaded

        # Check for cancellation
        if self.should_stop_func and self.should_stop_func():
            return 1  # Abort transfer

        # Notify progress with speed
        if self.on_progress_func and upload_total > 0:
            self.on_progress_func(uploaded, upload_total, self.current_speed_bps)

        return 0

    def upload_file(
        self,
        file_path: Path,
        on_progress: Optional[Callable[[int, int, float], None]] = None,
        should_stop: Optional[Callable[[], bool]] = None
    ) -> Dict[str, Any]:
        """Upload file to file host.

        Args:
            file_path: Path to file to upload
            on_progress: Optional progress callback (uploaded_bytes, total_bytes, speed_bps)
            should_stop: Optional cancellation check callback

        Returns:
            Dictionary with upload results

        Raises:
            Exception: If upload fails
        """
        self.on_progress_func = on_progress
        self.should_stop_func = should_stop
        self.last_uploaded = 0
        self.last_time = time.time()
        self.last_uploaded_for_speed = 0
        self.current_speed_bps = 0.0

        if self._log_callback: self._log_callback(f"Uploading {file_path.name} to {self.config.name}...", "info")

        # Handle multi-step uploads (like RapidGator) with automatic token retry
        if self.config.upload_init_url:
            return self._with_token_retry(self._upload_multistep, file_path)

        # Standard upload
        return self._upload_standard(file_path)

    def _upload_standard(self, file_path: Path) -> Dict[str, Any]:
        """Perform standard single-step upload.

        Args:
            file_path: Path to file

        Returns:
            Upload result dictionary
        """
        # Get upload URL
        upload_url = self.config.upload_endpoint

        # Replace filename placeholder
        if "{filename}" in upload_url:
            upload_url = upload_url.replace("{filename}", file_path.name)

        # Get server if needed
        server_sess_id = None
        if self.config.get_server:
            upload_url, server_sess_id = self._get_upload_server()

        curl = pycurl.Curl()
        response_buffer = BytesIO()

        try:
            curl.setopt(pycurl.URL, upload_url)
            curl.setopt(pycurl.WRITEDATA, response_buffer)

            # Optional total timeout (None = unlimited)
            if self.config.upload_timeout:
                curl.setopt(pycurl.TIMEOUT, self.config.upload_timeout)

            # Inactivity timeout (abort if <1KB/s for this many seconds)
            curl.setopt(pycurl.LOW_SPEED_TIME, self.config.inactivity_timeout)
            curl.setopt(pycurl.LOW_SPEED_LIMIT, 1024)  # 1 KB/s minimum

            curl.setopt(pycurl.FOLLOWLOCATION, True)

            # Set up progress callbacks
            curl.setopt(pycurl.NOPROGRESS, False)
            curl.setopt(pycurl.XFERINFOFUNCTION, self._xferinfo_callback)

            # Prepare headers
            headers = self._prepare_headers()
            if headers:
                curl.setopt(pycurl.HTTPHEADER, [f"{k}: {v}" for k, v in headers.items()])

            # Session cookies
            if self.cookie_jar:
                cookie_str = "; ".join(f"{k}={v}" for k, v in self.cookie_jar.items())
                curl.setopt(pycurl.COOKIE, cookie_str)

            # Extract session ID for session-based uploads (before upload)
            sess_id = None
            if self.config.auth_type == "session":
                # Method 1: Use cookie value directly (e.g., FileSpace uses xfss cookie)
                if self.config.session_cookie_name:
                    if self.config.session_cookie_name in self.cookie_jar:
                        sess_id = self.cookie_jar[self.config.session_cookie_name]
                        if self._log_callback: self._log_callback(f"Using {self.config.session_cookie_name} cookie as sess_id: {sess_id[:20]}...", "debug")
                    else:
                        if self._log_callback: self._log_callback(f"Warning: {self.config.session_cookie_name} cookie not found in cookie jar", "warning")
                
                # Method 2: Extract from upload page HTML using regex (e.g., FileDot)
                elif self.config.session_id_regex:
                    # Visit upload page to extract fresh session ID
                    upload_page_url = self.config.upload_page_url
                    if not upload_page_url:
                        # Fallback: derive from upload_endpoint (remove /upload.cgi or similar)
                        import re
                        base_url = re.sub(r'/[^/]*$', '', upload_url)
                        upload_page_url = f"{base_url}/upload"
                    
                    if self._log_callback: self._log_callback(f"Visiting upload page to extract session ID: {upload_page_url}", "debug")
                    
                    page_curl = pycurl.Curl()
                    page_buffer = BytesIO()
                    try:
                        page_curl.setopt(pycurl.URL, upload_page_url)
                        page_curl.setopt(pycurl.WRITEDATA, page_buffer)
                        page_curl.setopt(pycurl.TIMEOUT, 30)
                        
                        # Use session cookies
                        if self.cookie_jar:
                            page_curl.setopt(pycurl.COOKIE, cookie_str)
                        
                        page_curl.perform()
                        page_html = page_buffer.getvalue().decode('utf-8')
                        
                        # Extract session ID using regex
                        import re
                        match = re.search(self.config.session_id_regex, page_html)
                        if match:
                            sess_id = match.group(1)
                            # Store in auth_token for reuse in delete and other operations
                            self.auth_token = sess_id
                            # Track when this token was acquired for TTL management
                            self._session_token_timestamp = time.time()
                            if self._log_callback: self._log_callback(f"Extracted session ID: {sess_id[:20]}...", "debug")
                        else:
                            if self._log_callback: self._log_callback(f"Could not extract session ID from upload page", "debug")
                    finally:
                        page_curl.close()

            # Upload file
            file_size = file_path.stat().st_size

            if self.config.method == "PUT":
                with open(file_path, 'rb') as f:
                    curl.setopt(pycurl.UPLOAD, 1)
                    curl.setopt(pycurl.READDATA, f)
                    curl.setopt(pycurl.INFILESIZE, file_size)
                    curl.perform()
            else:
                # POST with multipart form data
                form_fields = [
                    (self.config.file_field, (
                        pycurl.FORM_FILE, str(file_path),
                        pycurl.FORM_FILENAME, self._get_clean_filename(file_path.name)
                    )),
                    *[(k, v) for k, v in self.config.extra_fields.items()]
                ]
                
                # Add session ID if extracted (from upload page HTML or get_server API)
                if sess_id:
                    form_fields.append(('sess_id', sess_id))
                elif server_sess_id:  # Katfile-style: sess_id from get_server API response
                    form_fields.append(('sess_id', server_sess_id))
                
                curl.setopt(pycurl.HTTPPOST, form_fields)
                curl.perform()

            response_code = curl.getinfo(pycurl.RESPONSE_CODE)

            if response_code not in [200, 201]:
                raise Exception(f"Upload failed with status {response_code}")

            response_text = response_buffer.getvalue().decode('utf-8')
            return self._parse_response(response_text, response_code)

        finally:
            curl.close()

    def _upload_multistep(self, file_path: Path, **kwargs) -> Dict[str, Any]:
        """Perform multi-step upload (init → upload → poll).

        Args:
            file_path: Path to file
            **kwargs: Additional arguments (including _retry_attempted flag)

        Returns:
            Upload result dictionary
        """
        file_size = file_path.stat().st_size

        # Step 1: Calculate hash if required
        file_hash = None
        if self.config.require_file_hash:
            file_hash = self._calculate_file_hash(file_path)
            if self._log_callback: self._log_callback(f"Calculated file hash for {file_path.name}: {file_hash}", "debug")

        # Step 2: Initialize upload
        init_url = self.config.upload_init_url
        if not init_url:
            raise ValueError("upload_init_url not configured for multi-step upload")

        if self._log_callback: self._log_callback(f"Initializing upload of {file_path.name}...", "debug")

        curl = pycurl.Curl()
        response_buffer = BytesIO()

        try:
            # Check if we need POST with JSON body (K2S-style) or GET with query params (RapidGator-style)
            if self.config.init_method == "POST" and self.config.init_body_json:
                # POST with JSON body (K2S-style)
                body = {
                    "access_token": self.auth_token or "",
                    "parent_id": "/"  # Default to root folder
                }
                body_json = json.dumps(body)

                curl.setopt(pycurl.URL, init_url)
                curl.setopt(pycurl.POST, 1)
                curl.setopt(pycurl.POSTFIELDS, body_json)
                curl.setopt(pycurl.HTTPHEADER, ["Content-Type: application/json"])
                curl.setopt(pycurl.WRITEDATA, response_buffer)
                curl.setopt(pycurl.TIMEOUT, 30)
                curl.perform()
            else:
                # GET with URL template replacement (RapidGator-style)
                replacements = {
                    "filename": self._get_clean_filename(file_path.name),
                    "size": str(file_size),
                    "token": self.auth_token or "",
                    "hash": file_hash or ""
                }

                for key, value in replacements.items():
                    init_url = init_url.replace(f"{{{key}}}", value)

                curl.setopt(pycurl.URL, init_url)
                curl.setopt(pycurl.WRITEDATA, response_buffer)
                curl.setopt(pycurl.TIMEOUT, 30)
                curl.perform()

            response_code = curl.getinfo(pycurl.RESPONSE_CODE)

            # Always try to parse response body for detailed error messages
            response_text = response_buffer.getvalue().decode('utf-8')
            try:
                init_data = json.loads(response_text)
            except json.JSONDecodeError:
                init_data = {}

            if response_code != 200:
                # Try to extract detailed error from API response
                api_status = init_data.get("status")
                error_details = self._extract_from_json(init_data, ["response", "details"]) or \
                               self._extract_from_json(init_data, ["response", "msg"]) or \
                               self._extract_from_json(init_data, ["error"]) or \
                               response_text[:200]  # First 200 chars of response

                raise ValueError(f"Upload init failed for {file_path.name} (HTTP {response_code}, API status {api_status}): {error_details}")

            # Check API status even if HTTP was 200 (support both integer 200 and string "success")
            api_status = init_data.get("status")
            if api_status and api_status not in [200, "success"]:
                error_msg = self._extract_from_json(init_data, ["response", "details"]) or \
                           self._extract_from_json(init_data, ["response", "msg"]) or \
                           f"API returned status {api_status}"
                raise ValueError(f"Upload initialization failed for {file_path.name}: {error_msg}")

            # Extract upload URL and ID
            upload_url = self._extract_from_json(init_data, self.config.upload_url_path)
            upload_id = self._extract_from_json(init_data, self.config.upload_id_path)
            upload_state = self._extract_from_json(init_data, ["response", "upload", "state"])

            # Extract dynamic file field (K2S-specific)
            file_field = self.config.file_field  # Default from config
            if self.config.file_field_path:
                dynamic_field = self._extract_from_json(init_data, self.config.file_field_path)
                if dynamic_field:
                    file_field = dynamic_field

            # Extract form data (K2S-specific: ajax, params, signature)
            form_data: Dict[str, Any] = {}
            if self.config.form_data_path:
                extracted_form_data = self._extract_from_json(init_data, self.config.form_data_path)
                if isinstance(extracted_form_data, dict):
                    form_data = extracted_form_data

            # Check for deduplication (file already exists)
            if upload_state == 2 or (upload_url is None and upload_state is not None):
                existing_url = self._extract_from_json(init_data, ["response", "upload", "file", "url"])
                if existing_url:
                    if self._log_callback: self._log_callback("File already exists on server (deduplication)", "warning")
                    # Extract file_id from dedup response
                    file_id = self._extract_from_json(init_data, self.config.file_id_path) or upload_id
                    return {
                        "status": "success",
                        "url": existing_url,
                        "upload_id": upload_id,
                        "file_id": file_id,
                        "deduplication": True,
                        "raw_response": init_data
                    }

            if not upload_url:
                raise Exception(f"Failed to get upload URL from initialization response for {file_path.name}")

            # upload_id is optional (K2S returns it in upload response, not init response)
            if upload_id and self._log_callback:
                self._log_callback(f"Got upload ID for {file_path.name}: {upload_id}", "debug")

        finally:
            curl.close()

        # Step 3: Upload file
        if self._log_callback: self._log_callback("Uploading {file_path.name}...", "debug")

        curl = pycurl.Curl()
        response_buffer = BytesIO()

        try:
            with open(file_path, 'rb') as f:
                curl.setopt(pycurl.URL, upload_url)
                curl.setopt(pycurl.WRITEDATA, response_buffer)

                # Optional total timeout (None = unlimited)
                if self.config.upload_timeout:
                    curl.setopt(pycurl.TIMEOUT, self.config.upload_timeout)

                # Inactivity timeout (abort if <1KB/s for this many seconds)
                curl.setopt(pycurl.LOW_SPEED_TIME, self.config.inactivity_timeout)
                curl.setopt(pycurl.LOW_SPEED_LIMIT, 1024)  # 1 KB/s minimum

                curl.setopt(pycurl.NOPROGRESS, False)
                curl.setopt(pycurl.XFERINFOFUNCTION, self._xferinfo_callback)

                # Build form fields: file + form_data (ajax, params, signature for K2S)
                form_fields: List[Any] = [
                    (file_field, (
                        pycurl.FORM_FILE, str(file_path),
                        pycurl.FORM_FILENAME, self._get_clean_filename(file_path.name)
                    ))
                ]

                # Add form_data fields if present (K2S: ajax, params, signature)
                for key, value in form_data.items():
                    form_fields.append((key, str(value)))

                curl.setopt(pycurl.HTTPPOST, form_fields)

                curl.perform()

                response_code = curl.getinfo(pycurl.RESPONSE_CODE)
                if response_code not in [200, 201]:
                    raise Exception(f"File upload for {file_path.name} failed with status {response_code}")

                # Parse upload response (K2S returns URL directly here)
                upload_response_text = response_buffer.getvalue().decode('utf-8')
                try:
                    upload_data = json.loads(upload_response_text)
                except json.JSONDecodeError:
                    upload_data = {}

        finally:
            curl.close()

        # Step 4: Poll for completion
        if self.config.upload_poll_url:
            if self._log_callback: self._log_callback("Waiting for upload processing for {file_path.name}...", "debug")
            time.sleep(self.config.upload_poll_delay)

            poll_url = self.config.upload_poll_url.replace("{upload_id}", upload_id).replace("{token}", self.auth_token or "")

            for attempt in range(self.config.upload_poll_retries):
                curl = pycurl.Curl()
                response_buffer = BytesIO()

                try:
                    curl.setopt(pycurl.URL, poll_url)
                    curl.setopt(pycurl.WRITEDATA, response_buffer)
                    curl.setopt(pycurl.TIMEOUT, 120)
                    curl.perform()

                    poll_data = json.loads(response_buffer.getvalue().decode('utf-8'))

                    if self._log_callback: self._log_callback(f"{file_path.name}: Poll attempt {attempt + 1}/{self.config.upload_poll_retries}, response: {json.dumps(poll_data)[:200]}", "debug")

                    # Check for final URL
                    final_url = self._extract_from_json(poll_data, self.config.link_path)
                    if final_url:
                        if self._log_callback: self._log_callback(f"{file_path.name}: Upload complete!", "info")
                        # Extract file_id from poll response
                        file_id = self._extract_from_json(poll_data, self.config.file_id_path) or upload_id
                        return {
                            "status": "success",
                            "url": final_url,
                            "upload_id": upload_id,
                            "file_id": file_id,
                            "raw_response": poll_data
                        }

                    # Check for upload state to see if it's still processing
                    state = self._extract_from_json(poll_data, ["response", "upload", "state"])
                    if state == 2:
                        # State 2 means upload is complete - try alternate URL path
                        alternate_url = self._extract_from_json(poll_data, ["response", "file", "url"])
                        if not alternate_url:
                            # Try another path
                            alternate_url = self._extract_from_json(poll_data, ["response", "upload", "file_url"])

                        if alternate_url:
                            if self._log_callback: self._log_callback(f"{file_path.name}: Upload complete (state 2, alternate path)!", "info")
                            return {
                                "status": "success",
                                "url": alternate_url,
                                "upload_id": upload_id,
                                "file_id": upload_id,
                                "raw_response": poll_data
                            }

                    # Not ready yet, wait and retry
                    if attempt < self.config.upload_poll_retries - 1:
                        time.sleep(self.config.upload_poll_delay)

                finally:
                    curl.close()

            # If we got here, polling timed out - log the last response
            if self._log_callback: self._log_callback(f"{file_path.name}: Upload polling timeout. Last response: {json.dumps(poll_data) if 'poll_data' in locals() else 'No response'}", "warning")
            raise Exception(f"{file_path.name}: Upload processing timeout - file may still be uploading (got upload_id: {upload_id})")

        # No polling configured - parse upload response directly (K2S-style)
        # Extract URL from upload response
        url = self._extract_from_json(upload_data, self.config.link_path) or ""

        # Extract file_id from upload response using configured path
        file_id = self._extract_from_json(upload_data, self.config.file_id_path) or upload_id

        return {
            "status": "success",
            "url": url,
            "upload_id": upload_id,
            "file_id": file_id,
            "raw_response": upload_data
        }

    def _get_upload_server(self) -> tuple[str, Optional[str]]:
        """Get upload server URL and optional session ID.

        Returns:
            Tuple of (server_url, sess_id):
            - server_url: Upload server URL (may contain replaced placeholders)
            - sess_id: Single-use session ID from get_server API (Katfile-style), 
                       or None if not configured
        """
        if not self.config.get_server:
            return (self.config.upload_endpoint, None)

        # Replace {token} placeholder with API key
        get_server_url = self.config.get_server
        if "{token}" in get_server_url and self.auth_token:
            get_server_url = get_server_url.replace("{token}", self.auth_token)

        curl = pycurl.Curl()
        response_buffer = BytesIO()

        try:
            curl.setopt(pycurl.URL, get_server_url)
            curl.setopt(pycurl.WRITEDATA, response_buffer)
            curl.setopt(pycurl.TIMEOUT, 10)
            
            # Add auth headers if needed
            headers = self._prepare_headers()
            if headers:
                curl.setopt(pycurl.HTTPHEADER, [f"{k}: {v}" for k, v in headers.items()])
            
            curl.perform()

            data = json.loads(response_buffer.getvalue().decode('utf-8'))

            # Extract server URL using configured path
            server_url = self.config.upload_endpoint
            if self.config.server_response_path:
                extracted_url = self._extract_from_json(data, self.config.server_response_path)
                if extracted_url:
                    server_url = self.config.upload_endpoint.replace("{server}", extracted_url)
                else:
                    raise ValueError(f"Failed to extract server URL from get_server response (path: {self.config.server_response_path})")
            
            # Fallback: GoFile compatibility (legacy)
            elif "gofile" in self.config.name.lower() and "data" in data and "server" in data["data"]:
                server = data["data"]["server"]
                server_url = self.config.upload_endpoint.replace("{server}", server)

            # Extract sess_id if configured (Katfile-style single-use session IDs)
            sess_id = None
            if self.config.server_session_id_path:
                sess_id = self._extract_from_json(data, self.config.server_session_id_path)
                if sess_id:
                    if self._log_callback:
                        sess_id_preview = sess_id[:20] if len(sess_id) > 20 else sess_id
                        self._log_callback(f"Extracted single-use sess_id from get_server: {sess_id_preview}...", "debug")
                else:
                    # Extraction failed but was expected
                    if self._log_callback:
                        self._log_callback(
                            f"ERROR: server_session_id_path configured but extraction failed. Response: {json.dumps(data)[:200]}",
                            "error"
                        )
                    raise ValueError(f"Failed to extract required sess_id from get_server API (path: {self.config.server_session_id_path})")

            return (server_url, sess_id)

        finally:
            curl.close()

    def _prepare_headers(self) -> Dict[str, str]:
        """Prepare HTTP headers.

        Returns:
            Dictionary of headers
        """
        headers = {}

        if self.auth_token and self.config.auth_type:
            if self.config.auth_type == "bearer":
                headers["Authorization"] = f"Bearer {self.auth_token}"
            elif self.config.auth_type == "basic":
                auth_string = base64.b64encode(f":{self.auth_token}".encode()).decode()
                headers["Authorization"] = f"Basic {auth_string}"

        return headers

    def _parse_response(self, response_text: str, response_code: int) -> Dict[str, Any]:
        """Parse upload response and extract download link.

        Args:
            response_text: Response body
            response_code: HTTP status code

        Returns:
            Result dictionary with status and URL
        """
        result = {
            "status": "success",
            "timestamp": time.time()
        }

        if self.config.response_type == "json":
            data = json.loads(response_text)
            result["raw_response"] = data

            # Handle array responses
            if isinstance(data, list) and len(data) > 0:
                data = data[0]

            # Extract link using JSON path
            if self.config.link_path:
                link = self._extract_from_json(data, self.config.link_path)
                if link:
                    result["url"] = self.config.link_prefix + str(link) + self.config.link_suffix

                    # Apply regex transformation
                    if self.config.link_regex:
                        url_str = result["url"]
                        if isinstance(url_str, str):
                            match = re.search(self.config.link_regex, url_str)
                            if match and match.groups():
                                result["url"] = self.config.link_prefix + match.group(1) + self.config.link_suffix

            # Extract file_id for delete operations
            if self.config.file_id_path:
                file_id = self._extract_from_json(data, self.config.file_id_path)
                if file_id:
                    result["file_id"] = str(file_id)

        elif self.config.response_type == "text":
            result["raw_response"] = response_text

            if self.config.link_regex:
                match = re.search(self.config.link_regex, response_text)
                if match:
                    extracted = match.group(1) if match.groups() else match.group(0)
                    result["url"] = self.config.link_prefix + extracted + self.config.link_suffix
                    # For text responses with regex, use the extracted value as file_id
                    # This allows delete operations to work with session-based hosts
                    result["file_id"] = extracted
            else:
                result["url"] = response_text.strip()

        elif self.config.response_type == "redirect":
            # URL should be in Location header (handled by pycurl FOLLOWLOCATION)
            result["url"] = ""

        return result

    def _is_same_origin(self, url1: str, url2: str) -> bool:
        """Check if two URLs have the same origin (scheme + domain).

        Used for validating redirects to prevent CSRF attacks.

        Args:
            url1: First URL
            url2: Second URL

        Returns:
            True if same origin, False otherwise
        """
        from urllib.parse import urlparse
        try:
            parsed1 = urlparse(url1)
            parsed2 = urlparse(url2)
            return (parsed1.scheme == parsed2.scheme and
                    parsed1.netloc == parsed2.netloc)
        except Exception:
            # If URL parsing fails, assume different origin for safety
            return False

    def delete_file(self, file_id: str) -> Dict[str, Any]:
        """Delete a file from the host.

        Automatically refreshes stale tokens and retries on auth failures.

        Args:
            file_id: File ID to delete

        Returns:
            Result dictionary

        Raises:
            Exception: If delete fails or not supported
        """
        if not self.config.delete_url:
            raise ValueError(f"{self.config.name} does not support file deletion")

        if self._log_callback:
            self._log_callback(f"Deleting file {file_id} from {self.config.name}...", "debug")

        def _delete_impl(**kwargs) -> Dict[str, Any]:
            """Core delete implementation (wrapped for retry)."""
            curl = pycurl.Curl()
            response_buffer = BytesIO()

            try:
                # Initialize delete_url (needed for redirect validation)
                delete_url = self.config.delete_url or ""

                # Check if we need POST with JSON body (K2S-style)
                if self.config.delete_body_json:
                    body = {
                        "ids": [file_id],
                        "access_token": self.auth_token or ""
                    }
                    body_json = json.dumps(body)

                    curl.setopt(pycurl.URL, self.config.delete_url)
                    curl.setopt(pycurl.POST, 1)
                    curl.setopt(pycurl.POSTFIELDS, body_json)
                    curl.setopt(pycurl.HTTPHEADER, ["Content-Type: application/json"])
                    curl.setopt(pycurl.WRITEDATA, response_buffer)
                    curl.setopt(pycurl.TIMEOUT, 30)

                    # Send session cookies for session-based auth
                    if self.config.auth_type == "session" and self.cookie_jar:
                        cookie_str = "; ".join(f"{k}={v}" for k, v in self.cookie_jar.items())
                        curl.setopt(pycurl.COOKIE, cookie_str)

                    curl.perform()
                else:
                    # Traditional GET/DELETE/POST with URL template replacement
                    replacements = {
                        "file_id": file_id,
                        "token": self.auth_token or ""
                    }

                    # Check if we need POST with form parameters
                    if self.config.delete_method == "POST" and self.config.delete_params:
                        # POST with form data (for hosts that need sess_id as POST param)
                        from urllib.parse import urlencode

                        known_params = {"del_code", "sess_id", "file_id"}
                        form_data = {}
                        for param in self.config.delete_params:
                            if param not in known_params:
                                if self._log_callback:
                                    self._log_callback(f"Unknown delete parameter '{param}' in config - skipping", "warning")
                                continue

                            if param == "del_code":
                                form_data["del_code"] = file_id
                            elif param == "sess_id":
                                form_data["sess_id"] = self.auth_token or ""
                            elif param == "file_id":
                                form_data["file_id"] = file_id

                        post_data = urlencode(form_data)

                        curl.setopt(pycurl.URL, delete_url)
                        curl.setopt(pycurl.POST, 1)
                        curl.setopt(pycurl.POSTFIELDS, post_data)
                        curl.setopt(pycurl.WRITEDATA, response_buffer)
                        curl.setopt(pycurl.TIMEOUT, 30)
                    else:
                        # GET/DELETE with URL template replacement
                        for key, value in replacements.items():
                            delete_url = delete_url.replace(f"{{{key}}}", value)

                        curl.setopt(pycurl.URL, delete_url)
                        curl.setopt(pycurl.WRITEDATA, response_buffer)
                        curl.setopt(pycurl.TIMEOUT, 30)

                        if self.config.delete_method == "DELETE":
                            curl.setopt(pycurl.CUSTOMREQUEST, "DELETE")

                    # Send session cookies for session-based auth
                    if self.config.auth_type == "session" and self.cookie_jar:
                        cookie_str = "; ".join(f"{k}={v}" for k, v in self.cookie_jar.items())
                        curl.setopt(pycurl.COOKIE, cookie_str)

                    curl.perform()

                response_code = curl.getinfo(pycurl.RESPONSE_CODE)
                response_text = response_buffer.getvalue().decode('utf-8')

                # Check for stale token errors based on HTTP status and config
                if response_code in [200, 204]:
                    # Direct success - check for stale token patterns if configured
                    if self.config.check_body_on_success and self._detect_stale_token_error(response_text, response_code):
                        raise ValueError(f"Stale token error: {response_text[:200]}")
                elif response_code in [301, 302]:
                    # Redirect - validate it's same-origin to prevent CSRF attacks
                    final_url = curl.getinfo(pycurl.EFFECTIVE_URL)
                    if not self._is_same_origin(delete_url, final_url):
                        raise ValueError(f"Delete redirected to different origin: {final_url}")
                    # Check for stale token patterns even on redirect
                    if self.config.check_body_on_success and self._detect_stale_token_error(response_text, response_code):
                        raise ValueError(f"Stale token error: {response_text[:200]}")
                else:
                    # Non-success status - always check for stale token errors
                    if self._detect_stale_token_error(response_text, response_code):
                        raise ValueError(f"Stale token error: {response_text[:200]}")
                    raise ValueError(f"Delete failed with status {response_code}")

                if self._log_callback:
                    self._log_callback(f"Successfully deleted file {file_id} from {self.config.name}", "info")

                return {
                    "status": "success",
                    "file_id": file_id,
                    "raw_response": response_text
                }

            finally:
                curl.close()

        # Wrap delete operation with automatic token refresh/retry
        return self._with_token_retry(_delete_impl)

    def get_user_info(self) -> Dict[str, Any]:
        """Get user info including storage and premium status.

        Automatically refreshes stale tokens and retries on auth failures.

        Returns:
            Dictionary with user info

        Raises:
            ValueError: If user info retrieval fails or not supported
        """
        if not self.config.user_info_url:
            raise ValueError(f"{self.config.name} does not support user info retrieval")

        if self._log_callback:
            self._log_callback(f"Retrieving user info from {self.config.name}...", "debug")

        def _get_user_info_impl(**kwargs) -> Dict[str, Any]:
            """Core user info implementation (wrapped for retry)."""
            # user_info_url is guaranteed to exist by the check at the start of get_user_info()
            user_info_url = self.config.user_info_url
            if not user_info_url:
                raise ValueError("user_info_url not configured")

            # Check authentication based on auth type (must be inside for token refresh)
            if self.config.auth_type == "api_key":
                if not self.auth_token:
                    raise ValueError("API key required for user info")
                info_url = user_info_url.replace("{token}", self.auth_token)
            elif self.config.auth_type == "token_login":
                # Thread-safe token read
                with self._token_lock:
                    token = self.auth_token
                if not token:
                    raise ValueError("Authentication token required for user info")
                # Build user info URL with token (must use fresh token after refresh)
                info_url = user_info_url.replace("{token}", token)
            elif self.config.auth_type == "session":
                if not self.cookie_jar:
                    raise ValueError("Session cookies required for user info")
                # Use URL as-is (no token placeholder)
                info_url = user_info_url
            else:
                raise ValueError(f"Unsupported auth type for user info: {self.config.auth_type}")

            curl = pycurl.Curl()
            response_buffer = BytesIO()

            try:
                curl.setopt(pycurl.URL, info_url)
                curl.setopt(pycurl.WRITEDATA, response_buffer)
                curl.setopt(pycurl.TIMEOUT, 30)

                # Check if we need POST with JSON body (K2S-style)
                if self.config.user_info_method == "POST" and self.config.user_info_body_json:
                    with self._token_lock:
                        token = self.auth_token
                    body = {"access_token": token}
                    body_json = json.dumps(body)
                    curl.setopt(pycurl.POST, 1)
                    curl.setopt(pycurl.POSTFIELDS, body_json)
                    curl.setopt(pycurl.HTTPHEADER, ["Content-Type: application/json"])
                elif self.config.auth_type == "session" and self.cookie_jar:
                    # Send session cookies for session-based auth
                    cookie_str = "; ".join(f"{k}={v}" for k, v in self.cookie_jar.items())
                    curl.setopt(pycurl.COOKIE, cookie_str)

                curl.perform()

                response_code = curl.getinfo(pycurl.RESPONSE_CODE)

                # Raise ValueError on auth errors (caught by _with_token_retry)
                if response_code == 401:
                    raise ValueError(f"Unauthorized: Authentication failed (401)")
                elif response_code == 403:
                    raise ValueError(f"Forbidden: Access denied (403)")
                elif response_code != 200:
                    raise ValueError(f"User info retrieval failed with status {response_code}")

                response_text = response_buffer.getvalue().decode('utf-8')

                # For JSON responses, check API status field (K2S-style)
                if not self.config.storage_regex:
                    try:
                        data = json.loads(response_text)
                        api_status = data.get("status")
                        if api_status:
                            # Accept common success indicators
                            success_values = ["success", "ok", "OK", "200", 200, "true", True]
                            if api_status not in success_values:
                                error_msg = data.get("message", "Unknown API error")
                                raise ValueError(f"API returned status '{api_status}': {error_msg}")
                    except json.JSONDecodeError:
                        pass  # Not JSON, will be handled below

                # Check if we need HTML parsing (storage_regex) or JSON parsing
                if self.config.storage_regex:
                    # HTML response - extract storage using regex
                    result: Dict[str, Any] = {"raw_response": "HTML response (not logged)"}

                    if self._log_callback: self._log_callback(f"Parsing HTML for storage (response length: {len(response_text)} bytes)", "debug")

                    match = re.search(self.config.storage_regex, response_text, re.DOTALL)
                    if match:
                        # Regex should capture: (used, total) in GB
                        # Example: "566.87 of 10240 GB" -> groups (566.87, 10240)
                        used_gb = float(match.group(1))
                        total_gb = float(match.group(2))

                        # Convert to bytes
                        total_bytes = int(total_gb * 1024 * 1024 * 1024)
                        used_bytes = int(used_gb * 1024 * 1024 * 1024)
                        left_bytes = total_bytes - used_bytes

                        result['storage_total'] = total_bytes
                        result['storage_used'] = used_bytes
                        result['storage_left'] = left_bytes

                        if self._log_callback: self._log_callback(
                            f"Extracted storage from HTML: {used_gb} of {total_gb} GB (left: {(left_bytes / 1024 / 1024 / 1024):.2f} GB)",
                            "debug"
                        )
                    else:
                        # Regex didn't match - log entire HTML response for debugging
                        # Escape newlines for log viewer auto-expand (replace \n with literal \\n)
                        response_escaped = response_text.replace('\n', '\\n').replace('\r', '')
                        if self._log_callback: self._log_callback(
                            f"Storage regex did not match HTML response (full response): {response_escaped}",
                            "warning"
                        )
                else:
                    # JSON response - extract using JSON paths
                    data = json.loads(response_text)
                    result = {"raw_response": data}

                    if self.config.storage_total_path:
                        result['storage_total'] = self._extract_from_json(data, self.config.storage_total_path)
                        if self._log_callback: self._log_callback(
                            f"Extracted storage_total={result.get('storage_total')} using path {self.config.storage_total_path}",
                            "debug" )

                    if self.config.storage_left_path:
                        result['storage_left'] = self._extract_from_json(data, self.config.storage_left_path)
                        if self._log_callback: self._log_callback(
                            f"Extracted storage_left={result.get('storage_left')} using path {self.config.storage_left_path}",
                            "debug" )

                    if self.config.storage_used_path:
                        result['storage_used'] = self._extract_from_json(data, self.config.storage_used_path)

                    # Fallback: calculate storage_total from storage_left + storage_used if missing
                    if result.get('storage_total') is None:
                        storage_left = result.get('storage_left')
                        storage_used = result.get('storage_used')
                        if storage_left is not None and storage_used is not None:
                            try:
                                result['storage_total'] = int(storage_left) + int(storage_used)
                                if self._log_callback:
                                    self._log_callback(
                                        f"Calculated storage_total={result['storage_total']} from storage_left ({storage_left}) + storage_used ({storage_used})",
                                        "debug"
                                    )
                            except (ValueError, TypeError) as e:
                                if self._log_callback:
                                    self._log_callback(
                                        f"Failed to calculate storage_total: {e}",
                                        "warning"
                                    )

                    if self.config.premium_status_path:
                        result['is_premium'] = self._extract_from_json(data, self.config.premium_status_path)

                if self._log_callback: self._log_callback(f"Successfully retrieved user info from {self.config.name}", "debug")

                return result

            finally:
                curl.close()

        # Wrap user info operation with automatic token refresh/retry
        return self._with_token_retry(_get_user_info_impl)

    def get_session_state(self) -> Dict[str, Any]:
        """Extract current session state for persistence by worker.

        Returns:
            Dictionary with cookies, token, timestamp for worker to persist
        """
        return {
            'cookies': self.cookie_jar.copy(),
            'token': self.auth_token,
            'timestamp': self._session_token_timestamp
        }

    def test_credentials(self) -> Dict[str, Any]:
        """Test if credentials are valid.

        Returns:
            Dictionary with test results: {success: bool, message: str, user_info: dict}
        """
        try:
            if self.config.requires_auth:
                # Check authentication based on auth type
                if self.config.auth_type == "token_login":
                    if not self.auth_token:
                        return {
                            "success": False,
                            "message": "No authentication token available",
                            "error": "Not logged in"
                        }
                elif self.config.auth_type == "session":
                    if not self.cookie_jar:
                        return {
                            "success": False,
                            "message": "No session cookies available",
                            "error": "Not logged in"
                        }

                # Test using user info endpoint if available
                if self.config.user_info_url:
                    user_info = self.get_user_info()
                    return {
                        "success": True,
                        "message": "Successfully validated credentials",
                        "user_info": user_info
                    }
                else:
                    # No way to test, assume valid if we have a token
                    return {
                        "success": True,
                        "message": "Token exists (unable to verify)",
                        "warning": "No validation endpoint available"
                    }
            else:
                # No auth required
                return {
                    "success": True,
                    "message": "No authentication required"
                }

        except Exception as e:
            return {
                "success": False,
                "message": f"Credential validation failed: {str(e)}",
                "error": str(e)
            }

    def test_upload(self, cleanup: bool = True) -> Dict[str, Any]:
        """Test upload by uploading a small dummy file.

        Args:
            cleanup: If True, delete the test file after upload

        Returns:
            Dictionary with test results: {success: bool, message: str, file_id: str, url: str}
        """
        import tempfile

        try:
            # Create a small test ZIP file
            test_zip_path = Path(tempfile.gettempdir()) / "test_imxup.zip"

            with zipfile.ZipFile(test_zip_path, 'w', zipfile.ZIP_STORED) as zf:
                # Add a tiny text file to the ZIP
                zf.writestr("test.txt", "imxup test file - safe to delete")

            if self._log_callback: self._log_callback(f"Created test file: {test_zip_path} ({test_zip_path.stat().st_size} bytes)", "debug")

            # Attempt upload
            result = self.upload_file(test_zip_path)

            if result.get('status') == 'success':
                # Use proper file_id extraction (consistent with upload flow)
                file_id = result.get('file_id') or result.get('upload_id')
                download_url = result.get('url', '')

                # Cleanup: delete the test file if requested and delete is supported
                if cleanup and self.config.delete_url and file_id:
                    try:
                        self.delete_file(file_id)
                        cleanup_msg = " (test file deleted)"
                    except Exception as e:
                        cleanup_msg = f" (cleanup failed: {e})"
                else:
                    cleanup_msg = " (test file not deleted)"

                # Delete local test ZIP
                test_zip_path.unlink(missing_ok=True)

                return {
                    "success": True,
                    "message": f"Upload test successful{cleanup_msg}",
                    "file_id": file_id,
                    "url": download_url
                }
            else:
                # Delete local test ZIP
                test_zip_path.unlink(missing_ok=True)

                return {
                    "success": False,
                    "message": "Upload test failed",
                    "error": result.get('error', 'Unknown error')
                }

        except Exception as e:
            # Clean up test file on error
            if 'test_zip_path' in locals():
                Path(test_zip_path).unlink(missing_ok=True)

            return {
                "success": False,
                "message": f"Upload test failed: {str(e)}",
                "error": str(e)
            }

    def get_cached_storage_from_login(self) -> Optional[Dict[str, Any]]:
        """Get storage data that was opportunistically cached during login.

        This allows callers to get storage info without making a separate /info API call,
        since many APIs return storage data as part of the login response.

        Returns:
            Dictionary with storage_total, storage_left, storage_used if available,
            or None if no storage data was cached during login
        """
        return self._cached_storage_from_login
