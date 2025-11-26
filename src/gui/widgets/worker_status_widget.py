"""
Worker Status Widget for imxup.

Displays real-time status of upload workers for both imx.to and file hosts.
Shows active workers with icons, hostnames, speed, and status in a table view.
"""

from typing import Any, Callable, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from enum import Enum

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QLabel, QComboBox, QPushButton, QFrame, QSizePolicy,
    QMenu
)
from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot, QSettings, QTimer
from PyQt6.QtGui import QIcon, QPixmap, QFont, QPalette

from src.utils.format_utils import format_binary_rate
from src.utils.logger import log
from src.gui.icon_manager import get_icon_manager
from src.core.file_host_config import get_config_manager, get_file_host_setting


@dataclass
class WorkerStatus:
    """Data structure for worker status information."""
    worker_id: str
    worker_type: str  # 'imx' or 'filehost'
    hostname: str
    display_name: str
    speed_bps: float = 0.0
    status: str = "idle"  # idle, uploading, paused, error
    gallery_id: Optional[int] = None
    progress_bytes: int = 0
    total_bytes: int = 0
    error_message: Optional[str] = None
    last_update: float = 0.0


class ColumnType(Enum):
    """Column data types for formatting."""
    ICON = "icon"
    TEXT = "text"
    SPEED = "speed"
    BYTES = "bytes"
    PERCENT = "percent"
    COUNT = "count"
    WIDGET = "widget"


@dataclass
class ColumnConfig:
    """Configuration for a table column."""
    id: str                                    # Unique identifier
    name: str                                  # Display name for header
    width: int                                 # Default width in pixels
    col_type: ColumnType                       # Data type for formatting
    metric_key: Optional[str] = None           # Key in metrics dict (for metric columns)
    period: Optional[str] = None               # Aggregation period: 'session', 'today', 'all_time'
    resizable: bool = True                     # Can user resize
    hideable: bool = True                      # Can user hide
    default_visible: bool = True               # Visible by default
    alignment: Qt.AlignmentFlag = field(default_factory=lambda: Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)


# Core columns (always available)
CORE_COLUMNS = [
    ColumnConfig('icon', '', 24, ColumnType.ICON, resizable=False, hideable=False),
    ColumnConfig('hostname', 'Host', 120, ColumnType.TEXT),
    ColumnConfig('speed', 'Speed', 90, ColumnType.SPEED, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
    ColumnConfig('status', 'Status', 80, ColumnType.TEXT, alignment=Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter),
    ColumnConfig('settings', '', 32, ColumnType.WIDGET, resizable=False, hideable=False),
]

# Metric columns (optional, from MetricsStore)
METRIC_COLUMNS = [
    ColumnConfig('bytes_session', 'Session', 90, ColumnType.BYTES, 'bytes_uploaded', 'session', default_visible=False, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
    ColumnConfig('bytes_today', 'Today', 90, ColumnType.BYTES, 'bytes_uploaded', 'today', default_visible=False, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
    ColumnConfig('bytes_alltime', 'All Time', 90, ColumnType.BYTES, 'bytes_uploaded', 'all_time', default_visible=False, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
    ColumnConfig('files_session', 'Files', 60, ColumnType.COUNT, 'files_uploaded', 'session', default_visible=False, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
    ColumnConfig('avg_speed', 'Avg Speed', 90, ColumnType.SPEED, 'avg_speed', 'session', default_visible=False, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
    ColumnConfig('peak_speed', 'Peak', 90, ColumnType.SPEED, 'peak_speed', 'session', default_visible=False, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
    ColumnConfig('success_rate', 'Success %', 70, ColumnType.PERCENT, 'success_rate', 'session', default_visible=False, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
]

# Combined list
AVAILABLE_COLUMNS = {col.id: col for col in CORE_COLUMNS + METRIC_COLUMNS}


def format_bytes(value: int) -> str:
    """Format bytes to human readable (e.g., 1.5 GiB).

    Args:
        value: Byte count to format

    Returns:
        Human-readable byte string
    """
    if value <= 0:
        return "—"
    for unit in ['B', 'KiB', 'MiB', 'GiB', 'TiB']:
        if abs(value) < 1024.0:
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} PiB"


def format_percent(value: float) -> str:
    """Format percentage.

    Args:
        value: Percentage value (0-100)

    Returns:
        Formatted percentage string
    """
    if value <= 0:
        return "—"
    return f"{value:.1f}%"


def format_count(value: int) -> str:
    """Format count.

    Args:
        value: Count value

    Returns:
        Formatted count string
    """
    if value <= 0:
        return "—"
    return str(value)


class WorkerStatusWidget(QWidget):
    """
    Widget to display real-time status of upload workers.

    Features:
    - Table with columns: Icon | Hostname | Speed (MiB/s) | Status
    - Support for both imx.to and file host workers
    - Group workers by host type
    - Visual indicators for worker state (icons, colors)
    - Auto-refresh on worker updates
    - Customizable columns via header context menu

    Integration Points:
    - Connect to UploadWorker signals (imx.to)
    - Connect to FileHostWorker signals (file hosts)
    - Connect to FileHostWorkerManager for worker lifecycle
    - Connect to MetricsStore for upload statistics
    """

    # Signals
    worker_selected = pyqtSignal(str, str)  # worker_id, worker_type
    open_host_config_requested = pyqtSignal(str)  # host_id for file host config dialog
    open_settings_tab_requested = pyqtSignal(int)  # tab_index for settings dialog

    def __init__(self, parent=None):
        """Initialize worker status widget."""
        super().__init__(parent)

        # Data storage
        self._workers: Dict[str, WorkerStatus] = {}
        self._icon_cache: Dict[str, QIcon] = {}
        self._worker_row_map: Dict[str, int] = {}  # worker_id -> row index for targeted updates

        # Active columns (user's current selection)
        self._active_columns: List[ColumnConfig] = []

        # Metrics store connection
        self._metrics_store = None
        self._host_metrics_cache: Dict[str, Dict[str, Any]] = {}  # host_name -> metrics dict

        # UI references
        self.status_table: Optional[QTableWidget] = None
        self.filter_combo: Optional[QComboBox] = None
        self.worker_count_label: Optional[QLabel] = None

        # Selection tracking for refresh persistence
        self._selected_worker_id: Optional[str] = None

        # Sort state tracking
        self._sort_column: Optional[int] = None
        self._sort_order: Qt.SortOrder = Qt.SortOrder.AscendingOrder

        self._init_ui()
        self._load_icons()

    def _init_ui(self):
        """Initialize the user interface."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)

        # Top control bar
        control_layout = QHBoxLayout()
        control_layout.setSpacing(8)

        # Worker count label
        self.worker_count_label = QLabel("Workers: 0")
        self.worker_count_label.setProperty("class", "worker-count-label")
        control_layout.addWidget(self.worker_count_label)

        control_layout.addStretch()

        # Filter combo
        filter_label = QLabel("Filter:")
        control_layout.addWidget(filter_label)

        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["All Hosts", "Used This Session", "Enabled", "Active Only", "Errors Only"])
        self.filter_combo.currentIndexChanged.connect(self._on_filter_changed)
        self.filter_combo.setMinimumWidth(120)
        control_layout.addWidget(self.filter_combo)

        main_layout.addLayout(control_layout)

        # Separator line
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        separator.setProperty("class", "worker-separator")
        main_layout.addWidget(separator)

        # Status table
        self.status_table = QTableWidget()

        # Configure table behavior
        self.status_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.status_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.status_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.status_table.setAlternatingRowColors(True)
        self.status_table.verticalHeader().setVisible(False)
        self.status_table.horizontalHeader().setVisible(True)
        self.status_table.setShowGrid(False)

        # Row height
        self.status_table.verticalHeader().setDefaultSectionSize(32)

        # Disable built-in sorting (conflicts with manual sorting)
        # self.status_table.setSortingEnabled(True)

        # Header context menu and drag reorder
        header = self.status_table.horizontalHeader()
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._show_column_context_menu)
        header.setSectionsMovable(True)  # Allow drag reorder

        # Load saved column settings FIRST (before connecting signals)
        self._load_column_settings()

        # NOW connect signals AFTER columns are loaded
        header.sectionResized.connect(self._on_column_resized)
        header.sectionMoved.connect(self._on_column_moved)
        header.sectionClicked.connect(self._on_column_clicked)

        # Selection signal
        self.status_table.itemSelectionChanged.connect(self._on_selection_changed)

        main_layout.addWidget(self.status_table)

    def _load_icons(self):
        """Load and cache worker status icons."""
        icon_mgr = get_icon_manager()
        if not icon_mgr:
            return

        # Status icons
        self._icon_cache['uploading'] = icon_mgr.get_icon('status_uploading')
        self._icon_cache['idle'] = icon_mgr.get_icon('status_idle')
        self._icon_cache['paused'] = icon_mgr.get_icon('status_paused')
        self._icon_cache['error'] = icon_mgr.get_icon('status_error')
        self._icon_cache['completed'] = icon_mgr.get_icon('status_completed')
        self._icon_cache['settings'] = icon_mgr.get_icon('settings')

        # Host type icons (will load dynamically based on host)

    def _get_column_index(self, col_id: str) -> int:
        """Get the index of a column by its ID.

        Args:
            col_id: Column identifier

        Returns:
            Column index or -1 if not found
        """
        for idx, col in enumerate(self._active_columns):
            if col.id == col_id:
                return idx
        return -1

    def get_formatter_for_type(self, col_type: ColumnType) -> Optional[Callable]:
        """Get the appropriate formatter function for a column type.

        Args:
            col_type: Column data type

        Returns:
            Formatter function or None
        """
        formatters = {
            ColumnType.SPEED: self._format_speed,
            ColumnType.BYTES: format_bytes,
            ColumnType.PERCENT: format_percent,
            ColumnType.COUNT: format_count,
        }
        return formatters.get(col_type)

    def _get_host_icon(self, hostname: str, worker_type: str) -> QIcon:
        """Get icon for a specific host.

        Args:
            hostname: Host name (e.g., 'rapidgator', 'imx.to')
            worker_type: 'imx' or 'filehost'

        Returns:
            QIcon for the host, or fallback icon
        """
        cache_key = f"host_{hostname}"
        if cache_key in self._icon_cache:
            return self._icon_cache[cache_key]

        icon_mgr = get_icon_manager()
        if not icon_mgr:
            return QIcon()

        if worker_type == 'imx':
            icon = icon_mgr.get_icon('imx')
        else:
            # Load file host icon directly from path
            host_icon_path = Path(icon_mgr.assets_dir) / "hosts" / "logo" / f"{hostname.lower()}-icon.png"
            if host_icon_path.exists():
                icon = QIcon(str(host_icon_path))
            else:
                icon = icon_mgr.get_icon('filehosts')  # fallback

        self._icon_cache[cache_key] = icon
        return icon

    def refresh_icons(self):
        """Refresh all icons for theme changes."""
        # Clear icon cache to force reload with new theme
        self._icon_cache.clear()
        # Reload status icons from icon manager
        self._load_icons()
        # Refresh the display
        self._refresh_display()

    def start_monitoring(self):
        """Connect to metrics store for signal-driven updates."""
        self.connect_metrics_store()

    def stop_monitoring(self):
        """Disconnect from metrics store."""
        # No timer to stop - purely signal-driven
        pass

    # =========================================================================
    # MetricsStore Connection
    # =========================================================================

    def connect_metrics_store(self):
        """Connect to the MetricsStore for metrics display."""
        from src.utils.metrics_store import get_metrics_store
        self._metrics_store = get_metrics_store()
        if self._metrics_store:
            # Only connect if not already connected (avoid duplicates)
            try:
                self._metrics_store.signals.host_metrics_updated.disconnect(self._on_host_metrics_updated)
                self._metrics_store.signals.session_totals_updated.disconnect(self._on_session_totals_updated)
            except TypeError:
                # Not connected yet, this is fine
                pass

            # Now connect (fresh or reconnect)
            self._metrics_store.signals.host_metrics_updated.connect(self._on_host_metrics_updated)
            self._metrics_store.signals.session_totals_updated.connect(self._on_session_totals_updated)

            # Populate initial metrics from database (one-time load)
            self._populate_initial_metrics()

    def _populate_initial_metrics(self):
        """Load initial metrics from database asynchronously to prevent GUI freeze.

        This loads historical data in batches on startup using QTimer to keep
        the UI responsive. Subsequent updates come via signals from record_transfer().
        """
        if not self._metrics_store:
            return

        # Get hosts with historical data
        hosts_with_history = self._metrics_store.get_hosts_with_history()

        # Also get current session hosts
        session_hosts = self._metrics_store.get_active_hosts()

        # Combine all hosts that need metrics loaded
        all_hosts = list(set(hosts_with_history.keys()) | set(session_hosts))

        if not all_hosts:
            return

        # Process in batches to avoid blocking the main thread
        def process_batch(start_index):
            """Process a batch of hosts and schedule the next batch."""
            # Process 2 hosts at a time to balance responsiveness and speed
            batch_size = 2
            end_index = min(start_index + batch_size, len(all_hosts))

            for host_name in all_hosts[start_index:end_index]:
                try:
                    metrics = {
                        'session': self._metrics_store.get_session_metrics(host_name),
                        'today': self._metrics_store.get_aggregated_metrics(host_name, 'today'),
                        'all_time': self._metrics_store.get_aggregated_metrics(host_name, 'all_time'),
                    }
                    # Cache the metrics
                    self._host_metrics_cache[host_name.lower()] = metrics
                except Exception as e:
                    log(f"Error loading metrics for {host_name}: {e}", level="error", category="ui")

            # Schedule next batch if more hosts remain
            if end_index < len(all_hosts):
                QTimer.singleShot(10, lambda: process_batch(end_index))
            else:
                # All done - refresh display to show all loaded metrics
                self._refresh_display()

        # Start processing the first batch immediately
        QTimer.singleShot(0, lambda: process_batch(0))

    @pyqtSlot(str, dict)
    def _on_host_metrics_updated(self, host_name: str, metrics: dict):
        """Handle metrics update for a host.

        Supports partial updates - missing periods preserve cached values.

        Args:
            host_name: Host identifier
            metrics: Dict with period sub-dicts (session, today, all_time), each containing:
                     bytes_uploaded, files_uploaded, avg_speed, peak_speed, success_rate
        """
        # Get existing cache or create empty
        existing = self._host_metrics_cache.get(host_name.lower(), {})

        # Merge new metrics with existing (preserves today/all_time if only session updated)
        merged = {
            'session': metrics.get('session', existing.get('session', {})),
            'today': metrics.get('today', existing.get('today', {})),
            'all_time': metrics.get('all_time', existing.get('all_time', {})),
        }

        # Update cache
        self._host_metrics_cache[host_name.lower()] = merged

        # Find worker for this host and update metric columns
        for worker_id, worker in self._workers.items():
            if worker.hostname.lower() == host_name.lower():
                self._update_worker_metrics(worker_id, merged)
                break

    @pyqtSlot(dict)
    def _on_session_totals_updated(self, totals: dict):
        """Handle session totals update.

        Args:
            totals: Dict mapping host names to their session metrics
        """
        # Could display totals in footer or status bar
        # For now, just update the cache for all hosts
        for host_name, metrics in totals.items():
            self._host_metrics_cache[host_name.lower()] = metrics

    def _update_worker_metrics(self, worker_id: str, metrics: dict):
        """Update metric columns for a worker.

        Args:
            worker_id: Worker identifier
            metrics: Metrics dict from MetricsStore with period sub-dicts
        """
        row = self._worker_row_map.get(worker_id)
        if row is None:
            return

        # Update each metric column
        for col_idx, col_config in enumerate(self._active_columns):
            if col_config.metric_key and col_config.period:
                # This is a metric column - get the period sub-dict first
                period_data = metrics.get(col_config.period, {})
                # Then get the specific metric value from that period
                value = period_data.get(col_config.metric_key, 0)

                # Format based on column type
                if col_config.col_type == ColumnType.BYTES:
                    text = format_bytes(value)
                elif col_config.col_type == ColumnType.SPEED:
                    text = self._format_speed(value)
                elif col_config.col_type == ColumnType.PERCENT:
                    text = format_percent(value)
                elif col_config.col_type == ColumnType.COUNT:
                    text = format_count(value)
                else:
                    text = str(value)

                item = self.status_table.item(row, col_idx)
                if item and item.text() != text:
                    item.setText(text)

    # =========================================================================
    # Worker Management - Integration Points
    # =========================================================================

    @pyqtSlot(str, str, str, float, str)
    def update_worker_status(self, worker_id: str, worker_type: str, hostname: str,
                            speed_bps: float, status: str):
        """Update worker status information.

        Args:
            worker_id: Unique worker identifier
            worker_type: 'imx' or 'filehost'
            hostname: Host display name
            speed_bps: Current upload speed in bytes per second
            status: Worker status ('idle', 'uploading', 'paused', 'error')
        """
        if worker_id in self._workers:
            # Existing worker - use targeted updates ONLY (no refresh)
            worker = self._workers[worker_id]

            # Only update cells that changed
            if worker.speed_bps != speed_bps:
                worker.speed_bps = speed_bps
                self._update_worker_speed(worker_id, speed_bps)

            if worker.status != status:
                worker.status = status
                self._update_worker_status_cell(worker_id, status)

            worker.last_update = datetime.now().timestamp()
            # No _schedule_refresh() call for existing workers
        else:
            # New worker - create entry and schedule full refresh
            self._workers[worker_id] = WorkerStatus(
                worker_id=worker_id,
                worker_type=worker_type,
                hostname=hostname,
                display_name=self._format_display_name(hostname, worker_type),
                speed_bps=speed_bps,
                status=status,
                last_update=datetime.now().timestamp()
            )
            self._schedule_refresh()  # Only rebuild for new workers

    @pyqtSlot(str, int, int, int)
    def update_worker_progress(self, worker_id: str, gallery_id: int,
                               progress_bytes: int, total_bytes: int):
        """Update worker progress information.

        Args:
            worker_id: Worker identifier
            gallery_id: Gallery being uploaded
            progress_bytes: Bytes uploaded so far
            total_bytes: Total bytes to upload
        """
        if worker_id in self._workers:
            worker = self._workers[worker_id]
            worker.gallery_id = gallery_id
            worker.progress_bytes = progress_bytes
            worker.total_bytes = total_bytes
            worker.last_update = datetime.now().timestamp()
            self._schedule_refresh()

    @pyqtSlot(str, str)
    def update_worker_error(self, worker_id: str, error_message: str):
        """Update worker error state.

        Args:
            worker_id: Worker identifier
            error_message: Error description
        """
        if worker_id in self._workers:
            worker = self._workers[worker_id]
            worker.status = 'error'
            worker.speed_bps = 0.0
            worker.error_message = error_message
            worker.last_update = datetime.now().timestamp()
            self._schedule_refresh()

    @pyqtSlot(str)
    def remove_worker(self, worker_id: str):
        """Remove a worker from display.

        Args:
            worker_id: Worker identifier to remove
        """
        if worker_id in self._workers:
            del self._workers[worker_id]
            if worker_id in self._worker_row_map:
                del self._worker_row_map[worker_id]
            self._schedule_refresh()

    def clear_workers(self):
        """Clear all workers from display."""
        self._workers.clear()
        self._worker_row_map.clear()
        self._schedule_refresh()

    # =========================================================================
    # Display Logic
    # =========================================================================

    def _schedule_refresh(self):
        """Schedule a display refresh for worker add/remove and filter changes only."""
        # No timer check - just refresh immediately when workers are added/removed
        self._refresh_display()

    # =========================================================================
    # Targeted Cell Update Methods
    # =========================================================================

    def _update_worker_cell(self, worker_id: str, column: int, value: Any,
                           formatter: Optional[Callable] = None):
        """Update a single cell without rebuilding the table.

        Args:
            worker_id: Worker identifier
            column: Column index
            value: New value
            formatter: Optional function to format value for display
        """
        row = self._worker_row_map.get(worker_id)
        if row is None:
            return

        item = self.status_table.item(row, column)
        if item:
            # Store raw value for comparison
            cached = item.data(Qt.ItemDataRole.UserRole + 10)
            if cached != value:
                item.setData(Qt.ItemDataRole.UserRole + 10, value)
                if formatter:
                    item.setText(formatter(value))
                elif isinstance(value, str):
                    item.setText(value)
                else:
                    item.setText(str(value))

    def _update_worker_speed(self, worker_id: str, speed_bps: float):
        """Update only the speed cell for a worker.

        Args:
            worker_id: Worker identifier
            speed_bps: Speed in bytes per second
        """
        col_idx = self._get_column_index('speed')
        if col_idx >= 0:
            self._update_worker_cell(worker_id, col_idx, speed_bps, self._format_speed)

    def _update_worker_status_cell(self, worker_id: str, status: str):
        """Update only the status cell for a worker.

        Args:
            worker_id: Worker identifier
            status: New status string
        """
        row = self._worker_row_map.get(worker_id)
        if row is None:
            return

        col_idx = self._get_column_index('status')
        if col_idx < 0:
            return

        item = self.status_table.item(row, col_idx)
        if item:
            # Update icon - map 'disabled' to 'idle' icon
            status_icon = self._icon_cache.get(
                'idle' if status == 'disabled' else status,
                QIcon()
            )
            item.setIcon(status_icon)
            item.setText(status.capitalize())

            # Color coding
            if status == 'uploading':
                item.setForeground(Qt.GlobalColor.darkGreen)
            elif status == 'error':
                item.setForeground(Qt.GlobalColor.red)
            elif status == 'paused':
                item.setForeground(Qt.GlobalColor.darkYellow)
            else:
                # Reset to default color for idle/disabled (theme-aware)
                item.setForeground(self.palette().color(QPalette.ColorRole.WindowText))

    def _refresh_display(self):
        """Refresh the table display with current worker data."""
        # Get filtered workers
        filtered_workers = self._apply_filter()

        # Update worker count
        self.worker_count_label.setText(f"Workers: {len(filtered_workers)}")

        # Apply sorting if sort state exists
        if self._sort_column is not None and 0 <= self._sort_column < len(self._active_columns):
            col_config = self._active_columns[self._sort_column]
            filtered_workers = self._sort_workers(filtered_workers, col_config)
        else:
            # Default sort: by type, then by status (active first), then hostname
            filtered_workers = sorted(
                filtered_workers,
                key=lambda w: (
                    w.worker_type,  # imx first, then filehost
                    0 if w.status == 'uploading' else (1 if w.status != 'disabled' else 2),
                    w.hostname.lower()
                )
            )

        # Full table rebuild
        self._full_table_rebuild(filtered_workers)

    def _sort_workers(self, workers: list, col_config: ColumnConfig) -> list:
        """Sort workers by the specified column.

        Args:
            workers: List of workers to sort
            col_config: Column configuration for sorting

        Returns:
            Sorted list of workers
        """
        reverse = (self._sort_order == Qt.SortOrder.DescendingOrder)

        if col_config.id == 'hostname':
            return sorted(workers, key=lambda w: w.hostname.lower(), reverse=reverse)
        elif col_config.id == 'speed':
            return sorted(workers, key=lambda w: w.speed_bps, reverse=reverse)
        elif col_config.id == 'status':
            return sorted(workers, key=lambda w: w.status.lower(), reverse=reverse)
        elif col_config.metric_key:
            # Sort by metric value
            def get_metric_value(worker):
                metrics = self._host_metrics_cache.get(worker.hostname.lower(), {})
                period_data = metrics.get(col_config.period, {}) if col_config.period else {}
                return period_data.get(col_config.metric_key, 0)
            return sorted(workers, key=get_metric_value, reverse=reverse)
        else:
            # Default sort
            return workers

    def _full_table_rebuild(self, sorted_workers: list):
        """Rebuild the entire table with the provided workers.

        Args:
            sorted_workers: Pre-sorted list of workers to display
        """
        # Save current selection before clearing
        saved_worker_id = self._selected_worker_id

        # Block signals during update
        self.status_table.blockSignals(True)

        # Clear and rebuild table
        self.status_table.setRowCount(0)
        self._worker_row_map.clear()

        # Track which row to restore selection to
        row_to_select = -1

        for row_idx, worker in enumerate(sorted_workers):
            # Track row for selection restoration
            if saved_worker_id and worker.worker_id == saved_worker_id:
                row_to_select = row_idx

            # Update worker_id to row mapping for targeted updates
            self._worker_row_map[worker.worker_id] = row_idx

            self.status_table.insertRow(row_idx)

            # Render each column based on its configuration
            for col_idx, col_config in enumerate(self._active_columns):
                if col_config.id == 'icon':
                    # Icon column
                    icon_item = QTableWidgetItem()
                    icon_item.setIcon(self._get_host_icon(worker.hostname, worker.worker_type))
                    icon_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    icon_item.setData(Qt.ItemDataRole.UserRole, worker.worker_id)
                    icon_item.setData(Qt.ItemDataRole.UserRole + 1, worker.worker_type)
                    self.status_table.setItem(row_idx, col_idx, icon_item)

                elif col_config.id == 'hostname':
                    # Hostname column with auto-upload indicator
                    # Check if this host has automatic uploads enabled
                    has_auto_upload = False
                    if worker.worker_type == 'filehost':
                        trigger = get_file_host_setting(worker.hostname.lower(), "trigger", "str")
                        has_auto_upload = trigger and trigger != "disabled"

                    if has_auto_upload:
                        # Use a widget with icon for auto-upload hosts
                        container = QWidget()
                        layout = QHBoxLayout(container)
                        layout.setContentsMargins(4, 0, 4, 0)
                        layout.setSpacing(4)

                        # Add hostname text
                        text_label = QLabel(worker.display_name)
                        text_label.setAlignment(col_config.alignment)

                        # Apply disabled styling if needed
                        if worker.status == 'disabled':
                            text_label.setStyleSheet(f"color: {self.palette().color(QPalette.ColorRole.PlaceholderText).name()};")
                            font = text_label.font()
                            font.setItalic(True)
                            text_label.setFont(font)

                        layout.addWidget(text_label)

                        # Add auto icon
                        auto_icon_label = QLabel()
                        auto_icon = get_icon_manager().get_icon('auto')
                        auto_icon_label.setPixmap(auto_icon.pixmap(16, 16))
                        layout.addWidget(auto_icon_label)

                        layout.addStretch()
                        self.status_table.setCellWidget(row_idx, col_idx, container)
                    else:
                        # Regular text item for non-auto hosts
                        hostname_item = QTableWidgetItem(worker.display_name)
                        hostname_item.setTextAlignment(col_config.alignment)

                        # Apply disabled styling
                        if worker.status == 'disabled':
                            hostname_item.setForeground(self.palette().color(QPalette.ColorRole.PlaceholderText))
                            font = hostname_item.font()
                            font.setItalic(True)
                            hostname_item.setFont(font)

                        self.status_table.setItem(row_idx, col_idx, hostname_item)

                elif col_config.id == 'speed':
                    # Speed column
                    speed_text = self._format_speed(worker.speed_bps)
                    speed_item = QTableWidgetItem(speed_text)
                    speed_item.setTextAlignment(col_config.alignment)
                    speed_item.setData(Qt.ItemDataRole.UserRole + 10, worker.speed_bps)

                    # Monospace font for speed
                    speed_font = QFont("Consolas", 9)
                    speed_font.setStyleHint(QFont.StyleHint.Monospace)
                    speed_item.setFont(speed_font)

                    self.status_table.setItem(row_idx, col_idx, speed_item)

                elif col_config.id == 'status':
                    # Status column
                    status_item = QTableWidgetItem()
                    # Map 'disabled' to 'idle' icon since 'disabled' icon doesn't exist
                    status_icon = self._icon_cache.get(
                        'idle' if worker.status == 'disabled' else worker.status,
                        QIcon()
                    )
                    status_item.setIcon(status_icon)
                    status_item.setText(worker.status.capitalize())
                    status_item.setTextAlignment(col_config.alignment)

                    # Color coding
                    if worker.status == 'uploading':
                        status_item.setForeground(Qt.GlobalColor.darkGreen)
                    elif worker.status == 'error':
                        status_item.setForeground(Qt.GlobalColor.red)
                    elif worker.status == 'paused':
                        status_item.setForeground(Qt.GlobalColor.darkYellow)
                    elif worker.status == 'disabled':
                        status_item.setForeground(self.palette().color(QPalette.ColorRole.PlaceholderText))
                        font = status_item.font()
                        font.setItalic(True)
                        status_item.setFont(font)

                    self.status_table.setItem(row_idx, col_idx, status_item)

                elif col_config.id == 'settings':
                    # Settings button column
                    settings_btn = QPushButton()
                    settings_btn.setIcon(self._icon_cache.get('settings', QIcon()))
                    settings_btn.setFixedSize(24, 24)
                    settings_btn.setFlat(True)
                    settings_btn.setToolTip(f"Configure {worker.display_name}")
                    settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                    settings_btn.setProperty("worker_id", worker.worker_id)
                    settings_btn.setProperty("worker_type", worker.worker_type)
                    settings_btn.setProperty("hostname", worker.hostname)
                    settings_btn.clicked.connect(lambda checked, w_id=worker.worker_id, w_type=worker.worker_type, host=worker.hostname:
                                                self._on_settings_clicked(w_id, w_type, host))

                    # Center the button in the cell
                    btn_widget = QWidget()
                    btn_layout = QHBoxLayout(btn_widget)
                    btn_layout.setContentsMargins(0, 0, 0, 0)
                    btn_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    btn_layout.addWidget(settings_btn)
                    self.status_table.setCellWidget(row_idx, col_idx, btn_widget)

                elif col_config.metric_key:
                    # Metric column - get value from cache
                    metrics = self._host_metrics_cache.get(worker.hostname.lower(), {})
                    # Get the period sub-dict (session, today, or all_time)
                    period_data = metrics.get(col_config.period, {}) if col_config.period else {}
                    # Get the specific metric value from that period
                    value = period_data.get(col_config.metric_key, 0)

                    # Format value based on column type
                    if col_config.col_type == ColumnType.BYTES:
                        text = format_bytes(value)
                    elif col_config.col_type == ColumnType.SPEED:
                        text = self._format_speed(value)
                    elif col_config.col_type == ColumnType.PERCENT:
                        text = format_percent(value)
                    elif col_config.col_type == ColumnType.COUNT:
                        text = format_count(value)
                    else:
                        text = str(value) if value else "—"

                    item = QTableWidgetItem(text)
                    item.setTextAlignment(col_config.alignment)

                    # Monospace font for numeric values
                    if col_config.col_type in (ColumnType.BYTES, ColumnType.SPEED, ColumnType.COUNT, ColumnType.PERCENT):
                        metric_font = QFont("Consolas", 9)
                        metric_font.setStyleHint(QFont.StyleHint.Monospace)
                        item.setFont(metric_font)

                    self.status_table.setItem(row_idx, col_idx, item)

        # Restore selection if we had one
        if row_to_select >= 0:
            self.status_table.selectRow(row_to_select)

        self.status_table.blockSignals(False)

    def _on_settings_clicked(self, worker_id: str, worker_type: str, hostname: str):
        """Handle settings button click for a worker.

        Args:
            worker_id: Worker identifier
            worker_type: 'imx' or 'filehost'
            hostname: Host name (e.g., 'rapidgator', 'imx.to')
        """
        if worker_type == 'imx':
            # Open settings dialog to credentials tab (index 1)
            self.open_settings_tab_requested.emit(1)
        else:
            # Open file host config dialog for this host
            # Normalize hostname to lowercase for config manager lookup
            self.open_host_config_requested.emit(hostname.lower())

    def _apply_filter(self) -> list[WorkerStatus]:
        """Apply current filter to worker list.

        Returns:
            Filtered list of workers
        """
        if self.filter_combo is None:
            return list(self._workers.values())

        filter_idx = self.filter_combo.currentIndex()
        all_workers = list(self._workers.values())

        if filter_idx == 0:  # All Hosts
            # Get all hosts from config manager
            config_manager = get_config_manager()
            if config_manager and hasattr(config_manager, 'hosts') and config_manager.hosts:
                # Create placeholder workers for all hosts not in _workers
                result = list(all_workers)
                existing_hosts = {w.hostname.lower() for w in all_workers}

                # Add imx.to placeholder if not already present
                existing_types = {w.worker_type for w in all_workers}
                if 'imx' not in existing_types:
                    imx_placeholder = WorkerStatus(
                        worker_id="placeholder_imx",
                        worker_type="imx",
                        hostname="imx.to",
                        display_name="IMX.to",
                        status="idle"
                    )
                    result.append(imx_placeholder)

                enabled_hosts = []
                disabled_hosts = []

                for host_id, host_config in config_manager.hosts.items():
                    if host_id.lower() not in existing_hosts:
                        is_enabled = get_file_host_setting(host_id, "enabled", "bool")
                        placeholder = WorkerStatus(
                            worker_id=f"placeholder_{host_id}",
                            worker_type="filehost",
                            hostname=host_id,
                            display_name=host_config.name,
                            status="disabled" if not is_enabled else "idle"
                        )
                        if is_enabled:
                            enabled_hosts.append(placeholder)
                        else:
                            disabled_hosts.append(placeholder)

                # Sort: active workers first, then enabled idle, then disabled alphabetically
                result.extend(enabled_hosts)
                disabled_hosts.sort(key=lambda w: w.display_name.lower())
                result.extend(disabled_hosts)
                return result
            return all_workers

        elif filter_idx == 1:  # Used This Session
            return all_workers  # Only workers that have been active

        elif filter_idx == 2:  # Enabled
            config_manager = get_config_manager()
            if config_manager and hasattr(config_manager, 'hosts') and config_manager.hosts:
                result = list(all_workers)
                existing_hosts = {w.hostname.lower() for w in all_workers}

                # Add imx.to placeholder if not already present (imx.to is always enabled)
                existing_types = {w.worker_type for w in all_workers}
                if 'imx' not in existing_types:
                    imx_placeholder = WorkerStatus(
                        worker_id="placeholder_imx",
                        worker_type="imx",
                        hostname="imx.to",
                        display_name="IMX.to",
                        status="idle"
                    )
                    result.append(imx_placeholder)

                for host_id, host_config in config_manager.hosts.items():
                    if host_id.lower() not in existing_hosts:
                        if get_file_host_setting(host_id, "enabled", "bool"):
                            placeholder = WorkerStatus(
                                worker_id=f"placeholder_{host_id}",
                                worker_type="filehost",
                                hostname=host_id,
                                display_name=host_config.name,
                                status="idle"
                            )
                            result.append(placeholder)
                return result
            return all_workers

        elif filter_idx == 3:  # Active Only
            return [w for w in all_workers if w.status == 'uploading']

        elif filter_idx == 4:  # Errors Only
            return [w for w in all_workers if w.status == 'error']

        return all_workers

    def _format_speed(self, speed_bps: float) -> str:
        """Format speed for display.

        Args:
            speed_bps: Speed in bytes per second

        Returns:
            Formatted speed string always as MiB/s with 2 decimals (e.g., "1.23 MiB/s", "0.00 MiB/s")
        """
        # Convert bytes/s to MiB/s (divide by 1024^2)
        mib_per_s = speed_bps / (1024.0 * 1024.0)
        # Always show MiB/s with 2 decimal places for consistency
        return f"{mib_per_s:.2f} MiB/s"

    def _format_display_name(self, hostname: str, worker_type: str) -> str:
        """Format display name for worker.

        Args:
            hostname: Raw hostname
            worker_type: 'imx' or 'filehost'

        Returns:
            Formatted display name
        """
        if worker_type == 'imx':
            return "IMX.to"
        else:
            # Capitalize first letter
            return hostname.capitalize()

    # =========================================================================
    # Event Handlers
    # =========================================================================

    def _on_filter_changed(self, index: int):
        """Handle filter combo box change."""
        self._refresh_display()

    def _on_selection_changed(self):
        """Handle table row selection change."""
        selected_items = self.status_table.selectedItems()
        if selected_items:
            # Find the icon column dynamically (it stores worker_id and worker_type)
            row = self.status_table.currentRow()
            icon_col_idx = self._get_column_index('icon')
            if icon_col_idx >= 0:
                icon_item = self.status_table.item(row, icon_col_idx)
                if icon_item:
                    worker_id = icon_item.data(Qt.ItemDataRole.UserRole)
                    worker_type = icon_item.data(Qt.ItemDataRole.UserRole + 1)
                    self._selected_worker_id = worker_id
                    if worker_id and worker_type:
                        self.worker_selected.emit(worker_id, worker_type)
        else:
            self._selected_worker_id = None

    # =========================================================================
    # Public API
    # =========================================================================

    def get_worker_count(self, worker_type: Optional[str] = None) -> int:
        """Get count of workers.

        Args:
            worker_type: Optional filter ('imx' or 'filehost')

        Returns:
            Number of workers
        """
        if worker_type:
            return sum(1 for w in self._workers.values() if w.worker_type == worker_type)
        return len(self._workers)

    def get_active_count(self) -> int:
        """Get count of actively uploading workers.

        Returns:
            Number of active workers
        """
        return sum(1 for w in self._workers.values() if w.status == 'uploading')

    def get_total_speed(self) -> float:
        """Get total upload speed across all workers.

        Returns:
            Total speed in bytes per second
        """
        return sum(w.speed_bps for w in self._workers.values())

    # =========================================================================
    # Column Context Menu and Settings Persistence
    # =========================================================================

    def _show_column_context_menu(self, position):
        """Show context menu for column visibility and settings."""
        menu = QMenu(self)

        # Core columns section
        core_menu = menu.addMenu("Core Columns")
        for col in CORE_COLUMNS:
            if col.hideable:
                action = core_menu.addAction(col.name if col.name else col.id.capitalize())
                action.setCheckable(True)
                action.setChecked(self._is_column_visible(col.id))
                action.setData(col.id)
                action.triggered.connect(lambda checked, cid=col.id: self._toggle_column(cid, checked))

        # Metrics columns section
        metrics_menu = menu.addMenu("Metrics Columns")

        # Group by period
        session_menu = metrics_menu.addMenu("Session")
        today_menu = metrics_menu.addMenu("Today")
        alltime_menu = metrics_menu.addMenu("All Time")

        for col in METRIC_COLUMNS:
            if col.period == 'session':
                target_menu = session_menu
            elif col.period == 'today':
                target_menu = today_menu
            else:
                target_menu = alltime_menu

            action = target_menu.addAction(col.name)
            action.setCheckable(True)
            action.setChecked(self._is_column_visible(col.id))
            action.setData(col.id)
            action.triggered.connect(lambda checked, cid=col.id: self._toggle_column(cid, checked))

        menu.addSeparator()

        # Reset option
        reset_action = menu.addAction("Reset to Defaults")
        reset_action.triggered.connect(self._reset_column_settings)

        menu.exec(self.status_table.horizontalHeader().mapToGlobal(position))

    def _is_column_visible(self, col_id: str) -> bool:
        """Check if a column is currently visible."""
        return any(col.id == col_id for col in self._active_columns)

    def _toggle_column(self, col_id: str, visible: bool):
        """Toggle visibility of a column."""
        log(f"Toggling column '{col_id}' to {'visible' if visible else 'hidden'}", level="debug", category="ui")

        if visible:
            # Add column if not present
            if col_id in AVAILABLE_COLUMNS and not self._is_column_visible(col_id):
                self._active_columns.append(AVAILABLE_COLUMNS[col_id])
        else:
            # Remove column
            self._active_columns = [col for col in self._active_columns if col.id != col_id]

        log(f"Active columns: {', '.join(col.id for col in self._active_columns)}", level="debug", category="ui")

        self._rebuild_table_columns()
        self._save_column_settings()

    def _rebuild_table_columns(self):
        """Rebuild table with current active columns."""
        # Block signals during programmatic setup to prevent spam
        header = self.status_table.horizontalHeader()
        header.blockSignals(True)

        try:
            self.status_table.setColumnCount(len(self._active_columns))

            # Set headers
            headers = [col.name for col in self._active_columns]
            self.status_table.setHorizontalHeaderLabels(headers)

            # Configure each column
            for i, col in enumerate(self._active_columns):
                # Hostname column is interactive with 180px width (not stretch)
                if col.id == 'hostname':
                    header.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
                    self.status_table.setColumnWidth(i, 180)
                elif col.resizable:
                    header.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
                    self.status_table.setColumnWidth(i, col.width)
                else:
                    header.setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
                    self.status_table.setColumnWidth(i, col.width)
        finally:
            # Always unblock signals
            header.blockSignals(False)

        # Refresh display with new columns
        self._refresh_display()

    def _on_column_resized(self, logical_index: int, old_size: int, new_size: int):
        """Handle column resize - save settings."""
        # Only save if columns are fully initialized (not during startup)
        if self._active_columns:
            self._save_column_settings()

    def _on_column_moved(self, logical_index: int, old_visual: int, new_visual: int):
        """Handle column reorder - save settings."""
        # DON'T reorder _active_columns - it should stay in logical order
        # The visual order is tracked separately in QSettings
        # Only save if columns are fully initialized (not during startup)
        if self._active_columns:
            self._save_column_settings()

    def _on_column_clicked(self, logical_index: int):
        """Handle column header click for sorting."""
        if 0 <= logical_index < len(self._active_columns):
            col_config = self._active_columns[logical_index]
            # Only sort on sortable columns (not icon or widget columns)
            if col_config.col_type not in (ColumnType.ICON, ColumnType.WIDGET):
                # Toggle sort order - FIX: Corrected inverted logic
                header = self.status_table.horizontalHeader()
                current_order = header.sortIndicatorOrder()
                new_order = Qt.SortOrder.AscendingOrder if current_order == Qt.SortOrder.DescendingOrder else Qt.SortOrder.DescendingOrder

                # Store sort state
                self._sort_column = logical_index
                self._sort_order = new_order

                # Trigger refresh instead of direct sortItems()
                self._refresh_display()
                self._save_column_settings()

    def _save_column_settings(self):
        """Save column configuration to QSettings."""
        # Don't save if columns aren't initialized yet
        if not self._active_columns:
            return

        settings = QSettings("ImxUploader", "ImxUploadGUI")

        # Save visible column IDs (in logical order)
        visible_ids = [col.id for col in self._active_columns]
        settings.setValue("worker_status/visible_columns", visible_ids)

        # Debug logging (only log count, not full list to reduce spam)
        log(f"Saved {len(visible_ids)} column settings", level="debug", category="ui")

        # Save visual order separately (for drag-reorder restoration)
        header = self.status_table.horizontalHeader()
        visual_order = []
        for visual_idx in range(len(self._active_columns)):
            logical_idx = header.logicalIndex(visual_idx)
            if 0 <= logical_idx < len(self._active_columns):
                visual_order.append(self._active_columns[logical_idx].id)
        settings.setValue("worker_status/visual_order", visual_order)

        # Save column widths (by column ID)
        widths = {}
        for i, col in enumerate(self._active_columns):
            widths[col.id] = self.status_table.columnWidth(i)
        settings.setValue("worker_status/column_widths", widths)

        # Save sorting state
        sort_column = header.sortIndicatorSection()
        sort_order = header.sortIndicatorOrder()
        if 0 <= sort_column < len(self._active_columns):
            settings.setValue("worker_status/sort_column", self._active_columns[sort_column].id)
            settings.setValue("worker_status/sort_order", sort_order.value)

    def _load_column_settings(self):
        """Load column settings from QSettings."""
        settings = QSettings("ImxUploader", "ImxUploadGUI")

        # Load visible column IDs in saved order
        visible_ids = settings.value("worker_status/visible_columns", None, type=list)

        # Debug logging
        log("Loading column settings from QSettings", level="debug", category="ui")
        log(f"Found saved columns: {', '.join(visible_ids) if visible_ids else 'none'}", level="debug", category="ui")

        if visible_ids:
            # Rebuild active columns from saved IDs (in saved order)
            self._active_columns = []
            for col_id in visible_ids:
                if col_id in AVAILABLE_COLUMNS:
                    self._active_columns.append(AVAILABLE_COLUMNS[col_id])
            log(f"Restored {len(self._active_columns)} columns from settings", level="debug", category="ui")
        else:
            # Use defaults - include BOTH core and metric columns
            self._active_columns = [col for col in CORE_COLUMNS + METRIC_COLUMNS if col.default_visible]
            log(f"No saved settings, using {len(self._active_columns)} default columns", level="debug", category="ui")

        # Load column widths
        widths = settings.value("worker_status/column_widths", None, type=dict)

        # Rebuild table with loaded columns
        self._rebuild_table_columns()

        # Apply saved widths after rebuild
        if widths:
            for i, col in enumerate(self._active_columns):
                if col.id in widths:
                    self.status_table.setColumnWidth(i, int(widths[col.id]))

        # Restore visual column order from saved settings
        visual_order = settings.value("worker_status/visual_order", None, type=list)
        if visual_order:
            header = self.status_table.horizontalHeader()

            # Validate: all IDs in visual_order exist in _active_columns
            active_ids = {col.id for col in self._active_columns}
            valid = (
                all(col_id in active_ids for col_id in visual_order) and
                len(visual_order) == len(self._active_columns) and
                len(set(visual_order)) == len(visual_order)  # No duplicates
            )

            if valid:
                header.blockSignals(True)

                try:
                    # Build logical-to-visual mapping
                    col_id_to_logical = {col.id: i for i, col in enumerate(self._active_columns)}

                    # Apply visual order in single pass
                    for target_visual, col_id in enumerate(visual_order):
                        logical_idx = col_id_to_logical[col_id]
                        current_visual = header.visualIndex(logical_idx)
                        if current_visual != target_visual:
                            header.moveSection(current_visual, target_visual)
                except Exception as e:
                    # Log error but don't crash - columns will just be in default order
                    log(f"Failed to restore column order: {e}", level="warning", category="ui")
                finally:
                    header.blockSignals(False)

        # Restore sorting state
        sort_column_id = settings.value("worker_status/sort_column", None, type=str)
        sort_order = settings.value("worker_status/sort_order", 0, type=int)
        if sort_column_id:
            # Find the column index by ID
            sort_col_idx = next((i for i, col in enumerate(self._active_columns) if col.id == sort_column_id), -1)
            if sort_col_idx >= 0:
                self.status_table.sortItems(sort_col_idx, Qt.SortOrder(sort_order))

    def _reset_column_settings(self):
        """Reset columns to default settings."""
        settings = QSettings("ImxUploader", "ImxUploadGUI")
        settings.remove("worker_status/visible_columns")
        settings.remove("worker_status/column_widths")

        # Reset to default columns
        self._active_columns = [col for col in CORE_COLUMNS if col.default_visible]

        # Rebuild table with defaults
        self._rebuild_table_columns()
