#!/usr/bin/env python3
"""
Multi-Selection State Preservation Tests
Tests that multi-selection is correctly preserved across tab switches.

This test suite validates the fix for the multi-selection deselection bug
where selecting multiple items in one tab and switching to another tab
would cause all items to be deselected.

Test Scenarios:
1. Basic Multi-Select - Ctrl+Click to select multiple items
2. Range Selection - Shift+Click to select a range
3. Mixed Tabs - Independent selections per tab
4. Scroll + Selection - Both preserved together
5. Start Operation - Selection preserved after processing starts
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
from PyQt6.QtWidgets import QApplication, QTableWidgetItem
from PyQt6.QtCore import Qt, QItemSelectionModel

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.gui.widgets.tabbed_gallery import TabbedGalleryWidget
from src.gui.widgets.gallery_table import GalleryTableWidget


@pytest.fixture(scope="module")
def qapp():
    """Create QApplication instance for tests"""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


@pytest.fixture
def tabbed_widget(qapp):
    """Create TabbedGalleryWidget instance"""
    widget = TabbedGalleryWidget()

    # Mock tab manager with side_effect to return tab-specific galleries
    def load_tab_galleries_mock(tab_name):
        """Return all test galleries for any tab (simulate all galleries in each tab)"""
        # Return all 10 test gallery paths for each tab
        # This allows multi-selection tests to work properly
        return [{'path': f"/path/to/gallery{i+1}"} for i in range(10)]

    mock_tab_manager = Mock()
    mock_tab_manager.get_visible_tab_names.return_value = ["Main", "Tab A", "Tab B"]
    mock_tab_manager.last_active_tab = "Main"
    mock_tab_manager.load_tab_galleries.side_effect = load_tab_galleries_mock

    widget.set_tab_manager(mock_tab_manager)

    # Add test data
    _populate_test_data(widget)

    yield widget
    widget.deleteLater()


def _populate_test_data(widget):
    """Populate widget with test gallery data"""
    # Add 10 test galleries
    for i in range(10):
        row = widget.table.rowCount()
        widget.table.insertRow(row)

        # Name column
        name_item = QTableWidgetItem(f"Gallery {i+1}")
        name_item.setData(Qt.ItemDataRole.UserRole, f"/path/to/gallery{i+1}")
        widget.table.setItem(row, GalleryTableWidget.COL_NAME, name_item)

        # Status column
        status_item = QTableWidgetItem("Ready")
        widget.table.setItem(row, GalleryTableWidget.COL_STATUS, status_item)

        # Progress column
        progress_item = QTableWidgetItem("0%")
        widget.table.setItem(row, GalleryTableWidget.COL_PROGRESS, progress_item)


def _select_multiple_rows(table, rows):
    """Helper function to correctly select multiple rows using QItemSelectionModel"""
    table.clearSelection()
    selection_model = table.selectionModel()
    for row in rows:
        index = table.model().index(row, 0)
        selection_model.select(
            index,
            QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
        )


class TestMultiSelectionBasic:
    """Test basic multi-selection preservation"""

    def test_ctrl_click_selection_preserved(self, tabbed_widget):
        """Test Scenario 1: Basic Multi-Select with Ctrl+Click"""
        # Switch to Tab A
        tabbed_widget.switch_to_tab("Tab A")
        assert tabbed_widget.current_tab == "Tab A"

        # Select rows 0, 2, 4 (simulating Ctrl+Click)
        _select_multiple_rows(tabbed_widget.table, [0, 2, 4])

        # Verify selection
        selected_rows = {item.row() for item in tabbed_widget.table.selectedItems()}
        assert selected_rows == {0, 2, 4}, f"Expected {{0, 2, 4}}, got {selected_rows}"

        # Switch to Tab B
        tabbed_widget.switch_to_tab("Tab B")
        assert tabbed_widget.current_tab == "Tab B"

        # Switch back to Tab A
        tabbed_widget.switch_to_tab("Tab A")

        # CRITICAL: Verify selection is still preserved
        selected_rows_after = {item.row() for item in tabbed_widget.table.selectedItems()}
        assert selected_rows_after == {0, 2, 4}, \
            f"Selection lost! Expected {{0, 2, 4}}, got {selected_rows_after}"

    def test_shift_click_range_selection_preserved(self, tabbed_widget):
        """Test Scenario 2: Range Selection with Shift+Click"""
        # Switch to Tab A
        tabbed_widget.switch_to_tab("Tab A")

        # Select range 2-7 (simulating click row 2, Shift+Click row 7)
        _select_multiple_rows(tabbed_widget.table, range(2, 8))

        # Verify selection
        selected_rows = {item.row() for item in tabbed_widget.table.selectedItems()}
        expected_range = set(range(2, 8))
        assert selected_rows == expected_range, \
            f"Expected {expected_range}, got {selected_rows}"

        # Switch to Tab B
        tabbed_widget.switch_to_tab("Tab B")

        # Switch back to Tab A
        tabbed_widget.switch_to_tab("Tab A")

        # CRITICAL: Verify range selection is preserved
        selected_rows_after = {item.row() for item in tabbed_widget.table.selectedItems()}
        assert selected_rows_after == expected_range, \
            f"Range selection lost! Expected {expected_range}, got {selected_rows_after}"


class TestMultiSelectionMixedTabs:
    """Test independent selections across multiple tabs"""

    def test_independent_tab_selections(self, tabbed_widget):
        """Test Scenario 3: Independent selections per tab"""
        # Tab A: Select rows 1, 2, 3
        tabbed_widget.switch_to_tab("Tab A")
        _select_multiple_rows(tabbed_widget.table, [1, 2, 3])

        tab_a_selection = {item.row() for item in tabbed_widget.table.selectedItems()}
        assert tab_a_selection == {1, 2, 3}

        # Tab B: Select rows 4, 5
        tabbed_widget.switch_to_tab("Tab B")
        _select_multiple_rows(tabbed_widget.table, [4, 5])

        tab_b_selection = {item.row() for item in tabbed_widget.table.selectedItems()}
        assert tab_b_selection == {4, 5}

        # Switch back to Tab A - verify its selection
        tabbed_widget.switch_to_tab("Tab A")
        tab_a_after = {item.row() for item in tabbed_widget.table.selectedItems()}
        assert tab_a_after == {1, 2, 3}, \
            f"Tab A selection corrupted! Expected {{1, 2, 3}}, got {tab_a_after}"

        # Switch back to Tab B - verify its selection
        tabbed_widget.switch_to_tab("Tab B")
        tab_b_after = {item.row() for item in tabbed_widget.table.selectedItems()}
        assert tab_b_after == {4, 5}, \
            f"Tab B selection corrupted! Expected {{4, 5}}, got {tab_b_after}"

    def test_multiple_tab_switches_preserve_selection(self, tabbed_widget):
        """Test rapid switching between tabs preserves all selections"""
        # Setup selections in Tab A and Tab B
        tabbed_widget.switch_to_tab("Tab A")
        _select_multiple_rows(tabbed_widget.table, [0, 1])

        tabbed_widget.switch_to_tab("Tab B")
        _select_multiple_rows(tabbed_widget.table, [8, 9])

        # Rapidly switch between tabs 5 times
        for _ in range(5):
            tabbed_widget.switch_to_tab("Tab A")
            tabbed_widget.switch_to_tab("Tab B")
            tabbed_widget.switch_to_tab("Main")

        # Final verification - Tab A selection
        tabbed_widget.switch_to_tab("Tab A")
        tab_a_final = {item.row() for item in tabbed_widget.table.selectedItems()}
        assert tab_a_final == {0, 1}, \
            f"Tab A selection lost after rapid switching! Expected {{0, 1}}, got {tab_a_final}"

        # Final verification - Tab B selection
        tabbed_widget.switch_to_tab("Tab B")
        tab_b_final = {item.row() for item in tabbed_widget.table.selectedItems()}
        assert tab_b_final == {8, 9}, \
            f"Tab B selection lost after rapid switching! Expected {{8, 9}}, got {tab_b_final}"


class TestScrollAndSelectionPreservation:
    """Test both scroll position and selection are preserved together"""

    def test_scroll_and_selection_both_preserved(self, tabbed_widget):
        """Test Scenario 4: Scroll AND selection both preserved"""
        # Switch to Tab A
        tabbed_widget.switch_to_tab("Tab A")

        # Select rows and set scroll position
        _select_multiple_rows(tabbed_widget.table, [5, 6, 7])

        # Set specific scroll position
        test_scroll_position = 150
        tabbed_widget.table.verticalScrollBar().setValue(test_scroll_position)

        # Verify initial state
        initial_selection = {item.row() for item in tabbed_widget.table.selectedItems()}
        initial_scroll = tabbed_widget.table.verticalScrollBar().value()
        assert initial_selection == {5, 6, 7}
        assert initial_scroll == test_scroll_position

        # Switch to Tab B
        tabbed_widget.switch_to_tab("Tab B")

        # Switch back to Tab A
        tabbed_widget.switch_to_tab("Tab A")

        # CRITICAL: Verify BOTH scroll and selection preserved
        final_selection = {item.row() for item in tabbed_widget.table.selectedItems()}
        final_scroll = tabbed_widget.table.verticalScrollBar().value()

        assert final_selection == {5, 6, 7}, \
            f"Selection lost! Expected {{5, 6, 7}}, got {final_selection}"
        assert final_scroll == test_scroll_position, \
            f"Scroll position lost! Expected {test_scroll_position}, got {final_scroll}"


class TestSelectionAfterOperations:
    """Test selection preservation during operations like Start"""

    def test_selection_preserved_after_start_operation(self, tabbed_widget):
        """Test Scenario 5: Selection preserved after Start operation begins"""
        # Switch to Tab A and select items
        tabbed_widget.switch_to_tab("Tab A")
        _select_multiple_rows(tabbed_widget.table, [0, 1, 2])

        initial_selection = {item.row() for item in tabbed_widget.table.selectedItems()}
        assert initial_selection == {0, 1, 2}

        # Simulate Start operation triggering selection change
        # (The bug was that selection was cleared when Start was clicked)
        tabbed_widget.table.itemSelectionChanged.emit()

        # Verify selection still preserved
        after_operation = {item.row() for item in tabbed_widget.table.selectedItems()}
        assert after_operation == {0, 1, 2}, \
            f"Selection lost after operation! Expected {{0, 1, 2}}, got {after_operation}"

        # Switch tab and back
        tabbed_widget.switch_to_tab("Tab B")
        tabbed_widget.switch_to_tab("Tab A")

        # CRITICAL: Selection should STILL be preserved
        final_selection = {item.row() for item in tabbed_widget.table.selectedItems()}
        assert final_selection == {0, 1, 2}, \
            f"Selection lost after tab switch post-operation! Expected {{0, 1, 2}}, got {final_selection}"


class TestEdgeCases:
    """Test edge cases and boundary conditions"""

    def test_empty_selection_preserved(self, tabbed_widget):
        """Test that empty selection (no items selected) is preserved"""
        # Tab A: No selection
        tabbed_widget.switch_to_tab("Tab A")
        tabbed_widget.table.clearSelection()

        assert len(tabbed_widget.table.selectedItems()) == 0

        # Switch to Tab B, select something
        tabbed_widget.switch_to_tab("Tab B")
        tabbed_widget.table.selectRow(0)

        # Switch back to Tab A
        tabbed_widget.switch_to_tab("Tab A")

        # Verify Tab A still has no selection
        assert len(tabbed_widget.table.selectedItems()) == 0, \
            "Empty selection not preserved!"

    def test_single_item_selection_preserved(self, tabbed_widget):
        """Test single item selection is preserved (regression test)"""
        tabbed_widget.switch_to_tab("Tab A")
        tabbed_widget.table.clearSelection()
        tabbed_widget.table.selectRow(3)

        initial = {item.row() for item in tabbed_widget.table.selectedItems()}
        assert initial == {3}

        tabbed_widget.switch_to_tab("Tab B")
        tabbed_widget.switch_to_tab("Tab A")

        final = {item.row() for item in tabbed_widget.table.selectedItems()}
        assert final == {3}, \
            f"Single item selection lost! Expected {{3}}, got {final}"

    def test_all_items_selected_preserved(self, tabbed_widget):
        """Test selecting all items is preserved"""
        tabbed_widget.switch_to_tab("Tab A")

        # Select all rows
        _select_multiple_rows(tabbed_widget.table, range(tabbed_widget.table.rowCount()))

        initial = {item.row() for item in tabbed_widget.table.selectedItems()}
        expected = set(range(tabbed_widget.table.rowCount()))
        assert initial == expected

        tabbed_widget.switch_to_tab("Tab B")
        tabbed_widget.switch_to_tab("Tab A")

        final = {item.row() for item in tabbed_widget.table.selectedItems()}
        assert final == expected, \
            f"Select-all not preserved! Expected {expected}, got {final}"


def test_state_isolation_between_tabs(tabbed_widget):
    """Integration test: Verify complete state isolation between tabs"""
    # This is the master test that validates the entire fix

    # Tab A: Select rows 1, 3, 5, scroll to 100
    tabbed_widget.switch_to_tab("Tab A")
    _select_multiple_rows(tabbed_widget.table, [1, 3, 5])
    tabbed_widget.table.verticalScrollBar().setValue(100)

    # Tab B: Select rows 2, 4, 6, scroll to 200
    tabbed_widget.switch_to_tab("Tab B")
    _select_multiple_rows(tabbed_widget.table, [2, 4, 6])
    tabbed_widget.table.verticalScrollBar().setValue(200)

    # Main: Select rows 0, 9, scroll to 50
    tabbed_widget.switch_to_tab("Main")
    _select_multiple_rows(tabbed_widget.table, [0, 9])
    tabbed_widget.table.verticalScrollBar().setValue(50)

    # Verify each tab maintains its state independently

    # Check Tab A
    tabbed_widget.switch_to_tab("Tab A")
    tab_a_selection = {item.row() for item in tabbed_widget.table.selectedItems()}
    tab_a_scroll = tabbed_widget.table.verticalScrollBar().value()
    assert tab_a_selection == {1, 3, 5}, f"Tab A selection wrong: {tab_a_selection}"
    assert tab_a_scroll == 100, f"Tab A scroll wrong: {tab_a_scroll}"

    # Check Tab B
    tabbed_widget.switch_to_tab("Tab B")
    tab_b_selection = {item.row() for item in tabbed_widget.table.selectedItems()}
    tab_b_scroll = tabbed_widget.table.verticalScrollBar().value()
    assert tab_b_selection == {2, 4, 6}, f"Tab B selection wrong: {tab_b_selection}"
    assert tab_b_scroll == 200, f"Tab B scroll wrong: {tab_b_scroll}"

    # Check Main
    tabbed_widget.switch_to_tab("Main")
    main_selection = {item.row() for item in tabbed_widget.table.selectedItems()}
    main_scroll = tabbed_widget.table.verticalScrollBar().value()
    assert main_selection == {0, 9}, f"Main selection wrong: {main_selection}"
    assert main_scroll == 50, f"Main scroll wrong: {main_scroll}"


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
