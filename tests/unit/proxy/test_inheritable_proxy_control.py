"""Unit tests for InheritableProxyControl widget."""

import pytest
from unittest.mock import MagicMock, patch


class TestInheritableProxyControlConstants:
    """Tests for special value constants."""

    def test_special_value_constants(self):
        """Verify special value constants are correctly defined."""
        from src.gui.widgets.inheritable_proxy_control import InheritableProxyControl

        assert InheritableProxyControl.VALUE_DIRECT == "__direct__"
        assert InheritableProxyControl.VALUE_OS_PROXY == "__os_proxy__"

    def test_hierarchy_level_constants(self):
        """Verify hierarchy level constants are correctly defined."""
        from src.gui.widgets.inheritable_proxy_control import InheritableProxyControl

        assert InheritableProxyControl.LEVEL_GLOBAL == "global"
        assert InheritableProxyControl.LEVEL_CATEGORY == "category"
        assert InheritableProxyControl.LEVEL_SERVICE == "service"


class TestInheritableProxyControlDisplayName:
    """Tests for _get_display_name method."""

    @pytest.fixture
    def mock_control(self):
        """Create a mock control instance for testing _get_display_name."""
        with patch('src.gui.widgets.inheritable_proxy_control.QWidget.__init__', return_value=None), \
             patch('src.gui.widgets.inheritable_proxy_control.QHBoxLayout'), \
             patch('src.gui.widgets.inheritable_proxy_control.QComboBox'), \
             patch('src.gui.widgets.inheritable_proxy_control.QLabel'), \
             patch('src.gui.widgets.inheritable_proxy_control.QCheckBox'), \
             patch('src.gui.widgets.inheritable_proxy_control.ProxyStorage') as mock_storage:

            from src.gui.widgets.inheritable_proxy_control import InheritableProxyControl
            from src.proxy.models import ProxyPool

            control = InheritableProxyControl.__new__(InheritableProxyControl)

            # Create mock pools
            pool1 = ProxyPool(name="Main Pool")
            pool1.id = "pool-uuid-1"
            pool2 = ProxyPool(name="Backup Pool")
            pool2.id = "pool-uuid-2"

            control._pools = [pool1, pool2]

            yield control

    def test_display_name_none(self, mock_control):
        """Test display name for None value."""
        result = mock_control._get_display_name(None)
        assert result == "None"

    def test_display_name_direct(self, mock_control):
        """Test display name for direct connection."""
        from src.gui.widgets.inheritable_proxy_control import InheritableProxyControl
        result = mock_control._get_display_name(InheritableProxyControl.VALUE_DIRECT)
        assert result == "Direct Connection"

    def test_display_name_os_proxy(self, mock_control):
        """Test display name for OS proxy."""
        from src.gui.widgets.inheritable_proxy_control import InheritableProxyControl
        result = mock_control._get_display_name(InheritableProxyControl.VALUE_OS_PROXY)
        assert result == "OS System Proxy"

    def test_display_name_known_pool(self, mock_control):
        """Test display name for known pool ID."""
        result = mock_control._get_display_name("pool-uuid-1")
        assert result == "Main Pool"

        result = mock_control._get_display_name("pool-uuid-2")
        assert result == "Backup Pool"

    def test_display_name_unknown_pool(self, mock_control):
        """Test display name for unknown/deleted pool ID."""
        result = mock_control._get_display_name("unknown-pool-uuid")
        assert result == "(Deleted pool)"

    def test_display_name_deleted_pool(self, mock_control):
        """Test that deleted pools show appropriate message."""
        # Simulate a pool that was deleted
        result = mock_control._get_display_name("previously-valid-pool-id")
        assert result == "(Deleted pool)"


class TestInheritableProxyControlSaveAssignment:
    """Tests for _save_assignment method storing special values correctly."""

    @pytest.fixture
    def mock_storage(self):
        """Create mock storage."""
        storage = MagicMock()
        storage.list_pools.return_value = []
        storage.get_pool_assignment.return_value = None
        storage.get_global_default_pool.return_value = None
        storage.get_use_os_proxy.return_value = False
        return storage

    @pytest.fixture
    def create_control(self, mock_storage):
        """Factory to create control instances."""
        def _create(level="service", category="file_hosts", service_id="rapidgator"):
            with patch('src.gui.widgets.inheritable_proxy_control.QWidget.__init__', return_value=None), \
                 patch('src.gui.widgets.inheritable_proxy_control.QHBoxLayout'), \
                 patch('src.gui.widgets.inheritable_proxy_control.QComboBox') as mock_combo, \
                 patch('src.gui.widgets.inheritable_proxy_control.QLabel'), \
                 patch('src.gui.widgets.inheritable_proxy_control.QCheckBox'), \
                 patch('src.gui.widgets.inheritable_proxy_control.ProxyStorage', return_value=mock_storage):

                from src.gui.widgets.inheritable_proxy_control import InheritableProxyControl

                combo = MagicMock()
                mock_combo.return_value = combo

                control = InheritableProxyControl.__new__(InheritableProxyControl)
                control.storage = mock_storage
                control.level = level
                control.category = category
                control.service_id = service_id
                control._pools = []
                control._is_overriding = True
                control.combo = combo

                return control

        return _create

    def test_save_assignment_stores_direct_value(self, create_control, mock_storage):
        """Test that __direct__ is stored, not None, for direct connection."""
        from src.gui.widgets.inheritable_proxy_control import InheritableProxyControl

        control = create_control(level="service")
        control.combo.currentData.return_value = InheritableProxyControl.VALUE_DIRECT

        control._save_assignment()

        # Should store "__direct__" not None
        mock_storage.set_pool_assignment.assert_called_with(
            "__direct__", "file_hosts", "rapidgator"
        )

    def test_save_assignment_stores_os_proxy_value(self, create_control, mock_storage):
        """Test that __os_proxy__ is stored, not None, for OS proxy."""
        from src.gui.widgets.inheritable_proxy_control import InheritableProxyControl

        control = create_control(level="service")
        control.combo.currentData.return_value = InheritableProxyControl.VALUE_OS_PROXY

        control._save_assignment()

        # Should store "__os_proxy__" not None
        mock_storage.set_pool_assignment.assert_called_with(
            "__os_proxy__", "file_hosts", "rapidgator"
        )

    def test_save_assignment_stores_pool_id(self, create_control, mock_storage):
        """Test that pool ID is stored correctly."""
        control = create_control(level="service")
        control.combo.currentData.return_value = "pool-uuid-123"

        control._save_assignment()

        mock_storage.set_pool_assignment.assert_called_with(
            "pool-uuid-123", "file_hosts", "rapidgator"
        )

    def test_save_assignment_category_level(self, create_control, mock_storage):
        """Test save assignment at category level."""
        from src.gui.widgets.inheritable_proxy_control import InheritableProxyControl

        control = create_control(level="category", service_id=None)
        control.combo.currentData.return_value = InheritableProxyControl.VALUE_DIRECT

        control._save_assignment()

        # Category level: service_id should be None
        mock_storage.set_pool_assignment.assert_called_with(
            "__direct__", "file_hosts", None
        )

    def test_save_assignment_global_level_direct(self, create_control, mock_storage):
        """Test save assignment at global level for direct connection."""
        from src.gui.widgets.inheritable_proxy_control import InheritableProxyControl

        control = create_control(level="global")
        control.combo.currentData.return_value = InheritableProxyControl.VALUE_DIRECT

        control._save_assignment()

        # Global level uses different storage methods
        mock_storage.set_global_default_pool.assert_called_with(None)
        mock_storage.set_use_os_proxy.assert_called_with(False)

    def test_save_assignment_global_level_os_proxy(self, create_control, mock_storage):
        """Test save assignment at global level for OS proxy."""
        from src.gui.widgets.inheritable_proxy_control import InheritableProxyControl

        control = create_control(level="global")
        control.combo.currentData.return_value = InheritableProxyControl.VALUE_OS_PROXY

        control._save_assignment()

        mock_storage.set_global_default_pool.assert_called_with(None)
        mock_storage.set_use_os_proxy.assert_called_with(True)

    def test_save_assignment_global_level_pool(self, create_control, mock_storage):
        """Test save assignment at global level for pool."""
        control = create_control(level="global")
        control.combo.currentData.return_value = "pool-uuid-456"

        control._save_assignment()

        mock_storage.set_global_default_pool.assert_called_with("pool-uuid-456")
        mock_storage.set_use_os_proxy.assert_called_with(False)


class TestInheritableProxyControlOverrideState:
    """Tests for override state toggling."""

    @pytest.fixture
    def mock_storage(self):
        storage = MagicMock()
        storage.list_pools.return_value = []
        storage.get_pool_assignment.return_value = None
        storage.get_global_default_pool.return_value = None
        storage.get_use_os_proxy.return_value = False
        return storage

    def test_override_checkbox_state_change(self, mock_storage):
        """Test that override checkbox toggles _is_overriding correctly."""
        with patch('src.gui.widgets.inheritable_proxy_control.QWidget.__init__', return_value=None), \
             patch('src.gui.widgets.inheritable_proxy_control.QHBoxLayout'), \
             patch('src.gui.widgets.inheritable_proxy_control.QComboBox') as mock_combo, \
             patch('src.gui.widgets.inheritable_proxy_control.QLabel'), \
             patch('src.gui.widgets.inheritable_proxy_control.QCheckBox'), \
             patch('src.gui.widgets.inheritable_proxy_control.ProxyStorage', return_value=mock_storage):

            from src.gui.widgets.inheritable_proxy_control import InheritableProxyControl
            from PyQt6.QtCore import Qt

            combo = MagicMock()
            combo.currentData.return_value = "__direct__"
            mock_combo.return_value = combo

            control = InheritableProxyControl.__new__(InheritableProxyControl)
            control.storage = mock_storage
            control.level = "service"
            control.category = "file_hosts"
            control.service_id = "rapidgator"
            control._pools = []
            control._is_overriding = False
            control._parent_value = "__direct__"
            control._parent_source = "Global"
            control.combo = combo
            control.override_checkbox = MagicMock()
            control.inherited_label = MagicMock()
            control.status_icon = MagicMock()
            control.value_changed = MagicMock()

            # Simulate checking the override checkbox
            control._on_override_changed(Qt.CheckState.Checked.value)

            assert control._is_overriding is True
            mock_storage.set_pool_assignment.assert_called()

    def test_unchecking_override_clears_assignment(self, mock_storage):
        """Test that unchecking override calls _clear_assignment."""
        with patch('src.gui.widgets.inheritable_proxy_control.QWidget.__init__', return_value=None), \
             patch('src.gui.widgets.inheritable_proxy_control.QHBoxLayout'), \
             patch('src.gui.widgets.inheritable_proxy_control.QComboBox') as mock_combo, \
             patch('src.gui.widgets.inheritable_proxy_control.QLabel'), \
             patch('src.gui.widgets.inheritable_proxy_control.QCheckBox'), \
             patch('src.gui.widgets.inheritable_proxy_control.ProxyStorage', return_value=mock_storage):

            from src.gui.widgets.inheritable_proxy_control import InheritableProxyControl
            from PyQt6.QtCore import Qt

            combo = MagicMock()
            mock_combo.return_value = combo

            control = InheritableProxyControl.__new__(InheritableProxyControl)
            control.storage = mock_storage
            control.level = "service"
            control.category = "file_hosts"
            control.service_id = "rapidgator"
            control._pools = []
            control._is_overriding = True
            control._parent_value = "__direct__"
            control._parent_source = "Global"
            control.combo = combo
            control.override_checkbox = MagicMock()
            control.inherited_label = MagicMock()
            control.status_icon = MagicMock()
            control.value_changed = MagicMock()

            # Simulate unchecking the override checkbox
            control._on_override_changed(Qt.CheckState.Unchecked.value)

            assert control._is_overriding is False
            # Should clear the assignment (set to None)
            mock_storage.set_pool_assignment.assert_called_with(
                None, "file_hosts", "rapidgator"
            )


class TestInheritableProxyControlHierarchy:
    """Tests for hierarchy level behavior."""

    def test_global_level_always_overrides(self):
        """Test that global level is always in override mode."""
        with patch('src.gui.widgets.inheritable_proxy_control.QWidget.__init__', return_value=None), \
             patch('src.gui.widgets.inheritable_proxy_control.QHBoxLayout'), \
             patch('src.gui.widgets.inheritable_proxy_control.QComboBox') as mock_combo, \
             patch('src.gui.widgets.inheritable_proxy_control.QLabel'), \
             patch('src.gui.widgets.inheritable_proxy_control.QCheckBox'), \
             patch('src.gui.widgets.inheritable_proxy_control.ProxyStorage') as mock_storage:

            mock_storage.return_value.list_pools.return_value = []
            mock_storage.return_value.get_global_default_pool.return_value = None
            mock_storage.return_value.get_use_os_proxy.return_value = False

            combo = MagicMock()
            combo.count.return_value = 0
            mock_combo.return_value = combo

            from src.gui.widgets.inheritable_proxy_control import InheritableProxyControl

            control = InheritableProxyControl.__new__(InheritableProxyControl)
            control.storage = mock_storage.return_value
            control.level = InheritableProxyControl.LEVEL_GLOBAL
            control.category = None
            control.service_id = None
            control._pools = []
            control._parent_value = None  # Global has no parent value
            control.combo = combo
            control.override_checkbox = None  # Global has no checkbox

            # Load current value sets _is_overriding
            control._load_current_value()

            # Global level should always be overriding
            assert control._is_overriding is True

    def test_no_override_checkbox_for_global(self):
        """Test that global level does not have an override checkbox."""
        with patch('src.gui.widgets.inheritable_proxy_control.QWidget.__init__', return_value=None), \
             patch('src.gui.widgets.inheritable_proxy_control.QHBoxLayout'), \
             patch('src.gui.widgets.inheritable_proxy_control.QComboBox') as mock_combo, \
             patch('src.gui.widgets.inheritable_proxy_control.QLabel'), \
             patch('src.gui.widgets.inheritable_proxy_control.QCheckBox') as mock_checkbox, \
             patch('src.gui.widgets.inheritable_proxy_control.ProxyStorage') as mock_storage:

            mock_storage.return_value.list_pools.return_value = []
            mock_storage.return_value.get_global_default_pool.return_value = None
            mock_storage.return_value.get_use_os_proxy.return_value = False

            combo = MagicMock()
            combo.count.return_value = 0
            mock_combo.return_value = combo

            from src.gui.widgets.inheritable_proxy_control import InheritableProxyControl

            control = InheritableProxyControl.__new__(InheritableProxyControl)
            control.level = InheritableProxyControl.LEVEL_GLOBAL
            control.override_checkbox = None

            control._setup_ui(show_label=True, label_text="Proxy:", compact=False)

            # Global level should not have checkbox created
            assert control.override_checkbox is None


class TestInheritableProxyControlEffectiveValue:
    """Tests for get_effective_value method."""

    def test_effective_value_when_overriding(self):
        """Test effective value returns combo value when overriding."""
        with patch('src.gui.widgets.inheritable_proxy_control.QWidget.__init__', return_value=None), \
             patch('src.gui.widgets.inheritable_proxy_control.QHBoxLayout'), \
             patch('src.gui.widgets.inheritable_proxy_control.QComboBox'), \
             patch('src.gui.widgets.inheritable_proxy_control.QLabel'), \
             patch('src.gui.widgets.inheritable_proxy_control.QCheckBox'), \
             patch('src.gui.widgets.inheritable_proxy_control.ProxyStorage'):

            from src.gui.widgets.inheritable_proxy_control import InheritableProxyControl

            control = InheritableProxyControl.__new__(InheritableProxyControl)
            control._is_overriding = True
            control._parent_value = "__direct__"
            control.level = "service"
            control.combo = MagicMock()
            control.combo.currentData.return_value = "pool-uuid-123"

            result = control.get_effective_value()
            assert result == "pool-uuid-123"

    def test_effective_value_when_inheriting(self):
        """Test effective value returns parent value when not overriding."""
        with patch('src.gui.widgets.inheritable_proxy_control.QWidget.__init__', return_value=None), \
             patch('src.gui.widgets.inheritable_proxy_control.QHBoxLayout'), \
             patch('src.gui.widgets.inheritable_proxy_control.QComboBox'), \
             patch('src.gui.widgets.inheritable_proxy_control.QLabel'), \
             patch('src.gui.widgets.inheritable_proxy_control.QCheckBox'), \
             patch('src.gui.widgets.inheritable_proxy_control.ProxyStorage'):

            from src.gui.widgets.inheritable_proxy_control import InheritableProxyControl

            control = InheritableProxyControl.__new__(InheritableProxyControl)
            control._is_overriding = False
            control._parent_value = "__os_proxy__"
            control.level = "service"
            control.combo = MagicMock()
            control.combo.currentData.return_value = "pool-uuid-123"

            result = control.get_effective_value()
            assert result == "__os_proxy__"

    def test_effective_value_global_always_returns_combo(self):
        """Test global level always returns combo value."""
        with patch('src.gui.widgets.inheritable_proxy_control.QWidget.__init__', return_value=None), \
             patch('src.gui.widgets.inheritable_proxy_control.QHBoxLayout'), \
             patch('src.gui.widgets.inheritable_proxy_control.QComboBox'), \
             patch('src.gui.widgets.inheritable_proxy_control.QLabel'), \
             patch('src.gui.widgets.inheritable_proxy_control.QCheckBox'), \
             patch('src.gui.widgets.inheritable_proxy_control.ProxyStorage'):

            from src.gui.widgets.inheritable_proxy_control import InheritableProxyControl

            control = InheritableProxyControl.__new__(InheritableProxyControl)
            control._is_overriding = False  # Even if somehow set to False
            control._parent_value = "__direct__"
            control.level = InheritableProxyControl.LEVEL_GLOBAL
            control.combo = MagicMock()
            control.combo.currentData.return_value = "__os_proxy__"

            result = control.get_effective_value()
            # Global always returns combo value
            assert result == "__os_proxy__"
