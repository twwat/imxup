"""
Icon Manager for ImxUp application.
Centralized management of all application icons with validation and clear mappings.
"""

import os
from typing import Dict, Optional, List, Set, Union
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QStyle

from src.utils.logger import log


class IconManager:
    """Centralized icon management with validation and clear mappings."""
    
    # Hybrid icon mapping: string for auto-invert, list for manual light/dark pairs
    ICON_MAP = {
        # Status icons           Light icon                      Dark icon
        'status_completed':     ['status_completed-light.png',  'status_completed-dark.png'],
        'status_failed':        ['status_failed-light.png',     'status_failed-dark.png'],
        'status_uploading':     ['status_uploading-light.png',  'status_uploading-dark.png'],  # Fallback for single frame

        # Multi-frame uploading animation (7 frames, light/dark variants)
        'status_uploading_frame_0': ['status_uploading-001-light.png', 'status_uploading-001-dark.png'],
        'status_uploading_frame_1': ['status_uploading-002-light.png', 'status_uploading-002-dark.png'],
        'status_uploading_frame_2': ['status_uploading-003-light.png', 'status_uploading-003-dark.png'],

        'status_paused':        ['status_paused-light.png',     'status_paused-dark.png'],
        'status_queued':        ['status_queued-light.png',     'status_queued-dark.png'],
        'status_ready':         ['status_ready-light.png',      'status_ready-dark.png'],
        'status_pending':       ['status_pending-light.png',    'status_pending-dark.png'],
        'status_incomplete':    ['status_incomplete-light.png', 'status_incomplete-dark.png'],
        'status_scan_failed':   ['status_scan_failed-light.png','status_scan_failed-dark.png'],
        'status_upload_failed': ['status_error-light.png',      'status_error-dark.png'],
        'status_error':         ['status_error-light.png',      'status_error-dark.png'],
        'status_idle':          ['status_ready-light.png',      'status_ready-dark.png'],  # Reuse ready icons for idle state
        'status_scanning':      ['status_scanning-light.png',   'status_scanning-dark.png'],
        'status_validating':    ['status_validating-light.png', 'status_validating-dark.png'],

        # Action button icons    Light icon                      Dark icon
        'action_start':         ['action_start-light.png',      'action_start-dark.png'],
        'action_stop':          ['action_stop-light.png',       'action_stop-dark.png'],
        'action_view':          ['action_view-light.png',       'action_view-dark.png'],
        'action_view_error':    ['action_view_error-light.png', 'action_view_error-dark.png'],
        'action_cancel':        ['action_cancel-light.png',     'action_cancel-dark.png'],
        'action_resume':        ['action_resume-light.png',     'action_resume-dark.png'],

        # Rename status icons
        'renamed_true':         ['renamed_true-light.png',      'renamed_true-dark.png'],
        'renamed_false':        ['renamed_false-light.png',     'renamed_false-dark.png'],

        # File host
        'host_enabled':         ['host_enabled-light.png',      'host_enabled-dark.png'],
        'host_disabled':        ['host_disabled-light.png',     'host_disabled-dark.png'],
        'imx':                  ['imx-light.png',               'imx-dark.png'],
        'auto':                 ['auto-light.png',              'auto-dark.png'],
        'auto-disabled':        ['auto-disabled-light.png',     'auto-disabled-dark.png'],
        'disabledhost':         ['disabledhost-dark.png',       'disabledhost-light.png'],

        # UI element icons / Quick Settings
        'settings':             ['settings-light.png',          'settings-dark.png'],
        'templates':            ['templates-light.png',         'templates-dark.png'],
        'credentials':          ['credentials-light.png',       'credentials-dark.png'],
        'filehosts':            ['filehosts-light.png',         'filehosts-dark.png'],
        'help':                 ['help-light.png',              'help-dark.png'],
        'hooks':                ['hooks-light.png',             'hooks-dark.png'],
        'scan':                 ['scan-light.png',              'scan-dark.png'],
        'toggle_theme':         ['toggle_theme-light.png',      'toggle_theme-dark.png'],
        'statistics':           ['statistics-light.png',        'statistics-dark.png'],
        'log_viewer':           ['log_viewer-light.png',        'log_viewer-dark.png'],
        'radio_check':          ['radio_check-light.png',       'radio_check-dark.png'],
        'check':                ['check-light.png',             'check-dark.png'],
        'checkbox_check':       ['checkbox_check-light.png',    'checkbox_check-dark.png'],
        'main_window':          ['imxup-main-icon.png', 'imxup-main-icon.png'],
        'app_icon':             'imxup.ico',
        # Alternative sizes (optional)
    }

    # Qt standard icon fallbacks (explicit, not hidden)
    QT_FALLBACKS = {
        'status_completed': QStyle.StandardPixmap.SP_DialogApplyButton,
        'status_failed': QStyle.StandardPixmap.SP_DialogCancelButton,
        'status_scan_failed': QStyle.StandardPixmap.SP_MessageBoxWarning,
        'status_upload_failed': QStyle.StandardPixmap.SP_MessageBoxCritical,
        'status_uploading': QStyle.StandardPixmap.SP_MediaPlay,
        'status_paused': QStyle.StandardPixmap.SP_MediaPause,
        'status_ready': QStyle.StandardPixmap.SP_DialogOkButton,
        'status_pending': QStyle.StandardPixmap.SP_FileIcon,
        'status_incomplete': QStyle.StandardPixmap.SP_BrowserReload,
        'status_scanning': QStyle.StandardPixmap.SP_BrowserReload,
        'status_queued': QStyle.StandardPixmap.SP_FileIcon,
        'status_error': QStyle.StandardPixmap.SP_MessageBoxCritical,
        'status_idle': QStyle.StandardPixmap.SP_FileIcon,
        
        'action_start': QStyle.StandardPixmap.SP_MediaPlay,
        'action_stop': QStyle.StandardPixmap.SP_MediaStop,
        'action_view': QStyle.StandardPixmap.SP_DirOpenIcon,
        'action_view_error': QStyle.StandardPixmap.SP_MessageBoxWarning,
        'action_cancel': QStyle.StandardPixmap.SP_DialogCancelButton,
        'action_resume': QStyle.StandardPixmap.SP_MediaPlay,
        
        'renamed_true': QStyle.StandardPixmap.SP_DialogApplyButton,
        'renamed_false': QStyle.StandardPixmap.SP_ComputerIcon,
    }
    
    def __init__(self, assets_dir: str):
        """Initialize the icon manager with the assets directory path."""
        self.assets_dir = assets_dir
        self._icon_cache: Dict[str, QIcon] = {}
        self._missing_icons: Set[str] = set()
        self._validated = False

        # Cache statistics for performance monitoring
        self._cache_hits = 0
        self._cache_misses = 0
        self._disk_loads = 0

        # Force convert status icons to use dark variants since they exist
        #status_conversions = {
        #    'status_completed':     ['status_completed-light.png',  'status_completed-dark.png'],
        #    'status_failed':        ['status_failed-light.png',     'status_failed-dark.png'], 
        #    'status_uploading':     ['status_uploading-light.png',  'status_uploading-dark.png'],
        #    'status_paused':        ['status_paused-light.png',     'status_paused-dark.png'],
        #    'status_queued':        ['status_queued-light.png',     'status_queued-dark.png'],
        #    'status_ready':         ['status_ready-light.png',      'status_ready-dark.png'],
        #    'status_pending':       ['status_pending-light.png',    'status_pending-dark.png'],
        #    'status_incomplete':    ['status_incomplete-light.png', 'status_incomplete-dark.png'],
        #    'status_scan_failed':   ['status_scan_failed-light.png','status_scan_failed-dark.png'],
        #    'status_upload_failed': ['status_error-light.png',      'status_error-dark.png'],
        #    'status_scanning':      ['status_scanning-light.png',   'status_scanning-dark.png'],
        #}
        # 
        #for key, config in status_conversions.items():
        #    if key in self.ICON_MAP:
        #        self.ICON_MAP[key] = config
        
        # Debug: show final config state
        #print(f"DEBUG: Icon configs after auto-generation:")
        #for key, config in self.ICON_MAP.items():
        #    if key.startswith('status_'):
        #        print(f"  {key}: {type(config)} = {config}")
        
    # Legacy name mapping for backward compatibility
    LEGACY_ICON_MAP = {
        'completed': 'status_completed',
        'failed': 'status_failed',
        'uploading': 'status_uploading',
        'paused': 'status_paused',
        'ready': 'status_ready',
        'pending': 'status_pending',
        'scan_failed': 'status_scan_failed',
        'incomplete': 'status_incomplete',
        'start': 'action_start',
        'stop': 'action_stop',
        'view': 'action_view',
        'view_error': 'action_view_error',
        'cancel': 'action_cancel',
        'templates': 'templates',
        'credentials': 'credentials',
        'main_window': 'main_window',
        'renamed_true': 'renamed_true',
        'renamed_false': 'renamed_false',
    }

    def get_icon(self, icon_key: str, theme_mode: Optional[str] = None, is_selected: bool = False, requested_size: int = 32) -> QIcon:
        """
        Get an icon by its key with theme and selection awareness.

        Args:
            icon_key: The icon identifier (e.g., 'status_completed', 'action_start', or legacy 'completed', 'start')
            theme_mode: Theme mode string ('light', 'dark', or None for auto-detect from palette)
            is_selected: Whether the icon is for a selected table row
            requested_size: Size to generate inverted icons at (for quality)

        Returns:
            QIcon object (may be null if not found and no fallback)
        """
        # Handle legacy icon names
        if icon_key in self.LEGACY_ICON_MAP:
            icon_key = self.LEGACY_ICON_MAP[icon_key]

        # Auto-detect theme if not provided
        if theme_mode is None:
            from PyQt6.QtWidgets import QApplication
            from typing import cast
            app_instance = QApplication.instance()
            if app_instance:
                app = cast(QApplication, app_instance)
                palette = app.palette()
                window_color = palette.color(palette.ColorRole.Window)
                theme_mode = 'dark' if window_color.lightness() < 128 else 'light'
            else:
                theme_mode = 'dark'

        # Create cache key that includes theme/selection state and size
        cache_key = f"{icon_key}_{theme_mode}_{is_selected}_{requested_size}"

        # Check cache first
        if cache_key in self._icon_cache:
            self._cache_hits += 1
            return self._icon_cache[cache_key]

        # Cache miss - will need to load from disk
        self._cache_misses += 1

        # Get the configuration from our map
        if icon_key not in self.ICON_MAP:
            log(f"Unknown icon key '{icon_key}'", level="warning", category="ui")
            # Try Qt standard fallback
            if icon_key in self.QT_FALLBACKS:
                from PyQt6.QtWidgets import QApplication
                from typing import cast
                app_instance = QApplication.instance()
                if app_instance:
                    app = cast(QApplication, app_instance)
                    style = app.style()
                    if style:
                        fallback_pixmap = self.QT_FALLBACKS[icon_key]
                        icon = style.standardIcon(fallback_pixmap)
                        self._icon_cache[cache_key] = icon
                        return icon
            return QIcon()

        config = self.ICON_MAP[icon_key]

        # Determine which icon file to use
        # Convert to list if it's a list type for proper type handling
        config_value: Union[str, List[str]] = list(config) if isinstance(config, list) else config
        filename = self._get_themed_filename(config_value, theme_mode, is_selected)
        if not filename:
            return QIcon()

        icon_path = os.path.join(self.assets_dir, filename)

        # Try to load the icon
        if os.path.exists(icon_path):
            self._disk_loads += 1
            icon = QIcon(icon_path)
            if not icon.isNull():
                self._icon_cache[cache_key] = icon
                return icon

        # Record missing icon
        self._missing_icons.add(icon_key)

        # Use Qt standard icon fallback if available
        if icon_key in self.QT_FALLBACKS:
            from PyQt6.QtWidgets import QApplication
            from typing import cast
            app_instance = QApplication.instance()
            if app_instance:
                app = cast(QApplication, app_instance)
                style = app.style()
                if style:
                    fallback_pixmap = self.QT_FALLBACKS[icon_key]
                    icon = style.standardIcon(fallback_pixmap)
                    self._icon_cache[cache_key] = icon
                    return icon

        # Return empty icon as last resort
        return QIcon()
    
    def _get_themed_filename(self, config: Union[str, List[str]], theme_mode: str, is_selected: bool) -> Optional[str]:
        """
        Get the appropriate filename based on theme and selection state.

        Args:
            config: Icon configuration (string or [light, dark] list)
            theme_mode: Current theme mode ('light' or 'dark')
            is_selected: Whether icon is for selected row

        Returns:
            Filename to use, or None if invalid config
        """
        if isinstance(config, str):
            # Single icon - return as-is
            return config
        elif isinstance(config, list) and len(config) >= 2:
            # Manual light/dark pair
            # Logic:
            # - Always use icon matching the current theme (light icon for light theme, dark icon for dark theme)
            # - Selection state does not change icon choice
            return config[0] if theme_mode == 'light' else config[1]
        else:
            log(f"Invalid icon configuration: {config}", level="warning", category="ui")
            return None
    
    def get_status_icon(self, status: str, theme_mode: Optional[str] = None, is_selected: bool = False, requested_size: int = 32, animation_frame: int = 0) -> QIcon:
        """
        Get icon for a specific status with theme/selection awareness.

        Args:
            status: Status string (e.g., 'completed', 'uploading')
            theme_mode: Theme mode string ('light', 'dark', or None for auto-detect)
            is_selected: Whether icon is for selected row
            requested_size: Size to generate inverted icons at (for quality)
            animation_frame: Frame number for animated icons (0-3 for uploading)

        Returns:
            QIcon object
        """
        # Use frame-based icon for uploading status (all frames, including 0)
        if status == 'uploading':
            icon_key = f'status_uploading_frame_{animation_frame % 3}'
        else:
            icon_key = f'status_{status}'

        return self.get_icon(icon_key, theme_mode, is_selected, requested_size)

    def get_action_icon(self, action: str, theme_mode: Optional[str] = None, is_selected: bool = False) -> QIcon:
        """
        Get icon for an action button with theme/selection awareness.

        Args:
            action: Action name (e.g., 'start', 'stop')
            theme_mode: Theme mode string ('light', 'dark', or None for auto-detect)
            is_selected: Whether icon is for selected row

        Returns:
            QIcon object
        """
        icon_key = f'action_{action}'
        return self.get_icon(icon_key, theme_mode, is_selected)

    def get_file_host_icon(self, host_name: str, dimmed: bool = False) -> QIcon:
        """
        Get icon for a file host with caching and fallback chain.

        Args:
            host_name: Name of the file host (e.g., 'imx', 'pixhost')
            dimmed: If True, load dimmed variant of the icon

        Returns:
            QIcon object (fallback to action_view icon if not found)
        """
        # Input validation for security
        if not host_name or not isinstance(host_name, str):
            log(f"Invalid host_name: {host_name}", level="warning", category="icon_manager")
            return self.get_icon('action_view')

        # Sanitize: only allow alphanumeric, hyphen, underscore, dot
        import re
        if not re.match(r'^[a-zA-Z0-9._-]+$', host_name):
            log(f"Invalid characters in host_name: {host_name}", level="warning", category="icon_manager")
            return self.get_icon('action_view')

        # Prevent directory traversal
        if '..' in host_name or len(host_name) > 100:
            log(f"Potentially malicious host_name: {host_name}", level="warning", category="icon_manager")
            return self.get_icon('action_view')

        # Create cache key
        cache_key = f"file_host_{host_name}_{'dim' if dimmed else 'color'}"

        # Check cache first
        if cache_key in self._icon_cache:
            self._cache_hits += 1
            return self._icon_cache[cache_key]

        # Cache miss
        self._cache_misses += 1

        try:
            # Build fallback chain
            icon_paths = []

            if dimmed:
                # Try dimmed variant first
                dimmed_path = os.path.join(self.assets_dir, 'hosts', 'logo', f'{host_name}-icon-dim.png')
                icon_paths.append(dimmed_path)

            # Try color/normal variant
            color_path = os.path.join(self.assets_dir, 'hosts', 'logo', f'{host_name}-icon.png')
            icon_paths.append(color_path)

            # Try legacy path
            legacy_path = os.path.join(self.assets_dir, 'hosts', 'logo', f'{host_name}.png')
            icon_paths.append(legacy_path)

            # Try each path in the fallback chain
            for icon_path in icon_paths:
                if os.path.exists(icon_path):
                    self._disk_loads += 1
                    icon = QIcon(icon_path)
                    if not icon.isNull():
                        self._icon_cache[cache_key] = icon
                        return icon

            # No icon found - log warning
            log(f"File host icon not found for '{host_name}' (dimmed={dimmed})", level="warning", category="icon_manager")
            self._missing_icons.add(f"file_host_{host_name}")

        except Exception as e:
            log(f"Error loading file host icon for '{host_name}': {e}", level="error", category="icon_manager")

        # Final fallback - return action_view icon
        fallback_icon = self.get_icon('action_view')
        self._icon_cache[cache_key] = fallback_icon
        return fallback_icon

    def get_file_host_logo_path(self, host_name: str) -> Optional[str]:
        """
        Get the file path for a file host's full logo image.

        This returns the path to the full logo file (e.g., 'rapidgator.png'),
        not the small icon variants. Used for displaying larger logos in UI.

        Args:
            host_name: Name of the file host (e.g., 'imx.to', 'rapidgator', 'fileboom')

        Returns:
            Full path to the logo file if it exists, None otherwise
        """
        # Input validation for security
        if not host_name or not isinstance(host_name, str):
            log(f"Invalid host_name for logo: {host_name}", level="warning", category="icon_manager")
            return None

        # Sanitize: only allow alphanumeric, hyphen, underscore, dot
        import re
        if not re.match(r'^[a-zA-Z0-9._-]+$', host_name):
            log(f"Invalid characters in host_name for logo: {host_name}", level="warning", category="icon_manager")
            return None

        # Prevent directory traversal
        if '..' in host_name or len(host_name) > 100:
            log(f"Potentially malicious host_name for logo: {host_name}", level="warning", category="icon_manager")
            return None

        # Normalize host_name - handle 'imx' -> 'imx.to'
        normalized_name = host_name.lower()
        if normalized_name == 'imx':
            normalized_name = 'imx.to'

        # Build logo path using standard naming convention: {host_name}.png
        logo_path = os.path.join(self.assets_dir, 'hosts', 'logo', f'{normalized_name}.png')

        if os.path.exists(logo_path):
            return logo_path

        log(f"File host logo not found: {logo_path}", level="debug", category="icon_manager")
        return None

    def validate_icons(self, report: bool = True) -> Dict[str, List[str]]:
        """
        Validate that all required icons exist.
        
        Args:
            report: If True, print a report of missing icons
            
        Returns:
            Dictionary with 'missing' and 'found' lists
        """
        missing = []
        found = []
        
        for icon_key, config in self.ICON_MAP.items():
            if isinstance(config, str):
                # Single icon
                icon_path = os.path.join(self.assets_dir, config)
                if os.path.exists(icon_path):
                    found.append(f"{icon_key} -> {config}")
                else:
                    missing.append(f"{icon_key} -> {config}")
            elif isinstance(config, list):
                # Icon pair [light, dark]
                light_path = os.path.join(self.assets_dir, config[0])
                dark_path = os.path.join(self.assets_dir, config[1]) if len(config) > 1 else None
                
                light_exists = os.path.exists(light_path)
                dark_exists = dark_path and os.path.exists(dark_path)
                
                if light_exists and dark_exists:
                    found.append(f"{icon_key} -> {config[0]}, {config[1]}")
                elif light_exists:
                    found.append(f"{icon_key} -> {config[0]} (dark missing: {config[1] if len(config) > 1 else 'N/A'})")
                    if len(config) > 1:
                        missing.append(f"{icon_key} -> {config[1]} (dark variant)")
                else:
                    missing.append(f"{icon_key} -> {config[0]} (light variant)")
                    if dark_path:
                        missing.append(f"{icon_key} -> {config[1]} (dark variant)")
            else:
                missing.append(f"{icon_key} -> INVALID_CONFIG: {config}")
        
        if report and missing:
            print("=" * 60)
            print("ICON VALIDATION REPORT")
            print("=" * 60)
            print(f"Assets directory: {self.assets_dir}")
            print(f"Total icons defined: {len(self.ICON_MAP)}")
            print(f"Icons found: {len(found)}")
            print(f"Icons missing: {len(missing)}")
            
            if missing:
                print("\nMissing icons (will use fallbacks):")
                for item in missing:
                    print(f"  - {item}")
            print("=" * 60)
        
        self._validated = True
        return {'missing': missing, 'found': found}
    
    def get_missing_icons(self) -> List[str]:
        """Get list of icons that were requested but not found."""
        return list(self._missing_icons)
    
    def get_icon_path(self, icon_key: str) -> Optional[str]:
        """
        Get the full path for an icon.
        
        Args:
            icon_key: The icon identifier
            
        Returns:
            Full path to the icon file, or None if not defined
        """
        if icon_key not in self.ICON_MAP:
            return None

        config = self.ICON_MAP[icon_key]
        # Handle both string and list configurations
        if isinstance(config, str):
            filename = config
        elif isinstance(config, list) and len(config) > 0:
            filename = config[0]  # Return light variant by default
        else:
            return None
        return os.path.join(self.assets_dir, filename)
    
    def list_all_icons(self) -> Dict[str, Union[str, List[str]]]:
        """
        Get a dictionary of all icon mappings.

        Returns:
            Dictionary mapping icon keys to filenames (str or [light, dark] list)
        """
        return self.ICON_MAP.copy()
    
    def refresh_cache(self):
        """Clear the icon cache to force reloading."""
        self._icon_cache.clear()
        self._missing_icons.clear()
        # Reset statistics
        self._cache_hits = 0
        self._cache_misses = 0
        self._disk_loads = 0
    
    def get_status_tooltip(self, status: str) -> str:
        """
        Get appropriate tooltip text for a status.

        Args:
            status: Status string

        Returns:
            Tooltip text
        """
        tooltips = {
            'completed': 'Completed',
            'failed': 'Failed',
            'scan_failed': 'Scan Failed - Click to rescan',
            'upload_failed': 'Upload Failed - Click to retry',
            'uploading': 'Uploading',
            'paused': 'Paused',
            'ready': 'Ready',
            'pending': 'Pending',
            'incomplete': 'Incomplete - Resume to continue',
            'scanning': 'Scanning',
            'queued': 'Queued',
        }
        return tooltips.get(status, status.replace('_', ' ').title())

    def get_cache_stats(self) -> Dict[str, Union[int, float]]:
        """
        Get icon cache performance statistics.

        Returns:
            Dictionary with cache statistics:
            - hits: Number of cache hits (icons served from memory)
            - misses: Number of cache misses (icons needed to be loaded)
            - disk_loads: Number of actual disk I/O operations
            - cached_icons: Number of unique icons cached in memory
            - hit_rate: Cache hit percentage (0-100)
        """
        total_requests = self._cache_hits + self._cache_misses
        hit_rate = (self._cache_hits / total_requests * 100) if total_requests > 0 else 0.0

        return {
            'hits': self._cache_hits,
            'misses': self._cache_misses,
            'disk_loads': self._disk_loads,
            'cached_icons': len(self._icon_cache),
            'hit_rate': round(hit_rate, 2)
        }

    def print_cache_stats(self):
        """Print formatted cache statistics to console."""
        stats = self.get_cache_stats()
        print("=" * 60)
        print("ICON CACHE STATISTICS")
        print("=" * 60)
        print(f"Cache hits:        {stats['hits']:,}")
        print(f"Cache misses:      {stats['misses']:,}")
        print(f"Disk I/O ops:      {stats['disk_loads']:,}")
        print(f"Cached icons:      {stats['cached_icons']:,}")
        print(f"Hit rate:          {stats['hit_rate']:.2f}%")
        print(f"Disk I/O saved:    {stats['hits']:,} operations")
        print("=" * 60)


# Global instance (will be initialized by main window)
_icon_manager: Optional[IconManager] = None


def get_icon_manager() -> Optional[IconManager]:
    """Get the global icon manager instance."""
    return _icon_manager


def init_icon_manager(assets_dir: str) -> IconManager:
    """Initialize the global icon manager."""
    global _icon_manager
    _icon_manager = IconManager(assets_dir)
    return _icon_manager
