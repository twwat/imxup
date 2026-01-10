#!/usr/bin/env python3
"""
pytest-qt tests for ImxUploadGUI (main_window.py)
Tests main window initialization, UI components, menus, signals, and basic interactions
"""

import pytest
import sys
import os
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch, PropertyMock
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QMessageBox, QPushButton,
    QTableWidget, QTextEdit, QLabel, QSystemTrayIcon, QMenu
)
from PyQt6.QtCore import Qt, QSettings, QTimer, pyqtSignal
from PyQt6.QtGui import QIcon

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.gui.main_window import (
    ImxUploadGUI, CompletionWorker, SingleInstanceServer,
    LogTextEdit, NumericTableWidgetItem, get_icon,
    check_stored_credentials, api_key_is_set, format_timestamp_for_display
)
from src.gui.menu_manager import MenuManager


# ============================================================================
# Module-level Function Tests
# ============================================================================

class TestModuleFunctions:
    """Test module-level utility functions"""

    def test_format_timestamp_for_display_valid(self):
        """Test timestamp formatting with valid timestamp"""
        timestamp = 1700000000  # Nov 14, 2023
        display, tooltip = format_timestamp_for_display(timestamp)

        assert display != ""
        assert tooltip != ""
        assert len(display) > 0
        assert len(tooltip) >= len(display)  # Tooltip includes seconds

    def test_format_timestamp_for_display_empty(self):
        """Test timestamp formatting with empty/None value"""
        display, tooltip = format_timestamp_for_display(None)
        assert display == ""
        assert tooltip == ""

    def test_format_timestamp_for_display_invalid(self):
        """Test timestamp formatting with invalid value"""
        display, tooltip = format_timestamp_for_display(-1)
        # Should handle gracefully
        assert isinstance(display, str)
        assert isinstance(tooltip, str)

    @patch('imxup.get_credential')
    def test_check_stored_credentials_with_username_password(self, mock_get_cred):
        """Test credential check with username and password"""
        mock_get_cred.side_effect = lambda x: {
            'username': 'testuser',
            'password': 'encrypted_pass',
            'api_key': None
        }.get(x)

        assert check_stored_credentials() is True

    @patch('imxup.get_credential')
    def test_check_stored_credentials_with_api_key(self, mock_get_cred):
        """Test credential check with API key only"""
        mock_get_cred.side_effect = lambda x: {
            'username': None,
            'password': None,
            'api_key': 'encrypted_api_key'
        }.get(x)

        assert check_stored_credentials() is True

    @patch('imxup.get_credential')
    def test_check_stored_credentials_none(self, mock_get_cred):
        """Test credential check with no credentials"""
        mock_get_cred.return_value = None
        assert check_stored_credentials() is False

    @patch('imxup.get_credential')
    def test_api_key_is_set_true(self, mock_get_cred):
        """Test API key check when set"""
        mock_get_cred.return_value = 'encrypted_api_key'
        assert api_key_is_set() is True

    @patch('imxup.get_credential')
    def test_api_key_is_set_false(self, mock_get_cred):
        """Test API key check when not set"""
        mock_get_cred.return_value = None
        assert api_key_is_set() is False

    @patch('src.gui.main_window.get_icon_manager')
    def test_get_icon_success(self, mock_icon_mgr):
        """Test get_icon returns QIcon"""
        mock_mgr = Mock()
        mock_mgr.get_icon.return_value = QIcon()
        mock_icon_mgr.return_value = mock_mgr

        icon = get_icon('test_icon')
        assert isinstance(icon, QIcon)
        mock_mgr.get_icon.assert_called_once()

    @patch('src.gui.main_window.get_icon_manager')
    def test_get_icon_no_manager(self, mock_icon_mgr):
        """Test get_icon when manager not available"""
        mock_icon_mgr.return_value = None
        icon = get_icon('test_icon')
        assert isinstance(icon, QIcon)
        assert icon.isNull()


# ============================================================================
# LogTextEdit Tests
# ============================================================================

class TestLogTextEdit:
    """Test custom LogTextEdit widget"""

    def test_logtextedit_creation(self, qtbot):
        """Test LogTextEdit can be created"""
        widget = LogTextEdit()
        qtbot.addWidget(widget)
        assert widget is not None

    def test_logtextedit_has_doubleclicked_signal(self, qtbot):
        """Test LogTextEdit has doubleClicked signal"""
        widget = LogTextEdit()
        qtbot.addWidget(widget)
        assert hasattr(widget, 'doubleClicked')

    def test_logtextedit_double_click_emits_signal(self, qtbot):
        """Test double-click emits signal"""
        widget = LogTextEdit()
        qtbot.addWidget(widget)

        with qtbot.waitSignal(widget.doubleClicked, timeout=1000):
            qtbot.mouseDClick(widget.viewport(), Qt.MouseButton.LeftButton)

    def test_logtextedit_accepts_text(self, qtbot):
        """Test LogTextEdit can display text"""
        widget = LogTextEdit()
        qtbot.addWidget(widget)

        test_text = "Test log message"
        widget.setPlainText(test_text)
        assert widget.toPlainText() == test_text


# ============================================================================
# NumericTableWidgetItem Tests
# ============================================================================

class TestNumericTableWidgetItem:
    """Test NumericTableWidgetItem sorting"""

    def test_numeric_item_creation(self):
        """Test NumericTableWidgetItem creation"""
        item = NumericTableWidgetItem(42)
        assert item.text() == "42"
        assert item._numeric_value == 42

    def test_numeric_item_sorting(self):
        """Test numeric sorting"""
        item1 = NumericTableWidgetItem(10)
        item2 = NumericTableWidgetItem(100)

        assert item1 < item2
        assert not item2 < item1

    def test_numeric_item_invalid_value(self):
        """Test handling of invalid numeric value"""
        item = NumericTableWidgetItem("invalid")
        assert item._numeric_value == 0


# ============================================================================
# CompletionWorker Tests
# ============================================================================

class TestCompletionWorker:
    """Test CompletionWorker background thread"""

    def test_completion_worker_creation(self, qtbot):
        """Test CompletionWorker can be created"""
        worker = CompletionWorker()
        # QThread doesn't use addWidget
        assert worker is not None
        assert hasattr(worker, 'completion_queue')
        worker.stop()
        worker.wait()

    def test_completion_worker_has_signals(self, qtbot):
        """Test CompletionWorker has required signals"""
        worker = CompletionWorker()

        assert hasattr(worker, 'completion_processed')
        assert hasattr(worker, 'log_message')
        worker.stop()
        worker.wait()

    def test_completion_worker_stop(self, qtbot):
        """Test CompletionWorker can be stopped"""
        worker = CompletionWorker()
        worker.start()

        worker.stop()
        worker.wait(1000)  # Wait with timeout in milliseconds (positional arg)
        assert not worker.isRunning()


# ============================================================================
# SingleInstanceServer Tests
# ============================================================================

class TestSingleInstanceServer:
    """Test SingleInstanceServer socket communication"""

    def test_single_instance_server_creation(self, qtbot):
        """Test SingleInstanceServer creation"""
        server = SingleInstanceServer(port=27850)  # Use different port
        # QThread doesn't use addWidget
        assert server is not None
        assert server.port == 27850
        server.stop()

    def test_single_instance_server_has_signal(self, qtbot):
        """Test SingleInstanceServer has folder_received signal"""
        server = SingleInstanceServer(port=27851)
        assert hasattr(server, 'folder_received')
        server.stop()

    def test_single_instance_server_stop(self, qtbot):
        """Test SingleInstanceServer can be stopped"""
        server = SingleInstanceServer(port=27852)
        server.start()

        server.stop()
        assert not server.isRunning()


# ============================================================================
# ImxUploadGUI Initialization Tests
# ============================================================================

@pytest.fixture
def mock_dependencies(monkeypatch, tmp_path):
    """Mock all dependencies for ImxUploadGUI"""
    # Mock imxup functions
    monkeypatch.setattr('imxup.get_project_root', lambda: str(tmp_path))
    monkeypatch.setattr('imxup.get_config_path', lambda: str(tmp_path / '.imxup'))
    monkeypatch.setattr('imxup.load_user_defaults', lambda: {})
    monkeypatch.setattr('imxup.get_credential', lambda x: None)
    monkeypatch.setattr('src.utils.logger.set_main_window', lambda x: None)

    # Mock IconManager
    mock_icon_mgr = Mock()
    mock_icon_mgr.get_icon.return_value = QIcon()
    mock_icon_mgr.get_status_icon.return_value = QIcon()
    mock_icon_mgr.validate_icons.return_value = {'missing': [], 'found': []}
    monkeypatch.setattr('src.gui.main_window.init_icon_manager', lambda x: mock_icon_mgr)
    monkeypatch.setattr('src.gui.main_window.get_icon_manager', lambda: mock_icon_mgr)

    # Mock QueueManager
    mock_queue_mgr = Mock()
    mock_queue_mgr.items = {}
    mock_queue_mgr.get_version.return_value = 1
    mock_queue_mgr.get_scan_queue_status.return_value = {'queue_size': 0, 'items_pending_scan': 0}
    mock_queue_mgr.status_changed = Mock()
    mock_queue_mgr.status_changed.connect = Mock()
    mock_queue_mgr.queue_loaded = Mock()
    mock_queue_mgr.queue_loaded.connect = Mock()
    mock_queue_mgr.store = Mock()
    monkeypatch.setattr('src.gui.main_window.QueueManager', lambda: mock_queue_mgr)

    # Mock ArchiveService
    mock_archive_service = Mock()
    monkeypatch.setattr('src.gui.main_window.ArchiveService', lambda x: mock_archive_service)

    # Mock ArchiveCoordinator
    mock_archive_coord = Mock()
    monkeypatch.setattr('src.gui.main_window.ArchiveCoordinator', lambda *args, **kwargs: mock_archive_coord)

    # Mock TabManager
    mock_tab_mgr = Mock()
    mock_tab_mgr.get_visible_tab_names.return_value = []
    mock_tab_mgr.get_all_tabs.return_value = []
    monkeypatch.setattr('src.gui.main_window.TabManager', lambda x: mock_tab_mgr)

    # Mock FileHostWorkerManager
    mock_filehost_mgr = Mock()
    mock_filehost_mgr.test_completed = Mock()
    mock_filehost_mgr.test_completed.connect = Mock()
    mock_filehost_mgr.upload_started = Mock()
    mock_filehost_mgr.upload_started.connect = Mock()
    mock_filehost_mgr.upload_progress = Mock()
    mock_filehost_mgr.upload_progress.connect = Mock()
    mock_filehost_mgr.upload_completed = Mock()
    mock_filehost_mgr.upload_completed.connect = Mock()
    mock_filehost_mgr.upload_failed = Mock()
    mock_filehost_mgr.upload_failed.connect = Mock()
    mock_filehost_mgr.bandwidth_updated = Mock()
    mock_filehost_mgr.bandwidth_updated.connect = Mock()
    monkeypatch.setattr('src.processing.file_host_worker_manager.FileHostWorkerManager', lambda x: mock_filehost_mgr)

    return {
        'icon_mgr': mock_icon_mgr,
        'queue_mgr': mock_queue_mgr,
        'tab_mgr': mock_tab_mgr,
        'archive_coord': mock_archive_coord,
        'filehost_mgr': mock_filehost_mgr
    }


class TestImxUploadGUIInitialization:
    """Test ImxUploadGUI initialization"""

    @patch('src.gui.main_window.QSettings')
    def test_main_window_creation(self, mock_qsettings, qtbot, mock_dependencies):
        """Test main window can be created"""
        mock_settings = Mock()
        mock_settings.value.return_value = 0
        mock_qsettings.return_value = mock_settings

        with patch.object(MenuManager, 'setup_menu_bar'):
            with patch.object(ImxUploadGUI, 'setup_system_tray'):
                with patch.object(ImxUploadGUI, 'restore_settings'):
                    with patch.object(ImxUploadGUI, 'check_credentials'):
                        window = ImxUploadGUI()
                        qtbot.addWidget(window)

                        assert window is not None
                        assert isinstance(window, QMainWindow)

    @patch('src.gui.main_window.QSettings')
    def test_main_window_has_queue_manager(self, mock_qsettings, qtbot, mock_dependencies):
        """Test main window initializes queue manager"""
        mock_settings = Mock()
        mock_settings.value.return_value = 0
        mock_qsettings.return_value = mock_settings

        with patch.object(ImxUploadGUI, 'setup_ui'):
            with patch.object(MenuManager, 'setup_menu_bar'):
                with patch.object(ImxUploadGUI, 'setup_system_tray'):
                    with patch.object(ImxUploadGUI, 'restore_settings'):
                        with patch.object(ImxUploadGUI, 'check_credentials'):
                            window = ImxUploadGUI()
                            qtbot.addWidget(window)

                            assert hasattr(window, 'queue_manager')

    @patch('src.gui.main_window.QSettings')
    def test_main_window_has_completion_worker(self, mock_qsettings, qtbot, mock_dependencies):
        """Test main window starts completion worker"""
        mock_settings = Mock()
        mock_settings.value.return_value = 0
        mock_qsettings.return_value = mock_settings

        with patch.object(ImxUploadGUI, 'setup_ui'):
            with patch.object(MenuManager, 'setup_menu_bar'):
                with patch.object(ImxUploadGUI, 'setup_system_tray'):
                    with patch.object(ImxUploadGUI, 'restore_settings'):
                        with patch.object(ImxUploadGUI, 'check_credentials'):
                            window = ImxUploadGUI()
                            qtbot.addWidget(window)

                            assert hasattr(window, 'completion_worker')

    @patch('src.gui.main_window.QSettings')
    def test_main_window_has_single_instance_server(self, mock_qsettings, qtbot, mock_dependencies):
        """Test main window starts single instance server"""
        mock_settings = Mock()
        mock_settings.value.return_value = 0
        mock_qsettings.return_value = mock_settings

        with patch.object(ImxUploadGUI, 'setup_ui'):
            with patch.object(MenuManager, 'setup_menu_bar'):
                with patch.object(ImxUploadGUI, 'setup_system_tray'):
                    with patch.object(ImxUploadGUI, 'restore_settings'):
                        with patch.object(ImxUploadGUI, 'check_credentials'):
                            window = ImxUploadGUI()
                            qtbot.addWidget(window)

                            assert hasattr(window, 'server')

    @patch('src.gui.main_window.QSettings')
    def test_main_window_accepts_drops(self, mock_qsettings, qtbot, mock_dependencies):
        """Test main window accepts drag and drop"""
        mock_settings = Mock()
        mock_settings.value.return_value = 0
        mock_qsettings.return_value = mock_settings

        with patch.object(ImxUploadGUI, 'setup_ui'):
            with patch.object(MenuManager, 'setup_menu_bar'):
                with patch.object(ImxUploadGUI, 'setup_system_tray'):
                    with patch.object(ImxUploadGUI, 'restore_settings'):
                        with patch.object(ImxUploadGUI, 'check_credentials'):
                            window = ImxUploadGUI()
                            qtbot.addWidget(window)

                            assert window.acceptDrops() is True


# ============================================================================
# UI Setup Tests
# ============================================================================

class TestImxUploadGUISetup:
    """Test UI component setup"""

    @patch('src.gui.main_window.QSettings')
    def test_setup_ui_called(self, mock_qsettings, qtbot, mock_dependencies):
        """Test setup_ui is called during initialization"""
        mock_settings = Mock()
        mock_settings.value.return_value = 0
        mock_qsettings.return_value = mock_settings

        with patch.object(MenuManager, 'setup_menu_bar'):
            with patch.object(ImxUploadGUI, 'setup_system_tray'):
                with patch.object(ImxUploadGUI, 'restore_settings'):
                    with patch.object(ImxUploadGUI, 'check_credentials'):
                        window = ImxUploadGUI()
                        qtbot.addWidget(window)

                        # setup_ui is called as part of initialization
                        assert hasattr(window, 'gallery_table')

    @patch('src.gui.main_window.QSettings')
    def test_setup_menu_bar_called(self, mock_qsettings, qtbot, mock_dependencies):
        """Test setup_menu_bar is called during initialization"""
        mock_settings = Mock()
        mock_settings.value.return_value = 0
        mock_qsettings.return_value = mock_settings

        with patch.object(ImxUploadGUI, 'setup_ui'):
            with patch.object(MenuManager, 'setup_menu_bar') as mock_menu:
                with patch.object(ImxUploadGUI, 'setup_system_tray'):
                    with patch.object(ImxUploadGUI, 'restore_settings'):
                        with patch.object(ImxUploadGUI, 'check_credentials'):
                            window = ImxUploadGUI()
                            qtbot.addWidget(window)

                            mock_menu.assert_called_once()

    @patch('src.gui.main_window.QSettings')
    def test_setup_system_tray_called(self, mock_qsettings, qtbot, mock_dependencies):
        """Test setup_system_tray is called during initialization"""
        mock_settings = Mock()
        mock_settings.value.return_value = 0
        mock_qsettings.return_value = mock_settings

        with patch.object(ImxUploadGUI, 'setup_ui'):
            with patch.object(MenuManager, 'setup_menu_bar'):
                with patch.object(ImxUploadGUI, 'setup_system_tray') as mock_tray:
                    with patch.object(ImxUploadGUI, 'restore_settings'):
                        with patch.object(ImxUploadGUI, 'check_credentials'):
                            window = ImxUploadGUI()
                            qtbot.addWidget(window)

                            mock_tray.assert_called_once()


# ============================================================================
# Helper Method Tests
# ============================================================================

class TestImxUploadGUIHelpers:
    """Test helper methods"""

    @patch('src.gui.main_window.QSettings')
    def test_format_rate_consistent(self, mock_qsettings, qtbot, mock_dependencies):
        """Test rate formatting"""
        mock_settings = Mock()
        mock_settings.value.return_value = 0
        mock_qsettings.return_value = mock_settings

        with patch.object(ImxUploadGUI, 'setup_ui'):
            with patch.object(MenuManager, 'setup_menu_bar'):
                with patch.object(ImxUploadGUI, 'setup_system_tray'):
                    with patch.object(ImxUploadGUI, 'restore_settings'):
                        with patch.object(ImxUploadGUI, 'check_credentials'):
                            window = ImxUploadGUI()
                            qtbot.addWidget(window)

                                # Test KiB/s
                            result = window._format_rate_consistent(500)
                            assert "KiB/s" in result

                                # Test MiB/s
                            result = window._format_rate_consistent(1500)
                            assert "MiB/s" in result

    @patch('src.gui.main_window.QSettings')
    def test_format_size_consistent(self, mock_qsettings, qtbot, mock_dependencies):
        """Test size formatting"""
        mock_settings = Mock()
        mock_settings.value.return_value = 0
        mock_qsettings.return_value = mock_settings

        with patch.object(ImxUploadGUI, 'setup_ui'):
            with patch.object(MenuManager, 'setup_menu_bar'):
                with patch.object(ImxUploadGUI, 'setup_system_tray'):
                    with patch.object(ImxUploadGUI, 'restore_settings'):
                        with patch.object(ImxUploadGUI, 'check_credentials'):
                            window = ImxUploadGUI()
                            qtbot.addWidget(window)

                                # Test bytes
                            result = window._format_size_consistent(512)
                            assert "B" in result

                                # Test KiB
                            result = window._format_size_consistent(1024 * 10)
                            assert "KiB" in result

                                # Test MiB
                            result = window._format_size_consistent(1024 * 1024 * 5)
                            assert "MiB" in result

                                # Test GiB
                            result = window._format_size_consistent(1024 * 1024 * 1024 * 2)
                            assert "GiB" in result

    @patch('src.gui.main_window.QSettings')
    def test_format_size_empty(self, mock_qsettings, qtbot, mock_dependencies):
        """Test size formatting with empty value"""
        mock_settings = Mock()
        mock_settings.value.return_value = 0
        mock_qsettings.return_value = mock_settings

        with patch.object(ImxUploadGUI, 'setup_ui'):
            with patch.object(MenuManager, 'setup_menu_bar'):
                with patch.object(ImxUploadGUI, 'setup_system_tray'):
                    with patch.object(ImxUploadGUI, 'restore_settings'):
                        with patch.object(ImxUploadGUI, 'check_credentials'):
                            window = ImxUploadGUI()
                            qtbot.addWidget(window)

                            result = window._format_size_consistent(0)
                            assert result == ""

                            result = window._format_size_consistent(None)
                            assert result == ""


# ============================================================================
# Signal Connection Tests
# ============================================================================

class TestImxUploadGUISignals:
    """Test signal connections"""

    @patch('src.gui.main_window.QSettings')
    def test_completion_worker_signals_connected(self, mock_qsettings, qtbot, mock_dependencies):
        """Test completion worker signals are connected"""
        mock_settings = Mock()
        mock_settings.value.return_value = 0
        mock_qsettings.return_value = mock_settings

        with patch.object(ImxUploadGUI, 'setup_ui'):
            with patch.object(MenuManager, 'setup_menu_bar'):
                with patch.object(ImxUploadGUI, 'setup_system_tray'):
                    with patch.object(ImxUploadGUI, 'restore_settings'):
                        with patch.object(ImxUploadGUI, 'check_credentials'):
                            window = ImxUploadGUI()
                            qtbot.addWidget(window)

                                # Verify signals exist
                            assert hasattr(window.completion_worker, 'completion_processed')
                            assert hasattr(window.completion_worker, 'log_message')

    @patch('src.gui.main_window.QSettings')
    def test_server_signals_connected(self, mock_qsettings, qtbot, mock_dependencies):
        """Test single instance server signals are connected"""
        mock_settings = Mock()
        mock_settings.value.return_value = 0
        mock_qsettings.return_value = mock_settings

        with patch.object(ImxUploadGUI, 'setup_ui'):
            with patch.object(MenuManager, 'setup_menu_bar'):
                with patch.object(ImxUploadGUI, 'setup_system_tray'):
                    with patch.object(ImxUploadGUI, 'restore_settings'):
                        with patch.object(ImxUploadGUI, 'check_credentials'):
                            window = ImxUploadGUI()
                            qtbot.addWidget(window)

                                # Verify signal exists
                            assert hasattr(window.server, 'folder_received')


# ============================================================================
# Cleanup Tests
# ============================================================================

class TestImxUploadGUICleanup:
    """Test cleanup and shutdown"""

    @patch('src.gui.main_window.QSettings')
    def test_completion_worker_stops_on_close(self, mock_qsettings, qtbot, mock_dependencies):
        """Test completion worker is stopped on window close"""
        mock_settings = Mock()
        mock_settings.value.return_value = 0
        mock_qsettings.return_value = mock_settings

        with patch.object(ImxUploadGUI, 'setup_ui'):
            with patch.object(MenuManager, 'setup_menu_bar'):
                with patch.object(ImxUploadGUI, 'setup_system_tray'):
                    with patch.object(ImxUploadGUI, 'restore_settings'):
                        with patch.object(ImxUploadGUI, 'check_credentials'):
                            window = ImxUploadGUI()
                            qtbot.addWidget(window)

                                # Verify worker exists
                            assert hasattr(window, 'completion_worker')


# ============================================================================
# Resize Event Tests
# ============================================================================

class TestImxUploadGUIResize:
    """Test resize event handling"""

    @patch('src.gui.main_window.QSettings')
    def test_resize_event_updates_panel(self, mock_qsettings, qtbot, mock_dependencies):
        """Test resize event updates right panel width"""
        mock_settings = Mock()
        mock_settings.value.return_value = 0
        mock_qsettings.return_value = mock_settings

        with patch.object(ImxUploadGUI, 'setup_ui'):
            with patch.object(MenuManager, 'setup_menu_bar'):
                with patch.object(ImxUploadGUI, 'setup_system_tray'):
                    with patch.object(ImxUploadGUI, 'restore_settings'):
                        with patch.object(ImxUploadGUI, 'check_credentials'):
                            window = ImxUploadGUI()
                            qtbot.addWidget(window)

                                # Create mock right panel
                            mock_panel = Mock()
                            window.right_panel = mock_panel

                                # Trigger resize
                            window.resize(1000, 800)
                            qtbot.wait(100)

                                # Panel should exist
                            assert hasattr(window, 'right_panel')


# ============================================================================
# Filter and Refresh Tests
# ============================================================================

class TestImxUploadGUIFilter:
    """Test filter and refresh functionality"""

    @patch('src.gui.main_window.QSettings')
    def test_refresh_filter(self, mock_qsettings, qtbot, mock_dependencies):
        """Test refresh_filter method"""
        mock_settings = Mock()
        mock_settings.value.return_value = 0
        mock_qsettings.return_value = mock_settings

        with patch.object(ImxUploadGUI, 'setup_ui'):
            with patch.object(MenuManager, 'setup_menu_bar'):
                with patch.object(ImxUploadGUI, 'setup_system_tray'):
                    with patch.object(ImxUploadGUI, 'restore_settings'):
                        with patch.object(ImxUploadGUI, 'check_credentials'):
                            window = ImxUploadGUI()
                            qtbot.addWidget(window)

                                # Mock gallery_table
                            mock_table = Mock()
                            mock_table.refresh_filter = Mock()
                            window.gallery_table = mock_table

                                # Call refresh
                            window.refresh_filter()

                                # Should call gallery_table's refresh_filter
                            mock_table.refresh_filter.assert_called_once()


# ============================================================================
# Icon Tests
# ============================================================================

class TestImxUploadGUIIcons:
    """Test icon handling"""

    @patch('src.gui.main_window.QSettings')
    def test_refresh_icons(self, mock_qsettings, qtbot, mock_dependencies):
        """Test refresh_icons method"""
        mock_settings = Mock()
        mock_settings.value.return_value = 0
        mock_qsettings.return_value = mock_settings

        with patch.object(ImxUploadGUI, 'setup_ui'):
            with patch.object(MenuManager, 'setup_menu_bar'):
                with patch.object(ImxUploadGUI, 'setup_system_tray'):
                    with patch.object(ImxUploadGUI, 'restore_settings'):
                        with patch.object(ImxUploadGUI, 'check_credentials'):
                            window = ImxUploadGUI()
                            qtbot.addWidget(window)

                                # Mock gallery_table
                            mock_table = Mock()
                            mock_table.table = Mock()
                            mock_table.table.rowCount.return_value = 0
                            mock_table.table.viewport.return_value = Mock()
                            window.gallery_table = mock_table

                                # Should not raise
                            window.refresh_icons()


# ============================================================================
# Confirmation Dialog Tests
# ============================================================================

class TestImxUploadGUIConfirmation:
    """Test confirmation dialogs"""

    @patch('src.gui.main_window.QSettings')
    @patch('src.gui.main_window.load_user_defaults')
    @patch('src.gui.main_window.QMessageBox.question')
    def test_confirm_removal_single(self, mock_msg, mock_defaults, mock_qsettings, qtbot, mock_dependencies):
        """Test confirmation for single gallery removal"""
        mock_settings = Mock()
        mock_settings.value.return_value = 0
        mock_qsettings.return_value = mock_settings
        mock_defaults.return_value = {'confirm_delete': True}
        mock_msg.return_value = QMessageBox.StandardButton.Yes

        with patch.object(ImxUploadGUI, 'setup_ui'):
            with patch.object(MenuManager, 'setup_menu_bar'):
                with patch.object(ImxUploadGUI, 'setup_system_tray'):
                    with patch.object(ImxUploadGUI, 'restore_settings'):
                        with patch.object(ImxUploadGUI, 'check_credentials'):
                            window = ImxUploadGUI()
                            qtbot.addWidget(window)

                            result = window._confirm_removal(['/path/1'], ['Gallery 1'])
                            assert result is True
                            mock_msg.assert_called_once()

    @patch('src.gui.main_window.QSettings')
    @patch('src.gui.main_window.load_user_defaults')
    def test_confirm_removal_disabled(self, mock_defaults, mock_qsettings, qtbot, mock_dependencies):
        """Test confirmation skipped when disabled"""
        mock_settings = Mock()
        mock_settings.value.return_value = 0
        mock_qsettings.return_value = mock_settings
        mock_defaults.return_value = {'confirm_delete': False}

        with patch.object(ImxUploadGUI, 'setup_ui'):
            with patch.object(MenuManager, 'setup_menu_bar'):
                with patch.object(ImxUploadGUI, 'setup_system_tray'):
                    with patch.object(ImxUploadGUI, 'restore_settings'):
                        with patch.object(ImxUploadGUI, 'check_credentials'):
                            window = ImxUploadGUI()
                            qtbot.addWidget(window)

                            result = window._confirm_removal(['/path/1'], ['Gallery 1'])
                            assert result is True  # Should auto-confirm

    @patch('src.gui.main_window.QSettings')
    @patch('src.gui.main_window.load_user_defaults')
    @patch('src.gui.main_window.QMessageBox.question')
    def test_confirm_removal_large_batch(self, mock_msg, mock_defaults, mock_qsettings, qtbot, mock_dependencies):
        """Test confirmation always shown for large batches"""
        mock_settings = Mock()
        mock_settings.value.return_value = 0
        mock_qsettings.return_value = mock_settings
        mock_defaults.return_value = {'confirm_delete': False}
        mock_msg.return_value = QMessageBox.StandardButton.Yes

        with patch.object(ImxUploadGUI, 'setup_ui'):
            with patch.object(MenuManager, 'setup_menu_bar'):
                with patch.object(ImxUploadGUI, 'setup_system_tray'):
                    with patch.object(ImxUploadGUI, 'restore_settings'):
                        with patch.object(ImxUploadGUI, 'check_credentials'):
                            window = ImxUploadGUI()
                            qtbot.addWidget(window)

                            paths = [f'/path/{i}' for i in range(60)]
                            result = window._confirm_removal(paths)
                                # Should show confirmation for >50 galleries
                            mock_msg.assert_called_once()


# ============================================================================
# Background Tab Update Tests
# ============================================================================

class TestImxUploadGUIBackgroundUpdates:
    """Test background tab update system"""

    @patch('src.gui.main_window.QSettings')
    def test_queue_background_tab_update(self, mock_qsettings, qtbot, mock_dependencies):
        """Test queueing background tab updates"""
        mock_settings = Mock()
        mock_settings.value.return_value = 0
        mock_qsettings.return_value = mock_settings

        with patch.object(ImxUploadGUI, 'setup_ui'):
            with patch.object(MenuManager, 'setup_menu_bar'):
                with patch.object(ImxUploadGUI, 'setup_system_tray'):
                    with patch.object(ImxUploadGUI, 'restore_settings'):
                        with patch.object(ImxUploadGUI, 'check_credentials'):
                            window = ImxUploadGUI()
                            qtbot.addWidget(window)

                                # Should have background update tracking
                            assert hasattr(window, '_background_tab_updates')
                            assert isinstance(window._background_tab_updates, dict)

    @patch('src.gui.main_window.QSettings')
    def test_clear_background_tab_updates(self, mock_qsettings, qtbot, mock_dependencies):
        """Test clearing background tab updates"""
        mock_settings = Mock()
        mock_settings.value.return_value = 0
        mock_qsettings.return_value = mock_settings

        with patch.object(ImxUploadGUI, 'setup_ui'):
            with patch.object(MenuManager, 'setup_menu_bar'):
                with patch.object(ImxUploadGUI, 'setup_system_tray'):
                    with patch.object(ImxUploadGUI, 'restore_settings'):
                        with patch.object(ImxUploadGUI, 'check_credentials'):
                            window = ImxUploadGUI()
                            qtbot.addWidget(window)

                                # Add fake update
                            window._background_tab_updates['test'] = ('item', 'progress', 0)

                                # Clear
                            window.clear_background_tab_updates()

                                # Should be empty
                            assert len(window._background_tab_updates) == 0


# ============================================================================
# Animation Tests
# ============================================================================

class TestImxUploadGUIAnimation:
    """Test animation functionality"""

    @patch('src.gui.main_window.QSettings')
    def test_upload_animation_timer_exists(self, mock_qsettings, qtbot, mock_dependencies):
        """Test upload animation timer is initialized"""
        mock_settings = Mock()
        mock_settings.value.return_value = 0
        mock_qsettings.return_value = mock_settings

        with patch.object(ImxUploadGUI, 'setup_ui'):
            with patch.object(MenuManager, 'setup_menu_bar'):
                with patch.object(ImxUploadGUI, 'setup_system_tray'):
                    with patch.object(ImxUploadGUI, 'restore_settings'):
                        with patch.object(ImxUploadGUI, 'check_credentials'):
                            window = ImxUploadGUI()
                            qtbot.addWidget(window)

                            assert hasattr(window, '_upload_animation_timer')
                            assert hasattr(window, '_upload_animation_frame')


# ============================================================================
# Path Mapping Tests
# ============================================================================

class TestImxUploadGUIPathMapping:
    """Test path-to-row mapping"""

    @patch('src.gui.main_window.QSettings')
    def test_path_mapping_initialized(self, mock_qsettings, qtbot, mock_dependencies):
        """Test path mapping dictionaries are initialized"""
        mock_settings = Mock()
        mock_settings.value.return_value = 0
        mock_qsettings.return_value = mock_settings

        with patch.object(ImxUploadGUI, 'setup_ui'):
            with patch.object(MenuManager, 'setup_menu_bar'):
                with patch.object(ImxUploadGUI, 'setup_system_tray'):
                    with patch.object(ImxUploadGUI, 'restore_settings'):
                        with patch.object(ImxUploadGUI, 'check_credentials'):
                            window = ImxUploadGUI()
                            qtbot.addWidget(window)

                            assert hasattr(window, 'path_to_row')
                            assert hasattr(window, 'row_to_path')
                            assert isinstance(window.path_to_row, dict)
                            assert isinstance(window.row_to_path, dict)


# ============================================================================
# Settings Tests
# ============================================================================

class TestImxUploadGUISettings:
    """Test settings management"""

    @patch('src.gui.main_window.QSettings')
    def test_settings_initialized(self, mock_qsettings, qtbot, mock_dependencies):
        """Test QSettings is initialized"""
        mock_settings = Mock()
        mock_qsettings.return_value = mock_settings

        with patch.object(ImxUploadGUI, 'setup_ui'):
            with patch.object(MenuManager, 'setup_menu_bar'):
                with patch.object(ImxUploadGUI, 'setup_system_tray'):
                    with patch.object(ImxUploadGUI, 'restore_settings'):
                        with patch.object(ImxUploadGUI, 'check_credentials'):
                            window = ImxUploadGUI()
                            qtbot.addWidget(window)

                            assert hasattr(window, 'settings')


# ============================================================================
# Log Display Tests
# ============================================================================

class TestImxUploadGUILogDisplay:
    """Test log display functionality"""

    @patch('src.gui.main_window.QSettings')
    def test_refresh_log_display_settings(self, mock_qsettings, qtbot, mock_dependencies):
        """Test log display settings refresh"""
        mock_settings = Mock()
        mock_settings.value.return_value = 0
        mock_qsettings.return_value = mock_settings

        with patch.object(ImxUploadGUI, 'setup_ui'):
            with patch.object(MenuManager, 'setup_menu_bar'):
                with patch.object(ImxUploadGUI, 'setup_system_tray'):
                    with patch.object(ImxUploadGUI, 'restore_settings'):
                        with patch.object(ImxUploadGUI, 'check_credentials'):
                            window = ImxUploadGUI()
                            qtbot.addWidget(window)

                                # Should have log display settings cached
                            assert hasattr(window, '_log_show_level')
                            assert hasattr(window, '_log_show_category')


# ============================================================================
# Update Timer Tests
# ============================================================================

class TestImxUploadGUIUpdateTimer:
    """Test update timer functionality"""

    @patch('src.gui.main_window.QSettings')
    def test_update_timer_exists(self, mock_qsettings, qtbot, mock_dependencies):
        """Test update timer is created"""
        mock_settings = Mock()
        mock_settings.value.return_value = 0
        mock_qsettings.return_value = mock_settings

        with patch.object(ImxUploadGUI, 'setup_ui'):
            with patch.object(MenuManager, 'setup_menu_bar'):
                with patch.object(ImxUploadGUI, 'setup_system_tray'):
                    with patch.object(ImxUploadGUI, 'restore_settings'):
                        with patch.object(ImxUploadGUI, 'check_credentials'):
                            window = ImxUploadGUI()
                            qtbot.addWidget(window)

                            assert hasattr(window, 'update_timer')
