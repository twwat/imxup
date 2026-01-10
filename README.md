# ImXup - Multi-Host Gallery Uploader

![Version](https://img.shields.io/badge/version-0.7.2-blue.svg)
![Python](https://img.shields.io/badge/python-3.14+-green.svg)
![License](https://img.shields.io/badge/license-MIT-orange.svg)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20Mac-lightgrey.svg)

A modern desktop application for uploading galleries to image host imx.to and multiple file hosts, generating BBCode to post on forums, monitoring online availability of uploads and more.

Drag-and-drop support, queue management, batch operations, and comprehensive BBCode template support.

---

## Overview

**ImXup** is a professional-grade gallery uploader that streamlines the process of uploading, managing, and sharing image collections. Originally designed for imx.to, it has evolved into a comprehensive multi-host upload solution supporting 6 major file hosting providers with advanced authentication, token management, and automated workflows.

- **Multi-Host Support**: Upload to 7 different services (IMX.to + 6 file hosts)
- **Cross-Platform**: Windows, Mac, Linux (or run using Python)
- **Intelligent Queue Management**: Batch operations, priority scheduling, and status tracking
- **Advanced BBCode Templates**: Create custom templates with dynamic placeholders and conditional logic 
- **Professional GUI**: Modern PyQt6 interface with dark/light themes, keyboard shortcuts, drag-and-drop, etc.
- **Robust Error Handling**: Automatic retries, duplicate detection, fallback methods, comprehensive logging system

---

## Key Features

### Core Imx.to Upload Capabilities
- **Drag & Drop Interface**: Simply drag folders into the GUI to queue uploads
- **Batch Processing**: Efficient batch operations 
- **Concurrent Uploads**: Upload multiple files to multiple hosts simultaneously with parallel workers
- **Progress Tracking**: Real-time progress bars for individual files and overall completion
- **Smart Resume**: Automatically resume interrupted uploads
- **Duplicate Detection**: Intelligent detection of previously uploaded galleries


### Advanced Features
- **BBCode Template System**: Create multiple custom templates with 18 dynamic placeholders, conditional logic, switch on-the-fly
- **Archive Management**: Automatic ZIP extraction and compression support
- **Credential Management**: Secure storage using system keyring
- **Hook System**: External script integration for custom workflows
- **Bandwidth Tracking**: Monitor upload/download speeds and usage
- **Custom Tabs**: Use tab system to help organize uploads according to your workflow
- **Monitor Online Status**: Monitor online status/availability of uploaded files
- **Adaptive Settings**: Context-aware settings panels that adapt to your workflow
- **Comprehensive Logging**: Detailed logs with filtering and export capabilities

### Professional GUI
- **Modern Interface**: Sleek PyQt6 design with Material-inspired icons
- **Dark/Light Themes**: Automatic theme switching with custom styling
- **System Tray Integration**: Minimize to tray for background operation
- **Single Instance Mode**: Command-line invocations add to existing GUI
- **Keyboard Shortcuts**: Extensive keyboard navigation support
- **Responsive Design**: Adaptive layouts for different screen sizes

---

## Supported File Hosts

| Host | Authentication | Max File Size | Storage | Features |
|------|---------------|---------------|---------|----------|
| **IMX.to** | API / Session | Unlimited | Unlimited | Gallery/thumbnail hosting, online status checking |
| **FileBoom** | API | 10 GiB | 20 TiB\* | Multi-step, deduplication |
| **Filedot** | Session | Varies | 10 TiB | CAPTCHA handling, CSRF protection, storage monitoring |
| **Filespace** | Cookie | Varies | 50+ GiB (varies)) | Simple cookie-based auth, storage monitoring |
| **Keep2Share** | API | 10 GiB | 20 TiB\* | Multi-step, deduplication |
| **Rapidgator** | API / Token | 5 GiB | 4+ TiB (varies) | MD5 verification, polling, storage monitoring |
| **TezFiles** | API | Varies | 20 TiB\* | Multi-step, deduplication |

*All hosts support automatic retry, connection pooling, and token caching*
\* 20 TiB combined storage is shared between all 3 hosts (FileBoom, Keep2Share, TezFiles)

## Security

| Feature | Implementation |
|---------|---------------|
| **Credential Storage** | OS Keyring (Windows Credential Manager / macOS Keychain / Linux Secret Service) with Fernet AES-128-CBC fallback |
| **Password Hashing** | PBKDF2-HMAC-SHA256 (100,000 iterations) with cryptographic salt |
| **Transport Security** | TLS 1.2+ with SSL certificate verification via certifi CA bundle |
| **Token Management** | Encrypted token caching with configurable TTL and automatic refresh |
| **Database Security** | Parameterized SQL queries, SQLite WAL mode |
| **Thread Safety** | 60+ threading locks protecting shared state |
| **Timing Attack Prevention** | Constant-time password comparison via `secrets.compare_digest()` |
| **Input Validation** | Path normalization, SQL wildcard escaping, column whitelist validation |

---

## Quick Installation

1. Go to the [Releases](https://github.com/twwat/imxup/releases) page
2. Download the latest version for your operating system (portable version recommended)
3. Extract and run xecutable (imxup)

Alternatively, you can run using Python 3.14 or build your own executables from source.

## Python Installation

### Prerequisites

- **Python 3.14+** (required)
- **Windows/Linux/Mac** operating system
- **Internet connection** for uploads

```bash
# Clone the repository
git clone https://github.com/twwat/imxup.git
cd imxup

# Install dependencies
pip install -r requirements.txt

# Launch GUI
python imxup.py --gui
```

### Development Setup


```bash
# Clone the repository
git clone https://github.com/twwat/imxup.git
cd imxup

# Create virtual environment
python -m venv venv

# Activate virtual environment (Linux/Mac)
source venv/bin/activate

# Activate virtual environment (Windows)
./venv/scripts/activate

# Install dependencies
pip install -r requirements.txt

# Install development dependencies
pip install -r requirements-dev.txt

# Run tests
pytest tests/
```

---

## Quick Start

### GUI Mode (Recommended)

```bash
# Launch the GUI
python imxup.py --gui

# Add a folder via command line to existing GUI
python imxup.py --gui "/path/to/gallery/folder"

# Start with specific template
python imxup.py --gui --template "Detailed Example"
```

#### Basic Workflow:
1. **Launch** the GUI with `python imxup.py --gui`
2. **Drag folders** into the upload queue area
3. **Configure** settings (BBCode template, file hosts, etc.)
4. **Click "Start All"** to begin uploading
5. **View results** in the BBCode viewer when complete

### Command-Line Mode

```bash
# Upload a single gallery
python imxup.py /path/to/images

# With custom name and template
python imxup.py /path/to/images --name "Vacation 2025" --template "Forum Post"

# Show help
python imxup.py --help
```

### Windows Context Menu

```bash
# Install right-click integration
python imxup.py --install-context-menu

# Now you can:
# 1. Right-click any folder
# 2. Select "Upload to imx.to (GUI)"
# 3. Folder is automatically added to queue
```

---

## BBCode Templates

### What are BBCode Templates?

Templates allow you to customize the BBCode output format with dynamic placeholders that are automatically replaced with gallery information.

### Available Placeholders (18 Total)

| Placeholder | Description | Example |
|------------|-------------|---------|
| `#folderName#` | Gallery name | `Summer Vacation 2025` |
| `#width#` | Average width | `1920` |
| `#height#` | Average height | `1080` |
| `#longest#` | Longest dimension | `1920` |
| `#extension#` | Common format | `JPG` |
| `#pictureCount#` | Number of images | `42` |
| `#folderSize#` | Total size | `52.9 MB` |
| `#galleryLink#` | imx.to gallery URL | `https://imx.to/g/abc123` |
| `#allImages#` | BBCode for all images | `[img]...[/img]` |
| `#hostLinks#` | File host download links | `[url]...[/url]` |
| `#custom1#` | User-defined field 1 | Custom data |
| `#custom2#` | User-defined field 2 | Custom data |
| `#custom3#` | User-defined field 3 | Custom data |
| `#custom4#` | User-defined field 4 | Custom data |
| `#ext1#` | External link 1 | Custom data from hooks |
| `#ext2#` | External link 2 | Custom data from hooks |
| `#ext3#` | External link 3 | Custom data from hooks |
| `#ext4#` | External link 4 | Custom data from hooks |

### Example Template

```
📸 Gallery: #folderName#
📊 Images: #pictureCount# (#extension# format)
💾 Size: #folderSize#
📐 Dimensions: #width#x#height# (longest: #longest#)
🔗 Gallery Link: #galleryLink#

#allImages#
```

### Creating Custom Templates

1. Open **Settings → BBCode Template**
2. Click **Manage BBCode Templates**
3. Click **New Template**
4. Name your template (e.g., "Forum Post")
5. Use the placeholder buttons to insert dynamic values
6. Save and select from the dropdown

Templates are stored in `~/.imxup/*.template.txt` (unless you changed the central storage path from the default location)

---

## Configuration

### File Host Setup

1. Open **Settings → File Hosts** tab
2. Check the hosts you want to enable
3. Click **Configure** for each host
4. Enter credentials:
   - **API Key**: Paste your permanent token (Fileboom, Keep2Share)
   - **Username/Password**: Session-based login (Filedot, Rapidgator, etc.)
5. Click **Test Connection** to verify
6. Click **Save**

### Advanced Settings

- **Thumbnail Settings**: Configure size and compression
- **Visibility**: Set galleries as public/private
- **Retry Logic**: Adjust max retry attempts (default: 3)
- **Parallel Uploads**: Control simultaneous upload workers
- **Archive Handling**: Auto-extract ZIP files before upload

---

## Documentation

_**Note**: Documentation isn't fully up to date (work in progress)_

Comprehensive documentation is available in the `docs/` directory:

### User Documentation
- **[GUI Guide](docs/user/gui-guide.md)** - Complete GUI interface walkthrough
- **[Multi-Host Upload](docs/user/multi-host-upload.md)** - File host configuration guide
- **[BBCode Templates](docs/user/bbcode-templates.md)** - Template creation reference
- **[Keyboard Shortcuts](docs/user/keyboard-shortcuts.md)** - All keyboard shortcuts
- **[Quick Start Guide](docs/user/quick-start.md)** - Get started in 5 minutes
- **[Troubleshooting](docs/user/troubleshooting.md)** - Common issues and solutions

### Developer Documentation
- **[Architecture](docs/architecture/)** - System design and component overview _(incomplete)_
- **[Testing Guide](docs/dev/)** - Running and writing tests _(incomplete)_
- **[API Reference](docs/dev/)** - Internal API documentation _(incomplete)_

---

## System Requirements

### Minimum Requirements
- **OS**: Windows 10+ or Linux (Ubuntu 20.04+, Fedora 35+), MacOS (15 Sequoia)
- **Python**: 3.14 or higher
- **RAM**: 512 MB
- **Disk**: 100 MB free space
- **Network**: Semi-stable internet connection faster than dial-up

### Recommended
- **OS**: Windows 10/11, Linux (latest), MacOS (latest)
- **Python**: 3.14+
- **RAM**: 2 GB
- **Disk**: 500 MB (for logs and cache)
- **Network**: High-speed broadband (10+ Mbps upload)

### Dependencies

Core libraries:
- **PyQt6** (6.9.1) - GUI framework
- **requests** (2.31.0) - HTTP client
- **pycurl** (7.45.7) - High-performance uploads
- **Pillow** (11.3.0) - Image processing
- **cryptography** (45.0.5) - Secure credential storage
- **keyring** (25.0.0+) - System keyring integration

See `requirements.txt` for complete list.

---

## Development

### Project Structure

```
imxup/
├── src/
│   ├── core/           # Core upload engine
│   ├── gui/            # PyQt6 GUI components
│   ├── network/        # HTTP clients and file host handlers
│   ├── processing/     # Workers, coordinators, tasks
│   ├── storage/        # Database and queue management
│   └── utils/          # Utilities and helpers
├── assets/             # Icons, logos, stylesheets
├── docs/               # Documentation
├── tests/              # Test suite
├── hooks/              # External hook scripts
└── imxup.py           # Main entry point
```

### Running Tests

```bash
# Run all tests
pytest tests/

# Run with coverage
pytest --cov=src tests/

# Run specific test file
pytest tests/test_upload.py

# Run with verbose output
pytest -v tests/
```

### Manual build with PyInstaller
```bash
pyinstaller imxup.spec
```

### Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

See `CONTRIBUTING.md` for detailed guidelines.

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## Support

### Getting Help

- **Documentation**: Check the `docs/` directory
- **Issues**: [GitHub Issues](https://github.com/twwat/imxup/issues)
- **[Troubleshooting Guide](docs/user/troubleshooting.md)**
- **Discussions**: [GitHub Discussions](https://github.com/twwat/imxup/discussions)

For more issues, see **[Troubleshooting Guide](docs/user/troubleshooting.md)**

### Bug Reports

When reporting bugs, please include:
1. ImXup version (`Help → About`)
2. Operating system and version
3. Steps to reproduce
4. Error messages (check logs: `Help → View Logs`)
5. Screenshots if applicable

### Feature Requests

Have an idea? Open a feature request on GitHub Issues with:
- Clear description of the feature
- Use case and benefits
- Proposed implementation (optional)

---

See **[CHANGELOG.md](CHANGELOG.md)** for complete version history.

---

## Acknowledgments

- **[IMX.to](https://imx.to/)** - Primary image hosting service
- **PyQt6** - Excellent GUI framework
- **Contributors** - Everyone who has contributed code, bug reports, and ideas

---

## Project Status

**Active Development** - ImXup is actively maintained and receives regular updates. The latest stable version is v0.7.1.

---

**Made with ❤️ by the ImXup team**

[⬆ Back to top](#imxup---multi-host-gallery-uploader)
