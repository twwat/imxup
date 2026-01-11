"""
Template manager dialog for BBCode templates
Provides interface for creating, editing, and managing BBCode templates
"""

import os
import re
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QListWidget,
    QPushButton, QLabel, QPlainTextEdit, QMessageBox, QInputDialog,
    QWidget, QGridLayout, QComboBox, QRadioButton, QButtonGroup, QLineEdit, QApplication
)
from PyQt6.QtGui import QSyntaxHighlighter, QTextCharFormat, QColor, QFont
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QListWidgetItem

# Built-in templates that are read-only and cannot be deleted
BUILTIN_TEMPLATES = frozenset({"default", "Extended Example"})


class PlaceholderHighlighter(QSyntaxHighlighter):
    """Syntax highlighter for BBCode template placeholders and conditional tags"""

    def __init__(self, parent=None):
        super().__init__(parent)

        # Detect dark mode
        palette = QApplication.palette()
        is_dark = palette.window().color().lightness() < 128

        # Placeholder format
        self.placeholder_format = QTextCharFormat()
        if is_dark:
            # Dark mode: darker background, brighter text
            self.placeholder_format.setBackground(QColor("#5c4a1f"))  # Dark gold
            self.placeholder_format.setForeground(QColor("#ffd966"))  # Bright gold
        else:
            # Light mode: light background, dark text
            self.placeholder_format.setBackground(QColor("#fff3cd"))  # Light yellow
            self.placeholder_format.setForeground(QColor("#856404"))  # Dark yellow
        self.placeholder_format.setFontWeight(QFont.Weight.Bold)

        # Conditional tag format
        self.conditional_format = QTextCharFormat()
        if is_dark:
            # Dark mode: darker background, brighter text
            self.conditional_format.setBackground(QColor("#1a3d4d"))  # Dark blue
            self.conditional_format.setForeground(QColor("#66ccff"))  # Bright blue
        else:
            # Light mode: light background, dark text
            self.conditional_format.setBackground(QColor("#d1ecf1"))  # Light blue
            self.conditional_format.setForeground(QColor("#0c5460"))  # Dark blue
        self.conditional_format.setFontWeight(QFont.Weight.Bold)

        # Define all placeholders
        self.placeholders = [
            "#folderName#", "#width#", "#height#", "#longest#",
            "#extension#", "#pictureCount#", "#folderSize#",
            "#galleryLink#", "#allImages#", "#hostLinks#", "#custom1#", "#custom2#", "#custom3#", "#custom4#",
            "#ext1#", "#ext2#", "#ext3#", "#ext4#"
        ]

        # Conditional tags
        self.conditional_tags = ["[if", "[else]", "[/if]"]

    def highlightBlock(self, text):
        """Highlight placeholders and conditional tags in the text block"""
        # Highlight placeholders
        for placeholder in self.placeholders:
            index = 0
            while True:
                index = text.find(placeholder, index)
                if index == -1:
                    break
                self.setFormat(index, len(placeholder), self.placeholder_format)
                index += len(placeholder)

        # Highlight conditional tags
        for tag in self.conditional_tags:
            index = 0
            while True:
                index = text.find(tag, index)
                if index == -1:
                    break
                # For [if tag, find the closing bracket to highlight the full tag including conditions
                if tag == "[if":
                    end_index = text.find("]", index)
                    if end_index != -1:
                        self.setFormat(index, end_index - index + 1, self.conditional_format)
                        index = end_index + 1
                    else:
                        self.setFormat(index, len(tag), self.conditional_format)
                        index += len(tag)
                else:
                    self.setFormat(index, len(tag), self.conditional_format)
                    index += len(tag)


class ConditionalInsertDialog(QDialog):
    """Dialog to help users insert conditional tags"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Insert Conditional")
        self.setModal(True)
        self.resize(400, 250)

        layout = QVBoxLayout(self)

        # Placeholder selection
        placeholder_label = QLabel("Select placeholder:")
        layout.addWidget(placeholder_label)

        self.placeholder_combo = QComboBox()
        self.placeholder_combo.addItems([
            "folderName", "pictureCount", "width", "height", "longest",
            "extension", "folderSize", "galleryLink", "allImages", "hostLinks",
            "custom1", "custom2", "custom3", "custom4",
            "ext1", "ext2", "ext3", "ext4"
        ])
        layout.addWidget(self.placeholder_combo)

        # Condition type
        type_label = QLabel("Condition type:")
        layout.addWidget(type_label)

        self.type_group = QButtonGroup(self)
        self.exists_radio = QRadioButton("Check if exists (non-empty)")
        self.equals_radio = QRadioButton("Check if equals value:")
        self.exists_radio.setChecked(True)
        self.type_group.addButton(self.exists_radio)
        self.type_group.addButton(self.equals_radio)

        layout.addWidget(self.exists_radio)

        # Value input (for equality check)
        value_layout = QHBoxLayout()
        value_layout.addWidget(self.equals_radio)
        self.value_input = QLineEdit()
        self.value_input.setPlaceholderText("Enter value to compare")
        self.value_input.setEnabled(False)
        value_layout.addWidget(self.value_input)
        layout.addLayout(value_layout)

        # Connect radio button to enable/disable value input
        self.equals_radio.toggled.connect(self.value_input.setEnabled)

        # Include else clause
        self.include_else = QRadioButton("Include [else] clause")
        layout.addWidget(self.include_else)

        layout.addStretch()

        # Buttons
        button_layout = QHBoxLayout()
        insert_btn = QPushButton("Insert")
        insert_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addStretch()
        button_layout.addWidget(insert_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)

    def get_conditional_text(self):
        """Generate the conditional text based on user selections"""
        placeholder = self.placeholder_combo.currentText()

        if self.equals_radio.isChecked():
            value = self.value_input.text().strip()
            if_tag = f"[if {placeholder}={value}]"
        else:
            if_tag = f"[if {placeholder}]"

        if self.include_else.isChecked():
            return f"{if_tag}\nContent when true\n[else]\nContent when false\n[/if]"
        else:
            return f"{if_tag}\nContent\n[/if]"


class BBCodeValidator:
    """Stack-based BBCode validator with comprehensive tag support."""

    # All known BBCode tags
    KNOWN_TAGS = {
        # Text formatting
        'b', 'i', 'u', 's', 'strike', 'sub', 'sup',
        # Alignment
        'center', 'left', 'right', 'justify',
        # Size and font
        'size', 'font', 'color',
        # Links and media
        'url', 'img', 'video', 'audio',
        # Structure
        'code', 'quote', 'spoiler', 'hide',
        # Lists
        'list', 'ul', 'ol', 'li',
        # Tables
        'table', 'tr', 'td', 'th',
    }

    # Self-closing tags (no closing tag needed)
    SELF_CLOSING_TAGS = {'hr', 'br'}

    def __init__(self):
        # Pattern to match any BBCode tag: [tag], [/tag], [tag=value]
        self.tag_pattern = re.compile(
            r'\[(/?)(\w+)(?:=[^\]]+)?\]',
            re.IGNORECASE
        )

    def validate(self, content: str) -> tuple[bool, list[str]]:
        """Validate BBCode content using stack-based matching.

        Args:
            content: The BBCode content to validate.

        Returns:
            A tuple of (is_valid, list_of_error_strings).
        """
        errors = []
        lines = content.split('\n')
        tag_stack = []  # Stack of (tag_name, line_num, column)

        for line_num, line in enumerate(lines, 1):
            for match in self.tag_pattern.finditer(line):
                is_closing = match.group(1) == '/'
                tag_name = match.group(2).lower()
                column = match.start() + 1

                # Skip self-closing tags
                if tag_name in self.SELF_CLOSING_TAGS:
                    continue

                # Skip template conditional tags (handled separately)
                if tag_name in ('if', 'else'):
                    continue

                if is_closing:
                    if not tag_stack:
                        errors.append(f"Line {line_num}: Closing [/{tag_name}] without matching opening tag")
                    elif tag_stack[-1][0] != tag_name:
                        expected_tag, open_line, _ = tag_stack[-1]
                        errors.append(f"Line {line_num}: Tag [{expected_tag}] (opened at line {open_line}) closed by [/{tag_name}]")
                        # Try to recover by finding matching tag in stack
                        found = False
                        for i in range(len(tag_stack) - 1, -1, -1):
                            if tag_stack[i][0] == tag_name:
                                tag_stack = tag_stack[:i]
                                found = True
                                break
                        if not found:
                            if tag_stack:
                                tag_stack.pop()
                    else:
                        tag_stack.pop()
                else:
                    # Opening tag - push to stack
                    tag_stack.append((tag_name, line_num, column))

        # Check for unclosed tags
        for tag_name, line_num, _ in reversed(tag_stack):
            errors.append(f"Line {line_num}: Tag [{tag_name}] was never closed")

        return (len(errors) == 0, errors)


class TemplateManagerDialog(QDialog):
    """Dialog for managing BBCode templates"""
    
    def __init__(self, parent=None, current_template="default"):
        super().__init__(parent)
        self.setWindowTitle("Manage BBCode Templates")
        self.setModal(True)
        self.resize(900, 700)
        
        # Track unsaved changes
        self.unsaved_changes = False
        self.current_template_name = None
        self.initial_template = current_template
        self.active_template_name = current_template  # Store the active template name

        # Track pending changes (not yet saved to disk)
        self.pending_changes = {}  # {template_name: content}
        self.pending_new_templates = set()  # Templates created but not committed
        self.pending_deleted_templates = set()  # Templates marked for deletion

        # Setup UI
        layout = QVBoxLayout(self)
        
        # Template list section
        list_group = QGroupBox("Templates")
        list_layout = QHBoxLayout(list_group)
        
        # Template list
        self.template_list = QListWidget()
        self.template_list.setMinimumWidth(200)
        self.template_list.itemSelectionChanged.connect(self.on_template_selected)
        # Selection styling handled in styles.qss
        list_layout.addWidget(self.template_list)
        
        # Template actions
        actions_layout = QVBoxLayout()
        
        self.new_btn = QPushButton("New Template")
        if not self.new_btn.text().startswith(" "):
            self.new_btn.setText(" " + self.new_btn.text())
        self.new_btn.clicked.connect(self.create_new_template)
        actions_layout.addWidget(self.new_btn)
        
        self.rename_btn = QPushButton("Rename Template")
        if not self.rename_btn.text().startswith(" "):
            self.rename_btn.setText(" " + self.rename_btn.text())
        self.rename_btn.clicked.connect(self.rename_template)
        self.rename_btn.setEnabled(False)
        actions_layout.addWidget(self.rename_btn)
        
        self.delete_btn = QPushButton("Delete Template")
        if not self.delete_btn.text().startswith(" "):
            self.delete_btn.setText(" " + self.delete_btn.text())
        self.delete_btn.clicked.connect(self.delete_template)
        self.delete_btn.setEnabled(False)
        actions_layout.addWidget(self.delete_btn)

        self.copy_btn = QPushButton("Copy Template")
        if not self.copy_btn.text().startswith(" "):
            self.copy_btn.setText(" " + self.copy_btn.text())
        self.copy_btn.clicked.connect(self.copy_template)
        self.copy_btn.setEnabled(False)
        actions_layout.addWidget(self.copy_btn)

        actions_layout.addStretch()
        list_layout.addLayout(actions_layout)
        
        layout.addWidget(list_group)
        
        # Template editor section
        editor_group = QGroupBox("Template Editor")
        editor_layout = QHBoxLayout(editor_group)
        
        # Template content editor with syntax highlighting
        self.template_editor = QPlainTextEdit()
        self.template_editor.setProperty("class", "template-editor")
        self.template_editor.textChanged.connect(self.on_template_changed)
        
        # Add syntax highlighter for placeholders
        self.highlighter = PlaceholderHighlighter(self.template_editor.document())
        
        editor_layout.addWidget(self.template_editor)
        
        # Placeholder buttons on right side in two columns
        placeholder_widget = QWidget()
        placeholder_widget.setFixedWidth(180)
        placeholder_main_layout = QVBoxLayout(placeholder_widget)
        placeholder_main_layout.setContentsMargins(4, 0, 0, 0)
        
        # Label
        placeholder_label = QLabel("Insert Placeholders:")
        placeholder_label.setStyleSheet("font-weight: bold; margin-bottom: 5px;")
        placeholder_main_layout.addWidget(placeholder_label)
        
        # Grid layout for buttons in 2 columns
        placeholder_grid = QGridLayout()
        placeholder_grid.setSpacing(3)
        
        placeholders = [
            ("#folderName#", "Gallery Name"),
            ("#allImages#", "All Images"),
            ("#hostLinks#", "Host Links"),
            ("#height#", "Height"),
            ("#pictureCount#", "Picture Count"),
            ("#width#", "Width"),
            ("#folderSize#", "Folder Size"),
            ("#longest#", "Longest Side"),
            ("#custom1#", "Custom 1"),
            ("#galleryLink#", "Gallery Link"),
            ("#custom2#", "Custom 2"),
            ("#extension#", "Extension"),
            ("#custom3#", "Custom 3"),
            ("#ext1#", "Ext 1"),
            ("#custom4#", "Custom 4"),
            ("#ext2#", "Ext 2"),
            ("#ext3#", "Ext 3"),
            ("#ext4#", "Ext 4")
        ]
        
        row = 0
        col = 0
        for placeholder, label in placeholders:
            btn = QPushButton(label)
            btn.setToolTip(f"Insert {placeholder}")
            btn.clicked.connect(lambda _, p=placeholder: self.insert_placeholder(p))
            btn.setStyleSheet("""
                QPushButton {
                    padding: 2px 2px;
                    min-width: 70px;
                    max-width: 70px;
                    max-height: 20px;
                    font-size: 10px;
                }
            """)
            placeholder_grid.addWidget(btn, row, col)

            col += 1
            if col >= 2:
                col = 0
                row += 1
        
        placeholder_main_layout.addLayout(placeholder_grid)

        # Add conditional tag buttons
        conditional_label = QLabel("Insert Conditionals:")
        conditional_label.setStyleSheet("font-weight: bold; margin-top: 15px; margin-bottom: 5px;")
        placeholder_main_layout.addWidget(conditional_label)

        # Conditional buttons grid
        conditional_grid = QGridLayout()
        conditional_grid.setSpacing(3)

        self.insert_if_btn = QPushButton("[if] Helper")
        self.insert_if_btn.setToolTip("Insert conditional with helper dialog")
        self.insert_if_btn.clicked.connect(self.insert_conditional_helper)
        self.insert_if_btn.setStyleSheet("""
            QPushButton {
                padding: 2px 2px;
                min-width: 70px;
                max-width: 70px;
                max-height: 20px;
                font-size: 10px;
            }
        """)
        conditional_grid.addWidget(self.insert_if_btn, 0, 0)

        self.insert_else_btn = QPushButton("[else]")
        self.insert_else_btn.setToolTip("Insert [else] tag")
        self.insert_else_btn.clicked.connect(lambda: self.insert_text("[else]\n"))
        self.insert_else_btn.setStyleSheet("""
            QPushButton {
                padding: 2px 2px;
                min-width: 70px;
                max-width: 70px;
                max-height: 20px;
                font-size: 10px;
            }
        """)
        conditional_grid.addWidget(self.insert_else_btn, 0, 1)

        self.insert_endif_btn = QPushButton("[/if]")
        self.insert_endif_btn.setToolTip("Insert [/if] closing tag")
        self.insert_endif_btn.clicked.connect(lambda: self.insert_text("[/if]"))
        self.insert_endif_btn.setStyleSheet("""
            QPushButton {
                padding: 2px 2px;
                min-width: 70px;
                max-width: 70px;
                max-height: 20px;
                font-size: 10px;
            }
        """)
        conditional_grid.addWidget(self.insert_endif_btn, 1, 0)

        placeholder_main_layout.addLayout(conditional_grid)
        placeholder_main_layout.addStretch()

        editor_layout.addWidget(placeholder_widget)
        
        layout.addWidget(editor_group)
        
        # Buttons
        button_layout = QHBoxLayout()

        self.validate_btn = QPushButton("Validate Syntax")
        if not self.validate_btn.text().startswith(" "):
            self.validate_btn.setText(" " + self.validate_btn.text())
        self.validate_btn.clicked.connect(self.validate_and_show_results)
        button_layout.addWidget(self.validate_btn)

        button_layout.addStretch()


        layout.addLayout(button_layout)
        
        # Load templates
        self.load_templates()

    def _sanitize_template_name(self, name: str) -> str | None:
        """Sanitize template name for safe filesystem use.

        Returns sanitized name or None if invalid.
        """
        if not name or not name.strip():
            return None

        name = name.strip()

        # Check for path traversal attempts
        if '..' in name or '/' in name or '\\' in name:
            return None

        # Check for null bytes
        if '\x00' in name:
            return None

        # Windows reserved names
        reserved = {'CON', 'PRN', 'AUX', 'NUL', 'COM1', 'COM2', 'COM3', 'COM4',
                    'COM5', 'COM6', 'COM7', 'COM8', 'COM9', 'LPT1', 'LPT2',
                    'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9'}
        if name.upper() in reserved:
            return None

        # Forbidden characters on Windows
        forbidden = '<>:"/\\|?*'
        if any(c in name for c in forbidden):
            return None

        # Length limit
        if len(name) > 200:
            return None

        return name

    def _show_invalid_name_warning(self):
        """Show warning dialog for invalid template name."""
        QMessageBox.warning(
            self,
            "Invalid Name",
            "Invalid template name. Names cannot contain path separators, "
            "special characters (<>:\"/\\|?*), or be Windows reserved names."
        )

    def load_templates(self):
        """Load and display available templates"""
        from imxup import load_templates
        templates = load_templates()

        self.template_list.clear()
        for template_name in templates.keys():
            # Build display name with indicators
            display_name = template_name
            is_builtin = template_name in BUILTIN_TEMPLATES
            is_active = template_name == self.active_template_name

            if is_builtin:
                display_name += " (Built-in)"
            if is_active:
                display_name += " \u2605"  # Star character

            # Create list item with display name
            item = QListWidgetItem(display_name)
            # Store actual template name in UserRole
            item.setData(Qt.ItemDataRole.UserRole, template_name)

            # Use italic font for built-in templates
            if is_builtin:
                font = item.font()
                font.setItalic(True)
                item.setFont(font)

            self.template_list.addItem(item)

        # Select the current template if available, otherwise select first template
        if self.template_list.count() > 0:
            # Try to find and select the initial template
            found_template = False
            for i in range(self.template_list.count()):
                item = self.template_list.item(i)
                actual_name = item.data(Qt.ItemDataRole.UserRole) or item.text()
                if actual_name == self.initial_template:
                    self.template_list.setCurrentRow(i)
                    found_template = True
                    break

            # If initial template not found, select first template
            if not found_template:
                self.template_list.setCurrentRow(0)
    
    def on_template_selected(self):
        """Handle template selection"""
        current_item = self.template_list.currentItem()
        if current_item:
            # Get actual template name from UserRole data
            template_name = current_item.data(Qt.ItemDataRole.UserRole)
            if template_name is None:
                template_name = current_item.text()

            # Before switching, save current content to pending_changes if modified
            if self.current_template_name and self.current_template_name not in BUILTIN_TEMPLATES:
                current_content = self.template_editor.toPlainText()
                # Always store the current content in pending_changes when switching
                if self.unsaved_changes:
                    self.pending_changes[self.current_template_name] = current_content

            self.load_template_content(template_name)
            self.current_template_name = template_name
            # Reset unsaved_changes for the newly selected template
            # (it will be marked as having changes if pending_changes has content for it)
            self.unsaved_changes = template_name in self.pending_changes

            # Disable editing for built-in templates
            is_builtin = template_name in BUILTIN_TEMPLATES
            self.template_editor.setReadOnly(is_builtin)
            self.rename_btn.setEnabled(not is_builtin)
            self.delete_btn.setEnabled(not is_builtin)
            self.copy_btn.setEnabled(True)

            if is_builtin:
                self.template_editor.setProperty("class", "template-editor-placeholder")
            else:
                self.template_editor.setProperty("class", "template-editor")
                self.template_editor.style().polish(self.template_editor)
        else:
            self.template_editor.clear()
            self.current_template_name = None
            self.unsaved_changes = False
            self.rename_btn.setEnabled(False)
            self.delete_btn.setEnabled(False)
            self.copy_btn.setEnabled(False)
    
    def load_template_content(self, template_name):
        """Load template content into editor.

        Checks pending_changes first, then loads from disk.
        """
        # Check pending_changes first
        if template_name in self.pending_changes:
            self.template_editor.setPlainText(self.pending_changes[template_name])
            return

        # Load from disk
        from imxup import load_templates
        templates = load_templates()

        if template_name in templates:
            self.template_editor.setPlainText(templates[template_name])
        else:
            self.template_editor.clear()
    
    def insert_placeholder(self, placeholder):
        """Insert a placeholder at cursor position"""
        cursor = self.template_editor.textCursor()
        cursor.insertText(placeholder)
        self.template_editor.setFocus()

    def insert_text(self, text):
        """Insert text at cursor position"""
        cursor = self.template_editor.textCursor()
        cursor.insertText(text)
        self.template_editor.setFocus()

    def insert_conditional_helper(self):
        """Show dialog to help insert a conditional"""
        dialog = ConditionalInsertDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            conditional_text = dialog.get_conditional_text()
            self.insert_text(conditional_text)

    def validate_template_syntax(self, content):
        """Validate template syntax for conditionals and BBCode.

        Returns: (is_valid, list_of_errors)
        """
        import re
        errors = []

        # Check for unmatched conditional tags
        if_count = len(re.findall(r'\[if\s+\w+', content))
        endif_count = content.count('[/if]')

        if if_count != endif_count:
            errors.append(f"Unmatched conditional tags: {if_count} [if] but {endif_count} [/if]")

        # Check for invalid conditional syntax
        all_ifs = re.findall(r'\[if[^\]]*\]', content)
        valid_pattern = re.compile(r'^\[if\s+\w+(?:=[^\]]+)?\]$')
        for if_tag in all_ifs:
            if not valid_pattern.match(if_tag):
                errors.append(f"Invalid [if] syntax: '{if_tag}' - must be [if placeholder] or [if placeholder=value]")
                break

        # Check for orphaned [else] tags
        lines = content.split('\n')
        in_conditional = 0
        for line_num, line in enumerate(lines, 1):
            if '[if' in line:
                in_conditional += line.count('[if')
            if '[else]' in line and in_conditional <= 0:
                errors.append(f"Line {line_num}: [else] tag found outside of conditional block")
            if '[/if]' in line:
                in_conditional -= line.count('[/if]')

        # Validate BBCode with stack-based validator
        validator = BBCodeValidator()
        bbcode_valid, bbcode_errors = validator.validate(content)
        errors.extend(bbcode_errors)

        return (len(errors) == 0, errors)

    def validate_and_show_results(self):
        """Validate template and show results in a dialog"""
        content = self.template_editor.toPlainText()
        is_valid, errors = self.validate_template_syntax(content)

        if is_valid:
            QMessageBox.information(
                self,
                "Validation Passed",
                "No syntax errors found!\n\nYour template looks good."
            )
        else:
            # Limit to first 10 errors
            display_errors = errors[:10]
            error_msg = "Template has syntax errors:\n\n" + "\n".join(f"• {err}" for err in display_errors)
            if len(errors) > 10:
                error_msg += f"\n\n... and {len(errors) - 10} more errors"
            QMessageBox.warning(
                self,
                "Syntax Errors",
                error_msg
            )

    def on_template_changed(self):
        """Handle template content changes"""
        # Only track changes if not a built-in template
        if self.current_template_name and self.current_template_name not in BUILTIN_TEMPLATES:
            # Store change in pending changes
            self.pending_changes[self.current_template_name] = self.template_editor.toPlainText()
            self.unsaved_changes = True
    
    def create_new_template(self):
        """Create a new template.

        Adds template to UI and tracks in pending_new_templates.
        Does not write to disk until commit_all_changes() is called.
        """
        # Save current editor content to pending if modified
        if self.current_template_name and self.current_template_name not in BUILTIN_TEMPLATES:
            if self.unsaved_changes:
                self.pending_changes[self.current_template_name] = self.template_editor.toPlainText()

        name, ok = QInputDialog.getText(self, "New Template", "Template name:")
        if ok and name:
            # Sanitize the template name for security
            name = self._sanitize_template_name(name)
            if name is None:
                self._show_invalid_name_warning()
                return

            # Check if template already exists (on disk or in pending)
            from imxup import load_templates
            templates = load_templates()
            if name in templates or name in self.pending_new_templates:
                QMessageBox.warning(self, "Error", f"Template '{name}' already exists!")
                return

            # Also check if name is in pending deleted (restore it)
            if name in self.pending_deleted_templates:
                self.pending_deleted_templates.discard(name)

            # Track as new template
            self.pending_new_templates.add(name)
            self.pending_changes[name] = ""  # Empty content for new template

            # Create list item with display name
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.template_list.addItem(item)
            self.template_list.setCurrentItem(item)

            # Clear editor for new template
            self.template_editor.clear()
            self.current_template_name = name
            self.unsaved_changes = True
    
    def rename_template(self):
        """Rename the current template.

        Renames immediately on disk (rename is atomic and doesn't need pending).
        """
        current_item = self.template_list.currentItem()
        if not current_item:
            return

        # Get actual template name from UserRole data
        old_name = current_item.data(Qt.ItemDataRole.UserRole)
        if old_name is None:
            old_name = current_item.text()

        if old_name in BUILTIN_TEMPLATES:
            QMessageBox.warning(self, "Error", "Cannot rename built-in templates!")
            return

        new_name, ok = QInputDialog.getText(self, "Rename Template", "New name:", text=old_name)
        if ok and new_name:
            # Sanitize the template name for security
            new_name = self._sanitize_template_name(new_name)
            if new_name is None:
                self._show_invalid_name_warning()
                return

            # Check if new name already exists
            from imxup import load_templates
            templates = load_templates()
            if new_name in templates or new_name in self.pending_new_templates:
                QMessageBox.warning(self, "Error", f"Template '{new_name}' already exists!")
                return

            # Handle pending state updates
            if old_name in self.pending_new_templates:
                # Template was created in this session, just update tracking
                self.pending_new_templates.discard(old_name)
                self.pending_new_templates.add(new_name)
                if old_name in self.pending_changes:
                    self.pending_changes[new_name] = self.pending_changes.pop(old_name)
            else:
                # Template exists on disk, rename file
                from imxup import get_template_path
                template_path = get_template_path()
                old_file = os.path.join(template_path, f"{old_name}.template.txt")
                new_file = os.path.join(template_path, f"{new_name}.template.txt")

                try:
                    if os.path.exists(old_file):
                        os.rename(old_file, new_file)
                    # Update pending changes key if any
                    if old_name in self.pending_changes:
                        self.pending_changes[new_name] = self.pending_changes.pop(old_name)
                except OSError as e:
                    QMessageBox.warning(self, "Error", f"Failed to rename template: {str(e)}")
                    return

            # Update list item
            current_item.setText(new_name)
            current_item.setData(Qt.ItemDataRole.UserRole, new_name)
            self.current_template_name = new_name
    
    def delete_template(self):
        """Delete the current template.

        Marks template for deletion in pending_deleted_templates.
        Does not delete from disk until commit_all_changes() is called.
        """
        current_item = self.template_list.currentItem()
        if not current_item:
            return

        # Get actual template name from UserRole data
        template_name = current_item.data(Qt.ItemDataRole.UserRole)
        if template_name is None:
            template_name = current_item.text()

        if template_name in BUILTIN_TEMPLATES:
            QMessageBox.warning(self, "Error", "Cannot delete built-in templates!")
            return

        reply = QMessageBox.question(
            self,
            "Delete Template",
            f"Are you sure you want to delete template '{template_name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            # Remove from UI
            self.template_list.takeItem(self.template_list.currentRow())
            self.template_editor.clear()

            # Track deletion
            if template_name in self.pending_new_templates:
                # Template was created in this session, just remove from pending
                self.pending_new_templates.discard(template_name)
            else:
                # Template exists on disk, mark for deletion
                self.pending_deleted_templates.add(template_name)

            # Remove from pending changes if present
            self.pending_changes.pop(template_name, None)

            self.unsaved_changes = False
            self.current_template_name = None

    def copy_template(self):
        """Copy the current template to a new template.

        Creates a copy with pending changes, does not write to disk.
        """
        current_item = self.template_list.currentItem()
        if not current_item:
            return

        # Get actual template name from UserRole data
        source_name = current_item.data(Qt.ItemDataRole.UserRole)
        if source_name is None:
            source_name = current_item.text()

        # Get content (from pending or editor)
        if source_name in self.pending_changes:
            content = self.pending_changes[source_name]
        else:
            content = self.template_editor.toPlainText()

        # Prompt for new name
        new_name, ok = QInputDialog.getText(
            self, "Copy Template",
            "New template name:",
            text=f"{source_name} (copy)"
        )
        if ok and new_name:
            # Sanitize the template name for security
            new_name = self._sanitize_template_name(new_name)
            if new_name is None:
                self._show_invalid_name_warning()
                return

            # Check if template already exists
            from imxup import load_templates
            templates = load_templates()
            if new_name in templates or new_name in self.pending_new_templates:
                QMessageBox.warning(self, "Error", f"Template '{new_name}' already exists!")
                return

            # Track as new template with copied content
            self.pending_new_templates.add(new_name)
            self.pending_changes[new_name] = content

            # Create list item
            item = QListWidgetItem(new_name)
            item.setData(Qt.ItemDataRole.UserRole, new_name)
            self.template_list.addItem(item)
            self.template_list.setCurrentItem(item)

            self.current_template_name = new_name
            self.unsaved_changes = True

    def commit_all_changes(self) -> bool:
        """Commit all pending changes to disk.

        Called by settings dialog Apply/OK buttons.

        Returns:
            True if all changes were saved successfully, False otherwise.
        """
        from imxup import get_template_path
        template_path = get_template_path()

        errors = []

        # Save current editor content to pending if modified
        if self.current_template_name and self.current_template_name not in BUILTIN_TEMPLATES:
            current_content = self.template_editor.toPlainText()
            if self.current_template_name in self.pending_changes or self.unsaved_changes:
                self.pending_changes[self.current_template_name] = current_content

        # Process deletions first
        for template_name in self.pending_deleted_templates:
            template_file = os.path.join(template_path, f"{template_name}.template.txt")
            try:
                if os.path.exists(template_file):
                    os.remove(template_file)
            except OSError as e:
                errors.append(f"Failed to delete '{template_name}': {e}")

        # Save all pending changes
        for template_name, content in self.pending_changes.items():
            if template_name in self.pending_deleted_templates:
                continue
            if template_name in BUILTIN_TEMPLATES:
                continue

            template_file = os.path.join(template_path, f"{template_name}.template.txt")
            try:
                with open(template_file, 'w', encoding='utf-8') as f:
                    f.write(content)
            except OSError as e:
                errors.append(f"Failed to save '{template_name}': {e}")

        if errors:
            QMessageBox.warning(self, "Save Errors", "\n".join(errors))
            return False

        # Clear pending state
        self.pending_changes.clear()
        self.pending_new_templates.clear()
        self.pending_deleted_templates.clear()
        self.unsaved_changes = False

        return True

    def discard_all_changes(self):
        """Discard all pending changes.

        Called when Cancel is clicked in settings dialog.
        """
        self.pending_changes.clear()
        self.pending_new_templates.clear()
        self.pending_deleted_templates.clear()
        self.unsaved_changes = False
        # Reload templates from disk
        self.load_templates()

    def has_pending_changes(self) -> bool:
        """Check if there are any pending changes.

        Returns:
            True if there are unsaved changes, False otherwise.
        """
        # Check if current editor has unsaved content
        if self.current_template_name and self.current_template_name not in BUILTIN_TEMPLATES:
            if self.unsaved_changes:
                return True

        return bool(
            self.pending_changes
            or self.pending_new_templates
            or self.pending_deleted_templates
        )

    def closeEvent(self, event):
        """Handle dialog closing.

        When embedded in settings dialog, changes are managed by the parent.
        Just accept the close event without prompting.
        """
        # When used as embedded widget, let the settings dialog handle save/discard
        event.accept()