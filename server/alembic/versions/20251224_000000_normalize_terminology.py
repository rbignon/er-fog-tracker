"""Normalize terminology: zone_pairs->zone_links, add zone UUIDs

Revision ID: 007
Revises: 0eb029deb81c
Create Date: 2025-12-24

This migration:
1. Renames zone_pairs -> zone_links
2. Renames discovered_links -> discovered_zone_links
3. Transforms zones: id (name) -> id (UUID) + name
4. Transforms zone_links: destination -> target, adds source_id/target_id
5. Transforms discovered_zone_links: link_id -> zone_link_id, removes source/target
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "007"
down_revision: str | None = "0eb029deb81c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Step 1: Rename columns
    op.alter_column("games", "zone_pairs", new_column_name="zone_links")
    op.alter_column("games", "discovered_links", new_column_name="discovered_zone_links")

    # Step 2: Transform zones - add UUID, rename id -> name
    # This is done in a single UPDATE using a subquery that generates UUIDs
    op.execute("""
        UPDATE games SET zones = (
            SELECT COALESCE(jsonb_agg(
                jsonb_build_object(
                    'id', gen_random_uuid()::text,
                    'name', zone->>'id',
                    'is_boss', COALESCE((zone->>'is_boss')::boolean, false),
                    'scaling', zone->'scaling'
                )
            ), '[]'::jsonb)
            FROM jsonb_array_elements(zones) AS zone
        )
        WHERE zones IS NOT NULL AND jsonb_array_length(zones) > 0
    """)

    # Step 3: Transform zone_links
    # - destination -> target
    # - destination_key -> target_key
    # - Add source_id and target_id by looking up zone UUIDs
    # This requires a more complex query to join zones
    op.execute("""
        UPDATE games SET zone_links = (
            SELECT COALESCE(jsonb_agg(
                jsonb_build_object(
                    'id', link->>'id',
                    'source', link->>'source',
                    'source_id', (
                        SELECT z->>'id'
                        FROM jsonb_array_elements(zones) AS z
                        WHERE z->>'name' = link->>'source'
                        LIMIT 1
                    ),
                    'source_key', link->'source_key',
                    'target', link->>'destination',
                    'target_id', (
                        SELECT z->>'id'
                        FROM jsonb_array_elements(zones) AS z
                        WHERE z->>'name' = link->>'destination'
                        LIMIT 1
                    ),
                    'target_key', link->'destination_key',
                    'type', link->>'type',
                    'source_details', link->'source_details',
                    'target_details', link->'target_details',
                    'is_inherently_one_way', COALESCE((link->>'is_inherently_one_way')::boolean, false)
                )
            ), '[]'::jsonb)
            FROM jsonb_array_elements(zone_links) AS link
        )
        WHERE zone_links IS NOT NULL AND jsonb_array_length(zone_links) > 0
    """)

    # Step 4: Transform discovered_zone_links
    # - link_id -> zone_link_id
    # - Remove source/target (they were redundant)
    op.execute("""
        UPDATE games SET discovered_zone_links = (
            SELECT COALESCE(jsonb_agg(
                jsonb_build_object(
                    'zone_link_id', dl->>'link_id',
                    'discovered_at', dl->>'discovered_at',
                    'discovered_by', dl->>'discovered_by'
                )
            ), '[]'::jsonb)
            FROM jsonb_array_elements(discovered_zone_links) AS dl
        )
        WHERE discovered_zone_links IS NOT NULL AND jsonb_array_length(discovered_zone_links) > 0
    """)


def downgrade() -> None:
    # Step 1: Transform discovered_zone_links back
    # - zone_link_id -> link_id
    # - Re-add source/target from zone_links lookup
    op.execute("""
        UPDATE games SET discovered_zone_links = (
            SELECT COALESCE(jsonb_agg(
                jsonb_build_object(
                    'link_id', dl->>'zone_link_id',
                    'source', (
                        SELECT link->>'source'
                        FROM jsonb_array_elements(zone_links) AS link
                        WHERE link->>'id' = dl->>'zone_link_id'
                        LIMIT 1
                    ),
                    'target', (
                        SELECT link->>'target'
                        FROM jsonb_array_elements(zone_links) AS link
                        WHERE link->>'id' = dl->>'zone_link_id'
                        LIMIT 1
                    ),
                    'discovered_at', dl->>'discovered_at',
                    'discovered_by', dl->>'discovered_by'
                )
            ), '[]'::jsonb)
            FROM jsonb_array_elements(discovered_zone_links) AS dl
        )
        WHERE discovered_zone_links IS NOT NULL AND jsonb_array_length(discovered_zone_links) > 0
    """)

    # Step 2: Transform zone_links back
    # - target -> destination
    # - target_key -> destination_key
    # - Remove source_id/target_id
    op.execute("""
        UPDATE games SET zone_links = (
            SELECT COALESCE(jsonb_agg(
                jsonb_build_object(
                    'id', link->>'id',
                    'source', link->>'source',
                    'source_key', link->'source_key',
                    'destination', link->>'target',
                    'destination_key', link->'target_key',
                    'type', link->>'type',
                    'source_details', link->'source_details',
                    'target_details', link->'target_details',
                    'is_inherently_one_way', COALESCE((link->>'is_inherently_one_way')::boolean, false)
                )
            ), '[]'::jsonb)
            FROM jsonb_array_elements(zone_links) AS link
        )
        WHERE zone_links IS NOT NULL AND jsonb_array_length(zone_links) > 0
    """)

    # Step 3: Transform zones back - UUID id -> name as id
    op.execute("""
        UPDATE games SET zones = (
            SELECT COALESCE(jsonb_agg(
                jsonb_build_object(
                    'id', zone->>'name',
                    'is_boss', COALESCE((zone->>'is_boss')::boolean, false),
                    'scaling', zone->'scaling'
                )
            ), '[]'::jsonb)
            FROM jsonb_array_elements(zones) AS zone
        )
        WHERE zones IS NOT NULL AND jsonb_array_length(zones) > 0
    """)

    # Step 4: Rename columns back
    op.alter_column("games", "zone_links", new_column_name="zone_pairs")
    op.alter_column("games", "discovered_zone_links", new_column_name="discovered_links")
