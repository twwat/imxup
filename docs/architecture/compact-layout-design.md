# File Hosts Compact Layout - Architecture Design

**Design Goal**: Display each file host in a single compact row with all essential information visible at a glance.

## Current Layout Analysis

### Current Structure (Multi-row per host)
```
QFrame (host container)
├── QVBoxLayout (vertical stacking)
│   ├── Row 1: Status icon + Hostname + Logo + Test status
│   ├── Row 2: "Storage:" label + Progress bar
│   ├── Row 3: Enable/Disable + Configure buttons
│   └── Row 4: "Auto-upload:" label + trigger value
```

**Problems**:
- Uses 4 separate rows per host (excessive vertical space)
- Storage label redundant ("Storage:")
- Test results verbose ("✓ All tests passed (12/24 15:30)")
- Logo placement inconsistent (centered with stretches)

## Proposed Compact Layout

### New Structure (Single row per host)
```
QFrame (host container, height: 40-50px)
└── QHBoxLayout (horizontal single-line)
    ├── Status Icon (20x20)           # Green/red circle
    ├── Hostname (flex)                # "RapidGator", "Keep2Share", etc.
    ├── Configure Button (80px)        # "Configure"
    ├── Host Logo (24px height)        # PNG image, centered
    ├── Compact Storage Bar (150px)    # Progress bar only, no label
    └── Status Label (flex)            # "Ready", "Uploading", "⚠ No auth"
```

### Layout Measurements
- **Total height per host**: 40-50px (vs current ~120px)
- **Status icon**: 20x20px fixed
- **Hostname**: Minimum 100px, expands to fit
- **Configure button**: 80px fixed width
- **Host logo**: 24px height (auto width maintaining aspect ratio)
- **Storage bar**: 150px fixed width × 16px height
- **Status label**: Minimum 80px, expands to fit

## Qt Layout Implementation

### 1. Main Container
```python
host_frame = QFrame()
host_frame.setFrameShape(QFrame.Shape.StyledPanel)
host_frame.setMaximumHeight(50)  # Enforce compact height
host_frame.setMinimumHeight(40)

main_layout = QHBoxLayout(host_frame)
main_layout.setContentsMargins(8, 4, 8, 4)  # Tighter margins
main_layout.setSpacing(8)  # Consistent spacing between elements
```

### 2. Widget Hierarchy & Sizing Policies

#### Status Icon (Fixed)
```python
status_icon = QLabel()
status_icon.setFixedSize(20, 20)
status_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
# No size policy needed - fixed size
main_layout.addWidget(status_icon)
```

#### Hostname (Expanding)
```python
host_label = QLabel(host_config.name)
host_label.setMinimumWidth(100)
host_label.setSizePolicy(
    QSizePolicy.Policy.Expanding,  # Horizontal: expand to available space
    QSizePolicy.Policy.Fixed       # Vertical: fixed height
)
main_layout.addWidget(host_label, 1)  # Stretch factor 1
```

#### Configure Button (Fixed)
```python
configure_btn = QPushButton("Configure")
configure_btn.setFixedWidth(80)
configure_btn.setMaximumHeight(30)
# No size policy needed - fixed size
main_layout.addWidget(configure_btn)
```

#### Host Logo (Fixed Height, Auto Width)
```python
logo_label = QLabel()
logo_pixmap = QPixmap(logo_path).scaledToHeight(24, Qt.TransformationMode.SmoothTransformation)
logo_label.setPixmap(logo_pixmap)
logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
# Size automatically determined by pixmap
main_layout.addWidget(logo_label)
```

#### Compact Storage Bar (Fixed)
```python
storage_bar = QProgressBar()
storage_bar.setFixedSize(150, 16)  # Compact bar
storage_bar.setTextVisible(True)
storage_bar.setFormat("%p%")  # Show only percentage
storage_bar.setProperty("class", "storage-bar-compact")
# No size policy needed - fixed size
main_layout.addWidget(storage_bar)
```

#### Status Label (Expanding)
```python
status_label = QLabel()
status_label.setMinimumWidth(80)
status_label.setSizePolicy(
    QSizePolicy.Policy.Expanding,  # Horizontal: expand to available space
    QSizePolicy.Policy.Fixed       # Vertical: fixed height
)
main_layout.addWidget(status_label, 1)  # Stretch factor 1
```

## Storage Bar Optimization

### Current Implementation (Verbose)
- Label: "Storage:" (fixed 80px)
- Bar format: "15.2 GB / 20.0 GB free (76%)" (too long)
- Height: 16px
- Total width: ~280px (80px label + 200px bar)

### New Compact Design
- **No label** - bar is self-explanatory
- **Simplified format**: "76%" or "15.2/20 GB" (alternates based on space)
- **Height**: 16px (unchanged)
- **Fixed width**: 150px
- **Total savings**: 130px horizontal space

### Format Logic
```python
def format_storage_compact(left: int, total: int, width: int) -> str:
    """Return compact format based on available width."""
    percent = int((left / total) * 100) if total > 0 else 0

    if width < 120:
        return f"{percent}%"  # Percentage only
    else:
        left_str = format_binary_size(left)
        total_str = format_binary_size(total)
        return f"{left_str}/{total_str}"  # Short format
```

## Status Display Transformation

### Current Test Results Display
```
"✓ All tests passed (12/24 15:30)"          # Success
"⚠ 2/4 tests passed (12/24 15:30)"          # Partial
"⚠ Test failed - retest needed"             # Failed
"⚠ Requires credentials"                    # Not configured
"✓ No auth required"                        # No auth needed
```

### New Compact Status Display
```
"Ready"              # All tests passed, host is operational
"Uploading"          # Active upload in progress
"⚠ Auth needed"      # Requires credentials
"⚠ Tests failed"     # Test validation failed
"Disabled"           # Host is disabled
"✓ No auth"          # No authentication required
```

### Status Logic
```python
def get_compact_status(host_id: str, host_config: HostConfig, is_enabled: bool) -> tuple[str, str]:
    """
    Returns: (status_text, css_class)
    """
    if not is_enabled:
        return ("Disabled", "status-disabled")

    if not host_config.requires_auth:
        return ("✓ No auth", "status-success-light")

    # Check test results from cache
    test_results = load_test_results_from_settings(host_id)
    if not test_results:
        return ("⚠ Auth needed", "status-warning-light")

    tests_passed = sum([
        test_results['credentials_valid'],
        test_results['user_info_valid'],
        test_results['upload_success'],
        test_results['delete_success']
    ])

    if tests_passed == 4:
        # Check if actively uploading (requires worker integration)
        return ("Ready", "status-success")
    elif tests_passed > 0:
        return ("⚠ Tests partial", "status-warning")
    else:
        return ("⚠ Tests failed", "status-error")
```

## Enable/Disable Button Removal

**Rationale**: The Enable/Disable button is redundant in the compact layout. Users can:
1. Enable/disable hosts in the Configure dialog
2. See enabled state via the status icon (green/red circle)
3. Configure all settings in one place (Configure dialog)

**Benefits**:
- Saves 80-100px horizontal space
- Simplifies interaction (one-click Configure vs two-click Enable→Configure)
- Reduces visual clutter

## Auto-Upload Trigger Removal

**Rationale**: Auto-upload trigger is an advanced setting that:
- Most users leave on default ("On Completed")
- Doesn't need to be visible at a glance
- Can be configured in the Configure dialog
- Saves 120-150px vertical space per host

**Alternative**: Show trigger in Configure dialog only, or as tooltip on hover.

## Space Savings Summary

### Per-Host Savings
- **Vertical space**: 70-80px saved (4 rows → 1 row)
  - Row 1 (top): 24px
  - Row 2 (storage): 20px
  - Row 3 (buttons): 36px
  - Row 4 (auto-upload): 20px
  - Total current: ~100px
  - New compact: ~45px
  - **Savings: 55px per host**

- **Horizontal space**: More efficient use
  - Removed "Storage:" label: 80px
  - Removed Enable/Disable button: 80px
  - Compact storage bar: 150px vs 200px (50px saved)
  - **Total horizontal savings: 210px per host**

### Global Savings (6 hosts)
- **Vertical**: 330px saved (can fit 3-4 more hosts in same space)
- **Horizontal**: Better information density

## CSS Styling Enhancements

### New QSS Classes Needed

```css
/* Compact host frame */
QFrame[class="host-frame-compact"] {
    max-height: 50px;
    min-height: 40px;
    border: 1px solid #404040;
    border-radius: 4px;
    background-color: #2b2b2b;
}

/* Compact storage bar */
QProgressBar[class="storage-bar-compact"] {
    height: 16px;
    width: 150px;
    border: 1px solid #404040;
    border-radius: 3px;
    text-align: center;
}

/* Status labels with semantic colors */
QLabel[class="status-success"] { color: #4ade80; }      /* Green - Ready */
QLabel[class="status-warning"] { color: #fbbf24; }      /* Yellow - Partial */
QLabel[class="status-error"] { color: #f87171; }        /* Red - Failed */
QLabel[class="status-disabled"] { color: #6b7280; }     /* Gray - Disabled */
QLabel[class="status-success-light"] { color: #86efac; } /* Light green - No auth */
QLabel[class="status-warning-light"] { color: #fde047; } /* Light yellow - Auth needed */
```

## Implementation Strategy

### Phase 1: Layout Restructuring
1. Change `QVBoxLayout` to `QHBoxLayout` in `_create_host_row()`
2. Remove row-by-row structure, add all widgets to single layout
3. Set fixed heights on host frame (40-50px)
4. Apply size policies to widgets

### Phase 2: Storage Bar Optimization
1. Remove "Storage:" label widget
2. Change storage bar width to 150px
3. Update format string to show only percentage
4. Add tooltip for detailed info (hover shows full "15.2 GB / 20.0 GB free")

### Phase 3: Status Display Simplification
1. Implement `get_compact_status()` helper
2. Update `_update_status_label()` to use compact format
3. Remove timestamp from status text
4. Add tooltip for full test results (hover shows timestamp and details)

### Phase 4: Button Reorganization
1. Remove Enable/Disable button from main layout
2. Keep Configure button in compact layout
3. Move enable/disable to Configure dialog only

### Phase 5: Auto-Upload Trigger Removal
1. Remove auto-upload display row
2. Keep trigger configuration in Configure dialog
3. Add tooltip to hostname showing trigger setting

## Backwards Compatibility

### Settings Storage
- No changes to QSettings structure
- No changes to INI file structure
- Only UI layout changes

### Worker Integration
- No changes to worker signals
- Status updates work same way
- Storage updates work same way

## Testing Checklist

- [ ] All 6 hosts display correctly in single row
- [ ] Status icons show correct enabled/disabled state
- [ ] Configure button opens dialog correctly
- [ ] Host logos display at correct size (24px height)
- [ ] Storage bar updates correctly from worker
- [ ] Storage bar shows percentage or size based on width
- [ ] Status label updates correctly (Ready/Uploading/etc)
- [ ] Tooltips show detailed info on hover
- [ ] Frame height stays within 40-50px
- [ ] Layout adapts to window resize correctly
- [ ] Theme switching works correctly (dark/light mode)
- [ ] Scrollable area works correctly (vertical scroll only)

## Future Enhancements

### Phase 2 (Optional)
1. **Upload progress integration**: Show "Uploading 3/5" in status when active
2. **Tooltip rich info**: Hover shows last test timestamp, storage details, trigger setting
3. **Quick enable toggle**: Checkbox overlay on status icon for quick enable/disable
4. **Sortable hosts**: Drag-and-drop to reorder hosts in list
5. **Collapsible groups**: Group hosts by status (Active, Disabled, Needs Config)

## Architecture Decision Record

**Decision**: Single-row horizontal layout with compact storage bar and simplified status

**Rationale**:
- Users need to see multiple hosts at a glance
- Current 4-row layout wastes vertical space
- Storage details and test results are secondary info (can be in tooltips)
- Configure dialog is the primary interaction point

**Trade-offs**:
- **Pros**: 55px vertical space saved per host, cleaner visual hierarchy, faster scanning
- **Cons**: Less detailed info at a glance (mitigated by tooltips), slightly wider minimum window width

**Alternatives Considered**:
1. **2-row layout** (status+controls, storage+trigger): Still too tall, saves only 20px per host
2. **Collapsible rows**: Adds complexity, users must click to expand
3. **Tabbed interface**: Hides hosts from view, requires tab switching

**Status**: Approved for implementation

---

**Document Version**: 1.0
**Last Updated**: 2025-11-13
**Author**: System Architecture Designer
**Review Status**: Ready for Implementation
