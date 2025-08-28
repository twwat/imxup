# Icon System Documentation

This document describes ImxUp's icon system and how to manage, update, or add icons.

## Overview

ImxUp uses a centralized `IconManager` class to handle all application icons with **theme and selection awareness**. This hybrid system provides:
- **Single icons with auto-inversion**: Dark/light theme adaptation automatically
- **Manual icon pairs**: Full control with separate light/dark versions  
- **Selection state handling**: Icons adapt to selected table rows
- **Validation and fallbacks**: Missing icons detected with Qt standard fallbacks
- **Easy customization**: Icon Manager tab in settings for drag & drop management

## Icon Categories

### Status Icons

Status icons are shown in the "Status" column of the gallery table:

| Status | Icon File | Description |
|--------|-----------|-------------|
| `completed` | `check.png` | Gallery upload completed successfully |
| `failed` | `error.png` | Gallery upload failed |
| `uploading` | `start.png` | Gallery is currently uploading |
| `paused` | `pause.png` | Gallery upload is paused |
| `queued` | `queued.png` | Gallery is queued for upload |
| `ready` | `ready.png` | Gallery is ready to upload |
| `pending` | `pending.png` | Gallery is in a pending state |
| `incomplete` | `incomplete.png` | Gallery upload was partially completed |
| `scan_failed` | `scan_failed.png` | Failed to scan gallery folder for images |
| `upload_failed` | `error.png` | Upload failed (reuses error.png) |
| `scanning` | `pending.png` | Currently scanning folder (reuses pending.png) |

### Action Button Icons

Action icons are used in the "Actions" column buttons:

| Action | Icon File | Description |
|--------|-----------|-------------|
| `start/resume` | `play.png` | Start or resume gallery upload |
| `stop` | `stop.png` | Stop current upload |
| `view` | `view.png` | View completed gallery |
| `view_error` | `view_error.png` | View error details for failed gallery |
| `cancel` | `pause.png` | Cancel/pause operation (reuses pause.png) |

### UI Element Icons

| Element | Icon File | Description |
|---------|-----------|-------------|
| `templates` | `templates.svg` | Template management section |
| `credentials` | `credentials.svg` | Credentials section |
| `main_window` | `imxup.png` | Main application window icon |
| `app_icon` | `imxup.ico` | Application icon (.ico format) |

### Alternative Sizes

Some icons have alternative sizes available:

| Icon | Alternative | Description |
|------|-------------|-------------|
| `check.png` | `check16.png` | 16x16 version of check icon |

## File Locations

- **Icons Directory**: `assets/` (relative to project root)
- **Supported Formats**: PNG, SVG, ICO
- **Recommended Size**: 16x16 or 32x32 pixels for status/action icons

## Current Icon Inventory

### Available Icons
The following icons are currently available in the `assets/` directory:

- ✅ `check.png` - Green checkmark
- ✅ `check16.png` - 16x16 green checkmark  
- ✅ `error.png` - Red error icon
- ✅ `start.png` - Blue play/start button
- ✅ `pause.png` - Orange pause button
- ✅ `pending.png` - Clock icon (yellow/orange)
- ✅ `incomplete.png` - Partial/incomplete icon
- ✅ `scan_failed.png` - Scan failure icon
- ✅ `play.png` - Play button icon
- ✅ `stop.png` - Stop button icon
- ✅ `view.png` - Eye/view icon
- ✅ `view_error.png` - Error view icon
- ✅ `ready.png` - Ready status icon
- ✅ `templates.svg` - Templates icon (SVG)
- ✅ `credentials.svg` - Credentials icon (SVG)
- ✅ `imxup.png` - Main app icon (PNG)
- ✅ `imxup.ico` - Main app icon (ICO)

### Missing Icons (will use Qt fallbacks)
- ❌ `queued.png` - Will use Qt file icon fallback

## How the System Works

### 1. Icon Resolution Process
1. **IconManager lookup**: Check if icon key exists in `ICON_MAP`
2. **File existence**: Look for icon file in `assets/` directory
3. **Qt fallback**: Use Qt standard icon if available
4. **Empty icon**: Return empty QIcon as last resort

### 2. Status Icon Mapping
```python
# In IconManager.ICON_MAP
'status_completed': 'check.png'  # Maps status to file
```

### 3. Fallback System
```python
# In IconManager.QT_FALLBACKS
'status_completed': QStyle.StandardPixmap.SP_DialogApplyButton
```

## Hybrid Icon System

### Single Icons (Auto-Inversion)
```python
'status_completed': 'check.png'  # Auto-adapts to theme/selection
```
- **Pros**: Simple, only need one icon file
- **Cons**: Automatic inversion may not be perfect for all designs
- **Best for**: Simple geometric icons, solid colors

### Manual Icon Pairs  
```python
'status_completed': ['check-light.png', 'check-dark.png']  # Full control
```
- **Pros**: Perfect visual control for each scenario
- **Cons**: Need to maintain two icon files
- **Best for**: Complex icons, gradients, text-based icons

### Theme/Selection Logic
| Scenario | Background | Uses |
|----------|------------|------|
| Light theme, unselected | Light | Light icon (dark content) |
| Light theme, selected | Dark blue | Dark icon (light content) |
| Dark theme, unselected | Dark | Dark icon (light content) |  
| Dark theme, selected | Light blue | Light icon (dark content) |

## Managing Icons

### Using the Icon Manager Tab

1. **Open Settings** → **Icon Manager** tab
2. **Preview themes**: Use dropdown to see light/dark/selected appearance  
3. **Replace icons**: Drag & drop new files or click Browse
4. **Reset icons**: Use reset buttons to restore defaults
5. **Apply changes**: Click Apply to refresh all icons

### Manual Configuration

1. **Add the icon file(s)** to the `assets/` directory
2. **Update IconManager.ICON_MAP** in `src/gui/icon_manager.py`:
   ```python
   # Single icon (auto-invert)
   'status_new_status': 'new_icon.png'
   
   # Or icon pair (manual control)  
   'status_new_status': ['new_icon-light.png', 'new_icon-dark.png']
   ```
3. **Add Qt fallback** (optional) in `IconManager.QT_FALLBACKS`:
   ```python
   'status_new_status': QStyle.StandardPixmap.SP_SomeIcon
   ```
4. **Refresh via settings** or restart application

### Icon Validation

The application validates icons at startup and reports missing ones:

```
ICON VALIDATION REPORT
============================================
Assets directory: /path/to/assets
Total icons defined: 25
Icons found: 24  
Icons missing: 1

Missing icons (will use fallbacks):
  - status_queued -> queued.png
============================================
```

## Troubleshooting

### Problem: Status showing wrong icon

**Cause**: Icon file missing or status not handled in `_set_status_cell_icon()`

**Solution**: 
1. Check if icon file exists in `assets/`
2. Verify status is mapped in `IconManager.ICON_MAP`
3. Check startup validation report for missing icons

### Problem: Seeing Qt standard icons instead of custom icons

**Cause**: Custom icon files are missing

**Solution**:
1. Check the validation report at startup
2. Add missing icon files to `assets/`
3. Restart application to refresh cache

### Problem: Icon appears as folder/computer icon

**Cause**: Status falling back to Qt standard icons

**Solution**:
1. Add the custom icon file for that status
2. Or update the Qt fallback to a more appropriate standard icon

## Technical Details

### IconManager Class Location
- **File**: `src/gui/icon_manager.py`
- **Initialization**: `src/gui/main_window.py` in `ImxUploadGUI.__init__()`

### Key Methods
- `get_status_icon(status)` - Get icon for a status
- `get_action_icon(action)` - Get icon for an action
- `validate_icons()` - Check which icons are missing
- `get_missing_icons()` - List icons that were requested but not found

### Cache Management
Icons are cached after first load. To refresh:
```python
icon_mgr = get_icon_manager()
icon_mgr.refresh_cache()
```

## Best Practices

1. **Use PNG format** for most icons (16x16 or 32x32 pixels)
2. **Consistent visual style** across all icons
3. **Meaningful names** that clearly indicate purpose
4. **Test with both light and dark themes** if applicable
5. **Always add Qt fallbacks** for important status icons
6. **Update documentation** when adding new icons

## Migration from Old System

The old `ICON_CONFIG` system with arrays of fallback filenames has been replaced with the new IconManager system. The old system is still supported as a fallback but is deprecated.

**Old format**:
```python
'completed': ['check.png', 'check16.png']  # Try multiple files
```

**New format**:
```python
'status_completed': 'check.png'  # Single file per status
```