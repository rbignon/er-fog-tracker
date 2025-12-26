"""Unit tests for mod WebSocket handler.

Tests the zone_query handler logic for resolving zones after fast travel.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from fogvizu.websocket.mod import ModClient


class TestZoneQueryHandler:
    """Tests for _handle_zone_query method."""

    @pytest.fixture
    def mock_client(self):
        """Create a ModClient with mocked WebSocket and game_id."""
        ws = AsyncMock()
        game_id = uuid4()
        user = MagicMock()
        user.id = 1
        client = ModClient(ws, game_id, user)
        client.send = AsyncMock()
        return client

    @pytest.fixture
    def sample_zone_links(self):
        """Sample zone_links for testing."""
        return [
            {
                "id": "link1",
                "source": "Limgrave",
                "target": "Stormveil Castle",
                "type": "random",
            },
            {
                "id": "link2",
                "source": "Stormveil Castle",
                "target": "Liurnia",
                "type": "random",
            },
            {
                "id": "link3",
                "source": "Limgrave",
                "target": "Weeping Peninsula",
                "type": "random",
            },
        ]

    @pytest.fixture
    def sample_discovered_links(self):
        """Sample discovered_zone_links - only Limgrave->Stormveil discovered."""
        return [{"zone_link_id": "link1"}]

    @pytest.mark.asyncio
    async def test_zone_query_no_map_id(self, mock_client):
        """Should return null zone when map_id is missing."""
        await mock_client._handle_zone_query({"pos": {"x": 0, "y": 0, "z": 0}})

        mock_client.send.assert_called_once_with(
            {"type": "zone_query_ack", "zone": None, "exits": []}
        )

    @pytest.mark.asyncio
    async def test_zone_query_game_not_found(self, mock_client):
        """Should return null zone when game is not found."""
        mock_game = None

        with patch("fogvizu.websocket.mod.async_session") as mock_session:
            mock_db = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_game
            mock_db.execute.return_value = mock_result
            mock_session.return_value.__aenter__.return_value = mock_db

            await mock_client._handle_zone_query(
                {
                    "map_id": "m60_41_36_00",
                    "pos": {"x": 100, "y": 50, "z": 200},
                }
            )

        mock_client.send.assert_called_once_with(
            {"type": "zone_query_ack", "zone": None, "exits": []}
        )

    @pytest.mark.asyncio
    async def test_zone_query_prefers_discovered_zone(
        self, mock_client, sample_zone_links, sample_discovered_links
    ):
        """Should prefer discovered zone when multiple candidates exist."""
        mock_game = MagicMock()
        mock_game.zone_links = sample_zone_links
        mock_game.discovered_zone_links = sample_discovered_links

        # Mock resolver to return multiple candidates
        mock_resolver = MagicMock()
        mock_resolver.resolve_by_col.return_value = (None, None)
        mock_resolver.resolve_all_candidates.return_value = [
            ("weeping_peninsula", "Weeping Peninsula"),  # Not discovered
            ("limgrave", "Limgrave"),  # Discovered (via link1)
            ("stormveil", "Stormveil Castle"),  # Discovered (via link1)
        ]

        with (
            patch("fogvizu.websocket.mod.async_session") as mock_session,
            patch("fogvizu.websocket.mod.get_resolver", return_value=mock_resolver),
            patch("fogvizu.websocket.mod.compute_zone_exits", return_value=[]),
        ):
            mock_db = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_game
            mock_db.execute.return_value = mock_result
            mock_session.return_value.__aenter__.return_value = mock_db

            await mock_client._handle_zone_query(
                {
                    "map_id": "m60_41_36_00",
                    "pos": {"x": 100, "y": 50, "z": 200},
                }
            )

        # Should pick Limgrave (first discovered candidate), not Weeping Peninsula
        mock_client.send.assert_called_once()
        call_args = mock_client.send.call_args[0][0]
        assert call_args["type"] == "zone_query_ack"
        assert call_args["zone"] == "Limgrave"

    @pytest.mark.asyncio
    async def test_zone_query_fallback_to_first_when_none_discovered(
        self, mock_client, sample_zone_links
    ):
        """Should fallback to first candidate when no candidates are discovered."""
        mock_game = MagicMock()
        mock_game.zone_links = sample_zone_links
        mock_game.discovered_zone_links = []  # Nothing discovered

        mock_resolver = MagicMock()
        mock_resolver.resolve_by_col.return_value = (None, None)
        mock_resolver.resolve_all_candidates.return_value = [
            ("weeping_peninsula", "Weeping Peninsula"),
            ("limgrave", "Limgrave"),
        ]

        with (
            patch("fogvizu.websocket.mod.async_session") as mock_session,
            patch("fogvizu.websocket.mod.get_resolver", return_value=mock_resolver),
            patch("fogvizu.websocket.mod.compute_zone_exits", return_value=[]),
        ):
            mock_db = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_game
            mock_db.execute.return_value = mock_result
            mock_session.return_value.__aenter__.return_value = mock_db

            await mock_client._handle_zone_query(
                {
                    "map_id": "m60_41_36_00",
                    "pos": {"x": 100, "y": 50, "z": 200},
                }
            )

        # Should pick first candidate since none are discovered
        call_args = mock_client.send.call_args[0][0]
        assert call_args["zone"] == "Weeping Peninsula"

    @pytest.mark.asyncio
    async def test_zone_query_col_resolution_skipped_if_not_discovered(
        self, mock_client, sample_zone_links, sample_discovered_links
    ):
        """Should skip Col resolution if resolved zone is not discovered."""
        mock_game = MagicMock()
        mock_game.zone_links = sample_zone_links
        mock_game.discovered_zone_links = sample_discovered_links

        mock_resolver = MagicMock()
        # Col resolves to undiscovered zone
        mock_resolver.resolve_by_col.return_value = ("weeping", "Weeping Peninsula")
        # Position resolves to discovered zone
        mock_resolver.resolve_all_candidates.return_value = [
            ("limgrave", "Limgrave"),  # Discovered
        ]

        with (
            patch("fogvizu.websocket.mod.async_session") as mock_session,
            patch("fogvizu.websocket.mod.get_resolver", return_value=mock_resolver),
            patch("fogvizu.websocket.mod.compute_zone_exits", return_value=[]),
        ):
            mock_db = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_game
            mock_db.execute.return_value = mock_result
            mock_session.return_value.__aenter__.return_value = mock_db

            await mock_client._handle_zone_query(
                {
                    "map_id": "m60_41_36_00",
                    "pos": {"x": 100, "y": 50, "z": 200},
                    "play_region_id": 0x100000,
                }
            )

        # Should pick Limgrave from position (Col was skipped because not discovered)
        call_args = mock_client.send.call_args[0][0]
        assert call_args["zone"] == "Limgrave"
        # Verify resolve_all_candidates was called (fallback to position)
        mock_resolver.resolve_all_candidates.assert_called_once()

    @pytest.mark.asyncio
    async def test_zone_query_col_resolution_used_if_discovered(
        self, mock_client, sample_zone_links, sample_discovered_links
    ):
        """Should use Col resolution if resolved zone is discovered."""
        mock_game = MagicMock()
        mock_game.zone_links = sample_zone_links
        mock_game.discovered_zone_links = sample_discovered_links

        mock_resolver = MagicMock()
        # Col resolves to discovered zone
        mock_resolver.resolve_by_col.return_value = ("stormveil", "Stormveil Castle")

        with (
            patch("fogvizu.websocket.mod.async_session") as mock_session,
            patch("fogvizu.websocket.mod.get_resolver", return_value=mock_resolver),
            patch("fogvizu.websocket.mod.compute_zone_exits", return_value=[]),
        ):
            mock_db = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_game
            mock_db.execute.return_value = mock_result
            mock_session.return_value.__aenter__.return_value = mock_db

            await mock_client._handle_zone_query(
                {
                    "map_id": "m10_00_00_00",
                    "pos": {"x": 100, "y": 50, "z": 200},
                    "play_region_id": 0x100000,
                }
            )

        # Should use Stormveil Castle from Col resolution
        call_args = mock_client.send.call_args[0][0]
        assert call_args["zone"] == "Stormveil Castle"
        # Verify resolve_all_candidates was NOT called (Col was sufficient)
        mock_resolver.resolve_all_candidates.assert_not_called()

    @pytest.mark.asyncio
    async def test_zone_query_returns_exits(
        self, mock_client, sample_zone_links, sample_discovered_links
    ):
        """Should return exits for the resolved zone."""
        mock_game = MagicMock()
        mock_game.zone_links = sample_zone_links
        mock_game.discovered_zone_links = sample_discovered_links

        mock_resolver = MagicMock()
        mock_resolver.resolve_by_col.return_value = ("limgrave", "Limgrave")

        expected_exits = [
            {"id": "link1", "target": "Stormveil Castle", "description": "north"},
            {"id": "link3", "target": "???", "description": "south"},
        ]

        with (
            patch("fogvizu.websocket.mod.async_session") as mock_session,
            patch("fogvizu.websocket.mod.get_resolver", return_value=mock_resolver),
            patch("fogvizu.websocket.mod.compute_zone_exits", return_value=expected_exits),
        ):
            mock_db = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_game
            mock_db.execute.return_value = mock_result
            mock_session.return_value.__aenter__.return_value = mock_db

            await mock_client._handle_zone_query(
                {
                    "map_id": "m60_41_36_00",
                    "pos": {"x": 100, "y": 50, "z": 200},
                    "play_region_id": 0x100000,
                }
            )

        call_args = mock_client.send.call_args[0][0]
        assert call_args["exits"] == expected_exits

    @pytest.mark.asyncio
    async def test_zone_query_no_candidates(self, mock_client, sample_zone_links):
        """Should return null zone when no candidates found."""
        mock_game = MagicMock()
        mock_game.zone_links = sample_zone_links
        mock_game.discovered_zone_links = []

        mock_resolver = MagicMock()
        mock_resolver.resolve_by_col.return_value = (None, None)
        mock_resolver.resolve_all_candidates.return_value = []

        with patch("fogvizu.websocket.mod.async_session") as mock_session:
            mock_db = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_game
            mock_db.execute.return_value = mock_result
            mock_session.return_value.__aenter__.return_value = mock_db

            with patch("fogvizu.websocket.mod.get_resolver", return_value=mock_resolver):
                await mock_client._handle_zone_query(
                    {
                        "map_id": "m99_99_99_99",
                        "pos": {"x": 100, "y": 50, "z": 200},
                    }
                )

        mock_client.send.assert_called_once_with(
            {"type": "zone_query_ack", "zone": None, "exits": []}
        )
