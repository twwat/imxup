# ImxUp Help & Documentation

Welcome to ImxUp - your comprehensive image gallery uploader!

---

## 🚀 Getting Started

### First Time Setup

1. **Install ImxUp**
   - Windows: Run `imxup.exe`
   - Linux/Mac: `python imxup.py --gui`

2. **Configure Credentials** (Required)
   - Click **Settings** → **Comprehensive Settings**
   - Go to **Credentials** tab
   - Enter your IMX.to username and password
   - Click **Save**

3. **Add Your First Gallery**
   - Drag a folder of images into the main window
   - Or click **Browse for Folders...**
   - Gallery appears in the queue

4. **Upload**
   - Click **Start All** or individual **Start** buttons
   - Watch progress in real-time
   - BBCode generated automatically when complete

---

## 📤 Multi-Host Upload (NEW)

Upload your galleries to multiple file hosting services simultaneously!

### Supported Hosts
- **Fileboom** - Fast upload speeds
- **Filedot** - Reliable hosting
- **Filespace** - Large storage
- **Keep2Share** - Premium downloads
- **Rapidgator** - Popular host
- **Tezfiles** - High availability

### Setup

1. **Configure Host Credentials**
   - Settings → **Comprehensive Settings** → **File Hosts** tab
   - Enable hosts you want to use
   - Enter API keys or login credentials for each

2. **Select Hosts for Upload**
   - In the main queue, select galleries
   - Right-click → **Upload to File Hosts**
   - Choose which hosts to upload to
   - Click **Start Upload**

3. **Monitor Progress**
   - Each host shows individual progress
   - View upload speed and estimated time
   - Failed uploads retry automatically

### Tips
- Upload to multiple hosts for redundancy
- Some hosts require premium accounts
- Check host status indicators before uploading

---

## 📦 Archive Management

Create ZIP archives of your galleries before or after upload.

### Creating Archives

1. **Before Upload**
   - Select galleries in queue
   - Right-click → **Create Archive**
   - Choose compression level
   - Archive created in output folder

2. **After Upload**
   - Select completed galleries
   - Right-click → **Archive Gallery**
   - Original files preserved

### Archive Settings

- **Compression Level:** None, Fast, Normal, Maximum
- **Archive Location:** Configure in Settings → **Archive**
- **Naming Pattern:** Customize archive filenames

---

## 🎨 BBCode Templates

Customize the BBCode output for your galleries.

### Using Templates

1. **Select Template**
   - Settings → BBCode Template dropdown
   - Choose from built-in or custom templates

2. **Available Placeholders**
   - `#folderName#` - Gallery name
   - `#pictureCount#` - Number of images
   - `#width#` x `#height#` - Average dimensions
   - `#folderSize#` - Total size
   - `#galleryLink#` - Gallery URL
   - `#allImages#` - All image BBCode

### Creating Custom Templates

1. **Open Template Manager**
   - Settings → **Manage BBCode Templates**

2. **Create New**
   - Click **New Template**
   - Enter template name
   - Use placeholder buttons to insert fields
   - Save template

3. **Edit Existing**
   - Select template
   - Click **Edit**
   - Modify and save

### Example Template

```
Gallery: #folderName#
Images: #pictureCount# (#extension# format)
Size: #folderSize#
Link: #galleryLink#

#allImages#
```

---

## ⌨️ Keyboard Shortcuts

### Tab Management
- `Ctrl+T` - Create new tab
- `Ctrl+W` - Close current tab
- `Ctrl+Tab` - Next tab
- `Ctrl+Shift+Tab` - Previous tab

### Gallery Management
- `Delete` - Remove selected galleries
- `Ctrl+C` - Copy BBCode
- `F2` - Rename gallery

### Application
- `Ctrl+,` - Open Settings
- `Ctrl+.` - Show keyboard shortcuts
- `F1` - Show this help

### Selection
- `Ctrl+Click` - Select multiple galleries
- `Shift+Click` - Select range
- `Ctrl+A` - Select all (in current tab)

---

## 🔍 Duplicate Detection

Find and manage duplicate galleries across your collection.

### Finding Duplicates

1. **Open Duplicate Detector**
   - Tools → **Find Duplicates**
   - Or click **Duplicates** button

2. **Scan Options**
   - **By Name:** Match gallery names
   - **By Files:** Compare actual image files
   - **By Hash:** Deep content comparison

3. **Review Results**
   - Duplicates shown in pairs/groups
   - Preview images side-by-side
   - Choose which to keep

### Handling Duplicates

- **Keep Original:** Delete duplicate
- **Keep Newest:** Delete older version
- **Keep Both:** Mark as reviewed
- **Merge:** Combine metadata

---

## 🎨 Icon Customization

Customize file host and status icons.

### Changing Icons

1. **Open Icon Manager**
   - Settings → **Comprehensive Settings** → **Appearance**
   - Click **Manage Icons**

2. **Select Icon Type**
   - File host icons
   - Status icons
   - Application icons

3. **Choose New Icon**
   - Browse for image file (PNG, JPG, SVG)
   - Preview before applying
   - Click **Apply**

### Icon Requirements
- **Format:** PNG recommended (transparency support)
- **Size:** 16x16 to 128x128 pixels
- **File Size:** <500KB for best performance

---

## 🔧 Advanced Settings

### Thumbnail Settings
- **Size:** 100-300 pixels
- **Format:** Fixed width, Proportional, Square
- **Quality:** 1-100 (default: 85)

### Upload Settings
- **Max Retries:** 1-10 (default: 3)
- **Timeout:** 30-600 seconds
- **Concurrent Uploads:** 1-5 galleries

### Queue Settings
- **Auto-start:** Start uploads automatically
- **Notifications:** Desktop notifications
- **Minimize to Tray:** Keep running in background

### Database Settings
- **Auto-backup:** Backup frequency
- **Cleanup:** Remove old records
- **Optimize:** Database maintenance

---

## 🐛 Troubleshooting

### Upload Failures

**Symptom:** Uploads fail repeatedly
**Solutions:**
1. Check internet connection
2. Verify credentials in Settings
3. Check IMX.to service status
4. Increase timeout in Settings
5. Check firewall/antivirus settings

### Missing BBCode

**Symptom:** BBCode file not generated
**Solutions:**
1. Check template selection
2. Verify output folder permissions
3. Re-generate BBCode (right-click gallery)

### Slow Performance

**Symptom:** GUI freezes or slow uploads
**Solutions:**
1. Close unused tabs
2. Clear completed galleries
3. Reduce concurrent uploads
4. Check disk space
5. Optimize database (Settings → Database)

### Drag & Drop Not Working

**Symptom:** Can't drag folders into GUI
**Solutions:**
1. Use **Browse for Folders** button instead
2. Ensure dragging folders, not files
3. Check folder contains images
4. Try restarting application

### Multi-Host Upload Issues

**Symptom:** File host uploads fail
**Solutions:**
1. Verify host credentials
2. Check host service status
3. Some hosts require premium accounts
4. Try uploading to one host first
5. Check API key validity

---

## 📊 Queue Management

### Adding Galleries

**Multiple Ways:**
1. **Drag & Drop:** Drag folders onto window
2. **Browse:** Click **Browse for Folders**
3. **Command Line:** `imxup.py --gui /path/to/folder`
4. **Context Menu:** Right-click folder → Upload to ImxUp

### Organizing Galleries

**Tabs:**
- Create tabs: `Ctrl+T`
- Move galleries: Right-click → **Move to...**
- Rename tabs: Double-click tab name

**Queue Operations:**
- Start all: **Start All** button
- Pause all: **Pause All** button
- Clear completed: **Clear Completed** button
- Remove queued: Select + `Delete` key

### Gallery States

| State | Icon | Description |
|-------|------|-------------|
| **Queued** | 🟡 | Waiting to upload |
| **Uploading** | 🔵 | Currently uploading |
| **Completed** | 🟢 | Upload successful |
| **Failed** | 🔴 | Upload failed |
| **Paused** | ⏸️ | Upload paused |

---

## 💡 Tips & Tricks

### Performance Tips
- Upload during off-peak hours for faster speeds
- Close other tabs while uploading large galleries
- Use "Clear Completed" regularly
- Enable database auto-optimize

### Workflow Tips
- Create templates for different use cases
- Use tabs to organize by category/date
- Set up multi-host upload for important galleries
- Regular database backups (Settings → Database)

### Advanced Features
- Use hooks for custom automation
- Batch rename galleries with F2
- Export/import settings between machines
- Use command-line for automation scripts

---

## 🆘 Getting More Help

**Still need help?**

1. **FAQ:** Check the FAQ tab for common questions
2. **Documentation:** Full docs at `/docs` folder
3. **GitHub Issues:** Report bugs on GitHub
4. **Community:** Join discussions forum

**In the GUI:**
- Press `F1` to open this help anytime
- Press `Ctrl+.` for keyboard shortcut reference
- Check status bar for tips and messages

---

**ImxUp Version:** 0.6.00
**Help Version:** 1.0
**Last Updated:** 2025-11-15
