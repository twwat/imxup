"""
Graceful shutdown dialogs for IMXuploader.

Provides exit confirmation with active transfer details and
a shutdown progress dialog with force quit option.
"""

from threading import Event
from typing import List, Dict, Optional, TYPE_CHECKING
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QWidget, QFrame, QApplication, QSystemTrayIcon
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, pyqtSlot, QThread, QMetaObject
from PyQt6.QtGui import QFont

from src.storage.queue_manager import GalleryQueueItem
from src.utils.logger import log

if TYPE_CHECKING:
    from src.gui.main_window import ImxUploadGUI


class ExitConfirmationDialog(QDialog):
    """Dialog shown when closing application with active transfers.

    Displays active upload details and provides three options:
    - Exit Anyway: Proceed with shutdown
    - Minimize to Tray: Hide window but keep uploads running
    - Cancel: Stay in application

    Attributes:
        RESULT_CANCEL: Dialog rejected (Cancel clicked or Esc pressed)
        RESULT_EXIT: User confirmed exit
        RESULT_MINIMIZE: User requested minimize to tray
    """

    # Custom result codes
    RESULT_CANCEL = 0
    RESULT_EXIT = 1
    RESULT_MINIMIZE = 2

    def __init__(
        self,
        parent: QWidget,
        uploading_galleries: List[GalleryQueueItem],
        queued_galleries: List[GalleryQueueItem],
        file_host_uploads: Dict[str, int],
    ):
        """Initialize exit confirmation dialog.

        Args:
            parent: Parent widget (main window)
            uploading_galleries: List of galleries currently uploading
            queued_galleries: List of galleries queued for upload
            file_host_uploads: Dict mapping host_id to pending upload count
        """
        super().__init__(parent)
        self.uploading_galleries = uploading_galleries
        self.queued_galleries = queued_galleries
        self.file_host_uploads = file_host_uploads
        self._result = self.RESULT_CANCEL

        self._setup_dialog()
        self._create_ui()
        self._center_on_parent()

    def _setup_dialog(self):
        """Configure dialog window properties."""
        self.setWindowTitle("Exit Confirmation")
        self.setModal(True)
        self.setMinimumSize(450, 300)
        self.setMaximumSize(600, 500)

    def _create_ui(self):
        """Create and arrange UI components."""
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        # Warning header
        header_layout = QHBoxLayout()

        # Warning icon (use system warning icon)
        icon_label = QLabel()
        icon_label.setPixmap(
            self.style().standardIcon(
                self.style().StandardPixmap.SP_MessageBoxWarning
            ).pixmap(32, 32)
        )
        header_layout.addWidget(icon_label)

        header_text = QLabel("Active Uploads in Progress")
        header_font = QFont()
        header_font.setBold(True)
        header_font.setPointSize(12)
        header_text.setFont(header_font)
        header_layout.addWidget(header_text)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        # Details section (scrollable)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setMaximumHeight(200)
        scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        details_widget = QWidget()
        details_layout = QVBoxLayout(details_widget)
        details_layout.setContentsMargins(10, 10, 10, 10)
        details_layout.setSpacing(8)

        # Uploading galleries section
        if self.uploading_galleries:
            uploading_header = QLabel(
                f"Currently Uploading ({len(self.uploading_galleries)}):"
            )
            uploading_header.setStyleSheet("font-weight: bold; color: #e67e22;")
            details_layout.addWidget(uploading_header)

            for gallery in self.uploading_galleries[:5]:  # Show max 5
                name = gallery.name or gallery.path.split('/')[-1].split('\\')[-1]
                gallery_label = QLabel(f"  - {name}")
                gallery_label.setStyleSheet("color: #666; margin-left: 10px;")
                details_layout.addWidget(gallery_label)

            if len(self.uploading_galleries) > 5:
                more_label = QLabel(
                    f"  ... and {len(self.uploading_galleries) - 5} more"
                )
                more_label.setStyleSheet("color: #888; font-style: italic;")
                details_layout.addWidget(more_label)

        # File host uploads section
        if self.file_host_uploads:
            host_header = QLabel("File Host Uploads:")
            host_header.setStyleSheet("font-weight: bold; color: #9b59b6;")
            details_layout.addWidget(host_header)

            for host_id, count in self.file_host_uploads.items():
                host_label = QLabel(f"  - {host_id}: {count} pending")
                host_label.setStyleSheet("color: #666;")
                details_layout.addWidget(host_label)

        # Queued galleries section
        if self.queued_galleries:
            queued_header = QLabel(
                f"Queued for Upload ({len(self.queued_galleries)}):"
            )
            queued_header.setStyleSheet("font-weight: bold; color: #3498db;")
            details_layout.addWidget(queued_header)

            queued_summary = QLabel(
                f"  {len(self.queued_galleries)} galleries waiting to start"
            )
            queued_summary.setStyleSheet("color: #666;")
            details_layout.addWidget(queued_summary)

        details_layout.addStretch()
        scroll_area.setWidget(details_widget)
        layout.addWidget(scroll_area)

        # Warning message
        warning_frame = QFrame()
        warning_frame.setStyleSheet(
            "background-color: #fff3cd; border: 1px solid #ffc107; "
            "border-radius: 4px; padding: 8px;"
        )
        warning_layout = QVBoxLayout(warning_frame)
        warning_layout.setContentsMargins(10, 8, 10, 8)
        warning_label = QLabel(
            "Uploads will automatically resume when you restart the application."
        )
        warning_label.setWordWrap(True)
        warning_label.setStyleSheet("color: #856404;")
        warning_layout.addWidget(warning_label)
        layout.addWidget(warning_frame)

        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(separator)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        # Exit Anyway button (warning color)
        exit_btn = QPushButton("Exit Anyway")
        exit_btn.setStyleSheet(
            "QPushButton { min-width: 100px; background-color: #e74c3c; "
            "color: white; font-weight: bold; padding: 6px 12px; }"
            "QPushButton:hover { background-color: #c0392b; }"
        )
        exit_btn.clicked.connect(self._on_exit_clicked)
        button_layout.addWidget(exit_btn)

        # Minimize to Tray button
        minimize_btn = QPushButton("Minimize to Tray")
        minimize_btn.setStyleSheet(
            "QPushButton { min-width: 120px; padding: 6px 12px; }"
        )
        minimize_btn.clicked.connect(self._on_minimize_clicked)
        button_layout.addWidget(minimize_btn)

        # Cancel button (default)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(
            "QPushButton { min-width: 80px; background-color: #27ae60; "
            "color: white; font-weight: bold; padding: 6px 12px; }"
            "QPushButton:hover { background-color: #229954; }"
        )
        cancel_btn.setDefault(True)
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        layout.addLayout(button_layout)

    def _on_exit_clicked(self):
        """Handle Exit Anyway button click."""
        self._result = self.RESULT_EXIT
        self.accept()

    def _on_minimize_clicked(self):
        """Handle Minimize to Tray button click."""
        self._result = self.RESULT_MINIMIZE
        self.accept()

    def get_result(self) -> int:
        """Get the dialog result code.

        Returns:
            Result code: RESULT_CANCEL, RESULT_EXIT, or RESULT_MINIMIZE
        """
        return self._result

    def _center_on_parent(self):
        """Center dialog on parent window."""
        if self.parent():
            parent_geo = self.parent().geometry()
            self.move(
                parent_geo.x() + (parent_geo.width() - self.width()) // 2,
                parent_geo.y() + (parent_geo.height() - self.height()) // 2
            )


class ShutdownDialog(QDialog):
    """Non-dismissible modal showing shutdown progress.

    Displays current shutdown step with spinner animation.
    Shows Force Quit button after 10 second timeout.

    Signals:
        force_quit_requested: Emitted when Force Quit clicked
    """

    # Shutdown step constants
    STEP_SAVING_SETTINGS = 0
    STEP_STOPPING_TIMERS = 1
    STEP_STOPPING_WORKERS = 2
    STEP_STOPPING_FILE_HOSTS = 3
    STEP_CLOSING_CONNECTIONS = 4

    STEP_DESCRIPTIONS = {
        0: "Saving settings...",
        1: "Stopping timers...",
        2: "Stopping upload workers...",
        3: "Stopping file host workers...",
        4: "Closing connections...",
    }

    force_quit_requested = pyqtSignal()

    def __init__(self, parent: QWidget):
        """Initialize shutdown dialog.

        Args:
            parent: Parent widget (main window)
        """
        super().__init__(parent)
        self._current_step = -1
        self._completed_steps = set()
        self._step_labels: Dict[int, QLabel] = {}

        self._setup_dialog()
        self._create_ui()
        self._center_on_parent()
        self._start_force_quit_timer()

    def _setup_dialog(self):
        """Configure dialog window properties."""
        self.setWindowTitle("Shutting Down...")
        self.setModal(True)
        self.setFixedSize(350, 280)
        # Remove all window buttons
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.CustomizeWindowHint |
            Qt.WindowType.WindowTitleHint
        )

    def _create_ui(self):
        """Create and arrange UI components."""
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(25, 25, 25, 25)

        # Header with spinner
        header_layout = QHBoxLayout()

        # Spinner (animated dots)
        self._spinner_label = QLabel("...")
        self._spinner_label.setFixedWidth(30)
        self._spinner_label.setStyleSheet("font-size: 16pt; font-weight: bold;")
        self._spinner_index = 0

        # Animate spinner with timer
        self._spinner_timer = QTimer()
        self._spinner_timer.timeout.connect(self._animate_spinner)
        self._spinner_timer.start(300)

        header_layout.addWidget(self._spinner_label)

        header_text = QLabel("Shutting Down")
        header_font = QFont()
        header_font.setBold(True)
        header_font.setPointSize(11)
        header_text.setFont(header_font)
        header_layout.addWidget(header_text)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        # Current step label
        self._current_step_label = QLabel("Preparing...")
        self._current_step_label.setStyleSheet(
            "font-size: 10pt; color: #3498db;"
        )
        layout.addWidget(self._current_step_label)

        # Steps list
        steps_frame = QFrame()
        steps_frame.setStyleSheet(
            "background-color: #f8f9fa; border: 1px solid #dee2e6; "
            "border-radius: 4px;"
        )
        steps_layout = QVBoxLayout(steps_frame)
        steps_layout.setContentsMargins(12, 12, 12, 12)
        steps_layout.setSpacing(6)

        for step_id, description in self.STEP_DESCRIPTIONS.items():
            step_label = QLabel(f"○ {description}")
            step_label.setStyleSheet("color: #6c757d;")
            self._step_labels[step_id] = step_label
            steps_layout.addWidget(step_label)

        layout.addWidget(steps_frame)

        layout.addStretch()

        # Force Quit button (hidden initially)
        self._force_quit_btn = QPushButton("Force Quit")
        self._force_quit_btn.setStyleSheet(
            "QPushButton { min-width: 100px; background-color: #dc3545; "
            "color: white; font-weight: bold; padding: 6px 12px; }"
            "QPushButton:hover { background-color: #c82333; }"
        )
        self._force_quit_btn.clicked.connect(self._on_force_quit)
        self._force_quit_btn.hide()
        layout.addWidget(self._force_quit_btn, alignment=Qt.AlignmentFlag.AlignCenter)

    def _animate_spinner(self):
        """Animate spinner text."""
        dots = [".", "..", "...", ""]
        self._spinner_index = (self._spinner_index + 1) % len(dots)
        self._spinner_label.setText(dots[self._spinner_index])

    def _start_force_quit_timer(self):
        """Start 10 second timer for Force Quit button."""
        self._force_quit_timer = QTimer()
        self._force_quit_timer.setSingleShot(True)
        self._force_quit_timer.timeout.connect(self._enable_force_quit)
        self._force_quit_timer.start(10000)  # 10 seconds

    def _enable_force_quit(self):
        """Show Force Quit button after timeout."""
        self._force_quit_btn.show()

    def _on_force_quit(self):
        """Handle Force Quit button click."""
        self.force_quit_requested.emit()
        self.accept()

    @pyqtSlot(int, str)
    def set_step(self, step_id: int, description: str = None):
        """Update current step display.

        Args:
            step_id: Step identifier
            description: Optional custom description
        """
        self._current_step = step_id
        desc = description or self.STEP_DESCRIPTIONS.get(step_id, "Processing...")
        self._current_step_label.setText(desc)

        # Update step label to show in-progress
        if step_id in self._step_labels:
            self._step_labels[step_id].setText(f"● {desc}")
            self._step_labels[step_id].setStyleSheet(
                "color: #007bff; font-weight: bold;"
            )

    @pyqtSlot(int)
    def mark_step_complete(self, step_id: int):
        """Mark a step as completed.

        Args:
            step_id: Step identifier
        """
        self._completed_steps.add(step_id)

        if step_id in self._step_labels:
            desc = self.STEP_DESCRIPTIONS.get(step_id, "Done")
            self._step_labels[step_id].setText(f"✓ {desc}")
            self._step_labels[step_id].setStyleSheet(
                "color: #28a745;"
            )

    def closeEvent(self, event):
        """Prevent dialog from being closed."""
        event.ignore()

    def keyPressEvent(self, event):
        """Prevent Escape key from closing dialog."""
        if event.key() == Qt.Key.Key_Escape:
            event.ignore()
        else:
            super().keyPressEvent(event)

    def cleanup(self):
        """Stop timers and cleanup resources."""
        if hasattr(self, '_spinner_timer'):
            self._spinner_timer.stop()
        if hasattr(self, '_force_quit_timer'):
            self._force_quit_timer.stop()

    def _center_on_parent(self):
        """Center dialog on parent window."""
        if self.parent():
            parent_geo = self.parent().geometry()
            self.move(
                parent_geo.x() + (parent_geo.width() - self.width()) // 2,
                parent_geo.y() + (parent_geo.height() - self.height()) // 2
            )


class ShutdownWorker(QThread):
    """Worker thread that performs shutdown operations.

    Runs cleanup steps in background thread to keep UI responsive.
    Emits signals to update ShutdownDialog progress.

    Signals:
        step_started: Emitted when starting a step (step_id, description)
        step_completed: Emitted when step completes (step_id)
        shutdown_complete: Emitted when all steps done
        shutdown_error: Emitted on error (error_message)
    """

    step_started = pyqtSignal(int, str)
    step_completed = pyqtSignal(int)
    shutdown_complete = pyqtSignal()
    shutdown_error = pyqtSignal(str)

    def __init__(self, main_window: 'ImxUploadGUI'):
        """Initialize shutdown worker.

        Args:
            main_window: Reference to main window for accessing components
        """
        super().__init__()
        self.mw = main_window
        self._force_stop_event = Event()

    def force_stop(self):
        """Request immediate shutdown without waiting (thread-safe)."""
        log("ShutdownWorker: Force stop requested", level="warning", category="shutdown")
        self._force_stop_event.set()

    def run(self):
        """Execute shutdown sequence."""
        try:
            # Step 0: Save settings
            self._execute_step(
                ShutdownDialog.STEP_SAVING_SETTINGS,
                self._save_settings
            )
            if self._force_stop_event.is_set():
                self.shutdown_complete.emit()
                return

            # Step 1: Stop timers
            self._execute_step(
                ShutdownDialog.STEP_STOPPING_TIMERS,
                self._stop_timers
            )
            if self._force_stop_event.is_set():
                self.shutdown_complete.emit()
                return

            # Step 2: Stop upload workers
            self._execute_step(
                ShutdownDialog.STEP_STOPPING_WORKERS,
                self._stop_workers
            )
            if self._force_stop_event.is_set():
                self.shutdown_complete.emit()
                return

            # Step 3: Stop file host workers
            self._execute_step(
                ShutdownDialog.STEP_STOPPING_FILE_HOSTS,
                self._stop_file_host_workers
            )
            if self._force_stop_event.is_set():
                self.shutdown_complete.emit()
                return

            # Step 4: Close connections
            self._execute_step(
                ShutdownDialog.STEP_CLOSING_CONNECTIONS,
                self._close_connections
            )

            self.shutdown_complete.emit()
            log("ShutdownWorker: Shutdown sequence completed", level="info", category="shutdown")

        except Exception as e:
            log(f"ShutdownWorker: Error during shutdown: {e}", level="error", category="shutdown")
            self.shutdown_error.emit(str(e))
            self.shutdown_complete.emit()

    def _execute_step(self, step_id: int, step_func):
        """Execute a shutdown step with error handling.

        Args:
            step_id: Step identifier for signals
            step_func: Function to execute
        """
        description = ShutdownDialog.STEP_DESCRIPTIONS.get(step_id, "Processing...")
        self.step_started.emit(step_id, description)

        try:
            step_func()
        except Exception as e:
            log(f"ShutdownWorker: Step {step_id} error: {e}", level="error", category="shutdown")
            # Continue with other steps despite errors

        self.step_completed.emit(step_id)

    def _save_settings(self):
        """Save application settings and queue state."""
        log("ShutdownWorker: Saving settings...", level="debug", category="shutdown")

        # Save main window settings (must be done via main thread)
        QMetaObject.invokeMethod(
            self.mw, "save_settings",
            Qt.ConnectionType.BlockingQueuedConnection
        )

        # Shutdown queue manager
        if hasattr(self.mw, 'queue_manager'):
            self.mw.queue_manager.shutdown()

    def _stop_timers(self):
        """Stop all timers and batchers."""
        log("ShutdownWorker: Stopping timers...", level="debug", category="shutdown")

        # These need to run on main thread
        QMetaObject.invokeMethod(
            self.mw, "_stop_all_timers",
            Qt.ConnectionType.BlockingQueuedConnection
        )

    def _stop_workers(self):
        """Stop upload and completion workers."""
        log("ShutdownWorker: Stopping workers...", level="debug", category="shutdown")

        # Stop main upload worker
        if hasattr(self.mw, 'worker') and self.mw.worker:
            self.mw.worker.stop()
            if not self._force_stop_event.is_set():
                self.mw.worker.wait(3000)  # 3 second timeout

        # Stop completion worker
        if hasattr(self.mw, 'completion_worker'):
            self.mw.completion_worker.stop()
            if not self._force_stop_event.is_set():
                self.mw.completion_worker.wait(3000)

        # Stop worker status monitoring
        if hasattr(self.mw, 'worker_status_widget'):
            self.mw.worker_status_widget.stop_monitoring()

    def _stop_file_host_workers(self):
        """Stop all file host workers."""
        log("ShutdownWorker: Stopping file host workers...", level="debug", category="shutdown")

        if hasattr(self.mw, 'file_host_manager') and self.mw.file_host_manager:
            self.mw.file_host_manager.shutdown_all()

    def _close_connections(self):
        """Close remaining connections and cleanup."""
        log("ShutdownWorker: Closing connections...", level="debug", category="shutdown")

        # Stop update checker
        if hasattr(self.mw, '_update_checker') and self.mw._update_checker:
            if self.mw._update_checker.isRunning():
                self.mw._update_checker.quit()
                if not self._force_stop_event.is_set():
                    self.mw._update_checker.wait(1000)

        # Stop socket server
        if hasattr(self.mw, 'server'):
            self.mw.server.stop()
