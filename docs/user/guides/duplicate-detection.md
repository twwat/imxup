# Duplicate Detection Guide

## Quick Reference

**Version:** 0.6.16
**Last Updated:** 2026-01-03
**Feature:** Prevent uploading the same gallery twice
**Detection Methods:** Path matching, name matching, queue checking
**Use Case:** Organize and manage gallery uploads without accidental duplicates

---

## What is Duplicate Detection?

Duplicate detection helps you avoid uploading the same gallery multiple times. imxup automatically detects two types of duplicates:

1. **Previously Uploaded** - Galleries you've already uploaded to imx.to
2. **Already in Queue** - Galleries currently waiting to upload in the queue

When detected, imxup shows friendly dialogs allowing you to decide what to do.

---

## How Detection Works

### Previously Uploaded Galleries

imxup checks if a gallery folder has been uploaded before by looking for special marker files:

- **`.imxgalleryid`** - Stores the gallery ID from imx.to
- **`.imxmetadata`** - Stores upload metadata and timestamp
- Other imx-specific files in the gallery folder

**Detection Accuracy:**
- Matches on folder path (primary method)
- Matches on folder name (secondary)
- Works even if images have been modified since upload
- Reliable indicator that upload was successful

### Already in Queue

imxup checks if the folder path is already in your current upload queue:

- Exact path matching
- Works across all tabs
- Prevents duplicate processing

### Limitations

The current version uses path and name matching. True content hash comparison (MD5 checksum) is not yet implemented, so:

- **Renamed folders** may not be detected as duplicates
- **Copied galleries** with different paths won't be flagged
- **Modified images** in same folder won't prevent re-upload

---

## Detection Settings

Duplicate detection is **enabled by default** and cannot be disabled. This is intentional to prevent accidental re-uploads.

**What you can control:**

1. **User prompts** - You're always asked before action is taken
2. **Selection** - Choose which duplicates to upload
3. **Batch operations** - Select all or none with buttons

---

## User Options When Duplicates Detected

When imxup finds duplicates, you'll see a dialog with options:

### Previously Uploaded Dialog

```
⚠️ 2 galleries were uploaded previously

These folders have existing gallery files, indicating they
were uploaded before. Select which ones you want to upload again:

[x] Summer Vacation
    /home/user/photos/vacation
    Found: .imxgalleryid, .imxmetadata

[x] Birthday Party
    /home/user/photos/birthday
    Found: .imxgalleryid

[Select All] [Select None]              [No, Skip All] [Yes, Upload Selected]
```

**Your Options:**

1. **Yes, Upload Selected** - Re-upload checked galleries to imx.to
   - Use when: Gallery was updated with new images
   - Use when: Previous upload failed (has .imxgalleryid but no images on imx.to)
   - Creates new gallery ID on imx.to

2. **No, Skip All** - Skip all previously uploaded galleries
   - Use when: You don't want to re-upload anything
   - Closes dialog and moves on to next items

### Queue Duplicates Dialog

```
📋 1 item already in queue

These folders are already in your upload queue.
Select which ones you want to replace:

[ ] Summer Vacation (Queue)
    /home/user/photos/vacation
    Current status: uploading

[Select All] [Select None]              [No, Keep Existing] [Yes, Replace Selected]
```

**Your Options:**

1. **Yes, Replace Selected** - Remove from queue and re-add as new entry
   - Clears existing progress
   - Resets retry count
   - Starts upload from scratch

2. **No, Keep Existing** - Keep the original queue entry
   - Current upload continues unchanged
   - Skips the re-added gallery

---

## Re-uploading Galleries

### When to Re-upload

You might want to re-upload a previously uploaded gallery:

1. **Add new images** - Gallery folder has additional images
2. **Fix failed upload** - Previous upload didn't complete properly
3. **Update BBCode** - Gallery already exists but with different metadata
4. **Different host** - Upload same gallery to a different file host

### How to Force Re-upload

When the previously uploaded dialog appears:

1. Check the galleries you want to re-upload
2. Click "Yes, Upload Selected"
3. imxup creates a new gallery ID on imx.to
4. Both old and new galleries exist separately

**Important:** This creates a NEW gallery on imx.to. The old gallery is not modified or replaced.

### Updating an Existing Gallery

If you want to modify an existing gallery on imx.to (not create a new one):

1. Edit the images in your folder
2. Delete the `.imxgalleryid` file from the folder
3. Add the folder to imxup again
4. Gallery will be treated as new

---

## Troubleshooting

### False Positives - "Previously Uploaded" Wrongly Detected

**Problem:** A folder shows as "previously uploaded" but it's a fresh gallery

**Causes:**
- Another folder with same name was uploaded before
- Folder was copied from a previously uploaded gallery
- `.imxgalleryid` file somehow got into the folder

**Solutions:**

1. **Check for marker files**
   ```bash
   # Windows
   dir /a "C:\path\to\gallery" | findstr ".imx"

   # Linux
   ls -la /path/to/gallery | grep "^\.imx"
   ```

2. **Remove old metadata**
   - Delete `.imxgalleryid` and `.imxmetadata` files
   - Right-click folder → Properties (Windows) or show hidden files (Linux)
   - Confirm deletion

3. **Re-add the gallery**
   - Drag folder back into imxup
   - Should now be treated as new upload

### False Negatives - Duplicate Not Detected

**Problem:** Same gallery added twice but no duplicate warning

**Causes:**
- Folder was copied to new location with different path
- Gallery folder was renamed since previous upload
- No marker files from previous upload

**Current Limitations:**
- Path-based detection only (not content hash)
- Won't catch renamed or moved copies

**Workaround:**
- Manually check queue before adding
- Use consistent folder names for same galleries
- Check "Already in Queue" dialog carefully

### Clearing Duplicate Markers

**Problem:** Want to force a gallery to be treated as new

**Steps:**

1. Locate the gallery folder
2. Show hidden files (if not already visible):
   - **Windows:** View → Hidden items
   - **Linux:** Press Ctrl+H in file manager

3. Find and delete these files:
   - `.imxgalleryid`
   - `.imxmetadata`
   - Any other `.imx*` files

4. Close folder window and re-add to imxup

5. Gallery will now be treated as new upload

---

## Best Practices

### Organization Tips

1. **Keep folder names consistent**
   - Use same name for same gallery across sessions
   - Helps with duplicate detection accuracy

2. **Don't rename uploaded folders**
   - If you rename, imxup won't recognize as duplicate
   - Rename after confirming upload completed

3. **Use tabs for organization**
   - "Completed" tab for finished uploads
   - "Queue" tab for pending uploads
   - Reduces chance of accidental re-adds

### Duplicate Detection Workflow

**Recommended process:**

1. Add gallery folders to queue
2. imxup shows duplicate dialogs if needed
3. Review detected duplicates
4. Click "Yes, Upload Selected" or "No, Skip All"
5. Confirm uploads in queue
6. Start uploads when ready

**For batch operations:**

1. Prepare all folders
2. Add them all at once (drag multiple folders)
3. Handle all duplicate dialogs together
4. Start single batch upload

---

## See Also

- **[Gallery Management](../guides/archive-management.md)** - How to organize galleries
- **[GUI Guide](../guides/gui-guide.md)** - Complete interface walkthrough
- **[Multi-Host Upload](../guides/multi-host-upload.md)** - Upload to multiple hosts
- **[Features Reference](../reference/FEATURES.md)** - Full feature list

---

**Version:** 0.6.16
**Last Updated:** 2026-01-03
