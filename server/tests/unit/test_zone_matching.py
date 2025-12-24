"""Unit tests for zone_matching module.

Tests pure functions for zone name matching, graph traversal,
and discovery logic.
"""

from fogvizu.zone_matching import (
    START_NODE,
    build_full_adjacency,
    build_preexisting_adjacency,
    compute_backprop_cost,
    compute_discovery_stats,
    find_reachable_nodes,
    find_zone_pair,
    get_discovered_nodes,
    get_zones_via_preexisting,
    is_accessible_from_start,
    is_one_way,
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
