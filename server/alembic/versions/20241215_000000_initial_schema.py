"""Initial schema (simplified with JSONB)

Revision ID: 001
Revises:
Create Date: 2024-12-15 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Users table
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("twitch_id", sa.String(50), nullable=False),
        sa.Column("twitch_username", sa.String(100), nullable=False),
        sa.Column("twitch_display_name", sa.String(100), nullable=True),
        sa.Column("api_token", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("twitch_id"),
        sa.UniqueConstraint("api_token"),
    )
    op.create_index("idx_users_twitch_username", "users", ["twitch_username"])
    op.create_index("idx_users_api_token", "users", ["api_token"])

    # Games table (with JSONB columns for state)
    op.create_table(
        "games",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("seed", sa.BigInteger(), nullable=False),
        sa.Column("run_id", sa.String(100), nullable=False),
        sa.Column("label", sa.String(200), nullable=True),
        sa.Column("zone_pairs", postgresql.JSONB(), nullable=False),
        # State columns (JSONB)
        sa.Column("discovered_links", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("node_positions", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("tags", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_games_user_id", "games", ["user_id"])
    op.create_index(
        "idx_games_not_deleted",
        "games",
        ["user_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "idx_games_unique_run",
        "games",
        ["user_id", "seed", "run_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("games")
    op.drop_table("users")
