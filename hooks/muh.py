#!/usr/bin/env python3
"""
Multi-host file uploader inspired by PolyUploader
Supports multiple file hosting services with minimal code

Usage:
    python muh.py <host> <file> [api_key]

Examples:
    python muh.py gofile test.jpg
    python muh.py pixeldrain test.jpg your_api_key_here
    python muh.py litterbox test.jpg 24h
    python muh.py filedot test.jpg username:password
    python muh.py rapidgator test.jpg username:password

For imxup integration:
    Upload gallery folder: python "path/to/muh.py" gofile "%p"
    Upload as ZIP:         python "path/to/muh.py" gofile "%z"

    Available parameters in imxup External Apps:
    - %N: Gallery name            - %e1-%e4: ext field values
    - %T: Tab name                - %c1-%c4: custom field values
    - %p: Gallery path            - %g: Gallery ID (completed only)
    - %C: Image count             - %j: JSON artifact path (completed only)
    - %s: Size in bytes           - %b: BBCode path (completed only)
    - %t: Template name           - %z: ZIP path (auto-created if needed)

    Note: When using %z, imxup automatically creates a temporary ZIP of the gallery
    using store mode (no compression) for maximum speed, then deletes it after upload.

The script outputs JSON that can be mapped to ext1-4 fields in imxup.
"""

import sys
import json
import requests
import base64
import re
import hashlib
import time
from pathlib import Path
from typing import Dict, List, Any, Optional, Union
from datetime import datetime
from urllib.parse import quote
import mimetypes

class HostConfig:
    """Configuration for a file hosting service"""

    def __init__(
        self,
        name: str,
        get_server: Optional[str] = None,
        upload_endpoint: str = "",
        method: str = "POST",
        auth_type: Optional[str] = None,  # "bearer", "basic", "session", "token_login", or None
        file_field: str = "file",
        extra_fields: Optional[Dict] = None,
        response_type: str = "json",  # "json", "text", "regex", "redirect"
        link_path: Optional[List[Union[str, int]]] = None,  # JSON path to link (supports array indices)
        link_prefix: str = "",
        link_suffix: str = "",
        link_regex: Optional[str] = None,
        requires_auth: bool = False,
        login_url: Optional[str] = None,  # For session-based auth or token_login
        login_fields: Optional[Dict[str, str]] = None,  # Field mapping for login
        session_id_regex: Optional[str] = None,  # Regex to extract session ID from page
        token_path: Optional[List[Union[str, int]]] = None,  # JSON path to extract token from login response
        # Multi-step upload configuration
        upload_init_url: Optional[str] = None,  # URL template for upload initialization
        upload_init_params: Optional[List[str]] = None,  # Params: {filename}, {hash}, {size}, {token}
        upload_url_path: Optional[List[Union[str, int]]] = None,  # JSON path to actual upload URL
        upload_id_path: Optional[List[Union[str, int]]] = None,  # JSON path to upload ID
        upload_poll_url: Optional[str] = None,  # URL template to poll for completion
        upload_poll_delay: float = 1.0,  # Delay between poll attempts (seconds)
        upload_poll_retries: int = 10,  # Max poll attempts
        require_file_hash: bool = False  # Whether to calculate MD5 hash
    ):
        self.name = name
        self.get_server = get_server
        self.upload_endpoint = upload_endpoint
        self.method = method
        self.auth_type = auth_type
        self.file_field = file_field
        self.extra_fields = extra_fields or {}
        self.response_type = response_type
        self.link_path = link_path
        self.link_prefix = link_prefix
        self.link_suffix = link_suffix
        self.link_regex = link_regex
        self.requires_auth = requires_auth
        self.login_url = login_url
        self.login_fields = login_fields or {}
        self.session_id_regex = session_id_regex
        self.token_path = token_path
        # Multi-step upload
        self.upload_init_url = upload_init_url
        self.upload_init_params = upload_init_params or []
        self.upload_url_path = upload_url_path
        self.upload_id_path = upload_id_path
        self.upload_poll_url = upload_poll_url
        self.upload_poll_delay = upload_poll_delay
        self.upload_poll_retries = upload_poll_retries
        self.require_file_hash = require_file_hash

# Host configurations inspired by PolyUploader
HOSTS = {
    "gofile": HostConfig(
        name="GoFile",
        get_server="https://api.gofile.io/servers",
        upload_endpoint="https://{server}.gofile.io/contents/uploadfile",
        method="POST",
        auth_type="bearer",
        file_field="file",
        response_type="json",
        link_path=["data", "downloadPage"],
        requires_auth=False  # Optional API key for account features
    ),

    "pixeldrain": HostConfig(
        name="Pixeldrain",
        upload_endpoint="https://pixeldrain.com/api/file",
        method="PUT",
        auth_type="basic",
        file_field="file",
        response_type="json",
        link_path=["id"],
        link_prefix="https://pixeldrain.com/u/",
        requires_auth=False  # Works without auth, but limited
    ),

    "anonfiles": HostConfig(
        name="AnonFiles",
        upload_endpoint="https://api.anonfiles.com/upload",
        method="POST",
        file_field="file",
        response_type="json",
        link_path=["data", "file", "url", "short"],
        requires_auth=False
    ),

    "fileio": HostConfig(
        name="File.io",
        upload_endpoint="https://file.io",
        method="POST",
        file_field="file",
        extra_fields={"expires": "1w"},  # Default expiry
        response_type="json",
        link_path=["link"],
        requires_auth=False
    ),

    "0x0": HostConfig(
        name="0x0.st",
        upload_endpoint="https://0x0.st",
        method="POST",
        file_field="file",
        response_type="text",
        requires_auth=False
    ),

    "litterbox": HostConfig(
        name="Litterbox (Catbox)",
        upload_endpoint="https://litterbox.catbox.moe/resources/internals/api.php",
        method="POST",
        file_field="fileToUpload",
        extra_fields={
            "reqtype": "fileupload",
            "time": "24h"  # 1h, 12h, 24h, 72h
        },
        response_type="text",
        requires_auth=False
    ),

    "tmpfiles": HostConfig(
        name="TmpFiles",
        upload_endpoint="https://tmpfiles.org/api/v1/upload",
        method="POST",
        file_field="file",
        response_type="json",
        link_path=["data", "url"],
        link_regex=r"https://tmpfiles\.org/(.+)",
        link_prefix="https://tmpfiles.org/dl/",
        requires_auth=False
    ),

    "filebin": HostConfig(
        name="FileBin",
        upload_endpoint="https://filebin.net",
        method="POST",
        file_field="file",
        response_type="json",
        link_path=["url"],
        requires_auth=False
    ),

    "bashupload": HostConfig(
        name="BashUpload",
        upload_endpoint="https://bashupload.com/upload",
        method="POST",
        file_field="file",
        response_type="text",
        link_regex=r"wget\s+(https?://[^\s]+)",
        requires_auth=False
    ),

    "transfersh": HostConfig(
        name="Transfer.sh",
        upload_endpoint="https://transfer.sh/{filename}",
        method="PUT",
        file_field="file",
        response_type="text",
        requires_auth=False
    ),

    "wetransfer": HostConfig(
        name="WeTransfer",
        upload_endpoint="https://wetransfer.com/api/v4/transfers",
        method="POST",
        file_field="file",
        response_type="json",
        link_path=["shortened_url"],
        requires_auth=False  # Note: Has size limits for free tier
    ),

    "uploadcc": HostConfig(
        name="Upload.cc",
        upload_endpoint="https://upload.cc/upload",
        method="POST",
        file_field="file",
        response_type="json",
        link_path=["success_url"],
        requires_auth=False
    ),

    "uguu": HostConfig(
        name="Uguu.se",
        upload_endpoint="https://uguu.se/upload.php",
        method="POST",
        file_field="files[]",
        response_type="json",
        link_path=["files", 0, "url"],
        requires_auth=False
    ),

    "cockfile": HostConfig(
        name="Cockfile",
        upload_endpoint="https://cockfile.com/upload.php",
        method="POST",
        file_field="files[]",
        response_type="json",
        link_path=["files", 0, "url"],
        requires_auth=False
    ),

    "siasky": HostConfig(
        name="SiaSky",
        upload_endpoint="https://siasky.net/skynet/skyfile",
        method="POST",
        file_field="file",
        response_type="json",
        link_path=["skylink"],
        link_prefix="https://siasky.net/",
        requires_auth=False
    ),

    "freeimage": HostConfig(
        name="FreeImage.host",
        upload_endpoint="https://freeimage.host/api/1/upload",
        method="POST",
        file_field="source",
        extra_fields={"format": "json"},
        response_type="json",
        link_path=["image", "url"],
        requires_auth=False  # API key optional
    ),

    "imgbb": HostConfig(
        name="ImgBB",
        upload_endpoint="https://api.imgbb.com/1/upload",
        method="POST",
        file_field="image",
        response_type="json",
        link_path=["data", "url"],
        requires_auth=True  # Needs API key
    ),

    "imgur": HostConfig(
        name="Imgur",
        upload_endpoint="https://api.imgur.com/3/image",
        method="POST",
        auth_type="bearer",  # Client-ID in header
        file_field="image",
        response_type="json",
        link_path=["data", "link"],
        requires_auth=True  # Needs client ID
    ),

    "filebin2": HostConfig(
        name="FileBin.ca",
        upload_endpoint="https://filebin.ca/upload.php",
        method="POST",
        file_field="file",
        response_type="json",
        link_path=["url"],
        requires_auth=False
    ),

    "mixdrop": HostConfig(
        name="MixDrop",
        upload_endpoint="https://ul.mixdrop.co/api",
        method="POST",
        file_field="file",
        response_type="json",
        link_path=["result", "fileref"],
        link_prefix="https://mixdrop.co/f/",
        requires_auth=True  # Needs API key
    ),

    "uploadee": HostConfig(
        name="Upload.ee",
        upload_endpoint="https://www.upload.ee/api/upload",
        method="POST",
        file_field="file",
        response_type="json",
        link_path=["link"],
        requires_auth=False
    ),

    "filepost": HostConfig(
        name="FilePost",
        upload_endpoint="https://filepost.io/upload",
        method="POST",
        file_field="file",
        response_type="json",
        link_path=["url"],
        requires_auth=False
    ),

    "fileditch": HostConfig(
        name="FileDitch",
        upload_endpoint="https://fileditch.com/upload",
        method="POST",
        file_field="file",
        response_type="json",
        link_path=["url"],
        requires_auth=False
    ),

    "krakenfiles": HostConfig(
        name="KrakenFiles",
        upload_endpoint="https://krakenfiles.com/api/upload",
        method="POST",
        file_field="file",
        response_type="json",
        link_path=["url"],
        requires_auth=False  # API key optional for more features
    ),

    "zippyshare": HostConfig(
        name="ZippyShare",
        upload_endpoint="https://www.zippyshare.com/upload",
        method="POST",
        file_field="file",
        response_type="text",
        link_regex=r'href="([^"]+)" class="download"',
        link_prefix="https://www.zippyshare.com",
        requires_auth=False
    ),

    "sendspace": HostConfig(
        name="SendSpace",
        upload_endpoint="https://www.sendspace.com/api/upload",
        method="POST",
        file_field="file",
        response_type="json",
        link_path=["download_url"],
        requires_auth=False  # API key optional
    ),

    "mediafire": HostConfig(
        name="MediaFire",
        upload_endpoint="https://www.mediafire.com/api/1.5/upload/simple",
        method="POST",
        file_field="file",
        response_type="json",
        link_path=["response", "links", 0, "quickkey"],
        link_prefix="https://www.mediafire.com/file/",
        requires_auth=True  # Needs session token
    ),

    "mega": HostConfig(
        name="MEGA.nz",
        upload_endpoint="https://g.api.mega.co.nz/cs",  # Complex API
        method="POST",
        file_field="file",
        response_type="json",
        link_path=["f", 0, "h"],  # Handle
        link_prefix="https://mega.nz/file/",
        requires_auth=True  # Needs account
    ),

    "workupload": HostConfig(
        name="WorkUpload",
        upload_endpoint="https://workupload.com/api/upload",
        method="POST",
        file_field="file",
        response_type="json",
        link_path=["url"],
        requires_auth=False
    ),

    "uploadrar": HostConfig(
        name="UploadRAR",
        upload_endpoint="https://uploadrar.com/api/upload",
        method="POST",
        file_field="file",
        response_type="json",
        link_path=["url"],
        requires_auth=False
    ),

    "dosya": HostConfig(
        name="Dosya.tc",
        upload_endpoint="https://dosya.tc/upload",
        method="POST",
        file_field="file",
        response_type="json",
        link_path=["url"],
        requires_auth=False
    ),

    "usersdrive": HostConfig(
        name="UsersDrive",
        upload_endpoint="https://usersdrive.com/api/upload",
        method="POST",
        file_field="file",
        response_type="json",
        link_path=["url"],
        requires_auth=False
    ),

    "solidfiles": HostConfig(
        name="SolidFiles",
        upload_endpoint="https://www.solidfiles.com/api/v2/upload",
        method="POST",
        file_field="file",
        response_type="json",
        link_path=["url"],
        requires_auth=False
    ),

    "clicknupload": HostConfig(
        name="ClicknUpload",
        upload_endpoint="https://clicknupload.me/api/upload",
        method="POST",
        file_field="file",
        response_type="json",
        link_path=["url"],
        requires_auth=False  # API key optional
    ),

    "dailyuploads": HostConfig(
        name="DailyUploads",
        upload_endpoint="https://dailyuploads.net/api/upload",
        method="POST",
        file_field="file",
        response_type="json",
        link_path=["url"],
        requires_auth=False
    ),

    "userscloud": HostConfig(
        name="UsersCloud",
        upload_endpoint="https://userscloud.com/api/upload",
        method="POST",
        file_field="file",
        response_type="json",
        link_path=["url"],
        requires_auth=False
    ),

    "bayfiles": HostConfig(
        name="BayFiles",
        upload_endpoint="https://api.bayfiles.com/upload",
        method="POST",
        file_field="file",
        response_type="json",
        link_path=["data", "file", "url", "short"],
        requires_auth=False
    ),

    "uploadhaven": HostConfig(
        name="UploadHaven",
        upload_endpoint="https://uploadhaven.com/api/upload",
        method="POST",
        file_field="file",
        response_type="json",
        link_path=["url"],
        requires_auth=False
    ),

    "sendgb": HostConfig(
        name="SendGB",
        upload_endpoint="https://sendgb.com/api/upload",
        method="POST",
        file_field="file",
        response_type="json",
        link_path=["url"],
        requires_auth=False
    ),

    "fileconvoy": HostConfig(
        name="FileConvoy",
        upload_endpoint="https://www.fileconvoy.com/api/upload",
        method="POST",
        file_field="file",
        response_type="json",
        link_path=["url"],
        requires_auth=False
    ),

    "wormhole": HostConfig(
        name="Wormhole.app",
        upload_endpoint="https://wormhole.app/api/upload",
        method="POST",
        file_field="file",
        response_type="json",
        link_path=["url"],
        requires_auth=False
    ),

    "tempsend": HostConfig(
        name="TempSend",
        upload_endpoint="https://tempsend.com/send",
        method="POST",
        file_field="file",
        response_type="redirect",  # Returns 302 redirect with Location header
        requires_auth=False
    ),

    "filemail": HostConfig(
        name="Filemail",
        upload_endpoint="https://www.filemail.com/api/upload",
        method="POST",
        file_field="file",
        response_type="json",
        link_path=["url"],
        requires_auth=False  # Has size limits
    ),

    "pcloud": HostConfig(
        name="pCloud",
        upload_endpoint="https://api.pcloud.com/uploadfile",
        method="POST",
        file_field="file",
        response_type="json",
        link_path=["filelink"],
        requires_auth=True  # Needs auth token
    ),

    "filedot": HostConfig(
        name="FileDot.to",
        get_server="https://filedot.to/server",  # Get upload server URL first
        upload_endpoint="{server}/upload.cgi",  # Dynamic server endpoint
        method="POST",
        auth_type="session",  # Session-based authentication
        file_field="file_0",  # FileDot uses file_0 as field name
        extra_fields={"utype": "reg"},  # Required form field
        response_type="json",  # Returns JSON response
        link_path=["file_code"],  # file_code is the file identifier
        link_prefix="https://filedot.to/",  # Prepend domain to file code
        requires_auth=True,  # Requires login credentials (username:password)
        login_url="https://filedot.to/login",
        login_fields={"op": "login", "login": "{username}", "password": "{password}", "redirect": ""},
        session_id_regex=r'name="sess_id"\s+value="([^"]+)"'
    ),

    "rapidgator": HostConfig(
        name="RapidGator",
        upload_endpoint="",  # URL comes from init response
        method="POST",
        auth_type="token_login",  # Login to get token
        file_field="file",
        response_type="json",
        link_path=["response", "upload", "file", "url"],  # Final URL from upload_info
        requires_auth=True,  # Requires username:password
        # Token login configuration
        login_url="https://rapidgator.net/api/v2/user/login",
        login_fields={"login": "{username}", "password": "{password}"},
        token_path=["response", "token"],
        # Multi-step upload configuration
        upload_init_url="https://rapidgator.net/api/v2/file/upload?name={filename}&hash={hash}&size={size}&token={token}",
        upload_init_params=["filename", "hash", "size", "token"],
        upload_url_path=["response", "upload", "url"],
        upload_id_path=["response", "upload", "upload_id"],
        upload_poll_url="https://rapidgator.net/api/v2/file/upload_info?upload_id={upload_id}&token={token}",
        upload_poll_delay=1.0,
        upload_poll_retries=10,
        require_file_hash=True
    ),

    "filespace": HostConfig(
        name="FileSpace",
        upload_endpoint="https://phoebe.filespace.com/cgi-bin/upload.cgi?upload_id=",
        method="POST",
        auth_type="session",  # Session-based authentication
        file_field="file",  # Standard field name for file uploads
        extra_fields={},  # sess_id will be added from xfss cookie
        response_type="text",  # Parse HTML response with regex
        link_regex=r'https://filespace\.com/([a-z0-9]+)',  # Extract file code from link
        link_prefix="https://filespace.com/",  # Prepend domain to file code
        requires_auth=True,  # Requires login credentials (username:password)
        login_url="https://filespace.com/",
        login_fields={"op": "login", "redirect": "/", "login": "{username}", "password": "{password}"}
        # Note: FileSpace uses xfss cookie for session ID (handled in upload method)
    )
}


class MultiHostUploader:
    """Upload files to various hosting services"""

    def __init__(self, host: str, api_key: Optional[str] = None):
        self.host = host.lower()
        self.api_key = api_key
        self.session = requests.Session()

        if self.host not in HOSTS:
            raise ValueError(f"Unsupported host: {host}. Available: {', '.join(HOSTS.keys())}")

        self.config = HOSTS[self.host]

        if self.config.requires_auth and not api_key:
            raise ValueError(f"{self.config.name} requires credentials (format: username:password or api_key)")

        # Handle token-based authentication (login to get token)
        if self.config.auth_type == "token_login" and api_key:
            self.api_key = self._login_token_based(api_key)

        # Handle session-based authentication
        if self.config.auth_type == "session" and api_key:
            self._login_session_based(api_key)

    def _login_session_based(self, credentials: str) -> None:
        """Generic login for session-based file hosts"""
        if not self.config.login_url:
            raise ValueError(f"{self.config.name} requires login but no login_url configured")

        if ':' not in credentials:
            raise ValueError(f"{self.config.name} requires credentials in format 'username:password'")

        username, password = credentials.split(':', 1)

        try:
            # Step 1: GET login page first to extract any CSRF tokens
            get_response = self.session.get(self.config.login_url, timeout=30)
            get_response.raise_for_status()

            # Step 2: Extract CSRF token if present
            csrf_token = None
            token_match = re.search(r'<input[^>]+name=["\']token["\'][^>]+value=["\']([^"\']+)["\']', get_response.text)
            if token_match:
                csrf_token = token_match.group(1)
                print(f"✓ Extracted CSRF token for {self.config.name}", file=sys.stderr)

            # Step 3: Build login data by substituting placeholders
            login_data = {}
            for field, template in self.config.login_fields.items():
                value = template.replace("{username}", username).replace("{password}", password)
                login_data[field] = value

            # Add CSRF token if found
            if csrf_token:
                login_data["token"] = csrf_token

            # Step 4: POST login credentials
            print(f"DEBUG: Login data: {[(k, '***' if 'pass' in k.lower() else v) for k, v in login_data.items()]}", file=sys.stderr)
            response = self.session.post(self.config.login_url, data=login_data, timeout=30, allow_redirects=True)
            response.raise_for_status()
            print(f"DEBUG: Cookies: {dict(self.session.cookies)}", file=sys.stderr)

            # Step 5: Verify we got session cookies
            if not self.session.cookies:
                print(f"DEBUG: Response text: {response.text[:1000]}", file=sys.stderr)
                raise ValueError("Login failed: No session cookies received")

            print(f"✓ Logged in to {self.config.name} as {username}", file=sys.stderr)

        except Exception as e:
            raise ValueError(f"Failed to login to {self.config.name}: {e}")

    def _login_token_based(self, credentials: str) -> str:
        """Generic login that returns an auth token (like RapidGator)"""
        if not self.config.login_url or not self.config.token_path:
            raise ValueError(f"{self.config.name} requires login_url and token_path for token_login auth")

        if ':' not in credentials:
            raise ValueError(f"{self.config.name} requires credentials in format 'username:password'")

        username, password = credentials.split(':', 1)

        # Build login data by substituting placeholders
        login_data = {}
        for field, template in self.config.login_fields.items():
            value = template.replace("{username}", username).replace("{password}", password)
            login_data[field] = value

        try:
            # Try GET first (RapidGator uses GET)
            login_url = self.config.login_url
            if login_data:
                # URL encode parameters to handle special characters
                params = "&".join(f"{k}={quote(str(v))}" for k, v in login_data.items())
                login_url = f"{login_url}?{params}"

            response = self.session.get(login_url, timeout=30)
            response.raise_for_status()
            data = response.json()

            # Check for error response
            if data.get("status") != 200:
                error_msg = data.get("details", "Unknown error")
                raise ValueError(f"Login failed: {error_msg}")

            # Extract token from response
            token = self._extract_from_json(data, self.config.token_path)
            if not token:
                raise ValueError("Failed to extract token from login response")

            print(f"✓ Logged in to {self.config.name} as {username}", file=sys.stderr)
            return token

        except Exception as e:
            raise ValueError(f"Failed to login to {self.config.name}: {e}")

    def _extract_session_id(self, html: str) -> Optional[str]:
        """Extract session ID from HTML using configured regex"""
        if not self.config.session_id_regex:
            return None

        match = re.search(self.config.session_id_regex, html)
        return match.group(1) if match else None

    def _extract_from_json(self, data: Any, path: List[Union[str, int]]) -> Any:
        """Extract value from JSON using path (supports dict keys and array indices)"""
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

    def _calculate_file_hash(self, file_path: Path) -> str:
        """Calculate MD5 hash of file"""
        md5_hash = hashlib.md5()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b""):
                md5_hash.update(chunk)
        return md5_hash.hexdigest()

    def get_upload_server(self) -> str:
        """Get upload server for hosts that require it"""
        if not self.config.get_server:
            return self.config.upload_endpoint

        try:
            response = self.session.get(self.config.get_server, timeout=10)
            response.raise_for_status()
            data = response.json()

            # GoFile: server name in nested structure
            if self.host == "gofile":
                server = data["data"]["server"]
                return self.config.upload_endpoint.replace("{server}", server)

            # FileDot: full server URL returned
            if self.host == "filedot":
                server_url = data["url"]
                return self.config.upload_endpoint.replace("{server}", server_url)

            return self.config.upload_endpoint

        except Exception as e:
            print(f"Failed to get upload server: {e}", file=sys.stderr)
            return self.config.upload_endpoint

    def prepare_headers(self) -> Dict:
        """Prepare authorization headers if needed"""
        headers = {}

        if self.api_key and self.config.auth_type:
            if self.config.auth_type == "bearer":
                headers["Authorization"] = f"Bearer {self.api_key}"
            elif self.config.auth_type == "basic":
                # For Pixeldrain, the username is the API key
                auth_string = base64.b64encode(f":{self.api_key}".encode()).decode()
                headers["Authorization"] = f"Basic {auth_string}"

        return headers

    def upload_file(self, file_path: Path) -> Dict:
        """Upload file to the hosting service"""

        # Handle multi-step uploads (like RapidGator)
        if self.config.upload_init_url:
            return self._upload_multistep(file_path)

        # Handle session-based uploads that need dynamic session IDs (but not if they use get_server)
        if self.config.auth_type == "session" and self.config.session_id_regex and not self.config.get_server:
            return self._upload_session_based(file_path)

        # Get upload URL
        if "{filename}" in self.config.upload_endpoint:
            upload_url = self.config.upload_endpoint.replace("{filename}", file_path.name)
        else:
            upload_url = self.get_upload_server()

        # Prepare headers
        headers = self.prepare_headers()

        # For session-based auth with sess_id, fetch it before upload
        sess_id = None
        if self.config.auth_type == "session" and self.config.session_id_regex:
            upload_page_url = f"{self.config.upload_endpoint.split('/cgi-bin')[0] if '/cgi-bin' in self.config.upload_endpoint else self.config.upload_endpoint.rstrip('/')}/upload"
            # Extract base URL properly
            if self.host == "filedot":
                upload_page_url = "https://filedot.to/upload"

            page_resp = self.session.get(upload_page_url, timeout=30)
            page_resp.raise_for_status()
            sess_id = self._extract_session_id(page_resp.text)

        # Prepare the file and request
        with open(file_path, 'rb') as f:
            if self.config.method == "PUT":
                # For PUT requests (like Pixeldrain, Transfer.sh)
                response = self.session.put(
                    upload_url,
                    data=f,
                    headers=headers,
                    timeout=300
                )
            else:
                # For POST requests (most hosts)
                files = {self.config.file_field: (file_path.name, f, self.get_mime_type(file_path))}
                data = self.config.extra_fields.copy()

                # Add sess_id if we extracted it
                # FileSpace uses xfss cookie for session ID
                if self.host == "filespace" and "xfss" in self.session.cookies:
                    data["sess_id"] = self.session.cookies["xfss"]

                if sess_id:
                    data["sess_id"] = sess_id

                # Handle Litterbox time parameter from command line
                if self.host == "litterbox" and len(sys.argv) > 3:
                    time_param = sys.argv[3]
                    if time_param in ["1h", "12h", "24h", "72h"]:
                        data["time"] = time_param

                response = self.session.post(
                    upload_url,
                    files=files,
                    data=data,
                    headers=headers,
                    timeout=300,
                    allow_redirects=(self.host == "filespace")  # FileSpace needs redirects, others use Location header
                )

        response.raise_for_status()
        return self.parse_response(response)

    def _upload_session_based(self, file_path: Path) -> Dict[str, Any]:
        """Upload file to session-based hosts that require dynamic session IDs"""
        # Get the upload page to extract session ID
        upload_page_url = f"{self.config.upload_endpoint.rstrip('/')}/upload"
        response = self.session.get(upload_page_url, timeout=30)
        response.raise_for_status()

        # Extract session ID
        sess_id = self._extract_session_id(response.text)
        if not sess_id:
            raise ValueError(f"Could not extract session ID from {self.config.name} upload page")

        # Build upload URL with session ID
        upload_url = f"{self.config.upload_endpoint.rstrip('/')}/cgi-bin/upload.cgi?upload_id={sess_id}&utype=reg"

        # Upload the file
        with open(file_path, 'rb') as f:
            files = {self.config.file_field: (file_path.name, f, self.get_mime_type(file_path))}
            data = {
                'sess_id': sess_id,
                'utype': 'reg',
                **self.config.extra_fields
            }

            response = self.session.post(upload_url, files=files, data=data, timeout=300)
            response.raise_for_status()

        return self.parse_response(response)

    def _upload_multistep(self, file_path: Path) -> Dict[str, Any]:
        """Generic multi-step upload (init → upload → poll)"""
        # Step 1: Build init URL with parameters
        if not self.config.upload_init_url:
            raise ValueError("upload_init_url not configured for multi-step upload")

        init_url = self.config.upload_init_url
        file_size = file_path.stat().st_size

        replacements = {
            "filename": file_path.name,
            "size": str(file_size),
            "token": self.api_key or ""
        }

        # Calculate hash if required
        if self.config.require_file_hash:
            print(f"Calculating file hash...", file=sys.stderr)
            replacements["hash"] = self._calculate_file_hash(file_path)

        # Replace placeholders
        for key, value in replacements.items():
            init_url = init_url.replace(f"{{{key}}}", value)

        # Step 2: Call init API
        print(f"Initializing upload...", file=sys.stderr)
        init_resp = self.session.get(init_url, timeout=30)
        init_resp.raise_for_status()
        init_data = init_resp.json()

        # Check API response status first
        api_status = init_data.get("status")
        if api_status and api_status != 200:
            error_details = self._extract_from_json(init_data, ["response", "details"]) or \
                           self._extract_from_json(init_data, ["response", "msg"]) or \
                           f"API returned status {api_status}"
            print(f"API Error Response: {json.dumps(init_data, indent=2)}", file=sys.stderr)
            raise ValueError(f"Upload initialization failed: {error_details}")

        # Extract upload URL and upload ID
        if not self.config.upload_url_path or not self.config.upload_id_path:
            raise ValueError("upload_url_path and upload_id_path required for multi-step upload")

        upload_url = self._extract_from_json(init_data, self.config.upload_url_path)
        upload_id = self._extract_from_json(init_data, self.config.upload_id_path)
        upload_state = self._extract_from_json(init_data, ["response", "upload", "state"])

        # Check if file already exists (RapidGator deduplication)
        if upload_state == 2 or (upload_url is None and upload_state is not None):
            # File already exists, get the existing file URL
            existing_url = self._extract_from_json(init_data, ["response", "upload", "file", "url"])
            if existing_url:
                print(f"File already exists on server (hash match)", file=sys.stderr)
                print(f"Using existing file URL", file=sys.stderr)
                return {
                    "host": self.config.name,
                    "status": "success",
                    "timestamp": datetime.now().isoformat(),
                    "url": existing_url,
                    "upload_id": upload_id,
                    "deduplication": True,
                    "raw_response": init_data,
                    "success": True
                }

        if not upload_url:
            error = self._extract_from_json(init_data, ["response", "details"]) or \
                   self._extract_from_json(init_data, ["response", "msg"]) or \
                   "Upload initialization failed"
            print(f"Debug - Init Response: {json.dumps(init_data, indent=2)}", file=sys.stderr)
            raise ValueError(f"Failed to get upload URL: {error}")

        if not upload_id:
            raise ValueError("Failed to get upload ID from init response")

        print(f"Got upload ID: {upload_id}", file=sys.stderr)

        # Step 3: Upload file
        print(f"Uploading file...", file=sys.stderr)
        with open(file_path, 'rb') as f:
            files = {self.config.file_field: (file_path.name, f, self.get_mime_type(file_path))}
            upload_resp = self.session.post(upload_url, files=files, timeout=300)
            upload_resp.raise_for_status()

        # Step 4: Poll for completion
        if self.config.upload_poll_url and self.config.link_path:
            print(f"Waiting for upload to process...", file=sys.stderr)
            time.sleep(self.config.upload_poll_delay)

            poll_url = self.config.upload_poll_url.replace("{upload_id}", upload_id).replace("{token}", self.api_key or "")

            for attempt in range(self.config.upload_poll_retries):
                poll_resp = self.session.get(poll_url, timeout=30)
                poll_resp.raise_for_status()
                poll_data = poll_resp.json()

                # Check if we got the final URL
                final_url = self._extract_from_json(poll_data, self.config.link_path)
                if final_url:
                    print(f"Upload complete!", file=sys.stderr)
                    return {
                        "host": self.config.name,
                        "status": "success",
                        "timestamp": datetime.now().isoformat(),
                        "url": final_url,
                        "upload_id": upload_id,
                        "raw_response": poll_data,
                        "success": True
                    }

                # Not ready yet, wait and retry
                if attempt < self.config.upload_poll_retries - 1:
                    time.sleep(self.config.upload_poll_delay)

            raise ValueError("Upload processing timeout - file may still be uploading")

        # No polling configured, return init response
        return self.parse_response(init_resp)

    def get_mime_type(self, file_path: Path) -> str:
        """Get MIME type of file"""
        mime_type, _ = mimetypes.guess_type(str(file_path))
        return mime_type or 'application/octet-stream'

    def parse_response(self, response: requests.Response) -> Dict[str, Any]:
        """Parse response and extract download link"""
        result: Dict[str, Any] = {
            "host": self.config.name,
            "status": "success",
            "timestamp": datetime.now().isoformat()
        }

        if self.config.response_type == "json":
            data = response.json()
            result["raw_response"] = data

            # Handle array responses (e.g., FileDot returns [{...}])
            if isinstance(data, list) and len(data) > 0:
                data = data[0]

            # Check for errors in response
            if isinstance(data, dict):
                if data.get("file_status") == "OK":
                    # Success case for FileDot
                    pass
                elif data.get("file_status"):
                    # Error case
                    result["error"] = f"Upload failed: {data.get('file_status')}"
                    result["success"] = False
                    return result

            # Extract link using JSON path
            if self.config.link_path:
                link = data
                for key in self.config.link_path:
                    link = link.get(key) if isinstance(link, dict) else None
                    if link is None:
                        break

                if link:
                    # Apply prefix/suffix
                    result["url"] = self.config.link_prefix + str(link) + self.config.link_suffix

                    # Apply regex transformation if needed
                    if self.config.link_regex and result["url"]:
                        match = re.search(self.config.link_regex, result["url"])
                        if match:
                            if match.groups():
                                result["url"] = self.config.link_prefix + match.group(1) + self.config.link_suffix

        elif self.config.response_type == "text":
            text = response.text.strip()
            result["raw_response"] = text

            if self.config.link_regex:
                # Extract link using regex
                match = re.search(self.config.link_regex, text)
                if match:
                    extracted = match.group(1) if match.groups() else match.group(0)
                    result["url"] = self.config.link_prefix + extracted + self.config.link_suffix
            else:
                # Assume the whole response is the link
                result["url"] = text

        elif self.config.response_type == "redirect":
            # Extract URL from Location header (for services that use HTTP redirects)
            location = response.headers.get("Location")
            if location:
                result["url"] = location
                result["raw_response"] = {"status_code": response.status_code, "location": location}
            else:
                result["error"] = "No Location header found in redirect response"
                result["raw_response"] = {"status_code": response.status_code, "headers": dict(response.headers)}

        # Add file info
        if "url" in result:
            result["success"] = True
        else:
            result["success"] = False
            if "error" not in result:
                result["error"] = "Could not extract download link"

        return result


def main():
    """Main entry point"""

    if len(sys.argv) < 3:
        print("Usage: python multi_host_uploader.py <host> <file> [api_key]", file=sys.stderr)
        print(f"Available hosts: {', '.join(HOSTS.keys())}", file=sys.stderr)
        print("\nExamples:", file=sys.stderr)
        print("  python multi_host_uploader.py gofile test.jpg", file=sys.stderr)
        print("  python multi_host_uploader.py pixeldrain test.jpg your_api_key", file=sys.stderr)
        print("  python multi_host_uploader.py litterbox test.jpg 72h", file=sys.stderr)
        print("  python multi_host_uploader.py filedot test.jpg username:password", file=sys.stderr)
        print("  python multi_host_uploader.py rapidgator test.jpg username:password", file=sys.stderr)
        sys.exit(1)

    host = sys.argv[1]
    file_path = Path(sys.argv[2])
    api_key = sys.argv[3] if len(sys.argv) > 3 else None

    if not file_path.exists():
        error_output = {
            "error": f"File not found: {file_path}",
            "status": "failed"
        }
        print(json.dumps(error_output))
        sys.exit(1)

    if file_path.is_dir():
        error_output = {
            "error": f"Path is a directory: {file_path}",
            "status": "failed"
        }
        print(json.dumps(error_output))
        sys.exit(1)

    try:
        uploader = MultiHostUploader(host, api_key)
        print(f"Uploading to {uploader.config.name}...", file=sys.stderr)

        result = uploader.upload_file(file_path)

        # Add file info
        result["file_name"] = file_path.name
        result["file_size"] = file_path.stat().st_size
        result["file_size_mb"] = f"{result['file_size'] / (1024*1024):.2f} MB"

        # Output JSON for imxup
        print(json.dumps(result, indent=2))

        # Summary to stderr
        if result.get("success"):
            print(f"\n✓ Upload successful!", file=sys.stderr)
            print(f"URL: {result.get('url')}", file=sys.stderr)
        else:
            print(f"\n✗ Upload failed: {result.get('error')}", file=sys.stderr)

    except Exception as e:
        error_output = {
            "error": str(e),
            "status": "failed",
            "timestamp": datetime.now().isoformat()
        }
        print(json.dumps(error_output))
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()