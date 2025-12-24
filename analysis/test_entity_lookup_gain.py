#!/usr/bin/env python3
"""
POC: Measure the gain from using entity_zone_lookup.json for fog gate matching.

This script compares:
1. Current method (test_fog_resolution.py): map-based matching with potential duplicates
2. Entity lookup method: precise matching by destination_entity_id

We want to know: how many "problem cases" (duplicates, not found) are solved by the lookup?
"""

import json
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


def normalize_link(source: str, target: str) -> frozenset:
    """Normalize a link to a frozenset for comparison."""
    return frozenset([strip_parenthetical(source), strip_parenthetical(target)])


def categorize_zone_pairs(zone_pairs: list, index: FogDataIndex, resolver: ZoneResolver):
    """
    Categorize zone_pairs by resolution quality.

    Returns dict with:
    - 'perfect': links resolved to exactly 1 match
    - 'duplicates': links resolved to 2+ matches
    - 'not_found': links that couldn't be resolved

    Each category is a dict mapping normalized_link -> zone_pair info
    """
    categories = {
        'perfect': {},      # 1 match
        'duplicates': {},   # 2+ matches
        'not_found': {},    # 0 matches
    }

    # Only test random links, deduplicated
    seen_links = set()
    random_pairs = []
    for p in zone_pairs:
        if p["type"] != "random":
            continue
        link_key = frozenset([p["source"], p["destination"]])
        if link_key not in seen_links:
            seen_links.add(link_key)
            random_pairs.append(p)

    for pair in random_pairs:
        source_name = pair["source"]
        target_name = pair["destination"]
        source_details = pair.get("source_details")
        target_details = pair.get("target_details")

        # Reverse lookup to get map_id + position
        source_map_ids, _, source_pos = index.find_map_ids(source_name, source_details)
        target_map_ids, _, target_pos = index.find_map_ids(target_name, target_details)

        source_map_id = source_map_ids[0] if source_map_ids else None
        target_map_id = target_map_ids[0] if target_map_ids else None
        source_pos = source_pos or (0.0, 0.0, 0.0)
        target_pos = target_pos or (0.0, 0.0, 0.0)

        normalized = normalize_link(source_name, target_name)
        pair_info = {
            'source': source_name,
            'destination': target_name,
            'source_details': source_details,
            'target_details': target_details,
            'source_map_id': source_map_id,
            'target_map_id': target_map_id,
        }

        if not source_map_id or not target_map_id:
            categories['not_found'][normalized] = pair_info
            continue

        # Get zone candidates from resolver
        source_candidates = resolver.resolve_all_candidates(
            source_map_id, source_pos[0], source_pos[1], source_pos[2]
        )
        target_candidates = resolver.resolve_all_candidates(
            target_map_id, target_pos[0], target_pos[1], target_pos[2]
        )

        # Fallback: try spoiler name lookup
        source_from_detail = resolver.lookup_spoiler_name(source_name)
        if source_from_detail[0] and source_from_detail not in source_candidates:
            source_candidates.append(source_from_detail)
        target_from_detail = resolver.lookup_spoiler_name(target_name)
        if target_from_detail[0] and target_from_detail not in target_candidates:
            target_candidates.append(target_from_detail)

        if not source_candidates or not target_candidates:
            categories['not_found'][normalized] = pair_info
            continue

        # Find all matching zone pairs
        all_matches = find_all_matching_zone_pairs(
            zone_pairs,
            source_candidates[:15],
            target_candidates[:15],
        )

        num_matches = len(all_matches)
        pair_info['num_matches'] = num_matches
        pair_info['matches'] = [(src, tgt) for src, tgt, _ in all_matches]

        if num_matches == 0:
            categories['not_found'][normalized] = pair_info
        elif num_matches == 1:
            categories['perfect'][normalized] = pair_info
        else:
            categories['duplicates'][normalized] = pair_info

    return categories


def load_entity_lookup(lookup_path: Path) -> dict:
    """Load entity_zone_lookup.json and build a set of covered links."""
    with open(lookup_path) as f:
        data = json.load(f)

    lookup = data.get('lookup', {})

    # Build set of normalized links covered by lookup
    covered_links = {}
    for entity_id, info in lookup.items():
        source = info['source']
        destination = info['destination']
        normalized = normalize_link(source, destination)

        if normalized not in covered_links:
            covered_links[normalized] = {
                'entity_ids': [],
                'source': source,
                'destination': destination,
                'type': info.get('type', 'random'),
            }
        covered_links[normalized]['entity_ids'].append(int(entity_id))

    return covered_links


def main():
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    fog_dir = project_root.parent / "fog"

    # Paths
    spoiler_json = script_dir / "1078869800.json"
    entity_lookup_json = fog_dir / "entity_zone_lookup.json"
    data_dir = project_root / "server" / "data"

    # Check files exist
    if not spoiler_json.exists():
        print(f"Error: Spoiler log not found: {spoiler_json}")
        sys.exit(1)
    if not entity_lookup_json.exists():
        print(f"Error: Entity lookup not found: {entity_lookup_json}")
        sys.exit(1)
    if not data_dir.exists():
        print(f"Error: Data directory not found: {data_dir}")
        sys.exit(1)

    print("=" * 70)
    print("ENTITY LOOKUP GAIN ANALYSIS")
    print("=" * 70)
    print()

    # Load zone_pairs
    print(f"Loading spoiler log: {spoiler_json.name}")
    with open(spoiler_json) as f:
        zone_pairs = json.load(f)

    # Load entity lookup
    print(f"Loading entity lookup: {entity_lookup_json.name}")
    covered_links = load_entity_lookup(entity_lookup_json)
    print(f"  Entity lookup covers {len(covered_links)} unique links")

    # Initialize index and resolver
    print(f"Loading zone data from: {data_dir}")
    index = FogDataIndex(data_dir)
    resolver = ZoneResolver(data_dir)
    print()

    # Categorize zone_pairs using current method
    print("Analyzing current resolution method...")
    categories = categorize_zone_pairs(zone_pairs, index, resolver)
    print()

    # Stats for current method
    n_perfect = len(categories['perfect'])
    n_duplicates = len(categories['duplicates'])
    n_not_found = len(categories['not_found'])
    n_total = n_perfect + n_duplicates + n_not_found

    print("=" * 70)
    print("CURRENT METHOD (map + position based)")
    print("=" * 70)
    print(f"Total random links:     {n_total}")
    print(f"  ✓ Perfect (1 match):  {n_perfect:3d} ({n_perfect/n_total*100:5.1f}%)")
    print(f"  ⚠ Duplicates (2+):    {n_duplicates:3d} ({n_duplicates/n_total*100:5.1f}%)")
    print(f"  ✗ Not found:          {n_not_found:3d} ({n_not_found/n_total*100:5.1f}%)")
    print()

    # Analyze what entity lookup can fix
    print("=" * 70)
    print("ENTITY LOOKUP COVERAGE")
    print("=" * 70)

    # How many perfect cases are also in lookup (redundant coverage)
    lookup_covers_perfect = sum(1 for link in categories['perfect'] if link in covered_links)

    # How many duplicate cases are solved by lookup (THE KEY METRIC)
    lookup_fixes_duplicates = sum(1 for link in categories['duplicates'] if link in covered_links)

    # How many not_found cases are solved by lookup
    lookup_fixes_not_found = sum(1 for link in categories['not_found'] if link in covered_links)

    print(f"Links covered by entity lookup: {len(covered_links)}")
    print()
    print("Coverage breakdown:")
    print(f"  Already perfect:      {lookup_covers_perfect:3d} (redundant, no gain)")
    print(f"  Fixes duplicates:     {lookup_fixes_duplicates:3d} ← POTENTIAL GAIN")
    print(f"  Fixes not found:      {lookup_fixes_not_found:3d} ← POTENTIAL GAIN")
    print()

    # Calculate combined stats
    print("=" * 70)
    print("COMBINED METHOD (entity lookup + fallback)")
    print("=" * 70)

    new_perfect = n_perfect + lookup_fixes_duplicates + lookup_fixes_not_found
    new_duplicates = n_duplicates - lookup_fixes_duplicates
    new_not_found = n_not_found - lookup_fixes_not_found

    print(f"Total random links:     {n_total}")
    print(f"  ✓ Perfect (1 match):  {new_perfect:3d} ({new_perfect/n_total*100:5.1f}%) [+{lookup_fixes_duplicates + lookup_fixes_not_found}]")
    print(f"  ⚠ Duplicates (2+):    {new_duplicates:3d} ({new_duplicates/n_total*100:5.1f}%) [-{lookup_fixes_duplicates}]")
    print(f"  ✗ Not found:          {new_not_found:3d} ({new_not_found/n_total*100:5.1f}%) [-{lookup_fixes_not_found}]")
    print()

    # Show which duplicates are fixed
    if lookup_fixes_duplicates > 0 and ("-v" in sys.argv or "--verbose" in sys.argv):
        print("=" * 70)
        print("DUPLICATES FIXED BY ENTITY LOOKUP")
        print("=" * 70)
        for link in categories['duplicates']:
            if link in covered_links:
                info = categories['duplicates'][link]
                lookup_info = covered_links[link]
                print(f"'{info['source']}' ↔ '{info['destination']}'")
                print(f"  Was: {info['num_matches']} matches → Now: 1 match")
                print(f"  Entity IDs: {lookup_info['entity_ids']}")
                print()

    # Show duplicates NOT fixed (still problematic)
    remaining_duplicates = [link for link in categories['duplicates'] if link not in covered_links]
    if remaining_duplicates and ("-v" in sys.argv or "--verbose" in sys.argv):
        print("=" * 70)
        print(f"REMAINING DUPLICATES ({len(remaining_duplicates)})")
        print("=" * 70)
        for link in remaining_duplicates[:10]:
            info = categories['duplicates'][link]
            print(f"'{info['source']}' ↔ '{info['destination']}'")
            print(f"  {info['num_matches']} matches: {info['matches'][:3]}...")
            print()
        if len(remaining_duplicates) > 10:
            print(f"... and {len(remaining_duplicates) - 10} more")

    # Final verdict
    print("=" * 70)
    print("VERDICT")
    print("=" * 70)
    total_gain = lookup_fixes_duplicates + lookup_fixes_not_found
    if total_gain == 0:
        print("❌ Entity lookup provides NO additional benefit over current method.")
        print("   All links covered by lookup are already resolved perfectly.")
    elif total_gain < 5:
        print(f"⚠️  Entity lookup provides MARGINAL benefit: {total_gain} additional links fixed.")
        print("   May not be worth the implementation complexity.")
    else:
        print(f"✅ Entity lookup provides SIGNIFICANT benefit: {total_gain} additional links fixed.")
        print(f"   - {lookup_fixes_duplicates} duplicate cases → perfect")
        print(f"   - {lookup_fixes_not_found} not found cases → perfect")
    print()


if __name__ == "__main__":
    main()
