"""
Zone resolution module.

Resolves (map_id, position) to zone name using game data files:
- submaps.txt: Position-based rules for disambiguating zones within a map
- fog.txt: Internal zone names to display names
- foglocations2.txt: Col-to-zone mappings (fallback)
"""

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ZoneMetadata:
    """Enriched zone information for reverse lookups."""

    internal_name: str
    display_name: str = ""
    map_ids: list[str] = field(default_factory=list)
    cols: list[str] = field(default_factory=list)
    position_bounds: dict[str, float] = field(default_factory=dict)


@dataclass
class PositionRule:
    """A position-based rule for zone resolution."""

    area: str
    name: str = ""
    x_above: float | None = None
    x_below: float | None = None
    y_above: float | None = None
    y_below: float | None = None
    z_above: float | None = None
    z_below: float | None = None

    def matches(self, x: float, y: float, z: float) -> bool:
        """Check if position matches this rule."""
        if self.x_above is not None and x <= self.x_above:
            return False
        if self.x_below is not None and x >= self.x_below:
            return False
        if self.y_above is not None and y <= self.y_above:
            return False
        if self.y_below is not None and y >= self.y_below:
            return False
        if self.z_above is not None and z <= self.z_above:
            return False
        return not (self.z_below is not None and z >= self.z_below)


@dataclass
class MapRules:
    """Position rules for a single map."""

    rules: list[PositionRule] = field(default_factory=list)
    default_area: str | None = None


class ZoneResolver:
    """Resolves map_id + position to zone names."""

    def __init__(self, data_dir: Path | None = None):
        self.data_dir = data_dir
        # map_id -> MapRules
        self.map_rules: dict[str, MapRules] = {}
        # Internal zone name -> display name
        self.zone_display_names: dict[str, str] = {}
        # Display name -> internal zone name (reverse lookup)
        self.display_name_to_zone: dict[str, str] = {}
        # map_id -> set of possible zone names (from foglocations2.txt)
        self.map_zones: dict[str, set[str]] = {}
        # (map_id, col) -> internal zone name (from foglocations2.txt Cols)
        self.col_zones: dict[tuple[str, str], str] = {}
        # Detail text (from ASide/BSide) -> internal zone name (for fallback matching)
        self.detail_text_to_zone: dict[str, str] = {}
        # Grace entity ID -> grace info (from graces.json)
        self.grace_mapping: dict[str, dict] = {}

        # Reverse lookup structures (for test simulation)
        # internal_name -> ZoneMetadata (enriched zone info)
        self.zone_metadata: dict[str, ZoneMetadata] = {}
        # display_name -> list of internal_names (handles duplicates)
        self.display_name_to_zones: dict[str, list[str]] = {}
        # Known positions from fog.txt (ToArea + Location entries)
        # internal_name -> (x, y, z)
        self.zone_known_positions: dict[str, tuple[float, float, float]] = {}
        # Preexisting links from fog.txt To: sections
        # source_zone -> {target_zones}
        self.preexisting_links: dict[str, set[str]] = {}

        if data_dir:
            self._load_data()

    def _load_data(self):
        """Load all data files."""
        if not self.data_dir or not self.data_dir.exists():
            logger.warning("Data directory not found: %s", self.data_dir)
            return

        # Load submaps.txt
        submaps_path = self.data_dir / "submaps.txt"
        if submaps_path.exists():
            self._load_submaps(submaps_path)
            logger.info("Loaded %d map rules from submaps.txt", len(self.map_rules))

        # Load fog.txt
        fog_path = self.data_dir / "fog.txt"
        if fog_path.exists():
            self._load_fog(fog_path)
            # Build reverse lookup (display_name -> zone_key)
            for zone_key, display_name in self.zone_display_names.items():
                self.display_name_to_zone[display_name] = zone_key
            logger.info(
                "Loaded %d zone display names, %d detail texts, %d known positions from fog.txt",
                len(self.zone_display_names),
                len(self.detail_text_to_zone),
                len(self.zone_known_positions),
            )

        # Load foglocations2.txt
        locations_path = self.data_dir / "foglocations2.txt"
        if locations_path.exists():
            self._load_foglocations(locations_path)
            logger.info(
                "Loaded zone data for %d maps from foglocations2.txt",
                len(self.map_zones),
            )

        # Load graces.json
        graces_path = self.data_dir / "graces.json"
        if graces_path.exists():
            self._load_graces(graces_path)
            logger.info(
                "Loaded grace mapping: %d entries",
                len(self.grace_mapping),
            )

    def _load_submaps(self, path: Path):
        """Parse submaps.txt (YAML-like format)."""
        content = path.read_text()
        current_map = None
        current_areas: list[PositionRule] = []

        for line in content.split("\n"):
            line_stripped = line.strip()

            # Skip empty lines and comments
            if not line_stripped or line_stripped.startswith("#"):
                continue

            if line.startswith("- Map: "):
                # Save previous map
                if current_map:
                    self._finalize_map_rules(current_map, current_areas)

                current_map = line_stripped.replace("- Map: ", "").strip()
                current_areas = []
            elif line_stripped.startswith("- Name:"):
                # Start new area entry
                current_areas.append(
                    PositionRule(area="", name=line_stripped.replace("- Name:", "").strip())
                )
            elif line_stripped.startswith("Area:") and current_areas:
                current_areas[-1].area = line_stripped.replace("Area:", "").strip()
            elif line_stripped.startswith("XAbove:") and current_areas:
                current_areas[-1].x_above = float(line_stripped.replace("XAbove:", "").strip())
            elif line_stripped.startswith("XBelow:") and current_areas:
                current_areas[-1].x_below = float(line_stripped.replace("XBelow:", "").strip())
            elif line_stripped.startswith("YAbove:") and current_areas:
                current_areas[-1].y_above = float(line_stripped.replace("YAbove:", "").strip())
            elif line_stripped.startswith("YBelow:") and current_areas:
                current_areas[-1].y_below = float(line_stripped.replace("YBelow:", "").strip())
            elif line_stripped.startswith("ZAbove:") and current_areas:
                current_areas[-1].z_above = float(line_stripped.replace("ZAbove:", "").strip())
            elif line_stripped.startswith("ZBelow:") and current_areas:
                current_areas[-1].z_below = float(line_stripped.replace("ZBelow:", "").strip())

        # Save last map
        if current_map:
            self._finalize_map_rules(current_map, current_areas)

    def _finalize_map_rules(self, map_id: str, areas: list[PositionRule]):
        """Finalize rules for a map, separating conditional and default rules."""
        rules = MapRules()

        for area in areas:
            if not area.area:
                continue  # Skip entries without area

            has_condition = any(
                [
                    area.x_above is not None,
                    area.x_below is not None,
                    area.y_above is not None,
                    area.y_below is not None,
                    area.z_above is not None,
                    area.z_below is not None,
                ]
            )

            if has_condition:
                rules.rules.append(area)
                # Store position bounds in zone_metadata
                if area.area not in self.zone_metadata:
                    self.zone_metadata[area.area] = ZoneMetadata(internal_name=area.area)
                bounds = self.zone_metadata[area.area].position_bounds
                # Only set bounds if not already set (first occurrence wins)
                if area.x_above is not None and "XAbove" not in bounds:
                    bounds["XAbove"] = area.x_above
                if area.x_below is not None and "XBelow" not in bounds:
                    bounds["XBelow"] = area.x_below
                if area.y_above is not None and "YAbove" not in bounds:
                    bounds["YAbove"] = area.y_above
                if area.y_below is not None and "YBelow" not in bounds:
                    bounds["YBelow"] = area.y_below
                if area.z_above is not None and "ZAbove" not in bounds:
                    bounds["ZAbove"] = area.z_above
                if area.z_below is not None and "ZBelow" not in bounds:
                    bounds["ZBelow"] = area.z_below
            else:
                # Last unconditional rule becomes default
                rules.default_area = area.area

        self.map_rules[map_id] = rules

    def _load_fog(self, path: Path):
        """Parse fog.txt for internal name -> display name mapping, Maps, and ASide/BSide texts."""
        content = path.read_text()
        current_name = None
        in_to_section = False
        in_aside = False
        in_bside = False
        aside_area = None
        bside_area = None
        # Track fog gate's map (for ASide/BSide zone candidates)
        foggate_map = None
        # For parsing ToArea + Location entries (known zone positions)
        current_to_area = None

        for line in content.split("\n"):
            line_stripped = line.strip()
            # Track indentation to know if we're in a zone-level or nested section
            indent = len(line) - len(line.lstrip())

            if line_stripped.startswith("- Name:"):
                # Before moving to a new entry, add ASide/BSide areas to map_zones
                # Only for overworld fog gates (m60_/m61_) to underground zones
                if foggate_map and foggate_map.startswith(("m60_", "m61_")):
                    if aside_area and not aside_area.startswith("m"):
                        if foggate_map not in self.map_zones:
                            self.map_zones[foggate_map] = set()
                        self.map_zones[foggate_map].add(aside_area)
                    if bside_area and not bside_area.startswith("m"):
                        if foggate_map not in self.map_zones:
                            self.map_zones[foggate_map] = set()
                        self.map_zones[foggate_map].add(bside_area)

                current_name = line_stripped.replace("- Name:", "").strip()
                # Initialize zone_metadata entry
                if current_name not in self.zone_metadata:
                    self.zone_metadata[current_name] = ZoneMetadata(internal_name=current_name)
                in_to_section = False
                in_aside = False
                in_bside = False
                aside_area = None
                bside_area = None
                foggate_map = None
            elif line_stripped.startswith("To:"):
                in_to_section = True
                in_aside = False
                in_bside = False
            elif line_stripped.startswith("- Area:") and in_to_section and current_name:
                # Parse To: section entries (preexisting connections)
                target_area = line_stripped.replace("- Area:", "").strip()
                if current_name not in self.preexisting_links:
                    self.preexisting_links[current_name] = set()
                self.preexisting_links[current_name].add(target_area)
            elif line_stripped.startswith("ASide:"):
                in_aside = True
                in_bside = False
                aside_area = None
            elif line_stripped.startswith("BSide:"):
                in_bside = True
                in_aside = False
                bside_area = None
            elif line_stripped.startswith("Area:"):
                area = line_stripped.replace("Area:", "").strip()
                if in_aside:
                    aside_area = area
                elif in_bside:
                    bside_area = area
                elif indent <= 2 and not in_to_section:
                    # Fog gate's top-level Area: (the map_id it's in)
                    foggate_map = area
            elif line_stripped.startswith("Text:"):
                text = line_stripped.replace("Text:", "").strip()
                if in_aside and aside_area:
                    # Map this detail text to the zone
                    self.detail_text_to_zone[text] = aside_area
                elif in_bside and bside_area:
                    # Map this detail text to the zone
                    self.detail_text_to_zone[text] = bside_area
                elif (
                    current_name
                    and not in_to_section
                    and not in_aside
                    and not in_bside
                    and indent <= 2
                ):
                    # Zone-level Text: -> display name
                    self.zone_display_names[current_name] = text
                    # Also update zone_metadata
                    if current_name in self.zone_metadata:
                        self.zone_metadata[current_name].display_name = text
            elif line_stripped.startswith("Maps:") and current_name and indent <= 2:
                # Also build zone-to-map mappings from fog.txt
                map_ids = line_stripped.replace("Maps:", "").strip().split()
                for map_id in map_ids:
                    if map_id not in self.map_zones:
                        self.map_zones[map_id] = set()
                    self.map_zones[map_id].add(current_name)
                # Store map_ids in zone_metadata
                if current_name in self.zone_metadata:
                    self.zone_metadata[current_name].map_ids.extend(map_ids)
            elif line_stripped.startswith("ToArea:"):
                # Track ToArea for subsequent Location parsing
                current_to_area = line_stripped.replace("ToArea:", "").strip()
            elif line_stripped.startswith("Location:") and current_to_area:
                # Parse Location: X Y Z [rotation] - extract position for zone
                loc_str = line_stripped.replace("Location:", "").strip()
                parts = loc_str.split()
                if len(parts) >= 3:
                    try:
                        x, y, z = float(parts[0]), float(parts[1]), float(parts[2])
                        # Store as known position for this zone
                        # Only store if we don't have one yet (first occurrence wins)
                        if current_to_area not in self.zone_known_positions:
                            self.zone_known_positions[current_to_area] = (x, y, z)
                    except ValueError:
                        pass
                current_to_area = None  # Reset after parsing
            elif line_stripped.startswith("BossTriggerArea:"):
                # Parse BossTriggerArea: X Y Z ... for boss arena positions
                # Use the current aside_area or bside_area as the zone
                area_for_trigger = aside_area if in_aside else (bside_area if in_bside else None)
                if area_for_trigger:
                    trigger_str = line_stripped.replace("BossTriggerArea:", "").strip()
                    parts = trigger_str.split()
                    if len(parts) >= 3:
                        try:
                            x, y, z = float(parts[0]), float(parts[1]), float(parts[2])
                            if area_for_trigger not in self.zone_known_positions:
                                self.zone_known_positions[area_for_trigger] = (x, y, z)
                        except ValueError:
                            pass
            # Reset ASide/BSide context when we exit their indentation level
            elif indent <= 2 and (in_aside or in_bside):
                in_aside = False
                in_bside = False

        # Handle the last fog gate entry (same logic as above)
        if foggate_map and foggate_map.startswith(("m60_", "m61_")):
            if aside_area and not aside_area.startswith("m"):
                if foggate_map not in self.map_zones:
                    self.map_zones[foggate_map] = set()
                self.map_zones[foggate_map].add(aside_area)
            if bside_area and not bside_area.startswith("m"):
                if foggate_map not in self.map_zones:
                    self.map_zones[foggate_map] = set()
                self.map_zones[foggate_map].add(bside_area)

        # Build display_name_to_zones reverse index
        for internal_name, display_name in self.zone_display_names.items():
            if display_name not in self.display_name_to_zones:
                self.display_name_to_zones[display_name] = []
            self.display_name_to_zones[display_name].append(internal_name)

    def _load_foglocations(self, path: Path):
        """Parse foglocations2.txt for Col -> zone mappings and fog gate AArea."""
        content = path.read_text()
        current_zone = None
        current_fog_map = None

        # Pattern to extract map_id and col from: m10_01_00_00_h001000
        col_pattern = re.compile(r"(m\d+_\d+_\d+_\d+)_(h[0-9a-fA-F]+)")

        for line in content.split("\n"):
            line_stripped = line.strip()

            # Zone definitions (top-level)
            if line_stripped.startswith("- Name:"):
                current_zone = line_stripped.replace("- Name:", "").strip()
                current_fog_map = None  # Reset fog gate context
                # Ensure zone_metadata entry exists
                if current_zone not in self.zone_metadata:
                    self.zone_metadata[current_zone] = ZoneMetadata(internal_name=current_zone)
            elif line_stripped.startswith("Cols:") and current_zone:
                cols = line_stripped.replace("Cols:", "").strip().split()
                for col_entry in cols:
                    match = col_pattern.match(col_entry)
                    if match:
                        map_id = match.group(1)
                        col = match.group(2)
                        # Store in map_zones
                        if map_id not in self.map_zones:
                            self.map_zones[map_id] = set()
                        self.map_zones[map_id].add(current_zone)
                        # Store in col_zones for exact matching
                        self.col_zones[(map_id, col)] = current_zone
                        # Store in zone_metadata
                        if current_zone in self.zone_metadata:
                            meta = self.zone_metadata[current_zone]
                            if col_entry not in meta.cols:
                                meta.cols.append(col_entry)
                            if map_id not in meta.map_ids:
                                meta.map_ids.append(map_id)
            elif line_stripped.startswith("MainMap:") and current_zone:
                # MainMap: provides additional map_ids
                main_maps = line_stripped.replace("MainMap:", "").strip().split()
                if current_zone in self.zone_metadata:
                    for map_id in main_maps:
                        if map_id not in self.zone_metadata[current_zone].map_ids:
                            self.zone_metadata[current_zone].map_ids.append(map_id)
                        # Also add to map_zones for consistency
                        if map_id not in self.map_zones:
                            self.map_zones[map_id] = set()
                        self.map_zones[map_id].add(current_zone)
            # Fog gate definitions (nested under zones)
            elif line_stripped.startswith("- Map:"):
                current_fog_map = line_stripped.replace("- Map:", "").strip()
            elif line_stripped.startswith("AArea:") and current_fog_map:
                # AArea can have multiple zones separated by spaces
                areas = line_stripped.replace("AArea:", "").strip().split()
                if current_fog_map not in self.map_zones:
                    self.map_zones[current_fog_map] = set()
                for area in areas:
                    self.map_zones[current_fog_map].add(area)

    def _load_graces(self, path: Path):
        """Parse graces.json for grace entity ID -> zone mapping."""
        try:
            with open(path) as f:
                data = json.load(f)
                self.grace_mapping = data.get("mapping", {})
        except Exception as e:
            logger.error("Failed to load grace mapping: %s", e)
            self.grace_mapping = {}

    def resolve(self, map_id: str, x: float, y: float, z: float) -> tuple[str | None, str | None]:
        """
        Resolve map_id + position to zone.

        Returns:
            Tuple of (internal_name, display_name). Both may be None if not found.
        """
        internal_name = None

        # Try position-based rules first
        if map_id in self.map_rules:
            rules = self.map_rules[map_id]

            # Check conditional rules in order
            for rule in rules.rules:
                if rule.matches(x, y, z):
                    internal_name = rule.area
                    logger.debug(
                        "Position rule match: %s (%s) for %s at (%.1f, %.1f, %.1f)",
                        internal_name,
                        rule.name,
                        map_id,
                        x,
                        y,
                        z,
                    )
                    break

            # Fall back to default
            if internal_name is None and rules.default_area:
                internal_name = rules.default_area
                logger.debug("Default area: %s for %s", internal_name, map_id)

        # If no position rules, try foglocations fallback
        if internal_name is None and map_id in self.map_zones:
            zones = self.map_zones[map_id]
            if len(zones) == 1:
                internal_name = next(iter(zones))
                logger.debug("Foglocations fallback (unique): %s for %s", internal_name, map_id)
            else:
                # Multiple zones, pick the first non-boss zone as default
                non_boss_zones = [z for z in zones if not z.endswith("_boss")]
                if non_boss_zones:
                    internal_name = sorted(non_boss_zones)[0]
                    logger.info(
                        "Foglocations fallback (ambiguous, picked non-boss): %s for %s from %s",
                        internal_name,
                        map_id,
                        zones,
                    )
                else:
                    internal_name = sorted(zones)[0]
                    logger.info(
                        "Foglocations fallback (ambiguous): %s for %s from %s",
                        internal_name,
                        map_id,
                        zones,
                    )

        # Get display name
        display_name = None
        if internal_name:
            display_name = self.zone_display_names.get(internal_name)
            if not display_name:
                # Fallback: convert internal name to title case
                display_name = internal_name.replace("_", " ").title()

        return internal_name, display_name

    def resolve_from_map_id(self, map_id: str) -> list[tuple[str, str]]:
        """
        Get all possible zones for a map_id (without position disambiguation).

        For "parent" map IDs (m##_##_00_00), also returns zones from child maps
        (m##_##_XX_YY). This handles entity mapping which uses parent format.

        Returns:
            List of (internal_name, display_name) tuples.
        """
        results = []
        seen = set()

        # Check if this is a parent map ID (last two segments are 00_00)
        # Format: m{area}_{grid_x}_{grid_z}_{variant}
        match = re.match(r"(m\d+_\d+)_(\d+)_(\d+)", map_id)
        is_parent_map = match and match.group(2) == "00" and match.group(3) == "00"
        parent_prefix = match.group(1) + "_" if is_parent_map else None

        # Direct match
        if map_id in self.map_zones:
            for internal_name in self.map_zones[map_id]:
                if internal_name not in seen:
                    seen.add(internal_name)
                    display_name = self.zone_display_names.get(
                        internal_name, internal_name.replace("_", " ").title()
                    )
                    results.append((internal_name, display_name))

        # For parent maps, also check child maps
        if parent_prefix:
            for child_map_id, zones in self.map_zones.items():
                # Match child maps: m##_##_XX_YY where XX or YY is not 00
                if child_map_id.startswith(parent_prefix) and child_map_id != map_id:
                    for internal_name in zones:
                        if internal_name not in seen:
                            seen.add(internal_name)
                            display_name = self.zone_display_names.get(
                                internal_name, internal_name.replace("_", " ").title()
                            )
                            results.append((internal_name, display_name))

        return results

    def resolve_by_col(self, map_id: str, col: str) -> tuple[str | None, str | None]:
        """
        Resolve map_id + col to zone (exact match).

        Args:
            map_id: Map ID (e.g., "m10_01_00_00")
            col: Col identifier (e.g., "h001000")

        Returns:
            Tuple of (internal_name, display_name). Both may be None if not found.
        """
        internal_name = self.col_zones.get((map_id, col))
        if internal_name:
            display_name = self.zone_display_names.get(
                internal_name, internal_name.replace("_", " ").title()
            )
            logger.debug(
                "Col match: %s -> %s (%s)",
                col,
                internal_name,
                display_name,
            )
            return internal_name, display_name
        return None, None

    def _get_sibling_map_zones(
        self, map_id: str, exclude_map_ids: set[str] | None = None
    ) -> list[tuple[str, str]]:
        """
        Get zones from sibling maps (same area prefix, different sub-area).

        For a map like m21_01_00_00, returns zones from m21_00_00_00, m21_02_00_00, etc.
        For overworld tiles like m61_44_45_16, returns zones from m61_44_45_00, m61_44_45_10, etc.

        Args:
            map_id: The map ID to find siblings for
            exclude_map_ids: Set of map IDs to exclude (typically the original map)

        Returns:
            List of (internal_name, display_name) tuples from sibling maps.
        """
        if exclude_map_ids is None:
            exclude_map_ids = {map_id}

        results = []
        seen = set()

        # Parse map_id to extract prefix
        # Format: m{area}_{grid_x}_{grid_z}_{variant}
        match = re.match(r"(m\d+)_(\d+)_(\d+)_(\d+)", map_id)
        if not match:
            return results

        area = match.group(1)  # e.g., "m21" or "m61"
        grid_x = match.group(2)
        grid_z = match.group(3)

        # Determine sibling prefix based on map type
        # Overworld tiles (m60_, m61_): siblings share the same tile (m61_44_45_*)
        # Dungeon/legacy maps: siblings share the area (m21_*)
        sibling_prefix = f"{area}_{grid_x}_{grid_z}_" if area in ("m60", "m61") else f"{area}_"

        # Find zones from sibling maps
        for sibling_map_id, zones in self.map_zones.items():
            if sibling_map_id.startswith(sibling_prefix) and sibling_map_id not in exclude_map_ids:
                for internal_name in zones:
                    if internal_name not in seen:
                        seen.add(internal_name)
                        display_name = self.zone_display_names.get(
                            internal_name, internal_name.replace("_", " ").title()
                        )
                        results.append((internal_name, display_name))

        return results

    def resolve_all_candidates(
        self, map_id: str, x: float, y: float, z: float, extend_to_siblings: bool = True
    ) -> list[tuple[str, str]]:
        """
        Get all possible zones for a map_id, ordered by likelihood.

        Position-based rules are used to order candidates (best match first),
        but ALL candidates are returned so the caller can try alternatives.

        Ordering:
        1. Position-matched rules (priority 0)
        2. Default area (priority 1)
        3. Other zones sorted by distance to query position (priority 2)
        4. Boss zones (priority 3)
        Within same priority, sorts by distance to query position if known,
        otherwise alphabetically by internal name for determinism.

        Args:
            map_id: The map ID to resolve
            x, y, z: Player position
            extend_to_siblings: If True and no candidates found, extend search to sibling maps

        Returns:
            List of (internal_name, display_name) tuples, best match first.
        """
        # (internal, display, priority, distance) where distance is used for tie-breaking
        candidates: list[tuple[str, str, int, float]] = []

        def _compute_distance(internal_name: str) -> float:
            """Compute squared distance from query position to zone's known position."""
            known_pos = self.zone_known_positions.get(internal_name)
            if known_pos:
                dx, dy, dz = known_pos[0] - x, known_pos[1] - y, known_pos[2] - z
                return dx * dx + dy * dy + dz * dz
            # No known position - use a large sentinel value
            # This ensures zones with unknown positions sort after those with known positions
            return float("inf")

        # Check position-based rules from submaps.txt
        if map_id in self.map_rules:
            rules = self.map_rules[map_id]

            # Check conditional rules
            for rule in rules.rules:
                display_name = self.zone_display_names.get(
                    rule.area, rule.area.replace("_", " ").title()
                )
                dist = _compute_distance(rule.area)
                if rule.matches(x, y, z):
                    # Position match - highest priority
                    candidates.append((rule.area, display_name, 0, dist))
                else:
                    # Rule exists but position doesn't match - lower priority
                    candidates.append((rule.area, display_name, 2, dist))

            # Add default area
            if rules.default_area:
                display_name = self.zone_display_names.get(
                    rules.default_area, rules.default_area.replace("_", " ").title()
                )
                dist = _compute_distance(rules.default_area)
                candidates.append((rules.default_area, display_name, 1, dist))

        # Add zones from foglocations2.txt
        if map_id in self.map_zones:
            for internal_name in self.map_zones[map_id]:
                # Skip if already added from submaps
                if any(c[0] == internal_name for c in candidates):
                    continue
                display_name = self.zone_display_names.get(
                    internal_name, internal_name.replace("_", " ").title()
                )
                # All foglocations zones get same priority (2)
                # Note: boss zones (_boss suffix) used to be deprioritized (3) but this
                # caused fog gates leading to boss arenas to be excluded from candidates
                # when MAX_ZONE_CANDIDATES was exceeded (issue: Cave of Knowledge - Soldier
                # of Godrick not found because 5 non-boss zones filled the candidate list)
                priority = 2
                dist = _compute_distance(internal_name)
                candidates.append((internal_name, display_name, priority, dist))

        # Sort by (priority, distance, internal_name) for deterministic ordering
        # Distance breaks ties among same-priority zones by proximity to query position
        # Internal name breaks ties among zones with same priority and no known position
        candidates.sort(key=lambda c: (c[2], c[3], c[0]))
        seen = set()
        results = []
        for internal, display, _, _ in candidates:
            if internal not in seen:
                seen.add(internal)
                results.append((internal, display))

        # Fallback: if no candidates found, try sibling maps
        # This handles cases where the mod reports a different tile/sub-area than
        # what's defined in fog.txt (e.g., m61_44_45_16 vs m61_44_45_00)
        # Note: We only extend when there are NO candidates to avoid excessive
        # multi-link discoveries (spoilers). For cases where the map has candidates
        # but the target zone is on a sibling map, the fix should be in fog.txt data.
        if not results and extend_to_siblings:
            sibling_zones = self._get_sibling_map_zones(map_id)
            if sibling_zones:
                logger.info(
                    "No candidates for %s, extended to sibling maps: %d zones found",
                    map_id,
                    len(sibling_zones),
                )
                results = sibling_zones

        return results

    def lookup_by_detail_text(self, detail_text: str) -> tuple[str | None, str | None]:
        """
        Look up zone by ASide/BSide detail text.

        Args:
            detail_text: The detail text (e.g., "inside the Fell Twins' arena")

        Returns:
            Tuple of (internal_name, display_name). Both may be None if not found.
        """
        internal_name = self.detail_text_to_zone.get(detail_text)
        if internal_name:
            display_name = self.zone_display_names.get(
                internal_name, internal_name.replace("_", " ").title()
            )
            return internal_name, display_name
        return None, None

    def lookup_by_display_name(self, display_name: str) -> str | None:
        """
        Look up zone key by display name.

        Args:
            display_name: The display name (e.g., "Leyndell - Erdtree Sanctuary")

        Returns:
            Internal zone key, or None if not found.
        """
        return self.display_name_to_zone.get(display_name)

    def has_preexisting_link(self, source_key: str, target_key: str) -> bool:
        """
        Check if a preexisting link exists from source to target in fog.txt.

        This is used to determine one-way status: if A→B exists but B→A doesn't,
        the link is one-way.

        Args:
            source_key: Internal zone key for source
            target_key: Internal zone key for target

        Returns:
            True if the link exists in the To: section of source_key.
        """
        return target_key in self.preexisting_links.get(source_key, set())

    def lookup_spoiler_name(self, spoiler_name: str) -> tuple[str | None, str | None]:
        """
        Try to resolve a spoiler log zone name to our internal zone.

        Spoiler log names can have parenthetical details like:
        "Divine Tower of East Altus (approaching the Divine Tower of East Altus gate, or using the grace menu)"

        This method:
        1. Extracts the parenthetical text
        2. Looks it up in detail_text_to_zone
        3. Returns the matching zone

        Args:
            spoiler_name: The zone name from the spoiler log

        Returns:
            Tuple of (internal_name, display_name). Both may be None if not found.
        """
        # Extract text between parentheses
        match = re.search(r"\(([^)]+)\)$", spoiler_name)
        if match:
            detail_text = match.group(1)
            return self.lookup_by_detail_text(detail_text)
        return None, None

    # =========================================================================
    # Reverse lookup methods (for test simulation)
    # =========================================================================

    TILE_SIZE = 256.0  # Tile size for overworld maps (m60/m61)

    def estimate_position(
        self, map_id: str, internal_name: str | None = None
    ) -> tuple[float, float, float] | None:
        """
        Estimate approximate x, y, z coordinates for a zone.

        Uses known positions from fog.txt (ToArea + Location) when available,
        otherwise falls back to estimation based on map grid or position bounds.

        Args:
            map_id: The map ID (e.g., "m60_42_32_00")
            internal_name: Optional internal zone name for bounds lookup

        Returns:
            Tuple of (x, y, z) or None if cannot estimate.
        """
        # First, check if we have a known position for this zone from fog.txt
        if internal_name and internal_name in self.zone_known_positions:
            return self.zone_known_positions[internal_name]

        if not map_id:
            return None

        match = re.match(r"m(\d+)_(\d+)_(\d+)_(\d+)", map_id)
        if not match:
            return None

        area_no = int(match.group(1))
        grid_x = int(match.group(2))
        grid_z = int(match.group(3))

        # For overworld maps, use grid-based calculation
        if area_no in (60, 61):
            x = (grid_x - 50) * self.TILE_SIZE
            z = (grid_z - 50) * self.TILE_SIZE
            y = 100.0
            return (x, y, z)

        # For dungeon maps, try to use position bounds
        if internal_name and internal_name in self.zone_metadata:
            bounds = self.zone_metadata[internal_name].position_bounds
            if bounds:
                x = y = z = 0.0

                if "XAbove" in bounds and "XBelow" in bounds:
                    x = (bounds["XAbove"] + bounds["XBelow"]) / 2
                elif "XAbove" in bounds:
                    x = bounds["XAbove"] + 50
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

        return None

    def find_map_ids_for_display_name(
        self, display_name: str, details: str | None = None
    ) -> tuple[list[str], str | None, tuple[float, float, float] | None]:
        """
        Reverse lookup: find map_ids for a zone given its display name.

        This is used for test simulation - given a zone name from the spoiler log,
        find what map_id(s) it corresponds to.

        Args:
            display_name: Zone display name (e.g., "Limgrave")
            details: Optional detail text for disambiguation

        Returns:
            Tuple of:
            - list[str]: map_ids that match this zone
            - str | None: internal zone name (if disambiguated)
            - tuple | None: estimated position (x, y, z)
        """
        # Get all zones matching this display name
        internal_names = self.display_name_to_zones.get(display_name, [])

        if not internal_names:
            # Try extracting base name from parenthetical
            base_match = re.match(r"^(.+?)\s+\([^)]+\)\s*$", display_name)
            if base_match:
                base_name = base_match.group(1).strip()
                internal_names = self.display_name_to_zones.get(base_name, [])
                # Also extract the parenthetical as potential details
                paren_match = re.search(r"\(([^)]+)\)$", display_name)
                if paren_match and not details:
                    details = paren_match.group(1)

        if not internal_names:
            return [], None, None

        # Get zone metadata for each matching zone
        zones = [self.zone_metadata.get(name) for name in internal_names]
        zones = [z for z in zones if z is not None]

        if not zones:
            return [], None, None

        # If only one zone, return it directly
        if len(zones) == 1:
            zone = zones[0]
            map_id = zone.map_ids[0] if zone.map_ids else None
            pos = self.estimate_position(map_id, zone.internal_name)
            return zone.map_ids, zone.internal_name, pos

        # Multiple zones - try to disambiguate using details
        if details:
            details_lower = details.lower()

            # Try to match detail_text_to_zone
            if details in self.detail_text_to_zone:
                internal_name = self.detail_text_to_zone[details]
                if internal_name in self.zone_metadata:
                    zone = self.zone_metadata[internal_name]
                    map_id = zone.map_ids[0] if zone.map_ids else None
                    pos = self.estimate_position(map_id, zone.internal_name)
                    return zone.map_ids, zone.internal_name, pos

            # Try heuristics based on zone internal name patterns
            for zone in zones:
                if "boss" in zone.internal_name and "arena" in details_lower:
                    map_id = zone.map_ids[0] if zone.map_ids else None
                    pos = self.estimate_position(map_id, zone.internal_name)
                    return zone.map_ids, zone.internal_name, pos
                if "postboss" in zone.internal_name and "after" in details_lower:
                    map_id = zone.map_ids[0] if zone.map_ids else None
                    pos = self.estimate_position(map_id, zone.internal_name)
                    return zone.map_ids, zone.internal_name, pos

        # Could not disambiguate - return all map_ids
        all_map_ids: list[str] = []
        for zone in zones:
            for map_id in zone.map_ids:
                if map_id not in all_map_ids:
                    all_map_ids.append(map_id)
        return all_map_ids, None, None

    # =========================================================================
    # Grace entity ID resolution (from graces.json)
    # =========================================================================

    def resolve_zone_by_grace_entity_id(self, grace_entity_id: int | str) -> str | None:
        """Resolve zone display name from grace entity ID.

        Args:
            grace_entity_id: The entity ID of the grace (e.g., 1042362951 for "The First Step")

        Returns:
            Zone display name if found, None otherwise.
        """
        entity_id_str = str(grace_entity_id)
        entry = self.grace_mapping.get(entity_id_str)
        if entry:
            zone = entry.get("zone")
            grace_name = entry.get("grace_name")
            logger.debug(
                "Grace entity %s resolved to zone '%s' (grace: %s)",
                entity_id_str,
                zone,
                grace_name,
            )
            return zone

        logger.debug("Grace entity %s not found in mapping", entity_id_str)
        return None

    def get_grace_info(self, grace_entity_id: int | str) -> dict | None:
        """Get full grace info from entity ID.

        Args:
            grace_entity_id: The entity ID of the grace

        Returns:
            Dict with grace_name, zone, map_id if found, None otherwise.
        """
        return self.grace_mapping.get(str(grace_entity_id))


# Global instance
_resolver: ZoneResolver | None = None


def get_resolver() -> ZoneResolver:
    """Get or create the global zone resolver."""
    global _resolver
    if _resolver is None:
        _resolver = ZoneResolver()
    return _resolver


def init_resolver(data_dir: Path):
    """Initialize the global zone resolver with data directory."""
    global _resolver
    _resolver = ZoneResolver(data_dir)
    return _resolver
