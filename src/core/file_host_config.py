"""
File host configuration system for multi-host uploads.

Loads host configurations from JSON files in:
- Built-in: assets/hosts/ (shipped with imxup)
- Built-in logos: assets/hosts/logo/ (host logo images)
- Custom: ~/.imxup/hosts/ (user-created configs)
"""

import os
import json
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, field
from threading import Lock

from imxup import get_central_store_base_path
from src.utils.logger import log


# Module-level locks for thread safety
_config_manager_lock = Lock()  # Protects singleton initialization of _config_manager
_ini_file_lock = Lock()  # Protects INI file read/write operations to prevent race conditions


@dataclass
class HostConfig:
    """Configuration for a file hosting service."""

    # Basic info
    name: str
    icon: Optional[str] = None
    referral_url: Optional[str] = None  # Referral link for the host
    requires_auth: bool = False
    auth_type: Optional[str] = None  # "bearer", "basic", "session", "token_login"

    # Upload configuration
    get_server: Optional[str] = None  # URL to get upload server
    server_response_path: Optional[List[Union[str, int]]] = None  # JSON path to server URL in response
    server_session_id_path: Optional[List[Union[str, int]]] = None  # JSON path to single-use sess_id in get_server response (Katfile-style)
    upload_endpoint: str = ""
    method: str = "POST"  # "POST" or "PUT"
    file_field: str = "file"
    extra_fields: Dict[str, str] = field(default_factory=dict)

    # Response parsing
    response_type: str = "json"  # "json", "text", "regex", "redirect"
    link_path: Optional[List[Union[str, int]]] = None  # JSON path to download link
    link_prefix: str = ""
    link_suffix: str = ""
    link_regex: Optional[str] = None
    file_id_path: Optional[List[Union[str, int]]] = None  # JSON path to file ID (for deletion, tracking)

    # Authentication (session-based)
    login_url: Optional[str] = None
    login_fields: Dict[str, str] = field(default_factory=dict)
    session_id_regex: Optional[str] = None
    upload_page_url: Optional[str] = None  # Page to visit before upload to extract session ID
    session_cookie_name: Optional[str] = None  # Cookie name to use as sess_id (e.g., "xfss" for FileSpace)
    captcha_regex: Optional[str] = None  # Regex to extract captcha code from HTML
    captcha_field: str = "code"  # Field name for captcha submission
    captcha_transform: Optional[str] = None  # Transformation: "move_3rd_to_front", "reverse", etc.

    # Authentication (token-based)
    token_path: Optional[List[Union[str, int]]] = None  # JSON path to token

    # Multi-step upload (like RapidGator)
    upload_init_url: Optional[str] = None
    upload_init_params: List[str] = field(default_factory=list)
    upload_url_path: Optional[List[Union[str, int]]] = None
    upload_id_path: Optional[List[Union[str, int]]] = None
    upload_poll_url: Optional[str] = None
    upload_poll_delay: float = 1.0
    upload_poll_retries: int = 10
    require_file_hash: bool = False

    # K2S-specific multi-step enhancements
    init_method: str = "GET"  # "GET" or "POST"
    init_body_json: bool = False  # Send JSON POST body instead of query params
    file_field_path: Optional[List[Union[str, int]]] = None  # Path to dynamic file field name
    form_data_path: Optional[List[Union[str, int]]] = None  # Path to form_data dict (ajax, params, signature)

    # Default values for INI initialization (NOT runtime values - read from INI)
    # These are copied to INI on first launch, then always read from INI
    defaults: Dict[str, Any] = field(default_factory=dict)

    # Delete functionality
    delete_url: Optional[str] = None  # URL to delete files (e.g., with {file_id} and {token} placeholders)
    delete_method: str = "GET"  # HTTP method for delete
    delete_params: List[str] = field(default_factory=list)  # Required parameters

    # User info / storage monitoring
    user_info_url: Optional[str] = None  # URL to get user info (storage, premium status, etc.)
    storage_total_path: Optional[List[Union[str, int]]] = None  # JSON path to total storage
    storage_used_path: Optional[List[Union[str, int]]] = None  # JSON path to used storage
    storage_left_path: Optional[List[Union[str, int]]] = None  # JSON path to remaining storage
    storage_regex: Optional[str] = None  # Regex to extract storage from HTML (for non-JSON responses)
    premium_status_path: Optional[List[Union[str, int]]] = None  # JSON path to premium status

    # K2S-specific user info enhancements
    user_info_method: str = "GET"  # "GET" or "POST"
    user_info_body_json: bool = False  # Send JSON POST body
    account_expires_path: Optional[List[Union[str, int]]] = None  # JSON path to account expiration timestamp

    # K2S-specific delete enhancements
    delete_body_json: bool = False  # Send JSON POST body for delete

    # Token caching
    token_ttl: Optional[int] = None  # Token time-to-live in seconds (None = no expiration)

    # Session token lifecycle management
    session_token_ttl: Optional[int] = None  # Sess_id TTL in seconds (for proactive refresh)
    stale_token_patterns: List[str] = field(default_factory=list)  # Regex patterns to detect stale tokens
    check_body_on_success: bool = False  # Check response body for stale patterns even on HTTP 200/204

    # Upload timeout configuration
    inactivity_timeout: int = 300  # Seconds of no progress before abort (default 5 minutes)
    upload_timeout: Optional[int] = None  # Total time limit in seconds (None = unlimited)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'HostConfig':
        """Create HostConfig from dictionary (loaded from JSON)."""

        # Extract nested structures with defaults
        upload_config = data.get('upload', {})
        response_config = data.get('response', {})
        defaults_config = data.get('defaults', {})  # New unified defaults section
        auth_config = data.get('auth', {})
        multistep_config = data.get('multistep', {})

        return cls(
            # Basic info
            name=data.get('name', ''),
            icon=data.get('icon'),
            referral_url=data.get('referral_url'),
            requires_auth=data.get('requires_auth', False),
            auth_type=data.get('auth_type'),

            # Upload config
            get_server=upload_config.get('get_server'),
            server_response_path=upload_config.get('server_response_path'),
            server_session_id_path=upload_config.get('server_session_id_path'),
            upload_endpoint=upload_config.get('endpoint', ''),
            method=upload_config.get('method', 'POST'),
            file_field=upload_config.get('file_field', 'file'),
            extra_fields=upload_config.get('extra_fields', {}),

            # Response parsing
            response_type=response_config.get('type', 'json'),
            link_path=response_config.get('link_path'),
            link_prefix=response_config.get('link_prefix', ''),
            link_suffix=response_config.get('link_suffix', ''),
            link_regex=response_config.get('link_regex'),
            file_id_path=response_config.get('file_id_path'),

            # Session-based auth
            login_url=auth_config.get('login_url'),
            login_fields=auth_config.get('login_fields', {}),
            session_id_regex=auth_config.get('session_id_regex'),
            upload_page_url=auth_config.get('upload_page_url'),
            session_cookie_name=auth_config.get('session_cookie_name'),
            captcha_regex=auth_config.get('captcha_regex'),
            captcha_field=auth_config.get('captcha_field', 'code'),
            captcha_transform=auth_config.get('captcha_transform'),

            # Token-based auth
            token_path=auth_config.get('token_path'),

            # Multi-step upload
            upload_init_url=multistep_config.get('init_url'),
            upload_init_params=multistep_config.get('init_params', []),
            upload_url_path=multistep_config.get('upload_url_path'),
            upload_id_path=multistep_config.get('upload_id_path'),
            upload_poll_url=multistep_config.get('poll_url'),
            upload_poll_delay=multistep_config.get('poll_delay', 1.0),
            upload_poll_retries=multistep_config.get('poll_retries', 10),
            require_file_hash=multistep_config.get('require_hash', False),

            # K2S-specific multi-step enhancements
            init_method=multistep_config.get('init_method', 'GET'),
            init_body_json=multistep_config.get('init_body_json', False),
            file_field_path=multistep_config.get('file_field_path'),
            form_data_path=multistep_config.get('form_data_path'),

            # Default values (for INI initialization only)
            defaults=defaults_config,

            # Delete functionality
            delete_url=data.get('delete', {}).get('url'),
            delete_method=data.get('delete', {}).get('method', 'GET'),
            delete_params=data.get('delete', {}).get('params', []),

            # User info / storage
            user_info_url=data.get('user_info', {}).get('url'),
            storage_total_path=data.get('user_info', {}).get('storage_total_path'),
            storage_used_path=data.get('user_info', {}).get('storage_used_path'),
            storage_left_path=data.get('user_info', {}).get('storage_left_path'),
            storage_regex=data.get('user_info', {}).get('storage_regex'),
            premium_status_path=data.get('user_info', {}).get('premium_status_path'),

            # K2S-specific user info enhancements
            user_info_method=data.get('user_info', {}).get('method', 'GET'),
            user_info_body_json=data.get('user_info', {}).get('body_json', False),
            account_expires_path=data.get('user_info', {}).get('account_expires_path'),

            # K2S-specific delete enhancements
            delete_body_json=data.get('delete', {}).get('body_json', False),

            # Token caching
            token_ttl=auth_config.get('token_ttl'),

            # Session token lifecycle
            session_token_ttl=auth_config.get('session_token_ttl'),
            stale_token_patterns=auth_config.get('stale_token_patterns', []),
            check_body_on_success=auth_config.get('check_body_on_success', False),

            # Upload timeout configuration
            inactivity_timeout=upload_config.get('inactivity_timeout', 300),
            upload_timeout=upload_config.get('upload_timeout'),
        )


# ============================================================================
# SIMPLE CONFIG FUNCTIONS - Use these everywhere
# ============================================================================

# Hardcoded default values (used as final fallback)
_HARDCODED_DEFAULTS = {
    "max_connections": 2,
    "max_file_size_mb": None,
    "auto_retry": True,
    "max_retries": 3,
    "inactivity_timeout": 300,
    "upload_timeout": None,
    "bbcode_format": ""
}


def get_file_host_setting(host_id: str, key: str, value_type: str = "str") -> Any:
    """Get a file host setting. Simple: INI → JSON default → hardcoded default.

    Special handling for user preferences:
    - 'enabled': Defaults to False if not in INI (hosts disabled by default)
    - 'trigger': Defaults to 'disabled' if not in INI

    Args:
        host_id: Host identifier (e.g., 'filedot')
        key: Setting name (e.g., 'enabled', 'trigger', 'max_connections')
        value_type: 'str', 'bool', or 'int'

    Returns:
        Setting value from INI (if set), else JSON default, else hardcoded default
    """
    from imxup import get_config_path
    import configparser
    import os

    # 1. Check INI first (user override)
    ini_path = get_config_path()
    if os.path.exists(ini_path):
        with _ini_file_lock:  # Thread-safe INI access
            cfg = configparser.ConfigParser()
            cfg.read(ini_path)
            if cfg.has_section("FILE_HOSTS"):
                ini_key = f"{host_id}_{key}"
                if cfg.has_option("FILE_HOSTS", ini_key):
                    try:
                        raw_value = cfg.get("FILE_HOSTS", ini_key)
                        # Skip empty values - treat as "not set" and use defaults
                        if not raw_value or raw_value.strip() == "":
                            # Fall through to default value logic below
                            pass
                        elif value_type == "bool":
                            return cfg.getboolean("FILE_HOSTS", ini_key)
                        elif value_type == "int":
                            return cfg.getint("FILE_HOSTS", ini_key)
                        else:
                            return raw_value
                    except (ValueError, TypeError, configparser.Error) as e:
                        log(f"Invalid value for {ini_key} in INI file: {e}. Using default.",
                            level="warning", category="file_hosts")
                        # Fall through to default value logic below

    # 2. User preferences (not in INI = disabled)
    if key == "enabled":
        return False
    if key == "trigger":
        return "disabled"

    # 3. Host config defaults from JSON
    config_manager = get_config_manager()
    host = config_manager.hosts.get(host_id)
    if host and host.defaults and key in host.defaults:
        return host.defaults[key]

    # 4. Hardcoded fallback
    if key in _HARDCODED_DEFAULTS:
        return _HARDCODED_DEFAULTS[key]
    else:
        log(f"Unknown file host setting requested: {key} for {host_id}",
            level="warning", category="file_hosts")
        return None


def save_file_host_setting(host_id: str, key: str, value: Any) -> None:
    """Save a file host setting to INI. Simple: just write it.

    Args:
        host_id: Host identifier (e.g., 'filedot')
        key: Setting name (e.g., 'enabled', 'trigger')
        value: Value to save

    Raises:
        ValueError: If host_id doesn't exist or key is invalid
    """
    from imxup import get_config_path
    import configparser
    import os

    # Validate host exists
    config_manager = get_config_manager()
    if host_id not in config_manager.hosts:
        raise ValueError(f"Unknown host ID: {host_id}")

    # Validate key (whitelist approach)
    valid_keys = {"enabled", "trigger", "max_connections", "max_file_size_mb",
                  "auto_retry", "max_retries", "inactivity_timeout", "upload_timeout",
                  "bbcode_format"}
    if key not in valid_keys:
        raise ValueError(f"Invalid setting key: {key}")

    # Validate value based on key type
    if key == "enabled":
        if not isinstance(value, bool):
            raise ValueError(f"enabled must be bool, got {type(value).__name__}")
    elif key == "trigger":
        valid_triggers = {"disabled", "on_added", "on_started", "on_completed"}
        if value not in valid_triggers:
            raise ValueError(f"trigger must be one of {valid_triggers}, got {value}")
    elif key in {"max_connections", "max_retries"}:
        # Reject booleans explicitly (bool is subclass of int in Python)
        if isinstance(value, bool):
            raise ValueError(f"{key} must be int, not bool")
        if not isinstance(value, int) or value < 1 or value > 100:
            raise ValueError(f"{key} must be int between 1-100, got {value}")
    elif key == "inactivity_timeout":
        # Reject booleans explicitly (bool is subclass of int in Python)
        if isinstance(value, bool):
            raise ValueError(f"{key} must be int, not bool")
        if not isinstance(value, int) or value < 30 or value > 3600:
            raise ValueError(f"{key} must be int between 30-3600, got {value}")
    elif key in {"max_file_size_mb", "upload_timeout"}:
        # Reject booleans explicitly (bool is subclass of int in Python)
        if isinstance(value, bool):
            raise ValueError(f"{key} must be number, not bool")
        if value is not None and (not isinstance(value, (int, float)) or value <= 0):
            raise ValueError(f"{key} must be positive number or None, got {value}")
    elif key == "auto_retry":
        if not isinstance(value, bool):
            raise ValueError(f"auto_retry must be bool, got {type(value).__name__}")
    elif key == "bbcode_format":
        if value is not None and not isinstance(value, str):
            raise ValueError(f"bbcode_format must be str or None, got {type(value).__name__}")

    # Thread-safe read-modify-write operation
    with _ini_file_lock:
        ini_path = get_config_path()  # Get path inside lock to prevent race condition
        cfg = configparser.ConfigParser()

        # Load existing INI
        if os.path.exists(ini_path):
            cfg.read(ini_path)

        # Ensure section exists
        if not cfg.has_section("FILE_HOSTS"):
            cfg.add_section("FILE_HOSTS")

        # Write value
        if value is None:
            # Don't write None to INI - let get_file_host_setting() use defaults
            # Remove key if it exists to clean up INI file
            if cfg.has_option("FILE_HOSTS", f"{host_id}_{key}"):
                cfg.remove_option("FILE_HOSTS", f"{host_id}_{key}")
        else:
            cfg.set("FILE_HOSTS", f"{host_id}_{key}", str(value))

        # Save to file
        try:
            with open(ini_path, 'w') as f:
                cfg.write(f)
            log(f"Saved {host_id}_{key}={value} to INI", level="debug", category="file_hosts")
        except Exception as e:
            log(f"Error saving setting {key} for {host_id}: {e}",
                level="error", category="file_hosts")
            raise


class FileHostConfigManager:
    """Manages loading and accessing file host configurations."""

    def __init__(self):
        self.hosts: Dict[str, HostConfig] = {}
        self.builtin_dir = self._get_builtin_hosts_dir()
        self.custom_dir = self._get_custom_hosts_dir()

    def _get_builtin_hosts_dir(self) -> Path:
        """Get path to built-in host configs (shipped with imxup)."""
        # Use centralized get_project_root() for consistency with icon loading
        from imxup import get_project_root
        project_root = get_project_root()
        hosts_dir = Path(project_root) / "assets" / "hosts"
        return hosts_dir

    def _get_custom_hosts_dir(self) -> Path:
        """Get path to user custom host configs."""
        base_dir = get_central_store_base_path()
        hosts_dir = Path(base_dir) / "hosts"
        hosts_dir.mkdir(parents=True, exist_ok=True)
        return hosts_dir

    def load_all_hosts(self) -> None:
        """Load all host configurations from built-in and custom directories."""
        self.hosts.clear()

        # Load built-in hosts first
        log(f"Loading hosts from built-in dir: {self.builtin_dir}", level="debug", category="file_hosts")
        if self.builtin_dir.exists():
            self._load_hosts_from_dir(self.builtin_dir, is_builtin=True)
        else:
            log(f"Built-in hosts directory does not exist: {self.builtin_dir}", level="warning", category="file_hosts")

        # Load custom hosts (can override built-in)
        log(f"Loading hosts from custom dir: {self.custom_dir}", level="debug", category="file_hosts")
        if self.custom_dir.exists():
            self._load_hosts_from_dir(self.custom_dir, is_builtin=False)

    def reload_hosts(self) -> None:
        """Reload all host configurations (useful for testing or after config changes)."""
        log("Reloading all host configurations", level="info", category="file_hosts")
        self.load_all_hosts()

    def _load_hosts_from_dir(self, directory: Path, is_builtin: bool) -> None:
        """Load host configs from a directory."""
        if not directory.exists():
            return

        for json_file in directory.glob("*.json"):
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                # Validate JSON structure
                if not isinstance(data, dict):
                    raise ValueError(f"Config must be a dictionary, got {type(data)}")
                if 'name' not in data:
                    raise ValueError("Config missing required field: 'name'")

                host_config = HostConfig.from_dict(data)
                host_id = json_file.stem  # filename without .json

                self.hosts[host_id] = host_config

                source = "built-in" if is_builtin else "custom"
                log(f"Loaded {source} host config file for {host_config.name} ({json_file})", level="debug", category="file_hosts")

            except Exception as e:
                log(f"Error loading host config {json_file}: {e}", level="error")

    def get_host(self, host_id: str) -> Optional[HostConfig]:
        """Get a host configuration by ID."""
        return self.hosts.get(host_id)

    def get_enabled_hosts(self) -> Dict[str, HostConfig]:
        """Get all enabled host configurations."""
        result = {}
        for host_id, host_config in self.hosts.items():
            if get_file_host_setting(host_id, "enabled", "bool"):
                result[host_id] = host_config
        return result

    def get_hosts_by_trigger(self, trigger: str) -> Dict[str, HostConfig]:
        """Get hosts that should trigger on a specific event.

        Args:
            trigger: 'added', 'started', or 'completed' (without 'on_' prefix)

        Returns:
            Dictionary of host_id -> HostConfig that match the trigger
        """
        result = {}
        # Normalize trigger to expected format
        expected_trigger = f"on_{trigger}"

        for host_id, host_config in self.hosts.items():
            # Check if enabled
            if not get_file_host_setting(host_id, "enabled", "bool"):
                continue

            # Check trigger mode
            trigger_mode = get_file_host_setting(host_id, "trigger", "str")

            # Match trigger event
            if trigger_mode == expected_trigger:
                result[host_id] = host_config

        return result

    def get_all_host_ids(self) -> List[str]:
        """Get list of all host IDs."""
        return list(self.hosts.keys())

    def enable_host(self, host_id: str) -> bool:
        """Enable a host."""
        if host_id in self.hosts:
            save_file_host_setting(host_id, "enabled", True)
            return True
        return False

    def disable_host(self, host_id: str) -> bool:
        """Disable a host."""
        if host_id in self.hosts:
            save_file_host_setting(host_id, "enabled", False)
            return True
        return False


# Global instance (singleton pattern with thread-safety)
_config_manager: Optional[FileHostConfigManager] = None


def get_config_manager() -> FileHostConfigManager:
    """Get or create the global FileHostConfigManager instance (thread-safe)."""
    global _config_manager

    # Double-checked locking pattern for thread safety
    if _config_manager is None:
        with _config_manager_lock:
            if _config_manager is None:
                _config_manager = FileHostConfigManager()
                _config_manager.load_all_hosts()
    return _config_manager
