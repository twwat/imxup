#!/usr/bin/env python3
"""
pytest-qt tests for SplashScreen widget
Tests splash screen initialization, status updates, and visual elements
"""

import pytest
from unittest.mock import patch, MagicMock
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap, QColor

from src.gui.splash_screen import SplashScreen


class TestSplashScreenInit:
    """Test SplashScreen initialization and setup"""

    def test_splash_screen_creates_successfully(self, qtbot):
        """Test that SplashScreen can be instantiated"""
        with patch('imxup.get_project_root', return_value='/tmp/test'):
            with patch('imxup.get_version', return_value='1.0.0'):
                splash = SplashScreen()
                qtbot.addWidget(splash)

                assert splash is not None
                assert splash.isVisible() is False  # Not shown by default

    def test_splash_screen_has_correct_size(self, qtbot):
        """Test that splash screen has expected dimensions"""
        with patch('imxup.get_project_root', return_value='/tmp/test'):
            with patch('imxup.get_version', return_value='1.0.0'):
                splash = SplashScreen()
                qtbot.addWidget(splash)

                # Check expected size from __init__
                assert splash.pixmap().width() == 620
                assert splash.pixmap().height() == 405

    def test_splash_screen_initializes_with_version(self, qtbot):
        """Test version is properly initialized"""
        test_version = '2.5.3'
        with patch('imxup.get_project_root', return_value='/tmp/test'):
            with patch('imxup.get_version', return_value=test_version):
                splash = SplashScreen()
                qtbot.addWidget(splash)

                assert test_version in splash.version

    def test_splash_screen_has_status_text(self, qtbot):
        """Test that splash screen initializes with status text"""
        with patch('imxup.get_project_root', return_value='/tmp/test'):
            with patch('imxup.get_version', return_value='1.0.0'):
                splash = SplashScreen()
                qtbot.addWidget(splash)

                assert hasattr(splash, 'status_text')
                assert len(splash.status_text) > 0

    def test_splash_screen_has_action_words(self, qtbot):
        """Test that splash screen has action words list"""
        with patch('imxup.get_project_root', return_value='/tmp/test'):
            with patch('imxup.get_version', return_value='1.0.0'):
                splash = SplashScreen()
                qtbot.addWidget(splash)

                assert hasattr(splash, 'action_words')
                assert isinstance(splash.action_words, list)
                assert len(splash.action_words) > 0


class TestSplashScreenStatusUpdates:
    """Test SplashScreen status update functionality"""

    def test_update_status_changes_text(self, qtbot):
        """Test that update_status changes the status text"""
        with patch('imxup.get_project_root', return_value='/tmp/test'):
            with patch('imxup.get_version', return_value='1.0.0'):
                splash = SplashScreen()
                qtbot.addWidget(splash)

                initial_status = splash.status_text
                splash.update_status("Loading modules")
                qtbot.wait(100)

                assert splash.status_text != initial_status
                assert splash.status_text == "Loading modules"

    def test_update_status_adds_progress_dot(self, qtbot):
        """Test that update_status can add progress dots"""
        with patch('imxup.get_project_root', return_value='/tmp/test'):
            with patch('imxup.get_version', return_value='1.0.0'):
                splash = SplashScreen()
                qtbot.addWidget(splash)

                initial_dots = splash.progress_dots
                splash.update_status("random")  # Uses "random" keyword
                qtbot.wait(100)

                # Random status should add a dot
                assert len(splash.progress_dots) > len(initial_dots)

    def test_set_status_updates_text(self, qtbot):
        """Test set_status method"""
        with patch('imxup.get_project_root', return_value='/tmp/test'):
            with patch('imxup.get_version', return_value='1.0.0'):
                splash = SplashScreen()
                qtbot.addWidget(splash)

                splash.set_status("Initializing database")
                qtbot.wait(100)

                assert splash.status_text == "Initializing database..."

    def test_set_status_adds_progress_dot(self, qtbot):
        """Test that set_status adds a progress dot"""
        with patch('imxup.get_project_root', return_value='/tmp/test'):
            with patch('imxup.get_version', return_value='1.0.0'):
                splash = SplashScreen()
                qtbot.addWidget(splash)

                dots_before = len(splash.progress_dots)
                splash.set_status("Loading configuration")
                qtbot.wait(100)

                assert len(splash.progress_dots) == dots_before + 1

    def test_set_random_status(self, qtbot):
        """Test set_random_status method"""
        with patch('imxup.get_project_root', return_value='/tmp/test'):
            with patch('imxup.get_version', return_value='1.0.0'):
                splash = SplashScreen()
                qtbot.addWidget(splash)

                splash.set_random_status()
                qtbot.wait(100)

                # Should have one of the random statuses
                assert splash.status_text in splash.random_statuses


class TestSplashScreenLogoHandling:
    """Test logo loading and display"""

    def test_logo_loads_when_file_exists(self, qtbot, tmp_path):
        """Test that logo loads successfully when file exists"""
        # Create a minimal PNG file
        logo_path = tmp_path / 'assets' / 'imxup2.png'
        logo_path.parent.mkdir(parents=True, exist_ok=True)
        logo_path.write_bytes(
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01'
            b'\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89'
            b'\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01'
            b'\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
        )

        with patch('imxup.get_project_root', return_value=str(tmp_path)):
            with patch('imxup.get_version', return_value='1.0.0'):
                splash = SplashScreen()
                qtbot.addWidget(splash)

                assert splash.logo_pixmap is not None
                assert not splash.logo_pixmap.isNull()

    def test_logo_handles_missing_file(self, qtbot):
        """Test that splash handles missing logo file gracefully"""
        with patch('imxup.get_project_root', return_value='/nonexistent/path'):
            with patch('imxup.get_version', return_value='1.0.0'):
                splash = SplashScreen()
                qtbot.addWidget(splash)

                # Should handle missing logo gracefully
                assert splash.logo_pixmap is None or splash.logo_pixmap.isNull()


class TestSplashScreenVisibility:
    """Test splash screen visibility and closing"""

    def test_finish_and_hide_hides_splash(self, qtbot):
        """Test that finish_and_hide hides the splash screen"""
        with patch('imxup.get_project_root', return_value='/tmp/test'):
            with patch('imxup.get_version', return_value='1.0.0'):
                splash = SplashScreen()
                qtbot.addWidget(splash)

                splash.show()
                qtbot.wait(100)
                assert splash.isVisible()

                splash.finish_and_hide()
                qtbot.wait(100)
                assert not splash.isVisible()


class TestSplashScreenPainting:
    """Test splash screen painting and rendering"""

    def test_paint_event_executes_without_error(self, qtbot):
        """Test that paintEvent executes successfully"""
        with patch('imxup.get_project_root', return_value='/tmp/test'):
            with patch('imxup.get_version', return_value='1.0.0'):
                splash = SplashScreen()
                qtbot.addWidget(splash)

                # Trigger repaint
                splash.repaint()
                qtbot.wait(100)

                # If we get here without exception, paint succeeded
                assert True

    def test_paint_event_with_status_update(self, qtbot):
        """Test painting after status update"""
        with patch('imxup.get_project_root', return_value='/tmp/test'):
            with patch('imxup.get_version', return_value='1.0.0'):
                splash = SplashScreen()
                qtbot.addWidget(splash)

                splash.show()
                splash.update_status("Testing paint")
                qtbot.wait(100)

                # Should paint without error
                assert splash.status_text == "Testing paint"


class TestSplashScreenEdgeCases:
    """Test edge cases and error handling"""

    def test_multiple_status_updates_in_sequence(self, qtbot):
        """Test multiple rapid status updates"""
        with patch('imxup.get_project_root', return_value='/tmp/test'):
            with patch('imxup.get_version', return_value='1.0.0'):
                splash = SplashScreen()
                qtbot.addWidget(splash)

                for i in range(10):
                    splash.set_status(f"Step {i}")
                    qtbot.wait(10)

                assert "Step 9" in splash.status_text

    def test_empty_status_text(self, qtbot):
        """Test handling of empty status text"""
        with patch('imxup.get_project_root', return_value='/tmp/test'):
            with patch('imxup.get_version', return_value='1.0.0'):
                splash = SplashScreen()
                qtbot.addWidget(splash)

                splash.update_status("")
                qtbot.wait(100)

                assert splash.status_text == ""

    def test_very_long_status_text(self, qtbot):
        """Test handling of very long status text"""
        with patch('imxup.get_project_root', return_value='/tmp/test'):
            with patch('imxup.get_version', return_value='1.0.0'):
                splash = SplashScreen()
                qtbot.addWidget(splash)

                long_text = "A" * 200
                splash.update_status(long_text)
                qtbot.wait(100)

                assert splash.status_text == long_text


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
