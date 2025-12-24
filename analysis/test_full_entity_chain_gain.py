#!/usr/bin/env python3
"""
Analyze the full chain of entity-based resolution improvements.

This script measures:
1. Base method (map + position): X perfect, Y duplicates
2. + dest_entity lookup: fixes some duplicates
3. + source_entity lookup: fixes more duplicates

The goal is to quantify exactly how many of the remaining duplicates
after dest_entity lookup can be resolved using source_entity.
"""

import json
import sys
from pathlib import Path

# Add server module to path
sys.path.insert(0, str(Path(__file__).parent.parent / "server"))

# Add fog directory for match_entity_to_zone_pair
FOG_DIR = Path(__file__).parent.parent.parent / "fog"
sys.path.insert(0, str(FOG_DIR))

from test_zone_mapping import FogDataIndex
from fogvizu.zone_resolver import ZoneResolver
from fogvizu.zone_matching import find_all_matching_zone_pairs, strip_parenthetical
from match_entity_to_zone_pair import extract_fog_warps


def normalize_link(source: str, target: str) -> frozenset:
    """Normalize a link to a frozenset for comparison."""
    return frozenset([strip_parenthetical(source), strip_parenthetical(target)])


def categorize_zone_pairs(zone_pairs: list, index: FogDataIndex, resolver: ZoneResolver):
    """Categorize zone_pairs by resolution quality."""
    categories = {
        'perfect': {},
        'duplicates': {},
        'not_found': {},
    }

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

        source_candidates = resolver.resolve_all_candidates(
            source_map_id, source_pos[0], source_pos[1], source_pos[2]
        )
        target_candidates = resolver.resolve_all_candidates(
            target_map_id, target_pos[0], target_pos[1], target_pos[2]
        )

        source_from_detail = resolver.lookup_spoiler_name(source_name)
        if source_from_detail[0] and source_from_detail not in source_candidates:
            source_candidates.append(source_from_detail)
        target_from_detail = resolver.lookup_spoiler_name(target_name)
        if target_from_detail[0] and target_from_detail not in target_candidates:
            target_candidates.append(target_from_detail)

        if not source_candidates or not target_candidates:
            categories['not_found'][normalized] = pair_info
            continue

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

    return covered_links, lookup


def build_source_entity_index(fog_warps, entity_lookup: dict) -> dict:
    """
    Build an index: for each dest_entity NOT in lookup,
    check if its source_entity IS in lookup.

    Returns: dest_entity -> inferred zone pair info
    """
    source_entity_recovery = {}

    for warp in fog_warps:
        dest_str = str(warp.dest_entity)

        # Skip if already in lookup
        if dest_str in entity_lookup:
            continue

        # Check if source_entity is in lookup
        if warp.source_entity:
            source_str = str(warp.source_entity)
            if source_str in entity_lookup:
                lookup_info = entity_lookup[source_str]
                # Infer zone pair by reversing source/destination
                source_entity_recovery[warp.dest_entity] = {
                    'source_entity': warp.source_entity,
                    # Reversed from lookup entry
                    'inferred_source': lookup_info['destination'],
                    'inferred_destination': lookup_info['source'],
                    'warp_source_map': warp.source_map,
                    'warp_dest_map': warp.dest_map,
                }

    return source_entity_recovery


def main():
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    fog_dir = project_root.parent / "fog"

    spoiler_json = script_dir / "1078869800.json"
    entity_lookup_json = fog_dir / "entity_zone_lookup.json"
    data_dir = project_root / "server" / "data"

    if not spoiler_json.exists():
        print(f"Error: Spoiler log not found: {spoiler_json}")
        sys.exit(1)
    if not entity_lookup_json.exists():
        print(f"Error: Entity lookup not found: {entity_lookup_json}")
        sys.exit(1)

    print("=" * 70)
    print("FULL ENTITY CHAIN GAIN ANALYSIS")
    print("=" * 70)
    print()

    # Load data
    print(f"Loading spoiler log: {spoiler_json.name}")
    with open(spoiler_json) as f:
        zone_pairs = json.load(f)

    print(f"Loading entity lookup: {entity_lookup_json.name}")
    covered_links, entity_lookup = load_entity_lookup(entity_lookup_json)
    print(f"  Entity lookup covers {len(covered_links)} unique links")

    print(f"Loading zone data from: {data_dir}")
    index = FogDataIndex(data_dir)
    resolver = ZoneResolver(data_dir)

    # Extract fog warps for source_entity analysis
    print("Extracting fog warps from EMEVD...")
    fog_warps = extract_fog_warps()
    print(f"  Found {len(fog_warps)} fog warp events")

    # Build source_entity recovery index
    source_entity_recovery = build_source_entity_index(fog_warps, entity_lookup)
    print(f"  Source entity can recover {len(source_entity_recovery)} additional warps")
    print()

    # Categorize zone pairs
    print("Analyzing resolution quality...")
    categories = categorize_zone_pairs(zone_pairs, index, resolver)

    n_perfect = len(categories['perfect'])
    n_duplicates = len(categories['duplicates'])
    n_not_found = len(categories['not_found'])
    n_total = n_perfect + n_duplicates + n_not_found

    # =========================================================================
    # STAGE 1: Base method
    # =========================================================================
    print("=" * 70)
    print("STAGE 1: BASE METHOD (map + position)")
    print("=" * 70)
    print(f"Total random links:     {n_total}")
    print(f"  ✓ Perfect (1 match):  {n_perfect:3d} ({n_perfect/n_total*100:5.1f}%)")
    print(f"  ⚠ Duplicates (2+):    {n_duplicates:3d} ({n_duplicates/n_total*100:5.1f}%)")
    print(f"  ✗ Not found:          {n_not_found:3d} ({n_not_found/n_total*100:5.1f}%)")
    print()

    # =========================================================================
    # STAGE 2: + dest_entity lookup
    # =========================================================================
    dest_fixes_duplicates = sum(1 for link in categories['duplicates'] if link in covered_links)
    dest_fixes_not_found = sum(1 for link in categories['not_found'] if link in covered_links)

    stage2_perfect = n_perfect + dest_fixes_duplicates + dest_fixes_not_found
    stage2_duplicates = n_duplicates - dest_fixes_duplicates
    stage2_not_found = n_not_found - dest_fixes_not_found

    print("=" * 70)
    print("STAGE 2: + DEST_ENTITY LOOKUP")
    print("=" * 70)
    print(f"Total random links:     {n_total}")
    print(f"  ✓ Perfect (1 match):  {stage2_perfect:3d} ({stage2_perfect/n_total*100:5.1f}%) [+{dest_fixes_duplicates + dest_fixes_not_found}]")
    print(f"  ⚠ Duplicates (2+):    {stage2_duplicates:3d} ({stage2_duplicates/n_total*100:5.1f}%) [-{dest_fixes_duplicates}]")
    print(f"  ✗ Not found:          {stage2_not_found:3d} ({stage2_not_found/n_total*100:5.1f}%) [-{dest_fixes_not_found}]")
    print()

    # =========================================================================
    # STAGE 3: + source_entity recovery
    # =========================================================================
    # Build set of links recoverable via source_entity
    source_entity_links = set()
    for dest_entity, info in source_entity_recovery.items():
        normalized = normalize_link(info['inferred_source'], info['inferred_destination'])
        source_entity_links.add(normalized)

    # Check remaining duplicates (those not fixed by dest_entity)
    remaining_duplicates = [link for link in categories['duplicates'] if link not in covered_links]
    source_fixes_duplicates = sum(1 for link in remaining_duplicates if link in source_entity_links)

    # Check remaining not_found
    remaining_not_found = [link for link in categories['not_found'] if link not in covered_links]
    source_fixes_not_found = sum(1 for link in remaining_not_found if link in source_entity_links)

    stage3_perfect = stage2_perfect + source_fixes_duplicates + source_fixes_not_found
    stage3_duplicates = stage2_duplicates - source_fixes_duplicates
    stage3_not_found = stage2_not_found - source_fixes_not_found

    print("=" * 70)
    print("STAGE 3: + SOURCE_ENTITY RECOVERY")
    print("=" * 70)
    print(f"Total random links:     {n_total}")
    print(f"  ✓ Perfect (1 match):  {stage3_perfect:3d} ({stage3_perfect/n_total*100:5.1f}%) [+{source_fixes_duplicates + source_fixes_not_found}]")
    print(f"  ⚠ Duplicates (2+):    {stage3_duplicates:3d} ({stage3_duplicates/n_total*100:5.1f}%) [-{source_fixes_duplicates}]")
    print(f"  ✗ Not found:          {stage3_not_found:3d} ({stage3_not_found/n_total*100:5.1f}%) [-{source_fixes_not_found}]")
    print()

    # =========================================================================
    # SUMMARY
    # =========================================================================
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print()
    print("                        Perfect   Duplicates   Not Found")
    print(f"Base method:            {n_perfect:3d}       {n_duplicates:3d}          {n_not_found:3d}")
    print(f"+ dest_entity:          {stage2_perfect:3d}       {stage2_duplicates:3d}          {stage2_not_found:3d}   (+{dest_fixes_duplicates + dest_fixes_not_found} fixed)")
    print(f"+ source_entity:        {stage3_perfect:3d}       {stage3_duplicates:3d}          {stage3_not_found:3d}   (+{source_fixes_duplicates + source_fixes_not_found} fixed)")
    print()

    total_gain_dest = dest_fixes_duplicates + dest_fixes_not_found
    total_gain_source = source_fixes_duplicates + source_fixes_not_found
    total_gain = total_gain_dest + total_gain_source

    print(f"Total improvement: {n_perfect} → {stage3_perfect} perfect ({total_gain} links fixed)")
    print(f"  - dest_entity:   +{total_gain_dest}")
    print(f"  - source_entity: +{total_gain_source}")
    print()

    # Show details if verbose
    if "-v" in sys.argv or "--verbose" in sys.argv:
        if source_fixes_duplicates > 0:
            print("=" * 70)
            print(f"DUPLICATES FIXED BY SOURCE_ENTITY ({source_fixes_duplicates})")
            print("=" * 70)
            for link in remaining_duplicates:
                if link in source_entity_links:
                    info = categories['duplicates'][link]
                    print(f"  '{info['source']}' ↔ '{info['destination']}'")
                    print(f"    Was: {info['num_matches']} matches → Now: 1 match (via source_entity)")
            print()

        final_duplicates = [link for link in remaining_duplicates if link not in source_entity_links]
        if final_duplicates:
            print("=" * 70)
            print(f"REMAINING DUPLICATES ({len(final_duplicates)})")
            print("=" * 70)
            for link in final_duplicates[:10]:
                info = categories['duplicates'][link]
                print(f"  '{info['source']}' ↔ '{info['destination']}'")
                print(f"    {info['num_matches']} matches")
            if len(final_duplicates) > 10:
                print(f"  ... and {len(final_duplicates) - 10} more")
            print()

    # Final verdict
    print("=" * 70)
    print("VERDICT")
    print("=" * 70)
    if total_gain_source == 0:
        print(f"❌ source_entity provides NO additional benefit over dest_entity alone.")
    elif total_gain_source < 3:
        print(f"⚠️  source_entity provides MARGINAL benefit: +{total_gain_source} links fixed.")
        print(f"   May not be worth the implementation complexity.")
    else:
        print(f"✅ source_entity provides ADDITIONAL benefit: +{total_gain_source} links fixed.")
        print(f"   Combined with dest_entity: {total_gain} total improvement.")
    print()


if __name__ == "__main__":
    main()
