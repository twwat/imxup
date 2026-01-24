"""Unit tests for proxy models."""

import pytest
from dataclasses import asdict

from src.proxy.models import (
    ProxyProfile, ProxyType, ProxyContext, ProxyPool,
    ProxyHealth, RotationStrategy
)


class TestProxyType:
    """Tests for ProxyType enum."""

    def test_values(self):
        """Test all proxy types have correct string values."""
        assert ProxyType.HTTP.value == "http"
        assert ProxyType.HTTPS.value == "https"
        assert ProxyType.SOCKS4.value == "socks4"
        assert ProxyType.SOCKS5.value == "socks5"

    def test_from_string(self):
        """Test creating ProxyType from string."""
        assert ProxyType("http") == ProxyType.HTTP
        assert ProxyType("socks5") == ProxyType.SOCKS5


class TestRotationStrategy:
    """Tests for RotationStrategy enum."""

    def test_all_strategies(self):
        """Test all rotation strategies exist."""
        strategies = [
            RotationStrategy.ROUND_ROBIN,
            RotationStrategy.RANDOM,
            RotationStrategy.LEAST_USED,
            RotationStrategy.WEIGHTED,
            RotationStrategy.FAILOVER,
        ]
        assert len(strategies) == 5


class TestProxyProfile:
    """Tests for ProxyProfile dataclass."""

    def test_create_basic_profile(self):
        """Test creating a basic proxy profile."""
        profile = ProxyProfile(
            name="Test Proxy",
            host="proxy.example.com",
            port=8080
        )
        assert profile.name == "Test Proxy"
        assert profile.host == "proxy.example.com"
        assert profile.port == 8080
        assert profile.proxy_type == ProxyType.HTTP
        assert profile.enabled is True
        assert profile.auth_required is False

    def test_profile_with_auth(self):
        """Test profile with authentication."""
        profile = ProxyProfile(
            name="Auth Proxy",
            host="proxy.example.com",
            port=1080,
            proxy_type=ProxyType.SOCKS5,
            auth_required=True,
            username="testuser"
        )
        assert profile.auth_required is True
        assert profile.username == "testuser"
        assert profile.proxy_type == ProxyType.SOCKS5

    def test_profile_id_generated(self):
        """Test that profile ID is auto-generated."""
        profile = ProxyProfile(name="Test", host="test.com", port=8080)
        assert profile.id is not None
        assert len(profile.id) > 0

    def test_get_proxy_url_basic(self):
        """Test get_proxy_url for basic profile."""
        profile = ProxyProfile(
            name="Test",
            host="proxy.example.com",
            port=8080,
            proxy_type=ProxyType.HTTP
        )
        assert profile.get_proxy_url() == "http://proxy.example.com:8080"

    def test_get_proxy_url_socks(self):
        """Test get_proxy_url for SOCKS proxy."""
        profile = ProxyProfile(
            name="Test",
            host="socks.example.com",
            port=1080,
            proxy_type=ProxyType.SOCKS5
        )
        assert profile.get_proxy_url() == "socks5://socks.example.com:1080"

    def test_bypass_list(self):
        """Test bypass list functionality."""
        profile = ProxyProfile(
            name="Test",
            host="proxy.com",
            port=8080,
            bypass_list=["localhost", "127.0.0.1", "*.local"]
        )
        assert len(profile.bypass_list) == 3
        assert "localhost" in profile.bypass_list

    def test_to_dict(self):
        """Test converting profile to dictionary."""
        profile = ProxyProfile(
            name="Test",
            host="proxy.com",
            port=8080,
            proxy_type=ProxyType.HTTP
        )
        d = asdict(profile)
        assert d["name"] == "Test"
        assert d["host"] == "proxy.com"
        assert d["port"] == 8080


class TestProxyContext:
    """Tests for ProxyContext dataclass."""

    def test_create_context(self):
        """Test creating a proxy context."""
        context = ProxyContext(
            category="file_hosts",
            service_id="rapidgator"
        )
        assert context.category == "file_hosts"
        assert context.service_id == "rapidgator"
        assert context.operation == ""

    def test_context_with_operation(self):
        """Test context with operation."""
        context = ProxyContext(
            category="api",
            service_id="external",
            operation="download"
        )
        assert context.operation == "download"


class TestProxyPool:
    """Tests for ProxyPool dataclass."""

    def test_create_basic_pool(self):
        """Test creating a basic pool."""
        pool = ProxyPool(
            name="Test Pool",
            proxy_ids=["proxy1", "proxy2"]
        )
        assert pool.name == "Test Pool"
        assert len(pool.proxy_ids) == 2
        assert pool.rotation_strategy == RotationStrategy.ROUND_ROBIN
        assert pool.enabled is True

    def test_pool_with_rotation_strategy(self):
        """Test pool with specific rotation strategy."""
        pool = ProxyPool(
            name="Random Pool",
            proxy_ids=["p1", "p2", "p3"],
            rotation_strategy=RotationStrategy.RANDOM
        )
        assert pool.rotation_strategy == RotationStrategy.RANDOM

    def test_pool_with_weights(self):
        """Test pool with weighted proxies."""
        pool = ProxyPool(
            name="Weighted Pool",
            proxy_ids=["p1", "p2"],
            rotation_strategy=RotationStrategy.WEIGHTED,
            weights={"p1": 3, "p2": 1}
        )
        assert pool.weights["p1"] == 3
        assert pool.weights["p2"] == 1

    def test_sticky_sessions(self):
        """Test sticky session configuration."""
        pool = ProxyPool(
            name="Sticky Pool",
            proxy_ids=["p1"],
            sticky_sessions=True,
            sticky_ttl_seconds=7200
        )
        assert pool.sticky_sessions is True
        assert pool.sticky_ttl_seconds == 7200

    def test_failover_settings(self):
        """Test failover configuration."""
        pool = ProxyPool(
            name="Failover Pool",
            proxy_ids=["p1", "p2", "p3"],
            rotation_strategy=RotationStrategy.FAILOVER,
            fallback_on_failure=True,
            max_consecutive_failures=5
        )
        assert pool.fallback_on_failure is True
        assert pool.max_consecutive_failures == 5


class TestProxyHealth:
    """Tests for ProxyHealth dataclass."""

    def test_default_values(self):
        """Test default health values."""
        health = ProxyHealth(profile_id="test-id")
        assert health.profile_id == "test-id"
        assert health.is_alive is True
        assert health.latency_ms == 0.0
        assert health.total_requests == 0
        assert health.failed_requests == 0
        assert health.consecutive_failures == 0

    def test_update_health(self):
        """Test updating health values."""
        health = ProxyHealth(profile_id="test-id")
        health.is_alive = False
        health.latency_ms = 150.5
        health.consecutive_failures = 3

        assert health.is_alive is False
        assert health.latency_ms == 150.5
        assert health.consecutive_failures == 3
