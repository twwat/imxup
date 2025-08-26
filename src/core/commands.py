"""
Command pattern implementation for decoupled operations.
Enables undo/redo, logging, and clean separation of concerns.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Type, Union
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import json
import logging

from .interfaces import (
    IAuthenticationService, ISettingsService, ITemplateService,
    IQueueService, IStorageService, ServiceResponse, ServiceResult
)


class ICommand(ABC):
    """Interface for command pattern implementation."""
    
    @abstractmethod
    def execute(self) -> ServiceResponse:
        """Execute the command."""
        pass
    
    @abstractmethod
    def undo(self) -> ServiceResponse:
        """Undo the command."""
        pass
    
    @property
    @abstractmethod
    def can_undo(self) -> bool:
        """Whether this command can be undone."""
        pass
    
    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description of the command."""
        pass


@dataclass
class CommandContext:
    """Context information for command execution."""
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseCommand(ICommand):
    """Base class for commands with common functionality."""
    
    def __init__(self, context: Optional[CommandContext] = None):
        self.context = context or CommandContext()
        self.executed = False
        self.result: Optional[ServiceResponse] = None
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def execute(self) -> ServiceResponse:
        """Execute the command with error handling and logging."""
        try:
            self.logger.info(f"Executing: {self.description}")
            result = self._execute()
            self.executed = True
            self.result = result
            return result
        except Exception as e:
            error_msg = f"Command failed: {e}"
            self.logger.error(error_msg)
            return ServiceResponse(ServiceResult.FAILURE, error=error_msg)
    
    def undo(self) -> ServiceResponse:
        """Undo the command with error handling and logging."""
        if not self.executed:
            return ServiceResponse(ServiceResult.FAILURE, error="Command not executed")
        
        if not self.can_undo:
            return ServiceResponse(ServiceResult.FAILURE, error="Command cannot be undone")
        
        try:
            self.logger.info(f"Undoing: {self.description}")
            result = self._undo()
            self.executed = False
            return result
        except Exception as e:
            error_msg = f"Undo failed: {e}"
            self.logger.error(error_msg)
            return ServiceResponse(ServiceResult.FAILURE, error=error_msg)
    
    @abstractmethod
    def _execute(self) -> ServiceResponse:
        """Internal execute implementation."""
        pass
    
    @abstractmethod
    def _undo(self) -> ServiceResponse:
        """Internal undo implementation."""
        pass


# Authentication Commands

class LoginCommand(BaseCommand):
    """Command for user authentication."""
    
    def __init__(
        self,
        auth_service: IAuthenticationService,
        username: str,
        password: str,
        context: Optional[CommandContext] = None
    ):
        super().__init__(context)
        self.auth_service = auth_service
        self.username = username
        self.password = password
    
    def _execute(self) -> ServiceResponse:
        return self.auth_service.login(self.username, self.password)
    
    def _undo(self) -> ServiceResponse:
        return self.auth_service.logout()
    
    @property
    def can_undo(self) -> bool:
        return True
    
    @property
    def description(self) -> str:
        return f"Login user: {self.username}"


class LogoutCommand(BaseCommand):
    """Command for user logout."""
    
    def __init__(
        self,
        auth_service: IAuthenticationService,
        context: Optional[CommandContext] = None
    ):
        super().__init__(context)
        self.auth_service = auth_service
        self._previous_user: Optional[str] = None
    
    def _execute(self) -> ServiceResponse:
        self._previous_user = self.auth_service.get_current_user()
        return self.auth_service.logout()
    
    def _undo(self) -> ServiceResponse:
        # Cannot restore session without password
        return ServiceResponse(ServiceResult.FAILURE, error="Cannot restore login session")
    
    @property
    def can_undo(self) -> bool:
        return False
    
    @property
    def description(self) -> str:
        return "Logout user"


# Settings Commands

class UpdateSettingCommand(BaseCommand):
    """Command for updating a setting."""
    
    def __init__(
        self,
        settings_service: ISettingsService,
        key: str,
        new_value: Any,
        context: Optional[CommandContext] = None
    ):
        super().__init__(context)
        self.settings_service = settings_service
        self.key = key
        self.new_value = new_value
        self.old_value: Any = None
    
    def _execute(self) -> ServiceResponse:
        self.old_value = self.settings_service.get(self.key)
        return self.settings_service.set(self.key, self.new_value)
    
    def _undo(self) -> ServiceResponse:
        return self.settings_service.set(self.key, self.old_value)
    
    @property
    def can_undo(self) -> bool:
        return True
    
    @property
    def description(self) -> str:
        return f"Update setting {self.key}: {self.old_value} -> {self.new_value}"


class ResetSettingsCommand(BaseCommand):
    """Command for resetting settings to defaults."""
    
    def __init__(
        self,
        settings_service: ISettingsService,
        context: Optional[CommandContext] = None
    ):
        super().__init__(context)
        self.settings_service = settings_service
        self.backup_settings: Dict[str, Any] = {}
    
    def _execute(self) -> ServiceResponse:
        self.backup_settings = self.settings_service.get_all()
        return self.settings_service.reset_to_defaults()
    
    def _undo(self) -> ServiceResponse:
        # Restore all backed up settings
        for key, value in self.backup_settings.items():
            result = self.settings_service.set(key, value)
            if result.result == ServiceResult.FAILURE:
                return result
        return ServiceResponse(ServiceResult.SUCCESS)
    
    @property
    def can_undo(self) -> bool:
        return True
    
    @property
    def description(self) -> str:
        return "Reset all settings to defaults"


# Template Commands

class SaveTemplateCommand(BaseCommand):
    """Command for saving a template."""
    
    def __init__(
        self,
        template_service: ITemplateService,
        name: str,
        content: str,
        context: Optional[CommandContext] = None
    ):
        super().__init__(context)
        self.template_service = template_service
        self.name = name
        self.content = content
        self.old_content: Optional[str] = None
        self.was_new_template = False
    
    def _execute(self) -> ServiceResponse:
        self.old_content = self.template_service.get_template(self.name)
        self.was_new_template = self.old_content is None
        return self.template_service.save_template(self.name, self.content)
    
    def _undo(self) -> ServiceResponse:
        if self.was_new_template:
            return self.template_service.delete_template(self.name)
        else:
            return self.template_service.save_template(self.name, self.old_content)
    
    @property
    def can_undo(self) -> bool:
        return True
    
    @property
    def description(self) -> str:
        action = "Create" if self.was_new_template else "Update"
        return f"{action} template: {self.name}"


class DeleteTemplateCommand(BaseCommand):
    """Command for deleting a template."""
    
    def __init__(
        self,
        template_service: ITemplateService,
        name: str,
        context: Optional[CommandContext] = None
    ):
        super().__init__(context)
        self.template_service = template_service
        self.name = name
        self.backup_content: Optional[str] = None
    
    def _execute(self) -> ServiceResponse:
        self.backup_content = self.template_service.get_template(self.name)
        if self.backup_content is None:
            return ServiceResponse(ServiceResult.FAILURE, error="Template not found")
        return self.template_service.delete_template(self.name)
    
    def _undo(self) -> ServiceResponse:
        if self.backup_content is not None:
            return self.template_service.save_template(self.name, self.backup_content)
        return ServiceResponse(ServiceResult.FAILURE, error="No backup content")
    
    @property
    def can_undo(self) -> bool:
        return True
    
    @property
    def description(self) -> str:
        return f"Delete template: {self.name}"


# Queue Commands

class AddToQueueCommand(BaseCommand):
    """Command for adding gallery to upload queue."""
    
    def __init__(
        self,
        queue_service: IQueueService,
        folder_path: Path,
        name: str,
        config: Dict[str, Any],
        context: Optional[CommandContext] = None
    ):
        super().__init__(context)
        self.queue_service = queue_service
        self.folder_path = folder_path
        self.name = name
        self.config = config
        self.queue_id: Optional[str] = None
    
    def _execute(self) -> ServiceResponse:
        queue_id = self.queue_service.add_gallery(self.folder_path, self.name, self.config)
        self.queue_id = queue_id
        return ServiceResponse(ServiceResult.SUCCESS, data=queue_id)
    
    def _undo(self) -> ServiceResponse:
        if self.queue_id:
            return self.queue_service.remove_gallery(self.queue_id)
        return ServiceResponse(ServiceResult.FAILURE, error="No queue ID")
    
    @property
    def can_undo(self) -> bool:
        return True
    
    @property
    def description(self) -> str:
        return f"Add to queue: {self.name} ({self.folder_path})"


class RemoveFromQueueCommand(BaseCommand):
    """Command for removing gallery from upload queue."""
    
    def __init__(
        self,
        queue_service: IQueueService,
        storage_service: IStorageService,
        queue_id: str,
        context: Optional[CommandContext] = None
    ):
        super().__init__(context)
        self.queue_service = queue_service
        self.storage_service = storage_service
        self.queue_id = queue_id
        self.backup_data: Optional[Dict[str, Any]] = None
    
    def _execute(self) -> ServiceResponse:
        # Backup gallery data before removal
        self.backup_data = self.storage_service.load_gallery(self.queue_id)
        return self.queue_service.remove_gallery(self.queue_id)
    
    def _undo(self) -> ServiceResponse:
        if self.backup_data:
            # Restore gallery data
            restore_result = self.storage_service.save_gallery(self.backup_data)
            if restore_result.result == ServiceResult.SUCCESS:
                # Re-add to queue
                return self.queue_service.add_gallery(
                    Path(self.backup_data['folder_path']),
                    self.backup_data['name'],
                    self.backup_data['config']
                )
        return ServiceResponse(ServiceResult.FAILURE, error="Cannot restore gallery")
    
    @property
    def can_undo(self) -> bool:
        return self.backup_data is not None
    
    @property
    def description(self) -> str:
        return f"Remove from queue: {self.queue_id}"


# Composite Commands

class CompositeCommand(BaseCommand):
    """Command that executes multiple sub-commands."""
    
    def __init__(
        self,
        commands: List[ICommand],
        name: str,
        context: Optional[CommandContext] = None
    ):
        super().__init__(context)
        self.commands = commands
        self.name = name
        self.executed_commands: List[ICommand] = []
    
    def _execute(self) -> ServiceResponse:
        self.executed_commands = []
        for command in self.commands:
            result = command.execute()
            if result.result == ServiceResult.SUCCESS:
                self.executed_commands.append(command)
            else:
                # Rollback executed commands
                for executed_cmd in reversed(self.executed_commands):
                    if executed_cmd.can_undo:
                        executed_cmd.undo()
                return result
        
        return ServiceResponse(ServiceResult.SUCCESS)
    
    def _undo(self) -> ServiceResponse:
        # Undo in reverse order
        for command in reversed(self.executed_commands):
            if command.can_undo:
                result = command.undo()
                if result.result == ServiceResult.FAILURE:
                    return result
        
        self.executed_commands = []
        return ServiceResponse(ServiceResult.SUCCESS)
    
    @property
    def can_undo(self) -> bool:
        return all(cmd.can_undo for cmd in self.executed_commands)
    
    @property
    def description(self) -> str:
        return self.name


# Command Manager

class CommandManager:
    """Manages command execution, undo/redo functionality."""
    
    def __init__(self, max_history: int = 100):
        self.max_history = max_history
        self.history: List[ICommand] = []
        self.current_index = -1
        self.logger = logging.getLogger(__name__)
    
    def execute(self, command: ICommand) -> ServiceResponse:
        """Execute a command and add it to history."""
        result = command.execute()
        
        if result.result == ServiceResult.SUCCESS:
            # Remove any commands after current position
            self.history = self.history[:self.current_index + 1]
            
            # Add new command
            self.history.append(command)
            self.current_index += 1
            
            # Limit history size
            if len(self.history) > self.max_history:
                self.history = self.history[-self.max_history:]
                self.current_index = len(self.history) - 1
        
        return result
    
    def undo(self) -> ServiceResponse:
        """Undo the last executed command."""
        if not self.can_undo():
            return ServiceResponse(ServiceResult.FAILURE, error="Nothing to undo")
        
        command = self.history[self.current_index]
        result = command.undo()
        
        if result.result == ServiceResult.SUCCESS:
            self.current_index -= 1
        
        return result
    
    def redo(self) -> ServiceResponse:
        """Redo the next command in history."""
        if not self.can_redo():
            return ServiceResponse(ServiceResult.FAILURE, error="Nothing to redo")
        
        command = self.history[self.current_index + 1]
        result = command.execute()
        
        if result.result == ServiceResult.SUCCESS:
            self.current_index += 1
        
        return result
    
    def can_undo(self) -> bool:
        """Check if undo is possible."""
        return (self.current_index >= 0 and 
                self.current_index < len(self.history) and
                self.history[self.current_index].can_undo)
    
    def can_redo(self) -> bool:
        """Check if redo is possible."""
        return (self.current_index + 1 < len(self.history))
    
    def get_history(self) -> List[str]:
        """Get command history descriptions."""
        return [cmd.description for cmd in self.history]
    
    def clear_history(self) -> None:
        """Clear command history."""
        self.history.clear()
        self.current_index = -1