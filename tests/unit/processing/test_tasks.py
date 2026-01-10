"""
Comprehensive test suite for src/processing/tasks.py
Tests background task management, progress batching, icon caching, and table updates.
"""

import pytest
import time
from unittest.mock import Mock, MagicMock, patch, call
from PyQt6.QtCore import QTimer, QMutex, Qt
from PyQt6.QtWidgets import QTableWidgetItem

from src.processing.tasks import (
    BackgroundTask,
    BackgroundTaskSignals,
    ProgressUpdateBatcher,
    IconCache,
    TableRowUpdateTask,
    TableUpdateQueue,
    check_stored_credentials,
    api_key_is_set
)


class TestBackgroundTaskSignals:
    """Test BackgroundTaskSignals class"""

    def test_signals_exist(self):
        """Test that required signals are defined"""
        signals = BackgroundTaskSignals()
        assert hasattr(signals, 'finished')
        assert hasattr(signals, 'error')


class TestBackgroundTask:
    """Test BackgroundTask class"""

    def test_init(self):
        """Test BackgroundTask initialization"""
        mock_func = Mock(return_value="result")
        task = BackgroundTask(mock_func, "arg1", kwarg1="value1")

        assert task.func == mock_func
        assert task.args == ("arg1",)
        assert task.kwargs == {"kwarg1": "value1"}
        assert isinstance(task.signals, BackgroundTaskSignals)

    def test_run_success(self):
        """Test successful task execution"""
        mock_func = Mock(return_value="success_result")
        task = BackgroundTask(mock_func, "test_arg")

        finished_spy = Mock()
        task.signals.finished.connect(finished_spy)

        task.run()

        mock_func.assert_called_once_with("test_arg")
        finished_spy.assert_called_once_with("success_result")

    def test_run_error(self):
        """Test task execution with exception"""
        mock_func = Mock(side_effect=ValueError("test error"))
        task = BackgroundTask(mock_func)

        error_spy = Mock()
        task.signals.error.connect(error_spy)

        task.run()

        error_spy.assert_called_once_with("test error")

    def test_run_with_kwargs(self):
        """Test task execution with keyword arguments"""
        mock_func = Mock(return_value=42)
        task = BackgroundTask(mock_func, "pos_arg", key1="val1", key2="val2")

        finished_spy = Mock()
        task.signals.finished.connect(finished_spy)

        task.run()

        mock_func.assert_called_once_with("pos_arg", key1="val1", key2="val2")
        finished_spy.assert_called_once_with(42)


class TestProgressUpdateBatcher:
    """Test ProgressUpdateBatcher class"""

    @patch('src.processing.tasks.QTimer')
    def test_init(self, mock_timer_class):
        """Test ProgressUpdateBatcher initialization"""
        mock_callback = Mock()
        mock_timer = Mock()
        mock_timer_class.return_value = mock_timer

        batcher = ProgressUpdateBatcher(mock_callback, batch_interval=0.5)

        assert batcher._callback == mock_callback
        assert batcher._batch_interval == 0.5
        assert batcher._pending_updates == {}
        mock_timer.setSingleShot.assert_called_once_with(True)

    @patch('src.processing.tasks.QTimer')
    def test_add_update(self, mock_timer_class):
        """Test adding progress update to batch"""
        mock_callback = Mock()
        mock_timer = Mock()
        mock_timer.isActive.return_value = False
        mock_timer_class.return_value = mock_timer

        batcher = ProgressUpdateBatcher(mock_callback, batch_interval=1.0)
        # Set _last_batch_time to a recent time to prevent immediate processing
        batcher._last_batch_time = time.time()

        batcher.add_update("/path/test", 50, 100, 50, "image.jpg")

        assert "/path/test" in batcher._pending_updates
        update = batcher._pending_updates["/path/test"]
        assert update['completed'] == 50
        assert update['total'] == 100
        assert update['progress_percent'] == 50
        assert update['current_image'] == "image.jpg"

    @patch('src.processing.tasks.QTimer')
    def test_process_batch(self, mock_timer_class):
        """Test batch processing of updates"""
        mock_callback = Mock()
        mock_timer = Mock()
        mock_timer_class.return_value = mock_timer

        batcher = ProgressUpdateBatcher(mock_callback)
        batcher._pending_updates = {
            "/path/1": {
                'completed': 10, 'total': 100, 'progress_percent': 10,
                'current_image': 'img1.jpg', 'timestamp': time.time()
            },
            "/path/2": {
                'completed': 20, 'total': 100, 'progress_percent': 20,
                'current_image': 'img2.jpg', 'timestamp': time.time()
            }
        }

        batcher._process_batch()

        assert len(batcher._pending_updates) == 0
        assert mock_callback.call_count == 2
        mock_callback.assert_any_call("/path/1", 10, 100, 10, "img1.jpg")
        mock_callback.assert_any_call("/path/2", 20, 100, 20, "img2.jpg")

    @patch('src.processing.tasks.QTimer')
    def test_cleanup(self, mock_timer_class):
        """Test cleanup stops timer"""
        mock_timer = Mock()
        mock_timer.isActive.return_value = True
        mock_timer_class.return_value = mock_timer

        batcher = ProgressUpdateBatcher(Mock())
        batcher.cleanup()

        mock_timer.stop.assert_called_once()


class TestIconCache:
    """Test IconCache class"""

    def test_get_icon_data_cache_miss(self):
        """Test loading icon when not cached"""
        cache = IconCache()
        mock_loader = Mock(return_value="icon_data")

        result = cache.get_icon_data("status_ok", mock_loader)

        assert result == "icon_data"
        mock_loader.assert_called_once()

    def test_get_icon_data_cache_hit(self):
        """Test loading icon when already cached"""
        cache = IconCache()
        mock_loader = Mock(return_value="icon_data")

        # First call - cache miss
        result1 = cache.get_icon_data("status_ok", mock_loader)
        # Second call - cache hit
        result2 = cache.get_icon_data("status_ok", mock_loader)

        assert result1 == "icon_data"
        assert result2 == "icon_data"
        mock_loader.assert_called_once()  # Should only be called once

    def test_get_icon_data_load_failure(self):
        """Test handling of icon load failure"""
        cache = IconCache()
        mock_loader = Mock(side_effect=Exception("load error"))

        result = cache.get_icon_data("status_error", mock_loader)

        assert result is None
        # Subsequent calls should return cached None without calling loader again
        result2 = cache.get_icon_data("status_error", mock_loader)
        assert result2 is None
        mock_loader.assert_called_once()

    def test_clear(self):
        """Test cache clearing"""
        cache = IconCache()
        mock_loader = Mock(return_value="icon_data")

        cache.get_icon_data("status_ok", mock_loader)
        assert len(cache._cache) == 1

        cache.clear()
        assert len(cache._cache) == 0


class TestTableRowUpdateTask:
    """Test TableRowUpdateTask class"""

    def test_init(self):
        """Test TableRowUpdateTask initialization"""
        mock_item = Mock()
        task = TableRowUpdateTask(row=5, item=mock_item, update_type='full')

        assert task.row == 5
        assert task.item == mock_item
        assert task.update_type == 'full'
        assert isinstance(task.timestamp, float)

    def test_default_update_type(self):
        """Test default update type"""
        task = TableRowUpdateTask(row=1, item=Mock())
        assert task.update_type == 'full'


class TestTableUpdateQueue:
    """Test TableUpdateQueue class"""

    @patch('src.processing.tasks.QTimer')
    def test_init_with_gallery_table(self, mock_timer_class):
        """Test initialization with GalleryTableWidget"""
        mock_timer = Mock()
        mock_timer_class.return_value = mock_timer

        mock_table = Mock()
        path_to_row = {'/path/1': 0, '/path/2': 1}

        queue = TableUpdateQueue(mock_table, path_to_row)

        assert queue._path_to_row == path_to_row
        assert queue._pending_updates == {}
        assert queue._processing is False
        mock_timer.setSingleShot.assert_called_once_with(True)

    @patch('src.processing.tasks.QTimer')
    def test_init_with_tabbed_widget(self, mock_timer_class):
        """Test initialization with TabbedGalleryWidget"""
        mock_timer = Mock()
        mock_timer_class.return_value = mock_timer

        mock_gallery_table = Mock()
        mock_tabbed_widget = Mock()
        mock_tabbed_widget.gallery_table = mock_gallery_table

        path_to_row = {'/path/1': 0}
        queue = TableUpdateQueue(mock_tabbed_widget, path_to_row)

        assert queue._tabbed_widget is not None

    @patch('src.processing.tasks.QTimer')
    @patch('src.processing.tasks.TABLE_UPDATE_INTERVAL', 10)
    def test_queue_update(self, mock_timer_class):
        """Test queuing a table update"""
        mock_timer = Mock()
        mock_timer.isActive.return_value = False
        mock_timer_class.return_value = mock_timer

        # Create a proper mock that doesn't have gallery_table, so it uses the else path
        mock_table = Mock(spec=['rowCount', 'isRowHidden', 'item', 'cellWidget', 'setItem', 'parent'])
        mock_table.rowCount.return_value = 10
        mock_table.isRowHidden.return_value = False

        path_to_row = {'/path/1': 0}
        queue = TableUpdateQueue(mock_table, path_to_row)

        mock_item = Mock()
        queue.queue_update('/path/1', mock_item, 'progress')

        # When _tabbed_widget is None (plain table, not TabbedGalleryWidget),
        # hidden row check is skipped, so the update is queued
        assert '/path/1' in queue._pending_updates
        task = queue._pending_updates['/path/1']
        assert task.row == 0
        assert task.item == mock_item
        assert task.update_type == 'progress'
        mock_timer.start.assert_called_once_with(10)

    @patch('src.processing.tasks.QTimer')
    def test_queue_update_unknown_path(self, mock_timer_class):
        """Test queuing update for unknown path"""
        mock_timer = Mock()
        mock_timer_class.return_value = mock_timer

        mock_table = Mock()
        queue = TableUpdateQueue(mock_table, {'/path/1': 0})

        mock_item = Mock()
        queue.queue_update('/unknown/path', mock_item)

        assert '/unknown/path' not in queue._pending_updates

    @patch('src.processing.tasks.QTimer')
    def test_invalidate_visibility_cache(self, mock_timer_class):
        """Test visibility cache invalidation"""
        mock_timer = Mock()
        mock_timer_class.return_value = mock_timer

        mock_table = Mock()
        queue = TableUpdateQueue(mock_table, {})

        queue._cache_invalidation_counter = 0
        queue.invalidate_visibility_cache()

        assert queue._cache_invalidation_counter == 1000
        assert len(queue._visible_rows_cache) == 0

    @patch('src.processing.tasks.QTimer')
    def test_cleanup(self, mock_timer_class):
        """Test cleanup stops timer and clears updates"""
        mock_timer = Mock()
        mock_timer.isActive.return_value = True
        mock_timer_class.return_value = mock_timer

        mock_table = Mock()
        queue = TableUpdateQueue(mock_table, {'/path/1': 0})
        queue._pending_updates = {'/path/1': Mock()}

        queue.cleanup()

        mock_timer.stop.assert_called_once()
        assert len(queue._pending_updates) == 0


class TestCredentialFunctions:
    """Test credential checking functions"""

    @patch('imxup.get_credential')
    def test_check_stored_credentials_with_username_password(self, mock_get_credential):
        """Test credential check with username and password"""
        mock_get_credential.side_effect = lambda key: {
            'username': 'testuser',
            'password': 'encrypted_pass',
            'api_key': None
        }.get(key)

        result = check_stored_credentials()
        assert result is True

    @patch('imxup.get_credential')
    def test_check_stored_credentials_with_api_key(self, mock_get_credential):
        """Test credential check with API key only"""
        mock_get_credential.side_effect = lambda key: {
            'username': None,
            'password': None,
            'api_key': 'encrypted_api_key'
        }.get(key)

        result = check_stored_credentials()
        assert result is True

    @patch('imxup.get_credential')
    def test_check_stored_credentials_none(self, mock_get_credential):
        """Test credential check with no credentials"""
        mock_get_credential.return_value = None

        result = check_stored_credentials()
        assert result is False

    @patch('imxup.get_credential')
    def test_check_stored_credentials_exception(self, mock_get_credential):
        """Test credential check with exception"""
        mock_get_credential.side_effect = Exception("Import error")

        result = check_stored_credentials()
        assert result is False

    @patch('imxup.get_credential')
    def test_api_key_is_set_true(self, mock_get_credential):
        """Test API key check when set"""
        mock_get_credential.return_value = 'encrypted_api_key'

        result = api_key_is_set()
        assert result is True

    @patch('imxup.get_credential')
    def test_api_key_is_set_false(self, mock_get_credential):
        """Test API key check when not set"""
        mock_get_credential.return_value = None

        result = api_key_is_set()
        assert result is False

    @patch('imxup.get_credential')
    def test_api_key_is_set_exception(self, mock_get_credential):
        """Test API key check with exception"""
        mock_get_credential.side_effect = Exception("Import error")

        result = api_key_is_set()
        assert result is False


class TestProgressUpdateBatcherEdgeCases:
    """Test edge cases for ProgressUpdateBatcher"""

    @patch('src.processing.tasks.QTimer')
    def test_multiple_updates_same_path(self, mock_timer_class):
        """Test multiple updates for same path overwrites"""
        mock_callback = Mock()
        mock_timer = Mock()
        mock_timer.isActive.return_value = False
        mock_timer_class.return_value = mock_timer

        batcher = ProgressUpdateBatcher(mock_callback)
        batcher._last_batch_time = 0

        batcher.add_update("/path/test", 10, 100, 10, "img1.jpg")
        batcher.add_update("/path/test", 20, 100, 20, "img2.jpg")

        # Should only have one entry (latest)
        assert len(batcher._pending_updates) == 1
        assert batcher._pending_updates["/path/test"]['completed'] == 20

    @patch('src.processing.tasks.QTimer')
    def test_process_batch_empty(self, mock_timer_class):
        """Test processing empty batch"""
        mock_callback = Mock()
        mock_timer = Mock()
        mock_timer_class.return_value = mock_timer

        batcher = ProgressUpdateBatcher(mock_callback)
        batcher._process_batch()

        mock_callback.assert_not_called()


class TestTableUpdateQueueEdgeCases:
    """Test edge cases for TableUpdateQueue"""

    @patch('src.processing.tasks.QTimer')
    def test_process_updates_with_row_out_of_bounds(self, mock_timer_class):
        """Test processing update with invalid row number"""
        mock_timer = Mock()
        mock_timer_class.return_value = mock_timer

        mock_table = Mock(spec=['rowCount', 'isRowHidden', 'item', 'cellWidget', 'setItem', 'parent'])
        mock_table.rowCount.return_value = 5
        mock_table.isRowHidden.return_value = False
        path_to_row = {'/path/1': 10}  # Row 10 doesn't exist

        queue = TableUpdateQueue(mock_table, path_to_row)

        mock_item = Mock()
        mock_item.uploaded_images = 5
        mock_item.total_images = 10
        mock_item.progress = 50
        mock_item.status = "uploading"

        task = TableRowUpdateTask(10, mock_item, 'progress')
        queue._pending_updates['/path/1'] = task

        # Should not raise exception - should skip update due to out-of-bounds row
        queue._process_updates()

        # The update should have been processed and removed (skipped due to bounds check)
        assert '/path/1' not in queue._pending_updates

    @patch('src.processing.tasks.QTimer')
    def test_update_transfer_speed(self, mock_timer_class):
        """Test transfer speed formatting"""
        mock_timer = Mock()
        mock_timer_class.return_value = mock_timer

        mock_table = Mock()
        queue = TableUpdateQueue(mock_table, {})

        # Test KiB/s formatting
        assert "512.0 KiB/s" == queue._format_rate(512.0)

        # Test MiB/s formatting
        assert "1.5 MiB/s" == queue._format_rate(1536.0)

    @patch('src.processing.tasks.QTimer')
    def test_is_row_likely_hidden_caching(self, mock_timer_class):
        """Test row visibility caching mechanism"""
        mock_timer = Mock()
        mock_timer_class.return_value = mock_timer

        mock_table = Mock(spec=['rowCount', 'isRowHidden', 'item', 'cellWidget', 'setItem', 'parent'])
        mock_table.rowCount.return_value = 10
        mock_table.isRowHidden.return_value = False

        queue = TableUpdateQueue(mock_table, {})
        queue._last_cache_update = 0  # Force cache update

        # First call should update cache
        result1 = queue._is_row_likely_hidden(5)
        assert result1 is False

        # Second call should use cache
        mock_table.isRowHidden.reset_mock()
        result2 = queue._is_row_likely_hidden(5)
        assert result2 is False
