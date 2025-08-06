#!/usr/bin/env python3
"""
PyQt6 GUI for imx.to gallery uploader
Provides drag-and-drop interface with queue management and progress tracking
"""

import sys
import os
import json
import socket
import threading
import time
from pathlib import Path
from datetime import datetime
from queue import Queue, Empty
from dataclasses import dataclass
from typing import List, Optional, Dict, Any

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QListWidget, QListWidgetItem, QPushButton, QProgressBar, QLabel, 
    QGroupBox, QSplitter, QTextEdit, QComboBox, QSpinBox, QCheckBox,
    QMessageBox, QSystemTrayIcon, QMenu, QFrame, QScrollArea,
    QGridLayout, QSizePolicy, QTabWidget, QFileDialog, QTableWidget,
    QTableWidgetItem, QHeaderView, QDialog, QDialogButtonBox, QPlainTextEdit
)
from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QTimer, QMimeData, QUrl, 
    QMutex, QMutexLocker, QSettings, QSize
)
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QIcon, QFont, QPixmap, QPainter, QColor

# Import the core uploader functionality
from imxup import ImxToUploader, load_user_defaults, timestamp, sanitize_gallery_name

# Single instance communication port
COMMUNICATION_PORT = 27849

@dataclass
class GalleryQueueItem:
    """Represents a gallery in the upload queue"""
    path: str
    name: Optional[str] = None
    status: str = "ready"  # ready, queued, uploading, completed, failed, paused
    progress: int = 0
    total_images: int = 0
    uploaded_images: int = 0
    current_image: str = ""
    gallery_url: str = ""
    gallery_id: str = ""
    error_message: str = ""
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    insertion_order: int = 0  # For maintaining insertion order
    added_time: Optional[float] = None  # When item was added to queue
    finished_time: Optional[float] = None  # When item was completed
    
class GUIImxToUploader(ImxToUploader):
    """Custom uploader for GUI that doesn't block on user input"""
    
    def __init__(self, worker_thread=None):
        super().__init__()
        self.gui_mode = True
        self.worker_thread = worker_thread
    
    def upload_folder(self, folder_path, gallery_name=None, thumbnail_size=3, thumbnail_format=2, max_retries=3, public_gallery=1):
        """
        Upload folder without interactive prompts
        """
        start_time = time.time()
        
        if not os.path.exists(folder_path):
            raise FileNotFoundError(f"Folder not found: {folder_path}")
        
        # Get all image files in folder and calculate total size
        image_extensions = ('.jpg', '.jpeg', '.png', '.gif')
        image_files = []
        total_size = 0
        image_dimensions = []
        
        for f in os.listdir(folder_path):
            if f.lower().endswith(image_extensions) and os.path.isfile(os.path.join(folder_path, f)):
                image_files.append(f)
                file_path = os.path.join(folder_path, f)
                file_size = os.path.getsize(file_path)
                total_size += file_size
                
                # Get image dimensions using PIL
                try:
                    from PIL import Image
                    with Image.open(file_path) as img:
                        width, height = img.size
                        image_dimensions.append((width, height))
                except ImportError:
                    image_dimensions.append((0, 0))  # PIL not available
                except Exception:
                    image_dimensions.append((0, 0))  # Error reading image
        
        if not image_files:
            raise ValueError(f"No image files found in {folder_path}")
        
        # Signal gallery start with image count
        if self.worker_thread:
            self.worker_thread.gallery_started.emit(folder_path, len(image_files))
            self.worker_thread.log_message.emit(f"{timestamp()} Starting gallery '{os.path.basename(folder_path)}' with {len(image_files)} images")
        
        # Create gallery with name (default to folder name if not provided)
        if not gallery_name:
            gallery_name = os.path.basename(folder_path)
        
        # Sanitize gallery name
        from imxup import sanitize_gallery_name
        original_name = gallery_name
        gallery_name = sanitize_gallery_name(gallery_name)
        if original_name != gallery_name:
            if self.worker_thread:
                self.worker_thread.log_message.emit(f"{timestamp()} Sanitized gallery name: '{original_name}' -> '{gallery_name}'")
        
        # Check if gallery already exists - for GUI, skip interactive prompt
        from imxup import check_if_gallery_exists
        existing_files = check_if_gallery_exists(gallery_name)
        if existing_files:
            if self.worker_thread:
                self.worker_thread.log_message.emit(f"{timestamp()} Found existing gallery files for '{gallery_name}', continuing anyway...")
        
        # Create gallery (skip login since it's already done)
        gallery_id = self.create_gallery_with_name(gallery_name, public_gallery, skip_login=True)
        
        if not gallery_id:
            print("Failed to create named gallery, falling back to API-only upload...")
            # Fallback to API-only upload (no gallery naming)
            return self._upload_without_named_gallery(folder_path, image_files, thumbnail_size, thumbnail_format, max_retries)
        
        gallery_url = f"https://imx.to/g/{gallery_id}"
        
        # Store results
        results = {
            'gallery_url': gallery_url,
            'images': []
        }
        
        # Upload all images to the created gallery with progress bars
        def upload_single_image(image_file, attempt=1, pbar=None):
            image_path = os.path.join(folder_path, image_file)
            
            try:
                response = self.upload_image(
                    image_path, 
                    gallery_id=gallery_id,
                    thumbnail_size=thumbnail_size,
                    thumbnail_format=thumbnail_format
                )
                
                if response.get('status') == 'success':
                    return image_file, response['data'], None
                else:
                    error_msg = f"API error: {response}"
                    return image_file, None, error_msg
                    
            except Exception as e:
                error_msg = f"Network error: {str(e)}"
                return image_file, None, error_msg
        
        # Upload images with retries, maintaining order
        uploaded_images = []
        failed_images = []
        
        # Upload images sequentially for progress tracking
        for i, image_file in enumerate(image_files):
            if self.worker_thread:
                self.worker_thread.log_message.emit(f"{timestamp()} [{i+1}/{len(image_files)}] Uploading: {image_file}")
            
            image_file_result, image_data, error = upload_single_image(image_file)
            
            if image_data:
                uploaded_images.append((image_file_result, image_data))
                if self.worker_thread:
                    self.worker_thread.log_message.emit(f"{timestamp()} ✓ Uploaded: {image_file}")
            else:
                failed_images.append((image_file_result, error))
                if self.worker_thread:
                    self.worker_thread.log_message.emit(f"{timestamp()} ✗ Failed: {image_file} - {error}")
            
            # Update progress after each image
            completed_count = len(uploaded_images)
            progress_percent = int((completed_count / len(image_files)) * 100)
            
            if self.worker_thread:
                self.worker_thread.progress_updated.emit(
                    folder_path, completed_count, len(image_files), progress_percent, image_file
                )
                self.worker_thread.log_message.emit(f"{timestamp()} Progress: {completed_count}/{len(image_files)} ({progress_percent}%)")
        
        # Retry failed uploads
        retry_count = 0
        while failed_images and retry_count < max_retries:
            retry_count += 1
            retry_failed = []
            
            for image_file, _ in failed_images:
                image_file_result, image_data, error = upload_single_image(image_file, retry_count + 1)
                if image_data:
                    uploaded_images.append((image_file_result, image_data))
                else:
                    retry_failed.append((image_file_result, error))
            
            failed_images = retry_failed
        
        # Sort uploaded images by original file order
        uploaded_images.sort(key=lambda x: image_files.index(x[0]))
        
        # Add to results in correct order
        for _, image_data in uploaded_images:
            results['images'].append(image_data)
        
        # Calculate statistics
        end_time = time.time()
        upload_time = end_time - start_time
        
        # Calculate transfer speed
        uploaded_size = sum(os.path.getsize(os.path.join(folder_path, img_file)) 
                           for img_file, _ in uploaded_images)
        transfer_speed = uploaded_size / upload_time if upload_time > 0 else 0
        
        # Calculate image dimension statistics
        successful_dimensions = [image_dimensions[image_files.index(img_file)] 
                               for img_file, _ in uploaded_images]
        avg_width = sum(w for w, h in successful_dimensions) / len(successful_dimensions) if successful_dimensions else 0
        avg_height = sum(h for w, h in successful_dimensions) / len(successful_dimensions) if successful_dimensions else 0
        
        # Add statistics to results
        results.update({
            'gallery_id': gallery_id,
            'gallery_name': gallery_name,
            'upload_time': upload_time,
            'total_size': total_size,
            'uploaded_size': uploaded_size,
            'transfer_speed': transfer_speed,
            'avg_width': avg_width,
            'avg_height': avg_height,
            'successful_count': len(uploaded_images),
            'failed_count': len(failed_images)
        })
        
        # Create gallery folder and files
        gallery_folder = os.path.join(folder_path, f"gallery_{gallery_id}")
        os.makedirs(gallery_folder, exist_ok=True)
        
        # Create shortcut file (.url) to the gallery
        shortcut_content = f"""[InternetShortcut]
URL=https://imx.to/g/{gallery_id}
"""
        shortcut_path = os.path.join(gallery_folder, f"gallery_{gallery_id}.url")
        with open(shortcut_path, 'w', encoding='utf-8') as f:
            f.write(shortcut_content)
        
        # Files will be created in on_gallery_completed when gallery_id is available
        print(f"{timestamp()} Gallery upload completed successfully")
        
        return results

class UploadWorker(QThread):
    """Worker thread for uploading galleries"""
    
    # Signals
    progress_updated = pyqtSignal(str, int, int, int, str)  # path, completed, total, progress%, current_image
    gallery_started = pyqtSignal(str, int)  # path, total_images
    gallery_completed = pyqtSignal(str, dict)  # path, results
    gallery_failed = pyqtSignal(str, str)  # path, error_message
    log_message = pyqtSignal(str)
    
    def __init__(self, queue_manager):
        super().__init__()
        self.queue_manager = queue_manager
        self.uploader = None
        self.running = True
        self.current_item = None
        
    def stop(self):
        self.running = False
        self.wait()
        
    def run(self):
        """Main worker thread loop"""
        try:
            # Initialize custom GUI uploader with reference to this worker
            self.uploader = GUIImxToUploader(worker_thread=self)
            self.log_message.emit(f"{timestamp()} Worker thread started")
            
            # Login once for session reuse
            self.log_message.emit(f"{timestamp()} Logging in...")
            login_success = self.uploader.login()
            if not login_success:
                self.log_message.emit(f"{timestamp()} Login failed - using API-only mode")
            else:
                self.log_message.emit(f"{timestamp()} Login successful")
            
            while self.running:
                # Get next item from queue
                item = self.queue_manager.get_next_item()
                if item is None:
                    time.sleep(0.1)
                    continue
                
                # Only process items that are queued to upload
                if item.status == "queued":
                    self.current_item = item
                    self.upload_gallery(item)
                elif item.status == "paused":
                    # Skip paused items
                    time.sleep(0.1)
                else:
                    # Put item back in queue if not ready
                    time.sleep(0.1)
                
        except Exception as e:
            self.log_message.emit(f"{timestamp()} Worker error: {str(e)}")
    
    def upload_gallery(self, item: GalleryQueueItem):
        """Upload a single gallery"""
        try:
            self.log_message.emit(f"{timestamp()} Starting upload: {item.name or os.path.basename(item.path)}")
            
            # Set status to uploading and update display
            self.queue_manager.update_item_status(item.path, "uploading")
            item.status = "uploading"
            item.start_time = time.time()
            
            # Emit signal to update display immediately
            self.gallery_started.emit(item.path, item.total_images or 0)
            
            # Get default settings
            defaults = load_user_defaults()
            
            # Upload with progress tracking
            results = self.uploader.upload_folder(
                item.path,
                gallery_name=item.name,
                thumbnail_size=defaults.get('thumbnail_size', 3),
                thumbnail_format=defaults.get('thumbnail_format', 2),
                max_retries=defaults.get('max_retries', 3),
                public_gallery=defaults.get('public_gallery', 1)
            )
            
            # Check if item was paused during upload
            if item.status == "paused":
                self.log_message.emit(f"{timestamp()} Upload paused: {item.name}")
                return
            
            if results:
                item.end_time = time.time()
                item.gallery_url = results.get('gallery_url', '')
                item.gallery_id = results.get('gallery_id', '')
                self.queue_manager.update_item_status(item.path, "completed")
                self.gallery_completed.emit(item.path, results)
                self.log_message.emit(f"{timestamp()} Completed: {item.name} -> {item.gallery_url}")
            else:
                self.queue_manager.update_item_status(item.path, "failed")
                self.gallery_failed.emit(item.path, "Upload failed")
                
        except Exception as e:
            error_msg = str(e)
            self.log_message.emit(f"{timestamp()} Error uploading {item.name}: {error_msg}")
            item.error_message = error_msg
            self.queue_manager.update_item_status(item.path, "failed")
            self.gallery_failed.emit(item.path, error_msg)
    


class QueueManager:
    """Manages the gallery upload queue"""
    
    def __init__(self):
        self.items: Dict[str, GalleryQueueItem] = {}
        self.queue = Queue()
        self.mutex = QMutex()
        self.settings = QSettings("ImxUploader", "QueueManager")
        self._next_order = 0  # Track insertion order
        self.load_persistent_queue()
    
    def save_persistent_queue(self):
        """Save queue state to persistent storage"""
        queue_data = []
        for item in self.items.values():
            if item.status in ["ready", "queued", "paused", "completed"]:  # Save all persistent items
                queue_data.append({
                    'path': item.path,
                    'name': item.name,
                    'status': item.status,
                    'gallery_url': item.gallery_url,
                    'gallery_id': item.gallery_id,
                    'progress': item.progress,
                    'uploaded_images': item.uploaded_images,
                    'total_images': item.total_images,
                    'insertion_order': item.insertion_order,
                    'added_time': item.added_time,
                    'finished_time': item.finished_time
                })
        
        self.settings.setValue("queue_items", queue_data)
    
    def load_persistent_queue(self):
        """Load queue state from persistent storage"""
        queue_data = self.settings.value("queue_items", [])
        if queue_data:
            for item_data in queue_data:
                path = item_data.get('path', '')
                status = item_data.get('status', 'ready')
                
                # For completed items, don't check if path exists (might be moved/deleted)
                if status == "completed" or (os.path.exists(path) and os.path.isdir(path)):
                    if status == "completed":
                        # Restore completed item with saved data
                        item = GalleryQueueItem(
                            path=path,
                            name=item_data.get('name'),
                            status=status,
                            gallery_url=item_data.get('gallery_url', ''),
                            gallery_id=item_data.get('gallery_id', ''),
                            progress=item_data.get('progress', 100),
                            uploaded_images=item_data.get('uploaded_images', 0),
                            total_images=item_data.get('total_images', 0),
                            insertion_order=item_data.get('insertion_order', self._next_order),
                            added_time=item_data.get('added_time'),
                            finished_time=item_data.get('finished_time')
                        )
                        self._next_order = max(self._next_order, item.insertion_order + 1)
                        self.items[path] = item
                    else:
                        # Check for images and count them for non-completed items
                        image_extensions = ('.jpg', '.jpeg', '.png', '.gif')
                        image_files = []
                        for f in os.listdir(path):
                            if f.lower().endswith(image_extensions) and os.path.isfile(os.path.join(path, f)):
                                image_files.append(f)
                        
                        if image_files:
                            item = GalleryQueueItem(
                                path=path,
                                name=item_data.get('name'),
                                status=status,
                                total_images=len(image_files),  # Set the total count
                                insertion_order=item_data.get('insertion_order', self._next_order),
                                added_time=item_data.get('added_time')
                            )
                            self._next_order = max(self._next_order, item.insertion_order + 1)
                            self.items[path] = item
                            if item.status == "queued":
                                self.queue.put(item)
        
    def add_item(self, path: str, name: Optional[str] = None) -> bool:
        """Add a gallery to the queue"""
        with QMutexLocker(self.mutex):
            if path in self.items:
                return False  # Already exists
                
            # Validate path
            if not os.path.exists(path) or not os.path.isdir(path):
                return False
                
            # Check for images and count them
            image_extensions = ('.jpg', '.jpeg', '.png', '.gif')
            image_files = []
            for f in os.listdir(path):
                if f.lower().endswith(image_extensions) and os.path.isfile(os.path.join(path, f)):
                    image_files.append(f)
            
            if not image_files:
                return False
                
            item = GalleryQueueItem(
                path=path,
                name=name or sanitize_gallery_name(os.path.basename(path)),
                status="ready",  # Items start as ready
                total_images=len(image_files),  # Set the total count immediately
                insertion_order=self._next_order,
                added_time=time.time()  # Current timestamp
            )
            self._next_order += 1
            
            self.items[path] = item
            # Don't add to queue automatically - wait for manual start
            self.save_persistent_queue()
            return True
    
    def start_item(self, path: str) -> bool:
        """Start a specific item in the queue"""
        with QMutexLocker(self.mutex):
            if path in self.items and self.items[path].status in ["ready", "paused"]:
                self.items[path].status = "queued"
                self.queue.put(self.items[path])
                self.save_persistent_queue()
                return True
            return False
    
    def pause_item(self, path: str) -> bool:
        """Pause a specific item"""
        with QMutexLocker(self.mutex):
            if path in self.items and self.items[path].status == "uploading":
                self.items[path].status = "paused"
                self.save_persistent_queue()
                return True
            return False
    
    def remove_item(self, path: str) -> bool:
        """Remove a gallery from the queue"""
        with QMutexLocker(self.mutex):
            if path in self.items and self.items[path].status == "queued":
                del self.items[path]
                self.renumber_insertion_orders()
                return True
            return False
    
    def get_next_item(self) -> Optional[GalleryQueueItem]:
        """Get the next queued item"""
        try:
            item = self.queue.get_nowait()
            # Check if item is still in the right status
            if item.path in self.items and self.items[item.path].status in ["queued", "uploading"]:
                return item
            else:
                # Item status changed, try to get next item
                return self.get_next_item()
        except Empty:
            return None
    
    def update_item_status(self, path: str, status: str):
        """Update item status"""
        with QMutexLocker(self.mutex):
            if path in self.items:
                self.items[path].status = status
    
    def get_all_items(self) -> List[GalleryQueueItem]:
        """Get all items, sorted by insertion order"""
        with QMutexLocker(self.mutex):
            return sorted(self.items.values(), key=lambda x: x.insertion_order)
    
    def get_item(self, path: str) -> Optional[GalleryQueueItem]:
        """Get a specific item by path"""
        with QMutexLocker(self.mutex):
            return self.items.get(path)
    
    def renumber_insertion_orders(self):
        """Renumber insertion orders to be sequential (1, 2, 3, ...)"""
        with QMutexLocker(self.mutex):
            # Sort items by current insertion order to maintain relative order
            sorted_items = sorted(self.items.values(), key=lambda x: x.insertion_order)
            
            # Renumber starting from 1
            for i, item in enumerate(sorted_items, 1):
                item.insertion_order = i
            
            # Update the next order counter
            self._next_order = len(self.items) + 1
    
    def clear_completed(self):
        """Remove completed items"""
        with QMutexLocker(self.mutex):
            to_remove = [
                path for path, item in self.items.items() 
                if item.status in ["completed", "failed"]
            ]
            for path in to_remove:
                del self.items[path]
            
            # Renumber remaining items
            if to_remove:
                self.renumber_insertion_orders()
            
            return len(to_remove)
    
    def remove_items(self, paths: List[str]) -> int:
        """Remove specific items from the queue"""
        with QMutexLocker(self.mutex):
            removed_count = 0
            for path in paths:
                if path in self.items:
                    del self.items[path]
                    removed_count += 1
            
            # Renumber remaining items
            if removed_count > 0:
                self.renumber_insertion_orders()
            
            return removed_count

class GalleryTableWidget(QTableWidget):
    """Table widget for gallery queue with resizable columns, sorting, and action buttons"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Setup table
        self.setColumnCount(8)
        self.setHorizontalHeaderLabels(["#", "Gallery Name", "Uploaded", "Progress", "Status", "Added", "Finished", "Actions"])
        
        # Configure columns
        header = self.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)         # Order - fixed
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)       # Gallery Name - stretch to fill space
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)   # Uploaded - resizable
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)   # Progress - resizable
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)   # Status - resizable
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Interactive)   # Added - resizable
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Interactive)   # Finished - resizable
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.Fixed)         # Actions - fixed
        
        # Set initial column widths
        self.setColumnWidth(0, 40)   # Order (narrow)
        self.setColumnWidth(1, 300)  # Gallery Name (wider)
        self.setColumnWidth(2, 100)  # Uploaded (wider)
        self.setColumnWidth(3, 220)  # Progress (wider)
        self.setColumnWidth(4, 120)  # Status (wider)
        self.setColumnWidth(5, 140)  # Added (wider for YYYY-MM-DD format)
        self.setColumnWidth(6, 140)  # Finished (wider for YYYY-MM-DD format)
        self.setColumnWidth(7, 80)   # Actions
        
        # Enable sorting but start with no sorting (insertion order)
        self.setSortingEnabled(True)
        self.horizontalHeader().setSortIndicatorShown(False)  # No initial sort indicator
        
        # Styling - consolidated single stylesheet
        self.setStyleSheet("""
            QTableWidget {
                gridline-color: rgba(128, 128, 128, 0.1);
                alternate-background-color: rgba(240, 240, 240, 0.3);
                border: 1px solid #ccc;
                border-radius: 5px;
                background-color: white;
            }
            QTableWidget::item {
                padding: 0px 4px;
                border: none;
            }
            QTableWidget::item:selected {
                background-color: #2980b9;
                color: white;
            }
            QHeaderView::section {
                background-color: #f0f0f0;
                padding: 8px;
                border: none;
                font-weight: bold;
                border-bottom: 2px solid #3498db;
            }
            QHeaderView::section:hover {
                background-color: #e0e0e0;
            }
        """)
        self.setShowGrid(True)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(32)  # Compact rows
        
        # Enable multi-selection
        self.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
    
    def keyPressEvent(self, event):
        """Handle key press events"""
        if event.key() == Qt.Key.Key_Delete:
            # Find the main GUI window by walking up the parent chain
            widget = self
            while widget:
                if hasattr(widget, 'delete_selected_items'):
                    widget.delete_selected_items()
                    return
                widget = widget.parent()
        elif event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
            # Handle Enter key for completed items
            self.handle_enter_or_double_click()
        elif event.modifiers() == Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_C:
            # Handle Ctrl+C for copying BBCode
            self.handle_copy_bbcode()
            return  # Don't call super() to prevent default table copy behavior
        
        super().keyPressEvent(event)
    
    def mouseDoubleClickEvent(self, event):
        """Handle double-click events"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.handle_enter_or_double_click()
        super().mouseDoubleClickEvent(event)
    
    def handle_enter_or_double_click(self):
        """Handle Enter key or double-click for viewing completed items"""
        current_row = self.currentRow()
        if current_row >= 0:
            name_item = self.item(current_row, 1)  # Gallery name is now column 1
            if name_item:
                path = name_item.data(Qt.ItemDataRole.UserRole)
                if path:
                    # Find the main GUI window and check if item is completed
                    widget = self
                    while widget:
                        if hasattr(widget, 'view_bbcode_files'):
                            widget.view_bbcode_files(path)
                            return
                        widget = widget.parent()
    
    def handle_copy_bbcode(self):
        """Handle Ctrl+C for copying BBCode to clipboard"""
        current_row = self.currentRow()
        if current_row >= 0:
            name_item = self.item(current_row, 1)  # Gallery name is now column 1
            if name_item:
                path = name_item.data(Qt.ItemDataRole.UserRole)
                if path:
                    # Find the main GUI window and copy BBCode
                    widget = self
                    while widget:
                        if hasattr(widget, 'copy_bbcode_to_clipboard'):
                            widget.copy_bbcode_to_clipboard(path)
                            return
                        widget = widget.parent()

class ActionButtonWidget(QWidget):
    """Action buttons widget for table cells"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        
        
        self.start_btn = QPushButton("Start")
        self.start_btn.setFixedSize(50, 25)
        
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #27ae60;
                color: white;
                border: 1px solid #219150;
                border-radius: 3px;
                font-size: 10px;
                font-weight: bold;
                padding: 0 8px;
            }
            QPushButton:hover {
                background-color: #219150;
                border: 1px solid #1e874a;
            }
            QPushButton:pressed {
                background-color: #229954;
            }
        """)
        
        self.pause_btn = QPushButton("Pause")
        
        self.pause_btn.setFixedSize(50, 25)
        self.pause_btn.setVisible(False)
        self.pause_btn.setStyleSheet("""
            QPushButton {
                background-color: #f39c12;
                color: black;
                border: 1px solid #c27c0e;
                border-radius: 3px;
                font-size: 9px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #da8c10;
            }
            QPushButton:pressed {
                background-color: #c27c0e;
                border: 1px solid #915d0a;
            }
        """)
        
        self.view_btn = QPushButton("View")
        self.view_btn.setFixedSize(50, 25)
        self.view_btn.setVisible(False)
        self.view_btn.setStyleSheet("""
            QPushButton {
                background-color: #3498db;
                color: white;
                border: 1px solid #2980b9;
                border-radius: 3px;
                font-size: 9px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2980b9;
                border: 1px solid #21618c;
            }
            QPushButton:pressed {
                background-color: #21618c;
            }
        """)
        
        layout.addStretch()  # Left stretch
        layout.addWidget(self.start_btn)
        layout.addWidget(self.pause_btn)
        layout.addWidget(self.view_btn)
        layout.addStretch()  # Right stretch
    
    def update_buttons(self, status: str):
        """Update button visibility based on status"""
        if status == "ready":
            self.start_btn.setVisible(True)
            self.start_btn.setText("Start")
            self.pause_btn.setVisible(False)
            self.view_btn.setVisible(False)
        elif status == "queued":
            self.start_btn.setVisible(False)
            self.pause_btn.setVisible(False)  # No buttons when queued (waiting in line)
            self.view_btn.setVisible(False)
        elif status == "uploading":
            self.start_btn.setVisible(False)
            self.pause_btn.setVisible(True)
            self.view_btn.setVisible(False)
        elif status == "paused":
            self.start_btn.setVisible(True)
            self.start_btn.setText("Resume")
            self.pause_btn.setVisible(False)
            self.view_btn.setVisible(False)
        elif status == "completed":
            self.start_btn.setVisible(False)
            self.pause_btn.setVisible(False)
            self.view_btn.setVisible(True)
        else:  # failed
            self.start_btn.setVisible(False)
            self.pause_btn.setVisible(False)
            self.view_btn.setVisible(False)

class BBCodeViewerDialog(QDialog):
    """Dialog for viewing and editing BBCode text files"""
    
    def __init__(self, folder_path, parent=None):
        super().__init__(parent)
        self.folder_path = folder_path
        self.folder_name = os.path.basename(folder_path)
        self.central_path = None
        self.folder_files = []
        
        # Import here to avoid circular imports
        from imxup import get_central_storage_path
        self.central_path = get_central_storage_path()
        
        self.setWindowTitle(f"BBCode Files - {self.folder_name}")
        self.setModal(True)
        self.resize(800, 600)
        
        # Setup UI
        layout = QVBoxLayout(self)
        
        # Info label
        self.info_label = QLabel()
        layout.addWidget(self.info_label)
        
        # Text editor
        self.text_edit = QPlainTextEdit()
        self.text_edit.setFont(QFont("Consolas", 10))
        layout.addWidget(self.text_edit)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.copy_btn = QPushButton("Copy to Clipboard")
        self.copy_btn.clicked.connect(self.copy_to_clipboard)
        button_layout.addWidget(self.copy_btn)
        
        button_layout.addStretch()
        
        # Standard dialog buttons
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.save_files)
        self.button_box.rejected.connect(self.reject)
        button_layout.addWidget(self.button_box)
        
        layout.addLayout(button_layout)
        
        # Load content
        self.load_content()
    
    def get_file_paths(self):
        """Get the BBCode file paths (central and folder locations)"""
        # Try to get gallery info from the main GUI
        gallery_id = None
        gallery_name = None
        
        # Find the main GUI window to get item info
        widget = self.parent()
        while widget:
            if hasattr(widget, 'queue_manager'):
                item = widget.queue_manager.get_item(self.folder_path)
                if item and item.gallery_id:
                    gallery_id = item.gallery_id
                    gallery_name = item.name
                break
            widget = widget.parent()
        
        # Central location files - try new format first, then fallback to old
        if gallery_id and gallery_name:
            safe_gallery_name = sanitize_gallery_name(gallery_name)
            central_bbcode = os.path.join(self.central_path, f"{safe_gallery_name}_{gallery_id}_bbcode.txt")
            central_url = os.path.join(self.central_path, f"{safe_gallery_name}_{gallery_id}.url")
        else:
            # Fallback to old format for existing files
            central_bbcode = os.path.join(self.central_path, f"{self.folder_name}_bbcode.txt")
            central_url = os.path.join(self.central_path, f"{self.folder_name}.url")
        
        # Folder location files (with glob pattern)
        import glob
        folder_bbcode_pattern = os.path.join(self.folder_path, "gallery_*_bbcode.txt")
        folder_url_pattern = os.path.join(self.folder_path, "gallery_*.url")
        
        folder_bbcode_files = glob.glob(folder_bbcode_pattern)
        folder_url_files = glob.glob(folder_url_pattern)
        
        return {
            'central_bbcode': central_bbcode,
            'central_url': central_url,
            'folder_bbcode': folder_bbcode_files[0] if folder_bbcode_files else None,
            'folder_url': folder_url_files[0] if folder_url_files else None
        }
    
    def load_content(self):
        """Load BBCode content from files"""
        file_paths = self.get_file_paths()
        
        # Try to load from central location first, then folder location
        content = ""
        source_file = None
        
        if os.path.exists(file_paths['central_bbcode']):
            with open(file_paths['central_bbcode'], 'r', encoding='utf-8') as f:
                content = f.read()
            source_file = file_paths['central_bbcode']
        elif file_paths['folder_bbcode'] and os.path.exists(file_paths['folder_bbcode']):
            with open(file_paths['folder_bbcode'], 'r', encoding='utf-8') as f:
                content = f.read()
            source_file = file_paths['folder_bbcode']
        
        if source_file:
            self.info_label.setText(f"Loaded from: {source_file}")
            self.text_edit.setPlainText(content)
        else:
            self.info_label.setText("No BBCode files found for this gallery")
            self.text_edit.setPlainText("No BBCode content available")
            self.text_edit.setReadOnly(True)
            self.button_box.button(QDialogButtonBox.StandardButton.Save).setEnabled(False)
    
    def copy_to_clipboard(self):
        """Copy content to clipboard"""
        content = self.text_edit.toPlainText()
        clipboard = QApplication.clipboard()
        clipboard.setText(content)
        
        # Show brief confirmation
        self.copy_btn.setText("Copied!")
        QTimer.singleShot(1000, lambda: self.copy_btn.setText("Copy to Clipboard"))
    
    def save_files(self):
        """Save content to both central and folder locations"""
        content = self.text_edit.toPlainText()
        file_paths = self.get_file_paths()
        
        try:
            # Save to central location
            with open(file_paths['central_bbcode'], 'w', encoding='utf-8') as f:
                f.write(content)
            
            # Save to folder location if it exists
            if file_paths['folder_bbcode']:
                with open(file_paths['folder_bbcode'], 'w', encoding='utf-8') as f:
                    f.write(content)
            
            self.accept()
            
        except Exception as e:
            QMessageBox.warning(self, "Save Error", f"Error saving files: {str(e)}")

class TableProgressWidget(QWidget):
    """Progress bar widget for table cells - properly centered and sized"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)  # Minimal margins
        layout.setSpacing(0)  # No spacing between elements
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p%")
        self.progress_bar.setMinimumHeight(24)  # Taller for better visibility
        self.progress_bar.setMaximumHeight(26)  # Control maximum height
        self.progress_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)  # Center the text
        
        # Style for better text visibility and proper sizing
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #ccc;
                border-radius: 3px;
                text-align: center;
                font-size: 11px;
                font-weight: bold;
                margin: 0px;
                padding: 0px;
            }
            QProgressBar::chunk {
                border-radius: 2px;
            }
        """)
        
        # Make progress bar fill the entire cell
        layout.addWidget(self.progress_bar, 1)  # Stretch factor of 1
        
    def update_progress(self, value: int, status: str = ""):
        self.progress_bar.setValue(value)
        
        # Color code by status with better styling
        if status == "completed":
            self.progress_bar.setStyleSheet("""
                QProgressBar {
                    border: 1px solid #27ae60;
                    border-radius: 3px;
                    text-align: center;
                    font-size: 11px;
                    font-weight: bold;
                }
                QProgressBar::chunk {
                    background-color: #27ae60;
                    border-radius: 2px;
                }
            """)
        elif status == "failed":
            self.progress_bar.setStyleSheet("""
                QProgressBar {
                    border: 1px solid #e74c3c;
                    border-radius: 3px;
                    text-align: center;
                    font-size: 12px;
                    font-weight: bold;
                }
                QProgressBar::chunk {
                    background-color: #e74c3c;
                    border-radius: 2px;
                }
            """)
        elif status == "uploading":
            self.progress_bar.setStyleSheet("""
                QProgressBar {
                    border: 1px solid #3498db;
                    border-radius: 3px;
                    text-align: center;
                    font-size: 12px;
                    font-weight: bold;
                }
                QProgressBar::chunk {
                    background-color: #3498db;
                    border-radius: 2px;
                }
            """)
        else:
            self.progress_bar.setStyleSheet("""
                QProgressBar {
                    border: 1px solid #ccc;
                    border-radius: 3px;
                    text-align: center;
                    font-size: 12px;
                    font-weight: bold;
                }
                QProgressBar::chunk {
                    background-color: #f0f0f0;
                    border-radius: 2px;
                }
            """)

class SingleInstanceServer(QThread):
    """Server for single instance communication"""
    
    folder_received = pyqtSignal(str)
    
    def __init__(self, port=COMMUNICATION_PORT):
        super().__init__()
        self.port = port
        self.running = True
        
    def run(self):
        try:
            server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_socket.bind(('localhost', self.port))
            server_socket.listen(1)
            server_socket.settimeout(1.0)  # Timeout for checking self.running
            
            while self.running:
                try:
                    client_socket, _ = server_socket.accept()
                    data = client_socket.recv(1024).decode('utf-8')
                    if data:
                        self.folder_received.emit(data)
                    client_socket.close()
                except socket.timeout:
                    continue
                except Exception as e:
                    if self.running:  # Only log if we're supposed to be running
                        print(f"Server error: {e}")
                        
            server_socket.close()
        except Exception as e:
            print(f"Failed to start server: {e}")
    
    def stop(self):
        self.running = False
        self.wait()

class ImxUploadGUI(QMainWindow):
    """Main GUI application"""
    
    def __init__(self):
        super().__init__()
        self.queue_manager = QueueManager()
        self.worker = None
        self.table_progress_widgets = {}
        self.settings = QSettings("ImxUploader", "ImxUploadGUI")
        
        # Enable drag and drop on main window
        self.setAcceptDrops(True)
        
        # Single instance server
        self.server = SingleInstanceServer()
        self.server.folder_received.connect(self.add_folder_from_command_line)
        self.server.start()
        
        self.setup_ui()
        self.setup_system_tray()
        self.restore_settings()
        
        # Start worker thread
        self.start_worker()
        
        # Initial display update
        self.update_queue_display()
        
        # Update timer
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_progress_display)
        self.update_timer.start(500)  # Update every 500ms
        
    def setup_ui(self):
        self.setWindowTitle("IMX.to Gallery Uploader")
        self.setMinimumSize(800, 600)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main layout - vertical to stack queue and progress
        main_layout = QVBoxLayout(central_widget)
        
        # Top section with queue and settings
        top_layout = QHBoxLayout()
        
        # Left panel - Queue and controls (wider now)
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        
        # Queue section
        queue_group = QGroupBox("Upload Queue")
        queue_layout = QVBoxLayout(queue_group)
        
        # Simple drag and drop label - EXACTLY like your working test
        self.drop_label = QLabel("Drag folders here to add them to the upload queue")
        self.drop_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_label.setStyleSheet("border: 2px dashed #ccc; padding: 20px; font-size: 14px; background-color: #f9f9f9;")
        self.drop_label.setAcceptDrops(True)  # Enable drag and drop on the label specifically
        self.drop_label.setMinimumHeight(80)
        queue_layout.addWidget(self.drop_label)
        
        # Add folder button
        add_folder_btn = QPushButton("Browse for Folders...")
        add_folder_btn.clicked.connect(self.browse_for_folders)
        queue_layout.addWidget(add_folder_btn)
        
        # Gallery table
        self.gallery_table = GalleryTableWidget()
        self.gallery_table.setMinimumHeight(400)  # Taller table
        queue_layout.addWidget(self.gallery_table, 1)  # Give it stretch priority
        
        # Queue controls
        controls_layout = QHBoxLayout()
        
        self.start_all_btn = QPushButton("Start All")
        self.start_all_btn.clicked.connect(self.start_all_uploads)
        controls_layout.addWidget(self.start_all_btn)
        
        self.pause_all_btn = QPushButton("Pause All")
        self.pause_all_btn.clicked.connect(self.pause_all_uploads)
        controls_layout.addWidget(self.pause_all_btn)
        
        self.clear_completed_btn = QPushButton("Clear Completed")
        self.clear_completed_btn.clicked.connect(self.clear_completed)
        controls_layout.addWidget(self.clear_completed_btn)
        
        queue_layout.addLayout(controls_layout)
        left_layout.addWidget(queue_group)
        
        top_layout.addWidget(left_panel, 3)  # 3/4 width for queue (more space)
        
        # Right panel - Settings and logs
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        
        # Settings section
        settings_group = QGroupBox("Settings")
        settings_layout = QGridLayout(settings_group)
        
        # Load defaults
        defaults = load_user_defaults()
        
        # Thumbnail size
        settings_layout.addWidget(QLabel("Thumbnail Size:"), 0, 0)
        self.thumbnail_size_combo = QComboBox()
        self.thumbnail_size_combo.addItems([
            "100x100", "180x180", "250x250", "300x300", "150x150"
        ])
        self.thumbnail_size_combo.setCurrentIndex(defaults.get('thumbnail_size', 3) - 1)
        settings_layout.addWidget(self.thumbnail_size_combo, 0, 1)
        
        # Thumbnail format
        settings_layout.addWidget(QLabel("Thumbnail Format:"), 1, 0)
        self.thumbnail_format_combo = QComboBox()
        self.thumbnail_format_combo.addItems([
            "Fixed width", "Proportional", "Square", "Fixed height"
        ])
        self.thumbnail_format_combo.setCurrentIndex(defaults.get('thumbnail_format', 2) - 1)
        settings_layout.addWidget(self.thumbnail_format_combo, 1, 1)
        
        # Max retries
        settings_layout.addWidget(QLabel("Max Retries:"), 2, 0)
        self.max_retries_spin = QSpinBox()
        self.max_retries_spin.setRange(1, 10)
        self.max_retries_spin.setValue(defaults.get('max_retries', 3))
        settings_layout.addWidget(self.max_retries_spin, 2, 1)
        
        # Public gallery
        self.public_gallery_check = QCheckBox("Make galleries public")
        self.public_gallery_check.setChecked(defaults.get('public_gallery', 1) == 1)
        settings_layout.addWidget(self.public_gallery_check, 3, 0, 1, 2)
        
        # Confirm delete
        self.confirm_delete_check = QCheckBox("Confirm before deleting items")
        self.confirm_delete_check.setChecked(True)  # Default checked
        settings_layout.addWidget(self.confirm_delete_check, 4, 0, 1, 2)
        
        right_layout.addWidget(settings_group)
        
        # Log section
        log_group = QGroupBox("Log")
        log_layout = QVBoxLayout(log_group)
        
        self.log_text = QTextEdit()
        self.log_text.setMinimumHeight(300)  # Much taller
        self.log_text.setFont(QFont("Consolas", 9))  # Slightly larger font
        log_layout.addWidget(self.log_text)
        
        right_layout.addWidget(log_group, 1)  # Give it stretch priority
        
        top_layout.addWidget(right_panel, 1)  # 1/4 width for settings/log (less space)
        
        main_layout.addLayout(top_layout)
        
        # Bottom section - Overall progress (full width)
        progress_group = QGroupBox("Overall Progress")
        progress_layout = QVBoxLayout(progress_group)
        
        # Overall progress
        overall_layout = QHBoxLayout()
        overall_layout.addWidget(QLabel("Overall:"))
        self.overall_progress = QProgressBar()
        self.overall_progress.setTextVisible(True)
        self.overall_progress.setFormat("Ready")
        self.overall_progress.setMinimumHeight(25)
        overall_layout.addWidget(self.overall_progress)
        progress_layout.addLayout(overall_layout)
        
        # Statistics
        self.stats_label = QLabel("Ready to upload galleries")
        self.stats_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stats_label.setStyleSheet("color: #666; font-style: italic;")
        progress_layout.addWidget(self.stats_label)
        
        main_layout.addWidget(progress_group)
        
    def setup_system_tray(self):
        """Setup system tray icon"""
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon = QSystemTrayIcon(self)
            
            # Create a simple icon
            pixmap = QPixmap(16, 16)
            pixmap.fill(Qt.GlobalColor.blue)
            self.tray_icon.setIcon(QIcon(pixmap))
            
            # Tray menu
            tray_menu = QMenu()
            
            show_action = tray_menu.addAction("Show")
            show_action.triggered.connect(self.show)
            
            quit_action = tray_menu.addAction("Quit")
            quit_action.triggered.connect(self.close)
            
            self.tray_icon.setContextMenu(tray_menu)
            self.tray_icon.activated.connect(self.tray_icon_activated)
            self.tray_icon.show()
    
    def tray_icon_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show()
            self.raise_()
            self.activateWindow()
    
    def start_worker(self):
        """Start the upload worker thread"""
        if self.worker is None or not self.worker.isRunning():
            self.worker = UploadWorker(self.queue_manager)
            self.worker.progress_updated.connect(self.on_progress_updated)
            self.worker.gallery_started.connect(self.on_gallery_started)
            self.worker.gallery_completed.connect(self.on_gallery_completed)
            self.worker.gallery_failed.connect(self.on_gallery_failed)
            self.worker.log_message.connect(self.add_log_message)
            self.worker.start()
    
    def browse_for_folders(self):
        """Open folder browser to select galleries"""
        folder_path = QFileDialog.getExistingDirectory(
            self,
            "Select Gallery Folder",
            "",
            QFileDialog.Option.ShowDirsOnly
        )
        
        if folder_path:
            self.add_folders([folder_path])
    
    def add_folders(self, folder_paths: List[str]):
        """Add folders to the upload queue"""
        added_count = 0
        for path in folder_paths:
            if self.queue_manager.add_item(path):
                added_count += 1
                self.add_log_message(f"{timestamp()} Added to queue: {os.path.basename(path)}")
            else:
                self.add_log_message(f"{timestamp()} Failed to add: {os.path.basename(path)} (no images or already in queue)")
        
        if added_count > 0:
            self.update_queue_display()
    
    def add_folder_from_command_line(self, folder_path: str):
        """Add folder from command line (single instance)"""
        self.add_folders([folder_path])
        
        # Show window if hidden
        if not self.isVisible():
            self.show()
            self.raise_()
            self.activateWindow()
    
    def update_queue_display(self):
        """Update the gallery table display"""
        items = self.queue_manager.get_all_items()
        
        # Create a lookup table: path -> row number in current sorted table
        path_to_row = {}
        for row in range(self.gallery_table.rowCount()):
            name_item = self.gallery_table.item(row, 1)  # Gallery name is now column 1
            if name_item:
                stored_path = name_item.data(Qt.ItemDataRole.UserRole)
                if stored_path:
                    path_to_row[stored_path] = row
        
        # Update table row count if needed
        if self.gallery_table.rowCount() != len(items):
            self.gallery_table.setRowCount(len(items))
        
        # Update items using lookup table or add new ones
        for item in items:
            if item.path in path_to_row:
                # Update existing row
                row = path_to_row[item.path]
            else:
                # Find first empty row or add new row
                row = None
                for r in range(self.gallery_table.rowCount()):
                    name_item = self.gallery_table.item(r, 1)  # Gallery name is in column 1
                    if not name_item or not name_item.data(Qt.ItemDataRole.UserRole):
                        row = r
                        break
                if row is None:
                    continue  # Skip if no available row
            
            # Order number
            order_item = QTableWidgetItem(str(item.insertion_order))
            order_item.setFlags(order_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            order_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            order_item.setFont(QFont("Arial", 9))
            self.gallery_table.setItem(row, 0, order_item)
            
            # Gallery name
            name_item = QTableWidgetItem(item.name or "Unknown")
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            name_item.setData(Qt.ItemDataRole.UserRole, item.path)
            self.gallery_table.setItem(row, 1, name_item)
            
            # Uploaded count
            uploaded_text = f"{item.uploaded_images}/{item.total_images}" if item.total_images > 0 else "0/?"
            uploaded_item = QTableWidgetItem(uploaded_text)
            uploaded_item.setFlags(uploaded_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            uploaded_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.gallery_table.setItem(row, 2, uploaded_item)
            
            # Progress bar - always create fresh widget to avoid sorting issues
            progress_widget = TableProgressWidget()
            progress_widget.update_progress(item.progress, item.status)
            self.gallery_table.setCellWidget(row, 3, progress_widget)
            
            # Status
            status_item = QTableWidgetItem(item.status.title())
            status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            
            # Color code status
            if item.status == "completed":
                status_item.setBackground(QColor(46, 204, 113))  # Green
                status_item.setForeground(QColor(0, 0, 0))  # Black text
            elif item.status == "failed":
                status_item.setBackground(QColor(231, 76, 60))  # Red
                status_item.setForeground(QColor(255, 255, 255))  # White text
            elif item.status == "uploading":
                status_item.setBackground(QColor(52, 152, 219))  # Blue
                status_item.setForeground(QColor(255, 255, 255))  # White text
            elif item.status == "paused":
                status_item.setBackground(QColor(241, 196, 15))  # Yellow
                status_item.setForeground(QColor(0, 0, 0))  # Black text
            elif item.status == "queued":
                status_item.setBackground(QColor(189, 195, 199))  # Light gray
                status_item.setForeground(QColor(0, 0, 0))  # Black text
            elif item.status == "ready":
                # Default styling for ready items
                pass
            
            self.gallery_table.setItem(row, 4, status_item)
            
            # Added time
            added_text = ""
            if item.added_time:
                added_dt = datetime.fromtimestamp(item.added_time)
                added_text = added_dt.strftime("%Y-%m-%d %H:%M")
            added_item = QTableWidgetItem(added_text)
            added_item.setFlags(added_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            added_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            added_item.setFont(QFont("Arial", 9))
            self.gallery_table.setItem(row, 5, added_item)
            
            # Finished time
            finished_text = ""
            if item.finished_time:
                finished_dt = datetime.fromtimestamp(item.finished_time)
                finished_text = finished_dt.strftime("%Y-%m-%d %H:%M")
            finished_item = QTableWidgetItem(finished_text)
            finished_item.setFlags(finished_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            finished_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            finished_item.setFont(QFont("Arial", 9))
            self.gallery_table.setItem(row, 6, finished_item)
            
            # Action buttons - always create fresh widget to avoid sorting issues
            action_widget = ActionButtonWidget()
            # Connect button signals with proper closure capture
            action_widget.start_btn.clicked.connect(lambda checked, path=item.path: self.start_single_item(path))
            action_widget.pause_btn.clicked.connect(lambda checked, path=item.path: self.pause_single_item(path))
            action_widget.view_btn.clicked.connect(lambda checked, path=item.path: self.view_bbcode_files(path))
            action_widget.update_buttons(item.status)
            self.gallery_table.setCellWidget(row, 7, action_widget)
    
    def update_progress_display(self):
        """Update overall progress and statistics"""
        items = self.queue_manager.get_all_items()
        
        if not items:
            self.overall_progress.setValue(0)
            self.overall_progress.setFormat("Ready")
            self.stats_label.setText("Ready to upload galleries")
            return
        
        # Calculate overall progress
        total_images = sum(item.total_images for item in items if item.total_images > 0)
        uploaded_images = sum(item.uploaded_images for item in items)
        
        if total_images > 0:
            overall_percent = int((uploaded_images / total_images) * 100)
            self.overall_progress.setValue(overall_percent)
            self.overall_progress.setFormat(f"{overall_percent}% ({uploaded_images}/{total_images})")
        else:
            self.overall_progress.setValue(0)
            self.overall_progress.setFormat("Preparing...")
        
        # Update statistics
        completed = sum(1 for item in items if item.status == "completed")
        uploading = sum(1 for item in items if item.status == "uploading")
        failed = sum(1 for item in items if item.status == "failed")
        queued = len(items) - completed - uploading - failed
        
        stats_parts = []
        if queued > 0:
            stats_parts.append(f"{queued} queued")
        if uploading > 0:
            stats_parts.append(f"{uploading} uploading")
        if completed > 0:
            stats_parts.append(f"{completed} completed")
        if failed > 0:
            stats_parts.append(f"{failed} failed")
        
        if stats_parts:
            self.stats_label.setText(" • ".join(stats_parts))
        else:
            self.stats_label.setText("No galleries in queue")
    
    def on_gallery_started(self, path: str, total_images: int):
        """Handle gallery start"""
        with QMutexLocker(self.queue_manager.mutex):
            if path in self.queue_manager.items:
                self.queue_manager.items[path].total_images = total_images
                self.queue_manager.items[path].uploaded_images = 0
        
        # Update display when status changes
        self.update_queue_display()
    
    def on_progress_updated(self, path: str, completed: int, total: int, progress_percent: int, current_image: str):
        """Handle progress updates from worker"""
        with QMutexLocker(self.queue_manager.mutex):
            if path in self.queue_manager.items:
                item = self.queue_manager.items[path]
                item.uploaded_images = completed
                item.total_images = total
                item.progress = progress_percent
                item.current_image = current_image
                
                # Find and update the correct row in the table
                for row in range(self.gallery_table.rowCount()):
                    name_item = self.gallery_table.item(row, 1)  # Gallery name is now column 1
                    if name_item and name_item.data(Qt.ItemDataRole.UserRole) == path:
                        # Update uploaded count
                        uploaded_text = f"{completed}/{total}"
                        uploaded_item = QTableWidgetItem(uploaded_text)
                        uploaded_item.setFlags(uploaded_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        uploaded_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                        self.gallery_table.setItem(row, 2, uploaded_item)  # Uploaded is now column 2
                        
                        # Update progress bar
                        progress_widget = self.gallery_table.cellWidget(row, 3)  # Progress is now column 3
                        if isinstance(progress_widget, TableProgressWidget):
                            progress_widget.update_progress(progress_percent, item.status)
                        else:
                            # Create new progress widget if missing
                            progress_widget = TableProgressWidget()
                            progress_widget.update_progress(progress_percent, item.status)
                            self.gallery_table.setCellWidget(row, 3, progress_widget)  # Progress is now column 3
                        
                        # Update status if it's completed (100%)
                        if progress_percent >= 100:
                            # Set finished timestamp if not already set
                            if not item.finished_time:
                                item.finished_time = time.time()
                            
                            status_item = QTableWidgetItem("Completed")
                            status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                            status_item.setBackground(QColor(46, 204, 113))  # Green background
                            status_item.setForeground(QColor(0, 0, 0))  # Black text
                            self.gallery_table.setItem(row, 4, status_item)  # Status is now column 4
                            
                            # Update the finished time column
                            finished_dt = datetime.fromtimestamp(item.finished_time)
                            finished_text = finished_dt.strftime("%Y-%m-%d %H:%M")
                            finished_item = QTableWidgetItem(finished_text)
                            finished_item.setFlags(finished_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                            finished_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                            finished_item.setFont(QFont("Arial", 9))
                            self.gallery_table.setItem(row, 6, finished_item)
                        break
    
    def on_gallery_completed(self, path: str, results: dict):
        """Handle gallery completion"""
        with QMutexLocker(self.queue_manager.mutex):
            if path in self.queue_manager.items:
                item = self.queue_manager.items[path]
                item.status = "completed"
                item.progress = 100
                item.gallery_url = results.get('gallery_url', '')
                item.gallery_id = results.get('gallery_id', '')
                item.finished_time = time.time()  # Set completion timestamp
        
        # Create gallery files with new naming format
        gallery_id = results.get('gallery_id', '')
        gallery_name = results.get('gallery_name', os.path.basename(path))
        
        if gallery_id and gallery_name:
            # Create BBCode content
            bbcode_content = ""
            for image_data in results.get('images', []):
                bbcode_content += image_data.get('bbcode', '') + "\n"
            
            # Create shortcut content
            shortcut_content = f"""[InternetShortcut]
URL=https://imx.to/g/{gallery_id}
"""
            
            # Save to folder location (keep existing format for compatibility)
            gallery_folder = path
            folder_bbcode_path = os.path.join(gallery_folder, f"gallery_{gallery_id}_bbcode.txt")
            folder_shortcut_path = os.path.join(gallery_folder, f"gallery_{gallery_id}.url")
            
            with open(folder_bbcode_path, 'w', encoding='utf-8') as f:
                f.write(bbcode_content)
            with open(folder_shortcut_path, 'w', encoding='utf-8') as f:
                f.write(shortcut_content)
            
            # Save to central location with new naming format
            from imxup import get_central_storage_path
            central_path = get_central_storage_path()
            
            # Sanitize gallery name for filename
            safe_gallery_name = sanitize_gallery_name(gallery_name)
            
            central_bbcode_path = os.path.join(central_path, f"{safe_gallery_name}_{gallery_id}_bbcode.txt")
            central_shortcut_path = os.path.join(central_path, f"{safe_gallery_name}_{gallery_id}.url")
            
            with open(central_bbcode_path, 'w', encoding='utf-8') as f:
                f.write(bbcode_content)
            with open(central_shortcut_path, 'w', encoding='utf-8') as f:
                f.write(shortcut_content)
            
            self.add_log_message(f"{timestamp()} Saved gallery files to central location: {central_path}")
        
        # Update display when status changes
        self.update_queue_display()
        
        gallery_url = results.get('gallery_url', '')
        total_size = results.get('total_size', 0)
        upload_time = results.get('upload_time', 0)
        successful_count = results.get('successful_count', 0)
        
        self.add_log_message(f"{timestamp()} ✓ Completed: {gallery_name}")
        self.add_log_message(f"{timestamp()} Gallery URL: {gallery_url}")
        self.add_log_message(f"{timestamp()} Uploaded {successful_count} images ({total_size / (1024*1024):.1f} MB) in {upload_time:.1f}s")
    
    def on_gallery_failed(self, path: str, error_message: str):
        """Handle gallery failure"""
        with QMutexLocker(self.queue_manager.mutex):
            if path in self.queue_manager.items:
                item = self.queue_manager.items[path]
                item.status = "failed"
                item.error_message = error_message
        
        # Update display when status changes
        self.update_queue_display()
        
        gallery_name = os.path.basename(path)
        self.add_log_message(f"{timestamp()} ✗ Failed: {gallery_name} - {error_message}")
    
    def add_log_message(self, message: str):
        """Add message to log"""
        self.log_text.append(message)
        
        # Keep log size manageable
        if self.log_text.document().blockCount() > 1000:
            cursor = self.log_text.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)
            cursor.movePosition(cursor.MoveOperation.Down, cursor.MoveMode.KeepAnchor, 100)
            cursor.removeSelectedText()
    
    def start_single_item(self, path: str):
        """Start a single item"""
        if self.queue_manager.start_item(path):
            self.add_log_message(f"{timestamp()} Started: {os.path.basename(path)}")
            self.update_queue_display()
        else:
            self.add_log_message(f"{timestamp()} Failed to start: {os.path.basename(path)}")
    
    def pause_single_item(self, path: str):
        """Pause a single item"""
        if self.queue_manager.pause_item(path):
            self.add_log_message(f"{timestamp()} Paused: {os.path.basename(path)}")
            self.update_queue_display()
        else:
            self.add_log_message(f"{timestamp()} Failed to pause: {os.path.basename(path)}")
    
    def view_bbcode_files(self, path: str):
        """Open BBCode viewer/editor for completed item"""
        # Check if item is completed
        item = self.queue_manager.get_item(path)
        if not item or item.status != "completed":
            QMessageBox.warning(self, "Not Available", "BBCode files are only available for completed galleries.")
            return
        
        # Open the viewer dialog
        dialog = BBCodeViewerDialog(path, self)
        dialog.exec()
    
    def copy_bbcode_to_clipboard(self, path: str):
        """Copy BBCode content to clipboard for the given item"""
        # Check if item is completed
        item = self.queue_manager.get_item(path)
        if not item or item.status != "completed":
            self.add_log_message(f"{timestamp()} BBCode copy failed: {os.path.basename(path)} is not completed")
            return
        
        folder_name = os.path.basename(path)
        
        # Import here to avoid circular imports  
        from imxup import get_central_storage_path
        central_path = get_central_storage_path()
        
        # Try central location first with new naming format
        item = self.queue_manager.get_item(path)
        if item and item.gallery_id:
            # Use new naming format: GalleryName_galleryid_bbcode.txt
            safe_gallery_name = sanitize_gallery_name(item.name or folder_name)
            central_bbcode = os.path.join(central_path, f"{safe_gallery_name}_{item.gallery_id}_bbcode.txt")
        else:
            # Fallback to old format for existing files
            central_bbcode = os.path.join(central_path, f"{folder_name}_bbcode.txt")
        
        content = ""
        source_file = None
        
        if os.path.exists(central_bbcode):
            with open(central_bbcode, 'r', encoding='utf-8') as f:
                content = f.read()
            source_file = central_bbcode
        else:
            # Try folder location (existing format)
            import glob
            folder_bbcode_pattern = os.path.join(path, "gallery_*_bbcode.txt")
            folder_bbcode_files = glob.glob(folder_bbcode_pattern)
            
            if folder_bbcode_files and os.path.exists(folder_bbcode_files[0]):
                with open(folder_bbcode_files[0], 'r', encoding='utf-8') as f:
                    content = f.read()
                source_file = folder_bbcode_files[0]
        
        if content:
            clipboard = QApplication.clipboard()
            clipboard.setText(content)
            self.add_log_message(f"{timestamp()} Copied BBCode to clipboard from: {source_file}")
        else:
            self.add_log_message(f"{timestamp()} No BBCode file found for: {folder_name}")
    
    def start_all_uploads(self):
        """Start all ready uploads"""
        items = self.queue_manager.get_all_items()
        started_count = 0
        for item in items:
            if item.status == "ready" or item.status == "paused":
                if self.queue_manager.start_item(item.path):
                    started_count += 1
        
        if started_count > 0:
            self.add_log_message(f"{timestamp()} Started {started_count} uploads")
            self.update_queue_display()
        else:
            self.add_log_message(f"{timestamp()} No items to start")
    
    def pause_all_uploads(self):
        """Pause all uploads"""
        items = self.queue_manager.get_all_items()
        paused_count = 0
        for item in items:
            if item.status == "uploading":
                if self.queue_manager.pause_item(item.path):
                    paused_count += 1
        
        if paused_count > 0:
            self.add_log_message(f"{timestamp()} Paused {paused_count} uploads")
            self.update_queue_display()
        else:
            self.add_log_message(f"{timestamp()} No items to pause")
    
    def clear_completed(self):
        """Clear completed uploads from queue"""
        removed_count = self.queue_manager.clear_completed()
        if removed_count > 0:
            self.queue_manager.save_persistent_queue()
            self.update_queue_display()
            self.add_log_message(f"{timestamp()} Cleared {removed_count} completed uploads")
        else:
            self.add_log_message(f"{timestamp()} No completed uploads to clear")
    
    def delete_selected_items(self):
        """Delete selected items from the queue"""
        selected_rows = set()
        for item in self.gallery_table.selectedItems():
            selected_rows.add(item.row())
        
        if not selected_rows:
            return
        
        # Get paths directly from the table cells to handle sorting correctly
        selected_paths = []
        selected_names = []
        
        for row in selected_rows:
            name_item = self.gallery_table.item(row, 1)  # Gallery name is in column 1
            if name_item:
                path = name_item.data(Qt.ItemDataRole.UserRole)
                if path:
                    selected_paths.append(path)
                    selected_names.append(name_item.text())
        
        if not selected_paths:
            return
        
        # Check if confirmation is needed
        if self.confirm_delete_check.isChecked():
            if len(selected_paths) == 1:
                message = f"Delete '{selected_names[0]}'?"
            else:
                message = f"Delete {len(selected_paths)} selected items?"
            
            reply = QMessageBox.question(
                self,
                "Confirm Delete",
                message,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            
            if reply != QMessageBox.StandardButton.Yes:
                return
        
        # Remove the items
        removed_count = self.queue_manager.remove_items(selected_paths)
        if removed_count > 0:
            self.queue_manager.save_persistent_queue()
            self.update_queue_display()
            self.add_log_message(f"{timestamp()} Deleted {removed_count} items from queue")
    
    def restore_settings(self):
        """Restore window settings"""
        geometry = self.settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        
        # Restore confirm delete setting
        confirm_delete = self.settings.value("confirm_delete", True, type=bool)
        self.confirm_delete_check.setChecked(confirm_delete)
    
    def save_settings(self):
        """Save window settings"""
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("confirm_delete", self.confirm_delete_check.isChecked())
    
    def dragEnterEvent(self, event):
        """Handle drag enter - SIMPLE VERSION"""
        print("DEBUG: dragEnterEvent called")
        if event.mimeData().hasUrls():
            print("DEBUG: Has URLs")
            self.drop_label.setStyleSheet("border: 2px dashed #00f; padding: 20px; font-size: 14px; background-color: #e8f4fd;")
            self.drop_label.setText("Drop folders here!")
            event.acceptProposedAction()
        else:
            print("DEBUG: No URLs")
            event.ignore()
    
    def dragMoveEvent(self, event):
        """Handle drag move"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()
    
    def dragLeaveEvent(self, event):
        """Handle drag leave"""
        print("DEBUG: dragLeaveEvent called")
        self.drop_label.setStyleSheet("border: 2px dashed #ccc; padding: 20px; font-size: 14px; background-color: #f9f9f9;")
        self.drop_label.setText("Drag folders here to add them to the upload queue")
    
    def dropEvent(self, event):
        """Handle drop - EXACTLY like your working test"""
        print("DEBUG: dropEvent called")
        self.drop_label.setStyleSheet("border: 2px dashed #ccc; padding: 20px; font-size: 14px; background-color: #f9f9f9;")
        
        if event.mimeData().hasUrls():
            print("DEBUG: Processing URLs")
            urls = event.mimeData().urls()
            paths = []
            for url in urls:
                path = url.toLocalFile()
                print(f"DEBUG: Checking path: {path}")
                if os.path.isdir(path):
                    print(f"DEBUG: Adding folder: {path}")
                    paths.append(path)
            
            if paths:
                print(f"DEBUG: SUCCESS! Found {len(paths)} folders: {', '.join(os.path.basename(p) for p in paths)}")
                self.drop_label.setText(f"Added {len(paths)} folders!")
                self.add_folders(paths)
                event.acceptProposedAction()
                # Reset after 2 seconds
                QTimer.singleShot(2000, lambda: self.drop_label.setText("Drag folders here to add them to the upload queue"))
            else:
                print("DEBUG: No valid folders in drop")
                self.drop_label.setText("No valid folders in drop")
                event.ignore()
        else:
            print("DEBUG: No URLs in drop")
            event.ignore()

    def closeEvent(self, event):
        """Handle window close"""
        self.save_settings()
        
        # Save queue state
        self.queue_manager.save_persistent_queue()
        
        # Always stop worker and server on close
        if self.worker:
            self.worker.stop()
        self.server.stop()
        
        # Accept the close event to ensure app exits
        event.accept()

def check_single_instance(folder_path=None):
    """Check if another instance is running and send folder if needed"""
    try:
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_socket.connect(('localhost', COMMUNICATION_PORT))
        
        if folder_path:
            client_socket.send(folder_path.encode('utf-8'))
        
        client_socket.close()
        return True  # Another instance is running
    except ConnectionRefusedError:
        return False  # No other instance running

def main():
    """Main function"""
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)  # Exit when window closes
    
    # Handle command line arguments
    folder_to_add = None
    if len(sys.argv) > 1:
        folder_to_add = sys.argv[1]
        if os.path.isdir(folder_to_add):
            # Check if another instance is running
            if check_single_instance(folder_to_add):
                print(f"Added {folder_to_add} to existing instance")
                return
        else:
            print(f"Invalid folder path: {folder_to_add}")
            return
    
    # Create main window
    window = ImxUploadGUI()
    
    # Add folder from command line if provided
    if folder_to_add:
        window.add_folders([folder_to_add])
    
    window.show()
    
    try:
        sys.exit(app.exec())
    except KeyboardInterrupt:
        print("\nExiting gracefully...")
        # Clean shutdown
        if hasattr(window, 'worker') and window.worker:
            window.worker.stop()
        if hasattr(window, 'server') and window.server:
            window.server.stop()
        app.quit()

if __name__ == "__main__":
    main()