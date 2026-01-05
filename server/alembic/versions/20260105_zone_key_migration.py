"""Migrate from UUIDs to zone_keys as primary zone identifiers.

This migration:
1. Adds starting_zone_id column (backfilled with 'chapel_start')
2. Migrates zones[].id from UUID to zone_key
3. Migrates zone_links: source_key → source_id, target_key → target_id
4. Migrates node_positions keys: display_name → zone_key
5. Migrates tags keys: display_name → zone_key
6. Validates migration integrity

Revision ID: 20260105_zone_key_migration
Revises: 20251228_rename_is_one_way
Create Date: 2026-01-05
"""

import json
import logging
import re

from sqlalchemy import text

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260105_zone_key_migration"
down_revision = "20251228_rename_is_one_way"
branch_labels = None
depends_on = None

logger = logging.getLogger(__name__)

# UUID pattern for validation
UUID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def upgrade() -> None:
    """Migrate from UUIDs to zone_keys."""
    from fogtracker.zone_resolver import ZoneResolver

    conn = op.get_bind()
    resolver = ZoneResolver()

    # 1. Add starting_zone_id column
    op.execute("ALTER TABLE games ADD COLUMN IF NOT EXISTS starting_zone_id VARCHAR(100)")

    # 2. Backfill starting_zone_id with 'chapel_start' for existing games
    op.execute("""
        UPDATE games SET starting_zone_id = 'chapel_start'
        WHERE starting_zone_id IS NULL
    """)

    # 3. Migrate zones[].id and zone_links (requires Python for resolver lookup)
    result = conn.execute(text("SELECT id, zones, zone_links FROM games WHERE deleted_at IS NULL"))
    games = result.fetchall()

    logger.info("Migrating %d games to zone_key identifiers...", len(games))

    migration_errors = []

    for game_id, zones_json, zone_links_json in games:
        # Migrate zones[].id from UUID to zone_key
        if zones_json:
            zones = zones_json if isinstance(zones_json, list) else json.loads(zones_json)
            for zone in zones:
                zone_name = zone.get("name")
                if not zone_name:
                    continue

                zone_key = resolver.lookup_by_display_name(zone_name)
                if not zone_key:
                    migration_errors.append(
                        f"Game {game_id}: Zone '{zone_name}' not found in fog.txt"
                    )
                    continue

                zone["id"] = zone_key

            # Update zones in database
            conn.execute(
                text("UPDATE games SET zones = :zones WHERE id = :id"),
                {"zones": json.dumps(zones), "id": game_id},
            )

        # Migrate zone_links: source_key → source_id, target_key → target_id
        if zone_links_json:
            zone_links = (
                zone_links_json
                if isinstance(zone_links_json, list)
                else json.loads(zone_links_json)
            )
            for link in zone_links:
                # Copy source_key to source_id if source_key exists
                if link.get("source_key"):
                    link["source_id"] = link.pop("source_key")
                # Copy target_key to target_id if target_key exists
                if link.get("target_key"):
                    link["target_id"] = link.pop("target_key")

            # Update zone_links in database
            conn.execute(
                text("UPDATE games SET zone_links = :zone_links WHERE id = :id"),
                {"zone_links": json.dumps(zone_links), "id": game_id},
            )

    # 4. Migrate node_positions keys: display_name → zone_key
    # Uses the zones array to build the mapping
    op.execute("""
        UPDATE games SET node_positions = (
            SELECT COALESCE(
                jsonb_object_agg(
                    (SELECT zone->>'id'
                     FROM jsonb_array_elements(zones) AS zone
                     WHERE zone->>'name' = pos.key),
                    pos.value
                ) FILTER (WHERE (SELECT zone->>'id'
                                 FROM jsonb_array_elements(zones) AS zone
                                 WHERE zone->>'name' = pos.key) IS NOT NULL),
                '{}'::jsonb
            )
            FROM jsonb_each(node_positions) AS pos
        )
        WHERE node_positions IS NOT NULL
          AND node_positions != '{}'::jsonb
          AND zones IS NOT NULL
    """)

    # 5. Migrate tags keys: display_name → zone_key
    op.execute("""
        UPDATE games SET tags = (
            SELECT COALESCE(
                jsonb_object_agg(
                    (SELECT zone->>'id'
                     FROM jsonb_array_elements(zones) AS zone
                     WHERE zone->>'name' = tag.key),
                    tag.value
                ) FILTER (WHERE (SELECT zone->>'id'
                                 FROM jsonb_array_elements(zones) AS zone
                                 WHERE zone->>'name' = tag.key) IS NOT NULL),
                '{}'::jsonb
            )
            FROM jsonb_each(tags) AS tag
        )
        WHERE tags IS NOT NULL
          AND tags != '{}'::jsonb
          AND zones IS NOT NULL
    """)

    # 6. Post-migration validation
    validation_errors = _validate_migration(conn)
    migration_errors.extend(validation_errors)

    if migration_errors:
        for error in migration_errors:
            logger.error(error)
        raise RuntimeError(
            f"Migration validation failed with {len(migration_errors)} errors. "
            "Check logs for details. Fix fog.txt or data before retrying."
        )

    logger.info("Migration completed successfully")


def _validate_migration(conn):
    """Validate migration integrity. Returns list of error messages."""
    errors = []

    # Check for orphan node_positions keys (keys not matching any zone_id)
    result = conn.execute(
        text("""
        SELECT g.id, pos.key
        FROM games g, jsonb_each(g.node_positions) AS pos
        WHERE g.zones IS NOT NULL
          AND g.deleted_at IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM jsonb_array_elements(g.zones) AS zone
              WHERE zone->>'id' = pos.key
          )
    """)
    )
    for game_id, orphan_key in result:
        errors.append(f"Game {game_id}: Orphan node_positions key '{orphan_key}'")

    # Check for orphan tags keys
    result = conn.execute(
        text("""
        SELECT g.id, tag.key
        FROM games g, jsonb_each(g.tags) AS tag
        WHERE g.zones IS NOT NULL
          AND g.deleted_at IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM jsonb_array_elements(g.zones) AS zone
              WHERE zone->>'id' = tag.key
          )
    """)
    )
    for game_id, orphan_key in result:
        errors.append(f"Game {game_id}: Orphan tags key '{orphan_key}'")

    # Check for zones with UUID-like IDs (should all be zone_keys now)
    result = conn.execute(
        text("""
        SELECT g.id, zone->>'id' as zone_id, zone->>'name' as zone_name
        FROM games g, jsonb_array_elements(g.zones) AS zone
        WHERE g.zones IS NOT NULL
          AND g.deleted_at IS NULL
          AND zone->>'id' ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    """)
    )
    for game_id, zone_id, zone_name in result:
        errors.append(f"Game {game_id}: Zone '{zone_name}' still has UUID '{zone_id}'")

    # Check that zone_links don't have source_key/target_key anymore
    result = conn.execute(
        text("""
        SELECT g.id, link->>'source_key' as source_key, link->>'target_key' as target_key
        FROM games g, jsonb_array_elements(g.zone_links) AS link
        WHERE g.zone_links IS NOT NULL
          AND g.deleted_at IS NULL
          AND (link->>'source_key' IS NOT NULL OR link->>'target_key' IS NOT NULL)
        LIMIT 10
    """)
    )
    for game_id, source_key, target_key in result:
        errors.append(
            f"Game {game_id}: zone_link still has source_key={source_key}, target_key={target_key}"
        )

    return errors


def downgrade() -> None:
    """Revert to UUID-based identifiers.

    Note: This downgrade does NOT restore UUIDs - it only reverts the schema.
    The zone IDs will remain as zone_keys (which is fine for display purposes).
    A full restoration would require regenerating UUIDs, which is not reversible.
    """
    # Revert zone_links: source_id → source_key, target_id → target_key
    op.execute("""
        UPDATE games SET zone_links = (
            SELECT COALESCE(jsonb_agg(
                link ||
                jsonb_build_object(
                    'source_key', link->>'source_id',
                    'target_key', link->>'target_id'
                )
            ), '[]'::jsonb)
            FROM jsonb_array_elements(zone_links) AS link
        )
        WHERE zone_links IS NOT NULL AND jsonb_array_length(zone_links) > 0
    """)

    # Note: node_positions and tags keys are NOT reverted as we don't have
    # a reliable mapping from zone_key back to display_name in this context.
    # The application code should handle both formats during transition.

    # Remove starting_zone_id column
    op.execute("ALTER TABLE games DROP COLUMN IF EXISTS starting_zone_id")

    logger.info("Downgrade completed. Note: zone IDs remain as zone_keys.")
