"""
Template manager dialog for BBCode templates
Provides interface for creating, editing, and managing BBCode templates
"""

import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QListWidget,
    QPushButton, QLabel, QPlainTextEdit, QMessageBox, QInputDialog,
    QWidget, QGridLayout, QComboBox, QRadioButton, QButtonGroup, QLineEdit, QApplication
)
from PyQt6.QtGui import QSyntaxHighlighter, QTextCharFormat, QColor, QFont
from PyQt6.QtCore import Qt


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

        self.save_btn = QPushButton("Save Template")
        if not self.save_btn.text().startswith(" "):
            self.save_btn.setText(" " + self.save_btn.text())
        self.save_btn.clicked.connect(self.save_template)
        self.save_btn.setEnabled(False)
        button_layout.addWidget(self.save_btn)

        button_layout.addStretch()


        layout.addLayout(button_layout)
        
        # Load templates
        self.load_templates()
    
    def load_templates(self):
        """Load and display available templates"""
        from imxup import load_templates
        templates = load_templates()
        
        self.template_list.clear()
        for template_name in templates.keys():
            self.template_list.addItem(template_name)
        
        # Select the current template if available, otherwise select first template
        if self.template_list.count() > 0:
            # Try to find and select the initial template
            found_template = False
            for i in range(self.template_list.count()):
                if self.template_list.item(i).text() == self.initial_template:
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
            template_name = current_item.text()
            
            # Check for unsaved changes before switching
            if self.unsaved_changes and self.current_template_name:
                reply = QMessageBox.question(
                    self,
                    "Unsaved Changes",
                    f"You have unsaved changes to template '{self.current_template_name}'. Do you want to save them before switching?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Yes
                )
                
                if reply == QMessageBox.StandardButton.Yes:
                    # Save to the current template (not the one we're switching to)
                    content = self.template_editor.toPlainText()
                    from imxup import get_template_path
                    template_path = get_template_path()
                    template_file = os.path.join(template_path, f"{self.current_template_name}.template.txt")
                    
                    try:
                        with open(template_file, 'w', encoding='utf-8') as f:
                            f.write(content)
                        self.save_btn.setEnabled(False)
                        self.unsaved_changes = False
                    except Exception as e:
                        QMessageBox.warning(self, "Error", f"Failed to save template: {str(e)}")
                        # Restore the previous selection if save failed
                        for i in range(self.template_list.count()):
                            if self.template_list.item(i).text() == self.current_template_name:
                                self.template_list.setCurrentRow(i)
                                return
                        return
                elif reply == QMessageBox.StandardButton.Cancel:
                    # Restore the previous selection
                    for i in range(self.template_list.count()):
                        if self.template_list.item(i).text() == self.current_template_name:
                            self.template_list.setCurrentRow(i)
                            return
                    return
            
            self.load_template_content(template_name)
            self.current_template_name = template_name
            self.unsaved_changes = False
            
            # Disable editing for default template
            is_default = template_name == "default"
            self.template_editor.setReadOnly(is_default)
            self.rename_btn.setEnabled(not is_default)
            self.delete_btn.setEnabled(not is_default)
            self.save_btn.setEnabled(False)  # Will be enabled when content changes (if not default)
            
            if is_default:
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
    
    def load_template_content(self, template_name):
        """Load template content into editor"""
        from imxup import load_templates
        templates = load_templates()
        
        if template_name in templates:
            self.template_editor.setPlainText(templates[template_name])
        else:
            self.template_editor.clear()
        
        # Reset unsaved changes flag when loading content
        self.unsaved_changes = False
    
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
        # Valid: [if placeholder] or [if placeholder=value]
        # Find all [if ...] and check if they match the valid pattern
        all_ifs = re.findall(r'\[if[^\]]*\]', content)
        valid_pattern = re.compile(r'^\[if\s+\w+(?:=[^\]]+)?\]$')
        for if_tag in all_ifs:
            if not valid_pattern.match(if_tag):
                errors.append(f"Invalid [if] syntax: '{if_tag}' - must be [if placeholder] or [if placeholder=value]")
                break  # Only report first invalid one

        # Check for common BBCode mismatches
        bbcode_tags = {
            'b': (r'\[b\]', r'\[/b\]'),
            'i': (r'\[i\]', r'\[/i\]'),
            'u': (r'\[u\]', r'\[/u\]'),
            'url': (r'\[url[^\]]*\]', r'\[/url\]'),
            'img': (r'\[img[^\]]*\]', r'\[/img\]'),
            'code': (r'\[code\]', r'\[/code\]'),
            'quote': (r'\[quote\]', r'\[/quote\]'),
        }

        for tag_name, (open_pattern, close_pattern) in bbcode_tags.items():
            open_count = len(re.findall(open_pattern, content))
            close_count = len(re.findall(close_pattern, content))
            if open_count != close_count:
                errors.append(f"Unmatched [{tag_name}] tags: {open_count} opening but {close_count} closing")

        # Check for orphaned [else] tags (not between [if] and [/if])
        # This is a simple heuristic check
        lines = content.split('\n')
        in_conditional = 0
        for line_num, line in enumerate(lines, 1):
            if '[if' in line:
                in_conditional += line.count('[if')
            # Check [else] BEFORE processing [/if] to handle single-line conditionals
            if '[else]' in line and in_conditional <= 0:
                errors.append(f"Line {line_num}: [else] tag found outside of conditional block")
            if '[/if]' in line:
                in_conditional -= line.count('[/if]')

        return (len(errors) == 0, errors)

    def validate_and_show_results(self):
        """Validate template and show results in a dialog"""
        content = self.template_editor.toPlainText()
        is_valid, errors = self.validate_template_syntax(content)

        if is_valid:
            QMessageBox.information(
                self,
                "Validation Passed",
                "✓ No syntax errors found!\n\nYour template looks good."
            )
        else:
            error_msg = "Template has syntax errors:\n\n" + "\n".join(f"• {err}" for err in errors)
            QMessageBox.warning(
                self,
                "Syntax Errors",
                error_msg
            )

    def on_template_changed(self):
        """Handle template content changes"""
        # Only allow saving if not the default template
        if self.current_template_name != "default":
            self.save_btn.setEnabled(True)
            self.unsaved_changes = True
    
    def create_new_template(self):
        """Create a new template"""
        # Check for unsaved changes before creating new template
        if self.unsaved_changes and self.current_template_name:
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                f"You have unsaved changes to template '{self.current_template_name}'. Do you want to save them before creating a new template?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                self.save_template()
            elif reply == QMessageBox.StandardButton.Cancel:
                return
        
        name, ok = QInputDialog.getText(self, "New Template", "Template name:")
        if ok and name.strip():
            name = name.strip()
            
            # Check if template already exists
            from imxup import load_templates
            templates = load_templates()
            if name in templates:
                QMessageBox.warning(self, "Error", f"Template '{name}' already exists!")
                return
            
            # Add to list and select it
            self.template_list.addItem(name)
            self.template_list.setCurrentItem(self.template_list.item(self.template_list.count() - 1))
            
            # Clear editor for new template
            self.template_editor.clear()
            self.current_template_name = name
            self.unsaved_changes = True
            self.save_btn.setEnabled(True)
    
    def rename_template(self):
        """Rename the current template"""
        current_item = self.template_list.currentItem()
        if not current_item:
            return
        
        old_name = current_item.text()
        if old_name == "default":
            QMessageBox.warning(self, "Error", "Cannot rename the default template!")
            return
        
        new_name, ok = QInputDialog.getText(self, "Rename Template", "New name:", text=old_name)
        if ok and new_name.strip():
            new_name = new_name.strip()
            
            # Check if new name already exists
            from imxup import load_templates
            templates = load_templates()
            if new_name in templates:
                QMessageBox.warning(self, "Error", f"Template '{new_name}' already exists!")
                return
            
            # Rename the template file
            from imxup import get_template_path
            template_path = get_template_path()
            old_file = os.path.join(template_path, f"{old_name}.template.txt")
            new_file = os.path.join(template_path, f"{new_name}.template.txt")
            
            try:
                os.rename(old_file, new_file)
                current_item.setText(new_name)
                QMessageBox.information(self, "Success", f"Template renamed to '{new_name}'")
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to rename template: {str(e)}")
    
    def delete_template(self):
        """Delete the current template"""
        current_item = self.template_list.currentItem()
        if not current_item:
            return
        
        template_name = current_item.text()
        if template_name == "default":
            QMessageBox.warning(self, "Error", "Cannot delete the default template!")
            return
        
        # Check for unsaved changes before deleting
        if self.unsaved_changes and self.current_template_name == template_name:
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                f"You have unsaved changes to template '{template_name}'. Do you want to save them before deleting?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                self.save_template()
            elif reply == QMessageBox.StandardButton.Cancel:
                return
        
        reply = QMessageBox.question(
            self,
            "Delete Template",
            f"Are you sure you want to delete template '{template_name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            # Delete the template file
            from imxup import get_template_path
            template_path = get_template_path()
            template_file = os.path.join(template_path, f"{template_name}.template.txt")
            
            try:
                os.remove(template_file)
                self.template_list.takeItem(self.template_list.currentRow())
                self.template_editor.clear()
                self.save_btn.setEnabled(False)
                self.unsaved_changes = False
                self.current_template_name = None
                QMessageBox.information(self, "Success", f"Template '{template_name}' deleted")
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to delete template: {str(e)}")
    
    def save_template(self):
        """Save the current template"""
        current_item = self.template_list.currentItem()
        if not current_item:
            return

        template_name = current_item.text()
        content = self.template_editor.toPlainText()

        # Validate syntax before saving
        is_valid, errors = self.validate_template_syntax(content)
        if not is_valid:
            error_msg = "Template has syntax errors:\n\n" + "\n".join(f"• {err}" for err in errors)
            error_msg += "\n\nDo you want to save anyway?"

            reply = QMessageBox.question(
                self,
                "Syntax Errors Detected",
                error_msg,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )

            if reply != QMessageBox.StandardButton.Yes:
                return

        # Save the template file
        from imxup import get_template_path
        template_path = get_template_path()
        template_file = os.path.join(template_path, f"{template_name}.template.txt")

        try:
            with open(template_file, 'w', encoding='utf-8') as f:
                f.write(content)
            self.save_btn.setEnabled(False)
            self.unsaved_changes = False
            QMessageBox.information(self, "Success", f"Template '{template_name}' saved")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to save template: {str(e)}")
    
    def closeEvent(self, event):
        """Handle dialog closing with unsaved changes check"""
        if self.unsaved_changes and self.current_template_name:
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                f"You have unsaved changes to template '{self.current_template_name}'. Do you want to save them before closing?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                # Try to save the template
                current_item = self.template_list.currentItem()
                if current_item:
                    template_name = current_item.text()
                    content = self.template_editor.toPlainText()
                    
                    # Save the template file
                    from imxup import get_template_path
                    template_path = get_template_path()
                    template_file = os.path.join(template_path, f"{template_name}.template.txt")
                    
                    try:
                        with open(template_file, 'w', encoding='utf-8') as f:
                            f.write(content)
                        self.save_btn.setEnabled(False)
                        self.unsaved_changes = False
                        event.accept()
                    except Exception as e:
                        QMessageBox.warning(self, "Error", f"Failed to save template: {str(e)}")
                        event.ignore()
                else:
                    event.accept()
            elif reply == QMessageBox.StandardButton.No:
                event.accept()
            else:  # Cancel
                event.ignore()
        else:
            event.accept()