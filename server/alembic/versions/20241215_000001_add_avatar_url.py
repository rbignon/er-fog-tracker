"""Add twitch_avatar_url column to users table.

Revision ID: 002
Revises: 001
Create Date: 2024-12-15

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("twitch_avatar_url", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "twitch_avatar_url")
