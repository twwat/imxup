"""Proxy configuration and management module for imxup2.

Provides comprehensive proxy support including:
- Profile management (ProxyProfile, ProxyType)
- Pool management with rotation strategies (ProxyPool, PoolRotator)
- Hierarchical proxy resolution (ProxyResolver)
- Bulk import/export (BulkProxyParser, BulkProxyExporter)
- Health monitoring (HealthMonitor, PeriodicHealthChecker)
- Secure credential storage via keyring
- PyCurl integration (PyCurlProxyAdapter)
"""

# Models
from src.proxy.models import (
    ProxyProfile,
    ProxyEntry,
    ProxyType,
    ProxyContext,
    ProxyPool,
    ProxyHealth,
    RotationStrategy,
)

# Credentials (secure keyring storage) - lazy import to avoid pycurl dependency in tests
try:
    from src.proxy.credentials import (
        get_proxy_password,
        set_proxy_password,
        remove_proxy_password,
        has_proxy_password,
    )
except ImportError:
    # Allow module to load without pycurl (for testing)
    get_proxy_password = None
    set_proxy_password = None
    remove_proxy_password = None
    has_proxy_password = None

# Storage (QSettings persistence)
from src.proxy.storage import ProxyStorage

# Resolver (hierarchical proxy resolution)
from src.proxy.resolver import ProxyResolver

# Pool rotation
from src.proxy.pool import PoolRotator

# Bulk import/export
from src.proxy.bulk import (
    BulkProxyParser,
    BulkProxyExporter,
    ParseResult,
    ParseFormat,
    ExportFormat,
    parse_csv_proxies,
    parse_json_proxies,
)

# Health monitoring
from src.proxy.health import (
    HealthMonitor,
    PeriodicHealthChecker,
    sync_check_proxy,
)

# PyCurl adapter - lazy import to avoid pycurl dependency in tests
try:
    from src.proxy.pycurl_adapter import PyCurlProxyAdapter
except (ImportError, AttributeError):
    # AttributeError can occur if pycurl is installed but lacks certain constants
    PyCurlProxyAdapter = None

__all__ = [
    # Models
    'ProxyProfile',
    'ProxyEntry',
    'ProxyType',
    'ProxyContext',
    'ProxyPool',
    'ProxyHealth',
    'RotationStrategy',
    # Credentials
    'get_proxy_password',
    'set_proxy_password',
    'remove_proxy_password',
    'has_proxy_password',
    # Storage
    'ProxyStorage',
    # Resolver
    'ProxyResolver',
    # Pool
    'PoolRotator',
    # Bulk
    'BulkProxyParser',
    'BulkProxyExporter',
    'ParseResult',
    'ParseFormat',
    'ExportFormat',
    'parse_csv_proxies',
    'parse_json_proxies',
    # Health
    'HealthMonitor',
    'PeriodicHealthChecker',
    'sync_check_proxy',
    # PyCurl
    'PyCurlProxyAdapter',
]
