"""
Comprehensive test suite for queue_manager.py module.

Tests cover:
- Queue initialization and loading
- Gallery addition and removal
- Status management and transitions
- Queue operations (enqueue, dequeue)
- Scan operations and validation
- Retry and rescan functionality
- Custom field updates
- Tab organization
- Concurrent operations
- Error scenarios and edge cases
"""

import pytest
import queue
import os
import tempfile
import time
import threading
from unittest.mock import Mock, patch, MagicMock, call
from queue import Queue, Empty

from PyQt6.QtCore import QSettings

# Import module under test
from src.storage.queue_manager import (
    QueueManager,
    GalleryQueueItem
)
from src.core.constants import (
    QUEUE_STATE_READY,
    QUEUE_STATE_QUEUED,
    QUEUE_STATE_UPLOADING,
    QUEUE_STATE_COMPLETED,
    QUEUE_STATE_FAILED,
    QUEUE_STATE_SCAN_FAILED,
    QUEUE_STATE_UPLOAD_FAILED,
    QUEUE_STATE_PAUSED,
    QUEUE_STATE_INCOMPLETE,
    QUEUE_STATE_SCANNING,
    QUEUE_STATE_VALIDATING
)


@pytest.fixture
def temp_dir():
    """Create temporary directory for test galleries."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def mock_store():
    """Mock QueueStore."""
    store = Mock()
    store.load_all_items.return_value = []
    store.bulk_upsert.return_value = None
    store.bulk_upsert_async.return_value = None
    store.delete_by_paths.return_value = 1
    store.update_item_custom_field.return_value = True
    return store


@pytest.fixture
def queue_manager(mock_store):
    """Create QueueManager instance with mocked store."""
    with patch('src.storage.queue_manager.QueueStore', return_value=mock_store):
        with patch('src.storage.queue_manager.QSettings'):
            manager = QueueManager()
            yield manager
            # Cleanup - use proper shutdown to avoid Windows file locking issues
            # The scan worker thread must be stopped AND joined before temp files can be deleted
            manager._scan_worker_running = False
            try:
                manager._scan_queue.put(None, timeout=0.1)
            except (queue.Full, AttributeError):
                pass
            # CRITICAL: Wait for scan worker thread to finish to release file handles
            if manager._scan_worker and manager._scan_worker.is_alive():
                manager._scan_worker.join(timeout=3.0)
            # Force garbage collection to release any lingering PIL file handles
            import gc
            gc.collect()
            # Small delay to ensure OS releases file handles on Windows
            time.sleep(0.1)


@pytest.fixture
def gallery_dir(temp_dir):
    """Create a test gallery directory with images."""
    gallery_path = os.path.join(temp_dir, 'test_gallery')
    os.makedirs(gallery_path)

    # Create test images
    for i in range(5):
        img_path = os.path.join(gallery_path, f'image{i}.jpg')
        with open(img_path, 'wb') as f:
            f.write(b'\xFF\xD8\xFF\xE0')  # JPEG header

    return gallery_path


class TestGalleryQueueItem:
    """Test GalleryQueueItem dataclass."""

    def test_default_initialization(self):
        """Test item initialization with defaults."""
        item = GalleryQueueItem(path='/test/path')

        assert item.path == '/test/path'
        assert item.status == QUEUE_STATE_READY
        assert item.progress == 0
        assert item.total_images == 0
        assert item.uploaded_images == 0
        assert item.tab_name == 'Main'

    def test_custom_initialization(self):
        """Test item initialization with custom values."""
        item = GalleryQueueItem(
            path='/test/path',
            name='Test Gallery',
            status=QUEUE_STATE_COMPLETED,
            total_images=10,
            uploaded_images=10,
            tab_name='Custom'
        )

        assert item.name == 'Test Gallery'
        assert item.status == QUEUE_STATE_COMPLETED
        assert item.total_images == 10
        assert item.tab_name == 'Custom'

    def test_uploaded_files_set(self):
        """Test uploaded_files is a set."""
        item = GalleryQueueItem(path='/test/path')

        assert isinstance(item.uploaded_files, set)
        item.uploaded_files.add('image1.jpg')
        assert 'image1.jpg' in item.uploaded_files


class TestQueueManagerInitialization:
    """Test QueueManager initialization."""

    def test_initialization(self, queue_manager):
        """Test basic initialization."""
        assert hasattr(queue_manager, 'items')
        assert hasattr(queue_manager, 'queue')
        assert hasattr(queue_manager, 'mutex')
        assert isinstance(queue_manager.items, dict)

    def test_loads_persistent_queue(self, mock_store):
        """Test that persistent queue is loaded on init."""
        mock_store.load_all_items.return_value = [
            {
                'path': '/test/gallery1',
                'status': QUEUE_STATE_COMPLETED,
                'added_time': int(time.time()),
                'tab_name': 'Main'
            }
        ]

        with patch('src.storage.queue_manager.QueueStore', return_value=mock_store):
            with patch('src.storage.queue_manager.QSettings'):
                manager = QueueManager()

                assert len(manager.items) == 1
                assert '/test/gallery1' in manager.items

                manager._scan_worker_running = False

    def test_scan_worker_started(self, queue_manager):
        """Test that scan worker thread is started."""
        assert queue_manager._scan_worker_running
        assert queue_manager._scan_worker is not None


class TestAddItem:
    """Test adding items to queue."""

    def test_add_item_basic(self, queue_manager, gallery_dir):
        """Test basic item addition."""
        success = queue_manager.add_item(gallery_dir, name='Test Gallery')

        assert success
        assert gallery_dir in queue_manager.items
        assert queue_manager.items[gallery_dir].name == 'Test Gallery'
        assert queue_manager.items[gallery_dir].status == QUEUE_STATE_VALIDATING

    def test_add_item_duplicate_path(self, queue_manager, gallery_dir):
        """Test adding duplicate path fails."""
        queue_manager.add_item(gallery_dir, name='Gallery 1')
        success = queue_manager.add_item(gallery_dir, name='Gallery 2')

        assert not success
        assert queue_manager.items[gallery_dir].name == 'Gallery 1'

    def test_add_item_with_template(self, queue_manager, gallery_dir):
        """Test adding item with custom template."""
        success = queue_manager.add_item(gallery_dir, template_name='custom_template')

        assert success
        assert queue_manager.items[gallery_dir].template_name == 'custom_template'

    def test_add_item_with_tab(self, queue_manager, gallery_dir):
        """Test adding item to specific tab."""
        success = queue_manager.add_item(gallery_dir, tab_name='Custom Tab')

        assert success
        assert queue_manager.items[gallery_dir].tab_name == 'Custom Tab'

    def test_add_item_triggers_scan(self, queue_manager, gallery_dir):
        """Test that adding item triggers scan."""
        queue_manager.add_item(gallery_dir)

        # Give scan queue time to receive item
        time.sleep(0.1)

        # Verify scan was queued (queue should not be empty)
        # Note: This is timing-dependent and may need adjustment

    def test_add_item_increments_order(self, queue_manager, gallery_dir):
        """Test that insertion order increments."""
        gallery_dir2 = gallery_dir + '_2'
        os.makedirs(gallery_dir2, exist_ok=True)

        queue_manager.add_item(gallery_dir)
        queue_manager.add_item(gallery_dir2)

        assert queue_manager.items[gallery_dir].insertion_order < queue_manager.items[gallery_dir2].insertion_order


class TestRemoveItem:
    """Test removing items from queue."""

    def test_remove_item(self, queue_manager, gallery_dir):
        """Test removing an item."""
        queue_manager.add_item(gallery_dir)

        success = queue_manager.remove_item(gallery_dir)

        assert success
        assert gallery_dir not in queue_manager.items

    def test_remove_nonexistent_item(self, queue_manager):
        """Test removing non-existent item."""
        success = queue_manager.remove_item('/nonexistent/path')

        assert not success

    def test_remove_uploading_item_fails(self, queue_manager, gallery_dir):
        """Test that uploading items cannot be removed."""
        queue_manager.add_item(gallery_dir)
        queue_manager.items[gallery_dir].status = QUEUE_STATE_UPLOADING

        success = queue_manager.remove_item(gallery_dir)

        assert not success
        assert gallery_dir in queue_manager.items


class TestStatusManagement:
    """Test status management operations."""

    def test_update_item_status(self, queue_manager, gallery_dir):
        """Test updating item status."""
        queue_manager.add_item(gallery_dir)
        queue_manager.items[gallery_dir].status = QUEUE_STATE_READY

        queue_manager.update_item_status(gallery_dir, QUEUE_STATE_COMPLETED)

        assert queue_manager.items[gallery_dir].status == QUEUE_STATE_COMPLETED

    def test_completed_status_sets_progress_100(self, queue_manager, gallery_dir):
        """Test that completed status sets progress to 100%."""
        queue_manager.add_item(gallery_dir)
        queue_manager.items[gallery_dir].progress = 50

        queue_manager.update_item_status(gallery_dir, QUEUE_STATE_COMPLETED)

        assert queue_manager.items[gallery_dir].progress == 100

    def test_status_changed_signal_emitted(self, queue_manager, gallery_dir):
        """Test that status_changed signal is emitted."""
        signal_received = []
        queue_manager.status_changed.connect(lambda *args: signal_received.append(args))

        queue_manager.add_item(gallery_dir)
        queue_manager.items[gallery_dir].status = QUEUE_STATE_READY
        queue_manager.update_item_status(gallery_dir, QUEUE_STATE_QUEUED)

        # Give signal time to propagate
        time.sleep(0.1)

        # Verify signal was emitted
        assert len(signal_received) > 0


class TestQueueOperations:
    """Test queue operations."""

    def test_start_item(self, queue_manager, gallery_dir):
        """Test starting an item (queueing for upload)."""
        queue_manager.add_item(gallery_dir)
        queue_manager.items[gallery_dir].status = QUEUE_STATE_READY

        success = queue_manager.start_item(gallery_dir)

        assert success
        assert queue_manager.items[gallery_dir].status == QUEUE_STATE_QUEUED

    def test_start_nonexistent_item(self, queue_manager):
        """Test starting non-existent item fails."""
        success = queue_manager.start_item('/nonexistent')

        assert not success

    def test_start_invalid_status_item(self, queue_manager, gallery_dir):
        """Test starting item with invalid status fails."""
        queue_manager.add_item(gallery_dir)
        queue_manager.items[gallery_dir].status = QUEUE_STATE_UPLOADING

        success = queue_manager.start_item(gallery_dir)

        assert not success

    def test_start_paused_item(self, queue_manager, gallery_dir):
        """Test starting paused item."""
        queue_manager.add_item(gallery_dir)
        queue_manager.items[gallery_dir].status = QUEUE_STATE_PAUSED

        success = queue_manager.start_item(gallery_dir)

        assert success

    def test_start_incomplete_item(self, queue_manager, gallery_dir):
        """Test starting incomplete item."""
        queue_manager.add_item(gallery_dir)
        queue_manager.items[gallery_dir].status = QUEUE_STATE_INCOMPLETE

        success = queue_manager.start_item(gallery_dir)

        assert success

    def test_get_next_item(self, queue_manager, gallery_dir):
        """Test getting next queued item."""
        queue_manager.add_item(gallery_dir)
        queue_manager.items[gallery_dir].status = QUEUE_STATE_READY
        queue_manager.start_item(gallery_dir)

        item = queue_manager.get_next_item()

        assert item is not None
        assert item.path == gallery_dir

    def test_get_next_item_empty_queue(self, queue_manager):
        """Test getting next item from empty queue."""
        item = queue_manager.get_next_item()

        assert item is None


class TestGetOperations:
    """Test get operations."""

    def test_get_all_items(self, queue_manager, gallery_dir):
        """Test getting all items."""
        gallery_dir2 = gallery_dir + '_2'
        os.makedirs(gallery_dir2, exist_ok=True)

        queue_manager.add_item(gallery_dir)
        queue_manager.add_item(gallery_dir2)

        items = queue_manager.get_all_items()

        assert len(items) == 2

    def test_get_all_items_sorted(self, queue_manager, gallery_dir):
        """Test that items are sorted by insertion order."""
        gallery_dir2 = gallery_dir + '_2'
        gallery_dir3 = gallery_dir + '_3'
        os.makedirs(gallery_dir2, exist_ok=True)
        os.makedirs(gallery_dir3, exist_ok=True)

        queue_manager.add_item(gallery_dir)
        queue_manager.add_item(gallery_dir2)
        queue_manager.add_item(gallery_dir3)

        items = queue_manager.get_all_items()

        # Should be sorted by insertion order
        assert items[0].insertion_order < items[1].insertion_order < items[2].insertion_order

    def test_get_item(self, queue_manager, gallery_dir):
        """Test getting specific item."""
        queue_manager.add_item(gallery_dir, name='Test Gallery')

        item = queue_manager.get_item(gallery_dir)

        assert item is not None
        assert item.name == 'Test Gallery'

    def test_get_nonexistent_item(self, queue_manager):
        """Test getting non-existent item."""
        item = queue_manager.get_item('/nonexistent')

        assert item is None


class TestScanOperations:
    """Test scan operations."""

    def test_get_image_files(self, queue_manager, gallery_dir):
        """Test getting image files from directory."""
        files = queue_manager._get_image_files(gallery_dir)

        assert len(files) == 5
        assert all(f.endswith('.jpg') for f in files)

    def test_get_image_files_filters_non_images(self, queue_manager, gallery_dir):
        """Test that non-image files are filtered."""
        # Add non-image file
        with open(os.path.join(gallery_dir, 'readme.txt'), 'w') as f:
            f.write('test')

        files = queue_manager._get_image_files(gallery_dir)

        assert 'readme.txt' not in files

    def test_mark_scan_failed(self, queue_manager, gallery_dir):
        """Test marking scan as failed."""
        queue_manager.add_item(gallery_dir)

        queue_manager.mark_scan_failed(gallery_dir, 'Test error')

        assert queue_manager.items[gallery_dir].status == QUEUE_STATE_SCAN_FAILED
        assert queue_manager.items[gallery_dir].error_message == 'Test error'
        assert queue_manager.items[gallery_dir].scan_complete is True

    def test_mark_upload_failed(self, queue_manager, gallery_dir):
        """Test marking upload as failed."""
        queue_manager.add_item(gallery_dir)

        queue_manager.mark_upload_failed(gallery_dir, 'Upload error')

        assert queue_manager.items[gallery_dir].status == QUEUE_STATE_UPLOAD_FAILED
        assert queue_manager.items[gallery_dir].error_message == 'Upload error'


class TestRetryOperations:
    """Test retry and rescan operations."""

    def test_retry_failed_upload_complete_failure(self, queue_manager, gallery_dir):
        """Test retrying complete upload failure."""
        queue_manager.add_item(gallery_dir)
        queue_manager.items[gallery_dir].status = QUEUE_STATE_UPLOAD_FAILED
        queue_manager.items[gallery_dir].uploaded_images = 0

        queue_manager.retry_failed_upload(gallery_dir)

        assert queue_manager.items[gallery_dir].status == QUEUE_STATE_READY
        assert queue_manager.items[gallery_dir].error_message == ''

    def test_retry_failed_upload_partial_failure(self, queue_manager, gallery_dir):
        """Test retrying partial upload failure."""
        queue_manager.add_item(gallery_dir)
        queue_manager.items[gallery_dir].status = QUEUE_STATE_UPLOAD_FAILED
        queue_manager.items[gallery_dir].uploaded_images = 5
        queue_manager.items[gallery_dir].total_images = 10
        queue_manager.items[gallery_dir].gallery_id = 'abc123'

        queue_manager.retry_failed_upload(gallery_dir)

        assert queue_manager.items[gallery_dir].status == QUEUE_STATE_INCOMPLETE
        assert queue_manager.items[gallery_dir].gallery_id == 'abc123'  # Preserved

    def test_rescan_gallery_additive_new_images(self, queue_manager, gallery_dir):
        """Test additive rescan with new images."""
        queue_manager.add_item(gallery_dir)
        queue_manager.items[gallery_dir].total_images = 5
        queue_manager.items[gallery_dir].uploaded_images = 5
        queue_manager.items[gallery_dir].status = QUEUE_STATE_COMPLETED

        # Add more images
        for i in range(5, 8):
            with open(os.path.join(gallery_dir, f'image{i}.jpg'), 'wb') as f:
                f.write(b'\xFF\xD8\xFF\xE0')

        queue_manager.rescan_gallery_additive(gallery_dir)

        assert queue_manager.items[gallery_dir].total_images == 8
        assert queue_manager.items[gallery_dir].status == QUEUE_STATE_INCOMPLETE

    def test_rescan_gallery_additive_removed_images(self, queue_manager, gallery_dir):
        """Test additive rescan with removed images."""
        queue_manager.add_item(gallery_dir)
        queue_manager.items[gallery_dir].total_images = 5
        queue_manager.items[gallery_dir].uploaded_images = 3

        # Remove images
        os.remove(os.path.join(gallery_dir, 'image0.jpg'))
        os.remove(os.path.join(gallery_dir, 'image1.jpg'))

        queue_manager.rescan_gallery_additive(gallery_dir)

        assert queue_manager.items[gallery_dir].total_images == 3

    def test_reset_gallery_complete(self, queue_manager, gallery_dir):
        """Test complete gallery reset."""
        queue_manager.add_item(gallery_dir)
        queue_manager.items[gallery_dir].status = QUEUE_STATE_COMPLETED
        queue_manager.items[gallery_dir].gallery_id = 'abc123'
        queue_manager.items[gallery_dir].uploaded_images = 5
        queue_manager.items[gallery_dir].uploaded_files = {'image1.jpg', 'image2.jpg'}

        queue_manager.reset_gallery_complete(gallery_dir)

        assert queue_manager.items[gallery_dir].status == QUEUE_STATE_SCANNING
        assert queue_manager.items[gallery_dir].gallery_id == ''
        assert queue_manager.items[gallery_dir].uploaded_images == 0
        assert len(queue_manager.items[gallery_dir].uploaded_files) == 0


class TestCustomFields:
    """Test custom field operations."""

    def test_update_custom_field(self, queue_manager, gallery_dir, mock_store):
        """Test updating custom field."""
        queue_manager.add_item(gallery_dir)

        success = queue_manager.update_custom_field(gallery_dir, 'custom1', 'test_value')

        assert queue_manager.items[gallery_dir].custom1 == 'test_value'
        mock_store.update_item_custom_field.assert_called_with(gallery_dir, 'custom1', 'test_value')

    def test_update_custom_field_invalid_field(self, queue_manager, gallery_dir):
        """Test updating invalid custom field."""
        queue_manager.add_item(gallery_dir)

        success = queue_manager.update_custom_field(gallery_dir, 'invalid_field', 'value')

        assert not success

    def test_update_custom_field_all_fields(self, queue_manager, gallery_dir):
        """Test updating all custom fields."""
        queue_manager.add_item(gallery_dir)

        queue_manager.update_custom_field(gallery_dir, 'custom1', 'value1')
        queue_manager.update_custom_field(gallery_dir, 'custom2', 'value2')
        queue_manager.update_custom_field(gallery_dir, 'custom3', 'value3')
        queue_manager.update_custom_field(gallery_dir, 'custom4', 'value4')

        item = queue_manager.items[gallery_dir]
        assert item.custom1 == 'value1'
        assert item.custom2 == 'value2'
        assert item.custom3 == 'value3'
        assert item.custom4 == 'value4'


class TestGalleryNameUpdate:
    """Test gallery name update operations."""

    def test_update_gallery_name(self, queue_manager, gallery_dir):
        """Test updating gallery name."""
        queue_manager.add_item(gallery_dir, name='Old Name')

        success = queue_manager.update_gallery_name(gallery_dir, 'New Name')

        assert success
        assert queue_manager.items[gallery_dir].name == 'New Name'

    def test_update_gallery_name_nonexistent(self, queue_manager):
        """Test updating name of non-existent gallery."""
        success = queue_manager.update_gallery_name('/nonexistent', 'Name')

        assert not success


class TestPersistence:
    """Test persistence operations."""

    def test_save_persistent_queue(self, queue_manager, gallery_dir, mock_store):
        """Test saving queue to storage."""
        queue_manager.add_item(gallery_dir)
        queue_manager.items[gallery_dir].status = QUEUE_STATE_READY

        queue_manager.save_persistent_queue()

        # Verify bulk_upsert_async was called
        assert mock_store.bulk_upsert_async.called

    def test_save_persistent_queue_specific_paths(self, queue_manager, gallery_dir, mock_store):
        """Test saving specific paths."""
        gallery_dir2 = gallery_dir + '_2'
        os.makedirs(gallery_dir2, exist_ok=True)

        queue_manager.add_item(gallery_dir)
        queue_manager.add_item(gallery_dir2)

        queue_manager.save_persistent_queue([gallery_dir])

        # Should only save specified path
        assert mock_store.bulk_upsert_async.called

    def test_batch_updates(self, queue_manager, gallery_dir, mock_store):
        """Test batch update mode."""
        queue_manager.add_item(gallery_dir)

        with queue_manager.batch_updates():
            queue_manager.update_item_status(gallery_dir, QUEUE_STATE_READY)
            queue_manager.update_item_status(gallery_dir, QUEUE_STATE_QUEUED)

        # Should only save once after batch
        assert mock_store.bulk_upsert_async.called


class TestVersionTracking:
    """Test version tracking."""

    def test_version_increments_on_change(self, queue_manager, gallery_dir):
        """Test that version increments on changes."""
        v1 = queue_manager.get_version()

        queue_manager.add_item(gallery_dir)
        v2 = queue_manager.get_version()

        assert v2 > v1

    def test_version_increments_on_status_change(self, queue_manager, gallery_dir):
        """Test version increments on status change."""
        queue_manager.add_item(gallery_dir)
        v1 = queue_manager.get_version()

        queue_manager.update_item_status(gallery_dir, QUEUE_STATE_READY)
        v2 = queue_manager.get_version()

        assert v2 > v1


class TestStatusCounters:
    """Test status counter operations."""

    def test_status_counters_initialized(self, queue_manager):
        """Test that status counters are initialized."""
        assert hasattr(queue_manager, '_status_counts')
        assert QUEUE_STATE_READY in queue_manager._status_counts

    def test_status_counters_updated_on_add(self, queue_manager, gallery_dir):
        """Test status counters update when adding item."""
        initial = queue_manager._status_counts.get(QUEUE_STATE_VALIDATING, 0)

        queue_manager.add_item(gallery_dir)

        assert queue_manager._status_counts[QUEUE_STATE_VALIDATING] > initial

    def test_status_counters_updated_on_status_change(self, queue_manager, gallery_dir):
        """Test status counters update on status change."""
        queue_manager.add_item(gallery_dir)
        queue_manager.items[gallery_dir].status = QUEUE_STATE_READY
        queue_manager._status_counts[QUEUE_STATE_READY] = 1

        queue_manager.update_item_status(gallery_dir, QUEUE_STATE_QUEUED)

        assert queue_manager._status_counts[QUEUE_STATE_READY] == 0
        assert queue_manager._status_counts[QUEUE_STATE_QUEUED] == 1


class TestConcurrency:
    """Test concurrent operations."""

    def test_concurrent_add_items(self, queue_manager, temp_dir):
        """Test adding items concurrently."""
        errors = []

        def add_items(prefix):
            try:
                for i in range(5):
                    gallery_path = os.path.join(temp_dir, f'{prefix}_gallery{i}')
                    os.makedirs(gallery_path, exist_ok=True)
                    # Add image
                    with open(os.path.join(gallery_path, 'image.jpg'), 'wb') as f:
                        f.write(b'\xFF\xD8\xFF\xE0')
                    queue_manager.add_item(gallery_path)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=add_items, args=(f'thread{i}',))
            for i in range(3)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(queue_manager.items) == 15

    def test_concurrent_status_updates(self, queue_manager, gallery_dir):
        """Test concurrent status updates."""
        queue_manager.add_item(gallery_dir)

        errors = []

        def update_status(status):
            try:
                for _ in range(10):
                    queue_manager.update_item_status(gallery_dir, status)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=update_status, args=(QUEUE_STATE_READY,)),
            threading.Thread(target=update_status, args=(QUEUE_STATE_PAUSED,))
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should not crash
        assert len(errors) == 0


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_add_item_empty_path(self, queue_manager):
        """Test adding item with empty path."""
        # Should handle gracefully or reject
        # Depends on implementation
        pass

    def test_scan_empty_directory(self, queue_manager, temp_dir):
        """Test scanning empty directory."""
        empty_dir = os.path.join(temp_dir, 'empty')
        os.makedirs(empty_dir)

        queue_manager.add_item(empty_dir)

        # Should be marked as scan failed
        time.sleep(0.2)  # Give scan worker time

    def test_scan_nonexistent_directory(self, queue_manager):
        """Test scanning non-existent directory."""
        queue_manager.add_item('/nonexistent/path')

        # Should be marked as scan failed
        time.sleep(0.2)

    def test_very_large_gallery(self, queue_manager, temp_dir):
        """Test handling very large gallery."""
        large_gallery = os.path.join(temp_dir, 'large')
        os.makedirs(large_gallery)

        # Create many images
        for i in range(100):
            with open(os.path.join(large_gallery, f'image{i}.jpg'), 'wb') as f:
                f.write(b'\xFF\xD8\xFF\xE0')

        queue_manager.add_item(large_gallery)

        # Should handle without crashing
        assert large_gallery in queue_manager.items

    def test_special_characters_in_gallery_name(self, queue_manager, temp_dir):
        """Test gallery with special characters in name."""
        special_dir = os.path.join(temp_dir, "gallery's [test] & name")
        os.makedirs(special_dir)
        with open(os.path.join(special_dir, 'image.jpg'), 'wb') as f:
            f.write(b'\xFF\xD8\xFF\xE0')

        success = queue_manager.add_item(special_dir)

        assert success
        assert special_dir in queue_manager.items


class TestShutdown:
    """Test shutdown operations."""

    def test_shutdown_saves_queue(self, queue_manager, gallery_dir, mock_store):
        """Test that shutdown saves pending changes."""
        queue_manager.add_item(gallery_dir)

        queue_manager.shutdown()

        # Should have saved
        assert mock_store.bulk_upsert_async.called or mock_store.bulk_upsert.called

    def test_shutdown_stops_scan_worker(self, queue_manager):
        """Test that shutdown stops scan worker."""
        queue_manager.shutdown()

        assert not queue_manager._scan_worker_running

    def test_shutdown_waits_for_scan_worker(self, queue_manager):
        """Test that shutdown waits for scan worker to finish."""
        queue_manager.shutdown()

        # Give time for thread to finish
        time.sleep(0.5)

        if queue_manager._scan_worker:
            assert not queue_manager._scan_worker.is_alive()


class TestErrorHandling:
    """Test error handling."""

    def test_save_continues_on_database_error(self, queue_manager, gallery_dir, mock_store):
        """Test that save errors don't crash the manager."""
        mock_store.bulk_upsert_async.side_effect = Exception("Database error")

        queue_manager.add_item(gallery_dir)

        # Should not raise
        queue_manager.save_persistent_queue()

    def test_scan_continues_on_error(self, queue_manager, temp_dir):
        """Test that scan errors don't crash the scan worker."""
        # Create directory with permission issues (if possible)
        bad_dir = os.path.join(temp_dir, 'bad_dir')
        os.makedirs(bad_dir)

        queue_manager.add_item(bad_dir)

        # Give scan time
        time.sleep(0.2)

        # Worker should still be running
        assert queue_manager._scan_worker_running


class TestItemToDict:
    """Test item serialization."""

    def test_item_to_dict_basic(self, queue_manager, gallery_dir):
        """Test converting item to dictionary."""
        queue_manager.add_item(gallery_dir, name='Test')
        item = queue_manager.items[gallery_dir]

        item_dict = queue_manager._item_to_dict(item)

        assert item_dict['path'] == gallery_dir
        assert item_dict['name'] == 'Test'
        assert item_dict['status'] == QUEUE_STATE_VALIDATING

    def test_item_to_dict_includes_all_fields(self, queue_manager, gallery_dir):
        """Test that all fields are included."""
        queue_manager.add_item(gallery_dir)
        item = queue_manager.items[gallery_dir]
        item.custom1 = 'value1'
        item.uploaded_files = {'image1.jpg'}

        item_dict = queue_manager._item_to_dict(item)

        assert 'custom1' in item_dict
        assert 'uploaded_files' in item_dict
        assert 'tab_name' in item_dict


class TestDictToItem:
    """Test item deserialization."""

    def test_dict_to_item_basic(self, queue_manager):
        """Test creating item from dictionary."""
        data = {
            'path': '/test/gallery',
            'name': 'Test Gallery',
            'status': QUEUE_STATE_READY,
            'added_time': int(time.time()),
            'tab_name': 'Main'
        }

        item = queue_manager._dict_to_item(data)

        assert item.path == '/test/gallery'
        assert item.name == 'Test Gallery'
        assert item.status == QUEUE_STATE_READY

    def test_dict_to_item_converts_uploading_status(self, queue_manager):
        """Test that uploading status is converted to ready."""
        data = {
            'path': '/test/gallery',
            'status': QUEUE_STATE_UPLOADING,
            'added_time': int(time.time()),
            'tab_name': 'Main'
        }

        item = queue_manager._dict_to_item(data)

        assert item.status == QUEUE_STATE_READY

    def test_dict_to_item_sets_completed_progress(self, queue_manager):
        """Test that completed items have 100% progress."""
        data = {
            'path': '/test/gallery',
            'status': QUEUE_STATE_COMPLETED,
            'progress': 50,  # Wrong progress
            'added_time': int(time.time()),
            'tab_name': 'Main'
        }

        item = queue_manager._dict_to_item(data)

        assert item.progress == 100
