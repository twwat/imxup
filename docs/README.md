# IMXuploader Documentation Index

**Version:** 0.6.16
**Last Updated:** 2026-01-03

Welcome to the IMXuploader documentation! This index will help you find the right documentation for your needs.

---

## Quick Navigation

**New to IMXuploader?**
- Start with [Quick Start Guide](user/getting-started/quick-start.md)
- Or read the [Main README](../README.md) in the project root

**Looking for specific features?**
- [Multi-Host Upload Guide](user/guides/multi-host-upload.md) - Upload to multiple file hosts
- [Archive Management](user/guides/archive-management.md) - Working with ZIP archives
- [Troubleshooting](user/troubleshooting/troubleshooting.md) - Common issues and solutions

**Developer?**
- Coming Soon: Developer Documentation

---

## Documentation Categories

### User Documentation
**For end users of the IMXuploader application**

Complete guides for using the GUI, uploading galleries, managing archives, and configuring settings.

**Location:** `/docs/user/`

**Getting Started:**
- [User Documentation Index](user/index.md) - Overview of all user guides
- [Quick Start](user/getting-started/quick-start.md) - Get started in 5 minutes
- [Setup Guide](user/getting-started/setup.md) - Installation and configuration

**Core Guides:**
- [GUI Guide](user/guides/gui-guide.md) - Complete GUI documentation
- [Multi-Host Upload](user/guides/multi-host-upload.md) - Upload to multiple file hosts
- [BBCode Templates](user/guides/bbcode-templates.md) - Custom BBCode templates and placeholders
- [Archive Management](user/guides/archive-management.md) - Working with ZIP and other archives

**Reference:**
- [Features List](user/reference/FEATURES.md) - Complete feature inventory
- [Keyboard Shortcuts](user/getting-started/keyboard-shortcuts.md) - All keyboard shortcuts
- [Quick Reference](user/reference/quick-reference.md) - Quick lookup for common tasks
- [External Apps Parameters](user/reference/external-apps-parameters.md) - Parameters for external applications

**Troubleshooting:**
- [Troubleshooting Guide](user/troubleshooting/troubleshooting.md) - Common issues and solutions
- [FAQ](user/troubleshooting/faq.md) - Frequently asked questions
- [Silent Failures Guide](user/troubleshooting/silent-failures.md) - Diagnosing silent failures
- [WSL2 Drag-Drop Fix](user/troubleshooting/wsl2-drag-drop-fix.md) - WSL2 integration issues
- [Log Diagnosis Quick Reference](user/troubleshooting/LOG_DIAGNOSIS_QUICK_REF.md) - Using logs for diagnosis
- [Log Filtering Quick Diagnosis](user/troubleshooting/LOG_FILTERING_QUICK_DIAGNOSIS.md) - Filtering logs for issues

**Other:**
- [Help Content](user/reference/HELP_CONTENT.md) - In-app help dialog content

---

### Developer Documentation
**For contributors and developers extending IMXuploader**

**Location:** `/docs/dev/`

**Status:** Coming Soon

Developer documentation is being reorganized. In the interim, refer to:
- [CLAUDE.md](../CLAUDE.md) - Project context and architecture overview
- [Testing Quick Start](dev/testing/TESTING_QUICKSTART.md) - Getting started with testing
- [Testing Status](dev/testing/TESTING_STATUS.md) - Current testing status and coverage
- [Manual Testing State Isolation](dev/testing/MANUAL_TESTING_STATE_ISOLATION.md) - Test isolation guide
- [Coverage Quickstart](dev/testing/coverage-quickstart.md) - Coverage measurement guide

---

### Historical Documentation
**Archive of development history and technical investigations**

Historical development sessions, performance analyses, implementation notes, and legacy fixes preserved for reference.

**Location:** `/docs/archive/`

📖 **[Browse Archive Index →](archive/README.md)**

---

## Documentation by Task

### Getting Started
1. [Project README](../README.md) - Project overview
2. [Quick Start Guide](user/getting-started/quick-start.md) - Installation and first upload
3. [GUI Guide](user/guides/gui-guide.md) - Learn the interface

### Uploading Galleries
1. [Quick Start](user/getting-started/quick-start.md) - Basic upload
2. [Multi-Host Upload](user/guides/multi-host-upload.md) - Upload to multiple hosts
3. [BBCode Templates](user/guides/bbcode-templates.md) - Customize BBCode output

### Managing Content
1. [Archive Management](user/guides/archive-management.md) - Create and manage ZIP archives
2. [GUI Guide](user/guides/gui-guide.md) - Queue management and tabs

### Troubleshooting
1. [Troubleshooting Guide](user/troubleshooting/troubleshooting.md) - Common issues
2. [FAQ](user/troubleshooting/faq.md) - Frequently asked questions
3. [Log Diagnosis](user/troubleshooting/LOG_DIAGNOSIS_QUICK_REF.md) - Using logs to debug issues

### Testing & Contributing
1. [Testing Quick Start](dev/testing/TESTING_QUICKSTART.md) - How to run tests
2. [Testing Status](dev/testing/TESTING_STATUS.md) - Current test coverage
3. [Architecture Overview](../CLAUDE.md) - Understand the codebase

---

## Finding Documentation

### By Feature

| Feature | Documentation |
|---------|---------------|
| **Multi-Host Upload** | [Multi-Host Upload Guide](user/guides/multi-host-upload.md) |
| **Archive/ZIP Management** | [Archive Management](user/guides/archive-management.md) |
| **BBCode Templates** | [BBCode Templates Guide](user/guides/bbcode-templates.md) |
| **Keyboard Shortcuts** | [Keyboard Shortcuts](user/getting-started/keyboard-shortcuts.md) |
| **Settings & Configuration** | [Setup Guide](user/getting-started/setup.md) |
| **Troubleshooting** | [Troubleshooting Guide](user/troubleshooting/troubleshooting.md) |

### By Role

**End Users:** → [User Documentation Index](user/index.md)
**Testers:** → [Testing Quick Start](dev/testing/TESTING_QUICKSTART.md)
**Researchers/Contributors:** → [CLAUDE.md Architecture](../CLAUDE.md)

---

## Documentation Standards

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

## Contributing to Documentation

Found an error or want to improve documentation?

1. **Quick Fixes:** Edit the file directly and submit a PR
2. **New Documentation:** Follow the [Contributing Guide](../CONTRIBUTING.md)
3. **Structure Changes:** Open an issue first for discussion

All documentation contributions are welcome!

---

## Documentation Status

### Coverage

| Category | Status |
|----------|--------|
| User Docs | Completed (18 files) |
| Dev Docs (Testing) | Available (4 files) |
| Dev Docs (General) | Coming Soon |
| Archive | Organized |

### Recent Updates

- **2026-01-03:** Fixed links to reflect actual directory structure
- **2026-01-03:** Marked non-existent dev docs as "Coming Soon"
- **2026-01-03:** Updated version to 0.6.16
- **2025-11-15:** Documentation reorganization complete

---

## Need Help?

**Can't find what you're looking for?**

1. Check the [FAQ](user/troubleshooting/faq.md)
2. Review the [Troubleshooting Guide](user/troubleshooting/troubleshooting.md)
3. Check [Log Diagnosis Quick Reference](user/troubleshooting/LOG_DIAGNOSIS_QUICK_REF.md)
4. Open an issue on GitHub

**In the GUI:**
- Press `F1` or `Ctrl+.` to open the Help Dialog
- All user documentation is accessible from there

---

**Last Updated:** 2026-01-03
**Documentation Version:** 0.6.16
