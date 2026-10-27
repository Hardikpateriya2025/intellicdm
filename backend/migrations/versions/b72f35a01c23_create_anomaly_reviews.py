"""Create anomaly reviews."""

from alembic import op
import sqlalchemy as sa

revision = "b72f35a01c23"
down_revision = "a61e24f90b12"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "anomaly_reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("score_history_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("reviewer_name", sa.String(100), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('needs_investigation', "
            "'confirmed_data_error', "
            "'reviewed_no_correction_needed')",
            name="ck_anomaly_review_status",
        ),
        sa.ForeignKeyConstraint(
            ["score_history_id"],
            ["anomaly_score_history.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_anomaly_reviews_score_history_id",
        "anomaly_reviews",
        ["score_history_id"],
    )


def downgrade():
    op.drop_index(
        "ix_anomaly_reviews_score_history_id",
        table_name="anomaly_reviews",
    )
    op.drop_table("anomaly_reviews")
