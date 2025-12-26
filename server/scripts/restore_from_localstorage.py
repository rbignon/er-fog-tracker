#!/usr/bin/env python3
"""
Restore discovered_zone_links from localStorage data.

This script:
1. Adds UUIDs to zone_links that don't have them
2. Matches localStorage discoveredLinks ("source|target") to zone_links
3. Creates proper discovered_zone_links with zone_link_id format

Usage:
    python -m scripts.restore_from_localstorage <game_id>
"""

import asyncio
import sys
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

sys.path.insert(0, ".")

from fogtracker.config import settings
from fogtracker.database import Game

# localStorage data to restore
LOCALSTORAGE_DATA = {
    "discovered": [
        "Chapel of Anticipation",
        "Leyndell",
        "Ainsel River Downstream",
        "Limgrave Tunnels - Stonedigger Troll",
        "Farum Azula - Dragon Temple",
        "Farum Azula - Dragon Temple Transept",
        "Leyndell - Queen's Bedchamber",
        "Leyndell - Behind Erdtree Sanctuary",
        "Leyndell - before Divine Tower",
        "Maliketh the Black Blade",
        "Roundtable Hold",
        "Leyndell - Divine Bridge (taking the elevator from Fortified Manor)",
        "Leyndell - Erdtree Sanctuary Stairs",
        "Leyndell - Erdtree Sanctuary",
        "Cave of Knowledge - From Seaside Ruins",
        "Cave of Knowledge",
        "Specimen Storehouse - Before Messmer",
        "Specimen Storehouse",
        "Castle Sol",
        "Specimen Storehouse - Back Section",
        "Margit, the Fell Omen",
        "Capital Outskirts - Sealed Tunnel",
        "Capital Outskirts - Sealed Tunnel Before Boss",
        "Capital Outskirts - Sealed Tunnel - Onyx Lord",
        "Leyndell - Elden Throne",
        "Academy of Raya Lucaria after Red Wolf",
        "Red Wolf of Radagon",
        "Loretta, Knight of the Haligtree",
        "Farum Azula Rooftop and Bridge",
        "Belurat",
        "Belurat Swamp",
        "Enir-Ilim - Belurat",
        "Belurat - Stairs before Enir-Ilim",
        "Enir-Ilim",
        "Enir-Ilim - After Leda",
        "Enir-Ilim - Promised Consort Radahn",
    ],
    "discoveredLinks": [
        "Chapel of Anticipation|Leyndell",
        "Leyndell|Ainsel River Downstream",
        "Ainsel River Downstream|Limgrave Tunnels - Stonedigger Troll",
        "Limgrave Tunnels - Stonedigger Troll|Farum Azula - Dragon Temple",
        "Farum Azula - Dragon Temple|Farum Azula - Dragon Temple Transept",
        "Farum Azula - Dragon Temple Transept|Leyndell - Queen's Bedchamber",
        "Leyndell - Queen's Bedchamber|Leyndell - Behind Erdtree Sanctuary",
        "Leyndell|Leyndell - before Divine Tower",
        "Leyndell - Behind Erdtree Sanctuary|Maliketh the Black Blade",
        "Chapel of Anticipation|Cave of Knowledge - From Seaside Ruins",
        "Cave of Knowledge - From Seaside Ruins|Cave of Knowledge",
        "Leyndell - Queen's Bedchamber|Leyndell - Erdtree Sanctuary",
        "Leyndell - Erdtree Sanctuary|Castle Sol",
        "Castle Sol|Specimen Storehouse - Back Section",
        "Specimen Storehouse - Back Section|Specimen Storehouse",
        "Specimen Storehouse|Margit, the Fell Omen",
        "Margit, the Fell Omen|Capital Outskirts - Sealed Tunnel",
        "Cave of Knowledge|Capital Outskirts - Sealed Tunnel - Onyx Lord",
        "Capital Outskirts - Sealed Tunnel - Onyx Lord|Leyndell - Elden Throne",
        "Leyndell - Elden Throne|Academy of Raya Lucaria after Red Wolf",
        "Academy of Raya Lucaria after Red Wolf|Loretta, Knight of the Haligtree",
        "Loretta, Knight of the Haligtree|Farum Azula Rooftop and Bridge",
        "Farum Azula Rooftop and Bridge|Enir-Ilim",
        "Chapel of Anticipation|Roundtable Hold",
        "Leyndell|Leyndell - Divine Bridge (taking the elevator from Fortified Manor)",
        "Leyndell - Queen's Bedchamber|Leyndell - Erdtree Sanctuary Stairs",
        "Leyndell - Erdtree Sanctuary Stairs|Leyndell",
        "Specimen Storehouse|Specimen Storehouse - Before Messmer",
        "Capital Outskirts - Sealed Tunnel|Capital Outskirts - Sealed Tunnel Before Boss",
        "Academy of Raya Lucaria after Red Wolf|Red Wolf of Radagon",
        "Enir-Ilim|Belurat - Stairs before Enir-Ilim",
        "Belurat - Stairs before Enir-Ilim|Enir-Ilim",
        "Enir-Ilim|Enir-Ilim - After Leda",
        "Enir-Ilim - After Leda|Enir-Ilim",
        "Enir-Ilim - After Leda|Enir-Ilim - Promised Consort Radahn",
        "Enir-Ilim|Enir-Ilim - Belurat",
        "Enir-Ilim - Belurat|Belurat Swamp",
        "Belurat Swamp|Belurat",
        "Belurat|Belurat Swamp",
    ],
}


async def restore_game(game_id: str, dry_run: bool = False):
    """Restore a game's discovered_zone_links from localStorage data."""
    print(f"Restoring game {game_id} (dry_run={dry_run})...")

    engine = create_async_engine(settings.database_url)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    async with async_session() as session:
        result = await session.execute(select(Game).where(Game.id == game_id))
        game = result.scalar_one_or_none()

        if not game:
            print(f"Game {game_id} not found!")
            await engine.dispose()
            return

        print(f"Found game: seed={game.seed}")

        zone_links = game.zone_links or []
        print(f"Zone links: {len(zone_links)}")

        # Step 1: Add UUIDs to zone_links
        zl_updated = 0
        for zl in zone_links:
            if not zl.get("id"):
                zl["id"] = str(uuid4())
                zl_updated += 1
        print(f"Added UUIDs to {zl_updated} zone_links")

        # Step 2: Build index by endpoints (both directions for bidirectional links)
        zl_by_endpoints: dict[tuple[str, str], list[dict]] = {}
        for zl in zone_links:
            src = zl.get("source", "")
            dst = zl.get("target", "")
            # Index by (source, target)
            key = (src, dst)
            if key not in zl_by_endpoints:
                zl_by_endpoints[key] = []
            zl_by_endpoints[key].append(zl)

        # Step 3: Match localStorage discoveredLinks to zone_links
        now = datetime.now(UTC).isoformat()
        new_discovered_zone_links = []
        seen_link_ids = set()
        not_found = []

        for link_str in LOCALSTORAGE_DATA["discoveredLinks"]:
            parts = link_str.split("|")
            if len(parts) != 2:
                print(f"  Warning: Invalid link format: {link_str}")
                continue

            source, target = parts

            # Try both directions
            matching_zls = zl_by_endpoints.get((source, target), [])
            if not matching_zls:
                matching_zls = zl_by_endpoints.get((target, source), [])

            if not matching_zls:
                not_found.append(link_str)
                continue

            # Add all matching zone_links (handles parallel links)
            for zl in matching_zls:
                link_id = zl.get("id")
                if link_id and link_id not in seen_link_ids:
                    new_discovered_zone_links.append(
                        {
                            "zone_link_id": link_id,
                            "discovered_at": now,
                            "discovered_by": "restored",
                        }
                    )
                    seen_link_ids.add(link_id)

        print(f"Matched {len(new_discovered_zone_links)} links from localStorage")
        if not_found:
            print(f"Links not found in zone_links ({len(not_found)}):")
            for link in not_found:
                print(f"  - {link}")

        # Step 4: Update game
        if not dry_run:
            # Deep copy and flag_modified to force SQLAlchemy to detect changes
            import copy

            from sqlalchemy.orm.attributes import flag_modified

            game.zone_links = copy.deepcopy(zone_links)
            game.discovered_zone_links = new_discovered_zone_links
            flag_modified(game, "zone_links")
            flag_modified(game, "discovered_zone_links")
            await session.commit()
            print("Changes committed to database.")
        else:
            print("Dry run - no changes made.")

    await engine.dispose()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m scripts.restore_from_localstorage <game_id> [--dry-run]")
        sys.exit(1)

    game_id = sys.argv[1]
    dry_run = "--dry-run" in sys.argv

    asyncio.run(restore_game(game_id, dry_run))
