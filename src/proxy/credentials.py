"""Proxy credential management using imxup's secure storage system."""

from typing import Optional

try:
    from imxup import get_credential, set_credential, remove_credential, encrypt_password, decrypt_password
    _IMXUP_AVAILABLE = True
except ImportError:
    # Allow module to load without pycurl (for unit testing)
    _IMXUP_AVAILABLE = False
    get_credential = None
    set_credential = None
    remove_credential = None
    encrypt_password = None
    decrypt_password = None


def _proxy_key(profile_id: str) -> str:
    """Generate credential storage key for proxy profile."""
    return f"proxy_{profile_id}_password"


def get_proxy_password(profile_id: str) -> Optional[str]:
    """Retrieve proxy password from secure storage.

    Args:
        profile_id: Unique identifier for the proxy profile

    Returns:
        Decrypted password if found, None otherwise
    """
    if not _IMXUP_AVAILABLE:
        return None
    encrypted = get_credential(_proxy_key(profile_id))
    if encrypted:
        try:
            return decrypt_password(encrypted)
        except Exception:
            return None
    return None


def set_proxy_password(profile_id: str, password: str) -> None:
    """Store proxy password in secure storage.

    Args:
        profile_id: Unique identifier for the proxy profile
        password: Plain text password to encrypt and store
    """
    if not _IMXUP_AVAILABLE:
        return
    encrypted = encrypt_password(password)
    set_credential(_proxy_key(profile_id), encrypted)


def remove_proxy_password(profile_id: str) -> None:
    """Remove proxy password from secure storage.

    Args:
        profile_id: Unique identifier for the proxy profile
    """
    if not _IMXUP_AVAILABLE:
        return
    remove_credential(_proxy_key(profile_id))


def has_proxy_password(profile_id: str) -> bool:
    """Check if proxy has stored password.

    Args:
        profile_id: Unique identifier for the proxy profile

    Returns:
        True if password exists in storage, False otherwise
    """
    if not _IMXUP_AVAILABLE:
        return False
    return bool(get_credential(_proxy_key(profile_id)))
