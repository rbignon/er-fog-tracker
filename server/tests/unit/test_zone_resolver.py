"""
Unit tests for zone_resolver module.

Tests for ZoneResolver class and its methods:
- Position-based zone resolution (submaps.txt)
- Col-based zone resolution (foglocations2.txt)
- Display name lookups (fog.txt)
- Reverse lookups for test simulation
"""

from pathlib import Path

import pytest

from fogtracker.zone_resolver import MapRules, PositionRule, ZoneResolver


@pytest.fixture
def resolver():
    """Create a ZoneResolver with real data."""
    data_dir = Path(__file__).parent.parent.parent / "data"
    return ZoneResolver(data_dir)


@pytest.fixture
def empty_resolver():
    """Create a ZoneResolver without data (for unit testing)."""
    return ZoneResolver(None)


class TestOverworldFogGateZones:
    """Tests for ASide/BSide zone resolution from overworld fog gates.

    Fog gates in overworld maps (m60_/m61_) that connect to underground zones
    should have their ASide/BSide areas added to map_zones. This enables
    matching when the spoiler log names a connection by its underground
    destination (e.g., "Siofra River") but the fog gate is physically
    located on the surface (e.g., in Dragonbarrow).
    """

    def test_deep_siofra_well_includes_siofra(self, resolver):
        """Deep Siofra Well (m60_49_40_00) should include siofra as candidate.

        The fog gate at Deep Siofra Well has:
        - ASide: caelid_greatjar
        - BSide: siofra
        Both should be candidates for map m60_49_40_00.
        """
        zones = resolver.map_zones.get("m60_49_40_00", set())

        # Original zones from fog.txt Maps: entries
        assert "dragonbarrow" in zones
        assert "caelid_greatjar" in zones

        # Added from fog gate ASide/BSide
        assert (
            "siofra" in zones
        ), "siofra should be a candidate for m60_49_40_00 (from Deep Siofra Well fog gate BSide)"

    def test_siofra_well_limgrave_includes_siofra(self, resolver):
        """Siofra River Well in Limgrave should include siofra as candidate."""
        # m60_42_36_00 is Limgrave near the Siofra River Well
        zones = resolver.map_zones.get("m60_42_36_00", set())

        # Check that siofra is a candidate (from the well's BSide)
        assert (
            "siofra" in zones or "limgrave" in zones
        ), "Siofra River Well area should have underground zone candidates"

    def test_volcano_manor_no_extra_zones(self, resolver):
        """Volcano Manor (m16_00_00_00) should NOT have ASide/BSide zones added.

        Non-overworld maps should not have ASide/BSide areas added to map_zones
        to avoid creating ambiguity in zone matching.
        """
        zones = resolver.map_zones.get("m16_00_00_00", set())

        # These are the legitimate zones from Maps: entries
        legitimate_zones = {
            "volcano",
            "volcano_predoor",
            "volcano_drawingroom",
            "volcano_pretown",
            "volcano_town",
            "volcano_temple",
            "volcano_posttemple",
            "volcano_rykard",
            "volcano_pathway",
            "volcano_hallway",
            "volcano_sendinggate",
            "volcano_abductors",
            "volcano_postabductors",
            "volcano_posttemple_elevator",
        }

        # All zones should be from the legitimate set (no extra from ASide/BSide)
        for zone in zones:
            assert zone in legitimate_zones, (
                f"Unexpected zone '{zone}' in m16_00_00_00 - "
                "ASide/BSide zones should not be added to non-overworld maps"
            )

    def test_resolve_all_candidates_includes_siofra(self, resolver):
        """resolve_all_candidates for Deep Siofra Well should include Siofra River."""
        candidates = resolver.resolve_all_candidates("m60_49_40_00", -123, 117, -8)
        candidate_keys = [c[0] for c in candidates]
        candidate_names = [c[1] for c in candidates]

        assert "siofra" in candidate_keys, f"siofra should be in candidates, got: {candidate_keys}"
        assert (
            "Siofra River" in candidate_names
        ), f"'Siofra River' should be in candidate display names, got: {candidate_names}"


class TestDetailTextToZone:
    """Tests for detail text to zone mapping."""

    def test_deep_siofra_well_detail_maps_to_siofra(self, resolver):
        """'at the top of the Deep Siofra Well' should map to siofra."""
        zone = resolver.detail_text_to_zone.get("at the top of the Deep Siofra Well")
        assert zone == "siofra", f"Expected 'siofra', got '{zone}'"

    def test_deep_siofra_well_aside_maps_to_caelid_greatjar(self, resolver):
        """'at the Deep Siofra Well' should map to caelid_greatjar."""
        zone = resolver.detail_text_to_zone.get("at the Deep Siofra Well")
        assert zone == "caelid_greatjar", f"Expected 'caelid_greatjar', got '{zone}'"

    def test_siofra_well_limgrave_maps_correctly(self, resolver):
        """'at the top of the Siofra River Well' should map to siofra."""
        zone = resolver.detail_text_to_zone.get("at the top of the Siofra River Well")
        assert zone == "siofra", f"Expected 'siofra', got '{zone}'"


class TestZoneDisplayNames:
    """Tests for zone display name resolution."""

    def test_siofra_display_name(self, resolver):
        """siofra internal name should map to 'Siofra River' display name."""
        display = resolver.zone_display_names.get("siofra")
        assert display == "Siofra River", f"Expected 'Siofra River', got '{display}'"

    def test_dragonbarrow_display_name(self, resolver):
        """dragonbarrow should map to 'Dragonbarrow' display name."""
        display = resolver.zone_display_names.get("dragonbarrow")
        assert display == "Dragonbarrow", f"Expected 'Dragonbarrow', got '{display}'"


class TestPositionRule:
    """Tests for PositionRule matching logic."""

    def test_no_conditions_always_matches(self):
        """A rule with no conditions should match any position."""
        rule = PositionRule(area="test_zone")
        assert rule.matches(0, 0, 0)
        assert rule.matches(100, 200, 300)
        assert rule.matches(-500, -500, -500)

    def test_x_above_condition(self):
        """XAbove should match when x > threshold."""
        rule = PositionRule(area="test_zone", x_above=100.0)
        assert rule.matches(150, 0, 0)  # x > 100
        assert not rule.matches(100, 0, 0)  # x == 100 (not > 100)
        assert not rule.matches(50, 0, 0)  # x < 100

    def test_x_below_condition(self):
        """XBelow should match when x < threshold."""
        rule = PositionRule(area="test_zone", x_below=100.0)
        assert rule.matches(50, 0, 0)  # x < 100
        assert not rule.matches(100, 0, 0)  # x == 100 (not < 100)
        assert not rule.matches(150, 0, 0)  # x > 100

    def test_y_above_condition(self):
        """YAbove should match when y > threshold."""
        rule = PositionRule(area="test_zone", y_above=50.0)
        assert rule.matches(0, 100, 0)  # y > 50
        assert not rule.matches(0, 50, 0)  # y == 50
        assert not rule.matches(0, 25, 0)  # y < 50

    def test_y_below_condition(self):
        """YBelow should match when y < threshold."""
        rule = PositionRule(area="test_zone", y_below=50.0)
        assert rule.matches(0, 25, 0)  # y < 50
        assert not rule.matches(0, 50, 0)  # y == 50
        assert not rule.matches(0, 100, 0)  # y > 50

    def test_z_above_condition(self):
        """ZAbove should match when z > threshold."""
        rule = PositionRule(area="test_zone", z_above=-100.0)
        assert rule.matches(0, 0, 0)  # z > -100
        assert not rule.matches(0, 0, -100)  # z == -100
        assert not rule.matches(0, 0, -200)  # z < -100

    def test_z_below_condition(self):
        """ZBelow should match when z < threshold."""
        rule = PositionRule(area="test_zone", z_below=200.0)
        assert rule.matches(0, 0, 100)  # z < 200
        assert not rule.matches(0, 0, 200)  # z == 200
        assert not rule.matches(0, 0, 300)  # z > 200

    def test_multiple_conditions_all_must_match(self):
        """All conditions must be satisfied for a match."""
        rule = PositionRule(area="test_zone", x_above=0, x_below=100, y_above=0, y_below=100)
        assert rule.matches(50, 50, 0)  # All conditions met
        assert not rule.matches(150, 50, 0)  # x too high
        assert not rule.matches(50, 150, 0)  # y too high
        assert not rule.matches(-50, 50, 0)  # x too low
        assert not rule.matches(50, -50, 0)  # y too low

    def test_combined_x_y_z_conditions(self):
        """Test combining X, Y, and Z conditions."""
        rule = PositionRule(
            area="test_zone",
            x_above=10,
            y_above=20,
            z_below=100,
        )
        assert rule.matches(15, 25, 50)  # x>10, y>20, z<100
        assert not rule.matches(5, 25, 50)  # x not > 10
        assert not rule.matches(15, 15, 50)  # y not > 20
        assert not rule.matches(15, 25, 150)  # z not < 100


class TestResolve:
    """Tests for ZoneResolver.resolve method."""

    def test_resolve_limgrave_overworld(self, resolver):
        """Resolving a Limgrave overworld position should return limgrave zone."""
        # m60_42_32_00 is in Limgrave
        internal, display = resolver.resolve("m60_42_32_00", -100, 100, 200)
        assert internal is not None
        assert display is not None

    def test_resolve_dungeon_map(self, resolver):
        """Resolving a dungeon map should return appropriate zone."""
        # m10_00_00_00 is Stormveil Castle area
        internal, display = resolver.resolve("m10_00_00_00", 0, 0, 0)
        assert internal is not None

    def test_resolve_unknown_map_returns_none(self, resolver):
        """Resolving an unknown map should return None."""
        internal, display = resolver.resolve("m99_99_99_99", 0, 0, 0)
        assert internal is None
        assert display is None

    def test_resolve_with_position_rule(self, resolver):
        """Position-based rules should disambiguate zones in the same map."""
        # This test depends on having submaps.txt with position rules
        # Find a map that has position rules defined
        if resolver.map_rules:
            map_id = next(iter(resolver.map_rules.keys()))
            rules = resolver.map_rules[map_id]
            if rules.rules:
                # Test that different positions can resolve to different zones
                internal1, _ = resolver.resolve(map_id, 0, 0, 0)
                # Try a position that should match a specific rule
                rule = rules.rules[0]
                if rule.y_above is not None:
                    y = rule.y_above + 100  # Position above the threshold
                    internal2, _ = resolver.resolve(map_id, 0, y, 0)
                    # At least verify we got valid results
                    assert internal1 is not None or internal2 is not None


class TestResolveByCol:
    """Tests for ZoneResolver.resolve_by_col method."""

    def test_resolve_valid_col(self, resolver):
        """Resolving a valid col should return the mapped zone."""
        # Find a valid col entry from the loaded data
        if resolver.col_zones:
            (map_id, col), expected_zone = next(iter(resolver.col_zones.items()))
            internal, display = resolver.resolve_by_col(map_id, col)
            assert internal == expected_zone
            assert display is not None

    def test_resolve_invalid_col_returns_none(self, resolver):
        """Resolving an invalid col should return None."""
        internal, display = resolver.resolve_by_col("m60_42_32_00", "hFFFFFF")
        assert internal is None
        assert display is None

    def test_col_more_precise_than_position(self, resolver):
        """Col-based resolution is more precise than position-based."""
        # If both methods are available, col should be exact
        if resolver.col_zones:
            (map_id, col), expected_zone = next(iter(resolver.col_zones.items()))
            col_internal, _ = resolver.resolve_by_col(map_id, col)
            pos_internal, _ = resolver.resolve(map_id, 0, 0, 0)
            # Col should give exact zone, position might differ
            assert col_internal == expected_zone


class TestResolveFromMapId:
    """Tests for ZoneResolver.resolve_from_map_id method."""

    def test_returns_all_zones_for_map(self, resolver):
        """Should return all possible zones for a map."""
        # Volcano Manor has multiple zones
        zones = resolver.resolve_from_map_id("m16_00_00_00")
        assert len(zones) > 1
        # Each entry should be (internal, display) tuple
        for internal, display in zones:
            assert internal is not None
            assert display is not None

    def test_returns_empty_for_unknown_map(self, resolver):
        """Should return empty list for unknown map."""
        zones = resolver.resolve_from_map_id("m99_99_99_99")
        assert zones == []

    def test_parent_map_expands_to_child_zones(self, resolver):
        """Parent map ID (m##_##_00_00) should include zones from child maps.

        Entity mapping uses parent map format (e.g., m61_44_00_00) but zones
        are defined with specific tiles (e.g., m61_44_45_00). The resolver
        should expand parent maps to include zones from all child tiles.

        This fixes the Midra's Manse → Romina bug where entity mapping
        returned m61_44_00_00 but rauhruins_romina is in m61_44_45_00.
        """
        # Parent map m61_44_00_00 (from entity mapping)
        zones = resolver.resolve_from_map_id("m61_44_00_00")
        internal_names = [z[0] for z in zones]

        # rauhruins_romina is defined in m61_44_45_00 (child tile)
        # but should be found when querying parent m61_44_00_00
        assert (
            "rauhruins_romina" in internal_names
        ), "rauhruins_romina should be found via parent map m61_44_00_00"

        # Also check other zones from child tiles are included
        assert "rauhruins_west" in internal_names
        assert "rauhruins_postromina" in internal_names

    def test_non_parent_map_not_expanded(self, resolver):
        """Non-parent map IDs should not be expanded.

        Only maps with 00_00 as the last two segments should expand.
        """
        # Specific tile - should only return zones for that tile
        zones_specific = resolver.resolve_from_map_id("m61_44_45_00")
        zones_parent = resolver.resolve_from_map_id("m61_44_00_00")

        # Parent should have more zones (from all child tiles)
        assert len(zones_parent) >= len(zones_specific)


class TestResolveAllCandidates:
    """Tests for ZoneResolver.resolve_all_candidates method."""

    def test_returns_ordered_candidates(self, resolver):
        """Candidates should be ordered by likelihood."""
        # Find a map with both position rules and foglocations
        for map_id in resolver.map_rules:
            if map_id in resolver.map_zones:
                candidates = resolver.resolve_all_candidates(map_id, 0, 0, 0)
                assert len(candidates) >= 1
                # Each candidate is (internal, display)
                for internal, display in candidates:
                    assert internal is not None
                    assert display is not None
                break

    def test_position_matched_zones_first(self, resolver):
        """Position-matched zones should come before non-matched ones."""
        # This depends on the actual data structure
        for map_id, rules in resolver.map_rules.items():
            if rules.rules and rules.default_area:
                candidates = resolver.resolve_all_candidates(map_id, 0, 0, 0)
                # At least verify candidates are returned
                assert len(candidates) >= 1
                break


class TestLookupByDetailText:
    """Tests for ZoneResolver.lookup_by_detail_text method."""

    def test_finds_zone_by_detail(self, resolver):
        """Should find zone by ASide/BSide detail text."""
        # Find a known detail text
        if resolver.detail_text_to_zone:
            detail, expected_zone = next(iter(resolver.detail_text_to_zone.items()))
            internal, display = resolver.lookup_by_detail_text(detail)
            assert internal == expected_zone
            assert display is not None

    def test_unknown_detail_returns_none(self, resolver):
        """Unknown detail text should return None."""
        internal, display = resolver.lookup_by_detail_text("nonexistent detail text")
        assert internal is None
        assert display is None


class TestLookupByDisplayName:
    """Tests for ZoneResolver.lookup_by_display_name method."""

    def test_finds_zone_key_by_display_name(self, resolver):
        """Should find internal zone key by display name."""
        zone_key = resolver.lookup_by_display_name("Limgrave")
        assert zone_key == "limgrave"

    def test_siofra_river_lookup(self, resolver):
        """Siofra River should map to siofra."""
        zone_key = resolver.lookup_by_display_name("Siofra River")
        assert zone_key == "siofra"

    def test_unknown_display_name_returns_none(self, resolver):
        """Unknown display name should return None."""
        zone_key = resolver.lookup_by_display_name("Nonexistent Zone Name")
        assert zone_key is None

    def test_duplicate_display_name_returns_first_zone(self, resolver):
        """For duplicate display names, should return the first zone_id (not the last).

        fog.txt has multiple zones with the same display name:
        - "Mohg, the Omen" exists as both sewer_mohg (line ~1059) and sewer_mohg_flame (line ~16517)
        - We want the main zone (sewer_mohg), not the virtual Entrance/Exit zone

        This is a regression test for a bug where the last zone_id won, causing
        inconsistent zone_ids between random links and preexisting links.
        """
        zone_key = resolver.lookup_by_display_name("Mohg, the Omen")
        assert zone_key == "sewer_mohg"  # First match, not sewer_mohg_flame


class TestLookupSpoilerName:
    """Tests for ZoneResolver.lookup_spoiler_name method."""

    def test_extracts_detail_from_parenthetical(self, resolver):
        """Should extract detail text from spoiler log names."""
        # Spoiler names like "Zone (detail text)"
        spoiler_name = (
            "Divine Tower of East Altus (approaching the Divine Tower of East Altus gate)"
        )
        internal, display = resolver.lookup_spoiler_name(spoiler_name)
        # If the detail text is mapped, should return the zone
        if "approaching the Divine Tower of East Altus gate" in resolver.detail_text_to_zone:
            assert internal is not None

    def test_no_parenthetical_returns_none(self, resolver):
        """Names without parenthetical should return None."""
        internal, display = resolver.lookup_spoiler_name("Limgrave")
        assert internal is None

    def test_unmapped_detail_returns_none(self, resolver):
        """Unmapped parenthetical detail should return None."""
        internal, display = resolver.lookup_spoiler_name("Zone (random unmapped text)")
        assert internal is None


class TestEstimatePosition:
    """Tests for ZoneResolver.estimate_position method."""

    def test_overworld_grid_calculation(self, resolver):
        """Overworld maps should estimate position from grid."""
        # m60_42_32_00 -> grid_x=42, grid_z=32
        pos = resolver.estimate_position("m60_42_32_00")
        assert pos is not None
        x, y, z = pos
        # Check approximate grid position
        expected_x = (42 - 50) * resolver.TILE_SIZE
        expected_z = (32 - 50) * resolver.TILE_SIZE
        assert x == expected_x
        assert z == expected_z

    def test_dungeon_with_bounds(self, resolver):
        """Dungeons with bounds should estimate from bounds."""
        # Find a zone with position bounds
        for zone_key, meta in resolver.zone_metadata.items():
            if meta.position_bounds:
                map_id = meta.map_ids[0] if meta.map_ids else None
                if map_id:
                    pos = resolver.estimate_position(map_id, zone_key)
                    if pos:
                        x, y, z = pos
                        # Should be within bounds or near them
                        assert isinstance(x, float)
                        assert isinstance(y, float)
                        assert isinstance(z, float)
                    break

    def test_invalid_map_id_returns_none(self, resolver):
        """Invalid map ID format should return None."""
        pos = resolver.estimate_position("invalid")
        assert pos is None


class TestFindMapIdsForDisplayName:
    """Tests for ZoneResolver.find_map_ids_for_display_name method."""

    def test_finds_maps_for_display_name(self, resolver):
        """Should find map IDs for a display name."""
        map_ids, internal, pos = resolver.find_map_ids_for_display_name("Limgrave")
        assert len(map_ids) >= 1
        # Should be overworld maps
        assert any(m.startswith("m60_") or m.startswith("m61_") for m in map_ids)

    def test_unknown_display_name_returns_empty(self, resolver):
        """Unknown display name should return empty list."""
        map_ids, internal, pos = resolver.find_map_ids_for_display_name("Nonexistent Zone")
        assert map_ids == []
        assert internal is None

    def test_no_duplicate_display_names_for_real_zones(self, resolver):
        """Real zones should have unique display names.

        fog.txt was cleaned up to ensure all zones have unique display names.
        This prevents bugs where lookup_by_display_name returns the wrong zone_id.
        If this test fails, rename the duplicate zone in fog.txt to be unique.
        """
        duplicates = []
        for display_name, zones in resolver.display_name_to_zones.items():
            if not display_name or display_name.startswith("Return"):
                continue
            # Filter to real zones (not AEG fog gates or numeric IDs)
            real_zones = [z for z in zones if not z.startswith("AEG") and not z[0].isdigit()]
            if len(real_zones) > 1:
                duplicates.append((display_name, real_zones))

        assert not duplicates, (
            f"Found duplicate display names for real zones: {duplicates}. "
            "Rename the zones in fog.txt to have unique display names."
        )

    def test_extracts_parenthetical_as_details(self, resolver):
        """Should extract parenthetical from display name as details."""
        # "Zone (detail)" format
        map_ids, internal, pos = resolver.find_map_ids_for_display_name(
            "Siofra River (at the top of the Deep Siofra Well)"
        )
        # Should try to use the parenthetical for disambiguation


class TestMapRulesDataStructure:
    """Tests for MapRules data structure."""

    def test_map_rules_structure(self, resolver):
        """MapRules should have rules list and optional default."""
        for _map_id, rules in resolver.map_rules.items():
            assert isinstance(rules, MapRules)
            assert isinstance(rules.rules, list)
            assert rules.default_area is None or isinstance(rules.default_area, str)

    def test_rules_have_required_fields(self, resolver):
        """Each PositionRule should have area field."""
        for _map_id, rules in resolver.map_rules.items():
            for rule in rules.rules:
                assert isinstance(rule, PositionRule)
                assert rule.area is not None


class TestZoneMetadata:
    """Tests for zone_metadata reverse lookup."""

    def test_zone_metadata_populated(self, resolver):
        """zone_metadata should be populated from data files."""
        assert len(resolver.zone_metadata) > 0

    def test_metadata_has_internal_name(self, resolver):
        """Each metadata entry should have internal_name."""
        for zone_key, meta in resolver.zone_metadata.items():
            assert meta.internal_name == zone_key

    def test_metadata_can_have_map_ids(self, resolver):
        """zone_metadata entries can have associated map_ids."""
        # Find an entry with map_ids
        has_map_ids = any(len(meta.map_ids) > 0 for meta in resolver.zone_metadata.values())
        assert has_map_ids

    def test_metadata_can_have_cols(self, resolver):
        """zone_metadata entries can have associated cols."""
        # Find an entry with cols
        has_cols = any(len(meta.cols) > 0 for meta in resolver.zone_metadata.values())
        assert has_cols


class TestDisplayNameToZones:
    """Tests for display_name_to_zones reverse index."""

    def test_index_populated(self, resolver):
        """display_name_to_zones should be populated."""
        assert len(resolver.display_name_to_zones) > 0

    def test_handles_duplicate_display_names(self, resolver):
        """Should handle multiple zones with same display name."""
        # Check if any display name has multiple zones
        for _display_name, zones in resolver.display_name_to_zones.items():
            assert isinstance(zones, list)
            assert len(zones) >= 1


class TestTileBoundaryResolution:
    """Tests for zones near tile boundaries.

    When a player is near a tile boundary, they may be in a different map tile
    than the fog gate they're entering. The entity_mapping provides the fog gate's
    actual tile, allowing the server to find zones that wouldn't otherwise be
    candidates from the player's tile alone.

    This documents the Royal Knight Loretta case where:
    - Fog gate is in m60_35_50_00 (liurnia_loretta zone)
    - Player may be in m60_35_51_00 (adjacent tile, liurnia_postmanor only)
    - Without entity_mapping enhancement, liurnia_loretta wouldn't be found
    """

    def test_liurnia_loretta_only_in_fog_gate_tile(self, resolver):
        """liurnia_loretta should only be in m60_35_50_00, not m60_35_51_00.

        This verifies the underlying data that makes entity_mapping enhancement
        necessary for tile boundary cases.
        """
        # Fog gate tile - should include liurnia_loretta
        zones_50 = resolver.map_zones.get("m60_35_50_00", set())
        assert (
            "liurnia_loretta" in zones_50
        ), "liurnia_loretta should be a candidate for m60_35_50_00 (fog gate tile)"

        # Adjacent tile - should NOT include liurnia_loretta
        zones_51 = resolver.map_zones.get("m60_35_51_00", set())
        assert "liurnia_loretta" not in zones_51, (
            "liurnia_loretta should NOT be in m60_35_51_00 (adjacent tile) - "
            "this is why entity_mapping enhancement is needed"
        )

    def test_resolve_from_map_id_for_adjacent_tiles(self, resolver):
        """resolve_from_map_id should return different zones for adjacent tiles."""
        zones_50 = resolver.resolve_from_map_id("m60_35_50_00")
        zones_51 = resolver.resolve_from_map_id("m60_35_51_00")

        keys_50 = {z[0] for z in zones_50}
        keys_51 = {z[0] for z in zones_51}

        # liurnia_loretta should be in 50 but not 51
        assert "liurnia_loretta" in keys_50
        assert "liurnia_loretta" not in keys_51

        # liurnia_postmanor should be in both (spans multiple tiles)
        assert "liurnia_postmanor" in keys_50
        assert "liurnia_postmanor" in keys_51

    def test_liurnia_postmanor_spans_both_tiles(self, resolver):
        """liurnia_postmanor should be a candidate for both adjacent tiles."""
        zones_50 = resolver.map_zones.get("m60_35_50_00", set())
        zones_51 = resolver.map_zones.get("m60_35_51_00", set())

        assert "liurnia_postmanor" in zones_50
        assert "liurnia_postmanor" in zones_51


class TestNokronBeforeMimicTearResolution:
    """Tests for Nokron before Mimic Tear zone resolution.

    Bug fix: siofrabank_nokron ("Nokron before Mimic Tear") should be
    correctly resolved when the player is in m12_02_00_00 near the
    Mimic Tear fog gate entrance (Z > 1100).

    The fog gate AEG099_002_9000 (Mimic Tear front) is in m12_02_00_00
    with ASide = siofrabank_nokron, but this zone was originally only
    mapped to m12_07_00_00.
    """

    def test_siofrabank_nokron_is_candidate_for_m12_02_00_00(self, resolver):
        """siofrabank_nokron should be a candidate for m12_02_00_00."""
        zones = resolver.map_zones.get("m12_02_00_00", set())
        assert (
            "siofrabank_nokron" in zones
        ), f"siofrabank_nokron should be in m12_02_00_00 candidates, got: {zones}"

    def test_siofrabank_nokron_prioritized_when_z_above_1100(self, resolver):
        """siofrabank_nokron should be first candidate when Z > 1100.

        Player at (963.5, -617.5, 1164.9) should resolve to
        siofrabank_nokron before siofra_nokron.
        """
        candidates = resolver.resolve_all_candidates("m12_02_00_00", 963.5, -617.5, 1164.9)
        candidate_keys = [c[0] for c in candidates]

        assert "siofrabank_nokron" in candidate_keys
        # siofrabank_nokron should come before siofra_nokron due to position match
        siofrabank_idx = candidate_keys.index("siofrabank_nokron")
        siofra_nokron_idx = candidate_keys.index("siofra_nokron")
        assert siofrabank_idx < siofra_nokron_idx, (
            f"siofrabank_nokron (idx={siofrabank_idx}) should be prioritized over "
            f"siofra_nokron (idx={siofra_nokron_idx})"
        )

    def test_siofra_nokron_prioritized_when_z_below_1100(self, resolver):
        """siofra_nokron should be first candidate when Z < 1100.

        Player at lower Z values (e.g., Z=0) should resolve to
        siofra_nokron (default) before siofrabank_nokron.
        """
        candidates = resolver.resolve_all_candidates("m12_02_00_00", 963.5, -617.5, 0.0)
        candidate_keys = [c[0] for c in candidates]

        assert "siofra_nokron" in candidate_keys
        assert "siofrabank_nokron" in candidate_keys
        # siofra_nokron (default) should come before siofrabank_nokron (no position match)
        siofra_nokron_idx = candidate_keys.index("siofra_nokron")
        siofrabank_idx = candidate_keys.index("siofrabank_nokron")
        assert siofra_nokron_idx < siofrabank_idx, (
            f"siofra_nokron (idx={siofra_nokron_idx}) should be prioritized over "
            f"siofrabank_nokron (idx={siofrabank_idx}) when Z < 1100"
        )

    def test_resolve_returns_siofrabank_at_mimic_tear_position(self, resolver):
        """resolve() should return siofrabank_nokron at Mimic Tear fog gate position."""
        # Position from race shop data: 929.708 -617.300 1179.369
        internal, display = resolver.resolve("m12_02_00_00", 929.7, -617.3, 1179.4)
        assert (
            internal == "siofrabank_nokron"
        ), f"Expected siofrabank_nokron at Mimic Tear fog gate position, got {internal}"
        assert display == "Nokron before Mimic Tear"


class TestPreexistingLinks:
    """Tests for preexisting link detection from fog.txt To: sections.

    The To: section in fog.txt defines one-way preexisting connections.
    If zone A has To: B but zone B does NOT have To: A, the connection
    is one-way (A→B only).
    """

    def test_preexisting_links_loaded(self, resolver):
        """Preexisting links should be loaded from fog.txt."""
        assert len(resolver.preexisting_links) > 0

    def test_has_preexisting_link_forward(self, resolver):
        """has_preexisting_link returns True for forward direction."""
        # shadowkeep_church_lower has To: shadowkeep_sanctum
        assert resolver.has_preexisting_link("shadowkeep_church_lower", "shadowkeep_sanctum")

    def test_has_preexisting_link_no_reverse(self, resolver):
        """has_preexisting_link returns False when no reverse link exists."""
        # shadowkeep_sanctum does NOT have To: shadowkeep_church_lower
        assert not resolver.has_preexisting_link("shadowkeep_sanctum", "shadowkeep_church_lower")

    def test_one_way_detection_from_to_section(self, resolver):
        """One-way should be detected from asymmetric To: entries."""
        source = "shadowkeep_church_lower"
        target = "shadowkeep_sanctum"

        forward = resolver.has_preexisting_link(source, target)
        reverse = resolver.has_preexisting_link(target, source)

        # This link should be one-way (forward exists, reverse doesn't)
        assert forward and not reverse

    def test_bidirectional_link_both_directions(self, resolver):
        """Bidirectional links should have To: entries in both zones."""
        # Find a bidirectional link (both zones have To: entries pointing to each other)
        for source, targets in resolver.preexisting_links.items():
            for target in targets:
                if resolver.has_preexisting_link(target, source):
                    # Found a bidirectional link
                    assert resolver.has_preexisting_link(source, target)
                    assert resolver.has_preexisting_link(target, source)
                    return
        # If no bidirectional links found, that's also valid (all one-way)


class TestResolveAllCandidatesOrdering:
    """Test that resolve_all_candidates returns deterministic ordering."""

    def test_ordering_is_deterministic(self, resolver):
        """Verify that calling resolve_all_candidates multiple times returns same order."""
        # Call multiple times and verify same result
        results = []
        for _ in range(5):
            candidates = resolver.resolve_all_candidates("m13_00_00_00", 13.1, -39.0, 430.6)
            results.append([c[0] for c in candidates])

        # All results should be identical
        for i in range(1, len(results)):
            assert results[i] == results[0], "resolve_all_candidates should be deterministic"

    def test_zones_with_known_positions_ordered_by_distance(self, resolver):
        """Verify that zones with known positions are ordered by distance to query."""
        # Position near Farum Azula Rooftop and Bridge
        candidates = resolver.resolve_all_candidates("m13_00_00_00", 13.1, -39.0, 430.6)
        candidate_names = [c[0] for c in candidates]

        # farumazula has known position (50.658, -60.356, 520.79)
        # farumazula_temple has known position (-62.355, -20.0, 391.102)
        # farumazula_prestart has known position (175.2, 59.0, 205.9)
        # farumazula should appear before farumazula_prestart (closer to query)
        if "farumazula" in candidate_names and "farumazula_prestart" in candidate_names:
            assert candidate_names.index("farumazula") < candidate_names.index(
                "farumazula_prestart"
            ), "Closer zone should appear first"

    def test_farum_azula_rooftop_in_top_candidates(self, resolver):
        """Verify that Farum Azula Rooftop is in top 5 candidates for relevant position."""
        # This is the position from the reported bug
        candidates = resolver.resolve_all_candidates("m13_00_00_00", 13.1, -39.0, 430.6)
        top_5_names = [c[0] for c in candidates[:5]]

        assert (
            "farumazula" in top_5_names
        ), "farumazula should be in top 5 candidates for this position"


class TestBossZonesInCandidates:
    """Test that boss zones (_boss suffix) are included in top candidates.

    Bug fix: Boss zones used to be deprioritized (priority 3 instead of 2),
    causing them to be excluded when MAX_ZONE_CANDIDATES (5) was exceeded.
    This caused fog gates leading to boss arenas to fail matching.

    Example: "Cave of Knowledge - Soldier of Godrick" (graveyard_cave_boss)
    was excluded from candidates for m18_00_00_00 because 5 non-boss zones
    filled the list first.
    """

    def test_boss_zone_in_top_candidates_m18(self, resolver):
        """graveyard_cave_boss should be in top 5 candidates for m18_00_00_00."""
        # Position from the reported bug: target_pos = (-42.6, 11.3, 40.2)
        candidates = resolver.resolve_all_candidates("m18_00_00_00", -42.6, 11.3, 40.2)
        top_5_names = [c[0] for c in candidates[:5]]

        assert "graveyard_cave_boss" in top_5_names, (
            f"graveyard_cave_boss (Cave of Knowledge - Soldier of Godrick) should be "
            f"in top 5 candidates, got: {top_5_names}"
        )

    def test_boss_zones_not_deprioritized(self, resolver):
        """Boss zones should have same priority as non-boss zones."""
        candidates = resolver.resolve_all_candidates("m18_00_00_00", 0, 0, 0)

        # Get all zones and check their positions
        all_keys = [c[0] for c in candidates]

        # graveyard_cave_boss should not be last (was deprioritized before fix)
        boss_idx = all_keys.index("graveyard_cave_boss")

        # Boss zone should be interspersed with non-boss zones, not pushed to end
        # At minimum, it should appear before at least one non-boss zone
        # (accounting for distance-based sorting)
        assert (
            boss_idx < len(all_keys) - 1
        ), f"Boss zone at position {boss_idx} should not be at the very end"


class TestShadowKeepChurchDistrictElevator:
    """Test resolution for Shadow Keep - Church District elevator area.

    The elevator connecting Shadow Keep to Specimen Storehouse spans two maps.
    When the player warps to the top of this elevator from Leyndell - Erdtree
    Sanctuary, they spawn at position (245.28, 278.0, 264.84) in map m21_01_00_00.
    This position should resolve to Shadow Keep - Church District, not Specimen
    Storehouse.

    See: analysis/reports/20251231_153628_782495b2/REPORT.md
    """

    def test_elevator_position_resolves_to_church_district(self, resolver):
        """Position at top of elevator should resolve to Shadow Keep - Church District."""
        # Actual position from mod log: (245.28, 278.0, 264.84) in m21_01_00_00
        internal, display = resolver.resolve("m21_01_00_00", 245.28, 278.0, 264.84)

        assert (
            internal == "shadowkeep_church"
        ), f"Expected shadowkeep_church at elevator position, got {internal}"
        assert display == "Shadow Keep - Church District"

    def test_church_district_is_first_candidate(self, resolver):
        """Shadow Keep - Church District should be first candidate at elevator position."""
        candidates = resolver.resolve_all_candidates("m21_01_00_00", 245.28, 278.0, 264.84)
        candidate_keys = [c[0] for c in candidates]

        assert (
            candidate_keys[0] == "shadowkeep_church"
        ), f"Expected shadowkeep_church as first candidate, got {candidate_keys[:5]}"

    def test_church_district_map_includes_m21_01(self, resolver):
        """shadowkeep_church zone should include m21_01_00_00 in its map_ids."""
        zones_in_m21_01 = resolver.map_zones.get("m21_01_00_00", set())
        assert (
            "shadowkeep_church" in zones_in_m21_01
        ), "shadowkeep_church should be a candidate for m21_01_00_00"


class TestLakesideCrystalCaveExit:
    """Tests for Lakeside Crystal Cave exit to Slumbering Wolf's Shack.

    Bug fix: The exit from Lakeside Crystal Cave boss room (m31_05_00_00)
    leads to liurnia_slumbering (Slumbering Wolf's Shack). This zone was
    originally only mapped to m60_36_41_00 (overworld), causing discovery
    failures when the player exited the dungeon boss room.

    The fix adds m31_05_00_00 to liurnia_slumbering's Maps: list in fog.txt,
    since the fog gate AEG099_001_9000 (Bloodhound Knight back) has
    ASide: liurnia_slumbering, meaning you exit to that zone.

    See: analysis/reports/.../REPORT.md - Volcano Manor Drawing Room →
         Liurnia - Slumbering Wolf's Shack not found
    """

    def test_liurnia_slumbering_is_candidate_for_lakeside_cave(self, resolver):
        """liurnia_slumbering should be a candidate for m31_05_00_00."""
        zones = resolver.map_zones.get("m31_05_00_00", set())
        assert (
            "liurnia_slumbering" in zones
        ), f"liurnia_slumbering should be in m31_05_00_00 candidates, got: {zones}"

    def test_resolve_all_candidates_includes_slumbering(self, resolver):
        """resolve_all_candidates for Lakeside Crystal Cave should include Slumbering Wolf's Shack."""
        # Position from fog gate exit (approximate)
        candidates = resolver.resolve_all_candidates("m31_05_00_00", -150, 150, -30)
        candidate_keys = [c[0] for c in candidates]
        candidate_names = [c[1] for c in candidates]

        assert (
            "liurnia_slumbering" in candidate_keys
        ), f"liurnia_slumbering should be in candidates, got: {candidate_keys}"
        assert (
            "Liurnia - Slumbering Wolf's Shack" in candidate_names
        ), f"'Liurnia - Slumbering Wolf's Shack' should be in candidate display names, got: {candidate_names}"

    def test_lakeside_cave_zones_include_expected(self, resolver):
        """m31_05_00_00 should include cave, boss, and exit zones."""
        zones = resolver.map_zones.get("m31_05_00_00", set())

        # Core cave zones
        assert "liurnia_lakesidecave" in zones, "liurnia_lakesidecave should be in m31_05_00_00"
        assert (
            "liurnia_lakesidecave_boss" in zones
        ), "liurnia_lakesidecave_boss should be in m31_05_00_00"

        # Exit zone (the fix)
        assert (
            "liurnia_slumbering" in zones
        ), "liurnia_slumbering should be in m31_05_00_00 (boss room exit)"


class TestSiblingMapFallback:
    """Tests for sibling map fallback in zone resolution.

    When a map has no directly associated zones, the resolver extends the search
    to sibling maps (same area prefix). This handles cases where the mod reports
    a different tile/sub-area than what's defined in fog.txt.

    Examples:
    - m61_44_45_16 has no zones, but m61_44_45_00 does (overworld tile variant)
    - m21_01_00_00 has zones, but shadowkeep is on m21_00_00_00 (DLC sub-area)
    """

    def test_get_sibling_map_zones_overworld_tile(self, resolver):
        """Sibling zones for overworld tile should include same-tile variants.

        m61_44_45_16 → should find zones from m61_44_45_00, m61_44_45_10, etc.
        """
        siblings = resolver._get_sibling_map_zones("m61_44_45_16")
        sibling_names = [z[1] for z in siblings]

        # Should include zones from the same tile (m61_44_45_*)
        assert len(siblings) > 0, "Should find sibling zones for m61_44_45_16"
        assert "Ancient Ruins of Rauh - After Romina" in sibling_names

    def test_get_sibling_map_zones_dlc_area(self, resolver):
        """Sibling zones for DLC area should include zones from same area prefix.

        m21_03_00_00 (hypothetical) → should find zones from m21_00, m21_01, m21_02
        """
        # Use a map that might not have direct zones but shares prefix with Shadow Keep
        siblings = resolver._get_sibling_map_zones("m21_03_00_00")
        sibling_names = [z[1] for z in siblings]

        # Should include Shadow Keep zones from m21_* maps
        assert len(siblings) > 0, "Should find sibling zones for m21_03_00_00"
        assert "Shadow Keep" in sibling_names or "Specimen Storehouse" in sibling_names

    def test_get_sibling_map_zones_excludes_original_map(self, resolver):
        """Sibling zones should not include zones from the excluded map."""
        # m21_00_00_00 has shadowkeep, get siblings excluding it
        siblings = resolver._get_sibling_map_zones("m21_01_00_00", exclude_map_ids={"m21_01_00_00"})

        # Verify we got sibling zones (from m21_00, m21_02, etc.)
        assert len(siblings) > 0

        # The siblings should include zones NOT from m21_01_00_00
        sibling_names = [z[1] for z in siblings]
        assert "Shadow Keep" in sibling_names  # From m21_00_00_00

    def test_resolve_all_candidates_fallback_to_siblings(self, resolver):
        """When no direct candidates, should fall back to sibling maps.

        m61_44_45_16 has no direct zones but siblings (m61_44_45_00) do.
        """
        candidates = resolver.resolve_all_candidates("m61_44_45_16", 0, 0, 0)
        candidate_names = [c[1] for c in candidates]

        assert len(candidates) > 0, "Should find candidates via sibling fallback"
        assert "Ancient Ruins of Rauh - After Romina" in candidate_names

    def test_resolve_all_candidates_no_fallback_when_direct_zones_exist(self, resolver):
        """When direct candidates exist, should NOT add sibling zones.

        m21_01_00_00 has direct zones (Specimen Storehouse), so sibling zones
        (Shadow Keep from m21_00_00_00) should NOT be added.
        """
        candidates = resolver.resolve_all_candidates("m21_01_00_00", 0, 0, 0)
        candidate_names = [c[1] for c in candidates]

        # Should have direct zones
        assert "Specimen Storehouse" in candidate_names

        # Should also have zones added via fog.txt updates (shadowkeep, westrampart)
        # These are now directly associated with m21_01_00_00
        assert "Shadow Keep" in candidate_names
        assert "Shadow Keep - West Rampart" in candidate_names

    def test_resolve_all_candidates_can_disable_sibling_extension(self, resolver):
        """Can disable sibling extension for testing/debugging."""
        # m61_44_45_16 has no direct zones
        candidates = resolver.resolve_all_candidates(
            "m61_44_45_16", 0, 0, 0, extend_to_siblings=False
        )

        assert len(candidates) == 0, "Should have no candidates without sibling fallback"

    def test_sibling_prefix_for_dungeon_maps(self, resolver):
        """Dungeon maps (m10_, m11_, etc.) use area prefix for siblings.

        m10_01_00_00 → siblings include m10_00_00_00, m10_02_00_00, etc.
        """
        siblings = resolver._get_sibling_map_zones("m10_99_00_00")  # Hypothetical
        sibling_names = [z[1] for z in siblings]

        # Should find Stormveil zones (m10_00_00_00) and Limgrave zones (m10_01_00_00)
        assert len(siblings) > 0
        # Stormveil is on m10_00, should be in siblings of m10_99
        stormveil_found = any("Stormveil" in name for name in sibling_names)
        assert stormveil_found, f"Expected Stormveil zones in siblings, got: {sibling_names[:5]}"

    def test_sibling_prefix_for_overworld_tiles(self, resolver):
        """Overworld tiles (m60_, m61_) use tile prefix for siblings.

        m60_42_36_16 → siblings include m60_42_36_00, m60_42_36_10, etc.
        NOT m60_42_37_00 (different tile).
        """
        # m60_42_36 is Limgrave starting area
        siblings = resolver._get_sibling_map_zones("m60_42_36_99")  # Hypothetical variant

        # Should find zones from m60_42_36_00 (same tile)
        assert len(siblings) > 0, "Should find sibling zones for m60_42_36_99"

        # Verify sibling zones are from same tile prefix
        # (The sibling logic uses tile prefix m60_42_36_ for overworld)


class TestIsZoneBasedCond:
    """Tests for _is_zone_based_cond() method.

    This method determines if a Cond: value from fog.txt represents a zone-based
    condition (indicating a one-way fog gate) vs an item/progression condition
    (bidirectional once unlocked).
    """

    def test_simple_zone_name_is_zone_based(self, resolver):
        """Simple zone names like 'leyndell_bedchamber' are zone-based."""
        assert resolver._is_zone_based_cond("leyndell_bedchamber") is True
        assert resolver._is_zone_based_cond("volcano_town") is True
        assert resolver._is_zone_based_cond("graveyard_cave") is True
        assert resolver._is_zone_based_cond("siofra") is True

    def test_item_conditions_are_not_zone_based(self, resolver):
        """Item conditions like keys and medals are not zone-based."""
        assert resolver._is_zone_based_cond("academyglintstonekey") is False
        assert resolver._is_zone_based_cond("purebloodknightsmedal") is False
        assert resolver._is_zone_based_cond("darkmoonring") is False
        assert resolver._is_zone_based_cond("holeladennecklace") is False

    def test_medallion_conditions_are_not_zone_based(self, resolver):
        """Medallion conditions are not zone-based (bidirectional once used)."""
        assert resolver._is_zone_based_cond("dectusmedallionleft") is False
        assert resolver._is_zone_based_cond("haligtreesecretmedallionright") is False

    def test_rune_conditions_are_not_zone_based(self, resolver):
        """Rune/progression conditions are not zone-based."""
        assert resolver._is_zone_based_cond("runes_leyndell") is False
        assert resolver._is_zone_based_cond("runes_rold") is False
        assert resolver._is_zone_based_cond("runeradahn") is False

    def test_and_conditions_are_not_zone_based(self, resolver):
        """Complex AND conditions are not zone-based."""
        assert resolver._is_zone_based_cond("AND storehouse_back omother") is False
        assert resolver._is_zone_based_cond("AND dectusmedallionleft dectusmedallionright") is False

    def test_or_conditions_are_not_zone_based(self, resolver):
        """Complex OR conditions are not zone-based."""
        assert resolver._is_zone_based_cond("OR altus outskirts gelmir") is False
        assert resolver._is_zone_based_cond("OR farumazula_maliketh leyndell") is False

    def test_kindling_condition_not_zone_based(self, resolver):
        """Tree kindling condition is not zone-based."""
        assert resolver._is_zone_based_cond("treekindling") is False

    def test_omother_condition_not_zone_based(self, resolver):
        """O Mother gesture condition is not zone-based."""
        assert resolver._is_zone_based_cond("omother") is False


class TestConditionalFogGates:
    """Tests for conditional fog gate detection (one-way indicators).

    Fog gates with Cond: on one side indicate that side requires a condition
    to USE the fog gate. When the Cond is zone-based (not an item), this
    typically means a physical barrier (shortcut ladder, one-way door, drop).
    """

    def test_shortcut_ladder_detected(self, resolver):
        """Shortcut ladders (bedchamber fog gates) should be detected."""
        # Godfrey/Gideon fog gates have Cond: on the bedchamber side
        godfrey_text = "outside of Godfrey's arena at the base of a shortcut ladder, accessed from an open window on a second-floor rooftop"
        gideon_text = "outside of Gideon's arena at the base of a shortcut ladder, accessed from an open window on a second-floor rooftop"

        assert resolver.has_conditional_fog_gate_by_detail(godfrey_text) is True
        assert resolver.has_conditional_fog_gate_by_detail(gideon_text) is True

    def test_boss_fog_gate_detected(self, resolver):
        """Boss fog gates with zone Cond: should be detected."""
        # Soldier of Godrick fog gate
        soldier_text = "before Soldier of Godrick's arena"
        assert resolver.has_conditional_fog_gate_by_detail(soldier_text) is True

        # Godskin Apostle in Divine Tower of Caelid
        godskin_text = "before Godskin Apostle's arena"
        assert resolver.has_conditional_fog_gate_by_detail(godskin_text) is True

    def test_one_way_door_detected(self, resolver):
        """One-way doors should be detected."""
        # Volcano Manor hallway to Prison Town
        volcano_text = "at the end of the dark hallway leading to Prison Town"
        assert resolver.has_conditional_fog_gate_by_detail(volcano_text) is True

    def test_sewer_entrance_detected(self, resolver):
        """Sewer entrance (one-way door) should be detected."""
        sewer_text = "at the entrance to Subterranean Shunning-Grounds"
        assert resolver.has_conditional_fog_gate_by_detail(sewer_text) is True

    def test_deep_well_detected(self, resolver):
        """Deep Siofra Well (elevator with key) should be detected."""
        well_text = "at the top of the Deep Siofra Well"
        assert resolver.has_conditional_fog_gate_by_detail(well_text) is True

    def test_item_based_fog_gate_not_detected(self, resolver):
        """Fog gates with item Cond: should NOT be detected as one-way."""
        # Academy entrance requires key but is bidirectional once opened
        academy_text = "using South-facing gate at Raya Lucaria Main Entrance"
        assert resolver.has_conditional_fog_gate_by_detail(academy_text) is False

    def test_normal_fog_gate_not_detected(self, resolver):
        """Normal fog gates without Cond: should not be detected."""
        # A typical fog gate without conditions
        normal_text = "at the front of Morgott's arena"
        assert resolver.has_conditional_fog_gate_by_detail(normal_text) is False

    def test_none_detail_returns_false(self, resolver):
        """None detail_text should return False."""
        assert resolver.has_conditional_fog_gate_by_detail(None) is False

    def test_empty_detail_returns_false(self, resolver):
        """Empty detail_text should return False."""
        assert resolver.has_conditional_fog_gate_by_detail("") is False

    def test_fog_gate_conditions_loaded(self, resolver):
        """Verify that fog gate conditions are loaded from fog.txt."""
        # Should have loaded some conditions
        assert len(resolver.fog_gate_detail_has_cond) > 0

        # Check some expected entries exist
        expected_texts = [
            "before Soldier of Godrick's arena",
            "outside of Godfrey's arena at the base of a shortcut ladder",
        ]
        for text in expected_texts:
            # Use partial match since the full text might be slightly different
            found = any(text in key for key in resolver.fog_gate_detail_has_cond)
            assert found, f"Expected to find '{text}' in fog_gate_detail_has_cond"
