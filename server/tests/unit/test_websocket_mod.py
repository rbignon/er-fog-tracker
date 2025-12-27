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
    async def test_discovery_v2_discovers_all_tied_matches(
        self, mock_client, sample_zone_links, mock_manager
    ):
        """Should discover all matches when multiple have same cost."""
        mock_game = self._make_mock_game(sample_zone_links)

        mock_resolver = MagicMock()
        mock_resolver.resolve_by_col.return_value = (None, None)
        mock_resolver.resolve_all_candidates.side_effect = [
            [("limgrave", "Limgrave"), ("weeping", "Weeping Peninsula")],
            [("stormveil", "Stormveil Castle"), ("liurnia", "Liurnia")],
        ]

        # Multiple matches with same cost
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

        # Should propagate BOTH matches (same cost)
        assert mock_propagate.call_count == 2

    @pytest.mark.asyncio
    async def test_discovery_v2_destination_zone_from_actual_discovery(
        self, mock_client, sample_zone_links, mock_manager
    ):
        """When multiple matches tie with cost 0 but only one discovers new links,
        destination_zone should be from the one that actually discovered something.

        This tests the fix for the bug where:
        - Match 1: Erdtree Sanctuary -> Academy Main Entrance (already known)
        - Match 2: Behind Erdtree Sanctuary -> Grand Library (new discovery)
        The destination should be Grand Library, not Academy Main Entrance.
        """
        mock_game = self._make_mock_game(sample_zone_links)

        mock_resolver = MagicMock()
        mock_resolver.resolve_by_col.return_value = (None, None)
        mock_resolver.resolve_all_candidates.side_effect = [
            [("erdtree_sanctuary", "Erdtree Sanctuary"), ("behind_erdtree", "Behind Erdtree")],
            [("main_entrance", "Main Entrance"), ("grand_library", "Grand Library")],
        ]

        # Multiple matches with same cost
        all_matches = [
            ("Erdtree Sanctuary", "Main Entrance", {"id": "link1"}),  # Already known
            ("Behind Erdtree", "Grand Library", {"id": "link2"}),  # New discovery
        ]

        # First discovery result: already known (no main_links)
        discovery_result_1 = DiscoveryResult(origin="Erdtree Sanctuary")
        # main_links is empty because link was already discovered

        # Second discovery result: new discovery (has main_links)
        discovery_result_2 = DiscoveryResult(origin="Behind Erdtree")
        discovery_result_2.main_links = [
            DiscoveredLink("Behind Erdtree", "Grand Library", "random")
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
                side_effect=[discovery_result_1, discovery_result_2],
            ),
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

        call_args = mock_client.send.call_args[0][0]
        # Should use the zone from the discovery that actually found new links
        # (Grand Library from discovery_result_2, not Main Entrance from discovery_result_1)
        assert call_args["current_zone"] == "Grand Library"

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

        # Should complete without error
        call_args = mock_client.send.call_args[0][0]
        assert call_args["type"] == "discovery_v2_ack"
        assert call_args["propagated"] == []
