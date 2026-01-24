"""Unit tests for ProxySelector widget - verifying argument order bug fix."""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock


class TestProxySelectorArgumentOrder:
    """Tests verifying correct argument order for storage method calls.

    Bug fix verification:
    - get_pool_assignment(category, service_id)
    - set_pool_assignment(pool_id, category, service_id)
    """

    @pytest.fixture
    def mock_storage(self):
        """Create a mock ProxyStorage with tracking for call arguments."""
        storage = MagicMock()
        storage.list_profiles.return_value = []
        storage.list_pools.return_value = []
        storage.get_pool_assignment.return_value = None
        storage.get_assignment.return_value = None
        return storage

    @pytest.fixture
    def mock_qwidget(self):
        """Mock Qt widgets to avoid GUI initialization."""
        with patch('src.gui.widgets.proxy_selector.QWidget.__init__', return_value=None), \
             patch('src.gui.widgets.proxy_selector.QHBoxLayout'), \
             patch('src.gui.widgets.proxy_selector.QComboBox') as mock_combo, \
             patch('src.gui.widgets.proxy_selector.QLabel'), \
             patch('src.gui.widgets.proxy_selector.QToolButton'):

            # Configure combo mock
            combo_instance = MagicMock()
            combo_instance.count.return_value = 0
            mock_combo.return_value = combo_instance
            yield

    def test_get_pool_assignment_argument_order(self, mock_storage, mock_qwidget):
        """Test that get_pool_assignment is called with (category, service_id)."""
        with patch('src.gui.widgets.proxy_selector.ProxyStorage', return_value=mock_storage):
            from src.gui.widgets.proxy_selector import ProxySelector

            # Create selector with category and service_id
            selector = ProxySelector.__new__(ProxySelector)
            selector.storage = mock_storage
            selector.category = "file_hosts"
            selector.service_id = "rapidgator"
            selector.allow_inherit = True
            selector._profiles = []
            selector._pools = []

            # Mock combo to avoid Qt initialization issues
            selector.combo = MagicMock()
            selector.combo.count.return_value = 2

            # Call the method that loads service selection
            selector._load_service_selection()

            # Verify get_pool_assignment was called with correct order: (category, service_id)
            mock_storage.get_pool_assignment.assert_called_with("file_hosts", "rapidgator")

    def test_set_pool_assignment_on_inherit_selection(self, mock_storage, mock_qwidget):
        """Test that set_pool_assignment uses (pool_id, category, service_id) order for inherit."""
        with patch('src.gui.widgets.proxy_selector.ProxyStorage', return_value=mock_storage):
            from src.gui.widgets.proxy_selector import ProxySelector

            selector = ProxySelector.__new__(ProxySelector)
            selector.storage = mock_storage
            selector.category = "file_hosts"
            selector.service_id = "rapidgator"
            selector.allow_inherit = True
            selector._profiles = []
            selector._pools = []

            # Mock combo box
            selector.combo = MagicMock()
            selector.combo.currentData.return_value = (ProxySelector.TYPE_INHERIT, None)

            # Create and connect signal
            selector.selection_changed = MagicMock()

            # Trigger selection change
            selector._on_selection_changed()

            # For inherit, both should be cleared with None
            # set_pool_assignment(None, category, service_id)
            mock_storage.set_pool_assignment.assert_called_with(None, "file_hosts", "rapidgator")
            mock_storage.set_assignment.assert_called_with(None, "file_hosts", "rapidgator")

    def test_set_pool_assignment_on_direct_selection(self, mock_storage, mock_qwidget):
        """Test that set_pool_assignment uses correct order for direct connection."""
        with patch('src.gui.widgets.proxy_selector.ProxyStorage', return_value=mock_storage):
            from src.gui.widgets.proxy_selector import ProxySelector

            selector = ProxySelector.__new__(ProxySelector)
            selector.storage = mock_storage
            selector.category = "file_hosts"
            selector.service_id = "rapidgator"
            selector.allow_inherit = True
            selector._profiles = []
            selector._pools = []

            selector.combo = MagicMock()
            selector.combo.currentData.return_value = (ProxySelector.TYPE_DIRECT, None)
            selector.selection_changed = MagicMock()

            selector._on_selection_changed()

            # For direct: set_assignment(__direct__), clear pool
            mock_storage.set_assignment.assert_called_with("__direct__", "file_hosts", "rapidgator")
            mock_storage.set_pool_assignment.assert_called_with(None, "file_hosts", "rapidgator")

    def test_set_pool_assignment_on_pool_selection(self, mock_storage, mock_qwidget):
        """Test that set_pool_assignment uses (pool_id, category, service_id) order."""
        with patch('src.gui.widgets.proxy_selector.ProxyStorage', return_value=mock_storage):
            from src.gui.widgets.proxy_selector import ProxySelector

            selector = ProxySelector.__new__(ProxySelector)
            selector.storage = mock_storage
            selector.category = "file_hosts"
            selector.service_id = "rapidgator"
            selector.allow_inherit = True
            selector._profiles = []
            selector._pools = []

            selector.combo = MagicMock()
            pool_id = "test-pool-uuid"
            selector.combo.currentData.return_value = (ProxySelector.TYPE_POOL, pool_id)
            selector.selection_changed = MagicMock()

            selector._on_selection_changed()

            # For pool: set_pool_assignment(pool_id, category, service_id)
            mock_storage.set_pool_assignment.assert_called_with(pool_id, "file_hosts", "rapidgator")
            # Profile assignment should be cleared
            mock_storage.set_assignment.assert_called_with(None, "file_hosts", "rapidgator")

    def test_set_assignment_on_profile_selection(self, mock_storage, mock_qwidget):
        """Test that set_assignment uses (profile_id, category, service_id) order."""
        with patch('src.gui.widgets.proxy_selector.ProxyStorage', return_value=mock_storage):
            from src.gui.widgets.proxy_selector import ProxySelector

            selector = ProxySelector.__new__(ProxySelector)
            selector.storage = mock_storage
            selector.category = "file_hosts"
            selector.service_id = "rapidgator"
            selector.allow_inherit = True
            selector._profiles = []
            selector._pools = []

            selector.combo = MagicMock()
            profile_id = "test-profile-uuid"
            selector.combo.currentData.return_value = (ProxySelector.TYPE_PROFILE, profile_id)
            selector.selection_changed = MagicMock()

            selector._on_selection_changed()

            # For profile: set_assignment(profile_id, category, service_id)
            mock_storage.set_assignment.assert_called_with(profile_id, "file_hosts", "rapidgator")
            # Pool assignment should be cleared
            mock_storage.set_pool_assignment.assert_called_with(None, "file_hosts", "rapidgator")


class TestProxySelectorSelectionTypes:
    """Tests for selection type handling."""

    def test_type_constants_defined(self):
        """Verify selection type constants are correctly defined."""
        from src.gui.widgets.proxy_selector import ProxySelector

        assert ProxySelector.TYPE_INHERIT == "inherit"
        assert ProxySelector.TYPE_DIRECT == "direct"
        assert ProxySelector.TYPE_PROFILE == "profile"
        assert ProxySelector.TYPE_POOL == "pool"

    def test_get_selection_returns_tuple(self):
        """Test get_selection returns (profile_id, pool_id, use_inherit) tuple."""
        with patch('src.gui.widgets.proxy_selector.QWidget.__init__', return_value=None), \
             patch('src.gui.widgets.proxy_selector.QHBoxLayout'), \
             patch('src.gui.widgets.proxy_selector.QComboBox') as mock_combo, \
             patch('src.gui.widgets.proxy_selector.QLabel'), \
             patch('src.gui.widgets.proxy_selector.ProxyStorage') as mock_storage:

            mock_storage.return_value.list_profiles.return_value = []
            mock_storage.return_value.list_pools.return_value = []

            combo = MagicMock()
            combo.count.return_value = 0
            mock_combo.return_value = combo

            from src.gui.widgets.proxy_selector import ProxySelector

            selector = ProxySelector.__new__(ProxySelector)
            selector.storage = mock_storage.return_value
            selector.combo = combo

            # Test inherit
            combo.currentData.return_value = (ProxySelector.TYPE_INHERIT, None)
            result = selector.get_selection()
            assert result == (None, None, True)

            # Test direct
            combo.currentData.return_value = (ProxySelector.TYPE_DIRECT, None)
            result = selector.get_selection()
            assert result == (None, None, False)

            # Test profile
            combo.currentData.return_value = (ProxySelector.TYPE_PROFILE, "profile-123")
            result = selector.get_selection()
            assert result == ("profile-123", None, False)

            # Test pool
            combo.currentData.return_value = (ProxySelector.TYPE_POOL, "pool-456")
            result = selector.get_selection()
            assert result == (None, "pool-456", False)
