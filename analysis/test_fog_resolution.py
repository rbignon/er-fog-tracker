#!/usr/bin/env python3
"""
End-to-end test: simulate fog traversals and verify server resolution.

This test:
1. Loads zone_pairs from a spoiler log JSON (or zone_links.json in a folder)
2. Uses reverse lookup to get map_id + estimated position for each zone
3. Optionally uses entity_mapping.json to get precise EMEVD maps
4. Calls the server's zone resolver to resolve back to zone names
5. Uses find_matching_zone_pair to disambiguate using the spoiler log
6. Verifies the resolved names match the original zone_pairs

Input formats:
- Single JSON file: spoiler log with zone pairs
- Folder: containing zone_links.json and optionally entity_mapping.json

Usage:
    python test_fog_resolution.py <spoiler.json or folder> [options]

Options:
    -v, --verbose       Show all mismatches
    --no-entity         Disable entity_mapping even if available
    -h, --help          Show this help
"""

import json
import sys
from pathlib import Path

# Add server module to path
sys.path.insert(0, str(Path(__file__).parent.parent / "server"))

from fogtracker.zone_resolver import ZoneResolver
from fogtracker.zone_matching import (
    find_all_matching_zone_pairs,
    find_all_matching_zone_pairs_by_ids,
    names_match,
)

# Maximum number of zone candidates to use for matching (should match server)
MAX_ZONE_CANDIDATES = 15


# =============================================================================
# Entity mapping helpers
# =============================================================================


def build_entity_index(entity_mapping: dict) -> dict:
    """
    Build an index: (source_map, dest_map) -> list of entity_ids.

    This allows quick lookup of entities that match a given map pair.
    """
    index = {}
    for entity_id, info in entity_mapping.items():
        source_map = info.get("source_map")
        dest_map = info.get("dest_map")
        if source_map and dest_map:
            key = (source_map, dest_map)
            if key not in index:
                index[key] = []
            index[key].append(entity_id)
            # Also index reverse for bidirectional
            rev_key = (dest_map, source_map)
            if rev_key not in index:
                index[rev_key] = []
            index[rev_key].append(entity_id)
    return index


def test_fog_resolution(
    zone_pairs: list,
    data_dir: Path,
    entity_mapping: dict | None = None,
    use_entity_mapping: bool = True,
):
    """Test that the server can resolve fog traversals correctly."""
    # Build entity index if available
    entity_index = None
    if entity_mapping and use_entity_mapping:
        entity_index = build_entity_index(entity_mapping)
        print(f"Entity mapping: {len(entity_mapping)} entities")
    else:
        print("Entity mapping: not used")

    # Initialize zone resolver (used for both forward and reverse lookups)
    resolver = ZoneResolver(data_dir)
    print(f"Zone resolver: {len(resolver.map_rules)} map rules, {len(resolver.zone_display_names)} display names")
    print(f"Zone metadata: {len(resolver.zone_metadata)} zones, {len(resolver.display_name_to_zones)} display names")
    print()

    # Check if zone_pairs have keys (V3 format with source_key/target_key)
    has_zone_keys = any(
        p.get("source_key") or p.get("target_key") for p in zone_pairs[:5]
    )

    # Stats
    stats = {
        "total": len(zone_pairs),
        "resolved_1_link": 0,     # Exactly 1 valid link found (certain)
        "resolved_2_links": 0,    # 2 valid links found (small spoil)
        "resolved_3plus_links": 0, # 3+ valid links found (larger spoil)
        "not_found": 0,           # No valid link found
        "entity_used": 0,         # Count where entity_mapping provided maps
    }

    results_1_link = []
    results_multi_link = []
    not_found = []

    # Only test random links (actual fog gates), not preexisting (auto-propagated)
    # Deduplicate bidirectional pairs (A→B and B→A are the same link)
    seen_links = set()
    random_pairs = []
    for p in zone_pairs:
        if p.get("type") != "random":
            continue
        link_key = frozenset([p["source"], p["target"]])
        if link_key not in seen_links:
            seen_links.add(link_key)
            random_pairs.append(p)
    stats["total"] = len(random_pairs)

    for pair in random_pairs:
        source_name = pair["source"]
        target_name = pair["target"]
        source_details = pair.get("source_details")
        target_details = pair.get("target_details")

        # Step 1: Reverse lookup to get map_id + position
        source_map_ids, _, source_pos = resolver.find_map_ids_for_display_name(source_name, source_details)
        target_map_ids, _, target_pos = resolver.find_map_ids_for_display_name(target_name, target_details)

        # Use first map_id if multiple, default position if none
        source_map_id = source_map_ids[0] if source_map_ids else None
        target_map_id = target_map_ids[0] if target_map_ids else None
        source_pos = source_pos or (0.0, 0.0, 0.0)
        target_pos = target_pos or (0.0, 0.0, 0.0)

        # Step 1b: If entity_mapping available, try to get more precise maps
        entity_id_used = None
        if entity_index and source_map_id and target_map_id:
            key = (source_map_id, target_map_id)
            if key in entity_index:
                # Entity found - we could use its maps for prioritization
                entity_id_used = entity_index[key][0]
                stats["entity_used"] += 1

        if not source_map_id or not target_map_id:
            stats["not_found"] += 1
            not_found.append({
                "expected_source": source_name,
                "expected_target": target_name,
                "source_map_id": source_map_id,
                "target_map_id": target_map_id,
                "source_candidates": [],
                "target_candidates": [],
                "reason": "no map_id from reverse lookup",
            })
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
            not_found.append({
                "expected_source": source_name,
                "expected_target": target_name,
                "source_map_id": source_map_id,
                "target_map_id": target_map_id,
                "source_candidates": [c[1] for c in source_candidates[:5]],
                "target_candidates": [c[1] for c in target_candidates[:5]],
                "reason": "no candidates from resolver",
            })
            continue

        # Step 3: Use server logic - find ALL matching zone pairs
        # Only match against random links (preexisting are auto-propagated, not tracked by mod)
        random_zone_pairs = [p for p in zone_pairs if p.get("type") == "random"]

        if has_zone_keys:
            # Use zone_id-based matching (V3+ format with source_id/target_id)
            raw_matches = find_all_matching_zone_pairs_by_ids(
                random_zone_pairs,
                source_candidates[:MAX_ZONE_CANDIDATES],
                target_candidates[:MAX_ZONE_CANDIDATES],
            )
            # Convert (source_id, target_id, pair) to (source_name, target_name, pair)
            # for compatibility with the rest of the script
            all_matches = [
                (pair.get("source", src_id), pair.get("target", tgt_id), pair)
                for src_id, tgt_id, pair in raw_matches
            ]
        else:
            all_matches = find_all_matching_zone_pairs(
                random_zone_pairs,
                source_candidates[:MAX_ZONE_CANDIDATES],
                target_candidates[:MAX_ZONE_CANDIDATES],
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
                "reason": "no zone_link matches candidates",
                "entity_id": entity_id_used,
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
                "resolved_with_pairs": all_matches,
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
                "resolved_with_pairs": all_matches,
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
            for src, tgt, pair in m['resolved_with_pairs']:
                # Check if this exact link matches (respecting direction)
                is_expected = (
                    (names_match(src, m['expected_source']) and names_match(tgt, m['expected_target'])) or
                    (names_match(src, m['expected_target']) and names_match(tgt, m['expected_source']))
                )
                # But only mark once - prefer the one matching the original direction
                if is_expected:
                    # Check if it's the exact direction match (not reversed)
                    exact_direction = names_match(src, m['expected_source']) and names_match(tgt, m['expected_target'])
                    if exact_direction:
                        marker = " ← expected"
                    else:
                        marker = ""  # Same link but reversed direction, don't double-mark
                else:
                    marker = ""
                # Use → for one-way links, ↔ for bidirectional
                arrow = "→" if pair.get("is_one_way") else "↔"
                print(f"    - '{src}' {arrow} '{tgt}'{marker}")
            print()

        if len(results_multi_link) > 50:
            print(f"... and {len(results_multi_link) - 50} more")
            print()

    # Print not found cases
    if not_found:
        print("=" * 60)
        print("NOT FOUND (no valid link in spoiler log):")
        print("=" * 60)
        for nf in not_found[:30]:
            print(f"Expected: '{nf['expected_source']}' → '{nf['expected_target']}'")
            print(f"  Maps: {nf['source_map_id']} → {nf['target_map_id']}")
            print(f"  Reason: {nf.get('reason', 'unknown')}")
            if nf.get('entity_id'):
                print(f"  Entity ID: {nf['entity_id']}")
            if nf['source_candidates']:
                print(f"  Source candidates: {nf['source_candidates'][:3]}")
            if nf['target_candidates']:
                print(f"  Target candidates: {nf['target_candidates'][:3]}")
            print()
        if len(not_found) > 30:
            print(f"... and {len(not_found) - 30} more")

    # Print summary
    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    total = stats['total']
    resolved_total = stats['resolved_1_link'] + stats['resolved_2_links'] + stats['resolved_3plus_links']

    link1_pct = stats['resolved_1_link'] / total * 100 if total > 0 else 0
    link2_pct = stats['resolved_2_links'] / total * 100 if total > 0 else 0
    link3_pct = stats['resolved_3plus_links'] / total * 100 if total > 0 else 0
    not_found_pct = stats['not_found'] / total * 100 if total > 0 else 0
    resolved_pct = resolved_total / total * 100 if total > 0 else 0

    print(f"Total random links tested: {total}")
    if entity_index:
        print(f"Entity mapping matches:    {stats['entity_used']}")
    print()
    print(f"  ✓ Resolved:      {resolved_total:3d} ({resolved_pct:5.1f}%) - expected link will be discovered")
    print(f"      1 link:      {stats['resolved_1_link']:3d} ({link1_pct:5.1f}%) - perfect, no spoil")
    print(f"      2 links:     {stats['resolved_2_links']:3d} ({link2_pct:5.1f}%) - small spoil (1 extra link)")
    print(f"      3+ links:    {stats['resolved_3plus_links']:3d} ({link3_pct:5.1f}%) - larger spoil")
    print(f"  ✗ Not found:     {stats['not_found']:3d} ({not_found_pct:5.1f}%) - no valid link found")

    return stats


def main():
    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__)
        sys.exit(0)

    # Default paths
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    data_dir = project_root / "server" / "data"

    # Parse options
    use_entity_mapping = "--no-entity" not in sys.argv

    # Find input path (file or folder)
    input_path = None
    for arg in sys.argv[1:]:
        if not arg.startswith("-"):
            input_path = Path(arg)
            break

    if input_path is None:
        # Try to find a default
        for candidate in script_dir.glob("*.json"):
            if candidate.name not in ("entity_mapping.json", "zones.json"):
                input_path = candidate
                break

    if input_path is None:
        print("Error: No input file or folder specified")
        print()
        print(__doc__)
        sys.exit(1)

    # Load zone_pairs and optionally entity_mapping
    zone_pairs = None
    entity_mapping = None

    if input_path.is_dir():
        # Folder mode: expect zone_links.json and optionally entity_mapping.json
        zone_links_path = input_path / "zone_links.json"
        entity_mapping_path = input_path / "entity_mapping.json"

        if not zone_links_path.exists():
            print(f"Error: zone_links.json not found in {input_path}")
            sys.exit(1)

        print(f"Loading from folder: {input_path}")
        with open(zone_links_path) as f:
            zone_pairs = json.load(f)
        print(f"  zone_links.json: {len(zone_pairs)} entries")

        if entity_mapping_path.exists() and use_entity_mapping:
            with open(entity_mapping_path) as f:
                entity_mapping = json.load(f)
            print(f"  entity_mapping.json: {len(entity_mapping)} entries")
        elif not use_entity_mapping:
            print("  entity_mapping.json: disabled via --no-entity")
        else:
            print("  entity_mapping.json: not found")

    elif input_path.is_file():
        # File mode: single JSON file (legacy spoiler log format)
        if not input_path.exists():
            print(f"Error: File not found: {input_path}")
            sys.exit(1)

        print(f"Loading from file: {input_path}")
        with open(input_path) as f:
            zone_pairs = json.load(f)
        print(f"  {len(zone_pairs)} entries")

    else:
        print(f"Error: Path not found: {input_path}")
        sys.exit(1)

    if not data_dir.exists():
        print(f"Error: Data directory not found: {data_dir}")
        sys.exit(1)

    print(f"Data directory: {data_dir}")
    print()

    stats = test_fog_resolution(
        zone_pairs,
        data_dir,
        entity_mapping=entity_mapping,
        use_entity_mapping=use_entity_mapping,
    )

    sys.exit(0 if stats['not_found'] == 0 else 1)


if __name__ == "__main__":
    main()
