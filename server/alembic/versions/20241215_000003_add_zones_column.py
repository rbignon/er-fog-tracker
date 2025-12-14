"""Add zones column to games table.

Revision ID: 004
Revises: 003
Create Date: 2024-12-15
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("games", sa.Column("zones", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("games", "zones")
