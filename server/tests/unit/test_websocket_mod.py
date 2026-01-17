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
            "source_id": "limgrave",
            "target": "Stormveil Castle",
            "target_id": "stormveil_castle",
            "type": "random",
        },
        {
            "id": "link2",
            "source": "Stormveil Castle",
            "source_id": "stormveil_castle",
            "target": "Liurnia",
            "target_id": "liurnia",
            "type": "random",
        },
        {
            "id": "link3",
            "source": "Limgrave",
            "source_id": "limgrave",
            "target": "Weeping Peninsula",
            "target_id": "weeping_peninsula",
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
            {"type": "zone_query_ack", "zone": None, "zone_id": None, "exits": []}
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
            {"type": "zone_query_ack", "zone": None, "zone_id": None, "exits": []}
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
            ("limgrave", "Limgrave"),  # Discovered (source of link1)
            ("stormveil_castle", "Stormveil Castle"),  # Discovered (target of link1)
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
        # Col resolves to discovered zone (zone_id must match fixture)
        mock_resolver.resolve_by_col.return_value = ("stormveil_castle", "Stormveil Castle")

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
            {"type": "zone_query_ack", "zone": None, "zone_id": None, "exits": []}
        )


# =============================================================================
# TestDiscoveryV2Handler
# =============================================================================


class TestDiscoveryV2Handler:
    """Tests for _handle_discovery_v2 method."""

    @pytest.fixture
    def zone_links_with_ids(self):
        """Zone links with source_id/target_id (zone_key format)."""
        return [
            {
                "id": "link1",
                "source": "Limgrave",
                "source_id": "limgrave",
                "target": "Stormveil Castle",
                "target_id": "stormveil",
                "type": "random",
            },
            {
                "id": "link2",
                "source": "Stormveil Castle",
                "source_id": "stormveil",
                "target": "Liurnia",
                "target_id": "liurnia",
                "type": "random",
            },
            {
                "id": "link3",
                "source": "Chapel of Anticipation",
                "source_id": "chapel",
                "target": "Limgrave",
                "target_id": "limgrave",
                "type": "preexisting",
            },
        ]

    def _make_mock_game(self, zone_links, discovered_links=None, entity_mapping=None):
        """Helper to create a mock game object."""
        game = MagicMock()
        game.zone_links = zone_links
        game.discovered_zone_links = discovered_links or []
        game.entity_mapping = entity_mapping
        game.zones = {}
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
                "fogtracker.websocket.mod.find_all_matching_zone_pairs_by_ids",
                return_value=[
                    (
                        "limgrave",
                        "stormveil_castle",
                        {
                            "id": "link1",
                            "source": "Limgrave",
                            "source_id": "limgrave",
                            "target": "Stormveil Castle",
                            "target_id": "stormveil_castle",
                            "type": "random",
                        },
                    )
                ],
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
                "fogtracker.websocket.mod.find_all_matching_zone_pairs_by_ids",
                return_value=[
                    (
                        "limgrave",
                        "stormveil_castle",
                        {
                            "id": "link1",
                            "source": "Limgrave",
                            "source_id": "limgrave",
                            "target": "Stormveil Castle",
                            "target_id": "stormveil_castle",
                            "type": "random",
                        },
                    )
                ],
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
            (
                "weeping_peninsula",
                "liurnia",
                {
                    "id": "linkX",
                    "source": "Weeping Peninsula",
                    "source_id": "weeping_peninsula",
                    "target": "Liurnia",
                    "target_id": "liurnia",
                    "type": "random",
                },
            ),  # Cost 5
            (
                "limgrave",
                "stormveil_castle",
                {
                    "id": "link1",
                    "source": "Limgrave",
                    "source_id": "limgrave",
                    "target": "Stormveil Castle",
                    "target_id": "stormveil_castle",
                    "type": "random",
                },
            ),  # Cost 1 (lowest)
        ]

        discovery_result = DiscoveryResult(origin="Limgrave")
        discovery_result.main_links = [DiscoveredLink("Limgrave", "Stormveil Castle", "random")]

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch(
                "fogtracker.websocket.mod.find_all_matching_zone_pairs_by_ids",
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
        # propagate_discovery(db, game_id, source_id, target_id, discovered_by=...)
        # Positional args are at index 0, kwargs at index 1
        assert call_args[0][2] == "limgrave"  # source_id (3rd positional arg)
        assert call_args[0][3] == "stormveil_castle"  # target_id (4th positional arg)

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
            (
                "limgrave",
                "stormveil_castle",
                {
                    "id": "link1",
                    "source": "Limgrave",
                    "source_id": "limgrave",
                    "target": "Stormveil Castle",
                    "target_id": "stormveil_castle",
                    "type": "random",
                },
            ),
            (
                "weeping_peninsula",
                "liurnia",
                {
                    "id": "linkX",
                    "source": "Weeping Peninsula",
                    "source_id": "weeping_peninsula",
                    "target": "Liurnia",
                    "target_id": "liurnia",
                    "type": "random",
                },
            ),
        ]

        discovery_result = DiscoveryResult(origin="Limgrave")
        discovery_result.main_links = [DiscoveredLink("Limgrave", "Stormveil Castle", "random")]

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch(
                "fogtracker.websocket.mod.find_all_matching_zone_pairs_by_ids",
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
            (
                "erdtree_sanctuary",
                "main_entrance",
                {
                    "id": "link1",
                    "source": "Erdtree Sanctuary",
                    "source_id": "erdtree_sanctuary",
                    "target": "Main Entrance",
                    "target_id": "main_entrance",
                    "type": "random",
                },
            ),  # Already known
            (
                "behind_erdtree",
                "grand_library",
                {
                    "id": "link2",
                    "source": "Behind Erdtree",
                    "source_id": "behind_erdtree",
                    "target": "Grand Library",
                    "target_id": "grand_library",
                    "type": "random",
                },
            ),  # New discovery
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
                "fogtracker.websocket.mod.find_all_matching_zone_pairs_by_ids",
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
            (
                "limgrave",
                "stormveil_castle",
                {
                    "id": "link1",
                    "source": "Limgrave",
                    "source_id": "limgrave",
                    "target": "Stormveil Castle",
                    "target_id": "stormveil_castle",
                    "type": "random",
                },
            ),
        ]

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch(
                "fogtracker.websocket.mod.find_all_matching_zone_pairs_by_ids",
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
                "fogtracker.websocket.mod.find_all_matching_zone_pairs_by_ids",
                return_value=[
                    (
                        "limgrave",
                        "stormveil_castle",
                        {
                            "id": "link1",
                            "source": "Limgrave",
                            "source_id": "limgrave",
                            "target": "Stormveil Castle",
                            "target_id": "stormveil_castle",
                            "type": "random",
                        },
                    )
                ],
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
                "fogtracker.websocket.mod.find_all_matching_zone_pairs_by_ids",
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
                "fogtracker.websocket.mod.find_all_matching_zone_pairs_by_ids",
                return_value=[
                    (
                        "limgrave",
                        "stormveil_castle",
                        {
                            "id": "link1",
                            "source": "Limgrave",
                            "source_id": "limgrave",
                            "target": "Stormveil Castle",
                            "target_id": "stormveil_castle",
                            "type": "random",
                        },
                    )
                ],
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
                "fogtracker.websocket.mod.find_all_matching_zone_pairs_by_ids",
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

    # -------------------------------------------------------------------------
    # Regression tests for priority filtering bug (commit 38483fd, reverted)
    #
    # These tests ensure that when multiple zone matches have the same backprop
    # cost, ALL matches are discovered (not just the one with "best priority"
    # based on position in candidate list).
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_regression_fias_champions_to_siofra_river(
        self, mock_client, sample_zone_links, mock_manager
    ):
        """Regression test: Fia's Champions → Siofra River must be discovered.

        Bug scenario (Bug 1):
        - Player is at "Deeproot Depths - Fia's Champions"
        - Player warps to Siofra River via waygate
        - Two matches found with same cost 0:
          - Deeproot Depths → Siofra River
          - Deeproot Depths - Fia's Champions → Siofra River
        - BOTH must be discovered, not just the first one.

        The bug was introduced by filtering matches based on "candidate priority"
        (position in candidate list), which incorrectly excluded the more specific
        zone match.
        """
        mock_game = self._make_mock_game(sample_zone_links)

        mock_resolver = MagicMock()
        mock_resolver.resolve_by_col.return_value = (None, None)
        # Candidates ordered by position - Deeproot Depths appears before Fia's Champions
        mock_resolver.resolve_all_candidates.side_effect = [
            [
                ("deeproot", "Deeproot Depths"),
                ("fias_champions", "Deeproot Depths - Fia's Champions"),
            ],
            [("siofra", "Siofra River")],
        ]

        # Both links exist in the spoiler log
        all_matches = [
            (
                "deeproot_depths",
                "siofra_river",
                {
                    "id": "link1",
                    "source": "Deeproot Depths",
                    "source_id": "deeproot_depths",
                    "target": "Siofra River",
                    "target_id": "siofra_river",
                    "type": "random",
                },
            ),
            (
                "deeproot_depths_fias_champions",
                "siofra_river",
                {
                    "id": "link2",
                    "source": "Deeproot Depths - Fia's Champions",
                    "source_id": "deeproot_depths_fias_champions",
                    "target": "Siofra River",
                    "target_id": "siofra_river",
                    "type": "random",
                },
            ),
        ]

        discovery_result = DiscoveryResult(origin="Deeproot Depths")
        discovery_result.main_links = [DiscoveredLink("Deeproot Depths", "Siofra River", "random")]

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch(
                "fogtracker.websocket.mod.find_all_matching_zone_pairs_by_ids",
                return_value=all_matches,
            ),
            patch(
                "fogtracker.websocket.mod.compute_backprop_cost",
                return_value=0,  # Same cost for both
            ),
            patch(
                "fogtracker.websocket.mod.propagate_discovery",
                return_value=discovery_result,
            ) as mock_propagate,
            patch("fogtracker.websocket.mod.compute_zone_exits", return_value=[]),
            patch(
                "fogtracker.websocket.mod.compute_discovery_stats",
                return_value={"discovered": 2, "total": 10, "percent": 20},
            ),
            patch("fogtracker.websocket.mod.expand_discovered_links", return_value=[]),
            patch("fogtracker.websocket.mod.manager", mock_manager),
        ):
            self._setup_db_mock(mock_session, mock_game)

            await mock_client._handle_discovery_v2(
                {
                    "source_map_id": "m12_03_00_00",  # Deeproot Depths
                    "target_map_id": "m12_02_00_00",  # Siofra River area
                    "source_pos": {"x": -355.4, "y": 150.1, "z": -199.4},
                    "target_pos": {"x": 1450.1, "y": -805.1, "z": 1640.3},
                }
            )

        # BOTH matches must be propagated (same cost)
        assert mock_propagate.call_count == 2

    @pytest.mark.asyncio
    async def test_regression_divine_tower_to_margit(
        self, mock_client, sample_zone_links, mock_manager
    ):
        """Regression test: Divine Tower of East Altus Start → Margit must be discovered.

        Bug scenario (Bug 2):
        - Player is at "Divine Tower of East Altus Start"
        - Player defeats a boss and warps to Stormveil area
        - Two matches found with same cost 0:
          - Ashen Leyndell - before Divine Tower → Stormveil Castle after Gate
          - Divine Tower of East Altus Start → Margit, the Fell Omen
        - BOTH must be discovered, not just the first one.

        The bug was excluding the correct Divine Tower → Margit link because
        it had lower "priority" (appeared later in the candidate list).
        """
        mock_game = self._make_mock_game(sample_zone_links)

        mock_resolver = MagicMock()
        mock_resolver.resolve_by_col.return_value = (None, None)
        # Ashen Leyndell appears before Divine Tower in source candidates
        mock_resolver.resolve_all_candidates.side_effect = [
            [
                ("ashen_leyndell", "Ashen Leyndell - before Divine Tower"),
                ("ashen_leyndell2", "Ashen Leyndell"),
                ("divine_tower", "Divine Tower of East Altus Start"),
            ],
            [
                ("stormveil_after", "Stormveil Castle after Gate"),
                ("stormhill", "Stormhill"),
                ("margit", "Margit, the Fell Omen"),
            ],
        ]

        # Both links exist in the spoiler log
        all_matches = [
            (
                "ashen_leyndell_before_divine_tower",
                "stormveil_castle_after_gate",
                {
                    "id": "link1",
                    "source": "Ashen Leyndell - before Divine Tower",
                    "source_id": "ashen_leyndell_before_divine_tower",
                    "target": "Stormveil Castle after Gate",
                    "target_id": "stormveil_castle_after_gate",
                    "type": "random",
                },
            ),
            (
                "divine_tower_of_east_altus_start",
                "margit_the_fell_omen",
                {
                    "id": "link2",
                    "source": "Divine Tower of East Altus Start",
                    "source_id": "divine_tower_of_east_altus_start",
                    "target": "Margit, the Fell Omen",
                    "target_id": "margit_the_fell_omen",
                    "type": "random",
                },
            ),
        ]

        discovery_result = DiscoveryResult(origin="Ashen Leyndell - before Divine Tower")
        discovery_result.main_links = [
            DiscoveredLink(
                "Ashen Leyndell - before Divine Tower",
                "Stormveil Castle after Gate",
                "random",
            )
        ]

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch(
                "fogtracker.websocket.mod.find_all_matching_zone_pairs_by_ids",
                return_value=all_matches,
            ),
            patch(
                "fogtracker.websocket.mod.compute_backprop_cost",
                return_value=0,  # Same cost for both
            ),
            patch(
                "fogtracker.websocket.mod.propagate_discovery",
                return_value=discovery_result,
            ) as mock_propagate,
            patch("fogtracker.websocket.mod.compute_zone_exits", return_value=[]),
            patch(
                "fogtracker.websocket.mod.compute_discovery_stats",
                return_value={"discovered": 2, "total": 10, "percent": 20},
            ),
            patch("fogtracker.websocket.mod.expand_discovered_links", return_value=[]),
            patch("fogtracker.websocket.mod.manager", mock_manager),
        ):
            self._setup_db_mock(mock_session, mock_game)

            await mock_client._handle_discovery_v2(
                {
                    "source_map_id": "m11_05_00_00",  # Ashen Leyndell area
                    "target_map_id": "m10_00_00_00",  # Stormveil area
                    "source_pos": {"x": 125.3, "y": -21.5, "z": -200.0},
                    "target_pos": {"x": -34.5, "y": -0.6, "z": -18.0},
                }
            )

        # BOTH matches must be propagated (same cost)
        assert mock_propagate.call_count == 2

    @pytest.mark.asyncio
    async def test_regression_valiant_gargoyles_to_astel(
        self, mock_client, sample_zone_links, mock_manager
    ):
        """Regression test: Valiant Gargoyles → Astel must be discovered.

        Bug scenario (Bug 5):
        - Player is at "Valiant Gargoyles" (confirmed by grace entity)
        - Player defeats boss and warps to Astel area
        - Two matches found with same cost 0:
          - Siofra River → Before Astel, Naturalborn of the Void
          - Valiant Gargoyles → Astel, Naturalborn of the Void
        - BOTH must be discovered, not just the first one.

        The bug was excluding the Valiant Gargoyles link because the warp
        position placed it later in the candidate list than Siofra River.
        """
        mock_game = self._make_mock_game(sample_zone_links)

        mock_resolver = MagicMock()
        mock_resolver.resolve_by_col.return_value = (None, None)
        # Siofra River appears before Valiant Gargoyles based on warp position
        mock_resolver.resolve_all_candidates.side_effect = [
            [
                ("nokron", "Nokron before Mimic Tear"),
                ("siofra", "Siofra River"),
                ("valiant", "Valiant Gargoyles"),
            ],
            [
                ("astel", "Astel, Naturalborn of the Void"),
                ("before_astel", "Before Astel, Naturalborn of the Void"),
            ],
        ]

        # Both links exist in the spoiler log
        all_matches = [
            (
                "siofra_river",
                "before_astel_naturalborn_of_the_void",
                {
                    "id": "link1",
                    "source": "Siofra River",
                    "source_id": "siofra_river",
                    "target": "Before Astel, Naturalborn of the Void",
                    "target_id": "before_astel_naturalborn_of_the_void",
                    "type": "random",
                },
            ),
            (
                "valiant_gargoyles",
                "astel_naturalborn_of_the_void",
                {
                    "id": "link2",
                    "source": "Valiant Gargoyles",
                    "source_id": "valiant_gargoyles",
                    "target": "Astel, Naturalborn of the Void",
                    "target_id": "astel_naturalborn_of_the_void",
                    "type": "random",
                },
            ),
        ]

        discovery_result = DiscoveryResult(origin="Siofra River")
        discovery_result.main_links = [
            DiscoveredLink("Siofra River", "Before Astel, Naturalborn of the Void", "random")
        ]

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch(
                "fogtracker.websocket.mod.find_all_matching_zone_pairs_by_ids",
                return_value=all_matches,
            ),
            patch(
                "fogtracker.websocket.mod.compute_backprop_cost",
                return_value=0,  # Same cost for both
            ),
            patch(
                "fogtracker.websocket.mod.propagate_discovery",
                return_value=discovery_result,
            ) as mock_propagate,
            patch("fogtracker.websocket.mod.compute_zone_exits", return_value=[]),
            patch(
                "fogtracker.websocket.mod.compute_discovery_stats",
                return_value={"discovered": 2, "total": 10, "percent": 20},
            ),
            patch("fogtracker.websocket.mod.expand_discovered_links", return_value=[]),
            patch("fogtracker.websocket.mod.manager", mock_manager),
        ):
            self._setup_db_mock(mock_session, mock_game)

            await mock_client._handle_discovery_v2(
                {
                    "source_map_id": "m12_02_00_00",  # Siofra/Nokron area
                    "target_map_id": "m12_04_00_00",  # Astel area
                    "source_pos": {"x": 1189.8, "y": -618.7, "z": 1906.4},
                    "target_pos": {"x": -104.3, "y": -106.1, "z": -241.5},
                }
            )

        # BOTH matches must be propagated (same cost)
        assert mock_propagate.call_count == 2


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
                "source_id": "chapel_start",
                "target_id": "siofra_nokron_preboss",
                "required_item": "Pureblood Knight's Medal",
                "type": "random",
                "is_one_way": True,
            },
            {
                "id": "link2",
                "source": "Chapel of Anticipation",
                "target": "Limgrave",
                "target_id": "limgrave",
                "source_id": "chapel_start",
                "type": "preexisting",
            },
            {
                "id": "link3",
                "source": "Limgrave",
                "source_id": "limgrave",
                "target": "Stormveil Castle",
                "target_id": "stormveil",
                "type": "random",
            },
        ]

    def _make_mock_game(self, zone_links, discovered_links=None, zones=None):
        """Helper to create a mock game object."""
        game = MagicMock()
        game.zone_links = zone_links
        game.discovered_zone_links = discovered_links or []
        game.zones = zones or {}
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
    async def test_medal_discovery_matches_by_target_id(
        self, mock_client, zone_links_with_medal, mock_manager
    ):
        """Medal discovery should match using target_id when available."""
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
                "source_id": "limgrave",
                "target": "Stormveil Castle",
                "target_id": "stormveil_castle",
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
                "source_id": "limgrave",
                "target": "Stormveil Castle",
                "target_id": "stormveil_castle",
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
        game.zones = {}
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
        # Grace resolver on the mock - now uses get_grace_info which returns dict
        mock_resolver.get_grace_info.return_value = {"zone_id": "limgrave", "zone": "Limgrave"}

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch("fogtracker.websocket.mod.compute_zone_exits", return_value=[]),
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

        # Should call grace info resolver
        mock_resolver.get_grace_info.assert_called_once_with(1042362951)

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
        # Grace resolves to Limgrave (but Limgrave is not discovered)
        mock_resolver.get_grace_info.return_value = {"zone_id": "limgrave", "zone": "Limgrave"}

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch("fogtracker.websocket.mod.compute_zone_exits", return_value=[]),
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
        # Grace not found in mapping
        mock_resolver.get_grace_info.return_value = None
        # Provide candidates
        mock_resolver.resolve_all_candidates.return_value = [("limgrave", "Limgrave")]

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch("fogtracker.websocket.mod.compute_zone_exits", return_value=[]),
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
        # Provide candidates
        mock_resolver.resolve_all_candidates.return_value = [("limgrave", "Limgrave")]

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch("fogtracker.websocket.mod.compute_zone_exits", return_value=[]),
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
        mock_resolver.get_grace_info.assert_not_called()

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
        # Grace resolves to Limgrave
        mock_resolver.get_grace_info.return_value = {"zone_id": "limgrave", "zone": "Limgrave"}
        # Provide candidates for zone_query (both limgrave and stormveil)
        mock_resolver.resolve_all_candidates.return_value = [
            ("limgrave", "Limgrave"),
            ("stormveil", "Stormveil Castle"),
        ]

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch("fogtracker.websocket.mod.compute_zone_exits", return_value=[]),
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


# =============================================================================
# TestSourceZoneFiltering
# =============================================================================


class TestSourceZoneFiltering:
    """Tests for source_zone filtering in discovery_v2.

    When the mod sends source_zone or source_zone_id, the server should
    filter to only matching candidates to prevent discovering multiple
    links when only one fog gate was traversed.
    """

    @pytest.fixture
    def zone_links_ambiguous(self):
        """Zone links where multiple zones share the same map.

        This creates an ambiguous situation where the source position
        could match either limgrave or limgrave_east.
        """
        return [
            {
                "id": "link1",
                "source": "Limgrave",
                "source_id": "limgrave",
                "target": "Stormveil Castle",
                "target_id": "stormveil",
                "type": "random",
            },
            {
                "id": "link2",
                "source": "Limgrave - East",
                "source_id": "limgrave_east",
                "target": "Caelid",
                "target_id": "caelid",
                "type": "random",
            },
            {
                "id": "link3",
                "source": "Limgrave - East",
                "source_id": "limgrave_east",
                "target": "Stormveil Castle",
                "target_id": "stormveil",
                "type": "random",
            },
        ]

    def _make_mock_game(self, zone_links, discovered_links=None, entity_mapping=None):
        """Helper to create a mock game object."""
        game = MagicMock()
        game.zone_links = zone_links
        game.discovered_zone_links = discovered_links or []
        game.entity_mapping = entity_mapping
        game.zones = {}
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
    async def test_source_zone_filters_to_matching_display_name(
        self, mock_client, mock_manager, zone_links_ambiguous
    ):
        """When source_zone matches a candidate display name, filter to only that candidate.

        This prevents discovering multiple links when only one fog gate was traversed.
        """
        mock_game = self._make_mock_game(zone_links_ambiguous)
        mock_resolver = MagicMock()
        mock_resolver.resolve_by_col.return_value = (None, None)
        # Source candidates: limgrave first, then limgrave_east
        mock_resolver.resolve_all_candidates.side_effect = [
            [("limgrave", "Limgrave"), ("limgrave_east", "Limgrave - East")],  # Source
            [("stormveil", "Stormveil Castle")],  # Target
        ]
        mock_resolver.lookup_by_display_name.return_value = "stormveil"

        discovery_result = DiscoveryResult(origin="Limgrave - East")
        discovery_result.main_links = [
            DiscoveredLink("Limgrave - East", "Stormveil Castle", "random")
        ]

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch(
                "fogtracker.websocket.mod.find_all_matching_zone_pairs_by_ids",
                return_value=[
                    (
                        "limgrave_east",
                        "stormveil",
                        {
                            "id": "link3",
                            "source": "Limgrave - East",
                            "source_id": "limgrave_east",
                            "target": "Stormveil Castle",
                            "target_id": "stormveil",
                            "type": "random",
                        },
                    )
                ],
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
                    "source_map_id": "m60_42_36_00",
                    "target_map_id": "m10_00_00_00",
                    "source_pos": {"x": 100, "y": 50, "z": 200},
                    "target_pos": {"x": 200, "y": 60, "z": 300},
                    "source_zone": "Limgrave - East",  # Should prioritize limgrave_east
                }
            )

            # Verify source_zone caused filtering: only limgrave_east should remain
            call_args = mock_find.call_args[0]
            source_candidates = call_args[1]
            assert source_candidates == [("limgrave_east", "Limgrave - East")]

    @pytest.mark.asyncio
    async def test_source_zone_id_filters_to_matching_key(
        self, mock_client, mock_manager, zone_links_ambiguous
    ):
        """When source_zone_id matches a candidate key, filter to only that candidate."""
        mock_game = self._make_mock_game(zone_links_ambiguous)
        mock_resolver = MagicMock()
        mock_resolver.resolve_by_col.return_value = (None, None)
        mock_resolver.resolve_all_candidates.side_effect = [
            [("limgrave", "Limgrave"), ("limgrave_east", "Limgrave - East")],  # Source
            [("stormveil", "Stormveil Castle")],  # Target
        ]
        mock_resolver.lookup_by_display_name.return_value = "stormveil"

        discovery_result = DiscoveryResult(origin="Limgrave - East")
        discovery_result.main_links = [
            DiscoveredLink("Limgrave - East", "Stormveil Castle", "random")
        ]

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch(
                "fogtracker.websocket.mod.find_all_matching_zone_pairs_by_ids",
                return_value=[
                    (
                        "limgrave_east",
                        "stormveil",
                        {
                            "id": "link3",
                            "source": "Limgrave - East",
                            "source_id": "limgrave_east",
                            "target": "Stormveil Castle",
                            "target_id": "stormveil",
                            "type": "random",
                        },
                    )
                ],
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
                    "source_map_id": "m60_42_36_00",
                    "target_map_id": "m10_00_00_00",
                    "source_pos": {"x": 100, "y": 50, "z": 200},
                    "target_pos": {"x": 200, "y": 60, "z": 300},
                    "source_zone_id": "limgrave_east",  # Should prioritize by key
                }
            )

            # Verify source_zone_id caused filtering: only limgrave_east should remain
            call_args = mock_find.call_args[0]
            source_candidates = call_args[1]
            assert source_candidates == [("limgrave_east", "Limgrave - East")]

    @pytest.mark.asyncio
    async def test_source_zone_no_match_keeps_original_order(
        self, mock_client, mock_manager, zone_links_ambiguous
    ):
        """When source_zone doesn't match any candidate, original order is kept."""
        mock_game = self._make_mock_game(zone_links_ambiguous)
        mock_resolver = MagicMock()
        mock_resolver.resolve_by_col.return_value = (None, None)
        mock_resolver.resolve_all_candidates.side_effect = [
            [("limgrave", "Limgrave"), ("limgrave_east", "Limgrave - East")],  # Source
            [("stormveil", "Stormveil Castle")],  # Target
        ]
        mock_resolver.lookup_by_display_name.return_value = "stormveil"

        discovery_result = DiscoveryResult(origin="Limgrave")
        discovery_result.main_links = [DiscoveredLink("Limgrave", "Stormveil Castle", "random")]

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch(
                "fogtracker.websocket.mod.find_all_matching_zone_pairs_by_ids",
                return_value=[
                    (
                        "limgrave",
                        "stormveil",
                        {
                            "id": "link1",
                            "source": "Limgrave",
                            "source_id": "limgrave",
                            "target": "Stormveil Castle",
                            "target_id": "stormveil",
                            "type": "random",
                        },
                    )
                ],
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
                    "source_map_id": "m60_42_36_00",
                    "target_map_id": "m10_00_00_00",
                    "source_pos": {"x": 100, "y": 50, "z": 200},
                    "target_pos": {"x": 200, "y": 60, "z": 300},
                    "source_zone": "Caelid",  # Doesn't match any source candidate
                }
            )

            # Original order should be preserved (limgrave first)
            call_args = mock_find.call_args[0]
            source_candidates = call_args[1]
            assert source_candidates[0] == ("limgrave", "Limgrave")
            assert source_candidates[1] == ("limgrave_east", "Limgrave - East")

    @pytest.mark.asyncio
    async def test_source_zone_not_provided_uses_original_order(
        self, mock_client, mock_manager, zone_links_ambiguous
    ):
        """When source_zone is not provided, candidates stay in original order."""
        mock_game = self._make_mock_game(zone_links_ambiguous)
        mock_resolver = MagicMock()
        mock_resolver.resolve_by_col.return_value = (None, None)
        mock_resolver.resolve_all_candidates.side_effect = [
            [("limgrave", "Limgrave"), ("limgrave_east", "Limgrave - East")],  # Source
            [("stormveil", "Stormveil Castle")],  # Target
        ]
        mock_resolver.lookup_by_display_name.return_value = "stormveil"

        discovery_result = DiscoveryResult(origin="Limgrave")
        discovery_result.main_links = [DiscoveredLink("Limgrave", "Stormveil Castle", "random")]

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch(
                "fogtracker.websocket.mod.find_all_matching_zone_pairs_by_ids",
                return_value=[
                    (
                        "limgrave",
                        "stormveil",
                        {
                            "id": "link1",
                            "source": "Limgrave",
                            "source_id": "limgrave",
                            "target": "Stormveil Castle",
                            "target_id": "stormveil",
                            "type": "random",
                        },
                    )
                ],
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
                    "source_map_id": "m60_42_36_00",
                    "target_map_id": "m10_00_00_00",
                    "source_pos": {"x": 100, "y": 50, "z": 200},
                    "target_pos": {"x": 200, "y": 60, "z": 300},
                    # No source_zone or source_zone_id
                }
            )

            # Original order should be preserved
            call_args = mock_find.call_args[0]
            source_candidates = call_args[1]
            assert source_candidates[0] == ("limgrave", "Limgrave")
            assert source_candidates[1] == ("limgrave_east", "Limgrave - East")


# =============================================================================
# TestZoneKeyInResponses
# =============================================================================


class TestZoneKeyInResponses:
    """Tests for zone_id fields in server responses.

    The server should include zone_id (internal name) alongside zone (display name)
    in discovery_v2_ack and zone_query_ack responses.
    """

    def _make_mock_game(self, zone_links, discovered_links=None):
        """Helper to create a mock game object."""
        game = MagicMock()
        game.zone_links = zone_links
        game.discovered_zone_links = discovered_links or []
        game.entity_mapping = None
        game.zones = {}
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
    async def test_zone_query_ack_includes_zone_id(self, mock_client):
        """zone_query_ack should include zone_id alongside zone."""
        zone_links = [
            {
                "id": "link1",
                "source": "Limgrave",
                "source_id": "limgrave",
                "target": "Stormveil Castle",
                "target_id": "stormveil_castle",
                "type": "random",
            }
        ]
        mock_game = self._make_mock_game(zone_links, [{"zone_link_id": "link1"}])

        mock_resolver = MagicMock()
        mock_resolver.resolve_by_col.return_value = ("limgrave", "Limgrave")
        mock_resolver.resolve_all_candidates.return_value = [("limgrave", "Limgrave")]
        mock_resolver.lookup_by_display_name.return_value = "limgrave"

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch("fogtracker.websocket.mod.compute_zone_exits", return_value=[]),
            patch("fogtracker.websocket.mod.get_zone_scaling", return_value=None),
        ):
            self._setup_db_mock(mock_session, mock_game)

            await mock_client._handle_zone_query(
                {
                    "map_id": "m60_42_36_00",
                    "pos": {"x": 100, "y": 50, "z": 200},
                    "play_region_id": 0x100000,
                }
            )

        call_args = mock_client.send.call_args[0][0]
        assert call_args["type"] == "zone_query_ack"
        assert call_args["zone"] == "Limgrave"
        assert call_args["zone_id"] == "limgrave"

    @pytest.mark.asyncio
    async def test_zone_query_ack_zone_id_null_when_zone_null(self, mock_client):
        """zone_id should be None when zone is null (early return path)."""
        zone_links = []
        mock_game = self._make_mock_game(zone_links)

        mock_resolver = MagicMock()
        mock_resolver.resolve_by_col.return_value = (None, None)
        mock_resolver.resolve_all_candidates.return_value = []

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch("fogtracker.websocket.mod.compute_zone_exits", return_value=[]),
            patch("fogtracker.websocket.mod.get_zone_scaling", return_value=None),
        ):
            self._setup_db_mock(mock_session, mock_game)

            await mock_client._handle_zone_query(
                {
                    "map_id": "m99_99_99_99",  # Unknown map
                    "pos": {"x": 100, "y": 50, "z": 200},
                }
            )

        call_args = mock_client.send.call_args[0][0]
        assert call_args["type"] == "zone_query_ack"
        assert call_args["zone"] is None
        assert call_args["zone_id"] is None

    @pytest.mark.asyncio
    async def test_discovery_v2_ack_includes_current_zone_id(self, mock_client, mock_manager):
        """discovery_v2_ack should include current_zone_id alongside current_zone."""
        zone_links = [
            {
                "id": "link1",
                "source": "Limgrave",
                "source_id": "limgrave",
                "target": "Stormveil Castle",
                "target_id": "stormveil",
                "type": "random",
            }
        ]
        mock_game = self._make_mock_game(zone_links)

        mock_resolver = MagicMock()
        mock_resolver.resolve_by_col.return_value = (None, None)
        mock_resolver.resolve_all_candidates.side_effect = [
            [("limgrave", "Limgrave")],  # Source
            [("stormveil", "Stormveil Castle")],  # Target
        ]
        mock_resolver.lookup_by_display_name.return_value = "stormveil"

        discovery_result = DiscoveryResult(origin="Limgrave")
        discovery_result.main_links = [DiscoveredLink("Limgrave", "Stormveil Castle", "random")]

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch("fogtracker.websocket.mod.get_resolver", return_value=mock_resolver),
            patch(
                "fogtracker.websocket.mod.find_all_matching_zone_pairs_by_ids",
                return_value=[
                    (
                        "limgrave",
                        "stormveil_castle",
                        {
                            "id": "link1",
                            "source": "Limgrave",
                            "source_id": "limgrave",
                            "target": "Stormveil Castle",
                            "target_id": "stormveil_castle",
                            "type": "random",
                        },
                    )
                ],
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
            patch("fogtracker.websocket.mod.expand_discovered_links", return_value=[]),
            patch("fogtracker.websocket.mod.get_zone_scaling", return_value=None),
            patch("fogtracker.websocket.mod.manager", mock_manager),
        ):
            self._setup_db_mock(mock_session, mock_game)

            await mock_client._handle_discovery_v2(
                {
                    "source_map_id": "m60_42_36_00",
                    "target_map_id": "m10_00_00_00",
                    "source_pos": {"x": 100, "y": 50, "z": 200},
                    "target_pos": {"x": 200, "y": 60, "z": 300},
                }
            )

        call_args = mock_client.send.call_args[0][0]
        assert call_args["type"] == "discovery_v2_ack"
        assert call_args["current_zone"] == "Stormveil Castle"
        assert call_args["current_zone_id"] == "stormveil"


class TestTagUpdateHandler:
    """Tests for _handle_tag_update method."""

    @pytest.mark.asyncio
    async def test_tag_update_missing_zone_id(self, mock_client):
        """Should ignore updates without zone_id."""
        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch(
                "fogtracker.websocket.mod.manager.broadcast_to_all",
                new_callable=AsyncMock,
            ) as mock_broadcast,
        ):
            await mock_client._handle_tag_update({"tags": ["important"]})

        mock_session.assert_not_called()
        mock_broadcast.assert_not_called()


# =============================================================================
# TestGameStatsUpdateHandler
# =============================================================================


class TestGameStatsUpdateHandler:
    """Tests for _handle_game_stats_update method."""

    @pytest.mark.asyncio
    async def test_game_stats_update_valid(self, mock_client):
        """Should update stats, send ack, and broadcast."""
        mock_game = MagicMock()
        mock_game.game_stats = {}

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch(
                "fogtracker.websocket.mod.manager.broadcast_to_all",
                new_callable=AsyncMock,
            ) as mock_broadcast,
        ):
            mock_db = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_game
            mock_db.execute.return_value = mock_result
            mock_session.return_value.__aenter__.return_value = mock_db

            await mock_client._handle_game_stats_update(
                {
                    "great_runes": ["Godrick", "Radahn"],
                    "kindling_count": 5,
                    "death_count": 10,
                    "play_time_ms": 3600000,
                }
            )

            # Check ack was sent
            mock_client.send.assert_called_once()
            ack = mock_client.send.call_args[0][0]
            assert ack["type"] == "game_stats_update_ack"

            # Check database was updated
            assert mock_game.game_stats == {
                "great_runes": ["Godrick", "Radahn"],
                "kindling_count": 5,
                "death_count": 10,
                "play_time_ms": 3600000,
            }
            mock_db.commit.assert_called_once()

            # Check broadcast was called
            mock_broadcast.assert_called_once()
            broadcast_args = mock_broadcast.call_args[0]
            assert broadcast_args[0] == mock_client.game_id
            assert broadcast_args[1]["type"] == "game_stats_update"
            assert broadcast_args[1]["great_runes"] == ["Godrick", "Radahn"]
            assert broadcast_args[1]["death_count"] == 10

    @pytest.mark.asyncio
    async def test_game_stats_update_invalid_rune(self, mock_client):
        """Should reject unknown rune names."""
        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch(
                "fogtracker.websocket.mod.manager.broadcast_to_all",
                new_callable=AsyncMock,
            ) as mock_broadcast,
        ):
            await mock_client._handle_game_stats_update(
                {
                    "great_runes": ["UnknownRune"],
                    "kindling_count": 0,
                    "death_count": 0,
                    "play_time_ms": 0,
                }
            )

            # No ack should be sent
            mock_client.send.assert_not_called()
            mock_session.assert_not_called()
            mock_broadcast.assert_not_called()

    @pytest.mark.asyncio
    async def test_game_stats_update_too_many_runes(self, mock_client):
        """Should reject more than 7 runes."""
        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch(
                "fogtracker.websocket.mod.manager.broadcast_to_all",
                new_callable=AsyncMock,
            ) as mock_broadcast,
        ):
            await mock_client._handle_game_stats_update(
                {
                    "great_runes": ["Godrick"] * 8,  # 8 runes, max is 7
                    "kindling_count": 0,
                    "death_count": 0,
                    "play_time_ms": 0,
                }
            )

            mock_client.send.assert_not_called()
            mock_session.assert_not_called()
            mock_broadcast.assert_not_called()

    @pytest.mark.asyncio
    async def test_game_stats_update_invalid_great_runes_type(self, mock_client):
        """Should reject if great_runes is not a list."""
        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch(
                "fogtracker.websocket.mod.manager.broadcast_to_all",
                new_callable=AsyncMock,
            ) as mock_broadcast,
        ):
            await mock_client._handle_game_stats_update(
                {
                    "great_runes": "Godrick",  # String instead of list
                    "kindling_count": 0,
                    "death_count": 0,
                    "play_time_ms": 0,
                }
            )

            mock_client.send.assert_not_called()
            mock_session.assert_not_called()
            mock_broadcast.assert_not_called()

    @pytest.mark.asyncio
    async def test_game_stats_update_negative_values(self, mock_client):
        """Should reject negative numeric values."""
        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch(
                "fogtracker.websocket.mod.manager.broadcast_to_all",
                new_callable=AsyncMock,
            ) as mock_broadcast,
        ):
            await mock_client._handle_game_stats_update(
                {
                    "great_runes": [],
                    "kindling_count": -1,
                    "death_count": 0,
                    "play_time_ms": 0,
                }
            )

            mock_client.send.assert_not_called()
            mock_session.assert_not_called()
            mock_broadcast.assert_not_called()

    @pytest.mark.asyncio
    async def test_game_stats_update_empty_runes(self, mock_client):
        """Should accept empty great_runes list."""
        mock_game = MagicMock()
        mock_game.game_stats = {}

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch(
                "fogtracker.websocket.mod.manager.broadcast_to_all",
                new_callable=AsyncMock,
            ) as mock_broadcast,
        ):
            mock_db = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_game
            mock_db.execute.return_value = mock_result
            mock_session.return_value.__aenter__.return_value = mock_db

            await mock_client._handle_game_stats_update(
                {
                    "great_runes": [],
                    "kindling_count": 0,
                    "death_count": 42,
                    "play_time_ms": 1000,
                }
            )

            # Should succeed
            mock_client.send.assert_called_once()
            assert mock_game.game_stats["death_count"] == 42
            mock_broadcast.assert_called_once()

    @pytest.mark.asyncio
    async def test_game_stats_update_all_runes(self, mock_client):
        """Should accept all 7 valid great runes."""
        mock_game = MagicMock()
        mock_game.game_stats = {}

        all_runes = ["Godrick", "Radahn", "Morgott", "Rykard", "Mohg", "Malenia", "Unborn"]

        with (
            patch("fogtracker.websocket.mod.async_session") as mock_session,
            patch(
                "fogtracker.websocket.mod.manager.broadcast_to_all",
                new_callable=AsyncMock,
            ) as mock_broadcast,
        ):
            mock_db = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_game
            mock_db.execute.return_value = mock_result
            mock_session.return_value.__aenter__.return_value = mock_db

            await mock_client._handle_game_stats_update(
                {
                    "great_runes": all_runes,
                    "kindling_count": 10,
                    "death_count": 100,
                    "play_time_ms": 7200000,
                }
            )

            mock_client.send.assert_called_once()
            assert mock_game.game_stats["great_runes"] == all_runes
            mock_broadcast.assert_called_once()
