# Frequently Asked Questions (FAQ)

**Version:** 0.6.16
**Last Updated:** 2026-01-03

---

## Table of Contents

1. [Getting Started](#getting-started) (5 questions)
2. [Upload Issues](#upload-issues) (5 questions)
3. [Multi-Host Upload](#multi-host-upload) (5 questions)
4. [BBCode Templates](#bbcode-templates) (3 questions)
5. [Troubleshooting](#troubleshooting) (5 questions)

---

## Getting Started

### How do I install IMXuploader?

**Option 1: From Source (Recommended)**
```bash
# Clone repository
git clone <repository-url>
cd IMXuploader

# Install dependencies
pip install -r requirements.txt

# Run GUI
python imxup.py --gui
```

**Option 2: Windows Executable**
- Download the latest `imxup-*.exe` from releases
- Extract to a folder
- Double-click `imxup.exe`

**Option 3: Python Package**
```bash
pip install imxup
python -m imxup --gui
```

See [Quick Start](../getting-started/quick-start.md) for detailed installation steps.

---

### How do I add folders to the upload queue?

**Method 1: Drag & Drop (Easiest)**
1. Open IMXuploader GUI (`python imxup.py --gui`)
2. Drag image folders directly into the "Upload Queue" area
3. Folders are automatically validated and added

**Method 2: Command Line**
```bash
python imxup.py --gui "/path/to/folder"
```

**Method 3: Windows Context Menu**
1. Right-click any folder in Windows Explorer
2. Select "Upload to imx.to (GUI)"
3. GUI opens with folder pre-loaded

To enable context menu: `python imxup.py --install-context-menu`

**Supported Image Formats:** `.jpg`, `.jpeg`, `.png`, `.gif`

---

### What does each upload status mean?

- **Queued** - Waiting in queue, upload hasn't started
- **Scanning** - Analyzing gallery (counting images, calculating size)
- **Validating** - Verifying upload parameters before start
- **Uploading** - Currently uploading to imx.to
- **Paused** - Upload paused, can resume later
- **Completed** - Successfully uploaded
- **Failed** - Upload failed (check logs for error)
- **Retrying** (1/3) - Auto-retry in progress

---

### How do I start uploading?

1. **Add galleries** to the queue (drag & drop or command line)
2. Click **Start All** button to upload all queued galleries
3. Or right-click a gallery → **Start** to upload just that one
4. Monitor progress in the status bar and individual progress bars

To pause: Click **Pause All** or right-click gallery → **Pause**

---

### Where are my galleries stored?

Gallery data is stored in two places:

**Database Location:**
- Windows: `%USERPROFILE%\.imxup\imxup.db`
- Linux/Mac: `~/.imxup/imxup.db`

**Original Files:**
- Image files stay in their original folder (not copied or moved)
- Only metadata (name, size, status) stored in database

To change database location: Settings → General → Database Location

---

## Upload Issues

### Why did my upload fail?

**Check logs for error message:**
1. Click **Help** → **View Logs** (or press Ctrl+L)
2. Filter by "ERROR" level
3. Look for messages about connection, authentication, or file size

**Common causes and fixes:**

| Error | Cause | Fix |
|-------|-------|-----|
| "Connection timed out" | Network issue | Check internet, retry upload |
| "Unauthorized (401)" | Bad credentials | Settings → Verify credentials |
| "File too large" | Exceeds host limit | Compress images or split into smaller gallery |
| "Disk full" | No space for temp files | Free up disk space |
| "Permission denied" | Can't write temp files | Check folder permissions |

For detailed solutions, see [Troubleshooting Guide](troubleshooting.md#upload-failures).

---

### How do I retry a failed upload?

**Manual Retry:**
1. Right-click failed gallery → **Retry Upload**
2. Or select gallery and press Ctrl+R

**Automatic Retry:**
IMXuploader automatically retries failed uploads 3 times (configurable).

**Check retry count:**
- Status bar shows: `Retrying (2/3)` = 2nd retry attempt
- After 3 failed attempts, status shows: "Failed"

**To increase retry attempts:**
Settings → Upload → Max Retries: [1-10]

---

### Why does the upload seem stuck?

**Check if it's actually uploading:**
1. Look at status bar for upload speed (e.g., "2.5 MB/s")
2. If 0 bytes/sec → connection lost or server issue
3. Wait 1-2 minutes (large files take time)

**If truly stuck (no speed for 5+ minutes):**
1. Right-click gallery → **Cancel**
2. Wait 30 seconds for cleanup
3. Right-click → **Retry Upload**

**Network issues:**
- Firewall blocking connection → Add imxup.exe to exceptions
- VPN available? → Some regions block hosting sites

---

### How do I upload to multiple hosts at once?

See **Multi-Host Upload** section below. IMXuploader supports uploading a single gallery to up to 6 file hosts simultaneously.

**Quick setup:**
1. Settings → File Hosts
2. Select each host (Fileboom, Rapidgator, Keep2Share, etc.)
3. Click **Configure** and enter API key or credentials
4. Click **Test Connection**
5. Galleries automatically upload to all enabled hosts

---

## Multi-Host Upload

### Which file hosts does IMXuploader support?

IMXuploader supports **6 premium file hosts:**

1. **Fileboom** (fboom.me)
   - Max file: 10 GB | Storage: 10 TB
   - Auth: API Key

2. **Rapidgator** (rapidgator.net)
   - Max file: 5 GB | Storage: 1 TB+
   - Auth: Username/Password

3. **Keep2Share** (k2s.cc)
   - Max file: 10 GB | Storage: 10 TB
   - Auth: API Key

4. **Filespace** (filespace.com)
   - Max file: 10 GB | Storage: 10 TB
   - Auth: Username/Password

5. **Filedot** (filedot.to)
   - Max file: 5 GB
   - Auth: Username/Password

6. **Tezfiles** (tezfiles.com)
   - Auth: API Key

All hosts enabled = all hosts receive same gallery automatically.

For detailed setup, see [Multi-Host Upload Guide](../guides/multi-host-upload.md).

---

### How do I add credentials for file hosts?

**For API Key Hosts (Fileboom, Keep2Share, Tezfiles):**
1. Log into host account
2. Navigate to Account → API Settings or similar
3. Copy/generate your API key
4. IMXuploader Settings → File Hosts → Select host → Configure
5. Paste API key into credentials field
6. Click **Test Connection** to verify
7. Click **Save**

**For Username/Password Hosts (Rapidgator, Filedot, Filespace):**
1. IMXuploader Settings → File Hosts → Select host → Configure
2. Enter credentials as: `username:password`
3. Click **Test Connection**
4. Click **Save**

**Where are credentials stored?**
- Primary: System Keyring (Windows Credential Manager, Linux Secret Service)
- Fallback: Encrypted in `~/.imxup/imxup.ini`
- All credentials encrypted at rest using Fernet (AES-128)

---

### What's the difference between API Key and Username/Password?

| Feature | API Key | Username/Password |
|---------|---------|-------------------|
| **Expires** | Never (permanent) | Can expire |
| **Security** | Very high | High |
| **Setup** | 1-time copy | Each time needed |
| **Hosts** | Fileboom, Keep2Share, Tezfiles | Rapidgator, Filedot, Filespace |

**Recommendation:** Use API Key hosts when possible (more secure, never expires).

---

### How many galleries can I upload simultaneously?

**Global limit:** 3 concurrent uploads across all hosts
**Per-host limit:** 2 concurrent uploads per host

This ensures:
- Reliable uploads without overwhelming servers
- Better performance than 10+ simultaneous connections
- Fair resource usage

**To change limits:**
Settings → File Hosts → Global Max Connections: [1-10]

---

### Where can I find my download links?

After upload completes:

**In IMXuploader:**
1. Right-click gallery → **View BBCode**
2. Look for section: `[b]Download:[/b]`
3. Lists all file host download links

**Or copy from template:**
- BBCode templates include `#hostLinks#` placeholder
- Automatically inserts all download links
- Auto-copy to clipboard if enabled (Settings → BBCode)

**In Gallery Properties:**
1. Right-click gallery → **Properties**
2. View all download links and metadata

---

## BBCode Templates

### How do I customize my gallery BBCode output?

**Access Template Editor:**
Settings → BBCode → **Manage Templates**

**Create New Template:**
1. Click **New**
2. Enter template name
3. Build template using:
   - Plain text and BBCode tags (`[b]`, `[i]`, `[url]`, etc.)
   - Placeholders like `#folderName#`, `#pictureCount#`, etc.
   - Conditionals: `[if placeholder]...[/if]`

**Example Template:**
```bbcode
[center][b]#folderName#[/b][/center]

[b]Gallery Info:[/b]
- Images: #pictureCount# (#extension# format)
- Resolution: #width#x#height#
- Size: #folderSize#

[if galleryLink]
[b]Gallery:[/b] [url=#galleryLink#]View on imx.to[/url]
[/if]

[if hostLinks]
[b]Downloads:[/b]
#hostLinks#
[/if]

[b]Images:[/b]
#allImages#
```

**Save and Apply:**
1. Click **Save**
2. Settings → BBCode → Default Template: [Your Template]
3. New uploads use this template automatically

See [BBCode Templates Guide](../guides/bbcode-templates.md) for full syntax.

---

### What placeholders can I use in templates?

**18 Available Placeholders:**

| Placeholder | Description | Example |
|-------------|-------------|---------|
| `#folderName#` | Gallery name | `Summer Vacation` |
| `#pictureCount#` | Number of images | `127` |
| `#width#` | Average image width | `4000` |
| `#height#` | Average image height | `3000` |
| `#longest#` | Longest dimension | `4000` |
| `#extension#` | Image format | `JPG` |
| `#folderSize#` | Total gallery size | `245.8 MB` |
| `#galleryLink#` | imx.to gallery URL | `https://imx.to/g/abc123` |
| `#allImages#` | All image BBCode | `[img]...[/img]...` |
| `#hostLinks#` | File host links | `[url=...]Fileboom[/url]` |
| `#custom1-4#` | User-defined fields | Photographer, location, etc. |
| `#ext1-4#` | External app outputs | Processing results, links |

**Using Custom Fields:**
Right-click gallery → **Properties** → Set Custom Fields (Photographer, Location, License, etc.)

---

### My placeholder shows literally instead of value. Why?

**Causes:**
1. Placeholder name is wrong (typo)
2. Gallery data missing for that field
3. Template syntax error

**Solutions:**
1. Check spelling: Is it `#folderName#` or `#foldername#`? (case matters)
2. Verify gallery data: Right-click → Properties → Check if field populated
3. Test with default template first (works with all galleries)

**Force data refresh:**
Right-click gallery → **Re-analyze** (recalculates dimensions, count, size)

---

## Troubleshooting

### Where are the log files located?

**View Logs in GUI:**
- Click **Help** → **View Logs** (or press Ctrl+L)
- Real-time log viewer with filtering and search
- Export logs: View Logs → Export to File

**Log Files on Disk:**
- Windows: `%USERPROFILE%\.imxup\logs\imxup.log`
- Linux/Mac: `~/.imxup/logs/imxup.log`
- Crash logs: Same directory, `crash_*.log`

**Increase Log Verbosity:**
Settings → Logging → Log Level: **DEBUG** (for detailed info)

Or launch with: `python imxup.py --debug`

---

### How do I backup my database?

**Manual Backup:**
```bash
# Copy database file
cp ~/.imxup/imxup.db ~/.imxup/imxup.db.backup

# Or on Windows
copy %USERPROFILE%\.imxup\imxup.db %USERPROFILE%\.imxup\imxup.db.backup
```

**Automatic Backups:**
- Created daily in `~/.imxup/.db-backups/`
- Keeps last 7 days of backups
- Automatically cleaned up

**Restore from Backup:**
```bash
# Stop IMXuploader
# Restore backup
cp ~/.imxup/.db-backups/imxup_backup_20250101.db ~/.imxup/imxup.db
# Restart IMXuploader
```

**For database corruption issues**, see [Troubleshooting Guide](troubleshooting.md#database-issues).

---

### How do I report a bug?

**Before Reporting:**
1. Check [Troubleshooting Guide](troubleshooting.md) for known solutions
2. Try latest version: `git pull && pip install -r requirements.txt`
3. Check logs: Help → View Logs

**Information to Include:**
1. **System Details:**
   - OS: Windows 11 / Ubuntu 22.04 / macOS 14
   - Python version: `python --version`
   - IMXuploader version: Help → About

2. **Error Logs:**
   - Help → View Logs
   - Filter by ERROR or WARNING
   - Copy relevant lines

3. **Steps to Reproduce:**
   ```
   1. Add gallery with X images
   2. Upload to [host name]
   3. Error appears at X% completion
   ```

4. **Expected vs Actual:**
   - Expected: Gallery uploads successfully
   - Actual: Error "database locked" appears

**Where to Report:**
- GitHub Issues on project repository
- Include logs and screenshots
- Use bug report template (if available)

See [full bug reporting guide](troubleshooting.md#how-to-report-a-bug).

---

### My GUI doesn't start. What's wrong?

**Check Python Version:**
```bash
python --version
# Should be 3.10 or higher
```

**Install Dependencies:**
```bash
pip install -r requirements.txt
```

**Check for Errors:**
```bash
python imxup.py --gui --debug
# Watch console output for error messages
```

**Common Issues:**

| Error | Fix |
|-------|-----|
| "ModuleNotFoundError: PyQt6" | `pip install PyQt6` |
| "database is locked" | Close other IMXuploader instances |
| "Crash on startup" | Reset database: `rm ~/.imxup/imxup.db` (backup first!) |
| "GUI freezes" | Check logs for slow operations, restart app |

For detailed help, see [Troubleshooting - GUI Errors](troubleshooting.md#gui-errors-and-solutions).

---

## Quick Reference

### Keyboard Shortcuts
- **Ctrl+,** - Settings
- **Ctrl+L** - View Logs
- **Ctrl+C** - Copy BBCode
- **Ctrl+T** - New tab
- **Delete** - Remove selected gallery
- **F2** - Rename gallery

### File Locations
- Database: `~/.imxup/imxup.db`
- Config: `~/.imxup/imxup.ini`
- Logs: `~/.imxup/logs/imxup.log`
- Backups: `~/.imxup/.db-backups/`
- Templates: `~/.imxup/templates/`

### Common Commands
```bash
# Launch GUI
python imxup.py --gui

# Launch with debug logging
python imxup.py --gui --debug

# Add folder to existing GUI
python imxup.py --gui "/path/to/folder"

# Install Windows context menu
python imxup.py --install-context-menu

# Check Python version
python --version

# View database info
sqlite3 ~/.imxup/imxup.db "SELECT COUNT(*) FROM galleries;"
```

---

## Need More Help?

| Topic | Link |
|-------|------|
| Getting Started | [Quick Start Guide](../getting-started/quick-start.md) |
| GUI Features | [GUI Guide](../guides/gui-guide.md) |
| Multi-Host Upload | [Multi-Host Guide](../guides/multi-host-upload.md) |
| BBCode Templates | [Template Guide](../guides/bbcode-templates.md) |
| Troubleshooting | [Full Troubleshooting Guide](troubleshooting.md) |
| Features List | [Complete Features](../reference/FEATURES.md) |
| Keyboard Shortcuts | [Shortcuts Reference](../getting-started/keyboard-shortcuts.md) |

**Still need help?**
- Check GitHub Issues (may find your answer)
- View logs with Help → View Logs
- Contact project maintainers

---

**Version:** 0.6.16 | **Last Updated:** 2026-01-03
