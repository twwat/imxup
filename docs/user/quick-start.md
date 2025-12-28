# Quick Start Guide - IMX.to GUI Uploader

## Installation & Setup

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Setup Credentials (Required)
```bash
python imxup.py --setup-secure
```

## Fixed Issues

### **Drag & Drop Now Works**
- Enhanced drag detection with visual feedback
- Proper file type validation
- Clear visual indicators during drag operations

### **Browse Button Added**
- "Browse for Folders..." button in the GUI
- Standard file dialog for folder selection
- Easy alternative to drag and drop

### **GUI Crashes Fixed**
- Fixed Qt color compatibility issues (lightBlue to cyan)
- Resolved threading problems with user input
- Created non-blocking GUI uploader class

### **Single Instance Working**
- Command line integration now works properly
- Context menu adds galleries to running GUI
- No more duplicate instances

## How to Use

### Launch GUI
```bash
python imxup.py --gui
```

### Add Galleries

#### **Option 1: Drag & Drop**
1. Open the GUI
2. Drag folders containing images into the queue area
3. Drop to add them to the upload queue

#### **Option 2: Browse Button**
1. Click "Browse for Folders..." in the GUI
2. Select a folder containing images
3. Click OK to add to queue

#### **Option 3: Command Line**
```bash
# Add folder to existing GUI instance
python imxup.py --gui "/path/to/gallery"

# Or use context menu (after installation)
python imxup.py --install-context-menu
# Then right-click any folder -> "Upload to imx.to (GUI)"
```

### Upload Process
1. **Queue**: Added galleries appear in the upload queue
2. **Start**: Click "Start All" or wait for automatic processing
3. **Progress**: Watch real-time progress bars for each gallery
4. **Complete**: Finished uploads show green status with gallery URLs

## Key Features

### **Visual Progress Tracking**
- Individual progress bars for each gallery
- Overall progress across all uploads
- Real-time current image and speed display
- Upload statistics and timing

### **Queue Management**
- Add multiple galleries before starting
- Remove queued items (before upload)
- Clear completed uploads
- Status indicators (Queued, Uploading, Completed, Failed)

### **Settings Control**
- Thumbnail size and format options
- Public/private gallery toggle
- Retry count configuration
- Persistent settings between sessions

### **Non-Blocking Operation**
- Uploads run in background thread
- GUI remains responsive during uploads
- System tray support for minimizing
- Single instance prevents duplicates

## Troubleshooting

### **Drag & Drop Not Working**
- Ensure you're dragging **folders**, not individual files
- Try the "Browse for Folders..." button as alternative
- Check that folders contain image files (.jpg, .png, .gif)

### **GUI Crashes**
- Verify PyQt6 is installed: `pip install PyQt6`
- Check credentials are set up: `python imxup.py --setup-secure`

### **Context Menu Issues**
- Run as administrator: `python imxup.py --install-context-menu`
- Test command line first: `python imxup.py "/path/to/folder"`

### **Upload Failures**
- Same troubleshooting as command-line version
- Check log output in GUI for detailed errors
- Verify internet connection and IMX.to service status

## Integration with Command Line

The GUI **preserves all original functionality**:

- Same authentication system
- Same configuration files
- Same gallery creation process
- Same BBCode output and file structure
- Full backward compatibility

**You can use both interfaces interchangeably:**
- Command line for automation/scripting
- GUI for interactive uploads and queue management

---

**You're ready to go!** Start with `python imxup.py --gui` and drag some folders into the queue area.
