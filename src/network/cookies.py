"""
Cookie utilities for imx.to uploader.
Separated to avoid duplication and to keep the core clean.
"""

from __future__ import annotations

import os
import sqlite3
import platform
import time
from src.utils.logger import log
from datetime import datetime

# Cookie cache to avoid repeated Firefox database access
# Structure: {cache_key: {cookie_name: cookie_data}}
_firefox_cookie_cache: dict[str, dict[str, dict[str, str | bool]]] = {}
_firefox_cache_time: float = 0.0
_cache_duration: int = 300  # Cache for 5 minutes


def _timestamp() -> str:
    return datetime.now().strftime("%H:%M:%S")


def get_firefox_cookies(domain: str = "imx.to", cookie_names: list[str] | None = None) -> dict:
    """Extract cookies from Firefox browser for the given domain.

    Args:
        domain: Domain to extract cookies for (default: "imx.to")
        cookie_names: Optional list of specific cookie names to extract.
                      If None, extracts all cookies for the domain.
                      Example: ["PHPSESSID", "session_token"]

    Returns:
        Dictionary of cookies: {name: {value: str, domain: str, path: str, secure: bool}}
    """
    import time
    start_time = time.time()

    # Create cache key from domain and cookie_names
    cache_key = f"{domain}:{','.join(sorted(cookie_names) if cookie_names else [])}"

    # Check cache
    if cache_key in _firefox_cookie_cache and (time.time() - _firefox_cache_time) < _cache_duration:
        elapsed = time.time() - start_time
        log(f"Returning cached Firefox cookies for {domain} ({len(_firefox_cookie_cache[cache_key])} cookies, {elapsed:.3f}s)", level="trace", category="cookies")
        return _firefox_cookie_cache[cache_key].copy()

    # Determine OS-specific Firefox profile location
    system = platform.system()
    if system == "Windows":
        appdata = os.getenv("APPDATA")
        if not appdata:
            log("APPDATA environment variable not set", level="warning", category="cookies")
            return {}
        profile_path = os.path.join(appdata, "Mozilla", "Firefox", "Profiles")
    elif system == "Linux":
        profile_path = os.path.expanduser("~/.mozilla/firefox")
    elif system == "Darwin":  # macOS
        profile_path = os.path.expanduser("~/Library/Application Support/Firefox/Profiles")
    else:
        log(f"Unsupported OS for Firefox cookie extraction: {system}", level="warning", category="cookies")
        elapsed = time.time() - start_time
        return {}

    if not os.path.exists(profile_path):
        log(f"Firefox profile path not found: {profile_path}", level="debug", category="cookies")
        elapsed = time.time() - start_time
        return {}

    # Find the default profile directory (usually ends with .default or .default-release)
    try:
        profiles = [d for d in os.listdir(profile_path) if os.path.isdir(os.path.join(profile_path, d))]
        default_profile = next((p for p in profiles if ".default" in p), None)
        if not default_profile:
            log("No default Firefox profile found", level="debug", category="cookies")
            return {}

        cookie_db_path = os.path.join(profile_path, default_profile, "cookies.sqlite")
        if not os.path.exists(cookie_db_path):
            log(f"Firefox cookies database not found at {cookie_db_path}", level="debug", category="cookies")
            return {}

        # Connect to SQLite database and fetch cookies
        sqlite_start = time.time()
        # Use URI mode with immutable flag to avoid locking issues
        conn = sqlite3.connect(f"file:{cookie_db_path}?mode=ro", uri=True)
        sqlite_connect_time = time.time() - sqlite_start
        cursor = conn.cursor()

        query_start = time.time()
        # Query for cookies matching the domain
        if cookie_names:
            placeholders = ','.join('?' * len(cookie_names))
            query = f"""
                SELECT name, value, host, path, isSecure, expiry
                FROM moz_cookies
                WHERE host LIKE ?
                AND name IN ({placeholders})
            """
            cursor.execute(query, (f"%{domain}%", *cookie_names))
        else:
            query = """
                SELECT name, value, host, path, isSecure, expiry
                FROM moz_cookies
                WHERE host LIKE ?
            """
            cursor.execute(query, (f"%{domain}%",))

        rows = cursor.fetchall()
        query_time = time.time() - query_start
        conn.close()

        # Format cookies into a dictionary
        cookies = {}
        for name, value, host, path, is_secure, expiry in rows:
            cookies[name] = {
                "value": value,
                "domain": host,
                "path": path,
                "secure": bool(is_secure),
                "expiry": expiry
            }

        # Update cache
        _firefox_cookie_cache[cache_key] = cookies.copy()
        _firefox_cache_time = time.time()

        elapsed = time.time() - start_time
        log(f"Loaded {len(cookies)} Firefox cookies for {domain} in {elapsed:.3f}s (SQLite: {sqlite_connect_time:.3f}s, query: {query_time:.3f}s)", level="trace", category="cookies")
        return cookies
    except Exception as e:
        elapsed = time.time() - start_time
        log(f"Error extracting Firefox cookies: {e}", level="debug", category="cookies")
        # Update cache with empty result to avoid repeated failures
        _firefox_cache_time = time.time()
        return {}


def load_cookies_from_file(filepath: str) -> dict:
    """Load cookies from a Netscape format cookies file.

    Args:
        filepath: Path to cookies file

    Returns:
        Dictionary of cookies in the same format as get_firefox_cookies()
    """
    if not os.path.exists(filepath):
        return {}

    cookies = {}
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                # Skip comments and empty lines
                if not line or line.startswith('#'):
                    continue

                parts = line.split('\t')
                if len(parts) >= 7:
                    domain, _, path, secure, _, name, value = parts[:7]
                    cookies[name] = {
                        "value": value,
                        "domain": domain,
                        "path": path,
                        "secure": secure.upper() == 'TRUE'
                    }
        log(f"Loaded {len(cookies)} cookies from {filepath}", level="trace", category="cookies")
    except Exception as e:
        log(f"Error loading cookies from {filepath}: {e}", level="warning", category="cookies")

    return cookies
