#!/usr/bin/env python3
"""
Unit tests for BandwidthManager and BandwidthSource classes.

Tests cover:
- Asymmetric EMA smoothing (alpha_up=0.6 fast attack, alpha_down=0.35 moderate release)
- Multi-source aggregation (IMX, file hosts, link checker)
- PyQt6 signals (total_bandwidth_updated, host_bandwidth_updated, peak_updated)
- Thread safety with QMutex
- QSettings persistence
"""

import time
from unittest.mock import Mock, patch, MagicMock

import pytest

from PyQt6.QtCore import QSettings, QTimer


class TestBandwidthSource:
    """Test suite for BandwidthSource class."""

    @pytest.fixture
    def bandwidth_source(self):
        """Create a BandwidthSource with default parameters."""
        from src.gui.bandwidth_manager import BandwidthSource
        return BandwidthSource("test_source")

    @pytest.fixture
    def custom_bandwidth_source(self):
        """Create a BandwidthSource with custom smoothing parameters."""
        from src.gui.bandwidth_manager import BandwidthSource
        return BandwidthSource(
            "custom_source",
            window_size=10,
            alpha_up=0.8,
            alpha_down=0.2
        )

    # =========================================================================
    # Initialization Tests
    # =========================================================================

    def test_initialization_default_parameters(self, bandwidth_source):
        """Verify default initialization parameters."""
        assert bandwidth_source.name == "test_source"
        assert bandwidth_source.active is True
        assert bandwidth_source._window_size == 20
        assert bandwidth_source._alpha_up == 0.6
        assert bandwidth_source._alpha_down == 0.35
        assert bandwidth_source.smoothed_value == 0.0
        assert bandwidth_source.peak_value == 0.0

    def test_initialization_custom_parameters(self, custom_bandwidth_source):
        """Verify custom initialization parameters."""
        assert custom_bandwidth_source.name == "custom_source"
        assert custom_bandwidth_source._window_size == 10
        assert custom_bandwidth_source._alpha_up == 0.8
        assert custom_bandwidth_source._alpha_down == 0.2

    # =========================================================================
    # Asymmetric EMA Smoothing Tests
    # =========================================================================

    def test_ema_fast_attack_on_increase(self, bandwidth_source):
        """Verify fast attack (alpha_up=0.6) when bandwidth increases."""
        # Start with a baseline
        bandwidth_source.add_sample(100.0)
        initial_value = bandwidth_source.smoothed_value

        # Add a higher sample - should rise quickly
        bandwidth_source.add_sample(200.0)
        after_increase = bandwidth_source.smoothed_value

        # The smoothed value should respond quickly to increases
        # With alpha_up=0.6, it should be closer to the new value than the old
        assert after_increase > initial_value
        # After just 2 samples, rolling avg is (100+200)/2 = 150
        # EMA: 0.6 * 150 + 0.4 * (previous smoothed)
        # The increase should be substantial due to high alpha_up

    def test_ema_slow_release_on_decrease(self):
        """Verify moderate release (alpha_down=0.35) when bandwidth decreases."""
        from src.gui.bandwidth_manager import BandwidthSource

        # Create source and establish high baseline
        source = BandwidthSource("test", window_size=5, alpha_up=0.6, alpha_down=0.35)

        # Fill window with high values to establish baseline
        for _ in range(5):
            source.add_sample(1000.0)

        high_baseline = source.smoothed_value
        assert high_baseline > 500.0  # Should be near 1000

        # Now add a much lower sample
        source.add_sample(100.0)
        after_drop = source.smoothed_value

        # The decay should be moderate (alpha_down=0.35)
        # Value should still be relatively high because of slow release
        assert after_drop < high_baseline
        # But it shouldn't have dropped too much due to slow release
        assert after_drop > 400.0  # Should retain most of its value

    def test_asymmetric_behavior_comparison(self):
        """Compare asymmetric vs symmetric behavior."""
        from src.gui.bandwidth_manager import BandwidthSource

        # Create two sources with asymmetric and symmetric behavior
        asymmetric = BandwidthSource("asym", window_size=5, alpha_up=0.6, alpha_down=0.35)
        symmetric = BandwidthSource("sym", window_size=5, alpha_up=0.3, alpha_down=0.3)

        # Both start at 0, add same samples
        samples = [100, 200, 300, 400, 500, 400, 300, 200, 100, 50]

        asym_values = []
        sym_values = []

        for sample in samples:
            asym_values.append(asymmetric.add_sample(sample))
            sym_values.append(symmetric.add_sample(sample))

        # Asymmetric should rise faster during increases (first 5 samples)
        # Check that asymmetric rises faster initially
        assert asym_values[2] >= sym_values[2]  # Rising phase

        # Asymmetric should fall slower during decreases (last 5 samples)
        # Check that asymmetric retains more value during fall
        assert asym_values[-1] >= sym_values[-1]  # Falling phase

    def test_rolling_average_window_size(self):
        """Verify rolling average respects window_size."""
        from src.gui.bandwidth_manager import BandwidthSource

        source = BandwidthSource("test", window_size=3, alpha_up=1.0, alpha_down=1.0)

        # With alpha=1.0, smoothed = rolling_avg exactly
        source.add_sample(100.0)
        assert source.smoothed_value == 100.0  # [100] -> avg = 100

        source.add_sample(200.0)
        assert source.smoothed_value == 150.0  # [100, 200] -> avg = 150

        source.add_sample(300.0)
        assert source.smoothed_value == 200.0  # [100, 200, 300] -> avg = 200

        # Window is full, oldest value should be pushed out
        source.add_sample(400.0)
        assert source.smoothed_value == 300.0  # [200, 300, 400] -> avg = 300

    # =========================================================================
    # Sample Management Tests
    # =========================================================================

    def test_add_sample_returns_smoothed_value(self, bandwidth_source):
        """Verify add_sample returns the smoothed value."""
        result = bandwidth_source.add_sample(100.0)
        assert result == bandwidth_source.smoothed_value

    def test_add_sample_updates_last_update_time(self, bandwidth_source):
        """Verify add_sample updates the last update timestamp."""
        before = time.time()
        bandwidth_source.add_sample(100.0)
        after = time.time()

        assert before <= bandwidth_source._last_update <= after

    def test_peak_value_tracking(self):
        """Verify peak value is tracked correctly.

        Uses a controlled source with full window to ensure rolling average
        actually decreases when low values are added.
        """
        from src.gui.bandwidth_manager import BandwidthSource

        # Use small window and alpha=1.0 for predictable behavior
        source = BandwidthSource("test", window_size=3, alpha_up=1.0, alpha_down=1.0)

        # Fill window with high values
        source.add_sample(500.0)
        source.add_sample(500.0)
        source.add_sample(500.0)
        peak_after_high = source.peak_value  # Should be 500.0

        # Now add low values - window becomes [500, 500, 10] then [500, 10, 10] etc.
        source.add_sample(10.0)
        source.add_sample(10.0)
        source.add_sample(10.0)  # Window is now [10, 10, 10], avg = 10

        # Peak should still be the maximum reached (500), not the current value (10)
        assert source.peak_value == peak_after_high
        assert source.peak_value == 500.0
        assert source.smoothed_value == 10.0  # Current value is low

    # =========================================================================
    # Reset Tests
    # =========================================================================

    def test_reset_clears_samples(self, bandwidth_source):
        """Verify reset clears all samples."""
        for i in range(10):
            bandwidth_source.add_sample(float(i * 100))

        bandwidth_source.reset()

        assert len(bandwidth_source._samples) == 0
        assert bandwidth_source.smoothed_value == 0.0

    def test_reset_preserves_peak_value(self, bandwidth_source):
        """Verify reset preserves peak value for session tracking."""
        bandwidth_source.add_sample(1000.0)
        peak = bandwidth_source.peak_value

        bandwidth_source.reset()

        # Peak value is preserved (it's a session metric)
        assert bandwidth_source.peak_value == peak

    # =========================================================================
    # Alpha Adjustment Tests
    # =========================================================================

    def test_set_alpha_clamps_values(self, bandwidth_source):
        """Verify set_alpha clamps values to [0, 1]."""
        # Test upper bound
        bandwidth_source.set_alpha(1.5, 2.0)
        assert bandwidth_source._alpha_up == 1.0
        assert bandwidth_source._alpha_down == 1.0

        # Test lower bound
        bandwidth_source.set_alpha(-0.5, -1.0)
        assert bandwidth_source._alpha_up == 0.0
        assert bandwidth_source._alpha_down == 0.0

        # Test valid values
        bandwidth_source.set_alpha(0.7, 0.2)
        assert bandwidth_source._alpha_up == 0.7
        assert bandwidth_source._alpha_down == 0.2

    # =========================================================================
    # Property Tests
    # =========================================================================

    def test_time_since_update_property(self, bandwidth_source):
        """Verify time_since_update property."""
        bandwidth_source.add_sample(100.0)
        time.sleep(0.05)  # 50ms
        elapsed = bandwidth_source.time_since_update

        assert elapsed >= 0.05
        assert elapsed < 1.0  # Should be much less than 1 second


class TestBandwidthManager:
    """Test suite for BandwidthManager class."""

    @pytest.fixture
    def mock_qsettings(self, monkeypatch):
        """Mock QSettings to avoid actual settings file access."""
        mock_settings = MagicMock(spec=QSettings)
        mock_settings.value.side_effect = lambda key, default, type=None: default

        def mock_init(self, *args, **kwargs):
            pass

        monkeypatch.setattr(QSettings, '__init__', mock_init)
        monkeypatch.setattr(QSettings, 'value', lambda self, key, default, type=None: default)
        monkeypatch.setattr(QSettings, 'setValue', lambda self, key, value: None)

        return mock_settings

    @pytest.fixture
    def bandwidth_manager(self, qtbot, mock_qsettings):
        """Create a BandwidthManager instance."""
        from src.gui.bandwidth_manager import BandwidthManager
        manager = BandwidthManager()
        yield manager
        manager.stop()

    # =========================================================================
    # Initialization Tests
    # =========================================================================

    def test_initialization(self, bandwidth_manager):
        """Verify BandwidthManager initializes correctly."""
        assert bandwidth_manager._alpha_up == 0.6
        assert bandwidth_manager._alpha_down == 0.35
        assert bandwidth_manager._session_peak == 0.0
        assert bandwidth_manager._imx_source is not None
        assert bandwidth_manager._link_checker_source is not None
        assert len(bandwidth_manager._file_host_sources) == 0

    def test_default_constants(self, bandwidth_manager):
        """Verify class constants are set correctly."""
        from src.gui.bandwidth_manager import BandwidthManager
        assert BandwidthManager.DEFAULT_ALPHA_UP == 0.6
        assert BandwidthManager.DEFAULT_ALPHA_DOWN == 0.35
        assert BandwidthManager.EMIT_INTERVAL_MS == 200
        assert BandwidthManager.HOST_CLEANUP_DELAY_MS == 5000

    def test_loads_settings_on_init(self, qtbot, monkeypatch):
        """Verify settings are loaded from QSettings on initialization."""
        from src.gui.bandwidth_manager import BandwidthManager

        custom_alpha_up = 0.8
        custom_alpha_down = 0.25

        def mock_value(self, key, default, type=None):
            if key == BandwidthManager.SETTINGS_KEY_ALPHA_UP:
                return custom_alpha_up
            elif key == BandwidthManager.SETTINGS_KEY_ALPHA_DOWN:
                return custom_alpha_down
            return default

        monkeypatch.setattr(QSettings, '__init__', lambda self, *args, **kwargs: None)
        monkeypatch.setattr(QSettings, 'value', mock_value)

        manager = BandwidthManager()
        try:
            assert manager._alpha_up == custom_alpha_up
            assert manager._alpha_down == custom_alpha_down
        finally:
            manager.stop()

    # =========================================================================
    # IMX Bandwidth Tests
    # =========================================================================

    def test_on_imx_bandwidth_activates_source(self, bandwidth_manager):
        """Verify on_imx_bandwidth activates the IMX source."""
        bandwidth_manager._imx_source.active = False
        bandwidth_manager.on_imx_bandwidth(100.0)

        assert bandwidth_manager._imx_source.active is True

    def test_on_imx_bandwidth_adds_sample(self, bandwidth_manager):
        """Verify on_imx_bandwidth adds sample to IMX source."""
        bandwidth_manager.on_imx_bandwidth(100.0)
        assert bandwidth_manager._imx_source.smoothed_value > 0

    def test_get_imx_bandwidth(self, bandwidth_manager):
        """Verify get_imx_bandwidth returns correct value."""
        bandwidth_manager.on_imx_bandwidth(500.0)
        result = bandwidth_manager.get_imx_bandwidth()

        assert result == bandwidth_manager._imx_source.smoothed_value

    # =========================================================================
    # File Host Bandwidth Tests
    # =========================================================================

    def test_on_file_host_bandwidth_creates_source(self, bandwidth_manager):
        """Verify on_file_host_bandwidth creates new source for unknown host."""
        assert "rapidgator" not in bandwidth_manager._file_host_sources

        bandwidth_manager.on_file_host_bandwidth("rapidgator", 100.0)

        assert "rapidgator" in bandwidth_manager._file_host_sources
        assert bandwidth_manager._file_host_sources["rapidgator"].name == "rapidgator"

    def test_on_file_host_bandwidth_reuses_source(self, bandwidth_manager):
        """Verify on_file_host_bandwidth reuses existing source."""
        bandwidth_manager.on_file_host_bandwidth("rapidgator", 100.0)
        source_id = id(bandwidth_manager._file_host_sources["rapidgator"])

        bandwidth_manager.on_file_host_bandwidth("rapidgator", 200.0)

        assert id(bandwidth_manager._file_host_sources["rapidgator"]) == source_id

    def test_on_file_host_bandwidth_emits_signal(self, bandwidth_manager, qtbot):
        """Verify on_file_host_bandwidth emits host_bandwidth_updated signal."""
        with qtbot.waitSignal(bandwidth_manager.host_bandwidth_updated, timeout=1000) as blocker:
            bandwidth_manager.on_file_host_bandwidth("fileboom", 150.0)

        assert blocker.args[0] == "fileboom"
        assert blocker.args[1] > 0

    def test_get_file_host_bandwidth_unknown_host(self, bandwidth_manager):
        """Verify get_file_host_bandwidth returns 0 for unknown host."""
        result = bandwidth_manager.get_file_host_bandwidth("unknown_host")
        assert result == 0.0

    def test_get_file_host_bandwidth_known_host(self, bandwidth_manager):
        """Verify get_file_host_bandwidth returns value for known host."""
        bandwidth_manager.on_file_host_bandwidth("keep2share", 300.0)
        result = bandwidth_manager.get_file_host_bandwidth("keep2share")

        assert result > 0

    def test_multiple_file_hosts(self, bandwidth_manager):
        """Verify multiple file hosts are tracked independently."""
        bandwidth_manager.on_file_host_bandwidth("host1", 100.0)
        bandwidth_manager.on_file_host_bandwidth("host2", 200.0)
        bandwidth_manager.on_file_host_bandwidth("host3", 300.0)

        assert len(bandwidth_manager._file_host_sources) == 3
        assert bandwidth_manager.get_file_host_bandwidth("host1") != \
               bandwidth_manager.get_file_host_bandwidth("host2")

    # =========================================================================
    # Link Checker Bandwidth Tests
    # =========================================================================

    def test_on_link_checker_bandwidth_activates_source(self, bandwidth_manager):
        """Verify on_link_checker_bandwidth activates the link checker source."""
        bandwidth_manager._link_checker_source.active = False
        bandwidth_manager.on_link_checker_bandwidth(50.0)

        assert bandwidth_manager._link_checker_source.active is True

    def test_on_link_checker_bandwidth_adds_sample(self, bandwidth_manager):
        """Verify on_link_checker_bandwidth adds sample to link checker source."""
        bandwidth_manager.on_link_checker_bandwidth(75.0)
        assert bandwidth_manager._link_checker_source.smoothed_value > 0

    # =========================================================================
    # Multi-Source Aggregation Tests
    # =========================================================================

    def test_total_bandwidth_aggregates_all_sources(self, bandwidth_manager):
        """Verify total bandwidth includes all active sources."""
        # Add bandwidth to all source types
        bandwidth_manager.on_imx_bandwidth(100.0)
        bandwidth_manager.on_file_host_bandwidth("host1", 200.0)
        bandwidth_manager.on_link_checker_bandwidth(50.0)

        total = bandwidth_manager.get_total_bandwidth()

        # Total should be sum of all individual sources
        imx = bandwidth_manager.get_imx_bandwidth()
        host1 = bandwidth_manager.get_file_host_bandwidth("host1")
        link = bandwidth_manager._link_checker_source.smoothed_value

        assert total == pytest.approx(imx + host1 + link, rel=0.01)

    def test_total_bandwidth_excludes_inactive_sources(self, bandwidth_manager):
        """Verify total bandwidth excludes inactive sources."""
        bandwidth_manager.on_imx_bandwidth(100.0)
        bandwidth_manager.on_file_host_bandwidth("host1", 200.0)

        # Deactivate IMX source
        bandwidth_manager._imx_source.active = False

        total = bandwidth_manager.get_total_bandwidth()
        host1 = bandwidth_manager.get_file_host_bandwidth("host1")

        # Total should only include active host
        assert total == pytest.approx(host1, rel=0.01)

    def test_get_active_hosts(self, bandwidth_manager):
        """Verify get_active_hosts returns only active file hosts."""
        bandwidth_manager.on_file_host_bandwidth("host1", 100.0)
        bandwidth_manager.on_file_host_bandwidth("host2", 200.0)
        bandwidth_manager.on_file_host_bandwidth("host3", 300.0)

        # Deactivate one host
        bandwidth_manager._file_host_sources["host2"].active = False

        active = bandwidth_manager.get_active_hosts()

        assert "host1" in active
        assert "host2" not in active
        assert "host3" in active
        assert len(active) == 2

    # =========================================================================
    # Signal Emission Tests
    # =========================================================================

    def test_total_bandwidth_signal_emitted(self, bandwidth_manager, qtbot):
        """Verify total_bandwidth_updated signal is emitted periodically."""
        bandwidth_manager.on_imx_bandwidth(100.0)

        with qtbot.waitSignal(bandwidth_manager.total_bandwidth_updated, timeout=500) as blocker:
            pass  # Wait for periodic emission

        assert blocker.args[0] >= 0

    def test_peak_signal_emitted_on_new_peak(self, bandwidth_manager, qtbot):
        """Verify peak_updated signal is emitted when new peak is reached."""
        # Reset session to start fresh
        bandwidth_manager.reset_session()

        # Add high bandwidth to trigger peak update
        bandwidth_manager.on_imx_bandwidth(1000.0)

        with qtbot.waitSignal(bandwidth_manager.peak_updated, timeout=500) as blocker:
            pass  # Wait for periodic aggregation

        assert blocker.args[0] > 0

    # =========================================================================
    # Host Completion and Cleanup Tests
    # =========================================================================

    def test_on_host_completed_marks_inactive(self, bandwidth_manager):
        """Verify on_host_completed marks host as inactive."""
        bandwidth_manager.on_file_host_bandwidth("rapidgator", 100.0)
        assert bandwidth_manager._file_host_sources["rapidgator"].active is True

        bandwidth_manager.on_host_completed("rapidgator")

        assert bandwidth_manager._file_host_sources["rapidgator"].active is False

    def test_on_host_completed_schedules_cleanup(self, bandwidth_manager):
        """Verify on_host_completed schedules cleanup timer."""
        bandwidth_manager.on_file_host_bandwidth("fileboom", 100.0)
        bandwidth_manager.on_host_completed("fileboom")

        assert "fileboom" in bandwidth_manager._cleanup_timers
        assert bandwidth_manager._cleanup_timers["fileboom"].isActive()

    def test_host_reactivation_cancels_cleanup(self, bandwidth_manager):
        """Verify new bandwidth from host cancels pending cleanup."""
        bandwidth_manager.on_file_host_bandwidth("host1", 100.0)
        bandwidth_manager.on_host_completed("host1")

        # Cleanup should be scheduled
        assert "host1" in bandwidth_manager._cleanup_timers

        # Reactivate by sending new bandwidth
        bandwidth_manager.on_file_host_bandwidth("host1", 200.0)

        # Cleanup should be cancelled
        assert "host1" not in bandwidth_manager._cleanup_timers

    def test_cleanup_removes_host(self, bandwidth_manager):
        """Verify _cleanup_host removes the host source."""
        bandwidth_manager.on_file_host_bandwidth("testhost", 100.0)
        assert "testhost" in bandwidth_manager._file_host_sources

        bandwidth_manager._cleanup_host("testhost")

        assert "testhost" not in bandwidth_manager._file_host_sources

    # =========================================================================
    # Session Peak Tests
    # =========================================================================

    def test_session_peak_tracking(self, bandwidth_manager):
        """Verify session peak is tracked correctly."""
        bandwidth_manager.reset_session()
        assert bandwidth_manager.get_session_peak() == 0.0

        bandwidth_manager.on_imx_bandwidth(500.0)
        # Trigger aggregation manually
        bandwidth_manager._emit_aggregated()

        peak = bandwidth_manager.get_session_peak()
        assert peak > 0

    def test_reset_session_clears_peak(self, bandwidth_manager):
        """Verify reset_session clears the session peak."""
        bandwidth_manager.on_imx_bandwidth(1000.0)
        bandwidth_manager._emit_aggregated()

        bandwidth_manager.reset_session()

        assert bandwidth_manager.get_session_peak() == 0.0

    def test_reset_session_resets_sources(self, bandwidth_manager):
        """Verify reset_session resets all bandwidth sources."""
        bandwidth_manager.on_imx_bandwidth(100.0)
        bandwidth_manager.on_file_host_bandwidth("host1", 200.0)
        bandwidth_manager.on_link_checker_bandwidth(50.0)

        bandwidth_manager.reset_session()

        assert bandwidth_manager._imx_source.smoothed_value == 0.0
        assert bandwidth_manager._link_checker_source.smoothed_value == 0.0
        # File host sources should also be reset
        if "host1" in bandwidth_manager._file_host_sources:
            assert bandwidth_manager._file_host_sources["host1"].smoothed_value == 0.0

    # =========================================================================
    # Smoothing Settings Tests
    # =========================================================================

    def test_update_smoothing_changes_parameters(self, bandwidth_manager):
        """Verify update_smoothing changes smoothing parameters."""
        bandwidth_manager.update_smoothing(0.9, 0.1)

        assert bandwidth_manager._alpha_up == 0.9
        assert bandwidth_manager._alpha_down == 0.1

    def test_update_smoothing_clamps_values(self, bandwidth_manager):
        """Verify update_smoothing clamps values to [0, 1]."""
        bandwidth_manager.update_smoothing(1.5, -0.5)

        assert bandwidth_manager._alpha_up == 1.0
        assert bandwidth_manager._alpha_down == 0.0

    def test_update_smoothing_propagates_to_sources(self, bandwidth_manager):
        """Verify update_smoothing updates all existing sources."""
        bandwidth_manager.on_file_host_bandwidth("host1", 100.0)

        bandwidth_manager.update_smoothing(0.8, 0.25)

        assert bandwidth_manager._imx_source._alpha_up == 0.8
        assert bandwidth_manager._imx_source._alpha_down == 0.25
        assert bandwidth_manager._link_checker_source._alpha_up == 0.8
        assert bandwidth_manager._file_host_sources["host1"]._alpha_up == 0.8

    def test_update_smoothing_persists_to_settings(self, qtbot, monkeypatch):
        """Verify update_smoothing persists values to QSettings."""
        from src.gui.bandwidth_manager import BandwidthManager

        saved_values = {}

        def mock_set_value(self, key, value):
            saved_values[key] = value

        monkeypatch.setattr(QSettings, '__init__', lambda self, *args, **kwargs: None)
        monkeypatch.setattr(QSettings, 'value', lambda self, key, default, type=None: default)
        monkeypatch.setattr(QSettings, 'setValue', mock_set_value)

        manager = BandwidthManager()
        try:
            manager.update_smoothing(0.7, 0.2)

            assert saved_values.get(BandwidthManager.SETTINGS_KEY_ALPHA_UP) == 0.7
            assert saved_values.get(BandwidthManager.SETTINGS_KEY_ALPHA_DOWN) == 0.2
        finally:
            manager.stop()

    def test_get_smoothing_settings(self, bandwidth_manager):
        """Verify get_smoothing_settings returns current parameters."""
        bandwidth_manager._alpha_up = 0.75
        bandwidth_manager._alpha_down = 0.18

        alpha_up, alpha_down = bandwidth_manager.get_smoothing_settings()

        assert alpha_up == 0.75
        assert alpha_down == 0.18

    # =========================================================================
    # Stop and Cleanup Tests
    # =========================================================================

    def test_stop_stops_emit_timer(self, bandwidth_manager):
        """Verify stop() stops the emit timer."""
        assert bandwidth_manager._emit_timer.isActive()

        bandwidth_manager.stop()

        assert not bandwidth_manager._emit_timer.isActive()

    def test_stop_stops_cleanup_timers(self, bandwidth_manager):
        """Verify stop() stops all cleanup timers."""
        bandwidth_manager.on_file_host_bandwidth("host1", 100.0)
        bandwidth_manager.on_file_host_bandwidth("host2", 200.0)
        bandwidth_manager.on_host_completed("host1")
        bandwidth_manager.on_host_completed("host2")

        assert len(bandwidth_manager._cleanup_timers) == 2

        bandwidth_manager.stop()

        assert len(bandwidth_manager._cleanup_timers) == 0


class TestBandwidthManagerThreadSafety:
    """Test suite for thread safety of BandwidthManager."""

    @pytest.fixture
    def mock_qsettings(self, monkeypatch):
        """Mock QSettings to avoid actual settings file access."""
        monkeypatch.setattr(QSettings, '__init__', lambda self, *args, **kwargs: None)
        monkeypatch.setattr(QSettings, 'value', lambda self, key, default, type=None: default)
        monkeypatch.setattr(QSettings, 'setValue', lambda self, key, value: None)

    @pytest.fixture
    def bandwidth_manager(self, qtbot, mock_qsettings):
        """Create a BandwidthManager instance."""
        from src.gui.bandwidth_manager import BandwidthManager
        manager = BandwidthManager()
        yield manager
        manager.stop()

    def test_mutex_used_for_file_host_access(self, bandwidth_manager):
        """Verify QMutex is used when accessing file host sources."""
        # This test verifies the mutex exists and is a QMutex
        from PyQt6.QtCore import QMutex
        assert isinstance(bandwidth_manager._lock, QMutex)

    def test_concurrent_file_host_updates(self, bandwidth_manager, qtbot):
        """Verify concurrent updates to different file hosts work correctly."""
        import threading

        errors = []
        results = {"hosts_created": 0}

        def add_host_bandwidth(host_name, value):
            try:
                for _ in range(10):
                    bandwidth_manager.on_file_host_bandwidth(host_name, value)
            except Exception as e:
                errors.append(e)

        # Create multiple threads updating different hosts
        threads = [
            threading.Thread(target=add_host_bandwidth, args=(f"host{i}", 100.0 * i))
            for i in range(5)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # No errors should have occurred
        assert len(errors) == 0

        # All hosts should exist
        assert len(bandwidth_manager._file_host_sources) == 5

    def test_concurrent_read_and_write(self, bandwidth_manager, qtbot):
        """Verify concurrent reads and writes work correctly."""
        import threading

        errors = []

        def writer():
            try:
                for i in range(20):
                    bandwidth_manager.on_file_host_bandwidth(f"writer_host_{i % 5}", float(i))
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(20):
                    bandwidth_manager.get_total_bandwidth()
                    bandwidth_manager.get_active_hosts()
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=writer),
            threading.Thread(target=reader),
            threading.Thread(target=writer),
            threading.Thread(target=reader),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


class TestBandwidthManagerIntegration:
    """Integration tests for BandwidthManager with realistic scenarios."""

    @pytest.fixture
    def mock_qsettings(self, monkeypatch):
        """Mock QSettings to avoid actual settings file access."""
        monkeypatch.setattr(QSettings, '__init__', lambda self, *args, **kwargs: None)
        monkeypatch.setattr(QSettings, 'value', lambda self, key, default, type=None: default)
        monkeypatch.setattr(QSettings, 'setValue', lambda self, key, value: None)

    @pytest.fixture
    def bandwidth_manager(self, qtbot, mock_qsettings):
        """Create a BandwidthManager instance."""
        from src.gui.bandwidth_manager import BandwidthManager
        manager = BandwidthManager()
        yield manager
        manager.stop()

    def test_realistic_upload_scenario(self, bandwidth_manager, qtbot):
        """Test a realistic multi-host upload scenario."""
        # Simulate IMX upload starting
        for i in range(5):
            bandwidth_manager.on_imx_bandwidth(200.0 + i * 10)

        # Simulate file host upload starting while IMX continues
        for i in range(5):
            bandwidth_manager.on_imx_bandwidth(250.0)
            bandwidth_manager.on_file_host_bandwidth("rapidgator", 150.0 + i * 5)

        # Both should be active
        assert bandwidth_manager._imx_source.active
        assert "rapidgator" in bandwidth_manager.get_active_hosts()

        # Total should be sum of both
        total = bandwidth_manager.get_total_bandwidth()
        assert total > 0

    def test_host_completion_lifecycle(self, bandwidth_manager, qtbot):
        """Test complete lifecycle of a file host upload."""
        # Start upload
        bandwidth_manager.on_file_host_bandwidth("fileboom", 100.0)
        assert "fileboom" in bandwidth_manager.get_active_hosts()

        # Upload completes
        bandwidth_manager.on_host_completed("fileboom")
        assert "fileboom" not in bandwidth_manager.get_active_hosts()

        # Host still exists but is inactive
        assert "fileboom" in bandwidth_manager._file_host_sources

        # Manual cleanup (normally happens via timer)
        bandwidth_manager._cleanup_host("fileboom")
        assert "fileboom" not in bandwidth_manager._file_host_sources

    def test_bandwidth_decay_over_time(self, bandwidth_manager, qtbot):
        """Test that bandwidth decays correctly when no new samples are added."""
        from src.gui.bandwidth_manager import BandwidthSource

        # Use a custom source for controlled testing
        source = BandwidthSource("test", window_size=5, alpha_up=0.6, alpha_down=0.35)

        # Build up bandwidth
        for _ in range(5):
            source.add_sample(1000.0)

        high_value = source.smoothed_value

        # Simulate decay by adding zero samples
        for _ in range(10):
            source.add_sample(0.0)

        low_value = source.smoothed_value

        # Value should have decayed significantly with moderate release
        assert low_value < high_value
        assert low_value > 0  # Still some residual due to moderate decay

    def test_session_statistics(self, bandwidth_manager, qtbot):
        """Test session-level statistics tracking."""
        bandwidth_manager.reset_session()

        # Simulate upload session
        peak_values = []
        for bw in [100, 200, 300, 400, 500, 400, 300]:
            bandwidth_manager.on_imx_bandwidth(float(bw))
            bandwidth_manager._emit_aggregated()
            peak_values.append(bandwidth_manager.get_session_peak())

        # Peak should increase then plateau
        assert peak_values[-1] >= peak_values[0]

        # Peak should be the maximum reached
        session_peak = bandwidth_manager.get_session_peak()
        assert session_peak > 0