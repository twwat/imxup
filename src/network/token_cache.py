"""
Token cache manager for file host authentication tokens.

Stores and retrieves authentication tokens with expiration timestamps
using encrypted QSettings storage (same encryption as credentials).
"""

import time
from typing import Optional, Dict, Any
from PyQt6.QtCore import QSettings

# Import encryption functions from imxup module
from imxup import encrypt_password, decrypt_password


class TokenCache:
    """Manages cached authentication tokens for file hosts."""

    def __init__(self):
        """Initialize token cache."""
        self.settings = QSettings("ImxUploader", "ImxUploadGUI")

    def store_token(self, host_id: str, token: str, ttl: Optional[int] = None) -> None:
        """Store an authentication token with optional TTL.

        Args:
            host_id: Host identifier
            token: Authentication token
            ttl: Time-to-live in seconds (None = no expiration)
        """
        # Encrypt the token
        encrypted_token = encrypt_password(token)

        # Calculate expiration timestamp
        expires_at = None
        if ttl is not None:
            expires_at = int(time.time()) + ttl

        # Store in QSettings
        self.settings.beginGroup(f"FileHosts/Tokens/{host_id}")
        self.settings.setValue("token", encrypted_token)
        if expires_at:
            self.settings.setValue("expires_at", expires_at)
        else:
            self.settings.remove("expires_at")
        self.settings.setValue("cached_at", int(time.time()))
        self.settings.endGroup()

    def get_token(self, host_id: str) -> Optional[str]:
        """Retrieve a cached authentication token if valid.

        Args:
            host_id: Host identifier

        Returns:
            Decrypted token if valid, None if expired or not found
        """
        self.settings.beginGroup(f"FileHosts/Tokens/{host_id}")

        # Check if token exists
        encrypted_token = self.settings.value("token", None)
        if not encrypted_token:
            self.settings.endGroup()
            return None

        # Check expiration
        expires_at = self.settings.value("expires_at", None)
        if expires_at is not None:
            try:
                expires_at = int(expires_at)
                if time.time() >= expires_at:
                    # Token expired
                    self.settings.endGroup()
                    self.clear_token(host_id)
                    return None
            except (ValueError, TypeError):
                pass

        self.settings.endGroup()

        # Decrypt and return token
        try:
            return decrypt_password(encrypted_token)
        except Exception:
            # Decryption failed, clear invalid token
            self.clear_token(host_id)
            return None

    def clear_token(self, host_id: str) -> None:
        """Clear cached token for a host.

        Args:
            host_id: Host identifier
        """
        self.settings.beginGroup(f"FileHosts/Tokens/{host_id}")
        self.settings.remove("")  # Remove all keys in this group
        self.settings.endGroup()

    def get_token_info(self, host_id: str) -> Optional[Dict[str, Any]]:
        """Get information about a cached token.

        Args:
            host_id: Host identifier

        Returns:
            Dict with cached_at, expires_at, is_valid, ttl_remaining
        """
        self.settings.beginGroup(f"FileHosts/Tokens/{host_id}")

        encrypted_token = self.settings.value("token", None)
        if not encrypted_token:
            self.settings.endGroup()
            return None

        cached_at = self.settings.value("cached_at", None)
        expires_at = self.settings.value("expires_at", None)

        self.settings.endGroup()

        now = time.time()
        is_valid = True
        ttl_remaining = None

        if expires_at is not None:
            try:
                expires_at = int(expires_at)
                is_valid = now < expires_at
                ttl_remaining = max(0, expires_at - int(now))
            except (ValueError, TypeError):
                pass

        return {
            'cached_at': cached_at,
            'expires_at': expires_at,
            'is_valid': is_valid,
            'ttl_remaining': ttl_remaining
        }

    def clear_all_tokens(self) -> None:
        """Clear all cached tokens."""
        self.settings.beginGroup("FileHosts/Tokens")
        self.settings.remove("")  # Remove all keys in this group
        self.settings.endGroup()


# Global instance
_token_cache: Optional[TokenCache] = None


def get_token_cache() -> TokenCache:
    """Get or create the global TokenCache instance.

    Returns:
        Global TokenCache instance
    """
    global _token_cache
    if _token_cache is None:
        _token_cache = TokenCache()
    return _token_cache
