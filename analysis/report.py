#!/usr/bin/env python3
"""
Generate a bug report for zone resolution issues.

This script:
1. Takes a game ID as parameter
2. Prompts for a problem description (Ctrl+D to finish)
3. Creates a report directory with:
   - Game data files (zones.json, zone_links.json, entity_mapping.json, discovered_zone_links.json)
   - Recent log extract (last 5 minutes, with intelligent cut point)
   - REPORT.md with description and resolution instructions

Usage:
    ./report.py <game_id>

Example:
    ./report.py b12d5475-0b87-455a-a318-e81279b5a942
"""

import asyncio
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Change to server directory so pydantic-settings finds .env
script_dir = Path(__file__).parent
server_dir = script_dir.parent / "server"
os.chdir(server_dir)

# Add server dir to path for imports
sys.path.insert(0, str(server_dir))

from scripts.export_game import export_game  # noqa: E402

# Log file location
LOG_FILE = script_dir.parent / "fogtracker.log"

# Time window for log extraction (in minutes)
LOG_WINDOW_MINUTES = 5

# Minimum gap (in seconds) to consider as a "quiet" moment for cutting logs
QUIET_GAP_SECONDS = 10


def parse_log_timestamp(line: str) -> datetime | None:
    """Parse ISO timestamp from log line."""
    match = re.match(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+)Z", line)
    if match:
        ts_str = match.group(1)
        # Handle microseconds (may have more than 6 digits)
        if "." in ts_str:
            base, frac = ts_str.split(".")
            frac = frac[:6].ljust(6, "0")  # Truncate or pad to 6 digits
            ts_str = f"{base}.{frac}"
        return datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
    return None


def extract_recent_logs(log_path: Path, minutes: int = LOG_WINDOW_MINUTES) -> str:
    """Extract log lines from the last N minutes with intelligent cut point.

    Tries to find a "quiet" moment (gap of at least QUIET_GAP_SECONDS) to start
    the extract, so we capture a coherent session.
    """
    if not log_path.exists():
        return "(Log file not found)"

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=minutes)

    # Read all lines and filter by timestamp
    recent_lines: list[tuple[datetime, str]] = []
    with open(log_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            ts = parse_log_timestamp(line)
            if ts and ts >= cutoff:
                recent_lines.append((ts, line))

    if not recent_lines:
        return "(No recent log entries in the last {minutes} minutes)"

    # Try to find a quiet gap at the beginning
    # We look for a gap of at least QUIET_GAP_SECONDS between consecutive lines
    start_index = 0
    for i in range(1, len(recent_lines)):
        prev_ts = recent_lines[i - 1][0]
        curr_ts = recent_lines[i][0]
        gap = (curr_ts - prev_ts).total_seconds()
        if gap >= QUIET_GAP_SECONDS:
            start_index = i
            break

    # Extract lines from start_index
    extracted = [line for _, line in recent_lines[start_index:]]

    return "".join(extracted)


def generate_report_md(
    description: str,
    report_dir: Path,
) -> str:
    """Generate the REPORT.md content."""
    relative_path = report_dir.relative_to(script_dir.parent)

    lines = [
        "# Zone Resolution Issue Report",
        "",
        f"**Created:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Problem Description",
        "",
        description.strip(),
        "",
        "## Files Included",
        "",
        "- `zones.json` - Zone definitions",
        "- `zone_links.json` - All zone links (randomized connections)",
        "- `entity_mapping.json` - Entity ID to zone mapping",
        "- `discovered_zone_links.json` - Currently discovered links",
        "- `fogtracker.log` - Recent server logs",
        "",
        "## Reference Files (not included)",
        "",
        "These files in `server/data/` may be relevant for fixing zone resolution:",
        "",
        "- `fog.txt` - Zone definitions and fog gate data",
        "- `submaps.txt` - Position-based zone rules",
        "- `foglocations2.txt` - Zone location data by map",
        "",
        "## Resolution Instructions",
        "",
        "### 1. Capture baseline before fixing",
        "",
        "```bash",
        f"./analysis/test_fog_resolution.py {relative_path}",
        "```",
        "",
        "Note the '1 link' percentage and 'not found' count.",
        "",
        "### 2. Investigate the issue",
        "",
        "Key files for zone resolution:",
        "",
        "- `server/fogtracker/zone_resolver.py` - Zone candidate resolution",
        "- `server/fogtracker/zone_matching.py` - Spoiler log matching",
        "- `server/fogtracker/websocket/mod.py` - Discovery handling",
        "",
        "### 3. After fixing, verify",
        "",
        "```bash",
        f"./analysis/test_fog_resolution.py {relative_path}",
        "```",
        "",
        "Check that:",
        "- The specific case is now resolved",
        "- No regression: '1 link %' stays same or improves",
        "- No new 'not found' cases introduced",
        "",
        "### ⚠️ Test Limitations",
        "",
        "The test script **simulates** mod behavior by estimating positions from `fog.txt`.",
        "Only ~8% of zones have known coordinates (from `ToArea+Location` or `BossTriggerArea`).",
        "",
        "**This means:**",
        "",
        "- **'Not found' cases** may be test artifacts. In production, the mod sends real",
        "  player coordinates, so resolution would likely succeed.",
        "",
        "- **Multi-link discoveries (2+ links)** in the test might not occur in production",
        "  if the real position is more precise and correctly prioritizes the right zone.",
        "",
        "- **Focus on the specific bug** from the logs rather than overall test percentages.",
        "  If the reported issue is fixed, that's the main success criteria.",
        "",
        "### 4. Add a unit test",
        "",
        "Add a test case in `server/tests/unit/test_zone_resolver.py` for the fix.",
        "",
    ]

    return "\n".join(lines)


async def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: ./report.py <game_id>")
        print("Example: ./report.py b12d5475-0b87-455a-a318-e81279b5a942")
        sys.exit(1)

    game_id = sys.argv[1]

    # Prompt for problem description
    print("Describe the problem (Ctrl+D when done):", file=sys.stderr)
    try:
        description = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    except KeyboardInterrupt:
        print("\nAborted.", file=sys.stderr)
        sys.exit(1)

    if not description.strip():
        print("Error: No description provided", file=sys.stderr)
        sys.exit(1)

    # Create report directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    short_id = game_id[:8]
    report_dir = script_dir / "reports" / f"{timestamp}_{short_id}"
    report_dir.mkdir(parents=True, exist_ok=True)
    print(f"Created report directory: {report_dir}", file=sys.stderr)

    # Export game data
    print("Exporting game data...", file=sys.stderr)
    await export_game(game_id, report_dir)

    # Extract recent logs
    print("Extracting recent logs...", file=sys.stderr)
    log_content = extract_recent_logs(LOG_FILE)
    log_file = report_dir / "fogtracker.log"
    with open(log_file, "w") as f:
        f.write(log_content)
    print(f"Extracted log to: {log_file}", file=sys.stderr)

    # Generate report markdown
    report_md = generate_report_md(description, report_dir)
    report_file = report_dir / "REPORT.md"
    with open(report_file, "w") as f:
        f.write(report_md)
    print(f"Generated report: {report_file}", file=sys.stderr)

    print(f"\nReport created: {report_dir}", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
