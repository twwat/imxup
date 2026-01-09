#!/usr/bin/env python3
"""
pytest fixtures for GUI testing with pytest-qt
Provides common fixtures, mocks, and test utilities for all GUI test modules
"""

import os
import sys

# Ensure Qt uses offscreen platform for headless testing - must be set before QApplication import
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
import shutil
from pathlib import Path
from typing import Generator, Any
from unittest.mock import Mock, MagicMock, patch

import pytest
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QSettings, Qt, QThread
from PyQt6.QtGui import QIcon

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


@pytest.fixture(scope='session')
def qapp() -> QApplication:
    """
    Session-scoped Qt Application fixture.
    Creates a QApplication instance for all GUI tests.
    """
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app
    # Note: Don't quit the app here, pytest-qt handles cleanup


@pytest.fixture
def qapp_args() -> list:
    """Command-line arguments for QApplication"""
    return []


@pytest.fixture(autouse=True)
def mock_qmessagebox_for_tests(monkeypatch):
    """
    CRITICAL: Mock QMessageBox to prevent modal dialogs from blocking test teardown.

    Many dialogs show confirmation messages in closeEvent, which blocks pytest-qt's
    internal _close_widgets() function during teardown.

    This fixture auto-returns Discard for all warning/question dialogs.
    """
    from PyQt6.QtWidgets import QMessageBox

    # Store original methods
    original_warning = QMessageBox.warning
    original_question = QMessageBox.question
    original_information = QMessageBox.information
    original_critical = QMessageBox.critical

    # Create mock that returns Discard (to skip saving) or Yes (to proceed)
    def mock_warning(*args, **kwargs):
        return QMessageBox.StandardButton.Discard

    def mock_question(*args, **kwargs):
        return QMessageBox.StandardButton.Yes

    def mock_information(*args, **kwargs):
        return QMessageBox.StandardButton.Ok

    def mock_critical(*args, **kwargs):
        return QMessageBox.StandardButton.Ok

    # Patch all static dialog methods
    monkeypatch.setattr(QMessageBox, 'warning', mock_warning)
    monkeypatch.setattr(QMessageBox, 'question', mock_question)
    monkeypatch.setattr(QMessageBox, 'information', mock_information)
    monkeypatch.setattr(QMessageBox, 'critical', mock_critical)

    yield

    # monkeypatch auto-restores on teardown


@pytest.fixture(autouse=True)
def cleanup_qthreads():
    """
    Automatically cleanup any running QThreads after each test.
    This prevents "QThread: Destroyed while thread is still running" warnings
    and fixes pytest hanging issues.

    This is a critical fixture that runs after EVERY test to ensure no threads
    are left running.

    NOTE: This is a GUI-specific fixture. The main conftest.py also has
    cleanup_qt_resources which does more comprehensive cleanup.
    """
    # Before test: nothing to do, just yield
    yield

    # After test: Cleanup GUI-specific resources

    # 1. Close all open dialogs and windows
    app = QApplication.instance()
    if app is None:
        return

    # Close all dialogs first (they may have timers/threads)
    from PyQt6.QtWidgets import QDialog, QWidget
    for dialog in app.topLevelWidgets():
        if isinstance(dialog, QDialog) and dialog.isVisible():
            # Stop any timers in the dialog
            from PyQt6.QtCore import QTimer
            for timer in dialog.findChildren(QTimer):
                if timer.isActive():
                    timer.stop()

            # CRITICAL: Clear unsaved changes flag to prevent QMessageBox during close
            # This prevents modal dialogs from blocking test teardown
            if hasattr(dialog, 'has_unsaved_changes'):
                dialog.has_unsaved_changes = False

            # Close the dialog
            try:
                dialog.close()
                dialog.deleteLater()
            except Exception:
                pass

    # Process events to let dialogs close
    app.processEvents()

    # 2. Stop all QTimers
    from PyQt6.QtCore import QTimer
    for timer in app.findChildren(QTimer):
        if timer.isActive():
            timer.stop()

    app.processEvents()

    # 3. Get all QThread instances
    threads_to_cleanup = []
    for obj in app.findChildren(QThread):
        if obj.isRunning():
            threads_to_cleanup.append(obj)

    # 4. Stop each thread properly
    for thread in threads_to_cleanup:
        # Request stop if thread has stop method
        if hasattr(thread, 'stop') and callable(thread.stop):
            try:
                thread.stop()
            except Exception:
                pass  # Ignore errors during stop

        # Try to quit the thread event loop
        thread.quit()

        # Wait briefly for thread to finish (100ms max to avoid hanging)
        if not thread.wait(100):
            # If it didn't finish quickly, terminate it immediately
            thread.terminate()
            thread.wait(50)  # Short wait after terminate

    # 5. Process all pending deleteLater() calls
    app.sendPostedEvents(None, 0)  # 0 = QEvent.DeferredDelete
    app.processEvents()
    app.processEvents()  # Second pass


@pytest.fixture
def temp_config_dir(tmp_path) -> Generator[Path, None, None]:
    """
    Temporary configuration directory for testing.
    Creates a clean config directory that's cleaned up after tests.
    """
    config_dir = tmp_path / ".imxup"
    config_dir.mkdir(parents=True, exist_ok=True)
    yield config_dir
    # Cleanup handled by tmp_path


@pytest.fixture
def temp_assets_dir(tmp_path) -> Generator[Path, None, None]:
    """
    Temporary assets directory with mock icon files.
    Creates basic icon files for testing icon-related functionality.
    """
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    # Create some dummy icon files
    dummy_icons = [
        'status_completed-light.png',
        'status_completed-dark.png',
        'status_failed-light.png',
        'status_failed-dark.png',
        'action_start-light.png',
        'action_start-dark.png',
        'imxup.ico',
        'imxup.png',
    ]

    for icon_name in dummy_icons:
        icon_path = assets_dir / icon_name
        # Create a minimal 1x1 PNG file
        icon_path.write_bytes(
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01'
            b'\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89'
            b'\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01'
            b'\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
        )

    yield assets_dir


@pytest.fixture
def mock_qsettings(monkeypatch) -> Generator[Mock, None, None]:
    """
    Mock QSettings to avoid writing to actual system settings.
    Returns a mock that simulates QSettings behavior.
    Each test gets a fresh isolated dictionary to prevent pollution between tests.
    All instances within the same test share the same backing store (class variable).
    """
    # Create a fresh storage dict for this test
    # Use a list as a mutable container so we can swap the dict without losing reference
    shared_storage = [{}]

    class MockQSettings:
        def __init__(self, *args, **kwargs):
            # All instances within a test share the same dictionary
            # Expose it as .data so the test fixture can access it
            self.data = shared_storage[0]

        def value(self, key, default=None, type=None):
            val = shared_storage[0].get(key, default)
            if type is not None:
                if val is None:
                    # QSettings returns default type instances for None values
                    if type == list:
                        return []
                    elif type == str:
                        return ""
                    elif type == int:
                        return 0
                    elif type == bool:
                        return False
                    return default
                try:
                    return type(val)
                except (ValueError, TypeError):
                    return default
            return val

        def setValue(self, key, value):
            shared_storage[0][key] = value

        def remove(self, key):
            shared_storage[0].pop(key, None)

        def contains(self, key):
            return key in shared_storage[0]

        def clear(self):
            shared_storage[0].clear()

        def sync(self):
            pass

        def beginGroup(self, group):
            pass

        def endGroup(self):
            pass

    mock_settings = MockQSettings
    # Patch QSettings in PyQt6.QtCore AND in all modules that import it
    monkeypatch.setattr('PyQt6.QtCore.QSettings', mock_settings)
    monkeypatch.setattr('src.gui.widgets.worker_status_widget.QSettings', mock_settings)
    monkeypatch.setattr('src.gui.widgets.file_hosts_settings_widget.QSettings', mock_settings)
    monkeypatch.setattr('src.gui.widgets.tabbed_gallery.QSettings', mock_settings)
    # CRITICAL: Also patch in test modules that have already imported QSettings
    # Check sys.modules for already-loaded test modules
    import sys
    for module_name, module in list(sys.modules.items()):
        if module and 'test_' in module_name and hasattr(module, 'QSettings'):
            try:
                monkeypatch.setattr(f'{module_name}.QSettings', mock_settings)
            except (AttributeError, ModuleNotFoundError):
                pass  # Module structure doesn't allow patching
    yield mock_settings

    # Clear after test to prevent pollution (clearing the dict in-place)
    shared_storage[0].clear()


@pytest.fixture
def mock_icon_manager(temp_assets_dir) -> Mock:
    """
    Mock IconManager for testing GUI components that use icons.
    Returns a mock with basic icon functionality.
    """
    from src.gui.icon_manager import IconManager

    icon_manager = Mock(spec=IconManager)
    icon_manager.assets_dir = str(temp_assets_dir)
    icon_manager.get_icon.return_value = QIcon()
    icon_manager.get_status_icon.return_value = QIcon()
    icon_manager.get_action_icon.return_value = QIcon()
    icon_manager.validate_icons.return_value = {'missing': [], 'found': []}

    return icon_manager


@pytest.fixture
def mock_queue_store() -> Mock:
    """
    Mock QueueStore for testing components that interact with the database.
    Returns a mock with common database operations.
    """
    from src.storage.database import QueueStore

    queue_store = Mock(spec=QueueStore)
    queue_store.get_all_tabs.return_value = [
        {'id': 1, 'name': 'Main', 'tab_type': 'system', 'display_order': 0,
         'color_hint': None, 'created_ts': 0, 'updated_ts': 0, 'is_active': True}
    ]
    # Note: get_tab_by_name doesn't exist on QueueStore - use get_all_tabs and filter
    queue_store.create_tab.return_value = 2
    queue_store.delete_tab.return_value = True
    queue_store.load_items_by_tab.return_value = []  # Correct method name

    return queue_store


@pytest.fixture
def mock_queue_manager() -> Mock:
    """
    Mock QueueManager for testing upload-related functionality.
    Returns a mock with queue management operations.
    """
    from src.storage.queue_manager import QueueManager

    # Use Mock without spec to allow any attribute access
    queue_manager = Mock()
    queue_manager.get_all_items.return_value = []
    queue_manager.get_item.return_value = None
    queue_manager.add_item.return_value = True
    queue_manager.update_item_status.return_value = True
    queue_manager.remove_item.return_value = True

    return queue_manager


@pytest.fixture
def mock_config_file(temp_config_dir) -> Generator[Path, None, None]:
    """
    Create a temporary imxup.ini config file for testing.
    Returns path to the config file.
    """
    import configparser

    config_path = temp_config_dir / "imxup.ini"
    config = configparser.ConfigParser()

    config['credentials'] = {
        'username': '',
        'password': '',
        'api_key': '',
    }

    config['templates'] = {
        'default': '[b]{name}[/b]',
    }

    config['scanning'] = {
        'fast_scan_enabled': 'true',
        'fast_scan_sample_size': '10',
        'use_file_exclusion': 'false',
    }

    config['upload'] = {
        'timeout': '30',
        'retries': '3',
        'batch_size': '5',
    }

    with open(config_path, 'w') as f:
        config.write(f)

    yield config_path


@pytest.fixture
def mock_imxup_functions(monkeypatch):
    """
    Mock core imxup functions to avoid external dependencies.
    Patches common functions from the imxup module.
    """
    # Mock credential functions
    monkeypatch.setattr('imxup.get_credential', lambda x: None)
    monkeypatch.setattr('imxup.set_credential', lambda x, y: True)
    monkeypatch.setattr('imxup.remove_credential', lambda x: True)
    monkeypatch.setattr('imxup.encrypt_password', lambda x: f"encrypted_{x}")
    monkeypatch.setattr('imxup.decrypt_password', lambda x: x.replace("encrypted_", ""))

    # Mock path functions
    monkeypatch.setattr('imxup.get_config_path', lambda: '/tmp/.imxup')
    monkeypatch.setattr('imxup.get_project_root', lambda: '/tmp/imxup')

    # Mock version function
    monkeypatch.setattr('imxup.get_version', lambda: '1.0.0-test')


@pytest.fixture
def sample_gallery_data() -> dict:
    """
    Sample gallery data for testing table and queue operations.
    """
    return {
        'id': 'test-gallery-123',
        'name': 'Test Gallery',
        'path': '/tmp/test/gallery',
        'status': 'ready',
        'progress': 0,
        'total_files': 10,
        'uploaded_files': 0,
        'total_size': 1024000,
        'uploaded_size': 0,
        'tab_name': 'Main',
        'template': 'default',
        'renamed': False,
        'created_ts': 1700000000,
        'updated_ts': 1700000000,
    }


@pytest.fixture
def qtbot_skip_slow(qtbot):
    """
    Enhanced qtbot that skips slow tests in CI.
    Useful for marking tests that should run locally but not in CI.
    """
    import os
    if os.getenv('CI') or os.getenv('GITHUB_ACTIONS'):
        pytest.skip("Skipping slow test in CI environment")
    return qtbot


class MockLogger:
    """Mock logger for testing log-related functionality"""

    def __init__(self):
        self.messages = []

    def info(self, msg, *args, **kwargs):
        self.messages.append(('info', msg))

    def warning(self, msg, *args, **kwargs):
        self.messages.append(('warning', msg))

    def error(self, msg, *args, **kwargs):
        self.messages.append(('error', msg))

    def debug(self, msg, *args, **kwargs):
        self.messages.append(('debug', msg))

    def clear(self):
        self.messages.clear()


@pytest.fixture
def mock_logger() -> MockLogger:
    """Mock logger instance for testing"""
    return MockLogger()


# Utility functions for tests

def wait_for_signal(signal, timeout=1000):
    """
    Helper to wait for a Qt signal with timeout.
    Usage: wait_for_signal(widget.signal_name, timeout=2000)
    """
    from PyQt6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    signal.connect(loop.quit)
    QTimer.singleShot(timeout, loop.quit)
    loop.exec()


def trigger_action(widget, action_name):
    """
    Helper to trigger a QAction by name.
    Usage: trigger_action(menu, 'Open File')
    """
    for action in widget.actions():
        if action.text() == action_name:
            action.trigger()
            return True
    return False
