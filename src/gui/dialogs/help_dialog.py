#!/usr/bin/env python3
"""
Enhanced Help Dialog for imx.to gallery uploader
Features markdown rendering, navigation tree, and search functionality

Uses QThread for non-blocking document loading to keep UI responsive.
"""

import os
from typing import Dict, List, Tuple, Optional
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTextBrowser, QLineEdit,
    QDialogButtonBox, QApplication, QTreeWidget, QTreeWidgetItem,
    QSplitter, QLabel, QPushButton
)
from PyQt6.QtCore import QUrl
import webbrowser
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QColor

# Import markdown at module level to avoid 3-4 second delay on first use
try:
    from markdown import markdown as render_markdown
    MARKDOWN_AVAILABLE = True
except ImportError:
    MARKDOWN_AVAILABLE = False
    render_markdown = None


class DocumentLoaderThread(QThread):
    """Background thread for loading and parsing documentation files.

    This thread handles all heavy operations:
    - File I/O (reading markdown files)
    - Markdown parsing with extensions
    - Emoji wrapping for PNG replacement

    Signals are emitted as documents become ready, allowing progressive
    loading without blocking the UI.
    """

    # Emitted when a document is ready: (filename, title, rendered_html)
    document_ready = pyqtSignal(str, str, str)
    # Emitted when all documents have been loaded
    all_loaded = pyqtSignal()
    # Emitted on error: (error_message)
    error = pyqtSignal(str)

    def __init__(
        self,
        docs_dir: str,
        doc_structure: Dict[str, List[Tuple[str, str]]],
        theme_css: str,
        parent: Optional[QThread] = None
    ):
        """Initialize the document loader thread.

        Args:
            docs_dir: Path to the documentation directory
            doc_structure: Dictionary mapping category names to list of (title, filename) tuples
            theme_css: Pre-computed CSS for the current theme
            parent: Optional parent QObject
        """
        super().__init__(parent)
        self.docs_dir = docs_dir
        self.doc_structure = doc_structure
        self.theme_css = theme_css
        self._stop_requested = False

        # Store references needed for rendering (class constants from HelpDialog)
        self._emoji_keys_sorted = HelpDialog._EMOJI_KEYS_SORTED
        self._emoji_to_file = HelpDialog.EMOJI_TO_FILE
        self._emoji_dir = HelpDialog._EMOJI_DIR

    def stop(self):
        """Request the thread to stop processing."""
        self._stop_requested = True

    def run(self):
        """Load and parse all documentation files in background.

        Emits document_ready signal for each file as it's processed,
        allowing the UI to progressively display content.
        """
        try:
            for category, files in self.doc_structure.items():
                if self._stop_requested:
                    return

                for title, filename in files:
                    if self._stop_requested:
                        return

                    file_path = os.path.join(self.docs_dir, filename)
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()

                        # Parse markdown in background thread (the expensive operation)
                        if MARKDOWN_AVAILABLE:
                            html_content = render_markdown(
                                content,
                                extensions=['extra', 'codehilite', 'toc']
                            )
                            html_content = self._wrap_emojis(html_content)
                            html = self._build_html(title, html_content)
                        else:
                            html = f"<pre>{title}\n\n{content}</pre>"

                        # Emit signal with rendered content
                        self.document_ready.emit(filename, title, html)

                    except FileNotFoundError:
                        error_html = self._build_error_html(
                            title,
                            f"Documentation file not found: {filename}"
                        )
                        self.document_ready.emit(filename, title, error_html)
                    except Exception as e:
                        error_html = self._build_error_html(
                            title,
                            f"Error loading documentation: {str(e)}"
                        )
                        self.document_ready.emit(filename, title, error_html)

            if not self._stop_requested:
                self.all_loaded.emit()

        except Exception as e:
            self.error.emit(str(e))

    def _wrap_emojis(self, html: str) -> str:
        """Replace emoji characters with Twemoji PNG images.

        Args:
            html: HTML content that may contain emoji characters.

        Returns:
            HTML with emoji characters replaced by img tags pointing to local PNGs.
        """
        result = html
        # Process longer sequences first (FE0F variants) to avoid partial matches
        for emoji in self._emoji_keys_sorted:
            if emoji in result:
                codepoint = self._emoji_to_file[emoji]
                img_path = os.path.join(self._emoji_dir, f"{codepoint}.png")
                # Use file:// URL for Qt - normalize path separators
                file_url = "file:///" + img_path.replace("\\", "/")
                img_tag = f'<img src="{file_url}" width="20" height="20" style="vertical-align: middle;" />'
                result = result.replace(emoji, img_tag)

        return result

    def _build_html(self, title: str, html_content: str) -> str:
        """Build complete HTML document with CSS styling.

        Args:
            title: Document title
            html_content: Pre-rendered HTML content

        Returns:
            Complete HTML document string
        """
        wrapped_title = self._wrap_emojis(title)
        return f"""
        <html>
        <head>
            <style>
                {self.theme_css}
            </style>
        </head>
        <body>
            <h1>{wrapped_title}</h1>
            {html_content}
        </body>
        </html>
        """

    def _build_error_html(self, title: str, error_message: str) -> str:
        """Build HTML for error display.

        Args:
            title: Document title that failed to load
            error_message: Error description

        Returns:
            HTML string showing the error
        """
        return f"""
        <html>
        <head>
            <style>
                {self.theme_css}
            </style>
        </head>
        <body>
            <h1>{title}</h1>
            <p style="color: #e74c3c;">{error_message}</p>
        </body>
        </html>
        """


class HelpDialog(QDialog):
    """Enhanced help dialog with navigation tree and search.

    Uses a background QThread for loading and parsing documentation,
    keeping the UI fully responsive during the loading process.
    """

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

    # Documentation structure: category -> [(title, filename), ...]
    # Paths are relative to docs/user/
    DOC_STRUCTURE = {
        "Getting Started": [
            ("Overview", "reference/HELP_CONTENT.md"),
            ("Quick Start", "getting-started/quick-start.md"),
            ("Setup", "getting-started/setup.md"),
            ("Keyboard Shortcuts", "getting-started/keyboard-shortcuts.md"),
        ],
        "Guides": [
            ("GUI Guide", "guides/gui-guide.md"),
            ("Multi-Host Upload", "guides/multi-host-upload.md"),
            ("BBCode Templates", "guides/bbcode-templates.md"),
            ("Archive Management", "guides/archive-management.md"),
            ("Hooks System", "guides/hooks-system.md"),
        ],
        "Reference": [
            ("Features", "reference/FEATURES.md"),
            ("Quick Reference", "reference/quick-reference.md"),
            ("External Apps", "reference/external-apps-parameters.md"),
        ],
        "Troubleshooting": [
            ("FAQ", "troubleshooting/faq.md"),
            ("Troubleshooting Guide", "troubleshooting/troubleshooting.md"),
        ],
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Help & Documentation")
        self.setModal(False)  # Allow interaction with main window
        self.resize(1000, 700)
        self._center_on_parent()

        # Store documentation content and state
        self.docs: Dict[str, Tuple[str, str]] = {}  # filename: (title, raw_content)
        self._html_cache: Dict[str, str] = {}  # filename: rendered_html
        self._loaded_docs: set = set()  # Track which docs are loaded
        self.current_doc: str = ""
        self._loader_thread: Optional[DocumentLoaderThread] = None
        self._first_doc_displayed = False

        # Map filename to tree item for quick access
        self._filename_to_item: Dict[str, QTreeWidgetItem] = {}

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

        # Right side: Content viewer (QTextBrowser for link support)
        self.content_viewer = QTextBrowser()
        self.content_viewer.setReadOnly(True)
        self.content_viewer.setProperty("class", "help-content")
        self.content_viewer.setOpenExternalLinks(False)  # We handle all links
        self.content_viewer.anchorClicked.connect(self._on_link_clicked)

        # Set font with emoji support
        font = QFont()
        font.setFamilies(["Segoe UI Emoji", "Segoe UI", "Arial", "sans-serif"])
        font.setPointSize(10)
        self.content_viewer.setFont(font)

        splitter.addWidget(self.content_viewer)

        # Set initial splitter sizes (30% tree, 70% content)
        splitter.setSizes([300, 700])
        layout.addWidget(splitter)

        # Build tree structure immediately (fast operation)
        self._build_tree_structure()

        # Show loading message
        self._show_loading_message()

        # Start background loading
        self._start_document_loading()

        # Close button
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _build_tree_structure(self):
        """Build the navigation tree structure.

        Creates all tree items immediately (fast operation) with loading
        indicators. Items are updated as documents become available.
        """
        for category, files in self.DOC_STRUCTURE.items():
            category_item = QTreeWidgetItem(self.tree)
            category_item.setText(0, category)
            category_item.setExpanded(True)

            for title, filename in files:
                item = QTreeWidgetItem(category_item)
                # Show loading indicator in title
                item.setText(0, f"{title} (loading...)")
                item.setData(0, Qt.ItemDataRole.UserRole, filename)
                # Gray out until loaded
                item.setForeground(0, QColor(128, 128, 128))
                # Store reference for quick updates
                self._filename_to_item[filename] = item

    def _start_document_loading(self):
        """Start the background document loading thread."""
        from imxup import get_project_root
        docs_dir = os.path.join(get_project_root(), "docs", "user")

        if not os.path.exists(docs_dir):
            self._show_error("Documentation directory not found")
            return

        # Get current theme CSS before starting thread
        theme_css = self._get_theme_css()

        # Create and start loader thread
        self._loader_thread = DocumentLoaderThread(
            docs_dir=docs_dir,
            doc_structure=self.DOC_STRUCTURE,
            theme_css=theme_css,
            parent=self
        )

        # Connect signals
        self._loader_thread.document_ready.connect(self._on_document_ready)
        self._loader_thread.all_loaded.connect(self._on_all_loaded)
        self._loader_thread.error.connect(self._on_loader_error)

        # Start loading
        self._loader_thread.start()

    def _on_document_ready(self, filename: str, title: str, html: str):
        """Handle a document being ready from the loader thread.

        Args:
            filename: Document filename
            title: Document title
            html: Pre-rendered HTML content
        """
        # Store in cache
        self._html_cache[filename] = html
        self._loaded_docs.add(filename)

        # Update tree item appearance
        if filename in self._filename_to_item:
            item = self._filename_to_item[filename]
            item.setText(0, title)  # Remove "(loading...)"
            # Restore normal color
            palette = QApplication.palette()
            item.setForeground(0, palette.text().color())

        # Display first document automatically
        if not self._first_doc_displayed:
            self._first_doc_displayed = True
            if self.tree.topLevelItemCount() > 0:
                first_category = self.tree.topLevelItem(0)
                if first_category.childCount() > 0:
                    first_item = first_category.child(0)
                    first_filename = first_item.data(0, Qt.ItemDataRole.UserRole)
                    if first_filename == filename:
                        self.tree.setCurrentItem(first_item)
                        self.content_viewer.setHtml(html)
                        self.current_doc = filename

    def _on_all_loaded(self):
        """Handle all documents being loaded."""
        # If no document displayed yet, select first one
        if not self.current_doc and self._html_cache:
            if self.tree.topLevelItemCount() > 0:
                first_category = self.tree.topLevelItem(0)
                if first_category.childCount() > 0:
                    first_item = first_category.child(0)
                    self.tree.setCurrentItem(first_item)
                    self._on_tree_item_clicked(first_item, 0)

    def _on_loader_error(self, error_message: str):
        """Handle loader thread error.

        Args:
            error_message: Error description
        """
        self._show_error(f"Error loading documentation: {error_message}")

    def _on_tree_item_clicked(self, item: QTreeWidgetItem, column: int):
        """Handle tree item click.

        Args:
            item: Clicked tree item
            column: Column index (unused)
        """
        filename = item.data(0, Qt.ItemDataRole.UserRole)
        if not filename:
            return  # Category item, not a document

        self.current_doc = filename

        if filename in self._html_cache:
            # Document is ready - display immediately
            self.content_viewer.setHtml(self._html_cache[filename])
        else:
            # Document still loading - show loading indicator
            self._show_document_loading(item.text(0))

    def _on_link_clicked(self, url):
        """Handle link clicks in the content viewer.

        Routes external links to browser and internal .md links to tree navigation.
        """
        url_string = url.toString()
        scheme = url.scheme().lower()

        # External link - open in default browser (only allow safe schemes)
        if scheme in ('http', 'https'):
            webbrowser.open(url_string)
            return

        # Block dangerous schemes (javascript:, file:, data:, etc.)
        if scheme and scheme not in ('', 'file'):
            return

        # Anchor link (same page) - scroll to it
        if url_string.startswith('#'):
            self.content_viewer.scrollToAnchor(url.fragment())
            return

        # Internal .md link - navigate to the topic in tree
        if url_string.endswith('.md'):
            self._navigate_to_doc(url_string)

    def _navigate_to_doc(self, relative_path: str):
        """Navigate to an internal documentation link.

        Tries two resolution strategies to handle inconsistent link conventions.
        Only navigates to documents already in the tree (prevents path traversal).
        """
        def normalize(path: str) -> str:
            return os.path.normpath(path).replace("\\", "/")

        # Strategy 1: Resolve relative to current document's directory
        if self.current_doc:
            current_dir = os.path.dirname(self.current_doc)
            resolved = normalize(os.path.join(current_dir, relative_path))
            # Security: Only allow navigation to docs already in the tree
            if resolved in self._filename_to_item:
                self._select_doc(resolved)
                return

        # Strategy 2: Treat as path from docs/user/ root
        resolved = normalize(relative_path)
        # Security: Only allow navigation to docs already in the tree
        if resolved in self._filename_to_item:
            self._select_doc(resolved)

    def _select_doc(self, filename: str):
        """Select a document in the tree and display it."""
        item = self._filename_to_item[filename]
        self.tree.setCurrentItem(item)
        self._on_tree_item_clicked(item, 0)

    def _show_document_loading(self, title: str):
        """Show loading indicator for a specific document.

        Args:
            title: Document title being loaded
        """
        palette = QApplication.palette()
        is_dark = palette.window().color().lightness() < 128

        bg_color = "#1e1e1e" if is_dark else "#ffffff"
        text_color = "#e0e0e0" if is_dark else "#333333"
        muted_color = "#aaaaaa" if is_dark else "#7f8c8d"

        self.content_viewer.setHtml(f"""
        <html>
        <body style="padding: 40px; font-family: 'Segoe UI', Arial, sans-serif; background-color: {bg_color}; color: {text_color}; text-align: center;">
            <h2 style="color: #3498db;">Loading: {title}</h2>
            <p style="color: {muted_color};">Please wait while the document is being processed...</p>
        </body>
        </html>
        """)

    def _get_theme_css(self) -> str:
        """Generate theme-appropriate CSS for HTML content.

        Returns:
            CSS string for the current theme (dark or light)
        """
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

    def _on_search(self, text: str):
        """Filter tree items based on search text.

        Args:
            text: Search query
        """
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

                # Check if title matches
                title_match = text in item.text(0).lower()

                # Check if cached HTML content matches
                content_match = False
                if filename in self._html_cache:
                    content_match = text in self._html_cache[filename].lower()

                matches = title_match or content_match
                item.setHidden(not matches)
                if matches:
                    category_has_match = True

            category.setHidden(not category_has_match)

    def _find_in_content(self):
        """Find and highlight search term in current document."""
        search_text = self.search_input.text()
        if not search_text:
            return

        # Use QTextEdit's built-in find
        self.content_viewer.find(search_text)

    def _show_loading_message(self):
        """Display loading message while documentation loads asynchronously."""
        palette = QApplication.palette()
        is_dark = palette.window().color().lightness() < 128

        bg_color = "#1e1e1e" if is_dark else "#ffffff"
        text_color = "#e0e0e0" if is_dark else "#333333"
        muted_color = "#aaaaaa" if is_dark else "#7f8c8d"

        self.content_viewer.setHtml(f"""
        <html>
        <body style="padding: 40px; font-family: 'Segoe UI', Arial, sans-serif; background-color: {bg_color}; color: {text_color}; text-align: center;">
            <h2 style="color: #3498db;">Loading Documentation...</h2>
            <p style="color: {muted_color};">Please wait while documentation is being loaded.</p>
            <p style="color: {muted_color}; font-size: 0.9em;">Documents will appear as they are ready.</p>
        </body>
        </html>
        """)

    def _show_error(self, message: str):
        """Display error message in content viewer.

        Args:
            message: Error message to display
        """
        palette = QApplication.palette()
        is_dark = palette.window().color().lightness() < 128

        bg_color = "#1e1e1e" if is_dark else "#ffffff"
        text_color = "#e0e0e0" if is_dark else "#333333"
        muted_color = "#aaaaaa" if is_dark else "#7f8c8d"

        self.content_viewer.setHtml(f"""
        <html>
        <body style="padding: 20px; font-family: Arial, sans-serif; background-color: {bg_color}; color: {text_color};">
            <h2 style="color: #e74c3c;">Error</h2>
            <p>{message}</p>
            <p style="color: {muted_color};">
                Please ensure the documentation files are available in the <code>docs/user/</code> directory.
            </p>
        </body>
        </html>
        """)

    def _center_on_parent(self):
        """Center dialog on parent window or screen."""
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
        """Open help dialog and navigate to keyboard shortcuts."""
        # Find and select keyboard shortcuts item
        for i in range(self.tree.topLevelItemCount()):
            category = self.tree.topLevelItem(i)
            for j in range(category.childCount()):
                item = category.child(j)
                filename = item.data(0, Qt.ItemDataRole.UserRole)
                if filename and filename.endswith("keyboard-shortcuts.md"):
                    self.tree.setCurrentItem(item)
                    self._on_tree_item_clicked(item, 0)
                    self.show()
                    return
        self.show()

    def closeEvent(self, event):
        """Handle dialog close - cleanup the loader thread.

        Args:
            event: Close event
        """
        if self._loader_thread is not None and self._loader_thread.isRunning():
            self._loader_thread.stop()
            self._loader_thread.wait(1000)  # Wait up to 1 second
            if self._loader_thread.isRunning():
                self._loader_thread.terminate()
        super().closeEvent(event)

    def reject(self):
        """Handle dialog rejection (Escape key or Close button)."""
        if self._loader_thread is not None and self._loader_thread.isRunning():
            self._loader_thread.stop()
            self._loader_thread.wait(1000)
            if self._loader_thread.isRunning():
                self._loader_thread.terminate()
        super().reject()
