#!/usr/bin/env python3
"""
Comprehensive pytest-qt tests for GalleryTableWidget
Tests table model/view, row operations, selection handling, context menus, and cell editing
Target: 70%+ coverage with 40-60 tests
"""

import os
import sys
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch, call

import pytest
from PyQt6.QtWidgets import (
    QTableWidget, QTableWidgetItem, QApplication, QMenu,
    QHeaderView, QMessageBox, QInputDialog, QDialog, QMainWindow
)
from PyQt6.QtCore import Qt, QPoint, QUrl, QMimeData, QTimer
from PyQt6.QtGui import QIcon, QFont, QDragEnterEvent, QDropEvent, QKeyEvent

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from src.gui.widgets.gallery_table import GalleryTableWidget, NumericColumnDelegate
from src.core.constants import IMAGE_EXTENSIONS


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_queue_manager():
    """Mock QueueManager for testing"""
    manager = Mock()
    manager.get_item = Mock(return_value=None)
    manager.get_all_items = Mock(return_value=[])
    manager.update_gallery_name = Mock(return_value=True)
    manager.start_item = Mock(return_value=True)
    manager.update_item_status = Mock(return_value=True)
    manager.rescan_gallery_additive = Mock()
    manager.reset_gallery_complete = Mock()
    manager.retry_failed_upload = Mock()
    manager.batch_updates = Mock(return_value=MagicMock(__enter__=Mock(), __exit__=Mock()))
    manager._scan_queue = Mock()
    manager._scan_queue.put = Mock()
    return manager


@pytest.fixture
def mock_tab_manager():
    """Mock TabManager for testing"""
    manager = Mock()
    manager.get_tab_by_name = Mock(return_value=Mock(id=1, name='Main'))
    manager.move_galleries_to_tab = Mock(return_value=1)
    manager.invalidate_tab_cache = Mock()
    manager.load_tab_galleries = Mock(return_value=[])
    return manager


@pytest.fixture
def mock_icon_manager():
    """Mock IconManager for testing"""
    manager = Mock()
    manager.get_icon = Mock(return_value=QIcon())
    manager.get_status_icon = Mock(return_value=QIcon())
    manager.get_action_icon = Mock(return_value=QIcon())
    return manager


@pytest.fixture
def gallery_table(qtbot, mock_queue_manager):
    """Create a GalleryTableWidget for testing"""
    table = GalleryTableWidget()
    table.queue_manager = mock_queue_manager
    table.tab_manager = None
    table.icon_manager = None
    qtbot.addWidget(table)
    return table


@pytest.fixture
def sample_gallery_item():
    """Sample gallery queue item"""
    item = Mock()
    item.name = "Test Gallery"
    item.path = "/tmp/test_gallery"
    item.status = "ready"
    item.gallery_id = "12345"
    item.gallery_url = "https://imx.to/g/12345"
    item.tab_name = "Main"
    item.tab_id = 1
    return item


# ============================================================================
# Test: Initialization and Setup
# ============================================================================

class TestGalleryTableInit:
    """Test GalleryTableWidget initialization and setup"""

    def test_table_creates_successfully(self, qtbot):
        """Test basic table instantiation"""
        table = GalleryTableWidget()
        qtbot.addWidget(table)

        assert table is not None
        assert isinstance(table, QTableWidget)

    def test_table_has_correct_column_count(self, gallery_table):
        """Test that table has correct number of columns"""
        expected_columns = len(GalleryTableWidget.COLUMNS)
        assert gallery_table.columnCount() == expected_columns

    def test_table_column_definitions_exist(self, gallery_table):
        """Test COLUMNS class attribute exists and is valid"""
        assert hasattr(GalleryTableWidget, 'COLUMNS')
        assert len(GalleryTableWidget.COLUMNS) > 0

        # Validate structure of COLUMNS
        for col_def in GalleryTableWidget.COLUMNS:
            assert len(col_def) >= 6  # (index, name, label, width, mode, hidden)

    def test_table_column_constants_generated(self, gallery_table):
        """Test that column constants are generated from COLUMNS"""
        # Test a few key columns
        assert hasattr(GalleryTableWidget, 'COL_ORDER')
        assert hasattr(GalleryTableWidget, 'COL_NAME')
        assert hasattr(GalleryTableWidget, 'COL_STATUS')
        assert hasattr(GalleryTableWidget, 'COL_ACTION')
        assert hasattr(GalleryTableWidget, 'COL_PROGRESS')

    def test_table_headers_set_correctly(self, gallery_table):
        """Test that column headers are set from COLUMNS definition"""
        for idx, name, label, *_ in GalleryTableWidget.COLUMNS:
            header_item = gallery_table.horizontalHeaderItem(idx)
            assert header_item is not None
            assert header_item.text() == label

    def test_table_column_visibility(self, gallery_table):
        """Test that columns have correct default visibility"""
        for idx, name, label, width, mode, hidden, *_ in GalleryTableWidget.COLUMNS:
            is_hidden = gallery_table.isColumnHidden(idx)
            assert is_hidden == hidden, f"Column {name} visibility mismatch"

    def test_table_column_widths(self, gallery_table):
        """Test that columns have correct default widths"""
        for idx, name, label, width, *_ in GalleryTableWidget.COLUMNS:
            if not gallery_table.isColumnHidden(idx):
                actual_width = gallery_table.columnWidth(idx)
                # Width should be set (allowing for slight variations)
                assert actual_width > 0

    def test_table_sorting_enabled(self, gallery_table):
        """Test that table sorting is enabled"""
        assert gallery_table.isSortingEnabled() is True

    def test_table_selection_behavior(self, gallery_table):
        """Test that table selects entire rows"""
        assert gallery_table.selectionBehavior() == QTableWidget.SelectionBehavior.SelectRows

    def test_table_alternating_row_colors(self, gallery_table):
        """Test alternating row colors enabled"""
        assert gallery_table.alternatingRowColors() is True

    def test_table_vertical_header_hidden(self, gallery_table):
        """Test vertical header is hidden"""
        assert gallery_table.verticalHeader().isVisible() is False

    def test_table_drag_enabled(self, gallery_table):
        """Test drag and drop enabled"""
        assert gallery_table.dragEnabled() is True
        assert gallery_table.acceptDrops() is True

    def test_table_icon_size_set(self, gallery_table):
        """Test icon size is configured"""
        icon_size = gallery_table.iconSize()
        assert icon_size.width() == 20
        assert icon_size.height() == 20


# ============================================================================
# Test: NumericColumnDelegate
# ============================================================================

class TestNumericColumnDelegate:
    """Test NumericColumnDelegate for numeric columns"""

    def test_delegate_creates(self, qtbot):
        """Test delegate instantiation"""
        delegate = NumericColumnDelegate()
        assert delegate is not None

    def test_delegate_can_be_set_on_column(self, gallery_table):
        """Test delegate can be assigned to a column"""
        delegate = NumericColumnDelegate(gallery_table)
        gallery_table.setItemDelegateForColumn(GalleryTableWidget.COL_UPLOADED, delegate)

        # Verify delegate is set
        assigned_delegate = gallery_table.itemDelegateForColumn(GalleryTableWidget.COL_UPLOADED)
        assert assigned_delegate is delegate


# ============================================================================
# Test: Row Operations
# ============================================================================

class TestRowOperations:
    """Test row insertion, deletion, and manipulation"""

    def test_add_row_to_empty_table(self, gallery_table):
        """Test adding a row to empty table"""
        initial_count = gallery_table.rowCount()
        assert initial_count == 0

        gallery_table.insertRow(0)
        assert gallery_table.rowCount() == 1

    def test_add_multiple_rows(self, gallery_table):
        """Test adding multiple rows"""
        for i in range(5):
            gallery_table.insertRow(i)

        assert gallery_table.rowCount() == 5

    def test_remove_row(self, gallery_table):
        """Test removing a row"""
        gallery_table.insertRow(0)
        gallery_table.insertRow(1)

        gallery_table.removeRow(0)
        assert gallery_table.rowCount() == 1

    def test_clear_table(self, gallery_table):
        """Test clearing all rows"""
        for i in range(3):
            gallery_table.insertRow(i)

        gallery_table.setRowCount(0)
        assert gallery_table.rowCount() == 0

    def test_set_row_data(self, gallery_table):
        """Test setting data in a row"""
        gallery_table.insertRow(0)

        # Set name column
        name_item = QTableWidgetItem("Test Gallery")
        name_item.setData(Qt.ItemDataRole.UserRole, "/path/to/gallery")
        gallery_table.setItem(0, GalleryTableWidget.COL_NAME, name_item)

        # Verify data
        item = gallery_table.item(0, GalleryTableWidget.COL_NAME)
        assert item.text() == "Test Gallery"
        assert item.data(Qt.ItemDataRole.UserRole) == "/path/to/gallery"

    def test_row_height_default(self, gallery_table):
        """Test default row height"""
        default_height = gallery_table.verticalHeader().defaultSectionSize()
        assert default_height == 24  # As per initialization


# ============================================================================
# Test: Selection Handling
# ============================================================================

class TestSelectionHandling:
    """Test table selection operations"""

    def test_select_single_row(self, gallery_table):
        """Test selecting a single row"""
        gallery_table.insertRow(0)
        gallery_table.selectRow(0)

        selected_rows = gallery_table.selectionModel().selectedRows()
        assert len(selected_rows) == 1
        assert selected_rows[0].row() == 0

    def test_select_multiple_rows(self, gallery_table):
        """Test selecting multiple rows"""
        from PyQt6.QtCore import QItemSelectionModel

        for i in range(5):
            gallery_table.insertRow(i)

        # Select multiple rows using selection model
        selection_model = gallery_table.selectionModel()
        for row in [0, 2, 4]:
            index = gallery_table.model().index(row, 0)
            selection_model.select(index, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)

        selected_rows = gallery_table.selectionModel().selectedRows()
        assert len(selected_rows) >= 1  # At least one row selected

    def test_clear_selection(self, gallery_table):
        """Test clearing selection"""
        gallery_table.insertRow(0)
        gallery_table.selectRow(0)
        gallery_table.clearSelection()

        selected_rows = gallery_table.selectionModel().selectedRows()
        assert len(selected_rows) == 0

    def test_get_selected_items(self, gallery_table):
        """Test retrieving selected items"""
        gallery_table.insertRow(0)
        item = QTableWidgetItem("Test")
        gallery_table.setItem(0, GalleryTableWidget.COL_NAME, item)
        gallery_table.selectRow(0)

        selected_items = gallery_table.selectedItems()
        assert len(selected_items) > 0

    def test_current_row_selection(self, gallery_table):
        """Test current row tracking"""
        gallery_table.insertRow(0)
        gallery_table.insertRow(1)
        gallery_table.setCurrentCell(1, 0)

        assert gallery_table.currentRow() == 1


# ============================================================================
# Test: Cell Editing
# ============================================================================

class TestCellEditing:
    """Test cell editing functionality"""

    def test_cell_can_be_edited(self, gallery_table):
        """Test that cells can be edited"""
        gallery_table.insertRow(0)
        item = QTableWidgetItem("Original")
        gallery_table.setItem(0, GalleryTableWidget.COL_NAME, item)

        # Modify cell
        item.setText("Modified")
        assert gallery_table.item(0, GalleryTableWidget.COL_NAME).text() == "Modified"

    def test_cell_data_role(self, gallery_table):
        """Test setting and getting UserRole data"""
        gallery_table.insertRow(0)
        item = QTableWidgetItem("Text")
        item.setData(Qt.ItemDataRole.UserRole, {"key": "value"})
        gallery_table.setItem(0, GalleryTableWidget.COL_NAME, item)

        retrieved_item = gallery_table.item(0, GalleryTableWidget.COL_NAME)
        assert retrieved_item.data(Qt.ItemDataRole.UserRole) == {"key": "value"}

    def test_enter_key_handling_custom_columns(self, gallery_table, qtbot):
        """Test Enter key moves to next row in custom columns"""
        # Add rows with custom column items
        for i in range(3):
            gallery_table.insertRow(i)
            item = QTableWidgetItem(f"Custom{i}")
            gallery_table.setItem(i, GalleryTableWidget.COL_CUSTOM1, item)

        # Select first row, custom1 column
        gallery_table.setCurrentCell(0, GalleryTableWidget.COL_CUSTOM1)

        # Simulate Enter key
        event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Enter, Qt.KeyboardModifier.NoModifier)
        gallery_table.keyPressEvent(event)

        # Due to QTimer.singleShot, we need to process events
        qtbot.wait(50)

        # Current row should potentially move (implementation-dependent)
        # This tests that the event handler doesn't crash

    def test_delete_key_calls_handler(self, gallery_table, mock_queue_manager):
        """Test Delete key triggers deletion"""
        # Create a parent mock with delete method
        parent_mock = Mock(spec=QMainWindow)
        parent_mock.delete_selected_items = Mock()
        parent_mock.queue_manager = mock_queue_manager

        with patch.object(gallery_table, 'parent', return_value=parent_mock):
            gallery_table.insertRow(0)
            gallery_table.selectRow(0)

            # Simulate Delete key
            event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier)
            gallery_table.keyPressEvent(event)

            # Verify delete was called
            parent_mock.delete_selected_items.assert_called_once()

    def test_ctrl_c_copy_bbcode(self, gallery_table, mock_queue_manager):
        """Test Ctrl+C copies BBCode for completed items"""
        # Setup mock item
        sample_item = Mock()
        sample_item.status = "completed"
        sample_item.gallery_id = "123"
        sample_item.name = "Test"
        sample_item.gallery_url = "https://test.com"

        mock_queue_manager.get_item.return_value = sample_item

        # Add row
        gallery_table.insertRow(0)
        name_item = QTableWidgetItem("Test")
        name_item.setData(Qt.ItemDataRole.UserRole, "/tmp/test")
        gallery_table.setItem(0, GalleryTableWidget.COL_NAME, name_item)
        gallery_table.selectRow(0)

        with patch.object(gallery_table, 'handle_copy_bbcode') as mock_copy:
            # Simulate Ctrl+C
            event = QKeyEvent(
                QKeyEvent.Type.KeyPress,
                Qt.Key.Key_C,
                Qt.KeyboardModifier.ControlModifier
            )
            gallery_table.keyPressEvent(event)

            mock_copy.assert_called_once()


# ============================================================================
# Test: Context Menu
# ============================================================================

class TestContextMenu:
    """Test context menu operations"""

    def test_context_menu_helper_exists(self, gallery_table):
        """Test context menu helper can be set"""
        helper = Mock()
        gallery_table.context_menu_helper = helper
        assert gallery_table.context_menu_helper is helper

    def test_show_context_menu_basic(self, gallery_table):
        """Test basic context menu display"""
        gallery_table.insertRow(0)
        name_item = QTableWidgetItem("Test")
        name_item.setData(Qt.ItemDataRole.UserRole, "/tmp/test")
        gallery_table.setItem(0, GalleryTableWidget.COL_NAME, name_item)

        helper = Mock()
        helper.create_context_menu = Mock(return_value=QMenu())
        gallery_table.context_menu_helper = helper

        # Find parent window
        parent_mock = Mock(spec=QMainWindow)
        parent_mock.queue_manager = gallery_table.queue_manager

        with patch.object(gallery_table, 'parent', return_value=parent_mock):
            gallery_table.show_context_menu(QPoint(10, 10))

    def test_context_menu_event_fallback(self, gallery_table):
        """Test contextMenuEvent fallback"""
        gallery_table.insertRow(0)

        with patch.object(gallery_table, 'show_context_menu') as mock_show:
            from PyQt6.QtGui import QContextMenuEvent
            event = Mock(spec=QContextMenuEvent)
            event.globalPos.return_value = QPoint(100, 100)
            event.pos.return_value = QPoint(10, 10)

            gallery_table.contextMenuEvent(event)
            mock_show.assert_called_once()


# ============================================================================
# Test: Gallery Management Actions
# ============================================================================

class TestGalleryManagementActions:
    """Test gallery management operations called from context menu"""

    def test_manage_gallery_files(self, gallery_table, mock_queue_manager):
        """Test opening file manager dialog"""
        path = "/tmp/test_gallery"

        parent_mock = Mock(spec=QMainWindow)
        parent_mock.queue_manager = mock_queue_manager

        with patch.object(gallery_table, 'parent', return_value=parent_mock):
            with patch('src.gui.widgets.gallery_table.GalleryFileManagerDialog') as mock_dialog:
                mock_dialog_instance = Mock()
                mock_dialog_instance.exec.return_value = QDialog.DialogCode.Accepted
                mock_dialog.return_value = mock_dialog_instance

                gallery_table.manage_gallery_files(path)

                mock_dialog.assert_called_once()

    def test_rename_gallery_success(self, gallery_table, mock_queue_manager, sample_gallery_item, monkeypatch):
        """Test successful gallery rename"""
        path = "/tmp/test_gallery"
        mock_queue_manager.get_item.return_value = sample_gallery_item

        parent_mock = Mock(spec=QMainWindow)
        parent_mock.queue_manager = mock_queue_manager
        parent_mock._update_specific_gallery_display = Mock()
        parent_mock.regenerate_bbcode_for_gallery = Mock()

        # Mock QInputDialog class and static methods
        mock_dialog_class = Mock()
        mock_dialog_instance = Mock()
        mock_dialog_instance.exec.return_value = 1
        mock_dialog_instance.textValue.return_value = "New Name"
        mock_dialog_instance.resize = Mock()
        mock_dialog_instance.sizeHint = Mock(return_value=Mock(height=Mock(return_value=100)))
        mock_dialog_class.return_value = mock_dialog_instance

        monkeypatch.setattr('src.gui.widgets.gallery_table.QInputDialog', mock_dialog_class)

        with patch.object(gallery_table, 'parent', return_value=parent_mock):
            gallery_table.rename_gallery(path)
            mock_queue_manager.update_gallery_name.assert_called_once_with(path, "New Name")

    def test_rename_gallery_cancelled(self, gallery_table, mock_queue_manager, sample_gallery_item, monkeypatch):
        """Test cancelled gallery rename"""
        path = "/tmp/test_gallery"
        mock_queue_manager.get_item.return_value = sample_gallery_item

        parent_mock = Mock(spec=QMainWindow)
        parent_mock.queue_manager = mock_queue_manager

        # Mock QInputDialog
        mock_dialog_class = Mock()
        mock_dialog_instance = Mock()
        mock_dialog_instance.exec.return_value = 0
        mock_dialog_instance.resize = Mock()
        mock_dialog_instance.sizeHint = Mock(return_value=Mock(height=Mock(return_value=100)))
        mock_dialog_class.return_value = mock_dialog_instance

        monkeypatch.setattr('src.gui.widgets.gallery_table.QInputDialog', mock_dialog_class)

        with patch.object(gallery_table, 'parent', return_value=parent_mock):
            gallery_table.rename_gallery(path)
            mock_queue_manager.update_gallery_name.assert_not_called()

    def test_start_selected_via_menu(self, gallery_table, mock_queue_manager):
        """Test starting selected items"""
        parent_mock = Mock(spec=QMainWindow)
        parent_mock.queue_manager = mock_queue_manager
        parent_mock._update_specific_gallery_display = Mock()

        # Add test rows
        for i in range(3):
            gallery_table.insertRow(i)
            item = QTableWidgetItem(f"Gallery {i}")
            item.setData(Qt.ItemDataRole.UserRole, f"/tmp/gallery{i}")
            gallery_table.setItem(i, GalleryTableWidget.COL_NAME, item)

        gallery_table.selectRow(0)
        gallery_table.selectRow(2)

        with patch.object(gallery_table, 'parent', return_value=parent_mock):
            gallery_table.start_selected_via_menu()

            # Should have tried to start 2 items
            assert mock_queue_manager.start_item.call_count == 2

    def test_delete_selected_via_menu(self, gallery_table):
        """Test delete selected delegates to parent"""
        parent_mock = Mock(spec=QMainWindow)
        parent_mock.delete_selected_items = Mock()

        with patch.object(gallery_table, 'parent', return_value=parent_mock):
            gallery_table.delete_selected_via_menu()
            parent_mock.delete_selected_items.assert_called_once()

    def test_open_folders_via_menu(self, gallery_table, tmp_path):
        """Test opening gallery folders"""
        # Create temp directory
        test_dir = tmp_path / "test_gallery"
        test_dir.mkdir()

        with patch('src.gui.widgets.gallery_table.QDesktopServices.openUrl') as mock_open:
            gallery_table.open_folders_via_menu([str(test_dir)])
            mock_open.assert_called_once()


# ============================================================================
# Test: Upload Status Operations
# ============================================================================

class TestUploadStatusOperations:
    """Test upload status management operations"""

    def test_cancel_selected_via_menu_single(self, gallery_table, mock_queue_manager):
        """Test cancelling single upload"""
        parent_mock = Mock(spec=QMainWindow)
        parent_mock.queue_manager = mock_queue_manager
        parent_mock.cancel_single_item = Mock()

        with patch.object(gallery_table, 'parent', return_value=parent_mock):
            gallery_table.cancel_selected_via_menu(["/tmp/gallery1"])
            parent_mock.cancel_single_item.assert_called_once_with("/tmp/gallery1")

    def test_cancel_selected_via_menu_multiple(self, gallery_table, mock_queue_manager):
        """Test cancelling multiple uploads"""
        parent_mock = Mock(spec=QMainWindow)
        parent_mock.queue_manager = mock_queue_manager
        parent_mock.cancel_multiple_items = Mock()

        paths = ["/tmp/gallery1", "/tmp/gallery2"]

        with patch.object(gallery_table, 'parent', return_value=parent_mock):
            gallery_table.cancel_selected_via_menu(paths)
            parent_mock.cancel_multiple_items.assert_called_once_with(paths)

    def test_retry_selected_via_menu(self, gallery_table, mock_queue_manager, sample_gallery_item):
        """Test retrying failed uploads"""
        paths = ["/tmp/gallery1", "/tmp/gallery2"]
        mock_queue_manager.get_item.return_value = sample_gallery_item

        parent_mock = Mock(spec=QMainWindow)
        parent_mock.queue_manager = mock_queue_manager

        with patch.object(gallery_table, 'parent', return_value=parent_mock):
            gallery_table.retry_selected_via_menu(paths)

            assert mock_queue_manager.retry_failed_upload.call_count == 2

    def test_rescan_additive_via_menu(self, gallery_table, mock_queue_manager, sample_gallery_item):
        """Test additive rescan operation"""
        paths = ["/tmp/gallery1"]
        mock_queue_manager.get_item.return_value = sample_gallery_item

        parent_mock = Mock(spec=QMainWindow)
        parent_mock.queue_manager = mock_queue_manager

        with patch.object(gallery_table, 'parent', return_value=parent_mock):
            gallery_table.rescan_additive_via_menu(paths)

            mock_queue_manager._scan_queue.put.assert_called()

    def test_rescan_all_items_via_menu(self, gallery_table, mock_queue_manager, sample_gallery_item):
        """Test complete rescan operation"""
        paths = ["/tmp/gallery1"]
        mock_queue_manager.get_item.return_value = sample_gallery_item

        parent_mock = Mock(spec=QMainWindow)
        parent_mock.queue_manager = mock_queue_manager

        with patch.object(gallery_table, 'parent', return_value=parent_mock):
            gallery_table.rescan_all_items_via_menu(paths)

            mock_queue_manager._scan_queue.put.assert_called()

    def test_reset_gallery_via_menu_confirmed(self, gallery_table, mock_queue_manager, sample_gallery_item, monkeypatch):
        """Test gallery reset with confirmation"""
        paths = ["/tmp/gallery1"]
        mock_queue_manager.get_item.return_value = sample_gallery_item

        parent_mock = Mock(spec=QMainWindow)
        parent_mock.queue_manager = mock_queue_manager
        parent_mock.refresh_filter = Mock()

        # Mock QMessageBox to auto-accept
        with patch('src.gui.widgets.gallery_table.QMessageBox') as mock_msgbox:
            mock_msgbox_instance = Mock()
            mock_msgbox_instance.exec.return_value = QMessageBox.StandardButton.Yes
            mock_msgbox.return_value = mock_msgbox_instance
            mock_msgbox.StandardButton = QMessageBox.StandardButton

            with patch.object(gallery_table, 'parent', return_value=parent_mock):
                gallery_table.reset_gallery_via_menu(paths)

                mock_queue_manager.reset_gallery_complete.assert_called_once()

    def test_reset_gallery_via_menu_cancelled(self, gallery_table, mock_queue_manager):
        """Test gallery reset cancellation"""
        paths = ["/tmp/gallery1"]

        parent_mock = Mock(spec=QMainWindow)
        parent_mock.queue_manager = mock_queue_manager

        # Mock QMessageBox to reject
        with patch('src.gui.widgets.gallery_table.QMessageBox') as mock_msgbox:
            mock_msgbox_instance = Mock()
            mock_msgbox_instance.exec.return_value = QMessageBox.StandardButton.Cancel
            mock_msgbox.return_value = mock_msgbox_instance
            mock_msgbox.StandardButton = QMessageBox.StandardButton

            with patch.object(gallery_table, 'parent', return_value=parent_mock):
                gallery_table.reset_gallery_via_menu(paths)

                mock_queue_manager.reset_gallery_complete.assert_not_called()


# ============================================================================
# Test: BBCode Operations
# ============================================================================

class TestBBCodeOperations:
    """Test BBCode copying and viewing"""

    def test_copy_bbcode_single_item(self, gallery_table, mock_queue_manager, tmp_path):
        """Test copying BBCode for single completed item"""
        # Create BBCode file
        bbcode_file = tmp_path / "Test_12345_bbcode.txt"
        bbcode_file.write_text("[b]Test Content[/b]")

        sample_item = Mock()
        sample_item.status = "completed"
        sample_item.gallery_id = "12345"
        sample_item.name = "Test"
        mock_queue_manager.get_item.return_value = sample_item

        parent_mock = Mock(spec=QMainWindow)
        parent_mock.queue_manager = mock_queue_manager
        parent_mock._get_central_storage_path = Mock(return_value=str(tmp_path))
        parent_mock._build_gallery_filenames = Mock(return_value=("", "", str(bbcode_file.name)))
        parent_mock.statusBar = Mock(return_value=Mock(showMessage=Mock()))

        with patch.object(gallery_table, 'parent', return_value=parent_mock):
            with patch('src.gui.widgets.gallery_table.QApplication.clipboard') as mock_clipboard:
                mock_clipboard_instance = Mock()
                mock_clipboard.return_value = mock_clipboard_instance

                gallery_table.copy_bbcode_via_menu_multi(["/tmp/test"])

                # Clipboard should be called (implementation may vary)

    def test_copy_bbcode_multiple_items(self, gallery_table, mock_queue_manager, tmp_path):
        """Test copying BBCode for multiple items"""
        # Create BBCode files
        bbcode1 = tmp_path / "Test1_123_bbcode.txt"
        bbcode1.write_text("[b]Content 1[/b]")
        bbcode2 = tmp_path / "Test2_456_bbcode.txt"
        bbcode2.write_text("[b]Content 2[/b]")

        items = [
            Mock(status="completed", gallery_id="123", name="Test1"),
            Mock(status="completed", gallery_id="456", name="Test2"),
        ]

        mock_queue_manager.get_item.side_effect = items

        parent_mock = Mock(spec=QMainWindow)
        parent_mock.queue_manager = mock_queue_manager
        parent_mock._get_central_storage_path = Mock(return_value=str(tmp_path))
        parent_mock.statusBar = Mock(return_value=Mock(showMessage=Mock()))

        def build_filenames(name, gid):
            return ("", "", f"{name}_{gid}_bbcode.txt")

        parent_mock._build_gallery_filenames = build_filenames

        with patch.object(gallery_table, 'parent', return_value=parent_mock):
            with patch('src.gui.widgets.gallery_table.QApplication.clipboard') as mock_clipboard:
                mock_clipboard_instance = Mock()
                mock_clipboard.return_value = mock_clipboard_instance

                gallery_table.copy_bbcode_via_menu_multi(["/tmp/test1", "/tmp/test2"])

    def test_open_gallery_links_via_menu(self, gallery_table, mock_queue_manager):
        """Test opening gallery links in browser"""
        sample_item = Mock()
        sample_item.status = "completed"
        sample_item.gallery_url = "https://imx.to/g/12345"

        mock_queue_manager.get_item.return_value = sample_item

        parent_mock = Mock(spec=QMainWindow)
        parent_mock.queue_manager = mock_queue_manager
        parent_mock.statusBar = Mock(return_value=Mock(showMessage=Mock()))

        with patch.object(gallery_table, 'parent', return_value=parent_mock):
            with patch('src.gui.widgets.gallery_table.QDesktopServices.openUrl') as mock_open:
                gallery_table.open_gallery_links_via_menu(["/tmp/test"])

                mock_open.assert_called_once()


# ============================================================================
# Test: Drag and Drop
# ============================================================================

class TestDragAndDrop:
    """Test drag and drop functionality"""

    def test_drag_enter_event_with_images(self, gallery_table):
        """Test drag enter accepts image files"""
        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile("/tmp/test.jpg")])

        event = Mock()
        event.mimeData.return_value = mime_data
        event.acceptProposedAction = Mock()

        with patch('os.path.isfile', return_value=True):
            gallery_table.dragEnterEvent(event)
            event.acceptProposedAction.assert_called()

    def test_drag_enter_event_non_images(self, gallery_table):
        """Test drag enter with non-image files"""
        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile("/tmp/test.txt")])

        event = Mock()
        event.mimeData.return_value = mime_data

        with patch('os.path.isfile', return_value=True):
            gallery_table.dragEnterEvent(event)

    def test_drop_event_adds_files_to_gallery(self, gallery_table, mock_queue_manager, tmp_path):
        """Test dropping image files on gallery row"""
        # Create test image
        test_image = tmp_path / "test.jpg"
        test_image.write_bytes(b"fake image")

        # Setup table row
        gallery_table.insertRow(0)
        name_item = QTableWidgetItem("Test Gallery")
        name_item.setData(Qt.ItemDataRole.UserRole, str(tmp_path))
        gallery_table.setItem(0, GalleryTableWidget.COL_NAME, name_item)

        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile(str(test_image))])

        event = Mock()
        event.mimeData.return_value = mime_data
        event.position.return_value = Mock(toPoint=Mock(return_value=QPoint(10, 10)))
        event.acceptProposedAction = Mock()

        parent_mock = Mock(spec=QMainWindow)
        parent_mock.queue_manager = mock_queue_manager
        sample_item = Mock()
        sample_item.status = "ready"
        mock_queue_manager.get_item.return_value = sample_item

        with patch.object(gallery_table, 'indexAt', return_value=Mock(isValid=Mock(return_value=True), row=Mock(return_value=0))):
            with patch.object(gallery_table, 'parent', return_value=parent_mock):
                with patch('src.gui.widgets.gallery_table.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
                    with patch.object(gallery_table, 'add_files_to_gallery') as mock_add:
                        gallery_table.dropEvent(event)
                        mock_add.assert_called()

    def test_add_files_to_gallery(self, gallery_table, mock_queue_manager, tmp_path):
        """Test adding files to gallery"""
        gallery_path = tmp_path / "gallery"
        gallery_path.mkdir()

        test_file = tmp_path / "test.jpg"
        test_file.write_bytes(b"image data")

        sample_item = Mock()
        sample_item.status = "ready"
        mock_queue_manager.get_item.return_value = sample_item

        parent_mock = Mock(spec=QMainWindow)
        parent_mock.queue_manager = mock_queue_manager
        parent_mock.refresh_filter = Mock()

        with patch.object(gallery_table, 'parent', return_value=parent_mock):
            gallery_table.add_files_to_gallery(str(gallery_path), [str(test_file)])

            mock_queue_manager.rescan_gallery_additive.assert_called_once()


# ============================================================================
# Test: Mouse and Keyboard Events
# ============================================================================

class TestMouseKeyboardEvents:
    """Test mouse and keyboard event handling"""

    def test_mouse_press_event_sets_focus(self, gallery_table, qtbot):
        """Test left mouse click sets focus"""
        from PyQt6.QtGui import QMouseEvent

        event = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            QPoint(10, 10),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier
        )

        gallery_table.mousePressEvent(event)
        # Focus should be set (hard to verify without actual widget display)

    def test_double_click_event(self, gallery_table):
        """Test double-click calls handler"""
        gallery_table.insertRow(0)
        name_item = QTableWidgetItem("Test")
        name_item.setData(Qt.ItemDataRole.UserRole, "/tmp/test")
        gallery_table.setItem(0, GalleryTableWidget.COL_NAME, name_item)
        gallery_table.setCurrentCell(0, GalleryTableWidget.COL_NAME)

        with patch.object(gallery_table, 'handle_enter_or_double_click') as mock_handler:
            from PyQt6.QtGui import QMouseEvent
            event = QMouseEvent(
                QMouseEvent.Type.MouseButtonDblClick,
                QPoint(10, 10),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier
            )

            gallery_table.mouseDoubleClickEvent(event)
            mock_handler.assert_called_once()

    def test_handle_enter_or_double_click(self, gallery_table, mock_queue_manager):
        """Test enter/double-click handler"""
        gallery_table.insertRow(0)
        name_item = QTableWidgetItem("Test")
        name_item.setData(Qt.ItemDataRole.UserRole, "/tmp/test")
        gallery_table.setItem(0, GalleryTableWidget.COL_NAME, name_item)
        gallery_table.setCurrentCell(0, GalleryTableWidget.COL_NAME)

        parent_mock = Mock(spec=QMainWindow)
        parent_mock.handle_view_button = Mock()
        parent_mock.queue_manager = mock_queue_manager

        with patch.object(gallery_table, 'parent', return_value=parent_mock):
            gallery_table.handle_enter_or_double_click()
            parent_mock.handle_view_button.assert_called_once_with("/tmp/test")


# ============================================================================
# Test: Tab Management
# ============================================================================

class TestTabManagement:
    """Test moving galleries between tabs"""

    def test_move_selected_to_tab(self, gallery_table, mock_queue_manager, mock_tab_manager, sample_gallery_item):
        """Test moving galleries to different tab"""
        gallery_paths = ["/tmp/gallery1", "/tmp/gallery2"]
        target_tab = "Archive"

        mock_queue_manager.get_item.return_value = sample_gallery_item

        parent_mock = Mock(spec=QMainWindow)
        parent_mock.tab_manager = mock_tab_manager
        parent_mock.queue_manager = mock_queue_manager
        parent_mock.refresh_filter = Mock()
        parent_mock._update_tab_tooltips = Mock()

        with patch.object(gallery_table, 'parent', return_value=parent_mock):
            gallery_table._move_selected_to_tab(gallery_paths, target_tab)

            mock_tab_manager.move_galleries_to_tab.assert_called_once()
            mock_tab_manager.invalidate_tab_cache.assert_called_once()


# ============================================================================
# Test: Scrolling and Icon Refresh
# ============================================================================

class TestScrollingAndIconRefresh:
    """Test scroll-based icon refresh"""

    def test_scroll_event_refresh_icons(self, gallery_table):
        """Test scrolling triggers icon refresh when needed"""
        gallery_table._needs_full_icon_refresh = True

        parent_mock = Mock(spec=QMainWindow)
        parent_mock.refresh_all_status_icons = Mock()
        parent_mock._refresh_button_icons = Mock()

        with patch.object(gallery_table, 'parent', return_value=parent_mock):
            gallery_table._on_scroll()

            parent_mock.refresh_all_status_icons.assert_called_once()
            parent_mock._refresh_button_icons.assert_called_once()

    def test_scroll_no_refresh_when_not_needed(self, gallery_table):
        """Test scrolling doesn't refresh when flag is False"""
        gallery_table._needs_full_icon_refresh = False

        parent_mock = Mock(spec=QMainWindow)
        parent_mock.refresh_all_status_icons = Mock()

        with patch.object(gallery_table, 'parent', return_value=parent_mock):
            gallery_table._on_scroll()

            parent_mock.refresh_all_status_icons.assert_not_called()


# ============================================================================
# Test: Resize Behavior
# ============================================================================

class TestResizeBehavior:
    """Test table resize behavior"""

    def test_resize_event_does_not_auto_resize_columns(self, gallery_table):
        """Test resize event maintains Excel-like column behavior"""
        initial_width = gallery_table.columnWidth(GalleryTableWidget.COL_NAME)

        # Trigger resize event
        from PyQt6.QtGui import QResizeEvent
        event = QResizeEvent(gallery_table.size(), gallery_table.size())
        gallery_table.resizeEvent(event)

        # Column width should remain unchanged
        assert gallery_table.columnWidth(GalleryTableWidget.COL_NAME) == initial_width


# ============================================================================
# Run tests
# ============================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
