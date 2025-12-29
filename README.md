# ImXup - Multi-Host Gallery Uploader

![Version](https://img.shields.io/badge/version-0.6.15-blue.svg)
![Python](https://img.shields.io/badge/python-3.14+-green.svg)
![License](https://img.shields.io/badge/license-MIT-orange.svg)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux-lightgrey.svg)

A powerful PyQt6-based desktop application for uploading image galleries to imx.to and multiple file hosting services with advanced features including drag-and-drop, queue management, batch operations, and comprehensive BBCode template support.

---

## Overview

**ImXup** is a professional-grade gallery uploader that streamlines the process of uploading, managing, and sharing image collections. Originally designed for imx.to, it has evolved into a comprehensive multi-host upload solution supporting 6 major file hosting providers with advanced authentication, token management, and automated workflows.

### Why ImXup?

- **Multi-Host Support**: Upload to 7 different services (imx.to + 6 file hosts)
- **Intelligent Queue Management**: Batch operations, priority scheduling, and status tracking
- **Advanced BBCode Templates**: Customizable templates with 18 dynamic placeholders
- **Production-Ready GUI**: Modern PyQt6 interface with dark/light themes
- **Robust Error Handling**: Automatic retries, duplicate detection, and comprehensive logging
- **Windows Integration**: Context menu support, system tray, single-instance mode

---

## Key Features

### Core Upload Capabilities
- **Drag & Drop Interface**: Simply drag folders into the GUI to queue uploads
- **Batch Processing**: Upload multiple galleries simultaneously with parallel workers
- **Progress Tracking**: Real-time progress bars for individual files and overall completion
- **Smart Resume**: Automatically resume interrupted uploads
- **Duplicate Detection**: Intelligent detection of previously uploaded galleries

### Multi-Host File Upload (v0.6.00)
Upload galleries to 6 premium file hosting services:
- **Fileboom** (fboom.me) - API key authentication, 10GB files, 10TB storage
- **Filedot** (filedot.to) - Session-based with CAPTCHA handling
- **Filespace** (filespace.com) - Cookie-based sessions
- **Keep2Share** (k2s.cc) - API key authentication, same features as Fileboom
- **Rapidgator** (rapidgator.net) - Token login, 5GB files, MD5 verification
- **Tezfiles** (tezfiles.com) - Session-based authentication

### Advanced Features
- **BBCode Template System**: Create custom templates with 18 dynamic placeholders
- **Archive Management**: Automatic ZIP extraction and compression support
- **Credential Management**: Secure storage using system keyring
- **Hook System**: External script integration for custom workflows
- **Comprehensive Logging**: Detailed logs with filtering and export capabilities
- **Adaptive Settings**: Context-aware settings panels that adapt to your workflow
- **Bandwidth Tracking**: Monitor upload/download speeds and usage

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
| **imx.to** | Session | Unlimited | Unlimited | Primary gallery hosting |
| **Fileboom** | API Key | 10 GB | 10 TB | Multi-step upload, deduplication |
| **Filedot** | Session | Varies | Varies | CAPTCHA handling, CSRF protection |
| **Filespace** | Cookie | Varies | Varies | Simple cookie-based auth |
| **Keep2Share** | API Key | 10 GB | 10 TB | Same API as Fileboom |
| **Rapidgator** | Token | 5 GB | Varies | MD5 verification, polling |
| **Tezfiles** | Session | Varies | Varies | Token extraction |

*All hosts support automatic retry, connection pooling, and token caching*

---

## Installation

### Prerequisites

- **Python 3.14+** (required)
- **Windows/Linux** operating system
- **Internet connection** for uploads

### Quick Install

```bash
# Clone the repository
git clone https://github.com/twwat/imxup.git
cd imxup

# Install dependencies
pip install -r requirements.txt

# Launch GUI
python imxup.py --gui
```

### Windows Executable

Download the pre-built executable from releases:
1. Download `imxup.exe`
2. Double-click to run
3. No Python installation required!

### Development Setup

```bash
# Install development dependencies
pip install -r requirements-dev.txt

# Run tests
pytest tests/

# Build executable (Windows)
build.bat
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
| `#ext1#` | Extended field 1 | Custom data |
| `#ext2#` | Extended field 2 | Custom data |
| `#ext3#` | Extended field 3 | Custom data |
| `#ext4#` | Extended field 4 | Custom data |

### Example Template

```
📸 Gallery: #folderName#
📊 Images: #pictureCount# (#extension# format)
💾 Size: #folderSize#
📐 Dimensions: #width#x#height# (longest: #longest#)
🔗 Link: #galleryLink#

#allImages#
```

### Creating Custom Templates

1. Open **Settings → BBCode Template**
2. Click **Manage BBCode Templates**
3. Click **New Template**
4. Name your template (e.g., "Forum Post")
5. Use the placeholder buttons to insert dynamic values
6. Save and select from the dropdown

Templates are stored in `~/.imxup/*.template.txt`

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

Comprehensive documentation is available in the `docs/` directory:

### User Documentation
- **[GUI Guide](docs/user/gui-guide.md)** - Complete GUI interface walkthrough
- **[Multi-Host Upload](docs/user/multi-host-upload.md)** - File host configuration guide
- **[BBCode Templates](docs/user/bbcode-templates.md)** - Template creation reference
- **[Keyboard Shortcuts](docs/user/keyboard-shortcuts.md)** - All keyboard shortcuts
- **[Quick Start Guide](docs/user/quick-start.md)** - Get started in 5 minutes
- **[Troubleshooting](docs/user/troubleshooting.md)** - Common issues and solutions

### Developer Documentation
- **[Architecture](docs/architecture/)** - System design and component overview
- **[Testing Guide](docs/dev/)** - Running and writing tests
- **[API Reference](docs/dev/)** - Internal API documentation

---

## Screenshots

### Main Interface
![Main Window](assets/screenshot-main.png)
*Drag-and-drop interface with queue management and real-time progress*

### Settings Panel
![Settings](assets/screenshot-settings.png)
*Adaptive settings with file host configuration and template management*

### BBCode Viewer
![BBCode Output](assets/screenshot-bbcode.png)
*Generated BBCode with syntax highlighting and one-click copy*

### Multi-Host Upload
![File Hosts](assets/filehosts-dark.png)
*Configure multiple file hosting services with credential management*

---

## System Requirements

### Minimum Requirements
- **OS**: Windows 10+ or Linux (Ubuntu 20.04+, Fedora 35+)
- **Python**: 3.14 or higher
- **RAM**: 512 MB
- **Disk**: 100 MB free space
- **Network**: Stable internet connection

### Recommended
- **OS**: Windows 11 or Linux (latest)
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

### Building Executable

```bash
# Windows
build.bat

# Manual build with PyInstaller
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

## Troubleshooting

### Common Issues

**Problem**: GUI won't start
```bash
# Solution: Check PyQt6 installation
pip install --upgrade PyQt6
```

**Problem**: qt.qpa.xcb: could not connect to display (Windows Subsystem for Linux) 
```bash
# Solution: Set DISPLAY environment variable to :0
export DISPLAY=:0

**Problem**: Upload fails with "Authentication error"
```bash
# Solution: Re-enter credentials in Settings → File Hosts
# Click "Test Connection" to verify
```

**Problem**: Duplicate detection not working
```bash
# Solution: Enable in Settings → Advanced → Duplicate Detection
```

**Problem**: BBCode template not applying
```bash
# Solution: Check template syntax, ensure placeholders are spelled correctly
# View logs: Help → View Logs
```

For more issues, see **[Troubleshooting Guide](docs/user/troubleshooting.md)**

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## Support

### Getting Help

- **Documentation**: Check the `docs/` directory
- **Issues**: [GitHub Issues](https://github.com/twwat/imxup/issues)
- **Discussions**: [GitHub Discussions](https://github.com/twwat/imxup/discussions)

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

## Changelog

### v0.6.00 (Latest)
- ✨ Multi-host file upload system with 6 provider integrations
- 🔐 Enhanced authentication with token caching and TTL management
- 🎨 Improved GUI with adaptive settings panels
- 🔧 External hooks system for custom workflows

### v0.5.13
- 🚀 Partial multi-host uploader implementation
- 🗜️ ZIP compression support

### v0.5.12
- ⚙️ Adaptive Settings Panel
- 🪝 External Hooks system
- 🛠️ System enhancements

See **[CHANGELOG.md](CHANGELOG.md)** for complete version history.

---

## Acknowledgments

- **PyQt6** - Excellent GUI framework
- **imx.to** - Primary image hosting service
- **File Host Providers** - Fileboom, Keep2Share, Rapidgator, and others
- **Contributors** - Everyone who has contributed code, bug reports, and ideas

---

## Project Status

**Active Development** - ImXup is actively maintained and receives regular updates. The latest stable version is v0.6.15.

### Roadmap

- [ ] Additional file host integrations (1fichier, Katfile)
- [ ] Cloud storage support (Google Drive, Dropbox)
- [ ] API for automation and integrations
- [ ] Mobile companion app
- [ ] Batch BBCode template processing
- [ ] Advanced duplicate detection with perceptual hashing

---

**Made with ❤️ by the ImXup team**

[⬆ Back to top](#imxup---multi-host-gallery-uploader)
