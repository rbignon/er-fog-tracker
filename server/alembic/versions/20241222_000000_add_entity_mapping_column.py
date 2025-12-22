"""Add entity_mapping column to games table.

Stores EMEVD entity mapping from launcher for improved fog gate resolution.
Maps destination entity IDs (755890xxx) to source/dest maps.

Revision ID: 006
Revises: 005
Create Date: 2024-12-22
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("games", sa.Column("entity_mapping", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("games", "entity_mapping")
