"""
Upload Service - Refactored upload logic with clean separation of concerns.
Follows SOLID principles and clean code practices.
"""

import os
import json
import time
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Protocol
from dataclasses import dataclass, field
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging

from .constants import (
    MAX_RETRIES, DEFAULT_TIMEOUT, DEFAULT_PARALLEL_BATCH_SIZE,
    QUEUE_STATE_UPLOADING, QUEUE_STATE_COMPLETED, QUEUE_STATE_FAILED,
    ERROR_NO_IMAGES, ERROR_GALLERY_CREATE_FAILED, ERROR_UPLOAD_FAILED,
    SUCCESS_GALLERY_CREATED, SUCCESS_UPLOAD_COMPLETE,
    IMAGE_EXTENSIONS, MEGABYTE
)


class UploadStatus(Enum):
    """Upload status enumeration."""
    PENDING = "pending"
    VALIDATING = "validating"
    PREPARING = "preparing"
    UPLOADING = "uploading"
    GENERATING_ARTIFACTS = "generating_artifacts"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ImageInfo:
    """Data class for image information."""
    path: Path
    filename: str
    size: int
    width: Optional[int] = None
    height: Optional[int] = None
    md5: Optional[str] = None
    upload_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    status: UploadStatus = UploadStatus.PENDING
    error_message: Optional[str] = None


@dataclass
class GalleryInfo:
    """Data class for gallery information."""
    folder_path: Path
    gallery_name: str
    gallery_id: Optional[str] = None
    gallery_url: Optional[str] = None
    images: List[ImageInfo] = field(default_factory=list)
    total_size: int = 0
    status: UploadStatus = UploadStatus.PENDING
    progress: float = 0.0
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class UploadConfig:
    """Configuration for upload operations."""
    parallel_batch_size: int = DEFAULT_PARALLEL_BATCH_SIZE
    max_retries: int = MAX_RETRIES
    timeout: int = DEFAULT_TIMEOUT
    thumbnail_size: int = 3
    thumbnail_format: int = 2
    is_public: bool = True
    generate_bbcode: bool = True
    template_name: Optional[str] = None
    save_artifacts: bool = True
    artifact_dir: Optional[Path] = None


class IProgressCallback(Protocol):
    """Protocol for progress callbacks."""
    def on_progress(self, current: int, total: int, message: str) -> None:
        """Called when progress is updated."""
        ...
    
    def on_status_change(self, status: UploadStatus, message: str) -> None:
        """Called when status changes."""
        ...


class IUploadClient(Protocol):
    """Protocol for upload client implementations."""
    def login(self, username: str, password: str) -> bool:
        """Authenticate with the service."""
        ...
    
    def create_gallery(self, name: str, config: UploadConfig) -> Optional[str]:
        """Create a new gallery and return its ID."""
        ...
    
    def upload_image(self, gallery_id: str, image_path: Path) -> Optional[Dict[str, str]]:
        """Upload a single image to the gallery."""
        ...
    
    def finalize_gallery(self, gallery_id: str) -> bool:
        """Finalize the gallery after all uploads."""
        ...


class ITemplateEngine(Protocol):
    """Protocol for template engine implementations."""
    def render(self, template_name: str, context: Dict[str, Any]) -> str:
        """Render a template with the given context."""
        ...


class IArtifactGenerator(Protocol):
    """Protocol for artifact generator implementations."""
    def generate(self, gallery_info: GalleryInfo, output_dir: Path) -> List[Path]:
        """Generate artifacts for the gallery."""
        ...


class UploadService:
    """
    Refactored upload service with clean separation of concerns.
    Handles the upload workflow without mixing UI or storage concerns.
    """
    
    def __init__(
        self,
        upload_client: IUploadClient,
        template_engine: Optional[ITemplateEngine] = None,
        artifact_generator: Optional[IArtifactGenerator] = None,
        logger: Optional[logging.Logger] = None
    ):
        """Initialize the upload service with dependencies."""
        self.upload_client = upload_client
        self.template_engine = template_engine
        self.artifact_generator = artifact_generator
        self.logger = logger or logging.getLogger(__name__)
        
    def upload_gallery(
        self,
        folder_path: Path,
        gallery_name: str,
        config: UploadConfig,
        progress_callback: Optional[IProgressCallback] = None
    ) -> GalleryInfo:
        """
        Main upload workflow - orchestrates the entire upload process.
        """
        gallery_info = GalleryInfo(
            folder_path=folder_path,
            gallery_name=gallery_name
        )
        
        try:
            # Step 1: Validate input
            self._update_status(gallery_info, UploadStatus.VALIDATING, 
                              "Validating folder and images...", progress_callback)
            self._validate_folder(gallery_info)
            
            # Step 2: Prepare gallery
            self._update_status(gallery_info, UploadStatus.PREPARING,
                              "Creating gallery...", progress_callback)
            gallery_id = self._create_gallery(gallery_info, config)
            gallery_info.gallery_id = gallery_id
            
            # Step 3: Upload images
            self._update_status(gallery_info, UploadStatus.UPLOADING,
                              "Uploading images...", progress_callback)
            self._upload_images(gallery_info, config, progress_callback)
            
            # Step 4: Generate artifacts
            if config.save_artifacts:
                self._update_status(gallery_info, UploadStatus.GENERATING_ARTIFACTS,
                                  "Generating artifacts...", progress_callback)
                self._generate_artifacts(gallery_info, config)
            
            # Step 5: Complete
            self._update_status(gallery_info, UploadStatus.COMPLETED,
                              SUCCESS_UPLOAD_COMPLETE, progress_callback)
            
        except Exception as e:
            self.logger.error(f"Upload failed: {e}")
            gallery_info.status = UploadStatus.FAILED
            gallery_info.error_message = str(e)
            if progress_callback:
                progress_callback.on_status_change(UploadStatus.FAILED, str(e))
            raise
            
        return gallery_info
    
    def _validate_folder(self, gallery_info: GalleryInfo) -> None:
        """Validate folder and scan for images."""
        if not gallery_info.folder_path.exists():
            raise ValueError(f"Folder does not exist: {gallery_info.folder_path}")
        
        # Scan for images
        images = self._scan_images(gallery_info.folder_path)
        if not images:
            raise ValueError(ERROR_NO_IMAGES)
        
        gallery_info.images = images
        gallery_info.total_size = sum(img.size for img in images)
        
    def _scan_images(self, folder_path: Path) -> List[ImageInfo]:
        """Scan folder for valid images."""
        images = []
        for file_path in sorted(folder_path.iterdir()):
            if file_path.is_file() and file_path.suffix.lower() in IMAGE_EXTENSIONS:
                images.append(ImageInfo(
                    path=file_path,
                    filename=file_path.name,
                    size=file_path.stat().st_size
                ))
        return images
    
    def _create_gallery(self, gallery_info: GalleryInfo, config: UploadConfig) -> str:
        """Create gallery on the service."""
        gallery_id = self.upload_client.create_gallery(
            gallery_info.gallery_name,
            config
        )
        if not gallery_id:
            raise RuntimeError(ERROR_GALLERY_CREATE_FAILED)
        
        self.logger.info(f"Gallery created: {gallery_id}")
        return gallery_id
    
    def _upload_images(
        self,
        gallery_info: GalleryInfo,
        config: UploadConfig,
        progress_callback: Optional[IProgressCallback] = None
    ) -> None:
        """Upload all images in parallel batches."""
        total_images = len(gallery_info.images)
        completed = 0
        
        with ThreadPoolExecutor(max_workers=config.parallel_batch_size) as executor:
            futures = []
            for image in gallery_info.images:
                future = executor.submit(
                    self._upload_single_image,
                    gallery_info.gallery_id,
                    image,
                    config
                )
                futures.append((future, image))
            
            for future, image in futures:
                try:
                    result = future.result(timeout=config.timeout)
                    if result:
                        image.upload_url = result.get('url')
                        image.thumbnail_url = result.get('thumbnail')
                        image.status = UploadStatus.COMPLETED
                    completed += 1
                    
                    if progress_callback:
                        progress_callback.on_progress(
                            completed, total_images,
                            f"Uploaded {image.filename}"
                        )
                    gallery_info.progress = (completed / total_images) * 100
                    
                except Exception as e:
                    self.logger.error(f"Failed to upload {image.filename}: {e}")
                    image.status = UploadStatus.FAILED
                    image.error_message = str(e)
    
    def _upload_single_image(
        self,
        gallery_id: str,
        image: ImageInfo,
        config: UploadConfig
    ) -> Optional[Dict[str, str]]:
        """Upload a single image with retry logic."""
        for attempt in range(config.max_retries):
            try:
                result = self.upload_client.upload_image(gallery_id, image.path)
                if result:
                    return result
            except Exception as e:
                if attempt == config.max_retries - 1:
                    raise
                self.logger.warning(f"Retry {attempt + 1} for {image.filename}")
                time.sleep(2 ** attempt)  # Exponential backoff
        
        return None
    
    def _generate_artifacts(
        self,
        gallery_info: GalleryInfo,
        config: UploadConfig
    ) -> None:
        """Generate BBCode and other artifacts."""
        if self.artifact_generator:
            output_dir = config.artifact_dir or gallery_info.folder_path
            artifacts = self.artifact_generator.generate(gallery_info, output_dir)
            gallery_info.metadata['artifacts'] = [str(p) for p in artifacts]
    
    def _update_status(
        self,
        gallery_info: GalleryInfo,
        status: UploadStatus,
        message: str,
        callback: Optional[IProgressCallback] = None
    ) -> None:
        """Update gallery status and notify callback."""
        gallery_info.status = status
        self.logger.info(f"{status.value}: {message}")
        if callback:
            callback.on_status_change(status, message)


class UploadOrchestrator:
    """
    High-level orchestrator for managing multiple gallery uploads.
    Coordinates between UI, storage, and upload services.
    """
    
    def __init__(
        self,
        upload_service: UploadService,
        max_concurrent: int = 3
    ):
        """Initialize the orchestrator."""
        self.upload_service = upload_service
        self.max_concurrent = max_concurrent
        self.active_uploads: Dict[str, GalleryInfo] = {}
        self.queue: List[Tuple[Path, str, UploadConfig]] = []
        
    def add_to_queue(
        self,
        folder_path: Path,
        gallery_name: str,
        config: UploadConfig
    ) -> str:
        """Add a gallery to the upload queue."""
        queue_id = self._generate_queue_id(folder_path)
        self.queue.append((folder_path, gallery_name, config))
        return queue_id
    
    def start_uploads(self) -> None:
        """Start processing the upload queue."""
        with ThreadPoolExecutor(max_workers=self.max_concurrent) as executor:
            futures = []
            for folder_path, gallery_name, config in self.queue:
                future = executor.submit(
                    self.upload_service.upload_gallery,
                    folder_path,
                    gallery_name,
                    config
                )
                futures.append(future)
            
            # Wait for all uploads to complete
            for future in as_completed(futures):
                try:
                    result = future.result()
                    self._handle_upload_complete(result)
                except Exception as e:
                    self.logger.error(f"Upload failed: {e}")
    
    def cancel_upload(self, queue_id: str) -> bool:
        """Cancel an active upload."""
        # Implementation for cancellation
        pass
    
    def get_status(self, queue_id: str) -> Optional[GalleryInfo]:
        """Get the status of an upload."""
        return self.active_uploads.get(queue_id)
    
    def _generate_queue_id(self, folder_path: Path) -> str:
        """Generate a unique queue ID for a folder."""
        return hashlib.md5(str(folder_path).encode()).hexdigest()[:8]
    
    def _handle_upload_complete(self, gallery_info: GalleryInfo) -> None:
        """Handle upload completion."""
        queue_id = self._generate_queue_id(gallery_info.folder_path)
        self.active_uploads[queue_id] = gallery_info