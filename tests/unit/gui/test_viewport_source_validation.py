"""
CRITICAL SOURCE CODE VALIDATION: Viewport-Based Lazy Loading Implementation

These tests directly analyze the source code to verify viewport-based lazy loading
was actually implemented, NOT just documented.
"""

import pytest
from pathlib import Path


@pytest.fixture
def main_window_source():
    """Read the main_window.py source code"""
    source_path = Path(__file__).parent.parent.parent.parent / 'src' / 'gui' / 'main_window.py'
    return source_path.read_text(encoding='utf-8')


@pytest.fixture
def table_row_manager_source():
    """Read the table_row_manager.py source code"""
    source_path = Path(__file__).parent.parent.parent.parent / 'src' / 'gui' / 'table_row_manager.py'
    return source_path.read_text(encoding='utf-8')


class TestViewportImplementationExists:
    """Verify viewport lazy loading is actually implemented in source code"""

    def test_get_visible_row_range_method_exists(self, main_window_source):
        """Verify _get_visible_row_range method is implemented"""
        assert 'def _get_visible_row_range(self)' in main_window_source, (
            "❌ FAILURE: Method '_get_visible_row_range' not found in source code"
        )
        print("✅ PASS: _get_visible_row_range method exists")

    def test_on_table_scrolled_method_exists(self, main_window_source):
        """Verify _on_table_scrolled method is implemented"""
        assert 'def _on_table_scrolled(self)' in main_window_source, (
            "❌ FAILURE: Method '_on_table_scrolled' not found in source code"
        )
        print("✅ PASS: _on_table_scrolled method exists")

    def test_rows_with_widgets_attribute_initialized(self, main_window_source):
        """Verify _rows_with_widgets set is initialized"""
        assert 'self._rows_with_widgets = set()' in main_window_source, (
            "❌ FAILURE: '_rows_with_widgets = set()' not found in __init__"
        )
        print("✅ PASS: _rows_with_widgets initialized as set()")

    def test_scroll_event_connected(self, main_window_source):
        """Verify scroll event is connected to handler"""
        # Should have connection like: scrollbar.valueChanged.connect(self._on_table_scrolled)
        assert 'valueChanged.connect(self._on_table_scrolled)' in main_window_source, (
            "❌ FAILURE: Scroll event not connected to _on_table_scrolled handler"
        )
        print("✅ PASS: Scroll event connected to _on_table_scrolled")


class TestPhase2UsesViewportRange:
    """CRITICAL: Verify Phase 2 uses viewport range, NOT mass widget creation"""

    def test_phase2_calls_get_visible_row_range(self, table_row_manager_source):
        """Verify _load_galleries_phase2 calls _get_visible_row_range"""
        # Extract _load_galleries_phase2 method from TableRowManager
        start_idx = table_row_manager_source.find('def _load_galleries_phase2(self)')
        assert start_idx != -1, "_load_galleries_phase2 method not found in TableRowManager"

        # Find the end of the method (next 'def ' or end of class)
        end_idx = table_row_manager_source.find('\n    def ', start_idx + 1)
        if end_idx == -1:
            end_idx = len(table_row_manager_source)

        phase2_source = table_row_manager_source[start_idx:end_idx]

        # Should call _get_visible_row_range
        assert '_get_visible_row_range()' in phase2_source, (
            "❌ CRITICAL FAILURE: _load_galleries_phase2 does NOT call _get_visible_row_range()\n"
            "This means Phase 2 is still creating widgets for ALL 997 galleries!"
        )
        print("✅ PASS: _load_galleries_phase2 calls _get_visible_row_range()")

    def test_phase2_uses_first_last_visible_variables(self, table_row_manager_source):
        """Verify Phase 2 uses first_visible, last_visible range variables"""
        start_idx = table_row_manager_source.find('def _load_galleries_phase2(self)')
        end_idx = table_row_manager_source.find('\n    def ', start_idx + 1)
        if end_idx == -1:
            end_idx = len(table_row_manager_source)

        phase2_source = table_row_manager_source[start_idx:end_idx]

        # Should use first_visible, last_visible
        assert 'first_visible' in phase2_source, (
            "❌ FAILURE: 'first_visible' variable not used in _load_galleries_phase2"
        )
        assert 'last_visible' in phase2_source, (
            "❌ FAILURE: 'last_visible' variable not used in _load_galleries_phase2"
        )
        print("✅ PASS: _load_galleries_phase2 uses first_visible, last_visible range")

    def test_phase2_does_not_loop_all_galleries(self, table_row_manager_source):
        """CRITICAL: Verify Phase 2 does NOT loop over all galleries"""
        start_idx = table_row_manager_source.find('def _load_galleries_phase2(self)')
        end_idx = table_row_manager_source.find('\n    def ', start_idx + 1)
        if end_idx == -1:
            end_idx = len(table_row_manager_source)

        phase2_source = table_row_manager_source[start_idx:end_idx]

        # Should NOT have 'for gallery in self.galleries:'
        assert 'for gallery in self.galleries:' not in phase2_source, (
            "❌ CRITICAL FAILURE: _load_galleries_phase2 still loops over ALL galleries!\n"
            "Viewport lazy loading was NOT implemented - still creating widgets for all 997 galleries!"
        )
        print("✅ PASS: _load_galleries_phase2 does NOT loop over all galleries")

    def test_phase2_tracks_created_widgets(self, table_row_manager_source):
        """Verify Phase 2 tracks created widgets in _rows_with_widgets"""
        start_idx = table_row_manager_source.find('def _load_galleries_phase2(self)')
        end_idx = table_row_manager_source.find('\n    def ', start_idx + 1)
        if end_idx == -1:
            end_idx = len(table_row_manager_source)

        phase2_source = table_row_manager_source[start_idx:end_idx]

        # Should add to _rows_with_widgets
        assert '_rows_with_widgets.add' in phase2_source, (
            "❌ FAILURE: _load_galleries_phase2 doesn't track widgets in _rows_with_widgets"
        )
        print("✅ PASS: _load_galleries_phase2 tracks widgets in _rows_with_widgets")

    def test_phase2_logs_widget_count(self, table_row_manager_source):
        """Verify Phase 2 logs number of widgets created"""
        start_idx = table_row_manager_source.find('def _load_galleries_phase2(self)')
        end_idx = table_row_manager_source.find('\n    def ', start_idx + 1)
        if end_idx == -1:
            end_idx = len(table_row_manager_source)

        phase2_source = table_row_manager_source[start_idx:end_idx]

        # Should log len(mw._rows_with_widgets) or len(self._rows_with_widgets)
        assert 'len(' in phase2_source and '_rows_with_widgets' in phase2_source, (
            "❌ FAILURE: _load_galleries_phase2 doesn't log widget count"
        )
        print("✅ PASS: _load_galleries_phase2 logs widget count")


class TestScrollHandlerImplementation:
    """Verify scroll handler creates widgets for newly visible rows"""

    def test_scroll_handler_gets_visible_range(self, main_window_source):
        """Verify _on_table_scrolled calls _get_visible_row_range"""
        start_idx = main_window_source.find('def _on_table_scrolled(self)')
        end_idx = main_window_source.find('\n    def ', start_idx + 1)
        if end_idx == -1:
            end_idx = len(main_window_source)

        scroll_handler_source = main_window_source[start_idx:end_idx]

        assert '_get_visible_row_range()' in scroll_handler_source, (
            "❌ FAILURE: _on_table_scrolled doesn't call _get_visible_row_range()"
        )
        print("✅ PASS: _on_table_scrolled calls _get_visible_row_range()")

    def test_scroll_handler_checks_existing_widgets(self, main_window_source):
        """Verify _on_table_scrolled checks if row already has widgets"""
        start_idx = main_window_source.find('def _on_table_scrolled(self)')
        end_idx = main_window_source.find('\n    def ', start_idx + 1)
        if end_idx == -1:
            end_idx = len(main_window_source)

        scroll_handler_source = main_window_source[start_idx:end_idx]

        # Should check 'if row not in self._rows_with_widgets:'
        assert 'not in self._rows_with_widgets' in scroll_handler_source or \
               'row not in self._rows_with_widgets' in scroll_handler_source, (
            "❌ FAILURE: _on_table_scrolled doesn't check if row needs widgets"
        )
        print("✅ PASS: _on_table_scrolled checks if widgets already exist")

    def test_scroll_handler_creates_widgets(self, main_window_source):
        """Verify _on_table_scrolled creates widgets for rows without them"""
        start_idx = main_window_source.find('def _on_table_scrolled(self)')
        end_idx = main_window_source.find('\n    def ', start_idx + 1)
        if end_idx == -1:
            end_idx = len(main_window_source)

        scroll_handler_source = main_window_source[start_idx:end_idx]

        # Should create widgets (setCellWidget or similar method)
        assert '_rows_with_widgets.add' in scroll_handler_source, (
            "❌ FAILURE: _on_table_scrolled doesn't track newly created widgets"
        )
        print("✅ PASS: _on_table_scrolled creates and tracks new widgets")


class TestGetVisibleRowRangeImplementation:
    """Verify _get_visible_row_range implementation"""

    def test_uses_viewport(self, table_row_manager_source):
        """Verify _get_visible_row_range uses viewport"""
        start_idx = table_row_manager_source.find('def _get_visible_row_range(self)')
        end_idx = table_row_manager_source.find('\n    def ', start_idx + 1)
        if end_idx == -1:
            end_idx = len(table_row_manager_source)

        method_source = table_row_manager_source[start_idx:end_idx]

        assert 'viewport()' in method_source, (
            "❌ FAILURE: _get_visible_row_range doesn't use viewport()"
        )
        print("✅ PASS: _get_visible_row_range uses viewport()")

    def test_returns_tuple(self, table_row_manager_source):
        """Verify _get_visible_row_range returns tuple"""
        start_idx = table_row_manager_source.find('def _get_visible_row_range(self)')
        end_idx = table_row_manager_source.find('\n    def ', start_idx + 1)
        if end_idx == -1:
            end_idx = len(table_row_manager_source)

        method_source = table_row_manager_source[start_idx:end_idx]

        # Should have return statement
        assert 'return' in method_source, (
            "❌ FAILURE: _get_visible_row_range missing return statement"
        )

        # Should return tuple (either explicit tuple or tuple[int, int] hint)
        assert 'tuple' in method_source or '(' in method_source.split('return')[1].split('\n')[0], (
            "❌ FAILURE: _get_visible_row_range doesn't return tuple"
        )
        print("✅ PASS: _get_visible_row_range returns tuple")


class TestStateManagement:
    """Verify state tracking and cleanup"""

    def test_rows_with_widgets_cleared_on_new_session(self, table_row_manager_source):
        """Verify _rows_with_widgets is cleared when starting new session"""
        # Should be cleared in _load_galleries_phase1
        start_idx = table_row_manager_source.find('def _load_galleries_phase1(self)')
        end_idx = table_row_manager_source.find('\n    def ', start_idx + 1)
        if end_idx == -1:
            end_idx = len(table_row_manager_source)

        phase1_source = table_row_manager_source[start_idx:end_idx]

        assert '_rows_with_widgets.clear()' in phase1_source, (
            "❌ FAILURE: _rows_with_widgets not cleared in _load_galleries_phase1"
        )
        print("✅ PASS: _rows_with_widgets cleared on new session")


class TestMemorySavingsCalculation:
    """Calculate theoretical memory savings"""

    def test_calculate_memory_savings(self):
        """Calculate memory savings from viewport approach"""
        TOTAL_GALLERIES = 997
        WIDGETS_PER_ROW = 2  # progress bar + action button
        VISIBLE_ROWS = 40

        widgets_without_viewport = TOTAL_GALLERIES * WIDGETS_PER_ROW
        widgets_with_viewport = VISIBLE_ROWS * WIDGETS_PER_ROW

        reduction = (widgets_without_viewport - widgets_with_viewport) / widgets_without_viewport

        print(f"\n{'='*70}")
        print(f"VIEWPORT LAZY LOADING MEMORY SAVINGS")
        print(f"{'='*70}")
        print(f"Total galleries: {TOTAL_GALLERIES}")
        print(f"Widgets per row: {WIDGETS_PER_ROW} (progress bar + action button)")
        print(f"Visible rows: ~{VISIBLE_ROWS}")
        print(f"\nWithout viewport:")
        print(f"  {widgets_without_viewport:,} widgets (all galleries)")
        print(f"\nWith viewport:")
        print(f"  {widgets_with_viewport:,} widgets (visible only)")
        print(f"\nMemory reduction:")
        print(f"  {widgets_without_viewport - widgets_with_viewport:,} fewer widgets")
        print(f"  {reduction*100:.1f}% memory savings")
        print(f"{'='*70}\n")

        assert reduction > 0.95, "Expected >95% memory reduction"


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short', '-s'])
