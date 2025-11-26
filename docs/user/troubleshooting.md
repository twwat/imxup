# Troubleshooting Guide

## Quick Reference

**Common Issues:**
- GUI not responding → Check database locks, restart application
- Upload failures → Verify credentials, check network, review logs
- Slow performance → Enable lazy loading, reduce image sampling
- Database errors → Run integrity check, restore from backup
- BBCode issues → Validate template syntax, check placeholders

**Log Location:** View → Logs (Ctrl+L)
**Settings Location:** File → Settings (Ctrl+Comma)
**Database Location:** `.imxup/` (hidden folder)

---

## GUI Errors and Solutions

### Application Won't Start

**Symptom:** imxup window doesn't appear or crashes immediately

**Common Causes:**
1. **Database corruption:** Damaged SQLite database
2. **Missing dependencies:** Required libraries not installed
3. **Python version:** Incompatible Python version (requires 3.14+)
4. **Config file errors:** Malformed JSON configuration

**Solutions:**

**1. Check Python Version:**
```bash
python --version
# Should show: Python 3.14.x
```

**2. Reinstall Dependencies:**
```bash
pip install -r requirements.txt
```

**3. Reset Database:**
```bash
# Backup first!
cp .imxup/imxup.db .imxup/imxup.db.backup

# Run database repair
python -m src.storage.database --repair
```

**4. Check Crash Logs:**
```bash
python check_crash_logs.py
# View crash reports in logs/
```

**5. Run with Debug Output:**
```bash
python imxup.py --debug
# Watch console for error messages
```

---

### GUI Freezes or Hangs

**Symptom:** Application becomes unresponsive, cursor spins

**Common Causes:**
1. **Database locked:** Another process accessing database
2. **Long-running operation:** Large gallery processing
3. **Network timeout:** Slow file host connection
4. **Memory leak:** Large number of galleries loaded

**Solutions:**

**1. Wait for Operation to Complete:**
- Check status bar for progress
- Look for "Processing..." messages
- Wait 30-60 seconds before forcing close

**2. Check Database Locks:**
```bash
# List processes using database
lsof .imxup/imxup.db

# Kill stale processes if needed
kill -9 <PID>
```

**3. Reduce Gallery Count:**
- Close unused galleries: Gallery → Close Gallery
- Enable pagination: Settings → General → Max Galleries per Page

**4. Disable Expensive Features:**
- Disable image sampling: Settings → Display → Sample Images: Off
- Disable auto-refresh: Settings → General → Auto Refresh: Off
- Enable lazy loading: Settings → Performance → Lazy Load Gallery Table

**5. Increase Timeout:**
Settings → Network → Request Timeout: 60 seconds

---

### Slow Gallery Loading

**Symptom:** Gallery table takes 10+ seconds to populate

**Common Causes:**
1. **No lazy loading:** Loading all rows at once
2. **Image sampling enabled:** Processing thousands of images
3. **Hidden column updates:** Calculating hidden column data
4. **No viewport optimization:** Rendering off-screen rows

**Solutions:**

**1. Enable Lazy Loading (Recommended):**
- Settings → Performance → **Lazy Load Gallery Table: On**
- Only loads visible rows (100x faster for large databases)

**2. Disable Image Sampling:**
- Settings → Display → **Sample Images: Off**
- Speeds up initial load significantly

**3. Reduce Sample Count:**
- Settings → Display → **Sample Count: 5** (down from 10)
- Or disable entirely for folders with 1000+ images

**4. Use Viewport Rendering:**
- Already enabled by default in v0.6.00
- Only renders visible table rows
- Automatic scrolling optimization

**5. Hide Unused Columns:**
- Right-click table header → Hide columns not needed
- Fewer columns = faster rendering

---

## Upload Failures

### Network Connection Errors

**Error Messages:**
- "Connection timed out"
- "Network unreachable"
- "Connection reset by peer"

**Solutions:**

**1. Check Internet Connection:**
```bash
ping google.com
# Should show responses
```

**2. Test Host Availability:**
```bash
curl -I https://k2s.cc
# Should return HTTP 200 or 301/302
```

**3. Disable Firewall:**
- Temporarily disable to test
- Add imxup.exe to firewall exceptions
- Check antivirus blocking connections

**4. Use VPN (if host blocked):**
- Some hosts may be region-blocked
- Try different VPN server locations

**5. Reduce Concurrent Connections:**
- Settings → File Hosts → Select Host → Configure
- Max Connections: 1 (instead of 2)
- Prevents overwhelming connection pool

---

### Authentication Failures

**Error Messages:**
- "Login failed with status 401"
- "Unauthorized"
- "Invalid credentials"
- "Anti-CSRF check failed"

**Solutions:**

**1. Verify Credentials:**
- Check username/password for typos
- Test login on host's website manually
- Ensure account is active (not suspended)

**2. Clear Token Cache:**
```bash
rm .imxup/token_cache.db
# Forces re-login on next upload
```

**3. Re-configure Host:**
- Settings → File Hosts → Select Host
- Click **Configure**
- Re-enter credentials
- Click **Test Connection**

**4. Check Account Status:**
- Log into host website
- Verify account not expired/suspended
- Check if premium subscription active

**5. Use Alternative Auth Method:**
- API Key instead of password (if supported)
- Export cookies from browser (for session-based hosts)

---

### File Size Errors

**Error Messages:**
- "File too large"
- "Exceeds maximum file size"
- "Upload quota exceeded"

**Solutions:**

**1. Check File Host Limits:**
| Host | Free Max | Premium Max |
|------|----------|-------------|
| Fileboom | 500 MB | 10 GB |
| Rapidgator | 500 MB | 5 GB |
| Keep2Share | 500 MB | 10 GB |
| Filespace | 2 GB | 10 GB |

**2. Split Large Archives:**
- Use ZIP split: Settings → Archive → Split Size: 2 GB
- Creates multi-part archives (gallery.zip.001, .002, etc.)

**3. Reduce Image Quality:**
- Settings → Processing → Compress Images: On
- Quality: 85% (down from 100%)
- Reduces file size by 30-50%

**4. Use Different Host:**
- Some hosts allow larger files
- Upload to multiple hosts with different limits

**5. Upgrade to Premium:**
- Premium accounts have higher limits
- Worth it for regular uploaders

---

### Upload Stuck/Frozen

**Symptom:** Upload progress stays at same percentage for 5+ minutes

**Solutions:**

**1. Check Network Activity:**
- Look for upload speed in status bar
- If 0 bytes/sec → connection lost

**2. Cancel and Retry:**
- Right-click upload → **Cancel**
- Wait 30 seconds for cleanup
- Right-click gallery → **Retry Upload**

**3. Check Server Status:**
- Visit host website
- Check if maintenance ongoing
- Try different upload time

**4. Reduce File Size:**
- Use compression: ZIP DEFLATE
- Split into smaller archives
- Remove unnecessary files

**5. Try Different Host:**
- If one host consistently fails
- Use alternative from the 6 supported

---

## Database Issues

### Database Locked Error

**Error Message:** "database is locked"

**Cause:** Another process or thread accessing database

**Solutions:**

**1. Close Duplicate Instances:**
```bash
# Linux/Mac
ps aux | grep imxup
kill <PID>

# Windows
tasklist | findstr imxup
taskkill /PID <PID> /F
```

**2. Wait for Operation:**
- Check status bar for active operations
- Wait 30-60 seconds for completion

**3. Restart Application:**
- File → Exit (don't force close!)
- Wait 10 seconds
- Restart imxup

**4. Check File Permissions:**
```bash
chmod 644 .imxup/imxup.db
# Ensure user has write access
```

**5. Repair Database:**
```bash
python -m src.storage.database --repair
```

---

### Database Corruption

**Symptoms:**
- "database disk image is malformed"
- Galleries missing or duplicated
- Crashes on startup
- Foreign key constraint errors

**Solutions:**

**1. Run Integrity Check:**
```bash
sqlite3 .imxup/imxup.db "PRAGMA integrity_check;"
# Should return: ok
```

**2. Vacuum Database:**
```bash
sqlite3 .imxup/imxup.db "VACUUM;"
# Rebuilds database, removes corruption
```

**3. Restore from Backup:**
```bash
# List available backups
ls .db-backups/

# Restore most recent
cp .db-backups/imxup_backup_20250115.db .imxup/imxup.db
```

**4. Export and Re-import:**
```bash
# Export to SQL
sqlite3 .imxup/imxup.db .dump > backup.sql

# Create fresh database
rm .imxup/imxup.db
python imxup.py --init-db

# Import data
sqlite3 .imxup/imxup.db < backup.sql
```

**5. Contact Support:**
- If above fails, attach database file
- Include error logs from View → Logs

---

### Missing Galleries

**Symptom:** Galleries disappeared from table

**Possible Causes:**
1. Deleted accidentally
2. Database corruption
3. Filter active (hiding galleries)
4. Wrong database file loaded

**Solutions:**

**1. Check Active Filters:**
- Top toolbar → Clear all filters
- Search box → Clear search text
- View → Show All Galleries

**2. Verify Database Path:**
- Settings → General → Database Location
- Should be: `.imxup/imxup.db`

**3. Restore from Backup:**
- See "Database Corruption" section above
- Backups created daily in `.db-backups/`

**4. Check Trash/Deleted:**
- Currently no trash feature
- Deleted galleries are permanent
- Use backups to recover

---

## Performance Problems

### High Memory Usage

**Symptom:** imxup using 1+ GB RAM, system slows down

**Common Causes:**
1. Large number of galleries loaded
2. Image sampling enabled on huge folders
3. Memory leak in long-running sessions
4. Large BBCode templates cached

**Solutions:**

**1. Reduce Loaded Galleries:**
- Close unused galleries: Gallery → Close Gallery
- Enable pagination: Settings → General → Max Galleries: 100

**2. Disable Image Sampling:**
- Settings → Display → Sample Images: Off
- Reduces memory by 70-80%

**3. Restart Application:**
- File → Exit
- Restart imxup
- Clears memory leaks

**4. Increase System RAM:**
- Upgrade from 4 GB → 8 GB or higher
- Close other memory-heavy apps

**5. Use 64-bit Python:**
```bash
python --version
# Should show x64 or amd64
```

---

### Slow File Operations

**Symptom:** Adding galleries or renaming files takes minutes

**Solutions:**

**1. Check Disk Speed:**
```bash
# Linux
hdparm -t /dev/sda

# Windows
winsat disk -seq -read -drive c
```

**2. Use SSD Instead of HDD:**
- Move `.imxup/` to SSD
- 10-100x faster database operations

**3. Reduce File Count:**
- Split large folders into smaller galleries
- Use filters to hide processed galleries

**4. Disable Auto-Refresh:**
- Settings → General → Auto Refresh: Off
- Manually refresh: Ctrl+R

**5. Close Background Apps:**
- Antivirus scanning files
- Cloud sync (Dropbox, OneDrive)
- Windows Search indexing

---

### Startup Bottlenecks

**Symptom:** Application takes 30+ seconds to start

**Common Causes:**
1. Loading large BBCode template library
2. Initializing GUI with thousands of galleries
3. Validating all file host configurations

**Solutions:**

**1. Enable Startup Profiling:**
```bash
python diagnose_startup.py
# Shows which components are slow
```

**2. Reduce BBCode Templates:**
- Settings → BBCode → Templates
- Delete unused templates
- Keep only 5-10 active templates

**3. Archive Old Galleries:**
- Export old galleries to CSV
- Delete from database
- Import only when needed

**4. Disable File Host Auto-Connect:**
- Settings → File Hosts → Uncheck "Connect on Startup"
- Hosts will connect on first upload instead

---

## Archive Creation Failures

### ZIP Creation Errors

**Error Messages:**
- "Permission denied"
- "Disk full"
- "Invalid characters in filename"

**Solutions:**

**1. Check Disk Space:**
```bash
df -h  # Linux/Mac
wmic logicaldisk get size,freespace,caption  # Windows
```

**2. Verify Folder Permissions:**
```bash
chmod -R 755 /path/to/gallery
# Ensure read/write access
```

**3. Fix Invalid Filenames:**
- Avoid: `< > : " / \ | ? *`
- Use Gallery → Rename Files → Auto-Fix Special Characters

**4. Use Temporary Directory:**
- Settings → Archive → Temp Directory: `/tmp` (Linux) or `C:\Temp` (Windows)
- Ensure temp dir has sufficient space

**5. Change Compression:**
- Settings → Archive → Compression: STORE
- No compression = faster + fewer errors

---

### Archive Size Mismatch

**Symptom:** ZIP file much larger/smaller than expected

**Solutions:**

**1. Check Compression Setting:**
- STORE: No compression (1:1 size ratio)
- DEFLATE: Compression (varies by file type)
- Images rarely compress (already compressed)

**2. Include/Exclude Files:**
- Settings → Archive → Include Hidden Files: Off
- Settings → Archive → Exclude Patterns: `.DS_Store, Thumbs.db`

**3. Verify File Count:**
- Right-click gallery → Properties
- Check: Files in Folder vs Files in Archive

**4. Check for Corruption:**
```bash
unzip -t gallery.zip
# Should show: No errors detected
```

---

## BBCode Template Issues

### Template Syntax Errors

**Error Messages:**
- "Unmatched conditional tags"
- "Invalid [if] syntax"
- "Unmatched [url] tags"

**Solutions:**

**1. Validate Template:**
- Settings → BBCode → Templates
- Select template → **Validate Syntax**
- Fix errors shown in dialog

**2. Check Conditional Pairing:**
```
Correct:
[if folderName]Content[/if]

Wrong:
[if folderName]Content  ← Missing [/if]
```

**3. Match Opening/Closing Tags:**
```
Correct:
[b]Bold text[/b]

Wrong:
[b]Bold text  ← Missing [/b]
```

**4. Use Template Helper:**
- Click **[if] Helper** button
- Auto-generates correct conditional syntax

**5. Copy from Working Template:**
- Start with default template
- Modify incrementally
- Validate after each change

---

### Missing Placeholders

**Symptom:** Placeholder like `#folderName#` appears literally in output

**Cause:** Placeholder not recognized or gallery data missing

**Solutions:**

**1. Verify Placeholder Name:**
Correct placeholders:
```
#folderName#     - Gallery name
#pictureCount#   - Number of images
#width#          - Image width (px)
#height#         - Image height (px)
#longest#        - Longest side (px)
#extension#      - File extension
#folderSize#     - Total size (MB)
#galleryLink#    - Link to gallery
#allImages#      - All image BBCode
#hostLinks#      - File host download links
#custom1-4#      - Custom fields
#ext1-4#         - Extension fields
```

**2. Check Gallery Data:**
- Right-click gallery → **Properties**
- Ensure fields are populated (not blank)

**3. Re-process Gallery:**
- Right-click gallery → **Re-analyze**
- Forces data refresh

**4. Use Default Template:**
- Switch to "default" template
- Verify placeholders work there
- Copy working syntax to custom template

---

### Conditional Logic Not Working

**Example:**
```
[if pictureCount]
  Found #pictureCount# images
[/if]
```
Shows nothing even though gallery has images.

**Solutions:**

**1. Check Conditional Syntax:**
```
Correct:
[if pictureCount]Content[/if]      ← Tests if not empty
[if pictureCount=50]Content[/if]   ← Tests if equals 50

Wrong:
[if #pictureCount#]Content[/if]    ← Don't include # in condition
```

**2. Verify Field Has Value:**
- Right-click gallery → Properties
- Check if "Picture Count" shows number (not blank)

**3. Use Else Clause for Debugging:**
```
[if pictureCount]
  Has images: #pictureCount#
[else]
  No images or field empty
[/if]
```

**4. Check for Whitespace:**
- `[if pictureCount ]` ← Extra space causes failure
- Should be: `[if pictureCount]`

---

## Keyboard Shortcuts Not Working

**Solutions:**

**1. Check Modifier Keys:**
- Ensure Ctrl (not Cmd on Mac, unless configured)
- Check Shift, Alt combinations

**2. Resolve Conflicts:**
- Settings → Keyboard → **Show Conflicts**
- Disable conflicting shortcuts

**3. Reset to Defaults:**
- Settings → Keyboard → **Reset All Shortcuts**

**4. Check Focus:**
- Some shortcuts only work when table has focus
- Click on gallery table first

**5. See Full List:**
- Help → Keyboard Shortcuts (or press F1)

---

## How to Report a Bug

### Before Reporting

**1. Check if Known Issue:**
- Search GitHub Issues: https://github.com/[repo]/issues
- Check latest release notes

**2. Try Latest Version:**
```bash
git pull
pip install -r requirements.txt --upgrade
```

**3. Reproduce Consistently:**
- Note exact steps to trigger bug
- Try on fresh database (if possible)

### Information to Include

**1. System Details:**
```
OS: Windows 11 / Ubuntu 22.04 / macOS 14
Python: 3.14.1
imxup Version: v0.6.00
```

**2. Error Logs:**
- View → Logs
- Filter by "ERROR" or "WARNING"
- Copy last 50-100 lines
- Or attach: `logs/imxup.log`

**3. Steps to Reproduce:**
```
1. Open imxup
2. Add gallery with 100+ images
3. Click Upload to Rapidgator
4. Error appears after 50% upload
```

**4. Expected vs Actual:**
- Expected: Upload completes successfully
- Actual: Error "database locked" appears

**5. Screenshots/Videos:**
- Screenshot of error dialog
- Screen recording of bug occurring

### Where to Report

**GitHub Issues:**
https://github.com/[your-repo]/issues

**Template:**
```markdown
**Bug Description:**
Brief description

**Steps to Reproduce:**
1. Step one
2. Step two
3. Error occurs

**Expected Behavior:**
What should happen

**Actual Behavior:**
What actually happens

**Environment:**
- OS:
- Python:
- imxup Version:

**Logs:**
```
[Paste relevant logs here]
```

**Screenshots:**
[Attach if applicable]
```

---

## Log Files and Debugging

### Log Locations

**Main Log:**
`logs/imxup.log` - All application activity

**Crash Logs:**
`logs/crash_*.log` - Uncaught exceptions

**Network Logs:**
View → Logs → Filter: "FileHostClient"

### Log Viewer Features

**Filters:**
- Level: DEBUG, INFO, WARNING, ERROR
- Source: Component name (e.g., "FileHostClient")
- Text Search: Any keyword

**Export Logs:**
- View → Logs → **Export to File**
- Saves filtered view as text file

**Auto-Refresh:**
- Settings → Logs → **Auto Refresh: On**
- Updates in real-time

### Understanding Log Levels

**DEBUG:** Detailed diagnostic information
```
DEBUG: Extracted session ID: abc123... (src.network.file_host_client)
```

**INFO:** Normal operation events
```
INFO: Upload complete for My_Gallery.zip (src.processing.upload_workers)
```

**WARNING:** Potentially harmful situations
```
WARNING: Token TTL expired, refreshing... (src.network.file_host_client)
```

**ERROR:** Error events, may allow continued operation
```
ERROR: Upload failed: Connection timeout (src.processing.upload_workers)
```

**CRITICAL:** Severe errors causing shutdown
```
CRITICAL: Database corruption detected, exiting (src.storage.database)
```

### Increasing Log Verbosity

**1. Enable Debug Mode:**
Settings → Logs → **Log Level: DEBUG**

**2. Command Line:**
```bash
python imxup.py --debug
# Outputs to console + file
```

**3. Component-Specific:**
```python
# In settings.json
"logging": {
  "level": "DEBUG",
  "components": {
    "FileHostClient": "DEBUG",
    "Database": "INFO"
  }
}
```

---

## Advanced Troubleshooting

### Database Maintenance Commands

**Integrity Check:**
```bash
sqlite3 .imxup/imxup.db "PRAGMA integrity_check;"
```

**Foreign Key Check:**
```bash
sqlite3 .imxup/imxup.db "PRAGMA foreign_key_check;"
```

**Optimize Database:**
```bash
sqlite3 .imxup/imxup.db "PRAGMA optimize;"
```

**Table Statistics:**
```bash
sqlite3 .imxup/imxup.db "SELECT name, COUNT(*) FROM sqlite_master GROUP BY type;"
```

### Network Debugging

**Test File Host API:**
```bash
# Rapidgator login
curl -X GET "https://rapidgator.net/api/v2/user/login?login=user&password=pass"

# Keep2Share account info
curl -X POST "https://k2s.cc/api/v2/accountInfo" \
  -H "Content-Type: application/json" \
  -d '{"access_token": "your-key"}'
```

**Check SSL Certificates:**
```bash
python -c "import certifi; print(certifi.where())"
# Should show valid certificate bundle path
```

**Trace Network Requests:**
```bash
# Linux/Mac
tcpdump -i any port 443 -w upload.pcap

# Windows
# Use Wireshark or Fiddler
```

### Memory Profiling

**Track Memory Usage:**
```bash
pip install memory_profiler
python -m memory_profiler imxup.py
```

**Heap Dump:**
```python
from guppy import hpy
h = hpy()
print(h.heap())
```

### Performance Profiling

**CPU Profiling:**
```bash
python -m cProfile -o profile.stats imxup.py
python -m pstats profile.stats
```

**Startup Profiling:**
```bash
python diagnose_startup.py
# Shows component load times
```

---

## Getting Additional Help

**Documentation:**
- `docs/QUICK_START_GUI.md` - Getting started
- `docs/GUI_IMPROVEMENTS.md` - Latest features
- `docs/KEYBOARD_SHORTCUTS.md` - Shortcuts reference
- `docs/user/multi-host-upload.md` - File host guide
- `docs/user/bbcode-templates.md` - Template guide

**Community:**
- GitHub Discussions: https://github.com/[repo]/discussions
- GitHub Issues: https://github.com/[repo]/issues

**Contact:**
- Email: [support-email]
- Discord: [invite-link]

---

**Remember:** Always backup your database before major operations!

Location: `.imxup/imxup.db`
Backups: `.db-backups/`
