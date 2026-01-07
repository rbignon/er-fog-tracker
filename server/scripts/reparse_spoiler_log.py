#!/usr/bin/env python3
"""
Re-parse a spoiler log and update the game's zones/zone_links in the database.

Usage:
    python scripts/reparse_spoiler_log.py <seed> <spoiler_log_file>

Example:
    python scripts/reparse_spoiler_log.py 399723671 ../analysis/reports/260107_2247/2026-01-07_16.52.10_log_399723671_04021.txt
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select

from fogtracker.database import Game, async_session
from fogtracker.models import Zone, ZoneLink
from fogtracker.spoiler_parser import enrich_connections_with_zone_keys, parse_spoiler_log
from fogtracker.zone_resolver import get_resolver, init_resolver


async def reparse_game(seed: int, spoiler_log_path: Path) -> None:
    """Re-parse spoiler log and update game in database."""
    # Initialize resolver
    data_dir = Path(__file__).parent.parent / "data"
    init_resolver(data_dir)
    resolver = get_resolver()

    # Read and parse spoiler log
    spoiler_log_text = spoiler_log_path.read_text()
    parsed = parse_spoiler_log(spoiler_log_text, resolver)

    if parsed.seed != seed:
        print(f"Warning: Spoiler log seed ({parsed.seed}) doesn't match provided seed ({seed})")
        return

    # Enrich connections
    enriched_connections = enrich_connections_with_zone_keys(parsed.connections, resolver)

    # Convert to database format
    zone_links = [
        ZoneLink(
            id=conn.id,
            source=conn.source,
            source_id=conn.source_id,
            target=conn.target,
            target_id=conn.target_id,
            type=conn.conn_type,
            source_details=conn.source_details or None,
            target_details=conn.target_details or None,
            required_item=conn.required_item,
            required_item_from=conn.required_item_from,
            is_one_way=conn.is_one_way,
        ).model_dump()
        for conn in enriched_connections
    ]

    zones = {
        zone.id: Zone(
            id=zone.id,
            name=zone.name,
            is_boss=zone.is_boss,
            scaling=zone.scaling,
        ).model_dump()
        for zone in parsed.zones.values()
    }

    print(f"Parsed {len(zones)} zones and {len(zone_links)} zone_links")

    # Find and update games with this seed
    async with async_session() as db:
        result = await db.execute(select(Game).where(Game.seed == seed, Game.deleted_at.is_(None)))
        games = result.scalars().all()

        if not games:
            print(f"No games found with seed {seed}")
            return

        print(f"Found {len(games)} game(s) with seed {seed}")

        for game in games:
            old_zones_count = len(game.zones) if game.zones else 0
            old_links_count = len(game.zone_links) if game.zone_links else 0

            game.zones = zones
            game.zone_links = zone_links

            print(f"  Game {game.id}:")
            print(f"    Zones: {old_zones_count} -> {len(zones)} (+{len(zones) - old_zones_count})")
            print(
                f"    Links: {old_links_count} -> {len(zone_links)} (+{len(zone_links) - old_links_count})"
            )

        await db.commit()
        print("Database updated successfully")


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)

    seed = int(sys.argv[1])
    spoiler_log_path = Path(sys.argv[2])

    if not spoiler_log_path.exists():
        print(f"Error: Spoiler log file not found: {spoiler_log_path}")
        sys.exit(1)

    asyncio.run(reparse_game(seed, spoiler_log_path))


if __name__ == "__main__":
    main()
