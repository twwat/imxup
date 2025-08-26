"""
Service interfaces for dependency injection and clean architecture.
Defines protocols for core services to enable loose coupling.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Protocol, Callable
from pathlib import Path
from dataclasses import dataclass
from enum import Enum


class ServiceResult(Enum):
    """Standard service operation results."""
    SUCCESS = "success"
    FAILURE = "failure"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


@dataclass
class ServiceResponse:
    """Standard response from service operations."""
    result: ServiceResult
    data: Optional[Any] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = None


class IAuthenticationService(Protocol):
    """Interface for authentication operations."""
    
    def login(self, username: str, password: str) -> ServiceResponse:
        """Authenticate user with credentials."""
        ...
    
    def logout(self) -> ServiceResponse:
        """Logout current user."""
        ...
    
    def is_authenticated(self) -> bool:
        """Check if user is currently authenticated."""
        ...
    
    def get_current_user(self) -> Optional[str]:
        """Get current authenticated username."""
        ...


class ISettingsService(Protocol):
    """Interface for settings management."""
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a setting value."""
        ...
    
    def set(self, key: str, value: Any) -> ServiceResponse:
        """Set a setting value."""
        ...
    
    def get_all(self) -> Dict[str, Any]:
        """Get all settings."""
        ...
    
    def reset_to_defaults(self) -> ServiceResponse:
        """Reset all settings to default values."""
        ...
    
    def export_settings(self, path: Path) -> ServiceResponse:
        """Export settings to file."""
        ...
    
    def import_settings(self, path: Path) -> ServiceResponse:
        """Import settings from file."""
        ...


class ITemplateService(Protocol):
    """Interface for template management."""
    
    def get_template(self, name: str) -> Optional[str]:
        """Get template content by name."""
        ...
    
    def list_templates(self) -> List[str]:
        """List all available templates."""
        ...
    
    def save_template(self, name: str, content: str) -> ServiceResponse:
        """Save a template."""
        ...
    
    def delete_template(self, name: str) -> ServiceResponse:
        """Delete a template."""
        ...
    
    def render(self, template_name: str, context: Dict[str, Any]) -> str:
        """Render template with context data."""
        ...


class IQueueService(Protocol):
    """Interface for upload queue management."""
    
    def add_gallery(self, folder_path: Path, name: str, config: Dict[str, Any]) -> str:
        """Add gallery to queue and return queue ID."""
        ...
    
    def remove_gallery(self, queue_id: str) -> ServiceResponse:
        """Remove gallery from queue."""
        ...
    
    def get_queue_status(self) -> List[Dict[str, Any]]:
        """Get status of all items in queue."""
        ...
    
    def start_queue(self) -> ServiceResponse:
        """Start processing the upload queue."""
        ...
    
    def pause_queue(self) -> ServiceResponse:
        """Pause queue processing."""
        ...
    
    def clear_completed(self) -> ServiceResponse:
        """Clear completed items from queue."""
        ...


class IStorageService(Protocol):
    """Interface for data persistence."""
    
    def save_gallery(self, gallery_data: Dict[str, Any]) -> ServiceResponse:
        """Persist gallery data."""
        ...
    
    def load_gallery(self, gallery_id: str) -> Optional[Dict[str, Any]]:
        """Load gallery data."""
        ...
    
    def delete_gallery(self, gallery_id: str) -> ServiceResponse:
        """Delete gallery data."""
        ...
    
    def list_galleries(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """List galleries with optional status filter."""
        ...
    
    def backup_data(self, path: Path) -> ServiceResponse:
        """Backup all data to file."""
        ...
    
    def restore_data(self, path: Path) -> ServiceResponse:
        """Restore data from backup file."""
        ...


class IEventBus(Protocol):
    """Interface for event publishing and subscription."""
    
    def subscribe(self, event_type: str, callback: Callable) -> str:
        """Subscribe to events and return subscription ID."""
        ...
    
    def unsubscribe(self, subscription_id: str) -> bool:
        """Unsubscribe from events."""
        ...
    
    def publish(self, event_type: str, data: Any) -> None:
        """Publish an event."""
        ...


class IUIService(Protocol):
    """Interface for UI operations (for decoupling business logic from UI)."""
    
    def show_message(self, message: str, message_type: str = "info") -> None:
        """Show a message to the user."""
        ...
    
    def show_error(self, error: str) -> None:
        """Show an error message to the user."""
        ...
    
    def ask_confirmation(self, message: str) -> bool:
        """Ask user for confirmation."""
        ...
    
    def show_progress(self, current: int, total: int, message: str) -> None:
        """Update progress display."""
        ...
    
    def select_folder(self, title: str) -> Optional[Path]:
        """Let user select a folder."""
        ...
    
    def select_file(self, title: str, filters: str) -> Optional[Path]:
        """Let user select a file."""
        ...


# Domain Models

@dataclass
class Gallery:
    """Domain model for a gallery."""
    id: str
    name: str
    folder_path: Path
    status: str
    images: List['Image']
    created_at: str
    updated_at: str
    metadata: Dict[str, Any]


@dataclass
class Image:
    """Domain model for an image."""
    filename: str
    path: Path
    size: int
    width: Optional[int] = None
    height: Optional[int] = None
    upload_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    status: str = "pending"


@dataclass
class Template:
    """Domain model for a template."""
    name: str
    content: str
    placeholders: List[str]
    created_at: str
    updated_at: str


@dataclass
class UserSettings:
    """Domain model for user settings."""
    username: str
    upload_settings: Dict[str, Any]
    ui_settings: Dict[str, Any]
    paths: Dict[str, str]
    preferences: Dict[str, Any]


# Service Factory Interface

class IServiceFactory(Protocol):
    """Factory for creating service instances."""
    
    def create_auth_service(self) -> IAuthenticationService:
        """Create authentication service."""
        ...
    
    def create_settings_service(self) -> ISettingsService:
        """Create settings service."""
        ...
    
    def create_template_service(self) -> ITemplateService:
        """Create template service."""
        ...
    
    def create_queue_service(self) -> IQueueService:
        """Create queue service."""
        ...
    
    def create_storage_service(self) -> IStorageService:
        """Create storage service."""
        ...
    
    def create_event_bus(self) -> IEventBus:
        """Create event bus."""
        ...


# Exception Classes

class ServiceException(Exception):
    """Base exception for service operations."""
    pass


class AuthenticationException(ServiceException):
    """Exception for authentication failures."""
    pass


class ValidationException(ServiceException):
    """Exception for validation failures."""
    pass


class StorageException(ServiceException):
    """Exception for storage operations."""
    pass


class NetworkException(ServiceException):
    """Exception for network operations."""
    pass


class TemplateException(ServiceException):
    """Exception for template operations."""
    pass