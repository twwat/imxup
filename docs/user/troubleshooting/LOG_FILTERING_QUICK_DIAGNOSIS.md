# Quick Diagnosis: Why INFO Shows But ERROR/WARNING Don't

## The Mystery

User sees "INFO" messages in the GUI log widget, but NOT "ERROR", "WARNING", or other log levels.

## The Investigation

I traced through the entire logging system and found the filtering logic:

### How Filtering Works

1. **Log level filtering** in `src/utils/logging.py` (line 330-338):
   ```python
   def should_emit_gui(self, category: str, level: int) -> bool:
       if level < self._gui_level:
           return False  # Block message
       # ... category checks ...
   ```

2. **Numeric log levels**:
   - DEBUG = 10
   - INFO = 20 (default GUI level)
   - WARNING = 30
   - ERROR = 40
   - CRITICAL = 50

3. **Default behavior**: With `level_gui = INFO`:
   - ✓ Should show: INFO, WARNING, ERROR, CRITICAL
   - ✗ Should block: DEBUG, TRACE

## The Paradox

**According to the code, ERROR and WARNING should ALWAYS show when INFO shows!**

This is because:
- ERROR (40) >= INFO (20) ✓
- WARNING (30) >= INFO (20) ✓

So if INFO appears, ERROR and WARNING must also pass the filter.

## Possible Explanations

### 1. Messages Don't Have Correct Log Level

Maybe ERROR/WARNING messages aren't being logged with `level="error"` or `level="warning"`:

```python
# Wrong (defaults to INFO)
log("Something failed")

# Correct (explicit ERROR level)
log("Something failed", level="error")
```

### 2. Category Filters Block Them

Each category can be disabled independently. If ERROR messages are in a disabled category:

```ini
[LOGGING]
cats_gui_network = false  # Blocks ALL network messages, even ERROR
```

### 3. Messages Aren't Being Generated

Code paths that would generate ERROR/WARNING might not be executing.

### 4. Config Has Wrong Level

The config file might have:
```ini
[LOGGING]
level_gui = ERROR  # This would block INFO and WARNING!
```

But this contradicts the fact that INFO is showing...

## Run the Diagnostics

### Step 1: Check Configuration
```bash
python3 scripts/diagnose_log_filtering.py
```

This will show:
- Current `level_gui` setting
- Which categories are enabled/disabled
- Which log levels should pass the filter
- Specific diagnosis of the problem

### Step 2: Test Message Generation
```bash
python3 scripts/test_log_levels.py
```

This sends messages at all levels and you can see which appear in the GUI.

### Step 3: Search for Actual ERROR Logs

Check if ERROR messages are even being called:
```bash
grep -rn 'level="error"\|level="warning"' src/
```

## Expected Output

If everything is working correctly:

1. `diagnose_log_filtering.py` should show:
   - `GUI Log Level: INFO`
   - All categories ENABLED
   - Test showing: INFO, WARNING, ERROR all pass filter

2. `test_log_levels.py` should display:
   - INFO messages in GUI
   - WARNING messages in GUI
   - ERROR messages in GUI
   - CRITICAL messages in GUI

## What to Look For

### If ERROR messages are being blocked:

Check the diagnostic output for:
- `level_gui` setting (should be INFO or DEBUG)
- Category status (ERROR messages' categories should be enabled)
- Test results (ERROR test should show "✓ SHOWN")

### If ERROR messages aren't being generated:

Search the codebase:
```bash
# Find all ERROR log calls
grep -rn 'log.*level.*error\|log.*"error"' src/

# Find all WARNING log calls
grep -rn 'log.*level.*warning\|log.*"warning"' src/
```

If no results, then ERROR/WARNING simply aren't being logged anywhere!

## Most Likely Culprit

Based on the code analysis, **I suspect one of these**:

1. **ERROR/WARNING aren't being called** - The application isn't logging errors yet
2. **Category filters** - ERROR messages are in disabled categories
3. **Wrong log level in code** - Code is calling `log(message)` without `level="error"`

## Quick Fix

If you want to test ERROR messages immediately, add this to any Python file:

```python
from src.utils.logger import log

log("This is an ERROR test", level="error", category="general")
log("This is a WARNING test", level="warning", category="general")
log("This is an INFO test", level="info", category="general")
```

All three should appear in the GUI (assuming general category is enabled).

## Files to Check

1. `/home/jimbo/.config/imxup/config.ini` - Check `[LOGGING]` section
2. `src/utils/logger.py` - Main logging function (line 198-370)
3. `src/utils/logging.py` - AppLogger class with filters (line 330-338)
4. `src/gui/main_window.py` - GUI log display (line 5214-5263)

## Summary

The logging system **should work correctly**. If ERROR/WARNING don't show but INFO does, it's likely:

- Messages aren't being logged at ERROR/WARNING level
- OR category filters are blocking them
- OR there's a bug I haven't found yet

Run the diagnostic scripts to find out which!
