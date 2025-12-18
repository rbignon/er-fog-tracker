#!/usr/bin/env python3
"""
Migration script to add UUIDs to zone_pairs and convert discovered_links format.

Run from the server directory:
    python -m scripts.migrate_link_uuids

Or with dry-run to preview changes:
    python -m scripts.migrate_link_uuids --dry-run
"""

import asyncio
import sys
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Add parent directory to path for imports
sys.path.insert(0, ".")

from fogvizu.config import settings
from fogvizu.database import Game


async def migrate_game(session: AsyncSession, game: Game, dry_run: bool = False) -> dict:
    """
    Migrate a single game's zone_pairs and discovered_links.

    Returns dict with migration stats.
    """
    stats = {
        "zone_pairs_updated": 0,
        "discovered_links_converted": 0,
        "parallel_links_expanded": 0,
    }

    zone_pairs = game.zone_pairs or []
    discovered_links = game.discovered_links or []

    # Step 1: Add UUIDs to zone_pairs that don't have them
    zone_pairs_modified = False
    for zp in zone_pairs:
        if not zp.get("id"):
            zp["id"] = str(uuid4())
            stats["zone_pairs_updated"] += 1
            zone_pairs_modified = True

    # Step 2: Build index for looking up zone_pairs by source/target
    # Note: Multiple zone_pairs can have same source/target (parallel links)
    zp_by_endpoints: dict[tuple[str, str], list[dict]] = {}
    for zp in zone_pairs:
        key = (zp.get("source", ""), zp.get("destination", ""))
        if key not in zp_by_endpoints:
            zp_by_endpoints[key] = []
        zp_by_endpoints[key].append(zp)

    # Step 3: Convert discovered_links from {source, target} to {link_id}
    new_discovered_links = []
    seen_link_ids = set()

    for dl in discovered_links:
        # Check if already in new format
        if "link_id" in dl and "source" not in dl:
            # Already migrated
            if dl["link_id"] not in seen_link_ids:
                new_discovered_links.append(dl)
                seen_link_ids.add(dl["link_id"])
            continue

        # Old format: {source, target, discovered_at, discovered_by}
        source = dl.get("source", "")
        target = dl.get("target", "")
        discovered_at = dl.get("discovered_at")
        discovered_by = dl.get("discovered_by")

        # Find matching zone_pair(s)
        matching_zps = zp_by_endpoints.get((source, target), [])

        if not matching_zps:
            # Try reverse direction for bidirectional links
            matching_zps = zp_by_endpoints.get((target, source), [])

        if not matching_zps:
            # No matching zone_pair found - skip this discovered_link
            print(f"  Warning: No zone_pair found for {source} -> {target}")
            continue

        # Mark ALL matching zone_pairs as discovered (conservative approach for parallel links)
        if len(matching_zps) > 1:
            stats["parallel_links_expanded"] += len(matching_zps) - 1

        for zp in matching_zps:
            link_id = zp.get("id")
            if link_id and link_id not in seen_link_ids:
                new_discovered_links.append(
                    {
                        "link_id": link_id,
                        "discovered_at": discovered_at,
                        "discovered_by": discovered_by,
                    }
                )
                seen_link_ids.add(link_id)
                stats["discovered_links_converted"] += 1

    # Step 4: Update game if changes were made
    has_changes = zone_pairs_modified or stats["discovered_links_converted"] > 0
    if has_changes and not dry_run:
        import copy

        from sqlalchemy.orm.attributes import flag_modified

        # Deep copy and flag_modified to force SQLAlchemy to detect JSONB changes
        game.zone_pairs = copy.deepcopy(zone_pairs)
        game.discovered_links = list(new_discovered_links)
        flag_modified(game, "zone_pairs")
        flag_modified(game, "discovered_links")

    return stats


async def run_migration(dry_run: bool = False):
    """Run the migration on all games."""
    print(f"Starting migration (dry_run={dry_run})...")
    print(f"Database: {settings.database_url.split('@')[-1]}")  # Hide credentials

    engine = create_async_engine(settings.database_url)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    total_stats = {
        "games_processed": 0,
        "games_modified": 0,
        "zone_pairs_updated": 0,
        "discovered_links_converted": 0,
        "parallel_links_expanded": 0,
    }

    async with async_session() as session:
        # Get all games
        result = await session.execute(select(Game).where(Game.deleted_at.is_(None)))
        games = result.scalars().all()

        print(f"Found {len(games)} games to process")

        for game in games:
            total_stats["games_processed"] += 1
            print(f"\nProcessing game {game.id} (seed {game.seed})...")

            stats = await migrate_game(session, game, dry_run)

            if stats["zone_pairs_updated"] > 0 or stats["discovered_links_converted"] > 0:
                total_stats["games_modified"] += 1
                print(f"  - Zone pairs updated: {stats['zone_pairs_updated']}")
                print(f"  - Discovered links converted: {stats['discovered_links_converted']}")
                if stats["parallel_links_expanded"] > 0:
                    print(f"  - Parallel links expanded: {stats['parallel_links_expanded']}")

        if not dry_run:
            await session.commit()
            print("\nChanges committed to database.")
        else:
            print("\nDry run - no changes committed.")

    await engine.dispose()

    print("\n=== Migration Summary ===")
    print(f"Games processed: {total_stats['games_processed']}")
    print(f"Games modified: {total_stats['games_modified']}")
    print(f"Zone pairs updated: {total_stats['zone_pairs_updated']}")
    print(f"Discovered links converted: {total_stats['discovered_links_converted']}")
    print(f"Parallel links expanded: {total_stats['parallel_links_expanded']}")


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    asyncio.run(run_migration(dry_run))
