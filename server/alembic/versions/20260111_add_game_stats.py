"""Add game_stats JSONB column for tracking player statistics.

Revision ID: 20260111_add_game_stats
Revises: 20260110_zones_dict
Create Date: 2026-01-11
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260111_add_game_stats"
down_revision = "20260110_zones_dict"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add game_stats column with default empty object."""
    op.add_column(
        "games",
        sa.Column(
            "game_stats",
            JSONB,
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade() -> None:
    """Remove game_stats column."""
    op.drop_column("games", "game_stats")
