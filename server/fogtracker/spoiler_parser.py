"""
Spoiler log parser - port from web/js/parser.js
Parses Fog Gate Randomizer spoiler logs into structured zone pairs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from fogtracker.zone_resolver import ZoneResolver

# Patterns that ALWAYS indicate a one-way connection
ALWAYS_ONE_WAY_PATTERNS = [
    # "sending gate" triggers one-way when:
    # - actively being used as a teleport (source): "using the sending gate"
    # - arriving at a sending gate destination (target): "arriving at the sending gate"
    # NOT when mentioned as a location landmark (e.g., "opposite the Sending Gate")
    re.compile(r"using (?:the|a|an|either|a new) (?:new )?sending gate", re.IGNORECASE),
    re.compile(r"arriving at (?:the|a) sending gate", re.IGNORECASE),
    re.compile(r"abducted", re.IGNORECASE),
    re.compile(r"dying", re.IGNORECASE),
    re.compile(r"burning the Sealing Tree", re.IGNORECASE),
    re.compile(r"using the Pureblood", re.IGNORECASE),
    re.compile(r"Hole-Laden Necklace", re.IGNORECASE),
    re.compile(r"O Mother", re.IGNORECASE),
    re.compile(r"resting in the coffin", re.IGNORECASE),
    re.compile(r"using the coffin", re.IGNORECASE),
    re.compile(r"lying down", re.IGNORECASE),
    re.compile(r"warp to", re.IGNORECASE),
    re.compile(r"warp after", re.IGNORECASE),
    re.compile(
        r"arriving by", re.IGNORECASE
    ),  # Grace warp arrivals (e.g., "arriving by the Great Waterfall Crest grace")
    re.compile(r"from Deeproot", re.IGNORECASE),  # Sending gate destination from Deeproot
]

# Patterns that indicate one-way ONLY for preexisting connections
# "dropping" describes the connection action for preexisting links (e.g., "dropping down")
# but for random links, it often describes navigation to the fog gate location
# (e.g., "can be reached from main town dropping down outside Temple of Eiglay")
PREEXISTING_ONE_WAY_PATTERNS = [
    re.compile(r"dropping", re.IGNORECASE),  # Drop-down connections (can't go back up)
]

# "arriving at/in/from" is only one-way if the SOURCE contains a teleport mechanism
TELEPORT_SOURCE_PATTERNS = [
    # "sending gate" only triggers when actively being used as a teleport
    re.compile(r"using (?:the|a|an|either|a new) (?:new )?sending gate", re.IGNORECASE),
    re.compile(r"abducted", re.IGNORECASE),
    re.compile(r"coffin", re.IGNORECASE),
    re.compile(r"Pureblood", re.IGNORECASE),
    re.compile(r"Hole-Laden", re.IGNORECASE),
    re.compile(r"burning", re.IGNORECASE),
    re.compile(r"warp", re.IGNORECASE),
    re.compile(r"Horned Remains", re.IGNORECASE),
    re.compile(r"lying down", re.IGNORECASE),
    re.compile(r"transporter chest", re.IGNORECASE),
]

# Known key items that can be mentioned in fog log descriptions
KNOWN_KEY_ITEMS = [
    "Hole-Laden Necklace",
    "Discarded Palace Key",
    "Carian Inverted Statue",
    "Drawing-Room Key",
    "Pureblood Knight's Medal",
    "O Mother",
    "Rusty Key",
    "Academy Glintstone Key",
    "Dectus Medallion",
    "Haligtree Secret Medallion",
    "Rold Medallion",
    "Cursemark of Death",
    "Dark Moon Ring",
    "Well Depths Key",
]

# Known actions that require items (not items themselves but indicate item requirements)
KNOWN_ACTIONS = [
    "burning the Sealing Tree",
    "acquiring enough Great Runes",
]

# Patterns to skip (metadata lines and randomizer log messages)
SKIP_PATTERNS = [
    re.compile(r"^Options and seed:"),
    re.compile(r"^Key item hash:"),
    re.compile(r"^Mod directories"),
    re.compile(r"^Connecting"),
    re.compile(r"^Main fixup"),
    re.compile(r"^Areas before"),
    re.compile(r"^Other areas"),
    re.compile(r"^This spoiler"),
    re.compile(r"^For each area"),
    re.compile(r"^Paired warps"),
    re.compile(r"^How to get"),
    re.compile(r"^- Find"),
    re.compile(r"^- The first"),
    re.compile(r"^- Repeat"),
    re.compile(r"^If you're stuck"),
    re.compile(r"^you haven't"),
    re.compile(r"^>>>"),
    re.compile(r"^Optional areas:"),
    re.compile(r"^Finished"),
    re.compile(r"^Writing"),
    re.compile(r"^\$ "),
    re.compile(r"^\d+ entrances"),
    re.compile(r"^Done$"),
    re.compile(r"^Done "),  # "Done with core pass", etc.
    re.compile(r"^[A-Z]:\\"),  # Windows paths (C:\, D:\, I:\, etc.)
    re.compile(r"^Clique fixup"),  # Randomizer log message
    re.compile(r"^Found key item"),  # Randomizer routing info
]

# Patterns that indicate details in connection descriptions
DETAIL_PATTERNS = [
    re.compile(r"\s*\(before\s", re.IGNORECASE),
    re.compile(r"\s*\(after\s", re.IGNORECASE),
    re.compile(r"\s*\(at\s", re.IGNORECASE),
    re.compile(r"\s*\(using\s", re.IGNORECASE),
    re.compile(r"\s*\(in\s", re.IGNORECASE),
    re.compile(r"\s*\(the\s", re.IGNORECASE),
    re.compile(r"\s*\(on\s", re.IGNORECASE),
    re.compile(r"\s*\(arriving\s", re.IGNORECASE),
    re.compile(r"\s*\(opening\s", re.IGNORECASE),
    re.compile(r"\s*\(dropping\s", re.IGNORECASE),
    re.compile(r"\s*\(with\s", re.IGNORECASE),
    re.compile(r"\s*\(accessing\s", re.IGNORECASE),
    re.compile(r"\s*\(defeating\s", re.IGNORECASE),
    re.compile(r"\s*\(completing\s", re.IGNORECASE),
    re.compile(r"\s*\(riding\s", re.IGNORECASE),
    re.compile(r"\s*\(jumping\s", re.IGNORECASE),
    re.compile(r"\s*\(resting\s", re.IGNORECASE),
    re.compile(r"\s*\(touching\s", re.IGNORECASE),
    re.compile(r"\s*\(burning\s", re.IGNORECASE),
    re.compile(r"\s*\(getting\s", re.IGNORECASE),
    re.compile(r"\s*\(traversing\s", re.IGNORECASE),
    re.compile(r"\s*\(going\s", re.IGNORECASE),
    re.compile(r"\s*\(return\s", re.IGNORECASE),
    re.compile(r"\s*\(unlocking\s", re.IGNORECASE),
    re.compile(r"\s*\(instead\s", re.IGNORECASE),
    re.compile(r"\s*\(warp\s", re.IGNORECASE),
    re.compile(r"\s*\(outside\s", re.IGNORECASE),
    re.compile(r"\s*\(behind\s", re.IGNORECASE),
    re.compile(r"\s*\(past\s", re.IGNORECASE),
    re.compile(r"\s*\(up\s", re.IGNORECASE),
    re.compile(r"\s*\(down\s", re.IGNORECASE),
    re.compile(r"\s*\(backwards\s", re.IGNORECASE),
    re.compile(r"\s*\(to\s", re.IGNORECASE),  # "to Capital Rampart after..."
]


@dataclass
class ZoneInfo:
    """Parsed zone/area info."""

    id: str  # zone_key (internal identifier from fog.txt)
    name: str  # Display name
    is_boss: bool = False
    scaling: str | None = None


@dataclass
class ConnectionInfo:
    """Parsed connection info."""

    # Required fields (no defaults) must come first
    id: str  # Unique identifier for this link
    source: str  # Source zone name
    target: str  # Target zone name

    # Optional fields with defaults
    source_id: str | None = None  # Source zone_key (internal identifier from fog.txt)
    target_id: str | None = None  # Target zone_key (internal identifier from fog.txt)
    conn_type: str = "random"  # 'random' or 'preexisting'
    source_details: str = ""
    target_details: str = ""
    required_item: str | None = None  # Name of required item (e.g., "Academy Glintstone Key")
    required_item_from: str | None = None  # Zones where the item can be found
    is_one_way: bool = False  # True for sending gates, coffins, drop-downs, etc.


@dataclass
class ParseResult:
    """Result of parsing a spoiler log."""

    seed: int
    zones: dict[str, ZoneInfo] = field(default_factory=dict)
    connections: list[ConnectionInfo] = field(default_factory=list)
    options: str = ""
    starting_zone_id: str | None = None  # zone_key of starting zone (first zone parsed)
    is_dungeon_crawler: bool = False  # True if "crawl" mode (dungeons only)


class SpoilerParseError(Exception):
    """Raised when spoiler log parsing fails."""

    pass


def _should_skip_line(line: str) -> bool:
    """Check if a line should be skipped."""
    trimmed = line.strip()
    if not trimmed:
        return True
    return any(pattern.match(trimmed) for pattern in SKIP_PATTERNS)


def _parse_area_line(line: str) -> ZoneInfo | None:
    """Parse an area definition line.

    Note: The zone ID is initially set to the display name.
    It will be replaced with the zone_key later in parse_spoiler_log()
    when the resolver is available.
    """
    # Area lines are not indented
    if line.startswith("  ") or line.startswith("\t"):
        return None
    if _should_skip_line(line):
        return None

    is_boss = "<<<<<" in line
    line_clean = line.replace("<<<<<", "").strip()

    # Extract scaling info
    scaling_match = re.search(r"\(scaling:\s*([^)]+)\)", line_clean)
    scaling = scaling_match.group(1).strip() if scaling_match else None

    # Extract area name (everything before the parenthesis)
    name_match = re.match(r"^([^(]+)", line_clean)
    if name_match:
        name = name_match.group(1).strip()
        if name:
            # ID is temporarily set to name, will be replaced with zone_key later
            return ZoneInfo(id=name, name=name, is_boss=is_boss, scaling=scaling)
    return None


def _extract_area_and_details(text: str) -> tuple[str, str]:
    """Extract area name and details from a text segment.

    Zone names in fog.txt never contain parentheses, so any parenthetical
    content in spoiler log names is always connection detail text.
    """
    # First try DETAIL_PATTERNS for specific pattern matching
    for pattern in DETAIL_PATTERNS:
        match = pattern.search(text)
        if match:
            area_name = text[: match.start()].strip()
            # Extract details in parentheses
            details_match = re.search(r"\(([^)]+)\)", text[match.start() :])
            details = details_match.group(1) if details_match else ""
            return area_name, details

    # Fallback: extract any trailing parenthetical content
    # Zone names never contain parentheses, so this is always details
    paren_match = re.search(r"\s*\(([^)]+)\)\s*$", text)
    if paren_match:
        area_name = text[: paren_match.start()].strip()
        details = paren_match.group(1)
        return area_name, details

    return text.strip(), ""


def _extract_required_item(source_details: str, target_details: str) -> str | None:
    """Extract key item or action name from connection details.

    Args:
        source_details: The source details text
        target_details: The target details text

    Returns:
        The item/action name if found, None otherwise
    """
    text = f"{source_details} {target_details}"

    # Check for known key items
    for item in KNOWN_KEY_ITEMS:
        if item in text:
            return item

    # Check for known actions (case-insensitive)
    text_lower = text.lower()
    for action in KNOWN_ACTIONS:
        if action.lower() in text_lower:
            return action

    return None


def _parse_connection_line(line: str) -> ConnectionInfo | None:
    """Parse a connection line (Random: or Preexisting:)."""
    trimmed = line.strip()

    if trimmed.startswith("Random:"):
        conn_type = "random"
        content = trimmed[7:].strip()
    elif trimmed.startswith("Preexisting:"):
        conn_type = "preexisting"
        content = trimmed[12:].strip()
    else:
        return None

    if " --> " not in content:
        return None

    parts = content.split(" --> ")
    if len(parts) != 2:
        return None

    source_part, target_part = parts

    source, source_details = _extract_area_and_details(source_part)
    target, target_details = _extract_area_and_details(target_part)

    # Extract "using an item from..." or "using items from..."
    required_item_from = None
    using_match = re.search(r",\s*using (?:an )?items? from\s+(.+?)$", content, re.IGNORECASE)
    if using_match:
        required_item_from = using_match.group(1).strip()

    # Clean up "using ... from..."
    clean_source = source.split(", using")[0].strip()
    clean_target = target.split(", using")[0].strip()

    # Detect if this is a one-way connection based on description patterns
    # IMPORTANT: Only search in details text (parenthetical content), not zone names.
    # Zone names like "Volcano Manor - Hallway Opposite Sending Gate" should not
    # trigger one-way detection just because they contain pattern keywords.
    details_text = f"{source_details} {target_details}"
    is_one_way = False

    # Check patterns that always indicate one-way (applies to both random and preexisting)
    # This catches sending gates, coffins, etc.
    if (
        any(pattern.search(details_text) for pattern in ALWAYS_ONE_WAY_PATTERNS)
        or conn_type == "preexisting"
        and any(pattern.search(details_text) for pattern in PREEXISTING_ONE_WAY_PATTERNS)
    ):
        is_one_way = True
    # Check "arriving" - only one-way if source details contain teleport mechanism
    # This is specific to random links (fog gates with teleport mechanisms)
    elif conn_type == "random" and re.search(r"arriving (at|in|from)", details_text, re.IGNORECASE):
        is_one_way = any(pattern.search(source_details) for pattern in TELEPORT_SOURCE_PATTERNS)

    # Extract required item name from details
    required_item = _extract_required_item(source_details, target_details)

    return ConnectionInfo(
        id=str(uuid4()),
        source=clean_source,
        source_id=None,  # Will be populated later with zone ID
        target=clean_target,
        target_id=None,  # Will be populated later with zone ID
        conn_type=conn_type,
        source_details=source_details,
        target_details=target_details,
        required_item=required_item,
        required_item_from=required_item_from,
        is_one_way=is_one_way,
    )


def parse_spoiler_log(text: str, resolver: ZoneResolver | None = None) -> ParseResult:
    """
    Parse a Fog Gate Randomizer spoiler log.

    Args:
        text: The full spoiler log text content.
        resolver: ZoneResolver for zone_key lookups. Required for zone_key-based IDs.

    Returns:
        ParseResult containing seed, zones, and connections.

    Raises:
        SpoilerParseError: If the log format is invalid, resolver is missing,
            or a zone is not found in fog.txt.
    """
    lines = text.split("\n")

    if not lines:
        raise SpoilerParseError("Empty spoiler log")

    # Extract seed from first line
    # Format: "Options and seed:12345 ..."
    first_line = lines[0].strip()
    seed_match = re.search(r"seed:(\d+)", first_line)
    if not seed_match:
        raise SpoilerParseError("Could not find seed in spoiler log header")

    seed = int(seed_match.group(1))
    options = first_line

    # Detect game mode: "crawl" = Dungeon Crawler (dungeons only)
    # In Dungeon Crawler mode, Optional areas contain overworld zones we don't want to show
    # In World Shuffle mode (no "crawl"), Optional areas contain accessible zones we want to include
    is_dungeon_crawler = " crawl " in f" {options} " or options.endswith(" crawl")

    zones: dict[str, ZoneInfo] = {}  # Keyed by zone name
    connections: list[ConnectionInfo] = []
    first_zone_name: str | None = None  # Track first zone for starting_zone_id

    for line in lines:
        # Stop at optional areas section only for Dungeon Crawler mode
        # In World Shuffle, we want to include optional areas as they're accessible via fog gates
        if line.strip() == "Optional areas:" and is_dungeon_crawler:
            break

        # Try to parse as area
        zone_info = _parse_area_line(line)
        if zone_info:
            if zone_info.name not in zones:
                zones[zone_info.name] = zone_info
                # Track first zone encountered
                if first_zone_name is None:
                    first_zone_name = zone_info.name
            else:
                # Update existing zone with boss/scaling info if we have it
                existing = zones[zone_info.name]
                if zone_info.is_boss:
                    existing.is_boss = True
                if zone_info.scaling:
                    existing.scaling = zone_info.scaling
            continue

        # Try to parse as connection
        if line.startswith("  ") or line.startswith("\t"):
            conn = _parse_connection_line(line)
            if conn:
                # Ensure zones exist (create with temporary ID if missing)
                if conn.source not in zones:
                    zones[conn.source] = ZoneInfo(id=conn.source, name=conn.source)
                if conn.target not in zones:
                    zones[conn.target] = ZoneInfo(id=conn.target, name=conn.target)
                connections.append(conn)

    if not zones:
        raise SpoilerParseError("No zones found in spoiler log")

    if not connections:
        raise SpoilerParseError("No connections found in spoiler log")

    # Resolve zone_keys for all zones
    starting_zone_id = None
    unknown_zones = []
    if not resolver:
        raise SpoilerParseError("ZoneResolver is required for zone_key-based IDs")

    for zone_name, zone_info in zones.items():
        zone_key = resolver.lookup_by_display_name(zone_name)
        if zone_key:
            zone_info.id = zone_key
        else:
            unknown_zones.append(zone_name)
        # Set starting_zone_id from first zone
        if zone_name == first_zone_name:
            starting_zone_id = zone_key

    # Fail if any zones are not found in fog.txt
    if unknown_zones:
        raise SpoilerParseError(
            f"Zones not found in fog.txt: {unknown_zones}. "
            "Please add them to data/fog.txt with their zone_key."
        )

    # Populate source_id and target_id for each connection (now zone_keys)
    for conn in connections:
        if conn.source in zones:
            conn.source_id = zones[conn.source].id
        if conn.target in zones:
            conn.target_id = zones[conn.target].id

    zones_by_id = {zone_info.id: zone_info for zone_info in zones.values()}

    return ParseResult(
        seed=seed,
        zones=zones_by_id,
        connections=connections,
        options=options,
        starting_zone_id=starting_zone_id,
        is_dungeon_crawler=is_dungeon_crawler,
    )


def validate_spoiler_header(text: str) -> int:
    """
    Quick validation of spoiler log header only.
    Returns seed if valid.

    Raises:
        SpoilerParseError: If the header is invalid.
    """
    lines = text.split("\n", 1)
    if not lines:
        raise SpoilerParseError("Empty spoiler log")

    first_line = lines[0].strip()
    seed_match = re.search(r"seed:(\d+)", first_line)
    if not seed_match:
        raise SpoilerParseError("Could not find seed in spoiler log header")

    return int(seed_match.group(1))


def enrich_connections_with_zone_keys(
    connections: list[ConnectionInfo],
    resolver: ZoneResolver,
) -> list[ConnectionInfo]:
    """
    Enrich connections with zone_keys from fog.txt.

    For each connection, looks up the internal zone key from:
    1. source_details/target_details (ASide/BSide text in fog.txt)
    2. Fallback: display_name → zone_key reverse lookup

    The zone_keys are stored in source_id and target_id fields.

    Args:
        connections: List of parsed connections
        resolver: ZoneResolver with fog.txt data loaded

    Returns:
        List of enriched connections with source_id and target_id populated with zone_keys.
    """
    enriched = []
    for conn in connections:
        source_id = None
        target_id = None

        # Try to resolve source zone_key from source_details (ASide/BSide text)
        if conn.source_details:
            zone_key, display_name = resolver.lookup_by_detail_text(conn.source_details)
            # Only use if the display_name matches the expected source
            if zone_key and display_name and display_name == conn.source:
                source_id = zone_key

        # Fallback: try display_name → zone_key
        if not source_id:
            source_id = resolver.lookup_by_display_name(conn.source)

        # Try to resolve target zone_key from target_details
        if conn.target_details:
            zone_key, display_name = resolver.lookup_by_detail_text(conn.target_details)
            # Only use if the display_name matches the expected target
            if zone_key and display_name and display_name == conn.target:
                target_id = zone_key

        # Fallback: try display_name → zone_key
        if not target_id:
            target_id = resolver.lookup_by_display_name(conn.target)

        # Determine is_one_way for preexisting connections using fog.txt To: structure
        is_one_way = conn.is_one_way
        if conn.conn_type == "preexisting" and source_id and target_id and not is_one_way:
            # Check if link exists in fog.txt To: sections
            forward_exists = resolver.has_preexisting_link(source_id, target_id)
            reverse_exists = resolver.has_preexisting_link(target_id, source_id)
            # If only one direction exists, mark as one-way
            if forward_exists and not reverse_exists:
                is_one_way = True

        # Determine is_one_way for random connections using fog.txt Cond: fields
        # If the source fog gate side (identified by source_details) has a Cond:,
        # the link is one-way because the player cannot return through that fog gate
        # without meeting the condition (shortcut ladder, one-way door, drop, etc.)
        if (
            conn.conn_type == "random"
            and conn.source_details
            and not is_one_way
            and resolver.has_conditional_fog_gate_by_detail(conn.source_details)
        ):
            is_one_way = True

        # Create enriched connection with zone_keys in source_id/target_id
        enriched.append(
            ConnectionInfo(
                id=conn.id,
                source=conn.source,
                source_id=source_id,
                target=conn.target,
                target_id=target_id,
                conn_type=conn.conn_type,
                source_details=conn.source_details,
                target_details=conn.target_details,
                required_item=conn.required_item,
                required_item_from=conn.required_item_from,
                is_one_way=is_one_way,
            )
        )

    return enriched
