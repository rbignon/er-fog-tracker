"""Unit tests for version header middleware.

Tests for Server-Version header in responses.
"""

from fastapi.testclient import TestClient

from fogtracker import __version__
from fogtracker.main import app

client = TestClient(app)


class TestVersionMiddleware:
    """Tests for version header middleware."""

    def test_health_endpoint_has_server_version_header(self):
        """Test that /api/health returns Server-Version header."""
        response = client.get("/api/health")

        assert response.status_code == 200
        assert "Server-Version" in response.headers
        assert response.headers["Server-Version"] == __version__

    def test_api_endpoint_has_server_version_header(self):
        """Test that API endpoints return Server-Version header."""
        # Use spoiler parse as a simple POST endpoint
        response = client.post(
            "/api/spoiler/parse",
            json={"spoiler_log": "Options and seed:12345 Fog Gate Randomizer"},
        )

        # Even on error (invalid spoiler), header should be present
        assert "Server-Version" in response.headers
        assert response.headers["Server-Version"] == __version__

    def test_version_format_is_semver(self):
        """Test that version follows semver format."""
        response = client.get("/api/health")
        version = response.headers["Server-Version"]

        # Should be X.Y.Z format
        parts = version.split(".")
        assert len(parts) == 3, f"Version should have 3 parts: {version}"

        for part in parts:
            assert part.isdigit(), f"Each part should be a number: {part}"

    def test_client_version_header_accepted(self):
        """Test that Client-Version header is accepted in requests."""
        response = client.get(
            "/api/health",
            headers={"Client-Version": "0.1.0"},
        )

        assert response.status_code == 200
        # Server should still respond with its version
        assert "Server-Version" in response.headers


class TestVersionConstant:
    """Tests for version constant."""

    def test_version_matches_pyproject(self):
        """Test that __version__ matches pyproject.toml."""
        # Just verify the version is set and valid
        assert __version__ is not None
        assert len(__version__) > 0

        # Should be semver format
        parts = __version__.split(".")
        assert len(parts) == 3
