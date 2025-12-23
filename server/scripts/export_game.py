#!/usr/bin/env python3
"""
Export game data (zone_pairs, zones, entity_mapping) to JSON files.

Usage:
    cd server
    python scripts/export_game.py <game_uuid>

Outputs:
    <seed>/zone_pairs.json
    <seed>/zones.json
    <seed>/entity_mapping.json
"""

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


async def export_game(game_id: str) -> None:
    """Export game data to JSON files."""
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

        # Create output directory
        output_dir = Path(str(seed))
        output_dir.mkdir(exist_ok=True)
        print(f"Created directory: {output_dir}")

        # Export zone_pairs
        zone_pairs_file = output_dir / "zone_pairs.json"
        with open(zone_pairs_file, "w") as f:
            json.dump(game.zone_pairs, f, indent=2)
        print(f"Exported: {zone_pairs_file}")

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

    await engine.dispose()


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python scripts/export_game.py <game_uuid>")
        print("Example: python scripts/export_game.py 123e4567-e89b-12d3-a456-426614174000")
        sys.exit(1)

    asyncio.run(export_game(sys.argv[1]))


if __name__ == "__main__":
    main()
