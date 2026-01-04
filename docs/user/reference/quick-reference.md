# IMXuploader Quick Reference

A concise reference card for common operations and settings.

---

## Starting the Application

```bash
# GUI Mode (recommended)
python imxup.py --gui

# CLI Mode
python imxup.py /path/to/folder --name "Gallery Name"

# Debug Mode (verbose logging)
python imxup.py --gui --debug
```

---

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| Ctrl+O | Add folders to queue |
| Ctrl+N | New tab |
| Ctrl+W | Close tab |
| Ctrl+T | New tab |
| Ctrl+. | Show keyboard shortcuts |
| F1 | Help |
| Del | Remove selected galleries |
| Ctrl+A | Select all |
| Ctrl+Shift+A | Deselect all |
| Ctrl+C | Copy BBCode output |
| Ctrl+S | Save settings |
| Escape | Cancel current operation |

---

## Gallery States

| State | Icon | Description |
|-------|------|-------------|
| Validating | ... | Checking folder contents |
| Scanning | ... | Counting images and calculating size |
| Ready | Green | Scanned and ready to upload |
| Queued | Blue | Waiting in upload queue |
| Uploading | Arrow | Currently uploading |
| Completed | Check | Upload finished successfully |
| Failed | Red X | Upload failed (check logs) |
| Paused | Pause | Upload paused by user |
| Incomplete | Yellow | Partially uploaded |

---

## Configuration Files

| File | Purpose |
|------|---------|
| `~/.imxup/imxup.ini` | User settings and preferences |
| `~/.imxup/imxup.db` | Queue database (SQLite) |
| `~/.imxup/templates/` | Custom BBCode templates |
| `~/.imxup/logs/` | Application logs |

**Note:** On Windows, `~` refers to `%USERPROFILE%` (e.g., `C:\Users\YourName`).

---

## Common CLI Options

```bash
--gui              # Launch GUI mode
--name "Name"      # Set gallery name
--thumb-size N     # Thumbnail size (1-6)
--content-type N   # Content type (0=SFW, 1=NSFW)
--debug            # Enable debug logging
--help             # Show all options
--version          # Show version number
```

### CLI Examples

```bash
# Upload a folder with custom name
python imxup.py "C:\Photos\Vacation" --name "Summer Vacation 2024"

# Upload with specific thumbnail size
python imxup.py /path/to/folder --thumb-size 3

# Upload NSFW content
python imxup.py /path/to/folder --content-type 1
```

---

## File Host Support

### Premium File Hosts

| Host | Auth Type | Status |
|------|-----------|--------|
| Fileboom | API Key | Supported |
| Filedot | Session | Supported |
| Filespace | Session | Supported |
| Katfile | API Key | Supported |
| Keep2Share | API Key | Supported |
| Rapidgator | Token Login | Supported |
| Tezfiles | API Key | Supported |

### Additional Hosts

44+ additional hosts available via the external hooks system.

---

## Supported Image Formats

- **Standard:** JPG, JPEG, PNG, GIF
- **Additional:** BMP, WEBP, TIFF (converted on upload)

---

## Supported Archive Formats

| Format | Extension |
|--------|-----------|
| ZIP | .zip |
| RAR | .rar |
| 7-Zip | .7z |
| TAR | .tar |
| Gzipped TAR | .tar.gz, .tgz |
| Bzipped TAR | .tar.bz2 |

Archives are automatically extracted before upload.

---

## BBCode Template Placeholders

| Placeholder | Description |
|-------------|-------------|
| `{gallery_name}` | Gallery display name |
| `{gallery_url}` | IMX.to gallery URL |
| `{image_count}` | Number of images |
| `{total_size}` | Total size (formatted) |
| `{upload_date}` | Upload timestamp |
| `{thumb_url}` | Thumbnail URL |
| `{image_url}` | Full image URL |
| `{download_url}` | File host download link |

See the full template documentation for all 18 placeholders.

---

## Quick Tips

1. **Drag and Drop:** Drag folders directly onto the queue table to add them.
2. **Batch Selection:** Use Shift+Click to select a range of galleries.
3. **Right-Click Menu:** Access gallery actions via context menu.
4. **System Tray:** Minimize to tray for background uploads.
5. **Tab Colors:** Assign colors to tabs for visual organization.

---

## Troubleshooting Quick Fixes

| Problem | Solution |
|---------|----------|
| Upload stuck | Check internet connection, try pause/resume |
| Login failed | Verify credentials in Settings |
| Gallery not appearing | Ensure folder contains supported images |
| Slow uploads | Reduce concurrent uploads in Settings |
| Database locked | Close other IMXuploader instances |

---

## Getting Help

- **F1 Key:** Opens built-in help
- **Ctrl+.:** Shows all keyboard shortcuts
- **Logs:** Check `~/.imxup/logs/` for detailed error messages
- **Debug Mode:** Run with `--debug` for verbose output

---

## Version Information

Check your version: `python imxup.py --version`

Current version information and changelog available in the application Help menu.

---

*Last Updated: 2025-12-28*
