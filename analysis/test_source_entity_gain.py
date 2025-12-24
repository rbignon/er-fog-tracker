#!/usr/bin/env python3
"""
POC: Measure the potential gain from using source_entity for fog gate matching.

This script analyzes:
1. How many bidirectional entity pairs exist in the EMEVD data
2. Whether source_entity could help resolve cases that dest_entity alone cannot
3. What additional disambiguation source_entity provides

The source_entity represents the spawn point on the SOURCE side of a fog gate,
used by RotateCharacter to orient the player. For bidirectional fog gates:
- Warp A→B: dest_entity=X, source_entity=Y
- Warp B→A: dest_entity=Y, source_entity=X

So source_entity from one direction equals dest_entity from the reverse direction.

Usage:
    python test_source_entity_gain.py [-v|--verbose]
"""

import json
import sys
from pathlib import Path

# Add fog directory to path for imports
FOG_DIR = Path(__file__).parent.parent.parent / "fog"
sys.path.insert(0, str(FOG_DIR))

from match_entity_to_zone_pair import extract_fog_warps, EmevdFogWarp


def analyze_bidirectional_pairs(fog_warps: list[EmevdFogWarp]) -> dict:
    """
    Analyze bidirectional pairs in the fog warps.

    For each warp, check if its source_entity appears as another warp's dest_entity.
    If so, they form a bidirectional pair.
    """
    # Build mapping: dest_entity -> warp
    dest_to_warp = {w.dest_entity: w for w in fog_warps}

    # Find bidirectional pairs
    pairs = []
    seen = set()

    for warp in fog_warps:
        if warp.dest_entity in seen:
            continue

        source_entity = warp.source_entity
        if source_entity and source_entity in dest_to_warp:
            reverse_warp = dest_to_warp[source_entity]

            # Check if it's truly bidirectional (reverse points back)
            if reverse_warp.source_entity == warp.dest_entity:
                pairs.append({
                    'forward': {
                        'dest_entity': warp.dest_entity,
                        'source_entity': warp.source_entity,
                        'source_map': warp.source_map,
                        'dest_map': warp.dest_map,
                    },
                    'reverse': {
                        'dest_entity': reverse_warp.dest_entity,
                        'source_entity': reverse_warp.source_entity,
                        'source_map': reverse_warp.source_map,
                        'dest_map': reverse_warp.dest_map,
                    },
                })
                seen.add(warp.dest_entity)
                seen.add(source_entity)

    with_source = sum(1 for w in fog_warps if w.source_entity is not None)

    return {
        'total_warps': len(fog_warps),
        'with_source_entity': with_source,
        'bidirectional_pairs': len(pairs),
        'one_way_warps': len(fog_warps) - len(seen),
        'pairs': pairs,
    }


def analyze_coverage_with_lookup(fog_warps: list[EmevdFogWarp], entity_lookup: dict) -> dict:
    """
    Analyze how source_entity could help with lookup coverage.

    For warps NOT in the lookup, check if their source_entity IS in the lookup.
    This would allow us to infer zone names from the reverse direction.
    """
    covered_by_dest = []
    not_covered = []

    for warp in fog_warps:
        dest_str = str(warp.dest_entity)
        if dest_str in entity_lookup:
            covered_by_dest.append(warp)
        else:
            not_covered.append(warp)

    # For warps not covered, check if source_entity is covered
    recoverable_via_source = []
    for warp in not_covered:
        if warp.source_entity:
            source_str = str(warp.source_entity)
            if source_str in entity_lookup:
                lookup_info = entity_lookup[source_str]
                recoverable_via_source.append({
                    'dest_entity': warp.dest_entity,
                    'source_entity': warp.source_entity,
                    'warp_source_map': warp.source_map,
                    'warp_dest_map': warp.dest_map,
                    # Info inferred from source_entity lookup (which is reverse direction)
                    'inferred_source': lookup_info['destination'],  # Reversed!
                    'inferred_destination': lookup_info['source'],  # Reversed!
                    'lookup_direction': lookup_info.get('traversal_direction'),
                })

    return {
        'covered_by_dest': len(covered_by_dest),
        'not_covered': len(not_covered),
        'recoverable_via_source': len(recoverable_via_source),
        'still_unresolved': len(not_covered) - len(recoverable_via_source),
        'details': recoverable_via_source,
    }


def main():
    verbose = "-v" in sys.argv or "--verbose" in sys.argv

    print("=" * 70)
    print("SOURCE_ENTITY GAIN ANALYSIS")
    print("=" * 70)
    print()

    # Check for extracted events
    events_dir = FOG_DIR / "extracted_events"
    if not events_dir.exists() or not list(events_dir.glob("*.txt")):
        print(f"ERROR: No extracted events found in {events_dir}")
        print()
        print("Run this first:")
        print(f"  cd {FOG_DIR}")
        print("  python extract_events.py")
        sys.exit(1)

    # Extract fog warps from EMEVD
    print("Extracting fog warps from EMEVD files...")
    fog_warps = extract_fog_warps()
    print(f"  Found {len(fog_warps)} fog warp events")
    print()

    # Analyze bidirectional pairs
    print("=" * 70)
    print("BIDIRECTIONAL PAIR ANALYSIS")
    print("=" * 70)

    pair_analysis = analyze_bidirectional_pairs(fog_warps)
    print(f"Total fog warps:         {pair_analysis['total_warps']}")
    print(f"With source_entity:      {pair_analysis['with_source_entity']}")
    print(f"Bidirectional pairs:     {pair_analysis['bidirectional_pairs']}")
    print(f"One-way/unpaired warps:  {pair_analysis['one_way_warps']}")
    print()

    if pair_analysis['pairs'] and verbose:
        print("Sample bidirectional pairs:")
        for pair in pair_analysis['pairs'][:5]:
            print(f"  {pair['forward']['dest_entity']} ↔ {pair['reverse']['dest_entity']}")
            print(f"    Forward: {pair['forward']['source_map']} → {pair['forward']['dest_map']}")
            print(f"    Reverse: {pair['reverse']['source_map']} → {pair['reverse']['dest_map']}")
        if len(pair_analysis['pairs']) > 5:
            print(f"  ... and {len(pair_analysis['pairs']) - 5} more pairs")
        print()

    # Load entity lookup
    entity_lookup_path = FOG_DIR / "entity_zone_lookup.json"
    if not entity_lookup_path.exists():
        print(f"ERROR: Entity lookup not found: {entity_lookup_path}")
        print()
        print("Run this first:")
        print(f"  cd {FOG_DIR}")
        print("  python match_entity_to_zone_pair.py")
        sys.exit(1)

    print(f"Loading entity lookup: {entity_lookup_path.name}")
    with open(entity_lookup_path) as f:
        lookup_data = json.load(f)

    entity_lookup = lookup_data.get('lookup', {})
    print(f"  Entity lookup has {len(entity_lookup)} entries")
    print(f"  (from {lookup_data.get('total_warps', '?')} total warps, {lookup_data.get('unmatched', '?')} unmatched)")
    print()

    # Analyze coverage with source_entity
    print("=" * 70)
    print("COVERAGE ANALYSIS (source_entity recovery)")
    print("=" * 70)

    coverage = analyze_coverage_with_lookup(fog_warps, entity_lookup)
    print(f"Covered by dest_entity lookup:    {coverage['covered_by_dest']}")
    print(f"Not covered:                      {coverage['not_covered']}")
    print(f"Recoverable via source_entity:    {coverage['recoverable_via_source']} ← POTENTIAL GAIN")
    print(f"Still unresolved:                 {coverage['still_unresolved']}")
    print()

    if coverage['details'] and verbose:
        print("Recoverable entries (zone inferred from reverse direction):")
        for detail in coverage['details'][:10]:
            print(f"  dest_entity {detail['dest_entity']}")
            print(f"    source_entity: {detail['source_entity']} (found in lookup)")
            print(f"    Warp: {detail['warp_source_map']} → {detail['warp_dest_map']}")
            print(f"    Inferred zones: {detail['inferred_source']} → {detail['inferred_destination']}")
        if len(coverage['details']) > 10:
            print(f"  ... and {len(coverage['details']) - 10} more")
        print()

    # Final verdict
    print("=" * 70)
    print("VERDICT")
    print("=" * 70)

    if coverage['not_covered'] > 0:
        recovery_rate = coverage['recoverable_via_source'] / coverage['not_covered'] * 100
    else:
        recovery_rate = 0

    if coverage['recoverable_via_source'] == 0:
        print("❌ source_entity provides NO additional coverage.")
        print("   All uncovered warps remain uncovered.")
    elif coverage['recoverable_via_source'] < 5:
        print(f"⚠️  source_entity provides MARGINAL benefit: {coverage['recoverable_via_source']} warps recoverable.")
        print(f"   Recovery rate: {recovery_rate:.1f}% of uncovered warps.")
    else:
        print(f"✅ source_entity provides SIGNIFICANT benefit: {coverage['recoverable_via_source']} warps recoverable.")
        print(f"   Recovery rate: {recovery_rate:.1f}% of uncovered warps.")
    print()

    # Additional insight: bidirectional pair completeness
    print("=" * 70)
    print("ADDITIONAL INSIGHTS")
    print("=" * 70)

    # Check how many lookup entries have their reverse also in lookup
    pairs_in_lookup = 0
    single_direction_in_lookup = 0

    for entity_id, info in entity_lookup.items():
        # For this entry, find if the reverse direction is also present
        # We need to find an entry where source/dest are swapped
        source = info['source']
        dest = info['destination']

        # Look for reverse
        has_reverse = False
        for other_id, other_info in entity_lookup.items():
            if other_id != entity_id:
                if other_info['source'] == dest and other_info['destination'] == source:
                    has_reverse = True
                    break

        if has_reverse:
            pairs_in_lookup += 1
        else:
            single_direction_in_lookup += 1

    # Divide by 2 since we count each pair twice
    pairs_in_lookup //= 2

    print(f"Lookup entries with reverse also in lookup: {pairs_in_lookup * 2} ({pairs_in_lookup} pairs)")
    print(f"Lookup entries without reverse:             {single_direction_in_lookup}")
    print()
    print("The 'without reverse' entries could benefit from source_entity:")
    print("  - When the mod sends dest_entity for the missing direction,")
    print("    we could use its source_entity to find the known direction")
    print()


if __name__ == "__main__":
    main()
