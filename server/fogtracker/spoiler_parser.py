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
    re.compile(r"sending gate", re.IGNORECASE),
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
    re.compile(r"dropping", re.IGNORECASE),  # Drop-down connections (can't go back up)
]

# "arriving at/in/from" is only one-way if the SOURCE contains a teleport mechanism
TELEPORT_SOURCE_PATTERNS = [
    re.compile(r"sending gate", re.IGNORECASE),
    re.compile(r"abducted", re.IGNORECASE),
    re.compile(r"coffin", re.IGNORECASE),
    re.compile(r"Pureblood", re.IGNORECASE),
    re.compile(r"Hole-Laden", re.IGNORECASE),
    re.compile(r"burning", re.IGNORECASE),
    re.compile(r"warp", re.IGNORECASE),
    re.compile(r"Horned Remains", re.IGNORECASE),
    re.compile(r"lying down", re.IGNORECASE),
]

# Patterns to skip (metadata lines)
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
    re.compile(r"^C:\\"),
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
]


@dataclass
class ZoneInfo:
    """Parsed zone/area info."""

    id: str  # UUID
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
    source_id: str | None = None  # Source zone UUID
    target_id: str | None = None  # Target zone UUID
    conn_type: str = "random"  # 'random' or 'preexisting'
    source_details: str = ""
    target_details: str = ""
    source_key: str | None = None  # Internal zone key (from fog.txt)
    target_key: str | None = None  # Internal zone key (from fog.txt)
    required_item_from: str | None = None
    is_inherently_one_way: bool = False


@dataclass
class ParseResult:
    """Result of parsing a spoiler log."""

    seed: int
    zones: list[ZoneInfo] = field(default_factory=list)
    connections: list[ConnectionInfo] = field(default_factory=list)
    options: str = ""


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
    """Parse an area definition line."""
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
            return ZoneInfo(id=str(uuid4()), name=name, is_boss=is_boss, scaling=scaling)
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
    is_inherently_one_way = False

    # Check patterns that always indicate one-way (applies to both random and preexisting)
    # This catches drop-downs, sending gates, coffins, etc.
    if any(pattern.search(details_text) for pattern in ALWAYS_ONE_WAY_PATTERNS):
        is_inherently_one_way = True
    # Check "arriving" - only one-way if source details contain teleport mechanism
    # This is specific to random links (fog gates with teleport mechanisms)
    elif conn_type == "random" and re.search(r"arriving (at|in|from)", details_text, re.IGNORECASE):
        is_inherently_one_way = any(
            pattern.search(source_details) for pattern in TELEPORT_SOURCE_PATTERNS
        )

    return ConnectionInfo(
        id=str(uuid4()),
        source=clean_source,
        source_id=None,  # Will be populated later with zone UUID
        target=clean_target,
        target_id=None,  # Will be populated later with zone UUID
        conn_type=conn_type,
        source_details=source_details,
        target_details=target_details,
        required_item_from=required_item_from,
        is_inherently_one_way=is_inherently_one_way,
    )


def parse_spoiler_log(text: str) -> ParseResult:
    """
    Parse a Fog Gate Randomizer spoiler log.

    Args:
        text: The full spoiler log text content.

    Returns:
        ParseResult containing seed, zones, and connections.

    Raises:
        SpoilerParseError: If the log format is invalid.
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

    zones: dict[str, ZoneInfo] = {}  # Keyed by zone name
    connections: list[ConnectionInfo] = []

    for line in lines:
        # Stop at optional areas section
        if line.strip() == "Optional areas:":
            break

        # Try to parse as area
        zone_info = _parse_area_line(line)
        if zone_info:
            if zone_info.name not in zones:
                zones[zone_info.name] = zone_info
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
                # Ensure zones exist (create with UUID if missing)
                if conn.source not in zones:
                    zones[conn.source] = ZoneInfo(id=str(uuid4()), name=conn.source)
                if conn.target not in zones:
                    zones[conn.target] = ZoneInfo(id=str(uuid4()), name=conn.target)
                connections.append(conn)

    if not zones:
        raise SpoilerParseError("No zones found in spoiler log")

    if not connections:
        raise SpoilerParseError("No connections found in spoiler log")

    # Populate source_id and target_id for each connection
    for conn in connections:
        if conn.source in zones:
            conn.source_id = zones[conn.source].id
        if conn.target in zones:
            conn.target_id = zones[conn.target].id

    return ParseResult(
        seed=seed,
        zones=list(zones.values()),
        connections=connections,
        options=options,
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

    Args:
        connections: List of parsed connections
        resolver: ZoneResolver with fog.txt data loaded

    Returns:
        List of enriched connections with source_key and target_key populated.
    """
    enriched = []
    for conn in connections:
        source_key = None
        target_key = None

        # Try to resolve source_key from source_details (ASide/BSide text)
        if conn.source_details:
            zone_key, display_name = resolver.lookup_by_detail_text(conn.source_details)
            # Only use if the display_name matches the expected source
            if zone_key and display_name and display_name == conn.source:
                source_key = zone_key

        # Fallback: try display_name → zone_key
        if not source_key:
            source_key = resolver.lookup_by_display_name(conn.source)

        # Try to resolve target_key from target_details
        if conn.target_details:
            zone_key, display_name = resolver.lookup_by_detail_text(conn.target_details)
            # Only use if the display_name matches the expected target
            if zone_key and display_name and display_name == conn.target:
                target_key = zone_key

        # Fallback: try display_name → zone_key
        if not target_key:
            target_key = resolver.lookup_by_display_name(conn.target)

        # Create enriched connection (preserve source_id/target_id from original)
        enriched.append(
            ConnectionInfo(
                id=conn.id,
                source=conn.source,
                source_id=conn.source_id,
                target=conn.target,
                target_id=conn.target_id,
                conn_type=conn.conn_type,
                source_details=conn.source_details,
                target_details=conn.target_details,
                source_key=source_key,
                target_key=target_key,
                required_item_from=conn.required_item_from,
                is_inherently_one_way=conn.is_inherently_one_way,
            )
        )

    return enriched
