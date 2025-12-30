"""
Unit tests for grace_resolver module.

Tests for grace entity ID to zone resolution:
- resolve_zone_by_grace_entity_id() for known graces
- Handling of unknown entity IDs
- get_grace_info() for full grace data
"""

from fogtracker.grace_resolver import (
    get_grace_info,
    get_grace_mapping,
    resolve_zone_by_grace_entity_id,
)


class TestGraceMapping:
    """Tests for grace mapping loading."""

    def test_mapping_loads_successfully(self):
        """Grace mapping should load from graces.json."""
        mapping = get_grace_mapping()
        assert isinstance(mapping, dict)
        assert len(mapping) > 0, "Grace mapping should not be empty"

    def test_mapping_has_expected_structure(self):
        """Each mapping entry should have grace_name, zone, and map_id."""
        mapping = get_grace_mapping()
        # Check a few random entries
        for entity_id, entry in list(mapping.items())[:5]:
            assert "grace_name" in entry, f"Entry {entity_id} missing grace_name"
            assert "zone" in entry, f"Entry {entity_id} missing zone"
            assert "map_id" in entry, f"Entry {entity_id} missing map_id"


class TestResolveZoneByGraceEntityId:
    """Tests for resolve_zone_by_grace_entity_id()."""

    def test_the_first_step_grace(self):
        """The First Step grace should resolve to Limgrave."""
        # Entity ID 1042362951 = "The First Step" in Limgrave
        zone = resolve_zone_by_grace_entity_id(1042362951)
        assert zone == "Limgrave"

    def test_church_of_elleh_grace(self):
        """Church of Elleh grace should resolve to Limgrave."""
        # Entity ID 1042362950 = "Church of Elleh" in Limgrave
        zone = resolve_zone_by_grace_entity_id(1042362950)
        assert zone == "Limgrave"

    def test_stormveil_main_gate_grace(self):
        """Stormveil Main Gate grace should resolve to Stormveil Castle before Gate."""
        # Entity ID 10002958 = "Stormveil Main Gate"
        zone = resolve_zone_by_grace_entity_id(10002958)
        assert zone == "Stormveil Castle before Gate"

    def test_roundtable_hold_grace(self):
        """Table of Lost Grace should resolve to Roundtable Hold."""
        # Entity ID 11102950 = "Table of Lost Grace" in Roundtable Hold
        zone = resolve_zone_by_grace_entity_id(11102950)
        assert zone == "Roundtable Hold"

    def test_unknown_entity_id_returns_none(self):
        """Unknown entity ID should return None."""
        zone = resolve_zone_by_grace_entity_id(999999999)
        assert zone is None

    def test_fog_rando_entity_id_returns_none(self):
        """Fog rando entity IDs (755890xxx) should return None."""
        # These are fog gate entity IDs, not grace entity IDs
        zone = resolve_zone_by_grace_entity_id(755890042)
        assert zone is None

    def test_accepts_string_entity_id(self):
        """Function should accept entity ID as string."""
        zone = resolve_zone_by_grace_entity_id("1042362951")
        assert zone == "Limgrave"

    def test_accepts_int_entity_id(self):
        """Function should accept entity ID as int."""
        zone = resolve_zone_by_grace_entity_id(1042362951)
        assert zone == "Limgrave"


class TestGetGraceInfo:
    """Tests for get_grace_info()."""

    def test_returns_full_info_for_known_grace(self):
        """Should return full info dict for known grace."""
        info = get_grace_info(1042362951)
        assert info is not None
        assert info["grace_name"] == "The First Step"
        assert info["zone"] == "Limgrave"
        assert info["map_id"] == "m60_42_36_00"

    def test_returns_none_for_unknown_grace(self):
        """Should return None for unknown entity ID."""
        info = get_grace_info(999999999)
        assert info is None


class TestGraceEntityIdFormats:
    """Tests for different grace entity ID patterns."""

    def test_overworld_grace_format(self):
        """Overworld graces have format 10XXYY295x."""
        # Gatefront: 1042372950 -> m60_42_37_00 (Limgrave)
        zone = resolve_zone_by_grace_entity_id(1042372950)
        assert zone is not None
        assert zone == "Limgrave"

    def test_legacy_dungeon_grace_format(self):
        """Legacy dungeon graces have format with different pattern."""
        # Stormveil Cliffside: 1041382950
        zone = resolve_zone_by_grace_entity_id(1041382950)
        assert zone is not None

    def test_dlc_grace_format(self):
        """DLC graces should be handled if present in mapping."""
        # Check if any DLC graces exist in mapping (m20_/m21_ maps)
        mapping = get_grace_mapping()
        dlc_graces = [
            eid
            for eid, info in mapping.items()
            if (info.get("map_id") or "").startswith(("m20_", "m21_"))
        ]
        # Just verify DLC graces are included if they exist
        # (This test documents that DLC support exists)
        if dlc_graces:
            zone = resolve_zone_by_grace_entity_id(dlc_graces[0])
            assert zone is not None
