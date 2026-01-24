"""Proxy profile and assignment persistence using QSettings."""

import json
from typing import Optional, List, Dict
from PyQt6.QtCore import QSettings

from src.proxy.models import ProxyProfile, ProxyPool, ProxyHealth
from src.proxy.credentials import remove_proxy_password


class ProxyStorage:
    """Manages proxy profile, pool, and assignment persistence."""

    PROFILES_GROUP = "Proxy/Profiles"
    POOLS_GROUP = "Proxy/Pools"
    HEALTH_GROUP = "Proxy/Health"
    POOL_ASSIGNMENTS_GROUP = "Proxy/PoolAssignments"
    ASSIGNMENTS_GROUP = "Proxy/Assignments"
    GLOBAL_DEFAULT_KEY = "Proxy/GlobalDefault"
    GLOBAL_DEFAULT_POOL_KEY = "Proxy/GlobalDefaultPool"
    USE_OS_PROXY_KEY = "Proxy/UseOSProxy"

    def __init__(self):
        self._settings = QSettings("imxup", "imxup")

    # === Profile CRUD (Legacy - kept for bulk import compatibility) ===

    def save_profile(self, profile: ProxyProfile) -> None:
        """Save a proxy profile."""
        self._settings.beginGroup(self.PROFILES_GROUP)
        self._settings.setValue(profile.id, json.dumps(profile.to_dict()))
        self._settings.endGroup()
        self._settings.sync()

    def load_profile(self, profile_id: str) -> Optional[ProxyProfile]:
        """Load a proxy profile by ID."""
        self._settings.beginGroup(self.PROFILES_GROUP)
        data = self._settings.value(profile_id)
        self._settings.endGroup()

        if data:
            try:
                return ProxyProfile.from_dict(json.loads(data))
            except (json.JSONDecodeError, KeyError):
                return None
        return None

    def delete_profile(self, profile_id: str) -> None:
        """Delete a proxy profile and its credentials."""
        # Remove from settings
        self._settings.beginGroup(self.PROFILES_GROUP)
        self._settings.remove(profile_id)
        self._settings.endGroup()

        # Remove password from keyring
        remove_proxy_password(profile_id)

        # Clear any assignments using this profile
        self._clear_assignments_for_profile(profile_id)

        self._settings.sync()

    def list_profiles(self) -> List[ProxyProfile]:
        """List all saved proxy profiles."""
        profiles = []
        self._settings.beginGroup(self.PROFILES_GROUP)
        for profile_id in self._settings.childKeys():
            data = self._settings.value(profile_id)
            if data:
                try:
                    profiles.append(ProxyProfile.from_dict(json.loads(data)))
                except (json.JSONDecodeError, KeyError):
                    pass
        self._settings.endGroup()
        return profiles

    # === Profile Assignments (Legacy - kept for ProxySelector compatibility) ===

    def get_assignment(self, category: str, service_id: Optional[str] = None) -> Optional[str]:
        """Get assigned profile ID for a service or category."""
        self._settings.beginGroup(self.ASSIGNMENTS_GROUP)

        if service_id:
            # Service-specific assignment
            key = f"{category}/{service_id}"
        else:
            # Category default
            key = f"{category}/_default"

        profile_id = self._settings.value(key, "")
        self._settings.endGroup()

        return profile_id if profile_id else None

    def set_assignment(self, profile_id: Optional[str], category: str,
                       service_id: Optional[str] = None) -> None:
        """Assign a profile to a service or category. None clears assignment."""
        self._settings.beginGroup(self.ASSIGNMENTS_GROUP)

        if service_id:
            key = f"{category}/{service_id}"
        else:
            key = f"{category}/_default"

        if profile_id:
            self._settings.setValue(key, profile_id)
        else:
            self._settings.remove(key)

        self._settings.endGroup()
        self._settings.sync()

    def clear_assignment(self, category: str, service_id: Optional[str] = None) -> None:
        """Clear an assignment."""
        self.set_assignment(None, category, service_id)

    # === Global Settings (Legacy profile-based - use get_global_default_pool instead) ===

    def get_global_default(self) -> Optional[str]:
        """Get global default proxy profile ID."""
        return self._settings.value(self.GLOBAL_DEFAULT_KEY, "") or None

    def set_global_default(self, profile_id: Optional[str]) -> None:
        """Set global default proxy profile."""
        if profile_id:
            self._settings.setValue(self.GLOBAL_DEFAULT_KEY, profile_id)
        else:
            self._settings.remove(self.GLOBAL_DEFAULT_KEY)
        self._settings.sync()

    def get_use_os_proxy(self) -> bool:
        """Check if OS proxy should be used as fallback."""
        return self._settings.value(self.USE_OS_PROXY_KEY, False, type=bool)

    def set_use_os_proxy(self, enabled: bool) -> None:
        """Set whether to use OS proxy as fallback."""
        self._settings.setValue(self.USE_OS_PROXY_KEY, enabled)
        self._settings.sync()

    # === Helpers ===

    def _clear_assignments_for_profile(self, profile_id: str) -> None:
        """Clear all assignments that reference a profile."""
        self._settings.beginGroup(self.ASSIGNMENTS_GROUP)

        # Find and remove all keys with this profile_id
        def clear_recursive(group_prefix: str = ""):
            for key in self._settings.childKeys():
                if self._settings.value(key) == profile_id:
                    self._settings.remove(key)

            for group in self._settings.childGroups():
                self._settings.beginGroup(group)
                clear_recursive(f"{group_prefix}{group}/")
                self._settings.endGroup()

        clear_recursive()
        self._settings.endGroup()

        # Also check global default
        if self._settings.value(self.GLOBAL_DEFAULT_KEY) == profile_id:
            self._settings.remove(self.GLOBAL_DEFAULT_KEY)

    # === Pool CRUD ===

    def save_pool(self, pool: ProxyPool) -> None:
        """Save a proxy pool."""
        self._settings.beginGroup(self.POOLS_GROUP)
        self._settings.setValue(pool.id, json.dumps(pool.to_dict()))
        self._settings.endGroup()
        self._settings.sync()

    def load_pool(self, pool_id: str) -> Optional[ProxyPool]:
        """Load a proxy pool by ID."""
        self._settings.beginGroup(self.POOLS_GROUP)
        data = self._settings.value(pool_id)
        self._settings.endGroup()

        if data:
            try:
                return ProxyPool.from_dict(json.loads(data))
            except (json.JSONDecodeError, KeyError):
                return None
        return None

    def delete_pool(self, pool_id: str) -> None:
        """Delete a proxy pool."""
        self._settings.beginGroup(self.POOLS_GROUP)
        self._settings.remove(pool_id)
        self._settings.endGroup()

        # Clear any pool assignments using this pool
        self._clear_pool_assignments_for_pool(pool_id)

        # Clear global default pool if it was this one
        if self._settings.value(self.GLOBAL_DEFAULT_POOL_KEY) == pool_id:
            self._settings.remove(self.GLOBAL_DEFAULT_POOL_KEY)

        self._settings.sync()

    def list_pools(self) -> List[ProxyPool]:
        """List all saved proxy pools."""
        pools = []
        self._settings.beginGroup(self.POOLS_GROUP)
        for pool_id in self._settings.childKeys():
            data = self._settings.value(pool_id)
            if data:
                try:
                    pools.append(ProxyPool.from_dict(json.loads(data)))
                except (json.JSONDecodeError, KeyError):
                    pass
        self._settings.endGroup()
        return pools

    # === Health Persistence ===

    def save_health(self, health: ProxyHealth) -> None:
        """Save proxy health data."""
        self._settings.beginGroup(self.HEALTH_GROUP)
        self._settings.setValue(health.profile_id, json.dumps(health.to_dict()))
        self._settings.endGroup()
        self._settings.sync()

    def load_health(self, profile_id: str) -> Optional[ProxyHealth]:
        """Load proxy health data."""
        self._settings.beginGroup(self.HEALTH_GROUP)
        data = self._settings.value(profile_id)
        self._settings.endGroup()

        if data:
            try:
                return ProxyHealth.from_dict(json.loads(data))
            except (json.JSONDecodeError, KeyError):
                return None
        return None

    def list_health(self) -> Dict[str, ProxyHealth]:
        """List all health records."""
        health_map = {}
        self._settings.beginGroup(self.HEALTH_GROUP)
        for profile_id in self._settings.childKeys():
            data = self._settings.value(profile_id)
            if data:
                try:
                    health_map[profile_id] = ProxyHealth.from_dict(json.loads(data))
                except (json.JSONDecodeError, KeyError):
                    pass
        self._settings.endGroup()
        return health_map

    def clear_health(self, profile_id: Optional[str] = None) -> None:
        """Clear health data for one or all profiles."""
        self._settings.beginGroup(self.HEALTH_GROUP)
        if profile_id:
            self._settings.remove(profile_id)
        else:
            for key in self._settings.childKeys():
                self._settings.remove(key)
        self._settings.endGroup()
        self._settings.sync()

    # === Pool Assignments ===

    def get_pool_assignment(self, category: str, service_id: Optional[str] = None) -> Optional[str]:
        """Get assigned pool ID for a service or category."""
        self._settings.beginGroup(self.POOL_ASSIGNMENTS_GROUP)

        if service_id:
            key = f"{category}/{service_id}"
        else:
            key = f"{category}/_default"

        pool_id = self._settings.value(key, "")
        self._settings.endGroup()

        return pool_id if pool_id else None

    def set_pool_assignment(self, pool_id: Optional[str], category: str,
                            service_id: Optional[str] = None) -> None:
        """Assign a pool to a service or category. None clears assignment."""
        self._settings.beginGroup(self.POOL_ASSIGNMENTS_GROUP)

        if service_id:
            key = f"{category}/{service_id}"
        else:
            key = f"{category}/_default"

        if pool_id:
            self._settings.setValue(key, pool_id)
        else:
            self._settings.remove(key)

        self._settings.endGroup()
        self._settings.sync()

    def clear_pool_assignment(self, category: str, service_id: Optional[str] = None) -> None:
        """Clear a pool assignment."""
        self.set_pool_assignment(None, category, service_id)

    def get_global_default_pool(self) -> Optional[str]:
        """Get global default pool ID."""
        return self._settings.value(self.GLOBAL_DEFAULT_POOL_KEY, "") or None

    def set_global_default_pool(self, pool_id: Optional[str]) -> None:
        """Set global default pool."""
        if pool_id:
            self._settings.setValue(self.GLOBAL_DEFAULT_POOL_KEY, pool_id)
        else:
            self._settings.remove(self.GLOBAL_DEFAULT_POOL_KEY)
        self._settings.sync()

    def _clear_pool_assignments_for_pool(self, pool_id: str) -> None:
        """Clear all assignments that reference a pool."""
        self._settings.beginGroup(self.POOL_ASSIGNMENTS_GROUP)

        def clear_recursive(group_prefix: str = ""):
            for key in self._settings.childKeys():
                if self._settings.value(key) == pool_id:
                    self._settings.remove(key)

            for group in self._settings.childGroups():
                self._settings.beginGroup(group)
                clear_recursive(f"{group_prefix}{group}/")
                self._settings.endGroup()

        clear_recursive()
        self._settings.endGroup()
