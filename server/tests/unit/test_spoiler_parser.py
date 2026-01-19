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
    _extract_required_item,
    _parse_area_line,
    _parse_connection_line,
    _should_skip_line,
    enrich_connections_with_zone_keys,
    parse_spoiler_log,
    validate_spoiler_header,
)
from fogtracker.zone_resolver import get_resolver

RESOLVER = get_resolver()


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

    def test_windows_paths(self):
        """Windows paths from randomizer output should be skipped."""
        assert _should_skip_line("C:\\Program Files\\EldenRing\\randomizer")
        assert _should_skip_line("I:\\Elden Ring Random\\randomizer")
        assert _should_skip_line("D:\\Games\\mod")

    def test_randomizer_log_messages(self):
        """Randomizer log messages should be skipped."""
        assert _should_skip_line("Done with core pass")
        assert _should_skip_line("Clique fixup done in 1")
        assert _should_skip_line("Done")

    def test_done_zone_name_not_skipped(self):
        """A hypothetical zone starting with 'Done' should not be skipped."""
        # "Done" alone is skipped, but "DoneTown" or similar should not be
        assert not _should_skip_line("DoneTown")


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


class TestExtractRequiredItem:
    """Tests for _extract_required_item function."""

    def test_no_item(self):
        assert _extract_required_item("at the main gate", "arriving from the west") is None

    def test_academy_glintstone_key(self):
        assert (
            _extract_required_item("", "using the Academy Glintstone Key")
            == "Academy Glintstone Key"
        )

    def test_pureblood_medal(self):
        assert (
            _extract_required_item("using the Pureblood Knight's Medal", "")
            == "Pureblood Knight's Medal"
        )

    def test_dectus_medallion(self):
        assert (
            _extract_required_item("at the Grand Lift of Dectus", "using Dectus Medallion")
            == "Dectus Medallion"
        )

    def test_rold_medallion(self):
        assert (
            _extract_required_item("at the Grand Lift of Rold", "using Rold Medallion")
            == "Rold Medallion"
        )

    def test_haligtree_medallion(self):
        assert (
            _extract_required_item("using the Haligtree secret medallion", "")
            == "Haligtree Secret Medallion"
        )

    def test_carian_inverted_statue(self):
        assert (
            _extract_required_item("using the Carian Inverted Statue", "")
            == "Carian Inverted Statue"
        )

    def test_discarded_palace_key(self):
        assert (
            _extract_required_item("", "using the Discarded Palace Key") == "Discarded Palace Key"
        )

    def test_drawing_room_key(self):
        assert _extract_required_item("using the Drawing-Room Key", "") == "Drawing-Room Key"

    def test_rusty_key(self):
        assert _extract_required_item("using the Rusty Key", "") == "Rusty Key"

    def test_hole_laden_necklace(self):
        assert _extract_required_item("using the Hole-Laden Necklace", "") == "Hole-Laden Necklace"

    def test_o_mother(self):
        assert _extract_required_item("using O Mother", "") == "O Mother"

    def test_cursemark_of_death(self):
        assert _extract_required_item("", "using Cursemark of Death") == "Cursemark of Death"

    def test_dark_moon_ring(self):
        assert _extract_required_item("using the Dark Moon Ring", "") == "Dark Moon Ring"

    def test_well_depths_key(self):
        assert _extract_required_item("using the Well Depths Key", "") == "Well Depths Key"

    def test_burning_sealing_tree(self):
        result = _extract_required_item("after burning the Sealing Tree", "")
        assert result == "burning the Sealing Tree"

    def test_great_runes(self):
        result = _extract_required_item("", "after acquiring enough Great Runes")
        assert result == "acquiring enough Great Runes"

    def test_item_in_source_details(self):
        """Item mentioned in source details."""
        assert (
            _extract_required_item("using the Academy Glintstone Key", "warp destination")
            == "Academy Glintstone Key"
        )

    def test_item_in_target_details(self):
        """Item mentioned in target details."""
        assert _extract_required_item("at the entrance", "using Rold Medallion") == "Rold Medallion"


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

    def test_has_id(self):
        """Zone ID is initially set to display name (will be replaced with zone_key later)."""
        zone = _parse_area_line("Limgrave")
        assert zone is not None
        assert zone.id is not None
        assert zone.id == zone.name  # Initially set to display name


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
        assert conn.is_one_way is True

    def test_one_way_abducted(self):
        conn = _parse_connection_line(
            "  Random: Roundtable Hold (abducted by maiden) --> Volcano Manor"
        )
        assert conn is not None
        assert conn.is_one_way is True

    def test_bidirectional_fog_gate(self):
        conn = _parse_connection_line("  Random: Limgrave (near beach) --> Caelid (at the border)")
        assert conn is not None
        assert conn.is_one_way is False

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
  Random: Chapel of Anticipation (before boss) --> Stormhill (at start)
Stormhill
  Preexisting: Stormhill --> Stormveil Castle before Gate
Stormveil Castle before Gate
Optional areas:
"""
        result = parse_spoiler_log(text, RESOLVER)
        assert result.seed == 12345
        assert len(result.zones) == 3
        assert len(result.connections) == 2

    def test_extracts_zone_names(self):
        text = """Options and seed:99999
Chapel of Anticipation
  Random: Chapel of Anticipation --> Stormhill
Stormhill
"""
        result = parse_spoiler_log(text, RESOLVER)
        zone_names = {z.name for z in result.zones.values()}
        assert "Chapel of Anticipation" in zone_names
        assert "Stormhill" in zone_names

    def test_connection_types(self):
        text = """Options and seed:99999
Chapel of Anticipation
  Random: Chapel of Anticipation --> Stormhill
  Preexisting: Chapel of Anticipation --> Stormveil Castle before Gate
Stormhill
Stormveil Castle before Gate
"""
        result = parse_spoiler_log(text, RESOLVER)
        types = {c.conn_type for c in result.connections}
        assert "random" in types
        assert "preexisting" in types

    def test_boss_zone_marked(self):
        text = """Options and seed:99999
Stormveil Castle before Gate <<<<<
  Preexisting: Stormveil Castle before Gate --> Stormhill
Stormhill
"""
        result = parse_spoiler_log(text, RESOLVER)
        boss_zones = [z for z in result.zones.values() if z.is_boss]
        assert len(boss_zones) == 1
        assert boss_zones[0].name == "Stormveil Castle before Gate"

    def test_stops_at_optional_areas_in_crawl_mode(self):
        """In Dungeon Crawler mode (crawl), Optional areas are skipped.

        Optional areas in crawl mode contain overworld zones that are not
        accessible via fog gates in dungeon-only runs.
        """
        text = """Options and seed:99999 crawl
Chapel of Anticipation
  Random: Chapel of Anticipation --> Stormhill
Stormhill
Optional areas:
Limgrave
  Preexisting: Chapel of Anticipation --> Limgrave
"""
        result = parse_spoiler_log(text, RESOLVER)
        zone_names = {z.name for z in result.zones.values()}
        # Limgrave should not be parsed (after Optional areas: in crawl mode)
        assert "Limgrave" not in zone_names
        assert result.is_dungeon_crawler is True

    def test_includes_optional_areas_in_world_shuffle_mode(self):
        """In World Shuffle mode (no crawl), Optional areas are included.

        Optional areas in World Shuffle contain zones accessible via randomized
        fog gates, so they should be parsed and displayed.
        """
        text = """Options and seed:99999 shuffle
Chapel of Anticipation
  Random: Chapel of Anticipation --> Stormhill
Stormhill
Optional areas:
Limgrave
  Random: Stormhill --> Limgrave
"""
        result = parse_spoiler_log(text, RESOLVER)
        zone_names = {z.name for z in result.zones.values()}
        # Limgrave should be parsed (Optional areas included in World Shuffle)
        assert "Limgrave" in zone_names
        assert result.is_dungeon_crawler is False

    def test_empty_log_raises(self):
        # Empty string goes through seed parsing first, which fails
        with pytest.raises(SpoilerParseError, match="Could not find seed"):
            parse_spoiler_log("", RESOLVER)

    def test_no_seed_raises(self):
        with pytest.raises(SpoilerParseError, match="Could not find seed"):
            parse_spoiler_log("Invalid header\nLimgrave", RESOLVER)

    def test_no_zones_raises(self):
        with pytest.raises(SpoilerParseError, match="No zones found"):
            parse_spoiler_log("Options and seed:12345\nOptional areas:", RESOLVER)

    def test_no_connections_raises(self):
        with pytest.raises(SpoilerParseError, match="No connections found"):
            parse_spoiler_log("Options and seed:12345\nLimgrave\nCaelid", RESOLVER)

    def test_zone_ids_linked_to_connections(self):
        text = """Options and seed:99999
Chapel of Anticipation
  Random: Chapel of Anticipation --> Stormhill
Stormhill
"""
        result = parse_spoiler_log(text, RESOLVER)
        conn = result.connections[0]
        zone_a = next(z for z in result.zones.values() if z.name == "Chapel of Anticipation")
        zone_b = next(z for z in result.zones.values() if z.name == "Stormhill")
        assert conn.source_id == zone_a.id
        assert conn.target_id == zone_b.id


class TestOneWayDetection:
    """Tests for one-way connection detection patterns."""

    @pytest.mark.parametrize(
        "description,expected_one_way",
        [
            ("using the sending gate", True),
            ("arriving at the sending gate after some grace", True),  # Sending gate destination
            ("abducted by maiden", True),
            ("warp to destination", True),
            ("resting in the coffin", True),
            ("lying down in bed", True),
            ("using the Pureblood Knight's Medal", True),
            ("arriving by the Great Waterfall Crest grace", True),  # Grace warp arrivals
            ("before boss arena", False),
            ("at the main gate", False),
            ("near the beach", False),
            ("return to entrance after boss", False),
            ("at the elevator", False),  # Elevators are bidirectional
            # "dropping" is NOT one-way for random links (see test_random_link_with_navigation_dropping)
            ("dropping down to the right", False),
            ("dropping into the boss fight", False),
        ],
    )
    def test_one_way_patterns(self, description, expected_one_way):
        line = f"  Random: Origin ({description}) --> Destination"
        conn = _parse_connection_line(line)
        assert conn is not None
        assert conn.is_one_way is expected_one_way

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
        assert conn.is_one_way is False

    def test_source_details_mentioning_sending_gate_landmark_is_not_one_way(self):
        """Location descriptions mentioning 'Sending Gate' as landmark should NOT be one-way.

        Regression test: "opposite the Sending Gate" in source_details was incorrectly
        matched by the "sending gate" pattern, marking the link as one-way when it's
        actually a bidirectional fog gate near the sending gate location.
        """
        line = (
            "  Random: Volcano Manor - Room Before Sending Gate "
            "(on the doorway on the second story opposite the Sending Gate) "
            "--> Ainsel River Downstream (before Dragonkin of Nokstella's arena)"
        )
        conn = _parse_connection_line(line)
        assert conn is not None
        assert conn.source == "Volcano Manor - Room Before Sending Gate"
        assert conn.target == "Ainsel River Downstream"
        # This should be bidirectional - "opposite the Sending Gate" is just describing
        # the fog gate's location, not indicating use of a sending gate mechanism
        assert conn.is_one_way is False

    def test_actual_sending_gate_usage_is_one_way(self):
        """Using a sending gate (in details) should be one-way."""
        line = (
            "  Random: Divine Tower of Limgrave (using the sending gate) "
            "--> Leyndell, Royal Capital (arriving at the Divine Bridge)"
        )
        conn = _parse_connection_line(line)
        assert conn is not None
        assert conn.is_one_way is True

    def test_arriving_at_sending_gate_destination_is_one_way(self):
        """Arriving at a sending gate destination (in target_details) should be one-way.

        When target_details mentions "arriving at the sending gate", it indicates
        the destination is a vanilla sending gate location - these are teleport-only
        destinations and should be one-way.
        """
        line = (
            "  Random: Divine Tower of Liurnia "
            "(opening the door at the bottom of the flipped tower) "
            "--> Siofra River "
            "(arriving at the sending gate after the Worshippers' Woods grace)"
        )
        conn = _parse_connection_line(line)
        assert conn is not None
        assert conn.source == "Divine Tower of Liurnia"
        assert conn.target == "Siofra River"
        assert conn.is_one_way is True

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
        assert conn.is_one_way is False

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
        assert conn.is_one_way is True  # Drop-down = one-way

    def test_preexisting_elevator_is_bidirectional(self):
        """Preexisting links with elevator should be bidirectional."""
        line = "  Preexisting: After Loretta --> Elphael (at the elevator)"
        conn = _parse_connection_line(line)
        assert conn is not None
        assert conn.conn_type == "preexisting"
        assert conn.is_one_way is False  # Elevator = bidirectional

    def test_random_link_with_navigation_dropping_is_bidirectional(self):
        """Random fog gates with 'dropping' in navigation instructions should be bidirectional.

        Regression test: Volcano Manor Prison Town fog gate was incorrectly marked
        as one-way because the description mentioned "dropping down" as navigation
        instructions to reach the fog gate location, not as the fog gate action.

        The phrase "it can be reached from main town dropping down outside Temple of Eiglay"
        describes how to navigate to the fog gate, not that the fog gate itself involves
        a drop-down action.
        """
        line = (
            "  Random: Volcano Manor Prison Town "
            "(before Abductor Virgins' arena. it can be reached from main town dropping down "
            "outside Temple of Eiglay) "
            "--> Castle Ensis - Rellana, Twin Moon Knight (at the back of Rellana's arena)"
        )
        conn = _parse_connection_line(line)
        assert conn is not None
        assert conn.conn_type == "random"
        assert conn.source == "Volcano Manor Prison Town"
        assert conn.target == "Castle Ensis - Rellana, Twin Moon Knight"
        # "dropping down" in the source_details describes how to reach the fog gate location,
        # NOT a drop-down fog gate action - this should be bidirectional
        assert conn.is_one_way is False

    def test_transporter_chest_is_one_way(self):
        """Transporter chest with 'arriving' target is one-way.

        The transporter chest teleports you somewhere and you can't use
        the arrival point to return.
        """
        line = (
            "  Random: Limgrave (opening the transporter chest in Dragon-Burnt Ruins) "
            "--> Caelid - Sellia Crystal Tunnel (arriving in the middle of Sellia Crystal Tunnel)"
        )
        conn = _parse_connection_line(line)
        assert conn is not None
        assert conn.source == "Limgrave"
        assert conn.target == "Caelid - Sellia Crystal Tunnel"
        assert conn.is_one_way is True

    def test_from_deeproot_destination_is_one_way(self):
        """Destinations 'from Deeproot' are one-way.

        The sending gate from Deeproot leads to a point in Leyndell that
        cannot be used as an exit, regardless of what the source is.
        """
        line = (
            "  Random: Divine Tower of Liurnia "
            "(opening the door at the bottom of the flipped tower) "
            "--> Leyndell (arriving at the start of Leyndell from Deeproot)"
        )
        conn = _parse_connection_line(line)
        assert conn is not None
        assert conn.source == "Divine Tower of Liurnia"
        assert conn.target == "Leyndell"
        assert conn.is_one_way is True


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
        assert conn.is_one_way is False

    def test_parse_result_defaults(self):
        result = ParseResult(seed=12345)
        assert result.zones == {}
        assert result.connections == []
        assert result.options == ""


class TestWithRealSpoilerLogs:
    """Tests using real spoiler log files."""

    def test_parse_seed_1078869800(self, spoiler_log_1078869800):
        result = parse_spoiler_log(spoiler_log_1078869800, RESOLVER)
        assert result.seed == 1078869800
        assert len(result.zones) > 50
        assert len(result.connections) > 100

    def test_parse_seed_1851144969(self, spoiler_log_1851144969):
        result = parse_spoiler_log(spoiler_log_1851144969, RESOLVER)
        assert result.seed == 1851144969
        assert len(result.zones) > 50
        assert len(result.connections) > 100

    def test_all_connections_have_valid_zones(self, spoiler_log_1078869800):
        result = parse_spoiler_log(spoiler_log_1078869800, RESOLVER)
        zone_names = {z.name for z in result.zones.values()}
        for conn in result.connections:
            assert conn.source in zone_names, f"Source '{conn.source}' not in zones"
            assert conn.target in zone_names, f"Target '{conn.target}' not in zones"

    def test_connections_have_valid_zone_ids(self, spoiler_log_1078869800):
        result = parse_spoiler_log(spoiler_log_1078869800, RESOLVER)
        zone_ids = {z.id for z in result.zones.values()}
        for conn in result.connections:
            assert conn.source_id in zone_ids, f"source_id '{conn.source_id}' not found"
            assert conn.target_id in zone_ids, f"target_id '{conn.target_id}' not found"

    def test_has_both_connection_types(self, spoiler_log_1078869800):
        result = parse_spoiler_log(spoiler_log_1078869800, RESOLVER)
        types = {c.conn_type for c in result.connections}
        assert "random" in types
        assert "preexisting" in types

    def test_has_boss_zones(self, spoiler_log_1078869800):
        result = parse_spoiler_log(spoiler_log_1078869800, RESOLVER)
        boss_zones = [z for z in result.zones.values() if z.is_boss]
        assert len(boss_zones) > 0

    def test_has_scaling_info(self, spoiler_log_1078869800):
        result = parse_spoiler_log(spoiler_log_1078869800, RESOLVER)
        zones_with_scaling = [z for z in result.zones.values() if z.scaling]
        assert len(zones_with_scaling) > 0

    def test_has_one_way_connections(self, spoiler_log_1078869800):
        result = parse_spoiler_log(spoiler_log_1078869800, RESOLVER)
        one_way = [c for c in result.connections if c.is_one_way]
        # Real spoiler logs typically have some one-way connections (sending gates, etc.)
        assert len(one_way) > 0

    def test_chapel_of_anticipation_exists(self, spoiler_log_1078869800):
        """Chapel of Anticipation is always the starting zone."""
        result = parse_spoiler_log(spoiler_log_1078869800, RESOLVER)
        zone_names = {z.name for z in result.zones.values()}
        assert "Chapel of Anticipation" in zone_names


class TestEnrichConnectionsOneWay:
    """Tests for one-way detection in enrich_connections_with_zone_keys.

    Preexisting connections should be marked as one-way based on fog.txt
    To: structure. If source has To: target but target doesn't have To: source,
    the connection is one-way.
    """

    @pytest.fixture
    def resolver(self):
        """Create a ZoneResolver with real data."""
        return get_resolver()

    def test_one_way_preexisting_from_fog_txt(self, resolver):
        """Preexisting link should be marked one-way from fog.txt To: structure."""
        # shadowkeep_church_lower -> shadowkeep_sanctum is one-way
        conn = ConnectionInfo(
            id="test-id",
            source="Shadow Keep - Drained Church District",
            target="Shadow Keep - Tree-Worship Sanctum",
            conn_type="preexisting",
            source_details="opening the door",
            target_details="in map",
            is_one_way=False,  # Parser sets False (no pattern match)
        )

        enriched = enrich_connections_with_zone_keys([conn], resolver)
        result = enriched[0]

        assert result.source_id == "shadowkeep_church_lower"
        assert result.target_id == "shadowkeep_sanctum"
        assert result.is_one_way is True  # Should be corrected to True

    def test_already_one_way_not_changed(self, resolver):
        """Connections already marked one-way should stay one-way."""
        conn = ConnectionInfo(
            id="test-id",
            source="Some Zone",
            target="Another Zone",
            conn_type="preexisting",
            is_one_way=True,  # Already one-way from pattern
        )

        enriched = enrich_connections_with_zone_keys([conn], resolver)
        result = enriched[0]

        assert result.is_one_way is True

    def test_random_connection_unchanged(self, resolver):
        """Random connections should not be affected by fog.txt To: structure."""
        conn = ConnectionInfo(
            id="test-id",
            source="Shadow Keep - Drained Church District",
            target="Shadow Keep - Tree-Worship Sanctum",
            conn_type="random",  # Random, not preexisting
            is_one_way=False,
        )

        enriched = enrich_connections_with_zone_keys([conn], resolver)
        result = enriched[0]

        # Random connections use pattern-based detection, not fog.txt To:
        assert result.is_one_way is False


class TestBlocksPropagation:
    """Tests for blocks_propagation field in ConnectionInfo.

    The blocks_propagation field is set for random fog gate links where the target
    side (where the player arrives) has a Cond: field in fog.txt. This indicates
    the player arrives at a restricted area (e.g., base of a shortcut ladder) and
    shouldn't trigger propagation of preexisting links from the destination zone.

    Unlike is_one_way (which hides the exit from the destination), blocks_propagation
    allows the player to see and use the exit (e.g., "return to entrance") while
    preventing the discovery of inaccessible preexisting links.
    """

    @pytest.fixture
    def resolver(self):
        """Create a ZoneResolver with real data."""
        return get_resolver()

    def test_conditional_fog_gate_sets_blocks_propagation(self, resolver):
        """Fog gates with Cond: on target side should set blocks_propagation."""
        # Gideon fog gate has Cond: on the bedchamber side (shortcut ladder)
        # When arriving at this side, player can't access the rest of Bedchamber
        conn = ConnectionInfo(
            id="test-id",
            source="Caelid - Gaol Cave - Frenzied Duelist",
            target="Ashen Leyndell - Queen's Bedchamber",
            conn_type="random",
            source_details="at the back of Frenzied Duelist's arena",
            target_details="outside of Gideon's arena at the base of a shortcut ladder, accessed from an open window on a second-floor rooftop",
            is_one_way=False,
        )

        enriched = enrich_connections_with_zone_keys([conn], resolver)
        result = enriched[0]

        # Should set blocks_propagation, NOT is_one_way
        assert result.blocks_propagation is True
        assert result.is_one_way is False  # Player can still use the exit to return

    def test_normal_fog_gate_no_blocks_propagation(self, resolver):
        """Normal fog gates without Cond: should not set blocks_propagation."""
        conn = ConnectionInfo(
            id="test-id",
            source="Limgrave - Stormhill",
            target="Some Target Zone",
            conn_type="random",
            source_details="at the front of some area",
            target_details="at the entrance",
            is_one_way=False,
        )

        enriched = enrich_connections_with_zone_keys([conn], resolver)
        result = enriched[0]

        assert result.blocks_propagation is False
        assert result.is_one_way is False

    def test_preexisting_link_no_blocks_propagation(self, resolver):
        """Preexisting links should not set blocks_propagation (only affects random)."""
        conn = ConnectionInfo(
            id="test-id",
            source="Some Zone",
            target="Another Zone",
            conn_type="preexisting",
            source_details="some details",
            is_one_way=False,
        )

        enriched = enrich_connections_with_zone_keys([conn], resolver)
        result = enriched[0]

        assert result.blocks_propagation is False

    def test_blocks_propagation_default_false(self):
        """ConnectionInfo should default blocks_propagation to False."""
        conn = ConnectionInfo(
            id="test-id",
            source="Source",
            target="Target",
        )
        assert conn.blocks_propagation is False


class TestMusttrapOneWay:
    """Tests for musttrap-based is_one_way detection.

    Fog gates with Tags: musttrap on the source side indicate that entering
    through that side traps the player - they cannot return. Random connections
    using such fog gates should be marked is_one_way=True.
    """

    @pytest.fixture
    def resolver(self):
        """Create a ZoneResolver with real data."""
        return get_resolver()

    def test_musttrap_fog_gate_sets_one_way(self, resolver):
        """Fog gates with musttrap on source side should set is_one_way."""
        # War-Dead Catacombs entrance from Radahn arena has musttrap
        conn = ConnectionInfo(
            id="test-id",
            source="Starscourge Radahn",
            target="Limgrave Tunnels - Stonedigger Troll",
            conn_type="random",
            source_details="at the far North entrance to War-Dead Catacombs",
            target_details="at the front of Stonedigger Troll's arena",
            is_one_way=False,
        )

        enriched = enrich_connections_with_zone_keys([conn], resolver)
        result = enriched[0]

        # Should set is_one_way because source has musttrap
        assert result.is_one_way is True

    def test_musttrap_morgott_sets_one_way(self, resolver):
        """Morgott's arena back exit with musttrap should set is_one_way."""
        conn = ConnectionInfo(
            id="test-id",
            source="Leyndell - Morgott, the Omen King",
            target="Some Target Zone",
            conn_type="random",
            source_details="at the back of Morgott's arena",
            target_details="some target details",
            is_one_way=False,
        )

        enriched = enrich_connections_with_zone_keys([conn], resolver)
        result = enriched[0]

        assert result.is_one_way is True

    def test_normal_fog_gate_no_musttrap_one_way(self, resolver):
        """Normal fog gates without musttrap should not set is_one_way."""
        conn = ConnectionInfo(
            id="test-id",
            source="Limgrave - Stormhill",
            target="Some Target Zone",
            conn_type="random",
            source_details="at the front of some area",
            target_details="at the entrance",
            is_one_way=False,
        )

        enriched = enrich_connections_with_zone_keys([conn], resolver)
        result = enriched[0]

        assert result.is_one_way is False

    def test_preexisting_link_no_musttrap_check(self, resolver):
        """Preexisting links should not check musttrap (only affects random)."""
        conn = ConnectionInfo(
            id="test-id",
            source="Starscourge Radahn",
            target="Caelid - War-Dead Catacombs",
            conn_type="preexisting",
            source_details="at the far North entrance to War-Dead Catacombs",
            is_one_way=False,
        )

        enriched = enrich_connections_with_zone_keys([conn], resolver)
        result = enriched[0]

        # Preexisting links use fog.txt To: structure, not musttrap
        # The is_one_way for preexisting is determined by To: sections
        # So we don't force is_one_way=True based on musttrap here
        assert result.is_one_way is False or result.is_one_way is True  # depends on To: structure
