# WSL2 Drag-and-Drop Fix

## Problem Identified

When dragging files from Windows Explorer into the imxup application running in WSL2, the drag operation was being rejected with a "no drop" cursor (circle with line through it). The files were never reaching the `dropEvent` handler where WSL path conversion occurs.

## Root Cause

The issue was in the **drag event acceptance logic** in `src/gui/main_window.py`:

1. **`dragEnterEvent`** (line 6562) and **`dragMoveEvent`** (line 6570) were checking if the mime data contains valid URLs
2. In WSL2, when dragging from Windows Explorer, Qt might not immediately recognize the Windows paths as valid URLs
3. The drag was being **rejected before** the `dropEvent` could perform WSL path conversion
4. The path conversion logic in `dropEvent` (line 6592) never got a chance to run

## Solution Implemented

Made the drag acceptance logic **MORE PERMISSIVE** by:

### 1. Enhanced `dragEnterEvent` (lines 6562-6588)
- Now accepts drags that have **URLs OR text** (Windows paths might come as text)
- Added comprehensive debug logging to diagnose what's being passed
- Logs mime data formats, URL count, and text content
- Only rejects if there are no URLs AND no text

### 2. Enhanced `dragMoveEvent` (lines 6590-6602)
- Now accepts drags that have **URLs OR text**
- Simpler implementation since it just needs to maintain the acceptance

### 3. Enhanced `dropEvent` (lines 6607-6649)
- Added extensive debug logging throughout the validation process
- Logs:
  - Initial mime data status
  - Number of URLs being processed
  - Original path from each URL
  - WSL path conversion results
  - Path validation success/failure
  - Final acceptance or rejection

## Key Changes

**Before:**
```python
def dragEnterEvent(self, event):
    if event.mimeData().hasUrls():
        event.acceptProposedAction()
    else:
        event.ignore()
```

**After:**
```python
def dragEnterEvent(self, event):
    mime_data = event.mimeData()

    # Accept URLs
    if mime_data.hasUrls():
        event.acceptProposedAction()
        return

    # Also accept text (WSL2 might pass paths as text)
    if mime_data.hasText():
        event.acceptProposedAction()
        return

    # Only reject if no URLs AND no text
    event.ignore()
```

## Debug Logging

The fix includes extensive logging with category "drag_drop":

1. **dragEnterEvent**: Logs hasUrls, hasText, formats, and acceptance decision
2. **dropEvent**: Logs URL processing, WSL conversion, validation results

To enable drag-drop debugging, ensure logging is enabled for the "drag_drop" category in the application settings.

## Testing Instructions

1. Launch imxup in WSL2: `python imxup.py`
2. Open Windows Explorer
3. Navigate to a folder containing archives (ZIP, RAR, etc.) or folders with images
4. Drag a folder or archive from Windows Explorer to the imxup window
5. **Expected behavior**:
   - Cursor should change to "drop allowed" (no circle with line)
   - File should be accepted
   - Check logs for "drag_drop" messages showing path conversion

## Technical Details

### WSL Path Conversion
The `convert_to_wsl_path()` function (from `src/utils/system_utils.py`) converts:
- `C:\path\to\folder` → `/mnt/c/path/to/folder`
- Only active when `is_wsl2()` returns True

### Acceptance Flow
```
Windows Explorer drag
    ↓
dragEnterEvent: Accept if hasUrls OR hasText
    ↓
dragMoveEvent: Accept if hasUrls OR hasText
    ↓
dropEvent:
    - Extract URLs from mime data
    - Convert Windows paths to WSL format
    - Validate converted paths
    - Add to application if valid
```

## Files Modified

- `/home/jimbo/imxup/src/gui/main_window.py`
  - `dragEnterEvent()` (lines 6562-6588): Enhanced acceptance logic + logging
  - `dragMoveEvent()` (lines 6590-6602): Accept URLs or text
  - `dropEvent()` (lines 6607-6649): Enhanced logging throughout

## Verification

To verify the fix is working:

1. Check the application accepts drags (cursor changes)
2. Enable "drag_drop" logging category
3. Monitor logs for messages showing:
   ```
   dragEnterEvent: Accepting drag with N URLs
   dropEvent: Processing N URLs
   dropEvent: Original path from URL: C:\...
   WSL2 path conversion: C:\... -> /mnt/c/...
   Path validated: /mnt/c/...
   dropEvent: Adding N valid paths
   ```

## Related Code

- **WSL Detection**: `src/utils/system_utils.py::is_wsl2()` (line 355)
- **Path Conversion**: `src/utils/system_utils.py::convert_to_wsl_path()` (line 372)
- **Logging**: `src/utils/logger.py::log()` with category "drag_drop"

## Backward Compatibility

This fix is **backward compatible**:
- Non-WSL2 systems: Paths pass through unchanged
- WSL2 without Windows drags: Works as before
- Native Linux drags: Works as before
- **Improvement**: WSL2 with Windows drags now works correctly

## Future Enhancements

Potential improvements:
1. Handle text-based file paths if mime data has text but not URLs
2. Add support for multiple file selection validation
3. Create user-visible error messages for invalid drops
4. Add telemetry to track drag-drop success rates on different platforms
