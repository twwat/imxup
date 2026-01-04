# Theme Customization Guide

## Quick Reference

**Version:** v0.6.16
**Feature:** Dark/light theme support with system detection
**Supported Themes:** Dark, Light, Auto (system-aware)
**Customization:** Font sizes, color schemes, icon themes
**Use Case:** Adapt IMXuploader to your working environment

---

## What is Theme Customization?

IMXuploader includes a professional theming system that allows you to customize the application's appearance. This guide covers how to switch themes, adjust font sizes, and troubleshoot display issues.

The theming system provides:
- **Dark Mode** - Eye-friendly dark interface (recommended for evening work)
- **Light Mode** - Traditional light interface (bright environments)
- **Auto Mode** - Automatic system detection (Windows 11 & modern Linux)
- **Font Scaling** - Adjust text size throughout the application

---

## Available Themes

### Dark Theme

Dark theme features a dark background with light text, designed to reduce eye strain during extended use.

**Color Scheme:**
- Background: `#1e1e1e` (dark gray)
- Text: `#e6e6e6` (light gray)
- Buttons: `#2d2d2d` (darker gray)
- Selection: `#2f5f9f` (blue highlight)
- Icons: Optimized for dark backgrounds

**Best For:**
- Evening and night work
- Reduced eye strain
- Low-light environments
- Professional workflows

---

### Light Theme

Light theme uses a traditional white background with dark text for clear visibility in bright environments.

**Color Scheme:**
- Background: `#ffffff` (white)
- Text: `#333333` (dark gray)
- Buttons: `#f0f0f0` (light gray)
- Selection: `#3399ff` (blue highlight)
- Icons: Optimized for light backgrounds

**Best For:**
- Daytime use
- Bright office environments
- Printing documentation
- Traditional workflows

---

### Auto Theme (System Detection)

Auto mode automatically detects your system theme setting and applies the matching theme.

**Platform Support:**
- **Windows 11** - Reads Registry setting automatically
- **Windows 10** - May require manual selection
- **Linux (modern)** - Detects GNOME, KDE, or Xfce theme preference
- **macOS** - System appearance detection

**How It Works:**
1. Application starts and checks system settings
2. Auto-selects dark or light theme accordingly
3. Follows system theme changes if OS supports it
4. Falls back to dark theme if detection fails

---

## Switching Themes

### Method 1: View Menu

**Steps:**
1. Click **View** menu in menu bar
2. Select **Themes**
3. Choose from:
   - **Dark Theme**
   - **Light Theme**
   - **Auto (System)**

**Menu Location:**
```
File  Edit  View  Tools  Help
              └─ Themes
                  ├─ Dark Theme
                  ├─ Light Theme
                  └─ Auto (System)
```

### Method 2: Settings Dialog

**Steps:**
1. Press **Ctrl+,** or go to **File -> Settings**
2. Click **General** tab
3. Under "Appearance," find **Theme**
4. Select desired theme from dropdown
5. Click **Save**

**Changes apply immediately** - no restart needed.

### Method 3: Theme Toggle Button

The theme toggle button in the toolbar provides quick switching:

1. Look for the theme icon (usually sun/moon symbol) in the top toolbar
2. Click to switch between dark and light
3. Tooltip shows next theme when you hover

---

## Theme Components

When you switch themes, the following elements update automatically:

### Window & Backgrounds
- Main window background
- Table backgrounds
- Dialog backgrounds
- Menu backgrounds

### Text & Labels
- Gallery names and text
- Status messages
- Button text
- Log viewer text

### Interface Elements
- Progress bars (fill colors)
- Table row highlighting
- Button borders and hover states
- Dialog borders and frames

### Icons & Graphics
- Status icons (queued, uploading, completed, failed)
- File host logos
- Action buttons (start, pause, stop)
- Navigation tabs

### Dialogs & Menus
- Settings dialog styling
- Context menus appearance
- Tooltips background/text
- Input fields borders

---

## Font Size Adjustment

Font sizes can be adjusted independently from theme selection.

### Accessing Font Size Settings

**Via Settings Dialog:**
1. Press **Ctrl+,** to open Settings
2. Click **General** tab
3. Find **Font Size** slider or input
4. Current options: 8pt to 14pt (default: 9pt)
5. Click **Save**

**Changes Apply To:**
- Gallery table rows
- Column headers (slightly smaller)
- Log viewer text
- Dialog text
- Labels throughout interface

### Font Size Recommendations

| Size | Best For | Notes |
|------|----------|-------|
| **8pt** | High-resolution displays | Very compact, requires good eyesight |
| **9pt** | Standard displays | Default, balanced |
| **10pt** | 1080p monitors | Slightly larger, easier to read |
| **11pt** | 1440p+ displays | Large text, spacious layout |
| **12pt** | TV/projector display | Very large, for distance viewing |

**Tip:** If table rows appear cramped, increase font size to 10pt or 11pt.

---

## Theme Persistence

Theme settings are **automatically saved** in your configuration:

**Windows:**
```
Registry: HKEY_CURRENT_USER\Software\ImxUploader\ImxUploadGUI
Settings: ui/theme (value: "dark", "light", or "auto")
```

**Linux:**
```
File: ~/.config/ImxUploader/ImxUploadGUI.conf
Settings: ui/theme=dark
```

**Persistence Features:**
- Theme preference saved on switch
- Font size saved with every change
- Settings restored when application starts
- Survives application restart and updates

---

## Platform Notes

### Windows 11

**Auto Theme Support:** Full support
- Application reads Windows Settings
- Automatically detects dark/light preference
- Updates when system theme changes (if supported)
- No manual action needed

**Dark Theme Look:**
- Matches Windows 11 dark mode
- Compatible with system taskbar theme
- Icons refresh for dark backgrounds

**Light Theme Look:**
- Matches Windows 11 light mode
- Clean white interface
- Consistent with system dialogs

### Windows 10

**Auto Theme Support:** Limited
- May not auto-detect system theme
- Recommend manual selection (dark/light)
- No dynamic system theme following

**Workaround:**
If auto theme shows incorrect theme, manually select dark or light in View > Themes.

### Linux (Ubuntu, Fedora, etc.)

**Auto Theme Support:** Partial (depends on desktop)
- **GNOME**: Full support (auto-detects)
- **KDE**: Full support (auto-detects)
- **Xfce**: Partial (may need manual selection)
- **Other DEs**: May default to dark theme

**Manual Override:**
If auto-detect doesn't match your system theme, manually select dark or light.

---

## Troubleshooting

### Theme Not Applying

**Problem:** Theme appears not to change when selected

**Solutions:**

1. **Check theme selection**
   - View > Themes to confirm selection
   - Look at menu to see checkmark next to active theme

2. **Restart application**
   - Close IMXuploader completely
   - Wait 2 seconds
   - Reopen application
   - Check if theme persisted

3. **Verify settings save**
   - Open Settings (Ctrl+,)
   - Change theme
   - Click "Save" button
   - Confirm dialog closes successfully

4. **Clear settings cache** (if nothing works)
   - Close application
   - Delete: `~/.imxup/imxup.ini` (Linux) or Registry keys (Windows)
   - Restart application
   - Theme will reset to default (dark)

### Theme Looks Different from Expected

**Problem:** Theme colors don't match screenshots or descriptions

**Possible Causes:**

1. **System settings override**
   - Windows: Check Windows Settings > Personalization > Colors
   - Linux: Check system theme in Settings
   - May conflict with IMXuploader theme

2. **High Contrast mode enabled**
   - Windows: Settings > Ease of Access > High Contrast
   - Temporarily disable to test
   - IMXuploader themes designed for standard contrast

3. **Display color profile**
   - Monitor calibration affects appearance
   - Test on another monitor if available
   - Check display settings for "color temperature"

### Icons Appear Wrong in Theme

**Problem:** Icons are too dark/light for selected theme

**Solutions:**

1. **Verify theme is actually applied**
   - View > Themes should show checkmark
   - Window background should match theme (dark/light)

2. **Refresh icon cache**
   - Close application
   - Delete: `~/.imxup/.icon_cache/` (if exists)
   - Restart application
   - Icons will regenerate with correct theme

3. **Check icon files exist**
   - Icons should be in: `assets/hosts/logo/` and `assets/` directory
   - If files missing, application falls back to placeholder icons
   - Try reinstalling IMXuploader to restore icon files

### Text Too Small or Too Large

**Problem:** Font size doesn't match what you set

**Solutions:**

1. **Check font size in Settings**
   - Ctrl+, > General tab
   - Verify font size slider is at desired position
   - Confirm "Save" was clicked

2. **Verify system DPI settings**
   - Windows: Settings > Display > Scale and Layout
   - Standard DPI is 100% - if set higher, text appears larger
   - IMXuploader font size + Windows DPI = final size

3. **Reset to defaults**
   - In Settings, look for "Reset to Defaults" button
   - Will restore default font size (9pt)

### Theme Flicker or Flickering on Startup

**Problem:** Theme flickers or shows wrong theme briefly when starting

**Causes:**
- Normal on slower systems
- Application loads default theme, then applies saved preference
- Takes 1-2 seconds on most systems

**Workaround:**
- Increase startup speed by closing other applications
- Clear log viewer to reduce memory usage (Ctrl+L > Clear)
- Try lighter theme (light theme loads faster than dark on some systems)

---

## Best Practices

### For Dark Theme Users

1. **Enable Auto-Scroll in Log Viewer**
   - Settings > Logging > Auto-scroll
   - Prevents needing to scroll manually

2. **Use 9-10pt Font Size**
   - Default 9pt is optimal for dark theme
   - Larger fonts (11pt+) may look odd on dark backgrounds

3. **Enable Tray Icon**
   - Settings > General > Show system tray icon
   - Allows minimizing to tray in dark theme

### For Light Theme Users

1. **Consider Font Size 10pt**
   - Light theme with 9pt can feel cramped
   - 10pt provides better spacing

2. **Use in Bright Environments**
   - Light theme designed for bright daylight
   - May cause eye strain in dark rooms

3. **Monitor Contrast Settings**
   - Light theme relies on contrast
   - Ensure monitor brightness is moderate (not too dim)

### For Auto Theme Users

1. **Verify System Detection Works**
   - Switch your system to dark/light theme
   - Check if IMXuploader follows (requires app restart)
   - If not, manually select dark or light

2. **Consistent Environment**
   - If you switch system themes frequently, use manual selection
   - Auto theme only checks on startup

---

## Keyboard Shortcuts

**Theme Control (when available):**
- **Ctrl+Shift+T** - Toggle between dark and light theme (if configured)
- **Ctrl+,** - Open Settings to adjust theme

No dedicated keyboard shortcut exists for theme toggle by default. If needed, use the View menu or Settings dialog.

---

## See Also

- [GUI Guide](./gui-guide.md) - Complete IMXuploader interface walkthrough
- [Keyboard Shortcuts](../getting-started/keyboard-shortcuts.md) - All keyboard shortcuts
- [FEATURES.md](../reference/FEATURES.md) - Full feature documentation
- [Troubleshooting](../troubleshooting/troubleshooting.md) - Common issues and solutions

---

**Version:** 0.6.16
**Last Updated:** 2026-01-03
