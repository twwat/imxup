"""
Visual Regression Testing Fixtures

Provides screenshot capture, comparison, and baseline management for PyQt6 widgets.
"""

import pytest
from pathlib import Path
from typing import Optional, Tuple
import hashlib

from PyQt6.QtWidgets import QWidget, QApplication
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QImage, QPainter

# Directories
VISUAL_DIR = Path(__file__).parent
BASELINES_DIR = VISUAL_DIR / "baselines"
DIFFS_DIR = VISUAL_DIR / "diffs"


class ScreenshotComparator:
    """Captures and compares widget screenshots."""

    def __init__(self, threshold: float = 0.01):
        """
        Args:
            threshold: Maximum allowed pixel difference ratio (0.01 = 1%)
        """
        self.threshold = threshold
        self.last_diff_path: Optional[Path] = None
        self.last_diff_ratio: float = 0.0

    def capture(self, widget: QWidget) -> QImage:
        """Capture a widget as QImage."""
        # Ensure widget is shown and rendered
        widget.show()
        QApplication.processEvents()

        # Grab the widget
        pixmap = widget.grab()
        return pixmap.toImage()

    def save_image(self, image: QImage, path: Path) -> None:
        """Save QImage to file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(str(path), "PNG")

    def load_image(self, path: Path) -> Optional[QImage]:
        """Load image from file."""
        if not path.exists():
            return None
        image = QImage()
        if image.load(str(path)):
            return image
        return None

    def compare(self, image1: QImage, image2: QImage) -> Tuple[bool, float, Optional[QImage]]:
        """
        Compare two images pixel-by-pixel.

        Returns:
            Tuple of (match, diff_ratio, diff_image)
            - match: True if images are within threshold
            - diff_ratio: Ratio of different pixels (0.0 to 1.0)
            - diff_image: Visual diff image (different pixels highlighted in red)
        """
        # Handle size mismatch
        if image1.size() != image2.size():
            return False, 1.0, None

        width = image1.width()
        height = image1.height()
        total_pixels = width * height

        if total_pixels == 0:
            return True, 0.0, None

        # Create diff image
        diff_image = QImage(width, height, QImage.Format.Format_ARGB32)
        diff_image.fill(Qt.GlobalColor.transparent)

        different_pixels = 0

        for y in range(height):
            for x in range(width):
                pixel1 = image1.pixel(x, y)
                pixel2 = image2.pixel(x, y)

                if pixel1 != pixel2:
                    different_pixels += 1
                    # Mark different pixel in red
                    diff_image.setPixel(x, y, 0xFFFF0000)
                else:
                    # Copy original pixel with reduced opacity
                    diff_image.setPixel(x, y, (pixel1 & 0x00FFFFFF) | 0x40000000)

        diff_ratio = different_pixels / total_pixels
        match = diff_ratio <= self.threshold

        self.last_diff_ratio = diff_ratio

        return match, diff_ratio, diff_image

    def compare_to_baseline(
        self,
        widget: QWidget,
        name: str,
        theme: str = "light"
    ) -> Tuple[bool, str]:
        """
        Compare widget screenshot to baseline.

        Args:
            widget: Widget to capture
            name: Test name (e.g., "main_window", "settings_dialog")
            theme: Theme name ("light" or "dark")

        Returns:
            Tuple of (passed, message)
        """
        baseline_path = BASELINES_DIR / theme / f"{name}.png"

        # Capture current state
        current = self.capture(widget)

        # Load baseline
        baseline = self.load_image(baseline_path)

        if baseline is None:
            # No baseline - save current as new baseline
            self.save_image(current, baseline_path)
            return True, f"Created new baseline: {baseline_path}"

        # Compare
        match, diff_ratio, diff_image = self.compare(baseline, current)

        if match:
            return True, f"Match (diff: {diff_ratio*100:.2f}%)"

        # Save diff and current for inspection
        diff_path = DIFFS_DIR / theme / f"{name}_diff.png"
        current_path = DIFFS_DIR / theme / f"{name}_current.png"

        if diff_image:
            self.save_image(diff_image, diff_path)
        self.save_image(current, current_path)
        self.last_diff_path = diff_path

        return False, (
            f"Visual regression detected!\n"
            f"  Diff ratio: {diff_ratio*100:.2f}% (threshold: {self.threshold*100:.2f}%)\n"
            f"  Baseline: {baseline_path}\n"
            f"  Current: {current_path}\n"
            f"  Diff: {diff_path}"
        )


@pytest.fixture
def screenshot_comparator():
    """Fixture providing screenshot comparison utilities."""
    return ScreenshotComparator(threshold=0.01)


@pytest.fixture
def capture_baseline(screenshot_comparator):
    """Fixture for capturing new baselines (use in baseline capture mode)."""
    def _capture(widget: QWidget, name: str, theme: str = "light"):
        image = screenshot_comparator.capture(widget)
        path = BASELINES_DIR / theme / f"{name}.png"
        screenshot_comparator.save_image(image, path)
        return path
    return _capture


@pytest.fixture
def assert_visual_match(screenshot_comparator):
    """Fixture for asserting visual match against baseline."""
    def _assert(widget: QWidget, name: str, theme: str = "light"):
        passed, message = screenshot_comparator.compare_to_baseline(widget, name, theme)
        assert passed, message
        return message
    return _assert


def get_baseline_hash(name: str, theme: str = "light") -> Optional[str]:
    """Get hash of baseline image for change detection."""
    path = BASELINES_DIR / theme / f"{name}.png"
    if not path.exists():
        return None
    return hashlib.md5(path.read_bytes()).hexdigest()
