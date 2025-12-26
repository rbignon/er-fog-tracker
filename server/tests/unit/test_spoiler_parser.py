"""Unit tests for spoiler_parser module.

Tests the parsing of Fog Gate Randomizer spoiler logs.
"""

import pytest

from fogtracker.spoiler_parser import (
    ConnectionInfo,
    ParseResult,
    SpoilerParseError,
    ZoneInfo,
    _extract_area_and_details,
    _parse_area_line,
    _parse_connection_line,
    _should_skip_line,
    parse_spoiler_log,
    validate_spoiler_header,
)


class TestShouldSkipLine:
    """Tests for _should_skip_line function."""

    def test_empty_line(self):
        assert _should_skip_line("")
        assert _should_skip_line("   ")
        assert _should_skip_line("\t")

    def test_options_and_seed(self):
        assert _should_skip_line("Options and seed:12345 Fog Gate Randomizer")

    def test_key_item_hash(self):
        assert _should_skip_line("Key item hash: abc123")

    def test_optional_areas(self):
        assert _should_skip_line("Optional areas:")

    def test_valid_area_line(self):
        assert not _should_skip_line("Limgrave")
        assert not _should_skip_line("Chapel of Anticipation")

    def test_connection_line(self):
        assert not _should_skip_line("  Random: Chapel --> Limgrave")


class TestExtractAreaAndDetails:
    """Tests for _extract_area_and_details function."""

    def test_no_details(self):
        area, details = _extract_area_and_details("Limgrave")
        assert area == "Limgrave"
        assert details == ""

    def test_before_details(self):
        area, details = _extract_area_and_details(
            "Chapel of Anticipation (before Grafted Scion's arena)"
        )
        assert area == "Chapel of Anticipation"
        assert details == "before Grafted Scion's arena"

    def test_at_details(self):
        area, details = _extract_area_and_details("Limgrave (at the start)")
        assert area == "Limgrave"
        assert details == "at the start"

    def test_arriving_details(self):
        area, details = _extract_area_and_details("Caelid (arriving from the west)")
        assert area == "Caelid"
        assert details == "arriving from the west"

    def test_using_details(self):
        area, details = _extract_area_and_details("Divine Bridge (using the sending gate)")
        assert area == "Divine Bridge"
        assert details == "using the sending gate"

    def test_fallback_inside_details(self):
        """Parenthetical starting with 'inside' (not in DETAIL_PATTERNS)."""
        area, details = _extract_area_and_details(
            "Divine Tower of East Altus - Fell Twins (inside the Fell Twins' arena)"
        )
        assert area == "Divine Tower of East Altus - Fell Twins"
        assert details == "inside the Fell Twins' arena"

    def test_fallback_approaching_details(self):
        """Parenthetical starting with 'approaching' (not in DETAIL_PATTERNS)."""
        area, details = _extract_area_and_details(
            "Divine Tower of East Altus (approaching the Divine Tower of East Altus gate)"
        )
        assert area == "Divine Tower of East Altus"
        assert details == "approaching the Divine Tower of East Altus gate"

    def test_fallback_lying_down_details(self):
        """Parenthetical starting with 'lying down' (not in DETAIL_PATTERNS)."""
        area, details = _extract_area_and_details(
            "Farum Azula Rooftop and Bridge (lying down in front of the tempest)"
        )
        assert area == "Farum Azula Rooftop and Bridge"
        assert details == "lying down in front of the tempest"


class TestParseAreaLine:
    """Tests for _parse_area_line function."""

    def test_simple_area(self):
        zone = _parse_area_line("Limgrave")
        assert zone is not None
        assert zone.name == "Limgrave"
        assert zone.is_boss is False
        assert zone.scaling is None

    def test_boss_area(self):
        zone = _parse_area_line("Ashen Leyndell <<<<<")
        assert zone is not None
        assert zone.name == "Ashen Leyndell"
        assert zone.is_boss is True

    def test_area_with_scaling(self):
        zone = _parse_area_line("Limgrave (scaling: 1-50)")
        assert zone is not None
        assert zone.name == "Limgrave"
        assert zone.scaling == "1-50"

    def test_indented_line_returns_none(self):
        zone = _parse_area_line("  Random: Chapel --> Limgrave")
        assert zone is None

    def test_skip_pattern_returns_none(self):
        zone = _parse_area_line("Options and seed:12345")
        assert zone is None

    def test_has_uuid(self):
        zone = _parse_area_line("Limgrave")
        assert zone is not None
        assert zone.id is not None
        assert len(zone.id) == 36  # UUID format


class TestParseConnectionLine:
    """Tests for _parse_connection_line function."""

    def test_random_connection(self):
        conn = _parse_connection_line(
            "  Random: Chapel of Anticipation (before boss) --> Limgrave (at start)"
        )
        assert conn is not None
        assert conn.conn_type == "random"
        assert conn.source == "Chapel of Anticipation"
        assert conn.target == "Limgrave"
        assert conn.source_details == "before boss"
        assert conn.target_details == "at start"

    def test_preexisting_connection(self):
        conn = _parse_connection_line(
            "  Preexisting: Limgrave --> Stormveil Castle (at the main gate)"
        )
        assert conn is not None
        assert conn.conn_type == "preexisting"
        assert conn.source == "Limgrave"
        assert conn.target == "Stormveil Castle"

    def test_one_way_sending_gate(self):
        conn = _parse_connection_line(
            "  Random: Divine Bridge (using the sending gate) --> Isolated Tower (warp destination)"
        )
        assert conn is not None
        assert conn.is_inherently_one_way is True

    def test_one_way_abducted(self):
        conn = _parse_connection_line(
            "  Random: Roundtable Hold (abducted by maiden) --> Volcano Manor"
        )
        assert conn is not None
        assert conn.is_inherently_one_way is True

    def test_bidirectional_fog_gate(self):
        conn = _parse_connection_line("  Random: Limgrave (near beach) --> Caelid (at the border)")
        assert conn is not None
        assert conn.is_inherently_one_way is False

    def test_non_connection_returns_none(self):
        conn = _parse_connection_line("Limgrave")
        assert conn is None

    def test_no_arrow_returns_none(self):
        conn = _parse_connection_line("  Random: Limgrave to Caelid")
        assert conn is None


class TestValidateSpoilerHeader:
    """Tests for validate_spoiler_header function."""

    def test_valid_header(self):
        text = "Options and seed:12345 Fog Gate Randomizer\nLimgrave"
        seed = validate_spoiler_header(text)
        assert seed == 12345

    def test_large_seed(self):
        text = "Options and seed:1078869800 Fog Gate Randomizer"
        seed = validate_spoiler_header(text)
        assert seed == 1078869800

    def test_missing_seed_raises(self):
        with pytest.raises(SpoilerParseError, match="Could not find seed"):
            validate_spoiler_header("Invalid header line")

    def test_empty_raises(self):
        # Empty string still has one empty line, so "Could not find seed" is raised
        with pytest.raises(SpoilerParseError, match="Could not find seed"):
            validate_spoiler_header("")


class TestParseSpoilerLog:
    """Tests for parse_spoiler_log function."""

    def test_minimal_valid_log(self):
        text = """Options and seed:12345 Fog Gate Randomizer
Chapel of Anticipation
  Random: Chapel of Anticipation (before boss) --> Limgrave (at start)
Limgrave
  Preexisting: Limgrave --> Stormveil Castle
Stormveil Castle
Optional areas:
"""
        result = parse_spoiler_log(text)
        assert result.seed == 12345
        assert len(result.zones) == 3
        assert len(result.connections) == 2

    def test_extracts_zone_names(self):
        text = """Options and seed:99999
Chapel of Anticipation
  Random: Chapel of Anticipation --> Limgrave
Limgrave
"""
        result = parse_spoiler_log(text)
        zone_names = {z.name for z in result.zones}
        assert "Chapel of Anticipation" in zone_names
        assert "Limgrave" in zone_names

    def test_connection_types(self):
        text = """Options and seed:99999
A
  Random: A --> B
  Preexisting: A --> C
B
C
"""
        result = parse_spoiler_log(text)
        types = {c.conn_type for c in result.connections}
        assert "random" in types
        assert "preexisting" in types

    def test_boss_zone_marked(self):
        text = """Options and seed:99999
Stormveil Castle <<<<<
  Preexisting: Stormveil Castle --> Liurnia
Liurnia
"""
        result = parse_spoiler_log(text)
        boss_zones = [z for z in result.zones if z.is_boss]
        assert len(boss_zones) == 1
        assert boss_zones[0].name == "Stormveil Castle"

    def test_stops_at_optional_areas(self):
        text = """Options and seed:99999
A
  Random: A --> B
B
Optional areas:
C
  Random: C --> D
D
"""
        result = parse_spoiler_log(text)
        zone_names = {z.name for z in result.zones}
        # C and D should not be parsed (after Optional areas:)
        assert "C" not in zone_names
        assert "D" not in zone_names

    def test_empty_log_raises(self):
        # Empty string goes through seed parsing first, which fails
        with pytest.raises(SpoilerParseError, match="Could not find seed"):
            parse_spoiler_log("")

    def test_no_seed_raises(self):
        with pytest.raises(SpoilerParseError, match="Could not find seed"):
            parse_spoiler_log("Invalid header\nLimgrave")

    def test_no_zones_raises(self):
        with pytest.raises(SpoilerParseError, match="No zones found"):
            parse_spoiler_log("Options and seed:12345\nOptional areas:")

    def test_no_connections_raises(self):
        with pytest.raises(SpoilerParseError, match="No connections found"):
            parse_spoiler_log("Options and seed:12345\nLimgrave\nCaelid")

    def test_zone_ids_linked_to_connections(self):
        text = """Options and seed:99999
A
  Random: A --> B
B
"""
        result = parse_spoiler_log(text)
        conn = result.connections[0]
        zone_a = next(z for z in result.zones if z.name == "A")
        zone_b = next(z for z in result.zones if z.name == "B")
        assert conn.source_id == zone_a.id
        assert conn.target_id == zone_b.id


class TestOneWayDetection:
    """Tests for one-way connection detection patterns."""

    @pytest.mark.parametrize(
        "description,expected_one_way",
        [
            ("using the sending gate", True),
            ("abducted by maiden", True),
            ("warp to destination", True),
            ("resting in the coffin", True),
            ("lying down in bed", True),
            ("using the Pureblood Knight's Medal", True),
            ("dropping down to the right", True),  # Drop-down connections
            ("dropping into the boss fight", True),
            ("before boss arena", False),
            ("at the main gate", False),
            ("near the beach", False),
            ("return to entrance after boss", False),
            ("at the elevator", False),  # Elevators are bidirectional
        ],
    )
    def test_one_way_patterns(self, description, expected_one_way):
        line = f"  Random: Origin ({description}) --> Destination"
        conn = _parse_connection_line(line)
        assert conn is not None
        assert conn.is_inherently_one_way is expected_one_way

    def test_zone_name_containing_sending_gate_is_not_one_way(self):
        """Zone names containing 'Sending Gate' should NOT make a link one-way.

        Regression test: 'Volcano Manor - Hallway Opposite Sending Gate' was
        incorrectly marked as one-way because the pattern matched the zone name.
        """
        line = (
            "  Random: After Mohg, Lord of Blood (after Mohg's arena at the back left) "
            "--> Volcano Manor - Hallway Opposite Sending Gate "
            "(in the hallway towards the Imp Seal back to main Volcano Manor)"
        )
        conn = _parse_connection_line(line)
        assert conn is not None
        assert conn.source == "After Mohg, Lord of Blood"
        assert conn.target == "Volcano Manor - Hallway Opposite Sending Gate"
        assert conn.is_inherently_one_way is False

    def test_actual_sending_gate_usage_is_one_way(self):
        """Using a sending gate (in details) should be one-way."""
        line = (
            "  Random: Divine Tower of Limgrave (using the sending gate) "
            "--> Leyndell, Royal Capital (arriving at the Divine Bridge)"
        )
        conn = _parse_connection_line(line)
        assert conn is not None
        assert conn.is_inherently_one_way is True

    def test_return_to_entrance_fog_gate_is_bidirectional(self):
        """Boss exit fog gates (return to entrance) are bidirectional in randomizer.

        In vanilla, these are one-way teleports. But in the Fog Gate Randomizer,
        they become regular fog gates that can be traversed in both directions.
        """
        line = (
            "  Random: Consecrated Snowfield - Yelough Anix Tunnel "
            "(at the entrance from Consecrated Snowfield) "
            "--> Consecrated Snowfield - Yelough Anix Tunnel - Astel, Stars of Darkness "
            "(return to entrance after Astel, Stars of Darkness)"
        )
        conn = _parse_connection_line(line)
        assert conn is not None
        assert conn.source == "Consecrated Snowfield - Yelough Anix Tunnel"
        assert (
            conn.target == "Consecrated Snowfield - Yelough Anix Tunnel - Astel, Stars of Darkness"
        )
        assert conn.is_inherently_one_way is False

    def test_preexisting_drop_down_is_one_way(self):
        """Preexisting links with 'dropping' in description should be one-way.

        Regression test: Queen's Bedchamber -> Ashen Leyndell drop-down was
        incorrectly treated as bidirectional, causing propagation in wrong direction.
        """
        line = (
            "  Preexisting: Ashen Leyndell - Queen's Bedchamber --> "
            "Ashen Leyndell (instead of entering the sanctuary, dropping down to the right)"
        )
        conn = _parse_connection_line(line)
        assert conn is not None
        assert conn.conn_type == "preexisting"
        assert conn.source == "Ashen Leyndell - Queen's Bedchamber"
        assert conn.target == "Ashen Leyndell"
        assert conn.is_inherently_one_way is True  # Drop-down = one-way

    def test_preexisting_elevator_is_bidirectional(self):
        """Preexisting links with elevator should be bidirectional."""
        line = "  Preexisting: After Loretta --> Elphael (at the elevator)"
        conn = _parse_connection_line(line)
        assert conn is not None
        assert conn.conn_type == "preexisting"
        assert conn.is_inherently_one_way is False  # Elevator = bidirectional


class TestDataclasses:
    """Tests for dataclass structures."""

    def test_zone_info_defaults(self):
        zone = ZoneInfo(id="123", name="Test")
        assert zone.is_boss is False
        assert zone.scaling is None

    def test_connection_info_defaults(self):
        conn = ConnectionInfo(id="123", source="A", target="B")
        assert conn.conn_type == "random"
        assert conn.source_details == ""
        assert conn.target_details == ""
        assert conn.is_inherently_one_way is False

    def test_parse_result_defaults(self):
        result = ParseResult(seed=12345)
        assert result.zones == []
        assert result.connections == []
        assert result.options == ""


class TestWithRealSpoilerLogs:
    """Tests using real spoiler log files."""

    def test_parse_seed_1078869800(self, spoiler_log_1078869800):
        result = parse_spoiler_log(spoiler_log_1078869800)
        assert result.seed == 1078869800
        assert len(result.zones) > 50
        assert len(result.connections) > 100

    def test_parse_seed_1851144969(self, spoiler_log_1851144969):
        result = parse_spoiler_log(spoiler_log_1851144969)
        assert result.seed == 1851144969
        assert len(result.zones) > 50
        assert len(result.connections) > 100

    def test_all_connections_have_valid_zones(self, spoiler_log_1078869800):
        result = parse_spoiler_log(spoiler_log_1078869800)
        zone_names = {z.name for z in result.zones}
        for conn in result.connections:
            assert conn.source in zone_names, f"Source '{conn.source}' not in zones"
            assert conn.target in zone_names, f"Target '{conn.target}' not in zones"

    def test_connections_have_valid_zone_ids(self, spoiler_log_1078869800):
        result = parse_spoiler_log(spoiler_log_1078869800)
        zone_ids = {z.id for z in result.zones}
        for conn in result.connections:
            assert conn.source_id in zone_ids, f"source_id '{conn.source_id}' not found"
            assert conn.target_id in zone_ids, f"target_id '{conn.target_id}' not found"

    def test_has_both_connection_types(self, spoiler_log_1078869800):
        result = parse_spoiler_log(spoiler_log_1078869800)
        types = {c.conn_type for c in result.connections}
        assert "random" in types
        assert "preexisting" in types

    def test_has_boss_zones(self, spoiler_log_1078869800):
        result = parse_spoiler_log(spoiler_log_1078869800)
        boss_zones = [z for z in result.zones if z.is_boss]
        assert len(boss_zones) > 0

    def test_has_scaling_info(self, spoiler_log_1078869800):
        result = parse_spoiler_log(spoiler_log_1078869800)
        zones_with_scaling = [z for z in result.zones if z.scaling]
        assert len(zones_with_scaling) > 0

    def test_has_one_way_connections(self, spoiler_log_1078869800):
        result = parse_spoiler_log(spoiler_log_1078869800)
        one_way = [c for c in result.connections if c.is_inherently_one_way]
        # Real spoiler logs typically have some one-way connections (sending gates, etc.)
        assert len(one_way) > 0

    def test_chapel_of_anticipation_exists(self, spoiler_log_1078869800):
        """Chapel of Anticipation is always the starting zone."""
        result = parse_spoiler_log(spoiler_log_1078869800)
        zone_names = {z.name for z in result.zones}
        assert "Chapel of Anticipation" in zone_names
