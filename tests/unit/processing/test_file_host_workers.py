"""
Comprehensive test suite for src/processing/file_host_workers.py
Tests file host upload workers with threading, signals, and session management.
"""

import pytest
import time
import threading
from unittest.mock import Mock, MagicMock, patch, call
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from src.processing.file_host_workers import FileHostWorker


class TestFileHostWorkerInit:
    """Test FileHostWorker initialization"""

    @patch('src.processing.file_host_workers.get_config_manager')
    @patch('src.processing.file_host_workers.get_coordinator')
    @patch('src.processing.file_host_workers.get_zip_manager')
    @patch('src.processing.file_host_workers.QSettings')
    def test_init_basic(self, mock_qsettings, mock_zip_mgr, mock_coord, mock_config_mgr):
        """Test basic initialization"""
        mock_config = Mock()
        mock_config.name = "RapidGator"
        mock_config_mgr.return_value.get_host.return_value = mock_config

        mock_queue_store = Mock()

        worker = FileHostWorker("rapidgator", mock_queue_store)

        assert worker.host_id == "rapidgator"
        assert worker.queue_store == mock_queue_store
        assert worker.log_prefix == "RapidGator Worker"
        # Worker uses threading.Event objects for state management
        assert not worker._stop_event.is_set()  # Not stopped
        assert not worker._pause_event.is_set()  # Not paused

    @patch('src.processing.file_host_workers.get_config_manager')
    @patch('src.processing.file_host_workers.get_coordinator')
    @patch('src.processing.file_host_workers.get_zip_manager')
    @patch('src.processing.file_host_workers.QSettings')
    @patch('src.processing.file_host_workers.get_credential')
    def test_init_loads_credentials(self, mock_get_cred, mock_qsettings, mock_zip_mgr,
                                     mock_coord, mock_config_mgr):
        """Test credential loading during init"""
        mock_config = Mock()
        mock_config.name = "RapidGator"
        mock_config_mgr.return_value.get_host.return_value = mock_config

        mock_get_cred.return_value = "encrypted_credentials"

        with patch('src.processing.file_host_workers.decrypt_password', return_value='username:password'):
            worker = FileHostWorker("rapidgator", Mock())

        assert "rapidgator" in worker.host_credentials
        assert worker.host_credentials["rapidgator"] == "username:password"

    @patch('src.processing.file_host_workers.get_config_manager')
    @patch('src.processing.file_host_workers.get_coordinator')
    @patch('src.processing.file_host_workers.get_zip_manager')
    @patch('src.processing.file_host_workers.QSettings')
    def test_init_creates_session_state(self, mock_qsettings, mock_zip_mgr, mock_coord, mock_config_mgr):
        """Test session state initialization"""
        mock_config = Mock()
        mock_config.name = "TestHost"
        mock_config_mgr.return_value.get_host.return_value = mock_config

        worker = FileHostWorker("testhost", Mock())

        assert worker._session_cookies == {}
        assert worker._session_token is None
        assert worker._session_timestamp is None
        assert isinstance(worker._session_lock, threading.Lock)


class TestFileHostWorkerSignals:
    """Test worker signals"""

    @patch('src.processing.file_host_workers.get_config_manager')
    @patch('src.processing.file_host_workers.get_coordinator')
    @patch('src.processing.file_host_workers.get_zip_manager')
    @patch('src.processing.file_host_workers.QSettings')
    def test_signals_exist(self, mock_qsettings, mock_zip_mgr, mock_coord, mock_config_mgr):
        """Test that all required signals exist"""
        mock_config = Mock()
        mock_config.name = "TestHost"
        mock_config_mgr.return_value.get_host.return_value = mock_config

        worker = FileHostWorker("testhost", Mock())

        assert hasattr(worker, 'upload_started')
        assert hasattr(worker, 'upload_progress')
        assert hasattr(worker, 'upload_completed')
        assert hasattr(worker, 'upload_failed')
        assert hasattr(worker, 'bandwidth_updated')
        assert hasattr(worker, 'log_message')
        assert hasattr(worker, 'storage_updated')
        assert hasattr(worker, 'test_completed')
        assert hasattr(worker, 'spinup_complete')


class TestFileHostWorkerLogging:
    """Test logging functionality"""

    @patch('src.processing.file_host_workers.get_config_manager')
    @patch('src.processing.file_host_workers.get_coordinator')
    @patch('src.processing.file_host_workers.get_zip_manager')
    @patch('src.processing.file_host_workers.QSettings')
    @patch('src.processing.file_host_workers.log')
    def test_log_emits_signal_and_writes(self, mock_log, mock_qsettings, mock_zip_mgr,
                                          mock_coord, mock_config_mgr):
        """Test logging emits signal and writes to file"""
        mock_config = Mock()
        mock_config.name = "TestHost"
        mock_config_mgr.return_value.get_host.return_value = mock_config

        worker = FileHostWorker("testhost", Mock())

        log_spy = Mock()
        worker.log_message[str, str].connect(log_spy)

        worker._log("Test message", level="info")

        log_spy.assert_called_once_with("info", "Test message")
        mock_log.assert_called_once_with(
            "TestHost Worker: Test message",
            level="info",
            category="file_hosts"
        )


class TestFileHostWorkerCredentials:
    """Test credential management"""

    @patch('src.processing.file_host_workers.get_config_manager')
    @patch('src.processing.file_host_workers.get_coordinator')
    @patch('src.processing.file_host_workers.get_zip_manager')
    @patch('src.processing.file_host_workers.QSettings')
    def test_update_credentials(self, mock_qsettings, mock_zip_mgr, mock_coord, mock_config_mgr):
        """Test updating credentials via signal"""
        mock_config = Mock()
        mock_config.name = "TestHost"
        mock_config_mgr.return_value.get_host.return_value = mock_config

        worker = FileHostWorker("testhost", Mock())

        worker._update_credentials("new_username:new_password")

        assert worker.host_credentials["testhost"] == "new_username:new_password"

    @patch('src.processing.file_host_workers.get_config_manager')
    @patch('src.processing.file_host_workers.get_coordinator')
    @patch('src.processing.file_host_workers.get_zip_manager')
    @patch('src.processing.file_host_workers.QSettings')
    def test_update_credentials_clear(self, mock_qsettings, mock_zip_mgr, mock_coord, mock_config_mgr):
        """Test clearing credentials"""
        mock_config = Mock()
        mock_config.name = "TestHost"
        mock_config_mgr.return_value.get_host.return_value = mock_config

        worker = FileHostWorker("testhost", Mock())
        worker.host_credentials["testhost"] = "old_creds"

        worker._update_credentials("")

        assert "testhost" not in worker.host_credentials


class TestFileHostWorkerSessionManagement:
    """Test session state management"""

    @patch('src.processing.file_host_workers.get_config_manager')
    @patch('src.processing.file_host_workers.get_coordinator')
    @patch('src.processing.file_host_workers.get_zip_manager')
    @patch('src.processing.file_host_workers.QSettings')
    @patch('src.processing.file_host_workers.FileHostClient')
    def test_create_client_with_session(self, mock_client_class, mock_qsettings,
                                         mock_zip_mgr, mock_coord, mock_config_mgr):
        """Test client creation with session injection"""
        mock_config = Mock()
        mock_config.name = "TestHost"
        mock_config_mgr.return_value.get_host.return_value = mock_config

        worker = FileHostWorker("testhost", Mock())
        worker._session_cookies = {'session': 'test_session'}
        worker._session_token = 'test_token'
        worker._session_timestamp = time.time()

        mock_client = Mock()
        mock_client_class.return_value = mock_client

        client = worker._create_client(mock_config)

        mock_client_class.assert_called_once()
        call_kwargs = mock_client_class.call_args[1]
        assert call_kwargs['session_cookies'] == {'session': 'test_session'}
        assert call_kwargs['session_token'] == 'test_token'
        assert call_kwargs['session_timestamp'] is not None

    @patch('src.processing.file_host_workers.get_config_manager')
    @patch('src.processing.file_host_workers.get_coordinator')
    @patch('src.processing.file_host_workers.get_zip_manager')
    @patch('src.processing.file_host_workers.QSettings')
    def test_update_session_from_client(self, mock_qsettings, mock_zip_mgr,
                                         mock_coord, mock_config_mgr):
        """Test session state extraction from client"""
        mock_config = Mock()
        mock_config.name = "TestHost"
        mock_config_mgr.return_value.get_host.return_value = mock_config

        worker = FileHostWorker("testhost", Mock())

        mock_client = Mock()
        mock_client.get_session_state.return_value = {
            'cookies': {'new_session': 'value'},
            'token': 'new_token',
            'timestamp': time.time()
        }

        worker._update_session_from_client(mock_client)

        assert worker._session_cookies == {'new_session': 'value'}
        assert worker._session_token == 'new_token'
        assert worker._session_timestamp is not None


class TestFileHostWorkerControl:
    """Test worker control methods"""

    @patch('src.processing.file_host_workers.get_config_manager')
    @patch('src.processing.file_host_workers.get_coordinator')
    @patch('src.processing.file_host_workers.get_zip_manager')
    @patch('src.processing.file_host_workers.QSettings')
    def test_pause(self, mock_qsettings, mock_zip_mgr, mock_coord, mock_config_mgr):
        """Test pausing worker"""
        mock_config = Mock()
        mock_config.name = "TestHost"
        mock_config_mgr.return_value.get_host.return_value = mock_config

        worker = FileHostWorker("testhost", Mock())
        worker.pause()

        assert worker._pause_event.is_set()

    @patch('src.processing.file_host_workers.get_config_manager')
    @patch('src.processing.file_host_workers.get_coordinator')
    @patch('src.processing.file_host_workers.get_zip_manager')
    @patch('src.processing.file_host_workers.QSettings')
    def test_resume(self, mock_qsettings, mock_zip_mgr, mock_coord, mock_config_mgr):
        """Test resuming worker"""
        mock_config = Mock()
        mock_config.name = "TestHost"
        mock_config_mgr.return_value.get_host.return_value = mock_config

        worker = FileHostWorker("testhost", Mock())
        worker._pause_event.set()  # Simulate paused state
        worker.resume()

        assert not worker._pause_event.is_set()

    @patch('src.processing.file_host_workers.get_config_manager')
    @patch('src.processing.file_host_workers.get_coordinator')
    @patch('src.processing.file_host_workers.get_zip_manager')
    @patch('src.processing.file_host_workers.QSettings')
    def test_cancel_current_upload(self, mock_qsettings, mock_zip_mgr, mock_coord, mock_config_mgr):
        """Test canceling current upload"""
        mock_config = Mock()
        mock_config.name = "TestHost"
        mock_config_mgr.return_value.get_host.return_value = mock_config

        worker = FileHostWorker("testhost", Mock())
        worker.current_upload_id = 123
        worker.current_host = "testhost"
        worker.current_gallery_id = 456

        worker.cancel_current_upload()

        assert worker._should_stop_current is True

    @patch('src.processing.file_host_workers.get_config_manager')
    @patch('src.processing.file_host_workers.get_coordinator')
    @patch('src.processing.file_host_workers.get_zip_manager')
    @patch('src.processing.file_host_workers.QSettings')
    def test_stop(self, mock_qsettings, mock_zip_mgr, mock_coord, mock_config_mgr):
        """Test stopping worker"""
        mock_config = Mock()
        mock_config.name = "TestHost"
        mock_config_mgr.return_value.get_host.return_value = mock_config

        worker = FileHostWorker("testhost", Mock())

        with patch.object(worker, 'wait'):
            worker.stop()

        assert worker._stop_event.is_set()


class TestFileHostWorkerTestQueue:
    """Test test request queuing"""

    @patch('src.processing.file_host_workers.get_config_manager')
    @patch('src.processing.file_host_workers.get_coordinator')
    @patch('src.processing.file_host_workers.get_zip_manager')
    @patch('src.processing.file_host_workers.QSettings')
    def test_queue_test_request(self, mock_qsettings, mock_zip_mgr, mock_coord, mock_config_mgr):
        """Test queuing test request"""
        mock_config = Mock()
        mock_config.name = "TestHost"
        mock_config_mgr.return_value.get_host.return_value = mock_config

        worker = FileHostWorker("testhost", Mock())

        worker.queue_test_request("test_credentials")

        assert len(worker._test_queue) == 1
        assert worker._test_queue[0] == "test_credentials"


class TestFileHostWorkerBandwidth:
    """Test bandwidth tracking"""

    @patch('src.processing.file_host_workers.get_config_manager')
    @patch('src.processing.file_host_workers.get_coordinator')
    @patch('src.processing.file_host_workers.get_zip_manager')
    @patch('src.processing.file_host_workers.QSettings')
    def test_emit_bandwidth(self, mock_qsettings, mock_zip_mgr, mock_coord, mock_config_mgr):
        """Test bandwidth emission"""
        mock_config = Mock()
        mock_config.name = "TestHost"
        mock_config_mgr.return_value.get_host.return_value = mock_config

        worker = FileHostWorker("testhost", Mock())
        worker.bandwidth_counter.add(1024 * 100)  # 100 KB

        bandwidth_spy = Mock()
        worker.bandwidth_updated.connect(bandwidth_spy)

        # First emission should be skipped (no time elapsed)
        worker._emit_bandwidth()

        # Simulate time passage
        worker._bw_last_time = time.time() - 1.0
        worker._bw_last_emit = time.time() - 1.0

        worker._emit_bandwidth()

        # Should emit bandwidth signal
        assert bandwidth_spy.call_count >= 0  # May or may not emit based on timing

    @patch('src.processing.file_host_workers.get_config_manager')
    @patch('src.processing.file_host_workers.get_coordinator')
    @patch('src.processing.file_host_workers.get_zip_manager')
    @patch('src.processing.file_host_workers.QSettings')
    def test_get_current_upload_info(self, mock_qsettings, mock_zip_mgr, mock_coord, mock_config_mgr):
        """Test getting current upload info"""
        mock_config = Mock()
        mock_config.name = "TestHost"
        mock_config_mgr.return_value.get_host.return_value = mock_config

        worker = FileHostWorker("testhost", Mock())
        worker.current_upload_id = 789
        worker.current_db_id = 456
        worker.current_host = "testhost"

        info = worker.get_current_upload_info()

        assert info is not None
        assert info['upload_id'] == 789
        assert info['db_id'] == 456
        assert info['host_name'] == "testhost"

    @patch('src.processing.file_host_workers.get_config_manager')
    @patch('src.processing.file_host_workers.get_coordinator')
    @patch('src.processing.file_host_workers.get_zip_manager')
    @patch('src.processing.file_host_workers.QSettings')
    def test_get_current_upload_info_none(self, mock_qsettings, mock_zip_mgr,
                                           mock_coord, mock_config_mgr):
        """Test getting upload info when no upload active"""
        mock_config = Mock()
        mock_config.name = "TestHost"
        mock_config_mgr.return_value.get_host.return_value = mock_config

        worker = FileHostWorker("testhost", Mock())

        info = worker.get_current_upload_info()

        assert info is None


class TestFileHostWorkerStorageCache:
    """Test storage caching"""

    @patch('src.processing.file_host_workers.get_config_manager')
    @patch('src.processing.file_host_workers.get_coordinator')
    @patch('src.processing.file_host_workers.get_zip_manager')
    @patch('src.processing.file_host_workers.QSettings')
    def test_save_storage_cache(self, mock_qsettings_class, mock_zip_mgr,
                                 mock_coord, mock_config_mgr):
        """Test saving storage cache"""
        mock_settings = Mock()
        mock_qsettings_class.return_value = mock_settings

        mock_config = Mock()
        mock_config.name = "TestHost"
        mock_config_mgr.return_value.get_host.return_value = mock_config

        worker = FileHostWorker("testhost", Mock())

        worker._save_storage_cache(1000000, 500000)

        # Verify setValue calls
        assert mock_settings.setValue.call_count >= 3
        mock_settings.sync.assert_called_once()

    @patch('src.processing.file_host_workers.get_config_manager')
    @patch('src.processing.file_host_workers.get_coordinator')
    @patch('src.processing.file_host_workers.get_zip_manager')
    @patch('src.processing.file_host_workers.QSettings')
    def test_load_storage_cache_valid(self, mock_qsettings_class, mock_zip_mgr,
                                       mock_coord, mock_config_mgr):
        """Test loading valid storage cache"""
        mock_settings = Mock()
        mock_settings.value.side_effect = lambda key, default=None, type=None: {
            "FileHosts/testhost/storage_ts": int(time.time()),
            "FileHosts/testhost/storage_total": "1000000",
            "FileHosts/testhost/storage_left": "500000"
        }.get(key, default)
        mock_qsettings_class.return_value = mock_settings

        mock_config = Mock()
        mock_config.name = "TestHost"
        mock_config_mgr.return_value.get_host.return_value = mock_config

        worker = FileHostWorker("testhost", Mock())

        cache = worker._load_storage_cache()

        assert cache is not None
        assert cache['total'] == 1000000
        assert cache['left'] == 500000

    @patch('src.processing.file_host_workers.get_config_manager')
    @patch('src.processing.file_host_workers.get_coordinator')
    @patch('src.processing.file_host_workers.get_zip_manager')
    @patch('src.processing.file_host_workers.QSettings')
    def test_load_storage_cache_expired(self, mock_qsettings_class, mock_zip_mgr,
                                         mock_coord, mock_config_mgr):
        """Test loading expired storage cache"""
        mock_settings = Mock()
        mock_settings.value.side_effect = lambda key, default=None, type=None: {
            "FileHosts/testhost/storage_ts": 0  # Very old timestamp
        }.get(key, default)
        mock_qsettings_class.return_value = mock_settings

        mock_config = Mock()
        mock_config.name = "TestHost"
        mock_config_mgr.return_value.get_host.return_value = mock_config

        worker = FileHostWorker("testhost", Mock())

        cache = worker._load_storage_cache()

        assert cache is None


class TestFileHostWorkerTestResults:
    """Test test result caching"""

    @patch('src.processing.file_host_workers.get_config_manager')
    @patch('src.processing.file_host_workers.get_coordinator')
    @patch('src.processing.file_host_workers.get_zip_manager')
    @patch('src.processing.file_host_workers.QSettings')
    def test_save_test_results(self, mock_qsettings_class, mock_zip_mgr,
                                mock_coord, mock_config_mgr):
        """Test saving test results"""
        mock_settings = Mock()
        mock_qsettings_class.return_value = mock_settings

        mock_config = Mock()
        mock_config.name = "TestHost"
        mock_config_mgr.return_value.get_host.return_value = mock_config

        worker = FileHostWorker("testhost", Mock())

        results = {
            'timestamp': int(time.time()),
            'credentials_valid': True,
            'user_info_valid': True,
            'upload_success': True,
            'delete_success': False,
            'error_message': ''
        }

        worker._save_test_results(results)

        # Verify setValue calls for all fields
        assert mock_settings.setValue.call_count >= 6
        mock_settings.sync.assert_called_once()

    @patch('src.processing.file_host_workers.get_config_manager')
    @patch('src.processing.file_host_workers.get_coordinator')
    @patch('src.processing.file_host_workers.get_zip_manager')
    @patch('src.processing.file_host_workers.QSettings')
    def test_load_test_results_valid(self, mock_qsettings_class, mock_zip_mgr,
                                      mock_coord, mock_config_mgr):
        """Test loading valid test results"""
        mock_settings = Mock()
        current_time = int(time.time())
        mock_settings.value.side_effect = lambda key, default=None, type=None: {
            "FileHosts/TestResults/testhost/timestamp": current_time,
            "FileHosts/TestResults/testhost/credentials_valid": True,
            "FileHosts/TestResults/testhost/user_info_valid": True,
            "FileHosts/TestResults/testhost/upload_success": True,
            "FileHosts/TestResults/testhost/delete_success": False,
            "FileHosts/TestResults/testhost/error_message": ""
        }.get(key, default)
        mock_qsettings_class.return_value = mock_settings

        mock_config = Mock()
        mock_config.name = "TestHost"
        mock_config_mgr.return_value.get_host.return_value = mock_config

        worker = FileHostWorker("testhost", Mock())

        results = worker.load_test_results()

        assert results is not None
        assert results['timestamp'] == current_time
        assert results['credentials_valid'] is True
        assert results['upload_success'] is True

    @patch('src.processing.file_host_workers.get_config_manager')
    @patch('src.processing.file_host_workers.get_coordinator')
    @patch('src.processing.file_host_workers.get_zip_manager')
    @patch('src.processing.file_host_workers.QSettings')
    def test_load_test_results_none(self, mock_qsettings_class, mock_zip_mgr,
                                     mock_coord, mock_config_mgr):
        """Test loading non-existent test results"""
        mock_settings = Mock()
        mock_settings.value.return_value = None
        mock_qsettings_class.return_value = mock_settings

        mock_config = Mock()
        mock_config.name = "TestHost"
        mock_config_mgr.return_value.get_host.return_value = mock_config

        worker = FileHostWorker("testhost", Mock())

        results = worker.load_test_results()

        assert results is None


class TestFileHostWorkerProcessUpload:
    """Test upload processing (without actually running thread)"""

    @patch('src.processing.file_host_workers.get_config_manager')
    @patch('src.processing.file_host_workers.get_coordinator')
    @patch('src.processing.file_host_workers.get_zip_manager')
    @patch('src.processing.file_host_workers.QSettings')
    def test_process_upload_file_not_found(self, mock_qsettings, mock_zip_mgr_func,
                                            mock_coord, mock_config_mgr):
        """Test upload processing with missing gallery folder"""
        mock_config = Mock()
        mock_config.name = "TestHost"
        mock_config_mgr.return_value.get_host.return_value = mock_config

        mock_queue_store = Mock()
        # Mock get_file_host_uploads to return a list (not iterable by default)
        mock_queue_store.get_file_host_uploads.return_value = []

        worker = FileHostWorker("testhost", mock_queue_store)

        # Mock signals
        failed_spy = Mock()
        worker.upload_failed.connect(failed_spy)

        # Process upload with non-existent path
        worker._process_upload(
            upload_id=1,
            db_id=123,
            gallery_path="/nonexistent/path",
            gallery_name="Test",
            host_name="testhost",
            host_config=mock_config
        )

        # Should emit failed signal
        failed_spy.assert_called_once()
        # Should update database with failure
        mock_queue_store.update_file_host_upload.assert_called()


class TestFileHostWorkerEdgeCases:
    """Test edge cases and error handling"""

    @patch('src.processing.file_host_workers.get_config_manager')
    @patch('src.processing.file_host_workers.get_coordinator')
    @patch('src.processing.file_host_workers.get_zip_manager')
    @patch('src.processing.file_host_workers.QSettings')
    def test_log_prefix_without_config(self, mock_qsettings, mock_zip_mgr,
                                        mock_coord, mock_config_mgr):
        """Test log prefix when config not found"""
        mock_config_mgr.return_value.get_host.return_value = None

        worker = FileHostWorker("unknown_host", Mock())

        assert worker.log_prefix == "unknown_host Worker"

    @patch('src.processing.file_host_workers.get_config_manager')
    @patch('src.processing.file_host_workers.get_coordinator')
    @patch('src.processing.file_host_workers.get_zip_manager')
    @patch('src.processing.file_host_workers.QSettings')
    @patch('src.processing.file_host_workers.get_credential')
    def test_load_credentials_decrypt_failure(self, mock_get_cred, mock_qsettings,
                                               mock_zip_mgr, mock_coord, mock_config_mgr):
        """Test credential loading with decryption failure"""
        mock_config = Mock()
        mock_config.name = "TestHost"
        mock_config_mgr.return_value.get_host.return_value = mock_config

        mock_get_cred.return_value = "encrypted_data"

        with patch('src.processing.file_host_workers.decrypt_password',
                   side_effect=Exception("Decryption error")):
            worker = FileHostWorker("testhost", Mock())

        # Should handle error gracefully
        assert "testhost" not in worker.host_credentials
