#!/usr/bin/env python3
"""
Test script: reverse lookup from zone_pairs to map_ids.

Given a zone_pairs JSON (from a spoiler log), attempts to find the
corresponding source and target map_ids by matching:
1. Display name -> internal name -> map_id
2. Details text (e.g., "before Grafted Scion's arena") to disambiguate fog gates
"""

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FogGate:
    """A fog gate (connection) from one zone to another."""

    source_internal: str
    target_internal: str
    description: str  # e.g., "before Grafted Scion's arena"


@dataclass
class ZoneInfo:
    """Information about a zone from fog.txt."""

    internal_name: str
    display_name: str
    map_ids: list[str] = field(default_factory=list)
    fog_gates: list[FogGate] = field(default_factory=list)
    cols: list[str] = field(default_factory=list)  # Col IDs from foglocations2.txt
    position_bounds: dict = field(default_factory=dict)  # From submaps.txt


class FogDataIndex:
    """Index for reverse-looking up zone info from display names and descriptions."""

    # Tile size for overworld maps (m60/m61)
    TILE_SIZE = 256.0

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        # display_name -> list of ZoneInfo (multiple zones can have same display name)
        self.by_display_name: dict[str, list[ZoneInfo]] = {}
        # internal_name -> ZoneInfo
        self.by_internal_name: dict[str, ZoneInfo] = {}
        # (internal_name, normalized_description) -> target_internal_name
        self.fog_gates_by_desc: dict[tuple[str, str], str] = {}

        self._load_fog_txt()
        self._load_foglocations()
        self._load_submaps()

    def _normalize_desc(self, text: str) -> str:
        """Normalize description for matching."""
        # Lowercase, remove extra whitespace
        text = text.lower().strip()
        # Remove common prefixes/variations
        text = re.sub(r"^(at the |in the |on the |before |after |using |from )", "", text)
        return text

    def _load_fog_txt(self):
        """Parse fog.txt to build zone index."""
        fog_path = self.data_dir / "fog.txt"
        if not fog_path.exists():
            print(f"Warning: {fog_path} not found")
            return

        content = fog_path.read_text()
        current_zone: ZoneInfo | None = None
        current_fog_target: str | None = None
        in_to_section = False
        in_fog_gate = False  # True when we just saw "- Area:"

        for line in content.split("\n"):
            line_stripped = line.strip()

            # New zone entry (top-level)
            if line.startswith("- Name: "):
                # Save previous zone
                if current_zone:
                    self._register_zone(current_zone)

                internal_name = line_stripped.replace("- Name: ", "").strip()
                current_zone = ZoneInfo(internal_name=internal_name, display_name="")
                in_to_section = False
                in_fog_gate = False
                current_fog_target = None

            elif current_zone:
                # Zone-level properties (indented with 2 spaces, not 4)
                indent = len(line) - len(line.lstrip())

                # Display name (zone level, indent = 2)
                if line_stripped.startswith("Text: ") and indent == 2 and not in_to_section:
                    current_zone.display_name = line_stripped.replace("Text: ", "").strip()

                # Map IDs
                elif line_stripped.startswith("Maps: "):
                    map_ids = line_stripped.replace("Maps: ", "").strip().split()
                    current_zone.map_ids.extend(map_ids)

                # Start of To: section
                elif line_stripped == "To:":
                    in_to_section = True
                    in_fog_gate = False

                # Fog gate entry in To: section
                elif in_to_section and line_stripped.startswith("- Area: "):
                    current_fog_target = line_stripped.replace("- Area: ", "").strip()
                    in_fog_gate = True

                # Description of fog gate (inside a fog gate entry)
                elif in_to_section and in_fog_gate and line_stripped.startswith("Text: "):
                    desc = line_stripped.replace("Text: ", "").strip()
                    fog_gate = FogGate(
                        source_internal=current_zone.internal_name,
                        target_internal=current_fog_target,
                        description=desc,
                    )
                    current_zone.fog_gates.append(fog_gate)

                    # Index by normalized description
                    norm_desc = self._normalize_desc(desc)
                    self.fog_gates_by_desc[(current_zone.internal_name, norm_desc)] = (
                        current_fog_target
                    )

                # End of To: section (new top-level section)
                elif in_to_section and indent == 2 and not line_stripped.startswith("- "):
                    in_to_section = False
                    in_fog_gate = False

        # Save last zone
        if current_zone:
            self._register_zone(current_zone)

    def _register_zone(self, zone: ZoneInfo):
        """Register a zone in the indexes."""
        self.by_internal_name[zone.internal_name] = zone

        if zone.display_name:
            if zone.display_name not in self.by_display_name:
                self.by_display_name[zone.display_name] = []
            self.by_display_name[zone.display_name].append(zone)

    def _load_foglocations(self):
        """Parse foglocations2.txt to add Cols (more precise map_id info)."""
        loc_path = self.data_dir / "foglocations2.txt"
        if not loc_path.exists():
            print(f"Warning: {loc_path} not found")
            return

        content = loc_path.read_text()
        current_name = None

        for line in content.split("\n"):
            line_stripped = line.strip()

            if line.startswith("- Name: "):
                current_name = line_stripped.replace("- Name: ", "").strip()

            elif line_stripped.startswith("Cols: ") and current_name:
                cols = line_stripped.replace("Cols: ", "").strip().split()
                zone = self.by_internal_name.get(current_name)
                if zone:
                    zone.cols.extend(cols)
                    # Extract map_ids from cols (format: m10_01_00_00_h001000)
                    for col in cols:
                        match = re.match(r"(m\d+_\d+_\d+_\d+)_h\d+", col)
                        if match:
                            map_id = match.group(1)
                            if map_id not in zone.map_ids:
                                zone.map_ids.append(map_id)

            elif line_stripped.startswith("MainMap: ") and current_name:
                main_maps = line_stripped.replace("MainMap: ", "").strip().split()
                zone = self.by_internal_name.get(current_name)
                if zone:
                    for map_id in main_maps:
                        if map_id not in zone.map_ids:
                            zone.map_ids.append(map_id)

    def _load_submaps(self):
        """Parse submaps.txt to add position bounds."""
        submaps_path = self.data_dir / "submaps.txt"
        if not submaps_path.exists():
            print(f"Warning: {submaps_path} not found")
            return

        content = submaps_path.read_text()
        current_map = None
        current_area = None
        current_bounds = {}

        for line in content.split("\n"):
            line_stripped = line.strip()

            if line.startswith("- Map: "):
                current_map = line_stripped.replace("- Map: ", "").strip()

            elif line_stripped.startswith("- Name: "):
                # Save previous area's bounds
                if current_area and current_bounds:
                    zone = self.by_internal_name.get(current_area)
                    if zone:
                        zone.position_bounds = current_bounds.copy()

                current_bounds = {}

            elif line_stripped.startswith("Area: "):
                current_area = line_stripped.replace("Area: ", "").strip()

            elif current_area:
                for bound_type in ["XAbove", "XBelow", "YAbove", "YBelow", "ZAbove", "ZBelow"]:
                    if line_stripped.startswith(f"{bound_type}: "):
                        value = float(line_stripped.replace(f"{bound_type}: ", "").strip())
                        current_bounds[bound_type] = value

        # Save last area
        if current_area and current_bounds:
            zone = self.by_internal_name.get(current_area)
            if zone:
                zone.position_bounds = current_bounds.copy()

    def estimate_position(
        self, map_id: str, zone: ZoneInfo | None = None
    ) -> tuple[float, float, float] | None:
        """
        Estimate approximate x, y, z coordinates for a zone.

        For overworld (m60/m61): calculate from map_id grid position
        For dungeons: use position bounds from submaps.txt if available

        Returns (x, y, z) or None if cannot estimate.
        """
        if not map_id:
            return None

        # Parse map_id: mAA_XX_YY_DD
        match = re.match(r"m(\d+)_(\d+)_(\d+)_(\d+)", map_id)
        if not match:
            return None

        area_no = int(match.group(1))
        grid_x = int(match.group(2))
        grid_z = int(match.group(3))

        # Overworld maps (m60, m61) - calculate from grid position
        if area_no in (60, 61):
            # Grid position to world coordinates
            # Each tile is TILE_SIZE units, centered at grid intersection
            x = (grid_x - 50) * self.TILE_SIZE  # Approximate center reference
            z = (grid_z - 50) * self.TILE_SIZE
            y = 100.0  # Default elevation (varies greatly in practice)

            # If we have a Col, use it for more precision
            if zone and zone.cols:
                for col in zone.cols:
                    if col.startswith(map_id):
                        # Extract h-code: m60_42_36_00_h423600 -> 423600
                        col_match = re.match(r"m\d+_\d+_\d+_\d+_h(\d{6})", col)
                        if col_match:
                            # Col format for overworld: hXXYY00 where XX=grid_x, YY=grid_z
                            # This gives us confirmation but not more precision
                            pass

            return (x, y, z)

        # Dungeon maps - use position bounds if available
        if zone and zone.position_bounds:
            bounds = zone.position_bounds
            x = y = z = 0.0

            # Calculate center from bounds
            if "XAbove" in bounds and "XBelow" in bounds:
                x = (bounds["XAbove"] + bounds["XBelow"]) / 2
            elif "XAbove" in bounds:
                x = bounds["XAbove"] + 50  # Offset above the threshold
            elif "XBelow" in bounds:
                x = bounds["XBelow"] - 50

            if "YAbove" in bounds and "YBelow" in bounds:
                y = (bounds["YAbove"] + bounds["YBelow"]) / 2
            elif "YAbove" in bounds:
                y = bounds["YAbove"] + 50
            elif "YBelow" in bounds:
                y = bounds["YBelow"] - 50

            if "ZAbove" in bounds and "ZBelow" in bounds:
                z = (bounds["ZAbove"] + bounds["ZBelow"]) / 2
            elif "ZAbove" in bounds:
                z = bounds["ZAbove"] + 50
            elif "ZBelow" in bounds:
                z = bounds["ZBelow"] - 50

            return (x, y, z)

        # No position info available for dungeon
        return None

    def find_zone_by_display_name(self, display_name: str) -> list[ZoneInfo]:
        """Find zones by display name."""
        return self.by_display_name.get(display_name, [])

    def _extract_base_name(self, display_name: str) -> tuple[str, str | None]:
        """
        Extract base zone name and optional extra context.

        Some spoiler log entries have format: "Zone Name (extra context)"
        Returns (base_name, extra_context)
        """
        # Check for parenthetical context at the end
        match = re.match(r"^(.+?)\s+\(([^)]+)\)\s*$", display_name)
        if match:
            return match.group(1).strip(), match.group(2).strip()
        return display_name, None

    def find_map_ids(
        self, display_name: str, details: str | None = None
    ) -> tuple[list[str], str | None, tuple[float, float, float] | None]:
        """
        Find map_ids for a zone given its display name and optional details.

        Returns:
            Tuple of (map_ids, matched_internal_name, estimated_position)
        """
        # First try exact match
        zones = self.find_zone_by_display_name(display_name)

        # If no match, try stripping parenthetical context
        if not zones:
            base_name, extra_context = self._extract_base_name(display_name)
            if base_name != display_name:
                zones = self.find_zone_by_display_name(base_name)
                # Use extra_context as additional detail info
                if extra_context and not details:
                    details = extra_context

        if not zones:
            return [], None, None

        # If only one zone matches, return it
        if len(zones) == 1:
            zone = zones[0]
            map_id = zone.map_ids[0] if zone.map_ids else None
            pos = self.estimate_position(map_id, zone)
            return zone.map_ids, zone.internal_name, pos

        # Multiple zones match - try to disambiguate using details
        if details:
            norm_details = self._normalize_desc(details)

            # Try to find a fog gate with matching description
            for zone in zones:
                for fg in zone.fog_gates:
                    norm_fg_desc = self._normalize_desc(fg.description)
                    # Check if details match (partial match)
                    if norm_details in norm_fg_desc or norm_fg_desc in norm_details:
                        map_id = zone.map_ids[0] if zone.map_ids else None
                        pos = self.estimate_position(map_id, zone)
                        return zone.map_ids, zone.internal_name, pos

            # Try matching on keywords in details
            details_lower = details.lower()
            for zone in zones:
                # Check zone internal name patterns
                if "boss" in zone.internal_name and "arena" in details_lower:
                    map_id = zone.map_ids[0] if zone.map_ids else None
                    pos = self.estimate_position(map_id, zone)
                    return zone.map_ids, zone.internal_name, pos
                if "postboss" in zone.internal_name and "after" in details_lower:
                    map_id = zone.map_ids[0] if zone.map_ids else None
                    pos = self.estimate_position(map_id, zone)
                    return zone.map_ids, zone.internal_name, pos

        # Could not disambiguate - return all map_ids from all matching zones
        all_map_ids = []
        for zone in zones:
            all_map_ids.extend(zone.map_ids)
        return list(set(all_map_ids)), None, None


def test_zone_mapping(json_path: Path, data_dir: Path):
    """Test reverse mapping from zone_pairs to map_ids."""
    print(f"Loading zone_pairs from: {json_path}")
    print(f"Using data from: {data_dir}")
    print()

    # Load zone_pairs
    with open(json_path) as f:
        zone_pairs = json.load(f)

    # Build index
    index = FogDataIndex(data_dir)
    print(f"Loaded {len(index.by_display_name)} display names")
    print(f"Loaded {len(index.by_internal_name)} internal names")
    print(f"Loaded {len(index.fog_gates_by_desc)} fog gate descriptions")
    print()

    # Test each zone_pair
    stats = {"found": 0, "partial": 0, "not_found": 0, "ambiguous": 0, "with_pos": 0}

    for pair in zone_pairs:
        source = pair["source"]
        target = pair["destination"]
        source_details = pair.get("source_details")
        target_details = pair.get("target_details")
        pair_type = pair["type"]

        # Find source map_ids and position
        source_map_ids, source_internal, source_pos = index.find_map_ids(source, source_details)

        # Find target map_ids and position
        target_map_ids, target_internal, target_pos = index.find_map_ids(target, target_details)

        # Count positions found
        if source_pos and target_pos:
            stats["with_pos"] += 1

        # Determine status
        if source_map_ids and target_map_ids:
            if source_internal and target_internal:
                status = "✓"
                stats["found"] += 1
            else:
                status = "~"  # Found but ambiguous
                stats["ambiguous"] += 1
        elif source_map_ids or target_map_ids:
            status = "?"
            stats["partial"] += 1
        else:
            status = "✗"
            stats["not_found"] += 1

        # Print result
        source_map_str = source_map_ids[0] if len(source_map_ids) == 1 else f"{source_map_ids}"
        target_map_str = target_map_ids[0] if len(target_map_ids) == 1 else f"{target_map_ids}"

        verbose = "--verbose" in sys.argv or "-v" in sys.argv
        show_all = "--all" in sys.argv or "-a" in sys.argv
        show_pos = "--pos" in sys.argv or "-p" in sys.argv

        if status != "✓" or verbose or show_all:
            print(f"[{status}] {pair_type}: {source} → {target}")
            print(f"    Source: {source_map_str} ({source_internal or '?'})")
            if source_pos and show_pos:
                print(f"            pos: ({source_pos[0]:.1f}, {source_pos[1]:.1f}, {source_pos[2]:.1f})")
            if source_details:
                print(f"            details: \"{source_details}\"")
            print(f"    Target: {target_map_str} ({target_internal or '?'})")
            if target_pos and show_pos:
                print(f"            pos: ({target_pos[0]:.1f}, {target_pos[1]:.1f}, {target_pos[2]:.1f})")
            if target_details:
                print(f"            details: \"{target_details}\"")
            print()

    # Print summary
    print("=" * 60)
    print("Summary:")
    print(f"  Found (exact):    {stats['found']}")
    print(f"  Found (ambiguous):{stats['ambiguous']}")
    print(f"  Partial:          {stats['partial']}")
    print(f"  Not found:        {stats['not_found']}")
    print(f"  Total:            {len(zone_pairs)}")

    success_rate = (stats["found"] + stats["ambiguous"]) / len(zone_pairs) * 100
    print(f"  Success rate:     {success_rate:.1f}%")

    pos_rate = stats["with_pos"] / len(zone_pairs) * 100
    print(f"  With positions:   {stats['with_pos']} ({pos_rate:.1f}%)")


def main():
    # Help message
    if "--help" in sys.argv or "-h" in sys.argv:
        print("Usage: test_zone_mapping.py [zone_pairs.json] [options]")
        print()
        print("Options:")
        print("  -v, --verbose    Show all results (not just errors)")
        print("  -a, --all        Same as --verbose")
        print("  -p, --pos        Show estimated positions")
        print("  -h, --help       Show this help")
        print()
        print("Tests reverse lookup: zone display names → map_ids")
        print()
        print("Position estimation:")
        print("  - Overworld (m60/m61): Calculated from grid coordinates")
        print("  - Dungeons: Estimated from submaps.txt bounds (if available)")
        sys.exit(0)

    # Default paths
    script_dir = Path(__file__).parent
    project_root = script_dir.parent

    # JSON file (first argument or default)
    json_path = None
    for arg in sys.argv[1:]:
        if not arg.startswith("-"):
            json_path = Path(arg)
            break

    if json_path is None:
        json_path = script_dir / "391139473.json"

    # Data directory
    data_dir = project_root / "server" / "data"

    if not json_path.exists():
        print(f"Error: JSON file not found: {json_path}")
        sys.exit(1)

    if not data_dir.exists():
        print(f"Error: Data directory not found: {data_dir}")
        sys.exit(1)

    test_zone_mapping(json_path, data_dir)


if __name__ == "__main__":
    main()
