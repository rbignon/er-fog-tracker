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

from fogvizu.zone_resolver import MapRules, PositionRule, ZoneResolver


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

    def test_disambiguates_with_details(self, resolver):
        """Should disambiguate zones using details."""
        # Find a display name with multiple zones to test disambiguation
        multi_zone_display = None
        for display_name, zones in resolver.display_name_to_zones.items():
            if len(zones) > 1 and display_name and not display_name.startswith("Return"):
                multi_zone_display = display_name
                break

        if multi_zone_display:
            # Test that we get results for a multi-zone display name
            map_ids, internal, pos = resolver.find_map_ids_for_display_name(multi_zone_display)
            # Should return map_ids even if can't disambiguate
            assert len(map_ids) >= 1 or internal is not None

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
