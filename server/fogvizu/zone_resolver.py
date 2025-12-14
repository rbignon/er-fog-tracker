"""
Zone resolution module.

Resolves (map_id, position) to zone name using game data files:
- submaps.txt: Position-based rules for disambiguating zones within a map
- fog.txt: Internal zone names to display names
- foglocations2.txt: Col-to-zone mappings (fallback)
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


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
        # map_id -> set of possible zone names (from foglocations2.txt)
        self.map_zones: dict[str, set[str]] = {}

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
            logger.info(
                "Loaded %d zone display names from fog.txt",
                len(self.zone_display_names),
            )

        # Load foglocations2.txt
        locations_path = self.data_dir / "foglocations2.txt"
        if locations_path.exists():
            self._load_foglocations(locations_path)
            logger.info(
                "Loaded zone data for %d maps from foglocations2.txt",
                len(self.map_zones),
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
            else:
                # Last unconditional rule becomes default
                rules.default_area = area.area

        self.map_rules[map_id] = rules

    def _load_fog(self, path: Path):
        """Parse fog.txt for internal name -> display name mapping."""
        content = path.read_text()
        current_name = None

        for line in content.split("\n"):
            line_stripped = line.strip()

            if line_stripped.startswith("- Name:"):
                current_name = line_stripped.replace("- Name:", "").strip()
            elif line_stripped.startswith("Text:") and current_name:
                display_name = line_stripped.replace("Text:", "").strip()
                self.zone_display_names[current_name] = display_name
                current_name = None

    def _load_foglocations(self, path: Path):
        """Parse foglocations2.txt for Col -> zone mappings."""
        content = path.read_text()
        current_zone = None

        # Pattern to extract map_id from Col: m10_01_00_00_h001000
        col_pattern = re.compile(r"(m\d+_\d+_\d+_\d+)_h\d+")

        for line in content.split("\n"):
            line_stripped = line.strip()

            if line_stripped.startswith("- Name:"):
                current_zone = line_stripped.replace("- Name:", "").strip()
            elif line_stripped.startswith("Cols:") and current_zone:
                cols = line_stripped.replace("Cols:", "").strip().split()
                for col in cols:
                    match = col_pattern.match(col)
                    if match:
                        map_id = match.group(1)
                        if map_id not in self.map_zones:
                            self.map_zones[map_id] = set()
                        self.map_zones[map_id].add(current_zone)

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

        Returns:
            List of (internal_name, display_name) tuples.
        """
        results = []

        # From foglocations
        if map_id in self.map_zones:
            for internal_name in self.map_zones[map_id]:
                display_name = self.zone_display_names.get(
                    internal_name, internal_name.replace("_", " ").title()
                )
                results.append((internal_name, display_name))

        return results

    def resolve_all_candidates(
        self, map_id: str, x: float, y: float, z: float
    ) -> list[tuple[str, str]]:
        """
        Get all possible zones for a map_id, ordered by likelihood.

        Position-based rules are used to order candidates (best match first),
        but ALL candidates are returned so the caller can try alternatives.

        Returns:
            List of (internal_name, display_name) tuples, best match first.
        """
        candidates: list[tuple[str, str, int]] = []  # (internal, display, priority)

        # Check position-based rules from submaps.txt
        if map_id in self.map_rules:
            rules = self.map_rules[map_id]

            # Check conditional rules
            for rule in rules.rules:
                display_name = self.zone_display_names.get(
                    rule.area, rule.area.replace("_", " ").title()
                )
                if rule.matches(x, y, z):
                    # Position match - highest priority
                    candidates.append((rule.area, display_name, 0))
                else:
                    # Rule exists but position doesn't match - lower priority
                    candidates.append((rule.area, display_name, 2))

            # Add default area
            if rules.default_area:
                display_name = self.zone_display_names.get(
                    rules.default_area, rules.default_area.replace("_", " ").title()
                )
                candidates.append((rules.default_area, display_name, 1))

        # Add zones from foglocations2.txt
        if map_id in self.map_zones:
            for internal_name in self.map_zones[map_id]:
                # Skip if already added from submaps
                if any(c[0] == internal_name for c in candidates):
                    continue
                display_name = self.zone_display_names.get(
                    internal_name, internal_name.replace("_", " ").title()
                )
                # Lower priority for foglocations (no position info)
                priority = 3 if internal_name.endswith("_boss") else 2
                candidates.append((internal_name, display_name, priority))

        # Sort by priority and remove duplicates
        candidates.sort(key=lambda c: c[2])
        seen = set()
        results = []
        for internal, display, _ in candidates:
            if internal not in seen:
                seen.add(internal)
                results.append((internal, display))

        return results


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
