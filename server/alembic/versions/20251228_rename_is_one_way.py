"""Rename is_inherently_one_way to is_one_way in zone_links JSONB.

Revision ID: 20251228_rename_is_one_way
Revises: 008
Create Date: 2025-12-28

This simplifies the naming now that we've unified the one-way logic
for both random and preexisting links.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "20251228_rename_is_one_way"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Rename is_inherently_one_way -> is_one_way in zone_links JSONB
    op.execute("""
        UPDATE games SET zone_links = (
            SELECT COALESCE(jsonb_agg(
                (link - 'is_inherently_one_way') ||
                jsonb_build_object('is_one_way', COALESCE((link->>'is_inherently_one_way')::boolean, false))
            ), '[]'::jsonb)
            FROM jsonb_array_elements(zone_links) AS link
        )
        WHERE zone_links IS NOT NULL AND jsonb_array_length(zone_links) > 0
    """)


def downgrade() -> None:
    # Rename is_one_way -> is_inherently_one_way in zone_links JSONB
    op.execute("""
        UPDATE games SET zone_links = (
            SELECT COALESCE(jsonb_agg(
                (link - 'is_one_way') ||
                jsonb_build_object('is_inherently_one_way', COALESCE((link->>'is_one_way')::boolean, false))
            ), '[]'::jsonb)
            FROM jsonb_array_elements(zone_links) AS link
        )
        WHERE zone_links IS NOT NULL AND jsonb_array_length(zone_links) > 0
    """)
