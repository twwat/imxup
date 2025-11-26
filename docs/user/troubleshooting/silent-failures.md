# Troubleshooting: Silent Startup Failure

## Problem
Running `python imxup.py --gui --debug` produces:
- No GUI window
- No console output
- No error messages
- Nothing at all

## Diagnostic Steps

Run these diagnostic scripts **on the failing computer** to identify the issue:

### Step 1: Check for Crash Logs

```bash
python check_crash_logs.py
```

This will check for:
- `imxup_crash.log` in the project directory (from top-level exception handler)
- `~/.imxup/crash.log` in user directory (from Qt exception hook)
- Windows Error Reporting crash dumps
- SQLite database integrity

**What to look for:** Any crash logs that contain error messages or tracebacks.

### Step 2: Run Startup Diagnostic

```bash
python diagnose_startup.py
```

This will test each initialization step individually:
1. Basic Python imports (requests, pathlib)
2. PyQt6.QtWidgets import
3. PyQt6.QtCore import
4. Splash screen import
5. QApplication creation
6. Splash screen object creation
7. Splash screen showing (Qt graphics test)
8. Main window import
9. Database connectivity

**What to look for:** The FIRST step that shows `[FAIL]`. This identifies exactly where the startup is breaking.

The diagnostic creates `diagnose_startup.log` with full details including tracebacks.

### Step 3: Check Python Environment

On the failing computer, verify:

```bash
# Check Python version
python --version

# Check if PyQt6 is installed
python -c "import PyQt6; print(PyQt6.__version__)"

# List installed packages (Windows CMD)
pip list | findstr /i "pyqt requests pillow"

# OR using PowerShell
pip list | Select-String "pyqt|requests|pillow"
```

## Common Causes

### 1. Missing/Broken PyQt6 Installation
**Symptom:** Diagnostic fails at "Import PyQt6.QtWidgets"
**Solution:**
```bash
pip uninstall PyQt6 PyQt6-Qt6 PyQt6-sip
pip install PyQt6==6.9.1
```

### 2. Missing Core Dependencies
**Symptom:** Diagnostic fails at "Import requests" or "Import pathlib"
**Solution:**
```bash
pip install -r requirements.txt
```

### 3. Corrupted SQLite Database
**Symptom:** check_crash_logs.py shows database error
**Solution (Windows CMD):**
```cmd
REM Backup and recreate database
move %USERPROFILE%\.imxup\imxup.db %USERPROFILE%\.imxup\imxup.db.backup
REM Run imxup again - it will create fresh database
```

**Solution (PowerShell):**
```powershell
# Backup and recreate database
Move-Item $env:USERPROFILE\.imxup\imxup.db $env:USERPROFILE\.imxup\imxup.db.backup
# Run imxup again - it will create fresh database
```

### 4. Windows-Specific DLL Issues
**Symptom:** No output at all, even from diagnostic scripts
**Solution:**
- Install Visual C++ Redistributables: https://aka.ms/vs/17/release/vc_redist.x64.exe
- Reinstall Python from python.org

### 5. Permission/Antivirus Blocking
**Symptom:** Silent failure, no logs created
**Solution:**

**Check Windows Defender logs:**
1. Open Event Viewer: `Win+R`, type `eventvwr.msc`
2. Navigate to: Applications and Services Logs → Microsoft → Windows → Windows Defender → Operational
3. Look for recent blocks/warnings related to Python or imxup

**Add exclusions (Windows Security):**
1. Open Windows Security → Virus & threat protection
2. Click "Manage settings" under Virus & threat protection settings
3. Scroll to "Exclusions" and click "Add or remove exclusions"
4. Add folder exclusion for your imxup directory

**Test as administrator (diagnostic only - NOT recommended for regular use):**
- Right-click Python script → "Run as administrator"
- If this works, indicates permission issue

## Exception Handling in imxup.py

The application has **three layers** of exception handling:

1. **GUI-specific handlers** (lines 2527-2534): Catches GUI initialization errors
   - ImportError handler (lines 2527-2529): PyQt6 import failures
   - Generic exception handler (lines 2530-2534): Other GUI startup errors
   - Both print to console via `debug_print()` and exit with code 1

2. **Qt event loop handler** (lines 2400-2421): Catches runtime exceptions in Qt callbacks
   - Prints to console with full traceback
   - Writes to `~/.imxup/crash.log` in user directory
   - Allows application to continue running

3. **Top-level handler** (lines 2809-2823): Catch-all for unhandled exceptions
   - Writes to `imxup_crash.log` in project directory
   - Attempts to log via normal logging system
   - Exits with code 1

**If NO output appears AND no logs are created**, the failure is occurring BEFORE any exception handlers can activate, likely in:
- Early Python imports (before line 2358)
- DLL loading failures (PyQt6, system libraries)
- Operating system blocking execution (antivirus, permissions)
- Missing Visual C++ Runtime or other system dependencies

## What to Report

After running the diagnostics, please report:

1. **Output from check_crash_logs.py** - Any crash logs found
2. **Output from diagnose_startup.py** - Which step failed first
3. **Python version and environment**:
   - `python --version`
   - `pip list | findstr /i "pyqt requests"`
4. **Operating system**:
   - Windows version
   - 32-bit or 64-bit
5. **Any antivirus/security software** installed

## Emergency Workarounds

If diagnostics don't reveal the issue:

### Option A: Clean Virtual Environment
```bash
# Create fresh virtual environment
python -m venv venv_new
venv_new\Scripts\activate
pip install -r requirements.txt

# Test with new environment
venv_new\Scripts\python.exe imxup.py --gui --debug
```

### Option B: Minimal Test
Create `test_minimal.py` in the imxup project directory:
```python
import sys
print("Step 1: Python works")

from PyQt6.QtWidgets import QApplication
print("Step 2: PyQt6 imports work")

app = QApplication(sys.argv)
print("Step 3: QApplication created")

from PyQt6.QtWidgets import QMessageBox
msg = QMessageBox()
msg.setText("If you see this, PyQt6 works!")
msg.show()
print("Step 4: Showing QMessageBox...")

sys.exit(app.exec())
```

Run: `python test_minimal.py`

This isolates whether the issue is PyQt6-related or specific to imxup's startup sequence.
