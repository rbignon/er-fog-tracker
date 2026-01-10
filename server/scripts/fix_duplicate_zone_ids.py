#!/usr/bin/env python3
"""
Fix zone_ids for games affected by the duplicate display name bug.

The bug: lookup_by_display_name used to return the LAST zone_id for duplicate
display names (e.g., "Mohg, the Omen" returned sewer_mohg_flame instead of sewer_mohg).
This caused inconsistent zone_ids between random links (resolved via detail text)
and preexisting links (resolved via display name).

This script:
1. Finds games with zone_links that have affected zone_ids
2. Re-resolves zone_ids from display names using the fixed resolver
3. Updates the database

Usage:
    python scripts/fix_duplicate_zone_ids.py [--dry-run]

Options:
    --dry-run    Show what would be changed without modifying the database
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select

from fogtracker.database import Game, async_session
from fogtracker.zone_resolver import get_resolver, init_resolver

# Zone IDs that were incorrectly returned by lookup_by_display_name
# Map: wrong_id -> correct_id
ZONE_ID_FIXES = {
    # "Mohg, the Omen" - sewer_mohg is the main boss zone, sewer_mohg_flame is virtual
    "sewer_mohg_flame": "sewer_mohg",
    # "Hinterland - Tree Sentinel" - first boss zone (both are real but first should be canonical)
    "hinterland_treesentinel2_boss": "hinterland_treesentinel_boss",
}


def fix_zone_links(zone_links: list[dict], resolver) -> tuple[list[dict], int]:
    """Fix zone_ids in zone_links, returning updated links and count of fixes."""
    fixed = []
    fix_count = 0

    for link in zone_links:
        link = link.copy()  # Don't modify original
        changed = False

        # Re-resolve source_id from source display name
        if link.get("source"):
            correct_source_id = resolver.lookup_by_display_name(link["source"])
            if correct_source_id and link.get("source_id") != correct_source_id:
                old_id = link.get("source_id")
                if old_id in ZONE_ID_FIXES:
                    link["source_id"] = correct_source_id
                    changed = True

        # Re-resolve target_id from target display name
        if link.get("target"):
            correct_target_id = resolver.lookup_by_display_name(link["target"])
            if correct_target_id and link.get("target_id") != correct_target_id:
                old_id = link.get("target_id")
                if old_id in ZONE_ID_FIXES:
                    link["target_id"] = correct_target_id
                    changed = True

        if changed:
            fix_count += 1

        fixed.append(link)

    return fixed, fix_count


def check_game_affected(zone_links: list[dict]) -> list[str]:
    """Check if a game's zone_links contain any affected zone_ids."""
    affected_ids = set()
    for link in zone_links:
        source_id = link.get("source_id")
        target_id = link.get("target_id")
        if source_id in ZONE_ID_FIXES:
            affected_ids.add(source_id)
        if target_id in ZONE_ID_FIXES:
            affected_ids.add(target_id)
    return list(affected_ids)


async def fix_games(dry_run: bool = False) -> None:
    """Find and fix games with affected zone_ids."""
    # Initialize resolver with fixed display_name_to_zone mapping
    data_dir = Path(__file__).parent.parent / "data"
    init_resolver(data_dir)
    resolver = get_resolver()

    # Verify the fix is in place
    mohg_zone_id = resolver.lookup_by_display_name("Mohg, the Omen")
    if mohg_zone_id != "sewer_mohg":
        print(f"ERROR: Resolver fix not applied! 'Mohg, the Omen' -> '{mohg_zone_id}'")
        print("Expected: 'sewer_mohg'")
        sys.exit(1)

    print(f"Resolver verified: 'Mohg, the Omen' -> '{mohg_zone_id}'")
    print()

    async with async_session() as db:
        # Get all non-deleted games
        result = await db.execute(select(Game).where(Game.deleted_at.is_(None)))
        games = result.scalars().all()

        print(f"Checking {len(games)} games...")
        print()

        affected_games = []
        total_fixes = 0

        for game in games:
            if not game.zone_links:
                continue

            affected_ids = check_game_affected(game.zone_links)
            if not affected_ids:
                continue

            fixed_links, fix_count = fix_zone_links(game.zone_links, resolver)
            total_fixes += fix_count

            affected_games.append(
                {
                    "game": game,
                    "affected_ids": affected_ids,
                    "fixed_links": fixed_links,
                    "fix_count": fix_count,
                }
            )

            print(f"Game {game.id} (seed={game.seed}):")
            print(f"  Affected zone_ids: {affected_ids}")
            print(f"  Links to fix: {fix_count}")

        print()
        print(f"Summary: {len(affected_games)} game(s) affected, {total_fixes} link(s) to fix")

        if not affected_games:
            print("No games need fixing!")
            return

        if dry_run:
            print()
            print("DRY RUN - no changes made")
            print("Run without --dry-run to apply fixes")
            return

        # Apply fixes
        print()
        print("Applying fixes...")

        for item in affected_games:
            game = item["game"]
            game.zone_links = item["fixed_links"]

        await db.commit()
        print(f"Fixed {len(affected_games)} game(s)")


def main():
    dry_run = "--dry-run" in sys.argv

    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__)
        sys.exit(0)

    asyncio.run(fix_games(dry_run=dry_run))


if __name__ == "__main__":
    main()
