"""
Cookie utilities for imx.to uploader.
Separated to avoid duplication and to keep the core clean.
"""

from __future__ import annotations

import os
import sqlite3
import platform
from src.utils.logger import log
from datetime import datetime

# Cookie cache to avoid repeated Firefox database access
# Structure: {cache_key: {cookie_name: cookie_data}}
_firefox_cookie_cache = {}
_firefox_cache_time = 0
_cache_duration = 300  # Cache for 5 minutes


def _timestamp() -> str:
    return datetime.now().strftime("%H:%M:%S")


def get_firefox_cookies(domain: str = "imx.to", cookie_names: list[str] | None = None) -> dict:
    """Extract cookies from Firefox browser for the given domain.

    Args:
        domain: Domain to extract cookies for (default: "imx.to")
        cookie_names: Optional list of specific cookie names to extract.
                     If None, extracts all cookies for the domain.

    Returns:
        Dict of name -> { value, domain, path, secure }
    """
    import time
    global _firefox_cookie_cache, _firefox_cache_time

    start_time = time.time()

    # Create cache key including cookie filter
    cache_key = f"{domain}_{','.join(sorted(cookie_names)) if cookie_names else 'all'}"

    # Check cache first
    if cache_key in _firefox_cookie_cache and (time.time() - _firefox_cache_time) < _cache_duration:
        elapsed = time.time() - start_time
        log(f"Using cached Firefox cookies (took {elapsed:.3f}s)", level="debug", category="auth")
        return _firefox_cookie_cache[cache_key].copy()
    
    try:
        if platform.system() == "Windows":
            firefox_dir = os.path.join(os.environ.get('APPDATA', ''), 'Mozilla', 'Firefox', 'Profiles')
        else:
            firefox_dir = os.path.join(os.path.expanduser("~"), '.mozilla', 'firefox')

        if not os.path.exists(firefox_dir):
            elapsed = time.time() - start_time
            log(f"Firefox profiles directory not found: {firefox_dir} (took {elapsed:.3f}s)", level="warning", category="auth")
            return {}

        profiles = [d for d in os.listdir(firefox_dir) if d.endswith('.default-release')]
        if not profiles:
            profiles = [d for d in os.listdir(firefox_dir) if 'default' in d]
        if not profiles:
            log(f"No Firefox profile found", level="debug")
            return {}

        profile_dir = os.path.join(firefox_dir, profiles[0])
        cookie_file = os.path.join(profile_dir, 'cookies.sqlite')
        if not os.path.exists(cookie_file):
            log(f"Firefox cookie file not found: {cookie_file}", level="debug", category="auth")
            return {}

        cookies = {}
        #print(f"{_timestamp()} DEBUG: About to connect to SQLite database: {cookie_file}")
        sqlite_start = time.time()
        # Set a 1-second timeout to prevent long waits on locked Firefox databases
        conn = sqlite3.connect(cookie_file, timeout=1.0)
        sqlite_connect_time = time.time() - sqlite_start
        #log(f"SQLite connect took {sqlite_connect_time:.4f}s", level="debug")
        
        cursor = conn.cursor()
        query_start = time.time()

        # Build query with optional cookie name filter
        if cookie_names:
            # Filter for specific cookie names (and require secure cookies)
            placeholders = ','.join(['?'] * len(cookie_names))
            query = f"""
                SELECT name, value, host, path, expiry, isSecure
                FROM moz_cookies
                WHERE host LIKE ? AND name IN ({placeholders}) AND isSecure = 1
            """
            params = (f'%{domain}%', *cookie_names)
        else:
            # Get all cookies for domain
            query = """
                SELECT name, value, host, path, expiry, isSecure
                FROM moz_cookies
                WHERE host LIKE ?
            """
            params = (f'%{domain}%',)

        cursor.execute(query, params)
        query_time = time.time() - query_start
        #log(f"SQLite query took {query_time:.4f}s", level="debug", category="auth")
        for row in cursor.fetchall():
            name, value, host, path, _expiry, secure = row
            cookies[name] = {
                'value': value,
                'domain': host,
                'path': path,
                'secure': bool(secure),
            }
        conn.close()

        # Update cache (use cache key)
        if cache_key not in _firefox_cookie_cache:
            _firefox_cookie_cache[cache_key] = {}
        _firefox_cookie_cache[cache_key] = cookies.copy()
        _firefox_cache_time = time.time()
        
        elapsed = time.time() - start_time
        log(f"get_firefox_cookies() completed in {elapsed:.3f}s (SQLite: connect took {sqlite_connect_time:.3f}s, query took {query_time:.3f}s), found {len(cookies)} {domain} cookies (cached)", level="debug", category="auth")
        return cookies
    except Exception as e:
        elapsed = time.time() - start_time
        log(f"Error extracting Firefox cookies: {e} (took {elapsed:.3f}s)", level="warning", category="auth")
        # Cache empty result to avoid repeated failures
        _firefox_cookie_cache[cache_key] = {}
        _firefox_cache_time = time.time()
        return {}


def load_cookies_from_file(cookie_file: str = "cookies.txt") -> dict:
    """Load cookies from a Netscape-format cookie file.
    Returns a dict of name -> { value, domain, path, secure }.
    """
    cookies = {}
    try:
        if os.path.exists(cookie_file):
            with open(cookie_file, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '\t' in line:
                        parts = line.split('\t')
                        if len(parts) >= 7 and 'imx.to' in parts[0]:
                            domain, _subdomain, path, secure, _expiry, name, value = parts[:7]
                            cookies[name] = {
                                'value': value,
                                'domain': domain,
                                'path': path,
                                'secure': secure == 'TRUE',
                            }
            log(f"Loaded {len(cookies)} cookies from {cookie_file}", level="info", category="auth")
        #else:
        #    print(f"{_timestamp()} Cookie file not found: {cookie_file}")
    except Exception as e:
        log(f"Error loading cookies: {e}", level="error", category="auth")
    return cookies


