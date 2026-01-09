#!/usr/bin/env python3
"""
pytest-qt tests for custom widgets
Tests TableProgressWidget, ActionButtonWidget, and OverallProgressWidget
"""

import pytest
from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt

from src.gui.widgets.custom_widgets import TableProgressWidget, ActionButtonWidget, OverallProgressWidget


class TestTableProgressWidget:
    """Test TableProgressWidget functionality"""

    def test_table_progress_widget_creates(self, qtbot):
        """Test TableProgressWidget instantiation"""
        widget = TableProgressWidget()
        qtbot.addWidget(widget)

        assert widget is not None
        assert hasattr(widget, 'progress_bar')

    def test_set_value(self, qtbot):
        """Test setting progress value"""
        widget = TableProgressWidget()
        qtbot.addWidget(widget)

        widget.set_progress(50)
        qtbot.wait(100)

        assert widget.progress == 50

    def test_set_text(self, qtbot):
        """Test setting progress text"""
        widget = TableProgressWidget()
        qtbot.addWidget(widget)

        widget.set_progress(25, "Uploading...")
        qtbot.wait(100)

        assert "Uploading" in widget.status_text


class TestOverallProgressWidget:
    """Test OverallProgressWidget functionality"""

    def test_overall_progress_widget_creates(self, qtbot):
        """Test OverallProgressWidget instantiation"""
        widget = OverallProgressWidget()
        qtbot.addWidget(widget)

        assert widget is not None

    def test_set_value_updates_progress(self, qtbot):
        """Test setting value updates the progress bar"""
        widget = OverallProgressWidget()
        qtbot.addWidget(widget)

        widget.setValue(75)
        qtbot.wait(100)

        assert widget.progress_bar.value() == 75


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
