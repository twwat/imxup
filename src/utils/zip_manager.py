"""
Smart ZIP file manager for file host uploads.

Handles creation, reuse, and cleanup of temporary ZIP files with reference counting
to avoid creating multiple ZIPs for the same gallery when uploading to multiple hosts.
"""

import os
import zipfile
import tempfile
import threading
from pathlib import Path
from typing import Dict, Tuple, Optional
from src.utils.logger import log


class ZIPManager:
    """Manages temporary ZIP files with reference counting for reuse across hosts."""

    def __init__(self, temp_dir: Optional[Path] = None):
        """Initialize ZIP manager.

        Args:
            temp_dir: Directory for temporary ZIP files. If None, uses system temp.
        """
        self.temp_dir = temp_dir or Path(tempfile.gettempdir())
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        # Cache: {gallery_id: (zip_path, ref_count)}
        self.zip_cache: Dict[int, Tuple[Path, int]] = {}
        self.lock = threading.Lock()

    def create_or_reuse_zip(
        self,
        db_id: int,
        folder_path: Path,
        gallery_name: Optional[str] = None
    ) -> Path:
        """Create a new ZIP or return existing cached ZIP path.

        Args:
            db_id: Unique database ID
            folder_path: Path to gallery folder
            gallery_name: Optional gallery name for ZIP filename

        Returns:
            Path to ZIP file

        Raises:
            Exception: If ZIP creation fails
        """
        with self.lock:
            # Check if ZIP already exists in cache
            if db_id in self.zip_cache:
                zip_path, ref_count = self.zip_cache[db_id]

                # Verify ZIP still exists on disk
                if zip_path.exists():
                    self.zip_cache[db_id] = (zip_path, ref_count + 1)
                    log(
                        f"Reusing existing ZIP for gallery {db_id} (refs: {ref_count + 1}): {zip_path.name}",
                        level="debug",
                        category="file_hosts"
                    )
                    return zip_path
                else:
                    # ZIP was deleted externally, remove from cache
                    log(
                        f"Cached ZIP no longer exists: {zip_path}, recreating...",
                        level="warning",
                        category="file_hosts"
                    )
                    del self.zip_cache[db_id]

            # Create new ZIP
            zip_name = self._generate_zip_name(db_id, gallery_name)
            zip_path = self.temp_dir / zip_name

            log(f"Creating ZIP for gallery {db_id}: {zip_path.name}", level="info", category="file_hosts")

            try:
                self._create_store_mode_zip(folder_path, zip_path)

                # Add to cache with ref_count = 1
                self.zip_cache[db_id] = (zip_path, 1)

                file_size_mb = zip_path.stat().st_size / (1024 * 1024)
                log(
                    f"Created ZIP: {zip_path.name} ({file_size_mb:.2f} MB)",
                    level="info",
                    category="file_hosts"
                )

                return zip_path

            except Exception as e:
                log(f"Failed to create ZIP for gallery {db_id}: {e}", level="error", category="file_hosts")
                # Clean up partial ZIP if it exists
                if zip_path.exists():
                    try:
                        zip_path.unlink()
                    except (OSError, PermissionError):
                        pass
                raise

    def release_zip(self, db_id: int, force_delete: bool = False) -> bool:
        """Release a reference to a ZIP file. Deletes when ref_count reaches 0.

        Args:
            db_id: Database ID
            force_delete: If True, delete immediately regardless of ref count

        Returns:
            True if ZIP was deleted, False otherwise
        """
        with self.lock:
            if db_id not in self.zip_cache:
                log(
                    f"Attempted to release non-existent ZIP for gallery {db_id}",
                    level="warning",
                    category="file_hosts"
                )
                return False

            zip_path, ref_count = self.zip_cache[db_id]

            if force_delete:
                # Force delete the ZIP (explicit cleanup request)
                try:
                    file_existed = zip_path.exists()
                    if file_existed:
                        zip_path.unlink()
                        log(
                            f"Deleted ZIP for gallery {db_id}: {zip_path.name}",
                            level="debug",
                            category="file_hosts"
                        )
                    del self.zip_cache[db_id]
                    return file_existed
                except Exception as e:
                    log(f"Failed to delete ZIP {zip_path}: {e}", level="error", category="file_hosts")
                    # Remove from cache anyway
                    del self.zip_cache[db_id]
                    return False
            elif ref_count <= 1:
                # Decrement to 0 but keep in cache for retry reuse
                self.zip_cache[db_id] = (zip_path, 0)
                log(
                    f"Released ZIP reference for gallery {db_id} (refs: 0, kept for retry)",
                    level="debug",
                    category="file_hosts"
                )
                return False
            else:
                # Decrement ref count
                self.zip_cache[db_id] = (zip_path, ref_count - 1)
                log(
                    f"Released ZIP reference for gallery {db_id} (refs: {ref_count - 1})",
                    level="debug",
                    category="file_hosts"
                )
                return False

    def cleanup_gallery(self, gallery_id: int) -> None:
        """Force cleanup of ZIP for a gallery (ignores ref count).

        Args:
            gallery_id: Gallery ID
        """
        self.release_zip(gallery_id, force_delete=True)

    def cleanup_all(self) -> int:
        """Clean up all cached ZIPs. Use when shutting down.

        Returns:
            Number of ZIPs deleted
        """
        with self.lock:
            deleted_count = 0
            gallery_ids = list(self.zip_cache.keys())

            # FIXED: Call release_zip without holding the lock to avoid deadlock
            # release_zip() acquires its own lock, so calling it while holding
            # the lock causes a deadlock (thread waiting for itself)

        # Release lock before calling release_zip
        for gallery_id in gallery_ids:
            if self.release_zip(gallery_id, force_delete=True):
                deleted_count += 1

        return deleted_count

    def get_cache_info(self) -> Dict[int, Dict]:
        """Get information about cached ZIPs.

        Returns:
            Dictionary of gallery_id -> {path, ref_count, size_mb, exists}
        """
        with self.lock:
            info = {}
            for gallery_id, (zip_path, ref_count) in self.zip_cache.items():
                info[gallery_id] = {
                    'path': str(zip_path),
                    'ref_count': ref_count,
                    'exists': zip_path.exists(),
                    'size_mb': zip_path.stat().st_size / (1024 * 1024) if zip_path.exists() else 0
                }
            return info

    def _generate_zip_name(self, gallery_id: int, gallery_name: Optional[str] = None) -> str:
        """Generate ZIP filename.

        Args:
            gallery_id: Gallery ID
            gallery_name: Optional gallery name

        Returns:
            ZIP filename
        """
        # Sanitize gallery name for filename
        if gallery_name:
            safe_name = "".join(c for c in gallery_name if c.isalnum() or c in (' ', '-', '_')).strip()
            safe_name = safe_name[:50]  # Limit length
            if safe_name:
                return f"imxup_{gallery_id}_{safe_name}.zip"

        return f"imxup_gallery_{gallery_id}.zip"

    def _create_store_mode_zip(self, folder_path: Path, zip_path: Path) -> None:
        """Create a ZIP file in store mode (no compression) for maximum speed.

        Args:
            folder_path: Path to folder to ZIP
            zip_path: Path where ZIP should be created

        Raises:
            Exception: If ZIP creation fails
        """
        if not folder_path.exists():
            raise FileNotFoundError(f"Folder does not exist: {folder_path}")

        if not folder_path.is_dir():
            raise ValueError(f"Path is not a directory: {folder_path}")

        # Get list of image files
        image_extensions = ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp')
        image_files = []

        for item in folder_path.iterdir():
            if item.is_file() and item.suffix.lower() in image_extensions:
                image_files.append(item)

        if not image_files:
            raise ValueError(f"No image files found in: {folder_path}")

        # Create ZIP with STORED (no compression) method
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_STORED) as zf:
            for image_file in image_files:
                # Add file to ZIP with just the filename (no directory structure)
                zf.write(image_file, arcname=image_file.name)

        # Verify ZIP was created
        if not zip_path.exists():
            raise Exception(f"ZIP file was not created: {zip_path}")


# Global singleton instance
_zip_manager: Optional[ZIPManager] = None
_zip_manager_lock = threading.Lock()


def get_zip_manager() -> ZIPManager:
    """Get or create the global ZIPManager instance.

    Returns:
        Global ZIPManager instance
    """
    global _zip_manager

    if _zip_manager is None:
        with _zip_manager_lock:
            if _zip_manager is None:
                _zip_manager = ZIPManager()

    return _zip_manager
