"""Add mod_token column to users table.

Revision ID: 003
Revises: 002
Create Date: 2024-12-15
"""

import secrets

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def generate_token():
    """Generate a secure token."""
    return secrets.token_urlsafe(32)


def upgrade() -> None:
    # Add mod_token column (nullable first for existing rows)
    op.add_column("users", sa.Column("mod_token", sa.String(64), nullable=True))

    # Generate tokens for existing users
    connection = op.get_bind()
    users = connection.execute(sa.text("SELECT id FROM users")).fetchall()
    for (user_id,) in users:
        token = generate_token()
        connection.execute(
            sa.text("UPDATE users SET mod_token = :token WHERE id = :id"),
            {"token": token, "id": user_id},
        )

    # Make column non-nullable and add unique constraint
    op.alter_column("users", "mod_token", nullable=False)
    op.create_unique_constraint("uq_users_mod_token", "users", ["mod_token"])
    op.create_index("idx_users_mod_token", "users", ["mod_token"])


def downgrade() -> None:
    op.drop_index("idx_users_mod_token", table_name="users")
    op.drop_constraint("uq_users_mod_token", "users", type_="unique")
    op.drop_column("users", "mod_token")
