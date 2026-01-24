"""Proxy resolution engine."""

import os
from typing import Optional, Union

from src.proxy.models import ProxyEntry, ProxyContext, ProxyPool, ProxyType
from src.proxy.storage import ProxyStorage
from src.proxy.pool import PoolRotator


# Special values for proxy assignments
PROXY_DIRECT = "__direct__"
PROXY_OS_PROXY = "__os_proxy__"


class ProxyResolver:
    """Resolves proxy for a given context.

    Now pool-centric: pools contain proxies directly, no separate profiles needed.

    Resolution hierarchy (3 levels):
    1. Service-level (e.g., file_hosts/rapidgator)
    2. Category-level (e.g., file_hosts)
    3. Global-level

    Special values:
    - "__direct__" - Direct connection (no proxy)
    - "__os_proxy__" - Use OS system proxy
    """

    def __init__(
        self,
        storage: Optional[ProxyStorage] = None,
        rotator: Optional[PoolRotator] = None
    ):
        self._storage = storage or ProxyStorage()
        self._rotator = rotator or PoolRotator()

    def resolve(self, context: ProxyContext) -> Optional[ProxyEntry]:
        """
        Resolve proxy for a given context.

        Resolution hierarchy:
        1. Service pool assignment (e.g., file_hosts/rapidgator -> "Fast Pool")
        2. Category pool assignment (e.g., file_hosts -> "Main Pool")
        3. Global default pool
        4. OS proxy (if enabled)
        5. None (direct connection)

        Special values "__direct__" and "__os_proxy__" short-circuit the hierarchy.

        Args:
            context: ProxyContext with category and service_id

        Returns:
            ProxyEntry if proxy should be used, None for direct connection
        """
        service_key = f"{context.category}/{context.service_id}" if context.service_id else context.category

        # 1. Check service-level pool assignment (if service_id provided)
        if context.service_id:
            pool_id = self._storage.get_pool_assignment(context.category, context.service_id)
            if pool_id:
                # Handle special values
                if pool_id == PROXY_DIRECT:
                    return None
                if pool_id == PROXY_OS_PROXY:
                    return self._get_os_proxy()

                pool = self._storage.load_pool(pool_id)
                if pool and pool.enabled and pool.proxies:
                    proxy = self._rotator.get_next_proxy(pool, service_key)
                    if proxy:
                        return proxy

        # 2. Check category pool assignment
        pool_id = self._storage.get_pool_assignment(context.category)
        if pool_id:
            # Handle special values
            if pool_id == PROXY_DIRECT:
                return None
            if pool_id == PROXY_OS_PROXY:
                return self._get_os_proxy()

            pool = self._storage.load_pool(pool_id)
            if pool and pool.enabled and pool.proxies:
                proxy = self._rotator.get_next_proxy(pool, service_key)
                if proxy:
                    return proxy

        # 3. Check global default pool
        pool_id = self._storage.get_global_default_pool()
        if pool_id:
            pool = self._storage.load_pool(pool_id)
            if pool and pool.enabled and pool.proxies:
                proxy = self._rotator.get_next_proxy(pool, service_key)
                if proxy:
                    return proxy

        # 4. Check OS proxy (if enabled)
        if self._storage.get_use_os_proxy():
            proxy = self._get_os_proxy()
            if proxy:
                return proxy

        # 5. Direct connection
        return None

    def report_result(self, pool_id: str, proxy_index: int, success: bool) -> None:
        """Report proxy usage result."""
        pool = self._storage.load_pool(pool_id)
        if not pool:
            return

        if success:
            self._rotator.report_success(pool_id, proxy_index)
        else:
            self._rotator.report_failure(pool_id, proxy_index, pool.max_consecutive_failures)

    def _get_os_proxy(self) -> Optional[ProxyEntry]:
        """Get OS proxy settings from environment."""
        for var in ['HTTPS_PROXY', 'https_proxy', 'HTTP_PROXY', 'http_proxy']:
            proxy_url = os.environ.get(var)
            if proxy_url:
                return self._parse_proxy_url(proxy_url)
        return None

    def _parse_proxy_url(self, url: str) -> Optional[ProxyEntry]:
        """Parse proxy URL into ProxyEntry."""
        from urllib.parse import urlparse, unquote

        try:
            parsed = urlparse(url)

            scheme = parsed.scheme.lower()
            if scheme in ('socks5', 'socks5h'):
                proxy_type = ProxyType.SOCKS5
            elif scheme == 'socks4':
                proxy_type = ProxyType.SOCKS4
            elif scheme == 'https':
                proxy_type = ProxyType.HTTPS
            else:
                proxy_type = ProxyType.HTTP

            return ProxyEntry(
                host=parsed.hostname or '',
                port=parsed.port or 8080,
                proxy_type=proxy_type,
                username=unquote(parsed.username) if parsed.username else '',
                password=unquote(parsed.password) if parsed.password else '',
            )
        except Exception:
            return None

    def get_effective_proxy_info(self, context: ProxyContext) -> dict:
        """Get information about which proxy will be used and why."""
        info = {
            'proxy': None,
            'pool': None,
            'source': 'direct',
            'reason': 'No proxy configured'
        }

        service_key = f"{context.category}/{context.service_id}" if context.service_id else context.category

        # Check service-level pool (if service_id provided)
        if context.service_id:
            pool_id = self._storage.get_pool_assignment(context.category, context.service_id)
            if pool_id:
                # Handle special values
                if pool_id == PROXY_DIRECT:
                    info['source'] = 'service'
                    info['reason'] = f"Service override: Direct connection ({context.service_id})"
                    return info
                if pool_id == PROXY_OS_PROXY:
                    proxy = self._get_os_proxy()
                    if proxy:
                        info['proxy'] = proxy
                        info['source'] = 'service'
                        info['reason'] = f"Service override: OS proxy ({context.service_id})"
                        return info

                pool = self._storage.load_pool(pool_id)
                if pool and pool.enabled and pool.proxies:
                    info['pool'] = pool
                    info['source'] = 'service'
                    info['reason'] = f"Service pool: {pool.name} ({context.service_id})"
                    info['proxy'] = self._rotator.get_next_proxy(pool, service_key)
                    return info

        # Check category pool
        pool_id = self._storage.get_pool_assignment(context.category)
        if pool_id:
            # Handle special values
            if pool_id == PROXY_DIRECT:
                info['source'] = 'category'
                info['reason'] = f"Category override: Direct connection ({context.category})"
                return info
            if pool_id == PROXY_OS_PROXY:
                proxy = self._get_os_proxy()
                if proxy:
                    info['proxy'] = proxy
                    info['source'] = 'category'
                    info['reason'] = f"Category override: OS proxy ({context.category})"
                    return info

            pool = self._storage.load_pool(pool_id)
            if pool and pool.enabled and pool.proxies:
                info['pool'] = pool
                info['source'] = 'category'
                info['reason'] = f"Category pool: {pool.name} ({context.category})"
                info['proxy'] = self._rotator.get_next_proxy(pool, service_key)
                return info

        # Check global pool
        pool_id = self._storage.get_global_default_pool()
        if pool_id:
            pool = self._storage.load_pool(pool_id)
            if pool and pool.enabled and pool.proxies:
                info['pool'] = pool
                info['source'] = 'global'
                info['reason'] = f"Global pool: {pool.name}"
                info['proxy'] = self._rotator.get_next_proxy(pool, service_key)
                return info

        # Check OS proxy
        if self._storage.get_use_os_proxy():
            proxy = self._get_os_proxy()
            if proxy:
                info['proxy'] = proxy
                info['source'] = 'os'
                info['reason'] = 'OS environment proxy'
                return info

        return info
