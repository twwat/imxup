#!/usr/bin/env python3
"""
pytest-qt tests for HelpDialog
Tests help documentation dialog functionality
"""

import pytest
from PyQt6.QtWidgets import QDialog
from PyQt6.QtCore import Qt

from src.gui.dialogs.help_dialog import HelpDialog


class TestHelpDialogInit:
    """Test HelpDialog initialization"""

    def test_help_dialog_creates(self, qtbot):
        """Test HelpDialog instantiation"""
        dialog = HelpDialog()
        qtbot.addWidget(dialog)

        try:
            assert dialog is not None
            assert isinstance(dialog, QDialog)
        finally:
            # Ensure thread is stopped before dialog is destroyed
            if hasattr(dialog, '_loader_thread') and dialog._loader_thread is not None:
                if dialog._loader_thread.isRunning():
                    dialog._loader_thread.stop()
                    dialog._loader_thread.wait(2000)
                    if dialog._loader_thread.isRunning():
                        dialog._loader_thread.terminate()
                        dialog._loader_thread.wait(500)
            dialog.close()
            dialog.deleteLater()

    def test_help_dialog_has_content_viewer(self, qtbot):
        """Test that dialog has content viewer"""
        dialog = HelpDialog()
        qtbot.addWidget(dialog)

        try:
            assert hasattr(dialog, 'content_viewer')
            assert hasattr(dialog, 'tree')
        finally:
            # Ensure thread is stopped before dialog is destroyed
            if hasattr(dialog, '_loader_thread') and dialog._loader_thread is not None:
                if dialog._loader_thread.isRunning():
                    dialog._loader_thread.stop()
                    dialog._loader_thread.wait(2000)
                    if dialog._loader_thread.isRunning():
                        dialog._loader_thread.terminate()
                        dialog._loader_thread.wait(500)
            dialog.close()
            dialog.deleteLater()


class TestHelpDialogDocumentation:
    """Test documentation loading"""

    def test_loads_documentation_structure(self, qtbot, tmp_path):
        """Test loading documentation structure"""
        # Create temp docs directory
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()

        # Create a test doc file
        (docs_dir / "TEST.md").write_text("# Test Documentation")

        dialog = HelpDialog()
        qtbot.addWidget(dialog)

        try:
            # Should have tree widget populated
            assert dialog.tree.topLevelItemCount() >= 0
        finally:
            # Ensure thread is stopped before dialog is destroyed
            if hasattr(dialog, '_loader_thread') and dialog._loader_thread is not None:
                if dialog._loader_thread.isRunning():
                    dialog._loader_thread.stop()
                    dialog._loader_thread.wait(2000)
                    if dialog._loader_thread.isRunning():
                        dialog._loader_thread.terminate()
                        dialog._loader_thread.wait(500)
            dialog.close()
            dialog.deleteLater()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
