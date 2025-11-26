# Multi-Host Upload Guide

## Quick Reference

**Version:** v0.6.00
**Feature:** Upload galleries to 6 different file hosting services
**Supported Hosts:** Fileboom, Filedot, Filespace, Keep2Share, Rapidgator, Tezfiles
**Authentication:** Username/password, API keys, session cookies
**Token Management:** Automatic caching with TTL (Time To Live)

---

## What is Multi-Host Upload?

Multi-host upload allows you to upload your image galleries to multiple file hosting services simultaneously. This provides:

- **Redundancy:** If one host goes down, your content remains accessible on others
- **Geographic distribution:** Different hosts may perform better in different regions
- **Monetization options:** Some hosts offer rewards for downloads
- **Flexibility:** Choose the best host for your specific needs

---

## Supported File Hosts

### 1. **Fileboom** (fboom.me)
- **Authentication:** API Key (permanent token)
- **Max File Size:** 10 GB
- **Storage:** 10 TB (premium accounts)
- **Connections:** Up to 2 simultaneous uploads
- **Features:** Multi-step upload, file deduplication, automatic retry

### 2. **Filedot** (filedot.to)
- **Authentication:** Session-based (username/password)
- **Session Management:** Automatic token refresh with visual CAPTCHA solving
- **Features:** Session persistence, CSRF protection

### 3. **Filespace** (filespace.com)
- **Authentication:** Session-based (username/password)
- **Session Cookie:** Uses `xfss` cookie for authentication
- **Features:** Cookie-based sessions, automatic retry

### 4. **Keep2Share** (k2s.cc)
- **Authentication:** API Key (permanent token)
- **Max File Size:** 10 GB
- **Storage:** 10 TB (premium accounts)
- **Connections:** Up to 2 simultaneous uploads
- **Features:** Same API structure as Fileboom

### 5. **Rapidgator** (rapidgator.net)
- **Authentication:** Token login (username/password → temporary token)
- **Token TTL:** 24 hours (86,400 seconds)
- **Max File Size:** 5 GB
- **Features:** Multi-step upload with MD5 hash verification, polling for completion
- **Upload Flow:** Init → Upload → Poll status

### 6. **Tezfiles** (tezfiles.com)
- **Authentication:** Session-based (username/password)
- **Features:** Session cookies, automatic token extraction

---

## Authentication Methods

### Method 1: API Key (Permanent Token)
**Used by:** Fileboom, Keep2Share

**Setup Steps:**
1. Log into your file host account
2. Navigate to API settings (usually under Account → API)
3. Generate or copy your API key
4. In imxup, go to **Settings → File Hosts**
5. Select the host and click **Configure**
6. Paste your API key in the credentials field
7. Click **Test Connection** to verify

**Advantages:**
- No login required per session
- Permanent (doesn't expire)
- Simple setup

**Security Note:** Store API keys securely. Anyone with your API key can upload to your account.

---

### Method 2: Token Login (Username/Password → Temporary Token)
**Used by:** Rapidgator

**Setup Steps:**
1. In imxup, go to **Settings → File Hosts**
2. Select Rapidgator and click **Configure**
3. Enter credentials in format: `username:password`
4. Click **Test Connection**

**How it works:**
1. imxup logs in using your credentials
2. Receives a temporary authentication token (valid 24 hours)
3. Caches the token for reuse
4. Automatically refreshes when expired

**Token Caching:**
- Tokens are stored in `.imxup/token_cache.db`
- TTL (Time To Live): 24 hours for Rapidgator
- Automatic refresh on expiration
- No need to re-login for each upload

---

### Method 3: Session-Based (Username/Password → Cookies)
**Used by:** Filedot, Filespace, Tezfiles

**Setup Steps:**
1. In imxup, go to **Settings → File Hosts**
2. Select the host and click **Configure**
3. Enter credentials in format: `username:password`
4. Click **Test Connection**

**How it works:**
1. imxup visits the login page (GET request)
2. Extracts CSRF tokens and hidden fields
3. Solves any CAPTCHAs automatically (if configured)
4. Submits login form (POST request)
5. Stores session cookies for future requests

**Session Features:**
- **Cookie Persistence:** Cookies are reused across uploads
- **CAPTCHA Solving:** Visual CAPTCHAs solved using CSS position parsing
- **Token Extraction:** Session IDs extracted from upload page HTML
- **Automatic Refresh:** Expired sessions are re-authenticated

**Example: Filedot CAPTCHA Solving**
```
HTML: <span style="padding-left:26px">2</span><span style="padding-left:45px">8</span>
Parsed: Position 26→'2', Position 45→'8'
Result: "28" (sorted by CSS padding-left position)
```

---

## Setting Up File Hosts

### Step 1: Enable a File Host

1. Open **Settings** (Ctrl+Comma or File → Settings)
2. Navigate to **File Hosts** tab
3. Find your desired host in the list
4. Check the **Enable** checkbox
5. Click **Configure** to enter credentials

### Step 2: Configure Credentials

**For API Key hosts (Fileboom, Keep2Share):**
```
API Key: your-api-key-here
```

**For Login-based hosts (All others):**
```
Username: your-username
Password: your-password
Format: username:password
```

### Step 3: Test Connection

1. Click **Test Connection** button
2. Wait for verification (5-10 seconds)
3. Check results:
   - ✅ **Success:** Credentials validated, user info retrieved
   - ❌ **Failed:** Check credentials, network connection, or account status

**What Test Connection Does:**
- Validates credentials
- Checks authentication
- Retrieves account information (storage, premium status)
- Tests file upload with tiny dummy file
- Automatically deletes test file (if supported)

### Step 4: Adjust Settings (Optional)

**Max Connections:**
- Default: 2 simultaneous uploads
- Higher values = faster uploads but more bandwidth
- Recommended: 2-3 for stable connections

**Auto Retry:**
- Enabled by default
- Automatically retries failed uploads (up to 3 times)
- Handles transient network errors

---

## Token Management

### Token Cache

**Location:** `.imxup/token_cache.db` (SQLite database)

**What's Stored:**
- Host identifier
- Authentication token
- Token expiration timestamp
- Session cookies (for session-based auth)

**Security:**
- Database permissions: User-only read/write
- Tokens encrypted in memory
- Automatic cleanup of expired tokens

### Token Lifecycle

**Token Login (Rapidgator):**
```
1. Login: username:password → token
2. Cache: Store token with 24h TTL
3. Reuse: Use cached token for uploads
4. Refresh: Auto-refresh when TTL < 5% remaining
5. Retry: On 401/403 errors, refresh and retry
```

**Session-based (Filedot, Filespace, Tezfiles):**
```
1. Login: GET login page → extract CSRF tokens
2. Submit: POST credentials → receive session cookies
3. Extract: Visit upload page → extract session ID from HTML
4. Cache: Store cookies + session ID + timestamp
5. Reuse: Use same cookies for all uploads in session
6. Refresh: If "Anti-CSRF check failed" → refresh session
```

**API Key (Fileboom, Keep2Share):**
```
1. Set: Paste API key once
2. Use: API key sent with every request
3. No expiration, no refresh needed
```

### Stale Token Detection

**Proactive (TTL-based):**
- Check token age before each operation
- Refresh if TTL expired
- Prevents upload failures

**Reactive (Error-based):**
- Detect HTTP 401/403 status codes
- Match error patterns: "Anti-CSRF check failed", "session expired"
- Automatically refresh and retry once

**Example Error Patterns:**
```
HTTP 401: Unauthorized
HTTP 403: Forbidden
"Anti-CSRF check failed" (Filedot)
"Session expired" (generic)
```

---

## Uploading to File Hosts

### Step 1: Prepare Your Gallery

1. Add images to a gallery (drag & drop or File → Add Gallery)
2. Optionally rename images (if needed for sorting)
3. Select archive format: ZIP or None
4. Choose BBCode template for output

### Step 2: Select File Hosts

1. In the gallery table, find your gallery row
2. Click the **File Hosts** column (shows icons of enabled hosts)
3. Check which hosts you want to upload to
4. Each host will appear as a separate upload task

### Step 3: Start Upload

**Option A: Upload Single Gallery**
1. Right-click gallery → **Upload to File Hosts**
2. Select hosts in dialog
3. Click **Start Upload**

**Option B: Upload Multiple Galleries**
1. Select multiple galleries (Ctrl+Click or Shift+Click)
2. Right-click → **Batch Upload to File Hosts**
3. Choose hosts and settings
4. Click **Start All**

### Step 4: Monitor Progress

**Upload Status Column:**
- 🔄 **Uploading:** Transfer in progress (shows %)
- ✅ **Complete:** Upload successful
- ❌ **Failed:** Upload error (click for details)
- ⏸️ **Paused:** Upload paused (can resume)
- 🔁 **Retrying:** Auto-retry in progress (X/3 attempts)

**Progress Details:**
- Hover over status to see tooltip with details
- Click status icon to view full upload log
- Bandwidth usage shown in status bar

---

## Multi-Step Upload Process

Some hosts (Rapidgator, Fileboom, Keep2Share) use multi-step uploads for better reliability:

### Step 1: Initialize Upload
```
Request: POST /api/v2/getUploadFormData
Payload: {access_token, parent_id}
Response: {upload_url, upload_id, form_data}
```

**Purpose:**
- Get dedicated upload server
- Receive dynamic form fields
- Check for file deduplication

**File Deduplication:**
If file already exists on server:
```
Response: {state: 2, file: {url: "existing-file-url"}}
Result: Skip upload, return existing URL
```

### Step 2: Upload File
```
Request: POST <upload_url from step 1>
Payload: multipart/form-data with file + form_data
Response: {status: "success"}
```

**Features:**
- Progress callbacks for bandwidth tracking
- Cancellation support (via should_stop callback)
- MD5 hash verification (Rapidgator only)

### Step 3: Poll for Completion (Rapidgator only)
```
Request: GET /api/v2/file/upload_info?upload_id=xxx&token=xxx
Response: {upload: {state: 2, file: {url: "final-url"}}}
```

**Polling Settings:**
- Delay: 1 second between polls
- Retries: Up to 10 attempts
- Timeout: 10 seconds total

---

## Troubleshooting Upload Issues

### Error: "Login failed with status 401"

**Cause:** Invalid credentials or expired session

**Solutions:**
1. Verify username/password are correct
2. Check if account is active (not suspended/expired)
3. Try logging in on the host's website manually
4. Clear token cache: Delete `.imxup/token_cache.db`
5. Re-configure credentials in Settings → File Hosts

---

### Error: "Anti-CSRF check failed"

**Cause:** Stale session token (session-based hosts)

**Solutions:**
1. Automatic: imxup will auto-refresh session and retry
2. Manual: Click **Test Connection** to force re-login
3. Check session timeout settings in host config

---

### Error: "Upload init failed (HTTP 403)"

**Cause:** Insufficient permissions or storage quota exceeded

**Solutions:**
1. Check account storage: Settings → File Hosts → **View User Info**
2. Upgrade to premium account if free tier exceeded
3. Delete old files to free up space
4. Verify API key has upload permissions

---

### Error: "Upload processing timeout"

**Cause:** Server took too long to process file (Rapidgator polling)

**Solutions:**
1. File may still be uploading - check host website
2. Increase poll retries in host config
3. Retry upload manually
4. Use smaller files (split large archives)

---

### Error: "Failed to extract session ID from upload page"

**Cause:** HTML structure changed or regex mismatch

**Solutions:**
1. Check if host website updated (may need config update)
2. Report issue on GitHub with full error log
3. Use alternative authentication method if available

---

### Upload Stuck at 0%

**Cause:** Network connection issue or server timeout

**Solutions:**
1. Check internet connection
2. Disable firewall/antivirus temporarily
3. Try different upload server (if host supports)
4. Reduce max_connections to 1 in host settings
5. Check logs: View → Logs → Filter by host name

---

### Slow Upload Speed

**Cause:** Bandwidth throttling, server limits, or network congestion

**Solutions:**
1. Check your internet upload speed (speedtest.net)
2. Close other upload-heavy applications
3. Increase max_connections (2 → 3) for parallel uploads
4. Try uploading during off-peak hours
5. Use compression: ZIP with deflate (slower) vs STORE (faster but larger)

---

## Advanced Features

### Bandwidth Tracking

**Location:** Status bar (bottom right)

**Display:**
```
Upload: 2.5 MB/s ↑  |  Downloaded: 1.2 GB
```

**Features:**
- Real-time upload speed
- Total bytes uploaded this session
- Per-host bandwidth breakdown (in logs)

**Atomic Counter:**
- Thread-safe bandwidth aggregation
- Accurate even with multiple simultaneous uploads

---

### Session Persistence

**Worker-Level Caching:**
Each upload worker caches session state:
```python
{
  'cookies': {'PHPSESSID': 'abc123', 'xfss': 'xyz789'},
  'token': 'session-token-here',
  'timestamp': 1699564800.0
}
```

**Benefits:**
- No re-login between files in same gallery
- Faster uploads (skip authentication overhead)
- Reduced server load

**Session Reuse:**
```
Upload 1: Login → Extract token → Upload file
Upload 2: Reuse token → Upload file (no login!)
Upload 3: Reuse token → Upload file
... (continues until session expires)
```

---

### Automatic Retry Logic

**Retry Conditions:**
1. Network errors (connection reset, timeout)
2. HTTP 5xx errors (server errors)
3. Transient failures (temporary unavailable)

**Retry Strategy:**
```
Attempt 1: Immediate retry
Attempt 2: Wait 5 seconds → retry
Attempt 3: Wait 10 seconds → final retry
Failure: Mark upload as failed
```

**Non-Retryable Errors:**
- HTTP 401/403 (triggers token refresh instead)
- HTTP 404 (endpoint not found)
- File too large (exceeds host limit)
- Invalid credentials (user must fix)

---

### Clean Filename Handling

**Internal Prefix Removal:**

Local temp files use unique prefixes:
```
Local: imxup_1555_My_Gallery.zip
```

**External Upload (sent to host):**
```
Uploaded as: My_Gallery.zip
```

**Purpose:**
- Prevent temp file collisions on disk
- Send clean names to file hosts
- Preserve original gallery name for sharing

---

## File Host Configuration Files

**Location:** `assets/hosts/*.json`

**Structure:**
```json
{
  "name": "HostName",
  "icon": "host-icon.png",
  "requires_auth": true,
  "auth_type": "api_key | token_login | session",

  "upload": {
    "endpoint": "https://...",
    "method": "POST",
    "file_field": "file"
  },

  "response": {
    "type": "json | text | redirect",
    "link_path": ["path", "to", "url"]
  }
}
```

**Customization:**
- Add new hosts by creating JSON config
- Adjust timeouts, retries, TTL values
- Configure custom regex patterns
- See existing configs for examples

---

## Best Practices

### 1. Test Before Batch Upload
- Always test credentials with **Test Connection**
- Upload a single small gallery first
- Verify download links work

### 2. Monitor Storage Quota
- Check user info regularly: Settings → File Hosts → **View User Info**
- Set up multiple hosts to distribute storage
- Delete old/unused files to free space

### 3. Use Appropriate Compression
- **ZIP STORE:** Faster upload, larger files (images already compressed)
- **ZIP DEFLATE:** Slower upload, smaller files (use for text/docs)

### 4. Backup Your API Keys
- Store API keys securely (password manager)
- Generate new keys if compromised
- Don't share keys publicly

### 5. Respect Rate Limits
- Don't exceed max_connections settings
- Space out large batch uploads
- Monitor for "Too Many Requests" errors

---

## Getting More Help

**Log Viewer:**
- View → Logs
- Filter by host name to see upload details
- Copy logs when reporting issues

**Error Reports:**
- Include full error message
- Attach relevant log entries
- Mention host name and account type (free/premium)

**GitHub Issues:**
https://github.com/[your-repo]/issues

**Documentation:**
- `docs/QUICK_START_GUI.md` - General GUI guide
- `docs/GUI_IMPROVEMENTS.md` - Latest features
- `docs/KEYBOARD_SHORTCUTS.md` - Keyboard shortcuts

---

## Frequently Asked Questions

**Q: Can I upload to multiple hosts simultaneously?**
A: Yes! Enable multiple hosts and they'll upload in parallel (up to max_connections each).

**Q: What happens if upload fails midway?**
A: imxup auto-retries up to 3 times. If all fail, you can manually retry from the gallery table.

**Q: Do I need premium accounts?**
A: Free accounts work but have limitations (file size, storage, speed). Premium recommended for regular use.

**Q: How long are tokens cached?**
A: Depends on host: 24 hours (Rapidgator), session-based (until logout), permanent (API keys).

**Q: Can I use cookie authentication instead?**
A: Yes for session-based hosts. Export cookies from browser and configure in settings.

**Q: What file formats are supported?**
A: Any format, but typically ZIP archives of image galleries. Max size depends on host (5-10 GB).

**Q: How do I delete files from hosts?**
A: Some hosts support deletion via API (Fileboom, Keep2Share, Rapidgator). Use host's website for others.

**Q: Why is upload speed slower than my internet speed?**
A: Host server limits, encryption overhead, compression, or multiple simultaneous uploads sharing bandwidth.

---

## Technical Details (For Advanced Users)

### Authentication Flow Internals

**Token Login (Rapidgator):**
1. Build login URL with username/password params
2. GET request to `/api/v2/user/login`
3. Parse JSON response: `response.token`
4. Store in SQLite cache with 86400s TTL
5. Include in all future requests: `?token=xxx`

**Session-based (Filedot):**
1. GET login page → extract CSRF tokens, hidden fields
2. Solve CAPTCHA: Parse `<span>` positions using regex
3. POST login form with all hidden fields + credentials + CAPTCHA
4. Extract cookies from `Set-Cookie` headers
5. GET upload page with cookies → extract session ID from HTML
6. Include cookies in all requests: `Cookie: PHPSESSID=xxx; xfss=yyy`

**API Key (Fileboom):**
1. Use key directly in POST body: `{access_token: "key"}`
2. No login step required
3. No caching needed (key is permanent)

### Upload Protocol Details

**Standard Upload (Tezfiles, Filespace):**
```
POST /upload.cgi
Content-Type: multipart/form-data
Cookie: PHPSESSID=xxx; xfss=yyy

--boundary
Content-Disposition: form-data; name="file"; filename="gallery.zip"
Content-Type: application/zip

[binary file data]
--boundary
Content-Disposition: form-data; name="sess_id"

session-token-here
--boundary--
```

**Multi-Step Upload (Rapidgator):**
```
Step 1 - Init:
GET /api/v2/file/upload?name=gallery.zip&hash=abc123&size=12345&token=xxx
Response: {upload_url: "https://upXX.rapidgator.net/upload", upload_id: "12345"}

Step 2 - Upload:
POST https://upXX.rapidgator.net/upload
[multipart file data]

Step 3 - Poll:
GET /api/v2/file/upload_info?upload_id=12345&token=xxx
Poll until: response.upload.state == 2
Final URL: response.upload.file.url
```

### Progress Callback Implementation

**pycurl XFERINFO:**
```python
def _xferinfo_callback(download_total, downloaded, upload_total, uploaded):
    bytes_since_last = uploaded - self.last_uploaded
    if bytes_since_last > 0:
        self.bandwidth_counter.add(bytes_since_last)  # Atomic increment
        self.last_uploaded = uploaded

    if self.should_stop_func and self.should_stop_func():
        return 1  # Abort transfer

    if self.on_progress_func and upload_total > 0:
        self.on_progress_func(uploaded, upload_total)  # Update GUI

    return 0  # Continue
```

**Bandwidth Counter (Thread-Safe):**
```python
class AtomicCounter:
    def __init__(self):
        self._value = 0
        self._lock = threading.Lock()

    def add(self, amount: int):
        with self._lock:
            self._value += amount

    def get(self) -> int:
        with self._lock:
            return self._value
```

---

**End of Multi-Host Upload Guide**
