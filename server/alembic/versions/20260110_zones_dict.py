"""Store games.zones as dict keyed by zone_id and make it non-nullable.

Revision ID: 20260110_zones_dict
Revises: 20260105_zone_key_migration
Create Date: 2026-01-10
"""

import json
import logging

from sqlalchemy import text

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260110_zones_dict"
down_revision = "20260105_zone_key_migration"
branch_labels = None
depends_on = None

logger = logging.getLogger(__name__)


def _normalize_zones(zones_json, zone_links_json):
    if zones_json:
        zones = zones_json if isinstance(zones_json, list | dict) else json.loads(zones_json)
    else:
        zones = {}

    zones_by_id = {}
    if isinstance(zones, dict):
        zones_by_id.update(zones)
    else:
        for zone in zones:
            zone_id = zone.get("id")
            if zone_id:
                zones_by_id[zone_id] = zone

    zone_links = (
        zone_links_json
        if isinstance(zone_links_json, list)
        else json.loads(zone_links_json or "[]")
    )
    for link in zone_links or []:
        for zone_id_key, zone_name_key in (("source_id", "source"), ("target_id", "target")):
            zone_id = link.get(zone_id_key)
            if zone_id and zone_id not in zones_by_id:
                zones_by_id[zone_id] = {
                    "id": zone_id,
                    "name": link.get(zone_name_key),
                    "is_boss": False,
                    "scaling": None,
                }

    return zones_by_id


def upgrade() -> None:
    """Convert zones list to dict and enforce non-null."""
    conn = op.get_bind()
    result = conn.execute(text("SELECT id, zones, zone_links FROM games WHERE deleted_at IS NULL"))
    games = result.fetchall()

    logger.info("Migrating %d games to zones dict format...", len(games))

    for game_id, zones_json, zone_links_json in games:
        zones_by_id = _normalize_zones(zones_json, zone_links_json)
        conn.execute(
            text("UPDATE games SET zones = :zones WHERE id = :id"),
            {"zones": json.dumps(zones_by_id), "id": game_id},
        )

    op.execute("UPDATE games SET zones = '{}'::jsonb WHERE zones IS NULL")
    op.execute("ALTER TABLE games ALTER COLUMN zones SET NOT NULL")

    logger.info("zones dict migration completed successfully")


def downgrade() -> None:
    """Revert zones dict back to list and allow nulls."""
    conn = op.get_bind()
    result = conn.execute(text("SELECT id, zones FROM games WHERE deleted_at IS NULL"))
    games = result.fetchall()

    for game_id, zones_json in games:
        if zones_json is None:
            zones_list = None
        else:
            zones = zones_json if isinstance(zones_json, list | dict) else json.loads(zones_json)
            zones_list = list(zones.values()) if isinstance(zones, dict) else zones

        conn.execute(
            text("UPDATE games SET zones = :zones WHERE id = :id"),
            {"zones": json.dumps(zones_list) if zones_list is not None else None, "id": game_id},
        )

    op.execute("ALTER TABLE games ALTER COLUMN zones DROP NOT NULL")
