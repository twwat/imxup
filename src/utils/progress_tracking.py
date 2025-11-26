"""
Progress tracking and monitoring utilities.

Provides classes and utilities for tracking upload progress, bandwidth,
and providing real-time status updates.
"""

import time
import threading
from typing import Optional, Callable, Dict, Any
from dataclasses import dataclass, field
from collections import deque


@dataclass
class ProgressState:
    """Represents the current state of a progress-tracked operation."""
    total: int = 0
    current: int = 0
    start_time: float = field(default_factory=time.time)
    last_update: float = field(default_factory=time.time)
    completed: bool = False
    error: Optional[str] = None

    @property
    def percentage(self) -> float:
        """Get completion percentage."""
        if self.total <= 0:
            return 0.0
        return min(100.0, (self.current / self.total) * 100.0)

    @property
    def elapsed_time(self) -> float:
        """Get elapsed time in seconds."""
        return time.time() - self.start_time

    @property
    def remaining_items(self) -> int:
        """Get number of remaining items."""
        return max(0, self.total - self.current)

    @property
    def estimated_time_remaining(self) -> Optional[float]:
        """
        Estimate remaining time in seconds.

        Returns:
            float: Estimated seconds remaining, or None if cannot estimate
        """
        if self.current <= 0 or self.total <= 0:
            return None

        elapsed = self.elapsed_time
        rate = self.current / elapsed
        if rate <= 0:
            return None

        remaining_items = self.remaining_items
        return remaining_items / rate


class ProgressTracker:
    """
    Thread-safe progress tracker for monitoring operations.

    Supports callbacks for progress updates and completion notifications.
    """

    def __init__(
        self,
        total: int,
        on_progress: Optional[Callable[[ProgressState], None]] = None,
        on_complete: Optional[Callable[[ProgressState], None]] = None
    ):
        """
        Initialize progress tracker.

        Args:
            total: Total number of items to process
            on_progress: Optional callback called on progress updates
            on_complete: Optional callback called on completion
        """
        self._state = ProgressState(total=total)
        self._lock = threading.Lock()
        self._on_progress = on_progress
        self._on_complete = on_complete

    def update(self, increment: int = 1) -> None:
        """
        Update progress by incrementing the current count.

        Args:
            increment: Amount to increment (default 1)
        """
        with self._lock:
            self._state.current = min(self._state.total, self._state.current + increment)
            self._state.last_update = time.time()

            if self._state.current >= self._state.total:
                self._state.completed = True

        # Call callbacks outside the lock to prevent deadlocks
        if self._on_progress:
            self._on_progress(self.get_state())

        if self._state.completed and self._on_complete:
            self._on_complete(self.get_state())

    def set_current(self, current: int) -> None:
        """
        Set the current progress to a specific value.

        Args:
            current: Current progress value
        """
        with self._lock:
            self._state.current = min(self._state.total, max(0, current))
            self._state.last_update = time.time()

            if self._state.current >= self._state.total:
                self._state.completed = True

        if self._on_progress:
            self._on_progress(self.get_state())

        if self._state.completed and self._on_complete:
            self._on_complete(self.get_state())

    def set_error(self, error: str) -> None:
        """
        Mark the operation as failed with an error.

        Args:
            error: Error message
        """
        with self._lock:
            self._state.error = error
            self._state.completed = True

        if self._on_complete:
            self._on_complete(self.get_state())

    def get_state(self) -> ProgressState:
        """
        Get a copy of the current progress state.

        Returns:
            ProgressState: Current state
        """
        with self._lock:
            return ProgressState(
                total=self._state.total,
                current=self._state.current,
                start_time=self._state.start_time,
                last_update=self._state.last_update,
                completed=self._state.completed,
                error=self._state.error
            )

    def is_completed(self) -> bool:
        """Check if the operation is completed."""
        with self._lock:
            return self._state.completed

    def has_error(self) -> bool:
        """Check if the operation has an error."""
        with self._lock:
            return self._state.error is not None

    def reset(self, new_total: Optional[int] = None) -> None:
        """
        Reset the progress tracker.

        Args:
            new_total: Optional new total (keeps existing if not provided)
        """
        with self._lock:
            total = new_total if new_total is not None else self._state.total
            self._state = ProgressState(total=total)


class BandwidthMonitor:
    """
    Monitor bandwidth usage with moving average calculation.

    Tracks transfer rates over time and provides smoothed bandwidth estimates.
    """

    def __init__(self, window_size: int = 10):
        """
        Initialize bandwidth monitor.

        Args:
            window_size: Number of samples to use for moving average
        """
        self._samples: deque = deque(maxlen=window_size)
        self._lock = threading.Lock()
        self._total_bytes = 0
        self._start_time = time.time()

    def add_bytes(self, bytes_count: int) -> None:
        """
        Record transferred bytes.

        Args:
            bytes_count: Number of bytes transferred
        """
        current_time = time.time()

        with self._lock:
            self._total_bytes += bytes_count
            self._samples.append((current_time, bytes_count))

    def get_current_speed(self) -> float:
        """
        Get current transfer speed in bytes per second.

        Uses moving average of recent samples.

        Returns:
            float: Current speed in bytes/second
        """
        with self._lock:
            if len(self._samples) < 2:
                return 0.0

            # Calculate speed from recent samples
            recent_samples = list(self._samples)
            if not recent_samples:
                return 0.0

            time_diff = recent_samples[-1][0] - recent_samples[0][0]
            if time_diff <= 0:
                return 0.0

            total_bytes = sum(sample[1] for sample in recent_samples)
            return total_bytes / time_diff

    def get_average_speed(self) -> float:
        """
        Get overall average transfer speed in bytes per second.

        Returns:
            float: Average speed in bytes/second
        """
        with self._lock:
            elapsed = time.time() - self._start_time
            if elapsed <= 0:
                return 0.0

            return self._total_bytes / elapsed

    def get_total_bytes(self) -> int:
        """
        Get total bytes transferred.

        Returns:
            int: Total bytes
        """
        with self._lock:
            return self._total_bytes

    def get_formatted_speed(self, use_current: bool = True) -> str:
        """
        Get formatted speed string (e.g., "1.23 MB/s").

        Args:
            use_current: If True, use current speed; otherwise use average

        Returns:
            str: Formatted speed string
        """
        speed = self.get_current_speed() if use_current else self.get_average_speed()

        for unit in ['B/s', 'KB/s', 'MB/s', 'GB/s']:
            if speed < 1024.0:
                return f"{speed:.2f} {unit}"
            speed /= 1024.0
        return f"{speed:.2f} GB/s"

    def reset(self) -> None:
        """Reset the bandwidth monitor."""
        with self._lock:
            self._samples.clear()
            self._total_bytes = 0
            self._start_time = time.time()


class MultiProgressTracker:
    """
    Track progress for multiple concurrent operations.

    Each operation gets a unique ID and can be tracked independently.
    """

    def __init__(self):
        """Initialize multi-progress tracker."""
        self._trackers: Dict[str, ProgressTracker] = {}
        self._lock = threading.Lock()

    def create_tracker(
        self,
        operation_id: str,
        total: int,
        on_progress: Optional[Callable[[ProgressState], None]] = None,
        on_complete: Optional[Callable[[ProgressState], None]] = None
    ) -> ProgressTracker:
        """
        Create a new progress tracker for an operation.

        Args:
            operation_id: Unique identifier for the operation
            total: Total items for this operation
            on_progress: Optional progress callback
            on_complete: Optional completion callback

        Returns:
            ProgressTracker: The created tracker
        """
        with self._lock:
            tracker = ProgressTracker(total, on_progress, on_complete)
            self._trackers[operation_id] = tracker
            return tracker

    def get_tracker(self, operation_id: str) -> Optional[ProgressTracker]:
        """
        Get a tracker by operation ID.

        Args:
            operation_id: Operation identifier

        Returns:
            ProgressTracker or None: The tracker if found
        """
        with self._lock:
            return self._trackers.get(operation_id)

    def remove_tracker(self, operation_id: str) -> None:
        """
        Remove a tracker.

        Args:
            operation_id: Operation identifier
        """
        with self._lock:
            self._trackers.pop(operation_id, None)

    def get_all_states(self) -> Dict[str, ProgressState]:
        """
        Get states for all tracked operations.

        Returns:
            Dict: Mapping of operation_id to ProgressState
        """
        with self._lock:
            return {
                op_id: tracker.get_state()
                for op_id, tracker in self._trackers.items()
            }

    def get_overall_progress(self) -> tuple[int, int]:
        """
        Get overall progress across all operations.

        Returns:
            tuple: (total_completed, total_items)
        """
        with self._lock:
            total_completed = 0
            total_items = 0

            for tracker in self._trackers.values():
                state = tracker.get_state()
                total_completed += state.current
                total_items += state.total

            return total_completed, total_items

    def clear_completed(self) -> None:
        """Remove all completed trackers."""
        with self._lock:
            self._trackers = {
                op_id: tracker
                for op_id, tracker in self._trackers.items()
                if not tracker.is_completed()
            }


class HealthCheck:
    """
    Simple health check utility for monitoring application status.
    """

    def __init__(self):
        """Initialize health check."""
        self._checks: Dict[str, Callable[[], bool]] = {}
        self._lock = threading.Lock()
        self._start_time = time.time()

    def register_check(self, name: str, check_func: Callable[[], bool]) -> None:
        """
        Register a health check function.

        Args:
            name: Name of the check
            check_func: Function that returns True if healthy, False otherwise
        """
        with self._lock:
            self._checks[name] = check_func

    def run_checks(self) -> Dict[str, Any]:
        """
        Run all registered health checks.

        Returns:
            Dict: Health check results with status and details
        """
        results = {
            'healthy': True,
            'uptime_seconds': time.time() - self._start_time,
            'checks': {}
        }

        with self._lock:
            checks = dict(self._checks)

        for name, check_func in checks.items():
            try:
                is_healthy = check_func()
                results['checks'][name] = {
                    'status': 'healthy' if is_healthy else 'unhealthy',
                    'healthy': is_healthy
                }
                if not is_healthy:
                    results['healthy'] = False
            except Exception as e:
                results['checks'][name] = {
                    'status': 'error',
                    'healthy': False,
                    'error': str(e)
                }
                results['healthy'] = False

        return results

    def is_healthy(self) -> bool:
        """
        Check if all health checks pass.

        Returns:
            bool: True if all checks pass
        """
        return self.run_checks()['healthy']
