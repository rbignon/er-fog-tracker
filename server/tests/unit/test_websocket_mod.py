"""Unit tests for mod WebSocket handler.

Tests the zone_query handler logic for resolving zones after fast travel,
and the discovery_v2 handler for fog gate traversals.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from fogtracker.game_logic import DiscoveredLink, DiscoveryResult
from fogtracker.websocket.mod import ModClient

# =============================================================================
# Shared Fixtures
# =============================================================================


@pytest.fixture
def mock_client():
    """Create a ModClient with mocked WebSocket and game_id."""
    ws = AsyncMock()
    game_id = uuid4()
    user = MagicMock()
    user.id = 1
    client = ModClient(ws, game_id, user)
    client.send = AsyncMock()
    return client


@pytest.fixture
def sample_zone_links():
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
def sample_discovered_links():
    """Sample discovered_zone_links - only Limgrave->Stormveil discovered."""
    return [{"zone_link_id": "link1"}]


@pytest.fixture
def mock_manager():
    """Create a mock manager with async broadcast_to_all."""
    manager = MagicMock()
    manager.broadcast_to_all = AsyncMock()
    return manager


# =============================================================================
# TestZoneQueryHandler
# =============================================================================


class TestZoneQueryHandler:
    """Tests for _handle_zone_query method."""

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

        with patch("fogtracker.websocket.mod.async_session") as mock_session:
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
    async def test_zone_query_returns_single_discovered_candidate(
        self, mock_client, sample_zone_links, sample_discovered_links
    ):
        """Should return zone when exactly one discovered candidate exists."""
        mock_game = MagicMock()
        mock_game.zone_links = sample_zone_links
        mock_game.discovered_zone_links = sample_discovered_links

        # Mock resolver to return multiple candidates, but only one is discovered
        mock_resolver = MagicMock()
        mock_resolver.resolve_by_col.return_value = (None, None)
        mock_resolver.resolve_all_candidates.return_value = [
            ("weeping_peninsula", "Weeping Peninsula"),  # Not discovered
            ("limgrave", "Limgrave"),  # Discovered (via link1)
            ("unknown", "Unknown Zone"),  # Not discovered
        ]

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch("fogtracker.websocket.mod.compute_zone_exits", return_value=[]),
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

        # Should return Limgrave (the only discovered candidate)
        mock_client.send.assert_called_once()
        call_args = mock_client.send.call_args[0][0]
        assert call_args["type"] == "zone_query_ack"
        assert call_args["zone"] == "Limgrave"

    @pytest.mark.asyncio
    async def test_zone_query_returns_null_when_multiple_discovered(
        self, mock_client, sample_zone_links, sample_discovered_links
    ):
        """Should return null when multiple discovered candidates exist (ambiguous)."""
        mock_game = MagicMock()
        mock_game.zone_links = sample_zone_links
        mock_game.discovered_zone_links = sample_discovered_links

        # Mock resolver to return candidates where 2 are discovered
        mock_resolver = MagicMock()
        mock_resolver.resolve_by_col.return_value = (None, None)
        mock_resolver.resolve_all_candidates.return_value = [
            ("weeping_peninsula", "Weeping Peninsula"),  # Not discovered
            ("limgrave", "Limgrave"),  # Discovered (via link1)
            ("stormveil", "Stormveil Castle"),  # Discovered (via link1)
        ]

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch("fogtracker.websocket.mod.compute_zone_exits", return_value=[]),
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

        # Should return null (ambiguous - multiple discovered candidates)
        call_args = mock_client.send.call_args[0][0]
        assert call_args["zone"] is None

    @pytest.mark.asyncio
    async def test_zone_query_returns_null_when_none_discovered(
        self, mock_client, sample_zone_links
    ):
        """Should return null when no candidates are discovered."""
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
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch("fogtracker.websocket.mod.compute_zone_exits", return_value=[]),
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

        # Should return null (no discovered candidates)
        call_args = mock_client.send.call_args[0][0]
        assert call_args["zone"] is None

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
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch("fogtracker.websocket.mod.compute_zone_exits", return_value=[]),
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
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch("fogtracker.websocket.mod.compute_zone_exits", return_value=[]),
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
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch("fogtracker.websocket.mod.compute_zone_exits", return_value=expected_exits),
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

        with patch("fogtracker.websocket.mod.async_session") as mock_session:
            mock_db = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_game
            mock_db.execute.return_value = mock_result
            mock_session.return_value.__aenter__.return_value = mock_db

            with patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver):
                await mock_client._handle_zone_query(
                    {
                        "map_id": "m99_99_99_99",
                        "pos": {"x": 100, "y": 50, "z": 200},
                    }
                )

        mock_client.send.assert_called_once_with(
            {"type": "zone_query_ack", "zone": None, "exits": []}
        )


# =============================================================================
# TestDiscoveryV2Handler
# =============================================================================


class TestDiscoveryV2Handler:
    """Tests for _handle_discovery_v2 method."""

    @pytest.fixture
    def zone_links_with_keys(self):
        """Zone links with source_key/target_key (V3 format)."""
        return [
            {
                "id": "link1",
                "source": "Limgrave",
                "target": "Stormveil Castle",
                "source_key": "limgrave",
                "target_key": "stormveil",
                "type": "random",
            },
            {
                "id": "link2",
                "source": "Stormveil Castle",
                "target": "Liurnia",
                "source_key": "stormveil",
                "target_key": "liurnia",
                "type": "random",
            },
            {
                "id": "link3",
                "source": "Chapel of Anticipation",
                "target": "Limgrave",
                "source_key": "chapel",
                "target_key": "limgrave",
                "type": "preexisting",
            },
        ]

    def _make_mock_game(self, zone_links, discovered_links=None, entity_mapping=None):
        """Helper to create a mock game object."""
        game = MagicMock()
        game.zone_links = zone_links
        game.discovered_zone_links = discovered_links or []
        game.entity_mapping = entity_mapping
        return game

    def _setup_db_mock(self, mock_session, game):
        """Helper to setup database mock.

        Sets up the async session mock with proper sync/async handling:
        - execute, commit: async methods
        - expire_all: sync method (not awaited in source)
        """
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = game
        # execute returns awaitable that resolves to mock_result
        mock_db.execute = AsyncMock(return_value=mock_result)
        # commit is async
        mock_db.commit = AsyncMock()
        # expire_all is sync (not awaited)
        mock_db.expire_all = MagicMock()
        mock_session.return_value.__aenter__.return_value = mock_db
        return mock_db

    # -------------------------------------------------------------------------
    # Input validation tests
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_discovery_v2_missing_source_map_id(self, mock_client):
        """Should return error when source_map_id is missing."""
        await mock_client._handle_discovery_v2(
            {
                "target_map_id": "m60_41_36_00",
                "source_pos": {"x": 0, "y": 0, "z": 0},
                "target_pos": {"x": 100, "y": 50, "z": 200},
            }
        )

        mock_client.send.assert_called_once()
        call_args = mock_client.send.call_args[0][0]
        assert call_args["type"] == "error"
        assert "source_map_id" in call_args["message"]

    @pytest.mark.asyncio
    async def test_discovery_v2_missing_target_map_id(self, mock_client):
        """Should return error when target_map_id is missing."""
        await mock_client._handle_discovery_v2(
            {
                "source_map_id": "m60_41_36_00",
                "source_pos": {"x": 0, "y": 0, "z": 0},
                "target_pos": {"x": 100, "y": 50, "z": 200},
            }
        )

        mock_client.send.assert_called_once()
        call_args = mock_client.send.call_args[0][0]
        assert call_args["type"] == "error"
        assert "target_map_id" in call_args["message"]

    # -------------------------------------------------------------------------
    # No candidates tests
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_discovery_v2_no_source_candidates(self, mock_client, sample_zone_links):
        """Should return error when no source zone candidates found."""
        mock_game = self._make_mock_game(sample_zone_links)
        mock_resolver = MagicMock()
        mock_resolver.resolve_by_col.return_value = (None, None)
        mock_resolver.resolve_all_candidates.side_effect = [
            [],  # No source candidates
            [("stormveil", "Stormveil Castle")],  # Target candidates
        ]

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
        ):
            self._setup_db_mock(mock_session, mock_game)

            await mock_client._handle_discovery_v2(
                {
                    "source_map_id": "m99_99_99_99",
                    "target_map_id": "m10_00_00_00",
                    "source_pos": {"x": 0, "y": 0, "z": 0},
                    "target_pos": {"x": 100, "y": 50, "z": 200},
                }
            )

        call_args = mock_client.send.call_args[0][0]
        assert call_args["type"] == "discovery_v2_ack"
        assert call_args["error"] == "No zone candidates found"
        assert call_args["propagated"] == []

    @pytest.mark.asyncio
    async def test_discovery_v2_no_target_candidates(self, mock_client, sample_zone_links):
        """Should return error when no target zone candidates found."""
        mock_game = self._make_mock_game(sample_zone_links)
        mock_resolver = MagicMock()
        mock_resolver.resolve_by_col.return_value = (None, None)
        mock_resolver.resolve_all_candidates.side_effect = [
            [("limgrave", "Limgrave")],  # Source candidates
            [],  # No target candidates
        ]

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
        ):
            self._setup_db_mock(mock_session, mock_game)

            await mock_client._handle_discovery_v2(
                {
                    "source_map_id": "m60_41_36_00",
                    "target_map_id": "m99_99_99_99",
                    "source_pos": {"x": 0, "y": 0, "z": 0},
                    "target_pos": {"x": 100, "y": 50, "z": 200},
                }
            )

        call_args = mock_client.send.call_args[0][0]
        assert call_args["type"] == "discovery_v2_ack"
        assert call_args["error"] == "No zone candidates found"

    # -------------------------------------------------------------------------
    # Col resolution tests
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_discovery_v2_col_resolution_prioritized(
        self, mock_client, sample_zone_links, mock_manager
    ):
        """Should prioritize Col resolution over position candidates."""
        mock_game = self._make_mock_game(sample_zone_links)
        mock_resolver = MagicMock()
        # Col resolves to specific zones
        mock_resolver.resolve_by_col.side_effect = [
            ("limgrave", "Limgrave"),  # Source by Col
            ("stormveil", "Stormveil Castle"),  # Target by Col
        ]
        # Position would give different candidates
        mock_resolver.resolve_all_candidates.side_effect = [
            [("weeping", "Weeping Peninsula"), ("limgrave", "Limgrave")],
            [("liurnia", "Liurnia"), ("stormveil", "Stormveil Castle")],
        ]

        discovery_result = DiscoveryResult(origin="Limgrave")
        discovery_result.main_links = [DiscoveredLink("Limgrave", "Stormveil Castle", "random")]

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch(
                "fogtracker.websocket.mod.find_all_matching_zone_pairs",
                return_value=[("Limgrave", "Stormveil Castle", {"id": "link1"})],
            ) as mock_find,
            patch("fogtracker.websocket.mod.compute_backprop_cost", return_value=0),
            patch(
                "fogtracker.websocket.mod.propagate_discovery",
                return_value=discovery_result,
            ),
            patch("fogtracker.websocket.mod.compute_zone_exits", return_value=[]),
            patch(
                "fogtracker.websocket.mod.compute_discovery_stats",
                return_value={"discovered": 1, "total": 3, "percent": 33},
            ),
            patch("fogtracker.websocket.mod.expand_discovered_links", return_value=[]),
            patch("fogtracker.websocket.mod.manager", mock_manager),
        ):
            self._setup_db_mock(mock_session, mock_game)

            await mock_client._handle_discovery_v2(
                {
                    "source_map_id": "m60_41_36_00",
                    "target_map_id": "m10_00_00_00",
                    "source_pos": {"x": 0, "y": 0, "z": 0},
                    "target_pos": {"x": 100, "y": 50, "z": 200},
                    "source_play_region_id": 0x100000,
                    "target_play_region_id": 0x200000,
                }
            )

        # Col-resolved zones should be first in candidates passed to find_all_matching_zone_pairs
        call_args = mock_find.call_args[0]
        source_candidates = call_args[1]
        target_candidates = call_args[2]
        # Col-resolved should be at index 0
        assert source_candidates[0] == ("limgrave", "Limgrave")
        assert target_candidates[0] == ("stormveil", "Stormveil Castle")

    # -------------------------------------------------------------------------
    # Entity mapping tests
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_discovery_v2_entity_mapping_prioritizes_candidates(
        self, mock_client, sample_zone_links, mock_manager
    ):
        """Should use entity_mapping to prioritize zone candidates."""
        entity_mapping = {
            "755890001": {
                "source_map": "m60_41_36_00",
                "dest_map": "m10_00_00_00",
            }
        }
        mock_game = self._make_mock_game(sample_zone_links, entity_mapping=entity_mapping)

        mock_resolver = MagicMock()
        mock_resolver.resolve_by_col.return_value = (None, None)
        # Position candidates
        mock_resolver.resolve_all_candidates.side_effect = [
            [("weeping", "Weeping Peninsula")],  # Source
            [("liurnia", "Liurnia")],  # Target
        ]
        # EMEVD map resolution adds more candidates
        mock_resolver.resolve_from_map_id.side_effect = [
            [("limgrave", "Limgrave")],  # From source EMEVD map
            [("stormveil", "Stormveil Castle")],  # From dest EMEVD map
        ]

        discovery_result = DiscoveryResult(origin="Limgrave")
        discovery_result.main_links = [DiscoveredLink("Limgrave", "Stormveil Castle", "random")]

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch(
                "fogtracker.websocket.mod.find_all_matching_zone_pairs",
                return_value=[("Limgrave", "Stormveil Castle", {"id": "link1"})],
            ) as mock_find,
            patch("fogtracker.websocket.mod.compute_backprop_cost", return_value=0),
            patch(
                "fogtracker.websocket.mod.propagate_discovery",
                return_value=discovery_result,
            ),
            patch("fogtracker.websocket.mod.compute_zone_exits", return_value=[]),
            patch(
                "fogtracker.websocket.mod.compute_discovery_stats",
                return_value={"discovered": 1, "total": 3, "percent": 33},
            ),
            patch("fogtracker.websocket.mod.expand_discovered_links", return_value=[]),
            patch("fogtracker.websocket.mod.manager", mock_manager),
        ):
            self._setup_db_mock(mock_session, mock_game)

            await mock_client._handle_discovery_v2(
                {
                    "source_map_id": "m60_41_36_00",
                    "target_map_id": "m10_00_00_00",
                    "source_pos": {"x": 0, "y": 0, "z": 0},
                    "target_pos": {"x": 100, "y": 50, "z": 200},
                    "destination_entity_id": 755890001,
                }
            )

        # EMEVD-resolved zones should be prioritized
        call_args = mock_find.call_args[0]
        source_candidates = call_args[1]
        target_candidates = call_args[2]
        # EMEVD candidates should be first (prioritized)
        assert ("limgrave", "Limgrave") in source_candidates
        assert ("stormveil", "Stormveil Castle") in target_candidates

    # -------------------------------------------------------------------------
    # Zone key matching tests
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_discovery_v2_uses_zone_keys_when_available(
        self, mock_client, zone_links_with_keys, mock_manager
    ):
        """Should use key-based matching when zone_links have zone_keys."""
        mock_game = self._make_mock_game(zone_links_with_keys)

        mock_resolver = MagicMock()
        mock_resolver.resolve_by_col.return_value = (None, None)
        mock_resolver.resolve_all_candidates.side_effect = [
            [("limgrave", "Limgrave")],
            [("stormveil", "Stormveil Castle")],
        ]

        discovery_result = DiscoveryResult(origin="Limgrave")
        discovery_result.main_links = [DiscoveredLink("Limgrave", "Stormveil Castle", "random")]

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch(
                "fogtracker.websocket.mod.find_all_matching_zone_pairs_by_keys",
                return_value=[("Limgrave", "Stormveil Castle", {"id": "link1"})],
            ) as mock_find_by_keys,
            patch("fogtracker.websocket.mod.find_all_matching_zone_pairs") as mock_find_by_name,
            patch("fogtracker.websocket.mod.compute_backprop_cost", return_value=0),
            patch(
                "fogtracker.websocket.mod.propagate_discovery",
                return_value=discovery_result,
            ),
            patch("fogtracker.websocket.mod.compute_zone_exits", return_value=[]),
            patch(
                "fogtracker.websocket.mod.compute_discovery_stats",
                return_value={"discovered": 1, "total": 3, "percent": 33},
            ),
            patch("fogtracker.websocket.mod.expand_discovered_links", return_value=[]),
            patch("fogtracker.websocket.mod.manager", mock_manager),
        ):
            self._setup_db_mock(mock_session, mock_game)

            await mock_client._handle_discovery_v2(
                {
                    "source_map_id": "m60_41_36_00",
                    "target_map_id": "m10_00_00_00",
                    "source_pos": {"x": 0, "y": 0, "z": 0},
                    "target_pos": {"x": 100, "y": 50, "z": 200},
                }
            )

        # Key-based matching should be used
        mock_find_by_keys.assert_called_once()
        # Display name matching should NOT be called
        mock_find_by_name.assert_not_called()

    @pytest.mark.asyncio
    async def test_discovery_v2_fallback_to_display_name_when_no_keys(
        self, mock_client, sample_zone_links, mock_manager
    ):
        """Should use display name matching when zone_links lack zone_keys."""
        mock_game = self._make_mock_game(sample_zone_links)  # No zone_keys

        mock_resolver = MagicMock()
        mock_resolver.resolve_by_col.return_value = (None, None)
        mock_resolver.resolve_all_candidates.side_effect = [
            [("limgrave", "Limgrave")],
            [("stormveil", "Stormveil Castle")],
        ]

        discovery_result = DiscoveryResult(origin="Limgrave")
        discovery_result.main_links = [DiscoveredLink("Limgrave", "Stormveil Castle", "random")]

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch(
                "fogtracker.websocket.mod.find_all_matching_zone_pairs",
                return_value=[("Limgrave", "Stormveil Castle", {"id": "link1"})],
            ) as mock_find_by_name,
            patch("fogtracker.websocket.mod.compute_backprop_cost", return_value=0),
            patch(
                "fogtracker.websocket.mod.propagate_discovery",
                return_value=discovery_result,
            ),
            patch("fogtracker.websocket.mod.compute_zone_exits", return_value=[]),
            patch(
                "fogtracker.websocket.mod.compute_discovery_stats",
                return_value={"discovered": 1, "total": 3, "percent": 33},
            ),
            patch("fogtracker.websocket.mod.expand_discovered_links", return_value=[]),
            patch("fogtracker.websocket.mod.manager", mock_manager),
        ):
            self._setup_db_mock(mock_session, mock_game)

            await mock_client._handle_discovery_v2(
                {
                    "source_map_id": "m60_41_36_00",
                    "target_map_id": "m10_00_00_00",
                    "source_pos": {"x": 0, "y": 0, "z": 0},
                    "target_pos": {"x": 100, "y": 50, "z": 200},
                }
            )

        # Display name matching should be used
        mock_find_by_name.assert_called_once()

    @pytest.mark.asyncio
    async def test_discovery_v2_fallback_when_key_matching_fails(
        self, mock_client, zone_links_with_keys, mock_manager
    ):
        """Should fallback to display name when key-based matching finds nothing."""
        mock_game = self._make_mock_game(zone_links_with_keys)

        mock_resolver = MagicMock()
        mock_resolver.resolve_by_col.return_value = (None, None)
        mock_resolver.resolve_all_candidates.side_effect = [
            [("limgrave", "Limgrave")],
            [("stormveil", "Stormveil Castle")],
        ]

        discovery_result = DiscoveryResult(origin="Limgrave")
        discovery_result.main_links = [DiscoveredLink("Limgrave", "Stormveil Castle", "random")]

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch(
                "fogtracker.websocket.mod.find_all_matching_zone_pairs_by_keys",
                return_value=[],  # No key match
            ),
            patch(
                "fogtracker.websocket.mod.find_all_matching_zone_pairs",
                return_value=[("Limgrave", "Stormveil Castle", {"id": "link1"})],
            ) as mock_find_by_name,
            patch("fogtracker.websocket.mod.compute_backprop_cost", return_value=0),
            patch(
                "fogtracker.websocket.mod.propagate_discovery",
                return_value=discovery_result,
            ),
            patch("fogtracker.websocket.mod.compute_zone_exits", return_value=[]),
            patch(
                "fogtracker.websocket.mod.compute_discovery_stats",
                return_value={"discovered": 1, "total": 3, "percent": 33},
            ),
            patch("fogtracker.websocket.mod.expand_discovered_links", return_value=[]),
            patch("fogtracker.websocket.mod.manager", mock_manager),
        ):
            self._setup_db_mock(mock_session, mock_game)

            await mock_client._handle_discovery_v2(
                {
                    "source_map_id": "m60_41_36_00",
                    "target_map_id": "m10_00_00_00",
                    "source_pos": {"x": 0, "y": 0, "z": 0},
                    "target_pos": {"x": 100, "y": 50, "z": 200},
                }
            )

        # Should fallback to display name matching
        mock_find_by_name.assert_called_once()

    # -------------------------------------------------------------------------
    # Backprop cost tests
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_discovery_v2_selects_lowest_backprop_cost(
        self, mock_client, sample_zone_links, mock_manager
    ):
        """Should select match with lowest back-propagation cost."""
        mock_game = self._make_mock_game(sample_zone_links)

        mock_resolver = MagicMock()
        mock_resolver.resolve_by_col.return_value = (None, None)
        mock_resolver.resolve_all_candidates.side_effect = [
            [("limgrave", "Limgrave"), ("weeping", "Weeping Peninsula")],
            [("stormveil", "Stormveil Castle"), ("liurnia", "Liurnia")],
        ]

        # Multiple matches with different costs
        all_matches = [
            ("Weeping Peninsula", "Liurnia", {"id": "linkX"}),  # Cost 5
            ("Limgrave", "Stormveil Castle", {"id": "link1"}),  # Cost 1 (lowest)
        ]

        discovery_result = DiscoveryResult(origin="Limgrave")
        discovery_result.main_links = [DiscoveredLink("Limgrave", "Stormveil Castle", "random")]

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch(
                "fogtracker.websocket.mod.find_all_matching_zone_pairs",
                return_value=all_matches,
            ),
            patch(
                "fogtracker.websocket.mod.compute_backprop_cost",
                side_effect=[5, 1],  # First match cost 5, second cost 1
            ),
            patch(
                "fogtracker.websocket.mod.propagate_discovery",
                return_value=discovery_result,
            ) as mock_propagate,
            patch("fogtracker.websocket.mod.compute_zone_exits", return_value=[]),
            patch(
                "fogtracker.websocket.mod.compute_discovery_stats",
                return_value={"discovered": 1, "total": 3, "percent": 33},
            ),
            patch("fogtracker.websocket.mod.expand_discovered_links", return_value=[]),
            patch("fogtracker.websocket.mod.manager", mock_manager),
        ):
            self._setup_db_mock(mock_session, mock_game)

            await mock_client._handle_discovery_v2(
                {
                    "source_map_id": "m60_41_36_00",
                    "target_map_id": "m10_00_00_00",
                    "source_pos": {"x": 0, "y": 0, "z": 0},
                    "target_pos": {"x": 100, "y": 50, "z": 200},
                }
            )

        # Should only propagate the lowest cost match (Limgrave -> Stormveil)
        assert mock_propagate.call_count == 1
        call_args = mock_propagate.call_args
        # propagate_discovery(db, game_id, source, target, discovered_by=...)
        # Positional args are at index 0, kwargs at index 1
        assert call_args[0][2] == "Limgrave"  # source (3rd positional arg)
        assert call_args[0][3] == "Stormveil Castle"  # target (4th positional arg)

    @pytest.mark.asyncio
    async def test_discovery_v2_uses_priority_tiebreaker(
        self, mock_client, sample_zone_links, mock_manager
    ):
        """When multiple matches have same cost, should use candidate priority as tiebreaker.

        Priority is based on candidate ordering (position proximity). The match
        with lowest priority sum (source_priority + target_priority) wins.
        """
        mock_game = self._make_mock_game(sample_zone_links)

        mock_resolver = MagicMock()
        mock_resolver.resolve_by_col.return_value = (None, None)
        # Candidates ordered by position proximity
        mock_resolver.resolve_all_candidates.side_effect = [
            [("limgrave", "Limgrave"), ("weeping", "Weeping Peninsula")],
            [("stormveil", "Stormveil Castle"), ("liurnia", "Liurnia")],
        ]

        # Multiple matches with same cost but different priorities
        # Limgrave->Stormveil: priority = 0+0 = 0 (best)
        # Weeping->Liurnia: priority = 1+1 = 2 (worse)
        all_matches = [
            ("Limgrave", "Stormveil Castle", {"id": "link1"}),
            ("Weeping Peninsula", "Liurnia", {"id": "linkX"}),
        ]

        discovery_result = DiscoveryResult(origin="Limgrave")
        discovery_result.main_links = [DiscoveredLink("Limgrave", "Stormveil Castle", "random")]

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch(
                "fogtracker.websocket.mod.find_all_matching_zone_pairs",
                return_value=all_matches,
            ),
            patch(
                "fogtracker.websocket.mod.compute_backprop_cost",
                return_value=0,  # Same cost for all
            ),
            patch(
                "fogtracker.websocket.mod.propagate_discovery",
                return_value=discovery_result,
            ) as mock_propagate,
            patch("fogtracker.websocket.mod.compute_zone_exits", return_value=[]),
            patch(
                "fogtracker.websocket.mod.compute_discovery_stats",
                return_value={"discovered": 2, "total": 3, "percent": 66},
            ),
            patch("fogtracker.websocket.mod.expand_discovered_links", return_value=[]),
            patch("fogtracker.websocket.mod.manager", mock_manager),
        ):
            self._setup_db_mock(mock_session, mock_game)

            await mock_client._handle_discovery_v2(
                {
                    "source_map_id": "m60_41_36_00",
                    "target_map_id": "m10_00_00_00",
                    "source_pos": {"x": 0, "y": 0, "z": 0},
                    "target_pos": {"x": 100, "y": 50, "z": 200},
                }
            )

        # Should propagate ONLY the best priority match (Limgrave -> Stormveil)
        assert mock_propagate.call_count == 1
        call_args = mock_propagate.call_args
        # propagate_discovery(db, game_id, source, target, discovered_by=...)
        # Positional args are at index 0, kwargs at index 1
        assert call_args[0][2] == "Limgrave"  # source (3rd positional arg)
        assert call_args[0][3] == "Stormveil Castle"  # target (4th positional arg)

    @pytest.mark.asyncio
    async def test_discovery_v2_destination_zone_from_best_priority_match(
        self, mock_client, sample_zone_links, mock_manager
    ):
        """When multiple matches exist, destination_zone should be from the best priority match.

        With priority filtering, only the match with best candidate priority is tried.
        The destination zone is from that match, regardless of whether it finds new links.

        Given candidates:
        - Source: [Erdtree Sanctuary (0), Behind Erdtree (1)]
        - Target: [Main Entrance (0), Grand Library (1)]

        Matches:
        - Erdtree Sanctuary -> Main Entrance: priority = 0+0 = 0 (best)
        - Behind Erdtree -> Grand Library: priority = 1+1 = 2 (worse)

        Only the best priority match is tried, so destination is Main Entrance.
        """
        mock_game = self._make_mock_game(sample_zone_links)

        mock_resolver = MagicMock()
        mock_resolver.resolve_by_col.return_value = (None, None)
        mock_resolver.resolve_all_candidates.side_effect = [
            [("erdtree_sanctuary", "Erdtree Sanctuary"), ("behind_erdtree", "Behind Erdtree")],
            [("main_entrance", "Main Entrance"), ("grand_library", "Grand Library")],
        ]

        # Multiple matches with same cost but different priorities
        all_matches = [
            ("Erdtree Sanctuary", "Main Entrance", {"id": "link1"}),  # priority = 0
            ("Behind Erdtree", "Grand Library", {"id": "link2"}),  # priority = 2
        ]

        # Discovery result for the best priority match
        discovery_result = DiscoveryResult(origin="Erdtree Sanctuary")
        discovery_result.main_links = [
            DiscoveredLink("Erdtree Sanctuary", "Main Entrance", "random")
        ]

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch(
                "fogtracker.websocket.mod.find_all_matching_zone_pairs",
                return_value=all_matches,
            ),
            patch(
                "fogtracker.websocket.mod.compute_backprop_cost",
                return_value=0,  # Same cost for all
            ),
            patch(
                "fogtracker.websocket.mod.propagate_discovery",
                return_value=discovery_result,
            ) as mock_propagate,
            patch("fogtracker.websocket.mod.compute_zone_exits", return_value=[]),
            patch(
                "fogtracker.websocket.mod.compute_discovery_stats",
                return_value={"discovered": 2, "total": 3, "percent": 66},
            ),
            patch("fogtracker.websocket.mod.expand_discovered_links", return_value=[]),
            patch("fogtracker.websocket.mod.manager", mock_manager),
        ):
            self._setup_db_mock(mock_session, mock_game)

            await mock_client._handle_discovery_v2(
                {
                    "source_map_id": "m11_00_00_00",
                    "target_map_id": "m14_00_00_00",
                    "source_pos": {"x": -109.9, "y": 32.2, "z": -387.6},
                    "target_pos": {"x": 89.7, "y": 154.1, "z": -43.7},
                }
            )

        # Only the best priority match should be propagated
        assert mock_propagate.call_count == 1

        call_args = mock_client.send.call_args[0][0]
        # Destination should be from the best priority match (Main Entrance)
        assert call_args["current_zone"] == "Main Entrance"

    @pytest.mark.asyncio
    async def test_discovery_v2_maliketh_spurious_link_filtered(
        self, mock_client, sample_zone_links, mock_manager
    ):
        """Regression test: Maliketh link should be filtered out when warping to Ashen Leyndell.

        This tests the fix for the bug where warping from Yelough Anix Tunnel to
        Ashen Leyndell would incorrectly discover both:
        - Yelough Anix Tunnel -> Ashen Leyndell (correct)
        - Yelough Anix Tunnel -> Maliketh the Black Blade (spurious)

        The spurious Maliketh link appeared because:
        1. Maliketh's zone (farumazula_maliketh) has a Col in m11_05_00_00
        2. So it was included in target_candidates for Ashen Leyndell map
        3. There exists a zone_link: Yelough Anix Tunnel -> Maliketh
        4. Both matches had backprop cost 0

        With priority filtering, Maliketh should be excluded because:
        - Ashen Leyndell is first in target_candidates (priority 0)
        - Maliketh is later in the list (higher priority number)
        """
        mock_game = self._make_mock_game(sample_zone_links)

        mock_resolver = MagicMock()
        mock_resolver.resolve_by_col.return_value = (None, None)
        # Simulate candidates ordered by position proximity
        # Ashen Leyndell is close to spawn point, Maliketh is far away
        mock_resolver.resolve_all_candidates.side_effect = [
            [("snowfield_tunnel", "Consecrated Snowfield - Yelough Anix Tunnel")],
            [
                ("leyndell2", "Ashen Leyndell"),  # index 0 - close to target pos
                ("farumazula_maliketh", "Maliketh the Black Blade"),  # index 1 - far away
            ],
        ]

        # Both links exist in the spoiler log, both match the candidates
        all_matches = [
            ("Consecrated Snowfield - Yelough Anix Tunnel", "Ashen Leyndell", {"id": "link1"}),
            (
                "Consecrated Snowfield - Yelough Anix Tunnel",
                "Maliketh the Black Blade",
                {"id": "link2"},
            ),
        ]

        discovery_result = DiscoveryResult(origin="Consecrated Snowfield - Yelough Anix Tunnel")
        discovery_result.main_links = [
            DiscoveredLink(
                "Consecrated Snowfield - Yelough Anix Tunnel", "Ashen Leyndell", "random"
            )
        ]

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch(
                "fogtracker.websocket.mod.find_all_matching_zone_pairs",
                return_value=all_matches,
            ),
            patch(
                "fogtracker.websocket.mod.compute_backprop_cost",
                return_value=0,  # Both have same cost
            ),
            patch(
                "fogtracker.websocket.mod.propagate_discovery",
                return_value=discovery_result,
            ) as mock_propagate,
            patch("fogtracker.websocket.mod.compute_zone_exits", return_value=[]),
            patch(
                "fogtracker.websocket.mod.compute_discovery_stats",
                return_value={"discovered": 1, "total": 10, "percent": 10},
            ),
            patch("fogtracker.websocket.mod.expand_discovered_links", return_value=[]),
            patch("fogtracker.websocket.mod.manager", mock_manager),
        ):
            self._setup_db_mock(mock_session, mock_game)

            await mock_client._handle_discovery_v2(
                {
                    "source_map_id": "m32_11_00_00",  # Yelough Anix Tunnel
                    "target_map_id": "m11_05_00_00",  # Ashen Leyndell
                    "source_pos": {"x": 49.6, "y": 1208.0, "z": 68.8},
                    "target_pos": {"x": -5.1, "y": 1.1, "z": 1.4},
                }
            )

        # Should propagate ONLY the Ashen Leyndell link (priority 0+0=0)
        # NOT the Maliketh link (priority 0+1=1)
        assert mock_propagate.call_count == 1
        call_args = mock_propagate.call_args
        assert call_args[0][2] == "Consecrated Snowfield - Yelough Anix Tunnel"
        assert call_args[0][3] == "Ashen Leyndell"  # NOT "Maliketh the Black Blade"

    @pytest.mark.asyncio
    async def test_discovery_v2_same_priority_discovers_all(
        self, mock_client, sample_zone_links, mock_manager
    ):
        """When multiple matches have same cost AND same priority, all should be discovered.

        This ensures we don't over-filter: if two matches genuinely tie on all
        criteria, both should be discovered.
        """
        mock_game = self._make_mock_game(sample_zone_links)

        mock_resolver = MagicMock()
        mock_resolver.resolve_by_col.return_value = (None, None)
        # Both source and target candidates at same position in list
        mock_resolver.resolve_all_candidates.side_effect = [
            [("zone_a", "Zone A"), ("zone_b", "Zone B")],
            [("zone_x", "Zone X"), ("zone_y", "Zone Y")],
        ]

        # Two matches with same priority:
        # Zone A -> Zone X: priority = 0+0 = 0
        # Zone B -> Zone Y: priority = 1+1 = 2
        # But what if both have priority 0?
        # Zone A -> Zone X: priority = 0+0 = 0
        # Zone A -> Zone Y: priority = 0+1 = 1  (different)
        # To test same priority, we need:
        # Zone A -> Zone Y: priority = 0+1 = 1
        # Zone B -> Zone X: priority = 1+0 = 1  (same!)
        all_matches = [
            ("Zone A", "Zone Y", {"id": "link1"}),  # priority = 0+1 = 1
            ("Zone B", "Zone X", {"id": "link2"}),  # priority = 1+0 = 1 (tie!)
        ]

        discovery_result = DiscoveryResult(origin="Zone A")
        discovery_result.main_links = [DiscoveredLink("Zone A", "Zone Y", "random")]

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch(
                "fogtracker.websocket.mod.find_all_matching_zone_pairs",
                return_value=all_matches,
            ),
            patch(
                "fogtracker.websocket.mod.compute_backprop_cost",
                return_value=0,  # Same cost for all
            ),
            patch(
                "fogtracker.websocket.mod.propagate_discovery",
                return_value=discovery_result,
            ) as mock_propagate,
            patch("fogtracker.websocket.mod.compute_zone_exits", return_value=[]),
            patch(
                "fogtracker.websocket.mod.compute_discovery_stats",
                return_value={"discovered": 2, "total": 5, "percent": 40},
            ),
            patch("fogtracker.websocket.mod.expand_discovered_links", return_value=[]),
            patch("fogtracker.websocket.mod.manager", mock_manager),
        ):
            self._setup_db_mock(mock_session, mock_game)

            await mock_client._handle_discovery_v2(
                {
                    "source_map_id": "m60_41_36_00",
                    "target_map_id": "m10_00_00_00",
                    "source_pos": {"x": 0, "y": 0, "z": 0},
                    "target_pos": {"x": 100, "y": 50, "z": 200},
                }
            )

        # Should propagate BOTH matches since they tie on both cost AND priority
        assert mock_propagate.call_count == 2

    @pytest.mark.asyncio
    async def test_discovery_v2_correct_link_always_discovered_when_best_priority(
        self, mock_client, sample_zone_links, mock_manager
    ):
        """Regression test: the correct link should always be discovered when it has best priority.

        This ensures we haven't broken the normal case where:
        1. Multiple matches exist
        2. The correct match has the best priority
        3. Only the correct match is discovered
        """
        mock_game = self._make_mock_game(sample_zone_links)

        mock_resolver = MagicMock()
        mock_resolver.resolve_by_col.return_value = (None, None)
        mock_resolver.resolve_all_candidates.side_effect = [
            [("limgrave", "Limgrave"), ("weeping", "Weeping Peninsula"), ("caelid", "Caelid")],
            [("stormveil", "Stormveil Castle"), ("liurnia", "Liurnia"), ("altus", "Altus Plateau")],
        ]

        # Multiple matches exist, but correct one (Limgrave->Stormveil) has best priority
        all_matches = [
            ("Limgrave", "Stormveil Castle", {"id": "correct"}),  # priority = 0+0 = 0 (best)
            ("Weeping Peninsula", "Liurnia", {"id": "wrong1"}),  # priority = 1+1 = 2
            ("Caelid", "Altus Plateau", {"id": "wrong2"}),  # priority = 2+2 = 4
        ]

        discovery_result = DiscoveryResult(origin="Limgrave")
        discovery_result.main_links = [DiscoveredLink("Limgrave", "Stormveil Castle", "random")]

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch(
                "fogtracker.websocket.mod.find_all_matching_zone_pairs",
                return_value=all_matches,
            ),
            patch(
                "fogtracker.websocket.mod.compute_backprop_cost",
                return_value=0,
            ),
            patch(
                "fogtracker.websocket.mod.propagate_discovery",
                return_value=discovery_result,
            ) as mock_propagate,
            patch("fogtracker.websocket.mod.compute_zone_exits", return_value=[]),
            patch(
                "fogtracker.websocket.mod.compute_discovery_stats",
                return_value={"discovered": 1, "total": 3, "percent": 33},
            ),
            patch("fogtracker.websocket.mod.expand_discovered_links", return_value=[]),
            patch("fogtracker.websocket.mod.manager", mock_manager),
        ):
            self._setup_db_mock(mock_session, mock_game)

            await mock_client._handle_discovery_v2(
                {
                    "source_map_id": "m60_41_36_00",
                    "target_map_id": "m10_00_00_00",
                    "source_pos": {"x": 0, "y": 0, "z": 0},
                    "target_pos": {"x": 100, "y": 50, "z": 200},
                }
            )

        # Should propagate exactly the correct link
        assert mock_propagate.call_count == 1
        call_args = mock_propagate.call_args
        assert call_args[0][2] == "Limgrave"
        assert call_args[0][3] == "Stormveil Castle"

    @pytest.mark.asyncio
    async def test_discovery_v2_ignores_unreachable_matches(
        self, mock_client, sample_zone_links, mock_manager
    ):
        """Should not discover matches unreachable from START (cost = -1)."""
        mock_game = self._make_mock_game(sample_zone_links)

        mock_resolver = MagicMock()
        mock_resolver.resolve_by_col.return_value = (None, None)
        mock_resolver.resolve_all_candidates.side_effect = [
            [("limgrave", "Limgrave")],
            [("stormveil", "Stormveil Castle")],
        ]

        all_matches = [
            ("Limgrave", "Stormveil Castle", {"id": "link1"}),
        ]

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch(
                "fogtracker.websocket.mod.find_all_matching_zone_pairs",
                return_value=all_matches,
            ),
            patch(
                "fogtracker.websocket.mod.compute_backprop_cost",
                return_value=-1,  # Unreachable
            ),
            patch("fogtracker.websocket.mod.propagate_discovery") as mock_propagate,
            patch("fogtracker.websocket.mod.compute_zone_exits", return_value=[]),
            patch(
                "fogtracker.websocket.mod.compute_discovery_stats",
                return_value={"discovered": 0, "total": 3, "percent": 0},
            ),
            patch("fogtracker.websocket.mod.manager", mock_manager),
        ):
            self._setup_db_mock(mock_session, mock_game)

            await mock_client._handle_discovery_v2(
                {
                    "source_map_id": "m60_41_36_00",
                    "target_map_id": "m10_00_00_00",
                    "source_pos": {"x": 0, "y": 0, "z": 0},
                    "target_pos": {"x": 100, "y": 50, "z": 200},
                }
            )

        # Should NOT propagate (unreachable)
        mock_propagate.assert_not_called()

        # Should send ack without error but with empty resolved
        call_args = mock_client.send.call_args[0][0]
        assert call_args["type"] == "discovery_v2_ack"
        assert call_args["resolved"] == []

    # -------------------------------------------------------------------------
    # Broadcast tests
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_discovery_v2_broadcasts_to_host_and_viewers(
        self, mock_client, sample_zone_links, mock_manager
    ):
        """Should broadcast discovery to connected host/viewers."""
        mock_game = self._make_mock_game(
            sample_zone_links, discovered_links=[{"zone_link_id": "link1"}]
        )

        mock_resolver = MagicMock()
        mock_resolver.resolve_by_col.return_value = (None, None)
        mock_resolver.resolve_all_candidates.side_effect = [
            [("limgrave", "Limgrave")],
            [("stormveil", "Stormveil Castle")],
        ]

        discovery_result = DiscoveryResult(origin="Limgrave")
        discovery_result.main_links = [DiscoveredLink("Limgrave", "Stormveil Castle", "random")]

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch(
                "fogtracker.websocket.mod.find_all_matching_zone_pairs",
                return_value=[("Limgrave", "Stormveil Castle", {"id": "link1"})],
            ),
            patch("fogtracker.websocket.mod.compute_backprop_cost", return_value=0),
            patch(
                "fogtracker.websocket.mod.propagate_discovery",
                return_value=discovery_result,
            ),
            patch("fogtracker.websocket.mod.compute_zone_exits", return_value=[]),
            patch(
                "fogtracker.websocket.mod.compute_discovery_stats",
                return_value={"discovered": 1, "total": 3, "percent": 33},
            ),
            patch(
                "fogtracker.websocket.mod.expand_discovered_links",
                return_value=[{"zone_link_id": "link1"}],
            ),
            patch("fogtracker.websocket.mod.manager", mock_manager),
        ):
            self._setup_db_mock(mock_session, mock_game)

            await mock_client._handle_discovery_v2(
                {
                    "source_map_id": "m60_41_36_00",
                    "target_map_id": "m10_00_00_00",
                    "source_pos": {"x": 0, "y": 0, "z": 0},
                    "target_pos": {"x": 100, "y": 50, "z": 200},
                }
            )

        # Should broadcast to all (excluding the mod client)
        mock_manager.broadcast_to_all.assert_called_once()
        broadcast_args = mock_manager.broadcast_to_all.call_args
        assert broadcast_args[0][0] == mock_client.game_id
        broadcast_data = broadcast_args[0][1]
        assert broadcast_data["type"] == "discovery"
        assert "propagated" in broadcast_data
        assert "discovered_zone_links" in broadcast_data
        assert broadcast_args[1]["exclude"] == mock_client.ws

    @pytest.mark.asyncio
    async def test_discovery_v2_no_broadcast_when_nothing_propagated(
        self, mock_client, sample_zone_links, mock_manager
    ):
        """Should not broadcast when nothing was discovered."""
        mock_game = self._make_mock_game(sample_zone_links)

        mock_resolver = MagicMock()
        mock_resolver.resolve_by_col.return_value = (None, None)
        mock_resolver.resolve_all_candidates.side_effect = [
            [("limgrave", "Limgrave")],
            [("stormveil", "Stormveil Castle")],
        ]

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch(
                "fogtracker.websocket.mod.find_all_matching_zone_pairs",
                return_value=[],  # No match found
            ),
            patch("fogtracker.websocket.mod.compute_zone_exits", return_value=[]),
            patch(
                "fogtracker.websocket.mod.compute_discovery_stats",
                return_value={"discovered": 0, "total": 3, "percent": 0},
            ),
            patch("fogtracker.websocket.mod.manager", mock_manager),
        ):
            self._setup_db_mock(mock_session, mock_game)

            await mock_client._handle_discovery_v2(
                {
                    "source_map_id": "m60_41_36_00",
                    "target_map_id": "m10_00_00_00",
                    "source_pos": {"x": 0, "y": 0, "z": 0},
                    "target_pos": {"x": 100, "y": 50, "z": 200},
                }
            )

        # Should NOT broadcast (nothing propagated)
        mock_manager.broadcast_to_all.assert_not_called()

    # -------------------------------------------------------------------------
    # Response format tests
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_discovery_v2_ack_contains_expected_fields(
        self, mock_client, sample_zone_links, mock_manager
    ):
        """Should return ack with all expected fields."""
        mock_game = self._make_mock_game(sample_zone_links)

        mock_resolver = MagicMock()
        mock_resolver.resolve_by_col.return_value = (None, None)
        mock_resolver.resolve_all_candidates.side_effect = [
            [("limgrave", "Limgrave")],
            [("stormveil", "Stormveil Castle")],
        ]

        discovery_result = DiscoveryResult(origin="Limgrave")
        discovery_result.main_links = [DiscoveredLink("Limgrave", "Stormveil Castle", "random")]

        expected_exits = [{"id": "link2", "target": "Liurnia", "description": "north"}]
        expected_stats = {"discovered": 1, "total": 3, "percent": 33}

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch(
                "fogtracker.websocket.mod.find_all_matching_zone_pairs",
                return_value=[("Limgrave", "Stormveil Castle", {"id": "link1"})],
            ),
            patch("fogtracker.websocket.mod.compute_backprop_cost", return_value=0),
            patch(
                "fogtracker.websocket.mod.propagate_discovery",
                return_value=discovery_result,
            ),
            patch("fogtracker.websocket.mod.compute_zone_exits", return_value=expected_exits),
            patch(
                "fogtracker.websocket.mod.compute_discovery_stats",
                return_value=expected_stats,
            ),
            patch("fogtracker.websocket.mod.expand_discovered_links", return_value=[]),
            patch("fogtracker.websocket.mod.manager", mock_manager),
        ):
            self._setup_db_mock(mock_session, mock_game)

            await mock_client._handle_discovery_v2(
                {
                    "source_map_id": "m60_41_36_00",
                    "target_map_id": "m10_00_00_00",
                    "source_pos": {"x": 0, "y": 0, "z": 0},
                    "target_pos": {"x": 100, "y": 50, "z": 200},
                }
            )

        call_args = mock_client.send.call_args[0][0]
        assert call_args["type"] == "discovery_v2_ack"
        assert "propagated" in call_args
        assert "resolved" in call_args
        assert call_args["current_zone"] == "Stormveil Castle"
        assert call_args["exits"] == expected_exits
        assert call_args["stats"] == expected_stats
        # No error when match found
        assert "error" not in call_args

    @pytest.mark.asyncio
    async def test_discovery_v2_ack_includes_error_when_no_match(
        self, mock_client, sample_zone_links, mock_manager
    ):
        """Should include error field when no match found in spoiler log."""
        mock_game = self._make_mock_game(sample_zone_links)

        mock_resolver = MagicMock()
        mock_resolver.resolve_by_col.return_value = (None, None)
        mock_resolver.resolve_all_candidates.side_effect = [
            [("unknown_zone", "Unknown Zone")],
            [("another_unknown", "Another Unknown")],
        ]

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch(
                "fogtracker.websocket.mod.find_all_matching_zone_pairs",
                return_value=[],  # No match
            ),
            patch("fogtracker.websocket.mod.compute_zone_exits", return_value=[]),
            patch(
                "fogtracker.websocket.mod.compute_discovery_stats",
                return_value={"discovered": 0, "total": 3, "percent": 0},
            ),
            patch("fogtracker.websocket.mod.manager", mock_manager),
        ):
            self._setup_db_mock(mock_session, mock_game)

            await mock_client._handle_discovery_v2(
                {
                    "source_map_id": "m60_41_36_00",
                    "target_map_id": "m10_00_00_00",
                    "source_pos": {"x": 0, "y": 0, "z": 0},
                    "target_pos": {"x": 100, "y": 50, "z": 200},
                }
            )

        call_args = mock_client.send.call_args[0][0]
        assert call_args["type"] == "discovery_v2_ack"
        assert call_args["error"] == "No matching link found in spoiler log"
        assert call_args["resolved"] == []

    # -------------------------------------------------------------------------
    # Edge case tests
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_discovery_v2_game_has_no_zone_links(self, mock_client, mock_manager):
        """Should handle game without zone_links gracefully."""
        mock_game = self._make_mock_game(zone_links=None)

        mock_resolver = MagicMock()
        mock_resolver.resolve_by_col.return_value = (None, None)
        mock_resolver.resolve_all_candidates.side_effect = [
            [("limgrave", "Limgrave")],
            [("stormveil", "Stormveil Castle")],
        ]

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch("fogtracker.websocket.mod.compute_zone_exits", return_value=[]),
            patch(
                "fogtracker.websocket.mod.compute_discovery_stats",
                return_value={"discovered": 0, "total": 0, "percent": 0},
            ),
            patch("fogtracker.websocket.mod.manager", mock_manager),
        ):
            self._setup_db_mock(mock_session, mock_game)

            await mock_client._handle_discovery_v2(
                {
                    "source_map_id": "m60_41_36_00",
                    "target_map_id": "m10_00_00_00",
                    "source_pos": {"x": 0, "y": 0, "z": 0},
                    "target_pos": {"x": 100, "y": 50, "z": 200},
                }
            )

        # Should complete without error
        call_args = mock_client.send.call_args[0][0]
        assert call_args["type"] == "discovery_v2_ack"
        assert call_args["propagated"] == []

    @pytest.mark.asyncio
    async def test_discovery_v2_game_not_found(self, mock_client, mock_manager):
        """Should handle missing game gracefully."""
        mock_resolver = MagicMock()
        mock_resolver.resolve_by_col.return_value = (None, None)
        mock_resolver.resolve_all_candidates.side_effect = [
            [("limgrave", "Limgrave")],
            [("stormveil", "Stormveil Castle")],
        ]

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch("fogtracker.websocket.mod.compute_zone_exits", return_value=[]),
            patch(
                "fogtracker.websocket.mod.compute_discovery_stats",
                return_value={"discovered": 0, "total": 0, "percent": 0},
            ),
            patch("fogtracker.websocket.mod.manager", mock_manager),
        ):
            self._setup_db_mock(mock_session, None)  # No game

            await mock_client._handle_discovery_v2(
                {
                    "source_map_id": "m60_41_36_00",
                    "target_map_id": "m10_00_00_00",
                    "source_pos": {"x": 0, "y": 0, "z": 0},
                    "target_pos": {"x": 100, "y": 50, "z": 200},
                }
            )

        # Should complete without error (game not found)
        call_args = mock_client.send.call_args[0][0]
        assert call_args["type"] == "discovery_v2_ack"
        assert call_args["propagated"] == []


# =============================================================================
# TestMedalDiscoveryHandler
# =============================================================================


class TestMedalDiscoveryHandler:
    """Tests for _handle_medal_discovery method.

    The Pureblood Knight's Medal can be used from anywhere, so the source
    position is ignored. Instead, we find the link with required_item="Pureblood
    Knight's Medal" and match only by destination.
    """

    @pytest.fixture
    def zone_links_with_medal(self):
        """Zone links including a Medal link."""
        return [
            {
                "id": "link1",
                "source": "Chapel of Anticipation",
                "target": "Before Regal Ancestor Spirit",
                "source_key": "chapel_start",
                "target_key": "siofra_nokron_preboss",
                "required_item": "Pureblood Knight's Medal",
                "type": "random",
                "is_one_way": True,
            },
            {
                "id": "link2",
                "source": "Chapel of Anticipation",
                "target": "Limgrave",
                "source_key": "chapel_start",
                "target_key": "limgrave",
                "type": "preexisting",
            },
            {
                "id": "link3",
                "source": "Limgrave",
                "target": "Stormveil Castle",
                "source_key": "limgrave",
                "target_key": "stormveil",
                "type": "random",
            },
        ]

    def _make_mock_game(self, zone_links, discovered_links=None, zones=None):
        """Helper to create a mock game object."""
        game = MagicMock()
        game.zone_links = zone_links
        game.discovered_zone_links = discovered_links or []
        game.zones = zones
        return game

    def _setup_db_mock(self, mock_session, game):
        """Helper to setup database mock."""
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = game
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        mock_db.expire_all = MagicMock()
        mock_session.return_value.__aenter__.return_value = mock_db
        return mock_db

    @pytest.mark.asyncio
    async def test_medal_discovery_routes_to_handler(self, mock_client):
        """Medal warp_type should route to _handle_medal_discovery."""
        mock_client._handle_medal_discovery = AsyncMock()

        await mock_client._handle_discovery_v2(
            {
                "source_map_id": "m60_41_36_00",
                "target_map_id": "m12_02_00_00",
                "source_pos": {"x": 100, "y": 50, "z": 200},
                "target_pos": {"x": -50, "y": 100, "z": 300},
                "warp_type": "Medal",
            }
        )

        mock_client._handle_medal_discovery.assert_called_once()

    @pytest.mark.asyncio
    async def test_medal_discovery_ignores_source_position(
        self, mock_client, zone_links_with_medal, mock_manager
    ):
        """Medal discovery should not use source position to find zones."""
        mock_game = self._make_mock_game(zone_links_with_medal)

        mock_resolver = MagicMock()
        mock_resolver.resolve_by_col.return_value = (None, None)
        # Even if source would resolve to some random zone, it shouldn't matter
        mock_resolver.resolve_all_candidates.return_value = [
            ("siofra_nokron_preboss", "Before Regal Ancestor Spirit"),
        ]

        discovery_result = DiscoveryResult(origin="Chapel of Anticipation")
        discovery_result.main_links = [
            DiscoveredLink("Chapel of Anticipation", "Before Regal Ancestor Spirit", "random")
        ]

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch(
                "fogtracker.websocket.mod.propagate_discovery",
                return_value=discovery_result,
            ),
            patch("fogtracker.websocket.mod.compute_zone_exits", return_value=[]),
            patch(
                "fogtracker.websocket.mod.compute_discovery_stats",
                return_value={"discovered": 1, "total": 3, "percent": 33},
            ),
            patch("fogtracker.websocket.mod.expand_discovered_links", return_value=[]),
            patch("fogtracker.websocket.mod.manager", mock_manager),
        ):
            self._setup_db_mock(mock_session, mock_game)

            await mock_client._handle_medal_discovery(
                {
                    "source_map_id": "m60_41_36_00",  # Random source map
                    "target_map_id": "m12_02_00_00",
                    "source_pos": {"x": 100, "y": 50, "z": 200},  # Random position
                    "target_pos": {"x": -50, "y": 100, "z": 300},
                }
            )

        # resolve_all_candidates should only be called once (for target)
        assert mock_resolver.resolve_all_candidates.call_count == 1

        # Should discover the Medal link
        call_args = mock_client.send.call_args[0][0]
        assert call_args["type"] == "discovery_v2_ack"
        assert call_args["resolved"] == [
            {"source": "Chapel of Anticipation", "target": "Before Regal Ancestor Spirit"}
        ]

    @pytest.mark.asyncio
    async def test_medal_discovery_matches_by_target_key(
        self, mock_client, zone_links_with_medal, mock_manager
    ):
        """Medal discovery should match using target_key when available."""
        mock_game = self._make_mock_game(zone_links_with_medal)

        mock_resolver = MagicMock()
        mock_resolver.resolve_by_col.return_value = (None, None)
        # Target candidates include the medal target by key
        mock_resolver.resolve_all_candidates.return_value = [
            ("siofra_nokron_preboss", "Before Regal Ancestor Spirit"),
        ]

        discovery_result = DiscoveryResult(origin="Chapel of Anticipation")
        discovery_result.main_links = [
            DiscoveredLink("Chapel of Anticipation", "Before Regal Ancestor Spirit", "random")
        ]

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch(
                "fogtracker.websocket.mod.propagate_discovery",
                return_value=discovery_result,
            ),
            patch("fogtracker.websocket.mod.compute_zone_exits", return_value=[]),
            patch(
                "fogtracker.websocket.mod.compute_discovery_stats",
                return_value={"discovered": 1, "total": 3, "percent": 33},
            ),
            patch("fogtracker.websocket.mod.expand_discovered_links", return_value=[]),
            patch("fogtracker.websocket.mod.manager", mock_manager),
        ):
            self._setup_db_mock(mock_session, mock_game)

            await mock_client._handle_medal_discovery(
                {
                    "target_map_id": "m12_02_00_00",
                    "target_pos": {"x": -50, "y": 100, "z": 300},
                }
            )

        call_args = mock_client.send.call_args[0][0]
        assert call_args["current_zone"] == "Before Regal Ancestor Spirit"

    @pytest.mark.asyncio
    async def test_medal_discovery_matches_by_display_name(
        self, mock_client, zone_links_with_medal, mock_manager
    ):
        """Medal discovery should fallback to display name matching."""
        mock_game = self._make_mock_game(zone_links_with_medal)

        mock_resolver = MagicMock()
        mock_resolver.resolve_by_col.return_value = (None, None)
        # Target candidates match by display name (different key)
        mock_resolver.resolve_all_candidates.return_value = [
            ("different_key", "Before Regal Ancestor Spirit"),  # Same name, different key
        ]

        discovery_result = DiscoveryResult(origin="Chapel of Anticipation")
        discovery_result.main_links = [
            DiscoveredLink("Chapel of Anticipation", "Before Regal Ancestor Spirit", "random")
        ]

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch(
                "fogtracker.websocket.mod.propagate_discovery",
                return_value=discovery_result,
            ),
            patch("fogtracker.websocket.mod.compute_zone_exits", return_value=[]),
            patch(
                "fogtracker.websocket.mod.compute_discovery_stats",
                return_value={"discovered": 1, "total": 3, "percent": 33},
            ),
            patch("fogtracker.websocket.mod.expand_discovered_links", return_value=[]),
            patch("fogtracker.websocket.mod.manager", mock_manager),
        ):
            self._setup_db_mock(mock_session, mock_game)

            await mock_client._handle_medal_discovery(
                {
                    "target_map_id": "m12_02_00_00",
                    "target_pos": {"x": -50, "y": 100, "z": 300},
                }
            )

        call_args = mock_client.send.call_args[0][0]
        assert call_args["current_zone"] == "Before Regal Ancestor Spirit"

    @pytest.mark.asyncio
    async def test_medal_discovery_no_medal_link_in_zone_links(self, mock_client, mock_manager):
        """Should return error when no Medal link exists in zone_links."""
        zone_links_no_medal = [
            {
                "id": "link1",
                "source": "Limgrave",
                "target": "Stormveil Castle",
                "type": "random",
            },
        ]
        mock_game = self._make_mock_game(zone_links_no_medal)

        mock_resolver = MagicMock()
        mock_resolver.resolve_by_col.return_value = (None, None)
        mock_resolver.resolve_all_candidates.return_value = [
            ("some_zone", "Some Zone"),
        ]

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
        ):
            self._setup_db_mock(mock_session, mock_game)

            await mock_client._handle_medal_discovery(
                {
                    "target_map_id": "m12_02_00_00",
                    "target_pos": {"x": -50, "y": 100, "z": 300},
                }
            )

        call_args = mock_client.send.call_args[0][0]
        assert call_args["type"] == "discovery_v2_ack"
        assert call_args["error"] == "No Medal link found in spoiler log"
        assert call_args["propagated"] == []

    @pytest.mark.asyncio
    async def test_medal_discovery_target_not_in_candidates(
        self, mock_client, zone_links_with_medal, mock_manager
    ):
        """Should return error when Medal target doesn't match any candidate."""
        mock_game = self._make_mock_game(zone_links_with_medal)

        mock_resolver = MagicMock()
        mock_resolver.resolve_by_col.return_value = (None, None)
        # Candidates don't include the medal target
        mock_resolver.resolve_all_candidates.return_value = [
            ("limgrave", "Limgrave"),
            ("stormveil", "Stormveil Castle"),
        ]

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch("fogtracker.websocket.mod.compute_zone_exits", return_value=[]),
            patch(
                "fogtracker.websocket.mod.compute_discovery_stats",
                return_value={"discovered": 0, "total": 3, "percent": 0},
            ),
            patch("fogtracker.websocket.mod.manager", mock_manager),
        ):
            self._setup_db_mock(mock_session, mock_game)

            await mock_client._handle_medal_discovery(
                {
                    "target_map_id": "m12_02_00_00",
                    "target_pos": {"x": -50, "y": 100, "z": 300},
                }
            )

        call_args = mock_client.send.call_args[0][0]
        assert call_args["type"] == "discovery_v2_ack"
        assert call_args["error"] == "Medal target not found in candidates"
        assert call_args["resolved"] == []

    @pytest.mark.asyncio
    async def test_medal_discovery_no_target_candidates(self, mock_client, zone_links_with_medal):
        """Should return error when no target zone candidates found."""
        mock_game = self._make_mock_game(zone_links_with_medal)

        mock_resolver = MagicMock()
        mock_resolver.resolve_by_col.return_value = (None, None)
        mock_resolver.resolve_all_candidates.return_value = []  # No candidates

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
        ):
            self._setup_db_mock(mock_session, mock_game)

            await mock_client._handle_medal_discovery(
                {
                    "target_map_id": "m12_02_00_00",
                    "target_pos": {"x": -50, "y": 100, "z": 300},
                }
            )

        call_args = mock_client.send.call_args[0][0]
        assert call_args["type"] == "discovery_v2_ack"
        assert call_args["error"] == "No target zone candidates found for Medal warp"

    @pytest.mark.asyncio
    async def test_medal_discovery_broadcasts_to_host_and_viewers(
        self, mock_client, zone_links_with_medal, mock_manager
    ):
        """Medal discovery should broadcast to connected clients."""
        mock_game = self._make_mock_game(zone_links_with_medal)

        mock_resolver = MagicMock()
        mock_resolver.resolve_by_col.return_value = (None, None)
        mock_resolver.resolve_all_candidates.return_value = [
            ("siofra_nokron_preboss", "Before Regal Ancestor Spirit"),
        ]

        discovery_result = DiscoveryResult(origin="Chapel of Anticipation")
        discovery_result.main_links = [
            DiscoveredLink("Chapel of Anticipation", "Before Regal Ancestor Spirit", "random")
        ]

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch(
                "fogtracker.websocket.mod.propagate_discovery",
                return_value=discovery_result,
            ),
            patch("fogtracker.websocket.mod.compute_zone_exits", return_value=[]),
            patch(
                "fogtracker.websocket.mod.compute_discovery_stats",
                return_value={"discovered": 1, "total": 3, "percent": 33},
            ),
            patch(
                "fogtracker.websocket.mod.expand_discovered_links",
                return_value=[{"zone_link_id": "link1"}],
            ),
            patch("fogtracker.websocket.mod.manager", mock_manager),
        ):
            self._setup_db_mock(mock_session, mock_game)

            await mock_client._handle_medal_discovery(
                {
                    "target_map_id": "m12_02_00_00",
                    "target_pos": {"x": -50, "y": 100, "z": 300},
                }
            )

        mock_manager.broadcast_to_all.assert_called_once()
        broadcast_args = mock_manager.broadcast_to_all.call_args
        assert broadcast_args[0][0] == mock_client.game_id
        broadcast_data = broadcast_args[0][1]
        assert broadcast_data["type"] == "discovery"
        assert broadcast_data["focus_target"] == "Before Regal Ancestor Spirit"


# =============================================================================
# TestZoneQueryGraceEntityId
# =============================================================================


class TestZoneQueryGraceEntityId:
    """Tests for zone_query with grace_entity_id parameter.

    When fast traveling to a grace, the mod sends the grace entity ID.
    The server should use this to precisely resolve the zone, bypassing
    position-based resolution which can be ambiguous.
    """

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
        ]

    @pytest.fixture
    def sample_discovered_links(self):
        """Sample discovered_zone_links with Limgrave discovered."""
        return [{"zone_link_id": "link1"}]

    def _make_mock_game(self, zone_links, discovered_links=None):
        """Helper to create a mock game object."""
        game = MagicMock()
        game.zone_links = zone_links
        game.discovered_zone_links = discovered_links or []
        return game

    def _setup_db_mock(self, mock_session, game):
        """Helper to setup database mock."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = game
        mock_db.execute.return_value = mock_result
        mock_session.return_value.__aenter__.return_value = mock_db
        return mock_db

    @pytest.mark.asyncio
    async def test_zone_query_uses_grace_entity_id_when_provided(
        self, mock_client, sample_zone_links, sample_discovered_links
    ):
        """Should use grace_entity_id to resolve zone when provided."""
        mock_game = self._make_mock_game(sample_zone_links, sample_discovered_links)

        mock_resolver = MagicMock()
        # Position resolves to multiple candidates (ambiguous)
        mock_resolver.resolve_by_col.return_value = (None, None)
        mock_resolver.resolve_all_candidates.return_value = [
            ("limgrave", "Limgrave"),
            ("stormveil", "Stormveil Castle"),
        ]

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch("fogtracker.websocket.mod.compute_zone_exits", return_value=[]),
            patch(
                "fogtracker.websocket.mod.resolve_zone_by_grace_entity_id",
                return_value="Limgrave",
            ) as mock_grace_resolve,
        ):
            self._setup_db_mock(mock_session, mock_game)

            # Pass grace_entity_id for "The First Step" grace in Limgrave
            await mock_client._handle_zone_query(
                {
                    "map_id": "m60_42_36_00",
                    "pos": {"x": 100, "y": 50, "z": 200},
                    "grace_entity_id": 1042362951,
                }
            )

        # Should call grace resolver
        mock_grace_resolve.assert_called_once_with(1042362951)

        # Should return Limgrave (from grace resolution, not position)
        call_args = mock_client.send.call_args[0][0]
        assert call_args["zone"] == "Limgrave"

    @pytest.mark.asyncio
    async def test_zone_query_grace_entity_id_skipped_if_zone_not_discovered(
        self, mock_client, sample_zone_links
    ):
        """Should skip grace resolution if zone is not discovered."""
        mock_game = self._make_mock_game(sample_zone_links, discovered_links=[])

        mock_resolver = MagicMock()
        mock_resolver.resolve_by_col.return_value = (None, None)
        mock_resolver.resolve_all_candidates.return_value = []

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch("fogtracker.websocket.mod.compute_zone_exits", return_value=[]),
            patch(
                "fogtracker.websocket.mod.resolve_zone_by_grace_entity_id",
                return_value="Limgrave",  # Grace resolves to Limgrave
            ),
        ):
            self._setup_db_mock(mock_session, mock_game)

            await mock_client._handle_zone_query(
                {
                    "map_id": "m60_42_36_00",
                    "pos": {"x": 100, "y": 50, "z": 200},
                    "grace_entity_id": 1042362951,
                }
            )

        # Should return None (Limgrave not discovered)
        call_args = mock_client.send.call_args[0][0]
        assert call_args["zone"] is None

    @pytest.mark.asyncio
    async def test_zone_query_fallback_when_grace_returns_none(
        self, mock_client, sample_zone_links, sample_discovered_links
    ):
        """Should fallback to position resolution when grace returns None."""
        mock_game = self._make_mock_game(sample_zone_links, sample_discovered_links)

        mock_resolver = MagicMock()
        # Col resolution finds the zone
        mock_resolver.resolve_by_col.return_value = ("limgrave", "Limgrave")

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch("fogtracker.websocket.mod.compute_zone_exits", return_value=[]),
            patch(
                "fogtracker.websocket.mod.resolve_zone_by_grace_entity_id",
                return_value=None,  # Grace not found in mapping
            ),
        ):
            self._setup_db_mock(mock_session, mock_game)

            # Pass unknown grace_entity_id (fog gate entity, not a grace)
            await mock_client._handle_zone_query(
                {
                    "map_id": "m60_42_36_00",
                    "pos": {"x": 100, "y": 50, "z": 200},
                    "play_region_id": 0x100000,
                    "grace_entity_id": 755890042,  # Fog gate entity, not a grace
                }
            )

        # Should fallback to Col resolution
        call_args = mock_client.send.call_args[0][0]
        assert call_args["zone"] == "Limgrave"

    @pytest.mark.asyncio
    async def test_zone_query_no_grace_entity_id_uses_position(
        self, mock_client, sample_zone_links, sample_discovered_links
    ):
        """Should use position resolution when no grace_entity_id provided."""
        mock_game = self._make_mock_game(sample_zone_links, sample_discovered_links)

        mock_resolver = MagicMock()
        mock_resolver.resolve_by_col.return_value = ("limgrave", "Limgrave")

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch("fogtracker.websocket.mod.compute_zone_exits", return_value=[]),
            patch("fogtracker.websocket.mod.resolve_zone_by_grace_entity_id") as mock_grace_resolve,
        ):
            self._setup_db_mock(mock_session, mock_game)

            # No grace_entity_id in the message
            await mock_client._handle_zone_query(
                {
                    "map_id": "m60_42_36_00",
                    "pos": {"x": 100, "y": 50, "z": 200},
                    "play_region_id": 0x100000,
                }
            )

        # Should NOT call grace resolver
        mock_grace_resolve.assert_not_called()

        # Should use Col resolution
        call_args = mock_client.send.call_args[0][0]
        assert call_args["zone"] == "Limgrave"

    @pytest.mark.asyncio
    async def test_zone_query_grace_entity_id_priority_over_col(
        self, mock_client, sample_zone_links, sample_discovered_links
    ):
        """Grace entity ID should have priority over Col resolution."""
        mock_game = self._make_mock_game(sample_zone_links, sample_discovered_links)

        mock_resolver = MagicMock()
        # Col would resolve to different zone
        mock_resolver.resolve_by_col.return_value = ("stormveil", "Stormveil Castle")

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch("fogtracker.websocket.mod.compute_zone_exits", return_value=[]),
            patch(
                "fogtracker.websocket.mod.resolve_zone_by_grace_entity_id",
                return_value="Limgrave",
            ),
        ):
            self._setup_db_mock(mock_session, mock_game)

            await mock_client._handle_zone_query(
                {
                    "map_id": "m60_42_36_00",
                    "pos": {"x": 100, "y": 50, "z": 200},
                    "play_region_id": 0x100000,
                    "grace_entity_id": 1042362951,
                }
            )

        # Should use grace resolution (Limgrave), not Col (Stormveil Castle)
        call_args = mock_client.send.call_args[0][0]
        assert call_args["zone"] == "Limgrave"
