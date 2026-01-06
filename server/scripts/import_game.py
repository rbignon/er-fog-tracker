#!/usr/bin/env python3
"""
Import game data from JSON files.

Usage:
    cd server
    python scripts/import_game.py <input_dir> --user-id <user_id>
    python scripts/import_game.py <input_dir> --game-id <game_uuid>

Modes:
    --user-id: Create a new game for the specified user
    --game-id: Update an existing game

Expected input files:
    <input_dir>/game_info.json       (optional: seed, label, starting_zone_id, tags, node_positions)
    <input_dir>/zone_links.json      (required)
    <input_dir>/zones.json           (optional)
    <input_dir>/entity_mapping.json  (optional)
    <input_dir>/discovered_zone_links.json (optional, defaults to [])

CLI options --seed and --label override values from game_info.json.
"""

import argparse
import asyncio
import contextlib
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

from fogtracker.config import settings  # noqa: E402
from fogtracker.database import Game, User  # noqa: E402


def load_json_file(file_path: Path, required: bool = True) -> dict | list | None:
    """Load a JSON file, returning None if optional and not found."""
    if not file_path.exists():
        if required:
            print(f"Error: Required file not found: {file_path}")
            sys.exit(1)
        return None

    with open(file_path) as f:
        return json.load(f)


def extract_seed_from_zone_links(zone_links: list) -> int:
    """Try to extract seed from zone_links metadata, or return 0."""
    # Some zone_links exports include metadata with the seed
    # This is a best-effort extraction
    if isinstance(zone_links, list) and len(zone_links) > 0:
        first_link = zone_links[0]
        if isinstance(first_link, dict) and "seed" in first_link:
            return int(first_link["seed"])
    return 0


async def import_game_new(
    input_dir: Path,
    user_id: int,
    seed: int | None = None,
    label: str | None = None,
    dry_run: bool = False,
) -> UUID:
    """Import game data by creating a new game for a user.

    Returns the new game UUID.
    """
    # Load game_info (metadata) if present
    game_info = load_json_file(input_dir / "game_info.json", required=False) or {}

    # Load required files
    zone_links = load_json_file(input_dir / "zone_links.json", required=True)

    # Load optional files
    zones = load_json_file(input_dir / "zones.json", required=False)
    entity_mapping = load_json_file(input_dir / "entity_mapping.json", required=False)
    discovered_zone_links = load_json_file(input_dir / "discovered_zone_links.json", required=False)

    # Determine seed (CLI > game_info > heuristics)
    if seed is None:
        seed = game_info.get("seed")
    if seed is None:
        seed = extract_seed_from_zone_links(zone_links)
        if seed == 0:
            # Try to get seed from directory name (analysis/seeds/<seed>/ pattern)
            with contextlib.suppress(ValueError):
                seed = int(input_dir.name)

    # Determine label (CLI > game_info)
    if label is None:
        label = game_info.get("label")

    print(f"Using seed: {seed}")

    engine = create_async_engine(settings.database_url, echo=False)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # Verify user exists
        user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if user is None:
            print(f"Error: User not found: {user_id}")
            await engine.dispose()
            sys.exit(1)

        # Create new game
        game = Game(
            user_id=user_id,
            seed=seed,
            label=label,
            starting_zone_id=game_info.get("starting_zone_id"),
            zone_links=zone_links,
            zones=zones,
            entity_mapping=entity_mapping,
            discovered_zone_links=discovered_zone_links or [],
            node_positions=game_info.get("node_positions") or {},
            tags=game_info.get("tags") or {},
        )

        if dry_run:
            print(f"Dry run - would create game with seed {seed}")
            await engine.dispose()
            return game.id

        session.add(game)
        await session.commit()

        game_id = game.id
        print(f"Created new game: {game_id}")

    await engine.dispose()
    return game_id


async def import_game_update(input_dir: Path, game_id: str, dry_run: bool = False) -> UUID:
    """Import game data by updating an existing game.

    Returns the game UUID.
    """
    try:
        game_uuid = UUID(game_id)
    except ValueError:
        print(f"Error: Invalid UUID format: {game_id}")
        sys.exit(1)

    # Load game_info (metadata) if present
    game_info = load_json_file(input_dir / "game_info.json", required=False) or {}

    # Load required files
    zone_links = load_json_file(input_dir / "zone_links.json", required=True)

    # Load optional files
    zones = load_json_file(input_dir / "zones.json", required=False)
    entity_mapping = load_json_file(input_dir / "entity_mapping.json", required=False)
    discovered_zone_links = load_json_file(input_dir / "discovered_zone_links.json", required=False)

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

        print(f"Updating game {game_id} (seed: {game.seed})")

        # Update data fields
        game.zone_links = zone_links
        if zones is not None:
            game.zones = zones
        if entity_mapping is not None:
            game.entity_mapping = entity_mapping
        if discovered_zone_links is not None:
            game.discovered_zone_links = discovered_zone_links

        # Update metadata from game_info if present
        if "label" in game_info:
            game.label = game_info["label"]
        if "starting_zone_id" in game_info:
            game.starting_zone_id = game_info["starting_zone_id"]
        if "tags" in game_info:
            game.tags = game_info["tags"]
        if "node_positions" in game_info:
            game.node_positions = game_info["node_positions"]

        if dry_run:
            print(f"Dry run - would update game {game_uuid}")
            await engine.dispose()
            return game_uuid

        await session.commit()
        print(f"Updated game: {game_uuid}")

    await engine.dispose()
    return game_uuid


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import game data from JSON files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("input_dir", type=Path, help="Input directory with JSON files")

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--user-id",
        type=int,
        help="Create a new game for this user ID",
    )
    group.add_argument(
        "--game-id",
        type=str,
        help="Update an existing game with this UUID",
    )

    parser.add_argument(
        "--seed",
        type=int,
        help="Seed for the game (only for --user-id mode, auto-detected if not specified)",
    )
    parser.add_argument(
        "--label",
        type=str,
        help="Label for the game (only for --user-id mode)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate only, do not write to database",
    )

    args = parser.parse_args()

    if not args.input_dir.is_dir():
        print(f"Error: Input directory does not exist: {args.input_dir}")
        sys.exit(1)

    if args.user_id is not None:
        asyncio.run(
            import_game_new(
                args.input_dir,
                args.user_id,
                seed=args.seed,
                label=args.label,
                dry_run=args.dry_run,
            )
        )
    else:
        if args.seed is not None:
            print("Warning: --seed is ignored in update mode")
        if args.label is not None:
            print("Warning: --label is ignored in update mode")
        asyncio.run(import_game_update(args.input_dir, args.game_id, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
