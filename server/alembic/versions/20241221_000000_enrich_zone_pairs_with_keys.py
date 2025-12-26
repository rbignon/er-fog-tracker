"""Enrich zone_pairs with source_key/destination_key from fog.txt.

This is a data migration that adds zone_keys to existing games for
more precise fog gate matching.

Revision ID: 005
Revises: 004
Create Date: 2024-12-21
"""

import json
import logging

from sqlalchemy import text

from alembic import op

# revision identifiers, used by Alembic.
revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None

logger = logging.getLogger(__name__)


def upgrade() -> None:
    """Enrich all existing zone_pairs with zone_keys."""
    # Import here to avoid circular imports and ensure fresh resolver
    from fogtracker.zone_resolver import ZoneResolver

    conn = op.get_bind()

    # Load the zone resolver
    resolver = ZoneResolver()

    # Fetch all games with their zone_pairs
    result = conn.execute(
        text("SELECT id, zone_pairs FROM games WHERE zone_pairs IS NOT NULL AND deleted_at IS NULL")
    )
    games = result.fetchall()

    logger.info("Enriching zone_pairs for %d games...", len(games))

    enriched_count = 0
    for game_id, zone_pairs in games:
        if not zone_pairs:
            continue

        # Always re-enrich to fix any incorrect keys from previous runs
        # Enrich each zone_pair
        updated = False
        for zp in zone_pairs:
            source_key = None
            destination_key = None

            # Try to resolve source_key from source_details
            if zp.get("source_details"):
                zone_key, display_name = resolver.lookup_by_detail_text(zp["source_details"])
                # Only use if the display_name matches the expected source
                if zone_key and display_name and display_name == zp.get("source"):
                    source_key = zone_key

            # Fallback: display_name -> zone_key
            if not source_key and zp.get("source"):
                source_key = resolver.lookup_by_display_name(zp["source"])

            # Try to resolve destination_key from target_details
            if zp.get("target_details"):
                zone_key, display_name = resolver.lookup_by_detail_text(zp["target_details"])
                # Only use if the display_name matches the expected target
                if zone_key and display_name and display_name == zp.get("destination"):
                    destination_key = zone_key

            # Fallback: display_name -> zone_key
            if not destination_key and zp.get("destination"):
                destination_key = resolver.lookup_by_display_name(zp["destination"])

            # Update the zone_pair
            if source_key or destination_key:
                zp["source_key"] = source_key
                zp["destination_key"] = destination_key
                updated = True

        if updated:
            # Update the game in database
            conn.execute(
                text(
                    "UPDATE games SET zone_pairs = :zone_pairs::jsonb, updated_at = NOW() WHERE id = :game_id"
                ),
                {"zone_pairs": json.dumps(zone_pairs), "game_id": game_id},
            )
            enriched_count += 1
            logger.debug("Enriched game %s", game_id)

    logger.info("Enriched %d games with zone_keys", enriched_count)


def downgrade() -> None:
    """Remove zone_keys from zone_pairs."""
    conn = op.get_bind()

    # Fetch all games
    result = conn.execute(
        text("SELECT id, zone_pairs FROM games WHERE zone_pairs IS NOT NULL AND deleted_at IS NULL")
    )
    games = result.fetchall()

    logger.info("Removing zone_keys from %d games...", len(games))

    for game_id, zone_pairs in games:
        if not zone_pairs:
            continue

        # Remove source_key and destination_key from each zone_pair
        updated = False
        for zp in zone_pairs:
            if "source_key" in zp:
                del zp["source_key"]
                updated = True
            if "destination_key" in zp:
                del zp["destination_key"]
                updated = True

        if updated:
            conn.execute(
                text(
                    "UPDATE games SET zone_pairs = :zone_pairs::jsonb, updated_at = NOW() WHERE id = :game_id"
                ),
                {"zone_pairs": json.dumps(zone_pairs), "game_id": game_id},
            )

    logger.info("Removed zone_keys from games")
