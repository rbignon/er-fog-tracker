"""Configuration for integration tests.

Integration tests require a running server and database.
They are skipped by default unless --run-integration is passed.

Usage:
    # Run unit tests only (default):
    pytest

    # Run integration tests (requires server on localhost:8001):
    pytest --run-integration
"""

import os
from pathlib import Path

import pytest


def pytest_configure(config):
    """Configure integration tests to use the real database.

    When --run-integration is passed, we load the real DATABASE_URL from .env
    instead of using the test SQLite database.
    """
    if config.getoption("--run-integration", default=False):
        # Load DATABASE_URL from .env file (server/ directory)
        env_file = Path(__file__).parent.parent.parent / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip()
                    # Only override DATABASE_URL for integration tests
                    if key == "DATABASE_URL":
                        os.environ["DATABASE_URL"] = value
                        break

        # Clear cached settings/engine to force reload with new DATABASE_URL
        # We need to import and clear caches in a specific order
        import sys

        # Clear config cache first
        if "fogtracker.config" in sys.modules:
            from fogtracker.config import get_settings

            get_settings.cache_clear()

        # Clear database caches
        if "fogtracker.database" in sys.modules:
            from fogtracker.database import get_async_session_maker, get_engine

            get_engine.cache_clear()
            get_async_session_maker.cache_clear()


def pytest_collection_modifyitems(config, items):
    """Skip integration tests unless --run-integration is passed."""
    if config.getoption("--run-integration"):
        # --run-integration given: do not skip integration tests
        return

    skip_integration = pytest.mark.skip(
        reason="Integration tests require --run-integration flag and a running server"
    )
    for item in items:
        # Skip all tests in the integration directory
        if "integration" in str(item.fspath):
            item.add_marker(skip_integration)
