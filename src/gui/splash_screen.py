#!/usr/bin/env python3
"""
Splash screen with animated GIF and random status updates for bbdrop GUI
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
        pixmap = QPixmap(620, 405)  # Increased height for logo
        pixmap.fill(QColor(29, 22, 22))  # Dark blue-gray background
        super().__init__(pixmap, Qt.WindowType.WindowStaysOnTopHint)
        
        # Load the bbdrop logo
        try:
            from bbdrop import get_project_root
            logo_path = os.path.join(get_project_root(), 'assets', 'bbdrop2.png')
            self.logo_pixmap = QPixmap(logo_path)
            if self.logo_pixmap.isNull():
                self.logo_pixmap = None
        except Exception:
            self.logo_pixmap = None
            
        # Get version info
        try:
            from bbdrop import get_version
            APP_VERSION = get_version()
            self.version = f"bbdrop v{APP_VERSION}    "
        except (ImportError, ModuleNotFoundError):
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
        
        self.status_text = f"{random.choice(self.action_words).title()} BBDrop v{APP_VERSION}"
        self.progress_dots = ""


        # Set rounded window shape
        self.setWindowShape()
    
    def setWindowShape(self):
        """Set the window to have rounded corners"""
        # Use QRegion constructor that takes QPainterPath directly
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 78, 78)
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
        painter.setPen(QPen(QColor(0,124,250), 3))
        painter.drawRoundedRect(2, 2, self.width() - 3, self.height() - 3, 80, 80)
        
        # Draw logo at top if available
        y_offset = 22
        if self.logo_pixmap and not self.logo_pixmap.isNull():
            # Scale logo to fit nicely at top
            logo_height = 120
            logo_scaled = self.logo_pixmap.scaledToHeight(logo_height, Qt.TransformationMode.SmoothTransformation)
            logo_x = (self.width() - logo_scaled.width()) // 2
            painter.drawPixmap(logo_x, y_offset, logo_scaled)
            y_offset += logo_height - 32

        # Draw version
        version_font = QFont("Courier", 13, QFont.Weight.Bold)
        painter.setFont(version_font)
        painter.setPen(QColor(0,124,250))
        version_rect = painter.fontMetrics().boundingRect(self.version)
        version_x = (self.width() - version_rect.width()) // 2
        painter.drawText(version_x, y_offset + 12, self.version)
        y_offset += 42
        
        copyright_text = "Copyright © 2025-2026 twat"
        copyright_font = QFont("Courier", 12)
        painter.setFont(copyright_font)
        painter.setPen(QColor(148, 138, 126))
        copyright_rect = painter.fontMetrics().boundingRect(copyright_text)
        copyright_x = (self.width() - copyright_rect.width()) // 2
        painter.drawText(copyright_x, y_offset + 20, copyright_text)
        y_offset += 45
        
        mit_text = "Licensed under the MIT License"
        mit_font = QFont("Courier", 12)
        painter.setFont(mit_font)
        painter.setPen(QColor(195, 195, 195))
        mit_rect = painter.fontMetrics().boundingRect(mit_text)
        mit_x = (self.width() - mit_rect.width()) // 2
        painter.drawText(mit_x, y_offset + 20, mit_text)
        y_offset += 68
        
        # Draw copyright and license info
        painter.setPen(QColor(102, 99, 99))
        license_font = QFont("Courier New", 8)
        painter.setFont(license_font)

        license_lines = [
            "THE SOFTWARE IS PROVIDED \"AS IS\", WITHOUT WARRANTIES OF ANY KIND, EXPRESS OR",
            "IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS",
            "FOR A PARTICULAR PURPOSE AND NON-INFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR",
            "COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER",
            "IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN",
            "CONNECTION WITH THE SOFTWARE OR THE USE OR DEALINGS IN THE SOFTWARE."
            #"THE SOFTWARE IS PROVIDED 'AS IS', WITHOUT WARRANTY OF ANY KIND, EXPRESS OR",
            #"IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,",
            #"FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE",
            #"THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR",
            #"OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE,",
            #"ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR",
            #"THE USE OR OTHER DEALINGS IN THE SOFTWARE.      "
        ]

        y_pos = y_offset
        for line in license_lines:
            if line:
                line_rect = painter.fontMetrics().boundingRect(line)
                line_x = (self.width() - line_rect.width()) // 2
                painter.drawText(line_x, y_pos, line)
            if line=="":
                y_pos += 6
            else:
                y_pos += 14
        
        # Draw status text at bottom
        #painter.setPen(QColor(89, 152, 222))
        painter.setPen(QColor(16,141,204))
        status_font = QFont("Verdana", 11)
        #status_font = QFont("Arial", 11, QFont.Weight.Bold)
        painter.setFont(status_font)
        
        status_rect = painter.fontMetrics().boundingRect(self.status_text)
        status_x = (self.width() - status_rect.width()) // 2
        painter.drawText(status_x, self.height() - 35, self.status_text)
        
        # Draw progress dots centered
        dots_font = QFont("Courier", 12)
        painter.setFont(dots_font)
        #painter.setPen(QColor(89, 152, 222))
        painter.setPen(QColor(16, 141, 204))

        # Center the dots by measuring their actual width
        dots_rect = painter.fontMetrics().boundingRect(self.progress_dots)
        dots_x = (self.width() - dots_rect.width()) // 2
        painter.drawText(dots_x, self.height() - 10, self.progress_dots)
        
        painter.end()
    
    def update_status(self, message):
        """Update the status message and repaint"""
        if message == "random":
            message = random.choice(self.random_statuses)
            self.progress_dots += "•"
        elif random.randint(1,20) == 13:
            self.progress_dots += "•"
        self.status_text = f"{message}"
        self.repaint()
        QApplication.processEvents()  # Ensure UI updates immediately

    def set_status(self, text):
        """Set status text with progress dot"""
        #self.random_timer.stop()
        #action = random.choice(self.action_words).title()
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
        self.close()  # Required for WSL/X11 - hide() alone doesn't close the window
