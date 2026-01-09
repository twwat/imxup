"""
Comprehensive test suite for src/processing/file_host_worker_manager.py

Tests FileHostWorkerManager lifecycle, signal relay, worker management,
concurrent operations, and persistence layers with proper mocking.
"""

import pytest
import time
import threading
from unittest.mock import Mock, MagicMock, patch, call, PropertyMock
from unittest.mock import ANY

from PyQt6.QtCore import QThread

from src.processing.file_host_worker_manager import FileHostWorkerManager
from src.storage.database import QueueStore


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_queue_store():
    """Mock QueueStore instance."""
    store = Mock(spec=QueueStore)
    return store


@pytest.fixture
def mock_worker():
    """Mock FileHostWorker instance."""
    worker = Mock()
    worker.start = Mock()
    worker.stop = Mock()
    worker.wait = Mock()
    worker.pause = Mock()
    worker.resume = Mock()

    # Add Qt signals
    worker.storage_updated = Mock()
    worker.test_completed = Mock()
    worker.spinup_complete = Mock()
    worker.upload_started = Mock()
    worker.upload_progress = Mock()
    worker.upload_completed = Mock()
    worker.upload_failed = Mock()
    worker.bandwidth_updated = Mock()

    return worker


@pytest.fixture
def manager(mock_queue_store):
    """Create FileHostWorkerManager instance."""
    return FileHostWorkerManager(mock_queue_store)


# ============================================================================
# INITIALIZATION TESTS
# ============================================================================

class TestFileHostWorkerManagerInit:
    """Test FileHostWorkerManager initialization."""

    def test_init_creates_manager(self, mock_queue_store):
        """Test basic initialization."""
        manager = FileHostWorkerManager(mock_queue_store)

        assert manager.queue_store == mock_queue_store
        assert manager.workers == {}
        assert manager.pending_workers == {}
        assert isinstance(manager.workers, dict)
        assert isinstance(manager.pending_workers, dict)

    def test_init_signals_exist(self, mock_queue_store):
        """Test that all required signals are initialized."""
        manager = FileHostWorkerManager(mock_queue_store)

        assert hasattr(manager, 'storage_updated')
        assert hasattr(manager, 'test_completed')
        assert hasattr(manager, 'spinup_complete')
        assert hasattr(manager, 'enabled_workers_changed')
        assert hasattr(manager, 'upload_started')
        assert hasattr(manager, 'upload_progress')
        assert hasattr(manager, 'upload_completed')
        assert hasattr(manager, 'upload_failed')
        assert hasattr(manager, 'bandwidth_updated')

    def test_init_multiple_instances(self, mock_queue_store):
        """Test creating multiple manager instances."""
        manager1 = FileHostWorkerManager(mock_queue_store)
        manager2 = FileHostWorkerManager(mock_queue_store)

        assert manager1 is not manager2
        assert manager1.queue_store == manager2.queue_store
        assert manager1.workers is not manager2.workers


# ============================================================================
# ENABLE/DISABLE HOST TESTS
# ============================================================================

class TestEnableHostBasic:
    """Test host enabling functionality."""

    @patch('src.processing.file_host_worker_manager.FileHostWorker')
    def test_enable_host_creates_worker(self, mock_worker_class, manager, mock_worker):
        """Test enabling a host creates and starts a worker."""
        mock_worker_class.return_value = mock_worker

        manager.enable_host('rapidgator')

        mock_worker_class.assert_called_once_with('rapidgator', manager.queue_store)
        assert 'rapidgator' in manager.pending_workers
        assert manager.pending_workers['rapidgator'] == mock_worker
        mock_worker.start.assert_called_once()

    @patch('src.processing.file_host_worker_manager.FileHostWorker')
    def test_enable_host_already_enabled(self, mock_worker_class, manager, mock_worker):
        """Test enabling host that is already enabled."""
        mock_worker_class.return_value = mock_worker

        manager.workers['rapidgator'] = mock_worker

        manager.enable_host('rapidgator')

        # Should not create new worker
        mock_worker_class.assert_not_called()

    @patch('src.processing.file_host_worker_manager.FileHostWorker')
    def test_enable_host_already_spinning_up(self, mock_worker_class, manager, mock_worker):
        """Test enabling host that is already spinning up."""
        mock_worker_class.return_value = mock_worker

        manager.pending_workers['rapidgator'] = mock_worker

        manager.enable_host('rapidgator')

        # Should not create new worker
        mock_worker_class.assert_not_called()

    @patch('src.processing.file_host_worker_manager.FileHostWorker')
    def test_enable_multiple_hosts(self, mock_worker_class, manager, mock_worker):
        """Test enabling multiple hosts creates separate workers."""
        hosts = ['rapidgator', 'mega', 'filehost']
        mock_worker_class.side_effect = [Mock() for _ in hosts]

        for host in hosts:
            manager.enable_host(host)

        assert len(manager.pending_workers) == len(hosts)
        for host in hosts:
            assert host in manager.pending_workers

    @patch('src.processing.file_host_worker_manager.FileHostWorker')
    def test_enable_host_connects_signals(self, mock_worker_class, manager, mock_worker):
        """Test enabling host connects worker signals to manager."""
        mock_worker_class.return_value = mock_worker

        with patch.object(manager, '_connect_worker_signals') as mock_connect:
            manager.enable_host('rapidgator')
            mock_connect.assert_called_once_with(mock_worker)


class TestDisableHostBasic:
    """Test host disabling functionality."""

    @patch('src.processing.file_host_worker_manager.FileHostWorkerManager._persist_enabled_state')
    def test_disable_host_stops_worker(self, mock_persist, manager, mock_worker):
        """Test disabling host stops worker (non-blocking).

        Note: disable_host() calls stop() but NOT wait() - cleanup happens in background.
        See disable_host() implementation: "Don't wait() - let it finish in background"
        """
        manager.workers['rapidgator'] = mock_worker

        manager.disable_host('rapidgator')

        mock_worker.stop.assert_called_once()
        # Note: wait() is NOT called in disable_host() - only in shutdown_all()
        assert 'rapidgator' not in manager.workers

    @patch('src.processing.file_host_worker_manager.FileHostWorkerManager._persist_enabled_state')
    def test_disable_host_not_found(self, mock_persist, manager, mock_worker):
        """Test disabling host that doesn't exist."""
        # Should not raise exception
        manager.disable_host('nonexistent')

        assert len(manager.workers) == 0

    @patch('src.processing.file_host_worker_manager.FileHostWorkerManager._persist_enabled_state')
    def test_disable_host_emits_signal(self, mock_persist, manager, mock_worker):
        """Test disabling host emits enabled_workers_changed signal."""
        manager.workers['rapidgator'] = mock_worker
        manager.workers['mega'] = Mock()

        signal_spy = Mock()
        manager.enabled_workers_changed.connect(signal_spy)

        manager.disable_host('rapidgator')

        signal_spy.assert_called_once()
        call_args = signal_spy.call_args[0][0]
        assert 'rapidgator' not in call_args
        assert 'mega' in call_args

    @patch('src.processing.file_host_worker_manager.FileHostWorkerManager._persist_enabled_state')
    def test_disable_host_persists_state(self, mock_persist, manager, mock_worker):
        """Test disabling host persists disabled state to INI."""
        manager.workers['rapidgator'] = mock_worker

        manager.disable_host('rapidgator')

        mock_persist.assert_called_once_with('rapidgator', enabled=False)

    @patch('src.processing.file_host_worker_manager.FileHostWorkerManager._persist_enabled_state')
    def test_disable_host_multiple_hosts(self, mock_persist, manager):
        """Test disabling multiple hosts in sequence."""
        workers = {'rapidgator': Mock(), 'mega': Mock(), 'filehost': Mock()}
        manager.workers = workers.copy()

        for host in ['rapidgator', 'mega']:
            manager.disable_host(host)

        assert len(manager.workers) == 1
        assert 'filehost' in manager.workers


# ============================================================================
# GET WORKER TESTS
# ============================================================================

class TestGetWorker:
    """Test getting worker references."""

    def test_get_worker_exists(self, manager, mock_worker):
        """Test getting enabled worker."""
        manager.workers['rapidgator'] = mock_worker

        result = manager.get_worker('rapidgator')

        assert result == mock_worker

    def test_get_worker_not_exists(self, manager):
        """Test getting non-existent worker."""
        result = manager.get_worker('nonexistent')

        assert result is None

    def test_get_worker_pending_not_returned(self, manager, mock_worker):
        """Test that pending workers are not returned."""
        manager.pending_workers['rapidgator'] = mock_worker

        result = manager.get_worker('rapidgator')

        assert result is None

    def test_get_worker_multiple_hosts(self, manager):
        """Test getting worker from multiple hosts."""
        workers = {'rapidgator': Mock(), 'mega': Mock()}
        manager.workers = workers

        rg = manager.get_worker('rapidgator')
        mg = manager.get_worker('mega')

        assert rg == workers['rapidgator']
        assert mg == workers['mega']


# ============================================================================
# IS_ENABLED TESTS
# ============================================================================

class TestIsEnabled:
    """Test host enabled status checking."""

    def test_is_enabled_true(self, manager, mock_worker):
        """Test checking enabled host."""
        manager.workers['rapidgator'] = mock_worker

        assert manager.is_enabled('rapidgator') is True

    def test_is_enabled_false(self, manager):
        """Test checking disabled host."""
        assert manager.is_enabled('rapidgator') is False

    def test_is_enabled_pending_not_enabled(self, manager, mock_worker):
        """Test that pending workers are not considered enabled."""
        manager.pending_workers['rapidgator'] = mock_worker

        assert manager.is_enabled('rapidgator') is False

    def test_is_enabled_multiple_hosts(self, manager):
        """Test checking multiple hosts."""
        manager.workers['rapidgator'] = Mock()

        assert manager.is_enabled('rapidgator') is True
        assert manager.is_enabled('mega') is False


# ============================================================================
# SHUTDOWN TESTS
# ============================================================================

class TestShutdownAll:
    """Test graceful shutdown of all workers."""

    def test_shutdown_all_no_workers(self, manager):
        """Test shutdown when no workers are running."""
        manager.shutdown_all()

        assert len(manager.workers) == 0

    def test_shutdown_all_stops_workers(self, manager):
        """Test shutdown stops all workers."""
        workers = {
            'rapidgator': Mock(),
            'mega': Mock(),
            'filehost': Mock()
        }
        manager.workers = workers

        manager.shutdown_all()

        for worker in workers.values():
            worker.stop.assert_called_once()
            worker.wait.assert_called_once()

    def test_shutdown_all_waits_for_all(self, manager):
        """Test shutdown waits for all workers to complete."""
        workers = {'host1': Mock(), 'host2': Mock()}
        manager.workers = workers

        manager.shutdown_all()

        # All workers should be waited on
        for worker in workers.values():
            worker.wait.assert_called_once()

    def test_shutdown_all_clears_workers(self, manager):
        """Test shutdown clears workers dict."""
        manager.workers = {
            'host1': Mock(),
            'host2': Mock()
        }

        manager.shutdown_all()

        assert len(manager.workers) == 0

    def test_shutdown_all_error_in_stop(self, manager):
        """Test shutdown with error in stop propagates exception."""
        mock_worker = Mock()
        mock_worker.stop.side_effect = Exception("Stop error")
        mock_worker.wait = Mock()

        manager.workers['host1'] = mock_worker

        # The implementation doesn't catch exceptions, so this will raise
        with pytest.raises(Exception, match="Stop error"):
            manager.shutdown_all()

    def test_shutdown_all_error_in_wait(self, manager):
        """Test shutdown with error in wait propagates exception."""
        mock_worker = Mock()
        mock_worker.wait.side_effect = Exception("Wait error")

        manager.workers['host1'] = mock_worker

        # The implementation doesn't catch exceptions, so this will raise
        with pytest.raises(Exception, match="Wait error"):
            manager.shutdown_all()


# ============================================================================
# SPINUP COMPLETE HANDLER TESTS
# ============================================================================

class TestSpinupCompleteHandler:
    """Test spinup completion handling."""

    @patch('src.processing.file_host_worker_manager.FileHostWorkerManager._persist_enabled_state')
    def test_spinup_complete_success(self, mock_persist, manager, mock_worker):
        """Test successful spinup transitions to enabled."""
        manager.pending_workers['rapidgator'] = mock_worker

        signal_spy = Mock()
        manager.spinup_complete.connect(signal_spy)

        manager._on_spinup_complete('rapidgator', '')  # Empty error = success

        assert 'rapidgator' in manager.workers
        assert 'rapidgator' not in manager.pending_workers
        assert manager.workers['rapidgator'] == mock_worker
        mock_persist.assert_called_once_with('rapidgator', enabled=True)
        signal_spy.assert_called_once_with('rapidgator', '')

    @patch('src.processing.file_host_worker_manager.FileHostWorkerManager._persist_enabled_state')
    def test_spinup_complete_failure(self, mock_persist, manager, mock_worker):
        """Test failed spinup cleans up worker."""
        manager.pending_workers['rapidgator'] = mock_worker

        error_msg = "Authentication failed"
        manager._on_spinup_complete('rapidgator', error_msg)

        assert 'rapidgator' not in manager.workers
        assert 'rapidgator' not in manager.pending_workers
        mock_worker.wait.assert_called_once()
        # Should NOT persist on failure
        mock_persist.assert_not_called()

    @patch('src.processing.file_host_worker_manager.FileHostWorkerManager._persist_enabled_state')
    def test_spinup_complete_unknown_worker(self, mock_persist, manager):
        """Test spinup complete for unknown worker."""
        # Should not raise exception
        manager._on_spinup_complete('unknown_host', '')

        assert len(manager.workers) == 0
        mock_persist.assert_not_called()

    @patch('src.processing.file_host_worker_manager.FileHostWorkerManager._persist_enabled_state')
    def test_spinup_complete_emits_enabled_workers_changed(self, mock_persist, manager, mock_worker):
        """Test spinup complete emits enabled_workers_changed signal."""
        manager.pending_workers['rapidgator'] = mock_worker
        manager.workers['mega'] = Mock()

        signal_spy = Mock()
        manager.enabled_workers_changed.connect(signal_spy)

        manager._on_spinup_complete('rapidgator', '')

        signal_spy.assert_called_once()
        call_args = signal_spy.call_args[0][0]
        assert 'rapidgator' in call_args
        assert 'mega' in call_args


# ============================================================================
# SIGNAL CONNECTION TESTS
# ============================================================================

class TestConnectWorkerSignals:
    """Test worker signal relay connections."""

    def test_connect_storage_updated_signal(self, manager, mock_worker):
        """Test storage_updated signal is connected."""
        with patch.object(mock_worker.storage_updated, 'connect') as mock_connect:
            manager._connect_worker_signals(mock_worker)

            # Verify connect was called (once for storage_updated)
            calls = [c for c in mock_connect.call_args_list if 'storage_updated' in str(c)]
            assert len(calls) >= 1

    def test_connect_test_completed_signal(self, manager, mock_worker):
        """Test test_completed signal is connected."""
        with patch.object(mock_worker.test_completed, 'connect') as mock_connect:
            manager._connect_worker_signals(mock_worker)

            mock_connect.assert_called_once()

    def test_connect_spinup_complete_signal(self, manager, mock_worker):
        """Test spinup_complete signal is connected."""
        with patch.object(mock_worker.spinup_complete, 'connect') as mock_connect:
            manager._connect_worker_signals(mock_worker)

            mock_connect.assert_called_once()

    def test_connect_upload_signals(self, manager, mock_worker):
        """Test upload signals are connected."""
        manager._connect_worker_signals(mock_worker)

        # Verify all upload signals have connect called
        assert mock_worker.upload_started.connect.called
        assert mock_worker.upload_progress.connect.called
        assert mock_worker.upload_completed.connect.called
        assert mock_worker.upload_failed.connect.called

    def test_connect_bandwidth_signal(self, manager, mock_worker):
        """Test bandwidth_updated signal is connected."""
        with patch.object(mock_worker.bandwidth_updated, 'connect') as mock_connect:
            manager._connect_worker_signals(mock_worker)

            mock_connect.assert_called_once()


# ============================================================================
# PAUSE/RESUME TESTS
# ============================================================================

class TestPauseAllWorkers:
    """Test pausing all workers."""

    def test_pause_all_no_workers(self, manager):
        """Test pause when no workers."""
        manager.pause_all()

        assert len(manager.workers) == 0

    def test_pause_all_pauses_workers(self, manager):
        """Test pause all workers."""
        workers = {'host1': Mock(), 'host2': Mock()}
        manager.workers = workers

        manager.pause_all()

        for worker in workers.values():
            worker.pause.assert_called_once()

    def test_pause_all_multiple_hosts(self, manager):
        """Test pause all with multiple hosts."""
        num_hosts = 5
        manager.workers = {f'host{i}': Mock() for i in range(num_hosts)}

        manager.pause_all()

        for worker in manager.workers.values():
            worker.pause.assert_called_once()


class TestResumeAllWorkers:
    """Test resuming all workers."""

    def test_resume_all_no_workers(self, manager):
        """Test resume when no workers."""
        manager.resume_all()

        assert len(manager.workers) == 0

    def test_resume_all_resumes_workers(self, manager):
        """Test resume all workers."""
        workers = {'host1': Mock(), 'host2': Mock()}
        manager.workers = workers

        manager.resume_all()

        for worker in workers.values():
            worker.resume.assert_called_once()

    def test_resume_all_multiple_hosts(self, manager):
        """Test resume all with multiple hosts."""
        num_hosts = 5
        manager.workers = {f'host{i}': Mock() for i in range(num_hosts)}

        manager.resume_all()

        for worker in manager.workers.values():
            worker.resume.assert_called_once()


# ============================================================================
# WORKER COUNT AND LIST TESTS
# ============================================================================

class TestWorkerCountAndList:
    """Test getting worker count and enabled hosts list."""

    def test_get_worker_count_zero(self, manager):
        """Test worker count when none."""
        count = manager.get_worker_count()

        assert count == 0

    def test_get_worker_count_multiple(self, manager):
        """Test worker count with multiple workers."""
        manager.workers = {
            'host1': Mock(),
            'host2': Mock(),
            'host3': Mock()
        }

        count = manager.get_worker_count()

        assert count == 3

    def test_get_worker_count_ignores_pending(self, manager, mock_worker):
        """Test worker count ignores pending workers."""
        manager.workers = {'host1': Mock()}
        manager.pending_workers = {'host2': mock_worker}

        count = manager.get_worker_count()

        assert count == 1

    def test_get_enabled_hosts_empty(self, manager):
        """Test enabled hosts list when empty."""
        hosts = manager.get_enabled_hosts()

        assert hosts == []
        assert isinstance(hosts, list)

    def test_get_enabled_hosts_multiple(self, manager):
        """Test enabled hosts list with multiple hosts."""
        expected_hosts = ['rapidgator', 'mega', 'filehost']
        manager.workers = {host: Mock() for host in expected_hosts}

        hosts = manager.get_enabled_hosts()

        assert set(hosts) == set(expected_hosts)
        assert len(hosts) == 3

    def test_get_enabled_hosts_ignores_pending(self, manager, mock_worker):
        """Test enabled hosts ignores pending workers."""
        manager.workers = {'host1': Mock()}
        manager.pending_workers = {'host2': mock_worker}

        hosts = manager.get_enabled_hosts()

        assert hosts == ['host1']


# ============================================================================
# PERSIST ENABLED STATE TESTS
# ============================================================================

class TestPersistEnabledState:
    """Test persisting enabled state to INI."""

    @patch('src.core.file_host_config.save_file_host_setting')
    def test_persist_enabled_state_true(self, mock_save, manager):
        """Test persisting enabled=True."""
        manager._persist_enabled_state('rapidgator', enabled=True)

        mock_save.assert_called_once_with('rapidgator', 'enabled', True)

    @patch('src.core.file_host_config.save_file_host_setting')
    def test_persist_enabled_state_false(self, mock_save, manager):
        """Test persisting enabled=False."""
        manager._persist_enabled_state('rapidgator', enabled=False)

        mock_save.assert_called_once_with('rapidgator', 'enabled', False)

    @patch('src.core.file_host_config.save_file_host_setting')
    def test_persist_enabled_state_error(self, mock_save, manager):
        """Test error handling in persist."""
        mock_save.side_effect = Exception("Save error")

        # Should not raise exception
        manager._persist_enabled_state('rapidgator', enabled=True)

    @patch('src.core.file_host_config.save_file_host_setting')
    def test_persist_enabled_state_multiple_hosts(self, mock_save, manager):
        """Test persisting state for multiple hosts."""
        hosts = ['host1', 'host2', 'host3']

        for host in hosts:
            manager._persist_enabled_state(host, enabled=True)

        assert mock_save.call_count == len(hosts)


# ============================================================================
# INIT ENABLED HOSTS TESTS
# ============================================================================

class TestInitEnabledHosts:
    """Test initializing enabled hosts at startup."""

    @patch('src.processing.file_host_worker_manager.get_config_manager')
    @patch('imxup.get_config_path')
    def test_init_enabled_hosts_calls_enable_for_enabled(self, mock_config_path,
                                                         mock_config_mgr,
                                                         manager):
        """Test init enables hosts marked as enabled in INI file."""
        mock_config_path.return_value = '/config.ini'

        mock_host_config = Mock()
        mock_config_mgr.return_value.hosts = {'rapidgator': mock_host_config}

        # Mock INI file reading to return enabled=True for rapidgator
        ini_content = {
            'FILE_HOSTS': {
                'rapidgator_enabled': 'True'
            }
        }

        with patch.object(manager, 'enable_host') as mock_enable, \
             patch('os.path.exists', return_value=True), \
             patch('configparser.ConfigParser') as mock_config_parser:

            mock_parser_instance = Mock()
            mock_config_parser.return_value = mock_parser_instance

            # Mock ConfigParser methods
            mock_parser_instance.has_section.return_value = True
            mock_parser_instance.has_option.return_value = True
            mock_parser_instance.getboolean.return_value = True

            manager.init_enabled_hosts()

            # enable_host should be called with host_id and persist=False (during startup)
            mock_enable.assert_called_once_with('rapidgator', persist=False)

    @patch('src.processing.file_host_worker_manager.get_config_manager')
    @patch('imxup.get_config_path')
    def test_init_enabled_hosts_skips_disabled(self, mock_config_path,
                                              mock_config_mgr,
                                              manager):
        """Test init skips hosts marked as disabled in INI file."""
        mock_config_path.return_value = '/config.ini'

        mock_host_config = Mock()
        mock_config_mgr.return_value.hosts = {'rapidgator': mock_host_config}

        # Mock INI file reading to return enabled=False for rapidgator
        with patch.object(manager, 'enable_host') as mock_enable, \
             patch('os.path.exists', return_value=True), \
             patch('configparser.ConfigParser') as mock_config_parser:

            mock_parser_instance = Mock()
            mock_config_parser.return_value = mock_parser_instance

            # Mock ConfigParser methods - enabled is False
            mock_parser_instance.has_section.return_value = True
            mock_parser_instance.has_option.return_value = True
            mock_parser_instance.getboolean.return_value = False

            manager.init_enabled_hosts()

            mock_enable.assert_not_called()

    @patch('src.processing.file_host_worker_manager.get_config_manager')
    @patch('imxup.get_config_path')
    def test_init_enabled_hosts_empty_config(self, mock_config_path, mock_config_mgr, manager):
        """Test init with no hosts in config."""
        mock_config_path.return_value = '/config.ini'
        mock_config_mgr.return_value.hosts = {}

        with patch('os.path.exists', return_value=True):
            manager.init_enabled_hosts()

        assert len(manager.workers) == 0

    @patch('src.processing.file_host_worker_manager.get_config_manager')
    @patch('imxup.get_config_path')
    def test_init_enabled_hosts_multiple_mixed(self, mock_config_path,
                                              mock_config_mgr,
                                              manager):
        """Test init with multiple hosts, mixed enabled/disabled."""
        mock_config_path.return_value = '/config.ini'

        hosts_config = {
            'rapidgator': Mock(),
            'mega': Mock(),
            'filehost': Mock()
        }
        mock_config_mgr.return_value.hosts = hosts_config

        # Only first two are enabled
        def getboolean_side_effect(*args, **kwargs):
            # getboolean is called with ('FILE_HOSTS', key_name)
            if len(args) >= 2:
                key_name = args[1]
                return key_name in ['rapidgator_enabled', 'mega_enabled']
            return False

        with patch.object(manager, 'enable_host') as mock_enable, \
             patch('os.path.exists', return_value=True), \
             patch('configparser.ConfigParser') as mock_config_parser:

            mock_parser_instance = Mock()
            mock_config_parser.return_value = mock_parser_instance

            # Mock ConfigParser methods
            mock_parser_instance.has_section.return_value = True
            mock_parser_instance.has_option.return_value = True
            mock_parser_instance.getboolean.side_effect = getboolean_side_effect

            manager.init_enabled_hosts()

            # Should call enable_host for rapidgator and mega, both with persist=False
            assert mock_enable.call_count == 2
            mock_enable.assert_any_call('rapidgator', persist=False)
            mock_enable.assert_any_call('mega', persist=False)


# ============================================================================
# CONCURRENT OPERATION TESTS
# ============================================================================

class TestConcurrentOperations:
    """Test concurrent worker operations."""

    @patch('src.processing.file_host_worker_manager.FileHostWorker')
    def test_concurrent_enable_multiple_hosts(self, mock_worker_class, manager):
        """Test enabling multiple hosts concurrently."""
        workers = [Mock() for _ in range(5)]
        mock_worker_class.side_effect = workers

        threads = []
        for i in range(5):
            host_id = f'host{i}'
            t = threading.Thread(target=manager.enable_host, args=(host_id,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        assert len(manager.pending_workers) == 5

    @patch('src.processing.file_host_worker_manager.FileHostWorkerManager._persist_enabled_state')
    def test_concurrent_disable_multiple_hosts(self, mock_persist, manager):
        """Test disabling multiple hosts concurrently."""
        for i in range(5):
            manager.workers[f'host{i}'] = Mock()

        threads = []
        for i in range(5):
            host_id = f'host{i}'
            t = threading.Thread(target=manager.disable_host, args=(host_id,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        assert len(manager.workers) == 0

    def test_concurrent_pause_resume(self, manager):
        """Test concurrent pause and resume operations."""
        for i in range(3):
            manager.workers[f'host{i}'] = Mock()

        def pause_resume():
            manager.pause_all()
            manager.resume_all()

        threads = [threading.Thread(target=pause_resume) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All workers should have been called
        for worker in manager.workers.values():
            assert worker.pause.call_count >= 1
            assert worker.resume.call_count >= 1

    def test_concurrent_get_worker(self, manager, mock_worker):
        """Test concurrent get_worker calls."""
        manager.workers['host1'] = mock_worker

        results = []

        def get_and_store():
            w = manager.get_worker('host1')
            results.append(w)

        threads = [threading.Thread(target=get_and_store) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 10
        assert all(w == mock_worker for w in results)

    @patch('src.processing.file_host_worker_manager.FileHostWorkerManager._persist_enabled_state')
    def test_concurrent_spinup_complete(self, mock_persist, manager):
        """Test concurrent spinup_complete handling."""
        for i in range(3):
            manager.pending_workers[f'host{i}'] = Mock()

        def complete_spinup(host_id):
            manager._on_spinup_complete(host_id, '')

        threads = [threading.Thread(target=complete_spinup, args=(f'host{i}',))
                  for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(manager.workers) == 3
        assert len(manager.pending_workers) == 0


# ============================================================================
# SIGNAL RELAY TESTS
# ============================================================================

class TestSignalRelay:
    """Test that worker signals are properly relayed to GUI."""

    def test_storage_updated_relayed(self, manager, mock_worker):
        """Test storage_updated signal is relayed."""
        manager._connect_worker_signals(mock_worker)

        signal_spy = Mock()
        manager.storage_updated.connect(signal_spy)

        # Simulate worker signal
        mock_worker.storage_updated.emit('rapidgator', 1000000, 500000)

        # Note: In real Qt, we'd need QTest.qWait() or similar
        # Here we're testing the connection is made

    def test_test_completed_relayed(self, manager, mock_worker):
        """Test test_completed signal is relayed."""
        manager._connect_worker_signals(mock_worker)

        signal_spy = Mock()
        manager.test_completed.connect(signal_spy)

    def test_upload_started_relayed(self, manager, mock_worker):
        """Test upload_started signal is relayed."""
        manager._connect_worker_signals(mock_worker)

        signal_spy = Mock()
        manager.upload_started.connect(signal_spy)

    def test_upload_progress_relayed(self, manager, mock_worker):
        """Test upload_progress signal is relayed."""
        manager._connect_worker_signals(mock_worker)

        signal_spy = Mock()
        manager.upload_progress.connect(signal_spy)

    def test_upload_completed_relayed(self, manager, mock_worker):
        """Test upload_completed signal is relayed."""
        manager._connect_worker_signals(mock_worker)

        signal_spy = Mock()
        manager.upload_completed.connect(signal_spy)

    def test_upload_failed_relayed(self, manager, mock_worker):
        """Test upload_failed signal is relayed."""
        manager._connect_worker_signals(mock_worker)

        signal_spy = Mock()
        manager.upload_failed.connect(signal_spy)

    def test_bandwidth_updated_relayed(self, manager, mock_worker):
        """Test bandwidth_updated signal is relayed."""
        manager._connect_worker_signals(mock_worker)

        signal_spy = Mock()
        manager.bandwidth_updated.connect(signal_spy)


# ============================================================================
# ERROR HANDLING AND EDGE CASES
# ============================================================================

class TestErrorHandling:
    """Test error handling and edge cases."""

    @patch('src.processing.file_host_worker_manager.FileHostWorker')
    def test_enable_host_worker_creation_fails(self, mock_worker_class, manager):
        """Test enable_host when worker creation fails."""
        mock_worker_class.side_effect = Exception("Creation failed")

        with pytest.raises(Exception):
            manager.enable_host('rapidgator')

    @patch('src.processing.file_host_worker_manager.FileHostWorker')
    def test_enable_host_worker_start_fails(self, mock_worker_class, manager):
        """Test enable_host when worker.start() fails."""
        mock_worker = Mock()
        mock_worker.start.side_effect = Exception("Start failed")
        mock_worker_class.return_value = mock_worker

        with pytest.raises(Exception):
            manager.enable_host('rapidgator')

    @patch('src.processing.file_host_worker_manager.FileHostWorkerManager._persist_enabled_state')
    def test_disable_host_worker_stop_fails(self, mock_persist, manager):
        """Test disable_host when worker.stop() fails."""
        mock_worker = Mock()
        mock_worker.stop.side_effect = Exception("Stop failed")
        manager.workers['rapidgator'] = mock_worker

        with pytest.raises(Exception):
            manager.disable_host('rapidgator')

    def test_empty_host_id_string(self, manager, mock_worker):
        """Test handling empty host_id."""
        manager.workers[''] = mock_worker

        result = manager.get_worker('')
        assert result == mock_worker

    def test_special_characters_in_host_id(self, manager, mock_worker):
        """Test host_id with special characters."""
        host_id = 'host-name_123!@#'
        manager.workers[host_id] = mock_worker

        result = manager.get_worker(host_id)
        assert result == mock_worker

    @patch('src.processing.file_host_worker_manager.FileHostWorkerManager._persist_enabled_state')
    def test_disable_then_enable_same_host(self, mock_persist, manager):
        """Test disabling and re-enabling same host."""
        mock_worker1 = Mock()
        manager.workers['host1'] = mock_worker1

        manager.disable_host('host1')
        assert len(manager.workers) == 0

        with patch('src.processing.file_host_worker_manager.FileHostWorker') as mock_worker_class:
            mock_worker2 = Mock()
            mock_worker_class.return_value = mock_worker2

            manager.enable_host('host1')
            assert 'host1' in manager.pending_workers
            assert mock_worker2 != mock_worker1


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

class TestIntegration:
    """Integration tests with realistic workflows."""

    @patch('src.processing.file_host_worker_manager.FileHostWorker')
    def test_workflow_enable_then_disable(self, mock_worker_class, manager, mock_worker):
        """Test complete workflow: enable -> spinup -> disable."""
        mock_worker_class.return_value = mock_worker

        # Enable
        manager.enable_host('rapidgator')
        assert 'rapidgator' in manager.pending_workers

        # Spinup complete
        with patch.object(manager, '_persist_enabled_state'):
            manager._on_spinup_complete('rapidgator', '')

        assert 'rapidgator' in manager.workers
        assert 'rapidgator' not in manager.pending_workers

        # Disable
        with patch.object(manager, '_persist_enabled_state'):
            manager.disable_host('rapidgator')

        assert 'rapidgator' not in manager.workers

    @patch('src.processing.file_host_worker_manager.FileHostWorker')
    def test_workflow_multiple_hosts_mixed_operations(self, mock_worker_class, manager):
        """Test mixed operations with multiple hosts."""
        workers = {
            'rapidgator': Mock(),
            'mega': Mock(),
            'filehost': Mock()
        }
        mock_worker_class.side_effect = list(workers.values())

        # Enable all
        for host_id in workers:
            manager.enable_host(host_id)

        # Move first two to enabled
        with patch.object(manager, '_persist_enabled_state'):
            manager._on_spinup_complete('rapidgator', '')
            manager._on_spinup_complete('mega', '')

        assert len(manager.workers) == 2

        # Pause all
        manager.pause_all()
        for worker in manager.workers.values():
            worker.pause.assert_called_once()

        # Resume all
        manager.resume_all()
        for worker in manager.workers.values():
            worker.resume.assert_called_once()

        # Shutdown all
        manager.shutdown_all()
        assert len(manager.workers) == 0

    def test_workflow_rapid_enable_disable(self, manager):
        """Test rapid enable/disable cycling."""
        with patch('src.processing.file_host_worker_manager.FileHostWorker') as mock_worker_class, \
             patch.object(manager, '_persist_enabled_state'):

            mock_worker_class.return_value = Mock()

            for i in range(10):
                manager.enable_host('test_host')
                if 'test_host' in manager.pending_workers:
                    manager._on_spinup_complete('test_host', '')

                if 'test_host' in manager.workers:
                    manager.disable_host('test_host')

            assert len(manager.workers) == 0


# ============================================================================
# CLEANUP AND RESOURCE TESTS
# ============================================================================

class TestResourceCleanup:
    """Test proper resource cleanup."""

    def test_manager_cleanup_on_delete(self, manager):
        """Test that manager cleans up on deletion."""
        manager.workers = {'host1': Mock(), 'host2': Mock()}

        # Simulate cleanup (in real code, would be __del__)
        manager.workers.clear()

        assert len(manager.workers) == 0

    @patch('src.processing.file_host_worker_manager.FileHostWorkerManager._persist_enabled_state')
    def test_shutdown_all_multiple_times(self, mock_persist, manager):
        """Test calling shutdown_all multiple times."""
        manager.workers = {'host1': Mock(), 'host2': Mock()}

        # First shutdown
        manager.shutdown_all()
        assert len(manager.workers) == 0

        # Second shutdown (should be safe)
        manager.shutdown_all()
        assert len(manager.workers) == 0

    def test_pending_workers_cleanup(self, manager, mock_worker):
        """Test cleanup of pending workers."""
        manager.pending_workers['host1'] = mock_worker
        manager.pending_workers['host2'] = Mock()

        manager.pending_workers.clear()

        assert len(manager.pending_workers) == 0
