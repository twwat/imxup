"""
Background task management for ImxUp application.
Handles async operations, progress batching, and table updates.
"""

import time
import weakref
import configparser
import os
from typing import Callable, Optional, Dict, Any, Set
from PyQt6.QtCore import QObject, QRunnable, pyqtSignal, QTimer, QMutex, QMutexLocker, Qt
from PyQt6.QtWidgets import QTableWidgetItem

from imxup_constants import (
    PROGRESS_UPDATE_BATCH_INTERVAL, TABLE_UPDATE_INTERVAL,
    QUEUE_STATE_UPLOADING
)


class BackgroundTaskSignals(QObject):
    """Signals for background tasks"""
    finished = pyqtSignal(object)  # result
    error = pyqtSignal(str)  # error message


class BackgroundTask(QRunnable):
    """Generic background task runner"""
    
    def __init__(self, func: Callable, *args, **kwargs):
        super().__init__()
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.signals = BackgroundTaskSignals()
    
    def run(self):
        """Execute the background task"""
        try:
            result = self.func(*self.args, **self.kwargs)
            self.signals.finished.emit(result)
        except Exception as e:
            self.signals.error.emit(str(e))


class ProgressUpdateBatcher:
    """Batches and throttles progress updates to prevent GUI blocking"""
    
    def __init__(self, update_callback: Callable, batch_interval: float = PROGRESS_UPDATE_BATCH_INTERVAL):
        self._callback = update_callback
        self._batch_interval = batch_interval
        self._pending_updates = {}
        self._last_batch_time = 0
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._process_batch)
    
    def add_update(self, path: str, completed: int, total: int, progress_percent: int, current_image: str):
        """Add a progress update to the batch"""
        self._pending_updates[path] = {
            'completed': completed,
            'total': total,
            'progress_percent': progress_percent,
            'current_image': current_image,
            'timestamp': time.time()
        }
        
        # Schedule batch processing if not already scheduled
        current_time = time.time()
        if not self._timer.isActive():
            if current_time - self._last_batch_time >= self._batch_interval:
                self._process_batch()
            else:
                remaining_time = int((self._batch_interval - (current_time - self._last_batch_time)) * 1000)
                self._timer.start(max(remaining_time, 10))
    
    def _process_batch(self):
        """Process all pending updates"""
        if not self._pending_updates:
            return
        
        updates_to_process = self._pending_updates.copy()
        self._pending_updates.clear()
        self._last_batch_time = time.time()
        
        # Process updates on main thread
        for path, update_data in updates_to_process.items():
            self._callback(
                path,
                update_data['completed'],
                update_data['total'],
                update_data['progress_percent'],
                update_data['current_image']
            )


class IconCache:
    """Thread-safe icon cache to prevent blocking icon loads"""
    
    def __init__(self):
        self._cache = {}
        self._mutex = QMutex()
    
    def get_icon_data(self, status: str, load_func: Callable) -> Any:
        """Get cached icon data or load if not cached"""
        with QMutexLocker(self._mutex):
            if status not in self._cache:
                try:
                    result = load_func()
                    self._cache[status] = result
                except Exception:
                    self._cache[status] = None
            return self._cache[status]
    
    def clear(self):
        """Clear the cache"""
        with QMutexLocker(self._mutex):
            self._cache.clear()


class TableRowUpdateTask:
    """Represents a table row update task"""
    
    def __init__(self, row: int, item: Any, update_type: str = 'full'):
        self.row = row
        self.item = item
        self.update_type = update_type
        self.timestamp = time.time()


class TableUpdateQueue:
    """Manages table update operations in a non-blocking way"""
    
    def __init__(self, table_widget, path_to_row_map: Dict[str, int]):
        # Handle both GalleryTableWidget and TabbedGalleryWidget
        if hasattr(table_widget, 'gallery_table'):
            self._table = weakref.ref(table_widget.gallery_table)
            self._tabbed_widget = weakref.ref(table_widget)
        else:
            self._table = weakref.ref(table_widget)
            self._tabbed_widget = None
        
        self._path_to_row = path_to_row_map
        self._pending_updates = {}
        self._processing = False
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._process_updates)
        
        # Performance optimizations
        self._visibility_cache = {}
        self._cache_invalidation_counter = 0
        self._visible_rows_cache: Set[int] = set()
        self._last_cache_update = 0
    
    def queue_update(self, path: str, item: Any, update_type: str = 'progress'):
        """Queue a table update"""
        if path not in self._path_to_row:
            return
        
        row = self._path_to_row[path]
        
        # Skip hidden rows for performance
        if self._tabbed_widget and self._is_row_likely_hidden(row):
            return
        
        self._pending_updates[path] = TableRowUpdateTask(row, item, update_type)
        
        if not self._processing and not self._timer.isActive():
            self._timer.start(TABLE_UPDATE_INTERVAL)
    
    def _is_row_likely_hidden(self, row: int) -> bool:
        """Check if row is likely hidden using cache"""
        current_time = time.time()
        
        # Update cache periodically
        if (current_time - self._last_cache_update > 0.1 or
            self._cache_invalidation_counter > 50):
            self._update_visibility_cache()
        
        return row not in self._visible_rows_cache
    
    def _update_visibility_cache(self):
        """Update visibility cache efficiently"""
        table = self._table()
        if not table:
            return
        
        start_time = time.time()
        self._visible_rows_cache.clear()
        
        # Time-budgeted visibility check
        TIME_BUDGET = 0.008  # 8ms
        row_count = min(table.rowCount(), 2000)
        
        for row in range(row_count):
            if time.time() - start_time > TIME_BUDGET:
                break
            if not table.isRowHidden(row):
                self._visible_rows_cache.add(row)
        
        self._last_cache_update = time.time()
        self._cache_invalidation_counter = 0
    
    def invalidate_visibility_cache(self):
        """Force cache invalidation"""
        self._cache_invalidation_counter = 1000
        self._visible_rows_cache.clear()
    
    def _process_updates(self):
        """Process pending table updates"""
        table = self._table()
        if not table or not self._pending_updates:
            return
        
        self._processing = True
        start_time = time.time()
        
        # Process with time budget
        TIME_BUDGET = 0.012  # 12ms for 60fps
        
        for path, task in list(self._pending_updates.items()):
            if time.time() - start_time > TIME_BUDGET:
                break
            
            # Skip hidden rows
            if self._tabbed_widget and task.row < table.rowCount():
                if table.isRowHidden(task.row):
                    del self._pending_updates[path]
                    continue
            
            if task.update_type == 'progress':
                self._update_progress_only(table, task)
            else:
                self._update_full_row(table, task)
            
            del self._pending_updates[path]
        
        self._processing = False
        
        # Schedule next batch if needed
        if self._pending_updates:
            self._timer.start(TABLE_UPDATE_INTERVAL)
    
    def _update_progress_only(self, table, task):
        """Update only progress-related cells"""
        if task.row >= table.rowCount():
            return
        
        try:
            # Update count column
            uploaded_text = f"{task.item.uploaded_images}/{task.item.total_images}"
            count_item = table.item(task.row, 2)
            if count_item:
                count_item.setText(uploaded_text)
            else:
                new_item = QTableWidgetItem(uploaded_text)
                new_item.setFlags(new_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                new_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(task.row, 2, new_item)
            
            # Update progress widget
            progress_widget = table.cellWidget(task.row, 3)
            if progress_widget:
                if hasattr(progress_widget, 'update_progress'):
                    progress_widget.update_progress(task.item.progress, task.item.status)
            
            # Update transfer speed for uploading items
            if task.item.status == QUEUE_STATE_UPLOADING:
                self._update_transfer_speed(table, task.row, task.item)
                
        except Exception:
            pass
    
    def _update_full_row(self, table, task):
        """Update full row with all details"""
        if task.row >= table.rowCount():
            return
        
        try:
            # Find main GUI for detailed update
            main_gui = None
            parent = table.parent()
            while parent:
                if hasattr(parent, '_populate_table_row'):
                    main_gui = parent
                    break
                parent = parent.parent()
            
            if main_gui:
                main_gui._populate_table_row(task.row, task.item)
                
        except Exception:
            pass
    
    def _update_transfer_speed(self, table, row: int, item: Any):
        """Update transfer speed display"""
        try:
            xfer_item = table.item(row, 9)
            transfer_text = ""
            
            if hasattr(item, 'current_kibps') and item.current_kibps:
                transfer_text = self._format_rate(item.current_kibps)
            elif hasattr(item, 'final_kibps') and item.final_kibps:
                transfer_text = self._format_rate(item.final_kibps)
            
            if xfer_item:
                xfer_item.setText(transfer_text)
            else:
                new_item = QTableWidgetItem(transfer_text)
                new_item.setFlags(new_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                new_item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
                table.setItem(row, 9, new_item)
                
        except Exception:
            pass
    
    def _format_rate(self, kibps: float) -> str:
        """Format transfer rate"""
        try:
            if kibps >= 1024:
                return f"{kibps/1024:.1f} MiB/s"
            return f"{kibps:.1f} KiB/s"
        except:
            return ""


def check_stored_credentials() -> bool:
    """Check if credentials are stored in configuration"""
    try:
        from imxup import get_config_path
        config = configparser.ConfigParser()
        config_file = get_config_path()
        
        if os.path.exists(config_file):
            config.read(config_file)
            if 'CREDENTIALS' in config:
                auth_type = config.get('CREDENTIALS', 'auth_type', fallback='username_password')
                
                if auth_type == 'username_password':
                    username = config.get('CREDENTIALS', 'username', fallback='')
                    password = config.get('CREDENTIALS', 'password', fallback='')
                    return bool(username and password)
                    
                elif auth_type == 'api_key':
                    api_key = config.get('CREDENTIALS', 'api_key', fallback='')
                    return bool(api_key)
                    
    except Exception:
        pass
    
    return False


def api_key_is_set() -> bool:
    """Check if API key is configured"""
    try:
        from imxup import get_config_path
        config = configparser.ConfigParser()
        config_file = get_config_path()
        
        if os.path.exists(config_file):
            config.read(config_file)
            if 'CREDENTIALS' in config:
                api_key = config.get('CREDENTIALS', 'api_key', fallback='')
                return bool(api_key)
                
    except Exception:
        pass
    
    return False