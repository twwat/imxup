#!/usr/bin/env python3
"""
Credential setup dialog for imx.to uploader
Provides secure credential management with encryption
"""

import os
import configparser
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox, QPushButton,
    QLineEdit, QMessageBox, QStyle
)
from PyQt6.QtCore import QSize
from PyQt6.QtGui import QIcon

# Import the core credential functions
from imxup import (get_config_path, encrypt_password, decrypt_password,
                   get_credential, set_credential, remove_credential)


class CredentialSetupDialog(QDialog):
    """Dialog for setting up secure credentials"""

    def __init__(self, parent=None, standalone=False):
        super().__init__(parent)
        self.setWindowTitle("Setup Secure Credentials")
        self.setModal(True)
        self.resize(500, 430)
        self.standalone = standalone
        
        layout = QVBoxLayout(self)

        # ========== API KEY SECTION ==========
        api_key_group = QGroupBox("API Key")
        api_key_layout = QVBoxLayout(api_key_group)

        # API Key info text
        api_key_info = QLabel(
            "<b>Required</b> for uploading files &mdash; get your API key from <a style=\"color:#0078d4\" href=\"https://imx.to/user/api\">https://imx.to/user/api</a>"
        )
        api_key_info.setWordWrap(True)
        api_key_info.setProperty("class", "info-panel")
        api_key_layout.addWidget(api_key_info)

        # API Key status
        api_key_status_layout = QHBoxLayout()
        api_key_status_layout.addWidget(QLabel("<b>API Key</b>: "))
        self.api_key_status_label = QLabel("NOT SET")
        self.api_key_status_label.setProperty("class", "status-muted")
        api_key_status_layout.addWidget(self.api_key_status_label)
        api_key_status_layout.addStretch()
        self.api_key_change_btn = QPushButton("Set")
        if not self.api_key_change_btn.text().startswith(" "):
            self.api_key_change_btn.setText(" " + self.api_key_change_btn.text())
        self.api_key_change_btn.clicked.connect(self.change_api_key)
        api_key_status_layout.addWidget(self.api_key_change_btn)
        self.api_key_remove_btn = QPushButton("Unset")
        if not self.api_key_remove_btn.text().startswith(" "):
            self.api_key_remove_btn.setText(" " + self.api_key_remove_btn.text())
        self.api_key_remove_btn.clicked.connect(self.remove_api_key)
        api_key_status_layout.addWidget(self.api_key_remove_btn)
        api_key_layout.addLayout(api_key_status_layout)

        # Add API Key group to main layout
        layout.addWidget(api_key_group)

        # ========== LOGIN / PASSWORD SECTION ==========
        login_group = QGroupBox("Login")
        login_layout = QVBoxLayout(login_group)

        # Login info text
        login_info = QLabel(
            "<b>Required</b> for renaming galleries on imx.to &mdash; without this, all galleries will be named \"untitled gallery\"."
        )
        login_info.setWordWrap(True)
        login_info.setProperty("class", "info-panel")
        login_layout.addWidget(login_info)

        # ========== USERNAME/PASSWORD SUBSECTION (nested) ==========
        username_password_group = QGroupBox("Login / Password")
        username_password_layout = QVBoxLayout(username_password_group)

        # Username status
        username_status_layout = QHBoxLayout()
        username_status_layout.addWidget(QLabel("<b>Username</b>: "))
        self.username_status_label = QLabel("NOT SET")
        self.username_status_label.setProperty("class", "status-muted")
        username_status_layout.addWidget(self.username_status_label)
        username_status_layout.addStretch()
        self.username_change_btn = QPushButton("Set")
        if not self.username_change_btn.text().startswith(" "):
            self.username_change_btn.setText(" " + self.username_change_btn.text())
        self.username_change_btn.clicked.connect(self.change_username)
        username_status_layout.addWidget(self.username_change_btn)
        self.username_remove_btn = QPushButton("Unset")
        if not self.username_remove_btn.text().startswith(" "):
            self.username_remove_btn.setText(" " + self.username_remove_btn.text())
        self.username_remove_btn.clicked.connect(self.remove_username)
        username_status_layout.addWidget(self.username_remove_btn)
        username_password_layout.addLayout(username_status_layout)

        # Password status
        password_status_layout = QHBoxLayout()
        password_status_layout.addWidget(QLabel("<b>Password</b>: "))
        self.password_status_label = QLabel("NOT SET")
        self.password_status_label.setProperty("class", "status-muted")
        password_status_layout.addWidget(self.password_status_label)
        password_status_layout.addStretch()
        self.password_change_btn = QPushButton("Set")
        if not self.password_change_btn.text().startswith(" "):
            self.password_change_btn.setText(" " + self.password_change_btn.text())
        self.password_change_btn.clicked.connect(self.change_password)
        password_status_layout.addWidget(self.password_change_btn)
        self.password_remove_btn = QPushButton("Unset")
        if not self.password_remove_btn.text().startswith(" "):
            self.password_remove_btn.setText(" " + self.password_remove_btn.text())
        self.password_remove_btn.clicked.connect(self.remove_password)
        password_status_layout.addWidget(self.password_remove_btn)
        username_password_layout.addLayout(password_status_layout)

        # Add username/password group to login group (nested)
        login_layout.addWidget(username_password_group)

        # ========== FIREFOX COOKIES SUBSECTION (nested) ==========
        cookies_group = QGroupBox("Firefox Cookies")
        cookies_layout = QVBoxLayout(cookies_group)

        # Cookies info text
        cookies_info = QLabel(
            "Attempt login using existing Firefox cookies. &nbsp;<i>Cookies tried first, login/password used as fallback (if set)</i>"
        )
        cookies_info.setWordWrap(True)
        cookies_info.setProperty("class", "info-panel")
        cookies_layout.addWidget(cookies_info)

        # Firefox cookies toggle status
        cookies_status_layout = QHBoxLayout()
        cookies_status_layout.addWidget(QLabel("<b>Firefox cookies</b>: "))
        self.cookies_status_label = QLabel("Unknown")
        self.cookies_status_label.setProperty("class", "status-muted")
        cookies_status_layout.addWidget(self.cookies_status_label)
        cookies_status_layout.addStretch()
        self.cookies_enable_btn = QPushButton("Enable")
        if not self.cookies_enable_btn.text().startswith(" "):
            self.cookies_enable_btn.setText(" " + self.cookies_enable_btn.text())
        self.cookies_enable_btn.clicked.connect(self.enable_cookies_setting)
        cookies_status_layout.addWidget(self.cookies_enable_btn)
        self.cookies_disable_btn = QPushButton("Disable")
        if not self.cookies_disable_btn.text().startswith(" "):
            self.cookies_disable_btn.setText(" " + self.cookies_disable_btn.text())
        self.cookies_disable_btn.clicked.connect(self.disable_cookies_setting)
        cookies_status_layout.addWidget(self.cookies_disable_btn)
        cookies_layout.addLayout(cookies_status_layout)

        # Add cookies group to login group (nested)
        login_layout.addWidget(cookies_group)

        # Add login group to main layout
        layout.addWidget(login_group)

        # Encryption note at bottom
        encryption_note = QLabel(
            "<small>API key and password are encrypted via Fernet (AES-128-CBC / PKCS7 padding + HMAC-SHA256) using your system's hostname and stored in the registry.<br><br>This means the encrypted data is protected from other users on this system and won't work on other computers.</small>"
        )
        encryption_note.setWordWrap(True)
        encryption_note.setProperty("class", "label-credential-note")
        layout.addWidget(encryption_note)

        # Remove all button at bottom
        destructive_layout = QHBoxLayout()
        # Place on bottom-left to reduce accidental clicks
        destructive_layout.addStretch()  # we'll remove this and add after button to push left
        self.remove_all_btn = QPushButton("Unset All")
        if not self.remove_all_btn.text().startswith(" "):
            self.remove_all_btn.setText(" " + self.remove_all_btn.text())
        self.remove_all_btn.clicked.connect(self.remove_all_credentials)
        destructive_layout.insertWidget(0, self.remove_all_btn)
        destructive_layout.addStretch()
        layout.addLayout(destructive_layout)
        
        # Hidden input fields for editing
        self.username_edit = QLineEdit()
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        
        # Load current credentials
        self.load_current_credentials()

        # OK button (only for standalone mode)
        if self.standalone:
            button_layout = QHBoxLayout()
            button_layout.addStretch()

            ok_btn = QPushButton("OK")
            style = self.style()
            if style:
                ok_btn.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DialogOkButton))
            ok_btn.setIconSize(QSize(16, 16))
            if not ok_btn.text().startswith(" "):
                ok_btn.setText(" " + ok_btn.text())
            ok_btn.clicked.connect(self.accept)
            ok_btn.setDefault(True)
            button_layout.addWidget(ok_btn)

            layout.addLayout(button_layout)
        

    
    def load_current_credentials(self):
        """Load and display current credentials"""
        # Load from QSettings (migration happens once at app startup)
        username = get_credential('username')
        password = get_credential('password')

        if username:
            self.username_status_label.setText(username)
            self.username_status_label.setProperty("class", "status-success")
            style = self.username_status_label.style()
            if style:
                style.polish(self.username_status_label)
            # Buttons: Change/Unset
            self.username_change_btn.setText(" Change")
            self.username_remove_btn.setEnabled(True)
        else:
            self.username_status_label.setText("NOT SET")
            self.username_status_label.setProperty("class", "status-muted")
            style = self.username_status_label.style()
            if style:
                style.polish(self.username_status_label)
            self.username_change_btn.setText(" Set")
            self.username_remove_btn.setEnabled(False)

        if password:
            self.password_status_label.setText("********************************")
            self.password_status_label.setProperty("class", "status-success")
            style = self.password_status_label.style()
            if style:
                style.polish(self.password_status_label)
            self.password_change_btn.setText(" Change")
            self.password_remove_btn.setEnabled(True)
        else:
            self.password_status_label.setText("NOT SET")
            self.password_status_label.setProperty("class", "status-muted")
            style = self.password_status_label.style()
            if style:
                style.polish(self.password_status_label)
            self.password_change_btn.setText(" Set")
            self.password_remove_btn.setEnabled(False)

        # Check API key
        encrypted_api_key = get_credential('api_key')
        if encrypted_api_key:
            try:
                api_key = decrypt_password(encrypted_api_key)
                if api_key and len(api_key) > 8:
                    masked_key = api_key[:4] + "*" * 24 + api_key[-4:]
                    self.api_key_status_label.setText(masked_key)
                else:
                    self.api_key_status_label.setText("SET")
                self.api_key_status_label.setProperty("class", "status-success")
                style = self.api_key_status_label.style()
                if style:
                    style.polish(self.api_key_status_label)
                self.api_key_change_btn.setText(" Change")
                self.api_key_remove_btn.setEnabled(True)
            except (AttributeError, RuntimeError):
                self.api_key_status_label.setText("SET")
                self.api_key_status_label.setProperty("class", "status-success")
                style = self.api_key_status_label.style()
                if style:
                    style.polish(self.api_key_status_label)
                self.api_key_change_btn.setText(" Change")
                self.api_key_remove_btn.setEnabled(True)
        else:
            self.api_key_status_label.setText("NOT SET")
            self.api_key_status_label.setProperty("class", "status-muted")
            style = self.api_key_status_label.style()
            if style:
                style.polish(self.api_key_status_label)
            # When not set, offer Set and disable Unset
            self.api_key_change_btn.setText(" Set")
            self.api_key_remove_btn.setEnabled(False)

        # Cookies setting (still stored in INI file as it's a preference, not a credential)
        import configparser
        config = configparser.ConfigParser()
        config_file = get_config_path()
        cookies_enabled = True  # Default
        if os.path.exists(config_file):
            config.read(config_file)
            if 'CREDENTIALS' in config:
                cookies_enabled_val = str(config['CREDENTIALS'].get('cookies_enabled', 'true')).lower()
                cookies_enabled = cookies_enabled_val != 'false'
        if cookies_enabled:
            self.cookies_status_label.setText("Enabled")
            self.cookies_status_label.setProperty("class", "status-success")
        else:
            self.cookies_status_label.setText("Disabled")
            self.cookies_status_label.setProperty("class", "status-error")
        style = self.cookies_status_label.style()
        if style:
            style.polish(self.cookies_status_label)
        # Toggle button states
        self.cookies_enable_btn.setEnabled(not cookies_enabled)
        self.cookies_disable_btn.setEnabled(cookies_enabled)
    
    def change_username(self):
        """Open dialog to change username only"""
        dialog = QDialog(self)
        dialog.setWindowTitle("Set Username")
        dialog.setModal(True)
        dialog.resize(400, 140)
        
        layout = QVBoxLayout(dialog)
        
        # Username input only
        username_layout = QHBoxLayout()
        username_layout.addWidget(QLabel("Username:"))
        username_edit = QLineEdit()
        username_layout.addWidget(username_edit)
        layout.addLayout(username_layout)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        save_btn = QPushButton("Save")
        style = self.style()
        if style:
            save_btn.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
        save_btn.setIconSize(QSize(16, 16))
        if not save_btn.text().startswith(" "):
            save_btn.setText(" " + save_btn.text())
        save_btn.clicked.connect(dialog.accept)
        button_layout.addWidget(save_btn)

        cancel_btn = QPushButton("Cancel")
        if style:
            cancel_btn.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DialogCancelButton))
        cancel_btn.setIconSize(QSize(16, 16))
        if not cancel_btn.text().startswith(" "):
            cancel_btn.setText(" " + cancel_btn.text())
        cancel_btn.clicked.connect(dialog.reject)
        button_layout.addWidget(cancel_btn)
        
        layout.addLayout(button_layout)
        
        # Store reference to username_edit for callback and use non-blocking show()
        def handle_username_result(result):
            self._handle_username_dialog_result(result, username_edit.text().strip())
        
        dialog.show()
        dialog.finished.connect(handle_username_result)
    
    def _handle_username_dialog_result(self, result, username):
        """Handle username dialog result without blocking GUI"""
        if result == QDialog.DialogCode.Accepted:
            if username:
                try:
                    set_credential('username', username)
                    self.load_current_credentials()
                    QMessageBox.information(self, "Success", "Username saved successfully!")
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"Failed to save credentials: {str(e)}")
            else:
                QMessageBox.warning(self, "Missing Information", "Please enter a username.")

    def change_password(self):
        """Open dialog to change password only"""
        dialog = QDialog(self)
        dialog.setWindowTitle("Set Password")
        dialog.setModal(True)
        dialog.resize(400, 140)
        
        layout = QVBoxLayout(dialog)
        
        # Password input only
        password_layout = QHBoxLayout()
        password_layout.addWidget(QLabel("Password:"))
        password_edit = QLineEdit()
        password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        password_layout.addWidget(password_edit)
        layout.addLayout(password_layout)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        save_btn = QPushButton("Save")
        style = self.style()
        if style:
            save_btn.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
        save_btn.setIconSize(QSize(16, 16))
        if not save_btn.text().startswith(" "):
            save_btn.setText(" " + save_btn.text())
        save_btn.clicked.connect(dialog.accept)
        button_layout.addWidget(save_btn)

        cancel_btn = QPushButton("Cancel")
        if style:
            cancel_btn.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DialogCancelButton))
        cancel_btn.setIconSize(QSize(16, 16))
        if not cancel_btn.text().startswith(" "):
            cancel_btn.setText(" " + cancel_btn.text())
        cancel_btn.clicked.connect(dialog.reject)
        button_layout.addWidget(cancel_btn)
        
        layout.addLayout(button_layout)
        
        # Store reference to password_edit for callback and use non-blocking show()
        def handle_password_result(result):
            self._handle_password_dialog_result(result, password_edit.text())
        
        dialog.show()
        dialog.finished.connect(handle_password_result)
    
    def _handle_password_dialog_result(self, result, password):
        """Handle password dialog result without blocking GUI"""
        if result == QDialog.DialogCode.Accepted:
            if password:
                try:
                    set_credential('password', encrypt_password(password))
                    self.load_current_credentials()
                    QMessageBox.information(self, "Success", "Password saved successfully!")
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"Failed to save password: {str(e)}")
            else:
                QMessageBox.warning(self, "Missing Information", "Please enter a password.")
    
    def change_api_key(self):
        """Open dialog to change API key"""
        dialog = QDialog(self)
        dialog.setWindowTitle("Change API Key")
        dialog.setModal(True)
        dialog.resize(400, 150)
        
        layout = QVBoxLayout(dialog)
        
        # API Key input
        api_key_layout = QHBoxLayout()
        api_key_layout.addWidget(QLabel("API Key:"))
        api_key_edit = QLineEdit()
        api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        api_key_layout.addWidget(api_key_edit)
        layout.addLayout(api_key_layout)
        
        # Info label
        info_label = QLabel("Get your API key from: https://imx.to/user/api")
        info_label.setProperty("class", "small-text status-muted")
        layout.addWidget(info_label)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(dialog.accept)
        button_layout.addWidget(save_btn)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(dialog.reject)
        button_layout.addWidget(cancel_btn)
        
        layout.addLayout(button_layout)
        
        # Store reference to api_key_edit for callback and use non-blocking show()
        def handle_api_key_result(result):
            self._handle_api_key_dialog_result(result, api_key_edit.text().strip())
        
        dialog.show()
        dialog.finished.connect(handle_api_key_result)
    
    def _handle_api_key_dialog_result(self, result, api_key):
        """Handle API key dialog result without blocking GUI"""
        if result == QDialog.DialogCode.Accepted:
            if api_key:
                try:
                    set_credential('api_key', encrypt_password(api_key))
                    self.load_current_credentials()
                    QMessageBox.information(self, "Success", "API key saved successfully!")
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"Failed to save API key: {str(e)}")
            else:
                QMessageBox.warning(self, "Missing Information", "Please enter your API key.")

    def enable_cookies_setting(self):
        """Enable Firefox cookies usage for login"""
        try:
            config = configparser.ConfigParser()
            config_file = get_config_path()
            if os.path.exists(config_file):
                config.read(config_file)
            if 'CREDENTIALS' not in config:
                config['CREDENTIALS'] = {}
            config['CREDENTIALS']['cookies_enabled'] = 'true'
            with open(config_file, 'w') as f:
                config.write(f)
            self.load_current_credentials()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to enable cookies: {str(e)}")

    def disable_cookies_setting(self):
        """Disable Firefox cookies usage for login"""
        try:
            config = configparser.ConfigParser()
            config_file = get_config_path()
            if os.path.exists(config_file):
                config.read(config_file)
            if 'CREDENTIALS' not in config:
                config['CREDENTIALS'] = {}
            config['CREDENTIALS']['cookies_enabled'] = 'false'
            with open(config_file, 'w') as f:
                config.write(f)
            self.load_current_credentials()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to disable cookies: {str(e)}")

    def remove_username(self):
        """Remove stored username with confirmation"""
        msgbox = QMessageBox(self)
        msgbox.setWindowTitle("Remove Username")
        msgbox.setText("Without username/password, all galleries will be titled 'untitled gallery'.\n\nRemove the stored username?")
        msgbox.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msgbox.setDefaultButton(QMessageBox.StandardButton.No)
        msgbox.open()
        msgbox.finished.connect(self._handle_remove_username_confirmation)
    
    def _handle_remove_username_confirmation(self, result):
        """Handle username removal confirmation"""
        if result != QMessageBox.StandardButton.Yes:
            return
        try:
            remove_credential('username')
            self.load_current_credentials()
            QMessageBox.information(self, "Removed", "Username removed.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to remove username: {str(e)}")

    def remove_password(self):
        """Remove stored password with confirmation"""
        reply = QMessageBox.question(
            self,
            "Remove Password",
            "Without username/password, all galleries will be titled 'untitled gallery'.\n\nRemove the stored password?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            remove_credential('password')
            self.load_current_credentials()
            QMessageBox.information(self, "Removed", "Password removed.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to remove password: {str(e)}")

    def remove_api_key(self):
        """Remove stored API key with confirmation"""
        reply = QMessageBox.question(
            self,
            "Remove API Key",
            "Without an API key, it is not possible to upload anything.\n\nRemove the stored API key?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            remove_credential('api_key')
            self.load_current_credentials()
            QMessageBox.information(self, "Removed", "API key removed.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to remove API key: {str(e)}")

    def remove_all_credentials(self):
        """Remove username, password, and API key with confirmation"""
        reply = QMessageBox.question(
            self,
            "Remove All Credentials",
            "This will remove your username, password, and API key.\n\n- Without username/password, all galleries will be titled 'untitled gallery'.\n- Without an API key, uploads are not possible.\n\nProceed?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            remove_credential('username')
            remove_credential('password')
            remove_credential('api_key')
            self.load_current_credentials()
            QMessageBox.information(self, "Removed", "All credentials removed.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to remove all credentials: {str(e)}")
    

    
    def validate_and_close(self):
        """Close the dialog - no validation required"""
        self.accept()
    
    def save_credentials(self):
        """Save credentials securely - this is now handled by individual change buttons"""
        self.accept()