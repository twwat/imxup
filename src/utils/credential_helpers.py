"""
Credential management helper utilities.

Provides secure credential storage helpers and utilities for working with
encrypted credentials and authentication tokens.
"""

import hashlib
import secrets
import base64
from typing import Optional, Dict, Any
from pathlib import Path
import json


class CredentialError(Exception):
    """Raised when credential operations fail."""
    pass


def generate_salt(length: int = 32) -> bytes:
    """
    Generate a cryptographically secure random salt.

    Args:
        length: Length of the salt in bytes (default 32)

    Returns:
        bytes: Random salt
    """
    return secrets.token_bytes(length)


def derive_key_pbkdf2(password: str, salt: bytes, iterations: int = 100000) -> bytes:
    """
    Derive an encryption key from a password using PBKDF2.

    This is more secure than simple hashing as it uses a salt and iterations
    to make brute-force attacks more difficult.

    Args:
        password: Password to derive key from
        salt: Salt for key derivation
        iterations: Number of PBKDF2 iterations (higher is more secure)

    Returns:
        bytes: Derived 32-byte key
    """
    return hashlib.pbkdf2_hmac('sha256', password.encode(), salt, iterations)


def hash_password(password: str, salt: Optional[bytes] = None) -> tuple[str, str]:
    """
    Hash a password with a salt.

    Args:
        password: Password to hash
        salt: Optional salt (generated if not provided)

    Returns:
        tuple: (hashed_password_base64, salt_base64)
    """
    if salt is None:
        salt = generate_salt()

    # Use PBKDF2 for password hashing
    hashed = derive_key_pbkdf2(password, salt)

    # Return as base64 strings for storage
    return (
        base64.b64encode(hashed).decode('ascii'),
        base64.b64encode(salt).decode('ascii')
    )


def verify_password(password: str, hashed_b64: str, salt_b64: str) -> bool:
    """
    Verify a password against a hash.

    Args:
        password: Password to verify
        hashed_b64: Base64-encoded hashed password
        salt_b64: Base64-encoded salt

    Returns:
        bool: True if password matches
    """
    try:
        # Decode from base64
        salt = base64.b64decode(salt_b64)
        expected_hash = base64.b64decode(hashed_b64)

        # Hash the provided password with the same salt
        actual_hash = derive_key_pbkdf2(password, salt)

        # Constant-time comparison to prevent timing attacks
        return secrets.compare_digest(actual_hash, expected_hash)
    except Exception:
        return False


def generate_api_token(length: int = 32) -> str:
    """
    Generate a secure random API token.

    Args:
        length: Length of the token in bytes (default 32)

    Returns:
        str: URL-safe base64-encoded token
    """
    return secrets.token_urlsafe(length)


def mask_credential(credential: str, visible_chars: int = 4) -> str:
    """
    Mask a credential for display purposes.

    Args:
        credential: The credential to mask
        visible_chars: Number of characters to show at the end

    Returns:
        str: Masked credential (e.g., "****xyz123")
    """
    if not credential:
        return ""

    if len(credential) <= visible_chars:
        return "*" * len(credential)

    masked_length = len(credential) - visible_chars
    return "*" * masked_length + credential[-visible_chars:]


class CredentialValidator:
    """
    Validate credentials against security requirements.
    """

    @staticmethod
    def validate_password_strength(password: str, min_length: int = 8) -> tuple[bool, list[str]]:
        """
        Validate password strength.

        Args:
            password: Password to validate
            min_length: Minimum required length

        Returns:
            tuple: (is_valid, list_of_issues)
        """
        issues = []

        if len(password) < min_length:
            issues.append(f"Password must be at least {min_length} characters")

        if not any(c.isupper() for c in password):
            issues.append("Password must contain at least one uppercase letter")

        if not any(c.islower() for c in password):
            issues.append("Password must contain at least one lowercase letter")

        if not any(c.isdigit() for c in password):
            issues.append("Password must contain at least one digit")

        # Check for special characters
        special_chars = set("!@#$%^&*()_+-=[]{}|;:,.<>?")
        if not any(c in special_chars for c in password):
            issues.append("Password must contain at least one special character")

        return len(issues) == 0, issues

    @staticmethod
    def validate_username(username: str, min_length: int = 3, max_length: int = 50) -> tuple[bool, list[str]]:
        """
        Validate username format.

        Args:
            username: Username to validate
            min_length: Minimum length
            max_length: Maximum length

        Returns:
            tuple: (is_valid, list_of_issues)
        """
        issues = []

        if len(username) < min_length:
            issues.append(f"Username must be at least {min_length} characters")

        if len(username) > max_length:
            issues.append(f"Username must not exceed {max_length} characters")

        if not username[0].isalpha():
            issues.append("Username must start with a letter")

        if not all(c.isalnum() or c in ('_', '-', '.') for c in username):
            issues.append("Username can only contain letters, numbers, and _-.")

        return len(issues) == 0, issues


class SecureCredentialCache:
    """
    Simple in-memory credential cache with expiration.

    Note: This is for temporary caching only. For persistent storage,
    use the OS keyring or encrypted files.
    """

    def __init__(self, default_ttl: int = 3600):
        """
        Initialize credential cache.

        Args:
            default_ttl: Default time-to-live in seconds (default 1 hour)
        """
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._default_ttl = default_ttl

    def store(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """
        Store a credential in cache.

        Args:
            key: Cache key
            value: Value to store
            ttl: Optional custom TTL in seconds
        """
        import time

        expiry = time.time() + (ttl if ttl is not None else self._default_ttl)
        self._cache[key] = {
            'value': value,
            'expiry': expiry
        }

    def retrieve(self, key: str) -> Optional[Any]:
        """
        Retrieve a credential from cache.

        Args:
            key: Cache key

        Returns:
            Any: Cached value, or None if not found or expired
        """
        import time

        if key not in self._cache:
            return None

        entry = self._cache[key]
        if time.time() > entry['expiry']:
            # Expired - remove from cache
            del self._cache[key]
            return None

        return entry['value']

    def remove(self, key: str) -> None:
        """
        Remove a credential from cache.

        Args:
            key: Cache key
        """
        self._cache.pop(key, None)

    def clear(self) -> None:
        """Clear all cached credentials."""
        self._cache.clear()

    def cleanup_expired(self) -> int:
        """
        Remove all expired entries.

        Returns:
            int: Number of entries removed
        """
        import time

        current_time = time.time()
        expired_keys = [
            key for key, entry in self._cache.items()
            if current_time > entry['expiry']
        ]

        for key in expired_keys:
            del self._cache[key]

        return len(expired_keys)


def sanitize_credential_for_logging(credential: str, reveal_length: int = 4) -> str:
    """
    Sanitize a credential for safe logging.

    Args:
        credential: The credential to sanitize
        reveal_length: Number of characters to reveal (default 4)

    Returns:
        str: Sanitized credential safe for logging
    """
    if not credential:
        return "[empty]"

    if len(credential) <= reveal_length * 2:
        return "[redacted]"

    return f"[redacted]...{credential[-reveal_length:]}"


def generate_secure_filename(prefix: str = "", extension: str = "") -> str:
    """
    Generate a secure random filename.

    Args:
        prefix: Optional filename prefix
        extension: Optional file extension (with or without dot)

    Returns:
        str: Secure random filename
    """
    random_part = secrets.token_hex(16)

    if extension and not extension.startswith('.'):
        extension = f'.{extension}'

    if prefix:
        return f"{prefix}_{random_part}{extension}"
    else:
        return f"{random_part}{extension}"


class CredentialRotationHelper:
    """
    Helper for managing credential rotation.
    """

    def __init__(self, storage_path: Path):
        """
        Initialize credential rotation helper.

        Args:
            storage_path: Path to store rotation metadata
        """
        self._storage_path = Path(storage_path)
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)

    def record_rotation(self, credential_id: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """
        Record a credential rotation.

        Args:
            credential_id: Identifier for the credential
            metadata: Optional metadata about the rotation
        """
        import time

        rotation_data = {
            'credential_id': credential_id,
            'timestamp': time.time(),
            'metadata': metadata or {}
        }

        # Append to rotation log
        log_file = self._storage_path / 'rotation_log.json'

        try:
            if log_file.exists():
                with open(log_file, 'r') as f:
                    log = json.load(f)
            else:
                log = []

            log.append(rotation_data)

            with open(log_file, 'w') as f:
                json.dump(log, f, indent=2)
        except Exception as e:
            raise CredentialError(f"Failed to record rotation: {e}")

    def get_last_rotation(self, credential_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the last rotation record for a credential.

        Args:
            credential_id: Identifier for the credential

        Returns:
            Dict or None: Last rotation record if found
        """
        log_file = self._storage_path / 'rotation_log.json'

        try:
            if not log_file.exists():
                return None

            with open(log_file, 'r') as f:
                log = json.load(f)

            # Find most recent rotation for this credential
            matching = [
                entry for entry in log
                if entry.get('credential_id') == credential_id
            ]

            if not matching:
                return None

            # Return most recent
            return max(matching, key=lambda x: x.get('timestamp', 0))

        except Exception:
            return None

    def should_rotate(self, credential_id: str, max_age_seconds: int) -> bool:
        """
        Check if a credential should be rotated based on age.

        Args:
            credential_id: Identifier for the credential
            max_age_seconds: Maximum age before rotation is needed

        Returns:
            bool: True if rotation is recommended
        """
        import time

        last_rotation = self.get_last_rotation(credential_id)

        if last_rotation is None:
            # Never rotated - should rotate
            return True

        age = time.time() - last_rotation.get('timestamp', 0)
        return age >= max_age_seconds
