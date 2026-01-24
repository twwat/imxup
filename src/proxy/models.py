"""Proxy profile data models."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any
import uuid


class ProxyType(Enum):
    """Supported proxy protocol types."""
    HTTP = "http"
    HTTPS = "https"
    SOCKS4 = "socks4"
    SOCKS5 = "socks5"


@dataclass
class ProxyProfile:
    """Represents a complete proxy configuration profile.

    Passwords are stored separately via the credentials module for security.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    proxy_type: ProxyType = ProxyType.HTTP
    host: str = ""
    port: int = 8080
    auth_required: bool = False
    username: str = ""
    # Password stored separately via credentials.py
    bypass_list: List[str] = field(default_factory=list)
    enabled: bool = True

    def to_dict(self) -> Dict[str, Any]:
        """Serialize proxy profile to dictionary for storage."""
        return {
            'id': self.id,
            'name': self.name,
            'proxy_type': self.proxy_type.value,
            'host': self.host,
            'port': self.port,
            'auth_required': self.auth_required,
            'username': self.username,
            'bypass_list': self.bypass_list,
            'enabled': self.enabled,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ProxyProfile':
        """Deserialize proxy profile from dictionary."""
        return cls(
            id=data.get('id', str(uuid.uuid4())),
            name=data.get('name', ''),
            proxy_type=ProxyType(data.get('proxy_type', 'http')),
            host=data.get('host', ''),
            port=data.get('port', 8080),
            auth_required=data.get('auth_required', False),
            username=data.get('username', ''),
            bypass_list=data.get('bypass_list', []),
            enabled=data.get('enabled', True),
        )

    def get_proxy_url(self) -> str:
        """Get proxy URL for display (no password)."""
        prefix = self.proxy_type.value
        if self.auth_required and self.username:
            return f"{prefix}://{self.username}@{self.host}:{self.port}"
        return f"{prefix}://{self.host}:{self.port}"


@dataclass
class ProxyContext:
    """Context for proxy resolution.

    Used to determine which proxy profile should be used for a specific
    operation based on service category, service ID, and operation type.
    """
    category: str  # "file_hosts", "forums", "api", etc.
    service_id: str  # "rapidgator", "pixeldrain", etc.
    operation: str = ""  # "upload", "download", "auth", etc.


class RotationStrategy(Enum):
    """Proxy rotation strategies for pools."""
    ROUND_ROBIN = "round_robin"
    RANDOM = "random"
    LEAST_USED = "least_used"
    WEIGHTED = "weighted"
    FAILOVER = "failover"  # Try first, fallback on failure


@dataclass
class ProxyEntry:
    """A single proxy server entry within a pool."""
    host: str
    port: int
    proxy_type: ProxyType = ProxyType.HTTP
    username: str = ""
    password: str = ""  # Stored directly for pool entries
    weight: int = 1
    enabled: bool = True

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            'host': self.host,
            'port': self.port,
            'proxy_type': self.proxy_type.value,
            'username': self.username,
            'password': self.password,
            'weight': self.weight,
            'enabled': self.enabled,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ProxyEntry':
        """Deserialize from dictionary."""
        return cls(
            host=data.get('host', ''),
            port=data.get('port', 8080),
            proxy_type=ProxyType(data.get('proxy_type', 'http')),
            username=data.get('username', ''),
            password=data.get('password', ''),
            weight=data.get('weight', 1),
            enabled=data.get('enabled', True),
        )

    def get_display_url(self) -> str:
        """Get URL for display (no password)."""
        if self.username:
            return f"{self.proxy_type.value}://{self.username}@{self.host}:{self.port}"
        return f"{self.proxy_type.value}://{self.host}:{self.port}"

    def get_full_url(self) -> str:
        """Get full URL with password for connections."""
        if self.username and self.password:
            return f"{self.proxy_type.value}://{self.username}:{self.password}@{self.host}:{self.port}"
        elif self.username:
            return f"{self.proxy_type.value}://{self.username}@{self.host}:{self.port}"
        return f"{self.proxy_type.value}://{self.host}:{self.port}"


@dataclass
class ProxyPool:
    """A pool of proxies with rotation support.

    Contains proxy servers directly - just paste your proxies and go.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    proxies: List[ProxyEntry] = field(default_factory=list)  # The actual proxies
    proxy_type: ProxyType = ProxyType.HTTP  # Default type for new entries
    rotation_strategy: RotationStrategy = RotationStrategy.ROUND_ROBIN
    sticky_sessions: bool = False
    sticky_ttl_seconds: int = 3600
    fallback_on_failure: bool = True
    max_consecutive_failures: int = 3
    enabled: bool = True
    # Legacy field for migration
    proxy_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize proxy pool to dictionary for storage."""
        return {
            'id': self.id,
            'name': self.name,
            'proxies': [p.to_dict() for p in self.proxies],
            'proxy_type': self.proxy_type.value,
            'rotation_strategy': self.rotation_strategy.value,
            'sticky_sessions': self.sticky_sessions,
            'sticky_ttl_seconds': self.sticky_ttl_seconds,
            'fallback_on_failure': self.fallback_on_failure,
            'max_consecutive_failures': self.max_consecutive_failures,
            'enabled': self.enabled,
            'proxy_ids': self.proxy_ids,  # Keep for migration
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ProxyPool':
        """Deserialize proxy pool from dictionary."""
        proxies_data = data.get('proxies', [])
        proxies = [ProxyEntry.from_dict(p) for p in proxies_data]

        return cls(
            id=data.get('id', str(uuid.uuid4())),
            name=data.get('name', ''),
            proxies=proxies,
            proxy_type=ProxyType(data.get('proxy_type', 'http')),
            rotation_strategy=RotationStrategy(data.get('rotation_strategy', 'round_robin')),
            sticky_sessions=data.get('sticky_sessions', False),
            sticky_ttl_seconds=data.get('sticky_ttl_seconds', 3600),
            fallback_on_failure=data.get('fallback_on_failure', True),
            max_consecutive_failures=data.get('max_consecutive_failures', 3),
            enabled=data.get('enabled', True),
            proxy_ids=data.get('proxy_ids', []),
        )

    def add_from_text(self, text: str, skip_duplicates: bool = True) -> 'ProxyParseResult':
        """Parse and add proxies from text. Returns detailed parse result.

        Supports formats:
        - host:port
        - host:port:user:pass
        - type://host:port
        - type://user:pass@host:port

        Args:
            text: Text containing proxy lines
            skip_duplicates: If True, skip proxies with same host:port as existing

        Returns:
            ProxyParseResult with details about added, skipped, and invalid entries
        """
        result = ProxyParseResult()

        # Build set of existing host:port for duplicate detection
        existing = {(p.host.lower(), p.port) for p in self.proxies}

        lines = text.strip().split('\n') if text.strip() else []
        for line_num, line in enumerate(lines, start=1):
            original_line = line
            line = line.strip()

            # Skip blank lines and comments
            if not line or line.startswith('#'):
                result.blank_or_comments += 1
                continue

            entry, error = self._parse_proxy_line_with_error(line)

            if entry is None:
                result.invalid_lines.append((line_num, original_line.strip(), error))
                continue

            # Check for duplicates
            key = (entry.host.lower(), entry.port)
            if skip_duplicates and key in existing:
                result.skipped_duplicates.append(original_line.strip())
                continue

            # Add the proxy
            self.proxies.append(entry)
            result.added.append(entry)
            existing.add(key)

        return result

    def _parse_proxy_line(self, line: str) -> Optional['ProxyEntry']:
        """Parse a single proxy line into a ProxyEntry."""
        entry, _ = self._parse_proxy_line_with_error(line)
        return entry

    def _parse_proxy_line_with_error(self, line: str) -> tuple[Optional['ProxyEntry'], str]:
        """Parse a single proxy line into a ProxyEntry with error details.

        Returns:
            Tuple of (ProxyEntry or None, error_message)
        """
        import re

        line = line.strip()
        if not line:
            return None, "Empty line"

        # URL format: type://user:pass@host:port or type://host:port
        url_match = re.match(
            r'^(https?|socks[45])://(?:([^:]+):([^@]+)@)?([^:]+):(\d+)$',
            line, re.IGNORECASE
        )
        if url_match:
            ptype, user, passwd, host, port = url_match.groups()
            try:
                port_int = int(port)
                if not 1 <= port_int <= 65535:
                    return None, f"Port {port} out of range (1-65535)"
                return ProxyEntry(
                    host=host,
                    port=port_int,
                    proxy_type=ProxyType(ptype.lower()),
                    username=user or '',
                    password=passwd or '',
                ), ""
            except ValueError:
                return None, f"Invalid port: {port}"

        # host:port:user:pass format
        parts = line.split(':')
        if len(parts) == 4:
            host, port, user, passwd = parts
            try:
                port_int = int(port)
                if not 1 <= port_int <= 65535:
                    return None, f"Port {port} out of range (1-65535)"
                return ProxyEntry(
                    host=host,
                    port=port_int,
                    proxy_type=self.proxy_type,
                    username=user,
                    password=passwd,
                ), ""
            except ValueError:
                return None, f"Invalid port: {port}"

        # host:port format
        if len(parts) == 2:
            host, port = parts
            try:
                port_int = int(port)
                if not 1 <= port_int <= 65535:
                    return None, f"Port {port} out of range (1-65535)"
                return ProxyEntry(
                    host=host,
                    port=port_int,
                    proxy_type=self.proxy_type,
                ), ""
            except ValueError:
                return None, f"Invalid port: {port}"

        # Explain what formats are expected
        if len(parts) == 1:
            return None, "Missing port (expected host:port)"
        elif len(parts) == 3:
            return None, "Invalid format (expected host:port or host:port:user:pass)"
        else:
            return None, f"Invalid format ({len(parts)} parts, expected 2 or 4)"


@dataclass
class ProxyParseResult:
    """Result of parsing proxy text with detailed feedback."""
    added: List[ProxyEntry] = field(default_factory=list)
    skipped_duplicates: List[str] = field(default_factory=list)  # Original lines
    invalid_lines: List[tuple] = field(default_factory=list)  # (line_number, line, error)
    blank_or_comments: int = 0

    @property
    def total_added(self) -> int:
        return len(self.added)

    @property
    def total_skipped(self) -> int:
        return len(self.skipped_duplicates)

    @property
    def total_invalid(self) -> int:
        return len(self.invalid_lines)

    @property
    def had_issues(self) -> bool:
        return self.total_skipped > 0 or self.total_invalid > 0


@dataclass
class ProxyHealth:
    """Health and usage statistics for a proxy."""
    profile_id: str
    is_alive: bool = True
    last_check: Optional[float] = None  # timestamp
    last_success: Optional[float] = None  # timestamp
    latency_ms: float = 0.0
    consecutive_failures: int = 0
    total_requests: int = 0
    failed_requests: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Serialize proxy health to dictionary for storage."""
        return {
            'profile_id': self.profile_id,
            'is_alive': self.is_alive,
            'last_check': self.last_check,
            'last_success': self.last_success,
            'latency_ms': self.latency_ms,
            'consecutive_failures': self.consecutive_failures,
            'total_requests': self.total_requests,
            'failed_requests': self.failed_requests,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ProxyHealth':
        """Deserialize proxy health from dictionary."""
        return cls(
            profile_id=data.get('profile_id', ''),
            is_alive=data.get('is_alive', True),
            last_check=data.get('last_check'),
            last_success=data.get('last_success'),
            latency_ms=data.get('latency_ms', 0.0),
            consecutive_failures=data.get('consecutive_failures', 0),
            total_requests=data.get('total_requests', 0),
            failed_requests=data.get('failed_requests', 0),
        )
