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
    QMenu, QStyle, QStyleOptionHeader, QProgressBar, QAbstractItemView, QToolTip
)
from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot, QSettings, QTimer, pyqtProperty, QSize, QRect, QEvent, QMutex, QMutexLocker, QObject
from PyQt6.QtGui import QIcon, QPixmap, QFont, QPalette, QColor, QFontMetrics

from src.utils.format_utils import format_binary_rate
from src.utils.logger import log
from src.gui.icon_manager import get_icon_manager
from src.core.file_host_config import get_config_manager, get_file_host_setting
from src.gui.widgets.custom_widgets import StorageProgressBar
from src.core.constants import (
    METRIC_FONT_SIZE_SMALL,
    METRIC_FONT_SIZE_DEFAULT,
    METRIC_CELL_PADDING,
    METRIC_MIN_FONT_SIZE,
    METRIC_MAX_FONT_SIZE
)


class NoAutoScrollTable(QTableWidget):
    """QTableWidget subclass that disables auto-scroll-to-selection behavior.

    Prevents the table from automatically scrolling to make the selected
    item visible, which can cause unwanted scroll jumps when other widgets
    trigger focus or selection changes.
    """
    def scrollTo(self, index, hint=QAbstractItemView.ScrollHint.EnsureVisible):
        # Don't auto-scroll - prevents unwanted horizontal scrolling
        # when selection is restored or focus changes
        pass


class MultiLineHeaderView(QHeaderView):
    """Custom header view that renders column names on two lines.

    Splits names like "Uploaded (All Time)" into:
      Line 1: "Uploaded"
      Line 2: "(All Time)"

    Styleable via QSS:
      MultiLineHeaderView { qproperty-primaryColor: #000; qproperty-secondaryColor: #666; }
    """

    def __init__(self, orientation=Qt.Orientation.Horizontal, parent=None, worker_widget=None):
        super().__init__(orientation, parent)
        self._primaryColor = None
        self._secondaryColor = None
        self._worker_widget = worker_widget  # Direct reference for tooltip access
        # Increase default section height for two lines
        self.setMinimumSectionSize(30)  # Allow icon columns to be 28px

    def getPrimaryColor(self):
        return self._primaryColor or self.palette().color(QPalette.ColorRole.WindowText)

    def setPrimaryColor(self, color):
        self._primaryColor = color
        self.update()

    def getSecondaryColor(self):
        return self._secondaryColor or self.palette().color(QPalette.ColorRole.PlaceholderText)

    def setSecondaryColor(self, color):
        self._secondaryColor = color
        self.update()

    # Expose as Qt properties for QSS
    primaryColor = pyqtProperty(QColor, getPrimaryColor, setPrimaryColor)
    secondaryColor = pyqtProperty(QColor, getSecondaryColor, setSecondaryColor)

    def sizeHint(self):
        """Return size hint with room for two lines."""
        base = super().sizeHint()
        # Height for two lines + padding
        return QSize(base.width(), 40)

    def paintSection(self, painter, rect, logicalIndex):
        """Paint header section with two-line text."""
        painter.save()

        # Get the header text
        model = self.model()
        if model is None:
            painter.restore()
            return

        text = model.headerData(logicalIndex, self.orientation(), Qt.ItemDataRole.DisplayRole)
        if text is None:
            text = ""

        # Draw background (let default styling handle this)
        opt = QStyleOptionHeader()
        self.initStyleOption(opt)
        opt.rect = rect
        opt.section = logicalIndex
        opt.text = ""  # We'll draw text ourselves

        # Check sort indicator
        if self.isSortIndicatorShown() and self.sortIndicatorSection() == logicalIndex:
            opt.sortIndicator = (QStyleOptionHeader.SortIndicator.SortUp
                                if self.sortIndicatorOrder() == Qt.SortOrder.AscendingOrder
                                else QStyleOptionHeader.SortIndicator.SortDown)

        # CRITICAL: Isolate drawControl() to prevent painter clipping corruption
        # drawControl() modifies the painter's clipping region; without save/restore,
        # subsequent drawText() calls are clipped and invisible
        painter.save()
        self.style().drawControl(QStyle.ControlElement.CE_Header, opt, painter, self)
        painter.restore()

        # Parse text into primary and secondary parts
        primary_text = text
        secondary_text = ""

        if "(" in text and text.endswith(")"):
            # Split "Uploaded (All Time)" into "Uploaded" and "(All Time)"
            paren_idx = text.rfind("(")
            primary_text = text[:paren_idx].strip()
            secondary_text = text[paren_idx:]

        # Calculate text rectangles
        # Determine alignment based on column to set appropriate padding
        # Get WorkerStatusWidget (header -> table -> widget)
        col_config = None
        widget = self.parent().parent() if self.parent() else None
        if widget and hasattr(widget, '_active_columns') and 0 <= logicalIndex < len(widget._active_columns):
            col_config = widget._active_columns[logicalIndex]

        # Use more left padding for left-aligned columns (hostname, status)
        if col_config and col_config.id in ('hostname', 'status'):
            padding = 4
            left_padding = 18  # Extra padding for left-aligned text
            text_rect = rect.adjusted(left_padding, padding, -padding, -padding)
        else:
            padding = 4
            text_rect = rect.adjusted(padding, padding, -padding, -padding)

        if secondary_text:
            # Two-line layout
            line_height = (text_rect.height() // 2) - 2
            primary_rect = QRect(text_rect.x(), text_rect.y(), text_rect.width(), line_height)
            secondary_rect = QRect(text_rect.x(), text_rect.y() + line_height, text_rect.width(), line_height)

            # Draw primary text (metric name)
            painter.setPen(self.getPrimaryColor())
            primary_font = painter.font()
            primary_font.setPixelSize(11)
            primary_font.setBold(True)
            painter.setFont(primary_font)

            # Use left alignment for hostname and status columns, center for others
            # (col_config already determined earlier)
            if col_config and col_config.id in ('hostname', 'status'):
                alignment = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom
            else:
                alignment = Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignBottom

            # Elide primary text if too long
            fm = painter.fontMetrics()
            primary_text = fm.elidedText(primary_text, Qt.TextElideMode.ElideRight, primary_rect.width())
            painter.drawText(primary_rect, alignment, primary_text)

            # Draw secondary text (period)
            painter.setPen(self.getSecondaryColor())
            secondary_font = painter.font()
            secondary_font.setBold(False)
            secondary_font.setPixelSize(11)
            painter.setFont(secondary_font)

            # Elide secondary text if too long
            fm = painter.fontMetrics()
            secondary_text = fm.elidedText(secondary_text, Qt.TextElideMode.ElideRight, secondary_rect.width())
            painter.drawText(secondary_rect, Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignTop, secondary_text)
        else:
            # Single line (for columns without periods like "Host", "Speed")
            painter.setPen(self.getPrimaryColor())
            single_font = painter.font()
            single_font.setPixelSize(11)
            single_font.setBold(True)
            painter.setFont(single_font)

            # Use left alignment for hostname and status columns, center for others
            # ALWAYS use AlignVCenter for vertical centering in single-line headers
            if col_config and col_config.id in ('hostname', 'status'):
                alignment = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            else:
                alignment = Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter

            # Elide single-line text if too long
            fm = painter.fontMetrics()
            primary_text = fm.elidedText(primary_text, Qt.TextElideMode.ElideRight, text_rect.width())
            painter.drawText(text_rect, alignment, primary_text)

        painter.restore()

    def event(self, event):
        """Handle tooltip events for column headers.

        Args:
            event: The incoming event

        Returns:
            True if event was handled, False otherwise
        """
        if event.type() == QEvent.Type.ToolTip:
            # QHelpEvent uses pos() for local position, globalPos() for screen position
            pos = event.pos()
            logical_index = self.logicalIndexAt(pos)

            # Use stored reference (parent traversal unreliable with Qt scroll areas)
            widget = self._worker_widget
            if widget and hasattr(widget, '_active_columns'):
                if 0 <= logical_index < len(widget._active_columns):
                    col_config = widget._active_columns[logical_index]
                    # Build tooltip: use tooltip field or fall back to full column name
                    tooltip_text = col_config.tooltip or col_config.name
                    if tooltip_text:
                        QToolTip.showText(event.globalPos(), tooltip_text, self)
                        return True

        return super().event(event)


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
    files_remaining: int = 0
    bytes_remaining: int = 0
    storage_used_bytes: int = 0
    storage_total_bytes: int = 0


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
    tooltip: str = ""                          # Tooltip text for header


# Core columns (always available)
CORE_COLUMNS = [
    ColumnConfig('icon', '', 30, ColumnType.ICON, resizable=False, hideable=False, alignment=Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter),
    ColumnConfig('hostname', 'host', 120, ColumnType.TEXT),
    ColumnConfig('speed', 'speed', 90, ColumnType.SPEED, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
    ColumnConfig('status', 'status', 30, ColumnType.ICON, default_visible=True, resizable=False, hideable=False, alignment=Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter),
    ColumnConfig('status_text', 'status text', 100, ColumnType.TEXT, default_visible=True, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
    ColumnConfig('files_remaining', 'queue (files)', 90, ColumnType.COUNT, default_visible=True, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
    ColumnConfig('bytes_remaining', 'queue (bytes)', 110, ColumnType.BYTES, default_visible=True, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
    ColumnConfig('storage', 'storage', 140, ColumnType.WIDGET, default_visible=True, alignment=Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter),
]

# Metric columns (optional, from MetricsStore)
# Organized by metric type, each available for session/today/all_time periods
METRIC_COLUMNS = [
    # Bytes Uploaded - all periods
    ColumnConfig('bytes_session', 'uploaded (session)', 110, ColumnType.BYTES, 'bytes_uploaded', 'session', default_visible=False, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
    ColumnConfig('bytes_today', 'uploaded (today)', 110, ColumnType.BYTES, 'bytes_uploaded', 'today', default_visible=False, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
    ColumnConfig('bytes_alltime', 'uploaded (all time)', 110, ColumnType.BYTES, 'bytes_uploaded', 'all_time', default_visible=False, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
    # Files Uploaded - all periods
    ColumnConfig('files_session', 'files (session)', 90, ColumnType.COUNT, 'files_uploaded', 'session', default_visible=False, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
    ColumnConfig('files_today', 'files (today)', 90, ColumnType.COUNT, 'files_uploaded', 'today', default_visible=False, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
    ColumnConfig('files_alltime', 'files (all time)', 90, ColumnType.COUNT, 'files_uploaded', 'all_time', default_visible=False, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
    # Average Speed - all periods
    ColumnConfig('avg_speed_session', 'avg speed (session)', 120, ColumnType.SPEED, 'avg_speed', 'session', default_visible=False, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
    ColumnConfig('avg_speed_today', 'avg speed (today)', 120, ColumnType.SPEED, 'avg_speed', 'today', default_visible=False, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
    ColumnConfig('avg_speed_alltime', 'avg speed (all time)', 120, ColumnType.SPEED, 'avg_speed', 'all_time', default_visible=False, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
    # Peak Speed - all periods
    ColumnConfig('peak_speed_session', 'peak (session)', 100, ColumnType.SPEED, 'peak_speed', 'session', default_visible=False, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
    ColumnConfig('peak_speed_today', 'peak (today)', 100, ColumnType.SPEED, 'peak_speed', 'today', default_visible=False, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
    ColumnConfig('peak_speed_alltime', 'peak (all time)', 100, ColumnType.SPEED, 'peak_speed', 'all_time', default_visible=False, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
    # Success Rate - all periods
    ColumnConfig('success_rate_session', 'success % (session)', 110, ColumnType.PERCENT, 'success_rate', 'session', default_visible=False, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
    ColumnConfig('success_rate_today', 'success % (today)', 110, ColumnType.PERCENT, 'success_rate', 'today', default_visible=False, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
    ColumnConfig('success_rate_alltime', 'success % (all time)', 110, ColumnType.PERCENT, 'success_rate', 'all_time', default_visible=False, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
]

# Combined list
AVAILABLE_COLUMNS = {col.id: col for col in CORE_COLUMNS + METRIC_COLUMNS}

# Column IDs that use smaller font (8pt) - derived from metric columns
# These are the historical metrics: bytes_uploaded, peak_speed, avg_speed across all periods
SMALL_METRIC_COLUMN_IDS = frozenset(
    col.id for col in METRIC_COLUMNS
    if col.metric_key in ('bytes_uploaded', 'peak_speed', 'avg_speed')
)


def format_bytes(value: int) -> str:
    """Format bytes to human readable (e.g., 1.5 G).

    Args:
        value: Byte count to format

    Returns:
        Human-readable byte string
    """
    if value <= 0:
        return "—"
    for unit in ['B', 'K', 'M', 'G', 'T']:
        if abs(value) < 1024.0:
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} P"


def format_percent(value: float) -> str:
    """Format percentage, showing 100% without decimal.

    Args:
        value: Percentage value (0-100)

    Returns:
        Formatted percentage string (e.g., "50.5%", "100%")
    """
    if value <= 0:
        return "—"
    if value >= 100:
        return "100%"
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
    - Table with columns: Icon | Hostname | Speed (M/s) | Status
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
        self._workers_mutex = QMutex()  # Thread-safe access to _workers
        self._icon_cache: Dict[str, QIcon] = {}
        # Worker ID → row index mapping for O(1) row lookups
        # IMPORTANT: Only valid between full refreshes (_full_table_rebuild)
        # Becomes stale when workers are added/removed until next refresh
        self._worker_row_map: Dict[str, int] = {}
        # Preserved column widths during column visibility changes
        self._preserved_widths: Dict[str, int] = {}
        # Font cache for metric columns (column_id -> (QFont, QFontMetrics))
        self._column_font_cache: Dict[str, Tuple[QFont, QFontMetrics]] = {}

        # Timer for debounced column resize text re-fitting
        self._resize_refit_timer = QTimer()
        self._resize_refit_timer.setSingleShot(True)
        self._resize_refit_timer.setInterval(150)  # 150ms debounce
        self._resize_refit_timer.timeout.connect(self._refit_resized_columns)
        self._pending_resize_columns: set = set()  # Track which columns need re-fitting

        # Active columns (user's current selection)
        self._active_columns: List[ColumnConfig] = []

        # Metrics store connection
        self._metrics_store = None
        self._host_metrics_cache: Dict[str, Dict[str, Any]] = {}  # host_name -> metrics dict

        # UI references
        self.status_table: Optional[QTableWidget] = None
        self.filter_combo: Optional[QComboBox] = None

        # Selection tracking for refresh persistence
        self._selected_worker_id: Optional[str] = None

        # Sort state tracking
        self._sort_column: Optional[int] = None
        self._sort_order: Qt.SortOrder = Qt.SortOrder.AscendingOrder

        self._init_ui()
        self._load_icons()

    def keyPressEvent(self, event):
        """Handle keyboard shortcuts for table."""
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            selected = self.status_table.selectedItems()
            if selected:
                self._on_row_double_clicked(None)
                event.accept()
                return
        super().keyPressEvent(event)

    def _init_ui(self):
        """Initialize the user interface."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)

        # Top control bar
        control_layout = QHBoxLayout()
        control_layout.setSpacing(8)

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
        self.status_table = NoAutoScrollTable()
        self.status_table.setIconSize(QSize(22, 22))  # Host icons - scale by height, centered

        # Configure table behavior
        self.status_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.status_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.status_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.status_table.setAlternatingRowColors(True)
        self.status_table.verticalHeader().setVisible(False)
        self.status_table.horizontalHeader().setVisible(True)
        self.status_table.setShowGrid(True)

        # Row height
        self.status_table.verticalHeader().setDefaultSectionSize(30)

        # Disable built-in sorting (conflicts with manual sorting)
        # self.status_table.setSortingEnabled(True)

        # Use custom multi-line header (pass self for tooltip access)
        header = MultiLineHeaderView(Qt.Orientation.Horizontal, self.status_table, worker_widget=self)
        self.status_table.setHorizontalHeader(header)

        # Enable sort indicators and header clicks
        header.setSortIndicatorShown(True)
        header.setSectionsClickable(True)

        # Header context menu and drag reorder
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

        # Double-click signal
        self.status_table.itemDoubleClicked.connect(self._on_row_double_clicked)

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
        self._icon_cache['disabled'] = icon_mgr.get_icon('disabledhost')
        self._icon_cache['settings'] = icon_mgr.get_icon('settings')

        # Map spinup statuses to idle icon
        self._icon_cache['ready'] = icon_mgr.get_icon('status_idle')
        self._icon_cache['starting'] = icon_mgr.get_icon('status_idle')
        self._icon_cache['authenticating'] = icon_mgr.get_icon('status_idle')

        # Retry/error status icons - map to existing icons
        self._icon_cache['retry_pending'] = icon_mgr.get_icon('status_idle')
        self._icon_cache['failed'] = icon_mgr.get_icon('status_error')
        self._icon_cache['network_error'] = icon_mgr.get_icon('status_error')

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
            icon = icon_mgr.get_file_host_icon('imx.to', dimmed=False)
        else:
            # Use icon manager's file host icon loading (with fallback chain)
            icon = icon_mgr.get_file_host_icon(hostname.lower(), dimmed=False)

        self._icon_cache[cache_key] = icon
        return icon

    def _should_show_worker_logos(self) -> bool:
        """Check if file host logos should be shown instead of text.

        Returns:
            True if logos should be shown, False for text display
        """
        settings = QSettings()
        return settings.value('ui/show_worker_logos', True, type=bool)

    def _load_host_logo(self, host_id: str, height: int = 20) -> Optional[QLabel]:
        """Load file host logo as a QLabel.

        Uses IconManager to get the logo path, ensuring consistent naming
        conventions and security validation across the application.

        Args:
            host_id: Host identifier (e.g., 'rapidgator', 'fileboom', 'imx')
            height: Logo height in pixels (default 20, slightly smaller than settings tab's 22)

        Returns:
            QLabel with logo pixmap, or None if not found
        """
        from PyQt6.QtGui import QPixmap

        # Use IconManager for consistent path resolution and security validation
        icon_mgr = get_icon_manager()
        if not icon_mgr:
            return None

        logo_path = icon_mgr.get_file_host_logo_path(host_id)
        if not logo_path:
            return None

        try:
            pixmap = QPixmap(logo_path)
            if pixmap.isNull():
                return None

            # Scale to height, maintaining aspect ratio
            scaled_pixmap = pixmap.scaledToHeight(height, Qt.TransformationMode.SmoothTransformation)

            logo_label = QLabel()
            logo_label.setPixmap(scaled_pixmap)
            logo_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            return logo_label
        except Exception:
            return None

    def _create_storage_progress_widget(self, used_bytes: int, total_bytes: int, worker_id: str) -> QWidget:
        """Create storage progress bar widget using reusable StorageProgressBar class.

        Args:
            used_bytes: Used storage in bytes
            total_bytes: Total storage in bytes
            worker_id: Worker identifier for tracking

        Returns:
            StorageProgressBar widget configured with storage values
        """
        # Calculate left_bytes from used and total
        left_bytes = total_bytes - used_bytes if total_bytes > 0 else 0

        # Create widget using reusable StorageProgressBar class
        storage_widget = StorageProgressBar()

        # CRITICAL: Call update_storage() BEFORE setCellWidget() to avoid race condition
        # This ensures the widget is fully populated before Qt geometry events fire
        storage_widget.update_storage(total_bytes, left_bytes)

        # Store worker_id for updates
        storage_widget.setProperty("worker_id", worker_id)

        return storage_widget

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

        # Populate initial metrics from database (deferred until after GUI ready)
        if self._metrics_store and not hasattr(self, '_metrics_populated'):
            QTimer.singleShot(100, self._populate_initial_metrics)
            self._metrics_populated = True

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
            except TypeError:
                # Not connected yet, this is fine
                pass

            # Now connect (fresh or reconnect)
            self._metrics_store.signals.host_metrics_updated.connect(self._on_host_metrics_updated)

            # NOTE: _populate_initial_metrics() deferred to start_monitoring()
            # to avoid blocking database queries during GUI construction

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
            # Load cached storage data from QSettings for file hosts
            storage_used = 0
            storage_total = 0
            if worker_type == 'filehost':
                settings = QSettings("ImxUploader", "ImxUploadGUI")
                total_str = settings.value(f"FileHosts/{hostname.lower()}/storage_total", "0")
                left_str = settings.value(f"FileHosts/{hostname.lower()}/storage_left", "0")
                try:
                    storage_total = int(total_str) if total_str else 0
                    storage_left = int(left_str) if left_str else 0
                    storage_used = storage_total - storage_left
                except (ValueError, TypeError):
                    storage_used = 0
                    storage_total = 0

            self._workers[worker_id] = WorkerStatus(
                worker_id=worker_id,
                worker_type=worker_type,
                hostname=hostname,
                display_name=self._format_display_name(hostname, worker_type),
                speed_bps=speed_bps,
                status=status,
                last_update=datetime.now().timestamp(),
                storage_used_bytes=storage_used,
                storage_total_bytes=storage_total
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
            # Use targeted update instead of full rebuild
            self._update_worker_progress_cell(worker_id, progress_bytes, total_bytes)

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
            # Use targeted updates instead of full rebuild
            self._update_worker_status_cell(worker_id, 'error')
            self._update_worker_speed(worker_id, 0.0)

    @pyqtSlot(str, object, object)
    def update_worker_storage(self, host_id: str, total_bytes: int, left_bytes: int):
        """Update worker storage quota information.

        Args:
            host_id: Host identifier (e.g., 'rapidgator')
            total_bytes: Total storage quota in bytes
            left_bytes: Remaining storage in bytes
        """
        # Convert host_id to worker_id pattern: filehost_{host_id}
        worker_id = f"filehost_{host_id.lower().replace(' ', '_')}"

        if worker_id in self._workers:
            worker = self._workers[worker_id]
            worker.storage_total = total_bytes
            worker.storage_left = left_bytes
            worker.last_update = datetime.now().timestamp()
            # Update storage column cell (used_bytes = total - left)
            used_bytes = total_bytes - left_bytes
            self._update_storage_progress(worker_id, used_bytes, total_bytes)

    @pyqtSlot(int, int)
    def update_queue_columns(self, files_remaining: int, bytes_remaining: int):
        """Update queue-based columns (Files Left, Remaining) for IMX worker.

        Thread-safe via QMutexLocker on _workers dictionary.

        Args:
            files_remaining: Total images remaining across all galleries
            bytes_remaining: Total bytes remaining across all galleries
        """
        with QMutexLocker(self._workers_mutex):
            for worker_id, worker in self._workers.items():
                if worker.worker_type == 'imx':
                    worker.files_remaining = files_remaining
                    worker.bytes_remaining = bytes_remaining
                    self._update_files_remaining(worker_id, files_remaining)
                    self._update_bytes_remaining(worker_id, bytes_remaining)
                    break  # Only one IMX worker

    @pyqtSlot(str, int, int)
    def update_filehost_queue_columns(self, host_name: str, files_remaining: int, bytes_remaining: int):
        """Update queue columns for a specific file host worker.

        Called when file host uploads complete/fail (event-driven, not polled).
        Thread-safe via QMutexLocker on _workers dictionary.

        Args:
            host_name: Name of the file host (e.g., 'rapidgator', 'keep2share')
            files_remaining: Number of pending zip uploads for this host
            bytes_remaining: Total bytes remaining for pending uploads
        """
        with QMutexLocker(self._workers_mutex):
            for worker_id, worker in self._workers.items():
                if worker.worker_type == 'filehost' and worker.hostname.lower() == host_name.lower():
                    worker.files_remaining = files_remaining
                    worker.bytes_remaining = bytes_remaining
                    self._update_files_remaining(worker_id, files_remaining)
                    self._update_bytes_remaining(worker_id, bytes_remaining)
                    break

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
        """Schedule a display refresh - ONLY for worker add/remove and filter changes.

        This method should ONLY be called when:
        - Workers are added (new rows needed)
        - Workers are removed (rows need deletion)
        - Filters change (visible rows change)

        DO NOT call for worker data updates - use targeted cell updates instead:
        - _update_worker_status_cell() for status changes
        - _update_worker_speed() for speed changes
        - _update_worker_progress_cell() for progress changes
        - _update_worker_metrics() for metrics changes
        """
        # Full table rebuild - only when worker list changes
        self._refresh_display()

    # =========================================================================
    # Targeted Cell Update Methods
    # =========================================================================

    def _update_worker_cell(self, worker_id: str, column: int, value: Any,
                           formatter: Optional[Callable] = None):
        """Update a single cell for a worker - targeted update.

        Args:
            worker_id: Worker identifier
            column: Column index to update
            value: New value for the cell
            formatter: Optional callable to format the value
        """
        row = self._worker_row_map.get(worker_id)
        if row is None:
            return  # Worker not in current view

        # Bounds checking - worker may have been removed or columns changed
        if row < 0 or row >= self.status_table.rowCount():
            return  # Row out of bounds

        if column < 0 or column >= self.status_table.columnCount():
            return  # Column out of bounds

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
            # Also update tooltip
            row = self._worker_row_map.get(worker_id)
            if row is not None:
                item = self.status_table.item(row, col_idx)
                if item:
                    worker = self._workers.get(worker_id)
                    display_name = worker.display_name if worker else worker_id
                    speed_text = self._format_speed(speed_bps)
                    item.setToolTip(f"Current Speed\n{display_name}: {speed_text}")

    def _update_worker_status_cell(self, worker_id: str, status: str):
        """Update status icon and text cells separately.

        Args:
            worker_id: Worker identifier
            status: New status string (may be compound format like "retry_pending:45")
        """
        row = self._worker_row_map.get(worker_id)
        if row is None:
            return

        # Parse compound status (e.g., "retry_pending:45" or "failed:error message")
        base_status = status
        detail = ""
        if ":" in status:
            parts = status.split(":", 1)
            base_status = parts[0]
            detail = parts[1] if len(parts) > 1 else ""

        # Determine display text, tooltip, and color based on base_status
        display_text = base_status.capitalize()
        tooltip_text = f"Status: {base_status.capitalize()}"
        status_color = None  # Will use default if None

        if base_status == 'retry_pending':
            # Countdown display for retry
            if detail:
                display_text = f"Retrying in {detail}s"
                tooltip_text = f"Retry pending - will retry in {detail} seconds"
            else:
                display_text = "Retrying..."
                tooltip_text = "Retry pending"
            status_color = QColor("#DAA520")  # Goldenrod for dark theme visibility
        elif base_status == 'failed':
            display_text = "Failed"
            if detail:
                tooltip_text = f"Failed: {detail}"
            else:
                tooltip_text = "Upload failed"
            status_color = QColor("#FF6B6B")  # Red for dark theme, visible
        elif base_status == 'network_error':
            display_text = "Network Error"
            if detail:
                tooltip_text = f"Network Error: {detail}"
            else:
                tooltip_text = "Network error occurred"
            status_color = QColor("#DAA520")  # Goldenrod
        elif base_status == 'uploading':
            status_color = QColor("darkgreen")
        elif base_status == 'error':
            status_color = QColor("red")
        elif base_status == 'paused':
            status_color = QColor("#B8860B")  # Dark goldenrod

        # Update icon column
        icon_col_idx = self._get_column_index('status')
        if icon_col_idx >= 0:
            icon_item = self.status_table.item(row, icon_col_idx)
            if icon_item:
                # Use base_status for icon lookup
                status_icon = self._icon_cache.get(base_status, QIcon())
                icon_item.setIcon(status_icon)
                icon_item.setToolTip(tooltip_text)

        # Update text column
        text_col_idx = self._get_column_index('status_text')
        if text_col_idx >= 0:
            text_item = self.status_table.item(row, text_col_idx)
            if text_item:
                text_item.setText(display_text)
                text_item.setToolTip(tooltip_text)

                # Reset font to non-italic first (in case previously disabled)
                font = text_item.font()
                font.setItalic(False)
                text_item.setFont(font)

                # Apply color coding based on status
                if status_color:
                    text_item.setForeground(status_color)
                elif base_status == 'disabled':
                    text_item.setForeground(self.palette().color(QPalette.ColorRole.PlaceholderText))
                    font = text_item.font()
                    font.setItalic(True)
                    text_item.setFont(font)
                else:
                    # Reset to default color for other statuses
                    text_item.setForeground(self.palette().color(QPalette.ColorRole.Text))

    def _update_worker_progress_cell(self, worker_id: str, progress_bytes: int, total_bytes: int):
        """Update progress cell for a specific worker - targeted update.

        Args:
            worker_id: Worker identifier
            progress_bytes: Bytes uploaded so far
            total_bytes: Total bytes to upload
        """
        row = self._worker_row_map.get(worker_id)
        if row is None:
            return

        # Find progress column (if it exists in active columns)
        col_idx = self._get_column_index('progress')
        if col_idx >= 0:
            percentage = (progress_bytes / total_bytes * 100) if total_bytes > 0 else 0
            text = f"{percentage:.1f}%"

            item = self.status_table.item(row, col_idx)
            if item and item.text() != text:
                # Block signals to prevent cascade updates
                self.status_table.blockSignals(True)
                item.setText(text)
                self.status_table.blockSignals(False)

    def _update_files_remaining(self, worker_id: str, files_remaining: int):
        """Update files remaining cell for a worker.

        Args:
            worker_id: Worker identifier
            files_remaining: Number of files remaining
        """
        col_idx = self._get_column_index('files_remaining')
        if col_idx >= 0:
            text = format_count(files_remaining) if files_remaining > 0 else "—"
            self._update_worker_cell(worker_id, col_idx, files_remaining, lambda v: format_count(v) if v > 0 else "—")

    def _update_bytes_remaining(self, worker_id: str, bytes_remaining: int):
        """Update bytes remaining cell for a worker.

        Args:
            worker_id: Worker identifier
            bytes_remaining: Bytes remaining
        """
        col_idx = self._get_column_index('bytes_remaining')
        if col_idx >= 0:
            self._update_worker_cell(worker_id, col_idx, bytes_remaining, lambda v: format_bytes(v) if v > 0 else "—")

    def _update_storage_progress(self, worker_id: str, used_bytes: int, total_bytes: int):
        """Update storage progress bar for a worker using StorageProgressBar.update_storage().

        Args:
            worker_id: Worker identifier
            used_bytes: Used storage bytes
            total_bytes: Total storage bytes
        """
        row = self._worker_row_map.get(worker_id)
        if row is None:
            return

        col_idx = self._get_column_index('storage')
        if col_idx < 0:
            return

        # Get the StorageProgressBar widget
        widget = self.status_table.cellWidget(row, col_idx)
        if isinstance(widget, StorageProgressBar):
            # Calculate left_bytes from used and total
            left_bytes = total_bytes - used_bytes if total_bytes > 0 else 0

            # Update storage using the widget's update_storage() method
            widget.update_storage(total_bytes, left_bytes)

    def _refresh_display(self):
        """Refresh the table display with current worker data."""
        # Get filtered workers
        filtered_workers = self._apply_filter()

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
                    # Icon column - clickable button that opens host settings
                    icon_btn = QPushButton()
                    icon_btn.setIcon(self._get_host_icon(worker.hostname, worker.worker_type))
                    icon_btn.setFixedSize(26, 26)
                    icon_btn.setIconSize(QSize(20, 20))
                    icon_btn.setFlat(True)
                    icon_btn.setStyleSheet("QPushButton { border: none; padding: 2px; } QPushButton:hover { background-color: rgba(128,128,128,0.3); border-radius: 4px; }")
                    icon_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                    icon_btn.setToolTip(f"Configure {worker.display_name}")
                    icon_btn.setProperty("worker_id", worker.worker_id)
                    icon_btn.setProperty("worker_type", worker.worker_type)
                    icon_btn.setProperty("hostname", worker.hostname)
                    icon_btn.clicked.connect(self._on_icon_button_clicked)

                    container = QWidget()
                    layout = QHBoxLayout(container)
                    layout.setContentsMargins(0, 0, 0, 0)
                    layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    layout.addWidget(icon_btn)
                    container.setProperty("worker_id", worker.worker_id)

                    # Create an invisible item to store worker_id for tests/selection
                    icon_item = QTableWidgetItem()
                    icon_item.setData(Qt.ItemDataRole.UserRole, worker.worker_id)
                    self.status_table.setItem(row_idx, col_idx, icon_item)
                    self.status_table.setCellWidget(row_idx, col_idx, container)

                elif col_config.id == 'hostname':
                    # Hostname column with auto-upload indicator and optional logo
                    # Check if this host has automatic uploads enabled
                    has_auto_upload = False
                    if worker.worker_type == 'filehost':
                        trigger = get_file_host_setting(worker.hostname.lower(), "trigger", "str")
                        has_auto_upload = trigger and trigger != "disabled"

                    # Check if logos should be shown instead of text
                    show_logos = self._should_show_worker_logos()
                    logo_label = None
                    if show_logos:
                        # Try to load host logo
                        host_id = 'imx' if worker.worker_type == 'imx' else worker.hostname.lower()
                        logo_label = self._load_host_logo(host_id, height=22)

                    # Decide whether to use widget (logo or auto icon) or plain text
                    use_widget = has_auto_upload or (show_logos and logo_label is not None)

                    if use_widget:
                        # Use a widget with logo and/or auto icon
                        container = QWidget()
                        layout = QHBoxLayout(container)
                        layout.setContentsMargins(4, 0, 4, 0)
                        layout.setSpacing(4)

                        # Add logo or text based on availability
                        if show_logos and logo_label:
                            # Show logo instead of text (left-aligned)
                            layout.addWidget(logo_label)
                        else:
                            # Fallback to text (when logo not found or setting disabled)
                            text_label = QLabel(worker.display_name)
                            text_label.setAlignment(col_config.alignment)

                            # Apply disabled styling if needed
                            if worker.status == 'disabled':
                                self._apply_disabled_style(text_label)

                            layout.addWidget(text_label)

                        # Stretch pushes auto icon to right edge (if present)
                        if has_auto_upload:
                            layout.addStretch()

                            # Add auto icon - smaller size for compact display (right-aligned)
                            # Use auto-disabled icon when worker is disabled
                            auto_icon_label = QLabel()
                            auto_icon_key = 'auto-disabled' if worker.status == 'disabled' else 'auto'
                            auto_icon = get_icon_manager().get_icon(auto_icon_key)
                            auto_icon_label.setPixmap(auto_icon.pixmap(32, 14))
                            layout.addWidget(auto_icon_label)

                        tooltip = worker.display_name
                        if has_auto_upload:
                            tooltip += " (auto-upload enabled)"
                        container.setToolTip(tooltip)

                        # Store worker data on container for double-click handling
                        container.setProperty('worker_id', worker.worker_id)
                        container.setProperty('worker_type', worker.worker_type)
                        container.setProperty('hostname', worker.hostname)

                        # Install event filter to handle double-clicks on cell widgets
                        container.installEventFilter(self)

                        # Create an invisible item to store worker_id for tests/selection
                        # NOTE: Use empty string for text - the container widget shows the logo/text
                        # Setting text here would cause it to render BEHIND the widget (overlap)
                        hostname_item = QTableWidgetItem("")
                        hostname_item.setData(Qt.ItemDataRole.UserRole, worker.worker_id)
                        self.status_table.setItem(row_idx, col_idx, hostname_item)
                        self.status_table.setCellWidget(row_idx, col_idx, container)
                    else:
                        # Regular text item for non-auto hosts when logos disabled
                        hostname_item = QTableWidgetItem(worker.display_name)
                        hostname_item.setTextAlignment(col_config.alignment)
                        hostname_item.setToolTip(worker.display_name)
                        hostname_item.setData(Qt.ItemDataRole.UserRole, worker.worker_id)

                        # Apply disabled styling
                        if worker.status == 'disabled':
                            self._apply_disabled_style(hostname_item)

                        self.status_table.setItem(row_idx, col_idx, hostname_item)

                elif col_config.id == 'speed':
                    # Speed column
                    speed_text = self._format_speed(worker.speed_bps)
                    speed_item = QTableWidgetItem(speed_text)
                    speed_item.setTextAlignment(col_config.alignment)
                    speed_item.setData(Qt.ItemDataRole.UserRole, worker.worker_id)
                    speed_item.setData(Qt.ItemDataRole.UserRole + 10, worker.speed_bps)
                    speed_item.setToolTip(f"Current Speed\n{worker.display_name}: {speed_text}")

                    # Monospace font for speed
                    speed_font = QFont("Consolas")
                    speed_font.setPointSizeF(METRIC_FONT_SIZE_DEFAULT)
                    speed_font.setStyleHint(QFont.StyleHint.Monospace)
                    speed_item.setFont(speed_font)

                    self.status_table.setItem(row_idx, col_idx, speed_item)

                elif col_config.id == 'status':
                    # Status icon column (icon only)
                    status_icon_item = QTableWidgetItem()
                    # Use status directly for icon - no mapping needed
                    status_icon = self._icon_cache.get(worker.status, QIcon())
                    status_icon_item.setIcon(status_icon)
                    status_icon_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    status_icon_item.setToolTip(f"Status: {worker.status.capitalize()}")
                    status_icon_item.setData(Qt.ItemDataRole.UserRole, worker.worker_id)
                    self.status_table.setItem(row_idx, col_idx, status_icon_item)

                elif col_config.id == 'status_text':
                    # Status text column (text only with color coding)
                    status_text_item = QTableWidgetItem(worker.status.capitalize())
                    status_text_item.setTextAlignment(col_config.alignment)
                    status_text_item.setToolTip(f"Status: {worker.status.capitalize()}")

                    # Color coding
                    if worker.status == 'uploading':
                        status_text_item.setForeground(QColor("darkgreen"))
                    elif worker.status == 'error':
                        status_text_item.setForeground(QColor("red"))
                    elif worker.status == 'paused':
                        status_text_item.setForeground(QColor("#B8860B"))  # Dark goldenrod
                    elif worker.status == 'disabled':
                        status_text_item.setForeground(self.palette().color(QPalette.ColorRole.PlaceholderText))
                        font = status_text_item.font()
                        font.setItalic(True)
                        status_text_item.setFont(font)

                    self.status_table.setItem(row_idx, col_idx, status_text_item)

                elif col_config.id == 'files_remaining':
                    # Files remaining column
                    files_text = format_count(worker.files_remaining) if worker.files_remaining > 0 else "—"
                    files_item = QTableWidgetItem(files_text)
                    files_item.setTextAlignment(col_config.alignment)
                    files_item.setToolTip(f"Queue (Files)\n{worker.display_name}: {worker.files_remaining:,} files")
                    # Monospace font
                    files_font = QFont("Consolas")
                    files_font.setPointSizeF(METRIC_FONT_SIZE_DEFAULT)
                    files_font.setStyleHint(QFont.StyleHint.Monospace)
                    files_item.setFont(files_font)
                    self.status_table.setItem(row_idx, col_idx, files_item)

                elif col_config.id == 'bytes_remaining':
                    # Bytes remaining column
                    bytes_text = format_bytes(worker.bytes_remaining) if worker.bytes_remaining > 0 else "—"
                    bytes_item = QTableWidgetItem(bytes_text)
                    bytes_item.setTextAlignment(col_config.alignment)
                    bytes_item.setData(Qt.ItemDataRole.UserRole + 10, worker.bytes_remaining)
                    bytes_item.setToolTip(f"Queue (Bytes)\n{worker.display_name}: {worker.bytes_remaining:,} bytes")
                    # Monospace font
                    bytes_font = QFont("Consolas")
                    bytes_font.setPointSizeF(METRIC_FONT_SIZE_DEFAULT)
                    bytes_font.setStyleHint(QFont.StyleHint.Monospace)
                    bytes_item.setFont(bytes_font)
                    self.status_table.setItem(row_idx, col_idx, bytes_item)

                elif col_config.id == 'storage':
                    # Storage progress bar column
                    # IMX.to has unlimited storage - show green bar with infinity symbol
                    if worker.worker_type == 'imx':
                        storage_widget = StorageProgressBar()
                        storage_widget.set_unlimited()
                        storage_widget.setProperty("worker_id", worker.worker_id)
                    else:
                        storage_widget = self._create_storage_progress_widget(
                            worker.storage_used_bytes,
                            worker.storage_total_bytes,
                            worker.worker_id
                        )
                    self.status_table.setCellWidget(row_idx, col_idx, storage_widget)

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
                        raw_value = f"{value:,} bytes" if value else "—"
                    elif col_config.col_type == ColumnType.SPEED:
                        text = self._format_speed(value)
                        raw_value = f"{value:,.0f} B/s" if value else "—"
                    elif col_config.col_type == ColumnType.PERCENT:
                        text = format_percent(value)
                        raw_value = f"{value:.2f}%" if value > 0 else "—"
                    elif col_config.col_type == ColumnType.COUNT:
                        text = format_count(value)
                        raw_value = f"{value:,}" if value else "—"
                    else:
                        text = str(value) if value else "—"
                        raw_value = str(value) if value else "—"

                    item = QTableWidgetItem(text)
                    item.setTextAlignment(col_config.alignment)
                    # Build detailed tooltip: column name, host, value
                    item.setToolTip(f"{col_config.name.capitalize()}\n{worker.display_name}: {raw_value}")

                    # Monospace font for numeric values
                    # Use 8pt for uploaded/peak/avg speed metrics, 9pt for others
                    if col_config.col_type in (ColumnType.BYTES, ColumnType.SPEED, ColumnType.COUNT, ColumnType.PERCENT):
                        # Get or create cached base font and metrics for this column
                        if col_config.id not in self._column_font_cache:
                            # Check if this is one of the 9 specific metrics that should use 8pt font
                            is_small_metric = col_config.id in SMALL_METRIC_COLUMN_IDS
                            base_font = QFont("Consolas")
                            base_font.setStyleHint(QFont.StyleHint.Monospace)
                            base_font.setStretch(QFont.Stretch.SemiCondensed)  # Less aggressive than Condensed
                            if is_small_metric:
                                base_font.setPointSizeF(METRIC_FONT_SIZE_SMALL)  # Slightly smaller than default
                            else:
                                base_font.setPointSizeF(METRIC_FONT_SIZE_DEFAULT)  # Use float variant for consistency

                            # Cache the base font and its metrics
                            self._column_font_cache[col_config.id] = (base_font, QFontMetrics(base_font))

                        # Retrieve cached base font and metrics
                        base_font, base_fm = self._column_font_cache[col_config.id]

                        # Clone the base font for this cell (may be scaled)
                        metric_font = QFont(base_font)

                        # Shrink-to-fit: scale font if text doesn't fit in column width
                        col_width = self.status_table.columnWidth(col_idx)
                        padding = METRIC_CELL_PADDING  # Account for cell padding
                        available_width = max(0, col_width - padding)  # Bug 3: Negative width protection

                        # Use cached metrics for measurement
                        text_width = base_fm.horizontalAdvance(text)

                        if text_width > available_width and available_width > 0:
                            # Calculate scale factor and new font size
                            scale = available_width / text_width
                            base_size = metric_font.pointSizeF()
                            new_size = max(METRIC_MIN_FONT_SIZE, base_size * scale)  # Minimum font size for readability
                            metric_font.setPointSizeF(new_size)

                        item.setFont(metric_font)

                    self.status_table.setItem(row_idx, col_idx, item)

        # Restore selection if we had one
        if row_to_select >= 0:
            self.status_table.selectRow(row_to_select)

        self.status_table.blockSignals(False)

    def _on_icon_button_clicked(self):
        """Handle icon button click using sender properties.

        Retrieves worker info from the button's properties to avoid lambda
        closure memory leak issues. This is called when any icon button in
        the worker table is clicked.
        """
        btn = self.sender()
        if btn:
            worker_id = btn.property("worker_id")
            worker_type = btn.property("worker_type")
            hostname = btn.property("hostname")
            if worker_id and worker_type and hostname:
                self._on_settings_clicked(worker_id, worker_type, hostname)

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
                imx_exists = any(w.worker_type == "imx" for w in self._workers.values())
                if not imx_exists:
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
                        # Check if worker already exists before creating placeholder
                        worker_id = f"filehost_{host_id}"
                        if worker_id not in self._workers:
                            is_enabled = get_file_host_setting(host_id, "enabled", "bool")
                            # Load cached storage data from QSettings for filehost placeholders
                            settings = QSettings("ImxUploader", "ImxUploadGUI")
                            total_str = settings.value(f"FileHosts/{host_id}/storage_total", "0")
                            left_str = settings.value(f"FileHosts/{host_id}/storage_left", "0")
                            try:
                                storage_total = int(total_str) if total_str else 0
                                storage_left = int(left_str) if left_str else 0
                                storage_used = storage_total - storage_left
                            except (ValueError, TypeError):
                                storage_used = 0
                                storage_total = 0
                            placeholder = WorkerStatus(
                                worker_id=f"placeholder_{host_id}",
                                worker_type="filehost",
                                hostname=host_id,
                                display_name=host_config.name,
                                status="disabled",
                                storage_used_bytes=storage_used,
                                storage_total_bytes=storage_total
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
                imx_exists = any(w.worker_type == "imx" for w in self._workers.values())
                if not imx_exists:
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
                            # Check if worker already exists before creating placeholder
                            worker_id = f"filehost_{host_id}"
                            if worker_id not in self._workers:
                                # Load cached storage data from QSettings for enabled filehost placeholders
                                settings = QSettings("ImxUploader", "ImxUploadGUI")
                                total_str = settings.value(f"FileHosts/{host_id}/storage_total", "0")
                                left_str = settings.value(f"FileHosts/{host_id}/storage_left", "0")
                                try:
                                    storage_total = int(total_str) if total_str else 0
                                    storage_left = int(left_str) if left_str else 0
                                    storage_used = storage_total - storage_left
                                except (ValueError, TypeError):
                                    storage_used = 0
                                    storage_total = 0
                                placeholder = WorkerStatus(
                                    worker_id=f"placeholder_{host_id}",
                                    worker_type="filehost",
                                    hostname=host_id,
                                    display_name=host_config.name,
                                    status="disabled",
                                    storage_used_bytes=storage_used,
                                    storage_total_bytes=storage_total
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
            Formatted speed string as M/s with 2 decimals (e.g., "1.23 M/s")
            or em-dash (—) for zero/none values
        """
        # Return em-dash for zero or None values
        if speed_bps is None or speed_bps <= 0:
            return "—"

        # Convert bytes/s to M/s (divide by 1024^2)
        mib_per_s = speed_bps / (1024.0 * 1024.0)
        # Show M/s with 2 decimal places
        return f"{mib_per_s:.2f} M/s"

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
        self._save_column_settings()

    def _on_selection_changed(self):
        """Handle table row selection change."""
        selected_items = self.status_table.selectedItems()
        if selected_items:
            # Get worker_id from icon column, then lookup in _workers dict
            row = self.status_table.currentRow()
            icon_col_idx = self._get_column_index('icon')
            if icon_col_idx >= 0:
                # Check cellWidget first (icon is now a QPushButton in a container)
                worker_id = None
                widget = self.status_table.cellWidget(row, icon_col_idx)
                if widget:
                    worker_id = widget.property("worker_id")
                else:
                    # Fallback to item (legacy or if widget not found)
                    icon_item = self.status_table.item(row, icon_col_idx)
                    if icon_item:
                        worker_id = icon_item.data(Qt.ItemDataRole.UserRole)

                if worker_id:
                    self._selected_worker_id = worker_id
                    # Thread-safe lookup
                    with QMutexLocker(self._workers_mutex):
                        if worker_id in self._workers:
                            worker = self._workers[worker_id]
                            self.worker_selected.emit(worker_id, worker.worker_type)
        else:
            self._selected_worker_id = None

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        """Handle events from cell widgets, particularly double-clicks.

        When the hostname column uses setCellWidget() with a container holding
        the logo and auto icon, those widgets intercept mouse events before the
        table receives them. This event filter catches double-clicks on those
        containers and opens the appropriate config dialog.

        Args:
            obj: The object that received the event (cell widget container)
            event: The event to filter

        Returns:
            True if the event was handled, False to pass it on
        """
        if event.type() == QEvent.Type.MouseButtonDblClick:
            # Check if this is a cell widget container with worker data
            worker_id = obj.property('worker_id')
            if worker_id:
                worker_type = obj.property('worker_type')
                hostname = obj.property('hostname')

                # Open the appropriate dialog
                if worker_type == 'imx':
                    self.open_settings_tab_requested.emit(1)  # Credentials tab
                elif hostname:
                    self.open_host_config_requested.emit(hostname.lower())
                return True  # Event handled

        return super().eventFilter(obj, event)

    def _on_row_double_clicked(self, item):  # 'item' passed by itemDoubleClicked signal
        """Handle double-click on table row to open host config.

        ALWAYS opens a config dialog - no conditional guards that could fail silently.
        Handles both active workers (in _workers dict) and placeholder workers.
        """
        row = self.status_table.currentRow()
        if row < 0:
            return

        # Get worker_id from icon column - check cellWidget first (icon is now a QPushButton)
        worker_id = None
        icon_col_idx = self._get_column_index('icon')
        if icon_col_idx >= 0:
            widget = self.status_table.cellWidget(row, icon_col_idx)
            if widget:
                worker_id = widget.property("worker_id")
            else:
                # Fallback to item (legacy or if widget not found)
                icon_item = self.status_table.item(row, icon_col_idx)
                if icon_item:
                    worker_id = icon_item.data(Qt.ItemDataRole.UserRole)

        if not worker_id:
            log(f"Double-click: no worker_id found for row {row}", level="warning", category="ui")
            return

        # Handle placeholder workers (not in _workers dict)
        # Placeholder IDs: "placeholder_imx", "placeholder_{host_id}"
        if worker_id.startswith("placeholder_"):
            host_part = worker_id[len("placeholder_"):]
            if host_part == "imx":
                self.open_settings_tab_requested.emit(1)  # Credentials tab
            else:
                self.open_host_config_requested.emit(host_part.lower())
            return

        # Thread-safe lookup for active workers in _workers dict
        with QMutexLocker(self._workers_mutex):
            if worker_id not in self._workers:
                log(f"Double-click: worker_id={worker_id} not in active workers (row {row})", level="warning", category="ui")
                return
            worker = self._workers[worker_id]

        # Open the appropriate dialog based on worker type
        if worker.worker_type == 'imx':
            self.open_settings_tab_requested.emit(1)  # Credentials tab
        else:
            self.open_host_config_requested.emit(worker.hostname.lower())

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

        # Metrics columns section - GROUP BY METRIC TYPE
        metrics_menu = menu.addMenu("Metrics Columns")

        # Group by metric type instead of period
        bytes_menu = metrics_menu.addMenu("Bytes Uploaded")
        files_menu = metrics_menu.addMenu("Files Uploaded")
        avg_speed_menu = metrics_menu.addMenu("Average Speed")
        peak_speed_menu = metrics_menu.addMenu("Peak Speed")
        success_menu = metrics_menu.addMenu("Success Rate")

        # Map metric_key to menu
        metric_to_menu = {
            'bytes_uploaded': bytes_menu,
            'files_uploaded': files_menu,
            'avg_speed': avg_speed_menu,
            'peak_speed': peak_speed_menu,
            'success_rate': success_menu,
        }

        for col in METRIC_COLUMNS:
            if col.metric_key in metric_to_menu:
                target_menu = metric_to_menu[col.metric_key]
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

        # Preserve current column widths before rebuild
        self._preserved_widths = {}
        for i, col in enumerate(self._active_columns):
            self._preserved_widths[col.id] = self.status_table.columnWidth(i)

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
        # Clear font cache when columns change
        self._column_font_cache.clear()

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
                # Determine width: use preserved width if available, otherwise use default
                if hasattr(self, '_preserved_widths') and self._preserved_widths and col.id in self._preserved_widths:
                    width = self._preserved_widths[col.id]
                elif col.id == 'hostname':
                    # Hostname column has special 180px default
                    width = 180
                else:
                    # Use default from ColumnConfig
                    width = col.width

                # Set resize mode and width
                if col.id == 'hostname':
                    header.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
                    self.status_table.setColumnWidth(i, width)
                elif col.resizable:
                    header.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
                    self.status_table.setColumnWidth(i, width)
                else:
                    header.setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
                    self.status_table.setColumnWidth(i, width)
        finally:
            # Always unblock signals
            header.blockSignals(False)

        # Refresh display with new columns
        self._refresh_display()

        # Clear preserved widths after use
        self._preserved_widths = {}

    def _on_column_resized(self, logical_index: int, old_size: int, new_size: int):
        """Handle column resize - save settings and schedule text re-fitting."""
        # Only process if columns are fully initialized (not during startup)
        if self._active_columns:
            self._save_column_settings()

            # Schedule debounced text re-fitting for this column
            self._pending_resize_columns.add(logical_index)
            self._resize_refit_timer.start()  # Restart timer (debounce)

    def _refit_resized_columns(self):
        """Re-fit text in columns that were resized (debounced)."""
        if not self._pending_resize_columns or not self._active_columns:
            return

        columns_to_refit = self._pending_resize_columns.copy()
        self._pending_resize_columns.clear()

        # Get column configs for metric columns only
        for col_idx in columns_to_refit:
            if col_idx >= len(self._active_columns):
                continue

            col_config = self._active_columns[col_idx]

            # Only re-fit metric columns (they have shrink-to-fit)
            if col_config.col_type not in (ColumnType.BYTES, ColumnType.SPEED, ColumnType.COUNT, ColumnType.PERCENT):
                continue

            self._refit_column_text(col_idx, col_config)

    def _refit_column_text(self, col_idx: int, col_config: 'ColumnConfig') -> None:
        """Re-fit text in a single column after resize.

        Args:
            col_idx: Column index in the table
            col_config: Column configuration object
        """
        col_width = self.status_table.columnWidth(col_idx)
        available_width = max(0, col_width - METRIC_CELL_PADDING)

        if available_width <= 0:
            return

        # Get cached base font or create new one
        cache_entry = self._column_font_cache.get(col_config.id)
        if cache_entry:
            base_font, base_fm = cache_entry
        else:
            # Fallback: create font if not cached
            is_small_metric = col_config.id in SMALL_METRIC_COLUMN_IDS
            base_font_size = METRIC_FONT_SIZE_SMALL if is_small_metric else METRIC_FONT_SIZE_DEFAULT
            base_font = QFont("Consolas")
            base_font.setPointSizeF(base_font_size)
            base_font.setStyleHint(QFont.StyleHint.Monospace)
            base_font.setStretch(QFont.Stretch.SemiCondensed)
            base_fm = QFontMetrics(base_font)

        # Block signals during batch update
        self.status_table.blockSignals(True)
        try:
            for row in range(self.status_table.rowCount()):
                item = self.status_table.item(row, col_idx)
                if not item:
                    continue

                text = item.text()
                if not text:
                    continue

                # Measure with base font
                text_width = base_fm.horizontalAdvance(text)

                if text_width > available_width:
                    # Scale font DOWN to fit - clone base font and adjust
                    scaled_font = QFont(base_font)
                    scale = available_width / text_width
                    new_size = max(METRIC_MIN_FONT_SIZE, base_font.pointSizeF() * scale)
                    scaled_font.setPointSizeF(new_size)
                    item.setFont(scaled_font)
                else:
                    # Text fits - use base font but cap at max size
                    capped_size = min(base_font.pointSizeF(), METRIC_MAX_FONT_SIZE)
                    capped_font = QFont(base_font)
                    capped_font.setPointSizeF(capped_size)
                    item.setFont(capped_font)
        finally:
            self.status_table.blockSignals(False)

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
                header = self.status_table.horizontalHeader()

                # Toggle sort order if clicking same column, otherwise ascending
                if self._sort_column == logical_index:
                    # Toggle current order
                    new_order = Qt.SortOrder.DescendingOrder if self._sort_order == Qt.SortOrder.AscendingOrder else Qt.SortOrder.AscendingOrder
                else:
                    # New column - start with ascending
                    new_order = Qt.SortOrder.AscendingOrder

                # Store sort state
                self._sort_column = logical_index
                self._sort_order = new_order

                # Update sort indicator
                header.setSortIndicator(logical_index, new_order)

                # Trigger refresh with new sort
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

        # Column settings saved (debug logging removed to prevent spam)

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

        # Save filter selection
        if self.filter_combo:
            settings.setValue("worker_status/filter_index", self.filter_combo.currentIndex())

    def _load_column_settings(self):
        """Load column settings from QSettings."""
        settings = QSettings("ImxUploader", "ImxUploadGUI")

        # Load visible column IDs in saved order
        visible_ids = settings.value("worker_status/visible_columns", None, type=list)

        # Debug logging
        import traceback
        caller = traceback.extract_stack()[-2]
        log(f"Loading column settings from QSettings (called from {caller.filename}:{caller.lineno} in {caller.name})", level="debug", category="ui")
        log(f"Found saved columns: {', '.join(visible_ids) if visible_ids else 'none'}", level="debug", category="ui")

        # Migrate old settings: if "status" column exists but "status_text" doesn't, add it
        if visible_ids and 'status' in visible_ids and 'status_text' not in visible_ids:
            status_idx = visible_ids.index('status')
            visible_ids.insert(status_idx + 1, 'status_text')
            log("Migrated column settings: added status_text after status", level="debug", category="ui")

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

        # RESTORE SORT STATE BEFORE rebuilding table
        # This ensures _refresh_display() (called by _rebuild_table_columns) uses correct sort
        sort_column_id = settings.value("worker_status/sort_column", None, type=str)
        sort_order_val = settings.value("worker_status/sort_order", 0, type=int)
        if sort_column_id:
            # Find the column index by ID
            sort_col_idx = next((i for i, col in enumerate(self._active_columns) if col.id == sort_column_id), -1)
            if sort_col_idx >= 0:
                self._sort_column = sort_col_idx
                self._sort_order = Qt.SortOrder(sort_order_val)

        # NOW rebuild table - _refresh_display() will use the restored sort state
        self._rebuild_table_columns()

        # Apply saved widths after rebuild (but only for resizable columns)
        # Non-resizable columns (icon, settings) should always use ColumnConfig.width
        if widths:
            for i, col in enumerate(self._active_columns):
                if col.id in widths and col.resizable:
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

        # Update header sort indicator (visual only - sort state already restored above)
        if self._sort_column is not None:
            header = self.status_table.horizontalHeader()
            header.setSortIndicator(self._sort_column, self._sort_order)

        # Restore filter selection
        if self.filter_combo:
            filter_index = settings.value("worker_status/filter_index", 0, type=int)
            # Validate index is within range
            if 0 <= filter_index < self.filter_combo.count():
                self.filter_combo.setCurrentIndex(filter_index)

    def _apply_disabled_style(self, element: Any) -> None:
        """Apply disabled/grayed-out styling to widget or table item.

        Args:
            element: Either a QWidget (QLabel) or QTableWidgetItem to style as disabled
        """
        from PyQt6.QtWidgets import QWidget, QTableWidgetItem, QLabel
        from PyQt6.QtGui import QColor

        if isinstance(element, QLabel):
            # QLabel widget path - use stylesheet and italic font
            element.setStyleSheet(f"color: {self.palette().color(QPalette.ColorRole.PlaceholderText).name()};")
            font = element.font()
            font.setItalic(True)
            element.setFont(font)
        elif isinstance(element, QTableWidgetItem):
            # QTableWidgetItem path - use foreground color and italic font
            element.setForeground(self.palette().color(QPalette.ColorRole.PlaceholderText))
            font = element.font()
            font.setItalic(True)
            element.setFont(font)

    def _reset_column_settings(self):
        """Reset columns to default settings."""
        settings = QSettings("ImxUploader", "ImxUploadGUI")
        settings.remove("worker_status/visible_columns")
        settings.remove("worker_status/column_widths")

        # Reset to default columns
        self._active_columns = [col for col in CORE_COLUMNS if col.default_visible]

        # Rebuild table with defaults
        self._rebuild_table_columns()
