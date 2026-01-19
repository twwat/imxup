#!/usr/bin/env python3
"""
Comprehensive pytest-qt tests for BandwidthManager and BandwidthSource.

This test suite provides thorough coverage including:
- Asymmetric EMA smoothing (alpha_up=0.6 fast rise, alpha_down=0.15 slow decay)
- Multi-source bandwidth aggregation (IMX.to, file hosts, link checker)
- PyQt6 signal emission and reception with qtbot
- Thread safety with QMutex
- QSettings persistence of smoothing parameters
- Peak tracking and session management
- Host lifecycle (creation, completion, cleanup)
- Edge cases and error handling

Uses pytest-qt fixtures for proper Qt integration testing.
"""

import os
import sys
import time
import pytest
from pathlib import Path
from typing import List
from unittest.mock import Mock, patch, MagicMock

from PyQt6.QtCore import QSettings, QTimer
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QSignalSpy

from src.gui.bandwidth_manager import BandwidthManager, BandwidthSource


# Test file content continues...
