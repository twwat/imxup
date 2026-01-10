# Changelog

All notable changes to IMXuploader will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [0.7.2] - 2026-01-10

v0.7.2: Performance optimization, modular theming, design tokens

### Performance
- **Optimize deferred widget creation**: 16-32 seconds → ~1 second (17-32x faster)
  - Viewport-first loading: visible rows (~25) created in ~50ms
  - Batch repaints with setUpdatesEnabled(False): 1144 repaints → ~11
  - Pause update_timer during batch operation
  - Reduce processEvents frequency from every 20 to every 100 rows
- Optimize selection handler to avoid O(N²) complexity

### Added
- Design tokens system for consistent theming
- Modular QSS loader with token injection
- Session length and timeframe filter to Statistics dialog
- get_hosts_for_period() for per-host statistics filtering
- Visual regression testing infrastructure
- Widget creation timing benchmark (tests/performance/)
- Comprehensive STYLING_GUIDE.md

### Changed
- Migrate inline styles to property-based QSS
- Split monolithic QSS into modular architecture
- Enhance ImageStatusDialog with ProportionalBar

### Fixed
- Improve scanner cleanup in GalleryFileManagerDialog

### Assets
- Add scan icons
- Update Keep2Share logo

### Tests
- Add visual regression testing infrastructure
- Add Statistics dialog enhancement tests
- Refactor test infrastructure and update fixtures

## [0.7.1] - 2026-01-07

v0.7.1: Statistics dialog, IMX status scanner performance, comprehensive tests

### Added:
- Statistics dialog (Tools > Statistics) with session/upload/scanner metrics
  - Two-tab interface: General stats and File Hosts breakdown
  - Tracks app startups, first startup timestamp, total time open
  - Shows upload totals, fastest speed record with timestamp
  - Displays per-host file upload statistics from MetricsStore
- Add Statistics button to adaptive quick settings panel
- Add session time tracking (accumulated across app launches)
- Add format_duration() support for days (e.g., "2d 5h 30m")

### Performance:
- Fix massive UI freeze in ImageStatusDialog (50+ seconds → instant)
  - Disable ResizeToContents during batch table updates
  - Block signals and suspend sorting during bulk operations
- Optimize ImageStatusChecker with batch preprocessing
  - Single batch query replaces O(n) per-path queries
  - O(1) path-to-row lookup via pre-built index
  - Batch database writes via bulk_update_gallery_imx_status()
- Add quick count feature showing "Found: X images" within 2-3 seconds

### Thread Safety:
- Add threading.Lock to ImageStatusChecker for shared state protection
- Fix race condition with _cancelled flag preventing stale results
- Improve dialog cleanup timing (signals remain connected during checks)

### UI/UX:
- Add animated spinner to ImageStatusDialog (4-state dot animation)
- Add theme-aware status colors (green/amber/red) for online status
- Add NumericTableItem for proper numeric sorting in tables
- Add StatusColorDelegate preserving colors on row selection
- Simplify status display to single word (Online/Partial/Offline)
- Remove detailed offline URL tree view (cleaner presentation)
- Update worker status widget with clickable icon buttons
- Optimize host logos (reduced file sizes)

### Other Fixes:
- Fix is_dark_mode() using correct QSettings organization name
- Fix fastest_kbps_timestamp not being saved when record set
- Fix QSettings namespace consistency (ImxUploader/Stats)
- Fix test expectations for non-breaking space in format functions

### Tests:
- Add test_statistics_dialog.py (29 tests, 99% coverage)
- Add test_image_status_checker.py (956 lines)
- Add test_image_status_dialog.py (717 lines)
- Add test_rename_worker_status_check.py (1,358 lines)
- Update test_format_utils.py with NBSP constant and days tests
- Total: ~3,400 new lines of test code

### Refactoring:
- Extract format_duration() to format_utils.py (DRY principle)
- Reorganize rename_worker.py structure
- Standardize button labels in adaptive settings panel
- Apply code formatting pass to custom_widgets.py

## [00.6.15] - 2025-12-29~

### Changed
- Extracted ThemeManager from main_window.py
- Extracted SettingsManager from main_window.py
- Extracted TableRowManager from main_window.py
- Extracted GalleryQueueController from main_window.py

### Performance
- Cached QSettings to reduce disk I/O
- O(1) row lookup instead of O(n) iteration
- Schema initialization runs once per database

## [0.6.13] - 2025-12-26

### Added
- Help dialog with comprehensive documentation
- Emoji PNG support for templates
- Quick settings improvements

### Changed
- Optimized theme switching speed

### Fixed
- Help dialog performance issues

## [0.6.12] - 2025-12-25

### Added
- Worker logo setting in worker status widget
- ArtifactHandler extraction for cleaner artifact management

### Changed
- Refactored worker table for better maintainability

## [0.6.11] - 2025-12-24

### Fixed
- Thread-safety issues in ImageStatusChecker
- Worker lifecycle management improvements

### Changed
- Extracted WorkerSignalHandler from main_window.py
- Wired up progress_tracker.py and removed duplicates from main_window.py

## [0.6.10] - 2025-12-23

### Added
- Feature to check online status of images on imx.to
- Image availability verification

## [0.6.09] - 2025-12-19

### Fixed
- Upload Workers queue display issues
- Event-driven updates for worker status

## [0.6.08] - 2025-12-17

### Added
- Per-host BBCode formatting support
- Advanced Settings tab in settings dialog

## [0.6.07] - 2025-12-15

### Security
- Added SSL/TLS certificate verification to FileHostClient

### Fixed
- Thread-safe cookie caching
- GUI log display settings
- Worker table scroll behavior
- RenameWorker authentication issues

### Changed
- Renamed gallery_id to db_id for clarity and consistency
- Centralized file host icon loading with security validation
- Added comprehensive docstrings to main_window.py

## [0.6.06] - 2025-12-15

### Fixed
- Worker count initialization
- Optimized INI file operations (reduced from 11 to 1 operation)
- File host worker initialization location in imxup.py
- Removed duplicate init_enabled_hosts() call

## [0.6.05] - 2025-12-11

### Added
- Worker status auto-disabled icons
- Upload timing logs
- Live queue metrics in worker status widget
- Storage display in worker status widget

### Fixed
- Metrics persistence issues
- Auto-regenerate BBcode after file host uploads complete
- File host icons for disabled hosts
- Enable/disable state change handling for file hosts

### Performance
- Skip file host icon refresh during startup (prevented 48-second freeze)

## [0.6.02] - 2025-11-26

### Fixed
- Critical 20+ minute GUI freeze from table rebuilds and deadlock
- Main thread blocking during file host upload completion
- Initialization order for worker_status_widget and FileHostWorkerManager
- GUI freeze issues
- Metrics display issues
- Files column display

### Changed
- Removed debug logging spam from icon management
- Merged feature/file-host-progress-tracking into master

## [0.6.00] - 2025-11-09

### Added
- Multi-host file upload system with 6 provider integrations
  - Fileboom (fboom.me)
  - Keep2Share (k2s.cc)
  - TezFiles (tezfiles.com)
  - Rapidgator (rapidgator.net)
  - Filedot (filedot.to)
  - Filespace (filespace.com)
- ZIP compression support for file hosts
- Token management for API-based hosts

### Fixed
- Thread safety for multi-threaded uploads

## [0.5.12] - 2025-10-27

### Added
- Adaptive Settings Panel
- External Hooks system (pre/post-upload, on-complete, on-error)
- System enhancements for hook execution

### Changed
- Complete widget extraction refactoring
- Fixed CSS typo
- Resolved signal blocking bugs

## [0.5.10] - 2025-10-23

### Added
- Multi-host uploader integration
- Template conditionals for BBCode
- Credential migration system
- External app hooks system

## [0.5.07] - 2025-10-20

### Added
- Animated upload status icons
- Gallery removal system refactoring

### Changed
- Major storage architecture refactor
- Unified path resolution through get_base_path()
- Removed hardcoded ~/.imxup references
- Support for portable/custom storage modes
- Removed obsolete migration system and legacy configuration handling

## [0.5.05] - 2025-10-19

### Added
- ZIP archive extraction support
- pycurl upload engine for improved performance
- Bandwidth tracking improvements

### Changed
- Table UI refinements

## [0.5.03] - 2025-10-16

### Added
- Theme toggle button
- Enhanced icon system

### Changed
- Improved startup performance
- Windows build improvements
- UI polish refinements

## [0.5.01] - 2025-10-15

### Added
- PyInstaller support for Windows builds

### Changed
- Major type safety improvements
- UI improvements
- Code organization refactoring

## [0.5.00] - 2025-10-09

### Added
- Comprehensive logging system overhaul
- Advanced image sampling system

### Changed
- Major UI improvements
- Refactored database operations

### Fixed
- Renamed column showing incorrect status for pending galleries
- Critical gallery_id reuse bug by clearing session cookies
- Critical row verification bug
- Critical table corruption bugs causing duplicate rows and stale mappings

## [0.4.0] - 2025-10-05

### Added
- Auto-clear feature for completed galleries

### Changed
- Refactored RenameWorker to use independent session
- Eliminated uploader dependency from RenameWorker
- Cleaned up dependencies

## [0.3.13] - 2025-10-04

### Added
- User-Agent header to all HTTP requests with platform information
- Standalone log viewer popup option in View menu
- Tab tooltip updates after drag-drop and queue operations

### Changed
- Standardized log message levels and prefixes across CLI and GUI modules
- Refactored load_user_defaults() for cleaner fallback handling
- Reduced debug noise
- Improved upload file logging with per-image timing and success messages
- Cleaned up icon manager debug output and timestamp formatting

### Fixed
- Timer shutdown warnings
- Upload concurrency improvements

## [0.3.2] - 2025-08-31

### Added
- Multi-folder selection in Browse dialog
- Configurable timeouts for uploads

### Changed
- Improved upload reliability
- Better error logging

### Fixed
- Upload failures with improved timeout handling

## [0.3.0] - 2025-08-28

### Added
- Comprehensive theming system with dark mode icons
- Dark theme icon variants for all UI states
- Centralized styles.qss for styling

### Changed
- Refactored main_window.py: extracted dialogs
- Simplified UI architecture
- Major refactoring to eliminate code duplication
- Enhanced theme loading with proper light/dark theme section parsing
- Consolidated theme-aware styling across all GUI components

### Fixed
- UI layout issues

## [0.2.0] - 2025-08-25

### Added
- Icon management system
- Enhanced upload functionality
- System tab enhancements

### Changed
- Major UI/UX improvements
- Architecture enhancements
- Refactored codebase for better modularity and maintainability
- Reduced main GUI file from 10,685 to 9,012 lines (15.6% reduction)
- Extracted modules: TableProgressWidget, GalleryQueueItem, QueueManager

## [0.1.0] - 2025-08-15

### Added
- Initial GUI implementation with PyQt6
- Splash screen
- Comprehensive Settings Dialog
- Tab management functionality
- Gallery table with context menu operations
- Cookie caching for Firefox
- Auto-archive functionality
- Background task handling
- Completion processing worker
- Non-blocking dialog handling
- Unsaved changes management

---

## Version History Summary

| Version | Date | Highlights |
|---------|------|------------|
| 0.7.1  | 2026-01-07 | Statistics, thread safety, performance | 
| 0.6.13 | 2025-12-26 | Help dialog, emoji PNG support, quick settings |
| 0.6.12 | 2025-12-25 | Worker table refactor, ArtifactHandler, worker logos |
| 0.6.11 | 2025-12-24 | Thread-safety fixes, worker lifecycle improvements |
| 0.6.10 | 2025-12-23 | Image online status checking |
| 0.6.09 | 2025-12-19 | Worker queue display fixes |
| 0.6.08 | 2025-12-17 | Per-host BBCode, Advanced Settings |
| 0.6.07 | 2025-12-15 | SSL/TLS verification, security improvements |
| 0.6.06 | 2025-12-15 | INI optimization, initialization fixes |
| 0.6.05 | 2025-12-11 | Worker status improvements, startup optimization |
| 0.6.02 | 2025-11-26 | Critical GUI freeze fixes |
| 0.6.00 | 2025-11-09 | Multi-host file upload (6 providers) |
| 0.5.12 | 2025-10-27 | Adaptive Settings, External Hooks |
| 0.5.10 | 2025-10-23 | Template conditionals, credential migration |
| 0.5.07 | 2025-10-20 | Animated icons, storage refactor |
| 0.5.05 | 2025-10-19 | ZIP extraction, pycurl engine |
| 0.5.03 | 2025-10-16 | Theme toggle, startup performance |
| 0.5.01 | 2025-10-15 | PyInstaller, type safety |
| 0.5.00 | 2025-10-09 | Logging overhaul, image sampling |
| 0.4.0 | 2025-10-05 | Auto-clear, RenameWorker refactor |
| 0.3.13 | 2025-10-04 | Logging improvements, User-Agent |
| 0.3.2 | 2025-08-31 | Multi-folder selection, timeouts |
| 0.3.0 | 2025-08-28 | Dark mode theming, dialog extraction |
| 0.2.0 | 2025-08-25 | Modular architecture, UI/UX |
| 0.1.0 | 2025-08-15 | Initial release |
