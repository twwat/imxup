# IMX.to Gallery Uploader - GUI Mode

A PyQt6-based graphical interface for the IMX.to gallery uploader that provides drag-and-drop functionality, queue management, and progress tracking.

## Features

### 🎯 Core Functionality
- **Drag & Drop**: Drag folders containing images directly into the GUI to add them to the upload queue
- **Queue Management**: View and manage multiple galleries in an upload queue
- **Progress Tracking**: Real-time progress bars for individual galleries and overall progress
- **Single Instance**: Command-line invocations add galleries to existing GUI instance instead of creating new ones
- **System Tray**: Minimize to system tray for background operation

### 📊 Upload Management
- **Individual Control**: Start/pause individual gallery uploads
- **Batch Operations**: Start all queued galleries at once
- **Retry Logic**: Automatic retry of failed uploads with configurable retry count
- **Status Tracking**: Visual status indicators (Queued, Uploading, Completed, Failed)

### ⚙️ Settings & Configuration
- **Thumbnail Settings**: Configure size and format options
- **Visibility Control**: Set galleries as public or private
- **Retry Configuration**: Adjust maximum retry attempts
- **Persistent Settings**: GUI preferences saved between sessions

## Installation

### Prerequisites
```bash
# Install PyQt6 for GUI support
pip install PyQt6

# Or install from requirements file
pip install -r requirements_gui.txt
```

### Core Dependencies
The GUI uses the same core dependencies as the command-line version:
- requests
- aiohttp
- python-dotenv
- tqdm
- configparser
- cryptography
- Pillow (for image processing)

## Usage

### 🚀 Launching the GUI

#### Method 1: Via Main Script
```bash
python imxup.py --gui
```

#### Method 2: Direct Launch
```bash
python imxup_gui.py
```

#### Method 3: Alternative Launcher
```bash
python imxup.py --gui
```

### 📁 Adding Galleries

#### Drag and Drop
1. Launch the GUI
2. Drag folders containing images into the "Upload Queue" area
3. Galleries are automatically added to the queue

#### Command Line Integration
```bash
# Add a gallery to existing GUI instance
python imxup.py --gui "/path/to/gallery/folder"

# If no GUI is running, this will start GUI and add the folder
python imxup.py --gui "/path/to/my/photos"
```

#### Windows Context Menu
```bash
# Install context menu integration
python imxup.py --install-context-menu

# This creates two right-click options:
# - "Upload to imx.to" (command line mode)  
# - "Upload to imx.to (GUI)" (opens GUI with folder)
```

### 🎛️ GUI Interface

#### Main Sections

**Left Panel - Queue & Controls:**
- **Upload Queue**: List of galleries waiting to be uploaded
- **Control Buttons**:
  - `Start All`: Begin uploading all queued galleries
  - `Pause All`: Pause all active uploads
  - `Clear Completed`: Remove finished uploads from queue
- **Settings**: Configure upload parameters

**Right Panel - Progress & Logs:**
- **Overall Progress**: Shows progress across all galleries
- **Individual Progress**: Detailed progress for each gallery
- **Log Output**: Real-time upload logs with timestamps [[memory:4486747]]

#### Settings Configuration
- **Thumbnail Size**: 100x100, 180x180, 250x250, 300x300, 150x150
- **Thumbnail Format**: Fixed width, Proportional, Square, Fixed height  
- **Max Retries**: Number of retry attempts for failed uploads (1-10)
- **Public Gallery**: Toggle between public/private gallery visibility

### 🔄 Single Instance Behavior

The GUI implements single-instance behavior:

1. **First Launch**: Creates new GUI window
2. **Subsequent Launches**: 
   - Detects existing instance
   - Sends folder path to running GUI
   - Brings existing window to foreground
   - Adds gallery to existing queue

This ensures command-line calls integrate seamlessly with the GUI without creating multiple instances.

### 📈 Progress Tracking

#### Individual Gallery Progress
- Gallery name and current status
- Progress bar showing upload completion percentage
- Current image being uploaded
- Upload speed and time estimates

#### Overall Progress  
- Combined progress across all galleries
- Total images uploaded vs. remaining
- Average upload speed

#### Status Indicators
- **Queued**: 🟡 Waiting to start
- **Uploading**: 🔵 Currently uploading
- **Completed**: 🟢 Successfully finished  
- **Failed**: 🔴 Upload failed (with error message)

### 🗂️ Queue Management

#### Adding Galleries
- Drag folders into the queue area
- Use command line with `--gui` flag
- Folders are validated for image content before adding

#### Removing Galleries
- Select queued items and delete (only queued items can be removed)
- Use "Clear Completed" to remove finished uploads

#### Batch Operations
- "Start All" begins uploading all queued galleries sequentially
- "Pause All" pauses active uploads (can be resumed)

## Configuration

### Settings Storage
GUI settings are stored using QSettings:
- **Windows**: Registry under `HKEY_CURRENT_USER\Software\ImxUploader\ImxUploadGUI`
- **Linux/Mac**: `~/.config/ImxUploader/ImxUploadGUI.conf`

### Core Configuration
The GUI uses the same configuration as the command-line version:
- **Credentials**: `~/.imxup.ini` (encrypted passwords) [[memory:4205404]]
- **User Defaults**: Thumbnail settings, retry counts, etc.
- **Unnamed Galleries**: Tracking for galleries pending rename

## Integration with Command Line

### Seamless Workflow
1. **Setup**: Use command line for initial setup
   ```bash
   python imxup.py --setup-secure
   python imxup.py --install-context-menu
   ```

2. **GUI Usage**: Launch GUI for interactive uploads
   ```bash
   python imxup.py --gui
   ```

3. **Command Line**: Still available for scripting/automation
   ```bash
   python imxup.py "/path/to/folder" --name "My Gallery"
   ```

### Context Menu Integration
After installing context menu:
- **Right-click any folder**
- **Select "Upload to imx.to (GUI)"**
- **GUI opens with folder pre-loaded in queue**

## Troubleshooting

### Common Issues

#### PyQt6 Not Found
```bash
# Error: Import "PyQt6.QtWidgets" could not be resolved
pip install PyQt6
```

#### GUI Won't Start
```bash
# Check PyQt6 installation
python -c "import PyQt6.QtWidgets; print('PyQt6 OK')"

# Check for display issues (Linux)
export DISPLAY=:0
```

#### Single Instance Not Working
- Check if port 27849 is available
- Firewall may be blocking localhost communication
- Try restarting the GUI

#### Upload Issues
- Same troubleshooting as command-line version
- Check credentials setup: `python imxup.py --setup-secure`
- Verify API key in `.env` file
- Check log output in GUI for detailed errors

### Performance Tips

#### Large Queues
- GUI handles multiple galleries efficiently
- Consider uploading in smaller batches for very large collections
- Use "Clear Completed" regularly to keep queue manageable

#### Memory Usage
- GUI automatically limits log history to prevent memory issues
- Progress tracking is lightweight
- Consider restarting for very long sessions

## Core Functionality Preservation

The GUI maintains **100% compatibility** with the original command-line functionality:

✅ **All core features preserved**:
- IMX.to API integration
- Authentication and secure password storage [[memory:4205404]]
- Gallery creation and naming
- Image upload with progress tracking
- Retry logic and error handling
- BBCode generation and file output
- Thumbnail configuration
- Public/private gallery settings

✅ **Command-line interface unchanged**:
- All existing arguments work as before
- GUI mode is additive (`--gui` flag)
- Backward compatibility maintained

✅ **Configuration compatibility**:
- Uses same `.imxup.ini` configuration file
- Same environment variables (`.env` file)
- Same default settings and user preferences

## Development Notes

### Architecture
- **Threaded Design**: Upload worker runs in separate thread
- **Thread-Safe**: Queue management uses QMutex for thread safety
- **Signal/Slot**: PyQt signals for communication between threads
- **Modular**: GUI code separated from core uploader logic

### Future Enhancements
- Thumbnail previews in queue
- Upload scheduling
- Advanced filtering and sorting
- Gallery preview before upload
- Drag reordering of queue items

---

**Note**: This GUI enhances the original command-line tool without replacing it. Both interfaces share the same robust core functionality and can be used interchangeably based on your workflow preferences.