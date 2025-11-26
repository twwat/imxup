# External Apps Hook Parameters

Complete reference for all available parameters in imxup's External Apps hooks system.

## 📋 Parameter Categories

### Gallery Information
- **%N** - Gallery name
- **%T** - Tab name (e.g., "Main", "Favorites")
- **%p** - Gallery folder path (e.g., "C:\Images\MyGallery")
- **%C** - Image count (number of images in gallery)
- **%s** - Gallery size in bytes
- **%t** - Template name used for BBCode generation

### Artifacts (Completed Events Only)
- **%g** - Gallery ID (from imx.to)
- **%j** - JSON artifact file path
- **%b** - BBCode artifact file path
- **%z** - ZIP archive path (auto-created if needed)

### Database Fields
**Ext Fields (populated by external apps):**
- **%e1** - ext1 field value
- **%e2** - ext2 field value
- **%e3** - ext3 field value
- **%e4** - ext4 field value

**Custom Fields (user-editable):**
- **%c1** - custom1 field value
- **%c2** - custom2 field value
- **%c3** - custom3 field value
- **%c4** - custom4 field value

## 🎯 Hook Event Types

### 1. On Gallery Added
Triggered when a gallery is added to the queue.

**Available parameters:**
```
%N, %T, %p, %C, %s, %t, %e1-%e4, %c1-%c4
```

**Example command:**
```bash
python notify.py "Added: %N (%C images, %s bytes)"
```

### 2. On Gallery Started
Triggered when a gallery upload begins.

**Available parameters:**
```
%N, %T, %p, %C, %s, %t, %e1-%e4, %c1-%c4
```

**Example command:**
```bash
python logger.py --event start --gallery "%N" --path "%p"
```

### 3. On Gallery Completed
Triggered when a gallery upload finishes successfully.

**Available parameters:**
```
%N, %T, %p, %C, %s, %t, %g, %j, %b, %z, %e1-%e4, %c1-%c4
```

**Example command:**
```bash
python multi_host_uploader.py gofile "%z" --metadata "%N (%s bytes)"
```

## 💡 Usage Examples

### Upload to File Host with Metadata
```bash
python uploader.py --file "%z" --name "%N" --size "%s" --template "%t"
```

### Conditional Processing Based on Size
```bash
python process.py "%p" --large-mode --size %s --quality high
```

### Chain Ext Fields
```bash
# First hook populates ext1 with download URL
python multi_host_uploader.py gofile "%z"

# Second hook can read ext1 and add more data
python metadata_sync.py --url "%e1" --gallery "%N" --id "%g"
```

### Custom Workflow with All Fields
```bash
python workflow.py \
  --name "%N" \
  --path "%p" \
  --count %C \
  --size %s \
  --template "%t" \
  --gallery-id "%g" \
  --json "%j" \
  --bbcode "%b" \
  --ext1 "%e1" \
  --custom1 "%c1"
```

## 🔧 Technical Details

### Multi-Character Variables
Multi-character parameters (%e1, %c1, etc.) are processed using **longest-match-first** substitution:

```python
# Variables are sorted by length (descending) before substitution
# This prevents %e1 from being partially matched as %e + "1"

Order: %e1, %e2, %c1, %c2 ... %N, %T, %p, %C, %s, %t, %g
```

### Empty Values
- Empty fields are substituted with empty strings
- Use quotes around parameters to handle empty values:
  ```bash
  python script.py "%e1"  # Safe even if e1 is empty
  python script.py %e1    # May cause parsing errors if empty
  ```

### Path Quoting
Always quote paths to handle spaces:
```bash
python uploader.py "%p"              # ✓ Correct
python uploader.py %p                # ✗ Wrong (breaks with spaces)
```

## 📊 Field Value Flow

### Ext Fields (%e1-%e4)
1. External program outputs JSON:
   ```json
   {
     "url": "https://example.com/file",
     "file_id": "abc123",
     "status": "success"
   }
   ```

2. Map in "Configure & Test" dialog:
   - ext1 ← "url"
   - ext2 ← "file_id"
   - ext3 ← "status"

3. Values appear in database and templates:
   ```
   Download: #ext1#
   File ID: #ext2#
   Status: #ext3#
   ```

4. Available in subsequent hooks as %e1, %e2, %e3

### Custom Fields (%c1-%c4)
- User-editable in table (right-click header to show columns)
- Persist across sessions
- Can be set manually or by external programs
- Available in templates as #custom1#-#custom4#

## 🎨 Real-World Workflows

### Multi-Host Upload with Tracking
```bash
# Completed hook command:
python multi_host_uploader.py gofile "%z" && \
python backup.py --source "%p" --metadata "%N|%s|%t"
```

**Result:**
- Uploads ZIP to GoFile
- Returns download URL in ext1
- Backs up original with metadata
- All info available in template

### Gallery Size-Based Routing
```bash
# Use size parameter to choose upload destination:
python smart_uploader.py "%z" --size %s --auto-select-host
```

**Logic:**
- < 100MB → Transfer.sh (fast, temporary)
- 100MB-1GB → GoFile (free, permanent)
- > 1GB → pCloud (requires account)

### Template-Specific Processing
```bash
# Different processing based on template:
python processor.py "%p" --template "%t" --optimize
```

**Behavior:**
- "High Quality" template → No compression
- "Web Optimized" template → JPEG compression
- "Archive" template → ZIP with metadata

## ⚙️ Automatic ZIP Creation

When using **%z** parameter, imxup automatically:

1. **Detects** if command contains %z
2. **Creates** temporary ZIP in system temp folder
3. **Uses** store mode (no compression) for speed
4. **Executes** external program with ZIP path
5. **Deletes** temporary ZIP after completion

**Performance:**
- Store mode is 10-50x faster than compression
- No disk space wasted after execution
- Works transparently with any host

## 📚 Additional Resources

- **Multi-Host Uploader:** See `multi_host_uploader.py` for 44-host support
- **Keep2Share Uploader:** See `up3_windows.py` for K2S integration
- **Hook System:** See `src/processing/hooks_executor.py` for implementation

## 🔍 Debugging

### Test Your Command
1. Open Settings → External Apps
2. Click "Configure & Test..." for any hook
3. See live preview with all substitutions
4. Click "Run Test Command" to verify output
5. View both parsed JSON and raw output

### Common Issues

**Problem:** Parameters not substituted
```bash
# Wrong - no quotes
python script.py %N
# Right - with quotes
python script.py "%N"
```

**Problem:** Multi-char variable conflict
```bash
# If you define both %e and %e1, longest match wins
# %e1 is processed first, then %e
# This is handled automatically
```

**Problem:** Empty ext/custom fields
```bash
# Fields may be empty - always quote them
python script.py "%e1" "%c1"  # Safe
```

---

**Version:** imxup 0.5.08+
**Updated:** 2024-01-16