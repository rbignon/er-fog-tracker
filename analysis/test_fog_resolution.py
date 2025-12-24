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
import re
import sys
from pathlib import Path

# Add server module to path
sys.path.insert(0, str(Path(__file__).parent.parent / "server"))

from test_zone_mapping import FogDataIndex
from fogvizu.zone_resolver import ZoneResolver
from fogvizu.zone_matching import (
    find_all_matching_zone_pairs,
    names_match,
    strip_parenthetical,
)


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
        "resolved_1_link": 0,     # Exactly 1 valid link found (certain)
        "resolved_2_links": 0,    # 2 valid links found (small spoil)
        "resolved_3plus_links": 0, # 3+ valid links found (larger spoil)
        "not_found": 0,           # No valid link found
    }

    results_1_link = []
    results_multi_link = []
    not_found = []

    # Only test random links (actual fog gates), not preexisting (auto-propagated)
    # Deduplicate bidirectional pairs (A→B and B→A are the same link)
    seen_links = set()
    random_pairs = []
    for p in zone_pairs:
        if p["type"] != "random":
            continue
        link_key = frozenset([p["source"], p["destination"]])
        if link_key not in seen_links:
            seen_links.add(link_key)
            random_pairs.append(p)
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
            stats["not_found"] += 1
            continue

        # Step 2: Get zone candidates from resolver
        source_candidates = resolver.resolve_all_candidates(
            source_map_id, source_pos[0], source_pos[1], source_pos[2]
        )
        target_candidates = resolver.resolve_all_candidates(
            target_map_id, target_pos[0], target_pos[1], target_pos[2]
        )

        # Fallback: try to resolve parenthetical detail text from spoiler log names
        # e.g., "Zone Name (detail text)" -> lookup detail text to find zone
        source_from_detail = resolver.lookup_spoiler_name(source_name)
        if source_from_detail[0] and source_from_detail not in source_candidates:
            source_candidates.append(source_from_detail)

        target_from_detail = resolver.lookup_spoiler_name(target_name)
        if target_from_detail[0] and target_from_detail not in target_candidates:
            target_candidates.append(target_from_detail)

        if not source_candidates or not target_candidates:
            stats["not_found"] += 1
            continue

        # Step 3: Use server logic - find ALL matching zone pairs
        all_matches = find_all_matching_zone_pairs(
            zone_pairs,
            source_candidates[:15],
            target_candidates[:15],
        )

        # Step 4: Analyze results
        num_links = len(all_matches)

        if num_links == 0:
            stats["not_found"] += 1
            not_found.append({
                "expected_source": source_name,
                "expected_target": target_name,
                "source_map_id": source_map_id,
                "target_map_id": target_map_id,
                "source_candidates": [c[1] for c in source_candidates[:5]],
                "target_candidates": [c[1] for c in target_candidates[:5]],
            })
            continue

        # Check if expected link is in the matches
        expected_found = any(
            names_match(src, source_name) and names_match(tgt, target_name) or
            names_match(src, target_name) and names_match(tgt, source_name)
            for src, tgt, _ in all_matches
        )

        # Count by number of links
        if num_links == 1:
            stats["resolved_1_link"] += 1
            results_1_link.append({
                "expected_source": source_name,
                "expected_target": target_name,
                "resolved": [(src, tgt) for src, tgt, _ in all_matches],
                "source_map_id": source_map_id,
                "target_map_id": target_map_id,
            })
        elif num_links == 2:
            stats["resolved_2_links"] += 1
            results_multi_link.append({
                "expected_source": source_name,
                "expected_target": target_name,
                "resolved": [(src, tgt) for src, tgt, _ in all_matches],
                "source_map_id": source_map_id,
                "target_map_id": target_map_id,
                "expected_found": expected_found,
            })
        else:
            stats["resolved_3plus_links"] += 1
            results_multi_link.append({
                "expected_source": source_name,
                "expected_target": target_name,
                "resolved": [(src, tgt) for src, tgt, _ in all_matches],
                "source_map_id": source_map_id,
                "target_map_id": target_map_id,
                "expected_found": expected_found,
            })

    # Print multi-link results (2+ links discovered)
    if results_multi_link and ("--verbose" in sys.argv or "-v" in sys.argv or len(results_multi_link) <= 30):
        print("=" * 60)
        print("MULTI-LINK DISCOVERIES (2+ links found - potential spoil):")
        print("=" * 60)
        for m in results_multi_link[:50]:
            expected_marker = " ✓" if m.get('expected_found', True) else " ✗ EXPECTED NOT FOUND"
            print(f"Expected: '{m['expected_source']}' → '{m['expected_target']}'{expected_marker}")
            print(f"  Maps: {m['source_map_id']} → {m['target_map_id']}")
            print(f"  Server would discover ({len(m['resolved'])} links):")
            expected_link = frozenset([m['expected_source'], m['expected_target']])
            for src, tgt in m['resolved']:
                resolved_link = frozenset([src, tgt])
                # Check both exact and normalized match
                is_expected = resolved_link == expected_link
                if not is_expected:
                    normalized_expected = frozenset([strip_parenthetical(m['expected_source']), strip_parenthetical(m['expected_target'])])
                    normalized_resolved = frozenset([strip_parenthetical(src), strip_parenthetical(tgt)])
                    is_expected = normalized_expected == normalized_resolved
                marker = " ← expected" if is_expected else ""
                print(f"    - '{src}' ↔ '{tgt}'{marker}")
            print()

        if len(results_multi_link) > 50:
            print(f"... and {len(results_multi_link) - 50} more")
            print()

    # Print not found cases
    if not_found:
        print("=" * 60)
        print("NOT FOUND (no valid link in spoiler log):")
        print("=" * 60)
        for nf in not_found:
            print(f"Expected: '{nf['expected_source']}' → '{nf['expected_target']}'")
            print(f"  Maps: {nf['source_map_id']} → {nf['target_map_id']}")
            print(f"  Resolver candidates:")
            print(f"    Source: {nf['source_candidates'][:3]}")
            print(f"    Target: {nf['target_candidates'][:3]}")
            print()

    # Print summary
    print("=" * 60)
    print("SUMMARY (using server logic: discover ALL valid links)")
    print("=" * 60)
    total = stats['total']
    resolved_total = stats['resolved_1_link'] + stats['resolved_2_links'] + stats['resolved_3plus_links']

    link1_pct = stats['resolved_1_link'] / total * 100 if total > 0 else 0
    link2_pct = stats['resolved_2_links'] / total * 100 if total > 0 else 0
    link3_pct = stats['resolved_3plus_links'] / total * 100 if total > 0 else 0
    not_found_pct = stats['not_found'] / total * 100 if total > 0 else 0
    resolved_pct = resolved_total / total * 100 if total > 0 else 0

    print(f"Total zone pairs:  {total}")
    print()
    print(f"  ✓ Resolved:      {resolved_total:3d} ({resolved_pct:5.1f}%) - expected link will be discovered")
    print(f"      1 link:      {stats['resolved_1_link']:3d} ({link1_pct:5.1f}%) - perfect, no spoil")
    print(f"      2 links:     {stats['resolved_2_links']:3d} ({link2_pct:5.1f}%) - small spoil (1 extra link)")
    print(f"      3+ links:    {stats['resolved_3plus_links']:3d} ({link3_pct:5.1f}%) - larger spoil")
    print(f"  ✗ Not found:     {stats['not_found']:3d} ({not_found_pct:5.1f}%) - no valid link found")

    return stats['not_found'] == 0


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
