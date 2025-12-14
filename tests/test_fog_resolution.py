#!/usr/bin/env python3
"""
End-to-end test: simulate fog traversals and verify server resolution.

This test:
1. Loads zone_pairs from a spoiler log JSON
2. Uses reverse lookup to get map_id + estimated position for each zone
3. Calls the server's zone resolver to resolve back to zone names
4. Uses find_matching_zone_pair to disambiguate using the spoiler log
5. Verifies the resolved names match the original zone_pairs

Two modes:
- "resolver": Test the resolver alone (without spoiler log disambiguation)
- "full": Test the full flow with spoiler log disambiguation (default)
"""

import json
import sys
from pathlib import Path

# Add server module to path
sys.path.insert(0, str(Path(__file__).parent.parent / "server"))

from test_zone_mapping import FogDataIndex
from fogvizu.zone_resolver import ZoneResolver


def find_zone_pair(zone_pairs: list[dict], source: str, target: str) -> dict | None:
    """Find a zone pair matching source and target (in either direction for random links)."""
    for pair in zone_pairs:
        # Check direct match
        if pair["source"] == source and pair["destination"] == target:
            return pair
        # For random links, also check reverse (they're bidirectional)
        if pair["type"] == "random" and pair["source"] == target and pair["destination"] == source:
            return pair
    return None


def find_matching_zone_pair(
    zone_pairs: list[dict],
    source_candidates: list[tuple[str, str]],
    target_candidates: list[tuple[str, str]],
) -> tuple[str, str, dict] | None:
    """
    Find a matching zone pair from lists of candidates.

    Tries all combinations of source and target candidates until finding
    a match in zone_pairs.
    """
    for _, source_display in source_candidates:
        for _, target_display in target_candidates:
            pair = find_zone_pair(zone_pairs, source_display, target_display)
            if pair:
                return source_display, target_display, pair
    return None


def test_fog_resolution(json_path: Path, data_dir: Path, use_spoiler_log: bool = True):
    """Test that the server can resolve fog traversals correctly."""
    print(f"Loading zone_pairs from: {json_path}")
    print(f"Using data from: {data_dir}")
    print(f"Mode: {'full (with spoiler log)' if use_spoiler_log else 'resolver only'}")
    print()

    # Load zone_pairs
    with open(json_path) as f:
        zone_pairs = json.load(f)

    # Build reverse lookup index
    index = FogDataIndex(data_dir)
    print(f"Reverse index: {len(index.by_display_name)} display names")

    # Initialize server's zone resolver
    resolver = ZoneResolver(data_dir)
    print(f"Zone resolver: {len(resolver.map_rules)} map rules, {len(resolver.zone_display_names)} display names")
    print()

    # Stats
    stats = {
        "total": len(zone_pairs),
        "pair_match": 0,
        "pair_mismatch": 0,
        "pair_not_found": 0,
    }

    mismatches = []

    # Only test random links (actual fog gates), not preexisting (auto-propagated)
    random_pairs = [p for p in zone_pairs if p["type"] == "random"]
    stats["total"] = len(random_pairs)

    for pair in random_pairs:
        source_name = pair["source"]
        target_name = pair["destination"]
        source_details = pair.get("source_details")
        target_details = pair.get("target_details")

        # Step 1: Reverse lookup to get map_id + position
        source_map_ids, _, source_pos = index.find_map_ids(source_name, source_details)
        target_map_ids, _, target_pos = index.find_map_ids(target_name, target_details)

        # Use first map_id if multiple, default position if none
        source_map_id = source_map_ids[0] if source_map_ids else None
        target_map_id = target_map_ids[0] if target_map_ids else None
        source_pos = source_pos or (0.0, 0.0, 0.0)
        target_pos = target_pos or (0.0, 0.0, 0.0)

        if not source_map_id or not target_map_id:
            stats["pair_not_found"] += 1
            continue

        # Step 2: Get zone candidates from resolver
        source_candidates = resolver.resolve_all_candidates(
            source_map_id, source_pos[0], source_pos[1], source_pos[2]
        )
        target_candidates = resolver.resolve_all_candidates(
            target_map_id, target_pos[0], target_pos[1], target_pos[2]
        )

        if not source_candidates or not target_candidates:
            stats["pair_not_found"] += 1
            continue

        # Step 3: Resolve zone names
        if use_spoiler_log:
            # Full mode: use spoiler log to disambiguate
            match = find_matching_zone_pair(zone_pairs, source_candidates, target_candidates)
            if match:
                resolved_source, resolved_target, _ = match
            else:
                # Fallback to first candidate
                resolved_source = source_candidates[0][1] if source_candidates else None
                resolved_target = target_candidates[0][1] if target_candidates else None
        else:
            # Resolver-only mode: use first candidate (resolver's best guess)
            resolved_source = source_candidates[0][1] if source_candidates else None
            resolved_target = target_candidates[0][1] if target_candidates else None

        # Step 4: Compare results
        if resolved_source == source_name and resolved_target == target_name:
            stats["pair_match"] += 1
        else:
            stats["pair_mismatch"] += 1
            mismatches.append({
                "expected_source": source_name,
                "expected_target": target_name,
                "resolved_source": resolved_source,
                "resolved_target": resolved_target,
                "source_map_id": source_map_id,
                "target_map_id": target_map_id,
                "source_pos": source_pos,
                "target_pos": target_pos,
                "source_details": source_details,
                "target_details": target_details,
                "source_candidates": [c[1] for c in source_candidates[:3]],
                "target_candidates": [c[1] for c in target_candidates[:3]],
            })

    # Print mismatches
    if mismatches and ("--verbose" in sys.argv or "-v" in sys.argv or len(mismatches) <= 20):
        print("=" * 60)
        print("MISMATCHES:")
        print("=" * 60)
        for m in mismatches[:50]:  # Limit output
            print(f"Expected: '{m['expected_source']}' → '{m['expected_target']}'")
            print(f"Resolved: '{m['resolved_source']}' → '{m['resolved_target']}'")
            print(f"  Source map: {m['source_map_id']}, pos: ({m['source_pos'][0]:.1f}, {m['source_pos'][1]:.1f}, {m['source_pos'][2]:.1f})")
            print(f"  Target map: {m['target_map_id']}, pos: ({m['target_pos'][0]:.1f}, {m['target_pos'][1]:.1f}, {m['target_pos'][2]:.1f})")
            print(f"  Source candidates: {m['source_candidates']}")
            print(f"  Target candidates: {m['target_candidates']}")
            print()

        if len(mismatches) > 50:
            print(f"... and {len(mismatches) - 50} more mismatches")
            print()

    # Print summary
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total zone pairs:  {stats['total']}")
    print(f"  ✓ Match:         {stats['pair_match']}")
    print(f"  ✗ Mismatch:      {stats['pair_mismatch']}")
    print(f"  ? Not found:     {stats['pair_not_found']}")
    print()

    resolvable = stats['pair_match'] + stats['pair_mismatch']
    accuracy = stats['pair_match'] / resolvable * 100 if resolvable > 0 else 0
    print(f"ACCURACY: {accuracy:.1f}% ({stats['pair_match']}/{resolvable} pairs)")

    return len(mismatches) == 0


def main():
    if "--help" in sys.argv or "-h" in sys.argv:
        print("Usage: test_fog_resolution.py [zone_pairs.json] [options]")
        print()
        print("Simulates fog traversals and verifies server resolution.")
        print()
        print("Options:")
        print("  -v, --verbose       Show all mismatches")
        print("  --resolver-only     Test resolver without spoiler log disambiguation")
        print("  -h, --help          Show this help")
        print()
        print("Modes:")
        print("  full (default):     Uses spoiler log to disambiguate multiple candidates")
        print("  resolver-only:      Tests resolver's best guess without spoiler log")
        sys.exit(0)

    # Default paths
    script_dir = Path(__file__).parent
    project_root = script_dir.parent

    # JSON file
    json_path = None
    for arg in sys.argv[1:]:
        if not arg.startswith("-"):
            json_path = Path(arg)
            break

    if json_path is None:
        json_path = script_dir / "391139473.json"

    # Data directory
    data_dir = project_root / "server" / "data"

    # Mode
    use_spoiler_log = "--resolver-only" not in sys.argv

    if not json_path.exists():
        print(f"Error: JSON file not found: {json_path}")
        sys.exit(1)

    if not data_dir.exists():
        print(f"Error: Data directory not found: {data_dir}")
        sys.exit(1)

    success = test_fog_resolution(json_path, data_dir, use_spoiler_log)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
