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

# Import markdown at module level to avoid 3-4 second delay on first use
try:
    from markdown import markdown as render_markdown
    MARKDOWN_AVAILABLE = True
except ImportError:
    MARKDOWN_AVAILABLE = False
    render_markdown = None


class HelpDialog(QDialog):
    """Enhanced help dialog with navigation tree and search"""

    # Emoji character to codepoint filename mapping (class constant to avoid recreation)
    EMOJI_TO_FILE = {
        # Original emojis
        "\U0001F680": "1f680",  # rocket
        "\U0001F4E4": "1f4e4",  # outbox
        "\U0001F4E6": "1f4e6",  # package
        "\U0001F3A8": "1f3a8",  # palette
        "\u2328": "2328",       # keyboard
        "\u2328\uFE0F": "2328", # keyboard with variation selector
        "\U0001F50D": "1f50d",  # magnifying glass
        "\U0001F527": "1f527",  # wrench
        "\U0001F41B": "1f41b",  # bug
        "\U0001F4CA": "1f4ca",  # bar chart
        "\U0001F7E1": "1f7e1",  # yellow circle
        "\U0001F535": "1f535",  # blue circle
        "\U0001F7E2": "1f7e2",  # green circle
        "\U0001F534": "1f534",  # red circle
        "\u23F8": "23f8",       # pause
        "\u23F8\uFE0F": "23f8", # pause with variation selector
        "\U0001F4A1": "1f4a1",  # lightbulb
        "\U0001F198": "1f198",  # SOS
        # Additional emojis (high priority first)
        "\u2705": "2705",       # check mark (22 uses)
        "\u274C": "274c",       # cross mark (7 uses)
        "\u2714": "2714",       # heavy check mark (4 uses)
        "\u2714\uFE0F": "2714", # heavy check with variation selector
        "\U0001F3AF": "1f3af",  # bullseye (4 uses)
        "\u2699": "2699",       # gear
        "\u2699\uFE0F": "2699", # gear with variation selector
        "\u26A0": "26a0",       # warning sign
        "\u26A0\uFE0F": "26a0", # warning with variation selector
        "\U0001F389": "1f389",  # party popper
        "\U0001F393": "1f393",  # graduation cap
        "\U0001F39B": "1f39b",  # control knobs
        "\U0001F39B\uFE0F": "1f39b",  # control knobs with variation selector
        "\U0001F3D7": "1f3d7",  # building construction
        "\U0001F3D7\uFE0F": "1f3d7",  # building construction with variation selector
        "\U0001F4C1": "1f4c1",  # file folder
        "\U0001F4C2": "1f4c2",  # open file folder
        "\U0001F4C8": "1f4c8",  # chart increasing
        "\U0001F4CB": "1f4cb",  # clipboard
        "\U0001F4F1": "1f4f1",  # mobile phone
        "\U0001F504": "1f504",  # counterclockwise arrows
        "\U0001F517": "1f517",  # link
        "\U0001F5C2": "1f5c2",  # card index dividers
        "\U0001F5C2\uFE0F": "1f5c2",  # card index with variation selector
        "\U0001F6E0": "1f6e0",  # hammer and wrench
        "\U0001F6E0\uFE0F": "1f6e0",  # hammer and wrench with variation selector
        "\U0001F7E0": "1f7e0",  # orange circle
    }

    # Pre-sorted emoji keys (longest first for correct replacement order)
    _EMOJI_KEYS_SORTED = sorted(EMOJI_TO_FILE.keys(), key=len, reverse=True)

    # Emoji directory path (computed once)
    _EMOJI_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))), "assets", "emoji")

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

    def _get_theme_css(self) -> str:
        """Generate theme-appropriate CSS for HTML content."""
        # Detect dark mode using palette luminance
        palette = QApplication.palette()
        is_dark = palette.window().color().lightness() < 128

        # Common styles
        common = """
            body {
                font-family: 'Segoe UI Emoji', 'Segoe UI', 'Noto Color Emoji', -apple-system, BlinkMacSystemFont, Arial, sans-serif;
                line-height: 1.6;
                padding: 20px;
                max-width: 900px;
            }
            code {
                padding: 2px 6px;
                border-radius: 3px;
                font-family: 'Courier New', monospace;
            }
            pre {
                padding: 15px;
                border-radius: 5px;
                overflow-x: auto;
            }
            pre code {
                background-color: transparent;
                padding: 0;
            }
            ul, ol { margin-left: 20px; }
            li { margin-bottom: 5px; }
            table {
                border-collapse: collapse;
                width: 100%;
                margin: 15px 0;
            }
            th, td {
                padding: 8px;
                text-align: left;
            }
            th { font-weight: bold; }
            h1, h2, h3, h4, h5, h6 {
                font-family: 'Segoe UI Emoji', 'Segoe UI', 'Noto Color Emoji', -apple-system, BlinkMacSystemFont, Arial, sans-serif;
            }
            blockquote {
                margin: 15px 0;
                padding-left: 15px;
            }
            a { text-decoration: none; }
            a:hover { text-decoration: underline; }
        """

        if is_dark:
            theme_colors = """
                body { color: #e0e0e0; background-color: #1e1e1e; }
                h1, h2, h3 { color: #7fbfff; }
                h1 { border-bottom: 2px solid #3498db; padding-bottom: 10px; }
                h2 { border-bottom: 1px solid #555; padding-bottom: 5px; margin-top: 30px; }
                code { background-color: #2a2a2a; color: #e0e0e0; }
                pre { background-color: #2a2a2a; }
                th, td { border: 1px solid #555; }
                th { background-color: #333; }
                blockquote { border-left: 4px solid #3498db; color: #aaa; }
                a { color: #5dade2; }
            """
        else:
            theme_colors = """
                body { color: #333; background-color: #ffffff; }
                h1, h2, h3 { color: #2c3e50; }
                h1 { border-bottom: 2px solid #3498db; padding-bottom: 10px; }
                h2 { border-bottom: 1px solid #bdc3c7; padding-bottom: 5px; margin-top: 30px; }
                code { background-color: #f4f4f4; color: #333; }
                pre { background-color: #f4f4f4; }
                th, td { border: 1px solid #ddd; }
                th { background-color: #f2f2f2; }
                blockquote { border-left: 4px solid #3498db; color: #555; }
                a { color: #3498db; }
            """

        return common + theme_colors

    def _wrap_emojis(self, html: str) -> str:
        """Replace emoji characters with Twemoji PNG images.

        Args:
            html: HTML content that may contain emoji characters.

        Returns:
            HTML with emoji characters replaced by img tags pointing to local PNGs.
        """
        result = html
        # Process longer sequences first (FE0F variants) to avoid partial matches
        for emoji in self._EMOJI_KEYS_SORTED:
            if emoji in result:
                codepoint = self.EMOJI_TO_FILE[emoji]
                img_path = os.path.join(self._EMOJI_DIR, f"{codepoint}.png")
                # Use file:// URL for Qt - normalize path separators
                file_url = "file:///" + img_path.replace("\\", "/")
                img_tag = f'<img src="{file_url}" width="20" height="20" style="vertical-align: middle;" />'
                result = result.replace(emoji, img_tag)

        return result

    def _display_content(self, title: str, content: str):
        """Display markdown content in the viewer"""
        if MARKDOWN_AVAILABLE:
            html_content = render_markdown(content, extensions=['extra', 'codehilite', 'toc'])
            # Wrap emoji characters in spans with emoji font-family for proper rendering
            html_content = self._wrap_emojis(html_content)
            html = f"""
            <html>
            <head>
                <style>
                    {self._get_theme_css()}
                </style>
            </head>
            <body>
                <h1>{self._wrap_emojis(title)}</h1>
                {html_content}
            </body>
            </html>
            """
            self.content_viewer.setHtml(html)
        else:
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
        palette = QApplication.palette()
        is_dark = palette.window().color().lightness() < 128

        bg_color = "#1e1e1e" if is_dark else "#ffffff"
        text_color = "#e0e0e0" if is_dark else "#333333"
        muted_color = "#aaaaaa" if is_dark else "#7f8c8d"

        self.content_viewer.setHtml(f"""
        <html>
        <body style="padding: 20px; font-family: Arial, sans-serif; background-color: {bg_color}; color: {text_color};">
            <h2 style="color: #e74c3c;">⚠️ Error</h2>
            <p>{message}</p>
            <p style="color: {muted_color};">
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
