# Archive Management Guide

## Quick Reference

**Version:** v0.6.16
**Feature:** Extract archives and create ZIPs for external apps
**Supported Formats:** ZIP, RAR, 7Z, TAR, TAR.GZ, TAR.BZ2
**Compression:** STORE (fastest) | DEFLATE | BZIP2 | LZMA (maximum)
**Use Case:** Handle compressed galleries and multi-host uploads

---

## What is Archive Support?

Archive support in imxup provides two key features:

1. **Archive Extraction** - Extract compressed gallery folders and select which ones to upload
2. **ZIP Creation** - Automatically create compressed archives for external applications and multi-host uploads

This guide covers how to use both features effectively.

---

## Supported Archive Formats

### Extraction Formats

imxup can extract and process the following compressed archive formats:

| Format | Extension | Best For | Notes |
|--------|-----------|----------|-------|
| **ZIP** | `.zip` | Universal | Most common, wide compatibility |
| **RAR** | `.rar` | Large files | Excellent compression, requires WinRAR |
| **7-Zip** | `.7z` | High compression | Best compression ratio, slower |
| **TAR** | `.tar` | Unix/Linux | Uncompressed archive |
| **TAR.GZ** | `.tar.gz` | Unix/Linux | Compressed with gzip |
| **TAR.BZ2** | `.tar.bz2` | Unix/Linux | Compressed with bzip2 |

### Compression Formats (ZIP Creation)

When imxup creates archives automatically, it supports these compression modes:

| Mode | Type | Speed | Size | Recommended Use |
|------|------|-------|------|-----------------|
| **STORE** | No compression | 0.5-2x faster | Original size + 1-2% | Images (already compressed) |
| **DEFLATE** | Standard | Normal | 5-15% smaller | Mixed content |
| **BZIP2** | High compression | Slower | 10-20% smaller | Archive storage |
| **LZMA** | Maximum compression | Slowest | 15-25% smaller | Final archival |

**Recommendation:** Use STORE mode for image galleries since images (JPG, PNG) are already compressed and ZIP compression provides minimal benefit while wasting CPU time.

---

## How Archive Extraction Works

### Step 1: Adding an Archive to the Queue

You can add an archive file to imxup in three ways:

#### Drag & Drop
1. Locate your archive file in File Explorer
2. Drag it directly into the imxup window
3. imxup will auto-detect the archive type

#### Using the GUI
1. In imxup, click **File -> Add Archive**
2. Select your archive file
3. Click **Open**

#### Command Line
```bash
python imxup.py vacation.zip --gui
```

### Step 2: Archive Detection & Extraction

When you add an archive, imxup will:

1. **Validate** the archive integrity and format
2. **Extract** to a temporary system directory (`/tmp` on Linux, `%TEMP%` on Windows)
3. **Scan** for image-containing folders
4. **Display** a folder selection dialog

### Step 3: Folder Selection Dialog

The Archive Folder Selector appears after extraction:

```
+--- Select Folders to Upload ---+
| Archive: vacation_photos.zip    |
| Extracted to: /tmp/imxup_xyz    |
|                                 |
| Found 3 image folders:          |
| [x] Day1_Beach (127 images)     |
| [x] Day2_City (84 images)       |
| [ ] Day3_Mountain (95 images)   |
|                                 |
| [Select All] [Upload] [Cancel]  |
+---------------------------------+
```

**Actions:**
- **Check/uncheck** folders to include/exclude them
- **Select All** - Include all detected folders
- **Upload** - Add selected folders to the queue as separate galleries
- **Cancel** - Discard extraction and close dialog

### Step 4: Automatic Cleanup

After selection:
- Unchecked folders are permanently deleted
- Checked folders are converted to temporary galleries
- Temporary extraction directory is cleaned up after upload completes
- All temporary files are removed (success or failure)

---

## Archive Extraction Example

### Scenario: Multi-Day Event Photos

You have a single ZIP file containing photos from a 3-day event, organized by day:

```
vacation_photos.zip
├── Day1_Beach/
│   ├── IMG_0001.jpg
│   ├── IMG_0002.jpg
│   └── ... (127 total)
├── Day2_City/
│   ├── IMG_0128.jpg
│   ├── IMG_0129.jpg
│   └── ... (84 total)
└── Day3_Mountain/
    ├── IMG_0212.jpg
    ├── IMG_0213.jpg
    └── ... (95 total)
```

**Steps:**
1. Drag `vacation_photos.zip` into imxup
2. imxup extracts and detects 3 folders
3. Folder selector appears with all 3 checked by default
4. Click **Upload** to add all three as separate galleries
5. Each folder becomes a separate queue entry:
   - Gallery 1: "Day1_Beach" (127 images, 245 MB)
   - Gallery 2: "Day2_City" (84 images, 156 MB)
   - Gallery 3: "Day3_Mountain" (95 images, 189 MB)

---

## Archive Creation for External Hooks

### What is ZIP Creation for Hooks?

When you use external apps (hooks) to upload to additional hosts, imxup can automatically create temporary ZIP archives. This is useful for:

- **Multi-host uploaders** (like muh.py for Gofile)
- **Custom scripts** that process entire galleries
- **Cloud sync** to Dropbox, Google Drive, etc.
- **Backup services** that want compressed archives

### How It Works

#### 1. Configure External App

In **Settings -> External Apps**, set up an app with the `%z` parameter:

```json
{
  "name": "Upload to Gofile",
  "command": "python",
  "arguments": ["hooks/muh.py", "gofile", "%z"],
  "execute_on": "completed",
  "capture_output": true
}
```

The `%z` parameter tells imxup to create a ZIP file.

#### 2. Gallery Upload Completes

After your gallery finishes uploading to imx.to:

1. imxup creates a temporary ZIP file:
   - **Location:** System temp directory
   - **Name:** `imxup_<gallery_id>_<gallery_name>.zip`
   - **Contents:** All images from the gallery
   - **Compression:** STORE mode (fastest)

2. Example: `imxup_abc123_Summer_Vacation.zip` (245 MB)

#### 3. External App Executes

imxup runs the external app and passes the ZIP path:

```bash
python hooks/muh.py gofile /tmp/imxup_abc123_Summer_Vacation.zip
```

#### 4. Automatic Cleanup

After the external app completes (success or failure):
- Temporary ZIP file is **automatically deleted**
- No manual cleanup needed
- Disk space is immediately freed

### ZIP Creation Example

**Scenario:** Upload to both imx.to and Gofile

1. Drag 250 MB gallery into imxup
2. Start upload
3. Gallery uploads to imx.to (takes 2 minutes at 2 MB/s)
4. Gallery completes and gallery_id is obtained
5. External app configured:
   ```
   Name: Upload to Gofile
   Command: python
   Arguments: hooks/muh.py gofile %z
   Execute on: completed
   ```
6. imxup automatically:
   - Creates 250 MB ZIP in temp directory (0.5 seconds)
   - Runs: `python hooks/muh.py gofile /tmp/imxup_abc123_Summer_Vacation.zip`
   - Waits for Gofile upload to complete
   - Deletes temporary ZIP file
7. External app output (like Gofile URL) is captured and stored in `ext1` field

---

## Archive Performance & Storage

### Extraction Performance

| Archive Type | Size | Extraction Time | Notes |
|-------------|------|-----------------|-------|
| ZIP (STORE) | 250 MB | 1-2 sec | Fastest, no decompression |
| ZIP (DEFLATE) | 200 MB | 3-5 sec | Standard compression |
| 7Z | 150 MB | 5-8 sec | High compression, slower |
| RAR | 180 MB | 4-6 sec | Depends on compression |

### ZIP Creation Performance

| Compression | Speed | Output Size | Time (250 MB) |
|------------|-------|------------|---------------|
| **STORE** | Fastest | 250 MB | 0.5 sec |
| **DEFLATE** | Normal | 230 MB | 3-4 sec |
| **BZIP2** | Slower | 210 MB | 6-8 sec |
| **LZMA** | Slowest | 190 MB | 10-15 sec |

imxup uses **STORE mode by default** for ZIP creation because:
- JPG and PNG files are already compressed
- STORE is 50-100x faster than DEFLATE
- Size difference is negligible (<1% for images)

### Storage Locations

**Temporary Extraction:**
```
Windows: C:\Users\[username]\AppData\Local\Temp\imxup_extract_*
Linux:   /tmp/imxup_extract_*
```

**Temporary ZIP Creation:**
```
Windows: C:\Users\[username]\AppData\Local\Temp\imxup_[id]_[name].zip
Linux:   /tmp/imxup_[id]_[name].zip
```

These directories are automatically cleaned up:
- After successful extraction/upload
- After external app completes
- On application restart (orphaned temp files removed)

---

## Best Practices

### When to Use Archives vs. Folders

#### Use Archives When:

1. **Receiving from others** - Someone sends you a ZIP file
2. **Organized by folders** - Multi-day events, different locations
3. **Network transfer** - Downloading galleries over slow connections
4. **Storage efficiency** - Long-term storage of completed galleries
5. **Distribution** - Sharing gallery sets with others

#### Use Folders When:

1. **Local gallery** - Already have a folder of images
2. **Single category** - All images are from same event/location
3. **Quick upload** - No extraction overhead
4. **Adding images** - Can easily add more files to folder

### Performance Optimization Tips

#### For Large Archives

1. **Use DEFLATE or STORE compression**
   - RAR and 7Z decompress slowly
   - ZIP with STORE is fastest for already-compressed images

2. **Split large galleries**
   - Extract all folders, but only upload needed ones
   - Can resume later by re-adding archive

3. **Monitor extraction progress**
   - Check Logs (Ctrl+L) for extraction status
   - Large 7Z archives may take 10+ seconds

#### For External Apps

1. **Use STORE compression for speed**
   - Default STORE mode takes 0.5 sec for 250 MB
   - DEFLATE takes 5-10x longer with minimal size reduction

2. **Set appropriate timeout**
   - External app timeout (Settings -> External Apps)
   - Recommend 5 minutes (300 seconds) for multi-host uploads
   - Gofile uploads typically take 1-3 minutes

3. **Monitor with logs**
   - Check if external app executes successfully
   - View Logs (Ctrl+L) -> Filter: "archive" or "external"

### Archive Organization

#### Recommended Structure

For multi-location photo events:

```
vacation_2025.zip
├── Day1_Beach/
│   ├── Morning/
│   │   └── IMG_*.jpg
│   └── Sunset/
│       └── IMG_*.jpg
├── Day2_City/
│   ├── Downtown/
│   │   └── IMG_*.jpg
│   └── Museum/
│       └── IMG_*.jpg
└── Day3_Mountain/
    ├── Summit/
    │   └── IMG_*.jpg
    └── Base/
        └── IMG_*.jpg
```

Benefits:
- Extract once, see all available folders
- Select which day/location to upload
- Easy to skip unwanted folders
- Maintain organization across uploads

#### Avoid Flat Archives

Don't do this:

```
all_vacation_photos.zip
├── IMG_0001.jpg
├── IMG_0002.jpg
├── IMG_0003.jpg
└── ... (300+ files)
```

Problems:
- All images treated as single folder
- Hard to manage different photo sets
- No clear organization

---

## Troubleshooting

### Archive Won't Extract

**Error:** "Failed to extract archive"

**Solutions:**
1. **Verify archive integrity**
   - Try extracting manually with 7-Zip or WinRAR
   - Confirm file isn't corrupted

2. **Check file permissions**
   - Ensure imxup has read access to archive
   - Check temp directory has write access

3. **Free up disk space**
   - Archive extraction needs space for full uncompressed size
   - Check available disk space > archive size × 1.5

### Folders Not Detected

**Problem:** "Found 0 image folders" but archive contains images

**Solutions:**
1. **Check image format support**
   - Only JPG, PNG, GIF supported
   - Other formats (TIFF, BMP) won't be detected
   - Verify filenames have correct extensions

2. **Check folder structure**
   - Images must be in folders, not at root of archive
   - Create folders: `Photos/` → `IMG_*.jpg`
   - Subfolder depth doesn't matter

3. **Check image count**
   - Folder must contain at least 1 image
   - Hidden files not counted

### ZIP Creation Too Slow

**Problem:** External app ZIP creation takes 30+ seconds

**Solutions:**
1. **Switch to STORE compression**
   - Currently using high compression (DEFLATE/BZIP2/LZMA)
   - STORE mode: 10-50x faster
   - Minimal size difference for images

2. **Check disk I/O**
   - Slow disk (HDD) can bottleneck ZIP creation
   - External SSD recommended for large galleries
   - Check System tab in Task Manager

3. **Monitor memory**
   - Large galleries (500+ MB) use significant RAM
   - Close other apps if system is sluggish

### Temporary Files Not Cleaned Up

**Problem:** `C:\Users\[user]\AppData\Local\Temp\imxup_*` files remain

**Solutions:**
1. **Manual cleanup (one-time)**
   ```bash
   # Windows
   rmdir /s /q %TEMP%\imxup_*

   # Linux
   rm -rf /tmp/imxup_*
   ```

2. **Ensure proper shutdown**
   - Application crashed during extraction/upload
   - Restart imxup and check Logs

3. **Check disk space**
   - If drive is full, cleanup may fail
   - Free up space and restart

---

## External Apps & Multi-Host Uploads

### Using muh.py with ZIP Archives

The `muh.py` script is a multi-host uploader that works great with imxup-created ZIPs:

```bash
# Upload ZIP to Gofile
python hooks/muh.py gofile /tmp/imxup_abc123_Summer_Vacation.zip

# Upload ZIP to Pixeldrain
python hooks/muh.py pixeldrain /tmp/imxup_abc123_Summer_Vacation.zip

# Upload ZIP with authentication (Rapidgator)
python hooks/muh.py rapidgator /tmp/imxup_abc123_Summer_Vacation.zip username:password
```

### Configuring Multiple External Apps

Upload same gallery to multiple hosts:

**App 1: Gofile**
```json
{
  "name": "Upload ZIP to Gofile",
  "command": "python",
  "arguments": ["hooks/muh.py", "gofile", "%z"],
  "execute_on": "completed",
  "output_mapping": {"ext1": "$.download_link"}
}
```

**App 2: Pixeldrain**
```json
{
  "name": "Upload ZIP to Pixeldrain",
  "command": "python",
  "arguments": ["hooks/muh.py", "pixeldrain", "%z"],
  "execute_on": "completed",
  "output_mapping": {"ext2": "$.download_link"}
}
```

Both execute after gallery upload completes, and results are stored in `ext1` and `ext2` fields.

### Parameter Substitution in Archives

Available parameters for external apps:

| Parameter | Description | Example |
|-----------|-------------|---------|
| `%z` | ZIP path (auto-created) | `/tmp/imxup_abc123_vacation.zip` |
| `%N` | Gallery name | `Summer Vacation` |
| `%p` | Gallery path | `/home/user/images/vacation` |
| `%C` | Image count | `127` |
| `%g` | Gallery ID | `abc123xyz` |
| `%j` | JSON artifact path | `~/.imxup/artifacts/abc123.json` |

---

## Summary

Archive support in imxup is designed to be intuitive and automatic:

- **Extract archives** with a single drag-and-drop
- **Select folders** visually with a friendly dialog
- **Create ZIPs automatically** for external applications
- **Clean up automatically** without manual intervention
- **Support multiple formats** (ZIP, RAR, 7Z, TAR variants)

Use archives to handle complex gallery structures, multi-host uploads, and external application workflows efficiently.

---

**Version:** 0.6.16
**Last Updated:** 2026-01-03
