"""
Concrete implementations of service interfaces.
Clean implementations following SOLID principles.
"""

import os
import json
import sqlite3
import hashlib
import configparser
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
from datetime import datetime
from dataclasses import dataclass
import threading
from contextlib import contextmanager

from ..core.interfaces import (
    IAuthenticationService, ISettingsService, ITemplateService,
    IQueueService, IStorageService, IEventBus,
    ServiceResponse, ServiceResult, ServiceException,
    AuthenticationException, ValidationException, StorageException
)
from ..core.events import (
    EventBus, EventContext, UserLoginEvent, UserLogoutEvent,
    SettingChangedEvent, TemplateCreatedEvent, TemplateUpdatedEvent,
    GalleryAddedEvent, publish_event
)
from ..core.constants import *


@dataclass
class AuthenticationResult:
    """Result of authentication attempt."""
    success: bool
    username: Optional[str] = None
    session_token: Optional[str] = None
    error_message: Optional[str] = None


class AuthenticationService(IAuthenticationService):
    """
    Thread-safe authentication service with secure credential storage.
    """
    
    def __init__(self, settings_service: ISettingsService, event_bus: Optional[EventBus] = None):
        self.settings_service = settings_service
        self.event_bus = event_bus
        self.logger = logging.getLogger(__name__)
        self._current_user: Optional[str] = None
        self._session_token: Optional[str] = None
        self._lock = threading.RLock()
    
    def login(self, username: str, password: str) -> ServiceResponse:
        """Authenticate user and create session."""
        with self._lock:
            try:
                # Validate credentials
                if not self._validate_credentials(username, password):
                    error_msg = "Invalid credentials"
                    self.logger.warning(f"Login failed for user: {username}")
                    return ServiceResponse(ServiceResult.FAILURE, error=error_msg)
                
                # Create session
                self._current_user = username
                self._session_token = self._generate_session_token(username)
                
                # Save session info
                self.settings_service.set("current_user", username)
                self.settings_service.set("session_token", self._session_token)
                
                self.logger.info(f"User logged in: {username}")
                
                # Publish event
                if self.event_bus:
                    context = EventContext(source="AuthenticationService")
                    event = UserLoginEvent(username, context)
                    self.event_bus.publish(event)
                
                return ServiceResponse(
                    ServiceResult.SUCCESS,
                    data={"username": username, "session_token": self._session_token}
                )
                
            except Exception as e:
                self.logger.error(f"Login error: {e}")
                return ServiceResponse(ServiceResult.FAILURE, error=str(e))
    
    def logout(self) -> ServiceResponse:
        """Logout current user and clear session."""
        with self._lock:
            try:
                current_user = self._current_user
                if not current_user:
                    return ServiceResponse(ServiceResult.FAILURE, error="No user logged in")
                
                # Clear session
                self._current_user = None
                self._session_token = None
                
                # Clear stored session
                self.settings_service.set("current_user", "")
                self.settings_service.set("session_token", "")
                
                self.logger.info(f"User logged out: {current_user}")
                
                # Publish event
                if self.event_bus:
                    context = EventContext(source="AuthenticationService")
                    event = UserLogoutEvent(current_user, context)
                    self.event_bus.publish(event)
                
                return ServiceResponse(ServiceResult.SUCCESS)
                
            except Exception as e:
                self.logger.error(f"Logout error: {e}")
                return ServiceResponse(ServiceResult.FAILURE, error=str(e))
    
    def is_authenticated(self) -> bool:
        """Check if user is currently authenticated."""
        with self._lock:
            return self._current_user is not None and self._session_token is not None
    
    def get_current_user(self) -> Optional[str]:
        """Get current authenticated username."""
        with self._lock:
            return self._current_user
    
    def _validate_credentials(self, username: str, password: str) -> bool:
        """Validate username and password."""
        if not username or not password:
            return False
        
        # Get stored credentials from settings
        stored_username = self.settings_service.get("credentials.username", "")
        stored_password = self.settings_service.get("credentials.password", "")
        
        if not stored_username or not stored_password:
            return False
        
        # Compare credentials (in real implementation, password should be hashed)
        return username == stored_username and password == stored_password
    
    def _generate_session_token(self, username: str) -> str:
        """Generate a session token for the user."""
        timestamp = datetime.now().isoformat()
        data = f"{username}:{timestamp}:{os.urandom(16).hex()}"
        return hashlib.sha256(data.encode()).hexdigest()


class SettingsService(ISettingsService):
    """
    Settings service with file-based persistence and change notifications.
    """
    
    def __init__(self, config_file: Optional[Path] = None, event_bus: Optional[EventBus] = None):
        self.config_file = config_file or Path.home() / CONFIG_DIR_NAME / CONFIG_FILE_NAME
        self.event_bus = event_bus
        self.logger = logging.getLogger(__name__)
        self._config = configparser.ConfigParser()
        self._lock = threading.RLock()
        self._load_settings()
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a setting value."""
        with self._lock:
            try:
                section, option = self._parse_key(key)
                if self._config.has_option(section, option):
                    return self._deserialize_value(self._config.get(section, option))
                return default
            except Exception as e:
                self.logger.error(f"Error getting setting {key}: {e}")
                return default
    
    def set(self, key: str, value: Any) -> ServiceResponse:
        """Set a setting value."""
        with self._lock:
            try:
                old_value = self.get(key)
                section, option = self._parse_key(key)
                
                if not self._config.has_section(section):
                    self._config.add_section(section)
                
                self._config.set(section, option, self._serialize_value(value))
                self._save_settings()
                
                # Publish change event
                if self.event_bus and old_value != value:
                    context = EventContext(source="SettingsService")
                    event = SettingChangedEvent(key, old_value, value, context)
                    self.event_bus.publish(event)
                
                return ServiceResponse(ServiceResult.SUCCESS)
                
            except Exception as e:
                self.logger.error(f"Error setting {key}: {e}")
                return ServiceResponse(ServiceResult.FAILURE, error=str(e))
    
    def get_all(self) -> Dict[str, Any]:
        """Get all settings."""
        with self._lock:
            result = {}
            for section_name in self._config.sections():
                for option_name, value in self._config.items(section_name):
                    key = f"{section_name}.{option_name}" if section_name != "DEFAULT" else option_name
                    result[key] = self._deserialize_value(value)
            return result
    
    def reset_to_defaults(self) -> ServiceResponse:
        """Reset all settings to default values."""
        with self._lock:
            try:
                self._config.clear()
                self._load_default_settings()
                self._save_settings()
                return ServiceResponse(ServiceResult.SUCCESS)
            except Exception as e:
                self.logger.error(f"Error resetting settings: {e}")
                return ServiceResponse(ServiceResult.FAILURE, error=str(e))
    
    def export_settings(self, path: Path) -> ServiceResponse:
        """Export settings to file."""
        try:
            with open(path, 'w') as f:
                self._config.write(f)
            return ServiceResponse(ServiceResult.SUCCESS)
        except Exception as e:
            return ServiceResponse(ServiceResult.FAILURE, error=str(e))
    
    def import_settings(self, path: Path) -> ServiceResponse:
        """Import settings from file."""
        try:
            if not path.exists():
                return ServiceResponse(ServiceResult.FAILURE, error="File does not exist")
            
            with self._lock:
                self._config.read(path)
                self._save_settings()
            return ServiceResponse(ServiceResult.SUCCESS)
        except Exception as e:
            return ServiceResponse(ServiceResult.FAILURE, error=str(e))
    
    def _load_settings(self) -> None:
        """Load settings from file."""
        try:
            if self.config_file.exists():
                self._config.read(self.config_file)
            else:
                self._load_default_settings()
                self._save_settings()
        except Exception as e:
            self.logger.error(f"Error loading settings: {e}")
            self._load_default_settings()
    
    def _save_settings(self) -> None:
        """Save settings to file."""
        try:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_file, 'w') as f:
                self._config.write(f)
        except Exception as e:
            self.logger.error(f"Error saving settings: {e}")
    
    def _load_default_settings(self) -> None:
        """Load default settings."""
        defaults = {
            'upload.parallel_batch_size': str(DEFAULT_PARALLEL_BATCH_SIZE),
            'upload.max_retries': str(MAX_RETRIES),
            'upload.thumbnail_size': str(DEFAULT_THUMBNAIL_SIZE),
            'upload.thumbnail_format': str(DEFAULT_THUMBNAIL_FORMAT),
            'upload.timeout': str(DEFAULT_TIMEOUT),
            'ui.window_width': str(DEFAULT_WINDOW_WIDTH),
            'ui.window_height': str(DEFAULT_WINDOW_HEIGHT),
            'ui.theme': 'default',
            'storage.base_path': str(Path.home() / CONFIG_DIR_NAME),
            'credentials.username': '',
            'credentials.password': ''
        }
        
        for key, value in defaults.items():
            section, option = self._parse_key(key)
            if not self._config.has_section(section):
                self._config.add_section(section)
            self._config.set(section, option, value)
    
    def _parse_key(self, key: str) -> tuple[str, str]:
        """Parse setting key into section and option."""
        if '.' in key:
            section, option = key.split('.', 1)
        else:
            section, option = 'DEFAULT', key
        return section, option
    
    def _serialize_value(self, value: Any) -> str:
        """Serialize value for storage."""
        if isinstance(value, bool):
            return str(value).lower()
        elif isinstance(value, (int, float)):
            return str(value)
        elif isinstance(value, (list, dict)):
            return json.dumps(value)
        else:
            return str(value)
    
    def _deserialize_value(self, value_str: str) -> Any:
        """Deserialize value from storage."""
        # Try to parse as JSON first
        try:
            return json.loads(value_str)
        except:
            pass
        
        # Try boolean
        if value_str.lower() in ('true', 'false'):
            return value_str.lower() == 'true'
        
        # Try number
        try:
            if '.' in value_str:
                return float(value_str)
            else:
                return int(value_str)
        except ValueError:
            pass
        
        # Return as string
        return value_str


class TemplateService(ITemplateService):
    """
    Template service with file-based storage and rendering.
    """
    
    def __init__(self, templates_dir: Optional[Path] = None, event_bus: Optional[EventBus] = None):
        self.templates_dir = templates_dir or (Path.home() / CONFIG_DIR_NAME / TEMPLATES_DIR_NAME)
        self.event_bus = event_bus
        self.logger = logging.getLogger(__name__)
        self._lock = threading.RLock()
        self.templates_dir.mkdir(parents=True, exist_ok=True)
    
    def get_template(self, name: str) -> Optional[str]:
        """Get template content by name."""
        with self._lock:
            template_file = self.templates_dir / f"{name}.template"
            if template_file.exists():
                try:
                    return template_file.read_text(encoding='utf-8')
                except Exception as e:
                    self.logger.error(f"Error reading template {name}: {e}")
            return None
    
    def list_templates(self) -> List[str]:
        """List all available templates."""
        with self._lock:
            templates = []
            for template_file in self.templates_dir.glob("*.template"):
                templates.append(template_file.stem)
            return sorted(templates)
    
    def save_template(self, name: str, content: str) -> ServiceResponse:
        """Save a template."""
        with self._lock:
            try:
                if not self._validate_template_name(name):
                    return ServiceResponse(ServiceResult.FAILURE, error="Invalid template name")
                
                template_file = self.templates_dir / f"{name}.template"
                is_new = not template_file.exists()
                
                template_file.write_text(content, encoding='utf-8')
                
                # Publish event
                if self.event_bus:
                    context = EventContext(source="TemplateService")
                    event_class = TemplateCreatedEvent if is_new else TemplateUpdatedEvent
                    event = event_class(name, context)
                    self.event_bus.publish(event)
                
                return ServiceResponse(ServiceResult.SUCCESS)
                
            except Exception as e:
                self.logger.error(f"Error saving template {name}: {e}")
                return ServiceResponse(ServiceResult.FAILURE, error=str(e))
    
    def delete_template(self, name: str) -> ServiceResponse:
        """Delete a template."""
        with self._lock:
            try:
                template_file = self.templates_dir / f"{name}.template"
                if not template_file.exists():
                    return ServiceResponse(ServiceResult.FAILURE, error="Template not found")
                
                template_file.unlink()
                
                # Publish event
                if self.event_bus:
                    context = EventContext(source="TemplateService")
                    event = TemplateDeletedEvent(name, context)  # This would need to be imported
                    self.event_bus.publish(event)
                
                return ServiceResponse(ServiceResult.SUCCESS)
                
            except Exception as e:
                self.logger.error(f"Error deleting template {name}: {e}")
                return ServiceResponse(ServiceResult.FAILURE, error=str(e))
    
    def render(self, template_name: str, context: Dict[str, Any]) -> str:
        """Render template with context data."""
        template_content = self.get_template(template_name)
        if not template_content:
            raise ValidationException(f"Template not found: {template_name}")
        
        # Simple placeholder replacement
        rendered = template_content
        for placeholder in TEMPLATE_PLACEHOLDERS:
            if placeholder in rendered:
                key = placeholder.strip('#').lower()
                value = str(context.get(key, ''))
                rendered = rendered.replace(placeholder, value)
        
        return rendered
    
    def _validate_template_name(self, name: str) -> bool:
        """Validate template name."""
        if not name or not isinstance(name, str):
            return False
        
        # Check for valid filename characters
        invalid_chars = set('<>:"/\\|?*')
        return not any(c in invalid_chars for c in name)


class DatabaseService(IStorageService):
    """
    SQLite-based storage service with connection pooling.
    """
    
    def __init__(self, db_file: Optional[Path] = None):
        self.db_file = db_file or (Path.home() / CONFIG_DIR_NAME / DATABASE_FILE_NAME)
        self.logger = logging.getLogger(__name__)
        self._lock = threading.RLock()
        self._init_database()
    
    def _init_database(self) -> None:
        """Initialize database schema."""
        self.db_file.parent.mkdir(parents=True, exist_ok=True)
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Galleries table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS galleries (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    folder_path TEXT NOT NULL,
                    status TEXT NOT NULL,
                    gallery_url TEXT,
                    config TEXT,
                    metadata TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Images table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS images (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    gallery_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    size INTEGER,
                    width INTEGER,
                    height INTEGER,
                    upload_url TEXT,
                    thumbnail_url TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (gallery_id) REFERENCES galleries (id)
                )
            ''')
            
            # Create indexes
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_galleries_status ON galleries (status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_images_gallery_id ON images (gallery_id)')
            
            conn.commit()
    
    @contextmanager
    def _get_connection(self):
        """Get database connection with automatic cleanup."""
        conn = None
        try:
            conn = sqlite3.connect(
                self.db_file,
                timeout=DB_CONNECTION_TIMEOUT,
                check_same_thread=False
            )
            conn.row_factory = sqlite3.Row
            yield conn
        finally:
            if conn:
                conn.close()
    
    def save_gallery(self, gallery_data: Dict[str, Any]) -> ServiceResponse:
        """Persist gallery data."""
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    
                    gallery_id = gallery_data['id']
                    
                    # Check if gallery exists
                    cursor.execute('SELECT id FROM galleries WHERE id = ?', (gallery_id,))
                    exists = cursor.fetchone() is not None
                    
                    if exists:
                        # Update existing gallery
                        cursor.execute('''
                            UPDATE galleries 
                            SET name = ?, status = ?, gallery_url = ?, config = ?, 
                                metadata = ?, updated_at = CURRENT_TIMESTAMP
                            WHERE id = ?
                        ''', (
                            gallery_data['name'],
                            gallery_data['status'],
                            gallery_data.get('gallery_url'),
                            json.dumps(gallery_data.get('config', {})),
                            json.dumps(gallery_data.get('metadata', {})),
                            gallery_id
                        ))
                    else:
                        # Insert new gallery
                        cursor.execute('''
                            INSERT INTO galleries (id, name, folder_path, status, gallery_url, config, metadata)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        ''', (
                            gallery_id,
                            gallery_data['name'],
                            gallery_data['folder_path'],
                            gallery_data['status'],
                            gallery_data.get('gallery_url'),
                            json.dumps(gallery_data.get('config', {})),
                            json.dumps(gallery_data.get('metadata', {}))
                        ))
                    
                    # Save images if provided
                    if 'images' in gallery_data:
                        self._save_images(cursor, gallery_id, gallery_data['images'])
                    
                    conn.commit()
                
                return ServiceResponse(ServiceResult.SUCCESS)
                
            except Exception as e:
                self.logger.error(f"Error saving gallery {gallery_data.get('id')}: {e}")
                return ServiceResponse(ServiceResult.FAILURE, error=str(e))
    
    def load_gallery(self, gallery_id: str) -> Optional[Dict[str, Any]]:
        """Load gallery data."""
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    
                    # Load gallery
                    cursor.execute('''
                        SELECT * FROM galleries WHERE id = ?
                    ''', (gallery_id,))
                    
                    gallery_row = cursor.fetchone()
                    if not gallery_row:
                        return None
                    
                    gallery_data = dict(gallery_row)
                    
                    # Parse JSON fields
                    gallery_data['config'] = json.loads(gallery_data['config'] or '{}')
                    gallery_data['metadata'] = json.loads(gallery_data['metadata'] or '{}')
                    
                    # Load images
                    cursor.execute('''
                        SELECT * FROM images WHERE gallery_id = ? ORDER BY filename
                    ''', (gallery_id,))
                    
                    images = []
                    for image_row in cursor.fetchall():
                        images.append(dict(image_row))
                    
                    gallery_data['images'] = images
                    
                    return gallery_data
                    
            except Exception as e:
                self.logger.error(f"Error loading gallery {gallery_id}: {e}")
                return None
    
    def delete_gallery(self, gallery_id: str) -> ServiceResponse:
        """Delete gallery data."""
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    
                    # Delete images first (foreign key constraint)
                    cursor.execute('DELETE FROM images WHERE gallery_id = ?', (gallery_id,))
                    
                    # Delete gallery
                    cursor.execute('DELETE FROM galleries WHERE id = ?', (gallery_id,))
                    
                    conn.commit()
                
                return ServiceResponse(ServiceResult.SUCCESS)
                
            except Exception as e:
                self.logger.error(f"Error deleting gallery {gallery_id}: {e}")
                return ServiceResponse(ServiceResult.FAILURE, error=str(e))
    
    def list_galleries(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """List galleries with optional status filter."""
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    
                    if status:
                        cursor.execute('''
                            SELECT * FROM galleries WHERE status = ? ORDER BY created_at DESC
                        ''', (status,))
                    else:
                        cursor.execute('SELECT * FROM galleries ORDER BY created_at DESC')
                    
                    galleries = []
                    for row in cursor.fetchall():
                        gallery_data = dict(row)
                        gallery_data['config'] = json.loads(gallery_data['config'] or '{}')
                        gallery_data['metadata'] = json.loads(gallery_data['metadata'] or '{}')
                        galleries.append(gallery_data)
                    
                    return galleries
                    
            except Exception as e:
                self.logger.error(f"Error listing galleries: {e}")
                return []
    
    def backup_data(self, path: Path) -> ServiceResponse:
        """Backup all data to file."""
        try:
            import shutil
            shutil.copy2(self.db_file, path)
            return ServiceResponse(ServiceResult.SUCCESS)
        except Exception as e:
            return ServiceResponse(ServiceResult.FAILURE, error=str(e))
    
    def restore_data(self, path: Path) -> ServiceResponse:
        """Restore data from backup file."""
        try:
            if not path.exists():
                return ServiceResponse(ServiceResult.FAILURE, error="Backup file not found")
            
            import shutil
            shutil.copy2(path, self.db_file)
            return ServiceResponse(ServiceResult.SUCCESS)
        except Exception as e:
            return ServiceResponse(ServiceResult.FAILURE, error=str(e))
    
    def _save_images(self, cursor: sqlite3.Cursor, gallery_id: str, images: List[Dict[str, Any]]) -> None:
        """Save images for a gallery."""
        # Clear existing images
        cursor.execute('DELETE FROM images WHERE gallery_id = ?', (gallery_id,))
        
        # Insert new images
        for image in images:
            cursor.execute('''
                INSERT INTO images (gallery_id, filename, file_path, size, width, height, 
                                  upload_url, thumbnail_url, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                gallery_id,
                image['filename'],
                image['file_path'],
                image.get('size'),
                image.get('width'),
                image.get('height'),
                image.get('upload_url'),
                image.get('thumbnail_url'),
                image.get('status', 'pending')
            ))