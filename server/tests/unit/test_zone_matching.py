"""Unit tests for zone_matching module.

Tests pure functions for zone name matching, graph traversal,
and discovery logic.
"""

from fogvizu.zone_matching import (
    START_NODE,
    build_full_adjacency,
    build_preexisting_adjacency,
    build_zone_pairs_index,
    compute_backprop_cost,
    compute_discovery_stats,
    compute_total_zones,
    compute_zone_exits,
    expand_discovered_links,
    find_all_matching_zone_pairs,
    find_all_matching_zone_pairs_by_keys,
    find_candidate_zones,
    find_matching_zone_pair,
    find_matching_zone_pair_by_keys,
    find_path_prioritizing_discovered,
    find_reachable_nodes,
    find_similar_zones,
    find_zone_pair,
    find_zone_pair_by_keys,
    get_discovered_nodes,
    get_zone_link_id,
    get_zones_via_preexisting,
    is_accessible_from_start,
    is_link_discovered,
    is_one_way,
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


class TestIsOneWay:
    """Tests for is_one_way function."""

    def test_bidirectional_link(self, simple_zone_pairs):
        # Limgrave <-> Stormveil Castle has reverse link
        limgrave_to_stormveil = simple_zone_pairs[1]  # link-2
        assert not is_one_way(limgrave_to_stormveil, simple_zone_pairs)

    def test_one_way_random_link(self, simple_zone_pairs):
        # Chapel -> Limgrave has no reverse (random link)
        chapel_to_limgrave = simple_zone_pairs[0]  # link-1
        assert is_one_way(chapel_to_limgrave, simple_zone_pairs)

    def test_inherently_one_way_sending_gate(self, simple_zone_pairs):
        # Sending Gate Origin -> Divine Tower is one-way
        sending_gate = simple_zone_pairs[7]  # link-8
        assert is_one_way(sending_gate, simple_zone_pairs)


class TestBuildPreexistingAdjacency:
    """Tests for build_preexisting_adjacency function."""

    def test_only_includes_preexisting(self, simple_zone_pairs):
        adj = build_preexisting_adjacency(simple_zone_pairs)
        # Should not include random links
        assert "Chapel of Anticipation" not in adj

    def test_bidirectional_preexisting(self, simple_zone_pairs):
        adj = build_preexisting_adjacency(simple_zone_pairs)
        # Limgrave <-> Stormveil Castle
        assert any(dest == "Stormveil Castle" for dest, _ in adj.get("Limgrave", []))
        assert any(dest == "Limgrave" for dest, _ in adj.get("Stormveil Castle", []))

    def test_returns_is_bidirectional_flag(self, simple_zone_pairs):
        adj = build_preexisting_adjacency(simple_zone_pairs)
        # Caelid <-> Dragonbarrow is bidirectional
        caelid_neighbors = adj.get("Caelid", [])
        dragonbarrow_entry = next(
            (dest, is_bidir) for dest, is_bidir in caelid_neighbors if dest == "Dragonbarrow"
        )
        assert dragonbarrow_entry[1] is True  # is_bidirectional


class TestBuildFullAdjacency:
    """Tests for build_full_adjacency function."""

    def test_includes_all_link_types(self, simple_zone_pairs):
        adj = build_full_adjacency(simple_zone_pairs)
        # Should include both random and preexisting
        assert "Chapel of Anticipation" in adj
        assert "Limgrave" in adj

    def test_random_links_bidirectional_by_default(self, simple_zone_pairs):
        adj = build_full_adjacency(simple_zone_pairs)
        # Chapel -> Limgrave is random, should be bidirectional
        chapel_neighbors = adj.get("Chapel of Anticipation", [])
        assert any(dest == "Limgrave" for dest, _, _ in chapel_neighbors)
        limgrave_neighbors = adj.get("Limgrave", [])
        assert any(dest == "Chapel of Anticipation" for dest, _, _ in limgrave_neighbors)

    def test_one_way_link_not_reversed(self, simple_zone_pairs):
        adj = build_full_adjacency(simple_zone_pairs)
        # Sending Gate Origin -> Divine Tower is one-way
        assert any(dest == "Divine Tower" for dest, _, _ in adj.get("Sending Gate Origin", []))
        # Divine Tower should NOT have reverse to Sending Gate Origin
        divine_tower_neighbors = adj.get("Divine Tower", [])
        assert not any(dest == "Sending Gate Origin" for dest, _, _ in divine_tower_neighbors)


class TestFindZonePair:
    """Tests for find_zone_pair function."""

    def test_direct_match(self, simple_zone_pairs):
        pair = find_zone_pair(simple_zone_pairs, "Chapel of Anticipation", "Limgrave")
        assert pair is not None
        assert pair["id"] == "link-1"

    def test_reverse_match_for_random(self, simple_zone_pairs):
        # Random links can be found in either direction
        pair = find_zone_pair(simple_zone_pairs, "Limgrave", "Chapel of Anticipation")
        assert pair is not None
        assert pair["id"] == "link-1"

    def test_preexisting_no_reverse_match(self, simple_zone_pairs):
        # Preexisting links are directional
        # link-2 is Limgrave -> Stormveil Castle
        pair = find_zone_pair(simple_zone_pairs, "Limgrave", "Stormveil Castle")
        assert pair is not None
        assert pair["id"] == "link-2"

        # Reverse should find link-3 (Stormveil -> Limgrave), not link-2
        pair_reverse = find_zone_pair(simple_zone_pairs, "Stormveil Castle", "Limgrave")
        assert pair_reverse is not None
        assert pair_reverse["id"] == "link-3"

    def test_no_match(self, simple_zone_pairs):
        pair = find_zone_pair(simple_zone_pairs, "Nonexistent", "Limgrave")
        assert pair is None

    def test_normalized_name_match(self, simple_zone_pairs):
        # Should match even with parenthetical
        pair = find_zone_pair(simple_zone_pairs, "Chapel of Anticipation (detail)", "Limgrave")
        assert pair is not None


class TestIsAccessibleFromStart:
    """Tests for is_accessible_from_start function."""

    def test_start_node_always_accessible(self, simple_zone_pairs):
        assert is_accessible_from_start([], START_NODE, simple_zone_pairs)

    def test_unreachable_without_discoveries(self, simple_zone_pairs):
        # Caelid is not accessible without discovering links
        assert not is_accessible_from_start([], "Caelid", simple_zone_pairs)

    def test_accessible_via_discovered_link(self, simple_zone_pairs, discovered_chapel_to_limgrave):
        # Limgrave is accessible via Chapel -> Limgrave
        assert is_accessible_from_start(
            discovered_chapel_to_limgrave, "Limgrave", simple_zone_pairs
        )

    def test_accessible_via_chain(self, simple_zone_pairs, discovered_to_caelid):
        # Caelid is accessible via Chapel -> Limgrave -> Caelid
        assert is_accessible_from_start(discovered_to_caelid, "Caelid", simple_zone_pairs)

    def test_isolated_zone_not_accessible(self, simple_zone_pairs, discovered_to_caelid):
        # "Isolated Zone" is not connected to the main graph
        assert not is_accessible_from_start(
            discovered_to_caelid, "Isolated Zone", simple_zone_pairs
        )


class TestGetDiscoveredNodes:
    """Tests for get_discovered_nodes function."""

    def test_always_includes_start(self, simple_zone_pairs):
        nodes = get_discovered_nodes([], simple_zone_pairs)
        assert START_NODE in nodes

    def test_includes_link_endpoints(self, simple_zone_pairs, discovered_chapel_to_limgrave):
        nodes = get_discovered_nodes(discovered_chapel_to_limgrave, simple_zone_pairs)
        assert "Chapel of Anticipation" in nodes
        assert "Limgrave" in nodes


class TestFindReachableNodes:
    """Tests for find_reachable_nodes function."""

    def test_only_start_without_discoveries(self, simple_zone_pairs):
        reachable = find_reachable_nodes([], simple_zone_pairs)
        assert reachable == {START_NODE}

    def test_reachable_via_discoveries(self, simple_zone_pairs, discovered_to_caelid):
        reachable = find_reachable_nodes(discovered_to_caelid, simple_zone_pairs)
        assert "Limgrave" in reachable
        assert "Caelid" in reachable
        # Stormveil not discovered (only preexisting, not discovered)
        assert "Stormveil Castle" not in reachable


class TestGetZonesViaPreexisting:
    """Tests for get_zones_via_preexisting function."""

    def test_returns_connected_preexisting_zones(self, simple_zone_pairs):
        # From Limgrave, Stormveil is reachable via preexisting
        zones = get_zones_via_preexisting(simple_zone_pairs, "Limgrave")
        assert "Limgrave" in zones
        assert "Stormveil Castle" in zones

    def test_includes_start_zone(self, simple_zone_pairs):
        zones = get_zones_via_preexisting(simple_zone_pairs, "Caelid")
        assert "Caelid" in zones

    def test_does_not_cross_random_links(self, simple_zone_pairs):
        # From Limgrave, cannot reach Caelid (random link)
        zones = get_zones_via_preexisting(simple_zone_pairs, "Limgrave")
        assert "Caelid" not in zones


class TestComputeBackpropCost:
    """Tests for compute_backprop_cost function."""

    def test_already_accessible_returns_zero(
        self, simple_zone_pairs, discovered_chapel_to_limgrave
    ):
        # Limgrave is accessible, cost = 0
        cost = compute_backprop_cost(simple_zone_pairs, discovered_chapel_to_limgrave, "Limgrave")
        assert cost == 0

    def test_start_node_returns_zero(self, simple_zone_pairs):
        cost = compute_backprop_cost(simple_zone_pairs, [], START_NODE)
        assert cost == 0

    def test_one_random_link_away(self, simple_zone_pairs):
        # Limgrave requires 1 random link from START
        cost = compute_backprop_cost(simple_zone_pairs, [], "Limgrave")
        assert cost == 1

    def test_path_through_preexisting_cheaper(self, simple_zone_pairs):
        # Stormveil is reachable via Limgrave (1 random) + preexisting
        # Cost should be 1 (only the random link counts)
        cost = compute_backprop_cost(simple_zone_pairs, [], "Stormveil Castle")
        assert cost == 1

    def test_isolated_zone_returns_minus_one(self, simple_zone_pairs):
        # Isolated zones are unreachable
        cost = compute_backprop_cost(simple_zone_pairs, [], "Isolated Zone")
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
        zone_pairs = [
            # Path to C: 1 random + 2 preexisting
            {
                "id": "1",
                "type": "random",
                "source": START_NODE,
                "target": "Zone A",
                "source_key": "start",
                "target_key": "zone_a",
            },
            {
                "id": "2",
                "type": "preexisting",
                "source": "Zone A",
                "target": "Zone B",
                "source_key": "zone_a",
                "target_key": "zone_b",
            },
            {
                "id": "3",
                "type": "preexisting",
                "source": "Zone B",
                "target": "Zone C",
                "source_key": "zone_b",
                "target_key": "zone_c",
            },
            # Path to Z: 3 random
            {
                "id": "4",
                "type": "random",
                "source": START_NODE,
                "target": "Zone X",
                "source_key": "start",
                "target_key": "zone_x",
            },
            {
                "id": "5",
                "type": "random",
                "source": "Zone X",
                "target": "Zone Y",
                "source_key": "zone_x",
                "target_key": "zone_y",
            },
            {
                "id": "6",
                "type": "random",
                "source": "Zone Y",
                "target": "Zone Z",
                "source_key": "zone_y",
                "target_key": "zone_z",
            },
            # Fog gates at C and Z leading to different destinations
            {
                "id": "fog_c",
                "type": "random",
                "source": "Zone C",
                "target": "Far Away",
                "source_key": "zone_c",
                "target_key": "far_away",
            },
            {
                "id": "fog_z",
                "type": "random",
                "source": "Zone Z",
                "target": "Far Away 2",
                "source_key": "zone_z",
                "target_key": "far_away_2",
            },
        ]
        discovered_links = []

        # Cost to reach Zone C (1 random link via A)
        cost_c = compute_backprop_cost(zone_pairs, discovered_links, "Zone C")
        # Cost to reach Zone Z (3 random links via X, Y)
        cost_z = compute_backprop_cost(zone_pairs, discovered_links, "Zone Z")

        assert cost_c == 1, f"Expected cost 1 for Zone C, got {cost_c}"
        assert cost_z == 3, f"Expected cost 3 for Zone Z, got {cost_z}"
        assert cost_c < cost_z, "Zone C should have lower cost than Zone Z"


class TestUndiscoverZone:
    """Tests for undiscover_zone function."""

    def test_cannot_undiscover_start(self, simple_zone_pairs):
        links, removed = undiscover_zone([], START_NODE, simple_zone_pairs)
        assert removed == []

    def test_undiscover_removes_zone_links(self, simple_zone_pairs, discovered_chapel_to_limgrave):
        links, removed = undiscover_zone(
            discovered_chapel_to_limgrave, "Limgrave", simple_zone_pairs
        )
        assert "Limgrave" in removed
        assert len(links) == 0

    def test_cascade_undiscovery(self, simple_zone_pairs, discovered_to_caelid):
        # Undiscovering Limgrave should also undiscover Caelid
        links, removed = undiscover_zone(discovered_to_caelid, "Limgrave", simple_zone_pairs)
        assert "Limgrave" in removed
        assert "Caelid" in removed


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
    """Tests using real game data fixtures."""

    def test_start_node_in_real_data(self, zone_pairs_small):
        # START_NODE should be referenced in real data
        all_zones = set()
        for pair in zone_pairs_small:
            all_zones.add(pair["source"])
            all_zones.add(pair["target"])
        assert START_NODE in all_zones

    def test_preexisting_adjacency_not_empty(self, zone_pairs_small):
        adj = build_preexisting_adjacency(zone_pairs_small)
        assert len(adj) > 0

    def test_full_adjacency_larger_than_preexisting(self, zone_pairs_small):
        preexisting_adj = build_preexisting_adjacency(zone_pairs_small)
        full_adj = build_full_adjacency(zone_pairs_small)
        assert len(full_adj) >= len(preexisting_adj)

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
    """Tests for link_exists function."""

    def test_link_exists(self, simple_zone_pairs, discovered_chapel_to_limgrave):
        assert link_exists(
            discovered_chapel_to_limgrave,
            "Chapel of Anticipation",
            "Limgrave",
            simple_zone_pairs,
        )

    def test_link_not_exists(self, simple_zone_pairs, discovered_chapel_to_limgrave):
        assert not link_exists(
            discovered_chapel_to_limgrave,
            "Limgrave",
            "Caelid",
            simple_zone_pairs,
        )

    def test_empty_discoveries(self, simple_zone_pairs):
        assert not link_exists(
            [],
            "Chapel of Anticipation",
            "Limgrave",
            simple_zone_pairs,
        )


class TestFindZonePairByKeys:
    """Tests for find_zone_pair_by_keys function."""

    def test_direct_match(self):
        pairs = [
            {
                "id": "1",
                "source": "Limgrave",
                "target": "Caelid",
                "source_key": "limgrave",
                "target_key": "caelid",
                "type": "random",
            }
        ]
        result = find_zone_pair_by_keys(pairs, "limgrave", "caelid")
        assert result is not None
        assert result["id"] == "1"

    def test_reverse_match_for_bidirectional(self):
        pairs = [
            {
                "id": "1",
                "source": "Limgrave",
                "target": "Caelid",
                "source_key": "limgrave",
                "target_key": "caelid",
                "type": "random",
                "is_inherently_one_way": False,
            }
        ]
        result = find_zone_pair_by_keys(pairs, "caelid", "limgrave")
        assert result is not None
        assert result["id"] == "1"

    def test_no_reverse_for_one_way(self):
        pairs = [
            {
                "id": "1",
                "source": "Origin",
                "target": "Destination",
                "source_key": "origin",
                "target_key": "destination",
                "type": "random",
                "is_inherently_one_way": True,
            }
        ]
        result = find_zone_pair_by_keys(pairs, "destination", "origin")
        assert result is None

    def test_no_match(self):
        pairs = [
            {
                "id": "1",
                "source_key": "limgrave",
                "target_key": "caelid",
                "type": "random",
            }
        ]
        result = find_zone_pair_by_keys(pairs, "stormveil", "liurnia")
        assert result is None

    def test_disambiguate_by_source_details(self):
        pairs = [
            {
                "id": "1",
                "source": "Zone A",
                "target": "Zone B",
                "source_key": "zone_a",
                "target_key": "zone_b",
                "source_details": "near the gate",
                "type": "random",
            },
            {
                "id": "2",
                "source": "Zone A",
                "target": "Zone B",
                "source_key": "zone_a",
                "target_key": "zone_b",
                "source_details": "by the cliff",
                "type": "random",
            },
        ]
        result = find_zone_pair_by_keys(pairs, "zone_a", "zone_b", "by the cliff")
        assert result is not None
        assert result["id"] == "2"


class TestFindMatchingZonePairByKeys:
    """Tests for find_matching_zone_pair_by_keys function."""

    def test_finds_first_match(self):
        pairs = [
            {
                "id": "1",
                "source": "Limgrave",
                "target": "Caelid",
                "source_key": "limgrave",
                "target_key": "caelid",
                "type": "random",
            }
        ]
        source_candidates = [("limgrave", "Limgrave")]
        target_candidates = [("caelid", "Caelid")]
        result = find_matching_zone_pair_by_keys(pairs, source_candidates, target_candidates)
        assert result is not None
        source, target, pair = result
        assert source == "Limgrave"
        assert target == "Caelid"

    def test_tries_all_combinations(self):
        pairs = [
            {
                "id": "1",
                "source": "Zone A",
                "target": "Zone B",
                "source_key": "zone_a_alt",
                "target_key": "zone_b",
                "type": "random",
            }
        ]
        source_candidates = [("zone_a", "Zone A"), ("zone_a_alt", "Zone A")]
        target_candidates = [("zone_b", "Zone B")]
        result = find_matching_zone_pair_by_keys(pairs, source_candidates, target_candidates)
        assert result is not None

    def test_no_match_returns_none(self):
        pairs = []
        source_candidates = [("zone_a", "Zone A")]
        target_candidates = [("zone_b", "Zone B")]
        result = find_matching_zone_pair_by_keys(pairs, source_candidates, target_candidates)
        assert result is None


class TestFindAllMatchingZonePairsByKeys:
    """Tests for find_all_matching_zone_pairs_by_keys function."""

    def test_finds_all_matches(self):
        pairs = [
            {
                "id": "1",
                "source": "Zone A",
                "target": "Zone B",
                "source_key": "zone_a",
                "target_key": "zone_b",
                "type": "random",
            },
            {
                "id": "2",
                "source": "Zone A",
                "target": "Zone C",
                "source_key": "zone_a",
                "target_key": "zone_c",
                "type": "random",
            },
        ]
        source_candidates = [("zone_a", "Zone A")]
        target_candidates = [("zone_b", "Zone B"), ("zone_c", "Zone C")]
        result = find_all_matching_zone_pairs_by_keys(pairs, source_candidates, target_candidates)
        assert len(result) == 2

    def test_deduplicates_by_pair_id(self):
        pairs = [
            {
                "id": "1",
                "source": "Zone A",
                "target": "Zone B",
                "source_key": "zone_a",
                "target_key": "zone_b",
                "type": "random",
            }
        ]
        # Same pair matched from different candidate combinations
        source_candidates = [("zone_a", "Zone A"), ("zone_a", "Zone A Alt")]
        target_candidates = [("zone_b", "Zone B")]
        result = find_all_matching_zone_pairs_by_keys(pairs, source_candidates, target_candidates)
        assert len(result) == 1  # Deduplicated


class TestFindMatchingZonePair:
    """Tests for find_matching_zone_pair function."""

    def test_finds_match(self, simple_zone_pairs):
        source_candidates = [("chapel", "Chapel of Anticipation")]
        target_candidates = [("limgrave", "Limgrave")]
        result = find_matching_zone_pair(simple_zone_pairs, source_candidates, target_candidates)
        assert result is not None
        source, target, pair = result
        assert source == "Chapel of Anticipation"
        assert target == "Limgrave"

    def test_tries_candidates_in_order(self, simple_zone_pairs):
        # First candidate doesn't match, second does
        source_candidates = [("wrong", "Wrong Zone"), ("chapel", "Chapel of Anticipation")]
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
        candidates = find_candidate_zones(simple_zone_pairs, "Limgrave")
        assert len(candidates) >= 2  # Limgrave is source in multiple links

    def test_finds_zones_as_target(self, simple_zone_pairs):
        candidates = find_candidate_zones(simple_zone_pairs, "Stormveil Castle")
        assert len(candidates) >= 1

    def test_no_candidates(self, simple_zone_pairs):
        candidates = find_candidate_zones(simple_zone_pairs, "Nonexistent Zone")
        assert len(candidates) == 0


class TestFindSimilarZones:
    """Tests for find_similar_zones function."""

    def test_finds_substring_match(self, simple_zone_pairs):
        similar = find_similar_zones(simple_zone_pairs, "Castle")
        assert any("Castle" in z for z in similar)

    def test_finds_word_overlap(self, simple_zone_pairs):
        similar = find_similar_zones(simple_zone_pairs, "Stormveil")
        assert "Stormveil Castle" in similar

    def test_respects_limit(self, simple_zone_pairs):
        similar = find_similar_zones(simple_zone_pairs, "a", limit=2)
        assert len(similar) <= 2

    def test_no_match(self, simple_zone_pairs):
        similar = find_similar_zones(simple_zone_pairs, "XYZXYZXYZ")
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
            "Chapel of Anticipation",
            "Limgrave",
            simple_zone_pairs,
        )

    def test_link_discovered_reverse_direction(
        self, simple_zone_pairs, discovered_chapel_to_limgrave
    ):
        # Random links are bidirectional, should match in reverse
        assert is_link_discovered(
            discovered_chapel_to_limgrave,
            "Limgrave",
            "Chapel of Anticipation",
            simple_zone_pairs,
        )

    def test_link_not_discovered(self, simple_zone_pairs, discovered_chapel_to_limgrave):
        assert not is_link_discovered(
            discovered_chapel_to_limgrave,
            "Limgrave",
            "Caelid",
            simple_zone_pairs,
        )

    def test_link_with_parenthetical_name(self, simple_zone_pairs, discovered_chapel_to_limgrave):
        # Should match even with parenthetical suffix
        assert is_link_discovered(
            discovered_chapel_to_limgrave,
            "Chapel of Anticipation (detail)",
            "Limgrave",
            simple_zone_pairs,
        )


class TestFindPathPrioritizingDiscovered:
    """Tests for find_path_prioritizing_discovered function."""

    def test_start_node_returns_empty(self, simple_zone_pairs):
        path = find_path_prioritizing_discovered(simple_zone_pairs, [], START_NODE)
        assert path == []

    def test_finds_path_to_adjacent(self, simple_zone_pairs):
        path = find_path_prioritizing_discovered(simple_zone_pairs, [], "Limgrave")
        assert len(path) == 1
        assert path[0] == (START_NODE, "Limgrave")

    def test_finds_longer_path(self, simple_zone_pairs):
        # Path to Stormveil: Chapel -> Limgrave -> Stormveil (via preexisting)
        path = find_path_prioritizing_discovered(simple_zone_pairs, [], "Stormveil Castle")
        assert len(path) >= 1  # At least one hop

    def test_prioritizes_discovered_nodes(self, simple_zone_pairs, discovered_chapel_to_limgrave):
        # When Limgrave is discovered, path to Caelid should go through Limgrave
        path = find_path_prioritizing_discovered(
            simple_zone_pairs, discovered_chapel_to_limgrave, "Caelid"
        )
        # The path should include Limgrave
        all_nodes = set()
        for src, tgt in path:
            all_nodes.add(src)
            all_nodes.add(tgt)
        assert "Limgrave" in all_nodes

    def test_unreachable_returns_empty(self, simple_zone_pairs):
        # Isolated Zone is not reachable from START
        path = find_path_prioritizing_discovered(simple_zone_pairs, [], "Isolated Zone")
        assert path == []


class TestComputeZoneExits:
    """Tests for compute_zone_exits function."""

    def test_finds_random_exits(self, simple_zone_pairs, discovered_chapel_to_limgrave):
        exits = compute_zone_exits(simple_zone_pairs, discovered_chapel_to_limgrave, "Limgrave")
        # Limgrave has exit to Caelid (random, link-4)
        assert len(exits) >= 1
        exit_targets = [e["target"] for e in exits]
        # Caelid not yet discovered, so should be "???"
        assert "???" in exit_targets or "Caelid" in exit_targets

    def test_discovered_exits_show_target(self, simple_zone_pairs, discovered_to_caelid):
        exits = compute_zone_exits(simple_zone_pairs, discovered_to_caelid, "Limgrave")
        # Caelid is discovered, should show target name
        exit_targets = [e["target"] for e in exits]
        assert "Caelid" in exit_targets

    def test_undiscovered_exits_show_placeholder(
        self, simple_zone_pairs, discovered_chapel_to_limgrave
    ):
        exits = compute_zone_exits(simple_zone_pairs, discovered_chapel_to_limgrave, "Limgrave")
        # Find the exit to Caelid (not discovered)
        caelid_exit = next((e for e in exits if e.get("id") == "link-4"), None)
        if caelid_exit:
            assert caelid_exit["target"] == "???"

    def test_includes_description(self, simple_zone_pairs, discovered_chapel_to_limgrave):
        exits = compute_zone_exits(simple_zone_pairs, discovered_chapel_to_limgrave, "Limgrave")
        # link-4 has source_details "near the beach"
        caelid_exit = next((e for e in exits if e.get("id") == "link-4"), None)
        if caelid_exit:
            assert caelid_exit["description"] == "near the beach"

    def test_excludes_internal_preexisting_exits(self, simple_zone_pairs, discovered_to_caelid):
        # From Caelid, the preexisting link to Dragonbarrow is internal (merged zone)
        exits = compute_zone_exits(simple_zone_pairs, discovered_to_caelid, "Caelid")
        # Should not include preexisting links within the same merged group
        exit_ids = [e["id"] for e in exits]
        # link-5 and link-6 are preexisting Caelid<->Dragonbarrow - should not appear as exits
        assert "link-5" not in exit_ids
        assert "link-6" not in exit_ids

    def test_one_way_exit_only_forward(self, simple_zone_pairs):
        # From Divine Tower, cannot exit back through one-way sending gate
        discovered = [{"zone_link_id": "link-8"}]  # Sending Gate -> Divine Tower
        exits = compute_zone_exits(simple_zone_pairs, discovered, "Divine Tower")
        # Should NOT have an exit back to Sending Gate Origin (one-way)
        exit_targets = [e.get("target") for e in exits]
        assert "Sending Gate Origin" not in exit_targets

    def test_preexisting_bidirectional_without_reverse_link(self):
        """
        Test that preexisting links are bidirectional based on is_inherently_one_way field,
        even when no explicit reverse link exists in the data.

        Bug fix scenario (Elphael):
        - After Loretta -> Elphael (preexisting, is_inherently_one_way: false)
        - Yelough -> After Loretta (random)
        - From Elphael, we should see exits from both Elphael AND After Loretta
        """
        zone_pairs = [
            {
                "id": "link-yelough-afterloretta",
                "source": "Yelough Anix Tunnel",
                "target": "After Loretta",
                "type": "random",
                "source_details": "at the front of Astel's arena",
                "target_details": "after Loretta's arena",
                "is_inherently_one_way": False,
            },
            {
                "id": "link-afterloretta-elphael",
                "source": "After Loretta",
                "target": "Elphael",
                "type": "preexisting",
                "source_details": None,
                "target_details": "at the elevator",
                "is_inherently_one_way": False,  # Bidirectional elevator
            },
            {
                "id": "link-elphael-malenia",
                "source": "Elphael",
                "target": "Sellia Crystal Tunnel",
                "type": "random",
                "source_details": "before Malenia's arena",
                "target_details": "before Fallingstar Beast",
                "is_inherently_one_way": False,
            },
        ]

        # No discovered links
        discovered = []

        # From Elphael, merged zones should include After Loretta via preexisting
        merged = get_zones_via_preexisting(zone_pairs, "Elphael")
        assert "Elphael" in merged
        assert "After Loretta" in merged  # This was the bug - After Loretta was missing

        # Compute exits - should have 2 exits
        exits = compute_zone_exits(zone_pairs, discovered, "Elphael")
        exit_descriptions = {e["description"] for e in exits}

        # Exit from Elphael itself (to Sellia via Malenia fog gate)
        assert "before Malenia's arena" in exit_descriptions

        # Exit from After Loretta (back through the Yelough fog gate)
        assert "after Loretta's arena" in exit_descriptions

        # Verify from_zone is set correctly
        yelough_exit = next(e for e in exits if e["description"] == "after Loretta's arena")
        assert yelough_exit["from_zone"] == "After Loretta"

        malenia_exit = next(e for e in exits if e["description"] == "before Malenia's arena")
        assert malenia_exit["from_zone"] is None  # Same as current zone


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

    def test_source_not_accessible_before_backprop(self, backprop_preexisting_zone_pairs):
        """Zone C should not be accessible from START with no discovered links."""
        discovered_links = []
        accessible = is_accessible_from_start(
            discovered_links, "Zone C", backprop_preexisting_zone_pairs
        )
        assert not accessible

    def test_backprop_path_includes_preexisting_zones(self, backprop_preexisting_zone_pairs):
        """Back-propagation path to Zone C should include B (via preexisting link)."""
        discovered_links = []
        path = find_path_prioritizing_discovered(
            backprop_preexisting_zone_pairs, discovered_links, "Zone C"
        )
        # Path should be: START -> A, A -> B, B -> C
        assert len(path) == 3
        sources = [src for src, _ in path]
        targets = [tgt for _, tgt in path]
        assert "Chapel of Anticipation" in sources
        assert "Zone A" in sources or "Zone A" in targets
        assert "Zone B" in sources or "Zone B" in targets
        assert "Zone C" in targets

    def test_preexisting_adjacency_includes_boss_link(self, backprop_preexisting_zone_pairs):
        """Zone C should have preexisting link to Boss Arena in adjacency."""
        preexisting_adj = build_preexisting_adjacency(backprop_preexisting_zone_pairs)
        c_neighbors = [neighbor for neighbor, _ in preexisting_adj.get("Zone C", [])]
        assert "Boss Arena" in c_neighbors
        assert "Zone B" in c_neighbors

    def test_zones_needing_preexisting_propagation(self, backprop_preexisting_zone_pairs):
        """
        After back-propagation, zones in the path should have their preexisting
        links identified for propagation.

        This tests the logic that was missing before the fix:
        - Zone C (the source) has preexisting to Boss Arena
        - Zone B (in backprop path) has preexisting to Zone C
        """
        discovered_links = []
        preexisting_adj = build_preexisting_adjacency(backprop_preexisting_zone_pairs)

        # Find backprop path
        path = find_path_prioritizing_discovered(
            backprop_preexisting_zone_pairs, discovered_links, "Zone C"
        )

        # Collect zones from backprop path
        backprop_zones = set()
        for _src, dst in path:
            backprop_zones.add(dst)
        backprop_zones.add("Zone C")  # The source itself

        # These zones should have preexisting links that need propagation
        preexisting_to_propagate = []
        for zone in backprop_zones:
            for neighbor, _ in preexisting_adj.get(zone, []):
                preexisting_to_propagate.append((zone, neighbor))

        # Zone C -> Boss Arena should be in the list
        assert ("Zone C", "Boss Arena") in preexisting_to_propagate
        # Zone B -> Zone C should also be there (though Zone C is already in path)
        assert ("Zone B", "Zone C") in preexisting_to_propagate

    def test_get_zones_via_preexisting_from_source(self, backprop_preexisting_zone_pairs):
        """get_zones_via_preexisting should return Boss Arena from Zone C."""
        reachable = get_zones_via_preexisting(backprop_preexisting_zone_pairs, "Zone C")
        assert "Boss Arena" in reachable
        assert "Zone B" in reachable
        # Zone C itself should be in the set
        assert "Zone C" in reachable
