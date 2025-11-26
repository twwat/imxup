# ImxUp Documentation Index

**Version:** 0.6.00
**Last Updated:** 2025-11-15

Welcome to the ImxUp documentation! This index will help you find the right documentation for your needs.

---

## 🚀 Quick Navigation

**New to ImxUp?**
- Start with [Quick Start Guide](user/quick-start.md)
- Or read the [Main README](../README.md) in the project root

**Looking for specific features?**
- [Multi-Host Upload Guide](user/multi-host-upload.md) - Upload to multiple file hosts
- [Archive Management](user/archive-management.md) - Working with ZIP archives
- [Troubleshooting](user/troubleshooting.md) - Common issues and solutions

**Developer?**
- Check out [Developer Documentation](dev/README.md)
- Start with [Architecture Overview](dev/ARCHITECTURE.md)

---

## 📚 Documentation Categories

### 👤 User Documentation
**For end users of the ImxUp application**

Documentation for using the GUI, uploading galleries, managing archives, and configuring settings.

📁 **Location:** `/docs/user/`

**Core Guides:**
- [Quick Start](user/quick-start.md) - Get started in 5 minutes
- [GUI Guide](user/gui-guide.md) - Complete GUI documentation
- [Multi-Host Upload](user/multi-host-upload.md) - Upload to multiple file hosts ⭐ NEW
- [BBCode Templates](user/bbcode-templates.md) - Custom BBCode templates
- [Keyboard Shortcuts](user/keyboard-shortcuts.md) - All keyboard shortcuts
- [Troubleshooting](user/troubleshooting.md) - Common issues and solutions
- [Help Content](user/HELP_CONTENT.md) - In-app help dialog content
- [GUI Improvements](user/gui-improvements.md) - GUI feature changelog
- [Testing Quick Start](user/TESTING_QUICKSTART.md) - Quick testing setup
- [Testing Status](user/TESTING_STATUS.md) - Current testing status

📖 **[Browse All User Docs →](user/README.md)**

---

### 🛠️ Developer Documentation
**For contributors and developers extending ImxUp**

Technical documentation covering architecture, APIs, development workflows, and contribution guidelines.

📁 **Location:** `/docs/dev/`

**Core References:**
- [Architecture](dev/architecture.md) - System design and components ⭐ UPDATED
- [API Reference](dev/api-reference.md) - Complete file host API documentation ⭐ NEW
- [Architecture Analysis](dev/architecture-analysis.md) - Detailed architecture analysis
- [Integration Guide](dev/integration-guide.md) - Integration documentation
- [Testing Guide](dev/testing-guide.md) - Running and writing tests ⭐ NEW
- [Security Audit](dev/security-audit.md) - Security audit report
- [Security Fixes](dev/security-fixes.md) - Implemented security fixes
- [Database Reference](dev/database-reference.md) - Database quick reference
- [Database Maintenance](dev/database-maintenance.md) - Database maintenance guide
- [Module Dependencies](dev/module-dependencies.md) - Module dependency map
- [Implementation Roadmap](dev/implementation-roadmap.md) - Implementation roadmap
- [Coverage Roadmap](dev/COVERAGE_ROADMAP.md) - Test coverage roadmap
- [PyCURL PyInstaller Fix](dev/pycurl-pyinstaller-fix.md) - PyCURL bundling for PyInstaller
- [PyCURL Bundling](dev/pycurl-bundling.md) - PyCURL bundling verification
- [PyCURL Windows](dev/pycurl-windows.md) - PyCURL Windows structure
- [Cross-Platform Fixes](dev/cross-platform-fixes.md) - Cross-platform compatibility
- [Python 3.14 Upgrade](dev/python-314-upgrade.md) - Python 3.14 upgrade guide
- [Performance Reference](dev/performance_quick_reference.md) - Performance quick reference
- [Bottleneck Analysis](dev/BOTTLENECK_ANALYSIS.md) - Bottleneck analysis
- [GUI Blocking Investigation](dev/GUI_BLOCKING_INVESTIGATION.md) - GUI blocking investigation
- [Initialization System](dev/initialization-system.md) - Initialization system design
- [Emergency Startup Optimization](dev/EMERGENCY_STARTUP_OPTIMIZATION_ARCHITECTURE.md) - Startup optimization
- [Memory System](dev/memory-system/) - Memory system documentation

📖 **[Browse All Developer Docs →](dev/README.md)**

---

### 📦 Historical Documentation
**Archive of development history and technical investigations**

Historical development sessions, performance analyses, implementation notes, and legacy fixes preserved for reference.

📁 **Location:** `/docs/archive/`

**Categories:**
- **Development History** - Development sessions and phase results
- **Performance Analysis** - Performance investigations and optimizations
- **Implementation Notes** - Specific feature implementation details
- **Legacy Fixes** - Historical bug fixes and patches
- **Testing History** - Old test documentation and reports
- **Quality Audits** - Point-in-time quality and security audits

📖 **[Browse Archive Index →](archive/README.md)**

---

## 🎯 Documentation by Task

### Getting Started
1. [Project README](../README.md) - Project overview
2. [Quick Start Guide](user/quick-start.md) - Installation and first upload
3. [GUI Guide](user/gui-guide.md) - Learn the interface

### Uploading Galleries
1. [Quick Start](user/quick-start.md) - Basic upload
2. [Multi-Host Upload](user/multi-host-upload.md) - Upload to multiple hosts
3. [Templates](user/templates-advanced.md) - Customize BBCode output

### Managing Content
1. [Archive Management](user/archive-management.md) - Create and manage ZIP archives
2. [Duplicate Detection](user/duplicate-detection.md) - Find duplicate galleries
3. [GUI Guide](user/gui-guide.md) - Queue management and tabs

### Troubleshooting
1. [Troubleshooting Guide](user/troubleshooting.md) - Common issues
2. [FAQ](user/faq.md) - Frequently asked questions
3. [GitHub Issues](https://github.com/YOUR_REPO/issues) - Report bugs

### Contributing
1. [Contributing Guide](dev/contributing.md) - How to contribute
2. [Architecture](dev/ARCHITECTURE.md) - Understand the codebase
3. [Testing Guide](dev/testing-guide.md) - Run and write tests
4. [Build & Deploy](dev/build-deploy.md) - Build the application

---

## 🔍 Finding Documentation

### By Feature

| Feature | Documentation |
|---------|---------------|
| **Multi-Host Upload** | [Multi-Host Upload Guide](user/multi-host-upload.md) |
| **Archive/ZIP Creation** | [Archive Management](user/archive-management.md) |
| **BBCode Templates** | [Templates Advanced](user/templates-advanced.md) |
| **Duplicate Detection** | [Duplicate Detection](user/duplicate-detection.md) |
| **Keyboard Shortcuts** | [Keyboard Shortcuts](user/keyboard-shortcuts.md) |
| **Icon Customization** | [Icon Customization](user/icon-customization.md) |
| **Database** | [Database Schema](dev/database-schema.md) |
| **Networking** | [Network Layer](dev/network-layer.md) |
| **Threading** | [Threading Model](dev/threading-model.md) |
| **Hooks/Plugins** | [Hooks Development](dev/hooks-development.md) |

### By Role

**End Users:** → [User Documentation](user/README.md)
**Developers:** → [Developer Documentation](dev/README.md)
**Researchers:** → [Historical Archive](archive/README.md)

---

## 📝 Documentation Standards

All documentation follows these standards:

### User Documentation
- Clear, non-technical language
- Step-by-step instructions
- Screenshots where helpful
- Troubleshooting sections
- Related documentation links

### Developer Documentation
- Technical detail with code examples
- Architecture diagrams where relevant
- API signatures and parameters
- Best practices and patterns
- Cross-references to related code

### Markdown Formatting
- Use heading hierarchy (H1 = title, H2 = sections, H3 = subsections)
- Code blocks with language specification
- Tables for structured data
- Lists for sequential steps
- Bold for **important** concepts
- Italic for *emphasis*

---

## 🤝 Contributing to Documentation

Found an error or want to improve documentation?

1. **Quick Fixes:** Edit the file directly and submit a PR
2. **New Documentation:** Follow the [Contributing Guide](dev/contributing.md)
3. **Structure Changes:** Open an issue first for discussion

All documentation contributions are welcome!

---

## 📋 Documentation Status

### Coverage

| Category | Files | Coverage | Status |
|----------|-------|----------|--------|
| User Docs | 10 | 85% | ✅ Complete |
| Dev Docs | 23 | 90% | ✅ Complete |
| Archive | 65+ | 100% | ✅ Organized |

### Recent Updates

- **2025-11-15:** Documentation reorganization complete
- **2025-11-15:** Added multi-host upload documentation
- **2025-11-15:** Created archive for historical docs
- **2025-11-15:** Restructured user/dev separation

---

## 🆘 Need Help?

**Can't find what you're looking for?**

1. Check the [FAQ](user/faq.md)
2. Search [all documentation](https://github.com/YOUR_REPO/tree/master/docs)
3. Ask in [GitHub Discussions](https://github.com/YOUR_REPO/discussions)
4. Open an [issue](https://github.com/YOUR_REPO/issues)

**In the GUI:**
- Press `F1` or `Ctrl+.` to open the Help Dialog
- All user documentation is accessible from there

---

**Last Updated:** 2025-11-15
**Documentation Version:** 1.0 (Post-Reorganization)
