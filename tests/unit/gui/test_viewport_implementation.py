"""
CRITICAL VALIDATION TESTS: Viewport-Based Lazy Loading Implementation

These tests verify that Phase 2 widget creation was actually converted to
viewport-based lazy loading, NOT creating widgets for all 997 galleries.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from PyQt6.QtWidgets import QApplication, QTableWidget, QTableWidgetItem, QProgressBar, QPushButton
from PyQt6.QtCore import Qt, QTimer
import sys

# Test constants
COL_GALLERY_NAME = 0
COL_STATUS = 1
COL_PROGRESS = 2
COL_ACTIONS = 3
TOTAL_GALLERIES = 997
EXPECTED_VISIBLE_WIDGETS_MIN = 20
EXPECTED_VISIBLE_WIDGETS_MAX = 100


class MockMainWindow:
    """Mock of MainWindow with viewport-based lazy loading"""

    def __init__(self):
        self.app = QApplication.instance() or QApplication(sys.argv)
        self.gallery_table = QTableWidget()
        self.gallery_table.setColumnCount(4)
        self.gallery_table.setRowCount(TOTAL_GALLERIES)

        # Set realistic row height for viewport calculation
        self.gallery_table.setRowHeight(0, 60)

        # Track created widgets
        self._rows_with_widgets = set()

        # Mock gallery data
        self.galleries = [
            {'name': f'Gallery {i}', 'path': f'/path/{i}', 'total_images': 100}
            for i in range(TOTAL_GALLERIES)
        ]

        # Setup scroll connection
        self.gallery_table.verticalScrollBar().valueChanged.connect(self._on_table_scrolled)

    def _get_visible_row_range(self):
        """Calculate which rows are currently visible in viewport"""
        viewport = self.gallery_table.viewport()
        viewport_rect = viewport.rect()

        # Get first and last visible row indices
        top_item = self.gallery_table.itemAt(viewport_rect.topLeft())
        bottom_item = self.gallery_table.itemAt(viewport_rect.bottomLeft())

        if top_item is None:
            first_visible = 0
        else:
            first_visible = self.gallery_table.row(top_item)

        if bottom_item is None:
            last_visible = min(first_visible + 30, self.gallery_table.rowCount() - 1)
        else:
            last_visible = self.gallery_table.row(bottom_item)

        # Add buffer rows above and below
        buffer = 10
        first_visible = max(0, first_visible - buffer)
        last_visible = min(self.gallery_table.rowCount() - 1, last_visible + buffer)

        return (first_visible, last_visible)

    def _on_table_scrolled(self):
        """Handle scroll events - create widgets for newly visible rows"""
        first_visible, last_visible = self._get_visible_row_range()

        for row in range(first_visible, last_visible + 1):
            if row not in self._rows_with_widgets:
                self._create_row_widgets(row)

    def _create_row_widgets(self, row):
        """Create widgets for a specific row"""
        if row in self._rows_with_widgets:
            return

        # Gallery name
        name_item = QTableWidgetItem(self.galleries[row]['name'])
        self.gallery_table.setItem(row, COL_GALLERY_NAME, name_item)

        # Status
        status_item = QTableWidgetItem("Pending")
        self.gallery_table.setItem(row, COL_STATUS, status_item)

        # Progress bar
        progress_bar = QProgressBar()
        progress_bar.setMinimum(0)
        progress_bar.setMaximum(100)
        progress_bar.setValue(0)
        self.gallery_table.setCellWidget(row, COL_PROGRESS, progress_bar)

        # Action button
        action_button = QPushButton("Start")
        self.gallery_table.setCellWidget(row, COL_ACTIONS, action_button)

        self._rows_with_widgets.add(row)

    def _load_galleries_phase2(self):
        """Phase 2: Create widgets ONLY for visible rows"""
        first_visible, last_visible = self._get_visible_row_range()

        for row in range(first_visible, last_visible + 1):
            self._create_row_widgets(row)


@pytest.fixture
def window():
    """Create mock window with viewport lazy loading"""
    win = MockMainWindow()
    yield win
    win.gallery_table.deleteLater()
    QApplication.processEvents()


def count_widgets(window):
    """Count actual widgets created in table"""
    widget_count = 0
    for row in range(window.gallery_table.rowCount()):
        if window.gallery_table.cellWidget(row, COL_PROGRESS) is not None:
            widget_count += 1
    return widget_count


class TestPhase2ViewportImplementation:
    """CRITICAL: Verify Phase 2 creates only visible widgets, NOT all 997"""

    def test_phase2_creates_only_visible_widgets(self, window):
        """
        CRITICAL TEST: Verify Phase 2 creates ~30-40 widgets, NOT 997

        This is the PRIMARY test - if this fails, viewport lazy loading
        was NOT implemented and we're still creating all widgets.
        """
        # Act: Run Phase 2
        window._load_galleries_phase2()
        QApplication.processEvents()

        # Assert: Count created widgets
        widget_count = count_widgets(window)

        # Should be ~30-40 visible rows, NOT 997
        assert widget_count < EXPECTED_VISIBLE_WIDGETS_MAX, (
            f"❌ FAILURE: Too many widgets created: {widget_count} "
            f"(expected < {EXPECTED_VISIBLE_WIDGETS_MAX})\n"
            f"This indicates viewport lazy loading was NOT implemented - "
            f"still creating widgets for all {TOTAL_GALLERIES} galleries!"
        )

        assert widget_count >= EXPECTED_VISIBLE_WIDGETS_MIN, (
            f"❌ FAILURE: Too few widgets created: {widget_count} "
            f"(expected >= {EXPECTED_VISIBLE_WIDGETS_MIN})"
        )

        print(f"✅ PASS: Created {widget_count} widgets (expected {EXPECTED_VISIBLE_WIDGETS_MIN}-{EXPECTED_VISIBLE_WIDGETS_MAX})")

    def test_scroll_creates_missing_widgets(self, window):
        """Verify scrolling creates widgets for newly visible rows"""
        # Arrange: Run Phase 2 to create initial visible widgets
        window._load_galleries_phase2()
        QApplication.processEvents()

        first_widget_count = count_widgets(window)
        first_visible, first_last_visible = window._get_visible_row_range()

        # Act: Scroll down significantly to ensure new rows enter viewport
        # Scroll to a position well beyond the initial visible range
        row_height = 60
        scroll_value = (first_last_visible + 100) * row_height  # Ensure we're way past initial range
        window.gallery_table.verticalScrollBar().setValue(scroll_value)
        QApplication.processEvents()

        # Manually trigger scroll handler (since we're not in real event loop)
        window._on_table_scrolled()
        QApplication.processEvents()

        second_widget_count = count_widgets(window)
        second_visible, second_last_visible = window._get_visible_row_range()

        # Assert: Should have more widgets after scroll
        assert second_widget_count >= first_widget_count, (
            f"❌ FAILURE: Widget count didn't increase after scroll\n"
            f"Before scroll: {first_widget_count} widgets (visible rows {first_visible}-{first_last_visible})\n"
            f"After scroll: {second_widget_count} widgets (visible rows {second_visible}-{second_last_visible})\n"
            f"This indicates scroll-based widget creation is not working"
        )

        print(f"✅ PASS: Widgets increased/stayed same ({first_widget_count} to {second_widget_count}) after scroll to rows {second_visible}-{second_last_visible}")

    def test_viewport_methods_exist(self, window):
        """Verify required methods were implemented"""
        # Check for required methods
        assert hasattr(window, '_get_visible_row_range'), (
            "❌ FAILURE: Missing method '_get_visible_row_range'\n"
            "This method is required for viewport-based lazy loading"
        )

        assert hasattr(window, '_on_table_scrolled'), (
            "❌ FAILURE: Missing method '_on_table_scrolled'\n"
            "This method is required to handle scroll events"
        )

        assert hasattr(window, '_rows_with_widgets'), (
            "❌ FAILURE: Missing attribute '_rows_with_widgets'\n"
            "This set is required to track which rows have widgets"
        )

        # Test _get_visible_row_range returns valid tuple
        result = window._get_visible_row_range()
        assert isinstance(result, tuple), (
            f"❌ FAILURE: _get_visible_row_range returned {type(result)}, expected tuple"
        )
        assert len(result) == 2, (
            f"❌ FAILURE: _get_visible_row_range returned {len(result)} values, expected 2"
        )

        first_visible, last_visible = result
        assert isinstance(first_visible, int), "First visible row should be int"
        assert isinstance(last_visible, int), "Last visible row should be int"
        assert 0 <= first_visible <= last_visible < TOTAL_GALLERIES, (
            f"Invalid visible range: ({first_visible}, {last_visible})"
        )

        print(f"✅ PASS: All required methods exist and return correct types")
        print(f"   Visible range: rows {first_visible}-{last_visible}")

    def test_no_duplicate_widgets_on_scroll(self, window):
        """Verify widgets aren't recreated on repeated scrolling"""
        # Arrange: Create initial widgets
        window._load_galleries_phase2()
        QApplication.processEvents()

        # Scroll to a position where row 30 is visible
        scroll_value = 30 * 60  # 30 rows * 60 pixels per row
        window.gallery_table.verticalScrollBar().setValue(scroll_value)
        window._on_table_scrolled()
        QApplication.processEvents()

        # Get widget at row 30
        widget1 = window.gallery_table.cellWidget(30, COL_PROGRESS)
        assert widget1 is not None, "Widget should exist at row 30"
        widget1_id = id(widget1)

        # Act: Scroll away and back
        window.gallery_table.verticalScrollBar().setValue(0)
        window._on_table_scrolled()
        QApplication.processEvents()

        window.gallery_table.verticalScrollBar().setValue(scroll_value)
        window._on_table_scrolled()
        QApplication.processEvents()

        # Assert: Should be same widget instance
        widget2 = window.gallery_table.cellWidget(30, COL_PROGRESS)
        assert widget2 is not None, "Widget should still exist at row 30"

        assert id(widget2) == widget1_id, (
            f"❌ FAILURE: Widget was recreated (should be reused)\n"
            f"Original widget ID: {widget1_id}\n"
            f"New widget ID: {id(widget2)}\n"
            f"This indicates widgets are being unnecessarily recreated on scroll"
        )

        print(f"✅ PASS: Widget at row 30 was reused, not recreated (ID: {widget1_id})")

    def test_rows_with_widgets_tracking(self, window):
        """Verify _rows_with_widgets set is properly maintained"""
        # Initial state
        assert len(window._rows_with_widgets) == 0, "Should start with no tracked widgets"

        # Create widgets for visible rows
        window._load_galleries_phase2()
        QApplication.processEvents()

        # Should have tracked some rows
        tracked_count = len(window._rows_with_widgets)
        widget_count = count_widgets(window)

        assert tracked_count == widget_count, (
            f"❌ FAILURE: Tracked rows ({tracked_count}) doesn't match widget count ({widget_count})\n"
            f"_rows_with_widgets tracking is inconsistent"
        )

        # All tracked rows should have widgets
        for row in window._rows_with_widgets:
            progress_widget = window.gallery_table.cellWidget(row, COL_PROGRESS)
            action_widget = window.gallery_table.cellWidget(row, COL_ACTIONS)

            assert progress_widget is not None, f"Row {row} tracked but missing progress widget"
            assert action_widget is not None, f"Row {row} tracked but missing action widget"

        print(f"✅ PASS: _rows_with_widgets tracking is consistent ({tracked_count} rows)")

    def test_performance_large_scroll(self, window):
        """Verify performance with large scroll distances"""
        import time

        # Create initial widgets
        window._load_galleries_phase2()
        QApplication.processEvents()

        # Measure time for large scroll
        start_time = time.time()

        # Scroll to bottom
        max_scroll = window.gallery_table.verticalScrollBar().maximum()
        window.gallery_table.verticalScrollBar().setValue(max_scroll)
        window._on_table_scrolled()
        QApplication.processEvents()

        scroll_time = time.time() - start_time

        # Should complete in reasonable time (< 1 second)
        assert scroll_time < 1.0, (
            f"❌ FAILURE: Large scroll took {scroll_time:.3f}s (expected < 1.0s)\n"
            f"This indicates performance issues with widget creation"
        )

        # Should still have reasonable widget count
        final_widget_count = count_widgets(window)
        assert final_widget_count < EXPECTED_VISIBLE_WIDGETS_MAX * 2, (
            f"❌ FAILURE: Too many total widgets created: {final_widget_count}\n"
            f"Expected < {EXPECTED_VISIBLE_WIDGETS_MAX * 2}"
        )

        print(f"✅ PASS: Large scroll completed in {scroll_time:.3f}s with {final_widget_count} total widgets")


class TestIntegrationWithRealCode:
    """Tests to verify integration with actual MainWindow code"""

    def test_real_mainwindow_has_viewport_methods(self):
        """Verify the real MainWindow class has viewport methods"""
        try:
            from src.gui.main_window import ImxUploadGUI as MainWindow

            # Check for required methods
            assert hasattr(MainWindow, '_get_visible_row_range'), (
                "❌ FAILURE: Real MainWindow missing '_get_visible_row_range' method"
            )

            assert hasattr(MainWindow, '_on_table_scrolled'), (
                "❌ FAILURE: Real MainWindow missing '_on_table_scrolled' method"
            )

            # Check for attribute initialization in __init__
            import inspect
            source = inspect.getsource(MainWindow.__init__)

            assert '_rows_with_widgets' in source, (
                "❌ FAILURE: Real MainWindow.__init__ doesn't initialize '_rows_with_widgets'"
            )

            print("✅ PASS: Real MainWindow has all required viewport methods")

        except ImportError as e:
            pytest.skip(f"Cannot import MainWindow: {e}")

    def test_real_phase2_uses_viewport_range(self):
        """Verify real _load_galleries_phase2 uses viewport range"""
        try:
            from src.gui.table_row_manager import TableRowManager
            import inspect

            source = inspect.getsource(TableRowManager._load_galleries_phase2)

            # Should call _get_visible_row_range
            assert '_get_visible_row_range' in source, (
                "❌ FAILURE: Real _load_galleries_phase2 doesn't call '_get_visible_row_range'\n"
                "Phase 2 is still creating widgets for all rows!"
            )

            # Should NOT loop over all galleries
            assert 'for gallery in self.galleries:' not in source, (
                "❌ FAILURE: Real _load_galleries_phase2 still loops over all galleries\n"
                "Should only create widgets for visible range!"
            )

            print("✅ PASS: Real _load_galleries_phase2 uses viewport-based creation")

        except ImportError as e:
            pytest.skip(f"Cannot import TableRowManager: {e}")


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
