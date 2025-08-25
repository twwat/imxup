#!/usr/bin/env python3
"""
Tab Manager for coordinating between database tab definitions and user preferences.

Responsibilities:
- Coordinate between QueueStore (tab definitions) and QSettings (user preferences)  
- Manage tab visibility, ordering, and auto-archive preferences
- Provide unified API for tab operations with preference persistence
- Handle orphaned preferences cleanup and graceful fallbacks
- Support multiple user profiles sharing same database

Architecture Principles:
- Database: Tab definitions, gallery assignments (shared across users)
- QSettings: User-specific preferences (last active tab, visibility, auto-archive)
- Single source of truth: TabManager coordinates both sources
- Performance: Preferences loaded once at startup, updated incrementally
- Graceful degradation: Missing preferences use sensible defaults
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Tuple, Any, Set
from dataclasses import dataclass
from PyQt6.QtCore import QObject, QSettings, pyqtSignal

from src.storage.database import QueueStore


@dataclass
class TabPreferences:
    """User-specific tab preferences"""
    last_active_tab: str = "Main"
    hidden_tabs: Set[str] = None
    auto_archive_enabled: bool = False
    auto_archive_days: int = 30
    auto_archive_statuses: Set[str] = None
    custom_display_order: Dict[str, int] = None  # Tab name -> preferred order
    
    def __post_init__(self):
        if self.hidden_tabs is None:
            self.hidden_tabs = set()
        if self.auto_archive_statuses is None:
            self.auto_archive_statuses = {"completed", "failed"}
        if self.custom_display_order is None:
            self.custom_display_order = {}


@dataclass  
class TabInfo:
    """Combined tab information from database and preferences"""
    id: int
    name: str
    tab_type: str  # 'system' or 'user'
    display_order: int
    color_hint: Optional[str]
    created_ts: int
    updated_ts: int
    is_active: bool
    gallery_count: int
    # User preference fields
    is_hidden: bool = False
    preferred_order: Optional[int] = None


class TabManager(QObject):
    """
    Manages tab definitions and user preferences with proper separation of concerns.
    
    Database (QueueStore): Shared tab definitions, gallery assignments
    QSettings: User-specific preferences (visibility, ordering, auto-archive)
    
    Signals:
        tab_created(tab_info): New tab created
        tab_updated(tab_info): Tab definition or preferences updated  
        tab_deleted(tab_name, reassign_to): Tab deleted and galleries reassigned
        tabs_reordered(): Tab display order changed
        auto_archive_triggered(gallery_paths): Galleries auto-archived
    """
    
    # Signals
    tab_created = pyqtSignal(object)  # TabInfo
    tab_updated = pyqtSignal(object)  # TabInfo  
    tab_deleted = pyqtSignal(str, str)  # (deleted_tab_name, reassign_to)
    tabs_reordered = pyqtSignal()
    auto_archive_triggered = pyqtSignal(list)  # List[str] gallery paths
    
    def __init__(self, queue_store: QueueStore, settings_org: str = "ImxUploader", settings_app: str = "TabManager"):
        """
        Initialize TabManager with database store and settings.
        
        Args:
            queue_store: QueueStore instance for database operations
            settings_org: QSettings organization name
            settings_app: QSettings application name
        """
        super().__init__()
        
        self._store = queue_store
        self._settings = QSettings(settings_org, settings_app)
        self._preferences = TabPreferences()
        self._last_load_time = 0
        self._cached_tabs: Dict[str, TabInfo] = {}
        
        # Performance optimizations for memory management
        self._gallery_cache: Dict[str, List[Dict[str, Any]]] = {}  # Cache tab galleries
        self._cache_timestamps: Dict[str, float] = {}  # Track cache freshness
        self._cache_max_size = 100  # Maximum cached tabs
        self._cache_ttl = 30.0  # Cache time-to-live in seconds
        
        # Load preferences from QSettings
        self._load_preferences()
        
        # Initialize default tabs if needed
        self._store.initialize_default_tabs()
        
        # Clean up orphaned preferences
        self._cleanup_orphaned_preferences()
    
    # ----------------------------- Core Properties -----------------------------
    
    @property
    def last_active_tab(self) -> str:
        """Get the last active tab name"""
        return self._preferences.last_active_tab
    
    @last_active_tab.setter  
    def last_active_tab(self, tab_name: str) -> None:
        """Set the last active tab and persist to settings"""
        if tab_name and tab_name != self._preferences.last_active_tab:
            self._preferences.last_active_tab = tab_name
            self._settings.setValue("preferences/last_active_tab", tab_name)
    
    @property
    def auto_archive_enabled(self) -> bool:
        """Get auto-archive enabled state"""
        return self._preferences.auto_archive_enabled
    
    @auto_archive_enabled.setter
    def auto_archive_enabled(self, enabled: bool) -> None:
        """Set auto-archive enabled state and persist"""
        if enabled != self._preferences.auto_archive_enabled:
            self._preferences.auto_archive_enabled = enabled
            self._settings.setValue("preferences/auto_archive_enabled", enabled)
    
    @property
    def auto_archive_days(self) -> int:
        """Get auto-archive days threshold"""
        return self._preferences.auto_archive_days
    
    @auto_archive_days.setter
    def auto_archive_days(self, days: int) -> None:
        """Set auto-archive days threshold and persist"""
        if days > 0 and days != self._preferences.auto_archive_days:
            self._preferences.auto_archive_days = days
            self._settings.setValue("preferences/auto_archive_days", days)
    
    # ----------------------------- Tab Information -----------------------------
    
    def get_all_tabs(self, include_hidden: bool = False) -> List[TabInfo]:
        """
        Get all tabs with combined database and preference information.
        
        Args:
            include_hidden: Whether to include tabs marked as hidden
            
        Returns:
            List of TabInfo objects sorted by display order
        """
        # Get fresh data from database
        db_tabs = self._store.get_all_tabs()
        gallery_counts = self._store.get_tab_gallery_counts()
        
        combined_tabs = []
        for db_tab in db_tabs:
            tab_name = db_tab['name']
            
            # Skip hidden tabs unless requested
            if not include_hidden and tab_name in self._preferences.hidden_tabs:
                continue
                
            tab_info = TabInfo(
                id=db_tab['id'],
                name=tab_name,
                tab_type=db_tab['tab_type'], 
                display_order=db_tab['display_order'],
                color_hint=db_tab['color_hint'],
                created_ts=db_tab['created_ts'],
                updated_ts=db_tab['updated_ts'],
                is_active=db_tab['is_active'],
                gallery_count=gallery_counts.get(tab_name, 0),
                is_hidden=tab_name in self._preferences.hidden_tabs,
                preferred_order=self._preferences.custom_display_order.get(tab_name)
            )
            combined_tabs.append(tab_info)
        
        # Apply custom ordering if specified
        return self._apply_custom_ordering(combined_tabs)
    
    def get_tab_by_name(self, tab_name: str) -> Optional[TabInfo]:
        """Get specific tab by name with combined information"""
        tabs = self.get_all_tabs(include_hidden=True)
        return next((tab for tab in tabs if tab.name == tab_name), None)
    
    def get_visible_tab_names(self) -> List[str]:
        """Get list of visible tab names in display order"""
        return [tab.name for tab in self.get_all_tabs(include_hidden=False)]
    
    def get_tab_gallery_counts(self) -> Dict[str, int]:
        """Get gallery counts for all visible tabs"""
        tabs = self.get_all_tabs(include_hidden=False)
        return {tab.name: tab.gallery_count for tab in tabs}
    
    # ----------------------------- Tab Operations -----------------------------
    
    def create_tab(self, name: str, color_hint: Optional[str] = None, display_order: Optional[int] = None) -> TabInfo:
        """
        Create new user tab with default preferences.
        
        Args:
            name: Tab name (must be unique)
            color_hint: Optional hex color code
            display_order: Optional display order (auto-calculated if None)
            
        Returns:
            TabInfo object for created tab
            
        Raises:
            ValueError: If tab name already exists or is invalid
        """
        if not name or not name.strip():
            raise ValueError("Tab name cannot be empty")
            
        # Create in database
        tab_id = self._store.create_tab(name.strip(), color_hint, display_order)
        
        # Get the created tab info
        tab_info = self.get_tab_by_name(name.strip())
        if not tab_info:
            raise ValueError(f"Failed to retrieve created tab '{name}'")
        
        # Initialize default preferences for new tab
        # (No special preferences needed - defaults are handled in get_all_tabs)
        
        self.tab_created.emit(tab_info)
        return tab_info
    
    def update_tab(self, tab_name: str, new_name: Optional[str] = None, 
                   color_hint: Optional[str] = None, display_order: Optional[int] = None) -> bool:
        """
        Update tab definition in database.
        
        Args:
            tab_name: Current tab name
            new_name: New name (optional)
            color_hint: New color hint (optional)  
            display_order: New display order (optional)
            
        Returns:
            True if updated successfully
            
        Raises:
            ValueError: If tab not found or update invalid
        """
        tab_info = self.get_tab_by_name(tab_name)
        if not tab_info:
            raise ValueError(f"Tab '{tab_name}' not found")
        
        # Update in database
        success = self._store.update_tab(
            tab_info.id, 
            name=new_name,
            color_hint=color_hint,
            display_order=display_order
        )
        
        if success:
            # Handle preference updates if name changed
            if new_name and new_name != tab_name:
                self._handle_tab_rename(tab_name, new_name)
            
            # Get updated tab info and emit signal
            updated_tab = self.get_tab_by_name(new_name or tab_name)
            if updated_tab:
                self.tab_updated.emit(updated_tab)
        
        return success
    
    def rename_tab(self, old_name: str, new_name: str) -> bool:
        """
        Rename a tab (convenience method for update_tab).
        
        Args:
            old_name: Current tab name
            new_name: New tab name
            
        Returns:
            True if renamed successfully
            
        Raises:
            ValueError: If tab not found or name invalid
        """
        return self.update_tab(old_name, new_name=new_name)
    
    def delete_tab(self, tab_name: str, reassign_to: str = "Main") -> Tuple[bool, int]:
        """
        Delete tab and reassign galleries, cleaning up preferences.
        
        Args:
            tab_name: Name of tab to delete
            reassign_to: Tab to reassign galleries to
            
        Returns:
            Tuple of (success, galleries_reassigned_count)
            
        Raises:
            ValueError: If trying to delete system tab or invalid parameters
        """
        tab_info = self.get_tab_by_name(tab_name)
        if not tab_info:
            raise ValueError(f"Tab '{tab_name}' not found")
        
        # Delete from database
        success, gallery_count = self._store.delete_tab(tab_info.id, reassign_to)
        
        if success:
            # Clean up preferences for deleted tab
            self._cleanup_tab_preferences(tab_name)
            
            # Update last active tab if needed
            if self._preferences.last_active_tab == tab_name:
                self.last_active_tab = reassign_to
            
            self.tab_deleted.emit(tab_name, reassign_to)
        
        return success, gallery_count
    
    # ----------------------------- Tab Preferences -----------------------------
    
    def set_tab_hidden(self, tab_name: str, hidden: bool) -> None:
        """Show or hide a tab"""
        if hidden:
            self._preferences.hidden_tabs.add(tab_name)
        else:
            self._preferences.hidden_tabs.discard(tab_name)
        
        # Persist to settings
        hidden_list = list(self._preferences.hidden_tabs)
        self._settings.setValue("preferences/hidden_tabs", hidden_list)
        
        # Update last active tab if hiding current tab
        if hidden and self._preferences.last_active_tab == tab_name:
            visible_tabs = self.get_visible_tab_names()
            if visible_tabs:
                self.last_active_tab = visible_tabs[0]
    
    def is_tab_hidden(self, tab_name: str) -> bool:
        """Check if tab is hidden"""
        return tab_name in self._preferences.hidden_tabs
    
    def set_custom_tab_order(self, tab_order: Dict[str, int]) -> None:
        """
        Set custom display order for tabs.
        
        Args:
            tab_order: Dict mapping tab_name -> preferred_order
        """
        self._preferences.custom_display_order.update(tab_order)
        
        # Convert to QSettings-compatible format
        order_items = [f"{name}:{order}" for name, order in tab_order.items()]
        self._settings.setValue("preferences/custom_tab_order", order_items)
        
        self.tabs_reordered.emit()
    
    def get_custom_tab_order(self) -> Dict[str, int]:
        """Get current custom tab ordering"""
        return self._preferences.custom_display_order.copy()
    
    def reset_tab_order(self) -> None:
        """Reset to database default ordering"""
        self._preferences.custom_display_order.clear()
        self._settings.remove("preferences/custom_tab_order")
        self.tabs_reordered.emit()
    
    # ----------------------------- Auto-Archive -----------------------------
    
    def set_auto_archive_config(self, enabled: bool, days: int, statuses: Set[str]) -> None:
        """
        Configure auto-archive settings.
        
        Args:
            enabled: Whether auto-archive is enabled
            days: Days threshold for auto-archiving
            statuses: Gallery statuses to auto-archive
        """
        self.auto_archive_enabled = enabled
        self.auto_archive_days = days
        self._preferences.auto_archive_statuses = statuses.copy()
        
        # Persist statuses
        self._settings.setValue("preferences/auto_archive_statuses", list(statuses))
    
    def get_auto_archive_config(self) -> Tuple[bool, int, Set[str]]:
        """Get current auto-archive configuration"""
        return (
            self._preferences.auto_archive_enabled,
            self._preferences.auto_archive_days, 
            self._preferences.auto_archive_statuses.copy()
        )
    
    def check_auto_archive_candidates(self) -> List[str]:
        """
        Find galleries that should be auto-archived.
        
        Returns:
            List of gallery paths that meet auto-archive criteria
        """
        if not self._preferences.auto_archive_enabled:
            return []
        
        # Get galleries from all tabs except Archive
        all_items = self._store.load_all_items()
        current_time = int(time.time())
        days_threshold = self._preferences.auto_archive_days * 24 * 3600  # Convert to seconds
        
        candidates = []
        for item in all_items:
            # Skip if already in Archive tab
            if item.get('tab_name', 'Main') == 'Archive':
                continue
                
            # Check status criteria
            status = item.get('status', '')
            if status not in self._preferences.auto_archive_statuses:
                continue
                
            # Check time criteria (use finished_time if available, otherwise added_time)
            check_time = item.get('finished_time') or item.get('added_time', 0)
            if check_time and (current_time - check_time) >= days_threshold:
                candidates.append(item['path'])
        
        return candidates
    
    def execute_auto_archive(self) -> int:
        """
        Execute auto-archive operation.
        
        Returns:
            Number of galleries moved to Archive
        """
        candidates = self.check_auto_archive_candidates()
        if not candidates:
            return 0
        
        # Move galleries to Archive tab
        moved_count = self._store.move_galleries_to_tab(candidates, 'Archive')
        
        if moved_count > 0:
            self.auto_archive_triggered.emit(candidates[:moved_count])
        
        return moved_count
    
    # ----------------------------- Gallery Operations -----------------------------
    
    def move_galleries_to_tab(self, gallery_paths: List[str], new_tab_name: str) -> int:
        """
        Move galleries to different tab.
        
        Args:
            gallery_paths: List of gallery paths to move
            new_tab_name: Destination tab name
            
        Returns:
            Number of galleries moved
        """
        return self._store.move_galleries_to_tab(gallery_paths, new_tab_name)
    
    def load_tab_galleries(self, tab_name: str) -> List[Dict[str, Any]]:
        """Load galleries for specific tab with intelligent caching"""
        current_time = time.time()
        
        # Check if we have fresh cached data
        if (tab_name in self._gallery_cache and 
            tab_name in self._cache_timestamps and
            current_time - self._cache_timestamps[tab_name] < self._cache_ttl):
            return self._gallery_cache[tab_name]
        
        # Load from database
        galleries = self._store.load_items_by_tab(tab_name)
        
        # Update cache with memory management
        self._update_gallery_cache(tab_name, galleries, current_time)
        
        return galleries
        
    def _update_gallery_cache(self, tab_name: str, galleries: List[Dict[str, Any]], timestamp: float) -> None:
        """Update gallery cache with memory management"""
        # Clean old entries if cache is getting too large
        if len(self._gallery_cache) >= self._cache_max_size:
            self._cleanup_cache()
        
        # Store the new data
        self._gallery_cache[tab_name] = galleries
        self._cache_timestamps[tab_name] = timestamp
        
    def _cleanup_cache(self) -> None:
        """Clean up old cache entries to free memory"""
        current_time = time.time()
        
        # Remove expired entries
        expired_tabs = []
        for tab_name, timestamp in self._cache_timestamps.items():
            if current_time - timestamp > self._cache_ttl:
                expired_tabs.append(tab_name)
        
        for tab_name in expired_tabs:
            self._gallery_cache.pop(tab_name, None)
            self._cache_timestamps.pop(tab_name, None)
        
        # If still too many entries, remove oldest
        if len(self._gallery_cache) >= self._cache_max_size:
            # Sort by timestamp and remove oldest half
            sorted_tabs = sorted(self._cache_timestamps.items(), key=lambda x: x[1])
            tabs_to_remove = [tab for tab, _ in sorted_tabs[:len(sorted_tabs)//2]]
            
            for tab_name in tabs_to_remove:
                self._gallery_cache.pop(tab_name, None)
                self._cache_timestamps.pop(tab_name, None)
                
    def invalidate_tab_cache(self, tab_name: str = None) -> None:
        """Invalidate cache for specific tab or all tabs"""
        if tab_name:
            self._gallery_cache.pop(tab_name, None)
            self._cache_timestamps.pop(tab_name, None)
        else:
            self._gallery_cache.clear()
            self._cache_timestamps.clear()
    
    # ----------------------------- Private Methods -----------------------------
    
    def _load_preferences(self) -> None:
        """Load user preferences from QSettings"""
        # Last active tab
        self._preferences.last_active_tab = self._settings.value(
            "preferences/last_active_tab", "Main", type=str
        )
        
        # Hidden tabs
        hidden_list = self._settings.value("preferences/hidden_tabs", [], type=list)
        self._preferences.hidden_tabs = set(hidden_list) if hidden_list else set()
        
        # Auto-archive settings
        self._preferences.auto_archive_enabled = self._settings.value(
            "preferences/auto_archive_enabled", False, type=bool
        )
        self._preferences.auto_archive_days = self._settings.value(
            "preferences/auto_archive_days", 30, type=int
        )
        status_list = self._settings.value("preferences/auto_archive_statuses", 
                                          ["completed", "failed"], type=list)
        self._preferences.auto_archive_statuses = set(status_list) if status_list else {"completed", "failed"}
        
        # Custom tab ordering
        order_items = self._settings.value("preferences/custom_tab_order", [], type=list)
        self._preferences.custom_display_order = {}
        for item in order_items or []:
            try:
                name, order = item.split(':', 1)
                self._preferences.custom_display_order[name] = int(order)
            except (ValueError, AttributeError):
                continue  # Skip malformed entries
    
    def _apply_custom_ordering(self, tabs: List[TabInfo]) -> List[TabInfo]:
        """Apply custom user ordering to tab list"""
        if not self._preferences.custom_display_order:
            # Use database ordering
            return sorted(tabs, key=lambda t: (t.display_order, t.created_ts))
        
        def sort_key(tab: TabInfo) -> Tuple[int, int, int]:
            # Priority: custom_order (if set), database order, creation time
            custom_order = self._preferences.custom_display_order.get(tab.name)
            if custom_order is not None:
                return (0, custom_order, tab.created_ts)  # Custom ordering takes precedence
            else:
                return (1, tab.display_order, tab.created_ts)  # Fall back to database order
        
        return sorted(tabs, key=sort_key)
    
    def _handle_tab_rename(self, old_name: str, new_name: str) -> None:
        """Update preferences when tab is renamed"""
        # Update last active tab
        if self._preferences.last_active_tab == old_name:
            self.last_active_tab = new_name
        
        # Update hidden tabs
        if old_name in self._preferences.hidden_tabs:
            self._preferences.hidden_tabs.remove(old_name)
            self._preferences.hidden_tabs.add(new_name)
            hidden_list = list(self._preferences.hidden_tabs)
            self._settings.setValue("preferences/hidden_tabs", hidden_list)
        
        # Update custom ordering
        if old_name in self._preferences.custom_display_order:
            order = self._preferences.custom_display_order.pop(old_name)
            self._preferences.custom_display_order[new_name] = order
            order_items = [f"{name}:{order}" for name, order in self._preferences.custom_display_order.items()]
            self._settings.setValue("preferences/custom_tab_order", order_items)
    
    def _cleanup_tab_preferences(self, tab_name: str) -> None:
        """Clean up preferences for deleted tab"""
        # Remove from hidden tabs
        if tab_name in self._preferences.hidden_tabs:
            self._preferences.hidden_tabs.remove(tab_name)
            hidden_list = list(self._preferences.hidden_tabs)
            self._settings.setValue("preferences/hidden_tabs", hidden_list)
        
        # Remove from custom ordering
        if tab_name in self._preferences.custom_display_order:
            del self._preferences.custom_display_order[tab_name]
            order_items = [f"{name}:{order}" for name, order in self._preferences.custom_display_order.items()]
            self._settings.setValue("preferences/custom_tab_order", order_items)
    
    def _cleanup_orphaned_preferences(self) -> None:
        """Remove preferences for tabs that no longer exist"""
        try:
            db_tabs = self._store.get_all_tabs()
            valid_tab_names = {tab['name'] for tab in db_tabs}
            
            # Clean up hidden tabs
            orphaned_hidden = self._preferences.hidden_tabs - valid_tab_names
            if orphaned_hidden:
                self._preferences.hidden_tabs -= orphaned_hidden
                hidden_list = list(self._preferences.hidden_tabs)
                self._settings.setValue("preferences/hidden_tabs", hidden_list)
            
            # Clean up custom ordering
            orphaned_orders = set(self._preferences.custom_display_order.keys()) - valid_tab_names
            if orphaned_orders:
                for name in orphaned_orders:
                    del self._preferences.custom_display_order[name]
                order_items = [f"{name}:{order}" for name, order in self._preferences.custom_display_order.items()]
                self._settings.setValue("preferences/custom_tab_order", order_items)
            
            # Validate last active tab
            if self._preferences.last_active_tab not in valid_tab_names:
                # Fall back to Main, or first available tab
                if "Main" in valid_tab_names:
                    self.last_active_tab = "Main"
                elif valid_tab_names:
                    self.last_active_tab = sorted(valid_tab_names)[0]
                    
        except Exception as e:
            # Graceful degradation - log error but don't crash
            print(f"Warning: Failed to cleanup orphaned preferences: {e}")