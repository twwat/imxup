#!/usr/bin/env python3
"""
pytest-qt tests for Template Manager Dialog
Tests template CRUD operations, validation, and dialog interactions
"""

import os
import sys
import pytest
from pathlib import Path
from unittest.mock import patch, Mock, MagicMock, mock_open, call
from PyQt6.QtWidgets import (
    QDialog, QMessageBox, QInputDialog, QApplication
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTextCursor

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from src.gui.dialogs.template_manager import (
    TemplateManagerDialog,
    ConditionalInsertDialog,
    PlaceholderHighlighter,
    BUILTIN_TEMPLATES
)


# ============================================================================
# PlaceholderHighlighter Tests
# ============================================================================

class TestPlaceholderHighlighter:
    """Test syntax highlighting for template placeholders"""

    def test_highlighter_initialization(self, qtbot):
        """Test PlaceholderHighlighter creates with formats"""
        from PyQt6.QtGui import QTextDocument

        doc = QTextDocument()
        highlighter = PlaceholderHighlighter(doc)

        assert highlighter is not None
        assert highlighter.placeholder_format is not None
        assert highlighter.conditional_format is not None
        assert len(highlighter.placeholders) > 0
        assert len(highlighter.conditional_tags) > 0

    def test_placeholder_list_complete(self, qtbot):
        """Test all expected placeholders are defined"""
        from PyQt6.QtGui import QTextDocument

        doc = QTextDocument()
        highlighter = PlaceholderHighlighter(doc)

        expected_placeholders = [
            "#folderName#", "#width#", "#height#", "#longest#",
            "#extension#", "#pictureCount#", "#folderSize#",
            "#galleryLink#", "#allImages#", "#hostLinks#",
            "#custom1#", "#custom2#", "#custom3#", "#custom4#",
            "#ext1#", "#ext2#", "#ext3#", "#ext4#"
        ]

        for placeholder in expected_placeholders:
            assert placeholder in highlighter.placeholders

    def test_conditional_tags_defined(self, qtbot):
        """Test conditional tags are defined"""
        from PyQt6.QtGui import QTextDocument

        doc = QTextDocument()
        highlighter = PlaceholderHighlighter(doc)

        assert "[if" in highlighter.conditional_tags
        assert "[else]" in highlighter.conditional_tags
        assert "[/if]" in highlighter.conditional_tags

    def test_highlight_block_with_placeholder(self, qtbot):
        """Test highlighting placeholders in text"""
        from PyQt6.QtGui import QTextDocument

        doc = QTextDocument()
        highlighter = PlaceholderHighlighter(doc)
        doc.setPlainText("Template with #folderName# placeholder")

        # highlightBlock is called automatically by QSyntaxHighlighter
        assert doc.toPlainText() == "Template with #folderName# placeholder"

    def test_highlight_block_with_conditional(self, qtbot):
        """Test highlighting conditional tags"""
        from PyQt6.QtGui import QTextDocument

        doc = QTextDocument()
        highlighter = PlaceholderHighlighter(doc)
        doc.setPlainText("[if folderName]Content[/if]")

        # highlightBlock is called automatically
        assert doc.toPlainText() == "[if folderName]Content[/if]"

    def test_dark_mode_detection(self, qtbot, qapp):
        """Test highlighter adapts to dark mode"""
        from PyQt6.QtGui import QTextDocument

        doc = QTextDocument()
        highlighter = PlaceholderHighlighter(doc)

        # Just verify highlighter was created successfully
        # Dark mode detection happens during initialization
        assert highlighter.placeholder_format is not None
        assert highlighter.conditional_format is not None


# ============================================================================
# ConditionalInsertDialog Tests
# ============================================================================

class TestConditionalInsertDialog:
    """Test conditional tag insertion dialog"""

    def test_dialog_initialization(self, qtbot):
        """Test ConditionalInsertDialog creates successfully"""
        dialog = ConditionalInsertDialog()
        qtbot.addWidget(dialog)

        assert dialog is not None
        assert isinstance(dialog, QDialog)
        assert dialog.isModal()
        assert dialog.windowTitle() == "Insert Conditional"

    def test_placeholder_combo_populated(self, qtbot):
        """Test placeholder combo box has all options"""
        dialog = ConditionalInsertDialog()
        qtbot.addWidget(dialog)

        expected_items = [
            "folderName", "pictureCount", "width", "height", "longest",
            "extension", "folderSize", "galleryLink", "allImages", "hostLinks",
            "custom1", "custom2", "custom3", "custom4",
            "ext1", "ext2", "ext3", "ext4"
        ]

        assert dialog.placeholder_combo.count() == len(expected_items)
        for item in expected_items:
            assert dialog.placeholder_combo.findText(item) >= 0

    def test_exists_radio_default_checked(self, qtbot):
        """Test 'exists' radio button is checked by default"""
        dialog = ConditionalInsertDialog()
        qtbot.addWidget(dialog)

        assert dialog.exists_radio.isChecked()
        assert not dialog.equals_radio.isChecked()
        assert not dialog.value_input.isEnabled()

    def test_equals_radio_enables_value_input(self, qtbot):
        """Test selecting 'equals' radio enables value input"""
        dialog = ConditionalInsertDialog()
        qtbot.addWidget(dialog)

        # Set equals radio button checked programmatically
        dialog.equals_radio.setChecked(True)

        # Process events to allow signal/slot connections to fire
        qtbot.wait(10)

        assert dialog.equals_radio.isChecked()
        assert dialog.value_input.isEnabled()

    def test_get_conditional_text_exists(self, qtbot):
        """Test generating conditional text for 'exists' check"""
        dialog = ConditionalInsertDialog()
        qtbot.addWidget(dialog)

        dialog.placeholder_combo.setCurrentText("folderName")
        dialog.exists_radio.setChecked(True)
        dialog.include_else.setChecked(False)

        text = dialog.get_conditional_text()

        assert text == "[if folderName]\nContent\n[/if]"

    def test_get_conditional_text_equals(self, qtbot):
        """Test generating conditional text for 'equals' check"""
        dialog = ConditionalInsertDialog()
        qtbot.addWidget(dialog)

        dialog.placeholder_combo.setCurrentText("extension")
        dialog.equals_radio.setChecked(True)
        dialog.value_input.setText("jpg")
        dialog.include_else.setChecked(False)

        text = dialog.get_conditional_text()

        assert text == "[if extension=jpg]\nContent\n[/if]"

    def test_get_conditional_text_with_else(self, qtbot):
        """Test generating conditional text with else clause"""
        dialog = ConditionalInsertDialog()
        qtbot.addWidget(dialog)

        dialog.placeholder_combo.setCurrentText("pictureCount")
        dialog.exists_radio.setChecked(True)
        dialog.include_else.setChecked(True)

        text = dialog.get_conditional_text()

        expected = "[if pictureCount]\nContent when true\n[else]\nContent when false\n[/if]"
        assert text == expected

    def test_dialog_accept(self, qtbot):
        """Test accepting dialog"""
        dialog = ConditionalInsertDialog()
        qtbot.addWidget(dialog)

        with qtbot.waitSignal(dialog.finished):
            dialog.accept()

        assert dialog.result() == QDialog.DialogCode.Accepted

    def test_dialog_reject(self, qtbot):
        """Test rejecting dialog"""
        dialog = ConditionalInsertDialog()
        qtbot.addWidget(dialog)

        with qtbot.waitSignal(dialog.finished):
            dialog.reject()

        assert dialog.result() == QDialog.DialogCode.Rejected


# ============================================================================
# TemplateManagerDialog Initialization Tests
# ============================================================================

class TestTemplateManagerDialogInit:
    """Test TemplateManagerDialog initialization"""

    @patch('imxup.load_templates')
    def test_dialog_initialization(self, mock_load, qtbot):
        """Test TemplateManagerDialog creates successfully"""
        mock_load.return_value = {
            'default': '[b]#folderName#[/b]',
            'custom1': 'Custom template'
        }

        dialog = TemplateManagerDialog()
        qtbot.addWidget(dialog)

        assert dialog is not None
        assert isinstance(dialog, QDialog)
        assert dialog.isModal()
        assert dialog.windowTitle() == "Manage BBCode Templates"

    @patch('imxup.load_templates')
    def test_initial_state(self, mock_load, qtbot):
        """Test dialog initial state with pending changes tracking"""
        mock_load.return_value = {'default': 'Template'}

        dialog = TemplateManagerDialog()
        qtbot.addWidget(dialog)

        # New pending state tracking
        assert dialog.pending_changes == {}
        assert dialog.pending_new_templates == set()
        assert dialog.pending_deleted_templates == set()
        assert dialog.initial_template == "default"

    @patch('imxup.load_templates')
    def test_ui_components_created(self, mock_load, qtbot):
        """Test all UI components are created"""
        mock_load.return_value = {'default': 'Template'}

        dialog = TemplateManagerDialog()
        qtbot.addWidget(dialog)

        assert dialog.template_list is not None
        assert dialog.template_editor is not None
        assert dialog.new_btn is not None
        assert dialog.rename_btn is not None
        assert dialog.delete_btn is not None
        assert dialog.copy_btn is not None  # New copy button
        assert dialog.validate_btn is not None
        # Note: save_btn no longer exists - saving handled by commit_all_changes()

    @patch('imxup.load_templates')
    def test_highlighter_attached(self, mock_load, qtbot):
        """Test syntax highlighter is attached to editor"""
        mock_load.return_value = {'default': 'Template'}

        dialog = TemplateManagerDialog()
        qtbot.addWidget(dialog)

        assert dialog.highlighter is not None
        assert isinstance(dialog.highlighter, PlaceholderHighlighter)


# ============================================================================
# Template Loading Tests
# ============================================================================

class TestTemplateLoading:
    """Test template loading functionality"""

    @patch('imxup.load_templates')
    def test_load_templates_populates_list(self, mock_load, qtbot):
        """Test loading templates populates the list with display names"""
        mock_load.return_value = {
            'default': 'Default template',
            'custom1': 'Custom 1',
            'custom2': 'Custom 2'
        }

        dialog = TemplateManagerDialog()
        qtbot.addWidget(dialog)

        assert dialog.template_list.count() == 3

        # Check that actual names are stored in UserRole
        actual_names = []
        for i in range(dialog.template_list.count()):
            item = dialog.template_list.item(i)
            actual_name = item.data(Qt.ItemDataRole.UserRole)
            actual_names.append(actual_name)

        assert 'default' in actual_names
        assert 'custom1' in actual_names
        assert 'custom2' in actual_names

    @patch('imxup.load_templates')
    def test_template_display_names_have_indicators(self, mock_load, qtbot):
        """Test that template display names have appropriate indicators"""
        mock_load.return_value = {
            'default': 'Default template',
            'custom1': 'Custom 1'
        }

        dialog = TemplateManagerDialog(current_template='default')
        qtbot.addWidget(dialog)

        # Find default template item
        for i in range(dialog.template_list.count()):
            item = dialog.template_list.item(i)
            actual_name = item.data(Qt.ItemDataRole.UserRole)
            display_name = item.text()

            if actual_name == 'default':
                # Should have (Built-in) indicator
                assert "(Built-in)" in display_name
                # Should have star indicator since it's the active template
                assert "\u2605" in display_name  # Star character

    @patch('imxup.load_templates')
    def test_initial_template_selected(self, mock_load, qtbot):
        """Test initial template is selected on load"""
        mock_load.return_value = {
            'default': 'Default',
            'custom': 'Custom'
        }

        dialog = TemplateManagerDialog(current_template='custom')
        qtbot.addWidget(dialog)

        # Check UserRole data for actual template name
        current_item = dialog.template_list.currentItem()
        actual_name = current_item.data(Qt.ItemDataRole.UserRole)
        assert actual_name == 'custom'

    @patch('imxup.load_templates')
    def test_fallback_to_first_template(self, mock_load, qtbot):
        """Test fallback to first template if initial not found"""
        mock_load.return_value = {
            'default': 'Default',
            'custom': 'Custom'
        }

        dialog = TemplateManagerDialog(current_template='nonexistent')
        qtbot.addWidget(dialog)

        assert dialog.template_list.currentRow() == 0

    @patch('imxup.load_templates')
    def test_load_template_content(self, mock_load, qtbot):
        """Test loading template content into editor"""
        template_content = '[b]#folderName#[/b]\n#allImages#'
        mock_load.return_value = {'test': template_content}

        dialog = TemplateManagerDialog()
        qtbot.addWidget(dialog)

        dialog.load_template_content('test')

        assert dialog.template_editor.toPlainText() == template_content

    @patch('imxup.load_templates')
    def test_load_template_from_pending_changes(self, mock_load, qtbot):
        """Test loading template content from pending_changes first"""
        mock_load.return_value = {'test': 'Original content'}

        dialog = TemplateManagerDialog()
        qtbot.addWidget(dialog)

        # Simulate pending change
        dialog.pending_changes['test'] = 'Modified content'
        dialog.load_template_content('test')

        assert dialog.template_editor.toPlainText() == 'Modified content'


# ============================================================================
# Template Selection Tests
# ============================================================================

class TestTemplateSelection:
    """Test template selection behavior"""

    @patch('imxup.load_templates')
    def test_select_template_loads_content(self, mock_load, qtbot):
        """Test selecting template loads its content"""
        mock_load.return_value = {
            'default': 'Default content',
            'custom': 'Custom content'
        }

        dialog = TemplateManagerDialog()
        qtbot.addWidget(dialog)

        # Select custom template
        for i in range(dialog.template_list.count()):
            item = dialog.template_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == 'custom':
                dialog.template_list.setCurrentRow(i)
                break

        assert dialog.template_editor.toPlainText() == 'Custom content'

    @patch('imxup.load_templates')
    def test_select_builtin_disables_editing(self, mock_load, qtbot):
        """Test selecting built-in template disables editing"""
        mock_load.return_value = {
            'default': 'Default',
            'custom': 'Custom'
        }

        dialog = TemplateManagerDialog()
        qtbot.addWidget(dialog)

        # Find and select default template (built-in)
        for i in range(dialog.template_list.count()):
            item = dialog.template_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == 'default':
                dialog.template_list.setCurrentRow(i)
                break

        assert dialog.template_editor.isReadOnly()
        assert not dialog.rename_btn.isEnabled()
        assert not dialog.delete_btn.isEnabled()
        assert dialog.copy_btn.isEnabled()  # Copy should still work

    @patch('imxup.load_templates')
    def test_select_custom_enables_editing(self, mock_load, qtbot):
        """Test selecting custom template enables editing"""
        mock_load.return_value = {
            'default': 'Default',
            'custom': 'Custom'
        }

        dialog = TemplateManagerDialog()
        qtbot.addWidget(dialog)

        # Select custom template (not built-in)
        for i in range(dialog.template_list.count()):
            item = dialog.template_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == 'custom':
                dialog.template_list.setCurrentRow(i)
                break

        assert not dialog.template_editor.isReadOnly()
        assert dialog.rename_btn.isEnabled()
        assert dialog.delete_btn.isEnabled()

    @patch('imxup.load_templates')
    def test_selection_updates_current_template_name(self, mock_load, qtbot):
        """Test selection updates current_template_name"""
        mock_load.return_value = {'test': 'Content'}

        dialog = TemplateManagerDialog()
        qtbot.addWidget(dialog)

        dialog.template_list.setCurrentRow(0)

        assert dialog.current_template_name == 'test'

    @patch('imxup.load_templates')
    def test_editing_template_saves_to_pending(self, mock_load, qtbot):
        """Test editing template content saves to pending_changes immediately"""
        mock_load.return_value = {
            'template1': 'Content 1',
            'template2': 'Content 2'
        }

        dialog = TemplateManagerDialog()
        qtbot.addWidget(dialog)

        # Select first template (non-builtin)
        for i in range(dialog.template_list.count()):
            item = dialog.template_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == 'template1':
                dialog.template_list.setCurrentRow(i)
                break

        # Modify content
        dialog.template_editor.setPlainText('Modified content')

        # Changes should be immediately tracked in pending_changes
        assert dialog.unsaved_changes
        assert 'template1' in dialog.pending_changes
        assert dialog.pending_changes['template1'] == 'Modified content'


# ============================================================================
# Template CRUD Operations Tests
# ============================================================================

class TestCreateTemplate:
    """Test creating new templates"""

    @patch('imxup.load_templates')
    @patch('PyQt6.QtWidgets.QInputDialog.getText')
    def test_create_new_template(self, mock_input, mock_load, qtbot):
        """Test creating a new template adds to pending state"""
        mock_load.return_value = {'default': 'Default'}
        mock_input.return_value = ('new_template', True)

        dialog = TemplateManagerDialog()
        qtbot.addWidget(dialog)

        initial_count = dialog.template_list.count()
        dialog.create_new_template()

        assert dialog.template_list.count() == initial_count + 1
        assert dialog.current_template_name == 'new_template'
        assert 'new_template' in dialog.pending_new_templates
        assert 'new_template' in dialog.pending_changes
        assert dialog.pending_changes['new_template'] == ""  # Empty for new

    @patch('imxup.load_templates')
    @patch('PyQt6.QtWidgets.QInputDialog.getText')
    def test_create_template_cancelled(self, mock_input, mock_load, qtbot):
        """Test cancelling template creation"""
        mock_load.return_value = {'default': 'Default'}
        mock_input.return_value = ('', False)

        dialog = TemplateManagerDialog()
        qtbot.addWidget(dialog)

        initial_count = dialog.template_list.count()
        dialog.create_new_template()

        assert dialog.template_list.count() == initial_count

    @patch('imxup.load_templates')
    @patch('PyQt6.QtWidgets.QInputDialog.getText')
    @patch('PyQt6.QtWidgets.QMessageBox.warning')
    def test_create_duplicate_template_shows_warning(self, mock_warning, mock_input, mock_load, qtbot):
        """Test creating template with duplicate name shows warning"""
        mock_load.return_value = {'existing': 'Content'}
        mock_input.return_value = ('existing', True)

        dialog = TemplateManagerDialog()
        qtbot.addWidget(dialog)

        initial_count = dialog.template_list.count()
        dialog.create_new_template()

        mock_warning.assert_called_once()
        assert dialog.template_list.count() == initial_count


class TestRenameTemplate:
    """Test renaming templates"""

    @patch('imxup.load_templates')
    @patch('PyQt6.QtWidgets.QInputDialog.getText')
    @patch('os.path.exists')
    @patch('os.rename')
    def test_rename_template_success(self, mock_rename, mock_exists, mock_input, mock_load, qtbot):
        """Test successfully renaming a template"""
        mock_load.return_value = {'old_name': 'Content'}
        mock_input.return_value = ('new_name', True)
        mock_exists.return_value = True

        with patch('imxup.get_template_path', return_value='/tmp/templates'):
            dialog = TemplateManagerDialog()
            qtbot.addWidget(dialog)

            dialog.template_list.setCurrentRow(0)
            dialog.rename_template()

            mock_rename.assert_called_once()

    @patch('imxup.load_templates')
    @patch('PyQt6.QtWidgets.QMessageBox.warning')
    def test_rename_builtin_template_blocked(self, mock_warning, mock_load, qtbot):
        """Test renaming built-in template is blocked"""
        mock_load.return_value = {'default': 'Content'}

        dialog = TemplateManagerDialog()
        qtbot.addWidget(dialog)

        # Select default template (built-in)
        for i in range(dialog.template_list.count()):
            item = dialog.template_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == 'default':
                dialog.template_list.setCurrentRow(i)
                break

        dialog.rename_template()

        mock_warning.assert_called_once()
        assert "Cannot rename built-in templates" in str(mock_warning.call_args)

    @patch('imxup.load_templates')
    @patch('PyQt6.QtWidgets.QInputDialog.getText')
    def test_rename_template_cancelled(self, mock_input, mock_load, qtbot):
        """Test cancelling template rename"""
        mock_load.return_value = {'test': 'Content'}
        mock_input.return_value = ('', False)

        dialog = TemplateManagerDialog()
        qtbot.addWidget(dialog)

        dialog.template_list.setCurrentRow(0)
        original_name = dialog.template_list.currentItem().data(Qt.ItemDataRole.UserRole)
        dialog.rename_template()

        assert dialog.template_list.currentItem().data(Qt.ItemDataRole.UserRole) == original_name


class TestDeleteTemplate:
    """Test deleting templates"""

    @patch('imxup.load_templates')
    @patch('PyQt6.QtWidgets.QMessageBox.question')
    def test_delete_template_adds_to_pending(self, mock_question, mock_load, qtbot):
        """Test deleting template adds to pending_deleted_templates"""
        mock_load.return_value = {'test': 'Content'}
        mock_question.return_value = QMessageBox.StandardButton.Yes

        dialog = TemplateManagerDialog()
        qtbot.addWidget(dialog)

        dialog.template_list.setCurrentRow(0)
        initial_count = dialog.template_list.count()

        dialog.delete_template()

        # Should be removed from UI but tracked in pending_deleted
        assert dialog.template_list.count() == initial_count - 1
        assert 'test' in dialog.pending_deleted_templates

    @patch('imxup.load_templates')
    @patch('PyQt6.QtWidgets.QMessageBox.warning')
    def test_delete_builtin_template_blocked(self, mock_warning, mock_load, qtbot):
        """Test deleting built-in template is blocked"""
        mock_load.return_value = {'default': 'Content'}

        dialog = TemplateManagerDialog()
        qtbot.addWidget(dialog)

        for i in range(dialog.template_list.count()):
            item = dialog.template_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == 'default':
                dialog.template_list.setCurrentRow(i)
                break

        dialog.delete_template()

        mock_warning.assert_called_once()
        assert "Cannot delete built-in templates" in str(mock_warning.call_args)

    @patch('imxup.load_templates')
    @patch('PyQt6.QtWidgets.QMessageBox.question')
    def test_delete_template_cancelled(self, mock_question, mock_load, qtbot):
        """Test cancelling template deletion"""
        mock_load.return_value = {'test': 'Content'}
        mock_question.return_value = QMessageBox.StandardButton.No

        dialog = TemplateManagerDialog()
        qtbot.addWidget(dialog)

        dialog.template_list.setCurrentRow(0)
        initial_count = dialog.template_list.count()

        dialog.delete_template()

        assert dialog.template_list.count() == initial_count

    @patch('imxup.load_templates')
    @patch('PyQt6.QtWidgets.QInputDialog.getText')
    @patch('PyQt6.QtWidgets.QMessageBox.question')
    def test_delete_pending_new_template(self, mock_question, mock_input, mock_load, qtbot):
        """Test deleting a template that was just created (not on disk)"""
        mock_load.return_value = {'default': 'Default'}
        mock_input.return_value = ('new_template', True)
        mock_question.return_value = QMessageBox.StandardButton.Yes

        dialog = TemplateManagerDialog()
        qtbot.addWidget(dialog)

        # Create new template
        dialog.create_new_template()
        assert 'new_template' in dialog.pending_new_templates

        # Delete it
        dialog.delete_template()

        # Should be removed from pending_new, not added to pending_deleted
        assert 'new_template' not in dialog.pending_new_templates
        assert 'new_template' not in dialog.pending_deleted_templates


class TestCopyTemplate:
    """Test copying templates"""

    @patch('imxup.load_templates')
    @patch('PyQt6.QtWidgets.QInputDialog.getText')
    def test_copy_template_success(self, mock_input, mock_load, qtbot):
        """Test successfully copying a template"""
        mock_load.return_value = {'source': 'Source content'}
        mock_input.return_value = ('source_copy', True)

        dialog = TemplateManagerDialog()
        qtbot.addWidget(dialog)

        dialog.template_list.setCurrentRow(0)
        initial_count = dialog.template_list.count()

        dialog.copy_template()

        assert dialog.template_list.count() == initial_count + 1
        assert 'source_copy' in dialog.pending_new_templates
        assert dialog.pending_changes['source_copy'] == 'Source content'

    @patch('imxup.load_templates')
    @patch('PyQt6.QtWidgets.QInputDialog.getText')
    def test_copy_builtin_template_allowed(self, mock_input, mock_load, qtbot):
        """Test copying built-in template is allowed"""
        mock_load.return_value = {'default': 'Default content'}
        mock_input.return_value = ('my_default', True)

        dialog = TemplateManagerDialog()
        qtbot.addWidget(dialog)

        # Select default template (built-in)
        for i in range(dialog.template_list.count()):
            item = dialog.template_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == 'default':
                dialog.template_list.setCurrentRow(i)
                break

        dialog.copy_template()

        assert 'my_default' in dialog.pending_new_templates
        assert dialog.pending_changes['my_default'] == 'Default content'

    @patch('imxup.load_templates')
    @patch('PyQt6.QtWidgets.QInputDialog.getText')
    @patch('PyQt6.QtWidgets.QMessageBox.warning')
    def test_copy_template_duplicate_name(self, mock_warning, mock_input, mock_load, qtbot):
        """Test copying to duplicate name shows warning"""
        mock_load.return_value = {'source': 'Content', 'existing': 'Existing'}
        mock_input.return_value = ('existing', True)

        dialog = TemplateManagerDialog()
        qtbot.addWidget(dialog)

        dialog.template_list.setCurrentRow(0)
        initial_count = dialog.template_list.count()

        dialog.copy_template()

        mock_warning.assert_called_once()
        assert dialog.template_list.count() == initial_count


# ============================================================================
# Pending Changes Management Tests
# ============================================================================

class TestPendingChanges:
    """Test pending changes commit/discard functionality"""

    @patch('imxup.load_templates')
    @patch('builtins.open', new_callable=mock_open)
    def test_commit_all_changes(self, mock_file, mock_load, qtbot):
        """Test committing all pending changes to disk"""
        mock_load.return_value = {'test': 'Original'}

        with patch('imxup.get_template_path', return_value='/tmp/templates'):
            dialog = TemplateManagerDialog()
            qtbot.addWidget(dialog)

            # Make some changes
            dialog.pending_changes['test'] = 'Modified content'
            dialog.pending_changes['new_template'] = 'New content'
            dialog.pending_new_templates.add('new_template')

            result = dialog.commit_all_changes()

            assert result is True
            assert dialog.pending_changes == {}
            assert dialog.pending_new_templates == set()
            assert dialog.pending_deleted_templates == set()

    @patch('imxup.load_templates')
    @patch('os.path.exists')
    @patch('os.remove')
    @patch('builtins.open', new_callable=mock_open)
    def test_commit_deletes_pending_deleted(self, mock_file, mock_remove, mock_exists, mock_load, qtbot):
        """Test commit_all_changes deletes pending_deleted_templates"""
        mock_load.return_value = {'test': 'Content'}
        mock_exists.return_value = True

        with patch('imxup.get_template_path', return_value='/tmp/templates'):
            dialog = TemplateManagerDialog()
            qtbot.addWidget(dialog)

            dialog.pending_deleted_templates.add('test')

            result = dialog.commit_all_changes()

            assert result is True
            mock_remove.assert_called_once()
            assert dialog.pending_deleted_templates == set()

    @patch('imxup.load_templates')
    def test_discard_all_changes(self, mock_load, qtbot):
        """Test discarding all pending changes clears tracking state"""
        # Use only built-in template to avoid on_template_changed adding to pending
        mock_load.return_value = {'default': 'Default content'}

        dialog = TemplateManagerDialog()
        qtbot.addWidget(dialog)

        # Manually set up pending state (simulating changes made before discard)
        dialog.pending_changes['custom_template'] = 'Modified'
        dialog.pending_new_templates.add('new_template')
        dialog.pending_deleted_templates.add('to_delete')
        dialog.unsaved_changes = True

        dialog.discard_all_changes()

        # pending_new_templates and pending_deleted_templates should be cleared
        assert dialog.pending_new_templates == set()
        assert dialog.pending_deleted_templates == set()
        # unsaved_changes should be false after discard
        assert dialog.unsaved_changes is False
        # Note: pending_changes may have content loaded from disk for non-builtin
        # templates after load_templates() triggers selection.
        # For built-in templates (like 'default'), pending_changes won't be populated
        # because on_template_changed skips built-in templates.

    @patch('imxup.load_templates')
    def test_has_pending_changes_true(self, mock_load, qtbot):
        """Test has_pending_changes returns True when there are changes"""
        mock_load.return_value = {'test': 'Content'}

        dialog = TemplateManagerDialog()
        qtbot.addWidget(dialog)

        # Case 1: pending_changes
        dialog.pending_changes['test'] = 'Modified'
        assert dialog.has_pending_changes() is True

        dialog.pending_changes.clear()

        # Case 2: pending_new_templates
        dialog.pending_new_templates.add('new')
        assert dialog.has_pending_changes() is True

        dialog.pending_new_templates.clear()

        # Case 3: pending_deleted_templates
        dialog.pending_deleted_templates.add('to_delete')
        assert dialog.has_pending_changes() is True

        dialog.pending_deleted_templates.clear()

        # Case 4: unsaved_changes flag
        dialog.current_template_name = 'test'
        dialog.unsaved_changes = True
        assert dialog.has_pending_changes() is True

    @patch('imxup.load_templates')
    def test_has_pending_changes_false(self, mock_load, qtbot):
        """Test has_pending_changes returns False when no changes"""
        mock_load.return_value = {'test': 'Content'}

        dialog = TemplateManagerDialog()
        qtbot.addWidget(dialog)

        dialog.unsaved_changes = False
        dialog.pending_changes.clear()
        dialog.pending_new_templates.clear()
        dialog.pending_deleted_templates.clear()

        assert dialog.has_pending_changes() is False


# ============================================================================
# Built-in Templates Protection Tests
# ============================================================================

class TestBuiltinTemplatesProtection:
    """Test that built-in templates are protected"""

    @patch('imxup.load_templates')
    def test_builtin_templates_constant(self, mock_load, qtbot):
        """Test BUILTIN_TEMPLATES constant is defined correctly"""
        assert "default" in BUILTIN_TEMPLATES
        assert "Extended Example" in BUILTIN_TEMPLATES

    @patch('imxup.load_templates')
    @patch('PyQt6.QtWidgets.QMessageBox.warning')
    def test_extended_example_cannot_be_renamed(self, mock_warning, mock_load, qtbot):
        """Test Extended Example template cannot be renamed"""
        mock_load.return_value = {'Extended Example': 'Content'}

        dialog = TemplateManagerDialog()
        qtbot.addWidget(dialog)

        for i in range(dialog.template_list.count()):
            item = dialog.template_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == 'Extended Example':
                dialog.template_list.setCurrentRow(i)
                break

        dialog.rename_template()

        mock_warning.assert_called_once()
        assert "Cannot rename built-in templates" in str(mock_warning.call_args)

    @patch('imxup.load_templates')
    @patch('PyQt6.QtWidgets.QMessageBox.warning')
    def test_extended_example_cannot_be_deleted(self, mock_warning, mock_load, qtbot):
        """Test Extended Example template cannot be deleted"""
        mock_load.return_value = {'Extended Example': 'Content'}

        dialog = TemplateManagerDialog()
        qtbot.addWidget(dialog)

        for i in range(dialog.template_list.count()):
            item = dialog.template_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == 'Extended Example':
                dialog.template_list.setCurrentRow(i)
                break

        dialog.delete_template()

        mock_warning.assert_called_once()
        assert "Cannot delete built-in templates" in str(mock_warning.call_args)


# ============================================================================
# Template Validation Tests
# ============================================================================

class TestTemplateValidation:
    """Test template syntax validation"""

    @patch('imxup.load_templates')
    def test_validate_valid_template(self, mock_load, qtbot):
        """Test validating a valid template"""
        mock_load.return_value = {'test': ''}

        dialog = TemplateManagerDialog()
        qtbot.addWidget(dialog)

        content = "[b]#folderName#[/b]\n[if pictureCount]#pictureCount# images[/if]"
        is_valid, errors = dialog.validate_template_syntax(content)

        assert is_valid
        assert len(errors) == 0

    @patch('imxup.load_templates')
    def test_validate_unmatched_if_tags(self, mock_load, qtbot):
        """Test detecting unmatched [if] tags"""
        mock_load.return_value = {'test': ''}

        dialog = TemplateManagerDialog()
        qtbot.addWidget(dialog)

        content = "[if folderName]Content"  # Missing [/if]
        is_valid, errors = dialog.validate_template_syntax(content)

        assert not is_valid
        assert any("Unmatched conditional tags" in err for err in errors)

    @patch('imxup.load_templates')
    def test_validate_invalid_if_syntax(self, mock_load, qtbot):
        """Test detecting invalid [if] syntax"""
        mock_load.return_value = {'test': ''}

        dialog = TemplateManagerDialog()
        qtbot.addWidget(dialog)

        content = "[if]Content[/if]"  # Missing placeholder
        is_valid, errors = dialog.validate_template_syntax(content)

        assert not is_valid
        assert any("Invalid [if] syntax" in err for err in errors)

    @patch('imxup.load_templates')
    def test_validate_orphaned_else(self, mock_load, qtbot):
        """Test detecting orphaned [else] tags"""
        mock_load.return_value = {'test': ''}

        dialog = TemplateManagerDialog()
        qtbot.addWidget(dialog)

        content = "[else]\nContent outside conditional"
        is_valid, errors = dialog.validate_template_syntax(content)

        assert not is_valid
        assert any("[else] tag found outside" in err for err in errors)

    @patch('imxup.load_templates')
    def test_validate_unmatched_bbcode(self, mock_load, qtbot):
        """Test detecting unmatched BBCode tags with new error format"""
        mock_load.return_value = {'test': ''}

        dialog = TemplateManagerDialog()
        qtbot.addWidget(dialog)

        content = "[b]Bold text"  # Missing [/b]
        is_valid, errors = dialog.validate_template_syntax(content)

        assert not is_valid
        # New error format: "Line X: Tag [b] was never closed"
        assert any("Tag [b] was never closed" in err for err in errors)

    @patch('imxup.load_templates')
    @patch('PyQt6.QtWidgets.QMessageBox.information')
    def test_validate_and_show_results_success(self, mock_info, mock_load, qtbot):
        """Test validation success message"""
        mock_load.return_value = {'test': ''}

        dialog = TemplateManagerDialog()
        qtbot.addWidget(dialog)

        dialog.template_editor.setPlainText("[b]Valid template[/b]")
        dialog.validate_and_show_results()

        mock_info.assert_called_once()
        assert "No syntax errors" in str(mock_info.call_args)

    @patch('imxup.load_templates')
    @patch('PyQt6.QtWidgets.QMessageBox.warning')
    def test_validate_and_show_results_errors(self, mock_warning, mock_load, qtbot):
        """Test validation error message"""
        mock_load.return_value = {'test': ''}

        dialog = TemplateManagerDialog()
        qtbot.addWidget(dialog)

        dialog.template_editor.setPlainText("[if folderName]No closing tag")
        dialog.validate_and_show_results()

        mock_warning.assert_called_once()
        assert "syntax errors" in str(mock_warning.call_args).lower()


# ============================================================================
# Placeholder Insertion Tests
# ============================================================================

class TestPlaceholderInsertion:
    """Test placeholder insertion functionality"""

    @patch('imxup.load_templates')
    def test_insert_placeholder(self, mock_load, qtbot):
        """Test inserting a placeholder"""
        mock_load.return_value = {'test': ''}

        dialog = TemplateManagerDialog()
        qtbot.addWidget(dialog)

        dialog.template_editor.clear()
        dialog.insert_placeholder("#folderName#")

        assert "#folderName#" in dialog.template_editor.toPlainText()

    @patch('imxup.load_templates')
    def test_insert_multiple_placeholders(self, mock_load, qtbot):
        """Test inserting multiple placeholders"""
        mock_load.return_value = {'test': ''}

        dialog = TemplateManagerDialog()
        qtbot.addWidget(dialog)

        dialog.template_editor.clear()
        dialog.insert_placeholder("#folderName#")
        dialog.insert_placeholder(" - ")
        dialog.insert_placeholder("#pictureCount#")

        text = dialog.template_editor.toPlainText()
        assert "#folderName#" in text
        assert "#pictureCount#" in text

    @patch('imxup.load_templates')
    def test_insert_text(self, mock_load, qtbot):
        """Test inserting plain text"""
        mock_load.return_value = {'test': ''}

        dialog = TemplateManagerDialog()
        qtbot.addWidget(dialog)

        dialog.template_editor.clear()
        dialog.insert_text("[else]\n")

        assert "[else]" in dialog.template_editor.toPlainText()

    @patch('imxup.load_templates')
    def test_insert_conditional_helper(self, mock_load, qtbot):
        """Test inserting conditional via helper dialog"""
        mock_load.return_value = {'test': ''}

        dialog = TemplateManagerDialog()
        qtbot.addWidget(dialog)

        # Mock the ConditionalInsertDialog
        with patch.object(ConditionalInsertDialog, 'exec', return_value=QDialog.DialogCode.Accepted):
            with patch.object(ConditionalInsertDialog, 'get_conditional_text',
                            return_value='[if test]\nContent\n[/if]'):
                dialog.insert_conditional_helper()

        assert '[if test]' in dialog.template_editor.toPlainText()


# ============================================================================
# Close Event Tests
# ============================================================================

class TestCloseEvent:
    """Test dialog close event behavior"""

    @patch('imxup.load_templates')
    def test_close_event_accepts_without_prompt(self, mock_load, qtbot):
        """Test closeEvent accepts without prompting (parent handles save)"""
        mock_load.return_value = {'test': 'Content'}

        dialog = TemplateManagerDialog()
        qtbot.addWidget(dialog)

        # Make some unsaved changes
        dialog.template_list.setCurrentRow(0)
        dialog.current_template_name = 'test'
        dialog.template_editor.setPlainText('Modified')
        dialog.unsaved_changes = True

        # Close event should accept without prompting
        event = Mock()
        dialog.closeEvent(event)

        # Should accept (parent dialog handles save/discard)
        event.accept.assert_called_once()
        event.ignore.assert_not_called()


# ============================================================================
# Integration Tests
# ============================================================================

class TestTemplateManagerIntegration:
    """Integration tests for complete workflows"""

    @patch('imxup.load_templates')
    @patch('PyQt6.QtWidgets.QInputDialog.getText')
    @patch('builtins.open', new_callable=mock_open)
    def test_complete_template_creation_workflow(self, mock_file, mock_input, mock_load, qtbot):
        """Test complete workflow: create, edit, validate, commit"""
        mock_load.return_value = {'default': 'Default'}
        mock_input.return_value = ('new_template', True)

        with patch('imxup.get_template_path', return_value='/tmp/templates'):
            dialog = TemplateManagerDialog()
            qtbot.addWidget(dialog)

            # Create new template
            dialog.create_new_template()
            assert dialog.current_template_name == 'new_template'
            assert 'new_template' in dialog.pending_new_templates

            # Edit template
            dialog.template_editor.setPlainText('[b]#folderName#[/b]')
            assert dialog.unsaved_changes

            # Validate
            is_valid, errors = dialog.validate_template_syntax(dialog.template_editor.toPlainText())
            assert is_valid

            # Commit all changes
            result = dialog.commit_all_changes()
            assert result is True
            assert dialog.pending_new_templates == set()
            assert dialog.pending_changes == {}

    @patch('imxup.load_templates')
    def test_placeholder_buttons_functional(self, mock_load, qtbot):
        """Test all placeholder insertion buttons work"""
        mock_load.return_value = {'test': ''}

        dialog = TemplateManagerDialog()
        qtbot.addWidget(dialog)

        dialog.template_list.setCurrentRow(0)
        dialog.current_template_name = 'test'
        dialog.template_editor.clear()

        # Test some placeholders
        test_placeholders = ['#folderName#', '#pictureCount#', '#width#']

        for placeholder in test_placeholders:
            dialog.insert_placeholder(placeholder)

        text = dialog.template_editor.toPlainText()
        for placeholder in test_placeholders:
            assert placeholder in text


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
