"""Add account email and password recovery fields."""

from alembic import op
import sqlalchemy as sa

revision = '8af4ec4cf103'
down_revision = 'd94b57c23e45'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users", sa.Column("email", sa.String(254), nullable=True)
    )
    op.create_unique_constraint("uq_users_email", "users", ["email"])

    op.add_column(
        "users",
        sa.Column(
            "auth_version", sa.Integer(),
            nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "users",
        sa.Column("password_reset_digest", sa.String(64), nullable=True),
    )
    op.create_unique_constraint(
        "uq_users_password_reset_digest",
        "users",
        ["password_reset_digest"],
    )
    op.add_column(
        "users",
        sa.Column(
            "password_reset_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "password_reset_requested_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade():
    op.drop_column("users", "password_reset_requested_at")
    op.drop_column("users", "password_reset_expires_at")
    op.drop_constraint(
        "uq_users_password_reset_digest", "users", type_="unique"
    )
    op.drop_column("users", "password_reset_digest")
    op.drop_column("users", "auth_version")
    op.drop_constraint("uq_users_email", "users", type_="unique")
    op.drop_column("users", "email")
