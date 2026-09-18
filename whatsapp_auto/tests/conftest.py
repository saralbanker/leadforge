"""Pytest configuration and shared fixtures for WhatsApp-Auto tests."""

import os
import sys
from pathlib import Path
import pytest

# Ensure whatsapp-auto root is on python path
WHATSAPP_AUTO_ROOT = Path(__file__).resolve().parent.parent
if str(WHATSAPP_AUTO_ROOT) not in sys.path:
    sys.path.insert(0, str(WHATSAPP_AUTO_ROOT))
