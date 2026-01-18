"""Unit tests for game_logic module.

Tests for discovery result formatting and related utilities.
"""

import pytest

from fogtracker.game_logic import (
    DiscoveredLink,
    DiscoveryResult,
    format_discovery_summary,
    format_ingame_display,
    format_undiscovery_summary,
)


class TestDiscoveredLink:
    """Tests for DiscoveredLink dataclass."""

    def test_create_random_link(self):
        link = DiscoveredLink(source_name="Zone A", target_name="Zone B", link_type="random")
        assert link.source_name == "Zone A"
        assert link.target_name == "Zone B"
        assert link.source_id == "Zone A"
        assert link.target_id == "Zone B"
        assert link.link_type == "random"

    def test_create_preexisting_link(self):
        link = DiscoveredLink(source_name="Zone A", target_name="Zone B", link_type="preexisting")
        assert link.link_type == "preexisting"


class TestDiscoveryResult:
    """Tests for DiscoveryResult dataclass."""

    def test_empty_result(self):
        result = DiscoveryResult(origin="Zone A")
        assert result.origin == "Zone A"
        assert result.main_links == []
        assert result.backprop_links == []
        assert result.forward_links == []
        assert result.total_count() == 0
        assert result.all_links() == []

    def test_total_count(self):
        result = DiscoveryResult(origin="Zone A")
        result.main_links.append(DiscoveredLink("A", "B", "random"))
        result.backprop_links.append(DiscoveredLink("START", "A", "preexisting"))
        result.forward_links.append(DiscoveredLink("B", "C", "preexisting"))
        result.forward_links.append(DiscoveredLink("C", "D", "preexisting"))
        assert result.total_count() == 4

    def test_all_links_order(self):
        """all_links() returns backprop first, then main, then forward."""
        result = DiscoveryResult(origin="Zone A")
        result.backprop_links.append(DiscoveredLink("START", "A", "preexisting"))
        result.main_links.append(DiscoveredLink("A", "B", "random"))
        result.forward_links.append(DiscoveredLink("B", "C", "preexisting"))

        links = result.all_links()
        assert len(links) == 3
        assert links[0] == {
            "source_name": "START",
            "source_id": "START",
            "target_name": "A",
            "target_id": "A",
        }
        assert links[1] == {
            "source_name": "A",
            "source_id": "A",
            "target_name": "B",
            "target_id": "B",
        }
        assert links[2] == {
            "source_name": "B",
            "source_id": "B",
            "target_name": "C",
            "target_id": "C",
        }


class TestFormatDiscoverySummary:
    """Tests for format_discovery_summary function."""

    def test_simple_discovery_no_propagation(self):
        result = DiscoveryResult(origin="Limgrave")
        result.main_links.append(DiscoveredLink("Limgrave", "Stormveil Castle", "random"))

        summary = format_discovery_summary(result, "mod")

        assert "Discovery Summary" in summary
        assert "Origin:     Limgrave" in summary
        assert "Limgrave ───> Stormveil Castle" in summary
        assert "Total: 1 new link" in summary
        # No propagation sections
        assert "Back-propagation" not in summary
        assert "Forward-propagation" not in summary

    def test_discovery_with_forward_propagation(self):
        result = DiscoveryResult(origin="Zone A")
        result.main_links.append(DiscoveredLink("Zone A", "Zone B", "random"))
        result.forward_links.append(DiscoveredLink("Zone B", "Zone C", "preexisting"))
        result.forward_links.append(DiscoveredLink("Zone C", "Zone D", "preexisting"))

        summary = format_discovery_summary(result, "mod")

        assert "Forward-propagation (2)" in summary
        assert "Zone B ---> Zone C" in summary
        assert "Zone C ---> Zone D" in summary
        assert "Total: 3 new links" in summary

    def test_discovery_with_back_propagation(self):
        result = DiscoveryResult(origin="Zone C")
        result.backprop_links.append(DiscoveredLink("START", "Zone A", "preexisting"))
        result.backprop_links.append(DiscoveredLink("Zone A", "Zone B", "random"))
        result.backprop_links.append(DiscoveredLink("Zone B", "Zone C", "preexisting"))
        result.main_links.append(DiscoveredLink("Zone C", "Zone D", "random"))

        summary = format_discovery_summary(result, "mod")

        assert "Back-propagation (3)" in summary
        assert "START ---> Zone A" in summary
        assert "Zone A ───> Zone B" in summary  # random link
        assert "Zone B ---> Zone C" in summary  # preexisting link
        assert "Total: 4 new links" in summary

    def test_random_vs_preexisting_arrows(self):
        """Random links use ───>, preexisting use --->."""
        result = DiscoveryResult(origin="A")
        result.main_links.append(DiscoveredLink("A", "B", "random"))
        result.forward_links.append(DiscoveredLink("B", "C", "preexisting"))

        summary = format_discovery_summary(result, "mod")

        assert "A ───> B" in summary  # random: solid line
        assert "B ---> C" in summary  # preexisting: dashed line

    def test_with_progress_stats(self):
        result = DiscoveryResult(origin="Zone A")
        result.main_links.append(DiscoveredLink("Zone A", "Zone B", "random"))

        summary = format_discovery_summary(result, "mod", total_discovered=42, total_links=180)

        assert "Progress: 42/180 (23.3%)" in summary

    def test_without_progress_stats(self):
        result = DiscoveryResult(origin="Zone A")
        result.main_links.append(DiscoveredLink("Zone A", "Zone B", "random"))

        summary = format_discovery_summary(result, "mod")

        assert "Progress:" not in summary

    def test_with_warp_type_and_resolution_method(self):
        """Test that warp_type and resolution_method are displayed."""
        result = DiscoveryResult(origin="Limgrave")
        result.main_links.append(DiscoveredLink("Limgrave", "Stormveil Castle", "random"))

        summary = format_discovery_summary(
            result, "mod", warp_type="FogGate", resolution_method="zone_keys"
        )

        assert "Warp type:  FogGate" in summary
        assert "Resolved:   zone_keys" in summary

    def test_warp_type_only(self):
        """Test that warp_type is displayed without resolution_method."""
        result = DiscoveryResult(origin="Zone A")
        result.main_links.append(DiscoveredLink("Zone A", "Zone B", "random"))

        summary = format_discovery_summary(result, "mod", warp_type="Medal")

        assert "Warp type:  Medal" in summary
        assert "Resolved:" not in summary

    def test_full_scenario(self):
        """Test a complete discovery scenario with all propagation types."""
        result = DiscoveryResult(origin="Limgrave (Field)")
        # Back-propagation
        result.backprop_links.append(
            DiscoveredLink("START", "Limgrave (First Step)", "preexisting")
        )
        result.backprop_links.append(
            DiscoveredLink("Limgrave (First Step)", "Limgrave (Field)", "random")
        )
        # Main link
        result.main_links.append(DiscoveredLink("Limgrave (Field)", "Stormveil Castle", "random"))
        # Forward propagation
        result.forward_links.append(
            DiscoveredLink("Stormveil Castle", "Stormveil Castle (Rampart)", "preexisting")
        )

        summary = format_discovery_summary(result, "mod", total_discovered=15, total_links=180)

        # Check structure
        assert "╭─ Discovery Summary" in summary
        assert "╰─ Total:" in summary

        # Check origin
        assert "Origin:     Limgrave (Field)" in summary

        # Check main link
        assert "Link:       Limgrave (Field) ───> Stormveil Castle" in summary

        # Check back-propagation section
        assert "├─ Back-propagation (2):" in summary
        assert "◂ START ---> Limgrave (First Step)" in summary
        assert "◂ Limgrave (First Step) ───> Limgrave (Field)" in summary

        # Check forward-propagation section
        assert "├─ Forward-propagation (1):" in summary
        assert "▸ Stormveil Castle ---> Stormveil Castle (Rampart)" in summary

        # Check footer
        assert "Total: 4 new links" in summary
        assert "Progress: 15/180 (8.3%)" in summary


class TestFormatUndiscoverySummary:
    """Tests for format_undiscovery_summary function."""

    def test_single_zone_undiscovery(self):
        summary = format_undiscovery_summary("Stormveil Castle", ["Stormveil Castle"])

        assert "Undiscovery Summary" in summary
        assert "Target:     Stormveil Castle" in summary
        assert "Total: 1 zone removed" in summary
        # No cascade section when only the target is removed
        assert "Cascade" not in summary

    def test_undiscovery_with_cascade(self):
        removed = ["Stormveil Castle", "Stormveil Castle (Rampart)", "Stormveil Castle (Hall)"]
        summary = format_undiscovery_summary("Stormveil Castle", removed)

        assert "Target:     Stormveil Castle" in summary
        assert "├─ Cascade (2):" in summary
        assert "✗ Stormveil Castle (Rampart)" in summary
        assert "✗ Stormveil Castle (Hall)" in summary
        assert "Total: 3 zones removed" in summary

    def test_with_progress_stats(self):
        summary = format_undiscovery_summary(
            "Zone A", ["Zone A"], total_discovered=10, total_links=180
        )

        assert "Progress: 10/180 (5.6%)" in summary

    def test_without_progress_stats(self):
        summary = format_undiscovery_summary("Zone A", ["Zone A"])

        assert "Progress:" not in summary

    def test_full_scenario(self):
        """Test a complete undiscovery scenario with cascade."""
        removed = ["Limgrave (Field)", "Stormveil Castle", "Stormveil Castle (Rampart)"]
        summary = format_undiscovery_summary(
            "Limgrave (Field)", removed, total_discovered=5, total_links=180
        )

        # Check structure
        assert "╭─ Undiscovery Summary" in summary
        assert "╰─ Total:" in summary

        # Check target
        assert "Target:     Limgrave (Field)" in summary

        # Check cascade section
        assert "├─ Cascade (2):" in summary
        assert "✗ Stormveil Castle" in summary
        assert "✗ Stormveil Castle (Rampart)" in summary

        # Check footer
        assert "Total: 3 zones removed" in summary
        assert "Progress: 5/180 (2.8%)" in summary


class TestFormatIngameDisplay:
    """Tests for format_ingame_display function."""

    def test_simple_display(self):
        exits = [
            {"target": "Stormveil Castle", "from_zone": None, "description": "at the main gate"},
        ]
        stats = {"discovered": 5, "total": 180}

        display = format_ingame_display("Limgrave", exits, stats)

        assert "In-game Display" in display
        assert "Limgrave • 5/180" in display
        assert "→ Stormveil Castle" in display
        assert "at the main gate" in display
        assert "[from" not in display  # No from_zone

    def test_display_with_from_zone(self):
        exits = [
            {
                "target": "Capital Outskirts",
                "from_zone": "Cave of Knowledge",
                "description": "before the boss",
            },
        ]
        stats = {"discovered": 10, "total": 180}

        display = format_ingame_display("Cave of Knowledge", exits, stats)

        assert "→ Capital Outskirts [from Cave of Knowledge]" in display
        assert "before the boss" in display

    def test_display_with_undiscovered_exit(self):
        exits = [
            {"target": "???", "from_zone": None, "description": "near the cliff"},
        ]
        stats = {"discovered": 3, "total": 180}

        display = format_ingame_display("Limgrave", exits, stats)

        assert "→ ???" in display
        assert "near the cliff" in display

    def test_display_with_no_exits(self):
        stats = {"discovered": 5, "total": 180}

        display = format_ingame_display("Roundtable Hold", [], stats)

        assert "No exits available" in display

    def test_display_multiple_exits(self):
        exits = [
            {"target": "Chapel of Anticipation", "from_zone": None, "description": "at the back"},
            {"target": "???", "from_zone": "Stormveil", "description": "before the boss"},
            {"target": "Liurnia", "from_zone": None, "description": ""},
        ]
        stats = {"discovered": 42, "total": 180}

        display = format_ingame_display("Cave of Knowledge", exits, stats)

        assert "Cave of Knowledge • 42/180" in display
        assert "├─ Exits:" in display
        assert "→ Chapel of Anticipation" in display
        assert "at the back" in display
        assert "→ ??? [from Stormveil]" in display
        assert "before the boss" in display
        assert "→ Liurnia" in display

    def test_full_scenario(self):
        """Test a realistic in-game display scenario."""
        exits = [
            {
                "target": "Chapel of Anticipation",
                "from_zone": None,
                "description": "at the back entrance from the Seaside Ruins beach",
            },
            {
                "target": "Capital Outskirts - Sealed Tunnel - Onyx Lord",
                "from_zone": "Cave of Knowledge",
                "description": "before Soldier of Godrick's arena",
            },
            {
                "target": "???",
                "from_zone": None,
                "description": "at the door to Stranded Graveyard",
            },
        ]
        stats = {"discovered": 5, "total": 165}

        display = format_ingame_display("Cave of Knowledge - From Seaside Ruins", exits, stats)

        # Check header
        assert "╭─ In-game Display" in display
        assert "Cave of Knowledge - From Seaside Ruins • 5/165" in display

        # Check exits
        assert "→ Chapel of Anticipation" in display
        assert "at the back entrance from the Seaside Ruins beach" in display
        assert "→ Capital Outskirts - Sealed Tunnel - Onyx Lord [from Cave of Knowledge]" in display
        assert "before Soldier of Godrick's arena" in display
        assert "→ ???" in display
        assert "at the door to Stranded Graveyard" in display

        # Check footer
        assert "╰─" in display


class TestParallelLinksDiscovery:
    """Tests for parallel links discovery (multiple fog gates between same zones).

    These tests verify that when discovering a link between two zones that have
    multiple parallel connections, ALL parallel links are discovered together.
    """

    @pytest.fixture
    def mock_game(self, parallel_links_zone_pairs):
        """Create a mock game with parallel links."""
        from unittest.mock import MagicMock
        from uuid import uuid4

        game = MagicMock()
        game.id = uuid4()
        game.zone_links = parallel_links_zone_pairs
        game.discovered_zone_links = []
        game.starting_zone_id = "chapel_start"
        return game

    @pytest.fixture
    def mock_db(self, mock_game):
        """Create a mock database session."""
        from unittest.mock import AsyncMock, MagicMock

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = mock_game
        db.execute.return_value = result
        db.refresh = AsyncMock()
        db.flush = AsyncMock()
        return db

    @pytest.mark.asyncio
    async def test_discovers_all_parallel_links_between_same_zones(
        self, mock_db, mock_game, parallel_links_zone_pairs
    ):
        """When discovering dragonbarrow -> caelid_tower, both parallel links should be discovered."""
        from fogtracker.game_logic import propagate_discovery

        # First, discover the path to dragonbarrow (so it's accessible)
        mock_game.discovered_zone_links = [{"zone_link_id": "link-start-dragonbarrow"}]

        # Now discover one of the parallel links (dragonbarrow -> caelid_tower)
        await propagate_discovery(
            mock_db,
            mock_game.id,
            source_id="dragonbarrow",
            target_id="caelid_tower",
            discovered_by="test",
        )

        # Get all discovered zone_link_ids
        discovered_ids = {dl.get("zone_link_id") for dl in mock_game.discovered_zone_links}

        # Both parallel links between dragonbarrow and caelid_tower should be discovered
        assert "link-parallel-1" in discovered_ids, "Middle entrance should be discovered"
        assert "link-parallel-2" in discovered_ids, "Right entrance should be discovered"

        # The link to caelid_tower_boss is a different target, so it shouldn't be discovered
        assert (
            "link-parallel-3" not in discovered_ids
        ), "Left entrance (to boss) is different target"

    @pytest.mark.asyncio
    async def test_parallel_links_counted_correctly_in_result(
        self, mock_db, mock_game, parallel_links_zone_pairs
    ):
        """Discovery result should count all parallel links discovered."""
        from fogtracker.game_logic import propagate_discovery

        # Setup: dragonbarrow is already accessible
        mock_game.discovered_zone_links = [{"zone_link_id": "link-start-dragonbarrow"}]

        result = await propagate_discovery(
            mock_db,
            mock_game.id,
            source_id="dragonbarrow",
            target_id="caelid_tower",
            discovered_by="test",
        )

        # Should have 2 parallel links + preexisting propagation
        # main_links should have 1 (the first parallel link)
        # forward_links should have 1 (the second parallel link) + preexisting
        assert len(result.main_links) >= 1
        assert result.total_count() >= 2  # At least 2 parallel links

    @pytest.mark.asyncio
    async def test_backprop_also_discovers_parallel_links(
        self, mock_db, mock_game, parallel_links_zone_pairs
    ):
        """Back-propagation should also discover all parallel links on the path."""
        from fogtracker.game_logic import propagate_discovery

        # Start with nothing discovered
        mock_game.discovered_zone_links = []

        # Discover from dragonbarrow -> caelid_tower (dragonbarrow not yet accessible)
        # This triggers back-propagation: chapel_start -> dragonbarrow
        await propagate_discovery(
            mock_db,
            mock_game.id,
            source_id="dragonbarrow",
            target_id="caelid_tower",
            discovered_by="test",
        )

        discovered_ids = {dl.get("zone_link_id") for dl in mock_game.discovered_zone_links}

        # The back-propagated link should be discovered
        assert "link-start-dragonbarrow" in discovered_ids

        # Both parallel links should be discovered
        assert "link-parallel-1" in discovered_ids
        assert "link-parallel-2" in discovered_ids

    @pytest.mark.asyncio
    async def test_already_discovered_parallel_links_not_duplicated(
        self, mock_db, mock_game, parallel_links_zone_pairs
    ):
        """If one parallel link is already discovered, discovering again shouldn't duplicate."""
        from fogtracker.game_logic import propagate_discovery

        # Setup: one parallel link already discovered
        mock_game.discovered_zone_links = [
            {"zone_link_id": "link-start-dragonbarrow"},
            {"zone_link_id": "link-parallel-1"},  # Already discovered
        ]

        await propagate_discovery(
            mock_db,
            mock_game.id,
            source_id="dragonbarrow",
            target_id="caelid_tower",
            discovered_by="test",
        )

        # Count occurrences of each link_id
        link_ids = [dl.get("zone_link_id") for dl in mock_game.discovered_zone_links]

        # link-parallel-1 should appear only once (not duplicated)
        assert link_ids.count("link-parallel-1") == 1

        # link-parallel-2 should now be discovered
        assert "link-parallel-2" in link_ids


class TestBidirectionalBackpropSkip:
    """Tests for skipping back-propagation when discovering bidirectional links.

    When discovering a bidirectional link where:
    - Source is NOT accessible from START
    - Target IS accessible from START
    - Link is bidirectional (is_one_way=False)

    Back-propagation should be SKIPPED because the source will be accessible
    via the bidirectional link to the already-accessible target.

    This is a regression test for the bug where unnecessary back-propagation
    was triggered when discovering "Dragon's Pit Boss -> Elden Throne" even
    though Elden Throne was already accessible and the link was bidirectional.
    """

    @pytest.fixture
    def mock_game_bidir(self, bidirectional_backprop_zone_pairs):
        """Create a mock game with bidirectional link setup."""
        from unittest.mock import MagicMock
        from uuid import uuid4

        game = MagicMock()
        game.id = uuid4()
        game.zone_links = bidirectional_backprop_zone_pairs
        game.discovered_zone_links = []
        game.starting_zone_id = "chapel_start"
        return game

    @pytest.fixture
    def mock_game_one_way(self, one_way_backprop_zone_pairs):
        """Create a mock game with one-way link setup."""
        from unittest.mock import MagicMock
        from uuid import uuid4

        game = MagicMock()
        game.id = uuid4()
        game.zone_links = one_way_backprop_zone_pairs
        game.discovered_zone_links = []
        game.starting_zone_id = "chapel_start"
        return game

    @pytest.fixture
    def mock_db_bidir(self, mock_game_bidir):
        """Create a mock database session for bidirectional test."""
        from unittest.mock import AsyncMock, MagicMock

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = mock_game_bidir
        db.execute.return_value = result
        db.refresh = AsyncMock()
        db.flush = AsyncMock()
        return db

    @pytest.fixture
    def mock_db_one_way(self, mock_game_one_way):
        """Create a mock database session for one-way test."""
        from unittest.mock import AsyncMock, MagicMock

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = mock_game_one_way
        db.execute.return_value = result
        db.refresh = AsyncMock()
        db.flush = AsyncMock()
        return db

    @pytest.mark.asyncio
    async def test_bidirectional_link_skips_backprop_when_target_accessible(
        self, mock_db_bidir, mock_game_bidir
    ):
        """Bidirectional link should NOT trigger backprop when target is accessible.

        Setup:
        - Chapel -> Elden Throne is already discovered (target accessible)
        - Discover Dragon Pit -> Elden Throne (source NOT accessible, target accessible)
        - Link is bidirectional

        Expected:
        - NO back-propagation (academy path should NOT be discovered)
        - Only the main link should be discovered
        """
        from fogtracker.game_logic import propagate_discovery

        # Elden Throne is already accessible via Chapel
        mock_game_bidir.discovered_zone_links = [{"zone_link_id": "link-chapel-throne"}]

        result = await propagate_discovery(
            mock_db_bidir,
            mock_game_bidir.id,
            source_id="gravesite_dragonpit_boss",
            target_id="leyndell2_throne",
            discovered_by="test",
        )

        discovered_ids = {dl.get("zone_link_id") for dl in mock_game_bidir.discovered_zone_links}

        # Main link should be discovered
        assert "link-dragonpit-throne" in discovered_ids

        # Back-propagation path should NOT be discovered
        assert (
            "link-chapel-academy" not in discovered_ids
        ), "Academy link should NOT be back-propagated"
        assert (
            "link-academy-dragonpit" not in discovered_ids
        ), "Dragon pit path should NOT be back-propagated"

        # Result should have NO backprop_links
        assert len(result.backprop_links) == 0, "Should have no back-propagated links"

    @pytest.mark.asyncio
    async def test_one_way_link_triggers_backprop_even_when_target_accessible(
        self, mock_db_one_way, mock_game_one_way
    ):
        """One-way link SHOULD trigger backprop even when target is accessible.

        Setup:
        - Chapel -> Elden Throne is already discovered (target accessible)
        - Discover Dragon Pit -> Elden Throne (source NOT accessible, target accessible)
        - Link is ONE-WAY (can't traverse from throne to dragon pit)

        Expected:
        - Back-propagation SHOULD occur (academy path discovered)
        """
        from fogtracker.game_logic import propagate_discovery

        # Elden Throne is already accessible via Chapel
        mock_game_one_way.discovered_zone_links = [{"zone_link_id": "link-chapel-throne"}]

        result = await propagate_discovery(
            mock_db_one_way,
            mock_game_one_way.id,
            source_id="gravesite_dragonpit_boss",
            target_id="leyndell2_throne",
            discovered_by="test",
        )

        discovered_ids = {dl.get("zone_link_id") for dl in mock_game_one_way.discovered_zone_links}

        # Main link should be discovered
        assert "link-dragonpit-throne" in discovered_ids

        # Back-propagation path SHOULD be discovered for one-way link
        assert "link-chapel-academy" in discovered_ids, "Academy link should be back-propagated"
        assert (
            "link-academy-dragonpit" in discovered_ids
        ), "Dragon pit path should be back-propagated"

        # Result should have backprop_links
        assert len(result.backprop_links) > 0, "Should have back-propagated links"

    @pytest.mark.asyncio
    async def test_bidirectional_link_still_backprops_when_target_not_accessible(
        self, mock_db_bidir, mock_game_bidir
    ):
        """Bidirectional link SHOULD trigger backprop when target is NOT accessible.

        Setup:
        - Nothing is discovered yet
        - Discover Dragon Pit -> Elden Throne
        - Both source AND target are NOT accessible

        Expected:
        - Back-propagation SHOULD occur
        """
        from fogtracker.game_logic import propagate_discovery

        # Nothing discovered yet - target is NOT accessible
        mock_game_bidir.discovered_zone_links = []

        result = await propagate_discovery(
            mock_db_bidir,
            mock_game_bidir.id,
            source_id="gravesite_dragonpit_boss",
            target_id="leyndell2_throne",
            discovered_by="test",
        )

        discovered_ids = {dl.get("zone_link_id") for dl in mock_game_bidir.discovered_zone_links}

        # Main link should be discovered
        assert "link-dragonpit-throne" in discovered_ids

        # Back-propagation path SHOULD be discovered when target not accessible
        assert (
            "link-chapel-academy" in discovered_ids or "link-chapel-throne" in discovered_ids
        ), "Some path should be back-propagated when target not accessible"

        # Result should have backprop_links
        assert len(result.backprop_links) > 0, "Should have back-propagated links"
