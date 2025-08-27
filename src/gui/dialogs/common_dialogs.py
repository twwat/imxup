#!/usr/bin/env python3
"""
Common dialog classes for imxup GUI
Provides dialogs for credentials, BBCode viewing, help, and logs
"""

import os
import configparser
from typing import Optional

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QGroupBox, QLineEdit, QTextEdit, QDialogButtonBox,
    QPlainTextEdit, QMessageBox, QInputDialog
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QSyntaxHighlighter, QTextCharFormat, QColor, QFont

from imxup import (
    get_config_path, encrypt_password, decrypt_password,
    timestamp
)


class CredentialSetupDialog(QDialog):
    """Dialog for setting up secure credentials"""
    
    # Signal emitted when credentials change
    credentials_changed = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
        self.load_current_credentials()
    
    def setup_ui(self):
        """Initialize the UI components"""
        self.setWindowTitle("Setup Secure Credentials")
        self.setModal(True)
        self.resize(500, 430)
        
        layout = QVBoxLayout(self)
        
        # Theme-aware colors
        self._setup_theme_colors()
        
        # Info text
        layout.addWidget(self._create_info_widget())
        
        # Credential status display
        layout.addWidget(self._create_status_group())
        
        # Remove all button
        layout.addLayout(self._create_destructive_layout())
        
        # Hidden input fields
        self._create_hidden_inputs()
        
        # Close button
        layout.addLayout(self._create_button_layout())
    
    def _setup_theme_colors(self):
        """Setup theme-aware colors"""
        try:
            pal = self.palette()
            bg = pal.window().color()
            # Simple luminance check
            is_dark = (0.2126 * bg.redF() + 0.7152 * bg.greenF() + 0.0722 * bg.blueF()) < 0.5
        except Exception:
            is_dark = False
        
        self._muted_color = "#aaaaaa" if is_dark else "#666666"
        self._text_color = "#dddddd" if is_dark else "#333333"
        self._panel_bg = "#2e2e2e" if is_dark else "#f0f8ff"
        self._panel_border = "#444444" if is_dark else "#cccccc"
    
    def _create_info_widget(self) -> QLabel:
        """Create the info text widget"""
        info_text = QLabel(
            "IMX.to credentials:\n\n"
            "• API Key: Required for uploading files\n"
            "• Username/Password: Required for naming galleries\n\n"
            "Without username/password, all galleries will be named 'untitled gallery'\n\n"
            "Credentials are stored in your home directory, encrypted with AES-128-CBC via Fernet using system's hostname/username as the encryption key.\n\n"
            "This means:\n"
            "• They cannot be recovered if forgotten (you'll have to reset on imx.to)\n"
            "• The encrypted data won't work on other computers\n"
            "• Credentials are obfuscated from other users on this system\n\n"
            "Get your API key from: https://imx.to/user/api"
        )
        info_text.setWordWrap(True)
        info_text.setStyleSheet(
            f"padding: 10px; background-color: {self._panel_bg}; "
            f"border: 1px solid {self._panel_border}; border-radius: 5px; "
            f"color: {self._text_color};"
        )
        return info_text
    
    def _create_status_group(self) -> QGroupBox:
        """Create the credential status group"""
        status_group = QGroupBox("Current Credentials")
        status_layout = QVBoxLayout(status_group)
        
        # Username status
        status_layout.addLayout(self._create_credential_row(
            "Username", "username", self.change_username, self.remove_username
        ))
        
        # Password status
        status_layout.addLayout(self._create_credential_row(
            "Password", "password", self.change_password, self.remove_password
        ))
        
        # API Key status
        status_layout.addLayout(self._create_credential_row(
            "API Key", "api_key", self.change_api_key, self.remove_api_key
        ))
        
        # Firefox cookies status
        status_layout.addLayout(self._create_cookies_row())
        
        return status_group
    
    def _create_credential_row(self, label: str, attr_prefix: str, change_callback, remove_callback) -> QHBoxLayout:
        """Create a credential status row"""
        layout = QHBoxLayout()
        layout.addWidget(QLabel(f"{label}: "))
        
        # Status label
        status_label = QLabel("NOT SET")
        status_label.setStyleSheet(f"color: {self._muted_color}; font-style: italic;")
        setattr(self, f"{attr_prefix}_status_label", status_label)
        layout.addWidget(status_label)
        
        layout.addStretch()
        
        # Change button
        change_btn = QPushButton(" Set")
        change_btn.clicked.connect(change_callback)
        setattr(self, f"{attr_prefix}_change_btn", change_btn)
        layout.addWidget(change_btn)
        
        # Remove button
        remove_btn = QPushButton(" Unset")
        remove_btn.clicked.connect(remove_callback)
        setattr(self, f"{attr_prefix}_remove_btn", remove_btn)
        layout.addWidget(remove_btn)
        
        return layout
    
    def _create_cookies_row(self) -> QHBoxLayout:
        """Create the Firefox cookies status row"""
        layout = QHBoxLayout()
        layout.addWidget(QLabel("Firefox cookies: "))
        
        self.cookies_status_label = QLabel("Unknown")
        self.cookies_status_label.setStyleSheet(f"color: {self._muted_color}; font-style: italic;")
        layout.addWidget(self.cookies_status_label)
        
        layout.addStretch()
        
        self.cookies_enable_btn = QPushButton(" Enable")
        self.cookies_enable_btn.clicked.connect(self.enable_cookies_setting)
        layout.addWidget(self.cookies_enable_btn)
        
        self.cookies_disable_btn = QPushButton(" Disable")
        self.cookies_disable_btn.clicked.connect(self.disable_cookies_setting)
        layout.addWidget(self.cookies_disable_btn)
        
        return layout
    
    def _create_destructive_layout(self) -> QHBoxLayout:
        """Create the destructive actions layout"""
        layout = QHBoxLayout()
        self.remove_all_btn = QPushButton(" Unset All")
        self.remove_all_btn.clicked.connect(self.remove_all_credentials)
        layout.addWidget(self.remove_all_btn)
        layout.addStretch()
        return layout
    
    def _create_hidden_inputs(self):
        """Create hidden input fields for editing"""
        self.username_edit = QLineEdit()
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
    
    def _create_button_layout(self) -> QHBoxLayout:
        """Create the button layout"""
        layout = QHBoxLayout()
        layout.addStretch()
        
        self.close_btn = QPushButton(" Close")
        self.close_btn.clicked.connect(self.validate_and_close)
        layout.addWidget(self.close_btn)
        
        return layout
    
    def load_current_credentials(self):
        """Load and display current credentials"""
        config = configparser.ConfigParser()
        config_file = get_config_path()
        
        if not os.path.exists(config_file):
            return
        
        config.read(config_file)
        if 'CREDENTIALS' not in config:
            return
        
        # Load username
        username = config.get('CREDENTIALS', 'username', fallback='')
        self._update_credential_status('username', username, bool(username))
        
        # Load password
        password = config.get('CREDENTIALS', 'password', fallback='')
        if password:
            self._update_credential_status('password', '••••••••', True)
        else:
            self._update_credential_status('password', 'NOT SET', False)
        
        # Load API key
        api_key = config.get('CREDENTIALS', 'api_key', fallback='')
        if api_key:
            masked = api_key[:4] + '...' + api_key[-4:] if len(api_key) > 8 else '••••••••'
            self._update_credential_status('api_key', masked, True)
        else:
            self._update_credential_status('api_key', 'NOT SET', False)
        
        # Load cookies setting
        use_cookies = config.getboolean('CREDENTIALS', 'use_firefox_cookies', fallback=False)
        self._update_cookies_status(use_cookies)
    
    def _update_credential_status(self, attr_prefix: str, text: str, is_set: bool):
        """Update a credential status display"""
        status_label = getattr(self, f"{attr_prefix}_status_label")
        change_btn = getattr(self, f"{attr_prefix}_change_btn")
        remove_btn = getattr(self, f"{attr_prefix}_remove_btn")
        
        status_label.setText(text)
        if is_set:
            status_label.setStyleSheet("color: #27ae60; font-weight: bold;")
            change_btn.setText(" Change")
            remove_btn.setEnabled(True)
        else:
            status_label.setStyleSheet(f"color: {self._muted_color}; font-style: italic;")
            change_btn.setText(" Set")
            remove_btn.setEnabled(False)
    
    def _update_cookies_status(self, enabled: bool):
        """Update cookies status display"""
        if enabled:
            self.cookies_status_label.setText("ENABLED")
            self.cookies_status_label.setStyleSheet("color: #27ae60; font-weight: bold;")
            self.cookies_enable_btn.setEnabled(False)
            self.cookies_disable_btn.setEnabled(True)
        else:
            self.cookies_status_label.setText("DISABLED")
            self.cookies_status_label.setStyleSheet(f"color: {self._muted_color}; font-style: italic;")
            self.cookies_enable_btn.setEnabled(True)
            self.cookies_disable_btn.setEnabled(False)
    
    def change_username(self):
        """Change username"""
        text, ok = QInputDialog.getText(
            self, "Set Username", "Enter username:",
            QLineEdit.EchoMode.Normal
        )
        if ok and text:
            self._save_credential('username', text)
            self._update_credential_status('username', text, True)
            self.credentials_changed.emit()
    
    def change_password(self):
        """Change password"""
        text, ok = QInputDialog.getText(
            self, "Set Password", "Enter password:",
            QLineEdit.EchoMode.Password
        )
        if ok and text:
            encrypted = encrypt_password(text)
            self._save_credential('password', encrypted)
            self._update_credential_status('password', '••••••••', True)
            self.credentials_changed.emit()
    
    def change_api_key(self):
        """Change API key"""
        text, ok = QInputDialog.getText(
            self, "Set API Key", "Enter API key:",
            QLineEdit.EchoMode.Password
        )
        if ok and text:
            self._save_credential('api_key', text)
            masked = text[:4] + '...' + text[-4:] if len(text) > 8 else '••••••••'
            self._update_credential_status('api_key', masked, True)
            self.credentials_changed.emit()
    
    def remove_username(self):
        """Remove username"""
        self._remove_credential('username')
        self._update_credential_status('username', 'NOT SET', False)
        self.credentials_changed.emit()
    
    def remove_password(self):
        """Remove password"""
        self._remove_credential('password')
        self._update_credential_status('password', 'NOT SET', False)
        self.credentials_changed.emit()
    
    def remove_api_key(self):
        """Remove API key"""
        self._remove_credential('api_key')
        self._update_credential_status('api_key', 'NOT SET', False)
        self.credentials_changed.emit()
    
    def enable_cookies_setting(self):
        """Enable Firefox cookies"""
        self._save_credential('use_firefox_cookies', 'true')
        self._update_cookies_status(True)
        self.credentials_changed.emit()
    
    def disable_cookies_setting(self):
        """Disable Firefox cookies"""
        self._save_credential('use_firefox_cookies', 'false')
        self._update_cookies_status(False)
        self.credentials_changed.emit()
    
    def remove_all_credentials(self):
        """Remove all credentials"""
        reply = QMessageBox.question(
            self, "Confirm", 
            "Remove all stored credentials?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            config = configparser.ConfigParser()
            config_file = get_config_path()
            
            if os.path.exists(config_file):
                config.read(config_file)
                if 'CREDENTIALS' in config:
                    config.remove_section('CREDENTIALS')
                with open(config_file, 'w') as f:
                    config.write(f)
            
            self.load_current_credentials()
            self.credentials_changed.emit()
    
    def _save_credential(self, key: str, value: str):
        """Save a credential to config"""
        config = configparser.ConfigParser()
        config_file = get_config_path()
        
        if os.path.exists(config_file):
            config.read(config_file)
        
        if 'CREDENTIALS' not in config:
            config['CREDENTIALS'] = {}
        
        config['CREDENTIALS'][key] = value
        
        with open(config_file, 'w') as f:
            config.write(f)
    
    def _remove_credential(self, key: str):
        """Remove a credential from config"""
        config = configparser.ConfigParser()
        config_file = get_config_path()
        
        if os.path.exists(config_file):
            config.read(config_file)
            if 'CREDENTIALS' in config and key in config['CREDENTIALS']:
                del config['CREDENTIALS'][key]
                with open(config_file, 'w') as f:
                    config.write(f)
    
    def validate_and_close(self):
        """Validate and close dialog"""
        config = configparser.ConfigParser()
        config_file = get_config_path()
        
        has_api_key = False
        has_credentials = False
        
        if os.path.exists(config_file):
            config.read(config_file)
            if 'CREDENTIALS' in config:
                has_api_key = bool(config.get('CREDENTIALS', 'api_key', fallback=''))
                has_credentials = bool(config.get('CREDENTIALS', 'username', fallback=''))
        
        if not has_api_key and not has_credentials:
            reply = QMessageBox.warning(
                self, "No Credentials",
                "No credentials are set. Continue anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return
        
        self.accept()


class BBCodeViewerDialog(QDialog):
    """Dialog for viewing and copying BBCode output"""
    
    def __init__(self, bbcode: str, parent=None):
        super().__init__(parent)
        self.bbcode = bbcode
        self.setup_ui()
    
    def setup_ui(self):
        """Initialize the UI components"""
        self.setWindowTitle("BBCode Output")
        self.setModal(True)
        self.resize(800, 600)
        
        layout = QVBoxLayout(self)
        
        # Text editor with BBCode
        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlainText(self.bbcode)
        self.text_edit.setReadOnly(True)
        
        # Apply syntax highlighting
        self.highlighter = BBCodeHighlighter(self.text_edit.document())
        
        layout.addWidget(self.text_edit)
        
        # Buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | 
            QDialogButtonBox.StandardButton.Close
        )
        
        # Rename OK button to Copy
        copy_btn = button_box.button(QDialogButtonBox.StandardButton.Ok)
        copy_btn.setText("Copy to Clipboard")
        copy_btn.clicked.connect(self.copy_to_clipboard)
        
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
    
    def copy_to_clipboard(self):
        """Copy BBCode to clipboard"""
        from PyQt6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        clipboard.setText(self.bbcode)
        
        # Show confirmation
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.information(
            self, "Copied",
            "BBCode copied to clipboard!",
            QMessageBox.StandardButton.Ok
        )


class BBCodeHighlighter(QSyntaxHighlighter):
    """Syntax highlighter for BBCode"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_formats()
    
    def setup_formats(self):
        """Setup text formats for highlighting"""
        # BBCode tags
        self.tag_format = QTextCharFormat()
        self.tag_format.setForeground(QColor("#0066cc"))
        self.tag_format.setFontWeight(QFont.Weight.Bold)
        
        # URLs
        self.url_format = QTextCharFormat()
        self.url_format.setForeground(QColor("#008800"))
        self.url_format.setFontUnderline(True)
        
        # Placeholders
        self.placeholder_format = QTextCharFormat()
        self.placeholder_format.setForeground(QColor("#cc6600"))
        self.placeholder_format.setFontWeight(QFont.Weight.Bold)
    
    def highlightBlock(self, text: str):
        """Highlight a block of text"""
        # Highlight BBCode tags
        import re
        
        # BBCode tags pattern
        tag_pattern = re.compile(r'\[/?[^\]]+\]')
        for match in tag_pattern.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.tag_format)
        
        # URL pattern
        url_pattern = re.compile(r'https?://[^\s\]]+')
        for match in url_pattern.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.url_format)
        
        # Placeholder pattern
        placeholder_pattern = re.compile(r'#\w+#')
        for match in placeholder_pattern.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.placeholder_format)


class HelpDialog(QDialog):
    """Help dialog showing usage instructions"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
    
    def setup_ui(self):
        """Initialize the UI components"""
        self.setWindowTitle("IMX Upload Help")
        self.setModal(True)
        self.resize(700, 500)
        
        layout = QVBoxLayout(self)
        
        # Help text
        help_text = QTextEdit()
        help_text.setReadOnly(True)
        help_text.setHtml(self.get_help_html())
        
        layout.addWidget(help_text)
        
        # Close button
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
    
    def get_help_html(self) -> str:
        """Get the help content as HTML"""
        return """
        <h2>IMX Gallery Uploader</h2>
        
        <h3>Quick Start</h3>
        <ol>
            <li>Set up your credentials (File → Setup Credentials)</li>
            <li>Drag and drop image folders onto the main window</li>
            <li>Click "Start Queue" to begin uploading</li>
            <li>BBCode will be generated automatically when uploads complete</li>
        </ol>
        
        <h3>Features</h3>
        <ul>
            <li><b>Drag & Drop:</b> Simply drag folders containing images onto the window</li>
            <li><b>Queue Management:</b> Add multiple galleries and upload them in sequence</li>
            <li><b>Progress Tracking:</b> See real-time progress for each gallery</li>
            <li><b>BBCode Templates:</b> Customize output format with templates</li>
            <li><b>Auto-rename:</b> Automatically rename untitled galleries after upload</li>
            <li><b>Parallel Uploads:</b> Upload multiple images simultaneously</li>
        </ul>
        
        <h3>Keyboard Shortcuts</h3>
        <ul>
            <li><b>Space:</b> Start/pause selected gallery</li>
            <li><b>Delete:</b> Remove selected gallery from queue</li>
            <li><b>Ctrl+A:</b> Select all galleries</li>
            <li><b>Ctrl+C:</b> Copy BBCode for selected gallery</li>
        </ul>
        
        <h3>Templates</h3>
        <p>Templates support the following placeholders:</p>
        <ul>
            <li><b>#folderName#</b> - Name of the uploaded folder</li>
            <li><b>#galleryLink#</b> - URL to the gallery</li>
            <li><b>#allImages#</b> - All image links</li>
            <li><b>#pictureCount#</b> - Number of images</li>
            <li><b>#folderSize#</b> - Total size of images</li>
        </ul>
        
        <h3>Settings Storage</h3>
        <p>All settings and templates are stored in: <code>~/.imxup/</code></p>
        
        <h3>Support</h3>
        <p>For issues or feature requests, visit the project repository.</p>
        """


class LogViewerDialog(QDialog):
    """Dialog for viewing application logs"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.log_content = []
        self.setup_ui()
    
    def setup_ui(self):
        """Initialize the UI components"""
        self.setWindowTitle("Log Viewer")
        self.resize(900, 600)
        
        layout = QVBoxLayout(self)
        
        # Log text area
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        layout.addWidget(self.log_text)
        
        # Button layout
        button_layout = QHBoxLayout()
        
        # Clear button
        self.clear_btn = QPushButton("Clear Log")
        self.clear_btn.clicked.connect(self.clear_log)
        button_layout.addWidget(self.clear_btn)
        
        # Export button
        self.export_btn = QPushButton("Export Log")
        self.export_btn.clicked.connect(self.export_log)
        button_layout.addWidget(self.export_btn)
        
        button_layout.addStretch()
        
        # Close button
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.close)
        button_layout.addWidget(self.close_btn)
        
        layout.addLayout(button_layout)
    
    def append_log(self, message: str):
        """Append a message to the log"""
        self.log_content.append(message)
        self.log_text.appendPlainText(message)
        
        # Limit log size to prevent memory issues
        if len(self.log_content) > 10000:
            self.log_content = self.log_content[-9000:]
            self.log_text.setPlainText('\n'.join(self.log_content))
    
    def clear_log(self):
        """Clear the log content"""
        self.log_content.clear()
        self.log_text.clear()
    
    def export_log(self):
        """Export log to file"""
        from PyQt6.QtWidgets import QFileDialog
        
        filename, _ = QFileDialog.getSaveFileName(
            self, "Export Log",
            f"imxup_log_{timestamp().replace(':', '')}.txt",
            "Text Files (*.txt)"
        )
        
        if filename:
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write('\n'.join(self.log_content))
                
                QMessageBox.information(
                    self, "Export Successful",
                    f"Log exported to: {filename}",
                    QMessageBox.StandardButton.Ok
                )
            except Exception as e:
                QMessageBox.critical(
                    self, "Export Failed",
                    f"Failed to export log: {str(e)}",
                    QMessageBox.StandardButton.Ok
                )