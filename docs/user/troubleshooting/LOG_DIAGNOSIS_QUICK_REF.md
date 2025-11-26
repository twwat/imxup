# Log Level Diagnosis - Quick Reference

## The Problem

> "I see INFO in the GUI log widget, but not ERROR, WARNING, DEBUG, etc."

## Quick Diagnosis (30 seconds)

```bash
# Run the diagnostic tool
python3 scripts/diagnose_log_filtering.py

# Inject test messages
python3 scripts/inject_test_messages.py

# Check the GUI log widget
```

## What to Look For

### ✅ If test messages appear:
- **Conclusion**: System works! Your app isn't logging errors yet.
- **Solution**: Add error logging to your code:
  ```python
  log("Error occurred", level="error")
  ```

### ❌ If test messages don't appear:

Check diagnostic output for these issues:

#### Issue 1: Wrong GUI Level
```
GUI Log Level: ERROR  ← WRONG! Should be INFO
```
**Fix**: Edit config file:
```ini
[LOGGING]
level_gui = INFO
```

#### Issue 2: Disabled Categories
```
general [cats_gui_general] = ✗ DISABLED  ← WRONG!
```
**Fix**: Edit config file:
```ini
[LOGGING]
cats_gui_general = true
```

#### Issue 3: Filter Test Fails
```
ERROR in general (level=40): ✗ BLOCKED  ← WRONG!
```
**Fix**: There's a bug. Report this output.

## Understanding the GUI Display

**Important**: The GUI **strips level prefixes** before display!

This means:
- Message sent: `"12:34:56 ERROR: Upload failed"`
- GUI shows: `"12:34:56 Upload failed"` ← No "ERROR:" visible!

**How to tell what level a message is**:
1. Enable level prefixes: `show_log_level_gui = true` in config
2. Check the log file (always has prefixes)
3. Open the log viewer dialog (shows full messages)

## Common Mistakes

### Mistake 1: Not using level parameter
```python
# ❌ Wrong (defaults to INFO)
log("Upload failed")

# ✅ Correct (explicit ERROR level)
log("Upload failed", level="error")
```

### Mistake 2: Expecting to see "ERROR:" prefix
The GUI strips these prefixes! Enable `show_log_level_gui` if you want them.

### Mistake 3: Thinking messages are blocked
They're probably showing, just without obvious visual indicators.

## Filter Logic (Technical)

Messages pass the filter when:
```
log_level >= gui_level
```

With default `gui_level = INFO (20)`:
- DEBUG (10) < 20 → ❌ BLOCKED
- INFO (20) >= 20 → ✅ SHOWN
- WARNING (30) >= 20 → ✅ SHOWN
- ERROR (40) >= 20 → ✅ SHOWN
- CRITICAL (50) >= 20 → ✅ SHOWN

**Conclusion**: If INFO shows, ERROR/WARNING MUST show too (unless categories are disabled).

## Files to Check

1. **Config file**: `~/.config/imxup/config.ini`
   - Section: `[LOGGING]`
   - Key settings: `level_gui`, `cats_gui_*`

2. **Log file**: `~/.local/share/imxup/logs/imxup.log`
   - Shows ALL messages with full prefixes
   - Useful for comparison with GUI

3. **Source code**: Search for log calls
   ```bash
   grep -rn 'level="error"' src/
   ```

## Quick Fixes

### Enable All Categories
```ini
[LOGGING]
cats_gui_general = true
cats_gui_network = true
cats_gui_uploads = true
cats_gui_auth = true
cats_gui_ui = true
cats_gui_queue = true
cats_gui_renaming = true
cats_gui_fileio = true
cats_gui_hooks = true
```

### Show Level Prefixes in GUI
```ini
[LOGGING]
show_log_level_gui = true
show_category_gui = true
```

### Set GUI Level to Show Everything
```ini
[LOGGING]
level_gui = DEBUG
```

## Test Commands

```bash
# 1. Full diagnostic (shows config and tests)
python3 scripts/diagnose_log_filtering.py

# 2. Send test messages (verifies GUI receives them)
python3 scripts/inject_test_messages.py

# 3. Simple level tests
python3 scripts/test_log_levels.py

# 4. Find ERROR log calls in code
grep -rn 'level="error"' src/

# 5. Check config file
cat ~/.config/imxup/config.ini | grep -A 20 "\[LOGGING\]"

# 6. Check log file (last 50 lines)
tail -50 ~/.local/share/imxup/logs/imxup.log
```

## Most Likely Answer

**90% chance**: Your application isn't logging ERROR or WARNING messages yet. The logging system works fine, but there are no errors to log.

**8% chance**: Category filters are blocking the messages.

**2% chance**: There's an actual bug in the filtering logic.

**Run the diagnostic to know for sure!**
