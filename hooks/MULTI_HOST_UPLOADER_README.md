# Multi-Host File Uploader

A Python-based multi-host file uploader inspired by [PolyUploader](https://github.com/spel987/PolyUploader), supporting **44 different file hosting services** with minimal code.

## 🎯 Why This Exists

Instead of writing separate upload scripts for each file host, this uses a **configuration pattern** where each service is defined by a simple `HostConfig` object. The upload logic is shared across all hosts, making it trivial to add new services.

## 📦 Supported Services (44 Total)

### Anonymous/Free Hosts (No API Key Required)
- **0x0.st** - Simple, temporary file hosting
- **AnonFiles** - Anonymous file uploads
- **BashUpload** - CLI-friendly uploads
- **BayFiles** - Part of AnonFiles family
- **ClicknUpload** - File sharing platform
- **Cockfile** - Anonymous uploads (similar to Uguu)
- **DailyUploads** - File hosting with good speeds
- **Dosya.tc** - Turkish file hosting service
- **FileBin** - Simple file sharing
- **FileBin.ca** - Canadian file hosting
- **FileConvoy** - Quick file transfers
- **FileDitch** - Temporary file hosting
- **File.io** - Self-destructing file sharing
- **Filemail** - Large file transfers
- **FilePost** - File hosting platform
- **FreeImage.host** - Free image hosting
- **KrakenFiles** - Fast file hosting
- **Litterbox (Catbox)** - Temporary file hosting (1h-72h)
- **SendGB** - Large file transfers
- **SendSpace** - Classic file hosting
- **SolidFiles** - Reliable file hosting
- **TempSend** - Temporary file sharing
- **TmpFiles** - Quick temporary uploads
- **Transfer.sh** - CLI-friendly file sharing
- **Uguu.se** - Temporary file hosting
- **Upload.cc** - File hosting service
- **Upload.ee** - Estonian file hosting
- **UploadHaven** - Anonymous uploads
- **UploadRAR** - File hosting platform
- **UsersCloud** - Cloud file storage
- **UsersDrive** - File hosting service
- **WeTransfer** - Popular file transfer service
- **WorkUpload** - File hosting platform
- **Wormhole.app** - Encrypted file transfers
- **ZippyShare** - Fast file hosting

### Optional API Key (Works Better With Auth)
- **GoFile** - Fast uploads, optional account features
- **Pixeldrain** - Works anonymously but limited

### Requires API Key
- **ImgBB** - Image hosting (needs API key)
- **Imgur** - Popular image hosting (needs Client-ID)
- **MediaFire** - Requires session token
- **MEGA.nz** - Cloud storage (needs account)
- **MixDrop** - Video hosting (needs API key)
- **pCloud** - Cloud storage (needs auth token)
- **SiaSky** - Decentralized storage

## 🚀 Quick Start

### Basic Usage
```bash
# Anonymous upload (no API key needed)
python multi_host_uploader.py 0x0 myfile.zip
python multi_host_uploader.py litterbox image.jpg 24h
python multi_host_uploader.py gofile document.pdf

# With API key for enhanced features
python multi_host_uploader.py pixeldrain video.mp4 YOUR_API_KEY
python multi_host_uploader.py imgur screenshot.png YOUR_CLIENT_ID
```

### Integration with imxup

1. **Configure External Apps:**
   ```
   Command: python "C:\path\to\multi_host_uploader.py" gofile "%p"
   ```

2. **Map JSON Fields:**
   - Open "Map JSON Keys..." dialog
   - Run test to see the JSON response
   - Map fields to ext1-4:
     - `url` → ext1 (download link)
     - `file_name` → ext2 (filename)
     - `file_size_mb` → ext3 (size)
     - `host` → ext4 (service name)

3. **Use in Templates:**
   ```
   Download: #ext1#
   File: #ext2# (#ext3#)
   Host: #ext4#
   ```

## 📊 JSON Output Format

All hosts output standardized JSON:
```json
{
  "url": "https://example.com/download/xyz",
  "host": "GoFile",
  "file_name": "test.jpg",
  "file_size": 1234567,
  "file_size_mb": "1.18 MB",
  "status": "success",
  "timestamp": "2024-01-15T10:30:00",
  "raw_response": { /* full API response */ }
}
```

## 🔧 Adding New Hosts

To add a new file hosting service, just add its configuration to `HOSTS` dict:

```python
"newhost": HostConfig(
    name="New Service Name",
    upload_endpoint="https://api.newhost.com/upload",
    method="POST",                    # or "PUT"
    file_field="file",                # form field name
    response_type="json",             # "json", "text", or "regex"
    link_path=["data", "download"],   # JSON path to link
    link_prefix="https://newhost.com/", # Optional prefix
    requires_auth=False               # True if API key needed
)
```

That's it! The upload logic handles everything else automatically.

## 🎨 Advanced Configuration Options

### Response Handling
```python
# JSON path extraction
link_path=["data", "file", "url"]  # Navigate nested JSON

# Regex extraction from text
response_type="text"
link_regex=r'download:\s+(https?://[^\s]+)'

# URL construction
link_prefix="https://example.com/dl/"
link_suffix="/download"
```

### Authentication Types
```python
auth_type="bearer"     # Authorization: Bearer {token}
auth_type="basic"      # Authorization: Basic {base64}
auth_type=None         # No authentication
```

### Extra Form Fields
```python
extra_fields={
    "expires": "1w",
    "password": "optional"
}
```

## 📝 Examples

### Litterbox with Custom Expiry
```bash
python multi_host_uploader.py litterbox file.zip 72h
# Options: 1h, 12h, 24h, 72h
```

### GoFile with Account
```bash
# Get API key from https://gofile.io/myProfile
python multi_host_uploader.py gofile file.pdf YOUR_API_KEY
```

### Pixeldrain with Auth
```bash
# Get API key from https://pixeldrain.com/user/api_keys
python multi_host_uploader.py pixeldrain video.mp4 YOUR_API_KEY
```

## 🔍 Testing

View all available hosts and their configuration:
```bash
python test_multi_host.py
```

Test a specific host:
```bash
python multi_host_uploader.py 0x0 test.txt
```

## 💡 Why This Pattern Works

**Traditional Approach (Bad):**
- 44 separate scripts
- 44 × 100 lines = 4,400 lines of code
- Duplicated error handling, HTTP logic, etc.

**Configuration Pattern (Good):**
- 1 upload engine
- 44 × 15 lines = 660 lines of config
- Shared logic, consistent behavior
- Easy to maintain and extend

## 🛠️ Requirements

```bash
pip install requests
```

That's it! No complex dependencies.

## 📚 Comparison with PolyUploader

| Feature | PolyUploader (JS) | This (Python) |
|---------|------------------|---------------|
| Hosts | ~30 | 44 |
| Language | JavaScript/Rust | Python |
| Use Case | Tauri Desktop App | CLI/imxup Integration |
| Pattern | Configuration Objects | HostConfig Classes |

Both use the same elegant abstraction pattern!

## ⚠️ Important Notes

1. **API Availability**: Some hosts may change their APIs or go offline. The configuration pattern makes it easy to update or remove hosts.

2. **Rate Limits**: Many free hosts have rate limits. Using API keys (where available) typically increases limits.

3. **File Size Limits**: Each host has different size limits. Check their documentation for specifics.

4. **Temporary vs Permanent**:
   - Temporary: 0x0, Litterbox, File.io, TmpFiles
   - Permanent-ish: GoFile, Pixeldrain, MediaFire, MEGA

5. **Terms of Service**: Always check and comply with each host's TOS before using.

## 🤝 Contributing

To add a new host:
1. Find the host's upload API documentation
2. Add a `HostConfig` entry to the `HOSTS` dict
3. Test the upload
4. Submit a PR with the configuration

## 📄 License

This is a demonstration/educational project inspired by PolyUploader. Use at your own risk and respect each file host's terms of service.

## 🙏 Credits

Inspired by [PolyUploader](https://github.com/spel987/PolyUploader) by spel987, which pioneered this elegant configuration-based approach to multi-host uploading.