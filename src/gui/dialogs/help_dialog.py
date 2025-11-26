#!/usr/bin/env python3
"""
Enhanced Help Dialog for imx.to gallery uploader
Features markdown rendering, navigation tree, and search functionality
"""

import os
from typing import Dict, List, Tuple
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTextEdit, QLineEdit,
    QDialogButtonBox, QApplication, QTreeWidget, QTreeWidgetItem,
    QSplitter, QLabel, QPushButton
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QIcon, QFont


class HelpDialog(QDialog):
    """Enhanced help dialog with navigation tree and search"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Help & Documentation")
        self.setModal(False)  # Allow interaction with main window
        self.resize(1000, 700)
        self._center_on_parent()

        # Store documentation content
        self.docs: Dict[str, Tuple[str, str]] = {}  # key: (title, content)
        self.current_doc: str = ""

        # Main layout
        layout = QVBoxLayout(self)

        # Search bar at top
        search_layout = QHBoxLayout()
        search_label = QLabel("Search:")
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search help topics...")
        self.search_input.textChanged.connect(self._on_search)
        self.search_button = QPushButton("Find")
        self.search_button.clicked.connect(self._find_in_content)

        search_layout.addWidget(search_label)
        search_layout.addWidget(self.search_input)
        search_layout.addWidget(self.search_button)
        layout.addLayout(search_layout)

        # Splitter for tree and content
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left side: Navigation tree
        self.tree = QTreeWidget()
        self.tree.setHeaderLabel("Topics")
        self.tree.setMinimumWidth(250)
        self.tree.setMaximumWidth(400)
        self.tree.itemClicked.connect(self._on_tree_item_clicked)
        splitter.addWidget(self.tree)

        # Right side: Content viewer
        self.content_viewer = QTextEdit()
        self.content_viewer.setReadOnly(True)
        self.content_viewer.setProperty("class", "help-content")

        # Set font with emoji support
        font = QFont()
        font.setFamilies(["Segoe UI Emoji", "Segoe UI", "Arial", "sans-serif"])
        font.setPointSize(10)
        self.content_viewer.setFont(font)

        splitter.addWidget(self.content_viewer)

        # Set initial splitter sizes (30% tree, 70% content)
        splitter.setSizes([300, 700])
        layout.addWidget(splitter)

        # Load documentation
        self._load_documentation()

        # Close button
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _load_documentation(self):
        """Load all documentation files from docs/user/ directory"""
        docs_dir = os.path.join(os.getcwd(), "docs", "user")

        if not os.path.exists(docs_dir):
            self._show_error("Documentation directory not found")
            return

        # Documentation structure: category -> files
        doc_structure = {
            "Getting Started": [
                ("Overview", "HELP_CONTENT.md"),
                ("Quick Start", "quick-start.md"),
            ],
            "Features": [
                ("Multi-Host Upload", "multi-host-upload.md"),
                ("BBCode Templates", "bbcode-templates.md"),
                ("GUI Guide", "gui-guide.md"),
                ("GUI Improvements", "gui-improvements.md"),
            ],
            "Reference": [
                ("Keyboard Shortcuts", "keyboard-shortcuts.md"),
                ("Troubleshooting", "troubleshooting.md"),
            ],
            "Testing": [
                ("Quick Start", "TESTING_QUICKSTART.md"),
                ("Status", "TESTING_STATUS.md"),
            ],
        }

        # Build tree structure
        for category, files in doc_structure.items():
            category_item = QTreeWidgetItem(self.tree)
            category_item.setText(0, category)
            category_item.setExpanded(True)

            for title, filename in files:
                file_path = os.path.join(docs_dir, filename)
                item = QTreeWidgetItem(category_item)
                item.setText(0, title)
                item.setData(0, Qt.ItemDataRole.UserRole, filename)

                # Load file content
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        self.docs[filename] = (title, content)
                except FileNotFoundError:
                    self.docs[filename] = (title, f"Documentation file not found: {filename}")
                except Exception as e:
                    self.docs[filename] = (title, f"Error loading documentation: {str(e)}")

        # Select and display first item
        if self.tree.topLevelItemCount() > 0:
            first_category = self.tree.topLevelItem(0)
            if first_category.childCount() > 0:
                first_item = first_category.child(0)
                self.tree.setCurrentItem(first_item)
                self._on_tree_item_clicked(first_item, 0)

    def _on_tree_item_clicked(self, item: QTreeWidgetItem, column: int):
        """Handle tree item click"""
        filename = item.data(0, Qt.ItemDataRole.UserRole)
        if not filename:
            return  # Category item, not a document

        if filename in self.docs:
            title, content = self.docs[filename]
            self.current_doc = filename
            self._display_content(title, content)

    def _display_content(self, title: str, content: str):
        """Display markdown content in the viewer"""
        try:
            # Try to render as markdown
            from markdown import markdown
            html_content = markdown(content, extensions=['extra', 'codehilite', 'toc'])
            html = f"""
            <html>
            <head>
                <style>
                    body {{
                        font-family: 'Segoe UI Emoji', 'Segoe UI', 'Noto Color Emoji', -apple-system, BlinkMacSystemFont, Arial, sans-serif;
                        line-height: 1.6;
                        padding: 20px;
                        max-width: 900px;
                    }}
                    h1, h2, h3 {{ color: #2c3e50; }}
                    h1 {{ border-bottom: 2px solid #3498db; padding-bottom: 10px; }}
                    h2 {{ border-bottom: 1px solid #bdc3c7; padding-bottom: 5px; margin-top: 30px; }}
                    code {{
                        background-color: #f4f4f4;
                        padding: 2px 6px;
                        border-radius: 3px;
                        font-family: 'Courier New', monospace;
                    }}
                    pre {{
                        background-color: #f4f4f4;
                        padding: 15px;
                        border-radius: 5px;
                        overflow-x: auto;
                    }}
                    pre code {{
                        background-color: transparent;
                        padding: 0;
                    }}
                    ul, ol {{ margin-left: 20px; }}
                    li {{ margin-bottom: 5px; }}
                    table {{
                        border-collapse: collapse;
                        width: 100%;
                        margin: 15px 0;
                    }}
                    th, td {{
                        border: 1px solid #ddd;
                        padding: 8px;
                        text-align: left;
                    }}
                    th {{
                        background-color: #f2f2f2;
                        font-weight: bold;
                    }}
                    blockquote {{
                        border-left: 4px solid #3498db;
                        margin: 15px 0;
                        padding-left: 15px;
                        color: #555;
                    }}
                    a {{ color: #3498db; text-decoration: none; }}
                    a:hover {{ text-decoration: underline; }}
                </style>
            </head>
            <body>
                <h1>{title}</h1>
                {html_content}
            </body>
            </html>
            """
            self.content_viewer.setHtml(html)
        except ImportError:
            # Fallback to plain text if markdown not available
            self.content_viewer.setPlainText(f"# {title}\n\n{content}")

    def _on_search(self, text: str):
        """Filter tree items based on search text"""
        if not text:
            # Show all items
            for i in range(self.tree.topLevelItemCount()):
                category = self.tree.topLevelItem(i)
                category.setHidden(False)
                for j in range(category.childCount()):
                    category.child(j).setHidden(False)
            return

        text = text.lower()
        # Hide items that don't match
        for i in range(self.tree.topLevelItemCount()):
            category = self.tree.topLevelItem(i)
            category_has_match = False

            for j in range(category.childCount()):
                item = category.child(j)
                filename = item.data(0, Qt.ItemDataRole.UserRole)

                # Check if title or content matches
                title_match = text in item.text(0).lower()
                content_match = False
                if filename in self.docs:
                    _, content = self.docs[filename]
                    content_match = text in content.lower()

                matches = title_match or content_match
                item.setHidden(not matches)
                if matches:
                    category_has_match = True

            category.setHidden(not category_has_match)

    def _find_in_content(self):
        """Find and highlight search term in current document"""
        search_text = self.search_input.text()
        if not search_text:
            return

        # Use QTextEdit's built-in find
        self.content_viewer.find(search_text)

    def _show_error(self, message: str):
        """Display error message in content viewer"""
        self.content_viewer.setHtml(f"""
        <html>
        <body style="padding: 20px; font-family: Arial, sans-serif;">
            <h2 style="color: #e74c3c;">⚠️ Error</h2>
            <p>{message}</p>
            <p style="color: #7f8c8d;">
                Please ensure the documentation files are available in the <code>docs/user/</code> directory.
            </p>
        </body>
        </html>
        """)

    def _center_on_parent(self):
        """Center dialog on parent window or screen"""
        if self.parent():
            parent_geo = self.parent().geometry()
            self.move(
                parent_geo.x() + (parent_geo.width() - self.width()) // 2,
                parent_geo.y() + (parent_geo.height() - self.height()) // 2
            )
        else:
            screen_geo = QApplication.primaryScreen().availableGeometry()
            self.move(
                (screen_geo.width() - self.width()) // 2,
                (screen_geo.height() - self.height()) // 2
            )

    def show_shortcuts_tab(self):
        """Open help dialog and navigate to keyboard shortcuts"""
        # Find and select keyboard shortcuts item
        for i in range(self.tree.topLevelItemCount()):
            category = self.tree.topLevelItem(i)
            for j in range(category.childCount()):
                item = category.child(j)
                if item.text(0) == "Keyboard Shortcuts":
                    self.tree.setCurrentItem(item)
                    self._on_tree_item_clicked(item, 0)
                    self.show()
                    return
        self.show()
