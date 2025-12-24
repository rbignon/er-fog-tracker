"""Add indexes for seed and updated_at

Revision ID: 008
Revises: 007
Create Date: 2025-12-24

This migration adds indexes to improve query performance:
- idx_games_seed: For seed-based lookups
- idx_games_user_updated: For user game listings sorted by updated_at
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "008"
down_revision: str | None = "007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("idx_games_seed", "games", ["seed"])
    op.create_index(
        "idx_games_user_updated",
        "games",
        ["user_id", "updated_at"],
        postgresql_ops={"updated_at": "DESC"},
    )


def downgrade() -> None:
    op.drop_index("idx_games_user_updated", table_name="games")
    op.drop_index("idx_games_seed", table_name="games")
