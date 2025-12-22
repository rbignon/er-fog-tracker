"""remove_run_id

Revision ID: 0eb029deb81c
Revises: 006
Create Date: 2025-12-22 18:33:17.510961

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0eb029deb81c"
down_revision: str | None = "006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop the unique index first
    op.drop_index("idx_games_unique_run", table_name="games")
    # Drop the run_id column
    op.drop_column("games", "run_id")


def downgrade() -> None:
    # Add back the run_id column
    op.add_column("games", sa.Column("run_id", sa.String(100), nullable=True))
    # Populate with a placeholder value for existing rows
    op.execute("UPDATE games SET run_id = 'legacy_' || id::text WHERE run_id IS NULL")
    # Make it non-nullable
    op.alter_column("games", "run_id", nullable=False)
    # Recreate the unique index
    op.create_index("idx_games_unique_run", "games", ["user_id", "seed", "run_id"], unique=True)
