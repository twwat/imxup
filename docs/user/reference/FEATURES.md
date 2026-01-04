# ImXup Features Documentation

**Version:** 0.6.16
**Last Updated:** 2026-01-03
**Platform:** Windows 10+ | Linux (Ubuntu 20.04+)

---

## Table of Contents

1. [Gallery Management](#gallery-management)
2. [Multi-Host Upload System](#multi-host-upload-system)
3. [Archive & Compression](#archive--compression)
4. [BBCode Generation & Templates](#bbcode-generation--templates)
5. [File Host Integration](#file-host-integration)
6. [Template System](#template-system)
7. [Automation & Hooks](#automation--hooks)
8. [Configuration & Settings](#configuration--settings)
9. [User Interface](#user-interface)
10. [Advanced Features](#advanced-features)
11. [Database & Storage](#database--storage)
12. [Network & Performance](#network--performance)

---

## Gallery Management

### Drag & Drop Interface
**Version:** All versions
**Description:** Intuitive drag-and-drop functionality for adding galleries to the upload queue.

**Features:**
- Drag image folders directly into the GUI
- Automatic folder validation (checks for image content)
- Multiple folder selection support
- Visual feedback during drag operations
- Single-instance integration (adds to existing GUI window)

**Supported Image Formats:**
- `.jpg`, `.jpeg` - JPEG images
- `.png` - PNG images
- `.gif` - GIF animations

**Technical Details:**
- Uses PyQt6 drag-and-drop events (`QDragEnterEvent`, `QDropEvent`)
- Validates folder contains supported image formats
- Integrates with single-instance architecture via port 27849
- Thread-safe queue operations with `QMutex`

---

### Queue Management
**Version:** All versions
**Description:** Comprehensive queue system for managing multiple gallery uploads.

**Queue States (11 Total):**
- **Validating** - Initial gallery validation phase
- **Scanning** - Analyzing gallery folder for images
- **Ready** - Gallery prepared, waiting for upload
- **Queued** - In queue, waiting for available upload slot
- **Uploading** - Currently uploading
- **Paused** - Upload manually paused by user
- **Completed** - Successfully finished upload
- **Failed** - Upload failed (single attempt)
- **Upload Failed** - Failed after all retry attempts
- **Scan Failed** - Gallery scanning failed
- **Incomplete** - Partial upload with some images missing

**Batch Operations:**
- **Start All**: Begin uploading all queued galleries
- **Pause All**: Pause active uploads
- **Clear Completed**: Remove finished uploads
- **Remove Selected**: Delete galleries from queue (Delete key)
- **Copy BBCode**: Copy BBCode for selected completed galleries (Ctrl+C)

**Features:**
- Priority scheduling (galleries upload in queue order)
- Individual and overall progress tracking
- Automatic retry logic (configurable 1-10 attempts)
- Status persistence across application restarts
- Real-time status updates via PyQt signals

**Database Schema:**
```sql
CREATE TABLE galleries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  path TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL,
  tab TEXT DEFAULT 'Main',
  template TEXT DEFAULT 'Default Template',
  custom1-4 TEXT,  -- User-defined fields
  ext1-4 TEXT,     -- External app outputs
  created_at INTEGER NOT NULL,
  completed_at INTEGER,
  gallery_id TEXT,
  bbcode_path TEXT,
  artifact_path TEXT,
  retry_count INTEGER DEFAULT 0,
  error_message TEXT
);
```

---

### Tab-Based Organization
**Version:** v0.5.12+
**Description:** Organize galleries across multiple tabs for better workflow management.

**Features:**
- **Create tabs**: Ctrl+T
- **Close tabs**: Ctrl+W (except Main tab)
- **Switch tabs**: Ctrl+Tab (next), Ctrl+Shift+Tab (previous)
- **Rename tabs**: Double-click tab name
- **Move galleries**: Drag-and-drop or context menu "Move to..."
- **Per-tab counts**: Shows gallery count in each tab
- **Tab persistence**: State saved across sessions

**Default Tabs:**
- **Main**: Primary upload queue
- **Archive**: Archive extraction and processing (optional)
- **File Hosts**: Multi-host uploads (optional)
- **Completed**: Finished uploads (optional)

**Technical Details:**
- Tab state stored in QSettings
- Each tab maintains independent gallery list
- Shared database with `tab` column for filtering
- Thread-safe tab switching

---

### Gallery Renaming
**Version:** All versions
**Description:** Flexible gallery naming with conflict detection.

**Features:**
- **F2 Shortcut**: Quick rename selected gallery
- **Unrenamed Tracking**: Dialog for galleries without custom names
- **Duplicate Detection**: Warns if gallery name already exists
- **Bulk Rename**: Rename multiple galleries with patterns
- **Auto-sanitization**: Remove invalid characters for URLs

**Unrenamed Gallery Dialog:**
- Lists all galleries using default folder names
- Batch rename with pattern matching
- Preview new names before applying
- Persistent tracking in `~/.imxup/unnamed_galleries.json`

---

## Multi-Host Upload System

**Version:** v0.6.00 (Major Feature)
**Description:** Upload galleries to 7 file hosting services simultaneously.

### Supported File Hosts (7 Total)

#### 1. **Fileboom** (fboom.me)
- **Authentication:** API Key (permanent token)
- **Max File Size:** 10 GB
- **Storage:** 10 TB (premium accounts)
- **Upload Method:** Multi-step (init -> upload -> verify)
- **Connections:** Up to 2 simultaneous uploads
- **Features:**
  - File deduplication (skip if already exists)
  - Automatic MD5 hash verification
  - Resume support
  - Multi-step upload protocol

**Configuration:**
```json
{
  "name": "Fileboom",
  "auth_type": "bearer",
  "upload_init_url": "https://fboom.me/api/upload/getinfo?api_key={token}",
  "response_type": "json",
  "link_prefix": "https://fboom.me/file/"
}
```

---

#### 2. **Filedot** (filedot.to)
- **Authentication:** Session-based (username/password)
- **Session Management:** Automatic CAPTCHA solving
- **Features:**
  - CSRF protection handling
  - Session persistence
  - Cookie-based authentication
  - Visual CAPTCHA parsing via CSS position

**CAPTCHA Solving Example:**
```html
<!-- Visual CAPTCHA with CSS positioning -->
<span style="padding-left:26px">2</span>
<span style="padding-left:45px">8</span>
<span style="padding-left:67px">1</span>

<!-- Parsed as: [(26, '2'), (45, '8'), (67, '1')] -->
<!-- Sorted by position: "281" -->
```

**Workflow:**
1. Visit login page (GET request)
2. Extract CSRF tokens from hidden fields
3. Parse CAPTCHA via CSS `padding-left` positions
4. Submit login form (POST request)
5. Store session cookies for future requests

---

#### 3. **Filespace** (filespace.com)
- **Authentication:** Cookie-based sessions (`xfss` cookie)
- **Features:**
  - Simple session management
  - Automatic retry on transient failures
  - No CAPTCHA required
  - Cookie persistence across uploads

---

#### 4. **Keep2Share** (k2s.cc)
- **Authentication:** API Key (same structure as Fileboom)
- **Max File Size:** 10 GB
- **Storage:** 10 TB (premium accounts)
- **Connections:** Up to 2 simultaneous uploads
- **Features:** Identical API to Fileboom

---

#### 5. **Rapidgator** (rapidgator.net)
- **Authentication:** Token login (temporary token with 24h TTL)
- **Max File Size:** 5 GB
- **Upload Method:** Multi-step with polling
  - **Step 1**: Init upload session -> Get upload URL
  - **Step 2**: Upload file to dedicated server
  - **Step 3**: Poll for completion (10 retries @ 1s intervals)
- **Features:**
  - MD5 hash verification
  - Token caching (24-hour expiry)
  - State-based upload tracking
  - Automatic token refresh

**Token Management:**
```python
# Token cached in .imxup/token_cache.db
{
  "host": "rapidgator",
  "token": "abc123xyz789",
  "expiry": 1700000000,  # Unix timestamp
  "ttl": 86400,  # 24 hours in seconds
  "created_at": 1699913600
}
```

---

#### 6. **Tezfiles** (tezfiles.com)
- **Authentication:** API Key
- **Features:**
  - API key extraction from account settings
  - Simple upload protocol
  - Automatic token refresh on expiry

---

#### 7. **Katfile** (katfile.com)
- **Authentication:** API Key
- **Status:** In development
- **Features:**
  - API key-based authentication
  - Integration with upload pipeline

---

### Authentication Methods

#### Method 1: API Key (Permanent Token)
**Hosts:** Fileboom, Keep2Share, Tezfiles, Katfile

**Advantages:**
- No login required per session
- Permanent (doesn't expire)
- Simple one-time setup
- High security

**Setup:**
1. Log into file host account
2. Navigate to Account -> API Settings
3. Generate or copy your API key
4. Paste into imxup Settings -> File Hosts -> Configure
5. Click **Test Connection** to verify

**Security:**
- API keys stored in system keyring
- Encrypted at rest using Fernet symmetric encryption
- Never logged or exposed in error messages
- User-only read/write permissions

---

#### Method 2: Token Login (Username/Password -> Temporary Token)
**Hosts:** Rapidgator

**Workflow:**
1. User provides credentials in format: `username:password`
2. imxup performs login request to obtain token
3. Extracts authentication token from JSON response
4. Caches token with TTL (24 hours for Rapidgator)
5. Automatically refreshes token on expiration or 401/403 errors

**Token Cache:**
- **Location**: `~/.imxup/token_cache.db` (SQLite)
- **Schema**:
```sql
CREATE TABLE tokens (
  host TEXT PRIMARY KEY,
  token TEXT NOT NULL,
  expiry INTEGER NOT NULL,
  ttl INTEGER NOT NULL,
  created_at INTEGER NOT NULL
);
```

**Auto-Refresh Logic:**
- Check token expiry before each upload
- Refresh if expiry < 5 minutes
- Retry upload once if 401/403 received
- Re-authenticate on refresh failure

---

#### Method 3: Session-Based (Username/Password -> Cookies)
**Hosts:** Filedot, Filespace

**Features:**
- **Cookie Persistence**: Cookies reused across uploads
- **CAPTCHA Solving**: Visual CAPTCHAs solved using CSS position parsing
- **Token Extraction**: Session IDs extracted from upload page HTML
- **Automatic Refresh**: Expired sessions re-authenticated transparently
- **CSRF Protection**: Automatic CSRF token extraction and submission

**Login Flow:**
1. GET request to login page
2. Extract hidden fields (CSRF tokens, session IDs)
3. Parse CAPTCHA (if present) via CSS positioning
4. POST login form with credentials + CAPTCHA
5. Store session cookies (`Set-Cookie` headers)
6. Validate login success (check for error messages)
7. Extract upload session tokens from page HTML

---

### Connection Management

**Features:**
- **Global Limit**: Maximum total concurrent file host uploads (default: 3)
- **Per-Host Limit**: Maximum concurrent uploads per host (default: 2)
- **Connection Pooling**: Reuse HTTP connections across uploads
- **Semaphore-Based**: Thread-safe connection slot management
- **Dynamic Adjustment**: Update limits without restarting

**Configuration:**
```python
CONNECTION_LIMITS = {
  "global_max": 3,        # Total across all hosts
  "per_host_max": 2,      # Per individual host
  "timeout": 30,          # Request timeout (seconds)
  "retry_attempts": 3,    # Auto-retry count
  "retry_delay": 5        # Delay between retries (seconds)
}
```

**Semaphore Implementation:**
```python
# Global semaphore limits total concurrent uploads
global_semaphore = threading.Semaphore(3)

# Per-host semaphores limit per-host concurrency
host_semaphores = {
  "rapidgator": threading.Semaphore(2),
  "fileboom": threading.Semaphore(2),
  # ...
}
```

---

### Bandwidth Tracking

**Features:**
- **Real-time Speed**: Upload speed in MB/s shown in status bar
- **Total Uploaded**: Session-wide bytes uploaded across all hosts
- **Per-Host Breakdown**: Individual host bandwidth in logs
- **Thread-Safe Counter**: Atomic counter for accurate multi-threaded aggregation
- **Historical Data**: Track upload statistics over time

**Display:**
```
Status Bar: Upload 2.5 MB/s | Total: 127.3 MB / 245.8 MB | ETA: 3m 24s
```

---

### Multi-Host Download Links

**Placeholder:** `#hostLinks#`
**Version:** v0.6.00

**Description:** Automatically generate BBCode download links for all enabled file hosts.

**Example Output:**
```bbcode
[b]Download:[/b]
[url=https://fboom.me/file/abc123]Fileboom[/url] | [url=https://rapidgator.net/file/xyz789]Rapidgator[/url] | [url=https://k2s.cc/file/def456]Keep2Share[/url]
```

**Template Usage:**
```bbcode
[if hostLinks]
[b]Download Links:[/b]
#hostLinks#
[else]
[i]No file host uploads configured[/i]
[/if]
```

---

## Archive & Compression

**Version:** v0.5.13+
**Description:** Advanced ZIP archive handling for gallery compression and extraction.

### ZIP Creation

**Features:**
- **Auto-compression**: Automatically create ZIP archives for upload
- **Compression Modes**:
  - **STORE** (0): No compression (0.5-2x faster, recommended for images)
  - **DEFLATE** (8): Standard compression
  - **BZIP2** (12): High compression
  - **LZMA** (14): Maximum compression
- **Temporary Files**: Auto-cleanup after upload
- **Unique Prefixes**: Prevent collisions with `imxup_<gallery_id>_` prefix
- **Progress Tracking**: Real-time compression progress

**Usage Example:**
```bash
# External app parameter: %z
# Automatically creates temporary ZIP, uploads, then deletes
python hooks/muh.py gofile "%z"
```

**Technical Details:**
- Uses Python `zipfile` module
- STORE mode: 0.2-0.5 seconds for 250 MB gallery
- DEFLATE mode: 3-8 seconds for 250 MB gallery (minimal size reduction for images)
- Temporary location: System temp directory
- Auto-cleanup on upload completion or error

---

### ZIP Extraction

**Features:**
- **Supported Formats**: ZIP, RAR, 7Z, TAR, TAR.GZ, TAR.BZ2
- **Auto-detect**: Automatic format detection from file extension
- **Folder Scanning**: Scan extracted archive for image-containing folders
- **Multi-Folder Selection**: Select which folders to upload from archive
- **Validation**: Verify archive integrity before extraction
- **Progress Updates**: Track extraction progress
- **Error Handling**: Graceful handling of corrupted archives
- **Cleanup**: Automatic deletion of temporary extraction directory

**Archive Folder Selector Dialog:**
```
+-- Select Folders to Upload ---------------+
| Archive: vacation_photos.zip              |
| Extracted to: /tmp/imxup_extract          |
|                                           |
| Found 3 image folders:                    |
| [x] Day1_Beach (127 images)               |
| [x] Day2_City (84 images)                 |
| [x] Day3_Mountain (95 images)             |
|                                           |
|      [Select All] [Upload] [Cancel]       |
+-------------------------------------------+
```

---

### Archive Coordinator

**Component:** `src/processing/archive_coordinator.py`

**Features:**
- **Parallel Processing**: Handle multiple archives simultaneously
- **Worker Pool**: Spawn workers for compression/extraction
- **Queue Integration**: Seamless integration with upload queue
- **Status Tracking**: Real-time progress for archive operations
- **Thread-Safe**: Safe concurrent operations

**Worker Architecture:**
```
 ArchiveCoordinator
 +-- ArchiveWorker #1 (compression thread)
 +-- ArchiveWorker #2 (extraction thread)
 +-- ArchiveWorker #3 (validation thread)
```

---

## BBCode Generation & Templates

**Version:** All versions
**Description:** Powerful template system for generating formatted forum posts.

### 18 Available Placeholders (Gallery Info + File Hosts + Custom Fields)

#### Gallery Information (9 placeholders)

| Placeholder | Description | Example Output |
|-------------|-------------|----------------|
| `#folderName#` | Gallery name | `Summer Vacation 2024` |
| `#pictureCount#` | Number of images | `127` |
| `#width#` | Average width (px) | `4000` |
| `#height#` | Average height (px) | `3000` |
| `#longest#` | Longest dimension (px) | `4000` |
| `#extension#` | File format (uppercase) | `JPG` |
| `#folderSize#` | Total size | `245.8 MB` |
| `#galleryLink#` | imx.to gallery URL | `https://imx.to/g/abc123` |
| `#allImages#` | BBCode for all images | `[img]...[/img]` |

#### File Host Links (1 placeholder)

| Placeholder | Description | Example Output |
|-------------|-------------|----------------|
| `#hostLinks#` | Download links | `[url=...]Fileboom[/url] \| [url=...]Rapidgator[/url]` |

#### Custom Fields (8 placeholders)

| Placeholder | Description | Use Case |
|-------------|-------------|----------|
| `#custom1#` - `#custom4#` | User-defined fields | Photographer, camera, location, license |
| `#ext1#` - `#ext4#` | External app outputs | Upload links, processing results, ratings |

**Example Usage:**
```bbcode
[center][b]#folderName#[/b][/center]

[b]Gallery Stats:[/b]
- Images: #pictureCount# (#extension# format)
- Resolution: #width#x#height# (longest: #longest#px)
- Size: #folderSize#

[if galleryLink]
[b]Gallery:[/b] [url=#galleryLink#]View on imx.to[/url]
[/if]

[if hostLinks]
[b]Download:[/b]
#hostLinks#
[/if]

#allImages#
```

---

### Conditional Logic

**Syntax:**
```bbcode
[if placeholder]Content[/if]
[if placeholder=value]Content[/if]
[if placeholder]True[else]False[/if]
```

**Examples:**

**Simple Conditional:**
```bbcode
[if galleryLink]
[b]Source:[/b] [url=#galleryLink#]View Original Gallery[/url]
[/if]
```

**Value Comparison:**
```bbcode
[if extension=PNG]
  [i]Lossless PNG format - high quality![/i]
[else]
  [i]Standard JPG format[/i]
[/if]
```

**Nested Conditionals:**
```bbcode
[if pictureCount]
  [b]Gallery contains #pictureCount# images[/b]
  [if pictureCount>100]
    [i]Large gallery - may take time to load![/i]
  [/if]
[else]
  [b]Empty gallery[/b]
[/if]
```

**File Host Links:**
```bbcode
[if hostLinks]
[b]Alternative Downloads:[/b]
#hostLinks#
[else]
[i]Direct download only (no file hosts configured)[/i]
[/if]
```

**Custom Fields:**
```bbcode
[if custom1]
[b]Photographer:[/b] #custom1#
[/if]

[if ext1]
[b]External Link:[/b] [url=#ext1#]Download ZIP[/url]
[/if]
```

---

### Template Manager

**Component:** `src/gui/dialogs/template_manager.py`
**Access:** Settings -> BBCode -> **Manage Templates**

**Features:**
- **CRUD Operations**:
  - Create new templates
  - Edit existing templates
  - Delete templates (except default)
  - Rename templates
- **Syntax Highlighting**:
  - Placeholders: Yellow background
  - Conditionals: Blue background
  - BBCode tags: Green text
  - Real-time highlighting as you type
- **Placeholder Buttons**: Click to insert at cursor position
- **Conditional Helper**: Dialog-based conditional tag builder
- **Validation**:
  - Check for invalid placeholders
  - Verify matched `[if]`/`[/if]` pairs
  - Detect orphaned `[else]` tags
  - Validate BBCode tag matching
- **Import/Export**: Share templates between installations

**Template Storage:**
```
~/.imxup/templates/
+-- Default Template.template.txt
+-- Detailed Example.template.txt
+-- Compact Template.template.txt
+-- My Custom Template.template.txt
```

**Built-in Templates:**
- **Default Template**: Simple gallery info with images
- **Detailed Example**: All placeholders with conditionals
- **Compact Template**: Minimal info, images only

**Keyboard Shortcuts:**
- **Ctrl+N**: New template
- **Ctrl+S**: Save template
- **Ctrl+P**: Preview BBCode
- **F5**: Refresh template list
- **Ctrl+I**: Insert placeholder dialog

---

### BBCode Viewer

**Component:** `src/gui/dialogs/bbcode_viewer.py`
**Access:** Right-click gallery -> **View BBCode**

**Features:**
- **Syntax Highlighting**: Color-coded BBCode display
  - BBCode tags: Green (`#008000`)
  - URLs: Blue (`#0066cc`)
  - Bold text: Red (`#cc0000`)
- **One-Click Copy**: Copy entire BBCode to clipboard
- **Multi-Select**: View BBCode for multiple galleries combined
- **Template Switching**: Change template and regenerate
- **Export**: Save BBCode to text file
- **Regenerate**: Update BBCode with current template settings

**Theme Support:**
- **Dark theme**: `#1e1e1e` background, `#d4d4d4` text
- **Light theme**: `#f0f0f0` background, `#333333` text
- High contrast for readability
- Adaptive color schemes

---

## File Host Integration

**Version:** v0.6.00
**Description:** Comprehensive integration with 7 file hosting services.

### Credential Management

**Component:** `src/gui/dialogs/credential_setup.py`

**Features:**
- **System Keyring**: Secure storage using OS keyring
  - Windows: Credential Manager
  - macOS: Keychain
  - Linux: Secret Service (libsecret)
- **Encryption**: Passwords encrypted at rest using Fernet
- **Test Connection**: Validate credentials before saving
- **Account Info Display**:
  - Storage quota (used/total)
  - Premium status
  - Expiry date
  - Account email
- **Multiple Accounts**: Support multiple accounts per host

**Storage Methods:**
```python
# Method 1: System Keyring (preferred)
import keyring
keyring.set_password("imxup", "rapidgator", "username:password")

# Method 2: Encrypted config file (fallback)
# ~/.imxup/credentials.enc
from cryptography.fernet import Fernet
cipher = Fernet(key)
encrypted = cipher.encrypt(b"username:password")
```

---

### File Host Configuration Dialog

**Component:** `src/gui/dialogs/file_host_config_dialog.py`

**Per-Host Settings:**
- Enable/disable host
- Max connections (1-10)
- Retry attempts (1-10)
- Timeout (10-120 seconds)
- Custom API endpoints

**Authentication Setup:**
- API key input (Fileboom, Keep2Share, Tezfiles, Katfile)
- Username/password format: `username:password`
- Token TTL configuration

**Test Connection:**
- Uploads small dummy file (1 KB)
- Verifies authentication
- Retrieves account information
- Deletes test file (if host supports it)
- Displays success/error message

**UI Example:**
```
+-- File Host Configuration ----------------+
| Host: Rapidgator [dropdown]               |
| [x] Enable this host                      |
|                                           |
| Credentials:                              |
| +---------------------------------------+ |
| | username:password                     | |
| +---------------------------------------+ |
| [Test Connection]                         |
|                                           |
| Settings:                                 |
| Max Connections: [2] [dropdown]           |
| Retry Attempts:  [3] [dropdown]           |
| Timeout:         [30] seconds             |
|                                           |
| Account Info:                             |
| Premium until: 2025-12-31                 |
| Storage: 245.8 GB / 1000 GB               |
| Email: user@example.com                   |
|                                           |
|          [Save]  [Cancel]                 |
+-------------------------------------------+
```

---

### Token Cache System

**Component:** `src/network/token_cache.py`
**Database:** `~/.imxup/token_cache.db` (SQLite)

**Features:**
- **Persistent Storage**: Tokens survive application restarts
- **TTL Management**: Automatic expiry tracking
- **Auto-Refresh**: Refresh tokens before expiration
- **Thread-Safe**: Concurrent access support with locks
- **Per-Host Cache**: Separate cache entries for each host
- **Cleanup**: Remove expired tokens automatically

**Schema:**
```sql
CREATE TABLE tokens (
  host TEXT PRIMARY KEY,
  token TEXT NOT NULL,
  expiry INTEGER NOT NULL,  -- Unix timestamp
  ttl INTEGER NOT NULL,     -- Time To Live in seconds
  created_at INTEGER NOT NULL
);
```

**TTL Values:**
```python
TOKEN_TTL = {
  "rapidgator": 86400,   # 24 hours
  "fileboom": 0,         # Permanent (API key)
  "keep2share": 0,       # Permanent (API key)
  "filedot": 3600,       # 1 hour (session)
  "filespace": 3600,     # 1 hour (session)
  "tezfiles": 0,         # Permanent (API key)
  "katfile": 0           # Permanent (API key)
}
```

**API:**
```python
class TokenCache:
    def get_token(self, host: str) -> Optional[str]
    def set_token(self, host: str, token: str, ttl: int)
    def is_expired(self, host: str) -> bool
    def refresh_token(self, host: str) -> bool
    def clear_token(self, host: str)
    def cleanup_expired()
```

---

### File Host Clients

**Component:** `src/network/file_host_client.py`

**Architecture:**
```
FileHostClient (abstract base class)
+-- FileboomClient
+-- FiledotClient
+-- FilespaceClient
+-- Keep2ShareClient
+-- RapidgatorClient
+-- TezfilesClient
+-- KatfileClient
```

**Common Interface:**
```python
class FileHostClient:
    def authenticate(self) -> bool
    def upload_file(self, filepath: Path) -> str
    def get_account_info(self) -> dict
    def test_connection(self) -> bool
    def refresh_token(self) -> bool
    def is_authenticated(self) -> bool
```

**Upload Flow:**
```python
# 1. Authenticate (if needed)
if not client.is_authenticated():
    success = client.authenticate()
    if not success:
        raise AuthenticationError("Login failed")

# 2. Initialize upload (multi-step hosts)
upload_info = client.init_upload(
    filename="vacation.zip",
    filesize=245823412
)

# 3. Upload file
upload_url = upload_info.get("url")
response = client.upload_file(filepath, upload_url)

# 4. Poll for completion (if required)
if client.requires_polling():
    upload_id = upload_info.get("upload_id")
    status = client.poll_upload(upload_id, max_retries=10)

# 5. Extract download link
download_link = client.extract_link(response)
return download_link
```

---

## Template System

### Template Storage Format

**Location:** `~/.imxup/templates/*.template.txt`
**Encoding:** UTF-8
**Format:** Plain text with BBCode and placeholder syntax

**Example Template:**
```bbcode
[center][b]Gallery: #folderName#[/b][/center]

[b]Statistics:[/b]
- Images: #pictureCount# (#extension# format)
- Resolution: #width#x#height# (longest side: #longest#px)
- Total Size: #folderSize#

[if galleryLink]
[b]Gallery Link:[/b] [url=#galleryLink#]View on imx.to[/url]
[/if]

[if hostLinks]
[b]Download:[/b]
#hostLinks#
[/if]

[if custom1]
[b]Photographer:[/b] #custom1#
[/if]

[if custom2]
[b]Location:[/b] #custom2#
[/if]

[b]Images:[/b]
#allImages#
```

---

### Template Syntax Highlighting

**Features:**
- **Placeholders**: Yellow background (`#ffff00` with 30% opacity)
- **Conditionals**: Blue background (`#0066cc` with 20% opacity)
- **BBCode Tags**: Green text (`#008000`)
- **URLs**: Purple text (`#9900ff`)
- **Comments**: Gray text (`#808080`)
- **Real-time**: Updates as you type
- **Theme-Aware**: Adapts colors for dark/light themes

**Theme Support:**
```python
# Dark theme colors
DARK_THEME = {
  "placeholder": "#ffff00",
  "conditional": "#3399ff",
  "bbcode": "#00cc00",
  "url": "#cc99ff",
  "text": "#d4d4d4"
}

# Light theme colors
LIGHT_THEME = {
  "placeholder": "#ffcc00",
  "conditional": "#0066cc",
  "bbcode": "#008000",
  "url": "#9900ff",
  "text": "#333333"
}
```

---

### Template Validation

**Validation Rules:**
1. **Placeholder Check**: All placeholders must be from the 18 recognized placeholders
2. **Conditional Syntax**: Matching `[if]...[/if]` pairs
3. **Nested Conditionals**: Proper nesting (max 2 levels)
4. **Else Placement**: `[else]` only within `[if]...[/if]`
5. **BBCode Tags**: Matching opening/closing tags
6. **URL Syntax**: Valid URL structure in `[url]` tags

**Error Messages:**
```
Error Line 5: Unknown placeholder: #invalidPlaceholder#
   Valid placeholders: #folderName#, #pictureCount#, ...

Error Line 12: Unclosed conditional tag
   Found: [if pictureCount]
   Missing: [/if]

Error Line 18: Orphaned [else] tag without matching [if]

Error Line 23: Unmatched BBCode tag
   Found: [b]Bold text
   Missing: [/b]

Error Line 30: Invalid URL syntax
   Found: [url]Invalid[/url]
   Expected: [url=http://...]Text[/url]
```

---

## Automation & Hooks

**Version:** v0.5.12+
**Description:** External script integration for custom workflows and automation.

### Hook System

**Component:** `src/processing/hooks_executor.py`

**Hook Types:**
- **Pre-Upload**: Execute before gallery upload starts
- **Post-Upload**: Execute after gallery upload completes
- **On-Complete**: Execute when gallery fully processed
- **On-Error**: Execute if gallery upload fails

**Features:**
- Parameter substitution (15+ parameters)
- JSON output mapping to ext1-4 fields
- Error handling with detailed logging
- Timeout control (configurable per app)
- Async execution (non-blocking)

---

### External Apps Configuration

**Access:** Settings -> External Apps

**Configuration Fields:**
- **Name**: Display name for the app
- **Command**: Executable path (python, node, etc.)
- **Arguments**: Command arguments with parameter substitution
- **Working Directory**: Execution directory
- **Capture Output**: Capture stdout/stderr
- **Execute On**: Event trigger (queued, uploading, completed, failed)
- **Timeout**: Max execution time (seconds)
- **Output Mapping**:
  - Map JSON output to ext1-4 fields
  - JSONPath syntax supported
  - Example: `$.download_link` -> ext1

**Example Configuration:**
```json
{
  "name": "Upload to Gofile",
  "command": "python",
  "args": ["hooks/muh.py", "gofile", "%z"],
  "working_directory": "/home/user/imxup",
  "capture_output": true,
  "execute_on": "completed",
  "timeout": 300,
  "output_mapping": {
    "ext1": "$.download_link",
    "ext2": "$.file_id",
    "ext3": "$.file_size",
    "ext4": "$.upload_time"
  }
}
```

---

### Parameter Substitution

**Available Parameters:**

| Parameter | Description | Example Value |
|-----------|-------------|---------------|
| `%N` | Gallery name | `Summer Vacation` |
| `%T` | Tab name | `Main` |
| `%p` | Gallery folder path | `/home/user/images/vacation` |
| `%C` | Image count | `127` |
| `%s` | Size in bytes | `245823412` |
| `%t` | Template name | `Detailed Example` |
| `%g` | Gallery ID (completed only) | `abc123xyz` |
| `%j` | JSON artifact path | `~/.imxup/artifacts/abc123.json` |
| `%b` | BBCode file path | `~/.imxup/bbcode/abc123.txt` |
| `%z` | ZIP path (auto-created) | `/tmp/imxup_abc123_vacation.zip` |
| `%c1-%c4` | Custom field values | User-defined |
| `%e1-%e4` | Extension field values | External app outputs |

**Usage Example:**
```bash
# Upload ZIP to external host after gallery completes
python hooks/muh.py gofile "%z"

# Process images with metadata
python hooks/process.py --name "%N" --count %C --path "%p"

# Send notification with gallery details
curl -X POST https://api.example.com/notify \
  -H "Content-Type: application/json" \
  -d '{"gallery":"%N","count":%C,"link":"%g"}'
```

---

### Multi-Host Uploader (muh.py)

**Component:** `hooks/muh.py`
**Version:** v0.6.00
**Description:** Standalone multi-host file uploader inspired by PolyUploader.

**Supported Hosts:**
- Gofile
- Pixeldrain
- Litterbox
- Filedot
- Rapidgator
- Catbox
- (Extensible via JSON config)

**Features:**
- **Minimal Dependencies**: Only `requests` required
- **JSON Output**: Returns structured data for mapping
- **Auto-Cleanup**: Deletes temporary files
- **Error Handling**: Detailed error messages
- **Parameter Mapping**: Maps output to ext1-4 fields

**Usage:**
```bash
# Upload file to Gofile
python muh.py gofile /path/to/file.zip

# Upload with credentials
python muh.py rapidgator /path/to/file.zip username:password

# Upload from imxup hook (auto-created ZIP)
python muh.py gofile "%z"
```

**Example Output:**
```json
{
  "success": true,
  "host": "gofile",
  "download_link": "https://gofile.io/d/abc123",
  "file_id": "abc123",
  "file_name": "vacation.zip",
  "file_size": 245823412,
  "upload_time": 12.34,
  "expires": null
}
```

**Field Mapping in imxup:**
```json
{
  "ext1": "$.download_link",  // https://gofile.io/d/abc123
  "ext2": "$.file_id",        // abc123
  "ext3": "$.file_size",      // 245823412
  "ext4": "$.upload_time"     // 12.34
}
```

---

### Auto-ZIP Creation

**Feature:** Automatic temporary ZIP creation for external hooks
**Parameter:** `%z`

**Behavior:**
1. User configures external app with `%z` parameter
2. Gallery upload completes
3. imxup creates temporary ZIP:
   - Location: System temp directory
   - Name: `imxup_<gallery_id>_<gallery_name>.zip`
   - Compression: STORE mode (no compression, fastest)
   - Contents: All images from gallery
4. External app executes with ZIP path
5. ZIP automatically deleted after execution (success or failure)

**Benefits:**
- No manual ZIP creation
- Automatic cleanup
- Fast STORE mode compression
- Unique naming prevents collisions

---

## Configuration & Settings

**Version:** All versions
**Description:** Comprehensive settings system with persistent storage.

### Settings Dialog

**Component:** `src/gui/settings_dialog.py`
**Access:** Ctrl+, or File -> Settings

**Tabs:**
1. **General**: Application-wide settings
   - Window behavior
   - Theme selection
   - Single-instance mode
   - System tray integration
2. **Upload**: Upload behavior and retries
   - Max retry attempts (1-10)
   - Retry delay (1-60 seconds)
   - Parallel workers (1-10)
   - Thumbnail size and format
   - Gallery visibility (public/private)
3. **BBCode**: Template selection and management
   - Default template
   - Auto-copy to clipboard
   - Include host links
   - Template manager
4. **File Hosts**: Multi-host upload configuration
   - Enable/disable hosts
   - Credentials management
   - Connection limits
   - Test connections
5. **External Apps**: Hook system configuration
   - Add/edit/delete apps
   - Parameter substitution
   - Output mapping
   - Event triggers
6. **Logging**: Log level and output settings
   - Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
   - Max log lines (100-10000)
   - Auto-scroll
   - Log file location
7. **Advanced**: Database, cache, and performance
   - Database maintenance
   - Cache management
   - Performance tuning
   - Debug options

---

### Adaptive Settings Panel

**Component:** `src/gui/widgets/adaptive_settings_panel.py`
**Version:** v0.5.12+

**Features:**
- **Context-Aware**: Shows/hides options based on selections
- **Dynamic Validation**: Real-time input validation
- **Tooltips**: Hover help for all settings
- **Reset Options**:
  - Per-section reset
  - Global reset to defaults
- **Search/Filter**: Filter settings by keyword
- **Collapsible Sections**: Minimize sections to save space

**Adaptive Behavior Example:**
```python
# File host settings only visible when host enabled
if fileboom_enabled:
    show(fileboom_api_key_field)
    show(fileboom_max_connections)
    show(fileboom_test_button)
else:
    hide(fileboom_api_key_field)
    hide(fileboom_max_connections)
    hide(fileboom_test_button)
```

---

### Settings Storage

**Locations:**

**Windows:**
```
Registry: HKEY_CURRENT_USER\Software\ImxUploader\ImxUploadGUI
Files: %APPDATA%\ImxUploader\
  +-- settings.ini
  +-- imxup.db
  +-- token_cache.db
  +-- templates/
```

**Linux:**
```
Config: ~/.config/ImxUploader/ImxUploadGUI.conf
Files: ~/.imxup/
  +-- imxup.ini
  +-- imxup.db
  +-- token_cache.db
  +-- templates/
  +-- artifacts/
  +-- bbcode/
```

**Stored Settings:**
```python
SETTINGS = {
  # Window
  "window/width": 1200,
  "window/height": 800,
  "window/x": 100,
  "window/y": 100,
  "window/maximized": False,
  "window/theme": "auto",  # auto, dark, light

  # Upload
  "upload/max_retries": 3,
  "upload/retry_delay": 5,
  "upload/parallel_workers": 4,
  "upload/thumbnail_size": 3,  # 250x250
  "upload/thumbnail_format": 2,  # JPEG 90%
  "upload/public_gallery": True,

  # BBCode
  "bbcode/template": "Default Template",
  "bbcode/auto_copy": True,
  "bbcode/include_host_links": True,

  # File Hosts
  "filehosts/global_max": 3,
  "filehosts/fileboom/enabled": False,
  "filehosts/fileboom/max_connections": 2,
  "filehosts/rapidgator/enabled": False,
  "filehosts/rapidgator/max_connections": 2,

  # UI
  "ui/show_tray_icon": True,
  "ui/minimize_to_tray": True,
  "ui/confirm_delete": True,
  "ui/show_splash": True,

  # Logging
  "logging/level": "INFO",
  "logging/max_lines": 1000,
  "logging/auto_scroll": True,
  "logging/show_prefix": True
}
```

---

## User Interface

**Version:** All versions
**Platform:** PyQt6
**Description:** Modern, responsive GUI with dark/light theme support.

### Main Window

**Component:** `src/gui/main_window.py`

**Layout:**
```
+-- ImXup v0.6.16 -----------------------------+
| File  Edit  View  Tools  Help                |
+----------------------------------------------+
| +-- Tabs ----------------------------------+ |
| | Main(3) | Archive(0) | File Hosts(1) | + | |
| +------------------------------------------+ |
| | Gallery Queue                            | |
| | +--------------------------------------+ | |
| | | Name          | Status    | Progress | | |
| | +---------------+-----------+----------+ | |
| | | Vacation      | Done      | [#####]  | | |
| | | Birthday      | Paused    | [###..]  | | |
| | | Event Photos  | Upload    | [##...]  | | |
| | +--------------------------------------+ | |
| +------------------------------------------+ |
| +-- Quick Settings ------------------------+ |
| | Template: [Detailed Example v]           | |
| | Public: [x]  Retries: [3v]  Size: [250v] | |
| +------------------------------------------+ |
| +-- Controls ------------------------------+ |
| | [Start All] [Pause All] [Clear Done]     | |
| | [Settings]  [View BBCode] [Help]         | |
| +------------------------------------------+ |
| Status: Upload 2.5 MB/s | 127.3/245.8 MB    |
+----------------------------------------------+
```

**Features:**
- Drag & drop anywhere in window
- Resizable with minimum 800x600
- Status bar shows upload speed and progress
- Menu bar with keyboard shortcuts
- System tray icon
- Single-instance mode
- Theme-aware styling

---

### Keyboard Shortcuts

**Tab Management:**
- **Ctrl+T**: Create new tab
- **Ctrl+W**: Close current tab (except Main)
- **Ctrl+Tab**: Switch to next tab
- **Ctrl+Shift+Tab**: Switch to previous tab

**Gallery Management:**
- **Delete**: Remove selected galleries from queue
- **Ctrl+C**: Copy BBCode for selected galleries
- **F2**: Rename selected gallery
- **Ctrl+A**: Select all galleries
- **Ctrl+Shift+A**: Deselect all

**Application:**
- **Ctrl+,**: Open settings dialog
- **Ctrl+.**: Show keyboard shortcuts help
- **Ctrl+L**: Open log viewer
- **Ctrl+Q**: Quit application
- **Ctrl+R**: Refresh queue
- **F5**: Refresh current view

**Context Menu** (Right-click gallery):
- Copy BBCode
- Open gallery link
- Regenerate BBCode
- Move to tab
- View BBCode dialog
- Remove from queue
- Retry upload

---

### Themes

**Supported Themes:**
- **Auto**: System theme detection (Windows 11, modern Linux)
- **Dark**: Dark mode with `#1e1e1e` background
- **Light**: Light mode with `#f0f0f0` background

**Stylesheet:** `assets/styles.qss`

**Dark Theme:**
```css
QMainWindow {
  background-color: #1e1e1e;
  color: #d4d4d4;
}

QPushButton {
  background-color: #2d2d30;
  color: #ffffff;
  border: 1px solid #3e3e42;
  padding: 5px 15px;
  border-radius: 3px;
}

QPushButton:hover {
  background-color: #3e3e42;
}

QTableWidget {
  background-color: #252526;
  alternate-background-color: #2d2d30;
  gridline-color: #3e3e42;
  color: #d4d4d4;
}

QTextEdit {
  background-color: #222222;  /* Code background */
  color: #d4d4d4;
  selection-background-color: #264f78;
  border: 1px solid #3e3e42;
}
```

---

### Icon Manager

**Component:** `src/gui/icon_manager.py`

**Features:**
- **Theme-Aware**: Automatic icon selection for dark/light themes
- **SVG Support**: Vector icons scale perfectly
- **Icon Cache**: In-memory cache for performance
- **Fallback Icons**: Default icons if custom not found
- **Dynamic Loading**: Load icons on-demand
- **High-DPI Support**: Crisp icons on Retina/4K displays

**Icon Categories:**
- **Status**: queued, uploading, completed, failed, paused
- **Actions**: start, pause, stop, retry, delete, copy
- **File Hosts**: Logos for Fileboom, Rapidgator, Keep2Share, etc.
- **Navigation**: tabs, settings, help, logs

**Icon Locations:**
```
assets/
+-- status_queued-dark.png
+-- status_queued-light.png
+-- status_uploading-001-dark.png
+-- status_uploading-001-light.png
+-- status_uploading-002-dark.png
+-- status_uploading-003-dark.png
+-- status_uploading-004-dark.png
+-- status_completed-dark.png
+-- status_failed-dark.png
+-- hosts/
|   +-- logo/
|       +-- fileboom-icon.png
|       +-- fileboom-icon-dim.png
|       +-- rapidgator-icon.png
|       +-- keep2share-icon.png
|       +-- tezfiles-icon.png
|       +-- filedot-icon.png
|       +-- filespace-icon.png
|       +-- katfile-icon.png
+-- styles.qss
```

**API:**
```python
from src.gui.icon_manager import get_icon_manager

icon_manager = get_icon_manager()

# Get themed icon
icon = icon_manager.get_icon("status_uploading", theme="dark")

# Get file host icon
icon = icon_manager.get_host_icon("rapidgator")

# Check if icon exists
exists = icon_manager.has_icon("custom_icon")
```

---

### Progress Tracking

**Component:** `src/gui/widgets/gallery_table.py`

**Features:**
- **Individual Progress**: Per-gallery progress bars
- **Overall Progress**: Combined progress in status bar
- **Real-time Updates**: Refresh every 100ms
- **Upload Speed**: Current MB/s and average
- **ETA Calculation**: Estimated time remaining
- **Bandwidth Usage**: Total uploaded and remaining

**Progress Display:**
```
+-- Gallery: Summer Vacation ------------------+
| Status: Uploading                            |
| Progress: [########........] 42%             |
| Images: 54 / 127                             |
| Speed: 2.5 MB/s                              |
| ETA: 3m 24s                                  |
| Uploaded: 127.3 MB / 245.8 MB                |
+----------------------------------------------+
```

**Status Bar:**
```
Upload 2.5 MB/s | Total: 127.3 MB / 245.8 MB | ETA: 3m 24s | Active: 2 | Queued: 3
```

---

### Log Viewer

**Component:** `src/gui/dialogs/log_viewer.py`
**Access:** Ctrl+L or Help -> View Logs

**Features:**
- **Real-time Logging**: Live log updates
- **Log Levels**: Filter by DEBUG, INFO, WARNING, ERROR, CRITICAL
- **Category Filter**: Filter by component (upload, file_hosts, archive, etc.)
- **Search**: Find text in logs
- **Export**: Save logs to file
- **Auto-scroll**: Automatic scroll to bottom
- **Line Limit**: Max 1000 lines (configurable)
- **Syntax Highlighting**: Color-coded log levels

**Log Levels:**
```python
LOG_LEVELS = {
  "DEBUG": logging.DEBUG,      # Detailed diagnostic info
  "INFO": logging.INFO,        # General information
  "WARNING": logging.WARNING,  # Warning messages
  "ERROR": logging.ERROR,      # Error messages
  "CRITICAL": logging.CRITICAL # Critical failures
}
```

**Color Scheme:**
- **DEBUG**: Gray
- **INFO**: White/Black (theme-dependent)
- **WARNING**: Yellow
- **ERROR**: Orange
- **CRITICAL**: Red

---

## Advanced Features

### Duplicate Detection

**Component:** `src/gui/dialogs/duplicate_detection_dialogs.py`
**Version:** All versions

**Detection Methods:**
- **Path Matching**: Compare gallery folder paths
- **Name Matching**: Compare gallery names
- **Hash Comparison**: MD5 hash of gallery contents (optional, slow)

**User Options:**
- **Skip**: Skip duplicate, don't add to queue
- **Replace**: Replace existing gallery with new one
- **Add Anyway**: Add as new entry (ignore duplicate)
- **Rename**: Automatically rename with suffix (e.g., `Gallery_2`)

**Configuration:**
```python
DUPLICATE_DETECTION = {
  "enabled": True,
  "check_path": True,      # Check folder path
  "check_name": True,      # Check gallery name
  "check_hash": False,     # MD5 hash (slow)
  "prompt_user": True      # Ask before action
}
```

---

### Gallery File Manager

**Component:** `src/gui/dialogs/gallery_file_manager.py`

**Features:**
- **File Browser**: Browse gallery images before upload
- **Bulk Selection**: Select/deselect multiple images
- **Sorting**: Sort by name, size, date, dimensions
- **Filtering**: Filter by extension, size range, dimensions
- **Image Preview**: Thumbnail previews
- **Metadata Display**: Show EXIF data
- **Delete**: Remove unwanted images before upload
- **Statistics**: Show total count, size, average dimensions

**UI:**
```
+-- Gallery File Manager ----------------------+
| Gallery: Summer Vacation                     |
| Path: /home/user/images/vacation             |
| Total: 127 images | Size: 245.8 MB           |
|                                              |
| Filter: [Extension v] [Size v] [Dims v]      |
|                                              |
| +-- Files --------------------------------+  |
| | [x] IMG_0001.jpg  3.2 MB  4000x3000    |  |
| | [x] IMG_0002.jpg  3.1 MB  4000x3000    |  |
| | [ ] IMG_0003.jpg  3.3 MB  4000x3000    |  |
| | [x] IMG_0004.jpg  3.0 MB  4000x3000    |  |
| +----------------------------------------+  |
|                                              |
| Selected: 3 / 127 (9.6 MB)                   |
| [Select All] [Deselect All] [Delete]         |
|                      [Upload] [Cancel]       |
+----------------------------------------------+
```

---

### Help Dialog

**Component:** `src/gui/dialogs/help_dialog.py`
**Version:** All versions

**Help Tabs:**
1. **Overview**: Application introduction and quick start
2. **Keyboard Shortcuts**: All keyboard shortcuts reference
3. **BBCode Templates**: Template syntax and placeholder guide
4. **Multi-Host Upload**: File host setup and configuration
5. **Archive Support**: ZIP extraction and compression
6. **Troubleshooting**: Common issues and solutions

**Features:**
- **Markdown Rendering**: Rich text formatting with QTextBrowser
- **Emoji Support**: Windows emoji font integration
  - Windows: Segoe UI Emoji
  - Linux: Noto Color Emoji
  - macOS: Apple Color Emoji
- **Searchable**: Find topics quickly (Ctrl+F in dialog)
- **External Links**: Open documentation URLs
- **Theme Support**: Dark/light mode rendering

**Emoji Font Stack:**
```python
font = QFont()
font.setFamilies([
  "Segoe UI",           # Base font (Windows)
  "Segoe UI Emoji",     # Emoji font (Windows)
  "Noto Color Emoji",   # Emoji font (Linux)
  "Apple Color Emoji"   # Emoji font (macOS)
])
```

---

## Database & Storage

### Queue Database

**Location:** `~/.imxup/imxup.db`
**Engine:** SQLite 3
**Component:** `src/storage/database.py`

**Schema:**
```sql
CREATE TABLE galleries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  path TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL,
  tab TEXT DEFAULT 'Main',
  template TEXT DEFAULT 'Default Template',
  custom1 TEXT,
  custom2 TEXT,
  custom3 TEXT,
  custom4 TEXT,
  ext1 TEXT,
  ext2 TEXT,
  ext3 TEXT,
  ext4 TEXT,
  created_at INTEGER NOT NULL,
  completed_at INTEGER,
  gallery_id TEXT,
  bbcode_path TEXT,
  artifact_path TEXT,
  retry_count INTEGER DEFAULT 0,
  error_message TEXT
);

CREATE INDEX idx_status ON galleries(status);
CREATE INDEX idx_tab ON galleries(tab);
CREATE INDEX idx_created_at ON galleries(created_at);
CREATE INDEX idx_gallery_id ON galleries(gallery_id);
```

**Features:**
- **ACID Compliance**: Atomic, Consistent, Isolated, Durable
- **WAL Mode**: Write-Ahead Logging for better concurrency
- **Indexes**: Fast queries by status, tab, date
- **Foreign Keys**: Optional referential integrity

---

### Queue Manager

**Component:** `src/storage/queue_manager.py`

**API:**
```python
class QueueManager:
    def add_gallery(self, name: str, path: str, tab: str = "Main") -> int
    def get_gallery(self, gallery_id: int) -> dict
    def update_status(self, gallery_id: int, status: str)
    def update_custom_field(self, gallery_id: int, field: str, value: str)
    def get_galleries_by_status(self, status: str) -> List[dict]
    def get_galleries_by_tab(self, tab: str) -> List[dict]
    def remove_gallery(self, gallery_id: int)
    def clear_completed(self)
    def count_by_status(self) -> dict
    def get_all_galleries(self) -> List[dict]
```

**Thread Safety:**
- Connection pooling for concurrent access
- Row-level locking
- Transaction isolation

---

### Database Maintenance

**Features:**
- **Auto-Vacuum**: Reclaim space after deletions
- **Integrity Check**: Verify database consistency
- **Backup**: Automatic daily backups
- **Migration**: Version-based schema migrations

**Backup Location:**
```
~/.db-backups/
+-- imxup-2025-11-17-001.db
+-- imxup-2025-11-16-001.db
+-- imxup-2025-11-15-001.db
```

**Vacuum Schedule:**
```python
# Auto-vacuum on startup if:
# - Last vacuum > 7 days ago
# - Database size > 100 MB
# - Fragmentation > 20%
```

---

### Artifact Storage

**Location:** `~/.imxup/artifacts/`
**Format:** JSON
**Purpose:** Store upload metadata and results

**Artifact Structure:**
```json
{
  "gallery_id": "abc123xyz",
  "name": "Summer Vacation",
  "path": "/home/user/images/vacation",
  "uploaded_at": 1700000000,
  "image_count": 127,
  "total_size": 245823412,
  "gallery_url": "https://imx.to/g/abc123xyz",
  "images": [
    {
      "filename": "IMG_0001.jpg",
      "url": "https://imx.to/i/abc001",
      "size": 3200000,
      "width": 4000,
      "height": 3000
    }
  ],
  "file_host_links": {
    "rapidgator": "https://rapidgator.net/file/xyz789",
    "fileboom": "https://fboom.me/file/abc123",
    "keep2share": "https://k2s.cc/file/def456"
  },
  "custom_fields": {
    "custom1": "Photographer: John Doe",
    "custom2": "Location: Hawaii"
  },
  "ext_fields": {
    "ext1": "https://gofile.io/d/abc123",
    "ext2": "file_id_12345",
    "ext3": "245823412",
    "ext4": "12.34"
  }
}
```

---

## Network & Performance

### HTTP Client

**Component:** `src/network/client.py`

**Features:**
- **Session Management**: Persistent HTTP sessions
- **Connection Pooling**: Reuse connections
- **Retry Logic**: Exponential backoff with jitter
- **Timeout Control**: Per-request timeout
- **Cookie Handling**: Automatic cookie management
- **User-Agent**: Configurable user-agent string
- **SSL/TLS**: Certificate validation

**Configuration:**
```python
SESSION_CONFIG = {
  "pool_connections": 10,
  "pool_maxsize": 100,
  "max_retries": 3,
  "timeout": 30,
  "keep_alive": True
}
```

---

### pycurl Integration

**Component:** `src/network/client.py` (pycurl backend)
**Version:** v0.6.00

**Features:**
- **High Performance**: 2-3x faster than requests library
- **Progress Callbacks**: Real-time upload progress
- **Multi-Part Uploads**: Efficient large file handling
- **SSL/TLS**: Secure connections with certificate validation
- **Resume Support**: Resume interrupted uploads

**Windows DLL Bundling:**
- **PyInstaller**: Automatic DLL inclusion
- **delvewheel**: Pre-built wheels with bundled dependencies
- **Build Verification**: Post-build checks ensure DLLs present

**DLLs Required:**
```
libcurl-*.dll
libssh2-*.dll
zlib-*.dll
openssl-*.dll (libssl, libcrypto)
nghttp2-*.dll
```

---

### Parallel Upload Workers

**Component:** `src/processing/upload_workers.py`

**Architecture:**
```
UploadCoordinator
+-- UploadWorker #1 (thread)
+-- UploadWorker #2 (thread)
+-- UploadWorker #3 (thread)
+-- UploadWorker #4 (thread)
```

**Features:**
- **Worker Pool**: Configurable number of workers (1-10)
- **Load Balancing**: Distribute galleries across workers
- **Thread Safety**: Thread-safe queue operations
- **Progress Aggregation**: Combine progress from all workers
- **Error Isolation**: Worker failure doesn't affect others
- **Dynamic Scaling**: Add/remove workers on demand

**Configuration:**
```python
WORKER_CONFIG = {
  "max_workers": 4,
  "queue_size": 100,
  "thread_timeout": 300,
  "restart_on_error": True
}
```

---

### Performance Optimizations

**Startup Optimization:**
- Lazy loading of GUI components
- Icon caching (pre-load frequently used icons)
- Database indexing (fast status/tab queries)
- Viewport rendering (render only visible table rows)

**Upload Optimization:**
- Batch progress updates (every 50ms, not per-image)
- Connection pooling (reuse HTTP connections)
- Token caching (avoid repeated authentication)
- Parallel processing (multiple galleries simultaneously)

**Memory Optimization:**
- Log line limit (max 1000 lines in viewer)
- Image sampling (sample 25 images for dimensions, not all)
- Database pagination (load galleries in batches)
- Icon cache limit (max 100 cached icons)

**Benchmark Results (v0.6.13):**
```
Startup Time: 1.2s (down from 3.5s in v0.5.12)
Gallery Load: 0.8s for 100 galleries (down from 2.1s)
BBCode Generation: 0.3s for 127 images
Upload Speed: 2.5 MB/s average (pycurl backend)
Memory Usage: 120 MB (GUI + 4 workers)
CPU Usage: 15-25% (during active upload)
```

---

## Version History

### v0.6.16 (Latest - 2026-01-03)
**Latest Release**

**Updates:**
- Audit and correct FEATURES.md for accuracy
- Add Katfile (7th file host) to feature list
- Correct queue states (11 total, not 9)
- Verify BBCode placeholder count (18 confirmed)

---

### v0.6.13 (2025-12-28)
**Latest Stable Release**

**Updates:**
- Fix help dialog performance, add emoji PNG support, improve quick settings
- Optimize theme switching speed
- Refactor worker table, extract ArtifactHandler, add worker logo setting
- Fix thread-safety in ImageStatusChecker, improve worker lifecycle
- Extract WorkerSignalHandler from main_window.py

---

### v0.6.00 (2025-11-17)
**Major Release: Multi-Host Upload System**

**New Features:**
- Multi-host file upload with 6 provider integrations
- Enhanced authentication (API keys, token login, sessions)
- Adaptive settings panels
- External hooks system with parameter substitution
- ZIP auto-creation for external apps (`%z` parameter)
- `#hostLinks#` placeholder for BBCode templates

**Improvements:**
- 2x faster startup (1.2s vs 3.5s)
- Icon cache optimization
- Table viewport lazy loading
- pycurl Windows DLL bundling
- Thread-safe bandwidth tracking

**Bug Fixes:**
- Fixed emoji rendering in help dialog (Segoe UI Emoji font)
- Fixed dark theme code background (#222222)
- Fixed PyInstaller pycurl bundling (delvewheel DLLs)

---

### v0.5.13 (2025-11-15)
**Partial Multi-Host Implementation**
- ZIP compression support
- Token caching foundation
- File host client architecture
- Gallery loading splash screen status

---

### v0.5.12 (2025-11-14)
**Adaptive UI and Hooks**
- Adaptive Settings Panel
- External Hooks system
- Thread safety improvements
- System enhancements

---

## Technical Specifications

### Dependencies

**Core:**
- Python 3.14+
- PyQt6 6.9.1+
- requests 2.31.0+
- pycurl 7.45.7+
- Pillow 11.3.0+
- cryptography 45.0.5+
- keyring 25.0.0+

**Development:**
- pytest 8.0.0+
- pytest-qt 4.4.0+
- black 24.0.0+ (code formatting)
- mypy 1.8.0+ (type checking)
- pylint 3.0.0+ (linting)

---

### System Requirements

**Minimum:**
- OS: Windows 10 / Linux (Ubuntu 20.04+)
- Python: 3.14
- RAM: 512 MB
- Disk: 100 MB
- Network: Stable internet

**Recommended:**
- OS: Windows 11 / Linux (latest)
- Python: 3.14+
- RAM: 2 GB
- Disk: 500 MB (logs/cache)
- Network: 10+ Mbps upload

---

## Support & Documentation

**User Documentation:**
- [GUI Guide](../guides/gui-guide.md) - Complete GUI walkthrough
- [Multi-Host Upload](../guides/multi-host-upload.md) - File host setup
- [BBCode Templates](../guides/bbcode-templates.md) - Template reference
- [Keyboard Shortcuts](../getting-started/keyboard-shortcuts.md) - All shortcuts
- [Quick Start](../getting-started/quick-start.md) - 5-minute guide
- [Troubleshooting](../troubleshooting/troubleshooting.md) - Common issues

**Developer Documentation:**
- [Architecture](../../architecture/) - System design
- [Testing Guide](../../dev/) - Running tests
- [API Reference](../../dev/) - Internal APIs

**Support:**
- GitHub Issues: Bug reports and feature requests
- GitHub Discussions: Questions and community
- Logs: Help -> View Logs for debugging

---

**Made by the ImXup team**

*Last updated: 2026-01-03 | Version: 0.6.16*
