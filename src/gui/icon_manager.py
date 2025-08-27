"""
Icon Manager for ImxUp application.
Centralized management of all application icons with validation and clear mappings.
"""

import os
from typing import Dict, Optional, List, Set, Union
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor
from PyQt6.QtWidgets import QStyle
from PyQt6.QtCore import QSize


class IconManager:
    """Centralized icon management with validation and clear mappings."""
    
    # Hybrid icon mapping: string for auto-invert, list for manual light/dark pairs
    ICON_MAP = {
        # Status icons - single icons (auto-invert) or [light, dark] pairs
        'status_completed': 'check.png',                    # Auto-invert
        'status_failed': 'error.png',                       # Auto-invert  
        'status_uploading': 'start.png',                    # Auto-invert
        'status_paused': 'pause.png',                       # Auto-invert
        'status_queued': 'queued.png',                      # Auto-invert
        'status_ready': 'ready.png',                        # Auto-invert
        'status_pending': 'pending.png',                    # Auto-invert
        'status_incomplete': 'incomplete.png',              # Auto-invert
        'status_scan_failed': 'scan_failed.png',           # Auto-invert
        'status_upload_failed': 'error.png',               # Auto-invert (reuses error.png)
        'status_scanning': 'pending.png',                  # Auto-invert (reuses pending.png)
        
        # Example of manual light/dark pairs (uncomment when dark versions available):
        # 'status_failed': ['error.png', 'error-dark.png'],  # Manual pair
        
        # Action button icons
        'action_start': 'play.png',
        'action_stop': 'stop.png',
        'action_view': 'view.png',
        'action_view_error': 'view_error.png',
        'action_cancel': 'pause.png',
        'action_resume': 'play.png',  # Reuses play.png
        
        # UI element icons
        'templates': 'templates.svg',
        'credentials': 'credentials.svg',
        'main_window': 'imxup.png',
        'app_icon': 'imxup.ico',
        
        # Alternative sizes (optional)
        'check_small': 'check16.png',
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
        
        'action_start': QStyle.StandardPixmap.SP_MediaPlay,
        'action_stop': QStyle.StandardPixmap.SP_MediaStop,
        'action_view': QStyle.StandardPixmap.SP_DirOpenIcon,
        'action_view_error': QStyle.StandardPixmap.SP_MessageBoxWarning,
        'action_cancel': QStyle.StandardPixmap.SP_DialogCancelButton,
        'action_resume': QStyle.StandardPixmap.SP_MediaPlay,
    }
    
    def __init__(self, assets_dir: str):
        """Initialize the icon manager with the assets directory path."""
        self.assets_dir = assets_dir
        self._icon_cache: Dict[str, QIcon] = {}
        self._missing_icons: Set[str] = set()
        self._validated = False
        
        # Cache for inverted icons to avoid repeated processing
        self._inverted_cache: Dict[str, QIcon] = {}
        
        # Auto-generate dark variants for all single-icon configs
        self._create_missing_dark_variants()
        
        # Force convert status icons to use dark variants since they exist
        status_conversions = {
            'status_completed':     ['status_completed-light.png',  'status_completed-dark.png'],
            'status_failed':        ['status_failed-light.png',     'status_failed-dark.png'], 
            'status_uploading':     ['status_uploading-light.png',  'status_uploading-dark.png'],
            'status_paused':        ['status_paused-light.png',     'status_paused-dark.png'],
            'status_queued':        ['status_queued-light.png',     'status_queued-dark.png'],
            'status_ready':         ['status_ready-light.png',      'status_ready-dark.png'],
            'status_pending':       ['status_pending-light.png',    'status_pending-dark.png'],
            'status_incomplete':    ['status_incomplete-light.png', 'status_incomplete-dark.png'],
            'status_scan_failed':   ['status_scan_failed-light.png','status_scan_failed-dark.png'],
            'status_upload_failed': ['status_error-light.png',      'status_error-dark.png'],
            'status_scanning':      ['status_scanning-light.png',   'status_scanning-dark.png'],
        }
        
        for key, config in status_conversions.items():
            if key in self.ICON_MAP:
                self.ICON_MAP[key] = config
        
        # Debug: show final config state
        print(f"DEBUG: Icon configs after auto-generation:")
        for key, config in self.ICON_MAP.items():
            if key.startswith('status_'):
                print(f"  {key}: {type(config)} = {config}")
        
    def get_icon(self, icon_key: str, style_instance=None, is_dark_theme: bool = False, is_selected: bool = False, requested_size: int = 32) -> QIcon:
        """
        Get an icon by its key with theme and selection awareness.
        
        Args:
            icon_key: The icon identifier (e.g., 'status_completed', 'action_start')
            style_instance: QStyle instance for fallback icons
            is_dark_theme: Whether the current theme is dark
            is_selected: Whether the icon is for a selected table row
            requested_size: Size to generate inverted icons at (for quality)
            
        Returns:
            QIcon object (may be null if not found and no fallback)
        """
        # Create cache key that includes theme/selection state and size
        cache_key = f"{icon_key}_{is_dark_theme}_{is_selected}_{requested_size}"
        
        # Check cache first
        if cache_key in self._icon_cache:
            return self._icon_cache[cache_key]
        
        # Get the configuration from our map
        if icon_key not in self.ICON_MAP:
            print(f"Warning: Unknown icon key '{icon_key}'")
            return QIcon()
        
        config = self.ICON_MAP[icon_key]
        
        # Debug output for config type
        if icon_key.startswith('status_') and (is_selected or is_dark_theme):
            print(f"DEBUG: {icon_key} config type: {type(config)} = {config}")
        
        # Determine which icon file to use
        filename = self._get_themed_filename(config, is_dark_theme, is_selected)
        if not filename:
            return QIcon()
            
        icon_path = os.path.join(self.assets_dir, filename)
        
        # Try to load the icon
        if os.path.exists(icon_path):
            icon = QIcon(icon_path)
            if not icon.isNull():
                # No inversion needed - we now have real light/dark files
                self._icon_cache[cache_key] = icon
                return icon
        
        # Record missing icon
        self._missing_icons.add(icon_key)
        
        # Use Qt standard icon fallback if available
        if style_instance and icon_key in self.QT_FALLBACKS:
            fallback_pixmap = self.QT_FALLBACKS[icon_key]
            icon = style_instance.standardIcon(fallback_pixmap)
            self._icon_cache[cache_key] = icon
            return icon
        
        # Return empty icon as last resort
        return QIcon()
    
    def _get_themed_filename(self, config: Union[str, List[str]], is_dark_theme: bool, is_selected: bool) -> Optional[str]:
        """
        Get the appropriate filename based on theme and selection state.
        
        Args:
            config: Icon configuration (string or [light, dark] list)
            is_dark_theme: Whether current theme is dark
            is_selected: Whether icon is for selected row
            
        Returns:
            Filename to use, or None if invalid config
        """
        if isinstance(config, str):
            # Single icon - return as-is (inversion handled later)
            return config
        elif isinstance(config, list) and len(config) >= 2:
            # Manual light/dark pair
            # Logic: 
            # - Normal rows: light theme uses light icon, dark theme uses dark icon
            # - Selected rows: always use opposite variant for contrast on selection background
            if is_selected:
                # Selected: use dark icon in light theme, light icon in dark theme
                filename = config[1] if not is_dark_theme else config[0]
                # Debug output (removed icon_key reference)
                return filename
            else:
                # Not selected: use light icon in light theme, dark icon in dark theme
                filename = config[0] if not is_dark_theme else config[1]
                return filename
        else:
            print(f"Warning: Invalid icon configuration: {config}")
            return None
    
    def _needs_inversion(self, is_dark_theme: bool, is_selected: bool) -> bool:
        """
        Determine if a single icon needs color inversion.
        
        Args:
            is_dark_theme: Whether current theme is dark  
            is_selected: Whether icon is for selected row
            
        Returns:
            True if icon should be inverted
        """
        # Invert when we need light content on dark background
        return (is_dark_theme and not is_selected) or (not is_dark_theme and is_selected)
    
    def _invert_icon(self, icon: QIcon, original_path: str, requested_size: int = 96) -> QIcon:
        """
        Create an inverted version of an icon at the requested size.
        
        Args:
            icon: Original QIcon
            original_path: Path to original icon file (for caching)
            requested_size: Size to generate the inverted icon at
            
        Returns:
            Inverted QIcon at the requested size
        """
        # Check inverted cache first with size-specific key
        cache_key = f"inverted_{original_path}_{requested_size}"
        if cache_key in self._inverted_cache:
            return self._inverted_cache[cache_key]
        
        # Get the original pixmap at the requested size
        original_pixmap = icon.pixmap(requested_size, requested_size)
        if original_pixmap.isNull():
            return icon  # Return original if we can't process it
        
        # Create inverted pixmap at the same size
        inverted_pixmap = QPixmap(requested_size, requested_size)
        inverted_pixmap.fill(QColor(0, 0, 0, 0))  # Transparent background
        
        painter = QPainter(inverted_pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        
        # Draw the original pixmap (scale to fill the requested size)
        painter.drawPixmap(0, 0, requested_size, requested_size, original_pixmap)
        
        # Apply color inversion by using different composition mode
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Difference)
        painter.fillRect(0, 0, requested_size, requested_size, QColor(255, 255, 255))
        
        painter.end()
        
        # Create new icon from inverted pixmap
        inverted_icon = QIcon(inverted_pixmap)
        
        # Cache the result
        self._inverted_cache[cache_key] = inverted_icon
        
        return inverted_icon
    
    def _create_missing_dark_variants(self):
        """Auto-generate dark variants for all single-icon configs at startup"""
        import os
        import shutil
        
        for icon_key, config in self.ICON_MAP.items():
            if isinstance(config, str):  # Single icon config
                light_filename = config
                light_path = os.path.join(self.assets_dir, light_filename)
                
                # Generate dark variant filename
                base, ext = os.path.splitext(light_filename)
                dark_filename = f"{base}-dark{ext}"
                dark_path = os.path.join(self.assets_dir, dark_filename)
                
                # Create dark variant if it doesn't exist and light exists
                if os.path.exists(light_path) and not os.path.exists(dark_path):
                    try:
                        # Load original pixmap directly to preserve size and transparency
                        from PyQt6.QtGui import QPixmap, QPainter
                        light_pixmap = QPixmap(light_path)
                        if not light_pixmap.isNull():
                            # Create inverted version preserving original size and alpha
                            # Convert to QImage for pixel-level manipulation to preserve transparency
                            light_image = light_pixmap.toImage()
                            if light_image.format() != light_image.Format.Format_ARGB32:
                                light_image = light_image.convertToFormat(light_image.Format.Format_ARGB32)
                            
                            # Create dark image with same format
                            dark_image = light_image.copy()
                            
                            # Invert RGB channels while preserving alpha
                            for y in range(dark_image.height()):
                                for x in range(dark_image.width()):
                                    pixel = dark_image.pixel(x, y)
                                    # Extract ARGB components
                                    alpha = (pixel >> 24) & 0xFF
                                    red = (pixel >> 16) & 0xFF
                                    green = (pixel >> 8) & 0xFF  
                                    blue = pixel & 0xFF
                                    
                                    # Invert RGB, keep alpha unchanged
                                    inverted_red = 255 - red
                                    inverted_green = 255 - green
                                    inverted_blue = 255 - blue
                                    
                                    # Reconstruct pixel
                                    new_pixel = (alpha << 24) | (inverted_red << 16) | (inverted_green << 8) | inverted_blue
                                    dark_image.setPixel(x, y, new_pixel)
                            
                            # Convert back to pixmap and save
                            dark_pixmap = QPixmap.fromImage(dark_image)
                            dark_pixmap.save(dark_path)
                            
                            # Convert config to light/dark pair
                            self.ICON_MAP[icon_key] = [light_filename, dark_filename]
                            print(f"Created dark variant: {dark_filename} for {icon_key}")
                    except Exception as e:
                        print(f"ERROR: Failed to create dark variant for {icon_key}: {e}")
                        import traceback
                        traceback.print_exc()
    
    def get_status_icon(self, status: str, style_instance=None, is_dark_theme: bool = False, is_selected: bool = False, requested_size: int = 32) -> QIcon:
        """
        Get icon for a specific status with theme/selection awareness.
        
        Args:
            status: Status string (e.g., 'completed', 'uploading')
            style_instance: QStyle instance for fallback icons
            is_dark_theme: Whether current theme is dark
            is_selected: Whether icon is for selected row
            requested_size: Size to generate inverted icons at (for quality)
            
        Returns:
            QIcon object
        """
        icon_key = f'status_{status}'
        return self.get_icon(icon_key, style_instance, is_dark_theme, is_selected, requested_size)
    
    def get_action_icon(self, action: str, style_instance=None, is_dark_theme: bool = False, is_selected: bool = False) -> QIcon:
        """
        Get icon for an action button with theme/selection awareness.
        
        Args:
            action: Action name (e.g., 'start', 'stop')
            style_instance: QStyle instance for fallback icons
            is_dark_theme: Whether current theme is dark
            is_selected: Whether icon is for selected row
            
        Returns:
            QIcon object
        """
        icon_key = f'action_{action}'
        return self.get_icon(icon_key, style_instance, is_dark_theme, is_selected)
    
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
        
        filename = self.ICON_MAP[icon_key]
        return os.path.join(self.assets_dir, filename)
    
    def list_all_icons(self) -> Dict[str, str]:
        """
        Get a dictionary of all icon mappings.
        
        Returns:
            Dictionary mapping icon keys to filenames
        """
        return self.ICON_MAP.copy()
    
    def refresh_cache(self):
        """Clear the icon cache to force reloading."""
        self._icon_cache.clear()
        self._inverted_cache.clear()
        self._missing_icons.clear()
    
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