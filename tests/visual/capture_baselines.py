#!/usr/bin/env python3
"""
Baseline Screenshot Capture Utility

Captures baseline screenshots for visual regression testing.
Run this script to generate/update all baseline images.

Usage:
    python tests/visual/capture_baselines.py [--theme light|dark|both]
"""

import sys
import argparse
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QProgressBar, QLabel, QPushButton, QMainWindow
from PyQt6.QtCore import Qt
from unittest.mock import Mock, MagicMock

from conftest import ScreenshotComparator, BASELINES_DIR


class MockMainWindow(QMainWindow):
    """Mock main window for ThemeManager.

    Provides all attributes and methods required by ThemeManager.apply_theme()
    and related theme management methods.
    """
    def __init__(self):
        super().__init__()
        # Theme state
        self._current_theme_mode = 'dark'
        self._current_font_size = 9

        # Mock settings with QSettings-like interface
        self.settings = MagicMock()
        self.settings.value = MagicMock(return_value=9)  # Default font size
        self.settings.setValue = MagicMock()

        # Mock gallery_table with nested table attribute
        self.gallery_table = MagicMock()
        self.gallery_table.viewport = MagicMock(return_value=MagicMock())
        self.gallery_table.rowHeight = MagicMock(return_value=60)
        self.gallery_table.update_theme = MagicMock()
        # Nested table widget for font size operations
        self.gallery_table.table = MagicMock()
        self.gallery_table.table.columnCount = MagicMock(return_value=10)
        self.gallery_table.table.horizontalHeaderItem = MagicMock(return_value=MagicMock())
        self.gallery_table.table.setFont = MagicMock()

        # Mock log_text widget for font operations
        self.log_text = MagicMock()
        self.log_text.setFont = MagicMock()

        # Mock theme toggle button
        self.theme_toggle_btn = MagicMock()
        self.theme_toggle_btn.setToolTip = MagicMock()

        # Mock theme menu actions
        self._theme_action_light = MagicMock()
        self._theme_action_light.setChecked = MagicMock()
        self._theme_action_dark = MagicMock()
        self._theme_action_dark.setChecked = MagicMock()

        # Legacy attributes
        self._rows_with_widgets = set()

    def _refresh_button_icons(self):
        """Mock method called after theme change to refresh button icons."""
        pass

    def refresh_all_status_icons(self):
        """Mock method called after theme change to refresh status icons."""
        pass

    def update_action_buttons_for_row(self, row):
        """Mock method for row-specific button updates."""
        pass


def capture_widget_baselines(theme_manager, comparator, theme: str):
    """Capture baseline screenshots for standard widgets."""
    print(f"\n[CAPTURE] Capturing {theme} theme baselines...")

    theme_manager.apply_theme(theme)
    QApplication.processEvents()

    # Progress bars
    print("  - Progress bars...")
    container = QWidget()
    layout = QVBoxLayout(container)
    for label_text, value in [("Empty", 0), ("25%", 25), ("50%", 50), ("75%", 75), ("Complete", 100)]:
        label = QLabel(label_text)
        progress = QProgressBar()
        progress.setRange(0, 100)
        progress.setValue(value)
        progress.setFixedWidth(300)
        layout.addWidget(label)
        layout.addWidget(progress)
    container.setFixedSize(350, 300)

    image = comparator.capture(container)
    path = BASELINES_DIR / theme / "progress_bars.png"
    comparator.save_image(image, path)
    print(f"    [OK] Saved: {path}")

    # Buttons
    print("  - Buttons...")
    container = QWidget()
    layout = QVBoxLayout(container)
    for text, class_name in [
        ("Default Button", None),
        ("Primary", "btn-primary"),
        ("Secondary", "btn-secondary"),
        ("Danger", "btn-shutdown-danger"),
        ("Success", "btn-shutdown-success"),
    ]:
        btn = QPushButton(text)
        btn.setFixedWidth(200)
        if class_name:
            btn.setProperty("class", class_name)
        layout.addWidget(btn)
    container.setFixedSize(250, 250)

    image = comparator.capture(container)
    path = BASELINES_DIR / theme / "buttons.png"
    comparator.save_image(image, path)
    print(f"    [OK] Saved: {path}")

    # Status labels
    print("  - Status labels...")
    container = QWidget()
    layout = QVBoxLayout(container)
    for text, class_name in [
        ("Success Status", "status-success"),
        ("Error Status", "status-error"),
        ("Warning Status", "status-warning"),
        ("Muted Text", "status-muted"),
        ("Bold Label", "label-bold"),
        ("Info Italic", "label-info-italic"),
    ]:
        label = QLabel(text)
        label.setProperty("class", class_name)
        layout.addWidget(label)
    container.setFixedSize(250, 200)

    image = comparator.capture(container)
    path = BASELINES_DIR / theme / "status_labels.png"
    comparator.save_image(image, path)
    print(f"    [OK] Saved: {path}")


def capture_dialog_baselines(theme_manager, comparator, theme: str):
    """Capture baseline screenshots for dialogs."""
    print(f"\n[CAPTURE] Capturing {theme} dialog baselines...")

    theme_manager.apply_theme(theme)
    QApplication.processEvents()

    # Help Dialog
    print("  - Help dialog...")
    try:
        from src.gui.dialogs.help_dialog import HelpDialog
        dialog = HelpDialog()
        dialog.resize(800, 600)
        QApplication.processEvents()

        image = comparator.capture(dialog)
        path = BASELINES_DIR / theme / "help_dialog.png"
        comparator.save_image(image, path)
        print(f"    [OK] Saved: {path}")
        dialog.close()
    except Exception as e:
        print(f"    [WARN] Skipped HelpDialog: {e}")

    # Statistics Dialog
    print("  - Statistics dialog...")
    try:
        from src.gui.dialogs.statistics_dialog import StatisticsDialog
        from unittest.mock import patch

        # Patch _load_stats (not _load_statistics) to prevent database access
        with patch.object(StatisticsDialog, '_load_stats', return_value=None):
            dialog = StatisticsDialog(parent=None)
            dialog.resize(600, 400)
            QApplication.processEvents()

            image = comparator.capture(dialog)
            path = BASELINES_DIR / theme / "statistics_dialog.png"
            comparator.save_image(image, path)
            print(f"    [OK] Saved: {path}")
            dialog.close()
    except Exception as e:
        print(f"    [WARN] Skipped StatisticsDialog: {e}")


def main():
    parser = argparse.ArgumentParser(description="Capture visual regression baselines")
    parser.add_argument(
        "--theme",
        choices=["light", "dark", "both"],
        default="both",
        help="Theme to capture (default: both)"
    )
    parser.add_argument(
        "--widgets-only",
        action="store_true",
        help="Only capture widget baselines (skip dialogs)"
    )
    args = parser.parse_args()

    # Create app
    app = QApplication.instance() or QApplication(sys.argv)

    # Create mock main window and theme manager
    mock_window = MockMainWindow()
    from src.gui.theme_manager import ThemeManager
    theme_manager = ThemeManager(mock_window)

    # Create comparator
    comparator = ScreenshotComparator()

    # Determine themes to capture
    themes = ["light", "dark"] if args.theme == "both" else [args.theme]

    print("=" * 50)
    print("Visual Regression Baseline Capture")
    print("=" * 50)

    for theme in themes:
        capture_widget_baselines(theme_manager, comparator, theme)
        if not args.widgets_only:
            capture_dialog_baselines(theme_manager, comparator, theme)

    print("\n" + "=" * 50)
    print("[DONE] Baseline capture complete!")
    print(f"   Baselines saved to: {BASELINES_DIR}")
    print("=" * 50)


if __name__ == "__main__":
    main()
