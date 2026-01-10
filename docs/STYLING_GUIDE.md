# IMXuploader Styling Guide

**Version:** 1.0.0
**Last Updated:** 2025-01-09

This guide documents the modular QSS styling system used in IMXuploader, including design tokens, theme support, and best practices for adding new styles.

---

## Table of Contents

1. [Overview](#overview)
2. [Directory Structure](#directory-structure)
3. [Design Tokens](#design-tokens)
4. [Adding New Styles](#adding-new-styles)
5. [Theme Support](#theme-support)
6. [Best Practices](#best-practices)
7. [Examples](#examples)
8. [Troubleshooting](#troubleshooting)

---

## Overview

IMXuploader uses a **modular QSS styling system** with three key components:

1. **Design Tokens** (`tokens.json`) - Centralized color and spacing definitions
2. **Modular QSS Files** - Split by component type for maintainability
3. **ThemeManager** - Handles theme switching, token injection, and stylesheet caching

### Architecture

```
ThemeManager.apply_theme(mode)
       |
       v
+------------------+
| 1. Load base.qss |  (theme-independent sizing, fonts)
+------------------+
       |
       v
+----------------------+
| 2. Load components/* |  (base styles from each component)
+----------------------+
       |
       v
+------------------------+
| 3. Load themes/{mode}  |  (dark.qss or light.qss)
+------------------------+
       |
       v
+----------------------+
| 4. Apply tokens      |  (replace $token.path variables)
+----------------------+
       |
       v
+----------------------+
| 5. Set QPalette      |  (ColorRole definitions)
+----------------------+
       |
       v
+----------------------+
| 6. Apply stylesheet  |  (QApplication.setStyleSheet)
+----------------------+
```

### Key Files

| File | Purpose |
|------|---------|
| `src/gui/theme_manager.py` | Theme switching, token injection, QSS loading |
| `assets/tokens.json` | Design token definitions |
| `assets/styles/base.qss` | Theme-independent base styles |
| `assets/styles/themes/dark.qss` | Dark theme color overrides |
| `assets/styles/themes/light.qss` | Light theme color overrides |
| `assets/styles/components/*.qss` | Component-specific styles |

---

## Directory Structure

```
assets/
├── tokens.json                    # Design token definitions
├── styles.qss                     # Legacy monolithic stylesheet (fallback)
└── styles/
    ├── base.qss                   # Theme-independent base styles
    ├── components/
    │   ├── buttons.qss            # Button styling
    │   ├── forms.qss              # Form controls (inputs, checkboxes)
    │   ├── labels.qss             # Labels, status text, info panels
    │   ├── menus.qss              # Menu bar and context menus
    │   ├── progress.qss           # Progress bars
    │   ├── tabs.qss               # Tab widgets
    │   └── tables.qss             # Table widgets, headers
    └── themes/
        ├── dark.qss               # Dark theme colors
        └── light.qss              # Light theme colors
```

### Load Order

Components are loaded in this order (defined in `theme_manager.py`):

```python
COMPONENT_FILES = [
    'buttons.qss',
    'tables.qss',
    'forms.qss',
    'progress.qss',
    'tabs.qss',
    'menus.qss',
    'labels.qss',
]
```

### File Organization Rules

1. **base.qss** - Only theme-independent styles (sizing, fonts, margins)
2. **components/*.qss** - Can contain both base styles AND theme-specific sections
3. **themes/*.qss** - Only color and appearance overrides

Component files may contain theme markers:
```css
/* Base styles here (no theme markers) */
QPushButton[class="icon-btn"] { background-color: transparent; }

/* LIGHT_THEME_START */
/* Light-specific styles */
/* LIGHT_THEME_END */

/* DARK_THEME_START */
/* Dark-specific styles */
/* DARK_THEME_END */
```

---

## Design Tokens

Design tokens provide a centralized source of truth for colors, typography, and spacing.

### Token File Location

```
assets/tokens.json
```

### Token Categories

| Category | Example Path | Description |
|----------|--------------|-------------|
| `colors` | `$colors.dark.background.primary` | Theme-specific colors |
| `typography` | `$typography.fontSize.base` | Font sizes and families |
| `spacing` | `$spacing.md` | Padding and margin values |
| `borderRadius` | `$borderRadius.lg` | Border radius values |

### Token Syntax

Use `$` prefix with dot notation in QSS files:

```css
/* Full path with theme */
background-color: $colors.dark.background.primary;

/* Theme auto-inserted (converts to $colors.{current_theme}.status.success) */
color: $colors.status.success;
```

### Available Color Tokens

```
colors.{light|dark}
├── background
│   ├── primary      # Main background
│   ├── secondary    # Panel/group backgrounds
│   ├── tertiary     # Subtle backgrounds
│   ├── input        # Input field backgrounds
│   ├── hover        # Hover state backgrounds
│   ├── selected     # Selected item backgrounds
│   ├── disabled     # Disabled element backgrounds
│   └── tooltip      # Tooltip backgrounds
├── text
│   ├── primary      # Main text color
│   ├── secondary    # Secondary/muted text
│   ├── muted        # De-emphasized text
│   ├── disabled     # Disabled text
│   ├── inverse      # Text on dark/light backgrounds
│   └── tooltip      # Tooltip text
├── border
│   ├── default      # Standard borders
│   ├── light        # Subtle borders
│   ├── input        # Input field borders
│   ├── focus        # Focus state borders
│   ├── hover        # Hover state borders
│   └── disabled     # Disabled borders
├── accent
│   ├── primary      # Primary accent (links, buttons)
│   ├── secondary    # Secondary accent
│   ├── hover        # Accent hover state
│   └── highlight    # Selection highlight
├── status
│   ├── success      # Success state
│   ├── success_light
│   ├── success_border
│   ├── error        # Error state
│   ├── error_light
│   ├── error_border
│   ├── warning      # Warning state
│   ├── warning_light
│   ├── warning_border
│   ├── info         # Info state
│   └── info_light
├── progress
│   ├── completed, completed_border
│   ├── failed, failed_border
│   ├── uploading, uploading_border
│   ├── incomplete, incomplete_border
│   ├── ready, ready_border
│   └── default, default_border
├── table
│   ├── background
│   ├── alternate
│   ├── gridline
│   ├── header
│   └── header_border
├── button
│   ├── background, text, border
│   ├── hover_bg, hover_border
├── tab
│   ├── inactive_bg, inactive_text
│   ├── active_bg, active_text
│   └── border
├── menu
│   ├── background, text, border
│   ├── selected_bg, selected_text
├── scrollbar
│   ├── background
│   ├── handle
│   └── handle_hover
├── branding
│   └── title        # Brand color for titles
└── worker
    ├── retry        # Worker retry status
    └── error        # Worker error status
```

### Adding New Tokens

1. Edit `assets/tokens.json`
2. Add the token under the appropriate category
3. Define values for both `light` and `dark` themes

```json
{
  "colors": {
    "light": {
      "myCategory": {
        "newColor": "#ff0000"
      }
    },
    "dark": {
      "myCategory": {
        "newColor": "#ff6666"
      }
    }
  }
}
```

4. Use in QSS:
```css
QLabel[class="my-label"] { color: $colors.myCategory.newColor; }
```

---

## Adding New Styles

### Step 1: Choose Selector Type

| Selector Type | When to Use | Example |
|---------------|-------------|---------|
| `class` property | Static classification | `QLabel[class="status-success"]` |
| Custom property | Dynamic state changes | `QProgressBar[status="uploading"]` |
| Object name | Single unique widget | `QLineEdit#commandPreview` |
| Type only | Default styling | `QPushButton { }` |

### Step 2: Define the QSS Class

Add styles to the appropriate component file:

```css
/* In assets/styles/components/labels.qss */

/* LIGHT_THEME_START */
QLabel[class="my-new-label"] {
    color: $colors.light.text.primary;
    font-weight: bold;
}
/* LIGHT_THEME_END */

/* DARK_THEME_START */
QLabel[class="my-new-label"] {
    color: $colors.dark.text.primary;
    font-weight: bold;
}
/* DARK_THEME_END */
```

### Step 3: Apply in Python Code

```python
from PyQt6.QtWidgets import QLabel

# Create widget and set class property
label = QLabel("My Label")
label.setProperty("class", "my-new-label")
```

### Step 4: Update Style After Property Changes

When changing properties dynamically, you MUST refresh the widget's style:

```python
# Change property
widget.setProperty("status", "success")

# Refresh style (REQUIRED for property changes to take effect)
widget.style().unpolish(widget)
widget.style().polish(widget)
```

### Property-Based Selectors for Dynamic States

For widgets that change state at runtime, use property selectors:

**QSS:**
```css
QProgressBar[status="completed"]::chunk { background-color: $colors.dark.progress.completed; }
QProgressBar[status="failed"]::chunk { background-color: $colors.dark.progress.failed; }
QProgressBar[status="uploading"]::chunk { background-color: $colors.dark.progress.uploading; }
```

**Python:**
```python
def update_progress_status(progress_bar, status):
    """Update progress bar status and refresh styling."""
    progress_bar.setProperty("status", status)
    progress_bar.style().unpolish(progress_bar)
    progress_bar.style().polish(progress_bar)
```

---

## Theme Support

### How Themes Work

IMXuploader supports two themes: **dark** (default) and **light**.

Theme switching involves:
1. Loading theme-specific QSS
2. Setting QPalette ColorRoles
3. Applying the combined stylesheet
4. Refreshing icons and status indicators

### QPalette ColorRoles

The ThemeManager sets these palette roles for each theme:

| ColorRole | Dark Theme | Light Theme |
|-----------|------------|-------------|
| Window | #1e1e1e | #ffffff |
| WindowText | #e6e6e6 | #212121 |
| Base | #191919 | #ffffff |
| Text | #e6e6e6 | #212121 |
| Button | #2d2d2d | #f5f5f5 |
| ButtonText | #e6e6e6 | #212121 |
| Highlight | #2f6aa0 | #2980b9 |
| HighlightedText | #ffffff | #ffffff |
| PlaceholderText | #808080 | #808080 |
| Link | #50a0dc | #2980b9 |
| AlternateBase | #262626 | #f5f5f5 |
| ToolTipBase | #333333 | #ffffcc |
| ToolTipText | #e6e6e6 | #333333 |

### Theme-Specific QSS Files

**`themes/dark.qss`** - Dark theme colors:
```css
QWidget { color: #d0d0d0; }
QTableWidget {
    background-color: $colors.dark.background.primary;
    color: $colors.dark.text.primary;
}
```

**`themes/light.qss`** - Light theme colors:
```css
QWidget { color: $colors.light.text.primary; }
QTableWidget {
    background-color: $colors.light.background.primary;
    color: #222222;
}
```

### Checking Current Theme in Code

```python
from src.gui.theme_manager import is_dark_mode

if is_dark_mode():
    # Dark theme logic
else:
    # Light theme logic
```

### Getting Theme-Aware Colors

```python
from src.gui.theme_manager import get_online_status_colors

colors = get_online_status_colors()  # Auto-detects theme
# colors['online'] -> QColor for online status
# colors['partial'] -> QColor for partial status
# colors['offline'] -> QColor for offline status
```

### ThemeManager API

```python
# Get the ThemeManager instance
theme_manager = main_window.theme_manager

# Toggle between themes
theme_manager.toggle_theme()

# Set specific theme
theme_manager.set_theme_mode('dark')  # or 'light'

# Apply theme (internal use, called by set_theme_mode)
theme_manager.apply_theme('dark')

# Apply font size
theme_manager.apply_font_size(10)  # points
```

---

## Best Practices

### 1. Prefer QSS Classes Over Inline Styles

**Good:**
```python
label.setProperty("class", "status-success")
```

**Avoid:**
```python
label.setStyleSheet("color: green; font-weight: bold;")
```

**Why:** QSS classes are theme-aware and maintainable.

### 2. Use Semantic Class Names

**Good:**
```css
QLabel[class="status-success"] { }
QLabel[class="status-error"] { }
QPushButton[class="main-action-btn"] { }
```

**Avoid:**
```css
QLabel[class="green-bold-text"] { }
QPushButton[class="big-blue-button"] { }
```

**Why:** Semantic names describe purpose, not appearance.

### 3. Keep Dynamic Styles Minimal

Only use `setProperty()` + `unpolish()`/`polish()` when state changes at runtime:

```python
# Only when status actually changes
if new_status != current_status:
    widget.setProperty("status", new_status)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
```

### 4. Test Both Themes

Always verify styles work in both dark and light modes:

```python
# Quick theme toggle for testing
theme_manager.set_theme_mode('light')
# ... verify appearance ...
theme_manager.set_theme_mode('dark')
# ... verify appearance ...
```

### 5. Use Design Tokens for Colors

**Good:**
```css
color: $colors.status.success;
```

**Avoid:**
```css
color: #4caf50;
```

**Why:** Tokens ensure consistency and make theme updates easier.

### 6. Organize by Component

Place styles in the appropriate component file:
- Button styles -> `buttons.qss`
- Table styles -> `tables.qss`
- Label/text styles -> `labels.qss`

### 7. Comment Complex Selectors

```css
/* Progress bars inside table cells - status-based coloring */
QTableWidget QProgressBar[status="completed"]::chunk {
    background-color: $colors.dark.progress.completed;
}
```

---

## Examples

### Example 1: Status Label with Dynamic State

**QSS (`labels.qss`):**
```css
/* LIGHT_THEME_START */
QLabel[status="running"]  { color: $colors.light.status.info; }
QLabel[status="success"]  { color: $colors.light.status.success; font-weight: bold; }
QLabel[status="failure"]  { color: $colors.light.status.error; font-weight: bold; }
QLabel[status="skipped"]  { color: #999; }
/* LIGHT_THEME_END */

/* DARK_THEME_START */
QLabel[status="running"]  { color: $colors.dark.status.info; }
QLabel[status="success"]  { color: $colors.dark.status.success; font-weight: bold; }
QLabel[status="failure"]  { color: $colors.dark.status.error_light; font-weight: bold; }
QLabel[status="skipped"]  { color: #666; }
/* DARK_THEME_END */
```

**Python:**
```python
def update_test_status(status_label: QLabel, status: str, message: str = ""):
    """Update a test status label with the appropriate styling.

    Args:
        status_label: The QLabel to update
        status: One of 'running', 'success', 'failure', 'skipped'
        message: Optional status message
    """
    status_label.setText(message or status.capitalize())
    status_label.setProperty("status", status)

    # Reapply stylesheet to pick up property change
    status_label.style().unpolish(status_label)
    status_label.style().polish(status_label)
```

### Example 2: Button with Class-Based Styling

**QSS (`buttons.qss`):**
```css
/* Base styling (theme-independent) */
QPushButton[class="main-action-btn"] {
    min-height: 22px;
    max-height: 28px;
    font-weight: 700;
    margin: 1px 6px;
    font-size: 13px;
}

/* LIGHT_THEME_START */
QPushButton[class="main-action-btn"] { color: $colors.light.text.secondary; }
QPushButton[class="main-action-btn"]:hover {
    background-color: $colors.light.accent.hover;
    border: 1px solid $colors.light.border.hover;
}
QPushButton[class="main-action-btn"]:disabled {
    color: $colors.light.text.muted;
    font-style: italic;
}
/* LIGHT_THEME_END */

/* DARK_THEME_START */
QPushButton[class="main-action-btn"] { color: $colors.dark.button.text; }
QPushButton[class="main-action-btn"]:hover {
    background-color: $colors.dark.accent.hover;
    border: 1px solid $colors.dark.accent.primary;
}
/* DARK_THEME_END */
```

**Python:**
```python
# Create and style the button
start_btn = QPushButton("Start All")
start_btn.setProperty("class", "main-action-btn")
start_btn.clicked.connect(self.start_all_uploads)
```

### Example 3: Progress Bar with Status-Based Colors

**QSS (`progress.qss`):**
```css
/* Base styling */
QProgressBar {
    border-radius: 6px;
    text-align: center;
    font-size: 9px;
    font-weight: bold;
}

/* DARK_THEME_START */
QProgressBar[status="completed"]::chunk { background-color: $colors.dark.progress.completed; }
QProgressBar[status="failed"]::chunk { background-color: $colors.dark.progress.failed; }
QProgressBar[status="uploading"]::chunk { background-color: $colors.dark.progress.uploading; }
/* DARK_THEME_END */
```

**Python:**
```python
class ProgressCellWidget(QWidget):
    """Widget containing a progress bar for table cells."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        # ... layout setup ...

    def set_status(self, status: str):
        """Update progress bar status styling.

        Args:
            status: One of 'completed', 'failed', 'uploading',
                   'incomplete', 'ready', or empty string
        """
        self.progress_bar.setProperty("status", status)
        style = self.progress_bar.style()
        if style is not None:
            style.polish(self.progress_bar)
```

### Example 4: Storage Bar with Capacity Levels

**QSS (`progress.qss`):**
```css
/* Storage progress bars - plenty of space (green) */
QProgressBar[storage_status="plenty"]::chunk {
    background-color: $colors.dark.progress.completed;
}

/* Storage progress bars - medium space (blue) */
QProgressBar[storage_status="medium"]::chunk {
    background-color: $colors.dark.progress.uploading;
}

/* Storage progress bars - low space (red) */
QProgressBar[storage_status="low"]::chunk {
    background-color: $colors.dark.progress.failed;
}
```

**Python:**
```python
def update_storage_bar(storage_bar: QProgressBar, used: int, total: int):
    """Update storage bar with capacity-based styling."""
    if total <= 0:
        storage_bar.setProperty("storage_status", "unknown")
        storage_bar.setValue(0)
    else:
        percent_used = (used / total) * 100
        storage_bar.setValue(int(percent_used))

        # Set status based on remaining capacity
        percent_free = 100 - percent_used
        if percent_free > 30:
            storage_bar.setProperty("storage_status", "plenty")
        elif percent_free > 10:
            storage_bar.setProperty("storage_status", "medium")
        else:
            storage_bar.setProperty("storage_status", "low")

    # Refresh styling
    storage_bar.style().unpolish(storage_bar)
    storage_bar.style().polish(storage_bar)
```

---

## Troubleshooting

### Style Not Applying

**Problem:** Widget style doesn't change after setting property.

**Solution:** Call `unpolish()` then `polish()`:
```python
widget.setProperty("status", "success")
widget.style().unpolish(widget)
widget.style().polish(widget)
```

### Token Not Found Warning

**Problem:** Log shows "Missing design token: $colors.mytoken"

**Solution:**
1. Check token path spelling in QSS
2. Verify token exists in `tokens.json`
3. Ensure theme prefix is correct (`light` or `dark`)

### Theme Switch Not Updating Widget

**Problem:** Widget keeps old theme colors after switching.

**Solution:** Ensure the widget uses QSS classes, not inline styles:
```python
# Wrong - inline style won't update on theme change
label.setStyleSheet("color: #ff0000;")

# Right - QSS class updates automatically
label.setProperty("class", "status-error")
```

### Fallback to Legacy Stylesheet

**Problem:** Log shows "Using legacy styles.qss"

**Solution:**
1. Verify `assets/styles/base.qss` exists
2. Verify `assets/styles/themes/dark.qss` exists
3. Check file permissions

### Performance Issues on Theme Switch

**Problem:** UI freezes briefly when switching themes.

**Solution:** ThemeManager already implements:
- Stylesheet caching
- Deferred icon refresh via `QTimer.singleShot()`
- `setUpdatesEnabled(False)` during switch

If still slow, check for custom `update_theme()` methods doing heavy work.

---

## Quick Reference Card

### Setting a Class

```python
widget.setProperty("class", "my-class")
```

### Dynamic Property Update

```python
widget.setProperty("status", "new-value")
widget.style().unpolish(widget)
widget.style().polish(widget)
```

### QSS Token Syntax

```css
color: $colors.status.success;           /* Theme auto-detected */
color: $colors.dark.status.success;      /* Explicit dark theme */
font-size: $typography.fontSize.base;    /* Typography token */
padding: $spacing.md;                    /* Spacing token */
border-radius: $borderRadius.lg;         /* Border radius token */
```

### Common Status Classes

```python
# Labels
"status-success", "status-error", "status-warning", "status-info"
"status-muted", "status-disabled"

# Buttons
"main-action-btn", "quick-settings-btn", "icon-btn"

# Progress
status="completed", status="failed", status="uploading"
```

---

## See Also

- `src/gui/theme_manager.py` - ThemeManager implementation
- `assets/tokens.json` - Token definitions
- `docs/user/guides/theme-customization.md` - User-facing theme documentation

---

**End of STYLING_GUIDE.md**
