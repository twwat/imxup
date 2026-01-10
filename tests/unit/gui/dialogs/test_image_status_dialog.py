"""
Unit tests for ImageStatusDialog

Tests UI state management, spinner animation, timer cleanup,
results display, and gallery table functionality.

Target: 25-35 tests covering all major functionality.
"""

import os
import sys
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock
from typing import List

import pytest

# Ensure Qt uses offscreen platform for headless testing
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt, QTimer, QEventLoop
from PyQt6.QtWidgets import QApplication, QTableWidgetItem, QWidget
from PyQt6.QtGui import QColor, QCloseEvent

from src.gui.theme_manager import get_online_status_colors

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from src.gui.dialogs.image_status_dialog import ImageStatusDialog


class MockQtBot:
    """Simple mock for qtbot functionality without pytest-qt dependency."""

    def __init__(self, app: QApplication):
        self._app = app
        self._widgets: List[QWidget] = []

    def addWidget(self, widget: QWidget) -> None:
        """Track widget for cleanup."""
        self._widgets.append(widget)

    def wait(self, ms: int) -> None:
        """Wait for specified milliseconds, processing events."""
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def waitSignal(self, signal, timeout: int = 1000):
        """Context manager to wait for a signal."""
        return SignalWaiter(signal, timeout)

    def cleanup(self) -> None:
        """Clean up tracked widgets."""
        for widget in self._widgets:
            try:
                widget.close()
                widget.deleteLater()
            except RuntimeError:
                pass  # Widget already deleted
        self._widgets.clear()


class SignalWaiter:
    """Context manager for waiting on Qt signals."""

    def __init__(self, signal, timeout: int):
        self.signal = signal
        self.timeout = timeout
        self._received = False

    def __enter__(self):
        self._received = False
        self.signal.connect(self._on_signal)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.signal.disconnect(self._on_signal)
        if not self._received:
            # Process events briefly to allow signal to be emitted
            loop = QEventLoop()
            QTimer.singleShot(self.timeout, loop.quit)
            loop.exec()
        return False

    def _on_signal(self, *args):
        self._received = True


@pytest.fixture(scope='session')
def qapp() -> QApplication:
    """Session-scoped Qt Application fixture."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def qtbot(qapp) -> MockQtBot:
    """Mock qtbot fixture for widget testing."""
    bot = MockQtBot(qapp)
    yield bot
    bot.cleanup()


@pytest.fixture
def dialog(qtbot):
    """Create ImageStatusDialog for testing."""
    dlg = ImageStatusDialog()
    qtbot.addWidget(dlg)
    dlg.show()  # Show dialog so visibility tests work correctly
    return dlg


@pytest.fixture
def dialog_with_galleries(qtbot):
    """Create ImageStatusDialog with sample galleries."""
    dlg = ImageStatusDialog()
    qtbot.addWidget(dlg)

    galleries = [
        {
            "db_id": 1,
            "path": "/path/to/gallery1",
            "name": "Gallery One",
            "total_images": 10
        },
        {
            "db_id": 2,
            "path": "/path/to/gallery2",
            "name": "Gallery Two",
            "total_images": 5
        },
        {
            "db_id": 3,
            "path": "/path/to/gallery3",
            "name": "Gallery Three",
            "total_images": 20
        }
    ]

    dlg.set_galleries(galleries)
    dlg.show()  # Show dialog so visibility tests work correctly
    return dlg


class TestImageStatusDialogInitialization:
    """Test dialog initialization and setup."""

    def test_dialog_creation(self, dialog):
        """Test basic dialog creation."""
        assert dialog.windowTitle() == "Check Image Status - IMX.to"
        assert dialog.isModal()
        assert dialog.minimumWidth() == 750
        assert dialog.minimumHeight() == 450

    def test_table_columns(self, dialog):
        """Test table has correct columns."""
        assert dialog.table.columnCount() == 6
        headers = [
            dialog.table.horizontalHeaderItem(i).text()
            for i in range(6)
        ]
        assert headers == ["DB ID", "Name", "Images", "Online", "Offline", "Status"]

    def test_table_properties(self, dialog):
        """Test table properties are set correctly."""
        assert dialog.table.alternatingRowColors()
        assert dialog.table.isSortingEnabled()
        assert not dialog.table.verticalHeader().isVisible()

    def test_proportional_bars_exist(self, dialog):
        """Test proportional bars are created."""
        assert hasattr(dialog, 'images_bar')
        assert hasattr(dialog, 'galleries_bar')
        assert dialog.images_bar is not None
        assert dialog.galleries_bar is not None

    def test_status_labels_exist(self, dialog):
        """Test status labels are created."""
        assert hasattr(dialog, 'images_status_label')
        assert hasattr(dialog, 'galleries_status_label')
        assert hasattr(dialog, 'spinner_label')
        assert hasattr(dialog, 'elapsed_label')

    def test_statistics_widgets_exist(self, dialog):
        """Test statistics panel widgets are created."""
        assert hasattr(dialog, 'stat_galleries_scanned')
        assert hasattr(dialog, 'stat_images_checked')
        assert hasattr(dialog, 'stat_online_galleries')
        assert hasattr(dialog, 'stat_partial_galleries')
        assert hasattr(dialog, 'stat_offline_galleries')
        assert hasattr(dialog, 'stat_online_images')
        assert hasattr(dialog, 'stat_offline_images')

    def test_table_initially_hidden(self, dialog):
        """Test table is hidden initially until scan complete."""
        assert not dialog.table.isVisible()

    def test_cancel_button_initially_hidden(self, dialog):
        """Test cancel button is hidden initially."""
        assert not dialog.cancel_btn.isVisible()

    def test_close_button_initially_visible(self, dialog):
        """Test close button is visible initially."""
        assert dialog.close_btn.isVisible()

    def test_signals_defined(self, dialog):
        """Test signals are properly defined."""
        assert hasattr(dialog, 'check_requested')
        assert hasattr(dialog, 'cancelled')


class TestUIStateManagement:
    """Test UI state management for progress indicators."""

    def test_show_progress_shows_cancel_hides_close(self, dialog):
        """Test Cancel visible, Close hidden when running."""
        dialog.show_progress(True)

        assert dialog.cancel_btn.isVisible()
        assert dialog.cancel_btn.isEnabled()
        assert dialog.cancel_btn.text() == "Cancel"
        assert not dialog.close_btn.isVisible()

    def test_show_progress_false_hides_cancel_shows_close(self, dialog):
        """Test Cancel hidden, Close visible when idle."""
        # First show progress
        dialog.show_progress(True)
        # Then hide it
        dialog.show_progress(False)

        assert not dialog.cancel_btn.isVisible()
        assert dialog.close_btn.isVisible()

    def test_bars_indeterminate_during_progress(self, dialog):
        """Test proportional bars show indeterminate animation when running."""
        dialog.show_progress(True)

        assert dialog.images_bar._indeterminate
        assert dialog.galleries_bar._indeterminate

    def test_bars_stop_indeterminate_when_segments_set(self, dialog):
        """Test proportional bars stop animation when segments are set."""
        dialog.show_progress(True)
        assert dialog.images_bar._animation_timer.isActive()

        # Setting segments stops indeterminate mode
        colors = get_online_status_colors()
        dialog.images_bar.set_segments([
            (10, colors['online']),
            (5, colors['offline'])
        ])

        # Animation timer should be stopped
        assert not dialog.images_bar._animation_timer.isActive()
        assert not dialog.images_bar._indeterminate

    def test_status_labels_set_when_running(self, dialog):
        """Test status labels are set when running."""
        dialog.show_progress(True)

        assert dialog.images_status_label.text() == "Scanning..."
        assert dialog.galleries_status_label.text() == "Scanning..."
        assert dialog.spinner_label.text() == "Checking image status..."

    def test_elapsed_timer_starts_when_running(self, dialog):
        """Test elapsed timer starts when progress shown."""
        dialog.show_progress(True)

        assert dialog._elapsed_timer.isActive()
        assert dialog._start_time > 0

    def test_elapsed_timer_stops_when_hidden(self, dialog):
        """Test elapsed timer stops when progress hidden."""
        dialog.show_progress(True)
        dialog.show_progress(False)

        assert not dialog._elapsed_timer.isActive()


class TestProportionalBarAnimation:
    """Test proportional bar animation functionality."""

    def test_bars_animation_timers_start_when_indeterminate(self, dialog):
        """Test animation timers start in indeterminate mode."""
        dialog.show_progress(True)

        assert dialog.images_bar._animation_timer.isActive()
        assert dialog.galleries_bar._animation_timer.isActive()

    def test_bars_animation_timers_stop_when_segments_set(self, dialog):
        """Test animation timers stop when segments are set."""
        dialog.show_progress(True)
        assert dialog.images_bar._animation_timer.isActive()

        # Set segments (non-indeterminate mode)
        colors = get_online_status_colors()
        dialog.images_bar.set_segments([
            (10, colors['online']),
            (5, colors['offline'])
        ])

        assert not dialog.images_bar._animation_timer.isActive()
        assert not dialog.images_bar._indeterminate

    def test_bar_animation_offset_increments(self, dialog):
        """Test animation offset increments during animation."""
        dialog.show_progress(True)
        initial_offset = dialog.images_bar._animation_offset

        # Manually trigger animation
        dialog.images_bar._animate()

        # Offset should have changed
        assert dialog.images_bar._animation_offset != initial_offset

    def test_spinner_label_updates(self, dialog):
        """Test spinner label can be updated."""
        dialog.spinner_label.setText("Custom status text")

        assert dialog.spinner_label.text() == "Custom status text"


class TestTimerCleanup:
    """Test timer cleanup on dialog close."""

    def test_close_event_stops_timers(self, dialog):
        """Test all timers stopped in closeEvent."""
        dialog.show_progress(True)
        assert dialog._elapsed_timer.isActive()
        assert dialog.images_bar._animation_timer.isActive()

        # Close the dialog which triggers closeEvent
        dialog.close()

        assert not dialog._elapsed_timer.isActive()
        assert not dialog.images_bar._animation_timer.isActive()
        assert not dialog.galleries_bar._animation_timer.isActive()

    def test_reject_stops_timers(self, dialog):
        """Test all timers stopped in reject (ESC key)."""
        dialog.show_progress(True)
        assert dialog._elapsed_timer.isActive()
        assert dialog.images_bar._animation_timer.isActive()

        # Call reject (simulates ESC key)
        dialog.reject()

        assert not dialog._elapsed_timer.isActive()
        assert not dialog.images_bar._animation_timer.isActive()
        assert not dialog.galleries_bar._animation_timer.isActive()

    def test_timer_stopped_when_already_stopped(self, dialog):
        """Test stopping timer when it's already stopped doesn't raise."""
        # Timer should not be active initially
        assert not dialog._elapsed_timer.isActive()

        # This should not raise an exception
        dialog._elapsed_timer.stop()
        dialog.images_bar.stop_animation()
        dialog.galleries_bar.stop_animation()

        assert not dialog._elapsed_timer.isActive()


class TestResultsDisplay:
    """Test results display functionality."""

    def test_set_results_updates_statistics(self, dialog_with_galleries):
        """Test statistics panel updated with stats."""
        results = {
            "/path/to/gallery1": {
                "db_id": 1,
                "name": "Gallery One",
                "total": 10,
                "online": 8,
                "offline": 2,
                "online_urls": ["url1"] * 8,
                "offline_urls": ["url1", "url2"]
            },
            "/path/to/gallery2": {
                "db_id": 2,
                "name": "Gallery Two",
                "total": 5,
                "online": 5,
                "offline": 0,
                "online_urls": ["url1"] * 5,
                "offline_urls": []
            },
            "/path/to/gallery3": {
                "db_id": 3,
                "name": "Gallery Three",
                "total": 20,
                "online": 0,
                "offline": 20,
                "online_urls": [],
                "offline_urls": ["url1"] * 20
            }
        }

        dialog_with_galleries.set_results(results, elapsed_time=5.0)

        # Check statistics widgets were updated
        assert "3" in dialog_with_galleries.stat_galleries_scanned.value_label.text()
        assert "35" in dialog_with_galleries.stat_images_checked.value_label.text()
        assert "13" in dialog_with_galleries.stat_online_images.value_label.text()
        assert "22" in dialog_with_galleries.stat_offline_images.value_label.text()

        # Check elapsed time
        assert "5.0s" in dialog_with_galleries.elapsed_label.text()

    def test_set_results_shows_gallery_breakdown(self, dialog_with_galleries):
        """Test statistics show online/partial/offline breakdown."""
        results = {
            "/path/to/gallery1": {
                "db_id": 1, "name": "Gallery One",
                "total": 10, "online": 10, "offline": 0,
                "online_urls": [], "offline_urls": []
            },
            "/path/to/gallery2": {
                "db_id": 2, "name": "Gallery Two",
                "total": 5, "online": 3, "offline": 2,
                "online_urls": [], "offline_urls": []
            },
            "/path/to/gallery3": {
                "db_id": 3, "name": "Gallery Three",
                "total": 20, "online": 0, "offline": 20,
                "online_urls": [], "offline_urls": []
            }
        }

        dialog_with_galleries.set_results(results)

        # Check gallery breakdown statistics
        assert "1" in dialog_with_galleries.stat_online_galleries.value_label.text()
        assert "1" in dialog_with_galleries.stat_partial_galleries.value_label.text()
        assert "1" in dialog_with_galleries.stat_offline_galleries.value_label.text()

    def test_set_results_stops_timers(self, dialog_with_galleries):
        """Test timers stopped after results."""
        dialog_with_galleries.show_progress(True)
        assert dialog_with_galleries._elapsed_timer.isActive()

        results = {
            "/path/to/gallery1": {
                "db_id": 1, "name": "Gallery One",
                "total": 10, "online": 10, "offline": 0,
                "online_urls": [], "offline_urls": []
            }
        }

        dialog_with_galleries.set_results(results)

        assert not dialog_with_galleries._elapsed_timer.isActive()

    def test_set_results_shows_table(self, dialog_with_galleries):
        """Test table shown after results."""
        dialog_with_galleries.show_progress(True)
        assert not dialog_with_galleries.table.isVisible()

        results = {
            "/path/to/gallery1": {
                "db_id": 1, "name": "Gallery One",
                "total": 10, "online": 10, "offline": 0,
                "online_urls": [], "offline_urls": []
            }
        }

        dialog_with_galleries.set_results(results)

        assert dialog_with_galleries.table.isVisible()

    def test_set_results_shows_close_button(self, dialog_with_galleries):
        """Test Close button visible after results."""
        dialog_with_galleries.show_progress(True)

        results = {
            "/path/to/gallery1": {
                "db_id": 1, "name": "Gallery One",
                "total": 10, "online": 10, "offline": 0,
                "online_urls": [], "offline_urls": []
            }
        }

        dialog_with_galleries.set_results(results)

        assert dialog_with_galleries.close_btn.isVisible()
        assert not dialog_with_galleries.cancel_btn.isVisible()


class TestGalleryTable:
    """Test gallery table functionality."""

    def test_set_galleries_populates_table(self, dialog):
        """Test table rows created for galleries."""
        galleries = [
            {"db_id": 1, "path": "/path1", "name": "Gallery 1", "total_images": 10},
            {"db_id": 2, "path": "/path2", "name": "Gallery 2", "total_images": 5}
        ]

        dialog.set_galleries(galleries)

        assert dialog.table.rowCount() == 2

    def test_set_galleries_sets_db_id(self, dialog):
        """Test DB ID column is set correctly."""
        galleries = [
            {"db_id": 42, "path": "/path1", "name": "Gallery 1", "total_images": 10}
        ]

        dialog.set_galleries(galleries)

        id_item = dialog.table.item(0, 0)
        assert id_item.text() == "42"

    def test_set_galleries_sets_name(self, dialog):
        """Test Name column is set correctly."""
        galleries = [
            {"db_id": 1, "path": "/path1", "name": "Test Gallery Name", "total_images": 10}
        ]

        dialog.set_galleries(galleries)

        name_item = dialog.table.item(0, 1)
        assert name_item.text() == "Test Gallery Name"

    def test_set_galleries_sets_total_images(self, dialog):
        """Test Images column is set correctly."""
        galleries = [
            {"db_id": 1, "path": "/path1", "name": "Gallery", "total_images": 25}
        ]

        dialog.set_galleries(galleries)

        images_item = dialog.table.item(0, 2)
        assert images_item.text() == "25"

    def test_set_galleries_sets_pending_status(self, dialog):
        """Test initial status shows pending."""
        galleries = [
            {"db_id": 1, "path": "/path1", "name": "Gallery", "total_images": 10}
        ]

        dialog.set_galleries(galleries)

        online_item = dialog.table.item(0, 3)
        offline_item = dialog.table.item(0, 4)
        status_item = dialog.table.item(0, 5)

        # Online and Offline columns start at "0", status shows "Pending..."
        assert online_item.text() == "0"
        assert offline_item.text() == "0"
        assert status_item.text() == "Pending..."

    def test_set_galleries_stores_path_in_user_role(self, dialog):
        """Test gallery path stored in UserRole data."""
        galleries = [
            {"db_id": 1, "path": "/custom/path/gallery", "name": "Gallery", "total_images": 10}
        ]

        dialog.set_galleries(galleries)

        id_item = dialog.table.item(0, 0)
        path = id_item.data(Qt.ItemDataRole.UserRole)
        assert path == "/custom/path/gallery"

    def test_update_progress_is_noop(self, dialog):
        """Test update_progress exists for backward compatibility but is a no-op."""
        dialog.show_progress(True)

        # Should not raise (legacy method exists for backward compatibility)
        dialog.update_progress(5, 10)

        # Method exists but doesn't do anything in new UI

    def test_show_quick_count_updates_images_bar(self, dialog):
        """Test show_quick_count updates images bar with online/offline segments."""
        dialog.show_progress(True)

        dialog.show_quick_count(8, 10)

        # Images bar should now have segments (not indeterminate)
        assert not dialog.images_bar._indeterminate
        assert len(dialog.images_bar._segments) == 2
        assert dialog.images_bar._segments[0][0] == 8  # online count
        assert dialog.images_bar._segments[1][0] == 2  # offline count


class TestStatusColors:
    """Test status color coding in results."""

    def test_online_status_green(self, dialog_with_galleries):
        """Test fully online galleries show green status (theme-aware)."""
        results = {
            "/path/to/gallery1": {
                "db_id": 1, "name": "Gallery One",
                "total": 10, "online": 10, "offline": 0,
                "online_urls": [], "offline_urls": []
            }
        }

        dialog_with_galleries.set_results(results)

        # Get theme-aware colors
        colors = get_online_status_colors()
        status_item = dialog_with_galleries.table.item(0, 5)
        assert status_item.text() == "Online"
        assert status_item.foreground().color() == colors['online']

    def test_partial_status_orange(self, dialog_with_galleries):
        """Test partial galleries show amber status (theme-aware)."""
        results = {
            "/path/to/gallery1": {
                "db_id": 1, "name": "Gallery One",
                "total": 10, "online": 5, "offline": 5,
                "online_urls": [], "offline_urls": []
            }
        }

        dialog_with_galleries.set_results(results)

        # Get theme-aware colors
        colors = get_online_status_colors()
        status_item = dialog_with_galleries.table.item(0, 5)
        assert status_item.text() == "Partial"
        assert status_item.foreground().color() == colors['partial']

    def test_offline_status_red(self, dialog_with_galleries):
        """Test fully offline galleries show red status (theme-aware)."""
        results = {
            "/path/to/gallery1": {
                "db_id": 1, "name": "Gallery One",
                "total": 10, "online": 0, "offline": 10,
                "online_urls": [], "offline_urls": []
            }
        }

        dialog_with_galleries.set_results(results)

        # Get theme-aware colors
        colors = get_online_status_colors()
        status_item = dialog_with_galleries.table.item(0, 5)
        assert status_item.text() == "Offline"
        assert status_item.foreground().color() == colors['offline']

    def test_no_images_status_gray(self, dialog_with_galleries):
        """Test galleries with no images show gray status (theme-aware)."""
        results = {
            "/path/to/gallery1": {
                "db_id": 1, "name": "Gallery One",
                "total": 0, "online": 0, "offline": 0,
                "online_urls": [], "offline_urls": []
            }
        }

        dialog_with_galleries.set_results(results)

        # Get theme-aware colors
        colors = get_online_status_colors()
        status_item = dialog_with_galleries.table.item(0, 5)
        assert status_item.text() == "No images"
        assert status_item.foreground().color() == colors['gray']


class TestCancelFunctionality:
    """Test cancel button functionality."""

    def test_cancel_emits_signal(self, dialog, qtbot):
        """Test cancel button emits cancelled signal."""
        dialog.show_progress(True)

        signal_received = []

        def on_cancelled():
            signal_received.append(True)

        dialog.cancelled.connect(on_cancelled)
        dialog.cancel_btn.click()

        assert len(signal_received) == 1

    def test_cancel_disables_button(self, dialog):
        """Test cancel button is disabled after click."""
        dialog.show_progress(True)

        dialog._on_cancel()

        assert not dialog.cancel_btn.isEnabled()
        assert dialog.cancel_btn.text() == "Cancelling..."


class TestTimestampFunctions:
    """Test timestamp utility functions."""

    def test_get_checked_timestamp(self, dialog):
        """Test get_checked_timestamp returns valid timestamp."""
        timestamp = dialog.get_checked_timestamp()

        assert isinstance(timestamp, int)
        assert timestamp > 0
        # Should be close to current time (within 5 seconds)
        now = int(datetime.now().timestamp())
        assert abs(timestamp - now) < 5

    def test_format_check_datetime(self, dialog):
        """Test format_check_datetime returns expected format."""
        # Use a known timestamp (2025-01-05 12:30:00)
        timestamp = 1736076600

        formatted = dialog.format_check_datetime(timestamp)

        # Should be in YYYY-MM-DD HH:MM format
        assert len(formatted) == 16
        assert "-" in formatted
        assert ":" in formatted


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_galleries_list(self, dialog):
        """Test setting empty galleries list."""
        dialog.set_galleries([])

        assert dialog.table.rowCount() == 0

    def test_gallery_with_missing_keys(self, dialog):
        """Test gallery dict with missing keys uses defaults."""
        galleries = [
            {"path": "/path1"}  # Missing db_id, name, total_images
        ]

        # Should not raise
        dialog.set_galleries(galleries)

        assert dialog.table.rowCount() == 1
        assert dialog.table.item(0, 0).text() == "0"  # Default db_id
        assert dialog.table.item(0, 1).text() == ""   # Default name
        assert dialog.table.item(0, 2).text() == "0"  # Default total_images

    def test_results_for_unknown_path(self, dialog_with_galleries):
        """Test results for path not in table are ignored."""
        results = {
            "/unknown/path": {
                "db_id": 999, "name": "Unknown",
                "total": 10, "online": 10, "offline": 0,
                "online_urls": [], "offline_urls": []
            }
        }

        # Should not raise
        dialog_with_galleries.set_results(results)

        # Original rows should still show pending
        status_item = dialog_with_galleries.table.item(0, 5)
        assert status_item.text() == "Pending..."

    def test_zero_elapsed_time(self, dialog_with_galleries):
        """Test results with zero elapsed time doesn't divide by zero."""
        results = {
            "/path/to/gallery1": {
                "db_id": 1, "name": "Gallery One",
                "total": 10, "online": 10, "offline": 0,
                "online_urls": [], "offline_urls": []
            }
        }

        # Should not raise ZeroDivisionError
        dialog_with_galleries.set_results(results, elapsed_time=0.0)

        # Check elapsed label was updated
        assert "0.0s" in dialog_with_galleries.elapsed_label.text()
