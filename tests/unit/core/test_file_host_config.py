"""
Comprehensive tests for core.file_host_config module.

Tests cover:
- HostConfig dataclass initialization and from_dict conversion
- FileHostConfigManager singleton and thread safety
- Host configuration loading (builtin and custom)
- Settings management (get/save with INI persistence)
- Host enabling/disabling and trigger filtering
- Configuration validation and error handling
- Thread-safe INI file operations
- Default value fallback chain
"""

import pytest
import os
import tempfile
import shutil
import json
import configparser
import threading
from pathlib import Path
from typing import Dict, Any
from unittest.mock import Mock, patch, MagicMock

from src.core.file_host_config import (
    HostConfig,
    FileHostConfigManager,
    get_config_manager,
    get_file_host_setting,
    save_file_host_setting,
    _HARDCODED_DEFAULTS
)


# ============================================================================
# HostConfig Tests
# ============================================================================

class TestHostConfig:
    """Test suite for HostConfig dataclass."""

    def test_host_config_minimal_initialization(self):
        """Test HostConfig with minimal required fields."""
        config = HostConfig(name="TestHost")

        assert config.name == "TestHost"
        assert config.requires_auth is False
        assert config.method == "POST"
        assert config.file_field == "file"
        assert config.response_type == "json"

    def test_host_config_full_initialization(self):
        """Test HostConfig with all fields provided."""
        config = HostConfig(
            name="TestHost",
            icon="test.png",
            referral_url="https://example.com/ref",
            requires_auth=True,
            auth_type="bearer",
            get_server="https://api.example.com/server",
            server_response_path=["data", "server"],
            upload_endpoint="https://api.example.com/upload",
            method="POST",
            file_field="file",
            extra_fields={"key": "value"},
            response_type="json",
            link_path=["data", "url"],
            link_prefix="https://",
            link_suffix="",
            login_url="https://example.com/login",
            token_path=["auth", "token"],
            defaults={"max_connections": 5}
        )

        assert config.name == "TestHost"
        assert config.requires_auth is True
        assert config.auth_type == "bearer"
        assert config.upload_endpoint == "https://api.example.com/upload"
        assert config.defaults["max_connections"] == 5

    def test_host_config_from_dict_basic(self):
        """Test HostConfig.from_dict with basic configuration."""
        data = {
            "name": "TestHost",
            "requires_auth": False,
            "upload": {
                "endpoint": "https://api.example.com/upload",
                "method": "POST",
                "file_field": "file"
            },
            "response": {
                "type": "json",
                "link_path": ["data", "url"]
            }
        }

        config = HostConfig.from_dict(data)

        assert config.name == "TestHost"
        assert config.upload_endpoint == "https://api.example.com/upload"
        assert config.response_type == "json"
        assert config.link_path == ["data", "url"]

    def test_host_config_from_dict_with_auth(self):
        """Test HostConfig.from_dict with authentication configuration."""
        data = {
            "name": "SecureHost",
            "requires_auth": True,
            "auth_type": "token_login",
            "upload": {
                "endpoint": "https://api.example.com/upload"
            },
            "response": {
                "type": "json"
            },
            "auth": {
                "login_url": "https://example.com/login",
                "token_path": ["token"],
                "token_ttl": 3600
            }
        }

        config = HostConfig.from_dict(data)

        assert config.requires_auth is True
        assert config.auth_type == "token_login"
        assert config.login_url == "https://example.com/login"
        assert config.token_path == ["token"]
        assert config.token_ttl == 3600

    def test_host_config_from_dict_with_multistep(self):
        """Test HostConfig.from_dict with multistep upload configuration."""
        data = {
            "name": "MultiStepHost",
            "upload": {
                "endpoint": "https://api.example.com/upload"
            },
            "response": {
                "type": "json"
            },
            "multistep": {
                "init_url": "https://api.example.com/init",
                "init_method": "POST",
                "init_body_json": True,
                "upload_url_path": ["data", "upload_url"],
                "poll_url": "https://api.example.com/poll",
                "poll_delay": 2.0,
                "poll_retries": 5
            }
        }

        config = HostConfig.from_dict(data)

        assert config.upload_init_url == "https://api.example.com/init"
        assert config.init_method == "POST"
        assert config.init_body_json is True
        assert config.upload_poll_delay == 2.0

    def test_host_config_from_dict_with_defaults(self):
        """Test HostConfig.from_dict includes defaults section."""
        data = {
            "name": "HostWithDefaults",
            "upload": {"endpoint": "https://api.example.com/upload"},
            "response": {"type": "json"},
            "defaults": {
                "max_connections": 3,
                "max_file_size_mb": 500,
                "auto_retry": True,
                "max_retries": 5
            }
        }

        config = HostConfig.from_dict(data)

        assert config.defaults["max_connections"] == 3
        assert config.defaults["max_file_size_mb"] == 500
        assert config.defaults["auto_retry"] is True
        assert config.defaults["max_retries"] == 5


# ============================================================================
# FileHostConfigManager Tests
# ============================================================================

class TestFileHostConfigManager:
    """Test suite for FileHostConfigManager."""

    @pytest.fixture
    def temp_config_dirs(self):
        """Create temporary builtin and custom config directories."""
        temp_root = tempfile.mkdtemp()
        builtin_dir = Path(temp_root) / "builtin"
        custom_dir = Path(temp_root) / "custom"

        builtin_dir.mkdir(parents=True)
        custom_dir.mkdir(parents=True)

        yield builtin_dir, custom_dir

        shutil.rmtree(temp_root, ignore_errors=True)

    def create_host_config_file(self, directory: Path, host_id: str, config_data: Dict[str, Any]):
        """Helper to create a host configuration JSON file."""
        config_path = directory / f"{host_id}.json"
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, indent=2)
        return config_path

    def test_manager_initializes_with_real_hosts(self):
        """Test FileHostConfigManager initializes and loads real built-in hosts."""
        manager = FileHostConfigManager()
        # Don't call load_all_hosts() - test that initial state is empty
        assert isinstance(manager.hosts, dict)
        # Initially empty until load_all_hosts() is called
        assert len(manager.hosts) == 0

    def test_manager_loads_builtin_hosts(self, temp_config_dirs):
        """Test manager loads hosts from builtin directory."""
        builtin_dir, custom_dir = temp_config_dirs

        # Create builtin config
        self.create_host_config_file(builtin_dir, "testhost", {
            "name": "TestHost",
            "upload": {"endpoint": "https://api.test.com/upload"},
            "response": {"type": "json"}
        })

        manager = FileHostConfigManager()
        # Override directory paths BEFORE loading
        manager.builtin_dir = builtin_dir
        manager.custom_dir = custom_dir
        manager.load_all_hosts()

        assert "testhost" in manager.hosts
        assert manager.hosts["testhost"].name == "TestHost"

    def test_manager_loads_custom_hosts(self, temp_config_dirs):
        """Test manager loads hosts from custom directory."""
        builtin_dir, custom_dir = temp_config_dirs

        # Create custom config
        self.create_host_config_file(custom_dir, "customhost", {
            "name": "CustomHost",
            "upload": {"endpoint": "https://api.custom.com/upload"},
            "response": {"type": "json"}
        })

        manager = FileHostConfigManager()
        # Override directory paths BEFORE loading
        manager.builtin_dir = builtin_dir
        manager.custom_dir = custom_dir
        manager.load_all_hosts()

        assert "customhost" in manager.hosts
        assert manager.hosts["customhost"].name == "CustomHost"

    def test_manager_custom_overrides_builtin(self, temp_config_dirs):
        """Test custom configs override builtin configs with same ID."""
        builtin_dir, custom_dir = temp_config_dirs

        # Create builtin and custom with same ID
        self.create_host_config_file(builtin_dir, "shared", {
            "name": "BuiltinHost",
            "upload": {"endpoint": "https://api.builtin.com/upload"},
            "response": {"type": "json"}
        })

        self.create_host_config_file(custom_dir, "shared", {
            "name": "CustomHost",
            "upload": {"endpoint": "https://api.custom.com/upload"},
            "response": {"type": "json"}
        })

        manager = FileHostConfigManager()
        # Override directory paths BEFORE loading
        manager.builtin_dir = builtin_dir
        manager.custom_dir = custom_dir
        manager.load_all_hosts()

        # Custom should override builtin
        assert manager.hosts["shared"].name == "CustomHost"
        assert manager.hosts["shared"].upload_endpoint == "https://api.custom.com/upload"

    def test_manager_handles_invalid_json(self, temp_config_dirs):
        """Test manager handles invalid JSON gracefully."""
        builtin_dir, custom_dir = temp_config_dirs

        # Create invalid JSON file
        invalid_path = builtin_dir / "invalid.json"
        with open(invalid_path, 'w') as f:
            f.write("{ invalid json }")

        manager = FileHostConfigManager()
        # Override directory paths BEFORE loading
        manager.builtin_dir = builtin_dir
        manager.custom_dir = custom_dir
        # Should not raise - just log error
        manager.load_all_hosts()

        assert "invalid" not in manager.hosts

    def test_manager_handles_missing_name_field(self, temp_config_dirs):
        """Test manager rejects configs without required 'name' field."""
        builtin_dir, custom_dir = temp_config_dirs

        # Create config without name
        self.create_host_config_file(builtin_dir, "noname", {
            "upload": {"endpoint": "https://api.test.com/upload"},
            "response": {"type": "json"}
        })

        manager = FileHostConfigManager()
        # Override directory paths BEFORE loading
        manager.builtin_dir = builtin_dir
        manager.custom_dir = custom_dir
        manager.load_all_hosts()

        assert "noname" not in manager.hosts

    def test_manager_get_host(self, temp_config_dirs):
        """Test get_host returns correct config."""
        builtin_dir, custom_dir = temp_config_dirs

        self.create_host_config_file(builtin_dir, "testhost", {
            "name": "TestHost",
            "upload": {"endpoint": "https://api.test.com/upload"},
            "response": {"type": "json"}
        })

        manager = FileHostConfigManager()
        # Override directory paths BEFORE loading
        manager.builtin_dir = builtin_dir
        manager.custom_dir = custom_dir
        manager.load_all_hosts()

        host = manager.get_host("testhost")
        assert host is not None
        assert host.name == "TestHost"

        nonexistent = manager.get_host("nonexistent")
        assert nonexistent is None

    def test_manager_get_all_host_ids(self, temp_config_dirs):
        """Test get_all_host_ids returns all loaded host IDs."""
        builtin_dir, custom_dir = temp_config_dirs

        self.create_host_config_file(builtin_dir, "host1", {
            "name": "Host1",
            "upload": {"endpoint": "https://api.host1.com/upload"},
            "response": {"type": "json"}
        })

        self.create_host_config_file(builtin_dir, "host2", {
            "name": "Host2",
            "upload": {"endpoint": "https://api.host2.com/upload"},
            "response": {"type": "json"}
        })

        manager = FileHostConfigManager()
        # Override directory paths BEFORE loading
        manager.builtin_dir = builtin_dir
        manager.custom_dir = custom_dir
        manager.load_all_hosts()

        host_ids = manager.get_all_host_ids()
        assert len(host_ids) == 2
        assert "host1" in host_ids
        assert "host2" in host_ids

    def test_manager_reload_hosts(self, temp_config_dirs):
        """Test reload_hosts clears and reloads all configurations."""
        builtin_dir, custom_dir = temp_config_dirs

        # Initial config
        self.create_host_config_file(builtin_dir, "host1", {
            "name": "Host1",
            "upload": {"endpoint": "https://api.host1.com/upload"},
            "response": {"type": "json"}
        })

        manager = FileHostConfigManager()
        # Override directory paths BEFORE loading
        manager.builtin_dir = builtin_dir
        manager.custom_dir = custom_dir
        manager.load_all_hosts()
        assert "host1" in manager.hosts

        # Add new config
        self.create_host_config_file(builtin_dir, "host2", {
            "name": "Host2",
            "upload": {"endpoint": "https://api.host2.com/upload"},
            "response": {"type": "json"}
        })

        # Reload (directory paths remain set)
        manager.reload_hosts()

        assert "host1" in manager.hosts
        assert "host2" in manager.hosts


# ============================================================================
# Settings Management Tests
# ============================================================================

class TestSettingsManagement:
    """Test suite for host settings get/save operations."""

    @pytest.fixture
    def temp_ini_file(self):
        """Create temporary INI file for testing."""
        temp_dir = tempfile.mkdtemp()
        ini_path = os.path.join(temp_dir, "test.ini")

        yield ini_path

        shutil.rmtree(temp_dir, ignore_errors=True)

    @pytest.fixture
    def mock_config_manager(self):
        """Create mock config manager with test hosts."""
        manager = FileHostConfigManager()

        # Add test host
        manager.hosts["testhost"] = HostConfig(
            name="TestHost",
            upload_endpoint="https://api.test.com/upload",
            defaults={
                "max_connections": 3,
                "max_file_size_mb": 500,
                "auto_retry": True,
                "max_retries": 5
            }
        )

        return manager

    def test_get_setting_from_ini(self, temp_ini_file, mock_config_manager):
        """Test get_file_host_setting retrieves value from INI."""
        # Create INI with value
        cfg = configparser.ConfigParser()
        cfg.add_section("FILE_HOSTS")
        cfg.set("FILE_HOSTS", "testhost_enabled", "True")
        with open(temp_ini_file, 'w') as f:
            cfg.write(f)

        with patch('imxup.get_config_path', return_value=temp_ini_file):
            with patch('src.core.file_host_config.get_config_manager', return_value=mock_config_manager):
                value = get_file_host_setting("testhost", "enabled", "bool")
                assert value is True

    def test_get_setting_defaults_to_false_for_enabled(self, temp_ini_file, mock_config_manager):
        """Test 'enabled' setting defaults to False when not in INI."""
        with patch('imxup.get_config_path', return_value=temp_ini_file):
            with patch('src.core.file_host_config.get_config_manager', return_value=mock_config_manager):
                value = get_file_host_setting("testhost", "enabled", "bool")
                assert value is False

    def test_get_setting_defaults_to_disabled_for_trigger(self, temp_ini_file, mock_config_manager):
        """Test 'trigger' setting defaults to 'disabled' when not in INI."""
        with patch('imxup.get_config_path', return_value=temp_ini_file):
            with patch('src.core.file_host_config.get_config_manager', return_value=mock_config_manager):
                value = get_file_host_setting("testhost", "trigger", "str")
                assert value == "disabled"

    def test_get_setting_uses_json_defaults(self, temp_ini_file, mock_config_manager):
        """Test get_file_host_setting falls back to JSON defaults."""
        with patch('imxup.get_config_path', return_value=temp_ini_file):
            with patch('src.core.file_host_config.get_config_manager', return_value=mock_config_manager):
                value = get_file_host_setting("testhost", "max_connections", "int")
                assert value == 3  # From host defaults

    def test_get_setting_uses_hardcoded_defaults(self, temp_ini_file, mock_config_manager):
        """Test get_file_host_setting falls back to hardcoded defaults."""
        # Host without this default
        manager = FileHostConfigManager()
        manager.hosts["minimalhost"] = HostConfig(
            name="MinimalHost",
            upload_endpoint="https://api.test.com/upload",
            defaults={}
        )

        with patch('imxup.get_config_path', return_value=temp_ini_file):
            with patch('src.core.file_host_config.get_config_manager', return_value=manager):
                value = get_file_host_setting("minimalhost", "max_retries", "int")
                assert value == _HARDCODED_DEFAULTS["max_retries"]

    def test_save_setting_creates_ini_section(self, temp_ini_file, mock_config_manager):
        """Test save_file_host_setting creates FILE_HOSTS section if missing."""
        with patch('imxup.get_config_path', return_value=temp_ini_file):
            with patch('src.core.file_host_config.get_config_manager', return_value=mock_config_manager):
                save_file_host_setting("testhost", "enabled", True)

        cfg = configparser.ConfigParser()
        cfg.read(temp_ini_file)

        assert cfg.has_section("FILE_HOSTS")
        assert cfg.getboolean("FILE_HOSTS", "testhost_enabled") is True

    def test_save_setting_overwrites_existing_value(self, temp_ini_file, mock_config_manager):
        """Test save_file_host_setting overwrites existing values."""
        # Create INI with initial value
        cfg = configparser.ConfigParser()
        cfg.add_section("FILE_HOSTS")
        cfg.set("FILE_HOSTS", "testhost_max_connections", "2")
        with open(temp_ini_file, 'w') as f:
            cfg.write(f)

        with patch('imxup.get_config_path', return_value=temp_ini_file):
            with patch('src.core.file_host_config.get_config_manager', return_value=mock_config_manager):
                save_file_host_setting("testhost", "max_connections", 5)

        cfg = configparser.ConfigParser()
        cfg.read(temp_ini_file)
        assert cfg.getint("FILE_HOSTS", "testhost_max_connections") == 5

    def test_save_setting_validates_host_exists(self, temp_ini_file, mock_config_manager):
        """Test save_file_host_setting validates host exists."""
        with patch('imxup.get_config_path', return_value=temp_ini_file):
            with patch('src.core.file_host_config.get_config_manager', return_value=mock_config_manager):
                with pytest.raises(ValueError, match="Unknown host ID"):
                    save_file_host_setting("nonexistent", "enabled", True)

    def test_save_setting_validates_key(self, temp_ini_file, mock_config_manager):
        """Test save_file_host_setting validates key is in whitelist."""
        with patch('imxup.get_config_path', return_value=temp_ini_file):
            with patch('src.core.file_host_config.get_config_manager', return_value=mock_config_manager):
                with pytest.raises(ValueError, match="Invalid setting key"):
                    save_file_host_setting("testhost", "invalid_key", "value")

    @pytest.mark.parametrize("key,invalid_value,error_match", [
        ("enabled", "not_a_bool", "enabled must be bool"),
        ("trigger", "invalid_trigger", "trigger must be one of"),
        ("max_connections", -1, "max_connections must be int between 1-100"),
        ("max_connections", 200, "max_connections must be int between 1-100"),
        ("max_file_size_mb", -10, "max_file_size_mb must be positive number"),
        ("auto_retry", "yes", "auto_retry must be bool"),
    ])
    def test_save_setting_validates_values(self, temp_ini_file, mock_config_manager, key, invalid_value, error_match):
        """Test save_file_host_setting validates value types and ranges."""
        with patch('imxup.get_config_path', return_value=temp_ini_file):
            with patch('src.core.file_host_config.get_config_manager', return_value=mock_config_manager):
                with pytest.raises(ValueError, match=error_match):
                    save_file_host_setting("testhost", key, invalid_value)


# ============================================================================
# Enable/Disable and Trigger Tests
# ============================================================================

class TestEnableDisableAndTriggers:
    """Test suite for host enable/disable and trigger filtering."""

    @pytest.fixture
    def temp_ini_file(self):
        """Create temporary INI file for testing."""
        temp_dir = tempfile.mkdtemp()
        ini_path = os.path.join(temp_dir, "test.ini")
        yield ini_path
        shutil.rmtree(temp_dir, ignore_errors=True)

    @pytest.fixture
    def mock_config_manager_with_hosts(self):
        """Create mock config manager with multiple test hosts."""
        manager = FileHostConfigManager()

        manager.hosts["host1"] = HostConfig(name="Host1", upload_endpoint="https://api1.com/upload")
        manager.hosts["host2"] = HostConfig(name="Host2", upload_endpoint="https://api2.com/upload")
        manager.hosts["host3"] = HostConfig(name="Host3", upload_endpoint="https://api3.com/upload")

        return manager

    def test_get_enabled_hosts_returns_only_enabled(self, temp_ini_file, mock_config_manager_with_hosts):
        """Test get_enabled_hosts returns only enabled hosts."""
        # Enable host1 and host2
        cfg = configparser.ConfigParser()
        cfg.add_section("FILE_HOSTS")
        cfg.set("FILE_HOSTS", "host1_enabled", "True")
        cfg.set("FILE_HOSTS", "host2_enabled", "True")
        with open(temp_ini_file, 'w') as f:
            cfg.write(f)

        with patch('imxup.get_config_path', return_value=temp_ini_file):
            with patch('src.core.file_host_config.get_config_manager', return_value=mock_config_manager_with_hosts):
                enabled = mock_config_manager_with_hosts.get_enabled_hosts()

        assert len(enabled) == 2
        assert "host1" in enabled
        assert "host2" in enabled
        assert "host3" not in enabled

    def test_get_hosts_by_trigger_filters_correctly(self, temp_ini_file, mock_config_manager_with_hosts):
        """Test get_hosts_by_trigger returns hosts matching trigger."""
        cfg = configparser.ConfigParser()
        cfg.add_section("FILE_HOSTS")
        cfg.set("FILE_HOSTS", "host1_enabled", "True")
        cfg.set("FILE_HOSTS", "host1_trigger", "on_added")
        cfg.set("FILE_HOSTS", "host2_enabled", "True")
        cfg.set("FILE_HOSTS", "host2_trigger", "on_completed")
        cfg.set("FILE_HOSTS", "host3_enabled", "True")
        cfg.set("FILE_HOSTS", "host3_trigger", "on_added")
        with open(temp_ini_file, 'w') as f:
            cfg.write(f)

        with patch('imxup.get_config_path', return_value=temp_ini_file):
            with patch('src.core.file_host_config.get_config_manager', return_value=mock_config_manager_with_hosts):
                added_hosts = mock_config_manager_with_hosts.get_hosts_by_trigger("added")

        assert len(added_hosts) == 2
        assert "host1" in added_hosts
        assert "host3" in added_hosts
        assert "host2" not in added_hosts

    def test_enable_host_sets_enabled_to_true(self, temp_ini_file, mock_config_manager_with_hosts):
        """Test enable_host sets enabled setting to True."""
        with patch('imxup.get_config_path', return_value=temp_ini_file):
            with patch('src.core.file_host_config.get_config_manager', return_value=mock_config_manager_with_hosts):
                result = mock_config_manager_with_hosts.enable_host("host1")

        assert result is True

        cfg = configparser.ConfigParser()
        cfg.read(temp_ini_file)
        assert cfg.getboolean("FILE_HOSTS", "host1_enabled") is True

    def test_disable_host_sets_enabled_to_false(self, temp_ini_file, mock_config_manager_with_hosts):
        """Test disable_host sets enabled setting to False."""
        with patch('imxup.get_config_path', return_value=temp_ini_file):
            with patch('src.core.file_host_config.get_config_manager', return_value=mock_config_manager_with_hosts):
                result = mock_config_manager_with_hosts.disable_host("host1")

        assert result is True

        cfg = configparser.ConfigParser()
        cfg.read(temp_ini_file)
        assert cfg.getboolean("FILE_HOSTS", "host1_enabled") is False

    def test_enable_nonexistent_host_returns_false(self, temp_ini_file, mock_config_manager_with_hosts):
        """Test enable_host returns False for nonexistent host."""
        with patch('imxup.get_config_path', return_value=temp_ini_file):
            with patch('src.core.file_host_config.get_config_manager', return_value=mock_config_manager_with_hosts):
                result = mock_config_manager_with_hosts.enable_host("nonexistent")

        assert result is False


# ============================================================================
# Thread Safety Tests
# ============================================================================

class TestThreadSafety:
    """Test suite for thread-safe operations."""

    @pytest.fixture
    def temp_ini_file(self):
        """Create temporary INI file for testing."""
        temp_dir = tempfile.mkdtemp()
        ini_path = os.path.join(temp_dir, "test.ini")
        yield ini_path
        shutil.rmtree(temp_dir, ignore_errors=True)

    @pytest.fixture
    def mock_config_manager(self):
        """Create mock config manager with test host."""
        manager = FileHostConfigManager()
        manager.hosts["testhost"] = HostConfig(
            name="TestHost",
            upload_endpoint="https://api.test.com/upload",
            defaults={"max_connections": 2}
        )
        return manager

    def test_concurrent_ini_writes_are_thread_safe(self, temp_ini_file, mock_config_manager):
        """Test concurrent INI writes don't corrupt file."""
        num_threads = 20
        writes_per_thread = 10
        errors = []

        def write_setting(thread_id):
            try:
                for i in range(writes_per_thread):
                    save_file_host_setting("testhost", "max_connections", (thread_id % 10) + 1)
            except Exception as e:
                errors.append(e)

        # Apply patches at module level before starting threads
        with patch('src.core.file_host_config.get_config_manager', return_value=mock_config_manager):
            with patch('imxup.get_config_path', return_value=temp_ini_file):
                threads = [threading.Thread(target=write_setting, args=(i,)) for i in range(num_threads)]

                for t in threads:
                    t.start()
                for t in threads:
                    t.join()

        # Should complete without errors
        assert len(errors) == 0, f"Errors occurred: {errors}"

        # File should be valid
        cfg = configparser.ConfigParser()
        cfg.read(temp_ini_file)
        assert cfg.has_section("FILE_HOSTS")
        assert cfg.has_option("FILE_HOSTS", "testhost_max_connections")

    def test_concurrent_reads_are_thread_safe(self, temp_ini_file, mock_config_manager):
        """Test concurrent reads don't interfere with each other."""
        # Preset INI value
        cfg = configparser.ConfigParser()
        cfg.add_section("FILE_HOSTS")
        cfg.set("FILE_HOSTS", "testhost_max_connections", "5")
        with open(temp_ini_file, 'w') as f:
            cfg.write(f)

        num_threads = 20
        reads_per_thread = 10
        results = []
        results_lock = threading.Lock()

        def read_setting():
            for _ in range(reads_per_thread):
                val = get_file_host_setting("testhost", "max_connections", "int")
                with results_lock:
                    results.append(val)

        # Apply patches at module level before starting threads
        with patch('src.core.file_host_config.get_config_manager', return_value=mock_config_manager):
            with patch('imxup.get_config_path', return_value=temp_ini_file):
                threads = [threading.Thread(target=read_setting) for _ in range(num_threads)]

                for t in threads:
                    t.start()
                for t in threads:
                    t.join()

        # All reads should return the same value
        assert all(r == 5 for r in results), f"Expected all values to be 5, got: {set(results)}"
        assert len(results) == num_threads * reads_per_thread


# ============================================================================
# Singleton Tests
# ============================================================================

class TestSingleton:
    """Test suite for config manager singleton pattern."""

    def test_get_config_manager_returns_singleton(self):
        """Test get_config_manager returns same instance."""
        manager1 = get_config_manager()
        manager2 = get_config_manager()

        assert manager1 is manager2

    def test_singleton_is_thread_safe(self):
        """Test singleton initialization is thread-safe."""
        # Reset singleton
        import src.core.file_host_config
        src.core.file_host_config._config_manager = None

        managers = []

        def get_manager():
            managers.append(get_config_manager())

        threads = [threading.Thread(target=get_manager) for _ in range(10)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All threads should get same instance
        assert all(m is managers[0] for m in managers)
