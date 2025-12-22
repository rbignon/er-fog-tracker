"""
Tests for back-propagation cost calculation and multi-match tie-breaking.
"""

import sys
from pathlib import Path

# Add server directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "server"))

from fogvizu.zone_matching import (
    START_NODE,
    compute_backprop_cost,
    find_all_matching_zone_pairs_by_keys,
    is_accessible_from_start,
)


def test_compute_backprop_cost_already_accessible():
    """If source is already accessible, cost should be 0."""
    zone_pairs = [
        {
            "id": "1",
            "type": "random",
            "source": START_NODE,
            "destination": "Zone A",
            "source_key": "start",
            "destination_key": "zone_a",
        },
    ]
    discovered_links = [{"link_id": "1"}]

    # Zone A is accessible via discovered link
    cost = compute_backprop_cost(zone_pairs, discovered_links, "Zone A")
    assert cost == 0


def test_compute_backprop_cost_one_random_link():
    """Cost = 1 random link to reach source."""
    zone_pairs = [
        {
            "id": "1",
            "type": "random",
            "source": START_NODE,
            "destination": "Zone A",
            "source_key": "start",
            "destination_key": "zone_a",
        },
        {
            "id": "2",
            "type": "random",
            "source": "Zone A",
            "destination": "Zone B",
            "source_key": "zone_a",
            "destination_key": "zone_b",
        },
    ]
    discovered_links = []  # Nothing discovered yet

    # Zone A requires 1 random link (START -> Zone A)
    cost = compute_backprop_cost(zone_pairs, discovered_links, "Zone A")
    assert cost == 1


def test_compute_backprop_cost_preexisting_not_counted():
    """Preexisting links should not count toward cost."""
    zone_pairs = [
        {
            "id": "1",
            "type": "random",
            "source": START_NODE,
            "destination": "Zone A",
            "source_key": "start",
            "destination_key": "zone_a",
        },
        {
            "id": "2",
            "type": "preexisting",
            "source": "Zone A",
            "destination": "Zone B",
            "source_key": "zone_a",
            "destination_key": "zone_b",
        },
        {
            "id": "3",
            "type": "preexisting",
            "source": "Zone B",
            "destination": "Zone C",
            "source_key": "zone_b",
            "destination_key": "zone_c",
        },
    ]
    discovered_links = []

    # Zone C requires: START->A (random) + A->B (preexisting) + B->C (preexisting)
    # Only the random link counts
    cost = compute_backprop_cost(zone_pairs, discovered_links, "Zone C")
    assert cost == 1


def test_compute_backprop_cost_unreachable():
    """Unreachable nodes should return -1."""
    zone_pairs = [
        {
            "id": "1",
            "type": "random",
            "source": "Zone A",
            "destination": "Zone B",
            "source_key": "zone_a",
            "destination_key": "zone_b",
        },
    ]
    discovered_links = []

    # Zone A is not connected to START
    cost = compute_backprop_cost(zone_pairs, discovered_links, "Zone A")
    assert cost == -1


def test_find_all_matching_zone_pairs_by_keys_multiple_matches():
    """Should return all matching pairs, not just the first one."""
    zone_pairs = [
        {
            "id": "1",
            "type": "random",
            "source": "Zone A",
            "destination": "Zone X",
            "source_key": "zone_a",
            "destination_key": "zone_x",
        },
        {
            "id": "2",
            "type": "random",
            "source": "Zone B",
            "destination": "Zone Y",
            "source_key": "zone_b",
            "destination_key": "zone_y",
        },
        {
            "id": "3",
            "type": "random",
            "source": "Zone C",
            "destination": "Zone Z",
            "source_key": "zone_c",
            "destination_key": "zone_z",
        },
    ]

    # Candidates that could match pairs 1 and 2
    source_candidates = [
        ("zone_a", "Zone A"),
        ("zone_b", "Zone B"),
        ("zone_d", "Zone D"),  # No match
    ]
    target_candidates = [
        ("zone_x", "Zone X"),
        ("zone_y", "Zone Y"),
        ("zone_w", "Zone W"),  # No match
    ]

    matches = find_all_matching_zone_pairs_by_keys(
        zone_pairs, source_candidates, target_candidates
    )

    assert len(matches) == 2
    sources = {m[0] for m in matches}
    assert sources == {"Zone A", "Zone B"}


def test_find_all_matching_zone_pairs_by_keys_deduplication():
    """Should deduplicate by pair ID."""
    zone_pairs = [
        {
            "id": "1",
            "type": "random",
            "source": "Zone A",
            "destination": "Zone X",
            "source_key": "zone_a",
            "destination_key": "zone_x",
        },
    ]

    # Multiple candidates that all resolve to the same pair
    source_candidates = [
        ("zone_a", "Zone A"),
        ("zone_a", "Zone A Alias"),
    ]
    target_candidates = [
        ("zone_x", "Zone X"),
        ("zone_x", "Zone X Alias"),
    ]

    matches = find_all_matching_zone_pairs_by_keys(
        zone_pairs, source_candidates, target_candidates
    )

    # Should only return once despite multiple candidate combinations
    assert len(matches) == 1


def test_tiebreaker_scenario():
    """
    Simulate Roger's scenario: two matches, one with lower backprop cost.

    Graph structure:
    START -> A (random) -> B (preexisting) -> C (preexisting)
    START -> X (random) -> Y (random) -> Z (random)

    If we're looking for a match to reach C vs Z:
    - C costs 1 (one random link: START->A)
    - Z costs 3 (three random links: START->X, X->Y, Y->Z)

    The algorithm should prefer C.
    """
    zone_pairs = [
        # Path to C: 1 random + 2 preexisting
        {
            "id": "1",
            "type": "random",
            "source": START_NODE,
            "destination": "Zone A",
            "source_key": "start",
            "destination_key": "zone_a",
        },
        {
            "id": "2",
            "type": "preexisting",
            "source": "Zone A",
            "destination": "Zone B",
            "source_key": "zone_a",
            "destination_key": "zone_b",
        },
        {
            "id": "3",
            "type": "preexisting",
            "source": "Zone B",
            "destination": "Zone C",
            "source_key": "zone_b",
            "destination_key": "zone_c",
        },
        # Path to Z: 3 random
        {
            "id": "4",
            "type": "random",
            "source": START_NODE,
            "destination": "Zone X",
            "source_key": "start",
            "destination_key": "zone_x",
        },
        {
            "id": "5",
            "type": "random",
            "source": "Zone X",
            "destination": "Zone Y",
            "source_key": "zone_x",
            "destination_key": "zone_y",
        },
        {
            "id": "6",
            "type": "random",
            "source": "Zone Y",
            "destination": "Zone Z",
            "source_key": "zone_y",
            "destination_key": "zone_z",
        },
        # The pairs we're trying to match (fog gates at C and Z)
        {
            "id": "fog_c",
            "type": "random",
            "source": "Zone C",
            "destination": "Far Away",
            "source_key": "zone_c",
            "destination_key": "far_away",
        },
        {
            "id": "fog_z",
            "type": "random",
            "source": "Zone Z",
            "destination": "Far Away 2",
            "source_key": "zone_z",
            "destination_key": "far_away_2",
        },
    ]
    discovered_links = []

    # Cost to reach Zone C
    cost_c = compute_backprop_cost(zone_pairs, discovered_links, "Zone C")
    # Cost to reach Zone Z
    cost_z = compute_backprop_cost(zone_pairs, discovered_links, "Zone Z")

    assert cost_c == 1, f"Expected cost 1 for Zone C, got {cost_c}"
    assert cost_z == 3, f"Expected cost 3 for Zone Z, got {cost_z}"
    assert cost_c < cost_z, "Zone C should have lower cost than Zone Z"


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
