#!/usr/bin/env python3
"""
Unit tests for delegate classes in src/gui/delegates/.

Tests cover:
- ActionButtonDelegate: Action button rendering and click handling
- FileHostsStatusDelegate: File host status icon rendering and click handling

Test patterns:
- Mock icon_manager to avoid filesystem access
- Mock queue_manager/config_manager for data access
- Use pytest-qt for signal testing
- Use monkeypatch for dependency injection
"""

import os
import sys

# Ensure Qt uses offscreen platform for headless testing
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from unittest.mock import Mock, MagicMock, patch
from typing import Dict, List, Tuple

from PyQt6.QtCore import Qt, QRect, QSize, QModelIndex, QPoint, QEvent
from PyQt6.QtGui import QIcon, QPixmap, QPainter
from PyQt6.QtWidgets import QStyleOptionViewItem, QApplication, QStyledItemDelegate


# Ensure QApplication exists for tests that need it
@pytest.fixture(scope="module")
def qapp():
    """Ensure a QApplication exists for the module."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


# =============================================================================
# ActionButtonDelegate Tests
# =============================================================================

class TestActionButtonDelegateButtonConfig:
    """Test suite for ActionButtonDelegate._get_button_config()."""

    @pytest.fixture
    def delegate(self, qapp):
        """Create ActionButtonDelegate with mocked icon_manager."""
        with patch('src.gui.delegates.action_button_delegate.get_icon_manager') as mock_get_icon:
            mock_icon_manager = Mock()
            mock_icon = Mock(spec=QIcon)
            mock_icon.isNull.return_value = False
            mock_icon.pixmap.return_value = Mock(spec=QPixmap)
            mock_icon_manager.get_icon.return_value = mock_icon
            mock_get_icon.return_value = mock_icon_manager

            from src.gui.delegates.action_button_delegate import ActionButtonDelegate
            return ActionButtonDelegate()

    # =========================================================================
    # _get_button_config() Tests
    # =========================================================================

    def test_get_button_config_ready_status(self, delegate):
        """Verify 'ready' status returns start button config."""
        icon_key, action, tooltip = delegate._get_button_config("ready")

        assert icon_key == "action_start"
        assert action == "start"
        assert tooltip == "Start upload"

    def test_get_button_config_queued_status(self, delegate):
        """Verify 'queued' status returns cancel button config."""
        icon_key, action, tooltip = delegate._get_button_config("queued")

        assert icon_key == "action_cancel"
        assert action == "cancel"
        assert tooltip == "Cancel from queue"

    def test_get_button_config_uploading_status(self, delegate):
        """Verify 'uploading' status returns stop button config."""
        icon_key, action, tooltip = delegate._get_button_config("uploading")

        assert icon_key == "action_stop"
        assert action == "stop"
        assert tooltip == "Stop upload"

    def test_get_button_config_paused_status(self, delegate):
        """Verify 'paused' status returns resume button config."""
        icon_key, action, tooltip = delegate._get_button_config("paused")

        assert icon_key == "action_resume"
        assert action == "start"
        assert tooltip == "Resume upload"

    def test_get_button_config_incomplete_status(self, delegate):
        """Verify 'incomplete' status returns resume button config."""
        icon_key, action, tooltip = delegate._get_button_config("incomplete")

        assert icon_key == "action_resume"
        assert action == "start"
        assert tooltip == "Resume upload"

    def test_get_button_config_completed_status(self, delegate):
        """Verify 'completed' status returns view button config."""
        icon_key, action, tooltip = delegate._get_button_config("completed")

        assert icon_key == "action_view"
        assert action == "view"
        assert tooltip == "View BBCode"

    def test_get_button_config_failed_status(self, delegate):
        """Verify 'failed' status returns view error button config."""
        icon_key, action, tooltip = delegate._get_button_config("failed")

        assert icon_key == "action_view_error"
        assert action == "view_error"
        assert tooltip == "View error details"

    def test_get_button_config_unknown_status(self, delegate):
        """Verify unknown status returns empty tuple."""
        icon_key, action, tooltip = delegate._get_button_config("unknown_status")

        assert icon_key == ""
        assert action == ""
        assert tooltip == ""

    def test_get_button_config_empty_status(self, delegate):
        """Verify empty status returns empty tuple."""
        icon_key, action, tooltip = delegate._get_button_config("")

        assert icon_key == ""
        assert action == ""
        assert tooltip == ""

    @pytest.mark.parametrize("status,expected_icon,expected_action", [
        ("ready", "action_start", "start"),
        ("queued", "action_cancel", "cancel"),
        ("uploading", "action_stop", "stop"),
        ("paused", "action_resume", "start"),
        ("incomplete", "action_resume", "start"),
        ("completed", "action_view", "view"),
        ("failed", "action_view_error", "view_error"),
    ])
    def test_get_button_config_all_statuses(self, delegate, status, expected_icon, expected_action):
        """Parametrized test for all valid statuses."""
        icon_key, action, tooltip = delegate._get_button_config(status)

        assert icon_key == expected_icon
        assert action == expected_action
        assert tooltip != ""  # All valid statuses have tooltips


class TestActionButtonDelegateSizeHint:
    """Test suite for ActionButtonDelegate.sizeHint()."""

    @pytest.fixture
    def delegate(self, qapp):
        """Create ActionButtonDelegate."""
        with patch('src.gui.delegates.action_button_delegate.get_icon_manager'):
            from src.gui.delegates.action_button_delegate import ActionButtonDelegate
            return ActionButtonDelegate()

    def test_size_hint_returns_qsize(self, delegate):
        """Verify sizeHint returns a QSize object."""
        option = Mock(spec=QStyleOptionViewItem)
        index = Mock(spec=QModelIndex)

        result = delegate.sizeHint(option, index)

        assert isinstance(result, QSize)

    def test_size_hint_width_includes_padding(self, delegate):
        """Verify sizeHint width includes button size and padding."""
        option = Mock(spec=QStyleOptionViewItem)
        index = Mock(spec=QModelIndex)

        result = delegate.sizeHint(option, index)

        expected_width = delegate.BUTTON_SIZE + delegate.PADDING * 2
        assert result.width() == expected_width

    def test_size_hint_height_includes_margin(self, delegate):
        """Verify sizeHint height includes button size and margin."""
        option = Mock(spec=QStyleOptionViewItem)
        index = Mock(spec=QModelIndex)

        result = delegate.sizeHint(option, index)

        expected_height = delegate.BUTTON_SIZE + 4
        assert result.height() == expected_height

    def test_size_hint_default_values(self, delegate):
        """Verify sizeHint uses correct default constants."""
        option = Mock(spec=QStyleOptionViewItem)
        index = Mock(spec=QModelIndex)

        result = delegate.sizeHint(option, index)

        # BUTTON_SIZE=22, PADDING=4
        assert result.width() == 30  # 22 + 4*2
        assert result.height() == 26  # 22 + 4


class TestActionButtonDelegateSignals:
    """Test suite for ActionButtonDelegate signal emission."""

    @pytest.fixture
    def delegate_with_mocks(self, qapp):
        """Create ActionButtonDelegate with all necessary mocks."""
        with patch('src.gui.delegates.action_button_delegate.get_icon_manager') as mock_get_icon:
            mock_icon_manager = Mock()
            mock_icon = Mock(spec=QIcon)
            mock_icon.isNull.return_value = False
            mock_icon.pixmap.return_value = Mock(spec=QPixmap)
            mock_icon_manager.get_icon.return_value = mock_icon
            mock_get_icon.return_value = mock_icon_manager

            from src.gui.delegates.action_button_delegate import ActionButtonDelegate

            delegate = ActionButtonDelegate()

            # Setup queue manager mock
            mock_queue_manager = Mock()
            mock_item = Mock()
            mock_item.status = "ready"
            mock_queue_manager.get_item.return_value = mock_item
            delegate.set_queue_manager(mock_queue_manager)

            yield delegate, mock_icon_manager, mock_queue_manager

    def test_button_clicked_signal_exists(self, delegate_with_mocks):
        """Verify button_clicked signal is accessible."""
        delegate, _, _ = delegate_with_mocks

        # Signal should be accessible via property
        assert delegate.button_clicked is not None
        assert hasattr(delegate.button_clicked, 'emit')

    def test_button_clicked_signal_emits_on_click(self, delegate_with_mocks, qtbot):
        """Verify button_clicked signal emits with correct arguments."""
        delegate, _, mock_queue_manager = delegate_with_mocks

        # Mock index
        mock_index = Mock(spec=QModelIndex)
        mock_index.row.return_value = 0
        mock_index.data.return_value = "/test/gallery/path"

        # Mock event with real QEvent.Type
        mock_event = Mock()
        mock_event.type.return_value = QEvent.Type.MouseButtonRelease
        mock_position = Mock()
        mock_position.toPoint.return_value = QPoint(10, 10)  # Inside button rect
        mock_event.position.return_value = mock_position

        # Mock model and option with rect that produces button at (4, 4)
        mock_model = Mock()
        mock_option = Mock(spec=QStyleOptionViewItem)
        mock_option.rect = QRect(0, 0, 100, 30)  # Cell rect

        # Connect signal to capture emission
        received_args = []

        def on_clicked(path, action):
            received_args.append((path, action))

        delegate.button_clicked.connect(on_clicked)

        # Trigger editor event
        result = delegate.editorEvent(mock_event, mock_model, mock_option, mock_index)

        assert result is True
        assert len(received_args) == 1
        assert received_args[0] == ("/test/gallery/path", "start")

    def test_button_clicked_not_emitted_outside_rect(self, delegate_with_mocks):
        """Verify button_clicked is not emitted when clicking outside button rect."""
        delegate, _, _ = delegate_with_mocks

        # Mock index
        mock_index = Mock(spec=QModelIndex)
        mock_index.row.return_value = 0
        mock_index.data.return_value = "/test/gallery/path"

        # Mock event with position outside button rect
        mock_event = Mock()
        mock_event.type.return_value = QEvent.Type.MouseButtonRelease
        mock_position = Mock()
        mock_position.toPoint.return_value = QPoint(100, 100)  # Outside button rect
        mock_event.position.return_value = mock_position

        # Mock option with rect that produces button at (4, 4)
        mock_option = Mock(spec=QStyleOptionViewItem)
        mock_option.rect = QRect(0, 0, 50, 30)  # Cell rect

        # Connect signal
        received_args = []
        delegate.button_clicked.connect(lambda p, a: received_args.append((p, a)))

        # Mock the parent class's editorEvent to avoid TypeError with Mock arguments
        with patch.object(QStyledItemDelegate, 'editorEvent', return_value=False):
            # Trigger editor event
            result = delegate.editorEvent(mock_event, Mock(), mock_option, mock_index)

        assert result is False
        assert len(received_args) == 0

    def test_button_clicked_not_emitted_for_non_release_events(self, delegate_with_mocks):
        """Verify button_clicked is not emitted for non-release events."""
        delegate, _, _ = delegate_with_mocks

        mock_index = Mock(spec=QModelIndex)
        mock_index.row.return_value = 0
        mock_index.data.return_value = "/test/gallery/path"

        # Mock non-release event (Press, not Release)
        mock_event = Mock()
        mock_event.type.return_value = QEvent.Type.MouseButtonPress

        mock_option = Mock(spec=QStyleOptionViewItem)
        mock_option.rect = QRect(0, 0, 100, 30)

        received_args = []
        delegate.button_clicked.connect(lambda p, a: received_args.append((p, a)))

        # Mock the parent class's editorEvent to avoid TypeError with Mock arguments
        with patch.object(QStyledItemDelegate, 'editorEvent', return_value=False):
            delegate.editorEvent(mock_event, Mock(), mock_option, mock_index)

        assert len(received_args) == 0


class TestActionButtonDelegatePaint:
    """Test suite for ActionButtonDelegate.paint()."""

    @pytest.fixture
    def delegate_with_mocks(self, qapp):
        """Create ActionButtonDelegate with all necessary mocks for paint testing."""
        with patch('src.gui.delegates.action_button_delegate.get_icon_manager') as mock_get_icon:
            mock_icon_manager = Mock()
            mock_icon = Mock(spec=QIcon)
            mock_icon.isNull.return_value = False
            mock_pixmap = Mock(spec=QPixmap)
            mock_icon.pixmap.return_value = mock_pixmap
            mock_icon_manager.get_icon.return_value = mock_icon
            mock_get_icon.return_value = mock_icon_manager

            from src.gui.delegates.action_button_delegate import ActionButtonDelegate

            delegate = ActionButtonDelegate()

            # Setup queue manager
            mock_queue_manager = Mock()
            mock_item = Mock()
            mock_item.status = "ready"
            mock_queue_manager.get_item.return_value = mock_item
            delegate.set_queue_manager(mock_queue_manager)

            yield delegate, mock_icon_manager, mock_get_icon

    def test_paint_requests_correct_icon(self, delegate_with_mocks):
        """Verify paint requests the correct icon based on status."""
        delegate, mock_icon_manager, _ = delegate_with_mocks

        # Mock painter
        mock_painter = Mock(spec=QPainter)

        # Mock option with rect
        mock_option = Mock(spec=QStyleOptionViewItem)
        mock_option.rect = QRect(0, 0, 100, 30)

        # Mock index
        mock_index = Mock(spec=QModelIndex)
        mock_index.row.return_value = 0
        mock_index.data.return_value = "/test/path"

        delegate.paint(mock_painter, mock_option, mock_index)

        mock_icon_manager.get_icon.assert_called_with("action_start")

    def test_paint_computes_button_rect(self, delegate_with_mocks):
        """Verify _compute_button_rect returns correct rectangle."""
        delegate, _, _ = delegate_with_mocks

        cell_rect = QRect(10, 20, 100, 30)
        button_rect = delegate._compute_button_rect(cell_rect)

        # Button should be at PADDING from left edge, centered vertically
        assert button_rect.x() == 10 + delegate.PADDING
        assert button_rect.width() == delegate.BUTTON_SIZE
        assert button_rect.height() == delegate.BUTTON_SIZE

    def test_paint_does_nothing_without_path(self, delegate_with_mocks):
        """Verify paint returns early if no path in index."""
        delegate, mock_icon_manager, _ = delegate_with_mocks

        mock_painter = Mock(spec=QPainter)
        mock_option = Mock(spec=QStyleOptionViewItem)
        mock_index = Mock(spec=QModelIndex)
        mock_index.data.return_value = None  # No path

        delegate.paint(mock_painter, mock_option, mock_index)

        mock_icon_manager.get_icon.assert_not_called()

    def test_get_button_config_unknown_status_returns_empty(self, delegate_with_mocks):
        """Verify _get_button_config returns empty tuple for unknown status."""
        delegate, _, _ = delegate_with_mocks

        icon_key, action, tooltip = delegate._get_button_config("scanning")

        assert icon_key == ""
        assert action == ""
        assert tooltip == ""


class TestActionButtonDelegateQueueManager:
    """Test suite for ActionButtonDelegate queue manager integration."""

    @pytest.fixture
    def delegate(self, qapp):
        """Create ActionButtonDelegate."""
        with patch('src.gui.delegates.action_button_delegate.get_icon_manager'):
            from src.gui.delegates.action_button_delegate import ActionButtonDelegate
            return ActionButtonDelegate()

    def test_set_queue_manager(self, delegate):
        """Verify set_queue_manager stores the manager."""
        mock_queue_manager = Mock()
        delegate.set_queue_manager(mock_queue_manager)

        assert delegate._queue_manager is mock_queue_manager

    def test_get_status_for_path_with_queue_manager(self, delegate):
        """Verify _get_status_for_path uses queue manager."""
        mock_queue_manager = Mock()
        mock_item = Mock()
        mock_item.status = "uploading"
        mock_queue_manager.get_item.return_value = mock_item
        delegate.set_queue_manager(mock_queue_manager)

        status = delegate._get_status_for_path("/test/path")

        assert status == "uploading"
        mock_queue_manager.get_item.assert_called_with("/test/path")

    def test_get_status_for_path_without_queue_manager(self, delegate):
        """Verify _get_status_for_path returns 'ready' without queue manager."""
        status = delegate._get_status_for_path("/test/path")

        assert status == "ready"

    def test_get_status_for_path_item_not_found(self, delegate):
        """Verify _get_status_for_path returns 'ready' when item not found."""
        mock_queue_manager = Mock()
        mock_queue_manager.get_item.return_value = None
        delegate.set_queue_manager(mock_queue_manager)

        status = delegate._get_status_for_path("/nonexistent/path")

        assert status == "ready"

    def test_get_status_for_path_empty_path(self, delegate):
        """Verify _get_status_for_path returns 'ready' for empty path."""
        mock_queue_manager = Mock()
        delegate.set_queue_manager(mock_queue_manager)

        status = delegate._get_status_for_path("")

        assert status == "ready"
        mock_queue_manager.get_item.assert_not_called()


# =============================================================================
# FileHostsStatusDelegate Tests
# =============================================================================

class TestFileHostsStatusDelegateStatusColor:
    """Test suite for FileHostsStatusDelegate status handling."""

    @pytest.fixture
    def delegate(self, qapp, monkeypatch):
        """Create FileHostsStatusDelegate with mocked dependencies."""
        with patch('src.gui.delegates.file_hosts_status_delegate.get_icon_manager') as mock_get_icon:
            mock_icon_manager = Mock()
            mock_icon = Mock(spec=QIcon)
            mock_icon.isNull.return_value = False
            mock_icon.pixmap.return_value = Mock(spec=QPixmap)
            mock_icon_manager.get_file_host_icon.return_value = mock_icon
            mock_get_icon.return_value = mock_icon_manager

            from src.gui.delegates.file_hosts_status_delegate import FileHostsStatusDelegate
            delegate = FileHostsStatusDelegate()

            # Mock config manager
            mock_config_manager = Mock()
            mock_config_manager.get_enabled_hosts.return_value = {
                "rapidgator": {"enabled": True},
                "fileboom": {"enabled": True},
            }
            delegate._config_manager = mock_config_manager

            yield delegate, mock_icon_manager

    def test_overlay_pixmap_uploading_status(self, delegate):
        """Verify uploading status creates blue overlay."""
        delegate_obj, _ = delegate

        pixmap = delegate_obj._get_overlay_pixmap("uploading")

        assert not pixmap.isNull()
        assert pixmap.width() == delegate_obj.ICON_SIZE
        assert pixmap.height() == delegate_obj.ICON_SIZE

    def test_overlay_pixmap_pending_status(self, delegate):
        """Verify pending status creates gray overlay."""
        delegate_obj, _ = delegate

        pixmap = delegate_obj._get_overlay_pixmap("pending")

        assert not pixmap.isNull()
        assert pixmap.width() == delegate_obj.ICON_SIZE

    def test_overlay_pixmap_failed_status(self, delegate):
        """Verify failed status creates X overlay."""
        delegate_obj, _ = delegate

        pixmap = delegate_obj._get_overlay_pixmap("failed")

        assert not pixmap.isNull()
        assert pixmap.width() == delegate_obj.ICON_SIZE

    def test_overlay_pixmap_completed_status(self, delegate):
        """Verify completed status returns transparent overlay."""
        delegate_obj, _ = delegate

        pixmap = delegate_obj._get_overlay_pixmap("completed")

        # Completed status doesn't apply overlay during paint, but _get_overlay_pixmap
        # will return a transparent pixmap
        assert not pixmap.isNull()

    def test_overlay_pixmap_caching(self, delegate):
        """Verify overlay pixmaps are cached."""
        delegate_obj, _ = delegate

        # First call creates pixmap
        pixmap1 = delegate_obj._get_overlay_pixmap("uploading")

        # Second call should return cached pixmap
        pixmap2 = delegate_obj._get_overlay_pixmap("uploading")

        # Both should be the same object (cached)
        assert pixmap1 is pixmap2
        assert "uploading" in delegate_obj._overlay_cache


class TestFileHostsStatusDelegateSizeHint:
    """Test suite for FileHostsStatusDelegate.sizeHint()."""

    @pytest.fixture
    def delegate(self, qapp):
        """Create FileHostsStatusDelegate with mocked config manager."""
        with patch('src.gui.delegates.file_hosts_status_delegate.get_icon_manager'):
            from src.gui.delegates.file_hosts_status_delegate import FileHostsStatusDelegate
            delegate = FileHostsStatusDelegate()

            # Mock config manager with enabled hosts
            mock_config_manager = Mock()
            mock_config_manager.get_enabled_hosts.return_value = {
                "rapidgator": {"enabled": True},
                "fileboom": {"enabled": True},
                "keep2share": {"enabled": True},
            }
            delegate._config_manager = mock_config_manager

            yield delegate

    def test_size_hint_returns_qsize(self, delegate):
        """Verify sizeHint returns a QSize object."""
        option = Mock(spec=QStyleOptionViewItem)
        index = Mock(spec=QModelIndex)

        result = delegate.sizeHint(option, index)

        assert isinstance(result, QSize)

    def test_size_hint_width_based_on_host_count(self, delegate):
        """Verify sizeHint width accounts for number of enabled hosts."""
        option = Mock(spec=QStyleOptionViewItem)
        index = Mock(spec=QModelIndex)

        result = delegate.sizeHint(option, index)

        # 3 hosts * (22 + 2) + 4*2 = 3 * 24 + 8 = 80
        num_hosts = 3
        expected_width = delegate.PADDING * 2 + num_hosts * (delegate.ICON_SIZE + delegate.ICON_SPACING)
        assert result.width() == expected_width

    def test_size_hint_height_includes_margin(self, delegate):
        """Verify sizeHint height is ICON_SIZE + 4."""
        option = Mock(spec=QStyleOptionViewItem)
        index = Mock(spec=QModelIndex)

        result = delegate.sizeHint(option, index)

        expected_height = delegate.ICON_SIZE + 4
        assert result.height() == expected_height

    def test_size_hint_minimum_one_host(self, qapp):
        """Verify sizeHint uses minimum of 1 host when none enabled."""
        with patch('src.gui.delegates.file_hosts_status_delegate.get_icon_manager'):
            from src.gui.delegates.file_hosts_status_delegate import FileHostsStatusDelegate
            delegate = FileHostsStatusDelegate()

            # No enabled hosts
            mock_config_manager = Mock()
            mock_config_manager.get_enabled_hosts.return_value = {}
            delegate._config_manager = mock_config_manager

            option = Mock(spec=QStyleOptionViewItem)
            index = Mock(spec=QModelIndex)

            result = delegate.sizeHint(option, index)

            # With max(1, 0) = 1 host
            expected_width = delegate.PADDING * 2 + 1 * (delegate.ICON_SIZE + delegate.ICON_SPACING)
            assert result.width() == expected_width


class TestFileHostsStatusDelegateSignals:
    """Test suite for FileHostsStatusDelegate signal emission."""

    @pytest.fixture
    def delegate_with_mocks(self, qapp):
        """Create FileHostsStatusDelegate with all necessary mocks."""
        with patch('src.gui.delegates.file_hosts_status_delegate.get_icon_manager') as mock_get_icon:
            mock_icon_manager = Mock()
            mock_icon = Mock(spec=QIcon)
            mock_icon.isNull.return_value = False
            mock_icon.pixmap.return_value = Mock(spec=QPixmap)
            mock_icon_manager.get_file_host_icon.return_value = mock_icon
            mock_get_icon.return_value = mock_icon_manager

            from src.gui.delegates.file_hosts_status_delegate import FileHostsStatusDelegate
            delegate = FileHostsStatusDelegate()

            # Mock config manager
            mock_config_manager = Mock()
            mock_config_manager.get_enabled_hosts.return_value = {
                "rapidgator": {"enabled": True},
            }
            delegate._config_manager = mock_config_manager

            yield delegate, mock_icon_manager

    def test_host_clicked_signal_exists(self, delegate_with_mocks):
        """Verify host_clicked signal is accessible."""
        delegate, _ = delegate_with_mocks

        assert delegate.host_clicked is not None
        assert hasattr(delegate.host_clicked, 'emit')

    def test_host_clicked_signal_emits_on_click(self, delegate_with_mocks, qtbot):
        """Verify host_clicked signal emits with correct arguments."""
        delegate, _ = delegate_with_mocks

        # Mock index with path and host_uploads data
        mock_index = Mock(spec=QModelIndex)
        mock_index.row.return_value = 0
        # data returns path for UserRole, host_uploads dict for UserRole+1
        mock_index.data.side_effect = lambda role: {
            Qt.ItemDataRole.UserRole: "/test/gallery/path",
            Qt.ItemDataRole.UserRole + 1: {"rapidgator": {"status": "completed"}}
        }.get(role)

        # Mock option with cell rect
        mock_option = Mock(spec=QStyleOptionViewItem)
        mock_option.rect = QRect(0, 0, 100, 30)  # Icon will be at (4, y)

        # Mock event
        mock_event = Mock()
        mock_event.type.return_value = QEvent.Type.MouseButtonRelease
        mock_position = Mock()
        mock_position.toPoint.return_value = QPoint(10, 10)  # Inside icon rect
        mock_event.position.return_value = mock_position

        # Connect signal to capture emission
        received_args = []

        def on_clicked(path, host):
            received_args.append((path, host))

        delegate.host_clicked.connect(on_clicked)

        # Trigger editor event
        result = delegate.editorEvent(mock_event, Mock(), mock_option, mock_index)

        assert result is True
        assert len(received_args) == 1
        assert received_args[0] == ("/test/gallery/path", "rapidgator")

    def test_host_clicked_correct_host_when_multiple(self, delegate_with_mocks, qtbot):
        """Verify correct host is identified when multiple hosts displayed."""
        delegate, _ = delegate_with_mocks

        # Mock index with multiple hosts
        mock_index = Mock(spec=QModelIndex)
        mock_index.row.return_value = 0
        mock_index.data.side_effect = lambda role: {
            Qt.ItemDataRole.UserRole: "/test/path",
            Qt.ItemDataRole.UserRole + 1: {
                "fileboom": {"status": "pending"},
                "keep2share": {"status": "pending"},
                "rapidgator": {"status": "pending"},
            }
        }.get(role)

        # Mock option with cell rect - icons start at x=4, each 22+2=24 wide
        mock_option = Mock(spec=QStyleOptionViewItem)
        mock_option.rect = QRect(0, 0, 200, 30)

        mock_event = Mock()
        mock_event.type.return_value = QEvent.Type.MouseButtonRelease
        mock_position = Mock()
        # Click at x=35 should hit the second icon (fileboom, sorted alphabetically)
        mock_position.toPoint.return_value = QPoint(35, 10)
        mock_event.position.return_value = mock_position

        received_args = []
        delegate.host_clicked.connect(lambda p, h: received_args.append((p, h)))

        delegate.editorEvent(mock_event, Mock(), mock_option, mock_index)

        assert len(received_args) == 1
        assert received_args[0][1] == "keep2share"  # Second alphabetically after fileboom

    def test_host_clicked_not_emitted_outside_icons(self, delegate_with_mocks):
        """Verify host_clicked is not emitted when clicking outside all icons."""
        delegate, _ = delegate_with_mocks

        mock_index = Mock(spec=QModelIndex)
        mock_index.row.return_value = 0
        mock_index.data.side_effect = lambda role: {
            Qt.ItemDataRole.UserRole: "/test/path",
            Qt.ItemDataRole.UserRole + 1: {"rapidgator": {"status": "completed"}}
        }.get(role)

        mock_option = Mock(spec=QStyleOptionViewItem)
        mock_option.rect = QRect(0, 0, 100, 30)

        mock_event = Mock()
        mock_event.type.return_value = QEvent.Type.MouseButtonRelease
        mock_position = Mock()
        mock_position.toPoint.return_value = QPoint(100, 100)  # Outside all icons
        mock_event.position.return_value = mock_position

        received_args = []
        delegate.host_clicked.connect(lambda p, h: received_args.append((p, h)))

        # Mock the parent class's editorEvent to avoid TypeError with Mock arguments
        with patch.object(QStyledItemDelegate, 'editorEvent', return_value=False):
            result = delegate.editorEvent(mock_event, Mock(), mock_option, mock_index)

        assert result is False
        assert len(received_args) == 0


class TestFileHostsStatusDelegatePaint:
    """Test suite for FileHostsStatusDelegate.paint()."""

    @pytest.fixture
    def delegate_with_mocks(self, qapp):
        """Create FileHostsStatusDelegate with all necessary mocks for paint testing."""
        with patch('src.gui.delegates.file_hosts_status_delegate.get_icon_manager') as mock_get_icon:
            mock_icon_manager = Mock()
            mock_icon = Mock(spec=QIcon)
            mock_icon.isNull.return_value = False
            mock_icon.pixmap.return_value = Mock(spec=QPixmap)
            mock_icon_manager.get_file_host_icon.return_value = mock_icon
            mock_get_icon.return_value = mock_icon_manager

            from src.gui.delegates.file_hosts_status_delegate import FileHostsStatusDelegate
            delegate = FileHostsStatusDelegate()

            # Mock config manager
            mock_config_manager = Mock()
            mock_config_manager.get_enabled_hosts.return_value = {
                "rapidgator": {"enabled": True},
                "fileboom": {"enabled": True},
            }
            delegate._config_manager = mock_config_manager

            yield delegate, mock_icon_manager

    def test_paint_requests_icons_for_all_hosts(self, delegate_with_mocks):
        """Verify paint requests icons for all enabled hosts."""
        delegate, mock_icon_manager = delegate_with_mocks

        mock_painter = Mock(spec=QPainter)
        mock_option = Mock(spec=QStyleOptionViewItem)
        mock_option.rect = QRect(0, 0, 200, 30)

        mock_index = Mock(spec=QModelIndex)
        mock_index.row.return_value = 0
        mock_index.data.side_effect = ["/test/path", {}]  # UserRole, UserRole+1

        delegate.paint(mock_painter, mock_option, mock_index)

        # Should request icon for each host
        assert mock_icon_manager.get_file_host_icon.call_count >= 2

    def test_paint_uses_dimmed_icon_for_non_completed(self, delegate_with_mocks):
        """Verify paint uses dimmed icon for non-completed uploads."""
        delegate, mock_icon_manager = delegate_with_mocks

        mock_painter = Mock(spec=QPainter)
        mock_option = Mock(spec=QStyleOptionViewItem)
        mock_option.rect = QRect(0, 0, 200, 30)

        mock_index = Mock(spec=QModelIndex)
        mock_index.row.return_value = 0
        mock_index.data.side_effect = [
            "/test/path",
            {"rapidgator": {"status": "uploading"}}
        ]

        delegate.paint(mock_painter, mock_option, mock_index)

        # Should call with dimmed=True for uploading status
        calls = mock_icon_manager.get_file_host_icon.call_args_list
        rapidgator_calls = [c for c in calls if c[0][0] == "rapidgator"]
        assert any(c[1].get('dimmed', False) for c in rapidgator_calls)

    def test_paint_uses_bright_icon_for_completed(self, delegate_with_mocks):
        """Verify paint uses bright icon for completed uploads."""
        delegate, mock_icon_manager = delegate_with_mocks

        mock_painter = Mock(spec=QPainter)
        mock_option = Mock(spec=QStyleOptionViewItem)
        mock_option.rect = QRect(0, 0, 200, 30)

        mock_index = Mock(spec=QModelIndex)
        mock_index.row.return_value = 0
        mock_index.data.side_effect = [
            "/test/path",
            {"rapidgator": {"status": "completed"}}
        ]

        delegate.paint(mock_painter, mock_option, mock_index)

        # Should call with dimmed=False for completed status
        calls = mock_icon_manager.get_file_host_icon.call_args_list
        rapidgator_calls = [c for c in calls if c[0][0] == "rapidgator"]
        assert any(c[1].get('dimmed', True) is False for c in rapidgator_calls)

    def test_compute_icon_rects_returns_correct_positions(self, delegate_with_mocks):
        """Verify _compute_icon_rects returns correct icon rectangles."""
        delegate, _ = delegate_with_mocks

        cell_rect = QRect(10, 20, 200, 30)
        host_uploads = {"rapidgator": {"status": "completed"}}

        icon_rects = delegate._compute_icon_rects(cell_rect, host_uploads)

        # Should have at least one icon (rapidgator)
        assert len(icon_rects) >= 1
        # First icon should be at PADDING from cell left edge
        first_host, first_rect = icon_rects[0]
        assert first_rect.x() == 10 + delegate.PADDING
        assert first_rect.width() == delegate.ICON_SIZE

    def test_paint_does_nothing_without_path(self, delegate_with_mocks):
        """Verify paint returns early if no path in index."""
        delegate, mock_icon_manager = delegate_with_mocks

        mock_painter = Mock(spec=QPainter)
        mock_option = Mock(spec=QStyleOptionViewItem)
        mock_index = Mock(spec=QModelIndex)
        mock_index.data.side_effect = [None, {}]  # No path

        delegate.paint(mock_painter, mock_option, mock_index)

        mock_icon_manager.get_file_host_icon.assert_not_called()


class TestFileHostsStatusDelegateConfigManager:
    """Test suite for FileHostsStatusDelegate config manager integration."""

    @pytest.fixture
    def delegate(self, qapp):
        """Create FileHostsStatusDelegate."""
        with patch('src.gui.delegates.file_hosts_status_delegate.get_icon_manager'):
            from src.gui.delegates.file_hosts_status_delegate import FileHostsStatusDelegate
            return FileHostsStatusDelegate()

    def test_get_enabled_hosts_caches_result(self, delegate, monkeypatch):
        """Verify _get_enabled_hosts caches the result."""
        mock_config_manager = Mock()
        mock_config_manager.get_enabled_hosts.return_value = {"host1": {}}
        delegate._config_manager = mock_config_manager

        # First call
        result1 = delegate._get_enabled_hosts()

        # Second call should use cache
        result2 = delegate._get_enabled_hosts()

        # Should only call config manager once
        assert mock_config_manager.get_enabled_hosts.call_count == 1
        assert result1 is result2

    def test_refresh_enabled_hosts_clears_cache(self, delegate):
        """Verify refresh_enabled_hosts clears the cache."""
        delegate._enabled_hosts_cache = {"cached": {}}

        delegate.refresh_enabled_hosts()

        assert delegate._enabled_hosts_cache is None

    def test_get_enabled_hosts_returns_empty_without_config_manager(self, delegate, monkeypatch):
        """Verify _get_enabled_hosts returns empty dict without config manager."""
        # Prevent lazy loading of config manager by patching at correct import path
        with patch('src.core.file_host_config.get_config_manager', return_value=None):
            delegate._config_manager = None
            delegate._enabled_hosts_cache = None

            result = delegate._get_enabled_hosts()

            assert result == {}


class TestFileHostsStatusDelegateConstants:
    """Test suite for FileHostsStatusDelegate constants."""

    def test_default_constants(self, qapp):
        """Verify class constants are set correctly."""
        with patch('src.gui.delegates.file_hosts_status_delegate.get_icon_manager'):
            from src.gui.delegates.file_hosts_status_delegate import FileHostsStatusDelegate

            assert FileHostsStatusDelegate.ICON_SIZE == 22
            assert FileHostsStatusDelegate.ICON_SPACING == 2
            assert FileHostsStatusDelegate.PADDING == 4


# =============================================================================
# Integration Tests
# =============================================================================

class TestDelegateIntegration:
    """Integration tests for delegate classes working together."""

    @pytest.fixture
    def delegates(self, qapp, monkeypatch):
        """Create both delegates with common mocks."""
        with patch('src.gui.delegates.action_button_delegate.get_icon_manager') as mock_action_icon, \
             patch('src.gui.delegates.file_hosts_status_delegate.get_icon_manager') as mock_host_icon:

            mock_icon = Mock(spec=QIcon)
            mock_icon.isNull.return_value = False
            mock_icon.pixmap.return_value = Mock(spec=QPixmap)

            mock_action_manager = Mock()
            mock_action_manager.get_icon.return_value = mock_icon
            mock_action_icon.return_value = mock_action_manager

            mock_host_manager = Mock()
            mock_host_manager.get_file_host_icon.return_value = mock_icon
            mock_host_icon.return_value = mock_host_manager

            from src.gui.delegates.action_button_delegate import ActionButtonDelegate
            from src.gui.delegates.file_hosts_status_delegate import FileHostsStatusDelegate

            action_delegate = ActionButtonDelegate()
            host_delegate = FileHostsStatusDelegate()

            # Setup mock managers
            mock_queue_manager = Mock()
            mock_item = Mock()
            mock_item.status = "completed"
            mock_queue_manager.get_item.return_value = mock_item
            action_delegate.set_queue_manager(mock_queue_manager)

            mock_config_manager = Mock()
            mock_config_manager.get_enabled_hosts.return_value = {"rapidgator": {}}
            host_delegate._config_manager = mock_config_manager

            yield action_delegate, host_delegate

    def test_both_delegates_emit_signals(self, delegates, qtbot):
        """Verify both delegates can emit their signals."""
        action_delegate, host_delegate = delegates

        action_signals_received = []
        host_signals_received = []

        action_delegate.button_clicked.connect(
            lambda p, a: action_signals_received.append((p, a))
        )
        host_delegate.host_clicked.connect(
            lambda p, h: host_signals_received.append((p, h))
        )

        # Directly emit signals for testing
        action_delegate.signals.button_clicked.emit("/path", "view")
        host_delegate.signals.host_clicked.emit("/path", "rapidgator")

        assert len(action_signals_received) == 1
        assert len(host_signals_received) == 1
        assert action_signals_received[0] == ("/path", "view")
        assert host_signals_received[0] == ("/path", "rapidgator")
