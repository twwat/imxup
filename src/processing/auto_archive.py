#!/usr/bin/env python3
"""
Auto-Archive Engine for automatically moving completed galleries to the Archive tab.

This module provides comprehensive auto-archive functionality that integrates with
the existing tab management and queue systems. It monitors gallery status changes
and applies configurable criteria to automatically archive qualifying galleries.

Key Features:
- Real-time status change monitoring
- Configurable criteria (status types, time thresholds)
- Periodic cleanup for galleries that meet time-based criteria
- Integration with existing TabManager and QueueManager
- Efficient batch operations for large numbers of galleries
- Graceful error handling and fallback behavior

Architecture Integration:
- Connects to QueueManager status change signals
- Uses TabManager for configuration and gallery moves
- Emits signals for UI updates and notifications
- QSettings integration for persistent configuration
"""

from __future__ import annotations

import time
import logging
from typing import Dict, List, Optional, Set, Any
from dataclasses import dataclass
from PyQt6.QtCore import QObject, QTimer, pyqtSignal, QSettings

from src.gui.tab_manager import TabManager


@dataclass
class AutoArchiveConfig:
    """Configuration for auto-archive behavior"""
    enabled: bool = False
    days_threshold: int = 30
    archive_statuses: Set[str] = None
    immediate_archive: bool = True  # Archive immediately on status change
    periodic_check_minutes: int = 60  # Periodic check interval
    
    def __post_init__(self):
        if self.archive_statuses is None:
            self.archive_statuses = {"completed", "failed"}


class AutoArchiveEngine(QObject):
    """
    Centralized auto-archive engine that monitors gallery status changes and
    automatically moves qualifying galleries to the Archive tab.
    
    This engine provides both real-time status change monitoring and periodic
    time-based cleanup. It integrates seamlessly with the existing TabManager
    and QueueManager architecture.
    
    Signals:
        galleries_archived(gallery_paths, reason): Galleries were auto-archived
        archive_candidate_found(gallery_path, reason): Gallery qualifies for archiving
        config_changed(): Auto-archive configuration was updated
        error_occurred(error_message): Error during auto-archive operation
    """
    
    # Signals
    galleries_archived = pyqtSignal(list, str)  # List[str] paths, reason
    archive_candidate_found = pyqtSignal(str, str)  # gallery_path, reason
    config_changed = pyqtSignal()
    error_occurred = pyqtSignal(str)  # error_message
    
    def __init__(self, tab_manager: TabManager, settings_org: str = "ImxUploader", 
                 settings_app: str = "AutoArchive"):
        """
        Initialize the auto-archive engine.
        
        Args:
            tab_manager: TabManager instance for configuration and operations
            settings_org: QSettings organization name
            settings_app: QSettings application name
        """
        super().__init__()
        
        # Set up logging first
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        
        self._tab_manager = tab_manager
        self._settings = QSettings(settings_org, settings_app)
        self._config = AutoArchiveConfig()
        self._last_check_time = 0
        
        # Periodic timer for time-based checks
        self._periodic_timer = QTimer()
        self._periodic_timer.timeout.connect(self._run_periodic_check)
        
        # Track recently processed galleries to avoid duplicate processing
        self._recently_processed: Dict[str, float] = {}
        self._process_cooldown = 5.0  # 5 second cooldown between processing same gallery
        
        # Performance tracking
        self._stats = {
            'status_triggers': 0,
            'time_triggers': 0,
            'galleries_archived': 0,
            'errors': 0
        }
        
        # Load configuration from TabManager and QSettings
        self._load_configuration()
        
        # Connect to TabManager signals for configuration updates
        self._tab_manager.auto_archive_triggered.connect(self._handle_tab_manager_archive)
        
    # ----------------------------- Configuration Management -----------------------------
    
    def _load_configuration(self) -> None:
        """Load auto-archive configuration from TabManager and QSettings"""
        try:
            # Get primary configuration from TabManager
            enabled, days, statuses = self._tab_manager.get_auto_archive_config()
            
            # Load additional settings from QSettings
            immediate = self._settings.value("immediate_archive", True, type=bool)
            check_minutes = self._settings.value("periodic_check_minutes", 60, type=int)
            
            # Update configuration
            self._config.enabled = enabled
            self._config.days_threshold = days
            self._config.archive_statuses = statuses
            self._config.immediate_archive = immediate
            self._config.periodic_check_minutes = max(1, min(1440, check_minutes))  # 1 min to 24 hours
            
            # Update periodic timer
            self._update_periodic_timer()
            
            self._logger.info(f"Loaded auto-archive config: enabled={enabled}, "
                            f"days={days}, statuses={statuses}, immediate={immediate}")
            
        except Exception as e:
            self._logger.error(f"Failed to load auto-archive configuration: {e}")
            # Use default configuration on error
            self._config = AutoArchiveConfig()
    
    def update_configuration(self, enabled: Optional[bool] = None, 
                           days_threshold: Optional[int] = None,
                           archive_statuses: Optional[Set[str]] = None,
                           immediate_archive: Optional[bool] = None,
                           periodic_check_minutes: Optional[int] = None) -> None:
        """
        Update auto-archive configuration.
        
        Args:
            enabled: Whether auto-archive is enabled
            days_threshold: Days threshold for time-based archiving
            archive_statuses: Set of statuses to auto-archive
            immediate_archive: Whether to archive immediately on status change
            periodic_check_minutes: Periodic check interval in minutes
        """
        try:
            config_changed = False
            
            # Update TabManager configuration if primary settings changed
            if (enabled is not None or days_threshold is not None or 
                archive_statuses is not None):
                
                new_enabled = enabled if enabled is not None else self._config.enabled
                # Validate and clamp days_threshold
                if days_threshold is not None:
                    new_days = max(1, min(365, days_threshold))  # Clamp to 1-365 days
                else:
                    new_days = self._config.days_threshold
                new_statuses = archive_statuses if archive_statuses is not None else self._config.archive_statuses
                
                self._tab_manager.set_auto_archive_config(new_enabled, new_days, new_statuses)
                
                self._config.enabled = new_enabled
                self._config.days_threshold = new_days
                self._config.archive_statuses = new_statuses
                config_changed = True
            
            # Update additional settings in QSettings
            if immediate_archive is not None:
                self._config.immediate_archive = immediate_archive
                self._settings.setValue("immediate_archive", immediate_archive)
                config_changed = True
            
            if periodic_check_minutes is not None:
                self._config.periodic_check_minutes = max(1, min(1440, periodic_check_minutes))
                self._settings.setValue("periodic_check_minutes", self._config.periodic_check_minutes)
                self._update_periodic_timer()
                config_changed = True
            
            if config_changed:
                self.config_changed.emit()
                self._logger.info(f"Updated auto-archive config: {self._config}")
                
        except Exception as e:
            error_msg = f"Failed to update auto-archive configuration: {e}"
            self._logger.error(error_msg)
            self.error_occurred.emit(error_msg)
    
    def get_configuration(self) -> AutoArchiveConfig:
        """Get current auto-archive configuration"""
        return self._config
    
    def _update_periodic_timer(self) -> None:
        """Update periodic timer based on current configuration"""
        if self._config.enabled and self._config.periodic_check_minutes > 0:
            interval_ms = self._config.periodic_check_minutes * 60 * 1000
            self._periodic_timer.start(interval_ms)
            self._logger.debug(f"Started periodic timer: {self._config.periodic_check_minutes} minutes")
        else:
            self._periodic_timer.stop()
            self._logger.debug("Stopped periodic timer")
    
    # ----------------------------- Status Change Monitoring -----------------------------
    
    def on_gallery_status_changed(self, gallery_path: str, old_status: str, new_status: str) -> None:
        """
        Handle gallery status change events.
        
        This method should be connected to QueueManager status change signals
        to provide real-time auto-archive functionality.
        
        Args:
            gallery_path: Path to the gallery that changed status
            old_status: Previous status
            new_status: New status
        """
        if not self._config.enabled or not self._config.immediate_archive:
            return
        
        try:
            # Skip if not an archivable status
            if new_status not in self._config.archive_statuses:
                return
            
            # Skip if recently processed (avoid duplicate processing)
            current_time = time.time()
            if (gallery_path in self._recently_processed and 
                current_time - self._recently_processed[gallery_path] < self._process_cooldown):
                return
            
            # Mark as recently processed
            self._recently_processed[gallery_path] = current_time
            
            # Check if gallery should be archived
            if self._should_archive_gallery(gallery_path, new_status):
                reason = f"Status changed to '{new_status}'"
                self.archive_candidate_found.emit(gallery_path, reason)
                
                # Attempt to archive the gallery
                success = self._archive_single_gallery(gallery_path, reason)
                if success:
                    self._stats['status_triggers'] += 1
                    self._stats['galleries_archived'] += 1
                    self._logger.info(f"Auto-archived gallery '{gallery_path}' due to status change")
            
        except Exception as e:
            error_msg = f"Error processing status change for '{gallery_path}': {e}"
            self._logger.error(error_msg)
            self.error_occurred.emit(error_msg)
            self._stats['errors'] += 1
    
    def _should_archive_gallery(self, gallery_path: str, status: str) -> bool:
        """
        Determine if a gallery should be archived based on current criteria.
        
        Args:
            gallery_path: Path to the gallery
            status: Current status of the gallery
            
        Returns:
            True if gallery should be archived
        """
        try:
            # Check status criteria
            if status not in self._config.archive_statuses:
                return False
            
            # For immediate archiving, we only check status (time will be checked periodically)
            # This ensures galleries are archived as soon as they reach qualifying status
            return True
            
        except Exception as e:
            self._logger.error(f"Error checking archive criteria for '{gallery_path}': {e}")
            return False
    
    # ----------------------------- Periodic Time-Based Archiving -----------------------------
    
    def _run_periodic_check(self) -> None:
        """Run periodic check for galleries that meet time-based archive criteria"""
        if not self._config.enabled:
            return
        
        try:
            self._last_check_time = time.time()
            
            # Use TabManager's existing functionality for finding candidates
            candidates = self._tab_manager.check_auto_archive_candidates()
            
            if candidates:
                reason = f"Periodic check: older than {self._config.days_threshold} days"
                
                # Emit candidate found signals
                for gallery_path in candidates:
                    self.archive_candidate_found.emit(gallery_path, reason)
                
                # Execute batch archive operation
                archived_count = self._tab_manager.execute_auto_archive()
                
                if archived_count > 0:
                    self.galleries_archived.emit(candidates[:archived_count], reason)
                    self._stats['time_triggers'] += 1
                    self._stats['galleries_archived'] += archived_count
                    self._logger.info(f"Periodic check archived {archived_count} galleries")
            
        except Exception as e:
            error_msg = f"Error during periodic auto-archive check: {e}"
            self._logger.error(error_msg)
            self.error_occurred.emit(error_msg)
            self._stats['errors'] += 1
    
    def run_manual_check(self) -> int:
        """
        Run manual auto-archive check and return number of galleries archived.
        
        Returns:
            Number of galleries archived
        """
        try:
            if not self._config.enabled:
                return 0
            
            # Use TabManager's existing functionality
            archived_count = self._tab_manager.execute_auto_archive()
            
            if archived_count > 0:
                # Get the candidates to emit the signal
                candidates = self._tab_manager.check_auto_archive_candidates()
                reason = "Manual execution"
                self.galleries_archived.emit(candidates[:archived_count], reason)
                self._stats['galleries_archived'] += archived_count
                self._logger.info(f"Manual check archived {archived_count} galleries")
            
            return archived_count
            
        except Exception as e:
            error_msg = f"Error during manual auto-archive check: {e}"
            self._logger.error(error_msg)
            self.error_occurred.emit(error_msg)
            self._stats['errors'] += 1
            return 0
    
    def _archive_single_gallery(self, gallery_path: str, reason: str) -> bool:
        """
        Archive a single gallery to the Archive tab.
        
        Args:
            gallery_path: Path to gallery to archive
            reason: Reason for archiving
            
        Returns:
            True if successfully archived
        """
        try:
            # Use TabManager to move the gallery
            moved_count = self._tab_manager.move_galleries_to_tab([gallery_path], 'Archive')
            
            if moved_count > 0:
                self.galleries_archived.emit([gallery_path], reason)
                return True
            else:
                self._logger.warning(f"Failed to archive gallery '{gallery_path}': move operation returned 0")
                return False
                
        except Exception as e:
            self._logger.error(f"Error archiving gallery '{gallery_path}': {e}")
            return False
    
    # ----------------------------- TabManager Integration -----------------------------
    
    def _handle_tab_manager_archive(self, gallery_paths: List[str]) -> None:
        """Handle auto-archive events from TabManager"""
        if gallery_paths:
            reason = "TabManager auto-archive"
            self.galleries_archived.emit(gallery_paths, reason)
            self._stats['galleries_archived'] += len(gallery_paths)
    
    # ----------------------------- Status and Statistics -----------------------------
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get auto-archive operation statistics"""
        return {
            'status_triggers': self._stats['status_triggers'],
            'time_triggers': self._stats['time_triggers'],
            'galleries_archived': self._stats['galleries_archived'],
            'errors': self._stats['errors'],
            'last_check_time': self._last_check_time,
            'recently_processed_count': len(self._recently_processed),
            'configuration': {
                'enabled': self._config.enabled,
                'days_threshold': self._config.days_threshold,
                'archive_statuses': list(self._config.archive_statuses),
                'immediate_archive': self._config.immediate_archive,
                'periodic_check_minutes': self._config.periodic_check_minutes
            }
        }
    
    def reset_statistics(self) -> None:
        """Reset operation statistics"""
        self._stats = {
            'status_triggers': 0,
            'time_triggers': 0,
            'galleries_archived': 0,
            'errors': 0
        }
        self._recently_processed.clear()
        self._last_check_time = 0
    
    def cleanup_recently_processed(self) -> None:
        """Clean up old entries from recently processed cache"""
        current_time = time.time()
        cutoff_time = current_time - (self._process_cooldown * 2)  # Keep entries for 2x cooldown period
        
        # Remove old entries
        expired_paths = [path for path, timestamp in self._recently_processed.items() 
                        if timestamp < cutoff_time]
        
        for path in expired_paths:
            del self._recently_processed[path]
    
    # ----------------------------- Lifecycle Management -----------------------------
    
    def start(self) -> None:
        """Start the auto-archive engine"""
        try:
            self._load_configuration()
            self._update_periodic_timer()
            self._logger.info("Auto-archive engine started")
            
        except Exception as e:
            error_msg = f"Failed to start auto-archive engine: {e}"
            self._logger.error(error_msg)
            self.error_occurred.emit(error_msg)
    
    def stop(self) -> None:
        """Stop the auto-archive engine"""
        try:
            self._periodic_timer.stop()
            self._recently_processed.clear()
            self._logger.info("Auto-archive engine stopped")
            
        except Exception as e:
            self._logger.error(f"Error stopping auto-archive engine: {e}")
    
    def __del__(self):
        """Cleanup on destruction"""
        try:
            self.stop()
        except:
            pass