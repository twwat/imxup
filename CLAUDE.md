# CLAUDE.md - IMXuploader Project Context

**Version:** 0.6.13+
**Last Updated:** 2025-12-28

This document provides essential context for Claude AI when working with the IMXuploader codebase.

---

## Project Overview

**IMXuploader** is a professional-grade desktop application for uploading image galleries to imx.to and multiple file hosting services. It features a modern PyQt6 GUI, comprehensive multi-host support, and advanced BBCode template system.

### What It Does
- Uploads image galleries to **imx.to** (primary host)
- Supports **6 premium file hosts** + 44 additional hosts via hooks
- Generates customizable BBCode output with 18 dynamic placeholders
- Manages upload queues with 9 distinct gallery states
- Provides batch operations, drag-and-drop, and real-time progress tracking

### Operating Modes
- **GUI Mode** (recommended): `python imxup.py --gui`
  - PyQt6-based modern interface with dark/light themes
  - Tab management, queue management, system tray integration
  - Real-time progress tracking with bandwidth monitoring

- **CLI Mode**: `python imxup.py /path/to/folder`
  - Command-line interface for automation
  - Supports 15+ command-line arguments
  - Integrates with Windows context menu

---

## Architecture

### Module Organization

```
src/
├── core/           # Core upload engine and configuration
│   ├── engine.py              # UploadEngine - orchestrates uploads
│   ├── constants.py           # Application constants
│   └── file_host_config.py    # File host configuration loader
│
├── gui/            # PyQt6 GUI components
│   ├── main_window.py         # Main GUI (4975 lines) [REFACTORED]
│   ├── progress_tracker.py    # Progress tracking (268 lines) [EXTRACTED]
│   ├── worker_signal_handler.py # Worker signals (534 lines) [EXTRACTED]
│   ├── gallery_queue_controller.py # Queue management (756 lines) [EXTRACTED]
│   ├── table_row_manager.py   # Table operations (1268 lines) [EXTRACTED]
│   ├── settings_manager.py    # Settings persistence (320 lines) [EXTRACTED]
│   ├── theme_manager.py       # Theme management (403 lines) [EXTRACTED]
│   ├── settings_dialog.py     # Settings management
│   ├── tab_manager.py         # Tab system
│   ├── dialogs/               # 15+ dialog types
│   └── widgets/               # Custom widgets
│
├── network/        # HTTP clients and API handlers
│   ├── client.py              # IMX.to API client
│   ├── file_host_client.py    # Multi-host upload client (pycurl-based)
│   ├── cookies.py             # Cookie management
│   └── token_cache.py         # Token caching with TTL
│
├── processing/     # Background workers and coordinators
│   ├── upload_workers.py      # UploadWorker QThread
│   ├── file_host_workers.py   # File host upload workers
│   ├── archive_coordinator.py # ZIP/RAR extraction
│   ├── hooks_executor.py      # External hook system
│   └── rename_worker.py       # Gallery auto-renaming
│
├── storage/        # Persistence layer
│   ├── database.py            # SQLite storage (1636 lines - needs splitting)
│   ├── queue_manager.py       # Queue management facade
│   └── path_manager.py        # Path utilities
│
└── utils/          # Utilities and helpers
    ├── logger.py              # Logging system
    ├── format_utils.py        # Size/rate formatting
    ├── template_utils.py      # BBCode template parsing
    ├── credential_helpers.py  # Keyring integration
    └── metrics_store.py       # Performance metrics
```

### Main Entry Points

- **`imxup.py`** - Primary entry point for both CLI and GUI (--gui parameter)
- **`src/gui/main_window.py`** - `ImxUploadGUI` main window class
- **`src/core/engine.py`** - `UploadEngine` core upload logic

### Database Location

**CRITICAL:** The queue database is at `{central_store_path}/imxup.db`

- Default: `~/.imxup/imxup.db` (Windows: `%USERPROFILE%/.imxup/imxup.db`)
- **NOT** `~/.imxup/queue.db` (legacy location, no longer used)
- Uses SQLite with WAL mode for concurrent access
- Schema includes: galleries, images, tabs, unnamed_galleries, file_host_uploads, settings

---

## Key Files

### Core Files (Priority 1)
- **`imxup.py`** (2600+ lines) - Main entry, CLI argument parsing, credential setup
- **`src/core/engine.py`** (800+ lines) - Upload orchestration, retry logic, statistics
- **`src/storage/database.py`** (1636 lines) - SQLite CRUD operations, tab management
- **`src/network/file_host_client.py`** (1400+ lines) - Multi-host upload client with pycurl

### GUI Files (Priority 2)
- **`src/gui/main_window.py`** (4975 lines) - Main window [REFACTORED]
  - Reduced from 7518 lines through extraction of 6 modules
  - Extracted: ProgressTracker, WorkerSignalHandler, GalleryQueueController, TableRowManager, SettingsManager, ThemeManager
- **`src/gui/progress_tracker.py`** (268 lines) - Progress tracking component
- **`src/gui/worker_signal_handler.py`** (534 lines) - Worker signal coordination
- **`src/gui/gallery_queue_controller.py`** (756 lines) - Queue management logic
- **`src/gui/table_row_manager.py`** (1268 lines) - Table row operations
- **`src/gui/settings_manager.py`** (320 lines) - Settings persistence
- **`src/gui/theme_manager.py`** (403 lines) - Theme management
- **`src/gui/settings_dialog.py`** - Adaptive settings panel
- **`src/gui/widgets/gallery_table.py`** - Gallery queue table widget
- **`src/gui/widgets/file_hosts_settings_widget.py`** - File host configuration UI

### Processing Files (Priority 3)
- **`src/processing/upload_workers.py`** - Background upload workers (QThread)
- **`src/processing/file_host_workers.py`** - File host upload coordination
- **`src/processing/archive_coordinator.py`** - ZIP/RAR extraction

---

## Authentication Methods

### File Host Authentication (ACCURATE)

**API Key Authentication** (permanent tokens)
- **Fileboom** (fboom.me) - Credentials format: `api_key`
- **Keep2Share** (k2s.cc) - Credentials format: `api_key`
- **TezFiles** (tezfiles.com) - Credentials format: `api_key` **[NOT session-based]**
- **Katfile** (katfile.com) - Credentials format: `api_key` (in development)

**Token Login** (temporary with TTL)
- **Rapidgator** (rapidgator.net) - Token-based login, 24h TTL, auto-refresh
  - Auth flow: username/password → session token → cached token
  - Uses `TokenCache` with encrypted storage

**Session-Based** (cookie-based)
- **Filedot** (filedot.to) - Session cookies with CAPTCHA handling
- **Filespace** (filespace.com) - Cookie-based sessions

### IMX.to Authentication
- Username/password stored in OS keyring or encrypted in QSettings
- Session-based login with cookie persistence
- Uses `requests.Session()` for connection pooling

---

## Credentials Storage

### Storage Hierarchy (Secure)

1. **Primary: OS Keyring** (recommended)
   - Windows: Credential Manager
   - macOS: Keychain
   - Linux: Secret Service (gnome-keyring, KWallet)
   - Accessed via `keyring` library

2. **Fallback: QSettings with Fernet Encryption**
   - Location: `~/.imxup/config.ini`
   - Encrypted with Fernet (AES-128 in CBC mode)
   - Key derived from PBKDF2-HMAC-SHA256 (100,000 iterations)

### Security Notes

**All credentials ARE encrypted** (contrary to some review claims)
- Passwords encrypted before storage
- API keys encrypted in fallback storage
- Tokens cached with TTL and encryption

**Known Issues (from review_summary.txt):**
- Legacy Fernet key derivation in `imxup.py` lines 334-339 uses hostname (not ideal)
- Decrypted tokens cached in memory without secure wiping (should use `secrets` module)

---

## Code Style

### Language & Version
- **Python 3.14+** (minimum 3.10)
- Type hints throughout
- Modern Python features (union types with `|`, pattern matching)

### Code Conventions
- **Imports:** Standard library → Third-party → Local (`from src.module import ...`)
- **Naming:**
  - Classes: `PascalCase` (`UploadWorker`, `GalleryQueueItem`)
  - Functions/methods: `snake_case` (`format_binary_size`, `get_next_item`)
  - Constants: `UPPER_SNAKE_CASE` (`DEBUG_MODE`, `MAX_RETRIES`)
  - Private methods: `_underscore_prefix` (`_initialize_uploader`)
  - PyQt6 signals: `snake_case` (`progress_updated`, `gallery_completed`)

### Docstrings
- **Google-style docstrings** for all public functions/classes
- Example:
  ```python
  def sanitize_gallery_name(name: str) -> str:
      """Sanitize gallery name to remove invalid characters.

      Replaces characters <>:"/\\|?* with _

      Args:
          name: Original gallery name

      Returns:
          Sanitized name safe for use as filename
      """
  ```

### PyQt6 Conventions
- Signals defined at class level with type annotations
- Proper cleanup in `stop()` methods for QThreads
- Resource management: Always call `wait()` after stopping threads

### Formatting
- **Indentation:** 4 spaces (no tabs)
- **Line length:** 100-120 characters (flexible for readability)
- **String quotes:** Double quotes preferred, single quotes acceptable

---

## Common Tasks

### Running Tests
```bash
# Run all tests
pytest tests/

# Run with coverage
pytest --cov=src tests/

# Run specific test file
pytest tests/unit/utils/test_format_utils.py

# Run verbose
pytest -v tests/
```

### Building
```bash
# Windows
build.bat

# Manual build with PyInstaller
pyinstaller imxup.spec
```

### Running the Application
```bash
# GUI mode
python imxup.py --gui

# CLI mode
python imxup.py /path/to/folder --name "Gallery Name"

# Debug mode (verbose logging)
python imxup.py --gui --debug
```

---

## Known Issues / Tech Debt

### Critical (Fix Immediately - Week 1)
1. **SSL/TLS certificate verification not explicit** in `file_host_client.py`
   - Risk: Medium (MITM attacks possible)
   - Fix: Add `verify=True` to all requests
   - Effort: 1-2 hours

2. ~~**Thread-safety bug in cookie caching** (`src/network/cookies.py`)~~ **[FIXED]**
   - Fixed with proper locking around cache access

3. **Bare exception handlers** (5+ instances)
   - Risk: Medium (silently swallows all exceptions including KeyboardInterrupt)
   - Fix: Replace `except:` with specific exceptions
   - Effort: 2-3 hours

### High Priority (Next Sprint - 2-4 weeks)
4. ~~**main_window.py too large** (7518 lines)~~ **[LARGELY COMPLETE]**
   - Reduced from 7518 to ~4975 lines through extraction of 6 modules:
     - `progress_tracker.py` (268 lines)
     - `worker_signal_handler.py` (534 lines)
     - `gallery_queue_controller.py` (756 lines)
     - `table_row_manager.py` (1268 lines)
     - `settings_manager.py` (320 lines)
     - `theme_manager.py` (403 lines)
   - Further refactoring possible but no longer critical

5. **database.py too large** (1636 lines)
   - Risk: Single responsibility principle violated
   - Fix: Split into GalleryCRUD, TabStore, FileHostStore, Schema
   - Effort: 4-6 days

6. **Debug code mixed with production**
   - 126 `print()` statements
   - Commented code blocks
   - Fix: Remove or consolidate into logging
   - Effort: 1-2 hours

### Medium Priority
7. **Race condition in upload workers**
   - Location: `src/processing/upload_workers.py`
   - Issue: `_soft_stop_requested_for` check-then-clear without lock
   - Fix: Use `threading.Event` for atomic signaling
   - Effort: 1-2 hours

8. **Missing API documentation**
   - Impact: Developers cannot extend the system
   - Fix: Generate API reference with Sphinx/mkdocs
   - Effort: 80-100 hours

### Test Coverage Gaps
- **Current:** 78-82% overall coverage
- **Target:** 85%+ across all modules
- **Gaps:**
  - `src/storage/`: ~50% (needs +30%)
  - `src/utils/`: ~60% (needs +20%)

---

## Performance Characteristics

### Optimizations Implemented
- **Icon caching:** 50-100x improvement with statistics tracking
- **Database indexing:** Indexes on `status`, `tab_id`, `path` columns
- **Batch operations:** `bulk_upsert_async()` for multiple galleries
- **WAL mode:** Concurrent reads/writes in SQLite
- **Connection pooling:** Thread-local sessions for HTTP requests
- **Lazy loading:** Viewport-based widget creation in table
- **QSettings caching:** Cached settings access to reduce I/O
- **O(1) row lookup:** Hash-based row indexing in table operations
- **Schema init once:** Database schema initialization on first access only

### Performance Bottlenecks
- Large file uploads (10GB+) may timeout (default: unlimited)
- Database writes on main thread block UI (should be async)
- Icon loading on first launch (cached after)

---

## Feature Inventory (100+ Features)

### Core Features
- **Multi-host uploads:** imx.to + 6 premium hosts + 44 via hooks
- **Authentication:** API key, token login, session-based
- **BBCode templates:** 18 placeholders with conditional logic
- **Queue states:** validating, scanning, ready, queued, uploading, paused, incomplete, completed, failed
- **Archive support:** ZIP, RAR, 7Z, TAR, TAR.GZ, TAR.BZ2

### GUI Features
- **Tab management:** Create, rename, move galleries between tabs
- **Drag-and-drop:** Add folders to queue
- **Real-time progress:** Per-image and overall progress
- **Bandwidth monitoring:** KB/s tracking
- **Theme support:** Dark, light, auto (system)
- **Keyboard shortcuts:** 18+ shortcuts
- **System tray:** Minimize to tray

### Advanced Features
- **Hooks system:** 4 hook types (pre/post-upload, on-complete, on-error)
- **Duplicate detection:** Intelligent detection of previously uploaded galleries
- **Auto-rename:** Background renaming of galleries on imx.to website
- **Artifact storage:** JSON metadata export
- **Custom fields:** 4 user-defined + 4 external app fields
- **Credential management:** OS keyring + encrypted fallback

---

## Database Schema

### Tables
- **galleries:** Gallery metadata (path, name, status, gallery_id, tab_name, custom1-4, ext1-4)
- **images:** Per-image upload tracking (path, gallery_path, status, image_url, uploaded_size)
- **tabs:** Tab management (id, name, tab_type, display_order, color_hint)
- **unnamed_galleries:** Galleries pending rename (gallery_id, intended_name)
- **file_host_uploads:** External file host upload tracking (gallery_path, host_name, status, download_url, file_id)
- **settings:** Application settings (key, value)

### Indexes
- `idx_galleries_status` on `galleries(status)`
- `idx_galleries_tab` on `galleries(tab_name)`
- `idx_galleries_path` on `galleries(path)`
- `idx_images_gallery` on `images(gallery_path)`
- `idx_file_host_gallery` on `file_host_uploads(gallery_path)`

---

## Configuration Files


### `{central_store_path}/imxup.ini`
Main config file, contain most user settings

- Default location: `~/.imxup/imxup.ini` (Windows: `%USERPROFILE%/.imxup/imxup.ini`)


---

## Integration Points

### External Hooks
- **muh.py:** Multi-host uploader (7 hosts)
- Custom scripts can be triggered on:
  - Pre-upload (before gallery creation)
  - Post-upload (after individual image)
  - On-complete (after gallery completion)
  - On-error (on upload failure)

### Windows Integration
- Context menu integration: Right-click folder → "Upload to imx.to (GUI)"
- Single-instance mode: Subsequent invocations add to existing GUI
- System tray notifications

---

## Testing Strategy

### Test Organization
```
tests/
├── unit/          # Unit tests (fast, isolated)
├── integration/   # Integration tests (slower, multi-component)
├── performance/   # Performance benchmarks
└── conftest.py    # Shared fixtures
```

### Coverage Targets
- Critical paths (upload, auth, data integrity): 90%+
- Utility functions: 100%
- Overall: 85%+

### Running Tests
```bash
pytest tests/                    # All tests
pytest --cov=src tests/          # With coverage
pytest -m unit tests/            # Only unit tests
pytest -m integration tests/     # Only integration tests
```

---

## Common Pitfalls

1. **Database path:** Always use `~/.imxup/imxup.db`, NOT `~/.imxup/queue.db`
2. **Thread safety:** Use `AtomicCounter` for shared state across threads
3. **QThread cleanup:** Always call `stop()` then `wait()` before deleting
4. **Signal connections:** Use `Qt.QueuedConnection` for cross-thread signals
5. **File paths:** Use `Path` objects, not strings
6. **Credential access:** Always check keyring availability before fallback

---

## Recent Changes (v0.6.13)

From `git log`:
- **Fix:** Help dialog performance, add emoji PNG support, improve quick settings
- **Perf:** Optimize theme switching speed
- **Refactor:** Extract ThemeManager from main_window.py
- **Refactor:** Extract SettingsManager from main_window.py
- **Refactor:** Extract TableRowManager from main_window.py
- **Refactor:** Extract GalleryQueueController from main_window.py
- **Refactor:** Extract WorkerSignalHandler from main_window.py
- **Refactor:** Extract ArtifactHandler, add worker logo setting
- **Perf:** Quick wins - cache QSettings, O(1) row lookup, schema init once
- **Fix:** Thread-safety in ImageStatusChecker, improve worker lifecycle

---

## References

- **User Docs:** `docs/user/` - GUI guide, multi-host upload, BBCode templates
- **API Docs:** `docs/API_REFERENCE.md` - Comprehensive API documentation
- **Contributing:** `CONTRIBUTING.md` - Code style, PR process, development setup
- **Review:** `logs/review_summary.txt` - Comprehensive code review (76.8/100 grade)

---

## Notes for Claude

- **Main window refactoring** largely complete - reduced from 7518 to ~4975 lines
- **Test coverage** is good but has gaps in storage/utils modules
- **Documentation** is excellent for users, needs work for developers
- **Code quality** is professional (B+ grade) with some underengineering in places

---

## AI Team Configuration (autogenerated by team-configurator, 2025-12-27)

**Important: YOU MUST USE subagents when available for the task.**

### Detected Tech Stack

| Category | Technology | Version/Details |
|----------|------------|-----------------|
| Language | Python | 3.14+ (minimum 3.10), comprehensive type hints |
| GUI Framework | PyQt6 | 6.9.1 (desktop application with QThread workers) |
| Database | SQLite | WAL mode for concurrent access |
| HTTP Uploads | pycurl | 7.45.7 (multi-host file uploads) |
| HTTP Client | requests | 2.31.0 (API calls, session management) |
| Encryption | cryptography | 45.0.5 (Fernet AES-128-CBC) |
| Credentials | keyring | 25.0.0+ (OS credential storage) |
| Image Processing | Pillow | 11.3.0 |
| Testing | pytest | With pytest-cov for coverage |
| Building | PyInstaller | Via imxup.spec |
| Platform | Windows | Primary (pywin32-ctypes, winregistry) |

### Agent Locations

**System-Level Agents (priority):** `~/.claude/agents/awesome-claude-agents/agents/`
**Project-Level Agents (backup):** `H:\IMXuploader\.claude\agents-bak\`

### Primary Specialists (System-Level)

| Task | Agent | When to Use |
|------|-------|-------------|
| Codebase exploration | `code-archaeologist` | MUST USE before major refactors, onboarding, or architecture changes. Produces comprehensive reports. |
| Code review | `code-reviewer` | MUST USE for every PR, bug fix, or feature. Security-aware, severity-tagged reports. |
| Performance optimization | `performance-optimizer` | MUST USE for slowness, upload speed issues, UI lag. Profile before optimizing. |
| Documentation | `documentation-specialist` | MUST USE after major features or API changes. Creates READMEs, API specs, architecture guides. |
| Complex multi-step tasks | `tech-lead-orchestrator` | MUST USE for feature implementations requiring multiple specialists. Delegates to sub-agents. |

### Python Specialists (System-Level)

| Task | Agent | When to Use |
|------|-------|-------------|
| Python development | `python-expert` | Primary for all Python code: engine.py, workers, network clients, type hints. |
| Testing & QA | `testing-expert` | pytest fixtures, parametrized tests, mocking, coverage improvement. Target 85%+. |
| Security review | `security-expert` | Fernet key derivation, token caching, SSL verification, credential storage. |
| Performance profiling | `performance-expert` | cProfile, memory profiling, async optimization, QThread performance. |

### Backup Specialists (Project-Level)

| Task | Agent | Notes |
|------|-------|-------|
| Refactoring | `refactoring-specialist` | database.py (1636 lines). Safe incremental changes. |
| Debugging | `debugger` | Thread-safety bugs, race conditions, QThread issues. |
| Database optimization | `database-optimizer` | SQLite WAL mode, query optimization, index strategy. |
| Test automation | `test-automator` | CI/CD integration, PyQt6 GUI testing. |
| CLI development | `cli-developer` | imxup.py CLI mode, argument parsing. |
| UI/UX | `ui-designer` | Dark/light themes, PyQt6 widget design. |
| QA | `qa-expert` | Test strategy, coverage analysis. |
| Security audit | `security-auditor` | Comprehensive security assessment. |

### Task Routing Guide

#### Refactoring Tasks (Priority)

1. ~~**main_window.py refactoring** (7518 lines)~~ **[COMPLETE]**
   - Reduced to ~4975 lines through extraction of 6 modules
   - Extracted: ProgressTracker, WorkerSignalHandler, GalleryQueueController, TableRowManager, SettingsManager, ThemeManager

2. **database.py refactoring** (1636 lines)
   - Start: `@code-archaeologist` for schema analysis
   - Execute: `@python-expert` for implementation
   - Review: `@code-reviewer` for quality gate
   - Split into: GalleryCRUD, TabStore, FileHostStore, Schema

#### Security Tasks

| Issue | Agent | Location |
|-------|-------|----------|
| SSL/TLS verification | `@security-expert` | `src/network/file_host_client.py` |
| ~~Thread-safety in cookies~~ | ~~`@security-expert`~~ | ~~`src/network/cookies.py`~~ **[FIXED]** |
| Fernet key derivation | `@security-expert` | `imxup.py` lines 334-339 |
| Bare exception handlers | `@code-reviewer` | 5+ instances across codebase |

#### Performance Tasks

| Issue | Agent | Details |
|-------|-------|---------|
| Database writes blocking UI | `@performance-optimizer` | Should be async |
| Large file uploads (10GB+) | `@performance-expert` | Timeout handling |
| Icon loading optimization | `@performance-optimizer` | First launch performance |
| Upload speed profiling | `@performance-expert` | pycurl optimization |

#### Testing Tasks

| Gap | Agent | Target |
|-----|-------|--------|
| src/storage/ coverage | `@testing-expert` | From ~50% to 80%+ |
| src/utils/ coverage | `@testing-expert` | From ~60% to 80%+ |
| Overall coverage | `@testing-expert` | From 78-82% to 85%+ |
| PyQt6 GUI tests | `@testing-expert` | QThread, signals testing |

### Execution Patterns

**Full Feature Implementation:**
```
@tech-lead-orchestrator → analyze requirements → assign sub-agents
  ├── @code-archaeologist → understand existing code
  ├── @python-expert → implement feature
  ├── @testing-expert → write tests
  └── @code-reviewer → quality gate
```

**Bug Fix:**
```
@code-archaeologist → locate issue → understand context
  ├── @python-expert → implement fix
  ├── @testing-expert → add regression test
  └── @code-reviewer → verify fix
```

**Performance Issue:**
```
@performance-optimizer → profile → identify bottleneck
  ├── @python-expert → implement optimization
  └── @code-reviewer → verify no regressions
```

**Security Issue:**
```
@security-expert → audit → identify vulnerabilities
  ├── @python-expert → implement fixes
  ├── @testing-expert → add security tests
  └── @code-reviewer → verify fixes
```

### Sample Commands

```
# Explore codebase before refactoring
@code-archaeologist analyze src/gui/main_window.py and produce a structure report

# Refactor large file
@python-expert split database.py into separate modules for GalleryCRUD and TabStore

# Review code
@code-reviewer review the credential storage implementation in src/utils/credential_helpers.py

# Optimize database
@performance-optimizer analyze and optimize slow queries in src/storage/database.py

# Increase test coverage
@testing-expert add pytest tests for src/storage/database.py to reach 80% coverage

# Generate documentation
@documentation-specialist create API documentation for src/core/engine.py
```

### Agent Selection Rules

1. **Prefer system-level agents** (`~/.claude/agents/awesome-claude-agents/`) over project-level
2. **Use Python specialists** for Python-specific tasks (python-expert, testing-expert, security-expert)
3. **Always start with code-archaeologist** for unfamiliar code areas
4. **Always end with code-reviewer** for quality assurance
5. **Use tech-lead-orchestrator** for multi-step features requiring coordination

---

**End of CLAUDE.md**
