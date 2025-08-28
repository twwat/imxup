#!/usr/bin/env python3
"""
Message box factory for consistent dialog creation
Eliminates code duplication by providing standardized message box patterns
"""

from PyQt6.QtWidgets import QMessageBox, QWidget
from PyQt6.QtCore import Qt
from typing import Optional, Union


class MessageBoxFactory:
    """Factory class for creating standardized message boxes"""
    
    @staticmethod
    def warning(
        parent: Optional[QWidget] = None,
        title: str = "Warning",
        text: str = "",
        detailed_text: str = "",
        buttons: QMessageBox.StandardButton = QMessageBox.StandardButton.Ok
    ) -> int:
        """Create a warning message box
        
        Args:
            parent: Parent widget
            title: Window title
            text: Main message text
            detailed_text: Optional detailed text
            buttons: Standard buttons to show
            
        Returns:
            Button code that was clicked
        """
        msg_box = QMessageBox(parent)
        msg_box.setIcon(QMessageBox.Icon.Warning)
        msg_box.setWindowTitle(title)
        msg_box.setText(text)
        
        if detailed_text:
            msg_box.setDetailedText(detailed_text)
            
        msg_box.setStandardButtons(buttons)
        msg_box.setDefaultButton(
            QMessageBox.StandardButton.Ok if buttons & QMessageBox.StandardButton.Ok 
            else QMessageBox.StandardButton.Cancel
        )
        
        return msg_box.exec()
    
    @staticmethod
    def question(
        parent: Optional[QWidget] = None,
        title: str = "Question",
        text: str = "",
        detailed_text: str = "",
        buttons: QMessageBox.StandardButton = QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        default_button: Optional[QMessageBox.StandardButton] = None
    ) -> int:
        """Create a question message box
        
        Args:
            parent: Parent widget
            title: Window title
            text: Main message text
            detailed_text: Optional detailed text
            buttons: Standard buttons to show
            default_button: Default button to highlight
            
        Returns:
            Button code that was clicked
        """
        msg_box = QMessageBox(parent)
        msg_box.setIcon(QMessageBox.Icon.Question)
        msg_box.setWindowTitle(title)
        msg_box.setText(text)
        
        if detailed_text:
            msg_box.setDetailedText(detailed_text)
            
        msg_box.setStandardButtons(buttons)
        
        if default_button:
            msg_box.setDefaultButton(default_button)
        elif buttons & QMessageBox.StandardButton.Yes:
            msg_box.setDefaultButton(QMessageBox.StandardButton.Yes)
            
        return msg_box.exec()
    
    @staticmethod
    def information(
        parent: Optional[QWidget] = None,
        title: str = "Information",
        text: str = "",
        detailed_text: str = "",
        buttons: QMessageBox.StandardButton = QMessageBox.StandardButton.Ok
    ) -> int:
        """Create an information message box
        
        Args:
            parent: Parent widget
            title: Window title
            text: Main message text
            detailed_text: Optional detailed text
            buttons: Standard buttons to show
            
        Returns:
            Button code that was clicked
        """
        msg_box = QMessageBox(parent)
        msg_box.setIcon(QMessageBox.Icon.Information)
        msg_box.setWindowTitle(title)
        msg_box.setText(text)
        
        if detailed_text:
            msg_box.setDetailedText(detailed_text)
            
        msg_box.setStandardButtons(buttons)
        msg_box.setDefaultButton(QMessageBox.StandardButton.Ok)
        
        return msg_box.exec()
    
    @staticmethod
    def critical(
        parent: Optional[QWidget] = None,
        title: str = "Error",
        text: str = "",
        detailed_text: str = "",
        buttons: QMessageBox.StandardButton = QMessageBox.StandardButton.Ok
    ) -> int:
        """Create a critical error message box
        
        Args:
            parent: Parent widget
            title: Window title
            text: Main message text
            detailed_text: Optional detailed text
            buttons: Standard buttons to show
            
        Returns:
            Button code that was clicked
        """
        msg_box = QMessageBox(parent)
        msg_box.setIcon(QMessageBox.Icon.Critical)
        msg_box.setWindowTitle(title)
        msg_box.setText(text)
        
        if detailed_text:
            msg_box.setDetailedText(detailed_text)
            
        msg_box.setStandardButtons(buttons)
        msg_box.setDefaultButton(QMessageBox.StandardButton.Ok)
        
        return msg_box.exec()
    
    @staticmethod
    def confirm_action(
        parent: Optional[QWidget] = None,
        title: str = "Confirm Action",
        text: str = "Are you sure you want to continue?",
        action_name: str = "action"
    ) -> bool:
        """Show a standard confirmation dialog for destructive actions
        
        Args:
            parent: Parent widget
            title: Window title
            text: Main message text
            action_name: Name of the action being confirmed
            
        Returns:
            True if user confirmed, False if cancelled
        """
        result = MessageBoxFactory.question(
            parent=parent,
            title=title,
            text=text,
            buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            default_button=QMessageBox.StandardButton.Cancel
        )
        return result == QMessageBox.StandardButton.Yes
    
    @staticmethod
    def show_error(
        parent: Optional[QWidget] = None,
        title: str = "Error",
        message: str = "An error occurred",
        exception: Optional[Exception] = None
    ) -> int:
        """Show a standardized error message
        
        Args:
            parent: Parent widget
            title: Window title
            message: Error message
            exception: Optional exception for detailed text
            
        Returns:
            Button code that was clicked
        """
        detailed_text = ""
        if exception:
            detailed_text = f"Error details:\n{type(exception).__name__}: {str(exception)}"
            
        return MessageBoxFactory.critical(
            parent=parent,
            title=title,
            text=message,
            detailed_text=detailed_text
        )
    
    @staticmethod
    def ask_yes_no(
        parent: Optional[QWidget] = None,
        title: str = "Question",
        text: str = "Continue?",
        default_yes: bool = True
    ) -> bool:
        """Simple yes/no question dialog
        
        Args:
            parent: Parent widget
            title: Window title
            text: Question text
            default_yes: Whether Yes is the default button
            
        Returns:
            True if Yes was clicked, False if No
        """
        result = MessageBoxFactory.question(
            parent=parent,
            title=title,
            text=text,
            buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            default_button=(
                QMessageBox.StandardButton.Yes if default_yes 
                else QMessageBox.StandardButton.No
            )
        )
        return result == QMessageBox.StandardButton.Yes
    
    @staticmethod
    def ask_save_discard_cancel(
        parent: Optional[QWidget] = None,
        title: str = "Unsaved Changes",
        text: str = "Do you want to save your changes?",
        save_text: str = "Save",
        discard_text: str = "Don't Save"
    ) -> str:
        """Standard save/discard/cancel dialog for unsaved changes
        
        Args:
            parent: Parent widget
            title: Window title
            text: Main message text
            save_text: Text for save button
            discard_text: Text for discard button
            
        Returns:
            'save', 'discard', or 'cancel' based on user choice
        """
        msg_box = QMessageBox(parent)
        msg_box.setIcon(QMessageBox.Icon.Question)
        msg_box.setWindowTitle(title)
        msg_box.setText(text)
        
        save_button = msg_box.addButton(save_text, QMessageBox.ButtonRole.AcceptRole)
        discard_button = msg_box.addButton(discard_text, QMessageBox.ButtonRole.DestructiveRole)
        cancel_button = msg_box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        
        msg_box.setDefaultButton(save_button)
        
        result = msg_box.exec()
        clicked_button = msg_box.clickedButton()
        
        if clicked_button == save_button:
            return 'save'
        elif clicked_button == discard_button:
            return 'discard'
        else:
            return 'cancel'


# Convenience functions for common patterns
def show_warning(parent: Optional[QWidget], title: str, message: str) -> None:
    """Show a simple warning message"""
    MessageBoxFactory.warning(parent, title, message)


def show_error(parent: Optional[QWidget], title: str, message: str, exception: Optional[Exception] = None) -> None:
    """Show a simple error message"""
    MessageBoxFactory.show_error(parent, title, message, exception)


def show_info(parent: Optional[QWidget], title: str, message: str) -> None:
    """Show a simple information message"""
    MessageBoxFactory.information(parent, title, message)


def ask_confirmation(parent: Optional[QWidget], title: str, message: str) -> bool:
    """Ask for user confirmation"""
    return MessageBoxFactory.confirm_action(parent, title, message)


def ask_yes_no(parent: Optional[QWidget], title: str, message: str, default_yes: bool = True) -> bool:
    """Ask a simple yes/no question"""
    return MessageBoxFactory.ask_yes_no(parent, title, message, default_yes)