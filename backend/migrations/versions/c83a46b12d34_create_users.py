"""Create authentication users.

Revision ID: c83a46b12d34
Revises: b72f35a01c23
"""
from alembic import op
import sqlalchemy as sa

revision = "c83a46b12d34"
down_revision = "b72f35a01c23"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(),
            server_default=sa.true(), nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('admin', 'doctor', 'reviewer')",
            name="ck_users_role",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username", name="uq_users_username"),
    )


def downgrade():
    op.drop_table("users")
