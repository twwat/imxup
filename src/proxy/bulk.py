"""Bulk proxy import and export utilities."""

import re
import csv
import json
import io
from typing import List, Optional, Tuple, Dict, Any
from dataclasses import dataclass
from enum import Enum, auto

from src.proxy.models import ProxyProfile, ProxyType


class ParseFormat(Enum):
    """Detected or specified proxy format."""
    IP_PORT = auto()              # 192.168.1.1:8080
    IP_PORT_USER_PASS = auto()    # 192.168.1.1:8080:user:pass
    URL = auto()                  # http://user:pass@192.168.1.1:8080
    UNKNOWN = auto()


@dataclass
class ParseResult:
    """Result of parsing a single proxy entry."""
    success: bool
    profile: Optional[ProxyProfile] = None
    password: Optional[str] = None
    error: Optional[str] = None
    original_line: str = ""
    format_detected: ParseFormat = ParseFormat.UNKNOWN


class BulkProxyParser:
    """Parse proxies from various text formats."""

    # Regex patterns
    _URL_PATTERN = re.compile(
        r'^(?P<scheme>https?|socks[45])://'
        r'(?:(?P<user>[^:@]+):(?P<pass>[^@]+)@)?'
        r'(?P<host>[^:/]+)'
        r':(?P<port>\d+)/?$',
        re.IGNORECASE
    )

    _IP_PORT_PATTERN = re.compile(
        r'^(?P<host>[\d.]+):(?P<port>\d+)$'
    )

    _IP_PORT_USER_PASS_PATTERN = re.compile(
        r'^(?P<host>[\d.]+):(?P<port>\d+):(?P<user>[^:]+):(?P<pass>.+)$'
    )

    _HOSTNAME_PORT_PATTERN = re.compile(
        r'^(?P<host>[a-zA-Z0-9.-]+):(?P<port>\d+)$'
    )

    def __init__(self, default_type: ProxyType = ProxyType.HTTP):
        """
        Initialize parser.

        Args:
            default_type: Default proxy type when not specified in format
        """
        self.default_type = default_type

    def parse_text(self, text: str, name_prefix: str = "Imported") -> List[ParseResult]:
        """
        Parse multiple proxies from text (one per line).

        Args:
            text: Multi-line text with proxy entries
            name_prefix: Prefix for generated profile names

        Returns:
            List of ParseResult objects
        """
        results = []
        lines = text.strip().split('\n')

        for i, line in enumerate(lines, 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            result = self.parse_line(line, f"{name_prefix} {i}")
            results.append(result)

        return results

    def parse_line(self, line: str, name: str = "") -> ParseResult:
        """
        Parse a single proxy line.

        Args:
            line: Proxy entry string
            name: Name to assign to the profile

        Returns:
            ParseResult with profile and optional password
        """
        line = line.strip()

        # Try URL format first (most specific)
        result = self._try_url_format(line, name)
        if result.success:
            return result

        # Try IP:PORT:USER:PASS format
        result = self._try_ip_port_user_pass(line, name)
        if result.success:
            return result

        # Try IP:PORT format
        result = self._try_ip_port(line, name)
        if result.success:
            return result

        # Try hostname:port format
        result = self._try_hostname_port(line, name)
        if result.success:
            return result

        return ParseResult(
            success=False,
            error=f"Could not parse proxy format: {line}",
            original_line=line,
            format_detected=ParseFormat.UNKNOWN
        )

    def _try_url_format(self, line: str, name: str) -> ParseResult:
        """Try to parse URL format: scheme://user:pass@host:port"""
        match = self._URL_PATTERN.match(line)
        if not match:
            return ParseResult(success=False, original_line=line)

        scheme = match.group('scheme').lower()
        proxy_type = self._scheme_to_type(scheme)

        profile = ProxyProfile(
            name=name,
            proxy_type=proxy_type,
            host=match.group('host'),
            port=int(match.group('port')),
            auth_required=bool(match.group('user')),
            username=match.group('user') or '',
        )

        return ParseResult(
            success=True,
            profile=profile,
            password=match.group('pass'),
            original_line=line,
            format_detected=ParseFormat.URL
        )

    def _try_ip_port_user_pass(self, line: str, name: str) -> ParseResult:
        """Try to parse IP:PORT:USER:PASS format."""
        match = self._IP_PORT_USER_PASS_PATTERN.match(line)
        if not match:
            return ParseResult(success=False, original_line=line)

        profile = ProxyProfile(
            name=name,
            proxy_type=self.default_type,
            host=match.group('host'),
            port=int(match.group('port')),
            auth_required=True,
            username=match.group('user'),
        )

        return ParseResult(
            success=True,
            profile=profile,
            password=match.group('pass'),
            original_line=line,
            format_detected=ParseFormat.IP_PORT_USER_PASS
        )

    def _try_ip_port(self, line: str, name: str) -> ParseResult:
        """Try to parse IP:PORT format."""
        match = self._IP_PORT_PATTERN.match(line)
        if not match:
            return ParseResult(success=False, original_line=line)

        profile = ProxyProfile(
            name=name,
            proxy_type=self.default_type,
            host=match.group('host'),
            port=int(match.group('port')),
            auth_required=False,
        )

        return ParseResult(
            success=True,
            profile=profile,
            original_line=line,
            format_detected=ParseFormat.IP_PORT
        )

    def _try_hostname_port(self, line: str, name: str) -> ParseResult:
        """Try to parse hostname:port format."""
        match = self._HOSTNAME_PORT_PATTERN.match(line)
        if not match:
            return ParseResult(success=False, original_line=line)

        profile = ProxyProfile(
            name=name,
            proxy_type=self.default_type,
            host=match.group('host'),
            port=int(match.group('port')),
            auth_required=False,
        )

        return ParseResult(
            success=True,
            profile=profile,
            original_line=line,
            format_detected=ParseFormat.IP_PORT
        )

    def _scheme_to_type(self, scheme: str) -> ProxyType:
        """Convert URL scheme to ProxyType."""
        mapping = {
            'http': ProxyType.HTTP,
            'https': ProxyType.HTTPS,
            'socks4': ProxyType.SOCKS4,
            'socks5': ProxyType.SOCKS5,
        }
        return mapping.get(scheme.lower(), self.default_type)


class ExportFormat(Enum):
    """Export format options."""
    TEXT_IP_PORT = "ip:port"
    TEXT_IP_PORT_USER_PASS = "ip:port:user:pass"
    TEXT_URL = "url"
    CSV = "csv"
    JSON = "json"


class BulkProxyExporter:
    """Export proxies to various formats."""

    def export(
        self,
        profiles: List[ProxyProfile],
        format: ExportFormat,
        passwords: Optional[Dict[str, str]] = None,
        include_disabled: bool = False
    ) -> str:
        """
        Export profiles to specified format.

        Args:
            profiles: List of ProxyProfile to export
            format: Export format
            passwords: Optional dict of profile_id -> password
            include_disabled: Include disabled profiles

        Returns:
            Exported text/data
        """
        passwords = passwords or {}

        # Filter disabled if needed
        if not include_disabled:
            profiles = [p for p in profiles if p.enabled]

        if format == ExportFormat.TEXT_IP_PORT:
            return self._export_ip_port(profiles)
        elif format == ExportFormat.TEXT_IP_PORT_USER_PASS:
            return self._export_ip_port_user_pass(profiles, passwords)
        elif format == ExportFormat.TEXT_URL:
            return self._export_url(profiles, passwords)
        elif format == ExportFormat.CSV:
            return self._export_csv(profiles, passwords)
        elif format == ExportFormat.JSON:
            return self._export_json(profiles, passwords)

        raise ValueError(f"Unknown export format: {format}")

    def _export_ip_port(self, profiles: List[ProxyProfile]) -> str:
        """Export as simple ip:port list."""
        lines = []
        for p in profiles:
            lines.append(f"{p.host}:{p.port}")
        return '\n'.join(lines)

    def _export_ip_port_user_pass(
        self,
        profiles: List[ProxyProfile],
        passwords: Dict[str, str]
    ) -> str:
        """Export as ip:port:user:pass list."""
        lines = []
        for p in profiles:
            if p.auth_required and p.username:
                password = passwords.get(p.id, '')
                lines.append(f"{p.host}:{p.port}:{p.username}:{password}")
            else:
                lines.append(f"{p.host}:{p.port}")
        return '\n'.join(lines)

    def _export_url(
        self,
        profiles: List[ProxyProfile],
        passwords: Dict[str, str]
    ) -> str:
        """Export as URL list."""
        lines = []
        for p in profiles:
            scheme = p.proxy_type.value
            if p.auth_required and p.username:
                password = passwords.get(p.id, '')
                lines.append(f"{scheme}://{p.username}:{password}@{p.host}:{p.port}")
            else:
                lines.append(f"{scheme}://{p.host}:{p.port}")
        return '\n'.join(lines)

    def _export_csv(
        self,
        profiles: List[ProxyProfile],
        passwords: Dict[str, str]
    ) -> str:
        """Export as CSV."""
        output = io.StringIO()
        writer = csv.writer(output)

        # Header
        writer.writerow([
            'name', 'type', 'host', 'port', 'auth_required',
            'username', 'password', 'enabled', 'bypass_list'
        ])

        # Data
        for p in profiles:
            writer.writerow([
                p.name,
                p.proxy_type.value,
                p.host,
                p.port,
                p.auth_required,
                p.username,
                passwords.get(p.id, ''),
                p.enabled,
                ','.join(p.bypass_list)
            ])

        return output.getvalue()

    def _export_json(
        self,
        profiles: List[ProxyProfile],
        passwords: Dict[str, str]
    ) -> str:
        """Export as JSON."""
        data = []
        for p in profiles:
            entry = p.to_dict()
            # Include password in export if available
            if p.auth_required:
                entry['password'] = passwords.get(p.id, '')
            data.append(entry)

        return json.dumps(data, indent=2)


def parse_csv_proxies(csv_text: str) -> List[ParseResult]:
    """
    Parse proxies from CSV format.

    Expected columns: name, type, host, port, [auth_required, username, password, enabled, bypass_list]
    """
    results = []
    reader = csv.DictReader(io.StringIO(csv_text))

    for i, row in enumerate(reader, 1):
        try:
            # Required fields
            host = row.get('host', '').strip()
            port_str = row.get('port', '').strip()

            if not host or not port_str:
                results.append(ParseResult(
                    success=False,
                    error=f"Row {i}: Missing host or port",
                    original_line=str(row)
                ))
                continue

            port = int(port_str)

            # Optional fields with defaults
            name = row.get('name', f'CSV Import {i}').strip()
            proxy_type_str = row.get('type', 'http').strip().lower()
            auth_required = row.get('auth_required', '').lower() in ('true', '1', 'yes')
            username = row.get('username', '').strip()
            password = row.get('password', '').strip()
            enabled = row.get('enabled', 'true').lower() in ('true', '1', 'yes')
            bypass_str = row.get('bypass_list', '').strip()
            bypass_list = [b.strip() for b in bypass_str.split(',') if b.strip()]

            # Map type
            type_map = {
                'http': ProxyType.HTTP,
                'https': ProxyType.HTTPS,
                'socks4': ProxyType.SOCKS4,
                'socks5': ProxyType.SOCKS5,
            }
            proxy_type = type_map.get(proxy_type_str, ProxyType.HTTP)

            profile = ProxyProfile(
                name=name,
                proxy_type=proxy_type,
                host=host,
                port=port,
                auth_required=auth_required or bool(username),
                username=username,
                bypass_list=bypass_list,
                enabled=enabled,
            )

            results.append(ParseResult(
                success=True,
                profile=profile,
                password=password if password else None,
                original_line=str(row)
            ))

        except (ValueError, KeyError) as e:
            results.append(ParseResult(
                success=False,
                error=f"Row {i}: {str(e)}",
                original_line=str(row)
            ))

    return results


def parse_json_proxies(json_text: str) -> List[ParseResult]:
    """
    Parse proxies from JSON format.

    Expected: Array of objects with proxy fields.
    """
    results = []

    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as e:
        return [ParseResult(
            success=False,
            error=f"Invalid JSON: {str(e)}",
            original_line=json_text[:100]
        )]

    if not isinstance(data, list):
        data = [data]

    for i, entry in enumerate(data, 1):
        try:
            if not isinstance(entry, dict):
                results.append(ParseResult(
                    success=False,
                    error=f"Entry {i}: Not a JSON object",
                    original_line=str(entry)
                ))
                continue

            # Extract password before converting
            password = entry.pop('password', None)

            profile = ProxyProfile.from_dict(entry)
            # Generate new ID for imports
            import uuid
            profile.id = str(uuid.uuid4())

            results.append(ParseResult(
                success=True,
                profile=profile,
                password=password,
                original_line=json.dumps(entry)
            ))

        except (ValueError, KeyError) as e:
            results.append(ParseResult(
                success=False,
                error=f"Entry {i}: {str(e)}",
                original_line=str(entry)
            ))

    return results
