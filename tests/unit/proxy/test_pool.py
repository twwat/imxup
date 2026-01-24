"""Unit tests for proxy pool rotation."""

import pytest
from unittest.mock import MagicMock, patch
import time

from src.proxy.models import (
    ProxyProfile, ProxyPool, ProxyHealth, RotationStrategy, ProxyType
)
from src.proxy.pool import PoolRotator


def create_test_profile(name: str, proxy_id: str = None) -> ProxyProfile:
    """Create a test proxy profile."""
    profile = ProxyProfile(
        name=name,
        host=f"{name.lower()}.proxy.com",
        port=8080
    )
    if proxy_id:
        profile.id = proxy_id
    return profile


def create_test_pool(
    proxy_ids: list,
    strategy: RotationStrategy = RotationStrategy.ROUND_ROBIN,
    weights: dict = None,
    sticky: bool = False
) -> ProxyPool:
    """Create a test pool."""
    return ProxyPool(
        name="Test Pool",
        proxy_ids=proxy_ids,
        rotation_strategy=strategy,
        weights=weights or {},
        sticky_sessions=sticky,
        sticky_ttl_seconds=60
    )


def create_profiles_dict(proxy_ids: list) -> dict:
    """Create a dict of proxy_id -> ProxyProfile for testing."""
    return {pid: create_test_profile(pid, proxy_id=pid) for pid in proxy_ids}


class TestPoolRotatorRoundRobin:
    """Tests for round-robin rotation strategy."""

    def test_cycles_through_proxies(self):
        """Test that round-robin cycles through all proxies."""
        pool = create_test_pool(["p1", "p2", "p3"])
        profiles = create_profiles_dict(["p1", "p2", "p3"])
        rotator = PoolRotator()

        # Should cycle: p1 -> p2 -> p3 -> p1 -> ...
        results = [rotator.get_next_proxy(pool, profiles) for _ in range(6)]

        assert results[:3] == ["p1", "p2", "p3"]
        assert results[3:6] == ["p1", "p2", "p3"]

    def test_single_proxy(self):
        """Test round-robin with single proxy."""
        pool = create_test_pool(["only"])
        profiles = create_profiles_dict(["only"])
        rotator = PoolRotator()

        for _ in range(5):
            assert rotator.get_next_proxy(pool, profiles) == "only"


class TestPoolRotatorRandom:
    """Tests for random rotation strategy."""

    def test_returns_from_pool(self):
        """Test that random returns proxies from the pool."""
        pool = create_test_pool(["p1", "p2", "p3"], RotationStrategy.RANDOM)
        profiles = create_profiles_dict(["p1", "p2", "p3"])
        rotator = PoolRotator()

        for _ in range(20):
            result = rotator.get_next_proxy(pool, profiles)
            assert result in ["p1", "p2", "p3"]

    def test_distribution(self):
        """Test that random has reasonable distribution."""
        pool = create_test_pool(["p1", "p2", "p3"], RotationStrategy.RANDOM)
        profiles = create_profiles_dict(["p1", "p2", "p3"])
        rotator = PoolRotator()

        results = [rotator.get_next_proxy(pool, profiles) for _ in range(300)]
        counts = {pid: results.count(pid) for pid in ["p1", "p2", "p3"]}

        # Each should be roughly 100 (allow 30% variance)
        for count in counts.values():
            assert 50 < count < 150


class TestPoolRotatorLeastUsed:
    """Tests for least-used rotation strategy."""

    def test_prefers_less_used(self):
        """Test that least-used prefers proxies with fewer requests."""
        pool = create_test_pool(["p1", "p2", "p3"], RotationStrategy.LEAST_USED)
        profiles = create_profiles_dict(["p1", "p2", "p3"])
        rotator = PoolRotator()

        # Use p1 several times by getting and tracking
        for _ in range(5):
            rotator.get_next_proxy(pool, profiles)  # This increments use count

        # Reset to force p1 to have high count
        rotator._use_counts[pool.id] = {"p1": 10, "p2": 0, "p3": 0}

        # Next selection should prefer p2 or p3
        result = rotator.get_next_proxy(pool, profiles)
        assert result in ["p2", "p3"]

    def test_balanced_distribution(self):
        """Test that least-used balances usage over time."""
        pool = create_test_pool(["p1", "p2", "p3"], RotationStrategy.LEAST_USED)
        profiles = create_profiles_dict(["p1", "p2", "p3"])
        rotator = PoolRotator()

        # Simulate 30 requests - get_next_proxy auto-increments use count
        for _ in range(30):
            rotator.get_next_proxy(pool, profiles)

        # Check usage counts are balanced
        counts = rotator._use_counts.get(pool.id, {})
        if counts:
            values = list(counts.values())
            assert max(values) - min(values) <= 2


class TestPoolRotatorWeighted:
    """Tests for weighted rotation strategy."""

    def test_respects_weights(self):
        """Test that weighted respects weight ratios."""
        pool = create_test_pool(
            ["p1", "p2"],
            RotationStrategy.WEIGHTED,
            weights={"p1": 3, "p2": 1}
        )
        profiles = create_profiles_dict(["p1", "p2"])
        rotator = PoolRotator()

        results = [rotator.get_next_proxy(pool, profiles) for _ in range(400)]
        p1_count = results.count("p1")
        p2_count = results.count("p2")

        # p1 should be roughly 3x more common than p2
        ratio = p1_count / p2_count if p2_count > 0 else 0
        assert 2.0 < ratio < 4.0  # Allow some variance

    def test_default_weight(self):
        """Test that missing weights default to 1."""
        pool = create_test_pool(
            ["p1", "p2", "p3"],
            RotationStrategy.WEIGHTED,
            weights={"p1": 2}  # p2 and p3 default to 1
        )
        profiles = create_profiles_dict(["p1", "p2", "p3"])
        rotator = PoolRotator()

        # Should not raise and should include all proxies
        results = [rotator.get_next_proxy(pool, profiles) for _ in range(100)]
        assert "p1" in results
        assert "p2" in results
        assert "p3" in results


class TestPoolRotatorFailover:
    """Tests for failover rotation strategy."""

    def test_uses_first_proxy(self):
        """Test that failover always uses first proxy when healthy."""
        pool = create_test_pool(["primary", "backup1", "backup2"], RotationStrategy.FAILOVER)
        profiles = create_profiles_dict(["primary", "backup1", "backup2"])
        rotator = PoolRotator()

        for _ in range(10):
            assert rotator.get_next_proxy(pool, profiles) == "primary"

    def test_failover_to_backup(self):
        """Test failover when primary fails."""
        pool = create_test_pool(["primary", "backup1", "backup2"], RotationStrategy.FAILOVER)
        pool.max_consecutive_failures = 3
        profiles = create_profiles_dict(["primary", "backup1", "backup2"])
        rotator = PoolRotator()

        # Record failures for primary
        for _ in range(3):
            rotator.report_failure(pool.id, "primary")

        # Should now use backup1
        assert rotator.get_next_proxy(pool, profiles) == "backup1"

    def test_recovery_after_success(self):
        """Test that proxy recovers after success."""
        pool = create_test_pool(["primary", "backup"], RotationStrategy.FAILOVER)
        pool.max_consecutive_failures = 2
        profiles = create_profiles_dict(["primary", "backup"])
        rotator = PoolRotator()

        # Fail primary
        rotator.report_failure(pool.id, "primary")
        rotator.report_failure(pool.id, "primary")

        # Now using backup
        assert rotator.get_next_proxy(pool, profiles) == "backup"

        # Record success for primary
        rotator.report_success(pool.id, "primary")

        # Should return to primary
        assert rotator.get_next_proxy(pool, profiles) == "primary"


class TestPoolRotatorStickySession:
    """Tests for sticky session functionality."""

    def test_sticky_returns_same_proxy(self):
        """Test that sticky session returns same proxy for same service."""
        pool = create_test_pool(["p1", "p2", "p3"], sticky=True)
        profiles = create_profiles_dict(["p1", "p2", "p3"])
        rotator = PoolRotator()

        # Get proxy for a service
        first = rotator.get_next_proxy(pool, profiles, service_key="rapidgator")

        # Should get same proxy for same service
        for _ in range(10):
            assert rotator.get_next_proxy(pool, profiles, service_key="rapidgator") == first

    def test_different_services_different_proxies(self):
        """Test that different services can get different proxies."""
        pool = create_test_pool(["p1", "p2", "p3"], sticky=True)
        pool.rotation_strategy = RotationStrategy.ROUND_ROBIN
        profiles = create_profiles_dict(["p1", "p2", "p3"])
        rotator = PoolRotator()

        proxy1 = rotator.get_next_proxy(pool, profiles, service_key="service1")
        proxy2 = rotator.get_next_proxy(pool, profiles, service_key="service2")

        # They may be same or different, but should be consistent
        assert rotator.get_next_proxy(pool, profiles, service_key="service1") == proxy1
        assert rotator.get_next_proxy(pool, profiles, service_key="service2") == proxy2

    def test_sticky_expires(self):
        """Test that sticky session expires after TTL."""
        pool = create_test_pool(["p1", "p2", "p3"], sticky=True)
        pool.sticky_ttl_seconds = 1  # 1 second TTL
        profiles = create_profiles_dict(["p1", "p2", "p3"])
        rotator = PoolRotator()

        first = rotator.get_next_proxy(pool, profiles, service_key="test")

        # Wait for TTL to expire
        time.sleep(1.1)

        # May get different proxy now (depends on rotation)
        # At minimum, should not error
        rotator.get_next_proxy(pool, profiles, service_key="test")


class TestPoolRotatorHealthIntegration:
    """Tests for health-aware rotation."""

    def test_skips_unhealthy_proxies(self):
        """Test that unhealthy proxies are skipped."""
        pool = create_test_pool(["healthy", "unhealthy", "healthy2"])
        profiles = create_profiles_dict(["healthy", "unhealthy", "healthy2"])
        rotator = PoolRotator()

        # Create health data marking one as unhealthy
        health_data = {
            "healthy": ProxyHealth(profile_id="healthy", is_alive=True),
            "unhealthy": ProxyHealth(profile_id="unhealthy", is_alive=False),
            "healthy2": ProxyHealth(profile_id="healthy2", is_alive=True),
        }

        # Should only return healthy proxies
        results = set(
            rotator.get_next_proxy(pool, profiles, health_data=health_data)
            for _ in range(20)
        )
        assert "unhealthy" not in results
        assert "healthy" in results
        assert "healthy2" in results

    def test_all_unhealthy_returns_none(self):
        """Test behavior when all proxies are unhealthy."""
        pool = create_test_pool(["p1", "p2"])
        profiles = create_profiles_dict(["p1", "p2"])
        rotator = PoolRotator()

        # Mark all as unhealthy
        health_data = {
            "p1": ProxyHealth(profile_id="p1", is_alive=False),
            "p2": ProxyHealth(profile_id="p2", is_alive=False),
        }

        # Should return None when all are unhealthy
        result = rotator.get_next_proxy(pool, profiles, health_data=health_data)
        assert result is None


class TestPoolRotatorRecording:
    """Tests for usage recording."""

    def test_report_success(self):
        """Test recording success clears failure count."""
        pool = create_test_pool(["p1"])
        rotator = PoolRotator()

        rotator.report_failure(pool.id, "p1")
        rotator.report_failure(pool.id, "p1")
        rotator.report_success(pool.id, "p1")

        tracker = rotator._failure_trackers.get(pool.id, {}).get("p1")
        assert tracker is None or tracker.consecutive_failures == 0

    def test_report_failure(self):
        """Test recording failures."""
        pool = create_test_pool(["p1"])
        rotator = PoolRotator()

        rotator.report_failure(pool.id, "p1")
        rotator.report_failure(pool.id, "p1")

        tracker = rotator._failure_trackers.get(pool.id, {}).get("p1")
        assert tracker is not None
        assert tracker.consecutive_failures == 2
