"""Unit tests for zone_matching module.

Tests pure functions for zone name matching, graph traversal,
and discovery logic.
"""

import pytest

from fogtracker.zone_matching import (
    build_full_adjacency,
    build_preexisting_adjacency,
    build_zone_pairs_index,
    compute_backprop_cost,
    compute_discovery_stats,
    compute_total_zones,
    compute_zone_exits,
    expand_discovered_links,
    find_all_matching_zone_pairs,
    find_all_matching_zone_pairs_by_ids,
    find_candidate_zones,
    find_matching_zone_pair,
    find_matching_zone_pair_by_ids,
    find_path_prioritizing_discovered,
    find_reachable_nodes,
    find_similar_zones,
    find_zone_pair,
    find_zone_pair_by_ids,
    get_discovered_nodes,
    get_zone_link_id,
    get_zones_via_preexisting,
    is_accessible_from_start,
    is_link_discovered,
    link_exists,
    names_match,
    strip_parenthetical,
    undiscover_zone,
)


class TestStripParenthetical:
    """Tests for strip_parenthetical function."""

    def test_no_parentheses(self):
        assert strip_parenthetical("Limgrave") == "Limgrave"

    def test_with_parentheses(self):
        assert strip_parenthetical("Limgrave (near beach)") == "Limgrave"

    def test_with_long_parenthetical(self):
        result = strip_parenthetical("Zone Name (some detailed description here)")
        assert result == "Zone Name"

    def test_nested_parentheses_only_strips_last(self):
        # Regex only matches the final parenthetical
        assert strip_parenthetical("Zone (a) (b)") == "Zone (a)"

    def test_empty_parentheses(self):
        # Regex requires at least one character in parentheses
        # Empty parentheses are not stripped
        assert strip_parenthetical("Zone ()") == "Zone ()"

    def test_parentheses_in_middle_not_stripped(self):
        # Parentheses not at the end are preserved
        assert strip_parenthetical("Zone (a) Name") == "Zone (a) Name"


class TestNamesMatch:
    """Tests for names_match function."""

    def test_exact_match(self):
        assert names_match("Limgrave", "Limgrave")

    def test_normalized_match_left(self):
        assert names_match("Limgrave (detail)", "Limgrave")

    def test_normalized_match_right(self):
        assert names_match("Limgrave", "Limgrave (detail)")

    def test_both_have_parentheses_same(self):
        assert names_match("Limgrave (beach)", "Limgrave (beach)")

    def test_both_have_parentheses_different(self):
        # Current implementation: if both have parentheses, they must match exactly
        # or one must match the stripped version of the other
        # "Limgrave (beach)" vs "Limgrave (cliff)" - neither matches the other's stripped form
        assert not names_match("Limgrave (beach)", "Limgrave (cliff)")

    def test_no_match(self):
        assert not names_match("Limgrave", "Caelid")

    def test_partial_match_fails(self):
        assert not names_match("Limgrave", "Limgrave East")

    def test_case_sensitive(self):
        # Current implementation is case-sensitive
        assert not names_match("Limgrave", "limgrave")


class TestBuildPreexistingAdjacency:
    """Tests for build_preexisting_adjacency function."""

    def test_only_includes_preexisting(self, simple_zone_pairs):
        adj = build_preexisting_adjacency(simple_zone_pairs)
        # Should not include random links (chapel_start is only in random links)
        assert "chapel_start" not in adj

    def test_bidirectional_preexisting(self, simple_zone_pairs):
        adj = build_preexisting_adjacency(simple_zone_pairs)
        # limgrave <-> stormveil_castle
        assert any(dest == "stormveil_castle" for dest, _ in adj.get("limgrave", []))
        assert any(dest == "limgrave" for dest, _ in adj.get("stormveil_castle", []))

    def test_returns_is_bidirectional_flag(self, simple_zone_pairs):
        adj = build_preexisting_adjacency(simple_zone_pairs)
        # caelid <-> dragonbarrow is bidirectional
        caelid_neighbors = adj.get("caelid", [])
        dragonbarrow_entry = next(
            (dest, is_bidir) for dest, is_bidir in caelid_neighbors if dest == "dragonbarrow"
        )
        assert dragonbarrow_entry[1] is True  # is_bidirectional


class TestBuildFullAdjacency:
    """Tests for build_full_adjacency function."""

    def test_includes_all_link_types(self, simple_zone_pairs):
        adj = build_full_adjacency(simple_zone_pairs)
        # Should include both random and preexisting (keyed by zone_id)
        assert "chapel_start" in adj
        assert "limgrave" in adj

    def test_random_links_bidirectional_by_default(self, simple_zone_pairs):
        adj = build_full_adjacency(simple_zone_pairs)
        # chapel_start -> limgrave is random, should be bidirectional
        chapel_neighbors = adj.get("chapel_start", [])
        assert any(dest == "limgrave" for dest, _, _ in chapel_neighbors)
        limgrave_neighbors = adj.get("limgrave", [])
        assert any(dest == "chapel_start" for dest, _, _ in limgrave_neighbors)

    def test_one_way_link_not_reversed(self, simple_zone_pairs):
        adj = build_full_adjacency(simple_zone_pairs)
        # sending_gate_origin -> divine_tower is one-way
        assert any(dest == "divine_tower" for dest, _, _ in adj.get("sending_gate_origin", []))
        # divine_tower should NOT have reverse to sending_gate_origin
        divine_tower_neighbors = adj.get("divine_tower", [])
        assert not any(dest == "sending_gate_origin" for dest, _, _ in divine_tower_neighbors)


class TestFindZonePair:
    """Tests for find_zone_pair function (now uses zone_ids)."""

    def test_direct_match(self, simple_zone_pairs):
        pair = find_zone_pair(simple_zone_pairs, "chapel_start", "limgrave")
        assert pair is not None
        assert pair["id"] == "link-1"

    def test_reverse_match_for_random(self, simple_zone_pairs):
        # Random links can be found in either direction
        pair = find_zone_pair(simple_zone_pairs, "limgrave", "chapel_start")
        assert pair is not None
        assert pair["id"] == "link-1"

    def test_preexisting_no_reverse_match(self, simple_zone_pairs):
        # Preexisting links are directional
        # link-2 is limgrave -> stormveil_castle
        pair = find_zone_pair(simple_zone_pairs, "limgrave", "stormveil_castle")
        assert pair is not None
        assert pair["id"] == "link-2"

        # Reverse should find link-3 (stormveil_castle -> limgrave), not link-2
        pair_reverse = find_zone_pair(simple_zone_pairs, "stormveil_castle", "limgrave")
        assert pair_reverse is not None
        assert pair_reverse["id"] == "link-3"

    def test_no_match(self, simple_zone_pairs):
        pair = find_zone_pair(simple_zone_pairs, "nonexistent", "limgrave")
        assert pair is None


class TestIsAccessibleFromStart:
    """Tests for is_accessible_from_start function."""

    def test_start_node_always_accessible(self, simple_zone_pairs, starting_zone_id):
        assert is_accessible_from_start([], starting_zone_id, simple_zone_pairs, starting_zone_id)

    def test_unreachable_without_discoveries(self, simple_zone_pairs, starting_zone_id):
        # caelid is not accessible without discovering links
        assert not is_accessible_from_start([], "caelid", simple_zone_pairs, starting_zone_id)

    def test_accessible_via_discovered_link(
        self, simple_zone_pairs, discovered_chapel_to_limgrave, starting_zone_id
    ):
        # limgrave is accessible via chapel_start -> limgrave
        assert is_accessible_from_start(
            discovered_chapel_to_limgrave, "limgrave", simple_zone_pairs, starting_zone_id
        )

    def test_accessible_via_chain(self, simple_zone_pairs, discovered_to_caelid, starting_zone_id):
        # caelid is accessible via chapel_start -> limgrave -> caelid
        assert is_accessible_from_start(
            discovered_to_caelid, "caelid", simple_zone_pairs, starting_zone_id
        )

    def test_isolated_zone_not_accessible(
        self, simple_zone_pairs, discovered_to_caelid, starting_zone_id
    ):
        # "isolated_zone" is not connected to the main graph
        assert not is_accessible_from_start(
            discovered_to_caelid, "isolated_zone", simple_zone_pairs, starting_zone_id
        )


class TestGetDiscoveredNodes:
    """Tests for get_discovered_nodes function."""

    def test_always_includes_start(self, simple_zone_pairs, starting_zone_id):
        nodes = get_discovered_nodes([], simple_zone_pairs, starting_zone_id)
        assert starting_zone_id in nodes

    def test_includes_link_endpoints(
        self, simple_zone_pairs, discovered_chapel_to_limgrave, starting_zone_id
    ):
        nodes = get_discovered_nodes(
            discovered_chapel_to_limgrave, simple_zone_pairs, starting_zone_id
        )
        assert "chapel_start" in nodes
        assert "limgrave" in nodes


class TestFindReachableNodes:
    """Tests for find_reachable_nodes function."""

    def test_only_start_without_discoveries(self, simple_zone_pairs, starting_zone_id):
        reachable = find_reachable_nodes([], simple_zone_pairs, starting_zone_id)
        assert reachable == {starting_zone_id}

    def test_reachable_via_discoveries(
        self, simple_zone_pairs, discovered_to_caelid, starting_zone_id
    ):
        reachable = find_reachable_nodes(discovered_to_caelid, simple_zone_pairs, starting_zone_id)
        assert "limgrave" in reachable
        assert "caelid" in reachable
        # stormveil_castle not discovered (only preexisting, not discovered)
        assert "stormveil_castle" not in reachable


class TestGetZonesViaPreexisting:
    """Tests for get_zones_via_preexisting function."""

    def test_returns_connected_preexisting_zones(self, simple_zone_pairs):
        # From limgrave, stormveil_castle is reachable via preexisting
        zones = get_zones_via_preexisting(simple_zone_pairs, "limgrave")
        assert "limgrave" in zones
        assert "stormveil_castle" in zones

    def test_includes_start_zone(self, simple_zone_pairs):
        zones = get_zones_via_preexisting(simple_zone_pairs, "caelid")
        assert "caelid" in zones

    def test_does_not_cross_random_links(self, simple_zone_pairs):
        # From limgrave, cannot reach caelid (random link)
        zones = get_zones_via_preexisting(simple_zone_pairs, "limgrave")
        assert "caelid" not in zones


class TestComputeBackpropCost:
    """Tests for compute_backprop_cost function."""

    def test_already_accessible_returns_zero(
        self, simple_zone_pairs, discovered_chapel_to_limgrave, starting_zone_id
    ):
        # limgrave is accessible, cost = 0
        cost = compute_backprop_cost(
            simple_zone_pairs, discovered_chapel_to_limgrave, "limgrave", starting_zone_id
        )
        assert cost == 0

    def test_start_node_returns_zero(self, simple_zone_pairs, starting_zone_id):
        cost = compute_backprop_cost(simple_zone_pairs, [], starting_zone_id, starting_zone_id)
        assert cost == 0

    def test_one_random_link_away(self, simple_zone_pairs, starting_zone_id):
        # limgrave requires 1 random link from START
        cost = compute_backprop_cost(simple_zone_pairs, [], "limgrave", starting_zone_id)
        assert cost == 1

    def test_path_through_preexisting_cheaper(self, simple_zone_pairs, starting_zone_id):
        # stormveil_castle is reachable via limgrave (1 random) + preexisting
        # Cost should be 1 (only the random link counts)
        cost = compute_backprop_cost(simple_zone_pairs, [], "stormveil_castle", starting_zone_id)
        assert cost == 1

    def test_isolated_zone_returns_minus_one(self, simple_zone_pairs, starting_zone_id):
        # Isolated zones are unreachable
        cost = compute_backprop_cost(simple_zone_pairs, [], "isolated_zone", starting_zone_id)
        assert cost == -1

    def test_tiebreaker_scenario(self):
        """
        Simulate tie-breaking scenario: two matches with different backprop costs.

        Graph structure:
        START -> A (random) -> B (preexisting) -> C (preexisting)
        START -> X (random) -> Y (random) -> Z (random)

        Cost to reach C = 1 (one random link: START->A)
        Cost to reach Z = 3 (three random links: START->X, X->Y, Y->Z)

        The algorithm should prefer C (lower cost).
        """
        starting_zone_id = "start"
        zone_pairs = [
            # Path to C: 1 random + 2 preexisting
            {
                "id": "1",
                "type": "random",
                "source": "Chapel of Anticipation",
                "source_id": "start",
                "target": "Zone A",
                "target_id": "zone_a",
            },
            {
                "id": "2",
                "type": "preexisting",
                "source": "Zone A",
                "source_id": "zone_a",
                "target": "Zone B",
                "target_id": "zone_b",
            },
            {
                "id": "3",
                "type": "preexisting",
                "source": "Zone B",
                "source_id": "zone_b",
                "target": "Zone C",
                "target_id": "zone_c",
            },
            # Path to Z: 3 random
            {
                "id": "4",
                "type": "random",
                "source": "Chapel of Anticipation",
                "source_id": "start",
                "target": "Zone X",
                "target_id": "zone_x",
            },
            {
                "id": "5",
                "type": "random",
                "source": "Zone X",
                "source_id": "zone_x",
                "target": "Zone Y",
                "target_id": "zone_y",
            },
            {
                "id": "6",
                "type": "random",
                "source": "Zone Y",
                "source_id": "zone_y",
                "target": "Zone Z",
                "target_id": "zone_z",
            },
            # Fog gates at C and Z leading to different destinations
            {
                "id": "fog_c",
                "type": "random",
                "source": "Zone C",
                "source_id": "zone_c",
                "target": "Far Away",
                "target_id": "far_away",
            },
            {
                "id": "fog_z",
                "type": "random",
                "source": "Zone Z",
                "source_id": "zone_z",
                "target": "Far Away 2",
                "target_id": "far_away_2",
            },
        ]
        discovered_links = []

        # Cost to reach zone_c (1 random link via zone_a)
        cost_c = compute_backprop_cost(zone_pairs, discovered_links, "zone_c", starting_zone_id)
        # Cost to reach zone_z (3 random links via zone_x, zone_y)
        cost_z = compute_backprop_cost(zone_pairs, discovered_links, "zone_z", starting_zone_id)

        assert cost_c == 1, f"Expected cost 1 for zone_c, got {cost_c}"
        assert cost_z == 3, f"Expected cost 3 for zone_z, got {cost_z}"
        assert cost_c < cost_z, "zone_c should have lower cost than zone_z"


class TestUndiscoverZone:
    """Tests for undiscover_zone function."""

    def test_cannot_undiscover_start(self, simple_zone_pairs, starting_zone_id):
        links, removed = undiscover_zone([], starting_zone_id, simple_zone_pairs, starting_zone_id)
        assert removed == []

    def test_undiscover_removes_zone_links(
        self, simple_zone_pairs, discovered_chapel_to_limgrave, starting_zone_id
    ):
        links, removed = undiscover_zone(
            discovered_chapel_to_limgrave, "limgrave", simple_zone_pairs, starting_zone_id
        )
        assert "limgrave" in removed
        assert len(links) == 0

    def test_cascade_undiscovery(self, simple_zone_pairs, discovered_to_caelid, starting_zone_id):
        # Undiscovering limgrave should also undiscover caelid
        links, removed = undiscover_zone(
            discovered_to_caelid, "limgrave", simple_zone_pairs, starting_zone_id
        )
        assert "limgrave" in removed
        assert "caelid" in removed


class TestComputeDiscoveryStats:
    """Tests for compute_discovery_stats function."""

    def test_empty_discoveries(self, simple_zone_pairs):
        stats = compute_discovery_stats(simple_zone_pairs, [])
        assert stats["discovered"] == 0
        assert stats["total"] > 0
        assert stats["percent"] == 0.0

    def test_some_discoveries(self, simple_zone_pairs, discovered_chapel_to_limgrave):
        stats = compute_discovery_stats(simple_zone_pairs, discovered_chapel_to_limgrave)
        assert stats["discovered"] == 2  # Chapel + Limgrave
        assert stats["percent"] > 0.0

    def test_percentage_calculation(self, simple_zone_pairs, discovered_to_caelid):
        stats = compute_discovery_stats(simple_zone_pairs, discovered_to_caelid)
        # 3 zones discovered: Chapel, Limgrave, Caelid
        assert stats["discovered"] == 3


class TestWithRealData:
    """Tests using real game data fixtures.

    NOTE: These tests require regenerating JSON fixtures with source_id/target_id fields.
    After running the spoiler parser with Zone Key Migration, regenerate the fixtures:
        python -c "from fogtracker.spoiler_parser import ...; ..."
    """

    @pytest.mark.skip(reason="JSON fixtures need regeneration with source_id/target_id")
    def test_start_node_in_real_data(self, zone_pairs_small, starting_zone_id):
        # starting_zone_id should be referenced in real data as source_id or target_id
        all_zone_ids = set()
        for pair in zone_pairs_small:
            if pair.get("source_id"):
                all_zone_ids.add(pair["source_id"])
            if pair.get("target_id"):
                all_zone_ids.add(pair["target_id"])
        assert starting_zone_id in all_zone_ids

    @pytest.mark.skip(reason="JSON fixtures need regeneration with source_id/target_id")
    def test_preexisting_adjacency_not_empty(self, zone_pairs_small):
        adj = build_preexisting_adjacency(zone_pairs_small)
        assert len(adj) > 0

    def test_full_adjacency_larger_than_preexisting(self, zone_pairs_small):
        preexisting_adj = build_preexisting_adjacency(zone_pairs_small)
        full_adj = build_full_adjacency(zone_pairs_small)
        assert len(full_adj) >= len(preexisting_adj)

    @pytest.mark.skip(reason="JSON fixtures need regeneration with source_id/target_id")
    def test_discovery_stats_consistent(self, zone_pairs_small):
        stats = compute_discovery_stats(zone_pairs_small, [])
        assert stats["total"] > 50  # Real data has many zones
        assert stats["discovered"] == 0
        assert stats["percent"] == 0.0


class TestGetZoneLinkId:
    """Tests for get_zone_link_id function."""

    def test_new_format(self):
        link = {"zone_link_id": "uuid-123"}
        assert get_zone_link_id(link) == "uuid-123"

    def test_legacy_format(self):
        link = {"link_id": "uuid-456"}
        assert get_zone_link_id(link) == "uuid-456"

    def test_new_format_takes_precedence(self):
        link = {"zone_link_id": "uuid-new", "link_id": "uuid-legacy"}
        assert get_zone_link_id(link) == "uuid-new"

    def test_empty_link(self):
        assert get_zone_link_id({}) is None

    def test_none_values(self):
        link = {"zone_link_id": None, "link_id": None}
        assert get_zone_link_id(link) is None


class TestBuildZonePairsIndex:
    """Tests for build_zone_pairs_index function."""

    def test_builds_index_by_id(self, simple_zone_pairs):
        index = build_zone_pairs_index(simple_zone_pairs)
        assert "link-1" in index
        assert index["link-1"]["source"] == "Chapel of Anticipation"

    def test_handles_missing_id(self):
        pairs = [{"source": "A", "target": "B"}]  # No id
        index = build_zone_pairs_index(pairs)
        assert len(index) == 0

    def test_all_pairs_indexed(self, simple_zone_pairs):
        index = build_zone_pairs_index(simple_zone_pairs)
        assert len(index) == len(simple_zone_pairs)


class TestExpandDiscoveredLinks:
    """Tests for expand_discovered_links function."""

    def test_filters_valid_links(self, simple_zone_pairs):
        discovered = [{"zone_link_id": "link-1"}, {"zone_link_id": "link-2"}]
        result = expand_discovered_links(discovered, simple_zone_pairs)
        assert len(result) == 2
        assert all("zone_link_id" in r for r in result)

    def test_filters_invalid_links(self, simple_zone_pairs):
        discovered = [{"zone_link_id": "link-1"}, {"zone_link_id": "invalid-id"}]
        result = expand_discovered_links(discovered, simple_zone_pairs)
        assert len(result) == 1
        assert result[0]["zone_link_id"] == "link-1"

    def test_handles_legacy_format(self, simple_zone_pairs):
        discovered = [{"link_id": "link-1"}]  # Legacy format
        result = expand_discovered_links(discovered, simple_zone_pairs)
        assert len(result) == 1
        assert result[0]["zone_link_id"] == "link-1"

    def test_empty_input(self, simple_zone_pairs):
        result = expand_discovered_links([], simple_zone_pairs)
        assert result == []


class TestLinkExists:
    """Tests for link_exists function (now uses zone_ids)."""

    def test_link_exists(self, simple_zone_pairs, discovered_chapel_to_limgrave):
        assert link_exists(
            discovered_chapel_to_limgrave,
            "chapel_start",
            "limgrave",
            simple_zone_pairs,
        )

    def test_link_not_exists(self, simple_zone_pairs, discovered_chapel_to_limgrave):
        assert not link_exists(
            discovered_chapel_to_limgrave,
            "limgrave",
            "caelid",
            simple_zone_pairs,
        )

    def test_empty_discoveries(self, simple_zone_pairs):
        assert not link_exists(
            [],
            "chapel_start",
            "limgrave",
            simple_zone_pairs,
        )

    def test_reverse_direction_for_bidirectional_random(
        self, simple_zone_pairs, discovered_chapel_to_limgrave
    ):
        """Bidirectional random links should be found in reverse direction.

        link-1 is stored as chapel_start → limgrave, but checking limgrave → chapel_start
        should also return True since random links are bidirectional.
        """
        assert link_exists(
            discovered_chapel_to_limgrave,
            "limgrave",
            "chapel_start",
            simple_zone_pairs,
        )

    def test_reverse_direction_not_found_for_one_way(self, simple_zone_pairs):
        """One-way random links should NOT be found in reverse direction.

        link-8 is sending_gate_origin → divine_tower (is_one_way=True).
        Checking divine_tower → sending_gate_origin should return False.
        """
        discovered_one_way = [{"zone_link_id": "link-8"}]
        # Direct direction should be found
        assert link_exists(
            discovered_one_way,
            "sending_gate_origin",
            "divine_tower",
            simple_zone_pairs,
        )
        # Reverse direction should NOT be found (one-way link)
        assert not link_exists(
            discovered_one_way,
            "divine_tower",
            "sending_gate_origin",
            simple_zone_pairs,
        )


class TestFindZonePairByIds:
    """Tests for find_zone_pair_by_ids function."""

    def test_direct_match(self):
        pairs = [
            {
                "id": "1",
                "source": "Limgrave",
                "target": "Caelid",
                "source_id": "limgrave",
                "target_id": "caelid",
                "type": "random",
            }
        ]
        result = find_zone_pair_by_ids(pairs, "limgrave", "caelid")
        assert result is not None
        assert result["id"] == "1"

    def test_reverse_match_for_bidirectional(self):
        pairs = [
            {
                "id": "1",
                "source": "Limgrave",
                "target": "Caelid",
                "source_id": "limgrave",
                "target_id": "caelid",
                "type": "random",
                "is_one_way": False,
            }
        ]
        result = find_zone_pair_by_ids(pairs, "caelid", "limgrave")
        assert result is not None
        assert result["id"] == "1"

    def test_no_reverse_for_one_way(self):
        pairs = [
            {
                "id": "1",
                "source": "Origin",
                "target": "Destination",
                "source_id": "origin",
                "target_id": "destination",
                "type": "random",
                "is_one_way": True,
            }
        ]
        result = find_zone_pair_by_ids(pairs, "destination", "origin")
        assert result is None

    def test_no_match(self):
        pairs = [
            {
                "id": "1",
                "source_id": "limgrave",
                "target_id": "caelid",
                "type": "random",
            }
        ]
        result = find_zone_pair_by_ids(pairs, "stormveil", "liurnia")
        assert result is None

    def test_disambiguate_by_source_details(self):
        pairs = [
            {
                "id": "1",
                "source": "Zone A",
                "target": "Zone B",
                "source_id": "zone_a",
                "target_id": "zone_b",
                "source_details": "near the gate",
                "type": "random",
            },
            {
                "id": "2",
                "source": "Zone A",
                "target": "Zone B",
                "source_id": "zone_a",
                "target_id": "zone_b",
                "source_details": "by the cliff",
                "type": "random",
            },
        ]
        result = find_zone_pair_by_ids(pairs, "zone_a", "zone_b", "by the cliff")
        assert result is not None
        assert result["id"] == "2"


class TestFindMatchingZonePairByIds:
    """Tests for find_matching_zone_pair_by_ids function."""

    def test_finds_first_match(self):
        pairs = [
            {
                "id": "1",
                "source": "Limgrave",
                "target": "Caelid",
                "source_id": "limgrave",
                "target_id": "caelid",
                "type": "random",
            }
        ]
        source_candidates = [("limgrave", "Limgrave")]
        target_candidates = [("caelid", "Caelid")]
        result = find_matching_zone_pair_by_ids(pairs, source_candidates, target_candidates)
        assert result is not None
        source_id, target_id, pair = result
        # Returns zone_ids, not display names
        assert source_id == "limgrave"
        assert target_id == "caelid"

    def test_tries_all_combinations(self):
        pairs = [
            {
                "id": "1",
                "source": "Zone A",
                "target": "Zone B",
                "source_id": "zone_a_alt",
                "target_id": "zone_b",
                "type": "random",
            }
        ]
        source_candidates = [("zone_a", "Zone A"), ("zone_a_alt", "Zone A")]
        target_candidates = [("zone_b", "Zone B")]
        result = find_matching_zone_pair_by_ids(pairs, source_candidates, target_candidates)
        assert result is not None

    def test_no_match_returns_none(self):
        pairs = []
        source_candidates = [("zone_a", "Zone A")]
        target_candidates = [("zone_b", "Zone B")]
        result = find_matching_zone_pair_by_ids(pairs, source_candidates, target_candidates)
        assert result is None


class TestFindAllMatchingZonePairsByIds:
    """Tests for find_all_matching_zone_pairs_by_ids function."""

    def test_finds_all_matches(self):
        pairs = [
            {
                "id": "1",
                "source": "Zone A",
                "target": "Zone B",
                "source_id": "zone_a",
                "target_id": "zone_b",
                "type": "random",
            },
            {
                "id": "2",
                "source": "Zone A",
                "target": "Zone C",
                "source_id": "zone_a",
                "target_id": "zone_c",
                "type": "random",
            },
        ]
        source_candidates = [("zone_a", "Zone A")]
        target_candidates = [("zone_b", "Zone B"), ("zone_c", "Zone C")]
        result = find_all_matching_zone_pairs_by_ids(pairs, source_candidates, target_candidates)
        assert len(result) == 2

    def test_deduplicates_by_pair_id(self):
        pairs = [
            {
                "id": "1",
                "source": "Zone A",
                "target": "Zone B",
                "source_id": "zone_a",
                "target_id": "zone_b",
                "type": "random",
            }
        ]
        # Same pair matched from different candidate combinations
        source_candidates = [("zone_a", "Zone A"), ("zone_a", "Zone A Alt")]
        target_candidates = [("zone_b", "Zone B")]
        result = find_all_matching_zone_pairs_by_ids(pairs, source_candidates, target_candidates)
        assert len(result) == 1  # Deduplicated


class TestFindMatchingZonePair:
    """Tests for find_matching_zone_pair function."""

    def test_finds_match(self, simple_zone_pairs):
        source_candidates = [("chapel_start", "Chapel of Anticipation")]
        target_candidates = [("limgrave", "Limgrave")]
        result = find_matching_zone_pair(simple_zone_pairs, source_candidates, target_candidates)
        assert result is not None
        source_id, target_id, pair = result
        assert source_id == "chapel_start"
        assert target_id == "limgrave"

    def test_tries_candidates_in_order(self, simple_zone_pairs):
        # First candidate doesn't match, second does
        source_candidates = [("wrong", "Wrong Zone"), ("chapel_start", "Chapel of Anticipation")]
        target_candidates = [("limgrave", "Limgrave")]
        result = find_matching_zone_pair(simple_zone_pairs, source_candidates, target_candidates)
        assert result is not None

    def test_no_match(self, simple_zone_pairs):
        source_candidates = [("fake", "Fake Zone")]
        target_candidates = [("fake2", "Fake Zone 2")]
        result = find_matching_zone_pair(simple_zone_pairs, source_candidates, target_candidates)
        assert result is None


class TestFindAllMatchingZonePairs:
    """Tests for find_all_matching_zone_pairs function."""

    def test_finds_all_random_matches(self, simple_zone_pairs):
        source_candidates = [("limgrave", "Limgrave")]
        target_candidates = [("caelid", "Caelid"), ("chapel", "Chapel of Anticipation")]
        result = find_all_matching_zone_pairs(
            simple_zone_pairs, source_candidates, target_candidates
        )
        # Should find Limgrave->Caelid (link-4) and Chapel->Limgrave (link-1, reverse)
        assert len(result) >= 1

    def test_deduplicates_bidirectional(self, simple_zone_pairs):
        # Same pair A<->B should only be returned once
        source_candidates = [("chapel", "Chapel of Anticipation"), ("limgrave", "Limgrave")]
        target_candidates = [("limgrave", "Limgrave"), ("chapel", "Chapel of Anticipation")]
        result = find_all_matching_zone_pairs(
            simple_zone_pairs, source_candidates, target_candidates
        )
        # Chapel<->Limgrave appears in both directions, should be deduplicated
        pair_ids = [r[2]["id"] for r in result]
        assert len(pair_ids) == len(set(pair_ids))


class TestFindCandidateZones:
    """Tests for find_candidate_zones function."""

    def test_finds_zones_as_source(self, simple_zone_pairs):
        candidates = find_candidate_zones(simple_zone_pairs, "limgrave")
        assert len(candidates) >= 2  # Limgrave is source in multiple links

    def test_finds_zones_as_target(self, simple_zone_pairs):
        candidates = find_candidate_zones(simple_zone_pairs, "stormveil_castle")
        assert len(candidates) >= 1

    def test_no_candidates(self, simple_zone_pairs):
        candidates = find_candidate_zones(simple_zone_pairs, "nonexistent_zone")
        assert len(candidates) == 0


class TestFindSimilarZones:
    """Tests for find_similar_zones function."""

    def test_finds_substring_match(self, simple_zone_pairs):
        similar = find_similar_zones(simple_zone_pairs, "castle")
        assert any("castle" in z for z in similar)

    def test_finds_word_overlap(self, simple_zone_pairs):
        similar = find_similar_zones(simple_zone_pairs, "stormveil")
        assert "stormveil_castle" in similar

    def test_respects_limit(self, simple_zone_pairs):
        similar = find_similar_zones(simple_zone_pairs, "a", limit=2)
        assert len(similar) <= 2

    def test_no_match(self, simple_zone_pairs):
        similar = find_similar_zones(simple_zone_pairs, "xyzxyzxyz")
        assert len(similar) == 0


class TestComputeTotalZones:
    """Tests for compute_total_zones function."""

    def test_counts_unique_zones(self, simple_zone_pairs):
        total = compute_total_zones(simple_zone_pairs)
        # Count manually: Chapel, Limgrave, Stormveil, Caelid, Dragonbarrow,
        # Isolated Zone, Another Isolated, Sending Gate Origin, Divine Tower = 9
        assert total == 9

    def test_empty_pairs(self):
        assert compute_total_zones([]) == 0


class TestIsLinkDiscovered:
    """Tests for is_link_discovered function."""

    def test_link_is_discovered(self, simple_zone_pairs, discovered_chapel_to_limgrave):
        assert is_link_discovered(
            discovered_chapel_to_limgrave,
            "chapel_start",
            "limgrave",
            simple_zone_pairs,
        )

    def test_link_discovered_reverse_direction(
        self, simple_zone_pairs, discovered_chapel_to_limgrave
    ):
        # Random links are bidirectional, should match in reverse
        assert is_link_discovered(
            discovered_chapel_to_limgrave,
            "limgrave",
            "chapel_start",
            simple_zone_pairs,
        )

    def test_link_not_discovered(self, simple_zone_pairs, discovered_chapel_to_limgrave):
        assert not is_link_discovered(
            discovered_chapel_to_limgrave,
            "limgrave",
            "caelid",
            simple_zone_pairs,
        )

    def test_exact_zone_id_match_required(self, simple_zone_pairs, discovered_chapel_to_limgrave):
        # Zone IDs must match exactly - similar IDs should not match
        assert not is_link_discovered(
            discovered_chapel_to_limgrave,
            "chapel",  # Wrong zone_id (should be chapel_start)
            "limgrave",
            simple_zone_pairs,
        )


class TestFindPathPrioritizingDiscovered:
    """Tests for find_path_prioritizing_discovered function."""

    def test_start_node_returns_empty(self, simple_zone_pairs, starting_zone_id):
        path = find_path_prioritizing_discovered(
            simple_zone_pairs, [], starting_zone_id, starting_zone_id
        )
        assert path == []

    def test_finds_path_to_adjacent(self, simple_zone_pairs, starting_zone_id):
        path = find_path_prioritizing_discovered(
            simple_zone_pairs, [], "limgrave", starting_zone_id
        )
        assert len(path) == 1
        assert path[0] == (starting_zone_id, "limgrave")

    def test_finds_longer_path(self, simple_zone_pairs, starting_zone_id):
        # Path to stormveil_castle: chapel_start -> limgrave -> stormveil_castle (via preexisting)
        path = find_path_prioritizing_discovered(
            simple_zone_pairs, [], "stormveil_castle", starting_zone_id
        )
        assert len(path) >= 1  # At least one hop

    def test_prioritizes_discovered_nodes(
        self, simple_zone_pairs, discovered_chapel_to_limgrave, starting_zone_id
    ):
        # When limgrave is discovered, path to caelid should go through limgrave
        path = find_path_prioritizing_discovered(
            simple_zone_pairs, discovered_chapel_to_limgrave, "caelid", starting_zone_id
        )
        # The path should include limgrave
        all_nodes = set()
        for src, tgt in path:
            all_nodes.add(src)
            all_nodes.add(tgt)
        assert "limgrave" in all_nodes

    def test_unreachable_returns_empty(self, simple_zone_pairs, starting_zone_id):
        # isolated_zone is not reachable from START
        path = find_path_prioritizing_discovered(
            simple_zone_pairs, [], "isolated_zone", starting_zone_id
        )
        assert path == []


class TestComputeZoneExits:
    """Tests for compute_zone_exits function."""

    def test_finds_random_exits(self, simple_zone_pairs, discovered_chapel_to_limgrave):
        exits = compute_zone_exits(simple_zone_pairs, discovered_chapel_to_limgrave, "limgrave")
        # Limgrave has exit to Caelid (random, link-4)
        assert len(exits) >= 1
        exit_targets = [e["target"] for e in exits]
        # Caelid not yet discovered, so should be "???"
        assert "???" in exit_targets or "Caelid" in exit_targets

    def test_discovered_exits_show_target(self, simple_zone_pairs, discovered_to_caelid):
        exits = compute_zone_exits(simple_zone_pairs, discovered_to_caelid, "limgrave")
        # Caelid is discovered, should show target name
        exit_targets = [e["target"] for e in exits]
        assert "Caelid" in exit_targets

    def test_undiscovered_exits_show_placeholder(
        self, simple_zone_pairs, discovered_chapel_to_limgrave
    ):
        exits = compute_zone_exits(simple_zone_pairs, discovered_chapel_to_limgrave, "limgrave")
        # Find the exit to Caelid (not discovered)
        caelid_exit = next((e for e in exits if e.get("id") == "link-4"), None)
        if caelid_exit:
            assert caelid_exit["target"] == "???"

    def test_includes_description(self, simple_zone_pairs, discovered_chapel_to_limgrave):
        exits = compute_zone_exits(simple_zone_pairs, discovered_chapel_to_limgrave, "limgrave")
        # link-4 has source_details "near the beach"
        caelid_exit = next((e for e in exits if e.get("id") == "link-4"), None)
        if caelid_exit:
            assert caelid_exit["description"] == "near the beach"

    def test_excludes_internal_preexisting_exits(self, simple_zone_pairs, discovered_to_caelid):
        # From Caelid, the preexisting link to Dragonbarrow is internal (merged zone)
        exits = compute_zone_exits(simple_zone_pairs, discovered_to_caelid, "caelid")
        # Should not include preexisting links within the same merged group
        exit_ids = [e["id"] for e in exits]
        # link-5 and link-6 are preexisting Caelid<->Dragonbarrow - should not appear as exits
        assert "link-5" not in exit_ids
        assert "link-6" not in exit_ids

    def test_one_way_exit_only_forward(self, simple_zone_pairs):
        # From Divine Tower, cannot exit back through one-way sending gate
        discovered = [{"zone_link_id": "link-8"}]  # Sending Gate -> Divine Tower
        exits = compute_zone_exits(simple_zone_pairs, discovered, "divine_tower")
        # Should NOT have an exit back to Sending Gate Origin (one-way)
        exit_targets = [e.get("target") for e in exits]
        assert "Sending Gate Origin" not in exit_targets

    def test_preexisting_bidirectional_with_reverse_link(self):
        """
        Test that preexisting links are bidirectional when both directions exist.

        For a link to be bidirectional, there must be explicit links in both directions.
        A single preexisting link without reverse is one-way (like a one-way door).

        Scenario (Elphael elevator):
        - After Loretta -> Elphael (preexisting)
        - Elphael -> After Loretta (preexisting, reverse direction)
        - Yelough -> After Loretta (random)
        - From Elphael, we should see exits from both Elphael AND After Loretta
        """
        zone_pairs = [
            {
                "id": "link-yelough-afterloretta",
                "source": "Yelough Anix Tunnel",
                "source_id": "yelough_anix_tunnel",
                "target": "After Loretta",
                "target_id": "after_loretta",
                "type": "random",
                "source_details": "at the front of Astel's arena",
                "target_details": "after Loretta's arena",
                "is_one_way": False,
            },
            {
                "id": "link-afterloretta-elphael",
                "source": "After Loretta",
                "source_id": "after_loretta",
                "target": "Elphael",
                "target_id": "elphael",
                "type": "preexisting",
                "source_details": None,
                "target_details": "at the elevator",
                "is_one_way": False,
            },
            {
                "id": "link-elphael-afterloretta",
                "source": "Elphael",
                "source_id": "elphael",
                "target": "After Loretta",
                "target_id": "after_loretta",
                "type": "preexisting",
                "source_details": "at the elevator",
                "target_details": None,
                "is_one_way": False,
            },
            {
                "id": "link-elphael-malenia",
                "source": "Elphael",
                "source_id": "elphael",
                "target": "Sellia Crystal Tunnel",
                "target_id": "sellia_crystal_tunnel",
                "type": "random",
                "source_details": "before Malenia's arena",
                "target_details": "before Fallingstar Beast",
                "is_one_way": False,
            },
        ]

        # No discovered links
        discovered = []

        # From Elphael, merged zones should include After Loretta via bidirectional preexisting
        merged = get_zones_via_preexisting(zone_pairs, "elphael")
        assert "elphael" in merged
        assert "after_loretta" in merged  # Bidirectional because reverse link exists

        # Compute exits - should have 2 exits
        exits = compute_zone_exits(zone_pairs, discovered, "elphael")
        exit_descriptions = {e["description"] for e in exits}

        # Exit from Elphael itself (to Sellia via Malenia fog gate)
        assert "before Malenia's arena" in exit_descriptions

        # Exit from After Loretta (back through the Yelough fog gate)
        assert "after Loretta's arena" in exit_descriptions

        # Verify from_zone is set correctly (returns display name)
        yelough_exit = next(e for e in exits if e["description"] == "after Loretta's arena")
        assert yelough_exit["from_zone"] == "After Loretta"

        malenia_exit = next(e for e in exits if e["description"] == "before Malenia's arena")
        assert malenia_exit["from_zone"] is None  # Same as current zone

    def test_preexisting_bidirectional_door(self):
        """
        Test that a preexisting link (door) is bidirectional by default.

        Doors like "opening the heavy door" are bidirectional in the game,
        so they should be traversable in both directions unless explicitly
        marked as one-way (e.g., drop-downs).
        """
        zone_pairs = [
            {
                "id": "link-stormveil-pretower",
                "source": "Stormveil Castle after Gate",
                "source_id": "stormveil_castle_after_gate",
                "target": "Leyndell - before Divine Tower",
                "target_id": "leyndell_before_divine_tower",
                "type": "random",
                "source_details": "at the side path",
                "target_details": "at the base of the elevator",
                "is_one_way": False,
            },
            {
                "id": "link-leyndell-pretower",
                "source": "Leyndell",
                "source_id": "leyndell",
                "target": "Leyndell - before Divine Tower",
                "target_id": "leyndell_before_divine_tower",
                "type": "preexisting",
                "source_details": None,
                "target_details": "opening the heavy door",
                "is_one_way": False,  # Door = bidirectional
            },
        ]

        # From "Leyndell - before Divine Tower", we CAN go back to Leyndell
        # because doors are bidirectional
        merged = get_zones_via_preexisting(zone_pairs, "leyndell_before_divine_tower")
        assert "leyndell_before_divine_tower" in merged
        assert "leyndell" in merged  # Door is bidirectional

        # From Leyndell, we CAN also go to "Leyndell - before Divine Tower"
        merged_from_leyndell = get_zones_via_preexisting(zone_pairs, "leyndell")
        assert "leyndell" in merged_from_leyndell
        assert "leyndell_before_divine_tower" in merged_from_leyndell

    def test_preexisting_one_way_drop_down(self):
        """
        Test that a preexisting link marked as one-way (drop-down) is not bidirectional.
        """
        zone_pairs = [
            {
                "id": "link-drop-down",
                "source": "Upper Area",
                "source_id": "upper_area",
                "target": "Lower Area",
                "target_id": "lower_area",
                "type": "preexisting",
                "source_details": None,
                "target_details": "dropping down",
                "is_one_way": True,  # Drop-down = one-way
            },
        ]

        # From "Lower Area", we CANNOT go back to "Upper Area"
        merged = get_zones_via_preexisting(zone_pairs, "lower_area")
        assert "lower_area" in merged
        assert "upper_area" not in merged  # Cannot go back up

        # From "Upper Area", we CAN go to "Lower Area"
        merged_from_upper = get_zones_via_preexisting(zone_pairs, "upper_area")
        assert "upper_area" in merged_from_upper
        assert "lower_area" in merged_from_upper

    def test_random_link_parallel_to_preexisting_shown_as_exit(self):
        """
        Test that a random link is shown as an exit even when a parallel preexisting
        link connects the same zones.

        Bug scenario (Nokron):
        - Nokron - Ancestral Woods -> Nokron to Siofra Path (preexisting, dropping down)
        - Nokron - Ancestral Woods -> Nokron to Siofra Path (random, using Horned Remains)

        Both links should appear as exits because they represent different warp mechanisms.
        The random link should NOT be skipped just because the target is reachable via
        preexisting.
        """
        zone_pairs = [
            {
                "id": "link-preexisting-dropdown",
                "source": "Nokron - Ancestral Woods",
                "source_id": "nokron_ancestral_woods",
                "target": "Nokron to Siofra Path",
                "target_id": "nokron_to_siofra_path",
                "type": "preexisting",
                "source_details": None,
                "target_details": "dropping down below the east-side bridge",
                "is_one_way": True,
            },
            {
                "id": "link-random-horned-remains",
                "source": "Nokron - Ancestral Woods",
                "source_id": "nokron_ancestral_woods",
                "target": "Nokron to Siofra Path",
                "target_id": "nokron_to_siofra_path",
                "type": "random",
                "source_details": "using Horned Remains in Nokron",
                "target_details": "arriving at the lake between Nokron and lower Siofra",
                "is_one_way": True,
            },
        ]

        # Both random links discovered
        discovered = [
            {"zone_link_id": "link-preexisting-dropdown"},
            {"zone_link_id": "link-random-horned-remains"},
        ]

        # From Nokron - Ancestral Woods, the random exit should be shown
        exits = compute_zone_exits(zone_pairs, discovered, "nokron_ancestral_woods")

        # The random link should appear as an exit
        exit_ids = [e.get("id") for e in exits]
        assert (
            "link-random-horned-remains" in exit_ids
        ), "Random link should be shown as exit even when parallel preexisting exists"

        # Verify the exit has the correct description
        horned_exit = next(e for e in exits if e["id"] == "link-random-horned-remains")
        assert horned_exit["description"] == "using Horned Remains in Nokron"
        assert horned_exit["target"] == "Nokron to Siofra Path"

    def test_requires_zone_id_not_display_name(self):
        """
        Regression test: compute_zone_exits must receive zone_id, not display name.

        Bug scenario:
        - Mod sent discovery event
        - Server resolved destination_zone (display name)
        - compute_zone_exits was called with display name instead of zone_id
        - Result: No exits found because adjacency is keyed by zone_id

        The function uses get_zones_via_preexisting() which builds an adjacency
        keyed by zone_id (source_id/target_id fields). Passing a display name
        results in no matches and empty exits.
        """
        zone_pairs = [
            {
                "id": "link-1",
                "source": "Limgrave - Stormhill",
                "source_id": "limgrave_stormhill",
                "target": "Liurnia - Lake",
                "target_id": "liurnia_lake",
                "type": "random",
                "source_details": "near the broken bridge",
                "target_details": "by the telescope",
                "is_one_way": False,
            },
            {
                "id": "link-2",
                "source": "Liurnia - Lake",
                "source_id": "liurnia_lake",
                "target": "Liurnia - Academy Gate",
                "target_id": "liurnia_academy_gate",
                "type": "random",
                "source_details": "east of the lake",
                "target_details": "at the gate",
                "is_one_way": False,
            },
        ]

        discovered = [{"zone_link_id": "link-1"}]  # Limgrave->Liurnia discovered

        # CORRECT: Use zone_id - should find the exit to Academy Gate
        exits_with_zone_id = compute_zone_exits(zone_pairs, discovered, "liurnia_lake")
        assert len(exits_with_zone_id) >= 1, "Should find exits when using zone_id"
        exit_ids = [e.get("id") for e in exits_with_zone_id]
        assert "link-2" in exit_ids, "Should include exit to Academy Gate"

        # WRONG: Using display name - should find NO exits (regression test)
        exits_with_display_name = compute_zone_exits(zone_pairs, discovered, "Liurnia - Lake")
        assert len(exits_with_display_name) == 0, (
            "Display name should NOT match - adjacency is keyed by zone_id. "
            "If this fails, the caller is incorrectly passing display names."
        )


class TestBackpropPreexistingPropagation:
    """
    Tests for bug fix: preexisting links from zones made accessible via back-propagation
    must also be propagated.

    Bug scenario:
    - Player is at zone C (source) and traverses to Destination
    - Zone C is not yet accessible from START
    - System back-propagates path: START -> A -> B -> C
    - Zone C has a preexisting link to Boss Arena
    - BUG: The preexisting C -> Boss Arena was NOT propagated

    After fix:
    - All preexisting links from zones in the backprop path should be queued
    """

    def test_source_not_accessible_before_backprop(
        self, backprop_preexisting_zone_pairs, starting_zone_id
    ):
        """zone_c should not be accessible from START with no discovered links."""
        discovered_links = []
        accessible = is_accessible_from_start(
            discovered_links, "zone_c", backprop_preexisting_zone_pairs, starting_zone_id
        )
        assert not accessible

    def test_backprop_path_includes_preexisting_zones(
        self, backprop_preexisting_zone_pairs, starting_zone_id
    ):
        """Back-propagation path to zone_c should include zone_b (via preexisting link)."""
        discovered_links = []
        path = find_path_prioritizing_discovered(
            backprop_preexisting_zone_pairs, discovered_links, "zone_c", starting_zone_id
        )
        # Path should be: chapel_start -> zone_a, zone_a -> zone_b, zone_b -> zone_c
        assert len(path) == 3
        sources = [src for src, _ in path]
        targets = [tgt for _, tgt in path]
        assert starting_zone_id in sources
        assert "zone_a" in sources or "zone_a" in targets
        assert "zone_b" in sources or "zone_b" in targets
        assert "zone_c" in targets

    def test_preexisting_adjacency_includes_boss_link(self, backprop_preexisting_zone_pairs):
        """zone_c should have preexisting link to boss_arena in adjacency."""
        preexisting_adj = build_preexisting_adjacency(backprop_preexisting_zone_pairs)
        c_neighbors = [neighbor for neighbor, _ in preexisting_adj.get("zone_c", [])]
        assert "boss_arena" in c_neighbors
        assert "zone_b" in c_neighbors

    def test_zones_needing_preexisting_propagation(
        self, backprop_preexisting_zone_pairs, starting_zone_id
    ):
        """
        After back-propagation, zones in the path should have their preexisting
        links identified for propagation.

        This tests the logic that was missing before the fix:
        - zone_c (the source) has preexisting to boss_arena
        - zone_b (in backprop path) has preexisting to zone_c
        """
        discovered_links = []
        preexisting_adj = build_preexisting_adjacency(backprop_preexisting_zone_pairs)

        # Find backprop path
        path = find_path_prioritizing_discovered(
            backprop_preexisting_zone_pairs, discovered_links, "zone_c", starting_zone_id
        )

        # Collect zones from backprop path
        backprop_zones = set()
        for _src, dst in path:
            backprop_zones.add(dst)
        backprop_zones.add("zone_c")  # The source itself

        # These zones should have preexisting links that need propagation
        preexisting_to_propagate = []
        for zone in backprop_zones:
            for neighbor, _ in preexisting_adj.get(zone, []):
                preexisting_to_propagate.append((zone, neighbor))

        # zone_c -> boss_arena should be in the list
        assert ("zone_c", "boss_arena") in preexisting_to_propagate
        # zone_b -> zone_c should also be there (though zone_c is already in path)
        assert ("zone_b", "zone_c") in preexisting_to_propagate

    def test_get_zones_via_preexisting_from_source(self, backprop_preexisting_zone_pairs):
        """get_zones_via_preexisting should return boss_arena from zone_c."""
        reachable = get_zones_via_preexisting(backprop_preexisting_zone_pairs, "zone_c")
        assert "boss_arena" in reachable
        assert "zone_b" in reachable
        # zone_c itself should be in the set
        assert "zone_c" in reachable


class TestDirectionPreservation:
    """
    Tests that find_all_matching_zone_pairs returns the caller's direction,
    not the stored direction from zone_pairs.

    Regression test for bug where clicking "A → B" when the link is stored as
    "B → A" would cause the system to treat B as the source, triggering
    incorrect back-propagation.
    """

    def test_find_all_matching_zone_pairs_preserves_caller_direction(self):
        """
        When link is stored as B→A but caller searches A→B,
        result should have A as source (caller's direction).
        """
        zone_pairs = [
            {
                "id": "1",
                "source": "Nokron",  # Stored direction: Nokron → Farum
                "source_id": "nokron",
                "target": "Farum Azula",
                "target_id": "farum_azula",
                "type": "random",
            }
        ]
        # Caller is searching for Farum → Nokron (reverse of stored direction)
        source_candidates = [("farum_azula", "Farum Azula")]
        target_candidates = [("nokron", "Nokron")]

        result = find_all_matching_zone_pairs(zone_pairs, source_candidates, target_candidates)

        assert len(result) == 1
        source_id, target_id, pair = result[0]
        # Should preserve caller's direction, not stored direction
        assert source_id == "farum_azula"
        assert target_id == "nokron"
        # The pair itself still has the stored direction
        assert pair["source"] == "Nokron"
        assert pair["target"] == "Farum Azula"

    def test_find_all_matching_zone_pairs_by_ids_preserves_caller_direction(self):
        """
        When link is stored as B→A but caller searches A→B,
        result should have A as source (caller's direction).
        """
        zone_pairs = [
            {
                "id": "1",
                "source": "Nokron",
                "source_id": "nokron",
                "target": "Farum Azula",
                "target_id": "farum_azula",
                "type": "random",
            }
        ]
        # Caller is searching for Farum → Nokron (reverse of stored direction)
        source_candidates = [("farum_azula", "Farum Azula")]
        target_candidates = [("nokron", "Nokron")]

        result = find_all_matching_zone_pairs_by_ids(
            zone_pairs, source_candidates, target_candidates
        )

        assert len(result) == 1
        source_id, target_id, pair = result[0]
        # Should preserve caller's direction
        assert source_id == "farum_azula"
        assert target_id == "nokron"

    def test_find_all_matching_zone_pairs_direct_match_unchanged(self):
        """When caller's direction matches stored direction, result is same."""
        zone_pairs = [
            {
                "id": "1",
                "source": "Farum Azula",
                "source_id": "farum_azula",
                "target": "Nokron",
                "target_id": "nokron",
                "type": "random",
            }
        ]
        source_candidates = [("farum_azula", "Farum Azula")]
        target_candidates = [("nokron", "Nokron")]

        result = find_all_matching_zone_pairs(zone_pairs, source_candidates, target_candidates)

        assert len(result) == 1
        source_id, target_id, pair = result[0]
        assert source_id == "farum_azula"
        assert target_id == "nokron"
