#!/usr/bin/env python3
"""
Splash screen with animated GIF and random status updates for imxup GUI
"""

import os
import random
import threading
import time
from PyQt6.QtWidgets import QSplashScreen, QApplication, QVBoxLayout, QLabel, QWidget
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize
from PyQt6.QtGui import QPixmap, QFont, QPainter, QColor, QMovie


class SplashScreen(QSplashScreen):
    """Custom splash screen with animated GIF and status updates"""
    
    def __init__(self):
        # Create a base pixmap for the splash screen
        pixmap = QPixmap(480, 350)
        pixmap.fill(QColor(45, 52, 64))  # Dark blue-gray background
        super().__init__(pixmap, Qt.WindowType.WindowStaysOnTopHint)
        
        self.status_text = "Initializing"
        self.progress_dots = ""
        
        # Random action words and objects
        self.action_words = [
            "initializing", "activating", "establishing", "launching", "constructing",
            "inventing", "fabricating", "concocting", "devising", "improvising",
            "actuating", "starting", "mobilizing", "arousing", "galvanizing",
            "configuring", "populating", "instantiating", "kicking", "muttering at",
            "rebooting", "stabilizing", "normalizing", "approximating", "recombinating",
            "deriving", "extrapolating", "inseminating", "obliterating", "annihilating",
            "observifying", "recalibrating", "accelerating", "optimizing", "intubating",
            "exorcising"
        ]
        
        self.objects = [
            "PyQt6", "database connection", "galleries", "tab manager", "QueueManager",
            "main GUI", "upload engine", "settings manager", "image scanner", "file system",
            "SSL certificates", "network adapter", "memory allocator", "thread pool",
            "cache manager", "template engine", "BBCode parser", "progress tracker",
            "status monitor", "cookie jar", "session handler", "encryption module",
            "thumbnail generator", "metadata extractor", "queue processor", "drag handler"
        ]
        
        # Get version info
        try:
            from imxup import __version__
            self.version = f"v{__version__}"
        except:
            self.version = "v1.0"
        
        # Auto-cycling timer for random status updates
        self.random_timer = QTimer()
        self.random_timer.timeout.connect(self.update_random_status)
        self.random_timer.start(random.randint(300, 700))  # Random interval
    
    def paintEvent(self, event):
        """Custom paint event to draw text and layout"""
        super().paintEvent(event)
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Draw solid border
        painter.setPen(QColor(200, 200, 200))
        painter.drawRect(0, 0, self.width() - 1, self.height() - 1)
        
        # Draw title at top
        painter.setPen(QColor(255, 255, 255))
        title_font = QFont("Arial", 16, QFont.Weight.Bold)
        painter.setFont(title_font)
        title_text = "IMX.to Gallery Uploader"
        title_rect = painter.fontMetrics().boundingRect(title_text)
        title_x = (self.width() - title_rect.width()) // 2
        painter.drawText(title_x, 40, title_text)
        
        # Draw version
        version_font = QFont("Arial", 11)
        painter.setFont(version_font)
        painter.setPen(QColor(180, 180, 180))
        version_rect = painter.fontMetrics().boundingRect(self.version)
        version_x = (self.width() - version_rect.width()) // 2
        painter.drawText(version_x, 60, self.version)
        
        # Draw copyright and license info
        painter.setPen(QColor(150, 150, 150))
        license_font = QFont("Arial", 8)
        painter.setFont(license_font)
        
        license_lines = [
            "Copyright © 2025 by twat",
            "",
            "Licensed under the Apache License, Version 2.0",
            "",
            "THIS SOFTWARE IS DISTRIBUTED ON AN \"AS IS\" BASIS, WITHOUT",
            "WARRANTIES OR CONDITIONS OF ANY KIND, EXPRESS OR IMPLIED."
        ]
        
        y_pos = 90
        for line in license_lines:
            if line:
                line_rect = painter.fontMetrics().boundingRect(line)
                line_x = (self.width() - line_rect.width()) // 2
                painter.drawText(line_x, y_pos, line)
            y_pos += 12
        
        # Draw status text at bottom
        painter.setPen(QColor(255, 255, 255))
        status_font = QFont("Courier", 11)
        painter.setFont(status_font)
        
        status_rect = painter.fontMetrics().boundingRect(self.status_text)
        status_x = (self.width() - status_rect.width()) // 2
        painter.drawText(status_x, self.height() - 45, self.status_text)
        
        # Draw progress dots in fixed position (left-aligned within centered area)
        dots_font = QFont("Courier", 11)
        painter.setFont(dots_font)
        painter.setPen(QColor(180, 180, 180))
        
        # Create a fixed-width area for dots (centered, but dots are left-aligned within it)
        dots_area_width = 50
        dots_area_x = (self.width() - dots_area_width) // 2
        painter.drawText(dots_area_x, self.height() - 25, self.progress_dots)
        
        painter.end()
    
    
    def update_status(self, message):
        """Update the status message and repaint"""
        self.status_text = message
        self.repaint()
        QApplication.processEvents()  # Ensure UI updates immediately
    
    def update_random_status(self):
        """Generate and display a random status update"""
        action = random.choice(self.action_words).title()
        obj = random.choice(self.objects)
        
        # Add some variety to the format
        formats = [
            f"{action} {obj}...",
            f"{action} {obj}",
            f"{action} {random.randint(1, 999)} {obj}...",
            f"{action} the {obj}...",
        ]
        
        status = random.choice(formats)
        self.update_status(status)
        
        # Randomize next update interval
        self.random_timer.setInterval(random.randint(200, 600))
    
    def set_status(self, text):
        """Set status text with random action word and add progress dot"""
        self.random_timer.stop()
        action = random.choice(self.action_words).title()
        self.status_text = f"{action} {text}"
        self.progress_dots += "."
        self.repaint()
        QApplication.processEvents()
    
    def finish_and_hide(self):
        """Clean shutdown of splash screen"""
        if self.random_timer:
            self.random_timer.stop()
        self.hide()