"""
Cookie utilities for imx.to uploader.
Separated to avoid duplication and to keep the core clean.
"""

from __future__ import annotations

import os
import sqlite3
import platform
from datetime import datetime


def _timestamp() -> str:
    return datetime.now().strftime("%H:%M:%S")


def get_firefox_cookies(domain: str = "imx.to") -> dict:
    """Extract cookies from Firefox browser for the given domain.
    Returns a dict of name -> { value, domain, path, secure }.
    """
    try:
        if platform.system() == "Windows":
            firefox_dir = os.path.join(os.environ.get('APPDATA', ''), 'Mozilla', 'Firefox', 'Profiles')
        else:
            firefox_dir = os.path.join(os.path.expanduser("~"), '.mozilla', 'firefox')

        if not os.path.exists(firefox_dir):
            print(f"{_timestamp()} Firefox profiles directory not found: {firefox_dir}")
            return {}

        profiles = [d for d in os.listdir(firefox_dir) if d.endswith('.default-release')]
        if not profiles:
            profiles = [d for d in os.listdir(firefox_dir) if 'default' in d]
        if not profiles:
            print(f"{_timestamp()} No Firefox profile found")
            return {}

        profile_dir = os.path.join(firefox_dir, profiles[0])
        cookie_file = os.path.join(profile_dir, 'cookies.sqlite')
        if not os.path.exists(cookie_file):
            print(f"{_timestamp()} Firefox cookie file not found: {cookie_file}")
            return {}

        cookies = {}
        conn = sqlite3.connect(cookie_file)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT name, value, host, path, expiry, isSecure
            FROM moz_cookies 
            WHERE host LIKE ?
            """,
            (f'%{domain}%',),
        )
        for row in cursor.fetchall():
            name, value, host, path, _expiry, secure = row
            cookies[name] = {
                'value': value,
                'domain': host,
                'path': path,
                'secure': bool(secure),
            }
        conn.close()
        return cookies
    except Exception as e:
        print(f"{_timestamp()} Error extracting Firefox cookies: {e}")
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
            print(f"{_timestamp()} Loaded {len(cookies)} cookies from {cookie_file}")
        else:
            print(f"{_timestamp()} Cookie file not found: {cookie_file}")
    except Exception as e:
        print(f"{_timestamp()} Error loading cookies: {e}")
    return cookies


