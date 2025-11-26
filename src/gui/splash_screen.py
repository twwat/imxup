#!/usr/bin/env python3
"""
Splash screen with animated GIF and random status updates for imxup GUI
"""

import os
import random
#import threading
import time
from PyQt6.QtWidgets import QSplashScreen, QApplication, QVBoxLayout, QLabel, QWidget
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize, QRectF
from PyQt6.QtGui import QPixmap, QFont, QPainter, QColor, QPen, QPainterPath, QRegion


class SplashScreen(QSplashScreen):
    """Custom splash screen with animated GIF and status updates"""
    
    def __init__(self):
        # Create a base pixmap for the splash screen
        pixmap = QPixmap(520, 360)  # Increased height for logo
        pixmap.fill(QColor(29, 22, 22))  # Dark blue-gray background
        super().__init__(pixmap, Qt.WindowType.WindowStaysOnTopHint)
        
        # Load the imxup logo
        try:
            from imxup import get_project_root
            logo_path = os.path.join(get_project_root(), 'assets', 'imxup2.png')
            self.logo_pixmap = QPixmap(logo_path)
            if self.logo_pixmap.isNull():
                self.logo_pixmap = None
        except Exception:
            self.logo_pixmap = None
            
        # Get version info
        try:
            from imxup import get_version
            APP_VERSION = get_version()
            self.version = f"{APP_VERSION} "
        except:
            self.version = "unknown"
        self.random_statuses = ['Establishing alibi...', 'Flicking bean...', 'Wiping front to back...']
        #self.status_text = random.choice(self.init_action_words).title()
               
        # Random action words and objects
        self.action_words = [
            "reinitializing", "activating", "establishing", "launching", "constructing",
            "inventing", "fabricating", "concocting", "devising", "improvising",
            "actuating", "mobilizing", "arousing", "galvanizing", "monetizing", 
            "configuring", "populating", "instantiating", "kicking", "yelling 'fuck you' at",
            "rebooting", "stabilizing", "normalizing", "approximating", "recombinating",
            "deriving", "extrapolating", "inseminating", "obliterating", "annihilating",
            "observifying", "recalibrating", "accelerating", "optimizing", "exorcising",
            "adjusting", "dehumidifying", "hiding", "setting fire to", "vacuuming"
        ]
        
        self.status_text = f"{random.choice(self.action_words).title()} ImxUp v{APP_VERSION}"
        self.progress_dots = ""


        # Set rounded window shape
        self.setWindowShape()
    
    def setWindowShape(self):
        """Set the window to have rounded corners"""
        # Use QRegion constructor that takes QPainterPath directly
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 75, 75)
        # Convert path to region without double polygon conversion
        from PyQt6.QtGui import QTransform
        region = QRegion(path.toFillPolygon(QTransform()).toPolygon())
        self.setMask(region)
    
    def paintEvent(self, event):
        """Custom paint event to draw text and layout"""
        super().paintEvent(event)

        painter = QPainter(self)
        if not painter.isActive():
            # QPainter failed to begin - widget not ready for painting
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Draw rounded border with 2px thickness, 20px radius
        painter.setPen(QPen(QColor(207, 69, 2), 3))
        painter.drawRoundedRect(2, 2, self.width() - 3, self.height() - 3, 75, 75)
        
        # Draw logo at top if available
        y_offset = 16
        if self.logo_pixmap and not self.logo_pixmap.isNull():
            # Scale logo to fit nicely at top
            logo_height = 112
            logo_scaled = self.logo_pixmap.scaledToHeight(logo_height, Qt.TransformationMode.SmoothTransformation)
            logo_x = (self.width() - logo_scaled.width()) // 2
            painter.drawPixmap(logo_x, y_offset, logo_scaled)
            y_offset += logo_height
        
        # Draw version
        version_font = QFont("Courier", 12)
        painter.setFont(version_font)
        painter.setPen(QColor(208, 65, 0))
        version_rect = painter.fontMetrics().boundingRect(self.version)
        version_x = (self.width() - version_rect.width()) // 2
        painter.drawText(version_x, y_offset + 13, self.version)
        y_offset += 24
        
        copyright_text = "Copyright © 2025 twat"
        copyright_font = QFont("Courier", 11)
        painter.setFont(copyright_font)
        painter.setPen(QColor(123, 123, 123))
        copyright_rect = painter.fontMetrics().boundingRect(copyright_text)
        copyright_x = (self.width() - copyright_rect.width()) // 2
        painter.drawText(copyright_x, y_offset + 20, copyright_text)
        y_offset += 40
        
        apache_text = "Licensed under the Apache License, Version 2.0"
        apache_font = QFont("Courier", 12)
        painter.setFont(apache_font)
        painter.setPen(QColor(195, 195, 195))
        apache_rect = painter.fontMetrics().boundingRect(apache_text)
        apache_x = (self.width() - apache_rect.width()) // 2
        painter.drawText(apache_x, y_offset + 20, apache_text)
        y_offset += 50
        
        # Draw copyright and license info
        painter.setPen(QColor(170, 170, 170))
        license_font = QFont("Courier", 9)
        painter.setFont(license_font)

        license_lines = [
            "This software is distributed on an \"AS IS\" basis, without any",
            "warranties or conditions of any kind, express or implied."
        ]

        y_pos = y_offset
        for line in license_lines:
            if line:
                line_rect = painter.fontMetrics().boundingRect(line)
                line_x = (self.width() - line_rect.width()) // 2
                painter.drawText(line_x, y_pos, line)
            y_pos += 16
        
        # Draw status text at bottom
        painter.setPen(QColor(89, 152, 222))
        status_font = QFont("Courier", 9, QFont.Weight.Bold)
        painter.setFont(status_font)
        
        status_rect = painter.fontMetrics().boundingRect(self.status_text)
        status_x = (self.width() - status_rect.width()) // 2
        painter.drawText(status_x, self.height() - 60, self.status_text)
        
        # Draw progress dots centered
        dots_font = QFont("Courier", 12)
        painter.setFont(dots_font)
        painter.setPen(QColor(26, 150, 232))

        # Center the dots by measuring their actual width
        dots_rect = painter.fontMetrics().boundingRect(self.progress_dots)
        dots_x = (self.width() - dots_rect.width()) // 2
        painter.drawText(dots_x, self.height() - 25, self.progress_dots)
        
        painter.end()
    
    def update_status(self, message):
        """Update the status message and repaint"""
        if message == "random":
            message = random.choice(self.random_statuses)
            self.progress_dots += "•"
        elif random.randint(1,20) == 13:
            self.progress_dots += "•"
        self.status_text = message
        self.repaint()
        QApplication.processEvents()  # Ensure UI updates immediately

    def set_status(self, text):
        """Set status text with random action word and add progress dot"""
        #self.random_timer.stop()
        #action = random.choice(self.action_words).title()
        #self.status_text = f"{action} {text}"
        self.status_text = f"{text}"
        
        self.progress_dots += "•"
        self.repaint()
        QApplication.processEvents()
        
    def set_random_status(self, text=""):
        """Set status text with random action word and add progress dot"""
        #self.random_timer.stop()
        action = random.choice(self.random_statuses).capitalize()
        self.status_text = f"{action}"
        self.progress_dots += "•"
        self.repaint()
        QApplication.processEvents()
    
    def finish_and_hide(self):
        """Clean shutdown of splash screen"""
        self.hide()
