"""Pytest configuration for Linkplay tests."""

from __future__ import annotations

import pytest
from unittest.mock import patch
import sys
from pathlib import Path

# Add custom_components to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Enable Home Assistant testing support with asyncio
pytest_plugins = [
    "pytest_homeassistant_custom_component",
    "pytest_asyncio",
]


@pytest.fixture
def mock_aiohttp_session():
    """Mock aiohttp session."""
    with patch("custom_components.linkplay.config_flow.async_get_clientsession") as mock:
        yield mock

