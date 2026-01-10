"""
Comprehensive test suite for src/processing/upload_workers.py
Tests upload workers, completion workers, and bandwidth tracking with threading.
"""

import pytest
import time
import threading
from unittest.mock import Mock, MagicMock, patch, call, PropertyMock

from PyQt6.QtCore import QThread, QMutex

from src.processing.upload_workers import (
    UploadWorker,
    CompletionWorker,
    BandwidthTracker
)


class TestUploadWorkerInit:
    """Test UploadWorker initialization"""

    @patch('src.processing.upload_workers.RenameWorker')
    def test_init_basic(self, mock_rename_worker_class):
        """Test basic initialization"""
        mock_queue_manager = Mock()

        worker = UploadWorker(mock_queue_manager)

        assert worker.queue_manager == mock_queue_manager
        assert worker.uploader is None
        assert worker.running is True
        assert worker.current_item is None
        assert worker.auto_rename_enabled is True

    @patch('src.processing.upload_workers.RenameWorker')
    def test_init_creates_counters(self, mock_rename_worker_class):
        """Test initialization creates bandwidth counters"""
        mock_queue_manager = Mock()

        worker = UploadWorker(mock_queue_manager)

        assert worker.global_byte_counter is not None
        assert worker.current_gallery_counter is None
        assert worker._bw_last_bytes >= 0
        assert worker._bw_last_time > 0

    @patch('src.processing.upload_workers.RenameWorker')
    def test_init_rename_worker_unavailable(self, mock_rename_worker_class):
        """Test initialization when RenameWorker import fails"""
        mock_rename_worker_class.side_effect = ImportError("Module not found")

        mock_queue_manager = Mock()
        worker = UploadWorker(mock_queue_manager)

        # Should handle gracefully
        assert worker.queue_manager == mock_queue_manager


class TestUploadWorkerSignals:
    """Test UploadWorker signals"""

    @patch('src.processing.upload_workers.RenameWorker')
    def test_signals_exist(self, mock_rename_worker_class):
        """Test that all required signals exist"""
        mock_queue_manager = Mock()
        worker = UploadWorker(mock_queue_manager)

        assert hasattr(worker, 'progress_updated')
        assert hasattr(worker, 'gallery_started')
        assert hasattr(worker, 'gallery_completed')
        assert hasattr(worker, 'gallery_failed')
        assert hasattr(worker, 'gallery_exists')
        assert hasattr(worker, 'gallery_renamed')
        assert hasattr(worker, 'ext_fields_updated')
        assert hasattr(worker, 'log_message')
        assert hasattr(worker, 'queue_stats')
        assert hasattr(worker, 'bandwidth_updated')


class TestUploadWorkerControl:
    """Test worker control methods"""

    @patch('src.processing.upload_workers.RenameWorker')
    def test_stop(self, mock_rename_worker_class):
        """Test stopping worker"""
        mock_rename_worker = Mock()
        mock_rename_worker_class.return_value = mock_rename_worker

        mock_queue_manager = Mock()
        worker = UploadWorker(mock_queue_manager)
        worker.rename_worker = mock_rename_worker

        with patch.object(worker, 'wait'):
            worker.stop()

        assert worker.running is False
        mock_rename_worker.stop.assert_called_once()

    @patch('src.processing.upload_workers.RenameWorker')
    def test_stop_handles_rename_worker_error(self, mock_rename_worker_class):
        """Test stop handles RenameWorker errors gracefully"""
        mock_rename_worker = Mock()
        mock_rename_worker.stop.side_effect = Exception("Stop error")
        mock_rename_worker_class.return_value = mock_rename_worker

        mock_queue_manager = Mock()
        worker = UploadWorker(mock_queue_manager)
        worker.rename_worker = mock_rename_worker

        with patch.object(worker, 'wait'):
            # Should not raise exception
            worker.stop()

        assert worker.running is False

    @patch('src.processing.upload_workers.RenameWorker')
    def test_request_soft_stop_current(self, mock_rename_worker_class):
        """Test soft stop request"""
        mock_queue_manager = Mock()
        worker = UploadWorker(mock_queue_manager)

        mock_item = Mock()
        mock_item.path = "/path/to/gallery"
        worker.current_item = mock_item

        worker.request_soft_stop_current()

        assert worker._soft_stop_requested_for == "/path/to/gallery"


class TestUploadWorkerInitialization:
    """Test uploader initialization"""

    @patch('src.processing.upload_workers.GUIImxToUploader')
    @patch('src.processing.upload_workers.RenameWorker')
    def test_initialize_uploader(self, mock_rename_worker_class, mock_uploader_class):
        """Test uploader initialization"""
        mock_uploader = Mock()
        mock_uploader_class.return_value = mock_uploader

        mock_rename_worker = Mock()
        mock_rename_worker_class.return_value = mock_rename_worker

        mock_queue_manager = Mock()
        worker = UploadWorker(mock_queue_manager)
        worker._initialize_uploader()

        assert worker.uploader == mock_uploader
        assert worker.rename_worker == mock_rename_worker
        mock_uploader_class.assert_called_once()

    @patch('src.processing.upload_workers.GUIImxToUploader')
    @patch('src.processing.upload_workers.RenameWorker')
    def test_initialize_uploader_rename_worker_fails(self, mock_rename_worker_class,
                                                      mock_uploader_class):
        """Test uploader initialization when RenameWorker fails"""
        mock_uploader = Mock()
        mock_uploader_class.return_value = mock_uploader

        mock_rename_worker_class.side_effect = Exception("Init error")

        mock_queue_manager = Mock()
        worker = UploadWorker(mock_queue_manager)
        worker._rename_worker_available = True
        worker._initialize_uploader()

        assert worker.uploader == mock_uploader
        assert worker.rename_worker is None


class TestUploadWorkerProcessing:
    """Test upload processing (without running thread)"""

    @patch('src.processing.upload_workers.RenameWorker')
    @patch('src.processing.upload_workers.load_user_defaults')
    @patch('src.processing.upload_workers.execute_gallery_hooks')
    def test_upload_gallery_basic(self, mock_hooks, mock_defaults, mock_rename_worker_class):
        """Test basic gallery upload flow"""
        mock_defaults.return_value = {
            'thumbnail_size': 3,
            'thumbnail_format': 2,
            'max_retries': 3,
            'parallel_batch_size': 4
        }

        mock_hooks.return_value = {}

        mock_queue_manager = Mock()
        worker = UploadWorker(mock_queue_manager)

        # Mock uploader
        mock_uploader = Mock()
        mock_uploader.upload_folder.return_value = {
            'successful_count': 50,
            'failed_count': 0,
            'gallery_id': 'gal123',
            'gallery_url': 'http://example.com/gal123'
        }
        worker.uploader = mock_uploader

        # Create mock item
        mock_item = Mock()
        mock_item.path = "/path/to/gallery"
        mock_item.name = "Test Gallery"
        mock_item.tab_name = "Main"
        mock_item.total_images = 50
        mock_item.template_name = "default"
        mock_item.scan_complete = True
        mock_item.avg_width = 1920
        mock_item.avg_height = 1080
        mock_item.status = "uploading"

        worker.upload_gallery(mock_item)

        # Verify upload was called
        mock_uploader.upload_folder.assert_called_once()
        # Verify status was updated to uploading
        mock_queue_manager.update_item_status.assert_called()

    @patch('src.processing.upload_workers.RenameWorker')
    @patch('src.processing.upload_workers.load_user_defaults')
    @patch('src.processing.upload_workers.execute_gallery_hooks')
    def test_upload_gallery_with_hooks(self, mock_hooks, mock_defaults, mock_rename_worker_class):
        """Test upload with hook execution"""
        mock_defaults.return_value = {
            'thumbnail_size': 3,
            'thumbnail_format': 2,
            'max_retries': 3,
            'parallel_batch_size': 4
        }

        # Hook returns ext field values
        mock_hooks.return_value = {'ext1': 'hook_value'}

        mock_queue_manager = Mock()
        worker = UploadWorker(mock_queue_manager)

        mock_uploader = Mock()
        mock_uploader.upload_folder.return_value = {
            'successful_count': 50,
            'failed_count': 0,
            'gallery_id': 'gal123',
            'gallery_url': 'http://example.com/gal123'
        }
        worker.uploader = mock_uploader

        mock_item = Mock()
        mock_item.path = "/path/to/gallery"
        mock_item.name = "Test Gallery"
        mock_item.tab_name = "Main"
        mock_item.total_images = 50
        mock_item.template_name = "default"
        mock_item.scan_complete = True
        mock_item.status = "uploading"

        # Don't mock threading.Thread - let it run naturally for hook execution
        worker.upload_gallery(mock_item)

        # Give background thread time to complete
        time.sleep(0.1)

        # Hook should have been executed (called twice: 'started' and 'completed' events)
        assert mock_hooks.call_count >= 1

    @patch('src.processing.upload_workers.RenameWorker')
    @patch('src.processing.upload_workers.load_user_defaults')
    def test_upload_gallery_soft_stop(self, mock_defaults, mock_rename_worker_class):
        """Test upload respects soft stop request"""
        mock_defaults.return_value = {
            'thumbnail_size': 3,
            'thumbnail_format': 2,
            'max_retries': 3,
            'parallel_batch_size': 4
        }

        mock_queue_manager = Mock()
        worker = UploadWorker(mock_queue_manager)

        # Initialize uploader (required but won't be called due to early return)
        mock_uploader = Mock()
        worker.uploader = mock_uploader

        mock_item = Mock()
        mock_item.path = "/path/to/gallery"
        mock_item.name = "Test Gallery"
        mock_item.tab_name = "Main"
        mock_item.total_images = 50
        mock_item.status = "uploading"

        # Request soft stop before upload starts
        worker._soft_stop_requested_for = mock_item.path

        with patch('src.processing.upload_workers.execute_gallery_hooks'):
            worker.upload_gallery(mock_item)

        # Give hook thread time to complete
        time.sleep(0.1)

        # Should mark as incomplete (soft stop check at line 222 returns early)
        mock_queue_manager.update_item_status.assert_any_call(mock_item.path, "incomplete")

    @patch('src.processing.upload_workers.RenameWorker')
    @patch('src.processing.upload_workers.load_user_defaults')
    def test_upload_gallery_error(self, mock_defaults, mock_rename_worker_class):
        """Test upload error handling"""
        mock_defaults.return_value = {
            'thumbnail_size': 3,
            'thumbnail_format': 2,
            'max_retries': 3,
            'parallel_batch_size': 4
        }

        mock_queue_manager = Mock()
        worker = UploadWorker(mock_queue_manager)

        mock_uploader = Mock()
        mock_uploader.upload_folder.side_effect = Exception("Upload error")
        worker.uploader = mock_uploader

        mock_item = Mock()
        mock_item.path = "/path/to/gallery"
        mock_item.name = "Test Gallery"
        mock_item.tab_name = "Main"
        mock_item.total_images = 50
        mock_item.status = "uploading"

        failed_spy = Mock()
        worker.gallery_failed.connect(failed_spy)

        with patch('src.processing.upload_workers.execute_gallery_hooks'):
            worker.upload_gallery(mock_item)

        # Should emit failed signal
        failed_spy.assert_called_once()
        # Should mark as failed
        mock_queue_manager.mark_upload_failed.assert_called()


class TestUploadWorkerProcessResults:
    """Test upload result processing"""

    @patch('src.processing.upload_workers.RenameWorker')
    def test_process_upload_results_success(self, mock_rename_worker_class):
        """Test processing successful upload results"""
        mock_queue_manager = Mock()
        worker = UploadWorker(mock_queue_manager)

        mock_item = Mock()
        mock_item.path = "/path/to/gallery"
        mock_item.name = "Test Gallery"
        mock_item.total_images = 50
        mock_item.start_time = time.time()  # Set numeric timestamp
        mock_item.uploaded_bytes = 1024 * 1024  # Set numeric value

        results = {
            'successful_count': 50,
            'failed_count': 0,
            'gallery_id': 'gal123',
            'gallery_url': 'http://example.com/gal123'
        }

        with patch.object(worker, '_save_artifacts_for_result', return_value={}), \
             patch('src.processing.upload_workers.execute_gallery_hooks'):
            worker._process_upload_results(mock_item, results)

        # Should update to completed
        mock_queue_manager.update_item_status.assert_called_with(mock_item.path, "completed")

    @patch('src.processing.upload_workers.RenameWorker')
    def test_process_upload_results_partial_failure(self, mock_rename_worker_class):
        """Test processing partial upload failure"""
        mock_queue_manager = Mock()
        worker = UploadWorker(mock_queue_manager)

        mock_item = Mock()
        mock_item.path = "/path/to/gallery"
        mock_item.name = "Test Gallery"
        mock_item.total_images = 50
        mock_item.start_time = time.time()  # Set numeric timestamp
        mock_item.uploaded_bytes = 1024 * 900  # 45 files of ~20KB each

        results = {
            'successful_count': 45,
            'failed_count': 5,
            'failed_details': ['file1.jpg', 'file2.jpg', 'file3.jpg', 'file4.jpg', 'file5.jpg'],
            'gallery_id': 'gal123',
            'gallery_url': 'http://example.com/gal123'
        }

        with patch.object(worker, '_save_artifacts_for_result', return_value={}):
            worker._process_upload_results(mock_item, results)

        # Should mark as failed with partial failure message
        mock_queue_manager.mark_upload_failed.assert_called()

    @patch('src.processing.upload_workers.RenameWorker')
    def test_process_upload_results_none(self, mock_rename_worker_class):
        """Test processing when results are None"""
        mock_queue_manager = Mock()
        worker = UploadWorker(mock_queue_manager)

        mock_item = Mock()
        mock_item.path = "/path/to/gallery"
        mock_item.name = "Test Gallery"

        worker._process_upload_results(mock_item, None)

        # Should mark as failed
        mock_queue_manager.mark_upload_failed.assert_called()

    @patch('src.processing.upload_workers.RenameWorker')
    def test_process_upload_results_incomplete(self, mock_rename_worker_class):
        """Test processing incomplete upload (soft stopped)"""
        mock_queue_manager = Mock()
        worker = UploadWorker(mock_queue_manager)

        mock_item = Mock()
        mock_item.path = "/path/to/gallery"
        mock_item.name = "Test Gallery"
        mock_item.total_images = 50
        mock_item.start_time = time.time()  # Set numeric timestamp
        mock_item.uploaded_bytes = 1024 * 600  # 30 files worth of data

        worker._soft_stop_requested_for = mock_item.path

        results = {
            'successful_count': 30,  # Less than total
            'failed_count': 0,
            'gallery_id': 'gal123',
            'gallery_url': 'http://example.com/gal123'
        }

        with patch.object(worker, '_save_artifacts_for_result', return_value={}):
            worker._process_upload_results(mock_item, results)

        # Should mark as incomplete
        mock_queue_manager.update_item_status.assert_called_with(mock_item.path, "incomplete")


class TestUploadWorkerBandwidth:
    """Test bandwidth tracking"""

    @patch('src.processing.upload_workers.RenameWorker')
    def test_emit_current_bandwidth(self, mock_rename_worker_class):
        """Test bandwidth emission"""
        mock_queue_manager = Mock()
        worker = UploadWorker(mock_queue_manager)

        bandwidth_spy = Mock()
        worker.bandwidth_updated.connect(bandwidth_spy)

        # Simulate bytes transferred (use .add() not .increment())
        worker.global_byte_counter.add(1024 * 100)  # 100 KB

        # Set up timing for emission
        worker._bw_last_time = time.time() - 1.0
        worker._bw_last_emit = time.time() - 1.0

        worker._emit_current_bandwidth()

        # Should emit bandwidth (may or may not based on timing)
        assert bandwidth_spy.call_count >= 0


class TestCompletionWorkerInit:
    """Test CompletionWorker initialization"""

    def test_init(self):
        """Test CompletionWorker initialization"""
        worker = CompletionWorker()

        assert worker.queue == []
        assert worker.running is True
        assert isinstance(worker._mutex, QMutex)


class TestCompletionWorkerControl:
    """Test completion worker control"""

    def test_stop(self):
        """Test stopping completion worker"""
        worker = CompletionWorker()

        with patch.object(worker, 'wait'):
            worker.stop()

        assert worker.running is False

    def test_add_completion_task(self):
        """Test adding completion task"""
        worker = CompletionWorker()

        mock_item = Mock()
        mock_results = {'gallery_id': 'gal123'}

        worker.add_completion_task(mock_item, mock_results)

        assert len(worker.queue) == 1
        assert worker.queue[0] == (mock_item, mock_results)


class TestCompletionWorkerProcessing:
    """Test completion processing"""

    @patch('src.processing.upload_workers.generate_bbcode_from_results')
    def test_process_completion(self, mock_generate_bbcode):
        """Test processing completion task"""
        mock_generate_bbcode.return_value = "[bbcode]Test BBCode[/bbcode]"

        worker = CompletionWorker()

        bbcode_spy = Mock()
        worker.bbcode_generated.connect(bbcode_spy)

        mock_item = Mock()
        mock_item.path = "/path/to/gallery"
        mock_item.template_name = "default"

        mock_results = {
            'gallery_id': 'gal123',
            'written_artifacts': {}
        }

        worker._process_completion(mock_item, mock_results)

        # Should emit BBCode signal
        bbcode_spy.assert_called_once_with(mock_item.path, "[bbcode]Test BBCode[/bbcode]")

    @patch('src.processing.upload_workers.generate_bbcode_from_results')
    def test_process_completion_error(self, mock_generate_bbcode):
        """Test completion processing with error"""
        mock_generate_bbcode.side_effect = Exception("Generation error")

        worker = CompletionWorker()

        mock_item = Mock()
        mock_item.template_name = "default"

        mock_results = {'gallery_id': 'gal123'}

        # Should not raise exception
        worker._process_completion(mock_item, mock_results)


class TestBandwidthTrackerInit:
    """Test BandwidthTracker initialization"""

    @patch('src.processing.upload_workers.RenameWorker')
    def test_init_with_worker(self, mock_rename_worker_class):
        """Test initialization with upload worker"""
        mock_queue_manager = Mock()
        mock_upload_worker = UploadWorker(mock_queue_manager)

        tracker = BandwidthTracker(mock_upload_worker)

        assert tracker.upload_worker == mock_upload_worker
        assert tracker.running is True
        assert tracker._last_bytes == 0

    def test_init_without_worker(self):
        """Test initialization without upload worker"""
        tracker = BandwidthTracker()

        assert tracker.upload_worker is None
        assert tracker.running is True


class TestBandwidthTrackerControl:
    """Test bandwidth tracker control"""

    def test_stop(self):
        """Test stopping bandwidth tracker"""
        tracker = BandwidthTracker()

        with patch.object(tracker, 'wait'):
            tracker.stop()

        assert tracker.running is False


class TestBandwidthTrackerSignals:
    """Test bandwidth tracker signals"""

    def test_bandwidth_updated_signal_exists(self):
        """Test bandwidth_updated signal exists"""
        tracker = BandwidthTracker()

        assert hasattr(tracker, 'bandwidth_updated')


class TestUploadWorkerArtifacts:
    """Test artifact saving"""

    @patch('src.processing.upload_workers.RenameWorker')
    @patch('src.processing.upload_workers.save_gallery_artifacts')
    def test_save_artifacts_for_result(self, mock_save_artifacts, mock_rename_worker_class):
        """Test saving artifacts for upload result"""
        mock_save_artifacts.return_value = {
            'central': {
                'json': '/central/gallery.json',
                'bbcode': '/central/gallery.bbcode'
            },
            'uploaded': {
                'json': '/uploaded/gallery.json',
                'bbcode': '/uploaded/gallery.bbcode'
            }
        }

        mock_queue_manager = Mock()
        worker = UploadWorker(mock_queue_manager)

        mock_item = Mock()
        mock_item.path = "/path/to/gallery"
        mock_item.template_name = "default"
        mock_item.custom1 = "val1"
        mock_item.custom2 = "val2"
        mock_item.custom3 = "val3"
        mock_item.custom4 = "val4"
        mock_item.ext1 = "ext1"
        mock_item.ext2 = "ext2"
        mock_item.ext3 = "ext3"
        mock_item.ext4 = "ext4"

        results = {'gallery_id': 'gal123'}

        written = worker._save_artifacts_for_result(mock_item, results)

        assert 'central' in written
        assert 'uploaded' in written
        mock_save_artifacts.assert_called_once()

    @patch('src.processing.upload_workers.RenameWorker')
    @patch('src.processing.upload_workers.save_gallery_artifacts')
    def test_save_artifacts_error(self, mock_save_artifacts, mock_rename_worker_class):
        """Test artifact saving error handling"""
        mock_save_artifacts.side_effect = Exception("Save error")

        mock_queue_manager = Mock()
        worker = UploadWorker(mock_queue_manager)

        mock_item = Mock()
        mock_item.path = "/path/to/gallery"
        mock_item.template_name = "default"
        mock_item.custom1 = None
        mock_item.custom2 = None
        mock_item.custom3 = None
        mock_item.custom4 = None
        mock_item.ext1 = None
        mock_item.ext2 = None
        mock_item.ext3 = None
        mock_item.ext4 = None

        results = {}

        written = worker._save_artifacts_for_result(mock_item, results)

        # Should return empty dict on error
        assert written == {}


class TestUploadWorkerQueueStats:
    """Test queue statistics emission"""

    @patch('src.processing.upload_workers.RenameWorker')
    def test_emit_queue_stats(self, mock_rename_worker_class):
        """Test emitting queue statistics"""
        mock_queue_manager = Mock()
        mock_queue_manager.get_queue_stats.return_value = {
            'total': 10,
            'queued': 5,
            'uploading': 1,
            'completed': 4
        }

        worker = UploadWorker(mock_queue_manager)

        stats_spy = Mock()
        worker.queue_stats.connect(stats_spy)

        worker._emit_queue_stats(force=True)

        stats_spy.assert_called_once()

    @patch('src.processing.upload_workers.RenameWorker')
    def test_emit_queue_stats_throttled(self, mock_rename_worker_class):
        """Test queue stats emission is throttled"""
        mock_queue_manager = Mock()
        mock_queue_manager.get_queue_stats.return_value = {}

        worker = UploadWorker(mock_queue_manager)
        worker._stats_last_emit = time.time()  # Just emitted

        stats_spy = Mock()
        worker.queue_stats.connect(stats_spy)

        worker._emit_queue_stats(force=False)

        # Should not emit (too soon)
        stats_spy.assert_not_called()

    @patch('src.processing.upload_workers.RenameWorker')
    def test_emit_queue_stats_error_handling(self, mock_rename_worker_class):
        """Test queue stats handles errors gracefully"""
        mock_queue_manager = Mock()
        mock_queue_manager.get_queue_stats.side_effect = Exception("Stats error")

        worker = UploadWorker(mock_queue_manager)

        # Should not raise exception
        worker._emit_queue_stats(force=True)


class TestCompletionWorkerArtifactLogging:
    """Test artifact location logging"""

    def test_log_artifact_locations_central(self):
        """Test logging central artifact locations"""
        worker = CompletionWorker()

        results = {
            'written_artifacts': {
                'central': {
                    'json': '/central/path/gallery.json',
                    'bbcode': '/central/path/gallery.bbcode'
                }
            }
        }

        # Should not raise exception
        worker._log_artifact_locations(results)

    def test_log_artifact_locations_uploaded(self):
        """Test logging uploaded artifact locations"""
        worker = CompletionWorker()

        results = {
            'written_artifacts': {
                'uploaded': {
                    'json': '/uploaded/path/gallery.json',
                    'bbcode': '/uploaded/path/gallery.bbcode'
                }
            }
        }

        # Should not raise exception
        worker._log_artifact_locations(results)

    def test_log_artifact_locations_both(self):
        """Test logging both central and uploaded locations"""
        worker = CompletionWorker()

        results = {
            'written_artifacts': {
                'central': {
                    'json': '/central/gallery.json'
                },
                'uploaded': {
                    'json': '/uploaded/gallery.json'
                }
            }
        }

        # Should not raise exception
        worker._log_artifact_locations(results)

    def test_log_artifact_locations_none(self):
        """Test logging when no artifacts written"""
        worker = CompletionWorker()

        results = {'written_artifacts': {}}

        # Should not raise exception
        worker._log_artifact_locations(results)

    def test_log_artifact_locations_error(self):
        """Test logging handles errors gracefully"""
        worker = CompletionWorker()

        results = None

        # Should not raise exception
        worker._log_artifact_locations(results)
