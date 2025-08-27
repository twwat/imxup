"""
Network communication and upload management for ImxUp application.
Handles GUI-specific upload logic and single instance server.
"""

import os
import sys
import time
import socket
import ctypes
from typing import Dict, Any, Optional, Callable, Set
from functools import cmp_to_key

from PyQt6.QtCore import QThread, pyqtSignal

from imxup import ImxToUploader, timestamp, sanitize_gallery_name
from src.core.engine import UploadEngine
from src.core.constants import (
    COMMUNICATION_PORT,
    QUEUE_STATE_UPLOADING
)


class GUIImxToUploader(ImxToUploader):
    """Custom uploader for GUI that doesn't block on user input"""
    
    def __init__(self, worker_thread=None):
        super().__init__()
        self.gui_mode = True
        self.worker_thread = worker_thread
    
    def upload_folder(self, folder_path, gallery_name=None, thumbnail_size=3, 
                     thumbnail_format=2, max_retries=3, public_gallery=1, 
                     parallel_batch_size=4, template_name="default"):
        """GUI-friendly upload delegating to the shared UploadEngine."""
        # Non-blocking signals and resume support
        current_item = self.worker_thread.current_item if self.worker_thread else None
        already_uploaded = set(getattr(current_item, 'uploaded_files', set())) if current_item else set()

        # Emit start with original total
        try:
            image_extensions = ('.jpg', '.jpeg', '.png', '.gif')
            # Match Windows Explorer order for total determination (stable across views)
            def _natural_key(n: str):
                import re as _re
                parts = _re.split(r"(\d+)", n)
                out = []
                for p in parts:
                    out.append(int(p) if p.isdigit() else p.lower())
                return tuple(out)
            
            def _explorer_sort(names):
                if sys.platform != 'win32':
                    return sorted(names, key=_natural_key)
                try:
                    _cmp = ctypes.windll.shlwapi.StrCmpLogicalW
                    _cmp.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
                    _cmp.restype = ctypes.c_int
                    return sorted(names, key=cmp_to_key(lambda a, b: _cmp(a, b)))
                except Exception:
                    return sorted(names, key=_natural_key)
            
            names = [
                f for f in os.listdir(folder_path)
                if f.lower().endswith(image_extensions) and os.path.isfile(os.path.join(folder_path, f))
            ]
            original_total = len(_explorer_sort(names))
            if self.worker_thread:
                self.worker_thread.gallery_started.emit(folder_path, original_total)
        except Exception:
            pass

        # Sanitize name like CLI
        if not gallery_name:
            gallery_name = os.path.basename(folder_path)
        original_name = gallery_name
        gallery_name = sanitize_gallery_name(gallery_name)
        if original_name != gallery_name and self.worker_thread:
            self.worker_thread.log_message.emit(
                f"{timestamp()} Sanitized gallery name: '{original_name}' -> '{gallery_name}'"
            )
        
        engine = UploadEngine(self)

        def on_progress(completed: int, total: int, percent: int, current_image: str):
            if not self.worker_thread:
                return
            self.worker_thread.progress_updated.emit(folder_path, completed, total, percent, current_image)
            # Throttled bandwidth: approximate from uploaded_bytes
            try:
                now_ts = time.time()
                if now_ts - self.worker_thread._bw_last_emit >= 0.1:
                    total_bytes = 0
                    max_elapsed = 0.0
                    for it in self.worker_thread.queue_manager.get_all_items():
                        if it.status == QUEUE_STATE_UPLOADING and it.start_time:
                            total_bytes += getattr(it, 'uploaded_bytes', 0)
                            max_elapsed = max(max_elapsed, now_ts - it.start_time)
                    if max_elapsed > 0:
                        kbps = (total_bytes / max_elapsed) / 1024.0
                        self.worker_thread.bandwidth_updated.emit(kbps)
                        self.worker_thread._bw_last_emit = now_ts
                # Also update this item's instantaneous rate for the Transfer column
                try:
                    if self.worker_thread.current_item and self.worker_thread.current_item.path == folder_path:
                        elapsed = max(now_ts - float(self.worker_thread.current_item.start_time or now_ts), 0.001)
                        item_bytes = float(getattr(self.worker_thread.current_item, 'uploaded_bytes', 0) or 0)
                        self.worker_thread.current_item.current_kibps = (item_bytes / elapsed) / 1024.0
                except Exception:
                    pass
                if now_ts - self.worker_thread._stats_last_emit >= 0.5:
                    self.worker_thread._emit_queue_stats()
                    self.worker_thread._stats_last_emit = now_ts
            except Exception:
                pass
                    
        def on_log(message: str):
            if self.worker_thread:
                # Pass through categorized messages from engine
                self.worker_thread.log_message.emit(f"{timestamp()} {message}")

        def should_soft_stop() -> bool:
            if self.worker_thread and self.worker_thread.current_item:
                if self.worker_thread.current_item.path == folder_path:
                    return getattr(self.worker_thread, '_soft_stop_requested_for', None) == folder_path
            return False

        def on_image_uploaded(fname: str, data: Dict[str, Any], size_bytes: int):
            if self.worker_thread and self.worker_thread.current_item:
                if self.worker_thread.current_item.path == folder_path:
                    try:
                        self.worker_thread.current_item.uploaded_files.add(fname)
                        self.worker_thread.current_item.uploaded_images_data.append((fname, data))
                        self.worker_thread.current_item.uploaded_bytes += int(size_bytes or 0)
                    except Exception:
                        pass

        # Get existing gallery_id for resume/append operations
        existing_gallery_id = None
        if current_item and hasattr(current_item, 'gallery_id') and current_item.gallery_id:
            existing_gallery_id = current_item.gallery_id

        results = engine.run(
            folder_path=folder_path,
            gallery_name=gallery_name,
            thumbnail_size=thumbnail_size,
            thumbnail_format=thumbnail_format,
            max_retries=max_retries,
            public_gallery=public_gallery,
            parallel_batch_size=parallel_batch_size,
            template_name=template_name,
            already_uploaded=already_uploaded,
            existing_gallery_id=existing_gallery_id,
            on_progress=on_progress,
            on_log=on_log,
            should_soft_stop=should_soft_stop,
            on_image_uploaded=on_image_uploaded,
        )
        
        # Merge previously uploaded images (from earlier partial runs) with this run's results
        try:
            if self.worker_thread and self.worker_thread.current_item:
                if self.worker_thread.current_item.path == folder_path:
                    item = self.worker_thread.current_item
                    # Build ordering map based on Explorer order (match engine)
                    image_extensions = ('.jpg', '.jpeg', '.png', '.gif')
                    
                    def _natural_key(n: str):
                        import re as _re
                        parts = _re.split(r"(\d+)", n)
                        out = []
                        for p in parts:
                            out.append(int(p) if p.isdigit() else p.lower())
                        return tuple(out)
                    
                    def _explorer_sort(names):
                        if sys.platform != 'win32':
                            return sorted(names, key=_natural_key)
                        try:
                            _cmp = ctypes.windll.shlwapi.StrCmpLogicalW
                            _cmp.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
                            _cmp.restype = ctypes.c_int
                            return sorted(names, key=cmp_to_key(lambda a, b: _cmp(a, b)))
                        except Exception:
                            return sorted(names, key=_natural_key)
                    
                    all_image_files = _explorer_sort([
                        f for f in os.listdir(folder_path)
                        if f.lower().endswith(image_extensions) and os.path.isfile(os.path.join(folder_path, f))
                    ])
                    file_position = {fname: idx for idx, fname in enumerate(all_image_files)}
                    
                    # Collect enriched image data from accumulated uploads across runs
                    combined_by_name = {}
                    for fname, data in getattr(item, 'uploaded_images_data', []):
                        try:
                            base, ext = os.path.splitext(fname)
                            fname_norm = base + ext.lower()
                        except Exception:
                            fname_norm = fname
                        enriched = dict(data)
                        # Ensure required fields present
                        enriched.setdefault('original_filename', fname_norm)
                        # Best-effort thumb_url (mirrors engine)
                        if not enriched.get('thumb_url') and enriched.get('image_url'):
                            try:
                                parts = enriched.get('image_url').split('/i/')
                                if len(parts) == 2 and parts[1]:
                                    img_id = parts[1].split('/')[0]
                                    _, ext2 = os.path.splitext(fname_norm)
                                    ext_use = (ext2.lower() or '.jpg') if ext2 else '.jpg'
                                    enriched['thumb_url'] = f"https://imx.to/u/t/{img_id}{ext_use}"
                            except Exception:
                                pass
                        # Size bytes
                        try:
                            enriched.setdefault('size_bytes', 
                                              os.path.getsize(os.path.join(folder_path, fname)))
                        except Exception:
                            enriched.setdefault('size_bytes', 0)
                        combined_by_name[fname] = enriched
                    
                    # Order by original folder order (Explorer sort)
                    ordered = sorted(combined_by_name.items(), 
                                   key=lambda kv: file_position.get(kv[0], 10**9))
                    merged_images = [data for _fname, data in ordered]
                    
                    if merged_images:
                        # Replace images in results so downstream BBCode includes all
                        results = dict(results)  # shallow copy
                        results['images'] = merged_images
                        results['successful_count'] = len(merged_images)
                        # Uploaded size across all merged images
                        try:
                            results['uploaded_size'] = sum(
                                int(img.get('size_bytes') or 0) for img in merged_images
                            )
                        except Exception:
                            pass
                        # Ensure total_images reflects full set
                        results['total_images'] = len(all_image_files)
        except Exception:
            pass

        return results


class SingleInstanceServer(QThread):
    """Server for single instance communication"""
    
    folder_received = pyqtSignal(str)
    
    def __init__(self, port=COMMUNICATION_PORT):
        super().__init__()
        self.port = port
        self.running = True
        
    def run(self):
        """Run the single instance server"""
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
                    # Emit signal for both folder paths and empty messages (window focus)
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
        """Stop the server"""
        self.running = False
        self.wait()