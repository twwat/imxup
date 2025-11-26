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
from src.core.engine import UploadEngine, AtomicCounter
from src.utils.logger import log
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
                     thumbnail_format=2, max_retries=3,
                     parallel_batch_size=4, template_name="default",
                     precalculated_dimensions=None,
                     global_byte_counter: Optional[AtomicCounter] = None,
                     gallery_byte_counter: Optional[AtomicCounter] = None):
        """GUI-friendly upload delegating to the shared UploadEngine.

        Args:
            folder_path: Path to folder containing images
            gallery_name: Name for the gallery
            thumbnail_size: Thumbnail size setting
            thumbnail_format: Thumbnail format setting
            max_retries: Maximum retry attempts
            parallel_batch_size: Number of concurrent uploads
            template_name: BBCode template name
            global_byte_counter: Persistent counter across ALL galleries
            gallery_byte_counter: Per-gallery counter (reset for each gallery)
        """
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
        # No sanitization - only rename worker should sanitize

        # Get RenameWorker from worker thread if available
        rename_worker = None
        if self.worker_thread:
            if hasattr(self.worker_thread, 'rename_worker'):
                rename_worker = self.worker_thread.rename_worker
                if rename_worker:
                    log(f"Engine using RenameWorker {id(rename_worker)} from UploadWorker {id(self.worker_thread)}", level="debug", category="renaming")
                    log("Using RenameWorker for background renaming", level="debug", category="renaming")
                else:
                    log("Worker thread has rename_worker attribute but it's None", level="debug", category="renaming")
            else:
                log("Worker thread missing rename_worker attribute", level="debug", category="renaming")
        else:
            # This should not happen in GUI mode but let's log it
            log("No worker_thread available for RenameWorker", level="warning", category="renaming")

        # Create engine with both counters and worker_thread reference
        engine = UploadEngine(
            self,
            rename_worker,
            global_byte_counter=global_byte_counter,
            gallery_byte_counter=gallery_byte_counter,
            worker_thread=self.worker_thread
        )

        def on_progress(completed: int, total: int, percent: int, current_image: str):
            if not self.worker_thread:
                return
            self.worker_thread.progress_updated.emit(folder_path, completed, total, percent, current_image)
            # Trigger bandwidth update (main loop blocked during uploads)
            try:
                self.worker_thread._emit_current_bandwidth()
            except Exception:
                pass

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
            parallel_batch_size=parallel_batch_size,
            template_name=template_name,
            already_uploaded=already_uploaded,
            existing_gallery_id=existing_gallery_id,
            precalculated_dimensions=current_item,  # Pass the whole item, engine will extract what it needs
            on_progress=on_progress,
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
                        image_url = enriched.get('image_url')
                        if not enriched.get('thumb_url') and image_url:
                            try:
                                parts = image_url.split('/i/')
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
                        log(f"Server error: {e}", level="error", category="network")

            server_socket.close()
        except Exception as e:
            log(f"Failed to start server: {e}", level="error", category="network")

    def stop(self):
        """Stop the server"""
        self.running = False
        self.wait()
