#!/usr/bin/env python3
"""
Simple launcher for the IMX.to GUI uploader
"""

import sys
import os

# Add current directory to path to find imxup module
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from src.gui import main_window
    main_window.main()
except ImportError as e:
    print("Error: PyQt6 is required for GUI mode.")
    print("Install with: pip install PyQt6")
    print(f"Import error: {e}")
    sys.exit(1)
except Exception as e:
    print(f"Error launching GUI: {e}")
    sys.exit(1)