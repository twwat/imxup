# External Hooks and Automation Guide

**Version:** 0.6.16
**Last Updated:** 2026-01-03

---

## Quick Reference

**What:** Execute custom scripts at key upload events
**When:** Before/during/after gallery uploads
**Why:** Extend imxup with multi-host uploads, notifications, backups, custom processing
**Setup:** Settings -> External Apps

---

## What Are Hooks?

Hooks are external programs (Python scripts, shell commands, executables) that imxup runs automatically at specific points in the upload workflow. They enable powerful automation like:

- **Multi-host uploads** - Automatically upload to GoFile, Pixeldrain, etc. after imx.to completes
- **Notifications** - Send alerts when uploads start/finish
- **Backups** - Archive galleries to cloud storage
- **Processing** - Resize images, generate previews, update databases
- **Post-processing** - Rename galleries on imx.to, update metadata

### Real-World Example

Upload a gallery to both imx.to and GoFile:

1. You drag a folder into imxup
2. Gallery uploads to imx.to (takes 2 minutes)
3. imxup automatically:
   - Creates a ZIP file from the gallery
   - Runs `python hooks/muh.py gofile vacation.zip`
   - Captures the GoFile download link
   - Stores link in the `ext1` field
4. Gallery is now available on both hosts

---

## Hook Types

imxup supports **4 different hook events**:

### 1. On Gallery Added
**Trigger:** When gallery is added to the queue

**Available Parameters:**
- Gallery info: `%N` (name), `%p` (path), `%C` (image count), `%s` (size)
- User fields: `%c1` - `%c4` (custom fields)

**Use Cases:**
- Validate gallery before upload
- Log gallery additions
- Pre-process images

**Example:**
```bash
python notify.py "Gallery added: %N (%C images)"
```

---

### 2. On Gallery Started
**Trigger:** When upload to imx.to begins

**Available Parameters:**
Same as "On Gallery Added"

**Use Cases:**
- Send "upload started" notification
- Lock gallery folder
- Start monitoring upload progress

**Example:**
```bash
curl -X POST https://discord.com/api/webhooks/123... \
  -d '{"content":"Started uploading: %N"}'
```

---

### 3. On Gallery Completed
**Trigger:** When gallery successfully uploads to imx.to

**Available Parameters:**
- All from above PLUS:
- Gallery ID: `%g` (imx.to gallery ID)
- ZIP path: `%z` (auto-created temporary ZIP)
- Artifacts: `%j` (JSON metadata), `%b` (BBCode file)
- External fields: `%e1` - `%e4` (previous hook outputs)

**Use Cases:**
- **Multi-host uploads** - Upload to additional file hosts
- **Backups** - Archive to cloud storage
- **Notifications** - Send completion alert with gallery link
- **Database updates** - Update external tracking system

**Example:**
```bash
# Upload to GoFile (most common use case)
python hooks/muh.py gofile "%z"

# Or upload to multiple hosts
python hooks/muh.py gofile "%z" && python hooks/muh.py pixeldrain "%z"
```

---

### 4. On Upload Failed
**Trigger:** When gallery upload to imx.to fails (after all retries)

**Available Parameters:**
Same as "On Gallery Added" (gallery info only, no artifact data)

**Use Cases:**
- Send error notification
- Log failed uploads
- Trigger automatic retry with different settings

**Example:**
```bash
python notify.py --error "Upload failed: %N" --path "%p"
```

---

## Configuration

### Step 1: Open Settings

In imxup, go to **Settings (Ctrl+,)** → **External Apps** tab

### Step 2: Add External App

Click **Add App** to create a new hook configuration.

### Step 3: Configure Hook

Fill in the configuration fields:

| Field | Description | Example |
|-------|-------------|---------|
| **Name** | Display name | "Upload to GoFile" |
| **Command** | Executable path | `python` |
| **Arguments** | Command arguments | `hooks/muh.py gofile "%z"` |
| **Working Directory** | Execution folder | (leave blank for auto) |
| **Capture Output** | Capture stdout/stderr | Yes (if mapping JSON) |
| **Execute On** | When to run | "completed" |
| **Timeout** | Max execution seconds | 300 (5 minutes) |

### Step 4: Map Output (Optional)

If your hook outputs JSON, map fields to `ext1` - `ext4`:

**Example:** Multi-host uploader returns:
```json
{
  "download_link": "https://gofile.io/d/abc123",
  "file_id": "abc123",
  "upload_time": 12.34
}
```

Map these to:
- `ext1` ← `$.download_link` (JSON path)
- `ext2` ← `$.file_id`
- `ext3` ← `$.upload_time`

Then use in BBCode template: `Download: #ext1# | File ID: #ext2#`

### Step 5: Test

Click **Configure & Test** to:
- See parameter substitution in real-time
- View parsed JSON output
- Verify your mapping works

---

## Available Parameters

### Gallery Information

| Parameter | Description | Example |
|-----------|-------------|---------|
| `%N` | Gallery name | `Summer Vacation` |
| `%T` | Tab name | `Main` |
| `%p` | Gallery folder path | `C:\Images\vacation` |
| `%C` | Image count | `127` |
| `%s` | Total size (bytes) | `245823412` |
| `%t` | BBCode template name | `Detailed Example` |

### Completed Events Only

| Parameter | Description | Example |
|-----------|-------------|---------|
| `%g` | Gallery ID (imx.to) | `abc123xyz` |
| `%j` | JSON artifact path | `~/.imxup/artifacts/abc123.json` |
| `%b` | BBCode file path | `~/.imxup/bbcode/abc123.txt` |
| `%z` | ZIP archive path (auto-created) | `/tmp/imxup_abc123_vacation.zip` |

### Custom & External Fields

| Parameter | Description | Example |
|-----------|-------------|---------|
| `%c1` - `%c4` | Custom field values | User-defined |
| `%e1` - `%e4` | External app outputs | Previous hook results |

For the complete parameter reference, see [external-apps-parameters.md](../reference/external-apps-parameters.md).

---

## Example Scripts

### Simple Python Hook

**File:** `hooks/notify.py`

```python
#!/usr/bin/env python3
import json
import sys

# Parse arguments from imxup
gallery_name = sys.argv[1] if len(sys.argv) > 1 else "Unknown"
image_count = sys.argv[2] if len(sys.argv) > 2 else "0"

# Output JSON for imxup to capture
output = {
    "status": "success",
    "notification": f"Uploaded {image_count} images from {gallery_name}",
    "timestamp": "2025-01-03T10:30:00"
}

print(json.dumps(output))
```

**Configure in imxup:**
```
Command: python
Arguments: hooks/notify.py "%N" "%C"
Capture Output: Yes
Execute On: completed
```

### Multi-Host Uploader

**Use:** `hooks/muh.py` (built-in)

This script is included with imxup and supports 44 file hosts:

```bash
python hooks/muh.py gofile /path/to/file.zip
python hooks/muh.py pixeldrain /path/to/file.zip
python hooks/muh.py litterbx /path/to/file.zip 72h
```

**Configure in imxup:**
```
Command: python
Arguments: hooks/muh.py gofile "%z"
Capture Output: Yes
Execute On: completed
Output Mapping:
  ext1 ← $.download_link
  ext2 ← $.file_id
  ext3 ← $.file_size
  ext4 ← $.upload_time
```

For more details, see [Multi-Host Uploader README](../../../hooks/MULTI_HOST_UPLOADER_README.md).

---

## Output Mapping with JSONPath

When your hook outputs JSON, use JSONPath syntax to extract fields:

### Simple Path
```json
{ "url": "https://example.com/file" }
```
Map: `ext1` ← `$.url`

### Nested Path
```json
{
  "data": {
    "download": {
      "link": "https://example.com/file"
    }
  }
}
```
Map: `ext1` ← `$.data.download.link`

### Array First Element
```json
{ "urls": ["https://example.com/file1", "https://example.com/file2"] }
```
Map: `ext1` ← `$.urls[0]`

---

## Multi-Host Integration

### Scenario: Upload to Multiple Hosts

After gallery completes on imx.to, upload to GoFile AND Pixeldrain:

**Hook 1: GoFile**
```
Name: Upload to GoFile
Command: python
Arguments: hooks/muh.py gofile "%z"
Execute On: completed
Output Mapping:
  ext1 ← $.download_link
```

**Hook 2: Pixeldrain**
```
Name: Upload to Pixeldrain
Command: python
Arguments: hooks/muh.py pixeldrain "%z"
Execute On: completed
Output Mapping:
  ext2 ← $.download_link
```

**BBCode Template:**
```bbcode
[b]Download Links:[/b]
[url=#ext1#]GoFile[/url] | [url=#ext2#]Pixeldrain[/url]
```

**Result in template:**
```
Download Links:
[url=https://gofile.io/d/abc123]GoFile[/url] | [url=https://pixeldrain.com/xyz789]Pixeldrain[/url]
```

---

## Troubleshooting

### Hook Not Executing

**Problem:** External app doesn't run

**Solutions:**
1. Check **Execute On** is set correctly (should be "completed" for post-upload)
2. Verify **Command** path is correct (use full path if needed)
3. Check **Working Directory** is set (defaults to imxup folder)
4. View Logs (Ctrl+L) to see error messages

### Parameters Not Substituted

**Problem:** Hook receives literal `%N` instead of gallery name

**Solutions:**
1. **Quote parameters:** Use `"%N"` not `%N` in arguments
2. **Multi-char variables first:** Longest match wins (`%e1`, `%e2`, `%c1`)
3. **Empty fields:** Fields may be empty - always quote them
4. **Path spaces:** Always quote paths: `"%p"` not `%p`

### JSON Output Not Captured

**Problem:** Hook output not stored in `ext1` - `ext4` fields

**Solutions:**
1. Enable **Capture Output** checkbox
2. Verify hook outputs valid JSON (test separately)
3. Check **Output Mapping** JSONPath is correct
4. Use **Configure & Test** to verify mapping works
5. Check Logs for JSON parsing errors

### Hook Timeout

**Problem:** External app takes too long, times out

**Solutions:**
1. Increase **Timeout** value (in seconds)
2. For multi-host uploads, set timeout to at least 5 minutes (300 seconds)
3. Monitor network speed - slow uploads need longer timeout
4. Check Logs for progress updates

### ZIP Creation Too Slow

**Problem:** `%z` parameter ZIP creation is slow

**Solutions:**
See [Archive Management Guide](archive-management.md) for compression options.

By default, imxup uses STORE mode (0.5 seconds for 250 MB) which is recommended.

---

## See Also

- [External Apps Parameters Reference](../reference/external-apps-parameters.md) - Complete parameter list
- [Archive Management Guide](archive-management.md) - ZIP creation and extraction
- [Multi-Host Upload Guide](./multi-host-upload.md) - Detailed file host setup
- [Multi-Host Uploader README](../../../hooks/MULTI_HOST_UPLOADER_README.md) - muh.py documentation

---

**Version:** 0.6.16
**Last Updated:** 2026-01-03
