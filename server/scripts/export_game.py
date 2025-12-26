#!/usr/bin/env python3
"""
Export game data (zone_links, zones, entity_mapping, discovered_zone_links) to JSON files.

Usage:
    cd server
    python scripts/export_game.py <game_uuid> [--output-dir <path>]

Outputs:
    <output_dir>/zone_links.json
    <output_dir>/zones.json
    <output_dir>/entity_mapping.json
    <output_dir>/discovered_zone_links.json

If --output-dir is not specified, defaults to analysis/seeds/<seed>/
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Change to server directory so pydantic-settings finds .env
server_dir = Path(__file__).parent.parent
os.chdir(server_dir)

# Add server dir to path for imports
sys.path.insert(0, str(server_dir))

from fogvizu.config import settings  # noqa: E402
from fogvizu.database import Game  # noqa: E402


async def export_game(game_id: str, output_dir: Path | None = None) -> Path:
    """Export game data to JSON files.

    Returns the output directory path.
    """
    try:
        game_uuid = UUID(game_id)
    except ValueError:
        print(f"Error: Invalid UUID format: {game_id}")
        sys.exit(1)

    engine = create_async_engine(settings.database_url, echo=False)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        game = (
            await session.execute(select(Game).where(Game.id == game_uuid))
        ).scalar_one_or_none()

        if game is None:
            print(f"Error: Game not found: {game_id}")
            await engine.dispose()
            sys.exit(1)

        seed = game.seed
        print(f"Found game with seed: {seed}")

        # Determine output directory
        if output_dir is None:
            output_dir = Path("..") / "analysis" / "seeds" / str(seed)

        output_dir.mkdir(parents=True, exist_ok=True)
        print(f"Output directory: {output_dir}")

        # Export zone_links
        zone_links_file = output_dir / "zone_links.json"
        with open(zone_links_file, "w") as f:
            json.dump(game.zone_links, f, indent=2)
        print(f"Exported: {zone_links_file}")

        # Export zones
        zones_file = output_dir / "zones.json"
        with open(zones_file, "w") as f:
            json.dump(game.zones, f, indent=2)
        print(f"Exported: {zones_file}")

        # Export entity_mapping
        entity_mapping_file = output_dir / "entity_mapping.json"
        with open(entity_mapping_file, "w") as f:
            json.dump(game.entity_mapping, f, indent=2)
        print(f"Exported: {entity_mapping_file}")

        # Export discovered_zone_links
        discovered_zone_links_file = output_dir / "discovered_zone_links.json"
        with open(discovered_zone_links_file, "w") as f:
            json.dump(game.discovered_zone_links, f, indent=2)
        print(f"Exported: {discovered_zone_links_file}")

    await engine.dispose()
    return output_dir


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export game data to JSON files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("game_id", help="Game UUID")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Output directory (default: analysis/seeds/<seed>/)",
    )

    args = parser.parse_args()
    asyncio.run(export_game(args.game_id, args.output_dir))


if __name__ == "__main__":
    main()
