"""Configuration for integration tests.

Integration tests require a running server and database.
They are skipped by default unless --run-integration is passed.

Usage:
    # Run unit tests only (default):
    pytest

    # Run integration tests (requires server on localhost:8001):
    pytest --run-integration
"""

import pytest


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
