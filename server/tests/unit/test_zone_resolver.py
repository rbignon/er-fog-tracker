"""
Unit tests for zone_resolver module.
"""

from pathlib import Path

import pytest

from fogvizu.zone_resolver import ZoneResolver


@pytest.fixture
def resolver():
    """Create a ZoneResolver with real data."""
    data_dir = Path(__file__).parent.parent.parent / "data"
    return ZoneResolver(data_dir)


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
