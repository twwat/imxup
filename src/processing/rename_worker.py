"""
Background worker for handling gallery rename operations asynchronously.

This worker processes gallery renames in the background to avoid blocking
the main upload process, significantly improving upload performance.
"""

import threading
import queue
import time
from typing import Optional, Callable, Any


class RenameWorker:
    """Background worker for handling gallery rename operations."""
    
    def __init__(self, uploader: Any = None):
        """
        Initialize RenameWorker.
        
        Args:
            uploader: The uploader instance with rename_gallery_with_session method
        """
        self.queue = queue.Queue()
        self.running = True
        self.uploader = uploader
        self.thread = threading.Thread(target=self._process_renames, daemon=True, name="RenameWorker")
        self.thread.start()
    
    def queue_rename(self, gallery_id: str, gallery_name: str, callback: Optional[Callable[[str], None]] = None):
        """
        Queue a rename request for background processing.
        
        Args:
            gallery_id: The ID of the gallery to rename
            gallery_name: The desired name for the gallery
            callback: Optional callback function for logging (receives log message string)
        """
        if not gallery_id or not gallery_name:
            return
            
        self.queue.put({
            'gallery_id': gallery_id,
            'gallery_name': gallery_name,
            'callback': callback,
            'timestamp': time.time()
        })
    
    def _process_renames(self):
        """Process rename requests from the queue in background thread."""
        while self.running:
            try:
                # Wait for rename request with timeout
                try:
                    request = self.queue.get(timeout=1.0)
                except queue.Empty:
                    continue
                
                if request is None:  # Shutdown signal
                    break
                
                gallery_id = request['gallery_id']
                gallery_name = request['gallery_name']
                callback = request['callback']
                
                # Attempt to rename the gallery
                success = self._attempt_rename(gallery_id, gallery_name, callback)
                
                if not success:
                    # If rename failed, queue for later auto-rename
                    self._queue_for_auto_rename(gallery_id, gallery_name, callback)
                
                # Mark task as done
                self.queue.task_done()
                
            except Exception as e:
                # Don't let any exception crash the worker thread
                if callback:
                    try:
                        callback(f"RenameWorker error: {str(e)}")
                    except Exception:
                        pass
                continue
    
    def _attempt_rename(self, gallery_id: str, gallery_name: str, callback: Optional[Callable[[str], None]]) -> bool:
        """
        Attempt to rename a gallery using the uploader session.
        
        Returns:
            bool: True if rename was successful, False otherwise
        """
        if not self.uploader:
            if callback:
                callback(f"RenameWorker: No uploader instance available for '{gallery_name}'")
            return False
        
        try:
            # Check if uploader has the rename method
            rename_method = getattr(self.uploader, 'rename_gallery_with_session', None)
            if not rename_method:
                if callback:
                    callback(f"RenameWorker: Uploader missing rename_gallery_with_session method for '{gallery_name}'")
                return False
            
            # Log the attempt
            if callback:
                callback(f"RenameWorker: Attempting to rename gallery '{gallery_name}' (ID: {gallery_id})")
            
            # Attempt the rename
            success = rename_method(gallery_id, gallery_name)
            
            if success:
                if callback:
                    callback(f"RenameWorker: Successfully renamed gallery to '{gallery_name}'")
                return True
            else:
                if callback:
                    callback(f"RenameWorker: Gallery rename failed for '{gallery_name}' (ID: {gallery_id})")
                return False
                
        except Exception as e:
            if callback:
                callback(f"RenameWorker: Exception renaming gallery '{gallery_name}': {str(e)}")
            return False
    
    def _queue_for_auto_rename(self, gallery_id: str, gallery_name: str, callback: Optional[Callable[[str], None]]):
        """
        Queue gallery for later auto-rename if immediate rename failed.
        """
        try:
            # Import here to avoid circular imports
            from imxup import save_unnamed_gallery
            save_unnamed_gallery(gallery_id, gallery_name)
            
            if callback:
                callback(f"RenameWorker: Background rename failed, queued for auto-rename: '{gallery_name}'")
                
        except Exception as e:
            if callback:
                callback(f"RenameWorker: Failed to queue gallery for auto-rename: {str(e)}")
    
    def set_uploader(self, uploader: Any):
        """
        Set or update the uploader instance.
        
        Args:
            uploader: The uploader instance with rename_gallery_with_session method
        """
        self.uploader = uploader
    
    def stop(self, timeout: float = 5.0):
        """
        Stop the rename worker thread.
        
        Args:
            timeout: Maximum time to wait for worker to stop
        """
        self.running = False
        
        # Send shutdown signal
        try:
            self.queue.put(None)
        except Exception:
            pass
        
        # Wait for thread to finish
        if self.thread.is_alive():
            self.thread.join(timeout=timeout)
    
    def is_running(self) -> bool:
        """Check if the worker is running."""
        return self.running and self.thread.is_alive()
    
    def queue_size(self) -> int:
        """Get the current size of the rename queue."""
        return self.queue.qsize()