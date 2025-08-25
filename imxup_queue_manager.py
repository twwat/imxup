"""
Queue Manager for ImxUp application.
Manages the gallery upload queue with persistence and state tracking.
"""

import os
import time
import threading
import queue
from queue import Queue
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from contextlib import contextmanager

from PyQt6.QtCore import QObject, pyqtSignal, QMutex, QMutexLocker, QSettings, QTimer

from imxup_storage import QueueStore
from imxup import sanitize_gallery_name, load_user_defaults
from imxup_constants import (
    QUEUE_STATE_READY, QUEUE_STATE_QUEUED, QUEUE_STATE_UPLOADING,
    QUEUE_STATE_COMPLETED, QUEUE_STATE_FAILED, QUEUE_STATE_PAUSED,
    QUEUE_STATE_INCOMPLETE, IMAGE_EXTENSIONS
)


@dataclass
class GalleryQueueItem:
    """Represents a gallery in the upload queue"""
    path: str
    name: Optional[str] = None
    status: str = QUEUE_STATE_READY
    progress: int = 0
    total_images: int = 0
    uploaded_images: int = 0
    current_image: str = ""
    gallery_url: str = ""
    gallery_id: str = ""
    error_message: str = ""
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    insertion_order: int = 0
    added_time: Optional[float] = None
    finished_time: Optional[float] = None
    template_name: str = "default"
    
    # Pre-scan metadata
    total_size: int = 0
    avg_width: float = 0.0
    avg_height: float = 0.0
    max_width: float = 0.0
    max_height: float = 0.0
    min_width: float = 0.0
    min_height: float = 0.0
    scan_complete: bool = False
    
    # Failed validation details
    failed_files: list = field(default_factory=list)
    
    # Resume support
    uploaded_files: set = field(default_factory=set)
    uploaded_images_data: list = field(default_factory=list)
    uploaded_bytes: int = 0
    
    # Runtime transfer metrics
    current_kibps: float = 0.0
    final_kibps: float = 0.0
    
    # Tab organization
    tab_name: str = "Main"


class QueueManager(QObject):
    """Manages the gallery upload queue with persistence"""
    
    # Signals
    status_changed = pyqtSignal(str, str, str)  # path, old_status, new_status
    queue_loaded = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        self.items: Dict[str, GalleryQueueItem] = {}
        self.queue = Queue()
        self.mutex = QMutex()
        self.settings = QSettings("ImxUploader", "QueueManager")
        self.store = QueueStore()
        self._next_order = 0
        self._version = 0
        
        # Batch mode for deferred database saves
        self._batch_mode = False
        self._batched_changes = set()
        
        # Status counters for efficient updates
        self._status_counts = {
            QUEUE_STATE_READY: 0,
            QUEUE_STATE_PAUSED: 0,
            QUEUE_STATE_INCOMPLETE: 0,
            "scanning": 0,
            QUEUE_STATE_UPLOADING: 0,
            QUEUE_STATE_QUEUED: 0,
            QUEUE_STATE_COMPLETED: 0,
            QUEUE_STATE_FAILED: 0,
            "validating": 0
        }
        
        # Sequential scan worker
        self._scan_worker = None
        self._scan_queue = Queue()
        self._scan_worker_running = False
        
        # Migration and initialization
        try:
            self.store.migrate_from_qsettings_if_needed(self.settings)
        except Exception:
            pass
        self.load_persistent_queue()
        self._start_scan_worker()
    
    def _start_scan_worker(self):
        """Start the sequential scan worker thread"""
        print(f"DEBUG: _start_scan_worker called, running={self._scan_worker_running}")
        if not self._scan_worker_running:
            print(f"DEBUG: Starting scan worker thread")
            self._scan_worker_running = True
            self._scan_worker = threading.Thread(
                target=self._sequential_scan_worker,
                daemon=True
            )
            self._scan_worker.start()
            print(f"DEBUG: Scan worker thread started")
    
    def _sequential_scan_worker(self):
        """Worker that processes galleries sequentially"""
        print(f"DEBUG: Scan worker starting")
        while self._scan_worker_running:
            try:
                print(f"DEBUG: Scan worker waiting for item...")
                path = self._scan_queue.get(timeout=1.0)
                print(f"DEBUG: Scan worker got path: {path}")
                if path is None:  # Shutdown signal
                    break
                
                print(f"DEBUG: About to scan path: {path}")
                self._comprehensive_scan_item(path)
                print(f"DEBUG: Scan completed for {path}")
                self._scan_queue.task_done()
                print(f"DEBUG: task_done() called for {path}")
                
            except queue.Empty:
                continue
            except Exception as e:
                print(f"Scan worker error: {e}")
                try:
                    self._scan_queue.task_done()
                except:
                    pass
    
    def _comprehensive_scan_item(self, path: str):
        """Scan and validate a gallery item"""
        try:
            # Validation
            if not os.path.exists(path) or not os.path.isdir(path):
                self._mark_item_failed(path, "Path does not exist or is not a directory")
                return
            
            # Find images
            files = self._get_image_files(path)
            if not files:
                self._mark_item_failed(path, "No images found")
                return
            
            # Check for existing gallery
            with QMutexLocker(self.mutex):
                if path not in self.items:
                    return
                item = self.items[path]
                
                # Check if gallery already exists
                from imxup import check_if_gallery_exists
                existing = check_if_gallery_exists(item.name)
                if existing:
                    item.status = QUEUE_STATE_FAILED
                    item.error_message = f"Gallery '{item.name}' already exists"
                    item.scan_complete = True
                    return
                
                item.total_images = len(files)
                print(f"DEBUG: Set total_images={len(files)} for {path}")
                item.status = "scanning"
                print(f"DEBUG: Changed status to scanning for {path}")
            
            # Scan images
            scan_result = self._scan_images(path, files)
            
            if scan_result['failed_files']:
                self._mark_item_failed(
                    path,
                    f"Validation failed: {len(scan_result['failed_files'])}/{len(files)} images invalid",
                    scan_result['failed_files']
                )
                return
            
            # Update item with scan results
            with QMutexLocker(self.mutex):
                if path in self.items:
                    item = self.items[path]
                    item.total_size = scan_result['total_size']
                    item.avg_width = scan_result['avg_width']
                    item.avg_height = scan_result['avg_height']
                    item.max_width = scan_result['max_width']
                    item.max_height = scan_result['max_height']
                    item.min_width = scan_result['min_width']
                    item.min_height = scan_result['min_height']
                    item.scan_complete = True
                    
                    if item.status == "scanning":
                        print(f"DEBUG: Scan complete, updating status to ready for {path}")
                        old_status = item.status
                        item.status = QUEUE_STATE_READY
                        print(f"DEBUG: Status changed from {old_status} to {QUEUE_STATE_READY}")
                        # Emit signal directly (we're already in mutex lock)
                        print(f"DEBUG: EMITTING status_changed signal for {path}")
                        self.status_changed.emit(path, old_status, QUEUE_STATE_READY)
                        print(f"DEBUG: status_changed signal emitted")
            
            # Defer database save to avoid blocking
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(50, lambda: self.save_persistent_queue([path]))
            self._inc_version()
            
        except Exception as e:
            self._mark_item_failed(path, f"Scan error: {e}")
    
    def _get_image_files(self, path: str) -> List[str]:
        """Get list of image files in directory"""
        files = []
        for f in os.listdir(path):
            if f.lower().endswith(IMAGE_EXTENSIONS):
                fp = os.path.join(path, f)
                if os.path.isfile(fp):
                    files.append(f)
        return files
    
    def _scan_images(self, path: str, files: List[str]) -> dict:
        """Scan images for validation and metadata"""
        result = {
            'total_size': 0,
            'failed_files': [],
            'avg_width': 0.0,
            'avg_height': 0.0,
            'max_width': 0.0,
            'max_height': 0.0,
            'min_width': 0.0,
            'min_height': 0.0
        }
        
        # Get scan configuration
        config = self._get_scanning_config()
        use_fast = config.get('fast_scan', True)
        sampling = config.get('pil_sampling', 2)
        
        # Scan files
        if use_fast:
            import imghdr
            for i, f in enumerate(files):
                fp = os.path.join(path, f)
                try:
                    result['total_size'] += os.path.getsize(fp)
                    with open(fp, 'rb') as img:
                        if not imghdr.what(img):
                            result['failed_files'].append((f, "Invalid image"))
                except Exception as e:
                    result['failed_files'].append((f, str(e)))
                
                if i % 10 == 0:
                    time.sleep(0.001)  # Yield
        
        # Calculate dimensions with sampling
        if not result['failed_files']:
            dims = self._calculate_dimensions(path, files, sampling)
            if dims:
                result['avg_width'] = sum(w for w, _ in dims) / len(dims)
                result['avg_height'] = sum(h for _, h in dims) / len(dims)
                result['max_width'] = max(w for w, _ in dims)
                result['max_height'] = max(h for _, h in dims)
                result['min_width'] = min(w for w, _ in dims)
                result['min_height'] = min(h for _, h in dims)
        
        return result
    
    def _calculate_dimensions(self, path: str, files: List[str], sampling: int) -> List[tuple]:
        """Calculate image dimensions with sampling"""
        dims = []
        
        try:
            from PIL import Image
            
            # Determine sample files based on strategy
            if sampling == 0:  # 1 image
                samples = [files[0]]
            elif sampling == 1:  # 2 images
                samples = [files[0], files[-1]]
            elif sampling == 2:  # 4 images
                if len(files) <= 4:
                    samples = files
                else:
                    indices = [0, len(files)//3, 2*len(files)//3, -1]
                    samples = [files[i] for i in indices]
            elif sampling == 3:  # 8 images
                step = max(1, len(files) // 8)
                samples = files[::step][:8]
            elif sampling == 4:  # 16 images
                step = max(1, len(files) // 16)
                samples = files[::step][:16]
            else:  # All images
                samples = files
            
            # Process samples
            for f in samples:
                fp = os.path.join(path, f)
                try:
                    with Image.open(fp) as img:
                        dims.append(img.size)
                except:
                    continue
                    
        except ImportError:
            pass
        
        return dims
    
    def _mark_item_failed(self, path: str, error: str, failed_files: list = None):
        """Mark an item as failed"""
        with QMutexLocker(self.mutex):
            if path in self.items:
                item = self.items[path]
                item.status = QUEUE_STATE_FAILED
                item.error_message = error
                item.scan_complete = True
                if failed_files:
                    item.failed_files = failed_files
        
        QTimer.singleShot(100, lambda: self.save_persistent_queue([path]))
        self._inc_version()
    
    def _get_scanning_config(self) -> dict:
        """Get scanning configuration"""
        try:
            settings = QSettings("ImxUploader", "ImxUploadGUI")
            return {
                'fast_scan': settings.value('scanning/fast_scan', True, type=bool),
                'pil_sampling': settings.value('scanning/pil_sampling', 2, type=int)
            }
        except:
            return {'fast_scan': True, 'pil_sampling': 2}
    
    def _inc_version(self):
        """Increment version for change tracking"""
        self._version += 1
    
    def get_version(self) -> int:
        """Get current version"""
        with QMutexLocker(self.mutex):
            return self._version
    
    @contextmanager
    def batch_updates(self):
        """Context manager for batching updates"""
        old_batch = self._batch_mode
        self._batch_mode = True
        self._batched_changes.clear()
        try:
            yield
        finally:
            if self._batched_changes:
                self.save_persistent_queue(list(self._batched_changes))
            self._batch_mode = old_batch
            self._batched_changes.clear()
    
    def save_persistent_queue(self, specific_paths: List[str] = None):
        """Save queue state to database"""
        print(f"DEBUG: save_persistent_queue called with {len(specific_paths) if specific_paths else 'all'} items")
        if self._batch_mode and specific_paths:
            print(f"DEBUG: In batch mode, adding to batched changes")
            self._batched_changes.update(specific_paths)
            return
        
        print(f"DEBUG: Acquiring mutex for database save")
        with QMutexLocker(self.mutex):
            print(f"DEBUG: Mutex acquired, preparing items list")
            if specific_paths:
                items = [self.items[p] for p in specific_paths if p in self.items]
                print(f"DEBUG: Found {len(items)} items for specific paths")
            else:
                items = list(self.items.values())
                print(f"DEBUG: Saving all {len(items)} items")
            
            queue_data = []
            print(f"DEBUG: Building queue data for {len(items)} items")
            for item in items:
                if item.status in [QUEUE_STATE_READY, QUEUE_STATE_QUEUED, QUEUE_STATE_PAUSED,
                                  QUEUE_STATE_COMPLETED, QUEUE_STATE_INCOMPLETE, QUEUE_STATE_FAILED]:
                    queue_data.append(self._item_to_dict(item))
            print(f"DEBUG: Built queue data with {len(queue_data)} items to save")
            
            try:
                print(f"DEBUG: About to call store.bulk_upsert_async")
                self.store.bulk_upsert_async(queue_data)
                print(f"DEBUG: bulk_upsert_async completed")
            except Exception as e:
                print(f"DEBUG: Database save failed: {e}")
                pass
    
    def _item_to_dict(self, item: GalleryQueueItem) -> dict:
        """Convert item to dictionary for storage"""
        return {
            'path': item.path,
            'name': item.name,
            'status': item.status,
            'gallery_url': item.gallery_url,
            'gallery_id': item.gallery_id,
            'progress': item.progress,
            'uploaded_images': item.uploaded_images,
            'total_images': item.total_images,
            'template_name': item.template_name,
            'insertion_order': item.insertion_order,
            'added_time': item.added_time,
            'finished_time': item.finished_time,
            'tab_name': item.tab_name,
            'total_size': item.total_size,
            'avg_width': item.avg_width,
            'avg_height': item.avg_height,
            'max_width': item.max_width,
            'max_height': item.max_height,
            'min_width': item.min_width,
            'min_height': item.min_height,
            'scan_complete': item.scan_complete,
            'uploaded_bytes': item.uploaded_bytes,
            'final_kibps': item.final_kibps,
            'failed_files': item.failed_files,
            'error_message': item.error_message
        }
    
    def load_persistent_queue(self):
        """Load queue from database"""
        try:
            queue_data = self.store.load_all_items()
        except:
            queue_data = []
        
        for data in queue_data:
            path = data.get('path', '')
            status = data.get('status', QUEUE_STATE_READY)
            
            # Skip invalid paths unless completed
            if status != QUEUE_STATE_COMPLETED:
                if not os.path.exists(path) or not os.path.isdir(path):
                    continue
            
            # Create item from data
            item = self._dict_to_item(data)
            self._next_order = max(self._next_order, item.insertion_order + 1)
            self.items[path] = item
        
        self._rebuild_status_counts()
        self.queue_loaded.emit()
    
    def _dict_to_item(self, data: dict) -> GalleryQueueItem:
        """Create item from dictionary"""
        status = data.get('status', QUEUE_STATE_READY)
        if status in [QUEUE_STATE_QUEUED, QUEUE_STATE_UPLOADING]:
            status = QUEUE_STATE_READY
        
        # Ensure completed items have 100% progress
        progress = data.get('progress', 0)
        if status == 'completed':
            progress = 100
        
        item = GalleryQueueItem(
            path=data.get('path', ''),
            name=data.get('name'),
            status=status,
            gallery_url=data.get('gallery_url', ''),
            gallery_id=data.get('gallery_id', ''),
            progress=progress,
            uploaded_images=data.get('uploaded_images', 0),
            total_images=data.get('total_images', 0),
            template_name=data.get('template_name', 'default'),
            insertion_order=data.get('insertion_order', self._next_order),
            added_time=data.get('added_time'),
            finished_time=data.get('finished_time'),
            tab_name=data.get('tab_name', 'Main')
        )
        
        # Restore optional fields
        for field in ['total_size', 'avg_width', 'avg_height', 'max_width',
                     'max_height', 'min_width', 'min_height', 'scan_complete',
                     'uploaded_bytes', 'final_kibps', 'error_message']:
            if field in data:
                setattr(item, field, data[field])
        
        if 'uploaded_files' in data:
            item.uploaded_files = set(data['uploaded_files'])
        if 'uploaded_images_data' in data:
            item.uploaded_images_data = data['uploaded_images_data']
        if 'failed_files' in data:
            item.failed_files = data['failed_files']
        
        return item
    
    def add_item(self, path: str, name: str = None, template_name: str = "default") -> bool:
        """Add gallery to queue"""
        print(f"DEBUG: QueueManager.add_item called with path={path}")
        with QMutexLocker(self.mutex):
            if path in self.items:
                return False
            
            print(f"DEBUG: Sanitizing gallery name for {path}")
            gallery_name = name or sanitize_gallery_name(os.path.basename(path))
            print(f"DEBUG: Gallery name: {gallery_name}")
            print(f"DEBUG: Creating GalleryQueueItem...")
            item = GalleryQueueItem(
                path=path,
                name=gallery_name,
                status="validating",
                insertion_order=self._next_order,
                added_time=time.time(),
                template_name=template_name
            )
            print(f"DEBUG: GalleryQueueItem created successfully")
            self._next_order += 1
            
            self.items[path] = item
            print(f"DEBUG: Item added to dict, updating status count...")
            self._update_status_count("", "validating")
            print(f"DEBUG: Scheduling deferred database save...")
            # Use QTimer to defer database save to prevent blocking GUI thread
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(100, lambda: self.save_persistent_queue([path]))
            print(f"DEBUG: Incrementing version...")
            self._inc_version()
            print(f"DEBUG: Version incremented")
        
        print(f"DEBUG: Adding to scan queue: {path}")
        self._scan_queue.put(path)
        print(f"DEBUG: add_item returning True")
        return True
    
    def start_item(self, path: str) -> bool:
        """Queue an item for upload"""
        with QMutexLocker(self.mutex):
            if path not in self.items:
                return False
            
            item = self.items[path]
            if item.status not in [QUEUE_STATE_READY, QUEUE_STATE_PAUSED, QUEUE_STATE_INCOMPLETE]:
                return False
            
            old_status = item.status
            item.status = QUEUE_STATE_QUEUED
            self._update_status_count(old_status, QUEUE_STATE_QUEUED)
            self.queue.put(item)
            QTimer.singleShot(100, lambda: self.save_persistent_queue([path]))
            self._inc_version()
            return True
    
    def get_next_item(self) -> Optional[GalleryQueueItem]:
        """Get next queued item"""
        try:
            item = self.queue.get_nowait()
            if item.path in self.items:
                if self.items[item.path].status in [QUEUE_STATE_QUEUED, QUEUE_STATE_UPLOADING]:
                    return item
            return self.get_next_item()  # Try next
        except queue.Empty:
            return None
    
    def update_item_status(self, path: str, status: str):
        """Update item status"""
        with QMutexLocker(self.mutex):
            if path in self.items:
                old_status = self.items[path].status
                self.items[path].status = status
                
                # When marking as completed, ensure progress is 100%
                if status == "completed":
                    self.items[path].progress = 100
                    
                self._update_status_count(old_status, status)
                QTimer.singleShot(100, lambda: self.save_persistent_queue([path]))
                self._inc_version()
                
                if old_status != status:
                    self.status_changed.emit(path, old_status, status)
    
    def remove_item(self, path: str) -> bool:
        """Remove item from queue"""
        with QMutexLocker(self.mutex):
            if path not in self.items:
                return False
            
            if self.items[path].status == QUEUE_STATE_UPLOADING:
                return False
            
            old_status = self.items[path].status
            self._update_status_count(old_status, "")
            del self.items[path]
            self._renumber_items()
            self._inc_version()
        
        try:
            self.store._executor.submit(self.store.delete_by_paths, [path])
        except:
            pass
        
        return True
    
    def get_all_items(self) -> List[GalleryQueueItem]:
        """Get all items sorted by order"""
        with QMutexLocker(self.mutex):
            return sorted(self.items.values(), key=lambda x: x.insertion_order)
    
    def get_item(self, path: str) -> Optional[GalleryQueueItem]:
        """Get specific item"""
        with QMutexLocker(self.mutex):
            return self.items.get(path)
    
    def _rebuild_status_counts(self):
        """Rebuild status counters"""
        self._status_counts.clear()
        for item in self.items.values():
            status = item.status
            self._status_counts[status] = self._status_counts.get(status, 0) + 1
    
    def _update_status_count(self, old: str, new: str):
        """Update status counters"""
        if old:
            self._status_counts[old] = max(0, self._status_counts.get(old, 0) - 1)
        if new:
            self._status_counts[new] = self._status_counts.get(new, 0) + 1
    
    def _renumber_items(self):
        """Renumber insertion orders"""
        sorted_items = sorted(self.items.values(), key=lambda x: x.insertion_order)
        for i, item in enumerate(sorted_items, 1):
            item.insertion_order = i
        self._next_order = len(self.items) + 1
    
    def shutdown(self):
        """Shutdown queue manager"""
        self._scan_worker_running = False
        try:
            self._scan_queue.put(None, timeout=1.0)
        except:
            pass
        if self._scan_worker and self._scan_worker.is_alive():
            self._scan_worker.join(timeout=2.0)